from server.chat_agent.Pipeline.workflow.events import (
    QueryStartEvent,
    RoutedEvent,
    SchemaFetchedEvent,
    ToolExecutedEvent,
    ReadyToAnswerEvent,
    AnsweredEvent,
)
from server.chat_agent.Pipeline.workflow.enums import ModelTier, ReasonAction, WorkflowStepName
from server.prompt.schemas import Prompt

from llama_index.core.workflow import Workflow, StartEvent, StopEvent, Event, step, Context
from server.chat_agent.tools.enums import ToolErrorType, ToolName, ToolStatus
from server.chat_agent.schemas import ToolCall, WorkflowStepTrace
from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.prompts import PromptTemplate

from server.chat_agent.Pipeline.workflow.schemas import (
    ReasoningDecision,
    ToolObservation,
    SQLCallArgs,
    VectorCallArgs,
    WebSearchCallArgs,
    FinalAnswer,
    FollowUpQuestions
    )
import logging
import time
from datetime import datetime
from typing import Optional, TypeVar

from pydantic import BaseModel
from zoneinfo import ZoneInfo

from server.chat_agent.tools.tool import AgentTool

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)

# the tool that reads each routable tool's schema before its arguments are written
SCHEMA_TOOLS: dict[ToolName, ToolName] = {
    ToolName.QUERY_SQL: ToolName.GET_SQL_SCHEMA,
    ToolName.QUERY_SESSION_VECTOR_HYBRID: ToolName.GET_SESSION_VECTOR_HYBRID_SCHEMA,
    ToolName.SEARCH_FRAUD_PATTERNS: ToolName.GET_FRAUD_PATTERN_SEARCH_SCHEMA,
}
# the tools that read this store's data -- a web search needs one of their results first
STORE_TOOLS: set[str] = {ToolName.QUERY_SQL.value, ToolName.QUERY_SESSION_VECTOR_HYBRID.value}
# =====================================================================
# WORKFLOW: reason -> (schema -> execute -> reason)* -> synthesize
#           -> follow-up, with at most max_iterations tool calls
# =====================================================================


SGT = ZoneInfo("Asia/Singapore")


def _as_of_note(data_as_of: Optional[datetime]) -> str:
    """The "now" the steps work from, to turn "last 7 days" / "today" into concrete dates.
    The store data is a fixed snapshot ending at data_as_of: the real clock would put those
    windows past the end of the data, and every answer would be "no activity"."""
    if data_as_of is None:
        return f"Current time: {datetime.now(SGT):%Y-%m-%d %H:%M (%A)}, SGT"
    return (
        f"Current time: {data_as_of.astimezone(SGT):%Y-%m-%d %H:%M (%A)}, SGT. The store's data is "
        f"a fixed snapshot that ends at this moment, so treat the question as asked then: \"now\", "
        f"\"today\", \"recent\" and \"last N days\" are relative to this time, not the real date."
    )


def _as_of_literal(data_as_of: Optional[datetime]) -> Optional[str]:
    """The data's end as a timestamptz literal for SQL, e.g. "2026-10-07 09:19:52+08"."""
    return f"{data_as_of.astimezone(SGT):%Y-%m-%d %H:%M:%S}+08" if data_as_of is not None else None


def _sql_clock_rule(data_as_of: Optional[datetime]) -> str:
    # the model reaches for now() / current_timestamp by habit, and those return the real date;
    # SQLQueryTool also rejects them, this saves the round trip
    if data_as_of is None:
        return ""
    return (
        f" In SQL, write this time as the literal TIMESTAMPTZ '{_as_of_literal(data_as_of)}'. Never use "
        f"now(), current_timestamp or current_date: they return the real date, after the data ends, "
        f"and the query is rejected."
    )


def _as_of_disclaimer(data_as_of: datetime) -> str:
    """Opens every answer, so the analyst knows which "today" the answer counted from."""
    return (
        f"_Treated as asked on {data_as_of.astimezone(SGT):%d %b %Y, %H:%M} SGT: the store data is "
        f"a fixed snapshot that ends then, so \"today\" and \"last N days\" count back from that time._\n\n"
    )


