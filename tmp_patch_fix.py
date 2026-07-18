#!/usr/bin/env python3
"""Fix duplicate lines in llm.py P5-a injection"""
with open(r"E:\ETF_Surge\backend\app\analysis\llm.py", "r", encoding="utf-8") as f:
    c = f.read()

# Remove the duplicate lines
old = '    else:\n        lines = ["## 输入数据", ""]\n    lines.append(f"- 情绪指数: {market_sentiment.get(\'sentiment_index\', \'N/A\')}")\n    lines.append("### 市场情绪")\n    lines.append(f"- 情绪指数: {market_sentiment.get(\'sentiment_index\', \'N/A\')}")'
new = '    else:\n        lines = ["## 输入数据", ""]\n        lines.append("### 市场情绪")\n        lines.append(f"- 情绪指数: {market_sentiment.get(\'sentiment_index\', \'N/A\')}")'

if old in c:
    c = c.replace(old, new, 1)
    with open(r"E:\ETF_Surge\backend\app\analysis\llm.py", "w", encoding="utf-8") as f:
        f.write(c)
    print("OK: fixed")
else:
    print("FAIL: not found")
    import sys; sys.exit(1)
