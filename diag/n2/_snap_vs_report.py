import sys, json
sys.stdout.reconfigure(encoding='utf-8')
snap = json.load(open(r'backend\data\etf_list_cache.json', encoding='utf-8'))
etfs = snap.get('etfs', snap if isinstance(snap, list) else [])
print('snapshot entries:', len(etfs))
by_sym = {}
for e in etfs:
    if isinstance(e, dict) and e.get('symbol'):
        by_sym[str(e['symbol'])] = e
d = json.load(open(r'diag\n2\design_detail_456.json', encoding='utf-8'))
rt = json.load(open(r'diag\n2\realtime_batch_456.json', encoding='utf-8'))
rt_map = {str(it.get('symbol')): it for it in rt}
# 三套方案的 daily_change_pct（取第一出现）
daily = {}
for s in d['strategies']:
    for e in s.get('etfs', []):
        if e.get('symbol') != 'CASH' and e.get('symbol') not in daily:
            daily[e['symbol']] = e.get('daily_change_pct')
print(f"{'sym':<8}{'name':<14}{'report_daily':>12}{'snap_chg':>10}{'snap_time':>10}{'rt_chg':>8}")
for sym, rp in daily.items():
    e = by_sym.get(sym, {})
    snap_chg = e.get('change_pct')
    snap_mtime = e.get('fetched_at') or e.get('timestamp') or e.get('ts')
    r = rt_map.get(sym, {})
    print(f"{sym:<8}{str(e.get('name',''))[:12]:<14}{rp if rp is not None else '':>10}{snap_chg if snap_chg is not None else '-':>10}{str(snap_mtime)[:8] if snap_mtime else '-':>10}{r.get('change_pct','-')!s:>10}")