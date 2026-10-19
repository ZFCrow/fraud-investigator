"""
proposed_pipeline.py

A complete, self-contained workflow-based RAG pipeline for the fraud-investigation chat agent.
Consolidates what's currently split across Events.py / RAGWorkflow.py / pipeline.py into
one file, and finishes what that split skeleton only stubbed out (routing picked a tool
and then just stopped -- it never actually fetched a schema, executed the tool, or
produced a real answer).

The graph is a fixed, explicit, inspectable route rather than an open-ended agent loop:

    build memory -> reason: call a tool, or ready to answer?
                     call a tool -> fetch that tool's schema -> generate its call
                                    arguments -> execute it -> back to reason
                     ready       -> synthesize a final answer -> generate follow-ups

The reason step is capped at max_iterations tool calls, after which it is forced to
answer with whatever it has gathered.

Structured LLM calls use `llm.astructured_predict(...)`, matching the pattern already
established in server/evaluation/LLMEvaluator.py, rather than function-calling -- each step invokes
its tool directly with LLM-generated, schema-validated arguments.
"""

import asyncio
import logging
from datetime import datetime


from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.prompts import PromptTemplate


from server.chat_agent.Pipeline.BaseRAGPipeline import BaseRAGPipeline
from server.chat_agent.tools.FollowUpTool import FollowUpTool

from server.prompt.repository import IPromptRepository
from server.prompt.schemas import Prompt
from server.vector.repository import IVectorQueryRepository
from shared.cache.ICacheRepository import ICacheRepository
from shared.embeddings.EmbeddingService import EmbeddingService

from server.chat_agent.tools.SQLQuery.repository import IStoreQueryRepository
from server.chat_agent.tools.SQLQuery.retrieval_tool import SQLQueryTool
from server.chat_agent.tools.WebSearch.repository import IWebSearchRepository
from server.chat_agent.tools.WebSearch.retrieval_tool import FraudPatternSearchTool
from server.chat_agent.tools.WebSearch.schema_tool import FraudPatternSearchSchemaTool
from server.chat_agent.tools.SQLQuery.schema_tool import SQLSchemaTool

from server.chat_agent.tools.VectorRetrieval.retrieval_tool import SessionRetrievalTool
from server.chat_agent.tools.VectorRetrieval.schema_tool import SessionVectorStoreSchemaTool

from server.chat_agent.repository.repository import IChatRepository
from server.chat_agent.schemas import AgentTrace, WorkflowAgentTrace, ChatRequest, ToolCall, WorkflowStepTrace
from server.chat_agent.tools.enums import ToolName


from server.evaluation.service import EvaluationService
from server.core.stream.progressReporter import ProgressReporter

from server.chat_agent.Pipeline.workflow.workflow import ProposedRAGWorkflow
from server.chat_agent.Pipeline.workflow.enums import ModelTier, WorkflowStepName, PROMPTED_STEPS
from typing import Optional 

# =====================================================================
# OUTER PIPELINE CLASS -- lifecycle/bookkeeping around the graph
# (memory build, trace insert/cache, evaluation)
# =====================================================================

