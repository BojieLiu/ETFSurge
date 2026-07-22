"""Debug news - check backend and frontend behavior."""
import sys, os, json
sys.path.insert(0, os.path.join('backend'))

# 1. Check if backend server is running
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
port_open = s.connect_ex(('127.0.0.1', 8000)) == 0
s.close()
print(f"Backend port 8000: {'OPEN' if port_open else 'CLOSED'}")

# 2. Check health
if port_open:
    import requests
    try:
        r = requests.get('http://127.0.0.1:8000/health', timeout=5)
        print(f"Health: {r.status_code} {r.text[:100]}")
        
        # 3. Check news API
        r = requests.get('http://127.0.0.1:8000/api/v1/news/headlines', timeout=20)
        print(f"News API: {r.status_code}, len={len(r.text)}")
        data = r.json()
        print(f"News count: {len(data)}")
        for item in data[:3]:
            print(f"  id={item.get('id','')[:12]} title={item.get('title','')[:40]}")
    except Exception as e:
        print(f"API error: {e}")
else:
    print("Backend not running")

# 4. Test fetch_news_headlines directly
print("\n=== Direct: fetch_news_headlines ===")
from app.fetchers.news_fetcher import fetch_news_headlines
news = fetch_news_headlines()
print(f"Direct: {len(news)} items")
for item in news[:3]:
    print(f"  title={item.get('title','')[:40]} id={item.get('id','')[:12]}")
