import asyncio, json, sys
sys.stdout.reconfigure(encoding='utf-8')
from app.factors.factor_registry import registry

symbols = ['159338','510880','159545','159516','159992','513120','513010','512000','159869','518880']

async def main():
    try:
        fs = await asyncio.wait_for(registry.compute(symbols), timeout=90)
        print('compute done; symbols:', list(fs.keys()))
        for s in symbols:
            d = fs.get(s, {})
            if isinstance(d, dict):
                keys = list(d.keys())
                print(s, 'klen=', len(keys), 'sample:', keys[:8])
            else:
                print(s, 'type:', type(d))
    except Exception as e:
        print('ERR:', type(e).__name__, e)

asyncio.run(main())