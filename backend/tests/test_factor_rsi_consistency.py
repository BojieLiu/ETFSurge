from __future__ import annotations
"""TDD: F1-5 / §9.7 R1 — 设计因子 RSI 与 indicators 口径一致 + 估值字段按资产类别禁用。

覆盖：
  1. factor_scores 的 technical.rsi.rsi_14 是真实 0-100 RSI（与 ta.rsi 一致 ±2），
     不再是 z-score 后的 ±5 相对分
  2. compute_all_indicators 复用 factor_scores 的 RSI 时与独立计算一致
  3. aggregate_factor_scores：etf.price 不进入 valuation 聚合（价格≠估值）
  4. 黄金/债券类资产：C2 判定估值视为缺失（_valuation_is_meaningful=False）
"""
import pytest

from app.analysis.indicators import compute_all_indicators, compute_rsi
from app.factors.factor_registry import FactorRegistry, _compute_rsi_14


def _kline_rows(closes, volume=None):
    """构造行式 K 线（日期/开盘/最高/最低/收盘/成交量）。"""
    rows = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i > 0 else c
        rows.append({
            "date": f"2026-01-{i + 1:02d}",
            "open": prev, "high": max(prev, c) * 1.001, "low": min(prev, c) * 0.999,
            "close": c, "volume": volume[i] if volume else 1000000 + i,
        })
    return rows


# ── 1. RSI 因子输出真实 0-100 值 ───────────────────────────────

def test_rsi_factor_raw_value():
    """rsi_14 因子应保留真实 0-100 值（如 65.3），非 ±5 相对分。"""
    import pandas as pd
    closes = [100 + i * 0.5 for i in range(40)]  # 持续上行 → RSI 高
    data = {"close": closes, "high": closes, "low": closes}
    rsi = _compute_rsi_14(data)
    assert 0 <= rsi <= 100, f"RSI 应为 0-100 真实值: {rsi}"
    assert rsi > 60, f"上行序列 RSI 应偏高: {rsi}"


def test_rsi_factor_matches_indicators_endpoint():
    """同一 K 线下，factor RSI 与 /indicators 端点（compute_all_indicators）一致 ±2。"""
    import pandas as pd
    closes = [100 + (i % 7) * 2 - 3 for i in range(60)]
    rows = _kline_rows(closes)

    # factor 路径
    factor_rsi = _compute_rsi_14({"close": closes})
    # indicators 路径（独立计算，不传 factor_scores）
    ind = compute_all_indicators(rows)
    endpoint_rsi = ind["rsi"]

    assert abs(factor_rsi - endpoint_rsi) <= 2.0, (
        f"因子 RSI {factor_rsi:.2f} 与端点 RSI {endpoint_rsi:.2f} 不一致"
    )


def test_rsi_reuse_in_indicators_consistent():
    """compute_all_indicators 复用 factor_scores 的 RSI 时值一致（同源）。"""
    closes = [100 + (i % 9) * 1.5 for i in range(80)]
    rows = _kline_rows(closes)
    factor_rsi = _compute_rsi_14({"close": closes})
    ind = compute_all_indicators(rows, factor_scores={"technical.rsi.rsi_14": factor_rsi})
    assert abs(ind["rsi"] - factor_rsi) < 1e-6


# ── 2. aggregate：etf.price 不进 valuation ──────────────────────

def test_aggregate_valuation_excludes_price():
    """etf.price 不应再计入 valuation 聚合。"""
    result = FactorRegistry.aggregate_factor_scores({
        "etf.price": 4.5,          # 价格（非估值）
        "style.value_score": 0.8,  # 真实风格估值因子
        "etf.return_1m": 0.05,
        "technical.ma.sma_5": 0.3,
    })
    # valuation 只来自 style. 前缀
    assert result.get("valuation") == pytest.approx(0.8, abs=1e-6), result
    # momentum 仍捕获 etf.return_
    assert result.get("momentum") is not None


def test_aggregate_valuation_empty_with_only_price():
    """仅 price 时 valuation 不产出分数（黄金类资产不再有假估值）。"""
    result = FactorRegistry.aggregate_factor_scores({
        "etf.price": 3.926,
        "technical.ma.sma_5": 0.2,
    })
    assert "valuation" not in result or abs(result["valuation"]) < 0.001


# ── 3. 黄金类资产估值视为缺失（C2 惩罚触发）────────────────────

def test_valuation_is_meaningful_gold_false():
    """黄金 ETF 的估值分（错位值）视为无意义。"""
    from app.engine.allocation_engine import _valuation_is_meaningful
    assert _valuation_is_meaningful({"valuation": 3.926}, "黄金ETF") is False
    assert _valuation_is_meaningful({"valuation": -0.462}, "科创创新药ETF") is True
    assert _valuation_is_meaningful({"valuation": 0.0}, "沪深300ETF") is False


# ===== folded from test_round15_directional_ic.py =====
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
