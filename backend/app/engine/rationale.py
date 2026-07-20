"""
ETF Surge — Rationale builder.

Generates data-driven Chinese rationale strings explaining why a specific
ETF was selected for a given layer, referencing factor scores.

Pure function — no I/O, no database, no HTTP.
"""

from __future__ import annotations

from typing import Any


def build_rationale(
    symbol: str,
    layer: str,
    factor_scores: dict[str, float],
    regime: str | None = None,
) -> str:
    """
    Build a concise Chinese rationale for selecting an ETF.

    Args:
        symbol:     ETF ticker / symbol code.
        layer:      One of "core", "satellite", "defense".
        factor_scores: Dict with keys like "technical", "momentum",
                       "valuation", "sentiment" (values 0-1 range).
        regime:     Optional market regime label for context.

    Returns:
        A Chinese-language rationale string.
    """
    _ = symbol  # not needed in text, used for future symbol-specific logic
    parts: list[str] = []

    # ── Layer positioning ──
    layer_phrases = {
        "core": "核心层配置",
        "satellite": "卫星层增强",
        "defense": "防御层避险",
    }
    parts.append(layer_phrases.get(layer, "配置"))

    # ── Factor-score driven commentary ──
    tech = factor_scores.get("technical", 0.0)
    mom = factor_scores.get("momentum", 0.0)
    val = factor_scores.get("valuation", 0.0)
    sent = factor_scores.get("sentiment", 0.0)

    if tech >= 0.6:
        parts.append("技术面偏强")
    elif tech <= 0.3:
        parts.append("技术面偏弱")

    if mom >= 0.6:
        parts.append("动量向上")
    elif mom <= 0.3:
        parts.append("动量偏弱")

    if val >= 0.6:
        parts.append("估值有吸引力")
    elif val <= 0.3:
        parts.append("估值偏高")

    if sent >= 0.6:
        parts.append("市场情绪积极")
    elif sent <= 0.3:
        parts.append("市场情绪谨慎")

    # ── Regime context ──
    if regime:
        regime_notes: dict[str, str] = {
            "bull_strong": "，适合顺势加仓",
            "bull_weakening": "，注意控制风险",
            "range_bound": "，适合区间操作",
            "correction": "，建议降低风险敞口",
            "bear": "，以防御为主",
            "defensive_rotate": "，资金转向防御",
            "panic": "，保持谨慎",
        }
        note = regime_notes.get(regime, "")
        if note:
            parts.append(note)

    # ── Build composite score summary ──
    valid_scores = [v for v in (tech, mom, val, sent) if isinstance(v, (int, float))]
    if valid_scores:
        avg = sum(valid_scores) / len(valid_scores)
        if avg >= 0.6:
            parts.append("综合评分偏优")
        elif avg <= 0.3:
            parts.append("综合评分偏弱")
        else:
            parts.append("综合评分中性")

    return "，".join(parts)
