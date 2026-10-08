from server.chat_agent.Pipeline.workflow.events import (
    QueryStartEvent,
    RoutedEvent,
    SchemaFetchedEvent,
    ToolExecutedEvent,
    ReadyToAnswerEvent,
    AnsweredEvent,
)
from server.chat_agent.Pipeline.workflow.enums import ReasonAction, WorkflowStepName
from server.prompt.schemas import Prompt

from llama_index.core.workflow import Workflow, StartEvent, StopEvent, Event, step, Context
from server.chat_agent.tools.enums import ToolName
from server.chat_agent.schemas import WorkflowStepTrace
from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.prompts import PromptTemplate

from server.chat_agent.Pipeline.workflow.schemas import (
    ReasoningDecision,
    ToolObservation,
    SQLCallArgs,
    VectorCallArgs,
    FinalAnswer,
    FollowUpQuestions
    )
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from server.chat_agent.tools.tool import AgentTool
# =====================================================================
# WORKFLOW: reason -> (schema -> execute -> reason)* -> synthesize
#           -> follow-up, with at most max_iterations tool calls
# =====================================================================


def _now_sgt() -> str:
    # arg generation needs "now" to turn "last 7 days" / "today" into concrete dates
    return datetime.now(ZoneInfo("Asia/Singapore")).strftime("%Y-%m-%d %H:%M (%A), SGT")


def _format_observations(observations: list[ToolObservation]) -> str:
    if not observations:
        return "None yet."
    return "\n\n".join(
        f"[{i}] {o.tool_name}\nArguments: {o.arguments}\nResult:\n{o.result}"
        for i, o in enumerate(observations, start=1)
    )


