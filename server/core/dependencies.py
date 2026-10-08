
from llama_index.llms.openai_like import OpenAILike
from llama_index.core.llms import LLM

from fastapi import Request, Depends, HTTPException 
from typing import Callable, AsyncGenerator
import redis.asyncio as aioredis
import logging

from server.chat_agent.repository.repository import IChatRepository
from server.chat_agent.repository.postgres_repository import PostGresChatRepository
from server.chat_agent.tools.SQLQuery.postgres_session_repository import PostgresStoreQueryRepository 
from server.chat_agent.tools.SQLQuery.repository import IStoreQueryRepository

from server.prompt.postgres_repository import PostgresPromptRepository
from server.prompt.repository import IPromptRepository
from shared.settings import settings
from shared.embeddings.EmbeddingService import EmbeddingService

from server.vector.repository import IVectorQueryRepository
from server.vector.qdrant_repository import QdrantRepository

from shared.cache import ICacheRepository
from shared.cache.RedisCacheRepository import RedisCacheRepository

from server.evaluation.service import EvaluationService 
from server.evaluation.IEvaluator import IEvaluator 
from server.evaluation.LLMEvaluator import LLMEvaluator

from server.evaluation.repository import IEvaluationRepository, PostgresEvaluationRepository



def get_db_factory(request: Request) -> Callable:
    return request.app.state.db_factory

#!! ======================================
#! VECTOR STORES 
#!! ======================================
async def get_qdrant(request: Request):
    return request.app.state.qdrant

# But for our clean factory, we can abstract it:
async def get_vector_repo(request: Request) -> IVectorQueryRepository:
    """
    Factory pattern for the vector repo. Takes `request`, not `qdrant_client`, on
    purpose — Qdrant is only one possible backend behind IVectorQueryRepository.
    Naming qdrant_client/get_qdrant in the signature would tie every future branch
    (a different vector store for some environment, a fake for TESTING, etc.) to a
    Qdrant-specific dependency it has no use for. Each branch pulls whatever
    resource its own backend needs — same shape as get_cache_repo.
    """
    match settings.ENVIRONMENT:
        case "DEVELOPMENT" | "PRODUCTION" | "TESTING" :
            qdrant_client = await get_qdrant(request)
            try:
                return QdrantRepository(qdrant_client)
            except Exception as e:
                logging.error(f"Error initializing QdrantRepository: {e}")
                raise HTTPException(status_code=500, detail="Failed to init Qdrant")

        case _:
            raise ValueError(f"Unsupported env: {settings.ENVIRONMENT}")
#!! ======================================
#!! ======================================

async def get_embedding_service(request: Request) -> EmbeddingService:
    return request.app.state.embedding_service
#!! ======================================
#!! ======================================

async def get_store_repo(
    db_factory: Callable = Depends(get_db_factory)
) -> AsyncGenerator[IStoreQueryRepository, None]:
    """
    Factory pattern for the store-data query repo, returning the implementation
    based on the current environment. Same db_factory-gated generator shape as
    get_chat_repo/get_evaluation_repo — every environment currently lands in the
    same Postgres branch (no file-based repo yet), but this keeps it ready
    for a TESTING case to slot in later without reshaping the function again.
    """
    match settings.ENVIRONMENT:
        case "DEVELOPMENT" | "PRODUCTION" | "TESTING":
            async with db_factory() as session:
                yield PostgresStoreQueryRepository(session)

        case _:
            raise ValueError(f"Unsupported environment: {settings.ENVIRONMENT}")
#!! ======================================
#!! ======================================



#!! ======================================
#! Agent Trace / Chat Repository Factory
#!! ======================================
async def get_chat_repo(db_factory: Callable = Depends(get_db_factory)) -> AsyncGenerator[IChatRepository, None]:
    """
    Generator dependency (like get_db) rather than a plain return, so that the
    Postgres branch's session only gets opened — and its `async with` scope only
    spans the request — when that branch is actually the one picked. TESTING never
    calls db_factory() at all, so a flaky/unreachable Postgres can't break TESTING
    requests that only ever hit FileChatRepository.
    """
    match settings.ENVIRONMENT:
        case "DEVELOPMENT" | "PRODUCTION":
            async with db_factory() as session:
                yield PostGresChatRepository(session)
        case "TESTING":
            raise ValueError(f"testing Environment should be created under tests/calibrations/dependencies")
        case _:
            raise ValueError(f"Unsupported environment: {settings.ENVIRONMENT}")
#!! ======================================
#!! ======================================

