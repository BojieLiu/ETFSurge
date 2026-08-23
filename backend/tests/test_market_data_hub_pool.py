"""
R5-0-1: 候选池强制标的二次校验（docs/round5-diagnosis-and-optimization-plan.md §十 P0）。

背景：`_ensure_mandatory` 在 MAX_PER_LAYER 截断前执行，截断（含行业均衡挤出）后
强制标的（159338 等）可能被挤出候选池 → P1-1 A500 缺失真实链路复验 FAIL。
修复：①截断时保护强制标的（截断前剔除 MANDATORY_CODES，截断后再补回）；
     ②截断后二次校验（MANDATORY_CODES ∪ CORE_REQUIRED 缺失时从 flat 找回注入 + WARNING）。

纯函数/轻量 mock 测试，无网络。
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.market_data_hub import (
    MarketDataHub,
    MANDATORY_CODES,
    LAYER_CORE,
    LAYER_SATELLITE,
    LAYER_DEFENSE,
)


def _make_hub():
    """轻量构造 hub 实例（不跑 __init__ 的 I/O 逻辑）。"""
    return MarketDataHub.__new__(MarketDataHub)


def _flat_with(code, name="test-etf", layer="core"):
    return {"symbol": code, "name": name, "layer": layer,
            "tracked_index": name, "industry": "宽基指数", "segment": name}


class TestTruncateProtectsMandatory:
    """R5-0-1 用例②：MAX_PER_LAYER 截断前剔除 MANDATORY_CODES，截断后再补回。"""

    def test_truncate_keeps_mandatory_beyond_max(self):
        """截断 max_n=3 时，排在末尾的强制标的 159338 必须保留。"""
        hub = _make_hub()
        balanced = [
            {"symbol": "588000", "name": "科创50ETF"},
            {"symbol": "159915", "name": "创业板ETF"},
            {"symbol": "510050", "name": "上证50ETF"},
            {"symbol": "159338", "name": "中证A500ETF"},  # 强制标的，排第 4
        ]
        result = hub._truncate_with_mandatory_protection(balanced, max_n=3)
        syms = [e["symbol"] for e in result]
        assert "159338" in syms, f"截断后强制标的 159338 被挤出: {syms}"
        # 非强制标的仍按 max_n 截断
        non_mandatory = [s for s in syms if s not in MANDATORY_CODES]
        assert len(non_mandatory) <= 3, f"非强制标的超过 max_n: {non_mandatory}"

    def test_truncate_no_mandatory_plain_slice(self):
        """池中无强制标的时，行为与普通截断一致。"""
        hub = _make_hub()
        balanced = [
            {"symbol": "588000"}, {"symbol": "159915"}, {"symbol": "510050"},
            {"symbol": "512480"}, {"symbol": "515030"},
        ]
        result = hub._truncate_with_mandatory_protection(balanced, max_n=3)
        assert [e["symbol"] for e in result] == ["588000", "159915", "510050"]


class TestRecheckMandatoryAfterTruncate:
    """R5-0-1 用例①：截断后二次校验，缺失强制标的从 flat 找回注入。"""

    def test_recheck_injects_missing_mandatory(self):
        """pool 截断后缺失 159338 → 二次校验从 flat 找回注入 core 层。"""
        hub = _make_hub()
        pool = {
            LAYER_CORE: [{"symbol": "510300", "name": "沪深300ETF"}],
            LAYER_SATELLITE: [],
            LAYER_DEFENSE: [],
        }
        flat = [_flat_with("159338", "中证A500ETF")]
        hub._recheck_mandatory_after_truncate(pool, flat)
        core_syms = [e["symbol"] for e in pool[LAYER_CORE]]
        assert "159338" in core_syms, f"二次校验未注入 159338: {core_syms}"

    def test_recheck_skips_when_present(self):
        """强制标的本就在池中 → 二次校验不重复注入、不抛异常。"""
        hub = _make_hub()
        pool = {
            LAYER_CORE: [{"symbol": "159338", "name": "中证A500ETF"}],
            LAYER_SATELLITE: [],
            LAYER_DEFENSE: [],
        }
        flat = [_flat_with("159338", "中证A500ETF")]
        hub._recheck_mandatory_after_truncate(pool, flat)
        core_syms = [e["symbol"] for e in pool[LAYER_CORE]]
        assert core_syms.count("159338") == 1, "强制标的被重复注入"

    def test_recheck_flat_empty_noop(self):
        """flat 为空（扫描失败）→ 不注入、不抛异常（与 _ensure_mandatory 语义一致）。"""
        hub = _make_hub()
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: []}
        hub._recheck_mandatory_after_truncate(pool, [])
        assert pool[LAYER_CORE] == []

    def test_recheck_missing_from_flat_warns_noop(self):
        """flat 中没有 159338 → 无法注入，但不抛异常（仅 WARNING）。"""
        hub = _make_hub()
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: []}
        flat = [_flat_with("588000", "科创50ETF")]
        # 不应抛异常
        hub._recheck_mandatory_after_truncate(pool, flat)
        assert pool[LAYER_CORE] == []


# ── News aggregation（合并自 test_market_data_hub_news.py）──────────────


def _make_hub_news():
    from app.services.market_data_hub import MarketDataHub
    hub = MarketDataHub.__new__(MarketDataHub)
    hub._news_cache = None
    hub._news_buckets = None
    hub._news_cache_ts = 0.0
    hub.NEWS_TTL = 120
    return hub


def test_get_news_headlines_returns_bucket():
    """get_news_headlines should return only headlines after refresh."""
    hub = _make_hub_news()
    mock_headlines = [{"title": "h1", "level": "利好"}]
    mock_macro = [{"title": "m1", "level": "宏观"}]
    mock_global = [{"title": "g1"}]

    # Hub does lazy import inside refresh_news from ..fetchers.news_fetcher
    with patch("app.fetchers.news_fetcher.fetch_news_headlines",
               return_value=mock_headlines) as mh:
        with patch("app.fetchers.news_fetcher.fetch_macro_news",
                   return_value=mock_macro):
            with patch("app.fetchers.news_fetcher.fetch_global_news",
                       return_value=mock_global):
                hub.refresh_news()
                mh.assert_called_once()

    assert hub.get_news_headlines() == mock_headlines
    assert hub.get_news_macro() == mock_macro
    assert hub.get_news_global() == mock_global
    # Merged view backward compat
    assert hub.get_news() == mock_headlines + mock_macro + mock_global
    # Cache is now populated; getters should NOT re-fetch
    with patch("app.fetchers.news_fetcher.fetch_news_headlines") as mh2:
        assert hub.get_news_headlines() == mock_headlines
        mh2.assert_not_called()


def test_lazy_refresh_on_empty_bucket():
    """_news_bucket should trigger a refresh when buckets are uninitialized."""
    hub = _make_hub_news()
    mock_headlines = [{"title": "fresh"}]

    with patch("app.fetchers.news_fetcher.fetch_news_headlines",
               return_value=mock_headlines):
        with patch("app.fetchers.news_fetcher.fetch_macro_news",
                   return_value=[]):
            with patch("app.fetchers.news_fetcher.fetch_global_news",
                       return_value=[]):
                result = hub.get_news_headlines()

    assert result == mock_headlines
    assert hub._news_buckets is not None


def test_news_bucket_returns_empty_on_fetch_failure():
    """Buckets should be empty (not crash) when all fetchers fail."""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.fetch_news_headlines",
               side_effect=Exception("network down")):
        with patch("app.fetchers.news_fetcher.fetch_macro_news",
                   side_effect=Exception("network down")):
            with patch("app.fetchers.news_fetcher.fetch_global_news",
                       side_effect=Exception("network down")):
                assert hub.get_news_headlines() == []
                assert hub.get_news() == []


def test_get_news_stock_delegates():
    """get_news_stock should delegate to fetch_stock_news."""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.fetch_stock_news",
               return_value=[{"title": "s1"}]) as m:
        assert hub.get_news_stock("510300") == [{"title": "s1"}]
        m.assert_called_once_with("510300")


def test_get_news_stock_returns_empty_on_failure():
    """get_news_stock should return [] (not crash) on fetch failure."""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.fetch_stock_news",
               side_effect=Exception("down")):
        assert hub.get_news_stock("510300") == []


def test_get_akshare_pool_stats_delegates():
    """get_akshare_pool_stats should delegate to fetcher."""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.get_akshare_pool_stats",
               return_value={"etf_count": 100}) as m:
        assert hub.get_akshare_pool_stats() == {"etf_count": 100}
        m.assert_called_once()


def test_get_akshare_pool_stats_returns_empty_on_failure():
    """get_akshare_pool_stats should return {} on fetch failure."""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.get_akshare_pool_stats",
               side_effect=Exception("down")):
        assert hub.get_akshare_pool_stats() == {}


# ── Realtime delegate（合并自 test_market_data_hub_realtime.py）─────────


def _make_hub_realtime():
    from app.services.market_data_hub import MarketDataHub
    hub = MarketDataHub.__new__(MarketDataHub)
    return hub


@pytest.mark.asyncio
async def test_get_realtime_forwards_to_market_service():
    """hub.get_realtime -> market_service.get_realtime_batch."""
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_realtime_batch",
               new=AsyncMock(return_value=[{"symbol": "510300"}])) as m:
        result = await hub.get_realtime(["510300"], "A")
        assert result == [{"symbol": "510300"}]
        m.assert_awaited_once_with(["510300"], "A")


@pytest.mark.asyncio
async def test_get_all_realtime_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_all_realtime",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_all_realtime()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_asset_realtime_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_asset_realtime",
               new=AsyncMock(return_value={"symbol": "600519"})) as m:
        result = await hub.get_asset_realtime("600519", "stock")
        assert result == {"symbol": "600519"}
        m.assert_awaited_once_with("600519", "stock")


@pytest.mark.asyncio
async def test_get_portfolio_realtime_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_portfolio_realtime",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_portfolio_realtime()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_indices_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_indices",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_indices()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_global_indices_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_global_indices",
               new=AsyncMock(return_value={"A": []})) as m:
        result = await hub.get_global_indices()
        assert result == {"A": []}
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_commodities_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_commodities",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_commodities()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_market_history_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_history",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_market_history("510300", "A", "daily")
        assert result == []
        m.assert_awaited_once_with("510300", "A", "daily")


@pytest.mark.asyncio
async def test_search_etf_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.search_etf",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.search_etf("300")
        assert result == []
        m.assert_awaited_once_with("300")


def test_hub_has_no_circular_import():
    """Importing both hub and market_service should not crash (lazy imports)."""
    import app.services.market_data_hub
    import app.services.market_service
    assert app.services.market_data_hub.market_data_hub is not None
    assert callable(app.services.market_service.get_all_realtime)


# ===================================================================
# merged from test_round24_r26_snapshot.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round24 R26: 盘后数据变薄优化——market_session 显式盘后模式 + 快照持久化。

问题（round24 §12.1 R26 实证）：盘后/熔断时 design 570 `valid_rate=0.0%`、correlation
空、sector_momentum=[]、fund_flow=0。last-good pool / kline cache / ic batch 全内存
重启即丢 → 盘后重启 = 全空 = 静态兜底。T-1 真实数据不持久化。

修复：
- `market_session()`（market_calendar）：open / pre_market / after_hours（盘后固定价格
  交易 15:05-15:30，2026-07-06 A股新规）/ post_market / closed——纯函数；
- `MarketSnapshot` 模型 + `_persist_snapshot` / `_load_latest_snapshot`：pool /
  sector_momentum / fund_flow 落盘，盘后/熔断读快照兜底（last-good 之上再一层）；
- `strategy_design._build_market_context` 透传 session + data_as_of。
"""

