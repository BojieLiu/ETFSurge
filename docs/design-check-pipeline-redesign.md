# 组合设计与策略检查全链路分析与重构方案

**版本:** v1.2  
**日期:** 2026-07-24  
**状态:** ✅ **已实施**（2026-07-24 在 commit `4ff6084` 中落地）  
**实施说明:** 参见 `docs/implementation-master-plan.md` § Phase 1.0。所有 3 个 Phase（核心修复 + 架构清理 + 测试防护）均已完成。关键 commit: `4ff6084`（管道重构）+ `7e93321`（前端 report_quality 状态驱动）。12 文件改动，588 行新增。  
**审阅记录:** 并行架构评审（4 条 MAJOR + 4 条 MINOR）+ 代码验证（1 条 ERROR + 5 条 MISSING）— 全部已整合至 v1.1，v1.1 已全部实施  
**范围:** 从用户点击「开始设计」/「策略检查」到前端展示结果的全链路

---

## 摘要

智能组合设计和策略检查两条任务链路存在三个致命的「沉默错误」—— bug 被异步 fire-and-forget 和空日志吞噬，UI 展示错误信息但任务状态却标记为成功。本次审查发现了 8 个结构性问题（1 个 bug + 7 个架构缺陷），并设计了无历史包袱的重构方案：用 **顺序 Pipeline 替代 fire-and-forget、统一超时来源、引入报告质量分级、DB 原子写入、WS 驱动的 UI 状态同步**。方案已在 DB 事实数据和 E2E 测试结果上得到验证。

---

## 第一章：现状分析

### 1.1 智能组合设计——当前调用链

```
用户点击「开始设计」
                                                          后 台
  │                                                        │
  │→ POST /api/v1/portfolio/design-async                   │
           │→ portfolio_design_async()                      │
           │   task_manager.create_task("design")            │
           │   asyncio.create_task(design_worker(task_id))   │  (返回 202)
           │← 202 {task_id}                                 │
  │                                                        │
  │                                      Worker 启动        │
  │                                      │                  │
  │                                      ├─ Stage A: generate_enhanced_design(150s timeout)
  │                                      │    ├─ pool_manager.refresh(30s timeout)
  │                                      │    ├─ pool_manager.get_factor_matrix()
  │                                      │    ├─ pool_manager.get_pool("core"|"satellite"|"defense")
  │                                      │    ├─ engine.allocate()         ← 纯函数，无 I/O
  │                                      │    ├─ engine.rationale.build_rationale()
  │                                      │    └─ engine.risk_controls.apply_risk_controls()
  │                                      │
  │                                      ├─ Stage B: DB Save (strategies)
  │                                      │    INSERT PortfolioDesign(
  │                                      │      strategies_json = ...,
  │                                      │      design_text      = NULL,  ← 此时为空
  │                                      │      status           = "completed")
  │                                      │    → design_id = record.id
  │                                      │
  │                                      ├─ Stage C: asyncio.create_task(  ← FIRE-AND-FORGET
  │                                      │     _generate_and_save_report())
  │                                      │
  │                                      ├─ task_manager.update_task(      ← 立即标记完成
  │                                      │    status = "completed")          (不等报告)
  │                                      │
  │                                      │
  │  (WS 通知: completed)                 │  [后台协程: _generate_and_save_report()]
  │                                      │     ├─ _build_plan_tables(strategies)
  │  (5s 轮询)                            │     ├─ pool_manager.get_market_sentiment()
  │  │→ GET /tasks/{id}                   │     │     ✘ NameError — pool_manager 未 import
  │  │← {status: "completed"}             │     │
  │  │→ GET /designs/{design_id}          │     └─ DB SAVE 永远不会走到
  │  │← {design_text: ""}                 │        (异常被第227行 catch 吃掉)
  │                                        │
  │  (60s 后 reportStale 为 true)          │  报告写入：从未成功
  │  显示：「📄 完整报告暂不可用            │  日志输出：stdout → 隐藏 cmd 窗口
  │          LLM 报告未能完成」
```

