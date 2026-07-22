# Frontend Performance Optimization

> 分析日期：2026-07-22
> 针对前端首屏加载慢、路由切换卡顿的问题分析及优化方案。

---

## 1. 问题根因分析

### 🔴 核心问题 #1：ECharts 在 main.js 中被同步加载（首当其冲）

`main.js` 中的 `import './plugins/echarts'` 是**首屏性能的最大瓶颈**。

```js
// main.js 第 7 行 — 这行导致 ~1MB 的 ECharts 代码在应用初始化时同步下载+解析
import './plugins/echarts'
```

**问题链**：
- `plugins/echarts.js` 导入 `echarts/core` 并注册了 8 个 chart 组件 + canvas renderer
- 虽然 `vite.config.js` 有 `manualChunks: { echarts: ['echarts'] }`，ECharts 被分到了独立 chunk
- 但这个 chunk **仍然在 app 初始化时被加载** — 用户看到白屏的时间包括 ECharts 的下载+解析
- 用户可能只是看一眼 Dashboard，根本用不到 ECharts 的所有功能

**数据估算**：
| 资源 | 体积（gzip） | 说明 |
|------|------------|------|
| vue + vue-router + pinia | ~50KB | 框架本身 |
| echarts + vue-echarts | **~350-500KB** | 首屏加载的最大负担 |
| axios | ~15KB | 轻量 |
| 应用代码 | ~100KB | 所有组件 + 样式 |
| **合计首屏** | **~500-650KB** | 其中 ECharts 占 ~70% |

### 🟡 核心问题 #2：ECharts 重复注册

ECharts 组件在 **4 个地方** 被重复注册：

| 位置 | 注册的组件 | 性质 |
|------|-----------|------|
| `plugins/echarts.js` | CandlestickChart, BarChart, LineChart, Grid, DataZoom, Legend, Tooltip, AxisPointer, CanvasRenderer | 全局（main.js 加载） |
| `Dashboard.vue` | PieChart, BarChart, CanvasRenderer ++ | 路由级（重复） |
| `AnalysisView.vue` | CandlestickChart, BarChart, LineChart ++ | 路由级（重复） |
| `TokenMonitor.vue` | LineChart, BarChart, CanvasRenderer ++ | 路由级（重复） |

每个页面都调用 `use([...])` 注册 ECharts 组件，但这些注册在 `echarts/core` 中是全局的 — 多次注册没有额外代价，但问题是：**每个页面都 import 了 echarts 的子模块，导致无法 tree-shaking**。

### 🟡 核心问题 #3：路由懒加载被 ECharts 破坏

虽然路由本身用了 `() => import()` 懒加载：

```js
// router/index.js — 路由是懒加载的 ✓
component: () => import('../views/Dashboard.vue')
```

但**所有页面都用到了 ECharts**（Dashboard 有 PieChart/BarChart，AnalysisView 有 CandlestickChart，TokenMonitor 有 LineChart），所以 **无论用户访问哪个路由，ECharts 都会被下载**。

### 🟢 次要问题 #4：没有 node_modules 公共 chunk 拆分

`vite.config.js` 只拆分了一个 `echarts` chunk，没有拆分其他第三方库。这意味着：
- 用户访问第一页时，所有 node_modules 代码都在一个 bundle 中
- 浏览器缓存无法分层利用（vue/axios/pinia 等变化频率远低于业务代码）

### 🟢 次要问题 #5：Pinia task store 的 localStorage 序列化

`task.js` 每次调用 `updateTask()` / `addTask()` / `removeTask()` 都会对 `tasks.value` 做 `JSON.stringify` + `localStorage.setItem`。虽然数据量小，但在高频场景下（如 WS 推送状态更新）可能产生微小的卡顿。

### 🟢 已排除：全局 logger 拦截器

`api/index.js` 的 axios 拦截器在每次 API 调用时都会调用 `logger.debug()`。
但 `logger.debug()` 在生产构建中已被 Vite tree-shake 完全消除（因 `import.meta.env.DEV` 为 false），
`logger.info / warn / error` 仅在发生实际错误时触发，**不影响性能**。

---

## 2. 优化方案

### Step 1 — ECharts 从 main.js 移除，改为按需加载（高收益）

**改动**：删除 `main.js` 中的 `import './plugins/echarts'` 行。

此时 ECharts 会变成"真正按需"：只有访问 Dashboard / AnalysisView / TokenMonitor 这些页面时，`import()` 才会触发 ECharts chunk 的下载。

**但有一个前提**：必须确保 ECharts 在 `vue-echarts` 组件 mount 之前已完成注册。Vue Router 的懒加载 + 组件生命周期天然保证了这一点 — `script setup` 中的 `use()` 调用在组件 setup 阶段执行，早于模板渲染。

**实际改动量**：删除 `main.js` 一行，删除 `plugins/echarts.js` 文件（可选）。

**风险**：极低。ECharts 的 `use()` 是幂等的 — 多次调用重复注册同一组件没有副作用。

---

### Step 2 — 优化 Vite 构建 chunk 策略（中收益）

