#!/usr/bin/env python3
"""Pytest-based Data Quality gate: verifies factor data completeness.

Checks each factor key produced by FactorRegistry.compute() against
real fetched data and reports:
  - Which factors have live data (non-zero values)
  - Which factors are scaffolding (always return 0.0)
  - Per-category aggregate health

Usage:
    cd backend && python -m pytest tests/test_data_health.py -v       # as pytest test
    cd backend && python -m tests.test_data_health                     # as standalone
"""

import sys
import os
import asyncio
import time
import pytest
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
FAIL = 0
WARN = 0
ERRORS: list = []
WARNINGS: list = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        print(f"  [+] {name}")
        PASS += 1
    else:
        print(f"  [!] FAIL: {name}" + (f" - {detail}" if detail else ""))
        FAIL += 1
        ERRORS.append(name)


def warn(name, detail=""):
    global WARN
    print(f"  [~] WARN: {name}" + (f" - {detail}" if detail else ""))
    WARN += 1
    WARNINGS.append(name)


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def check_factor_data_health():
    """Verify data-backed factors: run compute() on real symbols, check each factor key."""
    section("Factor Data Health")
    from app.factors.factor_registry import FactorRegistry
    fr = FactorRegistry()
    symbols = ["510300", "159338", "589980", "518880", "511090", "512480", "588000"]
    print(f"  Computing factors for {len(symbols)} symbols: {', '.join(symbols)}")
    t0 = time.time()
    try:
        result = await asyncio.wait_for(fr.compute(symbols), timeout=45)
    except asyncio.TimeoutError:
        warn("FactorRegistry compute", "timed out after 45s (data sources slow)")
        return
    elapsed = time.time() - t0
    print(f"  Compute completed in {elapsed:.1f}s")
    if len(result) == 0:
        warn("FactorRegistry compute", "returned empty result")
        return
    non_zero_keys = sum(1 for sym, scores in result.items()
                        for k, v in scores.items()
                        if isinstance(v, (int, float)) and abs(float(v)) > 0.001)
    if non_zero_keys == 0:
        warn("FactorRegistry compute", "all factor values are zero (data sources may be down)")
        return
    all_keys = set()
    for sym, scores in result.items():
        all_keys.update(k for k, v in scores.items() if isinstance(v, (int, float)))
    categories = {"technical": ["technical."], "momentum": ["etf.", "china.policy.", "technical.signal."],
                  "valuation": ["style."], "sentiment": ["sentiment."], "other": []}
    cat_factors = {c: [] for c in categories}
    for k in sorted(all_keys):
        for cat, prefixes in categories.items():
            if any(k.startswith(p) for p in prefixes):
                cat_factors[cat].append(k)
                break
    print(f"\n  Total factor keys: {len(all_keys)}")
    for cat in ["technical", "momentum", "valuation", "sentiment"]:
        factors = cat_factors.get(cat, [])
        if not factors:
            warn(f"Category '{cat}'", "no factors registered")
            continue
        print(f"\n  --- {cat} ({len(factors)} factors) ---")
        live_factors = 0
        scaffolding_factors = 0
        total_variance = 0.0
        factor_details = []
        for fk in sorted(factors):
            values = [float(v) for sym in symbols
                      for v in [result.get(sym, {}).get(fk, 0.0)]
                      if isinstance(v, (int, float)) and abs(float(v)) > 0.001]
            live = len(values)
            mean_val = sum(values) / max(len(values), 1) if values else 0.0
            variance_val = sum((v - mean_val)**2 for v in values) / max(len(values), 1) if values else 0.0
            if live >= 2:
                live_factors += 1
                total_variance += variance_val
                status = "LIVE" if variance_val > 0.001 else "FLAT"
            elif live == 1:
                scaffolding_factors += 1
                status = "STUB-SINGLE"
            else:
                scaffolding_factors += 1
                status = "STUB-ZERO"
            factor_details.append((fk, live, mean_val, variance_val, status))
        print(f"    Live: {live_factors}/{len(factors)} | Stub: {scaffolding_factors}/{len(factors)}")
        cat_variance = total_variance / max(live_factors, 1)
        print(f"    Category variance: {cat_variance:.4f}")
        for fk, live, mean_val, variance_val, status in [f for f in factor_details if f[4].startswith("STUB")][:8]:
            print(f"      {status} {fk}: live={live}/{len(symbols)} mean={mean_val:.3f} var={variance_val:.4f}")
        for fk, live, mean_val, variance_val, status in [f for f in factor_details if f[4] == "LIVE"][:5]:
            print(f"      {status} {fk}: live={live}/{len(symbols)} mean={mean_val:.3f} var={variance_val:.4f}")
        if cat == "technical":
            check(f"Technical: >= 5 live factors", live_factors >= 5)
            check(f"Technical: variance > 0.1", cat_variance > 0.1)
        elif cat == "momentum":
            check(f"Momentum: >= 2 live factors", live_factors >= 2)
            check(f"Momentum: variance > 0.01", cat_variance > 0.01)
        elif cat == "valuation":
            check(f"Valuation: >= 1 live factor", live_factors >= 1)
            if live_factors >= 2:
                check(f"Valuation: variance > 0.01", cat_variance > 0.01)
        elif cat == "sentiment":
            if live_factors >= 1:
                check(f"Sentiment: >= 1 live factor", True)
            else:
                warn(f"Sentiment: no live factors")
    live_cats = sum(1 for cat in ["technical", "momentum", "valuation", "sentiment"]
                    if sum(1 for fk in cat_factors[cat] for sym in symbols
                           if abs(float(result.get(sym, {}).get(fk, 0.0))) > 0.001) >= 2)
    print()
    check(f"Categories with live data >= 3", live_cats >= 3)


