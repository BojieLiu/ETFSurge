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
        import akshare as ak
        df = ak.fund_etf_fund_info_em(fund=symbol)
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
        import akshare as ak
        market = _get_market(symbol)
        df = ak.stock_individual_fund_flow(stock=symbol, market=market)
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


def fetch_hist_avg_volume(symbol: str, days: int = 20) -> dict | None:
    """获取近 N 日历史行情，返回日均成交额、最新 PE/PB。

    返回:
      {"avg_volume_20d": float, "pe_ttm": float | None, "pb": float | None} 或 None
    """
    if not _is_a_stock(symbol):
        return None
    try:
        import akshare as ak
        market = _get_market(symbol)
        # stock_zh_a_hist 返回历史日线，含 成交额、市盈率-动态、市净率
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date="19900101", adjust="")
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
