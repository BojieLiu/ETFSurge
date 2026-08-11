"""round14 P2 行情批次测试：P2-AF/AH（watchlist 分组批量 + 降级标记）、P0-D、
P2-AG（港股指数过滤）、P2-AI（港股热门过滤）、P2-Z（tracking_error/shares_change）。

对应 docs/round14-container-acceptance-diagnosis.md §5：
- P2-AF: asset_type="stock"（江波龙 301317）归入 A 股批量 → 走 get_realtime_batch
  （修复前被 _a_items 排除走 per-item 3s 截断）
- P2-AH: HK 标的三只走 get_realtime_batch(...,'HK')（修复前 per-item）
- P0-D: 慢源降级 → 响应含 realtime:null + _degraded:true（不再丢 realtime 键）
- P2-AG: _search_indices(kw, market='HK') 只返回 HK 指数
- P2-AI: 基金/ETF 行过滤、恒生银行 00011 保留、_URL 含 t:3、缓存版本化
- P2-Z: compute 外部注入 market_data + symbol_extra → tracking_error 非 0；
  compute_periodic_ic 的 tracking_error 0.005 不被 abs<0.001 跳过
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.factors import factor_registry as fr_mod
from app.factors.factor_registry import FactorRegistry
from app.fetchers import hk_hot_fetcher
from app.routers import market as market_router


# ── P2-AF/AH + P0-D: watchlist enrich 分组批量 ──────────────────────────

def _item(symbol, asset_type, name="x"):
    return SimpleNamespace(id=1, symbol=symbol, name=name, asset_type=asset_type,
                           notes="", created_at=None, updated_at=None)


class TestWatchlistGroupedBatch:
    @pytest.mark.asyncio
    async def test_stock_asset_type_routes_to_a_batch(self):
        """P2-AF: asset_type='stock'（301317 江波龙）→ 走 A 股批量 get_realtime_batch。"""
        items = [_item("301317", "stock", "江波龙")]
        calls = {"a": 0, "hk": 0, "us": 0}

        async def _fake_batch(symbols, asset_type):
            calls[asset_type.lower()] += 1
            return [{"symbol": s, "price": 42.0, "change_pct": 0.5, "volume": 100} for s in symbols]

        with patch("app.routers.market.market_data_hub.get_asset_realtime", new=AsyncMock(return_value=None)), \
             patch("app.services.market_service.get_realtime_batch", side_effect=_fake_batch), \
             patch("app.routers.market.async_session"):
            result = await market_router._watchlist_enrich_items(items)
        assert calls["a"] == 1, "stock 应走 A 股批量路径"
        assert result[0]["realtime"]["price"] == 42.0

    @pytest.mark.asyncio
    async def test_hk_symbols_use_hk_batch(self):
        """P2-AH: HK 标的三只 → get_realtime_batch(...,'HK')（修复前 per-item 截断）。"""
        items = [_item("00700", "HK"), _item("09988", "HK"), _item("03690", "HK")]
        calls = {"a": 0, "hk": 0, "us": 0}

        async def _fake_batch(symbols, asset_type):
            calls[asset_type.lower()] += 1
            return [{"symbol": s, "price": 100.0, "change_pct": 0.1, "volume": 1000} for s in symbols]

        with patch("app.routers.market.market_data_hub.get_asset_realtime", new=AsyncMock(return_value=None)), \
             patch("app.services.market_service.get_realtime_batch", side_effect=_fake_batch):
            result = await market_router._watchlist_enrich_items(items)
        assert calls["hk"] == 1
        assert all(it["realtime"]["price"] == 100.0 for it in result)

    @pytest.mark.asyncio
    async def test_degraded_marker_injected_when_all_sources_fail(self):
        """P0-D: 全源失败 → realtime 显式 null + _degraded:true（不再丢键）。"""
        items = [_item("600519", "A", "贵州茅台")]

        async def _fail_batch(symbols, asset_type):
            raise asyncio.TimeoutError("slow source")

        with patch("app.routers.market.market_data_hub.get_asset_realtime", new=AsyncMock(return_value=None)), \
             patch("app.services.market_service.get_realtime_batch", side_effect=_fail_batch), \
             patch("app.services.cache_service.cache_get", new=AsyncMock(return_value=None)):
            result = await market_router._watchlist_enrich_items(items)
        item = result[0]
        assert item["realtime"] is None
        assert item["_degraded"] is True

    @pytest.mark.asyncio
    async def test_single_a_symbol_still_batches(self):
        """P2-AF/AH: 去掉 len>=2 门槛——单只也走批量（不落 per-item）。"""
        items = [_item("510300", "A")]
        calls = {"a": 0}

        async def _fake_batch(symbols, asset_type):
            calls["a"] += 1
            return [{"symbol": s, "price": 3.8, "change_pct": 0.0, "volume": 1} for s in symbols]

        with patch("app.routers.market.market_data_hub.get_asset_realtime", new=AsyncMock(return_value=None)), \
             patch("app.services.market_service.get_realtime_batch", side_effect=_fake_batch):
            result = await market_router._watchlist_enrich_items(items)
        assert calls["a"] == 1
        assert result[0]["realtime"]["price"] == 3.8


# ── P2-AG: 港股指数搜索过滤 ─────────────────────────────────────────────

class TestSearchIndicesMarketFilter:
    @pytest.mark.asyncio
    async def test_hk_market_filters_indices(self):
        """P2-AG: _search_indices(kw, market='HK') 只返回 HK 指数。"""
        class _FakeIndex:
            symbol = "HSI"
            name = "恒生指数"
            market = "HK"
            is_active = True
            pinyin = "hangsheng"
            first_letter = "HS"

        class _FakeResult:
            def scalars(self):
                return self
            def all(self):
                return [_FakeIndex()]

        class _FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def execute(self, stmt):
                # 捕获 SQL 以断言 market 过滤
                self._sql = str(stmt)
                return _FakeResult()

        sess = _FakeSession()
        with patch("app.routers.market.async_session", return_value=sess):
            result = await market_router._search_indices("恒生", market="HK")
        assert len(result) == 1
        assert result[0]["market"] == "HK"
        assert "market = :market_1" in sess._sql or "market = :" in sess._sql or "='HK'" in sess._sql


# ── P2-AI: 港股热门个股过滤 ─────────────────────────────────────────────

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


# ── P2-Z: tracking_error / shares_change 两因子 ─────────────────────────

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


# ── P2-AK/AN: 美股热点板块 + 美股 PE ──────────────────────────────────

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


# ── P2-AE: 板块热度财联社 plate_code join ──────────────────────────────

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
    async def test_plate_code_miss_falls_back_em_and_zero(self):
        """P2-AE 负向: plate_code 未命中 → 东财名称兜底 → 仍未命中保持 0（现有行为）。"""
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
        assert resp["items"][0]["change_pct"] == 0

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


# ── P2-AJ: 美股/港股综合研判 news 按市场选源 ─────────────────────────────

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
