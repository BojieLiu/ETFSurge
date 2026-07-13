import urllib.request, json, sys

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/v1/analysis/portfolio-design',
    data=b'{}',
    headers={'Content-Type': 'application/json'},
    method='POST'
)
try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = resp.read()
        print(f'Status: {resp.status}, Length: {len(body)}')
        data = json.loads(body)
        print(f'Keys: {list(data.keys())}')
        print(f'Portfolios: {len(data.get("portfolios", []))}')
except urllib.error.HTTPError as e:
    print(f'HTTP Error: {e.code}')
    body = e.read()
    print(f'Body: {body.decode("utf-8", errors="replace")[:500]}')
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
