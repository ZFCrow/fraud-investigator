"""
Synthetic storefront generator for the shop tables (customers, products, promo_codes,
sessions, events, orders, order_items, payment_attempts, refunds).

Everything here is fictional: the store ("Kestrel Market"), people, devices, cards
and IPs (RFC 5737 TEST-NET ranges, .example mail domains) are invented. The output is
a plain SQL file that can be loaded into the `shop` database:

    python data/synthetic/generate.py                     # writes data/synthetic/seed.sql
    docker exec hack_db psql -U shop -d shop -f /app/data/synthetic/seed.sql

Output is deterministic for a given --seed and --end. On top of ordinary shopping
activity, a handful of scripted fraud incidents are planted so the agent has something
real to find -- see SCENARIOS.md for the ground truth. Nothing in the data is flagged
as suspicious; every incident has to be derived from the rows.
"""
import argparse
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORE = "Kestrel Market"
MAIL_DOMAINS = ["mail.example", "inbox.example", "post.example"]

# home country -> (weight, cities, IP prefix inside TEST-NET-2)
COUNTRIES = {
    "SG": (10, ["Singapore"], "198.51.100."),
    "MY": (3, ["Kuala Lumpur", "Penang", "Johor Bahru"], "198.51.100."),
    "AU": (3, ["Sydney", "Melbourne", "Brisbane"], "198.51.100."),
    "US": (3, ["Austin", "Seattle", "Chicago"], "198.51.100."),
    "GB": (2, ["London", "Manchester"], "198.51.100."),
}

FIRST = ["Alex", "Priya", "Daniel", "Mei", "Samuel", "Aisha", "Tom", "Lena", "Omar", "Grace",
         "Ravi", "Hannah", "Kenji", "Sofia", "Ethan", "Nadia", "Lucas", "Chloe", "Victor", "Ingrid",
         "Marcus", "Yuki", "Farah", "Owen", "Jia", "Arjun", "Elena", "Noah", "Siti", "Liam"]
LAST = ["Tan", "Rivera", "Okafor", "Lindqvist", "Haddad", "Novak", "Brennan", "Iyer", "Moreau",
        "Castillo", "Ng", "Whitaker", "Sato", "Adeyemi", "Kowalski", "Webb", "Lau", "Fischer",
        "Duarte", "Kaur", "Petrov", "Nakamura", "Osei", "Hale", "Lim", "Mehta", "Rossi", "Clarke"]

# category -> [(name, price)]
CATALOGUE = {
    "Electronics": [("Aero 14 Laptop", 1299.00), ("Nova X Phone", 899.00), ("Slate 11 Tablet", 549.00),
                    ("Pulse Wireless Headphones", 199.00), ("Orbit Smartwatch", 329.00),
                    ("Lumen Mirrorless Camera", 749.00), ("Arc Game Console", 499.00),
                    ("Bolt Power Bank", 39.00), ("USB-C Cable 2m", 12.00)],
    "Home":        [("Ceramic Pour-Over Set", 48.00), ("Linen Duvet Cover", 119.00), ("Cast Iron Skillet", 65.00),
                    ("Desk Lamp", 54.00), ("Scented Candle Trio", 28.00), ("Bamboo Cutting Board", 24.00)],
    "Fashion":     [("Merino Crew Sweater", 95.00), ("Canvas Tote Bag", 32.00), ("Leather Belt", 45.00),
                    ("Trail Running Shoes", 139.00), ("Rain Jacket", 159.00), ("Cotton T-Shirt 3-Pack", 36.00)],
    "Beauty":      [("Vitamin C Serum", 42.00), ("Daily Sunscreen SPF50", 22.00), ("Beard Trimmer", 59.00),
                    ("Hair Dryer", 89.00)],
    "Books":       [("The Quiet Ledger (Hardcover)", 27.00), ("Field Guide to Night Skies", 34.00),
                    ("Cooking for Two", 25.00), ("Sticker Pack", 1.50)],
    "Sports":      [("Yoga Mat", 38.00), ("Adjustable Dumbbell", 189.00), ("Insulated Water Bottle", 29.00),
                    ("Cycling Helmet", 79.00)],
}

