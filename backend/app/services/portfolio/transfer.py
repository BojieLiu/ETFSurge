"""Portfolio export / import — split from portfolio_service (Batch 1)."""

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import PortfolioETF
from app.services.portfolio._facade_refs import list_etfs

logger = logging.getLogger(__name__)




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
            # F15 (round23 §3.3): 导入路径孤立 avg_cost 拦截——有成本无份额的 CSV
            # 行不落脏数据（verify_e2e「孤立 avg_cost 20 条」根因之一是导入路径）。
            if shares_held is None or shares_held <= 0:
                avg_cost = None
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
