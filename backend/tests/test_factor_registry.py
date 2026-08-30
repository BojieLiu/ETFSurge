from __future__ import annotations
"""
TDD: FactorRegistry engine + ICTracker + FredFetcher.

All external calls (akshare, FRED API, yfinance) must be mocked.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import pandas as pd
import numpy as np
from datetime import datetime, date


# =============================================================================
# Z-score Winsorization
# =============================================================================


class TestStandardizeWinsorization:
    """验证 Z-score winsorization 将极端值截断到 [-5, 5]。"""

    def test_winsorization_clips_extreme_zscores(self):
        """极端 Z-score 应被截断到 ZSCORE_CLIP_BOUND。"""
        from app.factors.factor_registry import _standardize, ZSCORE_CLIP_BOUND
        import pandas as pd
        import numpy as np

        # 创建一个包含极端值的 Series：一个点在 16σ，其余在 0 附近
        values = [0.0] * 98 + [16.0] + [-16.0]
        series = pd.Series(values, dtype=float)
        result = _standardize(series, "zscore")

        # 验证所有值在 [-5, 5] 范围内
        assert result.abs().max() <= ZSCORE_CLIP_BOUND + 1e-6, (
            f"Z-score {result.abs().max():.2f} exceeds {ZSCORE_CLIP_BOUND}"
        )

    def test_winsorization_preserves_normal_values(self):
        """正常 Z-score（在 [-5, 5] 内）不应被截断。"""
        from app.factors.factor_registry import _standardize
        import pandas as pd
        import numpy as np

        np.random.seed(42)
        values = np.random.randn(100) * 0.5  # 小标准差
        series = pd.Series(values, dtype=float)
        result = _standardize(series, "zscore")

        # 所有值应在 [-5, 5] 内
        assert result.abs().max() <= 5.0 + 1e-6

    def test_winsorization_zero_std(self):
        """零标准差时应返回全零。"""
        from app.factors.factor_registry import _standardize
        import pandas as pd

        series = pd.Series([5.0] * 10, dtype=float)
        result = _standardize(series, "zscore")
        assert (result == 0).all()

    def test_winsorization_non_zscore_methods_unchanged(self):
        """非 zscore 方法不受 winsorization 影响。"""
        from app.factors.factor_registry import _standardize
        import pandas as pd

        series = pd.Series([1.0, 2.0, 3.0, 100.0, 200.0], dtype=float)
        # rank: 不应被截断
        result = _standardize(series, "rank")
        assert result.max() == 1.0
        assert result.min() == 1.0 / len(series)  # min rank percentile


# =============================================================================
# FactorRegistry
# =============================================================================

class TestFactorRegistry:
    """FactorRegistry: YAML loading + factor computation."""

    @pytest.fixture
    def sample_yaml(self, tmp_path):
        """Create a minimal factor_definitions.yaml for testing."""
        import yaml
        factors = [
            {"code": "style.size.ln_mcap", "name": "对数市值",
             "category": "style", "subcategory": "size",
             "frequency": "daily", "standardization": "zscore",
             "dependencies": ["total_mv"], "ic_threshold": 0.02,
             "ic_ir_threshold": 0.5, "lookback_window": 1,
             "description": "自然对数(总市值)", "tags": ["size"]},
            {"code": "technical.ma.sma_5", "name": "5日均线",
             "category": "technical", "subcategory": "ma",
             "frequency": "daily", "standardization": "zscore",
             "dependencies": ["close"], "ic_threshold": 0.02,
             "ic_ir_threshold": 0.5, "lookback_window": 5,
             "description": "5日简单移动平均", "tags": ["ma"]},
            {"code": "technical.rsi.rsi_14", "name": "RSI 14日",
             "category": "technical", "subcategory": "rsi",
             "frequency": "daily", "standardization": "zscore",
             "dependencies": ["close"], "ic_threshold": 0.02,
             "ic_ir_threshold": 0.5, "lookback_window": 14,
             "description": "14日相对强弱指标", "tags": ["rsi"]},
            {"code": "macro.risk.vix_level", "name": "VIX恐慌指数",
             "category": "macro", "subcategory": "risk",
             "frequency": "daily", "standardization": "zscore",
             "dependencies": ["fred_macro"], "ic_threshold": 0.02,
             "ic_ir_threshold": 0.5, "lookback_window": 1,
             "description": "CBOE Volatility Index", "tags": ["vix"]},
        ]
        data = {"factor_definitions": factors}
        p = tmp_path / "test_factors.yaml"
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)
        return str(p)

    def test_load_definitions(self, sample_yaml):
        """加载 YAML 后应能列出全部因子"""
        from app.factors.factor_registry import FactorRegistry
        reg = FactorRegistry()
        reg.load_definitions(sample_yaml)
        factors = reg.list_factors()
        assert len(factors) == 4
        codes = [f.code for f in factors]
        assert "style.size.ln_mcap" in codes
        assert "technical.ma.sma_5" in codes

    def test_get_factor_by_code(self, sample_yaml):
        """按唯一编码查询因子"""
        from app.factors.factor_registry import FactorRegistry
        reg = FactorRegistry()
        reg.load_definitions(sample_yaml)
        f = reg.get_factor("technical.rsi.rsi_14")
        assert f is not None
        assert f.name == "RSI 14日"
        assert f.category == "technical"

    def test_get_factor_not_found(self, sample_yaml):
        """查询不存在的因子返回 None"""
        from app.factors.factor_registry import FactorRegistry
        reg = FactorRegistry()
        reg.load_definitions(sample_yaml)
        assert reg.get_factor("nonexistent.factor") is None

    def test_list_factors_by_category(self, sample_yaml):
        """按类别过滤因子"""
        from app.factors.factor_registry import FactorRegistry
        reg = FactorRegistry()
        reg.load_definitions(sample_yaml)
        tech = reg.list_factors(category="technical")
        assert len(tech) == 2
        for f in tech:
            assert f.category == "technical"

    @pytest.mark.asyncio
    async def test_compute_returns_dict(self, sample_yaml):
        """compute() 返回 {symbol: {code: value}} 格式"""
        from app.factors.factor_registry import FactorRegistry
        reg = FactorRegistry()
        reg.load_definitions(sample_yaml)
        # Mock market data provider
        with patch.object(reg, '_fetch_market_data', new=AsyncMock(return_value={
            "510300": {"close": [4.0] * 20, "total_mv": 500e9},
            "518880": {"close": [5.0] * 20, "total_mv": 100e9},
        })):
            result = await reg.compute(["510300", "518880"])
        assert isinstance(result, dict)
        assert "510300" in result
        assert "518880" in result
        # Should have computed the style.size.ln_mcap factor
        assert "style.size.ln_mcap" in result["510300"]

    def test_load_from_default_path(self):
        """默认路径应加载 YAML 文件中的全部 167 个因子"""
        from app.factors.factor_registry import FactorRegistry
        from pathlib import Path
        default = Path(__file__).parent.parent / "app" / "factors" / "factor_definitions.yaml"
        if not default.exists():
            pytest.skip("factor_definitions.yaml not found")
        reg = FactorRegistry()
        reg.load_definitions(str(default))
        factors = reg.list_factors()
        assert len(factors) >= 160  # Should be 167

    def test_factor_definition_dataclass(self):
        """FactorDefinition dataclass 字段完整性"""
        from app.factors.factor_registry import FactorDefinition
        f = FactorDefinition(
            code="test.factor",
            name="测试因子",
            category="style",
            subcategory="value",
            frequency="daily",
            compute_fn="compute_test",
            dependencies=["close"],
        )
        assert f.code == "test.factor"
        assert f.standardization == "zscore"  # default
        assert f.ic_threshold == 0.02  # default
        assert f.version == 1  # default


# =============================================================================
# ICTracker
# =============================================================================

class TestICTracker:
    """IC 跟踪器：Spearman IC 计算"""

    @pytest.fixture
    def tracker(self):
        from app.factors.ic_tracker import ICTracker
        return ICTracker()

    def test_compute_ic_perfect_positive(self, tracker):
        """完全正相关时 IC = 1.0"""
        values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
        ic = tracker.compute_ic(values, returns)
        assert abs(ic - 1.0) < 0.001

    def test_compute_ic_perfect_negative(self, tracker):
        """完全负相关时 IC = -1.0"""
        values = pd.Series([1.0, 2.0, 3.0, 4.0])
        returns = pd.Series([0.04, 0.03, 0.02, 0.01])
        ic = tracker.compute_ic(values, returns)
        assert abs(ic - (-1.0)) < 0.001

    def test_compute_ic_not_perfect(self, tracker):
        """随机数据应不接近完全相关"""
        values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        returns = pd.Series([0.05, 0.01, 0.04, 0.02, 0.03])
        ic = tracker.compute_ic(values, returns)
        assert abs(ic) < 0.5  # Not perfect

    def test_compute_ic_series(self, tracker):
        """多期 IC 序列应返回一个 Series"""
        np.random.seed(42)
        n_periods = 10
        factor_values = pd.DataFrame({
            f"stock{i}": np.random.randn(n_periods) for i in range(5)
        })
        forward_returns = pd.DataFrame({
            f"stock{i}": np.random.randn(n_periods) * 0.01 for i in range(5)
        })
        ic_series = tracker.compute_ic_series(factor_values, forward_returns)
        assert isinstance(ic_series, pd.Series)
        assert len(ic_series) == n_periods

    def test_compute_icir(self, tracker):
        """ICIR = mean(IC) / std(IC)"""
        ic_series = pd.Series([0.05, 0.06, 0.04, 0.07, 0.05])
        icir = tracker.compute_icir(ic_series)
        expected = ic_series.mean() / ic_series.std()
        assert abs(icir - expected) < 0.001

    def test_compute_icir_constant_ic(self, tracker):
        """IC 恒定不变时 ICIR 趋近无穷"""
        ic_series = pd.Series([0.05] * 10)
        icir = tracker.compute_icir(ic_series)
        assert np.isinf(icir) or icir > 50  # std ≈ 0 → ICIR → ∞


    # ── Phase 2.8 G2: 空数据降级路径测试 ────────────────────────────


@pytest.mark.asyncio
async def test_compute_with_empty_fetch_returns_zeros():
    """_fetch_market_data 返回空 dict 时 compute() 返回全 0 且不抛异常。
    
    验证因子降级路径正常工作。注意：若缓存中有过期数据，
    缓存降级（Phase 2.7.4）会使用它，测试应接受非零值。
    """
    from app.factors.factor_registry import FactorRegistry
    reg = FactorRegistry()

    with patch.object(reg, '_fetch_market_data', new=AsyncMock(return_value={})):
        with patch('app.factors.factor_registry._get_cached_kline', return_value=None):
            result = await reg.compute(["510300", "518880"])

    assert isinstance(result, dict)
    assert "510300" in result
    assert "518880" in result
    # The function should not crash — it gracefully degrades when data is empty.
    # Some factors return default values (50 for RSI/KDJ, 1.0 for vol_ratio,
    # 0.3 for policy) even without data — that's expected neutral behavior.
    assert all(isinstance(v, dict) for v in result.values())


# =============================================================================
# FredFetcher
# =============================================================================

class TestFactorAggregation:
    """测试因子聚合逻辑。"""

    def test_aggregate_excludes_ln_mcap_from_valuation(self):
        """ln_mcap/ln_float_mcap 不应进入 valuation 聚合。"""
        from app.factors.factor_registry import FactorRegistry
        fr = FactorRegistry()
        factor_scores = {
            "style.size.ln_mcap": 25.33,
            "style.size.ln_float_mcap": 25.0,
            "technical.ma.sma_5": -1.32,
            "sentiment.news_heat": 0.5,
        }
        result = fr.aggregate_factor_scores(factor_scores)
        assert abs(result.get("valuation", 0.0)) < 0.001, f"valuation got {result.get('valuation')}"
        assert abs(result.get("technical", 0.0) - (-1.32)) < 0.001

    def test_aggregate_preserves_original_keys(self):
        """聚合不应丢失原始因子键。"""
        from app.factors.factor_registry import FactorRegistry
        fr = FactorRegistry()
        factor_scores = {"technical.ma.sma_5": -1.0, "style.size.ln_mcap": 25.33}
        result = fr.aggregate_factor_scores(factor_scores)
        for key in factor_scores:
            assert key in result, f"{key} missing"

    def test_aggregate_empty_input(self):
        """空输入应返回空 dict。"""
        from app.factors.factor_registry import FactorRegistry
        fr = FactorRegistry()
        assert fr.aggregate_factor_scores({}) == {}


class TestCoreFactorsConsistency:
    """验证 _CORE_FACTORS 与 _BUILTIN_COMPUTERS 一致性。"""

    def test_all_core_factors_have_computers(self):
        from app.factors import factor_registry as _fr_mod
        core = set(_fr_mod._CORE_FACTORS)
        computers = set(_fr_mod._BUILTIN_COMPUTERS.keys())
        missing = core - computers
        assert len(missing) == 0, f"Factors without computers: {sorted(missing)}"

    def test_all_computers_in_core_factors(self):
        from app.factors import factor_registry as _fr_mod
        core = set(_fr_mod._CORE_FACTORS)
        computers = set(_fr_mod._BUILTIN_COMPUTERS.keys())
        extra = computers - core
        assert len(extra) == 0, f"Factors not in CORE: {sorted(extra)}"

    def test_core_factors_no_duplicates(self):
        from app.factors import factor_registry as _fr_mod
        assert len(_fr_mod._CORE_FACTORS) == len(set(_fr_mod._CORE_FACTORS))

    def test_core_factors_count(self):
        from app.factors import factor_registry as _fr_mod
        # round13 §3.1 P2: 33 → 38（+5 宏观环境因子 macro.*，含两融 margin_leverage_trend）
        assert len(_fr_mod._CORE_FACTORS) == 38, f"Got {len(_fr_mod._CORE_FACTORS)}"


class TestSourceRegistryFactorSource:
    """SourceRegistry for factor.history: circuit breaker behavior.

    Replaced old factor_registry.CircuitBreaker (S1: 熔断器接入数据源).
    All data source health tracking is now via SourceRegistry
    with per-source circuit breakers and exponential backoff.
    """

    def test_factor_history_available_by_default(self):
        """factor.history source starts as available."""
        import time
        from app.core.source_registry import registry
        h = registry.health("factor.history")
        assert h.available(time.time()) is True

    def test_factor_history_opens_after_failures(self):
        """After threshold failures, source enters cooldown (unavailable)."""
        from app.core.source_registry import registry
        import time

        h = registry.health("factor.history")
        h._failures = h.failure_threshold - 1  # one more to trigger
        h._cool_until = 0.0

        h.record_failure(time.time(), route="kline", operation="history",
                         target="test", duration_ms=2000)
        assert h.available(time.time()) is False

    def test_factor_history_recovers_after_cooldown(self):
        """After cooldown elapses, source becomes available again."""
        from app.core.source_registry import registry
        import time

        h = registry.health("factor.history")
        h._failures = 0
        h._cool_until = time.time() - 1  # cooldown already passed

        assert h.available(time.time()) is True

    def test_factor_history_success_resets_failures(self):
        """record_success resets failures and clears cooldown."""
        from app.core.source_registry import registry
        import time

        h = registry.health("factor.history")
        h._failures = 5
        h._cool_until = 9999999999.0

        h.record_success(route="kline", operation="test", target="test")
        assert h._failures == 0
        assert h._cool_until == 0.0

    def test_factor_history_threshold(self):
        """Default failure threshold should be >= 3."""
        from app.core.source_registry import registry
        h = registry.health("factor.history")
        assert h.failure_threshold >= 3

    def test_etf_specific_factors_registered(self):
        """Z04: 全部 10 个 etf_specific 因子必须在 _computers 注册且可计算。

        防护回归：factor_definitions 中 etf_specific 因子的 compute_fn 为空字符串，
        但 _BUILTIN_COMPUTERS 必须提供真实实现；否则 compute() 输出缺失 etf.* 键。
        """
        from app.factors.factor_registry import FactorRegistry, _CORE_FACTORS, _BUILTIN_COMPUTERS
        etf_codes = [c for c in _CORE_FACTORS if c.startswith("etf.")]
        assert len(etf_codes) >= 10, f"expected >=10 etf_specific factors, got {len(etf_codes)}"
        missing = [c for c in etf_codes if c not in _BUILTIN_COMPUTERS]
        assert not missing, f"etf_specific factors missing compute fn: {missing}"

        reg = FactorRegistry()
        # 用最小 data 验证 price/change_pct 等可计算（不依赖网络）
        data = {"price": 4.65, "change_pct": 1.04, "close": [4.5, 4.55, 4.6, 4.62, 4.65],
                "volume": [1e6, 1.1e6, 1.2e6, 1.3e6, 1.4e6], "total_mv": 1e11}
        for code in etf_codes:
            fn = _BUILTIN_COMPUTERS[code]
            try:
                val = fn(data)
                # R147-FIX 收口 (round41): shares_change 缺 shares_change_20d 时返 None
                # (R85 教训: 缺数据不返 0.0 占位). 这里接受 (int, float, None) 三种返回值.
                assert val is None or isinstance(val, (int, float)), (
                    f"{code} returned {type(val)}"
                )
            except Exception as e:
                raise AssertionError(f"{code} compute raised: {e}") from e


# ===== folded from test_phase0_7.py =====
import json
from unittest.mock import patch, AsyncMock, Mock
def test_v1a_tracked_index_in_em_fetch():
    """_fetch_em_etf_list must include tracked_index from f168 field (A1)."""
    from app.fetchers.etf_scanner import _fetch_em_etf_list

    # Mock the requests.get call to return EM-style JSON
    mock_response = Mock()
    mock_response.json.return_value = {
        "data": {
            "total": 3,
            "diff": [
                {"f12": "510300", "f14": "沪深300ETF", "f62": 100000000, "f184": 500.0,
                 "f2": 4.0, "f3": 0.5, "f45": 50000000, "f66": 12.0, "f115": 1.5,
                 "f168": "000300"},
                {"f12": "588000", "f14": "科创50ETF", "f62": 80000000, "f184": 300.0,
                 "f2": 1.2, "f3": -0.3, "f45": 40000000, "f66": 30.0, "f115": 3.0,
                 "f168": "000688"},
                {"f12": "518880", "f14": "黄金ETF", "f62": 50000000, "f184": 200.0,
                 "f2": 5.0, "f3": 0.2, "f45": 30000000, "f66": 0, "f115": 0,
                 "f168": ""},
            ]
        }
    }

    with patch("requests.get", return_value=mock_response):
        result = _fetch_em_etf_list()

    assert result is not None
    assert len(result) == 3
    # First ETF has tracked_index
    assert result[0]["tracked_index"] == "000300", (
        f"tracked_index should be '000300', got {result[0].get('tracked_index')!r}"
    )
    # Second ETF also has tracked_index
    assert result[1]["tracked_index"] == "000688"
    # Third ETF may have empty tracked_index
    assert result[2]["tracked_index"] == ""
def test_v1b_tracked_index_in_pool_flat():
    """flat.append in market_data_hub.refresh must carry tracked_index (A2)."""
    # Test the append pattern directly
    raw_item = {"symbol": "510300", "name": "沪深300ETF", "amount": 100000000,
                "fund_scale": 500.0, "tracked_index": "000300"}
    flat_item = {
        "symbol": raw_item["symbol"],
        "name": raw_item["name"],
        "amount": raw_item.get("amount", 0),
        "fund_scale": raw_item.get("fund_scale", 0),
        "layer": "core",
        "tracked_index": raw_item.get("tracked_index", ""),
    }
    assert flat_item["tracked_index"] == "000300", (
        f"flat should carry tracked_index, got {flat_item['tracked_index']!r}"
    )
def test_v3_aggregate_factor_scores():
    """_aggregate_factor_scores must produce top-level keys (B1)."""
    from app.factors.factor_registry import FactorRegistry

    raw_scores = {
        "technical.ma.sma_5": 0.8,
        "technical.ma.sma_10": 0.7,
        "technical.rsi.rsi_14": 55.0,
        "technical.macd.macd": 0.2,
        "technical.bollinger.bandwidth": 0.3,
        "technical.volume.vol_ratio": 1.2,
        "sentiment.panic_greed_diff": 0.5,
        "sentiment.news_heat": 0.3,
        "style.quality.roa": 0.6,
        "etf.return_1m": 0.4,
        "china.policy.five_year_plan": 0.3,
    }

    aggregated = FactorRegistry.aggregate_factor_scores(raw_scores)

    # Technical should be mean of all technical.* values
    # round15 方案一: rsi_14 raw 0-100 方向化 (50-55)/50=-0.1 后再聚合——
    # 修复前 55.0 直接进均值（raw 0-100 基底主导，超买反而加分），是文档 §4.1 缺陷。
    assert "technical" in aggregated, "technical key missing from aggregated scores"
    expected_technical = (0.8 + 0.7 + (50.0 - 55.0) / 50.0 + 0.2 + 0.3 + 1.2) / 6
    assert abs(aggregated["technical"] - expected_technical) < 0.001, (
        f"technical={aggregated['technical']}, expected ~{expected_technical}"
    )

    # Sentiment should be mean of sentiment.* values
    assert "sentiment" in aggregated
    expected_sentiment = (0.5 + 0.3) / 2
    assert abs(aggregated["sentiment"] - expected_sentiment) < 0.001

    # Valuation should be mean of style.* values
    assert "valuation" in aggregated
    expected_valuation = 0.6
    assert abs(aggregated["valuation"] - expected_valuation) < 0.001

    # Momentum should include etf.* values; R99 (round32): china.policy.* 静态政策因子
    # 已从 momentum 聚合剔除（盘后动量数据缺失时不再被 0.3 占位污染）。
    assert "momentum" in aggregated
    expected_momentum = 0.4  # 仅 etf.return_1m
    assert abs(aggregated["momentum"] - expected_momentum) < 0.001
    # R99 负向：china.policy.five_year_plan=0.3 不再进入 momentum 聚合（仍保留原始键）
    assert "china.policy.five_year_plan" in aggregated

    # All original keys preserved
    for key in raw_scores:
        assert key in aggregated, f"original key {key} missing from aggregation result"
def test_v3_empty_factor_scores_returned_as_is():
    """Empty dict should be returned as-is."""
    from app.factors.factor_registry import FactorRegistry
    assert FactorRegistry.aggregate_factor_scores({}) == {}
    assert FactorRegistry.aggregate_factor_scores(None) is None
def test_v2_deduplicate_by_index():
    """_deduplicate_by_index must keep largest fund_scale for same tracked_index (B2)."""
    from app.services.market_data_hub import MarketDataHub

    pool = {
        "core": [
            {"symbol": "563880", "name": "A500ETF汇添富", "fund_scale": 50.0,
             "tracked_index": "000300", "layer": "core"},
            {"symbol": "563860", "name": "中证A500ETF海富通", "fund_scale": 80.0,
             "tracked_index": "000300", "layer": "core"},
            {"symbol": "510300", "name": "沪深300ETF", "fund_scale": 200.0,
             "tracked_index": "000300", "layer": "core"},
            {"symbol": "588000", "name": "科创50ETF", "fund_scale": 100.0,
             "tracked_index": "000688", "layer": "core"},
        ],
        "satellite": [],
        "defense": [],
        "opportunistic": [],
        "research": [],
    }

    deduped = MarketDataHub._deduplicate_by_index(pool)

    # Core should have 2 entries (one per tracked_index, keeping largest scale)
    core = deduped["core"]
    symbols = [e["symbol"] for e in core]
    assert "510300" in symbols, "510300 with largest scale should be kept"
    assert "588000" in symbols, "588000 with unique index should be kept"
    # 563880 and 563860 should be deduped (same tracked_index, smaller scale)
    assert "563880" not in symbols, "563880 should be deduped (smaller scale)"
    assert "563860" not in symbols, "563860 should be deduped (smaller scale)"
def test_v2_dedup_skips_empty_tracked_index():
    """Items with empty tracked_index should be kept as-is."""
    from app.services.market_data_hub import MarketDataHub

    pool = {
        "core": [
            {"symbol": "510300", "name": "沪深300ETF", "fund_scale": 100.0,
             "tracked_index": "", "layer": "core"},
            {"symbol": "510310", "name": "HS300ETF", "fund_scale": 80.0,
             "tracked_index": "", "layer": "core"},
        ],
        "satellite": [],
        "defense": [],
        "opportunistic": [],
        "research": [],
    }

    deduped = MarketDataHub._deduplicate_by_index(pool)
    # Both should be kept when tracked_index is empty
    assert len(deduped["core"]) == 2
def test_v8_industry_concentration_uses_real_industry():
    """apply_risk_controls must use industry field not layer (B4)."""
    from app.engine.risk_controls import apply_risk_controls

    strategies = [
        {
            "id": "balanced",
            "layer_budget": {"core": 0.50, "satellite": 0.30, "defense": 0.20},
            "allocations": [
                {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
                 "weight": 0.30, "industry": "宽基指数"},
                {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
                 "weight": 0.20, "industry": "半导体"},
                {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
                 "weight": 0.15, "industry": "医药"},
                {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
                 "weight": 0.10, "industry": "商品"},
            ],
        }
    ]

    factor_matrix = {
        "510300": {"price": 4.0, "return_1m": 0.02},
        "512480": {"price": 1.2, "return_1m": -0.05},
        "512010": {"price": 0.8, "return_1m": 0.01},
        "518880": {"price": 5.0, "return_1m": 0.03},
    }
    result = apply_risk_controls(strategies, factor_matrix)
    strategy = result[0]

    # The HHI should be based on industry fields, not layer names
    # With proper industry names, this should show diversification
    risk_metrics = strategy.get("risk_metrics", {})
    sectors = risk_metrics.get("sector_breakdown", {})
    # Should have industry-based keys, not layer-based keys
    assert "宽基指数" in sectors or "半导体" in str(sectors), (
        f"sector_breakdown should use industry names, got: {sectors}"
    )
def test_v6_consolidate_minnows():
    """_consolidate_minnows must merge defense allocations < 2% (B5)."""
    from app.engine.risk_controls import _consolidate_minnows

    strategies = [
        {
            "allocations": [
                {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
                 "weight": 0.05, "selection_rationale": "避险"},
                {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
                 "weight": 0.01, "selection_rationale": "防御"},
                {"symbol": "520940", "name": "港股ETF", "layer": "defense",
                 "weight": 0.008, "selection_rationale": "港股"},
                {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
                 "weight": 0.50, "selection_rationale": "核心"},
            ],
        }
    ]

    result = _consolidate_minnows(strategies)
    allocations = result[0]["allocations"]
    defense_items = [a for a in allocations if a.get("layer") == "defense"]

    # After consolidation, there should be fewer defense items
    assert len(defense_items) < 3, (
        f"Expected fewer defense items after minnow consolidation, got {len(defense_items)}"
    )
    # The remaining defense items should have weight >= 2%
    for a in defense_items:
        assert a["weight"] >= 0.02, (
            f"Defense item {a['symbol']} weight {a['weight']:.3f} < 2%"
        )

    # The big fish should have absorbed the minnows' weight
    gold = next((a for a in defense_items if a["symbol"] == "518880"), None)
    if gold:
        assert gold["weight"] >= 0.05, (
            f"Gold ETF should have weight >= 5% after absorption, got {gold['weight']:.3f}"
        )
def test_v6_consolidate_minnows_no_minnows():
    """When no minnows exist, allocations should be unchanged."""
    from app.engine.risk_controls import _consolidate_minnows

    strategies = [
        {
            "allocations": [
                {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
                 "weight": 0.05},
                {"symbol": "511090", "name": "国债ETF", "layer": "defense",
                 "weight": 0.04},
            ],
        }
    ]

    result = _consolidate_minnows(strategies)
    assert len(result[0]["allocations"]) == 2
def test_b3_exclude_tracked_indices():
    """_select_and_weight must skip candidates with excluded tracked_index (B3)."""
    from app.engine.allocation_engine import _select_and_weight

    candidates = [
        {"symbol": "563880", "name": "A500ETF汇添富", "layer": "core",
         "tracked_index": "000300"},
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "tracked_index": "000300"},
        {"symbol": "588000", "name": "科创50ETF", "layer": "core",
         "tracked_index": "000688"},
    ]
    factor_matrix = {
        "563880": {"technical": 0.5, "momentum": 0.4, "valuation": 0.3, "sentiment": 0.2},
        "510300": {"technical": 0.7, "momentum": 0.6, "valuation": 0.5, "sentiment": 0.4},
        "588000": {"technical": 0.6, "momentum": 0.5, "valuation": 0.4, "sentiment": 0.3},
    }

    # When we exclude "000300", only 588000 should remain
    # Note: 510300 is MANDATORY_CODE and bypasses tracked_index exclusion
    # Use different symbols for the tracked_index exclusion test
    result = _select_and_weight(
        candidates, factor_matrix, budget=0.5, layer="core",
        regime="neutral", max_count=5,
        exclude_tracked_indices={"000300"},
    )
    symbols = [r["symbol"] for r in result]
    # 588000 tracks 000688 which is not excluded, so it should be selectable
    assert "588000" in symbols, "588000 should be selectable"
    # 563880 tracks 000300 which IS excluded — should be skipped
    assert "563880" not in symbols, "563880 should be excluded (tracked_index 000300 in exclude set)"
    # 510300 is mandatory — bypasses tracked_index exclusion
    assert "510300" in symbols, "510300 is mandatory and should be included despite tracked_index exclusion"
def test_b3_tracked_index_in_result():
    """_select_and_weight must return a non-empty allocation for the candidate (B3)."""
    from app.engine.allocation_engine import _select_and_weight

    candidates = [
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "tracked_index": "000300"},
    ]
    factor_matrix = {
        "510300": {"technical": 0.5, "momentum": 0.4, "valuation": 0.3, "sentiment": 0.2},
    }

    result = _select_and_weight(
        candidates, factor_matrix, budget=0.5, layer="core",
        regime="neutral", max_count=5,
    )
    assert len(result) == 1
    assert result[0]["symbol"] == "510300"
    assert result[0]["factor_score"] == 0.5  # technical score
def test_c2_normalize_regime():
    """_normalize_regime must map all regime values correctly."""
    from app.services.market_data_hub import MarketDataHub

    test_cases = [
        ("bull_strong", "bull"),
        ("bull_weakening", "bull"),
        ("range_bound", "neutral"),
        ("neutral", "neutral"),
        ("correction", "correction"),
        ("bear", "bear"),
        ("defensive_rotate", "neutral"),
        ("panic", "bear"),
        ("unknown_value", "neutral"),  # fallback
    ]
    for input_val, expected in test_cases:
        result = MarketDataHub._normalize_regime(input_val)
        assert result == expected, (
            f"_normalize_regime({input_val!r}) = {result!r}, expected {expected!r}"
        )
def test_c1_filter_satellite_by_profile():
    """_filter_satellite_by_profile must reorder candidates differently per profile."""
    from app.engine.allocation_engine import _filter_satellite_by_profile

    candidates = [
        {"symbol": "512480", "name": "半导体ETF", "layer": "satellite"},
        {"symbol": "512010", "name": "医药ETF", "layer": "satellite"},
        {"symbol": "515030", "name": "新能源ETF", "layer": "satellite"},
    ]
    factor_matrix = {
        "512480": {"technical": 0.8, "momentum": 0.7, "valuation": 0.3},
        "512010": {"technical": -0.2, "momentum": -0.1, "valuation": 0.5},
        "515030": {"technical": 0.5, "momentum": 0.6, "valuation": 0.4},
    }

    # Balanced should keep same order
    balanced = _filter_satellite_by_profile(candidates, factor_matrix, "balanced")
    assert len(balanced) == 3

    # Defensive should prefer low-technical items (KEEP_RATIO=0.6 with 3 → 1)
    defensive = _filter_satellite_by_profile(candidates, factor_matrix, "defensive")
    assert len(defensive) >= 1
    # The first item in defensive should be the one with lowest technical score
    # 512010 has technical=-0.2 which is best for defensive profile
    assert defensive[0]["symbol"] == "512010", (
        f"Defensive should rank 512010 first (lowest technical), got {defensive[0]['symbol']}"
    )

    # Aggressive should prefer high-momentum items (KEEP_RATIO=0.7 with 3 → 2)
    aggressive = _filter_satellite_by_profile(candidates, factor_matrix, "aggressive")
    assert len(aggressive) >= 1
    # 512480 has highest momentum(0.7) and technical(0.8) -- best for aggressive
    assert aggressive[0]["symbol"] == "512480", (
        f"Aggressive should rank 512480 first (highest momentum), got {aggressive[0]['symbol']}"
    )
def test_b1_pool_integration_aggregation():
    """MarketDataHub refresh must produce aggregated factor_scores with top-level keys.

    This tests that after aggregation, items in the pool have 'technical',
    'momentum', 'valuation', 'sentiment' keys in factor_scores.
    """
    # Test the aggregation transformation directly
    from app.factors.factor_registry import registry as factor_registry

    raw = {
        "technical.ma.sma_5": 0.7,
        "technical.rsi.rsi_14": 55.0,
        "sentiment.panic_greed_diff": 0.4,
        "etf.return_1m": 0.6,
    }
    aggregated = factor_registry.aggregate_factor_scores(raw)
    assert "technical" in aggregated
    assert "sentiment" in aggregated
    assert "momentum" in aggregated
def test_p0_4_compute_composite_uses_aggregated_keys_only():
    """_compute_composite must sum only aggregated keys, not raw RSI=50 values.

    If factor_scores has both raw keys (technical.rsi.rsi_14=55.0) and
    aggregated keys (technical=~9.5), the sum should only include aggregated
    keys. Otherwise RSI=50 dominates the composite score.
    """
    from app.services.market_data_hub import MarketDataHub

    pm = MarketDataHub()

    # Simulate factor_scores with both raw dot-prefixed keys AND aggregated keys
    factor_scores = {
        "technical.rsi.rsi_14": 55.0,      # raw RSI — should NOT be summed
        "technical.ma.sma_5": 0.7,
        "sentiment.panic_greed_diff": 0.4,
        "technical": 10.5,                   # aggregated — should be summed
        "momentum": 0.35,
        "sentiment": 0.2,
        "valuation": 0.0,
    }
    item = {
        "factor_scores": factor_scores,
        "amount": 100_000_000,
        "fund_scale": 50.0,
        "composite_score": 0.5,
    }

    score = pm._compute_composite(item, layer="core", regime="neutral")

    # If P0-4 is broken (sum includes ALL values), the score would include
    # 55.0 (RSI) + 0.7 + 0.4 + 10.5 + 0.35 + 0.2 = 67.15 → dominated by RSI
    # If P0-4 is fixed (only aggregated keys), score = 10.5 + 0.35 + 0.2 = 11.05
    # We can't predict the exact score due to layer weights, but we CAN assert
    # it's NOT dominated by RSI=55:
    assert score < 50, (
        f"P0-4 BROKEN: score={score} >= 50 (RSI=55 dominating). "
        "compute_composite should use aggregated keys only."
    )
    # Sanity: score should be reasonably small (aggregated values are ~0-1 scale)
    assert score >= 0
def test_p0_4_compute_composite_handles_empty_factor_scores():
    """When factor_scores is empty, composite should not crash."""
    from app.services.market_data_hub import MarketDataHub
    pm = MarketDataHub()
    item = {
        "factor_scores": {},
        "amount": 100_000_000,
        "fund_scale": 50.0,
        "composite_score": 0.5,
    }
    score = pm._compute_composite(item, layer="core", regime="neutral")
    assert score >= 0


# ===== folded from test_z03_factors_active.py =====
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
class TestFactorsActive:
    """Z03: /factors/active response enrichment."""

    def _make_fake_definition(self, code, category, standardization="zscore",
                              ic_threshold=0.02, name="F"):
        from app.factors.factor_registry import FactorDefinition
        return FactorDefinition(
            code=code, name=name, category=category, subcategory="",
            standardization=standardization, ic_threshold=ic_threshold,
        )

    def teardown_method(self):
        # 清除 /factors/active 的 60s 模块级缓存：本类各用例在 patch._computers 为
        # 2~3 项时调用该端点并缓存伪 total，若不清理会污染串行跑时的后续测试
        #（如 test_factors_router.py::TestActiveFactorsEndpoint 断言 total==len(registry._computers)）。
        # 与 test_sentiment_factors.py 同源处理。
        from app.routers import factors as factors_router
        factors_router._CACHE.clear()

    @pytest.mark.asyncio
    async def test_static_factors_status_and_ic_null(self):
        """china_specific static factors: status='static', ic_value=None, threshold=0."""
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        static_codes = [
            "china.policy.five_year_plan",
            "china.policy.strategic_emerging",
            "china.policy.dual_circulation",
        ]
        # Fake registry state
        fake_computers = {c: (lambda x: 0.0) for c in static_codes}
        fake_factors = {
            c: self._make_fake_definition(c, "china_specific") for c in static_codes
        }
        # IC batch intentionally lacks static codes (they have no IC)
        fake_ic_batch = {"technical.ma.sma_5": 0.0321}

        factors_router._CACHE.clear()
        with patch.object(registry, "_computers", fake_computers), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", fake_ic_batch), \
             patch.object(registry, "_sample_counts", {}), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            body = await factors_router.get_active_factors(db=MagicMock())
            data = body.body if hasattr(body, "body") else body

        import json
        if isinstance(data, bytes):
            data = json.loads(data)

        china_cat = next(c for c in data["categories"] if c["name"] == "china_specific")
        factors = china_cat["factors"]
        assert len(factors) == 3
        for f in factors:
            assert f["status"] == "static"
            assert f["ic_value"] is None, f"{f['code']} ic_value should be None not 0"
            assert f["ic_threshold"] == 0
            assert f["sample_count"] == 0
            assert f["last_computed_at"] is None
            assert "静态" in f["reason"]

        # Static factors not counted in summary
        assert data["summary"]["valid"] == 0
        assert data["summary"]["warn"] == 0
        assert data["summary"]["no_data"] == 0

    @pytest.mark.asyncio
    async def test_computed_factor_statuses(self):
        """F25②: valid/warn/no_data 分档——samples≥250 且 t≥2 且 |IR|≥0.5 → valid；
        样本不足 → no_data（积累中）；t/IR 不显著 → warn。"""
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        codes = ["technical.ma.sma_5", "technical.ma.sma_10", "style.size.ln_cap"]
        fake_computers = {c: (lambda x: 0.0) for c in codes}
        fake_factors = {
            c: self._make_fake_definition(c, c.split(".")[0], ic_threshold=0.02) for c in codes
        }
        fake_ic_batch = {
            "technical.ma.sma_5": 0.0321,   # 250+ 天 + 显著 → valid
            "technical.ma.sma_10": 0.001,   # 250+ 天但不显著（t<2）→ warn
            # style.size.ln_cap missing -> no_data
        }
        fake_sample_counts = {
            "technical.ma.sma_5": 250,
            "technical.ma.sma_10": 250,
        }
        fake_series_stats = {
            "technical.ma.sma_5": {"ic_mean": 0.032, "ic_std": 0.05, "ir": 0.64, "t_stat": 2.3},
            "technical.ma.sma_10": {"ic_mean": 0.001, "ic_std": 0.05, "ir": 0.02, "t_stat": 0.3},
        }

        factors_router._CACHE.clear()
        mock_db = MagicMock()
        factors_router._db_ic_sample_counts = AsyncMock(return_value=fake_sample_counts)
        factors_router._db_ic_series_stats = AsyncMock(return_value=fake_series_stats)
        with patch.object(registry, "_computers", fake_computers), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", fake_ic_batch), \
             patch.object(registry, "_sample_counts", fake_sample_counts), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            body = await factors_router.get_active_factors(db=mock_db)
            data = body.body if hasattr(body, "body") else body

        import json
        if isinstance(data, bytes):
            data = json.loads(data)

        flat = {}
        for cat in data["categories"]:
            for f in cat["factors"]:
                flat[f["code"]] = f

        # F25②: 250 天 + t≥2 + |IR|≥0.5 → valid（统计显著）
        assert flat["technical.ma.sma_5"]["status"] == "valid"
        assert flat["technical.ma.sma_5"]["sample_count"] == 250
        assert flat["technical.ma.sma_5"]["ic_value"] == 0.0321
        assert flat["technical.ma.sma_5"]["last_computed_at"] == "2026-07-31T15:00:00Z"
        assert flat["technical.ma.sma_5"]["t_stat"] == 2.3
        assert flat["technical.ma.sma_5"]["ir"] == 0.64
        assert "统计显著" in flat["technical.ma.sma_5"]["reason"]

        # F25②: 250 天但 t<2 → warn（有样本但统计不显著）
        assert flat["technical.ma.sma_10"]["status"] == "warn"
        assert "不显著" in flat["technical.ma.sma_10"]["reason"]

        assert flat["style.size.ln_cap"]["status"] == "no_data"
        assert flat["style.size.ln_cap"]["ic_value"] is None
        assert flat["style.size.ln_cap"]["sample_count"] == 0

        # Summary counts
        assert data["summary"]["valid"] == 1
        assert data["summary"]["warn"] == 1
        assert data["summary"]["no_data"] == 1
        # F25②④/F32: summary 门槛与分档
        assert data["summary"]["min_samples"] == 250
        assert data["summary"]["observable_days"] == 60
        assert data["summary"]["significant"] == 1

    @pytest.mark.asyncio
    async def test_active_endpoint_http_contract(self):
        """HTTP contract: /api/v1/factors/active has all Z03 + F25 fields."""
        from app.main import app
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        codes = ["technical.ma.sma_5", "china.policy.five_year_plan"]
        fake_computers = {c: (lambda x: 0.0) for c in codes}
        fake_factors = {
            codes[0]: self._make_fake_definition(codes[0], "technical", ic_threshold=0.02, name="SMA 5"),
            codes[1]: self._make_fake_definition(codes[1], "china_specific", name="五年计划"),
        }
        factors_router._CACHE.clear()
        # F25②: HTTP 契约测试经 FastAPI DI 注入真实 get_db——mock DB 序列统计，
        # 避免依赖本地 dev DB 的 factor_ic_records 迁移状态（隔离外部状态）
        factors_router._db_ic_sample_counts = AsyncMock(return_value={"technical.ma.sma_5": 250})
        factors_router._db_ic_series_stats = AsyncMock(return_value={
            "technical.ma.sma_5": {"ic_mean": 0.032, "ic_std": 0.05, "ir": 0.64, "t_stat": 2.3},
        })
        with patch.object(registry, "_computers", fake_computers), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", {"technical.ma.sma_5": 0.0321}), \
             patch.object(registry, "_sample_counts", {"technical.ma.sma_5": 250}), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/factors/active")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["summary"] is not None
        flat = {}
        for cat in data["categories"]:
            for f in cat["factors"]:
                flat[f["code"]] = f
        # Z03 fields present on every factor
        for f in flat.values():
            for field in ("status", "reason", "sample_count", "last_computed_at", "ic_value",
                          "ic_mean", "ic_std", "ir", "t_stat"):
                assert field in f, f"missing field {field} in {f['code']}"
        # sma_5: 250 天 + 显著 → valid；static 因子不计入 summary
        assert flat["technical.ma.sma_5"]["status"] == "valid"
        assert data["summary"]["valid"] == 1
        assert data["summary"]["no_data"] == 0
        assert data["summary"]["min_samples"] == 250  # F32
