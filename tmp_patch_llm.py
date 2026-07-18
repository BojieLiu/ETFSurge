#!/usr/bin/env python3
"""P5-a: modify generate_design_report + _build_design_report_prompt to accept plan_tables"""
import sys

path = r"E:\ETF_Surge\backend\app\analysis\llm.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# 1. Add plan_tables parameter to generate_design_report
old = "async def generate_design_report(\n    strategies: list[dict],\n    market_sentiment: dict | None = None,\n    benchmark_stocks: list[dict] | None = None,\n    market_context: dict | None = None,\n) -> str:"
new = "async def generate_design_report(\n    strategies: list[dict],\n    market_sentiment: dict | None = None,\n    benchmark_stocks: list[dict] | None = None,\n    market_context: dict | None = None,\n    plan_tables: str | None = None,\n) -> str:"
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("OK: generate_design_report signature updated")
else:
    print("FAIL: generate_design_report signature not found")

# 2. Pass plan_tables to _build_design_report_prompt
old = "    prompt = _build_design_report_prompt(\n        strategies,\n        ctx.get(\"market_sentiment\", market_sentiment or {}),\n        ctx.get(\"benchmark_stocks\", benchmark_stocks or []),\n        market_context=ctx,\n    )"
new = "    prompt = _build_design_report_prompt(\n        strategies,\n        ctx.get(\"market_sentiment\", market_sentiment or {}),\n        ctx.get(\"benchmark_stocks\", benchmark_stocks or []),\n        market_context=ctx,\n        plan_tables=plan_tables,\n    )"
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("OK: plan_tables passed to _build_design_report_prompt")
else:
    print("FAIL: _build_design_report_prompt call not found")

# 3. Add plan_tables param to _build_design_report_prompt
old = "def _build_design_report_prompt(\n    strategies: list[dict],\n    market_sentiment: dict,\n    benchmark_stocks: list[dict],\n    market_context: dict | None = None,\n) -> str:"
new = "def _build_design_report_prompt(\n    strategies: list[dict],\n    market_sentiment: dict,\n    benchmark_stocks: list[dict],\n    market_context: dict | None = None,\n    plan_tables: str | None = None,\n) -> str:"
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("OK: _build_design_report_prompt signature updated")
else:
    print("FAIL: _build_design_report_prompt signature not found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"TOTAL: {changes} changes")