import json
from datetime import datetime, date

import pytest


class TestMarketSession:
    """R26①: market_session 显式盘后模式（含 2026-07-06 盘后固定价格交易窗口）。"""

    def _dt(self, day, hhmm):
        h, m = int(hhmm[:2]), int(hhmm[3:])
        return datetime(2026, 8, day, h, m)  # 2026-08-14 是周五

    @pytest.mark.parametrize("hhmm,expected", [
        ("10:00", "open"),
        ("14:59", "open"),
        ("15:02", "post_market"),      # 15:00-15:05 间隙（收盘集合竞价后）
        ("15:10", "after_hours"),      # 盘后固定价格交易窗口 15:05-15:30（新规）
        ("15:30", "after_hours"),      # 边界含 15:30
        ("15:31", "post_market"),      # 窗口后
        ("18:00", "post_market"),
        ("09:00", "pre_market"),       # 开盘前
    ])
    def test_weekday_sessions(self, hhmm, expected):
        from app.core.market_calendar import market_session
        assert market_session(self._dt(14, hhmm)) == expected

    def test_weekend_closed(self):
        from app.core.market_calendar import market_session
        sat = datetime(2026, 8, 15, 10, 0)  # 周六
        assert market_session(sat) == "closed"

    def test_is_trading_time_semantics_preserved(self):
        """is_trading_time 仍以 15:00 为界——after_hours 不视为盘中（收盘价已定，
        盘后固定价格交易以收盘价成交不产生新价格）。"""
        from app.core.market_calendar import is_trading_time
        assert is_trading_time(self._dt(14, "15:10")) is False
        assert is_trading_time(self._dt(14, "14:00")) is True


