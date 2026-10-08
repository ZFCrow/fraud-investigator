import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import TIMESTAMP, Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.service import Base

# Storefront data the agent investigates. Deliberately plain typed columns (no JSON):
# the agent writes its own SQL against these tables, and nothing is pre-flagged as
# suspicious -- "new device", "card testing", "refund abuse" all have to be derived.


#! ========================================================
#! customers / catalogue
#! ========================================================
class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    full_name: Mapped[str] = mapped_column(String)
    country: Mapped[str] = mapped_column(String)  # ISO 3166-1 alpha-2, where the customer lives
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(String)  # active | suspended

    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="customer")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class PromoCode(Base):
    __tablename__ = "promo_codes"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(String)
    discount_percent: Mapped[int] = mapped_column(Integer)
    # a one-per-customer code redeemed by several accounts of the same person is abuse
    one_per_customer: Mapped[bool] = mapped_column(Boolean)


#! ========================================================
#! sessions and what happened in them
#! ========================================================
class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NULL = guest (browsing / guest checkout without an account)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop.customers.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    device_id: Mapped[str] = mapped_column(String)    # stable per browser/app install
    device_type: Mapped[str] = mapped_column(String)  # desktop | mobile | tablet
    ip_address: Mapped[str] = mapped_column(String)
    ip_country: Mapped[str] = mapped_column(String)   # ISO 3166-1 alpha-2, geolocated from the IP

    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="sessions")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="session")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shop.sessions.id"))
    # the account the event acted on; NULL for guests. A failed login carries the
    # account that was targeted.
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop.customers.id"), nullable=True)
    # LOGIN_SUCCESS | LOGIN_FAILED | PASSWORD_RESET | EMAIL_CHANGE | ADDRESS_CHANGE |
    # PRODUCT_VIEW | ADD_TO_CART | PROMO_APPLIED | CHECKOUT_START | ORDER_PLACED | REFUND_REQUESTED
    event_type: Mapped[str] = mapped_column(String)
    event_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    product_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop.products.id"), nullable=True)
    order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop.orders.id"), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # short free text, e.g. the new address

    session: Mapped["Session"] = relationship("Session", back_populates="events")


#! ========================================================
#! orders, payments, refunds
#! ========================================================
class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop.customers.id"), nullable=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shop.sessions.id"))
    guest_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # set only on guest checkouts
    placed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # after discount, USD
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    promo_code: Mapped[Optional[str]] = mapped_column(String, ForeignKey("shop.promo_codes.code"), nullable=True)
    status: Mapped[str] = mapped_column(String)  # placed | shipped | delivered | cancelled
    ship_city: Mapped[str] = mapped_column(String)
    ship_country: Mapped[str] = mapped_column(String)
    # same physical address -> same hash, whatever account ordered to it
    ship_address_hash: Mapped[str] = mapped_column(String)

    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop.orders.id"))
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop.products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped["Order"] = relationship("Order", back_populates="items")


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shop.sessions.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop.customers.id"), nullable=True)
    # the order this attempt paid for; NULL when the attempt was declined and no order followed
    order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop.orders.id"), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    card_fingerprint: Mapped[str] = mapped_column(String)  # same card -> same fingerprint
    card_last4: Mapped[str] = mapped_column(String)
    card_brand: Mapped[str] = mapped_column(String)
    card_country: Mapped[str] = mapped_column(String)      # issuing country
    result: Mapped[str] = mapped_column(String)            # approved | declined
    decline_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop.orders.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop.customers.id"), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reason: Mapped[str] = mapped_column(String)  # item_not_received | damaged | wrong_item | changed_mind
    status: Mapped[str] = mapped_column(String)  # approved | rejected | pending
