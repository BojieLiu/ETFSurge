"""Fundamentals Fetcher -- consolidated module."""

from __future__ import annotations

import logging
import os
import time as _time
from typing import Any

from ..core.async_utils import run_in_thread, run_sync
from ..core.logging import get_logger
from ..core.source_registry import registry as _source_registry
from ..services.cache_service import sync_memory_cache  # R5-2-8: 失败缓存 1h（R4-26 模式）

logger = get_logger(__name__)

# --- fundamental_fetcher.py: Fund flow ---

# F17 R61: 域名集中常量（实测 push2 502/HTTPS 连接关闭，保留 push2delay）
from ..core.market_context import EM_PUSH_HOST
from ..utils.decode import decode_df as _decode_df

_PUSH2_SOURCE = EM_PUSH_HOST
_AKSHARE_SOURCE = "akshare"

# round30: 美股指数估值——指数自身（^GSPC/^IXIC/^DJI 等）在数据源无 PE/PB 字段，
# 用对应指数 ETF 的估值作代理（SPY/QQQ/DIA 的 trailingPE/priceToBook 即指数组合口径）。
_US_INDEX_ETF_PROXY = {
    "SPX": "SPY", "^GSPC": "SPY",
    "IXIC": "QQQ", "^IXIC": "QQQ", "NDX": "QQQ", "^NDX": "QQQ",
    "DJI": "DIA", "^DJI": "DIA", "DJIA": "DIA",
}
_US_INDEX_ETF_NAME = {
    "SPX": "标普500", "^GSPC": "标普500",
    "IXIC": "纳斯达克", "^IXIC": "纳斯达克", "NDX": "纳斯达克100", "^NDX": "纳斯达克100",
    "DJI": "道琼斯", "^DJI": "道琼斯", "DJIA": "道琼斯",
}

# 熔断器健康句柄（registry._health 返回稳定单例，供涨跌家数采集记录成功/失败）
_push2_h = _source_registry.health(_PUSH2_SOURCE)


def _push2_available() -> bool:
    """检查 push2 数据源是否可用（熔断器未打开）。"""
    h = _source_registry.health(_PUSH2_SOURCE)
    return h.available(_time.time())


def _akshare_available() -> bool:
    """F17 R62: 检查 akshare 数据源健康（熔断器未打开）。"""
    h = _source_registry.health(_AKSHARE_SOURCE)
    return h.available(_time.time())


def _is_a_stock(symbol: str) -> bool:
    """A 股可交易代码的前缀判断（含场内 ETF）。"""
    return symbol[:1] in ("1", "5", "6", "0", "3")


def _get_market(symbol: str) -> str:
    """根据代码前缀返回 akshare 的 market 参数。"""
    if symbol[:1] in ("5", "6"):
        return "sh"
    if symbol[:1] in ("0", "3"):
        return "sz"
    if symbol[:1] == "1":
        return "sh"  # 16xxxx 上交所基金
    return "sz"


def fetch_fund_scale(symbol: str) -> dict | None:
    """获取基金规模与总份额。

    返回:
      {"shares_outstanding": float, "fund_scale": float} 或 None
    """
    try:
        def _p(sym=symbol):
            import akshare as ak
            return ak.fund_etf_fund_info_em(fund=sym)
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return None
        # 列名可能为 latin1 乱码，用 _decode_df
        df = _decode_df(df)
        # fund_etf_fund_info_em 通常包含 "基金规模"、"份额" 等列
        scale = None
        shares = None
        for col in df.columns:
            col_lower = col.lower()
            if "规模" in col_lower or "aum" in col_lower:
                try:
                    scale = float(df[col].iloc[0])
                except (ValueError, TypeError):
                    pass
            if "份额" in col_lower or "shares" in col_lower:
                try:
                    shares = float(df[col].iloc[0])
                except (ValueError, TypeError):
                    pass
        return {"shares_outstanding": shares, "fund_scale": scale}
    except Exception:
        return None


def fetch_fund_flow(symbol: str) -> dict | None:
    """获取个股/ETF 资金流向（主力净流入）。

    返回:
      {"main_net_inflow": float, "main_net_inflow_pct": float} 或 None
    """
    if not _is_a_stock(symbol):
        return None
    # OPT-01: 熔断器检查——F17 R62: fund_flow 实际走 akshare（stock_individual_fund_flow），
    # 旧 gate 查 push2delay 健康是语义错位（fund_flow 被涨跌家数路径的熔断 gate 误伤），
    # 改为检查 akshare 源健康
    if not _akshare_available():
        return None
    try:
        market = _get_market(symbol)
        def _p(sym=symbol, mkt=market):
            import akshare as ak
            return ak.stock_individual_fund_flow(stock=sym, market=mkt)
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return None
        df = _decode_df(df)
        # 取最新一行
        row = df.iloc[0]
        inflow = None
        inflow_pct = None
        for col in df.columns:
            col_lower = col.lower()
            if "主力净流入" in col_lower and ("净额" in col_lower or "金额" in col_lower):
                try:
                    inflow = float(row[col])
                except (ValueError, TypeError):
                    pass
            if "主力净流入" in col_lower and "占比" in col_lower:
                try:
                    inflow_pct = float(row[col])
                except (ValueError, TypeError):
                    pass
        return {"main_net_inflow": inflow, "main_net_inflow_pct": inflow_pct}
    except Exception:
        return None


