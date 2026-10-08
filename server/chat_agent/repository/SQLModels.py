from shared.database.service import Base 
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID, JSONB
from typing import Optional
from datetime import datetime
import uuid


class agent_trace(Base):
    """
    tool_calls: [{tool_name: "", output: ""}, ...]

    evaluation : [{
        response: "",
        evaluation: {}
    }]
    """
    __tablename__ = "agent_trace"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True)) 
    input: Mapped[str] = mapped_column(String)
    output: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tool_calls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # one entry per workflow step the run executed, in order
    steps: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    agent_prompt_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shop.prompt.id"),
        nullable=True,
        )