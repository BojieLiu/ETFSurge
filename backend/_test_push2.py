"""Round 3: Fix test F and test push2 with proper headers."""
import urllib.request, json, time

print("=" * 60)
print("PUSH2 DETAILED ANALYSIS")
print("=" * 60)

# The EXACT URL from fundamentals_fetcher.py line 607-608
push2_base = "https://push2.eastmoney.com"

# Test 1: push2 with different User-Agents
print("\n[1] push2 with Chrome User-Agent")
url = f"{push2_base}/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6"
for ua_name, ua_val in [
    ("Mozilla/5.0", "Mozilla/5.0"),
    ("Chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"),
    ("No UA", None),
]:
    t0 = time.time()
    req = urllib.request.Request(url)
    if ua_val:
        req.add_header("User-Agent", ua_val)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        print(f"  [{ua_name}] OK: {time.time()-t0:.2f}s, data.has_diff={bool(data.get('data',{}).get('diff'))}")
    except Exception as e:
        print(f"  [{ua_name}] FAIL after {time.time()-t0:.1f}s: {type(e).__name__}")

# Test 2: Sina fallback
print("\n[2] Sina (existing fallback)")
url_sina = "https://hq.sinajs.cn/list=s_sh000001"
try:
    t0 = time.time()
    req = urllib.request.Request(url_sina, headers={"Referer": "https://finance.sina.com.cn"})
    resp = urllib.request.urlopen(req, timeout=10)
    print(f"  OK: {time.time()-t0:.2f}s, {resp.read().decode('gbk')[:100]}")
except Exception as e:
    print(f"  FAIL after {time.time()-t0:.1f}s: {e}")

# Test 3: push2 82 subdomain
print("\n[3] push2.82 subdomain (from logs)")
url_82 = f"https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6"
try:
    t0 = time.time()
    req = urllib.request.Request(url_82, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode("utf-8"))
    print(f"  OK: {time.time()-t0:.2f}s")
except Exception as e:
    print(f"  FAIL after {time.time()-t0:.1f}s: {e}")

# Test 4: What the code actually calls - trace the URL params
print("\n[4] EXACT URL from fundamentals_fetcher.py")
exact_url = ("https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=5000&po=1&np=1&fields=f2,f3,f4"
    "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23")
t0 = time.time()
req = urllib.request.Request(exact_url, headers={"User-Agent": "Mozilla/5.0"})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode("utf-8"))
    items = data.get("data", {}).get("diff", [])
    print(f"  OK: {time.time()-t0:.2f}s, got {len(items)} items")
except Exception as e:
    print(f"  FAIL after {time.time()-t0:.1f}s: {e}")

print("\n[5] same but pz=100 (smaller request)")
exact_url2 = ("https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=100&po=1&np=1&fields=f2,f3,f4"
    "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23")
t0 = time.time()
req = urllib.request.Request(exact_url2, headers={"User-Agent": "Mozilla/5.0"})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode("utf-8"))
    items = data.get("data", {}).get("diff", [])
    print(f"  OK: {time.time()-t0:.2f}s, got {len(items)} items")
except Exception as e:
    print(f"  FAIL after {time.time()-t0:.1f}s: {e}")

# Test 6: Check if push2 works with httpx (different TLS)
print("\n[6] push2 with httpx (if available)")
try:
    import httpx
    t0 = time.time()
    r = httpx.get(exact_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    print(f"  OK: {time.time()-t0:.2f}s, status={r.status_code}")
except ImportError:
    print("  httpx not available")
except Exception as e:
    print(f"  FAIL after {time.time()-t0:.1f}s: {type(e).__name__}: {e}")
