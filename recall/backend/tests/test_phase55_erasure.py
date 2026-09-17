"""Phase 5.5 workspace-erasure tests; no live services required."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from retrieval import qdrant_store
from routers import security


WORKSPACE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class FakeResult:
    def __init__(self, *, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


class FakeSession:
    def __init__(self, results, events=None):
        self.results = list(results)
        self.events = events
        self.statements = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement, parameters):
        sql = str(statement)
        self.statements.append((sql, parameters))
        if self.events is not None and sql.lstrip().upper().startswith("DELETE"):
            self.events.append("postgres")
        return self.results.pop(0)

    async def commit(self):
        self.committed = True


class SessionFactory:
    def __init__(self, sessions):
        self.sessions = list(sessions)

    def __call__(self):
        return self.sessions.pop(0)


class FakeQdrant:
    def __init__(self, *, collection_exists=True, count=0):
        self.exists = collection_exists
        self.document_count = count
        self.count_calls = []
        self.delete_calls = []

    def collection_exists(self, collection_name):
        return self.exists

    def count(self, **kwargs):
        self.count_calls.append(kwargs)
        return SimpleNamespace(count=self.document_count)

    def delete(self, **kwargs):
        self.delete_calls.append(kwargs)


def test_qdrant_deletes_only_exact_workspace_filter(monkeypatch):
    client = FakeQdrant(count=3)
    monkeypatch.setattr(qdrant_store, "get_qdrant", lambda: client)
    monkeypatch.setattr(
        qdrant_store,
        "get_settings",
        lambda: SimpleNamespace(qdrant_collection="recall-documents"),
    )

    deleted = qdrant_store.delete_workspace_documents(WORKSPACE_ID)

    assert deleted == 3
    count_filter = client.count_calls[0]["count_filter"]
    assert count_filter.must[0].key == "workspace_id"
    assert count_filter.must[0].match.value == WORKSPACE_ID
    selector_filter = client.delete_calls[0]["points_selector"].filter
    assert selector_filter == count_filter
    assert client.delete_calls[0]["wait"] is True


@pytest.mark.parametrize("collection_exists,count", [(False, 0), (True, 0)])
def test_qdrant_no_documents_is_a_noop(monkeypatch, collection_exists, count):
    client = FakeQdrant(collection_exists=collection_exists, count=count)
    monkeypatch.setattr(qdrant_store, "get_qdrant", lambda: client)
    monkeypatch.setattr(
        qdrant_store,
        "get_settings",
        lambda: SimpleNamespace(qdrant_collection="recall-documents"),
    )

    assert qdrant_store.delete_workspace_documents(WORKSPACE_ID) == 0
    assert client.delete_calls == []
    assert len(client.count_calls) == int(collection_exists)


@pytest.mark.asyncio
async def test_erasure_is_moss_first_and_reports_each_store(monkeypatch):
    events = []
    read_session = FakeSession(
        [FakeResult(rows=[SimpleNamespace(id="11111111-1111-1111-1111-111111111111")])]
    )
    delete_results = [FakeResult(rowcount=n) for n in (2, 1, 3, 4, 5, 6, 7, 1)]
    delete_session = FakeSession(delete_results, events=events)
    factory = SessionFactory([read_session, delete_session])
    monkeypatch.setattr(security, "get_session_factory", lambda: factory)

    moss = SimpleNamespace(delete_documents=AsyncMock(side_effect=lambda ids: events.append("moss") or len(ids)))
    monkeypatch.setattr(security, "get_workspace_moss_client", lambda: moss)

    def delete_qdrant(workspace_id):
        events.append("qdrant")
        assert workspace_id == WORKSPACE_ID
        return 8

    monkeypatch.setattr(security.qdrant_store, "delete_workspace_documents", delete_qdrant)

    response = await security.erase_workspace_data(WORKSPACE_ID)

    assert events[:2] == ["moss", "qdrant"]
    assert events[2:] == ["postgres"] * 8
    assert response.workspace_id == WORKSPACE_ID
    assert response.moss_deleted == 1
    assert response.qdrant_deleted == 8
    assert response.postgres_deleted == {
        "checkpoint_writes": 2,
        "checkpoint_blobs": 1,
        "checkpoints": 3,
        "audit_logs": 4,
        "messages": 5,
        "tasks": 6,
        "sessions": 7,
        "workspaces": 1,
    }

    delete_sql = [sql for sql, _ in delete_session.statements]
    assert [sql.split()[2] for sql in delete_sql[:3]] == [
        "checkpoint_writes",
        "checkpoint_blobs",
        "checkpoints",
    ]
    for sql in delete_sql[:3]:
        assert "SELECT langgraph_thread_id FROM tasks" in sql
        assert "workspace_id = CAST(:wid AS uuid)" in sql
        assert "langgraph_thread_id IS NOT NULL" in sql
    assert all(parameters == {"wid": WORKSPACE_ID} for _, parameters in delete_session.statements)
    assert delete_session.committed is True


@pytest.mark.asyncio
async def test_moss_failure_leaves_qdrant_and_postgres_untouched(monkeypatch):
    read_session = FakeSession([FakeResult(rows=[SimpleNamespace(id="message-id")])])
    factory = SessionFactory([read_session])
    monkeypatch.setattr(security, "get_session_factory", lambda: factory)

    moss = SimpleNamespace(delete_documents=AsyncMock(side_effect=RuntimeError("Moss rejected erasure")))
    monkeypatch.setattr(security, "get_workspace_moss_client", lambda: moss)

    qdrant_delete = AsyncMock()
    monkeypatch.setattr(security.qdrant_store, "delete_workspace_documents", qdrant_delete)

    with pytest.raises(RuntimeError, match="Moss rejected erasure"):
        await security.erase_workspace_data(WORKSPACE_ID)

    qdrant_delete.assert_not_called()
    assert factory.sessions == []
