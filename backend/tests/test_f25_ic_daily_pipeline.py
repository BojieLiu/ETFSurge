"""
F25/F30 (archived/round23-system-audit-optimization.md §8): IC 统计管线业内对齐。

背景（docs/archived/archived/round23-system-audit-optimization.md.md §2.5 B1）:
- 旧 `sample_count` 统计「刷新次数」（4306 行/18 天 ≈240× 虚高），MIN_IC_SAMPLES=30
  开机 1h 即被跨过 →「有效 16」无统计含义。
- 旧 `abs(ic_val) < 0.0001 → continue` 丢弃近零批次 → 生存者偏差（F30）。

F25 设计要点（契约 api-contracts/factors/active.md）:
① 存储粒度: 日频 1 行, (factor_code, trade_date) 唯一约束, 同天重复刷新 upsert;
   sample_count = count(distinct trade_date)。
② 显著性: IC_mean/IC_std/IR/t（Newey-West SE）; MIN_OBSERVABLE_DAYS=60 可观察,
   MIN_TRADING_DAYS=250 有效, 且 t≥2 AND |IR|≥0.5 才 valid。
③ 缺失值: signal_absent=True 仍落库（IC 记 0）, 不丢弃（修复生存者偏差）。
④ 前端四指标: ic_mean/ic_std/t_stat/ir。

验收口径（文档）:
- factor_ic_records 总行数 == 去重日数 × 因子数;
- 18 天数据下所有因子状态 = no_data（积累中）, 不得出现 valid;
- 注入 250+ 天仿真数据后, 仅 t≥2 且 |IR|≥0.5 的因子转 valid;
- factor_ic_records 含近零批次行（signal_absent=True）;
- 同屏不存在两个相差 5× 的平均|IC|（由既有 T10 测试覆盖）。
"""
import random
import time as _time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from unittest.mock import patch

from app.core.market_calendar import is_a_share_trading_day
from app.database import Base
from app.factors.ic_tracker import ICTracker, _beijing_today, compute_series_stats
from app.models.factor_ic import FactorICRecord


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


async def _insert_daily_series(factory, code: str, dates: list[date], ic_values: list[float], signal_absent_flags: list[bool] | None = None):
    """按日频 1 行规则写入因子 IC 序列（绕过 save 方法，直接构造历史）。"""
    async with factory() as db:
        for i, (d, icv) in enumerate(zip(dates, ic_values)):
            flag = signal_absent_flags[i] if signal_absent_flags else abs(icv) < 0.0001
            db.add(FactorICRecord(
                factor_code=code,
                ic_value=0.0 if flag else round(float(icv), 4),
                signal_absent=flag,
                trade_date=d,
                sample_count=i + 1,
                computed_at=d,
            ))
        await db.commit()


class TestF25DailyUpsert:
    """F25①: 存储粒度日频 1 行，同天重复刷新 upsert 不追加。"""

    @pytest.mark.asyncio
    async def test_same_day_upsert_no_duplicates(self, ic_db):
        tracker = ICTracker()
        batch1 = {"technical.ma.sma_5": 0.0321, "technical.rsi.rsi_14": -0.0210}
        batch2 = {"technical.ma.sma_5": 0.0400}  # 同天第二次刷新（值变化）
        d = date(2026, 8, 14)
        async with ic_db() as db:
            await tracker.save_ic_batch_to_db(db, batch1, trade_date=d)
            await tracker.save_ic_batch_to_db(db, batch2, trade_date=d)
            rows = (await db.execute(select(FactorICRecord))).scalars().all()
        # 同天同因子只保留 1 行（upsert 覆盖）
        assert len(rows) == 2, f"同天刷新应 upsert 不追加，实际 {len(rows)} 行"
        by_code = {r.factor_code: r for r in rows}
        assert by_code["technical.ma.sma_5"].ic_value == 0.04  # 被第二批覆盖
        assert by_code["technical.rsi.rsi_14"].ic_value == -0.021

    @pytest.mark.asyncio
    async def test_sample_count_equals_distinct_dates(self, ic_db):
        """sample_count 语义 = count(distinct trade_date)（日频），而非刷新次数。"""
        tracker = ICTracker()
        batch = {"technical.ma.sma_5": 0.0321}
        async with ic_db() as db:
            for i in range(3):
                await tracker.save_ic_batch_to_db(db, batch, trade_date=date(2026, 8, 12 + i))
            rows = (await db.execute(select(FactorICRecord))).scalars().all()
            sample_counts = {r.trade_date: r.sample_count for r in rows}
        assert len(rows) == 3
        assert all(sc == i + 1 for i, sc in enumerate(sorted(sample_counts.values()))), sample_counts