#!! ===================================== 
#! PROMPT REPOSITORY FACTORY 
#!! ===================================== 
async def get_prompt_repo(
        db_factory: Callable = Depends(get_db_factory)
) -> AsyncGenerator[IPromptRepository, None]:
    async with db_factory() as session: 
        yield PostgresPromptRepository(session)
#!! ===================================== 
#!! ===================================== 


#!! ======================================
#! Cache 
#!! ======================================

async def get_redis_client(request: Request) -> aioredis.Redis:
    return request.app.state.redis

async def get_redis_repo(redis: aioredis.Redis = Depends(get_redis_client)) -> RedisCacheRepository:
    return RedisCacheRepository(redis)

async def get_cache_repo(request: Request) -> ICacheRepository:
    match settings.ENVIRONMENT: 
        case "DEVELOPMENT" | "PRODUCTION" | "TESTING":
            redis_client = await get_redis_client(request) 
            return await get_redis_repo(redis_client)
        case _:
            raise ValueError(f"Unsupported environment: {settings.ENVIRONMENT}") 
#!! ======================================
#!! ======================================





#!! ===================================== 
#! EVALUATION SERVICE FACTORY 
#!! ===================================== 
async def get_evaluator() -> IEvaluator: 
    match settings.ENVIRONMENT:
        case "DEVELOPMENT" | "TESTING":
            # the judge runs on the cheaper fast model; falls back to the agent model
            # when MODEL_FAST is not set
            judge_model = settings.MODEL_FAST or settings.MODEL_AGENT
            logging.info(f"Using LLMEvaluator ({judge_model}) for environment: {settings.ENVIRONMENT}")
            return LLMEvaluator(llm=get_nebius_llm(judge_model))
        case _:
            raise ValueError(f"Unsupported environment: {settings.ENVIRONMENT}")  

async def get_evaluation_repo(
        db_factory: Callable = Depends(get_db_factory)
        ) -> AsyncGenerator[IEvaluationRepository, None]:
    """
    Generator dependency for the same reason as get_chat_repo: only open a Postgres
    session (spanning the request via async with) on the branch that actually needs
    one. TESTING never calls db_factory().
    """
    match settings.ENVIRONMENT:
        case "DEVELOPMENT" | "PRODUCTION":
            async with db_factory() as session:
                yield PostgresEvaluationRepository(session)
        case "TESTING":
            raise ValueError(f"testing Environment should be created under eval/dependencies")
        case _:
            raise ValueError(f"Unsupported environment: {settings.ENVIRONMENT}")

async def get_evaluation_service(
        evaluator = Depends(get_evaluator),
        eval_repo: IEvaluationRepository = Depends(get_evaluation_repo),
        prompt_repo : IPromptRepository = Depends(get_prompt_repo)
) -> EvaluationService:
    match settings.ENVIRONMENT:
        case "DEVELOPMENT":
            return EvaluationService(evaluator=evaluator, eval_repo=eval_repo, prompt_repo=prompt_repo)
        case "TESTING":
            raise ValueError(f"testing Environment should be created under eval/dependencies")
        case _:
            raise ValueError(f"Unsupported environment: {settings.ENVIRONMENT}")

#!! ===================================== 
#!! ==================================== 


#!! ==================================== 
#! LLMS 
#!! ==================================== 
def get_nebius_llm(model: str) -> LLM:
    """A Nebius Token Factory model, reached through its OpenAI-compatible API."""
    if not settings.NEBIUS_API_KEY or not model:
        raise HTTPException(
            status_code=500,
            detail="NEBIUS_API_KEY and a model id (MODEL_AGENT / MODEL_FAST) must be set to use Nebius"
        )
    return OpenAILike(
        model=model,
        api_base=settings.NEBIUS_BASE_URL,
        api_key=settings.NEBIUS_API_KEY,
        is_chat_model=True,
        is_function_calling_model=True,
        context_window=settings.MODEL_AGENT_CONTEXT_WINDOW,
        max_retries=8,
        timeout=120,
    )


def get_llm() -> LLM:
    """The agent's model: MODEL_AGENT on Nebius Token Factory."""
    from llama_index.core.llms.function_calling import FunctionCallingLLM
    llm = get_nebius_llm(settings.MODEL_AGENT)

    logging.info(f"LLM type: {type(llm)}")
    logging.info(f"LLM MRO: {type(llm).__mro__}")
    logging.info(f"LLM metadata: {llm.metadata}")
    logging.info(
        f"Is FunctionCallingLLM: {isinstance(llm, FunctionCallingLLM)}"
    )

    return llm
#!! ==================================== 
#!! ====================================    