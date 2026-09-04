"""verify_allocation_invariants.py — 端到端业务不变量校验 (round39 §4.4.4 方案 A).

背景: round38 R140 实施后, round39 容器复验 design 12 balanced sat=0.300 > budget=0.220,
aggressive sat=0.350 > budget=0.300, 总仓位 1.030/1.065 均 > 1.0. R140 修复未生效是因为
apply_risk_controls / _consolidate_minnows / _apply_precision_bucketing 等后续步骤
仍可能把 sat 层 / 总仓位推超 budget. round40 在 strategy_design.py orchestrator 末尾
二次 _enforce_layer_budget_final 兜底 (commit b2e6078), 但**端到端无回归断言**——单测
测 enforce 函数本身, 不测整链路设计输出. 此脚本就是给 R140 兜底补端到端守卫.

校验:
- Σ(layer_weight for etf in etfs if etf.layer==X) ≤ budget[X] + 0.01
- Σ(etf.weight for etf in etfs if etf.symbol != "CASH") ≤ 1.0 + 0.01
- 防御层 cap=0 时跳过该层 (与 _enforce_layer_budget_final 内部 guard 一致)

调用:
  python scripts/verify_allocation_invariants.py             # 默认连 localhost:8000
  python scripts/verify_allocation_invariants.py --limit 5  # 检查最近 5 个 design
  python scripts/verify_allocation_invariants.py --design-id 13  # 检查指定 design

退出码: 0=PASS, 1=FAIL (任一不变量违例), 2=ERROR (后端不可达).
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# round36 §8-C 同款: 端口选择 (v6only 实际只 ::1 可连)
DEFAULT_BASE = "http://[::1]:8000"
# R172 (round52 §4.3 方案C): 容器场景 (0.0.0.0 v4 端口映射 + 宿主代理劫持 [::1] → 502/超时)
# 裸跑挂死; [::1] 探测失败时回落 localhost。显式 --base 不受影响 (patrol.py 传参路径)。
FALLBACK_BASE = "http://localhost:8000"
TIMEOUT = 15
PROBE_TIMEOUT = 3.0
TOLERANCE = 0.01  # 浮点累加容差


def _get_json(url, timeout=TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _probe_health(base: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """探测某 base 的 /health 是否可达（短超时，避免挂死）。"""
    try:
        _get_json(f"{base.rstrip('/')}/health", timeout=timeout)
    except Exception:
        return False
    return True


def _resolve_base(explicit: str | None) -> str:
    """解析后端 base：显式 --base 直接用；否则 [::1] 优先、失败回落 localhost。"""
    if explicit:
        return explicit.rstrip("/")
    if _probe_health(DEFAULT_BASE):
        return DEFAULT_BASE.rstrip("/")
    if _probe_health(FALLBACK_BASE):
        print(f"  [INFO] {DEFAULT_BASE} 不可达，已回退 {FALLBACK_BASE}"
              f"（R172：容器 v4 端口映射 / 宿主代理劫持 [::1] 场景）")
        return FALLBACK_BASE.rstrip("/")
    return DEFAULT_BASE.rstrip("/")


def _check_design(design: dict) -> list[str]:
    """单 design 校验, 返回违例列表 (空=合规)."""
    violations = []
    strategies = design.get("strategies", [])
    for s in strategies:
        sid = s.get("id", "?")
        etfs = s.get("etfs", [])
        layer_budget = s.get("layer_budget", {})

        # per-layer 总权重
        layer_total: dict[str, float] = {}
        non_cash_total = 0.0
        for a in etfs:
            sym = a.get("symbol", "")
            if sym == "CASH":
                continue
            layer = a.get("layer", "satellite")
            w = float(a.get("weight", 0) or 0)
            layer_total[layer] = layer_total.get(layer, 0.0) + w
            non_cash_total += w

        # per-layer 校验
        for layer, total in layer_total.items():
            budget = float(layer_budget.get(layer, 0) or 0)
            if budget <= 0:
                # 防御层 cap=0 时 _enforce_layer_budget_final 跳过, 不算违例
                continue
            if total > budget + TOLERANCE:
                violations.append(
                    f"design {design.get('id')} {sid} layer={layer} "
                    f"Σ={total:.4f} > budget={budget:.4f} (tol={TOLERANCE})"
                )

        # 总仓位校验 (仅 non_cash)
        if non_cash_total > 1.0 + TOLERANCE:
            violations.append(
                f"design {design.get('id')} {sid} "
                f"Σnon_cash={non_cash_total:.4f} > 1.0 (tol={TOLERANCE})"
            )

        # round51 方案 A (R162/R163): 一致性/完整性断言——R140 enforce 缩放后
        # cash 行不回补 (R162 悬空) / target_amount 未随缩放重算 (R163 脱节)
        # 都是「上限方向」断言抓不到的形态 (design15 balanced total=0.95 实证)。
        capital = float(s.get("capital", 0) or 0)
        cash_rows = [a for a in etfs if a.get("symbol") == "CASH"]
        if cash_rows:
            cash_w = float(cash_rows[0].get("weight", 0) or 0)
            expected_cash = 1.0 - non_cash_total
            # ① cash 一致性: |cash_row − (1−Σnon_cash)| ≤ 0.005 (R162)
            if abs(cash_w - expected_cash) > 0.005:
                violations.append(
                    f"design {design.get('id')} {sid} "
                    f"cash={cash_w:.4f} != 1−Σnon_cash={expected_cash:.4f} "
                    f"(gap={abs(cash_w - expected_cash):.4f}, tol=0.005)"
                )
            # ③ Σtotal(含 cash) ≤ 1.0 + tol (R162 另一侧: cash 不允许溢出)
            if non_cash_total + cash_w > 1.0 + TOLERANCE:
                violations.append(
                    f"design {design.get('id')} {sid} "
                    f"Σtotal={non_cash_total + cash_w:.4f} > 1.0 (tol={TOLERANCE})"
                )
        # ② target_amount 同步: |target_amount − capital×weight| ≤ 1 (R163)
        if capital > 0:
            for a in etfs:
                w = a.get("weight", 0)
                ta = a.get("target_amount")
                if ta is None or not isinstance(w, (int, float)):
                    continue
                if abs(float(ta) - capital * float(w)) > 1.0:
                    violations.append(
                        f"design {design.get('id')} {sid}/{a.get('symbol')} "
                        f"target_amount={float(ta):.0f} != capital×weight="
                        f"{capital * float(w):.0f} (weight={float(w):.4f})"
                    )

    return violations


def _run(args) -> int:
    base = args.base.rstrip("/")
    if args.design_id is not None:
        # 单 design 模式
        url = f"{base}/api/v1/portfolio/designs/{args.design_id}"
        try:
            design = _get_json(url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            print(f"  [ERROR] {url}: {e}")
            return 2
        # wrap 成 list 复用 _check_design
        design_wrapped = {"id": args.design_id, "strategies": design.get("strategies", [])}
        all_violations = _check_design(design_wrapped)
        if all_violations:
            print(f"[FAIL] design {args.design_id} 有 {len(all_violations)} 项不变量违例:")
            for v in all_violations:
                print(f"  - {v}")
            return 1
        print(f"[PASS] design {args.design_id} 全部不变量合规")
        return 0

    # 列表模式
    url = f"{base}/api/v1/portfolio/designs?limit={args.limit}"
    try:
        summaries = _get_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  [ERROR] {url}: {e}")
        return 2

    if not summaries:
        print(f"[WARN] designs 列表为空 (limit={args.limit}); 无可校验对象")
        return 0

    all_violations = []
    checked = 0
    for s in summaries:
        design_id = s.get("id")
        if design_id is None:
            continue
        detail_url = f"{base}/api/v1/portfolio/designs/{design_id}"
        try:
            detail = _get_json(detail_url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            print(f"  [WARN] design {design_id} 取详情失败: {e}; 跳过")
            continue
        violations = _check_design(detail)
        checked += 1
        if violations:
            all_violations.extend(violations)

    if all_violations:
        print(f"[FAIL] {checked} designs 中 {len(all_violations)} 项不变量违例:")
        for v in all_violations:
            print(f"  - {v}")
        return 1
    print(f"[PASS] {checked} designs 全部不变量合规 "
          f"(Σlayer ≤ budget+{TOLERANCE} ∧ Σtotal ≤ 1.0+{TOLERANCE})")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="端到端业务不变量校验: 拉 designs 拉 strategies 验 Σlayer ≤ budget + Σtotal ≤ 1.0"
    )
    parser.add_argument("--base", default=None,
                        help=f"后端 base URL（默认先试 {DEFAULT_BASE}，不可达回退 {FALLBACK_BASE}）")
    parser.add_argument("--limit", type=int, default=1, help="检查最近 N 个 design (默认 1: 仅最新 design; 防止历史 design 10-12 的 R140 修复前数据持续 FAIL; 传 --limit 5 看历史)")
    parser.add_argument("--design-id", type=int, default=None,
                        help="检查指定 design_id (单 design 模式, 跳过 --limit)")
    args = parser.parse_args(argv)
    args.base = _resolve_base(args.base)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
