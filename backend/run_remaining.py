"""Run remaining variants V15-V33 (V14 already done)."""
import asyncio, sys
sys.path.insert(0, '.')
from prompt_optimizer import get_current_market_data, CURRENT_SYSTEM_PROMPT, BASE_USER_PROMPT, call_llm, parse_json, analyze_output, print_round, print_comparison, ALL_VARIANTS

V14_RESULT = {"round": 14, "name": "V14: Fix defensive - higher equity 60%", "analysis": {
    "total_etf_count": 30, "per_portfolio": {"aggressive": {"count":10,"cash":0.1},"balanced":{"count":10,"cash":0.15},"defensive":{"count":10,"cash":0.15}},
    "style_breakdown": {"growth":14,"value":6,"balanced":5,"commodity":2,"cross_border":3},
    "asset_categories": {"broad_index":8,"sector":15,"cross_border":4,"commodity":3},"warnings":[]
}}

async def main():
    print("Running V15-V33...")
    market_data = get_current_market_data()
    all_results = [V14_RESULT]
    
    # Run in batches of 3
    remaining = ALL_VARIANTS[1:]  # V15-V33
    for start in range(0, len(remaining), 3):
        batch = remaining[start:start+3]
        for i, (name, instructions) in enumerate(batch):
            round_num = 15 + start + i
            print(f"\nBatch starting round {round_num}...")
            up = BASE_USER_PROMPT.format(
                cn_indices=market_data["cn_indices"], us_data=market_data["us_data"],
                commodity_data=market_data["commodity_data"], news_data=market_data["news_data"],
                prompt_instructions=instructions,
            )
            try:
                resp, elapsed = await call_llm(CURRENT_SYSTEM_PROMPT, up)
                parsed = parse_json(resp)
                analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count":0, "per_portfolio":{}, "style_breakdown":{}, "asset_categories":{}, "warnings":["JSON parse failed"]}
                print_round(round_num, name, parsed, analysis, elapsed)
                all_results.append({"round": round_num, "name": name, "analysis": analysis})
            except Exception as e:
                print(f"  ERROR: {e}")
                all_results.append({"round": round_num, "name": name, "analysis": {"total_etf_count":0, "warnings":[str(e)]}})
        
        print_comparison(all_results)
    
    # Final
    print("\nFINAL ALL RESULTS:")
    print_comparison(all_results)
    
    # Best
    valid = [r for r in all_results if r["analysis"].get("total_etf_count",0) > 0]
    if valid:
        best = max(valid, key=lambda r: (r["analysis"]["total_etf_count"], -len(r["analysis"].get("warnings",[]))))
        print(f"\nBEST: V{best['round']} ({best['name']}) - {best['analysis']['total_etf_count']} ETFs, {len(best['analysis'].get('warnings',[]))} warnings")

asyncio.run(main())
