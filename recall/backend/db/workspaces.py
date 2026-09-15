"""Workspace helpers: create-on-demand with per-workspace Moss isolation."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings

logger = logging.getLogger(__name__)


def _index_name_for(workspace_id: str) -> str:
    compact = workspace_id.replace("-", "")[:12]
    return f"recall-ws-{compact}"


async def ensure_workspace(
    session: AsyncSession,
    workspace_id: str,
    name: str | None = None,
) -> dict[str, Any]:
    cfg = get_settings()
    display = name or f"Workspace {workspace_id[:8]}"
    await session.execute(
        text("""
            INSERT INTO workspaces (
                id, name, moss_project_id, moss_project_key, moss_index_name
            )
            VALUES (
                CAST(:id AS uuid),
                :name,
                :moss_project_id,
                :moss_project_key,
                :moss_index_name
            )
            ON CONFLICT (id) DO NOTHING
        """),
        {
            "id": workspace_id,
            "name": display,
            "moss_project_id": cfg.moss_project_id,
            "moss_project_key": cfg.moss_project_key,
            "moss_index_name": _index_name_for(workspace_id),
        },
    )

    # Backfill isolation fields on workspaces created before Phase 3.
    await session.execute(
        text("""
            UPDATE workspaces SET
                moss_project_id = COALESCE(moss_project_id, :moss_project_id),
                moss_project_key = COALESCE(moss_project_key, :moss_project_key),
                moss_index_name = COALESCE(moss_index_name, :moss_index_name)
            WHERE id = CAST(:id AS uuid)
              AND (moss_project_id IS NULL OR moss_index_name IS NULL)
        """),
        {
            "id": workspace_id,
            "moss_project_id": cfg.moss_project_id,
            "moss_project_key": cfg.moss_project_key,
            "moss_index_name": _index_name_for(workspace_id),
        },
    )

    result = await session.execute(
        text("""
            SELECT id, name, moss_project_id, moss_project_key, moss_index_name, allowed_domains
            FROM workspaces
            WHERE id = CAST(:id AS uuid)
        """),
        {"id": workspace_id},
    )
    row = result.fetchone()
    if not row:
        raise RuntimeError(f"workspace {workspace_id} could not be loaded")

    domains = list(row.allowed_domains or cfg.allowed_domains_list)
    logger.debug(
        "workspace.loaded | id=%s index=%s domains=%s",
        workspace_id,
        row.moss_index_name,
        domains,
    )
    return {
        "id": str(row.id),
        "name": row.name,
        "moss_project_id": row.moss_project_id,
        "moss_project_key": row.moss_project_key,
        "moss_index_name": row.moss_index_name,
        "allowed_domains": domains,
    }
