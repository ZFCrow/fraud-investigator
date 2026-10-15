import functools
import logging
from typing import Optional

from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.enums import ToolErrorType, ToolStatus
from server.chat_agent.tools.exceptions import ToolError


def log_tool_call(tool_name: str,
                  tools_called: list[ToolCall]):
    """
    Wraps a tool so that every call -- successful or not -- is recorded as a ToolCall and
    handed back to the caller. A tool never raises through this: a failure comes back as a
    ToolCall tagged with how it failed, for the workflow to act on.
    """
    def decorator(func):

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> ToolCall:
            logging.info(f"calling Tool {tool_name}  with args {kwargs}")

            status: ToolStatus = ToolStatus.SUCCESS
            error_type: Optional[ToolErrorType] = None
            try:
                output = await func(*args, **kwargs)
            except ToolError as e:
                status, error_type = e.status, e.error_type
                prefix = "BLOCKED" if status == ToolStatus.BLOCKED else "ERROR"
                output = f"{prefix}: {e}"
            except Exception as e:
                logging.error(f"Error occurred while calling Tool {tool_name}: {e}")
                status, error_type = ToolStatus.ERROR, ToolErrorType.RUNTIME
                output = f"ERROR: {e}"

            call = ToolCall(
                tool_name=tool_name,
                input_args=kwargs,  # kwargs captures all named args
                output=output,
                status=status,
                error_type=error_type,
            )
            tools_called.append(call)
            logging.info(f"Tool {tool_name} called with args {kwargs} ended {status.value}, output: {output}")
            return call

        return wrapper

    return decorator
