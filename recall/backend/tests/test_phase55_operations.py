"""Phase 5.5 operational lifecycle tests."""

import pytest

from db import database


class FakeEngine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


@pytest.mark.asyncio
async def test_close_engine_disposes_and_resets_singletons(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", object())

    await database.close_engine()

    assert engine.disposed is True
    assert database._engine is None
    assert database._session_factory is None