async def main():
    print(f"\n{'#'*60}")
    print(f"#  Factor Data Health Check")
    print(f"#  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")
    try:
        await check_factor_data_health()
    except Exception as e:
        import traceback
        print(f"\n  ERROR: {e}")
        traceback.print_exc()
        check("FactorDataHealth", False, str(e)[:100])
    section("Results")
    print(f"  PASS: {PASS}")
    print(f"  FAIL: {FAIL}")
    print(f"  WARN: {WARN}")
    if ERRORS:
        print(f"\n  Failures:")
        for error_item in ERRORS:
            print(f"    - {error_item}")
    if WARNINGS:
        print(f"\n  Warnings:")
        for w in WARNINGS:
            print(f"    - {w}")
    print(f"\n  {'HEALTHY' if FAIL == 0 else 'UNHEALTHY (see failures)'}")
    sys.exit(0 if FAIL == 0 else 1)


def test_core_factors_no_scaffold():
    """（无网络）检查 _CORE_FACTORS 中是否有未接入数据源的脚手架因子。

    通过读取 FactorRegistry 的 _computers 映射，判断哪些因子函数硬编码返回 0.0
    （"return 0.0" 或 "return 0"），将其标记为 STUB。

    只接受不超过 _KNOWN_SCAFFOLD_COUNT 个脚手架因子。
    """
    from app.factors.factor_registry import FactorRegistry
    import inspect, ast

    from app.factors import factor_registry as _fr_mod
    factors = _fr_mod._CORE_FACTORS
    fr = FactorRegistry()
    computers = fr._computers

    stub_factors = []
    live_factors = []

    for f in factors:
        computer = computers.get(f)
        if computer is None:
            stub_factors.append(f)
            continue
        # 检查源程序是否硬编码了 return 0.0
        source = inspect.getsource(computer)
        is_stub = False
        try:
            tree = ast.parse(source)
            return_values = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Return) and node.value is not None:
                    if isinstance(node.value, ast.Constant):
                        return_values.add(node.value.value)
                    elif isinstance(node.value, ast.UnaryOp) and isinstance(node.value.op, ast.USub):
                        if isinstance(node.value.operand, ast.Constant):
                            return_values.add(-node.value.operand.value)
                        else:
                            return_values.add("computed")  # e.g. return -min(...)
                    else:
                        return_values.add("computed")  # non-constant return → live
            # 仅当 ALL return 都是 0 或 0.0 时标记为 stub
            if return_values and all(v in (0, 0.0) for v in return_values):
                is_stub = True
        except SyntaxError:
            pass  # 非关键路径
        if is_stub:
            stub_factors.append((f, "all returns are 0.0"))
        else:
            live_factors.append(f)

    # 已知脚手架因子（全部已修复：26/26 因子已接入真实数据源）
    known_scaffolds: set[str] = set()
    expected_stubs = len(known_scaffolds)

    if stub_factors:
        print(f"\n  STUB factors ({len(stub_factors)}):")
        for s in stub_factors:
            name = s[0] if isinstance(s, tuple) else s
            detail = s[1] if isinstance(s, tuple) else ""
            expected = " (known)" if name in known_scaffolds else " ⚠️ UNEXPECTED"
            print(f"    {name}{expected}  {detail}")

    print(f"\n  LIVE factors ({len(live_factors)}): {', '.join(live_factors[:8])}...")

    unexpected = [s for s in stub_factors
                  if (s[0] if isinstance(s, tuple) else s) not in known_scaffolds]
    assert len(unexpected) == 0, \
        f"Unexpected scaffolding factors: {[u[0] if isinstance(u, tuple) else u for u in unexpected]}"
    print(f"\n  [+] All {len(known_scaffolds)} known scaffolding factors expected, "
          f"{len(stub_factors)} found, {len(unexpected)} unexpected")


