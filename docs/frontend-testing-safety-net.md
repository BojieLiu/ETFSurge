# Frontend Testing & Safety Net Plan

> 目标：为 UI 重构和性能优化提供充分的测试防护，确保每次修改可放心提交。
> 核心理念：分层防护，快速反馈，精准定位问题。
> ✅ **2026-07-27 更新**：测试总数从 175→253（新增 ChartComponents.spec.js 16 条）。Phase A/B/C1/C2 全部完成。C3（E2E Charts）和 C4（截图基线）待 UI 优化定型后重新评估。

---

## 1. 现有测试现状（2026-07-26 更新）

> ⚠️ 本文档初始版本撰写于 Phase 2.5 前。**2026-07-29 审计更新**：现为 25 个 spec 文件，256 个测试用例（252 通过，4 失败）。

### 单元测试（Vitest）— **25 个 spec 文件，252 通过 / 256 总计（4 失败）**

| 层级 | 测试内容 | 数量 | 质量 |
|------|---------|:----:|------|
| 🟢 Utils | `changeClass`、`formatDate`、`newsLevel` | **19 个**（5+12+6） | ✅ 良好，覆盖主要逻辑 |
| 🟡 Stores | `taskStore` — 任务状态机 | **5 个** | ✅ 覆盖了 hasRunningTask/activeTaskId |
| 🟢 Composable | `useNewsWS` + `useDashboardData` + `useLLMStream` + `useMarketSearch` + `useMarketWS` + `useSectorAnalysis` | **71 个**（WS 3 + Dashboard 35 + LLM 6 + Search 11(2❌) + MarketWS 6 + Sector 10(2❌)） | ⚠️ useSectorAnalysis(2/10 失败) + useMarketSearch(2/11 失败) 需修复 |
| 🟡 Views | `DashboardAiTools` — 设计报告 | **10 个**（report 7 + timer 3） | ⚠️ 全 stub，只测业务逻辑 |
| 🟢 Components | `PortfolioAnalysis`×1、`PortfolioManager`×3 | **16 个** | ✅ 含 selection + features + analysis 交互 |
| 🟢 **子组件** | DashboardHistory(10) + StrategyCheckResult(10) + GlobalIndicesStrip(4) + ChartComponents(16) | **40 个** | ✅ 2026-07-29：全部已覆盖 |
| 🟡 Router | 路由结构 | 4 个 | ✅ 轻量，够用 |
| 🟡 App | `App.vue` 挂载 | 3 个 | ⚠️ 全 stub，只测无报错 |
| 🟢 **UI 组件** | AppButton/AppCard/AppTabs/AppInput/AppModal + AppTable/AppSelect/Skeleton/Pagination/Tooltip/Badge | **70 个**（AppComponents.spec.js 45 + AppComponents2.spec.js 25） | ✅ 覆盖 11 个核心组件所有常见交互 |
| 🟢 **News 模块** | NewsView + TokenMonitor | **15 个**（NewsView 12 + TokenMonitor 3） | ✅ 2026-07-29 新增 |

### E2E 测试（Playwright）— **5 个 spec 文件，24 个测试用例**

| 测试文件 | 内容 | 类型 |
|---------|------|------|
| `01-smoke.spec.js` | 5 个页面走查，只检查能打开、无 console error | 🌬️ 烟雾 |
| `03-navigation.spec.js` | 全局导航栏点击跳转（6 条） | 🧭 导航 |
| `04-wizard-design.spec.js` | AI 设计流程（输入金额→生成，5 条） | 🧪 功能 |
| `05-theme-assets.spec.js` | PWA manifest / theme-color / 图标（5 条） | 🎨 资产 |
| `12-regression.spec.js` | news 页面、market 按钮回归（3 条） | 🔄 回归 |

**仍缺少的核心能力**：
- ❌ 无视觉 diff（不能发现 CSS 改变导致布局偏移）
- ❌ 无截图对比（无法自动检测样式回归）
- ⚠️ Charts 渲染已有 E2E spec (`06-charts.spec.js`) 和 ChartComponents 单测 (16 条)
- ❌ E2E 覆盖仍有空白：AI Advisor (`13-ai-advisor.spec.js`)，Sector analysis，Symbol analysis，Token monitor specs 已创建但尚未集成/运行

