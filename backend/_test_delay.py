"""Test if push2delay can replace push2."""
import urllib.request, json, time

print("=" * 60)
print("TEST: Can push2delay replace push2?")
print("=" * 60)

# The EXACT failing URLs vs push2delay equivalents
pairs = [
    ("advance/decline (pz=10 test)",
     "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
     "https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"),
    ("ETF list (pz=10, all fields)",
     "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fs=m:1+t:2&fields=f12,f14,f2,f3,f62,f72,f184,f66,f45",
     "http://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fs=m:1+t:2&fields=f12,f14,f2,f3,f62,f72,f184,f66,f45"),
    ("big request (pz=5000, full market)",
     "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
     "https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"),
]

for label, old_url, new_url in pairs:
    print(f"\n--- {label} ---")

    for trial in range(2):
        t0 = time.time()
        req = urllib.request.Request(old_url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            n = len(data.get("data", {}).get("diff", []))
            print(f"  push2 [{trial+1}]:      OK {time.time()-t0:.2f}s ({n} items)")
        except Exception as e:
            print(f"  push2 [{trial+1}]:      FAIL {time.time()-t0:.1f}s - {type(e).__name__}")
        break  # only need 1 trial for push2 (it's consistently failing)

    for trial in range(3):
        t0 = time.time()
        req = urllib.request.Request(new_url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            n = len(data.get("data", {}).get("diff", []))
            total = data.get("data", {}).get("total", 0)
            print(f"  push2delay [{trial+1}]: OK {time.time()-t0:.2f}s ({n} items, total={total})")
        except Exception as e:
            print(f"  push2delay [{trial+1}]: FAIL {time.time()-t0:.1f}s - {type(e).__name__}")

print("\n" + "=" * 60)
print("CONCLUSION")
print("=" * 60)
