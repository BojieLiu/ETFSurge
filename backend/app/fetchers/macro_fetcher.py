"""
R5-2-10: 国内宏观/流动性数据管道（用户反馈 #16）。

akshare 宏观接口（LPR / 中美国债收益率 / M0-M2 / CPI-PPI），
带 24h 成功缓存 + 1h 失败缓存（R4-26 模式）；源不可用/数据滞后显式标注。

注意：R5-2-10 时代“Shibor/社融接口已失效”的评论已过时——2026-08-09 实测恢复可用：macro_china_shibor_all 2341 行 2.2s、macro_china_shrzgm（社融）136 行 1.5s。未纳入本模块（待 round13 接入）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ..core.async_utils import run_in_thread
from ..services.cache_service import cached
from ..utils.decode import decode_df as _decode_df

logger = logging.getLogger(__name__)

# 24h 成功缓存 / 1h 失败缓存（R4-26 模式）
_SUCCESS_TTL = 86400
_FAIL_TTL = 3600


def _stale_note(date_str: str, source: str, months: int = 3) -> tuple[bool, str]:
    """判断数据是否滞后 >3 个月 → (stale, note)。兼容 YYYY-MM-DD 与 YYYY-MM。"""
    s = str(date_str or "").strip()
    if not s:
        return False, ""
    try:
        # 月份格式 YYYY-MM（如 2025-09）→ 补 -01
        if len(s) == 7 and s[4] == "-":
            d = datetime.strptime(s + "-01", "%Y-%m-%d")
        else:
            d = datetime.strptime(s[:10], "%Y-%m-%d")
        if (datetime.now() - d) > timedelta(days=months * 30):
            return True, f"数据滞后至{s[:7]}（{source}），仅作趋势参考"
    except (ValueError, TypeError):
        pass
    return False, ""


def fetch_lpr() -> dict | None:
    """LPR 贷款市场报价利率：取最后一行（最新一期），映射 LPR1Y/LPR5Y。"""
    def _p():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_lpr()
    df = cached("macro:lpr", _p, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]  # 最后一行 = 最新一期
    date_str = str(row.get("日期", "") or "")
    stale, note = _stale_note(date_str, "数据源")
    try:
        return {
            "lpr_1y": float(row.get("LPR1Y", row.get("LPR1Y", 0)) or 0) or None,
            "lpr_5y": float(row.get("LPR5Y", row.get("LPR5Y", 0)) or 0) or None,
            "date": date_str[:10],
            "stale": stale,
            "note": note,
        }
    except (ValueError, TypeError):
        return None


def fetch_bond_yields() -> dict | None:
    """中美国债收益率 + 10Y 利差（bp）。"""
    def _p():
        import akshare as ak
        with _no_proxy():
            return ak.bond_zh_us_rate()
    df = cached("macro:bond", _p, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]
    date_str = str(row.get("日期", "") or "")
    stale, note = _stale_note(date_str, "数据源")
    try:
        cn_10y = float(row.get("中国国债收益率10年", 0) or 0) or None
        us_10y = float(row.get("美国国债收益率10年", 0) or 0) or None
        spread_bp = round((cn_10y - us_10y) * 100, 1) if cn_10y is not None and us_10y is not None else None
        return {
            "cn_10y": cn_10y,
            "us_10y": us_10y,
            "spread_bp": spread_bp,
            "date": date_str[:10],
            "stale": stale,
            "note": note,
        }
    except (ValueError, TypeError):
        return None


def fetch_money_supply() -> dict | None:
    """M0/M1/M2 货币供应同比。"""
    def _p():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_money_supply()
    df = cached("macro:money", _p, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]
    date_str = str(row.get("月份", "") or row.get("日期", "") or "")
    stale, note = _stale_note(date_str, "数据源")
    try:
        return {
            "m0_yoy": float(row.get("M0-同比增长", 0) or 0) or None,
            "m1_yoy": float(row.get("M1-同比增长", 0) or 0) or None,
            "m2_yoy": float(row.get("M2-同比增长", 0) or 0) or None,
            "date": date_str[:10],
            "stale": stale,
            "note": note,
        }
    except (ValueError, TypeError):
        return None


def fetch_cpi_ppi() -> dict | None:
    """CPI/PPI 同比。今值 nan 或日期 >3 个月 → stale=true + note（不编造）。"""
    def _p():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_cpi_monthly()
    df = cached("macro:cpi", _p, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]
    date_str = str(row.get("月份", "") or row.get("日期", "") or "")
    # CPI/PPI 通常分列（全国-当月 等），取同比列
    def _num(*keys):
        for k in keys:
            v = row.get(k)
            if v is None:
                continue
            try:
                f = float(v)
                if f == f:  # 非 nan
                    return f
            except (ValueError, TypeError):
                continue
        return None
    cpi = _num("全国-同比增长", "同比增长")
    ppi = _num("当月同比增长", "同比增长")
    # 今值 nan 或日期 >3 个月 → stale
    stale = cpi is None or ppi is None
    _, _ = _stale_note(date_str, "数据源")  # 日期滞后同样标记
    note = ""
    if cpi is None or ppi is None:
        stale = True
        note = f"数据滞后或缺失（数据源返回空值），仅作趋势参考"
    else:
        _, note = _stale_note(date_str, "数据源")
        stale = stale or (note != "")
    return {
        "cpi_yoy": cpi,
        "ppi_yoy": ppi,
        "date": date_str[:10],
        "stale": stale,
        "note": note,
    }


def _no_proxy():
    from ..utils.proxy import no_proxy
    return no_proxy()


async def fetch_all_domestic_macro() -> dict:
    """四源并行拉取；全失败 → {"unavailable": true}（LLM 显式写不可用，不编造）。"""
    import asyncio
    lpr, bond, money, cpi = await asyncio.gather(
        asyncio.to_thread(fetch_lpr),
        asyncio.to_thread(fetch_bond_yields),
        asyncio.to_thread(fetch_money_supply),
        asyncio.to_thread(fetch_cpi_ppi),
    )
    if lpr is None and bond is None and money is None and cpi is None:
        return {"unavailable": True}
    return {
        "lpr": lpr,
        "bond_yields": bond,
        "money_supply": money,
        "cpi_ppi": cpi,
        "unavailable": False,
    }
