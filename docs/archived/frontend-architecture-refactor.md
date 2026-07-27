# 前端架构重构方案

> 生成日期: 2026-07-21（v3：根据第二轮 Code Review 修正）
> 目标：拆分超大组件，标准化通信模式，提升可维护性与可测试性

---

## 现状（实测行数）

| 组件 | 实际行数 | 功能数 | 问题 |
|------|---------|--------|------|
| `MarketAnalysis.vue` | 1722 | 6 个 Section | Section 编号混乱（1、1.5、1.7、2、3、4），彼此共享作用域 |
| `DashboardAiTools.vue` | 2059 | 5 种操作模式 | 向导/加载/结果/历史/策略检查揉在一起 |
| `Dashboard.vue` | 1208 | 5+ 个独立区域 | 标签页切换/资金输入/概览卡片/持仓表/图表全部耦合 |
| `AnalysisView.vue` | 749 | 3+ 功能区 | 未纳入范围，但与 MarketAnalysis 共用数据获取逻辑 |

---

## 重构原则

1. **每个子组件 ≤400 行** — 超过就继续拆
2. **纯容器组件不做数据获取** — 只负责布局和 props 传递；数据获取抽到 composable
3. **数据获取抽到 composables** — 可复用、可 mock、可测试
4. **大型纯函数（报告生成、Markdown 渲染）抽到 `src/utils/`** — 不放在组件或 composable 中
5. **重构分阶段** — 先拆 MarketAnalysis.vue，再拆 DashboardAiTools.vue，最后依次拆 Dashboard.vue 和 AnalysisView.vue
6. **不新增外部依赖** — 只用 Vue 3 原生能力（defineProps, defineEmits, composables）
7. **CSS 统一使用 `scoped`** — 子组件样式自包含；全局颜色/间距变量从 `theme.css` 继承；原有全局样式在容器层保留一套
8. **ECharts 全局注册集中在 `src/plugins/echarts.js`** — 避免拆出图表组件后注册丢失

---

## 状态所有权策略

拆分前明确每种数据的归属，避免子组件各自引 store 导致耦合：

| 数据类型 | 归属 | 理由 |
|---------|------|------|
| 跨页面共享数据（watchlist、ETF 持仓、任务状态） | **Pinia store** | 多组件/多路由复用，需持久化或 WS 同步 |
| 当前页面独有的 UI 状态（activeTab、showModal、loading） | **容器组件 `ref`** | 只在该页面有效，不需要跨组件共享 |
| 可复用的数据获取/变换逻辑（搜索补全、板块数据、图表数据） | **Composable** | 可在不同页面间复用，易于 mock 测试 |
| 纯展示/格式化函数（Markdown 渲染、报告文本生成） | **`src/utils/` 纯函数** | 无状态、无 Vue API 依赖，可直接单元测试 |

**子组件原则上不直接引用 Pinia store** — 通过容器 props 下行 + emit 上行通信。
仅当子组件本身是 store 消费者（如 `TaskIndicator.vue` 读取 task 状态）时，允许直接引用。

---

## 阶段一：MarketAnalysis.vue → 容器 + 6 个子组件

### 新目录结构

```
frontend/src/
├── views/
│   └── MarketAnalysis.vue          ← 容器（~80 行）
├── components/
│   └── market/
│       ├── MarketReport.vue        ← 市场研判（原 Section 1）
│       ├── WatchlistPanel.vue      ← 自选列表（原 Section 1.5）
│       ├── AiAdvisor.vue           ← AI 投资顾问（原 Section 1.7）
│       ├── SectorAnalysis.vue      ← 板块概念分析（原 Section 2）
│       ├── SymbolAnalysis.vue      ← 个股/ETF 分析（原 Section 3）
│       └── IndexAnalysis.vue       ← 指数分析（原 Section 4）
├── composables/
│   ├── useMarketSearch.js          ← 搜索补全逻辑（从 MarketAnalysis.vue 抽出）
│   ├── useSectorAnalysis.js        ← 板块数据获取（与现有 useMarketWS/useLLMStream 风格对齐）
│   └── useChartView.js             ← K 线/指标图表数据（供 MarketAnalysis & AnalysisView 复用）
├── utils/
│   ├── markdown.js                 ← renderMarkdown() 纯函数（从 MarketAnalysis 抽出）
│   └── designReport.js             ← generateDesignReport() 纯函数（从 DashboardAiTools 抽出）
├── plugins/                        ← 新增
│   └── echarts.js                  ← ECharts 一次性全局注册（use() 调用）
└── api/
    └── index.js                    ← 现有，不变
```

