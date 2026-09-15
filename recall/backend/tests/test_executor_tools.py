"""
tests/test_executor_tools.py — Playwright browse tests (need Docker + network).

Allowlist unit tests live in test_phase3.py so they run without Settings/.env.
"""

import pytest
from agents.tools import browse_url

ALLOW = ["wikipedia.org", "github.com", "docs.python.org"]


@pytest.mark.asyncio
async def test_browse_wikipedia_success():
    """Real Playwright call to wikipedia.org (in allowlist)."""
    result = await browse_url(
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        timeout_ms=15000,
        allowed_domains=ALLOW,
    )
    assert result["success"] is True, f"Expected success, got error: {result.get('error')}"
    assert len(result["content"]) > 100, "Expected substantial page content"
    assert result["tool"] == "playwright/browse_url"
    assert "wikipedia.org" in result["url"]


@pytest.mark.asyncio
async def test_browse_blocked_domain():
    result = await browse_url("https://evil.com/attack", timeout_ms=9000, allowed_domains=ALLOW)
    assert result["success"] is False
    assert result["blocked"] is True
    assert "allowlist" in result["error"].lower() or "blocked" in result["error"].lower()


@pytest.mark.asyncio
async def test_browse_returns_dict_on_timeout():
    result = await browse_url("https://github.com", timeout_ms=1, allowed_domains=ALLOW)
    assert isinstance(result, dict)
    assert "success" in result
    assert "error" in result
