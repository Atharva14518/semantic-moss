"""
moss_guard.py — Single choke-point for live Moss Cloud queries.

HARD RULES (budget cap):
  - Never poll, retry-loop, refresh-on-focus, or auto-run a Moss query.
  - Benchmark UI must be a manual button. Server cache is the backstop.
  - Ingest is separate and even more expensive — do not call add_docs from here.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

logger = logging.getLogger(__name__)

LiveReason = Literal["manual_benchmark", "agent_retrieval", "health_query"]

_live_count = 0
_last_reason = ""
_last_ts = 0.0


def live_moss_stats() -> dict:
    return {
        "live_query_count": _live_count,
        "last_reason": _last_reason or None,
        "last_ts": _last_ts or None,
    }


def record_live_moss_query(reason: str) -> int:
    """Log every live query. Call this immediately before MossClient.query."""
    global _live_count, _last_reason, _last_ts
    _live_count += 1
    _last_reason = reason
    _last_ts = time.time()
    logger.info(
        "moss.live_query | count=%d reason=%s",
        _live_count,
        reason,
    )
    return _live_count
