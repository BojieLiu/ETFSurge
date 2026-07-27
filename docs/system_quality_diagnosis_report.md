# ETF Surge 系统质量诊断报告

> 生成日期：2026-07-27 | 最后更新：2026-07-27
> 诊断范围：组合设计质量、前后端性能、测试防护体系有效性
>
> ## 修复跟踪 (2026-07-27 实施)
>
> | 条目 | 状态 | 改动 |
> |------|------|------|
> | 7.1 池弹性 (first-run CRITICAL log) | ✅ `pool_manager.py` | 首次刷新生效时输出 CRITICAL 日志 + `_consecutive_failures` 计数 |
> | 7.2c Admin metrics 端点 | ✅ `admin.py` | `GET /admin/metrics` 返回池健康 / 设计成功率 / 连续失败计数 |
> | 7.5a 池弹性集成测试 | ✅ `tests/test_pool_resilience.py` | 5 个测试覆盖：CRITICAL 日志、失败计数、_last_good 回退、成功复位、保底标的 |
> | 7.5b verify_e2e 增强 | ✅ `verify_e2e.py` | risk_warnings 非空断言 + 类型校验 + response time gate + admin/metrics 检查 |
> | 7.5c 性能基准测试 | ✅ `tests/test_performance_benchmark.py` | /health(<3s) /etfs(<1s) /designs(<2s) /factors(<1s) /admin/metrics(<2s) |
> | 7.6a 组合实时行情缓存 | ✅ `market_service.py` | `get_portfolio_realtime()` 添加 15s 应用级内存缓存 |
> | 7.7 ETF 扫描熔断路由 | ✅ `etf_scanner.py` | `fetch_all_etfs_base()` 迁移到 `registry.route()`，3 源熔断保护 |

---

## 目录

