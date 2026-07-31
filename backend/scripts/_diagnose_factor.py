#!/usr/bin/env python3
"""Deep diagnose: find where the pipeline discards valid ETF allocations."""
import asyncio, time, logging
logging.basicConfig(level=logging.WARNING)

async def test():
    from app.services.market_data_hub import pool_manager

    await market_data_hub.refresh()
    factor_matrix = market_data_hub.get_factor_matrix()
    print(f"Factor matrix: {len(factor_matrix)} symbols")

    pool = market_data_hub.get_pool()
    candidates = {
        "core": pool.get("core", []),
        "satellite": pool.get("satellite", []),
        "defense": pool.get("defense", []),
    }
    total = sum(len(v) for v in candidates.values())
    print(f"Candidates: {total} total")

    # aggregate factor scores direct call
    from app.factors.factor_registry import FactorRegistry
    reg = FactorRegistry()
    agg = reg.aggregate_factor_scores(factor_matrix)
    print(f"Aggregated scores: {len(agg)} symbols")
    if agg:
        sorted_syms = sorted(agg.items(), key=lambda x: -x[1].get("composite_score", 0))
        for sym, s in sorted_syms[:5]:
            cs = s.get("composite_score", 0)
            print(f"  {sym}: composite={cs:.3f}")

    # allocate() call
    from app.engine.allocation_engine import allocate
    from app.engine.budgets import dynamic_layer_budget, STRATEGY_META
    import inspect
    sig = inspect.signature(allocate)
    print(f"\nallocate() signature: {sig}")

    # Test one strategy
    meta = STRATEGY_META["aggressive"]
    budget = dynamic_layer_budget(500000, "aggressive", factor_matrix)
    print(f"\n=== Allocate aggressive ===")
    print(f"Budget layers: {[(k, v['count']) for k, v in budget.items()]}")
    result = allocate(candidates, factor_matrix, budget, -1, "aggressive")
    etfs = result.get("etfs", [])
    real = [e for e in etfs if e.get("symbol") != "CASH"]
    print(f"Result: {len(etfs)} total, {len(real)} real")
    if real:
        for e in real[:5]:
            print(f"  {e['symbol']} ({e.get('weight',0)*100:.0f}%)")
    elif etfs:
        print(f"  All CASH: {etfs}")

asyncio.run(test())
