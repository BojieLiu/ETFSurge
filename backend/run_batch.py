"""
Run remaining variants V9-V33 (3 at a time to avoid timeout)
"""
import asyncio, sys, json
sys.path.insert(0, '.')

from prompt_optimizer_clean import get_current_market_data, SYSTEM_PROMPT, BASE_USER_PROMPT, call_llm, parse_json, analyze_output, VARIANTS

async def main():
    market_data = get_current_market_data()
    print(f"Market data loaded: {len(market_data['cn_indices'].split(chr(10)))} lines")
    
    # Load existing results
    try:
        with open('prompt_results_all.json', encoding='utf-8') as f:
            results = json.load(f)
        done_rounds = {r['round'] for r in results}
        print(f"Loaded {len(results)} existing results, completed rounds: {sorted(done_rounds)}")
    except:
        results = []
        done_rounds = set()
    
    # Run remaining variants
    for i, (name, instr) in enumerate(VARIANTS, 1):
        if i in done_rounds:
            continue
        if len([r for r in results if r.get('analysis',{}).get('total_etf_count',0) > 0]) >= 20:
            break
            
        user_prompt = BASE_USER_PROMPT.format(
            cn_indices=market_data["cn_indices"],
            us_data=market_data["us_data"],
            commodity_data=market_data["commodity_data"],
            news_data=market_data["news_data"],
            prompt_instructions=instr,
        )
        
        print(f"\nRound {i}: {name}")
        try:
            response, elapsed = await call_llm(SYSTEM_PROMPT, user_prompt)
            parsed = parse_json(response)
            analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "warnings": ["JSON parse failed"]}
            cnt = analysis['total_etf_count']
            print(f"  V{i}: {cnt} ETFs, {len(analysis.get('warnings',[]))} warnings, {elapsed:.1f}s")
            results.append({"round": i, "name": name, "analysis": analysis})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"round": i, "name": name, "analysis": {"total_etf_count": 0, "warnings": [str(e)]}})
        
        # Save after each
        with open("prompt_results_all.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        # Stop after 3 more completed rounds
        completed_now = [r for r in results if r.get('analysis',{}).get('total_etf_count',0) > 0]
        if len(completed_now) > 0 and len(completed_now) == len([r for r in json.load(open('prompt_results_all.json', encoding='utf-8')) if r.get('analysis',{}).get('total_etf_count',0) > 0]) + 3:
            print("\nBatch done, stopping.")
            break

asyncio.run(main())