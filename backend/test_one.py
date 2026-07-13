import asyncio, sys
sys.path.insert(0, '.')

from prompt_optimizer import get_current_market_data, CURRENT_SYSTEM_PROMPT, BASE_USER_PROMPT, call_llm, parse_json, analyze_output, ALL_VARIANTS

market_data = get_current_market_data()

async def test():
    instr = ALL_VARIANTS[1][1]  # V15
    up = BASE_USER_PROMPT.format(
        cn_indices=market_data["cn_indices"],
        us_data=market_data["us_data"],
        commodity_data=market_data["commodity_data"],
        news_data=market_data["news_data"],
        prompt_instructions=instr,
    )
    resp, elapsed = await call_llm(CURRENT_SYSTEM_PROMPT, up)
    parsed = parse_json(resp)
    analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "warnings": ["JSON parse failed"]}
    print(f"ETFs={analysis['total_etf_count']}, warns={len(analysis['warnings'])}, time={elapsed:.1f}s")

asyncio.run(test())