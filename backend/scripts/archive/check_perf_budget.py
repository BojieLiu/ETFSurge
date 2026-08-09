#!/usr/bin/env python3
"""Performance Budget Check — verify backend warmup stays within budget.

Usage:
    python scripts/check_perf_budget.py [--baseline baseline.json]

Checks:
1. Warmup time < 5s (P0 target)
2. Average API response time < 3s (P1 target)
3. No single endpoint exceeds 10s (P2 target)

Exits with code 1 if any check fails, 0 if all pass.
"""

import json
import sys
import time
from pathlib import Path

_BASELINE_FILE = Path(__file__).parent.parent / "backend" / "logs" / "warmup_timing.json"
_SCRIPTS_DIR = Path(__file__).parent.parent / "backend" / "scripts"
_PERF_DIAG_FILE = Path(__file__).parent.parent / "backend" / "logs" / "perf_diag_results.json"

# Budget thresholds (in seconds)
BUDGETS = {
    "warmup_total": 5.0,        # P0: warmup < 5s
    "api_avg": 3.0,             # P1: avg endpoint < 3s
    "api_max": 10.0,            # P2: no endpoint > 10s
    "factor_health": 3.0,       # P1: factor-health < 3s (with cache)
    "watchlist": 3.0,           # P1: watchlist < 3s
}


def check_warmup() -> list[str]:
    """Check warmup total time against budget."""
    failures = []
    if not _BASELINE_FILE.exists():
        failures.append(f"Warmup baseline not found: {_BASELINE_FILE}")
        return failures

    try:
        data = json.loads(_BASELINE_FILE.read_text(encoding="utf-8"))
        total = data.get("total_ms", 0) / 1000.0
        budget = BUDGETS["warmup_total"]
        if total > budget:
            failures.append(
                f"Warmup {total:.1f}s exceeds budget {budget:.1f}s"
            )
        else:
            print(f"  [PASS] Warmup {total:.1f}s <= {budget:.1f}s budget")
    except (json.JSONDecodeError, KeyError) as e:
        failures.append(f"Failed to parse warmup timing: {e}")

    return failures


def check_api_perf() -> list[str]:
    """Check API endpoint performance against budgets."""
    failures = []
    if not _PERF_DIAG_FILE.exists():
        failures.append(f"Perf diag results not found: {_PERF_DIAG_FILE}")
        return failures

    try:
        data = json.loads(_PERF_DIAG_FILE.read_text(encoding="utf-8"))
        endpoints = data.get("results", data.get("endpoints", []))
        if not endpoints:
            failures.append("No endpoint data in perf diag results")
            return failures

        times = []
        slow_endpoints = []
        for ep in endpoints:
            name = ep.get("endpoint", ep.get("name", "unknown"))
            duration = ep.get("duration_ms", ep.get("time_ms", 0)) / 1000.0
            times.append(duration)

            if duration > BUDGETS["api_max"]:
                slow_endpoints.append(f"{name}: {duration:.1f}s")
                failures.append(
                    f"  [FAIL] {name}: {duration:.1f}s exceeds max budget "
                    f"{BUDGETS['api_max']:.1f}s"
                )
            elif duration > BUDGETS["api_avg"]:
                failures.append(
                    f"  [WARN] {name}: {duration:.1f}s exceeds avg budget "
                    f"{BUDGETS['api_avg']:.1f}s"
                )
            else:
                print(f"  [PASS] {name}: {duration:.1f}s")

        avg = sum(times) / len(times) if times else 0
        if avg > BUDGETS["api_avg"]:
            failures.append(
                f"  [FAIL] Avg response {avg:.1f}s exceeds budget "
                f"{BUDGETS['api_avg']:.1f}s"
            )
        else:
            print(f"  [PASS] Avg response {avg:.1f}s <= {BUDGETS['api_avg']:.1f}s")

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        failures.append(f"Failed to parse perf diag: {e}")

    return failures


def main():
    print("Performance Budget Check")
    print(f"Budgets: {json.dumps(BUDGETS, indent=2)}")
    print()

    all_failures = []
    all_failures.extend(check_warmup())
    all_failures.extend(check_api_perf())

    print()
    if all_failures:
        print(f"FAILURES ({len(all_failures)}):")
        for f in all_failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print("All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
