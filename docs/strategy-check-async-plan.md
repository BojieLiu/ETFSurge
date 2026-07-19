# 策略检查异步化方案

## 现状问题

当前 `POST /strategy-check` 是同步 HTTP 请求：
- 用户点击→loading 60-90s→一次返回全部结果
- 中间无进度反馈，超时风险（axios 60s→已修复120s）
- 大组合（20+ ETF）时因子+技术指标+LLM 串行叠加更慢

## 目标

改为类似 `design-async` 的异步模式：
1. 提交后立即返回 task_id
2. 后台 worker 逐步执行，通过 WebSocket 推送进度
3. 前端展示实时进度，完成后自动展示结果

---

## 一、API 契约变更

### 新增端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/portfolio/strategy-check-async` | 异步提交策略检查任务，返回 `{task_id, status}` |
| GET | `/portfolio/strategy-check-result/{task_id}` | 查询任务完成后的结果 |

### POST 请求体

```json
{"total_capital": 500000}
```

### POST 响应 (202)

```json
{"task_id": 42, "status": "pending", "created_at": "2026-07-20T..."}
```

### GET 响应

```json
{
  "task_id": 42,
  "status": "completed",
  "summary": "...",
  "suggestions": [...],
  "holdings_analysis": [...],
  "risk_warnings": [...],
  "market_regime": "correction"
}
```

### WebSocket 进度事件

通过已有 `/ws/task-notifications` 推送：

```json
{"type": "task_update", "task_id": 42, "status": "running", "progress": 10}
{"type": "task_update", "task_id": 42, "status": "running", "progress": 30}
{"type": "task_update", "task_id": 42, "status": "running", "progress": 70}
{"type": "task_update", "task_id": 42, "status": "completed", "progress": 100}
{"type": "task_update", "task_id": 42, "status": "failed", "progress": 0, "error": "..."}
```

---

## 二、后端实现

### 文件变更

| 文件 | 改动 |
|------|------|
| `backend/app/tasks/design_tasks.py` | 复用 `DesignTaskManager` / `TaskNotifyManager`（已有） |
| `backend/app/tasks/strategy_check_worker.py` | **新建** — `strategy_check_worker()` 后台 worker |
| `backend/app/routers/portfolio.py` | 新增 `POST /strategy-check-async` + `GET /strategy-check-result/{task_id}` |
| `backend/app/services/portfolio_service.py` | `strategy_check()` 保持不动（worker 直接调用） |

### Worker 执行流程

```
task_id 创建 (status=pending, progress=0)
  → status=running, progress=10  [加载持仓]
  → status=running, progress=30  [因子评分]
  → status=running, progress=50  [技术指标]
  → status=running, progress=70  [市场状态/regime]
  → status=running, progress=80  [LLM 分析]
  → status=completed, progress=100 [保存结果]
```

### Result 存储

worker 完成后将结果存入 task_manager 的 task dict：

```python
task["_result"] = {
    "summary": ...,
    "suggestions": ...,
    "holdings_analysis": ...,
    "risk_warnings": ...,
    "market_regime": "correction",
}
```

`GET /strategy-check-result/{task_id}` 从 task dict 读取 `_result` 返回。

---

## 三、前端实现

### 文件变更

| 文件 | 改动 |
|------|------|
| `frontend/src/api/index.js` | 新增 `strategyCheckAsync()` + `getStrategyCheckResult()` |
| `frontend/src/composables/useTaskWS.js` | 扩展支持 strategy_check 类型（已有 WS 连接复用） |
| `frontend/src/components/DashboardAiTools.vue` | 替换 `checkStrategy()` 为异步流程 |

### 前端流程

```
用户点击"开始检查"
  → POST /strategy-check-async → 收到 task_id
  → 显示进度条（progress 0-100%）
  → WebSocket 接收 task_update 事件 → 更新进度条和阶段文本
  → 收到 "completed" → GET /strategy-check-result/{task_id}
  → 展示完整结果面板
```

### 进度阶段文本

| progress | 显示文本 |
|----------|---------|
| 0-10% | 正在加载持仓数据... |
| 10-30% | 正在计算因子评分... |
| 30-50% | 正在计算技术指标... |
| 50-70% | 正在判断市场状态... |
| 70-80% | 正在生成 LLM 分析... |
| 80-99% | 正在生成分析报告... |
| 100% | 分析完成 ✓ |

---

## 四、历史记录

### 需求

策略检查结果应持久化到数据库，与组合方案设计历史并列展示。

### 数据模型

新建 `StrategyCheckRecord` 表（`backend/app/models/strategy_check.py`）：

```
strategy_check_records
├── id (PK, auto)
├── created_at (DateTime)
├── capital (Float)
├── summary (Text)
├── suggestions_json (Text)   ← JSON: list[StrategySuggestion]
├── holdings_json (Text)      ← JSON: list[holdings_analysis]
├── risk_warnings_json (Text) ← JSON: list[risk_warnings]
├── market_regime (String)
```

### 后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portfolio/strategy-checks` | 列出历史策略检查（分页） |
| GET | `/portfolio/strategy-checks/{id}` | 获取单条检查详情 |

### 前端历史面板

`loadHistoryList()` 同时拉取两类记录：

```javascript
const [designs, checks] = await Promise.all([
  portfolioApi.listDesigns(20, 0),
  portfolioApi.listStrategyChecks(20, 0),
])
historyList.value = [...designs, ...checks]
  .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
```

历史列表项通过 `type` 字段区分：
- `type: 'design'` → 💡 图标 + capital / risk_profile
- `type: 'check'`  → 🔍 图标 + regime / summary 截断

点击后分别调用 `loadHistoryDetail(id)` / `loadCheckDetail(id)`。

### worker 持久化

worker 完成 LLM 分析后保存：

```python
record = StrategyCheckRecord(
    capital=task["capital"],
    summary=llm_result.get("summary", ""),
    suggestions_json=json.dumps(llm_result.get("suggestions", [])),
    holdings_json=json.dumps(llm_result.get("holdings_analysis", [])),
    risk_warnings_json=json.dumps(llm_result.get("risk_warnings", [])),
    market_regime=regime,
)
```

---

## 五、变更清单（实施时参考）

1. `docs/strategy-check-async-plan.md` — 本方案文档 ✓
2. `api-contracts/portfolio/strategy.md` — 更新契约（异步端点 + 历史）
3. `backend/app/models/strategy_check.py` — 新建模型
4. `backend/app/tasks/strategy_check_worker.py` — 新建 worker
5. `backend/app/routers/portfolio.py` — 新增 4 个端点
6. `backend/tests/test_strategy_check_async.py` — 新增单测
7. `frontend/src/api/index.js` — 新增 API 方法
8. `frontend/src/stores/task.js` — 扩展支持 strategy_check 类型
9. `frontend/src/components/DashboardAiTools.vue` — 改造按钮/进度/历史面板
