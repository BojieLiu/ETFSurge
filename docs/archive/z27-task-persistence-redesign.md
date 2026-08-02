# Z27 任务列表系统级数据断裂 — 可落地实施方案

> 版本: v2.1（已通过两轮独立审查，见 §13 修订记录）
> 日期: 2026-07-31
> 来源: `docs/v5_diagnostic_and_optimization_plan.md` Z27（严重度: 高）
> 状态: **✅ 已实施（2026-07-31，Phase 39）** — 验收 A1-A8 全部落地，见 docs/implementation-master-plan.md v39.0
> 对应架构目标: 任务持久化「TaskManager JSON + DB 双轨 → 统一到 DB」（v5 方案 §19）

---

## 0. 结论摘要

Z27 的根因是**任务状态与业务记录（设计方案 / 策略检查）分离存储、且任务状态存放在进程内 JSON 文件**：
进程重启、文件路径漂移、TTL 清理任一环节出问题，任务列表即断裂，而 DB 中的设计/检查记录仍在。

**本方案采用「以 DB 为唯一真相源」**（v5 方案 A 的具体化），核心动作：

1. 新增 `TaskRecord` 表（SQLite），任务生命周期全部落 DB；
2. `TaskManager` 改为 DB-backed 异步实现，删除 JSON 持久化双轨；
3. 任务完成时把 `design_id` / 检查 `record_id` 回写任务行，前端可从任务直达业务记录；
4. 前端 taskStore 单数据源 + WS 实时推送（补齐 check 任务的 `record_id` 通知）；
5. 启动时对遗留的 running/pending 任务统一标记 failed（进程已死，诚实收敛状态）。

**验收锚点**: 重启后端后 `GET /tasks` 仍返回任务、任务可关联 `GET /designs/{id}` 与 `GET /strategy-checks/{id}`、`GET /tasks/{id}` 返回契约全部字段、`tasks.json` 不再被创建。

---

## 1. 现状核查（对照 v5 文档 6 个断裂点）

> 以下为 2026-07-31 对当前代码的实际核查结论，非文档复述。

### 1.1 关键事实

| 事实 | 证据 |
|------|------|
| DB 位于项目根 `data/portfolio.db`（7.4MB，活跃） | `backend/app/config.py` `_DATA_DIR = _PROJECT_DIR / "data"`；`backend/data/portfolio.db` 为 0 字节残留 |
| 任务持久化 JSON 位于 `backend/data/tasks.json` | `task_manager.py:43` `DEFAULT_PERSIST_PATH = .../app/tasks/../../data/tasks.json` |
| **本地模式下 tasks.json 与 DB 不在同一目录**（`backend/data/` vs `data/`）；Docker 下两者经 `./backend:/app` + `./data:/app/data` 双挂载重合 | `docker-compose.yml` |
| `TaskManager` 是内存 dict + JSON 读写；`create_task/update_task/get_task/list_tasks` 全为同步方法 | `task_manager.py:45-189` |
| 设计管线完成时会把 `design_id` 写入 `task.result`，并 WS 推送 `design_id` | `task_manager.py:512-524` |
| 策略检查 worker 完成时把 `record_id` 写入任务（`update_task(record_id=...)`），但**本地 `_notify` 不携带 record_id**，WS 消息缺此字段 | `strategy_check_worker.py:173-180,191-200` |
| `GET /tasks/{id}` 响应缺 `type` / `stage` / `params` / `record_id`（与契约不符） | `routers/portfolio.py:274-289` vs `api-contracts/portfolio/tasks.md §2.4` |
| 前端 App.vue 已订阅 `/ws/task-notifications`，WS 已打通（F5 已修复） | `frontend/src/App.vue:183-250` |
| 前端 taskStore 仅内存态，不写 localStorage；`persistDesignState` 仅存向导表单状态（UX2 设计，非任务状态） | `frontend/src/stores/task.js` |
| 启动时已有 stuck 任务清理（>5min 的 running → failed） | `main.py:314-332`（A04） |
| `prune_tasks()` 默认把 >1h 的终态任务从 JSON 中删除（重启后即消失） | `task_manager.py:128-184` |
| `asyncio_mode = auto`：测试可直接写 async，转换成本低 | `backend/pytest.ini` |
| DB 中无 `tasks` 表 | `sqlite_master` 核查 |

### 1.2 断裂点现状汇总

| 断裂 | v5 描述 | 现状核查 | 本方案处理 |
|------|---------|---------|-----------|
| F1 | TaskManager 与 DB 各自为政 | **仍存在**：任务在 JSON，记录在 DB，无双向索引 | 任务落 DB，`record_id` 列关联 |
| F2 | 重启后任务消失 | **部分修复**：Phase 30b 修正了 `app/data`→`data` 路径；但本地 tasks.json 与 DB 仍不同目录，且 1h TTL 剪枝仍删任务 | 移除 JSON，DB 持久化 + 合理保留期 |
| F3 | 刷新页面 → 前端空 | **仍存在**（后端空则前端空） | 后端从 DB 恢复，前端刷新即有 |
| F4 | GET /tasks/{id} 404 | **仍存在**：重启/剪枝后任务丢失即 404 | DB 查询 + 启动收敛 |
| F5 | WS 未订阅 | **已修复**（App.vue 订阅 + 重连 + backfill） | 保留；补齐 check 的 record_id |
| F6 | localStorage 双轨 | **已解决**（任务状态不写 localStorage） | 保留现状，文档化 |

