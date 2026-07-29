# ETF Surge — 系统优化与质量保障方案 (v2.0)

> 基于 2026-07-28 全链路性能诊断与质量审计，覆盖后端预热/API/数据管道、前端渲染、报告质量、测试防护体系。

---

## 目录

1. [审计结果概要](#1-审计结果概要)
2. [问题清单与严重等级](#2-问题清单与严重等级)
3. [报告质量分析（核心关注）](#3-报告质量分析核心关注)
4. [后端性能诊断](#4-后端性能诊断)
5. [前端性能诊断](#5-前端性能诊断)
6. [测试防护体系分析](#6-测试防护体系分析)
7. [优化方案](#7-优化方案)
8. [结论与优先级建议](#8-结论与优先级建议)
9. [实施路线图](#9-实施路线图)

---

## 1. 审计结果概要

| 维度 | 评分 | 关键发现 |
|------|------|----------|
| 报告质量（设计方案） | ⚠️ 不合格 | 10个设计方案中 6 个无任何真实 ETF 分配（100%现金），但标记为 "full" 质量 |
| 报告质量（策略检查） | ⚠️ 不合格 | 所有检查记录返回"组合为空"，suggestions/holdings/risk_warnings 均为空数组 |
| 后端预热性能 | ⚠️ 需优化 | 首次预热 9.9s（ETF扫描占 7s），二次预热 1.8s |
| 后端运行时稳定性 | 🔴 严重 | EastMoney push2 不可用时产生无限重试风暴，每 5s 一次，迅速击穿所有线程池 |
| 后端 API 响应 | ⚠️ 波动大 | 正常时 0.01~3.2s；重试风暴期间全部超时（>30s） |
| 前端 Lighthouse | ⚠️ 38/100 | LCP 24.7s, Interactive 24.7s, CLS 0.538, 未使用 JS 2.3MB |
| 前端可访问性 | ✅ 92/100 | 良好 |
| 测试防护体系 | 🔴 严重缺口 | 单元测试全部 mock 外部调用，e2e 不检验分配合理性，无报告质量断言 |

---

## 2. 问题清单与严重等级

### P0 — 数据与报告质量（当前影响用户决策）

| ID | 问题 | 影响 | 根因 |
|----|------|------|------|
| Q-01 | **所有策略检查报告为空**：`summary="组合为空"`，无持仓/建议/风控数据 | 用户看不到任何策略建议 | 策略检查管道未连接到 on_exchange 持仓数据；`strategy_check_records` 表缺少 `report_text` 列 |
| Q-02 | **设计方案产生 100% 现金组合**：222-224 号设计 0 只真实 ETF | 用户看到的方案无实际指导意义 | 分配引擎 `allocate()` 返回空选择；LLM 报告虽好但基于空数据生成"主动观望"等误导性结论 |
| Q-03 | **report_quality 标签失真**：空方案标记为 "full"，用户无法分辨好坏 | 质检机制形同虚设 | `report_quality` 仅检测 LLM 报告生成成功，不检查分配结果有效性 |
| Q-04 | **LLM 报告数据完整性问题**：design_text 中的 ETF 表格全是空的（0 只，0% 权重） | 用户看到的报告有表格头但无数据 | 方案详情中的 `{% for etf in ... %}` 模板循环输出空结果 |

### P1 — 系统稳定性（严重影响可用性）

| ID | 问题 | 影响 | 根因 |
|----|------|------|------|
| S-01 | **push2 熔断器形同虚设**：`fetch_advance_decline_ratio()` 绕过 `registry.route()` 用 `urllib.urlopen` 直连 push2，失败后不向熔断器汇报 | 5秒级反复重试，迅速耗尽线程池，所有 API 超时 | ① `fundamentals_fetcher.py` 未使用 `registry.route()`，直连 push2 失败后不调 `record_failure()`；② `run_sync` 在文件中未 import，`fetch_market_sentiment()` 入口直接抛 NameError |
| S-02 | **`factor_registry.py` 引发 5s 阻塞循环**：`run_in_thread(fetch_advance_decline_ratio, timeout=5)` 每轮因子计算都阻塞 5s 等 akshare 超时 | 因子计算阶段耗时失控，设计管线被堵 | akshare stock_zh_a_spot_em 对 EastMoney 的请求也被拒（5.7s 超时），外层 `timeout=5` 准时截断，下一轮因子计算又重来 |
| S-03 | **设计任务执行不稳定**：任务 106/107/110 均卡在 "running" 状态不完成也不失败 | 设计功能对用户不可用 | 数据采集阶段被重试风暴阻塞，没有超时/取消机制 |
| S-04 | **numba SSA DEBUG 日志泛滥**：日志中大量 numba.core.ssa DEBUG 信息 | 日志膨胀，诊断难 | 默认日志级别过低，numba 内部日志未屏蔽 |

### P2 — 性能效率（影响体验）

| ID | 问题 | 发现问题工具 | 详情 |
|----|------|-------------|------|
| P-01 | **前端 LCP 24.7s / Interactive 24.7s** | Lighthouse | 前端等待后端 API 响应超时（后端重试风暴），Vite dev server 未对慢 API 设置超时 |
| P-02 | **前端未使用 JS 2.3MB / 总大小 4MB** | Lighthouse | ECharts 等库全量打包，未做 tree-shaking 优化 |
| P-03 | **前端 CLS 0.538** | Lighthouse | 未设置图片元素宽高比 |
| P-04 | **后端预热 ETF 扫描 7s** | cProfile + pyinstrument | akshare `fund_etf_category_sina` 返回 JSON 过大，demjson 解析耗时 |
| P-05 | **pyinstrument 未捕获异步协程** | 自检发现 | `async_mode="disabled"` 导致 async 协程不被采样 |

### P3 — 架构/可维护性

| ID | 问题 | 详情 |
|----|------|------|
| A-01 | **warmup_profiler 报告未自动接入 CI** | 预热性能数据存在容器内日志，但无 gate 检查 |
| A-02 | **strategy_check_records 表不包含 report_text** | 与 portfolio_designs 表结构不一致，无 LLM 报告列 |
| A-03 | **sentiment 数据源的降级路径未自动化** | push2 失败后 akshare fallback 同样连 EastMoney 也失败，但没有缓存持久化的断网保护；`run_sync` 未导入的 bug 使另一入口静默报错 |

---

## 3. 报告质量分析（核心关注）

### 3.1 设计方案质量逐项评审

以 **Design 224**（最新完成方案，report_quality="full"）为样本：

```
防御型: 0 只真实 ETF, 100% 现金, layer_budget={core:0.4, satellite:0.25, defense:0.1}
平衡型: 0 只真实 ETF, 100% 现金, layer_budget={core:0.4, satellite:0.3, defense:0.1}  
进攻型: 0 只真实 ETF, 100% 现金, layer_budget={core:0.4, satellite:0.35, defense:0.1}
```

**问题分析：**

1. **分配引擎输出为空**：`allocate()` 函数未返回任何 ETF 选择
2. **LLM 报告逻辑自洽但不真实**：报告中对 "range_bound" 市态的讨论合理，但"100% 现金主动观望"的结论是 LLM 在空数据上的事后合理化（hallucination）
3. **质检流程缺失**：没有任何门槛检查——"方案是否包含至少 3 只真实 ETF"，"现金比例是否超过 80% 需人工确认"等

### 3.2 策略检查报告质量逐项评审

所有策略检查记录（ID 117-121）：
- `summary` = "组合为空"
- `suggestions_json` = `[]`
- `holdings_json` = `[]`
- `risk_warnings_json` = `[]`

**问题分析：**

1. **无真实持仓数据**：策略检查未能读取当前持仓
2. **无 LLM 报告**：`strategy_check_records` 表不含 `report_text` 列
3. **即使有持仓也不产生报告**：检查逻辑未正确读取 `portfolio_etfs` 表数据

### 3.3 LLM 报告逻辑性评估

LLM 生成的报告（design_text）本身内容详实、逻辑清晰：
- 准确分析了 "range_bound" 市场特征
- 对三层架构的阐述正确
- 配置建议合理

**问题**：逻辑自洽但脱离实际数据——ETF 名单为空，但 LLM 生成了"系统主动观望"的解释，掩盖了分配引擎的故障。

### 3.4 与市场行情匹配度

- 市场状态判定为 "range_bound" ✅
- 情绪指数标记为 50（中性）✅
- 但所有方案均无真实分配，使"匹配度"讨论失去意义

---

## 4. 后端性能诊断

### 4.1 预热阶段

**工具**：warmup_profiler (pyinstrument + cProfile)

| 阶段 | 首次启动 | 二次启动 | 瓶颈 |
|------|---------|---------|------|
| DB 初始化 | 724ms | 151ms | AIOSQLite PRAGMA 查询 |
| Redis 初始化 | 51ms | 55ms | 网络延迟 |
| ETF 扫描 | 7055ms | 40ms | akshare demjson 解析 4.2s |
| 行情缓存 | 143ms | 79ms | 网络 I/O |
| 全球指数 | 1891ms | 1478ms | 多路 Sina API 请求 |
| **总计** | **9865ms** | **1802ms** | 网络 I/O 为主 |

**关键发现**：
- ETF 扫描首次占 71% 总时间
- `akshare.utils.demjson.decode_string` 被调用 51k+ 次，耗 5s
- `fund_etf_category_sina` 返回的 JSON 过大，demjson 解析效率极低
- 二次启动快是因为 ETF 和指数缓存已持久化

### 4.2 运行时 API

**工具**：curl + `time_total` 测量

| 端点 | 正常响应 | 重试风暴期间 |
|------|---------|-------------|
| `/health` | 0.009s | 不可用 |
| `/api/v1/market/sectors` | 0.22s | 不可用 |
| `/api/v1/portfolio/etfs` | 0.04s | 不可用 |
| `/api/v1/portfolio/designs` | 0.05s | 不可用 |
| `/api/v1/news/headlines` | 3.24s | 不可用 |

### 4.3 5 秒间隔实测追踪（实测验证）

日志显示 `[sentiment] push2 advance_decline failed` 每 ~5 秒一次。通过代码追踪 + Docker 内实测确定真实调用链：

**实测数据**
```
push2.eastmoney.com HTTPS:  FAIL 0.1s  → RemoteDisconnected（服务端主动断连）
push2.eastmoney.com HTTP:   FAIL 0.0s  → RemoteDisconnected
TCP connect push2:443:     OK   0.01s → 网络可达但 TLS 握手后被拒
Sina fallback:              OK   0.13s → 正常工作
akshare stock_zh_a_spot_em: FAIL 5.7s  → ConnectionError（akshare 也走 EastMoney）
```

**真实调用链**
```
T+0s    factor_registry.py:504 中的因子计算
        → run_in_thread(fetch_advance_decline_ratio, timeout=5)
        → push2 HTTPS 请求 (0.1s 失败)  ← 打印 log: "[sentiment] push2...failed"
        → akshare fallback: stock_zh_a_spot_em() 开始 (预计 5.7s 失败)
T+5s    run_in_thread 的 timeout=5 触发 → 返回 None
        akshare 后台线程继续跑 (再过 0.7s 后失败)
T+5s+   下一轮因子计算再次调用 → 重复上述循环
```

**关键发现**
1. **推手不是背景循环**：`refresh_sentiment_cache()` 内部 `fetch_market_sentiment()` 调用了 `run_sync(fetch_advance_decline_ratio)`，但 **`run_sync` 在 `fundamentals_fetcher.py` 中没有被 import**，所以实际报 NameError，不产生 push2 warning
2. **真正的 5s 源是 `factor_registry.py:504`**：`run_in_thread(fetch_advance_decline_ratio, timeout=5)`，timeout 参数正好 5s，akshare 要 5.7s 才超时，所以每次都被准时截断
3. **多任务积压放大问题**：旧的卡住任务（103/106/107/110）加上新的（111/112）排队执行，每个都触发因子计算，形成持续的 5s 间隔风暴

### 4.4 关键瓶颈根因

1. **Sentiment 重试风暴**（稳定性最严重问题）
   - **真实调用链**: `factor_registry.py:504` → `run_in_thread(fetch_advance_decline_ratio, timeout=5)` → push2 HTTPS (0.1s RemoteDisconnected) → akshare fallback `stock_zh_a_spot_em()` (5.7s timeout) → `run_in_thread` 5s 截断 → 下一轮因子计算又触发
   - **熔断器为何无效**：`fundamentals_fetcher.py` 未使用 `registry.route()` 机制，失败后不调 `record_failure()`，熔断器从未收到失败报告，永远返回 `available=true`
   - **import bug 使另一入口静默失败**：`fetch_market_sentiment()` 调用 `run_sync()` 但 `run_sync` 未被 import，调用即抛 NameError——push2 warning 非由此路产生
   - 频次：每 ~5s 一次（`run_in_thread` 的 `timeout=5` 参数决定的截断周期）

2. **ETF 扫描性能**
   - `_sina_tencent_provider` → `china_market.fetch_etf_list` → akshare `fund_etf_category_sina`
   - demjson 解析器对大型 JSON 效率极低，应替换为 `json` 或 `orjson`

3. **numba 日志**
   - akshare 依赖 numba，但 `backend.log` 中 numba.core.ssa DEBUG 日志巨量输出（每个调用数百行）

### 4.5 数据源可用性实测地图（2026-07-28 Docker 内实测）

实测所有 EastMoney 子域名 + 独立备选源。**结果不一致——部分域名可用，部分被拒。**

| 域名 | 实测 | 平均耗时 | 使用方 | 备注 |
|------|:----:|:-------:|--------|------|
| `push2.eastmoney.com` (HTTPS) | 🔴 全部被拒 | 0.1~0.2s | `fetch_advance_decline_ratio()` | RemoteDisconnected |
| `push2.eastmoney.com` (HTTP) | 🔴 全部被拒 | 0.1s | ETF scanner `_fetch_em_etf_list()` | 同样 TLS 层被拒 |
| `82.push2.eastmoney.com` (HTTPS) | 🔴 全部被拒 | 0.1~0.2s | akshare `stock_zh_a_spot_em()` | 所以 akshare 兜底也 5.7s 超时 |
| `push2his.eastmoney.com` (HTTPS) | 🟡 间歇被拒 | 0.1s | akshare `stock_individual_fund_flow()` | 两次测试结果不一致 |
| **`push2delay.eastmoney.com`** (HTTPS) | ✅ **3/3 全通** | **0.05~0.08s** | 代码中未使用；akshare `fund_etf_spot_em()` 使用 | **可作为替代** |
| **`api.fund.eastmoney.com`** (HTTPS) | ✅ **全通** | **0.06~0.08s** | akshare `fund_etf_fund_info_em()` | 基金规模数据 |
| **`vip.stock.finance.sina.com.cn`** | ✅ **全通** | **0.13~0.23s** | akshare `fund_etf_category_sina()` | **真正的独立冗余源** |
| **`qt.gtimg.cn`** (HTTP) | ✅ **全通** | **0.08s** | ETF scanner `_tencent_gtimg_batch()` | **真正的独立冗余源** |
| `hq.sinajs.cn` (HTTPS) | 🟡 间歇性 | 0.14~5.2s | `market_service.py` | 需要 Referer 头，有频率限制 |

**关键 insight**：akshare 的 `_em` 系列函数不是有效的独立降级路径——它们底层都走 EastMoney（push2 / 82.push2 / push2his / push2delay / api.fund 五个不同子域名），与直连 push2 共享相同基础设施。**唯一真正独立的数据源是 Sina 和腾讯 (gtimg)。**

**`push2delay.eastmoney.com` 的替代可行性**：
- 实测支持与 push2 相同的 API 路径（`/api/qt/clist/get`）和全部查询参数
- pz=5000 全市场请求 0.08s 返回，total=5542，数据完整
- 3 次连续测试全部通过，稳定性高
- 名称中的 "delay" 不影响用途——涨跌家数比和情绪指数不依赖秒级实时
- 但仍然是 EastMoney 基础设施，非独立冗余，不能作为唯一的保障

---

## 5. 前端性能诊断

**工具**：Lighthouse v11+ (headless Chrome)

| 指标 | 值 | 得分 | 评级 |
|------|----|------|------|
| Performance | — | 38/100 | 🔴 差 |
| First Contentful Paint | 4.4s | 0.16 | 🔴 |
| Largest Contentful Paint | 24.7s | 0 | 🔴 |
| Total Blocking Time | 200ms | 0.89 | ✅ |
| Cumulative Layout Shift | 0.538 | 0.14 | 🔴 |
| Speed Index | 4.9s | 0.65 | ⚠️ |
| Time to Interactive | 24.7s | 0 | 🔴 |
| Unused JavaScript | 2,366 KiB | 0 | 🔴 |
| Total Byte Weight | 4,044 KiB | 0.5 | ⚠️ |

**关键发现**：

1. **LCP/Interactive 24.7s 的主要原因是后端慢**：前端等待市场数据 API 响应，而后端在重试风暴中
2. **未使用 JS 2.3MB**：`echarts` 等依赖被全量打包而未做 tree-shaking。生产 build（npm run build）会启用 Vite 的 rollup tree-shaking，但需要按需导入配置才能生效
3. **CLS 0.538**：未为图片和动态加载的元素设置宽高占位
4. **Vite dev 模式**：开发模式未配置代码分割和懒加载（production build 可能改善但未验证）

---

## 6. 测试防护体系分析

### 6.1 当前防护体系概览

| 防护层 | 工具 | 覆盖范围 | 缺口 |
|--------|------|---------|------|
| 后端单元测试 | pytest + mock | 策略引擎、因子计算 | 全部 mock 外部调用，不测试真实数据管道 |
| 前端单元测试 | vitest + @vue/test-utils | 组件渲染、store 逻辑 | 不测试 WebSocket 连接，不测试 API 响应处理 |
| E2E 链路验证 | `verify_e2e.py` | 核心链路可达性 | 只检查"存在性"不检查"合理性" |
| Pre-commit | `.githooks/pre-commit` | Vue 编译错误 | 仅语法检查，无逻辑验证 |
| API 契约 | `api-contracts/*.md` | 接口形态一致性 | 静态文档，无自动化校验 |

### 6.2 为什么本次发现的问题未被捕获

| 问题 | 为什么被忽略 | 代码层面追踪 | 改进方向 |
|------|-------------|------------|---------|
| **Q-02 空 ETF 分配** | 单元测试 mock 了 `allocate()` 返回值，从未用真实因子跑分配。`verify_e2e.py` 只检查 `strategies 含方案（len≥1）`，不检查方案中 ETF 数量 | `test_design_optimization_plan.py:38-62` 把所有 pool_manager 方法都 mock 了；`verify_e2e.py:272` 只 `len(strategies) > 0` — 一个全 CASH 的策略(0只ETF)同样满足 | 增加集成测试：用真实因子数据（mock 数据源）跑分配，断言方案中 real_etf_count ≥ 3 |
| **Q-01 空策略检查** | `verify_e2e.py` 不检查策略检查 API 的返回内容，只校验 HTTP 200 | `verify_e2e.py:532-539` 只传空 body 测 schema 校验，不检查 `holdings_json` | 增加策略检查结果校验：`holdings_json` 不应为空 |
| **Q-03 report_quality 失真** | 质量判定逻辑只检测 LLM 报告是否成功写入，不检查分配结果有效性 | `task_manager.py` 中 `report_quality` 赋值在 LLM 生成成功后，分配阶段的空结果未被纳入判定条件 | 增加分配结果质量门禁：若方案全部为现金，标记为 "failed" |
| **S-01 重试风暴** | 单测全 mock 外部 HTTP 调用，从不测试真实网络行为。2 种 mock 层：① `_patch_singleton_methods` 在 fixture 中 mock pool_manager；② `_mock_scanner` mock 数据管道 — 实际网络代码从未被执行 | `test_design_optimization_plan.py:38-62` fixture 把所有数据源 mock 掉；`run_in_thread`/`run_sync` 调用的真实函数(`fetch_advance_decline_ratio`)从未进入测试执行路径 | 增加熔断器集成测试：用 mock 连接错误模拟数据源失败，验证 3 次后冷却 |
| **S-03 任务卡死** | 任务管理器无超时机制。单测中 `create_task` 后 design/check worker 的 `asyncio.wait_for` 监控只在 `strategy_check_pipeline` 有 30s 超时，`_design_pipeline` 和 `task_manager` 主循环没有超时 | `task_manager.py:236` 只有 `strategy_check_pipeline` 有 `asyncio.wait_for(_, timeout=30)`；`_design_pipeline_with_semaphore` 无超时（超时发生在 LLM 报告阶段 `compose_and_push_report` 的 90s）；数据采集阶段完全无超时保护 | 增加任务级超时看门狗 |
| **P-01 前端 24.7s 加载** | E2E 不测试前端加载性能。前端不设 API 超时，后端重试风暴时 axios 默认等待 | `frontend/src/api/index.js` 无 `timeout` 配置；Lighthouse 不在 CI 中运行 | 增加 axios 全局 timeout + Lighthouse CI gate |
| **P-04 ETF 扫描 7s** | 预热性能数据存在容器内日志，从未被 CI 或测试检查。cProfile 数据虽被写入但无阈值判定 | `warmup_profiler.py` 将 cProfile/pyinstrument/timing 写入 `/app/logs/`，但无任何门槛检查脚本读取这些文件 | 增加预热性能基线检查 |

### 6.3 深层原因分析

#### 6.3.1 "永远 mock、从不集成"的文化

测试文件 `test_design_optimization_plan.py` 的 fixture 结构揭示了根本问题：第 38-62 行的 `_patch_singleton_methods` 把 `pool_manager` 的 **所有数据获取方法都 mock 了**。这意味着：

```
pool_manager.get_index_realtime()     → mock `[]`
pool_manager.get_sector_momentum()     → mock `[]`  
pool_manager.get_market_sentiment()   → mock `{"sentiment_index": 55}`
pool_manager.get_news()               → mock `[]`
pool_manager.get_market_regime()      → mock `"range_bound"`
pool_manager.scanner                  → mock `{"core": [], ...}`
pool_manager.classifier               → mock `{}`
pool_manager.factor_registry          → mock `{}`
```

这个 fixture 在 test 文件中是 **autouse=True**，意味着 **每个测试用例都运行在全 mock 环境下**。这是一种确保"测试跑得又快又稳定"的设计，但代价是：

1. **数据管道的真实行为从未被验证** — 没人知道 `refresh_sentiment_cache()` 是否真的能连接上 push2
2. **空结果、异常超时等边缘情况从未被覆盖** — mock 只返回 Happy Path 数据
3. **跨组件集成组合从未被测试** — 每个组件单独测试时都认为"邻居会正常返回"

#### 6.3.2 verify_e2e.py 的"存在的就是合理的"哲学

`verify_e2e.py` 是部署前的最后一关，但它的设计哲学是**检查端点是否活着、返回是否符合基本 schema**，从不检查返回内容的**合理性**。

关键代码行：
```python
# verify_e2e.py 第 269 行 — "质量检查"
check(f"design_text 已持久化（{len(dt)} 字）", len(dt) > 200 and "三种方案详解" in dt)
# ↑ 空方案(0只ETF)也有2500字的LLM报告，一样通过

# verify_e2e.py 第 272 行 — "方案检查"  
check(f"strategies 含方案", len(strategies) > 0)
# ↑ 一个"防御型: 0只ETF, 100%现金"也算"含方案"
```

对测试人员的心理分析：verify_e2e.py 最初的设计目标是"确认系统正常运行"，不是"确认系统输出了正确的答案"。它隐含假设是"只要 HTTP 200 和数据结构正确，内容就是对的"——这个假设在本次审计中被证明是错误的。

#### 6.3.3 "看不到的缺陷"模式

| 问题 | 为什么在开发/测试时没被发现 |
|------|---------------------------|
| **空分配** | `allocate()` 返回空数组时，下游的 LLM 报告管道会生成看起来"很专业"的报告（"市场 range_bound，组合主动观望"），掩盖了分配失败的事实。人类 reviewer 容易被"头头是道"的报告迷惑 |
| **熔断器失效** | 熔断器代码(`_push2_available()`)看起来"在用"，实际上只读不写。熔断器状态从未积累失败。这种"被动失效"比"主动报错"更难被发现 |
| **import bug** | `run_sync` 未 import 抛 NameError，但被外层 `try/except` 吞掉。NameError 在日志里写了一行 "refresh_sentiment_cache failed"，但因为是背景任务，没人盯着日志看 |
| **任务卡死** | Task 显示 "running" 但无进度更新。这被当作"任务还在处理中"容忍了数天 |

这些缺陷的共同特征是：**系统仍在运行、不崩溃，只是输出"看起来没问题"的错误结果**。这种"静默错误"是测试防护体系最难防御的类型——因为系统没有以明显的方式表现出问题。

### 6.4 缺失的测试类型

1. **集成测试（Integration Tests）**：真实数据管道跑分配引擎，mock 数据源而非 mock 分配
2. **性能回归测试（Performance Regression Tests）**：预热时间、API 响应时间、Lighthouse 分数的基线跟踪
3. **稳定性测试（Resilience Tests）**：数据源熔断、重试限流、降级路径
4. **报告质量断言（Report Quality Assertions）**：设计方案真实 ETF 数量、现金比例上限

---

## 7. 优化方案

所有方案按优先级（P0→P1→P2→P3）排列，每项标注预期工时。

### 7.1 P0 — 数据与报告质量修复

#### FIX-Q01: 分配引擎输出有效性门禁

**问题**：`allocate()` 返回空选择时，方案仍被标记为 "completed" + "full"

**方案**：
```
在 _design_pipeline_with_semaphore() 中，allocate() 返回后增加检查：
- 若三个方案均仅有 CASH（无真实 ETF）：标记 design.status = "failed"
- 若至少一个方案有 ≥3 只 ETF：继续 LLM 报告生成
- 设置 error_message 描述具体失败原因（如"因子评分均低于阈值，无符合条件 ETF"）
```

**文件**：`backend/app/tasks/task_manager.py`（`_design_pipeline_with_semaphore` 函数）

**工时**：1h

---

#### FIX-Q02: 策略检查管道修复

**问题**：`strategy_check_worker` 未能读取持仓数据，产生空报告

**方案**：
```
- 检查 strategy_check_pipeline() 的持仓加载阶段：确保从 portfolio_etfs 表读取当前持仓
- 为 strategy_check_records 表增加 report_text 列
- 若持仓为空，在报告标题中说明"当前无持仓"，而非静默返回空
```

**文件**：
- `backend/app/tasks/strategy_check_worker.py`
- `backend/app/database.py`（schema 迁移）

**工时**：2h

---

#### FIX-Q03: report_quality 分级体系

**问题**：当前只有 "full"/"pending" 两档，空方案也被标为 "full"

**方案**：
```
细化 report_quality 分级：
- "full"：正常分配 + LLM 报告完整生成
- "partial"：分配成功但 LLM 报告不完整（如超时）
- "empty"：分配返回空（无真实 ETF）
- "failed"：管道执行异常

前端对 "empty" 和 "failed" 显示明显警告标记
```

**文件**：`backend/app/tasks/task_manager.py`

**工时**：1h

---

#### FIX-Q04: LLM 报告一致性校验增强

**问题**：LLM 报告在分配为空时仍生成"主动观望"等误导性内容

**方案**：
```
在 _validate_report_consistency() 中增加：
- 检查方案 ETF 数量：若为 0，追加明确的修正脚注
- 检查表格行是否为空，若为空则不渲染
- 添加日志 WARNING 级别告警
```

**文件**：`backend/app/tasks/design_report.py`

**工时**：0.5h

---

### 7.2 P1 — 系统稳定性修复

#### FIX-S01: 让 push2 熔断器真正生效 + 修复 import bug

**问题**：`fundamentals_fetcher.py` 绕过 `registry.route()` 用 `urllib.urlopen` 直连 push2，失败后不向熔断器报告；`run_sync` 未 import 导致 `fetch_market_sentiment()` 入口静默崩溃

**方案（A+B 合并，工时 3h）**：
```
步骤 1 — 熔断器接入（fundamentals_fetcher.py）：
  a) 将 fetch_advance_decline_ratio() 中直连 push2 的 urllib.urlopen 改为通过 registry.route() 调用
  b) 删除 push2 硬编码 URL，改为 registry.route([("push2delay.eastmoney.com", lambda: _call_push2delay()), ...])
  c) 失败时 route() 自动 record_failure，快失败 (<500ms) 自动转 hard_failure 立即冷却
  d) 熔断器冷却期 60s 指数退避（60s→120s→240s→480s→600s max）

步骤 2 — 域名替换为 push2delay（fundamentals_fetcher.py + etf_scanner.py）：
  fundamentals_fetcher.py:607:
    URL 从 https://push2.eastmoney.com/... 改为 https://push2delay.eastmoney.com/...
    HTTP 路径也改为 HTTPS
  etf_scanner.py:156:
    URL 从 http://push2.eastmoney.com/... 改为 https://push2delay.eastmoney.com/...
    HTTP → HTTPS

步骤 3 — 修复 import bug（fundamentals_fetcher.py）：
  在顶部添加：from ..core.async_utils import run_sync

步骤 4 — 跳过无效的 akshare fallback（fundamentals_fetcher.py）：
  push2delay 失败后跳过 stock_zh_a_spot_em()（底层 82.push2 也被拒）
  直接返回 0.5
  下游拿到 0.5 即知数据不可用，不再等待——消除 5s 阻塞

步骤 5 — 熔断器全局生效验证：
  熔断器 3 次失败后开始 60s 冷却，冷却期内 _push2_available() 返回 false
  push2delay 请求直接跳过（0.01s 内完成），不再向线程池提交阻塞任务

注意：push2delay 仍是 EastMoney 基础设施，非独立冗余。
中长期需依赖 Sina + Tencent 作为真正的独立数据源。
```

**文件**：`backend/app/fetchers/fundamentals_fetcher.py` + `backend/app/fetchers/etf_scanner.py`

**工时**：3h（比单项方案 A 多 1h，用于域名替换测试和熔断器路径验证）

---

#### FIX-S02: 消除 `factor_registry.py` 中 5s 阻塞调用

**问题**：`factor_registry.py:504` 通过 `run_in_thread(fetch_advance_decline_ratio, timeout=5)` 调用，因 akshare fallback 需 5.7s 超时，每次被 `timeout=5` 准时截断，形成每 5s 一次的阻塞循环

**方案**：
```
在 factor_registry.py 的 advance_decline 因子计算中：
1. 将 timeout=5 增至 timeout=10（给 akshare 充分的超时窗口）
   但更好的做法是：
2. 缓存该因子结果：设置 120s TTL，同一次设计管线内的多次因子计算不重复 fetch
3. 若返回 None 或 0（数据不可用），缓存该状态 60s 内不再重试
```

**文件**：`backend/app/factors/factor_registry.py`

**工时**：1h

---

#### FIX-S03: 任务管理器超时销毁

**问题**：任务 106/107/110 卡在 "running" 不完成

**方案**：
```
TaskManager.create_task() 时启动超时看门狗：
- design 任务：5 分钟超时
- check 任务：3 分钟超时
- report 任务：5 分钟超时
超时后自动标记为 "failed" 并记录 error_message
- 同时清理积压的旧任务：容器启动时扫描 tasks.json，清除超过超时时间且 stuck 在 "running" 状态的任务
```

**文件**：`backend/app/tasks/task_manager.py`

**工时**：2h

---

#### FIX-S04: numba 日志降级

**问题**：numba.core.ssa DEBUG 日志过量

**方案**：
```
在 logging 配置中增加：
logging.getLogger("numba").setLevel(logging.WARNING)
```

**文件**：`backend/app/core/logging.py`

**工时**：0.2h

---

#### FIX-S05: 剩余数据链路熔断器全覆盖

**问题**：除 `fundamentals_fetcher.py` 外，另有 2 个 fetcher 也通过 `urllib.urlopen` 直连外部 API，完全不经过 `registry.route()`：

| 文件 | 行号 | 直连域名 | 熔断器保护 | 实测可用性 |
|------|------|---------|-----------|-----------|
| `fund_fetcher.py` | 38 | `api.fund.eastmoney.com`（基金净值） | ❌ 无 | ✅ 可用（0.08s） |
| `global_markets_fetcher.py` | 125 | `qt.gtimg.cn`（腾讯港股指数） | ❌ 无 | ✅ 可用 |
| `global_markets_fetcher.py` | 347 | Sina 查询 | ❌ 无 | ✅ 可用（0.3s） |
| `global_markets_fetcher.py` | 450, 559 | Yahoo Finance（yfinance） | ❌ 无 | 部分可用 |

这些链路当前域名可达，不会产生请求风暴，但缺少熔断器意味着：
- 某天某个域名不可用时，将和 push2 一样产生无限重试（虽不那么频繁，但风险一致）
- 运维无法从统一面板看到这些源的健康状态
- 无法利用熔断器的指数退避冷却机制

**方案（4 个独立子任务）**：

```
子任务 A — fund_fetcher.py（工时 0.5h）
==================================
将 _fetch_nav() 的 urlopen 直连改为 registry.route() 批量方式：

1. 在源码顶层导入 source_registry：
   from ..services.source_registry import registry as _registry

2. 将 _fetch_nav 包装为注册到 registry 的 provider 函数：
   def _fund_nav_provider(symbol: str) -> dict | None:
       url = f"{_API_BASE}?fundCode={symbol}&pageIndex=1&pageSize=1"
       req = urllib.request.Request(url, headers=_HEADERS)
       with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
           raw = resp.read().decode("utf-8")
           data: dict = json.loads(raw)
       ...  # 后续解析逻辑不变

3. fetch_fund_nav() 内调用：
   return _registry.route(
       [("fund_eastmoney", lambda: _fund_nav_provider(symbol))],
       route_name="fund_nav", operation="query", target=symbol
   )
   失败时 route() 自动 record_failure，快失败自动 hard_failure


子任务 B — global_markets_fetcher.py: Tencent HK 指数（工时 0.5h）
=========================================================
_fetch_tencent_hk_indices() 的 urlopen 改为 registry.route()：

1. 导入 _registry
2. 将 try/urlopen 块包装为 provider 函数
3. fetch_hk_indices() 内调用：
   result = _registry.route(
       [("tencent_hk_index", _tencent_hk_provider),
        ("sina_hk_index", _sina_hk_provider)],
       ...
   )
   return result or fallback（fallback 保持现有 Sina akshare 路径）
4. 外部 _em_hk_realtime 已在 HK_stock_realtime 的 route() 中注册为 "dongfang" 源，受保护


子任务 C — global_markets_fetcher.py: Yahoo Finance（工时 1h）
======================================================
_request() 和 fetch_yahoo_realtime()/fetch_candles() 改为 registry.route()：

1. 将 _request() 重构为可被 route() 调用的 provider：
   def _yahoo_provider(symbol, params):
       data = _request(path, params)
       return data

2. fetch_yahoo_realtime() 调用：
   return _registry.route(
       [("yahoo_finance", lambda: _yahoo_provider(...))],
       ...
   )

3. fetch_candles() / k_line 同理

4. 注意：yfinance 可能不在 Docker 环境使用（需 YFINANCE_PROXY），
   熔断器冷却期合理设置为 120s（因 Yahoo 被墙通常是长期不可用）


子任务 D — 统一熔断源注册（工时 0.5h）
=================================
在 source_registry.py 中注册所有新数据源名称：

源名称                   | failure_threshold | base_cooldown | 说明
------------------------|-------------------|--------------|-----
"fund_eastmoney"        | 3                 | 60s          | 基金净值 api.fund
"tencent_hk_index"      | 3                 | 30s          | 腾讯 qt.gtimg.cn
"yahoo_finance"         | 2                 | 120s         | Yahoo 被墙概率高
"push2delay.eastmoney"  | 3                 | 60s          | 由 FIX-S01 新增
"sina_hk_index"         | 3                 | 30s          | Sina 港股指数

熔断参数选择原则：
- 快失败（<500ms）自动 hard_failure → 立刻冷却，counter 清零
- 慢失败（超时）→ 正常记录，满 threshold 后冷却
- Yahoo 的 threshold 设为 2 + cooldown 120s，因 Yahoo 被墙从 Docker 是常见情况
```

**文件**：`backend/app/fetchers/fund_fetcher.py` + `backend/app/fetchers/global_markets_fetcher.py` + `backend/app/services/source_registry.py`

**工时**：2.5h

**验证项**：
1. 单元测试：mock route() 返回 None → 验证降级到默认 fallback
2. 单元测试：mock route() 返回 200 正常数据 → 验证解析正确
3. E2E：后端启动后验证 fund NAV 查询、HK 指数、Yahoo 数据均可正常获取
4. 熔断器：模拟 3 次连续失败 → 验证 source_registry 中对应源进入 cooldown

---

### 7.3 P2 — 性能优化

#### FIX-P01: 前端加载性能

**问题**：LCP 24.7s, Interactive 24.7s, CLS 0.538

**方案**：
```
1. API 调用超时机制：
   - axios 全局 timeout: 10s
   - 降级展示（骨架屏 + 错误提示）
   - 前端不因后端慢而阻塞渲染

2. ECharts 按需加载：
   - import { LineChart, BarChart } from 'vue-echarts'
   - 而非全量 import 'echarts'

3. CLS 修复：
   - 所有 <img> 标签添加 width/height 属性
   - 动态加载组件使用 placeholder 占位

4. Vite 构建优化：
   - 启用 rollupOptions.output.manualChunks 代码分割
   - 开启 CSS 代码分割
```

**文件**：`frontend/src/api/index.js`, `frontend/vite.config.js`

**工时**：4h

---

#### FIX-P02: ETF 扫描预热优化

**问题**：首次预热 ETF 扫描 7s（akshare demjson 4.2s）

**方案**：
```
1. 尝试替代方案：
    - 使用 Sina 直接 API（跳过 akshare 的 demjson 解析器）
    - 或替换 demjson 为 orjson（orjson 解析速度是标准 json 的~4x）

2. 缓存策略：
   - 将 ETF 列表缓存到文件（持久化）
   - 预热时先读取缓存，后台异步刷新
   - 缓存有效期：24h

3. 预热并行度：
   - ETF 扫描、行情缓存、全球指数三路并行执行
   - 当前已并行（asyncio.gather），但提前检查缓存
```

**文件**：`backend/app/fetchers/etf_scanner.py`

**工时**：3h

---

#### FIX-P03: pyinstrument async 模式修复

**问题**：`warmup_profiler.py` 使用 `async_mode="disabled"` 不捕获协程

**方案**：
```python
# 将 async_mode 改为 "enabled" 以捕获 async 协程
self._pyinstrument_session = Profiler(async_mode="enabled")
```

**文件**：`backend/app/profiling/warmup_profiler.py`

**工时**：0.2h

---

### 7.4 P3 — 架构/可维护性

#### FIX-A01: 预热性能 CI 门禁

**问题**：预热性能数据存在容器内，无自动检查

**方案**：
```
- 将 warmup_timing.json 复制到 CI artifact
- verify_e2e.py 增加检查：
  - 首次预热总时间 ≤ 15s（警告线）
  - 首次预热总时间 ≤ 30s（失败线）
  - 各阶段时间不超过 3 倍基线
```

**文件**：`backend/scripts/verify_e2e.py`

**工时**：1h

---

#### FIX-A03: verify_e2e.py 报告质量断言

**问题**：现有 `verify_e2e.py` 只检查"存在性"不检查"合理性"，空方案标记 full 不触发告警

**方案**：
```
在 verify_e2e.py 中增加断言：
1. 检查最新设计方案：strategies_json 中每个 strategy["etfs"] 至少有 3 只真实 ETF
2. 若某个 strategy 全为 CASH（无 real_etf_count），输出 FAIL 并打印 warning
3. 检查策略检查记录：holdings_json 不应为空（若有持仓数据）
4. 增加 report_quality 检查：若 quality="full" 但 real_etf_count=0，标记为 FAIL
5. 预热性能检测：首次预热 ≤15s（警告线）≤30s（失败线）
```

**文件**：`backend/scripts/verify_e2e.py`

**工时**：1h

---

#### FIX-A04: 启动时清理积压任务

**问题**：旧 session 遗留的 stuck 任务（103/106/107/110）持久化在 `backend/app/data/tasks.json`，容器重启后继续被加载，排进设计管线并触发因子计算，放大 retry 风暴

**方案**：
```
1. TaskManager 初始化时扫描 tasks.json
2. 清除所有状态为 "running" 但 age > 10 分钟的任务（或创建时间在 2 次启动前的任务）
3. 清除后写回 tasks.json
4. 同时在 Docker entrypoint 中添加清理步骤
```

**文件**：`backend/app/tasks/task_manager.py`

**工时**：0.5h

---

#### FIX-A02: Sentiment 缓存持久化

**问题**：sentiment 数据源不可用时无降级数据

**方案**：
```
- 将 sentiment 缓存写入磁盘文件（JSON）
- 重启时优先加载磁盘缓存
- 缓存 TTL：30 分钟
- 当所有数据源不可用时，使用缓存而非返回默认值
```

**文件**：`backend/app/services/pool_manager.py`

**工时**：2h

---

## 8. 结论与优先级建议

### 立即执行（P0 — 数据质量）

本次审计最严重的发现是：**系统在产生无意义的空方案时，用户看到的报告质量评估为 "full"，LLM 报告描述了详尽的分析但不基于真实数据**。这直接损害了用户对系统的信任。

**关于 sentiment 重试风暴的修正**（基于 2026-07-28 实测）：
- push2 HTTPS 拒绝连接耗时仅 0.1s（非原分析的 10s 超时），akshare fallback 同样失败（5.7s）
- 熔断器未生效的真正原因：`fundamentals_fetcher.py` 绕过 `registry.route()` 直连 push2，失败后不向熔断器报告
- 5s 间隔的真正来源：`factor_registry.py:504` 的 `run_in_thread(timeout=5)` 每次准时截断 akshare 等待
- `fetch_market_sentiment()` 入口因 `run_sync` 未 import 而静默报 NameError

建议优先级：
1. **先修报告质量门禁**（FIX-Q01/Q03/Q04）：让空方案不出现，而非生成误导性报告
2. **再修策略检查**（FIX-Q02）：让策略检查能实际工作
3. **然后修稳定性**（FIX-S01/S02/S03/S04/S05/A04）：让系统能可靠运行，消除 retry 风暴，所有数据链路纳入熔断器保护
4. **同时补测试防护**（FIX-A03）：在验证链路中加入质量断言
5. **最后做性能优化**（P2/P3）：在功能可靠的基础上优化体验

### 终止指标（Definition of Done）

每阶段完成后，确认以下条件满足再进入下一阶段：

| 阶段 | 终止条件 | 验证方法 |
|------|---------|---------|
| 阶段 1 (P0) | 空方案 report_quality ≠ "full"；策略检查返回非空报告 | `verify_e2e.py` 全 PASS + 人工走查 API 返回 |
| 阶段 2 (P1) | push2delay 正常返回数据；熔断器 3 次失败后 60s 冷却不再重试；基金净值/港股指数/Yahoo 均通过 registry.route() 调用；积压任务自动清理 | 模拟数据源不可用 → 观察熔断器冷却 + 60s 后半开；`source_registry._health` 中显示所有源的健康状态 |
| 阶段 3 (P2) | Lighthouse ≥60/100（Performance）；预热 ≤10s | Lighthouse CLI + `verify_e2e.py` |
| 阶段 4 (P3) | 预热性能基线写入 CI；缓存持久化覆盖 sentiment；验证 e2e 包含质量断言 | CI 跑通 + 日志无 regress |

### 测试防护增强要点

1. **FIX-A03**: `verify_e2e.py` 增加报告质量断言（设计方案 ETF 数量、report_quality 一致性）
2. 为分配引擎增加集成测试（mock 数据源，不 mock 分配结果）
3. 增加预热性能基线检查
4. 增加熔断器行为测试

---

## 9. 实施路线图

### 阶段 1（1-2 天）：P0 数据质量

| 顺序 | 任务 | 依赖 |
|------|------|------|
| 1 | FIX-Q01: 分配引擎门禁 | 无 |
| 2 | FIX-Q02: 策略检查管道修复 | 1 |
| 3 | FIX-Q03: report_quality 分级 | 1 |
| 4 | FIX-Q04: LLM 一致性校验增强 | 1 |
| 5 | FIX-A03: `verify_e2e.py` 增加报告质量断言 | 1 |
| 6 | 更新 `api-contracts/` 反映新字段 | — |

### 阶段 2（3-4 天）：P1 系统稳定性

| 顺序 | 任务 | 依赖 |
|------|------|------|
| 1 | FIX-S01: 熔断器接入 + push2delay 域名替换 + import 修复（A+B 合并方案） | 无 |
| 2 | FIX-S03: 任务管理器超时（含启动时清理积压任务） | 无 |
| 3 | FIX-S04: numba 日志降级 | 无 |
| 4 | FIX-S02: factor_registry 阻塞优化 | 1 |
| 5 | FIX-S05-A: fund_fetcher → registry.route() 接入 | 1（复用 S01 模式） |
| 6 | FIX-S05-B: global_markets_fetcher Tencent HK 指数接入 | 1（复用 S01 模式） |
| 7 | FIX-S05-C: global_markets_fetcher Yahoo Finance 接入 | 1（复用 S01 模式） |
| 8 | FIX-S05-D: 统一熔断源注册 | 5,6,7 |
| 9 | FIX-A04: 启动时清理积压任务 | 2 |
| 10 | 熔断器集成测试（覆盖所有已注册源） | 8 |

### 阶段 3（1-2 天）：P2 性能

| 顺序 | 任务 | 依赖 |
|------|------|------|
| 1 | FIX-P01: 前端加载性能 | 无 |
| 2 | FIX-P02: ETF 扫描预热优化 | 无 |
| 3 | FIX-P03: pyinstrument async 模式 | 无 |
| 4 | Lighthouse CI 门禁 | 1 |

### 阶段 4（1 天）：P3 可维护性

| 顺序 | 任务 | 依赖 |
|------|------|------|
| 1 | FIX-A01: 预热 CI 门禁 | 阶段 2 |
| 2 | FIX-A02: Sentiment 缓存持久化 | 阶段 2 |

---

## 附录 A：诊断工具使用记录

### 后端

| 工具 | 用途 | 执行方式 |
|------|------|---------|
| **cProfile** | 预热 CPU 热点分析 | `PROFILE_WARMUP=1` 环境变量，数据写入 `/app/logs/warmup_cprofile.txt` |
| **pyinstrument** | 预热采样分析（async-aware） | `PROFILE_WARMUP=1`，输出 HTML + TXT 报告 |
| **Timing JSON** | 预热各阶段耗时 | `PROFILE_WARMUP=1`，输出 JSON 结构化报告 |
| **curl** | API 端点响应时间 | Windows `curl.exe -s -w "%{time_total}"` |

### 前端

| 工具 | 用途 | 执行方式 |
|------|------|---------|
| **Lighthouse CLI** | 全链路性能审计 | `lighthouse http://localhost:5173 --chrome-flags="--headless --no-sandbox"` |

---

## 附录 B：现有完成方案质量对比

| Design ID | 报告长度 | 策略数据 | 真实 ETF 数量 | 现金比例 | report_quality | 评估 |
|-----------|---------|---------|:-----------:|:-------:|:-------------:|------|
| 217 | 7809B | 34482B | ✅ 有分配 | 波动 | full | ✅ 正常 |
| 218 | 9098B | 37834B | ✅ 有分配 | 波动 | full | ✅ 正常 |
| 219 | — | — | — | — | pending | ⚪ 未完成（可能被 retry 风暴阻塞） |
| 220 | — | — | — | — | pending | ⚪ 同上 |
| 221 | — | — | — | — | pending | ⚪ 同上 |
| 222 | 551B | 416B | 0 | 100% | full | 🔴 空方案 |
| 223 | 3225B | 1920B | 0 | 100% | full | 🔴 空方案 |
| 224 | 3115B | 1914B | 0 | 100% | full | 🔴 空方案 |

**结论**：ID 217-218 是最后已知的正常方案。219 之后出现的空方案问题需要追溯根因。