> **⚠️ 2026-07-29 审计发现**：npm test 结果实际为 **4 个测试失败** — 分布在 `useSectorAnalysis.spec.js`（10 条中 2 失败）和 `useMarketSearch.spec.js`（11 条中 2 失败）。这些是新创建的 composable 测试，mock 尚未完善。在标记"✅ 全绿"前需修复。

---

## 2. 关键风险点（重构中最容易出问题的地方）

| 风险 | 易触发场景 | 当前是否有防护 |
|------|-----------|:-------------:|
| CSS 变量未定义导致颜色消失 | 修 `--color-primary` 时打错名字 | ✅ 已修复（`theme.css:121-124` 已追加向后兼容别名 `--color-primary` / `--color-primary-dark` / `--color-primary-light` / `--color-border` / `--color-text-muted`） |
| 卡片结构改变导致布局错位 | 手工 card → AppCard 迁移 | ⚠️ AppCard 有 43 条单测覆盖 variant/slot，但未覆盖实际页面布局回归 |
| Tab 交互失效（切换不显示内容） | 手工 tab → AppTabs 替换 | ⚠️ AppTabs 有 6 条单测覆盖切换/active 类名，但未与业务页面集成验证 |
| 图表渲染空白 | ECharts 注册变化 | ❌ 无（Chart 组件无单测，ECharts stub 策略已就绪但未实施） |
| 响应式布局断裂 | 修改 padding/margin 令牌 | ❌ 无 |
| 涨跌色反转（红绿颠倒） | 修改 CSS 变量引用 | ✅ `changeClass` 单测覆盖 |
| 路由懒加载失效 | 修改 import 路径 | ❌ 无 |

> 相比 Phase 2.5 前，UI 组件和 composable 已有单测防护。CSS 变量别名已在 `theme.css:121-124` 追加修复 ✅，但 **Chart 渲染、响应式布局**仍是空白。

---

## 3. 测试防护体系设计方案

> ✅ Phase 2.5 已完成大部分方案的实现（Phase A 全部 + B1/B2）。本节保留原始方案作为历史参考，并在各处标注实施状态。

### 3.1 第一层：UI 组件单元测试（✅ 已实施）

为 5 个最核心的 UI 基础组件添加单测，覆盖渲染、props、事件。

**现状**：`AppComponents.spec.js` 已实现 **43 个测试用例**，覆盖 AppButton(11) / AppCard(12) / AppTabs(8) / AppInput(6) / AppModal(6)。实际实现超出原始方案数量（原始估算 25-31 条 → 实际 43 条）。

**优先级排序：**

| 组件 | 测试重点 | 估算条数 | 为什么重要 |
|------|---------|---------|-----------|
| `AppButton.vue` | variant 类名、loading 态、disabled、click 事件 | 5-6 条 | 全页面使用，重构中最易触及 |
| `AppCard.vue` | 4 种 variant、header/content/footer slot、bordered、clickable | 5-6 条 | 卡片迁移的核心目标 |
| `AppTabs.vue` | tab 切换、active 类名、keyboard nav、icon/badge | 6-8 条 | Tab 统一的关键组件 |
| `AppInput.vue` | v-model、type number/text、disabled、placeholder | 4-5 条 | 表单基础 |
| `AppModal.vue` | open/close、ESC 关闭、overlay 关闭、focus trap | 5-6 条 | 替换手工 modal 的前提 |

**示例 — AppButton 测试：**
```js
describe('AppButton', () => {
  it('renders primary variant with correct class', () => {
    const wrapper = mount(AppButton, { props: { variant: 'primary' } })
    expect(wrapper.classes()).toContain('btn--primary')
  })
  it('shows loading spinner when loading is true', () => {
    const wrapper = mount(AppButton, { props: { loading: true } })
    expect(wrapper.find('.btn__loader').exists()).toBe(true)
  })
  it('does not emit click when disabled', async () => {
    const wrapper = mount(AppButton, { props: { disabled: true } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toBeFalsy()
  })
})
```

### 3.1.5 特别注意：Chart 组件的测试策略