---

## 2. 设计目标与验收标准

### 2.1 目标

1. **重启不丢任务**：后端重启后 `GET /tasks` 返回重启前的任务（含终态任务，带 `record_id`）。
2. **任务直达记录**：design 任务可经 `record_id` 关联 `GET /designs/{id}`；check 任务可经 `record_id` 关联 `GET /strategy-checks/{id}`。
3. **契约完整**：`GET /tasks/{id}`、`GET /tasks`、WS `task_update` 全部字段符合 `api-contracts/portfolio/tasks.md`。
4. **单一真相源**：任务状态只存 DB；删除 `_save()/_load()` 与 tasks.json 读写；前端不落任务 localStorage。
5. **诚实收敛**：重启后遗留的 running/pending 任务标记 failed 并给出原因，不悬挂。

### 2.2 验收标准（实施后逐条验证）

| # | 验收项 | 验证方式 |
|---|--------|---------|
| A1 | 重启后端后 `GET /tasks` 仍返回之前的任务 | 单测（同 DB 两实例）+ 手工重启验证 |
| A2 | design 任务完成，`task.record_id == design_id`，可 `GET /designs/{record_id}` 200 | 单测 + e2e |
| A3 | check 任务完成，`task.record_id == check_id`，可 `GET /strategy-checks/{record_id}` 200 | 单测 + e2e |
| A4 | `GET /tasks/{id}` 返回 `task_id/type/status/progress/stage/params/result/error_message/created_at/completed_at/record_id` | 契约测试 |
| A5 | `backend/data/tasks.json` 不再被创建/写入（删除代码后文件不出现） | 单测 + grep |
| A6 | WS `task_update` 消息含 `record_id`（design/check 完成时） | 单测（notify_manager 捕获）+ 前端用例 |
| A7 | 启动时遗留 running → failed（带 error_message），不再悬挂 | 单测 |
| A8 | `pytest` 全量 PASS（含适配后的旧测试）、`verify_e2e.py` 全 PASS、前端 `npm run build` + `npm test` PASS | CI 命令 |

---

## 3. 架构设计

### 3.1 数据流（改造后）

```
用户提交设计
  -> POST /design-async
  -> TaskManager.create_task()          ① INSERT tasks (status=pending)
  -> design_pipeline() 异步执行
     -> 每阶段: update_task()           ② UPDATE tasks (progress/stage)
     -> 完成: 写 PortfolioDesign 表      ③ INSERT portfolio_designs
     -> update_task(record_id=design_id) ④ UPDATE tasks (status=completed, record_id)
     -> WS broadcast (task_id/status/progress/stage/design_id/record_id)

前端:
  -> GET /api/v1/portfolio/tasks  <- SELECT tasks ORDER BY created_at DESC   （DB）
  -> 发现 completed -> GET /designs/{record_id}  <- SQLite                  （DB）
  -> WS task_update -> 直接更新 tasks.value（实时）
  -> 轮询降级为 fallback（已存在）

重启后端:
  -> init_db() 建/校验 tasks 表（create_all，无需 migration）
  -> 启动收敛: 所有 running/pending -> failed(后端重启，任务中断)
  -> GET /api/v1/portfolio/tasks  <- SELECT tasks（终态任务保留期内仍在）
```

### 3.2 关键决策记录

| 决策 | 内容 | 理由 |
|------|------|------|
| **D1** | `TaskManager` 全部方法改为 `async`，DB-backed | 全部生产调用方（routers/workers/lifespan/registry）均为 async；`asyncio_mode=auto` 降低测试适配成本；避免「内存缓存 + DB 写穿」双轨（那是 Z27 的根因本身） |
| **D2** | 新建 `TaskRecord` 表，**不用 FK 硬约束**，用 `record_id` 逻辑关联 | SQLite 默认关闭外键、项目现有 `PortfolioDesign` 也无 FK；design_id 在管线中途才产生，先 INSERT 后 UPDATE；逻辑关联足够且避免迁移风险 |
| **D3** | 保留扩展状态 `quick_ready` / `completed_with_errors`，契约文档化 | 渐进式状态机（S1-C）是既有设计，前端已处理；契约需补齐，避免「实现跑在契约前」 |
| **D4** | 重启时所有非终态任务 → `failed`（不再只处理 >5min） | 进程已死，任何 running/pending 都不可能被原 worker 接管；诚实收敛比悬挂强；error_message 指明原因 |
| **D5** | 保留期策略：终态任务保留 7 天 / 最近 100 条（可配常量），SQL 清理 | 替代 1h TTL（那是「重启即空」的直接元凶）；有界增长 |
| **D6** | **不迁移** `backend/data/tasks.json` 历史任务 | 任务行是执行状态，真正历史在 portfolio_designs / strategy_check_records（本就在 DB）；JSON 中多为已过 TTL 的终态任务，无迁移价值 |
| **D7** | 前端任务点击：design → 首页方案详情；check → `/portfolio-analysis`（deep-link checkId 列为 P2 延伸） | 保持最小改动；`PortfolioAnalysis` 目前不消费 checkId query |
| **D8** | 契约先行：先改 `tasks.md`，再实现 | 项目强制流程（AGENTS.md），也是本次设计的交付物之一 |
| **D9** | `TaskManager.__init__(persist_path=None)` 参数保留但忽略（DeprecationWarning） | `design_tasks.py` 兼容层与现有测试大量 `TaskManager()`/`TaskManager(persist_path=...)`，保留签名最小化破坏 |
| **D10** | `TaskManager` 支持注入 `session_factory`（默认 `async_session`），测试注入独立 SQLite 引擎 | 现有测试大量 mock `app.tasks.task_manager.async_session`（pipeline 写 portfolio_designs 用）+ MagicMock mgr（`await` 普通 dict 会 TypeError）；DB-backed 后 `get_task/list_tasks` 走 SELECT，mock session 无 `execute/scalars` 必崩。注入真实测试库是唯一干净出路 |
| **D11** | `task_manager.py` **保持模块级** `from app.database import async_session` 导入 | 既有测试 patch 目标 `app.tasks.task_manager.async_session`（pipeline 的 DB 写路径仍走它）不失效，降低适配面 |

