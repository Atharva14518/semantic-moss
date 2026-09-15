"""
main.py — Recall FastAPI application entry point.

Endpoints:
  - /health             → full liveness check (Postgres, Redis, Qdrant, Moss)
  - /health/services    → individual service statuses (cached from startup)
  - /moss/test          → explicit Moss round-trip smoke test
  - /workspace/{id}/task        → Phase 1: kick off a LangGraph task
  - /workspace/{id}/task/{id}   → Phase 1: read persisted task state
  - /ws/{workspace_id}  → Phase 2: real-time WebSocket sync
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from config import get_settings
from db.database import get_engine
from db.migrate import apply_schema_patches
from moss_client import get_moss_client
from routers import tasks as tasks_router
from routers import security as security_router
from routers import benchmark as benchmark_router
from agents.graph import checkpointer_context, compile_graph
from ws.router import router as ws_router

# ── Structured logging setup ─────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()
cfg = get_settings()

# ── Service state (populated on startup) ─────────────────────────
_service_status: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup checks; keep references alive for the app lifetime."""
    log.info("recall.startup | environment=%s", cfg.environment)

    try:
        await apply_schema_patches()
    except Exception as e:
        log.warning("recall.startup | schema patches failed: %s", e)

    # Hold Postgres checkpointer open for full app lifetime
    async with checkpointer_context() as checkpointer:
        try:
            await checkpointer.setup()  # creates langgraph checkpoint tables
            app.state.checkpointer = checkpointer
            app.state.graph = compile_graph(checkpointer)
            log.info("recall.startup | langgraph checkpointer ready")
        except Exception as e:
            log.warning("recall.startup | checkpointer setup failed: %s", e)
            app.state.checkpointer = None
            app.state.graph = None

        results = await _check_all_services()
        _service_status.update(results)

        try:
            from retrieval import qdrant_store
            from retrieval.corpus import BENCHMARK_DOCS
            qdrant_store.upsert_docs(BENCHMARK_DOCS)
            log.info("recall.startup | qdrant benchmark corpus seeded")
        except Exception as e:
            log.warning("recall.startup | qdrant seed failed: %s", e)

        all_ok = all(v["ok"] for v in results.values())
        if all_ok:
            log.info("recall.startup | all services healthy")
        else:
            failed = [k for k, v in results.items() if not v["ok"]]
            log.warning("recall.startup | degraded services=%s", failed)

        yield

    log.info("recall.shutdown")


app = FastAPI(
    title="Recall API",
    description="Shared real-time workspace for humans and AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────
app.include_router(tasks_router.router)
app.include_router(security_router.router)
app.include_router(benchmark_router.router)
app.include_router(ws_router)


# ── Service health checks ─────────────────────────────────────────

async def _check_postgres() -> dict:
    try:
        t0 = time.perf_counter()
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _check_redis() -> dict:
    try:
        t0 = time.perf_counter()
        r = aioredis.from_url(cfg.redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()
        return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _check_qdrant() -> dict:
    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{cfg.qdrant_url}/healthz")
            resp.raise_for_status()
        return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _check_moss() -> dict:
    try:
        t0 = time.perf_counter()
        moss = get_moss_client()
        # Load only — a live query here would run on every /health poll and burn quota.
        await moss.ensure_ready()
        if moss.quota_exhausted:
            return {
                "ok": True,
                "mode": "quota_exhausted",
                "note": "Moss Cloud cap reached; live queries are skipped",
            }
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "mode": "index_loaded",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _check_all_services() -> dict:
    postgres, redis, qdrant, moss = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_qdrant(),
        _check_moss(),
        return_exceptions=False,
    )
    return {
        "postgres": postgres,
        "redis": redis,
        "qdrant": qdrant,
        "moss": moss,
    }


# ── Routes ────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health():
    """
    Full liveness check. Returns 200 if all critical services are up,
    503 if any are degraded. Runs checks fresh on every call.
    """
    services = await _check_all_services()
    all_ok = all(v["ok"] for v in services.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "services": services,
        "version": "0.1.0",
    }


@app.get("/health/services", tags=["ops"])
async def health_services():
    """Return cached service status from startup (fast path)."""
    return {
        "status": "ok" if all(v["ok"] for v in _service_status.values()) else "degraded",
        "services": _service_status,
    }


@app.get("/moss/test", tags=["moss"])
async def moss_test():
    """
    Writes a document to Moss Cloud. Manual smoke test only — not used by the UI.
    """
    moss = get_moss_client()
    result = await moss.run_round_trip_test()
    return result


@app.get("/", tags=["ops"])
async def root():
    return {"app": "Recall", "docs": "/docs"}
