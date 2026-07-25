"""
TDD: PoolManager - unified candidate pool management.

All external calls (etf_scanner, ETFClassifier, FactorRegistry) must be mocked.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


class TestPoolManager:
    """PoolManager: candidate pool lifecycle."""

    @pytest.fixture
    def mock_scanner(self):
        """Mock etf_scanner.full_pipeline returning 3 layers."""
        scanner = MagicMock()
        scanner.full_pipeline.return_value = {
            "core": [
                {"symbol": "510300", "name": "沪深300ETF", "amount": 10e8, "fund_scale": 50e8},
                {"symbol": "560600", "name": "中证A500ETF", "amount": 5e8, "fund_scale": 20e8},
            ],
            "satellite": [
                {"symbol": "512480", "name": "半导体ETF", "amount": 8e8, "fund_scale": 30e8},
                {"symbol": "515030", "name": "新能源ETF", "amount": 6e8, "fund_scale": 25e8},
                {"symbol": "512010", "name": "医药ETF", "amount": 4e8, "fund_scale": 15e8},
            ],
            "defense": [
                {"symbol": "518880", "name": "黄金ETF", "amount": 20e8, "fund_scale": 100e8},
                {"symbol": "511090", "name": "30年国债ETF", "amount": 10e8, "fund_scale": 80e8},
            ],
        }
        return scanner

    @pytest.fixture
    def mock_classifier(self):
        """Mock ETFClassifier returning industry/concept data."""
        classifier = MagicMock()
        classifier.batch_classify.return_value = {
            "510300": {"industry": "宽基指数", "concepts": ["沪深300"], "confidence": 0.85},
            "560600": {"industry": "宽基指数", "concepts": ["A500"], "confidence": 0.85},
            "512480": {"industry": "电子", "concepts": ["半导体", "芯片"], "confidence": 0.85},
            "515030": {"industry": "电力设备", "concepts": ["新能源"], "confidence": 0.70},
            "512010": {"industry": "医药生物", "concepts": ["医药"], "confidence": 0.70},
            "518880": {"industry": "商品", "concepts": ["黄金"], "confidence": 0.85},
            "511090": {"industry": "固收", "concepts": ["国债"], "confidence": 0.85},
        }
        return classifier

    @pytest.fixture
    def mock_factor_registry(self):
        """Mock FactorRegistry.compute to return synthetic scores (no network)."""
        from unittest.mock import AsyncMock
        registry = MagicMock()
        registry.compute = AsyncMock(return_value={
            "510300": {"technical": 0.5, "momentum": 0.3},
            "560600": {"technical": 0.4, "momentum": 0.2},
            "512480": {"technical": 0.6, "momentum": 0.5},
            "515030": {"technical": -0.1, "momentum": 0.1},
            "512010": {"technical": -0.3, "momentum": -0.2},
            "518880": {"technical": 0.2, "momentum": 0.0},
            "511090": {"technical": 0.3, "momentum": -0.1},
        })
        registry.aggregate_factor_scores = MagicMock(return_value={"technical": 0.5, "momentum": 0.3})
        return registry

    @pytest.fixture
    def pool_manager(self, mock_scanner, mock_classifier, mock_factor_registry):
        from app.services.pool_manager import PoolManager
        pm = PoolManager()
        pm.scanner = mock_scanner
        pm.classifier = mock_classifier
        pm.factor_registry = mock_factor_registry
        return pm

    @pytest.mark.asyncio
    async def test_refresh_returns_pool_diff(self, pool_manager):
        """refresh() 应返回 PoolDiff 对象"""
        diff = await pool_manager.refresh()
        assert diff is not None
        assert hasattr(diff, "added")
        assert hasattr(diff, "removed")
        assert diff.version == 1

    @pytest.mark.asyncio
    async def test_refresh_contains_all_layers(self, pool_manager):
        """刷新后候选池应包含 5 层"""
        await pool_manager.refresh()
        pool = pool_manager.get_pool()
        assert "core" in pool
        assert "satellite" in pool
        assert "defense" in pool
        assert "opportunistic" in pool
        assert "research" in pool

    @pytest.mark.asyncio
    async def test_mandatory_codes_preserved(self, pool_manager):
        """510300 和 518880 应始终在池中"""
        await pool_manager.refresh()
        pool = pool_manager.get_pool()
        all_symbols = {e["symbol"] for layer in pool.values() for e in layer}
        assert "510300" in all_symbols  # 沪深300ETF
        assert "518880" in all_symbols  # 黄金ETF

    @pytest.mark.asyncio
    async def test_get_pool_by_layer(self, pool_manager):
        """get_pool(layer='core') 只返回核心层"""
        await pool_manager.refresh()
        core = pool_manager.get_pool(layer="core")
        assert len(core) >= 2
        assert all(e.get("layer") == "core" for e in core)

    @pytest.mark.asyncio
    async def test_get_by_code_found(self, pool_manager):
        """按 code 查询应返回单个条目"""
        await pool_manager.refresh()
        entry = pool_manager.get_by_code("510300")
        assert entry is not None
        assert entry["symbol"] == "510300"
        assert "industry" in entry

    @pytest.mark.asyncio
    async def test_get_by_code_not_found(self, pool_manager):
        """不存在的 code 返回 None"""
        await pool_manager.refresh()
        assert pool_manager.get_by_code("999999") is None

    @pytest.mark.asyncio
    async def test_pool_diff_version_increments(self, pool_manager):
        """每次 refresh() 版本号递增 (过期冷却期以允许立即刷新)"""
        diff1 = await pool_manager.refresh()
        # 清除冷却期，允许第二次刷新立即执行
        pool_manager._last_refresh_ts = 0.0
        diff2 = await pool_manager.refresh()
        assert diff2.version == diff1.version + 1

    @pytest.mark.asyncio
    async def test_empty_scanner_preserves_existing_pool(self, pool_manager):
        """扫描器返回空时不应清空已有候选池（last-good 保护）

        先刷新一次建立池子，第二次 refresh 模拟扫描器失败，
        断言：池子保留上次成功数据，版本号不变。
        """
        # 先成功刷新一次，建立候选池
        diff1 = await pool_manager.refresh()
        assert diff1.version == 1
        pool_before = pool_manager.get_pool()
        before_total = sum(len(v) for v in pool_before.values())
        assert before_total > 0

        # 第二次 refresh：模拟扫描器返回空（数据源故障）
        pool_manager.scanner.full_pipeline.return_value = {"core": [], "satellite": [], "defense": []}
        pool_manager._last_refresh_ts = 0.0  # 清除冷却期
        diff2 = await pool_manager.refresh()

        # 断言：池子未被清空，保留上次成功数据
        pool_after = pool_manager.get_pool()
        after_total = sum(len(v) for v in pool_after.values())
        assert after_total == before_total, "空池保护失败：扫描器故障后候选池被清空"
        # 版本号不应递增（refresh 返回空结果时跳过版本变更）
        assert pool_manager._version == 1

    @pytest.mark.asyncio
    async def test_empty_scanner_first_call_returns_empty(self, mock_classifier):
        """首次调用时扫描器就返回空 → 池为空（无 last-good 可保留）"""
        from app.services.pool_manager import PoolManager
        pm = PoolManager()
        pm.scanner = MagicMock()
        pm.scanner.full_pipeline.return_value = {"core": [], "satellite": [], "defense": []}
        pm.classifier = mock_classifier
        diff = await pm.refresh()
        pool = pm.get_pool()
        total = sum(len(v) for v in pool.values())
        assert total == 0  # 没有历史数据，只能返回空
        assert diff.version == 1

    @pytest.mark.asyncio
    async def test_classifier_integration(self, pool_manager):
        """候选池条目应包含 industry/concepts 字段"""
        await pool_manager.refresh()
        entry = pool_manager.get_by_code("512480")
        assert entry is not None
        assert entry.get("industry") == "电子"

    def test_pool_entry_structure(self, pool_manager):
        """PoolEntry 数据结构完整性"""
        # After refresh, check internal structure
        pass
