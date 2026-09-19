"""Idempotent schema initialization and patches for Recall."""

from __future__ import annotations

import logging

from sqlalchemy import text

from db.database import get_engine

logger = logging.getLogger(__name__)

_INITIAL_SCHEMA_STATEMENTS = [
    'CREATE EXTENSION IF NOT EXISTS "pgcrypto"',
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name            TEXT NOT NULL,
        moss_project_id TEXT,
        moss_project_key TEXT,
        moss_index_name TEXT,
        allowed_domains TEXT[] DEFAULT ARRAY['wikipedia.org','github.com','docs.python.org','nodejs.org'],
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        display_name    TEXT NOT NULL,
        participant_type TEXT NOT NULL CHECK (participant_type IN ('human','agent')),
        agent_role      TEXT CHECK (agent_role IN ('planner','executor','reviewer','escalator')),
        token           TEXT NOT NULL UNIQUE,
        connected_at    TIMESTAMPTZ,
        disconnected_at TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        goal            TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'planning'
                            CHECK (status IN ('planning','executing','reviewing','escalated','completed','failed')),
        langgraph_thread_id TEXT UNIQUE,
        review_attempts INT NOT NULL DEFAULT 0,
        subtasks        JSONB DEFAULT '[]',
        result          JSONB,
        error           TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
        session_id      UUID REFERENCES sessions(id) ON DELETE SET NULL,
        role            TEXT NOT NULL CHECK (role IN ('human','planner','executor','reviewer','system')),
        content         TEXT NOT NULL,
        metadata        JSONB DEFAULT '{}',
        moss_indexed    BOOLEAN NOT NULL DEFAULT FALSE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id    UUID REFERENCES workspaces(id) ON DELETE SET NULL,
        task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
        session_id      UUID REFERENCES sessions(id) ON DELETE SET NULL,
        event_type      TEXT NOT NULL,
        severity        TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warn','error','critical')),
        payload         JSONB DEFAULT '{}',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON tasks(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_messages_workspace ON messages(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_task ON messages(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_moss ON messages(moss_indexed) WHERE moss_indexed = FALSE",
    "CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_logs(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_logs(event_type)",
    """
    CREATE OR REPLACE FUNCTION update_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_workspaces_updated_at ON workspaces",
    """
    CREATE TRIGGER trg_workspaces_updated_at
        BEFORE UPDATE ON workspaces
        FOR EACH ROW EXECUTE FUNCTION update_updated_at()
    """,
    "DROP TRIGGER IF EXISTS trg_tasks_updated_at ON tasks",
    """
    CREATE TRIGGER trg_tasks_updated_at
        BEFORE UPDATE ON tasks
        FOR EACH ROW EXECUTE FUNCTION update_updated_at()
    """,
]

_PATCH_STATEMENTS = [
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS moss_project_id TEXT",
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS moss_project_key TEXT",
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS moss_index_name TEXT",
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS allowed_domains TEXT[] DEFAULT ARRAY['wikipedia.org','github.com','docs.python.org','nodejs.org']",
    "ALTER TABLE workspaces ALTER COLUMN allowed_domains SET DEFAULT ARRAY['wikipedia.org','github.com','docs.python.org','nodejs.org']",
    "UPDATE workspaces SET allowed_domains = array_append(allowed_domains, 'nodejs.org') WHERE allowed_domains IS NOT NULL AND NOT ('nodejs.org' = ANY(allowed_domains))",
]


async def apply_schema_patches() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        for stmt in _INITIAL_SCHEMA_STATEMENTS:
            await conn.execute(text(stmt))
        for stmt in _PATCH_STATEMENTS:
            await conn.execute(text(stmt))
    logger.info("schema.initialized | all tables and patches applied")
