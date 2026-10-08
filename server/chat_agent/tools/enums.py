import enum 

class ToolName(enum.Enum):
    QUERY_SESSION_VECTOR_HYBRID = "query_vector_store"
    GET_SESSION_VECTOR_HYBRID_SCHEMA = "get_vector_store_schema"
    QUERY_SQL = "query_sql"
    GET_SQL_SCHEMA = "get_sql_schema"
    FOLLOW_UP_QUESTION_GENERATOR = "follow_up_question_generator"



if __name__ == "__main__": 
    print(ToolName.QUERY_SESSION_VECTOR_HYBRID.name)  # Output: "query_session_vector_hybrid"
    print(ToolName.QUERY_SESSION_VECTOR_HYBRID.value)  # Output: "query_session_vector_hybrid"

    print(ToolName("query_session_vector_hybrid"))