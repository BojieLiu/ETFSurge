# Frontend Testing & Safety Net Plan

> 目标：为 UI 重构和性能优化提供充分的测试防护，确保每次修改可放心提交。
> 核心理念：分层防护，快速反馈，精准定位问题。

---

## 1. 现有测试现状

### 单元测试（Vitest）— 12 个 spec 文件

| 层级 | 测试内容 | 数量 | 质量 |
|------|---------|------|------|
| 🟢 Utils | `changeClass`、`formatDate`、`newsLevel` | 3 个 | ✅ 良好，覆盖主要逻辑 |
| 🟡 Stores | `taskStore` — 任务状态机 | 1 个 | ✅ 覆盖了 hasRunningTask/activeTaskId |
| 🟡 Composable | `useNewsWS` — WebSocket 连接 | 1 个 | ⚠️ 只测了一个 composable |
| 🟡 Views | `DashboardAiTools` — 设计报告 | 1 个 | ⚠️ 全 stub，只测业务逻辑 |
| 🟡 Components | `PortfolioAnalysis`、`PortfolioManager`×2 | 3 个 | ⚠️ 子组件全 stub，只测交互 |
| 🟡 Router | 路由结构 | 1 个 | ✅ 轻量，够用 |
| 🟡 App | `App.vue` 挂载 | 1 个 | ⚠️ 全 stub，只测无报错 |
| 🔴 **UI 组件** | `AppButton`、`AppCard`、`AppTabs`、`AppTable`、`AppModal` **等 13 个基础组件** | **0 个** | ❌ 完全缺失 |
| 🟡 **Composable** | `useDashboardData`、`useLLMStream`、`useSectorAnalysis`、`useMarketSearch`、`useMarketWS` **等 5 个** | **1 个** | ⚠️ 仅 `useNewsWS` 有测试，其余 4 个缺失 |
| 🔴 **Dashboard 子组件** | SummaryCards、AllocationPieChart、PnLDetailTable **等 7 个** | **0 个** | ❌ 完全缺失 |
| 🔴 **Market 子组件** | MarketReport、WatchlistPanel、SectorAnalysis **等 6 个** | **0 个** | ❌ 完全缺失 |

### E2E 测试（Playwright）— 2 个 spec 文件

| 测试 | 内容 | 类型 |
|------|------|------|
| `01-smoke.spec.js` | 5 个页面走查，只检查能打开、无 console error | 🌬️ 烟雾 |
| `12-regression.spec.js` | 2 个回归测试（news 页面、market 按钮） | 🔄 回归 |

**缺少的核心能力**：
- ❌ 无视觉 diff（不能发现 CSS 改变导致布局偏移）
- ❌ 无截图对比（无法自动检测样式回归）
- ❌ coverage 太浅（只测页面存在，不测功能正确性）

---

## 2. 关键风险点（重构中最容易出问题的地方）

| 风险 | 易触发场景 | 当前是否有防护 |
|------|-----------|--------------|
| CSS 变量未定义导致颜色消失 | 修 `--color-primary` 时打错名字 | ❌ 无 |
| 卡片结构改变导致布局错位 | 手工 card → AppCard 迁移 | ❌ 无 |
| Tab 交互失效（切换不显示内容） | 手工 tab → AppTabs 替换 | ⚠️ PM Analysis 有测，其余无 |
| 图表渲染空白 | ECharts 注册变化 | ❌ 无 |
| 响应式布局断裂 | 修改 padding/margin 令牌 | ❌ 无 |
| 涨跌色反转（红绿颠倒） | 修改 CSS 变量引用 | ✅ `changeClass` 单测覆盖 |
| 路由懒加载失效 | 修改 import 路径 | ❌ 无 |

---

## 3. 测试防护体系设计方案

### 3.1 第一层：UI 组件单元测试（收益最高 + 成本最低）

为 5 个最核心的 UI 基础组件添加单测，覆盖渲染、props、事件。

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

| Composable | 测试重点 | 估算条数 |
|-----------|---------|---------|
| `useDashboardData` | 数据流正确性、loading 状态转换、computed 派生（pnlTotal/cashPct） | 6-8 条 |
| `useMarketSearch` | 搜索防抖、结果渲染 | 3-4 条 |

**为什么 `useDashboardData` 尤其重要**：它是 Dashboard 页面的数据主干，涉及多个 API 调用 + computed 派生链。重构如果把 `pinia` store 换成别的状态方案，这个 composable 就是承上启下的关键层。现在它完全没有测试。

### 3.3 第三层：E2E 增强 — 关键路径走查

在现有 5 个烟雾测试基础上，增加覆盖**核心用户流程**的 E2E：

```
当前（5 条）：                       优化目标（10-12 条）：
✅ Dashboard 页面无白屏无报错         ✅ Dashboard 页面无白屏无报错
✅ Market 页面按钮可点击              ✅ Market 页面按钮可点击
✅ Portfolio 页面打开                 ✅ Portfolio tab 切换
✅ News 页面加载                      ✅ News 页面筛选交互
✅ Token Monitor 页面打开             ✅ Token Monitor 页面打开
                                     ✅ AI 设计流程（输入金额→生成）
                                     ✅ 技术分析页面选择标的→图表加载
                                     ✅ 全局导航栏点击跳转正确
```

**建议不要太多** — 保持 10-15 个 E2E，聚焦关键用户旅程即可。

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

## 4. 实施路线图

```
Phase A — 补齐基础防护（与 UI 重构 Phase 1 并行）
├── A1: AppButton 单测 ── 5-6 条，30 分钟
├── A2: AppCard 单测   ── 5-6 条，30 分钟
├── A3: AppTabs 单测   ── 6-8 条，40 分钟
├── A4: AppInput 单测  ── 4-5 条，20 分钟
├── A5: AppModal 单测  ── 4-5 条，20 分钟
└── 验证：npm test 全绿

Phase B — 业务层防护（与 UI 重构 Phase 2 并行）
├── B1: useDashboardData 单测 ── 6-8 条，45 分钟
├── B2: Dashboard 烟雾 E2E 增强 ── +2 条关键路径，30 分钟
├── B3: PortfolioAnalysis E2E ── tab 切换 + 交互，30 分钟
└── 验证：npm test + npm run test:e2e:smoke 全绿

Phase C — 全面覆盖（重构 Phase 3 前后）
├── C1: 剩余 UI 组件单测（AppTable、AppSelect 等）
├── C2: Chart 组件基本渲染测试（AllocationPieChart 等，带 vue-echarts stub）
├── C3: E2E 覆盖到 10-15 条
├── C4: E2E 截图对比基线建立（可选，建议在 UI Phase 4 开始前做）
└── 验证：全量测试 suite 在 CI 中通过
```

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

## 6. 关键验收标准

当达到以下标准时，可以认为测试防护体系完善：

- [ ] 所有 5 个核心 UI 组件有单测，覆盖 variant/事件/disabled/loading 状态
- [ ] `useDashboardData` 有单测，覆盖数据加载和 computed 派生
- [ ] 每次 commit 前 `npm test` 全绿
- [ ] 每次重构一个页面后，对应 E2E smoke 测试通过
- [ ] 执行 `npm test && npm run test:e2e:smoke` 在正常开发机上不超过 3 分钟
