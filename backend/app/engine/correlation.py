"""
correlation.py — 收益相关性纯函数引擎（round19 P1-①，2026-08-12）

目标：为组合内标的提供真实收益相关性矩阵（60 日日收益率 Pearson r），
替代关键词启发式成为唯一相关性事实源。纯函数无 I/O，可单测。

- correlation_matrix: 按日期对齐后计算 Pearson r（inner-join）
- high_correlation_pairs: 高相关对清单（r > threshold）
- avg_correlation: 组合加权平均相关（权重作参）

数据不足降级（诚实性）：某标的历史 < 30 根 → 该标的相关系数标 None，
**不得用 0 或默认值冒充**；矩阵整体 available 语义由调用方维护。
"""
from __future__ import annotations

MIN_SAMPLES = 30


def _pearson(a: list[float], b: list[float]) -> float:
    """Pearson 相关系数（两序列等长；长度 < 2 返回 0——由调用方过滤）。"""
    n = len(a)
    if n < 2:
        return 0.0
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=False))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / (va * vb) ** 0.5


def _daily_returns(closes: list[float]) -> list[float]:
    """日收益率序列（pct 形式）：closes[i]/closes[i-1] - 1。"""
    out = []
    prev = None
    for c in closes:
        if prev is not None and prev > 0:
            out.append(c / prev - 1.0)
        prev = c
    return out


def correlation_matrix(
    closes_by_symbol: dict[str, list[float]],
    window: int = 60,
) -> dict[tuple[str, str], float | None]:
    """按日期对齐后计算组合内标的间的 Pearson 相关系数（近 window 根 K 线）。

    输入 {symbol: closes 序列}（旧→新，截取最近 window 根）。
    输出 {(sym_a, sym_b): r}（a<b 排序，避免重复对）；某标的历史 < MIN_SAMPLES
    或收益序列无效 → 该标的与所有其它标的的 r = None（数据不足诚实标注，
    不得用 0 冒充）。
    """
    if not closes_by_symbol or len(closes_by_symbol) < 2:
        return {}

    # 截取最近 window 根（closes 旧→新）
    trimmed = {}
    insufficient = set()
    for sym, closes in closes_by_symbol.items():
        closes = list(closes)
        if len(closes) < MIN_SAMPLES:
            insufficient.add(sym)
            continue
        trimmed[sym] = _daily_returns(closes[-window:])

    result: dict[tuple[str, str], float | None] = {}
    symbols = sorted(trimmed.keys())
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            ra, rb = trimmed[a], trimmed[b]
            n = min(len(ra), len(rb))
            if n < MIN_SAMPLES:
                result[(a, b)] = None
                continue
            result[(a, b)] = round(_pearson(ra[-n:], rb[-n:]), 4)
    # 数据不足标的 → 与所有其它标的标 None（诚实性）
    for sym in insufficient:
        for other in closes_by_symbol:
            if sym == other:
                continue
            key: tuple[str, str] = (sym, other) if sym <= other else (other, sym)
            result[key] = None
    return result


def high_correlation_pairs(
    matrix: dict[tuple[str, str], float | None],
    threshold: float = 0.85,
) -> list[tuple[float, str, str]]:
    """高相关对清单 [(r, sym_a, sym_b)]（r > threshold，降序）。"""
    out = []
    for (a, b), r in matrix.items():
        if r is not None and r > threshold:
            out.append((r, a, b))
    out.sort(key=lambda x: -x[0])
    return out


def avg_correlation(
    matrix: dict[tuple[str, str], float | None],
    symbols: list[str],
    weights: dict[str, float] | None = None,
) -> float | None:
    """组合加权平均相关（权重作参；无权重时等权平均）。

    仅统计 matrix 中 r 非 None 的对；无有效对返回 None（数据不足，不编造）。
    """
    valid = []
    symbols_set = set(symbols)
    for (a, b), r in matrix.items():
        if r is None or a not in symbols_set or b not in symbols_set:
            continue
        valid.append(r)
    if not valid:
        return None
    if weights:
        # 加权：w_a × w_b 作对权重（归一化）
        _total_w = sum(weights.get(s, 0.0) for s in symbols)
        if _total_w <= 0:
            return round(sum(valid) / len(valid), 4)
        num = 0.0
        den = 0.0
        for (a, b), r in matrix.items():
            if r is None or a not in symbols_set or b not in symbols_set:
                continue
            w = (weights.get(a, 0.0) / _total_w) * (weights.get(b, 0.0) / _total_w)
            num += w * r
            den += w
        return round(num / den, 4) if den > 0 else None
    return round(sum(valid) / len(valid), 4)


def median_correlation_for(
    matrix: dict[tuple[str, str], float | None],
    symbol: str,
    others: list[str],
) -> float | None:
    """该标的与组合其它标的中位数 r（rationale「低相关性」条件化用）。

    无有效对返回 None（矩阵不可用/数据不足——调用方按「不使用低相关措辞」处理）。
    """
    vals = []
    for (a, b), r in matrix.items():
        if r is None:
            continue
        if a == symbol and b in others:
            vals.append(r)
        elif b == symbol and a in others:
            vals.append(r)
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    if n % 2 == 1:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2