class ProposedWorkflowRag(BaseRAGPipeline):
    def __init__(self,
                 embedding_service: EmbeddingService,
                 vector_repo: IVectorQueryRepository,
                 store_repo: IStoreQueryRepository,
                 chat_repo: IChatRepository,
                 cache_repo: ICacheRepository,
                 prompt_repo: IPromptRepository,
                 web_search_repo: IWebSearchRepository,
                 llms: dict[ModelTier, LLM],
                 evaluation_service: EvaluationService,
                 ):

        self.pipeline: Optional[ProposedRAGWorkflow] = None

        self.embedding_service = embedding_service
        self.vector_repo = vector_repo
        self.store_repo = store_repo
        self.chat_repo = chat_repo
        self.cache_repo = cache_repo
        self.prompt_repo = prompt_repo
        self.web_search_repo = web_search_repo
        self.llms = llms
        self.evaluation_service = evaluation_service

        self.tools_called: list[ToolCall] = []
        self.follow_up_questions: list[dict] = []
        self.charts_to_send: list[str] = []
        self.steps_taken: list[WorkflowStepTrace] = []

        self.tools : dict[ToolName, any] = {}  # List to hold tool instances for the workflow 

    @classmethod
    async def create(cls,
                     embedding_service: EmbeddingService,
                     vector_repo: IVectorQueryRepository,
                     store_repo: IStoreQueryRepository,
                     chat_repo: IChatRepository,
                     cache_repo: ICacheRepository,
                     prompt_repo: IPromptRepository,
                     web_search_repo: IWebSearchRepository,
                     llms: dict[ModelTier, LLM],
                     evaluation_service: EvaluationService = EvaluationService(),
                     ) -> "ProposedWorkflowRag":

        agent = cls(
            embedding_service=embedding_service,
            vector_repo=vector_repo,
            store_repo=store_repo,
            chat_repo=chat_repo,
            cache_repo=cache_repo,
            prompt_repo=prompt_repo,
            web_search_repo=web_search_repo,
            llms=llms,
            evaluation_service=evaluation_service,
        )
        await agent._init_pipeline()
        return agent

    async def _init_pipeline(self) -> None:
        #? TOOL INSTANCES
        #? =================================================================
        session_vector_retrieval_tool = SessionRetrievalTool(
            self.vector_repo, self.embedding_service,
            self.cache_repo, self.tools_called)
        session_vector_store_schema_tool = SessionVectorStoreSchemaTool(self.tools_called)

        sql_query_tool = SQLQueryTool(self.store_repo,
                                      tools_called=self.tools_called,
                                      charts_to_send=self.charts_to_send)
        sql_schema_tool = SQLSchemaTool(self.tools_called)

        fraud_pattern_search_tool = FraudPatternSearchTool(self.web_search_repo, self.tools_called)
        fraud_pattern_search_schema_tool = FraudPatternSearchSchemaTool(self.tools_called)

        follow_up_tool = FollowUpTool(tools_called=self.tools_called,
                                      follow_up_questions=self.follow_up_questions)
        #? =================================================================

        self.tools[ToolName.QUERY_SESSION_VECTOR_HYBRID] = session_vector_retrieval_tool
        self.tools[ToolName.QUERY_SQL] = sql_query_tool

        self.tools[ToolName.GET_SESSION_VECTOR_HYBRID_SCHEMA] = session_vector_store_schema_tool
        self.tools[ToolName.GET_SQL_SCHEMA] = sql_schema_tool

        self.tools[ToolName.SEARCH_FRAUD_PATTERNS] = fraud_pattern_search_tool
        self.tools[ToolName.GET_FRAUD_PATTERN_SEARCH_SCHEMA] = fraud_pattern_search_schema_tool

        self.tools[ToolName.FOLLOW_UP_QUESTION_GENERATOR] = follow_up_tool


        await self.setup_agent()

    async def setup_agent(self, prompt: Optional[Prompt] = None) -> None:
        """
        (Re)builds the workflow graph with the active versioned prompt of every LLM step.

        `prompt` is a candidate for ONE step -- the multi-step reflector's rewrite, applied
        through offline_evaluator.evaluate(prompt). It replaces only the step its type maps
        to; every other step keeps its active version, so a re-evaluation measures that one
        edit. A prompt of any other type (e.g. EVALUATOR_PROMPT) has no step here and
        is ignored.
        """
        step_prompts : dict[WorkflowStepName, Prompt] = {}
        for step in PROMPTED_STEPS:
            active : Optional[Prompt] = await self.prompt_repo.get_active_prompt(step.prompt_type)
            if active is None:
                raise ValueError(f"No active prompt for workflow step {step.value} ({step.prompt_type.value}) "
                                 f"-- run PostgresPromptRepository.setup() first.")
            step_prompts[step] = active

        if prompt is not None:
            candidate_step : Optional[WorkflowStepName] = WorkflowStepName.from_prompt_type(prompt.type)
            if candidate_step is None:
                logging.warning(f"[ProposedWorkflowRag] setup_agent ignored a {prompt.type.value} prompt -- "
                                f"it is not a workflow step prompt")
            else:
                logging.info(f"[ProposedWorkflowRag] using candidate prompt {prompt.id} for step {candidate_step.value}")
                step_prompts[candidate_step] = prompt

        self.pipeline = ProposedRAGWorkflow(
            tools = self.tools,
            llms=self.llms,
            step_prompts=step_prompts,
        )

    async def query(self,
                    chat_request: ChatRequest,
                    progress: ProgressReporter = ProgressReporter()
                    ) -> AgentTrace:

        
        #!=====================================================================================
        #! RESET THE TOOLS CALLED AND FOLLOW UP QUESTIONS FOR EACH QUERY
        #!=====================================================================================
        self.tools_called.clear()
        self.follow_up_questions.clear()
        self.charts_to_send.clear()
        self.steps_taken.clear()
        #!=====================================================================================

        #!============================================================================
        #! BUILDING CHAT MEMORY -- cache first, db fallback. Built once, here, and handed into the workflow via .run() -- the
        #! workflow's job is to make sense of context it's given, not to own fetching
        #! it, and this same chat_hist also feeds the evaluation_service call below.
        #!============================================================================
        await progress.update("Retrieving past traces for this session...")

        redis_key = f"chat_memory:{chat_request.session_id}"
        chat_hist: list[ChatMessage] = []

        trace_list_bytes: list[bytes] = await self.cache_repo.get_list(redis_key)

        if len(trace_list_bytes) > 0:
            await progress.update("Found context in Redis. Building chat history from cached traces...")
            past_traces: list[AgentTrace] = [AgentTrace.model_validate_json(b) for b in trace_list_bytes]
        else:
            await progress.update("No context found in Redis. Retrieving from database...")
            past_traces: list[AgentTrace] = await self.chat_repo.get_trace_by_session_id(chat_request.session_id)

        for trace in past_traces:
            chat_hist.extend(trace.chat_messages())

        context_str = "\n".join(
            f"User: {m.content}" if m.role == "user" else f"Agent: {m.content}"
            for m in chat_hist
        )
        #!============================================================================
        #!============================================================================

        await progress.update("Analyzing input...")

        # every question is answered as of the end of the store's data, not the real clock
        # (read per query, so a reseed is picked up without a restart). The judge gets the
        # same time below.
        data_as_of: Optional[datetime] = await self.store_repo.get_data_as_of()

        response = "System Error: Response generation failed or was cancelled."
        handler = self.pipeline.run(
            chat_request=chat_request,
            progress=progress,
            chat_history=chat_hist,
            context_str=context_str,
            data_as_of=data_as_of,
        )
        try:
            response = await handler
            logging.info("WORKFLOW COMPLETE")
            await progress.answer(str(response))

            if self.charts_to_send:
                await progress.graph(self.charts_to_send)

            if self.follow_up_questions:
                await progress.actions(self.follow_up_questions)
            else:
                logging.info("No follow-up questions generated for this response.")

        except Exception as e:
            logging.error(f"PIPELINE - Error in run_workflow: {e}", exc_info=True)
            response = f"Error in run_workflow: {e}"
            await progress.error(str(response))

        finally:
            # Pulled back out of the graph's own Context rather than relying on
            # self.steps_taken having been mutated in place -- a
            # list[WorkflowStepTrace]-typed Event field gets rebuilt into a brand
            # new list by Pydantic validation, so appends inside the graph never
            # reached this object. handler.ctx is the same Context the run used
            # throughout, so this reflects whatever was accumulated even if the
            # run failed partway through (as long as reason_and_route's step got
            # far enough to seed the "steps" key at all).
            try:
                self.steps_taken = await handler.ctx.store.get("steps") or []
            except Exception:
                self.steps_taken = []

            agent_trace = WorkflowAgentTrace(
                input=chat_request.user_input,
                session_id=chat_request.session_id,
                output=str(response),
                tool_calls=self.tools_called,
                steps=self.steps_taken,
                agent_prompt_id=None,  # no single prompt -- each step's prompt_id is on its WorkflowStepTrace
            )

            #! ============================================================
            #! INSERT TRACE INTO DB
            #! ============================================================
            await progress.update("saving conversation...")
            await self.chat_repo.insert_trace(trace=agent_trace)
            # the tools that actually ran, for the UI's trace panel -- sent before the judge
            # starts, so it shows even when the evaluation fails
            await progress.metaData(agent_trace, "AGENT TRACE SENT")
            #! ============================================================

            #! ============================================================
            #! EVALUATION -- started here, awaited below
            #! ============================================================
            eval_task = asyncio.create_task(
                self.evaluation_service.evaluate(
                    og_user_input=chat_request.user_input,
                    trace=agent_trace,
                    chat_history=chat_hist,
                    data_as_of=data_as_of,
                    progress=progress
                )
            )
            eval_task.add_done_callback(
                lambda t: t.exception() and logging.error(f"evaluation failed for trace {agent_trace.id}: {t.exception()}")
            )
            #! ============================================================

            #! ============================================================
            #! set the context in redis for 1 hour
            #! ============================================================
            await self.cache_repo.add_to_list(redis_key, agent_trace.model_dump_json().encode("utf-8"), ttl=3600)
            #! ============================================================

            # the answer is already on screen; a streaming client keeps the stream open
            # until the judge is done so the evaluation (sent by EvaluationService) reaches
            # the UI. asyncio.wait, not await: a client disconnect must not cancel the eval.
            if progress.queue:
                await asyncio.wait([eval_task])

            # mark as done
            await progress.done(
                "END OF QUERY SERVICE (PROPOSED WORKFLOW) - ALL DONE"
            )

            return agent_trace
