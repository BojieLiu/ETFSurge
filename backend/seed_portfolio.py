import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Run from backend dir so app imports resolve
sys.path.insert(0, r"E:\ETF_Surge\backend")

from app.database import async_session, init_db
from app.models.portfolio import PortfolioETF
from sqlalchemy import select, func

DEFAULT_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "asset_type": "A", "target_weight": 0.30, "portfolio_type": "on_exchange", "short_name": "沪深300ETF", "is_active": True, "tracked_index": None},
    {"symbol": "510500", "name": "中证500ETF", "asset_type": "A", "target_weight": 0.20, "portfolio_type": "on_exchange", "short_name": "中证500ETF", "is_active": True, "tracked_index": None},
    {"symbol": "159915", "name": "创业板ETF", "asset_type": "A", "target_weight": 0.20, "portfolio_type": "on_exchange", "short_name": "创业板ETF", "is_active": True, "tracked_index": None},
    {"symbol": "518880", "name": "黄金ETF", "asset_type": "A", "target_weight": 0.15, "portfolio_type": "on_exchange", "short_name": "黄金ETF", "is_active": True, "tracked_index": None},
    {"symbol": "159928", "name": "消费ETF", "asset_type": "A", "target_weight": 0.15, "portfolio_type": "on_exchange", "short_name": "消费ETF", "is_active": True, "tracked_index": None},
]


async def main():
    await init_db()
    async with async_session() as session:
        cnt = (await session.execute(select(func.count()).select_from(PortfolioETF))).scalar() or 0
        if cnt > 0:
            print(f"Portfolio already has {cnt} ETFs, skipping seed.")
            return
        session.add_all([PortfolioETF(**d) for d in DEFAULT_ETFS])
        await session.commit()
        print(f"Seeded {len(DEFAULT_ETFS)} default ETFs into portfolio.")


if __name__ == "__main__":
    asyncio.run(main())
