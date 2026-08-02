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
from app.services.source_registry import SourceRegistry


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

        h = reg._health("src_a")
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

        h = reg._health("src_b")
        with h._lock:
            assert h._failures == 0  # 达到阈值后已熔断并清零
            assert h._cool_until > 0, "异常累计到阈值必须熔断"

    def test_http_400_still_hard_failure(self):
        """N03: HTTP ≥400 仍走 record_hard_failure（硬失败语义不变）。"""
        reg = SourceRegistry()
        reg.route([("src_c", lambda: (None, 500))], route_name="test", target="x")

        h = reg._health("src_c")
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
