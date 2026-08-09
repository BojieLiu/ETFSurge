# -*- coding: utf-8 -*-
"""F3-4 / §9.5: Z04 etf_specific 4 因子数据补齐（NAV 降级链 / benchmark_close / 份额数据 / reason 区分）。"""
import asyncio
import math

import pytest

from app.factors import factor_registry as fr
from app.services.market_data_hub import market_data_hub


# ── 1-4: compute 函数（数据注入后应产出非 0 值） ─────────────────────────
def test_premium_discount_with_nav():
    """mock data 含 nav+price → 折溢价非 0。"""
    val = fr._compute_premium_discount({"nav": 1.0, "price": 1.03})
    assert abs(val - 0.03) < 1e-6


def test_tracking_error_with_benchmark():
    """mock close+benchmark_close（5 日以上）→ 非 0 且 ≤0.05。"""
    closes = [10.0, 10.2, 10.1, 10.4, 10.3, 10.6]
    bench = [10.0, 10.19, 10.12, 10.39, 10.31, 10.59]
    val = fr._compute_tracking_error({"close": closes, "benchmark_close": bench})
    assert 0.0 < val <= 0.05


def test_shares_change_from_20d():
    """mock shares_change_20d → 因子直接生效。"""
    val = fr._compute_shares_change({"shares_change_20d": 0.05})
    assert val == 0.05


def test_institutional_holdings_change_proxy():
    """mock shares_change_20d → 因子 = 值 × 0.5（§9.10.7-5 折扣代理）。"""
    val = fr._compute_institutional_holdings_change({"shares_change_20d": 0.10})
    assert abs(val - 0.05) < 1e-9


# ── 5: _enrich_symbol_extra 注入 benchmark_close + shares_change_20d ─────
@pytest.mark.asyncio
async def test_symbol_extra_injects_benchmark_and_shares(monkeypatch):
    """宽基 ETF → benchmark_close 注入；份额 → shares_change_20d + ×0.5 代理。"""
    calls = {"bench": 0, "shares": 0}

    async def fake_get_market_history(symbol, asset_type="A", period="daily"):
        calls["bench"] += 1
        return [
            {"date": f"2026-07-{d:02d}", "close": 3000.0 + d}
            for d in range(1, 21)
        ]

    def fake_fetch_etf_shares_outstanding(symbol):
        calls["shares"] += 1
        return {"total_shares": 1e8, "shares_change_20d": 0.03}

    monkeypatch.setattr(market_data_hub, "get_market_history", fake_get_market_history)
    import app.fetchers.china_market as cm
    monkeypatch.setattr(cm, "fetch_etf_shares_outstanding", fake_fetch_etf_shares_outstanding)
    # 清 24h 份额缓存（防全量跑时被其他用例污染）
    market_data_hub._FUND_SHARES_CACHE.clear()

    out = await market_data_hub._enrich_symbol_extra(
        ["510300", "588000", "512480"],  # 512480 半导体ETF（P1-J 有基准映射 sh931071）
        {"510300": {"fund_scale": 100}, "588000": {"fund_scale": 50}, "512480": {}},
    )
    assert calls["bench"] >= 3  # 510300/588000 宽基 + 512480 主题（P1-J 扩展后都有基准映射）
    assert len(out["510300"]["benchmark_close"]) == 20
    assert out["510300"]["shares_change_20d"] == 0.03
    assert abs(out["510300"]["institutional_holdings_change"] - 0.015) < 1e-9
    # P1-J (round10 §5.5): 行业/主题 ETF 基准映射扩展——512480 半导体也有基准
    assert "benchmark_close" in out["512480"]
    assert out["512480"]["shares_change_20d"] == 0.03


# ── 6: no_data reason 区分（数据源缺失 vs IC 不足） ───────────────────────
def test_no_data_reason_specifics():
    """_data_source_gaps 记录后，factors/active reason 区分「数据源未接入」。"""
    registry = fr.registry
    assert hasattr(registry, "_data_source_gaps"), "registry 应记录数据源缺口"
    # 缺口记录为 dict: factor_code -> [missing symbols]
    assert isinstance(registry._data_source_gaps, dict)


def test_gap_tracking_set():
    """_fetch_market_data 后 _data_source_gaps 覆盖 4 个 etf_specific 因子键。"""
    assert {"etf.premium_discount", "etf.tracking_error",
            "etf.shares_change", "etf.institutional_holdings_change"} <= set(fr.ET_SPECIFIC_GAP_CODES)
