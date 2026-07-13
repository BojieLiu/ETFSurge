import os
import asyncio
import httpx
import time

async def test():
    LLM_API_URL = "https://api.deepseek.com/chat/completions"
    API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    MODEL = "deepseek-v4-flash"
    
    system = "Test system prompt"
    user = 'Test user prompt - please respond with JSON: {"test": "ok"}'
    
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f'Bearer {os.getenv("DEEPSEEK_API_KEY")}', "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
                "max_tokens": 8192,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        print(f"Time: {time.time()-t0:.1f}s")
        print(f"Response: {content[:100]}")

asyncio.run(test())