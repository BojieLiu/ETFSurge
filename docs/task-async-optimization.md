## 十、异步任务管理优化方案

### 10.1 当前基础设施

已有可复用的通用组件：

**后端**：
- `DesignTaskManager`（`tasks/design_tasks.py:26`） — 内存任务表（create_task/update_task/get_task/list_tasks）
- `TaskNotifyManager`（`tasks/design_tasks.py:79`） — WS 广播（注册/注销/broadcast）
- WS 通道 `/ws/task-notifications`（`routers/ws.py:104`） — 前端长连接监听
- `design_worker`（`tasks/design_tasks.py:111`） — 组合设计后台执行器
- `strategy_check_worker`（`tasks/strategy_check_worker.py:20`） — 策略检查后台执行器（已复用 TaskNotifyManager）

**前端**：
- `task.js` Pinia store — 泛化 `taskType` 字段（`design`/`check`），addTask/updateTask/getTask
- 持久化到 localStorage（F5/关页不丢）
- 自动过期 5min 的 running 任务标记为 failed
- `DashboardAiTools.vue:113-157` 已有 loading 进度条 UI，可抽取为通用 `<TaskProgress>` 组件

### 10.2 问题

#### 10.2.1 任务模型是"设计"专属

```python
# DesignTaskManager.create_task() 返回的 task dict
task = {
    "task_id": ...,
    "status": "pending",
    "progress": 0,
    "design_id": None,       # ← 只有设计需要
    "capital": 500000,       # ← 只有设计需要
    "risk_profile": "...",   # ← 只有设计需要
    "constraints": {},       # ← 只有设计需要
}
```

要支持 `llm-report` 等新任务类型，这些字段不通用。

#### 10.2.2 `_notify()` 函数签名不统一

```python
# design_tasks.py — 无 stage 字段
async def _notify(task_id, status, progress):

# strategy_check_worker.py — 有 stage 字段
async def _notify(task_id, status, progress, stage=""):
```

两个版本的 `_notify` 独立存在于两个文件中，抽取到统一模块后应合并。

#### 10.2.3 DesignTaskManager 被 3 个文件引用

| 文件 | import 行 | 引用内容 |
|------|-----------|----------|
| `routers/portfolio.py` | line 373,391,403,427,444 | `task_manager`, `design_worker` |
| `routers/ws.py` | line 107 | `notify_manager` |
| `tasks/strategy_check_worker.py` | line 113 | `notify_manager` |

共 3 个文件 7 处 import 需要同步更新。

### 10.3 优化方案

#### 10.3.1 TaskManager 泛化

抽取 `DesignTaskManager` 为通用 `TaskManager`（`backend/app/tasks/task_manager.py`）：

```python
class TaskManager:
    """通用异步任务管理器。"""

    TASK_TYPES = {
        "design": {"label": "组合设计", "ttl": 600},
        "check":  {"label": "策略检查", "ttl": 600},
        "report": {"label": "市场研判", "ttl": 600},
    }

    def __init__(self):
        self._tasks: dict[int, dict] = {}
        self._next_id = 1

    def create_task(self, task_type: str, params: dict | None = None) -> dict:
        assert task_type in self.TASK_TYPES, f"unknown task type: {task_type}"
        task_id = self._next_id
        self._next_id += 1
        task = {
            "task_id": task_id,
            "type": task_type,                  # ← 泛化
            "status": "pending",
            "progress": 0,
            "stage": "",                        # ← 新增，统一携带 stage 文字
            "params": params or {},             # ← 泛化，不同任务放不同参数
            "result": None,                     # ← 泛化，不同任务放不同结果
            "error_message": None,
            "created_at": time.strftime(...),
            "completed_at": None,
        }
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: int) -> dict | None: ...
    def update_task(self, task_id: int, **kwargs) -> None: ...
    def list_tasks(self, limit=20, offset=0) -> list[dict]: ...


notify_manager = TaskNotifyManager()  # WS 通知管理器，保持不变


async def _notify(task_id: int, status: str, progress: int, stage: str = "") -> None:
    """统一 WS 通知函数。stage 为可选进度文字描述。"""
    await notify_manager.broadcast({
        "type": "task_update",
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "stage": stage,
    })
```

#### 10.3.2 Worker 注册表

新增 `backend/app/tasks/worker_registry.py`：

```python
WORKER_REGISTRY = {
    "design": design_worker,
    "check":  strategy_check_worker,
    "report": report_worker,     # Phase 4 新增
}

async def dispatch(manager: TaskManager, task_id: int) -> None:
    """通用调度器：根据 task.type 找到对应 worker 并执行。"""
    task = manager.get_task(task_id)
    if not task:
        return
    worker = WORKER_REGISTRY.get(task["type"])
    if not worker:
        manager.update_task(task_id, status="failed",
                            error_message=f"unknown task type: {task['type']}")
        await _notify(task_id, "failed", 0)
        return
    await worker(manager, task_id)
```

#### 10.3.3 新增 report_worker

`backend/app/tasks/report_worker.py`：

