"""
POST /benchmark — manual Moss vs Qdrant latency comparison.

Never called from startup, health, or a timer. Results are cached so
repeat clicks do not hit Moss Cloud.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from config import get_settings
from moss_client import get_moss_client
from moss_guard import live_moss_stats
from retrieval import qdrant_store
from retrieval.corpus import BENCHMARK_DOCS, BENCHMARK_QUERY

logger = logging.getLogger(__name__)
router = APIRouter(tags=["benchmark"])

# Server-side cache: the last live Moss query for this process.
_cache: dict[str, Any] | None = None
_qdrant_seeded = False


class BenchmarkResponse(BaseModel):
    query: str
    moss_ms: float | None
    qdrant_ms: float
    moss_hits: int
    qdrant_hits: int
    cached: bool
    cache_age_s: float | None
    cache_ttl_s: int
    live_query_count: int
    isolation: str
    moss_error: str | None = None


def _seed_qdrant_once() -> None:
    global _qdrant_seeded
    if _qdrant_seeded:
        return
    qdrant_store.upsert_docs(BENCHMARK_DOCS)
    _qdrant_seeded = True


@router.post("/benchmark", response_model=BenchmarkResponse)
async def run_benchmark():
    """
    Manual-only. Do not wire this to page load, polling, or retry loops.
    """
    global _cache
    cfg = get_settings()
    ttl = cfg.benchmark_cache_ttl_s
    now = time.time()
    if _cache and (now - _cache["ts"]) < ttl:
        age = round(now - _cache["ts"], 1)
        logger.info("benchmark.cache_hit | age_s=%s", age)
        return BenchmarkResponse(**{**_cache["body"], "cached": True, "cache_age_s": age})

    _seed_qdrant_once()

    moss = get_moss_client()
    (moss_docs, moss_ms), (qdrant_docs, qdrant_ms) = await _parallel(moss)

    moss_error = "quota_exhausted" if moss.quota_exhausted else None
    moss_value = None if moss_error else round(moss_ms, 2)

    body = {
        "query": BENCHMARK_QUERY,
        "moss_ms": moss_value,
        "qdrant_ms": round(qdrant_ms, 2),
        "moss_hits": len(moss_docs),
        "qdrant_hits": len(qdrant_docs),
        "cached": False,
        "cache_age_s": None,
        "cache_ttl_s": ttl,
        "live_query_count": live_moss_stats()["live_query_count"],
        "isolation": "shared_index_metadata_filter",
        "moss_error": moss_error,
    }
    _cache = {"ts": now, "body": body}
    logger.info(
        "benchmark.live | moss_ms=%s qdrant_ms=%s",
        body["moss_ms"],
        body["qdrant_ms"],
    )
    return BenchmarkResponse(**body)


async def _parallel(moss):
    import asyncio

    moss_res = await moss.query(BENCHMARK_QUERY, top_k=3, reason="manual_benchmark")
    qdrant_res = await asyncio.to_thread(qdrant_store.query, BENCHMARK_QUERY, 3, None)
    return moss_res, qdrant_res


@router.get("/benchmark/cache")
async def benchmark_cache_meta():
    """Read cache/stats without touching Moss."""
    cfg = get_settings()
    now = time.time()
    if not _cache:
        return {"cached": False, "cache_ttl_s": cfg.benchmark_cache_ttl_s, **live_moss_stats()}
    age = round(now - _cache["ts"], 1)
    return {
        "cached": age < cfg.benchmark_cache_ttl_s,
        "cache_age_s": age,
        "cache_ttl_s": cfg.benchmark_cache_ttl_s,
        "last": {k: _cache["body"][k] for k in ("moss_ms", "qdrant_ms", "query")},
        **live_moss_stats(),
    }


@router.post("/ops/sync")
async def sync_pending():
    """Batch Postgres → Qdrant (always) and Moss (only if MOSS_SYNC_ENABLED)."""
    from retrieval.syncer import sync_pending_messages
    return await sync_pending_messages()
