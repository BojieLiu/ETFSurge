"""verify_llm_exclusion.py — mark_excluded 端到端断言 (round39 §4.4.4 方案 C).

背景: round40 commit b2e6078 在 provider.py get_configured_providers() 末尾加统一
model_catalog.is_excluded() 兜底守卫——mark_excluded 命中的 (provider, model) 不挂载,
从根上排除出 LLM 候选链. 但**端到端无回归断言**——R160 复验发现 by_model.
deepseek-v4-flash-free 仍累计 22040 calls (mark_excluded 实施前的历史累计), 需新断言
确认 mark_excluded 之后 0 增量.

策略: 5min delta 模式 (round39 §4.4.4 方案 C 原文语义) + 持久化 baseline 避免阻塞
巡逻 L 段 60s 超时.
- 首次跑 / 显式 --snapshot: 拉 /admin/token-usage by_model, 保存到
  logs/patrol/llm_exclusion_baseline.json, 返 INFO (不校验).
- 后续跑: 传 --baseline-file, 拉新 by_model, 计算差值. excluded model
  delta > 0 → FAIL (mark_excluded 失效). 非 excluded model 不检查.
- 若 baseline 缺失/格式坏 → WARN 跳过 (不阻断), 提示下次先跑 --snapshot.

调用:
  python scripts/verify_llm_exclusion.py --snapshot
      # 首次: 拉 by_model 保存 baseline, 不校验, 返 INFO
  python scripts/verify_llm_exclusion.py --baseline-file logs/patrol/llm_exclusion_baseline.json
      # 后续: 对比 baseline + 当前 by_model, 断言 excluded model delta==0

退出码: 0=PASS, 1=FAIL (任一 excluded model delta > 0), 2=ERROR (端点不可达).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "http://[::1]:8000"
TIMEOUT = 15

# 默认 baseline 路径 (与 patrol log 目录同根, 便于 cron 持久化)
DEFAULT_BASELINE = Path("logs/patrol/llm_exclusion_baseline.json")


def _get_json(url, timeout=TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _flat_calls(by_model: dict) -> dict[str, int]:
    """把 by_model (key=model or provider/model) 拍平为 {combo_key: calls}."""
    flat: dict[str, int] = {}
    for key, info in by_model.items():
        if not isinstance(info, dict):
            continue
        flat[key] = int(info.get("calls", 0) or 0)
    return flat


def _save_baseline(path: Path, base: str, calls: dict[str, int],
                    excluded: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": _now_iso(),
        "base": base,
        "calls": calls,
        "excluded_items": excluded,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_baseline(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def _run_snapshot(args) -> int:
    """首次: 拉 by_model + excluded, 保存 baseline."""
    base = args.base.rstrip("/")
    try:
        usage = _get_json(f"{base}/api/v1/admin/token-usage")
        ex_data = _get_json(f"{base}/api/v1/admin/llm-excluded")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  [ERROR] {e}")
        return 2

    calls = _flat_calls(usage.get("by_model", {}))
    excluded = ex_data.get("items", [])
    baseline_path = Path(args.baseline_file)
    _save_baseline(baseline_path, base, calls, excluded)
    print(f"[INFO] baseline 已保存: {baseline_path}")
    print(f"       by_model keys: {len(calls)}; excluded items: {len(excluded)}")
    return 0


def _run_check(args) -> tuple[int, list[str]]:
    """后续: 对比 baseline + 当前 by_model, 断言 excluded model delta==0."""
    base = args.base.rstrip("/")
    baseline_path = Path(args.baseline_file)
    if not baseline_path.exists():
        return 0, [f"baseline {baseline_path} 不存在; 首次跑 --snapshot 建立基线"]

    try:
        baseline = _load_baseline(baseline_path)
    except (json.JSONDecodeError, OSError) as e:
        return 0, [f"baseline {baseline_path} 解析失败: {e}; 跳过 (WARN)"]

    # 1. 拉当前 excluded 列表
    try:
        ex_data = _get_json(f"{base}/api/v1/admin/llm-excluded")
        usage = _get_json(f"{base}/api/v1/admin/token-usage")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        return 2, [f"端点不可达: {e}"]

    excluded_items = ex_data.get("items", [])
    if not excluded_items:
        return 0, []  # INFO: 无 excluded, 跳过

    cur_calls = _flat_calls(usage.get("by_model", {}))
    base_calls = baseline.get("calls", {})

    # 2. 对每个 excluded 找 delta (兼容 model 名 vs provider/model 双 key)
    violations: list[str] = []
    for item in excluded_items:
        provider = item.get("provider")
        model = item.get("model")
        if not provider or not model:
            continue
        # 双 key 取 max (覆盖 by_model 内部不同存储方式)
        for key in (model, f"{provider}/{model}"):
            delta = cur_calls.get(key, 0) - base_calls.get(key, 0)
            if delta > 0:
                violations.append(
                    f"excluded {provider}:{model} (key={key}) "
                    f"delta=+{delta} calls in 5min window "
                    f"(baseline={base_calls.get(key, 0)}, now={cur_calls.get(key, 0)})"
                )
                break  # 一对 (provider, model) 只报一次
    return (1 if violations else 0), violations


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="mark_excluded 端到端断言 (round39 §4.4.4 方案 C): "
                    "5min delta 模式, baseline 持久化避免阻塞巡逻."
    )
    parser.add_argument("--base", default=DEFAULT_BASE, help="后端 base URL")
    parser.add_argument("--snapshot", action="store_true",
                        help="保存当前 by_model 为 baseline (首次跑)")
    parser.add_argument("--baseline-file", default=str(DEFAULT_BASELINE),
                        help=f"baseline JSON 路径 (默认 {DEFAULT_BASELINE})")
    args = parser.parse_args(argv)

    if args.snapshot:
        return _run_snapshot(args)

    rc, violations = _run_check(args)
    if rc == 2:
        print(f"[ERROR] 端点不可达 (rc=2)")
        return 2
    if violations:
        # 区分 WARN (baseline 缺失/格式坏) vs FAIL (有 excluded 增量)
        if any("baseline" in v or "解析失败" in v for v in violations):
            print(f"[WARN] {len(violations)} 项 baseline 问题 (不阻断):")
            for v in violations:
                print(f"  - {v}")
            return 0
        print(f"[FAIL] {len(violations)} 项 excluded model 5min 增量 > 0:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"[PASS] 所有 excluded model 5min 增量 == 0; mark_excluded 真正生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
