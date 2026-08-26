# 巡检编排 patrol.py 设计方案（2026-08-19）

> **性质**：本文档为**纯工具脚本设计方案**，不实施。目标是把「每次改完代码人工全量重测」升级为「一条命令」，把人工从「测试员」降级为「审查员」。
> **依据**：AGENTS.md「反假完成机制」「性能软门禁」「设计流程」。本方案不涉及新 API 端点，故不走 api-contracts 流程（patrol.py 是 CLI 脚本，非 HTTP 接口）。
> **用户决策（2026-08-19）**：**不做定时巡检**（`--scheduled` 已从方案移除）。patrol 定位为开发循环内的手动命令，无人值守场景不在本轮范围。
>
> **✅ 实施状态（2026-08-26 核验）**：§6 三步全部落地——`backend/scripts/patrol.py`（751 行，
> §3 CLI 契约 14 项特征全实现，实际层集超出方案：追加 L-golden / L4-ruff / L2-startup）；
> 单测 `tests/test_patrol_orchestration.py` 33 passed；AGENTS.md「测试 / Testing」入口已加；
> `logs/patrol/latest.json` 有真实 `--full` 运行记录（exit=2 = 后端离线必需层 SKIP 语义正确）。
> 下文复选框为验收时的原始勾选状态。

---

## 0. 执行摘要

用**一个聚合脚本 `backend/scripts/patrol.py`** 编排项目现有巡检资产，并提供两种运行模式：

| 模式 | 命令 | 用途 |
|---|---|---|
| 全量 | `python scripts/patrol.py` | 交付前：pytest 全量 + verify_e2e 全量 + data_health_check + verify_perf + 静态门禁 + L5（npm test + build），即 **L1+L2(e2e+health)+L3+L4+L5** |
| 增量 | `python scripts/patrol.py --diff` | 日常开发：只跑本轮工作区改动涉及的层（秒~分钟级） |

**核心设计点**：
1. **分层编排**——单测回归（L1）/ 真实环境探活（L2）/ 性能软门禁（L3）/ 静态结构（L4）/ 前端（L5），各层独立可跳过，跳过必须**显式报告**、绝不静默算通过（反假完成）。
2. **退出码聚合**——`0` 全过 / `1` 硬门禁失败 / `2` 后端未启动致必需层跳过 / `3` 用法错误。性能超阈值仅登记台账（软门禁，`verify_perf.py` 既有语义）。
3. **`--diff` 复用 pre-commit 档位逻辑**（`.githooks/pre-commit:307-363`）但针对**工作区**（`git diff HEAD`，含 staged+unstaged），且补齐 pre-commit 不跑的 e2e/health/perf。
4. **报告物**——`logs/patrol/latest.json`（每次运行覆盖）+ 控制台摘要，供人眼快速定位失败层。

---

## 1. 背景与问题

### 1.1 现状：巡检资产已齐，但各自为战

项目已有健壮的巡检资产，但**分散、无统一入口**：

| 脚本 | 位置 | 层 | 现状 |
|---|---|---|---|
| pytest（2400 用例） | `backend/tests/` | L1 单测回归 | pre-commit 档位化触发 |
| verify_e2e.py | `backend/scripts/verify_e2e.py` | L2 真实环境 | `--module` / `--smoke` 手动调 |
| data_health_check.py | `backend/scripts/data_health_check.py` | L2 数据管道 | 手动跑，无窗口感知 |
| verify_perf.py | `backend/scripts/verify_perf.py` | L3 性能软门禁 | pre-commit 条件触发（改 perf 脚本才跑） |
| check_routes.py | `backend/scripts/check_routes.py` | L4 契约-路由 | pre-commit 触发 |
| check_engine_purity.py | `backend/scripts/check_engine_purity.py` | L4 结构 | pre-commit 触发 |
| smoke_startup.py | `backend/scripts/smoke_startup.py` | L2 启动冒烟 | pre-commit 触发 |
| npm test / build | `frontend/` | L5 前端 | pre-commit 触发 build |

### 1.2 问题

