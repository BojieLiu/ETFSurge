# -*- coding: utf-8 -*-
"""前端全链路走查：收集 console error / failed requests / 关键数据渲染"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frontend", "node_modules"))
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

PAGES = [
    ("/", "Dashboard"),
    ("/market-analysis", "行情分析"),
    ("/portfolio-analysis", "组合管理"),
    ("/news", "资讯"),
    ("/factor-ic", "因子IC"),
    ("/admin/config", "配置"),
    ("/source-monitor", "数据源监控"),
    ("/token-monitor", "Token监控"),
]

results = {}


def walk(browser, page, name, url, wait_ms=9000):
    console_errs = []
    failed_reqs = []
    slow_reqs = []
    body_text = ""

    def on_console(msg):
        if msg.type in ("error", "warning"):
            console_errs.append({"type": msg.type, "text": msg.text[:300]})

    def on_failed(req):
        failed_reqs.append({"url": req.url[:160], "err": (req.failure or "")[:120]})

    def on_response(resp):
        if resp.status >= 400:
            failed_reqs.append({"url": resp.url[:160], "status": resp.status})

    page.on("console", on_console)
    page.on("requestfailed", on_failed)
    page.on("response", on_response)
    t0 = __import__("time").time()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(wait_ms)
    except Exception as e:
        console_errs.append({"type": "nav_error", "text": str(e)[:200]})
    elapsed = __import__("time").time() - t0
    try:
        body_text = page.evaluate("document.body.innerText.slice(0, 4000)")
    except Exception:
        pass
    # 关键文本样本
    sample = body_text.replace("\n", " ")[:600]
    results[name] = {
        "url": url,
        "load_sec": round(elapsed, 1),
        "console_errors": console_errs,
        "failed_requests": failed_reqs,
        "body_sample": sample,
    }
    print("== %s (%s) load=%.1fs | console err/warn=%d | failed reqs=%d" % (
        name, url, elapsed, len(console_errs), len(failed_reqs)), flush=True)
    for e in console_errs[:8]:
        print("   [console %s] %s" % (e["type"], e["text"][:160]), flush=True)
    for f in failed_reqs[:8]:
        print("   [req fail] %s %s" % (f.get("status", ""), f["url"][:140]), flush=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        for path, name in PAGES:
            walk(browser, page, name, "http://localhost" + path)
        # 搜索框自动补全测试（market-analysis 页面）
        try:
            page.goto("http://localhost/market-analysis", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
            # 尝试找到搜索输入框
            inputs = page.query_selector_all("input")
            print("market-analysis inputs:", len(inputs), flush=True)
            for i, inp in enumerate(inputs[:6]):
                ph = inp.get_attribute("placeholder") or ""
                print("   input[%d] placeholder=%s" % (i, ph[:60]), flush=True)
        except Exception as e:
            print("search probe fail:", str(e)[:150], flush=True)
        browser.close()

    with open(os.path.join(OUT, "frontend_walk.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("=== FRONTEND WALK DONE ===", flush=True)


if __name__ == "__main__":
    main()
