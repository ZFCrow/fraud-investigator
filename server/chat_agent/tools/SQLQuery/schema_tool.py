# tools/SchemaTool.py
from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.tool import AgentTool
from server.chat_agent.tools.enums import ToolName


SCHEMA = """
Database schema (all tables live in the `shop` schema; search_path already includes it).
The store is "Kestrel Market", an online shop. Amounts are in USD.

Table: customers -- one row per account
- id (PK)
- email -- the customer's identity (e.g. alex.tan@mail.example)
- full_name
- country -- ISO 2-letter code of where the customer lives (SG, MY, AU, US, GB)
- created_at (timestamptz) -- when the account was created
- status -- active | suspended

Table: products
- id (PK)
- name
- category -- Electronics | Home | Fashion | Beauty | Books | Sports
- price (numeric)

Table: promo_codes
- code (PK) -- e.g. WELCOME50
- description
- discount_percent (int)
- one_per_customer (bool) -- true: each customer may redeem it once

Table: sessions -- one row per visit to the store
- id (PK, uuid)
- customer_id (FK -> customers.id) -- NULL = guest (no account)
- started_at, ended_at (timestamptz)
- device_id -- stable identifier of the browser/app install, e.g. dev-9b1becd2
- device_type -- desktop | mobile | tablet
- ip_address
- ip_country -- ISO 2-letter code geolocated from the IP

Table: events -- one row per thing that happened in a session
- id (PK)
- session_id (FK -> sessions.id)
- customer_id (FK -> customers.id) -- the account acted on; NULL for guests
- event_type -- LOGIN_SUCCESS | LOGIN_FAILED | PASSWORD_RESET | EMAIL_CHANGE | ADDRESS_CHANGE |
  PRODUCT_VIEW | ADD_TO_CART | PROMO_APPLIED | CHECKOUT_START | ORDER_PLACED | REFUND_REQUESTED
- event_time (timestamptz)
- product_id (FK -> products.id) -- set on PRODUCT_VIEW / ADD_TO_CART
- order_id (FK -> orders.id) -- set on ORDER_PLACED / REFUND_REQUESTED
- detail (text) -- e.g. "wrong password", the promo code applied, the new shipping address, the refund reason

Table: orders -- one row per placed order
- id (PK)
- customer_id (FK -> customers.id) -- NULL for guest checkouts
- session_id (FK -> sessions.id) -- the session the order was placed in
- guest_email -- set only on guest checkouts
- placed_at (timestamptz)
- total_amount (numeric) -- what was charged, after discount
- discount_amount (numeric)
- promo_code (FK -> promo_codes.code) -- NULL when no code was used
- status -- placed | shipped | delivered | cancelled
- ship_city, ship_country
- ship_address_hash -- the same physical address always has the same hash, whichever account ordered to it

Table: order_items
- id (PK)
- order_id (FK -> orders.id)
- product_id (FK -> products.id)
- quantity (int)
- unit_price (numeric)

Table: payment_attempts -- one row per card charge attempt
- id (PK)
- session_id (FK -> sessions.id)
- customer_id (FK -> customers.id) -- NULL for guests
- order_id (FK -> orders.id) -- the order it paid for; NULL when declined and no order followed
- attempted_at (timestamptz)
- amount (numeric)
- card_fingerprint -- the same card always has the same fingerprint, e.g. card_3f9a1c22b7d0
- card_last4, card_brand
- card_country -- ISO 2-letter code of the issuing country
- result -- approved | declined
- decline_reason -- insufficient_funds | incorrect_cvc | expired_card | invalid_card_number |
  do_not_honor | stolen_card | card_not_supported; NULL when approved

Table: refunds -- one row per refund request
- id (PK)
- order_id (FK -> orders.id)
- customer_id (FK -> customers.id)
- requested_at (timestamptz)
- amount (numeric)
- reason -- item_not_received | damaged | wrong_item | changed_mind
- status -- approved | rejected | pending

Relationships:
- sessions -> customers (N:1 via customer_id, nullable); join customers to get the email
- events, payment_attempts, orders -> sessions (N:1 via session_id)
- order_items -> orders, products; refunds -> orders

Important semantics:
- Nothing is pre-flagged. There is no "suspicious", "fraud" or "is_new_device" column: every
  finding has to be derived from the rows, and the answer should show the numbers it rests on.
- A guest has customer_id NULL on sessions, events, orders and payment_attempts. Use
  LEFT JOIN customers, never an inner join, when guests must stay in the result.
- device_id and ip_address live on sessions only. To know which device or IP an event,
  order or payment came from, join through session_id.
- A failed login is an events row with event_type = 'LOGIN_FAILED'; its customer_id is the
  account that was targeted.
- numeric columns: for display use ROUND(x::numeric, 2) or x::float. ROUND(value, 2) only
  exists for numeric -- ROUND(a_float, 2) is an error, so cast to numeric first.
- Baselines: when comparing one order or session against a customer's history, leave the
  case itself out of the average (e.g. AND o.id <> the order being judged, or
  placed_at < its placed_at). An average that includes the outlier hides it.

### Timezone
All timestamps are timestamptz (stored as UTC internally).
To get the SGT date use exactly this -- a single conversion only:
(placed_at AT TIME ZONE 'Asia/Singapore')::date
Never use double AT TIME ZONE -- it produces wrong dates for timestamptz columns.

### Investigation patterns
These are the usual ways each kind of abuse shows up. Adapt them; do not copy blindly.

New device or country for an account -- compare a session against the customer's earlier ones:
SELECT s.id, s.started_at, s.device_id, s.ip_country,
       NOT EXISTS (SELECT 1 FROM shop.sessions p
                   WHERE p.customer_id = s.customer_id AND p.device_id = s.device_id
                     AND p.started_at < s.started_at) AS first_time_device,
       NOT EXISTS (SELECT 1 FROM shop.sessions p
                   WHERE p.customer_id = s.customer_id AND p.ip_country = s.ip_country
                     AND p.started_at < s.started_at) AS first_time_country
FROM shop.sessions s
WHERE s.customer_id = :customer_id
ORDER BY s.started_at;
An account takeover typically looks like: first-time device and country, failed logins or a
PASSWORD_RESET, then an ADDRESS_CHANGE and an order far above the customer's usual total,
often on a card never used on the account before.

Card testing -- many low-value attempts across many cards from one session, device or IP:
SELECT pa.session_id, s.device_id, s.ip_address, s.ip_country,
       COUNT(*) AS attempts,
       COUNT(DISTINCT pa.card_fingerprint) AS distinct_cards,
       COUNT(*) FILTER (WHERE pa.result = 'declined') AS declined,
       MIN(pa.attempted_at) AS first_attempt, MAX(pa.attempted_at) AS last_attempt
FROM shop.payment_attempts pa
JOIN shop.sessions s ON s.id = pa.session_id
GROUP BY pa.session_id, s.device_id, s.ip_address, s.ip_country
HAVING COUNT(DISTINCT pa.card_fingerprint) >= 5
ORDER BY distinct_cards DESC;
An ordinary shopper uses one or two cards and is rarely declined.

Refund abuse -- refund rate per customer against everyone else:
SELECT c.email,
       COUNT(DISTINCT o.id) AS orders,
       COUNT(DISTINCT r.id) AS refunds,
       ROUND(COUNT(DISTINCT r.id)::numeric / COUNT(DISTINCT o.id), 2) AS refund_rate
FROM shop.customers c
JOIN shop.orders o ON o.customer_id = c.id
LEFT JOIN shop.refunds r ON r.order_id = o.id
GROUP BY c.email
HAVING COUNT(DISTINCT o.id) >= 3
ORDER BY refund_rate DESC;
Also look at whether one reason (e.g. item_not_received) dominates.

Shared device, address or card across accounts -- the sign of one person behind many accounts
(e.g. a one_per_customer promo code redeemed many times):
SELECT o.ship_address_hash,
       COUNT(DISTINCT o.customer_id) AS accounts,
       COUNT(*) AS orders,
       SUM(o.discount_amount)::float AS discount_taken
FROM shop.orders o
WHERE o.promo_code = :code
GROUP BY o.ship_address_hash
HAVING COUNT(DISTINCT o.customer_id) > 1;
The same shape works grouped by s.device_id (join sessions) or by pa.card_fingerprint
(join payment_attempts).

Credential stuffing -- one device or IP failing logins against many accounts:
SELECT s.ip_address, s.device_id,
       COUNT(DISTINCT e.customer_id) AS accounts_targeted,
       COUNT(*) FILTER (WHERE e.event_type = 'LOGIN_FAILED') AS failed_logins,
       COUNT(DISTINCT e.customer_id) FILTER (WHERE e.event_type = 'LOGIN_SUCCESS') AS accounts_entered
FROM shop.events e
JOIN shop.sessions s ON s.id = e.session_id
WHERE e.event_type IN ('LOGIN_FAILED', 'LOGIN_SUCCESS')
GROUP BY s.ip_address, s.device_id
HAVING COUNT(DISTINCT e.customer_id) >= 5
ORDER BY accounts_targeted DESC;
"""

class SQLSchemaTool(AgentTool):
    def __init__(
            self,
            tools_called: list[ToolCall] = None):

        super().__init__(ToolName.GET_SQL_SCHEMA, tools_called)

    async def __call__(self):

        return SCHEMA
