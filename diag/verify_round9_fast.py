# -*- coding: utf-8 -*-
"""round9 验收快路径：watchlist 耗时 / 因子状态 / timeline orphan / market_regime / 新闻分级"""
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000/api/v1"


def get(path, timeout=30):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", errors="replace")
        return r.status, body, time.time() - t0


def post(path, payload, timeout=60):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace"), time.time() - t0


# 1) P0-4: watchlist 耗时（冷缓存第一发）
st, body, el = get("/market/watchlist")
print(f"[P0-4] watchlist {st} {el:.2f}s")
try:
    items = json.loads(body).get("items", [])
    print(f"       items={len(items)} realtime_cover={(sum(1 for i in items if i.get('realtime')))}")
except Exception as e:
    print("       parse err:", str(e)[:100])

# 2) P1-3/P1-10: factors/active sentiment 三因子 static + 无负IC valid
st, body, el = get("/factors/active")
data = json.loads(body)
fmap = {f["code"]: f for f in data.get("factors", [])}
for code in ("sentiment.panic_greed_diff", "sentiment.stock_divergence", "sentiment.news_direction"):
    f = fmap.get(code, {})
    print(f"[P1-10] {code}: status={f.get('status')} reason={str(f.get('reason'))[:50]}")
contra = [f["code"] for f in data.get("factors", [])
          if f.get("ic_value") is not None and f["ic_value"] < 0 and f.get("status") == "valid"]
print(f"[P1-3] 负IC标valid矛盾项: {contra if contra else '无'}")

# 3) P2-11: timeline orphan 字段
st, body, el = get("/portfolio/timeline?limit=30")
tl = json.loads(body)
checks = [i for i in tl.get("items", []) if i.get("_type") == "check"]
orphans = [i for i in checks if i.get("orphan")]
print(f"[P2-11] timeline check={len(checks)} orphan={len(orphans)}")

# 4) P1-6: design 详情顶层 market_regime
st, body, el = get("/portfolio/designs?limit=1")
rows = json.loads(body)
if rows:
    did = rows[0]["id"]
    st2, body2, el2 = get(f"/portfolio/designs/{did}")
    d = json.loads(body2)
    print(f"[P1-6] design {did} 顶层 market_regime={d.get('market_regime')} ctx.regime={ (d.get('market_context') or {}).get('market_regime') }")
    print(f"[P0-9] ctx.data_fetched_at={ (d.get('market_context') or {}).get('data_fetched_at') }")
else:
    print("[P1-6] 无设计记录")

# 5) P2-1: 新闻分级分布（level/stars 独立性）
st, body, el = get("/news/headlines?limit=30")
try:
    news = json.loads(body)
    if isinstance(news, dict):
        news = news.get("items", [])
    from collections import Counter
    lv = Counter(n.get("level") for n in news)
    st2 = Counter(n.get("stars") for n in news)
    print(f"[P2-1] 头条 level 分布={dict(lv)} stars 分布={dict(st2)}")
    same = sum(1 for n in news if n.get("level") == n.get("stars"))
    print(f"       level==stars 同分布条数: {same}/{len(news)}（应 < 全部）")
except Exception as e:
    print("[P2-1] 新闻端点异常:", str(e)[:100])
