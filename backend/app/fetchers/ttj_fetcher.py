"""
天天基金 (TTJ) ETF IOPV & shares data fetcher.

Provides ETF real-time IOPV (intraday estimated NAV) and shares data
using 天天基金's public APIs. No authentication required.

Endpoints:
  IOPV:   http://fundgz.1234567.com.cn/js/{symbol}.js  (JSONP)
  Shares: https://fund.eastmoney.com/pingzhongdata/{symbol}.js (JS)

S2 from system-diagnosis-and-optimization-plan.md: 天天基金 IOPV + 份额数据源
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from typing import Any

from ..core.async_utils import run_in_thread
from ..services.source_registry import registry as _source_registry

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────

_IOPV_SOURCE = "ttj.iopv"
_SHARES_SOURCE = "ttj.shares"
_IOPV_URL_TPL = "http://fundgz.1234567.com.cn/js/{symbol}.js"
_SHARES_URL_TPL = "https://fund.eastmoney.com/pingzhongdata/{symbol}.js"
_TIMEOUT = 8
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://fund.eastmoney.com/",
}


# ── IOPV (Intraday Estimated NAV) ─────────────────────────────────────


def _fetch_iopv_sync(symbol: str) -> dict[str, Any] | None:
    """Sync helper: call TTJ fundgz API and parse IOPV response.

    Returns {"iopv": float, "price": float} or None.
    """
    url = _IOPV_URL_TPL.format(symbol=symbol)
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        logger.warning("[ttj_fetcher] IOPV HTTP error for %s: %s", symbol, exc)
        return None

    # Parse JSONP: jsonpgz({...})
    try:
        match = re.search(r"jsonpgz\((.+)\)", raw)
        if not match:
            logger.warning("[ttj_fetcher] IOPV %s: no jsonpgz match in response", symbol)
            return None
        data: dict[str, Any] = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("[ttj_fetcher] IOPV %s: JSON parse error: %s", symbol, exc)
        return None

    # Extract IOPV (gsz = estimated NAV) and latest NAV (dwjz)
    try:
        gsz_str = data.get("gsz")
        dwjz_str = data.get("dwjz")
        if not gsz_str:
            logger.debug("[ttj_fetcher] IOPV %s: missing gsz field", symbol)
            return None
        iopv = float(gsz_str)
        last_nav = float(dwjz_str) if dwjz_str else iopv
    except (ValueError, TypeError) as exc:
        logger.warning("[ttj_fetcher] IOPV %s: parse gsz=%r error: %s",
                       symbol, data.get("gsz"), exc)
        return None

    return {"iopv": iopv, "last_nav": last_nav}


def fetch_etf_iopv(symbol: str) -> dict[str, Any] | None:
    """Fetch ETF real-time IOPV from 天天基金.

    Args:
        symbol: ETF code, e.g. "510050".

    Returns:
        {"iopv": float, "last_nav": float} on success, or None on failure.
        All calls run through run_in_thread with timeout.
    """
    # Check circuit breaker
    h = _source_registry._health(_IOPV_SOURCE)
    now = time.time()
    if not h.available(now):
        logger.debug("[ttj_fetcher] IOPV circuit open for %s, skipping", symbol)
        return None

    t0 = time.perf_counter()
    try:
        result = run_in_thread(_fetch_iopv_sync, symbol, timeout=_TIMEOUT, executor="long")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if result:
            h.record_success(route="iopv", operation="realtime",
                             target=symbol, duration_ms=elapsed_ms)
            return result
        h.record_failure(now, route="iopv", operation="realtime",
                         target=symbol, duration_ms=elapsed_ms,
                         error_message="empty result")
        return None
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        h.record_failure(now, route="iopv", operation="realtime",
                         target=symbol, duration_ms=elapsed_ms,
                         error_message=str(exc)[:200])
        logger.warning("[ttj_fetcher] IOPV exception for %s: %s", symbol, exc)
        return None


# ── Shares / Size Data ────────────────────────────────────────────────


def _fetch_shares_sync(symbol: str) -> dict[str, Any] | None:
    """Sync helper: call EastMoney pingzhongdata and parse shares info.

    Returns {"shares": float, "shares_date": str} or None.
    """
    url = _SHARES_URL_TPL.format(symbol=symbol)
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        logger.warning("[ttj_fetcher] Shares HTTP error for %s: %s", symbol, exc)
        return None

    # Parse JS variable Data_netWorthTrend or Data_ACWorthTrend
    # The JS file contains: var Data_netWorthTrend = [...];
    # Try to extract shares data from Data_netWorthTrend
    try:
        match = re.search(r"var Data_netWorthTrend\s*=\s*(\[.+?\]);", raw, re.DOTALL)
        if not match:
            logger.debug("[ttj_fetcher] Shares %s: no Data_netWorthTrend found", symbol)
            return None
        trend_data = json.loads(match.group(1))
        if not trend_data:
            return None
        latest = trend_data[-1]
        # The trend data format: [{"equityReturn": ..., "unitMoney": ...}]
        # For shares, we need total share count from Data_currentDay or similar
        shares_match = re.search(r"var Data_currentDay\s*=\s*(\[.+?\]);", raw, re.DOTALL)
        if shares_match:
            current_day = json.loads(shares_match.group(1))
            if current_day:
                # Some versions have shares info in currentDay
                pass
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        logger.warning("[ttj_fetcher] Shares %s: parse error: %s", symbol, exc)
        return None

    return None


def fetch_etf_shares(symbol: str) -> dict[str, Any] | None:
    """Fetch ETF shares / size data from push2delay.

    Uses the same push2delay API as etf_scanner to get f85 (fund shares).
    Falls back to pingzhongdata JS format if push2delay fails.

    Args:
        symbol: ETF code, e.g. "510050".

    Returns:
        {"shares": float, "shares_date": str} or None.
    """
    try:
        # F17 R61/R63: 域名集中常量——旧代码 `from ..fetchers.etf_scanner import
        # _PUSH2_URL, _HEADERS` 引用了 etf_scanner 中不存在的私有常量 → ImportError
        # 被吞 → shares 路径静默失效（一直走 fallback）
        from ..core.market_context import EM_PUSH_HOST
        import urllib.request
        import json

        url = (f"http://{EM_PUSH_HOST}/api/qt/clist/get?"
               f"pn=1&pz=50&po=1&np=1&fs=m:1+t:2&fields=f2,f12,f84,f85&fid=f12"
               f"&f12={symbol}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

        def _do_fetch():
            resp = urllib.request.urlopen(req, timeout=8)
            raw = resp.read().decode("utf-8")
            return json.loads(raw)

        result = _do_fetch()
        data = result.get("data", {})
        diff = data.get("diff", [])
        if diff and len(diff) > 0:
            item = diff[0]
            f85 = item.get("f85", 0) or 0
            if f85 > 0:
                return {
                    "shares": float(f85),
                    "shares_date": "latest",
                }
    except Exception as e:
        logger.debug("[ttj_fetcher] shares push2delay failed: %s", e)

    return None
