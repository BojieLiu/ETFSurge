"""round59 R01 — index technical pipeline (MA/BOLL/RSI/KDJ + support/resistance levels).

Why this module exists
----------------------
The AI advisor could not answer 「这轮A股下跌的支撑位会是怎么样的？」 because its
prompt carried zero K-line data: no MA, no Bollinger, no prior low, no volume.
The data was not missing — it was never wired in.

A1 decision (2026-09-30, probe-measured, not theoretical)
--------------------------------------------------------
Index daily bars go through ``fetch_history(sym, "index", "daily")`` ->
:func:`fetch_index_history`, and are cached under a **namespaced key**
``idx:<symbol>`` in ``_index_tech_cache``.

The existing K-line cache cannot be reused. ``refresh_kline`` fetches with
``asset_type="A"`` (``hub/_kline.py:308-310``), and only ``asset_type="index"``
routes to ``fetch_index_history`` (``fetchers/china_market.py:1615``). In the
A-share path ``000001`` resolves to Ping An Bank (000001.SZ) — while ``000001``
is *also* the Shanghai Composite's code (``_SH_INDEXES``,
``fetchers/china_market.py:491``). One probe run returned ``close=11.57`` with
stock-like volume for a symbol the prompt was about to label 「上证指数」, whose
real level that day was 3842. Sharing the cache key would have shipped silent
wrong data that looks perfectly normal. Namespacing removes the whole collision
class instead of patching one code.

``399006`` (ChiNext) is deliberately absent: ``fetch_index_history`` hardcodes an
``sh`` prefix (``:1526``), so Shenzhen indices are unreachable via the index path.
The design doc marked 399006 optional; the prefix bug needs its own round.

Request-path contract (R01 hard constraint)
-------------------------------------------
``get_index_technical`` / ``get_index_support_levels`` are **cache-only**: they
never fetch, never compute, never touch the event loop with real work. On a miss
or an expired entry they return empty (the prompt then omits the section, per
``api-contracts/analysis/llm-report-chat.md`` §5.2.2) and schedule a background
refresh, so the SSE first byte never waits. A cold ``refresh_kline`` measured
42-75s (round28 §14.4) — that cost must never land on a user's question.

All heavy work (fetch + indicators) happens in :meth:`refresh_index_technical`,
which stores a fully derived snapshot so reads are plain dict lookups.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.engine.support_levels import compute_support_levels

logger = logging.getLogger(__name__)

# Canonical index display names live in ``app/services/market_service.py``
# ``_GLOBAL_INDEX_DEFS``; kept local (2 entries) to avoid pulling that module in
# at hub import time. Codes must stay in sync with that table.
_INDEX_NAMES = {
    "000001": "上证指数",
    "000300": "沪深300",
}
DEFAULT_INDEX_TECH_SYMBOLS: tuple[str, ...] = ("000001", "000300")

# Daily bars only change once per trading day. Mirrors ``_kline.py``'s
# ``_KLINE_CACHE_TTL`` (24h) — long enough to keep reads free, short enough that
# a stale snapshot never survives a session.
_INDEX_TECH_TTL = 86400.0
# Cap retained bars. The engine only needs ``SupportCfg.lookback`` (120); keeping
# a few multiples leaves room for MA60 + structural windows without unbounded
# memory. Probe measured 8736 rows for 000001 over 1990-2026.
_INDEX_TECH_MAX_BARS = 500
# Same order of magnitude as ``_kline.py``'s per-symbol fetch timeout.
_INDEX_TECH_FETCH_TIMEOUT = 20.0

# ``fetch_index_history`` returns Chinese column names (日期/开盘/最高/最低/收盘/
# 成交量); the stock/K-line path returns English ones. Accept both so a future
# upstream normalization change cannot silently blank the section.
_BAR_KEY_ALIASES = {
    "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
    "收盘": "close", "成交量": "volume",
    "date": "date", "open": "open", "high": "high", "low": "low",
    "close": "close", "volume": "volume",
}


def _normalize_bars(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Chinese- or English-keyed K-line rows -> English-keyed, numeric, ascending.

    Rows that cannot yield a positive high/low/close are dropped rather than
    coerced to 0 — a 0 close would flow into the MA/BOLL math and surface as a
    real-looking level. Losing a malformed row is honest; inventing one is not.
    """
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        bar: dict[str, Any] = {}
        for key, value in r.items():
            canonical = _BAR_KEY_ALIASES.get(str(key).strip())
            if canonical is None or canonical in bar:
                continue
            if canonical == "date":
                bar["date"] = str(value or "")
            else:
                try:
                    bar[canonical] = float(value)
                except (TypeError, ValueError):
                    bar[canonical] = None
        try:
            if not bar.get("date"):
                continue
            if any(
                not isinstance(bar.get(k), (int, float)) or bar[k] <= 0
                for k in ("high", "low", "close")
            ):
                continue
        except (TypeError, ValueError):
            continue
        out.append(bar)
    out.sort(key=lambda b: b["date"])
    return out


