"""板块/概念/个股 数据源封装: levistock → akshare 多源降级。

每个对外函数都有两条数据链路,一条挂起另一条自动接管,绝不阻塞接口。
"""
from typing import Any

import logging

import levistock as lv

from ..services.cache_service import cached
from ..core.source_registry import registry

_logger = logging.getLogger(__name__)

_TIMEOUT = 10


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _exec(fn, timeout: int = _TIMEOUT):
    """在线程中执行 fn, 超时 / 异常返回 None（P1-2：统一走 safe_call, long 池）。"""
    from ..core.async_utils import safe_call
    return safe_call(fn, timeout=timeout, executor="long")



def _try_two(name_lv, lv_fn, name_ak, ak_fn, default=None):
    """通过 SourceRegistry 熔断路由依次尝试 levistock → akshare。"""
    result = registry.route([
        (name_lv, lambda: _exec(lv_fn, _TIMEOUT)),
        (name_ak, lambda: _exec(ak_fn, _TIMEOUT)),
    ], route_name=name_lv, operation="sector")
    if result:
        return result
    return default if default is not None else []


# ---------------------------------------------------------------------------
# akshare 回退 (在独立线程中执行, 不会阻塞事件循环)
# ---------------------------------------------------------------------------

def _sector_change_pct(v) -> float | None:
    """P2-3/P2-K (round10 §5.1): 板块涨跌幅值域校验——A股板块单日 ±10% 属合法
    （round9 实测 CRO/CMO +10.84%、医疗研发外包 +13.03%）；±20% 外才视为数据源异常
    （避免把真实大涨板块剔出回填 map 导致显示 0）。超界返回 None。"""
    try:
        val = float(v or 0)
    except (TypeError, ValueError):
        return None
    if abs(val) > 20.0:
        return None
    return val


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
                # P2-3: 板块涨跌幅 ±10% 值域校验（超界→None→端点 0 兑底/标数据源异常）
                "change_pct": _sector_change_pct(r.get("涨跌幅", 0)),
                "change_amt": float(r.get("涨跌额", 0) or 0),
                "volume": float(r.get("成交量", 0) or 0),
                "amount": float(r.get("成交额", 0) or 0),
                "amplitude": float(r.get("振幅", 0) or 0),
                "turnover_rate": float(r.get("换手率", 0) or 0),
                "total_market": float(r.get("总市值", 0) or 0),
                "main_inflow": float(r.get("主力净流入", 0) or 0),
                "lead_stock_name": str(r.get("领涨股票", "") or ""),
                "lead_stock_code": str(r.get("领涨股票代码", "") or ""),
                "lead_stock_chg": _sector_change_pct(r.get("领涨股票涨跌幅", 0)),
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
                # P2-3: 板块涨跌幅 ±10% 值域校验（超界→None）
                "change_pct": _sector_change_pct(r.get("涨跌幅", 0)),
                "change_amt": float(r.get("涨跌额", 0) or 0),
                "volume": float(r.get("成交量", 0) or 0),
                "amount": float(r.get("成交额", 0) or 0),
                "amplitude": float(r.get("振幅", 0) or 0),
                "turnover_rate": float(r.get("换手率", 0) or 0),
                "total_market": float(r.get("总市值", 0) or 0),
                "main_inflow": float(r.get("主力净流入", 0) or 0),
                "lead_stock_name": str(r.get("领涨股票", "") or ""),
                "lead_stock_code": str(r.get("领涨股票代码", "") or ""),
                "lead_stock_chg": _sector_change_pct(r.get("领涨股票涨跌幅", 0)),
                "up_count": int(r.get("上涨家数", 0) or 0),
                "down_count": int(r.get("下跌家数", 0) or 0),
            })
        return out
    except Exception:
        return None


