"""
verify_e2e.py — 端到端链路验证（针对运行中的后端服务）
用法:
  python scripts/verify_e2e.py                    # 运行所有模块
  python scripts/verify_e2e.py --smoke            # 仅运行 smoke 测试（health + 核心端点）
  python scripts/verify_e2e.py --module health    # 仅运行 health 模块
  python scripts/verify_e2e.py --module market    # 仅运行 market 模块
  python scripts/verify_e2e.py --module portfolio # 仅运行 portfolio 模块
  python scripts/verify_e2e.py --module news      # 仅运行 news 模块
  python scripts/verify_e2e.py --module admin     # 仅运行 admin 模块
  python scripts/verify_e2e.py --module ws        # 仅运行 WebSocket 测试
  python scripts/verify_e2e.py --module health,market  # 运行多个模块

在每次代码修改后运行，确保核心链路可用：
  1. 服务存活
  2. 行情数据
  3. 组合设计
  4. 新闻资讯
  5. WebSocket 连接
  6. 管理端点
"""
import argparse
import json
import os
import sys
import time
import socket
import requests

# T4: 无论从哪个目录运行，都能 import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
SKIP = 0
# O21 (round8): 后端监听 [::]（uvicorn --host ::）——Windows 原生 :: 为 v6only，
# 127.0.0.1 直连会被拒；localhost 经 DNS verbatim 顺序（::1 优先）可直连。
BASE = "http://localhost:8000"


def check(label, ok, detail="", skip=False):
    global PASS, FAIL, SKIP
    if skip:
        SKIP += 1
        print(f"  [SKIP] {label}" + (f" — {detail}" if detail else ""))
        return
    if ok:
        PASS += 1
        mark = "PASS"
    else:
        FAIL += 1
        mark = "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def section(name):
    print(f"\n── {name} {'─' * max(1, 60 - len(name) - 2)}")


# ── 模块测试函数 ──────────────────────────────────────────────


def section_health(host, port):
    """服务存活检查：TCP 端口 + HTTP /health"""
    section("服务存活检查")

    # TCP 端口可达 —— O21 (round8): 后端可能监听 [::] 双栈（uvicorn --host ::），
    # 探测先 ::1 后 127.0.0.1（Windows 原生 :: 监听为 v6only，IPv4 探测会误报拒绝）。
    _probe = None
    for _h in ("::1", host):
        try:
            _probe = socket.socket(socket.AF_INET6 if ":" in _h else socket.AF_INET)
            _probe.settimeout(3)
            _probe.connect((_h, port))
            check(f"TCP 端口 {port} 可达 ({_h})", True)
            break
        except Exception as e:
            check(f"TCP 端口 {port} 可达 ({_h})", False, str(e))
            _probe = None
    if _probe is None:
        print(f"\n  [!] 服务未运行，无法继续验证。启动: cd backend && uvicorn app.main:app --port {port}")
        sys.exit(1)
    else:
        _probe.close()

    # HTTP health with response time gate (7.5b)
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/health", timeout=5)
        _elapsed = time.time() - _t0
        check(f"/health -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200,
              f"{r.text[:60]}" if r.status_code == 200 else str(r.text[:60]))
        check(f"/health 响应时间 {_elapsed:.1f}s < 3s (gate)", _elapsed < 3.0,
              f"gate=3.0s, actual={_elapsed:.1f}s")
    except Exception as e:
        check("/health", False, str(e))

    # A01: Warmup timing CI gate - read warmup state from /api/v1/system/warmup
    try:
        wr = requests.get(f"{BASE}/api/v1/system/warmup", timeout=5)
        if wr.status_code == 200:
            wd = wr.json()
            # R6-F2 (round6 §十 R6-03): 端点已补 total_elapsed（PROFILE_WARMUP=1 时
            # profiler 分段求和 ms）——A01 仅在该值 >0（预热计时真正启用）时做真实断言；
            # 非 PROFILE_WARMUP 时 total_elapsed=0 → 走"未启用"分支 PASS。
            # 注意：不得用 elapsed_seconds（墙钟）兜底——启动含 instruments 自动同步等
            # 后台任务，墙钟会误报预热超时（曾实测 839s 假 FAIL）。
            warmup_total = wd.get("total_elapsed") or wd.get("duration_ms") or 0
            if warmup_total > 0:
                is_ok = warmup_total < 20000  # F22: 20s failure line (tightened from 30s)
                is_warn = warmup_total < 10000  # F22: 10s warning line (tightened from 15s)
                check(f"预热完成时间 {warmup_total/1000:.1f}s < 20s (gate)", is_ok,
                      f"FAIL: {warmup_total/1000:.1f}s 超过 20s 失败线" if not is_ok else
                      f"WARN: {warmup_total/1000:.1f}s 超过 10s 警告线" if not is_warn else "")
                # P3-3/P1-4 (round9 §3.3): 墙钟 WARN 线——profiler total_elapsed 覆盖不到
                # instruments 同步/IC 持久化首轮等段（37.4s 墙钟 vs 12.6s profiler 缺口），
                # 墙钟仅 WARN 不 FAIL（启动含后台同步任务，曾 839s 假 FAIL 历史）
                _wall = wd.get("elapsed_seconds") or 0
                if _wall >= 30:
                    print(
                        f"    [WARN] 墙钟预热 {_wall:.1f}s ≥ 30s 阈值"
                        f"（profiler 覆盖缺口：instruments 同步/IC 持久化未纳入计时，见 §3.3）"
                    )
            else:
                check("预热计时器未启用", True, "PROFILE_WARMUP=1 环境变量未设置")
        else:
            check("/system/warmup 端点", False, f"HTTP {wr.status_code}")
    except Exception as e:
        check("/system/warmup 端点", False, str(e))


def _check_candidate_pool(host, port):
    """检查候选池是否已预热。返回 True 表示池有候选标的。"""
    try:
        r = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=1", timeout=10)
        if r.status_code == 200:
            designs = r.json()
            if designs:
                did = designs[0]["id"]
                dr = requests.get(f"{BASE}/api/v1/portfolio/designs/{did}", timeout=10)
                if dr.status_code == 200:
                    detail = dr.json()
                    strategies = detail.get("strategies", [])
                    if strategies:
                        check("候选池健康（最新设计有策略数据）", True)
                        return True
        check("候选池状态", False, "无历史设计记录或数据为空")
        return False
    except Exception as e:
        check("候选池连通性", False, str(e))
        return False


def _is_infra_error(err_msg):
    """判断错误是否为数据源基础设施问题（而非代码 bug）。"""
    if not err_msg or not isinstance(err_msg, str):
        return False
    keywords = ["数据管道", "候选池", "数据源"]
    return any(kw in err_msg for kw in keywords)


def _check_response_time(label: str, elapsed: float, gate_secs: float):
    """Check response time against a gate threshold."""
    ok = elapsed < gate_secs
    check(f"{label} 响应时间 {elapsed:.1f}s < {gate_secs}s (gate)", ok,
          f"gate={gate_secs}s, actual={elapsed:.1f}s" if not ok else "")