### 子组件通信协议（含空/初始状态契约）

```
容器 (MarketAnalysis.vue)
  │
  ├─ marketTab: string              ← 所有子组件共享
  ├─ selectedSymbol: string|null    ← 来自 WatchlistPanel 的 select-symbol
  │
  ├── MarketReport
  │     props: marketTab
  │     emits: (none, self-contained)
  │     states: [loading, error, empty(初始提示), data]
  │
  ├── WatchlistPanel  
  │     props: marketTab
  │     emits: select-symbol(symbol)
  │     states: [loading, empty(引导添加), data]
  │     内部包含 AddWatchlistModal（搜索/键盘导航/补全，使用 useMarketSearch）
  │
  ├── AiAdvisor
  │     props: marketTab
  │     emits: (none, self-contained)
  │     states: [idle(输入框+按钮), loading, error, data]
  │
  ├── SectorAnalysis
  │     props: marketTab
  │     emits: select-sector(sectorCode)
  │     states: [loading, empty, data]
  │
  ├── SymbolAnalysis
  │     props: marketTab, selectedSymbol   ← 接收 WatchlistPanel 的选择
  │           初始值 null → 显示"请选择一个标的"提示
  │           非 null → 加载该标的详情（K 线/指标/信号）
  │           触发方式：内部 watch(() => props.selectedSymbol) 变化时
  │           调用 useChartView() 的 fetchAll()
  │     emits: (none)
  │     states: [no-selection(null), loading, indicator-loading, error, data]
  │
  └── IndexAnalysis
        props: marketTab
        emits: (none)
        states: [loading, empty, data]
```

### 提取的 Composables

#### `useMarketSearch.js`
```js
// 封装搜索补全逻辑，供 SymbolAnalysis 和 WatchlistPanel 复用
// composable 内自行 import onUnmounted，调用方无需额外 import
export function useMarketSearch() {
  // import { ref, onUnmounted } from 'vue'
  const searchQuery = ref('')
  const searchResults = ref([])
  const showDropdown = ref(false)
  let searchTimer = null              // ← let，会被重新赋值
  let searchFocusIndex = ref(-1)

  async function doSearch() { /* 调用 marketApi.search */ }
  function onSearchInput() { /* 300ms debounce：clearTimeout(searchTimer); searchTimer = setTimeout(doSearch, 300) */ }
  function onKeydown(e) { /* 键盘上下 + Enter 导航 */ }
  function selectSuggestion(s) { /* 选中补全项 */ }

  // 确保定时器在组件卸载时清理
  onUnmounted(() => { clearTimeout(searchTimer) })
  
  return { searchQuery, searchResults, showDropdown, searchFocusIndex, doSearch, onSearchInput, onKeydown, selectSuggestion }
}
```

#### `useSectorAnalysis.js`
```js
// 从 MarketAnalysis.vue 抽出，依赖 marketTab 变化时自动重载
export function useSectorAnalysis(marketTab) {
  const sectors = ref([])
  const loading = ref(false)
  const currentSector = ref(null)
  const sectorList = ref([])
  const sectorLoadingList = ref(false)
  
  watch(marketTab, () => { reset(); fetchSectors() })
  async function fetchSectors() { /* ... */ }
  async function fetchSectorList() { /* 详细板块列表 */ }
  
  return { sectors, loading, currentSector, sectorList, sectorLoadingList, fetchSectors, fetchSectorList }
}
```

#### `useChartView.js`
```js
// 供 MarketAnalysis.SymbolAnalysis & AnalysisView 复用
export function useChartView(symbol, assetType) {
  const klineData = ref([])
  const indicators = ref(null)
  const signal = ref(null)
  const loading = ref(false)
  const chartMode = ref('kline')   // 'kline' | 'intraday'
  
  watch([symbol, assetType], () => { if (symbol) fetchAll() })
  async function fetchAll() { /* 并行请求 K 线 + 指标 + 信号 */ }
  
  return { klineData, indicators, signal, loading, chartMode, fetchAll }
}
```

---

## 阶段二：DashboardAiTools.vue → 6 个子组件

### 新目录结构

```
frontend/src/components/design/
├── DesignWizard.vue           ← 设计向导（输入资金 + 风格约束）
├── DesignLoading.vue          ← 加载状态（进度条 + 步骤）
├── DesignResult.vue           ← 方案卡片 + 完整报告 Tab
├── DesignHistory.vue          ← 历史记录列表（含设计&策略检查混合）
├── StrategyCheckModal.vue     ← 策略检查弹窗（场内/场外选择）
└── StrategyCheckResult.vue    ← 策略检查结果面板（原与 DesignResult 耦合，强制拆出）
```

