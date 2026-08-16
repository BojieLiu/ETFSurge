from __future__ import annotations
"""
U1/N03 (round2-unfixed-fix-plan.md U1 / round3-diagnosis-and-optimization-plan.md N03):
港股路由分流 + 熔断空结果语义。

- U1 R1: get_asset_realtime 按 asset_type 分流——HK 跳过 A 股路径（避免空结果污染熔断）。
- U1 R2 / N03 规格 1: route() 中 provider 返回空结果记 record_miss（不增加失败计数），
  仅 HTTP 4xx/5xx / 异常 / 超时计入熔断。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.market_service import get_asset_realtime
from app.core.source_registry import SourceRegistry


class TestGetAssetRealtimeRouting:
    @pytest.mark.asyncio
    async def test_hk_realtime_skips_a_path(self):
        """U1: HK 标的直接走 HK 降级链，不再先跑 A 股路径。"""
        hk_data = [{"symbol": "00700", "price": 475.2, "change_pct": 0.72}]
        with patch("app.services.market_service._call",
                   new=AsyncMock(return_value=hk_data)) as mock_call, \
             patch("app.fetchers.china_market.fetch_a_stock_realtime") as mock_a:
            result = await get_asset_realtime("00700", "HK")

        assert result is not None
        assert result["symbol"] == "00700"
        mock_a.assert_not_called(), "HK 路径不得调用 fetch_a_stock_realtime"
        assert mock_call.await_count == 1, "HK 路径只应发起一次查询（fetch_hk_stock_realtime）"

    @pytest.mark.asyncio
    async def test_a_realtime_skips_hk_path(self):
        """U1: A 股标的只走 A 股路径，不查 HK。"""
        a_data = [{"symbol": "510050", "price": 3.033, "change_pct": 0.5}]
        with patch("app.services.market_service._call",
                   new=AsyncMock(return_value=a_data)) as mock_call, \
             patch("app.fetchers.china_market.fetch_hk_stock_realtime") as mock_hk:
            result = await get_asset_realtime("510050", "A")

        assert result is not None
        assert result["symbol"] == "510050"
        mock_hk.assert_not_called(), "A 股路径不得调用 fetch_hk_stock_realtime"
        assert mock_call.await_count == 1

    @pytest.mark.asyncio
    async def test_hk_missing_returns_none(self):
        """U1: HK 查无此标的返回 None（不崩溃、不误伤下游）。"""
        with patch("app.services.market_service._call",
                   new=AsyncMock(return_value=[])), \
             patch("app.fetchers.china_market.fetch_a_stock_realtime") as mock_a:
            result = await get_asset_realtime("99999", "HK")

        assert result is None
        mock_a.assert_not_called()

    @pytest.mark.asyncio
    async def test_us_path_unchanged(self):
        """U1: US 路径保持 _route_us（回归保护）。"""
        with patch("app.services.market_service._route_us",
                   new=AsyncMock(return_value={"symbol": "SPY", "price": 500.0})) as mock_us:
            result = await get_asset_realtime("SPY", "US")
        assert result["symbol"] == "SPY"
        mock_us.assert_awaited_once()


class TestN07ShortCache:
    @pytest.mark.asyncio
    async def test_3s_cache_skips_second_call(self):
        """N07: 3s 内重复请求命中短缓存，不再调用数据源。"""
        from app.services.market_service import _asset_realtime_cache
        _asset_realtime_cache.clear()
        calls = {"n": 0}

        async def _slow_fetch(*args, **kwargs):
            calls["n"] += 1
            return [{"symbol": "00700", "price": 475.2, "change_pct": 0.72}]

        with patch("app.services.market_service._call", new=_slow_fetch):
            r1 = await get_asset_realtime("00700", "HK")
            r2 = await get_asset_realtime("00700", "HK")

        assert r1 == r2
        assert calls["n"] == 1, "3s 短缓存应命中，第二次不再调用数据源"

    @pytest.mark.asyncio
    async def test_hk_timeout_relaxed_to_15s(self):
        """N07: HK 标的 _call 超时放宽到 15s（不再 8s 间歇 null）。"""
        import inspect
        from app.services.market_service import get_asset_realtime as gar
        src = inspect.getsource(gar)
        assert "timeout=_timeout" in src
        assert "_timeout = 8 if asset_type == \"A\" else 15" in src


class TestRouteEmptyResultMiss:
    def test_empty_result_does_not_count_failure(self):
        """N03: 连续空结果（超过阈值 3 次）不触发熔断。"""
        reg = SourceRegistry()
        for _ in range(6):
            result = reg.route([("src_a", lambda: [])], route_name="test", target="00700")
            assert result is None

        h = reg.health("src_a")
        with h._lock:
            assert h._failures == 0, "空结果不应增加失败计数"
            assert h._cool_until == 0.0, "空结果不应触发熔断"

    def test_exception_still_counts_failure(self):
        """N03: provider 抛异常仍计失败（真故障语义不变）。"""

        def _boom():
            raise ConnectionError("network down")

        reg = SourceRegistry()
        for _ in range(3):
            reg.route([("src_b", _boom)], route_name="test", target="x")

        h = reg.health("src_b")
        with h._lock:
            assert h._failures == 0  # 达到阈值后已熔断并清零
            assert h._cool_until > 0, "异常累计到阈值必须熔断"

    def test_http_400_still_hard_failure(self):
        """N03: HTTP ≥400 仍走 record_hard_failure（硬失败语义不变）。"""
        reg = SourceRegistry()
        reg.route([("src_c", lambda: (None, 500))], route_name="test", target="x")

        h = reg.health("src_c")
        with h._lock:
            assert h._cool_until > 0, "HTTP 500 必须立即冷却"

    def test_empty_then_success_recovers(self):
        """N03: 空结果后成功数据正常返回。"""
        calls = {"n": 0}

        def _flaky():
            calls["n"] += 1
            return [] if calls["n"] == 1 else [{"symbol": "00700", "price": 475.2}]

        reg = SourceRegistry()
        first = reg.route([("src_d", _flaky)], route_name="test", target="00700")
        assert first is None
        second = reg.route([("src_d", _flaky)], route_name="test", target="00700")
        assert second == [{"symbol": "00700", "price": 475.2}]


# ===== folded from test_round14_p2_market.py =====
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.factors import factor_registry as fr_mod
from app.factors.factor_registry import FactorRegistry
from app.fetchers import hk_hot_fetcher
from app.routers import market as market_router
class TestHkHotFilter:
    def _row(self, f12, f14, f6=1e8):
        return {"f12": f12, "f14": f14, "f2": 10.0, "f3": 0.5, "f6": f6, "f100": "金融"}

    def test_fund_rows_filtered_out(self):
        """基金/ETF/杠杆行被过滤（03033 南方恒生科技 / 02800 盈富基金 / 07709 杠杆做多）。"""
        rows = [
            self._row("03033", "南方恒生科技ETF", 9e9),
            self._row("02800", "盈富基金", 8e9),
            self._row("07709", "南方两倍做多海力士", 7e9),
            self._row("00700", "腾讯控股", 6e9),
            self._row("00011", "恒生银行", 5e9),
        ]
        stocks = hk_hot_fetcher.parse_hk_hot_stocks(rows, top_n=10)
        syms = [s["symbol"] for s in stocks]
        assert "00700" in syms
        assert "00011" in syms, "恒生银行不能被「恒生」前缀误杀"
        assert "03033" not in syms and "02800" not in syms and "07709" not in syms

    def test_url_contains_t3(self):
        assert "fs=m:128+t:3" in hk_hot_fetcher._URL
        assert hk_hot_fetcher._HK_FS == "m:128+t:3"

    def test_route_target_synced(self):
        """熔断观测 target 与 URL fs 一致。"""
        assert hk_hot_fetcher._HK_FS in hk_hot_fetcher._URL

    def test_cache_versioned_ignores_stale_fs(self):
        """旧 fs（m:128 含基金）缓存不得回填新榜。"""
        hk_hot_fetcher._HK_ROWS_CACHE.update({
            "ts": 0.0, "rows": [self._row("02800", "盈富基金")], "last_ok": [self._row("02800", "盈富基金")], "fs": "m:128",
        })
        with patch.object(hk_hot_fetcher.registry, "route",
                          return_value=[self._row("00700", "腾讯控股")]) as m:
            rows = hk_hot_fetcher._fetch_hk_rows()
        m.assert_called_once()
        assert rows[0]["f12"] == "00700", "fs 不一致时必须重新拉取而非用旧缓存"
class TestTrackingErrorSharesChange:
    @pytest.mark.asyncio
    async def test_compute_merges_symbol_extra_with_external_market_data(self):
        """P2-Z 修复 1: 外部注入 market_data 时合并 symbol_extra（benchmark_close）。"""
        reg = FactorRegistry()
        market_data = {
            "510300": {"close": [3.8 + i * 0.01 for i in range(60)],
                       "high": [3.9] * 60, "low": [3.7] * 60, "open": [3.8] * 60},
        }
        symbol_extra = {"510300": {"benchmark_close": [4.0 + i * 0.01 for i in range(60)],
                                   "shares_change_20d": 0.012}}
        result = await reg.compute(["510300"], market_data=market_data, symbol_extra=symbol_extra)
        row = result["510300"]
        assert "etf.tracking_error" in row
        assert row["etf.tracking_error"] != 0.0, "tracking_error 应为非 0（benchmark_close 注入生效）"
        assert row["etf.shares_change"] != 0.0

    def test_compute_periodic_ic_tracking_error_not_skipped(self):
        """P2-Z 修复 3: tracking_error=0.005 不被 abs<0.001 跳过（合法值 0.001~0.02）。"""
        from app.factors.ic_tracker import ICTracker
        tracker = ICTracker()
        factor_values = {
            "510300": {"etf.tracking_error": 0.005, "etf.shares_change": 0.012},
            "588000": {"etf.tracking_error": 0.004, "etf.shares_change": 0.008},
            "159915": {"etf.tracking_error": 0.006, "etf.shares_change": 0.010},
            "512480": {"etf.tracking_error": 0.005, "etf.shares_change": 0.011},
        }
        # market_data 需含 close 序列且各 sym 走势不同（build_forward_returns 用；
        # 常量 forward return 会被 compute_ic 的 nunique==1 判 None）
        market_data = {
            "510300": {"close": [10.0 + i * 0.05 for i in range(10)]},
            "588000": {"close": [10.0 + i * 0.10 for i in range(10)]},
            "159915": {"close": [10.0 + i * 0.15 for i in range(10)]},
            "512480": {"close": [10.0 + i * 0.08 for i in range(10)]},
        }
        result = tracker.compute_periodic_ic(factor_values, market_data, window=1)
        assert "etf.tracking_error" in result, "tracking_error 应产出 IC（0.005 不再被当零跳过）"
        assert "etf.shares_change" in result
class TestUsPlatesAndPePb:
    def test_us_plates_aggregated_by_industry(self):
        """P2-AK: 美股 spot 按行业聚合板块（mock 数据）。"""
        from app.fetchers import sector_fetcher as sf

        rows = [
            {"symbol": "NVDA", "name": "英伟达", "industry": "信息技术", "change_pct": 3.2, "amount": 1e9, "pe": 32.98},
            {"symbol": "MSFT", "name": "微软", "industry": "信息技术", "change_pct": 1.0, "amount": 2e9, "pe": 28.1},
            {"symbol": "XOM", "name": "埃克森美孚", "industry": "能源", "change_pct": -0.5, "amount": 5e8, "pe": 15.0},
        ]
        with patch.object(sf, "_fetch_us_spot_rich", return_value=rows), \
             patch.object(sf, "cached", side_effect=lambda key, fn, ttl: fn()):
            plates = sf.fetch_us_plates(limit=10)
        by_name = {p["name"]: p for p in plates}
        assert by_name["信息技术"]["stock_count"] == 2
        assert by_name["信息技术"]["change_pct"] == pytest.approx(2.1)  # (3.2+1.0)/2
        assert by_name["能源"]["stock_count"] == 1

    def test_us_pe_pb_from_spot(self):
        """P2-AN: 美股 PE 走东财美股 spot f9（PB 不可靠返回 None，不伪造）。"""
        from app.fetchers import fundamentals_fetcher as ff
        from app.fetchers import sector_fetcher as sf

        rows = [{"symbol": "NVDA", "name": "英伟达", "industry": "信息技术",
                 "change_pct": 3.2, "amount": 1e9, "pe": 32.98}]
        with patch.object(sf, "_fetch_us_spot_rich", return_value=rows):
            result = ff.fetch_current_pe_pb("NVDA", "US")
        assert result == {"pe_ttm": 32.98, "pb": None}

    def test_us_pe_missing_returns_none(self):
        """P2-AN 负向: 美股 spot 无 PE/负 PE → None（报告诚实标注不可用）。"""
        from app.fetchers import fundamentals_fetcher as ff
        from app.fetchers import sector_fetcher as sf

        with patch.object(sf, "_fetch_us_spot_rich", return_value=[
                {"symbol": "QQQ", "name": "纳指100ETF", "industry": "-", "pe": None}]):
            assert ff.fetch_current_pe_pb("QQQ", "US") is None
        with patch.object(sf, "_fetch_us_spot_rich", return_value=[
                {"symbol": "SPCX", "name": "SpaceX", "industry": "工业", "pe": -222.54}]):
            assert ff.fetch_current_pe_pb("SPCX", "US") is None

    def test_hot_plates_us_branch_returns_plates(self):
        """P2-AK 接入: get_hot_plates(market=US) 返回板块（非「暂不支持」空）。"""
        from app.services.market_data_hub import market_data_hub

        with patch("app.fetchers.sector_fetcher.fetch_us_plates", return_value=[
                {"name": "信息技术", "change_pct": 2.1, "amount": 3e9, "stock_count": 2}]):
            plates = market_data_hub.get_hot_plates(limit=10, market="US")
        assert len(plates) == 1
        assert plates[0]["name"] == "信息技术"
class TestSectorHeatPlateJoin:
    @pytest.mark.asyncio
    async def test_plate_code_join_priority(self):
        """P2-AE: plate_code join 命中 → 用财联社真实涨跌幅（×100）。"""
        from app.routers import market as m

        rows = [{"rank": 1, "plate_name": "乳业奶粉", "plate_code": "cls80041",
                 "cur_heat": 10, "rank_change": 0, "is_new": 0}]
        with patch.object(m.market_data_hub, "get_sector_heat", return_value=rows), \
             patch("app.routers.market.asyncio.to_thread", new=AsyncMock(side_effect=[
                 rows,               # get_sector_heat
                 {"cls80041": 1.86},  # fetch_cls_plate_changes
                 {},                  # fetch_em_sector_changes
             ])):
            resp = await m.sectors_heat(limit=20, market="A")
        item = resp["items"][0]
        assert item["change_pct"] == pytest.approx(1.86), "plate_code join 应命中财联社真实涨跌"

    @pytest.mark.asyncio
    async def test_plate_code_miss_falls_back_em_and_null(self):
        """P2-AE 负向: plate_code 未命中 → 东财名称兜底 → 仍未命中显式 null（round19 P4-③:
        0 改 null——0 会被前端显示成「平盘 0%」冒充真实涨跌）。"""
        from app.routers import market as m

        rows = [{"rank": 1, "plate_name": "民爆概念", "plate_code": "cls99999",
                 "cur_heat": 10, "rank_change": 0, "is_new": 0}]
        with patch.object(m.market_data_hub, "get_sector_heat", return_value=rows), \
             patch("app.routers.market.asyncio.to_thread", new=AsyncMock(side_effect=[
                 rows,  # get_sector_heat
                 {},    # cls 未命中
                 {},    # em 也未命中
             ])):
            resp = await m.sectors_heat(limit=20, market="A")
        assert resp["items"][0]["change_pct"] is None, \
            "未命中涨跌幅应显式 null（不冒充 0% 平盘）"

    def test_cls_plate_changes_parses_decimal_to_pct(self):
        """fetch_cls_plate_changes: change 小数（0.0186）→ ×100（1.86）。"""
        import json
        from app.fetchers import sector_fetcher as sf

        fake_resp = json.dumps({
            "errno": 0,
            "data": {"plate_list": [
                {"secu_code": "cls80041", "change": 0.0186},
                {"secu_code": "cls80042", "change": -0.0114},
                {"secu_code": "cls80043", "change": None},
            ]},
        }).encode("utf-8")

        class _Resp:
            def read(self):
                return fake_resp

        def _fake_urlopen(req, timeout=8):
            assert "type=" in req.full_url  # industry + concept 两轮
            return _Resp()

        with patch.object(sf, "cached", side_effect=lambda key, fn, ttl: fn()), \
             patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            result = sf.fetch_cls_plate_changes()
        assert result["cls80041"] == pytest.approx(1.86)
        assert result["cls80042"] == pytest.approx(-1.14)
        assert "cls80043" not in result
class TestNewsByMarket:
    @pytest.mark.asyncio
    async def test_us_market_uses_global_news(self):
        """P2-AJ: market=US → news 来自 fetch_global_news（非 A 股新闻）。"""
        from app.services import llm_context as lc
        from unittest.mock import MagicMock

        hub = MagicMock()
        hub.get_news_headlines.return_value = [
            {"title": "工银瑞信史宝珖：从工业革命到A股行情", "stars": 4, "level": "利好"}]
        global_news = [{"title": "Dow Jones: Global Markets Rally", "stars": 4, "level": "利好"}]
        with patch("app.fetchers.news_fetcher.fetch_global_news", return_value=global_news):
            ctx = await lc.build_full_context(hub, market="US", include_portfolio=False)
        news = ctx.get("news") or []
        assert news, "US 综合研判应注入新闻"
        assert "Dow Jones" in news[0].get("title", "")
        assert all("工银瑞信" not in n.get("title", "") for n in news)

    @pytest.mark.asyncio
    async def test_a_market_keeps_headlines(self):
        """P2-AJ: market=A → 保持 get_news_headlines（A 股行为不变）。

        注：news 段 A 分支原代码用模块单例 market_data_hub（非参数），patch 单例。
        """
        from app.services import llm_context as lc
        from app.services.market_data_hub import market_data_hub as real_hub
        from unittest.mock import MagicMock

        hub = MagicMock()
        with patch.object(real_hub, "get_news_headlines", return_value=[
                {"title": "A股财新头条", "stars": 4, "level": "利好"}]), \
             patch.object(real_hub, "get_news_macro", return_value=[]), \
             patch("app.fetchers.news_fetcher.fetch_global_news", return_value=[
                {"title": "Global", "stars": 4, "level": "利好"}]):
            ctx = await lc.build_full_context(
                hub, market="A", include_portfolio=False,
                include_global_liquidity=False, include_macro=False,
                include_fund_flow=False, include_commodities=False,
                include_sectors=False, include_indices=False,
                include_sentiment=False, include_regime=False,
            )
        news = ctx.get("news") or []
        assert any("A股财新头条" in n.get("title", "") for n in news)


# ===== folded from test_round19_p8.py =====
class TestStaticExtraIndicesHk:
    """round19 P8-①: 静态兜底段 HK 指数扩展。"""

    def test_hk_segment_has_industry_and_theme(self):
        from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES

        hk = [i for i in _STATIC_EXTRA_INDICES if i.get("market") == "HK"]
        symbols = {i["symbol"] for i in hk}
        # 基础 12 条 + 新增行业/主题 18 条 = 30；同步后表行数（新浪 ~25 + 静态）≥40
        assert len(hk) >= 28, f"HK 静态段应 ≥28 条（旧 12 + 行业/主题补齐），实得 {len(hk)}"
        for required in ("HSCI", "HSF", "HSAHC", "HSII", "HSHYLDI", "HSCIF", "HSCIT"):
            assert required in symbols, f"HK 静态段缺 {required}: {sorted(symbols)}"
        # 类别区分
        cats = {i["symbol"]: i.get("category") for i in hk}
        assert cats.get("HSF") == "industry", "恒生金融分类应标 industry"
        assert cats.get("HSAHC") == "theme", "恒生医疗保健应标 theme"
        # 全部 source=static（来源诚实性）
        assert all(i.get("source") == "static" for i in hk)