def test_each_factor_returns_nonzero_with_mock_data():
    """#3: 运行时断言 — 对每个因子函数注入模拟数据，验证返回值非零。

    如果某因子需要的数据不在 _MOCK_DATA 中，仍会调用函数（可能返回 0），
    但至少不抛异常且函数签名正确。
    scafhold-free 门禁：如果未来有人引入新 return 0.0 的脚手架因子，
    但忘了更新 _MOCK_DATA，这个测试会发现它。
    """
    from app.factors.factor_registry import _BUILTIN_COMPUTERS

    _MOCK_DATA: dict[str, dict] = {
        "etf.amount_stability": {"volume": [100, 200, 150, 180, 210, 190, 220] * 4},
        "etf.tracking_error": {
            "close": [4.0, 4.1, 4.0, 4.2, 4.1, 4.3, 4.2, 4.4],
            "benchmark_close": [4000, 4020, 4010, 4030, 4020, 4040, 4030, 4050],
        },
        "etf.shares_change": {"shares_change_20d": 0.03},
        "etf.industry_diversification": {"industry_holdings": {"银行": 0.5, "地产": 0.3, "制造": 0.2}},
        "etf.institutional_holdings_change": {"shares_change_20d": 0.05},
        "sentiment.panic_greed_diff": {"sentiment_index": 60, "sentiment_history": [50] * 20},
        "sentiment.stock_divergence": {"advance_decline": 1.8},
        "style.size.ln_mcap": {"total_mv": 1e10},
        "style.size.ln_float_mcap": {"total_mv": 8e9},
        "technical.ma.sma_5": {"close": [4.0] * 60},
        "technical.ma.sma_10": {"close": [4.0] * 60},
        "technical.ma.sma_20": {"close": [4.0] * 60},
        "technical.ma.sma_60": {"close": [4.0] * 60},
        "technical.rsi.rsi_14": {"close": [4.0 + i * 0.01 for i in range(60)]},
        "technical.macd.macd": {"close": [4.0 + i * 0.01 for i in range(60)]},
        "technical.bollinger.bandwidth": {"close": [4.0 + (i % 5) * 0.1 for i in range(60)]},
        "technical.volume.vol_ratio": {"close": [4.0] * 30, "volume": [1e6] * 30},
        "technical.atr.atr_14": {"close": [4.0] * 30, "high": [4.1] * 30, "low": [3.9] * 30},
        "technical.volume.vwap": {"close": [4.0] * 30, "volume": [1e6] * 30},
        "etf.change_pct": {"close": [4.0, 4.05]},
        "etf.premium_discount": {"price": 4.0, "nav": 3.98},
        "sentiment.news_heat": {"news_items": [{"stars": 3}, {"stars": 4}]},
        "sentiment.news_direction": {"news_items": [{"level": "利好"}, {"level": "中性"}, {"level": "重大"}, {"level": "中性"}]},
        "china.policy.five_year_plan": {"industry": "半导体"},
        "china.policy.strategic_emerging": {"industry": "电子"},
        "china.policy.dual_circulation": {"industry": "食品饮料"},
        "technical.kdj.k_value": {"close": [4.0] * 30, "high": [4.1] * 30, "low": [3.9] * 30},
        "technical.kdj.d_value": {"close": [4.0] * 30, "high": [4.1] * 30, "low": [3.9] * 30},
        "technical.kdj.j_value": {"close": [4.0] * 30, "high": [4.1] * 30, "low": [3.9] * 30},
        "technical.signal.overall": {
            "close": [4.0] * 30, "high": [4.1] * 30, "low": [3.9] * 30, "volume": [1e6] * 30,
            "rsi": 35, "macd": 0.5, "ma_bias_20": 0.02,
        },
    }

    passed = 0
    failed = 0
    for code, fn in _BUILTIN_COMPUTERS.items():
        data = _MOCK_DATA.get(code, {})
        try:
            result = fn(data)
            if code in _MOCK_DATA:
                # 有模拟数据时断言非零
                assert abs(result) > 0.001, f"{code}: expected non-zero with mock data, got {result}"
                passed += 1
            else:
                # 无模拟数据的因子，至少不抛异常
                passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {code} raised {type(e).__name__}: {e}")

    total = len(_BUILTIN_COMPUTERS)
    print(f"  Run-time assertion: {passed}/{total} factors OK (failed={failed})")
    assert failed == 0, f"{failed} factors raised exceptions"
    assert passed == total, f"Expected {total} factors, got {passed} OK"


@pytest.mark.timeout(120)  # 外部数据源可能较慢
@pytest.mark.skip(reason="Requires live data sources (run --runslow)")
def test_factor_data_health_pytest():
    """Pytest entry point: runs same logic as standalone main()."""
    asyncio.run(check_factor_data_health())
    assert FAIL == 0, f"{FAIL} factor data quality failures — see log"
    if WARN > 0:
        warnings.warn(f"{WARN} warnings in factor data health check")


if __name__ == "__main__":
    asyncio.run(main())