def _ak_concept_sectors_v2():
    """补充数据源: ak.stock_board_concept_name_em() — 返回所有概念板块名称和代码。

    作为 spot 接口的补充，确保不错过任何概念。
    返回格式与 _ak_concept_sectors 兼容但仅含 sector_code / sector_name。
    """
    try:
        import akshare as ak
        import pandas as pd
        df: pd.DataFrame = ak.stock_board_concept_name_em()  # type: ignore
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            out.append({
                "sector_code": str(r.get("概念代码", "") or ""),
                "sector_name": str(r.get("概念名称", "") or ""),
                "price": 0, "change_pct": 0, "change_amt": 0, "volume": 0, "amount": 0,
                "amplitude": 0, "turnover_rate": 0, "total_market": 0, "main_inflow": 0,
                "lead_stock_name": "", "lead_stock_code": "", "lead_stock_chg": 0,
                "up_count": 0, "down_count": 0,
            })
        return out
    except Exception:
        return None


def _ak_sector_stocks(sector_code: str):
    """akshare 板块成分股。

    F1-6: akshare 的 `stock_board_industry_cons_em(symbol=...)` 接收的是
    **板块名称**（如"半导体"）而非板块代码（BK0447）。此前直接传代码 →
    接口静默返回错位数据（半导体板块返回软件股）。修复：先建立
    行业/概念两张表的 代码→名称 映射，把传入代码转成名称再查询。
    """
    try:
        import akshare as ak
        import pandas as pd

        # F1-6: 板块代码 → 名称映射（行业 + 概念）
        name_by_code: dict[str, str] = {}
        for df_fn in (ak.stock_board_industry_name_em, ak.stock_board_concept_name_em):
            try:
                df = df_fn()
                if df is not None and not df.empty:
                    for _, r in df.iterrows():
                        code = str(r.get("板块代码", "") or "")
                        name = str(r.get("板块名称", "") or "")
                        if code and name:
                            name_by_code.setdefault(code, name)
            except Exception:
                continue
        # 传入代码 → 转名称；传入名称 → 原样使用（老调用方兼容）
        query_name = name_by_code.get(str(sector_code), sector_code)

        # 尝试行业板块成分股（用名称查询）
        try:
            df = ak.stock_board_industry_cons_em(symbol=query_name)  # type: ignore
            if df is not None and not df.empty:
                out = []
                for _, r in df.iterrows():
                    out.append({
                        "stock_code": str(r.get("代码", "") or ""),
                        "stock_name": str(r.get("名称", "") or ""),
                    })
                return out
        except Exception:
            pass
        # 降级：概念板块成分股（同样用名称查询）
        df = ak.stock_board_concept_cons_em(symbol=query_name)  # type: ignore
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
    rows = cached(key, lambda: _try_two("sector_lv", _lv, "sector_ak", _ak), "sector_industry")
    return rows[:limit]


def fetch_concept_sectors(limit: int = 150) -> list[dict[str, Any]]:
    """概念板块列表 (levistock 东方财富 → akshare 轮询降级 → akshare 名称补充)。"""
    import logging
    _logger = logging.getLogger(__name__)

    def _lv():
        return lv.sector_em("concept")
    def _ak():
        return _ak_concept_sectors()
    def _ak_v2():
        return _ak_concept_sectors_v2()

    key = "concept_sectors"
    # Try three sources in order: levistock → akshare spot → akshare name (full list)
    rows = cached(key, lambda: _try_two("concept_lv", _lv, "concept_ak", _ak), "sector_concept")

    # If the two-source attempt returned few results, try third source as supplement
    # R71 (round29): 补充分支入缓存（1h TTL）——旧实现 _ak_concept_sectors_v2() 在
    # cached 外每请求必跑（热态 17s，round29 §14.1 R71 实证）。失败返回 [] 同样缓存
    # 1h（不反复重跑慢源）；缓存空列表不制造假数据（主源下次轮询仍可命中补充）。
    if len(rows) < 60:
        _logger.info("[sector_fetcher] only got %d concepts from primary sources, trying _ak_concept_sectors_v2", len(rows))
        extra = cached("concept_sectors_v2",
                       lambda: _ak_concept_sectors_v2() or [],
                       "sector_concept_v2") or []
        if extra:
            existing_codes = {r["sector_code"] for r in rows if r.get("sector_code")}
            for e in extra:
                if e.get("sector_code") and e["sector_code"] not in existing_codes:
                    rows.append(e)
            _logger.info("[sector_fetcher] supplemented with %d extra concepts (total %d)",
                         len(extra) - len(existing_codes), len(rows))

    # 确保热门概念出现在结果中（通过模糊匹配）
    POPULAR_CONCEPTS = [
        "光模块", "CPO", "半导体设备", "半导体", "芯片", "人工智能", "AI",
        "算力", "数据中心", "液冷", "机器人", "低空经济", "新能源",
        "光伏", "储能", "锂电池", "新能源汽车", "智能驾驶", "车路云",
        "央企改革", "国企改革", "中特估", "高股息", "红利",
        "消费电子", "华为", "5G", "6G", "信创", "国产软件",
        "创新药", "生物医药", "医疗器械", "军工", "商业航天",
        "跨境电商", "物业管理", "旅游", "教育", "证券",
    ]
    found_names = {r.get("sector_name", "") for r in rows}
    for pop in POPULAR_CONCEPTS:
        if not any(pop in fn for fn in found_names):
            _logger.info("[sector_fetcher] popular concept '%s' not found in results — appending placeholder", pop)
            rows.append({
                "sector_code": "",
                "sector_name": pop,
                "price": 0, "change_pct": 0, "change_amt": 0, "volume": 0, "amount": 0,
                "amplitude": 0, "turnover_rate": 0, "total_market": 0, "main_inflow": 0,
                "lead_stock_name": "", "lead_stock_code": "", "lead_stock_chg": 0,
                "up_count": 0, "down_count": 0,
            })

    return rows[:limit]


