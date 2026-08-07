# -*- coding: utf-8 -*-
"""第6/7/8步：持仓技术分析与信号、资讯页面、因子模型"""
import json
import os
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)


def api(method, path, data=None, t=90):
    try:
        if method == "GET":
            r = urllib.request.urlopen(BASE + path, timeout=t)
        else:
            body = json.dumps(data).encode()
            req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"})
            r = urllib.request.urlopen(req, timeout=t)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err__": "HTTP %s: %s" % (e.code, e.read().decode()[:200])}
    except Exception as e:
        return {"__err__": str(e)}


def save(name, obj):
    with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return obj


HOLDINGS = ["159338", "510880", "159545", "159516", "159992", "513120", "513010", "512000", "159869", "518880"]


def main():
    # ===== 第6步：技术分析与综合信号 =====
    print("=== 技术分析与信号（10 只场内持仓） ===")
    summary = []
    for sym in HOLDINGS:
        ind = api("GET", "/api/v1/market/indicators/%s" % sym, t=60)
        sig = api("GET", "/api/v1/market/signal/%s" % sym, t=60)
        save("ind_%s" % sym, ind)
        save("sig_%s" % sym, sig)
        if "__err__" in ind or "__err__" in sig:
            summary.append((sym, "FAIL", str(ind.get("__err__") or sig.get("__err__"))[:80]))
            print("  %s FAIL: %s" % (sym, str(ind.get("__err__") or sig.get("__err__"))[:80]), flush=True)
            continue
        row = {
            "symbol": sym,
            "rsi": ind.get("rsi"), "macd": ind.get("macd"), "macd_signal": ind.get("macd_signal"),
            "ma5": ind.get("ma5"), "ma20": ind.get("ma20"),
            "bb_upper": ind.get("bb_upper"), "bb_mid": ind.get("bb_mid"), "bb_lower": ind.get("bb_lower"),
            "signal": sig.get("signal") or sig.get("signal_text") or sig.get("direction"),
            "score": sig.get("score") or sig.get("composite_score"),
        }
        summary.append(row)
        print("  %s rsi=%s macd=%s sig=%s score=%s" % (
            sym, row["rsi"], row["macd"], row["signal"], row["score"]), flush=True)
    save("step6_summary", summary)

    # ===== 第7步：资讯页面 =====
    print("=== 资讯头条（level/stars 分布） ===")
    news = api("GET", "/api/v1/news/headlines?limit=50", t=60)
    save("news_headlines", news)
    if isinstance(news, list):
        from collections import Counter
        lv = Counter(n.get("level") for n in news)
        st = Counter(n.get("stars") for n in news)
        print("  count:", len(news), "| level dist:", dict(sorted(lv.items())), "| stars dist:", dict(sorted(st.items())))
        for n in news[:6]:
            print("   [L%s ★%s] %s | %s" % (n.get("level"), n.get("stars"), (n.get("title") or "")[:50], (n.get("summary") or "")[:60]))
    print("=== 宏观/全球 ===")
    macro = api("GET", "/api/v1/news/macro", t=60)
    glob = api("GET", "/api/v1/news/global", t=60)
    save("news_macro", macro)
    save("news_global", glob)
    print("  macro:", len(macro) if isinstance(macro, list) else macro, "| global:", len(glob) if isinstance(glob, list) else glob)
    print("=== 新闻智能分析（LLM） ===")
    na = api("POST", "/api/v1/analysis/llm-news-analysis", {}, t=180)
    save("news_llm_analysis", na)
    if "__err__" in na:
        print("  FAIL:", str(na["__err__"])[:200])
    else:
        an = na.get("analysis") or ""
        print("  OK, analysis len:", len(an), "| preview:", an[:300].replace("\n", " "))

    # ===== 第8步：因子模型页面 =====
    print("=== 因子模型 ===")
    act = api("GET", "/api/v1/factors/active", t=60)
    save("factors_active", act)
    if isinstance(act, dict):
        print("  total:", act.get("total"), "| valid:", act.get("valid"), "| warn:", act.get("warn"),
              "| no_data:", act.get("no_data"), "| static:", act.get("static"), "| avg_ic:", act.get("avg_ic"))
        for f in (act.get("factors") or []):
            if f.get("status") != "ok":
                print("   [%s] %s | ic=%s | reason=%s" % (f.get("status"), f.get("code") or f.get("name"),
                                                          f.get("ic_value"), (f.get("no_data_reason") or "")[:60]))
    ic = api("GET", "/api/v1/factors/ic", t=60)
    save("factors_ic", ic)
    if isinstance(ic, dict):
        facs = ic.get("factors") or []
        neg = [f for f in facs if (f.get("ic_value") or 0) < 0]
        print("  IC total:", ic.get("total"), "| negative IC:", len(neg))
        for f in neg[:8]:
            print("    -", f.get("code"), f.get("ic_value"))
    mdl = api("GET", "/api/v1/factors/model", t=60)
    save("factors_model", mdl)
    print("  model keys:", list(mdl.keys())[:10] if isinstance(mdl, dict) else type(mdl))
    fh = api("GET", "/api/v1/admin/factor-health", t=60)
    save("factor_health", fh)
    if isinstance(fh, list):
        bad = [f for f in fh if f.get("status") != "ok"]
        print("  factor-health:", len(fh), "entries, bad:", len(bad))
        for b in bad[:10]:
            print("    -", b.get("symbol"), b.get("status"))

    print("=== DONE ===")


if __name__ == "__main__":
    main()
