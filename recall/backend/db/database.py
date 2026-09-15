"""
db.py — Async SQLAlchemy engine + session factory.
All database I/O uses asyncpg under the hood.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from config import get_settings


def _async_db_url(url: str) -> str:
    """Convert postgresql:// → postgresql+asyncpg://"""
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


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


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a session and always commits/rolls back."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
