import json
with open('prompt_results_all.json', encoding='utf-8') as f:
    data = json.load(f)
done = [r for r in data if r.get('analysis',{}).get('total_etf_count',0) > 0]
failed = [r for r in data if r.get('analysis',{}).get('total_etf_count',0) == 0]
done_rounds = sorted([r['round'] for r in done])
failed_rounds = sorted([r['round'] for r in failed])
print(f'Total: {len(data)}')
print(f'Completed: {len(done)} rounds: {done_rounds}')
print(f'Failed: {len(failed)} rounds: {failed_rounds}')
print()
print('Top 5 by ETF count:')
for r in sorted(done, key=lambda x: -x['analysis']['total_etf_count'])[:5]:
    a = r['analysis']
    print(f"  V{r['round']}: {r['name'][:25]:25s} - {a['total_etf_count']} ETFs, warns={len(a.get('warnings',[]))}, score={r.get('score',{}).get('total_score','N/A')}")