### 容器职责

容器持有 `activeCoreFeature`、`designStep`、`currentTaskId` 等 UI 状态，条件渲染各子组件。
子组件通过 props/emit 与容器通信，不直接引用 `taskStore`。

**容器中保留的内联模板不超过 50 行**（超出的部分强制拆为独立子组件）。

```
容器 (DashboardAiTools.vue)
  │
  ├─ activeCoreFeature: string|null  ('design' | 'strategy' | 'history')
  ├─ designStep: string              ('wizard' | 'loading' | 'result')
  ├─ currentTaskId: string|null      ← 创建任务后由容器持有，透传给 Loading/Result
  ├─ strategyResult: object|null     ← 策略检查结果
  │
  ├── DesignWizard           props: capital, constraints
  │                           emits: start-design(capital, constraints)
  │
  ├── DesignLoading          props: progress, stepLabel, taskId
  │                           emits: cancel
  │                           /* taskId 数据流：
  │                              Wizard emit → 容器调用 portfolioApi.designAsync()
  │                              → 容器赋值 currentTaskId → 透传给 DesignLoading */
  │
  ├── DesignResult           props: plans[], marketContext, designText
  │                           emits: apply(plan), regenerate, close
  │
  ├── DesignHistory          props: items[], loading
  │                           emits: select(id), load-more, close
  │
  ├── StrategyCheckModal     props: visible
  │                           emits: select-type("on_exchange"|"off_exchange"), close
  │
  └── StrategyCheckResult    props: result, loading, error
                              emits: apply(suggestions), close
```

### 大型纯函数提取到 `utils/`

- **`src/utils/designReport.js`** — 从 `generateDesignReport()` (DashboardAiTools.vue 第 598 行) 提取，纯函数，带单元测试
- **`src/utils/markdown.js`** — 从 `renderMarkdown()` (MarketAnalysis.vue 第 719 行) 提取，纯函数，带单元测试

---

## 阶段三：Dashboard.vue → 容器 + 7 个子组件

### 子组件目录

```
frontend/src/components/dashboard/
├── CapitalInputBar.vue       ← 资金输入栏（场内/场外 inputs，组合类型联动）
├── SummaryCards.vue          ← 概览卡片组（总仓位、场内/外当日盈亏、累计盈亏）
├── AllocationTable.vue       ← 持仓分配表（含 drift 提示，带空状态）
├── AllocationPieChart.vue    ← 分配饼图（可复用，参数化 type="on"|"off"）
├── PnLBarChart.vue           ← 当日盈亏分布柱状图
├── PnLDetailTable.vue        ← 当日盈亏明细表（标的级）
└── ErrorOverlay.vue          ← 错误覆盖层（renderError 状态展示 + 重试按钮）
```

> 注：`GlobalIndicesStrip.vue` 已是独立组件，保持不动。

### 容器通信

```
容器 (Dashboard.vue) — 注意：容器本身不做数据获取（违反原则 2），
数据获取由 useDashboardData composable 处理。
```

#### 提取的 Composable：`useDashboardData.js`

```js
// 将 Dashboard.vue 的数据获取 + computed 集中于此
export function useDashboardData(capitalOn, capitalOff, activeTab) {
  // 原始数据
  const allocationOn = ref({ allocations: [], total_amount: 0 })
  const allocationOff = ref({ allocations: [], total_amount: 0 })
  const pnlOnData = ref({ items: [] })
  const pnlOffData = ref({ items: [] })
  const pnlHistory = ref(null)
  const loading = ref(false)

  // 派生 computed（共约 10 个，全部从 Dashboard.vue 搬过来）
  const totalAll = computed(() => { ... })
  const pnlOn = computed(() => pnlOnData.value.total_pnl || 0)
  const pnlOff = computed(() => pnlOffData.value.total_pnl || 0)
  const pnlTotal = computed(() => ...)
  const pnlItems = computed(() => ...)
  const cashPctOn = computed(() => ...)
  // ... 等

  // 数据获取
  async function fetchAllocations() { ... }
  async function fetchPnl() { ... }
  async function refreshAll() { await Promise.all([fetchAllocations(), fetchPnl()]) }

  return { allocationOn, allocationOff, pnlItems, totalAll, pnlOn, pnlOff, loading,
           fetchAllocations, fetchPnl, refreshAll, ... }
}
```

