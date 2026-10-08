from shared.database.service import Base

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Boolean, Index, Integer, String, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

import uuid
from datetime import datetime


class prompt(Base):

    __tablename__ = "prompt"
    __table_args__ = (
        # Application code (PostgresPromptRepository.insert_prompt) computes the next
        # version per type, but the DB still enforces it can never collide.
        UniqueConstraint("type", "version", name="uq_prompt_type_version"),
        # DB-level guarantee that at most one row per type is ever active, even if
        # activate_prompt's deactivate-then-activate steps race or a bug skips the
        # deactivation.
        Index(
            "uq_prompt_active_per_type", "type",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    text: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))


    # optional fields
    gap_analysis_reason: Mapped[str | None] = mapped_column(String, nullable=True) 
    root_cause_analysis_reason: Mapped[str | None] = mapped_column(String, nullable=True) 
