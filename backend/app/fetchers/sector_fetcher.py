"""板块/概念/个股 数据源封装: levistock → akshare 多源降级。

每个对外函数都有两条数据链路,一条挂起另一条自动接管,绝不阻塞接口。
"""
from typing import Any

import levistock as lv

from ..core.ttl import CACHE_TTL
from ..services.cache_service import sync_memory_cache
from ..services.source_registry import registry

_TRY = ["levistock", "akshare"]
_TIMEOUT = 10


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _exec(fn, timeout: int = _TIMEOUT):
    """在线程中执行 fn, 超时 / 异常返回 None。"""
    from ..core.async_utils import run_in_thread
    return run_in_thread(fn, timeout=timeout)


def _cached(key: str, producer, ttl_key: str = "sector_industry"):
    """统一缓存包装，使用 sync_memory_cache 替代本地 _CACHE。"""
    ttl = CACHE_TTL.get(ttl_key, 60)
    hit = sync_memory_cache.get(key)
    if hit is not None:
        return hit
    data = producer()
    sync_memory_cache.set(key, data, ttl)
    return data


def _try_two(name_lv, lv_fn, name_ak, ak_fn, default=None):
    """通过 SourceRegistry 熔断路由依次尝试 levistock → akshare。"""
    result = registry.route([
        (name_lv, lambda: _exec(lv_fn, _TIMEOUT)),
        (name_ak, lambda: _exec(ak_fn, _TIMEOUT)),
    ])
    if result:
        return result
    return default if default is not None else []


# ---------------------------------------------------------------------------
# akshare 回退 (在独立线程中执行, 不会阻塞事件循环)
# ---------------------------------------------------------------------------

def _ak_industry_sectors():
    try:
        import akshare as ak
        import pandas as pd
        df: pd.DataFrame = ak.stock_board_industry_spot_em()  # type: ignore
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            out.append({
                "sector_code": r.get("板块代码", ""),
                "sector_name": r.get("板块名称", ""),
                "price": float(r.get("最新价", 0) or 0),
                "change_pct": float(r.get("涨跌幅", 0) or 0),
                "change_amt": float(r.get("涨跌额", 0) or 0),
                "volume": float(r.get("成交量", 0) or 0),
                "amount": float(r.get("成交额", 0) or 0),
                "amplitude": float(r.get("振幅", 0) or 0),
                "turnover_rate": float(r.get("换手率", 0) or 0),
                "total_market": float(r.get("总市值", 0) or 0),
                "main_inflow": float(r.get("主力净流入", 0) or 0),
                "lead_stock_name": str(r.get("领涨股票", "") or ""),
                "lead_stock_code": str(r.get("领涨股票代码", "") or ""),
                "lead_stock_chg": float(r.get("领涨股票涨跌幅", 0) or 0),
                "up_count": int(r.get("上涨家数", 0) or 0),
                "down_count": int(r.get("下跌家数", 0) or 0),
            })
        return out
    except Exception:
        return None


def _ak_concept_sectors():
    try:
        import akshare as ak
        import pandas as pd
        df: pd.DataFrame = ak.stock_board_concept_spot_em()  # type: ignore
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            out.append({
                "sector_code": r.get("板块代码", ""),
                "sector_name": r.get("板块名称", ""),
                "price": float(r.get("最新价", 0) or 0),
                "change_pct": float(r.get("涨跌幅", 0) or 0),
                "change_amt": float(r.get("涨跌额", 0) or 0),
                "volume": float(r.get("成交量", 0) or 0),
                "amount": float(r.get("成交额", 0) or 0),
                "amplitude": float(r.get("振幅", 0) or 0),
                "turnover_rate": float(r.get("换手率", 0) or 0),
                "total_market": float(r.get("总市值", 0) or 0),
                "main_inflow": float(r.get("主力净流入", 0) or 0),
                "lead_stock_name": str(r.get("领涨股票", "") or ""),
                "lead_stock_code": str(r.get("领涨股票代码", "") or ""),
                "lead_stock_chg": float(r.get("领涨股票涨跌幅", 0) or 0),
                "up_count": int(r.get("上涨家数", 0) or 0),
                "down_count": int(r.get("下跌家数", 0) or 0),
            })
        return out
    except Exception:
        return None


def _ak_sector_stocks(sector_code: str):
    try:
        import akshare as ak
        # 尝试行业板块成分股
        df = ak.stock_board_industry_cons_em(symbol=sector_code)  # type: ignore
        if df is not None and not df.empty:
            out = []
            for _, r in df.iterrows():
                out.append({
                    "stock_code": str(r.get("代码", "") or ""),
                    "stock_name": str(r.get("名称", "") or ""),
                })
            return out
        # 试概念板块
        df = ak.stock_board_concept_cons_em(symbol=sector_code)  # type: ignore
        if df is not None and not df.empty:
            out = []
            for _, r in df.iterrows():
                out.append({
                    "stock_code": str(r.get("代码", "") or ""),
                    "stock_name": str(r.get("名称", "") or ""),
                })
            return out
        return []
    except Exception:
        return None


def _ak_all_stocks():
    try:
        import akshare as ak
        import pandas as pd
        df: pd.DataFrame = ak.stock_info_a_code_name()  # type: ignore
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            out.append({
                "stock_code": str(r.get("code", "") or ""),
                "stock_name": str(r.get("name", "") or ""),
            })
        return out
    except Exception:
        return None


