from abc import ABC, abstractmethod
from typing import Any

from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.LogDecorator import log_tool_call
from server.chat_agent.tools.enums import ToolName


class AgentTool(ABC):
    """
    Common parent for every tool the chat agent can call (SQL query/schema,
    vector query/schema, operation-code mapper, follow-up generator).

    Two things this buys every subclass:
    - Typing: a tool collection can be dict[ToolName, AgentTool] instead
      of dict[ToolName, any].
    - The log_tool_call() wrapping itself: call super().__init__(tool_name,
      tools_called) from the subclass's own __init__ instead of
      each tool repeating its own `self.__call__ = log_tool_call(...)(self.__call__)`
      line. self.__call__ here resolves to the subclass's own concrete
      __call__ (normal method resolution finds the most-derived definition),
      so this works regardless of where in the subclass's __init__ the
      super().__init__() call happens to sit.

    tool_name should be the real ToolName enum member (e.g. ToolName.QUERY_SQL),
    not a hardcoded string literal -- pydantic coerces it to its .value when it
    lands in ToolCall, but passing the enum member itself
    is what keeps a tool's identity in sync with ToolName if it's ever renamed.
    Normalized to a plain str here so log_tool_call's own log line reads
    "query_sql" rather than "ToolName.QUERY_SQL".
    """

    def __init__(
        self,
        tool_name: str | ToolName,
        tools_called: list[ToolCall] = None,
    ):
        if isinstance(tool_name, ToolName):
            tool_name = tool_name.value
        self.__call__ = log_tool_call(tool_name, tools_called)(self.__call__)

    @abstractmethod
    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ...
