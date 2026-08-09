"""
Comprehensive performance diagnostic script for ETF Surge backend.

Tests all available API endpoints, measures response times, and
identifies performance bottlenecks.
"""
import asyncio
import json
import time
import sys
import os
from urllib.parse import urljoin

import httpx

BASE_URL = "http://localhost:8000"

# Critical endpoints grouped by module
ENDPOINTS = {
    "health": [
        ("GET", "/health", "Health check"),
    ],
    "system": [
        ("GET", "/api/v1/system/warmup", "Warmup status"),
    ],
    "market": [
        ("GET", "/api/v1/market/realtime", "Real-time quotes"),
        ("GET", "/api/v1/market/indices/global", "Global indices"),
        ("GET", "/api/v1/market/indices/meta", "Index metadata"),
        ("GET", "/api/v1/market/search", "Market search"),
        ("GET", "/api/v1/market/sentiment", "Market sentiment"),
        ("GET", "/api/v1/market/watchlist", "Watchlist"),
        ("GET", "/api/v1/market/hot-plates", "Hot plates"),
        ("GET", "/api/v1/market/stock-hot-rank", "Stock hot rank"),
        ("GET", "/api/v1/market/wind", "Wind data"),
        ("GET", "/api/v1/market/sectors/concept", "Concept sectors"),
        ("GET", "/api/v1/market/sectors/industry", "Industry sectors"),
        ("GET", "/api/v1/market/sectors/industry-cls", "Industry CLS"),
    ],
    "market_details": [
        ("GET", "/api/v1/market/realtime/portfolio", "Portfolio realtime"),
        ("GET", "/api/v1/market/realtime/510050", "Single stock (510050)"),
        ("GET", "/api/v1/market/realtime/batch?symbols=510050,510880,159338", "Batch quote"),
        ("GET", "/api/v1/market/chart/510050?range=1m", "Chart 1m"),
        ("GET", "/api/v1/market/history/510050?days=5", "History 5d"),
        ("GET", "/api/v1/market/indicators/510050", "Indicators"),
        ("GET", "/api/v1/market/fundamentals/510050", "Fundamentals"),
        ("GET", "/api/v1/market/signal/510050", "Signal"),
    ],
    "portfolio": [
        ("GET", "/api/v1/portfolio/etfs", "ETF list"),
        ("GET", "/api/v1/portfolio/pnl-history", "PnL history"),
        ("GET", "/api/v1/portfolio/designs", "Designs list"),
        ("GET", "/api/v1/portfolio/tasks", "Tasks list"),
        ("GET", "/api/v1/portfolio/strategy-checks", "Strategy checks"),
        ("GET", "/api/v1/portfolio/drift-check", "Drift check"),
    ],
    "portfolio_write": [
        ("POST", "/api/v1/portfolio/apply-design", "Apply design", {"design_id": 224}),
        # R6-F12 (round6 §十 R6-14): calculate/daily-pnl 为 POST——旧配置用 GET 测 POST 端点
        # → 3 个假 FAIL
        ("POST", "/api/v1/portfolio/calculate", "Calculate allocation", {"total_capital": 100000}),
        ("POST", "/api/v1/portfolio/daily-pnl", "Daily PnL", {"total_capital": 100000}),
    ],
    "analysis": [
        ("GET", "/api/v1/factors/active", "Active factors"),
        ("GET", "/api/v1/factors/ic", "Factor IC"),
        ("GET", "/api/v1/factors/model", "Factor model"),
    ],
    "analysis_write": [
        # R6-F12: news-impact 为 POST（复杂 body 最小化——422 也算快速响应，非假 FAIL）
        ("POST", "/api/v1/analysis/news-impact", "News impact", {}),
    ],
    "news": [
        ("GET", "/api/v1/news/headlines", "News headlines"),
        ("GET", "/api/v1/news/macro", "Macro news"),
        ("GET", "/api/v1/news/global", "Global news"),
    ],
    "admin": [
        ("GET", "/api/v1/admin/config", "Admin config"),
        ("GET", "/api/v1/admin/sources/health", "Source health"),
        ("GET", "/api/v1/admin/sources/circuit-breakers", "Circuit breakers"),
        ("GET", "/api/v1/admin/sources/events/timeline", "Events timeline"),
        ("GET", "/api/v1/admin/sources/events/failures", "Event failures"),
        ("GET", "/api/v1/admin/token-usage", "Token usage"),
        ("GET", "/api/v1/admin/token-usage/timeseries", "Token ts"),
        ("GET", "/api/v1/admin/token-usage/failures", "Token failures"),
        ("GET", "/api/v1/admin/metrics", "Metrics"),
        ("GET", "/api/v1/admin/factor-health", "Factor health"),
        ("GET", "/api/v1/admin/thread-pool", "Thread pool"),
    ],
}


