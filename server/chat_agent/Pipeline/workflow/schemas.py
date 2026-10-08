from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from server.chat_agent.Pipeline.workflow.enums import ReasonAction

# =====================================================================
# STRUCTURED LLM CALL SHAPES
# =====================================================================


def _blank_to_none(v):
    # Nemotron sometimes writes an empty optional field as the string "None"/"null" instead
    # of a JSON null. Left as-is that fails validation (a Literal or int field, which fails
    # the whole run) or passes as a real value (a search filtered to a user called "None").
    if isinstance(v, str) and v.strip().lower() in ("", "none", "null", "n/a"):
        return None
    return v


class ReasoningDecision(BaseModel):
    """
    The LLM only reports its reasoning and the facts below -- it never names the next
    step. `action` derives the step from those facts, so the routing is ours and a
    contradictory label (e.g. "answer" on a question with no data yet) can't happen.
    """
    # first on purpose: fields are generated in order, so the model thinks before it
    # commits to the flags below
    reasoning: str = Field(
        ..., description="Think first: what is being asked, which tables/tools could answer it, "
                         "and what the tool calls made so far already cover."
    )
    in_scope: bool = Field(
        ..., description="True if this is answerable from the store data/sessions or prior results. "
                         "False ONLY for unrelated topics (weather, coding help, etc)."
    )
    refuse_reason: Optional[str] = Field(
        default=None, description="Required if in_scope is False: what the question asks for "
                                  "that the store data does not contain."
    )
    needs_more_data: bool = Field(
        ..., description="True if answering requires data not already in the tool calls made so far. "
                         "Any count/list/trend/who/which question with no matching result -> True."
    )
    # Literal of the *string values*, not the enum members: astructured_predict validates
    # the LLM's raw JSON output (a plain string like "query_sql") against this schema, and
    # pydantic's Literal validator does not coerce a matching string into an enum member the
    # way a bare Enum-typed field would -- Literal[ToolName.QUERY_SQL, ...] rejects the exact
    # string the model actually returns. Not a bare ToolName either: that would let the model
    # pick tools this step can't route to (the schema tools, the follow-up generator).
    # Converted back to ToolName right after validation.
    tool_name: Optional[Literal["query_sql", "query_vector_store"]] = Field(
        default=None, description="Next tool to call. Required if needs_more_data is True."
    )

    _blank_to_none = field_validator("tool_name", "refuse_reason", mode="before")(_blank_to_none)

    @property
    def action(self) -> ReasonAction:
        # scope is checked first: an out-of-scope question is refused even if the model
        # also flagged needs_more_data
        if not self.in_scope:
            return ReasonAction.REFUSE
        if self.needs_more_data:
            return ReasonAction.CALL_TOOL
        return ReasonAction.ANSWER


class ToolObservation(BaseModel):
    """One completed tool call, accumulated across reasoning iterations."""
    tool_name: str
    arguments: dict
    result: str


class SQLCallArgs(BaseModel):
    sql: str = Field(..., description="The read-only SELECT query to execute.")
    generate_chart: bool = Field(default=False)
    chart_type: str = Field(default="bar", description="bar | line | pie | heatmap")
    x_column: Optional[str] = None
    y_column: Optional[str] = None
    value_column: Optional[str] = None

    _blank_to_none = field_validator("x_column", "y_column", "value_column", mode="before")(_blank_to_none)


class VectorCallArgs(BaseModel):
    query: str = Field(..., description="The semantic/keyword query text, with time words stripped out.")
    limit: int = Field(default=10)
    filter_customer_email: Optional[str] = None
    filter_device_id: Optional[str] = None
    filter_ip_country: Optional[str] = Field(default=None, description="ISO 2-letter country code, e.g. RO.")
    filter_start_date: Optional[str] = Field(default=None, description="ISO 8601, GMT+8 -- vector store dates are not UTC.")
    filter_end_date: Optional[str] = Field(default=None, description="ISO 8601, GMT+8 -- vector store dates are not UTC.")
    filter_event_count: Optional[int] = None
    filter_declined_payments: Optional[int] = None

    _blank_to_none = field_validator(
        "filter_customer_email", "filter_device_id", "filter_ip_country", "filter_start_date",
        "filter_end_date", "filter_event_count", "filter_declined_payments", mode="before")(_blank_to_none)


class FollowUpQuestion(BaseModel):
    short: str = Field(..., description="3-8 word button label.")
    long: str = Field(..., description="Full question sent back to the agent if clicked.")


class FollowUpQuestions(BaseModel):
    generated_questions: list[FollowUpQuestion]


class FinalAnswer(BaseModel):
    answer: str = Field(
        ..., description="The full response to show the analyst, ending with a Reasoning/Trace section."
    )