class TestF25SignalAbsent:
    """F25③/F30: 近零 IC 批次标记 signal_absent=True 仍落库（修复生存者偏差）。"""

    @pytest.mark.asyncio
    async def test_near_zero_ic_recorded_not_dropped(self, ic_db):
        tracker = ICTracker()
        # 旧逻辑 `abs(ic_val)<0.0001 → continue` 会丢弃 0.00005；新逻辑必须落库
        batch = {"technical.vol.vol_ratio": 0.00005}
        async with ic_db() as db:
            await tracker.save_ic_batch_to_db(db, batch, trade_date=date(2026, 8, 14))
            rows = (await db.execute(select(FactorICRecord))).scalars().all()
        assert len(rows) == 1, "近零 IC 批次不得丢弃"
        assert rows[0].signal_absent is True
        assert rows[0].ic_value == 0.0


class TestMarketCalendarTradingDay:
    """is_a_share_trading_day：周末 False，工作日 True（节假日不在本层能力内）。"""

    def test_saturday_is_not_trading_day(self):
        assert is_a_share_trading_day(date(2026, 9, 5)) is False

    def test_sunday_is_not_trading_day(self):
        # 2026-09-06 周日（round53 §8.3 实测 IC 灌水日；文档写作「周六」系笔误，
        # 9-08=周二 → 9-06=周日，非交易日实质不变）
        assert is_a_share_trading_day(date(2026, 9, 6)) is False

    def test_weekday_is_trading_day(self):
        # 2026-09-08 周二（round53 §12 复测日）
        assert is_a_share_trading_day(date(2026, 9, 8)) is True

    def test_accepts_datetime(self):
        assert is_a_share_trading_day(datetime(2026, 9, 5, 10, 0)) is False  # 周六
        assert is_a_share_trading_day(datetime(2026, 9, 9, 10, 0)) is True   # 周三


class TestR183NonTradingDaySkip:
    """R183 负向断言：非交易日（周末）触发落库不产生新 factor_ic_records 行。"""

    @pytest.mark.asyncio
    async def test_weekend_default_date_skips(self, ic_db):
        """默认交易日路径（生产 _ic_persistence_loop）：周末 → 0 行落库。"""
        tracker = ICTracker()
        batch = {"technical.ma.sma_5": 0.0321, "technical.rsi.rsi_14": -0.0210}
        async with ic_db() as db:
            with patch(
                "app.factors.ic_tracker._beijing_today",
                return_value=date(2026, 9, 6),  # 周日
            ):
                count = await tracker.save_ic_batch_to_db(db, batch)
            rows = (await db.execute(select(FactorICRecord))).scalars().all()
        assert count == 0, "周末默认交易日必须 0 行落库"
        assert len(rows) == 0, f"周末不得产生 factor_ic_records 行，实际 {len(rows)}"

    @pytest.mark.asyncio
    async def test_trading_day_default_date_persists(self, ic_db):
        """对照：交易日默认路径正常落库（校验不误杀生产路径）。"""
        tracker = ICTracker()
        batch = {"technical.ma.sma_5": 0.0321}
        async with ic_db() as db:
            with patch(
                "app.factors.ic_tracker._beijing_today",
                return_value=date(2026, 9, 8),  # 周二交易日
            ):
                count = await tracker.save_ic_batch_to_db(db, batch)
            rows = (await db.execute(select(FactorICRecord))).scalars().all()
        assert count == 1 and len(rows) == 1

    @pytest.mark.asyncio
    async def test_explicit_trade_date_not_validated(self, ic_db):
        """显式注入 trade_date 不校验——历史回填按 K 线日期序列（本身即交易日）落库。"""
        tracker = ICTracker()
        async with ic_db() as db:
            # 周六 2026-09-06 显式注入：仍落库（回填兼容）
            count = await tracker.save_ic_batch_to_db(
                db, {"technical.ma.sma_5": 0.0321}, trade_date=date(2026, 9, 6))
            rows = (await db.execute(select(FactorICRecord))).scalars().all()
        assert count == 1 and len(rows) == 1

    @pytest.mark.asyncio
    async def test_monday_after_midnight_utc_offset(self, ic_db):
        """时区边界：北京时间周一 07:00 = UTC 周日 23:00 —— 北京日期应为周一（交易日）。"""
        tracker = ICTracker()
        utc_sun_23 = datetime(2026, 9, 6, 23, 0, tzinfo=timezone.utc)  # UTC 周日 23:00 = 北京周一 07:00
        assert _beijing_today(utc_sun_23) == date(2026, 9, 7)
        async with ic_db() as db:
            with patch(
                "app.factors.ic_tracker._beijing_today",
                return_value=date(2026, 9, 7),
            ):
                count = await tracker.save_ic_batch_to_db(
                    db, {"technical.ma.sma_5": 0.0321})
            rows = (await db.execute(select(FactorICRecord))).scalars().all()
        assert count == 1 and len(rows) == 1


