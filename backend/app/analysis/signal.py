from typing import Any


def composite_signal(
    technical: float = 0.0,
    valuation: float = 0.0,
    momentum: float = 0.0,
    weights: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """F1-8/§9.7 R5: 三因子加权聚合综合信号（纯函数，无 I/O）。

    规则：
      - 聚合公式：0.4*技术 + 0.4*估值 + 0.2*动量（权重可覆盖）
      - 单因子极端值封顶 |score| ≤ 1.0，防单项拉平（如动量 +9 拉平技术/估值双弱）
      - 硬约束「技术<0 且 估值<0 → 综合信号不得为 buy/偏多，至多 hold」
        （589720 实测：技术 -0.408 / 估值 -0.462 曾因动量 +1.047 被误判偏多）

    Returns:
        {"signal": "buy"|"hold"|"sell", "score": float,
         "components": {"technical": t, "valuation": v, "momentum": m}}
    """
    def _cap(v: float) -> float:
        try:
            f = float(v or 0.0)
        except (TypeError, ValueError):
            f = 0.0
        return max(-1.0, min(1.0, f))

    t, v, m = _cap(technical), _cap(valuation), _cap(momentum)
    w = weights or (0.4, 0.4, 0.2)
    score = w[0] * t + w[1] * v + w[2] * m

    # 双弱不判多：技术/估值同时为负 → 至多 hold（动量不能拉平方向）
    if t < 0 and v < 0:
        score = min(score, 0.0)

    if score >= 0.5:
        signal = "buy"
    elif score <= -0.5:
        signal = "sell"
    else:
        signal = "hold"

    return {
        "signal": signal,
        "score": round(score, 3),
        "components": {"technical": t, "valuation": v, "momentum": m},
    }


def generate_signal(indicators: dict) -> dict[str, Any]:
    if not indicators:
        return {"signal": "hold", "score": 0, "reason": "insufficient_data"}

    score = 0.0
    reasons = []

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
    import numpy as np

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
