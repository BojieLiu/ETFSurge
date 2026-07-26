# 前端业务逻辑下沉方案

> 目标：消除前端重复计算和业务逻辑，让前端只做"拿数据、展数据"，后端管"计算/聚合/状态"
>
> 版本：v2（经过系统审查修正后）

## 目录

- [Sprint 1 — Dashboard 财务指标去重 + 方案格式去重](#sprint-1--p0p1-dashboard-财务指标去重--方案格式去重)
- [Sprint 2 — 历史合并 + 搜索统一 + PnL 分类型聚合](#sprint-2--p1p3-历史合并--搜索统一--pnl-分类型聚合)
- [Sprint 3 — 任务轮询提取 + Sector URL 统一 + 超时修复](#sprint-3--p2-任务轮询提取--sector-url-统一--超时修复)
- [Sprint 4 — 自选同步 + 格式化字段（可选）](#sprint-4--p2p3-自选同步--格式化字段可选)
- [通用约定](#通用约定)

---

## Sprint 1 — P0/P1: Dashboard 财务指标去重 + 方案格式去重

### 1.1 P0: Dashboard 财务指标去重

#### 现状

`composables/useDashboardData.js` 中有 10 个 computed。其中 3 个（`totalAll`、`pnlOn`、`pnlOff`）**已是对后端返回字段的直读**，无需修改。

需要改造的只有 7 个 computed：`pnlTotal`、`pnlTotalAmount`、`pnlWeightedChange`、`cashPctOn`、`cashOn`、`cashPctOff`、`cashOff`。

#### 需改造的 computed 对照表

| 前端 computed | 当前前端计算方式 | 后端已返回字段 | 替换方式 |
|---|---|---|---|
| `pnlTotal` | `pnlItems.reduce((s, i) => s + (i.daily_pnl\|\|0), 0)` | `daily-pnl` 返回 `total_pnl` | 改为直接用后端 `total_pnl`。combined 时为 `pnlOnData.value.total_pnl + pnlOffData.value.total_pnl` |
| `pnlTotalAmount` | `pnlItems.reduce((s, i) => s + (i.target_amount\|\|0), 0)` | `daily-pnl` 返回 `total_amount` | 同上 |
| `pnlWeightedChange` | `pnlItems.reduce((s, i) => s + (i.daily_pnl / total) * 100, 0)` | `daily-pnl` 返回 `weighted_change_pct` | **按 tab 区分**（见下方关键逻辑） |
| `cashPctOn` | `Math.max(0, (capital - used) / capital)` | `calculate` 返回 `cash_weight` | 直接取 `allocationOn.value.cash_weight` |
| `cashOn` | `capitalOn.value - total_amount` | `calculate` 返回 `cash_amount` | 直接取 `allocationOn.value.cash_amount` |
| `cashPctOff` | 同上 | 同上 | 直接取 `allocationOff.value.cash_weight` |
| `cashOff` | 同上 | 同上 | 直接取 `allocationOff.value.cash_amount` |


#### pnlWeightedChange 按 tab 区分的关键逻辑

```js
// 现状 — 所有 tab 都用同一个 reduce 计算
const pnlWeightedChange = computed(() => {
  const total = pnlTotalAmount.value
  if (!total) return 0
  return pnlItems.value.reduce((sum, item) => sum + ((item.daily_pnl || 0) / total) * 100, 0)
})

// 改造后 — 按 tab 从后端直接取值
const pnlWeightedChange = computed(() => {
  const tab = activeTab.value
  if (tab === 'on_exchange') return pnlOnData.value.weighted_change_pct || 0
  if (tab === 'off_exchange') return pnlOffData.value.weighted_change_pct || 0
  // combined: 使用后端 total_pnl 和 total_amount 的简单除法
  const totalAmount = (pnlOnData.value.total_amount || 0) + (pnlOffData.value.total_amount || 0)
  const totalPnl = (pnlOnData.value.total_pnl || 0) + (pnlOffData.value.total_pnl || 0)
  return totalAmount > 0 ? (totalPnl / totalAmount) * 100 : 0
})
```

#### pnlItems 的处理

`pnlItems` 只是 items 的数据合并（非计算），保留但简化：

```js
// 现状 — 合并 on+off 的 items
const pnlItems = computed(() => {
  if (activeTab.value === 'on_exchange') return pnlOnData.value.items || []
  if (activeTab.value === 'off_exchange') return pnlOffData.value.items || []
  return [...(pnlOnData.value.items || []), ...(pnlOffData.value.items || [])]
})
// ✅ 保留，这是数据呈现的合并，不是金融计算
```

#### 精确修改清单

| # | 文件 | 操作 |
|---|------|------|
| F1.1 | `frontend/src/composables/useDashboardData.js` | 删除 `pnlTotal`/`pnlTotalAmount`/`pnlWeightedChange`/`cashPctOn`/`cashPctOff`/`cashOn`/`cashOff` 的 computed 定义（共 7 个） |
| F1.2 | 同上 | 新增 `pnlTotal` 为 tab-aware 的 `pnlOnData.value.total_pnl + pnlOffData.value.total_pnl` |
| F1.3 | 同上 | 新增 `pnlTotalAmount` 为 tab-aware 的 `pnlOnData.value.total_amount + pnlOffData.value.total_amount` |
| F1.4 | 同上 | 新增 `pnlWeightedChange` 按 tab 区分（使用后端 `weighted_change_pct`，combined 时 `(totalPnl / totalAmount) * 100`） |
| F1.5 | 同上 | `cashPctOn` 改为 `allocationOn.value.cash_weight \|\| 0` |
| F1.6 | 同上 | `cashOn` 改为 `allocationOn.value.cash_amount \|\| 0` |
| F1.7 | 同上 | `cashPctOff` 改为 `allocationOff.value.cash_weight \|\| 0` |
| F1.8 | 同上 | `cashOff` 改为 `allocationOff.value.cash_amount \|\| 0` |

> **注意**：`totalAll`、`pnlOn`、`pnlOff` 三个 computed 已经是后端返回值的直读，**无需修改**。

#### 测试文件更新

`frontend/src/test/useDashboardData.spec.js` 中以下测试期望需同步更新：

| 受影响测试 | 行号 | 当前断言 | 改为 |
|---|---|---|---|
| `cashOn = capitalOn - used amount` | L104-109 | 手动赋值 `total_amount` 并期望 `cashOn = capital - total_amount` | mock `allocationOn.value.cash_amount`，直接期望 `cashOn = cash_amount` |
| `cashPctOn = (capital - used) / capital` | L111-115 | 同上 | 直接期望 `cashPctOn = cash_weight` |
| `cashOff = capitalOff - used amount` | L123-127 | 同 cashOn | 同 cashOn |
| `cashPctOff = (capital - used) / capital` | L129-133 | 同 cashPctOn | 同 cashPctOn |
| `pnlTotal sums all daily_pnl values` | L181-190 | 期望 `100 + 50 = 150` | 直接期望 `total_pnl` 值 |
| `pnlTotalAmount sums` | L192-201 | 同上 | 直接期望 `total_amount` 值 |
| `pnlWeightedChange calculates` | L203-213 | 期望 reduce 结果 | 期望 tab-aware 的公式结果 |

> ⚠️ Mock 数据调整：`portfolioApi.getPnl` 的 mock response 需要增加 `total_pnl`/`total_amount`/`weighted_change_pct` 等汇总字段（后端实际上已经返回这些字段，但 mock 中没有包含）。

#### 验证策略

- 运行 `cd frontend && npm test` 检查 `useDashboardData` 测试通过
- Dashboard 页面手动走查：切换三个 tab，确认 `totalAll`、`pnlTotal`、`pnlWeightedChange` 正确
- 无 ETF 时测试空状态
- 运行 `npm run build` 确保无编译错误

#### 尾部声明：后端不需要任何改动

---

### 1.2 P1: 设计方案格式转换去重

#### 现状

`DashboardAiTools.vue` 中两处做相同的数据转换：

```
fetchDesignDetail() L319-339  → data.strategies → plans
onHistorySelect()   L584-597  → data.strategies → plans
```

两处转换不一致（`onHistorySelect` 比 `fetchDesignDetail` 多 `risk_factors` 字段）。

#### 后端改动

**`GET /api/v1/portfolio/designs/{id}` 响应中新增 `plans` 字段**，直接返回前端需要的数据结构，`strategies` 保留以向后兼容。

新增字段 `plans` 的格式：

```json
{
  "strategies": [ ... ],  // 保留，不变
  "plans": [
    {
      "style": "防御型",
      "style_label": "防御型",
      "portfolio_name": "防御稳健组合",
      "positioning": "低波稳健配置，控制回撤，适合保守风险偏好者",
      "expected_return": 0.08,
      "max_drawdown": -0.12,
      "sharpe_ratio": 1.2,
      "risk_factors": [],
      "rebalance_rules": "月度检视",
      "allocations": [
        {
          "symbol": "510300",
          "name": "沪深300ETF",
          "layer": "core",
          "target_weight": 0.15,
          "selection_rationale": "沪深300核心宽基，当前偏低估区间"
        }
      ]
    }
  ]
}
```

字段映射规则（后端 `get_design()` 中新增）：

| strategies 源字段 | plans 目标字段 | 转换规则 |
|---|---|---|
| `s.label` | `.style` | 直接映射 |
| `s.label` | `.style_label` | 直接映射 |
| `s.portfolio_name` | `.portfolio_name` | 直接映射 |
| `s.positioning` | `.positioning` | 直接映射 |
| `s.expected_return` | `.expected_return` | 直接映射 |
| `s.max_drawdown` | `.max_drawdown` | 直接映射 |
| `s.sharpe_ratio` | `.sharpe_ratio` | 直接映射 |
| `s.risk_factors` | `.risk_factors` | `s.risk_factors \|\| []` |
| — | `.rebalance_rules` | 固定值 `"月度检视"` |
| `s.etfs[].symbol` | `.allocations[].symbol` | 直接映射 |
| `s.etfs[].name` | `.allocations[].name` | 直接映射 |
| `s.etfs[].layer` | `.allocations[].layer` | 直接映射 |
| `s.etfs[].weight` | `.allocations[].target_weight` | **改名**：`weight` → `target_weight` |
| `s.etfs[].selection_rationale` | `.allocations[].selection_rationale` | `\|\| ''` |

#### 精确修改清单

| # | 文件 | 操作 |
|---|---|---|
| B1.1 | `backend/app/routers/portfolio.py` | `get_design()` 返回中增加 `plans` 字段（实现字段映射逻辑） |
| F1.10 | `frontend/src/views/DashboardAiTools.vue` | `fetchDesignDetail()` 改为 `const plans = data.plans || []`（删除转换逻辑） |
| F1.11 | 同上 | `onHistorySelect()` 改为 `const plans = data.plans || []`（删除转换逻辑） |

#### 验证策略

- 查看历史设计方案，确认卡片/报告 Tab 数据正确
- 新生成的方案确认格式一致
- 运行 `verify_e2e.py` 确认 `design_text 已持久化` 和其他检查项 PASS
- 运行 `npm run build`

---

## Sprint 2 — P1/P3: 历史合并 + 搜索统一 + PnL 分类型聚合

### 2.1 P1: 历史列表合并排序

#### 现状

`DashboardAiTools.vue` L510-526 前端发两次请求 + 本地拼合排序。

#### 后端新增 timeline endpoint

**新路由**: `GET /api/v1/portfolio/timeline`

**参数**:

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | int | No | 20 | 返回条数上限 |
| `offset` | int | No | 0 | 分页偏移 |

**响应**:

```json
{
  "items": [
    {
      "id": 42,
      "_type": "design",
      "created_at": "2026-07-26T12:00:00",
      "status": "completed",
      "capital": 500000.0,
      "error_message": null
    },
    {
      "id": 7,
      "_type": "check",
      "created_at": "2026-07-25T10:30:00",
      "status": "completed",
      "summary": "策略检查已完成",
      "error_message": null
    }
  ],
  "total": 42
}
```

**实现要点**:
- 后端从 `portfolio_designs` 和 `strategy_check_records` 两个表分别查询
- 按 `created_at DESC` 合并排序
- 分页在合并排序后做（`sorted_all[offset:offset+limit]`）
- `_type` 取值：`"design"` 或 `"check"`
- `total` 为两个表的记录数之和（不减去 offset/limit 影响）

#### 精确修改清单

| # | 文件 | 操作 |
|---|---|---|
| B2.1 | `backend/app/routers/portfolio.py` | 新增 `GET /timeline` 路由 |
| B2.2 | `api-contracts/portfolio/` | 新建 `timeline.md` 契约文件 |
| F2.1 | `frontend/src/api/index.js` | 新增 `portfolioApi.getTimeline(limit, offset)` |
| F2.2 | `frontend/src/views/DashboardAiTools.vue` | `loadHistoryList()` 改为单次 `portfolioApi.getTimeline()` 调用；运行中的 task 仍由 `taskStore` 本地补入列表头部 |

#### 验证策略

- 有 design 和 check 记录时，查看任务列表确认正确合并
- 分页加载更多（loadMoreTasks）确认连续
- 运行中 task 显示在列表最前面

---

### 2.2 P1: 搜索结果统一

#### 现状

前端 `useMarketSearch.js` 发两个请求手动合并。

#### 后端改动

`GET /api/v1/market/search` 新增 `include_stocks` 参数（与原 `market` 参数兼容）：

```python
@router.get("/search")
async def search(
    keyword: str = Query(""),
    market: str | None = Query(None),
    include_stocks: bool = Query(False),
) -> list[dict]:
```

当 `include_stocks=true` 时，后端统一查 ETF + 个股，合并排序后返回。

**响应**（与现有格式兼容，仅增加 `type` 字段）：

```json
[
  { "symbol": "510300", "name": "沪深300ETF", "type": "etf", "asset_type": "A" },
  { "symbol": "600519", "name": "贵州茅台", "type": "stock", "asset_type": "A" }
]
```

**`type` 字段取值**: `"etf"` / `"stock"`（英文，前端展示时映射为中文）

#### 精确修改清单

| # | 文件 | 操作 |
|---|---|---|
| B2.3 | `backend/app/routers/market.py` | `search()` 增加 `include_stocks` 参数和合并逻辑 |
| B2.4 | `api-contracts/market/all.md` | 更新契约，增加 `include_stocks` 参数和 `type` 字段 |
| F2.3 | `frontend/src/composables/useMarketSearch.js` | `doSearch()` 改为单次调用 `marketApi.search(keyword, { include_stocks: true })`；同时 import `marketApi` 替换 `fetchJson` |
| F2.4 | `frontend/src/composables/useMarketSearch.js` | 删除 `type` 映射逻辑（后端直接返回 type） |
| F2.5 | `frontend/src/api/index.js` | `marketApi.search` 增加 `params.include_stocks` 参数传递 |
| F2.6 | `frontend/src/test/useMarketSearch.spec.js` | 修改 mock：从 mock `fetchJson` 改为 mock `marketApi.search`，期望单次调用 |

#### 验证策略

- 输入关键词搜索，确认 ETF 和个股都能搜到
- `type` 字段正确传给 `PortfolioManager` 组件

---

### 2.3 P3: PnL 分类型聚合

#### 现状

`SummaryCards.vue` 中 `findCumulativePnl(type)` 从前端 `pnlHistory.holdings` 中按 `portfolio_type` 过滤。

#### 后端改动

`GET /api/v1/portfolio/pnl-history` 响应中的 `summary` 结构增强：

```json
{
  "summary": {
    "total_cost_basis": 500000.00,
    "total_market_value": 520000.00,
    "total_cumulative_pnl": 20000.00,
    "total_cumulative_pnl_pct": 4.00,
    "has_cost_basis_data": true,
    "by_type": {
      "on_exchange": {
        "cumulative_pnl": 12000.00,
        "cumulative_pnl_pct": 4.80
      },
      "off_exchange": {
        "cumulative_pnl": 8000.00,
        "cumulative_pnl_pct": 3.20
      }
    }
  },
  "holdings": [ ... ]
}
```

#### 精确修改清单

| # | 文件 | 操作 |
|---|---|---|
| B2.5 | `backend/app/services/portfolio_service.py` | `calculate_cumulative_pnl()` 返回中增加 `summary.by_type` 子字段 |
| B2.6 | `api-contracts/portfolio/pnl-history.md` | 更新契约 |
| F2.5 | `frontend/src/components/dashboard/SummaryCards.vue` | 改为直接取 `pnlHistory.summary.by_type.on_exchange.cumulative_pnl` |
| F2.6 | 同上 | 删除 `findCumulativePnl()` 和 `findCumulativePnlPct()` 函数 |

#### 验证策略

- 有成本数据时，确认各卡片的累计盈亏数值正确
- 无成本数据时，确认显示"需输入成本"

---

## Sprint 3 — P2: 任务轮询提取 + Sector URL 统一 + 超时修复

### 3.1 任务轮询提取

#### 现状

`DashboardAiTools.vue` 中有两套独立轮询逻辑（设计任务 + 策略检查），`stores/task.js` 还有第三套超时检测。

#### 新建 composable: `useTaskPolling.js`

**接口定义**:

```js
/**
 * 可复用的任务轮询 composable
 * @param {string} taskId - 任务 ID
 * @param {object} options - 选项
 * @param {number} options.interval - 轮询间隔（ms，默认 10000）
 * @param {number} options.timeout - 超时时间（ms，默认 180000）
 * @param {number} options.maxErrors - 熔断连续错误次数（默认 5）
 * @param {function} options.onCompleted - 完成回调
 * @param {function} options.onFailed - 失败回调
 * @param {function} options.onProgress - 进度更新回调
 * @returns {object} { start, stop, progress, stage, status, error, isRunning }
 */
export function useTaskPolling(taskId, options = {}) {
  // ...
}
```

**使用方式**:

```js
// 替换设计任务轮询
const polling = useTaskPolling(taskData.task_id, {
  onCompleted: (task) => { /* 加载结果 */ },
  onFailed: (task) => { /* 显示错误 */ },
})
polling.start()
```

**实现要点**:
- 统一 `interval: 10000`、`timeout: 180000`（两个任务统一用 180s）
- 熔断逻辑：连续错误 5 次
- 不再使用 `Math.min(pollCount * 10, 80)` 前端自行估算进度
- 提供 `stop()` 方法用于 cleanup

#### 修复 `stores/task.js` 超时检测

**`_startStaleCheck()` 的替代方案**：

当前 `_startStaleCheck()` 每 30s 检查一次，将运行超过 120s 的任务标记为失败。这个逻辑与后端 task_manager 的 90s 超时保护不一致。

改造后：
1. 删除 `_startStaleCheck()` 和 `_staleTimer`
2. `fetchAndMergeTasks()` 从后端 `/tasks` 接口刷新时，**完全信任后端任务状态**，不做前端二次超时判断
3. 如果后端重启导致 in-memory 任务丢失，`fetchAndMergeTasks()` 返回空列表时自动清除前端对应状态

#### 修复后端 `progress` 为 null 的问题

`backend/app/tasks/task_manager.py` 中 `get_task()` 确保 `progress` 始终有值：

```python
# 修改前
return {
    "task_id": ...,
    "progress": task.get("progress"),  # 可能为 None
}

# 修改后
return {
    "task_id": ...,
    "progress": task.get("progress") or 0,
}
```

#### 精确修改清单

| # | 文件 | 操作 |
|---|---|---|
| B3.1 | `backend/app/tasks/task_manager.py` | `get_task()`/`list_tasks()` 返回中确保 `progress` 不为 null |
| F3.1 | `frontend/src/composables/` | 新建 `useTaskPolling.js` |
| F3.2 | `frontend/src/views/DashboardAiTools.vue` | 两处轮询改为使用 `useTaskPolling` |
| F3.3 | `frontend/src/stores/task.js` | 删除 `_startStaleCheck()`（L19-33），`fetchAndMergeTasks` 信任后端状态 |

#### 验证策略

- 发起设计任务，确认轮询正常，完成后自动加载方案
- 发起策略检查，确认轮询正常
- 组件卸载（`onBeforeUnmount`）时确认轮询停止，无内存泄漏
- 后端 `/tasks` 接口返回 `progress: 0` 而非 `null`

---

### 3.2 Sector URL 统一

#### 现状

`useSectorAnalysis.js` 中前端拼接硬编码 URL。

#### 后端新增统一路由

**`GET /api/v1/market/sectors`**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `type` | string | Yes | — | `industry` 或 `concept` |
| `limit` | int | No | 200 | 返回条数限制 |
| `market` | string | No | `A` | 市场筛选 |

该路由内部转发到现有的 `/market/sectors/industry` 或 `/market/sectors/concept`（或直接查询 DB）。

#### 精确修改清单

| # | 文件 | 操作 |
|---|---|---|
| B3.2 | `backend/app/routers/market.py` | 新增 `GET /sectors` 统一路由 |
| F3.4 | `frontend/src/api/index.js` | 新增 `marketApi.getSectors(params)` |
| F3.5 | `frontend/src/composables/useSectorAnalysis.js` | `fetchSectorList()` 改为用 `marketApi.getSectors()` 替换 `fetchJson` 硬编码 URL |
| F3.6 | 同上 | 删除 `fetchJson` 的 import |

#### 验证策略

- 切换行业/概念板块，确认列表正常加载
- 切换 marketTab，确认自动刷新

---

## Sprint 4 — P2/P3: 自选同步 + 格式化字段（可选）

### 4.1 P2: 自选清单本地状态取消

#### 现状

`stores/market.js` 中 watchlist CRUD 操作同时维护本地缓存：
```js
watchlist.value.unshift(res.data)   // 添加后
watchlist.value = watchlist.value.filter(...)  // 删除后
```

#### 修改方案

所有 CRUD 操作后直接重新 `fetchWatchlist()`，不维护本地增量。性能不是问题——watchlist 通常不超过 100 条。

如果批量操作频繁，后端 `POST /watchlist` 可返回完整列表而非单条，省去二次请求。

#### 精确修改清单

| # | 文件 | 操作 |
|---|---|---|
| F4.1 | `frontend/src/stores/market.js` | `addWatchlist()` 中删除 `watchlist.value.unshift()` 和 `watchlistTotal.value += 1`，改为 `await fetchWatchlist()` |
| F4.2 | 同上 | `updateWatchlist()` 中删除本地修改，改为 `await fetchWatchlist()` |
| F4.3 | 同上 | `removeWatchlist()` 中删除 `watchlist.value.filter()` 和 `watchlistTotal.value -= 1`，改为 `await fetchWatchlist()` |
| F4.4 | 同上 | `batchRemoveWatchlist()` 同上 |

#### 验证策略

- 添加自选后列表自动刷新
- 删除自选后列表自动刷新

---

### 4.2 P3: 展示层格式化（可选）

#### 现状

```html
<!-- AllocationTable.vue -->
<span class="weight-badge">{{ (item.target_weight * 100).toFixed(1) }}%</span>
```

#### 可选优化

**注意**: `changeClass`（CSS class 选择）是纯 UI 职责，不应下沉。只下沉数字格式化。

后端在 `calculate_allocation` 返回中增加：

```python
# portfolio_service.py allocation 构建时增加
"display_weight_pct": f"{round(e.target_weight * 100, 1)}%",
"display_change": f"{'+' if change_pct > 0 else ''}{change_pct:.2f}%",
```

前端改为直接使用：

```html
<span class="weight-badge">{{ item.display_weight_pct }}</span>
```

#### 精确修改清单

| # | 文件 | 操作 |
|---|---|---|
| B4.1 | `backend/app/services/portfolio_service.py` | `calculate_allocation` 返回增加 `display_weight_pct`、`display_change` |
| F4.5 | `frontend/src/components/dashboard/AllocationTable.vue` | 改为 `{{ item.display_weight_pct }}` |
| F4.6 | `frontend/src/components/dashboard/PnLDetailTable.vue` | `formatChange()` 替换为 `item.display_change` |

---

## 实施优先级汇总

| Sprint | 内容 | 后端改动量 | 前端改动量 | 风险 | 需新契约 |
|--------|------|-----------|-----------|------|---------|
| **Sprint 1** | P0 财务指标去重 + P1 方案格式去重 | 极小（增加 `plans` 字段） | 中（2 个文件重构 + 1 个文件简化） | **低** | 更新 `designs/{id}` 契约 |
| **Sprint 2** | P1 历史 timeline + 搜索统一 + P3 PnL 分类型 | 中（2 个新路由 + 1 个现有路由增强） | 小（3 个文件修调用） | **低** | `timeline.md` 新建 + `search` 更新 + `pnl-history` 更新 |
| **Sprint 3** | P2 轮询提取 + Sector URL + 超时修复 | 小（1 个 bug fix） | 中（新建 composable + 2 个文件重构） | **中**（需验证轮询可靠性） | 无需 |
| **Sprint 4** | P2 自选同步 + P3 格式化 | 极小（2 个字段） | 中（4 个文件微调） | **低** | 无需 |

**预估总工时**: 后端 1.5-2d + 前端 2-3d

---

## 通用约定

### 后端改动的原则

1. **向后兼容**: 新字段只增不减。`strategies` 保留，新增 `plans`
2. **契约先行**: 每次后端改动前，先更新或新建对应的 `api-contracts/` 文件
3. **`verify_e2e.py`**: 每次改完后端必须运行，确认全 PASS

### 前端改动的原则

1. **每个 Sprint 单独提交**: 一个 Sprint 内涉及的所有文件改动在同一个 commit 中完成
2. **`npm run build`**: 每次改完前端必须运行确保无编译错误
3. **不破坏预提交钩子**: pre-commit 门禁中的 `npm run build` 应通过

### 验证清单（每次 Sprint 完成）

- [ ] 后端单测通过：`cd backend && python -m pytest`
- [ ] E2E 链路通过：`cd backend && python scripts/verify_e2e.py`（全 PASS）
- [ ] 前端编译通过：`cd frontend && npm run build`（无 error）
- [ ] 前端单测通过：`cd frontend && npm test`
- [ ] 改动涉及的页面手动走查关键功能

### 风险登记

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| P0 改完后 `Dashboard.vue` 模板中某个 `cashPctOn` 引用遗漏 | 低 | 改完后 `npm run build` 会报未定义的变量错误 |
| P1 `plans` 字段与旧前端不兼容 | 低 | 保留 `strategies` 字段不变 |
| P2 轮询 composable 在多组件间共享状态 | 中 | `useTaskPolling` 每个实例独立，无全局状态 |
| P3 `by_type` 结构与外部 API 消费者不兼容 | 低 | 只在 `summary` 对象中新增 `by_type` 子字段，不改变顶层字段 |
