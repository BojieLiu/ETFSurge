"""Fundamentals Fetcher -- consolidated module."""

from __future__ import annotations
import logging
import time as _time
from datetime import datetime, timedelta
from typing import Any

from ..core.async_utils import run_in_thread
from ..config import settings
from ..services.source_registry import registry as _source_registry
from ..core.logging import get_logger

logger = get_logger(__name__)

# --- fundamental_fetcher.py: Fund flow ---

from ..utils.decode import decode_df as _decode_df
_PUSH2_SOURCE = "push2.eastmoney.com"
_AKSHARE_SOURCE = "akshare"


def _push2_available() -> bool:
    """检查 push2 数据源是否可用（熔断器未打开）。"""
    h = _source_registry._health(_PUSH2_SOURCE)
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
    # OPT-01: 熔断器检查，push2 不可用时立即降级
    if not _push2_available():
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
    # OPT-01: 熔断器检查，push2 不可用时立即降级
    if not _push2_available():
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
        market = _get_market(symbol)
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


def fetch_current_pe_pb(symbol: str) -> dict | None:
    """获取 ETF 最新 PE/PB 估值（轻量版，仅拉最近 5 个交易日）。

    返回:
      {"pe_ttm": float, "pb": float} | None
    """
    if not _is_a_stock(symbol):
        return None
    try:
        market = _get_market(symbol)
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
        result = {}
        if pe is not None:
            result["pe_ttm"] = pe
        if pb_val is not None:
            result["pb"] = pb_val
        return result
    except Exception:
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
    url = f"{_SSE_URL}?jsonCallBack=jsonp&_={int(_time.time() * 1000)}"
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

# --- sentiment_fetcher.py: Market sentiment ---

logger = logging.getLogger(__name__)

# ── Static default weights (used when no regime context) ──────────
SENTIMENT_WEIGHTS = {
    "advance_ratio": 0.25,
    "inst_consensus": 0.25,
    "north_flow": 0.25,
    "margin_change": 0.25,
}

# ── Regime-conditioned weights ───────────────────────────────────
# In strong bull markets, institutional consensus and north flow carry more signal.
# In bear/correction, advance/decline ratio and margin changes matter more.
_REGIME_WEIGHTS = {
    "bull_strong":   {"advance_ratio": 0.15, "inst_consensus": 0.35, "north_flow": 0.35, "margin_change": 0.15},
    "bull_weakening": {"advance_ratio": 0.20, "inst_consensus": 0.30, "north_flow": 0.30, "margin_change": 0.20},
    "range_bound":   {"advance_ratio": 0.25, "inst_consensus": 0.25, "north_flow": 0.25, "margin_change": 0.25},
    "correction":    {"advance_ratio": 0.30, "inst_consensus": 0.20, "north_flow": 0.20, "margin_change": 0.30},
    "bear":          {"advance_ratio": 0.35, "inst_consensus": 0.15, "north_flow": 0.15, "margin_change": 0.35},
    "panic":         {"advance_ratio": 0.40, "inst_consensus": 0.10, "north_flow": 0.10, "margin_change": 0.40},
    "defensive_rotate": {"advance_ratio": 0.30, "inst_consensus": 0.25, "north_flow": 0.20, "margin_change": 0.25},
}


def _dynamic_weights(regime: str | None) -> dict[str, float]:
    """Return regime-conditioned weights, falling back to equal weights."""
    if regime and regime in _REGIME_WEIGHTS:
        return dict(_REGIME_WEIGHTS[regime])
    return dict(SENTIMENT_WEIGHTS)


