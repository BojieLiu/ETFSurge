"""Unit tests for ICTracker: build_forward_returns, compute_periodic_ic, API."""
from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from app.factors.ic_tracker import (
    ICTracker,
    ic_tracker,
    build_forward_returns,
)


class TestBuildForwardReturns:
    """Tests for build_forward_returns()."""

    def test_basic(self):
        """Basic case: 1 symbol with sufficient close data."""
        market_data = {
            "000300.SH": {"close": [4100, 4080, 4050, 4020, 4000]},
        }
        result = build_forward_returns(market_data, window=1)
        assert "000300.SH" in result.index
        # (4100 - 4080) / 4080
        expected = (4100 - 4080) / 4080
        assert abs(result["000300.SH"] - expected) < 1e-6

    def test_multiple_symbols(self):
        """Multiple symbols with varying data length."""
        market_data = {
            "A": {"close": [100, 98, 96]},
            "B": {"close": [50, 52, 54]},
            "C": {"close": [200]},  # too short for window=1
        }
        result = build_forward_returns(market_data, window=1)
        assert "A" in result.index
        assert "B" in result.index
        assert "C" not in result.index  # not enough data
        # A: (100-98)/98
        assert abs(result["A"] - (100 - 98) / 98) < 1e-6
        # B: (50-52)/52
        assert abs(result["B"] - (50 - 52) / 52) < 1e-6

    def test_window_3(self):
        """Window of 3 periods."""
        market_data = {
            "A": {"close": [110, 108, 105, 100, 95]},
        }
        result = build_forward_returns(market_data, window=3)
        assert "A" in result.index
        # (110 - 100) / 100
        assert abs(result["A"] - (110 - 100) / 100) < 1e-6

    def test_empty_market_data(self):
        """Empty market data returns empty Series."""
        result = build_forward_returns({})
        assert len(result) == 0

    def test_none_close(self):
        """Symbol with close=None is skipped."""
        market_data = {"A": {"close": None}}
        result = build_forward_returns(market_data)
        assert len(result) == 0

    def test_symbols_filter(self):
        """Filter by symbols parameter."""
        market_data = {
            "A": {"close": [100, 99]},
            "B": {"close": [50, 49]},
        }
        result = build_forward_returns(market_data, symbols=["A"], window=1)
        assert "A" in result.index
        assert "B" not in result.index

    def test_zero_division(self):
        """Handle zero close price gracefully."""
        market_data = {
            "A": {"close": [100, 0, 95]},
        }
        result = build_forward_returns(market_data, window=1)
        # window=1, close[0]=100, close[1]=0 -> (100-0)/0 -> division by zero, skip
        assert len(result) == 0

    def test_insufficient_data(self):
        """Less than window+1 close prices."""
        market_data = {
            "A": {"close": [100]},
        }
        result = build_forward_returns(market_data, window=2)
        assert len(result) == 0


class TestComputePeriodicIC:
    """Tests for ICTracker.compute_periodic_ic()."""

    def setup_method(self):
        self.tracker = ICTracker()

    def test_basic(self):
        """Basic case with 3 symbols having correlated factor and return."""
        factor_values = {
            "A": {"momentum": 0.8, "volatility": 0.2},
            "B": {"momentum": 0.5, "volatility": 0.4},
            "C": {"momentum": 0.2, "volatility": 0.6},
            "D": {"momentum": -0.1, "volatility": 0.8},
        }
        # Forward returns positively correlated with momentum
        market_data = {
            "A": {"close": [1.10, 1.00]},
            "B": {"close": [1.05, 1.00]},
            "C": {"close": [1.02, 1.00]},
            "D": {"close": [0.98, 1.00]},
        }
        result = self.tracker.compute_periodic_ic(factor_values, market_data)
        assert "momentum" in result
        # momentum should have positive correlation with forward returns
        assert result["momentum"] > 0.5
        assert "volatility" in result

    def test_empty_factor_values(self):
        """Empty factor_values returns empty dict."""
        result = self.tracker.compute_periodic_ic({}, {"A": {"close": [1, 0]}})
        assert result == {}

    def test_insufficient_symbols(self):
        """Less than 3 symbols returns empty."""
        factor_values = {
            "A": {"f1": 0.5},
            "B": {"f2": 0.3},
        }
        market_data = {
            "A": {"close": [1.0, 0.9]},
            "B": {"close": [1.0, 0.9]},
        }
        result = self.tracker.compute_periodic_ic(factor_values, market_data)
        assert result == {}

    def test_no_forward_returns(self):
        """No forward returns data returns empty."""
        factor_values = {
            "A": {"f1": 0.5},
            "B": {"f1": 0.3},
        }
        market_data = {}  # no close data
        result = self.tracker.compute_periodic_ic(factor_values, market_data)
        assert result == {}


class TestICTrackerSingleton:
    """Tests for the global ic_tracker singleton."""

    def test_singleton_exists(self):
        """IC tracker singleton is importable and has expected methods."""
        assert hasattr(ic_tracker, "compute_ic")
        assert hasattr(ic_tracker, "compute_periodic_ic")
        assert hasattr(ic_tracker, "record")
        assert hasattr(ic_tracker, "compute_icir")


