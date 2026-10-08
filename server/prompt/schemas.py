import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from server.prompt.enums import PROMPTTYPE


class Prompt(BaseModel):
    """
    One versioned prompt row — the full DB record, and what IPromptRepository.
    insert_prompt takes as input (same shape as insert_evaluation_result /
    insert_trace elsewhere in this codebase).

    id and created_at follow the usual convention (default_factory, trusted as
    given on insert). version is the one field the caller can't meaningfully set:
    it depends on existing DB state (current max version for this type + 1), so
    PostgresPromptRepository always recomputes and overwrites it on insert
    regardless of what's passed in — construct a Prompt without worrying about
    it, and readd the real value off the returned object.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique identifier for the prompt.")
    text: str = Field(..., description="The text of the prompt.")

    type: PROMPTTYPE = Field(..., description="Prompt for which system (e.g., a workflow step prompt, evaluator prompt).")
    version: int = Field(
        default=0,
        description="Version of this prompt within its type, assigned sequentially starting at 1. "
                     "Ignored on insert_prompt — the repository always computes the real value. "
                     "Meaningful only on a Prompt read back from the DB.",
    )

    # At most one active row per type (enforced by a partial unique index in
    # SQLModels.prompt). Runtime consumers call get_active_prompt(type) to fetch
    # this row instead of reading a hardcoded prompt constant. A freshly inserted
    # candidate (e.g. from the reflector) defaults to inactive until it clears
    # validation and IPromptRepository.activate_prompt is called on it.
    is_active: bool = Field(default=False, description="Whether this version is the one currently served for its type.")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp when the prompt was created.")

    #gap analysis This is used to inform the next prompt version's design. 
    gap_analysis_reason: str | None = Field(default=None, description="Optional justification for this prompt version update.") 

    # root cause analysis This is used to inform the next prompt version's design. 
    root_cause_analysis_reason: str | None = Field(default=None, description="Optional root cause analysis for this prompt version update.")


    def __eq__(self, other: object) -> bool:
        if isinstance(other, type(self)):
            return self.text == other.text
        if isinstance(other, str):
            return self.text == other
        return False