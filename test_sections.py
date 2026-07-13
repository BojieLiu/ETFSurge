with open('E:/ETF_Surge/frontend/src/components/MarketAnalysis.vue', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if '<section' in line or '</section>' in line:
        print(f'{i+1}: {line.strip()}')