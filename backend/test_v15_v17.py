import asyncio, sys, json
sys.path.insert(0, '.')

from prompt_optimizer import get_current_market_data, CURRENT_SYSTEM_PROMPT, BASE_USER_PROMPT, call_llm, parse_json, analyze_output, ALL_VARIANTS

async def main():
    m = get_current_market_data()
    print(f"CN: {len(m['cn_indices'].split(chr(10)))} lines")
    
    # Run V15, V16, V17 (indices 1, 2, 3 in ALL_VARIANTS)
    for i in range(1, 4):
        name, instr = ALL_VARIANTS[i]
        round_num = 15 + i - 1
        
        up = BASE_USER_PROMPT.format(
            cn_indices=market_data["cn_indices"],
            us_data=market_data["us_data"],
            commodity_data=market_data["commodity_data"],
            news_data=market_data["news_data"],
            prompt_instructions=ALL_VARIANTS[i][1]
        )
        
        print(f"\n{'='*60}")
        print(f"  Round {15+i-1}: {ALL_VARIANTS[i][0]}")
        print(f"{'='*60}")
        
        try:
            response, elapsed = await call_llm(CURRENT_SYSTEM_PROMPT, up)
            parsed = parse_json(response)
            analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "warnings": ["JSON parse failed"]}
            print(f"  V{15+i-1}: ETFs={analysis['total_etf_count']}, warns={len(analysis['warnings'])}, time={elapsed:.1f}s")
        except Exception as e:
            print(f"  ERROR: {e}")

async def main():
    m = get_current_market_data()
    print(f"CN: {len(m['cn_indices'].split(chr(10)))} lines")
    
    for i in range(1, 4):  # V15, V16, V17
        name, instr = ALL_VARIANTS[i]
        round_num = 15 + i - 1
        
        up = BASE_USER_PROMPT.format(
            cn_indices=m["cn_indices"],
            us_data=m["us_data"],
            commodity_data=m["commodity_data"],
            news_data=m["news_data"],
            prompt_instructions=instr
        )
        
        print(f"\n{'='*60}")
        print(f"  Round {round_num}: {ALL_VARIANTS[i][0]}")
        print(f"{'='*60}")
        
        try:
            response, elapsed = await call_llm(CURRENT_SYSTEM_PROMPT, up)
            parsed = parse_json(response)
            analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "warnings": ["JSON parse failed"]}
            print(f"  V{round_num}: ETFs={analysis['total_etf_count']}, warns={len(analysis['warnings'])}, time={elapsed:.1f}s")
        except Exception as e:
            print(f"  ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())