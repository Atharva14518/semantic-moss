"""
security/domain_guard.py — Domain allowlist gate for Playwright Executor.

Any URL an agent wants to visit is validated here before Playwright
navigates to it. This is the canonical allowlist check.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from config import get_settings

logger = logging.getLogger(__name__)


class DomainBlocked(Exception):
    """Raised when a URL's domain is not in the allowlist."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"Domain blocked: {urlparse(url).hostname}")


def _normalize_domains(domains: list[str] | None) -> list[str]:
    if domains is None:
        domains = get_settings().allowed_domains_list
    return [d.strip().lstrip(".") for d in domains if d and d.strip()]


def is_allowed(url: str, allowed_domains: list[str] | None = None) -> bool:
    """
    Return True if url's hostname (or any parent domain) is in the allowlist.

    Examples (allowed_domains = ["wikipedia.org", "github.com"]):
        is_allowed("https://en.wikipedia.org/wiki/Python") → True
        is_allowed("https://evil.com")                     → False
    """
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except Exception:
        return False

    if not hostname:
        return False

    for domain in _normalize_domains(allowed_domains):
        domain = domain.lower()
        if hostname == domain or hostname.endswith("." + domain):
            logger.debug("domain_guard.allowed | hostname=%s domain=%s", hostname, domain)
            return True

    logger.warning("domain_guard.blocked | url=%s hostname=%s", url, hostname)
    return False


def assert_allowed(url: str, allowed_domains: list[str] | None = None) -> None:
    """Raise DomainBlocked if url is not on the allowlist."""
    if not is_allowed(url, allowed_domains):
        raise DomainBlocked(url)
