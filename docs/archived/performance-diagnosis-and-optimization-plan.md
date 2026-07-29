# ETF Surge 性能诊断与优化方案

> 撰写日期：2026-07-28 | 最后更新：2026-07-28（v5）
> 诊断范围：后端预热性能、组合设计管线超时、线程池架构、数据源可靠性、测试防护体系
> 审阅轮次：v5（新增 §3.4-3.6 测试防护缺口 T1-T5 分类分析 + §4.0 T级缺口→修复方案对应关系 + OPT-16 红绿切换回归测试门禁）
> 
> **核心问题**：过去 3 天内同一类问题被修复 2 次但第 3 次复发，本方案不治标而是修复"为什么会复发"的工程体质。

---

## 一、后端预热性能诊断

### 1.1 诊断方法

通过 `PROFILE_WARMUP=1` 环境变量启用内置的 `WarmupProfiler`，同时采集三路数据：
- **warmup_timer**: 细粒度阶段计时（输出 `warmup_timing.json`）
- **cProfile**: CPU 调用统计（输出 `warmup_cprofile.txt`）
- **pyinstrument**: 采样实时调用栈（输出 `warmup_pyinstrument.html` / `.txt`）

### 1.2 关键数据

**warmup_timing.json**（活跃计时段合计 9129ms, 总 elapsed 201s）：

| 阶段 | 耗时(ms) | 占比 | 说明 |
|------|---------|------|------|
| warmup_market_cache | 5422 | 59.4% | 最慢，akshare HTTP I/O |
| warmup_global_indices | 3371 | 36.9% | 次慢，DNS + HTTP |
| redis_init | 244 | 2.7% | |
| init_db | 40 | 0.4% | |
| warmup_etf_cache | 52 | 0.6% | |

**CPU 耗时（cProfile 5.653s CPU 时间）**：

| ncalls | cumtime | 函数 |
|--------|---------|------|
| 10 | 7.215s | `china_market.py:749(fetch_fund_nav)` |
| 1 | 5.620s | `sentiment_fetcher.py:155(fetch_advance_decline_ratio)` |
| 1 | 4.926s | akshare `stock_zh_a_spot_em` (58 页分页) |
| 694 | — | `{method 'acquire' of '_thread.lock'}` 锁竞争高 |

### 1.3 时间去哪了

总 elapsed **201s**，但计时段仅 **9.1s**。差值 ~192s 的构成：

1. **`asyncio.wait(_warmup_tasks, timeout=130)`** — 等待三个后台预热任务完成，超时 130s
   - `warmup_etf_cache`: 有 120s 内部超时，通常 1-2s 完成
   - `warmup_global_indices`: 有 30s 内部超时，实际 3.4s
   - `warmup_market_cache`: 有 25s 内部超时，实际 5.4s
   - `asyncio.wait()` 要等所有任务完成或超时才返回 → 最小 120s+（等待 etf scan）
2. **后台循环启动延迟**：sector refresh 循环有 `asyncio.sleep(10)`，IC 持久化循环有 `asyncio.sleep(30)`
3. **模块导入时间**：lazy import 的冷启动时间

### 1.4 诊断结论

预热瓶颈在 I/O 等待层，CPU 时间仅 5.6s，无显著计算瓶颈。201s 的总 elapsed 时间 <= 设计值（130s wait + 后台循环初始化），非异常但不理想。

---

## 二、组合设计管线超时根因分析

### 2.1 问题现象

通过 `POST /api/v1/portfolio/design-async`（capital=500000）提交设计任务后，**连续 4 次均超时**，错误一致："方案生成超时，数据源响应过慢，请稍后重试"

### 2.2 完整调用链

```
POST /design-async
  └─ design_pipeline(task_id)                    [task_manager.py:261]
       └─ asyncio.wait_for(generate_enhanced_design(), timeout=90)
            ├─ pool_manager.refresh()
            │    ├─ scanner.full_pipeline (run_sync_long, 60s)
            │    └─ factor computation (run_sync, 77× K-line, 20s each)
            │
            ├─ _build_market_context()
            │    ├─ **_compute_fund_flow()**  ← ← ← 主瓶颈
            │    │    └─ asyncio.gather(77× **run_sync**(fetch_fund_flow, 8s))
            │    │         └─ fetch_fund_flow → **run_in_thread**(_p, 8s)
            │    │              ├─ akshare → **push2.eastmoney.com** (TLS RST)
            │    │              └─ *注意: run_in_thread 硬编码共享池！*
            │    │
            │    └─ sentiment cache refresh (run_sync, 15s × 3)
            │
            ├─ engine_allocate()              ← 纯函数
            └─ generate_design_report()       ← LLM (~30-90s)
```

### 2.3 根因定位

**直接原因**：`_compute_fund_flow()` 对 77 只 ETF 并发调用 `fetch_fund_flow()`，每路都访问已完全不可达的 `push2.eastmoney.com`。

