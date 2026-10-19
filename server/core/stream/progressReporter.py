
import asyncio
from typing import Optional
from server.core.stream.stream_events import StreamEvent 
import logging
from server.evaluation.schemas import EvaluationResult
from server.chat_agent.schemas import AgentTrace

class ProgressReporter:
    def __init__(
            self, 
            queue: Optional[asyncio.Queue[StreamEvent]] = None):
        
        # set it to none 
        self.queue = queue 
        self.answered = False  # flag to track if an answer has been sent 

    async def update(
        self, 
        message: str,
        log: Optional[str] = None):
        
        if self.queue and not self.answered:  # only send progress if an answer hasn't been sent yet 
            await self.queue.put(
                StreamEvent(event="progress", data=message)
                )
        logging.info(log) if log else logging.info(message) 

    async def answer(
        self , ans : str):
        if self.queue: 
            await self.queue.put(
                StreamEvent(event="answer", data=ans)
            )
        self.answered = True  # mark that an answer has been sent
        

    async def graph(
        self, 
        charts : Optional[list[str]] = None):
        if self.queue and charts:
            for chart in charts: 
                await self.queue.put(
                    StreamEvent(event="graph", data=chart)
                )


    async def actions(self, questions: Optional[list[dict]] = None):
        if self.queue and questions:
            for question in questions:
                await self.queue.put(
                    StreamEvent(event="action", data=question)
                ) 
    async def metaData(
         self , 
         # the agent's trace (sent with the answer) or the judge's evaluation (sent once
         # the judge is done); the UI tells them apart by the trace's tool_calls key
         metaData : AgentTrace | EvaluationResult,
         log : Optional[str] = None 
         ):
        if self.queue:
            await self.queue.put(
                StreamEvent(event="metadata", data=metaData.model_dump(mode="json"))
            ) 

        logging.info(log) if log else None  

    async def error(self, message: str):
        if self.queue:
            await self.queue.put(
                StreamEvent(event="error", data=message)
            )
        self.answered = True  # mark that an answer has been sent (even though it's an error, we don't want to send further progress updates)
        logging.error(message)

    async def done(
            self,
            log : Optional[str] = None):
        if self.queue:
            await self.queue.put(
            StreamEvent(event="done")
        )
        logging.info(log) if log else None  