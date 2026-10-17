# Storefront Fraud Investigator

An agent that answers a fraud or trust-and-safety analyst's questions about an online store in
plain English: was this account taken over, is this session card testing, who is abusing
refunds or a promo code -- with the numbers it rests on.

Built for the **Nebius x NVIDIA Global AI Hackathon** (Best Apps and Agents track). It runs on
**NVIDIA Nemotron** models served by **Nebius Token Factory**.

License: [MIT](LICENSE)

- Demo: <http://zfcrow.online/ui/>
- Video: _TBD_

## What it does

Fraud rarely sits in one row. An account takeover is a first-time device, a password reset, an
address change and an order thirty times the customer's usual, spread across four tables.
Finding it by hand means joining sessions to events to payments to orders and comparing against
the customer's own history. The agent does that work and shows its reasoning.

- **Nothing is pre-flagged.** The data has no "suspicious" column. Every finding is derived:
  first-time devices, cards per session, refund rates against everyone else, accounts sharing
  a device or delivery address.
- **Two data stores.** Postgres holds the store's tables (customers, sessions, events, orders,
  payment attempts, refunds) for exact counts, rates and comparisons. Qdrant holds each session
  written out in time order for "what happened here" questions, searched with dense + sparse
  hybrid search: dense vectors from Qwen3-Embedding-8B on Token Factory, sparse BM25 vectors for
  exact identifiers, fused with RRF.
- **Known-pattern check against the open web.** Once the store data shows something suspicious,
  the agent can ask "is this a known scheme?": it restates the evidence as a generic pattern
  (no names, emails, devices, IPs or cards), searches it with Tavily, and the answer keeps the
  store evidence and the outside sources apart, citing each source by link. A query carrying
  store identifiers is rejected in code before it is sent.