**架构层面的根本原因（这才是关键的）**：

```
run_sync(fetch_fund_flow, sym, timeout=8)
  │
  ├─ 外层: loop.run_in_executor(_shared_executor, ...)   # 占 1 个共享池线程
  │
  └─ 内层: run_in_thread(_p, timeout=8)
       └─ future = _shared_executor.submit(fn, ...)       # 再占 1 个共享池线程 ← 同一个池！
```

**一个请求占 2 个共享池线程**。77 个并发 → 154 个线程需求 → 64 线程池的 2.4x 超配。

### 2.4 数据源测试验证

| 数据源 | 测试结果 | 诊断结论 |
|--------|---------|----------|
| `push2.eastmoney.com:443` | TLS 连接立即被 RST | 服务器主动拒绝连接 |
| `money.finance.sina.com.cn` | ✅ HTTP 200 | 正常工作 |
| akshare `stock_individual_fund_flow` | ❌ | 内部依赖 push2 |

### 2.5 线程池饱和度定量分析

```
共享线程池:     max_workers=64 (35 处调用点)
长任务线程池:   max_workers=8  (仅 1 处调用点, scanner)

_run_in_thread 调用点: 全代码库约 40 处, 全部硬编码共享池
```

T+0s — 77 个 `run_sync` 涌入共享池，64 个立即占满，13 个排队
T+0s — 每个 `fetch_fund_flow` 再调 `run_in_thread`，queue 再深 64
T+8s — `asyncio.wait_for` 超时，但线程还在等 push2 的 8s timeout
T+8~16s — 线程逐一释放
T=16s — 全部释放，但 90s 总预算已被消耗 ~16s + 因子计算
           → 留给 LLM 报告的时间不足（LLM 本身需 30-90s）

**结论**：即使 push2 正常，90s 也不够用。需要超时预算拆分。

---

## 三、测试防护体系缺陷分析

### 3.1 现有测试防护覆盖

| 防护层 | 文件 | 作用 | 未能捕获该类错误的根因 |
|--------|------|------|----------------------|
| E2E 链路验证 | `scripts/verify_e2e.py` | 核心端点存活 + 数据完整性 | 只检查返回字段，不模拟数据源故障 |
| 后端单测 | `tests/` (pytest) | 模块级功能验证 | 全部 mock 外部 HTTP，不暴露真实连接问题 |
| 并发限流 | Semaphore(1) | 防止多设计任务叠加 | 只防叠加，不防单一任务卡死 |
| 数据源健康探活 | `source_health.py` | 每 120s 探测各数据源 | **只写日志，无熔断动作** |
| 线程池队列告警 | `async_utils.py` | 队列深度 > 16 时 ERROR | **只写日志不降级** |
| `run_in_thread` | `async_utils.py:31` | 同步包装 | **硬编码共享池，无池选择参数** |

### 3.2 缺失的关键机制

1. **熔断器覆盖不全** — `SourceRegistry` [services/source_registry.py] 已存在但只覆盖了 5 个模块，**14 个有外部 API 调用的模块未接入**
2. **`factor_registry.py` 自建了重复的 `CircuitBreaker`** — 没复用已有的 `SourceRegistry`，造成两份熔断状态
3. **无池选择机制的 `run_in_thread`** — 所有内部调用锁死共享池
4. **无失败快速降级** — `_compute_fund_flow` 单请求等 8s 超时
5. **无并发量控制** — 77 并发无 Semaphore
6. **无超时预算拆分** — 90s 单一大锅
7. **无自动化池分配审计** — 无 lint 规则检查 run_sync timeout > 5s 的调用

### 3.3 为什么现有测试未能捕获

- 单元测试 100% mock 外部依赖：绕过了真实线程池和数据源
- E2E 测试无故障注入：从未测试数据源全部熔断的场景
- 无压力测试：从未模拟 77 并发请求线程池
- **无架构合规测试**：没有检查"run_sync 的 timeout 参数是否在合理范围内的测试"

### 3.4 分类：测试防护体系的 5 级缺口

| 级别 | 缺口类型 | 说明 | 典型例子 |
|------|---------|------|---------|
| **T1** | 测试范围缺口 | 特定路径/模块/失败模式没有测试覆盖 | `_compute_fund_flow` 没有单独的集成测试 |
| **T2** | 测试深度缺口 | 有测试但条件太弱，无法捕获高强度场景 | `test_concurrency_guard` 测 16 路×300ms，实际场景 77 路×8s |
| **T3** | 模拟策略缺口 | mock 了全部外部依赖，绕过了真实线程池/网络 | `test_pool_resilience` mock 了 scanner 全链路 |
| **T4** | 架构合规缺口 | 没有自动检查机制验证架构约束未被违反 | 无 "所有 fetcher 必须接入 SourceRegistry" 测试 |
| **T5** | 回归防护缺口 | 修复后没有追加红绿切换测试 | Phase 10 池修复后未新增回归测试 |

