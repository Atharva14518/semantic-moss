"""
moss_client.py — One shared Moss index for the whole app.

Isolation is metadata.workspace_id + orchestrator authz, not per-workspace
Moss projects. Creating extra indexes would burn the metered Cloud quota.
"""

import logging
import time
from typing import Any

from moss import MossClient, DocumentInfo, QueryOptions

from config import get_settings
from moss_guard import record_live_moss_query
from security.moss_authz import authorize_or_empty, scoped_doc_id

logger = logging.getLogger(__name__)


def is_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "429" in text
        or "usage_limit" in text
        or "credit_exhausted" in text
        or "quota" in text
    )


class MossIndexClient:
    def __init__(
        self,
        project_id: str | None = None,
        project_key: str | None = None,
        index_name: str | None = None,
    ):
        cfg = get_settings()
        self._project_id = project_id or cfg.moss_project_id
        self._project_key = project_key or cfg.moss_project_key
        self._index_name = index_name or cfg.moss_index_name
        self._client = MossClient(self._project_id, self._project_key)
        self._ready = False
        self.quota_exhausted = False

    async def ensure_ready(self) -> None:
        if self.quota_exhausted or self._ready:
            return
        try:
            logger.info("moss.ensure_ready | index=%s", self._index_name)
            try:
                await self._client.load_index(self._index_name, auto_refresh=True)
                logger.info("moss.ensure_ready | existing index loaded")
                self._ready = True
                # Warm up embedding model so first benchmark query is not penalized by cold load
                try:
                    await self._client.query(self._index_name, "warmup", QueryOptions(top_k=1))
                except Exception:
                    pass
                return
            except Exception as exc:
                if is_quota_error(exc):
                    self.quota_exhausted = True
                    logger.warning("moss.quota_exhausted | no further Cloud calls this process")
                    return
                msg = str(exc).lower()
                missing = any(
                    s in msg
                    for s in ("not found", "does not exist", "unknown index", "no such index")
                )
                if not missing:
                    logger.error("moss.load_index failed | %s", exc)
                    raise
                # Free trial: 3 indexes max. Create only the single shared name, never a 2nd.
                logger.warning("moss.ensure_ready | creating the one shared index=%s", self._index_name)
                seed = DocumentInfo(
                    id="__recall_seed__",
                    text="Recall workspace initialized",
                    metadata={"workspace_id": "shared", "kind": "seed"},
                )
                await self._client.create_index(self._index_name, [seed], wait=True)
                await self._client.load_index(self._index_name, auto_refresh=True)
                logger.info("moss.ensure_ready | shared index created and loaded")
                self._ready = True
                return
        except Exception as exc:
            if is_quota_error(exc):
                self.quota_exhausted = True
                logger.warning("moss.quota_exhausted | no further Cloud calls this process")
                return
            logger.error("moss.ensure_ready failed | %s", exc, exc_info=True)
            raise

    async def add_documents(self, documents: list[dict[str, Any]]) -> None:
        await self.ensure_ready()
        if self.quota_exhausted:
            logger.warning("moss.add_documents skipped | quota_exhausted")
            return
        docs = [
            DocumentInfo(
                id=d["id"],
                text=d["text"],
                metadata=d.get("metadata") or {},
            )
            for d in documents
        ]
        logger.info("moss.add_documents | count=%d", len(docs))
        await self._client.add_docs(self._index_name, docs)

    async def query(
        self,
        text: str,
        top_k: int = 5,
        reason: str = "agent_retrieval",
        workspace_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], float]:
        await self.ensure_ready()
        if self.quota_exhausted or not self._ready:
            logger.warning(
                "moss.query skipped | quota_exhausted=%s ready=%s",
                self.quota_exhausted,
                self._ready,
            )
            return [], 0.0
        record_live_moss_query(reason)
        t0 = time.perf_counter()
        try:
            results = await self._client.query(
                self._index_name,
                text,
                QueryOptions(top_k=top_k),
            )
        except Exception as exc:
            if is_quota_error(exc):
                self.quota_exhausted = True
                logger.warning("moss.quota_exhausted | query circuit open")
                return [], 0.0
            raise
        latency_ms = (time.perf_counter() - t0) * 1000

        docs = []
        for doc in results.docs:
            meta = getattr(doc, "metadata", None) or {}
            docs.append({
                "id": doc.id,
                "text": doc.text,
                "score": doc.score,
                "metadata": meta if isinstance(meta, dict) else {},
            })
        logger.info(
            "moss.query | query=%r hits=%d latency=%.2fms sdk_ms=%s reason=%s",
            text[:60],
            len(docs),
            latency_ms,
            results.time_taken_ms,
            reason,
        )
        return docs, latency_ms

    async def query_authorized(
        self,
        workspace_id: str,
        text: str,
        top_k: int = 5,
        reason: str = "agent_retrieval",
    ) -> tuple[list[dict[str, Any]], float]:
        docs, latency_ms = await self.query(
            text,
            top_k=top_k,
            reason=reason,
            workspace_id=workspace_id,
        )
        return authorize_or_empty(workspace_id, docs), latency_ms

    async def add_workspace_documents(
        self,
        workspace_id: str,
        documents: list[dict[str, Any]],
    ) -> None:
        scoped = [
            {
                "id": scoped_doc_id(workspace_id, d["id"]),
                "text": d["text"],
                "metadata": {"workspace_id": workspace_id, **(d.get("metadata") or {})},
            }
            for d in documents
        ]
        await self.add_documents(scoped)

    async def delete_documents(self, document_ids: list[str]) -> int:
        """Delete known workspace document IDs from the shared Moss index.

        The Moss SDK deletes by ID rather than metadata filter. Callers must
        obtain IDs from Postgres first; this prevents a workspace deletion from
        touching another tenant's documents in the shared index.
        """
        if not document_ids:
            return 0
        await self.ensure_ready()
        # Deletion is a data-rights operation, not normal workload. Attempt it
        # even when the query circuit is open due to trial quota; if Moss
        # rejects the operation, let the caller fail closed before Postgres is
        # touched.
        try:
            await self._client.delete_docs(self._index_name, document_ids)
        except Exception as exc:
            raise RuntimeError("Moss rejected workspace data erasure") from exc
        logger.info("moss.delete_documents | count=%d", len(document_ids))
        return len(document_ids)

    async def run_round_trip_test(self) -> dict[str, Any]:
        """Writes to Moss Cloud. Do not call from health, UI, or loops."""
        if self.quota_exhausted:
            return {"status": "quota_exhausted", "latency_ms": None, "hits": 0, "top_score": None}
        test_id = "__recall_health_check__"
        test_text = "Recall workspace health check semantic round-trip test document"
        await self.ensure_ready()
        if self.quota_exhausted:
            return {"status": "quota_exhausted", "latency_ms": None, "hits": 0, "top_score": None}
        await self._client.add_docs(
            self._index_name,
            [DocumentInfo(
                id=test_id,
                text=test_text,
                metadata={"workspace_id": "shared", "kind": "health"},
            )],
        )
        await self._client.unload_index(self._index_name)
        await self._client.load_index(self._index_name, auto_refresh=True)
        self._ready = True
        docs, latency_ms = await self.query(
            "workspace semantic health check",
            top_k=3,
            reason="health_query",
        )
        found = any(doc["id"] == test_id for doc in docs)
        if not found:
            raise RuntimeError("Moss round-trip FAILED: test document not in query results")
        top_score = docs[0]["score"] if docs else None
        return {
            "status": "ok",
            "latency_ms": round(latency_ms, 2),
            "hits": len(docs),
            "top_score": round(top_score, 4) if top_score else None,
        }


_moss_client: MossIndexClient | None = None


def get_moss_client() -> MossIndexClient:
    global _moss_client
    if _moss_client is None:
        _moss_client = MossIndexClient()
    return _moss_client


def get_workspace_moss_client(
    project_id: str | None = None,
    project_key: str | None = None,
    index_name: str | None = None,
) -> MossIndexClient:
    """Always the shared index. Args ignored — kept so callers do not create tenants."""
    return get_moss_client()
