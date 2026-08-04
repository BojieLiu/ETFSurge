from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# F11 (round6 §15.3): 因子键→中文名映射 + 方向/值域解读。
# 覆盖 factor_registry 全部 34 维核心因子（_BUILTIN_COMPUTERS 键全集）。
# 策略检查持仓明细"因子评分"栏不再裸拼因子代码，输出可读中文。
FACTOR_LABELS: dict[str, str] = {
    # 规模/风格
    "style.size.ln_mcap": "对数市值",
    "style.size.ln_float_mcap": "对数流通市值",
    # 技术面
    "technical.ma.sma_5": "MA5",
    "technical.ma.sma_10": "MA10",
    "technical.ma.sma_20": "MA20",
    "technical.ma.sma_60": "MA60",
    "technical.rsi.rsi_14": "RSI(14)",
    "technical.macd.macd": "MACD",
    "technical.bollinger.bandwidth": "布林带宽",
    "technical.volume.vol_ratio": "量比",
    "technical.volume.vwap": "VWAP",
    "technical.atr.atr_14": "ATR(14)",
    "technical.kdj.k_value": "KDJ.K",
    "technical.kdj.d_value": "KDJ.D",
    "technical.kdj.j_value": "KDJ.J",
    "technical.signal.overall": "综合信号",
    # ETF 基本面
    "etf.amount_stability": "成交额稳定性",
    "etf.change_pct": "涨跌幅",
    "etf.return_1m": "近1月收益",
    "etf.return_3m": "近3月收益",
    "etf.price": "价格",
    "etf.premium_discount": "溢价率",
    "etf.tracking_error": "跟踪误差",
    "etf.shares_change": "份额变化",
    "etf.industry_diversification": "行业分散度",
    "etf.institutional_holdings_change": "机构持仓变化",
    # 情绪
    "sentiment.panic_greed_diff": "恐慌贪婪差",
    "sentiment.stock_divergence": "个股背离",
    "sentiment.news_heat": "新闻热度",
    "sentiment.news_direction": "新闻方向",
    # 政策
    "china.policy.five_year_plan": "十五五规划",
    "china.policy.strategic_emerging": "战略性新兴",
    "china.policy.dual_circulation": "双循环",
}

_RSI_HINT = (
    ("超买", lambda v: v >= 70),
    ("超卖", lambda v: v <= 30),
)
_KDJ_HINT = (
    ("超卖区", lambda v: v < 0),
)


def _factor_hint(code: str, value: float) -> str:
    """按因子键与值域给方向/含义解读；无规则返回空串。"""
    if code == "technical.rsi.rsi_14":
        for label, cond in _RSI_HINT:
            if cond(value):
                return f"（{label}）"
        return "（中性）"
    if code.startswith("technical.kdj.") and value < 0:
        return "（超卖区）"
    if code == "technical.signal.overall":
        if value > 0:
            return "（偏多）"
        if value < 0:
            return "（偏空）"
    if code.startswith("sentiment."):
        return "（情绪因子，正值偏多）" if value > 0 else "（情绪因子，负值偏空）" if value < 0 else ""
    return ""


def format_factor_summary(real_fs: dict[str, float], top_n: int = 3) -> str:
    """F11: 因子分 → 中文解读字符串（保持 factor_summary 字符串契约不变）。

    示例输入: {"technical.rsi.rsi_14": 39.53, "technical.kdj.d_value": -3.46}
    输出: "RSI(14) 39.53（中性）；KDJ.D -3.46（超卖区）"
    """
    if not real_fs:
        return ""
    items = sorted(real_fs.items(), key=lambda x: -abs(x[1]))[:top_n]
    parts = []
    for k, v in items:
        label = FACTOR_LABELS.get(k, k)
        hint = _factor_hint(k, float(v))
        parts.append(f"{label} {v:.2f}{hint}")
    return "；".join(parts)

from ..models.portfolio import PortfolioETF
from ..models.schemas import PortfolioETFCreate, PortfolioETFUpdate
from ..services.market_data_hub import market_data_hub
from ..analysis.indicators import compute_all_indicators
from ..analysis.signal import generate_signal
from ..core.async_utils import run_sync

PORTFOLIO_TYPES = {"on_exchange": "场内", "off_exchange": "场外"}


async def list_etfs(db: AsyncSession, portfolio_type: str | None = None) -> list[PortfolioETF]:
    q = select(PortfolioETF).where(PortfolioETF.is_active == True)
    if portfolio_type:
        q = q.where(PortfolioETF.portfolio_type == portfolio_type)
    result = await db.execute(q)
    return list(result.scalars().all())


async def add_etf(db: AsyncSession, data: PortfolioETFCreate) -> PortfolioETF:
    etf = PortfolioETF(
        symbol=data.symbol,
        name=data.name,
        short_name=data.short_name or data.name,
        asset_type=data.asset_type,
        target_weight=data.target_weight,
        portfolio_type=data.portfolio_type,
        tracked_index=data.tracked_index,
    )
    db.add(etf)
    await db.commit()
    await db.refresh(etf)
    return etf


async def update_etf(db: AsyncSession, symbol: str, data: PortfolioETFUpdate) -> PortfolioETF | None:
    result = await db.execute(select(PortfolioETF).where(
        PortfolioETF.symbol == symbol, PortfolioETF.is_active == True
    ))
    etf = result.scalar_one_or_none()
    if not etf:
        return None
    if data.name is not None:
        etf.name = data.name
    if data.target_weight is not None:
        etf.target_weight = data.target_weight
    if data.is_active is not None:
        etf.is_active = data.is_active
    if data.portfolio_type is not None:
        etf.portfolio_type = data.portfolio_type
    if data.short_name is not None:
        etf.short_name = data.short_name
    if data.tracked_index is not None:
        etf.tracked_index = data.tracked_index
    await db.commit()
    await db.refresh(etf)
    return etf


async def remove_etf(db: AsyncSession, symbol: str) -> bool:
    result = await db.execute(select(PortfolioETF).where(
        PortfolioETF.symbol == symbol, PortfolioETF.is_active == True
    ))
    etf = result.scalar_one_or_none()
    if not etf:
        return False
    etf.is_active = False
    await db.commit()
    return True


async def build_price_map(etfs: list[PortfolioETF | dict]) -> dict[str, tuple[float, float]]:
    """Public wrapper: fetch realtime prices for all holdings concurrently (F8).

    Runs the independent A-share batch, HK, US and index fetches in parallel
    via asyncio.gather + run_sync so a slow source does not block the others.
    """
    try:
        return await _build_price_map_async(etfs)
    except Exception:
        return {}


def _get_etf_attr(e, attr, default=None):
    """Read symbol/asset_type/tracked_index from a PortfolioETF or dict."""
    if isinstance(e, dict):
        return e.get(attr, default)
    return getattr(e, attr, default)


def _split_symbols(etfs):
    a_symbols = [_get_etf_attr(e, "symbol") for e in etfs
                 if _get_etf_attr(e, "asset_type") == "A"
                 and _get_etf_attr(e, "symbol", "")[:1] in ("1", "5", "6")]
    hk_symbols = [_get_etf_attr(e, "symbol") for e in etfs if _get_etf_attr(e, "asset_type") == "HK"]
    us_symbols = [_get_etf_attr(e, "symbol") for e in etfs if _get_etf_attr(e, "asset_type") == "US"]
    tracked_a = [_get_etf_attr(e, "tracked_index") for e in etfs
                 if _get_etf_attr(e, "tracked_index") and _get_etf_attr(e, "tracked_index", "")[:1] in ("1", "5", "6")]
    a_symbols = a_symbols + tracked_a
    return a_symbols, hk_symbols, us_symbols, tracked_a


# F2-1: 组合行情 15s 模块级缓存（与 portfolio:realtime TTL 一致；
# 缓存键 = 四类 symbol 列表；命中时跳过网络拉取，组合计算从 8s 级降至亚秒级）
_PRICE_MAP_CACHE: dict[tuple, tuple[float, dict]] = {}
_PRICE_MAP_TTL = 15.0

# F2-1: A 股 ETF 基本面（pe/pb/规模）同样 15s 缓存——它是 /calculate 8s 主因之一
#（每只 get_fundamentals 最多 8s，20 只并行仍被最慢单只拖到 ~8s）
_FUNDAMENTALS_CACHE: dict[tuple, tuple[float, dict]] = {}


def _clear_price_map_cache() -> None:
    """清空行情缓存（测试与手动刷新用）。"""
    _PRICE_MAP_CACHE.clear()
    _FUNDAMENTALS_CACHE.clear()


