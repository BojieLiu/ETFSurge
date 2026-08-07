# -*- coding: utf-8 -*-
"""第3步：A股/港股/美股行情分析全功能测试（综合研判/AI投顾/个股/ETF/板块/概念/指数/搜索补全）"""
import json
import os
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)


def api_get(path, t=60):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=t)
        return json.loads(r.read().decode())
    except Exception as e:
        return {"__err__": str(e)}


def api_post(path, data, t=60):
    body = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=t)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err__": "HTTP %s: %s" % (e.code, e.read().decode()[:300])}
    except Exception as e:
        return {"__err__": str(e)}


def sse_post(path, data, t=180):
    """POST SSE 流，收集所有 event 行直到 done/超时"""
    body = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"})
    events = []
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=t)
        buf = b""
        while time.time() - t0 < t:
            chunk = resp.read(1024)
            if not chunk:
                break
            buf += chunk
            text = buf.decode("utf-8", "replace")
            buf = b""
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("data:"):
                    events.append(line[5:].strip())
    except Exception as e:
        events.append("__SSE_ERR__: %s" % repr(e))
    return events


def run(name, path, data=None, kind="post", t=60):
    print("=== %s ===" % name, flush=True)
    if kind == "post":
        r = api_post(path, data, t)
    elif kind == "sse":
        r = sse_post(path, data, t)
        with open(os.path.join(OUT, name.replace("/", "_") + ".sse.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print("  SSE events:", len(r), "| last:", (r[-1] if r else "EMPTY")[:200], flush=True)
        return r
    else:
        r = api_get(path, t)
    with open(os.path.join(OUT, name.replace("/", "_") + ".json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    if "__err__" in r:
        print("  FAIL:", r["__err__"][:200], flush=True)
    else:
        print("  OK, keys:", list(r.keys())[:12], flush=True)
    return r


def main():
    # 0) 取真实板块代码
    ind = api_get("/api/v1/market/sectors/industry", t=90)
    sector_code = sector_name = None
    if isinstance(ind, list) and ind:
        sector_code = ind[0].get("sector_code")
        sector_name = ind[0].get("sector_name")
    con = api_get("/api/v1/market/sectors/concept", t=90)
    concept_code = concept_name = None
    if isinstance(con, list) and con:
        concept_code = con[0].get("sector_code")
        concept_name = con[0].get("sector_name")
    print("sector:", sector_code, sector_name, "| concept:", concept_code, concept_name, flush=True)

    # 1) 综合研判（A股）
    run("llm-report-A", "/api/v1/analysis/llm-report", {"market": "A"}, "post", 120)
    run("llm-report-HK", "/api/v1/analysis/llm-report", {"market": "HK"}, "post", 120)
    run("llm-report-US", "/api/v1/analysis/llm-report", {"market": "US"}, "post", 120)
    # 2) AI 投顾问答
    run("llm-advice-A", "/api/v1/analysis/llm-advice",
        {"query": "当前A股市场行情如何？应该如何配置资产？", "market": "A"}, "post", 120)
    # 3) 个股分析（A股/港股/美股）
    run("symbol-A-600519", "/api/v1/analysis/symbol-analysis/stream",
        {"symbol": "600519", "name": "贵州茅台", "asset_type": "stock", "market": "A"}, "sse")
    run("symbol-HK-00700", "/api/v1/analysis/symbol-analysis/stream",
        {"symbol": "00700", "name": "腾讯控股", "asset_type": "stock", "market": "HK"}, "sse")
    run("symbol-US-AAPL", "/api/v1/analysis/symbol-analysis/stream",
        {"symbol": "AAPL", "name": "Apple Inc", "asset_type": "stock", "market": "US"}, "sse")
    # 4) ETF 分析
    run("symbol-ETF-510300", "/api/v1/analysis/symbol-analysis/stream",
        {"symbol": "510300", "name": "沪深300ETF", "asset_type": "etf", "market": "A"}, "sse")
    # 5) 板块分析 / 概念分析
    if sector_code:
        run("sector-industry", "/api/v1/analysis/sector-analysis/stream",
            {"sector_code": sector_code, "sector_type": "industry", "sector_name": sector_name, "market": "A"}, "sse")
    if concept_code:
        run("sector-concept", "/api/v1/analysis/sector-analysis/stream",
            {"sector_code": concept_code, "sector_type": "concept", "sector_name": concept_name, "market": "A"}, "sse")
    # 6) 指数分析（A股指数）
    run("symbol-index-000300", "/api/v1/analysis/symbol-analysis/stream",
        {"symbol": "000300", "name": "沪深300", "asset_type": "index", "market": "A"}, "sse")
    # 7) 搜索自动补全（A/港股/美股）
    for kw, mkt in [("510", "A"), ("0070", "HK"), ("AAP", "US"), ("贵州", "A")]:
        r = api_get("/api/v1/market/search?keyword=%s&market=%s&include_stocks=true&limit=8" % (kw, mkt), t=60)
        with open(os.path.join(OUT, "search_%s_%s.json" % (mkt, kw)), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        n = len(r) if isinstance(r, list) else (r.get("__err__", "?"))
        print("  search %s/%s -> %s items" % (mkt, kw, n), flush=True)

    print("=== MARKET ANALYSIS DONE ===", flush=True)


if __name__ == "__main__":
    main()
