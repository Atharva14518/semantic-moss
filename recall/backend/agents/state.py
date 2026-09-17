"""
agents/state.py — LangGraph state definition for the Recall orchestration graph.

The state is a TypedDict that flows through every node.
LangGraph checkpoints this entire object to Postgres on every step.
"""

from __future__ import annotations

from typing import Annotated, Any
from typing_extensions import TypedDict
import operator


class RecallState(TypedDict):
    # ── Core task ────────────────────────────────────────────────
    workspace_id: str
    task_id: str
    goal: str                          # The human's stated objective
    request_type: str                  # "recall" | "task"; set before routing

    # ── Planner output ───────────────────────────────────────────
    subtasks: list[dict[str, Any]]     # [{id, description, status}]

    # ── Executor output ──────────────────────────────────────────
    executor_results: Annotated[list[dict[str, Any]], operator.add]  # accumulate

    # ── Reviewer ─────────────────────────────────────────────────
    review_status: str                 # "approved" | "rejected" | "escalated" | ""
    review_feedback: str               # Reviewer's reasoning
    review_attempts: int               # Incremented each failed review pass

    # ── Messages (broadcast to WebSocket clients) ─────────────────
    messages: Annotated[list[dict[str, Any]], operator.add]  # accumulate

    # ── Final ─────────────────────────────────────────────────────
    final_result: str | None
    error: str | None
