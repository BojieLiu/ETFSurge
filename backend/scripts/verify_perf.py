"""
verify_perf.py — 热点路径性能软门禁（round15 基线 E，docs/archived/round15-test-guard-baseline.md §2-E）

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


def _http(method, url, timeout=20, json_body=None):
    import requests
    _t0 = time.monotonic()
    try:
        if method == "GET":
            resp = requests.get(url, timeout=timeout)
        else:
            resp = requests.post(url, json=json_body or {}, timeout=timeout, stream=True)
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
            # round25 R35: 旧路径 /analysis/symbol/510050 恒 404 → 恒 0.00s 假 OK
            #（性能软门禁盲区）。真路径 POST /analysis/symbol-analysis/stream（SSE 首包）。
            url = f"{args.base}/api/v1/analysis/symbol-analysis/stream"
            status, dur = _http("POST", url, json_body={"symbol": "510050", "asset_type": "A"})
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
        # round20 P0-1: timeline/metrics 为纯 DB 内部端点（不依赖外部行情），
        # 改硬门禁——超阈值即退出码 1（CI 阻断）；外部数据端点保持软门禁（防外部源抖动误伤）。
        hard = label in ("timeline", "metrics")
        mark = "OK" if ok else ("FAIL" if hard else "WARN")
        report.append({"path": label, "status": status, "dur_s": round(dur, 2), "threshold_s": threshold, "mark": mark})
        print(f"  [{mark}] {label} {dur:.2f}s (阈值 {threshold}s, HTTP {status})")
        if not ok:
            if hard:
                print(f"        → 硬门禁 FAIL（{label} 为纯 DB 端点，不应超阈值）")
            else:
                print(f"        → 性能债登记（{DEBT_LOG}）——软门禁不阻断，排期优化")

    # 登记台账（控制台 + 可追加文件）
    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "report": report,
           "note": "round15 基线 E 软门禁：超阈值仅登记不阻断"}
    try:
        with open(os.path.join(os.path.dirname(__file__), "..", "..", "data", "perf_baseline.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(f"性能校验完成：{sum(1 for r in report if r['mark']=='OK')} OK / "
          f"{sum(1 for r in report if r['mark']=='WARN')} WARN / "
          f"{sum(1 for r in report if r['mark']=='FAIL')} FAIL（台账已登记）")
    # round20 P0-1: 硬门禁端点超阈值 → 退出码 1（CI 阻断）；其余软门禁恒 0
    return 1 if any(r["mark"] == "FAIL" for r in report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
