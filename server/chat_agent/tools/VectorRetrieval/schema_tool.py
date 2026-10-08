from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.tool import AgentTool
from server.chat_agent.tools.enums import ToolName

SCHEMA = """
## Vector Store Schema (Qdrant)

Each point in the vector store is one storefront session (one row of the `sessions` table)
with everything that happened in it: its events, payment attempts and the orders placed.

### Payload fields
- session_id (str) -- sessions.id
- customer_id (int) -- customers.id; null for a guest
- customer_email (str) -- the customer's email; null for a guest
- customer_name (str) -- full name; null for a guest
- is_guest (bool)
- session_start, session_end (datetime, GMT+8)
- device_id (str) -- e.g. dev-9b1becd2
- device_type (str) -- desktop | mobile | tablet
- ip_address (str)
- ip_country (str) -- ISO 2-letter code
- event_count (int) -- number of events in the session
- payment_attempt_count (int)
- declined_payment_count (int)
- distinct_card_count (int) -- how many different cards were tried in the session
- order_count (int)
- order_total (float) -- sum of the orders placed in the session, USD
- text (str) -- the session written out in time order (logins, account changes, products
  viewed, payment attempts with card and outcome, orders with items and shipping address).
  This is what the search matches against.

## Available Filters
When calling query_vector_store, you can optionally pass filters:
- filter_customer_email (str) -- sessions of one customer, by exact email e.g. "alex.tan@mail.example"
- filter_device_id (str) -- sessions from one device e.g. "dev-9b1becd2"
- filter_ip_country (str) -- sessions from one country, ISO 2-letter code e.g. "RO"
- filter_start_date (str, ISO format GMT+8) -- sessions starting after this date
- filter_end_date (str, ISO format GMT+8) -- sessions starting before this date
- filter_event_count (int) -- sessions with at least this many events
- filter_declined_payments (int) -- sessions with at least this many declined payment attempts

### Timezone
All datetime fields are stored in GMT+8. When filtering by filter_start_date and
filter_end_date, pass GMT+8 ISO format strings.

## Behaviour
- A guest session has no customer_email: never set filter_customer_email to find guests;
  use the other filters (device, country, declined payments) instead.
- The search is semantic + keyword over the session text. It finds sessions that read like
  the query; it does not count or rank. Use query_sql for any number.

## Example usage
- "what was alex.tan@mail.example doing last week" -> filter_customer_email + filter_start_date
- "sessions with lots of declined cards" -> filter_declined_payments = 5
- "logins from Romania" -> filter_ip_country = "RO"
- "everything from device dev-9b1becd2" -> filter_device_id = "dev-9b1becd2"

## Example payload
{"session_id":"0b6f6a3e-6d0c-4c0e-9a57-1d2b7a7c9f10","customer_id":17,
"customer_email":"alex.tan@mail.example","customer_name":"Alex Tan","is_guest":false,
"session_start":"2026-10-01T20:14:05+08:00","session_end":"2026-10-01T20:21:48+08:00",
"device_id":"dev-4f2a9c10","device_type":"mobile","ip_address":"198.51.100.24","ip_country":"SG",
"event_count":7,"payment_attempt_count":1,"declined_payment_count":0,"distinct_card_count":1,
"order_count":1,"order_total":95.0,
"text":"Customer Alex Tan (alex.tan@mail.example), customer id 17, home country SG, account created 2025-03-02. Session 0b6f6a3e-... from 2026-10-01 20:14:05 to 20:21:48 (GMT+8) on mobile device dev-4f2a9c10, IP 198.51.100.24 (SG). 7 events, 1 payment attempts (1 approved, 0 declined) across 1 distinct card, 1 order totalling $95.00.\n20:14:19 LOGIN_SUCCESS\n20:15:02 PRODUCT_VIEW 'Merino Crew Sweater'\n20:15:20 ADD_TO_CART 'Merino Crew Sweater'\n20:20:11 CHECKOUT_START\n20:20:40 PAYMENT APPROVED $95.00 on Visa card ending 4421 (fingerprint card_3f9a1c22b7d0, issued in SG), for order 88\n20:20:42 ORDER_PLACED order 88 for $95.00 (1 x Merino Crew Sweater), shipping to Singapore, SG (address addr-1c9e77a0b2)"}
"""

class SessionVectorStoreSchemaTool(AgentTool):
    def __init__(
            self,
            tools_called: list[ToolCall] = None):

        super().__init__(ToolName.GET_SESSION_VECTOR_HYBRID_SCHEMA, tools_called)
 
    async def __call__(self) -> str:
        return SCHEMA