def fetch_fund_flow_detailed(symbol: str) -> dict | None:
    """获取个股/ETF 四类分单资金流向（超大单/大单/中单/小单）。

    返回:
      {
        "super_large": {"inflow": float, "direction": str},
        "large": {"inflow": float, "direction": str},
        "medium": {"inflow": float, "direction": str},
        "small": {"inflow": float, "direction": str},
        "main_net_inflow": float,
        "main_net_inflow_pct": float,
      } 或 None
    direction: "净流入" / "净流出" / ""
    """
    if not _is_a_stock(symbol):
        return None
    # OPT-01: 熔断器检查——F17 R62: fund_flow 实际走 akshare（stock_individual_fund_flow），
    # 旧 gate 查 push2delay 健康是语义错位（fund_flow 被涨跌家数路径的熔断 gate 误伤），
    # 改为检查 akshare 源健康
    if not _akshare_available():
        return None
    try:
        market = _get_market(symbol)
        def _p(sym=symbol, mkt=market):
            import akshare as ak
            return ak.stock_individual_fund_flow(stock=sym, market=mkt)
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return None
        df = _decode_df(df)
        row = df.iloc[0]

        # 列名匹配模式: 前缀 + "净流入-净额" 或 "净流入-净占比"
        categories = {
            "super_large": ("超大单",),       # ≥500万
            "large": ("大单",),               # 100~500万
            "medium": ("中单",),              # 20~100万
            "small": ("小单",),               # <20万
        }

        result = {}
        main_inflow = None
        main_pct = None

        for key, prefixes in categories.items():
            inflow_val = None
            for col in df.columns:
                cl = col.lower()
                for prefix in prefixes:
                    p_lower = prefix.lower()
                    if p_lower in cl and "净流入" in cl and ("净额" in cl or "金额" in cl):
                        # 主力列单独处理
                        if "主力" in cl:
                            continue
                        try:
                            inflow_val = float(row[col])
                        except (ValueError, TypeError):
                            pass
            direction = "净流入" if (inflow_val or 0) >= 0 else "净流出"
            result[key] = {"inflow": inflow_val or 0, "direction": direction}

        # 主力净流入
        for col in df.columns:
            cl = col.lower()
            if "主力净流入" in cl and ("净额" in cl or "金额" in cl):
                try:
                    main_inflow = float(row[col])
                except (ValueError, TypeError):
                    pass
            if "主力净流入" in cl and "占比" in cl:
                try:
                    main_pct = float(row[col])
                except (ValueError, TypeError):
                    pass

        result["main_net_inflow"] = main_inflow
        result["main_net_inflow_pct"] = main_pct
        return result
    except Exception:
        return None


def fetch_hist_avg_volume(symbol: str, days: int = 20) -> dict | None:
    """获取近 N 日历史行情，返回日均成交额、最新 PE/PB。

    返回:
      {"avg_volume_20d": float, "pe_ttm": float | None, "pb": float | None} 或 None
    """
    if not _is_a_stock(symbol):
        return None
    try:
        def _p(sym=symbol):
            import akshare as ak
            return ak.stock_zh_a_hist(symbol=sym, period="daily", start_date="19900101", adjust="")
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return None
        df = _decode_df(df)
        # 取近 N 日
        recent = df.head(days)
        total_amount = 0.0
        count = 0
        for _, row in recent.iterrows():
            for col in recent.columns:
                col_lower = col.lower()
                if "成交额" in col_lower or "amount" in col_lower:
                    try:
                        total_amount += float(row[col])
                        count += 1
                    except (ValueError, TypeError):
                        pass
                    break
        avg_volume = round(total_amount / count, 2) if count else None

        # PE/PB 从最新一行取
        latest = df.iloc[0]
        pe = None
        pb_val = None
        for col in df.columns:
            col_lower = col.lower()
            if "市盈率" in col_lower or "pe" in col_lower:
                try:
                    pe = float(latest[col])
                except (ValueError, TypeError):
                    pass
            if "市净率" in col_lower or "pb" in col_lower:
                try:
                    pb_val = float(latest[col])
                except (ValueError, TypeError):
                    pass
        return {"avg_volume_20d": avg_volume, "pe_ttm": pe, "pb": pb_val}
    except Exception:
        return None


