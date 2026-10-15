import enum

class ToolName(enum.Enum):
    QUERY_SESSION_VECTOR_HYBRID = "query_vector_store"
    GET_SESSION_VECTOR_HYBRID_SCHEMA = "get_vector_store_schema"
    QUERY_SQL = "query_sql"
    GET_SQL_SCHEMA = "get_sql_schema"
    FOLLOW_UP_QUESTION_GENERATOR = "follow_up_question_generator"
    SEARCH_FRAUD_PATTERNS = "search_fraud_patterns"
    GET_FRAUD_PATTERN_SEARCH_SCHEMA = "get_fraud_pattern_search_schema"


class ToolStatus(str, enum.Enum):
    """How a tool call ended -- recorded on every ToolCall."""
    SUCCESS = "success"
    BLOCKED = "blocked"  # refused on permissions: the agent's database user can only read
    ERROR = "error"      # see ToolErrorType


class ToolErrorType(str, enum.Enum):
    """
    What kind of ERROR. The split that matters to the workflow is whether the call ran:
    an INVALID_QUERY was rejected before it touched any data, so it says nothing about the
    question and its repair does not use up a tool call. The others ran and failed, and
    count like any other call.
    """
    INVALID_QUERY = "invalid_query"  # rejected while parsing/planning: unknown column, syntax, wrong function
    TIMEOUT = "timeout"              # ran past the statement timeout
    RUNTIME = "runtime"              # ran and failed (division by zero, bad cast...), or any non-database failure



if __name__ == "__main__":
    print(ToolName.QUERY_SESSION_VECTOR_HYBRID.name)  # Output: "query_session_vector_hybrid"
    print(ToolName.QUERY_SESSION_VECTOR_HYBRID.value)  # Output: "query_session_vector_hybrid"

    print(ToolName("query_session_vector_hybrid"))
