import json

with open('prompt_results_all.json', encoding='utf-8') as f:
    data = json.load(f)

completed = [r for r in data if r.get('analysis', {}).get('total_etf_count', 0) > 0]
print(f'Total: {len(data)}')
print(f'Completed: {len([r for r in data if r.get("analysis", {}).get("total_etf_count", 0) > 0])}')
print(f'Failed: {len([r for r in data if r.get("analysis", {}).get("total_etf_count", 0) == 0])}')

if data:
    best = max([r for r in data if r.get('analysis', {}).get('total_etf_count', 0) > 0], 
               key=lambda r: (r['analysis']['total_etf_count'], -len(r['analysis'].get('warnings', [])), r.get('score', {}).get('total_score', 0)))
    print(f'Best: V{best["round"]} ({best["name"]}) - {best["analysis"]["total_etf_count"]} ETFs, score={best["score"].get("total_score", 0)}')