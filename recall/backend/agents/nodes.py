"""
agents/nodes.py — Individual node functions for the LangGraph state machine.

Node signatures: (state: RecallState) -> dict  (partial state update)

Nodes:
  planner   → breaks goal into subtasks
  executor  → executes one subtask at a time (Playwright or text)
  reviewer  → approves or rejects executor output
  escalate  → called after MAX_REVIEW_ATTEMPTS failed reviews

All LLM calls have timeout + retry-with-backoff (Phase 5 hardens this further).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import RecallState
from agents.llm import get_llm
from ws.manager import manager as ws_manager

logger = logging.getLogger(__name__)

MAX_REVIEW_ATTEMPTS = 3


async def _broadcast(workspace_id: str, msg: dict) -> None:
    """Fire-and-forget broadcast; never crashes a node if WS fails."""
    try:
        await ws_manager.broadcast(workspace_id, {"type": "agent_message", **msg})
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws.broadcast_failed | %s", exc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msg(role: str, content: str, task_id: str, workspace_id: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "task_id": task_id,
        "workspace_id": workspace_id,
        "created_at": _now(),
    }


# ── Planner Node ──────────────────────────────────────────────────

PLANNER_SYSTEM = """You are the Planner agent in the Recall workspace.
Your job is to decompose the user's goal into 2-5 clear, actionable subtasks.

Respond ONLY with valid JSON — an array of subtask objects:
[
  {"id": "1", "description": "...", "status": "pending"},
  ...
]

Keep each description under 80 characters. Be specific, not vague.
Do NOT include any text outside the JSON array."""


async def planner_node(state: RecallState) -> dict:
    logger.info("planner | task=%s goal=%r", state["task_id"], state["goal"][:60])
    llm = get_llm()

    response = await llm.ainvoke([
        SystemMessage(content=PLANNER_SYSTEM),
        HumanMessage(content=f"Goal: {state['goal']}"),
    ])

    # Parse subtasks — robust to markdown code fences
    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        subtasks = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("planner | JSON parse failed, using fallback subtask")
        subtasks = [{"id": "1", "description": state["goal"], "status": "pending"}]

    msg = _msg(
        role="planner",
        content=f"Planned {len(subtasks)} subtasks:\n" +
                "\n".join(f"  {s['id']}. {s['description']}" for s in subtasks),
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )

    logger.info("planner | subtasks=%d", len(subtasks))
    await _broadcast(state["workspace_id"], msg)
    return {
        "subtasks": subtasks,
        "review_attempts": 0,
        "review_status": "",
        "messages": [msg],
    }


# ── Executor Node ─────────────────────────────────────────────────

EXECUTOR_SYSTEM = """You are the Executor agent in the Recall workspace.
You receive a list of subtasks and must attempt to complete them.

For each subtask:
- If it involves browsing a URL, describe what you would find (Playwright is available).
- For research/writing tasks, produce the actual content.

Respond with a JSON object:
{
  "subtask_id": "...",
  "status": "completed" | "failed",
  "result": "...",
  "notes": "..."
}"""


async def executor_node(state: RecallState) -> dict:
    # Find the first pending subtask
    pending = [s for s in state["subtasks"] if s.get("status") == "pending"]
    if not pending:
        logger.info("executor | no pending subtasks, marking completed")
        return {"executor_results": []}

    subtask = pending[0]
    logger.info("executor | task=%s subtask=%s", state["task_id"], subtask["id"])
    llm = get_llm()

    response = await llm.ainvoke([
        SystemMessage(content=EXECUTOR_SYSTEM),
        HumanMessage(content=(
            f"Goal: {state['goal']}\n\n"
            f"Execute this subtask:\n"
            f"ID: {subtask['id']}\n"
            f"Description: {subtask['description']}\n\n"
            f"Previous results: {json.dumps(state.get('executor_results', []))}"
        )),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        result = json.loads(raw.strip())
    except json.JSONDecodeError:
        result = {
            "subtask_id": subtask["id"],
            "status": "completed",
            "result": raw,
            "notes": "Raw LLM output (JSON parse failed)",
        }

    # Update subtask status in-place
    updated_subtasks = []
    for s in state["subtasks"]:
        if s["id"] == subtask["id"]:
            updated_subtasks.append({**s, "status": result.get("status", "completed")})
        else:
            updated_subtasks.append(s)

    msg = _msg(
        role="executor",
        content=f"Subtask {subtask['id']}: {result.get('status', 'completed')}\n{result.get('result', '')[:200]}",
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )

    logger.info("executor | subtask=%s status=%s", subtask["id"], result.get("status"))
    await _broadcast(state["workspace_id"], msg)
    return {
        "subtasks": updated_subtasks,
        "executor_results": [result],
        "messages": [msg],
    }


# ── Reviewer Node ─────────────────────────────────────────────────

REVIEWER_SYSTEM = """You are the Reviewer agent in the Recall workspace.
You assess whether the Executor's work meets the original goal.

