## 十一、前端冗余代码清理清单

实施完整方案后，以下前端代码变为冗余，在 Phase 3-4 执行过程中删除。

### 11.1 废弃 API 方法

| 方法 | 文件 | 行号 | 删除原因 |
|------|------|------|----------|
| `portfolioApi.design()` | `api/index.js:84-90` | 已被 `designAsync` 取代，无组件引用 |
| `analysisApi.portfolioDesign()` | `api/index.js:105` | `/analysis/portfolio-design` 路由删除 |
| `analysisApi.portfolioDesignStream()` | `api/index.js:106` | `/analysis/portfolio-design/stream` 路由删除 |

**确认方式**：grep 全项目确认 `portfolioApi.design(` 无其他引用。

### 11.2 废弃组件内代码

| 代码 | 文件 | 行号 | 删除原因 |
|------|------|------|----------|
| `designWsConnect()` + `designWs` | `DashboardAiTools.vue` | 1023-1079 | 设计报告 WS 改为由 `/ws/design-report/{session_id}` 统一管理，不再需要组件内手动 WS 连接 |
| `retryReport()` | `DashboardAiTools.vue` | 800 | 报告来自数据管道，不再需要重试逻辑 |
| `designReportStale` computed | `DashboardAiTools.vue` | 491 | 同上 |
| 报告 Tab 的 waiting/stale/error 三态 UI | `DashboardAiTools.vue` | 175-191 | 由通用 TaskProgress 组件取代 |
| loading 进度条 UI（整体） | `DashboardAiTools.vue` | 113-157 | 抽取为通用 `<TaskProgress>` 组件，原位置引用新组件 |

### 11.3 可抽取为通用组件的代码

| 原代码 | 目标组件 | 行号 | 说明 |
|--------|----------|------|------|
| loading 进度条 UI | `TaskProgress.vue` | 113-157 | 含进度条、百分比、步骤列表、加载提示 |
| 策略检查 loading 区 | `TaskProgress.vue` | 362-365 | 与设计 loading 重复，同组件复用 |

### 11.4 保留但微调的代码

| 代码 | 文件 | 说明 |
|------|------|------|
| `useLLMStream` composable | `composables/useLLMStream.js` | 保留，llm-report/advice/sector/symbol 的 SSE 流继续使用 |
| `useMarketWS` | `composables/useMarketWS.js` | 保留，实时行情 WS 通道 |
| `useNewsWS` | `composables/useNewsWS.js` | 保留，新闻推送 WS 通道 |
| `MarketAnalysis.vue` SSE 调用 | `MarketAnalysis.vue:837,956,1179` | 保留，其中 llm-report stream 新增 WS async 入口作为替代 |

### 11.5 删除影响范围

| 文件 | 删除行数 | 影响 |
|------|----------|------|
| `api/index.js` | ~20 行 | 3 个废弃方法 |
| `DashboardAiTools.vue` | ~80 行 | 旧 WS 连接 + 重试逻辑 + 三态 UI → 替换为新组件引用 |
| **合计** | **~100 行** | 无功能影响，均为被新架构替换的旧实现 |
