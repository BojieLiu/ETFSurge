import json, sys
sys.stdout.reconfigure(encoding='utf-8')
data = json.load(open(r'diag\n2\realtime_batch_456.json', encoding='utf-8'))
print('items:', len(data))
report_chg = {
    '510300': '+1.13%', '159338': '+1.76%', '510050': '-0.23%', '563020': '-2.01%',
    '562870': '-0.43%', '518880': '-0.11%', '511090': '+0.14%', '510500': '+2.44%',
    '562000': '+1.67%', '562600': '+0.00%', '562990': '-0.31%', '562950': '+5.67%',
    '589720': '+3.27%', '589420': '+4.49%', '159915': '+5.68%', '588000': '+4.28%',
    '589560': '+4.64%', '589960': '+1.82%',
}
for it in data:
    sym = str(it.get('symbol'))
    if sym in report_chg:
        rep = float(report_chg[sym].replace('%', '').replace('+', ''))
        cur = it.get('change_pct')
        match = cur is not None and abs(float(cur) - rep) < 0.6
        print('%s %-8s current=%s%% report=%s MATCH=%s' % (sym, it.get('name'), cur, report_chg[sym], match))