async def _build_price_map_async(etfs):
    """Concurrently fetch realtime prices for all holdings (F8 + F2-1)."""
    a_symbols, hk_symbols, us_symbols, tracked_a = _split_symbols(etfs)
    _cache_key = (
        tuple(sorted(a_symbols)),
        tuple(sorted(hk_symbols)),
        tuple(sorted(us_symbols)),
        tuple(sorted(tracked_a)),
    )
    _now = time.monotonic()
    _cached = _PRICE_MAP_CACHE.get(_cache_key)
    if _cached and (_now - _cached[0]) < _PRICE_MAP_TTL:
        return _cached[1]
    m: dict[str, tuple[float, float]] = {}

    async def _a_batch():
        if not a_symbols:
            return []
        # P2-1 (R4-16): 单源超时截断 3s——慢源降级为空并 WARN，不拖累整体
        try:
            return await asyncio.wait_for(
                run_sync(market_data_hub.get_a_stock_batch, a_symbols), timeout=3.0)
        except Exception as e:
            logger.warning("[price_map] A股批量行情超时/失败（3s 截断）: %s", e)
            return []

    async def _hk_batch():
        if not hk_symbols:
            return {}

        async def _one(s):
            try:
                items = await run_sync(market_data_hub.get_hk_stock_realtime, s)
                if items:
                    return s, (float(items[0]["price"]), float(items[0]["change_pct"]))
            except Exception:
                pass
            return s, None

        out = {}
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_one(s) for s in hk_symbols], return_exceptions=True),
                timeout=3.0)
        except Exception as e:
            logger.warning("[price_map] 港股行情超时（3s 截断）: %s", e)
            return out
        for r in results:
            if isinstance(r, tuple) and r[1] is not None:
                out[r[0]] = r[1]
        return out

    async def _us_batch():
        if not us_symbols:
            return {}

        async def _one(s):
            try:
                data = await run_sync(market_data_hub.get_us_etf_realtime, s)
                if data:
                    return s, (float(data["price"]), float(data["change_pct"]))
            except Exception:
                pass
            return s, None

        out = {}
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_one(s) for s in us_symbols], return_exceptions=True),
                timeout=3.0)
        except Exception as e:
            logger.warning("[price_map] 美股行情超时（3s 截断）: %s", e)
            return out
        for r in results:
            if isinstance(r, tuple) and r[1] is not None:
                out[r[0]] = r[1]
        return out

    async def _idx_batch():
        try:
            return {it["symbol"]: (it["price"], it["change_pct"]) for it in await asyncio.wait_for(
                run_sync(market_data_hub.get_index_realtime), timeout=3.0)}
        except Exception as e:
            logger.warning("[price_map] 指数行情超时（3s 截断）: %s", e)
            return {}

    # F8: run independent top-level fetches concurrently (offloaded to threads).
    results = await asyncio.gather(_a_batch(), _hk_batch(), _us_batch(), _idx_batch(),
                                    return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            continue
        if isinstance(res, list):  # A-share batch
            for item in res:
                m[item["symbol"]] = (item["price"], item["change_pct"])
        elif isinstance(res, dict):  # HK / US / index
            m.update(res)

    # NAV fallback for off-exchange tracked indices still missing (parallel).
    tracked = list({_get_etf_attr(e, "tracked_index") for e in etfs
                    if _get_etf_attr(e, "tracked_index") and _get_etf_attr(e, "tracked_index") not in m})
    if tracked:
        async def _nav(s):
            try:
                # P2-1: NAV 单源 3s 截断
                nav = await asyncio.wait_for(
                    run_sync(market_data_hub.get_fund_nav, s), timeout=3.0)
                if nav:
                    if isinstance(nav, tuple) and len(nav) >= 1:
                        return s, (float(nav[0]), float(nav[1]) if len(nav) > 1 else 0.0)
                    elif isinstance(nav, dict) and nav.get("nav") and nav.get("nav_date"):
                        from datetime import datetime
                        nav_v = float(nav["nav"])
                        nav_date = datetime.strptime(nav["nav_date"], "%Y-%m-%d")
                        if (datetime.now() - nav_date).days <= 3:
                            return s, (nav_v, 0.0)
            except Exception:
                pass
            return s, None

        nav_res = await asyncio.gather(*[_nav(t) for t in tracked])
        for s, val in nav_res:
            if val is not None:
                m[s] = val

    # Map tracked_index prices to fund symbols for off-exchange funds
    for e in etfs:
        sym = _get_etf_attr(e, "symbol")
        ti = _get_etf_attr(e, "tracked_index")
        if ti and ti in m and sym not in m:
            m[sym] = m[ti]

    _PRICE_MAP_CACHE[_cache_key] = (time.monotonic(), m)
    return m

async def calculate_allocation(
    db: AsyncSession | None = None,
    total_capital: float = 0.0,
    portfolio_type: str | None = None,
    etfs: list[PortfolioETF] | None = None,
    skip_fundamentals: bool = False,
) -> dict[str, Any]:
    if etfs is None:
        etfs = await list_etfs(db, portfolio_type)
    weight_sum = sum(e.target_weight for e in etfs)
    if weight_sum <= 0:
        return {"total_capital": total_capital, "allocations": []}

    price_map = await build_price_map(etfs)
    allocations = []
    total_amount = 0.0

    # 第一遍：构建不含基本面的 allocation 字典
    for e in etfs:
        target_amount = total_capital * e.target_weight
        total_amount += target_amount
        price, change_pct = price_map.get(e.symbol, (0, 0))
        is_estimated = False
        estimate_source = None
        if e.portfolio_type == "off_exchange" and e.tracked_index:
            _, change_pct = price_map.get(e.tracked_index, (0, 0))
            is_estimated = True
            estimate_source = "tracked_index"

        avg_cost = getattr(e, 'avg_cost', None)
        shares_held = getattr(e, 'shares_held', None)
        cost_basis = round(avg_cost * shares_held, 2) if (avg_cost is not None and shares_held is not None) else None

        allocations.append({
            "symbol": e.symbol,
            "name": e.name,
            "short_name": e.short_name or e.name,
            "asset_type": e.asset_type,
            "portfolio_type": e.portfolio_type,
            "target_weight": e.target_weight,
            "target_amount": round(target_amount, 2),
            "current_price": price,
            "change_pct": change_pct,
            "shares": round(target_amount / price, 2) if price else 0,
            "tracked_index": e.tracked_index,
            "is_estimated": is_estimated,
            "estimate_source": estimate_source,
            "avg_cost": avg_cost,
            "shares_held": shares_held,
            "cost_basis": cost_basis,
            "first_buy_date": getattr(e, 'first_buy_date', None).isoformat() if getattr(e, 'first_buy_date', None) else None,
            "last_trade_date": getattr(e, 'last_trade_date', None).isoformat() if getattr(e, 'last_trade_date', None) else None,
        })

    # 第二遍：并行获取 A 股 ETF 基本面数据（仅当 skip_fundamentals=False）
    if not skip_fundamentals:
        a_etf_indices = [i for i, e in enumerate(etfs) if e.asset_type == "A"]
        if a_etf_indices:
            symbols = [(idx, etfs[idx].symbol) for idx in a_etf_indices]
            _fkey = tuple(sorted(s for _, s in symbols))
            _now = time.monotonic()
            _fcached = _FUNDAMENTALS_CACHE.get(_fkey)
            if _fcached and (_now - _fcached[0]) < _PRICE_MAP_TTL:
                sym_task_map = _fcached[1]
            else:
                sym_task_map = {}
                async def _fetch_all_fundamentals():
                    nonlocal sym_task_map
                    # U5 R1/R2: 单标的 3s 快速失败（数据源 3s 无响应即返回空 dict，
                    # 不占满 8s）+ asyncio.Semaphore(4) 限并发（避免 10 路同打
                    # 同一数据源触发限流）——旧实现 8s×并发 gather + 10s 总预算
                    # 实测 8.2s（某标的 fundamentals 接近超时）
                    _sem = asyncio.Semaphore(4)

                    async def _one(sym: str) -> dict:
                        async with _sem:
                            try:
                                return await asyncio.wait_for(
                                    run_sync(market_data_hub.get_fundamentals, sym, timeout=8),
                                    timeout=3.0,
                                )
                            except (asyncio.TimeoutError, Exception):
                                return {}

                    results = await asyncio.gather(*[_one(sym) for _, sym in symbols])
                    sym_task_map = {sym: res for (_, sym), res in zip(symbols, results)}
                try:
                    await asyncio.wait_for(_fetch_all_fundamentals(), timeout=5.0)
                except Exception:
                    pass
                _FUNDAMENTALS_CACHE[_fkey] = (time.monotonic(), sym_task_map)
            for idx, sym in [(idx, etfs[idx].symbol) for idx in a_etf_indices]:
                result = sym_task_map.get(sym)
                if result and not isinstance(result, Exception):
                    allocations[idx].update(result)

    cash_weight = max(0.0, 1.0 - weight_sum)
    cash_amount = round(total_capital * cash_weight, 2)
    return {
        "total_capital": total_capital,
        "allocations": allocations,
        "total_amount": round(total_amount, 2),
        "cash_weight": cash_weight,
        "cash_amount": cash_amount,
    }


async def calculate_daily_pnl(
    db: AsyncSession | None = None,
    total_capital: float = 0.0,
    portfolio_type: str | None = None,
    etfs: list[PortfolioETF] | None = None,
) -> dict[str, Any]:
    """返回每只基金的当日盈亏和汇总。场外基金使用跟踪指数的涨跌幅作为预估收益。"""
    if etfs is None:
        etfs = await list_etfs(db, portfolio_type)
    allocation = await calculate_allocation(db, total_capital, portfolio_type, etfs, skip_fundamentals=True)
    etf_map = {e.symbol: e for e in etfs}
    etf_map = {e.symbol: e for e in etfs}
    pnl_items = []
    total_pnl = 0.0
    total_amount = 0.0
    weighted_change_sum = 0.0

    for a in allocation["allocations"]:
        e = etf_map.get(a["symbol"])
        price = a["current_price"]
        change_pct = a["change_pct"]
        target_amount = a["target_amount"]
        daily_pnl = target_amount * change_pct / 100.0
        total_pnl += daily_pnl
        total_amount += target_amount
        if target_amount:
            weighted_change_sum += change_pct * target_amount
        pnl_items.append({
            "symbol": a["symbol"],
            "name": a["name"],
            "short_name": a["short_name"],
            "asset_type": a["asset_type"],
            "portfolio_type": a["portfolio_type"],
            "target_amount": target_amount,
            "current_price": price,
            "change_pct": change_pct,
            "daily_pnl": round(daily_pnl, 2),
            "tracked_index": a.get("tracked_index"),
            "is_estimated": a.get("is_estimated", False),
            "estimate_source": a.get("estimate_source"),
            "shares_outstanding": a.get("shares_outstanding"),
            "fund_scale": a.get("fund_scale"),
            "pe_ttm": a.get("pe_ttm"),
            "pb": a.get("pb"),
            "main_net_inflow": a.get("main_net_inflow"),
            "main_net_inflow_pct": a.get("main_net_inflow_pct"),
        })

    weighted_change_pct = (weighted_change_sum / total_amount) if total_amount else 0.0
    return {
        "items": pnl_items,
        "total_pnl": round(total_pnl, 2),
        "total_amount": round(total_amount, 2),
        "weighted_change_pct": round(weighted_change_pct, 2),
    }


import time as _time
_strategy_check_cache: dict[str, tuple[float, dict]] = {}  # key -> (timestamp, result)


def _is_failed_result(factor_scores: dict) -> bool:
    """P0-4: 判断因子结果是否为失败（全部为空或全零）。"""
    if not factor_scores:
        return True
    for sym, scores in factor_scores.items():
        if scores and isinstance(scores, dict) and any(v != 0 for v in scores.values()):
            return False
    return True  # 所有标的因子分全为零或空

def _build_llm_fail_summary(duration_s: float, diag: str) -> str:
    """R6-F13: 策略检查 LLM 失败兜底文案——按诊断内容区分限流/超时/服务端错误。

    旧实现恒写"LLM 分析超时（60s 未返回）"：500 快速失败（10s）时文案误导。
    """
    diag = diag or ""
    low = diag.lower()
    if "限流" in diag or "429" in low:
        reason = "LLM 限流"
    elif "timeout" in low or "timed out" in low or "超时" in diag:
        reason = "LLM 响应超时"
    else:
        reason = "LLM 服务端错误"
    return (
        f"{reason}（{duration_s:.0f}s，已用规则引擎兜底生成建议）"
        f"（最后错误: {diag or '未知'}）"
    )


async def strategy_check(
    db: AsyncSession,
    total_capital: float,
    design_data: dict | None = None,
    portfolio_type: str | None = None,
) -> dict[str, Any]:
    """v2: 因子评分 + regime 感知 + 结构化输出（60s LRU 缓存避免重复采集）。"""
    from ..analysis.llm import generate_strategy_check_report
    from ..factors.factor_registry import registry as factor_registry
    
    # Use design_data if provided, otherwise fall back to DB ETFs
    use_design = False
    if design_data and design_data.get("plans"):
        plan = design_data["plans"][0] if design_data["plans"] else None
        if plan and plan.get("allocations"):
            etfs = []
            for alloc in plan["allocations"]:
                etfs.append({
                    "symbol": alloc.get("symbol"),
                    "name": alloc.get("name", alloc.get("symbol")),
                    "short_name": alloc.get("short_name", alloc.get("symbol")),
                    "asset_type": "ETF",
                    "portfolio_type": "on_exchange",
                    "target_weight": alloc.get("target_weight", 0),
                })
            use_design = True
        else:
            etfs = await list_etfs(db, portfolio_type)
    else:
        etfs = await list_etfs(db, portfolio_type)
    
    if not etfs:
        return {"summary": "组合为空，请先添加ETF或生成组合方案", "suggestions": []}
    
    # Build price map - handle both SQLAlchemy objects and dicts
    def _get_attr(e, attr, default=None):
        if isinstance(e, dict):
            return e.get(attr, default)
        return getattr(e, attr, default)
    
    # 组合持仓计算缓存 key（按 symbol 列表 + capital 去重）
    symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "symbol") != "CASH"]
    cache_key = "_".join(sorted(symbols) if symbols else ["empty"])
    cached = _strategy_check_cache.get(cache_key)
    if cached and _time.monotonic() - cached[0] < 60:
        # P0-4: 失效结果不命中缓存
        if cached[1] and not _is_failed_result(cached[1].get("factor_scores", {})):
            logger.debug("[strategy_check] returning cached result")
            return cached[1]
        else:
            logger.debug("[strategy_check] cache hit but result is failed/stale, re-fetching")
    
    # 并行采集（带 30s 总超时，任一失败不影响整体结果）
    indicators_task = _compute_indicators(symbols)
    factor_task = factor_registry.compute(symbols)

    try:
        indicators, factor_scores = await asyncio.wait_for(
            asyncio.gather(indicators_task, factor_task, return_exceptions=True),
            timeout=30,
        )
    except asyncio.TimeoutError:
        logger.warning("[strategy_check] data collection timed out after 30s, using partial results")
        indicators, factor_scores = {}, {}

    indicators = indicators if isinstance(indicators, dict) else {}
    factor_scores = factor_scores if isinstance(factor_scores, dict) else {}

    # 市场状态统一从 market_data_hub 读取（与设计管线一致，避免双套判定）
    try:
        from ..services.market_data_hub import market_data_hub
        regime = market_data_hub.get_market_regime() or "range_bound"
    except Exception:
        regime = "range_bound"
    trends = {}
    index_realtime = []
    
    # 构建 market_data with allocation info
    price_map = await build_price_map(etfs)
    market_data = []
    factor_breakdowns = {}
    for e in etfs:
        symbol = _get_attr(e, "symbol")
        price, change_pct = price_map.get(symbol, (0, 0))
        target_w = _get_attr(e, "target_weight", 0)
        market_data.append({
            "symbol": symbol, "name": _get_attr(e, "name", symbol),
            "short_name": _get_attr(e, "short_name", symbol),
            "price": price, "change_pct": change_pct,
            "asset_type": _get_attr(e, "asset_type", "ETF"),
            "portfolio_type": _get_attr(e, "portfolio_type", "on_exchange"),
            "target_weight": target_w,
            "target_amount": round(total_capital * target_w, 2),
        })
        
        if symbol != "CASH":
            fb = factor_scores.get(symbol, {}) if isinstance(factor_scores, dict) else {}
            ind = indicators.get(symbol, {})
            sig = ind.get("signal", {}) if isinstance(ind, dict) else {}
            drift = None
            if market_data:
                pass
            factor_breakdowns[symbol] = {
                "factor_scores": fb if isinstance(fb, dict) else {},
                "technical_indicators": ind if isinstance(ind, dict) else {},
                "technical_signal": sig if isinstance(sig, dict) else {"signal": "hold"},
                "weight_drift": drift,
            }
    
    # 统计因子数据质量
    filled_factor_count = sum(
        1 for fb in factor_breakdowns.values()
        if fb.get("factor_scores") and any(v != 0 for v in fb["factor_scores"].values())
    )
    total_factor_count = len(factor_breakdowns)
    data_quality = {
        "filled_count": filled_factor_count,
        "total_count": total_factor_count,
        "all_empty": filled_factor_count == 0,
        "partial": 0 < filled_factor_count < total_factor_count,
    }

    # LLM 分析（Z26: 显式预算，超时走规则引擎兜底）
    # U2 R3: 超时预算 20s → 60s → F9 (round6 §十五 R6-15.1): 60s → 30s——
    # DeepSeek 慢响应（60s 无返回）只能等满 60s，用户等待减半；30s 内无响应
    # 即兜底（R5-1-6 快速失败只覆盖快速 500/429）。
    # F1-9: wait_for 超时会取消内部协程，抛 CancelledError（BaseException），
    # 必须与 TimeoutError 一起捕获，否则 usage 失败记录缺失、规则兜底文案丢失。
    _llm_failed = False
    _llm_start = _time.monotonic()
    _llm_diag = ""
    try:
        llm_result = await asyncio.wait_for(
            generate_strategy_check_report(
                market_data=market_data,
                factor_breakdowns=factor_breakdowns,
                regime=regime,
                data_quality=data_quality,
            ),
            timeout=30,  # F9 (round6 §十五): 60s → 30s，慢响应快速兜底
        )
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        _llm_failed = True
        _llm_dur = _time.monotonic() - _llm_start
        # R5-1-6: 取 LLM 层最后失败诊断（区分限流/超时），供 summary 展示
        try:
            from ..analysis.llm import get_last_llm_error
            _llm_diag = get_last_llm_error() or ""
        except Exception:
            _llm_diag = ""
        logger.warning(
            "[strategy_check] LLM analysis timed out/cancelled after %.1fs (%s), using rule fallback. last_error=%s",
            _llm_dur, type(e).__name__, _llm_diag,
        )
        # F1-9: 失败留痕 — 写 usage 失败记录（成功路径由 llm.py 写入）
        try:
            from ..monitor.token_usage import token_store, UsageRecord
            await token_store.record(UsageRecord(
                function_name="generate_strategy_check_report",
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                model="", timestamp=_time.time(), success=False,
                duration_ms=round(_llm_dur * 1000, 1),
                error_message=f"wait_for timeout ({type(e).__name__})",
                provider="",
            ))
        except Exception as _ue:
            logger.debug("[strategy_check] usage record failed (non-fatal): %s", _ue)
        llm_result = {
            # R6-F13 (round6 §十五 R6-15): 文案区分限流/超时/快速失败——与
            # get_last_llm_error 一致（旧模板恒写"超时 60s"，500 快速失败时误导）
            "summary": _build_llm_fail_summary(_llm_dur, _llm_diag),
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
    except Exception as e:
        _llm_failed = True
        logger.warning("[strategy_check] LLM analysis failed: %s", e)
        llm_result = {
            "summary": f"LLM 分析暂不可用（{e}），返回因子数据摘要",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }

    # F1-9 兜底识别：llm.py 内部捕获 CancelledError 返回兜底结构（wait_for 不抛异常），
    # 此时 summary 以"LLM 分析超时"开头——同样视为 LLM 失败（风险兜底诚实化）
    if not _llm_failed and str(llm_result.get("summary", "")).startswith("LLM 分析超时"):
        _llm_failed = True
    
    # P2-1+P2-2+P2-4: 后处理 — 回填 weight + 真实因子分 + factor_summary
    weight_map: dict[str, float] = {}
    for e in etfs:
        sym = _get_attr(e, "symbol", "")
        if sym and sym != "CASH":
            w = _get_attr(e, "target_weight", None)
            if w is None:
                w = _get_attr(e, "weight", 0)
            weight_map[sym] = float(w) if w else 0.0

    holdings_analysis = llm_result.get("holdings_analysis", [])

    # R5-1-2: rule 兜底路径 holdings_analysis 补全——LLM 超时/失败时
    # holdings_analysis 恒空 → 行业集中度检查静默跳过。用 factor_breakdowns/
    # industry_map 生成骨架（symbol/name/weight/factor_summary/industry），
    # 使行业分布分析在兜底路径也存在（数量级正确，标注"规则引擎生成"）。
    if _llm_failed and not holdings_analysis:
        holdings_analysis = _build_rule_fallback_holdings_analysis(
            etfs=etfs,
            market_data=market_data,
            factor_breakdowns=factor_breakdowns,
            weight_map={},  # 下面 P2-4 会统一回填
        )

    # P0-1 (R4-01): 行业注入——从 market_data_hub 候选池构建 symbol→industry 映射
    # （与设计任务同一来源；候选池条目含 ETFClassifier 产出的 industry 字段）。
    # 仅作数据回填，不参与因子计算；失败时静默（risk_warnings 有空行业保护兜底）。
    industry_map: dict[str, str] = {}
    try:
        from ..services.market_data_hub import market_data_hub as _hub
        _pool = _hub.get_pool()
        _pool_items = _pool.values() if isinstance(_pool, dict) else (_pool or [])
        for _items in _pool_items:
            for _it in _items or []:
                _sym = _it.get("symbol", "")
                _ind = _it.get("industry") or ""
                if _sym and _ind and _ind != "unknown" and _sym not in industry_map:
                    industry_map[_sym] = _ind
        for _sym in (symbols or []):
            if _sym and _sym not in industry_map:
                _entry = _hub.get_by_code(_sym)
                if _entry:
                    _ind = (_entry.get("industry") or "").strip()
                    if _ind and _ind != "unknown":
                        industry_map[_sym] = _ind
        if industry_map:
            logger.debug("[strategy_check] industry map built for %d symbols", len(industry_map))
    except Exception as _e:
        logger.debug("[strategy_check] industry map build failed (non-fatal): %s", _e)

    for h in holdings_analysis:
        sym = h.get("symbol", "")
        # P0-1: 注入 sector/industry（缺失时由 _compute_risk_warnings 空行业保护兜底）
        _ind = industry_map.get(sym, "")
        if _ind:
            h.setdefault("industry", _ind)
            h.setdefault("sector", _ind)
        # P2-4: weight 回填
        if sym and h.get("weight") is None:
            h["weight"] = weight_map.get(sym, 0.0)
        # P2-1: 注入真实因子分到 holdings_analysis
        fb = factor_breakdowns.get(sym, {})
        real_fs = fb.get("factor_scores", {})
        real_sig = fb.get("technical_signal", {})
        if real_fs and isinstance(real_fs, dict) and any(v != 0 for v in real_fs.values()):
            # 用真实因子分覆盖 LLM 编造的因子描述（F11: 中文名+方向解读）
            h["factor_summary"] = format_factor_summary(real_fs)
            # Phase 2.7.7: 注入因子级可用性详情
            filled = sum(1 for v in real_fs.values() if isinstance(v, (int, float)) and abs(v) > 0.01)
            total = len(real_fs)
            h["factor_availability"] = {"filled": filled, "total": total, "ratio": f"{filled}/{total}"}
        elif data_quality and data_quality.get("all_empty"):
            h["factor_availability"] = {"filled": 0, "total": 0, "ratio": "0/0"}
        if real_sig and isinstance(real_sig, dict) and real_sig.get("signal"):
            sig = real_sig["signal"]
            h["tech_signal"] = f"{sig.upper()}，真实信号"

        # FIX-10: 始终基于因子覆盖率计算 confidence，不依赖 LLM source_confidence
        filled_count = data_quality.get("filled_count", 0) if data_quality else 0
        total_count = data_quality.get("total_count", 0) if data_quality else 0
        h["confidence"] = _compute_confidence(filled_count, total_count)

    # P2-3: 增强摘要 — 纳入市态 + 数据质量
    regime_label = {"range_bound": "震荡", "bullish": "偏多", "bearish": "偏空",
                    "volatile": "高波动", "unknown": "待定"}.get(regime, regime)
    unique_sectors = set()
    for e in etfs:
        sym = _get_attr(e, "symbol", "")
        if sym and sym != "CASH":
            fb = factor_breakdowns.get(sym, {})
            sec = fb.get("technical_indicators", {}).get("sector", "")
            if sec:
                unique_sectors.add(sec)
    sector_text = f"，覆盖{len(unique_sectors)}个行业" if unique_sectors else ""

    filled_count = data_quality.get("filled_count", 0) if data_quality else 0
    total_count = data_quality.get("total_count", 0) if data_quality else 0
    quality_summary = f"；因子数据{filled_count}/{total_count}正常" if total_count > 0 else ""

    llm_summary = llm_result.get("summary", "")
    data_confidence = _compute_confidence(filled_count, total_count)

    # ── Z26: 规则引擎兜底 + 覆盖率统计（确保 100% 覆盖） ──────────────
    hold_symbols = [m for m in market_data if m.get("symbol") != "CASH"]
    total_holdings = len(hold_symbols)
    llm_suggestions = llm_result.get("suggestions", []) or []
    for s in llm_suggestions:
        s.setdefault("source", "llm")
        # 契约硬约束: action 仅允许 increase/decrease/hold
        if s.get("action") not in ("increase", "decrease", "hold"):
            s["action"] = "hold"

    covered_symbols = {s.get("symbol") for s in llm_suggestions if s.get("symbol")}
    covered_by_llm = len(covered_symbols)
    rule_suggestions: list[dict] = []
    for m in hold_symbols:
        sym = m.get("symbol")
        if sym in covered_symbols:
            continue
        fb = factor_breakdowns.get(sym, {})
        rule_suggestions.append(_rule_based_suggestion(
            symbol=sym,
            name=m.get("name", sym),
            target_weight=m.get("target_weight", 0),
            factor_score=fb.get("factor_scores", {}),
            signal=fb.get("technical_signal"),
            regime=regime,
        ))
    covered_by_rule = len(rule_suggestions)

    merged_suggestions = llm_suggestions + rule_suggestions
    covered_total = covered_by_llm + covered_by_rule
    coverage_pct = covered_total / total_holdings if total_holdings else 1.0
    if total_holdings and coverage_pct < 1.0:
        logger.error("[strategy_check] coverage < 100%%: %s/%s holdings covered",
                     covered_total, total_holdings)
    coverage = {
        "total_holdings": total_holdings,
        "covered_by_llm": covered_by_llm,
        "covered_by_rule": covered_by_rule,
        "coverage_pct": round(coverage_pct, 4),
    }

    # U2 R1: 风险兜底诚实化（LLM 超时/因子缺失 → warning 级降级标注）
    risk_warnings = _combine_risk_warnings(
        llm_result.get("risk_warnings", []),
        _compute_risk_warnings(holdings_analysis, factor_scores, regime),
        llm_failed=_llm_failed,
        data_all_empty=bool((data_quality or {}).get("all_empty")),
    )

    result = {
        "summary": f"{llm_summary}（市态：{regime_label}{sector_text}{quality_summary}）" if llm_summary else f"市态：{regime_label}，{filled_count}/{total_count}只正常{quality_summary}",
        "suggestions": merged_suggestions,
        "holdings_analysis": holdings_analysis,
        "risk_warnings": risk_warnings,
        # U2 R1: 兜底正文——rule/LLM 建议一律渲染为完整 Markdown 报告
        # （旧实现无 report_text 键 → task 结果 report_text len=0）
        "report_text": _build_rule_fallback_report(
            market_data=market_data,
            factor_breakdowns=factor_breakdowns,
            merged_suggestions=merged_suggestions,
            regime=regime,
            data_quality=data_quality,
            llm_failed=_llm_failed,
            risk_warnings=risk_warnings,
        ),
        "market_regime": regime,
        "data_quality": {
            "filled_count": filled_count,
            "total_count": total_count,
        },
        "data_confidence": data_confidence,
        "coverage": coverage,
        "raw_llm": str(llm_result),
    }
    # 缓存 60s
    if cache_key:
        _strategy_check_cache[cache_key] = (_time.monotonic(), result)
    return result


def _compute_confidence(filled_count: int, total_count: int) -> str:
    """FIX-10: 基于因子数据覆盖率计算置信度（不依赖 LLM source_confidence）。"""
    if total_count <= 0:
        return "low"
    ratio = filled_count / total_count
    if ratio > 0.8:
        return "high"
    elif ratio >= 0.5:
        return "medium"
    return "low"


def _build_rule_fallback_holdings_analysis(
    etfs: list,
    market_data: list[dict],
    factor_breakdowns: dict[str, dict],
    weight_map: dict[str, float],
) -> list[dict]:
    """R5-1-2: rule 兜底路径的 holdings_analysis 骨架生成。

    LLM 超时/失败时 holdings_analysis 恒空 → 行业集中度检查静默跳过（P0-1 收敛）。
    本函数用 market_data + factor_breakdowns 生成逐标的分析骨架：
    symbol/name/weight/factor_summary/industry，标注 "规则引擎生成"。
    后续 P0-1 行业注入 + P2-4 权重回填会统一覆盖/补全字段。
    """
    result: list[dict] = []
    for e in etfs:
        if isinstance(e, dict):
            sym = e.get("symbol")
            name = e.get("name", sym)
        else:
            sym = getattr(e, "symbol", None)
            name = getattr(e, "name", sym)
        if not sym or sym == "CASH":
            continue
        md = next((m for m in market_data if m.get("symbol") == sym), {})
        fb = factor_breakdowns.get(sym, {}) or {}
        fs = fb.get("factor_scores", {}) or {}
        if isinstance(fs, dict) and any(v for v in fs.values()):
            factor_str = format_factor_summary(fs)
        else:
            factor_str = "因子数据不足"
        # industry 占位：P0-1 行业注入会 setdefault 填充真实行业（数据源可用时）
        ind = ""
        if isinstance(fb.get("technical_indicators"), dict):
            ind = (fb["technical_indicators"].get("sector") or "")
        result.append({
            "symbol": sym,
            "name": name or sym,
            "weight": weight_map.get(sym),
            "factor_summary": factor_str,
            "industry": ind,
            "generated_by": "规则引擎生成",
        })
    return result


def _rule_based_suggestion(
    symbol: str,
    name: str,
    target_weight: float,
    factor_score: dict,
    signal: dict | None,
    regime: str,
    current_weight: float | None = None,
) -> dict:
    """Z26: 规则引擎兜底建议 — 基于因子分 + 技术信号 + regime 决策表。

    仅输出 increase/decrease/hold 枚举（契约硬约束），source='rule'，
    confidence 固定 0.7。suggested_weight 调整：
      increase -> min(current * 1.2, 0.30)（单只 ≤30% 风控）
      decrease -> max(current * 0.7, 0.0)
      hold     -> 维持当前权重

    U2 R2 (factor-and-strategy-check-review 问题3 R2): 决策表分档——
      - avg_factor > 0.5 + buy 且非 bearish → increase
      - avg_factor < -0.5 + sell → decrease
      - avg_factor ∈ (0.2, 0.5) + buy → hold（偏多但未达增仓阈值 0.5）
      - 其余 hold，reason 带因子分/信号依据（不再裸"维持现状"）
    """
    fs_vals = [v for v in (factor_score or {}).values()
               if isinstance(v, (int, float)) and v != 0]
    avg_factor = sum(fs_vals) / len(fs_vals) if fs_vals else 0.0
    sig = ""
    if isinstance(signal, dict):
        sig = signal.get("signal", "hold") or "hold"

    bearish = regime in ("bearish", "bear", "bear_market", "defensive")
    cur = current_weight if current_weight is not None else target_weight
    # R4-22: 建议丰富化 — reason 输出 3 句结构化文本（依据/操作/纪律），
    # 保留旧关键词（测试断言兼容：偏离目标权重/未达增仓阈值/因子分/信号）
    _regime_cn = {"range_bound": "震荡", "bullish": "偏多", "bearish": "偏空",
                  "volatile": "高波动", "unknown": "待定"}.get(regime, regime)
    # 相对偏离度：|current - target| / max(target, eps) > 20% → 向 target 回归
    _eps = 1e-9
    if current_weight is not None and abs(current_weight - target_weight) > max(target_weight, _eps) * 0.2:
        if current_weight < target_weight:
            action = "increase"
            reason = (
                f"偏离目标权重（当前 {current_weight:.1%} < 目标 {target_weight:.1%}），建议回归至 {target_weight:.1%}；"
                f"分 2 次加仓、单次加仓不超过目标权重的 20%，避免追高；"
                f"当前市态{_regime_cn}，若跌破 MA20 或市态转空则暂停加仓"
            )
            suggested = min(target_weight, 0.30)
        else:
            action = "decrease"
            reason = (
                f"偏离目标权重（当前 {current_weight:.1%} > 目标 {target_weight:.1%}），建议回归至 {target_weight:.1%}；"
                f"分批减仓、单次减幅不超过当前仓位的 30%，平滑换仓成本；"
                f"若跌破前期支撑位可加速离场，保留现金等待市态企稳"
            )
            suggested = max(target_weight, 0.0)
    # F10 (round6 §十五, 用户已决策): 信号-因子背离分支——技术面与因子分冲突时
    # hold 并解释，禁止裸"信号 X 维持现状"自相矛盾写法（159992 类：SELL + 强正因子）。
    elif sig == "sell" and avg_factor >= 0.5:
        action = "hold"
        reason = (
            f"技术面偏空但因子分强正（{avg_factor:.2f}），信号与因子背离——暂不追空；"
            f"跌破 MA20 或因子分转负再降仓，市态{_regime_cn}下保持纪律"
        )
        suggested = cur
    elif sig == "buy" and avg_factor <= -0.5:
        action = "hold"
        reason = (
            f"技术面偏多但因子分偏弱（{avg_factor:.2f}），信号与因子背离——不追高；"
            f"站上 MA20 且因子分转正再加仓，市态{_regime_cn}下保持纪律"
        )
        suggested = cur
    elif avg_factor > 0.5 and sig == "buy" and not bearish:
        action = "increase"
        reason = (
            f"因子评分优({avg_factor:.2f})、技术面买入信号，基本面与动量共振，建议增仓；"
            f"分 2 次执行、单次加仓不超过目标权重的 20%，留出回调加仓空间；"
            f"若市态转空或跌破 MA20 则暂停加仓，不逆势硬扛"
        )
        suggested = min(cur * 1.2, 0.30)
    elif avg_factor < -0.5 and sig == "sell":
        action = "decrease"
        reason = (
            f"因子评分弱({avg_factor:.2f})+技术卖出信号，趋势转弱，建议减仓；"
            f"分批执行、单次减幅不超过当前仓位的 30%，避免一次性冲击成本；"
            f"若继续破位（跌破 MA60 或前期低点）加速离场，市态{_regime_cn}下优先控制回撤"
        )
        suggested = max(cur * 0.7, 0.0)
    elif avg_factor > 0.2 and sig == "buy":
        action = "hold"
        reason = (
            f"偏多（因子分 {avg_factor:.2f} 未达增仓阈值 0.5），维持现状；"
            f"继续持有观察，若因子分突破 0.5 或放量突破关键阻力位再转增配；"
            f"止损纪律：跌破 MA20 或买入逻辑破坏即减仓一半"
        )
        suggested = cur
    else:
        action = "hold"
        reason = (
            f"因子分 {avg_factor:.2f}（中性区间），信号 {sig or '中性'}，维持现状；"
            f"持有逻辑不变，跟踪因子与信号变化；"
            f"关注 RSI 进入超卖区（<30）或因子转正后的加仓机会，市态{_regime_cn}不追涨杀跌"
        )
        suggested = cur

    return {
        "symbol": symbol,
        "name": name,
        "action": action,
        "current_weight": round(float(cur or 0), 4),
        "suggested_weight": round(float(suggested), 4),
        "reason": reason,
        "confidence": 0.7,
        "source": "rule",
    }


def _build_rule_fallback_report(
    market_data: list[dict],
    factor_breakdowns: dict,
    merged_suggestions: list[dict],
    regime: str,
    data_quality: dict | None,
    llm_failed: bool = False,
    risk_warnings: list[dict] | None = None,
) -> str:
    """U2 R1: 用已生成的 suggestions/factor/risk 渲染结构化 Markdown 正文。

    旧问题：rule 兜底只有 suggestions 数组、report_text 永远为空（task 66
    report_text len=0）——本函数为兜底路径生成完整正文：
    市态结论 → 因子数据质量 → 逐标的因子/信号/建议表 → 风险提示 → 操作建议。
    """
    regime_label = {"range_bound": "震荡", "bullish": "偏多", "bearish": "偏空",
                    "volatile": "高波动", "unknown": "待定"}.get(regime, regime)
    lines: list[str] = []
    lines.append("## 策略检查报告")
    lines.append("")
    lines.append(f"**市态**：{regime_label}")
    if llm_failed:
        lines.append("")
        lines.append("> ⚠️ LLM 分析超时/不可用，以下内容由规则引擎基于因子数据与信号生成。")
    filled = (data_quality or {}).get("filled_count", 0)
    total = (data_quality or {}).get("total_count", 0)
    lines.append("")
    lines.append(f"**因子数据质量**：{filled}/{total} 只持仓因子数据可用。")
    lines.append("")
    lines.append("### 逐标的因子/信号/建议")
    lines.append("| 代码 | 名称 | 因子分 | 信号 | 建议 | 理由 |")
    lines.append("|------|------|--------|------|------|------|")
    for s in merged_suggestions or []:
        sym = s.get("symbol", "")
        fb = factor_breakdowns.get(sym, {}) or {}
        fs = fb.get("factor_scores", {}) or {}
        fs_vals = [v for v in fs.values() if isinstance(v, (int, float)) and v != 0]
        avg = sum(fs_vals) / len(fs_vals) if fs_vals else 0.0
        sig = ((fb.get("technical_signal") or {}).get("signal") or "hold")
        action = s.get("action", "hold")
        reason = (s.get("reason", "") or "").replace("|", "｜")
        lines.append(
            f"| {sym} | {s.get('name', sym)} | {avg:.2f} | {sig} | {action} | {reason} |"
        )
    lines.append("")
    lines.append("### 风险提示")
    warnings = risk_warnings or []
    if warnings:
        for w in warnings:
            sev = w.get("severity", "info")
            desc = (w.get("description", "") or "").replace("|", "｜")
            lines.append(f"- [{sev}] {desc}")
    else:
        lines.append("- 当前组合风险指标正常，未触发自动警告。")
    lines.append("")
    lines.append("### 操作建议")
    if merged_suggestions:
        lines.append("")
        for s in merged_suggestions:
            action = s.get("action", "hold")
            sym = s.get("symbol", "")
            cw = s.get("current_weight", 0)
            sw = s.get("suggested_weight", 0)
            conf = s.get("confidence", "medium")
            reason = (s.get("reason", "") or "").replace("|", "｜")
            lines.append(f"**{sym} {s.get('name', sym)}**：`{action}` {cw:.1%} → {sw:.1%}（置信度 {conf}）")
            # R4-22: reason 为 3 句结构化文本（依据/操作/纪律），分点列出提升可读性
            for part in [p for p in reason.split("；") if p.strip()]:
                lines.append(f"- {part.strip()}")
            lines.append("")
    else:
        lines.append("- 无可操作标的（组合为空）。")
    return "\n".join(lines)


def _combine_risk_warnings(
    llm_warnings: list[dict],
    rule_warnings: list[dict],
    llm_failed: bool = False,
    data_all_empty: bool = False,
) -> list[dict]:
    """合并 LLM 和规则风险警告，确保至少有一条。

    U2 R3 (factor-and-strategy-check-review 问题3 R3): 风险兜底诚实化——
    LLM 超时或因子数据缺失时输出 warning 级降级标注，而非误导性的 info"正常"。
    """
    combined = llm_warnings + rule_warnings
    if not combined:
        if data_all_empty:
            combined = [{"type": "general", "severity": "warning",
                         "description": "因子数据不可用，风险提示完整性受限（基于规则引擎部分数据）。"}]
        elif llm_failed:
            combined = [{"type": "general", "severity": "warning",
                         "description": "LLM 分析超时，风险提示基于规则引擎部分数据，完整性受限。"}]
        else:
            combined = [{"type": "general", "severity": "info",
                          "description": "当前组合风险指标正常，未触发自动警告。"}]
    elif llm_failed:
        # R5-1-2: 骨架生成后 combined 可能非空（行业缺失/超配 warning），
        # LLM 超时标注仍须存在（诚实降级）——前置一条，不依赖 combined 为空。
        if not any("LLM 分析超时" in w.get("description", "") for w in combined):
            combined = [{"type": "general", "severity": "warning",
                         "description": "LLM 分析超时，风险提示基于规则引擎部分数据，完整性受限。"}] + combined
    return combined


def _compute_risk_warnings(
    holdings_analysis: list[dict],
    factor_matrix: dict[str, dict[str, float | int]],
    regime: str,
) -> list[dict]:
    """基于因子数据和持仓分析计算组合风险警告。
    
    独立于 LLM 输出，确保风险 section 不会为空。
    """
    warnings: list[dict] = []
    from collections import defaultdict

    # 1. 行业集中度风险
    sector_weights: dict[str, float] = defaultdict(float)
    for h in holdings_analysis:
        sym = h.get("symbol", "")
        if sym == "CASH":
            continue
        sec = h.get("sector") or h.get("industry", "")
        w = float(h.get("weight", 0) or 0)
        sector_weights[sec] += w

    unique_sectors = len(sector_weights)
    if unique_sectors <= 2 and len(holdings_analysis) > 2:
        blank_weight = sector_weights.get("", 0.0)
        if blank_weight > 0:
            # P0-1 (R4-01): 空行业保护——行业数据缺失（数据源未覆盖）时
            # 降级为 WARN + 显式标注，而非误导性的 HIGH「仅覆盖1个行业」。
            # （旧逻辑把无行业字段的标的全部归入空串行业 → unique_sectors=1 误报）
            warnings.append({
                "type": "concentration",
                "severity": "warning",
                "description": (
                    f"行业集中度提示：行业数据缺失（数据源未覆盖{blank_weight:.0%}权重标的），"
                    "行业分布无法准确评估"
                ),
                "affected_symbols": [
                    h.get("symbol", "") for h in holdings_analysis
                    if not (h.get("sector") or h.get("industry", ""))
                ],
            })
        else:
            top_sector = max(sector_weights, key=sector_weights.get)
            warnings.append({
                "type": "concentration",
                "severity": "high",
                "description": f"行业集中度风险：仅覆盖{unique_sectors}个行业，"
                               f"最大行业{top_sector}占比{sector_weights[top_sector]:.0%}",
                "affected_symbols": [h.get("symbol", "") for h in holdings_analysis if (h.get("sector") or h.get("industry", "")) == top_sector],
            })

    # 2. 单只权重超配风险
    for h in holdings_analysis:
        w = float(h.get("weight", 0) or 0)
        if w >= 0.25:
            sym = h.get("symbol", "")
            name = h.get("name", sym)
            warnings.append({
                "type": "concentration",
                "severity": "medium",
                "description": f"{name}权重{w:.0%}，超过25%建议上限",
                "affected_symbols": [sym],
            })

    # 3. 低流动性风险
    for h in holdings_analysis:
        turnover = float(h.get("turnover_rate", 0) or 0)
        if 0 < turnover < 0.01:
            sym = h.get("symbol", "")
            warnings.append({
                "type": "liquidity",
                "severity": "low",
                "description": f"{h.get('name', sym)}成交量较低",
                "affected_symbols": [sym],
            })

    return warnings


async def _compute_indicators(symbols: list[str]) -> dict:
    """并行计算每只持仓的技术指标 + 信号。

    R6-F5 (round6 §十 R6-06): 与 /market/signal 同口径——纯 K 线计算，不传
    factor_scores（zscore 值会污染信号致两端分歧）。
    """
    from ..analysis.indicators import compute_all_indicators
    from ..analysis.signal import generate_signal
    from ..services.market_data_hub import market_data_hub

    results = {}
    hist_data = await asyncio.gather(
        *[market_data_hub.get_market_history(sym, "A") for sym in symbols],
        return_exceptions=True,
    )
    for sym, hist in zip(symbols, hist_data):
        if isinstance(hist, list) and hist:
            try:
                # R6-F5 (round6 §十 R6-06): 不传 factor_scores——factor_matrix 的
                # zscore 值（如 MACD）会污染信号，与 /market/signal 的纯 K 线口径
                # 产生分歧（518880 策略检查 BUY vs /market/signal hold）。
                ind = compute_all_indicators(hist)
                sig = generate_signal(ind)
                ind["signal"] = sig
                results[sym] = ind
            except Exception:
                continue
    return results


async def _detect_regime(symbols: list[str]) -> tuple[dict, list, str]:
    """并行获取 trend + index → detect_market_regime。"""
    from .market_trends import compute_etf_trends, detect_market_regime
    from ..services.market_data_hub import market_data_hub
    
    trends, index_realtime = await asyncio.gather(
        compute_etf_trends(symbols, ("5d", "1m", "3m")),
        asyncio.to_thread(market_data_hub.get_index_realtime),
        return_exceptions=True,
    )
    trends = trends if isinstance(trends, dict) else {}
    index_realtime = index_realtime if isinstance(index_realtime, list) else []
    
    regime = detect_market_regime(
        trends=trends,
        broad_index_code="510300",
        index_realtime=index_realtime,
    )
    return trends, index_realtime, regime


# 应用策略
async def apply_strategy_suggestions(db: AsyncSession, suggestions: list) -> dict[str, Any]:
    """应用策略建议到持仓"""
    try:
        # 获取所有持仓
        etfs = await list_etfs(db)
        if not etfs:
            return {"symbols": [], "applied_suggestions": suggestions, "message": "无持仓可应用策略"}

        etf_dict = {etf.symbol: etf for etf in etfs}

        applied = []
        for s in suggestions:
            action = s.get("action")
            symbol = s.get("symbol")
            suggested_weight = s.get("suggested_weight", s.get("target_weight", 0))
            if symbol in etf_dict:
                e = etf_dict[symbol]
                if action == "increase" or action == "decrease" or action == "adjust_weight":
                    e.target_weight = max(0, min(0.5, suggested_weight))
                    applied.append({"symbol": symbol, "name": e.name, "target_weight": e.target_weight, "portfolio_type": e.portfolio_type, "action": "updated"})
                elif action == "remove":
                    e.is_active = False
                    applied.append({"symbol": symbol, "name": e.name, "portfolio_type": e.portfolio_type, "action": "removed"})

        await db.commit()
        updated = await list_etfs(db)
        return {"symbols": [{"symbol": e.symbol, "name": e.name, "target_weight": e.target_weight, "portfolio_type": e.portfolio_type} for e in updated], "applied": applied}
    except Exception as e:
        await db.rollback()
        raise e


async def apply_portfolio_design(db: AsyncSession, design: dict) -> dict[str, Any]:
    """根据组合设计应用持仓"""
    try:
        portfolio_type = design.get("portfolio_type", "on_exchange")
        symbols = design.get("symbols", [])
        weights = design.get("weights", {})
        if not symbols:
            return {"symbols": [], "message": "组合设计中没有指定持仓"}

        etfs = await list_etfs(db)
        etf_dict = {e.symbol: e for e in etfs}
        applied = []
        for symbol in symbols:
            w = max(0, min(0.5, weights.get(symbol, 0.1)))
            if symbol in etf_dict:
                e = etf_dict[symbol]
                e.target_weight = w
                e.portfolio_type = portfolio_type
                applied.append({"symbol": symbol, "name": e.name, "target_weight": w, "portfolio_type": portfolio_type, "action": "updated"})
            else:
                new_etf = PortfolioETF(symbol=symbol, name=f"{symbol} ETF", short_name=symbol, asset_type="ETF",
                    target_weight=w, portfolio_type=portfolio_type, tracked_index=None, is_active=True)
                db.add(new_etf)
                applied.append({"symbol": symbol, "name": new_etf.name, "target_weight": w, "portfolio_type": portfolio_type, "action": "added"})

        await db.commit()
        updated = await list_etfs(db)
        return {"symbols": [{"symbol": e.symbol, "name": e.name, "target_weight": e.target_weight, "portfolio_type": e.portfolio_type} for e in updated], "applied": applied}
    except Exception as e:
        await db.rollback()
        raise e


# ── Cumulative P&L History / 累计盈亏历史 ──────────────────────────

async def calculate_cumulative_pnl(
    db: AsyncSession,
    portfolio_type: str | None = None,
    period: str = "all",
    total_capital: float = 0.0,
) -> dict[str, Any]:
    """
    Calculate cumulative P&L based on cost basis and shares held.
    When cost basis data is missing, estimate from target allocation if total_capital is provided.
    """
    etfs = await list_etfs(db, portfolio_type)
    if not etfs:
        return {"summary": {}, "holdings": [], "daily_series": []}
    
    price_map = await build_price_map(etfs)
    
    holdings_pnl = []
    total_cost_basis = 0.0
    total_market_value = 0.0
    has_real_data = False
    # R65: 估算成本累计（估算占比 = estimated_cost_basis / total_cost_basis）
    estimated_cost_basis = 0.0
    est_cost_by_type = {"on_exchange": 0.0, "off_exchange": 0.0}
    
    for e in etfs:
        price, _ = price_map.get(e.symbol, (0.0, 0.0))
        
        # Only calculate if we have cost basis data
        if e.avg_cost is not None and e.shares_held is not None and e.shares_held > 0:
            cost_basis = e.cost_basis or (e.avg_cost * e.shares_held)
            market_value = e.shares_held * price
            cumulative_pnl = market_value - cost_basis
            cumulative_pnl_pct = (cumulative_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
            has_real_data = True
            
            total_cost_basis += cost_basis
            total_market_value += market_value
            
            holdings_pnl.append({
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "portfolio_type": e.portfolio_type,
                "shares_held": e.shares_held,
                "avg_cost": e.avg_cost,
                "cost_basis": round(cost_basis, 2),
                "current_price": price,
                "market_value": round(market_value, 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "cumulative_pnl_pct": round(cumulative_pnl_pct, 2),
                "first_buy_date": e.first_buy_date.isoformat() if e.first_buy_date else None,
                "last_trade_date": e.last_trade_date.isoformat() if e.last_trade_date else None,
                "estimated": False,
            })
        elif e.avg_cost is not None and total_capital > 0 and e.target_weight > 0:
            # R64: 有 avg_cost 但无份额——按目标权重估算份额，成本用用户录入的 avg_cost
            # （旧逻辑用 current price 当成本 → 累计盈亏恒为 0、成本价零贡献）
            target_amount = total_capital * e.target_weight
            pt = e.portfolio_type or ""
            if pt == "off_exchange":
                # P1-6 (R4-21): 场外累计盈亏口径修复——联接基金不再混用
                # 「场内 ETF 实时价折算份额」与「联接基金净值成本」（两者量级差
                # 2-5 倍：半导体联接C avg_cost=3.534 vs 场内 0.67，成本被错误放大）。
                # 唯一口径：份额按联接净值折算 → 成本=投入本金；市值按跟踪指数
                # 涨跌幅估算（场内对应 ETF change_pct 作代理）；无涨跌幅时降级
                # market_value=本金（盈亏 0，标注「净值变动暂缺」）。
                if e.avg_cost > 0:
                    est_shares = target_amount / e.avg_cost
                    cost_basis = target_amount
                    _, change_pct = price_map.get(e.symbol, (0.0, 0.0))
                    has_chg = isinstance(change_pct, (int, float)) and abs(change_pct) > 1e-9
                    market_value = target_amount * (1 + change_pct / 100.0) if has_chg else target_amount
                    cumulative_pnl = market_value - cost_basis
                    cumulative_pnl_pct = (cumulative_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
                    estimate_note = "" if has_chg else "净值变动暂缺"
                    # 019633 avg_cost=3.534 经用户确认为真实申购成本（a94c0af 决策）
                    # ——非录入错误，无需 WARN 提示核对；新口径（联接净值折算）下
                    # 单只盈亏率即真实语义。
                else:
                    # avg_cost 异常（<=0）→ 无法按净值折算，降级按本金估算（盈亏 0）
                    est_shares = 0.0
                    cost_basis = target_amount
                    market_value = target_amount
                    cumulative_pnl = 0.0
                    cumulative_pnl_pct = 0.0
                    estimate_note = "净值变动暂缺"
            elif price > 0:
                # on_exchange：场内价与场内 avg_cost 同单位，无错配（保持原口径）
                est_shares = target_amount / price
                cost_basis = est_shares * e.avg_cost
                market_value = est_shares * price
                cumulative_pnl = market_value - cost_basis
                cumulative_pnl_pct = (cumulative_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
                estimate_note = ""
            else:
                # R67⑤: on_exchange 且 price=0 → 无法估算，但仍计入 has_real_data
                has_real_data = True
                continue
            has_real_data = True
            estimated_cost_basis += cost_basis
            if pt in est_cost_by_type:
                est_cost_by_type[pt] += cost_basis

            total_cost_basis += cost_basis
            total_market_value += market_value

            holdings_pnl.append({
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "portfolio_type": e.portfolio_type,
                "shares_held": round(est_shares, 2),
                "avg_cost": e.avg_cost,
                "cost_basis": round(cost_basis, 2),
                "current_price": price,
                "market_value": round(market_value, 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "cumulative_pnl_pct": round(cumulative_pnl_pct, 2),
                "first_buy_date": getattr(e, 'first_buy_date', None).isoformat() if getattr(e, 'first_buy_date', None) else None,
                "last_trade_date": getattr(e, 'last_trade_date', None).isoformat() if getattr(e, 'last_trade_date', None) else None,
                "estimated": True,
                "estimate_note": estimate_note,
            })
        elif total_capital > 0 and price > 0 and e.target_weight > 0:
            # 无 avg_cost——旧估算逻辑（price 当成本，PnL 从 0 起，不置 has_real_data）
            est_shares = (total_capital * e.target_weight) / price
            # Use current price as estimated avg cost (cumulative PnL starts at 0)
            cost_basis = est_shares * price
            market_value = est_shares * price
            cumulative_pnl = 0.0
            cumulative_pnl_pct = 0.0

            total_cost_basis += cost_basis
            total_market_value += market_value

            holdings_pnl.append({
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "portfolio_type": e.portfolio_type,
                "shares_held": round(est_shares, 2),
                "avg_cost": price,
                "cost_basis": round(cost_basis, 2),
                "current_price": price,
                "market_value": round(market_value, 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "cumulative_pnl_pct": round(cumulative_pnl_pct, 2),
                "first_buy_date": getattr(e, 'first_buy_date', None).isoformat() if getattr(e, 'first_buy_date', None) else None,
                "last_trade_date": getattr(e, 'last_trade_date', None).isoformat() if getattr(e, 'last_trade_date', None) else None,
                "estimated": True,
            })
        elif e.avg_cost is not None:
            # R67⑤: 有 avg_cost 但无法估算（capital/price/weight 任一为 0）→
            # 跳过估算但仍计入 has_real_data（前端据此显示盈亏区而非"需输入成本"）
            has_real_data = True
    
    total_cumulative_pnl = total_market_value - total_cost_basis
    total_cumulative_pnl_pct = (total_cumulative_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0
    
        # Build by_type summary: aggregate PnL by portfolio_type
    by_type = {"on_exchange": {"cumulative_pnl": 0.0, "cumulative_pnl_pct": 0.0,
                                "estimated_cost_basis": 0.0, "estimated_ratio": 0.0},
               "off_exchange": {"cumulative_pnl": 0.0, "cumulative_pnl_pct": 0.0,
                                "estimated_cost_basis": 0.0, "estimated_ratio": 0.0}}
    on_cost = 0.0
    off_cost = 0.0
    for h in holdings_pnl:
        pt = h.get("portfolio_type", "")
        pnl = h.get("cumulative_pnl", 0.0)
        cost = h.get("cost_basis", 0.0) or 0.0
        if pt == "on_exchange":
            by_type["on_exchange"]["cumulative_pnl"] += pnl
            on_cost += cost
        elif pt == "off_exchange":
            by_type["off_exchange"]["cumulative_pnl"] += pnl
            off_cost += cost
    by_type["on_exchange"]["cumulative_pnl_pct"] = round((by_type["on_exchange"]["cumulative_pnl"] / on_cost * 100), 2) if on_cost > 0 else 0.0
    by_type["off_exchange"]["cumulative_pnl_pct"] = round((by_type["off_exchange"]["cumulative_pnl"] / off_cost * 100), 2) if off_cost > 0 else 0.0
    # R65: by_type 估算占比（estimated_cost_basis / total_cost_basis）
    by_type["on_exchange"]["estimated_cost_basis"] = round(est_cost_by_type["on_exchange"], 2)
    by_type["on_exchange"]["estimated_ratio"] = round(est_cost_by_type["on_exchange"] / on_cost, 4) if on_cost > 0 else 0.0
    by_type["off_exchange"]["estimated_cost_basis"] = round(est_cost_by_type["off_exchange"], 2)
    by_type["off_exchange"]["estimated_ratio"] = round(est_cost_by_type["off_exchange"] / off_cost, 4) if off_cost > 0 else 0.0

    daily_series = []
    
    return {
        "summary": {
            "total_cost_basis": round(total_cost_basis, 2),
            "total_market_value": round(total_market_value, 2),
            "total_cumulative_pnl": round(total_cumulative_pnl, 2),
            "total_cumulative_pnl_pct": round(total_cumulative_pnl_pct, 2),
            "annualized_return": None,
            "max_drawdown": None,
            "sharpe_ratio": None,
            "has_cost_basis_data": has_real_data,
            # R65: 估算占比——前端据此显示"含估算成本"提示
            "estimated_cost_basis": round(estimated_cost_basis, 2),
            "estimated_ratio": round(estimated_cost_basis / total_cost_basis, 4) if total_cost_basis > 0 else 0.0,
            "by_type": by_type,
        },
        "holdings": holdings_pnl,
        "daily_series": daily_series,
    }


# ── Portfolio Export / Import / 组合导出导入 ──────────────────────────

async def export_portfolio(
    db: AsyncSession,
    portfolio_type: str | None = None,
    format: str = "csv",
) -> str | list[dict]:
    """
    Export portfolio holdings to CSV or JSON format.
    """
    etfs = await list_etfs(db, portfolio_type)
    
    if format == "json":
        return [
            {
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "portfolio_type": e.portfolio_type,
                "target_weight": e.target_weight,
                "tracked_index": e.tracked_index,
                "avg_cost": e.avg_cost,
                "shares_held": e.shares_held,
                "cost_basis": e.cost_basis,
                "first_buy_date": e.first_buy_date.isoformat() if e.first_buy_date else None,
                "last_trade_date": e.last_trade_date.isoformat() if e.last_trade_date else None,
            }
            for e in etfs
        ]
    
    # CSV format
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "symbol", "name", "short_name", "asset_type", "portfolio_type",
        "target_weight", "tracked_index", "avg_cost", "shares_held",
        "cost_basis", "first_buy_date", "last_trade_date"
    ])
    
    for e in etfs:
        writer.writerow([
            e.symbol,
            e.name,
            e.short_name or "",
            e.asset_type,
            e.portfolio_type,
            e.target_weight,
            e.tracked_index or "",
            e.avg_cost if e.avg_cost is not None else "",
            e.shares_held if e.shares_held is not None else "",
            e.cost_basis if e.cost_basis is not None else "",
            e.first_buy_date.isoformat() if e.first_buy_date else "",
            e.last_trade_date.isoformat() if e.last_trade_date else "",
        ])
    
    return output.getvalue()


async def import_portfolio(
    db: AsyncSession,
    csv_content: str,
    portfolio_type: str = "on_exchange",
    mode: str = "merge",
    skip_invalid: bool = True,
) -> dict[str, Any]:
    """
    Import portfolio holdings from CSV content.
    """
    import csv
    import io
    from datetime import date
    
    reader = csv.DictReader(io.StringIO(csv_content))
    required_fields = {"symbol", "name", "asset_type", "portfolio_type"}
    
    # Check headers
    headers = reader.fieldnames or []
    missing = required_fields - set(headers)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
    imported = 0
    skipped = 0
    errors = []
    holdings = []
    
    for row_num, row in enumerate(reader, start=2):  # 1-based, +1 for header
        try:
            # Validate required fields
            if not row.get("symbol") or not row.get("name"):
                raise ValueError("Missing required field: symbol or name")
            
            symbol = row["symbol"].strip()
            name = row["name"].strip()
            asset_type = row.get("asset_type", "ETF").strip()
            pt = row.get("portfolio_type", portfolio_type).strip()
            short_name = row.get("short_name") or name
            tracked_index = row.get("tracked_index") or None
            
            # Parse numeric fields
            target_weight = float(row["target_weight"]) if row.get("target_weight") else 0.1
            avg_cost = float(row["avg_cost"]) if row.get("avg_cost") else None
            shares_held = float(row["shares_held"]) if row.get("shares_held") else None
            first_buy_date = None
            last_trade_date = None
            
            if row.get("first_buy_date"):
                try:
                    first_buy_date = date.fromisoformat(row["first_buy_date"])
                except ValueError:
                    pass
            if row.get("last_trade_date"):
                try:
                    last_trade_date = date.fromisoformat(row["last_trade_date"])
                except ValueError:
                    pass
            
            if mode == "replace" and imported == 0:
                # Soft delete all existing of this type
                existing = await list_etfs(db, pt)
                for e in existing:
                    e.is_active = False
            
            # Upsert
            existing_etfs = await list_etfs(db, pt)
            existing_dict = {e.symbol: e for e in existing_etfs}
            
            if symbol in existing_dict:
                e = existing_dict[symbol]
                e.name = name
                e.short_name = short_name
                e.asset_type = asset_type
                e.target_weight = target_weight
                e.tracked_index = tracked_index
                e.avg_cost = avg_cost
                e.shares_held = shares_held
                e.first_buy_date = first_buy_date
                e.last_trade_date = last_trade_date
                e.is_active = True
            else:
                e = PortfolioETF(
                    symbol=symbol,
                    name=name,
                    short_name=short_name,
                    asset_type=asset_type,
                    target_weight=target_weight,
                    portfolio_type=pt,
                    tracked_index=tracked_index,
                    avg_cost=avg_cost,
                    shares_held=shares_held,
                    first_buy_date=first_buy_date,
                    last_trade_date=last_trade_date,
                    is_active=True,
                )
                db.add(e)
            
            await db.flush()
            
            holdings.append({
                "id": e.id,
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "target_weight": e.target_weight,
                "portfolio_type": e.portfolio_type,
                "tracked_index": e.tracked_index,
                "avg_cost": e.avg_cost,
                "shares_held": e.shares_held,
                "first_buy_date": e.first_buy_date.isoformat() if e.first_buy_date else None,
                "last_trade_date": e.last_trade_date.isoformat() if e.last_trade_date else None,
                "is_active": e.is_active,
            })
            imported += 1
            
        except Exception as exc:
            skipped += 1
            errors.append({
                "row": row_num,
                "symbol": row.get("symbol", "UNKNOWN"),
                "error": str(exc)
            })
            if not skip_invalid:
                await db.rollback()
                raise
    
    await db.commit()
    
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "holdings": holdings,
    }


# ── Weight Drift Check / 权重偏离检查 ────────────────────────────────

async def calculate_weight_drift(
    db: AsyncSession,
    portfolio_type: str | None = None,
) -> dict[str, Any]:
    """
    Calculate actual vs target weight deviation for each holding.
    """
    etfs = await list_etfs(db, portfolio_type)
    if not etfs:
        return {"items": [], "alerts": []}
    
    price_map = await build_price_map(etfs)
    
    # Calculate total portfolio value
    total_value = 0.0
    for e in etfs:
        price, _ = price_map.get(e.symbol, (0.0, 0.0))
        if e.shares_held and e.shares_held > 0:
            total_value += e.shares_held * price
        else:
            # Use target_amount as fallback
            total_value += total_value * e.target_weight if total_value > 0 else 0
    
    items = []
    alerts = []
    
    for e in etfs:
        price, change_pct = price_map.get(e.symbol, (0.0, 0.0))
        shares = e.shares_held or 0
        market_value = shares * price
        actual_weight = (market_value / total_value) if total_value > 0 else 0
        target_weight = e.target_weight
        deviation = actual_weight - target_weight
        deviation_pct = (deviation / target_weight * 100) if target_weight > 0 else 0
        
        item = {
            "symbol": e.symbol,
            "name": e.name,
            "target_weight": target_weight,
            "actual_weight": round(actual_weight, 4),
            "deviation": round(deviation, 4),
            "deviation_pct": round(deviation_pct, 2),
            "market_value": round(market_value, 2),
            "needs_rebalance": abs(deviation_pct) > 20,  # Alert threshold: 20%
        }
        items.append(item)
        
        if abs(deviation_pct) > 20:
            alerts.append({
                "symbol": e.symbol,
                "name": e.name,
                "message": f"权重偏离 {deviation_pct:.1f}% (目标 {target_weight:.1%}, 实际 {actual_weight:.1%})",
                "severity": "warning" if abs(deviation_pct) < 50 else "critical",
            })
    
    return {"items": items, "alerts": alerts}