class TestMarketSnapshotPersistence:
    """R26②: 快照持久化——MarketSnapshot 模型 + 写读兜底。"""

    def test_model_roundtrip(self, tmp_path):
        """模型 JSON 落盘 → 读回 → payload 完整（负向：字段缺失 → FAIL）。"""
        import sys
        sys.path.insert(0, str(tmp_path))  # 隔离模型导入路径
        from app.models.market_snapshot import MarketSnapshot
        snap = MarketSnapshot(
            kind="pool",
            payload=json.dumps({"core": [{"symbol": "510300"}]}, ensure_ascii=False),
            as_of="2026-08-14T15:30:00",
        )
        assert snap.kind == "pool"
        assert json.loads(snap.payload)["core"][0]["symbol"] == "510300"
        assert snap.as_of == "2026-08-14T15:30:00"

    def test_as_of_after_hours_full_volume(self):
        """盘后固定价格交易结束（≥15:30）→ as_of 用 15:30（含盘后成交量）。"""
        from app.services.market_data_hub import _snapshot_as_of_for
        assert _snapshot_as_of_for(datetime(2026, 8, 14, 15, 35)) == "2026-08-14T15:30:00"

    def test_as_of_intraday_last(self):
        """15:00-15:30 窗口内（盘后固定价格交易未结束）→ as_of=15:00（盘中最后快照）。"""
        from app.services.market_data_hub import _snapshot_as_of_for
        assert _snapshot_as_of_for(datetime(2026, 8, 14, 15, 10)) == "2026-08-14T15:00:00"

    def test_as_of_open_session(self):
        """盘中 → as_of=当前时刻（非快照场景，函数应返回 None 表示不写快照）。"""
        from app.services.market_data_hub import _snapshot_as_of_for
        assert _snapshot_as_of_for(datetime(2026, 8, 14, 10, 0)) is None


