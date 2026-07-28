"""Test akshare fallback from inside Docker."""
import time, urllib.request, json, sys

print("=" * 60)
print("TEST 1: push2 HTTPS")
t0 = time.time()
try:
    req = urllib.request.Request(
        "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fields=f2,f3,f4&fs=m:0+t:6",
        headers={"User-Agent": "Mozilla/5.0"}
    )
    resp = urllib.request.urlopen(req, timeout=15)
    print(f"  OK: {time.time()-t0:.2f}s")
except Exception as e:
    print(f"  FAIL: {time.time()-t0:.1f}s - {type(e).__name__}")

print()
print("TEST 2: Sina (working fallback)")
t0 = time.time()
try:
    req = urllib.request.Request(
        "https://hq.sinajs.cn/list=s_sh000001",
        headers={"Referer": "https://finance.sina.com.cn"}
    )
    resp = urllib.request.urlopen(req, timeout=10)
    print(f"  OK: {time.time()-t0:.2f}s")
except Exception as e:
    print(f"  FAIL: {time.time()-t0:.1f}s - {type(e).__name__}")

print()
print("TEST 3: akshare stock_zh_a_spot_em (the advance_decline fallback)")
t0 = time.time()
try:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    print(f"  OK: {time.time()-t0:.2f}s, {len(df)} rows")
    if len(df) > 0:
        cols = list(df.columns)
        print(f"  Columns: {cols[:6]}")
except Exception as e:
    print(f"  FAIL: {time.time()-t0:.1f}s - {type(e).__name__}: {str(e)[:100]}")

print()
print("TEST 4: akshare stock_margin_szse_sz (margin_change fallback)")
t0 = time.time()
try:
    import akshare as ak
    df = ak.stock_margin_szse_sz()
    print(f"  OK: {time.time()-t0:.2f}s, {len(df)} rows")
except Exception as e:
    print(f"  FAIL: {time.time()-t0:.1f}s - {type(e).__name__}: {str(e)[:100]}")

print()
print("TEST 5: akshare north flow")
t0 = time.time()
try:
    import akshare as ak
    # Try multiple func names as in the code
    for fn in ["stock_hsgt_north_net_flow_in_em", "stock_hsgt_north_flow_in_em"]:
        func = getattr(ak, fn, None)
        if func:
            df = func(symbol="北上")
            if df is not None and len(df) > 0:
                print(f"  [{fn}] OK: {time.time()-t0:.2f}s, {len(df)} rows")
                break
            else:
                print(f"  [{fn}] empty: {time.time()-t0:.2f}s")
    else:
        print(f"  All north flow funcs failed: {time.time()-t0:.2f}s")
except Exception as e:
    print(f"  FAIL: {time.time()-t0:.1f}s - {type(e).__name__}: {str(e)[:100]}")

print()
print("TEST 6: akshare fund_etf_category_sina (used in ETF scan)")
t0 = time.time()
try:
    import akshare as ak
    df = ak.fund_etf_category_sina(symbol="ETF基金")
    print(f"  OK: {time.time()-t0:.2f}s, {len(df)} rows")
except Exception as e:
    print(f"  FAIL: {time.time()-t0:.1f}s - {type(e).__name__}: {str(e)[:100]}")

print(f"\nTotal test time: {time.time()-sys.modules['__main__'].__dict__.get('_start', time.time()):.1f}s")
_start = time.time()
