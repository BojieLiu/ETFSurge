"""
check_routes.py — API Route Contract Verification (方案 C1)

Walks all registered FastAPI routes, parses expected routes from api-contracts/*.md,
and reports mismatches. Exits with non-zero when a discrepancy is found.

Usage:
    cd backend && python scripts/check_routes.py
    python scripts/check_routes.py --fix    # Print report only
    python scripts/check_routes.py --json   # Output as JSON for CI
"""
import argparse
import glob
import json
import os
import re
import sys

# Add backend/ to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Expected routes from api-contracts ──────────────────────────

def _parse_contract_method(path: str) -> str | None:
    """Parse an HTTP method from a contract file line.

    Contract files use varied formats: `GET /api/v1/x`, `### 2.1 GET /api/v1/x`,
    `| GET /api/v1/x |` (table), `**GET** /api/v1/x`. Match the method token
    anywhere before a /api/v1 path.
    """
    m = re.search(r"(GET|POST|PUT|DELETE|PATCH)[*`]*\s+`?(/api/v1/[^\s`|]*)", path)
    if m:
        return m.group(1), m.group(2)
    return None


def _norm_path(path: str) -> str:
    """Normalize a contract path: strip query string, Chinese/English notes,
    and unify placeholder syntax ({id}/{item_id}/:id/<x> → {x})."""
    path = path.split("?")[0]                       # 剥离 query 示例（?limit=10）
    path = re.split(r"[（(]", path)[0]               # 剥离中文/英文注记
    path = path.replace("${", "{")
    path = re.sub(r"<[^>]+>", "{x}", path)
    path = re.sub(r"\{[^}]*\}", "{x}", path)        # {id}/{item_id} 统一
    path = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", "{x}", path)
    return path.rstrip("/")


def load_expected_routes(contracts_dir: str = None) -> list[tuple[str, str]]:
    """Scan api-contracts/*.md and extract expected (method, path) pairs."""
    if contracts_dir is None:
        contracts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "api-contracts")

    expected: list[tuple[str, str]] = []
    md_files = glob.glob(os.path.join(contracts_dir, "**", "*.md"), recursive=True)

    for md_file in md_files:
        if os.path.basename(md_file) == "contract_template.md":
            continue  # 模板占位非真实契约
        rel_path = os.path.relpath(md_file, contracts_dir)
        with open(md_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parsed = _parse_contract_method(line)
                if parsed:
                    method, path = parsed
                    expected.append((method.upper(), _norm_path(path)))

    return expected


# ── Actual routes from FastAPI app ──────────────────────────────


def load_actual_routes() -> list[tuple[str, str]]:
    """Collect all registered API routes.

    FastAPI >= 0.121 的 app.routes 含 _IncludedRouter 惰性占位（path=None、
    无 methods），无法直接展开 —— 与 test_contract_auto.py 同法：直接遍历
    8 个业务 router 的 routes（不含默认 /docs 等，契约也只需 API 路由）。
    """
    from app.routers import (
        admin,
        analysis,
        factors,
        market,
        news,
        portfolio,
        system,
        ws,
    )

    routes: list[tuple[str, str]] = []
    for mod in (market, portfolio, analysis, news, ws, admin, factors, system):
        for route in mod.router.routes:
            p = getattr(route, "path", "") or ""
            methods = getattr(route, "methods", None) or set()
            for method in methods:
                if method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    routes.append((method.upper(), _norm_path(p)))
    return routes


# ── Compare ─────────────────────────────────────────────────────


def compare_routes(
    actual: list[tuple[str, str]],
    expected: list[tuple[str, str]],
) -> list[dict]:
    """Compare actual vs expected routes. Returns issues list."""
    actual_set = set(actual)
    expected_set = set(expected)

    issues: list[dict] = []

    # Routes in actual but not in contracts
    for route in sorted(actual_set - expected_set):
        issues.append({
            "type": "missing_from_contract",
            "method": route[0],
            "path": route[1],
            "message": f"Route {route[0]} {route[1]} is registered but not documented in api-contracts/",
        })

    # Routes in contracts but not in actual
    for route in sorted(expected_set - actual_set):
        issues.append({
            "type": "not_found_in_app",
            "method": route[0],
            "path": route[1],
            "message": f"Route {route[0]} {route[1]} is in api-contracts/ but not registered in app",
        })

    return issues


# ── Main ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="API Route Contract Verification")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--actual-only", action="store_true",
                        help="Only dump actual routes (no comparison)")
    args = parser.parse_args()

    actual = load_actual_routes()
    if args.actual_only:
        for method, path in sorted(set(actual)):
            print(f"{method:6s} {path}")
        return 0

    contracts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "api-contracts")
    expected = load_expected_routes(contracts_dir)

    if not actual:
        print("[FAIL] Could not load actual routes from app.main", file=sys.stderr)
        return 1

    issues = compare_routes(actual, expected)

    if args.json:
        print(json.dumps({
            "actual_count": len(set(actual)),
            "expected_count": len(set(expected)),
            "issues": issues,
            "pass": len(issues) == 0,
        }, indent=2, ensure_ascii=False))
    else:
        print(f"Actual routes: {len(set(actual))}")
        print(f"Contract routes: {len(set(expected))}")
        print()

        if issues:
            for issue in sorted(issues, key=lambda x: x["path"]):
                print(f"  [{issue['type']}] {issue['message']}")
            print()
            print(f"FAIL: {len(issues)} route mismatch(es) found")
        else:
            print("PASS: All routes match between app and contracts")

        print()
        print(f"=== Route Summary ===")
        for method, path in sorted(set(actual)):
            is_documented = (method, path) in set(expected)
            # 用 ASCII 标记避免 Windows GBK 控制台 UnicodeEncodeError
            mark = "[OK]" if is_documented else "[??]"
            print(f"  {mark} {method:6s} {path}")

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
