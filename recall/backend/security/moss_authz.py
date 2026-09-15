"""
security/moss_authz.py — Orchestrator-side authorization for Moss hits.

Nothing retrieved from Moss reaches an agent until it is proven to belong
to the requesting workspace. Document IDs are namespaced as
`{workspace_id}::{local_id}`. Metadata.workspace_id is checked when present.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SCOPE_SEP = "::"


class MossUnauthorized(Exception):
    """Raised when retrieved Moss documents fail workspace isolation checks."""


def scoped_doc_id(workspace_id: str, local_id: str) -> str:
    return f"{workspace_id}{SCOPE_SEP}{local_id}"


def workspace_id_from_doc(doc: dict[str, Any]) -> str | None:
    meta = doc.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("workspace_id"):
        return str(meta["workspace_id"])
    doc_id = str(doc.get("id") or "")
    if SCOPE_SEP in doc_id:
        return doc_id.split(SCOPE_SEP, 1)[0]
    return None


def authorize_moss_hits(
    workspace_id: str,
    docs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Split Moss hits into (allowed, rejected).

    Rejected docs never leave this function toward an agent prompt.
    """
    allowed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for doc in docs:
        owner = workspace_id_from_doc(doc)
        if owner == workspace_id:
            allowed.append(doc)
        else:
            rejected.append(doc)
            logger.warning(
                "moss_authz.rejected | workspace=%s doc_id=%s owner=%s",
                workspace_id,
                doc.get("id"),
                owner,
            )
    return allowed, rejected


def authorize_or_empty(workspace_id: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed, rejected = authorize_moss_hits(workspace_id, docs)
    if rejected:
        logger.warning(
            "moss_authz.stripped | workspace=%s stripped=%d kept=%d",
            workspace_id,
            len(rejected),
            len(allowed),
        )
    return allowed
