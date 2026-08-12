"""
round18 P0-3 / P1-1 测试（2026-08-12 实施）：
- P0-3: 策略检查 factor_summary KDJ 对齐 /market/indicators 原始值（负向：KDJ 负值 → FAIL）
- P1-1: 规则引擎建议文案诚实化——increase 不含「基本面」（无基本面数据）；
        sell 信号下 hold 不再提示「加仓机会」（D8 逻辑矛盾）
"""

import pytest


def _suggestion(avg_factor, sig, regime="range_bound", current=None, target=0.1):
    from app.services.portfolio_service import _rule_based_suggestion
    fs = {"technical.rsi.rsi_14": avg_factor}
    return _rule_based_suggestion(
        symbol="512000", name="券商ETF", target_weight=target,
        factor_score=fs, signal={"signal": sig}, regime=regime,
        current_weight=current,
    )


class TestP11SuggestionWording:
    """round18 P1-1: 措辞与数据支撑匹配（负向断言）。"""

    def test_increase_reason_no_fundamental_claim(self):
        """increase 理由不含「基本面」措辞（规则引擎无基本面数据，
        负向: 「基本面与动量共振」仍在 → FAIL）。"""
        s = _suggestion(avg_factor=0.7, sig="buy")
        assert s["action"] == "increase"
        assert "基本面" not in s["reason"], f"increase 不应声称基本面支撑: {s['reason']}"
        assert "因子与技术信号共振" in s["reason"]

    def test_sell_hold_reason_no_add_hint(self):
        """sell 信号 + 中性因子分 → hold 且不含「加仓机会」（D8: 卖出信号下
        提示加仓 = 逻辑矛盾；负向: 仍含加仓暗示 → FAIL）。"""
        s = _suggestion(avg_factor=-0.19, sig="sell")
        assert s["action"] == "hold"
        assert "加仓机会" not in s["reason"], f"sell+hold 不应提示加仓: {s['reason']}"
        assert "暂不加仓" in s["reason"]

    def test_hold_neutral_reason_keeps_add_hint(self):
        """非 sell 信号下 hold 仍保留「关注加仓机会」（正常语义不误伤）。"""
        s = _suggestion(avg_factor=0.0, sig="hold")
        assert s["action"] == "hold"
        assert "加仓机会" in s["reason"]
