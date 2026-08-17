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

import pytest
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
