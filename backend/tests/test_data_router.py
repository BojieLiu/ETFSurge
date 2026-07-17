"""P1: DataRouter 智能路由 — 单元测试。所有外部调用必须 mock。"""

from unittest.mock import patch, MagicMock, AsyncMock
import pytest
import asyncio

from app.fetchers.router import DataRouter
from app.fetchers.source_registry import SourceRegistry


class TestDataRouter:
    """DataRouter 智能路由测试"""

    @pytest.fixture
    def router(self):
        return DataRouter()

    @pytest.fixture
    def mock_sources(self):
        """模拟数据源"""
        return {
            "tdx_pytdx": AsyncMock(return_value={"price": 100.0, "change": 1.5}),
            "sina_realtime": AsyncMock(return_value={"price": 100.0, "change": 1.5}),
            "tencent_realtime": AsyncMock(return_value={"price": 100.0, "change": 1.5}),
            "mootdx": AsyncMock(return_value={"price": 100.0, "change": 1.5}),
        }

    @pytest.mark.asyncio
    async def test_route_selects_first_available(self, router, mock_sources):
        """路由应选择第一个可用的数据源"""
        with patch.object(router, 'sources', mock_sources):
            result = await router.route("realtime", symbols=["510300"])
            assert result is not None
            assert "price" in result
            # 验证第一优先级源被调用
            mock_sources["tdx_pytdx"].assert_called_once()

    @pytest.mark.asyncio
    async def test_route_falls_back_on_failure(self, router, mock_sources):
        """首选源失败时应自动降级到下一优先级"""
        mock_sources["tdx_pytdx"].side_effect = Exception("Connection failed")
        
        with patch.object(router, 'sources', mock_sources):
            result = await router.route("realtime", symbols=["510300"])
            assert result is not None
            assert "price" in result
            # 验证降级到第二优先级
            mock_sources["sina_realtime"].assert_called_once()

    @pytest.mark.asyncio
    async def test_route_all_fail_returns_none(self, router, mock_sources):
        """所有源都失败时返回 None"""
        for source in mock_sources.values():
            source.side_effect = Exception("All failed")
        
        with patch.object(router, 'sources', mock_sources):
            result = await router.route("realtime", symbols=["510300"])
            assert result is None

    @pytest.mark.asyncio
    async def test_route_empty_symbols(self, router):
        """空符号列表应返回空结果"""
        result = await router.route("realtime", symbols=[])
        assert result == []


class TestSourceRegistry:
    """SourceRegistry 熔断路由测试"""

    @pytest.fixture
    def registry(self):
        return SourceRegistry()

    @pytest.mark.asyncio
    async def test_register_source(self, registry):
        """注册数据源"""
        async def dummy_fn():
            return {"data": "test"}
        
        registry.register("test_source", dummy_fn, tier=1)
        assert "test_source" in registry.sources
        assert registry.sources["test_source"]["tier"] == 1

    @pytest.mark.asyncio
    async def test_route_selects_by_tier(self, registry):
        """按优先级选择数据源"""
        results = []
        
        async def source1():
            results.append("source1")
            return {"data": "1"}
        
        async def source2():
            results.append("source2")
            return {"data": "2"}
        
        registry.register("source1", source1, tier=1)
        registry.register("source2", source2, tier=2)
        
        result = await registry.route()
        assert result == {"data": "1"}
        assert results == ["source1"]  # 只有 tier 1 被调用

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failure(self, registry):
        """连续失败触发熔断"""
        call_count = 0
        
        async def failing_source():
            nonlocal call_count
            call_count += 1
            raise Exception("API error")
        
        registry.register("failing", failing_source, tier=1, max_failures=3)
        
        # 连续失败 3 次后熔断
        for _ in range(3):
            with pytest.raises(Exception):
                await registry.route(source="failing")
        
        # 第 4 次应直接抛出熔断异常
        with pytest.raises(Exception, match="circuit breaker"):
            await registry.route(source="failing")

    @pytest.mark.asyncio
    async def test_circuit_breaker_resets_on_success(self, registry):
        """成功调用重置熔断器"""
        call_count = 0
        
        async def flaky_source():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("Temporary error")
            return {"data": "success"}
        
        registry.register("flaky", flaky_source, tier=1, max_failures=3)
        
        # 前两次失败
        for _ in range(2):
            with pytest.raises(Exception):
                await registry.route(source="flaky")
        
        # 第三次成功，熔断器重置
        result = await registry.route(source="flaky")
        assert result == {"data": "success"}


class TestDataRouterIntegration:
    """DataRouter 集成测试"""

    @pytest.mark.asyncio
    async def test_route_realtime_priority_chain(self):
        """实时行情完整优先级链路"""
        router = DataRouter()
        
        with patch.object(router, 'sources', {
            "tdx_pytdx": AsyncMock(side_effect=Exception("TDX down")),
            "sina_realtime": AsyncMock(return_value={"510300": {"price": 3.5, "change": 0.02}}),
            "tencent_realtime": AsyncMock(return_value={"510300": {"price": 3.5, "change": 0.02}}),
            "mootdx": AsyncMock(return_value={"510300": {"price": 3.5, "change": 0.02}}),
        }):
            result = await router.route("realtime", symbols=["510300"])
            assert result is not None
            assert "510300" in result
            assert result["510300"]["price"] == 3.5

    @pytest.mark.asyncio
    async def test_route_history_kline(self):
        """历史K线路由"""
        router = DataRouter()
        
        with patch.object(router, 'sources', {
            "tdx_local_csv": AsyncMock(return_value={"510300": [{"close": 3.5, "volume": 1000000}]}),
            "tdx_pytdx": AsyncMock(return_value={"510300": [{"close": 3.5, "volume": 1000000}]}),
        }):
            result = await router.route("history_kline", symbols=["510300"], period="D")
            assert result is not None

    @pytest.mark.asyncio
    async def test_route_fundamental(self):
        """基本面数据路由"""
        router = DataRouter()
        
        with patch.object(router, 'sources', {
            "tushare": AsyncMock(return_value={"pe": 12.5, "pb": 1.2}),
            "sina_finance": AsyncMock(return_value={"pe": 12.5, "pb": 1.2}),
        }):
            result = await router.route("fundamental", symbols=["510300"])
            assert result is not None
            assert "pe" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])