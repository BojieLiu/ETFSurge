"""Run 2 remaining prompt variants at a time"""
import asyncio, sys, json
sys.path.insert(0, '.')
from prompt_optimizer_clean import get_current_market_data, SYSTEM_PROMPT, BASE_USER_PROMPT, call_llm, parse_json, analyze_output, VARIANTS

async def run_one(round_num, name, instructions, market_data):
    up = BASE_USER_PROMPT.format(
        cn_indices=market_data["cn_indices"],
        us_data=market_data["us_data"],
        commodity_data=market_data["commodity_data"],
        news_data=market_data["news_data"],
        prompt_instructions=instructions,
    )
    try:
        r, elapsed = await call_llm(SYSTEM_PROMPT, up)
        p = parse_json(r)
        a = analyze_output(p) if p.get("portfolios") else {"total_etf_count": 0, "warnings": ["JSON parse failed"]}
        print(f"V{round_num}: {name} - {a['total_etf_count']} ETFs, {len(a.get('warnings',[]))} warns, {elapsed:.1f}s")
        return {"round": round_num, "name": name, "analysis": a}
    except Exception as e:
        print(f"V{round_num} ERROR: {e}")
        return {"round": round_num, "name": name, "analysis": {"total_etf_count": 0, "warnings": [str(e)]}}

async def main():
    m = get_current_market_data()
    print(f"Data: {len(m['cn_indices'].split(chr(10)))} lines")
    
    try:
        with open('prompt_results_all.json', encoding='utf-8') as f:
            results = json.load(f)
        done = {r['round'] for r in results}
        print(f"Existing: {len(results)} results, {len(done)} completed rounds")
    except:
        results = []
        done = set()
    
    batch_count = 0
    for i, (name, instr) in enumerate(VARIANTS, 1):
        if i in done:
            continue
        if batch_count >= 2:
            break
        res = await run_one(i, name, instr, m)
        results.append(res)
        batch_count += 1
        with open("prompt_results_all.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

asyncio.run(main())