容器只做：

```
容器 (Dashboard.vue)
  │
  ├─ activeTab, capitalOn, capitalOff  ← 容器持有的 UI 状态
  ├─ allocationOn, pnlItems, ...       ← useDashboardData 返回的响应式数据
  │
  ├── CapitalInputBar     props: activeTab, capitalOn, capitalOff
  │                        emits: update:capitalOn(v), update:capitalOff(v), refresh
  │
  ├── SummaryCards        props: activeTab, totalAll, pnlOn, pnlOff, pnlTotal, loading
  │                        emits: (none)
  │
  ├── AllocationTable     props: items, loading
  │       /* items 数据形状：
  │          [{ symbol: string, name: string, target_weight: number,
  │             target_amount: number, market_value: number, daily_pnl: number,
  │             daily_return_pct: number }] */
  │                        emits: (none)
  │
  ├── AllocationPieChart  props: items, title
  │       /* items 数据形状同 AllocationTable */
  │                        emits: (none)
  │
  ├── PnLBarChart         props: items, loading
  │       /* items 数据形状：{ symbol, daily_pnl, target_amount } */
  │                        emits: (none)
  │
  ├── PnLDetailTable      props: items, loading
  │                        emits: (none)
  │
  └── ErrorOverlay        props: hasError, errorMessage
                          emits: retry
```

> ECharts 注册说明：`AllocationPieChart` 和 `PnLBarChart` 不再各自调用 `use()`，
> 改为在 `src/plugins/echarts.js` 中一次性注册所有需要的渲染器和组件，
> 在 `main.js` 中 `import './plugins/echarts'` 一次即可。

---

## 阶段四：AnalysisView.vue → 容器 + 3 个子组件

> **注意**：AnalysisView **不是**路由组件——它被 `PortfolioAnalysis.vue` import 使用。
> 容器**保留在** `src/components/AnalysisView.vue`，不需要创建 `src/views/` 版本，
> 也不需要更新 `router/index.js`。

```
frontend/src/components/
├── AnalysisView.vue          ← 容器（~60 行），复用 useChartView
└── analysis/
    ├── ControlPanel.vue      ← 分析标的选择 + 周期/指标切换
    ├── ChartPanel.vue        ← K 线/分时图（ECharts 封装，复用 useChartView）
    └── SignalPanel.vue       ← 综合买卖信号
```

---

## 路由迁移

容器组件从 `src/components/` 移到 `src/views/` 后，需要同步更新 3 个路由条目：

```js
// frontend/src/router/index.js — 修改前
component: () => import('../components/Dashboard.vue'),
component: () => import('../components/MarketAnalysis.vue'),
component: () => import('../components/TokenMonitor.vue'),

// — 修改后
component: () => import('../views/Dashboard.vue'),
component: () => import('../views/MarketAnalysis.vue'),
component: () => import('../views/TokenMonitor.vue'),
```

> 不受影响的路由（保持 `components/` 路径不变）：
> - `PortfolioAnalysis.vue` — 不是容器，内部已拆为多子组件
> - `NewsView.vue` — 体量尚可，不在本次重构范围
> - `AnalysisView.vue` — 不是路由组件，`src/components/` 路径不变

在阶段一完成后立即执行此更新，避免后续阶段中路由与文件路径不一致。

---

## 拆分步骤

