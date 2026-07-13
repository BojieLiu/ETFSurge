import json
with open('E:\\ETF_Surge\\backend\\prompt_results_all.json', encoding='utf-8') as f:
    d = json.load(f)
completed = {r['round'] for r in d if r.get('analysis',{}).get('total_etf_count',0) > 0}
all_rounds = set(range(1, 34))
remaining = set(range(1, 34)) - completed
print(f'Completed rounds: {sorted(completed)}')
print(f'Remaining: {sorted(set(range(1,34)) - completed)}')
print(f'Total done: {len([r for r in d if r.get("analysis",{}).get("total_etf_count",0) > 0])}')
print(f'Total in file: {len(d)}')