# -*- coding: utf-8 -*-
"""实测 sector-analysis/stream 与 symbol-analysis/stream（AI 按钮路径）"""
import json, urllib.request

BASE = "http://localhost:8000/api/v1"


def stream_post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=90)
        body = r.read().decode("utf-8", errors="replace")
        return r.status, body
    except Exception as e:
        return "ERR", f"{type(e).__name__}: {e}"


# sector 模式（heat tab 板块行 AI 按钮）
st, body = stream_post("/analysis/sector-analysis/stream", {"sector_type": "industry", "name": "医药"})
print("[sector] status=", st, "len=", len(body))
print("  head:", body[:150].replace("\n", " "))
print("  STREAM_ERROR?", "STREAM_ERROR" in body, "| full_text?", "full_text" in body)

# symbol 模式（symbol tab 行 AI 按钮）—— O24 回归路径
st2, body2 = stream_post("/analysis/symbol-analysis/stream", {"symbol": "600519", "market": "A"})
print("\n[symbol] status=", st2, "len=", len(body2))
print("  head:", body2[:200].replace("\n", " "))
print("  STREAM_ERROR?", "STREAM_ERROR" in body2, "| full_text?", "full_text" in body2)