### 3.5 逐项分析：为什么现有哪些防护挡不住本次漏洞

#### 漏洞 1：`fundamental_fetcher` 未接入 SourceRegistry

```
有测试吗？    ├─ test_source_health.py (3.2KB) → 只测探针注册和执行，不检查覆盖范围
             ├─ test_fundamental_fetcher.py (5KB) → mock 了 akshare，不经过真实网络
             └─ 无 SourceRegistry 覆盖范围检查 → ❌ T4 架构合规缺口
为什么没挡住？  测试 mock 了全部外部调用，且没有架构断言说所有 fetcher 必须注册到 SourceRegistry
```

#### 漏洞 2：`_compute_fund_flow` 77 并发无批次限制

```
有测试吗？    ├─ test_design_optimization_plan.py (25KB) → mock 了 generate_enhanced_design 的返回值
             ├─ test_concurrency_guard.py → 测 16 路×300ms
             └─ _compute_fund_flow 本身无独立测试 → ❌ T1 范围缺口
为什么没挡住？  测试条件太弱（16×300ms vs 77×8s），且该模块被整体 mock
               → ❌ T2 深度缺口 + T3 模拟策略缺口
```

#### 漏洞 3：线程池双重占用（run_sync→run_in_thread）

```
有测试吗？    ├─ test_concurrency_guard.G1 → 16 路×300ms sleep → 通过
             ├─ test_timeout_resilience → 单次 run_in_thread 超时 → 通过
             └─ 无 run_sync 套 run_in_thread 的双线程池压力测试 → ❌ T1
为什么没挡住？  G1 测试仅验证 mootdx 场景（16×300ms），
               不覆盖 fund_flow 的嵌套线程池调用模式
               → ❌ T2 深度缺口
```

#### 漏洞 4：`factor_registry.py` 自建重复 CircuitBreaker

```
有测试吗？    ├─ test_factor_registry.py (17KB) → 只测因子计算逻辑
             ├─ 无 CircuitBreaker 重复检测
             └─ 无 "是否复用了 SourceRegistry" 架构检查 → ❌ T4
为什么没挡住？  架构约束仅在注释和文档中，无代码强制
```

#### 漏洞 5：修复后未添加回归测试

```
Phase 10 修复 (c7a70d9):
   修改了 async_utils.py（池+管道修复）
   影响范围: 线程池隔离、run_sync 行为
   测试覆盖: 未为本次修复新增专用回归测试
             现有测试全部 mock -> 未感知行为变化
             → ❌ T5 回归防护缺口

Phase 7 修复 (e97a16d):
   修改了 design pipeline timeout 处理
   影响范围: 90s 超时行为
   测试覆盖: 未验证 "push2 全挂时 design 仍应在 <45s 返回降级数据"
             → ❌ T1 范围缺口 + T5 回归缺口
```

### 3.6 根因：测试防护体系设计中的"毒性"

| 特征 | 表现 | 后果 |
|------|------|------|
| **"全部 mock" 的惯性** | 所有外部依赖一律 mock | 永远测不到真实线程池行为和数据源不可用场景 |
| **测试条件过于温和** | 16 并发×300ms，永远不模拟 77 并发×8s | 高强度场景漏洞无法暴露 |
| **测试覆盖不检查架构** | 没有测试断言 "所有 fetcher 都用 SourceRegistry" | 架构退化无人察觉 |
| **修复不留回归资产** | 每轮修复后不追加红绿切换测试 | 同一类问题复发时无测试变红提醒 |
| **测试与真实运行环境割裂** | CI 跑 mock 测试全绿，生产环境线程池耗尽 | 测试失去预警作用 |

---

## 四、优化修复方案

### 4.0 修复方案与 T 级缺口的对应关系

| 缺口级别 | 问题 | 对应的修复工单 | 预期效果 |
|---------|------|--------------|---------|
| **T1** 测试范围缺口 | `_compute_fund_flow` 等关键路径无独立测试 | OPT-11, OPT-07 | 故障注入 + E2E 降级场景覆盖 |
| **T2** 测试深度缺口 | 现有测试条件过于温和（16×300ms） | OPT-11 | 用故障注入模拟真实高强度场景 |
| **T3** 模拟策略缺口 | 全部 mock 外部依赖，绕过真实线程池 | OPT-11, OPT-12 | 引入部分集成测试，不全部 mock |
| **T4** 架构合规缺口 | 无架构断言验证约束未被违反 | OPT-12, OPT-13 | AST 审计 + 架构合规测试 |
| **T5** 回归防护缺口 | 修复后不追加红绿切换测试 | **OPT-16**（新增） | 每条修复必须包含一条红绿切换测试 |

### 4.1 总体结构

