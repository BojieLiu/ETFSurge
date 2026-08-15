"""round24 R4/R14: confidence 表示法统一 + 规则路径分档非硬编码。

R14：verify_e2e 对「规则建议 confidence=0.7」无断言，回归可能把分级改回恒定值。
R4（本轮修订）：规则路径旧输出裸数值 0.5/0.7，与 LLM 的 high/medium 语义标签**同屏
混排**（`StrategyCheckResult.vue:146` `confidenceLabel` 对 0.7 直接回落显示「0.7」、
class 变 `conf-0.7` 无样式），且 0.7 实为「中等」却易读作「高置信」。

契约：`api-contracts/portfolio/strategy-check-v2.md` §关键字段契约 / §3.1-3。
统一后：全站 `high`/`medium`/`low` 三档语义标签；规则路径按因子填充率分档
（≥90%→high、≥70%→medium、<70%→low），LLM 数值/中文标签一律归一化。
"""

import pytest

from app.services.portfolio_service import (
    _normalize_confidence,
    _rule_based_suggestion,
)


def _call(fill_ratio: float | None):
    """fill_ratio=None 模拟无因子可用度信息（total=0）。"""
    fa = None if fill_ratio is None else {"filled": int(100 * fill_ratio), "total": 100}
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


# ── R4：规则路径三档语义标签 ──────────────────────────────────────────


def test_low_fill_rate_gives_low_label():
    """填充率 50% (<70%) → low（旧实现为裸数值 0.5）。"""
    s = _call(0.50)
    assert s["source"] == "rule"
    assert s["confidence"] == "low"


def test_mid_fill_rate_gives_medium_label():
    """填充率 80% (≥70%, <90%) → medium（旧 0.7 的真实语义就是「中等」）。"""
    assert _call(0.80)["confidence"] == "medium"


def test_high_fill_rate_gives_high_label():
    """填充率 95% (≥90%) → high（因子输入近乎完整）。"""
    assert _call(0.95)["confidence"] == "high"


def test_missing_availability_defaults_to_medium():
    """无因子可用度信息（total=0）→ medium，不得冒充 high。"""
    assert _call(None)["confidence"] == "medium"


def test_confidence_is_multi_tier_not_constant():
    """三档必须互不相同——若回归成恒值，本断言失败（抓「假修复」）。"""
    labels = {_call(r)["confidence"] for r in (0.40, 0.80, 0.95)}
    assert labels == {"low", "medium", "high"}


def test_rule_confidence_is_never_raw_number():
    """负向断言：规则路径不得再输出裸数值（0.5/0.7）表示法。"""
    for ratio in (0.0, 0.40, 0.69, 0.70, 0.90, 1.0, None):
        c = _call(ratio)["confidence"]
        assert isinstance(c, str), f"fill={ratio} 输出非标签: {c!r}"
        assert c in ("high", "medium", "low")


def test_rule_suggestion_action_enum_only():
    """规则路径仅输出 increase/decrease/hold 枚举（契约硬约束）。"""
    for ratio in (0.40, 0.80, None):
        assert _call(ratio)["action"] in ("increase", "decrease", "hold")


# ── R4：LLM 路径归一化（数值/中文/大小写 → 同一枚举） ──────────────────


@pytest.mark.parametrize("raw,expected", [
    (0.85, "high"), (0.8, "high"), (1, "high"),
    (0.7, "medium"), (0.5, "medium"),
    (0.49, "low"), (0.0, "low"),
    ("high", "high"), ("HIGH", "high"), ("Medium", "medium"), ("low", "low"),
    ("高", "high"), ("中", "medium"), ("低", "low"),
    ("高置信", "high"), ("0.85", "high"),
])
def test_normalize_confidence(raw, expected):
    assert _normalize_confidence(raw) == expected


def test_normalize_confidence_unknown_falls_back_to_medium():
    """无法识别（None/空/乱值）→ medium，不得静默丢字段或冒充 high。"""
    for bad in (None, "", "  ", "很高吧", {}, []):
        assert _normalize_confidence(bad) == "medium"
