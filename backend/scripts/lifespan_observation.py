"""lifespan 长尾观测脚本 (round44 option C 决策依据).

读 backend/logs/ 已有产物 (r41 探针), 不重启后端.
输出 markdown 报告 + JSON 数据.

观测 4 维度:
  1. warmup_timing.json: lifespan 6 阶段耗时 + 总耗时
  2. warmup_pyinstrument.txt: 主线程栈帧 (哪些函数占了多少 ms)
  3. backend.log 内的 loop_lag 历史 (r41 watchdog 触发记录)
  4. perf_diag_results.json: 49 端点 e2e 实测 (哪些端点慢)

输出:
  - 控制台摘要
  - logs/lifespan_observation_report.md  (markdown 报告)
  - logs/lifespan_observation_data.json   (结构化数据)

用法: cd backend && python -W ignore scripts/lifespan_observation.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 路径
BACKEND_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = BACKEND_ROOT / "logs"


# ─── 1. 读 warmup_timing.json ─────────────────────────────────────────
def read_warmup_timing() -> dict[str, Any]:
    p = LOGS_DIR / "warmup_timing.json"
    if not p.exists():
        return {"available": False, "reason": f"{p} not found"}
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return {"available": True, "data": d}
    except Exception as e:
        return {"available": False, "reason": f"parse error: {e}"}


# ─── 2. 读 warmup_pyinstrument.txt (主线程栈帧) ──────────────────────
_PYINSTRUMENT_FRAME_RE = re.compile(
    r"^\s*([\d.]+)\s+(\S+)\s+(.+?):(\d+)\s*$"
)


def read_pyinstrument_top() -> dict[str, Any]:
    p = LOGS_DIR / "warmup_pyinstrument.txt"
    if not p.exists():
        return {"available": False, "reason": f"{p} not found"}
    # pyinstrument 输出可能含 UTF-8 树形字符, 但每行起首的数字/函数/文件:行
    # 是纯 ASCII. 用 bytes + 正则直接抓这些子串, 绕开 GBK/UTF-8 locale 解析.
    raw = p.read_bytes()
    text_for_header = raw.decode("utf-8", errors="replace")
    header: dict[str, Any] = {}
    m = re.search(r"Recorded:\s*(\S+)\s+Samples:\s*(\d+)", text_for_header)
    if m:
        header["recorded"] = m.group(1)
        header["samples"] = int(m.group(2))
    m = re.search(r"Duration:\s*([\d.]+)", text_for_header)
    if m:
        header["duration_s"] = float(m.group(1))

    # bytes 正则: 行首允许缩进 (\s) + pyinstrument tree char (├/└/─/│ U+2500-251F).
    # 行尾锚定 "文件:行号" 倒推 rest. 树根行 "41.856 MainThread  <thread>:..." 由 HIDE_RE 过滤.
    TREE_CHAR_BYTES = rb"(?:\xe2\x94[\x80-\xbf])"
    LINE_RE = re.compile(
        rb"^(?:\s|" + TREE_CHAR_BYTES + rb")*(?P<dur>[\d.]+)\s+(?P<rest>.+?):(?P<line>\d+)\s*$",
        re.MULTILINE,
    )
    HIDE_RE = re.compile(rb"frames hidden|^\s*\[self\]|<thread>|<string>")
    frames: list[dict[str, Any]] = []
    for m in LINE_RE.finditer(raw):
        if HIDE_RE.search(m.group(0)):
            continue
        if len(frames) >= 30:
            break
        try:
            rest_str = m.group("rest").decode("utf-8", errors="replace").strip()
            # rest 格式: "<function>  <file_path>" (末尾 :<line> 已被 LINE_RE 吃掉)
            # rest 可能含 tree char (├/└/─/│), 已被 LINE_RE 行首吃掉; 此处只留 ASCII 段
            tokens = rest_str.split()
            if len(tokens) >= 2:
                fn_part = tokens[0]
                file_part = tokens[-1]
            elif len(tokens) == 1:
                fn_part = tokens[0]
                file_part = "?"
            else:
                fn_part = "?"
                file_part = "?"
        except Exception:
            continue
        frames.append({
            "duration_s": float(m.group("dur")),
            "function": fn_part,
            "file": file_part,
            "line": int(m.group("line")),
        })
    return {"available": True, "header": header, "top_frames": frames}


# ─── 3. 读 backend.log 内的 loop_lag 触发历史 ─────────────────────────
_LOOP_LAG_RE = re.compile(
    r"event loop lag ([\d.]+)s.*?(\d+) live tasks"
)


def read_loop_lag_history(log_files: list[Path] | None = None) -> dict[str, Any]:
    if log_files is None:
        log_files = sorted(LOGS_DIR.glob("backend.log*"), reverse=True)
    history: list[dict[str, Any]] = []
    for lf in log_files:
        try:
            text = lf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            if "loop_lag" not in line and "event loop lag" not in line:
                continue
            m = _LOOP_LAG_RE.search(line)
            if not m:
                continue
            lag = float(m.group(1))
            live_tasks = int(m.group(2))
            # 抓时间戳 (行首)
            ts = ""
            ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if ts_m:
                ts = ts_m.group(1)
            history.append({
                "timestamp": ts,
                "lag_s": lag,
                "live_tasks": live_tasks,
                "log_file": lf.name,
            })
    history.sort(key=lambda x: x.get("timestamp", ""))
    if not history:
        return {"available": False, "count": 0}
    lags = [h["lag_s"] for h in history]
    return {
        "available": True,
        "count": len(history),
        "max_lag_s": max(lags),
        "mean_lag_s": round(sum(lags) / len(lags), 2),
        "p95_lag_s": round(sorted(lags)[int(len(lags) * 0.95) - 1] if lags else 0, 2),
        "ge_5s_count": sum(1 for l in lags if l >= 5.0),
        "history": history,
    }


# ─── 4. 读 perf_diag_results.json (e2e 49 端点) ──────────────────────
def read_perf_diag() -> dict[str, Any]:
    p = LOGS_DIR / "perf_diag_results.json"
    if not p.exists():
        return {"available": False, "reason": f"{p} not found"}
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return {"available": True, "data": d}
    except Exception as e:
        return {"available": False, "reason": f"parse error: {e}"}


# ─── 报告生成 ──────────────────────────────────────────────────────────
def _fmt_pct(num: float, denom: float) -> str:
    if denom <= 0:
        return "0.0%"
    return f"{(num / denom) * 100:.1f}%"


def build_markdown(warmup: dict, pyinst: dict, lag: dict, perf: dict) -> str:
    out: list[str] = []
    out.append(f"# Lifespan 长尾观测报告\n")
    out.append(f"生成时间: {datetime.now().isoformat(timespec='seconds')}\n")
    out.append(f"数据源: `backend/logs/` 已有产物 (不重启后端)\n")
    out.append("\n---\n\n")

    # 1. warmup_timing
    out.append("## 1. Lifespan 启动期 6 阶段耗时\n\n")
    if not warmup.get("available"):
        out.append(f"⚠️ warmup_timing.json 不可用: {warmup.get('reason')}\n")
    else:
        d = warmup["data"]
        out.append(f"**total: {d.get('total_duration_ms', 0):.1f}ms** ({d.get('total_duration_ms', 0) / 1000:.2f}s)\n\n")
        out.append("| 阶段 | 耗时 (ms) | 占比 | 类别 | 说明 |\n")
        out.append("|---|---:|---:|---|---|\n")
        total = d.get("total_duration_ms", 0) or 1
        for r in d.get("records", []):
            pct = r.get("duration_ms", 0) / total * 100
            out.append(f"| `{r.get('label')}` | {r.get('duration_ms', 0):.1f} | "
                       f"{pct:.1f}% | {r.get('category')} | {r.get('note', '')} |\n")
        # 关键观察
        out.append("\n**关键观察**:\n\n")
        records = d.get("records", [])
        records.sort(key=lambda r: r.get("duration_ms", 0), reverse=True)
        if records:
            top = records[0]
            out.append(f"- 最慢阶段: `{top.get('label')}` = {top.get('duration_ms', 0):.1f}ms "
                       f"({_fmt_pct(top.get('duration_ms', 0), total)})\n")
            # NAV 拉取相关
            nav_stages = [r for r in records if "nav" in r.get("label", "").lower() or "fund" in r.get("note", "").lower()]
            if nav_stages:
                out.append(f"- NAV/基金相关阶段: {', '.join(s.get('label') for s in nav_stages)} "
                           f"累计 {sum(s.get('duration_ms', 0) for s in nav_stages):.1f}ms\n")
        out.append("\n")

    # 2. pyinstrument
    out.append("## 2. 主线程栈帧耗时 (warmup_pyinstrument.txt)\n\n")
    if not pyinst.get("available"):
        out.append(f"⚠️ warmup_pyinstrument.txt 不可用: {pyinst.get('reason')}\n")
    else:
        h = pyinst.get("header", {})
        out.append(f"**总时长**: {h.get('duration_s', 0):.2f}s · "
                   f"**采样数**: {h.get('samples', 0)}\n\n")
        out.append("**Top 25 栈帧** (按耗时降序):\n\n")
        out.append("| 耗时 (s) | 函数 | 文件:行 |\n")
        out.append("|---:|---|---|\n")
        for f in pyinst.get("top_frames", []):
            out.append(f"| {f.get('duration_s', 0):.3f} | `{f.get('function')}` | "
                       f"`{f.get('file')}:{f.get('line')}` |\n")
        out.append("\n")

    # 3. loop_lag
    out.append("## 3. 事件循环 lag 历史 (loop_watchdog)\n\n")
    if not lag.get("available"):
        out.append("⚠️ backend.log 内未发现 loop_lag 触发记录 (watchdog 阈值 = 5.0s)\n")
        out.append("   - 若后端已启动但无任何 lag 记录 → lifespan 5.62s 问题已修复\n")
        out.append("   - 若后端未启动 → 数据为空, 启动后端重跑本脚本\n")
    else:
        out.append(f"**记录数**: {lag.get('count')} · **峰值**: {lag.get('max_lag_s', 0):.2f}s · "
                   f"**均值**: {lag.get('mean_lag_s', 0):.2f}s · **P95**: {lag.get('p95_lag_s', 0):.2f}s\n\n")
        out.append(f"**≥ 5.0s 触发次数**: {lag.get('ge_5s_count', 0)}\n\n")
        if lag.get("history"):
            out.append("**时间线**:\n\n")
            for h in lag["history"][-10:]:  # 最近 10 条
                out.append(f"- `{h.get('timestamp')}` lag={h.get('lag_s'):.2f}s "
                           f"live_tasks={h.get('live_tasks')} (源: {h.get('log_file')})\n")
        out.append("\n")
        out.append("**判定**:\n\n")
        if lag.get("max_lag_s", 0) >= 10.0:
            out.append("- 🔴 **严重**: peak lag ≥ 10s, 仍有 5min+ 卡死风险\n")
        elif lag.get("max_lag_s", 0) >= 5.0:
            out.append("- 🟡 **警告**: peak lag ≥ 5s (watchdog 阈值), 仍可能触发卡死\n")
        else:
            out.append("- 🟢 **健康**: peak lag < 5s, r42 治标已生效\n")
        out.append("\n")

    # 4. perf_diag
    out.append("## 4. E2E 端点实测耗时 (verify_perf)\n\n")
    if not perf.get("available"):
        out.append(f"⚠️ perf_diag_results.json 不可用: {perf.get('reason')}\n")
    else:
        d = perf["data"]
        out.append(f"**总端点数**: {d.get('total_endpoints', 0)} · "
                   f"**通过**: {d.get('passed', 0)} · **失败**: {d.get('failed', 0)} · "
                   f"**总耗时**: {d.get('total_time_ms', 0):.1f}ms\n\n")
        slow = d.get("slow_endpoints", [])
        if slow:
            out.append("**慢端点 Top N**:\n\n")
            out.append("| 端点 | 耗时 (ms) |\n|---|---:|\n")
            for ep, ms in slow[:15]:
                out.append(f"| `{ep}` | {ms:.1f} |\n")
            out.append("\n")

    out.append("## 5. 决策依据 / round45 实施参考\n\n")
    out.append("- 若 §1 的 NAV 拉取相关阶段 ≥ 5s 且 §3 peak lag ≥ 5s → **r45 必须做**:\n")
    out.append("  - cache_service 加 `redis_cache_sync` 抽象 (现有 async client 的 sync 包装)\n")
    out.append("  - `_fundamentals.get_fund_nav` 改先 Redis hit, miss 再 fetch_fund_nav\n")
    out.append("  - main.py lifespan 后台加 1h 周期预热任务 (调 warmup_one_sync 拉 1618 候选)\n")
    out.append("- 若 §3 peak lag < 1s (r42 治标已足够) → r45 可降级为「lifespan 长尾监控」\n")
    out.append("- 若 §4 慢端点 > 5s 的 ≥ 3 个 → 单独排期优化 (与 r45 解耦)\n")
    return "".join(out)


# ─── main ──────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true",
                    help="输出 JSON 到 stdout (默认: markdown 报告 + JSON 文件)")
    args = ap.parse_args()

    warmup = read_warmup_timing()
    pyinst = read_pyinstrument_top()
    lag = read_loop_lag_history()
    perf = read_perf_diag()

    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "warmup_timing": warmup,
        "pyinstrument": pyinst,
        "loop_lag": lag,
        "perf_diag": perf,
    }

    # 写 JSON 数据
    json_path = LOGS_DIR / "lifespan_observation_data.json"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[JSON] {json_path}")

    # 写 markdown
    md = build_markdown(warmup, pyinst, lag, perf)
    md_path = LOGS_DIR / "lifespan_observation_report.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[MD]   {md_path}")

    # 控制台摘要
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n=== 摘要 ===")
        if warmup.get("available"):
            d = warmup["data"]
            print(f"warmup 总耗时: {d.get('total_duration_ms', 0) / 1000:.2f}s")
        if pyinst.get("available"):
            h = pyinst.get("header", {})
            print(f"pyinstrument duration: {h.get('duration_s', 0):.2f}s "
                  f"samples={h.get('samples', 0)}")
        if lag.get("available"):
            print(f"loop_lag: count={lag.get('count')} max={lag.get('max_lag_s', 0):.2f}s "
                  f"ge_5s={lag.get('ge_5s_count', 0)}")
        else:
            print("loop_lag: 0 触发记录 (后端未启动或无 ≥5s lag)")
        if perf.get("available"):
            d = perf["data"]
            print(f"perf_diag: {d.get('passed')}/{d.get('total_endpoints')} pass "
                  f"total={d.get('total_time_ms', 0) / 1000:.2f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
