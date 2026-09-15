"""
Phase 0 smoke test — runs against the live stack.
Requires docker compose up to be running.
"""
import pytest
import httpx

BASE_URL = "http://localhost:8100"


@pytest.mark.asyncio
async def test_health_returns_200():
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "services" in data


@pytest.mark.asyncio
async def test_postgres_healthy():
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/health")
    services = resp.json()["services"]
    assert services["postgres"]["ok"] is True, f"Postgres unhealthy: {services['postgres']}"


@pytest.mark.asyncio
async def test_redis_healthy():
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/health")
    services = resp.json()["services"]
    assert services["redis"]["ok"] is True, f"Redis unhealthy: {services['redis']}"


@pytest.mark.asyncio
async def test_qdrant_healthy():
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/health")
    services = resp.json()["services"]
    assert services["qdrant"]["ok"] is True, f"Qdrant unhealthy: {services['qdrant']}"


@pytest.mark.asyncio
async def test_moss_round_trip():
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(f"{BASE_URL}/moss/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["latency_ms"] < 100  # should be sub-10ms once index is warm
    print(f"\n✓ Moss round-trip latency: {data['latency_ms']}ms  top_score={data['top_score']}")
