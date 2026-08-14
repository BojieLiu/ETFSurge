"""round24 R14: 规则兜底建议 confidence 须为数据驱动的两档分级，不得硬编码 0.7。

R14 关注：verify_e2e 对「规则建议 confidence=0.7」无断言，回归可能把两档分级改回恒 0.7。
本测试固化 round18 P2-7 的两档逻辑：
  · 因子填充率 <70% → confidence=0.5（medium，数据不完整）
  · 因子填充率 >=70% → confidence=0.7
并验证 R4 表示法一致性：规则路径 confidence 为数值（0.5/0.7），与 LLM 的 high/medium
语义标签分处不同字段，本测试仅锁定规则路径两档数值真实存在、非单一常量。
"""

from app.services.portfolio_service import _rule_based_suggestion


def _call(fill_ratio: float | None):
    """fill_ratio=None 模拟无因子可用度信息（等价于 total=0 → 走 >=70% 分支）。"""
    if fill_ratio is None:
        fa = None
    else:
        fa = {"filled": int(100 * fill_ratio), "total": 100}
    return _rule_based_suggestion(
        symbol="159992",
        name="创新药",
        target_weight=0.10,
        factor_score={"technical.rsi.rsi_14": 0.6},
        signal={"signal": "buy"},
        regime="range_bound",
        current_weight=0.08,
        factor_availability=fa,
    )


def test_low_fill_rate_gives_confidence_0_5():
    """填充率 50% (<70%) → confidence=0.5，证伪「恒 0.7 硬编码」。"""
    s = _call(0.50)
    assert s["source"] == "rule"
    assert s["confidence"] == 0.5


def test_high_fill_rate_gives_confidence_0_7():
    """填充率 90% (>=70%) → confidence=0.7。"""
    s = _call(0.90)
    assert s["source"] == "rule"
    assert s["confidence"] == 0.7


def test_missing_availability_defaults_to_0_7():
    """无因子可用度信息（total=0）→ 走 >=70% 分支，confidence=0.7。"""
    s = _call(None)
    assert s["confidence"] == 0.7


def test_confidence_is_two_tier_not_constant():
    """两档必须不同——若回归成恒值，本断言失败（抓「假修复」）。"""
    low = _call(0.40)["confidence"]
    high = _call(0.80)["confidence"]
    assert low != high
    assert low == 0.5 and high == 0.7


def test_rule_suggestion_action_enum_only():
    """规则路径仅输出 increase/decrease/hold 枚举（契约硬约束）。"""
    for ratio in (0.40, 0.80, None):
        s = _call(ratio)
        assert s["action"] in ("increase", "decrease", "hold")