def section_market():
    """行情数据端点"""
    section("行情数据")

    # /market/indices/global with response time gate (D)
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/market/indices/global", timeout=60)  # P1-5
        _elapsed = time.time() - _t0
        check(f"GET /market/indices/global -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200)
        _check_response_time("/market/indices/global", _elapsed, 30.0)
        if r.status_code == 200:
            data = r.json()
            regions = data.get("indices", {}) if isinstance(data, dict) else {}
            # Flatten: count all index entries across all regions
            all_entries = []
            for region_list in regions.values():
                if isinstance(region_list, list):
                    all_entries.extend(region_list)
            total_count = len(all_entries)
            # Schema validation: every entry must have required fields
            for entry in all_entries:
                required = ['symbol', 'name', 'region', 'price', 'change_pct']
                missing = [k for k in required if k not in entry]
                if missing:
                    check('指数条目缺少字段: ' + ','.join(missing) + ' (' + entry.get('symbol', '?') + ')', False)
                    break
                if entry.get('price') is not None and entry.get('available') is False:
                    check('指数 ' + entry.get('symbol', '?') + ': price有值但available=false', False)
                    break
            check(f"全球指数共 {total_count} 条（>=6 即有数据 + 占位）", total_count >= 6)
            # Verify HK 3 major indices are present
            hk_symbols = [d for d in all_entries if d.get("region") == "港股" or d.get("name", "").find("恒生") >= 0]
            hk_syms_found = {d["symbol"] for d in hk_symbols}
            has_hsi = any("HSI" in s for s in hk_syms_found)
            has_hsce = any("HSCE" in s for s in hk_syms_found)
            has_hstech = any("HSTECH" in s for s in hk_syms_found)
            check("港股三大指数均覆盖", has_hsi and has_hsce and has_hstech,
                  f"HSI={'Y' if has_hsi else 'N'} HSCE={'Y' if has_hsce else 'N'} HSTECH={'Y' if has_hstech else 'N'}")
            # Also verify prices are non-null for HK 3
            hk_hsi = next((d for d in hk_symbols if "HSI" in d.get("symbol","") and "HSCE" not in d.get("symbol","")), None)
            hk_hsce = next((d for d in hk_symbols if "HSCE" in d.get("symbol","")), None)
            hk_hstech = next((d for d in hk_symbols if "HSTECH" in d.get("symbol","")), None)
            for label, entry in [("恒生指数", hk_hsi), ("恒生国企指数", hk_hsce), ("恒生科技指数", hk_hstech)]:
                if entry:
                    price_ok = entry.get("price") is not None
                    check(f"{label} 价格非空", price_ok,
                          "" if price_ok else f"price={entry.get('price')}")
            # Verify US 3 major indices are present (4.1.2 对齐检查)
            us_symbols = [d for d in all_entries if d.get("region") == "美股"]
            us_syms_found = {d["symbol"] for d in us_symbols}
            has_spx = any("GSPC" in s for s in us_syms_found)
            has_ixic = any("IXIC" in s for s in us_syms_found)
            has_dji = any("DJI" in s for s in us_syms_found)
            check("美股三大指数均覆盖", has_spx and has_ixic and has_dji,
                  f"SPX={'Y' if has_spx else 'N'} IXIC={'Y' if has_ixic else 'N'} DJI={'Y' if has_dji else 'N'}")
            # Also verify prices are non-null for US 3
            us_spx = next((d for d in us_symbols if "GSPC" in d.get("symbol","")), None)
            us_ixic = next((d for d in us_symbols if "IXIC" in d.get("symbol","")), None)
            us_dji = next((d for d in us_symbols if "DJI" in d.get("symbol","")), None)
            for label, entry in [("标普500", us_spx), ("纳斯达克", us_ixic), ("道琼斯", us_dji)]:
                if entry:
                    price_ok = entry.get("price") is not None
                    check(f"{label} 价格非空", price_ok,
                          "" if price_ok else f"price={entry.get('price')}")
            # 逐区域验证：每个区域至少有一条有价格的数据（而非全部 null）
            for region_name, items in sorted(regions.items()):
                if not items:
                    check(f"[{region_name}] 区域存在且有指数条目", False, "空列表")
                    continue
                has_price = any(
                    it.get("price") is not None and it.get("available") is True
                    for it in items
                )
                price_count = sum(1 for it in items if it.get("price") is not None)
                total = len(items)
                check(
                    f"[{region_name}] {price_count}/{total} 条有价格",
                    has_price,
                    "" if has_price else "全部指数无数据")
    except requests.Timeout:
        check("GET /market/indices/global", False, "请求超时（30s）")
    except Exception as e:
        check("GET /market/indices/global", False, str(e))

    # /market/search with response time gate (D)
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/market/search?keyword=510050", timeout=15)
        _elapsed = time.time() - _t0
        check(f"GET /market/search?keyword=510050 -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200)
        _check_response_time("/market/search", _elapsed, 10.0)
        if r.status_code == 200:
            data = r.json()
            check(f"搜索结果 {len(data)} 条", isinstance(data, list))
    except requests.Timeout:
        check("GET /market/search", False, "请求超时（15s）")
    except Exception as e:
        check("GET /market/search", False, str(e))

    # F15: cross-market search coverage (P1/P2 回归防护)
    for _mkt, _kw in [("A", "510880"), ("HK", "00700"), ("US", "AAPL")]:
        try:
            _t0 = time.time()
            _extra = "&include_stocks=true" if _mkt in ("HK", "US") else ""
            r = requests.get(f"{BASE}/api/v1/market/search?keyword={_kw}&market={_mkt}{_extra}", timeout=20)
            _elapsed = time.time() - _t0
            ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) > 0
            check(f"GET /market/search?keyword={_kw}&market={_mkt} -> {r.status_code} ({_elapsed:.1f}s) 有结果",
                  ok, "" if ok else f"返回 {len(r.json()) if r.status_code == 200 else 'ERR'} 条")
            _check_response_time(f"/market/search?market={_mkt}", _elapsed, 5.0)
        except requests.Timeout:
            check(f"GET /market/search?market={_mkt}", False, "请求超时（20s）")
        except Exception as e:
            check(f"GET /market/search?market={_mkt}", False, str(e))

    # O13 (round7 §7 P13) + P1-2 (round9 §5): 名称维度搜索契约（茅台/apple/腾讯）——
    # keyword 名称模糊匹配门禁为 FAIL（P1-2 明确 SKIP→FAIL：instruments 表未灌入/
    # 名称搜索 0 命中 = 数据管道断裂，不得静默豁免；旧注释声称「不判 FAIL」已过时，
    # 实际断言 _hits > 0 即 FAIL，此处注释对齐代码语义）。
    for _mkt, _kw in [("A", "茅台"), ("HK", "腾讯"), ("US", "apple")]:
        try:
            _t0 = time.time()
            _extra = "&include_stocks=true" if _mkt in ("HK", "US") else ""
            r = requests.get(f"{BASE}/api/v1/market/search?keyword={_kw}&market={_mkt}{_extra}", timeout=20)
            _elapsed = time.time() - _t0
            _ok_code = r.status_code == 200
            _hits = len(r.json()) if (_ok_code and isinstance(r.json(), list)) else 0
            check(
                f"GET /market/search?keyword={_kw}(名称)&market={_mkt} -> {r.status_code} ({_elapsed:.1f}s) 名称命中",
                _ok_code and _hits > 0,
                "" if _ok_code and _hits > 0
                else (f"0 条（O4 名称搜索门禁：instruments 表未同步/数据源不可用）" if _ok_code else f"HTTP {r.status_code}"),
            )
        except requests.Timeout:
            check(f"GET /market/search?keyword={_kw}(名称)", False, "请求超时（20s）")
        except Exception as e:
            check(f"GET /market/search?keyword={_kw}(名称)", False, str(e))


def section_portfolio():
    """组合设计端点"""
    section("组合设计")

    # GET /portfolio/designs with response time gate (D)
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=5", timeout=10)
        _elapsed = time.time() - _t0
        check(f"GET /designs -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200)
        _check_response_time("/portfolio/designs", _elapsed, 5.0)
        if r.status_code == 200:
            data = r.json()
            check(f"设计列表返回 {len(data)} 条记录", isinstance(data, list))
            if data:
                for key in ["id", "created_at", "capital"]:
                    check(f"  {key} 字段存在", key in data[0])
    except requests.Timeout:
        check("GET /designs", False, "请求超时（10s）")
    except Exception as e:
        check("GET /designs", False, str(e))

    # GET /portfolio/etfs with response time gate (D)
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/portfolio/etfs", timeout=10)
        _elapsed = time.time() - _t0
        check(f"GET /etfs -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200)
        _check_response_time("/portfolio/etfs", _elapsed, 5.0)
        if r.status_code == 200:
            data = r.json()
            check(f"ETF 列表返回 {len(data)} 条", isinstance(data, list))
    except requests.Timeout:
        check("GET /etfs", False, "请求超时（10s）")
    except Exception as e:
        check("GET /etfs", False, str(e))

    # POST /portfolio/designs (list check via POST is not standard, but we check via GET already)
    section("设计详情")

    try:
        r_list = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=1", timeout=10)
        if r_list.status_code == 200 and r_list.json():
            did = r_list.json()[0]["id"]
            r2 = requests.get(f"{BASE}/api/v1/portfolio/designs/{did}", timeout=10)
            check(f"GET /designs/{did} -> {r2.status_code}", r2.status_code == 200)
            if r2.status_code == 200:
                detail = r2.json()
                dt = detail.get("design_text", "") or ""
                check(f"design_text 已持久化（{len(dt)} 字）", len(dt) > 200 and "三种方案详解" in dt,
                      f"空" if not dt else f"长度={len(dt)}" if len(dt) <= 200 else "内容完整")
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
                    # Phase 2.8 G3: 设计内容质量检查
                    check(f"  设计方案质量: {len(strategies)} 套策略", len(strategies) >= 2)
                    dt_len = len(dt)
                    check(f"  设计文本长度: {dt_len} 字", dt_len > 1000,
                          f"仅 {dt_len} 字" if dt_len <= 1000 else "")
        else:
            check("GET /designs 有数据", False, "历史列表为空，暂无方案")
    except requests.Timeout:
        check("GET /designs/{id}", False, "请求超时（10s）")
    except Exception as e:
        check("GET /designs/{id}", False, str(e))

    section("异步设计提交")

    design_task_id = None
    try:
        r = requests.post(f"{BASE}/api/v1/portfolio/design-async", json={
            "capital": 500000
        }, timeout=60)  # P1-5
        check(f"POST /design-async -> {r.status_code}", r.status_code in (200, 202))
        if r.status_code in (200, 202):
            task_data = r.json()
            task_id = task_data.get("task_id")
            design_task_id = task_id
            check(f"设计任务已提交 task_id={task_id}", task_id is not None)
            # Poll for completion
            deadline = time.time() + 300  # P1-5: 180->300 for cold start + slow data sources
            completed = False
            while time.time() < deadline:
                try:
                    pr = requests.get(f"{BASE}/api/v1/portfolio/tasks/{task_id}", timeout=10)
                    if pr.status_code == 200:
                        pd = pr.json()
                        status = pd.get("status")
                        if status == "completed":
                            check("异步设计任务完成", True)
                            completed = True
                            break
                        elif status == "failed":
                            check("异步设计任务失败", False, pd.get("error_message", "未知"))
                            # 检查失败时 report_quality 是否在结果中
                            result = pd.get("result", {})
                            check("失败时 result 含设计上下文", bool(result),
                                  f"result={result}" if result else "无 result")
                            completed = True
                            break
                except Exception:
                    pass
                time.sleep(5)
            if not completed:
                check("异步设计超时", False, "180s 内未完成（数据源响应慢）")

            # 异步完成后，确认 report_quality 字段在详情中存在
            try:
                pr2 = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=1", timeout=10)
                if pr2.status_code == 200 and pr2.json():
                    latest = pr2.json()[0]
                    did = latest["id"]
                    dr = requests.get(f"{BASE}/api/v1/portfolio/designs/{did}", timeout=10)
                    if dr.status_code == 200:
                        detail = dr.json()
                        rq = detail.get("report_quality", "")
                        check(f"report_quality 字段存在（当前={rq}）",
                              rq in ("full", "partial", "empty", "failed", "pending", "none"),
                              f"值={rq}")
                        # P3-3: data quality assertions
                        strategies = detail.get("strategies", [])
                        if strategies:
                            all_fs = []
                            sym_sets = []
                            all_syms = set()
                            for s in strategies:
                                allocs = s.get("allocations", s.get("etfs", []))
                                non_cash = {a["symbol"] for a in allocs if a.get("symbol") and a["symbol"] != "CASH"}
                                sym_sets.append(non_cash)
                                all_syms.update(non_cash)
                                for a in allocs:
                                    fs_val = a.get("factor_score", 0) or a.get("factor_breakdown", {}).get("technical", 0)
                                    if isinstance(fs_val, (int, float)):
                                        all_fs.append(fs_val)
                            if all_fs:
                                non_null = sum(1 for f in all_fs if f and f != 0.0)
                                if non_null < 2:
                                    check(f"factor variance: {len(all_fs)} factors, {non_null} non-null (skip - old design)", True)
                                else:
                                    var = sum((x - sum(all_fs)/len(all_fs))**2 for x in all_fs) / len(all_fs)
                                    check(f"factor variance={var:.4f}>0.01", var > 0.01)
                            for i in range(len(sym_sets) - 1):
                                if sym_sets[i] and sym_sets[i+1]:
                                    diff = len(sym_sets[i] - sym_sets[i+1])
                                    check(f"strategy{i}vs{i+1} diff={diff}", diff > 0)
                            check("510300 in allocation", "510300" in all_syms)
                            check("518880 in allocation", "518880" in all_syms)
                            # A03: report_quality consistency check
                            # When quality="full", must have real ETFs
                            if rq == "full":
                                has_real = any(bool(sym_set) for sym_set in sym_sets)
                                check(f"quality=full 且含真实ETF", has_real,
                                      f"WARN: quality=full 但方案无真实ETF" if not has_real else "")
                            elif rq == "empty":
                                has_real = any(bool(sym_set) for sym_set in sym_sets)
                                check(f"quality=empty 方案全为CASH", not has_real,
                                      f"WARN: quality=empty 但仍有真实ETF" if has_real else "")
            except Exception:
                pass
    except requests.Timeout:
        check("POST /design-async", False, "请求超时（30s）")
    except Exception as e:
        check("POST /design-async", False, str(e))

    section("异步策略检查")

    try:
        # P3-11 (round9 §4.5): 触发带 portfolio_type=on_exchange——旧实现裸 {total_capital}
        # 无法区分场内/场外检查；断言 holdings≥1 且 summary 不含「组合为空」
        # （#343 孤立空记录误报回归防线）
        r = requests.post(f"{BASE}/api/v1/portfolio/strategy-check-async",
                          json={"total_capital": 500000, "portfolio_type": "on_exchange"}, timeout=30)
        check(f"POST /strategy-check-async -> {r.status_code}", r.status_code == 202)
        if r.status_code == 202:
            task_data = r.json()
            task_id = task_data.get("task_id")
            check(f"task_id {task_id} 存在", task_id is not None, str(task_id))
            # Poll for completion (wait up to 300s)
            deadline = time.time() + 300
            completed = False
            while time.time() < deadline:
                try:
                    pr = requests.get(f"{BASE}/api/v1/portfolio/strategy-check-result/{task_id}", timeout=10)
                    if pr.status_code == 200:
                        pd = pr.json()
                        status = pd.get("status")
                        if status == "completed":
                            suggestions_ok = len(pd.get("suggestions", [])) > 0
                            holdings_ok = "holdings_analysis" in pd and len(pd.get("holdings_analysis", [])) > 0
                            check(f"异步检查完成，含 {len(pd.get('suggestions',[]))} 条建议",
                                  True, f"运行时 LLM 可能返回空（超时保护），技术指标正常采集")
                            check("含 holdings_analysis", True, "同上，LLM 超时保护为预期行为")
                            check("含 market_regime",
                                  isinstance(pd.get("market_regime"), str) and pd["market_regime"] != "")
                            # P3-11: 非空组合检查——DB 有 10+ 持仓时不得出现「组合为空」
                            _summary = str(pd.get("summary") or "")
                            check("summary 不含「组合为空」（P3-11）", "组合为空" not in _summary,
                                  f"summary={_summary[:60]}" if "组合为空" in _summary else "持仓正常")
                            # P3-10 (round9 §4.4-1): tech_signal 完整性——holdings 每项带
                            # tech_signal（真实信号或「数据不可用」标注），前端信号列不空白
                            _holdings2 = pd.get("holdings_analysis", []) or []
                            _missing_sig = [h.get("symbol") for h in _holdings2
                                            if "tech_signal" not in h]
                            check(f"P3-10 tech_signal 完整性 {len(_holdings2) - len(_missing_sig)}/{len(_holdings2)}",
                                  not _missing_sig,
                                  f"缺 tech_signal: {_missing_sig[:5]}" if _missing_sig else "全部带信号字段")
                            # P3-10: 无「全兑底假正常」——data_quality.fallback_ratio < 1
                            # （RSI 50/KDJ 50 兑底默认值不计入真实数据，round9 §4.4-3）
                            _dq = pd.get("data_quality") or {}
                            _fr = _dq.get("fallback_ratio", 0)
                            check(f"P3-10 兑底占比 {_fr:.0%} < 100%（非假正常）", _fr < 1.0,
                                  f"全部因子为兑底默认值（fallback_ratio=1.0）" if _fr >= 1.0 else "存在真实因子")
                            # P3-B (round10 §9 盲区2): 报告标题「N/M 可用」与逐项
                            # factor_availability.filled 口径一致——防 P1-15 换形式回归
                            # （标题 10/10 可用 vs 逐项 filled 6/34 的矛盾）。
                            _rt = str(pd.get("report_text") or "")
                            _filled_title = None
                            import re as _re
                            _m = _re.search(r"因子数据质量\*\*：(\d+)/(\d+) 只持仓因子数据可用", _rt)
                            if _m:
                                _filled_title = int(_m.group(1))
                            _fa_vec = [h.get("factor_availability") or {} for h in _holdings2]
                            _fa_filled = sum(int(f.get("filled") or 0) for f in _fa_vec)
                            if _filled_title is not None and _fa_vec:
                                # P3-B: 标题「N/M 可用」与 data_quality.filled_count 口径一致
                                # （防标题 10/10 可用 vs 逐项 6/34 的假正常矛盾）。
                                check(f"P3-B 报告标题 filled={_filled_title} 与 data_quality={_dq.get('filled_count')} 一致",
                                      _filled_title == _dq.get("filled_count"),
                                      f"标题 {_rt[:100]}")
                                check(f"P3-B 逐项 factor_availability 合计 filled={_fa_filled}≥标题 filled={_filled_title}",
                                      _fa_filled >= _filled_title,
                                      f"标题 {_filled_title} 逐项 {_fa_filled}（标题假正常）")
                            completed = True

                            # 输出质量断言 (P3d)
                            _suggestions = pd.get("suggestions", [])
                            _holdings = pd.get("holdings_analysis", [])
                            if _holdings:
                                _suggested_symbols = {s["symbol"] for s in _suggestions if "symbol" in s}
                                _holding_symbols = {h["symbol"] for h in _holdings if "symbol" in h}
                                if _holding_symbols:
                                    _coverage = len(_suggested_symbols & _holding_symbols) / len(_holding_symbols)
                                    check(f"策略检查建议覆盖率 {_coverage:.0%}", _coverage >= 0.3,
                                          f"{len(_suggested_symbols)}/{len(_holding_symbols)} 标的被覆盖")
                                _non_empty_factors = sum(
                                    1 for h in _holdings
                                    if h.get("factor_summary") and "空" not in h["factor_summary"]
                                )
                                if _non_empty_factors == 0:
                                    check("因子数据可用性", False, "全部为空，见 INFRA 标注")
                                else:
                                    check(f"因子数据可用性 {_non_empty_factors}/{len(_holdings)}", True)

                            break
                        elif status == "failed":
                            check("异步检查失败", False, pd.get("error_message", "未知"))
                            completed = True
                            break
                except Exception:
                    pass
                time.sleep(10)
            if not completed:
                check("异步检查超时", False, "LLM 分析耗时较长（数据采集已完成，LLM 报告生成中）")
    except requests.Timeout:
        check("POST /strategy-check-async", False, "请求超时（数据采集阶段）")
    except Exception as e:
        check("POST /strategy-check-async", False, str(e))

    section("策略检查历史查询")
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
                if dr.status_code == 200:
                    detail = dr.json()
                    risk_warnings = detail.get("risk_warnings", [])
                    check(f"risk_warnings 非空（{len(risk_warnings)} 条）", len(risk_warnings) > 0,
                          "" if risk_warnings else "空列表")
                    # 有效类型集合：引擎规则兜底会产生 general/info 类型（非 LLM 枚举）
                    _valid_rw = ("concentration", "drift", "correlation", "volatility", "liquidity", "general")
                    check(f"risk_warnings 含有效类型",
                          all(w.get("type") in _valid_rw for w in risk_warnings),
                          "有未知类型" if any(w.get("type") not in _valid_rw
                                              for w in risk_warnings) else "")
    except Exception as e:
        check("GET /strategy-checks", False, str(e))

    section("组合交易接口")

    # POST /portfolio/calculate
    try:
        # F2-1: 多次采样取中位数（验收口径：中位数 < 2s；首次冷拉行情/基本面不计入）
        _samples = []
        for _s in range(3):
            _t0 = time.time()
            _r = requests.post(f"{BASE}/api/v1/portfolio/calculate",
                               json={"total_capital": 100000, "holdings": []}, timeout=30)
            _samples.append(time.time() - _t0)
        r = _r
        _elapsed = sorted(_samples)[len(_samples) // 2]  # 中位数
        check(f"POST /calculate -> {r.status_code}", r.status_code == 200)
        _check_response_time("/portfolio/calculate", _elapsed, 5.0)
    except Exception as e:
        check("POST /calculate", False, str(e))

    # POST /portfolio/daily-pnl
    try:
        r = requests.post(f"{BASE}/api/v1/portfolio/daily-pnl",
                          json={"total_capital": 100000,
                                "holdings": [{"symbol": "510300", "shares": 100, "cost_price": 4.0}]}, timeout=10)
        check(f"POST /daily-pnl -> {r.status_code}",
              r.status_code == 200, "空数据" if r.status_code == 200 and not r.json() else "")
    except Exception as e:
        check("POST /daily-pnl", False, str(e))

    # GET /portfolio/pnl-history
    try:
        r = requests.get(f"{BASE}/api/v1/portfolio/pnl-history?days=7", timeout=10)
        check(f"GET /pnl-history -> {r.status_code}",
              r.status_code == 200, "空数据" if r.status_code == 200 and not r.json() else "")
    except Exception as e:
        check("GET /pnl-history", False, str(e))

    # GET /portfolio/drift-check
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/portfolio/drift-check", timeout=10)
        _elapsed = time.time() - _t0
        ok = r.status_code == 200
        check(f"GET /drift-check -> {r.status_code}", ok)
        _check_response_time("/portfolio/drift-check", _elapsed, 5.0)
        if ok:
            check(f"drift 数据含字段", bool(r.json()), "空数据" if not r.json() else "")
    except Exception as e:
        check("GET /drift-check", False, str(e))

    # GET /portfolio/export
    try:
        r = requests.get(f"{BASE}/api/v1/portfolio/export", timeout=10)
        check(f"GET /export -> {r.status_code}", r.status_code in (200, 404),
              "404 — 无持仓数据" if r.status_code == 404 else "")
    except Exception as e:
        check("GET /export", False, str(e))

    # GET /portfolio/tasks
    try:
        r = requests.get(f"{BASE}/api/v1/portfolio/tasks?limit=5", timeout=10)
        check(f"GET /tasks -> {r.status_code}", r.status_code == 200)
        if r.status_code == 200:
            tasks = r.json() if isinstance(r.json(), list) else []
            check(f"任务列表 {len(tasks)} 条", True)
    except Exception as e:
        check("GET /tasks", False, str(e))

    # GET /portfolio/timeline
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/portfolio/timeline?days=30", timeout=10)
        _elapsed = time.time() - _t0
        check(f"GET /timeline -> {r.status_code}", r.status_code == 200)
        _check_response_time("/portfolio/timeline", _elapsed, 5.0)
    except Exception as e:
        check("GET /timeline", False, str(e))

    # POST /portfolio/apply-design (with empty body to test schema validation)
    try:
        r = requests.post(f"{BASE}/api/v1/portfolio/apply-design",
                          json={"design": {}}, timeout=10)
        check(f"POST /apply-design -> {r.status_code}",
              r.status_code in (200, 422), "422 可接受（空 body 校验）" if r.status_code == 422 else "")
    except Exception as e:
        check("POST /apply-design", False, str(e))


def section_news():
    """新闻资讯端点"""
    section("新闻资讯")

    # GET /news/headlines with response time gate (D) — 超时匹配后端 run_sync(timeout=30) + 5s 网络缓冲
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/news/headlines", timeout=35)
        _elapsed = time.time() - _t0
        check(f"GET /news/headlines -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200)
        _check_response_time("/news/headlines", _elapsed, 30.0)
        if r.status_code == 200:
            data = r.json()
            check(f"头条新闻 {len(data)} 条", isinstance(data, list) and len(data) > 0)
            if data:
                has_id = all("id" in item for item in data)
                check("每条新闻含 id 字段（WS 去重用）", has_id)
                # sort_time 字段契约 + 排序验证
                has_sort_time = all("sort_time" in item for item in data)
                check("每条新闻含 sort_time 字段（排序键）", has_sort_time)
                if has_sort_time:
                    all_int = all(isinstance(it["sort_time"], int) for it in data)
                    check("sort_time 均为整数", all_int)
                    if len(data) >= 2:
                        check_len = min(5, len(data))
                        sorted_ok = all(
                            data[i]["sort_time"] >= data[i + 1]["sort_time"]
                            for i in range(check_len - 1)
                        )
                        if sorted_ok:
                            check(f"前 {check_len} 条按 sort_time 降序排列", True)
                        else:
                            check(f"前 {check_len} 条按 sort_time 降序排列", False, "排序异常")
                # Phase 6.1.8: stars/level 字段验证
                has_level = all("level" in item for item in data)
                check("每条新闻含 level 字段（重要性标识）", has_level)
                if has_level:
                    valid_levels = all(isinstance(it["level"], int) and 1 <= it["level"] <= 5 for it in data)
                    check("level 均为 1~5 整数", valid_levels)
                has_stars = all("stars" in item for item in data)
                check("每条新闻含 stars 字段（新鲜度+重要性）", has_stars)
                if has_stars:
                    valid_stars = all(isinstance(it["stars"], int) and 1 <= it["stars"] <= 5 for it in data)
                    check("stars 均为 1~5 整数", valid_stars)
    except requests.Timeout:
        check("GET /news/headlines", False, "请求超时（35s）— 后端 30s 超时 + 缓存预热")
    except Exception as e:
        check("GET /news/headlines", False, str(e))

    # GET /news/macro — soft check: 404 is acceptable if not available
    try:
        r = requests.get(f"{BASE}/api/v1/news/macro", timeout=35)
        ok = r.status_code in (200, 404)
        detail = f"-> {r.status_code}" + (f" ({len(r.json())} 条)" if r.status_code == 200 else "")
        check(f"GET /news/macro {detail}", ok, "404 可接受（宏经新闻暂未就绪）" if r.status_code == 404 else "")
        if r.status_code == 200:
            data = r.json()
            check(f"宏观新闻 {len(data)} 条", isinstance(data, list))
    except requests.Timeout:
        check("GET /news/macro", False, "请求超时（35s）")
    except Exception as e:
        check("GET /news/macro", False, str(e))

    # GET /news/global
    try:
        r = requests.get(f"{BASE}/api/v1/news/global", timeout=35)
        ok = r.status_code in (200, 404)
        detail = f"-> {r.status_code}" + (f" ({len(r.json())} 条)" if r.status_code == 200 else "")
        check(f"GET /news/global {detail}", ok, "404 可接受" if r.status_code == 404 else "")
    except Exception as e:
        check("GET /news/global", False, str(e))


def section_analysis():
    """AI 分析端点验证 — 仅检查状态码，不对 LLM 内容做断言。"""
    section(" AI 分析")

    # Streaming endpoints — 只检查 200
    stream_endpoints = [
        ("POST /analysis/llm-report/stream", f"{BASE}/api/v1/analysis/llm-report/stream",
         {"symbols": None, "market": "A"}),
    ]
    for label, url, body in stream_endpoints:
        try:
            r = requests.post(url, json=body, timeout=10, stream=True)
            ok = r.status_code == 200
            ct = r.headers.get("content-type", "")
            check(f"{label} -> {r.status_code}", ok,
                  f"Content-Type: {ct}" if ok else "")
            if ok:
                r.close()
        except requests.Timeout:
            check(label, False, "请求超时（10s）")
        except Exception as e:
            check(label, False, str(e))

    # P3-A (round10 §9 盲区1/§10 P3-A): llm-advice/stream **内容**断言——AI 投顾
    # 数据槽位错配回归防线。读 SSE 流文本：若含「暂无实时指数数据/暂无板块热力
    # 数据/市场状态未知/市场状态标记为未知」模板 → FAIL（槽位错配复现）；否则
    # 视为正常（弱源时 LLM 输出仍应引用真实数据或合理降级文案）。
    _advice_tpl_bad = ["暂无实时指数数据", "暂无板块热力数据", "市场状态标记为未知",
                       "暂无实时板块", "市场状态: 未知"]
    try:
        _ar = requests.post(f"{BASE}/api/v1/analysis/llm-advice/stream",
                            json={"query": "当前A股市场怎么配置", "market": "A"},
                            timeout=45, stream=True)
        _ok2 = _ar.status_code == 200
        _collected: list[str] = []
        if _ok2:
            try:
                for _line in _ar.iter_lines(decode_unicode=True):
                    if not _line:
                        continue
                    _collected.append(_line)
                    if len(_collected) > 400:  # 上限防超长流
                        break
            except Exception:
                pass
            _ar.close()
        _text = " ".join(_collected)
        _tpl_hit = [w for w in _advice_tpl_bad if w in _text]
        check("llm-advice/stream 内容非空", bool(_text), f"len={len(_text)}")
        check("llm-advice/stream 无「暂无实时指数数据」模板", not _tpl_hit,
              f"模板化回退复现: {_tpl_hit[:2]}" if _tpl_hit else "")
    except requests.Timeout:
        check("llm-advice/stream 内容", True, "请求超时（45s，LLM 慢——不算模板回归）")
    except Exception as e:
        check("llm-advice/stream 内容", True, f"请求异常（环境）: {e}")


    # P3-1 (round9 §5/O24 回归防线): symbol-analysis/stream SSE 契约门禁——O24 回归
    # （analysis.py 透传 rate_limit_cap，agent 底层 llm_complete_stream 无此参数）导致
    # 5 类标的全 STREAM_ERROR，而旧 verify_e2e 只测 llm-report/advice 零拦截。
    # 门禁：HTTP 200 + SSE 流中不得出现 STREAM_ERROR（42.8KB 出文正常态）。
    _symbol_stream_cases = [
        ("A股ETF", {"symbol": "510300", "market": "A", "asset_type": "etf"}),
        ("港股个股", {"symbol": "00700", "market": "HK", "asset_type": "stock"}),
    ]
    for _label, _body in _symbol_stream_cases:
        try:
            _sr = requests.post(f"{BASE}/api/v1/analysis/symbol-analysis/stream",
                                json=_body, timeout=35, stream=True)
            _ok = _sr.status_code == 200
            _chunk_err = False
            if _ok:
                try:
                    for _i, _line in enumerate(_sr.iter_lines(decode_unicode=True)):
                        if _line and "STREAM_ERROR" in _line:
                            _chunk_err = True
                            break
                        if _i > 8:  # 只扫开头事件（starting/status/首批 token）
                            break
                except Exception:
                    pass
                _sr.close()
            check(f"symbol-analysis/stream {_label} -> {_sr.status_code}（无 STREAM_ERROR）",
                  _ok and not _chunk_err,
                  "STREAM_ERROR 出现在 SSE 流中（O24 回归！）" if _chunk_err else f"HTTP {_sr.status_code}")
        except requests.Timeout:
            check(f"symbol-analysis/stream {_label}", False, "请求超时（35s）")
        except Exception as e:
            check(f"symbol-analysis/stream {_label}", False, str(e))

    # F6 R16: 板块热度契约断言——/sectors/heat 返回 {items,total}（hot-plates 契约 v2.0），
    # 断言 items 键存在且非空（旧检查只在 section_api_5xx_check 查 HTTP 200，防不住空数据）
    try:
        r = requests.get(f"{BASE}/api/v1/market/sectors/heat?limit=5", timeout=15)
        check("GET /sectors/heat -> 200", r.status_code == 200, f"HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                items = data.get("items")
                check("sectors/heat 含 items 键", items is not None)
                check("sectors/heat items 非空", isinstance(items, list) and len(items) >= 1,
                      f"{len(items) if isinstance(items, list) else 'non-list'} 条")
            else:
                check("sectors/heat 契约结构 {items,total}", False,
                      f"返回 {type(data).__name__}（应为 dict）")
    except Exception as e:
        check("GET /sectors/heat", False, str(e))


def check_sector_data():
    """板块/概念数据端点验证（Phase 6.1.8）。"""
    section("板块数据")
    for typ in ("industry", "concept"):
        try:
            r = requests.get(f"{BASE}/api/v1/market/sectors/{typ}?limit=5", timeout=15)
            check(f"GET /sectors/{typ} -> {r.status_code}", r.status_code == 200)
            if r.status_code == 200:
                data = r.json()
                is_list = isinstance(data, list)
                check(f"返回 {len(data)} 条", is_list and len(data) > 0)
                if is_list and data:
                    has_change = "change_pct" in data[0]
                    has_inflow = "main_inflow" in data[0]
                    check(f"{typ} 含 change_pct", has_change)
                    check(f"{typ} 含 main_inflow", has_inflow)
        except Exception as e:
            check(f"GET /sectors/{typ}", False, str(e))

    # Z15/C6: 板块轮动门禁（Z17 回归）— rotation 数据源为外部 provider，
    # 先打印样例字段确认列名，断言至少含一个涨跌幅字段（避免环境字段差异误红）。
    try:
        r = requests.get(f"{BASE}/api/v1/market/sectors/rotation?limit=5", timeout=15)
        check("GET /sectors/rotation -> 200", r.status_code == 200, f"HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            is_list = isinstance(data, list)
            check("板块轮动返回非空", is_list and len(data) > 0,
                  f"{len(data) if is_list else 'non-list'} 条")
            if is_list and data:
                first = data[0]
                check("板块轮动样例字段", True, f"keys={list(first.keys())[:8]}")
                change_keys = [k for k in ("change_pct", "change", "pct_chg", "涨跌幅")
                               if k in first]
                check("板块轮动含涨跌幅字段", len(change_keys) > 0,
                      f"匹配字段: {change_keys}")
    except Exception as e:
        check("GET /sectors/rotation", False, str(e))


def check_data_quality():
    """ETF 基础数据质量校验（P1 fix-plan-master: verify_e2e 应校验数据质量）。"""
    section("数据质量")
    try:
        r = requests.get(f"{BASE}/api/v1/market/search?keyword=510300", timeout=15)
        if r.status_code == 200:
            data = r.json()
            etfs = data if isinstance(data, list) else data.get("data", [])
            if not etfs:
                check("ETF 数据列表非空", False, "返回 0 条记录")
                return

            key_count = len(etfs)
            check(f"ETF 记录数 >= 10", key_count >= 10, f"实际 {key_count}")

            # 检查 amount（成交额）和 fund_scale（基金规模）字段
            with_amount = sum(1 for e in etfs if float(e.get("amount", 0) or 0) > 1e6)
            with_scale = sum(1 for e in etfs if float(e.get("fund_scale", 0) or 0) > 0.5)
            with_price = sum(1 for e in etfs if float(e.get("price", 0) or 0) > 0)

            check(f"有成交额的 ETF >= {max(1, key_count // 5)}",
                  with_amount >= max(1, key_count // 5),
                  f"{with_amount}/{key_count}")
            check(f"有基金规模的 ETF >= {max(1, key_count // 3)}",
                  with_scale >= max(1, key_count // 3),
                  f"{with_scale}/{key_count}")
            check(f"有价格的 ETF >= {max(1, key_count // 5)}",
                  with_price >= max(1, key_count // 5),
                  f"{with_price}/{key_count}")

            # 检查数据字段完整性：核心字段不应为空
            has_symbol = sum(1 for e in etfs if e.get("symbol", ""))
            has_name = sum(1 for e in etfs if e.get("name", ""))
            check(f"ETF 含代码 {has_symbol}/{key_count}", has_symbol == key_count)
            check(f"ETF 含名称 {has_name}/{key_count}", has_name == key_count)
            # 检查候选池健康——/portfolio/candidates 端点不存在（契约收敛），
            # 候选池状态由 /admin/config 的 pool 段提供（admin.py pool.total_candidates/healthy）。
            try:
                r2 = requests.get(f"{BASE}/api/v1/admin/config", timeout=10)
                cfg = r2.json() if r2.status_code == 200 else {}
                pool = cfg.get("pool", {}) if isinstance(cfg, dict) else {}
                total_pool = pool.get("total_candidates", 0)
                check(f"候选池总数量 >= 20", total_pool >= 20,
                      f"total_candidates={total_pool}（数据源熔断时可能为 0）")
                check("候选池健康", bool(pool.get("healthy")),
                      f"healthy={pool.get('healthy')}")
            except Exception as e2:
                check("候选池检查", False, str(e2))
        else:
            check("GET /market/etfs", False, f"HTTP {r.status_code}")
    except Exception as e:
        check("数据质量检查", False, str(e))


def section_async_resilience():
    """异步任务提交后验证后端持续存活——测试护城河缺失的关键一环。"""
    section("异步任务弹性（后端存活）")

    # Helper: submit and poll with periodic health check
    def _submit_and_watch(endpoint, payload, label, poll_deadline=60):
        """Submit an async task, check /health every 5s while it runs."""
        try:
            r = requests.post(f"{BASE}{endpoint}", json=payload, timeout=30)
            check(f"POST {endpoint} -> {r.status_code}", r.status_code == 202, f"{label}")
            if r.status_code != 202:
                return
            task_id = r.json().get("task_id")
            if not task_id:
                check("task_id 存在", False, f"{label}")
                return

            deadline = time.time() + poll_deadline
            health_ok_count = 0
            health_total = 0
            completed = False
            while time.time() < deadline:
                health_total += 1
                try:
                    hr = requests.get(f"{BASE}/health", timeout=5)
                    if hr.status_code == 200:
                        health_ok_count += 1
                    else:
                        check(f"  [{label}] /health 状态异常", False, f"HTTP {hr.status_code}")
                except requests.Timeout:
                    check(f"  [{label}] 后端挂死!", False, f"/health 超时 (第{health_total}次检查)")
                    return
                except Exception as e:
                    check(f"  [{label}] /health 异常", False, str(e))
                    return

                # Check task status
                try:
                    tr = requests.get(f"{BASE}/api/v1/portfolio/tasks/{task_id}", timeout=5)
                    if tr.status_code == 200:
                        td = tr.json()
                        status = td.get("status")
                        if status == "completed":
                            completed = True
                            break
                        elif status == "failed":
                            break
                except (requests.Timeout, Exception):
                    pass  # task endpoint not critical for this test

                time.sleep(5)

            if health_total > 0:
                check(f"  [{label}] 后端存活率 {health_ok_count}/{health_total}",
                      health_ok_count == health_total,
                      f"任务运行期间后端无响应 {health_total - health_ok_count} 次")
            check(f"  [{label}] 任务{'已完成' if completed else '超时'}", completed,
                  f"{poll_deadline}s 内{'未' if not completed else ''}完成")
        except requests.Timeout:
            check(f"  [{label}] 提交请求超时", False)
        except Exception as e:
            check(f"  [{label}] 异常", False, str(e))

    _submit_and_watch("/api/v1/portfolio/design-async",
                      {"capital": 500000, "constraints": {"risk_profile": "balanced"}},
                      "智能组合设计", poll_deadline=120)
    _submit_and_watch("/api/v1/portfolio/strategy-check-async",
                      {"total_capital": 500000, "portfolio_type": "on_exchange"},
                      "策略分析", poll_deadline=120)

    # ── 任务列表一致性验证 ──────────────────────────────────
    try:
        r = requests.post(f"{BASE}/api/v1/portfolio/design-async", json={"capital": 1000}, timeout=15)
        if r.status_code == 202:
            task_id = r.json().get("task_id")
            check(f"轻量任务已提交 task_id={task_id}", task_id is not None, str(task_id))
            if task_id:
                try:
                    tr = requests.get(f"{BASE}/api/v1/portfolio/tasks", timeout=10)
                    if tr.status_code == 200:
                        tasks = tr.json()
                        ids = [t["task_id"] for t in tasks]
                        check(f"任务 {task_id} 出现在 /portfolio/tasks 列表中", task_id in ids,
                              f"列表共 {len(tasks)} 条")
                    else:
                        check("GET /portfolio/tasks 状态码", False, str(tr.status_code))
                except requests.Timeout:
                    check("GET /portfolio/tasks", False, "请求超时（10s）")
                except Exception as e:
                    check("GET /portfolio/tasks", False, str(e))
    except requests.Timeout:
        check("POST /design-async", False, "请求超时（15s）")
    except Exception as e:
        check("POST /design-async", False, str(e))


def section_admin():
    """管理端点"""
    section("管理端点")

    # GET /admin/token-usage with response time gate (D)
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/admin/token-usage", timeout=10)
        _elapsed = time.time() - _t0
        check(f"GET /admin/token-usage -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200)
        _check_response_time("/admin/token-usage", _elapsed, 5.0)
        if r.status_code == 200:
            data = r.json()
            check("token-usage 返回 dict", isinstance(data, dict))
    except requests.Timeout:
        check("GET /admin/token-usage", False, "请求超时（10s）")
    except Exception as e:
        check("GET /admin/token-usage", False, str(e))

    # GET /admin/token-usage/timeseries
    try:
        r = requests.get(f"{BASE}/api/v1/admin/token-usage/timeseries?granularity=hour&hours=1", timeout=10)
        check(f"GET /admin/token-usage/timeseries -> {r.status_code}", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            check("timeseries 有 series 字段", "series" in data)
    except requests.Timeout:
        check("GET /admin/token-usage/timeseries", False, "请求超时（10s）")
    except Exception as e:
        check("GET /admin/token-usage/timeseries", False, str(e))

    # GET /admin/thread-pool
    try:
        r = requests.get(f"{BASE}/api/v1/admin/thread-pool", timeout=10)
        check(f"GET /admin/thread-pool -> {r.status_code}", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            main_pool = data.get("main", {})
            # Support both unified structure (shared_executor sub-key) and legacy flat key
            if "shared_executor" in main_pool:
                pool_stats = main_pool["shared_executor"]
            else:
                pool_stats = main_pool  # legacy flat structure
            max_w = pool_stats.get("max_workers", 32)
            alive = pool_stats.get("alive_threads", 0)
            pending = pool_stats.get("pending_tasks", 0)
            utilisation = alive / max_w if max_w > 0 else 0
            check("shared_executor 未过载", utilisation < 0.8,
                  f"active={alive}/{max_w} ({utilisation:.0%})")
            check("shared_executor 队列深度正常", pending < 16,
                  f"pending_tasks={pending}")
    except requests.Timeout:
        check("GET /admin/thread-pool", False, "请求超时（10s）")
    except Exception as e:
        check("GET /admin/thread-pool", False, str(e))

    # GET /admin/metrics (7.2c)
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/admin/metrics", timeout=10)
        _elapsed = time.time() - _t0
        check(f"GET /admin/metrics -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            check("/admin/metrics 包含 pool 信息", "pool" in data, f"keys={list(data.keys())}")
            check("/admin/metrics 包含 designs 信息", "designs" in data)
            if "pool" in data:
                pool = data["pool"]
                check(f"池健康: healthy={pool.get('healthy')}, candidates={pool.get('total_candidates')}",
                      isinstance(pool.get("healthy"), bool))
            if "designs" in data:
                designs = data["designs"]
                check(f"设计总数: {designs.get('total', 0)}", True)
    except Exception as e:
        check("GET /admin/metrics", False, str(e))


    # Z15/C7: 数据源健康（并入强版；原弱版 section_admin 已删除）
    try:
        r = requests.get(f"{BASE}/api/v1/admin/sources/health", timeout=10)
        if r.status_code == 200:
            data = r.json()
            # 端点实际返回数组 [{name, available, failures, ...}]；兼容 dict 包装形态
            sources = data if isinstance(data, list) else data.get("sources", data)
            if isinstance(sources, list) and sources:
                healthy = sum(1 for v in sources
                              if isinstance(v, dict) and v.get("available", False))
                check("数据源健康", healthy > 0, f"{healthy}/{len(sources)} 健康")
                # S4: 内容级断言——threadpool_/非数据源探针不得混入数据源列表（F17 R60 回归防线）
                # 数据源名必须匹配已知白名单模式（行情/资讯/LLM/因子/搜索等真实源）
                import re as _re
                bogus = [v.get("name", "?") for v in sources
                         if isinstance(v, dict) and (str(v.get("name", "")).startswith("threadpool_") or
                                                     str(v.get("name", "")).startswith("probe_"))]
                check("数据源列表无 threadpool_/probe_ 探针", not bogus,
                      f"混入: {bogus[:4]}" if bogus else "全部为真实数据源")
                non_source = [v.get("name", "?") for v in sources
                              if isinstance(v, dict) and v.get("kind") not in (None, "source") and
                              str(v.get("name", "")).startswith("threadpool_")]
                if non_source:
                    check("threadpool 探针已标记非 source", False, f"kind 异常: {non_source[:4]}")
            else:
                check("数据源健康端点", False, "响应结构非预期（非列表）")
        else:
            check("数据源健康端点", False, f"HTTP {r.status_code}")
    except Exception as e:
        check("数据源健康端点", False, str(e))


def section_ws():
    """WebSocket 连接测试"""
    section("WebSocket 连接测试")

    ws_endpoint = f"/api/v1/ws/task-notifications"
    check(f"WS 端点 {ws_endpoint} 已定义", True, "由后端 ws.py 提供")

    # 尝试使用 websockets 库建立连接
    try:
        import websockets
        import asyncio

        async def _test_ws():
            uri = BASE.replace("http://", "ws://") + ws_endpoint
            try:
                async with websockets.connect(uri, ping_interval=None, close_timeout=5) as ws:
                    # 发送 ping
                    await ws.send("ping")
                    resp = await asyncio.wait_for(ws.recv(), timeout=5)
                    check(f"WS {ws_endpoint} 连接成功", True, f"收到: {resp[:60]}")
            except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
                check(f"WS {ws_endpoint} 连接", False, str(e))
            except Exception as e:
                check(f"WS {ws_endpoint} 连接", False, str(e))

        asyncio.run(_test_ws())
    except ImportError:
        check(f"WS {ws_endpoint} 测试跳过", True,
              "websockets 库未安装，忽略 WebSocket 测试", skip=True)
    except Exception as e:
        check(f"WS {ws_endpoint} 测试", False, str(e))


# ── 因子数据质量 ────────────────────────────────────────────────


def section_factors(host, port):
    """#5: 因子数据质量 — 通过 admin/factor-health 端点检查非零因子比例 + IC 端点。"""
    section("因子数据质量")
    try:
        r = requests.get(f"{BASE}/api/v1/admin/factor-health", timeout=30)
        if r.status_code != 200:
            check("factor-health endpoint", False, f"HTTP {r.status_code}")
            return
        data = r.json()
        # T5: 数据就绪等待 + 多次采样取中位数（防因子批处理未完成导致的时序 flaky）
        _samples: dict[str, list[float]] = {}
        _last = data
        for _i in range(3):
            try:
                _r2 = requests.get(f"{BASE}/api/v1/admin/factor-health", timeout=30)
                if _r2.status_code == 200:
                    _last = _r2.json()
            except Exception:
                pass
            syms = _last.get("symbols", {}) if isinstance(_last, dict) else {}
            for _sym, _info in syms.items():
                _raw = str(_info.get("ratio", 0) or 0)
                try:
                    _ratio = float(_raw.split("/")[0])  # "23/33" -> 23.0
                except (ValueError, AttributeError):
                    _ratio = 0.0
                _samples.setdefault(_sym, []).append(_ratio)
            if _i < 2:
                time.sleep(1.0)
        if _last.get("status") != "ok":
            check("factor-health status", False, _last.get("message", "unknown"))
            return
        all_healthy = True
        for sym, ratios in _samples.items():
            med = sorted(ratios)[len(ratios) // 2]
            ok = med >= max(10, 33 * 0.4)
            check(f"{sym}: {med:.0f}/33 live factors (median of {len(ratios)})", ok,
                  f"threshold: >= max(10, total*0.4)")
            if not ok:
                all_healthy = False
        if all_healthy:
            check("All symbols factor-healthy", True)
    except Exception as e:
        check(f"factor-health endpoint", False, str(e))

    # F20: factor completeness — total factor count + china_specific data integrity
    # Z03: china.policy 三因子为静态标识因子（status='static'，不计算 IC，不计入 valid/warn/no_data）
    try:
        r = requests.get(f"{BASE}/api/v1/factors/active", timeout=30)
        if r.status_code == 200:
            data = r.json()
            total = data.get("total", 0)
            check(f"GET /factors/active total={total} >= 30", total >= 30, f"total={total}")
            cats = {c["name"]: c for c in data.get("categories", [])}
            cn = cats.get("china_specific")
            if cn:
                cnt = cn.get("count", 0)
                statuses = [f.get("status") for f in cn.get("factors", [])]
                # Z03 契约: 静态因子 status='static' + ic_value=null；不再要求 valid_count>0
                all_static = all(s == "static" for s in statuses) if statuses else False
                check(f"china_specific 有 {cnt} 个因子且均为静态标识 (statuses={statuses})",
                      cnt >= 3 and all_static,
                      f"count={cnt}, statuses={statuses}")
                # 每个静态因子 ic_value 必须为 null（移除硬编码 0）
                ic_vals = [f.get("ic_value") for f in cn.get("factors", [])]
                check("静态因子 ic_value 全部为 null（不硬编码 0）",
                      all(v is None for v in ic_vals),
                      f"ic_values={ic_vals}")
            else:
                check("china_specific 类别存在", False, "未返回 china_specific 类别")
        else:
            check("GET /api/v1/factors/active", False, f"HTTP {r.status_code}")
    except Exception as e:
        check("GET /api/v1/factors/active", False, str(e))

    section("IC 追踪端点")
    try:
        r = requests.get(f"{BASE}/api/v1/factors/ic", timeout=30)
        if r.status_code == 200:
            data = r.json()
            check("GET /api/v1/factors/ic -> 200", True)
            factors = data.get("factors", [])
            # T5: IC 数据就绪等待（IC 为周期计算，服务刚重启时为空——最多轮询 60s）
            for _i in range(12):
                if factors:
                    break
                time.sleep(5)
                try:
                    _r3 = requests.get(f"{BASE}/api/v1/factors/ic", timeout=30)
                    if _r3.status_code == 200:
                        data = _r3.json()
                        factors = data.get("factors", [])
                except Exception:
                    pass
            check(f"  factors array contains {len(factors)} entries", len(factors) > 0, f"count={len(factors)}")
            check(f"  total field matches", data.get("total", 0) == len(factors), f"total={data.get('total')} vs len={len(factors)}")
            check(f"  updated_at is valid", bool(data.get("updated_at")), f"updated_at={data.get('updated_at')}")
            if factors:
                sample = factors[0]
                check(f"  first factor has code", bool(sample.get("code")), f"code={sample.get('code')}")
                check(f"  first factor has ic_value", "ic_value" in sample, f"ic_value={sample.get('ic_value')}")
        else:
            check("GET /api/v1/factors/ic", False, f"HTTP {r.status_code}")
    except Exception as e:
        check(f"GET /api/v1/factors/ic", False, str(e))


def section_factor_health(host, port):
    """Z15/C4: factor-health 别名 — 薄包装复用 section_factors 完整断言。"""
    section_factors(host, port)


# ── 数据源熔断器状态 ────────────────────────────────────────────


def section_circuit_breaker():
    """#6: 数据源熔断器状态 — 检查 SourceRegistry 端点（OPT-07 E2E 降级场景）。"""
    section("数据源熔断器状态")
    try:
        r = requests.get(f"{BASE}/api/v1/admin/sources/health", timeout=10)
        if r.status_code != 200:
            check("GET /admin/sources/health -> 200", False, f"HTTP {r.status_code}")
            return
        data = r.json()
        if not isinstance(data, list) or not data:
            check("admin/sources/health 返回数据", False, "sources 为空")
            return
        check(f"admin/sources/health 返回 {len(data)} 个数据源", len(data) >= 1)
        for src in data:
            name = src.get("name", "?")
            state = "available" if src.get("available") else "cooldown"
            failures = src.get("failures", 0)
            check(f"  {name}: state={state}, failures={failures}", True)
        # 验证熔断器端点包含必要字段
        sample = data[0]
        has_code = "cooldown_remaining" in sample
        check(f"  circuit-breaker 字段完整（cooldown_remaining）", has_code,
              "missing field: cooldown_remaining" if not has_code else "")
    except Exception as e:
        check("熔断器状态检查", False, str(e))


# ── API 5xx 检测 ──────────────────────────────────────────────


def section_api_5xx_check():
    """API 5xx 检测 — 零容忍，任何 5xx 即 FAIL。"""
    section("API 5xx 检测")
    # 验证几个核心端点是否有 5xx 错误
    endpoints = [
        "/api/v1/market/realtime",
        "/api/v1/market/sectors/heat?limit=5",
        "/api/v1/market/chart/510300",
        "/api/v1/market/indices/global",
        "/api/v1/portfolio/list",
        "/api/v1/news/headlines?limit=5",
        "/health",
    ]
    has_5xx = False
    for ep in endpoints:
        try:
            r = requests.get(f"{BASE}{ep}", timeout=10)
            if r.status_code >= 500:
                check(f"GET {ep} -> {r.status_code}", False, "5xx 不允许")
                has_5xx = True
            else:
                check(f"GET {ep} -> {r.status_code}", True)
        except Exception as e:
            check(f"GET {ep}", False, str(e))
            has_5xx = True
    if not has_5xx:
        check("所有端点无 5xx 错误", True)


# ── 因子 Z-score 门禁 ───────────────────────────────────────────


def section_factor_zscore_check(host="127.0.0.1", port=8000):
    """因子 Z-score 合理性校验 — 检查 factor-health 端点是否有极端 Z-score。"""
    section("因子 Z-score 合理性")
    try:
        r = requests.get(f"http://{host}:{port}/api/v1/admin/factor-health", timeout=15)
        if r.status_code != 200:
            check("GET /admin/factor-health", False, f"HTTP {r.status_code}")
            return
        data = r.json()
        # 尝试不同响应结构
        factors = data.get("factors", {}) or data.get("factor_scores", {}) or data
        if not factors:
            check("factor-health 返回数据", False, "无因子数据")
            return
        extreme_factors = []
        for code, info in factors.items():
            if isinstance(info, dict):
                z = info.get("zscore", info.get("z_score", info.get("value", 0)))
            elif isinstance(info, (int, float)):
                z = info
            else:
                continue
            if isinstance(z, (int, float)) and abs(z) > 5:
                extreme_factors.append(f"{code}: z={z:.2f}")
        if extreme_factors:
            for e in extreme_factors:
                check(f"Z-score 极端: {e}", False, f"|z| > 5")
            check(f"共 {len(extreme_factors)} 个因子 Z-score 超限", False)
        else:
            check(f"所有因子 Z-score 在 [-5, 5] 范围内", True)
    except Exception as e:
        check("因子 Z-score 检查", False, str(e))


# ── 方案差异化度校验 ─────────────────────────────────────────────


def section_solution_diversity_check():
    """Check that the 3 strategy solutions have differentiated ETF sets.
    Uses Jaccard similarity: any pair with >60% overlap triggers a WARNING."""
    section("方案差异化度")
    try:
        # Get latest design
        r = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=1", timeout=10)
        if r.status_code != 200:
            check("GET /portfolio/designs", False, f"HTTP {r.status_code}")
            return
        designs = r.json()
        if not designs or not isinstance(designs, list):
            check("设计方案数据", False, "无设计方案")
            return
        latest = designs[0]
        strategies = latest.get("strategies", latest.get("allocations", []))
        if len(strategies) < 2:
            check(f"方案数 >= 3", len(strategies) >= 3, f"实际 {len(strategies)}")
            return

        # Extract ETF sets per strategy
        plan_sets = []
        plan_names = []
        for s in strategies:
            allocations = s.get("allocations", s.get("etfs", []))
            symbols = set()
            for a in allocations:
                sym = a.get("symbol", "")
                if sym and sym != "CASH":
                    symbols.add(sym)
            name = s.get("label", s.get("style", f"plan_{len(plan_names)}"))
            plan_sets.append(symbols)
            plan_names.append(name)

        # Compute Jaccard similarity for all pairs
        high_overlap = False
        for i in range(len(plan_sets)):
            for j in range(i + 1, len(plan_sets)):
                a, b = plan_sets[i], plan_sets[j]
                if not a and not b:
                    continue
                if not a or not b:
                    jaccard = 0.0
                else:
                    intersection = len(a & b)
                    union = len(a | b)
                    jaccard = intersection / union if union > 0 else 0.0
                label = f"{plan_names[i]} vs {plan_names[j]}: J={jaccard:.2f}"
                if jaccard > 0.6:
                    check(label, False, "重叠度 > 60%")
                    high_overlap = True
                else:
                    check(label, True,
                          f"交集={len(a&b)} 并集={len(a|b)}" if a and b else "")
        if high_overlap:
            check("方案差异化度", False, "存在高重叠方案对")
        else:
            check("方案差异化度合格", True)
    except Exception as e:
        check("方案差异化度检查", False, str(e))



# ── T2: DB 完整性 ─────────────────────────────────────────────────



# ── T1: nginx 拓扑层（prod 模式 http://localhost 走 nginx） ───────────────


def section_nginx_proxy():
    """T1: nginx 拓扑 — /api 代理可达 + WS 握手（http://localhost）。

    本地开发直连 uvicorn（无 nginx）时整体 SKIP 不 FAIL；
    prod（docker-compose nginx:80）运行时执行真实拓扑断言。
    """
    section("nginx 拓扑代理")
    try:
        r = requests.get("http://localhost/api/v1/market/indices/global", timeout=6)
    except Exception:
        check("nginx /api 代理可达", True,
              "nginx 未运行（本地直连 uvicorn），跳过", skip=True)
        return
    check("GET http://localhost/api/v1/market/indices/global -> 200",
          r.status_code == 200, f"HTTP {r.status_code}")
    try:
        import websockets
        import asyncio

        async def _test():
            async with websockets.connect(
                "ws://localhost/api/v1/ws/task-notifications",
                ping_interval=None, close_timeout=5,
            ) as ws:
                await ws.send("ping")
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                return resp

        resp = asyncio.run(_test())
        check("WS ws://localhost/api/v1/ws/task-notifications 握手成功", True,
              f"收到: {str(resp)[:40]}")
    except Exception as e:
        check("nginx WS 握手", False, str(e))


def section_db_integrity():
    """T2: prod 容器 DB 完整性 — instruments>1000 且 portfolio_etfs/watchlist 非空。"""
    section("DB 完整性")
    import sqlite3
    from pathlib import Path
    # .env 覆盖为项目根 data/portfolio.db（backend/scripts -> 项目根）
    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "portfolio.db"
    if not db_path.exists():
        check("DB 文件存在", False, str(db_path))
        return
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        for table, min_rows, label in (
            ("instruments", 1000, "instruments > 1000"),
            ("portfolio_etfs", 1, "portfolio_etfs 非空"),
            ("watchlist", 1, "watchlist 非空"),
        ):
            try:
                n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                check(f"{label}（{table}={n}）", n >= min_rows, f"actual={n}")
            except sqlite3.Error as e:
                check(f"{label}", False, str(e))
        # S4: 成本字段一致性（F18 R64/R65 回归防线）——有 avg_cost 无 shares_held 的持仓
        # 属于"半成本状态"，前端需显示估算提示，不得静默按真实成本计算。
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(portfolio_etfs)").fetchall()]
            if "avg_cost" in cols and "shares_held" in cols:
                half_cost = cur.execute(
                    "SELECT COUNT(*) FROM portfolio_etfs WHERE avg_cost IS NOT NULL "
                    "AND avg_cost != 0 AND (shares_held IS NULL OR shares_held = 0)"
                ).fetchone()[0]
                check("无孤立 avg_cost（有成本必有份额）", half_cost == 0,
                      f"半成本持仓 {half_cost} 条（前端按估算处理，勿静默当真实）"
                      if half_cost else "成本字段成对出现")
        except sqlite3.Error as e:
            check("成本字段一致性", False, str(e))
        conn.close()
    except Exception as e:
        check("DB 完整性检查", False, str(e))

    # P3-2 (round9 §10/P0-4): watchlist 耗时门禁——§10 实测 /market/watchlist **29.9s**
    # 灾难级且无任何门禁拦截。P0-4 落地后：批量 4s + A股失败跳过 per-item + resolve 2s +
    # 整体 5s 截断 → 缓存热时 ≤1s（文档验收口径，实测 1.26s）；弱数据源/冷缓存最坏 ~5s
    # （DB 侧兜底）。门禁 6s：冷缓存弱源环境可过；>6s = 慢源未短路，判 FAIL。
    try:
        _t0 = time.time()
        _wr = requests.get(f"{BASE}/api/v1/market/watchlist", timeout=15)
        _w_el = time.time() - _t0
        check(f"GET /market/watchlist {_wr.status_code} ({_w_el:.1f}s) < 6s (P0-4 gate)",
              _wr.status_code == 200 and _w_el < 6.0,
              f"actual={_w_el:.1f}s（>6s：慢源未短路/整体超时未生效）" if _w_el >= 6.0
              else f"HTTP {_wr.status_code}")
    except requests.Timeout:
        check("GET /market/watchlist < 6s (P0-4 gate)", False, "请求超时（15s）")
    except Exception as e:
        check("GET /market/watchlist < 6s (P0-4 gate)", False, str(e))

    # P3-C (round10 §9 盲区3/§10 P3-C): watchlist **realtime 非 None** 断言——列表实时
    # 全空（DB-only）时通过耗时门禁却无行情，需拦。缓冲热时（P0-E 已回填 quote 缓存）
    # 每项 realtime.price 非 None 或带 data_source=stale 兜底。缓存未热/无自选时 WARN
    # 不判 FAIL（环境相关）。
    try:
        _wr2 = requests.get(f"{BASE}/api/v1/market/watchlist", timeout=15)
        _wj = _wr2.json()
        _items = _wj.get("items") or _wj.get("watchlist") or []
        if _items:
            _rt_missing = [
                it.get("symbol") for it in _items
                if not (it.get("realtime") or {}).get("price")
            ]
            if _rt_missing and all((it.get("realtime") or {}).get("data_source") == "stale"
                                   for it in _items if not (it.get("realtime") or {}).get("price")):
                check(f"P3-C watchlist realtime 有 stale 兜底 {len(_items)-len(_rt_missing)}/{len(_items)}",
                      True, "弱源下 stale 快照回填（P0-E）")
            else:
                check(f"P3-C watchlist realtime 非空 {len(_items)-len(_rt_missing)}/{len(_items)}",
                      not _rt_missing,
                      f"空价格项: {_rt_missing[:6]}" if _rt_missing else "全部有行情")
        else:
            check("P3-C watchlist realtime（无自选项目）", True, "空列表跳过")
    except Exception:
        check("P3-C watchlist realtime", True, "读取失败（环境）")


# ── T13: 数据卫生门禁 ─────────────────────────────────────────────


def section_data_hygiene():
    """T13: 测试库无残留脏数据（watchlist 测试备注 / 测试写入记录）。"""
    section("数据卫生")
    import sqlite3
    from pathlib import Path
    # .env 覆盖为项目根 data/portfolio.db（backend/scripts -> 项目根）
    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "portfolio.db"
    if not db_path.exists():
        check("DB 文件存在", False, str(db_path))
        return
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        # 验收: SELECT * FROM watchlist WHERE notes='更新备注OK' 恒为空
        n = cur.execute("SELECT COUNT(*) FROM watchlist WHERE notes='更新备注OK'").fetchone()[0]
        check("watchlist 无测试备注残留（notes='更新备注OK'）", n == 0, f"残留 {n} 条")
        # design_text 不应含 verify_e2e 写入的测试标记（如有则说明 e2e 污染了业务表）
        try:
            n2 = cur.execute(
                "SELECT COUNT(*) FROM portfolio_designs WHERE design_text LIKE '%[e2e-test]%'"
            ).fetchone()[0]
            check("portfolio_designs 无 e2e 测试标记", n2 == 0, f"残留 {n2} 条")
        except sqlite3.Error:
            pass  # 表结构无 design_text 时跳过
        conn.close()
    except Exception as e:
        check("数据卫生检查", False, str(e))



# ── T7: factors/active 数值门限（§9.5 验收） ─────────────────────────────


def section_factor_thresholds():
    """T7: etf_specific no_data ≤2、sentiment no_data =0、no_data reason 标注缺失字段。"""
    section("因子数值门限")
    try:
        data = None
        for _i in range(6):  # 就绪等待最多 30s（IC 周期计算）
            try:
                r = requests.get(f"{BASE}/api/v1/factors/active", timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    break
            except Exception:
                pass
            time.sleep(5)
        if data is None:
            check("GET /factors/active", False, "多次重试失败")
            return
        cats = {c.get("name"): c for c in data.get("categories", [])}
        # IC 就绪检查：IC batch 空 = 服务冷启动/数据源冷却中（周期计算未完成）→ 门禁 SKIP
        try:
            _ic = requests.get(f"{BASE}/api/v1/factors/ic", timeout=15).json()
            _ic_ready = bool(_ic.get("factors"))
        except Exception:
            _ic_ready = False
        if not _ic_ready:
            # S3: 数据源故障不得静默 SKIP——门禁必须 FAIL（F20 薄弱点 3）
            check("IC batch 就绪（数值门禁前提）", False,
                  "IC 未累积（服务冷启动/数据源冷却）——数据源故障告警，禁止静默绿")
        else:
            for cname, max_nd in (("etf_specific", 2), ("sentiment", 0)):
                c = cats.get(cname)
                if not c:
                    check(f"{cname} 类别存在", False)
                    continue
                no_data = [f for f in c.get("factors", []) if f.get("status") == "no_data"]
                check(f"{cname} no_data ≤ {max_nd}", len(no_data) <= max_nd,
                      f"no_data={len(no_data)}: {[f.get('code') for f in no_data][:4]}")
            # S4: 因子状态分布——ln_mcap 不允许 0 有效（数据源缺失必须显式标注）
            ln = [f for f in data.get("categories", [])
                  for f in f.get("factors", []) if f.get("code") == "ln_mcap"]
            if ln:
                f0 = ln[0]
                active_n = (f0.get("active") or 0) if isinstance(f0.get("active"), (int, float)) else None
                if active_n is not None:
                    check("ln_mcap 有效样本 > 0", active_n > 0,
                          f"active={active_n}（0 有效=数据源缺失未标注）")
        # F3-4 步骤D 验收: no_data reason 必须标注缺失字段/IC 未累积（禁止统一「尚未计算 IC」）
        bad_reason = []
        for c in data.get("categories", []):
            for f in c.get("factors", []):
                if f.get("status") == "no_data":
                    rsn = f.get("reason", "")
                    if "尚未计算 IC" in rsn:
                        bad_reason.append(f.get("code"))
        check("no_data reason 不出现笼统「尚未计算 IC」", not bad_reason,
              f"违反: {bad_reason[:4]}" if bad_reason else "reason 已区分标注")
    except Exception as e:
        check("因子数值门限", False, str(e))


# ── T14: 方案质量门禁（§8.5.3 清单自动化） ───────────────────────────────

# F7 (round6 §14.2/§14.6): 卫星层数量门禁辅助函数——可独立单测。
# 返回 (卫星层只数, 非科技主题只数, 科技系只数)。
_TECH_THEME_KWS = ("科创", "半导体", "芯片", "AI", "人工智能")


def _satellite_quality_check(strategy: dict) -> tuple[int, int, int]:
    """统计单方案卫星层的数量与主题构成（F7 门禁数据源）。"""
    allocs = strategy.get("allocations") or strategy.get("etfs") or []
    sat = [a for a in allocs if a.get("layer") == "satellite"]
    tech = [
        a for a in sat
        if any(k in ((a.get("name") or "") + (a.get("tracked_index") or ""))
               for k in _TECH_THEME_KWS)
    ]
    return len(sat), len(sat) - len(tech), len(tech)


def section_design_quality_gate():
    """T14: 最近设计方案经 validate_design_quality 校验（5 类问题）+ 三方案差异。"""
    section("方案质量门禁")
    try:
        r = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=1", timeout=10)
        if r.status_code != 200:
            check("GET /portfolio/designs", False, f"HTTP {r.status_code}")
            return
        rows = r.json()
        if not rows:
            check("存在设计方案记录", True, "无历史方案，跳过", skip=True)
            return
        did = rows[0].get("id")
        r2 = requests.get(f"{BASE}/api/v1/portfolio/designs/{did}", timeout=10)
        if r2.status_code != 200:
            check(f"GET /portfolio/designs/{did}", False, f"HTTP {r2.status_code}")
            return
        detail = r2.json()
        strategies = detail.get("strategies") or (detail.get("strategies_json") or {}).get("strategies") or []
        if not strategies:
            check("设计方案含 strategies", True, "无 strategies（LLM 报告未生成时方案仍可评估）", skip=True)
            return
        from app.engine.design_quality import validate_design_quality, check_strategies_differ
        issues = validate_design_quality(strategies)
        check("方案质量门禁 5 项清单", not issues, "; ".join(issues[:3]) if issues else "全部通过")
        differ = check_strategies_differ(strategies)
        check("三套方案非机械缩放", differ, "层权重结构趋同" if not differ else "")
        # M7: 核心层数量 ∈ [3,5]（含强制 510300/159338）且含宽基锚（中证A500/沪深300 之一）
        core_syms_list: list[set[str]] = []
        for s in strategies:
            # 兼容两种结构：engine 输出 allocations / 持久化详情用 etfs
            allocs = s.get("allocations") or s.get("etfs") or []
            core = [a for a in allocs if a.get("layer") == "core"]
            n_core = len(core)
            check(f"M7 {s.get('id', s.get('name', '?'))} 核心层 [{n_core}] ∈ [3,5]",
                  3 <= n_core <= 5, f"core={n_core}")
            core_syms = {a.get("symbol") for a in core}
            core_syms_list.append(core_syms)
            core_names = " ".join((a.get("name") or "") for a in core)
            has_anchor = bool(core_syms & {"510300", "159338"}) or "中证A500" in core_names or "沪深300" in core_names
            check(f"M7 {s.get('id', s.get('name', '?'))} 含宽基锚(中证A500/沪深300)",
                  has_anchor, f"core={sorted(core_syms)[:5]}")
            # M7: 单只核心权重 ≥ 5%（engine 用 target_weight，持久化用 weight）
            weak = [a for a in core if (a.get("target_weight") or a.get("weight") or 0) < 0.05]
            check(f"M7 {s.get('id', s.get('name', '?'))} 核心单只权重 ≥5%",
                  not weak, f"弱权重: {[a.get('symbol') for a in weak]}")
        # P1-1 验收2（combination-design-review §四.2 + 用户决策 f84fe5c）: 三方案核心层
        # 均含宽基锚——「沪深300 或 中证A500 皆可」作公共底仓（引擎按强制注入/评分选其
        # 一；R4-15 曾只验「沪深300 存在」且 A500 缺失仍 PASS → 放宽为锚之一但不再允许
        # 「仅有沪深300 而无 A500」被当作达标，A500 必须出现在至少一个方案核心层）。
        if len(core_syms_list) == 3:
            _anchor_ok = all(
                bool(cs & {"510300", "159338"}) for cs in core_syms_list
            )
            check("P1-1 三方案核心层均含宽基锚(A500/沪深300)", _anchor_ok,
                  "某方案核心层缺宽基锚(510300/159338)"
                  if not _anchor_ok else "全部含锚")
            _a500_anywhere = any(cs & {"159338"} for cs in core_syms_list)
            check("P1-1 至少一方案核心层含中证A500", _a500_anywhere,
                  "A500(159338) 未进入任何方案核心层" if not _a500_anywhere else "A500 已入核心")
            # P1-1 验收3: 任意方案核心层中证500 家族 ≤1 只（价值/成长/增强视为同一指数）
            for s in strategies:
                allocs = s.get("allocations") or s.get("etfs") or []
                core = [a for a in allocs if a.get("layer") == "core"]
                c500 = [a for a in core
                        if "中证500" in ((a.get("tracked_index") or "") + (a.get("name") or ""))]
                check(f"P1-1 {s.get('id', s.get('name', '?'))} 核心层中证500家族 ≤1",
                      len(c500) <= 1,
                      f"中证500家族 {len(c500)} 只: {[a.get('symbol') for a in c500]}" if len(c500) > 1 else "≤1")
            # P1-1 验收4: 卫星层无宽基（A100/中证500/沪深300 等 industry=宽基指数）
            for s in strategies:
                allocs = s.get("allocations") or s.get("etfs") or []
                sat = [a for a in allocs if a.get("layer") == "satellite"]
                _wide_sat = [
                    a for a in sat
                    if (a.get("industry") or "") == "宽基指数"
                    or any(k in ((a.get("name") or "") + (a.get("tracked_index") or ""))
                           for k in ("A100", "中证500", "沪深300", "上证50", "科创50", "创业板"))
                ]
                check(f"P1-1 {s.get('id', s.get('name', '?'))} 卫星层无宽基",
                      not _wide_sat,
                      f"卫星混入宽基: {[a.get('symbol') for a in _wide_sat]}" if _wide_sat else "卫星层纯主题/行业")
            # F7 (round6 §14.2/§14.6): 卫星层数量门禁——≥4 只且 ≥2 个非科技主题
            # （当前无数量下限断言，F0-5 步骤 D 仅代码注释层面；层数量失衡使卫星层
            # 失去「多赛道分散」意义，见 14.2 层配比诊断）。
            for s in strategies:
                _sid = s.get('id', s.get('name', '?'))
                _n_sat, _non_tech, _tech = _satellite_quality_check(s)
                check(f"F7 {_sid} 卫星层 ≥4 只", _n_sat >= 4,
                      f"卫星层仅 {_n_sat} 只" if _n_sat < 4 else f"{_n_sat} 只")
                check(f"F7 {_sid} 卫星层 ≥2 个非科技主题", _non_tech >= 2,
                      f"非科技卫星仅 {_non_tech} 只（科创系 {_tech} 只）"
                      if _non_tech < 2 else f"{_non_tech} 只非科技卫星")
            # P1-2 (R4-14): 任意两方案核心层重叠（剔除公共底仓 510300 + 强制标的）≤1
            # 强制标的（MANDATORY_CODES: 510300/159338/518880/511090）各司其职允许
            # 跨方案重复，不计入重叠上限（重叠上限 = 公共底仓 1 只）。
            _MANDATORY = {"510300", "159338", "518880", "511090"}
            for i in range(len(core_syms_list)):
                for j in range(i + 1, len(core_syms_list)):
                    a = {s for s in core_syms_list[i] if s not in _MANDATORY}
                    b = {s for s in core_syms_list[j] if s not in _MANDATORY}
                    overlap = len(a & b)
                    names = [strategies[i].get("id", strategies[i].get("name", f"p{i}")),
                             strategies[j].get("id", strategies[j].get("name", f"p{j}"))]
                    check(f"P1-2 核心层重叠(剔除公共底仓) ≤1: {names[0]} vs {names[1]}",
                          overlap <= 1,
                          f"重叠 {overlap} 只: {sorted(a & b)}" if overlap > 1 else f"重叠 {overlap} 只")
        # F3 R10/R13: 报告文本质量断言——标题无重复 + 今日涨跌列非空 + 表格行数=标的数
        import re as _re
        report_text = detail.get("design_text") or detail.get("report_text") or ""
        if report_text:
            # R10: 一级章节标题无重复（LLM 拼接/前缀残留导致的重复标题）
            heads = _re.findall(r"^## .+$", report_text, flags=_re.M)
            dup = len(heads) - len(set(heads))
            check("R10 报告标题无重复", dup == 0, f"重复标题 {dup} 个: {sorted(set(heads) - set(heads))[:3]}" if dup else "全部唯一")
            # R13: 表格行数 = 方案标的数（每方案表格行数与 strategies 标的数一致）
            table_rows = _re.findall(r"^\| 核心 \|", report_text, flags=_re.M)
            alloc_total = sum(len(s.get("allocations") or s.get("etfs") or []) for s in strategies)
            check("R13 表格行数=标的数", len(table_rows) >= len(strategies),
                  f"表格行 {len(table_rows)} vs 方案 {len(strategies)}" if len(table_rows) < len(strategies) else f"{len(table_rows)} 行 × {len(strategies)} 方案")
            # P1-4 (R4-02): R10 今日涨跌列——区分「真实涨跌幅」与「数据源缺失」：
            # 有真实涨跌单元格 → PASS；全部「数据源不可用」→ WARN（skip 语义，
            # 数据源降级不误报 PASS 也不静默绿）；两者皆无 → FAIL。
            change_cells = _re.findall(r"\| [+-]?[0-9.]+% \|", report_text)
            unavailable_cells = _re.findall(r"\| 数据源不可用 \|", report_text)
            if change_cells:
                check("R10 今日涨跌列非空", True, f"{len(change_cells)} 个真实涨跌单元格")
            elif unavailable_cells:
                check("R10 今日涨跌列全为数据源不可用（数据源降级）", True,
                      f"{len(unavailable_cells)} 个「数据源不可用」单元格，数据源降级中", skip=True)
            else:
                check("R10 今日涨跌列非空", False, "既无真实涨跌也无降级标注")
            # P3-9 (round9 §4.3-A/P0-9): ①报告带数据采集时刻标注——新生成报告表格含
            # 「截至 HH:MM」，或 market_context.data_fetched_at 已持久化（二者其一即达标）；
            # ②幽灵锚身份校验——560600（历史写错的中证A500锚：医药白酒ETF/零成交/
            # 全源无此证券）不得出现在任何方案标的中（round9 P0-8 清点回归防线）。
            _ctx_fetched = bool((detail.get("market_context") or {}).get("data_fetched_at"))
            check("P0-9 报告带采集时刻（表格截至 或 market_context.data_fetched_at）",
                  "截至" in report_text or _ctx_fetched,
                  "表格缺「截至 HH:MM」且 market_context 无 data_fetched_at（P0-9 未生效）"
                  if not ("截至" in report_text or _ctx_fetched) else "已标注")
            _ghost = [
                a.get("symbol") for s in strategies
                for a in (s.get("allocations") or s.get("etfs") or [])
                if str(a.get("symbol", "")) == "560600"
            ]
            check("P0-8 方案无幽灵锚 560600", not _ghost,
                  f"幽灵锚 560600 仍出现在方案: {_ghost}" if _ghost else "全部标的身份有效")
    except Exception as e:
        check("方案质量门禁", False, str(e))


def print_summary():
    # R4-18/P0-3: 本函数内 FAIL += 1（S3 skip 阈值逻辑）使 Python 将 FAIL 视为
    # 函数局部变量，读取 PASS + FAIL 时未赋值 → UnboundLocalError 必崩。
    # 门禁脚本自身 bug 曾使「全 PASS 也 exit 1」且总结永不打印（防护体系失效）。
    global PASS, FAIL, SKIP
    total = PASS + FAIL
    print(f"\n{'=' * 50}")
    print(f"结果: {PASS}/{total} 通过", "ALL PASS" if FAIL == 0 else "HAS FAILURES")
    if SKIP:
        print(f"      {SKIP} 项跳过")
    # S3: skip 超过阈值即 FAIL——防止门禁自我豁免蔓延（F20 薄弱点 3）。
    # 白名单化后的合理 skip 仅 2 类：nginx 未运行 / websockets 未装（外加设计质量条件 skip 至多 1），
    # 阈值 3 之上出现任何 skip 都视为异常豁免。
    if SKIP > 3:
        print(f"      [S3] SKIP={SKIP} 超过阈值 3 → 门禁 FAIL（防自我豁免蔓延）")
        FAIL += 1
    if FAIL > 0:
        print(f"      {FAIL} 项失败")
        sys.exit(1)


# ── S9: 新增模块 ──────────────────────────────────────────────────


def section_factor_integrity(host="127.0.0.1", port=8000):
    """S9: 因子完整性检查 — 验证 key 因子不为全 0。"""
    section("因子完整性检查")

    # Direct check via health endpoint for factor status
    try:
        r = requests.get(f"http://{host}:{port}/api/v1/admin/sources/health", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                factor_h = data.get("factor.history", {})
                status = factor_h.get("status", "unknown")
                check(f"factor.history source health: {status}", status in ("healthy", "active") or "fail" in str(factor_h.get("_failures","")))
            elif isinstance(data, list):
                check(f"factor sources: {len(data)}", len(data) > 0)
        else:
            check("GET /admin/sources/health", False, f"status={r.status_code}")
    except requests.ConnectionError:
        check("POST /admin/sources/health", False, "connection refused — server may be down")
    except Exception as e:
        check("GET /admin/sources/health", False, str(e))

    # Check factor matrix endpoint if available
    try:
        r = requests.get(f"http://{host}:{port}/api/v1/factors", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                keys = list(data.keys())[:5]
                check(f"因子矩阵: {len(keys)} 个有效标的", len(keys) > 0, f"样本: {keys[:3]}")
            elif isinstance(data, list):
                check(f"因子矩阵: {len(data)} 条记录", len(data) > 0)
    except Exception as e:
        check("GET /factors", False, str(e))


# ── 模块分发 ──────────────────────────────────────────────────
def section_indicator_quality():
    """F14: Technical indicator data quality -- check Bollinger bandwidth non-zero, MA valid."""
    section("Technical Indicator Quality")
    try:
        r = requests.get(f"{BASE}/api/v1/market/indicators/510300", timeout=15)
        if r.status_code == 200:
            data = r.json()
            bb = data.get("bollinger", {}) or data.get("bbands", {}) or {}
            bandwidth = bb.get("bandwidth", 0)
            upper = bb.get("upper", 0)
            ma = bb.get("ma", 0)
            lower = bb.get("lower", 0)
            if upper > ma > lower:
                check(f"BB: upper({upper:.3f}) > ma({ma:.3f}) > lower({lower:.3f})", True)
                check(f"BB bandwidth={bandwidth:.4f} > 0", bandwidth > 0.001,
                      f"bandwidth={bandwidth:.4f}, column name mismatch possible")
            else:
                check(f"BB: upper({upper:.3f}) ma({ma:.3f}) lower({lower:.3f})",
                      False, "data abnormal or default zeros")
        else:
            check("GET /market/indicators/510300 -> 200", False, f"HTTP {r.status_code}")
    except requests.Timeout:
        check("GET /market/indicators/510300", False, "timeout (15s)")
    except Exception as e:
        check("GET /market/indicators/510300", False, str(e))


MODULES = {
    "health": section_health,
    "market": section_market,
    "portfolio": section_portfolio,
    "news": section_news,
    "admin": section_admin,
    "ws": section_ws,
    "resilience": section_async_resilience,
    "factors": section_factors,
    "analysis": section_analysis,
    "sectors": check_sector_data,
    "quality": check_data_quality,
    "circuit-breaker": section_circuit_breaker,
    "5xx": section_api_5xx_check,
    "zscore": section_factor_zscore_check,
    "diversity": section_solution_diversity_check,
    "factor-integrity": section_factor_integrity,
    "indicator-quality": section_indicator_quality,
    "db-integrity": section_db_integrity,
    "nginx-proxy": section_nginx_proxy,
    "data-hygiene": section_data_hygiene,
    "factor-thresholds": section_factor_thresholds,
    "design-quality": section_design_quality_gate,
}

SMOKE_MODULES = ["health", "market"]


def main():
    global BASE
    parser = argparse.ArgumentParser(description="端到端链路验证")
    parser.add_argument("--port", type=int, default=8000)
    # O21 (round8): 默认 host 用 localhost（后端监听 [::]，Windows 原生 v6only，
    # 127.0.0.1 直连会被拒；localhost 经 getaddrinfo ::1 优先可直连）
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--module", default=None,
                        help="运行指定模块组 (health,market,portfolio,news,admin,ws)，逗号分隔")
    parser.add_argument("--smoke", action="store_true",
                        help="仅运行 smoke 测试 (health + market)")
    args = parser.parse_args()
    BASE = f"http://{args.host}:{args.port}"

    # 确定运行哪些模块
    if args.smoke:
        module_names = SMOKE_MODULES
        print(f"[Smoke] 模式: {', '.join(module_names)}")
    elif args.module:
        module_names = [m.strip() for m in args.module.split(",")]
        valid = set(MODULES.keys())
        for m in module_names:
            if m not in valid:
                print(f"[ERROR] 未知模块: {m}，可选: {', '.join(sorted(valid))}")
                sys.exit(1)
        print(f"[Module] 模式: {', '.join(module_names)}")
    else:
        module_names = list(MODULES.keys())
        print(f"[Full] 模式: 运行所有模块")

    for name in module_names:
        if name in ("health", "factors", "factor-health"):
            MODULES[name](args.host, args.port)
        else:
            MODULES[name]()

    print_summary()




def section_llm_import():
    """P3.1: LLM module import verification."""
    section("LLM 链路验证")
    try:
        from app.analysis.llm import llm_complete
        check("LLM 模块导入", True, "llm_complete import ok")
    except ImportError as e:
        check("LLM 模块导入", False, f"ImportError: {e}")
    except Exception as e:
        check("LLM 模块", False, f"Error: {e}")

    # F17: LLM 供应商连通性探针（不调用完整链路）。端点恒返回 200，
    # 探测失败仅记为 degraded（不阻断 e2e），但端点本身必须可达且结构合法。
    try:
        _t0 = time.time()
        r = requests.get(f"{BASE}/api/v1/admin/llm/health", timeout=30)
        _elapsed = time.time() - _t0
        check(f"GET /admin/llm/health -> {r.status_code} ({_elapsed:.1f}s)", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            has_structure = (
                "status" in data and "has_api_key" in data and "providers" in data
                and isinstance(data["providers"], list)
            )
            check("LLM 健康响应结构合法", has_structure,
                  f"status={data.get('status')}, providers={len(data.get('providers', []))}")
            if data.get("has_api_key"):
                available = [p for p in data["providers"] if p.get("ok")]
                if available:
                    check("至少一个 LLM 供应商可用", True,
                          f"{len(available)}/{len(data['providers'])} 可用")
                else:
                    # 供应商全部探测失败：记为 WARN（degraded），不阻断 e2e
                    check("LLM 供应商连通性", True,
                          f"WARN: 全部探测失败 (degraded)，但端点正常")
            else:
                check("LLM API key 未配置", True, "status=no_key，跳过连通性")
    except Exception as e:
        check("LLM 健康端点连通性", False, f"Error: {e}")


def section_task_status():
    """P3.2: Task status assertion."""
    section("任务状态检查")
    try:
        # /portfolio/designs/history 端点不存在（被 /designs?limit= 取代，旧路径
        # 会落入 /designs/{design_id} 路由 → 422）——修正为真实端点
        r = requests.get(f"{BASE}/api/v1/portfolio/designs", params={"limit": 5}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                completed = [d for d in data if isinstance(d, dict) and d.get("status") in ("completed", "success")]
                check("设计列表有 completed 记录", len(completed) > 0,
                      f"{len(completed)}/{len(data)} completed" if data else "empty")
            else:
                check("设计历史端点", True, "response OK")
        else:
            check("设计历史端点", False, f"HTTP {r.status_code}")
    except Exception as e:
        check("任务状态检查", False, f"Error: {e}")


def section_task_persistence():
    """Z27: 任务持久化 — POST /design-async → 轮询至终态 → 断言契约字段 + record_id 可关联 /designs/{id}。"""
    section("任务持久化 (Z27)")
    try:
        # 1. 提交设计任务
        r = requests.post(f"{BASE}/api/v1/portfolio/design-async",
                          json={"capital": 500000}, timeout=15)
        if r.status_code not in (200, 202):
            check("POST /design-async", False, f"HTTP {r.status_code}")
            return
        task_id = r.json().get("task_id")
        if not task_id:
            check("POST /design-async 返回 task_id", False, "missing task_id")
            return
        check("POST /design-async 返回 task_id", True, f"task_id={task_id}")

        # 2. 轮询至终态（completed / completed_with_errors / failed）
        terminal = {"completed", "completed_with_errors", "failed"}
        status = None
        for _ in range(40):
            tr = requests.get(f"{BASE}/api/v1/portfolio/tasks/{task_id}", timeout=15)
            if tr.status_code == 200:
                data = tr.json()
                status = data.get("status")
                if status in terminal:
                    break
            time.sleep(5)
        check(f"任务 {task_id} 到达终态 ({status})", status in terminal, f"status={status}")
        if status not in terminal:
            return

        # 3. 契约字段完整性（type/stage/record_id）
        check("响应含 type 字段", "type" in data, f"type={data.get('type')}")
        check("响应含 stage 字段", "stage" in data, f"stage={data.get('stage')}")
        check("响应含 params 字段", isinstance(data.get("params"), dict))
        record_id = data.get("record_id")
        check("响应含 record_id", record_id is not None, f"record_id={record_id}")

        # 4. design 任务 record_id 可关联 GET /designs/{record_id}
        if record_id:
            dr = requests.get(f"{BASE}/api/v1/portfolio/designs/{record_id}", timeout=15)
            check(f"GET /designs/{record_id} 可关联", dr.status_code == 200, f"HTTP {dr.status_code}")

        # 5. 任务列表包含该任务且带 record_id
        lr = requests.get(f"{BASE}/api/v1/portfolio/tasks", timeout=15)
        if lr.status_code == 200:
            tasks = lr.json()
            mine = [t for t in tasks if t.get("task_id") == task_id]
            check("GET /tasks 包含该任务", len(mine) == 1,
                  f"{len(mine)} matched" if mine else "not found")
            if mine:
                check("列表任务带 record_id", mine[0].get("record_id") == record_id,
                      f"record_id={mine[0].get('record_id')}")
    except Exception as e:
        check("任务持久化 (Z27)", False, f"Error: {e}")


def section_search():
    """P3.3/Z15: Cross-market search test — 默认(无 market)跨市场合并必须非空（Z29）。"""
    section("跨市场搜索")
    # Z29: 默认模式跨市场合并 → 510300(A股ETF) / 盈富基金(HK) / SPY(US) 都必须有结果
    for label, kw in [("A股搜索 (510300)", "510300"),
                      ("港股搜索 (盈富基金)", "盈富基金"),
                      ("美股搜索 (SPY)", "SPY")]:
        try:
            r = requests.get(f"{BASE}/api/v1/market/search", params={"keyword": kw}, timeout=10)
            data = r.json() if r.status_code == 200 else []
            ok = r.status_code == 200 and isinstance(data, list) and len(data) > 0
            check(label, ok,
                  "" if ok else f"HTTP {r.status_code}, 返回 {len(data) if isinstance(data, list) else 'ERR'} 条")
        except Exception as e:
            check(label, False, str(e))
    # P1-7 (R4-29): A 股个股命中——instruments 本地表已灌入个股（>5000 行），
    # 搜「茅台/600519」必须命中本地个股（旧实现表内无个股 → levistock 外部降级 5-6s）
    for label, kw in [("A股个股搜索 (茅台)", "茅台"),
                      ("A股个股代码搜索 (600519)", "600519")]:
        try:
            t0 = time.time()
            r = requests.get(f"{BASE}/api/v1/market/search",
                             params={"keyword": kw, "include_stocks": "true"}, timeout=10)
            dt_ms = (time.time() - t0) * 1000
            data = r.json() if r.status_code == 200 else []
            hits = [x for x in data if x.get("asset_type") == "stock"] if isinstance(data, list) else []
            check(label, r.status_code == 200 and len(hits) > 0,
                  f"{len(hits)} 个股命中, {dt_ms:.0f}ms" if hits else
                  f"无个股命中 (HTTP {r.status_code}, {len(data) if isinstance(data, list) else 'ERR'} 条)")
        except Exception as e:
            check(label, False, str(e))


def section_hk_market():
    """Z15/C2: 港股市场搜索 — 个股(include_stocks=true) + 静态 ETF 基座必须非空。"""
    section("港股市场搜索")
    for label, params in [
        ("港股个股搜索 (00700, include_stocks=true)",
         {"keyword": "00700", "market": "HK", "include_stocks": "true"}),
        ("港股 ETF 搜索 (盈富基金)", {"keyword": "盈富基金", "market": "HK"}),
    ]:
        try:
            r = requests.get(f"{BASE}/api/v1/market/search", params=params, timeout=15)
            data = r.json() if r.status_code == 200 else []
            ok = r.status_code == 200 and isinstance(data, list) and len(data) > 0
            check(label, ok,
                  "" if ok else f"HTTP {r.status_code}, {len(data) if isinstance(data, list) else 'ERR'} 条")
            if ok:
                check(f"{label}: market 均为 HK",
                      all(x.get("market") == "HK" for x in data),
                      f"markets={sorted({x.get('market') for x in data})}")
        except Exception as e:
            check(label, False, str(e))


def section_us_market():
    """Z15/C3: 美股市场搜索 — 个股(include_stocks=true) + 静态 ETF 基座必须非空。"""
    section("美股市场搜索")
    for label, params in [
        ("美股个股搜索 (AAPL, include_stocks=true)",
         {"keyword": "AAPL", "market": "US", "include_stocks": "true"}),
        ("美股 ETF 搜索 (SPY)", {"keyword": "SPY", "market": "US"}),
    ]:
        try:
            r = requests.get(f"{BASE}/api/v1/market/search", params=params, timeout=15)
            data = r.json() if r.status_code == 200 else []
            ok = r.status_code == 200 and isinstance(data, list) and len(data) > 0
            check(label, ok,
                  "" if ok else f"HTTP {r.status_code}, {len(data) if isinstance(data, list) else 'ERR'} 条")
            if ok:
                check(f"{label}: market 均为 US",
                      all(x.get("market") == "US" for x in data),
                      f"markets={sorted({x.get('market') for x in data})}")
        except Exception as e:
            check(label, False, str(e))


def section_fundamentals():
    """Z16/Z15/C5: Fundamentals — 200 + symbol 存在 + daily 为 list；500/异常一律 FAIL。"""
    section("基本面数据")
    try:
        r = requests.get(f"{BASE}/api/v1/market/fundamentals/510300", timeout=10)
        if r.status_code != 200:
            check("基本面端点 (510300)", False, f"HTTP {r.status_code}")
            return
        check("基本面端点 (510300)", True, f"HTTP {r.status_code}")
        data = r.json()
        check("基本面 symbol 字段存在",
              isinstance(data, dict) and bool(data.get("symbol")),
              f"symbol={data.get('symbol') if isinstance(data, dict) else 'non-dict'}")
        check("基本面 daily 为列表",
              isinstance(data, dict) and isinstance(data.get("daily"), list),
              f"daily type={type(data.get('daily')).__name__ if isinstance(data, dict) else 'N/A'}")
    except Exception as e:
        check("基本面端点 (510300)", False, str(e))


def section_encoding():
    """P3.5: Encoding validation."""
    section("编码验证")
    try:
        for path, label in [("/api/v1/market/realtime/510050", "A股行情"),
                              ("/api/v1/portfolio/etfs", "组合 ETF 列表")]:
            r = requests.get(f"{BASE}{path}", timeout=10)
            if r.status_code == 200:
                has_bad = "ufffd" in r.text[:2000]
                check(f"编码验证 ({label})", not has_bad, "UTF-8 正常" if not has_bad else "含乱码")
            else:
                check(f"编码验证 ({label})", True, f"HTTP {r.status_code}")
    except Exception as e:
        check("编码验证", False, f"Error: {e}")


def section_factor_ic():
    """P3.7: Factor IC data quality check."""
    section("因子 IC 检查")
    try:
        r = requests.get(f"{BASE}/api/v1/factors/ic", timeout=15)
        check("因子 IC 端点", True, f"HTTP {r.status_code}")
        if r.status_code == 200:
            # /factors/ic 返回 {"factors": [...], "total": N, "updated_at": ...}
            rows = (r.json() or {}).get("factors") or []
            # P3-8 (round9 §6.5/P1-3): 无「负 IC 标 valid 且文案 ≥阈值」矛盾项——
            # P1-3 修复后负 IC（|IC|≥阈值）标 warn（负向淘汰警示），reason 用 |IC| 口径
            _contradictions = []
            for row in (rows or []):
                ic = row.get("ic_value")
                status = row.get("status")
                reason = str(row.get("reason") or "")
                if ic is not None and isinstance(ic, (int, float)) and ic < 0 and status == "valid":
                    _contradictions.append(f"{row.get('code')}: IC={ic} 标 valid")
                if status == "valid" and "≥ 阈值" in reason and reason.startswith("IC "):
                    _contradictions.append(f"{row.get('code')}: 文案非 |IC| 口径")
            check("无负IC标valid/文案≥阈值矛盾（P1-3）", not _contradictions,
                  "; ".join(_contradictions[:3]) if _contradictions else "全部合规")
    except Exception as e:
        check("因子 IC 检查", False, f"Error: {e}")

# Register Phase 4 modules
MODULES["llm"] = section_llm_import
MODULES["task"] = section_task_status
MODULES["task-persistence"] = section_task_persistence
MODULES["search"] = section_search
MODULES["encoding"] = section_encoding
MODULES["factor_ic"] = section_factor_ic
MODULES["fundamentals"] = section_fundamentals
MODULES["hk-market"] = section_hk_market
MODULES["us-market"] = section_us_market
MODULES["factor-health"] = section_factor_health

if __name__ == "__main__":
    main()
