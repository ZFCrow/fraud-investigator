import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
import logging
from typing import AsyncGenerator

from ingestor.store.repository import ISessionIngestionRepository
from ingestor.store.schemas import SessionEvent, SessionOrder, SessionPayment, ShopSession


class PostgresSessionIngestionRepository(ISessionIngestionRepository):
    """
    Ingestion repository for storefront sessions: one row of `sessions` with its
    events, payment attempts and the orders placed in it.

    Only sessions that ended more than 30 minutes ago are returned, so a session
    still in progress is not embedded half-finished. The checkpoint is anchored on
    ended_at.
    """

    def __init__(self,
                 session: AsyncSession):
        self.tz = timezone(timedelta(hours=8))
        self.session = session

    async def get_logs_since(self,
                             last_processed_at: datetime = None,
                             batch_size: int = 30,
                             offset : int = 0
                             ) -> AsyncGenerator[list[ShopSession], None]:
        """
        implements ISessionIngestionRepository to fetch sessions by batch
        """
        logging.info(f"Starting to fetch sessions since {last_processed_at} with batch size {batch_size} offset {offset}")

        time_filter = "AND s.ended_at > :last_processed_at" if last_processed_at else ""

        sql = f"""
SELECT
    s.id AS session_id, s.started_at, s.ended_at,
    s.device_id, s.device_type, s.ip_address, s.ip_country,
    c.id AS customer_id, c.email AS customer_email, c.full_name AS customer_name,
    c.country AS customer_country, c.created_at AS account_created_at,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'id', e.id, 'event_type', e.event_type, 'event_time', e.event_time,
                   'detail', e.detail, 'product_name', p.name, 'order_id', e.order_id
               ) ORDER BY e.event_time, e.id)
        FROM shop.events e
        LEFT JOIN shop.products p ON p.id = e.product_id
        WHERE e.session_id = s.id
    ), '[]'::jsonb) AS events,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'id', pa.id, 'attempted_at', pa.attempted_at, 'amount', pa.amount,
                   'card_fingerprint', pa.card_fingerprint, 'card_last4', pa.card_last4,
                   'card_brand', pa.card_brand, 'card_country', pa.card_country,
                   'result', pa.result, 'decline_reason', pa.decline_reason, 'order_id', pa.order_id
               ) ORDER BY pa.attempted_at, pa.id)
        FROM shop.payment_attempts pa
        WHERE pa.session_id = s.id
    ), '[]'::jsonb) AS payments,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'id', o.id, 'placed_at', o.placed_at, 'total_amount', o.total_amount,
                   'discount_amount', o.discount_amount, 'status', o.status,
                   'promo_code', o.promo_code, 'guest_email', o.guest_email,
                   'ship_city', o.ship_city, 'ship_country', o.ship_country,
                   'ship_address_hash', o.ship_address_hash,
                   'items', (
                       SELECT jsonb_agg(oi.quantity || ' x ' || pr.name ORDER BY oi.id)
                       FROM shop.order_items oi
                       JOIN shop.products pr ON pr.id = oi.product_id
                       WHERE oi.order_id = o.id
                   )
               ) ORDER BY o.placed_at, o.id)
        FROM shop.orders o
        WHERE o.session_id = s.id
    ), '[]'::jsonb) AS orders
FROM shop.sessions s
LEFT JOIN shop.customers c ON c.id = s.customer_id
WHERE s.ended_at < NOW() - INTERVAL '30 minutes'
{time_filter}
ORDER BY s.ended_at, s.id
LIMIT :batch_size OFFSET :offset
        """

        while True:
            params = {"batch_size": batch_size, "offset": offset}
            if last_processed_at:
                params["last_processed_at"] = last_processed_at

            result = await self.session.execute(text(sql), params)
            batch = result.mappings().all()

            if not batch:
                break

            # convert batch to ShopSession objects before yielding
            batch : list[ShopSession] = [self._to_domain(row) for row in batch]
            yield batch
            offset += batch_size

    # infrastructure
    # so that the domain doesnt know about the database schema, we convert the row to a domain object here
    def _to_domain(self, row) -> ShopSession:
        account_created_at = row["account_created_at"]
        return ShopSession(
            session_id=row["session_id"] if isinstance(row["session_id"], uuid.UUID) else uuid.UUID(str(row["session_id"])),
            session_start=row["started_at"].astimezone(self.tz),
            session_end=row["ended_at"].astimezone(self.tz),
            device_id=row["device_id"],
            device_type=row["device_type"],
            ip_address=row["ip_address"],
            ip_country=row["ip_country"],
            customer_id=row["customer_id"],
            customer_email=row["customer_email"],
            customer_name=row["customer_name"],
            customer_country=row["customer_country"],
            account_created_at=account_created_at.astimezone(self.tz) if account_created_at else None,
            events=[self._to_event(e) for e in row["events"]],
            payments=[self._to_payment(p) for p in row["payments"]],
            orders=[self._to_order(o) for o in row["orders"]],
        )

    def _time(self, value: str) -> datetime:
        return datetime.fromisoformat(value).astimezone(self.tz)

    def _to_event(self, e: dict) -> SessionEvent:
        return SessionEvent(
            id=e["id"],
            event_type=e["event_type"],
            event_time=self._time(e["event_time"]),
            detail=e.get("detail"),
            product_name=e.get("product_name"),
            order_id=e.get("order_id"),
        )

    def _to_payment(self, p: dict) -> SessionPayment:
        return SessionPayment(
            id=p["id"],
            attempted_at=self._time(p["attempted_at"]),
            amount=float(p["amount"]),
            card_fingerprint=p["card_fingerprint"],
            card_last4=p["card_last4"],
            card_brand=p["card_brand"],
            card_country=p["card_country"],
            result=p["result"],
            decline_reason=p.get("decline_reason"),
            order_id=p.get("order_id"),
        )

    def _to_order(self, o: dict) -> SessionOrder:
        return SessionOrder(
            id=o["id"],
            placed_at=self._time(o["placed_at"]),
            total_amount=float(o["total_amount"]),
            discount_amount=float(o["discount_amount"]),
            status=o["status"],
            ship_city=o["ship_city"],
            ship_country=o["ship_country"],
            ship_address_hash=o["ship_address_hash"],
            promo_code=o.get("promo_code"),
            guest_email=o.get("guest_email"),
            items=o.get("items") or [],
        )