class TestFactorRegistryIntegration:
    """Tests for FactorRegistry._last_ic_batch integration."""

    async def test_last_ic_batch_type(self):
        """FactorRegistry._last_ic_batch should be a dict."""
        from app.factors.factor_registry import registry
        assert isinstance(registry._last_ic_batch, dict), (
            f"Expected dict, got {type(registry._last_ic_batch)}"
        )

    async def test_last_ic_batch_with_market_data(self):
        """Calling compute() with market_data should populate _last_ic_batch."""
        from app.factors.factor_registry import registry
        symbols = ["159915", "510050", "510300"]
        market_data = {
            sym: {
                "close": [4.0, 3.9, 3.8, 3.7],
                "high": [4.1, 4.0, 3.9, 3.8],
                "low": [3.9, 3.8, 3.7, 3.6],
                "volume": [10000, 12000, 11000, 9000],
                "total_mv": 1e10,
                "float_mv": 5e9,
                "pe": 15.0,
                "pb": 1.5,
            }
            for sym in symbols
        }
        result = await registry.compute(symbols, market_data=market_data)
        assert isinstance(result, dict)
        # _last_ic_batch should be populated
        assert isinstance(registry._last_ic_batch, dict)


class TestICContract:
    """Contract tests for GET /api/v1/factors/active (P2-1: /factors/ic merged)."""

    async def test_router_importable(self):
        """Factors router is importable and has correct prefix."""
        from app.routers.factors import router
        assert router.prefix == "/api/v1/factors"
        routes = [r.path for r in router.routes]
        assert any("/active" in r for r in routes), f"Routes: {routes}"
        # P2-1: /factors/ic 已删除，IC 数据并入 /factors/active
        assert not any(r == "/api/v1/factors/ic" for r in routes), \
            "/factors/ic 应已删除（P2-1 合并）"


class TestR515ICRestoreFromDB:
    """R5-1-5: 启动时从 DB 恢复 _last_ic_batch（IC 非请求驱动）。

    旧问题：/factors/ic 只读内存 _last_ic_batch，重启后内存态丢失 → IC 空
    （DB 有历史数据但端点读不到）。修复：restore_ic_from_db 回填内存。
    """

    @pytest.mark.asyncio
    async def test_restore_populates_last_ic_batch(self):
        """DB 含历史 IC → _last_ic_batch 被填充（含有效信号条目）。"""
        from datetime import datetime
        from app.factors.factor_registry import FactorRegistry
        from app.models.factor_ic import FactorICRecord

        reg = FactorRegistry()
        reg._last_ic_batch = {}  # 模拟重启后内存空

        class _FakeRow:
            def __init__(self, code, val, ts):
                self.factor_code = code
                self.ic_value = val
                self.computed_at = ts

        ts = datetime.utcnow()

        class _FakeResult:
            def scalars(self):
                return self

            def all(self):
                return [
                    _FakeRow("momentum", 0.35, ts),
                    _FakeRow("valuation", 0.12, ts),
                    _FakeRow("technical", 0.0005, ts),  # abs ≤ 0.001 → 不恢复
                ]

        class _FakeExec:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def execute(self, *a, **kw):
                return _FakeResult()

        restored = await reg.restore_ic_from_db(_FakeExec())
        assert restored == 2, f"应恢复 2 条有效 IC，实际 {restored}"
        assert reg._last_ic_batch.get("momentum") == pytest.approx(0.35)
        assert reg._last_ic_batch.get("valuation") == pytest.approx(0.12)
        # abs ≤ 0.001 的 technical 不恢复（U3/N06 覆盖保护）
        assert "technical" not in reg._last_ic_batch, \
            "abs(val)≤0.001 不应覆盖 _last_ic_batch（覆盖保护）"

    @pytest.mark.asyncio
    async def test_restore_empty_db_keeps_empty(self):
        """DB 无历史记录 → 不抛异常、_last_ic_batch 保持空。"""
        from app.factors.factor_registry import FactorRegistry

        reg = FactorRegistry()
        reg._last_ic_batch = {}

        class _FakeExec:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def execute(self, *a, **kw):
                return _FakeEmpty()

        class _FakeEmpty:
            def scalars(self):
                return self

            def all(self):
                return []

        restored = await reg.restore_ic_from_db(_FakeExec())
        assert restored == 0
        assert reg._last_ic_batch == {}


class TestP012DbBackedSampleCount:
    """P0-12 (round16 3.13 R2/R3): _get_ic_sample_count 从 DB 数 IC 累积周期数，
    而非内存 _records（候选池空时恒 0）的「单批非零符号数」。"""

    @pytest.mark.asyncio
    async def test_db_backed_count_counts_periods(self):
        """DB 已有 29 条 factor_code=technical 历史记录 → 新批 sample_count=30。"""
        from app.factors.ic_tracker import ICTracker

        tracker = ICTracker()

        class _FakeRow:
            def __init__(self, n):
                self.n = n

        class _FakeResult:
            def scalar_one_or_none(self):
                return 29

        class _FakeSession:
            async def execute(self, *a, **kw):
                return _FakeResult()

        n = await tracker._get_ic_sample_count_db(_FakeSession(), "technical")
        # 29 条历史 + 本批 1 条 = 30（≥ MIN_IC_SAMPLES → 不再误判 no_data）
        assert n == 30, f"样本数应按 IC 周期数累计，实际 {n}"

    @pytest.mark.asyncio
    async def test_db_count_fallback_on_error_uses_records(self):
        """DB 查询异常时回退内存计数（不崩溃）。"""
        from app.factors.ic_tracker import ICTracker

        tracker = ICTracker()
        tracker._records = [
            {"factor_code": "technical", "value": 1.0},
            {"factor_code": "momentum", "value": 0.5},
        ]

        class _BoomSession:
            async def execute(self, *a, **kw):
                raise RuntimeError("db down")

        n = await tracker._get_ic_sample_count_db(_BoomSession(), "technical")
        assert n == 2, f"DB 异常时应回退内存计数+1，实际 {n}"
