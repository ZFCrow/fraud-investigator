from enum import Enum


# str Enum (like LLMProvider) rather than a bare int Enum: `type` is stored in a
# String column and shows up directly in ad-hoc SQL/dashboard queries against the
# `prompt` table, so the DB value should be self-describing rather than a magic 0/1.
class PROMPTTYPE(str, Enum):
    EVALUATOR_PROMPT = "evaluator_prompt"

    # one prompt per LLM step of the workflow pipeline (server/chat_agent/Pipeline/workflow/),
    # versioned separately so a single step can be rewritten without touching the others
    WORKFLOW_REASON_STEP = "workflow_reason_step"
    WORKFLOW_SQL_ARGS_STEP = "workflow_sql_args_step"
    WORKFLOW_VECTOR_ARGS_STEP = "workflow_vector_args_step"
    WORKFLOW_SYNTHESIZE_STEP = "workflow_synthesize_step"
    WORKFLOW_FOLLOW_UP_STEP = "workflow_follow_up_step"

if __name__ == "__main__":
    # sanity check: the str Enum values are unique and non-empty.
    print (PROMPTTYPE.EVALUATOR_PROMPT.value)