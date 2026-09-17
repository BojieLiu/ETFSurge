# -*- coding: utf-8 -*-
"""Valuation Fetcher — 指数/板块估值取数（L2 P0，PE-only v1）.

D1 实证（2026-09-17 探针）：
- ak.stock_zh_index_value_csindex(symbol): 近 20 个交易日，
  列=日期/指数代码/市盈率1/市盈率2/股息率1/股息率2（无 PB；
  市盈率1/2 口径未定，原样透传不猜）。
- ak.stock_industry_pe_ratio_cninfo(date): 120 行业，
  列=变动日期/行业编码/行业名称/静态PE三口径（无 PB/ROE/股息）。

复用 fundamentals_fetcher 的 R4-26 模式：失败缓存 1h +
akshare 熔断记账；列名 latin1 乱码走 decode_df（探针实证必须调）。
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime
from typing import Any

from ..core.async_utils import run_in_thread
from ..core.logging import get_logger
from ..core.source_registry import registry as _source_registry
from ..services.cache_service import sync_memory_cache
from ..utils.decode import decode_df as _decode_df

logger = get_logger(__name__)

_AKSHARE_SOURCE = "akshare"
_FAIL_TTL = 3600  # 失败缓存 1h（R4-26 模式）


def _fnum(v: Any) -> float | None:
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    return f if f and abs(f) > 0 else None


def _fail_key(scope: str, arg: str) -> str:
    return f"_val_fail:{scope}:{arg}"


def _is_failing(key: str) -> bool:
    try:
        return sync_memory_cache.get(key) is not None
    except Exception:
        return False


def _mark_fail(key: str) -> None:
    try:
        sync_memory_cache.set(key, True, _FAIL_TTL)
    except Exception:
        pass


def fetch_index_valuation_history(symbol: str) -> list[dict]:
    """指数估值历史（近 20 个交易日，中证口径）.

    返回 [{date, pe_1, pe_2, div_1, div_2}]（源顺序，一般最新在前）。
    失败/空 → []（失败记熔断 + 1h 缓存，防反复触发慢源）。
    """
    key = _fail_key("index", symbol)
    if _is_failing(key):
        return []
    _ak_h = _source_registry.health(_AKSHARE_SOURCE)
    try:
        def _p(sym=symbol):
            import akshare as ak
            return ak.stock_zh_index_value_csindex(symbol=sym)
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return []
        df = _decode_df(df)
        rows: list[dict] = []
        for _, r in df.iterrows():
            rows.append({
                "date": str(r.get("日期", ""))[:10],
                "pe_1": _fnum(r.get("市盈率1")),
                "pe_2": _fnum(r.get("市盈率2")),
                "div_1": _fnum(r.get("股息率1")),
                "div_2": _fnum(r.get("股息率2")),
            })
        _ak_h.record_success()
        return rows
    except Exception as e:
        logger.warning("[valuation] index %s failed: %s", symbol, e)
        _ak_h.record_failure(_time.time())
        _mark_fail(key)
        return []


def fetch_sector_pe_snapshot(date: str | None = None) -> list[dict]:
    """板块静态 PE 快照（CNINFO，约 120 行业）.

    返回 [{ind_code, ind_name, pe_wavg, pe_median, pe_avg, as_of}]。
    失败 → []（失败记熔断 + 1h 缓存）。
    """
    arg = date or datetime.now().strftime("%Y%m%d")
    key = _fail_key("sector", arg)
    if _is_failing(key):
        return []
    _ak_h = _source_registry.health(_AKSHARE_SOURCE)
    try:
        def _p(d=arg):
            import akshare as ak
            return ak.stock_industry_pe_ratio_cninfo(date=d)
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return []
        df = _decode_df(df)
        rows: list[dict] = []
        for _, r in df.iterrows():
            rows.append({
                "ind_code": str(r.get("行业编码", "")),
                "ind_name": str(r.get("行业名称", "")),
                "pe_wavg": _fnum(r.get("静态市盈率-加权平均")),
                "pe_median": _fnum(r.get("静态市盈率-中位数")),
                "pe_avg": _fnum(r.get("静态市盈率-算术平均")),
                "as_of": str(r.get("变动日期", ""))[:10],
            })
        _ak_h.record_success()
        return rows
    except Exception as e:
        logger.warning("[valuation] sector %s failed: %s", arg, e)
        _ak_h.record_failure(_time.time())
        _mark_fail(key)
        return []
