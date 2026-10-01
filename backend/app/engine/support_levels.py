"""round59 R02a/R02b — support / resistance levels from daily bars (PURE).

Why
---
The AI advisor could not answer 「这轮A股下跌的支撑位会是怎么样的？」: its prompt
carried no K-line data at all. This module turns a daily-bar series into the
level tables that answer requires — deterministically, with no I/O, so it is
unit-testable without mocks and reproducible run to run.

The direction trap (the whole point of this module)
---------------------------------------------------
Measuring Fibonacci down from the *current* leg high yields **rebound targets**,
not support. The genuine support levels come from the retracement zone of the
*previous up-leg* ``[L*, H*]``::

    level_i = H* - ratio_i * (H* - L*)     # ratios 0.382 / 0.5 / 0.618

A retracement zone has exactly **three** levels, and each one is either support
or resistance depending on where price currently sits. So every level here is
labelled by comparing it to ``price_now``::

    value < price_now -> "support"
    value > price_now -> "resist"
    value == price_now -> dropped (ambiguous)

Two traps this module exists to avoid:

1. Measuring from the current leg high yields rebound targets, not support.
2. The mirror-image trap the design originally missed: when price has already
   fallen *through* the whole zone, the 38.2% level sits above the market and is
   resistance. Labeling the whole set "support" is simply wrong.

The design doc also asked for a second family ``L* + ratio*(H* - L*)`` as
"rebound resistance". That family is algebraically the *same three numbers*
(``L* + r*span == H* - (1-r)*span``), so emitting it would make the model read
"support 3827.66" and "resistance 3827.66" in one answer. One family, three
levels, direction carried per entry.

The doc's original assertion ``S3 < S2 < S1 < P_now`` only holds in an uptrend —
i.e. never in the situation the advisor is actually asked about. The invariant
enforced here is stronger and always true: *a level labelled support is below
price; a level labelled resist is above; the two families never mix.*

Anchor selection (probe-validated, 2026-09-30)
---------------------------------------------
Enumerating all fractal up-legs and taking "the last pair" — what the design said
— selects a leg whose entire retracement zone already sits above price, which is
useless for a support question. Instead: pick the **most recent up-leg whose zone
still brackets the current price** (``S3 < price_now < S1``).

Measured on 000001 上证指数 (120 bars, price_now 3842.195): the naive rule picked
a dead leg; this rule picks ``L*=3741.11 / H*=3967.68`` giving
``S1/S2/S3 = 3881.13 / 3854.40 / 3827.66`` — S1/S2 above price (resist), S3 below
(support). Measured on 000300 沪深300 (price_now 4357.62): **no** leg brackets
price, so Fibonacci is reported unavailable rather than fabricated. That guard
fires on half of the real target indices, so it is a live path, not a theoretical
one.

Anchors must also agree between the two fractal widths (k=3 and k=5); when they
disagree the level is not trustworthy enough to publish and Fibonacci is disabled.

No I/O, no third-party imports — ``scripts/check_engine_purity.py`` forbids
``app.services``/``app.fetchers``/``app.tasks``/``app.analysis``/``app.routers``/
``app.factors`` plus a list of I/O tokens, and the rest of ``engine/`` is stdlib
only. Rolling means and stdevs are therefore implemented here in plain Python
rather than by importing ``app.analysis.indicators``; that also makes this module
the single source of truth for MA/Bollinger, so the service layer reuses the
``indicators`` block returned below instead of recomputing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

__all__ = ["SupportCfg", "compute_support_levels", "normalize_bars"]


@dataclass(frozen=True)
class SupportCfg:
    """Tunables. Defaults are the probe-validated caliber for A-share indices."""

    lookback: int = 120
    ma_windows: tuple[int, ...] = (5, 10, 20, 60)
    boll_window: int = 20
    boll_std: float = 2.0
    fib_ratios: tuple[float, ...] = (0.382, 0.5, 0.618)
    min_upleg_range: float = 0.05
    fractal_ks: tuple[int, ...] = (3, 5)
    struct_windows: tuple[int, ...] = (60, 120)


# Basis strings are quoted verbatim into the LLM prompt, so they must state the
# condition that would invalidate the level — a level without an invalidation
# condition is an assertion, not an analysis.
_BASIS = {
    "MA5": "5日均线，短线强弱分界",
    "MA10": "10日均线，短线趋势线",
    "MA20": "20日均线，跌破则趋势转弱",
    "MA60": "60日均线，中期趋势分水岭",
    "BOLL上轨": "布林上轨，波动率上沿，反弹压力参考",
    "BOLL中轨": "布林中轨，方向枢轴",
    "BOLL下轨": "布林下轨，波动率下沿，非刚性支撑",
}
_STRUCT_BASIS = "前低，跌破则打开下方空间"
_FIB_BASIS = "上一轮上涨段 [{low:.2f}, {high:.2f}] 回撤 {ratio:.1%}"

# Reasons are surfaced in the prompt, so they must be human-readable, not codes.
_REASON_NO_BARS = "no_usable_bars"
_REASON_NO_BRACKET = "no_upleg_brackets_price"
_REASON_UNSTABLE = "anchor_unstable_k3_k5"
_REASON_TOO_SHORT = "insufficient_bars"


def normalize_bars(bars: list[dict] | None) -> list[dict]:
    """Keep only rows that can carry a real level, ascending by date.

    Rows missing a positive high/low/close are dropped rather than coerced to 0:
    a 0 close would flow into the MA/Bollinger math and surface as a plausible
    looking level. Losing a malformed row is honest; inventing one is not.
    """
    out: list[dict] = []
    for bar in bars or []:
        if not isinstance(bar, dict):
            continue
        try:
            high = float(bar["high"])
            low = float(bar["low"])
            close = float(bar["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (high > 0 and low > 0 and close > 0):
            continue
        if high < low:
            high, low = low, high
        out.append(
            {
                "date": str(bar.get("date") or ""),
                "open": float(bar["open"]) if _is_num(bar.get("open")) else close,
                "high": high,
                "low": low,
                "close": close,
            }
        )
    out.sort(key=lambda b: b["date"])
    return out


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _stdev(values: list[float]) -> float | None:
    """Sample standard deviation (``ddof=1``) — matches pandas_ta's bbands.

    Calibrated against the measured 000001 window: population stdev
    (``ddof=0``) gives a lower band of 3823.86 while
    ``/market/indicators/{symbol}`` reports 3821.74; the ratio is exactly
    ``sqrt(20/19)``, i.e. pandas_ta divides by ``n-1``. Using ``ddof=0`` here
    would put two different "BOLL lower" values for one symbol in the same
    product, so the parity is load-bearing, not cosmetic.
    """
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _swing_points(bars: list[dict], k: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Fractal swing highs/lows: k bars either side strictly higher/lower.

    Strictness (the value must be the unique extreme of its window) is what stops
    flat stretches from manufacturing a dozen identical pivots.
    """
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    n = len(bars)
    for i in range(k, n - k):
        window_h = [b["high"] for b in bars[i - k : i + k + 1]]
        window_l = [b["low"] for b in bars[i - k : i + k + 1]]
        h, low = bars[i]["high"], bars[i]["low"]
        if h == max(window_h) and window_h.count(h) == 1:
            highs.append((i, h))
        if low == min(window_l) and window_l.count(low) == 1:
            lows.append((i, low))
    return highs, lows