从 ID 176 到 180 的五条设计记录 `design_text` 列全为 NULL，证实 `_generate_and_save_report` 从未成功执行过一次。

### 1.2 策略检查——当前调用链

```
用户点击「策略检查」

  │→ POST /api/v1/portfolio/strategy-check-async
           │→ strategy_check_async()
           │   asyncio.create_task(strategy_check_worker(task_id))
           │← 202

                                     Worker
                                      │
                                      ├─ strategy_check(240s timeout)
                                      │    ├─ 数据采集 (30s)
                                      │    │    ├─ _compute_indicators(symbols)
                                      │    │    └─ factor_registry.compute(symbols)
                                      │    │
                                      │    ├─ generate_strategy_check_report(45s timeout)  ← 外层
                                      │    │    └─ llm_complete_with_system(provider.timeout=120s)  ← 内层
                                      │    │        45s 到达 → TimeoutError
                                      │    │
                                      │    ├─ catch TimeoutError
                                      │    │    return {summary: "LLM 分析超时..."}  ← 部分结果
                                      │    │
                                      │    ├─ DB SAVE: StrategyCheckRecord(...)
                                      │    └─ task_manager.update_task(status="completed")  ← 视为成功
                                      │
  (3s 轮询)
  │→ GET /strategy-check-result/{id}
  │← {status: "completed", summary: "LLM 分析超时，基于 N 只标的因子数据...", suggestions: []}

  显示「策略检查完成」但仅有数据摘要，无 LLM 分析
```

注：E2E 测试在 `strategy-check-async` 的 POST 请求级别就超时（30s），说明数据采集环节本身就超过了 30s。

### 1.3 E2E 测试证据（34/42 PASS，8 FAIL）

关键失败项：

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `design_text 已持久化` | **FAIL** — 空 | ID 178 的设计记录 design_text 为 NULL |
| 异步设计超时 (60s) | **FAIL** | 数据采集超过 60s |
| POST /strategy-check-async | **FAIL** — 请求超时 (30s) | 数据采集阶段超时 |
| GET /news/headlines | **FAIL** — 超时 (35s) | 新闻接口慢 |
| GET /news/macro | **FAIL** — 500 | 宏观新闻端点崩溃 |
| 异步最终验证 /health | **FAIL** — 超时 | 后端在重压无响应 |

---

## 第二章：结构性问题清单

### #2.1 Bug — `pool_manager` NameError（致命，P0）

**位置：** `backend/app/tasks/task_manager.py:200`

```python
async def _generate_and_save_report():
    try:
        from app.tasks.design_report import _build_plan_tables
        from app.analysis.llm import generate_design_report

        plan_tables = _build_plan_tables(strategies)
        market_sentiment = pool_manager.get_market_sentiment() if ...  # ← NameError
```

`pool_manager` 在该模块的任意作用域均未被 import。`_generate_and_save_report` 在调用 LLM **之前**就崩溃了。异常被 `except Exception as e:`（227 行）捕获，仅输出日志到不可见的 stdout。

**证据：** `data/portfolio.db` 中 ID 176–180 的 `design_text` 列全为 NULL。

### #2.2 Fire-and-Forget 反模式（架构，P0）

```python
# task_manager.py:230
asyncio.create_task(_generate_and_save_report())

# task_manager.py:247 — 仅 17 行后
mgr.update_task(task_id, progress=100, status="completed")
```

主 Worker 不等待 LLM 报告完成就标记了 task 成功。后果：
- **UI 永远拿不到报告**——前端在 design_text 写入 DB 之前就 fetch 了
- **失败无声**——报告生成异常只输出日志，不更新 task 状态，前端完全不知情
- **无法重试**——task 已 `completed`，没有触发重新生成的机制
- **E2E 无法检测**——`verify_e2e.py` 只检查 `bool(design_text)`，而 fallback 数据摘要非空也能通过

### #2.3 三层超时互相倾轧（架构，P1）

