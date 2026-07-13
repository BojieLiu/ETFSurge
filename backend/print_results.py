import json

with open('prompt_results_all.json', encoding='utf-8') as f:
    data = json.load(f)

for r in data:
    if r.get('analysis', {}).get('total_etf_count', 0) > 0:
        a = r['analysis']
        print(f'V{r["round"]}: {r["name"]} - {a["total_etf_count"]} ETFs, score={r["score"].get("total_score",0)}, warns={len(a.get("warnings",[]))}')