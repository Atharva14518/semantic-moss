# Recall

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
- [ ] **Phase 5** — Reliability: reconnect rehydration is complete; retries, backoff, and broader isolation testing remain
- [x] **Phase 5.5** — Data erasure, durable decision explainability, and 12-factor operational review
- [ ] **Phase 6** — Deployment: Fly.io/Railway + Vercel
- [ ] **Phase 7** — Polish: OpenTelemetry, prompt/limit verification, demo video, and design review

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

## Phase 5.5 - Data Rights, Explainability, and Operational Notes

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
  automatic restart recovery is still Phase 5 work.

## Non-Goals (v1)

- Mobile / responsive layouts — desktop workspace only
- Real-time voice or video between participants
- Multi-LLM routing (single Grok backend for all agents)
- Fine-tuning or custom model training
- SOC 2 / enterprise SSO