```
design_worker 外层 asyncio.wait_for(generate_enhanced_design, timeout=150s)  ← 杀策略引擎
                                                                               (不含 LLM 报告)
  └─ _generate_and_save_report 外层 asyncio.wait_for(generate_design_report, 120s)
       └─ llm_complete_with_system per-provider timeout=120s         ← 实际 LLM 等待
          └─ 2 个 provider 依次尝试，每个 120s ＝ 最多 240s！          ← 外层 120s 杀早了

strategy_check: asyncio.wait_for(generate_strategy_check_report, 45s)  ← 外层 45s
  └─ llm_complete_with_system per-provider timeout=120s                ← 内层 120s
     45s 到达时内层永远等不到结果
```

- **外层 120s** 包裹内层 **240s**（2 providers × 120s each）——provider 尚在重试就被外层杀掉
- **策略检查**同理：外层 45s 掐掉内层 120s provider wait——从未等到 LLM 正常返回
- 注意 `generate_enhanced_design` 的 150s 超时不保护 LLM 报告（报告在 fire-and-forget 中异步运行）

### #2.4 任务状态与用户体验分离（P1）

Task 的 `status: "completed"` 不等于用户拿到了有用结果：
- 设计任务：策略 OK / 报告缺失 → 仍然 `completed`
- 策略检查：数据 OK / LLM 超时 → 仍然 `completed`

缺少对结果质量的分类语义。用户看到的是「任务成功」但内容残缺。

### #2.5 无事务原子性（P2）

```python
# 第一步：design_worker 写入 (task_manager.py:174-187)
async with async_session() as db:
    record = PortfolioDesign(strategies_json=..., design_text=NULL)
    db.add(record)
    await db.commit()
    design_id = record.id

# asyncio.create_task 切换协程调度 …

# 第二步：_generate_and_save_report 写入 (task_manager.py:221-225)
async with async_session() as db:
    d = await db.get(PortfolioDesign, design_id)
    d.design_text = report_text
    await db.commit()
```

两步分属不同协程、不同事务、不同 DB 会话。若第二步崩溃（如当前 NameError），design_text 永久丢失。

### #2.6 前端时序不感知后端真实状态（P2）

前端的 `reportStale`：
```js
const designReportStale = computed(() => {
  return Date.now() - new Date(designResult.created_at).getTime() > 60_000
})
```

这是一个**硬编码 60s 猜测**，与 LLM 报告的实际完成时间完全无关：
- LLM 10s 完成 → 前端仍等满 60s 才显示
- LLM 110s 完成 → 前端在 60s 时已切到错误提示，即使报告随后已就绪

没有后端驱动的「报告已就绪」通知。

### #2.7 测试全部停在引擎层（P2）

```
层级             现有测试集              覆盖率
──────────────────────────────────────────────────
engine/          test_design_optimization_plan   ✅ 已覆盖
(纯函数)         test_design_cascade_failure

task_worker      test_design_tasks               ⚠️ 只在 mock 层面
(task_manager)                                     测到设计返回

_generate_and_   —                                0%
save_report

strategy_check   —                                0%
_worker

E2E              verify_e2e.py                    ⚠️「有内容即通过」
(真实网络)                                        不区分 LLM vs 数据摘要
```

### #2.8 日志不可见（P3）

- `.env` 无 `LOG_FILE` 配置 → backend 日志只输出到 stdout
- `start.ps1` 用 `Start-Process -WindowStyle Hidden` → stdout 被丢弃
- 当前排查完全依赖 DB 取证和代码推理，无实时日志可供翻阅

---

## 第三章：重构设计

### 3.1 设计原则

1. **顺序 Pipeline** — 消灭 `asyncio.create_task`。Worker 跑完所有阶段后一次性标记结果，每个阶段通过 WS 推送进度。
2. **优雅降级** — LLM 失败不影响策略方案可用。引入 `report_quality: full | fallback | none` 清晰分级。
3. **DB 原子写入** — 策略 + 报告在一次 DB commit 中完成。不可能出现"有方案无报告"。
4. **单层超时** — provider 自身的 timeout 是唯一超时来源。删除所有嵌套 `asyncio.wait_for`。
5. **后端驱动 UI** — WS 推送"报告已就绪"事件。前端不再靠定时器猜测。
6. **测试覆盖全链路** — mock pool_manager 和 LLM，真实验证 Worker 调度、DB 落盘、WS 通知。

