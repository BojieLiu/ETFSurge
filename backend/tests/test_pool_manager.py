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
    def pool_manager(self, mock_scanner, mock_classifier):
        from app.services.pool_manager import PoolManager
        pm = PoolManager()
        pm.scanner = mock_scanner
        pm.classifier = mock_classifier
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
        """每次 refresh() 版本号递增"""
        diff1 = await pool_manager.refresh()
        diff2 = await pool_manager.refresh()
        assert diff2.version == diff1.version + 1

    @pytest.mark.asyncio
    async def test_empty_scanner_returns_empty_pool(self, mock_classifier):
        """扫描器返回空时池也应为空"""
        from app.services.pool_manager import PoolManager
        pm = PoolManager()
        pm.scanner = MagicMock()
        pm.scanner.full_pipeline.return_value = {"core": [], "satellite": [], "defense": []}
        pm.classifier = mock_classifier
        diff = await pm.refresh()
        pool = pm.get_pool()
        total = sum(len(v) for v in pool.values())
        assert total == 0  # 没有 MANDATORY_CODES 时为空
        # 但强制保留的 MANDATORY_CODES 不应出现在空池中（扫描失败应报错）
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
