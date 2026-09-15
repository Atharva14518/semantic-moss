"""
routers/tasks.py — Task management API endpoints.

POST /workspace/{workspace_id}/task       → start a LangGraph task run
GET  /workspace/{workspace_id}/task/{id}  → read persisted task state
GET  /workspace/{workspace_id}/tasks      → list all tasks in workspace
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy import text

from agents.state import RecallState
from db.database import get_session_factory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace", tags=["tasks"])


# ── Request / Response schemas ────────────────────────────────────

class CreateTaskRequest(BaseModel):
    goal: str
    display_name: str = "API User"


class TaskResponse(BaseModel):
    task_id: str
    workspace_id: str
    status: str
    goal: str
    langgraph_thread_id: str | None = None
    subtasks: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    final_result: str | None = None
    error: str | None = None


# ── Background runner ─────────────────────────────────────────────

async def _run_graph(
    workspace_id: str,
    task_id: str,
    thread_id: str,
    goal: str,
    graph,  # compiled LangGraph — passed from app.state
) -> None:
    """Run the LangGraph graph to completion in the background."""
    if graph is None:
        logger.error("_run_graph | graph not initialised (checkpointer failed?)")
        return

    try:
        initial_state: RecallState = {
            "workspace_id": workspace_id,
            "task_id": task_id,
            "goal": goal,
            "subtasks": [],
            "executor_results": [],
            "review_status": "",
            "review_feedback": "",
            "review_attempts": 0,
            "messages": [],
            "final_result": None,
            "error": None,
        }

        config = {"configurable": {"thread_id": thread_id}}

        logger.info("graph.run | task=%s thread=%s", task_id, thread_id)
        final_state = await graph.ainvoke(initial_state, config=config)

        # Persist final state to our tasks table
        status = "completed"
        if final_state.get("review_status") == "escalated":
            status = "escalated"
        elif final_state.get("error"):
            status = "failed"

        subtasks_json = json.dumps(final_state.get("subtasks", []))
        summary = (final_state.get("final_result") or "").replace("\n", " ")[:500]
        result_json = json.dumps({"summary": summary})

        async with get_session_factory()() as session:
            await session.execute(
                text("""
                    UPDATE tasks SET
                        status = :status,
                        subtasks = CAST(:subtasks AS jsonb),
                        result = CAST(:result AS jsonb),
                        error = :error,
                        updated_at = NOW()
                    WHERE id = CAST(:task_id AS uuid)
                """),
                {
                    "status": status,
                    "subtasks": subtasks_json,
                    "result": result_json,
                    "error": final_state.get("error"),
                    "task_id": task_id,
                },
            )
            await session.commit()
        logger.info("graph.complete | task=%s status=%s", task_id, status)

    except Exception as exc:
        logger.error("graph.error | task=%s error=%s", task_id, exc, exc_info=True)
        async with get_session_factory()() as session:
            await session.execute(
                text("UPDATE tasks SET status='failed', error=:e, updated_at=NOW() WHERE id=CAST(:id AS uuid)"),
                {"e": str(exc), "id": task_id},
            )
            await session.commit()


# ── Endpoints ─────────────────────────────────────────────────────

@router.post("/{workspace_id}/task", response_model=TaskResponse)
async def create_task(
    workspace_id: str,
    body: CreateTaskRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """
    Create a new task in the workspace and immediately start the
    Planner→Executor→Reviewer graph in the background.
    Returns immediately with the task_id — poll GET /task/{id} for state.
    """
    task_id = str(uuid.uuid4())
    thread_id = f"recall-{task_id}"
    graph = getattr(request.app.state, "graph", None)

    async with get_session_factory()() as session:
        # Ensure workspace exists (create on-the-fly for Phase 1)
        await session.execute(
            text("""
                INSERT INTO workspaces (id, name)
                VALUES (CAST(:id AS uuid), :name)
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": workspace_id, "name": f"Workspace {workspace_id[:8]}"},
        )
        # Create task row
        await session.execute(
            text("""
                INSERT INTO tasks (id, workspace_id, goal, status, langgraph_thread_id)
                VALUES (CAST(:id AS uuid), CAST(:wid AS uuid), :goal, 'planning', :thread_id)
            """),
            {
                "id": task_id,
                "wid": workspace_id,
                "goal": body.goal,
                "thread_id": thread_id,
            },
        )
        await session.commit()

    # Start graph in background — returns immediately
    background_tasks.add_task(_run_graph, workspace_id, task_id, thread_id, body.goal, graph)

    logger.info("task.created | workspace=%s task=%s", workspace_id, task_id)
    return TaskResponse(
        task_id=task_id,
        workspace_id=workspace_id,
        status="planning",
        goal=body.goal,
        langgraph_thread_id=thread_id,
    )


@router.get("/{workspace_id}/task/{task_id}", response_model=TaskResponse)
async def get_task(workspace_id: str, task_id: str):
    """Get current persisted state of a task. Poll this to track progress."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text("""
                SELECT id, workspace_id, goal, status, langgraph_thread_id,
                       subtasks, result, error
                FROM tasks
                WHERE id = CAST(:id AS uuid) AND workspace_id = CAST(:wid AS uuid)
            """),
            {"id": task_id, "wid": workspace_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        task_id=str(row.id),
        workspace_id=str(row.workspace_id),
        status=row.status,
        goal=row.goal,
        langgraph_thread_id=row.langgraph_thread_id,
        subtasks=row.subtasks or [],
        final_result=row.result.get("summary") if row.result else None,
        error=row.error,
    )


@router.get("/{workspace_id}/tasks")
async def list_tasks(workspace_id: str):
    """List all tasks in a workspace."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text("""
                SELECT id, goal, status, created_at, updated_at
                FROM tasks
                WHERE workspace_id = CAST(:wid AS uuid)
                ORDER BY created_at DESC
                LIMIT 50
            """),
            {"wid": workspace_id},
        )
        rows = result.fetchall()

    return [
        {
            "task_id": str(r.id),
            "goal": r.goal,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]
