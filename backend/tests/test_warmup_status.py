"""Tests for /api/v1/system/warmup endpoint and warmup state tracking.

Contract: api-contracts/system/warmup.md
All external calls are mocked — no network needed.
"""
import time
from unittest.mock import patch
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


@pytest.fixture
def warmup_app():
    """Create a minimal app with the system router and mock warmup state."""
    from app.routers.system import router

    app = FastAPI()
    app.include_router(router)

    app.state.warmup = {
        "market_cache": {"done": False, "success": False, "label": "\u884c\u60c5\u7f13\u5b58"},
        "global_indices": {"done": False, "success": False, "label": "\u5168\u7403\u6307\u6570"},
        "etf_cache": {"done": False, "success": False, "label": "ETF \u626b\u63cf"},
    }
    app.state._startup_ts = time.time()
    return app


@pytest.mark.asyncio
async def test_warmup_returns_all_not_done_on_fresh_start(warmup_app):
    """On a fresh app, all warmup tasks should show done=False."""
    transport = ASGITransport(app=warmup_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/system/warmup")

    assert resp.status_code == 200
    data = resp.json()

    assert data["all_done"] is False
    for name in ("market_cache", "global_indices", "etf_cache"):
        assert name in data["warmup"]
        assert data["warmup"][name]["done"] is False
        assert data["warmup"][name]["success"] is False
        assert "label" in data["warmup"][name]
    assert isinstance(data["elapsed_seconds"], (int, float))
    assert data["elapsed_seconds"] >= 0


@pytest.mark.asyncio
async def test_warmup_returns_all_done_when_all_complete(warmup_app):
    """When all tasks are complete, all_done should be True."""
    for v in warmup_app.state.warmup.values():
        v["done"] = True
        v["success"] = True

    transport = ASGITransport(app=warmup_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/system/warmup")

    assert resp.status_code == 200
    data = resp.json()
    assert data["all_done"] is True
    for name in ("market_cache", "global_indices", "etf_cache"):
        assert data["warmup"][name]["done"] is True
        assert data["warmup"][name]["success"] is True


@pytest.mark.asyncio
async def test_warmup_partial_done(warmup_app):
    """Partial completion: only market_cache done, others still running."""
    warmup_app.state.warmup["market_cache"]["done"] = True
    warmup_app.state.warmup["market_cache"]["success"] = True

    transport = ASGITransport(app=warmup_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/system/warmup")

    assert resp.status_code == 200
    data = resp.json()
    assert data["all_done"] is False
    assert data["warmup"]["market_cache"]["done"] is True
    assert data["warmup"]["market_cache"]["success"] is True
    assert data["warmup"]["global_indices"]["done"] is False
    assert data["warmup"]["etf_cache"]["done"] is False


@pytest.mark.asyncio
async def test_warmup_done_is_true_even_on_failure(warmup_app):
    """A task that finished (even with failure) should show done=True."""
    warmup_app.state.warmup["global_indices"]["done"] = True
    warmup_app.state.warmup["global_indices"]["success"] = False

    transport = ASGITransport(app=warmup_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/system/warmup")

    assert resp.status_code == 200
    data = resp.json()
    assert data["warmup"]["global_indices"]["done"] is True
    assert data["warmup"]["global_indices"]["success"] is False
    assert data["all_done"] is False


@pytest.mark.asyncio
async def test_warmup_elapsed_seconds_increases(warmup_app):
    """elapsed_seconds should reflect time since startup."""
    with patch("app.routers.system.time.time") as mock_time:
        mock_time.return_value = warmup_app.state._startup_ts + 5.0
        transport = ASGITransport(app=warmup_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/system/warmup")

    assert resp.status_code == 200
    data = resp.json()
    assert data["elapsed_seconds"] == 5.0


# ── R6-F2 (round6 §十 R6-03): total_elapsed 字段 ─────────────────
# A01 门禁读 total_elapsed/duration_ms，端点此前只返回 elapsed_seconds →
# 门禁恒走"未启用"分支恒 PASS。修复：端点补 total_elapsed（profiler 分段求和，
# 与 warmup_timing.json 对齐）；verify_e2e 兜底读 elapsed_seconds。


@pytest.mark.asyncio
async def test_warmup_total_elapsed_from_profiler(warmup_app, monkeypatch):
    """PROFILE_WARMUP=1 时 total_elapsed = profiler 各分段耗时之和（毫秒）。"""
    import app.routers.system as sys_mod

    class _FakeProfiler:
        def __init__(self):
            self.records = []
            self.record = type("R", (), {"duration_ms": 6512.0})()
            self.record2 = type("R", (), {"duration_ms": 6220.0})()

    # 模拟 profiler 已记录两条耗时
    fake = _FakeProfiler()
    fake.records = [fake.record, fake.record2]
    monkeypatch.setattr(sys_mod, "_get_profiler_records", lambda: fake.records)

    transport = ASGITransport(app=warmup_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/system/warmup")

    assert resp.status_code == 200
    data = resp.json()
    assert "total_elapsed" in data
    assert data["total_elapsed"] == 6512.0 + 6220.0


@pytest.mark.asyncio
async def test_warmup_total_elapsed_zero_without_profiler(warmup_app, monkeypatch):
    """无 profiler 记录（非 PROFILE_WARMUP）时 total_elapsed 为 0——verify_e2e 兜底 elapsed_seconds。"""
    import app.routers.system as sys_mod

    monkeypatch.setattr(sys_mod, "_get_profiler_records", lambda: [])
    transport = ASGITransport(app=warmup_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/system/warmup")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_elapsed"] == 0