- **An explicit, bounded workflow.** A reasoning step decides whether more data is
  needed and which tool gets it; the tool's schema is fetched; a second step writes the SQL
  or search arguments; the tool runs; the loop repeats (at most 3 tool calls), then a final
  step writes the answer. Every tool call is tagged with how it ended (success, blocked, or
  error with a type read from Postgres's error code). A query the database rejected before
  running it (unknown column, syntax) is repaired on the next pass without using up a tool
  call, up to twice per question; a query that ran and failed (timeout, division by zero)
  counts like any other call.
- **Evidence, not verdicts.** The prompts require every number to come from a SQL result,
  every answer to say what the evidence is consistent with and what it was compared against,
  and to end with a Reasoning/Trace section (tools called, the SQL or filters used).
- **Read-only, enforced by the database.** The SQL the model writes runs as a separate
  Postgres user (`shop_reader`) that can only SELECT the nine store tables, in read-only
  sessions with a 15 s statement timeout. There is no keyword filter on the SQL text: a
  write, or a read of the app's own tables (prompts, traces, evaluations), is refused by
  Postgres, tagged `blocked`, and the agent stops and says it cannot do that.
- **Every answer is evaluated.** Once the answer is on screen, an LLM judge scores it
  (helpfulness, coherence, coverage, faithfulness, context relevance, answer relevance, tool
  routing). The scores and the judge's reasoning appear in a side panel on the answer and are
  stored next to the trace.
- **Prompts are versioned** in Postgres, one per workflow step, so a single step can be changed
  without touching the others.

All data in this repo is fictional. `data/synthetic/generate.py` produces an invented store
("Kestrel Market") with about 100 customers and 500 sessions of ordinary shopping, plus five
planted incidents for the agent to find: an account takeover, card testing, refund abuse, a
promo code shared across accounts and credential stuffing. The ground truth is in
[`data/synthetic/SCENARIOS.md`](data/synthetic/SCENARIOS.md).

## How Nemotron is used

Every LLM call in the app goes to a Nemotron model on Token Factory; there is no other model
path. One question fans out into several calls, and each call runs on one of three model
tiers. The tiers are settings; any tier left empty runs on `MODEL_AGENT`
(`nvidia/nemotron-3-super-120b-a12b`, NVIDIA Nemotron 3 Super).

| Call | Where | Tier (setting) | How |
|---|---|---|---|
| Reason / route | `server/chat_agent/Pipeline/workflow/workflow.py` (`reason_and_route`) | agent (`MODEL_AGENT`) | Structured output (`ReasoningDecision`) |
| SQL and search arguments | same file (`execute_tool`) | agent (`MODEL_AGENT`) | Structured output (`SQLCallArgs`, `VectorCallArgs`, `WebSearchCallArgs`) |
| Final answer | same file (`synthesize_answer`) | chosen per question, see below | Structured output (`FinalAnswer`) |
| Follow-up questions | same file (`generate_follow_up`) | fast (`MODEL_FAST`) | Structured output (`FollowUpQuestions`) |
| Evaluation judge | `server/evaluation/LLMEvaluator.py` | `MODEL_JUDGE` | Structured output (`EvaluationResult`) |

**The final answer is routed by what the investigation needed, not by a guess at the
question.** There is no classifier call in front of the workflow. By the time the answer is
written, the reasoning loop has already shown how hard the question was
(`ReadyToAnswerEvent.synthesis_tier`):

- two or more tool results to combine -> the reasoning tier (`MODEL_REASONING`, meant for
  Nemotron 3 Ultra). A failed call does not count, so a lookup whose SQL needed one repair
  stays a lookup.
- one result, or none -> the agent tier.
- an out-of-scope question -> the fast tier, which only writes the refusal.

The model that served each step and its latency are stored on the step in the trace
(`WorkflowStepTrace.model`, `latency_ms`), and the UI's progress line names the model writing
the answer.

Measured on the synthetic dataset with every tier on Nemotron 3 Super, each answer checked
against the planted scenario:

- "Has any single IP address tried to log into many different accounts?" -- one SQL call,
  answer in 12 s.
- "Which customers have an unusually high refund rate?" -- two SQL calls (the rate, then the
  store-wide baseline), answer in 16 s.
- "Was there anything unusual about Samuel Hale's most recent order?" -- SQL then two session
  searches, answer in 25 s: order 100x his usual, first-time device and country, password
  reset and address change in the same session.
- Judge on Nemotron 3 Super: 4-7 s per evaluation.

With routing on (`MODEL_REASONING` = Nemotron 3 Ultra, `MODEL_FAST` = Nemotron 3.5 Lightning),
read from the stored traces:

- The single-IP question (one SQL result) stayed on Super end to end; answer in 12 s.
- The refund-rate question (two SQL results) had its answer written by Ultra in 3.2 s; answer
  in 19 s.
- The Samuel Hale question, when the loop gathered SQL and session-search results, had its
  answer written by Ultra in 5-7 s; answer in 23-24 s.
- An out-of-scope question was refused by Lightning; reply in 5 s.
- Follow-up questions on Lightning: 1.9-2.9 s.

Nemotron 3 Nano and Nemotron 3.5 Lightning were also tried as the judge. Nano took 70-105 s
and sometimes returned incomplete results; Lightning did not produce the nested result shape.
The judge therefore runs on Super (`MODEL_JUDGE` can point it at another model).

## Where Token Factory helped

- **One OpenAI-compatible endpoint.** The whole app talks to Token Factory through LlamaIndex
  `OpenAILike` (`get_nebius_llm` in `server/core/dependencies.py`). Moving the project onto
  Nemotron was a provider change, not a pipeline change.
- **Trying models is a config change.** The three Nemotron models above were compared as the
  judge by changing a model id, with no deployment or GPU setup.
- **Structured output is served by the API.** Every step of the workflow and the judge get
  schema-validated JSON back from Nemotron, with no self-hosted model server to run.
- **Embeddings are an API call too.** The dense half of the session search comes from
  `Qwen/Qwen3-Embedding-8B` on Token Factory's `/v1/embeddings` (1024 dims, query-side
  instruction), in `shared/embeddings/NebiusEmbedder.py`. This replaced a local BGE-M3 model,
  so the server and ingestor images no longer ship PyTorch or download model weights. The
  sparse half is BM25 (fastembed `Qdrant/bm25`, no model weights), with Qdrant applying IDF.

## How Tavily is used

Store data can show *what* happened; it cannot say whether that behaviour is a scheme fraud
teams already know. The `search_fraud_patterns` tool (`server/chat_agent/tools/WebSearch/`)
answers that from public sources with one Tavily `/search` call, so an answer can say "this
matches card testing" and link the write-ups it rests on.

How a call happens:

1. **Store evidence first.** The reasoning step may route to the tool only after a SQL or
   session-search result (in this question or earlier in the conversation) has shown the
   behaviour. This is enforced in `reason_and_route`, not only in the prompt: a web search
   routed before any store result is turned into a SQL call, and a second search in the same
   question goes straight to the answer.
2. **The evidence is abstracted before the query is written.** The `generate_web_search_args`
   step returns `WebSearchCallArgs`: first `pattern_summary`, the behaviour rewritten
   generically (what happened, in what order, how fast, how many), then `query`, 5-15 words
   built from that summary in the terms fraud write-ups use. Only `query` is sent;
   `pattern_summary` exists so the query is written from the pattern rather than from raw rows.
