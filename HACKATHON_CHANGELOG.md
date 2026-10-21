# Hackathon changelog

What was built or changed during the Nebius x NVIDIA Global AI Hackathon submission period.

This repo started from a pre-existing log-analysis RAG project: a FastAPI and Chainlit chat
app, an ingestor that groups log rows into sessions and loads them into Qdrant, SQL and hybrid
search tools, and an LLM judge, all running on an OpenAI model. The entries below are the
work done for the hackathon.

## 2026-10-21

- **SQL can't read the real clock.** The model still wrote `current_timestamp` / `now()` by
  habit, which put "last 7 days" past the end of the data. The SQL step is now given the data's
  end as a `TIMESTAMPTZ` literal, and `SQLQueryTool` rejects a query that reads the database
  clock as an invalid query, so the free-repair loop rewrites it with the literal.
- **No fan-out joins.** The SQL schema text now explains that joining two of a session's child
  tables on `session_id` multiplies rows (8 orders x 46 payment attempts = 368), and that several
  measures are counted in one CTE per table.
- **Store-wide overview pattern.** "Anything unusual?" had no example query and the model's own
  attempts were hit and miss. A 14-day per-day activity query (one CTE per table) is now one of
  the schema's investigation patterns; on the synthetic data it surfaces the credential
  stuffing, the account takeover and the card testing in one call.
- **Tool calls in the UI.** Each answer ends with the tool chain; each call opens a side panel
  with its real SQL or search input and its output, and a "Models & timing" panel shows which
  Nemotron model served each step.

## 2026-10-20

- **Questions are answered as of the end of the store data.** The synthetic store is a fixed
  snapshot, so "today" and "last 7 days" measured from the real clock fell past its end and
  every such question came back as "no activity". The pipeline now reads the latest session
  activity (`IStoreQueryRepository.get_data_as_of`) per question and gives that time to the
  reasoning, argument-writing and answer steps as "now". Every answer opens with a line saying
  which moment it was treated as asked at, and the judge is told the same time so it scores
  relative periods against it.

## 2026-10-16

- **Embeddings moved to Token Factory.** Session and query embeddings come from
  `Qwen/Qwen3-Embedding-8B` on Token Factory's OpenAI-compatible `/v1/embeddings`, at 1024
  dimensions (`NebiusEmbedder` in `shared/embeddings/`, `EMBEDDING_MODEL` / `EMBEDDING_DIM`).
  Queries carry Qwen3's retrieval instruction; documents are embedded as-is. The local BGE-M3
  model, FlagEmbedding and PyTorch were removed from the server and ingestor images.
- **Sparse half of hybrid search is now BM25.** Token Factory returns dense vectors only, so
  the sparse vectors come from fastembed's `Qdrant/bm25` (tokenizer + stemmer, no weights).
  The collection's `text-sparse` vector is created with Qdrant's IDF modifier, since BM25
  vectors carry term frequency only. Existing collections must be re-ingested.
- **Known fraud patterns from the web (Tavily).** New `search_fraud_patterns` tool
  (`server/chat_agent/tools/WebSearch/`). After a SQL or session-search result shows
  suspicious behaviour, a new `generate_web_search_args` step rewrites it as a generic pattern
  and a search query; Tavily returns public write-ups, and the answer adds a "Known pattern"
  section with source links, kept separate from the store evidence. Guards in code: the query
  is rejected before sending if it contains an email, IP, device, card, address or session id;
  the tool can't be the first call of a conversation; and it runs at most once per question.

## 2026-10-10

- **Model routing across Nemotron tiers.** The workflow takes one model per tier (fast, agent,
  reasoning) instead of a single model, and every LLM step calls the tier it is assigned
  (`get_llms` in `server/core/dependencies.py`). The final answer's tier is chosen per
  question from what the reasoning loop needed: two or more successful tool results go to the
  reasoning tier (`MODEL_REASONING`), a single-result lookup stays on the agent tier, and a
  refusal goes to the fast tier. No classifier call is added. Unset tiers fall back to
  `MODEL_AGENT`.
- **Per-step telemetry.** Each LLM step in the trace records the model that served it and its
  latency.
