from enum import Enum
from typing import Optional

from server.prompt.enums import PROMPTTYPE


class ModelTier(str, Enum):
    """
    Which Nemotron model serves an LLM call. Every step has a fixed tier except
    synthesize_answer, whose tier depends on what the investigation needed
    (ReadyToAnswerEvent.synthesis_tier). Tier -> model id is settings, wired in
    server/core/dependencies.py (get_llms).
    """
    FAST = "fast"            # short, low-stakes output: follow-ups, the out-of-scope reply
    AGENT = "agent"          # the reason / write-arguments loop, and single-result answers
    REASONING = "reasoning"  # weighing several results into one conclusion


class WorkflowStepName(str, Enum):
    """
    The steps of ProposedRAGWorkflow, in pipeline order -- the value is what lands in
    WorkflowStepTrace.step_name. The order matters to the multi-step reflector: when two
    steps are blamed equally, the earlier one wins, since an upstream mistake cascades.
    """
    # the versioned prompt the step runs on, and the model tier its LLM call runs on --
    # both None for fetch_schema, which calls no LLM
    prompt_type: Optional[PROMPTTYPE]
    llm_tier: Optional[ModelTier]
    # what the step is for, so a reader of the trace (or a reflector rewriting the step's
    # prompt) knows the step's job before judging it
    role: str

    # Tier follows what a mistake costs: a wrong routing decision or wrong arguments produce
    # a wrong answer, while a weak follow-up question only costs quality.
    REASON = (
        "reason", PROMPTTYPE.WORKFLOW_REASON_STEP, ModelTier.AGENT,
        "Decides the next action: call a tool (and which one), or answer. Never writes the answer itself.",
    )
    FETCH_SCHEMA = (
        "fetch_schema", None, None,
        "Fetches the chosen tool's schema text. No LLM and no prompt; never the step to rewrite.",
    )
    GENERATE_SQL_ARGS = (
        "generate_sql_args", PROMPTTYPE.WORKFLOW_SQL_ARGS_STEP, ModelTier.AGENT,
        "Writes one read-only SQL query and its chart settings for query_sql.",
    )
    GENERATE_VECTOR_ARGS = (
        "generate_vector_args", PROMPTTYPE.WORKFLOW_VECTOR_ARGS_STEP, ModelTier.AGENT,
        "Writes the search text and filters for the session vector store.",
    )
    GENERATE_WEB_SEARCH_ARGS = (
        "generate_web_search_args", PROMPTTYPE.WORKFLOW_WEB_SEARCH_ARGS_STEP, ModelTier.AGENT,
        "Abstracts the store evidence into a generic fraud pattern (no customer data) and writes "
        "the public web search for it.",
    )
    # AGENT is only the baseline: the tier is chosen per question by
    # ReadyToAnswerEvent.synthesis_tier (REASONING for multi-result answers, FAST for refusals)
    SYNTHESIZE_ANSWER = (
        "synthesize_answer", PROMPTTYPE.WORKFLOW_SYNTHESIZE_STEP, ModelTier.AGENT,
        "Writes the analyst-facing answer from the tool results gathered so far.",
    )
    GENERATE_FOLLOW_UP = (
        "generate_follow_up", PROMPTTYPE.WORKFLOW_FOLLOW_UP_STEP, ModelTier.FAST,
        "Suggests 2-3 follow-up questions after the answer.",
    )

    def __new__(cls, value: str, prompt_type: Optional[PROMPTTYPE], llm_tier: Optional[ModelTier], role: str):
        obj = str.__new__(cls, value)
        obj._value_ = value  # .value stays "reason", not the tuple
        obj.prompt_type = prompt_type
        obj.llm_tier = llm_tier
        obj.role = role
        return obj

    @property
    def order(self) -> int:
        return list(WorkflowStepName).index(self)

    @classmethod
    def from_prompt_type(cls, prompt_type: PROMPTTYPE) -> Optional["WorkflowStepName"]:
        return next((s for s in cls if s.prompt_type == prompt_type), None)


class ReasonAction(str, Enum):
    """
    What reason_and_route does next. Derived in code from the facts the reasoning LLM
    reports (ReasoningDecision.action) -- never chosen by the LLM itself. The value is
    what lands in the reason step's WorkflowStepTrace output.
    """
    REFUSE = "refuse"
    CALL_TOOL = "call_tool"
    ANSWER = "answer"


# the steps that have a prompt of their own, i.e. the ones a reflector can rewrite
PROMPTED_STEPS: list[WorkflowStepName] = [s for s in WorkflowStepName if s.prompt_type is not None]
