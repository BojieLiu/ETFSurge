"""B6 (round35 §6.6 / 契约 design.md §6.3): 收益指标持仓推导单测。

- portfolio_volatility 闭式解：同序列完全正相关 → σ_p=σ_a；
  等权反向序列（ρ=-1、σ 相等）→ σ_p≈0；一般两资产对照手算。
- 缺席语义（契约约束 1）：任一持仓历史不足 / 任一对 r=None / 有效持仓<2 →
  None（调用方整体省略字段）。
- _attach_estimate_sources 编排接线：可行 → volatility_estimate+model_estimate
  标注齐全；数据残缺 → 仅静态三指标 reference_static，无 volatility 键。
"""

import math

import pytest

from app.engine.correlation import (
    annualized_vol,
    correlation_matrix,
    portfolio_volatility,
)
from app.services import strategy_design as sd


def _closes_from_daily_returns(rets: list[float], base: float = 100.0) -> list[float]:
    """由日收益率构造 closes（旧→新），长度 = len(rets)+1。"""
    out = [base]
    for r in rets:
        out.append(out[-1] * (1 + r))
    return out


def _const_returns(c: float, n: int = 40) -> list[float]:
    return [c] * n


# ── annualized_vol ───────────────────────────────────────────────

def test_constant_series_has_zero_vol():
    closes = _closes_from_daily_returns(_const_returns(0.001))
    assert annualized_vol(closes) == pytest.approx(0.0, abs=1e-12)


def test_short_history_is_none():
    closes = _closes_from_daily_returns([0.01] * 10)
    assert annualized_vol(closes) is None


# ── portfolio_volatility 闭式解 ──────────────────────────────────

def _two_asset_fixture(b_mult: float = 1.0):
    rets = [((i % 7) - 3) * 0.004 for i in range(40)]  # 非退化确定性序列
    a = _closes_from_daily_returns(rets)
    b = _closes_from_daily_returns([r * b_mult for r in rets])
    return {"A": a, "B": b}


def test_perfectly_correlated_equal_weights_vol_equals_component():
    """ρ=1、σ_A=σ_B、等权 → σ_p = σ_A（闭式：√(w²+w²+2w²·1)·σ=w_total·σ）。"""
    closes = _two_asset_fixture(b_mult=1.0)
    matrix = correlation_matrix(closes, window=60)
    w = {"A": 0.5, "B": 0.5}
    sigma_a = annualized_vol(closes["A"])
    got = portfolio_volatility(closes, w, matrix)
    assert sigma_a is not None and got is not None
    # 引擎输出 round(,4)：0.1258 级别值 rel 容差 2e-3 覆盖舍入
    assert got == pytest.approx(sigma_a, rel=2e-3)


def test_perfectly_anti_correlated_equal_weights_near_zero():
    """ρ=-1、等权、σ 相等 → 组合波动 ≈0（完全对冲的解析极限）。"""
    closes = _two_asset_fixture(b_mult=-1.0)
    matrix = correlation_matrix(closes, window=60)
    assert matrix[("A", "B")] == pytest.approx(-1.0, abs=1e-6)
    got = portfolio_volatility(closes, {"A": 0.5, "B": 0.5}, matrix)
    assert got is not None
    sigma_a = annualized_vol(closes["A"])
    # b 序列乘 -1 后日收益取反、|std| 不变 → σ_B=σ_A；完全对冲 → σ_p≈0
    # （引擎对浮点噪声负值夹 0：解析零是合法结果而非缺数据）
    assert got == pytest.approx(0.0, abs=5e-3), f"对冲组合波动应≈0: {got} vs σ={sigma_a}"


