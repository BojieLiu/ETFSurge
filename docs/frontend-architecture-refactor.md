# 前端架构重构方案

> 生成日期: 2026-07-20
> 目标：拆分超大组件，标准化通信模式，提升可维护性与可测试性

---

## 现状

| 组件 | 行数 | 功能数 | 问题 |
|------|------|--------|------|
| `MarketAnalysis.vue` | 1812 | 6 | 6 个无关功能共享作用域，修改风险高 |
| `DashboardAiTools.vue` | 2141 | 5 | 向导/加载/结果/历史/策略检查揉在一起 |
| `Dashboard.vue` | 1231 | 3 | 组合摘要/盈亏/持仓列表耦合 |

---

## 重构原则

1. **每个子组件 ≤400 行** — 超过就继续拆
2. **纯容器组件不做数据获取** — 只负责布局和 props 传递
3. **数据获取抽到 composables** — 可复用、可 mock、可测试
4. **重构分阶段** — 先拆 MarketAnalysis.vue，再拆 DashboardAiTools.vue，最后拆 Dashboard.vue
5. **不新增外部依赖** — 只用 Vue 3 原生能力（defineProps, defineEmits, composables）

---

## 阶段一：MarketAnalysis.vue → 容器 + 6 个子组件

### 新目录结构

```
frontend/src/
├── views/
│   └── MarketAnalysis.vue        ← 容器（~80 行）
├── components/
│   └── market/
│       ├── MarketReport.vue      ← 市场研判（原 Section 1）
│       ├── WatchlistPanel.vue    ← 自选列表（原 Section 2）
│       ├── AiAdvisor.vue         ← AI 投资顾问（原 Section 3）
│       ├── SectorAnalysis.vue    ← 板块概念分析（原 Section 4）
│       ├── SymbolAnalysis.vue    ← 个股/ETF 分析（原 Section 5）
│       └── IndexAnalysis.vue     ← 指数分析（原 Section 6）
├── composables/
│   ├── useMarketSearch.js        ← 搜索补全逻辑（从 MarketAnalysis.vue 抽出）
│   ├── useSectorData.js          ← 板块数据获取
│   ├── useChartData.js           ← K 线/指标图表数据
│   └── usePagination.js          ← 通用分页逻辑
└── api/
    └── index.js                  ← 现有，不变
```

### MarketAnalysis.vue（容器）模板

```html
<template>
  <div class="market-analysis">
    <!-- 全局 Tab（A股/港股/美股/全球） -->
    <div class="market-tabs" role="tablist">
      <button v-for="tab in marketTabs" ...>{{ tab.label }}</button>
    </div>

    <MarketReport :market-tab="marketTab" />
    <WatchlistPanel :market-tab="marketTab" />
    <AiAdvisor :market-tab="marketTab" />
    <SectorAnalysis :market-tab="marketTab" />
    <SymbolAnalysis :market-tab="marketTab" />
    <IndexAnalysis :market-tab="marketTab" />
  </div>
</template>
```

### 子组件通信协议

所有子组件通过 **props 下行 + emit 上行** 通信：

```
容器 (MarketAnalysis.vue)
  │
  ├─ marketTab: string          ← 所有子组件共享
  ├─ marketTab change watch     ← 切换时通知子组件 reload
  │
  ├── MarketReport
  │     props: marketTab
  │     emits: (none, self-contained)
  │
  ├── WatchlistPanel  
  │     props: marketTab
  │     emits: select-symbol(symbol)
  │
  ├── AiAdvisor
  │     props: marketTab
  │     emits: (none, self-contained)
  │
  ├── SectorAnalysis
  │     props: marketTab
  │     emits: select-sector(sectorCode)
  │
  ├── SymbolAnalysis
  │     props: marketTab, selectedSymbol (from WatchlistPanel emit)
  │     emits: (none)
  │
  └── IndexAnalysis
        props: marketTab
        emits: (none)
```

### 提取的 Composables

#### `useMarketSearch.js`
```js
// 封装搜索补全逻辑，供 SymbolAnalysis 和 WatchlistPanel 复用
export function useMarketSearch() {
  const searchQuery = ref('')
  const searchResults = ref([])
  const showDropdown = ref(false)
  const searchTimer = null
  
  async function doSearch() { /* 调用 marketApi.search */ }
  function onSearchInput() { /* 300ms debounce */ }
  // ... 键盘导航、补全等
  return { searchQuery, searchResults, showDropdown, doSearch, onSearchInput }
}
```

#### `useSectorData.js`
```js
export function useSectorData(marketTab) {
  const sectors = ref([])
  const loading = ref(false)
  const currentSector = ref(null)
  
  watch(marketTab, () => { fetchSectors() })
  async function fetchSectors() { /* ... */ }
  
  return { sectors, loading, currentSector, fetchSectors }
}
```

