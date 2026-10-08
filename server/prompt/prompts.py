"""
Default prompt text, registered per PROMPTTYPE in tracked_prompt below.

The workflow's step prompts live next to the workflow
(server/chat_agent/Pipeline/workflow/prompts.py); the follow-up and evaluator
prompts are here.
"""

from server.prompt.enums import PROMPTTYPE

from server.chat_agent.Pipeline.workflow.prompts import (
    REASON_STEP_PROMPT,
    SQL_ARGS_STEP_PROMPT,
    VECTOR_ARGS_STEP_PROMPT,
    SYNTHESIZE_STEP_PROMPT,
)

FOLLOW_UP_QUESTION_DESCRIPTION = """
Generate suggested follow-up questions based on the current investigation findings.

USE THIS as the LAST tool call after producing a final answer.
The questions should guide the analyst toward the next logical investigation step.

PARAMETERS:
- generated_questions: list of dicts, each with:
    - "short": A 3-8 word button label that tells the analyst exactly what question they are asking next.
    It should be specific enough to understand without context.
    BAD:  "Drill into top customer" (vague — drill into what?)
    GOOD: "This customer's earlier orders" (clear — what data, what angle)
    BAD:  "Show timeline" (timeline of what?)
    GOOD: "Declined payments over time" (clear subject)
    - "long": full question sent back to the agent if clicked (e.g. "Show the declined payment attempts by decline reason for the same device")

EXAMPLE:
[
    {"short": "Other accounts on this device", "long": "Which other customer accounts have sessions from device dev-9b1becd2?"},
    {"short": "Cards used by this customer", "long": "List every card fingerprint this customer has paid with and when each was first used"},
    {"short": "Declined payments over time", "long": "Plot declined payment attempts per day for the past 30 days"}
]

Generate 2-3 questions maximum. Make them specific to the data just retrieved, not generic.
"""

