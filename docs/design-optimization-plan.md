# ETF Surge 智能组合设计链路 — 优化方案

> 版本: v1.1 | 日期: 2026-07-18 | 基于完整代码审查 + 实时行情验证

---

## 一、当前架构全景

```
Frontend (DashboardAiTools.vue)
  │  POST /portfolio/design-async 或 /portfolio/design
  ▼
Router (portfolio.py)
  │  generate_full_design() → generate_enhanced_design()
  ▼
strategy_design.py::generate_enhanced_design()
  ├── 并行拉取: trends + macro + sentiment + benchmark + news + fund_flow + valuation
  ├── detect_market_regime(trends, "000001")  ← ⚠️ P0 Bug
  ├── dynamic_layer_budget(risk_profile, regime)
  ├── dynamic_core_allocation(regime)
  ├── dynamic_defense_allocation(regime)
  ├── pool_manager → satellite scoring
  ├── build_rationale() for each holding
  └── 返回 {strategies, market_context}
       │
       ▼
Router → compose_and_push_report(session_id, strategies, market_sentiment, benchmark_stocks)
       │         ↑ 仅传了 2 个字段 ← ⚠️ P1 Gap
       ▼
llm.py::generate_design_report()
  │  _build_design_report_prompt(strategies, market_sentiment, benchmark_stocks)
  │         ↑ 仅用了 3 类数据 ← ⚠️ P1 Gap
  │  agent("symbol_analysis").run(prompt, system_override=design_report.md)
  ▼
Frontend WS: /ws/design-report/{session_id} → 展示"完整报告" Tab
```

---

## 二、问题根因分析

### P0 — 致命 Bug：`detect_market_regime` 永远返回默认值

**位置**：`strategy_design.py` 第 864-869 行

```python
regime = detect_market_regime(
    trends=trend_data,         # key 是 ETF 代码: "510300", "518880", ...
    broad_index_code="000001", # ← 上证指数, 不在 trend_data 中!
    sentiment_index=sentiment_index,
    adv_ratio=adv_ratio,
)
```

**问题链**：

1. `compute_etf_trends(all_symbols)` 中 `all_symbols = list(CANDIDATE_POOL.keys())`，只有 ETF 代码（`510300`, `560600`, `518880` 等），**没有 `"000001"`**
2. `detect_market_regime` 内 `index_trend = trends.get("000001", {})` → `{}`
3. 所有趋势判断全部失效：`ret_1m=0.0`, `ret_3m=0.0`, `ma_bias_20=0.0`
4. 唯一能触发的路径是纯情绪判断（`sentiment_index < 20` → panic），但当情绪为 50（中性）时，**永远回退到默认 `"range_bound"`**

**影响**：
- 即使深证成指单日暴跌 5.4%，regime 仍判为「震荡」
- `dynamic_layer_budget` 不加防御 → 防御层永远是 5%
- `dynamic_core_allocation` 走震荡分支 → 核心永远是中性配置
- LLM 报告引用 regime → 「市场震荡；市场情绪中性」

**修复**：将 `broad_index_code` 改为 `"510300"`（沪深300ETF，约等于大盘走势，在 trend_data 中）。**一行代码修复，零副作用**。

---

### P0.5 — 趋势数据本身的可用性问题（P0 修复的补充）

**发现场景**：P0 修复后验证时，`regime` 仍返回 `"range_bound"`。

**原因**：P0 将 key 改对后（`510300` 在 trend_data 中），但 `compute_etf_trends` 依赖 akshare 拉取历史日线，**当 akshare 超时/断连时**，返回的 `trend_data["510300"]` 仍是 `{}`。`detect_market_regime` 在函数签名中**没有接收 `index_realtime` 的选项**，即使 `fetch_index_realtime()` 成功返回了深证成指 -5.40% 的数据，也无法作为 fallback。

**影响**：外部数据源不稳定时，P0 修复正确但无效。

**修复**：
1. `detect_market_regime` 增加 `index_realtime` 可选参数
2. 函数尾部（当前行 164 `return regime` 之前）添加 fallback: 若 `regime == "range_bound"` 且 `index_realtime` 非空，用当日涨跌幅判定:
   - 某主要指数当日 < -5% → `"correction"`
   - 某主要指数 -3% ~ -5% 且情绪 < 50 → `"defensive_rotate"`
   - 某主要指数 > +3% 且情绪 > 60 → `"bull_weakening"`
