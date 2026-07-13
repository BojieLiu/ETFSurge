import asyncio
import httpx
import time

async def test():
    import httpx
    import time

    system = "You are an ETF portfolio strategist. Output ONLY valid JSON."

    user = """Design 3 ETF portfolios (aggressive, balanced, defensive) with 8-12 ETFs each.
Rules: 8-12 ETFs per portfolio, single ETF 5-15%, same industry <=2, no bonds.
Aggressive: equity >=85%, cash <=10%. Balanced: equity 65-75%, cash 10-15%. Defensive: equity 50-60%, cash 15-20%, gold <=8%.
Must include CSI A500 ETF (560310) 5-15% in each.
Output pure JSON only.

{
  "portfolios": [
    {"type":"aggressive","name":"进攻型组合","etfs":[{"name":"ETF名称","symbol":"代码","weight":0.XX,"logic":"配置逻辑"}],"cash_weight":0.XX},
    {"type":"balanced",...},{"type":"defensive",...}
  ]
}"""

    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        t0 = time.time()
        resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": "Bearer REDACTED", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
            },
        )
        print(f"HTTP Status: {resp.status_code}")
        print(f"Headers: {dict(resp.headers)}")
        print(f"Response text length: {len(resp.text)}")
        print(f"Response text: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        print(f"Content length: {len(content) if content else 0}")
        if content:
            print(f"Content: {content[:1000]}")

import asyncio
asyncio.run(test())