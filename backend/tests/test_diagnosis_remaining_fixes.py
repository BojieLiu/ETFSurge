"""Tests for remaining items from comprehensive-diagnosis-and-optimization-plan.

Covers three fixes that were identified in the Phase 20 diagnosis:
  1. Bollinger Bands column name mismatch (P0) — BBB_20_2_2 vs BBB_20_2.0_2.0
  2. Sector default limit (P1) — 80 → 500 for industry/concept
  3. ic_tracker._get_ic_sample_count type error (P1) — list[dict] indexed by str

Each test verifies the fix before landing, per TDD discipline.
"""

import pytest
import pandas as pd
import numpy as np

from app.analysis.indicators import compute_bollinger
from app.factors.ic_tracker import ICTracker


# =============================================================================
# 1. 布林带列名格式修复验证 (P0)
# =============================================================================

class TestBollingerBandwidthFix:
    """Verify compute_bollinger returns non-zero values with sufficient data.

    The root cause was a column-name format mismatch: pandas-ta 0.7+ stores
    std as float (BBB_20_2.0_2.0) while the old code constructed integer keys
    (BBB_20_2_2), causing all four band values to silently default to 0.
    """

    def test_bandwidth_is_positive_with_60_points(self):
        """60 data points > 20 window → bandwidth must be > 0."""
        np.random.seed(42)
        close = pd.Series(np.random.randn(60).cumsum() + 100)
        result = compute_bollinger(close, window=20, num_std=2)
        assert result["bandwidth"] > 0, (
            f"Expected positive bandwidth, got {result['bandwidth']}\n"
            f"  ma={result['ma']} upper={result['upper']} lower={result['lower']}\n"
            "This likely means the column-name prefix lookup still fails."
        )

    def test_bandwidth_nonzero_in_upper_lower_spread(self):
        """upper > ma > lower when data is sufficient."""
        np.random.seed(42)
        close = pd.Series(np.random.randn(60).cumsum() + 100)
        result = compute_bollinger(close, window=20, num_std=2)
        assert result["upper"] > result["ma"] > result["lower"], (
            f"Expected upper > ma > lower, got u={result['upper']} "
            f"m={result['ma']} l={result['lower']}"
        )
        # Also verify these are not the default 0 sentinels
        assert result["upper"] != 0
        assert result["ma"] != 0
        assert result["lower"] != 0

    def test_non_default_window_and_std(self):
        """Different window/num_std must still produce valid results."""
        np.random.seed(42)
        close = pd.Series(np.random.randn(100).cumsum() + 100)
        result = compute_bollinger(close, window=10, num_std=1.5)
        assert result["bandwidth"] > 0, f"bandwidth={result['bandwidth']} with window=10, std=1.5"
        assert result["upper"] > result["ma"] > result["lower"]

    def test_empty_series_still_returns_defaults(self):
        """Empty series must still return all-zero sentinels."""
        result = compute_bollinger(pd.Series([]))
        assert result["ma"] == 0
        assert result["upper"] == 0
        assert result["lower"] == 0
        assert result["bandwidth"] == 0


# =============================================================================
# 2. ic_tracker._get_ic_sample_count 类型错误修复验证 (P1)
# =============================================================================

class TestICTrackerSampleCountFix:
    """Verify _get_ic_sample_count works with list[dict] records.

    The original code treated self._records (list[dict]) as a dict,
    using 'factor_code not in self._records' (always True for str in list[dict])
    and 'self._records[factor_code]' (TypeError: list indices must be ints).
    """

    def test_sample_count_after_record(self):
        """After recording one symbol, count should be 1."""
        tracker = ICTracker()
        tracker.record("510300", "momentum_20d", 0.5)
        assert tracker._get_ic_sample_count("momentum_20d") == 1

    def test_sample_count_multiple_symbols(self):
        """Multiple records for the same factor."""
        tracker = ICTracker()
        for sym in ["510300", "518880", "513080"]:
            tracker.record(sym, "momentum_20d", 0.5)
        assert tracker._get_ic_sample_count("momentum_20d") == 3

    def test_sample_count_different_factors(self):
        """Records for different factors are counted independently."""
        tracker = ICTracker()
        tracker.record("510300", "momentum_20d", 0.5)
        tracker.record("518880", "volatility_20d", -0.3)
        tracker.record("513080", "momentum_20d", 0.1)
        assert tracker._get_ic_sample_count("momentum_20d") == 2
        assert tracker._get_ic_sample_count("volatility_20d") == 1

    def test_sample_count_empty(self):
        """No records for a factor returns 0."""
        tracker = ICTracker()
        assert tracker._get_ic_sample_count("nonexistent_factor") == 0

    def test_sample_count_no_crash_with_str_index(self):
        """The old code would crash on 'factor_code not in self._records' (list).
        Verify this no longer happens by calling with any factor_code."""
        tracker = ICTracker()
        tracker.record("510300", "some_factor", 0.5)
        # This should not raise TypeError
        count = tracker._get_ic_sample_count("some_factor")
        assert count == 1


# =============================================================================
# 3. API 契约测试：板块默认限额 (P1)
# =============================================================================

class TestSectorDefaultLimit:
    """Verify the sector API default limit was raised from 80 to 500.

    We test this via the route definition by importing the handler functions.
    """

    @staticmethod
    def _get_limit_default(func) -> int:
        """Extract the default value from a FastAPI Query parameter."""
        import inspect
        sig = inspect.signature(func)
        param = sig.parameters.get("limit")
        assert param is not None, f"{func.__name__} has no 'limit' parameter"
        default = param.default
        # FastAPI Query wraps the default; try accessing .default attribute
        if hasattr(default, "default"):
            return default.default
        return default

    def test_industry_sector_default_not_80(self):
        """Default limit must no longer be 80 (it should be >= 300)."""
        from app.routers.market import industry_sectors
        limit_default = self._get_limit_default(industry_sectors)
        assert limit_default > 80, f"industry_sectors default limit still {limit_default}, expected > 80"
        assert limit_default == 500, f"industry_sectors default limit should be 500, got {limit_default}"

    def test_concept_sector_default_not_80(self):
        """Default limit must no longer be 80 (it should be >= 300)."""
        from app.routers.market import concept_sectors
        limit_default = self._get_limit_default(concept_sectors)
        assert limit_default > 80, f"concept_sectors default limit still {limit_default}, expected > 80"
        assert limit_default == 500, f"concept_sectors default limit should be 500, got {limit_default}"