def test_general_two_assets_matches_hand_computation():
    """非平凡相关下与手算 wᵀ(σ⊙ρ⊙σ)w 对照（rel 2e-3，覆盖引擎 4 位小数舍入）。"""
    rets_a = [((i % 5) - 2) * 0.005 for i in range(40)]
    rets_b = [((i % 4) - 1.5) * 0.003 for i in range(40)]
    closes = {"A": _closes_from_daily_returns(rets_a),
              "B": _closes_from_daily_returns(rets_b)}
    matrix = correlation_matrix(closes, window=60)
    w = {"A": 0.3, "B": 0.7}
    sa, sb = annualized_vol(closes["A"]), annualized_vol(closes["B"])
    r = matrix[("A", "B")]
    expected = math.sqrt(
        (0.3 * sa) ** 2 + (0.7 * sb) ** 2 + 2 * 0.3 * 0.7 * sa * sb * r
    )
    got = portfolio_volatility(closes, w, matrix)
    assert got == pytest.approx(expected, rel=2e-3)


# ── 缺席语义（契约约束 1）────────────────────────────────────────

def test_missing_history_for_one_symbol_returns_none():
    closes = _two_asset_fixture()
    closes["B"] = closes["B"][:20]  # 历史不足
    matrix = correlation_matrix({"A": closes["A"], "B": closes["B"]}, window=60)
    assert portfolio_volatility(closes, {"A": 0.5, "B": 0.5}, matrix) is None


def test_none_correlation_pair_returns_none():
    closes = _two_asset_fixture()
    matrix = {("A", "B"): None}
    assert portfolio_volatility(closes, {"A": 0.5, "B": 0.5}, matrix) is None


def test_single_holding_returns_none():
    closes = _two_asset_fixture()
    assert portfolio_volatility(
        {"A": closes["A"]}, {"A": 1.0}, {}) is None


# ── 编排接线 ─────────────────────────────────────────────────────

def test_attach_estimate_sources_full_path(monkeypatch):
    """ρ/σ 齐备 → volatility_estimate 出现且标注 model_estimate；静态三项恒在。"""
    closes = _two_asset_fixture()
    monkeypatch.setattr(sd, "_CORR_CLOSES_CACHE",
                        {"A": closes["A"], "B": closes["B"]})
    matrix = correlation_matrix(closes, window=60)
    s: dict = {}
    allocs = [
        {"symbol": "A", "weight": 0.5},
        {"symbol": "B", "weight": 0.4},
    ]
    sd._attach_estimate_sources(s, allocs, matrix)
    vol = s["volatility_estimate"]
    assert isinstance(vol, float) and vol > 0
    src = s["estimate_sources"]
    assert src["volatility_estimate"] == "model_estimate"
    assert src["expected_return"] == "reference_static"
    assert src["max_drawdown"] == "reference_static"
    assert src["sharpe_ratio"] == "reference_static"
    # 数值核对：权重含现金拖累（0.9 投出）
    manual = portfolio_volatility(
        {"A": closes["A"], "B": closes["B"]},
        {"A": 0.5, "B": 0.4}, matrix)
    assert vol == pytest.approx(manual)


def test_attach_estimate_sources_degrades_to_static_only(monkeypatch):
    """缓存缺一个标的的历史 → 无 volatility_estimate 键，仅静态三指标。"""
    closes = _two_asset_fixture()
    monkeypatch.setattr(sd, "_CORR_CLOSES_CACHE", {"A": closes["A"]})
    s: dict = {}
    allocs = [{"symbol": "A", "weight": 0.5}, {"symbol": "B", "weight": 0.4}]
    sd._attach_estimate_sources(s, allocs, {("A", "B"): 0.2})
    assert "volatility_estimate" not in s, "不得用静态值冒充模型估算"
    assert s["estimate_sources"] == {
        "expected_return": "reference_static",
        "max_drawdown": "reference_static",
        "sharpe_ratio": "reference_static",
    }


def test_attach_never_raises_on_garbage(monkeypatch):
    """异常输入不冒泡（主链路不受阻），estimate_sources 仍写入。"""
    monkeypatch.setattr(sd, "_CORR_CLOSES_CACHE", {"A": ["not-a-number"]})
    s: dict = {}
    sd._attach_estimate_sources(s, [{"symbol": "A", "weight": 1.0}],
                                {("A", "A"): None})
    assert "volatility_estimate" not in s
    assert s["estimate_sources"]["sharpe_ratio"] == "reference_static"
