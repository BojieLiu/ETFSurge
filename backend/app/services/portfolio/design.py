"""Portfolio design application — split from portfolio_service (Batch 1)."""

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import PortfolioETF
from app.services.portfolio._facade_refs import list_etfs
from app.services.portfolio.pricing import normalize_asset_type

logger = logging.getLogger(__name__)




async def apply_portfolio_design(db: AsyncSession, design: dict) -> dict[str, Any]:
    """根据组合设计应用持仓"""
    try:
        portfolio_type = design.get("portfolio_type", "on_exchange")
        symbols = design.get("symbols", [])
        weights = design.get("weights", {})
        if not symbols:
            return {"symbols": [], "message": "组合设计中没有指定持仓"}

        # P0-10② (round16 3.11): 幽灵标的名称回填——新增标的先查 ETF 基座缓存补真实名，
        # 查不到才用默认名并打 _degraded 标记（前端可提示）。
        _degraded = False
        _code_name_map: dict[str, str] = {}
        try:
            from ...fetchers.etf_scanner import fetch_all_etfs_base
            # P0-11 (round16 3.12): 同步读取走线程池，不阻塞事件循环
            _base = await asyncio.to_thread(fetch_all_etfs_base) or []
            _code_name_map = {
                str(e.get("symbol", "")).zfill(6): str(e.get("name") or "")
                for e in _base
                if e.get("symbol") and e.get("name")
            }
        except Exception as _e:
            logger.warning("[apply_portfolio_design] etf base name lookup failed (non-fatal): %s", _e)

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
                real_name = _code_name_map.get(str(symbol).zfill(6)) or _code_name_map.get(str(symbol), "")
                if real_name:
                    name = real_name
                    short_name = real_name
                else:
                    name = f"{symbol} ETF"
                    short_name = symbol
                    _degraded = True
                # R176 (round52 §7.3 方案E-1): asset_type 写 'A'（pricing/_split_symbols
                # 既定口径）——旧值 'ETF' 会导致带 portfolio_type 过滤的请求现价恒 0。
                new_etf = PortfolioETF(symbol=symbol, name=name, short_name=short_name,
                    asset_type=normalize_asset_type("ETF"),
                    target_weight=w, portfolio_type=portfolio_type, tracked_index=None, is_active=True)
                db.add(new_etf)
                applied.append({"symbol": symbol, "name": new_etf.name, "target_weight": w, "portfolio_type": portfolio_type, "action": "added", "_degraded": _degraded})

        await db.commit()
        updated = await list_etfs(db)
        return {"symbols": [{"symbol": e.symbol, "name": e.name, "target_weight": e.target_weight, "portfolio_type": e.portfolio_type} for e in updated], "applied": applied, "degraded": _degraded}
    except Exception as e:
        await db.rollback()
        raise e
