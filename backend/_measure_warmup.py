"""Measure warmup duration per component."""
import time, os, sys, json, asyncio
sys.path.insert(0, os.path.dirname(__file__))

async def main():
    from app.fetchers.etf_scanner import fetch_all_etfs_base
    from app.core.async_utils import run_sync

    # ETF cache file
    cf = os.path.join(os.path.dirname(__file__), "app/data/etf_list_cache.json")
    if os.path.exists(cf):
        with open(cf) as f:
            c = json.load(f)
        ts = c.get("ts", 0)
        age_min = (time.time() - ts) / 60
        print(f"[etf_cache_file] {len(c.get('etfs',[]))} items, age={age_min:.0f} min")

    # Measure ETF scan time
    t0 = time.time()
    result = await run_sync(fetch_all_etfs_base, timeout=120)
    t = time.time() - t0
    print(f"[etf_warmup] took {t:.1f}s, {len(result)} ETFs")

    # Check cache file now
    if os.path.exists(cf):
        with open(cf) as f:
            c = json.load(f)
        print(f"[etf_cache_post] {len(c.get('etfs',[]))} items")

asyncio.run(main())
