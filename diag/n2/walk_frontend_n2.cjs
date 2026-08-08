// 前端全链路走查：console error / 失败请求 / 关键渲染（第9步数据断裂排查）
const path = require("path");
const { chromium } = require(path.join(__dirname, "..", "..", "frontend", "node_modules", "playwright"));
const fs = require("fs");

const OUT = path.join(__dirname, "out");
fs.mkdirSync(OUT, { recursive: true });

const PAGES = [
  ["/", "Dashboard"],
  ["/market-analysis", "行情分析"],
  ["/portfolio-analysis", "组合管理"],
  ["/news", "资讯"],
  ["/factor-ic", "因子IC"],
  ["/admin/config", "配置"],
  ["/source-monitor", "数据源监控"],
  ["/token-monitor", "Token监控"],
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const results = {};

  for (const [pathname, name] of PAGES) {
    const consoleMsgs = [];
    const failedReqs = [];
    page.removeAllListeners("console");
    page.removeAllListeners("requestfailed");
    page.removeAllListeners("response");
    page.on("console", (m) => {
      if (m.type() === "error") consoleMsgs.push(m.type() + ": " + m.text().slice(0, 250));
    });
    page.on("requestfailed", (r) => failedReqs.push("FAIL " + r.url().slice(0, 150)));
    page.on("response", (r) => { if (r.status() >= 400) failedReqs.push(r.status() + " " + r.url().slice(0, 150)); });

    const t0 = Date.now();
    try {
      await page.goto("http://localhost" + pathname, { waitUntil: "domcontentloaded", timeout: 30000 });
      // 等待动态请求完成
      await page.waitForTimeout(12000);
    } catch (e) {
      consoleMsgs.push("NAV_ERR: " + e.message.slice(0, 150));
    }
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    results[pathname] = { page: name, elapsed_s: elapsed, consoleErrors: consoleMsgs, failedReqs: failedReqs };

    console.log("=== %s (%s) %ss  consoleErrors=%d failedReqs=%d",
      name, pathname, elapsed, consoleMsgs.length, failedReqs.length);
    for (const m of consoleMsgs) console.log("  CONSOLE: " + m);
    for (const f of failedReqs) console.log("  REQFAIL: " + f);
  }
  fs.writeFileSync(path.join(OUT, "walk_frontend_n2.json"), JSON.stringify(results, null, 2));
  await browser.close();
  console.log("\nDONE -> diag/n2/frontend_walk_n2.json");
  const allErr = Object.values(results).reduce((a, r) => a + r.consoleErrors.length, 0);
  const allFail = Object.values(results).reduce((a, r) => a + r.failedReqs.length, 0);
  console.log("TOTAL consoleErrors=%d failedReqs=%d", allErr, allFail);
})().catch((e) => { console.error("FATAL", e); process.exit(1); });