1. [执行概要](#1-执行概要)
2. [组合设计与策略检查质量评估](#2-组合设计与策略检查质量评估)
3. [前端性能诊断](#3-前端性能诊断)
4. [后端性能诊断](#4-后端性能诊断)
5. [测试防护体系缺口分析](#5-测试防护体系缺口分析)
6. [根因综合分析](#6-根因综合分析)
7. [改进建议](#7-改进建议)

---

## 1. 执行概要

### 核心结论
- **组合设计质量严重退化**：最新 6 个设计方案（ID 219-224）产出 0 只 ETF，而此前方案（ID 218）成功产出 27 只。该退化未被任何测试或 CI 门禁发现。
- **前端性能极差**：Lighthouse 评分 **17/100**，LCP 达 **25.1 秒**，TTI 达 **25.1 秒**。
- **后端 API 响应慢**：关键 API 平均 2-8 秒，部分端点因同步 I/O 阻塞事件循环高达 10 秒。
- **测试防护体系存在系统性缺口**：全部 7 个设计相关测试文件均使用 Mock 数据，无任何端到端数据管道验证。

### 关键数据
| 指标 | 值 | 目标 |
|------|-----|------|
| 前端 Lighthouse 性能分 | 17/100 | ≥ 90 |
| 首屏时间 (FCP) | 4.8s | < 2s |
| 最大内容绘制 (LCP) | 25.1s | < 2.5s |
| 交互时间 (TTI) | 25.1s | < 3.5s |
| 后端 API 平均响应 | 946ms | < 200ms |
| 组合设计成功率（最近 6 次） | 0% | 100% |
| 测试覆盖率（数据管道） | ~0% | 关键路径 100% |

---

## 2. 组合设计与策略检查质量评估

### 2.1 组合设计退化分析

#### 退化证据
对 10 个最新设计方案的 ETF 数量统计：

| 设计 ID | 创建时间 | 状态 | ETF 数量 | 方案质量 |
|---------|---------|------|---------|---------|
| 224 | 07-26 02:58 | completed | **0** 只 | ❌ 全空 |
| 223 | 07-26 02:58 | completed | **0** 只 | ❌ 全空 |
| 222 | 07-25 16:35 | completed | **0** 只 | ❌ 全空 |
| 221 | 07-25 16:20 | completed | **0** 只 | ❌ 全空 |
| 220 | 07-25 16:15 | completed | **0** 只 | ❌ 全空 |
| 219 | 07-25 16:06 | completed | **0** 只 | ❌ 但 non-null |
| 218 | 07-25 08:35 | completed | **27** 只 | ✅ 完整 |
| 217 | 07-25 03:27 | completed | **27** 只 | ✅ 完整 |
| 216 | 07-24 16:49 | completed | 0 只 | ❌ |
| 215 | 07-24 16:47 | completed | 0 只 | ❌ |

**退化分界点**：ID 218 → 219 之间（07-25 08:35 → 07-25 16:06）。

#### 退化根因
代码分析表明，组合设计流程为：

```
generate_enhanced_design()
  → pool_manager.refresh()          # 刷新数据管道
    → scanner.full_pipeline()        # 扫描全市场 ETF（可能失败）
  → pool_manager.get_pool("core")    # 读取候选池
  → pool_manager.get_factor_matrix() # 读取因子矩阵
  → engine_allocate()                # 分配权重
  → 持久化
```

**退化机制**：
1. `scanner.full_pipeline()` 对外调用 `akshare.fund_etf_spot_em()` 等 API
2. 当数据源 API 超时/失败时，`_refresh_impl()` 捕获异常并返回空池（line 270-273）
3. `generate_enhanced_design()` 检测到 `total_candidates == 0`，返回 `strategies: []`
4. **关键问题**：尽管返回空方案，依然返回 `"status": "completed"` — 没有错误标记
5. 空方案被持久化时，`etf_count` 被记为 `0`，但 `error_message` 为 `null`

**设计文本质量问题**：
- **ID 218**（27 只 ETF）：19,715 字节的完整设计文本，包含因子评分、技术指标、板块分布、预期收益估算、免责声明
- **ID 219**（2 只 ETF）：仅 887 字节，仅有 510300 和 518880，无因子评分细节
- **ID 220-224**（0 只 ETF）：更短，仅有表格框架无实际内容

#### 退化深层原因：数据管道脆弱性

`_refresh_impl()` 中 `scanner.full_pipeline` 调用链路：
```
run_sync_long(scanner.full_pipeline, timeout=60)
  → asyncio.wait_for(..., timeout=90)
```

`full_pipeline` 内部调用：
- `fetch_all_etfs_base()` → `akshare.fund_etf_spot_em()` — **同步 HTTP**
- `filter_etfs()` → pandas 操作
- `classify_etf()` → 分类逻辑
- `layer_ranking()` → 排序逻辑

当 East Money API 限流或超时时，整个链路会阻塞事件循环长达 60-90 秒。两次失败后，TTL 机制返回缓存但缓存可能失效。

### 2.2 策略检查质量评估

策略检查（ID 109）内容评估：

- **市态判断**：`range_bound`（区间震荡）— 合理，与情绪数据一致
- **建议动作**：3 条增持 + 3 条减持 + 2 条风险警告
- **数据基础**：标记 `因子数据 10/10 正常`
- **逻辑性**：KDJ 金叉买入逻辑合理，ATR 波动低位反弹逻辑成立
- **可读性**：中文通顺，建议具体

**已修复**：`portfolio_service.py` 第 543–569 行已增加 `_combine_risk_warnings()` + `_compute_risk_warnings()`，确保 `risk_warnings` 至少包含规则驱动的行业集中度/个股权重/流动性三类警告，不再为空。

**剩余问题**：
1. 未附具体行情数据引用（如当前价格、涨幅）
2. 建议置信度全为 "medium"，缺乏 high/low 区分
3. 未提供量化回测依据

### 2.3 小结

| 维度 | 评分 | 说明 |
|------|------|------|
| 逻辑性 | ★★☆ | 策略检查 OK，设计方案退化严重 |
| 可读性 | ★★★ | 中文输出质量可接受 |
| 数据完整性 | ★☆ | 近期方案 ETF 为 0，无因子数据 |
| 准确性 | ★★ | 有数据的方案合理，空方案未标记错误 |
| 投资判断科学性 | ★★☆ | 因子评分体系合理，但缺少数据支撑 |
| 因子缺失 | ★☆ | 近期方案全部缺失 |
| 退化检测 | ✗ | 未识别数据管道故障 |

---

## 3. 前端性能诊断

### 3.1 诊断工具与方法
- **Lighthouse 13.41**：Headless Chrome 全页面审计
- **Playwright Chromium**：浏览器自动化
- **Vite 构建分析**：基于 `package.json` 和 `vite.config.js`

### 3.2 Lighthouse 评分
| 类别 | 得分 | 评级 |
|------|------|------|
| **Performance** | **17/100** | 🔴 极差 |
| Accessibility | 96/100 | 🟢 优秀 |
| Best Practices | 96/100 | 🟢 优秀 |
| SEO | 82/100 | 🟡 良好 |

### 3.3 核心 Web 指标

| 指标 | 实测值 | 目标值 | 差距 |
|------|--------|--------|------|
| First Contentful Paint (FCP) | **4.8s** | < 1.8s | 3.0s ❌ |
| Largest Contentful Paint (LCP) | **25.1s** | < 2.5s | 22.6s ❌ |
| Speed Index | **8.3s** | < 3.4s | 4.9s ❌ |
| Total Blocking Time (TBT) | **830ms** | < 200ms | 630ms ❌ |
| Cumulative Layout Shift (CLS) | **0.538** | < 0.1 | 0.44 ❌ |
| Time to Interactive (TTI) | **25.1s** | < 3.8s | 21.3s ❌ |
| 主线程工作 | **4.1s** | < 2.0s | 2.1s ❌ |

### 3.4 诊断发现

#### 发现 1：JS 负载过大（P0-关键）
- **总计 4,066 KiB** 网络传输
- 未使用的 JS **1,840 KiB**（占 45%）
- 可压缩的 JS **1,496 KiB**

**根因**：
- ECharts（`echarts: ^5.5.0`）包体积大，约 1MB+
- 虽配置了 `manualChunks` 分离 vendor，但开发模式不生效
- Dashboard 直接导入 `VChart from 'vue-echarts'`，ECharts 被包含在主 bundle 中
- 未使用路由级代码分割（虽路由使用 `() => import`，但 ECharts 在 Dashboard 直接导入）

#### 发现 2：无服务端/流式渲染（P0-关键）
- 所有 API 请求在客户端 `onMounted` 中依次发起
- 无 SSG/SSR 策略
- 无渐进式内容展示
- 大量的串行 API 请求导致渲染阻塞

#### 发现 3：布局稳定性差（P1-重要）
- CLS 0.538：图表和数据表格在加载过程中频繁重排
- 可能是因为 ECharts 图表初始化为空，数据到达后重绘导致布局变化
- 图表容器未设置固定宽高比

#### 发现 4：无缓存策略（P2-中等）
- 虽有 PWA 和 workbox 配置，但 `NetworkFirst` 策略在开发模式下作用有限
- 未使用 `localStorage`/`IndexedDB` 缓存行情数据
- 每次页面刷新都重新拉取全部数据

#### 发现 5：阻塞渲染资源（P2-中等）
- Vue SPA 的 `app.js` 和 `vendor-vue.js` 均为同步加载
- 无 `preload`/`prefetch` 策略

#### 发现 6：无骨架屏/加载占位效果（P3-低优）
- 虽有 `Skeleton` 组件但使用有限
- 大块区域（图表、表格）在数据加载完成前直接白屏

---

## 4. 后端性能诊断

### 4.1 诊断工具与方法
- **多次 HTTP 请求采样**（每端点 3 次，取均值/最大/最小）
- **`py-spy`** / **`memory-profiler`** 安装备用
- **后端日志分析**

### 4.2 API 响应时间全景

| 端点 | 平均 | 最小 | 最大 | 判定 |
|------|------|------|------|------|
| /health | **726ms** | 12ms | 2,145ms | 🔴 首次慢不稳定 |
| /portfolio/etfs | 23ms | 22ms | 24ms | 🟢 |
| /portfolio/designs | 32ms | 29ms | 36ms | 🟢 |
| /portfolio/strategy-checks | 82ms | 78ms | 89ms | 🟢 |
| /market/sentiment | **417ms** | 14ms | 1,221ms | 🟡 波动大 |
| /market/indices/global | **2,019ms** | 12ms | 6,023ms | 🔴 极差 |
| /market/realtime/portfolio | **8,617ms** | 7,158ms | 10,550ms | 🔴 极差 |
| /news/headlines | **3,506ms** | 21ms | 10,473ms | 🔴 极差 |
| /factors/active | 12ms | 10ms | 14ms | 🟢 |

### 4.3 诊断发现

#### 发现 1：同步 I/O 阻塞事件循环（P0-关键）

**证据**：
- `/market/realtime/portfolio` 耗时 **8.6 秒**（期间健康检查也受影响）
- 方差极大：最低 21ms（缓存命中） vs 最高 10,473ms（缓存未命中）
- 后端日志显示大量 `urllib3` 同步 HTTP 请求

**问题代码路径**：
```
/market/realtime/portfolio
  → market_service.py
    → china_market.fetch_realtime()  — 同步 requests.get()
    → / 或 akshare 同步调用

/news/headlines
  → news_fetcher.py
    → akshare 同步 HTTP 调用
    → urllib3 同步连接

/market/indices/global
  → market_service.get_global_indices()
    → yfinance / akshare 同步 HTTP 调用
```

**根因**：后端大量使用同步 I/O（akshare、yfinance、requests、urllib3）直接运行在 async 事件循环上，未通过 `run_sync()`/`asyncio.to_thread()` 桥接。尽管 AGENTS.md 明确要求：
> "任何 async def 函数内部若直接调用同步 I/O...会阻塞整个事件循环。正确做法：用 await run_sync(call, *args) 提交到线程池。"

#### 发现 2：缓存策略不足（P0-关键）

- `/market/realtime/portfolio` 无有效的 TTL 缓存（每次都发起实时请求）
- `/news/headlines` 无应用层缓存
- 缓存仅存在于 `pool_manager`（60s TTL），但市场行情 API 不走 pool
- 即便 60s TTL，在 TTL 窗口内同一请求仍会重复加载

#### 发现 3：外部 API 缺乏熔断保护（P1-重要）

- 单个 East Money API 超时会导致整个 `/news/headlines` 端点挂起 10 秒
- 多个 ETF 的 F10 历史数据请求呈并发爆发（后端日志显示同时几十个 HTTP 连接）
- 无可靠的 fallback 链验证（ADMIN 页面显示 sources health 但实际故障转移路径未经 e2e 验证）

#### 发现 4：设计/策略检查任务阻塞事件循环（P0-关键）

`design-async` 和 `strategy-check-async` 使用 `asyncio.create_task()` 启动后台任务，但任务内部：
- `design_worker` → `generate_enhanced_design()` → `pool_manager.refresh()` → `scanner.full_pipeline()` — 同步 I/O
- 后台任务中若有同步阻塞调用，会导致整个事件循环卡死

**验证**：本次诊断中执行 `POST /design-async` 后，后端所有端点（包括 `/health`）在约 90 秒内完全无响应。

#### 发现 5：高频日志写压力（P2-中等）

- `backend.log.1` 包含大量 DEBUG 级 `urllib3` 日志
- 每个 ETF 的历史数据请求都记录了请求和响应的完整 URL
- 在扫描 200+ ETF 时，日志文件会膨胀数 MB

---

## 5. 测试防护体系缺口分析

### 5.1 现有测试覆盖

| 测试文件 | 用例数 | Mock 程度 | 覆盖范围 |
|---------|--------|----------|---------|
| test_design_optimization_plan.py | 7+ | 全 Mock | 引擎层逻辑验证 |
| test_design_integration.py | 生产等价 | 全 Mock | ETF 分配器去重逻辑 |
| test_design_pipeline_integration.py | 5 | 全 Mock | 管道调度 |
| test_design_cascade_failure.py | 1+ | 全 Mock | 空池场景 |
| test_design_tasks.py | 6+ | 全 Mock | TaskManager CRUD |
| test_design_new_modules.py | 10+ | 全 Mock | Scanner 分类逻辑 |
| test_design_status.py | 5+ | 全 Mock | 设计状态管理 |
| test_async_boundaries.py | 1 | 部分 Mock | FactorRegistry 异步边界 |
| test_async_lint.py | 5+ | 无 Mock | AST 静态扫描检查 |
| test_concurrency_guard.py | 1 | 无 Mock | 健康端点响应时间 |
| test_decode.py | 11 | 无 Mock | 编码修复逻辑 |

### 5.2 系统性缺口

#### 缺口 1：全 Mock 数据管道 — 无真实数据集成测试（P0）

**问题描述**：所有 7 个设计相关测试文件均 Mock 了 `scanner.full_pipeline`、`classifier.batch_classify`、`factor_registry.compute`。
Mock 数据总是返回非空、格式良好的 DataFrame/dict。

**为什么 CI 没发现**：
- Mock 数据永远不超时、永远不返回空值
- Mock 的 DataFrame 列名永远正确
- 真实的 `akshare` 返回列名可能是乱码（latin1 编码），Mock 数据无此问题
- 边界测试（`test_design_cascade_failure.py`）Mock 了 `get_pool` 返回空列表，但该测试只验证引擎不崩溃，不验证：
  - 是否标记了错误
  - 是否持久化了空方案
  - 是否有监控告警

#### 缺口 2：无管道数据新鲜度测试（P1）

- 无测试验证 `pool_manager` 的候选池在重新启动后是否非空
- 无测试验证 ETF 缓存刷新是否成功
- 无测试验证因子矩阵是否包含关键 ETF

#### 缺口 3：无性能基准测试（P0）

- 无任何测试断言 API 响应时间
- `conftest.py` 仅抑制 HTTP 泄漏，无性能阈值
- Lighthouse 审计从未集成到 CI

#### 缺口 4：异步阻塞检测不完整（P1）

- `scripts/audit_async_blocking.py` 是 AST 静态扫描，只能检测简单的 `ak.function()` 调用模式
- 无法检测通过变量间接调用的阻塞操作（如 `fetcher = getattr(akshare, func_name); fetcher()`）
- 无法检测通过 `run_sync` 提交的长时间运行线程（虽然不是阻塞事件循环，但会占用线程池资源）
- 无法检测链式调用中的阻塞（`a().b().c()` 中间任一环节可能阻塞）

#### 缺口 5：E2E 验证脚本部分验证内容但缺少时序与风险检查（P2）

`scripts/verify_e2e.py` 已检查设计内容质量（第 245–263 行）：
- `design_text` 长度 > 200 字 + 包含"三种方案详解"
- 每套策略有 >= 1 只非 CASH 标的
- 每只标的的入选理由非空
- 总策略数 >= 2
- 设计文本长度 > 1000 字

**但缺少以下检查：**
- 响应时间断言（无任何 timeout < 具体值的门禁）
- `risk_warnings` 非空断言
- 因子评分完整性检查

#### 缺口 6：组合设计中 "completed" 状态误导（P0）

**背景**：`task_manager.py` 第 321–346 行已上线修复 A（校验降级），空策略会被填入全 CASH 保留而非直接失败，`error_info` 检查（第 306–312 行）也已捕获 `generate_enhanced_design()` 返回的 error 字段。

**剩余问题**：
- `strategy_design.py` 第 59–68 行：候选池为空时返回 `error: "无候选标的"` + `detail` 字段，但 DB 持久化层（`save_design()`）在任务被标记为 `failed` 后仍可能尝试写入"空"设计方案（时序竞态）
- 如果 `generate_enhanced_design()` 返回空 `strategies` 且不携带 `error` 字段（如异常路径），则校验逻辑走不到 `error_info` 检查，直接进入 `if not strategies:` 分支
- `design_worker`（与 `design_pipeline` 不同入口）可能未同步上述修复逻辑
- 无监控告警：即使任务失败，运维人员无法主动感知

---

## 6. 根因综合分析

### 6.1 问题关联图

```
数据源异常（EastMoney 限流/超时）
        │
        ▼
  scanner.full_pipeline() 失败
        │
        ▼
  pool_manager.refresh() 返回空池
        │
        ├──▶ generate_enhanced_design() → 空 strategies → saved as "completed"
        │
        ├──▶ mock 测试无法捕获（Mock 数据永不失败）
        │
        ├──▶ E2E 只检查 HTTP 200，不验证内容
        │
        └──▶ 无性能监控
                │
                ▼
        前端 LCP 25s + 后端 API 8s
```

### 6.2 测试防护失效的元分析

| 保护层 | 预期职能 | 实际效果 | 失效原因 |
|--------|---------|---------|---------|
| 单元测试 (pytest) | 验证核心逻辑 | ❌ Mock 全部外部依赖 | 测试设计早于数据管道稳定化 |
| 异步阻塞审计 | 检测同步 I/O | ⚠️ 部分有效 | 只能检测简单模式 |
| pre-commit 门禁 | 阻止构建错误 | ⚠️ 检查 Vue 编译 | 不检查数据质量 |
| E2E 验证 | 验证核心链路 | ⚠️ 检查 HTTP 状态 | 不验证内容/时序 |
| 运行时异常 | 失败时标记错误 | ❌ 静默降级 | 空候选池被视为正常路径 |

### 6.3 风险矩阵

| 风险 | 可能性 | 影响 | 优先级 |
|------|--------|------|--------|
| 数据管道再次崩溃 → 生产环境用户看到空方案 | 高 | 高 | P0 |
| 前端加载过慢 → 用户流失 | 高 | 高 | P0 |
| 异步阻塞导致后端完全无响应 | 中 | 极高 | P0 |
| East Money API 限流 → 关键功能不可用 | 高 | 高 | P1 |
| LLM 调用超时 → 报告降级 | 中 | 中 | P1 |
| 行情数据缓存过期 → 投资决策依据过时 | 高 | 中 | P1 |

---

## 7. 改进建议

### P0 — 立即执行（本周）

#### 7.1 数据管道弹性修复
- **改造点**：`pool_manager._refresh_impl()` 在 scanner 失败时使用前一次成功池（`_last_good` 已定义但未充分使用）
- **验证**：重启后端后验证池非空
- **验收标准**：`warmup.etf_cache.done == true && warmup.etf_cache.success == true`

#### 7.2 空方案告警增强（部分已修复）

**已上线**：`task_manager.py` 第 306–312 行已检查 `error_info` 并标记 failed；第 321–346 行已将空策略填入全 CASH 保留。

**剩余待做**：
- `save_design()` 增加时序保护：仅在任务状态为 `"completed"` 时才写入 DB
- DB 持久化层在 `etf_count == 0` 时标记 `status = "degraded"` 而非 `"completed"`
- 监控：增加 Prometheus/metrics 端点到 `/admin` 路由

#### 7.3 异步边界修复（部分已处理）

**已上线**：部分代码已使用 `run_sync_in_thread()`/`run_sync_long()`（如 `pool_manager._refresh_impl` 中的 scanner 调用）；`scripts/audit_async_blocking.py` 提供 AST 静态扫描。

**剩余待做**：
- 所有同步 I/O 调用（akshare、requests、urllib3）必须通过 `run_sync()`/`asyncio.to_thread()`
- 检查清单：`market_service.py`、`news_fetcher.py`、`china_market.py`、`etf_scanner.py`、`fundamental_fetcher.py`（合计约 50+ 处外部调用）
- 将 `audit_async_blocking.py` 从静态 AST 升级为运行时监控（如 `sys.settrace` 或 `wrap_async_handler`）
- 验证：`test_async_boundaries.py` 扩展到覆盖所有外部调用路径

#### 7.4 前端加载优化
- **ECharts 按需导入**：改为 `import { use } from 'echarts/core'` 仅导入所需图表类型
- **路由级代码分割**：确认 Dashboard 的主 bundle 不含非必要 ECharts 代码
- **骨架屏**：每个数据区域在加载时显示 Skeleton 占位

### P1 — 本周内

#### 7.5 测试防护增强

**已上线**：`verify_e2e.py` 第 245–263 行已包含设计内容质量检查（design_text 长度、非 CASH 标的、入选理由、策略数量）。

**剩余待做**：
- 添加 1 个集成测试：不 Mock 数据管道，验证 `_refresh_impl()` 返回非空池（若 API 不可用则 skip）
- 性能基准测试：在 CI 中添加 `pytest --benchmark` 或独立性能脚本
- `verify_e2e.py` 增加：`risk_warnings` 非空断言、因子评分完整性断言、响应时间门禁

#### 7.6 缓存策略
- `/market/realtime/portfolio` 添加 15s 应用层缓存
- `/news/headlines` 添加 60s 缓存
- 缓存过期标记：数据源失败时返回缓存旧数据 + `"stale": true` 标记

#### 7.7 熔断器
- 外部 API 调用统一使用超时 + 重试 + 回退链
- East Money API 限流时自动切换到 akshare fallback

### P2 — 下阶段

#### 7.8 CI/CD 集成
- Lighthouse CI 接入 GitHub Actions
- 性能阈值门禁：LCP < 3s, TBT < 300ms
- API 响应时间门禁：95% API < 1s

#### 7.9 监控体系
- 组合设计成功率仪表盘
- 数据管道健康度时间线
- 前端 Web Vitals 实时监控

---

## 附录 A：诊断方法

- **后端诊断**：PowerShell `Invoke-WebRequest` 多次采样 + 后端日志分析 + 代码审查
- **前端诊断**：Lighthouse 13.4.1 Headless Chrome 审计 + Playwright Chromium
- **测试分析**：审阅 `backend/tests/` 和 `backend/conftest.py` 全部 7 个设计相关测试文件 + 3 个辅助测试（async_lint、concurrency_guard、decode）
- **代码审查**：审查 `pool_manager.py`（792 行）、`strategy_design.py`（214 行）、`allocation_engine.py`、`portfolio.py` 路由

## 附录 B：验证数据

- **后端端点总数**：API 列表 56 条路由（OpenAPI）
- **已测试端点**：17 个（涵盖所有关键路径）
- **前端页面数**：8 个路由，全部使用懒加载
- **测试代码行**：11 个相关测试文件合计约 95,000 字节（含 7 个设计测试 ~71KB + 4 个辅助测试 ~27KB）
- **Git 历史**：主分支 main，最近活跃
