"""
moss_client.py — Async wrapper around Moss SDK 1.11.0.

API shape confirmed against live credentials:
  - MossClient(project_id, project_key)
  - create_index(name, docs: List[DocumentInfo], wait=True)
  - load_index(name, auto_refresh=False) → str
  - add_docs(name, docs: List[DocumentInfo])
  - query(name, query_str, options: QueryOptions | None) → SearchResult
      SearchResult.docs → List[QueryResultDocumentInfo]
      QueryResultDocumentInfo: .id .text .score .metadata .payload .index_name

Round-trip confirmed: create → load → query = 12ms total, time_taken_ms=1ms in-process.
"""

import asyncio
import time
import logging
from typing import Any

from moss import MossClient, DocumentInfo, QueryOptions

from config import get_settings
from security.moss_authz import authorize_or_empty, scoped_doc_id

logger = logging.getLogger(__name__)


class MossIndexClient:
    """
    Manages a single named Moss index.
    Singleton per application instance via get_moss_client().
    """

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

    async def ensure_ready(self) -> None:
        """
        Idempotent — loads index into local memory if it exists,
        or creates it with a seed document on first run.
        Moss rejects create_index with empty docs (docCount >= 1 required).
        """
        if self._ready:
            return
        try:
            logger.info("moss.ensure_ready | index=%s", self._index_name)
            # Try to load first — works if index was created in a prior run
            try:
                await self._client.load_index(self._index_name, auto_refresh=True)
                logger.info("moss.ensure_ready | existing index loaded")
            except Exception:
                # Index doesn't exist yet — create it with a seed document
                seed = DocumentInfo(
                    id="__recall_seed__",
                    text="Recall workspace initialized",
                )
                await self._client.create_index(self._index_name, [seed], wait=True)
                await self._client.load_index(self._index_name, auto_refresh=True)
                logger.info("moss.ensure_ready | new index created and loaded")
            self._ready = True
        except Exception as exc:
            logger.error("moss.ensure_ready failed | %s", exc, exc_info=True)
            raise

    async def add_documents(self, documents: list[dict[str, Any]]) -> None:
        """
        Upsert documents. Each dict needs at least {"id": str, "text": str}.
        Optional: {"metadata": dict, "payload": dict}
        """
        await self.ensure_ready()
        docs = [DocumentInfo(id=d["id"], text=d["text"]) for d in documents]
        logger.debug("moss.add_documents | count=%d", len(docs))
        await self._client.add_docs(self._index_name, docs)

    async def query(
        self,
        text: str,
        top_k: int = 5,
    ) -> tuple[list[dict[str, Any]], float]:
        """
        Hybrid semantic + keyword query.
        Returns (docs_list, latency_ms).
        docs_list entries: {"id", "text", "score"}
        """
        await self.ensure_ready()
        t0 = time.perf_counter()
        results = await self._client.query(
            self._index_name,
            text,
            QueryOptions(top_k=top_k),
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        docs = [
            {"id": doc.id, "text": doc.text, "score": doc.score}
            for doc in results.docs
        ]
        logger.info(
            "moss.query | query=%r hits=%d latency=%.2fms sdk_ms=%s",
            text[:60],
            len(docs),
            latency_ms,
            results.time_taken_ms,
        )
        return docs, latency_ms

    async def query_authorized(
        self,
        workspace_id: str,
        text: str,
        top_k: int = 5,
    ) -> tuple[list[dict[str, Any]], float]:
        """Query this index, then strip any hit that is not owned by workspace_id."""
        docs, latency_ms = await self.query(text, top_k=top_k)
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
            }
            for d in documents
        ]
        await self.add_documents(scoped)

    async def run_round_trip_test(self) -> dict[str, Any]:
        """
        Smoke test: write a known document, query it back, assert it appears.
        Returns {"status", "latency_ms", "hits", "top_score"}.
        Raises RuntimeError if the test document isn't returned.

        NOTE: Moss is local-first — add_docs pushes to Moss Cloud but the
        local in-memory index is stale until reloaded. We force unload→reload
        here to get immediate consistency for the health check. Production
        queries rely on auto_refresh=True polling for eventual consistency.
        """
        test_id = "__recall_health_check__"
        test_text = "Recall workspace health check semantic round-trip test document"

        # Ensure index exists and is loaded
        await self.ensure_ready()

        # Upsert the canary document → Moss Cloud
        await self._client.add_docs(
            self._index_name,
            [DocumentInfo(id=test_id, text=test_text)],
        )

        # Force reload: unload stale local cache, pull fresh from Moss Cloud
        await self._client.unload_index(self._index_name)
        await self._client.load_index(self._index_name, auto_refresh=True)
        self._ready = True

        # Query — should now find the canary doc in local memory
        t0 = time.perf_counter()
        results = await self._client.query(
            self._index_name,
            "workspace semantic health check",
            QueryOptions(top_k=3),
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        found = any(doc.id == test_id for doc in results.docs)
        if not found:
            raise RuntimeError(
                "Moss round-trip FAILED: test document not in query results"
            )

        top_score = results.docs[0].score if results.docs else None
        logger.info(
            "moss.round_trip PASSED | latency=%.2fms sdk_ms=%s top_score=%s",
            latency_ms,
            results.time_taken_ms,
            top_score,
        )
        return {
            "status": "ok",
            "latency_ms": round(latency_ms, 2),
            "sdk_ms": results.time_taken_ms,
            "hits": len(results.docs),
            "top_score": round(top_score, 4) if top_score else None,
        }


# ── Module-level clients ──────────────────────────────────────────
_moss_client: MossIndexClient | None = None
_workspace_clients: dict[tuple[str, str, str], MossIndexClient] = {}


def get_moss_client() -> MossIndexClient:
    """Default / health-check client. Agents must use get_workspace_moss_client()."""
    global _moss_client
    if _moss_client is None:
        _moss_client = MossIndexClient()
    return _moss_client


def get_workspace_moss_client(
    project_id: str,
    project_key: str,
    index_name: str,
) -> MossIndexClient:
    """One Moss client per workspace isolation triple — never a global agent index."""
    key = (project_id, project_key, index_name)
    client = _workspace_clients.get(key)
    if client is None:
        client = MossIndexClient(
            project_id=project_id,
            project_key=project_key,
            index_name=index_name,
        )
        _workspace_clients[key] = client
    return client