def fetch_sector_stocks(sector_code: str) -> list[dict[str, Any]]:
    """板块成分股。"""
    def _lv():
        return lv.sector_stocks_em(sector_code)
    def _ak():
        return _ak_sector_stocks(sector_code)
    key = f"sector_stocks:{sector_code}"
    return cached(key, lambda: _try_two("sector_stocks_lv", _lv, "sector_stocks_ak", _ak), "sector_stocks")


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
    return cached(key, lambda: _try_two("sector_hist_lv", _lv, "sector_hist_ak", _ak), "sector_history")


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
    return cached(key, lambda: _try_two("all_stocks_lv", _lv, "all_stocks_ak", _ak), "all_stocks")


# ---------------------------------------------------------------------------
# public – 财联社 / 同花顺 独家数据 (无 akshare 替代, 仅 levistock)
# ---------------------------------------------------------------------------

def fetch_sector_industry_cls(limit: int = 80) -> list[dict[str, Any]]:
    """行业板块实时行情 (财联社) — 含主力资金、涨跌家数、首板股信息。"""
    def _p():
        rows = lv.sector_industry_cls() or []
        return rows[:limit]
    return cached("industry_cls", _p, "sector_industry")


def fetch_stock_hot_rank(limit: int = 50) -> list[dict[str, Any]]:
    """A 股热门个股排名 (同花顺)。"""
    def _p():
        return lv.stock_hot_rank_ths(limit)
    return cached("stock_hot_rank", _p, "sector_heat")


def get_stock_industry_map(symbols: list[str]) -> dict[str, str]:
    """批量查询股票代码 → 行业名称映射（Z25 热门个股 sector 补全）。

    数据源: tushare stock_basic（无 key / 失败返回空映射，容错）。
    缓存: 1h（stock_basic）。
    """
    if not symbols:
        return {}
    def _p():
        try:
            from .global_markets_fetcher import fetch_stock_basic
            rows = fetch_stock_basic() or []
            mapping = {
                str(r.get("symbol", "")).strip(): str(r.get("industry", "") or "").strip()
                for r in rows if str(r.get("symbol", "")).strip()
            }
            # R5: 空映射不缓存（返回 None）——避免 tushare 暂时失败时空映射污染 1h，
            # 导致后续真实请求（如 symbol 分析板块注入）拿不到行业归属。
            return mapping if mapping else None
        except Exception:
            return None
    return cached("stock_industry_map", _p, "stock_basic") or {}


def fetch_hot_plates(limit: int = 15) -> list[dict[str, Any]]:
    """热点板块及涨停股 (财联社)。

    Z23: 捕获 levistock 异常，返回空列表而非抛出。
    """
    def _p():
        try:
            rows = lv.get_sector_hot_plates() or []
            return rows[:limit]
        except Exception:
            return []
    return cached("hot_plates", _p, "sector_hot_plates")


