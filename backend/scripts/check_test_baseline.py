"""P3-6: Test redundancy baseline gate (round11-code-redundancy.md §8.2).

Counts backend/tests/test_*.py and fails if the number exceeds the frozen
baseline. New tests must be merged into existing files (or the baseline must
be explicitly bumped in this script) to prevent test-file proliferation from
recurring after the P1-8 7-group consolidation (226 -> 197 files).

Usage:
    python scripts/check_test_baseline.py            # check only
    python scripts/check_test_baseline.py --print    # print current count only
"""
from __future__ import annotations

import pathlib
import sys

TESTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "tests"

# Frozen baseline after P1-8 consolidation (2026-08-09, HEAD=eff796c).
# 226 -> 197 test files (docs target ~199). Bump ONLY via conscious review.
BASELINE = 197


def count_test_files() -> int:
    return len(list(TESTS_DIR.glob("test_*.py")))


def main() -> int:
    if "--print" in sys.argv:
        print(count_test_files())
        return 0

    n = count_test_files()
    if n <= BASELINE:
        print(f"[P3-6] test file count {n} <= baseline {BASELINE}: OK")
        return 0

    print(f"[P3-6] FAIL: test file count {n} > baseline {BASELINE}")
    print("  New tests must be merged into existing test files.")
    print("  If a new test file is truly required, bump BASELINE in "
          "scripts/check_test_baseline.py with review, then commit.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