PROMOS = [
    ("WELCOME50", "50% off a new customer's first order", 50, True),
    ("SAVE10", "10% off any order", 10, False),
    ("MIDYEAR15", "15% off orders during the mid-year sale", 15, False),
]

CARD_BRANDS = ["Visa", "Mastercard", "Amex"]
NORMAL_DECLINES = ["insufficient_funds", "incorrect_cvc", "expired_card"]
TESTING_DECLINES = ["invalid_card_number", "do_not_honor", "stolen_card", "incorrect_cvc", "card_not_supported"]
REFUND_REASONS = ["damaged", "wrong_item", "changed_mind"]


@dataclass
class Card:
    fingerprint: str
    last4: str
    brand: str
    country: str


@dataclass
class Address:
    city: str
    country: str
    hash: str


@dataclass
class Shopper:
    id: int
    name: str
    email: str
    country: str
    created_at: datetime
    address: Address
    devices: list = field(default_factory=list)  # (device_id, device_type, ip)
    cards: list = field(default_factory=list)


class Generator:
    def __init__(self, seed: int, end: datetime, days: int):
        self.rng = random.Random(seed)
        self.end = end
        self.start = end - timedelta(days=days)
        self.days = days

        self.customers: list[Shopper] = []
        self.products: list[dict] = []
        self.sessions: list[dict] = []
        self.events: list[dict] = []
        self.orders: list[dict] = []
        self.order_items: list[dict] = []
        self.payments: list[dict] = []
        self.refunds: list[dict] = []
        self.notes: list = []  # callables: evaluated after finalise() renumbers the ids
        self._names: set[tuple] = set()

    # ------------------------------------------------------------------ helpers
    def hex(self, n: int) -> str:
        return "".join(self.rng.choice("0123456789abcdef") for _ in range(n))

    def uuid(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def new_card(self, country: str) -> Card:
        return Card(f"card_{self.hex(12)}", f"{self.rng.randint(0, 9999):04d}", self.rng.choice(CARD_BRANDS), country)

    def new_address(self, country: str, city: str | None = None) -> Address:
        return Address(city or self.rng.choice(COUNTRIES[country][1]), country, f"addr-{self.hex(10)}")

    def product(self, name: str) -> dict:
        return next(p for p in self.products if p["name"] == name)

    def new_shopper(self, country: str, created_at: datetime) -> Shopper:
        while True:
            first, last = self.rng.choice(FIRST), self.rng.choice(LAST)
            email = f"{first}.{last}@{self.rng.choice(MAIL_DOMAINS)}".lower()
            # unique full names, not just emails: two "Samuel Hale"s would make every
            # lookup by name ambiguous
            if (first, last) not in self._names:
                break
        self._names.add((first, last))
        shopper = Shopper(len(self.customers) + 1, f"{first} {last}", email, country, created_at,
                          self.new_address(country))
        prefix = COUNTRIES[country][2]
        for _ in range(self.rng.choice([1, 1, 2])):
            shopper.devices.append((f"dev-{self.hex(8)}", self.rng.choice(["desktop", "mobile", "mobile", "tablet"]),
                                    prefix + str(self.rng.randint(2, 254))))
        for _ in range(self.rng.choice([1, 1, 2])):
            shopper.cards.append(self.new_card(country))
        self.customers.append(shopper)
        return shopper

    def daytime(self, day: datetime) -> datetime:
        """A moment during waking hours in Singapore time on the given UTC day."""
        hour_sgt = self.rng.choices(range(7, 24), weights=[1, 2, 3, 3, 3, 4, 4, 3, 3, 3, 3, 4, 5, 6, 6, 4, 2])[0]
        return (day.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(hours=hour_sgt - 8, minutes=self.rng.randint(0, 59), seconds=self.rng.randint(0, 59)))

    # ------------------------------------------------------------------ row builders
    def open_session(self, shopper: Shopper | None, at: datetime, device: tuple, ip_country: str) -> dict:
        device_id, device_type, ip = device
        session = {"id": self.uuid(), "customer_id": shopper.id if shopper else None, "started_at": at,
                   "ended_at": at, "device_id": device_id, "device_type": device_type,
                   "ip_address": ip, "ip_country": ip_country, "_clock": at}
        self.sessions.append(session)
        return session

    def tick(self, session: dict, lo: int = 5, hi: int = 90) -> datetime:
        session["_clock"] += timedelta(seconds=self.rng.randint(lo, hi))
        session["ended_at"] = session["_clock"]
        return session["_clock"]

    def event(self, session: dict, event_type: str, customer_id=..., product: dict | None = None,
              order: dict | None = None, detail: str | None = None, gap: tuple = (5, 90)) -> dict:
        row = {"id": len(self.events) + 1, "session_id": session["id"],
               "customer_id": session["customer_id"] if customer_id is ... else customer_id,
               "event_type": event_type, "event_time": self.tick(session, *gap),
               "product_id": product["id"] if product else None,
               "order_id": order["id"] if order else None, "detail": detail}
        self.events.append(row)
        return row

    def pay(self, session: dict, amount: float, card: Card, approved: bool, reason: str | None = None,
            gap: tuple = (8, 40)) -> dict:
        row = {"id": len(self.payments) + 1, "session_id": session["id"], "customer_id": session["customer_id"],
               "order_id": None, "attempted_at": self.tick(session, *gap), "amount": round(amount, 2),
               "card_fingerprint": card.fingerprint, "card_last4": card.last4, "card_brand": card.brand,
               "card_country": card.country, "result": "approved" if approved else "declined",
               "decline_reason": None if approved else reason}
        self.payments.append(row)
        return row

    def place_order(self, session: dict, basket: list[tuple], address: Address, payment: dict,
                    promo: str | None = None, guest_email: str | None = None) -> dict:
        """basket: [(product, quantity)]. Records the order, its items and the ORDER_PLACED event."""
        subtotal = sum(p["price"] * q for p, q in basket)
        percent = next((pc for code, _, pc, _ in PROMOS if code == promo), 0)
        discount = round(subtotal * percent / 100, 2)
        order = {"id": len(self.orders) + 1, "customer_id": session["customer_id"], "session_id": session["id"],
                 "guest_email": guest_email, "placed_at": None, "total_amount": round(subtotal - discount, 2),
                 "discount_amount": discount, "promo_code": promo, "status": "placed",
                 "ship_city": address.city, "ship_country": address.country, "ship_address_hash": address.hash}
        self.orders.append(order)
        for p, q in basket:
            self.order_items.append({"id": len(self.order_items) + 1, "order_id": order["id"],
                                     "product_id": p["id"], "quantity": q, "unit_price": p["price"]})
        payment["order_id"] = order["id"]
        order["placed_at"] = self.event(session, "ORDER_PLACED", order=order, gap=(1, 4))["event_time"]
        return order

    def basket_total(self, basket: list[tuple], promo: str | None = None) -> float:
        subtotal = sum(p["price"] * q for p, q in basket)
        percent = next((pc for code, _, pc, _ in PROMOS if code == promo), 0)
        return round(subtotal - round(subtotal * percent / 100, 2), 2)

    def browse(self, session: dict, wanted: list[dict] | None = None, affordable: bool = True) -> list[tuple]:
        """PRODUCT_VIEW / ADD_TO_CART events; returns the basket."""
        pool = [p for p in self.products if p["price"] <= 250] if affordable else self.products
        basket = []
        for product in wanted or self.rng.sample(pool, self.rng.randint(1, 5)):
            self.event(session, "PRODUCT_VIEW", product=product)
            if wanted or self.rng.random() < 0.45:
                self.event(session, "ADD_TO_CART", product=product, gap=(3, 30))
                basket.append((product, 1))
        return basket

    def shopping_session(self, shopper: Shopper, at: datetime, promo: str | None = None,
                         basket_products: list[dict] | None = None, must_buy: bool = False,
                         device: tuple | None = None, address: Address | None = None,
                         card: Card | None = None) -> dict | None:
        """An ordinary logged-in visit. Returns the order if one was placed."""
        session = self.open_session(shopper, at, device or self.rng.choice(shopper.devices), shopper.country)
        if self.rng.random() < 0.05:
            self.event(session, "LOGIN_FAILED", detail="wrong password", gap=(2, 10))
        self.event(session, "LOGIN_SUCCESS", gap=(4, 20))
        basket = self.browse(session, basket_products)
        if not basket or not (must_buy or self.rng.random() < 0.6):
            return None
        self.event(session, "CHECKOUT_START", gap=(10, 60))
        if promo is None and self.rng.random() < 0.1:
            promo = "SAVE10"
        if promo:
            self.event(session, "PROMO_APPLIED", detail=promo, gap=(4, 20))
        total = self.basket_total(basket, promo)
        card = card or self.rng.choice(shopper.cards)
        if self.rng.random() < 0.06:
            self.pay(session, total, card, False, self.rng.choice(NORMAL_DECLINES))
            if not must_buy and self.rng.random() < 0.2:
                return None  # gave up after the decline
        payment = self.pay(session, total, card, True)
        return self.place_order(session, basket, address or shopper.address, payment, promo)

    def refund(self, shopper: Shopper, order: dict, at: datetime, reason: str, status: str = "approved",
               device: tuple | None = None) -> None:
        session = self.open_session(shopper, at, device or self.rng.choice(shopper.devices), shopper.country)
        self.event(session, "LOGIN_SUCCESS", gap=(4, 20))
        self.refunds.append({"id": len(self.refunds) + 1, "order_id": order["id"], "customer_id": shopper.id,
                             "requested_at": None, "amount": order["total_amount"], "reason": reason,
                             "status": status})
        self.refunds[-1]["requested_at"] = self.event(
            session, "REFUND_REQUESTED", order=order, detail=reason, gap=(20, 120))["event_time"]

    # ------------------------------------------------------------------ world
    def build_catalogue(self):
        for category, items in CATALOGUE.items():
            for name, price in items:
                self.products.append({"id": len(self.products) + 1, "name": name, "category": category,
                                      "price": price})

    def build_customers(self, n: int = 90):
        countries = list(COUNTRIES)
        weights = [COUNTRIES[c][0] for c in countries]
        for i in range(n):
            # most accounts are long-standing; a few signed up inside the history window
            age_days = self.rng.randint(1, self.days - 2) if i >= n - 8 else self.rng.randint(self.days + 10, 900)
            created = self.daytime(self.end - timedelta(days=age_days))
            self.new_shopper(self.rng.choices(countries, weights)[0], created)

    def normal_activity(self):
        for shopper in list(self.customers):
            first_day = max(self.start, shopper.created_at)
            span = max(1, (self.end - first_day).days - 1)
            new_account = shopper.created_at > self.start
            visits = sorted(self.rng.sample(range(span), min(span, self.rng.randint(2, 7))))
            used_welcome = False
            for offset in visits:
                at = self.daytime(first_day + timedelta(days=offset + (1 if new_account else 0)))
                if at >= self.end - timedelta(hours=3) or at <= shopper.created_at:
                    continue
                promo = "WELCOME50" if new_account and not used_welcome and self.rng.random() < 0.7 else None
                order = self.shopping_session(shopper, at, promo=promo)
                if order and promo:
                    used_welcome = True
                # an occasional, ordinary refund a few days later
                if order and self.rng.random() < 0.04:
                    later = self.daytime(at + timedelta(days=self.rng.randint(3, 6)))
                    if later < self.end - timedelta(hours=3):
                        self.refund(shopper, order, later, self.rng.choice(REFUND_REASONS))

        # ordinary account maintenance, so these events are not a signal on their own
        for shopper in self.rng.sample(self.customers[:60], 3):
            session = self.open_session(shopper, self.daytime(self.end - timedelta(days=self.rng.randint(4, 25))),
                                        self.rng.choice(shopper.devices), shopper.country)
            self.event(session, "LOGIN_FAILED", detail="wrong password", gap=(2, 10))
            self.event(session, "PASSWORD_RESET", detail="reset link requested and completed", gap=(60, 240))
            self.event(session, "LOGIN_SUCCESS", gap=(5, 20))
        for shopper in self.rng.sample(self.customers[:60], 2):
            session = self.open_session(shopper, self.daytime(self.end - timedelta(days=self.rng.randint(4, 25))),
                                        self.rng.choice(shopper.devices), shopper.country)
            self.event(session, "LOGIN_SUCCESS", gap=(4, 20))
            shopper.address = self.new_address(shopper.country)
            self.event(session, "ADDRESS_CHANGE", gap=(30, 120),
                       detail=f"default shipping address changed to {shopper.address.city}, {shopper.address.country}")

        # guests: browsing and some guest checkouts
        countries = list(COUNTRIES)
        for _ in range(45):
            country = self.rng.choices(countries, [COUNTRIES[c][0] for c in countries])[0]
            at = self.daytime(self.start + timedelta(days=self.rng.randint(0, self.days - 1)))
            if at >= self.end - timedelta(hours=3):
                continue
            device = (f"dev-{self.hex(8)}", self.rng.choice(["desktop", "mobile"]),
                      COUNTRIES[country][2] + str(self.rng.randint(2, 254)))
            session = self.open_session(None, at, device, country)
            basket = self.browse(session)
            if basket and self.rng.random() < 0.45:
                self.event(session, "CHECKOUT_START", gap=(10, 60))
                payment = self.pay(session, self.basket_total(basket), self.new_card(country), True)
                email = f"{self.rng.choice(FIRST)}{self.rng.randint(10, 99)}@{self.rng.choice(MAIL_DOMAINS)}".lower()
                self.place_order(session, basket, self.new_address(country), payment, guest_email=email)

    # ------------------------------------------------------------------ planted incidents
    def scenarios(self):
        self.account_takeover()
        self.card_testing()
        self.refund_abuse()
        self.promo_sharing()
        self.credential_stuffing()

    def account_takeover(self):
        # an established Singapore customer with ordinary history
        victim = next(c for c in self.customers if c.country == "SG" and c.created_at < self.start
                      and sum(1 for o in self.orders if o["customer_id"] == c.id) >= 2)
        usual = max(o["total_amount"] for o in self.orders if o["customer_id"] == victim.id)
        # 03:14 Singapore time, three nights ago
        at = (self.end - timedelta(days=3)).replace(hour=19, minute=14, second=9, microsecond=0)
        device = (f"dev-{self.hex(8)}", "desktop", "203.0.113.77")
        session = self.open_session(victim, at, device, "RO")
        for _ in range(4):
            self.event(session, "LOGIN_FAILED", detail="wrong password", gap=(3, 9))
        self.event(session, "PASSWORD_RESET", detail="reset link requested and completed", gap=(40, 70))
        self.event(session, "LOGIN_SUCCESS", gap=(5, 12))
        drop = Address("Bucharest", "RO", f"addr-{self.hex(10)}")
        self.event(session, "ADDRESS_CHANGE", gap=(20, 40),
                   detail=f"default shipping address changed to {drop.city}, {drop.country}")
        basket = [(self.product("Aero 14 Laptop"), 2), (self.product("Nova X Phone"), 1),
                  (self.product("Lumen Mirrorless Camera"), 1)]
        for product, _ in basket:
            self.event(session, "PRODUCT_VIEW", product=product, gap=(5, 15))
            self.event(session, "ADD_TO_CART", product=product, gap=(2, 6))
        self.event(session, "CHECKOUT_START", gap=(5, 15))
        stolen = self.new_card("RO")
        payment = self.pay(session, self.basket_total(basket), stolen, True)
        order = self.place_order(session, basket, drop, payment)
        minutes = round((order["placed_at"] - at).total_seconds() / 60)
        self.notes.append(lambda: (
            f"**Account takeover.** `{victim.email}` (home country SG, account since {victim.created_at:%Y-%m-%d}, "
            f"largest earlier order ${usual:.2f}) was logged into at {at + timedelta(hours=8):%Y-%m-%d %H:%M} SGT from "
            f"device `{device[0]}` at `{device[2]}` (RO) -- a device and country never seen on the account. The session "
            f"shows 4 failed logins, a password reset, a successful login, a shipping-address change to Bucharest, RO, "
            f"and order {order['id']} for ${order['total_amount']:.2f} (2 laptops, a phone, a camera) paid with a "
            f"Romanian-issued card never used on the account before, all within {minutes} minutes."))

    def card_testing(self):
        # a guest on one device working through a list of stolen card numbers
        at = (self.end - timedelta(days=2)).replace(hour=16, minute=40, second=0, microsecond=0)
        device = (f"dev-{self.hex(8)}", "desktop", "192.0.2.146")
        session = self.open_session(None, at, device, "BR")
        sticker = self.product("Sticker Pack")
        self.event(session, "PRODUCT_VIEW", product=sticker, gap=(3, 8))
        self.event(session, "ADD_TO_CART", product=sticker, gap=(2, 5))
        self.event(session, "CHECKOUT_START", gap=(4, 10))
        email = "bulkbuyer77@quickmail.example"
        drop = Address("Miami", "US", f"addr-{self.hex(10)}")
        cards = [self.new_card(self.rng.choice(["US", "US", "US", "CA", "GB", "DE"])) for _ in range(40)]
        live: list[Card] = []
        small = 0
        for i, card in enumerate(cards):
            works = i in (6, 13, 19, 27, 33, 38)  # the few numbers that are still live
            payment = self.pay(session, sticker["price"], card, works,
                               None if works else self.rng.choice(TESTING_DECLINES), gap=(6, 16))
            if works:
                live.append(card)
                small += 1
                self.place_order(session, [(sticker, 1)], drop, payment, guest_email=email)
            elif self.rng.random() < 0.12:
                # a quick retry of the same number
                self.pay(session, sticker["price"], card, False, self.rng.choice(TESTING_DECLINES), gap=(3, 8))
        testing_minutes = round((session["_clock"] - at).total_seconds() / 60)
        testing = [p for p in self.payments if p["session_id"] == session["id"]]
        # cash out with two of the cards that passed
        big = []
        for card, name in ((live[1], "Nova X Phone"), (live[4], "Aero 14 Laptop")):
            product = self.product(name)
            self.event(session, "PRODUCT_VIEW", product=product, gap=(8, 20))
            self.event(session, "ADD_TO_CART", product=product, gap=(2, 6))
            self.event(session, "CHECKOUT_START", gap=(4, 10))
            payment = self.pay(session, product["price"], card, True)
            big.append(self.place_order(session, [(product, 1)], drop, payment, guest_email=email))
        declined = sum(1 for p in testing if p["result"] == "declined")
        self.notes.append(lambda: (
            f"**Card testing.** A guest session on device `{device[0]}` at `{device[2]}` (BR) starting "
            f"{at + timedelta(hours=8):%Y-%m-%d %H:%M} SGT made {len(testing)} payment attempts of "
            f"${sticker['price']:.2f} (a Sticker Pack) across {len(cards)} distinct cards in {testing_minutes} minutes: "
            f"{declined} declined, {small} approved. Two of the cards that passed were then used for order "
            f"{big[0]['id']} (${big[0]['total_amount']:.2f}) and order {big[1]['id']} "
            f"(${big[1]['total_amount']:.2f}), all shipped to the same Miami, US address under guest email `{email}`."))

    def refund_abuse(self):
        abuser = self.new_shopper("SG", self.daytime(self.end - timedelta(days=140)))
        device = abuser.devices[0]
        pool = [p for p in self.products if 80 <= p["price"] <= 250]
        orders = []
        for i in range(11):
            at = self.daytime(self.end - timedelta(days=26 - i * 2))
            orders.append((at, self.shopping_session(abuser, at, basket_products=[self.rng.choice(pool)],
                                                     must_buy=True, device=device)))
        claimed = 0
        for i, (at, order) in enumerate(orders):
            if i in (3, 8):
                continue  # two orders kept, the rest claimed as never delivered
            later = self.daytime(at + timedelta(days=self.rng.randint(2, 4)))
            if later >= self.end - timedelta(hours=3):
                continue
            claimed += 1
            self.refund(abuser, order, later, "item_not_received",
                        "pending" if later > self.end - timedelta(days=3) else "approved", device=device)
        value = sum(r["amount"] for r in self.refunds if r["customer_id"] == abuser.id)
        others = [r for r in self.refunds if r["customer_id"] != abuser.id]
        other_orders = sum(1 for o in self.orders if o["customer_id"] not in (None, abuser.id))
        self.notes.append(lambda: (
            f"**Refund abuse.** `{abuser.email}` placed {len(orders)} orders in the last 26 days and requested a "
            f"refund on {claimed} of them, every one with reason `item_not_received`, worth ${value:.2f} in total. "
            f"Across all other customers there are {len(others)} refund requests on {other_orders} orders, with "
            f"reasons like damaged / wrong_item / changed_mind."))

    def promo_sharing(self):
        # one person, twelve fresh accounts, one device and one delivery address
        device = (f"dev-{self.hex(8)}", "mobile", "198.51.100.212")
        home = Address("Singapore", "SG", f"addr-{self.hex(10)}")
        cards = [self.new_card("SG") for _ in range(3)]
        pool = [p for p in self.products if 140 <= p["price"] <= 350]
        accounts, saved = [], 0.0
        for i in range(12):
            created = self.daytime(self.end - timedelta(days=9 - (i * 2) // 3))
            account = self.new_shopper("SG", created)
            account.devices, account.cards, account.address = [device], cards, home
            order = self.shopping_session(account, created + timedelta(minutes=self.rng.randint(3, 12)),
                                          promo="WELCOME50", basket_products=[self.rng.choice(pool)],
                                          must_buy=True, device=device, address=home, card=cards[i % 3])
            accounts.append(account)
            saved += order["discount_amount"]
        self.notes.append(lambda: (
            f"**Promo code shared across accounts.** `WELCOME50` (50% off, one per customer) was redeemed by "
            f"{len(accounts)} accounts created within the last 9 days (e.g. `{accounts[0].email}`, "
            f"`{accounts[1].email}`, `{accounts[2].email}`). All {len(accounts)} placed their one order from the same "
            f"device `{device[0]}` at `{device[2]}`, shipped to the same Singapore address "
            f"(`{home.hash}`), and paid with the same 3 cards. Total discount taken: ${saved:.2f}."))

    def credential_stuffing(self):
        # one IP trying leaked passwords against many accounts
        at = (self.end - timedelta(days=5)).replace(hour=21, minute=0, second=0, microsecond=0)
        device = (f"dev-{self.hex(8)}", "desktop", "203.0.113.201")
        targets = self.rng.sample([c for c in self.customers if c.created_at < self.start], 26)
        breached, failed, clock = [], 0, at
        for i, target in enumerate(targets):
            session = self.open_session(target, clock, device, "VN")
            tries = self.rng.randint(2, 4)
            for _ in range(tries):
                self.event(session, "LOGIN_FAILED", detail="wrong password", gap=(2, 6))
            failed += tries
            if i in (9, 21):
                self.event(session, "LOGIN_SUCCESS", gap=(2, 6))
                breached.append(target)
            clock = session["_clock"] + timedelta(seconds=self.rng.randint(15, 45))
        minutes = round((clock - at).total_seconds() / 60)
        self.notes.append(lambda: (
            f"**Credential stuffing.** Starting {at + timedelta(hours=8):%Y-%m-%d %H:%M} SGT, device `{device[0]}` at "
            f"`{device[2]}` (VN) tried to log into {len(targets)} different customer accounts in {minutes} minutes: "
            f"{failed} failed logins in total. Two accounts were entered -- `{breached[0].email}` and "
            f"`{breached[1].email}` -- and nothing further was done in those sessions."))

    # ------------------------------------------------------------------ output
    def finalise(self):
        """Order status from age, and ids in time order (nicer to read, and what a real system would have)."""
        for order in self.orders:
            age = self.end - order["placed_at"]
            order["status"] = "delivered" if age > timedelta(days=5) else "shipped" if age > timedelta(days=2) else "placed"

        def renumber(rows, key, references=()):
            mapping = {}
            for new_id, row in enumerate(sorted(rows, key=lambda r: (r[key], r["id"])), 1):
                mapping[row["id"]] = new_id
            for row in rows:
                row["id"] = mapping[row["id"]]
            for other_rows, column in references:
                for row in other_rows:
                    if row[column] is not None:
                        row[column] = mapping[row[column]]
            rows.sort(key=lambda r: r["id"])

        renumber(self.orders, "placed_at", [(self.order_items, "order_id"), (self.payments, "order_id"),
                                            (self.refunds, "order_id"), (self.events, "order_id")])
        renumber(self.events, "event_time")
        renumber(self.payments, "attempted_at")
        renumber(self.refunds, "requested_at")
        self.order_items.sort(key=lambda r: (r["order_id"], r["id"]))
        for new_id, row in enumerate(self.order_items, 1):
            row["id"] = new_id
        self.sessions.sort(key=lambda r: r["started_at"])

    def to_sql(self) -> str:
        def lit(v):
            if v is None:
                return "NULL"
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, float):
                return f"{v:.2f}"
            if isinstance(v, int):
                return str(v)
            if isinstance(v, datetime):
                return f"'{v.isoformat()}'"
            return "'" + str(v).replace("'", "''") + "'"

        def inserts(table, rows, cols, chunk=500):
            out = []
            for i in range(0, len(rows), chunk):
                values = ",\n".join("(" + ",".join(lit(r[c]) for c in cols) + ")" for r in rows[i:i + chunk])
                out.append(f"INSERT INTO shop.{table} ({','.join(cols)}) VALUES\n{values};")
            return "\n".join(out)

        customers = [{"id": c.id, "email": c.email, "full_name": c.name, "country": c.country,
                      "created_at": c.created_at, "status": "active"} for c in self.customers]
        promos = [{"code": c, "description": d, "discount_percent": p, "one_per_customer": o} for c, d, p, o in PROMOS]
        session_cols = [c for c in self.sessions[0] if not c.startswith("_")]
        return "\n\n".join([
            f"-- Synthetic storefront data ({STORE}) generated by data/synthetic/generate.py -- fictional, safe to publish.",
            "BEGIN;",
            "TRUNCATE shop.refunds, shop.payment_attempts, shop.order_items, shop.events, shop.orders, "
            "shop.sessions, shop.promo_codes, shop.products, shop.customers RESTART IDENTITY CASCADE;",
            inserts("customers", customers, list(customers[0])),
            inserts("products", self.products, list(self.products[0])),
            inserts("promo_codes", promos, list(promos[0])),
            inserts("sessions", self.sessions, session_cols),
            inserts("orders", self.orders, list(self.orders[0])),
            inserts("order_items", self.order_items, list(self.order_items[0])),
            inserts("payment_attempts", self.payments, list(self.payments[0])),
            inserts("refunds", self.refunds, list(self.refunds[0])),
            inserts("events", self.events, list(self.events[0])),
            "COMMIT;",
        ]) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=30, help="how many days of history to generate")
    parser.add_argument("--end", type=str, default=None,
                        help="ISO date the history ends on (default: now). Must be in the past for ingestion.")
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("seed.sql"))
    args = parser.parse_args()

    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end else \
        datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)

    g = Generator(seed=args.seed, end=end, days=args.days)
    g.build_catalogue()
    g.build_customers()
    g.normal_activity()
    g.scenarios()
    g.finalise()
    args.out.write_text(g.to_sql(), encoding="utf-8", newline="\n")
    scenarios = args.out.with_name("SCENARIOS.md")
    scenarios.write_text(
        f"# Planted scenarios (seed {args.seed}, history ends {end:%Y-%m-%d %H:%M} UTC)\n\n"
        "Generated by `generate.py` alongside `seed.sql`; regenerate both together. Everything else in the "
        "dataset is ordinary shopping: logins, browsing, orders, the occasional declined card, password reset, "
        "address change and refund.\n\n"
        + "\n".join(f"{i}. {n()}" for i, n in enumerate(g.notes, 1)) + "\n",
        encoding="utf-8", newline="\n")

    declined = sum(1 for p in g.payments if p["result"] == "declined")
    print(f"wrote {args.out}: {len(g.customers)} customers, {len(g.products)} products, {len(g.sessions)} sessions, "
          f"{len(g.events)} events, {len(g.orders)} orders, {len(g.payments)} payment attempts ({declined} declined), "
          f"{len(g.refunds)} refunds")


if __name__ == "__main__":
    main()
