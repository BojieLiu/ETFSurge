import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test_all():
    from app.routers.analysis import _fetch_all_market, _collect_news, portfolio_design

    # 1. Test market fetching
    print("=== _fetch_all_market ===")
    market, indices, commodities = await _fetch_all_market()
    print(f"market={len(market)}, indices={len(indices)}, commodities={len(commodities)}")

    # 2. Test news collection
    print("\n=== _collect_news ===")
    news = await _collect_news()
    print(f"news={len(news)}")

    # 3. Test portfolio_design
    print("\n=== portfolio_design ===")
    result = await portfolio_design()
    print(f"keys={list(result.keys())}")
    print(f"portfolios={len(result.get('portfolios', []))}")
    if result.get("portfolios"):
        pf = result["portfolios"][0]
        print(f"First: {pf['name']}, ETFs={len(pf.get('etfs', []))}")
        total = sum(e["weight"] for e in pf["etfs"]) + (pf.get("cash_weight") or 0)
        print(f"Weight sum={total:.2f}")

    print("\nAll tests passed!")

asyncio.run(test_all())