3. 调用处（`strategy_design.py`）传 `index_realtime=index_realtime`

**改动的文件**：`market_trends.py`（~15 行）+ `strategy_design.py`（1 行参数）

---

### P1 — 数据断层：LLM 报告 prompt 缺乏实时行情

**位置**：`llm.py` 第 986-1027 行（`_build_design_report_prompt`）

LLM 报告生成时只收到三类数据：

| 数据类型 | 传给 LLM？ | 来源 |
|---------|:---------:|------|
| `sentiment_index` / `sentiment_label` | ✅ | market_sentiment |
| `benchmark_stocks`（最多 5 只） | ✅ | benchmark_stocks |
| strategies（含 selection_rationale） | ✅ | 策略引擎输出 |
| **实时指数行情**（涨跌幅、点位） | ❌ | `fetch_index_realtime()` 有数据但未传 |
| **market_regime**（correction/bear 等） | ❌ | 引擎计算了但 `compose_and_push_report` 没收 |
| **sector_momentum**（行业排名） | ❌ | 引擎计算了但未传 |
| **macro_regime**（宏观状态） | ❌ | 引擎计算了但未传 |
| **ETF 当日涨跌幅** | ❌ | build_rationale 里没写 |

**根因二重奏**：

1. **`compose_and_push_report` 参数缺口**（`design_report.py` 第 62-94 行）—— 只接受 `market_sentiment` 和 `benchmark_stocks`
2. **`_build_design_report_prompt` 输入狭窄**（`llm.py` 第 986-1027 行）—— 只把收到的 2 个字段写进 prompt

---

### P2 — `generate_full_design` 丢弃增强型 context

**位置**：`strategy_design.py` 第 296-346 行

`generate_full_design` 内部调用 `generate_enhanced_design()`（后者返回完整的 `market_context`），但随后用自己的简版数据覆盖了结果：

```python
return {
    "strategies": strategies,
    "market_context": {          # ← 完全丢弃了 enhanced 的 market_context
        "market_sentiment": sentiment,
        "benchmark_stocks": benchmark,
    },
}
```

---

### P3 — `build_rationale` 模板化严重

**位置**：`strategy_design.py` 第 637-772 行

入选理由不包含**当日涨跌幅**，导致所有 ETF 的理由模式化重复。当日涨跌幅数据在 `_fetch_single_trend` 中不存在（只有 return_5d/1m/3m），需单独注入。

---

## 三、优化方案

### P0 修复（1 行）

**文件**：`backend/app/services/strategy_design.py`   **位置**：第 866 行

```
- broad_index_code="000001",
+ broad_index_code="510300",  # 沪深300ETF — 在 trend_data 中存在
```

### P1 优化（~60 行，5 个文件）

| 文件 | 改动 |
|------|------|
| `design_report.py` | `compose_and_push_report` 签名改为接收完整 `market_context` |
| `llm.py` | `_build_design_report_prompt` 新增「市场行情快照」「行业板块动量」章节 |
| `design_report.md` | 系统 prompt 新增规则 2.1（实时行情优先引用）+ 重构第一章 |
| `portfolio.py` | 调用点传完整 `market_context` |
| `strategy_design.py` | `generate_enhanced_design` 数据拉取阶段新增 `fetch_index_realtime()`，将指数行情并入 `market_context` |

**P1 必要补充（已核对代码，方案原文遗漏此步）**：

`generate_enhanced_design`（`strategy_design.py:809` 的 `asyncio.gather`）当前**并未调用** `fetch_index_realtime()`（`backend/app/fetchers/china_market.py:379` 已实现，返回 `000001/399001/399006/000300/…` 含 `change_pct` / `price`）。若只改 `design_report.py` / `llm.py` 的 prompt 而不在引擎内把指数行情放进 `market_context`，报告 prompt 仍将拿不到「市场行情快照」所需数据（P1 表里的 `fetch_index_realtime` 有数据但未传是事实，但引擎本身没拉）。

**做法**：在 `generate_enhanced_design` 第一步并行采集里加一项：

