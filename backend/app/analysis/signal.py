from typing import Any

# round35 B1-F1b (docs/round35-architecture-review.md §4.1 D1): 纯函数下沉至
# engine/signal.py——engine/rationale.py 此前经相对导入引用本模块（绕过纯度门禁）。
# 此处 re-export 保持既有调用点兼容（上层→下层为合法依赖方向）；
# composite_signal_with_gate 留在本模块（业务门禁语义属上层）。
from ..engine.signal import _cap, composite_signal  # noqa: F401  re-export 下沉兼容

# round24 R25: 综合信号降级门禁阈值（与 R3 data_precision 的 0.6 同源）
_COMPOSITE_VALID_RATE_FLOOR = 0.6


def composite_signal_with_gate(
    technical: float = 0.0,
    valuation: float = 0.0,
    momentum: float = 0.0,
    factor_valid_rate: float | None = None,
    weights: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """round24 R25: 综合信号 + 降级门禁（纯函数，无 I/O）。

    背景（R25 实证）：策略检查/标的分析已把 33 维因子分 + 基本面（PE/PB）纳入展示列
    与 LLM 叙述，但未聚合进结构化 buy/sell/hold 决策信号——持仓技术面板纯技术、
    另两面因子基本面只展示不决策，三面口径不一致。

    本函数把 0.4技术+0.4估值+0.2动量 聚合成综合信号（复用 composite_signal），
    但应用 R3 式降级门禁：`factor_valid_rate < 0.6`（盘后/熔断 valid_rate=0%）时
    **拒绝合成结论**（signal=None, degraded=true）——否则会复现 R3「仅供参考横幅 +
    精确数字」的假精确（因子缺失时综合信号无统计意义）。

    Args:
        technical/valuation/momentum: 三个维度的分项分数（-1..1，内部 cap）
        factor_valid_rate: 因子有效比例 0-1；None = 未提供（不做门禁，保持原语义）
        weights: 三因子权重，默认 (0.4, 0.4, 0.2)

    Returns:
        {"signal": "buy"|"hold"|"sell"|None, "score": float|None, "degraded": bool,
         "reason": str, "components": {...}}
    """
    if factor_valid_rate is not None and factor_valid_rate < _COMPOSITE_VALID_RATE_FLOOR:
        cov_pct = round(max(0.0, min(1.0, float(factor_valid_rate))) * 100, 1)
        return {
            "signal": None,
            "score": None,
            "degraded": True,
            # R74 (round29): 口径自描述——原「因子数据缺失 X%」与摘要「因子填充率 Y%」
            # 互斥矛盾（两处百分数底不同）。改为明示「分项覆盖率」基底 + 阈值，避免
            # 专业投资者把不同口径的百分比误读为同一数字。
            "reason": (
                f"因子数据覆盖率不足（分项覆盖 {cov_pct:g}%，低于 60% 阈值）：综合信号不可用"
                "（退化为纯技术信号，不合成因子/基本面结论）"
            ),
            "components": {
                "technical": _cap(technical), "valuation": _cap(valuation),
                "momentum": _cap(momentum),
            },
        }
    out = composite_signal(technical, valuation, momentum, weights)
    return {
        "signal": out["signal"],
        "score": out["score"],
        "degraded": False,
        "reason": "综合信号正常（技术+估值+动量聚合）",
        "components": out["components"],
    }


def neutral_zone_info(indicators: dict, reasons: list[str]) -> str | None:
    """round24 R25: 中性区 info reason 补充（消除 Q1「caption 承诺 RSI/KDJ 但 reason
    只显 MACD/MA」的误导）。

    generate_signal 的 reason 只在极端区 emit RSI/KDJ（RSI<40/>60、KDJ 超买超卖）；
    calm 市（RSI 40-60、KDJ 中段）无相关条目，用户误以为「不含 RSI/KDJ」。
    本函数在**无极端 reason** 且 RSI 处于中性区时补一条 info（纯函数，无 I/O）。

    Returns:
        补充文案（如「RSI=52 中性、KDJ 中段，无极端信号」）；无指标/已有极端 reason → None。
    """
    if not isinstance(indicators, dict):
        return None
    if reasons:
        # 已有任一极端 reason → 不补（避免重复/矛盾）
        return None
    rsi = indicators.get("rsi")
    if isinstance(rsi, (int, float)) and 40 <= rsi <= 60:
        kdj = indicators.get("kdj") or {}
        k, d = kdj.get("k"), kdj.get("d")
        parts = [f"RSI={rsi:.1f} 中性"]
        if isinstance(k, (int, float)) and isinstance(d, (int, float)):
            parts.append("KDJ 中段")
        parts.append("无极端信号")
        return "、".join(parts)
    return None


def generate_signal(indicators: dict) -> dict[str, Any]:
    if not indicators:
        return {"signal": "hold", "score": 0, "reason": "insufficient_data"}

    score = 0.0
    reasons = []
    overbought = False  # P1-3/P1-6: 超买钝化标志（KDJ.J>100 / RSI>80）

    rsi = indicators.get("rsi", 50)
    if rsi is not None and rsi != 50:
        if rsi < 30:
            score += 2
            reasons.append(f"RSI={rsi:.1f} 超卖")
        elif rsi > 70:
            score -= 2
            reasons.append(f"RSI={rsi:.1f} 超买")
        elif rsi < 40:
            score += 1
            reasons.append(f"RSI={rsi:.1f} 偏弱")
        elif rsi > 60:
            score -= 1
            reasons.append(f"RSI={rsi:.1f} 偏强")
        # P1-3/P1-6 (round20 D-B1): RSI>80 极端超买钝化——不得给 BUY 信号
        if rsi > 80:
            score -= 2
            reasons.append(f"RSI={rsi:.1f} 极端超买钝化")
            overbought = True

    macd = indicators.get("macd", {})
    if macd:
        dif = macd.get("dif", 0)
        dea = macd.get("dea", 0)
        if dif > dea and dif > 0:
            score += 1
            reasons.append("MACD金叉多头")
        elif dif < dea and dif < 0:
            score -= 1
            reasons.append("MACD死叉空头")
        elif dif > dea:
            score += 0.5
            reasons.append("MACD偏多")
        elif dif < dea:
            score -= 0.5
            reasons.append("MACD偏空")

    kdj = indicators.get("kdj", {})
    if kdj:
        k, d, j = kdj.get("k", 50), kdj.get("d", 50), kdj.get("j", 50)
        if k > d and k < 30:
            score += 1
            reasons.append("KDJ超卖区金叉")
        elif k < d and k > 70:
            score -= 1
            reasons.append("KDJ超买区死叉")
        # round23 F10: KDJ 超买（J>=80，与 _KDJ_HINT「超买区 v>=80」同源）不得给 BUY。
        # 旧逻辑仅判 J>100，导致 J∈[80,100] 超买区（如 159338 J=85.7、159516 J=98.7）
        # 仍判 BUY/increase，与「超买应谨慎/卖出」矛盾。阈值下移到 80 覆盖整个超买区。
        if j >= 80:
            score -= 2
            reasons.append(f"KDJ超买区(J={j:.1f})")
            overbought = True

    boll = indicators.get("bollinger", {})
    if boll:
        bandwidth = boll.get("bandwidth", 100)
        if bandwidth < 5:
            score += 0.5
            reasons.append(f"布林带宽窄({bandwidth:.1f}%) 变盘前兆")

    ma5 = indicators.get("ma5")
    ma20 = indicators.get("ma20")
    if ma5 is not None and ma20 is not None:
        if ma5 > ma20:
            score += 1
            reasons.append("MA5>MA20 多头排列")
        else:
            score -= 1
            reasons.append("MA5<MA20 空头排列")

    # ── 九转信号 ────────────────────────────────────────────
    td = indicators.get("td_sequential", {})
    if td:
        if td.get("buy_setup_9"):
            score += 1.5
            reasons.append("九转买入序列9 反转窗口")
        elif td.get("sell_setup_9"):
            score -= 1.5
            reasons.append("九转卖出序列9 反转窗口")
        buy = td.get("current_buy", 0)
        sell = td.get("current_sell", 0)
        if buy >= 7 and buy < 9:
            score += 0.5
            reasons.append(f"九转买入序列{buy} 接近反转")
        if sell >= 7 and sell < 9:
            score -= 0.5
            reasons.append(f"九转卖出序列{sell} 接近反转")

    # Z10: Relaxed thresholds from +/-2.0 to +/-1.5
    if score >= 1.5:
        signal = "buy"
    elif score <= -1.5:
        signal = "sell"
    else:
        signal = "hold"

    # P1-3/P1-6 (round20 D-B1): 超买钝化（KDJ.J>100 / RSI>80）不得给 BUY——降级为 hold，
    # 并追加「超买回落风险」提示，避免「超买仍买入」的逻辑矛盾。
    if overbought and signal == "buy":
        signal = "hold"
        reasons.append("超买钝化，信号降级为持有（超买回落风险）")

    return {
        "signal": signal,
        "score": round(score, 2),
        "reasons": reasons,
    }


import pandas as pd


def compute_td_sequential(close: pd.Series) -> dict:
    """计算 Tom Demark Sequential 九转序列。

    Args:
        close: 收盘价序列（pandas Series）

    Returns:
        {
            "buy_sequence": list[int],     # 买入九转计数(每日)
            "sell_sequence": list[int],    # 卖出九转计数(每日)
            "buy_setup_9": bool,           # 当前是否完成买入九转
            "sell_setup_9": bool,          # 当前是否完成卖出九转
            "current_buy": int,            # 当前买入计数
            "current_sell": int,           # 当前卖出计数
        }
    """
    import pandas as pd

    if not isinstance(close, pd.Series):
        try:
            close = pd.Series(close)
        except Exception:
            return {"buy_sequence": [], "sell_sequence": [],
                    "buy_setup_9": False, "sell_setup_9": False,
                    "current_buy": 0, "current_sell": 0}

    n = len(close)
    if n < 8:
        return {"buy_sequence": [] if n == 0 else [0] * n,
                "sell_sequence": [] if n == 0 else [0] * n,
                "buy_setup_9": False, "sell_setup_9": False,
                "current_buy": 0, "current_sell": 0}

    buy_count = [0] * n
    sell_count = [0] * n

    for i in range(4, n):
        # 买入九转: close[i] < close[i-4]
        if close.iloc[i] < close.iloc[i - 4]:
            buy_count[i] = min(buy_count[i - 1] + 1, 9) if buy_count[i - 1] > 0 else 1
        else:
            buy_count[i] = 0

        # 卖出九转: close[i] > close[i-4]
        if close.iloc[i] > close.iloc[i - 4]:
            sell_count[i] = min(sell_count[i - 1] + 1, 9) if sell_count[i - 1] > 0 else 1
        else:
            sell_count[i] = 0

    return {
        "buy_sequence": buy_count,
        "sell_sequence": sell_count,
        "buy_setup_9": buy_count[-1] >= 9,
        "sell_setup_9": sell_count[-1] >= 9,
        "current_buy": buy_count[-1],
        "current_sell": sell_count[-1],
    }
