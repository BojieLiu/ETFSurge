"""Script to make remaining Phase D/E edits that the File tool can't handle due to encoding."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

# 1. Add market field to LLMReportRequest
with open('backend/app/routers/analysis.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = 'class LLMReportRequest(BaseModel):\n    symbols: list[str] | None = None'
new = 'class LLMReportRequest(BaseModel):\n    symbols: list[str] | None = None\n    market: str = "A"'
assert old in content, 'LLMReportRequest not found'
content = content.replace(old, new, 1)

# 2. In llm_report_stream, use req.market to filter data
old2 = "    if req.symbols:\n        market_data = [m for m in market_data if m.get(\"symbol\") in req.symbols]\n    else:\n        major_symbols = {\"000001\", \"399001\", \"399006\", \"000688\", \"000300\", \"510050\", \"510300\", \"510500\", \"159915\"}\n        market_data = [m for m in market_data if m.get(\"symbol\", \"\") in major_symbols or m.get(\"asset_type\", \"\") in (\"index\", \"futures\")]"
new2 = '''    if req.symbols:
        market_data = [m for m in market_data if m.get("symbol") in req.symbols]
    else:
        market = req.market
        if market == "A":
            major_symbols = {"000001", "399001", "399006", "000688", "000300", "510050", "510300", "510500", "159915"}
        elif market == "HK":
            major_symbols = {"HSI", "HSCEI", "00700", "09988", "02800"}
        elif market == "US":
            major_symbols = {"SPX", "IXIC", "SPY", "QQQ", "AAPL"}
        elif market == "global":
            major_symbols = {"000001", "HSI", "SPX", "IXIC", "GC=F", "CL=F"}
        else:
            major_symbols = {"000001", "399001", "399006", "000688", "000300"}
        market_data = [m for m in market_data if m.get("symbol", "") in major_symbols or m.get("asset_type", "") in ("index", "futures")]'''
assert old2 in content, 'market_data filter block not found'
content = content.replace(old2, new2, 1)

with open('backend/app/routers/analysis.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('analysis.py updated: LLMReportRequest + market filter')

# 3. Update master plan
with open('docs/implementation-master-plan.md', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    '| 2.5.5 | market-analysis Phase C（前端 UnifiedAnalysis 合并组件） | market-analysis \u00a75 | ❌ 未完成 | 4-5h | Phase 1.1.8+1.1.9 |',
    '| 2.5.5 | market-analysis Phase C（前端 UnifiedAnalysis 合并组件） | market-analysis \u00a75 | ✅ 已实施（commit 0136a77：UnifiedAnalysis.vue 合并三类分析） | 4-5h | Phase 1.1.8+1.1.9 |'
)
content = content.replace(
    '| 2.5.6 | market-analysis Phase D（AI 顾问流式+数据管道） | market-analysis \u00a76 | ❌ 未完成 | 2-3h | 无（可并行）',
    '| 2.5.7 | market-analysis Phase E（市场报告质量提升） | market-analysis \u00a77 | ❌ 未完成 | 2-3h | 无（可并行）'
)
# Actually let me just find the right lines
print('Master plan lines found:')
import re
for prefix in ['2.5.5', '2.5.6', '2.5.7']:
    for i, line in enumerate(content.split('\n')):
        if f'| {prefix} ' in line:
            print(f'  Line {i}: {line[:100]}')

with open('docs/implementation-master-plan.md', 'w', encoding='utf-8') as f:
    f.write(content)
print('Master plan updated')