1. **人工全量重测成本高**：每轮改完，人工要点页面、跑多个脚本，几小时。
2. **pre-commit 只在提交时跑**，且**不跑 e2e / data_health / perf 全量**（perf 仅在改 perf 脚本时触发，`.githooks/pre-commit:370-380`）——开发循环中段（未提交）无反馈。
3. **无统一报告**：各脚本输出各自 stdout，失败项要靠人肉汇总。

### 1.3 目标

- 交付一个命令 `patrol.py`，把 L1-L5 串成一条可重复执行的「巡检流水线」。
- `--diff` 把反馈前置到开发循环中段，秒~分钟级。
- **不做定时巡检**（用户决策）：数据源漂移等需无人值守监控的场景不在本轮范围，留待后续按需评估。

---

## 2. 总体架构

```
patrol.py
├─ 参数解析（模式/层/超时/报告路径）
├─ 环境预检（backend 在线？frontend node_modules？git 仓库？）
├─ 层调度器（按模式选定层集合，逐层 subprocess 执行，捕获退出码+输出）
├─ 结果聚合（PASS/FAIL/SKIP/WARN 四级；perf 超阈值 → WARN 不 FAIL）
└─ 报告器（控制台摘要 + logs/patrol/latest.json）
```

**层定义**：

| 层 | 执行内容 | 触发条件 | 后端依赖 |
|---|---|---|---|
| L1-unit | `python -m pytest -n auto`（全量）或 `-x <affected 文件>`（增量，**无 xdist 串行**，对齐 pre-commit） | 后端逻辑/测试变更 | 无 |
| L2-e2e | `python scripts/verify_e2e.py [--module ...] [--host H] [--port P]`（透传 patrol 的 `--backend-host/--backend-port`） | 后端/契约变更；**探测失败直接 SKIP，不调 verify_e2e**（其 health 模块服务离线会 `sys.exit(1)`，verify_e2e.py:108-110） | **需在线** |
| L2-health | `python scripts/data_health_check.py` | 后端/数据源相关变更 | 无（进程内网络探针） |
| L2-smoke | `SMOKE_FAST=1 python scripts/smoke_startup.py`（自起 uvicorn 于 **18000** 端口，与在线 8000 后端不冲突，smoke_startup.py:33） | **仅 `--diff` 档 1**（后端 app 变更）——`--full` 不跑（后端在线时启动能力已被证明，且双实例共享 SQLite 有写锁风险） | 无（自起子进程） |
| L3-perf | `python scripts/verify_perf.py --base http://H:P`（patrol 的 host/port 组装成 `--base`） | 全量/后端变更 | **需在线** |
| L4-routes | `python scripts/check_routes.py` | 契约/路由变更 | 无 |
| L4-purity | `python scripts/check_engine_purity.py` | engine 变更 | 无 |
| L4-async | `python scripts/audit_async_blocking.py` | 后端 app 变更 | 无 |
| L5-frontend | `cmd /c "npm test"` + `cmd /c "npm run build"` | 前端 src 变更 | 无 |

**层独立性原则**：每层是独立 subprocess，`--layer unit,perf` 可显式选层；未选层不执行。**依赖不满足的层必须显式 SKIP 并计入报告**（如后端未启动 → L2-e2e/L3-perf 打 SKIP，退出码 2），**绝不静默跳过冒充通过**（对应 verify_e2e 的 S3 防豁免精神，`verify_e2e.py:2032-2037`）。

**触发条件语义**：上表「触发条件」针对 `--diff`/`--layer` 模式（按改动档位选层）；`--full` 模式**无视触发条件，无条件执行全部层**（交付前完整性优先）。

---

## 3. CLI 契约