# ── Momentum tracking for sentiment inertia correction ───────────
# Stores (value, timestamp) for the three most recent calculations.
_sentiment_history: list[tuple[float, float]] = []


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
    inst_consensus: float = 0.0,
    north_flow: float = 0.0,
    margin_change: float = 0.0,
    regime: str | None = None,
) -> float:
    """合成四维情绪指数 (0~100)，含动态权重 + 情绪惯量修正。

    Args:
        advance_ratio: 上涨家数占比 (0~1)
        inst_consensus: 机构共识度 (-1~1, 默认0.0=中性)
        north_flow: 北向资金方向 (-1~1, 归一化)
        margin_change: 两融变化 (-1~1, 归一化)
        regime: 市场状态，用于条件权重 + 数据缺失偏置
    """
    w = _dynamic_weights(regime)
    score = (
        w["advance_ratio"] * advance_ratio
        + w["inst_consensus"] * normalize(inst_consensus)
        + w["north_flow"] * normalize(north_flow)
        + w["margin_change"] * normalize(margin_change)
    )

    # 当多维度均为中性默认值时（数据源故障），用 regime 偏置
    all_default = (
        abs(advance_ratio - 0.5) < 0.05
        and abs(north_flow) < 0.01
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

    数据源优先级: 1. Sina/EastMoney push2 API 2. akshare
    返回: 0~1, 失败时返回 0.5 (中性)
    """
    # 1. Sina/EastMoney push2 API (faster & more reliable than akshare)
    try:
        # 获取沪深全部股票简况
        import urllib.request
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = "?pn=1&pz=5000&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        req = urllib.request.Request(url + params, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        import json
        data = json.loads(resp.read().decode("utf-8"))
        items = data.get("data", {}).get("diff", [])
        if items:
            up = sum(1 for i in items if float(i.get("f3", 0) or 0) > 0)
            total = len(items)
            if total > 0:
                return up / total
    except Exception as e:
        logger.warning("[sentiment] push2 advance_decline failed: %s", e)

    # 2. akshare fallback
    try:
        def _p():
            import akshare as ak
            return ak.stock_zh_a_spot_em()
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is not None and not df.empty:
            up = sum(1 for _, r in df.iterrows() if float(r.get("涨跌幅", 0) or 0) > 0)
            total = len(df)
            if total > 0:
                return up / total
    except Exception as e2:
        logger.warning("[sentiment] akshare advance_decline failed: %s", e2)

    return 0.5


def fetch_north_flow() -> float:
    """获取北向资金当日净流入 (归一化 -1~1)。

    返回: -1~1, 失败时返回 0
    """
    try:
        # Try multiple akshare north-bound API names (version-dependent)
        df = None
        for func_name in ["stock_hsgt_north_net_flow_in_em",
                          "stock_hsgt_north_flow_in_em",
                          "stock_hsgt_north_net_flow"]:
            try:
                def _p(fn=func_name):
                    import akshare as ak
                    func = getattr(ak, fn, None)
                    if func:
                        return func(symbol="北上")
                    return None
                df = run_in_thread(_p, timeout=8, executor="long")
                if df is not None and not (hasattr(df, "empty") and df.empty):
                    break
            except Exception:
                continue
        if df is None or (hasattr(df, "empty") and df.empty):
            return 0.0
        # 取最近一条的净流入
        latest = df.iloc[0]
        for col in df.columns:
            if "净流入" in col or "net" in col.lower():
                val = float(latest[col] or 0)
                # 归一化: ±50亿为极端值
                return max(-1.0, min(1.0, val / 50_000_000))
    except Exception as e:
        logger.warning("[sentiment] fetch_north_flow failed: %s", e)
    return 0.0


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
        balance = run_in_thread(margin_fetcher.fetch_margin_balance, timeout=8, executor="long")
        if balance and balance > 0:
            # 归一化: ±5000亿为极端值
            norm = max(-1.0, min(1.0, (balance - 1.8e12) / 5e11))
            return norm
    except Exception as e:
        logger.warning("[sentiment] fetch_margin_change SZSE/SSE fallback failed: %s", e)

    return 0.0


async def fetch_market_sentiment() -> dict[str, Any]:
    """一站式获取市场情绪指数。

    返回:
    {
        "sentiment_index": 65.0,
        "sentiment_label": "中性偏乐观",
        "advance_ratio": 0.6,
        "institutional_consensus": 0.0,
        "north_flow": 0.0,
        "margin_change": 0.0,
    }
    """
    import asyncio
    advance, north, margin = await asyncio.gather(
        run_sync(fetch_advance_decline_ratio, timeout=15),
        run_sync(fetch_north_flow, timeout=15),
        run_sync(fetch_margin_change, timeout=15),
        return_exceptions=True,
    )

    advance = advance if isinstance(advance, float) and not isinstance(advance, Exception) else 0.5
    north = north if isinstance(north, float) and not isinstance(north, Exception) else 0.0
    margin = margin if isinstance(margin, float) and not isinstance(margin, Exception) else 0.0

    index = calc_sentiment_index(
        advance_ratio=advance,
        inst_consensus=0.0,  # 共识度由调用方传入（需要四类资金流数据）
        north_flow=north,
        margin_change=margin,
    )

    return {
        "sentiment_index": index,
        "sentiment_label": sentiment_label(index),
        "advance_ratio": round(advance, 4),
        "institutional_consensus": 0.0,  # placeholder, 调用方填充
        "north_flow": round(north, 4),
        "margin_change": round(margin, 4),
    }