- **The judge has its own setting.** `MODEL_JUDGE` replaces the judge's use of `MODEL_FAST`,
  which now means the workflow's fast tier.
- **Read-only is enforced by the database, not by a keyword filter.** The SQL tool's text
  checks (SELECT-only prefix, forbidden keywords) were removed. The agent's SQL now runs as
  a separate Postgres user, `shop_reader`, with SELECT on the nine store tables only,
  read-only sessions and a 15 s statement timeout (`db_init/03_create_users.sh`, migration
  `b2d4f6a8c0e1`, `get_store_repo` in `server/core/dependencies.py`).
- **Every tool call carries a status.** `ToolCall` records `success`, `blocked` or `error`,
  and for an error its type (`invalid_query`, `timeout`, `runtime`), read from the Postgres
  SQLSTATE code in `PostgresStoreQueryRepository`. The tool wrapper returns the `ToolCall`
  to the workflow instead of a string.
- **The tool budget only counts calls that ran.** A query rejected before running
  (`invalid_query`) is repaired without using up one of the three tool calls, up to twice
  per question. A `blocked` call ends the loop and the answer says the assistant is
  read-only. The reason and SQL prompts were updated to the new tags.

## 2026-10-08

- **Nebius Token Factory as the LLM provider.** The chat agent loads its model through
  LlamaIndex `OpenAILike` against Token Factory's OpenAI-compatible API
  (`server/core/dependencies.py`), configured by `NEBIUS_API_KEY`, `NEBIUS_BASE_URL` and
  `MODEL_AGENT`. The model is NVIDIA Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`).
- **Evaluation judge moved to Nemotron.** The LLM judge no longer builds its own OpenAI
  client; `LLMEvaluator` takes an injected model and runs on Token Factory. Code-owned fields
  of `EvaluationResult` are hidden from the judge's JSON schema.
- **Workflow pipeline rebuilt as a bounded reasoning loop.** Reason -> fetch schema ->
  generate arguments -> execute -> reason again, capped at 3 tool calls, then synthesize and
  generate follow-ups. Each LLM step has its own versioned prompt, written for the synthetic
  dataset's schema, and a failed SQL query is repaired on the next iteration.
- **Tool errors no longer crash a run.** A tool that raises now reports `ERROR: ...` back to
  the model and is recorded in the trace.
- **Nemotron on Token Factory is the only model path.** The OpenAI and local-model options
  were removed from the code, the settings and the UI.
- **One pipeline.** The earlier `FunctionAgent` pipeline and the pipeline selector were
  removed; the bounded workflow is the app. The `pipeline_type` column was dropped from the
  trace table (migration `7c2e9a41d5b0`).
- **Evaluation is shown in the UI.** The stream stays open after the answer until the judge
  finishes, and its scores and reasoning are attached to the answer as a side panel.
- **Removed what the hackathon build does not use:** per-component timing, the non-streaming
  chat endpoint, the offline ground-truth lookup in the evaluation service, and the
  prompt-reflector prompt types.
- **Deployable demo stack.** `docker-compose.prod.yml` brings the whole demo up with one
  command: one-shot containers run the migrations (`migrations/`), load the synthetic data
  and build the vector store before the server starts, and a Caddy reverse proxy exposes only
  the chat UI. The chat endpoint has per-visitor and daily rate limits
  (`server/core/rate_limit.py`).
- **New domain: storefront fraud investigation.** The data model, generator and everything the
  model reads were replaced. Nine typed tables in a `shop` schema (customers, products, promo
  codes, sessions, events, orders, order items, payment attempts, refunds), guest checkout
  included. `data/synthetic/generate.py` builds a fictional store with five planted incidents
  (account takeover, card testing, refund abuse, promo sharing, credential stuffing) and nothing
  pre-flagged. The ingestor embeds one document per session; the search tool filters by
  customer, device, IP country and declined payments. All five workflow prompts, both schema
  descriptions and the judge prompt were rewritten, with a single new baseline migration.
- **Read-only guard fixed.** The SQL tool matched forbidden keywords as substrings, so a column
  named `created_at` was rejected as "create". It now matches whole words.
