"""round27 R52: 综合信号分项覆盖率门禁 + 诚实降级（反假完成负向测试）。

验收（doc §15.1 R52）：
① mock 仅技术因子值（估值/动量缺失）→ composite_decision.degraded=True 且
   signal is None（禁再出现 degraded=False + signal=hold 的假综合信号）；
② 三面齐全（技术+估值+动量均有真实值）→ 综合信号**能产出 buy/sell**（负向：
   三面齐全仍恒 hold → FAIL）；
③ 缺一个分项（≥2 分项可用）→ 权重归一，缺失分项不静默稀释分数。
"""
import pytest

from app.services.portfolio_service import _attach_composite_decisions


def test_only_technical_present_is_degraded_and_none():
    """R52 负向①：只有技术类因子、估值/动量缺失 → 诚实降级，signal=None。"""
    fbs = {
        "159338": {
            "factor_scores": {
                # 仅技术类因子键；无估值/动量键
                "technical.momentum": 1.0,
            },
            "technical_signal": {"signal": "buy", "score": 1.0},
        },
    }
    _attach_composite_decisions(fbs)
    cd = fbs["159338"]["composite_decision"]
    assert cd["degraded"] is True, f"估值/动量缺失应降级，实际 degraded={cd['degraded']}"
    assert cd["signal"] is None, f"分项不足应 signal=None，实际 {cd['signal']}"
    # 门禁反面：绝不允许「降级了却还报 hold 假信号」
    assert not (cd["degraded"] is False and cd["signal"] == "hold")


def test_three_components_present_can_buy_or_sell():
    """R52 负向②：三面齐全（技术+估值+动量均真实>0）→ 综合信号必须能产出 buy/sell，
    不得恒 hold。"""
    fbs = {
        "159338": {
            "factor_scores": {
                "technical.momentum": 1.0,
                "valuation.pe": 1.0,
                "momentum.recent_return": 1.0,
            },
            "technical_signal": {"signal": "buy", "score": 1.0},
        },
    }
    _attach_composite_decisions(fbs)
    cd = fbs["159338"]["composite_decision"]
    assert cd["degraded"] is False, f"三面齐全不应降级，实际 {cd['degraded']}"
    assert cd["signal"] in ("buy", "sell"), (
        f"三面齐全应给出方向性信号，实际 {cd['signal']}"
    )


def test_missing_one_component_weights_normalized_not_diluted():
    """R52 ③：缺估值（技术+动量可用）→ 权重归一，缺失分项不静默稀释。

    技术=0.6、动量=0.6、估值缺失：
      - 旧（不归一）：0.4*0.6 + 0.4*0 + 0.2*0.6 = 0.36 → hold（被稀释）
      - 新（归一）：(0.4*0.6 + 0.2*0.6) / 0.6 = 0.6 → buy（归一后不稀释）
    """
    fbs = {
        "159338": {
            "factor_scores": {
                "technical.momentum": 0.6,
                "momentum.recent_return": 0.6,
                # 无 valuation.* 键
            },
            "technical_signal": {"signal": "hold", "score": 0.6},
        },
    }
    _attach_composite_decisions(fbs)
    cd = fbs["159338"]["composite_decision"]
    assert cd["degraded"] is False, "≥2 分项可用不应降级"
    # 归一后 score 应达到 0.6（buy），而非被 0 估值稀释到 hold
    assert cd["signal"] == "buy", (
        f"缺估值应归一权重后达 buy，实际 signal={cd['signal']} score={cd['score']}"
    )


def test_technical_signal_absent_reduces_coverage():
    """R52 配套：技术信号 score 缺失（仅因子键）→ 覆盖项减少，仍诚实降级。"""
    fbs = {
        "159338": {
            "factor_scores": {
                "technical.momentum": 1.0,
                # 无 valuation/momentum 键，且 technical_signal 无 score
            },
            "technical_signal": {"signal": "hold", "score": None},
        },
    }
    _attach_composite_decisions(fbs)
    cd = fbs["159338"]["composite_decision"]
    # 仅 technical 分项（来自 factor_scores 键），估值/动量缺失 + 技术信号无 score
    # → 覆盖数 < 2 → 降级
    assert cd["degraded"] is True
    assert cd["signal"] is None
