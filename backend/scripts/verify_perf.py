"""
verify_perf.py — 热点路径性能软门禁（round15 基线 E，docs/round15-test-guard-baseline.md §2-E）

用法:
  python scripts/verify_perf.py           # 针对运行中的后端（默认 localhost:8000）
  python scripts/verify_perf.py --base http://localhost:8000

对热点路径做首请求耗时测量，对照 AGENTS.md 软门禁阈值：
  watchlist ≤3s、搜索 ≤1s、factor-health ≤2s、symbol-analysis ≤5s、综合研判 ≤10s

性质：软门禁——超阈值仅 WARNING 登记（输出性能债台账），不阻断提交/退出码恒 0。
冷缓存首请求（round14 §2.8：watchlist 8.5s / search 6.25s / calculate 5.1s）为已知
性能债，超阈值时登记供后续排期优化，不伪装通过。
"""
import argparse
import json
import os
import sys
import time
import socket

BASE = "http://localhost:8000"

# 阈值（秒）——AGENTS.md 性能验收优先阈值参考
THRESHOLDS = {
    "watchlist": 3.0,          # GET /api/v1/market/watchlist
    "search": 1.0,             # GET /api/v1/market/search?keyword=510300
    "factor-health": 2.0,      # GET /api/v1/factors/active
    "symbol-analysis": 5.0,    # POST /api/v1/analysis/symbol/510050（SSE 仅测首包）
    "indices-global": 5.0,     # GET /api/v1/market/indices/global
    # round18 §5 盲区②/§7 P0-1/P0-2: timeline/metrics 热态恒定 2.3s/1.7s 无门禁——
    # 补阈值 ≤1s（修复后目标 ≤300ms，门禁留裕量）
    "timeline": 1.0,           # GET /api/v1/portfolio/timeline
    "metrics": 1.0,            # GET /api/v1/admin/metrics
}

DEBT_LOG = "已知性能债台账（软门禁预警登记，不阻断）"


def _http(method, url, timeout=20):
    import requests
    _t0 = time.monotonic()
    try:
        if method == "GET":
            resp = requests.get(url, timeout=timeout)
        else:
            resp = requests.post(url, json={}, timeout=timeout, stream=True)
            if resp.status_code == 200:
                # SSE 流：读首行即断（首包延迟 ≈ 分析启动耗时）
                resp.iter_lines().__next__()
        _dur = time.monotonic() - _t0
        return resp.status_code, _dur
    except Exception as e:
        return None, time.monotonic() - _t0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 后端未运行 → 软跳过（依赖 verify_e2e / smoke_startup 的服务存活门禁）
    try:
        sock = socket.create_connection(("127.0.0.1", 8000), timeout=2)
        sock.close()
    except OSError:
        print(f"[SKIP] 后端未在 {args.base} 运行——性能软门禁跳过（由 smoke_startup/verify_e2e 兜底服务存活）")
        return 0

    report = []
    for label, threshold in THRESHOLDS.items():
        if label == "watchlist":
            url = f"{args.base}/api/v1/market/watchlist"
            status, dur = _http("GET", url)
        elif label == "search":
            url = f"{args.base}/api/v1/market/search?keyword=510300"
            status, dur = _http("GET", url)
        elif label == "factor-health":
            url = f"{args.base}/api/v1/factors/active"
            status, dur = _http("GET", url)
        elif label == "symbol-analysis":
            url = f"{args.base}/api/v1/analysis/symbol/510050"
            status, dur = _http("POST", url)
        elif label == "timeline":
            url = f"{args.base}/api/v1/portfolio/timeline"
            status, dur = _http("GET", url)
        elif label == "metrics":
            url = f"{args.base}/api/v1/admin/metrics"
            status, dur = _http("GET", url)
        else:  # indices-global
            url = f"{args.base}/api/v1/market/indices/global"
            status, dur = _http("GET", url)

        ok = status is not None and dur <= threshold
        mark = "OK" if ok else "WARN"  # 软门禁：超阈值仅预警登记
        report.append({"path": label, "status": status, "dur_s": round(dur, 2), "threshold_s": threshold, "mark": mark})
        print(f"  [{mark}] {label} {dur:.2f}s (阈值 {threshold}s, HTTP {status})")
        if not ok:
            print(f"        → 性能债登记（{DEBT_LOG}）——软门禁不阻断，排期优化")

    # 登记台账（控制台 + 可追加文件）
    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "report": report,
           "note": "round15 基线 E 软门禁：超阈值仅登记不阻断"}
    try:
        with open(os.path.join(os.path.dirname(__file__), "..", "..", "data", "perf_baseline.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(f"性能软门禁完成：{sum(1 for r in report if r['mark']=='OK')} OK / "
          f"{sum(1 for r in report if r['mark']=='WARN')} WARN（台账已登记）")
    return 0  # 软门禁：恒 0 退出码


if __name__ == "__main__":
    raise SystemExit(main())