### 3.2 新 Pipeline：设计任务

```
POST /api/v1/portfolio/design-async
  │
  └─ design_pipeline(task_id, params)    ← 一个 Worker 函数，5 个顺序阶段
      │
    ├─【Stage 1: DATA  (progress 0→30%)  ⏱ 超时 30s】
    │    asyncio.wait_for(pool_manager.refresh(), timeout=30)  ← 可失败 → 用缓存
    │    pool_manager.get_factor_matrix()                       ← 有缓存
    │    pool_manager.get_pool(layer)                           ← 空池→返回 error
    │    → WS push: {stage:"数据采集", progress:30}
    │
    ├─【Stage 2: ENGINE  (progress 30→60%)  ⏱ 超时 10s】
    │    engine.allocate(candidates, factor_matrix, regime)
    │    engine.rationale.build_rationale()
    │    engine.risk_controls.apply_risk_controls()
    │    → 得到 3 strategies（防御/平衡/进攻）
    │    → WS push: {stage:"策略计算", progress:60}
    │
    ├─【Stage 3: DB WRITE (progress 60→75%)  ⏱ 超时 5s】
    │    plan_tables = _build_plan_tables(strategies)
    │    INSERT PortfolioDesign(
    │      strategies_json,
    │      design_text     = plan_tables,     ← 立即写入数据摘要
    │      report_quality  = "pending",        ← 标注报告待生成
    │      status          = "completed")
    │    COMMIT                                ← 一次事务
    │    → WS push: {stage:"方案已保存", progress:75}
    │
    ├─【Stage 4: LLM REPORT (progress 75→95%)  ⏱ 超时 150s（provider 兜底）】
    │    try:
    │        llm_text = generate_design_report(
    │            strategies=strategies,
    │            market_context=market_context,
    │            plan_tables=plan_tables)
    │        UPDATE design_text = plan_tables + "\n\n## 二、市场环境与配置建议\n\n" + llm_text
    │        UPDATE report_quality = "full"
    │        UPDATE report_generated_at = now()
    │    except TimeoutError:
    │        UPDATE report_quality = "fallback"   ← 保持数据摘要
    │    → WS push: {stage:"报告完成", progress:95}
    │
    └─【Stage 5: NOTIFY (progress 95→100%)  ⏱ 超时 5s】
         task_manager.update(status="completed",
                             result={design_id, report_quality})
         → WS push: {type:"task_update", status:"completed",
                      design_id, report_quality}  ← 复用现有 task_update 通道
```

**前端流程变更：**
- Stage 3 的 WS push 触发前端 `fetchDesignDetail()` → 立即展示方案卡片 + 数据摘要
- Stage 5 的 WS push 表明报告就绪 → 前端切换到完整报告 tab
- 轮询回退保持（3s），但不再依赖 60s stale 猜测
- `report_quality` 决定 UI 显示：
  - `"full"` → 完整报告
  - `"fallback"` → 数据摘要 + "LLM 报告未能完成，原因：超时"
  - `"none"` → 设计失败

### 3.3 新 Pipeline：策略检查

```
POST /api/v1/portfolio/strategy-check-async
  │
  └─ strategy_check_pipeline(task_id, params)
      │
      ├─【Stage 1: DATA (progress 0→40%)】
      │    并行采集：因子分 + 技术指标 + regime
      │    → WS push: {stage:"数据采集", progress:40}
      │
      ├─【Stage 2: LLM (progress 40→80%)】
      │    generate_strategy_check_report(
      │        market_data, factor_breakdowns, regime)
      │    → WS push: {stage:"AI分析", progress:80}
      │
      ├─【Stage 3: DB (progress 80→95%)】
      │    INSERT StrategyCheckRecord(...)
      │    COMMIT
      │    → WS push: {stage:"报告已保存", progress:95}
      │
      └─【Stage 4: NOTIFY (progress 95→100%)】
           task_manager.update(status="completed")
           → WS push: {type:"task_update", status:"completed",
                        record_id, report_quality}
```

