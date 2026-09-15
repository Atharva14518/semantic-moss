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

    g.add_node("planner", planner_node)
    g.add_node("executor", executor_node)
    g.add_node("reviewer", reviewer_node)
    g.add_node("escalate", escalate_node)
    g.add_node("finalise", finalise_node)

    g.set_entry_point("planner")

    g.add_edge("planner", "executor")

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
    g.add_edge("escalate", END)

    return g


def compile_graph(checkpointer: AsyncPostgresSaver):
    """Compile the graph with a live Postgres checkpointer."""
    g = build_graph()
    return g.compile(checkpointer=checkpointer)


def checkpointer_context(db_url: str | None = None):
    """
    Returns the async context manager for AsyncPostgresSaver.
    Use as:
        async with checkpointer_context() as checkpointer:
            await checkpointer.setup()
            app.state.checkpointer = checkpointer
            yield  # hold open for app lifetime
    """
    cfg = get_settings()
    url = db_url or cfg.database_url
    return AsyncPostgresSaver.from_conn_string(url)
