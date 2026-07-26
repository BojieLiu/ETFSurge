# ETF Surge — E2E 自动化测试方案

> 目标：通过 Playwright 覆盖前端**全部用户操作链路**，在每次修改后自动验证前端渲染正确性和功能完整性。
> 生成日期: 2026-07-21
>
> ⚠️ **2026-07-26 实施状态更新**：本文档为完整方案蓝图。实际已实施：
> - ✅ 基础设施：`playwright.config.js` + server utilities（`server-setup.cjs` / `server-teardown.cjs` / `server.js`）已就绪
> - ✅ package.json 脚本：`test:e2e` / `test:e2e:smoke` / `test:e2e:visual` / `test:e2e:ui` 已配置
> - ⚠️ 已实现 **6/12 个 spec 文件**：01-smoke / 02-visual / 03-navigation / 04-wizard-design / 05-theme-assets / 12-regression
> - ❌ 其余 6 个 spec（02-dashboard / 03-portfolio-mgr / 05-market-tabs / 06-watchlist / 07-ai-advisor / 08-sector-analysis / 09-symbol-analysis / 10-news / 11-token-monitor）待实现
> - 本文档保持完整方案不变，作为 Phase 7.1.5 的实施蓝图

---

## 目录

1. [现状与差距](#1-现状与差距)
2. [方案总览](#2-方案总览)
3. [测试基础设施](#3-测试基础设施)
4. [前端全部页面与操作链路清单](#4-前端全部页面与操作链路清单)
5. [Spec 文件结构与测试用例设计](#5-spec-文件结构与测试用例设计)
6. [测试数据管理](#6-测试数据管理)
7. [CI 集成与执行流程](#7-ci-集成与执行流程)
8. [验收标准](#8-验收标准)
9. [后端 API E2E 覆盖计划](#9-后端-api-e2e-覆盖计划verify_e2epy-扩展)
   - [API 清理计划](#911-冗余废弃-api-端点清理计划)

---

## 1. 现状与差距

### 当前测试覆盖

| 层次 | 技术 | 文件数 | 覆盖范围 | 限制 |
|------|------|--------|---------|------|
| 后端 API | `verify_e2e.py` | 1 | 8 类 HTTP 端点（health / designs / indices / async-tasks / strategy-checks） | 纯 HTTP，不涉及前端 |
| 前端单元 | vitest + jsdom | 11 | 工具函数 / store / composable / 组件挂载 | jsdom 无布局引擎，无真实网络，无 CSS 渲染 |

### 无法捕获的问题

验证是盲区，说明为什么"改好一个、坏两个"反复发生：

```
❌ 按钮渲染为纯文本（CSS scoping 问题）
❌ 页面白屏（JS 运行时错误）
❌ 输入框不可交互（事件冒泡被截断）
❌ 自选列表加载奇慢（真实网络延时）
❌ Modal 弹起后表单填不了（z-index / focus 问题）
❌ Tab 切换后功能未联动（prop 传递断裂）
❌ WebSocket 连接失败后无降级
```

---

## 2. 方案总览

```
┌─────────────────────────────────────────────────────┐
│                  Playwright E2E                      │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │   Spec 文件（12 个）                           │   │
│  │                                              │   │
│  │  01-smoke.spec          ← 全页面 200 不白屏   │   │
│  │  02-dashboard.spec      ← 首页交互全链路      │   │
│  │  03-portfolio-mgr.spec  ← 持仓增删改查        │   │
│  │  04-ai-tools.spec       ← 组合设计/策略检查    │   │
│  │  05-market-tabs.spec    ← 市场 Tab 联动       │   │
│  │  06-watchlist.spec      ← 自选操作全流程      │   │
│  │  07-ai-advisor.spec     ← AI 顾问输入/发送    │   │
│  │  08-sector-analysis.spec← 板块分析选择/分析   │   │
│  │  09-symbol-analysis.spec← 标的搜索/图表/研报  │   │
│  │  10-news.spec           ← 资讯展示/筛选      │   │
│  │  11-token-monitor.spec  ← Token 用量监控      │   │
│  │  12-regression.spec     ← 历史回归场景        │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │   支撑层                                       │   │
│  │   config/playwright.config.js  ← 配置        │   │
│  │   utils/server.js              ← 启停前后端  │   │
│  │   utils/seed.js               ← 测试数据注入 │   │
│  │   utils/assertions.js         ← 自定义断言  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 技术选型

| 工具 | 选型理由 |
|------|---------|
| **Playwright** | 跨浏览器、自动等待、locator 语义化、截图对比、网络拦截、test retry |
| **@playwright/test** | 内置 test runner、expect、parallel 执行 |
| **Vite 开发服务器** | 热更新 + API 代理，测试时使用真实 Vite dev server |

### 测试模式

| 模式 | 命令 | 用途 | 速度 |
|------|------|------|------|
| **smoke** | `npm run test:e2e -- --grep @smoke` | 每次修复后必跑（< 30s） | ⚡ |
| **full** | `npm run test:e2e` | 全覆盖（3-5 分钟） | 🐢 |
| **visual** | `npm run test:e2e:visual` | 截图基线对比，检测 CSS 回归 | 🐢 |
| **ui** | `npm run test:e2e:ui` | 交互式调试 | — |

---

## 3. 测试基础设施

### 3.1 目录结构

```
frontend/e2e/
├── config/
│   └── playwright.config.js    ← Playwright 配置
├── specs/
│   ├── 01-smoke.spec.js
│   ├── 02-dashboard.spec.js
│   ├── 03-portfolio-mgr.spec.js
│   ├── 04-ai-tools.spec.js
│   ├── 05-market-tabs.spec.js
│   ├── 06-watchlist.spec.js
│   ├── 07-ai-advisor.spec.js
│   ├── 08-sector-analysis.spec.js
│   ├── 09-symbol-analysis.spec.js
│   ├── 10-news.spec.js
│   ├── 11-token-monitor.spec.js
│   └── 12-regression.spec.js
├── utils/
│   ├── server.js              ← 前后端进程管理
│   ├── seed.js                ← 测试数据注入（DB + API mock）
│   └── assertions.js          ← 自定义断言
└── fixtures/                   ← 截图基线
    ├── dashboard.png
    ├── market-analysis.png
    └── ...
```

### 3.2 Playwright 配置

```javascript
// e2e/config/playwright.config.js
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '../specs',
  timeout: 60000,
  retries: 1,
  use: {
    baseURL: 'http://localhost:5173',  // Vite dev server
    viewport: { width: 1440, height: 900 },
    actionTimeout: 10000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  // 通过 globalSetup/globalTeardown 管理前后端生命周期
  globalSetup: require.resolve('../utils/server-setup.js'),
  globalTeardown: require.resolve('../utils/server-teardown.js'),
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
  // webServer 字段不适用（需要同时启动 Python 后端 + Vite），改用 globalSetup
})
```

### 3.3 前后端生命周期管理

server.js 提供 startServers / stopServers 函数。globalSetup 和 globalTeardown 封装它。

```javascript
// e2e/utils/server-setup.js
// Playwright globalSetup — 启动前后端服务
const { startServers } = require('./server')
module.exports = async () => { await startServers() }
```

```javascript
// e2e/utils/server-teardown.js
// Playwright globalTeardown — 关闭前后端服务
const { stopServers } = require('./server')
module.exports = async () => { await stopServers() }
```

```javascript
// e2e/utils/server.js
// ⚠️ Windows 兼容注意事项：
//   - uvicorn / npx 需要 shell: true 才能正确解析 .cmd 入口
//   - 使用 net 模块代替 spawn 检测端口（避免 PowerShell 编码问题）
//   - 前后端启动后通过 playwright.config.js 的 globalSetup 调用
import { spawn } from 'child_process'
import * as net from 'net'
import * as path from 'path'

const BACKEND_DIR = path.resolve(__dirname, '../../backend')
const FRONTEND_DIR = path.resolve(__dirname, '../..')
const BACKEND_PORT = 8000
const FRONTEND_PORT = 5173

function waitForPort(port, host = '127.0.0.1', timeoutMs = 30000) {
  const start = Date.now()
  return new Promise((resolve, reject) => {
    function tryConnect() {
      const sock = new net.Socket()
      sock.setTimeout(1000)
      sock.on('connect', () => { sock.destroy(); resolve() })
      sock.on('error', () => sock.destroy())
      sock.on('timeout', () => sock.destroy())
      sock.connect(port, host)
      if (Date.now() - start >= timeoutMs) {
        reject(new Error(`端口 ${port} 在 ${timeoutMs}ms 内未就绪`))
      } else {
        setTimeout(tryConnect, 500)
      }
    }
    tryConnect()
  })
}

let backend = null
let frontend = null

export async function startServers() {
  // 启动后端 — 使用 cmd.exe /c 解决 Windows 入口点问题
  backend = spawn('cmd.exe', ['/c', 'uvicorn', 'app.main:app', '--port', String(BACKEND_PORT)], {
    cwd: BACKEND_DIR,
    shell: true,
    stdio: 'pipe',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  })
  backend.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`))
  await waitForPort(BACKEND_PORT, '127.0.0.1', 30000)

  // 启动前端 Vite
  frontend = spawn('cmd.exe', ['/c', 'npx', 'vite', '--port', String(FRONTEND_PORT)], {
    cwd: FRONTEND_DIR,
    shell: true,
    stdio: 'pipe',
  })
  frontend.stderr.on('data', (d) => process.stderr.write(`[frontend] ${d}`))
  await waitForPort(FRONTEND_PORT, '127.0.0.1', 30000)
}

export async function stopServers() {
  if (backend) { backend.kill('SIGTERM'); backend = null }
  if (frontend) { frontend.kill('SIGTERM'); frontend = null }
  // 等待进程退出
  await new Promise(r => setTimeout(r, 1000))
}
```

### 3.4 .gitignore 新增条目

```
# Playwright E2E test artifacts
frontend/test-results/
frontend/e2e/fixtures/*.png
frontend/e2e/fixtures/*.spec.js.snap/
```

### 3.5 package.json 新增脚本

```json
{
  "scripts": {
    "test:e2e": "playwright test --config e2e/config/playwright.config.js",
    "test:e2e:smoke": "playwright test --config e2e/config/playwright.config.js --grep @smoke",
    "test:e2e:visual": "playwright test --config e2e/config/playwright.config.js --update-snapshots",
    "test:e2e:ui": "playwright test --config e2e/config/playwright.config.js --ui"
  },
  "devDependencies": {
    "@playwright/test": "^1.52.0",
    "playwright": "^1.52.0"
  }
}
```

---

## 4. 前端全部页面与操作链路清单

### 4.1 路由 → 页面 → 组件树

```
/  (Dashboard 投资总览)
├── GlobalIndicesStrip            ← 全球指数刷新
├── Tabs (综合/场内/场外)          ← Tab 切换
├── CapitalInputBar               ← 输入资金
├── SummaryCards                  ← 总览卡片（自动更新）
├── AllocationPieChart ×2        ← 饼图渲染
├── AllocationTable ×2           ← 表格渲染
├── PnLDetailTable               ← 盈亏明细
├── PnLBarChart                  ← 盈亏柱状图
└── ErrorOverlay                 ← 错误降级

/portfolio-analysis (组合分析)
├── [Tab] AI工具
│   └── DashboardAiTools (views/)
│       ├── DesignWizard          ← 输入资金 → 提交
│       ├── DesignLoading         ← 进度显示
│       ├── DesignResult          ← 方案卡片/报告切换
│       ├── DesignHistory         ← 历史记录查看
│       ├── StrategyCheckModal    ← 弹窗选择类型
│       └── StrategyCheckResult   ← 检查结果
├── [Tab] 持仓
│   └── PortfolioManager (1084行)
│       ├── Tab (场内/场外)
│       ├── 添加表单:
│       │   ├── 搜索 ETF (AppInput + dropdown)
│       │   ├── 市场类型 (AppSelect)
│       │   ├── 跟踪指数 (AppInput, 仅场外)
│       │   ├── 成本价 (AppInput number)
│       │   ├── 份额 (AppInput number)
│       │   ├── 目标权重 (AppInput number)
│       │   └── 提交按钮
│       ├── 数据表格 (分页)
│       │   ├── 行点击 → 编辑
│       │   ├── 删除按钮
│       │   └── 翻页按钮
│       └── 导出/导入
└── [Tab] 技术分析
    └── AnalysisView
        ├── ControlPanel           ← 标的/周期/指标切换
        ├── ChartPanel             ← K线/分时图
        └── SignalPanel            ← 综合信号

/market-analysis (行情分析)
├── 顶部 Tabs (A股/港股/美股/全球)  ← 全局 Tab
├── MarketReport                    ← 生成市场研判
├── WatchlistPanel                  ← 自选列表 + 添加 Modal
├── AiAdvisor                       ← 输入问题 → 发送
├── SectorAnalysis                  ← 板块类型切换 → 搜索 → 分析
├── SymbolAnalysis                  ← 搜索 → 图表 → 指标 → 研报
└── IndexAnalysis                   ← 搜索指数 → AI 分析

/news (资讯监控)
├── 连接状态指示器
├── 重要性筛选 (1-5 星)
├── 资讯列表 (WebSocket 实时推送)
│   ├── 标题/内容/来源/时间
│   └── AI 智能分析按钮
└── AI 分析结果弹窗/面板

/token-monitor (Token 监控)
├── 统计卡片 (总调用/今日/本月/错误率/费用)
├── Tab 切换 (按日/按月)
├── Token 趋势图
└── 异常列表
```

### 4.2 跨页面共享操作

| 操作 | 影响页面 | 涉及组件 |
|------|---------|---------|
| 修改资金 | Dashboard 全局 | CapitalInputBar |
| 添加/删除 ETF | Dashboard + PortfolioManager | allocation store |
| 生成设计方案 | DashboardAiTools + Dashboard | design store |
| WebSocket 连接 | Dashboard + MarketAnalysis + News | marketStore / useNewsWS |

---

## 5. Spec 文件结构与测试用例设计

### 5.1 通用断言工具

```javascript
// e2e/utils/assertions.js

// 页面没有 JS 报错
// ⚠️ 必须在 page.goto 之前注册监听器，否则会漏掉早期错误
// 正确用法：在 test.beforeEach 中调用 setupConsoleCapture，在 test 结束时调用 assertNoConsoleErrors
export function setupConsoleCapture(page) {
  const errors = []
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push({ text: msg.text(), location: msg.location() })
  })
  page.on('pageerror', err => errors.push({ text: err.message, stack: err.stack }))
  return errors
}

export function assertNoConsoleErrors(errors) {
  expect(errors).toHaveLength(0)
}

// 元素可见且可交互
export async function assertVisible(page, selector) {
  await expect(page.locator(selector)).toBeVisible()
}

// 按钮不是纯文本（通过 button tagName + 布局属性确认渲染）
// 注意：
//   - cursor: pointer 对 <button> 标签来说是浏览器默认的，样式全丢时也是 pointer
//   - 所以额外检查 padding 值（如果 CSS 丢失 padding 会为 0）和 border-radius
//   - backgroundColor 不检查，因为 ghost variant 背景可能为 transparent
export async function assertButtonRendered(page, text) {
  const btn = page.locator(`button:has-text("${text}")`)
  await expect(btn).toBeVisible()
  // 确保是 button 元素
  const tag = await btn.evaluate(el => el.tagName.toLowerCase())
  expect(tag).toBe('button')
  // 检查 padding 值（按钮样式丢失时 padding 为 0px）
  const padTop = await btn.evaluate(el => parseFloat(getComputedStyle(el).paddingTop))
  expect(padTop).toBeGreaterThan(0)
  // 检查 border-radius（按钮应有圆角，纯文本无）
  const radius = await btn.evaluate(el => parseFloat(getComputedStyle(el).borderRadius))
  expect(radius).toBeGreaterThanOrEqual(2)
}

// 输入框可交互
export async function assertInputInteractable(page, placeholder) {
  const input = page.locator(`input[placeholder*="${placeholder}"]`)
  await expect(input).toBeEnabled()
  await input.fill('test input')
  await expect(input).toHaveValue('test input')
}
```

### 5.2 各 Spec 测试用例

---

#### `01-smoke.spec.js` — @smoke

**目标**：全页面 200 不白屏 + 按钮渲染 + 输入框可交互

```javascript
// 每条用例都是 @smoke，每次改完必跑

test('Dashboard 打开无白屏 + 无报错', async ({ page }) => {
  const errors = setupConsoleCapture(page)
  await page.goto('/')
  await expect(page.locator('.dashboard')).toBeVisible()
  assertNoConsoleErrors(errors)
})

test('市场分析页面按钮和输入框均可交互', async ({ page }) => {
  await page.goto('/market-analysis')
  // 市场研判按钮
  await assertButtonRendered(page, '生成市场研判')
  // AI 顾问输入框
  await assertInputInteractable(page, '输入您的投资问题')
  // 发送提问按钮
  await assertButtonRendered(page, '发送提问')
  // 个股搜索
  await assertInputInteractable(page, '搜索 ETF 或股票')
  // 板块搜索
  await assertInputInteractable(page, '搜索板块/概念')
})

test('组合分析页面 AI 工具入口按钮可见', async ({ page }) => {
  await page.goto('/portfolio-analysis')
  await assertButtonRendered(page, '智能设计ETF组合方案')
  await assertButtonRendered(page, '策略检查分析')
  await assertButtonRendered(page, '历史记录')
})

test('资讯页面加载', async ({ page }) => {
  await page.goto('/news')
  // 重要性筛选按钮存在
  for (const label of ['1 一般', '2 关注', '3 重要', '4 紧急', '5 重大']) {
    await expect(page.locator(`text=${label}`).first()).toBeVisible()
  }
})

test('WS 断连后应有提示（News 页面）', async ({ page }) => {
  // News 页面有一个 WS 连接状态指示器
  await page.goto('/news')
  // 先等待页面加载完成（WS 可能已连接，此时 status-dot--on 会显示）
  // 模拟 WebSocket 断开
  await page.route('**/ws/**', route => route.abort('connectionrefused'))
  // 等待状态更新：--on 类应消失，灰点状态可见
  await expect(page.locator('.status-dot')).toBeVisible()
  await expect(page.locator('.status-dot--on')).toHaveCount(0)
})

test('Token 监控页面加载', async ({ page }) => {
  await page.goto('/token-monitor')
  await expect(page.locator('text=Token 消耗趋势')).toBeVisible()
})
```

---

#### `02-dashboard.spec.js`

**目标**：首页 Tab 切换 + 资金输入 + 数据渲染

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 2.1 | Tab 切换渲染不同面板 | 点击「场内」→「场外」→「综合」 | 每次切换后对应 panel 可见 |
| 2.2 | 资金输入栏可编辑 | 在 capitalOn input 输入 1000000 | value 变为 1,000,000 |
| 2.3 | 全球指数刷新 | 点击「刷新」按钮 | 等待请求完成，指数卡片渲染 > 0 |
| 2.4 | 饼图渲染 | 在有数据的 tab 下等待 | canvas 元素渲染 |
| 2.5 | 盈亏明细可滚动 | 切换到有数据的 tab | 表格行数 > 0 |
| 2.6 | 错误降级 | 拦截 API 使 /calculate 返回 500 | ErrorOverlay 显示，页面不白屏 |

```javascript
test('2.1 Tab 切换渲染不同面板', async ({ page }) => {
  await page.goto('/')
  // 点击「场内」
  await page.click('text=场内')
  await expect(page.locator('text=场内分配')).toBeVisible()
  // 点击「场外」
  await page.click('text=场外')
  await expect(page.locator('text=场外分配')).toBeVisible()
  // 点击「综合」
  await page.click('text=综合')
  await expect(page.locator('text=场内分配')).toBeVisible()
  await expect(page.locator('text=场外分配')).toBeVisible()
})
```

---

#### `03-portfolio-mgr.spec.js`

**目标**：持仓管理的增删改查 + 分页 + 导入导出

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 3.1 | Tab 切换 | 点击「场内」→「场外」 | 对应表单提示文字变化 |
| 3.2 | 搜索 ETF | 在搜索框输入 "510300" | 下拉出现候选项 |
| 3.3 | 选择候选项 | 点击候选项 | 表单填充 symbol/name |
| 3.4 | 填写完整表单 | 输入成本价 1.234 + 份额 1000 + 目标权重 0.1 | 字段有值 |
| 3.5 | 提交添加 | 点击提交按钮 | 表格新增一行 |
| 3.6 | 删除 ETF | 点击行删除按钮 | 行消失 |
| 3.7 | 编辑 ETF | 双击行 → 修改权重 → 保存 | 表格更新 |
| 3.8 | 翻页 | 添加足够多 ETF 后点击下一页 | 页码变化，表格内容变化 |
| 3.9 | 导出 | 点击导出按钮 | 下载 .csv 文件 |
| 3.10 | 导入 | 点击导入 → 选择文件 | 表格行数增加 |

---

#### `04-ai-tools.spec.js`

**目标**：组合设计 + 策略检查完整流程

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 4.1 | 智能设计入口 | 点击「智能设计ETF组合方案」 | DesignWizard 显示 |
| 4.2 | 输入资金并提交 | 输入 500000 → 点击「开始设计」 | DesignLoading 显示 |
| 4.3 | 设计完成 | 等待 task 完成（轮询/poll） | DesignResult 显示，plans > 0 |
| 4.4 | 方案卡片显示 | 在 result 中查看卡片 | 三套方案（进攻/平衡/防御）均显示 |
| 4.5 | 报告 Tab 切换 | 点击「完整报告」Tab | Markdown 报告渲染 |
| 4.6 | 应用方案 | 点击「应用此方案」 | 提示成功 |
| 4.7 | 策略检查入口 | 点击「策略检查分析」 | StrategyCheckModal 显示 |
| 4.8 | 弹窗选择类型 | 点击「场内组合」 | Modal 关闭，StrategyCheckResult 显示 |
| 4.9 | 历史记录查看 | 点击「历史记录」 | 列表显示过往方案 |
| 4.10 | 历史详情点击 | 点击某条历史记录 | 跳转到详情 / 展示详细结果 |

```javascript
test('4.1-4.2 智能设计完整流程（@smoke）', async ({ page }) => {
  await page.goto('/portfolio-analysis')
  // 确保在 AI 工具 Tab
  await page.click('text=AI工具')
  // 点击智能设计按钮
  await page.click('text=智能设计ETF组合方案')
  // Wizard 显示
  await expect(page.locator('text=请输入投资资金')).toBeVisible()
  // 输入资金
  await page.fill('input[type="number"]', '500000')
  // 提交
  await page.click('text=开始设计')
  // Loading 显示
  await expect(page.locator('text=正在提交任务')).toBeVisible()
  // 等待完成（最多 180s）
  await expect(page.locator('text=方案已生成')).toBeVisible({ timeout: 180000 })
  // 方案卡片展示
  await expect(page.locator('text=进攻型')).toBeVisible()
  await expect(page.locator('text=平衡型')).toBeVisible()
  await expect(page.locator('text=防御型')).toBeVisible()
})
```

---

#### `05-market-tabs.spec.js`

**目标**：A股/港股/美股/全球 Tab 切换，所有区域联动

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 5.1 | Tab 切换 UI | 依次点击 A股/港股/美股/全球 | active 类正确切换 |
| 5.2 | 市场研判 Tab 联动 | 切换到港股 → 生成报告 | 报告内容提及港股 |
| 5.3 | 自选列表 Tab 联动 | 切换到港股 → 查看自选 | 只显示 HK 类型 |
| 5.4 | AI 顾问 Tab 联动 | 切换到美股 → 提问 | context.market = 'US' |
| 5.5 | 板块分析 Tab 联动 | 切换到港股 → 选择板块 | API 参数包含 market=HK |
| 5.6 | 标的分析 Tab 联动 | 切换到全球 → 搜索 | asset_type 传 'global' |
| 5.7 | 指数分析 Tab 联动 | 切换到全球 → 查看指数 | 显示全球指数 |

---

#### `06-watchlist.spec.js`

**目标**：自选完整操作流程

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 6.1 | 添加自选弹窗 | 点击「添加自选」 | Modal 显示 |
| 6.2 | 搜索标的 | 在 Modal 中输入代码 "000001" | 搜索建议下拉显示 |
| 6.3 | 选择资产类型 | 下拉选择「A股 ETF/股票」 | select 值更新 |
| 6.4 | 填写备注 | 输入 "短线关注" | 备注字段有值 |
| 6.5 | 提交添加 | 点击「添加」按钮 | Modal 关闭，列表新增一行 |
| 6.6 | 编辑备注 | 点击 ✏️ 按钮 | prompt 弹窗 |
| 6.7 | 删除自选 | 点击 🗑️ 按钮 | 确认后行消失 |
| 6.8 | 空状态 | 清空所有自选 | 显示「暂无自选标的」占位 |

```javascript
test('6.1-6.5 添加自选完整流程（@smoke）', async ({ page }) => {
  await page.goto('/market-analysis')
  // 点击添加自选
  await page.click('text=添加自选')
  // 等待 Modal 弹出
  await expect(page.locator('text=添加自选标的')).toBeVisible()
  // 输入代码
  const input = page.locator('#wl-symbol')
  await input.fill('000001')
  // 选择资产类型
  await page.selectOption('#wl-asset-type', 'A')
  // 输入备注
  await page.fill('#wl-notes', '长线跟踪')
  // 点击添加
  await page.click('button:has-text("添加")')
  // Modal 关闭
  await expect(page.locator('text=添加自选标的')).not.toBeVisible()
})
```

---

#### `07-ai-advisor.spec.js`

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 7.1 | 输入框可交互 | 在输入框输入文字 | 输入框有值 |
| 7.2 | 发送按钮状态 | 空输入时按钮 disabled → 输入后 enabled | disabled 状态变化 |
| 7.3 | 发送提问 | 输入问题 → 点击发送 | loading 状态出现，回答显示 |
| 7.4 | 错误处理 | 拦截 API 使其失败 | 错误提示显示 |

---

#### `08-sector-analysis.spec.js`

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 8.1 | 行业/概念切换 | 点击「概念板块」radio | 选项切换，列表清空 |
| 8.2 | 搜索板块 | 输入 "新能源" | 下拉显示匹配结果 |
| 8.3 | 选择板块 | 点击候选项 | 选中 badge 显示 |
| 8.4 | AI 分析 | 点击「AI 分析板块」 | loading → 报告显示 |
| 8.5 | 清除选择 | 点击 badge 上的 × | 选择清空，返回空状态 |

---

#### `09-symbol-analysis.spec.js`

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 9.1 | 搜索建议 | 输入 "510300" | 下拉有结果，type 正确 |
| 9.2 | 键盘导航 | ArrowDown/ArrowUp 移动高亮 | active 类跟随 |
| 9.3 | Tab 补全 | 按 Tab | completionFull 显示 |
| 9.4 | 选择标的 | 点击候选项 | selectedSearchItem 设置，搜索框显示 name(code) |
| 9.5 | 图表渲染 | 选择标的 → 等待数据 | canvas 或 echarts 容器渲染 |
| 9.6 | 周期切换 | 点击「周K」/「月K」 | 图表更新 |
| 9.7 | K线/分时切换 | 点击「分时」 | 图表切换为分时模式 |
| 9.8 | 技术指标切换 | 勾选/取消 MACD checkbox | MACD sub-chart 显示/隐藏 |
| 9.9 | 综合信号显示 | 等待信号加载 | signal badge 显示（买入/持有/卖出） |
| 9.10 | AI 研报 | 点击「AI 研报」 | loading → 报告显示 |

---

#### `10-news.spec.js`

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 10.1 | 页面加载 | 导航到 /news | 资讯列表非空 |
| 10.2 | 重要性筛选 | 点击 4 星按钮 | 只显示 >= 4 星的条目 |
| 10.3 | AI 分析 | 点击「AI 智能分析」 | 分析结果面板显示 |
| 10.4 | WS 连接状态 | 等待连接 | status-dot--on 激活 |

---

#### `11-token-monitor.spec.js`

| # | 用例 | 步骤 | 断言 |
|---|------|------|------|
| 11.1 | 统计卡片 | 页面加载 | 5 张卡片均显示数字 |
| 11.2 | 日/月切换 | 点击「按月」 | 图表更新 |
| 11.3 | 错误率高亮 | 如错误率 > 5% | text-danger 类激活 |

---

#### `12-regression.spec.js`

**目标**：固定回归场景，确保不会二次出现问题

```javascript
// 每次修复一个 issue 后，在这里追加对应回归测试

test('#1 组合设计提交不报 registerTaskCompletion 错误', ...)
test('#4 生成市场研判按钮渲染为 button 而非纯文本', ...)
test('#6 AI 顾问发送按钮可见', ...)
test('#8 标的搜索输入框可输入', ...)
test('#14 Dashboard 不白屏（API 全失败时）', async ({ page }) => {
  // 拦截所有数据 API 返回 500
  await page.route('**/api/v1/**', route => route.fulfill({ status: 500 }))
  await page.goto('/')
  // 页面不白屏，应显示 ErrorOverlay 或空状态
  await expect(page.locator('.dashboard')).toBeVisible()
  // 控制台无 Uncaught error
})
```

---

## 6. 测试数据管理

### 6.1 策略

| 数据类型 | 方式 | 说明 |
|---------|------|------|
| ETF 列表 | API mock (`page.route`) | 前端搜索时 mock 返回固定数据，不依赖真实行情 |
| 组合数据 | DB seed | 测试前向 SQLite 插入 3-5 条 ETF 记录 |
| 设计方案 | DB seed | 插入 2 条设计历史 + 1 条策略检查历史 |
| 全球指数 | API mock | mock 恒生/标普/纳斯达克等固定数据 |
| LLM 响应 | API mock | mock stream 端点返回固定报告文本 |

### 6.2 种子脚本

```javascript
// e2e/utils/seed.js
// ⚠️ 不直接写入 SQLite（避免依赖 better-sqlite3 和文件路径问题）
// 改为通过后端 API 注入测试数据。后端应提供 /api/v1/admin/seed 端点。

const BASE = 'http://127.0.0.1:8000'

export async function seedDatabase() {
  // 通过 API 添加测试 ETF
  const testEtfs = [
    { symbol: '510300', name: '沪深300ETF', asset_type: 'A', portfolio_type: 'on_exchange', avg_cost: 3.850, shares_held: 1000, target_weight: 0.25 },
    { symbol: '510050', name: '上证50ETF', asset_type: 'A', portfolio_type: 'on_exchange', avg_cost: 2.500, shares_held: 2000, target_weight: 0.15 },
    { symbol: '513100', name: '纳指ETF', asset_type: 'US', portfolio_type: 'off_exchange', avg_cost: 1.200, shares_held: 500, target_weight: 0.10 },
  ]
  for (const etf of testEtfs) {
    await fetch(`${BASE}/api/v1/portfolio/etfs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(etf),
    })
  }

  // 通过 API 创建设计历史
  await fetch(`${BASE}/api/v1/admin/seed/design`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      capital: 500000,
      risk_profile: 'balanced',
      design_text: '# 测试报告\n\n## 方案概览\n...',
      created_at: new Date().toISOString(),
    }),
  })
}
```
```

### 6.3 LLM 端点的 Mock 策略

```javascript
// LLM 流式端点（/analysis/llm-report/stream 等）需要特殊处理。
// 直接用 fetch 拦截会导致 stream 被整个吞掉，需要用 Server-Sent Events 格式返回。

export async function mockLLMStream(page, urlPattern, tokens = []) {
  await page.route(urlPattern, async route => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        for (const token of tokens) {
          controller.enqueue(encoder.encode(`event: token\ndata: ${JSON.stringify({ token })}\n\n`))
        }
        controller.enqueue(encoder.encode(`event: done\ndata: ${JSON.stringify({ full_text: tokens.join(''), disclaimer: '⚠️ 测试用模拟数据' })}\n\n`))
        controller.close()
      }
    })
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' },
      body: stream,
    })
  })
}

// 异步任务端点（/portfolio/design-async 等）返回 task_id，前端轮询完成。
// Mock 设计：让第一次返回 running，第二次返回 completed。
export async function mockAsyncTask(page, submitPattern, statusPattern, result = {}) {
  let pollCount = 0
  await page.route(submitPattern, async route => {
    await route.fulfill({
      status: 202,
      body: JSON.stringify({ task_id: 'mock-task-001', design_id: 'mock-design-001' }),
    })
  })
  await page.route(statusPattern, async route => {
    pollCount++
    if (pollCount >= 3) {
      await route.fulfill({ status: 200, body: JSON.stringify({ status: 'completed', ...result }) })
    } else {
      await route.fulfill({ status: 200, body: JSON.stringify({ status: 'running', progress: pollCount * 30 }) })
    }
  })
}
```

### 6.4 API Mock 示例

```javascript
// 在 test 中
test.beforeEach(async ({ page }) => {
  // Mock 全球指数
  await page.route('**/api/v1/market/indices/global', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        indices: {
          'asia': [{ symbol: 'HSI', name: '恒生指数', price: 28000, change_pct: 0.5 }],
          'us': [{ symbol: 'SPX', name: '标普500', price: 5500, change_pct: -0.2 }],
        }
      })
    })
  })
  
  // Mock 搜索
  await page.route('**/api/v1/market/search*', async route => {
    await route.fulfill({
      status: 200,
      body: JSON.stringify([
        { symbol: '510300', name: '沪深300ETF', type: 'ETF' },
        { symbol: '000001', name: '平安银行', type: '股票' },
      ])
    })
  })
})
```

---

## 7. CI 集成与执行流程

### 7.1 每次修复后的标准流程

```
1. 改代码（后端 / 前端）
2. 跑后端 verify_e2e.py  →  ALL PASS
3. 跑前端 E2E @smoke     →  ALL PASS  （< 30s）
4. 跑前端 E2E full       →  ALL PASS  （3-5 min）
5. 提交 commit
```

### 7.2 新增功能流程

```
1. 写 API 契约 (api-contracts/*.md)
2. 写 E2E spec（先写 test case）
3. 实现功能
4. 跑 E2E → PASS
5. 提交
```

### 7.3 Git hooks / CI (推荐)

```yaml
# .github/workflows/e2e.yml
name: E2E Tests
on: [push, pull_request]

jobs:
  e2e:
    runs-on: windows-latest  # 与本地开发一致
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      
      - name: Install dependencies
        run: |
          cd backend && python -m pip install -r requirements.txt
          cd frontend && npm ci
          npx playwright install chromium
      
      - name: Verify backend
        run: cd backend && python scripts/verify_e2e.py
      
      - name: Run E2E tests
        run: cd frontend && npm run test:e2e
```

---

## 8. 验收标准

### 8.1 覆盖率要求

| 维度 | 目标 | 衡量方式 |
|------|------|---------|
| 页面覆盖 | 100%（5 个路由） | 每个路由至少 1 个 @smoke 用例 |
| 组件覆盖 | 100%（所有 .vue 文件） | 每个组件至少 1 个测试交互 |
| 操作链路覆盖 | 完整流程覆盖 | 上表所有用例 PASS |
| 回归覆盖 | 每次修 bug 追加用例 | regression.spec.js 用例数 >= bug 数 |

### 8.2 质量标准

```javascript
// 禁止存在的模式（会被 E2E 捕获）
❌ 页面白屏（pageerror 捕获）
❌ 按钮显示为纯文本（assertButtonRendered 检测背景色）
❌ 输入框 disabled 且无理由（assertInputInteractable 检测 enabled）
❌ API 500 导致页面崩溃（API mock 测试 error handling）
❌ WS 断开后无任何提示（状态指示器检测）
```

### 8.3 维护规则

1. **每次新增 UI 组件** → 添加对应的 E2E spec
2. **每次修复 bug** → 在 `12-regression.spec.js` 追加回归测试
3. **每次重构** → 先确保所有 @smoke 用例通过
4. **视觉基线** → `test:e2e:visual` 每周更新基线截图

---

## 9. 后端 API E2E 覆盖计划（verify_e2e.py 扩展）

> `backend/scripts/verify_e2e.py` 当前仅覆盖约 15% 的后端端点。
> 本节设计补齐剩余 85% 的端点测试，覆盖全部 ~78 个 REST 端点 + 5 个 WebSocket 端点。
> 实现方式：扩展 verify_e2e.py（Python requests），与 Playwright 前端 E2E 互补。

### 9.1 当前覆盖 vs 目标

| 模块 | 总端点 | 覆盖目标 | 新增用例数 | 优先级 |
|------|--------|---------|-----------|--------|
| Health | 1 | 1/1 ✅ | 0 | P0 |
| Market | 29 | 29/29 | 28 | P0 |
| Portfolio | 23 | 23/23 | 13 | P0 |
| Analysis | 12 | 12/12（仅验证 200/4xx，不依赖 LLM） | 12 | P1 |
| News | 5 | 5/5 | 5 | P1 |
| Admin | 3 | 3/3 | 3 | P2 |
| WebSocket | 5 | 5/5（实际连接测试） | 5 | P1 |
| **总计** | **~78** | **78/78** | **~66** | |

### 9.2 测试设计原则

1. **分层验证**：
   - 存活检查（200/4xx 状态码）
   - 响应结构检查（必含字段 + 字段类型）
   - 业务正确性（如 POST 创建后 GET 能查到）
   
2. **不依赖外部数据源**：
   - 行情端点（realtime / history / indices）可能依赖外部数据，用超时 + 降级容忍
   - 核心 crud 端点（etfs / watchlist / designs）使用测试专用种子数据

3. **与 Playwright 分工**：
   - `verify_e2e.py`：后端 API 存活 + 响应结构 + 数据持久化
   - Playwright：前端渲染 + 用户交互 + 端到端流程
   - 两者互不替代，共同组成测试安全网

### 9.3 Market 模块测试用例（新增 28 个）

```
┌────────────────────────────────────────────────────────────┐
│ verify_e2e.py Section: Market                              │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ # ├ endpoint             │ 验证内容                        │
│───┼──────────────────────┼─────────────────────────────────│
│ 1 │ GET /realtime        │ 200, 返回 list, 每项含 symbol   │
│ 2 │ GET /realtime/portfolio│ 200, 返回 list               │
│ 3 │ GET /realtime/batch  │ 200, 传入 symbols=510300,000001│
│ 4 │ GET /realtime/{sym}  │ 200, 返回 dict 含 price        │
│ 5 │ GET /indices/global  │ 200 ✅ 已覆盖                  │
│ 6 │ GET /history/{sym}   │ 200, 返回 list 含 K 线数据     │
│ 7 │ GET /search          │ 200, keyword=510300 → 有结果   │
│ 8 │ GET /search/stocks   │ 200, keyword=000001 → 有结果   │
│ 9 │ GET /indices/meta    │ 200, 返回 list 含 symbol/name  │
│10 │ GET /indices/search  │ 200, keyword=HSI → 有结果      │
│11 │ GET /indicators/{sym}│ 200, 返回 dict 含 ma/rsi/macd  │
│12 │ GET /signal/{sym}    │ 200, 返回 dict 含 signal/score │
│13 │ GET /chart/{sym}     │ 200, 返回 dict 含 kline/volume │
│14 │ GET /fundamentals/{s}│ 200 或 503（容忍外部超时）      │
│15 │ GET /sentiment       │ 200, 返回 dict 含关键情绪指标  │
│16 │ GET /sectors         │ 200, 返回 list                 │
│17 │ GET /sectors/industry│ 200, 返回 list 含 sector_name  │
│18 │ GET /sectors/concept │ 200, 返回 list 含 plate_name   │
│19 │ GET /sectors/industry-cls│ 200, 返回 list             │
│20 │ GET /sectors/{code}/stocks│ 200, 返回 list 含 symbol   │
│21 │ GET /sectors/{code}/popular│ 200, 返回 list            │
│22 │ GET /hot-plates      │ 200, 返回 list                 │
│23 │ GET /stock-hot-rank  │ 200, 返回 list                 │
│24 │ GET /wind            │ 200, 返回 list                 │
│25 │ POST /watchlist      │ 201, 创建后返回含 id           │
│26 │ GET /watchlist       │ 200, 返回 list 含刚创建的条目  │
│27 │ PUT /watchlist/{id}  │ 200, 更新 notes 后返回更新值   │
│28 │ DELETE /watchlist/{id}│ 204, 删除后 GET 不再返回      │
│29 │ DELETE /watchlist    │ 200, 批量删除                  │
└────────────────────────────────────────────────────────────┘
```

### 9.4 Portfolio 模块测试用例（新增 13 个）

```
┌────────────────────────────────────────────────────────────┐
│ verify_e2e.py Section: Portfolio                           │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ # ├ endpoint                   │ 验证内容                  │
│───┼────────────────────────────┼───────────────────────────│
│ 1 │ GET /etfs                  │ 200, 返回 list            │
│ 2 │ POST /etfs                 │ 201, 创建新 ETF 条目      │
│ 3 │ PUT /etfs/{symbol}         │ 200, 更新 target_weight   │
│ 4 │ DELETE /etfs/{symbol}      │ 204, 删除后 GET 不再返回  │
│ 5 │ POST /calculate            │ 200, 返回 allocations     │
│ 6 │ POST /daily-pnl            │ 200, 返回 items 含 pnl    │
│ 7 │ POST /apply-strategy       │ 200, 返回结果             │
│ 8 │ POST /apply-design         │ 200, 返回结果             │
│ 9 │ GET /pnl-history           │ 200, 返回历史数据         │
│10 │ GET /export                │ 200, 返回 CSV/JSON        │
│11 │ POST /import               │ 200, 导入 CSV → 行数增加  │
│12 │ GET /drift-check           │ 200, 返回偏离分析         │
│13 │ GET /designs/{id}/status   │ 200, 返回 status 字段     │
│14 │ GET /tasks                 │ 200, 返回 task list       │
│   │                            │                           │
│   │ 以下已覆盖：                                            │
│   │ GET /designs               │ ✅                        │
│   │ GET /designs/{id}          │ ✅                        │
│   │ DELETE /designs/{id}       │ ⚠️ 测试后需清理            │
│   │ POST /design-async         │ ✅                        │
│   │ POST /strategy-check-async │ ✅                        │
│   │ GET /strategy-check-result │ ✅                        │
│   │ GET /strategy-checks       │ ✅                        │
│   │ GET /strategy-checks/{id}  │ ✅                        │
│   │ GET /tasks/{id}            │ ✅（作为轮询的一部分）      │
└────────────────────────────────────────────────────────────┘
```

### 9.5 Analysis 模块测试用例（新增 12 个）

```
┌────────────────────────────────────────────────────────────┐
│ verify_e2e.py Section: Analysis                            │
├────────────────────────────────────────────────────────────┤
│ 注意：Analysis 端点大多依赖 DeepSeek LLM。                │
│ 测试策略：只验证 200/4xx 状态码 + 响应结构，              │
│ 不对 LLM 返回内容做断言（避免 flaky）。                    │
│ 流式端点（/stream）只检查 200 和 Content-Type。           │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ # ├ endpoint                    │ 验证内容                 │
│───┼─────────────────────────────┼──────────────────────────│
│ 1 │ POST /llm-report            │ 200, 返回文本内容（字段名以实际为准）      │
│ 2 │ POST /llm-advice            │ 200, 返回文本内容         │
│ 3 │ POST /llm-news-analysis     │ 200, 返回文本内容         │
│ 4 │ POST /news-impact           │ 200, 返回文本内容         │
│ 5 │ POST /portfolio-review      │ 200, 返回文本内容         │
│ 6 │ POST /sector-analysis       │ 200, 返回文本内容         │
│ 7 │ POST /symbol-analysis       │ 200, 返回文本内容         │
│ 8 │ POST /llm-report/stream     │ 200, Content-Type SSE    │
│ 9 │ POST /llm-advice/stream     │ 200, Content-Type SSE    │
│10 │ POST /sector-analysis/stream│ 200, Content-Type SSE    │
│11 │ POST /symbol-analysis/stream│ 200, Content-Type SSE    │
│12 │ POST /news-impact/stream    │ 200, Content-Type SSE    │
└────────────────────────────────────────────────────────────┘
```

### 9.6 News 模块测试用例（新增 5 个）

```
┌────────────────────────────────────────────────────────────┐
│ verify_e2e.py Section: News                                │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ # ├ endpoint              │ 验证内容                       │
│───┼───────────────────────┼───────────────────────────────│
│ 1 │ GET /headlines        │ 200, 返回 list 含 title/source │
│ 2 │ GET /macro            │ 200, 返回 list 含 title       │
│ 3 │ GET /global           │ 200, 返回 list 含 title       │
│ 4 │ GET /stock/{symbol}   │ 200, 返回 list               │
│ 5 │ GET /research/{symbol}│ 200, 返回 list               │
└────────────────────────────────────────────────────────────┘
```

### 9.7 Admin 模块 + WebSocket 测试用例（新增 8 个）

```
┌────────────────────────────────────────────────────────────┐
│ verify_e2e.py Section: Admin + WebSocket                   │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ Admin:                                                     │
│ # ├ endpoint                      │ 验证内容              │
│───┼───────────────────────────────┼───────────────────────│
│ 1 │ GET /token-usage              │ 200, 含 summary 对象   │
│ 2 │ GET /token-usage/timeseries   │ 200, 含 data 数组      │
│ 3 │ GET /token-usage/failures     │ 200, 含 failures 数组  │
│                                                            │
│ WebSocket（使用 websockets 库实际连接）：                    │
│ # ├ path                          │ 验证内容              │
│───┼───────────────────────────────┼───────────────────────│
│ 4 │ WS /ws/market/{symbol}        │ 连接成功，3s 内收到 msg │
│ 5 │ WS /ws/news                   │ 连接成功，保持 5s      │
│ 6 │ WS /ws/portfolio              │ 连接成功               │
│ 7 │ WS /ws/task-notifications     │ 连接成功               │
│ 8 │ WS /ws/design-report/{sid}    │ 连接成功               │
└────────────────────────────────────────────────────────────┘
```

> ⚠️ 依赖：WebSocket 测试需要安装 `websockets` 库：
> ```bash
> pip install websockets
> # 或添加到 requirements.txt: websockets>=12.0
> ```

WebSocket 测试示例（Python）：

```python
# 添加在 verify_e2e.py 末尾的 WS 测试
import asyncio
from websockets import connect  # pip install websockets

section("11. WebSocket 实际连接测试")

async def test_ws(path, timeout=5):
    try:
        async with connect(f"ws://127.0.0.1:8000{path}", timeout=3) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
            check(f"WS {path} 连接成功并收到消息", True, str(msg)[:60])
    except Exception as e:
        check(f"WS {path} 连接失败", False, str(e)[:60])

asyncio.run(test_ws("/api/v1/ws/market/510300"))
asyncio.run(test_ws("/api/v1/ws/news"))
```

### 9.8 执行策略

| 阶段 | 内容 | 新增用例 | 预计耗时 |
|------|------|---------|---------|
| Phase 1 (P0) | Market (indices/history/search/sectors) + Portfolio (etfs crud/calculate/pnl) | ~25 | 15s |
| Phase 2 (P1) | Analysis (非流式) + News + Watchlist 全流程 | ~20 | 30s |
| Phase 3 (P1) | WebSocket 实际连接 + Stream 端点 | ~10 | 20s |
| Phase 4 (P2) | Admin + 边缘情况（404/4xx/空结果） | ~11 | 10s |
| **总计** | **全覆盖 ~78 端点** | **~66** | **~75s** |

### 9.9 前后端 E2E 测试矩阵

```
                        ┌──────────────────────┐
                        │    E2E 覆盖矩阵       │
                        ├──────────┬───────────┤
                        │  后端      │  前端      │
                        │ verify_e2e │ Playwright │
 ├────────────┼──────────┼───────────┤
 │ 健康检查    │  ✅       │   —       │
 │ API 存活   │  ✅       │   —       │
 │ 响应结构   │  ✅       │   —       │
 │ 数据持久化 │  ✅       │   —       │
 │ 页面渲染   │   —       │  ✅       │
 │ 按钮交互   │   —       │  ✅       │
 │ 用户流程   │   —       │  ✅       │
 │ 视觉回归   │   —       │  ✅       │
 │ WS 推送    │  ⚠️ 连接   │  ✅ 内容   │
 │ LLM 响应   │  ✅ 格式   │  ✅ mock  │
 └────────────┴──────────┴───────────┘
```

### 9.10 verify_e2e.py 结构重组（推荐）

```python
# 当前：顺序执行 8 个 section
# 重组后：按模块分组，支持 --module 参数选择性运行

"""
用法扩展:
  python scripts/verify_e2e.py                 ← 全量（~75s）
  python scripts/verify_e2e.py --module market  ← 仅 Market 模块
  python scripts/verify_e2e.py --module ws     ← 仅 WebSocket
  python scripts/verify_e2e.py --smoke         ← 仅 P0 存活检查（< 15s）
"""

def section_market():     # 29 个 endpoint
def section_portfolio():  # 23 个 endpoint  
def section_analysis():   # 12 个 endpoint
def section_news():       # 5 个 endpoint
def section_admin():      # 3 个 endpoint
def section_ws():         # 5 个 endpoint
```

### 9.11 冗余/废弃 API 端点清理计划

> 通过交叉比对 `backend/app/routers/*.py` 的全部路由与 `frontend/src/api/index.js` + 各组件 `fetchJson` 调用，发现以下端点未被任何前端代码调用。

#### 9.11.1 未使用的端点（建议清理）

```
Market 模块（10 个未使用）：
┌──────────────────────────┬──────────────────────────────────┬──────────────┐
│ 端点                      │ 说明                           │ 建议处理      │
├──────────────────────────┼──────────────────────────────────┼──────────────┤
│ GET /indices/search      │ 指数搜索（已有 /indices/meta）    │ 删除或合并    │
│ GET /fundamentals/{sym}  │ Tushare 基本面数据               │ 保留（未来）  │
│ GET /sentiment           │ 市场情绪指标                     │ 保留（未来）  │
│ GET /sectors             │ 板块热度（与 industry/concept 重叠）│ 删除（冗余）  │
│ GET /sectors/industry-cls│ 行业板块实时行情（财联社）        │ 保留（备用）  │
│ GET /sectors/{code}/stocks │ 板块成分股                     │ 保留（未来）  │
│ GET /sectors/{code}/popular│ 板块热门个股                   │ 保留（未来）  │
│ GET /hot-plates          │ 热点板块及涨停股                 │ 保留（未来）  │
│ GET /stock-hot-rank      │ 热门个股排名                    │ 保留（未来）  │
│ GET /wind                │ 今日风口/主线板块                │ 保留（未来）  │
└──────────────────────────┴──────────────────────────────────┴──────────────┘

Portfolio 模块（1 个未使用）：
┌──────────────────────────┬──────────────────────────────────┬──────────────┐
│ GET /designs/{id}/status │ 设计任务状态（/designs/{id} 已含）│ 删除（冗余）  │
└──────────────────────────┴──────────────────────────────────┴──────────────┘

Analysis 模块（3 个未使用）：
┌──────────────────────────┬──────────────────────────────────┬──────────────┐
│ POST /portfolio-review   │ 组合回顾（非流式）               │ 删除（无人用）│
│ POST /sector-analysis    │ 板块分析非流式（仅用 stream 版）  │ 删除（无人用）│
│ POST /symbol-analysis    │ 标的分析非流式（仅用 stream 版）  │ 删除（无人用）│
└──────────────────────────┴──────────────────────────────────┴──────────────┘

总计 14 个无人调用的端点，其中 5 个建议直接删除（冗余或已被 stream 版取代），
9 个保留但暂不在前端使用（可能是为未来功能准备的）。
```

#### 9.11.2 测试文件中的废弃引用

```
文件                                 │ 问题                         │ 建议
─────────────────────────────────────┼─────────────────────────────┼─────────
frontend/src/utils/changeClass.spec.js│ 仍 mock 已删除的             │ 移除 mock
 line 36-37                          │ portfolioDesignStream /     │
                                     │ portfolioDesign             │
```

#### 9.11.3 清理原则

1. **删除**：前端已完全不调用、且有同功能替代（非流式→流式）的端点
2. **保留但标记**：未来可能使用、但不影响当前功能的端点（在代码中加 `# TODO: 未接入前端` 注释）
3. **不删**：被 `verify_e2e.py` 或其他后端测试引用的端点（即使前端没用）
4. **清理时机**：在完成全量 verify_e2e 覆盖（Phase 1-4）之后，有一份完整的测试安全网时再删，防止误删后无法恢复

---

## 附录：前期 17 个 issue 的回归覆盖

> 每个 issue 修复后追加到 `12-regression.spec.js`

| Issue | 回归测试方案 |
|-------|------------|
| #1 组合设计 | 4.1-4.3 流程测试 → 不报 registerTaskCompletion 错误 |
| #2 策略检查弹窗 | 4.7-4.8 Modal 弹出 → 选择类型 → 不白屏 |
| #3 历史记录分类 | 4.9 历史列表显示，检查 taskType 标签正确 |
| #4 市场研判按钮 | 1.2 assertButtonRendered('生成市场研判') |
| #5 自选列表慢 | 6.1-6.5 添加全流程 + 30s 超时断言 |
| #6 发送按钮 | 1.2 assertButtonRendered('发送提问') |
| #7 板块输入 | 8.2-8.3 搜索/选择板块 |
| #8 标的搜索 | 9.1 搜索建议弹出 + 9.4 选择标的 |
| #9 资讯推送 | 10.1-10.2 列表渲染 + 筛选 |
| #10 数据源 | 10.1 检查来源是否多样化 |
| #11 个股分析 | 9.10 AI 研报按钮 → 报告渲染 |
| #12 份额列 | 3.5 添加后有份额显示，非 N/A |
| #13 K线图 | 9.5 图表渲染 + 9.6-9.8 周期/指标切换 |
| #14 Dashboard 白屏 | 2.6 错误降级 + 12 regression 测试 |
| #15 Token 定价 | 11.1 卡片显示 |
| #16 Tab 联动 | 5.1-5.7 所有 Tab 切换 → 功能联动 |
| #17 UI 改进 | visual 截图对比 |