def fetch_sector_heat(limit: int = 20) -> list[dict[str, Any]]:
    """板块热度排行 (财联社)。"""
    def _p():
        rows = lv.get_sector_heat() or []
        return rows[:limit]
    return cached("sector_heat", _p, "sector_heat")


def fetch_em_industry_sectors(limit: int | None = None) -> list[dict[str, Any]] | None:
    """round19 P4-① (2026-08-12): push2delay 直连行业板块（绕过 akshare）。

    背景: akshare `stock_board_industry_spot_em` 硬编码 push2.eastmoney.com，
    被 EM 域名级风控断连（实测 8.5s RemoteDisconnected）→ 主路径静默失败、
    回退全面失效的财联社链（sign 失效 + 名称回填命中率 5%）→ 板块热度大量 0。
    push2delay 通道实测可用（历史 1843 行）：pn 分页循环（pz=200 服务端实回
    100，拉到 <100 为止，共 300 个行业板块）拉全，f3 涨跌幅真实。

    输出字段与 _ak_industry_sectors 兼容（sector_code/sector_name/change_pct/
    amount/main_inflow/total_market）；clist 无领涨股字段 → 降级空（与财联社
    回退路径一致）。失败返回 None（调用方走 akshare 兜底）；网络错误打 ERROR
    日志（不再静默吞异常）。
    """
    def _p():
        import json as _json
        import urllib.request
        from ..core.market_context import EM_PUSH_HOST as _EM_HOST
        rows: list[dict[str, Any]] = []
        pn = 1
        while True:
            url = (
                f"https://{_EM_HOST}/api/qt/clist/get?pn={pn}&pz=200&po=1&np=1"
                f"&fltt=2&invt=2&fid=f6&fs=m:90+t:2&fields=f12,f14,f3,f6,f62,f20"
            )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                raw = urllib.request.urlopen(req, timeout=8).read().decode()
                diff = ((_json.loads(raw) or {}).get("data") or {}).get("diff") or []
            except Exception as e:
                _logger.error("[sector_fetcher] fetch_em_industry_sectors pn=%s failed: %s", pn, e)
                break
            if not diff:
                break
            for r in diff:
                rows.append({
                    "sector_code": str(r.get("f12") or ""),
                    "sector_name": str(r.get("f14") or "").strip(),
                    # P2-3: 板块涨跌幅 ±20 值域校验（与 akshare 路径同口径）
                    "change_pct": _sector_change_pct(r.get("f3")),
                    "amount": float(r.get("f6") or 0),
                    "main_inflow": float(r.get("f62") or 0),
                    "total_market": float(r.get("f20") or 0),
                    # clist 无领涨股字段 → 降级空（与财联社回退路径一致）
                    "lead_stock_name": "", "lead_stock_code": "", "lead_stock_chg": None,
                })
            if len(diff) < 100:
                break
            pn += 1
        if limit:
            rows = rows[:limit]
        return rows
    return cached("em_industry_sectors", _p, "sector_heat")