```
python scripts/patrol.py [模式] [选项]

模式（互斥，默认 full）:
  --full        全量巡检（默认）：L1 全量 + L2(e2e+health) + L3 + L4 全量 + L5（**不含 L2-smoke**，见 §2 层定义）
  --diff        增量巡检：按工作区改动（git diff HEAD + untracked）选层，见 §4
  --smoke       快速冒烟：仅 L2-e2e --smoke + L2-health（交付中途速查）

选项:
  --layer L1-unit,L2-e2e,...   显式指定层（可组合）；覆盖模式默认层集——给了 --layer 则只跑显式层，
                                不再按档位映射展开（如 `--diff --layer L1-unit` 只跑 L1，忽略档 1 的 e2e）
  --module market,portfolio    覆盖 §4.3 映射的 e2e 模块（显式优先于映射；仅 L2-e2e 层生效）
  --backend-host HOST --backend-port PORT   后端地址（默认 localhost:8000）
  --timeout N                  单层 subprocess 超时秒（默认: 层各自默认值）
  --report-dir PATH            报告目录（默认 logs/patrol，项目根；§5）
  --no-frontend-build          增量模式跳过 npm run build（只跑 npm test）
  --start-backend              后端不在线时尝试拉起（直接起 uvicorn，非 start.ps1，见 §4.4）
  -v/--verbose                打印各层完整输出（默认只打印摘要+失败详情）

环境变量（透传，复用 pre-commit 语义）:
  SKIP_FRONTEND_BUILD=1（等价 --no-frontend-build，跳过 build 只跑 npm test）/
  SKIP_BACKEND_TESTS=1（跳过 L1-unit）... 与 pre-commit 同名；
  SKIP_MYPY 不适用（patrol 不编排 mypy——mypy 属 pre-commit 提交门禁，见 §8-1）
```

**退出码**：
- `0` 全过（WARN 允许，perf 超阈值不阻断）
- `1` 任一硬门禁层失败（pytest 失败 / e2e FAIL / health FAIL / build 失败）
- `2` 被选定的依赖后端的必需层（L2-e2e / L3-perf）因后端未启动被 SKIP（报警给调用方：巡检不完整）
- `3` 用法错误 / 环境不可用（非 git 仓库、node_modules 缺失等）

> 退出码 2 的「必需层」= 当前模式/`--layer` 实际选中的层中依赖后端者；显式 `--layer L1-unit` 时 L2/L3 未被选中，后端离线不影响退出码。

---

## 4. `--diff` 增量判定

### 4.1 改动来源

`git diff --name-only HEAD`（工作区 + 暂存区相对 HEAD 的**已跟踪**文件改动）+ `git ls-files --others --exclude-standard`（**未跟踪**新文件，如新测试/新模块/新脚本）并集去重。**两者缺一不可**——`git diff HEAD` 对 untracked 文件完全不可见，只靠它会漏检新增文件（新测试文件不触发档 2、新 router 不触发档 1r，都是假绿）。`--diff` 语义是「自上次提交以来改/增了啥」，不是「要提交啥」。

### 4.2 档位规则（对齐 pre-commit，`.githooks/pre-commit:307-363`）

按改动路径归类，取**各档位的并集**（同一批改动可能触发多层）：

| 档 | 改动路径 | 触发层 |
|---|---|---|
| 档 0 | `backend/tests/conftest.py`、`backend/tests/db_fixtures.py` | L1 全量 + L2-e2e 全量 + L2-health |
| 档 1 | `backend/app/*`（不限 .py）、`backend/scripts/*.py`、`backend/requirements.txt` | L1 全量 + L2-e2e（按 §4.3 映射选模块）+ L2-health + L3-perf + L2-smoke + L4-async |
| 档 1e | `backend/app/engine/*.py`、`backend/scripts/check_engine_purity.py` | 追加 L4-purity |
| 档 1r | `api-contracts/*`、`backend/app/routers/*.py` | 追加 L4-routes |
| 档 2 | 仅 `backend/tests/*.py`（且无档 0/1 命中） | 只跑 `-x <变更的测试文件>`（L1 子集），不跑 e2e |
| 档 3 | `frontend/src/*`、`frontend/index.html`、`frontend/vite.config.js`、`frontend/package.json` | L5（npm test + build） |
| 档 4 | 仅 `docs/*`、`diag/*`（非 api-contracts） | **不触发任何层**，打印「纯文档，跳过」 |

