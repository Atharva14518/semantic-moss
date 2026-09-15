"""Local Qdrant cold store. Free to query and ingest as often as needed."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import Distance, PointStruct, VectorParams

from config import get_settings

logger = logging.getLogger(__name__)

DIM = 128
_client: QdrantClient | None = None


def _embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token in text.lower().split():
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


def get_qdrant() -> QdrantClient:
    global _client
    if _client is None:
        cfg = get_settings()
        _client = QdrantClient(url=cfg.qdrant_url, timeout=10)
    return _client


def ensure_collection() -> None:
    cfg = get_settings()
    client = get_qdrant()
    try:
        client.get_collection(cfg.qdrant_collection)
    except (UnexpectedResponse, Exception):
        names = [c.name for c in client.get_collections().collections]
        if cfg.qdrant_collection not in names:
            client.create_collection(
                collection_name=cfg.qdrant_collection,
                vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
            )
            logger.info("qdrant.collection_created | name=%s", cfg.qdrant_collection)


def upsert_docs(documents: list[dict[str, Any]]) -> None:
    """documents: id, text, optional metadata.workspace_id"""
    ensure_collection()
    cfg = get_settings()
    points = []
    import hashlib

    for d in documents:
        meta = dict(d.get("metadata") or {})
        meta["text"] = d["text"]
        pid = int(hashlib.md5(d["id"].encode()).hexdigest()[:16], 16) % (2**63)
        points.append(
            PointStruct(
                id=pid,
                vector=_embed(d["text"]),
                payload={"id": d["id"], **meta},
            )
        )
    get_qdrant().upsert(collection_name=cfg.qdrant_collection, points=points)


def query(text: str, top_k: int = 5, workspace_id: str | None = None) -> tuple[list[dict[str, Any]], float]:
    ensure_collection()
    cfg = get_settings()
    t0 = time.perf_counter()
    query_filter = None
    if workspace_id:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_filter = Filter(
            must=[FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id))]
        )
    client = get_qdrant()
    try:
        hits = client.search(
            collection_name=cfg.qdrant_collection,
            query_vector=_embed(text),
            limit=top_k,
            query_filter=query_filter,
        )
    except Exception:
        res = client.query_points(
            collection_name=cfg.qdrant_collection,
            query=_embed(text),
            limit=top_k,
            query_filter=query_filter,
        )
        hits = res.points
    latency_ms = (time.perf_counter() - t0) * 1000
    docs = [
        {
            "id": (h.payload or {}).get("id"),
            "text": (h.payload or {}).get("text"),
            "score": h.score,
            "metadata": {k: v for k, v in (h.payload or {}).items() if k not in ("text",)},
        }
        for h in hits
    ]
    logger.info("qdrant.query | hits=%d latency=%.2fms", len(docs), latency_ms)
    return docs, latency_ms
