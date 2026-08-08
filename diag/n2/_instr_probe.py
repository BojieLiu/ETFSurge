import sys, asyncio
sys.stdout.reconfigure(encoding='utf-8')
from app.database import async_session
from app.models.search import Instrument
from app.services.market_service import get_asset_realtime

async def main():
    async with async_session() as s:
        from sqlalchemy import select
        rows = (await s.execute(select(Instrument).where(Instrument.symbol.like('%02800%')))).scalars().all()
        print('instruments matching 02800:', len(rows))
        for r in rows[:10]:
            print('  symbol=%r name=%r market=%r asset_type=%r type=%r' % (
                r.symbol, r.name, r.market, getattr(r, 'asset_type', None), getattr(r, 'type', None)))
    rt = await get_asset_realtime('02800', 'HK')
    print('realtime 02800:', {k: rt.get(k) for k in ('symbol','name','price','change_pct','asset_type','type','market')} if rt else 'None')

asyncio.run(main())