"""round6 多市场行情分析诊断脚本。
用法:
  python diag/market_diag.py report A|HK|US        # 综合研判（非流式）
  python diag/market_diag.py advice "问题"          # AI 投顾问答
  python diag/market_diag.py symbol <code> <type>   # 个股/ETF/港股/美股分析（流式）type: A|ETF|HK|US
  python diag/market_diag.py sector <name>          # 板块分析（流式，industry 表）
  python diag/market_diag.py concept <name>         # 概念分析（流式，concept 表）
  python diag/market_diag.py index <name>           # 指数分析（流式, asset_type=index）
  python diag/market_diag.py search <keyword>       # 搜索补全
结果存 diag/out/market/<case>.json（report/advice 为全文，stream 为完整 SSE 文本）
"""
import json, os, sys, time, urllib.request, urllib.parse

BASE = "http://localhost:8000/api/v1"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "market")
os.makedirs(OUT, exist_ok=True)


def post_json(path, body, timeout=300):
    data = json.dumps(body).encode("utf-8")
    r = urllib.request.Request(BASE + path, data=data, method="POST",
                               headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return {"elapsed": round(time.time() - t0, 1), "status": "ok", "content": raw}


def post_stream(path, body, timeout=600):
    """读取 SSE 流，累积 data: 行文本。"""
    data = json.dumps(body).encode("utf-8")
    r = urllib.request.Request(BASE + path, data=data, method="POST",
                               headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
    t0 = time.time()
    chunks = []
    events = 0
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        for line in resp:
            line = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.startswith("data:"):
                events += 1
                payload = line[5:].strip()
                if payload and payload not in ("[DONE]",):
                    try:
                        obj = json.loads(payload)
                        if isinstance(obj, dict) and "content" in obj:
                            chunks.append(obj["content"])
                        elif isinstance(obj, dict) and "delta" in obj:
                            chunks.append(obj["delta"])
                        else:
                            chunks.append(payload)
                    except Exception:
                        chunks.append(payload)
    return {"elapsed": round(time.time() - t0, 1), "status": "ok", "events": events,
            "content": "".join(chunks)}


def get_json(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save(name, data):
    p = os.path.join(OUT, name + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  saved -> {p}")
    return p


def main():
    cmd = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "report":
        market = arg or "A"
        res = post_json("/analysis/llm-report", {"symbols": [], "market": market}, timeout=300)
        save(f"llm_report_{market}", res)
        print(f"[report {market}] {res['elapsed']}s, len={len(res['content'])}")
        try:
            obj = json.loads(res["content"])
            print("  keys:", list(obj.keys()))
            for k in ("report", "market_regime", "disclaimer"):
                if k in obj and isinstance(obj[k], str):
                    print(f"  {k}[:120]:", obj[k][:120].replace("\n", " "))
        except Exception:
            print("  content[:300]:", res["content"][:300])
    elif cmd == "advice":
        q = arg or "当前A股市场怎么配置？"
        res = post_json("/analysis/llm-advice", {"query": q, "market": "A"}, timeout=300)
        save(f"llm_advice_{q[:10].replace(' ','_')}", res)
        print(f"[advice] {res['elapsed']}s, len={len(res['content'])}")
        print("  content[:500]:", res["content"][:500].replace("\\n", "\n"))
    elif cmd == "symbol":
        sym, at = arg, (sys.argv[3] if len(sys.argv) > 3 else "A")
        res = post_stream("/analysis/symbol-analysis/stream",
                          {"symbol": sym, "name": "", "asset_type": at}, timeout=600)
        save(f"symbol_{sym}_{at}", res)
        print(f"[symbol {sym} {at}] {res['elapsed']}s, events={res.get('events')}, len={len(res['content'])}")
        print("  content[:600]:", res["content"][:600].replace("\\n", "\n"))
    elif cmd in ("sector", "concept"):
        name = arg
        st = "industry" if cmd == "sector" else "concept"
        # 查找 sector_code：从对应板块列表按名称匹配（中文名经 URL 编码）
        from urllib.parse import quote as _q
        code = None
        try:
            lst = get_json(f"/market/sectors/{st}")
            items = lst if isinstance(lst, list) else lst.get("items", [])
            for it in items:
                nm = it.get("sector_name") or it.get("name") or ""
                if nm and (name in nm or nm in name):
                    code = it.get("sector_code")
                    print(f"  matched sector: {nm} -> {code}")
                    break
        except Exception as e:
            print("  sector lookup fail:", e)
        if not code:
            print(f"  !! sector_code not found for {name}（列表 {len(items) if 'items' in dir() else '?'} 条）——尝试 name 直传")
            code = name
        res = post_stream("/analysis/sector-analysis/stream",
                          {"sector_code": code, "sector_type": st, "sector_name": name}, timeout=600)
        save(f"sector_{st}_{name}", res)
        print(f"[{cmd} {name}] {res['elapsed']}s, events={res.get('events')}, len={len(res['content'])}")
        print("  content[:600]:", res["content"][:600].replace("\\n", "\n"))
    elif cmd == "index":
        name = arg
        # 传指数代码（沪深300 = 000300 / sh000300），asset_type=index
        code = {"沪深300": "sh000300", "上证指数": "sh000001", "中证500": "sh000905", "创业板指": "sz399006"}.get(name, name)
        res = post_stream("/analysis/symbol-analysis/stream",
                          {"symbol": code, "name": name, "asset_type": "index"}, timeout=600)
        save(f"index_{name}", res)
        print(f"[index {name}] {res['elapsed']}s, events={res.get('events')}, len={len(res['content'])}")
        print("  content[:600]:", res["content"][:600].replace("\\n", "\n"))
    elif cmd == "search":
        kw = arg
        t0 = time.time()
        items = get_json("/market/search?keyword=" + urllib.parse.quote(kw) + "&include_stocks=true")
        res = {"elapsed": round(time.time() - t0, 1), "count": len(items),
               "items": [{"symbol": i.get("symbol"), "name": i.get("name"),
                          "asset_type": i.get("asset_type"), "market": i.get("market")} for i in items]}
        save(f"search_{kw}", res)
        print(f"[search {kw}] {res['elapsed']}s, {res['count']} 条")
        for i in res["items"][:15]:
            print("  ", i)
    else:
        print("unknown cmd")


if __name__ == "__main__":
    main()
