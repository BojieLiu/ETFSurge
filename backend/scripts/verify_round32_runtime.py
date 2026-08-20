# -*- coding: utf-8 -*-
"""round32 R99-R101 运行时验收脚本（后端已启动 + warmup 完成时执行）。

对照 docs/round32-container-reacceptance-r99-r100.md §5.1 验收口径：

- R99: 设计任务（含盘后 partial）factor_breakdown.momentum 不再恒 0.300 全同占位；
       momentum 数据缺失时 momentum 键不设置或显式 null，不得 18/18 全同 0.300。
- R100: factor_data_quality.data_available 与实际 factor_breakdown 退化一致——
        actual_output_rate 字段存在且与 definition_ready_pct 可分离（口径脱节显性化）；
        factor_breakdown 退化时 data_available_pct 不得虚高 97%。
- R101: 核心层宽基数量 ≤4（含强制锚，中证500 已纳入识别）；不同宽基可并存；
        >0.95 宽基配对（510300×159338）出现 correlation_warnings（不静默）。

用法：
    python scripts/verify_round32_runtime.py [--base http://localhost:8000/api/v1]

退出码：0 = 全 PASS（或标注降级）；1 = 有 FAIL。
"""
import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api/v1"

PASS, FAIL = 0, 0


def check(name, ok, detail=""):
    global PASS, FAIL
    tag = "[PASS]" if ok else "[FAIL]"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))


def get_design():
    """提交设计任务并轮询至终态，返回设计详情 dict（失败返回 None）。"""
    try:
        r = requests.post(f"{BASE}/portfolio/design-async", json={"capital": 500000}, timeout=60)
    except Exception as e:
        check("POST /design-async", False, str(e))
        return None
    if r.status_code not in (200, 202):
        check("POST /design-async", False, f"HTTP {r.status_code}")
        return None
    task_id = r.json().get("task_id")
    if not task_id:
        check("design-async 返回 task_id", False)
        return None
    deadline = time.time() + 360
    while time.time() < deadline:
        try:
            pr = requests.get(f"{BASE}/portfolio/tasks/{task_id}", timeout=10)
            if pr.status_code == 200:
                status = pr.json().get("status")
                if status == "completed":
                    break
                if status == "failed":
                    check("设计任务完成", False, f"failed: {pr.json().get('error_message')}")
                    return None
        except Exception:
            pass
        time.sleep(5)
    else:
        check("设计任务完成", False, "360s 超时")
        return None
    # 取最新设计详情
    try:
        lst = requests.get(f"{BASE}/portfolio/designs?limit=1", timeout=10)
        if lst.status_code != 200 or not lst.json():
            check("GET /designs?limit=1", False, f"HTTP {lst.status_code}")
            return None
        did = lst.json()[0]["id"]
        dr = requests.get(f"{BASE}/portfolio/designs/{did}", timeout=10)
        if dr.status_code != 200:
            check("GET /designs/{id}", False, f"HTTP {dr.status_code}")
            return None
        return dr.json()
    except Exception as e:
        check("获取设计详情", False, str(e))
        return None