---

## 4. TaskRecord 数据模型

### 4.1 SQLAlchemy 模型（新建 `backend/app/models/task.py`）

```python
"""任务记录模型（Z27: DB 唯一真相源）"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from ..database import Base


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)          # = task_id
    task_type = Column(String(16), nullable=False)                     # design|check|report
    status = Column(String(20), nullable=False, default="pending")     # pending|running|quick_ready|completed|completed_with_errors|failed
    progress = Column(Integer, nullable=False, default=0)              # 0-100
    stage = Column(String(64), nullable=False, default="")
    params_json = Column(Text, nullable=False, default="{}")
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    record_id = Column(Integer, nullable=True)                         # design: design_id; check: check_id
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        import json
        return {
            "task_id": self.id,
            "type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "params": json.loads(self.params_json) if self.params_json else {},
            "result": json.loads(self.result_json) if self.result_json else None,
            "error_message": self.error_message,
            "record_id": self.record_id,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
            "completed_at": self.completed_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.completed_at else None,
        }
```

### 4.2 建表与迁移

- `database.py::init_db()` 增加 `from .models.task import TaskRecord` 导入。
- `create_all` 对**新表**自动建表，**无需** `_migrate()` 改动（`_migrate` 只处理既有表 ALTER）。
- 表名 `tasks` 与现有表无冲突（已核查 sqlite_master）。

### 4.3 字段 → 契约映射

| TaskRecord | 契约字段（tasks.md） | 说明 |
|-----------|----------------------|------|
| `id` | `task_id` | 契约明确「任务唯一标识是 task_id 不是 id」；`to_dict` 输出 `task_id` |
| `task_type` | `type` | design/check/report |
| `status` | `status` | 含扩展态，见 §5.2 |
| `record_id` | `record_id` | design→design_id；check→check record id；report→null |

---

## 5. API 契约变更（先行，改 `api-contracts/portfolio/tasks.md`）

> 契约先行原则：本节是实施第一步，实现时逐字段对照。

### 5.1 `GET /api/v1/portfolio/tasks/{task_id}` 响应补齐

现状实现只返回 7 个字段（缺 `type/stage/params/record_id`），补齐为标准响应：

```json
{
  "task_id": 39,
  "type": "design",
  "status": "completed",
  "progress": 100,
  "stage": "设计完成",
  "params": { "capital": 500000 },
  "result": { "...": "…" },
  "error_message": null,
  "created_at": "2026-07-31T06:00:00Z",
  "completed_at": "2026-07-31T06:04:00Z",
  "record_id": 222
}
```

### 5.2 状态枚举补充

契约 §2.3 状态列表由 `pending | running | completed | failed | cancelled` 扩展为：

| status | 含义 |
|--------|------|
| `pending` | 已创建，等待 worker |
| `running` | 执行中 |
| `quick_ready` | 组合方案已就绪（可先看方案），LLM 报告生成中 |
| `completed` | 完成（含 LLM 报告） |
| `completed_with_errors` | 方案完成但 LLM 报告失败/DB 保存失败 |
| `failed` | 失败（含启动收敛） |
| `cancelled` | 保留（当前无取消功能，预留） |

### 5.3 WS `task_update` 消息结构文档化

新增契约小节（`/ws/task-notifications`）：

```json
{
  "type": "task_update",
  "task_id": 39,
  "task_type": "design",
  "status": "completed",
  "progress": 100,
  "stage": "设计完成",
  "design_id": 222,
  "record_id": 222,
  "report_quality": "full"
}
```

- `record_id`：design/check 完成时必填（design 与 design_id 同值）。
- `task_type`（新增）：**WS 消息必须携带**，前端收到时若本地无该任务，可据此正确初始化任务类型与 label（当前实现缺此字段，check 任务会被 App.vue 自动建为 design 类型）。
- 前端约束：收到 `task_update` 即更新内存任务；`design_id`/`record_id` 用于跳转。

### 5.4 `GET /tasks` 与 `POST /design-async` / `strategy-check-async` 契约微调

- `POST` 端点契约不变（`task_id`/`status=pending` 已正确）。
- **limit 默认值统一（当前四处不一致：契约 §2.3 = 20 / 路由 `Query(10)` / 前端 `listTasks(10)` / manager 默认 20）**：S0 契约改为 `limit` 默认 **20**（与契约一致），路由实现 `Query(20, ge=1, le=50)`，前端 `listTasks` 默认同步为 20。

