import asyncio, json, sys, time
sys.path.insert(0, '.')

from prompt_optimizer import (
    get_current_market_data, CURRENT_SYSTEM_PROMPT, BASE_USER_PROMPT,
    call_llm, parse_json, analyze_output, ALL_VARIANTS
)

market_data = get_current_market_data()

async def run_one(round_num, name, instructions):
    user_prompt = BASE_USER_PROMPT.format(
        cn_indices=market_data["cn_indices"],
        us_data=market_data["us_data"],
        commodity_data=market_data["commodity_data"],
        news_data=market_data["news_data"],
        prompt_instructions=instructions,
    )
    try:
        response, elapsed = await call_llm(CURRENT_SYSTEM_PROMPT, user_prompt)
        parsed = parse_json(response)
        analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "warnings": ["JSON parse failed"]}
        print(f"V{round_num}: ETFs={analysis['total_etf_count']}, warns={len(analysis['warnings'])}, time={elapsed:.1f}s")
        return {"round": round_num, "name": name, "analysis": analysis}
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"round": round_num, "name": name, "analysis": {"total_etf_count": 0, "warnings": [str(e)]}}    

async def main():
    market_data = get_current_market_data()
    print(f"CN: {len(market_data['cn_indices'].split(chr(10)))} lines, US: {len(market_data['us_data'].split(chr(10)))} lines")
    
    # Load existing or start fresh
    try:
        with open("prompt_results_all.json", encoding="utf-8") as f:
            results = json.load(f)
        print(f"  Loaded {len(results)} existing results")
    except:
        results = []
    
    done_rounds = set(r["round"] for r in results)
    batch_count = 0
    
    for i, (name, instr) in enumerate(ALL_VARIANTS[1:], 15):
        if i in done_rounds:
            print(f"  Round {i} already done, skip")
            continue
        if batch_count >= 3:
            print(f"  Batch limit reached (3 new), stopping")
            break
            
        print(f"\n{'='*60}")
        print(f"  Round {i}: {name}")
        print(f"{'='*60}")
        res = await run_one(i, name, instr)
        results.append({"round": i, "name": name, "analysis": res["analysis"]})
        batch_count += 1
        
        # Save after each
        with open("prompt_results_all.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    
    # Show latest comparison
    print(f"\n{'='*80}")
    print("  LATEST RESULTS")
    print(f"{'='*80}")
    for r in results[-10:]:
        a = r.get("analysis", {})
        s = a.get("style_breakdown", {})
        nw = len(a.get("warnings", []))
        print(f"V{r['round']:<5} {r['name'][:33]:<33} {a.get('total_etf_count',0):<6} grow={s.get('growth',0)} val={s.get('value',0)} warn={nw}")
    
    valid = [r for r in results if r.get("analysis",{}).get("total_etf_count",0) > 0]
    if valid:
        best = max(valid, key=lambda r: (r["analysis"]["total_etf_count"], -len(r["analysis"].get("warnings",[]))))
        print(f"\nBEST so far: V{best['round']} ({best['name']}) - {best['analysis']['total_etf_count']} ETFs")

if __name__ == "__main__":
    asyncio.run(main())