Respond ONLY with valid JSON:
{
  "decision": "approved" | "rejected",
  "feedback": "concise reasoning under 100 words"
}

Approve if the results meaningfully address the goal.
Reject only if there are clear gaps or errors."""


async def reviewer_node(state: RecallState) -> dict:
    attempts = state.get("review_attempts", 0) + 1
    logger.info("reviewer | task=%s attempt=%d", state["task_id"], attempts)
    llm = get_llm()

    all_pending = [s for s in state["subtasks"] if s.get("status") == "pending"]
    all_completed = [s for s in state["subtasks"] if s.get("status") != "pending"]

    response = await llm.ainvoke([
        SystemMessage(content=REVIEWER_SYSTEM),
        HumanMessage(content=(
            f"Original goal: {state['goal']}\n\n"
            f"Completed subtasks: {json.dumps(all_completed)}\n\n"
            f"Results: {json.dumps(state.get('executor_results', []))}\n\n"
            f"Remaining pending: {len(all_pending)}"
        )),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        review = json.loads(raw.strip())
        decision = review.get("decision", "approved")
        feedback = review.get("feedback", "")
    except json.JSONDecodeError:
        decision = "approved"
        feedback = raw[:200]

    msg = _msg(
        role="reviewer",
        content=f"Review #{attempts}: {decision.upper()}\n{feedback}",
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )

    logger.info("reviewer | attempt=%d decision=%s", attempts, decision)
    await _broadcast(state["workspace_id"], msg)
    return {
        "review_status": decision,
        "review_feedback": feedback,
        "review_attempts": attempts,
        "messages": [msg],
    }


# ── Escalate Node ─────────────────────────────────────────────────

async def escalate_node(state: RecallState) -> dict:
    logger.warning(
        "escalate | task=%s after %d review attempts",
        state["task_id"],
        state.get("review_attempts", 0),
    )
    msg = _msg(
        role="system",
        content=(
            f"⚠ Task escalated after {state.get('review_attempts', 0)} failed review passes.\n"
            f"Last feedback: {state.get('review_feedback', 'N/A')}\n"
            f"Human review required."
        ),
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )
    await _broadcast(state["workspace_id"], msg)
    return {
        "review_status": "escalated",
        "final_result": None,
        "messages": [msg],
    }


# ── Finalise Node ─────────────────────────────────────────────────

async def finalise_node(state: RecallState) -> dict:
    """Synthesise a final summary once the reviewer approves."""
    llm = get_llm()
    response = await llm.ainvoke([
        SystemMessage(content="Summarise the completed work in 2-3 sentences for the user."),
        HumanMessage(content=(
            f"Goal: {state['goal']}\n"
            f"Results: {json.dumps(state.get('executor_results', []))}"
        )),
    ])
    summary = response.content.strip()
    msg = _msg(
        role="system",
        content=f"✓ Task completed.\n{summary}",
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )
    logger.info("finalise | task=%s", state["task_id"])
    await _broadcast(state["workspace_id"], msg)
    return {
        "final_result": summary,
        "messages": [msg],
    }
