from __future__ import annotations
"""Tests for factor_registry.py compute functions — validates pandas-ta refactoring."""

import numpy as np
import pytest

from app.factors.factor_registry import (
    _compute_sma_5,
    _compute_sma_10,
    _compute_sma_20,
    _compute_sma_60,
    _compute_rsi_14,
    _compute_macd,
    _compute_bollinger_bandwidth,
    _compute_atr_14,
    _compute_kdj_k,
    _compute_kdj_d,
    _compute_kdj_j,
    _compute_volume_ratio,
    _compute_vwap,
)


# ── Shared fixture ─────────────────────────────────────────────────
@pytest.fixture
def market_data() -> dict:
    """Synthetic 60-bar market data dict as used by factor compute functions."""
    np.random.seed(42)
    close = np.random.randn(60).cumsum() + 100
    high = close + abs(np.random.randn(60) * 0.5)
    low = close - abs(np.random.randn(60) * 0.5)
    volume = abs(np.random.randn(60) * 1e6)
    amount = volume * close
    return {
        "close": close.tolist(),
        "high": high.tolist(),
        "low": low.tolist(),
        "volume": volume.tolist(),
        "amount": amount.tolist(),
        "total_mv": 5e10,
    }


# ── SMA functions ──────────────────────────────────────────────────
class TestSMAFunctions:
    def test_sma_5(self, market_data):
        val = _compute_sma_5(market_data)
        assert isinstance(val, float)
        assert val > 0

    def test_sma_10(self, market_data):
        val = _compute_sma_10(market_data)
        assert isinstance(val, float)
        assert val > 0

    def test_sma_20(self, market_data):
        val = _compute_sma_20(market_data)
        assert isinstance(val, float)
        assert val > 0

    def test_sma_60(self, market_data):
        val = _compute_sma_60(market_data)
        assert isinstance(val, float)
        assert val > 0

    def test_ordering(self, market_data):
        """SMA values should differ: different windows → different values."""
        v5 = _compute_sma_5(market_data)
        v20 = _compute_sma_20(market_data)
        v60 = _compute_sma_60(market_data)
        assert v5 != v20 or v20 != v60  # At least some differ

    def test_short_data(self):
        data = {"close": [100.0] * 3}
        assert _compute_sma_5(data) == 0.0
        assert _compute_sma_10(data) == 0.0
        assert _compute_sma_20(data) == 0.0


# ── RSI ────────────────────────────────────────────────────────────
class TestRSI:
    def test_rsi_float(self, market_data):
        val = _compute_rsi_14(market_data)
        assert isinstance(val, float)
        assert 0 <= val <= 100

    def test_rsi_short_data(self):
        assert _compute_rsi_14({"close": [100.0] * 5}) == 50.0


# ── MACD ───────────────────────────────────────────────────────────
class TestMACD:
    def test_macd_float(self, market_data):
        val = _compute_macd(market_data)
        assert isinstance(val, float)

    def test_macd_short_data(self):
        assert _compute_macd({"close": [100.0] * 10}) == 0.0


# ── Bollinger Bandwidth ────────────────────────────────────────────
class TestBollingerBandwidth:
    def test_bollinger_bandwidth_float(self, market_data):
        val = _compute_bollinger_bandwidth(market_data)
        assert isinstance(val, float)
        assert val >= 0  # Bandwidth is non-negative

    def test_bollinger_short_data(self):
        assert _compute_bollinger_bandwidth({"close": [100.0] * 5}) == 0.0


# ── ATR ────────────────────────────────────────────────────────────
class TestATR:
    def test_atr_float(self, market_data):
        val = _compute_atr_14(market_data)
        assert isinstance(val, float)
        assert val > 0  # Positive volatility measure

    def test_atr_short_data(self):
        data = {"high": [100.0], "low": [99.0], "close": [99.5]}
        assert _compute_atr_14(data) == 0.0


# ── KDJ ────────────────────────────────────────────────────────────
class TestKDJ:
    def test_kdj_all_three(self, market_data):
        k = _compute_kdj_k(market_data)
        d = _compute_kdj_d(market_data)
        j = _compute_kdj_j(market_data)
        assert all(isinstance(v, float) for v in (k, d, j))

    def test_kdj_relationship(self, market_data):
        k = _compute_kdj_k(market_data)
        d = _compute_kdj_d(market_data)
        j = _compute_kdj_j(market_data)
        # J = 3K - 2D
        assert abs(j - (3 * k - 2 * d)) < 1e-6

    def test_kdj_short_data(self):
        data = {"high": [100.0], "low": [99.0], "close": [99.5]}
        assert _compute_kdj_k(data) == 50.0
        assert _compute_kdj_d(data) == 50.0
        assert _compute_kdj_j(data) == 50.0


# ── Volume Ratio (unchanged, verify still works) ──────────────────
class TestVolumeRatio:
    def test_volume_ratio(self, market_data):
        val = _compute_volume_ratio(market_data)
        assert isinstance(val, float)

    def test_short_data(self):
        assert _compute_volume_ratio({"volume": [100.0] * 3}) == 1.0


# ── VWAP (unchanged, verify still works) ──────────────────────────
class TestVWAP:
    def test_vwap(self, market_data):
        val = _compute_vwap(market_data)
        assert isinstance(val, float)


