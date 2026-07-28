"""
两融余额 (Margin Balance) fetcher.

Fetches total margin-trading balance (融资融券余额) from:
  1. 深交所 (SZSE) — POST API
  2. 上交所 (SSE) — JSONP GET API (fallback)

Both are public and require no authentication.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any

from ..core.async_utils import run_in_thread

logger = logging.getLogger(__name__)

_TIMEOUT = 8

# ── SZSE ───────────────────────────────────────────────────────────

_SZSE_URL = "https://www.szse.cn/api/report/ezfintrade/getFundCcl"
_SZSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.szse.cn/",
    "Content-Type": "application/json",
}


def _fetch_szse() -> float | None:
    """Fetch margin balance from SZSE via POST.

    Returns total 融资余额 (margin debit balance) in yuan, or None.
    """
    body = json.dumps({"scDate": ""}).encode("utf-8")
    req = urllib.request.Request(_SZSE_URL, data=body, headers=_SZSE_HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            data: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        logger.warning("[margin_fetcher] SZSE request failed: %s", exc)
        return None

    # Expected structure: {"data": [{"scDate": "...", "rzye": "123456789012.34", ...}]}
    try:
        rows = data.get("data", [])
        if not rows:
            logger.warning("[margin_fetcher] SZSE: empty data array")
            return None
        row = rows[0]
        val_str = row.get("rzye")  # 融资余额
        if not val_str:
            logger.warning("[margin_fetcher] SZSE: missing rzye field")
            return None
        return float(val_str)
    except (AttributeError, IndexError, ValueError, TypeError) as exc:
        logger.warning("[margin_fetcher] SZSE parse error: %s", exc)
        return None


# ── SSE ────────────────────────────────────────────────────────────

_SSE_URL = "https://query.sse.com.cn/security/stock/queryMarginBalance.do"
_SSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.sse.com.cn/",
}


def _fetch_sse() -> float | None:
    """Fetch margin balance from SSE via JSONP GET.

    Returns total 融资余额 (margin debit balance) in yuan, or None.
    """
    url = f"{_SSE_URL}?jsonCallBack=jsonp&_={int(time.time() * 1000)}"
    req = urllib.request.Request(url, headers=_SSE_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        logger.warning("[margin_fetcher] SSE request failed: %s", exc)
        return None

    # Response is JSONP: jsonp({...})
    # Strip the callback wrapper to get plain JSON
    try:
        text = raw.strip()
        if text.startswith("jsonp(") and text.endswith(")"):
            text = text[len("jsonp(") : -1]
        data: dict[str, Any] = json.loads(text)
    except Exception as exc:
        logger.warning("[margin_fetcher] SSE JSONP parse error: %s", exc)
        return None

    # Expected structure: {"total": ..., "page": ..., "result": [...]}
    # Each result row has "rzye" (融资余额)
    try:
        rows = data.get("result", [])
        if not rows:
            logger.warning("[margin_fetcher] SSE: empty result array")
            return None
        row = rows[0]
        val_str = row.get("rzye")
        if not val_str:
            logger.warning("[margin_fetcher] SSE: missing rzye field")
            return None
        return float(val_str)
    except (AttributeError, IndexError, ValueError, TypeError) as exc:
        logger.warning("[margin_fetcher] SSE parse error: %s", exc)
        return None


# ── Public API ─────────────────────────────────────────────────────


def fetch_margin_balance() -> float | None:
    """Fetch total margin balance (两融余额) from SZSE + SSE.

    Tries SZSE first, then SSE as fallback. Returns total 融资余额
    (margin debit balance) in yuan, or ``None`` if both sources fail.

    All calls run through ``run_in_thread`` with 8s timeout.
    """
    result = run_in_thread(_fetch_szse, timeout=_TIMEOUT, executor="long")
    if result is not None:
        return result

    logger.info("[margin_fetcher] SZSE failed, trying SSE fallback")
    return run_in_thread(_fetch_sse, timeout=_TIMEOUT, executor="long")
