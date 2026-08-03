"""F10 (round6 §十五 R6-15.2, 用户已决策两者都做): 决策表信号-因子背离分支。

背景：159992 创新药 tech_signal=SELL 但 avg_factor=+3.57（强正）→ 决策表
fall-through 到默认 hold，reason 裸写"信号 sell，维持现状"自相矛盾。
修复：sig=sell + 因子强正 → hold 带背离解释；sig=buy + 因子弱 → hold 对称；
原 increase/decrease 分支保留（U2 R2 不回归）。
"""
from app.services.portfolio_service import _rule_based_suggestion


def _sugg(sig, factor_score, regime="range_bound", current_weight=0.1, target_weight=0.1):
    return _rule_based_suggestion(
        symbol="159992",
        name="创新药ETF",
        factor_score=factor_score,
        signal={"signal": sig, "score": 0.0},
        regime=regime,
        target_weight=target_weight,
        current_weight=current_weight,
    )


def test_sell_with_strong_positive_factor_holds_with_explanation():
    """sig=sell + avg_factor=+3.57 → hold 且 reason 含背离解释（非裸"信号 sell 维持现状"）。"""
    s = _sugg("sell", {"technical": 3.57, "momentum": 1.2, "valuation": 0.5})
    assert s["action"] == "hold"
    assert "技术面偏空" in s["reason"], s["reason"]
    assert "因子分强正" in s["reason"], s["reason"]
    assert "MA20" in s["reason"]
    # 文案自洽门禁：背离时不得裸写"信号 sell，维持现状"
    assert "信号 sell，维持现状" not in s["reason"]


def test_buy_with_negative_factor_holds_symmetric():
    """sig=buy + avg_factor=-1.0 → hold 且解释（对称分支）。"""
    s = _sugg("buy", {"technical": -1.0, "momentum": -0.8})
    assert s["action"] == "hold"
    assert "技术面偏多" in s["reason"], s["reason"]
    assert "因子分偏弱" in s["reason"], s["reason"]
    assert "信号 buy，维持现状" not in s["reason"]


def test_u2_r2_increase_branch_not_regressed():
    """U2 R2 回归：buy + 因子>0.5 非 bearish → increase。"""
    s = _sugg("buy", {"technical": 0.8, "momentum": 0.6}, regime="range_bound")
    assert s["action"] == "increase"


def test_u2_r2_decrease_branch_not_regressed():
    """U2 R2 回归：sell + 因子<-0.5 → decrease。"""
    s = _sugg("sell", {"technical": -0.8, "momentum": -0.6})
    assert s["action"] == "decrease"


def test_weak_sell_still_holds_with_plain_reason():
    """弱信号 sell + 因子中性 → 默认 hold（无背离，不带强正解释）。"""
    s = _sugg("sell", {"technical": 0.2, "momentum": -0.1})
    assert s["action"] == "hold"
    assert "技术面偏空" not in s["reason"]
