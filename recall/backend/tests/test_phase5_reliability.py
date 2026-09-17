"""
Phase 5 reliability tests — offline only (no live services).

Covers:
  1. _llm_invoke retries on a rate-limit error (twice) and succeeds on attempt 3.
  2. _llm_invoke raises after 3 exhausted attempts.
  3. planner_node truncates a 7-element subtask list to 5.
  4. route_after_classification and route_after_planner are pure functions whose
     results depend only on state content, not on workspace identity.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import groq
import httpx
import pytest

from agents.nodes import _llm_invoke, planner_node
from agents.graph import route_after_classification, route_after_planner


# Minimal settings stub so tests never need real env vars.
_FAKE_SETTINGS = SimpleNamespace(groq_model="test-model", groq_max_tokens=512)


def _patch_settings():
    """Context manager: patches agents.nodes.get_settings and otel.get_settings."""
    return patch("agents.nodes.get_settings", return_value=_FAKE_SETTINGS)


# ── helpers ────────────────────────────────────────────────────────


def _make_429() -> groq.APIStatusError:
    """Build a groq 429 status error without a real httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 429
    resp.headers = {}
    return groq.APIStatusError("rate limit exceeded", response=resp, body=None)


# ── 1. _llm_invoke retries twice then succeeds ─────────────────────


async def test_llm_invoke_retries_on_rate_limit_then_succeeds():
    """Mock LLM raises 429 on attempts 1 and 2; succeeds on attempt 3."""
    success = MagicMock()
    success.content = "answer"

    call_count = 0

    async def flaky_ainvoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise _make_429()
        return success

    mock_llm = MagicMock()
    mock_llm.ainvoke = flaky_ainvoke

    with _patch_settings(), patch("asyncio.sleep", new=AsyncMock(return_value=None)):
        result = await _llm_invoke(mock_llm, [], "test_node")

    assert result is success
    assert call_count == 3


# ── 2. _llm_invoke exhausts 3 attempts and re-raises ──────────────


async def test_llm_invoke_raises_after_3_exhausted_attempts():
    """Mock LLM always raises 429; _llm_invoke must raise after 3 attempts."""
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=_make_429())

    with _patch_settings(), patch("asyncio.sleep", new=AsyncMock(return_value=None)):
        with pytest.raises(groq.APIStatusError):
            await _llm_invoke(mock_llm, [], "test_node")

    assert mock_llm.ainvoke.call_count == 3


# ── 3. planner_node truncates >5 subtasks ─────────────────────────


async def test_planner_truncates_subtask_list_to_5(monkeypatch):
    """planner_node must truncate a 7-element LLM response to exactly 5 subtasks."""
    seven_subtasks = [
        {"id": str(i), "description": f"Subtask {i}", "status": "pending"}
        for i in range(1, 8)
    ]

    mock_response = MagicMock()
    mock_response.content = json.dumps(seven_subtasks)

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    monkeypatch.setattr("agents.nodes.get_llm", lambda: mock_llm)
    monkeypatch.setattr("agents.nodes.get_settings", lambda: _FAKE_SETTINGS)
    monkeypatch.setattr("agents.nodes._moss_context", AsyncMock(return_value=""))
    monkeypatch.setattr("agents.nodes._broadcast", AsyncMock())

    state = {
        "task_id": "task-trunc",
        "workspace_id": "ws-trunc",
        "goal": "Do seven things",
    }

    result = await planner_node(state)

    assert len(result["subtasks"]) == 5
    assert result["subtasks"] == seven_subtasks[:5]


# ── 4. Routing functions are pure — no workspace state leaks ───────


def test_routing_functions_are_pure_across_workspace_ids():
    """
    route_after_classification and route_after_planner depend only on the
    logical content of state, not on workspace_id.  Two different workspace
    IDs with identical logical content must produce identical routes, and
    two workspaces with different logical content must produce independent
    (non-leaking) results.
    """
    ws_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ws_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    # --- route_after_classification ---

    # Same request_type → same route regardless of workspace_id
    assert (
        route_after_classification({"request_type": "task", "workspace_id": ws_a})
        == route_after_classification({"request_type": "task", "workspace_id": ws_b})
        == "planner"
    )
    assert (
        route_after_classification({"request_type": "recall", "workspace_id": ws_a})
        == route_after_classification({"request_type": "recall", "workspace_id": ws_b})
        == "recall"
    )

    # Different workspaces, different content → independent results (no leakage)
    result_classify_a = route_after_classification(
        {"request_type": "task", "workspace_id": ws_a}
    )
    result_classify_b = route_after_classification(
        {"request_type": "recall", "workspace_id": ws_b}
    )
    assert result_classify_a == "planner"
    assert result_classify_b == "recall"
    # Call again with ws_a — ws_b's previous result must not have changed anything
    assert (
        route_after_classification({"request_type": "task", "workspace_id": ws_a})
        == result_classify_a
    )

    # --- route_after_planner ---

    # Same subtasks content → same route regardless of workspace_id
    pending = [{"id": "1", "status": "pending"}]
    assert (
        route_after_planner({"subtasks": pending, "workspace_id": ws_a})
        == route_after_planner({"subtasks": pending, "workspace_id": ws_b})
        == "executor"
    )
    assert (
        route_after_planner({"subtasks": [], "workspace_id": ws_a})
        == route_after_planner({"subtasks": [], "workspace_id": ws_b})
        == "escalate"
    )

    # Independent results for different workspaces with different state
    result_plan_a = route_after_planner({"subtasks": pending, "workspace_id": ws_a})
    result_plan_b = route_after_planner({"subtasks": [], "workspace_id": ws_b})
    assert result_plan_a == "executor"
    assert result_plan_b == "escalate"
    # Re-check ws_a after evaluating ws_b — must be unchanged
    assert route_after_planner({"subtasks": pending, "workspace_id": ws_a}) == result_plan_a
