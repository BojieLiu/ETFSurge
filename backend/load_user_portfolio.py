import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"E:\ETF_Surge\backend")

from app.database import async_session, init_db
from app.models.portfolio import PortfolioETF
from sqlalchemy import select, func, delete

# 用户指定组合（场内 10 只 + 对应场外 C 类联接基金）
# 权重归一化：ETF 合计 0.82，现金自动 = 0.18
ON_EXCHANGE = [
    {"symbol": "159338", "name": "中证A500ETF", "asset_type": "A", "target_weight": 0.26, "portfolio_type": "on_exchange", "short_name": "中证A500ETF", "is_active": True, "tracked_index": None},
    {"symbol": "510880", "name": "红利ETF", "asset_type": "A", "target_weight": 0.08, "portfolio_type": "on_exchange", "short_name": "红利ETF", "is_active": True, "tracked_index": None},
    {"symbol": "159545", "name": "恒生红利低波ETF", "asset_type": "A", "target_weight": 0.05, "portfolio_type": "on_exchange", "short_name": "恒生红利低波ETF", "is_active": True, "tracked_index": None},
    {"symbol": "159516", "name": "半导体设备ETF国泰", "asset_type": "A", "target_weight": 0.04, "portfolio_type": "on_exchange", "short_name": "半导体设备ETF", "is_active": True, "tracked_index": None},
    {"symbol": "159992", "name": "创新药ETF银华", "asset_type": "A", "target_weight": 0.05, "portfolio_type": "on_exchange", "short_name": "创新药ETF", "is_active": True, "tracked_index": None},
    {"symbol": "513120", "name": "港股创新药ETF广发", "asset_type": "A", "target_weight": 0.05, "portfolio_type": "on_exchange", "short_name": "港股创新药ETF", "is_active": True, "tracked_index": None},
    {"symbol": "513010", "name": "恒生科技ETF易方达", "asset_type": "A", "target_weight": 0.03, "portfolio_type": "on_exchange", "short_name": "恒生科技ETF", "is_active": True, "tracked_index": None},
    {"symbol": "512000", "name": "券商ETF华宝", "asset_type": "A", "target_weight": 0.08, "portfolio_type": "on_exchange", "short_name": "券商ETF", "is_active": True, "tracked_index": None},
    {"symbol": "159869", "name": "游戏ETF华夏", "asset_type": "A", "target_weight": 0.05, "portfolio_type": "on_exchange", "short_name": "游戏ETF", "is_active": True, "tracked_index": None},
    {"symbol": "518880", "name": "黄金ETF华安", "asset_type": "A", "target_weight": 0.13, "portfolio_type": "on_exchange", "short_name": "黄金ETF", "is_active": True, "tracked_index": None},
]

# 场外 = 对应场内标的的场外联接基金（C 类）；tracked_index 指向场内 ETF 代码以复用其实时涨跌
OFF_EXCHANGE_C = [
    {"symbol": "022449", "name": "国泰中证A500ETF发起联接C", "asset_type": "A", "target_weight": 0.26, "portfolio_type": "off_exchange", "short_name": "A500联接C", "is_active": True, "tracked_index": "159338"},
    {"symbol": "012762", "name": "华泰柏瑞红利ETF联接C", "asset_type": "A", "target_weight": 0.08, "portfolio_type": "off_exchange", "short_name": "红利联接C", "is_active": True, "tracked_index": "510880"},
    {"symbol": "021458", "name": "易方达恒生港股通高股息低波ETF联接C", "asset_type": "A", "target_weight": 0.05, "portfolio_type": "off_exchange", "short_name": "港股红利低波联接C", "is_active": True, "tracked_index": "159545"},
    {"symbol": "019633", "name": "国泰中证半导体材料设备主题ETF发起联接C", "asset_type": "A", "target_weight": 0.04, "portfolio_type": "off_exchange", "short_name": "半导体设备联接C", "is_active": True, "tracked_index": "159516"},
    {"symbol": "012782", "name": "银华中证创新药产业ETF发起式联接C", "asset_type": "A", "target_weight": 0.05, "portfolio_type": "off_exchange", "short_name": "创新药联接C", "is_active": True, "tracked_index": "159992"},
    {"symbol": "019671", "name": "广发中证香港创新药ETF发起式联接(QDII)C", "asset_type": "A", "target_weight": 0.05, "portfolio_type": "off_exchange", "short_name": "港股创新药联接C", "is_active": True, "tracked_index": "513120"},
    {"symbol": "013309", "name": "易方达恒生科技ETF联接C", "asset_type": "A", "target_weight": 0.03, "portfolio_type": "off_exchange", "short_name": "恒生科技联接C", "is_active": True, "tracked_index": "513010"},
    {"symbol": "006098", "name": "华宝中证全指证券ETF联接C", "asset_type": "A", "target_weight": 0.08, "portfolio_type": "off_exchange", "short_name": "券商联接C", "is_active": True, "tracked_index": "512000"},
    {"symbol": "012769", "name": "华夏中证动漫游戏ETF发起式联接C", "asset_type": "A", "target_weight": 0.05, "portfolio_type": "off_exchange", "short_name": "游戏联接C", "is_active": True, "tracked_index": "159869"},
    {"symbol": "000217", "name": "华安黄金ETF联接C", "asset_type": "A", "target_weight": 0.13, "portfolio_type": "off_exchange", "short_name": "黄金联接C", "is_active": True, "tracked_index": "518880"},
]


async def main():
    await init_db()
    async with async_session() as session:
        cnt = (await session.execute(select(func.count()).select_from(PortfolioETF))).scalar() or 0
        if cnt > 0:
            await session.execute(delete(PortfolioETF))
            await session.commit()
            print(f"Cleared {cnt} existing portfolio rows.")

        rows = [PortfolioETF(**d) for d in (ON_EXCHANGE + OFF_EXCHANGE_C)]
        session.add_all(rows)
        await session.commit()
        on_w = round(sum(d["target_weight"] for d in ON_EXCHANGE), 4)
        print(f"Loaded {len(ON_EXCHANGE)} on_exchange + {len(OFF_EXCHANGE_C)} off_exchange C类 funds.")
        print(f"On-exchange weight sum = {on_w}, implied cash_weight = {round(1.0 - on_w, 4)}")


if __name__ == "__main__":
    asyncio.run(main())