### 3.4 超时策略：per-stage + provider 双保险

| 层级 | 新超时 | 理由 |
|------|--------|------|
| **Stage 1: DATA** (设计) | 30s per-stage | pool_manager.refresh 可能卡在外部 API |
| **Stage 2: ENGINE** (设计) | 10s per-stage | 纯函数，10s 足矣（实际 <1s） |
| **Stage 3: DB** (设计) | 5s per-stage | 单个 INSERT，不应对此超时 |
| **Stage 4: LLM** (设计) | Provider 自身 150s | 不额外包裹 asyncio.wait_for |
| **Stage 5: NOTIFY** (设计) | 5s per-stage | WS 推送 |
| Provider (opencode_zen) | **90s**（原 120s） | 单 provider 有 90s 完成报告；双 provider failover ≤150s |
| Provider (deepseek) | **60s**（原 120s） | fallback provider，可短一些 |
| 策略检查数据采集 (Stage 1) | 30s per-stage | 因子+指标并行 |
| 策略检查 LLM (Stage 2) | Provider 自身 60s | 策略检查 prompt 较设计报告小，60s 足够 |
| **设计 pipeline 预估** | ≈170s（30+5+5+150+5） | 含 20s 缓冲 |
| **前端任务超时** | 保持 180s | 有 10s 缓冲 |

**设计原则：**
- 每阶段有独立 `asyncio.wait_for` 保护——防止任一阶段挂死拖垮整个 pipeline
- LLM 阶段（Stage 4）不自加 `asyncio.wait_for`，完全由 provider timeout 和 failover 机制保护
- 策略检查同理：数据采集 keep 30s 外层，LLM 去掉 45s 外层
- 单 provider 场景（OpenCode Zen 有 key 但 DeepSeek 无 key）：90s 足够生成设计报告
- 整体 pipeline 无需外层 150s/240s 包裹——各阶段超时 + provider failover 构成完整的保护链

### 3.5 DB 模型扩展

**PortfolioDesign 新增字段：**

```python
class PortfolioDesign(Base):
    # … 现有字段 …
    report_quality = Column(String(16), default="pending")
    # "pending" | "full" | "fallback" | "none"
    report_generated_at = Column(DateTime, nullable=True)
```

**API 返回扩展：**

```json
GET /api/v1/portfolio/designs/{id}
{
  "id": 180,
  "strategies": [...],
  "design_text": "# ETF 组合设计方案\n...",   // 始终非空
  "report_quality": "full",                     // 前端以此判断 UI 状态
  "report_generated_at": "2026-07-24T10:30:01Z"
}
```

### 3.6 文件改动清单

| 文件 | 改动类型 | 预计行数 |
|------|---------|---------|
| `backend/app/tasks/task_manager.py` | 重构: `design_pipeline()` 替代 `design_worker` + `_generate_and_save_report` | ~200 改动 |
| `backend/app/tasks/strategy_check_worker.py` | 重构为 `strategy_check_pipeline()` | ~100 改动 |
| `backend/app/config.py` | `llm_primary_timeout=90, llm_fallback_timeout=60` | ~2 |
| `backend/app/analysis/provider.py` | default timeout: primary 90, fallback 60 | ~1 |
| `backend/app/models/portfolio_design.py` | +`report_quality`, +`report_generated_at` + DB migration（ALTER TABLE） | ~15 |
| `backend/app/routers/portfolio.py` | `/design-async` 调用新 pipeline；/designs/{id} 返回 report_quality | ~15 |
| `backend/app/routers/ws.py` | 无需改动（Stage 5 复用现有 `task_update` 通道，App.vue 已支持 `design_id`） | ~0 |
| `backend/app/services/strategy_design.py` | 移除 `pool_manager.refresh()` 的 30s 外层 timeout（由 pipeline Stage 1 接管） | ~3 |
| `backend/app/services/portfolio_service.py` | 移除 `generate_strategy_check_report` 的 45s 外层 `asyncio.wait_for` | ~3 |
| `backend/.env` | +`LOG_FILE=logs/backend.log`，+`LOG_LEVEL=DEBUG` | ~2 |
| `frontend/src/views/DashboardAiTools.vue` | 移除 `reportStale` computed；前端 State 从 `report_quality` 推导 | ~30 |
| `frontend/src/components/design/DesignResult.vue` | 三态：full/fallback/none | ~20 |
| `backend/app/main.py` | 添加启动时 `report_quality="pending"` 记录恢复任务（见 §3.7） | ~20 |
| **测试新增** | 5 个 pipeline 集成测试 + 1 个 E2E 升级 | ~300 |
| **合计** | | ~730 |

