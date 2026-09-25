"""
agents/graph.py — LangGraph state machine for Recall.

Graph topology:
  START → planner → executor → reviewer ──► approved → finalise → END
                        ▲          │
                        └─rejected─┘ (up to MAX_REVIEW_ATTEMPTS)
                                   │
                             escalated → escalate → END

Checkpointer: AsyncPostgresSaver used as an async context manager,
held open for the full application lifetime in main.py lifespan.
Task state survives backend restarts.
"""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.state import RecallState
from agents.nodes import (
    planner_node,
    classify_request_node,
    recall_node,
    executor_node,
    reviewer_node,
    escalate_node,
    finalise_node,
    MAX_REVIEW_ATTEMPTS,
)
from config import get_settings

logger = logging.getLogger(__name__)


# ── Routing logic ─────────────────────────────────────────────────

def route_after_executor(state: RecallState) -> str:
    """After executor, check if any subtasks are still pending."""
    pending = [s for s in state.get("subtasks", []) if s.get("status") == "pending"]
    if pending:
        return "executor"
    return "reviewer"


def route_after_classification(state: RecallState) -> str:
    return "recall" if state.get("request_type") == "recall" else "planner"


def route_after_planner(state: RecallState) -> str:
    """An empty plan is terminal; do not spend three review attempts on it."""
    return "escalate" if not state.get("subtasks") else "executor"


def route_after_reviewer(state: RecallState) -> str:
    """After reviewer: approve → finalise, reject → retry or escalate."""
    decision = state.get("review_status", "")
    attempts = state.get("review_attempts", 0)

    if decision == "approved":
        return "finalise"
    if attempts >= MAX_REVIEW_ATTEMPTS:
        return "escalate"
    return "executor"


# ── Graph builder ─────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Construct the LangGraph StateGraph (no checkpointer attached here)."""
    g = StateGraph(RecallState)

    g.add_node("classify", classify_request_node)
    g.add_node("recall", recall_node)
    g.add_node("planner", planner_node)
    g.add_node("executor", executor_node)
    g.add_node("reviewer", reviewer_node)
    g.add_node("escalate", escalate_node)
    g.add_node("finalise", finalise_node)

    g.set_entry_point("classify")

    g.add_conditional_edges("classify", route_after_classification, {
        "recall": "recall",
        "planner": "planner",
    })
    g.add_conditional_edges("planner", route_after_planner, {
        "executor": "executor",
        "escalate": "escalate",
    })

    g.add_conditional_edges("executor", route_after_executor, {
        "executor": "executor",
        "reviewer": "reviewer",
    })
    g.add_conditional_edges("reviewer", route_after_reviewer, {
        "finalise": "finalise",
        "escalate": "escalate",
        "executor": "executor",
    })

    g.add_edge("finalise", END)
    g.add_edge("recall", END)
    g.add_edge("escalate", END)

    return g


from contextlib import asynccontextmanager
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def compile_graph(checkpointer: AsyncPostgresSaver | None = None):
    """Compile the graph with a live Postgres checkpointer or in-memory fallback."""
    g = build_graph()
    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()


@asynccontextmanager
async def checkpointer_context(db_url: str | None = None):
    """
    Returns an async context manager for AsyncPostgresSaver backed by an
    AsyncConnectionPool. This automatically re-establishes dropped/idle connections
    on cloud Postgres (e.g. Render/Neon/Supabase).
    """
    cfg = get_settings()
    url = db_url or cfg.database_url
    if "postgresql+asyncpg://" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async with AsyncConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=10,
        max_idle=30,
        check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        yield AsyncPostgresSaver(conn=pool)