**改动**：`vite.config.js` 的 `build.rollupOptions.output.manualChunks` 增强。

```js
// 当前（仅拆分 echarts）
manualChunks: { echarts: ['echarts'] }

// 优化后（分层拆分）
manualChunks: {
  'vendor-vue': ['vue', 'vue-router', 'pinia', 'vue-echarts'],
  'vendor-axios': ['axios'],
  'vendor-echarts': ['echarts'],
}
```

**效果**：
- Vue 框架层（~50KB）单独缓存，版本升级时才重新下载
- ECharts 层（~500KB）只在访问图表页面时才加载
- `vendor-axios` 单独拆分，体积小但变化极少

---

### Step 3 — 消除 ECharts 重复注册（低收益，但规范化）

Step 1 删除了 `main.js` 中的全局导入后，每个图表页面应各自注册所需的 ECharts 组件。
这是 ECharts 官方推荐的做法，且 `use()` 是幂等的——无需担心跨页面重复。

**改动**：
- 删除 `plugins/echarts.js` 文件（不再需要）
- 各图表页面保留自己的 `use([...])` 调用，只注册该页面实际使用的组件

**效果**：减少不必要的模块加载，每个页面只 pull 自己需要的图表类型。

**验证**：打开 Dashboard → 饼图和柱状图正常渲染；打开 AnalysisView → K 线图正常渲染；打开 TokenMonitor → 趋势图正常渲染。Console 中无 "Unused echarts component" 相关警告。

---

### Step 4 — 任务商店 localStorage 写优化（低收益）

**改动**：`task.js` 中增加防抖或批量写入。

```js
// 当前（每次更新都写）
function updateTask(taskId, changes) {
  Object.assign(task, changes)
  _save(LS_KEYS.tasks, tasks.value)
}

// 优化（收集变更后 debounce 写入）
let _saveTimer = null
function _scheduleSave() {
  if (_saveTimer) clearTimeout(_saveTimer)
  _saveTimer = setTimeout(() => {
    _save(LS_KEYS.tasks, tasks.value)
    _saveTimer = null
  }, 500)
}
```

**效果**：连续的状态更新（如 WS 推送 progress）只触发一次磁盘写入。

---

## 3. 预期效果

| 指标 | 优化前 | 优化后 |
|------|-------|-------|
| 首屏 JS 体积（gzip） | ~500-650KB | **~150-200KB** |
| 首屏加载时间（3G 模拟） | ~3-5s | **~1-2s** |
| ECharts 加载时机 | 应用启动时 | **Dashboard/Analysis 路由激活时** |
| 路由切换卡顿 | AnalysisView 切换有明显延迟 | 首次进入分析页才加载 ECharts |
| node_modules 缓存利用率 | 单一大 chunk | 分层缓存，更新频率低的不重复下载 |

## 4. 实施路线图

```
Step 1 (ECharts 按需) ── 删 1 行，改 1 行，10 分钟
    │ 验证：npm run build 后 dist/assets/ 下 echarts chunk 应
    │      只在 Dashboard/ AnalysisView 的 chunk 中出现 import
    │
Step 2 (Chunk 优化)   ── 改 vite.config.js，5 行配置，10 分钟
    │ 验证：npm run build 输出应显示 vendor-vue / vendor-echarts 等
    │      独立 chunk
    │
Step 3 (消除重复注册) ── 各图表页面清理 use() 调用，20 分钟
    │ 验证：页面图表正常渲染，控制台无 ECharts 警告
    │
Step 4 (localStorage) ── task.js 加 debounce，15 分钟
```

**关键优先级**：Step 1 的收益占整体优化的 70% 以上，应最先做。

---

## 5. 验证方法

### 5.1 Chunk 体积验证（构建时）

```bash
# 安装分析工具（如尚未安装）
npm add -D rollup-plugin-visualizer

# 构建并生成可视化报告
npm run build

# 查看 dist/assets/ 下文件体积
dir dist\assets\*.js  # Windows
# ls -lh dist/assets/  # macOS / Linux
```

期望结果：
- `vendor-echarts.*.js` 约 300-500KB（仅在访问图表页面时加载）
- `vendor-vue.*.js` 约 50KB
- 入口 chunk `index.*.js` 不含 ECharts 代码

### 5.2 加载时间验证（浏览器中）

1. 打开 DevTools → Network → 勾选 "Disable cache"
2. Network 面板下方网络限流选择 "Slow 3G"
3. 刷新首页（`/`），观察：
   - **JS 总下载量**：优化前 ~500-650KB → 优化后 ~150-200KB
   - **Load 事件时间**：应在 2s 内触发
4. 点击导航到 `/portfolio-analysis`，观察：
   - 图表页面首次加载时，Network 面板出现 `vendor-echarts` chunk 的下载

### 5.3 功能验证

| 页面 | 验证项 |
|------|-------|
| Dashboard | 饼图、柱状图渲染正常 |
| AnalysisView | K 线图、成交量图渲染正常 |
| TokenMonitor | 趋势线图渲染正常 |
| 所有页面 | Console 无 "echarts not initialized" 类报错 |
