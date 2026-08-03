"""Trading-hours connectivity test: push2 vs push2delay (EastMoney)."""
import urllib.request, json, time, ssl

CLIST = ("/api/qt/clist/get?pn=1&pz=5&po=1&np=1"
         "&fields=f2,f3,f4,f12,f14&fs=m:1+t:2")
STOCK = "/api/qt/stock/get?secid=1.600519&fields=f43,f57,f58"

tests = [
    ("push2      HTTPS", f"https://push2.eastmoney.com{CLIST}"),
    ("push2      HTTP ", f"http://push2.eastmoney.com{CLIST}"),
    ("push2delay HTTPS", f"https://push2delay.eastmoney.com{CLIST}"),
    ("push2delay HTTP ", f"http://push2delay.eastmoney.com{CLIST}"),
    ("push2      HTTPS stock/get", f"https://push2.eastmoney.com{STOCK}"),
    ("push2delay HTTPS stock/get", f"https://push2delay.eastmoney.com{STOCK}"),
]

ctx = ssl.create_default_context()
print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S %A')} (交易时段)")
print("=" * 72)
for label, url in tests:
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        data = body.get("data") or {}
        if "diff" in data:
            n = len(data["diff"] or [])
            total = data.get("total")
            priced = sum(1 for d in (data["diff"] or []) if (d.get("f2") or 0) > 0)
            detail = f"{n}条(有价{priced})/total={total}"
        else:
            detail = f"f43现价={data.get('f43')}, f58名称={data.get('f58')}"
        print(f"  {label}: OK {time.time()-t0:.2f}s {detail}")
    except Exception as e:
        print(f"  {label}: FAIL {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:60]}")
print("=" * 72)
