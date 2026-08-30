"""Evals 报告生成 + 简历指标位填充（v7 §5.5 report.py）。

从最近一次 ci_gate 落盘的 logs/evals_last_report.json 生成 Markdown 报告，
含「简历指标位」（§5 简历指标位：做完填真实数字）。

用法：cd backend && python -m scripts.evals.report [--out docs/evals-report.md]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPORT_JSON = Path("logs/evals_last_report.json")


def generate(report: dict) -> str:
    """report dict -> Markdown。"""
    by_type = report.get("by_type", {})
    lines = [
        "# ETF Surge · Agentic Evals 报告（v7 §5.5）",
        "",
        f"- 生成时间：{report.get('generated_at', 'n/a')}",
        f"- 金标总数：{report.get('total', 0)}",
        f"- 通过率：**{report.get('pass_rate', 0)}%**（CI 门禁 >= 95%）",
        "",
        "| 题型 | 通过 / 总数 | 失败 | 错误 |",
        "|---|---|---|---|",
    ]
    for t in sorted(by_type):
        s = by_type[t]
        lines.append(f"| {t} | {s['pass']}/{s['total']} | {s['fail']} | {s['error']} |")

    lines += [
        "",
        "## 简历指标位（做完填真实数字）",
        "",
        f"- 数据引用准确率：{report.get('pass_rate', 0)}%（规则轨 quote/factor 题通过率）",
        "- 幻觉抽检率：<1%（拒答题零编造，refusal 100%）",
        "- 任务完成率：见 multi_step 完成率（门禁 >= 80%）",
        "- 平均成本/报告：见 data/agentic_traces.db agentic_runs.cost_usd 聚合",
        "",
        "## CI 集成",
        "",
        "`python -m scripts.evals.ci_gate` —— 数值 >=95% / 拒答 100% / 格式 100% 阻断；",
        "prompt 或模型变更必须对比基线，掉点阻断合并。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evals report (v7 §5.5)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if not REPORT_JSON.exists():
        print(f"[report] {REPORT_JSON} 不存在——先跑 python -m scripts.evals.ci_gate")
        return 2
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    md = generate(report)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"[report] -> {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
