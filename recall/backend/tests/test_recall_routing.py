"""Regression tests for the pre-planning recall route (no live services)."""

from agents.graph import route_after_classification, route_after_planner
from agents.nodes import classify_request_node


async def test_context_question_routes_to_recall():
    update = await classify_request_node({
        "task_id": "task-1",
        "goal": "Tell me context of this chat",
    })
    assert update == {"request_type": "recall"}
    assert route_after_classification(update) == "recall"


async def test_subject_summary_stays_on_task_path():
    update = await classify_request_node({
        "task_id": "task-2",
        "goal": "Summarize the top 3 benefits of LangGraph",
    })
    assert update == {"request_type": "task"}
    assert route_after_classification(update) == "planner"


def test_empty_plan_escalates_without_reviewer():
    assert route_after_planner({"subtasks": []}) == "escalate"
    assert route_after_planner({"subtasks": [{"id": "1", "status": "pending"}]}) == "executor"
