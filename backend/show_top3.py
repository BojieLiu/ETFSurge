"""Call LLM with top 3 prompt variants and show outputs"""
import asyncio, sys, json
sys.path.insert(0, '.')
from prompt_optimizer_clean import get_current_market_data, SYSTEM_PROMPT, BASE_USER_PROMPT, call_llm, parse_json, V5_DETAILED, V8, V11

market_data = get_current_market_data()
print(f"Market data: {len(market_data['cn_indices'].split(chr(10)))} lines CN")

variants = [
    ("V5: Detailed", V5_DETAILED),
    ("V8: Precise v2", V8),
    ("V11: Precise v5", V11),
]

async def main():
    for name, instr in variants:
        user_prompt = BASE_USER_PROMPT.format(
            cn_indices=market_data["cn_indices"],
            us_data=market_data["us_data"],
            commodity_data=market_data["commodity_data"],
            news_data=market_data["news_data"],
            prompt_instructions=instr,
        )
        print(f"\n{'='*70}")
        print(f"  {name}")
        print(f"{'='*70}")
        
        try:
            response, elapsed = await call_llm(SYSTEM_PROMPT, user_prompt)
            parsed = parse_json(response)
            pfs = parsed.get("portfolios", [])
            print(f"  Time: {elapsed:.1f}s")
            
            for pf in pfs:
                t = pf.get('type', '')
                etfs = pf.get('etfs', [])
                cash = pf.get('cash_weight', 0)
                print(f"\n  ── {pf.get('name', t)} ({t}) ──")
                print(f"  Cash: {cash:.0%}")
                for e in etfs:
                    w = e.get('weight', 0)
                    print(f"    {e.get('symbol',''):8s} {e.get('name',''):20s} {w*100:.0f}%")
            if not pfs:
                print(f"  (parse failed, raw: {response[:200]})")
        except Exception as e:
            print(f"  ERROR: {e}")

asyncio.run(main())