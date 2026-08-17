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
    而非内存 _records（候选池空时恒 0）的「单批非零符号数」。

    F25① (round23 §8): 周期数语义由 `count(*)`（刷新次数，240× 虚高）改为
    `count(distinct trade_date)`（日频交易日数）——不再 +1（upsert 本批不新增行）。"""

    @pytest.mark.asyncio
    async def test_db_backed_count_counts_distinct_dates(self):
        """DB 已有 29 个不同交易日 → sample_count=29（distinct date，非 count(*)+1）。"""
        from app.factors.ic_tracker import ICTracker

        tracker = ICTracker()

        class _FakeResult:
            def scalar_one_or_none(self):
                return 29

        class _FakeSession:
            async def execute(self, *a, **kw):
                return _FakeResult()

        n = await tracker._get_ic_sample_count_db(_FakeSession(), "technical")
        # F25①: distinct trade_date 计数，不再 +1（旧实现把本批刚插入行也算进去）
        assert n == 29, f"样本数应按日频交易日数累计，实际 {n}"

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
        assert n == 1, f"DB 异常时应回退内存计数，实际 {n}"


# ── folded from test_round27_r55_ic_backfill.py ──
"""
R55 (round27-reacceptance §2.11 / §15.1): 因子模型页 27 因子恒 no_data —— IC 历史回填。

根因：IC 由 `_ic_persistence_loop` 增量计算（`save_ic_batch_to_db` 用 `_beijing_today()`
打当天日期），fresh 库仅 3 个 distinct trade_date → 所有因子 sample_count=3 < 250 →
恒 no_data。修复 = `ICTracker.backfill_ic_history` 一次性批量回填历史截面 IC。

本测试（TDD，先写失败断言后实现）：
1. 回填后 factor_ic_records distinct trade_date ≥ 230（~240 交易日 K 线），
   且 `_status_of` 对回填后样本返回「可观察」（含"可观察"字样），而非"积累中 <60"。
2. 负向（诚实）：无回填时 `_status_of` 对任意 sample<250 不得谎报 "valid"。
3. 回填是一次性批量计算、无请求路径 IO：单个 backfill 调用产出全部日样本；
   命中 /factors/active 端点不触发 backfill（per-request 不回填）。