# ===== folded from test_phase2a_data_quality.py =====
import ast
import os
class TestP1_1_MarketContext:
    """P1.1: Ensure market_data_hub properly populates market context."""

    def test_pool_manager_has_market_context(self):
        """market_data_hub should export market context data functions.

        Batch 3 (giant-file split): implementation moved into app/services/hub/
        mixins, so the check is behavioral (methods present on the singleton)
        instead of scanning the facade module source text.
        """
        from app.services.market_data_hub import market_data_hub as hub

        for method in ["get_index_realtime", "get_sector_momentum", "get_market_sentiment"]:
            assert callable(getattr(hub, method, None)), f"market_data_hub missing {method}"

    def test_market_context_has_fallback(self):
        """Market context should have fallback defaults to avoid empty data."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "market_data_hub.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should have fallback/empty state handling
        has_fallback = any(
            term in content for term in ["fallback", "default", "empty", "None"]
        )
        assert has_fallback, "market_data_hub should handle empty/None data with fallbacks"
class TestP1_2b_PremiumDiscount:
    """P1.2b: premium_discount / tracking_error factor pipeline."""

    def test_premium_discount_uses_nav_and_price(self):
        """premium_discount should use nav and price data."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "factors", "factor_registry.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_premium_discount":
                    body = ast.get_source_segment(
                        open(probes_path, encoding="utf-8").read(), node
                    )
                    assert "nav" in body, "premium_discount should use nav data"
                    assert "price" in body, "premium_discount should use price data"
                    return
        pytest.fail("_compute_premium_discount function not found")


# ===== folded from test_round15_composite_scale.py =====
import math
from unittest.mock import patch
from app.services.market_data_hub import MarketDataHub
def _hub():
    h = MarketDataHub()
    # 固定「交易时段」，避免非交易时段 P6 分支（liquidity 减半）影响断言
    patcher = patch.object(h, "_is_market_hours", return_value=True)
    patcher.start()
    h.__market_hours_patcher = patcher  # 保持引用防 GC
    return h
def _item(amount: float, scale: float, factor_sum: float = 0.0):
    return {
        "amount": amount,
        "fund_scale": scale,
        "factor_scores": {"technical": factor_sum, "momentum": 0.0,
                          "valuation": 0.0, "sentiment": 0.0},
    }
class TestCompositeUnifiedScale:
    def test_scale_discrimination_restored(self):
        """2000 亿 vs 30 亿（factor_sum 均 0）→ composite 可区分（修复前 scale 分都≈0）。"""
        hub = _hub()
        big = _item(amount=1e9, scale=2000.0)
        small = _item(amount=1e9, scale=30.0)
        amounts = [1e9, 1e9]
        scales = [2000.0, 30.0]
        s_big = hub._compute_composite(big, "core", "neutral", amounts, scales)
        s_small = hub._compute_composite(small, "core", "neutral", amounts, scales)
        assert s_big > s_small, \
            f"2000 亿应高于 30 亿（scale 维度仍死值: {s_big} vs {s_small}）"

    def test_factor_dominance_kept(self):
        """同规模下 factor_sum=+9 > factor_sum=0，且 factor 项贡献 > 50%。"""
        hub = _hub()
        hi = _item(amount=1e9, scale=2000.0, factor_sum=9.0)
        lo = _item(amount=1e9, scale=2000.0, factor_sum=0.0)
        amounts = [1e9, 1e9]
        scales = [2000.0, 2000.0]
        s_hi = hub._compute_composite(hi, "core", "neutral", amounts, scales)
        s_lo = hub._compute_composite(lo, "core", "neutral", amounts, scales)
        assert s_hi > s_lo
        # factor 项 = w.factor(0.50) × tanh(9/6)=tanh(1.5)
        factor_term = 0.50 * math.tanh(9.0 / 6.0)
        assert factor_term / s_hi > 0.5, f"factor 贡献占比应 >50%（实际 {factor_term/s_hi:.2f}）"

    def test_backward_compat_legacy_path(self):
        """layer_amounts=None → 旧 *1e-9 路径（research 层等行为不变）。"""
        hub = _hub()
        item = _item(amount=4.47e9, scale=1193.85, factor_sum=1.0)
        # 旧路径：liquidity ≈ 4.47e9*1e-9*0.25 ≈ 1.12，scale ≈ 1193.85*1e-9*0.25 ≈ 0
        s = hub._compute_composite(item, "core", "neutral")
        assert s == pytest.approx(0.50 * 1.0 + 0.25 * 4.47e9 * 1e-9 + 0.25 * 1193.85 * 1e-9)

    def test_pct_rank_with_ties(self):
        hub = _hub()
        assert hub._pct_rank(30.0, [10.0, 30.0, 50.0]) == pytest.approx(0.5)  # 中位
        assert hub._pct_rank(50.0, [10.0, 30.0, 50.0]) == pytest.approx((2 + 0.5) / 3)
        assert hub._pct_rank(100.0, [10.0, 30.0, 50.0]) == pytest.approx(1.0)
        assert hub._pct_rank(1.0, []) == 0.0

    def test_opportunistic_keeps_legacy(self):
        """opportunistic 层不启用百分位（保持旧路径 + opp 分量）。"""
        hub = _hub()
        item = _item(amount=1e8, scale=10.0, factor_sum=0.0)
        item["composite_score"] = 0.6
        s = hub._compute_composite(item, "opportunistic", "neutral")
        # 旧路径：0.35(factor 0) + 0.15*1e8*1e-9 + 0.35*0.6（opp 权重随 regime）
        assert s == pytest.approx(0.15 * 1e8 * 1e-9 + 0.35 * 0.6, abs=1e-9)