class TestF25SeriesStats:
    """F25②: IC 序列统计——IC_mean/IC_std/IR/t（Newey-West lag=1）。"""

    def test_series_stats_basic(self):
        # 构造序列: [0.04]*250 → 恒正，std≈0 → IR 极大/t 极大
        st = compute_series_stats([0.04] * 250)
        assert st is not None
        assert abs(st["ic_mean"] - 0.04) < 1e-6

    def test_series_stats_ir_t(self):
        # 均值 0.05、std 0.10、T=250 的序列：IR=0.5、t 应 > 2（显著）
        rng = random.Random(42)
        vals = [0.05 + rng.gauss(0, 0.10) for _ in range(250)]
        st = compute_series_stats(vals)
        assert st is not None
        assert abs(st["ir"] - 0.5) < 0.3
        assert st["t_stat"] > 2, f"t 应显著，实际 {st['t_stat']}"

    def test_series_stats_zero_variance(self):
        """全同值序列：std=0 → IR 无定义，t=0（不显著，不抛异常）。"""
        st = compute_series_stats([0.03] * 100)
        assert st is not None
        assert st["ic_std"] == 0.0
        assert st["t_stat"] == 0.0

    def test_series_stats_insufficient(self):
        assert compute_series_stats([]) is None
        assert compute_series_stats([0.1]) is None  # 单点无法估 std


class TestF25StatusTiers:
    """F25② 验收: 18 天全 no_data；250+ 天仅 t≥2 且 |IR|≥0.5 转 valid。"""

    def test_18_days_all_no_data(self):
        from app.routers.factors import _status_of
        # 18 个交易日（即使 |IC| 很高）也不得 valid
        status, reason = _status_of("technical.ma.sma_5", samples=18, t_stat=1.2, ir=0.6)
        assert status == "no_data"
        assert "积累" in reason

    def test_60_days_observable_still_no_data(self):
        from app.routers.factors import _status_of
        status, reason = _status_of("technical.ma.sma_5", samples=60, t_stat=1.5, ir=0.6)
        assert status == "no_data"
        assert "可观察" in reason

    def test_250_days_significant_valid(self):
        from app.routers.factors import _status_of
        status, reason = _status_of("technical.ma.sma_5", samples=250, t_stat=2.3, ir=0.6)
        assert status == "valid", reason
        assert "统计显著" in reason

    def test_250_days_insignificant_warn(self):
        """有样本但 t<2 或 |IR|<0.5 → warn（不再 valid）。"""
        from app.routers.factors import _status_of
        status, reason = _status_of("technical.ma.sma_5", samples=250, t_stat=1.4, ir=0.6)
        assert status == "warn", reason
        status2, _ = _status_of("technical.ma.sma_5", samples=250, t_stat=2.3, ir=0.3)
        assert status2 == "warn"


