from typing import Any


def generate_signal(indicators: dict) -> dict[str, Any]:
    if not indicators:
        return {"signal": "hold", "score": 0, "reason": "insufficient_data"}

    score = 0
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

    if score >= 2:
        signal = "buy"
    elif score <= -2:
        signal = "sell"
    else:
        signal = "hold"

    return {
        "signal": signal,
        "score": round(score, 2),
        "reasons": reasons,
    }


def compute_td_sequential(close: "pd.Series") -> dict:
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
