"""R143 长尾: LLM 熔断状态 review 脚本。

读 gates.py 三个模块级 dict (进程内运行时状态) + 按 provider 聚合:
- _circuit: {key: {state, fail_count, opened_at, is_quota}}  熔断器
- _exclusions: {key: 永久 (无 opened_at)}                  catalog 黑名单
- _long_cooldown: {key: ttl_until}                      长冷却

设计目的:
- 运维 review 工具: 列出当前被熔断/排除/冷却的 model + 持续时长
- 不持久化 (进程内 dict): 每次跑只反映当前进程状态. 后端重启清零
- 决策依据:
  - _exclusions 永久不删 → 模型 6h 后 long_cooldown 失效但 mark_excluded 仍生效
    → 需手动 clear_excluded(provider, model) 才能复活
  - _circuit OPEN 状态 → 真实运行中熔断
  - _long_cooldown → 6h TTL 期内模型被永久错误命中

输出: markdown 表 (provider, key, state/ttl, time_since_open/ttl_remaining) + 决策建议
"""
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import sys

# 注入 backend 路径以便 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser(description="R143 LLM 熔断/排除/长冷却状态 review")
    ap.add_argument("--json", action="store_true", help="JSON 输出 (代替 markdown)")
    args = ap.parse_args()

    # 1) 读三个模块级 dict (延迟 import 避免冷启动开销)
    from app.analysis.llm import gates
    from app.analysis.llm import model_catalog

    now = time.monotonic()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    # 2) 聚合
    by_provider: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for key, entry in gates._circuit.items():
        prov = key.split(":", 1)[0] if ":" in key else key
        opened_at = entry.get("opened_at", 0.0)
        since = now - opened_at if opened_at > 0 else None
        by_provider[prov]["_circuit"].append({
            "key": key,
            "state": entry.get("state", "?"),
            "fail_count": entry.get("fail_count", 0),
            "is_quota": entry.get("is_quota", False),
            "since_open_s": round(since, 1) if since is not None else None,
        })
    for key in model_catalog.model_catalog._exclusions:
        prov = key.split(":", 1)[0] if ":" in key else key
        by_provider[prov]["_exclusions"].append({"key": key})
    for key, ttl_until in gates._long_cooldown.items():
        prov = key.split(":", 1)[0] if ":" in key else key
        remaining = ttl_until - now
        by_provider[prov]["_long_cooldown"].append({
            "key": key,
            "ttl_remaining_s": round(remaining, 1),
            "ttl_remaining_h": round(remaining / 3600, 2),
        })

    # 3) 输出
    if args.json:
        import json
        payload = {
            "snapshot_at": now_str,
            "providers": {
                p: {k: v for k, v in sections.items()}
                for p, sections in by_provider.items()
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # markdown
    lines: list[str] = []
    lines.append(f"# R143 LLM 熔断状态 review 快照")
    lines.append("")
    lines.append(f"**生成时间**: {now_str}  (本进程内运行时状态, 重启清零)")
    lines.append("")
    if not by_provider:
        lines.append("(空: 无任何 provider 处于熔断/排除/冷却状态)")
        print("\n".join(lines))
        return 0

    # 决策建议聚合
    lines.append("## 决策建议 (按 provider)")
    lines.append("")
    for prov, sections in sorted(by_provider.items()):
        circ = sections.get("_circuit", [])
        excl = sections.get("_exclusions", [])
        long_cd = sections.get("_long_cooldown", [])
        n_circ = len(circ)
        n_excl = len(excl)
        n_long = len(long_cd)
        if n_circ + n_excl + n_long == 0:
            continue
        lines.append(f"### {prov}")
        lines.append(f"- 熔断 (_circuit): {n_circ}")
        lines.append(f"- 排除 (_exclusions 永久): {n_excl}")
        lines.append(f"- 长冷却 (6h TTL): {n_long}")
        # 决策建议
        if n_excl > 0:
            lines.append(
                f"  - ⚠️ _exclusions 永久不删 (process 内存), 即使 long_cooldown 6h 到期也"
                f"不复活. 需手动 `model_catalog.model_catalog._exclusions.discard("
                f"'{{provider}}:{{model}}')` 才能复活."
            )
        if n_long > 0:
            for item in long_cd:
                key = item["key"]
                rem_h = item["ttl_remaining_h"]
                lines.append(f"  - ⏰ {key} 长冷却剩余 {rem_h}h (过期自动 pop)")
        if n_circ > 0:
            for item in circ:
                st = item["state"]
                if st == "OPEN":
                    since = item["since_open_s"] or 0
                    lines.append(
                        f"  - 🔴 {item['key']} OPEN {since:.0f}s "
                        f"(is_quota={item['is_quota']}, TTL 30min quota/5min 5xx)"
                    )
                elif st == "HALF_OPEN":
                    lines.append(
                        f"  - 🟡 {item['key']} HALF_OPEN (允许复探一次, 失败立即回 OPEN)"
                    )
        lines.append("")

    # 详细表
    lines.append("## 详细 (按 provider × 类型)")
    lines.append("")
    for prov, sections in sorted(by_provider.items()):
        for section_name in ("_circuit", "_long_cooldown", "_exclusions"):
            items = sections.get(section_name, [])
            if not items:
                continue
            lines.append(f"### {prov} / {section_name.strip('_')}")
            if section_name == "_circuit":
                lines.append("| key | state | fail_count | is_quota | since_open (s) |")
                lines.append("|---|---|---|---|---|")
                for it in items:
                    lines.append(
                        f"| {it['key']} | {it['state']} | {it['fail_count']} | "
                        f"{it['is_quota']} | {it['since_open_s']} |"
                    )
            elif section_name == "_long_cooldown":
                lines.append("| key | ttl_remaining (s) | ttl_remaining (h) |")
                lines.append("|---|---|---|")
                for it in items:
                    lines.append(
                        f"| {it['key']} | {it['ttl_remaining_s']} | {it['ttl_remaining_h']} |"
                    )
            else:  # _exclusions
                lines.append("| key |")
                lines.append("|---|")
                for it in items:
                    lines.append(f"| {it['key']} |")
            lines.append("")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