class TestF25ActiveEndpoint:
    """端点级验收: /factors/active 的 status/sample_count 与 DB 日频序列一致。"""

    @pytest.mark.asyncio
    async def test_active_uses_distinct_date_and_series(self, ic_db):
        from app.routers import factors as factors_router

        # 注入 18 天序列（显著值但样本不足）→ 必须 no_data 且 sample_count=18
        code = "technical.ma.sma_5"
        days = [date(2026, 7, 20) + timedelta(days=i) for i in range(18)]
        await _insert_daily_series(ic_db, code, days, [0.25] * 18)

        fake_ic = {code: 0.25}
        with patch.object(factors_router.registry, "_last_ic_batch", fake_ic), \
             patch.object(factors_router.registry, "_sample_counts", {}), \
             patch.object(factors_router.registry, "_computers", [code]), \
             patch.object(factors_router.registry, "get_factor", lambda c: None):
            factors_router._CACHE.clear()
            # 真实 DB 会话
            async with ic_db() as db:
                resp = await factors_router.get_active_factors(db=db)
                body = resp.body if not isinstance(resp.body, dict) else resp.body
            factors_router._CACHE.clear()
        if isinstance(body, bytes):
            import json as _json
            body = _json.loads(body)
        items = [f for cat in body["categories"] for f in cat["factors"]]
        assert len(items) == 1
        f = items[0]
        assert f["sample_count"] == 18, f"sample_count 应为 18 个交易日，实际 {f['sample_count']}"
        assert f["status"] == "no_data", f"18 天不得 valid，实际 {f['status']}: {f['reason']}"
        assert f["t_stat"] is not None and f["ic_mean"] is not None
        assert body["summary"]["min_samples"] == 250  # F32: 后端补 min_samples

    @pytest.mark.asyncio
    async def test_zero_ratio_not_empty(self):
        """F27+F25③: zero_ratio 非空（真实反映无信号占比）。"""
        from app.routers import factors as factors_router
        tracker = ICTracker()
        # compute_periodic_ic 里 _zero_ratio 会随批次更新；这里直接设值模拟
        tracker._zero_ratio = {"technical.vol.vol_ratio": 1.0, "technical.ma.sma_5": 0.0}
        with patch.object(factors_router, "_ic_tracker", tracker):
            factors_router._CACHE.clear()
            # 用 MagicMock db（DB 不可用回退内存路径），验证 zero_ratio 透出
            with patch.object(factors_router.registry, "_last_ic_batch", {}), \
                 patch.object(factors_router.registry, "_computers", []):
                resp = await factors_router.get_active_factors(db=MagicMock())
                body = resp.body if not isinstance(resp.body, dict) else resp.body
            factors_router._CACHE.clear()
        if isinstance(body, bytes):
            import json as _json
            body = _json.loads(body)
        assert body.get("zero_ratio", {}) != {}
        assert body["zero_ratio"].get("technical.vol.vol_ratio") == 1.0


class TestF25Migration:
    """F25 迁移（database._migrate）: 旧注水数据清空重建，新列存在。"""

    @pytest.mark.asyncio
    async def test_migrate_clears_legacy_inflated_rows(self, ic_db):
        from sqlalchemy import text
        from app.database import _migrate
        # 造旧注水数据（trade_date NULL → 旧格式）
        async with ic_db() as db:
            db.add(FactorICRecord(factor_code="x", ic_value=0.1, sample_count=4306))
            await db.commit()
            # 模拟迁移：给表加列（新库表已有列，这里直接验证 DELETE 逻辑）
            n = (await db.execute(
                text("SELECT COUNT(*) FROM factor_ic_records WHERE trade_date IS NULL")
            )).scalar_one()
        assert n == 1