| 层级 | 类型 | 工单 |
|------|------|------|
| **机制**（不会复发） | 熔断器 / Semaphore / 池参数化 / AST 审计 / 超时拆分 / 全面覆盖 / SourceRegistry 增强 | OPT-01,04,06,09,10,13,14,15 |
| **隔离**（减少复发概率） | 线程池分配迁移 / run_in_thread 改造 | OPT-03,09 |
| **发现**（让复发变明显） | 故障注入测试 / 架构合规测试 | OPT-07,11,12 |

### 4.2 工单清单

| 编号 | 优先级 | 描述 | 类型 | 预期效果 | 工时 |
|------|--------|------|------|---------|------|
| **OPT-01** | **P0** | **SourceRegistry 核心路径接入** | 机制 | 将 fundamental_fetcher + sentiment_fetcher 接入已有的 `SourceRegistry` 框架 | 2h |
| **OPT-09** | **P0** | **`run_in_thread` 增加 executor 参数** | 机制 | 所有内部调用可选长任务池，不再硬编码共享池 | 1h |
| **OPT-10** | **P0** | **`run_in_thread` 调用点审计**| 修复 | 扫描 40 处调用，将 >5s 的迁移到长任务池 | 2h |
| OPT-02 | P0 | `_compute_fund_flow` 快速降级 | 机制 | 熔断器开启时直接返回空，不等 8s | 0.5h |
| **OPT-14** | **P1** | **SourceRegistry 全面接入（18 个 HIGH 风险模块）** | 机制 | 所有外部数据源都有熔断保护，任一挂掉不扩散 | 6h |
| OPT-04 | P1 | 并发请求 Semaphore 限流 | 机制 | `_compute_fund_flow` 最多 8 个并发 | 0.5h |
| OPT-05 | P1 | 数据源熔断状态 API | 机制 | 运维可实时查看各数据源状态 | 1.5h |
| OPT-06 | P1 | 超时预算拆分 (DATA/ENGINE/LLM) | 架构 | LLM 报告不再被数据采集超时侵蚀 | 1.5h |
| OPT-03 | P2 | 线程池隔离强化 | 隔离 | 长任务全切 `run_sync_long` | 1h |
| **OPT-13** | **P2** | **AST 审计脚本（池分配合规）** | 机制 | CI 自动拦 timeout > 5s 还走共享池的调用 | 2h |
| **OPT-15** | **P2** | **SourceRegistry 自身机制优化** | 机制 | try_call 包装器 + 自动硬失败 + 指数退避 | 2h |
| OPT-11 | P3 | 故障注入集成测试 | 机制 | 数据源全部熔断 → design 在 <30s 内返回降级方案 | 3h |
| OPT-12 | P3 | 架构合规测试 | 机制 | 每个 deploy 前验证线程池分割未被破坏 | 1.5h |
| OPT-07 | P3 | E2E 测试增加数据源降级场景 | 修复 | verify_e2e 新增熔断模式 | 2h |
| OPT-08 | P4 | 预热耗时优化 | 优化 | 缩短 `asyncio.wait()` 为 60s | 1h |
| **OPT-16** | **P2** | **红绿切换回归测试门禁** | 机制 | 每次修复必须追加一条能红绿切换的回归测试，失败时阻止提交 | 1.5h |

**工时合计**：P0(6.5h) + P1(9.5h) + P2(6.5h) + P3(6.5h) + P4(1h) = **30h**

### 4.3 详细设计

#### OPT-01: SourceRegistry 核心路径接入

**关键发现**：`services/source_registry.py` 已提供了完整的熔断路由框架（`SourceRegistry` + `SourceHealth`），支持多源优先级路由（`route()`）、连续失败计数 + 冷却、线程安全、事件回调、健康探针集成和监控 API。已有 `china_market`、`etf_scanner`、`sector_fetcher`、`market_service` 等 5 个模块在使用。**本工单不做新轮子，而是把缺失的核心路径接入现有框架。**

接入方式 - `fundamental_fetcher.py`：
```python
def fetch_fund_flow(symbol):
    from ..services.source_registry import registry
    import time
    h = registry._health("push2.eastmoney.com")
    if not h.available(time.time()):
        return None  # 熔断降级，不等 8s 超时
    try:
        result = run_in_thread(_p, timeout=8)
        h.record_success()
        return result
    except Exception as e:
        h.record_failure(time.time(), error_message=str(e)[:200])
        return None
```

同理修改 `sentiment_fetcher.py` 的 `fetch_advance_decline_ratio()`。

清理工作：删除 `factor_registry.py` 中自建的 `CircuitBreaker` 类，切换为：
```python
from ..services.source_registry import registry
# CircuitBreaker.is_open() → registry._health("sina").available(time.time())
# CircuitBreaker.record_failure() → registry._health("sina").record_failure(...)
```

**涉及文件**：`fetchers/fundamental_fetcher.py`、`fetchers/sentiment_fetcher.py`、`factors/factor_registry.py`


#### OPT-09: `run_in_thread` 增加 executor 参数

这是**阻止复发的关键架构修复**。当前：