### 5.5 Checklist 更新

在 `tasks.md` 末尾追加：

- [ ] `GET /tasks/{id}` 返回 `type`/`stage`/`params`/`record_id`
- [ ] 任务列表在**后端重启后**仍返回（DB 持久化）
- [ ] design 任务 `record_id` 可关联 `GET /designs/{record_id}`
- [ ] check 任务 `record_id` 可关联 `GET /strategy-checks/{record_id}`
- [ ] WS `task_update` 完成时携带 `record_id`
- [ ] 状态枚举含 `quick_ready`/`completed_with_errors`

---

## 6. 后端改动清单（逐文件）

### 6.1 `backend/app/models/task.py`（新建）

见 §4.1。

### 6.2 `backend/app/database.py`

`init_db()` 增加 `from .models.task import TaskRecord`（与既有模型并列）。

### 6.3 `backend/app/tasks/task_manager.py`（核心重构）

**删除**: `_save()`、`_load()`、`_persist_path`、`DEFAULT_PERSIST_PATH`、JSON 读写、`_next_id`。

**改为 async 的方法**（签名保留，行为改 DB）：

```python
class TaskManager:
    # 保留期常量（替代原 prune 的 3600s TTL）
    RETENTION_TERMINAL_DAYS = 7          # 终态任务保留天数
    RETENTION_TERMINAL_MAX = 100         # 终态任务最大保留条数

    def __init__(self, persist_path: str | None = None, session_factory=None):
        if persist_path is not None:
            import warnings
            warnings.warn("[TaskManager] persist_path is deprecated (Z27: DB-backed); ignored", DeprecationWarning, stacklevel=2)
            logger.warning("[TaskManager] persist_path ignored (DB-backed since Z27)")
        # D10: 测试注入独立 SQLite 引擎；生产默认 async_session（惰性解析，见下）
        self._session_factory = session_factory  # None → 每次调用时取模块级 async_session
        # ⚠️ 惰性解析（M2 导入顺序地雷）：模块级单例 `task_manager = TaskManager()` 在
        #   task_manager.py:192 执行，而 `from app.database import async_session` 在 L258。
        #   若此处急切执行 `session_factory or async_session` 会 NameError → 模块 import 即崩。
        #   正确做法：方法内部 `sf = self._session_factory or async_session` 再使用，
        #   或把 async_session import 上移到文件顶部（推荐后者，与 D11 一致）。
        # 不再加载 JSON；不持有 _tasks/_next_id

    async def create_task(self, task_type: str = "design", params: dict | None = None) -> dict:
        # INSERT TaskRecord(status="pending", params_json=json.dumps(params or {}, ensure_ascii=False, default=str))
        # return record.to_dict()

    async def get_task(self, task_id: int) -> dict | None:
        # SELECT ... WHERE id=task_id; return record.to_dict() or None

    async def update_task(self, task_id: int, **kwargs) -> None:
        # 字段白名单: status/progress/stage/params/result/error_message/record_id
        #   params/result 为 dict → 序列化为 JSON 列（ensure_ascii=False, default=str，与既有写库风格一致）
        #   record_id 为 int → 写 record_id 列
        # status 为终态(completed/completed_with_errors/failed)时写 completed_at
        # UPDATE tasks SET ... WHERE id=task_id
        # 保留旧语义: kwargs 中值为 None 的字段不写（如 record_id=None 不覆盖既有值）

    async def list_tasks(self, limit: int = 20, offset: int = 0) -> list[dict]:
        # await self.prune_tasks()  # 用类默认保留期（RETENTION_TERMINAL_*），替代原 max(20, limit*2)/1h TTL
        # SELECT ... ORDER BY created_at DESC, id DESC LIMIT/OFFSET
        # 返回 [r.to_dict()]

    async def prune_tasks(self, max_count: int = 100, max_age_days: int = 7) -> int:
        # 删除策略（单条 SQL 完成，替代原内存剪枝）:
        #   DELETE FROM tasks
        #   WHERE status IN ('completed','completed_with_errors','failed')
        #     AND created_at < now - max_age_days
        #     AND id NOT IN (
        #       SELECT id FROM tasks WHERE status IN (...) ORDER BY created_at DESC LIMIT max_count
        #     )
        # 活跃任务（pending/running/quick_ready）永不清理
```

**`task_manager` 单例**：`task_manager = TaskManager()`（无 persist_path）。

**`_notify` 增强**（`task_manager.py` 顶层函数）：
- 参数增加 `record_id`（默认 None）；
- payload 增加 `record_id` **与 `task_type`**（M3：§5.3 契约要求 WS 消息携带 `task_type`，前端据此初始化任务类型/label；当前 `_notify` 无此字段，实现时从 `task` dict 的 `type` 取值）；
- `design_id` 推导逻辑保留（result 中的 design_id 或 extra）。

**`design_pipeline` 适配**（async 化调用）：
- 所有 `mgr.create_task/get_task/update_task` 加 `await`；
- 成功路径 Stage 6 与 `completed_with_errors` 路径，在写 result 的同时写 `record_id=design_id`：
  ```python
  await mgr.update_task(task_id, progress=100, status="completed",
                        result={...}, record_id=design_id)
  ```
