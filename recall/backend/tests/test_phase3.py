"""Phase 3 security tests — allowlist, Moss authz, blocked Executor browse."""

from security.domain_guard import is_allowed
from security.moss_authz import authorize_moss_hits, authorize_or_empty, scoped_doc_id
from agents.tools import extract_urls, browse_url


ALLOW = ["wikipedia.org", "github.com", "docs.python.org"]


class TestDomainAllowlist:
    def test_wikipedia_allowed(self):
        assert is_allowed("https://en.wikipedia.org/wiki/LangGraph", ALLOW) is True

    def test_github_allowed(self):
        assert is_allowed("https://github.com/langchain-ai/langgraph", ALLOW) is True

    def test_subdomain_allowed(self):
        assert is_allowed("https://docs.python.org/3/library/asyncio.html", ALLOW) is True

    def test_evil_domain_blocked(self):
        assert is_allowed("https://evil.com/exfiltrate", ALLOW) is False

    def test_evil_lookalike_blocked(self):
        assert is_allowed("https://notwikipedia.org", ALLOW) is False

    def test_empty_url_blocked(self):
        assert is_allowed("", ALLOW) is False

    def test_malformed_url_blocked(self):
        assert is_allowed("not-a-url", ALLOW) is False

    def test_workspace_custom_allowlist(self):
        assert is_allowed("https://evil.com", ["evil.com"]) is True
        assert is_allowed("https://wikipedia.org", ["evil.com"]) is False


class TestMossAuthz:
    def test_keeps_same_workspace_docs(self):
        ws = "11111111-1111-1111-1111-111111111111"
        docs = [
            {"id": scoped_doc_id(ws, "goal-1"), "text": "own goal"},
            {"id": scoped_doc_id(ws, "note"), "text": "own note", "metadata": {"workspace_id": ws}},
        ]
        allowed, rejected = authorize_moss_hits(ws, docs)
        assert len(allowed) == 2
        assert rejected == []

    def test_strips_foreign_workspace_docs(self):
        ws_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        ws_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        docs = [
            {"id": scoped_doc_id(ws_b, "secret"), "text": "other workspace secret"},
            {"id": scoped_doc_id(ws_a, "ok"), "text": "safe"},
            {"id": "__recall_seed__", "text": "global seed"},
        ]
        kept = authorize_or_empty(ws_a, docs)
        assert [d["id"] for d in kept] == [scoped_doc_id(ws_a, "ok")]

    def test_unscoped_docs_never_reach_agent(self):
        ws = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        kept = authorize_or_empty(ws, [{"id": "raw-id", "text": "leak"}])
        assert kept == []


class TestExtractUrls:
    def test_extracts_https(self):
        urls = extract_urls("Browse https://en.wikipedia.org/wiki/Python for info")
        assert urls == ["https://en.wikipedia.org/wiki/Python"]

    def test_extracts_multiple(self):
        urls = extract_urls("See https://github.com and https://docs.python.org")
        assert len(urls) == 2

    def test_no_urls(self):
        assert extract_urls("No URL here") == []

    def test_strips_trailing_punctuation(self):
        urls = extract_urls("Visit https://github.com.")
        assert all(not u.endswith(".") for u in urls)


async def test_browse_blocked_domain_no_browser():
    result = await browse_url("https://evil.com/attack", allowed_domains=ALLOW)
    assert result["success"] is False
    assert result["blocked"] is True
    assert "allowlist" in result["error"].lower()
