"""
db.py — Async SQLAlchemy engine + session factory.
All database I/O uses asyncpg under the hood.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from config import get_settings


import urllib.parse


_ASYNCPG_ALLOWED_PARAMS = {
    "ssl",
    "timeout",
    "command_timeout",
    "statement_cache_size",
    "max_cached_statement_lifetime",
    "max_cacheable_statement_size",
    "server_settings",
}


def _async_db_url(url: str) -> str:
    """Convert postgresql:// → postgresql+asyncpg:// and strip unsupported libpq parameters."""
    u = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    parsed = urllib.parse.urlsplit(u)
    if not parsed.query:
        return u
    # asyncpg only accepts specific parameters; strip libpq params like channel_binding, gssencmode
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    new_params = []
    has_ssl = False
    for k, v in query_params:
        if k == "sslmode":
            if v != "disable":
                has_ssl = True
        elif k == "ssl":
            has_ssl = True
            new_params.append((k, v))
        elif k in _ASYNCPG_ALLOWED_PARAMS:
            new_params.append((k, v))

    if has_ssl and not any(k == "ssl" for k, _ in new_params):
        new_params.append(("ssl", "require"))

    new_query = urllib.parse.urlencode(new_params)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def build_engine():
    cfg = get_settings()
    return create_async_engine(
        _async_db_url(cfg.database_url),
        echo=cfg.environment == "development",
        poolclass=NullPool,  # safe for async; no cross-coroutine connection sharing
    )


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


async def close_engine() -> None:
    """Release database resources during graceful process shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session and always commits/rolls back."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
