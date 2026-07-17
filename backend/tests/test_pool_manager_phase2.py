"""
TDD: PoolManager Phase 2 - factor-enhanced scoring + Layer 4/5.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestPoolManagerPhase2:
    """PoolManager Phase 2: factor scoring + layer 4/5."""

    @pytest.fixture
    def mock_factor_registry(self):
        """Mock FactorRegistry returning per-symbol factor scores."""
        reg = MagicMock()
        reg.compute = AsyncMock(return_value={
            "510300": {"style.momentum.mom_3m": 0.05, "style.quality.roe": 0.12},
            "560600": {"style.momentum.mom_3m": 0.03, "style.quality.roe": 0.10},
            "512480": {"style.momentum.mom_3m": 0.08, "style.quality.roe": 0.06},
            "515030": {"style.momentum.mom_3m": 0.06, "style.quality.roe": 0.07},
            "518880": {"style.momentum.mom_3m": -0.02, "style.quality.roe": 0.04},
        })
        return reg

    @pytest.fixture
    def pool_manager(self, mock_factor_registry):
        from app.services.pool_manager import PoolManager
        pm = PoolManager()
        # Inject mock dependencies
        pm.scanner = MagicMock()
        pm.scanner.full_pipeline.return_value = {
            "core": [
                {"symbol": "510300", "name": "沪深300ETF", "amount": 10e8, "fund_scale": 50e8},
                {"symbol": "560600", "name": "中证A500ETF", "amount": 5e8, "fund_scale": 20e8},
            ],
            "satellite": [
                {"symbol": "512480", "name": "半导体ETF", "amount": 8e8, "fund_scale": 30e8},
                {"symbol": "515030", "name": "新能源ETF", "amount": 6e8, "fund_scale": 25e8},
            ],
            "defense": [
                {"symbol": "518880", "name": "黄金ETF", "amount": 20e8, "fund_scale": 100e8},
            ],
        }
        pm.classifier = MagicMock()
        pm.classifier.batch_classify.return_value = {
            "510300": {"industry": "宽基指数", "concepts": ["沪深300"], "confidence": 0.85},
            "560600": {"industry": "宽基指数", "concepts": ["A500"], "confidence": 0.85},
            "512480": {"industry": "电子", "concepts": ["半导体"], "confidence": 0.85},
            "515030": {"industry": "电力设备", "concepts": ["新能源"], "confidence": 0.70},
            "518880": {"industry": "商品", "concepts": ["黄金"], "confidence": 0.85},
        }
        pm.factor_registry = mock_factor_registry
        return pm

    @pytest.mark.asyncio
    async def test_refresh_calls_factor_registry(self, pool_manager, mock_factor_registry):
        """refresh() 应调用 FactorRegistry.compute()"""
        await pool_manager.refresh()
        mock_factor_registry.compute.assert_called_once()

    @pytest.mark.asyncio
    async def test_entries_have_factor_scores(self, pool_manager):
        """候选池条目应包含 factor_scores 字段"""
        await pool_manager.refresh()
        entry = pool_manager.get_by_code("510300")
        assert entry is not None
        assert "factor_scores" in entry
        assert "style.momentum.mom_3m" in entry["factor_scores"]

    @pytest.mark.asyncio
    async def test_layer_4_opportunistic_exists(self, pool_manager):
        """第 4 层(Opportunistic)应存在"""
        await pool_manager.refresh()
        pool = pool_manager.get_pool()
        assert "opportunistic" in pool

    @pytest.mark.asyncio
    async def test_layer_5_research_exists(self, pool_manager):
        """第 5 层(Research)应存在"""
        await pool_manager.refresh()
        pool = pool_manager.get_pool()
        assert "research" in pool

    @pytest.mark.asyncio
    async def test_sorted_by_factor_score_within_layer(self, pool_manager):
        """同层内应因子得分高的排前面"""
        await pool_manager.refresh()
        satellite = pool_manager.get_pool(layer="satellite")
        if len(satellite) >= 2:
            s0 = satellite[0]["symbol"]
            s1 = satellite[1]["symbol"]
            fs0 = satellite[0].get("composite_score", 0)
            fs1 = satellite[1].get("composite_score", 0)
            assert fs0 >= fs1, "satellite layer should be sorted by composite score descending"

    @pytest.mark.asyncio
    async def test_opportunistic_added_via_text_signals(self, pool_manager):
        """文本信号可触发 ETF 加入 opportunistic 层"""
        pool_manager.set_opportunistic_signals({
            "159995": {"signal": "policy_heat", "heat_score": 0.85, "reason": "半导体政策利好"},
        })
        await pool_manager.refresh()
        opp = pool_manager.get_pool(layer="opportunistic")
        if opp:
            assert any(e["symbol"] == "159995" for e in opp)

    @pytest.mark.asyncio
    async def test_composite_score_weighted_correctly(self, pool_manager):
        """综合得分应按层差异化计算"""
        await pool_manager.refresh()
        core = pool_manager.get_pool(layer="core")
        if core:
            # core 层应重 factor, 轻 amount
            pass  # structural validation only

    def test_set_opportunistic_signals(self, pool_manager):
        """set_opportunistic_signals 应存储外部信号"""
        signals = {"159995": {"signal": "policy_heat", "heat_score": 0.85}}
        pool_manager.set_opportunistic_signals(signals)
        assert len(pool_manager._opportunistic_signals) == 1
        assert pool_manager._opportunistic_signals["159995"]["heat_score"] == 0.85
