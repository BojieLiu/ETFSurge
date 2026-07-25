# 已知剩余问题解决方案设计 (v4)

> 状态：✅ **已全部实施** | 预估工时：2.5h（实际实施跨度 2 个 session）
> 实施日期：2026-07-25
> 实施说明：S1-A(TTL 缓存) `53acbfa` ✅、S1-C(渐进状态机) `ef3de11` ✅、S3-B/C(WS 超时+清理) `ef3de11` ✅、S2(混合归一化) `5116681` ✅ — 均已 committed。
> 上次评审：2026-07-25 | 本版变更：去掉 report_quality 参数 → 自动渐进状态机；
> 修正问题三根因分析；简化缓存策略；增加验收标准和风险处理

---

## 问题一：设计耗时 4.6 分钟

### 现状

单轮设计链路耗时分解：

| 阶段 | 当前耗时 | 瓶颈类型 |
|:-----|:--------:|:---------|
| pool_manager.refresh() — 全市场1608只扫描+因子计算 | ~30s | 网络I/O |
| allocation_engine.allocate() | <1s | CPU |
| LLM 报告生成（三次方案描述 + 市场分析，串行） | ~100s | API I/O |
| 报告持久化 + WS推送 | ~15s | I/O |
| **总计** | **~4.6min** | — |

### 方案

#### A: pool_manager 60 秒 TTL 缓存（节省 ~25s）

取消全量增量分层，简化为单一 TTL 缓存：

```python
# pool_manager.py, class PoolManager
def __init__(self):
    ...
    self._cached_pool: dict | None = None
    self._cached_ts: float = 0.0
    self._cache_ttl: float = 60.0

async def refresh(self, force: bool = False) -> dict:
    now = time.monotonic()
    if not force and self._cached_pool and (now - self._cached_ts) < self._cache_ttl:
        return self._cached_pool
    # 全量刷新（run_sync_long），结果原地缓存
    layer_pool = await self._refresh_impl()
    self._cached_pool = layer_pool
    self._cached_ts = now
    return self._cached_pool
```

- **TTL=60s**：用户第二次点击"生成"直接命中缓存，耗时忽略
- **force=True**：lifespan 启动时和 `POST /admin/trigger-refresh`（如存在）时使用
- **不实现增量刷新**：1608只ETF的Sina扫描 + 腾讯补充Sina列约12-15s，占比不大，不值得为增量增加复杂度

涉及文件：`backend/app/services/pool_manager.py`，约40行。

#### B: LLM 报告并发化（节省 ~75s）

当前：三次方案描述 + 市场分析 = **4次串行** LLM 调用 → ~100s。
改为：**asyncio.gather 并发**，整体耗时 = max(单次调用耗时) → ~25s。

```python
# strategy_design.py
from asyncio import gather

async def _generate_llm_descriptions(strategies, regime):
    """并发生成三方案描述 + 市态分析。"""
    tasks = [
        _describe_strategy(s, regime) for s in strategies
    ] + [_market_analysis(regime)]
    return await gather(*tasks)
```

涉及文件：
- `backend/app/services/strategy_design.py` — 替换串行调用为 gather，约 30 行
- `backend/app/analysis/llm.py` — 无需改动，现有 `generate_description` 已经是 async

#### C: 自动渐进状态机（向用户隐藏复杂度，替代原 report_quality）

**不暴露 `report_quality` 参数。** 后端收到 `POST /portfolio/design-async` 后自动执行三段式：

```
task.submitted  (返回 task_id)
    ↓
── pool.refresh() + allocate() ──  ~35s ──
    ↓ task.status = "quick_ready"
    ↓ WS推送: {type: "design_quick", strategies: [...]}
    │  前端展示组合方案，用户可操作
    │
    ↓ (后台继续)
── LLM 并发描述 ──  ~60s ──
    ↓ task.status = "stage:descriptions"
    └─ WS推送: {type: "design_descriptions", ...}
    │  前端组合卡片下方显示"分析"标签
    │
    ↓ (后台继续)
── 完整报告 + 持久化 ──  ~60s ──
    ↓ task.status = "completed"
    └─ WS推送: {type: "design_report", report: {...}}
    │  前端弹窗或新标签页展示完整报告
```

**核心原则**：前端只看 `task.status` 的值变化来切换 UI，不需要理解"报告深度"概念。

- `in_progress` → 加载动画
- `quick_ready` → 展示组合方案，继续显示"报告生成中..."
- `completed` → 报告就绪，展示完整报告
- `failed` → 显示错误

涉及文件：
- `backend/app/tasks/design_tasks.py` — design_pipeline 改为三段状态机，约 50 行
- `backend/app/services/design_report.py` — 报告生成拆分为独立函数，约 20 行
- `backend/app/tasks/worker_registry.py` — 注册新状态，约 5 行

