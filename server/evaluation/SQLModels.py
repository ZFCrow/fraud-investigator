from shared.database.service import Base

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, Integer, String, TIMESTAMP, Float, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB

import uuid
from datetime import datetime
from typing import Optional

class evaluation(Base): 

    __tablename__ = "evaluation" 

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4) 

    agent_trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shop.agent_trace.id"),
        nullable=False,
        )

    # Which judge-prompt version produced this row. Nullable: rows written before
    # this column existed have no value to backfill, and it's also unset on any
    # path that doesn't go through EvaluationService.evaluate() (e.g. a future
    # calibration flow inserting pre-computed results directly). Needed so two
    # evaluation runs of the same agent_trace_id under different candidate judge
    # prompts (calibration stage 3 — see tests/calibration/readme.md) can be told
    # apart instead of landing as indistinguishable duplicate rows.
    evaluator_prompt_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shop.prompt.id"),
        nullable=True,
        )

    helpfulness_score: Mapped[float] = mapped_column(Float) 
    helpfulness_reasoning: Mapped[str] = mapped_column(String) 

    coherence_score: Mapped[float] = mapped_column(Float) 
    coherence_reasoning: Mapped[str] = mapped_column(String) 

    coverage_score: Mapped[float] = mapped_column(Float) 
    coverage_reasoning: Mapped[str] = mapped_column(String) 

    faithfulness_score: Mapped[float] = mapped_column(Float) 
    faithfulness_reasoning: Mapped[str] = mapped_column(String) 

    context_relevance_score: Mapped[float] = mapped_column(Float) 
    context_relevance_reasoning: Mapped[str] = mapped_column(String) 

    answer_relevance_score: Mapped[float] = mapped_column(Float)
    answer_relevance_reasoning: Mapped[str] = mapped_column(String)

    # tool routing: nullable — unknown/not assessed is a legitimate state, distinct from False.
    # Deterministic on benchmark runs, LLM-judged on live traffic — see EvaluationService.
    # No provenance column: benchmark and live traffic are expected to land in separate DBs.
    tool_routing_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    tool_routing_reasoning: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # route_efficiency = actual tool calls (derivable via join to agent_trace.tool_calls,
    # not duplicated here) / expected_tool_calls. expected_tool_calls itself isn't derivable
    # elsewhere once computed, so it's stored; route_efficiency is cached rather than
    # recomputed on every read.
    expected_tool_calls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    route_efficiency: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    overall_reasoning: Mapped[str] = mapped_column(String)
    overall_result: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True)) 


