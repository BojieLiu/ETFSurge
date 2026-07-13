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
