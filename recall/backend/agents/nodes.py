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
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import groq
from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from agents.state import RecallState
from agents.llm import get_llm
from agents.tools import browse_url, extract_urls, infer_official_docs_url
from config import get_settings
from db.database import get_session_factory
from db.workspaces import ensure_workspace
from moss_client import get_workspace_moss_client
from otel import get_tracer, llm_span
from realtime import publish_event
from security.flagged import persist_message
from security.flagged import emit_domain_blocked

logger = logging.getLogger(__name__)

MAX_REVIEW_ATTEMPTS = 3


# ── LLM invocation with retry-with-backoff ────────────────────────

def _is_retryable(exc: BaseException) -> bool:
    """True for Groq 429s and any error mentioning rate-limiting."""
    if isinstance(exc, groq.APIStatusError) and exc.status_code == 429:
        return True
    msg = str(exc).lower()
    return "rate_limit" in msg or "too many" in msg


async def _llm_invoke(llm, messages: list, node: str) -> Any:
    """Invoke the LLM with exponential-backoff retry on rate-limit errors.

    3 attempts, starting at 1 s, capped at 8 s.  Only rate-limit signals
    trigger a retry; blocked-domain errors and JSON parse failures happen
    after a successful invoke and are never seen here.

    Each call is wrapped in an OTel span (no-op when OTel is not configured)
    capturing node name, model, total latency, and token counts.
    """
    def _log_retry(retry_state) -> None:
        logger.warning(
            "llm.retry | node=%s attempt=%d error=%s",
            node,
            retry_state.attempt_number,
            retry_state.outcome.exception(),
        )

    model = get_settings().groq_model
    t0 = time.perf_counter()
    response = None
    with llm_span(get_tracer(), node, model) as span:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception(_is_retryable),
            before_sleep=_log_retry,
            reraise=True,
        ):
            with attempt:
                response = await llm.ainvoke(messages)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        usage = getattr(response, "usage_metadata", {}) or {}
        span.set_attribute("llm.latency_ms", latency_ms)
        span.set_attribute("llm.input_tokens", usage.get("input_tokens", 0))
        span.set_attribute("llm.output_tokens", usage.get("output_tokens", 0))
        logger.info(
            "llm.invoke | node=%s latency_ms=%.2f in=%d out=%d",
            node, latency_ms,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )
    return response

# Keep this flexible: questions asking what was discussed, chat recap, or session summary take the recall route.
_RECALL_REQUEST = re.compile(
    r"\b("
    r"what\s+(?:did\s+we\s+|have\s+we\s+|we\s+)?(?:discuss(?:ed)?|talk(?:ed)?\s+about)"
    r"|(?:what\s+(?:things\s+)?(?:were\s+|did\s+we\s+|we\s+)?discussed)"
    r"|(?:in\s+this\s+(?:chat|session|conversation|workspace)\s+what\s+.*(?:discuss|talk))"
    r"|(?:show|give|tell\s+me|provide|what\s+is)\s+(?:the\s+)?(?:chat\s+|session\s+|workspace\s+|conversation\s+)?"
    r"(?:context|recap|summary|history)"
    r"|(?:context|recap|summary|history)\s+(?:of|for)\s+(?:this|the)\s+(?:chat|session|workspace|conversation)"
    r"|what\s+happened\s+so\s+far|bring\s+me\s+up\s+to\s+speed"
    r"|what\s+was\s+(?:discussed|said|mentioned)"
    r"|earlier\s+discussion"
    r")\b",
    re.IGNORECASE,
)


