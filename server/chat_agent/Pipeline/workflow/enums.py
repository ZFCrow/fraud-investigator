from enum import Enum
from typing import Optional

from server.prompt.enums import PROMPTTYPE


class WorkflowStepName(str, Enum):
    """
    The steps of ProposedRAGWorkflow, in pipeline order -- the value is what lands in
    WorkflowStepTrace.step_name. The order matters to the multi-step reflector: when two
    steps are blamed equally, the earlier one wins, since an upstream mistake cascades.
    """
    REASON = "reason"
    FETCH_SCHEMA = "fetch_schema"
    GENERATE_SQL_ARGS = "generate_sql_args"
    GENERATE_VECTOR_ARGS = "generate_vector_args"
    SYNTHESIZE_ANSWER = "synthesize_answer"
    GENERATE_FOLLOW_UP = "generate_follow_up"

    @property
    def prompt_type(self) -> Optional[PROMPTTYPE]:
        """The versioned prompt this step runs on -- None for fetch_schema, which calls no LLM."""
        return _STEP_PROMPT_TYPES.get(self)

    @property
    def order(self) -> int:
        return list(WorkflowStepName).index(self)

    @classmethod
    def from_prompt_type(cls, prompt_type: PROMPTTYPE) -> Optional["WorkflowStepName"]:
        return next((s for s, t in _STEP_PROMPT_TYPES.items() if t == prompt_type), None)


class ReasonAction(str, Enum):
    """
    What reason_and_route does next. Derived in code from the facts the reasoning LLM
    reports (ReasoningDecision.action) -- never chosen by the LLM itself. The value is
    what lands in the reason step's WorkflowStepTrace output.
    """
    REFUSE = "refuse"
    CALL_TOOL = "call_tool"
    ANSWER = "answer"


_STEP_PROMPT_TYPES: dict[WorkflowStepName, PROMPTTYPE] = {
    WorkflowStepName.REASON: PROMPTTYPE.WORKFLOW_REASON_STEP,
    WorkflowStepName.GENERATE_SQL_ARGS: PROMPTTYPE.WORKFLOW_SQL_ARGS_STEP,
    WorkflowStepName.GENERATE_VECTOR_ARGS: PROMPTTYPE.WORKFLOW_VECTOR_ARGS_STEP,
    WorkflowStepName.SYNTHESIZE_ANSWER: PROMPTTYPE.WORKFLOW_SYNTHESIZE_STEP,
    WorkflowStepName.GENERATE_FOLLOW_UP: PROMPTTYPE.WORKFLOW_FOLLOW_UP_STEP,
}

# the steps that have a prompt of their own, i.e. the ones a reflector can rewrite
PROMPTED_STEPS: list[WorkflowStepName] = list(_STEP_PROMPT_TYPES)
