# -*- coding: utf-8 -*-
"""抓取 no_data/warn 因子的完整字段（ic_value vs avg_ic）"""
import urllib.request, json

d = json.loads(
    urllib.request.urlopen("http://localhost:8000/api/v1/factors/active", timeout=30).read().decode()
)
for c in d.get("categories", []):
    for f in c.get("factors", []):
        if f.get("status") in ("no_data", "warn"):
            print(
                f"[{f['status']}] {f['name']} | ic_value={f.get('ic_value')} "
                f"avg_ic={f.get('avg_ic')} sample={f.get('sample_count')} "
                f"last_computed={f.get('last_computed_at')}"
            )