async def test_endpoint(client, method, path, label, data=None, timeout=30.0):
    """Test a single endpoint and return timing/status info."""
    url = urljoin(BASE_URL, path)
    start = time.perf_counter()
    try:
        if method == "GET":
            resp = await client.get(path, timeout=timeout)
        else:
            resp = await client.post(path, json=data or {}, timeout=timeout)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "method": method,
            "path": path,
            "label": label,
            "status": resp.status_code,
            "ms": round(elapsed_ms, 1),
            "ok": 200 <= resp.status_code < 400,
            "size_bytes": len(resp.content),
        }
    except httpx.TimeoutException:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "method": method,
            "path": path,
            "label": label,
            "status": "TIMEOUT",
            "ms": round(elapsed_ms, 1),
            "ok": False,
            "error": f"Timeout after {timeout}s",
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "method": method,
            "path": path,
            "label": label,
            "status": "ERROR",
            "ms": round(elapsed_ms, 1),
            "ok": False,
            "error": str(e)[:200],
        }


async def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "logs", "perf_diag_results.json"
    )

    results = {}
    all_pass = 0
    all_fail = 0
    slow_ops = []

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # First - health check
        health = await test_endpoint(client, "GET", "/health", "Health check")
        results["/health"] = health

        for category, endpoints in ENDPOINTS.items():
            print(f"\n=== {category} ({len(endpoints)} endpoints) ===")
            for method, path, label, *rest in endpoints:
                data = rest[0] if rest else None
                result = await test_endpoint(client, method, path, label, data)
                results[path] = result

                status_icon = "OK" if result["ok"] else "FAIL"
                ms_str = f"{result['ms']:>8.1f}ms"
                extra = ""
                if result.get("error"):
                    extra = f" [{result['error']}]"
                elif not result["ok"]:
                    extra = f" [HTTP {result['status']}]"
                print(f"  {status_icon} {method:4s} {path:<50s} {ms_str}{extra}")

                if result["ok"]:
                    all_pass += 1
                    if result["ms"] > 1000:
                        slow_ops.append((path, result["ms"]))
                else:
                    all_fail += 1

    # Summary
    total = all_pass + all_fail
    total_ms = sum(r.get("ms", 0) for r in results.values() if isinstance(r.get("ms"), (int, float)))

    summary = {
        "timestamp": time.time(),
        "total_endpoints": total,
        "passed": all_pass,
        "failed": all_fail,
        "total_time_ms": round(total_ms, 1),
        "slow_endpoints": [(p, round(m, 1)) for p, m in slow_ops],
        "results": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Summary: {all_pass}/{total} passed, {all_fail} failed")
    print(f"Total wall time: {total_ms:.0f}ms = {total_ms/1000:.1f}s")
    if slow_ops:
        print(f"\nSlow endpoints (>1s):")
        for path, ms in sorted(slow_ops, key=lambda x: -x[1]):
            print(f"  {path:<55s} {ms:.0f}ms")
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
