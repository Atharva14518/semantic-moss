"""
ws/manager.py — WebSocket connection manager for Recall.

Manages per-workspace rooms: any message broadcast to a workspace_id
is delivered to all currently-connected WebSocket clients in that room.

Usage (in a FastAPI endpoint):
    @app.websocket("/ws/{workspace_id}")
    async def ws_endpoint(websocket: WebSocket, workspace_id: str):
        await manager.connect(workspace_id, websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await manager.broadcast(workspace_id, data)
        except WebSocketDisconnect:
            manager.disconnect(workspace_id, websocket)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Thread-safe WebSocket connection manager keyed by workspace_id."""

    def __init__(self) -> None:
        # workspace_id -> set of connected WebSockets
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, workspace_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._rooms[workspace_id].add(websocket)
        client = websocket.client
        logger.info(
            "ws.connect | workspace=%s client=%s total=%d",
            workspace_id,
            f"{client.host}:{client.port}" if client else "unknown",
            len(self._rooms[workspace_id]),
        )

    def disconnect(self, workspace_id: str, websocket: WebSocket) -> None:
        self._rooms[workspace_id].discard(websocket)
        if not self._rooms[workspace_id]:
            del self._rooms[workspace_id]
        logger.info(
            "ws.disconnect | workspace=%s remaining=%d",
            workspace_id,
            len(self._rooms.get(workspace_id, set())),
        )

    async def broadcast(self, workspace_id: str, payload: dict[str, Any]) -> None:
        """Broadcast a JSON payload to all clients in a workspace room."""
        text = json.dumps(payload)
        sockets = list(self._rooms.get(workspace_id, set()))
        if not sockets:
            return
        results = await asyncio.gather(
            *[ws.send_text(text) for ws in sockets],
            return_exceptions=True,
        )
        # Silently drop dead connections
        for ws, result in zip(sockets, results):
            if isinstance(result, Exception):
                logger.warning("ws.broadcast | stale connection pruned workspace=%s", workspace_id)
                self.disconnect(workspace_id, ws)

    def room_size(self, workspace_id: str) -> int:
        return len(self._rooms.get(workspace_id, set()))

    def all_workspaces(self) -> list[str]:
        return list(self._rooms.keys())


# Singleton — import this everywhere
manager = ConnectionManager()