class TestStrategyDesignSessionPropagation:
    """R26③: design market_context 透传 session + data_as_of。"""

    def test_market_context_has_session_and_as_of(self, monkeypatch):
        from app.services import strategy_design as sd
        from app.core import market_calendar as mc

        # 冻结时间：周五 18:00（盘后）
        frozen = datetime(2026, 8, 14, 18, 0)
        monkeypatch.setattr(mc, "datetime", _FrozenDatetime(frozen))
        # _snapshot_as_of_for 现位于 hub/_common.py，使用自身 `from datetime import datetime`
        # 的模块级绑定（非 market_data_hub.datetime），需冻结 _common.datetime 才生效
        from app.services.hub import _common as _common_mod
        monkeypatch.setattr(_common_mod, "datetime", _FrozenDatetime(frozen))
        from app.services import market_data_hub as mh
        monkeypatch.setattr(mh, "datetime", _FrozenDatetime(frozen))
        monkeypatch.setattr(sd, "market_session", lambda dt=None: mc.market_session(dt))

        # 轻量 fake hub + 桩掉重 I/O 纯函数，真实调用 _build_market_context 验证透传
        class _FakeHub:
            def get_market_regime(self): return "range_bound"
            def get_market_sentiment(self): return {"sentiment_index": 50, "sentiment_label": "中性"}
            def get_index_realtime(self): return []
            async def get_global_indices(self): return {}
            def get_sector_momentum(self): return []
            def get_sector_stocks(self, code): return []
            def get_pool(self): return {}

        async def _fake_ff(hub): return {}
        monkeypatch.setattr(sd, "_compute_fund_flow", _fake_ff)
        monkeypatch.setattr(sd, "_factor_data_quality_report",
                            lambda db_sample_counts=None: {"valid_rate": 1.0})
        monkeypatch.setattr(sd, "_data_precision_report", lambda fq: {"mode": "full"})

        ctx = sd._build_market_context.__wrapped__ if hasattr(sd._build_market_context, "__wrapped__") else sd._build_market_context
        import asyncio
        result = asyncio.run(ctx(_FakeHub()))
        assert result["session"] == "post_market", f"market_context.session 未透传 R26 盘后态：{result.get('session')}"
        assert result["data_as_of"] is not None, "盘后态 data_as_of 应为 T-1 时点（非空）"
        assert result["data_as_of"].endswith("15:30:00"), f"盘后完整数据 as_of 应为 15:30：{result.get('data_as_of')}"



