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
curl http://localhost:8000/health | python3 -m json.tool

# 5. Run the Moss round-trip smoke test
curl http://localhost:8000/moss/test | python3 -m json.tool
```

## Services

| Service | Local URL | Purpose |
|---|---|---|
| Backend API | http://localhost:8000 | FastAPI + agents |
| API Docs | http://localhost:8000/docs | Swagger UI |
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
- [ ] **Phase 1** — Core orchestration: LangGraph state machine, Postgres checkpointing
- [ ] **Phase 2** — Multiplayer UI: WebSockets, three-pane React workspace
- [ ] **Phase 3** — Security: domain allowlists, per-workspace Moss isolation
- [ ] **Phase 4** — Cold storage + benchmark panel
- [ ] **Phase 5** — Reliability: retries, backoff, test suite
- [ ] **Phase 6** — Deployment: Fly.io + Vercel
- [ ] **Phase 7** — Polish: README, demo video, design review

## Non-Goals (v1)

- Mobile / responsive layouts — desktop workspace only
- Real-time voice or video between participants
- Multi-LLM routing (single Grok backend for all agents)
- Fine-tuning or custom model training
- SOC 2 / enterprise SSO