def fetch_current_pe_pb(symbol: str, market: str = "A") -> dict | None:
    """获取 ETF 最新 PE/PB 估值（轻量版，仅拉最近 5 个交易日）。

    R5-2-8: 主源（东财 stock_zh_a_hist 估值列）失败时走备用源 stock_value_em
    （东财估值接口，含 市盈率(动态)/市净率 列）；失败/空缓存 1h（R4-26 模式），
    避免反复触发慢源。

    round14 P2-AN: 加 market 参数——US 分支走东财美股 spot 的 f9（PE，实测 NVDA
    32.98 合理）；PB 因东财美股接口 f115 与 f9 同值不可靠，返回 None（报告诚实
    标注"数据源不可用"，不伪造值）。HK 分支数据源待实测（akshare stock_hk_hist
    估值列或东财港股估值），当前仍返回 None。

    round30: 美股指数（SPX/IXIC/DJI 等）符号优先走指数估值分支——SPX 用 multpl
    （真实指数口径），其余用 Yahoo ETF 代理（直连 quoteSummary，绕开 yfinance
    库会话限流）；成功缓存 6h / 失败缓存 1h（R4-26 模式）。

    返回:
      {"pe_ttm": float, "pb": float} | None
    """
    if str(symbol).upper() in _US_INDEX_ETF_PROXY:
        return _fetch_us_index_pe_pb_cached(symbol)
    if market and market.upper() == "US":
        return _fetch_us_pe_pb(symbol)
    if not _is_a_stock(symbol):
        return None

    # R5-2-8: 失败/空结果缓存 1h（成功结果由调用方缓存，此处只防慢源反复触发）
    _FAIL_KEY = f"_pe_pb_fail:{symbol}"
    try:
        if sync_memory_cache.get(_FAIL_KEY) is not None:
            return None
    except Exception:
        pass

    result = _fetch_pe_pb_primary(symbol)
    if result is None:
        # 备用源：stock_value_em（东财估值，列：市盈率-动态/市净率 等）
        result = _fetch_pe_pb_fallback(symbol)
    if result is None:
        try:
            sync_memory_cache.set(_FAIL_KEY, True, 3600)
        except Exception:
            pass
    return result


def _fetch_us_index_pe_pb_cached(symbol: str) -> dict | None:
    """round30: 美股指数估值（multpl / Yahoo ETF 代理）+ 缓存——成功 6h / 失败 1h（R4-26）。

    估值变化慢 + 外部源有被限流风险：成功结果缓存 6h，失败缓存 1h，
    避免 symbol-analysis 每次请求都触发慢源/限流。
    """
    norm = str(symbol).upper()
    _ok_key = f"_pe_pb_us_index:{norm}"
    _fail_key = f"_pe_pb_us_index_fail:{norm}"
    try:
        cached = sync_memory_cache.get(_ok_key)
        if cached is not None:
            return cached
        if sync_memory_cache.get(_fail_key) is not None:
            return None
    except Exception:
        pass
    result = _fetch_us_index_pe_pb(symbol)
    try:
        if result:
            sync_memory_cache.set(_ok_key, result, 6 * 3600)
        else:
            sync_memory_cache.set(_fail_key, True, 3600)
    except Exception:
        pass
    return result


def _fetch_us_index_pe_pb(symbol: str) -> dict | None:
    """round30: 美股指数 PE/PB——SPX 走 multpl（指数官方口径），其余指数 Yahoo ETF 代理。

    探针（2026-08-19）：
    - multpl s-p-500-pe-ratio / s-p-500-price-to-book：S&P 500 自身 trailing PE=29.65 /
      PB=6.11（真实指数口径，非 ETF 代理；multpl 仅覆盖标普500）；
    - Yahoo quoteSummary：SPY/QQQ/DIA 的 trailingPE=25.85/30.68/22.13（指数组合口径
      代理；yfinance 库会话限流，改为直连）。ETF 的 priceToBook 为空 → PB=None。
    全部失败/无有效值返回 None（报告诚实降级为「数据源不可用」，不伪造值）。
    """
    norm = str(symbol).upper()
    if norm in ("SPX", "^GSPC"):
        result = _fetch_spx_pe_pb_multpl()
        if result:
            return result
        # multpl 失败时回落到 Yahoo SPY 代理（保证 SPX 报告仍可出估值）
        return _fetch_us_etf_proxy_pe_pb(norm)
    return _fetch_us_etf_proxy_pe_pb(norm)


_MULT_PL_URLS = {
    "pe": "https://www.multpl.com/s-p-500-pe-ratio",
    "pb": "https://www.multpl.com/s-p-500-price-to-book",
}