def fetch_em_concept_sectors(limit: int | None = None) -> list[dict[str, Any]] | None:
    """round27 R46: push2delay 直连概念板块（绕过 akshare 硬编码 push2 阻断）。

    与 `fetch_em_industry_sectors` 同源（EM_PUSH_HOST=push2delay），仅 fs 用
    `m:90+t:3`（概念）替代 `m:90+t:2`（行业）。akshare 的
    `stock_board_concept_name_em` 同样硬编码 push2 被 EM 域名级风控断连（实测
    ProxyError），故概念动量也改走本函数。字段与 `fetch_em_industry_sectors` 兼容
    （sector_code/sector_name/change_pct/amount/main_inflow/total_market）。
    失败返回 None（调用方走 akshare 兜底）。
    """
    def _p():
        import json as _json
        import urllib.request
        from ..core.market_context import EM_PUSH_HOST as _EM_HOST
        rows: list[dict[str, Any]] = []
        pn = 1
        while True:
            url = (
                f"https://{_EM_HOST}/api/qt/clist/get?pn={pn}&pz=200&po=1&np=1"
                f"&fltt=2&invt=2&fid=f6&fs=m:90+t:3&fields=f12,f14,f3,f6,f62,f20"
            )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                raw = urllib.request.urlopen(req, timeout=8).read().decode()
                diff = ((_json.loads(raw) or {}).get("data") or {}).get("diff") or []
            except Exception as e:
                _logger.error("[sector_fetcher] fetch_em_concept_sectors pn=%s failed: %s", pn, e)
                break
            if not diff:
                break
            for r in diff:
                rows.append({
                    "sector_code": str(r.get("f12") or ""),
                    "sector_name": str(r.get("f14") or "").strip(),
                    "change_pct": _sector_change_pct(r.get("f3")),
                    "amount": float(r.get("f6") or 0),
                    "main_inflow": float(r.get("f62") or 0),
                    "total_market": float(r.get("f20") or 0),
                    "lead_stock_name": "", "lead_stock_code": "", "lead_stock_chg": None,
                })
            if len(diff) < 100:
                break
            pn += 1
        if limit:
            rows = rows[:limit]
        return rows
    return cached("em_concept_sectors", _p, "sector_heat")


def fetch_sector_heat_em(limit: int = 20) -> list[dict[str, Any]]:
    """P0-17① (round16 3.19 R1): A股板块热度改走东财行业板块 spot（akshare）。

    round19 P4-① (2026-08-12): 主源切 push2delay 直连（fetch_em_industry_sectors，
    绕过 akshare 的 EM 域名级风控断连）——akshare 降至兜底；两者均空才回退
    财联社链（fetch_sector_heat 调用方处理），且任一环节失败打 ERROR 日志
    （不再静默——「修了没修好」无人发现）。

    输出与 fetch_sector_heat 兼容的条目格式
    （rank/name/heat_index/rank_change/is_new/plate_code/change_pct/lead_stocks）。
    失败返回 []（调用方回退财联社 + 名称回填链）。
    """
    def _p():
        rows = fetch_em_industry_sectors() or []
        if not rows:
            _logger.error("[sector_fetcher] fetch_sector_heat_em: push2delay 直连 0 行，尝试 akshare 兜底")
            rows = _ak_industry_sectors() or []
            if not rows:
                _logger.error("[sector_fetcher] fetch_sector_heat_em: push2delay + akshare 均无数据（回退财联社链）")
                return []
        # 按成交额降序作为热度排序（heat_index 语义≈板块活跃度）
        rows_sorted = sorted(rows, key=lambda r: (r.get("amount") or 0), reverse=True)
        out = []
        for i, r in enumerate(rows_sorted[:limit]):
            lead_code = str(r.get("lead_stock_code") or "")
            out.append({
                "rank": i + 1,
                "name": r.get("sector_name", ""),
                "heat_index": round((r.get("amount") or 0) / 1e6, 1),
                "rank_change": 0,
                "is_new": 0,
                "plate_code": str(r.get("sector_code") or ""),
                "change_pct": r.get("change_pct"),
                # P0-18: 领涨股数组（技术分析按钮 + 领涨股列）；clist 无 → 空
                "lead_stocks": [{
                    "symbol": lead_code,
                    "name": str(r.get("lead_stock_name") or ""),
                    "change_pct": r.get("lead_stock_chg"),
                }] if lead_code else [],
            })
        return out
    return cached("sector_heat_em", _p, "sector_heat")


