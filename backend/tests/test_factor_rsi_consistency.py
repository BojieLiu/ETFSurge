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