- **空分配失败路径（当前 task_manager.py:355-377）必须补回写**：该路径先 `update_task(status="failed")`（`:355`）时 `design_id` 尚为 None（`:373` 才产生），随后直接 `return`，导致任务永远无法关联到已落库的 `portfolio_designs` 记录。修正（注意 **M8 顺序**：不能在 `:356` 的 `_notify` 里带 record_id，那时还没有；应在 `design_id = record.id` 之后、`return` 之前追加）：
  ```python
  await mgr.update_task(task_id, record_id=design_id)
  # 可选：再发一次 WS 通知携带 record_id（前端此时已显示 failed，补发仅用于同步任务面板的 recordId）
  ```
- `_notify(...)` 调用：成功/`completed_with_errors` 路径带 `record_id=design_id`；空分配路径按 M8 顺序在回写后补发。

### 6.4 `backend/app/tasks/worker_registry.py`

`dispatch()` 中 `manager.update_task(...)` 加 `await`（已是 async 函数）。

### 6.5 `backend/app/tasks/strategy_check_worker.py`

- `mgr.update_task/get_task` 加 `await`；
- 完成路径写 `record_id`（已有 `update_task(record_id=record_id)`，语义不变）；
- 本地 `_notify()`（现 L191-201）增加 `record_id` 与 **`task_type`（M3：= "check"）** 字段（从 `mgr.get_task(task_id)` 取，或调用方传入）；
- 失败路径保持 `failed` + error_message。
- 注意：该 worker 的 `_notify` 是文件内独立函数，与 `task_manager._notify` 是两份实现，两处都要改（§5.3 契约对两条推送通道统一要求）。

### 6.6 `backend/app/tasks/report_worker.py`

- `mgr.update_task/get_task` 加 `await`（report 无 DB 业务记录，`record_id=None` 不写）；
- 本地 `_notify` 不变（report 完成不需要 record_id，但 payload 统一带 `record_id: None` 亦可）。

### 6.7 `backend/app/tasks/design_tasks.py`

无需改动（re-export 兼容层；`register_worker("design", design_worker)` 不变）。

### 6.8 `backend/app/routers/portfolio.py`

| 端点 | 改动 |
|------|------|
| `GET /tasks/{task_id}` | `task = await task_manager.get_task(task_id)`；返回 `task` 全量 dict（含 type/stage/params/record_id）；404 语义保留 |
| `GET /tasks` | `return await task_manager.list_tasks(limit=limit, offset=offset)`；**limit 默认改 `Query(20, ge=1, le=50)`**（§5.4 统一） |
| `POST /design-async` | `t = await task_manager.create_task(...)`；`asyncio.create_task(design_worker(task_manager, t["task_id"]))` 不变 |
| `POST /strategy-check-async` | 同上 |
| `GET /strategy-check-result/{task_id}` | `task = await task_manager.get_task(task_id)`；其余不变 |

### 6.9 `backend/app/main.py`

**⚠️ 必须整体替换** main.py:314-340 现有 A04 `_cleanup_stuck_tasks` 实现（它直接读 `_tm._tasks` 私有 dict，DB 化后必然崩溃），不能并存。

```python
async def _cleanup_stuck_tasks():
    # 所有非终态任务（pending/running/quick_ready）→ failed
    # 原因: "后端重启，任务中断（未完成）"
    from datetime import datetime          # ← 函数内 import，main.py 顶层无此名
    from .models.task import TaskRecord
    from .database import async_session
    from sqlalchemy import select
    async with async_session() as db:
        stuck = (await db.execute(
            select(TaskRecord).where(TaskRecord.status.in_(["pending", "running", "quick_ready"]))
        )).scalars().all()
        for t in stuck:
            t.status = "failed"
            t.error_message = "后端重启，任务中断（未完成），请重新提交"
            t.completed_at = datetime.utcnow()
        if stuck:
            await db.commit()
            logger.info("[recovery] marked %d stuck task(s) as failed", len(stuck))
```

（放在现有 `_recover_stale_designs` 附近；lifespan 中 `await _cleanup_stuck_tasks()`。）

### 6.10 遗留文件处理

- `backend/data/tasks.json`：保留在磁盘（gitignored），但代码不再读写。删除动作可选（实施 PR 不强制删除文件本身，避免误删其他环境数据）。

---

## 7. 前端改动清单（逐文件）

### 7.1 `frontend/src/stores/task.js`

- `_normalizeTask(rt)` 增加：
  ```js
  recordId: rt.record_id || (rt.type === 'design' ? (rt.result?.design_id || rt.design_id || null) : null) || null,
  ```
- `updateTask` 终端态 toast 补充：`completed_with_errors` → warning toast「方案已完成但报告生成异常」；`quick_ready` 不进 toast（仍算进行中）。
- 其余不变（任务状态不写 localStorage，F6 已解决）。

### 7.2 `frontend/src/App.vue`（WS 消息处理）

`taskWs.onmessage` 中：

1. **自动建任务时带类型与正确 label**（当前缺 `task_type` 字段，check 任务会被误建为 design 且 label 恒为「智能组合设计」）：
   ```js
   if (!taskStore.getTask(taskId)) {
     const type = msg.task_type || 'design'
     const label = type === 'check' ? '策略检查与分析'
       : type === 'report' ? '市场研判报告' : '智能组合设计'
     taskStore.addTask(taskId, label, type)
   }
   ```