```
第 1 步: 创建 composables + utils + plugins 目录
   - 从 MarketAnalysis.vue 抽出 useMarketSearch.js
   - 从 MarketAnalysis.vue 抽出 useSectorAnalysis.js
   - 从 MarketAnalysis.vue/AnalysisView.vue 抽出 useChartView.js
   - 从 MarketAnalysis.vue 抽出 src/utils/markdown.js（renderMarkdown）
   - 从 DashboardAiTools.vue 抽出 src/utils/designReport.js（generateDesignReport）
   - 创建 src/plugins/echarts.js（ECharts 全局注册）
   - 每新建一个，确认 `npm run build` 通过

第 2 步: 创建 market/ 组件目录
   - MarketReport.vue（从 MarketAnalysis Section 1 复制 + 适配）
   - WatchlistPanel.vue（从 Section 1.5 复制 + 适配）
   - 每新建一个，确认 `npm run build` 通过
   - 继续 AiAdvisor.vue、SectorAnalysis.vue、SymbolAnalysis.vue、IndexAnalysis.vue

第 3 步: 替换 MarketAnalysis.vue 为容器
   - 创建 src/views/MarketAnalysis.vue（容器）
   - 删除原 src/components/MarketAnalysis.vue
   - 更新 router/index.js 中 MarketAnalysis 的路径
   - 手动验证「行情分析」页所有 6 个功能正常

第 4 步: 创建 design/ 组件目录
   - DesignWizard.vue
   - DesignLoading.vue
   - DesignResult.vue
   - DesignHistory.vue
   - StrategyCheckModal.vue
   - StrategyCheckResult.vue
   - 每新建一个，确认 `npm run build` 通过

第 5 步: 替换 DashboardAiTools.vue 为容器
   - 创建 src/views/DashboardAiTools.vue（容器）
   - 删除原 src/components/DashboardAiTools.vue
   - 验证设计向导、加载、结果、历史、策略检查全流程

第 6 步: 提取 useDashboardData composable
   - 从 Dashboard.vue 抽出所有数据获取（fetchAllocations, fetchPnl, fetchPnlHistory）
   - 抽出所有 computed（pnlItems, totalAll, cashPctOn/Off 等）
   - 验证 Dashboard 功能正常

第 7 步: 创建 dashboard/ 组件目录
   - CapitalInputBar.vue
   - SummaryCards.vue
   - AllocationTable.vue
   - AllocationPieChart.vue
   - PnLBarChart.vue
   - PnLDetailTable.vue
   - ErrorOverlay.vue

第 8 步: 替换 Dashboard.vue 为容器
   - 创建 src/views/Dashboard.vue（容器）
   - 删除原 src/components/Dashboard.vue
   - 更新 router/index.js 中 Dashboard 路径
   - 验证 Dashboard 页所有功能

第 9 步: 创建 analysis/ 组件目录 + 缩小 AnalysisView.vue
   - ControlPanel.vue、ChartPanel.vue、SignalPanel.vue
   - 复用第 1 步的 useChartView
   - AnalysisView.vue 容器保持在 src/components/AnalysisView.vue（不是路由组件）
   - 验证「组合与分析」页中技术分析 Tab

第 10 步: 清理
   - 更新 TokenMonitor.vue 的路由路径（如已迁移）
   - 删除旧的 `.spec.js` 文件，创建新的子组件测试
   - 验证 CSS：全局涨跌色（theme.css 变量）不受 scoped 影响
   - 全局搜索残留的旧 import 路径
```

---

## 测试策略

| 组件类型 | 测试方式 | 覆盖率目标 |
|---------|---------|-----------|
| 容器组件 | 集成测试（所有子组件 stub） | 路由跳转、Tab 切换 |
| 子组件 | 单元测试（mount + props） | 所有状态（loading/empty/error/data） |
| Composables | 纯函数测试（mock API） | 所有分支 |
| `src/utils/` 纯函数 | 纯函数测试（无 mock） | 100% 分支 |

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 拆分过程中破坏现有功能 | 每拆一个组件就 `npm run build` + 手动验证对应功能 |
| 子组件间状态同步丢失 | 容器组件统一管理共享状态；参考通信协议中的初始状态 |
| CSS scoped 导致全局样式丢失 | 遵守规则 7：子组件用 scoped，关键变量从 theme.css 继承 |
| `renderMarkdown()` 从组件提取后行为不一致 | 提取后附带原有 spec 覆盖所有用例 |
| 路由路径与文件路径不同步 | 阶段一第 3 步立即更新 router/index.js |
| ECharts 图表组件拆出后 `use()` 注册丢失 | 规则 8 + `src/plugins/echarts.js` 一次性注册 |
| 重构时间长 | 见下时间估算，最坏情况接受分次完成 |

---

## 时间估算（修正后）

| 阶段 | 子组件数 | 附加产物 | 估算工时 | 依赖 |
|------|---------|---------|---------|------|
| 阶段一（MarketAnalysis） | 6 | 3 composables + 2 utils + 1 plugin | 6-8h | — |
| 阶段二（DashboardAiTools） | 6 | — | 4-6h | 阶段一的 utils / designReport.js |
| 阶段三（Dashboard） | 7 | 1 composable（useDashboardData） | 4-6h | 阶段一的 plugins/echarts.js |
| 阶段四（AnalysisView） | 3 | — | 2-3h | 阶段一的 useChartView |
| 测试 + 清理 | — | — | 2-4h | 所有阶段完成后 |
| **总计** | **22** | **7 个附加文件** | **18-27h** | 可分批次交付，每次一个阶段 |
