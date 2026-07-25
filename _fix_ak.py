import sys
sys.stdout.reconfigure(encoding='utf-8')
with open(r'backend/app/routers/analysis.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re

# Find the llm_advice_stream function
pattern = r'@router\.post\("/llm-advice/stream"\)\nasync def llm_advice_stream.*?HTTPException\(status_code=502, detail=f"LLM streaming failed: {e}"\)'

match = re.search(pattern, content, re.DOTALL)
if match:
    print(f'Found match at position {match.start()}-{match.end()}')
    old_func = match.group()
    
    new_func = '''@router.post("/llm-advice/stream")
async def llm_advice_stream(query: str = Query(...), context: dict | None = None):
    """流式投资建议问答 — 自动注入市场数据。"""
    from ..services.pool_manager import pool_manager
    from ..analysis.llm import _build_advice_stream_prompt
    from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news

    ctx = dict(context or {})

    try:
        ctx["market_regime"] = pool_manager.get_market_regime() or ""
        sent = pool_manager.get_market_sentiment() or {}
        ctx["market_sentiment"] = sent

        idx_data = pool_manager.get_index_realtime() or []
        ctx.setdefault("market_data", []).extend(idx_data[:8])

        sector_data = pool_manager.get_sector_momentum() or []
        for s in sector_data[:5]:
            ctx.setdefault("market_data", []).append({
                "name": s.get("name"),
                "change_pct": s.get("change_pct"),
                "asset_type": "sector",
            })

        news_items = fetch_news_headlines() or []
        try:
            macro_items = fetch_macro_news() or []
            news_items.extend(macro_items)
        except Exception:
            pass
        ctx["news"] = (ctx.get("news") or []) + (news_items or [])[:10]

        try:
            from ..services.portfolio_service import get_all_holdings
            portfolio_items = get_all_holdings()
            if portfolio_items:
                ctx["portfolio"] = portfolio_items[:10]
        except Exception:
            pass
    except Exception as e:
        logger.debug("[llm-advice-stream] data injection: %s", e)

    try:
        prompt = _build_advice_stream_prompt(query, ctx)
        agent = get_agent("advice")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")'''
    
    content = content.replace(old_func, new_func, 1)
    with open(r'backend/app/routers/analysis.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Replaced successfully')
else:
    print('Pattern NOT found - trying direct string match')
    if '@router.post("/llm-advice/stream")' in content:
        print('Route decorator found')
        start = content.index('@router.post("/llm-advice/stream")')
        end = content.index('raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")', start)
        # Find next blank line after the exception
        end = content.index('\n\n', end)
        print(f'Route spans {start} to {end}')
        print('First 200 chars:', repr(content[start:start+200]))
    else:
        print('Route decorator NOT found in file')
        print('File size:', len(content))
        print('First 200 chars:', repr(content[:200]))
