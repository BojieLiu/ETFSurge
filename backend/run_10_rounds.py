"""
Run 10 rounds of prompt optimization with constraint validation.
Each round tests a different prompt variant, validates constraints, and scores.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from prompt_optimizer_clean import (
    VARIANTS,
    call_llm,
    parse_json,
    analyze_output,
    score_portfolio,
    get_current_market_data,
)

async def run_round(round_num: int, name: str, instructions: str, market_data: dict) -> dict:
    """Run a single optimization round with constraint validation."""
    from app.analysis.llm import SYSTEM_PROMPT, generate_portfolio_design, _validate_portfolio_constraints
    import json as jsonlib
    
    # Build user prompt
    from prompt_optimizer_clean import BASE_USER_PROMPT
    user_prompt = BASE_USER_PROMPT.format(
        cn_indices=market_data["cn_indices"],
        us_data=market_data["us_data"],
        commodity_data=market_data["commodity_data"],
        news_data=market_data["news_data"],
        prompt_instructions=instructions,
    )
    
    print(f"\n{'='*60}")
    print(f"Round {round_num}: {name}")
    print(f"{'='*60}")
    
    # Try up to 2 times (original + 1 retry on validation failure)
    for attempt in range(2):
        try:
            # Call LLM
            response, _ = await call_llm(SYSTEM_PROMPT, user_prompt)
            parsed = parse_json(response)
            
            if not parsed.get("portfolios"):
                raise ValueError("No portfolios in response")
            
            # Validate constraints
            validation_errors = _validate_portfolio_constraints(parsed)
            if validation_errors:
                print(f"  [WARN] Validation failed (attempt {attempt+1}):")
                for e in validation_errors:
                    print(f"    - {e}")
                if attempt == 0:
                    # Retry with error feedback
                    retry_prompt = user_prompt + "\n\n[WARN] 上次生成违反硬性约束，请修正：\n" + "\n".join(f"- {e}" for e in validation_errors)
                    user_prompt = retry_prompt
                    continue
                else:
                    print(f"  [FAIL] Validation failed after retry")
            else:
                print(f"  [OK] Validation passed")
            
            # Analyze and score
            analysis = analyze_output(parsed)
            score_result = await score_portfolio(parsed)
            
            return {
                "round": round_num,
                "name": name,
                "attempt": attempt + 1,
                "validation_errors": validation_errors,
                "analysis": analysis,
                "score": score_result,
            }
            
        except Exception as e:
            print(f"  [FAIL] Error (attempt {attempt+1}): {e}")
            if attempt == 1:
                return {
                    "round": round_num,
                    "name": name,
                    "attempt": attempt + 1,
                    "error": str(e),
                    "analysis": {},
                    "score": {"total_score": 0},
                }
    
    return {
        "round": round_num,
        "name": name,
        "attempt": 2,
        "error": "Max retries exceeded",
        "analysis": {},
        "score": {"total_score": 0},
    }


async def main():
    # Get current market data
    print("Fetching market data...")
    market_data = get_current_market_data()
    print(f"Market data fetched: {len(market_data['cn_indices'])} lines CN, {len(market_data['us_data'])} lines US")
    
    # Select 10 variants to test (V8 + 9 new variants)
    test_variants = [
        ("V8: Precise v2", VARIANTS[7][1]),  # V8 was best before
        ("V34: A500+Strategy indices", "V34" in str(VARIANTS) and [v for v in VARIANTS if "V34" in v[0]][0][1] if any("V34" in v[0] for v in VARIANTS) else ""),
    ]
    
    # Actually let's pick 10 specific variants
    # We'll use the last 10 variants (V44-V53) since they're newest
    variants_to_test = VARIANTS[-5:]  # Last 5 variants for faster test
    
    results = []
    for i, (name, instructions) in enumerate(variants_to_test):
        result = await run_round(i+1, name, instructions, market_data)
        results.append(result)
    
    # Save results
    with open("optimization_results_v2.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # Print summary
    print("\n" + "="*80)
    print("OPTIMIZATION SUMMARY")
    print("="*80)
    for r in results:
        if "score" in r and "total_score" in r["score"]:
            score = r["score"]["total_score"]
            etfs = r.get("analysis", {}).get("total_etf_count", 0)
            warns = len(r.get("analysis", {}).get("warnings", []))
            val_ok = "✅" if not r.get("validation_errors") else "❌"
            print(f"  {r['name']}: score={score:.1f}, ETFs={etfs}, warns={warns}, val={val_ok}")
        elif "error" in r:
            print(f"  {r['name']}: ERROR - {r['error']}")
    
    # Find best
    valid_results = [r for r in results if "score" in r and "total_score" in r["score"] and r["score"]["total_score"] > 0 and not r.get("validation_errors")]
    if valid_results:
        best = max(valid_results, key=lambda r: r["score"]["total_score"])
        print(f"\n🏆 BEST: {best['name']} (score={best['score']['total_score']:.1f})")
        
        # Save best to platform
        with open("best_prompt_v2.json", "w", encoding="utf-8") as f:
            json.dump(best, f, ensure_ascii=False, indent=2)
        print("Saved best prompt to best_prompt_v2.json")


if __name__ == "__main__":
    asyncio.run(main())