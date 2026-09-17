"""Emit flagged security events to audit_logs, messages, and WebSocket rooms."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from db.database import get_session_factory
from realtime import publish_event
from security.audit import write_audit

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def persist_message(
    *,
    workspace_id: str,
    role: str,
    content: str,
    task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> str:
    message_id = message_id or str(uuid.uuid4())
    async with get_session_factory()() as session:
        await session.execute(
            text("""
                INSERT INTO messages (
                    id, workspace_id, task_id, role, content, metadata
                ) VALUES (
                    CAST(:id AS uuid),
                    CAST(:workspace_id AS uuid),
                    CAST(:task_id AS uuid),
                    :role,
                    :content,
                    CAST(:metadata AS jsonb)
                )
            """),
            {
                "id": message_id,
                "workspace_id": workspace_id,
                "task_id": task_id,
                "role": role,
                "content": content,
                "metadata": json.dumps(metadata or {}),
            },
        )
        await session.commit()
    return message_id


async def emit_domain_blocked(
    *,
    workspace_id: str,
    url: str,
    hostname: str,
    error: str,
    task_id: str | None = None,
    allowed_domains: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "url": url,
        "hostname": hostname,
        "error": error,
        "allowed_domains": allowed_domains or [],
    }
    audit_id = await write_audit(
        event_type="domain_blocked",
        severity="warn",
        workspace_id=workspace_id,
        task_id=task_id,
        payload=payload,
    )
    content = (
        f"Blocked navigation to {url}. "
        f"Hostname '{hostname}' is not on this workspace allowlist."
    )
    message_id = await persist_message(
        workspace_id=workspace_id,
        task_id=task_id,
        role="executor",
        content=content,
        metadata={"flagged": True, "event_type": "domain_blocked", "audit_id": audit_id, **payload},
    )
    event = {
        "type": "flagged_event",
        "id": message_id,
        "audit_id": audit_id,
        "event_type": "domain_blocked",
        "role": "executor",
        "flagged": True,
        "content": content,
        "task_id": task_id,
        "workspace_id": workspace_id,
        "url": url,
        "hostname": hostname,
        "created_at": _now(),
        "timestamp": _now(),
    }
    try:
        await publish_event(workspace_id, event)
    except Exception as exc:  # noqa: BLE001
        logger.warning("flagged.broadcast_failed | %s", exc)
    return event
