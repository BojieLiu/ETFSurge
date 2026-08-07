"""O4 (docs/archived/round7-rediagnosis.md §7): get_factor_matrix 尊重 YAML standardization=raw。

P6 根因: factor_registry.factor_scores 已对 raw 因子（rsi_14/rsi_24）保留真实 0-100，
但 market_data_hub.get_factor_matrix() 对 factor_scores 无条件做截面 z-score——
即使 factor_definitions.yaml 声明 rsi_14: raw。rationale 读到的 rsi_14 是 z-score 值
（-0.26 类），「RSI<30 超卖」判断失真。

修复: get_factor_matrix 收集 standardization=raw 的因子集，_normalize_matrix 跳过它们。
"""

from app.services.market_data_hub import MarketDataHub
from app.factors.factor_registry import registry as factor_registry


def _hub_with_pool(pool):
    hub = MarketDataHub.__new__(MarketDataHub)
    hub._pool = pool
    hub._by_code = {}
    hub._kline_cache_rows = {}
    hub._kline_cache_ts = 0.0
    return hub


def _pool_entry(symbol, factor_scores):
    return {"symbol": symbol, "name": symbol, "layer": "core", "factor_scores": factor_scores}


class TestFactorMatrixRespectsRaw:
    def test_rsi_raw_kept_through_normalize(self):
        """rsi_14 原始 0-100 值应穿过 get_factor_matrix（不被 z-score 化）。"""
        pool = {
            "core": [
                _pool_entry("510300", {
                    "technical.rsi.rsi_14": 45.0,
                    "technical.rsi.rsi_24": 48.0,
                    "technical.macd.macd": 0.5,
                    "momentum.etf.return_1m": 0.03,
                }),
                _pool_entry("560600", {
                    "technical.rsi.rsi_14": 55.0,
                    "technical.rsi.rsi_24": 52.0,
                    "technical.macd.macd": -0.3,
                    "momentum.etf.return_1m": -0.02,
                }),
                _pool_entry("512480", {
                    "technical.rsi.rsi_14": 72.0,
                    "technical.rsi.rsi_24": 66.0,
                    "technical.macd.macd": 0.8,
                    "momentum.etf.return_1m": 0.05,
                }),
            ]
        }
        hub = _hub_with_pool(pool)
        matrix = hub.get_factor_matrix()
        # rsi_14 保留真实 0-100（45/55/72），不再是 z-score（≈ -0.5/0/+1.5 量级）
        assert matrix["510300"]["technical.rsi.rsi_14"] == 45.0
        assert matrix["560600"]["technical.rsi.rsi_14"] == 55.0
        assert matrix["512480"]["technical.rsi.rsi_14"] == 72.0

    def test_rsi_24_raw_kept(self):
        """rsi_24 同样声明 raw，应保留真实值。"""
        pool = {
            "core": [
                _pool_entry("510300", {"technical.rsi.rsi_24": 40.0}),
                _pool_entry("560600", {"technical.rsi.rsi_24": 50.0}),
                _pool_entry("512480", {"technical.rsi.rsi_24": 60.0}),
            ]
        }
        hub = _hub_with_pool(pool)
        matrix = hub.get_factor_matrix()
        assert matrix["510300"]["technical.rsi.rsi_24"] == 40.0
        assert matrix["560600"]["technical.rsi.rsi_24"] == 50.0
        assert matrix["512480"]["technical.rsi.rsi_24"] == 60.0

    def test_zscore_factors_still_normalized(self):
        """非 raw 因子（macd/return_1m）仍被 z-score 归一化（行为不变）。"""
        pool = {
            "core": [
                _pool_entry("510300", {"technical.macd.macd": 0.5, "technical.rsi.rsi_14": 45.0}),
                _pool_entry("560600", {"technical.macd.macd": -0.3, "technical.rsi.rsi_14": 55.0}),
                _pool_entry("512480", {"technical.macd.macd": 0.8, "technical.rsi.rsi_14": 72.0}),
            ]
        }
        hub = _hub_with_pool(pool)
        matrix = hub.get_factor_matrix()
        macd_vals = [matrix[s]["technical.macd.macd"] for s in ("510300", "560600", "512480")]
        # z-score 后均值为 0 量级，有正有负（0.5/-0.3/0.8 → z-score 后 ±1 内）
        assert abs(sum(macd_vals)) < 0.01, f"macd 应被 z-score 化（均值≈0）: {macd_vals}"
        assert max(macd_vals) - min(macd_vals) > 1.0, f"macd z-score 应有区分度: {macd_vals}"

    def test_raw_codes_from_registry_definition(self):
        """raw 因子集来自 factor_definitions.yaml 的 standardization 声明。"""
        raw_codes = {c for c, f in factor_registry._factors.items() if f.standardization == "raw"}
        assert "technical.rsi.rsi_14" in raw_codes
        assert "technical.rsi.rsi_24" in raw_codes
        assert "technical.macd.macd" not in raw_codes  # macd 仍是 zscore