### 风险处理

| 场景 | 行为 |
|:-----|:-----|
| LLM 报告阶段超时（>90s） | 任务回退到 `quick_ready` 状态，report_quality = "fallback" |
| 分配引擎阶段失败 | 任务标记 `failed`，前端显示"数据源不可用" |
| WS推送失败 | 静默，用户下次轮询 `/tasks/{id}` 仍可获取结果 |

### 预期效果

| 用户视角 | 路由入口 | 等待时间 | 能看到什么 |
|:---------|:---------|:--------:|:----------|
| 普通使用 | POST design-async | **~35s** | 三只组合方案（权重、标的、因子分） |
| 等待完整 | 同一入口，自动升级 | +**~60s** | LLM 方案描述出现 |
| 最终结果 | 自动完成 | +**~60s**（总计 ~160s） | 完整市场研判报告 |

**对比当前：** 35s 看到组合方案 vs 当前 4.6min 才能看到任何结果。

---

## 问题二：因子分全负

### 现状

z-score 标准化后所有因子分以 0 为中心。在持续下跌行情中，所有 ETF 的原始因子值（RSI、MACD、动量等）都低于历史均值，z-score 全为负。

已做的修复：z-score 乘以 5 放大因子（commit `5116681`）。

但根本问题是：**所有标的都相似时，z-score 的区分力趋近于零，即使放大也无法产生正分数。**

### 方案：混合归一化

当前代码（factor_registry.py ~line 746）：
```python
z = (val - mean_v) / std_v
result[sym][code] = z * 5.0
```

改为：
```python
z = (val - mean_v) / std_v

# min-max 归一化到 [-1, 1]：保证顶部标为正
min_v = min(vals)
max_v = max(vals)
if max_v - min_v > 1e-10:
    mm = (val - min_v) / (max_v - min_v) * 2.0 - 1.0
else:
    mm = 0.0  # 所有值相同时不惩罚

# 混合：z-score（统计异常度）+ min-max（相对排名）
combined = z * 0.7 + mm * 0.3
result[sym][code] = combined * 5.0
```

`mm * 0.3` 的权重保证即使 z-score 全负，排名靠前的标的也会得到 **mm ≈ +1 → +0.3 的偏移**，足够覆盖部分 z-score 的负值。

### 影响面

- 仅涉及 `factor_registry.py` 中单一循环体（~20 行）
- 输出格式不变（仍是 `dict[str, dict[str, float]]`），下游零影响
- 原有 z-score ×5 的代码直接替换

### 效果预期

| 指标 | 当前（z-score×5） | 修复后（混合归一化） |
|:-----|:-----------------:|:------------------:|
| 因子分区间 | -5σ ~ +5σ | -5σ ~ +5σ |
| 多头市场顶部标的分 | >0 | >0（不变） |
| 空头市场顶部标的分 | <0（全负） | **>0**（min-max 兜底） |
| 尾部标的分 | <<0 | <<0（不变） |

---

## 问题三：`/tasks` 并发超时

### 修正的根因分析

会话中已排查：

1. `TaskManager.get_task()` 是纯 dict lookup（`self._tasks.get(task_id)`）→ **无 I/O 无锁，不会阻塞**
2. `GET /api/v1/portfolio/tasks/{task_id}` 路由是普通 async def → **无同步操作**
3. 设计任务通过 `asyncio.create_task()` 在后台运行 → **事件循环不阻塞**

**实际根因**（已修复）：`design_tasks.py` 中的 `from app.services.strategy_design import ...` 放在函数体内，首次导入时 Python 的**导入锁**阻塞事件循环 5-15 秒。`GET /tasks` 在此期间无法被处理。

修复（commit `3a3dc0a`）：main.py lifespan 预导入所有重型模块。

**以下为加固措施，非必要但推荐。**

### 加固措施

#### A: 导入路径内联（推荐，5 行，5 分钟）

将 `design_tasks.py` 和 `report_worker.py` 中的函数体内导入改为文件顶部导入，彻底消除隐患：

```python
# design_tasks.py 顶部
from ..services.strategy_design import generate_enhanced_design
from ..tasks.design_report import compose_and_push_report
```

#### B: WS 慢客户端超时断开

当前 `broadcast()` 逐个发送不设超时，慢客户端可能拖累其他客户端。

```python
# ws.py, broadcast()
for conn in targets:
    try:
        await asyncio.wait_for(conn.send_text(...), timeout=5.0)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await self.disconnect(conn, channel)
```

- `asyncio.wait_for` 保每个客户端 5 秒内完成发送
- 超时自动断开，不影响其他客户端

涉及文件：`backend/app/routers/ws.py`，约 5 行。

#### C: 心跳清理