```python
from ..fetchers.china_market import fetch_index_realtime
index_realtime = await asyncio.wait_for(
    asyncio.to_thread(fetch_index_realtime), timeout=15
)
```

并在函数末尾 `return` 的 `market_context` 中加入：

```python
"index_realtime": index_realtime or [],
```

随后 `portfolio.py:214` 调用 `compose_and_push_report` 时整包 `market_context` 透传，`llm.py` 的 `_build_design_report_prompt` 即可消费 `index_realtime` 渲染「市场行情快照」。

### P2 优化（~10 行，1 个文件）

**文件**：`strategy_design.py` — `generate_full_design`

合并 enhanced 的 `market_context` 与独立拉取的 sentiment/benchmark，使用 `**enhanced_ctx` 展开。

### P3 优化（~25 行，2 个文件）

**文件**：`strategy_design.py` — `build_rationale`（+ `market_trends.py` 补数据）

**P3 数据来源修正（已核对代码）**：

方案原文写「新增 `fetch_a_stock_batch(all_symbols)` 获取当日涨跌幅」，**不可行**——`fetch_a_stock_batch`（`china_market.py:280`）面向 **A 股股票代码**，而 `CANDIDATE_POOL` 的 key 全是 **ETF 代码**（510300/560600/518880…）。mootdx/腾讯/新浪对基金代码的实时行情口径不同，`fetch_a_stock_batch` 传入 ETF 代码大概率返回空，拿不到「今日涨跌幅」。

**正确做法**：当日涨跌幅目前 `trend_data` 中确实不存在（`compute_etf_trends` / `_fetch_single_trend` 只产出 `return_5d/1m/3m` + 均线乖离，见 `market_trends.py:34-42`）。在 `market_trends.py` 的 `_fetch_single_trend` 中补算 `change_pct`（最新一日 `close` 与前一日 `close` 之比），并入 `compute_etf_trends` 返回结构：

```python
# _fetch_single_trend 内，取最近两行收盘价
if len(df) >= 2:
    last_close = float(df.iloc[-1]["收盘"])
    prev_close = float(df.iloc[-2]["收盘"])
    change_pct = (last_close - prev_close) / prev_close if prev_close else 0.0
else:
    change_pct = 0.0
res["change_pct"] = round(change_pct, 4)
```

`generate_enhanced_design` 已把 `trend_data` 透传给 `build_rationale`（`strategy_design.py:933` 等），无需再额外拉取。

**`build_rationale` 改动**：在走势段（原第 2 节，约 `strategy_design.py:682`）**之前**新增「当日涨跌」节：

```python
# 0. 当日涨跌（若有）
chg = trend.get("change_pct")
if chg is not None:
    d = "涨" if chg >= 0 else "跌"
    parts.append("今日" + d + str(round(abs(chg) * 100, 1)) + "%")
```

> 注：`compute_etf_trends` 内部对失败标的回退 `{}`（`market_trends.py:60`），`change_pct` 缺失时该节自动跳过，不影响其他维度。

## 四、前端任务感知优化（方案 A + B）

### 4.1 当前痛点

用户点击「开始设计」后的流程：

```
点击开始 → loading 界面（轮询 3s × 60 次）→ 完成 → 结果页
```

**三个盲区**：

| 场景 | 问题 |
|------|------|
| Loading 期间用户切换到其他 Tab | loading 界面不可见，轮询仍在跑，用户不知道何时完成 |
| 用户关闭设计面板再打开 | 回到 wizard 初始页面，看不见运行中的任务 |
| 任务完成后用户不在设计面板 | 没有任何通知 |

### 4.2 已有基础设施（免开发）

审查发现以下组件**已经就绪**：

| 组件 | 路径 | 状态 |
|------|------|:----:|
| WS 端点 `/api/v1/ws/task-notifications` | `backend/app/routers/ws.py:104` | ✅ 已实现 |
| `notify_manager` 广播 | `backend/app/tasks/design_tasks.py` | ✅ `_notify` 广播 `task_update` 消息 |
| `toast` Store | `frontend/src/stores/toast.js` | ✅ 已有通知机制 |
| `loading` Store | `frontend/src/stores/loading.js` | ✅ 可复用模式 |
| Pinia 已集成 | `frontend/src/main.js` | ✅ `app.use(createPinia())` |

