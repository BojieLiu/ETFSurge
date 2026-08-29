"""R50 B2: LLM 错误率按时间窗统计 (扩展 R43 llm_error_breakdown).

R43 聚合 (provider x 错误码 矩阵) 是"快照"; 本轮加"时序"维度, 拉最近 N 天 / N 小时错误率
走势, 用于发现:
- 周一周五规律 (e.g. 周一全天 402 配额耗尽)
- 集中爆发 (e.g. 8-26 12:00-13:00 OpenRouter 全面 429)
- 长期趋势 (e.g. DeepSeek 错误率 5% → 15% 持续上升 = key 配额问题)

输出:
- 时序总览: 错误率 / 调用数 / 错误数 (按 time_bucket 粒度聚合)
- provider x time_bucket 错误率矩阵
- 错误码 x time_bucket 错误数矩阵
- 异常窗口告警 (e.g. 单小时错误率 > 30% 自动标红)

用法:
    python scripts/llm_error_timeseries.py                          # 默认最近 7 天, 按天聚合
    python scripts/llm_error_timeseries.py --hours 24 --granularity hour
    python scripts/llm_error_timeseries.py --days 30 --granularity day
    python scripts/llm_error_timeseries.py --db data/token_usage.db
    python scripts/llm_error_timeseries.py --json
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# ── 错误码分类规则 (与 R43 llm_error_breakdown.py 同步) ──────
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("401", re.compile(r"'401 Authorization Required'")),
    ("402", re.compile(r"'402 Payment Required'")),
    ("403", re.compile(r"'403 Forbidden'")),
    ("404", re.compile(r"'404 Not Found'")),
    ("429", re.compile(r"'429 Too Many Requests'|HTTP 429")),
    ("500", re.compile(r"'500 Internal Server Error'|HTTP 500")),
    ("502", re.compile(r"'502 Bad Gateway'")),
    ("503", re.compile(r"'503 Service Unavailable'")),
    ("timeout", re.compile(r"wait_for timeout|TimeoutError|timed out", re.IGNORECASE)),
    ("connection", re.compile(r"Connection refused|Server disconnected|ConnectionError|Connection reset")),
    ("dns", re.compile(r"getaddrinfo|Name or service not known", re.IGNORECASE)),
    ("stream_dropout", re.compile(r"stream dropout|'choices'|coroutine' object")),
]


def classify_error(msg: str) -> str:
    if not msg:
        return "empty"
    for code, pat in _PATTERNS:
        if pat.search(msg):
            return code
    return "unknown"


def bucket_ts(ts: float, granularity: str) -> str:
    """按粒度截断 timestamp → bucket key (字符串 ISO)."""
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    if granularity == "hour":
        return dt.strftime("%Y-%m-%d %H:00")
    return dt.strftime("%Y-%m-%d")


def query_records(db_path: Path, since_ts: float) -> list[dict[str, Any]]:
    """读 usage_records 自 since_ts 起的所有行."""
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT timestamp, provider, model, success, error_message, duration_ms "
            "FROM usage_records WHERE timestamp >= ? ORDER BY timestamp",
            (since_ts,),
        ).fetchall()
    return [dict(r) for r in rows]


def analyze(records: list[dict], granularity: str) -> dict:
    """聚合分析: 总览 + provider x bucket 矩阵 + error_code x bucket 矩阵 + 异常窗口."""
    total_calls = 0
    total_errors = 0
    provider_bucket: dict[str, dict[str, tuple[int, int]]] = defaultdict(lambda: defaultdict(lambda: (0, 0)))
    code_bucket: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    overall_bucket: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    for r in records:
        ts = r["timestamp"]
        bucket = bucket_ts(ts, granularity)
        is_err = (r["success"] == 0)
        total_calls += 1
        if is_err:
            total_errors += 1
        # provider x bucket
        prov = r["provider"] or "unknown"
        calls, errs = provider_bucket[prov][bucket]
        provider_bucket[prov][bucket] = (calls + 1, errs + (1 if is_err else 0))
        # code x bucket
        code = classify_error(r.get("error_message", ""))
        if is_err:
            code_bucket[code][bucket] += 1
        # overall bucket
        c, e = overall_bucket[bucket]
        overall_bucket[bucket] = (c + 1, e + (1 if is_err else 0))

    # 异常窗口: 单 bucket 错误率 >= 30% (>= 5 calls)
    alert_buckets: list[dict] = []
    for bucket, (c, e) in overall_bucket.items():
        if c >= 5 and (e / c) >= 0.30:
            alert_buckets.append({
                "bucket": bucket,
                "calls": c, "errors": e, "rate": round(e / c, 4),
            })
    alert_buckets.sort(key=lambda x: x["rate"], reverse=True)

    return {
        "total_calls": total_calls,
        "total_errors": total_errors,
        "overall_error_rate": round(total_errors / total_calls, 4) if total_calls else 0.0,
        "buckets_count": len(overall_bucket),
        "overall_bucket": {b: {"calls": c, "errors": e, "rate": round(e / c, 4) if c else 0}
                           for b, (c, e) in sorted(overall_bucket.items())},
        "provider_bucket": {
            p: {bk: {"calls": c, "errors": e, "rate": round(e / c, 4) if c else 0}
                for bk, (c, e) in sorted(buckets.items())}
            for p, buckets in provider_bucket.items()
        },
        "code_bucket": {c: dict(sorted(buckets.items())) for c, buckets in code_bucket.items()},
        "alert_buckets": alert_buckets,
    }


def render_markdown(result: dict, granularity: str, since_hours: float) -> str:
    out: list[str] = []
    out.append(f"# LLM 错误率时序分析 (R50 B2)\n")
    out.append(f"时间窗: 最近 {since_hours:.0f}h · 粒度: {granularity}\n")
    out.append(f"总调用: **{result['total_calls']}** · "
               f"总错误: **{result['total_errors']}** · "
               f"错误率: **{result['overall_error_rate']*100:.2f}%**\n")
    out.append(f"覆盖 buckets: {result['buckets_count']}\n\n")

    if not result["overall_bucket"]:
        out.append("(无数据, DB 为空或时间窗内无调用)\n")
        out.append("\n## 1. 整体时序\n\n(空)\n")
        out.append("## 2. Provider x Bucket 错误率\n\n(空)\n")
        out.append("## 3. 错误码 x Bucket 错误数\n\n(空)\n")
        out.append("## 4. 异常窗口\n\n(空)\n")
        return "".join(out)

    # 总览表
    out.append("## 1. 整体时序 (按粒度聚合)\n\n")
    out.append("| bucket | calls | errors | rate |\n|---|---:|---:|---:|\n")
    for b, v in result["overall_bucket"].items():
        out.append(f"| `{b}` | {v['calls']} | {v['errors']} | {v['rate']*100:.1f}% |\n")
    out.append("\n")

    # provider x bucket
    if result["provider_bucket"]:
        out.append("## 2. Provider x Bucket 错误率\n\n")
        # 收集所有 bucket
        all_buckets = sorted({b for p in result["provider_bucket"].values() for b in p.keys()})
        out.append("| provider | " + " | ".join(f"`{b}`" for b in all_buckets) + " |\n")
        out.append("|---|" + "---:|" * len(all_buckets) + "\n")
        for prov, buckets in sorted(result["provider_bucket"].items()):
            row = [f"`{prov}`"]
            for b in all_buckets:
                if b in buckets:
                    v = buckets[b]
                    row.append(f"{v['rate']*100:.1f}%")
                else:
                    row.append("-")
            out.append("| " + " | ".join(row) + " |\n")
        out.append("\n")

    # code x bucket
    if result["code_bucket"]:
        out.append("## 3. 错误码 x Bucket 错误数\n\n")
        all_buckets = sorted({b for c in result["code_bucket"].values() for b in c.keys()})
        out.append("| code | " + " | ".join(f"`{b}`" for b in all_buckets) + " | total |\n")
        out.append("|---|" + "---:|" * len(all_buckets) + "---:|\n")
        for code, buckets in sorted(result["code_bucket"].items(), key=lambda x: -sum(x[1].values())):
            row = [f"`{code}`"]
            total = 0
            for b in all_buckets:
                n = buckets.get(b, 0)
                total += n
                row.append(str(n) if n else "-")
            row.append(str(total))
            out.append("| " + " | ".join(row) + " |\n")
        out.append("\n")

    # 异常窗口
    if result["alert_buckets"]:
        out.append(f"## 4. 异常窗口 (错误率 ≥ 30% 且调用 ≥ 5)\n\n")
        out.append("| bucket | calls | errors | rate |\n|---|---:|---:|---:|\n")
        for a in result["alert_buckets"][:20]:  # Top 20
            out.append(f"| `{a['bucket']}` | {a['calls']} | {a['errors']} | "
                       f"{a['rate']*100:.1f}% |\n")
        out.append("\n")
    else:
        out.append("## 4. 异常窗口\n\n无 (所有 bucket 错误率 < 30% 或调用 < 5)\n\n")

    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/token_usage.db", help="SQLite path")
    ap.add_argument("--hours", type=float, default=None, help="最近 N 小时 (与 --days 互斥)")
    ap.add_argument("--days", type=float, default=7, help="最近 N 天 (默认 7)")
    ap.add_argument("--granularity", choices=("hour", "day"), default="day",
                    help="聚合粒度 (默认 day)")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    since_hours = args.hours if args.hours is not None else args.days * 24
    since_ts = (datetime.datetime.now(tz=datetime.timezone.utc)
                - datetime.timedelta(hours=since_hours)).timestamp()

    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = Path(__file__).resolve().parent.parent / db_path

    records = query_records(db_path, since_ts)
    result = analyze(records, args.granularity)

    if args.json:
        out = {"params": {"since_hours": since_hours, "granularity": args.granularity},
               "result": result}
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_markdown(result, args.granularity, since_hours))
    return 0


if __name__ == "__main__":
    sys.exit(main())