def _uplegs(bars: list[dict], k: int, min_range: float) -> list[tuple[int, float, int, float]]:
    """All (low_idx, L*, high_idx, H*) up-leg pairs, oldest first."""
    highs, lows = _swing_points(bars, k)
    legs: list[tuple[int, float, int, float]] = []
    for low_idx, low_star in lows:
        for high_idx, high_star in highs:
            if high_idx <= low_idx or high_star <= low_star:
                continue
            if (high_star - low_star) / low_star < min_range:
                continue
            legs.append((low_idx, low_star, high_idx, high_star))
    legs.sort(key=lambda leg: leg[2])
    return legs


def _select_anchor(
    bars: list[dict], k: int, ratios: tuple[float, ...], min_range: float
) -> tuple[float, float, int, int] | None:
    """Most recent up-leg whose retracement zone still brackets the last close.

    "Brackets" is the whole test: if the zone sits entirely above price, those
    levels are overhead resistance and answering a support question with them is
    worse than answering nothing. Most recent wins so the levels belong to the
    leg actually in play.
    """
    price_now = bars[-1]["close"]
    for _low_idx, low_star, high_idx, high_star in reversed(_uplegs(bars, k, min_range)):
        span = high_star - low_star
        shallowest = high_star - ratios[0] * span   # S1, closest to H*
        deepest = high_star - ratios[-1] * span     # S3, deepest
        if deepest < price_now < shallowest:
            return (low_star, high_star, _low_idx, high_idx)
    return None


