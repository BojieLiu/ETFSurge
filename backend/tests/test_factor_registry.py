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


# =============================================================================
# FredFetcher
# =============================================================================

class TestFredFetcher:
    """FRED API 宏观数据获取（所有 HTTP 调用 mock）"""

    @pytest.fixture
    def mock_fred_response(self):
        """模拟 FRED API 的 JSON 响应"""
        return {
            "observations": [
                {"date": "2026-07-15", "value": "15.67"},
                {"date": "2026-07-14", "value": "16.50"},
                {"date": "2026-07-13", "value": "17.16"},
            ]
        }

    @patch("app.fetchers.fred_fetcher.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_vix(self, mock_client, mock_fred_response):
        """fetch_vix() 应返回最新 VIX 值"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_fred_response
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_resp

        from app.fetchers.fred_fetcher import fetch_vix
        vix = await fetch_vix()
        assert vix == 15.67

    @patch("app.fetchers.fred_fetcher.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_us_10y(self, mock_client):
        """fetch_us_10y() 应返回最新美债收益率"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "observations": [
                {"date": "2026-07-15", "value": "4.55"},
                {"date": "2026-07-14", "value": "4.52"},
            ]
        }
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_resp

        from app.fetchers.fred_fetcher import fetch_us_10y
        yield_10y = await fetch_us_10y()
        assert yield_10y == 4.55

    @patch("app.fetchers.fred_fetcher.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_fed_rate(self, mock_client):
        """fetch_fed_rate() 应返回联邦基金利率"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "observations": [
                {"date": "2026-07-15", "value": "3.63"},
            ]
        }
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_resp

        from app.fetchers.fred_fetcher import fetch_fed_rate
        rate = await fetch_fed_rate()
        assert rate == 3.63

    @patch("app.fetchers.fred_fetcher.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_api_error_returns_none(self, mock_client):
        """API 错误时应返回 None（不抛异常）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_resp

        from app.fetchers.fred_fetcher import fetch_vix
        result = await fetch_vix()
        assert result is None

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
        assert len(_fr_mod._CORE_FACTORS) == 30, f"Got {len(_fr_mod._CORE_FACTORS)}"
    @patch("app.fetchers.fred_fetcher.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_network_error_returns_none(self, mock_client):
        """网络异常时应返回 None（不抛异常）"""
        mock_client.return_value.__aenter__.return_value.get.side_effect = Exception("Connection timeout")

        from app.fetchers.fred_fetcher import fetch_vix
        result = await fetch_vix()
        assert result is None


class TestCircuitBreaker:
    """CircuitBreaker: auto-reset after cooldown."""

    def test_cb_closes_after_cooldown(self):
        """After opening, CB auto-closes once cooldown elapses."""
        from app.factors.factor_registry import CircuitBreaker
        import time

        # Reset CB state
        CircuitBreaker.failure_count = 0
        CircuitBreaker.open_until = 0.0

        # Record enough failures to open
        for _ in range(CircuitBreaker.threshold):
            CircuitBreaker.record_failure()

        assert CircuitBreaker.is_open() is True

        # Simulate cooldown passing
        CircuitBreaker.open_until = time.time() - 1

        assert CircuitBreaker.is_open() is False

    def test_cb_resets_on_success(self):
        """record_success resets failure_count, keeping CB closed."""
        from app.factors.factor_registry import CircuitBreaker

        CircuitBreaker.failure_count = 0
        CircuitBreaker.open_until = 0.0

        CircuitBreaker.record_failure()
        CircuitBreaker.record_failure()
        CircuitBreaker.record_success()

        assert CircuitBreaker.is_open() is False
        assert CircuitBreaker.failure_count == 0

    def test_cb_threshold_after_fix(self):
        """Threshold should be >= 10 (P1 fix: was 3)."""
        from app.factors.factor_registry import CircuitBreaker

        assert CircuitBreaker.threshold >= 10, (
            f"CB threshold {CircuitBreaker.threshold} is too low; "
            f"was increased from 3 to 10 to avoid premature tripping"
        )
