import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SessionEvent:
    id: int
    event_type: str
    event_time: datetime
    detail: Optional[str] = None
    product_name: Optional[str] = None
    order_id: Optional[int] = None


@dataclass
class SessionPayment:
    id: int
    attempted_at: datetime
    amount: float
    card_fingerprint: str
    card_last4: str
    card_brand: str
    card_country: str
    result: str
    decline_reason: Optional[str] = None
    order_id: Optional[int] = None


@dataclass
class SessionOrder:
    id: int
    placed_at: datetime
    total_amount: float
    discount_amount: float
    status: str
    ship_city: str
    ship_country: str
    ship_address_hash: str
    promo_code: Optional[str] = None
    guest_email: Optional[str] = None
    # "2 x Wireless Headphones", ...
    items: list[str] = field(default_factory=list)


@dataclass
class ShopSession:
    """One storefront session with everything that happened in it, ready to embed."""
    session_id: uuid.UUID
    session_start: datetime
    session_end: datetime
    device_id: str
    device_type: str
    ip_address: str
    ip_country: str

    # None on all three = guest session
    customer_id: Optional[int] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    customer_country: Optional[str] = None
    account_created_at: Optional[datetime] = None

    events: list[SessionEvent] = field(default_factory=list)
    payments: list[SessionPayment] = field(default_factory=list)
    orders: list[SessionOrder] = field(default_factory=list)