2. 处理 `record_id`：
   ```js
   if (msg.record_id || msg.design_id) {
     taskStore.updateTask(taskId, {
       recordId: msg.record_id || msg.design_id,
       ...(msg.design_id ? { designId: msg.design_id } : {}),
     })
   }
   ```

（保留既有 design_id fallback 分支；`getTask` fallback 补读 `record_id`。）

### 7.3 `frontend/src/components/TaskIndicator.vue`

`onClickTask(t)` 扩展：

```js
function onClickTask(t) {
  if (t.status === 'completed') {
    if (t.type === 'check' && t.recordId) {
      router.push('/portfolio-analysis')   // P1: 进入组合分析页（deep-link checkId 为 P2 延伸）
    } else if (t.designId) {
      router.push({ path: '/', query: { designId: String(t.designId) } })
    }
  }
  open.value = false
}
```

`is-clickable` 判定同步放宽为 `(t.status === 'completed' || t.status === 'completed_with_errors') && (t.designId || (t.type === 'check' && t.recordId))` —— `completed_with_errors` 的 design 任务同样携带合法 design_id（task_manager.py:491-503），应可点击直达。

补充（非阻塞小项）：`statusText()` 对 `quick_ready` 显示「方案已就绪」、`completed_with_errors` 显示「已完成（报告异常）」，避免原始英文态直出。

### 7.4 `frontend/src/views/DashboardAiTools.vue`（新发现：历史列表 ReferenceError）

**现状 bug（已核查，直接影响 Z27 症状「看不到报告/策略检查结果不显示」）**：
`loadHistoryList()` 第 509 行引用未定义的 `checks` 变量 —— `designHistoryList.value = [...runningTasks, ...designs, ...checks]`。`checks` 在该文件任何位置均未声明，每次打开历史 Tab 都抛 `ReferenceError: checks is not defined`（被 try/catch 吞掉 → toast「加载历史记录失败」→ 历史列表永远为空）。另 `designRes`/`checkRes`（497-498 行）为死代码。

**修复**：`/portfolio/timeline` 返回的 `data.items` 已合并 design+check（api-contracts/portfolio/timeline.md），直接使用即可：
```js
const items = (data.items || [])
// 移除 ...checks 引用与 designRes/checkRes 死代码
designHistoryList.value = [...runningTasks, ...items].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
```
前端测试补一条：`loadHistoryList` 渲染 timeline items 不抛错、check 项可点击加载 `getStrategyCheckDetail`。

---

## 8. 测试计划

### 8.1 后端单测

**新建 `backend/tests/test_task_db_persistence.py`**（Z27 专项，契约驱动）：

| 用例 | 断言 |
|------|------|
| `create_task` 落库并返回契约 dict（含 `task_id`） | `type/pending/progress/params` |
| `get_task` 返回全字段（含 `record_id` 默认 None） | to_dict 契约 |
| `update_task` 更新 status/progress/stage/record_id | 读回一致 |
| **重启恢复**：同 DB 两个 TaskManager 实例，`mgr2.get_task(1)` 仍有数据 | A1 |
| `list_tasks` 排序（created_at DESC）与分页 | 新任务在前 |
| 终态保留期内可列出；超期被 prune | D5 策略 |
| 活跃任务永不 prune | pending 存活 |
| `record_id` 关联：design → designs 表；check → strategy_check_records 表 | A2/A3（DB 层） |
| `to_dict` 时间戳 ISO 格式 | 契约 |
| 启动收敛：遗留 running → failed + error_message | A7（调用 main.py 清理逻辑或等价函数） |

**路由级（TestClient）**：
- `GET /tasks/{id}` 返回 11 字段（A4）；
- `GET /tasks?limit/offset` 分页；
- 不存在的 task → 404。

**WS 级**：mock `notify_manager`，断言 design/check 完成消息含 `record_id`（A6）。

**测试 DB 隔离（必须，否则直接红）**：
- `backend/conftest.py` 当前**没有任何建表 fixture**（仅有 HTTP 抑制 fixture），且开发库 `data/portfolio.db` **没有 `tasks` 表**（已核查 sqlite_master）——直接 `DELETE FROM tasks` 会 `OperationalError: no such table`。
- 方案：新增 **session 级 fixture `task_db`，放 `backend/tests/conftest.py` 或独立 `backend/tests/db_fixtures.py`（M4：不能放 `test_task_db_persistence.py` 内部**——§8.2 的 `test_design_pipeline_integration.py`/`test_design_tasks.py` 也需要同一测试库，pytest fixture 跨文件不可见）：
  1. `tmp_path` 下建独立 SQLite 测试库（`sqlite+aiosqlite:///{tmp}/test_tasks.db`）；
  2. 用 `create_async_engine` + `async_sessionmaker` 生成 `test_session_factory`，**建齐三张表（M5）**：`tasks` + `portfolio_designs` + `strategy_check_records`（`conn.run_sync(Base.metadata.create_all, tables=[TaskRecord.__table__, PortfolioDesign.__table__, StrategyCheckRecord.__table__])`）——A2/A3 的「record_id 关联」用例需要 design/check 表；
  3. 构造 `TaskManager(session_factory=test_session_factory)`（D10）供用例使用；
  4. 用例间 `DELETE FROM tasks`（表已存在，安全）或直接换新 tmp 库。
