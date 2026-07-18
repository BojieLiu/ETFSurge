import requests
d = requests.get('http://127.0.0.1:8000/api/v1/portfolio/designs/57', timeout=10).json()
for s in d.get('strategies', []):
    lb = s.get('layer_budget', {})
    allocs = s.get('etfs') or s.get('allocations') or []
    core = sum(e.get('weight',0) for e in allocs if e.get('layer')=='core')
    sat = sum(e.get('weight',0) for e in allocs if e.get('layer')=='satellite')
    defence = sum(e.get('weight',0) for e in allocs if e.get('layer')=='defence' or e.get('layer')=='defense')
    cash = sum(e.get('weight',0) for e in allocs if e.get('symbol')=='CASH')
    print(s['label'] + ':')
    print('  budget:  core=' + str(round(lb.get('core',0)*100)) + '% sat=' + str(round(lb.get('satellite',0)*100)) + '% def=' + str(round(lb.get('defense',0)*100)) + '%')
    print('  actual:  core=' + str(round(core*100)) + '% sat=' + str(round(sat*100)) + '% def=' + str(round(defence*100)) + '% cash=' + str(round(cash*100)) + '%')
    print()
