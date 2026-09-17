"""
routers/security.py — Phase 3 security endpoints.

POST /workspace/{id}/executor/browse  → same Playwright allowlist the Executor uses
GET  /workspace/{id}/audit            → flagged events for the UI
GET  /workspace/{id}                  → workspace isolation metadata (key redacted)
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from agents.tools import browse_url
from db.database import get_session_factory
from db.workspaces import ensure_workspace
from moss_client import get_workspace_moss_client
from security.audit import list_audit
from security.flagged import emit_domain_blocked
from security.moss_authz import scoped_doc_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace", tags=["security"])


class BrowseRequest(BaseModel):
    url: str
    task_id: str | None = None


class ErasureResponse(BaseModel):
    workspace_id: str
    postgres_deleted: dict[str, int]
    moss_deleted: int


async def _workspace_document_ids(workspace_id: str) -> list[str]:
    """Read source-of-truth message IDs before deleting Moss docs by ID."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text("SELECT id FROM messages WHERE workspace_id = CAST(:wid AS uuid)"),
            {"wid": workspace_id},
        )
        return [scoped_doc_id(workspace_id, str(row.id)) for row in result.fetchall()]


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str):
    async with get_session_factory()() as session:
        ws = await ensure_workspace(session, workspace_id)
        await session.commit()
    return {
        "id": ws["id"],
        "name": ws["name"],
        "moss_project_id": ws["moss_project_id"],
        "moss_index_name": ws["moss_index_name"],
        "allowed_domains": ws["allowed_domains"],
        "isolation": "shared_index_metadata_filter",
        "moss_isolated": False,
    }


@router.get("/{workspace_id}/audit")
async def get_audit(workspace_id: str):
    return await list_audit(workspace_id)


@router.delete("/{workspace_id}/data", response_model=ErasureResponse)
async def erase_workspace_data(workspace_id: str):
    """Erase one workspace's Postgres rows and its known Moss documents.

    The SDK deletes Moss documents by ID, so those scoped IDs are collected
    from Postgres first. If Moss deletion fails, Postgres is left untouched.
    """
    document_ids = await _workspace_document_ids(workspace_id)
    moss_deleted = await get_workspace_moss_client().delete_documents(document_ids)

    statements = {
        "audit_logs": "DELETE FROM audit_logs WHERE workspace_id = CAST(:wid AS uuid)",
        "messages": "DELETE FROM messages WHERE workspace_id = CAST(:wid AS uuid)",
        "tasks": "DELETE FROM tasks WHERE workspace_id = CAST(:wid AS uuid)",
        "sessions": "DELETE FROM sessions WHERE workspace_id = CAST(:wid AS uuid)",
        "workspaces": "DELETE FROM workspaces WHERE id = CAST(:wid AS uuid)",
    }
    async with get_session_factory()() as session:
        counts: dict[str, int] = {}
        for name, statement in statements.items():
            result = await session.execute(text(statement), {"wid": workspace_id})
            counts[name] = result.rowcount or 0
        await session.commit()
    logger.warning("workspace.data_erased | workspace=%s moss_docs=%d", workspace_id, moss_deleted)
    return ErasureResponse(workspace_id=workspace_id, postgres_deleted=counts, moss_deleted=moss_deleted)


@router.post("/{workspace_id}/executor/browse")
async def executor_browse(workspace_id: str, body: BrowseRequest):
    """
    Run the Executor Playwright tool against a URL.

    Blocked domains never launch a browser. The attempt is written to
    audit_logs and broadcast as a flagged_event on the workspace WebSocket.
    """
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")

    async with get_session_factory()() as session:
        ws = await ensure_workspace(session, workspace_id)
        await session.commit()

    result = await browse_url(body.url, allowed_domains=ws["allowed_domains"])
    if result.get("blocked"):
        hostname = result.get("hostname") or (urlparse(body.url).hostname or "")
        event = await emit_domain_blocked(
            workspace_id=workspace_id,
            url=body.url,
            hostname=hostname,
            error=result["error"],
            task_id=body.task_id,
            allowed_domains=ws["allowed_domains"],
        )
        return {**result, "flagged": True, "event": event}

    return {**result, "flagged": False}