def _format_observations(observations: list[ToolObservation]) -> str:
    if not observations:
        return "None yet."
    return "\n\n".join(
        f"[{i}] {o.tool_name} -- {o.label}\nArguments: {o.arguments}\nResult:\n{o.result}"
        for i, o in enumerate(observations, start=1)
    )


class ProposedRAGWorkflow(Workflow):
    def __init__(self,
                 tools : dict[ToolName, AgentTool],
                 llms: dict[ModelTier, LLM],
                 step_prompts: dict[WorkflowStepName, Prompt],
                 max_iterations: int = 3,
                 max_free_repairs: int = 2,
                 timeout: float = 180.0,
                 ):
        # generous timeout: each iteration is 2 sequential LLM calls plus a tool
        # execution, on top of the synthesize/follow-up calls -- the llama_index
        # Workflow default (10s) is nowhere near enough.
        super().__init__(timeout=timeout)

        self.tools : dict[ToolName, AgentTool] = tools
        # one model per tier (server/core/dependencies.py get_llms); each LLM step asks
        # for a tier, and synthesize_answer's tier depends on the run (see _predict)
        self.llms : dict[ModelTier, LLM] = llms
        # one versioned Prompt per LLM step (see ProposedWorkflowRag.setup_agent); each
        # step records its prompt's id in WorkflowStepTrace, so the reflector can tell
        # exactly which prompt version produced a bad step
        self.step_prompts : dict[WorkflowStepName, Prompt] = step_prompts
        # cap on tool calls per query; once reached, reason_and_route is forced
        # to emit ReadyToAnswerEvent with whatever it has gathered.
        self.max_iterations = max_iterations
        # a query the database rejected before running it (ToolErrorType.INVALID_QUERY)
        # is repaired without using up one of those tool calls -- but only this many
        # times per question, so a model that keeps writing invalid SQL still stops.
        self.max_free_repairs = max_free_repairs

    async def _predict(self,
                       step_name: WorkflowStepName,
                       output_cls: type[StructuredOutput],
                       prompt_text: str,
                       steps: list[WorkflowStepTrace],
                       tier: Optional[ModelTier] = None,
                       ) -> StructuredOutput:
        """One structured LLM call on the step's tier (or `tier`, when the caller picks it per
        run), recorded in the trace with the model that served it and how long it took."""
        llm: LLM = self.llms[tier or step_name.llm_tier]
        started = time.perf_counter()
        result: StructuredOutput = await llm.astructured_predict(output_cls, PromptTemplate(prompt_text))
        steps.append(WorkflowStepTrace(
            step_name=step_name.value,
            prompt_id=self.step_prompts[step_name].id,
            input=prompt_text,
            output=result.model_dump(mode="json"),
            model=llm.metadata.model_name,
            latency_ms=round((time.perf_counter() - started) * 1000),
        ))
        return result

    @step
    async def reason_and_route(self,
                               ev: QueryStartEvent | ToolExecutedEvent,
                               ctx: Context
                               ) -> RoutedEvent | ReadyToAnswerEvent:
        """
        The reasoning step: entered once at the start of the query and again after
        every tool execution. Decides whether more tool calls are needed (RoutedEvent)
        or there is enough context to answer (ReadyToAnswerEvent).
        """
        if isinstance(ev, QueryStartEvent):
            # Seeded fresh here rather than threaded in via QueryStartEvent: a
            # list[WorkflowStepTrace]-typed Event field gets rebuilt into a brand-new
            # list by Pydantic validation the moment the Event is constructed (unlike
            # `progress`, an arbitrary class Pydantic just passes through by
            # reference) -- confirmed directly, appends made after that point never
            # reached whatever list the outer pipeline originally passed in. `steps`
            # and the plain `data_as_of` datetime are the only things ever put into
            # ctx.store; `progress` is threaded
            # through event fields instead because ctx.store.set() deep-copies the
            # whole accumulated state on every call, which breaks the instant
            # anything non-deepcopyable, like progress's live asyncio.Queue, is
            # already sitting in it. The outer pipeline (ProposedWorkflowRag.query())
            # retrieves the real accumulated list back out via handler.ctx.store
            # after the run completes, rather than relying on shared object identity.
            await ctx.store.set("steps", [])
            await ctx.store.set("data_as_of", ev.data_as_of)
            observations: list[ToolObservation] = []
            iteration = 0
        else:
            observations = ev.observations
            iteration = ev.iteration
        steps = await ctx.store.get("steps")
        data_as_of: Optional[datetime] = await ctx.store.get("data_as_of")

        def ready(hit_max_iterations: bool,
                  refused: bool = False,
                  refuse_reason: Optional[str] = None,
                  blocked: bool = False) -> ReadyToAnswerEvent:
            
            return ReadyToAnswerEvent(
                chat_request=ev.chat_request,
                progress=ev.progress,
                chat_history=ev.chat_history,
                context_str=ev.context_str,
                observations=observations,
                hit_max_iterations=hit_max_iterations,
                refused=refused,
                refuse_reason=refuse_reason,
                blocked=blocked,
            )

        #! blocked -- no LLM call. The database refused the last call because the agent's
        #! user can only read; no rewrite of the query changes that, so stop and say so.
        if observations and observations[-1].status == ToolStatus.BLOCKED:
            logging.info("[ProposedRAGWorkflow] last tool call was blocked by the database, answering")
            await ev.progress.update("The database refused that as a write. This assistant is read-only...")
            steps.append(WorkflowStepTrace(
                step_name=WorkflowStepName.REASON.value,
                prompt_id=None,  # forced, no LLM call
                input=observations[-1].result,
                output={"action": ReasonAction.ANSWER.value, "tool_name": None,
                        "reasoning": "forced: the last tool call was blocked (read-only database user)"},
            ))
            return ready(hit_max_iterations=False, blocked=True)

        #! hard cap -- no LLM call, straight to answering with what we have
        if iteration >= self.max_iterations:
            logging.info(f"[ProposedRAGWorkflow] hit max_iterations ({self.max_iterations}), forcing answer")
            await ev.progress.update("Reached the tool-call limit, preparing an answer...")
            steps.append(WorkflowStepTrace(
                step_name=WorkflowStepName.REASON.value,
                prompt_id=None,  # forced, no LLM call
                input=f"iteration {iteration}/{self.max_iterations}",
                output={"action": ReasonAction.ANSWER.value, "tool_name": None,
                        "reasoning": f"forced: reached max_iterations ({self.max_iterations})"},
            ))
            return ready(hit_max_iterations=True)

        await ev.progress.update(
            "Deciding which tool best answers this question..." if iteration == 0
            else "Checking whether there is enough information to answer..."
        )

        prompt_text = (
            f"{self.step_prompts[WorkflowStepName.REASON].text}\n\n"
            f"{_as_of_note(data_as_of)}\n\n"
            f"Conversation so far:\n{ev.context_str}\n\n"
            f"Analyst's question: {ev.chat_request.user_input}\n\n"
            f"Tool calls made so far ({iteration}/{self.max_iterations}):\n"
            f"{_format_observations(observations)}\n\n"
            f"Reason about the question and report the facts."
        )

        decision: ReasoningDecision = await self._predict(
            WorkflowStepName.REASON, ReasoningDecision, prompt_text, steps
        )
        # the next step is derived from the facts the LLM reported, not picked by it;
        # recorded in the trace so the reflector sees which branch actually ran
        action: ReasonAction = decision.action
        steps[-1].output["action"] = action.value

        if action == ReasonAction.REFUSE:
            logging.info(f"[ProposedRAGWorkflow] refused: {decision.refuse_reason}")
            return ready(hit_max_iterations=False, refused=True, refuse_reason=decision.refuse_reason)

        if action == ReasonAction.ANSWER:
            logging.info(f"[ProposedRAGWorkflow] ready to answer after {iteration} tool call(s): {decision.reasoning}")
            return ready(hit_max_iterations=False)

        # needs more data: must route to a tool. Answering here instead (the old
        # behaviour) would synthesize from data the model itself said was missing.
        if decision.tool_name is None:
            logging.warning("[ProposedRAGWorkflow] needs_more_data without a tool_name, defaulting to query_sql")
            tool_name = ToolName.QUERY_SQL
        else:
            tool_name = ToolName(decision.tool_name)

        if tool_name == ToolName.SEARCH_FRAUD_PATTERNS:
            # Enforced here, not only in the prompt: a web search with no store evidence has
            # nothing to abstract (and nothing to ground), and a second one rarely adds to the first.
            # Evidence from an earlier turn counts: "is this a known scam?" is often a follow-up.
            if any(o.tool_name == ToolName.SEARCH_FRAUD_PATTERNS.value and o.status == ToolStatus.SUCCESS
                   for o in observations):
                logging.info("[ProposedRAGWorkflow] web search already done for this question, answering")
                return ready(hit_max_iterations=False)
            if not ev.context_str and not any(o.tool_name in STORE_TOOLS and o.status == ToolStatus.SUCCESS
                                              for o in observations):
                logging.warning("[ProposedRAGWorkflow] web search routed before any store result, using query_sql first")
                tool_name = ToolName.QUERY_SQL
        logging.info(f"[ProposedRAGWorkflow] routed to {tool_name.value}: {decision.reasoning}")
        await ev.progress.update(f"Routing to {tool_name.value}...")

        return RoutedEvent(
            chat_request=ev.chat_request,
            progress=ev.progress,
            chat_history=ev.chat_history,
            context_str=ev.context_str,
            tool_name=tool_name,
            reasoning=decision.reasoning,
            observations=observations,
            iteration=iteration,
        )

    @step
    async def fetch_schema(self, ev: RoutedEvent, ctx: Context) -> SchemaFetchedEvent:
        """Fetches the schema for whichever tool was routed to -- the schema is always
        read before any SQL or search arguments are written."""
        progress = ev.progress
        steps = await ctx.store.get("steps")
        await progress.update(f"Fetching {ev.tool_name.value} schema...")

        schema_call: ToolCall = await self.tools[SCHEMA_TOOLS[ev.tool_name]].__call__()
        schema_text: str = schema_call.output_text

        steps.append(WorkflowStepTrace(
            step_name=WorkflowStepName.FETCH_SCHEMA.value,
            prompt_id=None,
            input=ev.tool_name.value,
            output=schema_text,
        ))

        return SchemaFetchedEvent(
            chat_request=ev.chat_request,
            progress=ev.progress,
            chat_history=ev.chat_history,
            context_str=ev.context_str,
            tool_name=ev.tool_name,
            reasoning=ev.reasoning,
            schema_text=schema_text,
            observations=ev.observations,
            iteration=ev.iteration,
        )

    @step
    async def execute_tool(self, ev: SchemaFetchedEvent, ctx: Context) -> ToolExecutedEvent:
        """Generates the tool's call arguments (schema-validated, not free-form JSON
        parsing) and executes it directly.
        Earlier calls' results are shown to the model so a follow-up call can build on
        (or correct) them instead of repeating them."""
        progress = ev.progress
        steps = await ctx.store.get("steps")
        data_as_of: Optional[datetime] = await ctx.store.get("data_as_of")
        previous_calls = _format_observations(ev.observations)

        if ev.tool_name == ToolName.QUERY_SQL:
            await progress.update("Writing SQL query...")
            prompt_text = (
                f"{self.step_prompts[WorkflowStepName.GENERATE_SQL_ARGS].text}\n\n"
                f"Schema:\n{ev.schema_text}\n\n"
                f"{_as_of_note(data_as_of)}{_sql_clock_rule(data_as_of)}\n\n"
                f"Conversation so far:\n{ev.context_str}\n\n"
                f"Analyst's question: {ev.chat_request.user_input}\n\n"
                f"Tool calls already made for this question:\n{previous_calls}\n\n"
                f"Why this call is being made: {ev.reasoning}"
            )
            args: SQLCallArgs = await self._predict(
                WorkflowStepName.GENERATE_SQL_ARGS, SQLCallArgs, prompt_text, steps
            )
            await progress.update("Executing SQL query...")
            call: ToolCall = await self.tools[ToolName.QUERY_SQL].__call__(
                sql=args.sql,
                generate_chart=args.generate_chart,
                chart_type=args.chart_type,
                x_column=args.x_column,
                y_column=args.y_column,
                value_column=args.value_column,
                as_of=_as_of_literal(data_as_of),
            )
        elif ev.tool_name == ToolName.SEARCH_FRAUD_PATTERNS:
            await progress.update("Describing the pattern without customer data...")
            prompt_text = (
                f"{self.step_prompts[WorkflowStepName.GENERATE_WEB_SEARCH_ARGS].text}\n\n"
                f"Search guide:\n{ev.schema_text}\n\n"
                f"Conversation so far:\n{ev.context_str}\n\n"
                f"Analyst's question: {ev.chat_request.user_input}\n\n"
                f"Tool calls already made for this question:\n{previous_calls}\n\n"
                f"Why this call is being made: {ev.reasoning}"
            )
            args: WebSearchCallArgs = await self._predict(
                WorkflowStepName.GENERATE_WEB_SEARCH_ARGS, WebSearchCallArgs, prompt_text, steps
            )
            await progress.update(f"Searching the web for known patterns: \"{args.query}\"...")
            call: ToolCall = await self.tools[ToolName.SEARCH_FRAUD_PATTERNS].__call__(
                query=args.query,
                max_results=args.max_results,
            )
        else:
            await progress.update("Building session search query...")
            prompt_text = (
                f"{self.step_prompts[WorkflowStepName.GENERATE_VECTOR_ARGS].text}\n\n"
                f"Schema:\n{ev.schema_text}\n\n"
                f"{_as_of_note(data_as_of)}\n\n"
                f"Conversation so far:\n{ev.context_str}\n\n"
                f"Analyst's question: {ev.chat_request.user_input}\n\n"
                f"Tool calls already made for this question:\n{previous_calls}\n\n"
                f"Why this call is being made: {ev.reasoning}"
            )
            args: VectorCallArgs = await self._predict(
                WorkflowStepName.GENERATE_VECTOR_ARGS, VectorCallArgs, prompt_text, steps
            )
            await progress.update("Searching session history...")
            call: ToolCall = await self.tools[ToolName.QUERY_SESSION_VECTOR_HYBRID].__call__(
                query=args.query,
                limit=args.limit,
                filter_customer_email=args.filter_customer_email,
                filter_device_id=args.filter_device_id,
                filter_ip_country=args.filter_ip_country,
                filter_start_date=args.filter_start_date,
                filter_end_date=args.filter_end_date,
                filter_event_count=args.filter_event_count,
                filter_declined_payments=args.filter_declined_payments,
            )

        # An invalid query never ran, so it used none of the question's budget: its repair
        # is free while free repairs remain. Everything else -- a result, an empty result,
        # a timeout, a runtime error -- is a call that ran, and counts.
        repairs_used: int = sum(1 for o in ev.observations if o.error_type == ToolErrorType.INVALID_QUERY)
        free_repair: bool = (call.error_type == ToolErrorType.INVALID_QUERY
                             and repairs_used < self.max_free_repairs)
        if free_repair:
            await progress.update("The database rejected that query before running it. Repairing it...")

        return ToolExecutedEvent(
            chat_request=ev.chat_request,
            progress=ev.progress,
            chat_history=ev.chat_history,
            context_str=ev.context_str,
            observations=[*ev.observations, ToolObservation(
                tool_name=ev.tool_name.value,
                arguments=args.model_dump(mode="json"),
                result=call.output_text,
                status=call.status,
                error_type=call.error_type,
            )],
            iteration=ev.iteration if free_repair else ev.iteration + 1,
        )

    @step
    async def synthesize_answer(self, ev: ReadyToAnswerEvent, ctx: Context) -> AnsweredEvent:
        """Writes the analyst-facing answer from whatever the reasoning loop gathered.
        The synthesize step prompt carries only presentation/accuracy rules -- no routing or
        tool-calling instructions, which confuse the model into disclaiming a
        follow_up_question_generator call it was never meant to make itself."""
        progress = ev.progress
        steps = await ctx.store.get("steps")
        data_as_of: Optional[datetime] = await ctx.store.get("data_as_of")
        # the one step whose model is chosen per run: see ReadyToAnswerEvent.synthesis_tier
        tier: ModelTier = ev.synthesis_tier
        model_name: str = self.llms[tier].metadata.model_name
        logging.info(f"[ProposedRAGWorkflow] synthesizing on the {tier.value} tier ({model_name})")
        await progress.update(
            f"Combining {sum(1 for o in ev.observations if o.status == ToolStatus.SUCCESS)} results into an answer with {model_name}..."
            if tier == ModelTier.REASONING
            else f"Writing the answer with {model_name}..."
        )

        limit_note = (
            f"The tool-call limit ({self.max_iterations}) was reached before the reasoning step "
            f"judged the results complete. Answer as fully as the results allow, and state "
            f"clearly what could not be determined.\n\n"
            if ev.hit_max_iterations else ""
        )
        refusal_note = (
            f"The reasoning step judged this question out of scope"
            f"{f': {ev.refuse_reason}' if ev.refuse_reason else ''}. "
            f"Do not answer it -- reply with the out-of-scope message.\n\n"
            if ev.refused else ""
        )
        blocked_note = (
            "The last tool call was BLOCKED by the database: this assistant's database user can "
            "only read the store's tables (customers, sessions, events, orders, payments, "
            "refunds, products, promo codes). Nothing was changed. Tell the analyst this "
            "assistant is read-only and cannot do that, then give what the earlier results "
            "(if any) show.\n\n"
            if ev.blocked else ""
        )
        prompt_text = (
            f"{self.step_prompts[WorkflowStepName.SYNTHESIZE_ANSWER].text}\n\n"
            f"{_as_of_note(data_as_of)} Name the absolute dates any relative period resolved to. "
            f"The answer already opens with a line saying it was treated as asked at that time -- "
            f"do not repeat it.\n\n"
            f"Conversation so far:\n{ev.context_str}\n\n"
            f"Analyst's question: {ev.chat_request.user_input}\n\n"
            f"Tool calls made:\n{_format_observations(ev.observations)}\n\n"
            f"{limit_note}"
            f"{refusal_note}"
            f"{blocked_note}"
            f"Write the final response to the analyst."
        )
        final: FinalAnswer = await self._predict(
            WorkflowStepName.SYNTHESIZE_ANSWER, FinalAnswer, prompt_text, steps, tier=tier
        )

        # added in code, not left to the model, so every answer carries it; a refusal has no
        # data behind it to date
        answer: str = (
            _as_of_disclaimer(data_as_of) + final.answer
            if data_as_of is not None and not ev.refused
            else final.answer
        )
        return AnsweredEvent(chat_request=ev.chat_request, progress=ev.progress, answer=answer)

    @step
    async def generate_follow_up(self, ev: AnsweredEvent, ctx: Context) -> StopEvent:
        """Always the last step: generates the follow-up questions. A failure here must
        never take down an otherwise-successful answer, so it's caught and logged
        rather than propagated."""
        progress = ev.progress
        steps = await ctx.store.get("steps")
        await progress.update("Generating follow-up questions...")

        prompt_text = (
            f"{self.step_prompts[WorkflowStepName.GENERATE_FOLLOW_UP].text}\n\n"
            f"Analyst's question: {ev.chat_request.user_input}\n"
            f"Final answer given: {ev.answer}\n\n"
            f"Generate 2-3 follow-up questions."
        )
        try:
            # _predict records the step as soon as the LLM call itself succeeds, before
            # the tool call below -- so a failure in the tool invocation doesn't erase
            # the record that this step's generation did complete.
            follow_up: FollowUpQuestions = await self._predict(
                WorkflowStepName.GENERATE_FOLLOW_UP, FollowUpQuestions, prompt_text, steps
            )
            await self.tools[ToolName.FOLLOW_UP_QUESTION_GENERATOR].__call__(
                generated_questions=[q.model_dump() for q in follow_up.generated_questions]
            )
        except Exception as e:
            logging.warning(f"[ProposedRAGWorkflow] follow-up generation failed, continuing without it: {e}")

        return StopEvent(result=ev.answer)
