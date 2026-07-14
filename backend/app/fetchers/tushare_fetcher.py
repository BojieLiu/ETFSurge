from typing import Any

from ..core.logging import get_logger
from ..config import settings

logger = get_logger(__name__)


def _to_ts_code(symbol: str) -> str:
    """APP 代码 -> Tushare ts_code。支持 '600519' / 'sh600519' / '600519.SH'。"""
    s = symbol.strip().upper()
    if s.endswith((".SH", ".SZ")):
        return s
    if s.startswith("SH"):
        return f"{s[2:]}.SH"
    if s.startswith("SZ"):
        return f"{s[2:]}.SZ"
    if s[0] in ("6", "9"):
        return f"{s}.SH"
    if s[0] in ("0", "3"):
        return f"{s}.SZ"
    return f"{s}.SH"


def _pro():
    """惰性获取 Tushare pro 客户端;无 token 或导入失败返回 None。"""
    if not settings.tushare_token:
        logger.warning("[tushare_fetcher] TUSHARE_TOKEN not configured in .env - Tushare data source disabled")
        return None
    try:
        import tushare as ts

        ts.set_token(settings.tushare_token)
        return ts.pro_api()
    except Exception:
        return None


def fetch_daily(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """A 股日线(用于增强分析/回测)。低频、长缓存调用。"""
    pro = _pro()
    if pro is None:
        return []
    try:
        df = pro.daily(ts_code=_to_ts_code(ts_code), start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return []
        return [
            {
                "日期": str(row["trade_date"]),
                "开盘": float(row["open"]),
                "最高": float(row["high"]),
                "最低": float(row["low"]),
                "收盘": float(row["close"]),
                "成交量": float(row["vol"]),
            }
            for _, row in df.iterrows()
        ]
    except Exception:
        return []


def fetch_moneyflow(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """个股主力资金流(增强)。低频、长缓存调用。"""
    pro = _pro()
    if pro is None:
        return []
    try:
        df = pro.moneyflow(ts_code=_to_ts_code(ts_code), start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return []
        return [
            {
                "日期": str(row["trade_date"]),
                "主力净流入": float(row.get("main_net_in", row.get("net_mf_amount", 0)) or 0),
                "主力净占比": float(row.get("main_net_per", 0) or 0),
                "散户净流入": float(row.get("ret_net_in", 0) or 0),
            }
            for _, row in df.iterrows()
        ]
    except Exception:
        return []


def fetch_north_money(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """沪深港通北向资金(增强)。低频、长缓存调用。"""
    pro = _pro()
    if pro is None:
        return []
    try:
        df = pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return []
        return [
            {
                "日期": str(row["trade_date"]),
                "北向净流入": float(row.get("north_money", row.get("hk_s2_north_money", 0)) or 0),
            }
            for _, row in df.iterrows()
        ]
    except Exception:
        return []


def fetch_stock_basic() -> list[dict[str, Any]]:
    """股票基础信息(行业/市场),用于丰富标的元数据。"""
    pro = _pro()
    if pro is None:
        return []
    try:
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,area,industry,market,list_date")
        if df is None or df.empty:
            return []
        return [
            {
                "ts_code": str(row["ts_code"]),
                "symbol": str(row["symbol"]),
                "name": str(row["name"]),
                "industry": str(row.get("industry", "") or ""),
                "market": str(row.get("market", "") or ""),
            }
            for _, row in df.iterrows()
        ]
    except Exception:
        return []
