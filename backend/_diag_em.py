#!/usr/bin/env python3
"""Diagnose EM (East Money) connectivity issue layer by layer."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
os.environ["DEEPSEEK_API_KEY"] = "sk-test"

results = {}
import urllib.request, socket

# 1. DNS resolution
print("1. DNS...")
try:
    ip = socket.getaddrinfo("push2.eastmoney.com", 443)
    results["dns"] = {"ok": True, "ips": list(set(a[4][0] for a in ip))}
except Exception as e:
    results["dns"] = {"ok": False, "error": str(e)[:80]}

# 2. TCP connectivity (port 443)
print("2. TCP...")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(("push2.eastmoney.com", 443))
    s.close()
    results["tcp"] = {"ok": True}
except Exception as e:
    results["tcp"] = {"ok": False, "error": str(e)[:80]}

# 3. HTTP GET to push2 API with urllib (no akshare)
print("3. HTTP GET to EM push2 API...")
for test_url, label in [
    ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=100.N225&fields=f43,f58,f170", "push2_ulist"),
    ("https://push2.eastmoney.com/api/qt/stock/get?secid=100.N225&fields=f43,f58,f170", "push2_stock"),
]:
    try:
        req = urllib.request.Request(test_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rc = data.get("rc")
        d = data.get("data")
        results[label] = {"ok": True, "rc": rc, "has_data": bool(d), "status": resp.status}
        if d and d.get("diff") if isinstance(d, dict) else None:
            results[label]["items"] = len(d.get("diff", []))
    except Exception as e:
        results[label] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:100]}"}

# 4. Test with and without no_proxy for akshare
print("4. akshare EM with/without no_proxy...")
from app.utils.proxy import no_proxy
import akshare as ak

# Without no_proxy
try:
    df = ak.index_global_spot_em()
    results["akshare_no_proxy"] = {"ok": bool(df is not None and not df.empty), "rows": len(df) if df is not None else 0}
except Exception as e:
    results["akshare_no_proxy"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:100]}"}

# With no_proxy
try:
    with no_proxy():
        df = ak.index_global_spot_em()
    results["akshare_with_no_proxy"] = {"ok": bool(df is not None and not df.empty), "rows": len(df) if df is not None else 0}
except Exception as e:
    results["akshare_with_no_proxy"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:100]}"}

# 5. Test no_proxy helper
print("5. Testing no_proxy context...")
try:
    import urllib.request as ur
    with no_proxy():
        handler = ur.build_opener()
        results["no_proxy_test"] = {"ok": True, "handlers": [str(h)[:40] for h in handler.handlers]}
except Exception as e:
    results["no_proxy_test"] = {"error": str(e)[:80]}

out = json.dumps(results, ensure_ascii=False, indent=2)
outpath = os.path.join(os.path.dirname(__file__), "_diag_out.txt")
with open(outpath, "w", encoding="utf-8") as f:
    f.write(out)
print("Done")
