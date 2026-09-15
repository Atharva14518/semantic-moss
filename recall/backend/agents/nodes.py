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
from agents.tools import browse_url, extract_urls
from db.database import get_session_factory
from db.workspaces import ensure_workspace
from moss_client import get_workspace_moss_client
from security.flagged import emit_domain_blocked
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


async def _workspace(workspace_id: str) -> dict:
    async with get_session_factory()() as session:
        ws = await ensure_workspace(session, workspace_id)
        await session.commit()
        return ws


async def _moss_context(workspace_id: str, goal: str) -> str:
    """Retrieve authorized Moss hits for this workspace only. Failures never stall planning."""
    try:
        ws = await _workspace(workspace_id)
        moss = get_workspace_moss_client(
            ws["moss_project_id"],
            ws["moss_project_key"],
            ws["moss_index_name"],
        )
        hits, latency_ms = await moss.query_authorized(workspace_id, goal, top_k=3)
        if not hits:
            return ""
        lines = [f"Workspace memory ({latency_ms:.1f}ms, authorized):"]
        for hit in hits:
            lines.append(f"- {hit.get('text', '')[:200]}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        logger.warning("planner.moss_context_failed | %s", exc)
        return ""


async def planner_node(state: RecallState) -> dict:
    logger.info("planner | task=%s goal=%r", state["task_id"], state["goal"][:60])
    llm = get_llm()
    moss_context = await _moss_context(state["workspace_id"], state["goal"])

    human = f"Goal: {state['goal']}"
    if moss_context:
        human = f"{human}\n\n{moss_context}"

    response = await llm.ainvoke([
        SystemMessage(content=PLANNER_SYSTEM),
        HumanMessage(content=human),
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

EXECUTOR_SYNTHESIS_SYSTEM = """You are the Executor agent in the Recall workspace.
You have been given a subtask to complete. You may have real web content retrieved
by a Playwright browser tool — use it as your primary source.

Respond ONLY with valid JSON:
{
  "subtask_id": "<id>",
  "status": "completed" | "failed",
  "result": "<concise factual answer based on the content provided>",
  "notes": "<source URL if browsed, or 'LLM only' if no browser was used>"
}

Do NOT include any text outside the JSON object."""

EXECUTOR_LLM_ONLY_SYSTEM = """You are the Executor agent in the Recall workspace.
Complete the following subtask using your knowledge.

Respond ONLY with valid JSON:
{
  "subtask_id": "<id>",
  "status": "completed" | "failed",
  "result": "<your answer>",
  "notes": "LLM only — no browser available for this subtask"
}"""


async def executor_node(state: RecallState) -> dict:
    """Execute the next pending subtask.

    If the subtask description contains a URL → Playwright navigates to it
    (9 s timeout, domain allowlisted) and feeds real page content to the LLM
    for synthesis.  If no URL is present → pure LLM.
    Either path returns a structured result; errors are captured, not raised.
    """
    pending = [s for s in state["subtasks"] if s.get("status") == "pending"]
    if not pending:
        logger.info("executor | no pending subtasks")
        return {"executor_results": []}

    subtask = pending[0]
    logger.info("executor | task=%s subtask=%s desc=%r",
                state["task_id"], subtask["id"], subtask["description"][:60])
    llm = get_llm()

    # ── Step 1: detect URLs in the subtask description ────────────
    urls = extract_urls(subtask["description"] + " " + state.get("goal", ""))
    browse_result: dict | None = None

    if urls:
        url = urls[0]  # take the first URL found
        logger.info("executor | browsing url=%s", url)
        ws = await _workspace(state["workspace_id"])
        intent_msg = _msg(
            role="executor",
            content=f"Browsing {url}",
            task_id=state["task_id"],
            workspace_id=state["workspace_id"],
        )
        await _broadcast(state["workspace_id"], intent_msg)

        browse_result = await browse_url(
            url,
            timeout_ms=9000,
            allowed_domains=ws["allowed_domains"],
        )

        if browse_result.get("blocked"):
            await emit_domain_blocked(
                workspace_id=state["workspace_id"],
                url=url,
                hostname=browse_result.get("hostname") or "",
                error=browse_result["error"],
                task_id=state["task_id"],
                allowed_domains=ws["allowed_domains"],
            )
        elif not browse_result["success"]:
            logger.warning("executor | browse failed: %s", browse_result["error"])

    # ── Step 2: synthesise with LLM ───────────────────────────────
    if browse_result and browse_result["success"]:
        human_content = (
            f"Goal: {state['goal']}\n\n"
            f"Subtask ID: {subtask['id']}\n"
            f"Subtask: {subtask['description']}\n\n"
            f"Page content retrieved from {browse_result['url']}:\n"
            f"{browse_result['content']}\n\n"
            f"Previous results: {json.dumps(state.get('executor_results', []))}"
        )
        system = EXECUTOR_SYNTHESIS_SYSTEM
        notes_fallback = browse_result["url"]
    else:
        human_content = (
            f"Goal: {state['goal']}\n\n"
            f"Subtask ID: {subtask['id']}\n"
            f"Subtask: {subtask['description']}\n\n"
            + (f"Note: Browser failed — {browse_result['error']}\n\n" if browse_result else "")
            + f"Previous results: {json.dumps(state.get('executor_results', []))}"
        )
        system = EXECUTOR_LLM_ONLY_SYSTEM
        notes_fallback = "LLM only"

    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=human_content),
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
            "notes": notes_fallback,
        }

    # Ensure subtask_id is always present
    result.setdefault("subtask_id", subtask["id"])
    result.setdefault("notes", notes_fallback)

    # When we have real Playwright content, the subtask is completed
    # regardless of what the LLM chose for status — the browser worked.
    if browse_result and browse_result["success"]:
        result["status"] = "completed"

    # ── Step 3: mark subtask done ─────────────────────────────────
    updated_subtasks = [
        {**s, "status": result.get("status", "completed")}
        if s["id"] == subtask["id"] else s
        for s in state["subtasks"]
    ]

    # Build visible message — include source URL if browsed
    source_note = f" (via {result['notes']})" if result.get("notes") and result["notes"] != "LLM only" else ""
    msg = _msg(
        role="executor",
        content=(
            f"Subtask {subtask['id']}: {result.get('status', 'completed')}{source_note}\n"
            f"{result.get('result', '')[:300]}"
        ),
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )

    logger.info("executor | subtask=%s status=%s browsed=%s",
                subtask["id"], result.get("status"), bool(browse_result and browse_result["success"]))
    await _broadcast(state["workspace_id"], msg)
    return {
        "subtasks": updated_subtasks,
        "executor_results": [result],
        "messages": [msg],
    }


# ── Reviewer Node ─────────────────────────────────────────────────

REVIEWER_SYSTEM = """You are the Reviewer agent in the Recall workspace.
You assess whether the Executor's work meaningfully addresses the original goal.

Respond ONLY with valid JSON:
{
  "decision": "approved" | "rejected",
  "feedback": "concise reasoning under 80 words"
}

Approval rules:
- Approve if the results contain relevant content that addresses the goal,
  even if some subtasks are marked 'failed' in status.
- Approve if a browser tool was used and returned real page content.
- Reject ONLY if the results are completely empty, obviously wrong, or
  contain no relevant information whatsoever.
- Do not reject just because status fields say 'failed' — look at the actual result content.

Do NOT include any text outside the JSON object."""


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