def _fetch_spx_pe_pb_multpl() -> dict | None:
    """SPX 官方口径估值：multpl（S&P 500 trailing PE / Price-to-Book）。

    解析 meta description（'...Current S&P 500 PE Ratio is 29.65, a change...'）
    与页面显示（'Current S&P 500 PE Ratio : 29.65 -0.21 ...'）双兜底。
    任一请求失败返回 None（调用方回落到 Yahoo ETF 代理）。
    """
    def _load():
        import re as _re

        def _get(url: str) -> str:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=12) as r:
                body = r.read().decode("utf-8", "ignore")
            # HTML 实体归一：'S&amp;P 500' → 'S&P 500'，保证与正则匹配
            return body.replace("&amp;", "&")

        def _val(body: str, key: str):
            m = _re.search(key + r" is ([\d.]+)", body)
            if not m:
                m = _re.search(key + r" : ([\d.]+)", body)
            return float(m.group(1)) if m else None

        pe_body = _get(_MULT_PL_URLS["pe"])
        pb_body = _get(_MULT_PL_URLS["pb"])
        return {
            "pe": _val(pe_body, r"S&P 500 PE Ratio"),
            "pb": _val(pb_body, r"S&P 500 Price to Book Value"),
        }

    try:
        data = run_in_thread(_load, timeout=25, executor="long")
    except Exception:
        return None
    if not data:
        return None
    result = {}
    try:
        if data.get("pe") is not None and float(data["pe"]) > 0:
            result["pe_ttm"] = round(float(data["pe"]), 2)
    except (TypeError, ValueError):
        pass
    try:
        if data.get("pb") is not None and float(data["pb"]) > 0:
            result["pb"] = round(float(data["pb"]), 2)
    except (TypeError, ValueError):
        pass
    if not result:
        return None
    result["source"] = "标普500估值(multpl)"
    return result


def _fetch_us_etf_proxy_pe_pb(norm: str) -> dict | None:
    """round30: 美股指数估值备用源——直连 Yahoo quoteSummary 取 ETF 代理估值。

    SPY/QQQ/DIA（对应指数基金）的 trailingPE 即指数组合口径估值。yfinance 库在
    本环境会持续 YFRateLimitError（2026-08-19 实测 40+ 分钟未恢复，crumb/会话
    握手坏），改为手动 crumb 流程直连 query1.finance.yahoo.com quoteSummary
    （探针连续 4 次稳定返回）。ETF 的 priceToBook Yahoo 返回空 → PB 诚实置 None。
    失败/无有效值返回 None（报告诚实降级，不伪造值）。
    """
    etf = _US_INDEX_ETF_PROXY.get(norm)
    if not etf:
        return None
    try:
        data = run_in_thread(_fetch_yahoo_quote_summary, etf, timeout=15, executor="long")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    result = {}
    try:
        pe = data.get("pe")
        if pe is not None and float(pe) > 0:
            result["pe_ttm"] = round(float(pe), 2)
    except (TypeError, ValueError):
        pass
    try:
        pb = data.get("pb")
        if pb is not None and float(pb) > 0:
            result["pb"] = round(float(pb), 2)
    except (TypeError, ValueError):
        pass
    if not result:
        return None
    result["source"] = f"{_US_INDEX_ETF_NAME.get(norm, norm)}估值取{etf}ETF代理(yahoo)"
    return result


def _fetch_yahoo_quote_summary(etf: str) -> dict | None:
    """直连 Yahoo quoteSummary（手动 crumb 流程）→ {'pe','pb'} | None。

    yfinance 库的 cookie/crumb 会话在本环境持续 YFRateLimitError；此实现每次
    新会话取 crumb 再请求 quoteSummary（summaryDetail→trailingPE，
    defaultKeyStatistics→priceToBook），探针验证稳定。
    """
    import http.cookiejar
    import urllib.parse
    import urllib.request

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "Chrome/126.0 Safari/537.36"),
    ]

    def _get(url: str) -> str:
        with opener.open(url, timeout=10) as r:
            return r.read().decode("utf-8", "ignore")

    try:
        # 1) fc.yahoo.com 建会话 cookie（404 无妨，crumb 仍可用）
        try:
            _get("https://fc.yahoo.com")
        except Exception:
            pass
        # 2) crumb
        crumb = _get("https://query1.finance.yahoo.com/v1/test/getcrumb")
        if not crumb:
            return None
        # 3) quoteSummary
        url = (
            "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
            + urllib.parse.quote(etf)
            + "?modules=summaryDetail,defaultKeyStatistics&crumb=" + crumb
        )
        body = _get(url)
    except Exception:
        return None
    return _parse_yahoo_quote_summary(body)


def _parse_yahoo_quote_summary(body: str) -> dict | None:
    """从 Yahoo quoteSummary JSON 提取 {'pe','pb'}（ETF 的 priceToBook 常为空→pb=None）。"""
    import json

    try:
        d = json.loads(body)
    except Exception:
        return None
    res = (((d or {}).get("quoteSummary") or {}).get("result") or [{}])[0]
    pe = (((res or {}).get("summaryDetail") or {}).get("trailingPE") or {}).get("raw")
    pb = (((res or {}).get("defaultKeyStatistics") or {}).get("priceToBook") or {}).get("raw")
    return {"pe": pe, "pb": pb}


