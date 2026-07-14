import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv('DEEPSEEK_API_KEY')
print(f'Key from env: {key[:20]}...' if key else 'NO KEY')

async def test():
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            'https://api.deepseek.com/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={
                'model': 'deepseek-v4-flash',
                'messages': [{'role': 'system', 'content': 'Test'}, {'role': 'user', 'content': 'Say OK'}],
                'temperature': 0.3,
                'max_tokens': 100,
            },
        )
        print(f'Status: {resp.status_code}')
        print(f'Response: {resp.text[:500]}')

asyncio.run(test())