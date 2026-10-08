# Storefront Fraud Investigator

An agent that answers a fraud or trust-and-safety analyst's questions about an online store in
plain English: was this account taken over, is this session card testing, who is abusing
refunds or a promo code -- with the numbers it rests on.

Built for the **Nebius x NVIDIA Global AI Hackathon** (Best Apps and Agents track). It runs on
**NVIDIA Nemotron** models served by **Nebius Token Factory**.

License: [MIT](LICENSE)

- Demo: _TBD_
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
  (BGE-M3) hybrid search.
- **An explicit, bounded workflow.** A reasoning step decides whether more data is
  needed and which tool gets it; the tool's schema is fetched; a second step writes the SQL
  or search arguments; the tool runs; the loop repeats (at most 3 tool calls), then a final
  step writes the answer. A failed SQL query is repaired on the next pass.
- **Evidence, not verdicts.** The prompts require every number to come from a SQL result,
  every answer to say what the evidence is consistent with and what it was compared against,
  and to end with a Reasoning/Trace section (tools called, the SQL or filters used).
- **Read-only.** The agent investigates; it cannot suspend an account or issue a refund, and
  says so when asked.
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

Every LLM call in the app goes to `nvidia/nemotron-3-super-120b-a12b` (NVIDIA Nemotron 3
Super) on Token Factory; there is no other model path. The model id comes from the
`MODEL_AGENT` setting. One question fans out into several Nemotron calls:

| Call | Where | How |
|---|---|---|
| Reason / route | `server/chat_agent/Pipeline/workflow/workflow.py` (`reason_and_route`) | Structured output (`ReasoningDecision`) |
| SQL and search arguments | same file (`execute_tool`) | Structured output (`SQLCallArgs`, `VectorCallArgs`) |
| Final answer, follow-up questions | same file (`synthesize_answer`, `generate_follow_up`) | Structured output |
| Evaluation judge | `server/evaluation/LLMEvaluator.py` | Structured output (`EvaluationResult`) |

Measured on the synthetic dataset, each answer checked against the planted scenario:

- "Has any single IP address tried to log into many different accounts?" -- one SQL call,
  answer in 12 s.
- "Which customers have an unusually high refund rate?" -- two SQL calls (the rate, then the
  store-wide baseline), answer in 16 s.
- "Was there anything unusual about Samuel Hale's most recent order?" -- SQL then two session
  searches, answer in 25 s: order 100x his usual, first-time device and country, password
  reset and address change in the same session.
- Judge on Nemotron 3 Super: 4-7 s per evaluation.

Nemotron 3 Nano and Nemotron 3.5 Lightning were also tried as the judge. Nano took 70-105 s
and sometimes returned incomplete results; Lightning did not produce the nested result shape.
The judge therefore runs on Super (`MODEL_FAST` can point it at another model).

## Where Token Factory helped

- **One OpenAI-compatible endpoint.** The whole app talks to Token Factory through LlamaIndex
  `OpenAILike` (`get_nebius_llm` in `server/core/dependencies.py`). Moving the project onto
  Nemotron was a provider change, not a pipeline change.
- **Trying models is a config change.** The three Nemotron models above were compared as the
  judge by changing a model id, with no deployment or GPU setup.
- **Structured output is served by the API.** Every step of the workflow and the judge get
  schema-validated JSON back from Nemotron, with no self-hosted model server to run.

## Other Nebius services

None yet. Token Factory is the only Nebius service this project uses today.

## Setup

Requirements: Docker with Compose, and a Nebius Token Factory API key.

1. Create the two env files from the examples in the repo root:

   ```
   cp .env.db.example .env.db    # then set POSTGRES_PASSWORD
   cp .env.example .env          # then set NEBIUS_API_KEY
   ```

   `.env.db` is the Postgres superuser for the container. `.env` is the app's configuration;
   its hostnames are the Compose service names, and `DB_USER` / `DB_PASSWORD` are the app
   user created by `db_init/03_create_users.sh`, whose password is `APP_DB_PASSWORD` in
   `.env.db` (the two must match; the example files agree out of the box). `NEBIUS_BASE_URL` defaults to
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

4. Build the session vector store from the database (downloads the BGE-M3 embedding model on
   first run):

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

On a Linux VM with Docker (8 GB RAM, 16 GB to be comfortable; no GPU needed -- the server and
the ingestor each hold the BGE-M3 model, about 3 GB):

```
git clone <this repo> && cd <the cloned folder>
cp .env.db.example .env.db    # set POSTGRES_PASSWORD and your own APP_DB_PASSWORD
cp .env.example .env          # set DB_PASSWORD (= APP_DB_PASSWORD), NEBIUS_API_KEY, rate limits
docker compose -f docker-compose.prod.yml up -d --build
```

That one command creates the database, runs the migrations, loads the synthetic data, builds
the vector store and then starts the server, in that order. The first start takes a while
(the ingestor downloads BGE-M3 and embeds every session); later starts skip the work that is
already done. Embedding the 502 sessions on CPU took 8 minutes on an 8-core laptop. Follow it with
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
| Retrieval | BGE-M3 embedding service, Qdrant hybrid search, Redis cache, ingestion checkpointing | One document per store session, the session ingestion query, search filters by customer / device / country / declined payments |
| Evaluation | Evaluation service and storage | Judge on Nemotron, result streamed to the UI |
| App | FastAPI + Chainlit shell, streaming events | Single-pipeline UI, rate limiting |
| Deployment | Dev Docker Compose | Production compose with one-command bring-up (migrate, seed, ingest), migrations image, Caddy front end |
