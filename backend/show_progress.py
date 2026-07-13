import json
with open('prompt_results_all.json', encoding='utf-8') as f:
    data = json.load(f)
completed = [r for r in data if r.get('analysis',{}).get('total_etf_count',0) > 0]
print(f'Total entries: {len(data)}')
print(f'Completed: {len([r for r in data if r.get(\"analysis\",{}).get(\"total_etf_count\",0) > 0])}')
for r in data:
    a = r.get('analysis',{})
    if a.get('total_etf_count',0) > 0:
        print(f"  V{r['round']}: {r['name'][:20]} - {a['total_etf_count']} ETFs")