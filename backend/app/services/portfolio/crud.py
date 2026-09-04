"""Portfolio ETF CRUD — split from portfolio_service (Batch 1)."""

import logging
import sys as _sys

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import PortfolioETF
from app.models.schemas import PortfolioETFCreate, PortfolioETFUpdate
from app.services.portfolio._facade_refs import (
    _fetch_realtime_price,
    build_price_map,
    recompute_cost_after_trade,
)
from app.services.portfolio.pricing import normalize_asset_type

logger = logging.getLogger(__name__)


def _facade():
    """Late-bound reference to the facade module (keeps mock.patch semantics)."""
    m = _sys.modules.get("app.services.portfolio_service")
    if m is None:
        from app.services import portfolio_service as m
        _sys.modules["app.services.portfolio_service"] = m
    return m




async def list_etfs(db: AsyncSession, portfolio_type: str | None = None) -> list[PortfolioETF]:
    q = select(PortfolioETF).where(PortfolioETF.is_active.is_(True))
    if portfolio_type:
        q = q.where(PortfolioETF.portfolio_type == portfolio_type)
    result = await db.execute(q)
    return list(result.scalars().all())


async def add_etf(db: AsyncSession, data: PortfolioETFCreate) -> PortfolioETF:
    # P0-14① (round16 3.15 R1): 场内 ETF 添加时补 tracked_index——前端不传 → 旧实现
    # 恒 None，持仓表「跟踪指数」列场内全空。从候选池 _by_code + ETF 基座缓存兜底查真实指数名。
    _tidx = data.tracked_index
    if not _tidx and (data.asset_type or "").upper() in ("ETF", "A", "A-SHARE", ""):
        _tidx = _resolve_tracked_index(str(data.symbol))
    # F15 (round23 §3.3): 孤立 avg_cost 拦截——「有成本无份额」是导入/落库脏数据
    #（verify_e2e 曾实锤 20 条半成本持仓），shares_held 缺失/≤0 时强制 avg_cost=None。
    _shares = data.shares_held or 0
    _avg_cost = data.avg_cost if _shares > 0 else None
    etf = PortfolioETF(
        symbol=data.symbol,
        name=data.name,
        short_name=data.short_name or data.name,
        # R176 (round52 §7.3 方案E-1): 写入归一（'ETF'/'A-SHARE' → 'A'）——
        # 与消费侧 _split_symbols / allocation 基本面分支口径一致。
        asset_type=normalize_asset_type(data.asset_type),
        target_weight=data.target_weight,
        portfolio_type=data.portfolio_type,
        tracked_index=_tidx,
        # round19 P3-① (2026-08-12): 落库 avg_cost/shares_held——此前前端传值被静默
        # 丢弃，乐观更新掩盖「界面显示成功、刷新还原」bug。
        avg_cost=_avg_cost,
        shares_held=_shares,
        first_buy_date=data.first_buy_date,
        last_trade_date=data.last_trade_date,
    )
    db.add(etf)
    await db.commit()
    await db.refresh(etf)
    return etf


async def update_etf(db: AsyncSession, symbol: str, data: PortfolioETFUpdate) -> PortfolioETF | None:
    result = await db.execute(select(PortfolioETF).where(
        PortfolioETF.symbol == symbol, PortfolioETF.is_active.is_(True)
    ))
    etf = result.scalar_one_or_none()
    if not etf:
        return None
    # round19 P3-③ (2026-08-12): 「调整仓位（买卖）」语义——delta_shares 非 None 时
    # 走加权平均重算（增持/减持），并联动 target_weight（新市值÷组合总市值）。
    # 与 avg_cost/shares_held 直接覆盖态互斥（同传抛 400 语义）。
    _adjust_meta: dict | None = None
    if data.delta_shares is not None:
        if data.avg_cost is not None or data.shares_held is not None:
            raise HTTPException(status_code=400, detail="delta_shares 与 avg_cost/shares_held 互斥，不可同传")
        _price = data.price
        if _price is None:
            # 实时价兜底（拿不到 → 400，不用假价）
            _price = await _fetch_realtime_price(db, etf)
        if _price is None:
            raise HTTPException(status_code=400, detail="成交价缺失且实时价不可用")
        _r = recompute_cost_after_trade(
            etf.shares_held, etf.avg_cost, data.delta_shares, float(_price)
        )
        etf.shares_held = _r["new_shares"]
        etf.avg_cost = _r["new_avg_cost"]
        _new_weight = await _recompute_target_weight(
            db, symbol, _r["new_shares"], float(_price)
        )
        if _new_weight is not None:
            etf.target_weight = _new_weight
        _adjust_meta = {
            "realized_pnl": _r["realized_pnl"],
            "trade": {
                "delta_shares": data.delta_shares,
                "price": _price,
                "side": _r["side"],
            },
        }
    if data.name is not None:
        etf.name = data.name
    if data.target_weight is not None and data.delta_shares is None:
        etf.target_weight = data.target_weight
    if data.is_active is not None:
        etf.is_active = data.is_active
    if data.portfolio_type is not None:
        etf.portfolio_type = data.portfolio_type
    if data.short_name is not None:
        etf.short_name = data.short_name
    if data.tracked_index is not None:
        etf.tracked_index = data.tracked_index
    # round19 P3-① (2026-08-12): update_etf 补落库成本/份额——此前传了也不生效
    # （前端编辑成本被静默丢弃，刷新还原）。
    # F15 (round23 §3.3): 孤立 avg_cost 拦截——有成本无份额不落库（脏数据）：
    # ① avg_cost 仅在份额 >0 时写入；② 份额清零/缺失时同步清 avg_cost。
    if data.avg_cost is not None:
        _sh = data.shares_held if data.shares_held is not None else (etf.shares_held or 0)
        if _sh > 0:
            etf.avg_cost = data.avg_cost
    if data.shares_held is not None:
        etf.shares_held = data.shares_held
        if (data.shares_held or 0) <= 0:
            etf.avg_cost = None
    if data.first_buy_date is not None:
        etf.first_buy_date = data.first_buy_date
    if data.last_trade_date is not None:
        etf.last_trade_date = data.last_trade_date
    await db.commit()
    await db.refresh(etf)
    if _adjust_meta is not None:
        # 路由层读取注入响应（realized_pnl/trade 不属于 ORM 列）
        etf._adjust_meta = _adjust_meta
    return etf


