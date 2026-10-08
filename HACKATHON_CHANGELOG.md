# Hackathon changelog

What was built or changed during the Nebius x NVIDIA Global AI Hackathon submission period.

This repo started from a pre-existing log-analysis RAG project: a FastAPI and Chainlit chat
app, an ingestor that groups log rows into sessions and loads them into Qdrant, SQL and hybrid
search tools, and an LLM judge, all running on an OpenAI model. The entries below are the
work done for the hackathon.

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
