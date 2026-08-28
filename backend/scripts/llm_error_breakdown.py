"""R143 LLM 错误率按 provider 分解（round38 §5.4 观察项 R143 实施路径 A）。

读 data/token_usage.db 的 usage_records 表,按 provider × HTTP错误码 聚合,
输出 markdown 矩阵 + 决策建议(retry / 熔断 / 轮换 / 配额问题分类)。

输出:
- 总览: 总调用 / 总错误 / 错误率 (与 round38 §0.1 30.5% 基线对照)
- provider × 错误码 矩阵表 (主输出, 用于决策)
- 错误码 详细分类(401/402/403/404/429/500/503/timeout/stream_dropout/...)
- 决策建议表 (哪些 provider 需要 retry, 哪些需要熔断, 哪些是 key 问题)

用法:
    python scripts/llm_error_breakdown.py
    python scripts/llm_error_breakdown.py --days 7          # 最近 7 天
    python scripts/llm_error_breakdown.py --db data/token_usage.db
    python scripts/llm_error_breakdown.py --json            # JSON 输出
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


# ── 错误码分类规则 ────────────────────────────────────────────────
# error_message 是 httpx 异常文本,需要正则提取状态码/关键词
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
    """错误消息 → 错误码类别 (401/402/.../timeout/dns/stream_dropout/unknown/empty)."""
    if not msg:
        return "empty"
    for label, pat in _PATTERNS:
        if pat.search(msg):
            return label
    return "other"


# ── 决策建议分类 ──────────────────────────────────────────────────
# 根据错误模式推断需要什么处置
_DECISION_HINTS: dict[str, str] = {
    "401": "API key 过期/无效 → 检查 .env 配额",
    "402": "账户余额不足 → 充值或切换 provider",
    "403": "权限/区域限制 → 检查 key 权限或 IP 出口",
    "404": "模型 endpoint 错误 → 检查 model 名称",
    "429": "限流 → 加 retry with backoff + provider 轮换",
    "500": "服务端 bug → 熔断 + provider 轮换",
    "502": "上游网关问题 → 熔断 + 退避",
    "503": "服务端维护/过载 → 熔断 + 退避",
    "timeout": "网络慢/源超时 → 加重试 + 增加 timeout",
    "connection": "网络断/拒连 → 加重试 + 探活",
    "dns": "DNS 失败 → 检查代理/hosts",
    "stream_dropout": "流式响应中断 → 加重试 + 检查 SSE 解析",
    "empty": "异常未记录 message → 加 logger 记录",
    "other": "未分类 → 人工 review",
}


def fetch_records(conn: sqlite3.Connection, since_ts: float) -> list[tuple]:
    """读 usage_records,过滤时间窗。返回 (provider, success, error_message, model, function_name)。"""
    cur = conn.cursor()
    return list(cur.execute(
        "SELECT COALESCE(provider,''), success, error_message, model, function_name "
        "FROM usage_records WHERE timestamp >= ?",
        (since_ts,),
    ))


def aggregate(records: list[tuple]) -> dict:
    """聚合 records 为:
    - by_provider: {provider: {total, errors, err_rate, by_code: {code: n}}}
    - overall: {total, errors, err_rate, by_code: {code: n}}
    """
    by_provider: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "errors": 0, "err_rate": 0.0, "by_code": defaultdict(int),
    })
    overall = {"total": 0, "errors": 0, "err_rate": 0.0, "by_code": defaultdict(int)}

    for provider, success, err_msg, model, fn in records:
        prov = provider or "(empty)"
        is_error = (success == 0)

        by_provider[prov]["total"] += 1
        overall["total"] += 1

        if is_error:
            code = classify_error(err_msg)
            by_provider[prov]["errors"] += 1
            by_provider[prov]["by_code"][code] += 1
            overall["errors"] += 1
            overall["by_code"][code] += 1

    for d in (overall, *by_provider.values()):
        if d["total"] > 0:
            d["err_rate"] = round(d["errors"] / d["total"] * 100, 2)
        d["by_code"] = dict(d["by_code"])

    return {"overall": overall, "by_provider": dict(by_provider)}


def render_markdown(stats: dict, since: datetime, until: datetime) -> str:
    """渲染 markdown 报告。"""
    overall = stats["overall"]
    by_provider = stats["by_provider"]

    lines: list[str] = []
    lines.append(f"# R143 LLM 错误率按 Provider 分解")
    lines.append("")
    lines.append(f"**时间窗口**: {since.isoformat(timespec='seconds')} → {until.isoformat(timespec='seconds')}")
    lines.append(f"**总调用**: {overall['total']:,}  **总错误**: {overall['errors']:,}  "
                 f"**错误率**: {overall['err_rate']}%")
    lines.append("")

    # ── Provider × 错误码 矩阵 ──
    lines.append("## 1. Provider × 错误码矩阵（主决策表）")
    lines.append("")

    # 收集所有错误码
    all_codes: list[str] = sorted({
        code
        for prov in by_provider.values()
        for code in prov["by_code"]
    })
    # 把 'empty' / 'other' / 'stream_dropout' 等放在最后
    # 优先级: 数字错误码优先,然后字母序
    _priority_order = {c: i for i, c in enumerate([
        "401", "402", "403", "404", "429", "500", "502", "503",
        "timeout", "connection", "dns", "stream_dropout", "empty", "other",
    ])}
    all_codes.sort(key=lambda c: (_priority_order.get(c, 99), c))

    header = ["Provider", "总调用", "总错误", "错误率"] + all_codes
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    # 按总调用降序
    for prov in sorted(by_provider, key=lambda p: by_provider[p]["total"], reverse=True):
        d = by_provider[prov]
        row = [prov, f"{d['total']:,}", f"{d['errors']:,}", f"{d['err_rate']}%"]
        for code in all_codes:
            n = d["by_code"].get(code, 0)
            row.append(str(n) if n > 0 else "")
        lines.append("| " + " | ".join(row) + " |")

    # ── Provider 错误率排序 ──
    lines.append("")
    lines.append("## 2. Provider 错误率排序")
    lines.append("")
    lines.append("| Provider | 总调用 | 错误 | 错误率 | 主要错误码 |")
    lines.append("|---|---|---|---|---|")
    for prov, d in sorted(by_provider.items(), key=lambda x: -x[1]["err_rate"]):
        if d["errors"] == 0:
            continue
        # top 3 错误码
        top_codes = sorted(d["by_code"].items(), key=lambda x: -x[1])[:3]
        top_str = ", ".join(f"{c}:{n}" for c, n in top_codes)
        lines.append(f"| {prov} | {d['total']:,} | {d['errors']:,} | {d['err_rate']}% | {top_str} |")

    # ── 错误码全局分布 ──
    lines.append("")
    lines.append("## 3. 错误码全局分布")
    lines.append("")
    lines.append("| 错误码 | 次数 | 占比 | 决策建议 |")
    lines.append("|---|---|---|---|")
    for code, n in sorted(overall["by_code"].items(), key=lambda x: -x[1]):
        pct = round(n / overall["errors"] * 100, 1) if overall["errors"] > 0 else 0
        hint = _DECISION_HINTS.get(code, "")
        lines.append(f"| {code} | {n:,} | {pct}% | {hint} |")

    # ── 决策总结 ──
    lines.append("")
    lines.append("## 4. 决策总结")
    lines.append("")
    # 找最高错误率 provider
    worst_prov = max(by_provider.items(), key=lambda x: x[1]["err_rate"]) if by_provider else None
    if worst_prov:
        prov, d = worst_prov
        lines.append(f"- **最高错误率 provider**: `{prov}` ({d['err_rate']}%, {d['errors']:,}/{d['total']:,})")
    lines.append(f"- **总体错误率**: {overall['err_rate']}% (round38 §0.1 基线 30.5%)")
    if overall["by_code"].get("429", 0) > 0:
        n429 = overall["by_code"]["429"]
        pct = round(n429 / overall["errors"] * 100, 1) if overall["errors"] > 0 else 0
        lines.append(f"- **429 限流占比**: {n429:,}/{overall['errors']:,} = {pct}% — "
                     f"若 > 50% 则优先加 retry with backoff + provider 轮换")
    if overall["by_code"].get("dns", 0) > 0:
        lines.append(f"- **DNS 错误**: {overall['by_code']['dns']} 次 — 检查代理/hosts 配置")
    if overall["by_code"].get("401", 0) > 0:
        lines.append(f"- **401 鉴权错误**: {overall['by_code']['401']} 次 — 检查 .env API key 有效性")
    if overall["by_code"].get("402", 0) > 0:
        lines.append(f"- **402 余额不足**: {overall['by_code']['402']} 次 — 充值或切换 provider")
    if overall["by_code"].get("timeout", 0) > 0:
        lines.append(f"- **timeout**: {overall['by_code']['timeout']} 次 — 加 retry + 调大 timeout")
    if overall["by_code"].get("stream_dropout", 0) > 0:
        lines.append(f"- **流式响应中断**: {overall['by_code']['stream_dropout']} 次 — 加 retry + 检查 SSE 解析")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="R143 LLM 错误率按 provider 分解")
    ap.add_argument("--db", default="data/token_usage.db", help="token_usage.db 路径")
    ap.add_argument("--days", type=int, default=45, help="最近 N 天 (默认 45)")
    ap.add_argument("--json", action="store_true", help="JSON 输出 (代替 markdown)")
    ap.add_argument("--out", help="写文件 (默认 stdout)")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        until_ts = datetime.datetime.now().timestamp()
        since_ts = until_ts - args.days * 86400
        records = fetch_records(conn, since_ts)
    finally:
        conn.close()

    stats = aggregate(records)
    since_dt = datetime.datetime.fromtimestamp(since_ts)
    until_dt = datetime.datetime.fromtimestamp(until_ts)

    if args.json:
        out = {
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
            "stats": stats,
        }
        payload = json.dumps(out, ensure_ascii=False, indent=2)
    else:
        payload = render_markdown(stats, since_dt, until_dt)

    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"Written to {args.out} ({len(payload):,} bytes)")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
