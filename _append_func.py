import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

script_dir = os.path.dirname(os.path.abspath(__file__))
target = os.path.join(script_dir, 'backend', 'app', 'analysis', 'llm.py')

with open(target, 'r', encoding='utf-8') as f:
    content = f.read()

extra = """

def _build_advice_stream_prompt(query: str, ctx: dict) -> str:
    \"\"\"构建流式投资建议 prompt — 注入市场数据。\"\"\"
    lines = [f"用户提问: {query}", ""]

    regime = ctx.get("market_regime", "")
    if regime:
        lines.append(f"## 市场背景\\n- 市场状态: {regime}")

    sentiment = ctx.get("market_sentiment", {})
    if sentiment and isinstance(sentiment, dict):
        s_lbl = sentiment.get("sentiment_label", "")
        s_idx = sentiment.get("sentiment_index", "")
        if s_lbl and s_idx:
            lines.append(f"- 市场情绪: {s_lbl} ({s_idx}/100)")
        elif s_lbl:
            lines.append(f"- 市场情绪: {s_lbl}")

    market_data = ctx.get("market_data", [])
    if market_data:
        lines.append("\\n## 实时行情")
        for item in market_data[:8]:
            name = item.get("name", "?")
            price = item.get("price", "N/A")
            chg = item.get("change_pct", "")
            if chg != "":
                lines.append(f"- {name}: {price} ({chg:+.2f}%)")

    news = ctx.get("news", [])
    if news:
        lines.append("\\n## 近期资讯")
        for n in news[:5]:
            lines.append(f"- {str(n.get('title', ''))[:80]}")

    portfolio = ctx.get("portfolio", [])
    if portfolio:
        lines.append("\\n## 持仓信息")
        for p in portfolio[:5]:
            w = p.get("target_weight", 0) or 0
            name = p.get('name', '?') or '?'
            sym = p.get('symbol', '?') or '?'
            lines.append(f"- {name}({sym}): {w*100:.1f}%")

    lines.append('')
    lines.append('请按以下框架回答：')
    lines.append('1. 直接回答用户问题，引用具体数据')
    lines.append('2. 给出判断依据')
    lines.append('3. 如涉及操作，给出分析和建议（不构成投资指令）')
    lines.append('')
    lines.append('使用 Markdown 格式，控制 500 字以内。')

    return "\\n".join(lines)
"""

content += extra

with open(target, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"Appended function to llm.py (total length: {len(content)} chars)")
