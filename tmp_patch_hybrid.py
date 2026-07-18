#!/usr/bin/env python3
"""P5-a: hybrid assembly — modify compose_and_push_report"""
import sys

path = r"E:\ETF_Surge\backend\app\tasks\design_report.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = """        # 调用 LLM（P1: 透传完整 market_context），加 90 秒超时防止挂起
        try:
            report_text = await asyncio.wait_for(
                generate_design_report(
                    strategies=strategies,
                    market_sentiment=market_sentiment,
                    benchmark_stocks=benchmark_stocks,
                    market_context=market_context,
                ),
                timeout=90,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.error("[design_report] LLM generation timed out after 90s, using fallback summary")
            report_text = None"""

new = """        # P5-a: 先生成策略表格（引擎直接渲染，确保与方案卡片一致）
        plan_tables = _build_plan_tables(strategies)

        # 调用 LLM，注入预生成的策略表格，让 LLM 只写分析部分
        try:
            llm_analysis = await asyncio.wait_for(
                generate_design_report(
                    strategies=strategies,
                    market_sentiment=market_sentiment,
                    benchmark_stocks=benchmark_stocks,
                    market_context=market_context,
                    plan_tables=plan_tables,
                ),
                timeout=90,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.error("[design_report] LLM generation timed out after 90s, using fallback summary")
            llm_analysis = None

        if llm_analysis:
            report_text = llm_analysis + "\\n\\n---\\n\\n" + plan_tables
        else:
            logger.warning("[design_report] LLM empty, using engine tables only")
            report_text = "# ETF 组合设计方案（数据摘要）\\n" + plan_tables"""

if old in content:
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: hybrid assembly applied")
else:
    print("FAIL: old text not found")
    sys.exit(1)
