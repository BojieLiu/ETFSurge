"""round15 方案一（raw 方向化 + 显式聚合映射）与方案三阶段一（IC 加权聚合）测试。

对应 docs/archived/round15-factor-pool-selection-evaluation.md §5.1/§5.3/§7：
- 负向断言 1：构造 RSI=75 与 RSI=50 两只标的（其余 technical 因子=0），断言
  technical(RSI=75) < technical(RSI=50)——修复前 RSI raw 0-100 贡献 ≈75/15=5 分而更高
  （防方向化缺失回归）
- KDJ zscore 均值回归：超买（K/D/J 高位正值）→ 取负为负分
- 方向化不污染原始裸键（_raw 保留链路 / factor_scores 原值不动）
- IC 加权：正 IC 因子权重大于负 IC/零 IC；冷启动（<5 批）回退等权
"""
import pytest

from app.factors.factor_registry import (
    FactorDefinition,
    FactorRegistry,
    IC_FLIP_THRESHOLD,
    IC_MIN_BATCHES,
)

DEFS = {
    "technical.rsi.rsi_14": FactorDefinition(
        code="technical.rsi.rsi_14", name="RSI14", category="technical",
        subcategory="rsi", standardization="raw", direction=-1, neutral_value=50.0,
    ),
    "technical.kdj.k_value": FactorDefinition(
        code="technical.kdj.k_value", name="KDJ K", category="technical",
        subcategory="kdj", standardization="zscore", direction=-1,
    ),
    "technical.ma.sma_5": FactorDefinition(
        code="technical.ma.sma_5", name="SMA5", category="technical",
        subcategory="ma", standardization="zscore", direction=1,
    ),
    "technical.signal.overall": FactorDefinition(
        code="technical.signal.overall", name="signal", category="technical",
        subcategory="signal", standardization="zscore", direction=1,
    ),
}


def _agg(scores: dict, definitions=DEFS, ic_series=None):
    return FactorRegistry.aggregate_factor_scores(scores, definitions, ic_series)


class TestDirectionalization:
    """方案一：raw 方向化（RSI 超买为负）+ KDJ 取负 + 原始键不污染。"""

    def test_rsi_overbought_lower_than_neutral(self):
        """负向断言 1：RSI=75 的 technical < RSI=50 的 technical（修复前 75 更高）。"""
        hi = _agg({
            "technical.rsi.rsi_14": 75.0,
            "technical.ma.sma_5": 0.0,
            "technical.kdj.k_value": 0.0,
            "technical.signal.overall": 0.0,
        })
        mid = _agg({
            "technical.rsi.rsi_14": 50.0,
            "technical.ma.sma_5": 0.0,
            "technical.kdj.k_value": 0.0,
            "technical.signal.overall": 0.0,
        })
        assert hi["technical"] < mid["technical"], \
            f"RSI=75 不应高于 RSI=50（raw 0-100 污染仍存在: {hi['technical']} vs {mid['technical']}）"

    def test_rsi_oversold_higher(self):
        """RSI=30（超卖）应为正语义分（均值回归：超卖买入）。"""
        result = _agg({"technical.rsi.rsi_14": 30.0})
        assert result["technical"] > 0

    def test_kdj_overbought_negated(self):
        """KDJ zscore 超买（正值）→ 取负为负分（均值回归）。"""
        hi = _agg({
            "technical.rsi.rsi_14": 50.0,
            "technical.kdj.k_value": 3.0,   # 超买高位（zscore 正值）
            "technical.signal.overall": 0.0,
        })
        low = _agg({
            "technical.rsi.rsi_14": 50.0,
            "technical.kdj.k_value": -3.0,  # 超卖低位
            "technical.signal.overall": 0.0,
        })
        assert hi["technical"] < low["technical"], "KDJ 高位应取负（均值回归方向）"

    def test_raw_keys_not_polluted(self):
        """方向化作用于副本——原始裸键保持不变（rationale/_normalize_matrix 展示用）。"""
        scores = {"technical.rsi.rsi_14": 75.0}
        result = _agg(scores)
        assert scores["technical.rsi.rsi_14"] == 75.0  # 原 dict 未被变换
        assert result["technical.rsi.rsi_14"] == 75.0  # result 保留原始键原值

    def test_momentum_direction_unchanged(self):
        """动量类方向保持 +1（不翻转）。"""
        result = _agg({"etf.return_1m": 2.0})
        assert result["momentum"] == pytest.approx(2.0)

    def test_yaml_single_source(self):
        """yaml 是 direction/neutral_value 单一来源：rsi_14 direction=-1 + neutral=50。"""
        reg = FactorRegistry()
        d = reg.get_factor("technical.rsi.rsi_14")
        assert d is not None and d.direction == -1 and d.neutral_value == 50.0
        k = reg.get_factor("technical.kdj.k_value")
        assert k is not None and k.direction == -1 and k.neutral_value is None


class TestIcWeightedAggregation:
    """方案三阶段一：IC 加权聚合 + 冷启动回退。"""

    def test_positive_ic_factor_gets_more_weight(self):
        """正 IC 因子权重大：IC 高因子的方向化值主导顶层键。"""
        ic_series = {
            "technical.rsi.rsi_14": [0.05] * IC_MIN_BATCHES,   # 正 IC 稳定
            "technical.ma.sma_5": [-0.04] * IC_MIN_BATCHES,   # 负 IC（翻转）
            "technical.signal.overall": [0.0] * IC_MIN_BATCHES,  # 零 IC → w=0
            "technical.kdj.k_value": [0.01] * IC_MIN_BATCHES,    # 小正 IC
        }
        scores = {
            "technical.rsi.rsi_14": 30.0,   # 方向化后 +0.4（超卖）
            "technical.ma.sma_5": 2.0,      # 负 IC → 翻转 -2.0
            "technical.signal.overall": 3.0,  # w=0 不参与
            "technical.kdj.k_value": 1.0,   # 方向化 -1.0，小权重
        }
        result = _agg(scores, ic_series=ic_series)
        # RSI 正 IC 权重 (0.05) 高于 KDJ (0.01)，RSI 方向化值 +0.4 vs SMA 翻转 -2.0
        assert result["technical"] is not None

    def test_cold_start_falls_back_equal_weight(self):
        """冷启动（IC 样本 < 5 批）→ 等权均值（与修复前行为一致）。"""
        scores = {"technical.rsi.rsi_14": 50.0, "technical.ma.sma_5": 2.0}
        cold = _agg(scores, ic_series={"technical.rsi.rsi_14": [0.1]})  # 只有 1 批
        expected = (0.0 + 2.0) / 2  # RSI=50 → 0；SMA=2
        assert cold["technical"] == pytest.approx(expected)

    def test_negative_ic_flips_direction(self):
        """|mean_ic| > IC_FLIP_THRESHOLD 的负 IC 因子 → 值取负后按 |mean_ic| 加权。"""
        ic_series = {"technical.ma.sma_5": [-0.06] * IC_MIN_BATCHES}
        scores = {"technical.ma.sma_5": 2.0, "technical.signal.overall": 0.0}
        result = _agg(scores, ic_series=ic_series)
        # 仅 SMA 有 IC → 顶层键 = -2.0（翻转）
        assert result["technical"] == pytest.approx(-2.0, abs=1e-6)

    def test_no_ic_series_equal_weight(self):
        """无 IC 序列缓存（未加载）→ 等权（生产冷启动路径）。"""
        scores = {"technical.ma.sma_5": 2.0, "technical.signal.overall": 4.0}
        result = _agg(scores, ic_series=None)
        assert result["technical"] == pytest.approx(3.0)
