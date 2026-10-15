import ast

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from datetime import datetime, timezone
import uuid
import json

from llama_index.core.llms import ChatMessage

from server.chat_agent.tools.enums import ToolErrorType, ToolName, ToolStatus
# =====================================================================
# CORE STRUCTS (The building blocks)
# =====================================================================

class ToolCall(BaseModel):
    """
    Represents a call to a specific tool.
    """
    # allow str in case toolnames changes in the future , then stale toolnames in the db will still be valid 
    tool_name: str | ToolName = Field(..., description="The name of the tool being called.") 
    input_args: dict[str,Any]

    #vector returns list of str
    #sql returns list of dict 
    #schema returns str    
    #opcode mapper can return either an int or a str
    output: list[str] | list[dict] | str | int

    # defaults keep traces stored before these fields existed loadable
    status: ToolStatus = Field(default=ToolStatus.SUCCESS, description="How the call ended.")
    error_type: Optional[ToolErrorType] = Field(default=None, description="Set when status is error.")

    @property
    def output_text(self) -> str:
        """The output as the model reads it."""
        if isinstance(self.output, list):
            if not self.output:
                return "No results found."
            return "\n\n---\n\n".join(
                item if isinstance(item, str) else json.dumps(item, default=str)
                for item in self.output
            )
        return str(self.output)

    # this is when i am taking it from the db
    #! input_Args would comes as a string , so 
    #! i would have to parse it into a dict before using it in the agent
    @field_validator("input_args", mode="before")
    @classmethod
    def parse_input_args(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)          # try proper JSON first
            except json.JSONDecodeError:
                return ast.literal_eval(v)     # fallback for Python-repr strings like "{'sql': ...}"
        return v 

class WorkflowStepTrace(BaseModel):
    """
    One step of an explicit Workflow-graph run (server/chat_agent/Pipeline/workflow/).

    Distinct from ToolCall: this logs every LLM decision point in the graph (routing,
    tool-argument generation, answer synthesis, follow-up generation), not just the
    steps that happen to invoke an AgentTool. Several decision points -- routing,
    the arg-generation half of execute_tool, answer synthesis, and follow-up-question
    generation -- never touch a tool at all, so ToolCall alone leaves no record of them.

    Sequential, in execution order (appended to as the graph runs, same list object
    the outer pipeline owns), so a later pass can reconstruct the graph's actual
    causal path through one run, not just that each step happened somewhere in it.
    """
    step_name: str = Field(..., description="e.g. 'route', 'generate_sql_args', 'synthesize_answer'.")
    prompt_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Which versioned Prompt (server.prompt.schemas.Prompt) produced this step's output, if any -- None for steps not yet backed by a versioned prompt."
    )
    input: str = Field(..., description="What was fed into this step's LLM call (or tool call, for schema-fetch).")
    #!output: str = Field(..., description="This step's result, serialized.")
    #! so i dont need to deserialize it and dbeaver and show it mroe clearly! 
    output: Any = Field(..., description="This step's result, serialized. Can be a string, list, or dict depending on the step.")
    # both None for a step that makes no LLM call (fetch_schema, a forced answer)
    model: Optional[str] = Field(default=None, description="Model id that served this step's LLM call.")
    latency_ms: Optional[int] = Field(default=None, description="Wall time of this step's LLM call, retries included.")



# =====================================================================
# DATA TRANSFER OBJECTS (DTOs)
# =====================================================================

# 1. INPUT DTO: What the frontend sends to the FastAPI router
class ChatRequest(BaseModel):
    user_input: str = Field(..., examples=["What's the top 10 most denied days?"])
    session_id : uuid.UUID = Field(..., examples=["11111111-1111-1111-1111-111111111111"])


# 2. INTERNAL/DB DOMAIN MODEL: Your exact model tracking the whole execution
class AgentTrace(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    input: str
    output: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_prompt_id: Optional[uuid.UUID] = None

    # for evaluation purposes , not mapped to db
    reflected: Optional[bool] = False

    def chat_messages(self) -> list[ChatMessage]:
        """This turn as it appears in the chat history of later turns in its session."""
        messages : list[ChatMessage] = [ChatMessage(role="user", content=self.input)]
        if self.output:
            messages.append(ChatMessage(role="assistant", content=self.output))
        return messages

    class Config:
        from_attributes = True


class WorkflowAgentTrace(AgentTrace):
    """
    The trace of a run through the workflow graph (server/chat_agent/Pipeline/workflow/):
    adds `steps`, one entry per step the graph executed, in order. Always a list --
    a failed run still has a partial one.
    """
    steps: list[WorkflowStepTrace]


# 3. OUTPUT DTO: What goes back to the user over HTTP
# (It inherits from AgentTrace so you don't duplicate any fields)
class AgentTraceResponse(AgentTrace):
    """
    This matches AgentTrace perfectly, but acts as a strict boundary 
    for your API documentation and client response parsing.
    """
    pass