async def remove_etf(db: AsyncSession, symbol: str) -> bool:
    result = await db.execute(select(PortfolioETF).where(
        PortfolioETF.symbol == symbol, PortfolioETF.is_active.is_(True)
    ))
    etf = result.scalar_one_or_none()
    if not etf:
        return False
    etf.is_active = False
    await db.commit()
    return True


def _resolve_tracked_index(symbol: str) -> str | None:
    """P0-14: 从候选池/ETF 基座缓存解析场内 ETF 的真实跟踪指数名（510300→沪深300）。"""
    try:
        from ...services.market_data_hub import market_data_hub
        _entry = market_data_hub.get_by_code(symbol)
        _t = (_entry or {}).get("tracked_index") or ""
        if _t and _t != "unknown":
            return str(_t)
    except Exception:
        pass
    try:
        from ...fetchers.etf_scanner import (
            _extract_index_keyword,
            _load_tracked_index_cache,
        )
        _tidx_map = _load_tracked_index_cache() or {}
        if symbol in _tidx_map and _tidx_map[symbol]:
            return str(_tidx_map[symbol])
        # 名称关键词兜底（510300 → ±300）
        baseline = None
        try:
            from ...fetchers.etf_scanner import fetch_all_etfs_base
            for _it in (fetch_all_etfs_base() or []):
                if str(_it.get("symbol", "")).zfill(6) == str(symbol).zfill(6):
                    baseline = _it.get("name") or ""
                    break
        except Exception:
            pass
        if baseline:
            _kw = _extract_index_keyword(baseline)
            if _kw:
                return str(_kw)
    except Exception:
        pass
    return None


async def _recompute_target_weight(
    db: AsyncSession, symbol: str, new_shares: float, price: float
) -> float | None:
    """round19 P3-③ (用户已确认联动): 新 target_weight = 新市值 ÷ 组合总市值
    （分母 = Σ active 持仓 shares×price，含操作后当前标的；拿不到价返回 None
    不强制联动——保持原权重。shares_held 为 NULL 的持仓不参与分母——未知市值
    不冒充 0（否则分母偏小、新权重虚高）。"""
    try:
        etfs = await _facade().list_etfs(db)
        price_map = await build_price_map(etfs)
        total = 0.0
        skipped_null_shares = 0
        for e in etfs:
            if e.symbol == symbol:
                # 操作后当前标的市值 = 新份额 × 成交价（口径：新市值 = 操作后 shares×price）
                _p = price
                _sh = new_shares
            else:
                _p = price_map.get(e.symbol, (None, None))[0] if e.symbol in price_map else None
                _sh = e.shares_held
            if _sh is None:
                skipped_null_shares += 1
                continue
            if _p and _sh > 0:
                total += _sh * float(_p)
        if skipped_null_shares:
            logger.info(
                "[portfolio] _recompute_target_weight skipped %d holding(s) with NULL shares_held",
                skipped_null_shares,
            )
        if total <= 0:
            return None
        return round((new_shares * price) / total, 4)
    except Exception:
        return None
