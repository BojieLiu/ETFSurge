"""round49 B3: /admin/lifespan-warmup 端点 + app.state.nav_warmup 共享状态.

覆盖:
  - state 未初始化 → fallback dict (含 _state_uninitialized)
  - state 已初始化 + 刚跑完首轮 → 完整数据 + next_run_eta_s 按 elapsed 调整
  - state 中 last_cycle 字段完整 (cycle/total/ok/skip/err/duration_s/reason)
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def admin_client():
    """最小 FastAPI app + TestClient (避免 lifespan 卡死)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.admin import router as admin_router
    app = FastAPI()
    app.include_router(admin_router)
    return TestClient(app), app


def test_lifespan_warmup_state_uninitialized_fallback(admin_client):
    """app.state.nav_warmup 未初始化 → 返 fallback dict."""
    client, app = admin_client
    r = client.get("/api/v1/admin/lifespan-warmup")
    assert r.status_code == 200
    data = r.json()
    assert data["_state_uninitialized"] is True
    assert data["last_cycle"] is None
    assert data["redis_available"] is False
    assert data["started_at"] is None
    assert data["warmup_period_s"] == 3600
    assert data["first_run_delay_s"] == 60


def test_lifespan_warmup_state_initialized_with_last_cycle(admin_client):
    """app.state.nav_warmup 已初始化 + 跑过一轮 → 完整数据."""
    client, app = admin_client
    # 模拟 _nav_warmup_loop 跑完一轮后写入的 state
    _t = time.time() - 100  # 100s 前
    app.state.nav_warmup = {
        "enabled": True,
        "started_at": _t - 60,  # 60s 前启动
        "warmup_period_s": 3600,
        "first_run_delay_s": 60,
        "last_cycle": {
            "ts": "2026-08-29T10:01:00Z",
            "cycle": 1,
            "total": 1618,
            "ok": 1500,
            "skip": 100,
            "err": 18,
            "duration_s": 412.5,
            "reason": None,
        },
        "last_cycle_start_ts": _t,
        "next_run_eta_s": 3600,  # 刚跑完, 距下轮 1h
        "redis_available": True,
    }
    r = client.get("/api/v1/admin/lifespan-warmup")
    assert r.status_code == 200
    data = r.json()
    assert "_state_uninitialized" not in data
    assert data["redis_available"] is True
    assert data["started_at"] is not None and data["started_at"].endswith("Z")
    assert data["last_cycle"]["total"] == 1618
    assert data["last_cycle"]["ok"] == 1500
    assert data["last_cycle"]["skip"] == 100
    assert data["last_cycle"]["err"] == 18
    assert data["last_cycle"]["duration_s"] == 412.5
    # next_run_eta_s 应 = 3600 - 100 = 3500 (允许 ±5 误差)
    assert 3495 <= data["next_run_eta_s"] <= 3505


def test_lifespan_warmup_reason_redis_unavailable(admin_client):
    """reason='redis_unavailable' → 端点透传."""
    client, app = admin_client
    _t = time.time()
    app.state.nav_warmup = {
        "enabled": True,
        "started_at": _t,
        "warmup_period_s": 3600,
        "first_run_delay_s": 60,
        "last_cycle": {
            "ts": "2026-08-29T10:01:00Z",
            "cycle": 1,
            "total": 0,
            "ok": 0,
            "skip": 0,
            "err": 0,
            "duration_s": 0.05,
            "reason": "redis_unavailable",
        },
        "last_cycle_start_ts": _t,
        "next_run_eta_s": 3600,
        "redis_available": False,
    }
    r = client.get("/api/v1/admin/lifespan-warmup")
    data = r.json()
    assert data["last_cycle"]["reason"] == "redis_unavailable"
    assert data["redis_available"] is False


def test_lifespan_warmup_reason_pool_empty(admin_client):
    """reason='pool_empty' → 端点透传."""
    client, app = admin_client
    _t = time.time()
    app.state.nav_warmup = {
        "enabled": True,
        "started_at": _t,
        "warmup_period_s": 3600,
        "first_run_delay_s": 60,
        "last_cycle": {
            "ts": "2026-08-29T10:01:00Z",
            "cycle": 1,
            "total": 0,
            "ok": 0,
            "skip": 0,
            "err": 0,
            "duration_s": 0.01,
            "reason": "pool_empty",
        },
        "last_cycle_start_ts": _t,
        "next_run_eta_s": 3600,
        "redis_available": True,
    }
    r = client.get("/api/v1/admin/lifespan-warmup")
    data = r.json()
    assert data["last_cycle"]["reason"] == "pool_empty"


def test_lifespan_warmup_next_run_eta_decreases(admin_client):
    """next_run_eta_s 随 elapsed 减少."""
    client, app = admin_client
    _t = time.time() - 3000  # 50min 前跑完首轮
    app.state.nav_warmup = {
        "enabled": True,
        "started_at": _t - 60,
        "warmup_period_s": 3600,
        "first_run_delay_s": 60,
        "last_cycle": {
            "ts": "2026-08-29T10:01:00Z",
            "cycle": 1,
            "total": 1618,
            "ok": 1500,
            "skip": 100,
            "err": 18,
            "duration_s": 412.5,
            "reason": None,
        },
        "last_cycle_start_ts": _t,
        "next_run_eta_s": 3600,
        "redis_available": True,
    }
    r = client.get("/api/v1/admin/lifespan-warmup")
    data = r.json()
    # 3600 - 3000 = 600, 允许 ±5
    assert 595 <= data["next_run_eta_s"] <= 605


def test_lifespan_warmup_next_run_eta_clamped_to_zero(admin_client):
    """已过 1h+ → next_run_eta_s = 0 (下一轮已在跑)."""
    client, app = admin_client
    _t = time.time() - 4000  # 67min 前
    app.state.nav_warmup = {
        "enabled": True,
        "started_at": _t - 60,
        "warmup_period_s": 3600,
        "first_run_delay_s": 60,
        "last_cycle": {
            "ts": "2026-08-29T10:01:00Z",
            "cycle": 1,
            "total": 1618,
            "ok": 1500,
            "skip": 100,
            "err": 18,
            "duration_s": 412.5,
            "reason": None,
        },
        "last_cycle_start_ts": _t,
        "next_run_eta_s": 3600,
        "redis_available": True,
    }
    r = client.get("/api/v1/admin/lifespan-warmup")
    data = r.json()
    assert data["next_run_eta_s"] == 0
