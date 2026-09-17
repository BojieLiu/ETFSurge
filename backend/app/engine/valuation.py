"""
ETF Surge — Valuation helpers (PE-only v1).

Pure functions only — no I/O, no database, no HTTP.
契约: api-contracts/analysis/advice-valuation.md §5-§6.
D1 实证 (2026-09-17): 指数源仅 PE1/PE2+股息率(无 PB,近 20 日);
板块源仅静态 PE 三口径(无 PB/ROE/股息)——故 v1 缺基本面一律待验.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right


def compute_pe_percentile(
    current: float | None,
    history: list[float | None] | None,
) -> float | None:
    """当前值在历史序列中的经验分位 (0.0..1.0).

    线性插值秩 (numpy 默认口径): 现值 OHLC 恰为历史最小时 0.0,
    最大时 1.0, 中位数处 0.5; 未出现过的值按相邻两档数值插值.
    空历史/全 None/现值 None → None (调用方标待验,不编数).
    """
    if current is None or not history:
        return None
    vals = sorted(h for h in history if h is not None)
    if not vals:
        return None
    n = len(vals)
    if n == 1:
        if current < vals[0]:
            return 0.0
        if current > vals[0]:
            return 1.0
        return 0.5
    if current <= vals[0]:
        return 0.0
    if current >= vals[-1]:
        return 1.0
    lo = bisect_left(vals, current)
    hi = bisect_right(vals, current)
    if hi > lo:
        # 现值在历史中出现过(含重复):取秩中点
        rank = (lo + hi + 1) / 2.0
    else:
        # 未出现过:按相邻两档数值线性插值
        low, high = vals[lo - 1], vals[lo]
        span = high - low
        frac = (current - low) / span if span else 0.5
        rank = lo + frac
    return (rank - 1) / (n - 1)


def classify_valuation(
    pe_pct: float | None,
    pb_pct: float | None = None,
    roe: float | None = None,
) -> str:
    """PE-only v1 结论分级: 错杀候选 / 陷阱候选 / 合理 / 待验.

    v1 无 ROE/PB 源时 (roe is None) 一律待验——禁止 sess-1ef0 式
    “无支撑常识推断”. 有 ROE 时: 低分位+ROE 稳→错杀候选;
    高分位+ROE 为负→陷阱候选; 低分位+ROE 为负→陷阱候选;
    其余→合理; 低分位+ROE 平庸→待验.
    """
    _ = pb_pct  # v1 未使用 PB(源缺失),签名预留
    if pe_pct is None or roe is None:
        return "待验"
    if pe_pct <= 0.3:
        if roe >= 0.10:
            return "错杀候选"
        if roe < 0:
            return "陷阱候选"
        return "待验"
    if pe_pct >= 0.7:
        if roe < 0:
            return "陷阱候选"
        return "合理"
    return "合理"
