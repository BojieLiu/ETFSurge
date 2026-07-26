"""Check search endpoint behavior."""
import asyncio
import sys
sys.path.insert(0, '.')
from app.services.market_service import search_etf
from app.services.cache_service import sync_memory_cache

sync_memory_cache.clear()

# Test 1: search for Moutai
r = asyncio.run(search_etf("茅台"))
print(f"[DEFAULT search] keyword=茅台: {len(r)} items")
for it in r[:5]:
    print(f"  symbol={it.get('symbol')} name={it.get('name')} asset_type={it.get('asset_type')} market={it.get('market')}")

# Check if market parameter exists
from app.routers.market import router
for route in router.routes:
    if hasattr(route, 'path') and '/search' in str(route.path):
        import inspect
        src = inspect.getsource(route.endpoint)  # type: ignore[attr-defined]
        if 'market' in src:
            print(f"\n  [OK] {route.path} accepts 'market' param")
        else:
            print(f"\n  [MISSING] {route.path} does NOT accept 'market' param")