```python
async def report_worker(mgr: TaskManager, task_id: int) -> None:
    """异步执行市场综合研判。复用数据管道缓存，零额外采集成本。"""
    task = mgr.get_task(task_id)
    try:
        mgr.update_task(task_id, status="running", progress=10, stage="正在获取市场数据")
        await _notify(task_id, "running", 10, "正在获取市场数据")

        mc = get_orchestrator_context()  # 数据管道缓存，TTL 120s
        if not mc:
            raise RuntimeError("编排器不可用")

        mgr.update_task(task_id, progress=30, stage="正在生成研判报告")
        await _notify(task_id, "running", 30, "正在生成研判报告")

        report = await generate_market_report_v2(
            indices=mc["index_realtime"],
            us_indices=mc["us_indices"],
            commodities=mc["commodities"],
            news=mc["news"],
            regime=mc["market_regime"],
            sentiment=mc["market_sentiment"],
        )

        mgr.update_task(task_id, progress=100, status="completed",
                        result={"report": report})
        await _notify(task_id, "completed", 100, "报告已生成")
    except Exception as e:
        mgr.update_task(task_id, status="failed", error_message=str(e))
        await _notify(task_id, "failed", 0, str(e))
```

#### 10.3.4 路由统一入口

新增通用入口，旧路由保留别名（向后兼容）：

```python
# portfolio.py — 新增
@router.post("/async-task")
async def submit_async_task(task: dict):
    """通用异步任务提交。请求体: {type: "report", params: {...}}"""
    from ..tasks.task_manager import task_manager
    from ..tasks.worker_registry import dispatch
    t = task_manager.create_task(task["type"], task.get("params"))
    asyncio.create_task(dispatch(task_manager, t["task_id"]))
    return JSONResponse(
        status_code=202,
        content={"task_id": t["task_id"], "type": t["type"], "status": "pending"},
    )

# 保留旧路由别名（内部重定向）
@router.post("/design-async")
async def portfolio_design_async(task: dict):
    task["type"] = "design"
    return await submit_async_task(task)

@router.post("/strategy-check-async")
async def strategy_check_async(task: dict):
    task["type"] = "check"
    return await submit_async_task(task)
```

#### 10.3.5 前端 task store 扩展

`frontend/src/stores/task.js` 改动：

```javascript
// 新增类型标签映射
const TASK_LABELS = {
  design: '智能组合设计',
  check:  '策略检查分析',
  report: '市场综合研判',
}

// addTask 中 label 默认值改为按 type 查找
function addTask(taskId, taskType = 'design', label) {
  label = label || TASK_LABELS[taskType] || '后台任务'
  ...
}
```

`DashboardAiTools.vue` 中的 loading 进度条 UI（行 113-157）抽取为通用组件 `TaskProgress.vue`，所有异步任务页面共用。

### 10.4 兼容性

| 兼容事项 | 说明 |
|----------|------|
| `_notify` 签名统一 | 使用 `(task_id, status, progress, stage)`，原有 design_worker 步进时补 stage 文字描述 |
| import 路径变更 | `design_tasks.py` → `task_manager.py`，影响 portfolio.py / ws.py / strategy_check_worker.py 共 7 处 |
| 旧路由保留别名 | `POST /design-async` / `POST /strategy-check-async` 内部重定向到 `POST /async-task`，前端无需修改 |
| 前端 `task.js` | 现有 `design`/`check` 类型完全兼容，只需在 TASK_LABELS 中新增 `report` |
| `DashboardAiTools.vue` | `task-store` watch 逻辑不变，`taskType` 字段已存在 |

### 10.5 适用链路列表

| 链路 | 当前模式 | 推荐改 WS async？ | 原因 |
|------|---------|-----------------|------|
| 组合设计 | ✅ WS async | 已是最优 | — |
| 策略检查 | ✅ WS async | 已是最优 | — |
| **市场综合研判** | ❌ SSE + sync 180s | **✅ 强烈推荐** | 耗时 15-40s，用户可离开页面，已有 report_worker 方案 |
| AI 投资顾问 | ✅ SSE | 维持 | 对话式交互，SSE 自然 |
| 个股分析 | ✅ SSE | 维持 | 用户盯图表分析，SSE 足够 |
| 板块分析 | ✅ SSE | 维持 | 同上 |
| 资讯 AI 分析 | ❌ 纯 sync | 维持 | 5-10s 短等待 |
| 新闻影响 | ✅ SSE | 维持 | 3-8s 短等待 |

### 10.6 实施顺序

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 1 | 抽取 `task_manager.py`（TaskManager 泛化 + 统一 `_notify` + 迁入 TaskNotifyManager） | Phase 3 末 |
| 2 | 创建 `worker_registry.py`，原有 design_worker + strategy_check_worker 迁入 | 步骤 1 |
| 3 | 新增 `POST /async-task` 统一入口，旧路由改为内部别名 | 步骤 2 |
| 4 | 更新 `portfolio.py` / `ws.py` 共 7 处 import 路径 | 步骤 1 |
| 5 | 新增 `report_worker.py` | Phase 4 |
| 6 | 前端 TaskProgress 组件抽取 + task store 扩展 | Phase 4 |