# ---------------------------------------------------------------------------
# public – 板块列表
# ---------------------------------------------------------------------------

def fetch_industry_sectors(limit: int = 80) -> list[dict[str, Any]]:
    """行业板块列表 (levistock 东方财富 → akshare 轮询降级)。"""
    def _lv():
        return lv.sector_em("industry")
    def _ak():
        return _ak_industry_sectors()
    key = "industry_sectors"
    rows = _cached(key, lambda: _try_two("sector_lv", _lv, "sector_ak", _ak), "sector_industry")
    return rows[:limit]


def fetch_concept_sectors(limit: int = 80) -> list[dict[str, Any]]:
    """概念板块列表 (levistock 东方财富 → akshare 轮询降级)。"""
    def _lv():
        return lv.sector_em("concept")
    def _ak():
        return _ak_concept_sectors()
    key = "concept_sectors"
    rows = _cached(key, lambda: _try_two("concept_lv", _lv, "concept_ak", _ak), "sector_concept")
    return rows[:limit]


def fetch_sector_stocks(sector_code: str) -> list[dict[str, Any]]:
    """板块成分股。"""
    def _lv():
        return lv.sector_stocks_em(sector_code)
    def _ak():
        return _ak_sector_stocks(sector_code)
    key = f"sector_stocks:{sector_code}"
    return _cached(key, lambda: _try_two("sector_stocks_lv", _lv, "sector_stocks_ak", _ak), "sector_stocks")


# ---------------------------------------------------------------------------
# public – 板块历史 K 线 (用于自由分析)
# ---------------------------------------------------------------------------

def fetch_sector_history(sector_code: str) -> list[dict[str, Any]]:
    """板块历史行情 (akshare 东方财富 → levistock)。"""
    def _ak():
        try:
            import akshare as ak
            import pandas as pd
            df: pd.DataFrame = ak.stock_board_industry_hist_em(
                symbol=sector_code, period="daily", start_date="19700101", end_date="20500101", adjust=""
            )  # type: ignore
            if df is not None and not df.empty:
                out = []
                for _, r in df.iterrows():
                    date_val = r.get("日期", "")
                    if hasattr(date_val, "strftime"):
                        date_val = date_val.strftime("%Y-%m-%d")
                    else:
                        date_val = str(date_val)[:10]
                    out.append({
                        "date": date_val,
                        "open": float(r.get("开盘", 0) or 0),
                        "high": float(r.get("最高", 0) or 0),
                        "low": float(r.get("最低", 0) or 0),
                        "close": float(r.get("收盘", 0) or 0),
                        "volume": float(r.get("成交量", 0) or 0),
                        "amount": float(r.get("成交额", 0) or 0),
                    })
                return out
            return []
        except Exception:
            return None
    def _lv():
        # levistock sector k-line not available, fallback to None
        return None
    key = f"sector_hist:{sector_code}"
    return _cached(key, lambda: _try_two("sector_hist_lv", _lv, "sector_hist_ak", _ak), "sector_history")


# ---------------------------------------------------------------------------
# public – 全量 A 股 (用于自由分析搜索)
# ---------------------------------------------------------------------------

def fetch_all_stocks() -> list[dict[str, Any]]:
    """全量 A 股列表。"""
    def _lv():
        return lv.stocks_all_em()
    def _ak():
        return _ak_all_stocks()
    key = "all_stocks"
    return _cached(key, lambda: _try_two("all_stocks_lv", _lv, "all_stocks_ak", _ak), "all_stocks")


# ---------------------------------------------------------------------------
# public – 财联社 / 同花顺 独家数据 (无 akshare 替代, 仅 levistock)
# ---------------------------------------------------------------------------

def fetch_sector_industry_cls(limit: int = 80) -> list[dict[str, Any]]:
    """行业板块实时行情 (财联社) — 含主力资金、涨跌家数、首板股信息。"""
    def _p():
        rows = lv.sector_industry_cls() or []
        return rows[:limit]
    return _cached("industry_cls", _p, "sector_industry")


def fetch_stock_hot_rank(limit: int = 50) -> list[dict[str, Any]]:
    """A 股热门个股排名 (同花顺)。"""
    def _p():
        return lv.stock_hot_rank_ths(limit)
    return _cached("stock_hot_rank", _p, "sector_heat")


def fetch_hot_plates(limit: int = 15) -> list[dict[str, Any]]:
    """热点板块及涨停股 (财联社)。"""
    def _p():
        rows = lv.get_sector_hot_plates() or []
        return rows[:limit]
    return _cached("hot_plates", _p, "sector_hot_plates")


def fetch_sector_heat(limit: int = 20) -> list[dict[str, Any]]:
    """板块热度排行 (财联社)。"""
    def _p():
        rows = lv.get_sector_heat() or []
        return rows[:limit]
    return _cached("sector_heat", _p, "sector_heat")


def fetch_sector_popular_stocks(plate_code: str) -> list[dict[str, Any]]:
    """板块热门个股 (财联社)。"""
    def _p():
        return lv.get_sector_popular_stocks(plate_code) or []
    key = f"sector_popular:{plate_code}"
    return _cached(key, _p, "sector_popular")
