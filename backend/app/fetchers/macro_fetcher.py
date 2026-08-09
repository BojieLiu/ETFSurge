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

import pandas as pd

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
    # round13: 当前 akshare 返回 TRADE_DATE（datetime.date），兼容旧「日期」
    date_str = str(row.get("日期", row.get("TRADE_DATE", "")) or "")
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
    """M0/M1/M2 货币供应同比。

    round13: 当前 akshare 列名「货币和准货币(M2)-同比增长」（旧版「M2-同比增长」），
    双名兼容——旧实现映射失效致 m2_yoy 恒 None（假实现隐患）。
    """
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

    return {
        "m0_yoy": _num("流通中的现金(M0)-同比增长", "M0-同比增长"),
        "m1_yoy": _num("货币(M1)-同比增长", "M1-同比增长"),
        "m2_yoy": _num("货币和准货币(M2)-同比增长", "M2-同比增长"),
        "date": date_str[:10],
        "stale": stale,
        "note": note,
    }


def fetch_cpi_ppi() -> dict | None:
    """CPI/PPI 同比（round13 修正：宽表同比接口 macro_china_cpi / macro_china_ppi）。

    原实现错用 macro_china_cpi_monthly（单商品长表，今值=CPI 月率非同比）且
    iloc[-1] 取降序表最早行（2008）→ cpi_yoy/ppi_yoy 恒空/假数据。改用宽表
    「全国-同比增长」/「当月同比增长」（实测最新 2026-07 可用），取月份最大行
    （兼容接口升降序）。今值 nan 或日期 >3 个月 → stale=true + note（不编造）。
    """
    def _cpi():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_cpi()
    def _ppi():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_ppi()
    cpi_df = cached("macro:cpi", _cpi, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    ppi_df = cached("macro:ppi", _ppi, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if cpi_df is None and ppi_df is None:
        return None  # 源全失败 → None（fetch_all_domestic_macro unavailable 语义）
    cpi_row = _latest_row(cpi_df)
    ppi_row = _latest_row(ppi_df)

    def _num(row, *keys):
        if row is None:
            return None
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
    cpi = _num(cpi_row, "全国-同比增长", "同比增长")
    ppi = _num(ppi_row, "当月同比增长", "同比增长")
    _cpi_date = cpi_row.get("月份", "") if cpi_row is not None else ""
    _ppi_date = ppi_row.get("月份", "") if ppi_row is not None else ""
    date_str = str(_cpi_date or _ppi_date or "")
    # 今值 nan 或日期 >3 个月 → stale
    stale = cpi is None or ppi is None
    _, _ = _stale_note(date_str, "数据源")  # 日期滞后同样标记
    note = ""
    if cpi is None or ppi is None:
        stale = True
        note = "数据滞后或缺失（数据源返回空值），仅作趋势参考"
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


def _latest_row(df) -> dict | None:
    """取宏观 df 中「月份/日期」最大的一行（兼容接口升降序；macro_china_cpi 实测为降序）。"""
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    key = "月份" if "月份" in df.columns else ("日期" if "日期" in df.columns else df.columns[0])

    def _parse(s):
        s = str(s or "").strip()
        s = s.replace("年", "-").replace("月份", "").replace("月", "")
        try:
            return datetime.strptime(s[:7], "%Y-%m")
        except ValueError:
            return datetime(1970, 1, 1)
    best = df.iloc[0]
    best_d = _parse(best.get(key, ""))
    for _, r in df.iterrows():
        d = _parse(r.get(key, ""))
        if d > best_d:
            best, best_d = r, d
    return best


def _no_proxy():
    from ..utils.proxy import no_proxy
    return no_proxy()


def _macro_last_row(df, value_key: str = "今值") -> dict | None:
    """取宏观 df 最后一行 → {value, date, stale, note}（列名 商品/日期/今值 兼容）。"""
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]
    date_str = str(row.get("日期", "") or "")
    stale, note = _stale_note(date_str, "数据源")
    try:
        v = float(row.get(value_key, 0) or 0)
        if v != v:  # nan
            return {"value": None, "date": date_str[:10], "stale": True,
                    "note": "数据源返回空值，仅作趋势参考"}
    except (ValueError, TypeError):
        v = None
    return {"value": v, "date": date_str[:10], "stale": stale, "note": note}


def fetch_pmi_gdp() -> dict | None:
    """PMI + GDP 两源（round13 §3.1，实测 250/61 行，东财数据中心非 push2 反爬范围）。

    - PMI: macro_china_pmi_yearly（每月一条，荣枯线 50）
    - GDP: macro_china_gdp_yearly（季频发布，同比增速）
    各自 24h 成功 / 1h 失败缓存；全失败 → None。滞后 >3 个月 → stale + note（前视偏差红线）。
    """
    def _pmi():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_pmi_yearly()
    def _gdp():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_gdp_yearly()
    pmi_df = cached("macro:pmi", _pmi, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    gdp_df = cached("macro:gdp", _gdp, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    pmi = _macro_last_row(pmi_df)
    gdp = _macro_last_row(gdp_df)
    if (pmi is None or pmi.get("value") is None) and (gdp is None or gdp.get("value") is None):
        return None
    as_of = max([d for d in ((pmi or {}).get("date", "") or "", (gdp or {}).get("date", "") or "") if d] or [""])
    return {
        "pmi": pmi,
        "gdp": gdp,
        "as_of": as_of,
    }


def fetch_gdp_series(n: int = 8) -> list[float]:
    """GDP 同比增速近 n 期（季频，round13 §3.1 P2 macro.gdp_trend 用）。

    复用 macro:gdp 缓存键（与 fetch_pmi_gdp 共享）；只用已发布值（前视偏差红线）；
    失败/空 → []（compute 输出 0 诚实降级）。
    """
    def _gdp():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_gdp_yearly()
    df = cached("macro:gdp", _gdp, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return []
    df = _decode_df(df)
    # 列名兼容：优先「今值」，兜底「同比增长」（akshare 版本差异）
    col = next((c for c in df.columns if str(c) == "今值"), None) or \
        next((c for c in df.columns if "同比" in str(c)), None)
    if col is None:
        return []
    vals = pd.to_numeric(df[col], errors="coerce").dropna().tolist()
    return [float(v) for v in vals[-n:]]


def fetch_macro_snapshot() -> dict | None:
    """聚合 M2 同比 / PMI / LPR 1Y → 方向标注（round13 §3.1 P1，契约 market/macro-regime.md）。

    复用 macro:* 24h 成功 / 1h 失败缓存；三指标全不可用 → None（detect_market_regime 降级）。
    - m2_direction: M2 同比 3 月斜率（< -0.1 收紧 → -1；> +0.1 宽松 → +1）
    - pmi_direction: PMI ≥ 50 → +1；< 50 → -1
    - lpr_direction: LPR 1Y 同比（365 天窗口）：下降 → +1（降息周期）；上升 → -1
    - macro_direction: sign(三者之和)，clamp [-1, 1]
    """
    def _m2():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_money_supply()
    def _lpr():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_lpr()
    m2_df = cached("macro:m2_series", _m2, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    lpr_df = cached("macro:lpr_series", _lpr, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    pmi_gdp = fetch_pmi_gdp() or {}
    pmi_val = (pmi_gdp.get("pmi") or {}).get("value")

    def _series_vals(df, key_prefix: str) -> list[float]:
        if df is None or df.empty:
            return []
        df = _decode_df(df)
        # 优先「…同比增长」列（前缀 + 同比限定，避免命中数量/环比列）；
        # 前缀不匹配时兜底精确旧列名「M2-同比增长」（akshare 版本差异）
        col = next((c for c in df.columns if str(c).startswith(key_prefix) and "同比" in str(c)), None)
        if col is None:
            col = next((c for c in df.columns if str(c).startswith(key_prefix)), None)
        if col is None:
            legacy = "M2-同比增长"
            col = legacy if legacy in df.columns else None
        if col is None:
            return []
        return [float(x) for x in pd.to_numeric(df[col], errors="coerce").dropna().tolist() if float(x) == float(x)]

    m2_vals = _series_vals(m2_df, "货币和准货币(M2)")
    lpr_vals = _series_vals(lpr_df, "LPR1Y")

    m2_now = m2_vals[-1] if m2_vals else None
    m2_3m = m2_vals[-3] if len(m2_vals) >= 3 else None
    m2_slope = round(m2_now - m2_3m, 2) if m2_now is not None and m2_3m is not None else None
    m2_direction = -1 if (m2_slope is not None and m2_slope < -0.1) else (1 if (m2_slope is not None and m2_slope > 0.1) else 0)

    pmi_direction = 1 if (pmi_val is not None and pmi_val >= 50) else (-1 if (pmi_val is not None and pmi_val < 50) else 0)

    lpr_now = lpr_vals[-1] if lpr_vals else None
    lpr_12m = None
    if lpr_df is not None and not lpr_df.empty and lpr_vals:
        _d = _decode_df(lpr_df)
        try:
            dates = pd.to_datetime(_d["TRADE_DATE"] if "TRADE_DATE" in _d.columns else _d["日期"], errors="coerce")
            last_date = dates.iloc[-1]
            target = last_date - pd.Timedelta(days=365)
            mask = dates <= target
            if mask.any():
                lpr_12m = lpr_vals[mask.to_numpy().nonzero()[0][-1]]
        except Exception:
            lpr_12m = None
    lpr_diff = round(lpr_now - lpr_12m, 2) if lpr_now is not None and lpr_12m is not None else None
    lpr_direction = 1 if (lpr_diff is not None and lpr_diff < -0.05) else (-1 if (lpr_diff is not None and lpr_diff > 0.05) else 0)

    sources = []
    if m2_now is not None:
        sources.append("M2")
    if pmi_val is not None:
        sources.append("PMI")
    if lpr_now is not None:
        sources.append("LPR")
    if not sources:
        return None

    total = m2_direction + pmi_direction + lpr_direction
    macro_direction = 1 if total > 0 else (-1 if total < 0 else 0)
    as_of = max([d for d in (
        str((pmi_gdp.get("pmi") or {}).get("date", "") or ""),
        str((pmi_gdp.get("gdp") or {}).get("date", "") or ""),
    ) if d] or [""])
    return {
        "m2_yoy_now": m2_now,
        "m2_yoy_3m_ago": m2_3m,
        "m2_slope": m2_slope,
        "m2_direction": m2_direction,
        "pmi_value": pmi_val,
        "pmi_direction": pmi_direction,
        "lpr_1y_now": lpr_now,
        "lpr_1y_12m_ago": lpr_12m,
        "lpr_direction": lpr_direction,
        "macro_direction": macro_direction,
        "as_of": as_of,
        "sources": sources,
    }


async def fetch_all_domestic_macro() -> dict:
    """六源并行拉取；全失败 → {"unavailable": true}（LLM 显式写不可用，不编造）。

    round13: 并入 PMI/GDP（fetch_pmi_gdp）与 macro_snapshot（方向标注）。
    """
    import asyncio
    lpr, bond, money, cpi, pmi_gdp = await asyncio.gather(
        asyncio.to_thread(fetch_lpr),
        asyncio.to_thread(fetch_bond_yields),
        asyncio.to_thread(fetch_money_supply),
        asyncio.to_thread(fetch_cpi_ppi),
        asyncio.to_thread(fetch_pmi_gdp),
    )
    snapshot = await asyncio.to_thread(fetch_macro_snapshot)
    if lpr is None and bond is None and money is None and cpi is None and pmi_gdp is None:
        return {"unavailable": True}
    return {
        "lpr": lpr,
        "bond_yields": bond,
        "money_supply": money,
        "cpi_ppi": cpi,
        "pmi_gdp": pmi_gdp,
        "macro_snapshot": snapshot,
        "unavailable": False,
    }
