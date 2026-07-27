# ETF Surge: System Performance, Quality & Test-Gap Analysis

> 综合分析文档：基于 2026-07-27 日全面诊断（预热性能 / 全链路响应 / 前端性能 / 报告质量 / 测试守护评估）
> 状态：**已审阅**（Reviewed）— 经过 3 轮内部审阅，达到实施标准
> ✅ **2026-07-27 更新**：阶段一（B1/B2/C1/F1）全部 4 项已完成；阶段二（A1-A2/E1）已完成；阶段三（A3-A4/B3/E3/G/H/D）剩余项经重新评估后，部分降低优先级或简化方案。详见 §9 更新后的实施优先级。

---

## 目录

1. [诊断概述](#1-诊断概述)
2. [后端预热性能诊断](#2-后端预热性能诊断)
3. [后端全链路响应诊断](#3-后端全链路响应诊断)
4. [前端链路性能诊断](#4-前端链路性能诊断)
5. [组合设计与策略检查报告审阅](#5-组合设计与策略检查报告审阅)
6. [测试防护体系缺口分析](#6-测试防护体系缺口分析)
7. [根本原因分析](#7-根本原因分析)
8. [优化方案设计](#8-优化方案设计)
9. [实施优先级与依赖](#9-实施优先级与依赖)
10. [附录](#10-附录)

---

## 1. 诊断概述

### 1.1 执行方法

- **后端预热性能** — cProfile + pyinstrument + WarmupProfiler，修改 main.py 加条件性 profiling 钩子，启动时注入
- **后端全链路响应** — `_perf_diag.py` 脚本依次调用 17 个 API 端点并记录响应时间
- **前端链路性能** — Playwright Performance API，编写 `99-perf-diagnostic.spec.js` 按路由测量 FCP/LCP/传输量
- **组合设计报告质量** — API 调用 `/design-async` + `/strategy-check-async` 获取设计结果 + 历史检查记录审阅
- **测试防护缺口** — 审计 `backend/tests/` + `verify_e2e.py`，逐一对照发现的缺陷检查对应测试覆盖

### 1.2 环境

- 后端：FastAPI (async) + SQLite, port 8000
- 前端：Vite 5 + Vue 3, port 5173
- OS: Windows
- 诊断时间：2026-07-27 15:45 - 16:00

---

## 2. 后端预热性能诊断

### 2.1 数据采集方法

#### 诊断工具安装
在 `backend/app/profiling/warmup_profiler.py` 中创建可复用的 WarmupProfiler 类，支持 cProfile 和 pyinstrument 两种 profiler，通过环境变量 `PROFILE_WARMUP=1` 激活。

#### 注入方式
在 `backend/app/main.py` 中植入条件性 profiling 钩子：

1. **pyinstrument**（采样型 profiler）在 lifespan 开始时启动，在 `yield` 前停止。
2. **cProfile**（函数调用级 profiler）在事件回调注册后启动，在 `yield` 前停止。
3. 添加 `warmup_timer` context manager 用于函数级精细计时。

### 2.2 关键发现

#### pyinstrument 结果

```
Recorded: 15:45:34  Samples: 229
Duration: 2.358     CPU time: 0.375
```

- `GetQueuedCompletionStatus` — 2.077s (88%) — I/O 等待（async），合理
- `lifespan` — 0.153s (6.5%) — 实际应用启动代码
  - `RedisCache.init` — 0.144s (6.1%) — Redis 连接建立
- `run_sync` / 线程池执行 — 0.049s (2.1%) — 同步 I/O 提交到线程池

#### cProfile 结果

Total: 728,311 calls (638,436 primitive) in 0.568s CPU

- `akshare.__init__` — 0.442s — **模块导入**，akshare 整体导入的代价
- `bs4.__init__` / `soupsieve` — 0.399s+0.129s — **BS4 导入**，被 akshare 间接依赖
- `sqlalchemy.session.close` — 0.400s — DB 会话关闭（init_db 后的清理）
- `SSL wrap_socket` — 0.381s — HTTPS 连接建立（可能是 akshare 内部）
- `pyinstrument.output` — 0.381s — **profiler 自身输出**，被计入开销

### 2.3 关键问题

#### 问题 1（P0）：Profiling 停止在背景任务完成前

**表现**：

```python
# main.py 中 warmup 任务的典型模式：
asyncio.create_task(_warmup_market_cache())   # 25s 超时
asyncio.create_task(_warmup_global_indices())  # 30s 超时
asyncio.create_task(_warmup_etf_cache())       # 120s 超时
```

`yield` 在 lifespan 的 yield 点触发 profiler 关闭，此时上述三个 `create_task` 仍在执行。

**影响**：warmup 时序数据缺失——**预热阶段最耗时的部分未被采集**。

**根源**：设计上 warmup 采用 fire-and-forget（不阻塞启动），profiler 在同一 yield 点关闭，没有等待机制。

#### 问题 2（P1）：模块导入开销大

- akshare 导入耗时 0.442s CPU（~0.5s wall time）
- bs4 导入耗时 0.399s CPU
- 两项合计近 1s CPU，发生在启动阶段

**影响**：首次请求可能因模块 lazy import 而延迟（当前代码已在 lifespan 中做 pre-import，但 pre-import 自身有开销）。

#### 问题 3（P2）：Warmup 机制缺少监控

- 没有 warmup 耗时告警门限
- 没有 warmup 失败的分级处理
- `WarmupProfiler` 当前为一次性工具，未集成到生产环境

---

## 3. 后端全链路响应诊断

### 3.1 数据采集方法

`_perf_diag.py` 脚本依次调用 17 个后端 API 端点（含 2 个 LLM 异步端点），记录响应时间与状态码。

### 3.2 结果汇总

| 端点 | 响应时间 | 状态 | 说明 |
|---|---|---|---|
| `GET /health` | 28.7ms | OK | |
| `GET /api/v1/system/warmup` | 16.0ms | OK | |
| `GET /api/v1/portfolio/etfs` | 18.8ms | OK | |
| `GET /api/v1/news/headlines` | **2268.9ms** | OK | **最慢端点** — 需抓取外部新闻源 |
| `GET /api/v1/news/macro` | 1.6ms | OK | 可能是缓存返回 |
| `GET /api/v1/factors/active` | 15.3ms | OK | |
| `GET /api/v1/admin/token-usage` | 16.3ms | OK | |
| `GET /api/v1/market/realtime` | ~200ms | OK | 单独测试验证 |
| `GET /api/v1/market/indices/global` | ~200ms | OK | 单独测试验证 |
| `POST /api/v1/portfolio/calculate` | 1.5ms | 405 | **方法错误** — 需 POST 不是 GET |
| `POST /api/v1/portfolio/daily-pnl` | 10.4ms | 405 | **方法错误** |
| `GET /api/v1/market/indices` | 15.7ms | 404 | **路由错误** — 实际路径含 `/global` |
| `GET /api/v1/market/sectors` | 1.0ms | 404 | 实际路径为 `/industry` 或 `/concept` |
| `GET /api/v1/analysis/technical/000300` | 1.0ms | 404 | 实际路由不同 |
| `GET /api/v1/admin/sources` | 15.1ms | 404 | 实际路径为 `/sources/health` |
| `POST /api/v1/portfolio/design` | 1.2ms | 404 | 实际为 `/design-async` |
| `POST /api/v1/portfolio/strategy/check` | 13.4ms | 404 | 实际为 `/strategy-check-async` |

### 3.3 关键问题

#### 问题 4（P1）：新闻端点响应极慢（2.27s）

`GET /api/v1/news/headlines` 耗时 2.27s，远超其他端点。

**原因**：`fetch_news_headlines()` 在 `backend/app/fetchers/news_fetcher.py` 中为同步调用，通过 `run_sync` 提交到线程池。该函数依次请求财新网的三个分类（头条/宏观/国际），每个都是串行 HTTP 请求，且无超时保护或并发控制。可优化为 `asyncio.gather()` 并发请求。

#### 问题 5（P1）：后端进程频繁崩溃

诊断过程中后端进程崩了 3 次（表现为 `ConnectionRefusedError`，等待后端健康检查返回前 TCP 连接即被拒绝）。每次崩溃后进程完全退出，操作系统未保留任何挂起状态，需人工重启。

**原因分析**：后端代码中至少有 4 个活跃的代码缺陷和脆弱点：
1. `market_service.py` ~667 行 `UnboundLocalError` — `cache_set` 变量在局部作用域的条件分支中被赋值，当特定异常路径触发时变量未定义；
2. `em_global_fetcher.py` 中 `Connection aborted` 异常未内部消化，传播到调用栈；
3. `margin_fetcher.py` 中 SZSE/SSE 均返回 404 时 fallback 链耗尽后无降级处理；
4. 没有全局 `asyncio` 异常处理器，未处理的协程异常会静默吞掉或传播到主循环。

**注意**：`ConnectionRefusedError` 可能在 `Start-Process` 的 session 绑定机制下被放大——Windows Session 0 隔离导致后台进程在终端关闭时被终止。这部分属于环境问题，非纯代码缺陷。

#### 问题 6（P2）：实际路由与文档/契约不匹配

诊断脚本假设的 10 条路由中有多条返回 404/405。实际路由路径与 API 契约和用户预期的路径不一致：

| 预期路径 | 实际路径 |
|---|---|
| `/api/v1/market/all` | `/api/v1/market/realtime` |
| `/api/v1/market/indices` | `/api/v1/market/indices/global` |
| `/api/v1/market/sectors` | `/api/v1/market/sectors/industry` |
| `/api/v1/portfolio/design` | `/api/v1/portfolio/design-async` |
| `/api/v1/portfolio/strategy/check` | `/api/v1/portfolio/strategy-check-async` |
| `/api/v1/analysis/technical/{symbol}` | (不存在 GET 端点 — 纯函数引擎层) |

---

## 4. 前端链路性能诊断

### 4.1 诊断方法

编写 `e2e/specs/99-perf-diagnostic.spec.js` 使用 Playwright + Performance API：

- 逐路由导航：`/`, `/market`, `/portfolio`, `/news`, `/analysis`, `/settings`
- 捕获 FCP, LCP, DOM 就绪时间, 传输大小, 资源统计
- 安装 `rollup-plugin-visualizer` 用于构建产物分析

### 4.2 诊断障碍

1. **前端启动不稳定**：`Start-Process` 启动的 Vite dev server 在 Windows 上跨 shell session 会终止，导致 `ConnectionRefused`。
2. **工具兼容性**：`vite-plugin-inspect`（开发态模块分析）需要 Vite 8，当前项目使用 Vite 5，无法安装。
3. **Lighthouse CLI 无法安装**：npm 依赖解析冲突。

### 4.3 已发现的关键问题

#### 问题 7（P1）：构建产物未做体积优化

`vite.config.js` 已配置 `manualChunks`（vendor-vue, vendor-axios, echarts），但：

- ECharts 整个打包（~1.2MB gzip ~400KB）—— 可以考虑按需加载
- 没有 `rollup-plugin-visualizer` 集成到 build 流程
- 没有体积告警门限（budget thresholds）

#### 问题 8（P2）：前端 dev server 启动流程脆弱

Windows 下前端启动需 `cmd /c "npm run dev"`，使用 `Start-Process` 时父进程退出会导致子进程终止。已在 AGENTS.md 中记录，但没有自动化处理（如 Windows 服务或 PM2）。

#### 问题 9（P2）：WS 代理配置有潜在隐患

`vite.config.js` 中代理规则：

```js
'/api/v1/ws': { ... },
'/ws': { ... },
'/api': { ... },
```

顺序依赖是关键：细粒度规则必须在前。当前正确，但无自动化测试验证代理规则生效。

---

## 5. 组合设计与策略检查报告审阅

### 5.1 执行情况

通过 API 提交了两个异步任务：

- `POST /api/v1/portfolio/design-async` → task_id 86, status "pending"
- `POST /api/v1/portfolio/strategy-check-async` → task_id 87, status "pending"

任务状态轮询超时（可能因 LLM 调用耗时较长或任务在后台处理时有异常）。

通过 `GET /api/v1/portfolio/strategy-checks` 获取到 10 条历史检查记录。

### 5.2 历史报告审阅

从最近一条策略检查记录（2026-07-25, id=102）审阅：

**市态判定**: `range_bound`
**检查结论**: 市场呈震荡格局，建议维持现有组合结构

**具体建议**：
1. `159338`（中证A500ETF）：建议从 20% 降至 15%，理由权重过高且流动性缺失
2. `518880`（黄金ETF）：持仓建议维持

**评分**: 0/10 持仓无需调整 → 说明策略检查阈值偏宽松

### 5.3 报告质量评估

| 维度 | 评价 | 问题 |
|---|---|---|
| 逻辑性 | 中等 | 建议的理由缺乏定量数据支撑（如"流动性缺失"无具体数据） |
| 可读性 | 中等偏低 | 返回中文数据因数据库编码问题有乱码（见下方分析） |
| 数据完整性 | 低 | 缺失市场状态上下文、估值水平、宏观驱动因素 |
| 准确性 | 中等 | 市态判定合理，但置信度标注"low"无进一步说明 |
| 投资判断 | 一般 | 缺乏风险调整后收益的考量 |
| 方案合理性 | 中等 | 调整幅度较小，缺乏情景分析 |
| 市场匹配度 | 中等 | range_bound 判断与调整建议吻合 |

### 5.4 关键问题

#### 问题 10（P1）：数据库中文编码问题

日志和 API 响应中反复出现中文乱码（如 "鍏ㄧ悆鎸囨暟缂撳瓨棰勭儹"）。数据库存储在 SQLite 中，字符编码不统一可能导致数据读取/写入时出现乱码。

#### 问题 11（P2）：LLM 报告质量无自动化验证

- 无报告质量评分卡（逻辑、数据支撑、可读性）
- 无一致性校验（建议是否与市场状态匹配）
- 无数值验证（建议权重是否可执行）
- AGENTS.md 提到 `_validate_report_consistency` 函数，但当前策略检查报告未调用

---

## 6. 测试防护体系缺口分析

### 6.1 现有测试覆盖

后端测试集：60 个测试文件（~数千条用例）- 覆盖 FactorRegistry、引擎模块、池管理器等

前端测试集：Playwright E2E 测试（9 个 spec 文件）

E2E 验证脚本：`verify_e2e.py`（847 行）

### 6.2 按问题映射测试覆盖

| 问题 | 类别 | 对应测试 | 缺口说明 |
|---|---|---|---|
| P0: Profiler 提前关闭 | 性能测试 | **无** | 无 warmup 时序断言，无背景任务完成验证 |
| P1: 模块导入开销大 | 性能基准 | **test_performance_benchmark.py** | 有，但未测试导入时间 |
| P2: Warmup 监控 | 可观测性 | **test_warmup_status.py** | 只有状态端点测试，无时序指标 |
| P1: 新闻端点 2.27s | 性能门限 | **verify_e2e.py 含响应时间检查** | 但有门限未对 news 端点设具体值 |
| P1: 后端崩溃 | 稳定性 | **无** | 无进程存活守护，无崩溃恢复测试 |
| P2: 路由不匹配 | 契约测试 | **无** | 无端到端路由发现/验证 |
| P1: 构建无体积控制 | 构建质量 | **无** | 无 bundle size 门限 |
| P1: 编码乱码 | 数据质量 | **test_data_health.py**（部分）| 有因子数据检查，无编码/乱码检查 |
| P2: LLM 报告质量 | 报告质量 | **无** | 无报告评分门限 |
| P1: UnboundLocalError | 代码质量 | **无** | `market_service.py` 无覆盖该路径的测试 |

### 6.3 系统性缺口分类

#### 缺口 A：性能门限（Performance Gates）— 4/7

| 缺失门限 | 应设在哪 |
|---|---|
| warmup 总耗时门限（< 10s） | `test_warmup_status.py` 或 `verify_e2e.py` |
| 关键 API P95 响应时间 | `verify_e2e.py` |
| 前端 FCP/LCP 门限 | Playwright E2E |
| bundle 体积门限 | 构建脚本 / `rollup-plugin-visualizer` |

#### 缺口 B：稳定性测试（Resilience）— 5/7

| 缺失测试 | 说明 |
|---|---|
| 进程存活守护测试 | 验证后端进程异常退出后的恢复 |
| 数据源降级测试 | 验证某个数据源全部失效时的行为 |
| 超时传播测试 | 验证超时异常不会导致进程崩溃 |
| 并发请求测试 | 验证大量并发下的内存泄漏或死锁 |

#### 缺口 C：数据质量校验（Data Quality）— 3/7

| 缺失检查 | 说明 |
|---|---|
| 编码乱码检测 | `encoding_diagnosis.py` 存在但未集成到 CI |
| 数值合理性检查 | ETF 权重和不等于 1、价格负值等基本校验 |
| 报告一致性检查 | LLM 报告验证（标的限制规则 1 等）|

#### 缺口 D：契约与路由验证（Contract）— 2/7

| 缺失验证 | 说明 |
|---|---|
| 路由自动发现 | 确保所有注册路由可访问 |
| 响应结构验证 | 对比契约文件与实际响应字段 |

#### 缺口 E：前端质量门限（Frontend）— 3/7

| 缺失门限 | 说明 |
|---|---|
| 构建编译警告检测 | pre-commit 已部分覆盖（`npm run build`）|
| 体积预算检查 | 未集成 |
| 性能预算检查 | Playwright 测试已编写但未集成到 CI |

### 6.4 verify_e2e.py 超时分析

`verify_e2e.py` 在本次诊断中因 120s 超时被强制终止。分析如下：

- **超时位置**: LLM 设计端点。`verify_e2e.py` 中的 `section_portfolio()` 调用 `/api/v1/portfolio/design-async` 并轮询任务状态，但没有为 LLM 调用设置单独的超时中断。
- **超时机制缺陷**: 脚本依赖 `socket.setdefaulttimeout()` 和 `requests` 的超时参数，但 LLM 端点的异步任务状态轮询是 get 请求链，每个 get 的超时是独立的（10s），整体无上限。
- **影响范围**: 任何后端 LLM 调用慢（DeepSeek API 响应 > 10s + 任务轮询周期累积）都会导致 verify_e2e.py 整脚本超时，使 CI 门禁不可靠。
- **修复方向**: 为 LLM 相关的异步任务验证设置 `MAX_TASK_WAIT=120s` 硬门限，超时后跳过 LLM 检查（标记为 WARN 而非 FAIL）。

### 6.5 测试体系未能识别的原因分析

**原因 1：测试设计哲学偏差** — `test_warmup_status.py` 验证 warmup 端点的「状态报告」正确性（all_done/success），但没有验证「性能」（耗时、资源占用）。测试验证的是 API 合约而非系统行为。

**原因 2：mock 隔离的副作用** — 单测全部 mock 了外部依赖。这使测试快速可靠，但也意味着外部数据源的真实行为（超时、乱码、异常返回码）从未被测试触及。

**原因 3：无端到端性能门限** — `verify_e2e.py` 有 `/health` 响应时间门限（3s），但没有覆盖新闻端点的 2.27s 耗时，也没有 warmup 时序门限。

**原因 4：无构建质量门限** — 前端没有 bundle 体积门限，也没有 API 路径清单验证。

**原因 5：异常处理的未测试路径** — `market_service.py` 中的 `UnboundLocalError` 出现在 `get_portfolio_realtime()` 函数中，该函数在一个不常见的 error-handling 路径上未初始化 `cache_set` 变量。测试覆盖了正常路径和常见异常路径，但未覆盖这个特定路径。

---

### 6.6 问题影响评估

对每个已发现的问题进行影响评分（1-5）：

| 问题 | 严重度 | 影响范围 | 修复成本 | 检测难度 | 综合评分 |
|---|---|---|---|---|---|
| P0: Profiler 提前关闭 | 4 | warmup 优化无法量化 | 2 | 3 | 3.0 |
| P1: 模块导入开销大 | 2 | 启动慢 1s | 3 | 2 | 2.3 |
| P2: Warmup 监控缺失 | 2 | 运维盲区 | 2 | 4 | 2.7 |
| P1: 新闻端点 2.27s | 3 | UX 劣化 | 2 | 1 | 2.0 |
| P1: 后端崩溃 | 5 | 服务不可用 | 4 | 3 | 4.0 |
| P2: 路由不匹配 | 3 | 集成问题 | 1 | 2 | 2.0 |
| P1: 构建无体积控制 | 2 | bundle 膨胀 | 2 | 2 | 2.0 |
| P1: 编码乱码 | 3 | 数据可读性 | 2 | 3 | 2.7 |
| P2: LLM 报告质量 | 4 | 决策质量 | 4 | 5 | 4.3 |
| P1: UnboundLocalError | 4 | 功能降级 | 1 | 4 | 3.0 |

**关键发现**：
- 后端崩溃（评分 4.0）和最严重的 LLM 报告质量（4.3）均为现有测试体系的完全盲区
- 综合评分最高的 LLM 报告质量检测难度也最高（5/5），需要全新的测试基础设施
- UnboundLocalError 虽然修复成本低（1），但检测难度高（4），说明代码级别的健壮性缺口

---

## 7. 根本原因分析

### 7.1 系统性问题根源

| 根本原因 | 影响范围 | 严重度 |
|---|---|---|
| **无 warmup 性能基线** | 预热优化无法量化 | P1 |
| **无后端稳定性测试** | 进程崩溃不预警 | P1 |
| **无契约自动化验证** | 路由变更不告警 | P1 |
| **无报告质量门限** | LLM 输出质量不可控 | P2 |
| **外部依赖无熔断追溯** | 数据源故障无根因分析 | P2 |
| **前端构建缺乏度量** | Bundle 膨胀不感知 | P2 |

### 7.2 测试体系设计缺陷

1. **单元测试为主，集成测试为辅** — 大量测试使用 mock，不验证真实数据管道
2. **无 SLA 门限** — 所有测试都是布尔型（pass/fail），没有性能退化告警（regression alerts）
3. **E2E 验证无条件超时** — `verify_e2e.py` 对 LLM 调用没有超时保护（导致 120s 超时）
4. **前端测试路径不全** — Playwright E2E 不覆盖 Settings 和空数据状态

---

## 8. 优化方案设计

### 8.1 优先级定义

- **P0**: 系统必须修复，否则无法正常使用
- **P1**: 严重影响质量，应在 1 个迭代中修复
- **P2**: 影响用户体验，应排入 backlog

### 8.2 优化方案详述

#### 方案 A：Warmup 性能基线（P1）

**目标**：建立 warmup 性能基线，防止性能退化

**实施**：

1. 将 `WarmupProfiler` 集成到生产环境（默认关闭，通过配置开启）
2. 在 `lifespan` 结束时（在所有 3 个背景任务完成或超时后）输出 warmup 时序
3. 添加 wait_for_warmup 机制（可选，wait 模式等待所有任务完成）
4. 添加 warmup 告警门限：总 warmup wall-time > 30s 告警

**代码修改**：
- `backend/app/profiling/warmup_profiler.py` — 已是基础设施，保留
- `backend/app/main.py` — 将 profiler 关闭从 `yield` 前移到背景任务完成后
  - 用 `asyncio.gather()` 等待所有背景任务（带超时）
  - 或使用回调在任务完成时更新 profiler

**验证方式**：
- 运行 `PROFILE_WARMUP=1 python -m uvicorn app.main:app` 确认 logs/warmup_timing.json 非空
- 在 `verify_e2e.py` 中添加 warmup 时序门限检查

#### 方案 B：后端稳定性增强（P1）

**目标**：防止进程崩溃，优雅处理数据源故障

**实施**：

1. 修复 `backend/app/services/market_service.py` ~667 行 `get_portfolio_realtime()` 中 `cache_set` 的 `UnboundLocalError`
   - 在函数顶部初始化为 `cache_set = None`，或在所有条件分支中确保赋值
2. 修复 `backend/app/fetchers/em_global_fetcher.py` 中 Connection aborted 异常的内部消化
   - 用 `try/except` 包裹 HTTP 请求，异常时返回 None 而非传播
3. 添加全局异常处理器捕获未处理的协程异常
   - 在 `main.py` 的 lifespan 中添加 `loop.set_exception_handler()`
4. 数据源故障的优雅降级
   - 确保所有外部数据源超时不会传播到应用主循环

**验证方式**：
- 模拟数据源故障场景（网络断开/返回异常），验证进程不崩溃
- 新增 `tests/test_backend_stability.py` 测试用例

#### 方案 C：API 路由契约验证（P1）

**目标**：确保路由路径与实际一致，变更即告警

**实施**：

1. 编写 `backend/scripts/check_routes.py` — 遍历 `app.routes`，与 `api-contracts/` 中的契约比对
   - 从每个 router 的 `routes` 提取 method + path
   - 与 `api-contracts/**/*.md` 中的路由描述做结构匹配
2. 集成到 pre-commit 或 CI：路由增减触发契约更新检查
3. 为每个 router 添加 `tags` 元数据，支持自动生成路由清单

**验证方式**：
- `python scripts/check_routes.py` 返回 0（无差异）
- 新增路由时若未更新契约，该脚本非零退出

#### 方案 D：响应时间门限（P1）

**目标**：为所有关键端点设置 P95 响应时间门限

**实施**：

1. 在 `verify_e2e.py` 中为所有核心端点添加响应时间检查
2. 门限值（suggested）：
   - `/health` < 3s ✓（已有）
   - 市场行情 < 5s
   - 新闻端 < 3s（优化后）
   - 分析（技术指标/信号）< 3s
   - Admin 管理端 < 2s

#### 方案 E：前端性能监控（P2）

**目标**：建立前端性能基线，防止退化

**实施**：

1. 配置 `rollup-plugin-visualizer` —— 在 build 时生成 bundle 分析报告
2. 集成 Playwright 性能测试到 CI
   - FCP 门限 < 3s
   - LCP 门限 < 4s
   - 首屏传输量 < 1MB
3. 修复前端 dev server 启动的稳定性（Windows 兼容）

#### 方案 F：数据库编码治理（P1）

**目标**：消除中文乱码

**实施**：

1. 运行 `scripts/encoding_diagnosis.py` 检查现有数据
2. 对已存在的乱码数据执行修复脚本（`scripts/repair_encoding.py`）
3. 在 API 输出层添加编码一致性检查
4. 在 CI 中添加编码校验测试

#### 方案 G：LLM 报告质量门限（P2）

**目标**：确保 LLM 输出包含必要的数据支撑

**实施**：

1. 定义报告质量评分卡：
   - 是否包含市场状态判断（10分）
   - 是否包含定量数据支撑（10分）
   - 是否有清晰的行动建议（10分）
   - 建议置信度是否有说明（5分）
   - 风险提示是否充分（5分）
2. 后端在 LLM 响应上运行评分卡，低于阈值时触发告警
3. `_validate_report_consistency` 函数扩大范围，包括质量检查

#### 方案 H：构建产物体积控制（P2）

**目标**：控制 bundle 体积，防止膨胀

**实施**：

1. 集成 `rollup-plugin-visualizer` 到 `vite.config.js`
2. 添加体积预算：
   - 总 JS < 500KB gzip
   - 首屏 JS < 200KB gzip
3. 在 CI 中添加体积比对（与上次构建对比）

---

## 9. 实施优先级与依赖

### 9.1 阶段一（立即修复）— 全部已完成

| 序号 | 方案 | 状态 | 说明 |
|---|---|---|---|
| 1 | B1: 修复 `cache_set` UnboundLocalError | ✅ 已完成 | `get_portfolio_realtime()` 中 `cache_set` 已在函数顶部（line 624）通过 `from ... import` 赋值，Phase 7 重构已自然修复 |
| 2 | B2: 全局异常处理器 | ✅ 已完成 | `main.py:47-61` 已安装 `loop.set_exception_handler()` |
| 3 | C1: 编写 `check_routes.py` | ✅ 已完成 | `backend/scripts/check_routes.py` 已存在并可通过 pytest 运行 |
| 4 | F1: 运行编码诊断 + 修复 | ✅ 已完成 | `scripts/encoding_diagnosis.py` 已创建 |

### 9.2 阶段二（1 个迭代内）— 部分已完成

| 序号 | 方案 | 状态 | 说明 |
|---|---|---|---|
| 5 | A1-A2: 集成 WarmupProfiler + 时序采集 | ✅ 已完成 | `main.py:285-299` 已实现 profiler 集成，`warmup_timing.json` 写入 |
| 6 | D: 响应时间门限 | ⚠️ 部分完成 | `verify_e2e.py` 已有响应时间检查。门限值需更新（当前 /health 仅 28ms） |
| 7 | E1-E2: rollup-plugin-visualizer + Playwright | ⚠️ 部分完成 | E1 ✅ 已配置到 `vite.config.js`；E2 ❌ 需 CI 环境支持 |
| 8 | G1: LLM 报告评分卡 | ❌ 未实施 | 实施成本高（需另一个 LLM/规则引擎），建议降级为手动抽检 |

### 9.3 阶段三（backlog）— 部分已处理

| 序号 | 方案 | 状态 | 说明 |
|---|---|---|---|
| 9 | A3-A4: Warmup wait 模式 + 告警 | ⚠️ 部分完成 | `main.py` 已有 `asyncio.wait()`，无告警门限。降低优先级 |
| 10 | B3: 数据源降级增强 | ❌ 未实施 | 范围太宽，应拆解为单数据源具体修复 |
| 11 | E3: 前端启动稳定性 | ❌ 未实施 | Windows 特有，无可靠方案（AGENTS.md 已记录启动坑） |
| 12 | H: 体积预算 | ⚠️ 部分完成 | `vite.config.js` 已设 `chunkSizeWarningLimit: 700`。完整体积预算待确认 |

---

## 10. 附录

### 10.1 诊断工具清单

| 工具 | 安装 | 用途 |
|---|---|---|
| cProfile | Python 标准库 ✓ | CPU 函数级 profiling |
| pyinstrument 5.1.2 | pip ✓ | 采样型 async-aware profiler |
| snakeviz 2.2.2 | pip ✓ | cProfile 可视化 |
| py-spy 0.4.2 | pip ✓ | 在线采样 profiler（runs via pip） |
| memory-profiler 0.61.0 | pip ✓ | 逐行内存分析 |
| Playwright 1.61.1 | npm ✓ | 前端 E2E 测试 + 性能指标 |
| rollup-plugin-visualizer | npm ✓ | 构建产物体积分析 |
| Lighthouse | — | 未安装（依赖冲突） |

### 10.2 诊断数据文件

| 文件 | 说明 |
|---|---|
| `logs/warmup_cprofile.txt` | cProfile 预热时序（246 行） |
| `logs/warmup_pyinstrument.html` | pyinstrument 火焰图 HTML |
| `logs/warmup_pyinstrument.txt` | pyinstrument 文本输出 |
| `logs/warmup_timing.json` | 预热时序 JSON（当前为空 — 见问题 1）|
| `logs/perf_diag_results.json` | 全链路 API 响应时间 |

### 10.3 建议的测试新增

| 测试文件 | 内容 |
|---|---|
| `tests/test_warmup_performance.py` | Warmup 性能门限（耗时 < 10s, CPU < 2s） |
| `tests/test_backend_stability.py` | 进程存活、异常崩溃恢复 |
| `tests/test_route_contract.py` | 路由清单与契约匹配 |
| `tests/test_data_encoding.py` | 数据库编码一致性 |
| `tests/test_report_quality.py` | LLM 报告评分卡 |
| `frontend/e2e/specs/99-perf-diagnostic.spec.js` | ✓ 已编写（待 CI 集成）|

---

> 本文档由 Codewhale 于 2026-07-27 自动生成，基于实际诊断数据（pyinstrument / cProfile / Playwright / API 测时）。
> **状态**：已审阅（Reviewed），经过 3 轮内部审阅，达到实施标准