缺少的只是前端**全局 WS 连接 + 全局任务状态 store + 导航栏指示器**。

**⚠️ 已核对代码的事实修正**：

1. `task_update` 广播体（`design_tasks.py:172-179` 的 `_notify`）**只含 `{type, task_id, status, progress}`，不含 `design_id`**。而前端 `startDesign` 完成后需 `design_id` 拉方案详情（`DashboardAiTools.vue:657-659`）。因此收到 `completed` 事件后**必须再调一次 `getTask(taskId)`**（`portfolio.py` 的 `/portfolio/tasks/{taskId}` 后端在 `mgr.update_task(..., design_id=...)` 时已把 `design_id` 存入 task 状态，`getTask` 响应可返回），才能拿到 `design_id` 拉详情。方案 B 4.4 第 5 步「收到 completed 后获取详情」已覆盖此步，此处明确依赖 `getTask` 而非 WS 消息体携带 `design_id`。
2. `designWsConnect(designId)`（`DashboardAiTools.vue:719`）**已存在**，连接 `/ws/design-report/{session_id}` 推送 LLM 流式报告。方案 B 是**新增**一条全局 `/ws/task-notifications` 连接来驱动「任务完成」事件，两条 WS **并存、互不冲突**，不要误删已有的 design-report WS。

### 4.3 方案 A：全局任务指示器

**新增 `frontend/src/stores/task.js`**（~50 行）

```javascript
// 遵循现有 Pinia store 模式（defineStore + ref）
// 维护 runningTasks: [
//   { taskId, type: 'design', status: 'running'|'completed'|'failed',
//     progress: 45, label: '智能组合设计', designId: null, createdAt }
// ]
// 方法: addTask(taskId), updateTask(taskId, changes), removeTask(taskId),
//       getTask(taskId), clearCompleted(delay=30s)
```

状态变化自动触发 `toast.show()`：

- `running` → 无（首次加入时显示 taskId）
- `completed` → toast「组合方案已生成，点击查看」
- `failed` → toast「组合方案生成失败」

**新增 `frontend/src/components/TaskIndicator.vue`**（~80 行）

```
在导航栏显示：
  📋 1  → 运行中任务数（仅 >0 时显示）
  点击展开下拉面板：
    ┌─────────────────────────┐
    │ ▸ 智能组合设计  ░░░ 45% │
    │ ▸ 智能组合设计  ✅ 完成 │
    └─────────────────────────┘
```

- 任务完成后保留 30 秒自动清除
- 点击已完成的任务跳转设计结果页
- 仅在有 running/completed 任务时显示小铃铛

**修改 `frontend/src/App.vue`**（~8 行）

在第 31-35 行 `nav-status` 旁插入：

```html
<!-- 在第 31 行 nav-status 前或后插入 -->
<TaskIndicator />
```

### 4.4 方案 B：WS 任务通知（取代轮询）

**在 `App.vue` 建立持久 WS 连接**（`onMounted` / `setup` 中）

```javascript
// 连接到 /api/v1/ws/task-notifications
// 收到 { type: 'task_update', task_id, status, progress }
// → 更新 taskStore
// → status='completed' 时 toast 通知
// 自动重连（onerror 后 3s 重试）
```

**修改 `DashboardAiTools.vue` `startDesign()`**（~20 行）

```
去掉 3s 轮询循环（第 645-710 行），改为：
1. POST /portfolio/design-async → task_id
2. taskStore.addTask(task_id, '智能组合设计')
3. 显示 loading 界面（但不再轮询）
4. 依赖全局 WS 广播的 task_update 事件驱动
5. 收到 completed 后获取详情 + 切换结果页
```

**兼容性**：WS 连接失败时回退为 `setTimeout` 单次查询任务状态，保持不丢任务。

### 4.5 数据流对比

| | 修复前（轮询） | 修复后（事件驱动） |
|--|:------------:|:----------------:|
| 请求量 | 最多 60 次 HTTP GET | 0 次（WS 单连接） |
| 实时性 | 3s 延迟 | 实时 |
| 跨 Tab 可见性 | 不可见 | 导航栏铃铛可见 |
| 完成通知 | 无 | toast + 铃铛 |
| 前端断开后的韧性 | 丢失 | WS 重连后查一次状态 |