def fetch_em_sector_changes() -> dict[str, float]:
    """东财行业+概念板块涨跌幅映射 {板块名称: 涨跌幅%}（板块热度 change_pct 补充源）。

    财联社板块热度（fetch_sector_heat）无涨跌幅字段 → 热度行涨跌幅恒 0（O19）。
    本函数用东财板块行情（clist/get fs=m:90+t:2 行业 + t:3 概念，f3 涨跌幅）
    按板块名称构建映射，供 sectors/heat 端点回填真实涨跌幅。

    失败返回 {}（调用方保持 0 兜底，不抛错）。走 _cached 60s TTL。
    """
    def _p():
        import json as _json
        import urllib.request
        result: dict[str, float] = {}
        # 主源/降级源统一从 core.market_context 取（R61 门禁：禁止散落 push2delay 硬编码；
        # P2-3: 回填值也过 ±10% 板块值域校验）
        from ..core.market_context import EM_PUSH_HOST as _EM_HOST
        hosts = (_EM_HOST, "push2.eastmoney.com" if "push2delay" in _EM_HOST else "push2delay.eastmoney.com")
        for host in hosts:
            for fs in ("m:90+t:2", "m:90+t:3"):
                url = (
                    f"https://{host}/api/qt/clist/get?pn=1&pz=500&po=1&np=1"
                    f"&fltt=2&invt=2&fid=f3&fs={fs}&fields=f12,f14,f3"
                )
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    raw = urllib.request.urlopen(req, timeout=8).read().decode()
                    diff = ((_json.loads(raw) or {}).get("data") or {}).get("diff") or []
                    for r in diff:
                        name = (r.get("f14") or "").strip()
                        chg = _sector_change_pct(r.get("f3"))
                        if name and chg is not None and name not in result:
                            result[name] = chg
                except Exception as e:
                    _logger.warning("[sector_fetcher] em sector changes fetch failed (%s %s): %s", host, fs, e)
        return result
    return cached("em_sector_changes", _p, "sector_heat")


# round14 P2-AE: 财联社 plate_list 静态 sign（levistock 内部常量，站点仓库无签名逻辑）。
# sign 失效（errno≠0 / 401 / 404）时 fetch_cls_plate_changes 返回 {} → sectors/heat
# 回退东财名称回填（现状），不阻断 heat 展示——见 fetch_cls_plate_changes docstring。
_CLS_SIGN = "ef1ec7886be706a0b722d7e7bf3c0054"


def fetch_cls_plate_changes() -> dict[str, float]:
    """round14 P2-AE: 财联社 plate_list 涨跌幅映射 {plate_code: change_pct%}。

    plate_code 与 sectors/heat 的 rows.plate_code 同源同码（如 cls80424），
    按 code 精确 join 覆盖 20/20（docs/archived/round14 §2.13 实测）——东财名称回填仅
    命中 5/20（民爆/光通信/冰雪产业等东财板块体系无此板块）。

    - change 字段为小数涨跌幅（0.0186 → 1.86%），×100 并过 ±20 值域校验
      （_sector_change_pct，P2-3/P2-K 口径）。
    - sign 失效时返回 {}（调用方回退东财/0 兜底，不阻断）。
    - 120s TTL（ttl_key='sector_heat'，与 fetch_sector_heat 同 key 族）。
    """
    def _p():
        import json as _json
        import urllib.request
        result: dict[str, float] = {}
        for t in ("industry", "concept"):
            url = (
                f"https://www.cls.cn/v3/plate/plate_list?app=CailianpressWeb&os=web"
                f"&sv=7.7.5&sign={_CLS_SIGN}&type={t}&page=1&page_size=500"
            )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                raw = urllib.request.urlopen(req, timeout=8).read().decode("utf-8")
                d = _json.loads(raw)
                if d.get("errno") != 0:
                    _logger.warning(
                        "[sector_fetcher] cls plate_list errno=%s (sign 可能失效), type=%s",
                        d.get("errno"), t,
                    )
                    continue
                data = d.get("data") or {}
                arr = data.get("plate_list") or data.get("list") or []
                for r in arr:
                    code = str(r.get("secu_code") or r.get("plate_code") or "").strip()
                    chg_raw = r.get("change")
                    if chg_raw is None:
                        continue  # 无涨跌幅字段的板块不进入映射（None 不算 0）
                    try:
                        chg = float(chg_raw) * 100
                    except (TypeError, ValueError):
                        continue
                    chg = _sector_change_pct(chg)  # ±20 值域校验
                    if code and chg is not None and code not in result:
                        result[code] = chg
            except Exception as e:
                _logger.warning("[sector_fetcher] cls plate_list fetch failed (%s): %s", t, e)
        return result
    return cached("cls_plate_changes", _p, "sector_heat")


