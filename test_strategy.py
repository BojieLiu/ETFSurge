import json, urllib.request

# Test 1: Portfolio design (generates 3 AI plans)
print("=== Test 1: Portfolio Design ===")
data = json.dumps({'capital': 100000}).encode()
req = urllib.request.Request('http://localhost:8000/api/v1/analysis/portfolio-design', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read().decode())
print('Keys:', list(result.keys()))
print('Has plans:', 'plans' in result)
if 'plans' in result:
    print('Plans count:', len(result['plans']))
    for p in result['plans']:
        print(f'  Style: {p.get("style_label")}, Allocations: {len(p.get("allocations", []))}')

# Test 2: Strategy check with design data
print("\n=== Test 2: Strategy Check with AI Design ===")
design_data = {
    "plans": [
        {
            "style": "进攻型",
            "style_label": "进攻型",
            "portfolio_name": "进攻型组合",
            "allocations": [
                {"symbol": "510050", "name": "华泰柏瑞沪深300ETF", "asset_class": "宽基", "target_weight": 0.15, "selection_rationale": "test", "weight_rationale": "test", "tracked_index": "000300", "key_metrics": {}},
                {"symbol": "159915", "name": "易方达创业板ETF", "asset_class": "宽基", "target_weight": 0.15, "selection_rationale": "test", "weight_rationale": "test", "tracked_index": "399006", "key_metrics": {}},
                {"symbol": "513100", "name": "纳指100ETF", "asset_class": "跨境", "target_weight": 0.10, "selection_rationale": "test", "weight_rationale": "test", "tracked_index": "NDX", "key_metrics": {}},
                {"symbol": "518880", "name": "黄金ETF", "asset_class": "商品", "target_weight": 0.05, "selection_rationale": "test", "weight_rationale": "test", "tracked_index": "AU9999", "key_metrics": {}},
            ]
        }
    ]
}

req_data = json.dumps({'total_capital': 100000, 'design_data': design_data}).encode()
req = urllib.request.Request('http://localhost:8000/api/v1/portfolio/strategy-check', data=req_data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read().decode())
print('Keys:', list(result.keys()))
print('Summary:', result.get('summary', '')[:80])
print('Suggestions count:', len(result.get('suggestions', [])))