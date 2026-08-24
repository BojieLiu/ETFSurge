# -*- coding: utf-8 -*-
"""round35 §15.4 FM2 (docs/round35-architecture-review.md) —
IC 加权尺度相对化：「毕业即降权」缺陷修复的行为钉死。

旧实现（对旧代码必红）：warm 因子 weight = max(mean_ic, 0) ≈ 0.02~0.05，
而冷启动因子 weight = 1.0 → 通过验证的好因子反而被压到等权的 ~3%——
「数据多了更准」反向成立。新契约：
- warm 权重 = |mean_ic| / ref（ref = 本次聚合内 warm 因子中位 |mean_ic|），
  保底不低于等权 1.0；
- 负 IC 翻转分支沿用同尺度（翻转后强度 ≥ 等权）；
- 冷启动（< IC_MIN_BATCHES）恒等权，行为不变；
- ref 退化（全零 IC）回落等权，不除零。
"""
import pytest

from app.core.factor_aggregate import (
    IC_MIN_BATCHES,
    aggregate_factor_scores,
)


def _series(mean: float, n: int = IC_MIN_BATCHES) -> list[float]:
    """构造衰减均值恰为 *mean* 的 IC 序列（常数序列即可）。"""
    return [mean] * n


def test_warm_factor_not_demoted_below_cold_start():
    """负向（旧实现必红）：同类内唯一 warm 因子不得被冷启动等权淹没。

    同类两因子（均 +1 方向，值 10 / 2，均过零值过滤）：新契约权重 1:1 →
    聚合 ≈6；旧实现 warm 权重 max(.03,0)=0.03 vs 冷启动 1.0 → ≈2.3。
    （注：冷同伴不能取 0——聚合入口 abs(v)>0.001 会把零值因子滤出竞争。）
    """
    scores = {"technical.ma.sma_5": 10.0, "technical.macd.macd": 2.0}
    ic = {"technical.ma.sma_5": _series(0.03)}
    out = aggregate_factor_scores(scores, ic_series=ic)
    assert out["technical"] == pytest.approx(6.0, abs=0.5), out.get("technical")


def test_strong_warm_outranks_weak_warm_and_cold():
    """强 IC 因子权重 > 弱 IC 因子 ≥ 冷启动（排序保持且无人低于基线）。"""
    scores = {
        "etf.return_1m": 9.0,     # 强 warm（momentum 键）
        "etf.return_3m": 1.0,     # 弱 warm
        "etf.change_pct": 0.0,    # 冷启动
    }
    ic = {"etf.return_1m": _series(0.08), "etf.return_3m": _series(0.02)}
    out = aggregate_factor_scores(scores, ic_series=ic)
    momentum = out["momentum"]
    plain_avg = (9.0 + 1.0 + 0.0) / 3
    assert momentum > plain_avg, f"强 IC 未拉高聚合值: {momentum} vs avg {plain_avg}"
    assert momentum < 9.0  # 弱项与冷启动仍有话语权


def test_negative_ic_flip_keeps_strength_floor():
    """负 IC 翻转分支：方向化值被取反，且翻转后强度不低于等权。

    kdj（negate 方向）原始 -6 → 方向化 +6；同伴 ma=+4。无 IC 基线等权 → +5。
    注入 kdj 强负 IC（-0.05）后翻转：新契约两因子等权 → (-6+4)/2 = -1；
    旧实现 kdj 权重 |ic|=0.05 vs 冷启动 1.0 → 被稀释到 ≈+3.7（旧必红）。
    """
    scores = {"technical.kdj.kdj": -6.0, "technical.ma.sma_5": 4.0}
    baseline = aggregate_factor_scores(scores)
    assert baseline["technical"] == pytest.approx(5.0, abs=1e-6)

    ic = {"technical.kdj.kdj": _series(-0.05)}  # |0.05| > FLIP 阈值 0.03 → 翻转
    out = aggregate_factor_scores(scores, ic_series=ic)
    assert out["technical"] == pytest.approx(-1.0, abs=0.5), out.get("technical")


def test_degenerate_all_zero_ic_falls_back_to_equal_weights():
    """全零 IC：ref 退化为 0 → 回落等权均值，不崩不偏（同 +1 方向因子对）。"""
    scores = {"technical.ma.sma_5": 4.0, "technical.macd.macd": 8.0}
    ic = {"technical.ma.sma_5": _series(0.0), "technical.macd.macd": _series(0.0)}
    out = aggregate_factor_scores(scores, ic_series=ic)
    assert out["technical"] == pytest.approx(6.0, abs=1e-6)


def test_cold_start_unchanged_without_ic_series():
    """无 ic_series 注入 → 全等权（既有行为回归锚）。"""
    out = aggregate_factor_scores({"technical.ma.sma_5": 3.0, "sentiment.news_heat": 9.0})
    # 不同顶层键各自独立聚合，这里仅验证不抛与键存在
    assert out["technical"] == pytest.approx(3.0)
    assert out["sentiment"] == pytest.approx(9.0)
