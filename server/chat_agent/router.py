import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse 

from server.chat_agent.repository.repository import IChatRepository
from server.core.stream.progressReporter import ProgressReporter 
from server.core.stream.stream_events import StreamEvent 
from server.core.dependencies import (
    get_cache_repo, get_embedding_service, get_evaluation_service, get_llm, get_vector_repo, get_store_repo , 
    get_chat_repo, get_redis_repo, get_prompt_repo
    )

from server.core.rate_limit import enforce_rate_limit
from server.evaluation.service import EvaluationService
from server.chat_agent.Pipeline.BaseRAGPipeline import BaseRAGPipeline
from server.chat_agent.Pipeline.workflow.pipeline import ProposedWorkflowRag
from server.chat_agent.schemas import AgentTraceResponse, ChatRequest


from server.chat_agent.tools.SQLQuery.repository import IStoreQueryRepository
from server.prompt.repository import IPromptRepository
from server.vector.repository import IVectorQueryRepository
from shared.embeddings.EmbeddingService import EmbeddingService
from shared.cache.ICacheRepository import ICacheRepository

import asyncio

from llama_index.core.llms import LLM



# 1. Initialize the router
# The 'prefix' adds /items to all routes here
# The 'tags' group these routes together in the Swagger/Docs UI
router = APIRouter(
    prefix="/chat", 
    tags=["Chat"]
)

# 2. Define routes
@router.post("/stream", dependencies=[Depends(enforce_rate_limit)])
async def chat_stream(
    chat_request: ChatRequest,
    embedding_service: EmbeddingService =  Depends(get_embedding_service),
    vector_repo : IVectorQueryRepository  = Depends(get_vector_repo),
    store_repo : IStoreQueryRepository = Depends(get_store_repo), 
    chat_repository : IChatRepository = Depends(get_chat_repo),
    cache_repository : ICacheRepository = Depends(get_redis_repo),
    prompt_repo : IPromptRepository = Depends(get_prompt_repo), 
    evaluation_service : EvaluationService  = Depends(get_evaluation_service)  
):
    #
    # Same setup as before
    try:
        llm : LLM = get_llm()
        agent : BaseRAGPipeline = await ProposedWorkflowRag.create(
            embedding_service=embedding_service,
            vector_repo=vector_repo,
            store_repo=store_repo,
            chat_repo=chat_repository,
            cache_repo=cache_repository,
            prompt_repo=prompt_repo,
            llm=llm,
            evaluation_service=evaluation_service
        )
    except NotImplementedError as nie: 
        logging.exception(f"Error in chat_stream endpoint: {nie}")
        raise HTTPException(status_code=501, detail=str(nie)) 
    
    except Exception as e: 
        logging.exception(f"Error in chat_stream endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 
    
    # once the http is established, we can start the query and stream the results back to the client. 

    queue = asyncio.Queue[StreamEvent]() 
    progress = ProgressReporter(queue)

    async def run_agent():
        try:
            await agent.query(chat_request=chat_request,
                              progress=progress,
                              )
        except Exception as e:
            logging.error(f"ROUTER - Error in run_agent: {e}") 
            await queue.put(StreamEvent(event="error", data=str(e)))
        # finally:
        #     await queue.put(StreamEvent(event="done"))

    task = asyncio.create_task(run_agent())

    async def stream():
        try:
            while True:
                event : StreamEvent  = await queue.get()

                yield event.model_dump_json() + "\n"
                
                if event.event == "done" or event.event == "error": 
                    break 
                
        except asyncio.CancelledError: 
            logging.info("Streaming cancelled by client.")
            task.cancel()
            raise
        except Exception as e: 
            logging.exception(f"Error in streaming: {e}")
            yield StreamEvent(event="error", data=str(e)).model_dump_json() + "\n"
        
        finally:
            await task

    return StreamingResponse(stream(), media_type="text/event-stream")