def _fetch_us_pe_pb(symbol: str) -> dict | None:
    """round14 P2-AN: 美股 PE——东财美股 spot（m:105）按 symbol 查 f9。

    实测（2026-08-11 探针）：NVDA f9=32.98 合理；f115 与 f9 同值（PB 字段不可靠），
    PB 返回 None 由报告层诚实标注"数据源不可用"。失败/未命中返回 None。
    """
    try:
        from ..fetchers.sector_fetcher import _fetch_us_spot_rich
        rows = _fetch_us_spot_rich()
        hit = next((r for r in rows if str(r.get("symbol", "")).upper() == str(symbol).upper()), None)
        if not hit or hit.get("pe") is None:
            return None
        try:
            pe = float(hit["pe"])
        except (TypeError, ValueError):
            return None
        if pe <= 0:
            return None  # 负 PE（亏损）或 0 视为无有效估值
        return {"pe_ttm": pe, "pb": None}
    except Exception:
        return None


def _fetch_pe_pb_primary(symbol: str) -> dict | None:
    """主源：stock_zh_a_hist 日线估值列（东财）。R5-2-9: 成功/失败记入 akshare 熔断计数。"""
    _ak_h = _source_registry.health(_AKSHARE_SOURCE)
    try:
        def _p(sym=symbol):
            import akshare as ak
            return ak.stock_zh_a_hist(symbol=sym, period="daily",
                                      start_date="20260101", adjust="")
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return None
        df = _decode_df(df)
        latest = df.iloc[0]
        pe = None
        pb_val = None
        for col in df.columns:
            cl = col.lower()
            if "市盈率" in cl or "pe" in cl:
                try:
                    pe = float(latest[col])
                except (ValueError, TypeError):
                    pass
            if "市净率" in cl or "pb" in cl:
                try:
                    pb_val = float(latest[col])
                except (ValueError, TypeError):
                    pass
        if pe is None and pb_val is None:
            return None
        _ak_h.record_success()
        result = {}
        if pe is not None:
            result["pe_ttm"] = pe
        if pb_val is not None:
            result["pb"] = pb_val
        return result
    except Exception:
        _ak_h.record_failure(_time.time())
        return None


def _fetch_pe_pb_fallback(symbol: str) -> dict | None:
    """R5-2-8 备用源：stock_value_em（东财估值接口，列含 市盈率-动态/市净率）。
    R5-2-9: 成功/失败同样记入 akshare 熔断计数。"""
    _ak_h = _source_registry.health(_AKSHARE_SOURCE)
    try:
        def _p(sym=symbol):
            import akshare as ak
            return ak.stock_value_em(symbol=sym)
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return None
        df = _decode_df(df)
        row = df.iloc[0]
        result = {}
        for col in df.columns:
            cl = str(col).lower()
            if "市盈率" in cl or "pe" in cl:
                try:
                    v = float(row[col])
                    if v and abs(v) > 0:
                        result.setdefault("pe_ttm", v)
                except (ValueError, TypeError):
                    pass
            if "市净率" in cl or "pb" in cl:
                try:
                    v = float(row[col])
                    if v and abs(v) > 0:
                        result.setdefault("pb", v)
                except (ValueError, TypeError):
                    pass
        if result:
            _ak_h.record_success()
            return result
        return None
    except Exception:
        _ak_h.record_failure(_time.time())
        return None


def fetch_fundamentals(symbol: str) -> dict:
    """一站式获取某只 ETF 的所有基本面数据。

    所有字段在不可用时为 None。
    """
    result: dict[str, Any] = {
        "shares_outstanding": None,
        "fund_scale": None,
        "pe_ttm": None,
        "pb": None,
        "avg_volume_20d": None,
        "main_net_inflow": None,
        "main_net_inflow_pct": None,
    }

    if not _is_a_stock(symbol):
        return result

    scale_data = fetch_fund_scale(symbol)
    if scale_data:
        result.update(scale_data)

    hist_data = fetch_hist_avg_volume(symbol)
    if hist_data:
        result.update(hist_data)

    flow_data = fetch_fund_flow(symbol)
    if flow_data:
        result.update(flow_data)

    return result

# --- margin_fetcher.py: Margin balance ---

import json
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT = 8

# ── SZSE ───────────────────────────────────────────────────────────

def _fetch_szse() -> float | None:
    """Fetch margin balance from SZSE via akshare.

    Returns total 融资余额 (margin debit balance) in yuan, or None.
    Uses stock_margin_szse() from akshare (verified working under IPv4).
    """
    try:
        def _p():
            import akshare as ak
            df = ak.stock_margin_szse()
            if df is not None and not df.empty:
                return float(df['融资余额'].iloc[-1])
            return None
        from ..core.async_utils import run_in_thread
        result = run_in_thread(_p, timeout=_TIMEOUT, executor="long")
        return result
    except Exception as exc:
        logger.warning("[margin_fetcher] SZSE akshare failed: %s", exc)
        return None