**关键语义**：
- 档 0/1 命中即触发 L2-e2e——但**模块集按 §4.3 映射选取**，不恒为全量：改 `routers/news.py` 只跑 news 域，改共享层/未知路径回退全量。收益：开发中段反馈从分钟级降到秒级、减少非交易时段环境性噪音（round29 §0.4 实证）、避免「狼来了」淹没真回归。
- 档 1 中 `backend/scripts/*.py` 变更（如改 verify_e2e 自身）不在 §4.3 表 A/B → 走**兜底全量** e2e（scripts 影响巡检工具链，保守全量；可用 `--module` 覆盖）。
- 档 2 只跑变更测试文件（秒级），**不因改测试文件触发全量 e2e**（测试变更不改变生产行为）。
- `frontend/public/*` 静态资源变更不触发 L5（对齐 pre-commit 的 build 触发条件）。
- `--diff` 模式下若后端未启动：L2-e2e / L3-perf 打 SKIP 并提示 `--start-backend` 或 `restart.bat`，退出码 2（§3）。档 1 仍执行 L1/L2-health/L2-smoke 等不依赖后端在线的层。

### 4.3 改动模块 → e2e 子模块映射

**设计原则（防映射过时假绿）**：路由层精确、共享层宽集、未知路径回退全量——**宁可多跑不漏测**。e2e 模块全集见 `verify_e2e.py:2110-2133` + `:2459-2467` + `:2572`。

**表 A：路由层（精确）**——router 变更直接对应其业务域：

| 改动路径 | e2e 模块集 | 依据（该 router 端点被哪些 e2e section 断言） |
|---|---|---|
| `routers/market.py` | `market, search, sectors, indicator-quality, fundamentals, db-integrity, encoding, hk-market, us-market, 5xx, round19-boundary, quality` | section_market(indices)、section_search/hk/us、check_sector_data、section_indicator_quality、section_fundamentals、section_db_integrity(watchlist)、section_encoding、section_api_5xx_check、section_round19_boundary、check_data_quality(search/etfs) |
| `routers/portfolio.py` | `portfolio, resilience, task, task-persistence, design-quality, diversity, round19-boundary` | section_portfolio、section_async_resilience、section_task_status/persistence、section_design_quality_gate、section_solution_diversity_check、section_round19_boundary |
| `routers/news.py` | `news, 5xx, encoding` | section_news、section_api_5xx_check(headlines)、section_encoding |
| `routers/analysis.py` | `analysis, llm` | section_analysis（stream 四端点）、section_llm_import |
| `routers/factors.py` | `factors, factor-integrity, factor-thresholds, factor_ic, zscore` | section_factors(active/ic)、section_factor_integrity、section_factor_thresholds、section_factor_ic、section_factor_zscore_check |
| `routers/admin.py` | `admin, circuit-breaker, factor-integrity, llm, quality` | section_admin、section_circuit_breaker、section_factor_integrity、section_llm_import、check_data_quality(admin/config 候选池段) |
| `routers/system.py` | `health` | section_health(warmup) |
| `routers/ws.py` | `ws, nginx-proxy` | section_ws、section_nginx_proxy |

**表 B：共享层（宽集/全量）**——被多 router 引用，静态无法精确，宁宽勿漏：

| 改动路径 | e2e 模块集 | 依据（被哪些 router/task 引用，实测 grep） |
|---|---|---|
| `services/market_service.py`、`services/market_data_hub.py`、`services/hub/*` | **全量** | 被 market/analysis/admin/news/ws 五 router + 5 个 tasks（design_report/market_refresh/news_refresh/sector_refresh/task_manager）引用，影响横切所有域 |
| `services/portfolio_service.py`、`services/portfolio/*` | `portfolio, resilience, task, task-persistence, design-quality, diversity, round19-boundary` | 被 portfolio router（全部组合域端点）+ strategy_check_worker 引用——与 portfolio router 的 e2e 域一致（§4.3 表 A portfolio 行） |
| `services/strategy_design.py` | `portfolio, design-quality, diversity, task, task-persistence, resilience` | 被 task_manager/design_report 引用，组合设计域（含异步任务链） |
| `services/llm_context.py` | `analysis, llm` | 仅 analysis router 引用 |
| `fetchers/*`、`factors/*`、`engine/*`、`tasks/*`、`core/*` | **全量** | 数据源/引擎/任务横切多域，静态不可推断 |
| 其它 `backend/app/**`（未知路径） | **全量** | 兜底规则：未匹配即全量，防映射滞后漏测 |