def _volume_ratio(bars: list[dict[str, Any]], short: int = 5, long: int = 20) -> float | None:
    """近 short 日均量 / 近 long 日均量。缺失或样本不足时 None（整层由调用方省略）。"""
    vols = [
        b["volume"] for b in bars
        if isinstance(b.get("volume"), (int, float)) and b["volume"] > 0
    ]
    if len(vols) < long:
        return None
    mean_long = sum(vols[-long:]) / long
    if mean_long <= 0:
        return None
    return round((sum(vols[-short:]) / short) / mean_long, 3)


def _rsi_kdj(bars: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """RSI / KDJ-J via the existing indicator module. (None, None) on any failure.

    MA/Bollinger deliberately do NOT come from here: the engine is their single
    source of truth, and a second implementation would drift from it.
    """
    try:
        import pandas as pd

        from app.analysis.indicators import compute_kdj, compute_rsi

        close = pd.Series([float(b["close"]) for b in bars])
        high = pd.Series([float(b["high"]) for b in bars])
        low = pd.Series([float(b["low"]) for b in bars])
        return round(float(compute_rsi(close)), 2), round(float(compute_kdj(high, low, close)["j"]), 2)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("[index_technical] rsi/kdj unavailable: %s", e)
        return None, None


def build_index_snapshot(
    symbol: str, bars: list[dict[str, Any]], data_source: str
) -> dict[str, Any]:
    """Derived per-index snapshot: indicator caliber + engine support levels.

    ``bars`` must be ascending. Returns ``{}`` when there is nothing usable, so
    callers can treat "no data" and "broken data" identically (omit the section).
    """
    bars = _normalize_bars(bars)
    if not bars:
        return {}
    bars = bars[-_INDEX_TECH_MAX_BARS:]

    levels = compute_support_levels(bars)
    indicators = levels.get("indicators") or {}
    rsi, kdj_j = _rsi_kdj(bars[-120:])

    return {
        "symbol": symbol,
        "name": _INDEX_NAMES.get(symbol, symbol),
        "as_of": levels.get("as_of"),
        "data_source": data_source,
        "close": levels.get("price_now"),
        "ma5": indicators.get("ma5"),
        "ma10": indicators.get("ma10"),
        "ma20": indicators.get("ma20"),
        "ma60": indicators.get("ma60"),
        "boll_upper": indicators.get("boll_upper"),
        "boll_mid": indicators.get("boll_mid"),
        "boll_lower": indicators.get("boll_lower"),
        "rsi": rsi,
        "kdj_j": kdj_j,
        "volume_ratio_5_20": _volume_ratio(bars),
        "support_levels": levels,
    }


class TechnicalMixin:
    """Index technical-analysis slots for the LLM context (round59 R01)."""

    # Declared here (not only in MarketDataHub.__init__) so the types are part of
    # the mixin's contract: `asyncio.create_task` is typed `Task | None`, and
    # without an explicit annotation mypy narrows the attribute to `Task[None]`
    # and then rejects the plain assignment in the hub's __init__.
    _index_tech_cache: dict[str, dict[str, Any]]
    _index_tech_refresh_task: "asyncio.Task[Any] | None"

    # ---------------------------------------------------------------- reads

    def get_index_technical(
        self, symbols: tuple[str, ...] | list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Cache-only read of the ``index_technical`` slot. Never fetches.

        Returns ``[]`` on a miss or an expired entry, and schedules a background
        refresh so the *next* question has data. Callers render an empty slot as
        "omit the section" — never as a fabricated level.
        """
        syms = tuple(symbols) if symbols else DEFAULT_INDEX_TECH_SYMBOLS
        cache = getattr(self, "_index_tech_cache", None)
        if not isinstance(cache, dict):
            self._schedule_index_tech_refresh(syms)
            return []
        now = time.time()
        out: list[dict[str, Any]] = []
        stale: list[str] = []
        for sym in syms:
            entry = cache.get(sym)
            if not isinstance(entry, dict) or not entry.get("snapshot"):
                stale.append(sym)
                continue
            if (now - float(entry.get("ts") or 0.0)) >= _INDEX_TECH_TTL:
                # Expired -> degrade honestly (doc R01) rather than pass a
                # day-old snapshot off as current. The snapshot's real `as_of`
                # would make it usable, but the approved plan says degrade.
                stale.append(sym)
                continue
            out.append(entry["snapshot"])
        if stale:
            self._schedule_index_tech_refresh(stale)
        return out

    def get_index_support_levels(
        self, symbols: tuple[str, ...] | list[str] | None = None
    ) -> dict[str, Any]:
        """Cache-only read of per-index support/resistance levels.

        Shape mirrors ``app.engine.support_levels.compute_support_levels`` output
        plus the index identity, keyed by symbol.
        """
        out: dict[str, Any] = {}
        for snap in self.get_index_technical(symbols):
            levels = snap.get("support_levels")
            if isinstance(levels, dict):
                out[snap["symbol"]] = {
                    "symbol": snap["symbol"],
                    "name": snap.get("name"),
                    "as_of": snap.get("as_of"),
                    **levels,
                }
        return out

    # -------------------------------------------------------------- refresh

    def _schedule_index_tech_refresh(self, symbols: list[str] | tuple[str, ...]) -> None:
        """Fire-and-forget single-flight refresh; never blocks the caller."""
        if not symbols:
            return
        existing = getattr(self, "_index_tech_refresh_task", None)
        if existing is not None and not existing.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (sync caller / threadpool) — a later async read will
            # schedule it. Silently skipping beats crashing a request.
            return
        task = loop.create_task(self.refresh_index_technical(list(symbols)))
        self._index_tech_refresh_task = task
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def refresh_index_technical(self, symbols: list[str] | None = None) -> None:
        """The only network entry for index technical data.

        Fetches index daily bars, derives the snapshot, writes the cache. Safe to
        call concurrently with reads: readers either see the old entry or nothing.
        """
        syms = list(symbols) if symbols else list(DEFAULT_INDEX_TECH_SYMBOLS)
        from app.core import async_utils
        from app.fetchers import china_market

        for sym in syms:
            try:
                rows = await async_utils.run_sync_long(
                    china_market.fetch_history, sym, "index", "daily",
                    timeout=_INDEX_TECH_FETCH_TIMEOUT,
                )
            except Exception as e:
                logger.warning("[index_technical] fetch_history(%s, index) failed: %s", sym, e)
                continue
            bars = _normalize_bars(rows)
            if not bars:
                logger.warning("[index_technical] %s: index bars empty/unschema'd", sym)
                continue
            snapshot = build_index_snapshot(
                sym, bars, data_source="akshare stock_zh_index_daily"
            )
            if not snapshot:
                continue
            cache = getattr(self, "_index_tech_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._index_tech_cache = cache
            cache[sym] = {"ts": time.time(), "snapshot": snapshot}
            logger.info(
                "[index_technical] %s(%s) as_of=%s close=%s ma20=%s fib=%s",
                snapshot["symbol"], snapshot["name"], snapshot.get("as_of"),
                snapshot.get("close"), snapshot.get("ma20"),
                (snapshot.get("support_levels") or {}).get("fib", {}).get("fib_unavailable_reason"),
            )
