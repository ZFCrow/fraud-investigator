from typing import Optional

from llama_index.core.workflow import StartEvent, Event
from server.chat_agent.schemas import ChatRequest
from server.chat_agent.tools.enums import ToolName
from server.core.stream.progressReporter import ProgressReporter
from llama_index.core.llms import ChatMessage
from server.chat_agent.Pipeline.workflow.schemas import ToolObservation

# =====================================================================
# WORKFLOW EVENTS
# =====================================================================

class QueryStartEvent(StartEvent):
    chat_request: ChatRequest
    # per-call, not per-pipeline-instance: self.pipeline (ProposedRAGWorkflow) is
    # built once and reused across many queries, each with its own progress
    # reporter -- this must travel through .run()'s event, never live on self,
    # or query N+1 would silently report to query N's stale progress queue.
    #
    # Threaded through every Event field-to-field below, NOT via ctx.store: this
    # wraps a live asyncio.Queue (server/core/stream/progressReporter.py), and the
    # installed `workflows` runtime's ctx.store.set() deep-copies its *entire*
    # accumulated state on every call (workflows/context/state_store.py's
    # _load_state_for_edit -> state.model_copy(deep=True)) -- copying a live
    # asyncio.Queue's pending waiters throws "cannot pickle '_asyncio.Future'
    # object". Storing `progress` here once didn't crash by itself (nothing else
    # called .set() again), but it poisoned the state for the next .set() call,
    # which is exactly what happened when `steps` below was added via ctx.store.
    progress: ProgressReporter
    # built once by the outer pipeline (which also needs it for the evaluation
    # call afterward) and handed in here -- the workflow's job is to make sense
    # of context it's given, not to own fetching it; keeps this graph's only
    # dependencies to tools/llm/system_prompt, and avoids fetching the same
    # session's history from Redis/Postgres twice per query.
    chat_history: list[ChatMessage]
    context_str: str


# `observations` (every tool call made so far this query) and `iteration` (tool
# calls made so far) ride along the loop reason_and_route -> fetch_schema ->
# execute_tool -> reason_and_route, for the same reasons `progress` does.

class RoutedEvent(Event):
    chat_request: ChatRequest
    progress: ProgressReporter
    chat_history: list[ChatMessage]
    context_str: str
    tool_name: ToolName
    # the reasoning step's "why this call" -- e.g. what a retry must fix -- handed to
    # the arg-generation step so it doesn't have to re-derive the intent itself
    reasoning: str
    observations: list[ToolObservation]
    iteration: int


class SchemaFetchedEvent(Event):
    chat_request: ChatRequest
    progress: ProgressReporter
    chat_history: list[ChatMessage]
    context_str: str
    tool_name: ToolName
    reasoning: str
    schema_text: str
    observations: list[ToolObservation]
    iteration: int


class ToolExecutedEvent(Event):
    """Loops back into reason_and_route, which decides whether to call another tool."""
    chat_request: ChatRequest
    progress: ProgressReporter
    chat_history: list[ChatMessage]
    context_str: str
    observations: list[ToolObservation]  # includes the call that just ran
    iteration: int


class ReadyToAnswerEvent(Event):
    """Emitted by reason_and_route once it has enough context, or once max_iterations is hit."""
    chat_request: ChatRequest
    progress: ProgressReporter
    chat_history: list[ChatMessage]
    context_str: str
    observations: list[ToolObservation]
    hit_max_iterations: bool
    # set when the reasoning step judged the question out of scope: synthesize_answer
    # then writes a refusal instead of an answer
    refused: bool = False
    refuse_reason: Optional[str] = None


class AnsweredEvent(Event):
    chat_request: ChatRequest
    progress: ProgressReporter
    answer: str
