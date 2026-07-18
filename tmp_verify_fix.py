#!/usr/bin/env python3
import requests, time
BASE = "http://127.0.0.1:8000/api/v1"
sid = "verify_p5a_" + str(int(time.time()))
print("触发生成...")
r = requests.post(f"{BASE}/portfolio/design", params={"capital":500000,"mode":"standard","session_id":sid}, json={}, timeout=120)
if r.status_code != 200: print("FAIL"); exit(1)
d = r.json(); did = d.get("id"); regime = d.get("market_context",{}).get("market_regime")
print(f"设计#{did} regime={regime} strategies={len(d.get('strategies',[]))}套")
print("等待 50s..."); time.sleep(50)
detail = requests.get(f"{BASE}/portfolio/designs/{did}", timeout=10).json()
t = detail.get("design_text","")
print(f"has_text={bool(t)} len={len(t)}")
print(f"引擎表格={'✅' if '三、三种方案详解' in t else '❌'}")
print(f"LLM分析={'✅' if len(t)>500 else '❌'}")
print(f"卡片匹配={'✅' if '510300' in t else '❌'}")
print(t[:400] if t else "")
