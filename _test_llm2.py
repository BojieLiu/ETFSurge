"""Test LLM providers without Unicode emojis."""
import requests, json, sys, time

# Read .env
env = {}
for line in open('backend/.env', encoding='utf-8'):
    line = line.strip()
    if line and '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"')

print("=" * 60)
print("LLM Provider Connectivity Tests")
print("=" * 60)

# Test 1: OpenCode Zen
print("\n--- Test 1: OpenCode Zen (simple ping) ---")
oc_key = env.get('OPENCODE_ZEN_API_KEY', '')
oc_url = env.get('OPENCODE_ZEN_API_URL', 'https://opencode.ai/zen/v1/chat/completions')
oc_model = env.get('OPENCODE_ZEN_MODEL', 'deepseek-v4-flash-free')

t0 = time.time()
try:
    r = requests.post(oc_url, json={
        'model': oc_model,
        'messages': [{'role': 'user', 'content': 'Return only: OK'}],
        'max_tokens': 5,
        'temperature': 0
    }, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {oc_key}'
    }, timeout=30)
    elapsed = time.time() - t0
    print(f"  HTTP {r.status_code} in {elapsed:.1f}s")
    if r.status_code == 200:
        data = r.json()
        print(f"  Full response: {json.dumps(data, ensure_ascii=False)[:300]}")
    else:
        print(f"  Body: {r.text[:200]}")
except Exception as e:
    elapsed = time.time() - t0
    print(f"  ERROR: {type(e).__name__}: {e} ({elapsed:.1f}s)")

# Test 2: OpenCode Zen - full prompt (strategy check style)
print("\n--- Test 2: OpenCode Zen (strategy check style) ---")
t0 = time.time()
try:
    r = requests.post(oc_url, json={
        'model': oc_model,
        'messages': [
            {'role': 'system', 'content': 'You are a financial analyst. Respond in JSON format.'},
            {'role': 'user', 'content': 'Analyze: market is range_bound, 10 holdings, total factor score 0.3. Return {"summary":"brief","risk":"low"}'}
        ],
        'max_tokens': 200,
        'temperature': 0.1,
        'response_format': {'type': 'json_object'}
    }, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {oc_key}'
    }, timeout=60)
    elapsed = time.time() - t0
    print(f"  HTTP {r.status_code} in {elapsed:.1f}s")
    if r.status_code == 200:
        data = r.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        finish_reason = data.get('choices', [{}])[0].get('finish_reason', '')
        print(f"  Finish reason: {finish_reason}")
        print(f"  Content: {content[:300]}")
    else:
        print(f"  Body: {r.text[:300]}")
except Exception as e:
    elapsed = time.time() - t0
    print(f"  ERROR: {type(e).__name__}: {e} ({elapsed:.1f}s)")

# Test 3: DeepSeek Official
print("\n--- Test 3: DeepSeek Official ---")
ds_key = env.get('DEEPSEEK_API_KEY', '')
ds_url = "https://api.deepseek.com/chat/completions"

if ds_key:
    t0 = time.time()
    try:
        r = requests.post(ds_url, json={
            'model': 'deepseek-v4-flash',
            'messages': [{'role': 'user', 'content': 'Return only: OK'}],
            'max_tokens': 5,
            'temperature': 0
        }, headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {ds_key}'
        }, timeout=30)
        elapsed = time.time() - t0
        print(f"  HTTP {r.status_code} in {elapsed:.1f}s")
        if r.status_code == 200:
            data = r.json()
            print(f"  Full response: {json.dumps(data, ensure_ascii=False)[:300]}")
        else:
            print(f"  Body: {r.text[:200]}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR: {type(e).__name__}: {e} ({elapsed:.1f}s)")
else:
    print("  SKIPPED - no API key")

# Test 4: OpenCode Zen - long timeout test (match what backend uses)
print("\n--- Test 4: OpenCode Zen (long timeout, 90s) ---")
t0 = time.time()
try:
    r = requests.post(oc_url, json={
        'model': oc_model,
        'messages': [
            {'role': 'system', 'content': 'You are a professional financial analyst. Provide a detailed market analysis.'},
            {'role': 'user', 'content': 'Analyze current A-share market with ETF portfolio of 10 holdings. Market regime is range_bound with neutral sentiment (index 45). Provide analysis of risk and opportunities.'}
        ],
        'max_tokens': 1000,
        'temperature': 0.7
    }, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {oc_key}'
    }, timeout=95)
    elapsed = time.time() - t0
    print(f"  HTTP {r.status_code} in {elapsed:.1f}s")
    if r.status_code == 200:
        data = r.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        print(f"  Content length: {len(content)}")
        print(f"  Content preview: {content[:200]}")
        print(f"  Usage: {data.get('usage', {})}")
except Exception as e:
    elapsed = time.time() - t0
    print(f"  ERROR: {type(e).__name__}: {e} ({elapsed:.1f}s)")

print()
print("=" * 60)
print("ALL TESTS COMPLETE")
