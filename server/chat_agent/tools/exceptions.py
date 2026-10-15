from typing import Optional

from server.chat_agent.tools.enums import ToolErrorType, ToolStatus


class ToolError(Exception):
    """
    Raised by a tool (or the repository behind it) that knows how its call failed, so the
    ToolCall is tagged with that instead of the generic ERROR / RUNTIME that log_tool_call
    gives any other exception.
    """
    def __init__(self,
                 message: str,
                 status: ToolStatus = ToolStatus.ERROR,
                 error_type: Optional[ToolErrorType] = ToolErrorType.RUNTIME):
        super().__init__(message)
        self.status = status
        self.error_type = error_type
