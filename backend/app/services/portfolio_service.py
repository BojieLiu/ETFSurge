from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import asyncio
import logging

logger = logging.getLogger(__name__)

from ..models.portfolio import PortfolioETF
from ..models.schemas import PortfolioETFCreate, PortfolioETFUpdate
from ..fetchers.china_market import fetch_a_stock_batch, fetch_fund_nav, fetch_hk_stock_realtime, fetch_index_realtime
from ..fetchers.global_markets_fetcher import fetch_us_etf_realtime
from ..fetchers.fundamentals_fetcher import fetch_fundamentals
from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news
from ..analysis.indicators import compute_all_indicators
from ..analysis.signal import generate_signal
from ..core.async_utils import run_sync
from .market_service import get_history, get_indices, get_commodities

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
    """公开包装器，将同步 _build_price_map 放入线程池执行。"""
    try:
        return await run_sync(_build_price_map, etfs, timeout=30)
    except (asyncio.TimeoutError, Exception):
        return {}


def _build_price_map(etfs: list[PortfolioETF | dict]) -> dict[str, tuple[float, float]]:
    """批量获取一组持仓的实时价格，返回 {symbol: (price, change_pct)} 映射表。"""
    from ..fetchers.china_market import (
        fetch_a_stock_batch, fetch_fund_nav, fetch_hk_stock_realtime, fetch_index_realtime,
    )

    def _get_attr(e, attr, default=None):
        if isinstance(e, dict):
            return e.get(attr, default)
        return getattr(e, attr, default)

    a_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "A" and _get_attr(e, "symbol", "")[:1] in ("1", "5", "6")]
    hk_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "HK"]
    us_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "US"]
    # 离岸/场外 ETF 按 tracked_index 获取实时行情
    tracked_a = [_get_attr(e, "tracked_index") for e in etfs if _get_attr(e, "tracked_index") and _get_attr(e, "tracked_index", "")[:1] in ("1", "5", "6")]
    a_symbols = a_symbols + tracked_a
    m: dict[str, tuple[float, float]] = {}

    if a_symbols:
        try:
            all_a = fetch_a_stock_batch(a_symbols)
            for item in all_a:
                m[item["symbol"]] = (item["price"], item["change_pct"])
        except Exception:
            pass

    # FIX-07: parallel HK/US quote fetch
    from concurrent.futures import ThreadPoolExecutor, as_completed
    futures = []
    if hk_symbols or us_symbols:
        with ThreadPoolExecutor(max_workers=8) as executor:
            def _fetch_hk(sym):
                try:
                    items = fetch_hk_stock_realtime(sym)
                    if items:
                        return sym, (float(items[0]["price"]), float(items[0]["change_pct"]))
                except Exception:
                    pass
                return sym, None
            def _fetch_us(sym):
                try:
                    data = fetch_us_etf_realtime(sym)
                    if data:
                        return sym, (float(data["price"]), float(data["change_pct"]))
                except Exception:
                    pass
                return sym, None
            if hk_symbols:
                for s in hk_symbols:
                    futures.append(executor.submit(_fetch_hk, s))
            for s in us_symbols:
                futures.append(executor.submit(_fetch_us, s))
            for f in as_completed(futures):
                sym, val = f.result()
                if val is not None:
                    m[sym] = val

    # Also fetch tracked indices for off-exchange funds
    tracked = list({_get_attr(e, "tracked_index") for e in etfs if _get_attr(e, "tracked_index") and _get_attr(e, "tracked_index") not in m})
    if tracked:
        try:
            all_idx = fetch_index_realtime()
            for item in all_idx:
                if item["symbol"] in tracked:
                    m[item["symbol"]] = (item["price"], item["change_pct"])
        except Exception:
            pass
        # Fallback: compute change from NAV if still missing (FIX-07 parallel)
        tracked_missing = [t for t in tracked if t not in m]
        if tracked_missing:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            def _fetch_nav_fallback(sym):
                try:
                    nav_data = fetch_fund_nav(sym)
                    if nav_data:
                        if isinstance(nav_data, tuple) and len(nav_data) >= 1:
                            return sym, (float(nav_data[0]), float(nav_data[1]) if len(nav_data) > 1 else 0.0)
                        elif isinstance(nav_data, dict) and nav_data.get("nav") and nav_data.get("nav_date"):
                            from datetime import datetime, timedelta
                            nav = float(nav_data["nav"])
                            nav_date = datetime.strptime(nav_data["nav_date"], "%Y-%m-%d")
                            if (datetime.now() - nav_date).days <= 3:
                                return sym, (nav, 0.0)
                except Exception:
                    pass
                return sym, None
            nav_futures = []
            with ThreadPoolExecutor(max_workers=min(len(tracked_missing), 4)) as nav_executor:
                for t in tracked_missing:
                    nav_futures.append(nav_executor.submit(_fetch_nav_fallback, t))
                for f in as_completed(nav_futures):
                    sym, val = f.result()
                    if val is not None:
                        m[sym] = val

    # Map tracked_index prices to fund symbols for off-exchange funds
    for e in etfs:
        sym = _get_attr(e, "symbol")
        ti = _get_attr(e, "tracked_index")
        if ti and ti in m and sym not in m:
            m[sym] = m[ti]

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
            sym_task_map = {}
            async def _fetch_all_fundamentals():
                nonlocal sym_task_map
                symbols = [(idx, etfs[idx].symbol) for idx in a_etf_indices]
                futs = [run_sync(fetch_fundamentals, sym, timeout=8) for _, sym in symbols]
                results = await asyncio.gather(*futs, return_exceptions=True)
                sym_task_map = {sym: res for (_, sym), res in zip(symbols, results)}
            try:
                await asyncio.wait_for(_fetch_all_fundamentals(), timeout=10.0)
            except Exception:
                pass
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

    # 市场状态统一从 pool_manager 读取（与设计管线一致，避免双套判定）
    try:
        from ..services.pool_manager import pool_manager
        regime = pool_manager.get_market_regime() or "range_bound"
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

    # LLM 分析（provider timeout 负责，不再额外包裹 asyncio.wait_for）
    try:
        llm_result = await generate_strategy_check_report(
            market_data=market_data,
            factor_breakdowns=factor_breakdowns,
            regime=regime,
            data_quality=data_quality,
        )
    except asyncio.TimeoutError:
        logger.warning("[strategy_check] LLM analysis timed out, returning partial data")
        llm_result = {
            "summary": f"LLM 分析超时（基于 {len(market_data)} 只标的因子数据，未完成深度分析）",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
    except Exception as e:
        logger.warning("[strategy_check] LLM analysis failed: %s", e)
        llm_result = {
            "summary": f"LLM 分析暂不可用（{e}），返回因子数据摘要",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
    
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
    for h in holdings_analysis:
        sym = h.get("symbol", "")
        # P2-4: weight 回填
        if sym and h.get("weight") is None:
            h["weight"] = weight_map.get(sym, 0.0)
        # P2-1: 注入真实因子分到 holdings_analysis
        fb = factor_breakdowns.get(sym, {})
        real_fs = fb.get("factor_scores", {})
        real_sig = fb.get("technical_signal", {})
        if real_fs and isinstance(real_fs, dict) and any(v != 0 for v in real_fs.values()):
            # 用真实因子分覆盖 LLM 编造的因子描述
            top_factors = sorted(real_fs.items(), key=lambda x: -abs(x[1]))[:3]
            factor_str = "；".join(f"{k}: {v:.2f}σ" for k, v in top_factors)
            h["factor_summary"] = f"{factor_str}"
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
    result = {
        "summary": f"{llm_summary}（市态：{regime_label}{sector_text}{quality_summary}）" if llm_summary else f"市态：{regime_label}，{filled_count}/{total_count}只正常{quality_summary}",
        "suggestions": llm_result.get("suggestions", []),
        "holdings_analysis": holdings_analysis,
        "risk_warnings": _combine_risk_warnings(
            llm_result.get("risk_warnings", []),
            _compute_risk_warnings(holdings_analysis, factor_scores, regime),
        ),
        "market_regime": regime,
        "data_quality": {
            "filled_count": filled_count,
            "total_count": total_count,
        },
        "data_confidence": data_confidence,
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


def _combine_risk_warnings(
    llm_warnings: list[dict],
    rule_warnings: list[dict],
) -> list[dict]:
    """合并 LLM 和规则风险警告，确保至少有一条。"""
    combined = llm_warnings + rule_warnings
    if not combined:
        combined = [{"type": "general", "severity": "info",
                      "description": "当前组合风险指标正常，未触发自动警告。"}]
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
    
    从 pool_manager 获取预计算的因子分矩阵传给 compute_all_indicators，
    避免重复计算 RSI/KDJ/MACD。
    """
    from .market_service import get_history
    from ..analysis.indicators import compute_all_indicators
    from ..analysis.signal import generate_signal

    # 复用 pool_manager 的因子分，免去重新计算 RSI/KDJ/MACD
    try:
        from ..services.pool_manager import pool_manager
        factor_matrix = pool_manager.get_factor_matrix()
    except Exception:
        factor_matrix = {}

    results = {}
    hist_data = await asyncio.gather(
        *[get_history(sym, "A") for sym in symbols],
        return_exceptions=True,
    )
    for sym, hist in zip(symbols, hist_data):
        if isinstance(hist, list) and hist:
            try:
                sym_factors = factor_matrix.get(sym, {})
                ind = compute_all_indicators(hist, factor_scores=sym_factors)
                sig = generate_signal(ind)
                ind["signal"] = sig
                results[sym] = ind
            except Exception:
                continue
    return results


async def _detect_regime(symbols: list[str]) -> tuple[dict, list, str]:
    """并行获取 trend + index → detect_market_regime。"""
    from .market_trends import compute_etf_trends, detect_market_regime
    from ..fetchers.china_market import fetch_index_realtime
    
    trends, index_realtime = await asyncio.gather(
        compute_etf_trends(symbols, ("5d", "1m", "3m")),
        asyncio.to_thread(fetch_index_realtime),
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
        elif total_capital > 0 and price > 0 and e.target_weight > 0:
            # No cost basis but capital provided — estimate from target allocation
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
    
    total_cumulative_pnl = total_market_value - total_cost_basis
    total_cumulative_pnl_pct = (total_cumulative_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0
    
        # Build by_type summary: aggregate PnL by portfolio_type
    by_type = {"on_exchange": {"cumulative_pnl": 0.0, "cumulative_pnl_pct": 0.0},
               "off_exchange": {"cumulative_pnl": 0.0, "cumulative_pnl_pct": 0.0}}
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