**实现约定**：映射表作为 `patrol.py` 内模块级常量 `E2E_MODULE_MAP`（dict，路径 glob → module 集，key 带 `*` 通配）。新增 e2e section 或 router 时需同步维护；`check_routes.py` 已守护「路由↔契约」一致性，映射表在此之上只做**选测**不做**门禁**——映射不完整的最坏后果是多跑（时间），不是漏跑（假绿）。

### 4.4 后端在线探测与拉起

与 pre-commit perf 段一致（`.githooks/pre-commit:374`）：`socket.create_connection(('localhost', 8000), timeout=2)`（host/port 取 patrol 的 `--backend-host/--backend-port`，默认 localhost:8000）。探测结果三态：
- **在线** → L2-e2e / L3-perf 正常执行
- **离线 + 未传 `--start-backend`** → L2-e2e / L3-perf 打 **SKIP（带 reason）**，不调用 verify_e2e（其 health 模块离线会 `sys.exit(1)`，verify_e2e.py:108-110 会误报硬失败而非 SKIP），退出码 2（§3）
- **离线 + 传了 `--start-backend`** → **直接起 uvicorn**（`cd backend && python -m uvicorn app.main:app --host :: --port {patrol 的 --backend-port}`，后台、stdout 重定向到 `logs/backend_stdout.log`，复用 start.ps1:37 的命令模板）——**不用 start.ps1**（它总是连带启动前端 vite，start.ps1:51-54，超出巡检需求），然后按健康检查窗口轮询 `/health`（对齐 start.ps1 的 90s 窗口）。拉起失败或超时 → 该层 SKIP + 退出码 2。

---

## 5. 报告格式

`logs/patrol/latest.json`：

```json
{
  "timestamp": "2026-08-19T15:30:00+08:00",
  "mode": "full",
  "duration_s": 42.3,
  "exit_code": 0,
  "layers": {
    "L1-unit":   {"status": "PASS", "passed": 2400, "failed": 0, "duration_s": 90.1, "detail": ""},
    "L2-e2e":    {"status": "PASS", "checks_total": 128, "checks_failed": 0, "skipped": ["nginx"], "duration_s": 25.4},
    "L2-health": {"status": "PASS", "checks_total": 9, "checks_failed": 0, "duration_s": 12.0},
    "L3-perf":   {"status": "WARN", "warnings": ["watchlist 3.4s > 3.0s (known debt)"], "duration_s": 8.2},
    "L4-routes": {"status": "PASS", "detail": "73 routes consistent", "duration_s": 1.1},
    "L4-purity": {"status": "PASS", "detail": "engine pure", "duration_s": 0.4},
    "L4-async":  {"status": "PASS", "detail": "no async blocking", "duration_s": 1.0},
    "L5-frontend":{"status": "SKIP", "reason": "no frontend change in --diff mode"}
  }
}
```

**状态语义（四级）**：
- `PASS` — 该层全部断言通过
- `FAIL` — 硬门禁失败 → 退出码 1
- `SKIP` — 依赖不满足（后端离线 / 纯文档 / L5 无前端变更）→ **必须带 reason**；必需层 SKIP → 退出码 2
- `WARN` — 软门禁超阈值（perf）或非阻断提示 → 不影响退出码

---

## 6. 实施清单（分步，可验收）

> 本方案只设计不实施；以下为后续实施时的分步计划与验收标准。

