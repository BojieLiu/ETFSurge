"""Probe: check Finnhub API for sector/industry data."""
import sys, os, json, urllib.request
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv("../backend/.env")

key = os.getenv("FINNHUB_API_KEY", "")
if not key or key.startswith("your_"):
    print("FINNHUB_API_KEY not configured, skipping")
    sys.exit(0)

BASE = "https://finnhub.io/api/v1"

def req(path, params=None):
    url = f"{BASE}{path}?token={key}"
    if params:
        url += "&" + "&".join(f"{k}={v}" for k, v in params.items())
    r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

# 1. stock/profile2 行业信息
data = req("/stock/profile2", {"symbol": "AAPL"})
print("=== Finnhub AAPL profile2 ===")
if data:
    for k in sorted(data.keys()):
        print(f"  {k}: {data[k]}")
else:
    print("  empty")

# 2. US stock list with sectors
data2 = req("/stock/symbol", {"exchange": "US"})
print(f"\n=== Finnhub US stock list ===")
if data2 and len(data2) > 0:
    print(f"总数: {len(data2)}")
    print(f"字段: {list(data2[0].keys())}")
    print(f"第一行: {json.dumps(data2[0], indent=2)}")

# 3. sector-performance
data3 = req("/sector-performance")
print(f"\n=== Finnhub sector-performance ===")
if data3:
    print(json.dumps(data3[:10], indent=2))
else:
    print("  empty")
