import urllib.request, json

# Test through Vite proxy like the frontend would
req = urllib.request.Request(
    'http://localhost:5173/api/v1/analysis/portfolio-design',
    data=b'',
    headers={'Content-Type': 'application/json'},
    method='POST'
)
try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = resp.read()
        print(f'Status: {resp.status}')
        data = json.loads(body)
        print(f'Portfolios: {len(data.get("portfolios", []))}')
        if data.get('portfolios'):
            print(f'First: {data["portfolios"][0]["name"]}')
except Exception as e:
    print(f'Error: {e}')
