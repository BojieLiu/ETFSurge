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
