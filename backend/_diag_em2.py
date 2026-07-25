#!/usr/bin/env python3
"""Test EM with different TLS/HTTP settings, and alternative EM API endpoints."""
import sys, os, json, ssl
sys.path.insert(0, os.path.dirname(__file__))
os.environ["DEEPSEEK_API_KEY"] = "sk-test"

results = {}
import urllib.request

# 1. Check TLS version
print("1. TLS version test...")
try:
    ctx = ssl.create_default_context()
    with urllib.request.urlopen("https://push2.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43",
                                context=ctx, timeout=8) as resp:
        data = resp.read()
    results["tls_default"] = {"ok": True, "len": len(data)}
except Exception as e:
    results["tls_default"] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}

# Try with TLS 1.2 only
try:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen("https://push2.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43",
                                context=ctx, timeout=8) as resp:
        data = resp.read()
    results["tls_12"] = {"ok": True, "len": len(data)}
except Exception as e:
    results["tls_12"] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}

# 2. Try alternative EM API endpoints
print("2. Alternative EM endpoints...")
alt_urls = [
    ("em_old", "https://push2.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43,f58"),
    ("em_push", "https://push.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43,f58"),
    ("em_livedata", "https://push2.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43,f58,f170&fltt=2"),
    ("em_np_ulist", "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f43,f58,f170&secids=100.N225"),
    ("em_stockpai", "https://push2his.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43,f58"),
]
for label, url in alt_urls:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
            try:
                parsed = json.loads(data)
                rc = parsed.get("rc")
                results[label] = {"ok": True, "rc": rc, "len": len(data)}
            except:
                results[label] = {"ok": True, "raw": data[:50], "len": len(data)}
    except Exception as e:
        results[label] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}

# 3. Test with proper certificate validation disabled
print("3. Disable cert validation for EM...")
try:
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen("https://push2.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43",
                                context=ctx, timeout=8) as resp:
        data = resp.read()
    results["no_verify"] = {"ok": True, "len": len(data)}
except Exception as e:
    results["no_verify"] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}

# 4. Try to connect with raw HTTP (without TLS) to see error type
print("4. Test different User-Agent...")
for ua, label in [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "ua_chrome"),
    ("Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; Trident/6.0)", "ua_ie"),
    ("python-requests/2.31.0", "ua_requests"),
]:
    url = "https://push2.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Referer": "https://quote.eastmoney.com"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        results[label] = {"ok": True, "len": len(data)}
    except Exception as e:
        results[label] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}

out = json.dumps(results, ensure_ascii=False, indent=2)
outpath = os.path.join(os.path.dirname(__file__), "_diag_out.txt")
with open(outpath, "w", encoding="utf-8") as f:
    f.write(out)
print("Done")