验证边界（D3）：本测试用内存 SQLite + 注入数据，不依赖真实行情时段。
"""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.factors.ic_tracker import ICTracker
from app.models.factor_ic import FactorICRecord
from app.routers.factors import MIN_TRADING_DAYS, _status_of


@pytest.fixture
async def ic_db():
    """独立 SQLite 内存库（StaticPool 共享单连接），仅建 factor_ic_records 表。"""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"timeout": 30},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[FactorICRecord.__table__])
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _make_kline_and_scores(n_days: int = 240, n_symbols: int = 10):
    """构造 n_days 交易日 K 线（时序升序）+ 注入的历史因子分。

    - kline: {symbol: {"close":[升序收盘价], "dates":[升序日期]}}
    - factor_scores_by_index: {i: {symbol: {code: val}}} 截至第 i 日因子分
    因子值与收益均带跨标的差异（非常量），保证 compute_periodic_ic 产 IC（含近零→signal_absent 仍落库）。
    """
    import random
    rng = random.Random(20260816)
    symbols = [f"ETF{j:03d}" for j in range(n_symbols)]
    codes = ["technical.ma.sma_5", "technical.rsi.rsi_14", "momentum.return_20d"]
    base = date(2026, 8, 14)
    dates = [base - timedelta(days=(n_days - 1 - k)) for k in range(n_days)]

    kline: dict[str, dict] = {}
    factor_scores_by_index: dict[int, dict] = {}
    for s_idx, sym in enumerate(symbols):
        closes = []
        price = 1.0 + 0.1 * s_idx
        for _ in range(n_days):
            price *= (1.0 + rng.uniform(-0.03, 0.03))
            closes.append(round(price, 4))
        kline[sym] = {"close": closes, "dates": dates}

    for i in range(1, n_days):
        day_scores: dict[str, dict] = {}
        for s_idx, sym in enumerate(symbols):
            day_scores[sym] = {
                code: round(rng.uniform(-1.0, 1.0) + 0.01 * s_idx, 4)
                for code in codes
            }
        factor_scores_by_index[i] = day_scores

    return kline, factor_scores_by_index, symbols, codes


class TestR55BackfillObservable:
    """回填后状态翻「可观察」，且 distinct trade_date 跳升。"""

    @pytest.mark.asyncio
    async def test_backfill_lifts_distinct_trade_dates_and_status(self, ic_db):
        tracker = ICTracker()
        kline, scores, symbols, codes = _make_kline_and_scores(n_days=240, n_symbols=10)

        async with ic_db() as db:
            processed = await tracker.backfill_ic_history(db, kline, scores)
            distinct = await tracker.count_distinct_trade_dates(db)
            rows = (await db.execute(select(FactorICRecord))).scalars().all()

        # R55 验收：回填后 distinct trade_date ≥ 230（~240 交易日 K 线）
        assert processed >= 230, f"回填交易日数应 ≥230，实际 {processed}"
        assert distinct >= 230, f"distinct trade_date 应 ≥230，实际 {distinct}"
        # 每日每因子均有落库（含近零 signal_absent 行）
        assert len(rows) >= 230 * len(codes), f"落库行数不足：{len(rows)}"

        # R55 验收：_status_of 对回填后样本返回「可观察」（非"积累中 <60"）
        status, reason = _status_of(codes[0], distinct, None, None)
        assert status == "no_data", f"230<250 应仍 no_data（自然积累），实际 {status}"
        assert "可观察" in reason, f"回填后原因应含「可观察」，实际：{reason}"
        assert "未达可观察下限" not in reason, f"不应仍处 <60 积累中，实际：{reason}"

    @pytest.mark.asyncio
    async def test_backfill_does_not_falsely_report_valid(self, ic_db):
        """诚实性：即便回填到 ~239 天（<250），也不得谎报 valid。"""
        tracker = ICTracker()
        kline, scores, symbols, codes = _make_kline_and_scores(n_days=240, n_symbols=10)

        async with ic_db() as db:
            await tracker.backfill_ic_history(db, kline, scores)
            distinct = await tracker.count_distinct_trade_dates(db)

        assert distinct < MIN_TRADING_DAYS, "测试前提：<250 天"
        status, _ = _status_of(codes[0], distinct, None, None)
        assert status != "valid", "MIN_TRADING_DAYS 门槛不变：<250 天不得标 valid（诚实）"


class TestR55HonestNoBackfill:
    """无回填时状态必须诚实（不得谎报 valid）。"""

    @pytest.mark.asyncio
    async def test_no_backfill_never_valid(self, ic_db):
        tracker = ICTracker()
        # 模拟仅 3 个 distinct trade_date（生产 fresh 库现状）
        async with ic_db() as db:
            for i in range(3):
                await tracker.save_ic_batch_to_db(
                    db, {"technical.ma.sma_5": 0.03}, trade_date=date(2026, 8, 12 + i)
                )
            distinct = await tracker.count_distinct_trade_dates(db)
        assert distinct == 3
        real_status, real_reason = _status_of("technical.ma.sma_5", distinct, None, None)

        # 无回填：sample_count=3 < 60 → 诚实处「未达可观察下限」积累中，不得 valid
        assert real_status != "valid", "无回填不得谎报 valid"
        assert "未达可观察下限" in real_reason, (
            "未回填应处 <60 积累中（未达可观察下限），实际：" + real_reason
        )

        # 覆盖更宽样本档位（0/3/59）均不得 valid
        for samples in (0, 3, 59):
            st, _ = _status_of("technical.ma.sma_5", samples, None, None)
            assert st != "valid", f"sample={samples} 不得 valid"

    @pytest.mark.asyncio
    async def test_empty_db_status_not_valid(self, ic_db):
        # 空库（0 样本）必须诚实：不得 valid
        st, reason = _status_of("technical.ma.sma_5", 0, None, None)
        assert st != "valid"
        assert "未累积" in reason or "IC 未累积" in reason


class TestR55OneShotNoPerRequestIO:
    """回填是一次性批量计算，请求路径不触发回填。"""

    def test_factors_endpoint_does_not_trigger_backfill(self):
        """命中 /factors/active 不得调用 backfill_ic_history（无 per-request IO）。"""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.factors import ic_tracker as ic_tracker_mod

        # 模块级 client（与 test_factors_router.py 同模式）——不触发完整 lifespan，
        # 即便触发，backfill 后台任务先 sleep(20s) 再执行，请求期间不会调用。
        client = TestClient(app)
        with patch.object(
            ic_tracker_mod.ic_tracker, "backfill_ic_history", new=MagicMock()
        ) as mock_backfill:
            resp = client.get("/api/v1/factors/active")
            assert resp.status_code == 200
            # 请求过程中 backfill 绝不被调用（回填仅 startup-once 后台任务）
            mock_backfill.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_call_is_bulk(self, ic_db):
        """一次 backfill 调用即产出全部日样本（非逐请求累计）。"""
        tracker = ICTracker()
        kline, scores, symbols, codes = _make_kline_and_scores(n_days=240, n_symbols=10)

        async with ic_db() as db:
            processed1 = await tracker.backfill_ic_history(db, kline, scores)
            distinct1 = await tracker.count_distinct_trade_dates(db)
            # 再次调用（模拟重复触发）应幂等：upsert 覆盖同 (code, trade_date)，不追加
            processed2 = await tracker.backfill_ic_history(db, kline, scores)
            distinct2 = await tracker.count_distinct_trade_dates(db)

        assert processed1 >= 230
        assert distinct1 >= 230
        assert distinct2 == distinct1, "重复回填应 upsert 不追加（distinct 不变）"
        assert processed2 == processed1

