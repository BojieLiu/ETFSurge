#!/usr/bin/env python3
"""Diagnose: show full allocation output from generate_enhanced_design."""
import asyncio, json

async def test():
    from app.services.strategy_design import generate_enhanced_design as g
    result = await g(capital=500000)
    strategies = result.get("strategies", [])
    market = result.get("market_context", {})
    for s in strategies:
        lbl = s.get("label", "?")
        etfs = s.get("etfs", [])
        print(f"\n{lbl}: {len(etfs)} entries")
        for e in etfs:
            sym = e.get("symbol", "?")
            w = e.get("weight", 0)
            sc = e.get("factor_score", "n/a")
            print(f"  {sym} w={w:.2f} score={sc}")
    print(f"\nMarket regime: {market.get('market_regime', '?')}")
    print(f"Excess volatility: {market.get('excess_volatility', '?')}")

asyncio.run(test())
