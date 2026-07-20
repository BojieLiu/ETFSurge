# ETF Surge — 问题分析报告与修复方案（修订版 v2）

> 生成日期: 2026-07-20 | **修订版 v2**
> 基于第一轮修复后的用户反馈，重新分析全部 17 个问题，复盘修复失败原因，设计第二轮修复方案。

---

## 目录

1. [第一轮修复复盘](#第一轮修复复盘)
   - [修复总览](#修复总览)
   - [失败根因分析](#失败根因分析)
2. [问题现状与第二轮修复方案](#问题现状与第二轮修复方案)
   - [P0 — 仍阻塞](#p0--仍阻塞)
     - [#1 智能组合设计：生成依然失败](#1-智能组合设计生成依然失败)
     - [#4 市场研判报告不展示内容](#4-市场研判报告不展示内容)
     - [#8 个股分析：自动补全消失，按钮置灰](#8-个股分析自动补全消失按钮置灰)
     - [#9 资讯未推送到前端](#9-资讯未推送到前端)
     - [#12 持仓数据：份额列为空，翻页数据消失](#12-持仓数据份额列为空翻页数据消失)
     - [#14 Dashboard 数据未渲染 + 白屏](#14-dashboard-数据未渲染--白屏)
   - [P1 — 仍缺陷](#p1--仍缺陷)
     - [#2 策略检查需弹窗选择组合类型](#2-策略检查需弹窗选择组合类型)
     - [#3 历史记录显示「任务类型」而非原始代码](#3-历史记录显示任务类型而非原始代码)
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
3. [第二轮修复策略与执行路线图](#第二轮修复策略与执行路线图)
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

- `MarketAnalysis.vue`：1812 行，6 个功能区域
- `DashboardAiTools.vue`：2141 行，5 个面板
- 任何局部修改都容易影响其他区域

---

## 问题现状与第二轮修复方案

### P0 — 仍阻塞

#### #1 智能组合设计：生成依然失败

**现状**：按钮点击后，通知栏显示生成失败。

**根因（新增诊断）**：
可能存在以下任一原因：
1. `generate_enhanced_design()` 内部异常未被 `design_worker` 正确捕获
2. `pool_manager.get_pool()` 或 `get_factor_matrix()` 返回空 → 分配器无候选标的 → 生成空方案 → 前端显示失败
3. `_notify()` 的 WS 消息前端未正确处理（即使 `design_id` 已加入 payload）

**需要先诊断**：
```python
# 后端：在 design_worker 的 except 块中记录完整 traceback
logger.exception("[design_worker] 生成失败")
# 前端：在 WS 消息处理器中 console.log 收到的所有消息
```

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 诊断1 | `backend/app/tasks/task_manager.py` | `design_worker` except 块改用 `logger.exception` |
| 诊断2 | `frontend/src/App.vue` | WS handler 增加 `console.log` 调试输出 |
| 诊断3 | `backend/app/services/strategy_design.py` | 确认 `generate_enhanced_design` 对空候选池的处理 |
| 修复 | `task_manager.py:_notify()` | 确保 WS 消息含 `type` 和 `designId` 两个字段 |
| UX | `DashboardAiTools.vue` | 运行中任务时允许点击进入，但显示「任务进行中」弹窗而非直接跳 loading |
| UX | `DashboardAiTools.vue` | loading 页显示任务类型（"智能组合设计生成中..."） |

---

#### #4 市场研判报告不展示内容

**现状**：点击生成后显示「正在调用 DeepSeek 分析市场环境...」，然后回到「点击上方按钮生成当前市场环境研判报告」。

**根因**：
`llm_report_stream` 被修复为 `asyncio.gather` 数据采集 + `generate_market_report` 调用，但：

1. **`generate_market_report` 是非流式的** — 它不是一个 token-by-token 生成器，而是完整构建报告后一次性返回。流式端点把它包裹成 SSE（`event: done` + 完整文本），但前端 `useLLMStream` 期望的是 `event: chunk` 逐 token 推送
2. **前端 SSE 解析不匹配** — 前端在 `MarketAnalysis.vue` 的 `generateMarketReport()` 中可能直接调用非流式端点而非流式端点，或者 SSE 解析器不识别 `event: done` 格式

```javascript
// MarketAnalysis.vue 期望的流式响应格式
// 前端 receiveSSE 期望: { event: 'chunk', data: '...' } 或 { event: 'done', data: { full_text: '...' } }
// 实际返回: event: done\ndata: {"full_text": "...", "disclaimer": "..."}\n\n
// 如果前端的 SSE parser 只处理 'chunk' event，则 'done' event 被忽略
```

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `frontend/src/composables/useLLMStream.js` | 确认 SSE 解析器同时处理 `chunk` 和 `done` event |
| 2 | `frontend/src/components/MarketAnalysis.vue` | `generateMarketReport()` 确认调用正确的端点并正确设置 `marketReport` ref |
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
| 1 | `MarketAnalysis.vue` | 确认 `fetchJson` 已定义（或改用 `marketApi.search`） |
| 2 | `MarketAnalysis.vue` | 增加搜索失败时的错误提示 |
| 3 | `MarketAnalysis.vue` | 允许手动输入代码后直接点击分析（无需从下拉选择） |
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
| 1 | `DashboardAiTools.vue` | 点击「策略检查分析」时弹出 Modal，让用户选择「场内组合」或「场外组合」 |
| 2 | `DashboardAiTools.vue` | 弹窗中显示两种组合的概要信息（ETF 数量、总权重） |
| 3 | `DashboardAiTools.vue` | 用户选择后调用端点并传入对应的 `portfolio_type` |

---

#### #3 历史记录显示「任务类型」而非原始代码

**现状**：加了 `riskProfileLabel` 映射，但用户希望明确看到「策略检查与分析」或「智能组合设计生成」。

**修复方案**：

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `DashboardAiTools.vue` | 在历史项目上增加任务类型标签（`_type` 映射为中文） |
| 2 | `DashboardAiTools.vue` | 方案详情中也显示任务类型 |

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
| 1 | `MarketAnalysis.vue` 或 `sector_fetcher.py` | 根据 `marketTab` 过滤概念板块数据源（A 股从东方财富、港股从...） |
| 2 | `sector_fetcher.py` | 增加 `limit` 参数到 150，增加多个数据源 |
| 3 | `backend/app/analysis/llm.py:generate_sector_analysis` | prompt 增加近 5 日行情分析要求 |
| 4 | `MarketAnalysis.vue` | 移除 AI 开场白 |

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
| 1 | `MarketAnalysis.vue` | 将 Tab 提升到组件最顶部（`market-tabs`），样式加大加粗 |
| 2 | `MarketAnalysis.vue` | Tab 切换时，市场研判/自选/AI 顾问/板块分析/标的分析/指数分析 6 个区域都受 Tab 影响 |
| 3 | `MarketAnalysis.vue` | 每个区域的 API 调用根据 Tab 传递对应的 `market` 参数 |
| 4 | `MarketAnalysis.vue` | 将独立的 `watchlistAssetTypes` 与 `marketTab` 关联 |
| 5 | 如果组件过大 | 考虑将每个 Tab 拆分成独立子组件（`AMarketPanel.vue`、`HKMarketPanel.vue` 等） |

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

## 第二轮修复策略与执行路线图

### 核心原则

1. **集中式执行而非多 Agent 碎片化**：由一个主 Agent 统一协调，分批修复并按顺序验证
2. **先诊断后修复**：对每个 P0 问题先加诊断日志确认根因，再实施修复
3. **增量验证**：每修复 2-3 个问题就重启前后端 + 人工测试关键路径
4. **修复文档同步更新**：每个问题修复后在报告中标记状态

### 执行顺序

```
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
```

### 验证计划

| 阶段 | 验证内容 | 方法 |
|------|---------|------|
| 诊断 | 每个 P0 问题的根因确认 | 加日志/console.log → 重启 → 复现操作 → 读日志 |
| 修复中 | 每次编辑语法正确性 | `npm run build`（前端）/ `python -m py_compile`（后端） |
| 修复后 | 功能链路验证 | `python scripts/verify_e2e.py` |
| 集成 | 全部 17 个问题回归 | 人工按 checklist 逐项确认 |
| 最终 | 前后端联调 | 浏览器打开，走查全部功能页面 |

---

## 优先级总表 v2

| Pri | # | 问题 | 本轮状态 | 根因类型 | 修复工作量 | 关联文件 |
|-----|---|------|---------|---------|-----------|---------|
| **P0** | 8 | 自动补全消失 + 按钮置灰 | 回归 | `fetchJson` 未定义或搜索端点故障 | 低 | `MarketAnalysis.vue` |
| **P0** | 9 | 资讯未推送 | 未修复 | WS 广播条件过严 | 低 | `news_refresh.py`, `NewsView.vue` |
| **P0** | 4 | 研判报告不展示内容 | 修复不完整 | SSE 格式与前端解析不匹配 | 中 | `analysis.py`, `useLLMStream.js` |
| **P0** | 1 | 组合设计生成失败 | 修复不完整 | 需诊断（可能是空候选池或 WS 消息处理） | 中 | `task_manager.py`, `DashboardAiTools.vue` |
| **P0** | 11 | 信号/评分一直为 0 | 未修复 | fetcher 数据链静默失败 | 中 | `china_market.py`, `market_service.py` |
| **P0** | 12 | 份额空 + 翻页消失 | 修复不完整 | 数据模型缺失 + 分页逻辑缺陷 | 中 | `PortfolioManager.vue`, `portfolio_service.py` |
| **P0** | 14 | Dashboard 白屏 | 修复不完整 | Promise.all reject + 双重 fetch | 低 | `Dashboard.vue`, `GlobalIndicesStrip.vue` |
| **P1** | 5 | 自选添加成功但列表空 | 未修复 | 后端查询条件不一致或乐观更新缺失 | 中 | `MarketAnalysis.vue` + 后端 watchlist API |
| **P1** | 7 | 创新药分析错位 | 未修复 | marketTab → sector_type 传导断裂 | 中 | `llm.py`, `sector_fetcher.py` |
| **P1** | 2 | 策略检查需弹窗选择 | 实现过于简单 | 无 UI 交互 | 中 | `DashboardAiTools.vue` |
| **P1** | 6 | AI 顾问回答质量低 | 未修复 | prompt 模板数据不足 | 低 | `llm.py` |
| **P1** | 16 | 市场 Tab 粗糙 | 实现过于简单 | Tab 作用域太小 | 高 | `MarketAnalysis.vue` |
| **P2** | 13 | K 线图增强 | 部分修复 | chart 配置缺失 | 中 | `AnalysisView.vue`, `MarketAnalysis.vue` |
| **P2** | 3 | 历史记录任务类型 | 未完全满足 | 语义标签不清晰 | 极低 | `DashboardAiTools.vue` |
| **P2** | 15 | Token 定价确认 | 未确认 | 需查定价文档 | 低 | `TokenMonitor.vue` |
| **P2** | 17 | 全局 UI 改进 | 未修复 | 设计系统不完整 | 高 | 全部页面 |
| **P2** | 10 | 资讯源单一 | 部分修复 | 数据源集成 | 中 | `news_fetcher.py` |

---

## 第二轮修复 — 一键打开清单（推荐执行顺序）

```
第一批 (P0 核心功能):
  [ ] #8 — 检查 fetchJson 定义 / 确认搜索端点正常
  [ ] #9 — news_refresh.py 放宽广播条件 (level >= 2 或全部) + 初始全量推送
  [ ] #4 — analysis.py: llm_report_stream 增加 chunk 事件 / 前端 SSE 解析兼容
  [ ] #1 — 加诊断日志 → 重启 → 复现 → 定位 → 修复

第二批 (P0 数据/渲染):
  [ ] #11 — 检查 get_history 降级链，确认指标计算正常
  [ ] #12 — 确认 shares_held 字段返回 + 删除冗余成本列 + 分页骨架屏
  [ ] #14 — Dashboard: Promise.all → allSettled + error boundary
  [ ] #5 — 自选添加后乐观更新

第三批 (P1 功能增强):
  [ ] #2 — 策略检查弹窗（场内/场外选择）
  [ ] #16 — 市场 Tab 提升到页面级 + 各功能区域联动
  [ ] #7 — sector prompt 增加近期行情 + 概念覆盖面扩大
  [ ] #6 — AI 顾问 prompt 增加数据框架

第四批 (体验):
  [ ] #3 — 历史记录显示任务类型中文标签
  [ ] #13 — K 线图加标题 + KDJ/RSI sub-chart + tooltip 时间
  [ ] #15 — 确认 DeepSeek V4 Flash 定价
```
