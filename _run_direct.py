#!/usr/bin/env python3
"""Run design + strategy check directly, then persist results to DB."""
import asyncio, json, sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

async def main():
    from app.database import init_db, async_session
    from app.services.strategy_design import generate_enhanced_design
    from app.services.portfolio_service import strategy_check, list_etfs
    from app.models.portfolio_design import PortfolioDesign
    from app.models.strategy_check import StrategyCheckRecord
    from datetime import datetime

    await init_db()
    print("DB ready")
    sys.stdout.flush()

    # === DESIGN ===
    print("\n=== Design ===")
    t1 = time.time()
    result = await generate_enhanced_design(capital=500000, constraints=None)
    elapsed = time.time() - t1
    print(f"Done in {elapsed:.0f}s, strategies={len(result.get('strategies',[]))}")
    sys.stdout.flush()

    # Save to DB
    async with async_session() as db:
        record = PortfolioDesign(
            capital=500000,
            risk_profile="balanced",
            status="completed",
            design_text="",
            strategies_json=json.dumps(result.get("strategies", []), ensure_ascii=False),
            market_snapshot_json=json.dumps(result.get("market_context", {}), ensure_ascii=False),
            report_quality="full",
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        design_id = record.id
        print(f"Design saved: ID={design_id}")
    sys.stdout.flush()

    # === STRATEGY CHECK ===
    print("\n=== Strategy Check (on_exchange) ===")
    async with async_session() as db:
        t1 = time.time()
        check = await strategy_check(db, 500000, portfolio_type="on_exchange")
        elapsed = time.time() - t1
        print(f"Done in {elapsed:.0f}s")
        print(f"Regime: {check.get('market_regime','?')}")
        print(f"Suggestions: {len(check.get('suggestions',[]))}")
        sys.stdout.flush()

        # Save to DB
        record = StrategyCheckRecord(
            capital=500000,
            summary=check.get("summary", ""),
            market_regime=check.get("market_regime", ""),
            suggestions_json=json.dumps(check.get("suggestions", []), ensure_ascii=False, default=str),
            holdings_json=json.dumps(check.get("holdings_analysis", []), ensure_ascii=False, default=str),
            risk_warnings_json=json.dumps(check.get("risk_warnings", []), ensure_ascii=False, default=str),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        print(f"Check saved: ID={record.id}")
    sys.stdout.flush()

    # === Summary ===
    print("\n=== Summary ===")
    strategies = result.get("strategies", [])
    for i, s in enumerate(strategies):
        print(f"  [{i+1}] {s.get('portfolio_name','?')} ({s.get('id','?')})")
        for e in s.get("etfs", []):
            sym = e.get("symbol","?")
            w = e.get("weight",0)
            print(f"      {sym:8s}  w={w:.4f}")

    suggs = check.get("suggestions", [])
    print(f"\n  Check: {len(suggs)} suggestions")
    for s in suggs[:5]:
        if isinstance(s, dict):
            print(f"    {s.get('action','?'):10s} {s.get('symbol','?'):8s} cur={s.get('current_weight',0):.4f} sug={s.get('suggested_weight',0):.4f}")

    ha = check.get("holdings_analysis", [])
    print(f"\n  Holdings analysis: {len(ha)}")
    for h in ha[:3]:
        if isinstance(h, dict):
            print(f"    {h.get('symbol','?'):8s} signal={h.get('signal','?')} factor={str(h.get('factor_summary',''))[:50]}")

    print("\nDONE")

asyncio.run(main())
