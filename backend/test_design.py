import asyncio, httpx
async def t():
    async with httpx.AsyncClient(timeout=120, trust_env=False) as c:
        r = await c.post('http://127.0.0.1:8000/api/v1/analysis/portfolio-design')
    print(f'Status: {r.status_code}')
    if r.status_code == 200:
        d = r.json()
        pfs = d.get('portfolios', [])
        print(f'Portfolios: {len(pfs)}')
        for pf in pfs:
            etfs = pf.get('etfs', [])
            print(f'  {pf.get("type")}: {len(etfs)} ETFs')
asyncio.run(t())