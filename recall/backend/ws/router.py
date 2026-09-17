"""
ws/router.py — FastAPI WebSocket endpoint for real-time workspace sync.

Clients connect via:  ws://localhost:8100/ws/{workspace_id}?client_id=...

Protocol (JSON messages both directions):
  Client → Server:
    { "type": "ping" }
    { "type": "human_message", "content": "...", "display_name": "Alice" }

  Server → Client (broadcast to all in workspace):
    { "type": "pong" }
    { "type": "agent_message", "role": "planner", "content": "...", ... }
    { "type": "human_message", "display_name": "Alice", "content": "...", ... }
    { "type": "presence", "workspace_id": "...", "clients": 3 }
    { "type": "error", "detail": "..." }
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from ws.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.websocket("/ws/{workspace_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    workspace_id: str,
    client_id: str = Query(default=None),
):
    if not client_id:
        client_id = str(uuid.uuid4())[:8]

    await manager.connect(workspace_id, websocket)

    # Announce new client to the room
    await manager.broadcast(workspace_id, {
        "type": "presence",
        "workspace_id": workspace_id,
        "clients": manager.room_size(workspace_id),
        "event": "join",
        "client_id": client_id,
        "timestamp": _now(),
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "detail": "Invalid JSON"}))
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "timestamp": _now()}))

            elif msg_type == "human_message":
                # Broadcast human message to everyone in the room (including sender)
                await manager.broadcast(workspace_id, {
                    "type": "human_message",
                    # Preserve a client-generated ID so the sender can merge
                    # its optimistic row with this room broadcast.
                    "id": msg.get("id") or str(uuid.uuid4()),
                    "workspace_id": workspace_id,
                    "client_id": client_id,
                    "display_name": msg.get("display_name", "Human"),
                    "content": msg.get("content", ""),
                    "timestamp": _now(),
                })

            else:
                logger.debug("ws.unknown_type | type=%s client=%s", msg_type, client_id)

    except WebSocketDisconnect:
        manager.disconnect(workspace_id, websocket)
        await manager.broadcast(workspace_id, {
            "type": "presence",
            "workspace_id": workspace_id,
            "clients": manager.room_size(workspace_id),
            "event": "leave",
            "client_id": client_id,
            "timestamp": _now(),
        })
        logger.info("ws.disconnect | workspace=%s client=%s", workspace_id, client_id)