- **不共享开发库**：既有测试文件的行为不受影响（`tests/` 下实际 ~84 个 .py，含 conftest）；TaskManager 单测不再写 `data/portfolio.db`，避免污染真实数据与 dev server 文件锁竞争。

### 8.2 既有测试适配（结构性重写，不是「加 await 即可」）

> ⚠️ 独立审查发现：现有测试中 **MagicMock mgr 无法被 `await`**（`test_design_optimization_plan.py:313-315` 用 `task_mgr = MagicMock()` + `get_task.return_value = {...}`，pipeline 一旦 `await mgr.get_task()` 直接 TypeError）、**mock session 无 `execute/scalars`**（`test_design_pipeline_integration.py:47-74` `_make_mock_session` 仅 add/commit/refresh/get）、**task_id 硬编码为 1 而 mock refresh 返回 1001**。这三类必须**结构性重写**，不能靠机械加 `await`。

按 `git grep "task_manager\.\|TaskManager("` 核实的实际引用文件（排除仅注释提及者）：

| 文件 | 适配方式 |
|------|---------|
| `test_design_tasks.py` | mgr 构造换 `TaskManager(session_factory=test_session_factory)`；所有调用加 `await`；`task_id` 从 `create_task()` 返回值取（不硬编码）；`test_tasks_survive_manager_recreation` 改为同测试库两实例 |
| `test_design_pipeline_integration.py` | **结构性重写**：不再 mock `async_session` 当任务库；`mgr` 用真实测试库 TaskManager（D10），保留对 `app.tasks.task_manager.async_session` 的 patch（D11，管 pipeline 写 portfolio_designs）；`task_id=1` → 用 `create_task` 返回值；断言 target 从「task 内存 dict」改为「DB 读回」 |
| `test_design_optimization_plan.py` | P4/P6 的 `task_mgr = MagicMock()` 改 `AsyncMock`（`get_task`/`update_task` 均配 `return_value`/`side_effect` 为 coroutine），或改用真实测试库 mgr + mock 引擎；`await design_pipeline` 依赖的 mock 形态必须先行 |
| `test_phase0_7.py` | `mgr.create_task(...)` 加 `await`；`task["task_id"]` 从返回值取 |
| `test_strategy_check_async.py` | 同上 |
| `test_v5_diagnosis_fixes.py` | **点名 `test_task_manager_persist_path`（L24-40）**：它断言 `TaskManager.DEFAULT_PERSIST_PATH` 属性，§6.3 删除该属性后必 AttributeError —— 改写为「`tasks.json` 不再被创建/读写」（对应验收 A5），不再断言路径 |
| `test_design_status.py` | `task_id == 1` 断言删除（DB autoincrement 不保证 1）或断言改为「非空且递增」；`persist_path` 参数相关用例改写 |
| `test_phase1_diagnosis_fixes.py` / `test_phase5_architecture.py` / `test_solution_design_plan.py` / `test_report_quality.py` / `test_remaining_fixes.py` | 逐处 `grep "task_manager\."` 加 `await` + 构造调整（多为少量引用） |

> 原则：**断言目标不变（读回值语义一致），构造与调用形态重写**。先跑一遍现有 `pytest` 建立基线，再逐文件适配。

### 8.3 前端测试

- `taskStore.spec.js`：新增 `_normalizeTask` 的 `recordId` 映射用例（design 从 result.design_id；check 从 record_id）。
- `App.spec.js`：新增 WS 消息含 `record_id`/`task_type` → `updateTask(recordId)` + 自动建任务带类型 用例。
- `TaskIndicator` 相关用例：check 完成点击跳 `/portfolio-analysis`；`completed_with_errors` 带 design_id 可点击。
- `DashboardAiTools` 用例：`loadHistoryList` 用 timeline items 渲染不抛错（覆盖 §7.4 ReferenceError 修复）；check 项点击加载 `getStrategyCheckDetail`。

### 8.4 verify_e2e.py 补充

`section_task_persistence()`（新）：

1. `POST /design-async` → 轮询 `GET /tasks/{id}` 至 completed；
2. 断言响应含 `type/stage/record_id`，且 `GET /designs/{record_id}` 200；
3. `GET /tasks` 列表包含该 task 且带 `record_id`；
4. （可选，标记 skip）重启后端后重复 GET /tasks 验证持久化 —— 脚本内无法重启，此步留给手工验收 A1。

---

## 9. 实施顺序（每步含验证）

| 步骤 | 内容 | 验证 |
|------|------|------|
| S0 | 更新 `api-contracts/portfolio/tasks.md`（§5，含 limit 默认值统一 + WS `task_type` 字段） | review 契约 |
| S1 | 新建 `models/task.py` + `database.py` 导入 | `init_db` 后表存在 |
| S2 | 重构 `task_manager.py`（async + DB + `session_factory` 注入，D10/D11） | 新单测 PASS（独立测试库） |
| S3 | 适配 workers（design/check/report，含空分配 record_id 回写）+ registry + routers | 既有测试适配后 PASS |
| S4 | `main.py` 启动收敛（**替换** A04） | A7 单测 |
| S5 | 前端 taskStore / App.vue / TaskIndicator / DashboardAiTools(§7.4) | 前端单测 + build |
| S6 | verify_e2e 补充 + 全量回归 | `pytest`（先跑基线再改）+ `verify_e2e.py` + `npm test` + `npm run build` |
| S7 | 手工验收：提交设计 → 重启后端 → 任务仍在 → 点击直达方案 | A1/A2/A3 |

