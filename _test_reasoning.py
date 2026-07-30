"""Test if we can disable/shutdown reasoning in DeepSeek model calls."""
import requests, json, time

env = {}
for line in open('backend/.env', encoding='utf-8'):
    line = line.strip()
    if line and '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"')

oc_key = env.get('OPENCODE_ZEN_API_KEY', '')
oc_url = env.get('OPENCODE_ZEN_API_URL', 'https://opencode.ai/zen/v1/chat/completions')

def test(label, body, timeout=30):
    t0 = time.time()
    try:
        r = requests.post(oc_url, json=body, headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {oc_key}'
        }, timeout=timeout)
        elapsed = time.time() - t0
        print(f"  {elapsed:.1f}s HTTP {r.status_code}", end="")
        if r.status_code == 200:
            data = r.json()
            msg = data['choices'][0]['message']
            content = msg.get('content', '') or ''
            reasoning = msg.get('reasoning_content', '') or ''
            usage = data.get('usage', {})
            finish = data['choices'][0].get('finish_reason', '?')
            print(f" finish={finish} content_len={len(content)} reasoning_len={len(reasoning)}")
            print(f"    usage: {json.dumps(usage)}")
            if content:
                print(f"    content[:100]: {content[:100]}")
        else:
            print(f"  body: {r.text[:200]}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR: {type(e).__name__}: {e} ({elapsed:.1f}s)")

print("=" * 60)
print("Test: Reasoning control in DeepSeek model calls")
print("=" * 60)

base = {
    'messages': [{'role': 'user', 'content': 'Write a brief market summary: market is range_bound, sentiment neutral at 45. Keep it under 50 words.'}],
    'temperature': 0.1,
}

# Test 1: Current settings (max_tokens=8192, no reasoning params)
print("\n--- Test 1: max_tokens=8192, default ---")
body = dict(base, model='deepseek-v4-flash-free', max_tokens=8192)
test("8192 default", body)

# Test 2: Large max_tokens (16384)
print("\n--- Test 2: max_tokens=16384 ---")
body = dict(base, model='deepseek-v4-flash-free', max_tokens=16384)
test("16384", body)

# Test 3: Try reasoning_effort=none (OpenAI-style param)
print("\n--- Test 3: reasoning_effort=none ---")
body = dict(base, model='deepseek-v4-flash-free', max_tokens=8192, reasoning_effort='none')
test("reasoning_effort=none", body)

# Test 4: Try low reasoning effort
print("\n--- Test 4: reasoning_effort=low ---")
body = dict(base, model='deepseek-v4-flash-free', max_tokens=8192, reasoning_effort='low')
test("reasoning_effort=low", body)

# Test 5: Very large max_tokens (32768)
print("\n--- Test 5: max_tokens=32768 ---")
body = dict(base, model='deepseek-v4-flash-free', max_tokens=32768)
test("32768", body)

# Test 6: Try without max_tokens at all
print("\n--- Test 6: no max_tokens limit (model default) ---")
body = dict(base, model='deepseek-v4-flash-free')
test("no max_tokens", body)

print("\n" + "=" * 60)
print("ALL TESTS COMPLETE")
