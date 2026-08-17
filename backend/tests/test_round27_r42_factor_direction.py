"""round27 R42: 因子分两屏方向统一（反假完成负向测试）。

验收（doc §15.1 R42）：
① 同标的场内持仓，设计全池 z（≈-0.958）与策略检查「因子分」方向一致，
   禁止再出现「设计 -0.958 vs 检查 +0.16」方向相反；
② 场外联接（不在池内，如 022449）回落单标的口径，reference='单标的'；
③ reason 含参考群体标注（相对候选池 / 单标的）。
"""
import pytest
from unittest.mock import patch

from app.services.portfolio_service import (
    _full_pool_factor_composite,
    _cross_sectional_factor_composite,
    _rule_based_suggestion,
)


def _matrix_row_neg() -> dict:
    """全池截面 z 行：所有因子键 = -0.958（深负）→ 聚合后 composite ≈ -0.958（设计同口径）。"""
    keys = [
        "technical", "technical.momentum", "technical.rsi",
        "valuation", "valuation.pe", "valuation.pb",
        "momentum", "momentum.recent_return", "momentum.vol_ratio",
    ]
    return {k: -0.958 for k in keys}


def _build_breakdowns() -> dict:
    """159338 在 13 持仓子集内相对强（technical 高）→ 旧 _cross_sectional 会算成 +（与设计相反）。"""
    return {
        "159338": {"factor_scores": {
            "technical.rsi.rsi_14": 80.0, "technical.momentum": 0.6, "valuation.pe": 25.0,
            "momentum.recent_return": 5.0,
        }, "technical_signal": {"signal": "buy", "score": 1.5}},
        "510300": {"factor_scores": {
            "technical.rsi.rsi_14": 20.0, "technical.momentum": -0.5, "valuation.pe": 12.0,
            "momentum.recent_return": -3.0,
        }, "technical_signal": {"signal": "sell", "score": -1.5}},
        "510050": {"factor_scores": {
            "technical.rsi.rsi_14": 25.0, "technical.momentum": -0.4, "valuation.pe": 13.0,
            "momentum.recent_return": -2.0,
        }, "technical_signal": {"signal": "sell", "score": -1.0}},
    }


def test_design_and_strategy_sign_agree_for_on_exchange():
    """R42 负向：策略检查改用全池 z 后，与设计屏同号（负）；旧子集截面同号（正）必须不再出现。"""
    fbs = _build_breakdowns()
    matrix = {"159338": _matrix_row_neg(), "510300": _matrix_row_neg(), "510050": _matrix_row_neg()}
    design_score = -0.958  # 设计屏全池 z（深负）

    with patch("app.services.market_data_hub.market_data_hub.get_factor_matrix", return_value=matrix):
        new_comp = _full_pool_factor_composite(fbs)["159338"]["composite"]
    old_comp = _cross_sectional_factor_composite(fbs)["159338"]

    # 旧实现：持仓子集截面 → 159338 相对强 → 正（与设计相反，正是 R42 要修的 Bug）
    assert old_comp > 0, f"旧 _cross_sectional 应给出正值（与设计相反），实际 {old_comp}"
    # 新实现：复用全池 z → 应与设计同号（负），不得是 +0.16 类正值
    assert new_comp is not None
    assert new_comp < 0, f"策略检查应复用全池 z（与设计同号负），实际 {new_comp}"
    assert (new_comp < 0) == (design_score < 0), "策略检查与设计屏因子分方向必须一致"
    # 负向核心：修复后策略检查不得再与旧子集截面同号（否则两屏仍相反）
    assert (new_comp > 0) != (old_comp > 0), "修复后策略检查不得再与旧子集截面同号"


def test_off_exchange_uses_single_symbol_caliber():
    """R42：场外联接（不在池内，如 022449）回落单标的口径，reference='单标的'。"""
    fbs = {
        "022449": {"factor_scores": {
            "technical.rsi.rsi_14": 60.0, "valuation.pe": 20.0,
        }, "technical_signal": {"signal": "hold", "score": 0.0}},
    }
    with patch("app.services.market_data_hub.market_data_hub.get_factor_matrix",
               return_value={"159338": _matrix_row_neg()}):
        res = _full_pool_factor_composite(fbs)["022449"]
    assert res["reference"] == "单标的"
    assert res["composite"] is not None


def test_reference_label_in_reason():
    """R42：reason 含参考群体标注（场内='相对候选池' / 场外='单标的'）。"""
    with patch("app.services.market_data_hub.market_data_hub.get_factor_matrix",
               return_value={"159338": _matrix_row_neg()}):
        on = _rule_based_suggestion(
            symbol="159338", name="中证A500ETF", target_weight=0.2,
            factor_score={"technical.rsi.rsi_14": 80.0}, signal={"signal": "buy", "score": 1.5},
            regime="range_bound", current_weight=0.2,
            factor_composite=-0.958, factor_composite_label="相对候选池",
        )
        off = _rule_based_suggestion(
            symbol="022449", name="联接基金", target_weight=0.1,
            factor_score={"technical.rsi.rsi_14": 60.0}, signal={"signal": "hold", "score": 0.0},
            regime="range_bound", current_weight=0.1,
            factor_composite=0.2, factor_composite_label="单标的",
        )
    assert "因子分口径：相对候选池" in on["reason"]
    assert "因子分口径：单标的" in off["reason"]
