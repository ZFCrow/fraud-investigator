

from abc import ABC, abstractmethod

from server.chat_agent.schemas import AgentTrace


class IChatRepository(ABC):
    """
    Interface for the Chat Repository.
    """

    @abstractmethod
    async def insert_trace(self, trace: AgentTrace):
        """
        Insert a chat message into the repository.

        Args:
            chat_message: The chat message to be inserted.
        """
        ...

    @abstractmethod
    async def get_trace_by_session_id(self, session_id: str) -> list[AgentTrace]:
        """
        Retrieve chat messages by session ID.

        Args:
            session_id: The session ID to filter chat messages.

        Returns:
            A list of chat messages associated with the given session ID.
        """
        ...

