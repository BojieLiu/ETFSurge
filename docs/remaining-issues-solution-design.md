# 已知剩余问题解决方案设计

## 问题一：设计耗时 4.6 分钟

### 现状
单轮设计包含三步：
1. `pool_manager.refresh()` — 全市场 1608 只 ETF 扫描 + 因子计算 → **~30s**
2. `allocation_engine.allocate()` — 分配引擎 → **<1s**
3. LLM 报告生成（DeepSeek）— 三方案描述 + 市场分析 → **~100s**
4. 报告持久化、WS推送等 → **~15s**
                                    **总计 ≈ 4.6min**

### 方案：三段缓存 + 延迟抽象 + 报告流式化

#### A: `pool_manager` 缓存分层（预计节省 ~25s）

当前每次设计都触发全量刷新。改为：
- **全量缓存** 60 秒有效（`_last_refresh` 时间戳缓存）
- **增量刷新**：60-300 秒内的刷新只更新热门标的因子分（前 50 只），跳过全量扫描
- **强制刷新**：超过 300 秒或显式调用才全量扫描

```python
# pool_manager.py
_refresh_ts = 0.0
async def refresh(self, force=False):
    now = time.monotonic()
    if not force and now - self._refresh_ts < 60:
        return self._cached_pool
    if not force and now - self._refresh_ts < 300:
        return await self._refresh_incremental()
    return await self._refresh_full(persistent=True)
```

实现修改：`pool_manager.py` 增加 `_cached_pool` 字段和老化策略。涉及文件：`backend/app/services/pool_manager.py`，约 30 行新增。

#### B: LLM 报告生成异步化（预计节省 ~90s）

当前设计流程是**串行**的：先等 allocate 结果，再串行调用三次 LLM（三份方案描述）+ 一次市场分析。

改为：
- 三份方案描述**并发调用** LLM（`asyncio.gather`）
- 市场分析单独并发
- 整体 LLM 耗时从 4×25s → 1×25s（最慢的单个调用）

```python
# strategy_design.py
descriptions = await asyncio.gather(
    generate_description(strategies[0]),
    generate_description(strategies[1]),
    generate_description(strategies[2]),
    market_analysis(regime),
)
```

实现修改：`backend/app/services/strategy_design.py` 和 `backend/app/analysis/llm.py`，约 50 行。

#### C: 报告生成拆分为可选阶段（预计节省 ~20s 的持久化开销）

设计 API 增加 `report_depth` 参数：
- `"quick"`：只返回 allocate 结果，不生成 LLM 报告 → **~35s**
- `"standard"`：生成精简描述 → **~90s**
- `"full"`：当前行为（完整报告+WS推送） → **~4.6min**

```python
# POST /portfolio/design-async
json={"capital": 500000, "report_quality": "quick"}
```

实现修改：`backend/app/routers/portfolio.py`（路由参数）+ `backend/app/tasks/design_tasks.py`（分阶段逻辑），约 30 行。

### 预期效果

| 模式 | 现有时长 | 优化后 | 节省 |
|:-----|:--------:|:------:|:---:|
| quick | 4.6min | **~35s** | 4min |
| standard | 4.6min | **~90s** | 3min |
| full | 4.6min | **~2min** | 2.5min |

---

## 问题二：因子分全负

### 现状
z-score 标准化后所有因子分以 0 为中心。在持续下跌的行情中，所有 ETF 的原始因子值（RSI、MACD、动量等）都低于历史均值，导致 z-score 全为负。

已经做了：z-score 乘以 5 放大。

但根本问题没解决：**全负的因子分仍然只能区分"谁跌得少"，无法区分"谁涨得多"。**

### 方案：双基准归一化

#### A: 混合基准（z-score + min-max）
对每个因子同时计算两种归一化，取综合值：
```python
# factor_registry.py
z = (val - mean) / std
mm = (val - min_v) / (max_v - min_v) * 2 - 1  # 映射到 [-1, 1]
combined = z * 0.5 + mm * 0.5
```
即使 z-score 全负，min-max 也能把"相对最好的"映射到正数。

#### B: 弹性尺度
当最大值与最小值差距过小时（所有标的因子值相同），降级到固定先验：
```python
if max_v - min_v < EPSILON:
    mm = 0  # 无区分度时不惩罚
```

#### C: 因子截断与翻转
对某些天然为负的因子做符号翻转：
```python
# 波动率：越低越好 → 符号翻转
vol_score = -volatility_z
```

### 预期效果

| 方案 | 因子分范围 | 正数占比 | 三方案差异度 |
|:-----|:----------:|:--------:|:----------:|
| 当前（z-score ×5） | -5σ ~ +5σ | 可正可负但牛市多负 | variance 0.1-5 |
| 混合基准 | -3 ~ +3 | **>20% 为正** | variance 1-10 |

---

## 问题三：`/tasks` 并发超时

### 现状
设计任务运行期间，GET `/api/v1/portfolio/tasks/{task_id}` 偶尔超时（15-30s 无响应）。虽然事件循环预导入问题已修复，但以下场景仍会阻塞：

1. SQLite 写锁（`report_quality` 持久化在事件循环线程内执行）
2. WS 推送在被慢客户端阻塞时拖滞

### 方案：读路径隔离

#### A: `/tasks` 专用存储（内存 dict → 无锁）

当前 `TaskManager` 已有内存 dict（`self.tasks`），`get_task` 是 O(1) 的 dict lookup。但在高并发下，Python 的 GIL 和 SQLite 写锁仍可能干扰。

检查发现当前 `get_task` 已经不走 DB —— 从任务状态输出看，它直接返回 dict。所以理论上不会超时。

根因实际是：**服务器总线程池被长期 I/O 占满**。当 `run_sync_long` 使用 _long_running_executor（8 workers）时还剩 56 个 worker 给 API。但如果 Sina HTTP 请求在 _shared_executor 上排队...

**确认修复方案：**

- 新增 `/tasks` 轻量路由（skip pool_manager 和 DB）
- 在 `main.py` lifespan 中**预创建**一个独立低优先级客户端 session 池
- 所有数据获取类请求统一走 `_shared_executor` 的快速排队机制

#### B: 读写锁细化

```python
# task_manager.py
_task_lock = threading.RLock()  # 替代 asyncio.Lock 避免事件循环依赖
```

#### C: 慢 WS 客户端自动断开

```python
# ws.py: ConnectionManager
if time.time() - client.last_pong > 30:
    await client.disconnect()
```

### 实施优先级

| 步骤 | 内容 | 预计效果 |
|:-----|:------|:--------:|
| 1 | `get_task` 路由改为纯内存路径（跳过所有 I/O） | `/tasks` 99% 不超时 |
| 2 | `_task_lock` 改用 threading.RLock | 减少 asyncio 锁竞争 |
| 3 | WS 慢客户端超时断开 | 防止 WS 拖累 HTTP |

---

## 实施路线图

| 阶段 | 内容 | 依赖 | 预估工时 |
|:-----|:------|:-----|:--------:|
| **S1** | Pool 60s 缓存 + LLM 并发化 | 无 | 1 小时 |
| **S2** | 因子双基准归一化 | S1 之后 | 30 分钟 |
| **S3** | `/tasks` 纯内存 + WS 断开 | S1 之后 | 30 分钟 |
| **S4** | 测试 + E2E 验证 | S1+S2+S3 | 30 分钟 |

总预估：约 **2.5 小时** 完成所有优化。