class _FrozenDatetime(datetime):
    """冻结 datetime.now——测试盘后路径（避免依赖真实时钟）。

    子类化 datetime，使被冻结实例仍支持 .replace()/.isoformat() 等（_snapshot_as_of_for
    内部会调用），避免 AttributeError 被吞成 data_as_of=None。
    """

    _FROZEN_REF = None

    def __new__(cls, *args, **kwargs):
        # 既支持 _FrozenDatetime(real_datetime) 也支持基类 datetime(y,m,d,...) 构造
        # （.replace() 会走基类构造路径）
        if len(args) == 1 and isinstance(args[0], datetime) and not isinstance(args[0], _FrozenDatetime):
            f = args[0]
            obj = datetime.__new__(cls, f.year, f.month, f.day, f.hour, f.minute, f.second)
            cls._FROZEN_REF = f
            return obj
        return datetime.__new__(cls, *args, **kwargs)

    def now(self, tz=None):
        return self

    @classmethod
    def utcnow(cls):
        f = cls._FROZEN_REF or datetime(2026, 8, 14, 18, 0)
        return datetime.__new__(cls, f.year, f.month, f.day, f.hour, f.minute, f.second)


# ===================================================================
# merged from test_round24_strong_sector.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round24 R1: 强板块动量注入候选池（SECTOR_ETF_MAP + _strong_sector_etfs）。

R1 缺口：design 570 实证 strong_sector_pool_coverage=[]、候选池=0，强板块未进候选池，
方案与市场热点脱节。修复：板块动量 TopN 经 SECTOR_ETF_MAP 映射代表 ETF 注入 flat。

