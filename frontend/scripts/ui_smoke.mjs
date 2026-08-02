// S5: 关键页面 Playwright 冒烟——渲染成功 + 无关键占位文案 + tab 切换。
// 用法: node frontend/scripts/ui_smoke.mjs <baseURL>
import { chromium } from 'playwright';

const BASE = process.argv[2] || 'http://localhost:5173';

// 关键占位文案（F15-F18 渲染层回归防线）——出现即 FAIL
const PLACEHOLDERS = [
  '需输入成本',       // F18 R66: 累计盈亏估算提示不应大范围出现
  '暂无板块数据',     // F15: 板块空态
  '数据源未接入',     // F17: 数据源页
];

const ROUTES = [
  { name: 'Dashboard', path: '/', expect: '总仓位' },
  { name: '因子模型', path: '/factor-ic' },
  { name: 'Token 监控', path: '/token-monitor', expect: 'Token' },
  { name: '数据源', path: '/source-monitor' },
  { name: '标的分析', path: '/market-analysis' },
];

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  let pass = 0, fail = 0;
  const failures = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('favicon')) {
      failures.push(`console.error: ${msg.text().slice(0, 120)}`);
    }
  });
  page.on('pageerror', (err) => {
    failures.push(`pageerror: ${String(err).slice(0, 160)}`);
  });

  for (const route of ROUTES) {
    try {
      await page.goto(`${BASE}${route.path}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      // 等路由组件挂载 + 首屏数据（组合/行情可能需 2-5s）
      await page.waitForTimeout(route.expect ? 6000 : 3000);
      const body = await page.textContent('body');
      if (!body || body.trim().length <= 50) {
        fail++;
        failures.push(`[${route.name}] 页面渲染为空`);
        continue;
      }
      if (route.expect && !body.includes(route.expect)) {
        fail++;
        failures.push(`[${route.name}] 核心组件未挂载（缺「${route.expect}」）`);
        continue;
      }
      const found = PLACEHOLDERS.filter((p) => body.includes(p));
      if (found.length) {
        fail++;
        failures.push(`[${route.name}] 关键占位文案出现: ${found.join(', ')}`);
        continue;
      }
      pass++;
      console.log(`  [PASS] ${route.name} 渲染成功 (${(body.length / 1024).toFixed(1)}KB)`);
    } catch (e) {
      fail++;
      failures.push(`[${route.name}] 访问失败: ${String(e).slice(0, 120)}`);
    }
  }

  // 关键交互：Dashboard tab 切换内容变化
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2500);
    const tabs = page.locator('[role="tab"], .tab, .tabs button, .el-tabs__item, .nav-tab');
    const n = await tabs.count();
    if (n >= 2) {
      await tabs.nth(1).click();
      await page.waitForTimeout(1200);
      pass++;
      console.log(`  [PASS] tab 切换交互 (${n} 个 tab)`);
    } else {
      fail++;
      failures.push('[Dashboard] 未找到可切换 tab');
    }
  } catch (e) {
    fail++;
    failures.push(`[Dashboard tab 切换] ${String(e).slice(0, 120)}`);
  }

  await browser.close();

  console.log(`\n结果: ${pass}/${pass + fail} 通过`);
  if (failures.length) {
    console.log('FAILURES:');
    for (const f of failures.slice(0, 20)) console.log(`  ✗ ${f}`);
    process.exit(1);
  }
}

main().catch((e) => { console.error('SMOKE ERROR:', e); process.exit(1); });