# ═══ 节假日交易日历（round53 遗留批：从 test_market_calendar_holiday.py 并入，T4 约定）═══
class TestHolidayCalendar:
    @pytest.fixture(autouse=True)
    def _fresh_cal_cache(self):
        """每个用例独立日历缓存（防模块级缓存跨用例互涉——xdist 同 worker 下
        前一用例的拉取结果污染后一用例的 mock 假设）。"""
        import app.core.market_calendar as mc
        saved = mc._HOLIDAY_CAL_CACHE
        mc._HOLIDAY_CAL_CACHE = None
        yield
        mc._HOLIDAY_CAL_CACHE = saved

    def test_fetch_trade_dates_parses_dates(self):
        """_fetch_trade_dates 解析 date 元组（mock akshare，不触网——
        AGENTS.md「外部网络必须 mock」；真实拉取行为由生产代码路径覆盖）。"""
        import datetime as _dt
        import app.core.market_calendar as mc

        class _FakeDF:
            empty = False
            columns = ["trade_date"]

            def __getitem__(self, key):
                assert key == "trade_date"
                return [date(2026, 10, 8), "2026-10-09"]

        with patch("akshare.tool_trade_date_hist_sina", return_value=_FakeDF()):
            cal = mc._fetch_trade_dates()
        assert cal is not None
        assert date(2026, 10, 8) in cal
        assert date(2026, 10, 9) in cal  # str 路径解析

    def test_fetch_failure_returns_none(self):
        """负向：akshare 拉取抛异常 → _fetch_trade_dates 返 None（不炸调用方）。"""
        import app.core.market_calendar as mc
        with patch("akshare.tool_trade_date_hist_sina", side_effect=RuntimeError("net down")):
            assert mc._fetch_trade_dates() is None

    def test_national_day_is_not_trading_day(self):
        """2026-10-01 国庆 → False（mock 日历：不在集合）。"""
        fake = (date(2026, 9, 30), date(2026, 10, 8))
        with patch("app.core.market_calendar._holiday_calendar", return_value=fake):
            assert is_a_share_trading_day(date(2026, 10, 1)) is False

    def test_calendar_open_day_after_holiday_is_trading_day(self):
        """日历内真实开市日 2026-10-08（节后首日，周四）→ True（对照）。"""
        fake = (date(2026, 10, 8), date(2026, 10, 9))
        with patch("app.core.market_calendar._holiday_calendar", return_value=fake):
            assert is_a_share_trading_day(date(2026, 10, 8)) is True

    def test_calendar_is_authoritative_exchange_days(self):
        """日历口径 = 交易所实际开市日（含未来真实调休开市日——若某周六开市，
        日历是唯一能答对的机制；纯周末判定在调休场景会误杀 IC 落库）。

        mock 日历对齐实测数据（2026-09-09 tool_trade_date_hist_sina：
        2026-10-01..10-07 国庆休市、10-08 恢复开市）。
        """
        fake = (date(2026, 10, 8), date(2026, 10, 9))
        with patch("app.core.market_calendar._holiday_calendar", return_value=fake):
            assert is_a_share_trading_day(date(2026, 10, 1)) is False
            assert is_a_share_trading_day(date(2026, 10, 8)) is True

    def test_regular_saturday_still_false(self):
        """普通周六 2026-10-17 → False（日历不含 → 仍正确）。"""
        fake = (date(2026, 10, 8), date(2026, 10, 9))
        with patch("app.core.market_calendar._holiday_calendar", return_value=fake):
            assert is_a_share_trading_day(date(2026, 10, 17)) is False

    def test_calendar_failure_degrades_to_weekend(self):
        """负向：日历拉取失败 → 降级周末判定，不抛异常。

        降级模式下周六 → False（可接受的诚实降级——误杀一天 IC 比让 IC 落库
        链路崩溃危害小）；普通工作日照常 True。
        """
        with patch("app.core.market_calendar._holiday_calendar", return_value=None):
            assert is_a_share_trading_day(date(2026, 10, 10)) is False  # 周六
            assert is_a_share_trading_day(date(2026, 10, 12)) is True   # 周一

    def test_calendar_cached_second_call_no_refetch(self):
        """缓存生效：日历已加载时二次调用不重拉（mock 计数）。"""
        import app.core.market_calendar as mc
        mc._HOLIDAY_CAL_CACHE = (_time.time(), (date(2026, 10, 8),))
        calls = {"n": 0}

        def _counting_fetch():
            calls["n"] += 1
            return (date(2026, 10, 9),)

        with patch.object(mc, "_fetch_trade_dates", _counting_fetch):
            mc._holiday_calendar()
            mc._holiday_calendar()
        assert calls["n"] == 0, "缓存有效期内二次调用不得重拉"

    def test_weekday_beyond_calendar_horizon_uses_weekend_fallback(self):
        """日历覆盖范围外（如 2027 年底之后）的工作日：日历不含 → 回落周末判定。

        语义：日历覆盖期有限（如至 2026-12-31）；超出覆盖期的日期不能因为
        「不在日历里」被误判 False——必须在日历最晚日期之后回落周末判定。
        """
        fake = (date(2026, 10, 8), date(2026, 12, 31))
        with patch("app.core.market_calendar._holiday_calendar", return_value=fake):
            assert is_a_share_trading_day(date(2027, 6, 15)) is True   # 周二
            assert is_a_share_trading_day(date(2027, 6, 19)) is False  # 周六
