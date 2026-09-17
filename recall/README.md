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
- [x] **Phase 2** — Multiplayer UI: WebSockets, three-pane React workspace
- [x] **Phase 3** — Security: domain allowlists, Moss authz, flagged events
- [x] **Phase 4** — Cold storage + on-demand benchmark panel
- [ ] **Phase 5** — Reliability: LiveKit reconnection/state rehydration, retries, backoff, full test suite
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

## Phase 5.5 - Data Rights, Explainability, and Operational Notes

Workspace history has a default **30-day retention policy**. Automatic retention
enforcement is a deployment-phase responsibility; the policy is defined now and
the data-rights endpoint is available today. A workspace owner can erase all
workspace-owned Postgres records and the corresponding known Moss document IDs:

```bash
curl -X DELETE "http://localhost:8100/workspace/${WORKSPACE_ID}/data"
```

Deletion is deliberately fail-closed: Moss document deletion runs before the
Postgres transaction, so a Moss failure leaves durable rows intact and retryable.
The shared index is never deleted. Agent activity records include a short,
structured `reasoning` field (decision summary, not hidden chain-of-thought),
which appears under the **Why?** control in the activity thread.
Persisted activity metadata is intentionally limited to the event's role,
workspace/task association, and concise decision summary; raw model prompts,
tokens, and request bodies are not stored in the activity payload.

### 12-factor alignment

- **Config:** credentials and service URLs are read from environment variables;
  no production secrets are committed to code.
- **Backing services:** Postgres, Redis, Qdrant, Moss, and Groq are replaceable
  attached resources configured externally.
- **Stateless processes:** FastAPI does not retain required task state in memory;
  LangGraph checkpoints and durable task data live in Postgres.
- **Disposability:** the backend handles SIGTERM through container shutdown;
  incomplete graph state remains checkpointed and can be resumed/retried.

## Non-Goals (v1)

- Mobile / responsive layouts — desktop workspace only
- Real-time voice or video between participants
- Multi-LLM routing (single Grok backend for all agents)
- Fine-tuning or custom model training
- SOC 2 / enterprise SSO