图表组件（`AllocationPieChart`, `PnLBarChart` 等）依赖 ECharts + vue-echarts，在 jsdom 环境中 mount 会触发 `ResizeObserver` 和 Canvas 相关 API。

**策略**：不需要在单元测试中验证图表是否真的绘制了 Canvas。使用 stub 策略：

```js
// 对 vue-echarts 做全局 stub，保证组件可挂载即可
vi.mock('vue-echarts', () => ({
  default: { template: '<div class="v-chart-stub" />' },
}))
```

这样可以在不引入 ECharts 运行时的情况下验证：
- 组件是否正确接收 props（items、title）
- 组件在数据为空时显示空状态
- 组件结构（header、chart 容器）是否正确渲染

### 3.2 第二层：关键 Composable 测试

| Composable | 测试重点 | 估算条数 | 实施状态 |
|-----------|---------|:-------:|:-------:|
| `useDashboardData` | 数据流正确性、loading 状态转换、computed 派生（pnlTotal/cashPct） | 6-8 条 | ✅ **已实施**（35 条，远超估算） |
| `useMarketSearch` | 搜索防抖、结果渲染 | 3-4 条 | ❌ 待实施 |

**状态说明**：`useDashboardData` 已在 Phase 2.5 中实施（commits `b04b448`/`f6d47d3`），实际实现 35 条用例覆盖了全部 computed 派生 + 异步方法 + 响应式行为。`useMarketSearch` 等其余 composable 仍无测试。

### 3.3 第三层：E2E 增强 — 关键路径走查（✅ 实施中）

**当前状态**：Phase 2.5 已将 E2E spec 从 2 个扩充到 **5 个文件、24 个测试用例**（smoke×5 + navigation×6 + wizard×5 + theme/assets×5 + regression×3），覆盖了导航跳转、AI 设计流程、PWA 资产等关键路径。

**仍缺失**（建议后续 Phase 补齐）：
- Charts 渲染验证（Dashboard 饼图/柱状图 → 需截图 diff）
- 技术分析页面选择标的→图表加载流程
- News 页面筛选交互

```
当前（24 条）：                        仍缺失（~+6-8 条）：
✅ Dashboard 页面无白屏无报错           ❌ Dashboard 饼图/柱状图渲染
✅ Market 页面按钮可点击                ❌ 技术分析选择标的→图表加载
✅ Portfolio tab 切换                   ❌ News 页面筛选交互
✅ News 页面加载
✅ Token Monitor 页面打开
✅ AI 设计流程（输入金额→生成）
✅ 全局导航栏点击跳转正确
```

### 3.4 第四层（可选）：视觉回归测试 — Screenshot Diffing

**原理**：先在重构前跑一遍截图基线，重构后对比差异。

```js
// Playwright 截图对比示例
test('Dashboard matches visual baseline', async ({ page }) => {
  await page.goto('/')
  await page.waitForTimeout(2000) // 等图表加载
  await expect(page).toHaveScreenshot('dashboard.png', {
    maxDiffPixels: 100, // 允许微小差异
  })
})
```

**优点**：能发现任何视觉偏移 — 哪怕只是 padding 变了 2px。
**代价**：
- 首次需要生成基线截图（建议在重构前做）
- CI 中跑不稳定（字体渲染差异、动画时间差异），需要 `fullPage: true` + 禁用动画
- 对响应式布局需要多组截图（1440px + 768px + 375px）

**实施建议**：作为可选层，在 Phase 4（精细化打磨）阶段引入。**前三个层已经能覆盖 90% 的回退风险。**

---

## 4. 实施路线图（2026-07-26 更新）