---

## 阶段二：DashboardAiTools.vue → 5 个子组件

### 新目录结构

```
frontend/src/components/design/
├── DesignWizard.vue         ← 设计向导（输入资金）
├── DesignLoading.vue        ← 加载状态（进度条 + 步骤）
├── DesignResult.vue         ← 方案卡片 + 完整报告
├── DesignHistory.vue        ← 历史记录列表
├── StrategyCheckModal.vue   ← 策略检查弹窗（场内/场外选择）
└── StrategyCheckPanel.vue   ← 策略检查结果面板
```

### DashboardAiTools.vue（容器）模板

```html
<template>
  <section class="card core-actions">
    <div class="card-header"><h2>AI 智能工具</h2></div>

    <!-- 功能入口 -->
    <div v-if="!activeCoreFeature" class="core-actions-grid">
      <button @click="enterDesignMode">
        <span>智能设计ETF组合方案</span>
        <span class="badge" v-if="hasRunningTask">任务进行中</span>
      </button>
      <button @click="enterStrategyMode">策略检查分析</button>
      <button @click="enterHistoryMode">历史记录</button>
    </div>

    <!-- 各面板按条件渲染 -->
    <DesignWizard v-if="activeCoreFeature === 'design' && designStep === 'wizard'" ... />
    <DesignLoading v-else-if="activeCoreFeature === 'design' && designStep === 'loading'" ... />
    <DesignResult v-else-if="activeCoreFeature === 'design' && designStep === 'result'" ... />
    <DesignHistory v-else-if="activeCoreFeature === 'history'" ... />
    <StrategyCheckModal v-if="showStrategyCheckModal" ... />
  </section>
</template>
```

---

## 阶段三：Dashboard.vue → 容器 + 子组件

### 子组件

```
frontend/src/components/dashboard/
├── PnlCard.vue              ← 盈亏概览卡
├── AllocationTable.vue      ← 持仓分配表
└── PerformanceChart.vue     ← 业绩趋势图（ECharts）
```

---

## 拆分步骤

```
第 1 步: 创建 composables 目录
   - 从 MarketAnalysis.vue 抽出 useMarketSearch.js
   - 从 MarketAnalysis.vue 抽出 useSectorData.js  
   - 从 MarketAnalysis.vue/AnalysisView.vue 抽出 useChartData.js

第 2 步: 创建 market/ 组件目录
   - MarketReport.vue（从 MarketAnalysis Section 1 复制 + 适配）
   - WatchlistPanel.vue（从 Section 2 复制 + 适配）
   - AiAdvisor.vue（从 Section 3 复制 + 适配）
   - 每新建一个，确认 build 通过
   - 继续 SectorAnalysis.vue、SymbolAnalysis.vue、IndexAnalysis.vue

第 3 步: 替换 MarketAnalysis.vue 为容器
   - 删除 1700+ 行的内容
   - 改为导入 6 个子组件
   - 添加 props 传递和 tab 联动

第 4 步: 创建 design/ 组件目录
   - DesignWizard.vue
   - DesignLoading.vue
   - DesignResult.vue
   - DesignHistory.vue
   - StrategyCheckModal.vue

第 5 步: 替换 DashboardAiTools.vue 为容器

第 6 步: 创建 dashboard/ 组件目录
   - PnlCard.vue
   - AllocationTable.vue

第 7 步: 替换 Dashboard.vue 为容器

第 8 步: 清理
   - 删除重复的 CSS（每个子组件自包含）
   - 确认所有路由和导航正常
   - 删除旧的 `.spec.js` 文件，创建新的子组件测试
```

---

## 测试策略

| 组件类型 | 测试方式 | 覆盖率目标 |
|---------|---------|-----------|
| 容器组件 | 集成测试（所有子组件 stub） | 路由跳转、Tab 切换 |
| 子组件 | 单元测试（mount + props） | 所有状态（loading/empty/error/data） |
| Composables | 纯函数测试（mock API） | 所有分支 |

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 拆分过程中破坏现有功能 | 每拆一个组件就 `npm run build` + 手动验证对应功能 |
| 子组件间状态同步丢失 | 容器组件统一管理 `marketTab` 等共享状态 |
| CSS 样式泄漏/丢失 | 使用 `scoped` 样式，关键样式（涨跌色）从 `theme.css` 变量继承 |
| 重构时间长 | 见下时间估算 |

## 时间估算

| 阶段 | 子组件数 | 估算工时 |
|------|---------|---------|
| 阶段一（MarketAnalysis） | 6 + 3 composables | 3-4 小时 |
| 阶段二（DashboardAiTools） | 5 | 2-3 小时 |
| 阶段三（Dashboard） | 3 | 1-2 小时 |
| 测试 + 清理 | — | 1 小时 |
| **总计** | **14 子组件** | **7-10 小时** |
