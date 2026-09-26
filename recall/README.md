# Recall — a shared workspace where humans and AI agents collaborate on long-running tasks.

**🔴 Live demo: [https://semantic-moss.vercel.app/](https://semantic-moss.vercel.app/)**

> Popular AI agents today are single-player. ChatGPT gives one person one private conversation — if two teammates both need help on the same task, they open two separate chats that can't see each other, and nothing carries over to the next session. Even multi-agent tools like AutoGPT or CrewAI are built around one person watching a single run, not a shared, persistent workspace. Recall closes that gap: a shared workspace where humans and agents work on the same task, in real time, with a memory that doesn't reset.

Real-time multiplayer workspace for humans and AI agents (Planner, Executor, Reviewer). Powered by Moss for sub-10ms semantic retrieval, LangGraph for durable multi-agent orchestration, and Postgres for persisted task state.

## Quick Start

```bash
# 1. Clone and enter the application directory
git clone https://github.com/Atharva14518/semantic-moss.git
cd semantic-moss/recall

# 2. Create local configuration and fill in the required credentials
cp .env.example .env
# Set MOSS_PROJECT_ID, MOSS_PROJECT_KEY, GROQ_API_KEY,
# LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET.

# 3. Bring up the backend stack
docker compose up -d --build

# 4. Verify everything is healthy
curl http://localhost:8100/health | python3 -m json.tool

# 5. Start the Next.js frontend on http://localhost:3000
cd frontend && npm install && npm run dev
```

`GET /moss/test` performs a real Moss write/read round trip. Run it manually only when you intend to spend external API quota.

## Services

| Service | Local URL | Purpose |
|---|---|---|
| Frontend | http://localhost:3000 | Next.js workspace |
| Backend API | http://localhost:8100 | FastAPI + agents |
| API Docs | http://localhost:8100/docs | Swagger UI |
| Postgres | localhost:5432 | Source of truth |
| Redis | localhost:6379 | Locks, queues |
| Qdrant | http://localhost:6333 | Cold vector store |
| Moss | in-process | Sub-10ms retrieval |

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Frontend (Next.js + LiveKit data channels)              │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTPS / LiveKit
┌───────────────────────▼──────────────────────────────────┐
│  FastAPI Backend                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ LangGraph State Machine                             │ │
│  │  Planner → Executor → Reviewer → (Escalate)        │ │
│  │  Checkpointed to Postgres                          │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌──────────┐  ┌────────┐  ┌────────┐  ┌─────────────┐  │
│  │ Postgres │  │ Redis  │  │ Qdrant │  │ Moss (local)│  │
│  │ (state)  │  │(locks) │  │(cold)  │  │ (<10ms)     │  │
│  └──────────┘  └────────┘  └────────┘  └─────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Build Phases

- [x] **Phase 0** — Foundations: Docker stack, schema, /health, Moss round-trip
- [x] **Phase 1** — Core orchestration: LangGraph state machine, Postgres checkpointing
- [x] **Phase 2** — Multiplayer UI: LiveKit data channels and three-pane Next.js workspace
- [x] **Phase 3** — Security: domain allowlists, Moss authz, flagged events
- [x] **Phase 4** — Cold storage + on-demand benchmark panel
- [x] **Phase 5** — Reliability: LiveKit reconnect rehydration, Groq retry-with-backoff, subtask cap, workspace isolation tests
- [x] **Phase 5.5** — Data erasure (Moss + Qdrant + LangGraph checkpoints), reasoning rehydration, 12-factor ops
- [x] **Phase 6** — Deployment: `fly.toml` for Fly.io, `vercel.json` for Vercel — credentials and secrets documented
- [x] **Phase 7** — OpenTelemetry tracing on all LLM calls, CRISPE prompt claims verified in code

## Moss isolation (honest)

Recall uses **one shared Moss Cloud index**. Workspace separation is a `workspace_id` field on each document plus an orchestrator authorization check that strips foreign hits before they reach an agent. That is **metadata-filtered isolation**, not per-tenant Moss projects. Separate indexes were dropped on purpose to stay under a $5 Cloud cap.

Postgres → Qdrant sync is local and free. Postgres → Moss ingest is batched and **off unless `MOSS_SYNC_ENABLED=true`**.

## Phase 4 — Benchmark

The retrieval panel in the right pane is **manual**. It never runs on page load or a timer. Repeat clicks within 180s are served from cache (UI note: "last run Xs ago"). Health checks load the index only; they do not query Moss.

```bash
curl -s -X POST http://localhost:8100/benchmark | python3 -m json.tool
# second call is cached — does not hit Moss Cloud
curl -s -X POST http://localhost:8100/benchmark | python3 -m json.tool
```

A copy of a live (or quota-degraded) result is saved at `recall/docs/benchmark-backup.json` for judging if the cap is exhausted. Do not run `GET /moss/test` during a demo — it writes to Moss Cloud.

## Phase 3 — Security

Executor Playwright navigation is gated by a per-workspace domain allowlist. Blocked attempts are written to `audit_logs`, broadcast as `flagged_event` over LiveKit, and shown in the activity thread.

Moss retrieval is **not** a separate Moss project per workspace. Documents carry `workspace_id` (and often a `{workspace_id}::{id}` prefix). The orchestrator strips foreign hits before they reach an agent.

```bash
# Replace WORKSPACE_ID with the UUID shown in the left pane (last 8 chars are a suffix).
# The UI stores the full id in localStorage under recall_ws_id.

curl -s -X POST "http://localhost:8100/workspace/${WORKSPACE_ID}/executor/browse" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://evil.com/exfiltrate"}' | python3 -m json.tool

curl -s "http://localhost:8100/workspace/${WORKSPACE_ID}/audit" | python3 -m json.tool
```

A live UI tab on that workspace should show a flagged Executor event immediately.

## Phase 5 — Reliability

Groq LLM calls in all five agent nodes are wrapped in a tenacity retry loop: 3
attempts, exponential backoff starting at 1 s (capped at 8 s), retry only on
HTTP 429 or rate-limit signals. Non-retriable errors propagate immediately.

The Planner enforces the 5-subtask cap in code (not only in the prompt), so a model that returns 6+ items is silently truncated. The 512-token output limit per call is applied at the ChatGroq constructor (`groq_max_tokens = 512`). LiveKit reconnect triggers an HTTP rehydration call so no activity is permanently lost. Workspace isolation is verified with pure-function routing tests.

## Phase 5.5 — Data Rights, Explainability, and Operational Notes

Workspace history has a default **30-day retention policy**. Automatic retention
enforcement is a deployment-phase responsibility; the policy is defined now and
the data-rights endpoint is available today. A caller with access to a workspace
can erase its application rows, LangGraph checkpoints, Moss documents, and
Qdrant vectors:

```bash
curl -X DELETE "http://localhost:8100/workspace/${WORKSPACE_ID}/data"
```

Deletion is deliberately fail-closed for durable Postgres state: Moss and Qdrant
deletion run before the Postgres transaction, so a secondary-store failure leaves
durable rows intact and retryable. The shared indexes are never deleted. Agent
activity records include a short `reasoning` field (a decision summary, not hidden
chain-of-thought), which appears under the **Why?** control in the activity thread.
Persisted activity and reasoning are restored through the task API on initial load
and after LiveKit reconnects. Raw model prompts, tokens, and request bodies are not
stored in the activity payload.

### 12-factor alignment

- **Config:** credentials and service URLs are read from environment variables;
  no production secrets are committed to code.
- **Backing services:** Postgres, Redis, Qdrant, Moss, and Groq are replaceable
  attached resources configured externally.
- **Stateless processes:** FastAPI does not retain required task state in memory;
  LangGraph checkpoints and durable task data live in Postgres.
- **Disposability:** Uvicorn receives a bounded graceful-shutdown window, the
  LangGraph checkpointer exits through FastAPI lifespan handling, and the database
  engine is explicitly disposed. Incomplete graph state remains checkpointed;
  automatic restart recovery is a known gap.

## Phase 6 — Deployment

Deployment configuration ships with the repository:

- **Backend (Fly.io):** `recall/fly.toml` — single-worker Uvicorn, `/health` checks, secrets listed in comments, 30-second graceful-shutdown window, `shared-cpu-1x` VM. Deploy from `recall/` with `fly deploy`.
- **Frontend (Vercel):** `recall/frontend/vercel.json` — auto-detects Next.js; set `NEXT_PUBLIC_API_URL` in Vercel project settings to the Fly.io backend URL.
- **Required secrets:** `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY`, `GROQ_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
- **Optional:** `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_HEADERS` — set for Honeycomb or Jaeger.

## Phase 7 — Observability

Every LLM call in the agent pipeline (recall, planner, executor, reviewer, finalise) is wrapped in an OpenTelemetry span capturing:

| Attribute | Value |
|---|---|
| `llm.node` | Agent role (e.g. `planner`) |
| `llm.model` | Groq model name from config |
| `llm.latency_ms` | Wall-clock time including retries |
| `llm.input_tokens` | Token count from response metadata |
| `llm.output_tokens` | Token count from response metadata |

When `OTEL_EXPORTER_OTLP_ENDPOINT` is not set, tracing is a no-op — the SDK is installed but no data leaves the process. When set, spans are exported via OTLP/HTTP to any compatible collector (Honeycomb free tier, local Jaeger, etc.).

**CRISPE verification:** The Planner system prompt caps subtasks at 2-5; code enforces the ≤5 upper bound by truncating. The `groq_max_tokens = 512` limit is passed directly to ChatGroq. Both claims in the PRD CRISPE table now match delivered code.

## Non-Goals (v1)

- Mobile / responsive layouts — desktop workspace only
- Real-time voice or video between participants
- Multi-LLM routing (single Grok backend for all agents)
- Fine-tuning or custom model training
- SOC 2 / enterprise SSO