### 3.7 崩溃恢复：`report_quality="pending"` 记录

**问题：** Stage 3 写 `report_quality="pending"` + COMMIT，Stage 4 更新为 `full`/`fallback`。若进程在 Stage 3 后 Stage 4 前崩溃（OOM kill / 服务器重启），记录永久停留在 `"pending"`。

**解决：** 在 `main.py` 的 `lifespan` 启动时增加恢复任务：
```python
# 扫描 report_quality="pending" 且创建时间 >5min 的设计记录,
# 将其标记为 report_quality="fallback"
async def _recover_stale_designs():
    stale = await db.execute(
        select(PortfolioDesign).where(
            PortfolioDesign.report_quality == "pending",
            PortfolioDesign.created_at < datetime.utcnow() - timedelta(minutes=5)
        )
    )
    for design in stale.scalars().all():
        design.report_quality = "fallback"
    await db.commit()
```

前端收到 `report_quality="fallback"` 后展示数据摘要 + 提示 "报告生成失败（服务器重启），方案数据仍可用"。

---

## 第四章：测试防护设计

### 4.1 新增集成测试

**文件：`backend/tests/test_design_pipeline_integration.py`**

```python
# 1. test_pipeline_full_success
#    mock: pool_manager 各 get_, generate_design_report → 固定文本
#    verify: task.status="completed", report_quality="full", design_text 含 LLM 分析

# 2. test_pipeline_llm_timeout
#    mock: generate_design_report → TimeoutError
#    verify: task.status="completed", report_quality="fallback",
#            design_text 是数据摘要（非空）

# 3. test_pipeline_empty_pool
#    mock: pool_manager.get_pool → []
#    verify: task.status="failed", error_message="无候选标的"

# 4. test_pipeline_db_atomic
#    mock: DB commit 中途失败
#    verify: 现有的已成功 task 不受影响

# 5. test_pipeline_ws_notify
#    mock: WS connection
#    verify: 至少收到 4 次 progress push + 1 次 completed
```

**文件：`backend/tests/test_strategy_check_pipeline.py`**

```python
# 同模式覆盖策略检查全链路
```

### 4.2 E2E 测试升级

**文件：`backend/scripts/verify_e2e.py`**

```python
# 改: "design_text 已持久化" 从 bool 检查 → 检查长度>200 且包含"市场环境"
# 改: 异步设计等待 60s → 180s
# 增: 检查 report_quality 字段存在且值为 "full" 或 "fallback"
# 增: 策略检查超时回退 → 30s 请求超时 → 改为异步模式（POST 立即 202，poll 等待）
```

---

## 第五章：实施路线（已实施）

> ⚠️ 以下路线图已于 2026-07-24 在 commit `4ff6084` 中全部完成。保留为架构记录，不再作为待办。

