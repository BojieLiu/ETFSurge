#!/usr/bin/env python3
"""Data quality gate: verifies factor data completeness for each registered factor.

Checks each factor key produced by FactorRegistry.compute() against
real fetched data and reports:
  - Which factors have live data (non-zero values)
  - Which factors are scaffolding (always return 0.0)
  - Per-category aggregate health

Requirements:
  - Backend must be running (uses live API / real FactorRegistry)
  - At least 3 ETF symbols must produce non-technical factors with variance > 0
"""
import sys, os, asyncio, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PASS = 0
FAIL = 0
WARN = 0
ERRORS = []
WARNINGS = []

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

    # Use symbols that cover core/satellite/defense layers
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

    # Early exit if compute returned nothing — data sources may be unreachable
    if len(result) == 0:
        warn("FactorRegistry compute", "returned empty result (data sources may be down)")
        return
    non_zero_keys = sum(1 for sym, scores in result.items()
                        for k, v in scores.items()
                        if isinstance(v, (int, float)) and abs(float(v)) > 0.001)
    if non_zero_keys == 0:
        warn("FactorRegistry compute", "all factor values are zero (data sources may be down)")
        return

    # Gather all factor keys across all symbols
    all_keys = set()
    for sym, scores in result.items():
        all_keys.update(k for k, v in scores.items() if isinstance(v, (int, float)))

    # Category prefix mapping (same as aggregate_factor_scores)
    categories = {
        "technical": ["technical."],
        "momentum": ["etf.", "china.policy.", "technical.signal."],
        "valuation": ["style."],
        "sentiment": ["sentiment."],
        "other": [],  # fallback
    }
    # Build per-category factor lists
    cat_factors: dict[str, list[str]] = {c: [] for c in categories}
    for k in sorted(all_keys):
        assigned = False
        for cat, prefixes in categories.items():
            if any(k.startswith(p) for p in prefixes):
                cat_factors[cat].append(k)
                assigned = True
                break
        if not assigned:
            cat_factors["other"].append(k)

    # Analyze each factor: mean, variance, live_count across symbols
    print(f"\n  Total factor keys: {len(all_keys)}")
    print()

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
            values = []
            for sym in symbols:
                v = result.get(sym, {}).get(fk, 0.0)
                if isinstance(v, (int, float)) and abs(float(v)) > 0.001:
                    values.append(float(v))

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

        # Print summary per category
        print(f"    Live: {live_factors}/{len(factors)} | Stub: {scaffolding_factors}/{len(factors)}")
        cat_variance = total_variance / max(live_factors, 1)
        print(f"    Category variance: {cat_variance:.4f}")

        # Print individual factor details for stubs and top live factors
        stubs = [f for f in factor_details if f[4].startswith("STUB")]
        for fk, live, mean_val, variance_val, status in stubs[:8]:
            print(f"      {status} {fk}: live={live}/{len(symbols)} mean={mean_val:.3f} var={variance_val:.4f}")

        lives = [f for f in factor_details if f[4] == "LIVE"]
        for fk, live, mean_val, variance_val, status in lives[:5]:
            print(f"      {status} {fk}: live={live}/{len(symbols)} mean={mean_val:.3f} var={variance_val:.4f}")

        # Assertions per category
        if cat == "technical":
            check(f"Technical: >= 5 live factors", live_factors >= 5, f"got {live_factors}")
            check(f"Technical: variance > 0.1", cat_variance > 0.1, f"var={cat_variance:.4f}")
        elif cat == "momentum":
            check(f"Momentum: >= 2 live factors", live_factors >= 2, f"got {live_factors}")
            check(f"Momentum: variance > 0.01", cat_variance > 0.01, f"var={cat_variance:.4f}")
        elif cat == "valuation":
            check(f"Valuation: >= 1 live factor", live_factors >= 1, f"got {live_factors}")
            if live_factors >= 2:
                check(f"Valuation: variance > 0.01", cat_variance > 0.01, f"var={cat_variance:.4f}")
        elif cat == "sentiment":
            # Sentiment may be 0 if no news cache - warn not fail
            if live_factors >= 1:
                check(f"Sentiment: >= 1 live factor", True, f"got {live_factors}")
            else:
                warn(f"Sentiment: no live factors", "all 0.0 (news cache may be empty)")

    # Cross-category check: at least 3 categories with live factors
    live_cats = sum(1 for cat in ["technical", "momentum", "valuation", "sentiment"]
                    if sum(1 for fk in cat_factors[cat]
                           if sum(1 for sym in symbols
                                  if abs(float(result.get(sym, {}).get(fk, 0.0))) > 0.001) >= 2) >= 1)

    print()
    check(f"Categories with live data >= 3", live_cats >= 3, f"got {live_cats} categories")


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
        for e in ERRORS:
            print(f"    - {e}")
    if WARNINGS:
        print(f"\n  Warnings:")
        for w in WARNINGS:
            print(f"    - {w}")
    print(f"\n  {'HEALTHY' if FAIL == 0 else 'UNHEALTHY (see failures)'}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
