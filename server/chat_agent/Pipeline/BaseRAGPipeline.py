from abc import ABC, abstractmethod
from server.core.stream.progressReporter import ProgressReporter
from server.chat_agent.schemas import AgentTrace, ChatRequest

class BaseRAGPipeline(ABC):

    @classmethod
    @abstractmethod
    async def create(cls, *args, **kwargs) -> "BaseRAGPipeline":
        pass

    @abstractmethod
    async def query(self, 
                    chat_request: ChatRequest,
                    progress: ProgressReporter = ProgressReporter()
                    ) -> AgentTrace:
        pass