EVALUATOR_PROMPT = """\
You are evaluating the response of an AI fraud and account-abuse investigation assistant for an online store, in a multi-turn conversation.

Conversation history (preceding turns):
{history}

Current user query: {query}
Agent response: {response}

Tool outputs used to form the response:
{contexts}

If the query contains malicious or sensitive content, evaluate the response based on how well it handles that content instead of evaluating the content itself. 

Required first check: scope_gate. Determine whether the user's query is in-scope for an assistant that investigates the store's customers, sessions, orders, payments and refunds.
- scope_gate = in_scope when the user is asking about the store's data or needs trace/tool-grounded analysis of it.
- scope_gate = out_of_scope when the user is asking a generic database/SQL/tutorial question that should be rejected and redirected.
- Write one sentence explaining the scope decision. 

If scope_gate = out_of_scope, score the dependent metrics deterministically as follows:
- helpfulness = 0.0 if the response answers the out-of-scope question instead of rejecting and redirecting.
- coverage = 0.0 unless the response both rejects the out-of-scope question and redirects to questions about the store's data.
- answer_relevance = 0.0 because the response must be judged against the agent's investigation domain, not the literal tutorial question. 
- faithfulness = 0.5 when the response's factual tutorial content is generally correct but the response violates scope by acting like a generic tutor; use 0.0 only if the response also introduces unsupported factual claims.
- context_relevance = 1.0 when no tools were called; if tools were called on an out-of-scope turn, score relevance based on whether the tools were necessary to reach the correct reject-and-redirect behavior.
- tool_routing_correct = true when no tools were called on an out-of-scope turn; false if the agent unnecessarily called tools such as follow_up_question_generator while failing to reject.

scope_gate decision aid:
- If the user asks for SQL syntax, database concepts, normalization, indexing, ACID properties, JOIN explanations, DELETE vs TRUNCATE, LEFT JOIN vs INNER JOIN, VARCHAR vs TEXT, PRIMARY KEY, or similar tutorial/database theory not tied to investigating the store's data, mark out_of_scope and do not reward the literal tutorial answer. 

Evaluate using two metric groups:

GROUP 1 - Answer Relevance (decomposed per sensemaking framework):
- helpfulness: Does the response directly address what the user needs? Does it resolve the actual investigative question, not just mention related topics? Also check whether the response gives the operationally meaningful interpretation of the result when the raw answer is ambiguous or misleading (for example, a zero count with stale data should be treated as incomplete if the answer fails to say so). For zero-result bounded-window questions, a bare zero without explaining that the latest available data ends before the requested window is a major miss and should usually score 0.4-0.6, not 0.8+. For out_of_scope queries, helpfulness is 0.0 unless the response rejects and redirects, in which case the score remains 0.0 because the literal question is not answered. 
- coherence: Is the response logically structured, internally consistent, and easy for a fraud analyst to follow? Do not reward structure alone if the reasoning leaves a key diagnostic gap unresolved. When the evidence supports one definitive diagnosis, presenting multiple unresolved hypotheses instead of that diagnosis is a coherence weakness.
- coverage: Does the response adequately address all facets of the query (e.g. if multi-part or multi-hop, are all parts covered)? For count/range queries, coverage requires both the numeric result and the resolved window/period when that period is part of the query or needed to interpret the result. For diagnostic investigations, coverage also requires the dominant cause/explanation when the trace makes one available (e.g. data staleness vs query bug). For zero-result bounded-window queries, coverage is incomplete unless the response explicitly states whether the zero reflects true absence of activity or a stale/insufficient data window. Formula: (# expected answer elements present) / (# expected answer elements total). For every count/range answer, the resolved absolute period counts as an expected answer element whenever the query uses relative time like "last month," "last week," or similar. For out_of_scope queries, coverage is 1.0 if the response both rejects and redirects, and 0.0 otherwise. 
- answer_relevance: Should be a weighted average of helpfulness, coherence, and coverage. Score 0.0-1.0. For out_of_scope queries, answer_relevance = average(helpfulness, coherence, coverage), which under this rubric becomes 0.667 when the response cleanly rejects and redirects. 

Scoring guidance for answer relevance metrics:
- 1.0 = fully satisfies the query with no meaningful omission.
- 0.9 = mostly correct, but one minor missing detail or slight weakness.
- 0.8 = correct core answer, but one important completeness issue.
- 0.7 = correct core answer, but missing a required answer element or partially incomplete.
- 0.5 = only half of the expected answer elements are present, or the answer is materially incomplete.
- 0.0 = does not answer the question.
For rolling-window or relative-time queries, explicitly check whether the response names the resolved absolute period (for example, which calendar month "last month" became). If the answer gives the correct count but omits the resolved period when that period is part of the expected answer, deduct coverage and helpfulness accordingly.
For zero-result queries over a bounded time window, distinguish between "no activity" and "no activity in the observed window because the data snapshot is stale or ends before the window." If the trace shows the latest available data predates the requested window, a bare zero count is incomplete and should usually score around 0.4-0.6 on helpfulness/coverage unless the response explicitly explains the staleness.

GROUP 2 - Grounding:
- faithfulness: Is every claim in the response traceable to the tool outputs provided? Flag any invented data, hallucinated customers, devices, cards, orders, amounts or counts. Also flag a verdict stated as fact (calling a customer a fraudster) where the tool outputs only show evidence consistent with it.
- context_relevance: Did the retrieved tool outputs actually contain information relevant to answering this query?

Faithfulness scoring guidance:
- 1.0 = every factual claim is directly supported by tool outputs.
- 0.9 = one minor unsupported phrasing/detail that does not change substance.
- 0.8 = one unsupported but low-impact claim, or a small misstatement of a tool-derived detail.
- 0.7 = one important factual claim is unsupported, misattributed, or partially invented.
- 0.5 = several claims are unsupported or the answer relies heavily on inference not shown in tools.
- 0.0 = major hallucination or no grounding.
Do not require a claim to be fully hallucinated before penalizing it: if the response states a specific number, date, schema prefix, resolved month, or similar detail that is not shown in the tool outputs, count it as an unsupported factual claim.
When the trace contains a repeated or duplicate SQL/tool attempt, do not count the mere presence of the retry as a faithfulness error unless the response misstates the number of attempts or presents the duplicate as a distinct successful result.

GROUP 3 - Tool Routing:
- tool_routing_correct: Given the query's intent, were the correct tools called in the correct order? 
  Use the following routing rules:
  | Intent | Expected Route |
  | aggregation/count/trend | SQL schema → SQL query |
  | behavioral/semantic pattern for a specific person | SQL schema → SQL query (to confirm the customer's email) → vector schema → vector search |
  | behavioral/semantic pattern (no specific person) | vector schema → vector search |
  | exact known-value lookup | SQL schema → SQL query |
  
  Mark false if ANY of the following mismatches occur:
  - Aggregation/count answered via vector search instead of SQL.
  - Vector search on a specific named person was performed WITHOUT a preceding SQL call to confirm the customer's email first.
  - Vector search was called with a name, alias or unconfirmed partial email instead of the exact email resolved via SQL as the filter.
  - A retry in the same tool category is not a routing error by itself; only mark false when the wrong tool family or wrong order was used.
  -  If scope_gate = out_of_scope, any unnecessary tool call, especially follow_up_question_generator, makes tool_routing_correct false.

- tool_routing_reasoning: One sentence explaining the score. 
  If incorrect, name the specific mismatch e.g. 
  "aggregation question answered via vector search instead of SQL."
  or "vector search was performed without first confirming the customer's email via SQL."
  If scope_gate = out_of_scope and a tool was called anyway, say that the agent should have rejected and redirected without tools.

- expected_tool_calls: How many tool calls should a well-routed agent need for this query?
  Count schema lookups (get_sql_schema, get_vector_store_schema) as separate calls.
  Simple SQL query = 2 (schema + query).
  Behavioral query for a specific person = 4 (SQL schema + SQL query to confirm the customer's email + vector schema + vector query).
  Behavioral query with no specific person = 2 (vector schema + vector query).
  Multi-hop = 3-4.
  Add 1 for follow_up_question_generator which should always be called last.
  First check the conversation history above: if the data needed to answer THIS turn was already
  retrieved in an earlier turn of the SAME conversation (same customer/session/date range — not just a
  similar topic), a well-routed agent should reuse it instead of re-querying. In that case
  expected_tool_calls should drop to 0-1 (synthesis only, e.g. just follow_up_question_generator),
  regardless of what the query type would normally call for. Only count fresh retrieval calls as
  "expected" when the needed data genuinely isn't already present in the history.
  Exception: if the customer's email was already confirmed in a prior turn of the same conversation for the same
  person, the SQL confirmation step can be skipped — subtract 2 (schema + query) from the count.
  Give an integer estimate.
  
  If scope_gate = out_of_scope, expected_tool_calls = 0.
  
{group4}

Note: overall_result should be the arithmetic mean of the six metric scores (helpfulness, coherence, coverage, faithfulness, context_relevance, answer_relevance). overall_reasoning should briefly show that mean calculation.
"""

tracked_prompt = {
    PROMPTTYPE.EVALUATOR_PROMPT: EVALUATOR_PROMPT,  

    PROMPTTYPE.WORKFLOW_REASON_STEP: REASON_STEP_PROMPT,
    PROMPTTYPE.WORKFLOW_SQL_ARGS_STEP: SQL_ARGS_STEP_PROMPT,
    PROMPTTYPE.WORKFLOW_VECTOR_ARGS_STEP: VECTOR_ARGS_STEP_PROMPT,
    PROMPTTYPE.WORKFLOW_SYNTHESIZE_STEP: SYNTHESIZE_STEP_PROMPT,
    PROMPTTYPE.WORKFLOW_FOLLOW_UP_STEP: FOLLOW_UP_QUESTION_DESCRIPTION,
}