```python
# async_utils.py:31
def run_in_thread(fn, *args, timeout: int = 8):
    future = _shared_executor.submit(fn, *args)  # 硬编码共享池
```

改为：

```python
def run_in_thread(fn, *args, timeout: int = 8, executor: str = "shared"):
    pool = {
        "shared": _shared_executor,
        "long": _long_running_executor,
    }.get(executor, _shared_executor)
    future = pool.submit(fn, *args)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return None
```

使用示例：

```python
# fundamental_fetcher.py
df = run_in_thread(_p, timeout=8, executor="long")
```

**涉及文件**: `core/async_utils.py`（改签名）；`fetchers/*.py`（约 40 处添加参数）

#### OPT-10: `run_in_thread` 调用点审计

全代码库共约 **40 处** `run_in_thread` 调用，分布在：

| 文件 | 调用数 | timeout | 建议的 executor |
|------|--------|---------|----------------|
| `fundamental_fetcher.py` | 6 处 | 8s | `"long"` |
| `china_market.py` | 8 处 | 8-15s | `"long"` |
| `sentiment_fetcher.py` | 1 处 | 8s | `"long"` |
| `alphavantage_fetcher.py` | 2 处 | 10s | `"long"` |
| `twelvedata_fetcher.py` | 2 处 | 10s | `"long"` |
| `data_fetcher.py` | 2 处 | 10s | `"long"` |
| `factor_registry.py` | 1 处 | 5s | `"shared"`（保留） |
| 其他快速调用 | ~18 处 | ≤5s | `"shared"`（保留） |

**迁移规则**：timeout > 5s → `executor="long"`；timeout ≤ 5s → 保留默认（`"shared"`）

#### OPT-02: `_compute_fund_flow` 快速降级

**现状**：`_compute_fund_flow` 内的 `_fetch_one` 在 `asyncio.gather` 中同时发出 77 个请求，每个等 8s 超时，总耗时至少 16s。

**改动**（`strategy_design.py` `_fetch_one`）：
```python
try:
    return await run_sync(fetch_fund_flow, sym, timeout=8)
except Exception:
    return None  # 单个失败不阻塞整体
```

+ 上层 `_compute_fund_flow` 增加熔断器检查：
```python
from ..services.source_registry import registry
if not registry._health("push2.eastmoney.com").available(time.time()):
    return {"total_net_inflow": 0, "positive_flow_count": 0,
            "negative_flow_count": 0, "total_symbols": 0}
```

**优先级**：P0（与 OPT-01 同时实施，形成双层保护）
**工时**：0.5h

#### OPT-04: 并发请求 Semaphore 限流

**现状**：`strategy_design.py:201` 直接 `asyncio.gather(*[_fetch_one(s) for s in all_symbols])`，77 个并发同时涌入共享线程池。

**改动**（`strategy_design.py`）：
```python
_fund_flow_sem = asyncio.Semaphore(8)  # 最多 8 个并发

async def _fetch_one(sym: str) -> dict | None:
    async with _fund_flow_sem:  # 限流
        try:
            return await run_sync(fetch_fund_flow, sym, timeout=8)
        except Exception:
            return None
```

**效果**：即使 push2 全部超时，每次也只有 8 个线程被占用，不影响其他模块。
**优先级**：P1
**工时**：0.5h

### 4.4 其他关键工单

#### OPT-06: 超时预算拆分

现状（单一大锅）：
```python
result = await asyncio.wait_for(
    generate_enhanced_design(capital, constraints), timeout=90,
)
```

改为（三段独立预算）：
```python
# DATA 阶段 (因子 + fund flow): 45s 预算
result = await asyncio.wait_for(generate_enhanced_design(...), timeout=45)

# 持久化: 5s
await persist_design(result)

# LLM 报告阶段: 35s 预算
llm_result = await asyncio.wait_for(generate_design_report(...), timeout=35)
```

#### OPT-13: AST 审计脚本

新增 `scripts/audit_pool_usage.py`，作为 pre-commit 门禁和 CI 步骤：

```python
"""审计 run_sync / run_in_thread 的池使用合规性。"""
import ast
import sys

# 规则: run_sync 的 timeout 参数 > 5 → 应使用 run_sync_long
# 规则: run_in_thread 的 timeout 参数 > 5 → 应传递 executor="long"

violations = []
for file in sys.argv[1:]:
    tree = ast.parse(open(file).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ...
            if func_name == "run_sync":
                timeout = extract_timeout_kwarg(node)
                if timeout and timeout > 5:
                    violations.append(f"{file}:{node.lineno}: run_sync timeout={timeout} > 5s")

if violations:
    print("POOL USAGE VIOLATIONS FOUND:")
    for v in violations:
        print(f"  {v}")
    sys.exit(1)
```

作为 pre-commit 钩子运行，确保每次提交都经过审计。

#### OPT-15: SourceRegistry 自身机制优化

