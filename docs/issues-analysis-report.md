# ETF Surge — 问题分析报告与修复方案

> 生成日期: 2026-07-20
> 本次分析覆盖全部 17 个问题，包含代码级根因定位、影响评估与修复方案。  
> **原则：分析先行，未修改任何代码。**

---

## 目录

1. [P0 — 核心功能阻塞](#p0--核心功能阻塞)
   - [#1 智能组合设计：通知显失败，历史无记录](#1-智能组合设计通知显失败历史无记录)
   - [#4 市场研判流式端点：`_fetch_all_market` 未定义](#4-市场研判流式端点_fetch_all_market-未定义)
   - [#6 AI 投资顾问：`analysisApi` 未定义](#6-ai-投资顾问analysisapi-未定义)
   - [#14 Dashboard 所有数据未渲染](#14-dashboard-所有数据未渲染)
2. [P1 — 功能缺陷 / 数据不准确](#p1--功能缺陷--数据不准确)
   - [#2 策略检查未区分场内/场外组合](#2-策略检查未区分场内场外组合)
   - [#3 历史方案显示原始代码](#3-历史方案显示原始代码)
   - [#5 自选标的：无搜索补全，添加无反馈](#5-自选标的无搜索补全添加无反馈)
   - [#7 板块分析：prompt 冲突，概念不全](#7-板块分析prompt-冲突概念不全)
   - [#8 个股分析：角色错配 + 缺 LLM 调用](#8-个股分析角色错配--缺-llm-调用)
   - [#9 资讯重要性分级不合理](#9-资讯重要性分级不合理)
   - [#11 信号全是持有 / 评分 0](#11-信号全是持有--评分-0)
   - [#12 持仓数据为 0 + 白屏](#12-持仓数据为-0--白屏)
3. [P2 — 体验优化 / 架构建议](#p2--体验优化--架构建议)
   - [#10 资讯数据源单一](#10-资讯数据源单一)
   - [#13 K 线滚轮缩放体验差](#13-k-线滚轮缩放体验差)
   - [#15 Token 监控页面的合理性与改进](#15-token-监控页面的合理性与改进)
   - [#16 行情分析分市场板块的可行性与建议](#16-行情分析分市场板块的可行性与建议)
   - [#17 全局 UI 与样式优化](#17-全局-ui-与样式优化)
4. [优先级总表](#优先级总表)

---

## P0 — 核心功能阻塞

### #1 智能组合设计：通知显失败，历史无记录

**现象**：点击"智能设计 ETF 组合方案"后，通知栏显示"组合方案生成失败"，历史记录为空。

**根因定位**：`design_id` 在全链回传路径中丢失，导致前端认为生成失败。

#### 调用链路（逐段排查）

```
前端点击 "开始设计"
  → DashboardAiTools.vue:startDesign()
    → portfolioApi.designAsync({ capital })
      → POST /portfolio/design-async
        → 返回 { task_id, status: "pending", ... }   ← 无 design_id
    → taskStore.addTask(taskId)                       ← 加入运行中列表

后端 design_worker 执行
  → task_manager.py:design_worker()
    → 生成方案、存入 DB，获得 design_id
    → task.result = { design_id, ... }                ← ✓ 存在，但未暴露
    → _notify({ type: "task_update", task_id, status, progress })
                                                        ← ✗ 不含 design_id

前端 WS 收到通知
  → App.vue: WebSocket handler
    → taskStore.updateTask(taskId, { status, progress, designId: ??? })
    → 从哪儿拿 design_id？3 条路都失败：
      (a) WS 消息本身没有 design_id
      (b) 又调 portfolioApi.getTask(taskId)
          → GET /tasks/{task_id} 返回 { task_id, status, progress }
                                                        ← ✗ 不含 result
      (c) 前端轮询无果
    → 执行 onDesignFailed() → toast "生成失败" → 重置到 wizard
```

**更严重的问题**：DB 写入失败被静默吞掉

```python
# task_manager.py:156-161
try:
    db_session.add(design)
    await db_session.commit()
    design_id = design.id
except Exception:
    logger.warning("[design] Failed to save design to DB")
    # design_id 保持 None，task 仍标记为 completed
```

这意味着：
- DB 保存成功 → design_id 被后端持有但前端拿不到 → 前端显示"失败"（假阴性）
- DB 保存失败 → 无历史记录、前端显示"失败"（真阴性但静默，用户没有报错细节）

#### 修复方案

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `task_manager.py:_notify()` | WS 广播 payload 增加 `design_id` 字段 |
| 2 | `routers/portfolio.py:GET /tasks/{id}` | 返回中加入 `result`（含 `design_id`） |
| 3 | `task_manager.py:design_worker()` | DB 写入失败应标记任务为 `failed` 并记录详细错误 |
| 4 | `DashboardAiTools.vue` | 从 WS/API 两路都能拿到 design_id 后，任一先到即用 |

---

### #4 市场研判流式端点：`_fetch_all_market` 未定义

**现象**：点击"生成市场研判"→ 报错 `生成失败：LLM streaming failed: name '_fetch_all_market' is not defined`

**根因**：流式端点 `llm_report_stream` 调用三个已删除函数，非流式端点在之前重构中已改用编排器数据管道但流式端点被遗漏。

#### 代码证据

```python
# backend/app/routers/analysis.py:451-478
@router.post("/llm-report/stream")
async def llm_report_stream(req: LLMReportRequest):
    try:
        market_data, indices, commodities = await _fetch_all_market()   # ← 已删除
        news = await _collect_news()                                     # ← 已删除
        # ...
        prompt = _build_report_prompt(indices, commodities, ...)         # ← llm.py 中有但未 import
```

而 file 开头 line 88 注释明确写道：
```python
# _fetch_all_market 已废弃 — 数据管道统一在编排器中采集
```

非流式端点 (line 96-170) 已改用：
```python
results = await asyncio.gather(
    asyncio.wait_for(get_all_realtime(), timeout=15),
    asyncio.wait_for(get_indices(), timeout=15),
    asyncio.wait_for(get_commodities(), timeout=15),
    asyncio.to_thread(fetch_news_headlines),
    asyncio.to_thread(fetch_macro_news),
    return_exceptions=True,
)
```

#### 修复方案

将 `llm_report_stream` 的数据采集逻辑平行替换为非流式版本的实现：

1. 使用 `asyncio.gather` 替代 `_fetch_all_market` 和 `_collect_news`
2. 注入 `pool_manager` 的 regime/sentiment 缓存数据（见非流式端点 line 154-165）
3. 调用 `generate_market_report()` 而非直接构建 prompt，保持一致性
4. 引用 `get_agent("market_report")` 进行流式输出

---

### #6 AI 投资顾问：`analysisApi` 未定义

**现象**：在"AI 投资顾问"输入问题并发送 → 报错 `提问失败：analysisApi is not defined`

**根因**：`MarketAnalysis.vue:773` 调用 `analysisApi.llmAdvice()` 但该文件 **未导入 `analysisApi`**。

```javascript
// MarketAnalysis.vue:644-654 — 当前 imports
import { ref, computed, onMounted, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import AppButton from './ui/AppButton.vue'
import AppInput from './ui/AppInput.vue'
import AppSelect from './ui/AppSelect.vue'
import { useLLMStream } from '@/composables/useLLMStream'
import { useMarketStore } from '@/stores/market'
// ← 缺少 import { analysisApi } from '@/api'
```

**修复方案**：在 line 654 后添加一行（耗时 10 秒）：

```javascript
import { analysisApi } from '@/api'
```

---

### #14 Dashboard 所有数据未渲染

**现象**：Dashboard 页面打开后，所有数据区域（盈亏、主流指数等）为空白。

**根因**：3 处级联的引用错误导致 `onMounted` 中的整个 `Promise.all` reject。

#### 关键位置

```javascript
// Dashboard.vue 的 <script setup> 中
const globalIndices = ref([])    // ← 未声明！整个 ref 缺失
const marketTimer = ref(null)    // ← 未声明！

function fetchGlobalIndices() {  // ← 未定义！
  // ...
}

onMounted(() => {
  await Promise.all([
    fetchGlobalIndices(),   // ReferenceError → 整个 Promise.all 失败
    fetchAllocations(),
    fetchPnl(),
  ])
})
```

另一个子组件：

```javascript
// GlobalIndicesStrip.vue:62
const res = await marketApi.fetchAll()  // ← marketApi 没有 fetchAll 方法
// 正确应为 marketApi.indicesGlobal()
```

API 响应结构也不匹配：

```javascript
// 预期：{ "A股": [...], "港股": [...], ... }
// 实际：{ "indices": { "A股": [...], "港股": [...], ... } }
```

#### 修复方案

| 步骤 | 位置 | 变更 |
|------|------|------|
| 1 | `Dashboard.vue` | 声明 `globalIndices` 和 `marketTimer` ref |
| 2 | `Dashboard.vue` | 定义 `fetchGlobalIndices()` 函数，调用 `marketApi.indicesGlobal()` |
| 3 | `GlobalIndicesStrip.vue:62` | `marketApi.fetchAll()` → `marketApi.indicesGlobal()` |
| 4 | `GlobalIndicesStrip.vue` | 解包 `res.data.indices` 而非直接取 `res.data` |

---

## P1 — 功能缺陷 / 数据不准确

### #2 策略检查未区分场内/场外组合

**现象**：策略检查分析将场内和场外 ETF 当作同一个组合分析，而非各自独立分析。

**根因**：全链路缺少 `portfolio_type` 参数传递——这是系统内唯一遗漏此参数的端点。

#### 对比其他端点

| 端点 | `portfolio_type` 参数 | 状态 |
|------|----------------------|------|
| `GET /etfs` | 有 | ✓ |
| `POST /calculate` | 有 | ✓ |
| `POST /daily-pnl` | 有 | ✓ |
| `GET /drift-check` | 有 | ✓ |
| `GET /export` | 有 | ✓ |
| **`POST /strategy-check-async`** | **无** | **✗** |

#### 调用链路脱漏

```
前端: DashboardAiTools.vue:1125
  portfolioApi.strategyCheck({ total_capital: 500000 })
                                   ↑ 没有 portfolio_type

后端: portfolio.py:334
  total_capital = task.get("total_capital", 500000)
                                   ↑ 只取 total_capital

Worker: strategy_check_worker.py:39
  strategy_check(db, capital)      ↑ 没有 portfolio_type

Service: portfolio_service.py:350
  etfs = await list_etfs(db)       ↑ 不带筛选，返回全部
```

模型层同样缺失字段：
```python
# models/portfolio_design.py 或其他 strategy_check 模型
class StrategyCheckRecord(Base):
    # ... 现有字段
    # portfolio_type: str | None  ← 缺失，无法区分
```

#### 修复方案

1. **前端**：在策略检查入口新增组合类型选择框（或自动对两种类型各跑一次）
2. **API**：`POST /strategy-check-async` 添加可选 `portfolio_type` 参数
3. **Worker**：传递 `portfolio_type` 到 `strategy_check()`
4. **Service**：`strategy_check()` 签名增加 `portfolio_type` 参数，传给 `list_etfs()`
5. **Model**：`StrategyCheckRecord` 增加 `portfolio_type` 列

---

### #3 历史方案显示原始代码

**现象**：策略检查历史显示 `range_bound` 而非中文"震荡"；组合生成历史硬编码"3 套方案"而非实际风格标签。

**根因**：纯前端渲染缺陷——后端已返回所需数据但前端未正确映射。

#### 代码证据

```html
<!-- DashboardAiTools.vue:54 — 硬编码 -->
<span v-if="h._type === 'design'" class="history-style">3 套方案</span>

<!-- DashboardAiTools.vue:55 — 原始 regime 代码 -->
<span v-if="h._type === 'check'" class="history-style">{{ h.market_regime || '—' }}</span>
```

而同一文件中 line 761-768 存在已定义的映射函数却未被引用：

```javascript
function regimeLabel(regime) {
  const labels = {
    bull_strong: '强牛市',
    bull_weakening: '牛市趋弱',
    range_bound: '震荡',
    correction: '回调',
    bear: '熊市',
    defensive_rotate: '防御轮动',
    panic: '恐慌',
  }
  return labels[regime] || regime || '未知'
}
```

#### 修复方案

2 行修改：

| 行 | 当前代码 | 改为 |
|---|---------|------|
| 54 | `3 套方案` | 使用 `riskProfileLabel(h.risk_profile)` 或动态方案数 |
| 55 | `{{ h.market_regime || '—' }}` | `{{ regimeLabel(h.market_regime) }}` |

---

### #5 自选标的：无搜索补全，添加无反馈

**现象**：自选标的输入框无搜索/自动补全，用户需手动输入完整代码；点击添加后弹窗关闭但无视觉反馈。

**根因**：

1. **搜索/补全缺失**：`marketApi.search(keyword)` 已在 API 层定义 (`GET /market/search`)，但 `MarketAnalysis.vue` 的自选输入框仅实现 `v-model` 双向绑定，未绑定 `@input` 事件调用搜索接口，未实现下拉建议列表。

```html
<!-- MarketAnalysis.vue:91 -->
<AppInput
  id="wl-symbol"
  v-model="watchlistForm.symbol"
  placeholder="如: 510050, 000001"
  @keydown.enter="addWatchlist"
  <!-- 缺少 @input="searchSymbols" -->
/>
```

2. **添加后无反馈**：`addWatchlist()` 函数调用成功后仅关闭弹窗和重置表单，无 toast 提示或列表高亮动画。

```javascript
// MarketAnalysis.vue:799-806
async function addWatchlist() {
  // ...
  await addWatchlist(watchlistForm.value.symbol, ...)
  showAddWatchlist.value = false                      // 关闭弹窗
  watchlistForm.value = { symbol: '', ... }           // 重置表单
  await fetchWatchlist()                              // 刷新列表
  // ← 缺少成功 toast / 列表闪烁 / 新条目高亮
}
```

#### 修复方案

1. 输入框绑定 `@input`（带 300ms debounce）调用 `marketApi.search()` 
2. 搜索结果显示在下拉浮层（类似 combobox），支持键盘选择
3. 添加成功后：`toast.show('添加成功', 'success')` + 列表自动滚动到新条目

---

### #7 板块分析：prompt 冲突，概念不全

**现象**：
- 板块分析有 AI 开场白，排版不佳，Markdown `#` 符号直接显示
- 概念板块覆盖不全（光模块、CPO、半导体设备等热门概念缺失）
- 分析逻辑不顺畅

**根因**（3 个独立问题）：

#### 问题 A：Prompt 角色冲突

`registry.py` 将 `sector_analysis` agent 配置为使用 `general_analyst.md`：

```python
# registry.py:65
("sector_analysis", AgentConfig(prompt_file="general_analyst.md", ...))
```

该系统提示词开头为：
```
你是专业的 ETF 投资组合策略分析师...
不得推荐具体个股
```

但板块分析端点要求 LLM 输出"核心标的推荐（3-5 只）"——直接违反系统约束。LLM 要么被迫违反指令，要么输出 ETF 组合建议而非板块分析。

#### 问题 B：概念板块覆盖不全

```python
# sector_fetcher.py:178-186
def fetch_concept_sectors(limit: int = 80):
    rows = _cached("concept_sectors",
        lambda: _try_two("concept_lv", lv.sector_em("concept"),
                         "concept_ak", _ak_concept_sectors))
    return rows[:limit]
```

数据来源于东方财富（levistock/akshare），覆盖度完全取决于外部 API。光模块、CPO、半导体设备等热门概念可能不在返回列表中。

#### 问题 C：Markdown 渲染

```html
<!-- MarketAnalysis.vue:329 -->
<div class="report-content" v-html="renderMarkdown(sectorReport)"></div>
```

如果 `renderMarkdown()` 实现不完整或未正确 parse `#` 标题标记，原生 Markdown 符号会显示在页面上。

#### 修复方案

| 问题 | 方案 |
|------|------|
| A | 创建独立 `sector_analyst.md` prompt（行业分析师角色，允许推荐个股） |
| B | 验证 `lv.sector_em("concept")` 实际返回；补充第二数据源 |
| C | 检查 `renderMarkdown()` 实现，确保正确处理 `#` 标题 |

---

### #8 个股分析：角色错配 + 缺 LLM 调用

**现象**：选择个股（如"寒武纪"）做分析，操作建议却是对 ETF 和组合的。

**根因**：双重 Bug。

#### Bug 1：Prompt 角色冲突（同 #7）

`symbol_analysis` agent 也使用 `general_analyst.md`，"ETF 组合策略分析师"角色禁止推荐个股。

#### Bug 2（更严重）：核心 LLM 调用缺失

```python
# analysis/llm.py:668-711
async def generate_symbol_analysis(symbol, name, asset_type,
                                    realtime, history, indicators, news):
    display_name = name or symbol
    prompt = f"""
深度分析标的 {display_name} ({symbol})：
实时行情：{json.dumps(realtime, ...)}
技术指标：{json.dumps(indicators, ...)}
资讯催化：{json.dumps(news[:10], ...)}

请输出：基本面概览、技术面分析、资讯催化、风险提示、操作建议
"""
    # ← 缺少 return await get_agent("symbol_analysis").run(prompt)
    # 函数隐式返回 None！
```

`generate_symbol_analysis` 构建了完整的 prompt 却 **没有调用 LLM**。任意调用它的非流式端点都会收到 `None`。

流式端点 `symbol-analysis/stream` 绕过此函数，自己构建 inline prompt 直接调 agent，所以流式可用（观察正确）。

#### 修复方案

```python
# llm.py:711 — 添加这一行
return await get_agent("symbol_analysis").run(prompt)
```

并创建独立的 `symbol_analyst.md` prompt（个股分析师角色）。

---

### #9 资讯重要性分级不合理

**现象**：如"证监会召开投资者座谈会听取意见建议"被标记为"一般"（level 1）。

**根因**：关键词匹配模型的层级设计缺陷。

```python
# levistock_fetcher.py:92-102
def classify_news_level(title: str) -> int:
    t = (title or "").lower()
    for level in (5, 4, 3, 2):        # 从高到低匹配
        if any(k in t for k in _LEVEL_KEYWORDS[level]):
            return level
    return 1                           # 都不匹配 → level 1 "一般"
```

当前 keyword 分布：

| Level | 标签 | 示例关键字 |
|-------|------|----------|
| 5 | 重大/紧急 | 崩盘、熔断、退市、战争 |
| 4 | 利好/重要正面 | 降准、降息、大涨、飙升 |
| 3 | 利空/重要负面 | 暴跌、利空、违规、加息 |
| 2 | 提醒/关注 | 证监会、召开、会议、公告 |
| **1** | **一般** | **（无匹配）** |

"证监会召开投资者座谈会"中的"证监会"和"召开"匹配 level-2，被归为"提醒/关注"。但从政策信号角度看，此类事件对市场的影响可能达到 level 3-4。

**此外**：`_LEVEL_KEYWORDS.contains("证监会")` 的检查在 title 小写化后执行。Chinese 字符的 `.lower()` 不变，所以"证监会"能正确匹配。问题不在于匹配失败，而在于 **权重赋值不合理**：重大政策信号类事件应分配到更高 level。

#### 修复方案

1. 在 level-4 和 level-3 增加政策信号关键词
2. 或引入 `NewsLLMAnalyzer` (text_pipeline_b.py) 进行语义级重要性分类作为修正
3. 或采用混合策略：关键词初筛 + LLM 二次评估

---

### #11 信号全是持有 / 评分 0

**现象**：个股和 ETF 的"综合信号"永远显示"持有"，评分始终为 0。

**根因**：数据获取链路静默失败 → 指标为空 → 信号退化为默认值。

#### 调用链

```
GET /market/signal/{symbol}
  → get_history(symbol, asset_type, "daily")     ← 可能返回 []
    → compute_all_indicators([])
      → if not df: return {}                      ← 返回空字典
        → generate_signal({})
          → if not indicators:
              return {"signal": "hold", "score": 0, "reason": "insufficient_data"}
```

底层 fetcher 遇到异常时静默返回空，不抛异常也不写日志：

```python
# china_market.py:112-134
def _mootdx_history(...):
    try:
        df = api.get_k_data(...)
    except Exception:
        return []       # ← 静默吞错
```

```python
# market_service.py:37
def _call(fn, ...):
    try:
        return fn()
    except (Exception, asyncio.CancelledError):
        return None     # ← 静默吞错
```

#### 额外问题：评分刻度错位

前端显示 `signal.score / 100`（作为百分比），但后端 score 是加权和：

| 信号 | 权重 |
|------|------|
| RSI 超卖 (rsi<30) | +2 |
| 九转买入序列 9 | +1.5 |
| MACD 金叉 | +1 |
| ... | |

最大理论值约 7.5，显示为 "3.5 / 100" 非常反直觉。

#### 修复方案

1. 在 fetcher 异常处增加 `logger.warning()`
2. 增加数据健康检查和降级重试
3. 前端 `signal.score / 100` → 改为 `signal.score` 直接显示，或归一化到 0-100 区间

---

### #12 持仓数据为 0 + 白屏

**现象**：组合持仓页面上，除"成本价"外其他数据都是 0；停留一会儿页面白屏。

**根因**：多个子问题叠加。

#### 数据为 0

`PortfolioAnalysis.vue` 是薄封装层，持仓由 `PortfolioManager.vue` 渲染。数据来自 `portfolioApi.calculate()` 和 `portfolioApi.dailyPnl()`。

- 后端 `calculate_allocation()` 依赖实时行情 → 行情数据为空 → 计算出 0
- `dailyPnl()` 同样依赖行情 → 无数据 → 0
- "成本价"是用户在创建 ETF 条目时输入的持久化字段，不依赖行情 → 能显示

#### 白屏

可能原因（需要进一步定位验证）：
1. `PortfolioManager.vue` 在 `onMounted` 中调用某 API 方法不存在，或 watch 某个未初始化的 ref
2. `AnalysisView.vue` 在加载 K 线或信号时触发未捕获的异常
3. Vue 渲染循环中某个子组件的 `computed` 返回 `undefined`，模板中又访问了嵌套属性

#### 修复方案

1. 追踪 `PortfolioManager.vue` 中数据渲染依赖的 API 调用链
2. 在 `app.config.errorHandler` 中记录完整的组件栈（已有但可能不够详细）
3. 在数据渲染前增加空值/边界检查
4. 对行情不可用时给出明确提示而非显示 0
5. 技术分析区域：增加 AI 智能分析功能（调用 symbol_analysis 流式端点）

---

## P2 — 体验优化 / 架构建议

### #10 资讯数据源单一

**现象**：呈现的资讯只来自财联社和 RSS，覆盖面窄。

**根因**：`news_fetcher.py` 实际使用的源

```python
def fetch_news_headlines():
    items += fetch_cailian_telegraph(15)   # 财联社快讯 ← 主源
    items += fetch_macro_news()            # CCTV + 百度宏观
    items += fetch_global_news()           # 2 个 RSS (MarketWatch, CNBC)

def fetch_macro_news():
    items += ak.news_cctv()               # CCTV
    items += ak.news_economic_baidu()     # 百度宏观
    items += ak.news_economic_cls()       # 东方财富宏观（= 财联社）

def fetch_global_news():
    feeds = [
        "https://feeds.content.dowjones.io/...",   # MarketWatch
        "https://www.cnbc.com/id/100003114/...",    # CNBC
    ]
```

共 4 个实质来源，且有重叠（东方财富宏观 news_economic_cls 也是财联社内容）。

**建议新增源**：

| 来源 | akshare 接口 | 类型 |
|------|-------------|------|
| 东方财富个股资讯 | `ak.stock_news_em()` | A 股个股 |
| 新浪财经 | `ak.stock_info_global_cls()` | 全球/宏观 |
| 华尔街见闻 | RSS 或爬虫 | 宏观 |
| 36kr | RSS | 科技/创投 |
| 雪球 | RSS 或 API | 社区讨论 |

---

### #13 K 线滚轮缩放体验差

**现象**：在 K 线图上滚动滚轮 → 缩放图表；用户想滚轮翻页却无法实现。

**根因**：ECharts `inside` dataZoom 默认拦截所有滚轮事件用于缩放。

```javascript
// AnalysisView.vue:476-493
dataZoom: [
  {
    type: 'inside',
    zoomOnMouseWheel: true,      // ← 滚轮缩放，阻止页面滚动
    moveOnMouseMove: true,
  },
  { type: 'slider', ... }       // ← 滑块缩放仍保留
]
```

`MarketAnalysis.vue:1349-1352` 同样配置。

#### 修复方案

```javascript
// 方案 A：滚轮平移 + 滑块缩放
dataZoom: [
  {
    type: 'inside',
    zoomOnMouseWheel: false,     // 关闭滚轮缩放
    moveOnMouseWheel: true,      // 滚轮变为左右平移
    moveOnMouseMove: true,
  },
  { type: 'slider', ... }       // 滑块仍可缩放
]

// 方案 B：Ctrl+滚轮缩放，普通滚轮翻页
// 需要监听 keydown 事件动态切换配置
```

---

### #15 Token 监控页面的合理性与改进

**分析结论**：高度合理，且后端已完整实现。

#### 当前能力

`TokenUsageStore` 已跟踪以下数据并持久化到 SQLite：

```
UsageRecord:
  - function_name    // 功能名称（llm_report, generate_advice 等）
  - prompt_tokens    // 输入 token 数
  - completion_tokens // 输出 token 数
  - total_tokens     // 总数
  - model            // DeepSeek 模型名
  - provider         // 供应商
  - success          // 是否成功
  - duration_ms      // 耗时
  - error_message    // 错误信息
```

前端 `TokenMonitor.vue` 已实现：
- 概览统计（总 token、成功/失败次数、错误率）
- ECharts 时间序列趋势图（按日/时/月粒度切换）
- 按功能细分的用量排行表
- 最近失败记录列表

#### 建议改进

1. **费用计算**：添加定价表将 token → 实际费用
   ```javascript
   const PRICING = {
     'deepseek-chat': { input: 0.0005, output: 0.002 },    // ¥/1K tokens
     'deepseek-reasoner': { input: 0.001, output: 0.004 },
   }
   ```
2. **告警阈值**：当日费用超过 N 元时通知用户
3. **按功能优化建议**：识别调用次数最多的功能，建议降低频率

---

### #16 行情分析分市场板块的可行性与建议

**分析结论**：技术上完全可行，后端已具备强市场感知基础设施。

#### 后端现有能力

| 能力 | 位置 | 描述 |
|------|------|------|
| `market` 字段 | `models/search.py:Instrument` | 存储 'A'/'HK'/'US'/'gold' |
| `asset_type` 字段 | `models/search.py:Watchlist` | 存储 'A'/'HK'/'US' |
| 区域指数分组 | `market_service.py:_GLOBAL_INDEX_DEFS` | A 5 个 / HK 3 个 / US 3 个 |
| 独立 TTL | `market_service.py:_QUOTE_TTL` | A / HK / US / index 各自独立 |
| 路由逻辑 | `market_service.py:get_realtime_batch()` | 按 asset_type 分发到不同 fetcher |
| US 级联 | `market_service.py:_route_us()` | Twelve Data → Finnhub → Alpha Vantage → yfinance |

#### 建议方案

将 `MarketAnalysis.vue`（1703 行）按市场拆分为标签页结构：

```
┌─────────────────────────────────────┐
│ [A股] [港股] [美股] [全球]          │
├─────────────────────────────────────┤
│ 板块分析 │ 标的分析 │ 指数行情     │
│ （该市场专属的板块/个股分析）      │
└─────────────────────────────────────┘
```

**关键注意事项**：
- 交易时段差异：A 股 09:30-15:00、港股 09:30-16:00、美股 09:30-16:00 ET
- 非交易时段显示"上次更新"时间戳
- 先拆分子组件（`MarketOverview.vue`、`SectorAnalysis.vue`、`SymbolAnalysis.vue`）再添加 Tab 包装

---

### #17 全局 UI 与样式优化

**分析**：全栈视觉改进需求，归为 4 个方面

#### 1. 组件体积过大

| 组件 | 行数 | 问题 |
|------|------|------|
| `MarketAnalysis.vue` | 1703 | 包含 6 个独立功能区域 |
| `Dashboard.vue` | 1231 | 含组合摘要、盈亏、持仓列表等 |
| `DashboardAiTools.vue` | 2127 | 含向导/加载/结果/历史/策略检查 5 个面板 |

**建议**：按功能拆分为独立子组件，每个 ≤400 行。

#### 2. CSS 变量系统不完整

`theme.css` 已定义基础色但缺少完整设计系统：

```css
/* 已有 */
:root {
  --color-bg: #f8f9fa;
  --color-up: #e74c3c;     /* 红涨 */
  --color-down: #27ae60;   /* 绿跌 */
}

/* 建议补充 */
:root {
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-card: 0 2px 8px rgba(0,0,0,0.08);
  --shadow-modal: 0 4px 24px rgba(0,0,0,0.12);
  --font-mono: 'SF Mono', 'Cascadia Code', monospace;
  --transition: 0.2s ease;
}
```

#### 3. 信息层级

- 使用骨架屏（skeleton）替代 loading 文字
- 卡片标题/数值/辅助文字使用不同的字号和字重
- 关键数据（涨跌幅、盈亏）使用醒目的颜色和大小

#### 4. 移动端适配

- 当前卡片/表格在窄屏下会溢出
- 建议采用 `min-width: 320px` 断点 + `grid/auto-fill` 响应式布局

---

## 优先级总表

| Pri | # | 问题 | 根因类型 | 修复工作量 | 关联文件 |
|-----|---|------|---------|-----------|---------|
| **P0** | 6 | AI 顾问 `analysisApi` 未定义 | 缺少 import | **极低** (1行) | `MarketAnalysis.vue` |
| **P0** | 4 | 市场研判流式端点调用已删函数 | 重构遗漏 | 低 | `analysis.py` |
| **P0** | 14 | Dashboard 数据不渲染 | 引用错误 + 未定义函数 | 低 | `Dashboard.vue`, `GlobalIndicesStrip.vue` |
| **P0** | 1 | 组合设计通知失败/无记录 | design_id 回传断路 | 中 | `task_manager.py`, `portfolio.py`, `DashboardAiTools.vue` |
| **P1** | 3 | 历史显示原始代码 | 前端映射缺失 | **极低** (2行) | `DashboardAiTools.vue` |
| **P1** | 8 | 个股分析缺 LLM 调用 | 缺少 return 语句 | **极低** (1行) | `llm.py` |
| **P1** | 5 | 自选无搜索补全 | 功能未实现 | 中 | `MarketAnalysis.vue` |
| **P1** | 2 | 策略检查未区分组合类型 | 参数传递缺失 | 中 | 全链路 5 个文件 |
| **P1** | 7 | 板块分析 prompt 冲突 | 角色错配 | 低 | `registry.py`, 新建 prompt 文件 |
| **P1** | 11 | 信号全是持有/0 分 | 数据静默失败 | 中 | `china_market.py`, `market_service.py` |
| **P1** | 12 | 持仓数据 0 + 白屏 | 行情数据 + 渲染异常 | 中高 | `PortfolioManager.vue`, `AnalysisView.vue` |
| **P2** | 13 | K 线滚轮缩放冲突 | 配置不当 | **极低** | `AnalysisView.vue`, `MarketAnalysis.vue` |
| **P2** | 9 | 资讯分级不合理 | 关键词权重缺陷 | 低 | `levistock_fetcher.py` |
| **P2** | 10 | 资讯源单一 | 数据源集成 | 中 | `news_fetcher.py` |
| **P2** | 15 | Token 监控改进 | 功能增强 | 低 | `TokenMonitor.vue` |
| **P2** | 16 | 行情分市场 Tab | 架构优化 | 高 | `MarketAnalysis.vue` (拆分) |
| **P2** | 17 | 全局 UI 优化 | 视觉/布局 | 高 | 全部页面 |

---

## 一键修复清单（推荐首批执行）

按 **最小工作量、最大收益** 排序：

| # | 操作 | 文件 | 行数改动 |
|---|------|------|---------|
| 6 | 添加 `import { analysisApi } from '@/api'` | `MarketAnalysis.vue` | +1 |
| 3 | 历史显示调用 `regimeLabel()` | `DashboardAiTools.vue` | 2 |
| 8 | 补上 `return await get_agent("symbol_analysis").run(prompt)` | `llm.py` | +1 |
| 13 | 关闭 `zoomOnMouseWheel`，开启 `moveOnMouseWheel` | 两处 K 线配置 | 4 |
| 4 | 流式端点对齐非流式的数据采集 | `analysis.py` | ~30 |
| 14 | Dashboard 声明缺失变量 + 修 API 调用 | `Dashboard.vue` + `GlobalIndicesStrip.vue` | ~15 |
| 1 | 全链路打通 design_id | 3 个文件 | ~20 |
