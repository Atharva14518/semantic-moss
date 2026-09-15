"""Phase 4: metadata isolation + no accidental Moss ingest on authorize."""

from moss_client import is_quota_error
from security.moss_authz import authorize_or_empty, scoped_doc_id


def test_metadata_workspace_id_is_enough():
    ws = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    other = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    docs = [
        {"id": "raw-1", "text": "mine", "metadata": {"workspace_id": ws}},
        {"id": "raw-2", "text": "theirs", "metadata": {"workspace_id": other}},
        {"id": scoped_doc_id(ws, "n"), "text": "scoped"},
    ]
    kept = authorize_or_empty(ws, docs)
    assert {d["text"] for d in kept} == {"mine", "scoped"}


def test_shared_index_seed_stripped_from_agent():
    ws = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    kept = authorize_or_empty(ws, [{"id": "__recall_seed__", "text": "global"}])
    assert kept == []


def test_quota_error_detection():
    from moss_client import is_quota_error

    assert is_quota_error(RuntimeError('HTTP 429 Too Many Requests: credit_exhausted'))
    assert not is_quota_error(RuntimeError("timeout"))
