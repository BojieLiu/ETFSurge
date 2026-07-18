"""因子模型集成测试 — Phase 1: 12 个因子接入策略引擎。

P1-1: compute() 使用真实因子值（非 0 非 0.5）
P1-2: 跨符号 z-score 标准化 (mean~0, std~1)
P1-3: compute() 直接注入市场数据
"""

import pytest
from unittest.mock import patch, AsyncMock, Mock


# --- P1-1: FactorRegistry 真实因子值 ---

@pytest.mark.asyncio
async def test_p1_factor_computes_real_values():
    """compute() returns non-zero factor values with real OHLCV input."""
    from app.factors.factor_registry import registry

    symbols = ["510300", "518880", "510880"]
    market_data = {
        "510300": {
            "total_mv": 500e9, "float_mv": 400e9,
            "close": [4.0 + i * 0.005 for i in range(60)],
            "high": [4.0 + i * 0.01 for i in range(60)],
            "low": [4.0 - i * 0.003 for i in range(60)],
            "volume": [2_000_000 + i * 500 for i in range(60)],
        },
        "518880": {
            "total_mv": 200e9, "float_mv": 160e9,
            "close": [6.0 + i * 0.008 for i in range(60)],
            "high": [6.0 + i * 0.015 for i in range(60)],
            "low": [6.0 - i * 0.005 for i in range(60)],
            "volume": [500_000 + i * 200 for i in range(60)],
        },
        "510880": {
            "total_mv": 100e9, "float_mv": 80e9,
            "close": [3.0 + i * 0.003 for i in range(60)],
            "high": [3.0 + i * 0.006 for i in range(60)],
            "low": [3.0 - i * 0.002 for i in range(60)],
            "volume": [800_000 + i * 300 for i in range(60)],
        },
    }

    result = await registry.compute(symbols, market_data=market_data)

    for sym in symbols:
        scores = result.get(sym, {})
        assert scores, f"compute() returned empty for {sym}"
        non_zero = [v for v in scores.values() if abs(v) > 0.001]
        assert len(non_zero) >= 3, (
            f"Expected >=3 non-zero factor values for {sym}, got {len(non_zero)}"
        )


# --- P1-2: z-score 标准化 ---

@pytest.mark.asyncio
async def test_p1_zscore_standardization():
    """Cross-symbol z-score: mean~0, std~1 for each factor."""
    from app.factors.factor_registry import registry
    import statistics

    symbols = ["510300", "518880", "510880", "512480", "159766"]
    market_data = {
        sym: {
            "total_mv": 100e9 + i * 50e9,
            "float_mv": 80e9 + i * 40e9,
            "close": [4.0 + i * 0.01 * (j/60) for j in range(60)],
            "high": [4.0 + i * 0.02 * (j/60) for j in range(60)],
            "low": [4.0 - i * 0.005 * (j/60) for j in range(60)],
            "volume": [1_000_000 + i * 10_000 * (j/60) for j in range(60)],
        }
        for i, sym in enumerate(symbols)
    }

    result = await registry.compute(symbols, market_data=market_data)

    factor_codes = ["style.size.ln_mcap", "technical.ma.sma_20"]
    for code in factor_codes:
        vals = [result.get(sym, {}).get(code, 0) for sym in symbols]
        mean = statistics.mean(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 1.0
        assert abs(mean) < 0.05, f"z-score mean for {code} should be ~0, got {mean:.4f}"
        assert abs(std - 1.0) < 0.05, f"z-score std for {code} should be ~1, got {std:.4f}"


# --- P1-3: compute_all 方法 ---

@pytest.mark.asyncio
async def test_p1_compute_all_with_market_data():
    """compute() with direct market_data returns valid factor vectors."""
    from app.factors.factor_registry import registry

    symbols = ["510300", "518880"]
    market_data = {
        "510300": {
            "total_mv": 500e9, "float_mv": 400e9,
            "close": [4.0 * (1 + 0.01 * j) for j in range(60)],
            "high": [4.0 * (1 + 0.02 * j) for j in range(60)],
            "low": [4.0 * (1 - 0.005 * j) for j in range(60)],
            "volume": [2_000_000 + j * 1000 for j in range(60)],
        },
        "518880": {
            "total_mv": 200e9, "float_mv": 160e9,
            "close": [6.0 * (1 + 0.015 * j) for j in range(60)],
            "high": [6.0 * (1 + 0.025 * j) for j in range(60)],
            "low": [6.0 * (1 - 0.008 * j) for j in range(60)],
            "volume": [500_000 + j * 500 for j in range(60)],
        },
    }

    result = await registry.compute(symbols, market_data=market_data)

    for sym in symbols:
        scores = result.get(sym, {})
        assert len(scores) >= 8, f"Expected >=8 factor values for {sym}, got {len(scores)}"

    mcap_a = result["510300"].get("style.size.ln_mcap", 0)
    mcap_b = result["518880"].get("style.size.ln_mcap", 0)
    assert abs(mcap_a - mcap_b) > 0.01, "ln_mcap should differ across symbols after z-score"