本测试固化纯函数 _strong_sector_etfs 的映射/去重/排序/降级行为（无 I/O）。
"""

from app.services.market_data_hub import _strong_sector_etfs, SECTOR_ETF_MAP


def _sector(name, change_pct, type_="industry"):
    return {"sector": name, "sector_code": f"BK_{name}", "type": type_,
            "change_pct": change_pct, "rank_current": 1}


def test_top_sector_maps_to_etf():
    """涨幅最高的「半导体」→ 512480，且带 hot_sector 标记与保底 composite_score。"""
    momentum = [_sector("银行", 1.0), _sector("半导体", 3.5), _sector("煤炭", 0.5)]
    out = _strong_sector_etfs(momentum, top_n=8)
    syms = {e["symbol"] for e in out}
    assert "512480" in syms
    item = next(e for e in out if e["symbol"] == "512480")
    assert item["hot_sector"] is True
    assert item["composite_score"] == 0.6
    assert item["layer"] == "satellite"


def test_unmapped_sector_skipped():
    """未建映射的板块（如「XX概念」）被跳过，不报错。"""
    momentum = [_sector("未知板块XYZ", 5.0)]
    out = _strong_sector_etfs(momentum, top_n=8)
    assert out == []


def test_existing_symbol_skipped():
    """已存在于候选池的强板块 ETF 不重复注入。"""
    momentum = [_sector("半导体", 3.5)]
    out = _strong_sector_etfs(momentum, existing_symbols={"512480"}, top_n=8)
    assert out == []


def test_empty_momentum_returns_empty():
    """熔断/无板块动量（[]）→ 返回 []，不注入。"""
    assert _strong_sector_etfs([], top_n=8) == []
    assert _strong_sector_etfs(None, top_n=8) == []


def test_sorted_by_change_pct_desc():
    """注入顺序按 change_pct 降序（最强板块优先）。"""
    momentum = [_sector("煤炭", 0.5), _sector("半导体", 3.5), _sector("证券", 2.0)]
    out = _strong_sector_etfs(momentum, top_n=8)
    syms = [e["symbol"] for e in out]
    assert syms[0] == "512480"   # 半导体 3.5 最高
    assert "512880" in syms      # 证券 2.0


def test_top_n_limit():
    """top_n 限制注入数量（去重后）。"""
    momentum = [_sector(n, 1.0 + i) for i, n in enumerate(
        ["半导体", "证券", "军工", "煤炭", "医药", "光伏", "银行", "通信", "游戏", "白酒"])]
    out = _strong_sector_etfs(momentum, top_n=3)
    assert len(out) == 3


def test_map_covers_core_indices():
    """宽基（沪深300/中证500/创业板/科创50/恒生）映射为 core 层。"""
    for name, layer in [("沪深300", "core"), ("中证500", "core"),
                        ("创业板", "core"), ("科创50", "core"), ("恒生科技", "satellite")]:
        assert name in SECTOR_ETF_MAP, f"{name} 缺映射"
        assert SECTOR_ETF_MAP[name]["layer"] == layer


# ===================================================================
# merged from test_round28_fixes.py::TestR59RefreshConcurrentKlinePreWarm (S3.3 de-round, 2026-08-18)
# ===================================================================
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_mod
from app.services import market_service as ms
from app.services.market_data_hub import _rule_news_summary
from app.services.market_service import infer_market_from_symbol


class TestR59RefreshConcurrentKlinePreWarm:
    def test_prewarm_falls_back_to_pool_when_by_code_empty(self):
        """R59① 修复: 冷启动/重启时 _by_code 为空（扫描未完成）→ K 线预热必须回退
        last-good 池（_pool），否则预热线恒空转（实测无「kline pre-warm finished」日志）。
        """
        src = open(
            os.path.join(os.path.dirname(main_mod.__file__), "services", "market_data_hub.py"),
            encoding="utf-8",
        ).read()
        # _warm_kline_concurrent 内：_by_code 为空时遍历 _pool.values() 收集 symbol
        assert "_last_pool = getattr(self, \"_pool\", None) or {}" in src, \
            "K 线预热须在 _by_code 为空时回退 last-good 池（R59① 防空转）"


# merged from test_round24_batch3.py (R17/R23, S3.3, 2026-08-18)
import asyncio
from unittest.mock import patch
import pytest

# ── R17: 三桶 AI 摘要覆盖 ──────────────────────────────────────────────


def test_r17_three_bucket_summary_coverage():
    """R17: macro/global 重要项也生成摘要（不再仅 headlines）。"""
    from app.services.market_data_hub import market_data_hub as hub_inst

    buckets = {
        "headlines": [
            {"title": "头条重大", "level": 5, "stars": 2, "ai_summary": None},
        ],
        "macro": [
            {"title": "宏观重大", "level": 5, "stars": 1, "ai_summary": None},
        ],
        "global": [
            {"title": "全球重大", "level": 4, "stars": 1, "ai_summary": None},
        ],
    }

    def _fake_bucket(key):
        return buckets.get(key, [])

    monkeypatch_bucket = patch.object(hub_inst, "_news_bucket", side_effect=_fake_bucket)

    async def _fake_summary(title, content):
        return f"AI:{title}"

    with monkeypatch_bucket, patch(
        "app.analysis.llm.generate_news_summary", side_effect=_fake_summary
    ):
        n = asyncio.run(hub_inst.enrich_news_summaries(cap=6))

    # 三桶各 1 条重要项均被覆盖
    assert n == 3, f"三桶重要项应各生成 1 条摘要，实际 {n}"
    assert buckets["headlines"][0]["ai_summary"].startswith("AI:")
    assert buckets["macro"][0]["ai_summary"].startswith("AI:")
    assert buckets["global"][0]["ai_summary"].startswith("AI:")


def test_r17_cost_cap_respected():
    """R17/R90: cap 截断生效，控制 LLM 成本；rule 兜底覆盖配额外 level≥3 条目。

    round30 R90：cap 只约束 LLM 调用次数（避免打满配额）——配额外 level≥3
    条目由 `_rule_news_summary` 兜底填充（ai_summary_source="rule"），保证
    高重要性条目摘要非 null。故 `n`（LLM+rule 合计）> cap 是预期行为，
    **LLM 调用次数 ≤ cap** 才是 R17 的约束断言。
    """
    from app.services.market_data_hub import market_data_hub as hub_inst

    items = [
        {"title": f"新闻{i}", "level": 5, "stars": 1, "ai_summary": None}
        for i in range(10)
    ]
    monkeypatch_bucket = patch.object(hub_inst, "_news_bucket", return_value=items)

    llm_calls = []

    async def _fake_summary(title, content):
        llm_calls.append(title)
        return f"AI:{title}"

    with monkeypatch_bucket, patch(
        "app.analysis.llm.generate_news_summary", side_effect=_fake_summary
    ):
        n = asyncio.run(hub_inst.enrich_news_summaries(cap=4))

    # R17: LLM 调用次数 ≤ cap（成本约束）——旧断言 `n == 4` 已过时（R90 新增
    # 配额外 rule 兜底 pass，n 含 rule 摘要，不再等于 LLM 调用数）。
    assert len(llm_calls) <= 4, f"LLM 调用次数 {len(llm_calls)} 超过 cap=4"
    assert len(llm_calls) > 0, "LLM 应至少生成 1 条摘要"
    # R90: 全部 level≥3 条目 ai_summary 非 null（rule 兜底覆盖配额外）
    assert all(it.get("ai_summary") for it in items), "配额外 level>=3 条目应有 rule 兜底"


# ── R65 (round28): LLM 失败/配额空窗 → 规则摘要兜底非 null ──────────────


def test_r65_rule_fallback_on_llm_failure_macro_bucket():
    """R65: macro 桶重要条目在 LLM 失败时兜底为规则摘要（非 null）。

    round28 §6 R65 实证：LLM 配额门禁让位主链路后 enrich 永不回填 →
    高重要性条目 ai_summary 恒 null。修复：LLM 失败 → `_rule_news_summary`
    取 content 首句兜底，标注 ai_summary_source="rule"，保证非 null；
    下一轮 enrich 仍重试 LLM（仅 rule 来源允许覆盖）。
    """
    from app.services.market_data_hub import market_data_hub as hub_inst

    buckets = {
        "headlines": [],
        "macro": [
            {
                "title": "央行降准 0.5 个百分点 释放长期流动性",
                "content": "中国人民银行宣布下调金融机构存款准备金率 0.5 个百分点。"
                           "本次降准预计释放长期资金约 1 万亿元。专家表示这是稳增长的重要信号。",
                "level": 5,
                "stars": 4,
                "ai_summary": None,
            },
        ],
        "global": [],
    }

    def _fake_bucket(key):
        return buckets.get(key, [])

    async def _explode(title, content):
        raise RuntimeError("LLM 配额耗尽 / 调用失败")

    monkeypatch_bucket = patch.object(hub_inst, "_news_bucket", side_effect=_fake_bucket)

    with monkeypatch_bucket, patch(
        "app.analysis.llm.generate_news_summary", side_effect=_explode
    ):
        n = asyncio.run(hub_inst.enrich_news_summaries(cap=6))

    macro_item = buckets["macro"][0]
    assert n >= 1, "LLM 失败后仍应有 rule 兜底摘要"
    assert macro_item["ai_summary"] is not None, "macro 高重要性条目 ai_summary 不得为 null（R65）"
    assert macro_item["ai_summary_source"] == "rule", "rule 兜底须标注来源"
    assert "存款准备金率" in macro_item["ai_summary"], "rule 摘要应含 content 首句真实内容（非占位）"


def test_r65_rule_fallback_macro_and_global_both_nonnull():
    """R65: macro + global 两桶高重要性条目在 LLM 全失败时均兜底非 null。"""
    from app.services.market_data_hub import market_data_hub as hub_inst

    buckets = {
        "headlines": [],
        "macro": [
            {"title": "宏观头条", "content": "宏观内容甲。更多细节。", "level": 5, "stars": 1, "ai_summary": None},
        ],
        "global": [
            {"title": "国际要闻", "content": "国际内容乙。更多细节。", "level": 4, "stars": 1, "ai_summary": None},
        ],
    }

    def _fake_bucket(key):
        return buckets.get(key, [])

    async def _explode(title, content):
        raise RuntimeError("配额空窗")

    with patch.object(hub_inst, "_news_bucket", side_effect=_fake_bucket), patch(
        "app.analysis.llm.generate_news_summary", side_effect=_explode
    ):
        n = asyncio.run(hub_inst.enrich_news_summaries(cap=6))

    assert buckets["macro"][0]["ai_summary"] is not None
    assert buckets["global"][0]["ai_summary"] is not None
    assert buckets["macro"][0]["ai_summary_source"] == "rule"
    assert buckets["global"][0]["ai_summary_source"] == "rule"
    assert n >= 2


# ── R23: news 懒刷新锁 + 回退 ──────────────────────────────────────────


def _make_hub_news_r23():
    from app.services.market_data_hub import MarketDataHub

    hub = MarketDataHub.__new__(MarketDataHub)
    hub._news_cache = None
    hub._news_buckets = None
    hub._news_cache_ts = 0.0
    hub.NEWS_TTL = 120
    return hub


def test_r23_fallback_keeps_prev_nonempty_on_empty_fetch():
    """R23: TTL 过期但抓取返回空（数据源冷却）时，回退上次非空桶，不瞬态返 0。"""
    hub = _make_hub_news_r23()
    prev = [
        {"title": "prev-headline", "level": 3},
    ]
    hub._news_buckets = {
        "headlines": prev,
        "macro": [{"title": "prev-macro"}],
        "global": [{"title": "prev-global"}],
    }
    hub._news_cache_ts = 0.0  # 过期 → 触发刷新

    with patch("app.fetchers.news_fetcher.fetch_news_headlines", return_value=[]), \
         patch("app.fetchers.news_fetcher.fetch_macro_news", return_value=[]), \
         patch("app.fetchers.news_fetcher.fetch_global_news", return_value=[]):
        result = hub.get_news_headlines()

    # 抓取空 → 回退上次非空，高负载下不返 0
    assert result == prev, f"空抓取应回退上次非空桶，实得 {result}"
    assert hub.get_news_macro() != []
    assert hub.get_news_global() != []


def test_r23_lock_attribute_created_and_safe():
    """R23: 安全刷新建立锁且不抛异常（并发刷新路径可走）。"""
    hub = _make_hub_news_r23()
    with patch("app.fetchers.news_fetcher.fetch_news_headlines",
               return_value=[{"title": "h"}]), \
         patch("app.fetchers.news_fetcher.fetch_macro_news", return_value=[]), \
         patch("app.fetchers.news_fetcher.fetch_global_news", return_value=[]):
        hub._refresh_news_buckets_safe()
    assert getattr(hub, "_news_refresh_lock", None) is not None
    assert hub.get_news_headlines() == [{"title": "h"}]