**背景**：SourceRegistry 的熔断机制能有效阻挡"持续重试"，但面对第一波 77 个并发的冲击时不够快。三个小优化：

**优化 1：添加 `try_call()` 包装器**

减少调用方模板代码，降低漏记 `record_failure/success` 的概率：
```python
# source_registry.py
def try_call(self, name: str, fn: Callable, *args, timeout: float = 0,
             **kwargs) -> Any:
    """健康检查 → 执行 → 记录结果，三合一。"""
    h = self._health(name)
    now = time.time()
    if not h.available(now):
        return None
    try:
        result = fn(*args, **kwargs)
        h.record_success()
        return result
    except Exception as e:
        h.record_failure(now, error_message=str(e)[:200])
        return None
```

接入方只需 1 行：
```python
# 改前：4 行 + 异常处理
# 改后：1 行
result = registry.try_call("push2", run_in_thread, _p, timeout=8)
```

**优化 2：自动检测瞬间失败（< 500ms 视为硬失败）**

TLS RST 通常 < 500ms 就失败了，此时应走 `record_hard_failure()` 通道直接冷却，跳过 failure_threshold 计数。在 `try_call()` 内部实现：

```python
elapsed_ms = (time.time() - now) * 1000
if elapsed_ms < 500 and not result:
    h.record_hard_failure(now, duration_ms=elapsed_ms,
                          error_message="fast-fail (<500ms) — hard cooling")
```

**优化 3：指数退避 cooldown**

当前 `cooldown=60s` 固定值。如果 push2 死了一小时，系统每 60s 重试一次完全无意义。改为指数退避：

```python
# SourceHealth.__init__
self.base_cooldown = cooldown  # 60s
self.max_cooldown = 600        # 10 min max
self._consecutive_cycles = 0

# record_failure 中
if self._failures >= self.failure_threshold:
    self._consecutive_cycles += 1
    actual_cooldown = min(
        self.base_cooldown * (2 ** (self._consecutive_cycles - 1)),
        self.max_cooldown
    )
    self._cool_until = now + actual_cooldown
    self._failures = 0

# record_success 中
self._consecutive_cycles = 0
```

退避序列：60s → 120s → 240s → 480s → 600s(max)

**涉及文件**：`services/source_registry.py`
**工时**：2h（三个优化合并，改动量小）
**优先级**：P2（非阻塞 OPT-01/04/09，但建议后续实施）

#### OPT-11: 故障注入集成测试

新增 `tests/test_circuit_breaker_integration.py`：

```python
async def test_design_with_all_sources_broken():
    """当所有外部数据源熔断时，design 必须在 <30s 内返回降级方案。"""
    # 1. 手动激活所有熔断器（通过 SourceRegistry 直接设置冷却状态）
    from app.services.source_registry import registry
    import time
    now = time.time()
    for name in ["push2.eastmoney.com", "akshare", "sina"]:
        h = registry._health(name)
        h.record_hard_failure(now)  # 直接进入冷却
    
    # 2. 触发设计
    t0 = time.time()
    result = await asyncio.wait_for(
        generate_enhanced_design(capital=500000), timeout=45,
    )
    elapsed = time.time() - t0
    
    # 3. 断言：快速完成 + 降级数据
    assert elapsed < 30, f"设计耗时 {elapsed:.1f}s > 30s 上限"
    assert result.get("design_metadata", {}).get("data_quality", "") in ("degraded", "partial")
```

> **注意**：SourceRegistry 是全局单例，冷却状态跨测试共享。集成测试需在 `setup`/`teardown` 中重置状态，避免测试间相互影响。可使用 `registry._health(name).record_success()` 重置。

#### OPT-16: 红绿切换回归测试门禁

**问题**：过去 3 次修复均未追加回归测试，导致同类问题复发时无测试变红提醒。

**要求**：每个 P0/P1 修复工单的完成条件包括：**新增至少一条能红绿切换的回归测试**。

"红绿切换"定义：
- 在修复前运行该测试 → 必须 RED（失败）
- 在修复后运行该测试 → 必须 GREEN（通过）
- 未来改坏时运行该测试 → 必须 RED

**实现**（`tests/test_regression.py` 新增）：

```python
import pytest
from app.services.source_registry import registry
from app.fetchers.fundamental_fetcher import fetch_fund_flow
from app.core.async_utils import run_sync

@pytest.mark.regression("OPT-01")
async def test_fund_flow_circuit_breaker_regression():
    """OPT-01 红绿切换测试：push2 熔断时 fetch_fund_flow 立即返回 None。"""
    # 1. 模拟 push2 熔断
    h = registry._health("push2.eastmoney.com")
    t = time.time()
    h.record_failure(t, error_message="TLS RST")
    h.record_failure(t, error_message="TLS RST")
    h.record_failure(t, error_message="TLS RST")  # 连续 3 次 → 熔断
    
    # 2. 调用 fetch_fund_flow（OPT-01 修复后应直接返回 None，不等 8s）
    result = await run_sync(fetch_fund_flow, "sh518880")
    
    # 3. 断言：降级
    assert result is None, "熔断时应立即返回 None，不等 8s 超时"
    
    # 4. 清理：恢复熔断器状态（避免影响其他测试）
    h.record_success()
```