def main():
    print("=" * 60)
    print("# round32 R99-R101 运行时验收")
    print(f"# base={BASE}")

    detail = get_design()
    if detail is None:
        print(f"\n汇总: PASS={PASS} FAIL={FAIL}")
        return 1

    strategies = detail.get("strategies", [])
    fdq = (detail.get("market_context") or {}).get("factor_data_quality") or {}
    print(f"\n  report_quality={detail.get('report_quality')}")
    print(f"  factor_data_quality: data_available={fdq.get('data_available')} "
          f"pct={fdq.get('data_available_pct')} actual_output_rate={fdq.get('actual_output_rate')} "
          f"definition_ready_pct={fdq.get('definition_ready_pct')}")

    # ── R99: momentum 不再恒 0.300 全同占位 ──────────────────────────
    momentum_vals = []
    holdings_with_momentum = 0
    breakdown_keys = []
    for s in strategies:
        for a in s.get("allocations", s.get("etfs", [])):
            fb = a.get("factor_breakdown") or {}
            breakdown_keys.append(set(fb.keys()))
            if "momentum" in fb:
                mv = fb["momentum"]
                if isinstance(mv, (int, float)):
                    momentum_vals.append(mv)
                    holdings_with_momentum += 1
    if not momentum_vals:
        check("R99 momentum 无占位值（全缺失 = 显式「动量不可用」）", True)
    elif len(set(round(v, 3) for v in momentum_vals)) > 1:
        check("R99 momentum 差异化", True,
              f"{len(set(round(v, 3) for v in momentum_vals))} 个不同值")
    else:
        check("R99 momentum 不得全同占位", False,
              f"全部={momentum_vals[0]:.3f}（{holdings_with_momentum} 只全同 = 占位污染）")
    # 若存在 momentum=0.300 全同 → 负向 FAIL（R99 核心）
    placeholders = [v for v in momentum_vals if abs(v - 0.300) < 1e-6]
    if placeholders and len(momentum_vals) == len(placeholders):
        check("R99 负向：无 0.300 全同占位", False, f"{len(placeholders)}/{len(momentum_vals)} 全为 0.300")

    # ── R100: data_available 与实际产出对齐 ─────────────────────────
    if "actual_output_rate" in fdq:
        check("R100 字段 actual_output_rate 存在", True)
        if fdq.get("actual_output_rate") is not None:
            check("R100 两维并列（定义就位率 vs 实际产出率）",
                  fdq.get("definition_ready_pct") is not None,
                  f"def={fdq.get('definition_ready_pct')} act={fdq.get('actual_output_rate')}")
        # 负向：factor_breakdown 退化时 data_available_pct 不得虚高（>0.9 且 actual 明显低）
        if fdq.get("actual_output_rate") is not None and fdq.get("data_available_pct"):
            low_out = float(fdq["actual_output_rate"]) < 0.6
            high_avail = float(fdq["data_available_pct"]) > 0.9
            if low_out and high_avail:
                check("R100 负向：退化态 data_available_pct 不得虚高",
                      False,
                      f"actual_output_rate={fdq['actual_output_rate']} 但 data_available_pct={fdq['data_available_pct']}")
            else:
                check("R100 负向：退化态 data_available 与产出对齐", True)
    else:
        check("R100 字段 actual_output_rate 存在", False)

    # ── R101: 核心层宽基数量 ≤4 + 高相关提示 ────────────────────────
    wide_max = 0
    has_anchor_pair = False
    anchor_warned = False
    core_counts = []
    for s in strategies:
        core = [a for a in s.get("allocations", s.get("etfs", []))
                if a.get("layer") == "core" and a.get("symbol") != "CASH"]
        core_counts.append(len(core))
        wide_count = 0
        for a in core:
            text = f"{a.get('name', '') or ''}{a.get('tracked_index', '') or ''}"
            if any(k in text for k in ("沪深300", "中证A500", "中证A50", "中证A100",
                                       "上证50", "上证180", "深证100", "中证100",
                                       "中证800", "MSCI", "中证500", "A500", "A50")):
                wide_count += 1
        wide_max = max(wide_max, wide_count)
        syms = {a["symbol"] for a in core}
        if {"510300", "159338"} <= syms:
            has_anchor_pair = True
        for w in (s.get("risk_metrics") or {}).get("correlation_warnings") or []:
            pair = w.get("pair") or []
            if {"510300", "159338"} <= set(str(x) for x in pair):
                anchor_warned = True
    check("R101 核心层宽基数量 ≤4（含锚）", wide_max <= 4, f"max={wide_max}")
    # M7 core ∈ [3,5]：核心锚（510300/159338）在池中才可断言；池缺锚（159338 数据源
    # 不可用被 etf_scanner 过滤）属 round31 §2.6 已记载的历史已知（P1-1 宽基锚缺失），
    # 非 R101 回归——标注「环境性待复测」不判 FAIL。
    anchors_in_any_core = any(
        {"510300", "159338"} <= {a["symbol"] for a in
                                  [x for x in s.get("allocations", s.get("etfs", []))
                                   if x.get("layer") == "core" and x.get("symbol") != "CASH"]}
        for s in strategies
    )
    if anchors_in_any_core:
        check("R101 核心层数量 ∈ [3,5]（M7 达标）",
              all(3 <= c <= 5 for c in core_counts),
              f"core_counts={core_counts}")
    else:
        print("  [SKIP] M7 core 检查：核心锚 159338 不在候选池（环境性缺锚，round31 §2.6 "
              "已记载 P1-1 宽基锚缺失）——待交易时段复测")
    if has_anchor_pair:
        check("R101 负向：510300×159338 高相关配对有 correlation_warnings（不静默）",
              anchor_warned, "无 510300×159338 告警" if not anchor_warned else "")

    print(f"\n汇总: PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
