"""
agents/tools.py — Real tool implementations for the Executor agent.

browse_url(url, timeout_ms=9000, allowed_domains=None)
  • Validates the URL against the domain allowlist
  • Opens a headless Chromium page via Playwright
  • Returns plain-text content extracted from the page body
  • On any failure returns a structured error dict — never raises.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from security.domain_guard import is_allowed

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)

# A deliberately small set of canonical documentation routes.  This lets the
# executor perform an explicitly requested official-docs lookup even when the
# planner describes a site by name rather than pasting a URL.  It is not a
# general web-search facility: any resolved URL still goes through the
# workspace's domain allowlist in ``browse_url``.
_OFFICIAL_DOCS = (
    (
        re.compile(r"\bnode\.?js\b", re.IGNORECASE),
        "https://nodejs.org/en/download",
    ),
)

_WEB_LOOKUP_LANGUAGE = re.compile(
    r"\b(?:browse|download|docs?|documentation|latest|navigate|official|release|version|visit)\b",
    re.IGNORECASE,
)


def extract_urls(text: str) -> list[str]:
    """Return all http/https URLs found in `text`."""
    urls = _URL_RE.findall(text)
    cleaned: list[str] = []
    for url in urls:
        cleaned.append(url.rstrip(".,);]}>'\" "))
    return cleaned


def infer_official_docs_url(text: str) -> str | None:
    """Return a safe canonical URL for an explicit official-docs request.

    Planner subtasks often say "navigate to the Node.js docs" without a URL.
    Resolving only known official sites avoids silently replacing browsing with
    model knowledge while keeping browser access constrained and auditable.
    """
    if not _WEB_LOOKUP_LANGUAGE.search(text):
        return None
    for product_pattern, url in _OFFICIAL_DOCS:
        if product_pattern.search(text):
            return url
    return None


async def browse_url(
    url: str,
    timeout_ms: int = 9000,
    allowed_domains: list[str] | None = None,
) -> dict:
    """
    Navigate to `url` with headless Chromium and return extracted text.

    Returns a dict with keys:
        url        str
        success    bool
        blocked    bool   — True when the allowlist rejected the URL
        content    str
        error      str
        tool       str
    """
    result_base = {
        "url": url,
        "tool": "playwright/browse_url",
        "blocked": False,
    }

    if not is_allowed(url, allowed_domains):
        hostname = urlparse(url).hostname or ""
        logger.warning("browse_url.blocked | url=%s hostname=%s", url, hostname)
        return {
            **result_base,
            "success": False,
            "blocked": True,
            "content": "",
            "error": f"Domain not in allowlist: {hostname}",
            "hostname": hostname,
        }

    try:
        from playwright.async_api import TimeoutError as PWTimeout
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                await page.route(
                    "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,css}",
                    lambda route: route.abort(),
                )

                logger.info("browse_url.navigating | url=%s timeout=%dms", url, timeout_ms)
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                content = await page.evaluate("""() => {
                    const clone = document.body.cloneNode(true);
                    clone.querySelectorAll('script,style,nav,footer,header').forEach(el => el.remove());
                    return clone.innerText || clone.textContent || '';
                }""")

                content = " ".join(content.split())[:4000]
                logger.info("browse_url.success | url=%s chars=%d", url, len(content))

                return {
                    **result_base,
                    "success": True,
                    "content": content,
                    "error": "",
                }

            except PWTimeout:
                logger.warning("browse_url.timeout | url=%s timeout=%dms", url, timeout_ms)
                return {
                    **result_base,
                    "success": False,
                    "content": "",
                    "error": f"Page load timed out after {timeout_ms}ms",
                }
            finally:
                await browser.close()

    except Exception as exc:
        logger.error("browse_url.error | url=%s error=%s", url, exc)
        return {
            **result_base,
            "success": False,
            "content": "",
            "error": f"Could not reach page: {exc}",
        }