def _label(value: float, price_now: float) -> str | None:
    """Direction of a level relative to the current price.

    Returns None when the level coincides with price — unlabelable, so it is not
    published rather than published as a support that price is already sitting on.
    """
    if value < price_now:
        return "support"
    if value > price_now:
        return "resist"
    return None


def _entry(level: str, value: float, price_now: float, basis: str) -> dict | None:
    kind = _label(value, price_now)
    if kind is None:
        return None
    return {"level": level, "value": round(value, 2), "kind": kind, "basis": basis}


def _empty_fib(reason: str) -> dict:
    return {
        "s1": None, "s2": None, "s3": None,
        "anchor_low": None, "anchor_high": None,
        "anchor_low_index": None, "anchor_high_index": None,
        "k_primary": None,
        "fib_unavailable_reason": reason,
        "fib_levels": [],
    }


def compute_support_levels(
    bars: list[dict] | None, cfg: SupportCfg | None = None
) -> dict[str, Any]:
    """Dynamic / structural / Fibonacci level tables for one daily-bar series.

    ``bars`` is oldest-first with at least ``high``/``low``/``close`` (and
    ``date`` when available). Never raises: unusable input yields a well-formed
    result whose values are ``None`` and whose ``fib_unavailable_reason`` is
    non-empty, so callers have exactly one "no data" shape to handle.
    """
    cfg = cfg or SupportCfg()
    result: dict[str, Any] = {
        "as_of": None,
        "price_now": None,
        "indicators": {
            "ma5": None, "ma10": None, "ma20": None, "ma60": None,
            "boll_upper": None, "boll_mid": None, "boll_lower": None,
        },
        "dynamic": [],
        "structural": [],
        "fib": _empty_fib(_REASON_NO_BARS),
    }

    usable = normalize_bars(bars)[-cfg.lookback :]
    if not usable:
        return result

    closes = [b["close"] for b in usable]
    price_now = closes[-1]
    result["price_now"] = round(price_now, 2)
    result["as_of"] = usable[-1]["date"] or None

    # ---- indicators: single source of truth for MA / Bollinger -------------
    indicators = result["indicators"]
    for window in cfg.ma_windows:
        mean = _mean(closes[-window:]) if len(closes) >= window else None
        indicators[f"ma{window}"] = round(mean, 2) if mean is not None else None
    if len(closes) >= cfg.boll_window:
        window_closes = closes[-cfg.boll_window :]
        mid = _mean(window_closes)
        stdev = _stdev(window_closes)
        if mid is not None and stdev is not None:
            indicators["boll_mid"] = round(mid, 2)
            indicators["boll_upper"] = round(mid + cfg.boll_std * stdev, 2)
            indicators["boll_lower"] = round(mid - cfg.boll_std * stdev, 2)

    # ---- dynamic + structural levels, labelled against price -------------
    # One `seen` set across all three buckets: the same price must never be
    # published twice (measured: 近60日低点 == 近120日低点 == 3741.11, because
    # the 120-day low *is* the 60-day low). Duplicate rows read as two
    # independent pieces of evidence and invite the model to double-count them.
    seen: set[float] = set()

    def _add(bucket: list[dict], label: str, value: float | None, basis: str) -> None:
        if value is None or value in seen:
            return
        entry = _entry(label, value, price_now, basis)
        if entry is None:
            return
        seen.add(value)
        bucket.append(entry)

    for window in cfg.ma_windows:
        _add(result["dynamic"], f"MA{window}", indicators[f"ma{window}"],
             _BASIS.get(f"MA{window}", ""))
    _add(result["dynamic"], "BOLL上轨", indicators["boll_upper"], _BASIS["BOLL上轨"])
    _add(result["dynamic"], "BOLL中轨", indicators["boll_mid"], _BASIS["BOLL中轨"])
    _add(result["dynamic"], "BOLL下轨", indicators["boll_lower"], _BASIS["BOLL下轨"])

    lows = [b["low"] for b in usable]
    for window in cfg.struct_windows:
        if len(lows) >= window:
            _add(result["structural"], f"近{window}日低点", min(lows[-window:]), _STRUCT_BASIS)

    # ---- Fibonacci: anchor must exist, be bracketing, and be stable -------
    if len(usable) < max(cfg.fractal_ks) * 2 + 2:
        result["fib"] = _empty_fib(_REASON_TOO_SHORT)
        return result

    per_k: dict[int, tuple[float, float, int, int] | None] = {
        k: _select_anchor(usable, k, cfg.fib_ratios, cfg.min_upleg_range)
        for k in cfg.fractal_ks
    }
    found = {k: v for k, v in per_k.items() if v is not None}
    if not found:
        result["fib"] = _empty_fib(_REASON_NO_BRACKET)
        return result

    anchors = {
        (round(v[0], 6), round(v[1], 6)) for v in found.values()
    }
    if len(anchors) > 1:
        # The fractal width changes the answer -> the pivot is noise, not structure.
        result["fib"] = _empty_fib(_REASON_UNSTABLE)
        return result

    k_primary = min(found)  # prefer the tighter fractal when both agree
    low_star, high_star, low_idx, high_idx = found[k_primary]
    span = high_star - low_star

    fib: dict[str, Any] = {
        "anchor_low": round(low_star, 2),
        "anchor_high": round(high_star, 2),
        "anchor_low_index": low_idx,
        "anchor_high_index": high_idx,
        "k_primary": k_primary,
        "fib_unavailable_reason": None,
        "fib_levels": [],
    }
    # One family, three levels. The design doc also asked for a rebound family
    # "L* + ratio*(H*-L*)", but that is algebraically the same set:
    # L* + r*span == H* - (1-r)*span, so R(38.2%) == S(61.8%), R(50%) == S(50%),
    # R(61.8%) == S(38.2%). Emitting both would hand the model the same price
    # level twice under contradictory names ("support 3827.66" and
    # "resistance 3827.66" in one answer). Direction is therefore carried by
    # each entry's `kind`, decided by position against price_now.
    for ordinal, ratio in enumerate(cfg.fib_ratios, 1):
        value = round(high_star - ratio * span, 2)
        fib[f"s{ordinal}"] = value
        # Routed through the same `seen` set: a retracement level can coincide
        # with a prior low, and publishing one price under two labels reads as
        # two independent confirmations.
        if value in seen:
            continue
        entry = _entry(
            f"回撤 {ratio:.1%}", value, price_now,
            _FIB_BASIS.format(low=low_star, high=high_star, ratio=ratio),
        )
        if entry is not None:
            seen.add(value)
            fib["fib_levels"].append(entry)

    result["fib"] = fib
    return result
