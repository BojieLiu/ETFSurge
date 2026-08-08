import sys, json
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open(r'diag\n2\design_detail_456.json', encoding='utf-8'))
rt = json.load(open(r'diag\n2\realtime_batch_456.json', encoding='utf-8'))
rt_map = {}
for it in rt:
    rt_map[str(it.get('symbol'))] = it
print(f"{'sym':<8}{'name':<14}{'daily_chg':>9}{'fb_chg':>9}{'rt_price':>10}{'rt_chg':>9}")
for s in d['strategies']:
    print(f"--- {s.get('name')} ({len(s.get('etfs', []))}只) ---")
    for e in s.get('etfs', []):
        sym = e.get('symbol')
        daily = e.get('daily_change_pct')
        fb = (e.get('factor_breakdown') or {}).get('etf', {})
        fbchg = fb.get('change_pct')
        r = rt_map.get(str(sym), {})
        print(f"{sym:<8}{str(e.get('name',''))[:12]:<14}{daily if daily is not None else '':>9}{fbchg if fbchg is not None else '':>9}{r.get('price','')!s:>10}{r.get('change_pct','')!s:>9}")