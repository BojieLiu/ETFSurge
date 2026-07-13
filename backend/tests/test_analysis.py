"""End-to-end tests for analysis endpoints."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.analysis import portfolio_design, llm_report


async def test_portfolio_design():
    print("=" * 60)
    print("Test: portfolio_design")
    print("=" * 60)
    try:
        result = await portfolio_design()
        print(f"Status: OK")
        print(f"Keys: {list(result.keys())}")
        print(f"Portfolios: {len(result.get('portfolios', []))}")
        print(f"Indices: {len(result.get('indices', []))}")
        print(f"Commodities: {len(result.get('commodities', []))}")
        print(f"Has comparison: {'comparison' in result}")

        if result.get("portfolios"):
            for pf in result["portfolios"]:
                print(f"\n  [{pf['type']}] {pf['name']}")
                print(f"    risk={pf['risk_level']} return={pf['expected_return']} drawdown={pf.get('max_drawdown')}")
                print(f"    cash_weight={pf.get('cash_weight')}")
                print(f"    suitable_for={pf.get('suitable_for')}")
                print(f"    operating_guidelines={pf.get('operating_guidelines')}")
                print(f"    risk_warnings={pf.get('risk_warnings')}")
                etfs = pf.get("etfs", [])
                print(f"    ETFs ({len(etfs)}):")
                for e in etfs:
                    print(f"      {e['symbol']} {e['name']} {e['weight']*100:.0f}% - {e['reason'][:60]}...")
                total_w = sum(e["weight"] for e in etfs)
                cw = pf.get("cash_weight", 0) or 0
                print(f"    sum(etf_weight)={total_w:.2f} cash_weight={cw:.2f} total={total_w+cw:.2f}")
                assert abs(total_w + cw - 1.0) < 0.01, f"Weight sum {total_w + cw} != 1.0"
        else:
            print("  WARNING: No portfolios returned!")

        # Validate JSON serialization
        json_str = json.dumps(result, ensure_ascii=False, default=str)
        print(f"\nJSON size: {len(json_str)} bytes - OK")

    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()


async def test_llm_report():
    print("\n" + "=" * 60)
    print("Test: llm_report (no symbols)")
    print("=" * 60)
    try:
        result = await llm_report(None)
        print(f"Status: OK")
        print(f"Keys: {list(result.keys())}")
        report = result.get("report", "")
        print(f"Report length: {len(report)} chars")
        if report:
            print(f"Report preview: {report[:200]}...")
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()


async def main():
    await test_portfolio_design()
    await test_llm_report()

    print("\n" + "=" * 60)
    print("ALL TESTS DONE")


if __name__ == "__main__":
    asyncio.run(main())