### Step 1：`backend/scripts/patrol.py` 骨架
- [x] 参数解析（§3 CLI）+ 层注册表（§2 表格）+ 退出码约定（§3）
- [x] `--full` 模式打通：逐层 subprocess，捕获退出码/stdout 尾部/耗时，聚合报告
- [x] **验收**：后端在线时 `python scripts/patrol.py --full` 退出码 0；人为制造 pytest 失败 → 退出码 1；`--layer L1-unit` 只跑 L1

### Step 2：`--diff` 增量模式
- [x] 档位判定（§4.2）+ e2e 子模块映射（§4.3，`E2E_MODULE_MAP` 常量）+ 后端在线探测/拉起（§4.4，含「探测失败直接 SKIP 不调 verify_e2e」分支）
- [x] `--start-backend` 拉起逻辑（直接起 uvicorn + `/health` 轮询，见 §4.4）
- [x] `--module` 覆盖映射、`--layer` 覆盖档位的优先级逻辑
- [x] **验收**：
  - 只改 `docs/patrol-orchestration-plan.md` → 不触发任何层
  - 只改 `backend/tests/xxx.py` → 只跑该文件，不跑 e2e
  - **新增** `backend/tests/test_new_module.py`(untracked) → 只跑该新文件（档 2，验证 §4.1 的 `git ls-files --others` 分支）
  - 改 `backend/app/routers/market.py` → L1 全量 + e2e（**market 域 12 模块**，见 §4.3 表 A）+ health + routes + async
  - 改 `backend/app/routers/news.py` → e2e 只跑 `news, 5xx, encoding`（非全量）
  - 改 `backend/app/services/market_data_hub.py` → e2e **全量**（表 B 共享层兜底）
  - 改 `backend/app/fetchers/xxx.py`（新增未知路径）→ e2e 全量（兜底规则）
  - 后端离线 + 无 `--start-backend` → L2-e2e/L3-perf 显式 SKIP、退出码 2、不误报为硬失败
  - `--diff --module news`（改动为 market.py）→ 跑 news 模块（显式覆盖映射）

### Step 3：收尾
- [x] `verify_e2e.py` 既有结果：确认 patrol 透传 `--module` 无冲突
- [x] 在 AGENTS.md「测试 / Testing」节补一行：`python scripts/patrol.py --diff` 作为日常循环入口
- [x] 单测：`backend/tests/test_patrol_orchestration.py`（mock subprocess，断言档位判定/退出码聚合/报告结构——**不跑真实 subprocess**）
- [x] **验收**：全量 pytest 绿 + `patrol.py --full` 全 PASS + 一次真实 `--diff` 走查

---

## 7. 设计检查清单对照（AGENTS.md 设计流程必查 8 项）

