"""FM3 (round35 §15.5): etf_quality 第五顶层键接入 composite。

覆盖四类断言：
1. 聚合映射归属——etf.premium_discount / etf.tracking_error → etf_quality；
2. 缺席不变性——无这两键的输入，聚合输出与旧行为逐键一致（无 etf_quality 键），
   且 technical/sentiment/momentum 权重逐字未动 → 存量 composite 不漂移；
3. 方向语义（YAML 单源 -1）——高溢价扣分、高跟踪误差扣分、深折价加分；
4. 引擎级——其余因子相同、质量更好的候选胜出；权重表每风偏 Σ=1。

探针证据链：scripts/probe_fm3_results.json（A=GO 区分度 pstdev 2.14%，
B=修复后 GO，C=NO_GO 故本批不含 shares_change）。
"""

import math

from app.core.factor_aggregate import aggregate_factor_scores
from app.engine.allocation_engine import _PROFILE_WEIGHTS
from app.factors.factor_registry import registry


def _defs() -> dict:
    if not registry._factors:
        registry.load_definitions()
    return dict(registry._factors)


# ── 1: 聚合映射归属 ──────────────────────────────────────────────

def test_etf_quality_keys_aggregate_into_new_top_key():
    scores = {"etf.premium_discount": 0.012, "etf.tracking_error": 0.008}
    out = aggregate_factor_scores(scores, definitions=_defs())
    assert "etf_quality" in out, "两因子必须聚入 etf_quality 顶层键"
    # 两因子方向均为 -1（YAML）：方向化后值 = -raw，等权均值
    expected = (-0.012 + -0.008) / 2
    assert out["etf_quality"] == __import__("pytest").approx(expected)


def test_orphan_factors_do_not_leak_into_other_categories():
    """etf.premium_discount 不得被 valuation/style 等旧前缀误接（差一词即漏接的反向）。"""
    out = aggregate_factor_scores(
        {"etf.premium_discount": 0.01, "etf.tracking_error": 0.005},
        definitions=_defs(),
    )
    for cat in ("valuation", "momentum", "sentiment", "technical"):
        assert cat not in out, f"{cat} 不应吸收 etf_quality 因子"


# ── 2: 缺席不变性 ────────────────────────────────────────────────

def test_absence_keeps_output_identical():
    """不含两因子的输入：输出与「仅旧映射」逐键一致（etf_quality 键不出现）。"""
    scores = {
        "technical.ma.sma_5": 1.2, "technical.rsi.rsi_14": 55.0,
        "etf.return_1m": 0.03, "sentiment.news_heat": 40.0,
        "style.value.pe_percentile": 0.6,
    }
    defs = _defs()
    out = aggregate_factor_scores(scores, definitions=defs)
    assert "etf_quality" not in out
    # 与手工旧口径对照（technical 均值含 rsi 方向化）
    tech_expected = (1.2 + (50.0 - 55.0) / 50.0) / 2
    assert out["technical"] == __import__("pytest").approx(tech_expected)
    assert out["momentum"] == __import__("pytest").approx(0.03)


def test_profile_weights_unchanged_for_legacy_keys_and_sum_to_one():
    """technical/sentiment/momentum 三键权重与 FM3 前逐字一致；各风偏 Σ=1；
    划出的份额全部来自 valuation 槽（0.2→0.05）。"""
    legacy = {
        "defensive": {"technical": 0.4, "sentiment": 0.25, "momentum": 0.15},
        "balanced": {"technical": 0.3, "sentiment": 0.2, "momentum": 0.3},
        "aggressive": {"technical": 0.2, "sentiment": 0.15, "momentum": 0.45},
    }
    for profile, table in _PROFILE_WEIGHTS.items():
        for k, v in legacy[profile].items():
            assert table[k] == v, f"{profile}.{k} 必须保持不动"
        assert abs(sum(table.values()) - 1.0) < 1e-9, f"{profile} 权重和必须为 1"
        assert table["valuation"] == 0.05, "valuation 槽应从 0.2 划到 0.05"
        assert table["etf_quality"] == 0.15


# ── 3: 方向语义 ──────────────────────────────────────────────────

def test_high_premium_penalized_deep_discount_rewarded():
    defs = _defs()
    hot = aggregate_factor_scores({"etf.premium_discount": 0.04}, definitions=defs)
    cheap = aggregate_factor_scores({"etf.premium_discount": -0.02}, definitions=defs)
    assert hot["etf_quality"] < 0 < cheap["etf_quality"], (
        "高溢价应为负贡献、深折价应为正贡献（direction=-1）"
    )


def test_high_tracking_error_penalized():
    defs = _defs()
    sloppy = aggregate_factor_scores({"etf.tracking_error": 0.02}, definitions=defs)
    tight = aggregate_factor_scores({"etf.tracking_error": 0.001}, definitions=defs)
    assert sloppy["etf_quality"] < tight["etf_quality"], "跟踪误差越大质量分越低"


# ── 4: 引擎级 composite 生效（走 _select_and_weight 真实全链）────────

def _cand(symbol: str) -> dict:
    return {"symbol": symbol, "name": f"{symbol}测试ETF", "layer": "satellite",
            "tracked_index": f"{symbol}指数", "segment": symbol}


def test_engine_prefers_better_quality_all_else_equal():
    """候选仅差 premium_discount（其余因子相同且为正，双活）：深折价者得分更高，
    且分差恰为 Δetf_quality×0.15。"""
    from app.engine.allocation_engine import _select_and_weight

    cands = [_cand("QA"), _cand("QB")]
    # 共同技术面保证两者 composite 均为正（卫星分地板不淘汰），仅质量维度有差
    common = {"technical.macd.macd": 1.0}
    matrix = {
        "QA": {**common, "etf.premium_discount": -0.01},  # 深折价 → 正贡献
        "QB": {**common, "etf.premium_discount": 0.03},   # 高溢价 → 负贡献
    }
    out = _select_and_weight(
        cands, matrix, budget=1.0, layer="satellite", regime="neutral",
        strategy="balanced", max_count=2, factor_definitions=_defs(),
    )
    assert len(out) == 2, "两候选都应存活（共同技术面垫底）"
    by_sym = {r["symbol"]: r for r in out}
    assert by_sym["QA"]["factor_score"] > by_sym["QB"]["factor_score"]
    # 数量级核对：balanced etf_quality 权重 0.15
    qa = aggregate_factor_scores(matrix["QA"], definitions=_defs())["etf_quality"]
    qb = aggregate_factor_scores(matrix["QB"], definitions=_defs())["etf_quality"]
    expected_diff = (qa - qb) * 0.15
    actual_diff = by_sym["QA"]["factor_score"] - by_sym["QB"]["factor_score"]
    assert math.isclose(actual_diff, expected_diff, rel_tol=0.05, abs_tol=1e-6), (
        f"composite 差应≈Δetf_quality×0.15: {actual_diff} vs {expected_diff}"
    )
