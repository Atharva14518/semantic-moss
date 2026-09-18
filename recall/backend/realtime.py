"""LiveKit-only realtime events for Recall workspaces."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from livekit import api
from livekit.protocol import models, room

from config import get_settings

logger = logging.getLogger(__name__)


def room_name(workspace_id: str) -> str:
    return f"workspace-{workspace_id}"


def _credentials_configured() -> bool:
    cfg = get_settings()
    return bool(cfg.livekit_url and cfg.livekit_api_key and cfg.livekit_api_secret)


def mint_token(workspace_id: str, identity: str, name: str | None = None) -> str:
    """Mint a short-lived token scoped to exactly one workspace room."""
    if not _credentials_configured():
        raise RuntimeError("LiveKit is not configured; set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET")
    cfg = get_settings()
    token = api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
    token.with_identity(identity).with_name(name or identity).with_ttl(timedelta(minutes=15))
    token.with_grants(api.VideoGrants(room_join=True, room=room_name(workspace_id)))
    return token.to_jwt()


def event_envelope(workspace_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy agent events into the versioned LiveKit payload."""
    return {
        "event_id": event["id"],
        "event_version": "1.0",
        "workspace_id": workspace_id,
        "task_id": event.get("task_id"),
        "type": event.get("type", "agent_message").upper(),
        "actor": event.get("role", "system"),
        "payload": event,
        "timestamp": event.get("created_at") or event.get("timestamp"),
    }


async def publish_event(workspace_id: str, event: dict[str, Any]) -> None:
    """Publish one reliable, idempotent event to a LiveKit workspace room."""
    if not _credentials_configured():
        logger.warning("livekit.not_configured | event=%s", event.get("id"))
        return
    cfg = get_settings()
    payload = json.dumps(event_envelope(workspace_id, event)).encode("utf-8")
    lk = api.LiveKitAPI(cfg.livekit_url, cfg.livekit_api_key, cfg.livekit_api_secret)
    try:
        await lk.room.send_data(
            room.SendDataRequest(
                room=room_name(workspace_id),
                data=payload,
                kind=models.DataPacket.RELIABLE,
            )
        )
    except Exception as exc:
        logger.warning(
            "livekit.publish_failed | room=%s event=%s error=%s",
            room_name(workspace_id),
            event.get("id"),
            exc,
        )
    finally:
        await lk.aclose()
