"""Idempotent schema patches for databases that predate newer columns."""

from __future__ import annotations

import logging

from sqlalchemy import text

from db.database import get_engine

logger = logging.getLogger(__name__)

_STATEMENTS = [
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS moss_project_id TEXT",
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS moss_project_key TEXT",
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS moss_index_name TEXT",
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS allowed_domains TEXT[] DEFAULT ARRAY['wikipedia.org','github.com','docs.python.org']",
]


async def apply_schema_patches() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        for stmt in _STATEMENTS:
            await conn.execute(text(stmt))
    logger.info("schema.patches_applied | count=%d", len(_STATEMENTS))
