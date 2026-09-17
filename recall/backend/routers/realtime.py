"""LiveKit token issuance for the Recall workspace data channel."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from realtime import mint_token, room_name

router = APIRouter(prefix="/v1", tags=["realtime"])


class LiveKitTokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str
    expires_in_seconds: int = 900


@router.get("/workspace/{workspace_id}/token", response_model=LiveKitTokenResponse)
async def workspace_token(
    workspace_id: str,
    client_id: str | None = Query(default=None),
    display_name: str | None = Query(default=None),
):
    """Return a short-lived, room-scoped token after the API auth boundary.

    The MVP has no user-account system yet, so client identity is ephemeral.
    Replace this identity derivation with the authenticated session subject when
    account auth is enabled; room scope remains unchanged.
    """
    identity = client_id or f"human-{uuid.uuid4().hex[:12]}"
    try:
        token = mint_token(workspace_id, identity, display_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    from config import get_settings
    return LiveKitTokenResponse(
        token=token,
        url=get_settings().livekit_url,
        room=room_name(workspace_id),
        identity=identity,
    )
