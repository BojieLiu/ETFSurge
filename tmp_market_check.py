"""
临时脚本：获取报告涉及的ETF最新行情
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.fetchers.china_market import (
    fetch_a_stock_batch,
    fetch_index_realtime,
    fetch_a_stock_realtime,
)

print("=" * 60)
print("指数行情")
print("=" * 60)
for row in fetch_index_realtime():
    print(f"  {row.get('name','?')} ({row.get('code','?')}): "
          f"价格={row.get('price','?')}  涨跌幅={row.get('change_pct','?')}%")

print()
print("=" * 60)
print("ETF行情")
print("=" * 60)

etf_codes = ['510300', '560600', '510880', '512480', '561300',
             '515030', '512010', '159766', '512660', '588000', '518880']
etf_names = {
    '510300': '沪深300ETF', '560600': '中证A500ETF', '510880': '红利低波ETF',
    '512480': '半导体ETF', '561300': 'AI人工智能ETF', '515030': '新能源ETF',
    '512010': '医药ETF', '159766': '旅游ETF', '512660': '军工ETF',
    '588000': '科创50ETF', '518880': '黄金ETF',
}

for row in fetch_a_stock_batch(etf_codes):
    code = row.get('code', '?')
    name = etf_names.get(code, row.get('name', '?'))
    print(f"  {name} ({code}): "
          f"价格={row.get('price','?')}  涨跌幅={row.get('change_pct','?')}%  "
          f"昨收={row.get('prev_close','?')}")
