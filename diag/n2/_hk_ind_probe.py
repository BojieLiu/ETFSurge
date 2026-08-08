import sys, asyncio
sys.stdout.reconfigure(encoding='utf-8')
from app.services.market_service import get_history
from app.analysis.indicators import compute_all_indicators
from app.fetchers.hk_hot_fetcher import get_hk_hot_stocks

async def main():
    # 取港股热门个股真实代码
    try:
        stocks = await asyncio.to_thread(get_hk_hot_stocks, 5)
        print('HK hot stocks:', [(s['symbol'], s['name']) for s in stocks])
        sym = stocks[0]['symbol']
        name = stocks[0]['name']
    except Exception as e:
        print('hk_hot err:', e)
        sym, name = '02800', '盈富基金'
    # 用 HK asset_type 拉历史
    for at in ('HK', 'A'):
        try:
            hist = await get_history(sym, at, 'daily')
            print(f'asset_type={at}: history rows={len(hist) if hist else 0}')
            if hist:
                ind = compute_all_indicators(hist[:len(hist)//2]) if hist else {}
                # 打印部分指标字段
                print('  ind keys sample:', {k: (ind.get(k) if not isinstance(ind.get(k), dict) else 'dict') for k in list(ind.keys())[:8]})
                break
        except Exception as e:
            print(f'asset_type={at} ERR:', e)

asyncio.run(main())