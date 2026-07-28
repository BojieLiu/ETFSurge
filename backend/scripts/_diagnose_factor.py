#!/usr/bin/env python3
"""Diagnose: test generate_enhanced_design directly + trace pipeline steps."""
import asyncio, time, logging
logging.basicConfig(level=logging.INFO)

async def test():
    # Step 1: Pool refresh
    from app.services.pool_manager import pool_manager
    print("Step 1: Refreshing pool...")
    diff = await pool_manager.refresh()
    pool = pool_manager.get_pool()
    total = sum(len(v) for v in pool.values()) if pool else 0
    print(f"  Pool after refresh: {total} total ETFs")
    for k, v in pool.items() if pool else {}:
        print(f"    {k}: {len(v)} items")

    # Step 2: Direct generate_enhanced_design
    print("\nStep 2: Running generate_enhanced_design...")
    from app.services.strategy_design import generate_enhanced_design
    t0 = time.time()
    result = await generate_enhanced_design(capital=500000)
    elapsed = time.time() - t0
    strategies = result.get("strategies", [])
    print(f"  Done in {elapsed:.1f}s, {len(strategies)} strategies")

    # Step 3: Check if strategies have real ETFs
    for s in strategies:
        label = s.get("label", "?")
        etfs = s.get("etfs", [])
        real = [e for e in etfs if e.get("symbol") != "CASH"]
        sample = [(e.get("symbol"), e.get("weight", 0)) for e in real[:3]]
        print(f"  {label}: {len(etfs)} total, {len(real)} real {sample}")

    # Step 4: Check task_manager pipeline
    print("\nStep 3: Testing task_manager pipeline...")
    from app.tasks.task_manager import design_pipeline, task_manager
    import json

    # Create task
    task = task_manager.create_task("design", {"capital": 500000, "risk_profile": "balanced"})
    task_id = task["task_id"]
    print(f"  Task created: {task_id}")

    # Mock generate_enhanced_design to return real data
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_strategies = [
        {"id": "defensive", "label": "防御型",
         "etfs": [{"symbol": "510050", "weight": 0.3, "layer": "core"},
                  {"symbol": "511880", "weight": 0.2, "layer": "cash"}]},
        {"id": "balanced", "label": "平衡型",
         "etfs": [{"symbol": "510300", "weight": 0.3, "layer": "core"},
                  {"symbol": "518880", "weight": 0.2, "layer": "defense"}]},
    ]

    with patch("app.services.strategy_design.generate_enhanced_design",
               new=AsyncMock(return_value={"strategies": mock_strategies, "market_context": {}})):
        with patch("app.tasks.task_manager.async_session") as mock_db:
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock()
            mock_ctx.add = MagicMock()
            mock_ctx.commit = AsyncMock()
            mock_ctx.get = AsyncMock(return_value=None)
            mock_ctx.refresh = AsyncMock()
            mock_db.return_value = mock_ctx

            await design_pipeline(task_manager, task_id)

    task_result = task_manager.get_task(task_id)
    print(f"  Task status: {task_result.get('status')}")
    print(f"  Task error: {task_result.get('error_message', '')[:100]}")

asyncio.run(test())