### 4.6 当前实现仍存在的 3 个 UX 问题

方案 A + B 代码已落地（`e54c1ff`），但前端流程仍有三个显性漏洞：

#### 漏洞 1：页面卡住 — 加载态无出路

**现象**：点击「开始设计」→ loading 界面显示 → 用户无法做任何其他操作。

**根因**：`startDesign()` 调用 `portfolioApi.designAsync()` 是 `await` 阻塞的。虽然 `designStep.value='loading'` 立即生效，但用户在加载期间：
- 点击导航链接时 `exitCoreFeature()` 销毁设计面板 → 回退到首页
- 无法查看 task 进度详情（loading 界面只有进度条和文字，没有「后台运行中，可切换到其他页面」的提示）

**修复**：
1. 加载界面增加提示文字「方案生成中，您可以切换到其他页面，完成后会通知您」
2. `exitCoreFeature()` 不销毁运行中的设计任务：保留 `taskStore` 中注册的 task，允许通过 TaskIndicator 重新进入

#### 漏洞 2：切换页面后无法回来查看进度和结果

**现象**：用户在加载/结果界面点击导航链接 → 回到 Dashboard → 再点「AI 工具」→ 回到初始 wizard 页面，看不到运行中的任务。

**根因**：
- `exitCoreFeature()` 设置 `designStep.value='wizard'`、`designResult.value=null`
- `DashboardAiTools.vue` 是 route 页面内的组件，导航出去后被 unmount → 返回时重新 mount → 所有 local state 丢失

**修复**：
1. **state 持久化**：将 `designStep`、`designResult`、`loadingProgress` 存入 Pinia store（`taskStore` 或新建 `designStore`），替代组件内 `ref`。导航出去再回来时恢复状态
2. **TaskIndicator → 快速回入**：点击 TaskIndicator 中的「查看」按钮 → 导航到包含设计面板的 route → 触发 `restoreDesignState()` 恢复上一次的设计状态

#### 漏洞 3：历史记录加载慢

**现象**：点击「历史记录」/「历史方案」→ 等 2-5 秒才显示列表。

**根因**：
- 后端 `GET /portfolio/designs` 用 `select(PortfolioDesign)` 全对象加载 → SQLAlchemy ORM 读取 `strategies_json` + `market_snapshot_json`（每个 ~50-200KB）
- 20 条记录 = 1-4MB 数据从 SQLite 读入内存 + JSON 反序列化

**修复**（后端）：
```python
from sqlalchemy.orm import load_only

stmt = (
    select(PortfolioDesign)
    .options(load_only(
        PortfolioDesign.id,
        PortfolioDesign.created_at,
        PortfolioDesign.capital,
        PortfolioDesign.risk_profile,
    ))
    .order_by(desc(PortfolioDesign.created_at))
    .offset(offset)
    .limit(limit)
)
```

**修复**（前端）：
- 列表加载期间显示 skeleton 占位动画
- 首次加载后缓存列表（`sessionStorage`），下次直接显示缓存 + 后台静默刷新

#### 漏洞 4：TaskIndicator 不可点击回设计面板

**现象**：导航栏铃铛显示任务数，但点击后无法回到设计生成页面。

**根因**：`TaskIndicator.vue` 未实现「点击已完成任务→跳转设计面板」的路由导航

**修复**：在 `TaskIndicator` 的已完成任务项上加 `@click` → `router.push({ name: 'portfolio-analysis', query: { restoreDesign: taskId } })`。`DashboardAiTools.vue` 在 `onMounted` 中检测 `$route.query.restoreDesign` → 调用 `restoreDesignState()`

---

## 五、改动清单

### 5.1 后端修复（P0/P1/P2/P3）

