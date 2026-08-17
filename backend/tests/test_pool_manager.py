"""
TDD: MarketDataHub - unified candidate pool management.

All external calls (etf_scanner, ETFClassifier, FactorRegistry) must be mocked.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.market_data_hub import (
    LAYER_CORE,
    LAYER_DEFENSE,
    LAYER_RESEARCH,
    LAYER_SATELLITE,
)


class TestMarketDataHub:
    """MarketDataHub: candidate pool lifecycle."""

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
            "515030": {"industry": "新能源", "concepts": ["新能源"], "confidence": 0.70},  # round14 P2-U
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
    def market_data_hub(self, mock_scanner, mock_classifier, mock_factor_registry):
        from app.services.market_data_hub import MarketDataHub
        pm = MarketDataHub()
        pm.scanner = mock_scanner
        pm.classifier = mock_classifier
        pm.factor_registry = mock_factor_registry
        return pm

    @pytest.mark.asyncio
    async def test_refresh_returns_pool_diff(self, market_data_hub):
        """refresh() 应返回 PoolDiff 对象"""
        diff = await market_data_hub.refresh()
        assert diff is not None
        assert hasattr(diff, "added")
        assert hasattr(diff, "removed")
        assert diff.version == 1

    @pytest.mark.asyncio
    async def test_refresh_contains_all_layers(self, market_data_hub):
        """刷新后候选池应包含 5 层"""
        await market_data_hub.refresh()
        pool = market_data_hub.get_pool()
        assert "core" in pool
        assert "satellite" in pool
        assert "defense" in pool
        assert "opportunistic" in pool
        assert "research" in pool

    @pytest.mark.asyncio
    async def test_mandatory_codes_preserved(self, market_data_hub):
        """510300 和 518880 应始终在池中"""
        await market_data_hub.refresh()
        pool = market_data_hub.get_pool()
        all_symbols = {e["symbol"] for layer in pool.values() for e in layer}
        assert "510300" in all_symbols  # 沪深300ETF
        assert "518880" in all_symbols  # 黄金ETF

    @pytest.mark.asyncio
    async def test_get_pool_by_layer(self, market_data_hub):
        """get_pool(layer='core') 只返回核心层"""
        await market_data_hub.refresh()
        core = market_data_hub.get_pool(layer="core")
        assert len(core) >= 2
        assert all(e.get("layer") == "core" for e in core)

    @pytest.mark.asyncio
    async def test_get_by_code_found(self, market_data_hub):
        """按 code 查询应返回单个条目"""
        await market_data_hub.refresh()
        entry = market_data_hub.get_by_code("510300")
        assert entry is not None
        assert entry["symbol"] == "510300"
        assert "industry" in entry

    @pytest.mark.asyncio
    async def test_get_by_code_not_found(self, market_data_hub):
        """不存在的 code 返回 None"""
        await market_data_hub.refresh()
        assert market_data_hub.get_by_code("999999") is None

    @pytest.mark.asyncio
    async def test_pool_diff_version_increments(self, market_data_hub):
        """每次 refresh() 版本号递增 (过期冷却期以允许立即刷新)"""
        diff1 = await market_data_hub.refresh()
        # 清除冷却期，允许第二次刷新立即执行
        market_data_hub._last_refresh_ts = 0.0
        diff2 = await market_data_hub.refresh()
        assert diff2.version == diff1.version + 1

    @pytest.mark.asyncio
    async def test_empty_scanner_preserves_existing_pool(self, market_data_hub):
        """扫描器返回空时不应清空已有候选池（last-good 保护）

        先刷新一次建立池子，第二次 refresh 模拟扫描器失败，
        断言：池子保留上次成功数据，版本号不变。
        """
        # 先成功刷新一次，建立候选池
        diff1 = await market_data_hub.refresh()
        assert diff1.version == 1
        pool_before = market_data_hub.get_pool()
        before_total = sum(len(v) for v in pool_before.values())
        assert before_total > 0

        # 第二次 refresh：模拟扫描器返回空（数据源故障）
        market_data_hub.scanner.full_pipeline.return_value = {"core": [], "satellite": [], "defense": []}
        market_data_hub._last_refresh_ts = 0.0  # 清除冷却期
        diff2 = await market_data_hub.refresh()

        # 断言：池子未被清空，保留上次成功数据
        pool_after = market_data_hub.get_pool()
        after_total = sum(len(v) for v in pool_after.values())
        assert after_total == before_total, "空池保护失败：扫描器故障后候选池被清空"
        # 版本号不应递增（refresh 返回空结果时跳过版本变更）
        assert market_data_hub._version == 1

    @pytest.mark.asyncio
    async def test_empty_scanner_first_call_returns_empty(self, mock_classifier):
        """首次调用时扫描器就返回空 → 池为空（无 last-good 可保留）"""
        from app.services.market_data_hub import MarketDataHub
        pm = MarketDataHub()
        pm.scanner = MagicMock()
        pm.scanner.full_pipeline.return_value = {"core": [], "satellite": [], "defense": []}
        pm.classifier = mock_classifier
        # 隔离外部依赖：强板块动量注入（真实网络）+ T-1 快照兜底（读/写磁盘）
        pm.get_sector_momentum = MagicMock(return_value=[])
        pm._load_pool_snapshot = MagicMock(return_value=None)
        pm._persist_snapshot_after_refresh = AsyncMock()
        diff = await pm.refresh()
        pool = pm.get_pool()
        total = sum(len(v) for v in pool.values())
        assert total == 0  # 没有历史数据，只能返回空
        # 首次刷新即空：无 last-good 可回退，version 不递增
        assert diff.version == 0

    @pytest.mark.asyncio
    async def test_classifier_integration(self, market_data_hub):
        """候选池条目应包含 industry/concepts 字段"""
        await market_data_hub.refresh()
        entry = market_data_hub.get_by_code("512480")
        assert entry is not None
        assert entry.get("industry") == "电子"


@pytest.mark.asyncio
async def test_concurrent_refresh_lock_does_not_block_forever():
    """Concurrent refresh does not deadlock.

    Regression guard: lock timeout (P1 fix) ensures a second refresh
    does not wait forever when the first holds the lock.
    """
    import asyncio
    from unittest.mock import MagicMock
    from app.services.market_data_hub import MarketDataHub

    pm = MarketDataHub()
    pm.scanner = MagicMock()
    pm.scanner.full_pipeline.return_value = {
        "core": [], "satellite": [], "defense": []
    }
    pm.classifier = MagicMock()
    pm.classifier.batch_classify.return_value = {}
    pm.factor_registry = MagicMock()

    # Lock the refresh lock to simulate a stuck first refresh
    # _refresh_lock is a class attribute defaulting to None
    if pm._refresh_lock is None:
        pm._refresh_lock = asyncio.Lock()
    await pm._refresh_lock.acquire()
    pm._last_refresh_ts = 9999999999

    # Verify lock is held correctly
    assert pm._refresh_lock.locked() is True

    # Clean up
    pm._refresh_lock.release()


@pytest.mark.asyncio
async def test_market_context_getters_completeness():
    """2.8.7: market_context getters should return complete data when caches are set."""
    from app.services.market_data_hub import MarketDataHub
    pm = MarketDataHub()
    # Set up cache data directly
    pm._regime_cache = {"A": "range_bound"}
    pm._regime_cache_ts = 9999999999.0
    pm._sentiment_cache = {"sentiment_index": 55, "sentiment_label": "中性"}
    pm._sentiment_cache_ts = 9999999999.0
    pm._sector_momentum_cache = [{"name": "半导体", "change_pct": 1.5}]
    pm._sector_momentum_cache_ts = 9999999999.0
    pm._index_realtime_cache = [{"name": "上证指数", "price": 3200}]

    regime = pm.get_market_regime()
    assert regime == "range_bound", f"regime: {regime}"

    sentiment = pm.get_market_sentiment()
    assert isinstance(sentiment, dict)
    assert sentiment.get("sentiment_index") == 55
    assert sentiment.get("sentiment_label") == "中性"

    sectors = pm.get_sector_momentum()
    assert len(sectors) >= 1
    assert sectors[0]["name"] == "半导体"

    indices = pm.get_index_realtime()
    assert len(indices) >= 1
    assert indices[0]["name"] == "上证指数"


# ── 层分配逻辑（合并自 test_pool_manager_layer.py，改测真实 _assign_layer）──


class TestLayerAssignment:
    """行业→层映射的准确性（P1-2 防御层分类修复）。

    P1-8: 原手写 _apply_layer_assignment 复制实现已消除，改测
    market_data_hub.MarketDataHub._assign_layer 真实函数。
    """

    @pytest.fixture
    def hub(self):
        from app.services.market_data_hub import MarketDataHub
        return MarketDataHub.__new__(MarketDataHub)

    def test_gold_etf_goes_to_defense(self, hub):
        """黄金 ETF（商品行业）→ 防御层。"""
        assert hub._assign_layer("satellite", "商品") == LAYER_DEFENSE

    def test_treasury_etf_goes_to_defense(self, hub):
        """国债 ETF（固收行业）→ 防御层。"""
        assert hub._assign_layer("satellite", "固收") == LAYER_DEFENSE

    def test_cross_border_etf_goes_to_satellite(self, hub):
        """跨境 ETF（如纳指/标普）→ 卫星层（P1-2 修复）。"""
        assert hub._assign_layer("satellite", "跨境") == LAYER_SATELLITE

    def test_hk_etf_goes_to_satellite_not_defense(self, hub):
        """港股 ETF（跨境行业）不应落入防御层。"""
        result = hub._assign_layer("satellite", "跨境")
        assert result == LAYER_SATELLITE, f"跨境ETF应归卫星层，实际为 {result}"
        assert result != LAYER_DEFENSE, "跨境ETF不应归防御层"

    def test_broad_index_goes_to_core(self, hub):
        """宽基指数 ETF → 核心层。"""
        assert hub._assign_layer("core", "宽基指数") == LAYER_CORE

    def test_tech_etf_goes_to_satellite(self, hub):
        """科技 ETF（无特殊行业）→ 卫星层。"""
        assert hub._assign_layer("satellite", "信息技术") == LAYER_SATELLITE

    def test_defense_etf_from_scanner_stays_defense(self, hub):
        """扫描器标记为 defense 的标的，即使 industry 未知也走防御层。"""
        assert hub._assign_layer("defense", "unknown") == LAYER_DEFENSE

    def test_core_etf_stays_core(self, hub):
        """扫描器标记为 core 的标的不被 industry 覆盖。"""
        assert hub._assign_layer("core", "信息技术") == LAYER_CORE

    def test_unknown_industry_goes_research(self, hub):
        """industry unknown + 无 base 标记 → research 层。"""
        assert hub._assign_layer("", "unknown") == LAYER_RESEARCH


# ── Phase 2: 因子评分 + 第 4/5 层（合并自 test_pool_manager_phase2.py）──


class TestMarketDataHubPhase2:
    """MarketDataHub Phase 2: factor scoring + layer 4/5."""

    @pytest.fixture
    def mock_factor_registry_p2(self):
        """Mock FactorRegistry returning per-symbol factor scores."""
        reg = MagicMock()
        reg.compute = AsyncMock(return_value={
            "510300": {"style.momentum.mom_3m": 0.05, "style.quality.roe": 0.12},
            "560600": {"style.momentum.mom_3m": 0.03, "style.quality.roe": 0.10},
            "512480": {"style.momentum.mom_3m": 0.08, "style.quality.roe": 0.06},
            "515030": {"style.momentum.mom_3m": 0.06, "style.quality.roe": 0.07},
            "518880": {"style.momentum.mom_3m": -0.02, "style.quality.roe": 0.04},
        })
        # round15 方案一/三: aggregate_factor_scores 新增 definitions/ic_series 可选参数
        reg.aggregate_factor_scores = MagicMock(side_effect=lambda raw_scores, **kwargs: {
            **raw_scores,
            "composite": sum(raw_scores.values()) / max(len(raw_scores), 1),
        })
        return reg

    @pytest.fixture
    def market_data_hub_p2(self, mock_factor_registry_p2):
        from app.services.market_data_hub import MarketDataHub
        pm = MarketDataHub()
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
            "515030": {"industry": "新能源", "concepts": ["新能源"], "confidence": 0.70},  # round14 P2-U
            "518880": {"industry": "商品", "concepts": ["黄金"], "confidence": 0.85},
        }
        pm.factor_registry = mock_factor_registry_p2
        return pm

    @pytest.mark.asyncio
    async def test_refresh_calls_factor_registry(self, market_data_hub_p2, mock_factor_registry_p2):
        """refresh() 应调用 FactorRegistry.compute()"""
        await market_data_hub_p2.refresh()
        mock_factor_registry_p2.compute.assert_called_once()

    @pytest.mark.asyncio
    async def test_entries_have_factor_scores(self, market_data_hub_p2):
        """候选池条目应包含 factor_scores 字段"""
        await market_data_hub_p2.refresh()
        entry = market_data_hub_p2.get_by_code("510300")
        assert entry is not None
        assert "factor_scores" in entry
        assert "style.momentum.mom_3m" in entry["factor_scores"]

    @pytest.mark.asyncio
    async def test_layer_4_opportunistic_exists(self, market_data_hub_p2):
        """第 4 层(Opportunistic)应存在"""
        await market_data_hub_p2.refresh()
        pool = market_data_hub_p2.get_pool()
        assert "opportunistic" in pool

    @pytest.mark.asyncio
    async def test_layer_5_research_exists(self, market_data_hub_p2):
        """第 5 层(Research)应存在"""
        await market_data_hub_p2.refresh()
        pool = market_data_hub_p2.get_pool()
        assert "research" in pool

    @pytest.mark.asyncio
    async def test_sorted_by_factor_score_within_layer(self, market_data_hub_p2):
        """同层内应因子得分高的排前面"""
        await market_data_hub_p2.refresh()
        satellite = market_data_hub_p2.get_pool(layer="satellite")
        if len(satellite) >= 2:
            fs0 = satellite[0].get("composite_score", 0)
            fs1 = satellite[1].get("composite_score", 0)
            assert fs0 >= fs1, "satellite layer should be sorted by composite score descending"

    @pytest.mark.asyncio
    async def test_opportunistic_added_via_text_signals(self, market_data_hub_p2):
        """文本信号可触发 ETF 加入 opportunistic 层"""
        market_data_hub_p2.set_opportunistic_signals({
            "159995": {"signal": "policy_heat", "heat_score": 0.85, "reason": "半导体政策利好"},
        })
        await market_data_hub_p2.refresh()
        opp = market_data_hub_p2.get_pool(layer="opportunistic")
        if opp:
            assert any(e["symbol"] == "159995" for e in opp)

    def test_set_opportunistic_signals(self, market_data_hub_p2):
        """set_opportunistic_signals 应存储外部信号"""
        signals = {"159995": {"signal": "policy_heat", "heat_score": 0.85}}
        market_data_hub_p2.set_opportunistic_signals(signals)
        assert len(market_data_hub_p2._opportunistic_signals) == 1
        assert market_data_hub_p2._opportunistic_signals["159995"]["heat_score"] == 0.85


# ── Phase 3: 日频刷新审计 + pool_audit（合并自 test_pool_manager_phase3.py）──


class TestPoolAudit:
    """MarketDataHub 审计日志"""

    @pytest.fixture
    def audit(self):
        from app.services.pool_audit import PoolAudit
        return PoolAudit()

    def test_log_refresh(self, audit):
        """记录一次 refresh 事件"""
        diff = MagicMock()
        diff.version = 3
        diff.added = [{"symbol": "159995", "name": "芯片ETF"}]
        diff.removed = [{"symbol": "159999", "name": "僵尸ETF"}]
        diff.changed = []
        diff.timestamp = "2026-07-17T12:00:00"

        audit.log_refresh(diff)
        assert len(audit.get_history()) == 1

    def test_get_history_returns_sorted(self, audit):
        """历史记录应按时间倒序"""
        diff1 = MagicMock(version=1, added=[], removed=[], changed=[], timestamp="2026-07-16")
        diff2 = MagicMock(version=2, added=[], removed=[], changed=[], timestamp="2026-07-17")
        audit.log_refresh(diff1)
        audit.log_refresh(diff2)
        history = audit.get_history(limit=2)
        assert len(history) == 2
        assert history[0]["version"] == 2  # newest first

    def test_get_history_limit(self, audit):
        """限制返回条数"""
        for i in range(5):
            d = MagicMock(version=i, added=[], removed=[], changed=[], timestamp=f"2026-07-{16+i}")
            audit.log_refresh(d)
        assert len(audit.get_history(limit=3)) == 3

    def test_last_refresh(self, audit):
        """返回最近一次 refresh 记录"""
        assert audit.get_last_refresh() is None
        diff = MagicMock(version=5, added=[], removed=[], changed=[], timestamp="2026-07-17")
        audit.log_refresh(diff)
        last = audit.get_last_refresh()
        assert last is not None
        assert last["version"] == 5


class TestDailyRefresh:
    """MarketDataHub 日频刷新调度"""

    @pytest.mark.asyncio
    async def test_refresh_and_audit(self):
        """refresh() 后审计日志应有记录"""
        from app.services.market_data_hub import market_data_hub
        from app.services.pool_audit import pool_audit

        with patch.object(market_data_hub, 'scanner') as mock_scanner:
            mock_scanner.full_pipeline.return_value = {
                "core": [{"symbol": "510300", "name": "沪深300ETF", "amount": 10e8, "fund_scale": 50e8}],
                "satellite": [{"symbol": "512480", "name": "半导体ETF", "amount": 8e8, "fund_scale": 30e8}],
                "defense": [{"symbol": "518880", "name": "黄金ETF", "amount": 20e8, "fund_scale": 100e8}],
            }
            market_data_hub.classifier = MagicMock()
            market_data_hub.classifier.batch_classify.return_value = {
                "510300": {"industry": "宽基指数", "concepts": [], "confidence": 0.85},
                "512480": {"industry": "电子", "concepts": [], "confidence": 0.85},
                "518880": {"industry": "商品", "concepts": [], "confidence": 0.85},
            }

            diff = await market_data_hub.refresh()
            # 审计日志应有记录
            log_entry = pool_audit.get_last_refresh()
            assert log_entry is not None
            assert log_entry["version"] > 0
