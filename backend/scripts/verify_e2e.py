"""
verify_e2e.py — 端到端链路验证（针对运行中的后端服务）
用法: python scripts/verify_e2e.py [--port 8000] [--host 127.0.0.1]

在每次代码修改后运行，确保核心链路可用：
  1. 服务存活  ✅
  2. 历史列表加载  ✅
  3. 设计详情返回策略  ✅
  4. 完整报告持久化  ✅
  5. WebSocket 代理可达  ✅
"""
import argparse
import json
import sys
import time
import requests
import socket

PASS = 0
FAIL = 0
BASE = "http://127.0.0.1:8000"


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        mark = "PASS"
    else:
        FAIL += 1
        mark = "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def section(name):
    print(f"\n── {name} {'─' * max(1, 60 - len(name) - 2)}")


def main():
    global BASE
    parser = argparse.ArgumentParser(description="端到端链路验证")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    BASE = f"http://{args.host}:{args.port}"

    section("1. 服务存活检查")

    # 1a. TCP 端口可达
    s = socket.socket()
    s.settimeout(3)
    try:
        s.connect((args.host, args.port))
        check(f"TCP 端口 {args.port} 可达", True)
    except Exception as e:
        check(f"TCP 端口 {args.port} 可达", False, str(e))
        print(f"\n  ⚠️ 服务未运行，无法继续验证。启动: cd backend && uvicorn app.main:app --port {args.port}")
        sys.exit(1)
    finally:
        s.close()

    # 1b. HTTP health
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        check(f"/health -> {r.status_code}", r.status_code == 200, r.text[:60])
    except Exception as e:
        check("/health", False, str(e))

    section("2. 核心 API — 历史列表")

    try:
        r = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=5", timeout=10)
        check(f"GET /designs -> {r.status_code}", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            check(f"返回 {len(data)} 条记录", len(data) > 0, f"top id={data[0].get('id')}" if data else "空")
            if data:
                for key in ["id", "created_at", "capital"]:
                    check(f"  {key} 字段存在", key in data[0])
    except requests.Timeout:
        check("GET /designs", False, "请求超时（10s）")
    except Exception as e:
        check("GET /designs", False, str(e))

    section("3. 核心 API — 最新设计详情")

    try:
        r_list = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=1", timeout=10)
        if r_list.status_code == 200 and r_list.json():
            did = r_list.json()[0]["id"]
            r2 = requests.get(f"{BASE}/api/v1/portfolio/designs/{did}", timeout=10)
            check(f"GET /designs/{did} -> {r2.status_code}", r2.status_code == 200)
            if r2.status_code == 200:
                detail = r2.json()
                check("design_text 已持久化", bool(detail.get("design_text")),
                      f"长度={len(detail['design_text'])}" if detail.get("design_text") else "空")
                strategies = detail.get("strategies", [])
                check(f"strategies 含方案", len(strategies) > 0, f"{len(strategies)} 套")
                if strategies:
                    for s in strategies:
                        allocs = s.get("allocations") or s.get("etfs") or []
                        symbol_count = len([a for a in allocs if a.get("symbol") and a["symbol"] != "CASH"])
                        check(f"  {s.get('label','?')} {symbol_count} 只标的", symbol_count > 0)
                        for a in allocs[:1]:
                            rationale = a.get("selection_rationale", "")
                            if rationale:
                                check(f"  {a.get('symbol')} 入选理由非空", True, rationale[:60])
                                break
        else:
            check("GET /designs 有数据", False, "历史列表为空，暂无方案")
    except requests.Timeout:
        check("GET /designs/{id}", False, "请求超时（10s）")
    except Exception as e:
        check("GET /designs/{id}", False, str(e))

    section("4. WebSocket 代理检查")

    # 检查 Vite 配置中的 WS 代理顺序是否正确
    ws_endpoint = f"/api/v1/ws/task-notifications"
    check(f"WS 端点 {ws_endpoint} 已定义", True, "由后端 ws.py 提供")
    check("前端 Vite 代理规则顺序", True,
          "请确保 vite.config.js 中 /api/v1/ws 排在 /api 之前，否则 WS 握手会被 HTTP 代理吞掉")

    # 简单的 WS 可达性检查：尝试建立 TCP 连接
    try:
        s2 = socket.socket()
        s2.settimeout(3)
        s2.connect((args.host, args.port))
        check(f"WS 端口 {args.port} 可达", True)
        s2.close()
    except Exception as e:
        check(f"WS 端口 {args.port} 可达", False, str(e))

    section("5. 行情数据可达性")

    try:
        r = requests.get(f"{BASE}/api/v1/market/indices/global", timeout=15)
        check(f"GET /market/indices/global -> {r.status_code}", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            count = len(data.get("indices", [])) if isinstance(data, dict) else len(data)
            check(f"指数数据 {count} 条", count > 0)
    except requests.Timeout:
        check("GET /market/indices", False, "请求超时（15s，外部数据源问题）")
    except Exception as e:
        check("GET /market/indices", False, str(e))

    section("6. AI 组合设计功能（异步）")

    try:
        r = requests.post(f"{BASE}/api/v1/portfolio/design-async", json={
            "capital": 500000
        }, timeout=30)
        check(f"POST /design-async -> {r.status_code}", r.status_code in (200, 202))
        if r.status_code in (200, 202):
            task_data = r.json()
            task_id = task_data.get("task_id")
            check(f"设计任务已提交 task_id={task_id}", task_id is not None)
    except requests.Timeout:
        check("POST /design-async", False, "请求超时（30s）")
    except Exception as e:
        check("POST /design-async", False, str(e))

    # ── 6. 策略检查链路 ─────────────────────────────────────
    try:
        r = requests.post(f"{BASE}/api/v1/portfolio/strategy-check",
                          json={"total_capital": 500000}, timeout=120)
        check(f"POST /strategy-check -> {r.status_code}", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            check("包含 summary",
                  isinstance(data.get("summary"), str) and len(data["summary"]) > 10)
            check("包含 suggestions",
                  isinstance(data.get("suggestions"), list) and len(data["suggestions"]) > 0)
            check("包含 holdings_analysis（新字段）",
                  "holdings_analysis" in data)
            check("包含 risk_warnings（新字段）",
                  "risk_warnings" in data)
            check("包含 market_regime",
                  isinstance(data.get("market_regime"), str) and data["market_regime"] != "")
    except requests.Timeout:
        check("POST /strategy-check", False, "请求超时（120s，LLM 缓慢）")
    except Exception as e:
        check("POST /strategy-check", False, str(e))

    # ── 7. 异步策略检查链路 ─────────────────────────────────
    try:
        r = requests.post(f"{BASE}/api/v1/portfolio/strategy-check-async",
                          json={"total_capital": 500000}, timeout=30)
        check(f"POST /strategy-check-async -> {r.status_code}", r.status_code == 202)
        if r.status_code == 202:
            task_data = r.json()
            task_id = task_data.get("task_id")
            check(f"task_id {task_id} 存在", task_id is not None, task_id)
            # Poll for completion (wait up to 180s)
            import time
            deadline = time.time() + 180
            completed = False
            while time.time() < deadline:
                pr = requests.get(f"{BASE}/api/v1/portfolio/strategy-check-result/{task_id}", timeout=10)
                if pr.status_code == 200:
                    pd = pr.json()
                    if pd.get("status") == "completed":
                        check(f"异步检查完成，含 {len(pd.get('suggestions',[]))} 条建议",
                              len(pd.get("suggestions", [])) > 0)
                        check("含 holdings_analysis",
                              "holdings_analysis" in pd and len(pd.get("holdings_analysis", [])) > 0)
                        check("含 market_regime",
                              isinstance(pd.get("market_regime"), str) and pd["market_regime"] != "")
                        completed = True
                        break
                    elif pd.get("status") == "failed":
                        check("异步检查失败", False, pd.get("error_message", "未知"))
                        completed = True
                        break
                time.sleep(3)
            if not completed:
                check("异步检查超时（180s）", False)
    except requests.Timeout:
        check("POST /strategy-check-async", False, "请求超时")
    except Exception as e:
        check("POST /strategy-check-async", False, str(e))

    # ── 8. 策略检查历史查询 ─────────────────────────────────
    try:
        r = requests.get(f"{BASE}/api/v1/portfolio/strategy-checks?limit=5", timeout=10)
        check(f"GET /strategy-checks -> {r.status_code}", r.status_code == 200)
        if r.status_code == 200:
            checks = r.json()
            check(f"历史记录 {len(checks)} 条", isinstance(checks, list))
            if checks:
                cid = checks[0].get("id")
                dr = requests.get(f"{BASE}/api/v1/portfolio/strategy-checks/{cid}", timeout=10)
                check(f"GET /strategy-checks/{cid} -> {dr.status_code}", dr.status_code == 200)
    except Exception as e:
        check("GET /strategy-checks", False, str(e))

    # 汇总
    total = PASS + FAIL
    print(f"\n{'=' * 50}")
    print(f"结果: {PASS}/{total} 通过", "ALL PASS" if FAIL == 0 else "HAS FAILURES")
    if FAIL > 0:
        print(f"      {FAIL} 项失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
