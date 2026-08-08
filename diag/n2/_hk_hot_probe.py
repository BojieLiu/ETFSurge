import sys
sys.stdout.reconfigure(encoding='utf-8')
from app.fetchers.hk_hot_fetcher import _fetch_hk_rows, parse_hk_plates, parse_hk_hot_stocks
rows = _fetch_hk_rows()
print('rows:', len(rows))
# 检查 f100 为空/空白的行
empty_f100 = [r.get('f12') for r in rows if not (r.get('f100') or '').strip()]
print('rows with empty f100:', len(empty_f100), empty_f100[:20])
# 含全角空格等特殊空白
import re
weird = [(r.get('f12'), repr(r.get('f100'))) for r in rows if isinstance(r.get('f100'), str) and ('\u3000' in r.get('f100') or '\xa0' in r.get('f100') or '\u200b' in r.get('f100'))]
print('rows with unicode-space f100:', len(weird), weird[:10])
plates = parse_hk_plates(rows)
print('plates:', len(plates))
for p in plates[:5]:
    print('  plate name=%r chg=%s amt=%s n=%s' % (p['name'], p['change_pct'], p['amount'], p['stock_count']))
stocks = parse_hk_hot_stocks(rows, 20)
print('top stock:', {k: stocks[0].get(k) for k in ('symbol','name','price','change_pct','industry')})