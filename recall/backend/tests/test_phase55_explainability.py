"""Phase 5.5: durable task activity and explainability response shaping."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from routers.tasks import _message_response


WORKSPACE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TASK_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MESSAGE_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
CREATED_AT = datetime(2026, 9, 17, 12, 34, 56, tzinfo=timezone.utc)


def _row(**overrides):
    values = {
        "id": MESSAGE_ID,
        "workspace_id": WORKSPACE_ID,
        "task_id": TASK_ID,
        "role": "planner",
        "content": "I split the goal into two steps.",
        "metadata": {"reasoning": "Two independent sources are required."},
        "created_at": CREATED_AT,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_message_response_rehydrates_reasoning_and_timestamp():
    message = _message_response(_row())

    assert message["id"] == str(MESSAGE_ID)
    assert message["task_id"] == str(TASK_ID)
    assert message["metadata"]["reasoning"] == "Two independent sources are required."
    assert message["reasoning"] == "Two independent sources are required."
    assert message["created_at"] == CREATED_AT.isoformat()
    assert message["timestamp"] == CREATED_AT.isoformat()


def test_message_response_exposes_flagged_metadata_for_existing_ui():
    message = _message_response(_row(metadata={
        "flagged": True,
        "event_type": "domain_blocked",
        "audit_id": "audit-stable-id",
        "hostname": "blocked.example",
    }))

    assert message["flagged"] is True
    assert message["event_type"] == "domain_blocked"
    assert message["audit_id"] == "audit-stable-id"
    assert message["hostname"] == "blocked.example"
    assert message["reasoning"] is None


def test_message_response_keeps_persisted_identity_authoritative():
    message = _message_response(_row(
        task_id=None,
        metadata={"id": "metadata-id", "role": "system"},
        created_at=None,
    ))

    assert message["id"] == str(MESSAGE_ID)
    assert message["role"] == "planner"
    assert message["task_id"] is None
    assert message["created_at"] is None
    assert message["timestamp"] is None