# round14 P2-AK/AN: 东财美股 spot（fs=m:105，含行业 f100 + PE f9）——60s TTL。
# 实测（2026-08-11 探针）：m:105 返回美股个股（含行业字段），akshare
# stock_us_industry_spot_em 方法已不存在——美股热点板块按「个股 spot 行业聚合」
# 接入（与港股 get_hk_hot_plates 同型），美股 PE 取 f9（NVDA=32.98 实测合理）。
_US_SPOT_RICH_TTL = 60.0
_US_SPOT_RICH_CACHE: dict = {"ts": 0.0, "rows": []}


def _to_float(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _clean_industry(raw) -> str:
    """行业名归一（与 hk_hot_fetcher._clean_industry 同逻辑）——空/占位符 → 「其他」。"""
    ind = (raw or "").strip()
    if not ind or ind in ("-", "--", "—", "0", "None", "nan", "N/A"):
        return "其他"
    return ind


def _fetch_us_spot_rich() -> list[dict[str, Any]]:
    """东财美股 spot（m:105 全量，含 industry/pe），60s TTL 共享（板块聚合 + PE 查询）。"""
    import time as _time
    now = _time.time()
    if now - _US_SPOT_RICH_CACHE["ts"] < _US_SPOT_RICH_TTL:
        return _US_SPOT_RICH_CACHE["rows"]
    import json as _json
    import urllib.request
    rows: list[dict[str, Any]] = []
    for host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        url = (
            f"https://{host}/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fltt=2&invt=2"
            f"&fid=f6&fs=m:105&fields=f12,f14,f3,f6,f100,f9"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=8).read().decode("utf-8")
            diff = ((_json.loads(raw) or {}).get("data") or {}).get("diff") or []
            for r in diff:
                rows.append({
                    "symbol": str(r.get("f12", "")).strip(),
                    "name": r.get("f14", ""),
                    "industry": _clean_industry(r.get("f100")),
                    "change_pct": _sector_change_pct(r.get("f3")),
                    "amount": _to_float(r.get("f6")),
                    "pe": r.get("f9"),
                })
            if rows:
                break
        except Exception as e:
            _logger.warning("[sector_fetcher] us spot rich fetch failed (%s): %s", host, e)
    if rows:
        _US_SPOT_RICH_CACHE.update({"ts": now, "rows": rows})
    return rows


def fetch_us_plates(limit: int = 15) -> list[dict[str, Any]]:
    """round14 P2-AK: 美股热点板块——东财美股 spot 按行业聚合涨跌幅/成交额。

    实测结论：akshare stock_us_industry_spot_em 方法已删除，东财 fs=m:105 返回
    美股**个股**（含 f100 行业字段）——接入形态为「个股 spot 按行业聚合」
    （与港股 get_hk_hot_plates 同型）。返回按成交额降序
    [{name, change_pct(加权), amount, stock_count}]。失败返回 []（路由层提示）。
    """
    def _p():
        rows = _fetch_us_spot_rich()
        groups: dict[str, dict] = {}
        for r in rows:
            ind = r.get("industry") or "其他"
            g = groups.setdefault(ind, {"name": ind, "amount": 0.0, "change_sum": 0.0, "stock_count": 0})
            g["amount"] += float(r.get("amount") or 0)
            g["change_sum"] += float(r.get("change_pct") or 0)
            g["stock_count"] += 1
        plates = []
        for g in groups.values():
            n = max(g["stock_count"], 1)
            plates.append({
                "name": g["name"],
                "change_pct": round(g["change_sum"] / n, 2),  # 简单平均涨跌幅
                "amount": round(g["amount"], 2),
                "stock_count": g["stock_count"],
            })
        plates.sort(key=lambda p: -p["amount"])
        return plates[:limit]
    return cached("us_hot_plates", _p, "sector_heat")


def fetch_sector_popular_stocks(plate_code: str) -> list[dict[str, Any]]:
    """板块热门个股 (财联社)。"""
    def _p():
        return lv.get_sector_popular_stocks(plate_code) or []
    key = f"sector_popular:{plate_code}"
    return cached(key, _p, "sector_popular")
