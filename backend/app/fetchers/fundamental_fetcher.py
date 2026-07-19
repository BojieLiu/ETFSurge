"""
ETF 基本面与资金流数据采集 (Fundamental & Money Flow Fetcher)

数据来源：
  - 基金规模/份额：akshare fund_etf_fund_info_em
  - PE/PB：akshare stock_zh_a_hist (日均线, 需要计算)
  - 20日均成交额：akshare stock_zh_a_hist
  - 主力净流入：akshare stock_individual_fund_flow

所有函数在失败时返回 None，绝不抛异常。
"""

from typing import Any

from ..core.async_utils import run_in_thread
from ..utils.decode import decode_df as _decode_df


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
        df = run_in_thread(_p, timeout=8)
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
    try:
        market = _get_market(symbol)
        def _p(sym=symbol, mkt=market):
            import akshare as ak
            return ak.stock_individual_fund_flow(stock=sym, market=mkt)
        df = run_in_thread(_p, timeout=8)
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
    try:
        market = _get_market(symbol)
        def _p(sym=symbol, mkt=market):
            import akshare as ak
            return ak.stock_individual_fund_flow(stock=sym, market=mkt)
        df = run_in_thread(_p, timeout=8)
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
        df = run_in_thread(_p, timeout=8)
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
        df = run_in_thread(_p, timeout=8)
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