async def _broadcast(workspace_id: str, msg: dict) -> None:
    """Persist a concise decision rationale, then broadcast the activity event."""
    try:
        await persist_message(
            workspace_id=workspace_id,
            task_id=msg.get("task_id"),
            role=msg.get("role", "system"),
            content=msg["content"],
            message_id=msg["id"],
            metadata={"reasoning": msg.get("reasoning", "")},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("message.persist_failed | %s", exc)
    try:
        await publish_event(workspace_id, {"type": "agent_message", **msg})
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
        "reasoning": "",
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


async def classify_request_node(state: RecallState) -> dict:
    """Route explicit workspace-memory questions away from task planning.

    This local heuristic is intentionally free and deterministic. It avoids an
    extra LLM call for every task while keeping subject-matter summaries on the
    normal Planner → Executor → Reviewer path.
    """
    request_type = "recall" if _RECALL_REQUEST.search(state["goal"].strip()) else "task"
    logger.info("classify | task=%s request_type=%s", state["task_id"], request_type)
    return {"request_type": request_type}


RECALL_SYSTEM = """You answer questions about the current Recall workspace.
Use only the retrieved workspace memory below. Give a direct, concise answer.
If the memory does not contain enough information, say that clearly; do not
invent events or claims."""


async def recall_node(state: RecallState) -> dict:
    """Answer a workspace-context question with exactly one Moss query."""
    logger.info("recall | task=%s", state["task_id"])
    context = "No matching workspace memory was retrieved."
    try:
        ws = await _workspace(state["workspace_id"])
        moss = get_workspace_moss_client(
            ws["moss_project_id"], ws["moss_project_key"], ws["moss_index_name"],
        )
        hits, latency_ms = await moss.query_authorized(
            state["workspace_id"], state["goal"], top_k=5, reason="recall_retrieval",
        )
        if hits:
            context = "\n".join(f"- {hit.get('text', '')[:1000]}" for hit in hits)
        else:
            # Fallback to durable Postgres messages in this workspace
            try:
                from sqlalchemy import text
                async with get_session_factory()() as session:
                    res = await session.execute(
                        text("""
                            SELECT role, content FROM messages
                            WHERE workspace_id = CAST(:wid AS uuid)
                            AND role IN ('human', 'executor', 'system')
                            ORDER BY created_at DESC LIMIT 20
                        """),
                        {"wid": state["workspace_id"]},
                    )
                    rows = res.fetchall()
                    if rows:
                        context = "\n".join(f"- {r.role}: {r.content[:500]}" for r in reversed(rows))
            except Exception as e:
                logger.warning("recall.postgres_fallback_failed | %s", e)
        logger.info("recall | moss_hits=%d latency_ms=%.1f", len(hits), latency_ms)
    except Exception as exc:  # noqa: BLE001
        # A retrieval outage should still result in a completed, transparent
        # answer rather than sending a context question through task review.
        logger.warning("recall.moss_context_failed | %s", exc)

    llm = get_llm()
    response = await _llm_invoke(llm, [
        SystemMessage(content=RECALL_SYSTEM),
        HumanMessage(content=f"Question: {state['goal']}\n\nWorkspace memory:\n{context}"),
    ], "recall")
    answer = response.content.strip()
    msg = _msg(
        role="system", content=f"✓ Context recalled.\n{answer}",
        task_id=state["task_id"], workspace_id=state["workspace_id"],
    )
    msg["reasoning"] = "Classified the request as workspace recall and answered only from authorized retrieved context."
    await _broadcast(state["workspace_id"], msg)
    return {
        "review_status": "approved",
        "final_result": answer,
        "messages": [msg],
    }


async def planner_node(state: RecallState) -> dict:
    logger.info("planner | task=%s goal=%r", state["task_id"], state["goal"][:60])
    llm = get_llm()
    moss_context = await _moss_context(state["workspace_id"], state["goal"])

    human = f"Goal: {state['goal']}"
    if moss_context:
        human = f"{human}\n\n{moss_context}"

    response = await _llm_invoke(llm, [
        SystemMessage(content=PLANNER_SYSTEM),
        HumanMessage(content=human),
    ], "planner")

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

    if not isinstance(subtasks, list):
        logger.warning(
            "planner | parse returned non-list type=%s, using fallback subtask",
            type(subtasks).__name__,
        )
        subtasks = [{"id": "1", "description": state["goal"], "status": "pending"}]
    elif len(subtasks) > 5:
        logger.warning("planner | subtask cap: truncating %d subtasks to 5", len(subtasks))
        subtasks = subtasks[:5]

    msg = _msg(
        role="planner",
        content=f"Planned {len(subtasks)} subtasks:\n" +
                "\n".join(f"  {s['id']}. {s['description']}" for s in subtasks),
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )
    msg["reasoning"] = f"Decomposed the actionable goal into {len(subtasks)} concrete subtask(s)."

    logger.info("planner | subtasks=%d", len(subtasks))
    await _broadcast(state["workspace_id"], msg)
    return {
        "subtasks": subtasks,
        "review_attempts": 0,
        "review_status": "",
        "review_feedback": "Planner returned no actionable subtasks." if not subtasks else "",
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

    # ── Step 1: detect an explicit URL or a known official-docs request ──
    request_text = subtask["description"] + " " + state.get("goal", "")
    urls = extract_urls(request_text)
    if not urls:
        official_url = infer_official_docs_url(request_text)
        if official_url:
            urls = [official_url]
            logger.info("executor | resolved official docs request | url=%s", official_url)
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

    response = await _llm_invoke(llm, [
        SystemMessage(content=system),
        HumanMessage(content=human_content),
    ], "executor")

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
    msg["reasoning"] = (
        f"Completed subtask {subtask['id']} using "
        f"{'an allowlisted browser source' if browse_result and browse_result['success'] else 'the configured LLM path'}."
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

    response = await _llm_invoke(llm, [
        SystemMessage(content=REVIEWER_SYSTEM),
        HumanMessage(content=(
            f"Original goal: {state['goal']}\n\n"
            f"Completed subtasks: {json.dumps(all_completed)}\n\n"
            f"Results: {json.dumps(state.get('executor_results', []))}\n\n"
            f"Remaining pending: {len(all_pending)}"
        )),
    ], "reviewer")

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
    msg["reasoning"] = feedback or "Reviewer found the result sufficient for the original goal."

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
    attempts = state.get("review_attempts", 0)
    if attempts == 0 and not state.get("subtasks"):
        content = "⚠ Task escalated: Planner returned no actionable subtasks.\nHuman review required."
    else:
        content = (
            f"⚠ Task escalated after {attempts} failed review passes.\n"
            f"Last feedback: {state.get('review_feedback', 'N/A')}\n"
            "Human review required."
        )
    msg = _msg(
        role="system",
        content=content,
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )
    msg["reasoning"] = (
        "The Planner produced no actionable subtasks."
        if attempts == 0 and not state.get("subtasks")
        else f"Reviewer rejected the task {attempts} time(s): {state.get('review_feedback', 'No feedback provided.')}"
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
    response = await _llm_invoke(llm, [
        SystemMessage(content="Summarise the completed work in 2-3 sentences for the user."),
        HumanMessage(content=(
            f"Goal: {state['goal']}\n"
            f"Results: {json.dumps(state.get('executor_results', []))}"
        )),
    ], "finalise")
    summary = response.content.strip()
    msg = _msg(
        role="system",
        content=f"✓ Task completed.\n{summary}",
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
    )
    msg["reasoning"] = "Reviewer approved the completed subtask results; this is the final concise synthesis."
    logger.info("finalise | task=%s", state["task_id"])
    await _broadcast(state["workspace_id"], msg)
    return {
        "final_result": summary,
        "messages": [msg],
    }