3. **Store identifiers are blocked in code.** Before anything leaves the system,
   `FraudPatternSearchTool` checks the query against patterns for emails, IP addresses,
   device ids, card fingerprints, address ids and session ids. A match is rejected unsent as
   an invalid query, and the workflow asks for a rewrite, the same way it repairs bad SQL.
   Names can't be caught by a pattern, so the prompt forbids them and the check is the backstop.
4. **One request.** `TavilyWebSearchRepository` posts to `https://api.tavily.com/search`
   (`search_depth: basic`, up to 8 results, default 5) over plain HTTP; each result keeps its
   title, URL, extract and relevance score, with the URL verbatim so it can be cited.
5. **Sources stay apart from evidence.** The answer gives what this store's data shows first,
   then a "Known pattern" section: whether the behaviour matches the scheme the sources
   describe, which signals match and which do not, each outside claim cited as a markdown link
   using only URLs from the results. A match makes fraud more plausible; it is not proof, and
   the answer says what in the store data would confirm or rule it out.

`TAVILY_API_KEY` in `.env` is optional. Without it the tool returns an error and the agent
answers from store data alone.

Example, on the 2-core / 4 GB deployment: "Which device tried the most different cards, and
does it look like card testing? Is this a known fraud pattern?" ran SQL, then one Tavily
search, and answered with a Known pattern section and sources in 42 s.

## Other Nebius services

None yet. Token Factory is the only Nebius service this project uses today.

## Setup

Requirements: Docker with Compose, and a Nebius Token Factory API key.

1. Create the two env files from the examples in the repo root:

   ```
   cp .env.db.example .env.db    # then set POSTGRES_PASSWORD
   cp .env.example .env          # then set NEBIUS_API_KEY (and TAVILY_API_KEY for web search)
   ```

   `.env.db` is the Postgres superuser for the container. `.env` is the app's configuration;
   its hostnames are the Compose service names, and `DB_USER` / `DB_PASSWORD` are the app
   user created by `db_init/03_create_users.sh`, whose password is `APP_DB_PASSWORD` in
   `.env.db` (the two must match; the example files agree out of the box). The same goes for
   the read-only user the agent's SQL runs as: `DB_READER_PASSWORD` in `.env` must match
   `READER_DB_PASSWORD` in `.env.db`. `NEBIUS_BASE_URL` defaults to
   `https://api.tokenfactory.nebius.com/v1/`.

2. Start Postgres, Qdrant and Redis, and create the tables:

   ```
   docker compose up -d db qdrant redis
   docker compose --profile server run --rm migrate
   ```

   `migrate` runs `alembic upgrade head` in a container. It also runs by itself before the
   server or the ingestor starts, so this explicit run is only needed here, before the seed.

3. Load the synthetic store data (once):

   ```
   docker exec hack_db psql -U shop -d shop -f /app/data/synthetic/seed.sql
   ```

   To regenerate it (writes `seed.sql` and `SCENARIOS.md`):

   ```
   python data/synthetic/generate.py
   ```

4. Build the session vector store from the database (embeds every session through Token
   Factory; needs `NEBIUS_API_KEY` and `EMBEDDING_MODEL` in `.env`):

   ```
   docker compose --profile ingestor up --build ingestor
   ```

## Run

```
docker compose --profile server up --build rag_server
```

- Chat UI: http://localhost:8002/ui
- API: `POST http://localhost:8002/chat/stream`
- API docs: http://localhost:8002/docs

Questions to try, each matching a planted scenario:

- "Was there anything unusual about Samuel Hale's most recent order?"
- "Are there any sessions that look like card testing?"
- "Which customers have an unusually high refund rate?"
- "Is the WELCOME50 promo code being abused?"
- "Has any single IP address tried to log into many different accounts?"

## Deploy a public demo

`docker-compose.prod.yml` is the same stack built for a server. The code, the database init
scripts and the synthetic data are baked into the images, and the only published ports are
80/443 of a Caddy reverse proxy that exposes the chat UI and nothing else. Postgres, Qdrant,
Redis and the API are reachable only inside the Compose network.

On a Linux VM with Docker (no GPU needed -- embeddings and every LLM call go to Token Factory):

```
git clone <this repo> && cd <the cloned folder>
cp .env.db.example .env.db    # set POSTGRES_PASSWORD and your own APP_DB_PASSWORD, READER_DB_PASSWORD
cp .env.example .env          # set DB_PASSWORD (= APP_DB_PASSWORD), DB_READER_PASSWORD (= READER_DB_PASSWORD), NEBIUS_API_KEY, rate limits
docker compose -f docker-compose.prod.yml up -d --build
```

That one command creates the database, runs the migrations, loads the synthetic data, builds
the vector store and then starts the server, in that order. The first start takes a while
(the ingestor embeds every session through Token Factory); later starts skip the work that is
already done. Follow it with
`docker compose -f docker-compose.prod.yml logs -f`.