**工具化**：在 `conftest.py` 注册 regression marker + CI 门禁：
```python
# conftest.py
def pytest_addoption(parser):
    parser.addoption("--regression", action="store_true",
                     help="仅运行回归测试")
    parser.addoption("--require-regression", action="store_true",
                     help="回归测试失败时阻止提交")
```

**涉及文件**：新增 `tests/test_regression.py`；修改 `conftest.py`（注册 marker + option）
**优先级**：P2
**工时**：1.5h

---

## 五、尚未完成的工作

以下步骤因 push2 封锁未能完整执行：

- **Step 3: 前端性能诊断（Lighthouse）** — 需后端设计管线产出数据后才有实际内容可审计。理论预估：Vite 已配置 `manualChunks` 拆包（vendor-vue / vendor-echarts / vendor-axios / vendor-marked），但 `chunkSizeWarningLimit=700KB` 偏大，建议降至 400KB
- **Step 4: 后端路由全链路诊断** — 组合设计路由已全文分析（见第二章），其他路由在数据源故障场景下表现为"等待太久才报错"

---

## 六、如何防止再次复发

过去 3 天（Jul 26-28）同一类问题被修复 2 次（commit `e493581` 线程池耗尽修复, `c7a70d9` 池+管道修复）但第 3 次仍然重现。要打破这个循环，需要以下机制：

### 6.1 每次修复后必须增加"复发检测"

不是增加文档，而是增加在 CI 中能自动检测的防御：

- **P0 的修复完成后，必须补一条集成测试**，模拟修复前失败的场景
- **这条测试必须能红绿切换**：修复前红，修复后绿，未来改坏了变红

### 6.2 新代码的 "合规" 由机器审查，不由人

| 审查项 | 机制 |
|--------|------|
| `run_sync` timeout > 5s | AST 审计脚本（pre-commit 门禁）|
| `run_in_thread` timeout > 5s 未指定 executor | AST 审计脚本 |
| 新增 fetcher 未接入熔断器 | 类型提示（Protocol）让 IDE 提示 |
| 新增任务未定义超时预算 | TaskManager 注册时强制 `timeout_budget` 字段 |

### 6.3 架构决策记录（ADR）不应是文档，应是代码

当前架构决策（两个线程池的意图）仅存在于 `async_utils.py` 的注释中：
```python
# 全局共享线程池...64 workers
# 长任务专用线程池...8 workers
```

改成代码强制：
```python
def run_in_thread(fn, *args, timeout: int = 8, executor: str = "shared"):
    """executor: 'shared' (default, ≤5s tasks) or 'long' (>5s tasks)."""
```

这样 API 签名本身就编码了架构决策，调用者不需要读文档和注释。

### 6.4 回顾检查清单

每次修复完成后，用以下清单验证修复是否彻底：

- [ ] 修复是否引入了一条能 **红绿切换** 的回归测试？
- [ ] 修复是否添加了 **自动检查机制**（lint / pre-commit / CI）？
- [ ] 修复是否修改了 **架构决策载体**（API 签名 / 类型 / 接口）而非只改了注释？
- [ ] 修复是否覆盖了 **所有同类调用点**（不局限于出问题的那个）？
- [ ] 修复后，**复现原始故障的操作**是否不再触发该问题？

---

## 附录 A：push2 TLS 阻断诊断时间线

```
00:24:36 — 首次线程池告警
00:28:32 — push2 开始持续失败，每 5s 一次
00:31:02 — 连续失败 150s（30 次），task 104/105 超时
00:31:06 — akshare returned empty → cooling
00:31:52 — pool_manager 成功扫描 77 只 ETF（Sina 数据）
00:32:44 — 因子计算正常（Sina K-line API）
00:33:00+ — push2 继续失败，task 106/107 二次超时
```

## 附录 B：线程池使用全景图

```
_shared_executor (64 workers):
├── 短 I/O (≤5s): market_service / news routes / market_router / source_health
├── 长 I/O (>5s) - 错误分配:
│   ├── strategy_design._compute_fund_flow  (77×8s)
│   ├── sentiment_fetcher.*                 (3×15s)
│   ├── factor_registry.fetch_history       (77×20s)
│   ├── macro_state.*                       (2×30s)
│   ├── pool_manager.fetch_hot_plates       (20s)
│   └── portfolio_service.*                 (2×8-30s)
└── run_in_thread (全部走共享池):
    ├── fundamental_fetcher.*       (6处, all 8s)
    ├── china_market.*              (8处, 8-15s)
    ├── sentiment_fetcher.*         (1处, 8s)
    └── alphavantage/twelvedata.*   (4处, 10s)

_long_running_executor (8 workers):
└── pool_manager.scanner.full_pipeline  (60s) ✅ 唯一正确分配
```