```
Phase A — 补齐基础防护（✅ 已完成，Phase 2.5）
├── A1: AppButton 单测 ── ✅ 11 条，30 分钟
├── A2: AppCard 单测   ── ✅ 12 条，30 分钟
├── A3: AppTabs 单测   ── ✅ 8 条，40 分钟
├── A4: AppInput 单测  ── ✅ 6 条，20 分钟
├── A5: AppModal 单测  ── ✅ 6 条，20 分钟
├── A6: 统一在 AppComponents.spec.js 文件中，共 43 条
└── 验证：npm test 全绿 ✅

Phase B — 业务层防护（✅ 已完成，Phase 2.5）
├── B1: useDashboardData 单测 ── ✅ 35 条 >> 估算 6-8 条
├── B2: E2E spec 扩充到 24 条 ── ✅ 5 files: smoke(5)+navigation(6)+wizard(5)+theme(5)+regression(3)
├── B3: PortfolioAnalysis E2E ── 通过 navigation + regression 覆盖
└── 验证：npm test + npm run test:e2e:smoke 全绿 ✅

Phase C — 全面覆盖（📌 部分完成，4 个测试需修复）
├── C1: 剩余 UI 组件单测（AppTable、AppSelect、Skeleton 等）—— AppComponents2.spec.js 已覆盖（25 条），C1 已自然完成 ✅
├── C2: Chart 组件基本渲染测试（AllocationPieChart + PnLBarChart，带 vue-echarts stub）—— ✅ 已完成（ChartComponents.spec.js，16 条）
├── C3: E2E 覆盖 Charts 渲染 + 技术分析——06-charts.spec.js 已创建 ✅，另有 13-ai-advisor/14-sector-analysis 等 E2E 待集成
├── C4: E2E 截图对比基线建立（📌 待实施，建议 UI Phase 2 完成后）
├── ⚠️ 4 个测试失败待修复：useSectorAnalysis.spec.js (2) + useMarketSearch.spec.js (2)
└── 验证：npm test 应在修复后达到 256/256 通过
```

> 🎯 **对 Phase 3.1 的影响**：Phase A+B 已提供充分的测试防护（UI 组件 43 条 + composable 35 条 + E2E 24 条），**Phase 3.1 的测试依赖已满足，可以安全实施**。若进一步降低风险，建议在 Phase 3.1 开始前先做 C4（截图基线），可在 30 分钟内完成。

---

## 5. 跑一次测试的时间预算（估算）

```bash
npm test                 # Vitest 单元测试 → < 30 秒（含组件 mount）
npm run test:e2e:smoke   # Playwright 烟雾 → < 60 秒（+ 后端+前端服务启动）
npm run test:e2e         # 完整 E2E        → < 5 分钟
```

**实际时间会因硬件和网络而异**（E2E 需启动 uvicorn + vite dev server）。
增量开发时建议只跑 `npm test`（< 30s），在合并前跑一次完整 E2E。

每次 commit 前跑 `npm test` + `npm run test:e2e:smoke` 就能获得 90% 的安全感。

> **与性能优化文档的关系**：性能优化 Step 1 删除了 `main.js` 中 `import './plugins/echarts'` 行，
> 但现有测试已通过 `vi.mock('echarts')` 或组件 stub 隔离了 ECharts 依赖，不会受到影响。
> 性能优化 Step 4（task.js localStorage 防抖）完成后，需确认 taskStore 单测依然通过。

---

## 6. 关键验收标准（2026-07-26 更新）

当达到以下标准时，可以认为测试防护体系完善：

- [x] 所有 11 个核心 UI 组件有单测，覆盖 variant/事件/disabled/loading 状态 ✅
- [x] `useDashboardData` + `useLLMStream` + `useMarketWS` 等 6 个 composable 有单测 ✅
- [ ] **每次 commit 前 `npm test` 全绿** — ❌ **当前 4 个失败需修复**（useSectorAnalysis 2 + useMarketSearch 2）
- [ ] 每次重构一个页面后，对应 E2E smoke 测试通过（当前为人工验证）
- [x] `npm test && npm run test:e2e:smoke` 在正常开发机上不超过 3 分钟 ✅（实测 ~63s）

**补充说明**：
- 第 1-2 项已在 Phase 10.2-10.3 全部满足。
- 第 3 项**当前不达标**：`useSectorAnalysis.spec.js` 2/10 失败 + `useMarketSearch.spec.js` 2/11 失败。需要修复 mock 后恢复全绿状态。
- 第 4 项需在后续实施过程中逐页面验证（目前是人工→建议尽快自动化）。
- 第 5 项需实测，预估 `npm test`(~5s) + `npm run test:e2e:smoke`(~60s) 远超 3 分钟余量。
