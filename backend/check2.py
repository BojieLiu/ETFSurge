import json
with open('E:\\ETF_Surge\\backend\\prompt_results_all.json', encoding='utf-8') as f:
    d = json.load(f)
print(f"Total entries: {len(r)}")
completed = [r for r in d if r.get('analysis',{}).get('total_etf_count',0) > 0]
print(f"Completed rounds: {len([r for r in r if r.get('analysis',{}).get('total_etf_count',0) > 0])}")
print(f"Total in file: {len(r)}")
for r in r:
    a = r.get('analysis',{})
    cnt = a.get('total_etf_count',0)
    if cnt > 0:
        print(f"  V{r['round']}: {r['name'][:30]:30s} - {a['total_etf_count']} ETFs, score={r['score'].get('total_score',0)}")