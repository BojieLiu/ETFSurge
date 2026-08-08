import sys, json, os
sys.stdout.reconfigure(encoding='utf-8')
# _etf_cache_file 的候选路径
import glob
for p in [r'data\etf_list_cache.json', r'backend\data\etf_list_cache.json']:
    if os.path.exists(p):
        st = os.stat(p)
        print(f'=== {p} ===  size={st.st_size}  mtime={os.path.getmtime(p)}')
        import datetime
        print('  mtime:', datetime.datetime.fromtimestamp(st.st_mtime))
        try:
            snap = json.load(open(p, encoding='utf-8'))
            etfs = snap.get('etfs', snap if isinstance(snap, list) else [])
            by = {str(e['symbol']): e for e in etfs if isinstance(e, dict) and e.get('symbol')}
            print('  entries:', len(by))
            for sym in ['510300','159338','510050','563020','562950','588000','589560','159915','562600','562870','518880']:
                e = by.get(sym, {})
                print(f'    {sym} {str(e.get("name",""))[:10]:<10} chg={e.get("change_pct")} price={e.get("price")}')
        except Exception as ex:
            print('  parse err', ex)