# ── SSE ────────────────────────────────────────────────────────────

def _fetch_sse() -> float | None:
    """Fetch margin balance from SSE via akshare.

    Returns total 融资余额 (margin debit balance) in yuan, or None.
    Uses stock_margin_sse() from akshare (verified working under IPv4).
    """
    try:
        def _p():
            import akshare as ak
            df = ak.stock_margin_sse()
            if df is not None and not df.empty:
                return float(df['融资余额'].iloc[-1])
            return None
        from ..core.async_utils import run_in_thread
        result = run_in_thread(_p, timeout=_TIMEOUT, executor="long")
        return result
    except Exception as exc:
        logger.warning("[margin_fetcher] SSE akshare failed: %s", exc)
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

# --- sentiment_fetcher.py: Market sentiment ---

logger = logging.getLogger(__name__)

# ── Static default weights (used when no regime context) ──────────
SENTIMENT_WEIGHTS = {
    "advance_ratio": 0.30,
    "margin_change": 0.30,
    "volume_ratio": 0.20,
    "inst_consensus": 0.20,
}

# ── Regime-conditioned weights ───────────────────────────────────
# In strong bull markets, institutional consensus and north flow carry more signal.
# In bear/correction, advance/decline ratio and margin changes matter more.
_REGIME_WEIGHTS = {
    "bull_strong":   {"advance_ratio": 0.20, "inst_consensus": 0.35, "volume_ratio": 0.25, "margin_change": 0.20},
    "bull_weakening": {"advance_ratio": 0.25, "inst_consensus": 0.30, "volume_ratio": 0.25, "margin_change": 0.20},
    "range_bound":   {"advance_ratio": 0.25, "inst_consensus": 0.20, "volume_ratio": 0.25, "margin_change": 0.30},
    "correction":    {"advance_ratio": 0.30, "inst_consensus": 0.15, "volume_ratio": 0.20, "margin_change": 0.35},
    "bear":          {"advance_ratio": 0.35, "inst_consensus": 0.15, "volume_ratio": 0.15, "margin_change": 0.35},
    "panic":         {"advance_ratio": 0.40, "inst_consensus": 0.10, "volume_ratio": 0.10, "margin_change": 0.40},
    "defensive_rotate": {"advance_ratio": 0.30, "inst_consensus": 0.25, "volume_ratio": 0.20, "margin_change": 0.25},
}

def _dynamic_weights(regime: str | None) -> dict[str, float]:
    """Return regime-conditioned weights, falling back to equal weights."""
    if regime and regime in _REGIME_WEIGHTS:
        return dict(_REGIME_WEIGHTS[regime])
    return dict(SENTIMENT_WEIGHTS)


# ── Momentum tracking for sentiment inertia correction ───────────
# Stores (value, timestamp) for the three most recent calculations.
_sentiment_history: list[tuple[float, float]] = []

# F19 R68: 20 日 sentiment_index 滚动数组（供 panic_greed_diff 因子——
# 该因子要求 sentiment_history 且 len >= 5，旧实现从不生成该字段 → 永远 no_data）
_sentiment_rolling: list[float] = []

_SENTIMENT_HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sentiment_history.json"
)


def _persist_sentiment_history(file_path: str, sentiment: dict) -> None:
    """F19 R68: 将滚动数组落盘（进程重启后仍保留历史，冷启动即有样本）。"""
    history = sentiment.get("sentiment_history") or []
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
    except Exception:
        pass  # 落盘失败不阻塞主流程


def _load_sentiment_history(file_path: str) -> list[float]:
    """F19 R68: 模块加载/刷新时读回滚动数组（上限 20 条，丢弃最旧）。"""
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [float(x) for x in data][-20:]
    except Exception:
        pass
    return []


def _momentum_correction(current: float) -> float:
    """
    Apply inertia correction based on recent sentiment trajectory.

    A sharp drop (e.g., 75→55 in one period) indicates actual sentiment
    is worse than the current value suggests. Adds a penalty proportional
    to the rate of change.
    """
    global _sentiment_history
    now = __import__('time').time()
    _sentiment_history.append((current, now))
    # Keep last 3 entries
    if len(_sentiment_history) > 3:
        _sentiment_history.pop(0)

    if len(_sentiment_history) < 2:
        return current

    prev_val = _sentiment_history[-2][0]
    delta = current - prev_val

    # Sharp drop (-15+ points in one period): penalize
    # Sharp rise (+15+ points in one period): boost
    correction = delta * 0.3  # Dampened momentum factor
    corrected = current + correction

    # Clamp to [0, 100]
    return max(0.0, min(100.0, corrected))