The demo is then at `http://<vm-ip>` (it redirects to `/ui`). For HTTPS, point a domain at the
VM and set `SITE_ADDRESS=demo.example.com` in `.env`; Caddy obtains the certificate by itself.

Every question is several Nemotron calls, so set limits in `.env` before sharing the link:
`RATE_LIMIT_PER_MINUTE` (questions per visitor per minute) and `RATE_LIMIT_PER_DAY`
(questions per day across all visitors). `0` turns a limit off.

To deploy without building on the server, set `IMAGE_PREFIX` to a registry path (for example
`ghcr.io/<user>/fraud-investigator`), run `docker compose -f docker-compose.prod.yml build`
and `push` locally, and on the server copy only `docker-compose.prod.yml`, `caddy/Caddyfile`,
`.env` and `.env.db`, then `pull` and `up -d`.

## Project layout

| Path | Contents |
|---|---|
| `server/` | FastAPI app, chat UI, the workflow, tools, evaluation, versioned prompts |
| `ingestor/` | Reads each session with its events, payments and orders, embeds it and loads Qdrant; also owns the store's table models |
| `shared/` | Settings, database, cache, embeddings, vector-store code used by both |
| `data/synthetic/` | Synthetic data generator, seed SQL, planted scenarios |
| `migrations/` | Alembic migrations and the small image that applies them (single `shop` database, every table in the `shop` schema) |
| `db_init/` | Postgres init scripts run on first container start, and the demo's database image |
| `docker-compose.prod.yml`, `caddy/Caddyfile` | The hosted-demo stack and its reverse-proxy config |

Host ports: Postgres 5434, Qdrant 6335, Redis 6380, server 8002.

## Development notes

A database volume created before the read-only user existed does not have it (the
`db_init` scripts only run on a fresh volume), and the migration that grants its table
access stops with "role shop_reader does not exist". Create it once, then start the stack:

```
docker exec -i hack_db psql -U postgres -d shop <<'SQL'
CREATE USER shop_reader WITH PASSWORD 'shop_reader_dev';
GRANT CONNECT ON DATABASE shop TO shop_reader;
ALTER ROLE shop_reader SET default_transaction_read_only = on;
ALTER ROLE shop_reader SET statement_timeout = '15s';
GRANT USAGE ON SCHEMA shop TO shop_reader;
SQL
```

The workflow's prompts are stored in Postgres and seeded from `server/prompt/prompts.py`
only when a prompt type has no active version, so editing that file does not change a
database that already has them; insert the new text as a new version
(`PostgresPromptRepository.insert_prompt`).

New migration after changing a SQL model, from a host Python environment with `alembic`
installed, at the repo root (`migrations/alembic.ini` points at `127.0.0.1:5434`, the host
port of the dev `db` service):

```
alembic -c migrations/alembic.ini revision --autogenerate -m "describe the change"
```

It is applied the next time the stack starts, or with
`docker compose --profile server run --rm migrate`.

## What was built during the hackathon

This project started from an existing log-analysis RAG prototype. During the submission period
it was moved onto Nemotron and Token Factory, the agent was rebuilt as the bounded workflow
described above with one versioned prompt per step, the evaluation judge was moved to
Nemotron and surfaced in the UI, and the whole domain was replaced: a new storefront data
model, synthetic data generator, session ingestion, schema descriptions and prompts for fraud
investigation. The
dated list is in [`HACKATHON_CHANGELOG.md`](HACKATHON_CHANGELOG.md).

| | Carried over from the prototype | Built or replaced during the hackathon |
|---|---|---|
| Domain and data | -- | Storefront fraud investigation: the `shop` data model (9 tables), the synthetic generator and its five planted incidents |
| Agent | Tool base classes, tool-call logging | The bounded reason / fetch-schema / write-arguments / execute loop, structured outputs, SQL repair, refusal path |
| Model | -- | NVIDIA Nemotron on Nebius Token Factory for every step and for the judge |
| Prompts | Prompt versioning in Postgres; the judge's scoring rubric | One prompt per workflow step, both schema descriptions, the investigation patterns |
| Retrieval | Embedding service interface, Qdrant hybrid search, Redis cache, ingestion checkpointing | Token Factory embeddings + BM25 replacing local BGE-M3, one document per store session, the session ingestion query, search filters by customer / device / country / declined payments |
| Evaluation | Evaluation service and storage | Judge on Nemotron, result streamed to the UI |
| App | FastAPI + Chainlit shell, streaming events | Single-pipeline UI, rate limiting |
| Deployment | Dev Docker Compose | Production compose with one-command bring-up (migrate, seed, ingest), migrations image, Caddy front end |
