# -*- coding: utf-8 -*-
"""实测 IOPV/nav 三级降级链在本地是否工作�?0 只样本）"""
import asyncio
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

SYMBOLS = ["510050", "510880", "159338", "510300", "560600", "159545", "159516", "159992", "513120", "513010"]


async def main():
    from app.factors.factor_registry import _iopv_sina_symbols, _fetch_iopv_chain

    sina_list = _iopv_sina_symbols(SYMBOLS)
    print("sina symbols:", sina_list[:5], "...")
    iopv_data, source = await _fetch_iopv_chain(sina_list, SYMBOLS)
    print("IOPV source:", source, "| hits:", len(iopv_data))
    for s in SYMBOLS:
        v = iopv_data.get(s) or {}
        print(f"  {s}: nav={v.get('nav')} price={v.get('price')}")

    # TTJ 兜底
    from app.core.async_utils import run_sync
    from app.services.market_data_hub import market_data_hub as hub
    for s in SYMBOLS:
        nav = await run_sync(hub.get_fund_nav, s, timeout=6)
        print(f"  TTJ {s}: nav={ (nav or {}).get('nav') }")


asyncio.run(main())