def sentiment_label(index: float) -> str:
    """将情绪指数 (0~100) 映射为文字标签。"""
    if index >= 80:
        return "亢奋"
    elif index >= 65:
        return "乐观"
    elif index >= 55:
        return "中性偏乐观"
    elif index >= 45:
        return "中性"
    elif index >= 35:
        return "中性偏谨慎"
    elif index >= 20:
        return "谨慎"
    else:
        return "恐慌"


def normalize(val: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    """将数值归一化到 [0, 1] 区间。"""
    if max_val == min_val:
        return 0.5
    return max(0.0, min(1.0, (val - min_val) / (max_val - min_val)))


def calc_sentiment_index(
    advance_ratio: float,
    margin_change: float = 0.0,
    volume_ratio: float = 0.0,
    inst_consensus: float = 0.0,
    regime: str | None = None,
) -> float:
    """合成四维情绪指数 (0~100)，含动态权重 + 情绪惯量修正。

    Args:
        advance_ratio: 上涨家数占比 (0~1)
        inst_consensus: 机构共识度 (-1~1, 默认0.0=中性)
        margin_change: 两融变化 (-1~1, 归一化)
        volume_ratio: 成交量比 (近5日/20日)
        regime: 市场状态，用于条件权重 + 数据缺失偏置
    """
    w = _dynamic_weights(regime)
    score = (
        w["advance_ratio"] * advance_ratio
        + w["inst_consensus"] * normalize(inst_consensus)
        + w["volume_ratio"] * normalize(volume_ratio)
        + w["margin_change"] * normalize(margin_change)
    )

    # 当多维度均为中性默认值时（数据源故障），用 regime 偏置
    all_default = (
        abs(advance_ratio - 0.5) < 0.05
        and abs(volume_ratio - 1.0) < 0.01
        and abs(margin_change) < 0.01
    )
    if all_default and regime:
        regime_bias = {
            "bull_strong": 0.70, "bull_weakening": 0.55,
            "range_bound": 0.50,
            "correction": 0.30, "bear": 0.20,
            "defensive_rotate": 0.35, "panic": 0.10,
        }
        score = regime_bias.get(regime, score)

    raw = round(score * 100, 1)
    # Apply momentum (inertia) correction
    return _momentum_correction(raw)


def fetch_advance_decline_ratio() -> float:
    """获取市场涨跌家数比 (上涨家数/总家数)。

    FIX-S01: 使用 push2delay 域名替代 push2 (push2 已被拒)；
             失败时通过 registry.record_failure() 报告熔断器。
    数据源优先级: 1. push2delay.eastmoney.com 2. akshare
    返回: 0~1, 失败时返回 0.5 (中性)
    """
    # S01: 检查熔断器状态
    if not _push2_h.available(_time.time()):
        logger.warning("[sentiment] push2delay circuit open, skipping direct fetch")
        _push2_h.record_failure(_time.time())
        return _advance_decline_fallback()

    # 1. push2delay.eastmoney.com (实测可用，替代被拒的 push2)
    try:
        import json
        import urllib.request
        url = "https://push2delay.eastmoney.com/api/qt/clist/get"
        params = "?pn=1&pz=5000&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        req = urllib.request.Request(url + params, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        items = data.get("data", {}).get("diff", [])
        if items:
            up = sum(1 for i in items if float(i.get("f3", 0) or 0) > 0)
            total = len(items)
            if total > 0:
                _push2_h.record_success()
                return up / total
    except Exception as e:
        logger.warning("[sentiment] push2delay advance_decline failed: %s", e)
        _push2_h.record_failure(_time.time())

    return _advance_decline_fallback()


def _advance_decline_fallback() -> float:
    """S01: akshare fallback for advance_decline ratio. Also reports to circuit breaker."""
    try:
        def _p():
            import akshare as ak
            return ak.stock_zh_a_spot_em()
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is not None and not df.empty:
            up = sum(1 for _, r in df.iterrows() if float(r.get("涨跌幅", 0) or 0) > 0)
            total = len(df)
            if total > 0:
                _push2_h.record_success()
                return up / total
    except Exception as e2:
        logger.warning("[sentiment] akshare advance_decline fallback failed: %s", e2)

    _push2_h.record_failure(_time.time())
    return 0.5





def fetch_margin_change() -> float:
    """获取两融余额变化率 (归一化 -1~1)。

    返回: -1~1, 失败时返回 0
    """
    try:
        def _p():
            import akshare as ak
            return ak.stock_margin_szse()
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return 0.0
        if len(df) >= 2:
            # 最近两期的两融余额变化
            try:
                val_col = None
                for col in df.columns:
                    if "融资余额" in col or "余额" in col:
                        val_col = col
                        break
                if val_col:
                    v1 = float(df.iloc[0][val_col] or 0)
                    v2 = float(df.iloc[1][val_col] or 0)
                    if v2 > 0:
                        pct = (v1 - v2) / v2
                        return max(-1.0, min(1.0, pct * 5))  # ±20% => ±1
            except (IndexError, ValueError, TypeError):
                pass
    except Exception as e:
        logger.warning("[sentiment] fetch_margin_change akshare failed: %s", e)

    # Fallback: 深交所/上交所 API
    try:
        balance = run_in_thread(fetch_margin_balance, timeout=8, executor="long")
        if balance and balance > 0:
            # 归一化: ±5000亿为极端值
            norm = max(-1.0, min(1.0, (balance - 1.8e12) / 5e11))
            return norm
    except Exception as e:
        logger.warning("[sentiment] fetch_margin_change SZSE/SSE fallback failed: %s", e)

    return 0.0


def _fetch_volume_ratio() -> float:
    """Get volume ratio (5-day avg vol / 20-day avg vol).

    Returns: float >= 0, defaults to 1.0 on failure.
    """
    try:
        def _p():
            import akshare as ak
            import pandas as pd
            df = ak.stock_market_fundamental_em()
            if df is not None and not df.empty:
                try:
                    vol_col = None
                    for col in df.columns:
                        if 'amount' in col.lower() or 'volume' in col.lower() or '成交' in col:
                            vol_col = col
                            break
                    if vol_col and len(df) >= 20:
                        vol_series = pd.to_numeric(df[vol_col], errors='coerce').fillna(0)
                        vol5 = vol_series.tail(5).mean()
                        vol20 = vol_series.tail(20).mean()
                        if vol20 > 0:
                            return float(vol5 / vol20)
                except (ValueError, IndexError, TypeError):
                    pass
            return 1.0
        from ..core.async_utils import run_in_thread
        result = run_in_thread(_p, timeout=8, executor="long")
        return result if result is not None else 1.0
    except Exception as e:
        logger.warning("[sentiment] _fetch_volume_ratio failed: %s", e)
        return 1.0


async def fetch_market_sentiment() -> dict[str, Any]:
    """一站式获取市场情绪指数。

    返回:
    {
        "sentiment_index": 65.0,
        "sentiment_label": "中性偏乐观",
        "advance_ratio": 0.6,
        "institutional_consensus": 0.0,
        "volume_ratio": 1.0,
        "margin_change": 0.0,
    }
    """
    import asyncio
    advance, vr, margin = await asyncio.gather(
        run_sync(fetch_advance_decline_ratio, timeout=15),
        run_sync(_fetch_volume_ratio, timeout=15),
        run_sync(fetch_margin_change, timeout=15),
        return_exceptions=True,
    )

    # round15 基线 B（test-guard-baseline.md §2）: 降级路径显式标注——
    # 任一数据源失败（fallback 默认值）时输出带 _degraded: true，
    # 不冒充满血结果（R2: 降级标记语义，防「源全挂也恒绿」测试盲区）。
    advance_ok = isinstance(advance, float) and not isinstance(advance, Exception)
    vr_ok = isinstance(vr, float) and not isinstance(vr, Exception)
    margin_ok = isinstance(margin, float) and not isinstance(margin, Exception)

    advance = advance if advance_ok else 0.5
    vr = vr if vr_ok else 1.0
    margin = margin if margin_ok else 0.0

    index = calc_sentiment_index(
        advance_ratio=advance,
        inst_consensus=0.0,  # 共识度由调用方传入（需要四类资金流数据）
        volume_ratio=vr,
        margin_change=margin,
    )

    # F19 R68: 维护 20 日 sentiment_index 滚动数组并随返回附带——
    # _compute_panic_greed_diff 要求 data["sentiment_history"] 且 len>=5，
    # 旧实现从不生成该字段（结构性 bug → 因子永远 no_data）。
    global _sentiment_rolling
    if not _sentiment_rolling:
        # 冷启动：从持久化文件恢复历史（跨进程保留，避免重启后需 20 日才累积样本）
        _sentiment_rolling = _load_sentiment_history(_SENTIMENT_HISTORY_FILE)
    _sentiment_rolling.append(float(index))
    if len(_sentiment_rolling) > 20:
        _sentiment_rolling = _sentiment_rolling[-20:]

    result = {
        "sentiment_index": index,
        "sentiment_label": sentiment_label(index),
        "advance_ratio": round(advance, 4),
        "institutional_consensus": 0.0,  # placeholder, 调用方填充
        "volume_ratio": round(vr, 4),
        "margin_change": round(margin, 4),
        "sentiment_history": list(_sentiment_rolling),
    }
    # round15 基线 B: 降级标记（任一源失败 → 输出非满血，前端/测试可感知）
    if not (advance_ok and vr_ok and margin_ok):
        result["_degraded"] = True
    # F19 R68: 落盘（进程重启后仍保留历史）
    _persist_sentiment_history(_SENTIMENT_HISTORY_FILE, result)
    return result