```
Phase 1  — 核心修复（本次 1 天）              ✅ 已实施
─────────────────────────────────────────────
P1.1  修复 pool_manager NameError           task_manager.py:200
       → 从 market_context 取 market_sentiment，不调 pool_manager
P1.2  _generate_and_save_report 改为       task_manager.py:193-230
       design_worker 内 await (不 fire-and-forget)
P1.3  Provider timeout: primary 90s,       config.py + provider.py
       fallback 60s（原均为 120s）
P1.4  验证修复：重启后端后手动触发设计      restart.bat
       → 跑 E2E 确认 design_text 非空       verify_e2e.py --module portfolio
       (保留现有 asyncio.wait_for 直到 Phase 2 重建 pipeline)
       ⚠️ 永久日志修复：.env +LOG_FILE      .env

Phase 2  — 架构清理（本周）
─────────────────────────────────────────────
P2.1  新 design_pipeline() 函数            task_manager.py (+120)
       (含 per-stage 超时：30s/10s/5s/150s/5s)
P2.2  新 strategy_check_pipeline() 函数     strategy_check_worker.py (+100)
P2.3  report_quality 字段 + DB migration    models/portfolio_design.py
       + 崩溃恢复 (main.py lifespan)
P2.4  Router 适配新 pipeline                portfolio.py
P2.5  删除旧 asyncio.wait_for               task_manager.py:209
       (LLM 层) + portfolio_service.py:455   portfolio_service.py:455

Phase 3  — 测试 + 前端（本周）
─────────────────────────────────────────────
P3.1  5 个 pipeline 集成测试                tests/
P3.2  前端 report_quality 适配 + 移除        DashboardAiTools.vue
      reportStale 硬编码                     DesignResult.vue
P3.3  E2E 断言升级                          verify_e2e.py
```

---

## 附录 A：E2E 测试失败列表（2026-07-24）

| 检查项 | 状态 | 详细 |
|--------|------|------|
| `design_text 已持久化` (ID 178) | FAIL | design_text 为空 (0 chars) |
| `异步设计超时 (60s)` | FAIL | 数据采集超时 |
| `POST /strategy-check-async` | FAIL | 请求 30s 超时（数据采集阶段） |
| `GET /strategy-checks` | FAIL | Read timeout (10s) |
| `GET /news/headlines` | FAIL | 请求超时 (35s) |
| `GET /news/macro` | FAIL | HTTP 500 |
| `异步最终验证 /health` | FAIL | 超时（后端忙） |
| 其余 34 项 | PASS | — |

## 附录 B：涉及的核心文件

| 文件 | 角色 |
|------|------|
| `backend/app/main.py` | 启动恢复 + lifespan |  
| `backend/app/tasks/task_manager.py` | Task 生命周期 + design_worker |
| `backend/app/tasks/strategy_check_worker.py` | 策略检查 Worker |
| `backend/app/services/strategy_design.py` | 策略引擎编排器 (generate_enhanced_design) |
| `backend/app/services/pool_manager.py` | 数据管道：候选池 + 因子矩阵 + 市态 |
| `backend/app/services/portfolio_service.py` | strategy_check 核心逻辑 |
| `backend/app/engine/allocation_engine.py` | 纯函数分配器 |
| `backend/app/engine/budgets.py` | 层预算 + 市态调整 |
| `backend/app/engine/rationale.py` | 入选理由生成 |
| `backend/app/engine/risk_controls.py` | 风控约束 |
| `backend/app/analysis/llm.py` | LLM: generate_design_report, generate_strategy_check_report |
| `backend/app/analysis/provider.py` | LLM provider 配置 + timeout |
| `backend/app/analysis/runtime.py` | AgentRuntime: 系统 prompt + 重试 |
| `backend/app/analysis/registry.py` | Agent 注册表 |
| `backend/app/routers/portfolio.py` | 设计/策略检查 REST 路由 |
| `backend/app/routers/ws.py` | WebSocket 路由 + ConnectionManager |
| `backend/scripts/verify_e2e.py` | E2E 验证脚本 |
| `frontend/src/views/DashboardAiTools.vue` | 设计/检查 UI 主流程 |
| `frontend/src/components/design/DesignResult.vue` | 报告 tab 展示 |
