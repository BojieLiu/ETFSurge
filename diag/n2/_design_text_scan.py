import sys, json, re
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open(r'diag\n2\design_detail_456.json', encoding='utf-8'))
dt = d.get('design_text') or ''
print('design_text length:', len(dt))
# 找所有 "涨X.XX%" "跌X.XX%" "X.XX%" 出现处（正文里的涨跌幅）
print('=== 涨/跌 百分比片段 ===')
for m in re.finditer(r'[涨跌]?[\d.]+%', dt):
    pass
# 单独打印含"消费电子"的段落
for kw in ['消费电子', '科创50ETF', '科创人工智能', '科创芯片', '科创创新药', '创业板', '上证指数', '红利低波', '科技成长', '最强主线']:
    idx = dt.find(kw)
    if idx >= 0:
        seg = dt[max(0,idx-30):idx+40].replace('\n',' ')
        print(f'  [{kw}] ...{seg}...')
# 统计正文所有百分比格式，看有没有非两位小数的
nums = re.findall(r'[+-]?\d+\.\d+%', dt)
print('\n=== 所有含小数的百分比 ===')
print(len(nums), '个；两位小数:', sum(1 for n in nums if re.match(r'[+-]?\d+\.\d{2}%$', n)), '；非两位:', sum(1 for n in nums if not re.match(r'[+-]?\d+\.\d{2}%$', n)))
from collections import Counter
c = Counter(nums)
for n, cnt in c.most_common(30):
    print(' ', n, 'x', cnt)