class ProposedRAGWorkflow(Workflow):
    def __init__(self,
                 tools : dict[ToolName, AgentTool],
                 llm: LLM,
                 step_prompts: dict[WorkflowStepName, Prompt],
                 max_iterations: int = 3,
                 timeout: float = 180.0,
                 ):
        # generous timeout: each iteration is 2 sequential LLM calls plus a tool
        # execution, on top of the synthesize/follow-up calls -- the llama_index
        # Workflow default (10s) is nowhere near enough.
        super().__init__(timeout=timeout)

        self.tools : dict[ToolName, AgentTool] = tools
        self.llm = llm
        # one versioned Prompt per LLM step (see ProposedWorkflowRag.setup_agent); each
        # step records its prompt's id in WorkflowStepTrace, so the reflector can tell
        # exactly which prompt version produced a bad step
        self.step_prompts : dict[WorkflowStepName, Prompt] = step_prompts
        # cap on tool calls per query; once reached, reason_and_route is forced
        # to emit ReadyToAnswerEvent with whatever it has gathered.
        self.max_iterations = max_iterations

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
            # is the only thing ever put into ctx.store; `progress` is threaded
            # through event fields instead because ctx.store.set() deep-copies the
            # whole accumulated state on every call, which breaks the instant
            # anything non-deepcopyable, like progress's live asyncio.Queue, is
            # already sitting in it. The outer pipeline (ProposedWorkflowRag.query())
            # retrieves the real accumulated list back out via handler.ctx.store
            # after the run completes, rather than relying on shared object identity.
            await ctx.store.set("steps", [])
            observations: list[ToolObservation] = []
            iteration = 0
        else:
            observations = ev.observations
            iteration = ev.iteration
        steps = await ctx.store.get("steps")

        def ready(hit_max_iterations: bool,
                  refused: bool = False,
                  refuse_reason: Optional[str] = None) -> ReadyToAnswerEvent:
            return ReadyToAnswerEvent(
                chat_request=ev.chat_request,
                progress=ev.progress,
                chat_history=ev.chat_history,
                context_str=ev.context_str,
                observations=observations,
                hit_max_iterations=hit_max_iterations,
                refused=refused,
                refuse_reason=refuse_reason,
            )

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
            f"Conversation so far:\n{ev.context_str}\n\n"
            f"Analyst's question: {ev.chat_request.user_input}\n\n"
            f"Tool calls made so far ({iteration}/{self.max_iterations}):\n"
            f"{_format_observations(observations)}\n\n"
            f"Reason about the question and report the facts."
        )

        decision: ReasoningDecision = await self.llm.astructured_predict(
            ReasoningDecision,
            PromptTemplate(prompt_text)
        )
        # the next step is derived from the facts the LLM reported, not picked by it;
        # recorded in the trace so the reflector sees which branch actually ran
        action: ReasonAction = decision.action
        steps.append(WorkflowStepTrace(
            step_name=WorkflowStepName.REASON.value,
            prompt_id=self.step_prompts[WorkflowStepName.REASON].id,
            input=prompt_text,
            output={**decision.model_dump(mode="json"), "action": action.value},
        ))

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

        if ev.tool_name == ToolName.QUERY_SQL:
            schema_text = await self.tools[ToolName.GET_SQL_SCHEMA].__call__()
        else:
            schema_text = await self.tools[ToolName.GET_SESSION_VECTOR_HYBRID_SCHEMA].__call__()

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
        previous_calls = _format_observations(ev.observations)

        if ev.tool_name == ToolName.QUERY_SQL:
            await progress.update("Writing SQL query...")
            prompt_text = (
                f"{self.step_prompts[WorkflowStepName.GENERATE_SQL_ARGS].text}\n\n"
                f"Schema:\n{ev.schema_text}\n\n"
                f"Current time: {_now_sgt()}\n\n"
                f"Conversation so far:\n{ev.context_str}\n\n"
                f"Analyst's question: {ev.chat_request.user_input}\n\n"
                f"Tool calls already made for this question:\n{previous_calls}\n\n"
                f"Why this call is being made: {ev.reasoning}"
            )
            args: SQLCallArgs = await self.llm.astructured_predict(
                SQLCallArgs, PromptTemplate(prompt_text)
            )
            steps.append(WorkflowStepTrace(
                step_name=WorkflowStepName.GENERATE_SQL_ARGS.value,
                prompt_id=self.step_prompts[WorkflowStepName.GENERATE_SQL_ARGS].id,
                input=prompt_text,
                output=args.model_dump(mode="json"),
            ))
            await progress.update("Executing SQL query...")
            result = await self.tools[ToolName.QUERY_SQL].__call__(
                sql=args.sql,
                generate_chart=args.generate_chart,
                chart_type=args.chart_type,
                x_column=args.x_column,
                y_column=args.y_column,
                value_column=args.value_column,
            )
        else:
            await progress.update("Building session search query...")
            prompt_text = (
                f"{self.step_prompts[WorkflowStepName.GENERATE_VECTOR_ARGS].text}\n\n"
                f"Schema:\n{ev.schema_text}\n\n"
                f"Current time: {_now_sgt()}\n\n"
                f"Conversation so far:\n{ev.context_str}\n\n"
                f"Analyst's question: {ev.chat_request.user_input}\n\n"
                f"Tool calls already made for this question:\n{previous_calls}\n\n"
                f"Why this call is being made: {ev.reasoning}"
            )
            args: VectorCallArgs = await self.llm.astructured_predict(
                VectorCallArgs, PromptTemplate(prompt_text)
            )
            steps.append(WorkflowStepTrace(
                step_name=WorkflowStepName.GENERATE_VECTOR_ARGS.value,
                prompt_id=self.step_prompts[WorkflowStepName.GENERATE_VECTOR_ARGS].id,
                input=prompt_text,
                output=args.model_dump(mode="json"),
            ))
            await progress.update("Searching session history...")
            result = await self.tools[ToolName.QUERY_SESSION_VECTOR_HYBRID].__call__(
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

        return ToolExecutedEvent(
            chat_request=ev.chat_request,
            progress=ev.progress,
            chat_history=ev.chat_history,
            context_str=ev.context_str,
            observations=[*ev.observations, ToolObservation(
                tool_name=ev.tool_name.value,
                arguments=args.model_dump(mode="json"),
                result=str(result),
            )],
            iteration=ev.iteration + 1,
        )

    @step
    async def synthesize_answer(self, ev: ReadyToAnswerEvent, ctx: Context) -> AnsweredEvent:
        """Writes the analyst-facing answer from whatever the reasoning loop gathered.
        The synthesize step prompt carries only presentation/accuracy rules -- no routing or
        tool-calling instructions, which confuse the model into disclaiming a
        follow_up_question_generator call it was never meant to make itself."""
        progress = ev.progress
        steps = await ctx.store.get("steps")
        await progress.update("Synthesizing final answer...")

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
        prompt_text = (
            f"{self.step_prompts[WorkflowStepName.SYNTHESIZE_ANSWER].text}\n\n"
            f"Conversation so far:\n{ev.context_str}\n\n"
            f"Analyst's question: {ev.chat_request.user_input}\n\n"
            f"Tool calls made:\n{_format_observations(ev.observations)}\n\n"
            f"{limit_note}"
            f"{refusal_note}"
            f"Write the final response to the analyst."
        )
        final: FinalAnswer = await self.llm.astructured_predict(
            FinalAnswer, PromptTemplate(prompt_text)
        )

        steps.append(WorkflowStepTrace(
            step_name=WorkflowStepName.SYNTHESIZE_ANSWER.value,
            prompt_id=self.step_prompts[WorkflowStepName.SYNTHESIZE_ANSWER].id,
            input=prompt_text,
            output=final.model_dump(mode="json"),
        ))

        return AnsweredEvent(chat_request=ev.chat_request, progress=ev.progress, answer=final.answer)

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
            follow_up: FollowUpQuestions = await self.llm.astructured_predict(
                FollowUpQuestions, PromptTemplate(prompt_text)
            )
            # logged as soon as the LLM call itself succeeds, before the tool call
            # below -- so a failure in the tool invocation doesn't erase the record
            # that this step's generation did complete.
            steps.append(WorkflowStepTrace(
                step_name=WorkflowStepName.GENERATE_FOLLOW_UP.value,
                prompt_id=self.step_prompts[WorkflowStepName.GENERATE_FOLLOW_UP].id,
                input=prompt_text,
                output=follow_up.model_dump(mode="json"),
            ))
            await self.tools[ToolName.FOLLOW_UP_QUESTION_GENERATOR].__call__(
                generated_questions=[q.model_dump() for q in follow_up.generated_questions]
            )
        except Exception as e:
            logging.warning(f"[ProposedRAGWorkflow] follow-up generation failed, continuing without it: {e}")

        return StopEvent(result=ev.answer)
