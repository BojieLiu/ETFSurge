// 第11步：前端 Lighthouse 性能诊断（lighthouse + chrome-launcher）
const fs = require("fs");
const lighthouse = require("lighthouse").default || require("lighthouse");
const chromeLauncher = require("chrome-launcher");

const OUT = __dirname + "/out";
fs.mkdirSync(OUT, { recursive: true });

const PAGES = [
  ["http://localhost/", "dashboard"],
  ["http://localhost/market-analysis", "market-analysis"],
  ["http://localhost/portfolio-analysis", "portfolio-analysis"],
];

(async () => {
  const chrome = await chromeLauncher.launch({
    chromeFlags: ["--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
  });
  const results = {};
  for (const [url, name] of PAGES) {
    console.log(">>> Lighthouse:", name, url);
    const runnerResult = await lighthouse(url, {
      port: chrome.port,
      output: "json",
      logLevel: "error",
      onlyCategories: ["performance", "accessibility", "best-practices", "seo"],
      settings: {
        preset: "desktop",
        maxWaitForFcp: 60000,
        maxWaitForLoad: 90000,
      },
    });
    if (!runnerResult) { console.log("  NO RESULT"); results[name] = { error: "no result" }; continue; }
    const lhr = runnerResult.lhr;
    const cats = lhr.categories;
    const score = (c) => (c ? Math.round(c.score * 100) : null);
    const audits = lhr.audits;
    const metric = (id) => { const a = audits[id]; return a ? (a.displayValue || String(a.numericValue)) : "?"; };
    results[name] = {
      performance: score(cats.performance),
      accessibility: score(cats.accessibility),
      bestPractices: score(cats["best-practices"]),
      seo: score(cats.seo),
      FCP: metric("first-contentful-paint"),
      LCP: metric("largest-contentful-paint"),
      TBT: metric("total-blocking-time"),
      CLS: metric("cumulative-layout-shift"),
    };
    console.log("  perf=%s a11y=%s bp=%s seo=%s FCP=%s LCP=%s TBT=%s CLS=%s",
      results[name].performance, results[name].accessibility, results[name].bestPractices,
      results[name].seo, results[name].FCP, results[name].LCP, results[name].TBT, results[name].CLS);
    fs.writeFileSync(OUT + "/lh_" + name + ".json", JSON.stringify(lhr, null, 2));
  }
  fs.writeFileSync(OUT + "/lighthouse_n2_summary.json", JSON.stringify(results, null, 2));
  await chrome.kill();
  console.log("\nDONE -> diag/n2/out/lighthouse_n2_summary.json");
})().catch((e) => { console.error("FATAL", e && e.message); process.exit(1); });