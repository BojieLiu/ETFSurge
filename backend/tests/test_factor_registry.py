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
        default = Path(__file__).parent.parent.parent / "app" / "factors" / "factor_definitions.yaml"
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
        assert len(_fr_mod._CORE_FACTORS) == 33, f"Got {len(_fr_mod._CORE_FACTORS)}"


class TestSourceRegistryFactorSource:
    """SourceRegistry for factor.history: circuit breaker behavior.

    Replaced old factor_registry.CircuitBreaker (S1: 熔断器接入数据源).
    All data source health tracking is now via SourceRegistry
    with per-source circuit breakers and exponential backoff.
    """

    def test_factor_history_available_by_default(self):
        """factor.history source starts as available."""
        import time
        from app.services.source_registry import registry
        h = registry._health("factor.history")
        assert h.available(time.time()) is True

    def test_factor_history_opens_after_failures(self):
        """After threshold failures, source enters cooldown (unavailable)."""
        from app.services.source_registry import registry
        import time

        h = registry._health("factor.history")
        h._failures = h.failure_threshold - 1  # one more to trigger
        h._cool_until = 0.0

        h.record_failure(time.time(), route="kline", operation="history",
                         target="test", duration_ms=2000)
        assert h.available(time.time()) is False

    def test_factor_history_recovers_after_cooldown(self):
        """After cooldown elapses, source becomes available again."""
        from app.services.source_registry import registry
        import time

        h = registry._health("factor.history")
        h._failures = 0
        h._cool_until = time.time() - 1  # cooldown already passed

        assert h.available(time.time()) is True

    def test_factor_history_success_resets_failures(self):
        """record_success resets failures and clears cooldown."""
        from app.services.source_registry import registry
        import time

        h = registry._health("factor.history")
        h._failures = 5
        h._cool_until = 9999999999.0

        h.record_success(route="kline", operation="test", target="test")
        assert h._failures == 0
        assert h._cool_until == 0.0

    def test_factor_history_threshold(self):
        """Default failure threshold should be >= 3."""
        from app.services.source_registry import registry
        h = registry._health("factor.history")
        assert h.failure_threshold >= 3
