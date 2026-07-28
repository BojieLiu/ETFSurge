"""Test HTTP vs HTTPS for push2."""
import urllib.request, time

tests = [
    # The ETF scanner uses HTTP (port 80), not HTTPS
    ("push2 HTTP (used by ETF scanner)", "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fs=m:1+t:2&fields=f12,f14,f2,f3"),
    # The fetch_advance_decline_ratio uses HTTPS
    ("push2 HTTPS (used by adv/decl)", "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6"),
    # push2his and push2delay with different paths
    ("push2his HTTPS (fund flow)", "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?secid=1.000001"),
    ("push2delay HTTPS (ETF spot)", "https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fields=f2,f3,f4&fs=m:1+t:2"),
    # Sina with proper referer
    ("Sina HQ with Referer", "https://hq.sinajs.cn/list=s_sh000001"),
]
for label, url in tests:
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data_len = len(resp.read())
        print(f"[OK]   {label}: {time.time()-t0:.2f}s ({data_len} bytes)")
    except Exception as e:
        print(f"[FAIL] {label}: {time.time()-t0:.1f}s {type(e).__name__}")

print()
print("KEY INSIGHT:")
print("push2 HTTPS = BLOCKED, but push2 HTTP (used by ETF scanner) and")
print("push2his/push2delay (used by fund flow / spot) all WORK")
print("So the problem is specifically push2.eastmoney.com HTTPS")