| # | 检查项 | 本方案结论 |
|---|---|---|
| 1 | **可行性探针** | 全部编排对象（verify_e2e / data_health_check / verify_perf / smoke_startup / check_routes / npm test）均已在项目运行并接入 pre-commit——编排可行性的核心假设（各脚本可独立执行、退出码可用）已由 `.githooks/pre-commit` 各段反复验证。新增点：`git diff HEAD` 档位判定为纯本地逻辑，实施时以 Step 验收用例覆盖。 |
| 2 | **证据链** | §1.1 表格列各脚本 `file:line`；§4.2 引用 pre-commit 档位段 `.githooks/pre-commit:307-363`；§4.3 映射表列 router 端点被哪些 e2e section 断言（依据 verify_e2e 各 section 实际命中端点）；§4.4 引用 `.githooks/pre-commit:374`。 |
| 3 | **验证窗口** | 本方案**不做定时巡检**（用户决策），故无交易窗口分支；`--diff`/`--full` 均为开发态手动行为，验证窗口责任仍由既有脚本与验收流程承担（D3 不因本方案新增盲区）。 |
| 4 | **非兜底数据** | patrol 自身**不产生业务数据**，只编排与聚合。关键防假点：层依赖不满足必须 SKIP（带 reason）+ 退出码 2，禁止「假装全过」（对齐 verify_e2e S3 防豁免，`verify_e2e.py:2032-2037`）；报告 status 语义显式区分 PASS/FAIL/SKIP/WARN，perf 超阈值是 WARN 不是 PASS。 |
| 5 | **真实调用点** | patrol.py 调用点：开发者命令行（`--full`/`--diff`/`--smoke`）+ AGENTS.md「测试 / Testing」入口文档。均为真实入口；不接入任何前端/后端运行时。 |
| 6 | **四态 UI** | 不适用（CLI 脚本，非前端组件）。控制台等价物：层 PASS/FAIL/SKIP/WARN 显式标注 + 失败详情必打 + `-v` 全量输出。 |
| 7 | **复杂度审计** | patrol 新增的进程调用仅 subprocess（本地进程，非外部服务），全部带超时（`--timeout`，默认值见各层：pytest 1800s、e2e 900s、health 120s、perf 120s，对齐 pre-commit 的 timeout 兜底哲学 `.githooks/pre-commit:333-337`）；无循环内 IO、无外部网络调用；报告写文件为单次写。 |
| 8 | **已知问题模式** | 对照 round14 §4 盲区表 5 类：①格式断言——patrol 不新增业务断言，仅聚合既有断言；②mock 理想输入——L2 层全部跑真实环境，无 mock；③契约盲区——L4-routes 在档 1r 覆盖，补 pre-commit 之外的手动触发入口；④CSS 零覆盖——L5 含 build + npm test，非仅 build；⑤降级无门禁——SKIP 必须带 reason + 退出码 2，杜绝「静默降级冒充通过」。 |

---

## 8. 已知边界与不做什么

1. **不替代 pre-commit**：pre-commit 是提交时硬门禁（`git diff --cached`），patrol 是开发循环中段的日常巡检（`git diff HEAD`）。两者互补，不合并。mypy / secret 扫描 / API 调用覆盖等**提交语义门禁不在 patrol 编排范围**（pre-commit 专属）。
2. **不做定时巡检 / IM 推送**（用户决策）：patrol 定位为手动命令，无人值守监控与告警机制不在本轮范围。
3. **不新增测试文件泛滥**：patrol 自身单测 1 个文件（`test_patrol_orchestration.py`），计入 P3-6 基线（`check_test_baseline.py`，基线 210；当前实际 220，P3-6 已降级为提示不阻断，新增 1 个不影响提交）。
4. **不改变 verify_e2e 等既有脚本行为**：patrol 只 subprocess 调用，不透传任何会改变其语义的参数（仅 `--module` 白名单透传）。
5. **后端自动拉起 `--start-backend`**：默认不自动拉（避免巡检副作用），显式传参才拉；拉起直接起 uvicorn（非 start.ps1，避免连带前端 vite）。
6. **`--full` 不含 L2-smoke**：启动冒烟仅在 `--diff` 档 1（后端 app 变更）触发——后端在线时启动能力已被证明，且双实例共享 SQLite 有写锁风险。

---

## 9. 验收标准汇总（DONE 判定）

1. **功能正确**：§6 各 Step 验收用例全过。
2. **反假完成 reality check**：
   - 真实调用点：`rg "patrol.py"` 命中 AGENTS.md「测试 / Testing」入口文档；
   - 非兜底：`--full` 在真实环境输出真实层状态（非恒 PASS）；人为断网时 L2-health FAIL 且退出码 1；
   - 内容断言：报告 JSON 字段齐全、status **四级**语义正确、SKIP 必带 reason；
   - 映射正确性：§4.3 表 A/B 每条映射与 verify_e2e 实际 section 命中端点一致（review 时已逐一核对，含 quality 横切模块补入 market/admin 行）；
   - 引用同步：`rg "verify_e2e|data_health_check"` 旧调用点不受影响；
   - 四态等价：PASS/FAIL/SKIP/WARN 全部有控制台与 JSON 呈现。
3. **全量测试绿**：pytest 全量（2400）+ 前端 npm test + build。
4. **性能软门禁**：`--full` 自身编排开销可忽略（subprocess 启动 ~100ms/层），不新增热点路径。
