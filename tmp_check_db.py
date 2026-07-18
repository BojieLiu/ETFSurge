import requests
did = 57
detail = requests.get('http://127.0.0.1:8000/api/v1/portfolio/designs/' + str(did), timeout=10).json()
t = detail.get('design_text','')
print('len:', len(t))
print('has_table:', '三种方案详解' in t)
print('has_analysis:', '市场' in t and '风险' in t)
print('has_codes:', '510300' in t and '518880' in t)
print(t[:300])
