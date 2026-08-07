# -*- coding: utf-8 -*-
"""验证候选锚代码行情可用性（159338 vs 560600）"""
import urllib.request


def probe(name, url, headers):
    try:
        req = urllib.request.Request(url, headers=headers)
        r = urllib.request.urlopen(req, timeout=6)
        body = r.read().decode("utf-8", errors="replace")
        return f"OK head={body[:100]!r}"
    except Exception as e:
        return f"FAIL {type(e).__name__}: {e}"


for code in ("159338", "563650", "560510"):
    print(f"[{code}]")
    print("  QQ:", probe("qq", f"http://qt.gtimg.cn/q=sz{code}" if code.startswith(("0", "1", "3")) else f"http://qt.gtimg.cn/q=sh{code}", {"User-Agent": "Mozilla/5.0"}))