## 附录 C：`run_in_thread` 改造清单

目标：对全代码库约 40 处调用逐一检查 timeout，决定使用共享池还是长任务池。

| 文件 | 行号 | timeout | 建议 executor |
|------|------|---------|---------------|
| `fetchers/fundamental_fetcher.py` | 45 | 8s | long |
| `fetchers/fundamental_fetcher.py` | 83 | 8s | long |
| `fetchers/fundamental_fetcher.py` | 129 | 8s | long |
| `fetchers/fundamental_fetcher.py` | 198 | 8s | long |
| `fetchers/fundamental_fetcher.py` | 253 | 8s | long |
| `fetchers/china_market.py` | 181 | 15s | long |
| `fetchers/china_market.py` | 327 | 8s | long |
| `fetchers/china_market.py` | 422 | 8s | long |
| `fetchers/china_market.py` | 495 | 8s | long |
| `fetchers/china_market.py` | 749 | 8s | long |
| `fetchers/sentiment_fetcher.py` | 155 | 8s | long |
| `factors/factor_registry.py` | 504 | 5s | shared（保留）|
| `fetchers/alphavantage_fetcher.py` | 71 | 10s | long |
| `fetchers/alphavantage_fetcher.py` | 111 | 10s | long |
| 其余 ~25 处 | — | ≤5s | shared（保留）|

---

## 附录 D：熔断器接入全景图（OPT-14 实施计划）

以下为全代码库 22 个有外部 API 调用的模块的完整熔断器接入计划。

### 数据源依赖图谱

```
push2.eastmoney.com ──────────────────┐
  ├─ fundamental_fetcher: fund_flow   │ (OPT-14.1)
  ├─ sentiment_fetcher: advance_decline│ (OPT-14.2, 已有 fallback)
  ├─ etf_scanner: etf_spot            │ (OPT-14.3, 已有 cooling)
  └─ em_global_fetcher: global_spot   │ (OPT-14.4, 已有 fallback)

akshare（内部路由）───────────────────┐
  ├─ news_fetcher: news/headlines     │ (OPT-14.5)
  ├─ sector_fetcher: sector/data      │ (OPT-14.6, 已有 fallback)
  ├─ macro_state: pmi/bond            │ (OPT-14.7)
  ├─ market_trends: sector/hot_plates │ (OPT-14.8, 已有 fallback)
  └─ pool_manager: sector_heat        │ (OPT-14.9, 已有 fallback)

第三方 API ───────────────────────────┐
  ├─ yfinance_fetcher: US quotes      │ (OPT-14.10)
  ├─ finnhub_fetcher: US news         │ (OPT-14.11)
  ├─ alphavantage_fetcher: forex/etf  │ (OPT-14.12)
  ├─ twelvedata_fetcher: technical    │ (OPT-14.13)
  ├─ tushare_fetcher: A-stock data    │ (OPT-14.14)
  └─ levistock_fetcher: HK quotes     │ (OPT-14.15)
```

### 接入策略

| 熔断器名称 | 保护的模块 | failure_threshold | recovery_timeout | 降级返回值 |
|-----------|----------|------------------|-----------------|-----------|
| `push2` | fundamental, sentiment, scanner, em_global | 3 | 60s | None |
| `akshare` | news, sector, macro, trends, pool | 5 | 120s | None |
| `yfinance` | yfinance_fetcher | 3 | 60s | None |
| `finnhub` | finnhub_fetcher | 3 | 60s | None |
| `alphavantage` | alphavantage_fetcher | 3 | 60s | None |
| `twelvedata` | twelvedata_fetcher | 3 | 60s | None |
| `tushare` | tushare_fetcher | 3 | 60s | None |
| `levistock` | levistock_fetcher | 3 | 60s | None |

### 接入模板

每个 fetcher 的入口函数只需增加 3 行：

```python
def fetch_fund_flow(symbol):
    from app.core.circuit_breaker import CircuitBreaker
    if CircuitBreaker.get("push2").is_open():
        return None  # 熔断降级，不等 8s 超时
    # ... 原有逻辑 ...
    try:
        df = run_in_thread(_p, timeout=8)
        CircuitBreaker.get("push2").record_success()
        return df
    except Exception:
        CircuitBreaker.get("push2").record_failure()
        return None
```

### 实施顺序

1. **OPT-01 第一优先级**：创建 `core/circuit_breaker.py` + 接入 `fundamental_fetcher.fetch_fund_flow`（解决当前超时）
2. **OPT-14.2**：接入 `sentiment_fetcher`（同样依赖 push2，每次 15s 超时）
3. **OPT-14.3-14.9**：接入 akshare 线路
4. **OPT-14.10-14.15**：接入第三方 API 线路
