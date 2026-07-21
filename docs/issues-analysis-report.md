# ETF Surge — 问题分析报告与修复方案（修订版 v3）

> 生成日期: 2026-07-21 | **修订版 v3**
> 基于前两轮修复后的用户反馈，重新分析全部 17 个问题，复盘修复失败原因，引入 Playwright E2E 测试体系，设计第三轮修复方案。
> - [`docs/e2e-testing-plan.md`](./e2e-testing-plan.md) — 完整 E2E 测试方案，本报告引用该方案作为验证保障

---

## 目录

1. [第一轮修复复盘](#第一轮修复复盘)
   - [修复总览](#修复总览)
   - [失败根因分析](#失败根因分析)
2. [问题现状与第三轮修复方案](#问题现状与第三轮修复方案)
   - [P0 — 仍阻塞](#p0--仍阻塞)
     - [#1 智能组合设计：生成依然失败](#1-智能组合设计生成依然失败)
     - [#4 市场研判报告不展示内容](#4-市场研判报告不展示内容)
     - [#8 个股分析：自动补全消失，按钮置灰](#8-个股分析自动补全消失按钮置灰)
     - [#9 资讯未推送到前端](#9-资讯未推送到前端)
     - [#12 持仓数据：份额列为空，翻页数据消失](#12-持仓数据份额列为空翻页数据消失)
     - [#14 Dashboard 数据未渲染 + 白屏](#14-dashboard-数据未渲染--白屏)
   - [P1 — 仍缺陷](#p1--仍缺陷)
     - [#2 策略检查需弹窗选择组合类型](#2-策略检查需弹窗选择组合类型)
     - [#3 历史记录：保留任务类型标签，去除 regime 描述](#3-历史记录保留任务类型标签去除-regime-描述)
     - [#5 自选添加成功但列表为空](#5-自选添加成功但列表为空)
     - [#6 AI 投资顾问回答质量低](#6-ai-投资顾问回答质量低)
     - [#7 板块分析：创新药分析错位，概念缺失](#7-板块分析创新药分析错位概念缺失)
     - [#11 评分和信号仍为 0](#11-评分和信号仍为-0)
     - [#16 行情分市场 Tab 过于粗糙](#16-行情分市场-tab-过于粗糙)
   - [P2 — 体验优化](#p2--体验优化)
     - [#10 资讯数据源单一](#10-资讯数据源单一)
     - [#13 K 线图需加图名、技术指标、时间展示](#13-k-线图需加图名技术指标时间展示)
     - [#15 Token 监控需确认定价策略](#15-token-监控需确认定价策略)
     - [#17 全局 UI 未改进](#17-全局-ui-未改进)
3. [第三轮修复策略与执行路线图](#第三轮修复策略与执行路线图)
4. [优先级总表](#优先级总表)

---

## 第一轮修复复盘

### 修复总览

第一轮通过 4 个 commit 对全部 17 个问题实施了修复：

| Commit | 内容 | 文件数 | 行数 |
|--------|------|--------|------|
| `887c25b` | P0 (#1,#4,#6,#14) + P1 (#3,#8,#13) | 10 | +967 |
| `8b0de19` | P1 (#2,#5,#7,#10,#11,#12) + P2 (#9,#13,#15) | 12 | +154 |
| `d49e325` | P2 (#16,#17) | 3 | +92 |
| `0d77c1f` | 修复 E2E 失败（#2 兼容、DB migration、global indices） | 3 | +38 |

### 失败根因分析

#### 根因 1：多 Agent 碎片化执行，缺乏全局协调

每个 commit 由不同的子 Agent 独立完成，没有统一的代码审查和集成测试。Agent A 修 #8（加 return），Agent B 改 #5（自选搜索），Agent C 改 #16（市场 Tab）—— 彼此不知道对方的变更，导致：

- #5 的自选搜索补全代码修改影响了 #8 的标的搜索自动补全
- #16 的市场 Tab 修改了 `asset_type` 参数传递方式，影响 #7 的板块分析和 #8 的标的分析

#### 根因 2：症状修复而非根因修复

| 问题 | 症状修复 | 根因（未修复） |
|------|---------|--------------|
| #11 评分 0 | 去掉 `/100` 显示 | fetcher 静默返回空数据 → 指标为空 → 信号退化 |
| #4 市场研判 | 改数据采集为 gather | `generate_market_report` 非流式，包裹成 SSE 但前端解析不了 |
| #12 持仓 0 | 加空数据 fallback | 后端行情数据链仍为空，「份额」列后端模型无数据 |

#### 根因 3：用户意图翻译偏差

| 问题 | 用户要求 | 实现结果 | 差距 |
|------|---------|---------|------|
| #2 | 弹窗让用户选择场内/场外 | 加了一个 `portfolio_type` 参数 | 无 UI 交互 |
| #16 | 顶部大 Tab 切换市场，所有功能分市场 | AI 顾问和板块分析之间加了一行 Tab | Tab 作用域有限，板块仍回退到 A 股 |
| #3 | 显示任务类型 | 加了 `riskProfileLabel` 但没显式显示"策略检查分析"或"智能组合设计" | 语义不清晰 |
| #1 | "正在运行"时还能点进去 | Wizard → loading 直接切换，但用户看不到任务类型 | 无弹窗提示 |

#### 根因 4：数据层问题被忽略

- 自选添加后列表为空：后端 `add_watchlist` API 可能成功但 `list_watchlist` 查询条件不一致
- 资讯推送：`news_refresh.py` 只广播 `level >= 3` 的条目，大多数资讯被静默丢弃
- 份额空：`PortfolioManager.vue` 支持编辑 `shares_held` 但 `portfolioApi.getEtfs()` 的响应模型不返回该字段

#### 根因 5：无集成回归测试

4 个 commits 之间没有运行 `verify_e2e.py` 确认没有引入回归（除了最后一次 `0d77c1f` 修复了 E2E 失败）。前端 build 虽然通过，但运行时行为（autocomplete、news WS、dashboard data）完全未验证。

#### 根因 6：大组件耦合，修改风险高

- `MarketAnalysis.vue`：1812 行 → 重构后拆为 6 个子组件 + 容器
- `DashboardAiTools.vue`：2141 行 → 重构后拆为 6 个子组件 + 容器
- 重构本身正确，但重构化之后的功能验证依赖人工走查，缺乏自动化手段

#### 根因 7（本次新增）：零前端集成测试

所有 17 个 issue 中有 14 个是前端问题（按钮显示、输入交互、数据渲染等），但：

- 没有任何自动测试能检测"按钮变文字"、"页面白屏"、"输入框不可交互"这类 CSS/渲染问题
- `verify_e2e.py` 只测后端 HTTP，前端行为完全盲测
- 11 个前端 vitest 文件全是 jsdom 单元测试，抓不到真实浏览器问题
- 导致每次修改都像"盲飞"——改了一个地方，不知道坏了哪里

---

## 问题现状与第三轮修复方案

### P0 — 仍阻塞

#### #1 智能组合设计：生成依然失败（新增 registerTaskCompletion 错误）

**现状**：按钮点击后通知栏显示「提交失败：taskStore.registerTaskCompletion is not a function」。历史记录里能看到任务，但点击查看详情无反应。

**根因**：
1. **（新增）`registerTaskCompletion` 方法不存在**：`frontend/src/views/DashboardAiTools.vue:303` 调用了 `taskStore.registerTaskCompletion(taskData.task_id, callback)`，但 `stores/task.js` 中根本没有这个方法。该方法应为旧版 store 的方法，重构中丢失。
2. `generate_enhanced_design()` 内部异常未被正确捕获
3. `pool_manager.get_pool()` 或 `get_factor_matrix()` 返回空 → 生成空方案
4. 历史记录点击查看详情无反应：`DesignHistory.vue` 的 `@select` 事件绑定了 `onHistorySelect`，该函数可能未正确处理异步加载

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 修复1（阻塞） | `stores/task.js` | 新增 `registerTaskCompletion(taskId, callback)` 方法：注册 WS 回调，在收到完成通知时执行 callback |
| 修复2（阻塞） | `views/DashboardAiTools.vue:303` | 修正 `registerTaskCompletion` 调用方式；或改为纯轮询（已有 polling 备选） |
| 修复3 | `views/DashboardAiTools.vue` | 修复 `onHistorySelect` 函数：正确加载历史详情并显示 |
| 修复4 | `backend/app/tasks/task_manager.py` | `design_worker` except 块改用 `logger.exception` |
| 诊断 | `backend/app/services/strategy_design.py` | 确认 `generate_enhanced_design` 对空候选池的处理 |
| UX | `views/DashboardAiTools.vue` | loading 页显示任务类型（"智能组合设计生成中..."） |

---

#### #4 市场研判报告不展示内容

**现状**：点击生成后显示「正在调用 DeepSeek 分析市场环境...」，然后回到「点击上方按钮生成当前市场环境研判报告」。

**根因**：
`llm_report_stream` 被修复为 `asyncio.gather` 数据采集 + `generate_market_report` 调用，但：

1. **`generate_market_report` 是非流式的** — 它不是一个 token-by-token 生成器，而是完整构建报告后一次性返回。流式端点把它包裹成 SSE（`event: done` + 完整文本），但前端 `useLLMStream` 期望的是 `event: chunk` 逐 token 推送
2. **前端 SSE 解析不匹配** — 前端在 `components/market/MarketReport.vue` 的 `generateMarketReport()` 中调用 `useLLMStream().start()`，流式端点 `POST /analysis/llm-report/stream` 的前端解析可能不匹配

```javascript
// MarketReport.vue 使用 useLLMStream composable
// useLLMStream 的 SSE 解析逻辑在 streamPost (api/index.js)
// streamPost 期望: event: token / event: done / event: error
```

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `frontend/src/composables/useLLMStream.js` | 确认 SSE 解析器同时处理 `token` 和 `done` event |
| 2 | `frontend/src/components/market/MarketReport.vue` | `generateMarketReport()` 确认调用正确的端点并正确设置 `marketReport` ref |
| 3 | `backend/app/routers/analysis.py` | 增加 `chunk` event 推送（将完整文本切分成 chunk），与前端 SSE 解析器对齐 |
| 4 | 两端对调 | 如果流式持续不可用，临时使用非流式端点确保至少报告能展示 |

---

#### #8 个股分析：自动补全消失，按钮置灰

**现状**：
- 搜索输入框的自动联想补全功能消失
- AI 标的分析按钮始终置灰

**根因**（分析代码）：
1. **搜索自动补全**：`MarketAnalysis.vue` 中标的搜索（第 5 节 个股/ETF 分析）使用 `searchQuery` + `doSearch()`。查看代码（line 1180-1198），搜索逻辑使用 `fetchJson()` 而非 `marketApi.search()`，如果 `fetchJson` 是未定义的本地函数，或者后端 `/api/v1/market/search` 返回空，则搜索无结果。

```javascript
// MarketAnalysis.vue:1184-1186
const [etfRes, stockRes] = await Promise.all([
  fetchJson(`/api/v1/market/search?keyword=${encodeURIComponent(q)}`),
  fetchJson(`/api/v1/market/search/stocks?keyword=${encodeURIComponent(q)}`)
])
// 如果 fetchJson 未定义 → ReferenceError → catch 中 searchResults 设为空
```

2. **按钮置灰**：`line 417` — `:disabled="symbolLoading || !selectedSearchItem"`。如果 `selectedSearchItem` 从未被设置（因为搜索无结果无法选择），按钮始终 disabled。

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `composables/useMarketSearch.js` | 确认 `fetchJson` 已定义（或改用 `marketApi.search`） |
| 2 | `components/market/SymbolAnalysis.vue` | 增加搜索失败时的错误提示 |
| 3 | `components/market/SymbolAnalysis.vue` | 允许手动输入代码后直接点击分析（无需从下拉选择） |
| 4 | `backend/app/routers/market.py` | 确认 `/api/v1/market/search` 和 `/search/stocks` 端点正常返回 |

---

#### #9 资讯未推送到前端

**现状**：前端 NewsView 页面无资讯显示，WebSocket 无数据推入。

**根因**：
1. **`news_refresh.py` 广播条件过于严格** — 只广播 `level >= 3` 的条目。如果新闻源返回的条目 level 大部分为 1-2，则无广播
2. **`_last_titles` 去重机制** — 第一次广播后，后续相同的标题不再广播。如果新闻源内容变化不大，长时间无广播
3. **前端 `useNewsWS` 连接问题** — 可能需要确认 WS 连接是否成功建立

```python
# backend/app/tasks/news_refresh.py:42
if _level_of(it) >= 3:  # ← 只广播 level>=3
    await manager.broadcast("news", {"type": "news", "data": it})
```

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `news_refresh.py` | 放宽广播条件：改为 `level >= 2` 或全部广播（含去重） |
| 2 | `news_refresh.py` | 增加启动时的全量推送（不管 level） |
| 3 | `frontend/src/components/NewsView.vue` | 确认 `useNewsWS` 的 `onNews` handler 已正确设置 |
| 4 | `frontend/src/components/NewsView.vue` | 增加初始 HTTP 拉取作为 fallback（`GET /api/v1/news`） |
| 5 | 后端 | 确认 `refresh_news_cache` 定时任务在 lifespan 中正确启动 |

---

#### #12 持仓数据：份额列为空，翻页数据消失

**现状**：
- 份额列为空
- 成本列与成本价重合（可删除成本列）
- 上下翻页数据消失，停下一段时间才重新展示

**根因**：
1. **份额空**：`PortfolioManager.vue line 298-300` 显示 `etf.shares_held`，但后端 `list_etfs()` 的响应数据中可能不包含 `shares_held` 字段（或 SQLite 模型迁移未添加该列）
2. **成本列冗余**：`cost-cell`（成本价 `avg_cost`）和 `cost-basis-cell`（总成本 `cost_basis`）同时显示，数值相似
3. **翻页数据消失**：`PortfolioManager.vue` 使用 `currentEtfs` 计算属性进行分页，翻页时可能因为 `currentPage` 或 `pageSize` 的变化触发 `etfs` ref 重新计算，但异步行情数据未加载完成→临时显示空白

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `backend/app/services/portfolio_service.py` | `list_etfs()` 确认返回 `shares_held` 和 `cost_basis` 字段 |
| 2 | `backend/app/database.py` | 确认 SQLite 迁移包含 `shares_held` 列 |
| 3 | `PortfolioManager.vue` | 删除 `cost-basis-cell` 列（成本列） |
| 4 | `PortfolioManager.vue` | 翻页时添加骨架屏，数据加载完成前保持上一页内容 |
| 5 | `PortfolioManager.vue` | 增加 `loading` 状态管理，翻页时显示 loading 指示器 |

---

#### #14 Dashboard 数据未渲染 + 白屏

**现状**：仓位数据未渲染，全球主流指数缺失，过一会儿页面变白。

**根因**（已修复但仍有问题）：
1. 第一次修复添加了 `globalIndices` ref 和 `fetchGlobalIndices()` 函数（`Dashboard.vue line 414-489`）
2. 但 `GlobalIndicesStrip.vue` 也在 `onMounted` 中自行调用 `fetchGlobalIndices`，可能导致双重请求或状态冲突
3. **白屏根因**：`onMounted` 中的 `Promise.all([fetchGlobalIndices(), fetchAllocations(), fetchPnl()])` 中任一 reject 可能导致 `onMounted` 后续代码不执行
4. 仓位数据未渲染：`portfolioStore` 可能在初始化时返回空数据

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `Dashboard.vue` | 将 `Promise.all` 改为 `Promise.allSettled`，各个失败独立处理 |
| 2 | `Dashboard.vue` | 每个数据区域增加独立的 loading 和 error 状态 |
| 3 | `GlobalIndicesStrip.vue` | 移除内部的 `onMounted` 调用，改为由父组件 `Dashboard.vue` 统一管理 |
| 4 | `Dashboard.vue` | 增加错误边界（error boundary）防止白屏 |

---

### P1 — 仍缺陷

#### #2 策略检查需弹窗选择组合类型

**现状**：当前实现加了一个 `portfolio_type` 参数但无 UI 交互。

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `views/DashboardAiTools.vue` | 点击「策略检查分析」时弹出 `StrategyCheckModal` |
| 2 | `components/design/StrategyCheckModal.vue` | 弹窗中显示两种组合的概要信息（ETF 数量、总权重） |
| 3 | `views/DashboardAiTools.vue` | 用户选择后调用端点并传入对应的 `portfolio_type` |

---

#### #3 历史记录：保留任务类型标签，去除 regime 描述

**现状**：已实现了任务类型标签（`history-task-type` 显示"智能组合设计"或"策略检查与分析"）。但每条记录还附加了 `history-style` 标签显示 regime 描述（如"震荡"、"牛市趋弱"、"平衡型"），这些描述多余且不准确——市态判定与方案风格不是同一回事，共存造成混淆。

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `DesignHistory.vue` | 保留 `history-task-type` 标签（`智能组合设计` / `策略检查与分析`） |
| 2 | `DesignHistory.vue` | **移除** `history-style` 标签（即 `riskProfileLabel` 和 `regimeLabel` 渲染的行） |
| 3 | `DesignHistory.vue` | `h._type === 'check'` 的记录也不再显示 regime 标签 |

---

#### #5 自选添加成功但列表为空

**现状**：弹窗显示「添加成功」但自选列表为空。

**根因**：
`addWatchlist()` 在第 878-879 行：
```javascript
const { addWatchlist } = useMarketStore()
await addWatchlist(watchlistForm.value.symbol, watchlistForm.value.asset_type, watchlistForm.value.notes)
```
但如果 `addWatchlist` 内部调用后端 API 成功但返回的数据格式与前端期望不一致，或者 `fetchWatchlist()` 的查询条件与添加时不同（例如后端 `GET /watchlist` 按 `asset_type` 过滤但前端未传参数），则列表显示为空。

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | 前端 | 添加成功后增加延迟（500ms）再刷新列表 |
| 2 | 前端 | 刷新后检查 `watchlist` 数组长度 |
| 3 | 后端 | 确认 `POST /watchlist` 和 `GET /watchlist` 的查询条件一致 |
| 4 | 前端 | 添加后直接在前端 push 到本地列表（乐观更新），无需重新 fetch |

---

#### #6 AI 投资顾问回答质量低

**现状**：提问「今天的行情你怎么看？」回答缺乏有效信息。

**根因**：
Prompt 质量不足。`llm.py` 中的 `generate_advice()` 函数构建的 prompt 可能缺少：
- 实时行情数据（涨跌幅、成交量）
- 市场状态判断（recent regime）
- 具体的技术指标数值
- 明确的分析框架

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `backend/app/analysis/llm.py` | 重写 `generate_advice` 的 prompt 模板，加入明确的四段分析框架：大盘概况、热点板块、资金流向、后市展望 |
| 2 | `backend/app/analysis/llm.py` | 注入更多实时数据（至少包含主要指数涨跌幅、成交量、涨跌家数比） |
| 3 | `backend/app/analysis/llm.py` | 加入市场状态（regime）和情绪指标 |

---

#### #7 板块分析：创新药分析错位，概念缺失

**现状**：
- 选择银行板块效果满意
- 选择创新药概念时分析主体成了港股而非 A 股
- 仅有中长期行情回顾，缺乏近期行情分析
- 概念缺失严重（光模块、CPO、半导体设备等）
- AI 开场白仍在

**根因**：
1. **港股/A 股错位**：`marketTab` ref 值为 `'A'` 但代码中 `sector_type` 参数未能正确传递到 `sector_fetcher` → 部分概念板块数据源回退到港股
2. **概念缺失**：`fetch_concept_sectors(limit=80)` 只拿前 80 个概念，且数据源为东方财富，覆盖度有限
3. **缺乏近期行情**：`sector_analysis` prompt 只包含了中长期指标，没有注入近 1-5 日涨跌幅数据
4. **开场白**：`MarketAnalysis.vue` 中 sectors 渲染的 `v-if` 条件需要进一步排查

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `composables/useSectorAnalysis.js` 或 `sector_fetcher.py` | 根据 `marketTab` 过滤概念板块数据源（A 股从东方财富、港股从...） |
| 2 | `sector_fetcher.py` | 增加 `limit` 参数到 150，增加多个数据源 |
| 3 | `backend/app/analysis/llm.py:generate_sector_analysis` | prompt 增加近 5 日行情分析要求 |
| 4 | `components/market/SectorAnalysis.vue` | 移除 AI 开场白 |

---

#### #11 评分和信号仍为 0

**现状**：综合信号/评分一直显示持有/0。

**根因**（未真正修复）：
第一轮修复只做了：
1. 在 `china_market.py` 的静默吞错处加了 `logger.warning`（不影响行为）
2. 前端去掉了 `/100` 显示

但根因仍是 **fetcher 数据管道静默失败**：

```python
# china_market.py 或 market_service.py 中
# 某些数据源的 get_history() 返回 []，compute_all_indicators 返回 {}
# generate_signal({}) 返回 {"signal": "hold", "score": 0}
```

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `backend/app/fetchers/china_market.py` | 在 `_mootdx_history` 静默返回 `[]` 之前记录 warning 并尝试降级到 akshare |
| 2 | `backend/app/services/market_service.py` | 确认 `get_history()` 的降级链是否正确执行 |
| 3 | 后端 | 增加 `verify_signal` 端点用于调试 |
| 4 | 后端 | 在 `get_history` 返回空时尝试更多数据源 |

---

#### #16 行情分市场 Tab 过于粗糙

**现状**：
- 切换市场后仍然使用 A 股的板块和概念
- 用户期望所有行情分析功能都有 A 股、港股、美股三个大 Tab
- Tab 应该在页面最上方，选择后整个页面切换（包含：市场研判、自选、AI 投资顾问、板块概念分析）

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `views/MarketAnalysis.vue` | 确保顶部 `market-tabs` 切换时所有子组件都收到正确的 `marketTab` prop |
| 2 | `components/market/MarketReport.vue` | 接收 `marketTab` prop，按市场筛选数据调用对应 API |
| 3 | `components/market/WatchlistPanel.vue` | 接收 `marketTab` prop，`filteredWatchlist` 根据 marketTab 过滤 |
| 4 | `components/market/AiAdvisor.vue` | 接收 `marketTab` prop，请求中传 `market` 参数 |
| 5 | `components/market/SectorAnalysis.vue` | 使用 `useSectorAnalysis` composable，`marketTab` 变化时触发 `onSectorTypeChange` |
| 6 | `components/market/SymbolAnalysis.vue` | 接收 `marketTab` prop，搜索/分析 API 传对应的 `asset_type` |
| 7 | `components/market/IndexAnalysis.vue` | 接收 `marketTab` prop，`filteredIndicesByTab` 根据 marketTab 过滤 |

---

### P2 — 体验优化

#### #10 资讯数据源单一

**修复方案**：与 #9 一起修复。见 #9。

---

#### #13 K 线图需加图名、技术指标、时间展示

**现状**（已修复部分）：
- 鼠标滚轮问题已修复（改为了平移）
- 成交量、MACD 图无标题
- KDJ、RSI 图未显示（仅显示数值）
- K 线悬停未展示时间
- K 线显示代码而非名称
- 评分/综合信号仍为 0（见 #11）

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `AnalysisView.vue` chartOption | 成交量 sub-chart 增加 `name: '成交量'` |
| 2 | `AnalysisView.vue` chartOption | MACD sub-chart 增加 `name: 'MACD'` |
| 3 | `AnalysisView.vue` | 增加 KDJ 和 RSI 的独立 sub-chart（可切换显示）或切换按钮 |
| 4 | `AnalysisView.vue` tooltip | tooltip formatter 增加日期时间格式化 |
| 5 | `AnalysisView.vue` | 显示的标的名称改为 `name`（需传入 name prop） |

---

#### #15 Token 监控需确认定价策略

**现状**：已显示费用，但需确认是否基于 DeepSeek V4 Flash 实际定价且考虑峰谷价格。

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `TokenMonitor.vue` | 确认 price 表为 DeepSeek V4 Flash 最新定价 |
| 2 | `TokenMonitor.vue` | 增加峰谷时段标注（如适用） |
| 3 | 后端 | 确认 `UsageRecord` 记录的 `model` 字段正确 |

---

#### #17 全局 UI 未改进

**现状**：未修改。

**修复方案**：推迟到上述 P0/P1 问题全部解决后再实施。

---

## 第三轮修复策略与执行路线图

### 核心原则

1. **集中式执行而非多 Agent 碎片化**：由一个主 Agent 统一协调，分批修复并按顺序验证
2. **先诊断后修复**：对每个 P0 问题先加诊断日志确认根因，再实施修复
3. **增量验证**：每修复 2-3 个问题就重启前后端 + 人工测试关键路径
4. **修复文档同步更新**：每个问题修复后在报告中标记状态

### 执行顺序

```
第零批（安全网 — 必须先做）
  ├── Playwright E2E 测试体系搭建
  │     ├── 依赖安装 + config
  │     ├── 所有页面 @smoke 测试（不白屏、按钮可点、输入框可交互）
  │     ├── API mock 层（模拟全球指数 / 搜索 / stream 端点）
  │     └── 回归 spec 框架（每修一个 bug 追加一个测试用例）
  └── 后端 verify_e2e.py 扩展
        ├── 按模块分组（market / portfolio / analysis / news / admin / ws）
        ├── 新增 ~66 个端点测试用例
        ├── WebSocket 实际连接测试（websockets 库）
        └── 支持 --module / --smoke 选择性运行

第一批（P0 — 核心功能恢复）
  ├── #8 搜索自动补全恢复（低风险，优先恢复标的选择功能）
  ├── #9 资讯推送修复（低风险，WS 广播条件放宽）
  ├── #4 市场研判报告内容展示（中风险，SSE 解析对齐）
  └── #1 组合设计诊断与修复（高风险，需后端诊断）

第二批（P0 — 数据/渲染修复）
  ├── #11 信号/评分数据链修复（中风险，fetcher 降级链）
  ├── #12 持仓数据渲染（中风险，数据模型 + 前端逻辑）
  ├── #14 Dashboard 白屏修复（低风险，error boundary）
  └── #5 自选列表空修复（低风险，乐观更新）

第三批（P1 — 功能增强）
  ├── #2 策略检查弹窗（中风险，新的 UI 组件）
  ├── #16 市场 Tab 重构（高风险，涉及组件拆分）
  ├── #7 板块分析优化（中风险，prompt + 数据源）
  └── #6 AI 顾问 prompt 优化（低风险）

第四批（P1+P2 — 体验优化）
  ├── #3 历史记录任务类型显示（极低风险）
  ├── #13 K 线图增强（中风险，chart 配置）
  └── #15 Token 定价验证（低风险）

第五批（P2 — UI 优化）
  └── #17 全局 UI 改进（高风险，推迟）

第六批（清理 — E2E 全覆盖之后）
  ├── 删除 5 个废弃端点
  │     ├── GET /indices/search（与 /indices/meta 重叠）
  │     ├── GET /sectors（与 industry/concept 重叠）
  │     ├── GET /designs/{id}/status（/designs/{id} 已含状态）
  │     ├── POST /sector-analysis（已全部改用 stream 版）
  │     └── POST /symbol-analysis（已全部改用 stream 版）
  ├── 删除 changeClass.spec.js 中的废弃 mock
  ├── 为保留的 9 个端点加 # TODO 注释
  └── 跑 verify_e2e --smoke + test:e2e:smoke → ALL PASS
```

### 验证计划

| 阶段 | 验证内容 | 方法 |
|------|---------|------|
| 诊断 | 每个 P0 问题的根因确认 | 加日志/console.log → 重启 → 复现操作 → 读日志 |
| 修复中 | 每次编辑语法正确性 | `npm run build`（前端）/ `python -m py_compile`（后端） |
| 修复后 | 后端功能链路 | `python scripts/verify_e2e.py` |
| 修复后 | 前端核心链路（不白屏、按钮渲染、输入可交互） | `npm run test:e2e:smoke`（Playwright @smoke 用例集） |
| 修复后 | 受影响的 spec 专项验证 | `npm run test:e2e -- --grep "相关用例名"` |
| 集成 | 全部 17 个问题回归 | `npm run test:e2e`（Playwright 全量） + `verify_e2e.py` |
| 最终 | 视觉回归检测 | `npm run test:e2e:visual`（截图对比） |

---

## 优先级总表 v3

| Pri | # | 问题 | 本轮状态 | 根因类型 | 修复工作量 | 关联文件 |
|-----|---|------|---------|---------|-----------|---------|
| **P0** | 8 | 自动补全消失 + 按钮置灰 | 回归 | `fetchJson` 未定义或搜索端点故障 | 低 | `composables/useMarketSearch.js` |
| **P0** | 9 | 资讯未推送 | 未修复 | WS 广播条件过严 | 低 | `news_refresh.py`, `NewsView.vue` |
| **P0** | 4 | 研判报告不展示内容 | 修复不完整 | SSE 格式与前端解析不匹配 | 中 | `analysis.py`, `useLLMStream.js` |
| **P0** | 1 | 组合设计生成失败（registerTaskCompletion） | 回归 | 重构丢失方法 | 中 | `stores/task.js`, `views/DashboardAiTools.vue` |
| **P0** | 11 | 信号/评分一直为 0 | 未修复 | fetcher 数据链静默失败 | 中 | `china_market.py`, `market_service.py` |
| **P0** | 12 | 份额空 + 翻页消失 | 修复不完整 | 数据模型缺失 + 分页逻辑缺陷 | 中 | `PortfolioManager.vue`, `portfolio_service.py` |
| **P0** | 14 | Dashboard 白屏 | 修复不完整 | Promise.all reject + 双重 fetch | 低 | `Dashboard.vue`, `GlobalIndicesStrip.vue` |
| **P1** | 5 | 自选添加成功但列表空 | 未修复 | 后端查询条件不一致或乐观更新缺失 | 中 | `WatchlistPanel.vue` + 后端 watchlist API |
| **P1** | 7 | 创新药分析错位 | 未修复 | marketTab → sector_type 传导断裂 | 中 | `llm.py`, `sector_fetcher.py` |
| **P1** | 2 | 策略检查需弹窗选择 | 已实现但交互不全 | 弹窗后白屏 | 中 | `views/DashboardAiTools.vue`, `StrategyCheckModal.vue` |
| **P1** | 6 | AI 顾问回答质量低 | 未修复 | prompt 模板数据不足 | 低 | `llm.py` |
| **P1** | 16 | 市场 Tab 粗糙 | 已拆分为子组件但联动不足 | Tab prop 传递断裂 | 中 | `views/MarketAnalysis.vue`, `components/market/*` |
| **P2** | 13 | K 线图增强 | 部分修复 | chart 配置缺失 | 中 | `AnalysisView.vue`, `SymbolAnalysis.vue` |
| **P2** | 3 | 历史记录任务类型 | 未完全满足 | 语义标签不清晰 | 极低 | `DashboardAiTools.vue` |
| **P2** | 15 | Token 定价确认 | 未确认 | 需查定价文档 | 低 | `TokenMonitor.vue` |
| **P2** | 17 | 全局 UI 改进 | 未修复 | 设计系统不完整 | 高 | 全部页面 |
| **P2** | 10 | 资讯源单一 | 部分修复 | 数据源集成 | 中 | `news_fetcher.py` |

---

## 第三轮修复 — 一键打开清单（推荐执行顺序）

> 前置条件：Playwright E2E 测试体系已搭建（见 `docs/e2e-testing-plan.md`）
> 每个修复步骤后：`npm run test:e2e:smoke` 确认未引入回归

```
第零批 (E2E 安全网 — 前端):
  [ ] npm install @playwright/test
  [ ] playwright install chromium
  [ ] 创建 e2e/config/playwright.config.js
  [ ] 创建 e2e/utils/server.js + server-setup.js + server-teardown.js (启停前后端)
  [ ] 创建 e2e/utils/assertions.js (自定义断言)
  [ ] 创建 e2e/utils/seed.js (测试数据注入，通过后端 API)
  [ ] 创建 e2e/specs/01-smoke.spec.js (全页面 200 不白屏 + 按钮 + 输入框)
  [ ] npm run test:e2e:smoke → ALL PASS  (01-smoke 不依赖 seed，可独立运行)

第零批 (E2E 安全网 — 后端):
  [ ] pip install websockets (用于 WS 测试)
  [ ] 扩展 verify_e2e.py：按模块分组（section_market / portfolio / analysis / news / admin / ws）
  [ ] 新增 Market 29 个端点测试
  [ ] 新增 Portfolio 补齐 13 个端点测试
  [ ] 新增 Analysis 12 个端点测试（仅验证 200/4xx）
  [ ] 新增 News 5 个端点测试
  [ ] 新增 Admin 3 个端点测试
  [ ] 新增 WebSocket 5 个实际连接测试
  [ ] 新增 --module / --smoke 命令行参数
  [ ] python scripts/verify_e2e.py --smoke → ALL PASS

第一批 (P0 核心功能):
  [ ] #8 — 检查 fetchJson 定义 / 确认搜索端点正常
  [ ] #9 — news_refresh.py 放宽广播条件 (level >= 2 或全部) + 初始全量推送
  [ ] #9 — 追加 12-regression.spec.js 用例 → RUN → 修复 → PASS
  [ ] #4 — analysis.py: llm_report_stream 增加 chunk 事件 / 前端 SSE 解析兼容
  [ ] #1 — stores/task.js 新增 registerTaskCompletion + views/DashboardAiTools.vue 修复 onHistorySelect

第二批 (P0 数据/渲染):
  [ ] #11 — 检查 get_history 降级链，确认指标计算正常
  [ ] #12 — 确认 shares_held 字段返回 + 删除冗余成本列 + 分页骨架屏
  [ ] #14 — Dashboard: Promise.all → allSettled + error boundary
  [ ] #5 — 自选添加后乐观更新

第三批 (P1 功能增强):
  [ ] #2 — 策略检查弹窗（场内/场外选择）
  [ ] #16 — 修复 marketTab prop 传递，确保 6 个子组件联动
  [ ] #7 — sector prompt 增加近期行情 + 概念覆盖面扩大
  [ ] #6 — AI 顾问 prompt 增加数据框架

第四批 (体验):
  [ ] #3 — 保留任务类型标签，去除 regime 描述（DesignHistory.vue）
  [ ] #13 — K 线图加标题 + KDJ/RSI sub-chart + tooltip 时间
  [ ] #15 — 确认 DeepSeek V4 Flash 定价

第五批 (清理 — E2E 全覆盖之后):
  [ ] 删除 GET /indices/search（与 /indices/meta 重叠）
  [ ] 删除 GET /sectors（与 industry/concept 重叠）
  [ ] 删除 GET /designs/{id}/status（/designs/{id} 已含状态）
  [ ] 删除 POST /sector-analysis（已改用 stream 版）
  [ ] 删除 POST /symbol-analysis（已改用 stream 版）
  [ ] 删除 changeClass.spec.js 中的废弃 mock
  [ ] 为保留的 9 个端点加 # TODO: 未接入前端 注释
  [ ] python scripts/verify_e2e.py --smoke → ALL PASS
  [ ] npm run test:e2e:smoke → ALL PASS
```
