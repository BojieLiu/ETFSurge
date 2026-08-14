# -*- coding: utf-8 -*-
"""T6: 数据源熔断演练 — 强制 mootdx 熔断态下，A 股降级链（tencent/sina）输出非空。"""
import time

import pytest

from app.fetchers import china_market as cm
from app.core.source_registry import registry


@pytest.fixture(autouse=True)
def _restore_mootdx():
    h = registry.health("mootdx")
    _saved = h._cool_until
    yield
    h._cool_until = _saved


def test_circuit_trip_mootdx_degradation_serves(monkeypatch):
    """T6: mootdx 熔断 → registry.route 跳过 mootdx → tencent 降级输出非空。"""
    h = registry.health("mootdx")
    h._cool_until = time.time() + 3600  # 强制熔断 1h

    def boom(symbols):
        raise AssertionError("mootdx 不应被执行（熔断态应被 route 跳过）")

    def fake_tencent(symbols, asset_type="A"):
        return [{"symbol": "600519", "price": 1500.0, "change_pct": 1.0}]

    monkeypatch.setattr(cm, "_mootdx_realtime", boom)
    monkeypatch.setattr(cm, "_tencent_realtime", fake_tencent)

    rows = cm.fetch_a_stock_realtime("600519")
    # 降级链输出非空（tencent 命中）
    assert rows, "熔断态下降级链输出为空"
    assert rows[0]["price"] == 1500.0
    # mootdx 处于熔断态（不可用）
    assert not h.available(time.time())


def test_circuit_trip_batch_degradation_serves(monkeypatch):
    """T6: 批量版同样熔断短路 → tencent 降级。"""
    h = registry.health("mootdx")
    h._cool_until = time.time() + 3600

    def boom(symbols):
        raise AssertionError("mootdx 不应被执行")

    def fake_tencent(symbols, asset_type="A"):
        return [{"symbol": "600519", "price": 1500.0, "change_pct": 1.0}]

    monkeypatch.setattr(cm, "_mootdx_realtime", boom)
    monkeypatch.setattr(cm, "_tencent_realtime", fake_tencent)

    rows = cm.fetch_a_stock_batch(["600519"])
    assert rows and rows[0]["price"] == 1500.0


def test_circuit_recovery_after_cooldown(monkeypatch):
    """T6: 冷却期结束后 mootdx 恢复可用（熔断自愈）。"""
    h = registry.health("mootdx")
    h._cool_until = time.time() - 1  # 冷却已过

    called = {"mootdx": False}

    def fake_mootdx(symbols):
        called["mootdx"] = True
        return [{"symbol": "600519", "price": 1499.0, "change_pct": 0.5}]

    def fake_tencent(symbols, asset_type="A"):
        return [{"symbol": "600519", "price": 1500.0, "change_pct": 1.0}]

    monkeypatch.setattr(cm, "_mootdx_realtime", fake_mootdx)
    monkeypatch.setattr(cm, "_tencent_realtime", fake_tencent)

    rows = cm.fetch_a_stock_realtime("600519")
    assert called["mootdx"], "冷却恢复后应优先走 mootdx"
    assert rows[0]["price"] == 1499.0
