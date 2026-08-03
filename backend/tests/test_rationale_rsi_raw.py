"""R6-F4 (round6 §十 R6-05 + §十八-7): 设计报告技术指标源对齐。

背景：factor_matrix 的 technical.rsi.rsi_14 是 zscore 标准化值（-3~3），
rationale 把它当原始 RSI（0-100）展示且阈值 30/70 恒走"超卖区域"分支。
修复：compute 保留 raw 值（_raw 键），rationale 读 raw 展示真实 RSI/MACD。
"""
import pytest

from app.engine import rationale as rt


def test_rationale_rsi_raw_neutral():
    """raw RSI 42.5 → "RSI 42.5 中性区间"（真实值，非因子分）。"""
    text = rt.build_rationale(
        code="510300", layer="core", strategy="balanced",
        meta={"name": "沪深300ETF"}, regime="neutral",
        factor_scores={"technical.rsi.rsi_14_raw": 42.5, "technical.rsi.rsi_14": -0.215},
    )
    assert "RSI 42.5" in text
    assert "中性区间" in text


def test_rationale_rsi_raw_oversold():
    """raw RSI 25 → 超卖区域（旧实现 zscore 值恒走超卖，现按真实值判断）。"""
    text = rt.build_rationale(
        code="510300", layer="core", strategy="balanced",
        meta={"name": "沪深300ETF"}, regime="neutral",
        factor_scores={"technical.rsi.rsi_14_raw": 25.0},
    )
    assert "RSI 25.0" in text
    assert "超卖区域" in text


def test_rationale_rsi_raw_overbought():
    """raw RSI 85 → 超买区域。"""
    text = rt.build_rationale(
        code="510300", layer="core", strategy="balanced",
        meta={"name": "沪深300ETF"}, regime="neutral",
        factor_scores={"technical.rsi.rsi_14_raw": 85.0},
    )
    assert "超买区域" in text


def test_rationale_rsi_raw_key_takes_priority():
    """同时存在 _raw 与 zscore 键时，_raw（真实值）优先展示。"""
    text = rt.build_rationale(
        code="510300", layer="core", strategy="balanced",
        meta={"name": "沪深300ETF"}, regime="neutral",
        factor_scores={"technical.rsi.rsi_14_raw": 42.5, "technical.rsi.rsi_14": 5.0},
    )
    assert "RSI 42.5" in text
    assert "RSI 5.0" not in text


def test_rationale_macd_raw():
    """MACD 读 raw 值（真实 DIF），正负语义正确。"""
    text = rt.build_rationale(
        code="510300", layer="core", strategy="balanced",
        meta={"name": "沪深300ETF"}, regime="neutral",
        factor_scores={"technical.macd.macd_raw": 0.0123},
    )
    assert "MACD 为正 0.0123" in text


async def test_compute_keeps_raw_rsi(monkeypatch):
    """compute()：rsi_14 自 F1-5 起即 raw 0-100（无需额外键）；macd 保留 _raw 真实 DIF。"""
    from app.factors import factor_registry as fr

    # 用注入 market_data 直接走 compute（不触发网络）
    raw = {
        "510300": {"close": [10.0 + i * 0.01 for i in range(60)],
                   "high": [10.2] * 60, "low": [9.8] * 60, "volume": [1e7] * 60,
                   "price": 10.5, "change_pct": 1.0},
    }
    reg = fr.FactorRegistry()
    scores = await reg.compute(["510300"], market_data=raw,
                               codes=["technical.rsi.rsi_14", "technical.macd.macd"])
    # rsi_14 直接是 raw 0-100（F1-5 standardization=raw）
    raw_rsi = scores["510300"]["technical.rsi.rsi_14"]
    assert 0 <= raw_rsi <= 100, f"rsi_14 应为 raw 0-100, got {raw_rsi}"
    # macd 保留真实 DIF（_raw 键）
    assert "technical.macd.macd_raw" in scores["510300"]
    macd_raw = scores["510300"]["technical.macd.macd_raw"]
    assert isinstance(macd_raw, float)


def test_aggregate_ignores_raw_keys():
    """aggregate_factor_scores 聚合时排除 _raw 键（避免 raw RSI 拉高 technical 均值）。"""
    from app.factors.factor_registry import FactorRegistry as FR

    scores = {
        "technical.rsi.rsi_14_raw": 42.5,
        "technical.rsi.rsi_14": -0.2,
        "technical.ma.sma_5": 0.1,
    }
    agg = FR.aggregate_factor_scores(scores)
    # technical 分类均值 = (-0.2 + 0.1) / 2，不含 42.5
    assert abs(agg["technical"] - (-0.05)) < 1e-9