---

## 10. 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| 测试适配是结构性重写（MagicMock/mock session/硬编码 id），回归面大 | **高** | §8.2 三类重写模式已列明；S6 前先跑 pytest 基线；分文件提交；`asyncio_mode=auto` 已就绪；D10 注入真实测试库把 mock 面降到最低 |
| SQLite 并发写（progress 高频 update） | 低 | 每阶段一次写（非每毫秒）；引擎已有 `connect_args={"timeout": 30}`；如实测抖动，可对 progress 做节流（update_task 内合并 1s 内连续 progress）——列为可选优化，不阻塞主设计 |
| `task_manager` 单例在测试间共享状态 | 中 | 新测试用注入的测试库（§8.1），不碰全局单例；既有测试适配时避免对共享库写入 |
| 启动收敛把「用户刚提交、正排队」的任务误杀 | 低 | 提交与启动收敛不同时发生（收敛只在进程启动瞬间）；重启后原任务本就不可能继续执行，标记 failed 是正确语义 |
| `tasks.json` 残留文件造成误导 | 低 | 代码停止读写 + 文档说明；文件本身 gitignored |
| 前端 check 跳转 `/portfolio-analysis` 无 deep-link | 低 | P1 仅跳转页面；checkId deep-link 列为 P2 延伸，不阻塞主目标 |

---

## 11. 工作量估算

| 模块 | 估算 |
|------|------|
| 契约更新（S0） | 0.5h |
| 模型 + database（S1） | 0.5h |
| TaskManager 重构（S2，含 D10 注入） | 1.5h |
| workers/routers/lifespan 适配（S3-S4，含空分配 record_id 回写） | 1.5h |
| 前端适配（S5，含 §7.4 历史列表修复） | 1.5h |
| 测试：新单测 + **结构性适配既有测试** + e2e（S6） | **4h** |
| 手工验收（S7） | 0.5h |
| **合计** | **~9.5h（约 1.5 人日）** |

> v5 文档预估「修复: 2 小时」严重偏低 —— 未计入契约补齐、既有测试结构性重写（§8.2 三类模式）与前端历史列表 bug（§7.4）。

---

## 12. 决策记录（原待决问题 → 已定案）

| 问题 | 决策 | 理由 |
|------|------|------|
| 保留期参数 | **7 天 / 100 条**，列为 TaskManager 可配常量 | 有界增长；替代 1h TTL（「重启即空」直接元凶）；不阻塞任何功能 |
| `GET /tasks` 是否裁剪 result | **不裁剪，保持契约完整对象**（与现状行为一致） | 当前 `list_tasks` 已返回含 result 的完整 dict；契约 §2.3 即此形态；本地/局域网响应体数百 KB 可接受。将来如需优化再加 `?brief=1`（独立契约变更，不并入本方案） |
| check 任务 deep-link | **P1 只跳 `/portfolio-analysis`**；`?checkId=` 直达列为 P2 延伸 | `PortfolioAnalysis` 当前不消费 checkId query，P0 做 deep-link 需改该组件，超出 Z27 最小修复面 |
| `cancelled` 状态 | **保持契约预留**，不实现取消 API | 无此需求；枚举里保留不产生成本 |

---

## 13. 修订记录

| 版本 | 日期 | 修改 |
|------|------|------|
| v1.0 | 2026-07-31 | 初稿：DB 唯一真相源方案、TaskRecord 模型、契约变更、逐文件改动清单、测试计划 |
| v2.0 | 2026-07-31 | 第 1 轮独立审查修订：① 新增 D10（session_factory 注入）/D11（保持模块级 import）；② §8.1 测试 DB 隔离改为独立测试库 + 建表 fixture（原方案 DELETE 无表必红）；③ §8.2 改为结构性重写清单（MagicMock 不可 await / mock session 无 SELECT / task_id 硬编码三类模式）；④ §6.3 补空分配失败路径 record_id 回写；⑤ §6.9 明确替换 A04 + datetime import；⑥ §5.3 WS 契约补 `task_type`；⑦ §7.3 completed_with_errors 可点击；⑧ 新增 §7.4（DashboardAiTools `loadHistoryList` ReferenceError，独立核查发现）；⑨ §12 待决问题全部定案；⑩ 工作量 7.5h → 9.5h |
| v2.1 | 2026-07-31 | 第 2 轮终审（PASS）8 项 MINOR 全部落地：① `__init__` 补 `session_factory` 参数 + 惰性解析（M2 导入顺序地雷：单例在 L192、模块级 import 在 L258）；② §5.3/§6.3/§6.5 WS `task_type` 两端 `_notify` 双实现都要改；③ §6.3 空分配路径 M8 顺序（`:356` 通知时 design_id 未产生，回写后再补发）；④ §8.1 fixture 移至 conftest/db_fixtures.py 共享（M4）+ 建齐三张表（M5）+ 测试文件计数更正为 ~84（M6）；⑤ §8.2 点名 `test_task_manager_persist_path` 处置（M7）；⑥ §5.4/§6.8 limit 默认值统一为 20（契约/路由/前端） |

---

*（终版：已通过第 2 轮独立终审 — 达到实施标准）*
