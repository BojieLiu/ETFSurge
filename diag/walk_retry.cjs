// 复测：组合管理页 + 资讯页 请求失败是否为超时
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const report = {};

  for (const [pathname, name, waitMs] of [
    ["/portfolio-analysis", "组合管理", 50000],
    ["/news", "资讯", 30000],
  ]) {
    const reqs = {};
    page.removeAllListeners("response");
    page.removeAllListeners("requestfailed");
    page.on("response", (r) => { if (r.url().includes("/api/v1")) { reqs[r.url().split("/api/v1")[1].split("?")[0]] = { status: r.status(), ms: (r.request().timing() ? r.request().timing().responseEnd : 0) }; } });
    page.on("requestfailed", (r) => { if (r.url().includes("/api/v1")) { const k = r.url().split("/api/v1")[1].split("?")[0]; reqs[k] = { status: "FAILED", err: (r.failure() || "").slice(0, 80) }; } });
    const t0 = Date.now();
    await page.goto("http://localhost" + pathname, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(waitMs);
    report[name] = { wait_ms: waitMs, api_requests: reqs };
    console.log("== " + name + " ==");
    for (const [k, v] of Object.entries(reqs)) console.log("  " + k + " -> " + JSON.stringify(v));
  }
  await browser.close();
  fs.writeFileSync(path.join(__dirname, "out", "frontend_retry.json"), JSON.stringify(report, null, 1), "utf-8");
  console.log("DONE");
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