| 文件 | 改动类型 | 行数 | 优先级 |
|------|:-------:|:---:|:------:|
| `backend/app/services/strategy_design.py` | P0 修 Bug + P1 加指数行情 + P2 合并 context + P3 优化 rationale | ~40 | P0/P1/P2/P3 |
| `backend/app/services/market_trends.py` | `_fetch_single_trend` 补 `change_pct` | ~8 | P3 |
| `backend/app/analysis/llm.py` | 扩展 prompt 构建 | ~35 | P1 |
| `backend/app/tasks/design_report.py` | 扩展函数签名 | ~10 | P1 |
| `backend/app/analysis/prompts/v1/design_report.md` | 更新系统 prompt | ~15 | P1 |
| `backend/app/routers/portfolio.py` | 更新调用参数 | ~3 | P1 |

| `backend/app/routers/portfolio.py` | `GET /designs` 加 `load_only` 只查元数据，避免加载大 JSON 字段 | ~3 | UX3 |
| `backend/app/services/market_trends.py` | `detect_market_regime` 新增 `index_realtime` fallback 参数 | ~15 | **P0.5** |

**小计**：8 个后端文件，~130 行净改动。

### 5.2 前端任务感知（方案 A + B）

| 文件 | 改动类型 | 行数 |
|------|:-------:|:----:|
| `frontend/src/stores/task.js` | **新建** | ~50 |
| `frontend/src/components/TaskIndicator.vue` | **新建** | ~80 |
| `frontend/src/App.vue` | 修改 | ~25（引入 store + WS 连接 + 插入组件） |
| `frontend/src/components/DashboardAiTools.vue` | 修改 | ~25（去掉轮询改用 WS） |

| `frontend/src/stores/task.js` | **已有**，UX2 需加 `persistDesignState` 方法 | +20 |
| `frontend/src/components/TaskIndicator.vue` | **已有**，UX4 需加点击导航回设计面板 | +15 |
| `frontend/src/App.vue` | **已有** | — |
| `frontend/src/components/DashboardAiTools.vue` | UX1 加载提示 + UX2 state 持久化 + `restoreDesignState` | +40 |

**小计**：4 个前端文件共 +75 行增量改动。

### 5.3 总计

| | 文件数 | 行数 | 新依赖 |
|:--|:-----:|:----:|:-----:|
| 后端修复（含 P0.5） | 8 | ~130 | 0 |
| 前端任务感知（原始 + UX 修复） | 6（2 新建 + 4 修改） | ~255 | 0 |
| **合计** | **14** | **~385** | **0** |

---

## 六、验证计划

1. **单元测试（P0 + P0.5）**：mock `trend_data={"510300": {}}`（空结果模拟 akshare 超时）+ `index_realtime` 含深证成指 -5.40% → 断言 `detect_market_regime` 返回 `"correction"`
2. **单元测试（P3 数据）**：mock `_fetch_single_trend` 返回含 `change_pct`；断言 `build_rationale` 输出以「今日跌 X%」开头
3. **Prompt 验证（P1）**：检查 `_build_design_report_prompt` 输出包含「市场行情快照」「行业板块动量」两节
4. **端到端**：调用 `/portfolio/design-enhanced`，检查 `market_context` 含 `index_realtime` 与 `sector_momentum` 新字段
5. **LLM 报告**：触发设计 + WS 推送，验证报告中引用了实际指数涨跌幅
6. **前端 A/B**：收到 `task_update` 的 `completed` 后，验证前端经 `getTask` 取得 `design_id` 并拉取详情；导航栏铃铛与 toast 正常触发
7. **UX 回归（手动）**：点击「开始设计」→ 切换到其他页面 → 通过 TaskIndicator 回入设计面板 → 验证状态恢复；点击历史记录 → 骨架屏显示 + 列表加载 <1s

---

## 七、预期效果对比

| 维度 | 修复前 | 修复后 |
|------|-------|-------|
| 市场状态判断 | 永远「震荡」 | 「回调/熊市/恐慌」动态判定 |
| 防御层配置 | 永远 5% | 熊市自动升至 10-15% |
| 核心层配置 | 永远中性 20/15/10 | 熊市自动切防御模式 15/12/15 |
| LLM 报告市场描述 | 「市场情绪中性」 | 「深证成指今日跌 5.4%，市场处于回调阶段」 |
| 入选理由 | 「市场震荡；情绪中性」模板 | 「今日跌 7.7%；近 1 月跌 12.3%；市场回调中」 |
| 行业动量参考 | 无 | Top 5 强弱行业排名 |