当前 `ConnectionManager` 没有后台心跳。慢客户端断开后 `broadcast` 仍会尝试发送直到超时。

```python
# ws.py, __init__()
self._cleanup_interval = 60  # 60s 检查一次
self._last_cleanup = time.monotonic()
```

不需要定时器，在 `broadcast()` 调用时检查 `if now - _last_cleanup > _cleanup_interval`，扫描无效连接。

涉及文件：`backend/app/routers/ws.py`，约 15 行。

---

## API 契约

### 请求

```http
POST /api/v1/portfolio/design-async
Content-Type: application/json

{"capital": 500000}
```

NO `report_quality`，NO `depth`。后端自动渐进。

### 响应

```json
{
  "task_id": "123",
  "status": "in_progress",
  "progress": 0
}
```

### 状态机（前端轮询 /tasks/{task_id} 或 监听 WS）

| task.status | 何时触发 | 前端行为 |
|:------------|:---------|:---------|
| `in_progress` | 提交后立即 | 显示加载动画 |
| `quick_ready` | 分配引擎完成（~35s） | 展示组合方案，仍显示"报告生成中..."
| | | task.result 含 {"strategies": [...], "regime": "...", "report_stage": "quick"} |


| `completed` | 完整报告就绪（~160s） | 展开完整报告 |
| `failed` | 分配阶段出错 | 显示错误，任务不可恢复 |
| `completed_with_errors` | LLM 报告阶段出错 | 展示 quick_ready 方案 + "报告暂不可用" |



### WS 事件（channel: design-report/{session_id}）

| type | 载荷 | 触发时机 |
|:-----|:-----|:---------|
| `design_quick` | `{"strategies": [...], "regime": "..."}` | quick_ready |
| `design_descriptions` | `{"descriptions": [...], "status": "partial"}` | 描述就绪 |
| `design_report` | `{"report": {...}, "status": "full"}` | completed |
| `design_error` | `{"error": "..."}` | failed |

---

## 验收标准

每项修复完成后，按以下标准验证：

### 问题一

| # | 验收项 | 检查方法 | 通过条件 |
|:-|:-------|:---------|:---------|
| V1-1 | 第二次点击生成命中缓存 | 连续两次 POST，第二次耗时 <5s | 第二次 <5s |
| V1-2 | 60s 后缓存过期 | 等待 65s 后再次 POST，耗时 >10s（有网络 I/O） | >10s |
| V1-3 | quick_ready 状态机制 | POST 后轮询，**35s 内** status 变为 quick_ready | 35s 内 |
| V1-4 | 完整报告 | 同一任务继续轮询，**160s 内** status 变为 completed | 160s 内 |
| V1-5 | LLM 失败降级 | 模拟 LLM 超时，任务状态最终为 completed_with_errors（非 failed） | status=completed_with_errors |
| V1-6 | 缓存过期后自动刷新 | 等待 65s，第 2 次请求触发 refresh（如有其他并发请求在第 65s 之后） | 刷新后候选池包含新 ETF 数据 |

### 问题二

| # | 验收项 | 检查方法 | 通过条件 |
|:-|:-------|:---------|:--------- |
| V2-1 | 因子分正数存在 | compute(["510300","518880","511090"]) 返回的分数中有 >0 的 | >20% of factors > 0 |
| V2-2 | 区分度 >0.1 | 计算因子分方差 | variance > 0.1 |
| V2-3 | 零标准差不崩溃 | 构造全相同因子值，compute 返回 {sym: {code: 0}} | 不抛异常 |

### 问题三

| # | 验收项 | 检查方法 | 通过条件 |
|:-|:-------|:---------|:---------|
| V3-1 | GET /tasks 不超时 | 设计任务运行中，并发 10 次 GET /tasks | 全部 <1s |
| V3-2 | WS 慢客户端不影响 | 一个客户端暂停 10s，其他客户端正常接收 broadcast | 正常客户端不受影响 |
| V3-3 | 断开清理 | 断开连接后 broadcast 不报错 | 无异常日志 |

---

## 实施路线图

| 阶段 | 内容 | 依赖 | 预估工时 | 验收标准 |
|:-----|:------|:-----|:--------:|:---------|
| **S1** | pool 60s TTL 缓存 | 无 | 20min | V1-1, V1-2, V1-6 |
| | LLM 并发化 + 状态机 | 无 | 40min | V1-3, V1-4, V1-5 |
| | 导入路径内联 | 无 | 5min | V3-1 |
| **S2** | 因子混合归一化 | S1 之后 | 20min | V2-1, V2-2, V2-3 |
| **S3** | WS 超时 + 清理 | S1 之后 | 15min | V3-2, V3-3 |
| **S4** | E2E 验证 | S1+S2+S3 | 30min | 全部 13 项通过 |

**总计：约 2 小时 10 分钟。**
