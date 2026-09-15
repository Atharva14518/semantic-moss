# Recall

Real-time multiplayer workspace for humans and AI agents (Planner, Executor, Reviewer). Powered by Moss for sub-10ms semantic retrieval, LangGraph for durable multi-agent orchestration, and Postgres for persisted task state.

## Quick Start — Phase 0

```bash
# 1. Clone and enter the project
cd recall

# 2. Copy env and fill in your XAI_API_KEY
cp .env .env.local   # already has Moss creds

# 3. Bring up the full stack
docker compose up -d --build

# 4. Verify everything is healthy
curl http://localhost:8100/health | python3 -m json.tool

# 5. Run the Moss round-trip smoke test
curl http://localhost:8100/moss/test | python3 -m json.tool

# 6. Frontend (port 5175 — 5173 is often another Vite app)
cd frontend && npm install && npm run dev
```

## Services

| Service | Local URL | Purpose |
|---|---|---|
| Frontend | http://localhost:5175 | React workspace |
| Backend API | http://localhost:8100 | FastAPI + agents |
| API Docs | http://localhost:8100/docs | Swagger UI |
| Postgres | localhost:5432 | Source of truth |
| Redis | localhost:6379 | Locks, queues |
| Qdrant | http://localhost:6333 | Cold vector store |
| Moss | in-process | Sub-10ms retrieval |

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Frontend (React + WebSockets)                           │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTP / WS
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
- [x] **Phase 2** — Multiplayer UI: WebSockets, three-pane React workspace
- [x] **Phase 3** — Security: domain allowlists, Moss authz, flagged events
- [x] **Phase 4** — Cold storage + on-demand benchmark panel
- [ ] **Phase 5** — Reliability: retries, backoff, test suite
- [ ] **Phase 6** — Deployment: Fly.io + Vercel
- [ ] **Phase 7** — Polish: README, demo video, design review

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

Executor Playwright navigation is gated by a per-workspace domain allowlist. Blocked attempts are written to `audit_logs`, broadcast as `flagged_event` on the workspace WebSocket, and shown in the activity thread.

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

## Non-Goals (v1)

- Mobile / responsive layouts — desktop workspace only
- Real-time voice or video between participants
- Multi-LLM routing (single Grok backend for all agents)
- Fine-tuning or custom model training
- SOC 2 / enterprise SSO
