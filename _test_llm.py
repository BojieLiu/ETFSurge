"""Test LLM provider connectivity directly."""
import requests, json, time, sys

def test_provider(name, url, api_key, model, timeout=15):
    print(f"\n--- Testing {name} ---")
    print(f"  URL: {url}")
    print(f"  Model: {model}")
    print(f"  Timeout: {timeout}s")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Say 'hello' in one word only."}
        ],
        "max_tokens": 10,
        "temperature": 0
    }
    
    start = time.time()
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        elapsed = time.time() - start
        print(f"  HTTP {r.status_code} in {elapsed:.1f}s")
        
        if r.status_code == 200:
            data = r.json()
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            print(f"  Response: {content[:100]}")
            print(f"  ✅ CONNECTED")
            return True
        else:
            print(f"  Response: {r.text[:200]}")
            print(f"  ❌ FAILED (HTTP {r.status_code})")
            return False
    except requests.Timeout:
        elapsed = time.time() - start
        print(f"  ❌ TIMEOUT after {elapsed:.1f}s")
        return False
    except Exception as e:
        elapsed = time.time() - start
        print(f"  ❌ ERROR: {type(e).__name__}: {str(e)[:100]} ({elapsed:.1f}s)")
        return False

# Read API keys from .env
import os
from pathlib import Path
env_path = Path('backend/.env')
env_vars = {}
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env_vars[k.strip()] = v.strip()

# Test OpenCode Zen
oc_key = env_vars.get('OPENCODE_ZEN_API_KEY', '')
oc_url = env_vars.get('OPENCODE_ZEN_API_URL', 'https://opencode.ai/zen/v1/chat/completions')
oc_model = env_vars.get('OPENCODE_ZEN_MODEL', 'deepseek-v4-flash-free')

# Test DeepSeek
ds_key = env_vars.get('DEEPSEEK_API_KEY', '')
ds_url = "https://api.deepseek.com/chat/completions"
ds_model = "deepseek-v4-flash"

print("=" * 60)
print("LLM Provider Connectivity Test (from host)")
print("=" * 60)

results = []
if oc_key:
    ok = test_provider("OpenCode Zen", oc_url, oc_key, oc_model)
    results.append(("OpenCode Zen", ok))
else:
    print("\n--- OpenCode Zen ---")
    print("  ❌ SKIPPED - no API key configured")
    results.append(("OpenCode Zen", False))

if ds_key:
    ok = test_provider("DeepSeek Official", ds_url, ds_key, ds_model)
    results.append(("DeepSeek", ok))
else:
    print("\n--- DeepSeek Official ---")
    print("  ❌ SKIPPED - no API key configured")
    results.append(("DeepSeek", False))

print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
for name, ok in results:
    print(f"  {'✅' if ok else '❌'} {name}")
