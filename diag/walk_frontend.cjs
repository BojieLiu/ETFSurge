// 前端全链路走查（node + playwright）：console 错误 / 失败请求 / 关键渲染
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

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
      if (m.type() === "error" || m.type() === "warning") consoleMsgs.push(m.type() + ": " + m.text().slice(0, 250));
    });
    page.on("requestfailed", (r) => failedReqs.push("FAIL " + r.url().slice(0, 150)));
    page.on("response", (r) => { if (r.status() >= 400) failedReqs.push(r.status() + " " + r.url().slice(0, 150)); });

    const t0 = Date.now();
    try {
      await page.goto("http://localhost" + pathname, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForTimeout(8000);
    } catch (e) {
      consoleMsgs.push("nav_error: " + String(e).slice(0, 150));
    }
    const loadSec = ((Date.now() - t0) / 1000).toFixed(1);
    let bodySample = "";
    try { bodySample = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, " ").slice(0, 500); } catch (e) {}
    results[name] = { url: pathname, load_sec: loadSec, console_errors: consoleMsgs.slice(0, 10), failed_requests: failedReqs.slice(0, 10), body_sample: bodySample };
    console.log(`== ${name} (${pathname}) load=${loadSec}s console=${consoleMsgs.length} failed=${failedReqs.length}`);
    consoleMsgs.slice(0, 6).forEach((m) => console.log("   [console] " + m.slice(0, 150)));
    failedReqs.slice(0, 6).forEach((m) => console.log("   [req] " + m.slice(0, 140)));
  }

  // 搜索框自动补全 probe
  try {
    await page.goto("http://localhost/market-analysis", { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(3000);
    const inputs = await page.$$("input");
    console.log("market-analysis inputs: " + inputs.length);
    for (let i = 0; i < Math.min(inputs.length, 8); i++) {
      const ph = await inputs[i].getAttribute("placeholder");
      console.log(`   input[${i}] placeholder=${ph || ""}`);
    }
  } catch (e) { console.log("search probe fail: " + String(e).slice(0, 150)); }

  await browser.close();
  fs.writeFileSync(path.join(OUT, "frontend_walk.json"), JSON.stringify(results, null, 1), "utf-8");
  console.log("=== FRONTEND WALK DONE ===");
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
