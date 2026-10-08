from abc import ABC, abstractmethod
from dataclasses import dataclass
import uuid
from typing_extensions import Optional

from shared.embeddings.schemas import SparseEmbeddings


from ingestor.store.schemas import ShopSession

@dataclass(kw_only=True)
class Point(ABC):
    dense: Optional[list[float]] = None
    sparse: Optional[SparseEmbeddings] = None
    text: str = ""

    @property
    @abstractmethod
    def point_id(self) -> str:
        pass

    @abstractmethod
    def to_text(self) -> str:
        pass

    @abstractmethod
    def to_payload(self) -> dict:
        pass



@dataclass(kw_only=True)
class SessionPoint(Point):
    session: ShopSession

    @property
    def point_id(self) -> str:
        # the session's own id: re-ingesting a session overwrites its point
        return str(self.session.session_id)

    @property
    def _declined(self) -> int:
        return sum(1 for p in self.session.payments if p.result == "declined")

    def to_payload(self) -> dict:
        s = self.session
        return {
            "session_id": str(s.session_id),
            "customer_id": s.customer_id,
            "customer_email": s.customer_email,
            "customer_name": s.customer_name,
            "is_guest": s.customer_id is None,
            "session_start": s.session_start.isoformat(),
            "session_end": s.session_end.isoformat(),
            "device_id": s.device_id,
            "device_type": s.device_type,
            "ip_address": s.ip_address,
            "ip_country": s.ip_country,
            "event_count": len(s.events),
            "payment_attempt_count": len(s.payments),
            "declined_payment_count": self._declined,
            "distinct_card_count": len({p.card_fingerprint for p in s.payments}),
            "order_count": len(s.orders),
            "order_total": round(sum(o.total_amount for o in s.orders), 2),
            "text": self.text,
        }

    def to_text(self) -> str:
        """
        The session as a short narrative: who, from where, then everything that
        happened in time order (events, payment attempts and orders interleaved).
        States only what the rows say -- no "suspicious" judgement is added here.
        """
        s = self.session

        if s.customer_id is None:
            who = "Guest (no account)"
        else:
            who = f"Customer {s.customer_name} ({s.customer_email}), customer id {s.customer_id}"
            extra = []
            if s.customer_country:
                extra.append(f"home country {s.customer_country}")
            if s.account_created_at:
                extra.append(f"account created {s.account_created_at:%Y-%m-%d}")
            if extra:
                who += ", " + ", ".join(extra)

        approved = len(s.payments) - self._declined
        summary = [f"{len(s.events)} events"]
        if s.payments:
            cards = len({p.card_fingerprint for p in s.payments})
            summary.append(f"{len(s.payments)} payment attempts ({approved} approved, {self._declined} declined) "
                           f"across {cards} distinct card{'s' if cards != 1 else ''}")
        if s.orders:
            summary.append(f"{len(s.orders)} order{'s' if len(s.orders) != 1 else ''} "
                           f"totalling ${sum(o.total_amount for o in s.orders):.2f}")

        self.text = (
            f"{who}. Session {s.session_id} from {s.session_start:%Y-%m-%d %H:%M:%S} to "
            f"{s.session_end:%H:%M:%S} (GMT+8) on {s.device_type} device {s.device_id}, "
            f"IP {s.ip_address} ({s.ip_country}). " + ", ".join(summary) + ".\n"
        )

        orders = {o.id: o for o in s.orders}
        timeline: list[tuple] = []

        for e in s.events:
            phrase = e.event_type
            if e.product_name:
                phrase += f" '{e.product_name}'"
            if e.event_type == "ORDER_PLACED" and e.order_id in orders:
                o = orders[e.order_id]
                phrase += f" order {o.id} for ${o.total_amount:.2f}"
                if o.items:
                    phrase += f" ({', '.join(o.items)})"
                if o.promo_code:
                    phrase += f", promo {o.promo_code} (-${o.discount_amount:.2f})"
                phrase += f", shipping to {o.ship_city}, {o.ship_country} (address {o.ship_address_hash})"
                if o.guest_email:
                    phrase += f", guest email {o.guest_email}"
            elif e.order_id:
                phrase += f" for order {e.order_id}"
            if e.detail:
                phrase += f": {e.detail}"
            timeline.append((e.event_time, 0, e.id, phrase))

        for p in s.payments:
            phrase = (f"PAYMENT {p.result.upper()} ${p.amount:.2f} on {p.card_brand} card ending {p.card_last4} "
                      f"(fingerprint {p.card_fingerprint}, issued in {p.card_country})")
            if p.decline_reason:
                phrase += f", reason {p.decline_reason}"
            if p.order_id:
                phrase += f", for order {p.order_id}"
            timeline.append((p.attempted_at, 1, p.id, phrase))

        timeline.sort(key=lambda t: t[:3])
        self.text += "\n".join(f"{when:%H:%M:%S} {phrase}" for when, _, _, phrase in timeline) + "\n"

        return self.text
