"""Persist security and orchestration events to audit_logs."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text

from db.database import get_session_factory

logger = logging.getLogger(__name__)


async def write_audit(
    *,
    event_type: str,
    severity: str = "warn",
    workspace_id: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    audit_id = str(uuid.uuid4())
    async with get_session_factory()() as session:
        await session.execute(
            text("""
                INSERT INTO audit_logs (
                    id, workspace_id, task_id, session_id, event_type, severity, payload
                ) VALUES (
                    CAST(:id AS uuid),
                    CAST(:workspace_id AS uuid),
                    CAST(:task_id AS uuid),
                    CAST(:session_id AS uuid),
                    :event_type,
                    :severity,
                    CAST(:payload AS jsonb)
                )
            """),
            {
                "id": audit_id,
                "workspace_id": workspace_id,
                "task_id": task_id,
                "session_id": session_id,
                "event_type": event_type,
                "severity": severity,
                "payload": json.dumps(payload or {}),
            },
        )
        await session.commit()
    logger.warning(
        "audit.write | event=%s severity=%s workspace=%s task=%s",
        event_type,
        severity,
        workspace_id,
        task_id,
    )
    return audit_id


async def list_audit(workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        result = await session.execute(
            text("""
                SELECT id, event_type, severity, payload, created_at, task_id
                FROM audit_logs
                WHERE workspace_id = CAST(:wid AS uuid)
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"wid": workspace_id, "limit": limit},
        )
        rows = result.fetchall()
    return [
        {
            "id": str(r.id),
            "event_type": r.event_type,
            "severity": r.severity,
            "payload": r.payload or {},
            "task_id": str(r.task_id) if r.task_id else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
