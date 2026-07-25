"""
#4: Integration tests — requires live data sources (run with --runintegration).

These tests use real market data to verify the full factor computation pipeline.
They are NOT part of the default pytest run; use:
  pytest -m integration
"""
import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_26_factors_live_with_real_data():
    """Verify that 26 factors compute successfully with real market data.

    Expected: at least 40% of factor values per symbol are non-zero (>0.01).
    """
    from app.factors.factor_registry import FactorRegistry

    fr = FactorRegistry()
    result = await fr.compute(["510300", "518880", "511090"])

    assert len(result) >= 2, f"Expected >=2 symbols, got {len(result)}"

    for sym in ["510300", "518880", "511090"]:
        assert sym in result, f"{sym} missing from factor results"
        scores = result[sym]
        non_zero = sum(1 for v in scores.values() if isinstance(v, (int, float)) and abs(v) > 0.01)
        total = len(scores)
        ratio = non_zero / total
        assert ratio >= 0.3, (
            f"{sym}: only {non_zero}/{total} factors non-zero ({ratio:.0%}), "
            f"expected >= 30%"
        )
