"""
Run 10 rounds of prompt optimization with constraint validation.
Each round tests a different prompt variant, validates constraints, and scores.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from prompt_optimizer_clean import (
    VARIANTS,
    get_current_market_data,
    call_llm,
    parse_json,
    analyze_output,
    score_portfolio,
)
from app.analysis.llm import SYSTEM_PROMPT, generate_portfolio_design, _validate_portfolio_constraints

# Select 10 variants to test (V8 + 9 newest ones)
test_variants = [
    ("V8: Precise v2", VARIANTS[7][1]),
    ("V44: CSI/CNII/HSI official index pool", VARIANTS[-10][1]),
]


async def run_round(round_num: int, name: str, instructions: str, market_data: dict) -> dict:
    """Run a single optimization round with constraint validation."""
    print(f"\n{'='*60}")
    print(f"Round {round_num}: {name}")
    print(f"{'='*60}")

    user_prompt = (
        "# 任务\n"
        "基于以下最新行情数据，设计三套 ETF 组合策略（进攻型、平衡型、防御型）。\n\n"
        "# 输入数据\n"
        f"## A股市场\n{market_data['cn_indices']}\n\n"
        f"## 美股市场\n{market_data['us_data']}\n\n"
        f"## 港股市场\n- 恒生指数：（暂无数据）\n- 恒生科技指数：（暂无数据）\n\n"
        f"## 大宗商品\n{market_data['commodity_data']}\n\n"
        f"## 宏观背景\n{market_data['news_data']}\n\n"
        f"# 优化指令\n{instructions}"
    )

    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            print(f"  Attempt {attempt + 1}...")
            t0 = time.time()
            response, elapsed = await call_llm(SYSTEM_PROMPT, user_prompt)
            print(f"  LLM returned in {elapsed:.1f}s, length={len(response)}")

            if not response or len(response) < 100:
                raise ValueError("Empty or too short response")

            parsed = parse_json(response)
            if not parsed or not parsed.get("portfolios"):
                raise ValueError("JSON parse failed or no portfolios")

            # Validate constraints
            validation_errors = _validate_portfolio_constraints(parsed)
            if validation_errors:
                print(f"  [WARN] Constraint violations ({len(validation_errors)}):")
                for e in validation_errors:
                    print(f"    - {e}")
                if attempt == 0:
                    # Retry with error feedback
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
                "elapsed": elapsed,
                "validation_errors": validation_errors,
                "analysis": analysis,
                "score": score_result,
            }

        except Exception as e:
            print(f"  [ERROR] (attempt {attempt + 1}): {e}")
            if attempt == max_attempts - 1:
                return {
                    "round": round_num,
                    "name": name,
                    "attempt": attempt + 1,
                    "error": str(e),
                }

    return {"round": round_num, "name": name, "error": "Max retries exceeded"}


async def main():
    print("=" * 60)
    print("  10-Round Prompt Optimization with Constraint Validation")
    print("=" * 60)

    print("Fetching market data...")
    market_data = get_current_market_data()
    print(f"  CN indices: {len(market_data['cn_indices'].split(chr(10)))} lines")
    print(f"  US data: {len(market_data['us_data'].split(chr(10)))} lines")
    print(f"  Commodities: {len(market_data['commodity_data'].split(chr(10)))} lines")
    print(f"  News: {len(market_data['news_data'].split(chr(10)))} lines")

    results = []
    for i, (name, instructions) in enumerate(test_variants):
        result = await run_round(i + 1, name, instructions, market_data)
        results.append(result)

    # Save results
    output_file = "optimization_results_v2.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_file}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    valid_results = [r for r in results if "error" not in r and not r.get("validation_errors")]
    for r in results:
        name = r.get("name", "unknown")
        if "error" in r:
            print(f"  [FAIL] {name}: {r['error']}")
        elif r.get("validation_errors"):
            print(f"  [WARN] {name}: {len(r['validation_errors'])} violations, score={r.get('score', {}).get('total_score', 0):.1f}")
        else:
            score = r.get("score", {}).get("total_score", 0)
            etfs = r.get("analysis", {}).get("total_etf_count", 0)
            warns = len(r.get("analysis", {}).get("warnings", []))
            print(f"  [OK] {name}: score={score:.1f}, ETFs={etfs}, warnings={warns}")

    if valid_results:
        best = max(valid_results, key=lambda r: r.get("score", {}).get("total_score", 0))
        print(f"\n[BEST] {best['name']} (score={best['score']['total_score']:.1f})")
        with open("best_prompt_v2.json", "w", encoding="utf-8") as f:
            json.dump(best, f, ensure_ascii=False, indent=2)
        print("Saved best to best_prompt_v2.json")


if __name__ == "__main__":
    asyncio.run(main())