"""
Batch Postgres → retrieval indexes.

Qdrant is always updated (local, free).
Moss Cloud ingest is opt-in via MOSS_SYNC_ENABLED — default off to protect the $5 cap.
Never call this on every message write.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from config import get_settings
from db.database import get_session_factory
from moss_client import get_moss_client
from retrieval import qdrant_store
from security.moss_authz import scoped_doc_id

logger = logging.getLogger(__name__)


async def sync_pending_messages(limit: int = 20) -> dict[str, Any]:
    cfg = get_settings()
    async with get_session_factory()() as session:
        result = await session.execute(
            text("""
                SELECT id, workspace_id, role, content
                FROM messages
                WHERE moss_indexed = FALSE
                ORDER BY created_at ASC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.fetchall()

    if not rows:
        return {"synced": 0, "moss": False, "qdrant": 0}

    docs = [
        {
            "id": scoped_doc_id(str(r.workspace_id), str(r.id)),
            "text": f"{r.role}: {r.content}"[:2000],
            "metadata": {"workspace_id": str(r.workspace_id), "kind": "message"},
        }
        for r in rows
    ]

    qdrant_store.upsert_docs(docs)
    moss_wrote = False
    if cfg.moss_sync_enabled:
        moss = get_moss_client()
        await moss.add_documents(docs)
        moss_wrote = True
        logger.info("moss.ingest | count=%d reason=batch_sync", len(docs))
    else:
        logger.info("moss.ingest_skipped | count=%d reason=moss_sync_disabled", len(docs))

    ids = [str(r.id) for r in rows]
    async with get_session_factory()() as session:
        for mid in ids:
            await session.execute(
                text("UPDATE messages SET moss_indexed = TRUE WHERE id = CAST(:id AS uuid)"),
                {"id": mid},
            )
        await session.commit()

    return {"synced": len(docs), "moss": moss_wrote, "qdrant": len(docs)}
