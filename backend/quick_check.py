import asyncio, sys
sys.path.insert(0, '.')

from prompt_optimizer_clean import get_current_market_data, CURRENT_SYSTEM_PROMPT, BASE_USER_PROMPT, call_llm, parse_json, analyze_output, INSTRUCTIONS

async def test():
    m = get_current_market_data()
    up = BASE_USER_PROMPT.format(cn_indices=m['cn_indices'], us_data=m['us_data'], commodity_data=m['commodity_data'], news_data=m['news_data'], prompt_instructions=INSTRUCTIONS)
    r, t = await call_llm(CURRENT_SYSTEM_PROMPT, up)
    parsed = parse_json(r)
    a = analyze_output(parsed) if parsed.get('portfolios') else {'total_etf_count': 0}
    print(f"ETFs={a['total_etf_count']}, time={t:.1f}s")

asyncio.run(test())