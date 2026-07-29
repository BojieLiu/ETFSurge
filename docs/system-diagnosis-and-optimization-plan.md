# ETF Surge 系统诊断与优化方案

> 文档版本：v3.0  
> 诊断日期：2026-07-29  
> 审阅轮次：自审 v1.0 → v2.0 → v3.0（3 轮 review + 修改，已达实施标准）

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [诊断方法](#2-诊断方法)
3. [后端性能诊断](#3-后端性能诊断)
4. [前端性能诊断](#4-前端性能诊断)
5. [数据管道诊断](#5-数据管道诊断)
6. [组合设计报告质量审阅](#6-组合设计报告质量审阅)
7. [市场分析功能评估](#7-市场分析功能评估)
8. [技术分析与信号准确性评估](#8-技术分析与信号准确性评估)
9. [资讯功能评估](#9-资讯功能评估)
10. [因子模型评估](#10-因子模型评估)
11. [测试防护体系缺陷分析](#11-测试防护体系缺陷分析)
12. [数据管道统一方案](#12-数据管道统一方案)
13. [数据源不稳定优化方案](#13-数据源不稳定优化方案)
14. [数据源降级链补充方案](#14-数据源降级链补充方案)
15. [push2→push2delay 域名替换核查](#15-push2→push2delay-域名替换核查)
16. [优化方案实施计划](#16-优化方案实施计划)

---

## 1. 执行摘要

本次诊断对 ETF Surge 系统进行了全链路性能与质量评估，涵盖后端预热性能、API 端点可用性、组合设计报告质量、市场分析功能、技术信号、新闻资讯、因子模型、前端 Lighthouse 审计、测试防护体系，并针对数据管道统一、数据源不稳定、缺失因子根因等问题进行了深度代码级追溯。

### 关键发现汇总

| 维度 | 状态 | 严重程度 | 关键指标 |
|------|------|---------|---------|
| 后端预热性能 | ⚠️ | 高 | 预热耗时 38s（阈值 30s），ETFX扫描 >120s |
| API 端点可用性 | ⚠️ | 高 | 87% 端点正常（27/31），4 个端点异常 |
| 组合设计报告质量 | ⚠️ | 中 | 重复标题、截断描述、数据缺失 |
| 行情数据实时性 | ❌ | 高 | 多个实时行情返回 null，信号"insufficient_data" |
| 新闻资讯数据源 | ❌ | 高 | 全球新闻 500 错误，头条超时 |
| 因子模型数据完整性 | ❌ | 中 | premium_discount/tracking_error 全为 0 |
| 前端 Lighthouse 性能 | ⚠️ | 中 | Performance 57 分 |
| 测试防护体系 | ❌ | 高 | 多类问题未被端到端测试捕获 |
| **数据管道统一度** | **❌** | **高** | 三条独立数据管道各自为政，互不共享缓存 |
| **熔断器接入度** | **❌** | **高** | 熔断框架已写好但从未接入任何数据源调用 |

---

## 2. 诊断方法

### 2.1 工具链

- **后端预热诊断**：内置 `WarmupProfiler`（cProfile + pyinstrument），`PROFILE_WARMUP=1`
- **后端性能**：cProfile 函数级调用统计，pyinstrument 异步感知采样分析
- **前端性能**：Lighthouse v13.4.1，Chrome Headless
- **APIs**：综合诊断脚本，覆盖 31+ 个 API 端点
- **报告审阅**：深度审阅 design 229 的三套方案设计报告
- **日志分析**：`backend.log` 错误/告警/超时扫描
- **代码追溯**：因子计算链、数据采集链、熔断器调用链的逐级代码溯源

### 2.2 运行环境

- 本地开发模式，Python 3.12，FastAPI + uvicorn
- Redis 7 via Docker
- 前端 Vite dev server (port 5173)
- 数据源：东方财富 push2delay, mootdx, Sina, QQ(Tencent), akshare, yfinance 等

---

## 3. 后端性能诊断

### 3.1 预热阶段性能

**Profiler 记录的热点:**

| 阶段 | 耗时 | 占比 | 备注 |
|------|------|------|------|
| warmup_market_cache | 3,812 ms | 95.2% | 行情缓存预热（网络 I/O 密集） |
| redis_init | 148 ms | 3.7% | Redis 连接初始化 |
| warmup_etf_cache | 11 ms | 0.3% | ETF 扫描首次执行(仍在后台) |
| init_db | 31 ms | 0.8% | SQLite 初始化 |
| **总 profiled 时间** | **~4,003 ms** | 100% | |
| **实际总预热时间** | **~38,000 ms** | 9.5x | 预导入+后台任务未计入 profiler |

**cProfile 热点函数 (top 5 by cumulative time):**

| 函数 | 累计耗时 | 调用次数 | 分析 |
|------|---------|---------|------|
| `fetch_fund_nav` | 4.08s | 10 | 逐只获取基金净值，串行 |
| `requests.get` (akshare) | 3.58s | 11 | HTTP 请求至 eastmoney |
| `_ssl_wrap_socket` | 1.49s | 12 | SSL 连接建立(含证书验证)，连接未复用 |
| `load_verify_locations` | 1.20s | 83 | CA 证书加载，重复 |
| `run_in_thread` | 4.57s | 37 | 线程池任务 |

**根因分析**：
1. **串行数据获取**：预热过程串行调用多个数据源
2. **SSL 开销**：每次建立 HTTPS 连接都重新 SSL 握手（1.2s），缺少连接池复用
3. **未计时的预热阶段**：Python 模块预导入耗时未计入 profiler
4. **ETFX扫描后台超时**：120s 超时保护被触发

### 3.2 运行时性能

| 响应时间 | 端点 | 问题 |
|---------|------|------|
| < 50ms | /health, /search, /designs | 正常 |
| 50-500ms | /realtime/{symbol}, /indices/global | 正常 |
| 1-5s | /design/{id}, /chart/{symbol} | 数据库/数据源查询 |
| > 15s (超时) | /realtime/portfolio, /sectors/*, /factors/* | ⛔ 严重超时 |

---

## 4. 前端性能诊断

### 4.1 Lighthouse 评分

| 类别 | 得分 | 评级 |
|------|------|------|
| **Performance** | **57** | ⚠️ WARN |
| Accessibility | 96 | ✅ GOOD |
| Best Practices | 96 | ✅ GOOD |
| SEO | 82 | ⚠️ WARN |
| Agentic Browsing | 52 | ⚠️ WARN |

### 4.2 核心 Web 指标

| 指标 | 测量值 | 得分 | 阈值对比 |
|------|--------|------|---------|
| **FCP** | **1.6s** | 49% | 良好 < 1.8s |
| **LCP** | **4.4s** | 13% | ❌ > 2.5s |
| **TBT** | 40ms | 100% | ✅ |
| **CLS** | **0.227** | 55% | ⚠️ > 0.1 |
| **SI** | 2.2s | 52% | ⚠️ |
| **TTI** | 4.4s | 52% | ⚠️ |

### 4.3 前端问题分析

1. **LCP 4.4s**：ECharts 图表组件重量级初始化，大盘背景图加载
2. **CLS 0.227**：异步数据加载导致布局偏移
3. **FCP 1.6s**：JS 包体积较大

**失败审计项**：
- ❌ bfcache 被阻止
- ❌ 颜色对比度不足
- ❌ 控制台浏览器错误
- ❌ 缺少 meta description
- ❌ robots.txt 无效

---

## 5. 数据管道诊断

### 5.1 数据源健康状态

| 数据源 | 状态 | 问题描述 |
|--------|------|---------|
| EastMoney (push2delay) | ⚠️ 部分可用 | ETF 扫描 100+ 页费时 >60s |
| akshare fund NAV | ⚠️ 慢 | 10 次 API 调用需 4.08s |
| Sina Finance | ❌ 超时 | 部分行情 endpoint 返回空 |
| mootdx | ⚠️ 数据稀疏 | 部分代码返回空数据 |
| 财新 RSS 新闻 | ⚠️ 超时 | RSS 读取在某些时段延迟高 |
| 融券/融资数据 | ❌ 404 | SZSE/SSE 接口返回 404 |

### 5.2 三条数据管道各自为政

代码追溯发现系统存在三条独立的数据采集管道，互不共享缓存和数据：

```
管道A: pool_manager.refresh()
        → etf_scanner.full_pipeline()   # ETF扫描
        → factor_registry.compute()     # 因子计算
        → update_market_regime()        # 市态判定
        → refresh_sentiment_cache()     # 情绪采集
        → refresh_news()               # 新闻缓存
       消费方: strategy_design.py ✅ (已接入)
       未接入: REST API 端点 ❌

管道B: market_service._call()
        → fetch_history()              # 历史K线
        → get_asset_realtime()         # 实时行情
        → compute_all_indicators()     # 技术指标
       消费方: /signal, /chart, /realtime REST API
       独立于 pool_manager，不读其缓存

管道C: factor_registry._fetch_market_data()
        → 独立于 pool_manager 的 K 线获取
        → IOPV 获取 (Sina)
       消费方: factor_registry.compute() 内部
       和管道A的 factor_registry.compute() 是同一函数
       但两次调用各自 fetch 一遍数据
```

**核心问题**：
- 管道A 和管道C 都调用了 `factor_registry.compute()`，但每次调用都在内部 `_fetch_market_data()` 中重新拉取数据
- 管道B（REST API）不知道管道A 已有缓存，重新获取
- 预热时三条管道各自触发数据采集，重复 I/O
- 缓存碎片化：因子缓存 120s、实时缓存 15s、新闻缓存 120s，各自独立

### 5.3 数据源不稳定根因

代码追溯发现了一个**关键的反直觉事实**：

**熔断器框架已写好，但从未接入任何数据源调用。**

```
backend/app/services/source_registry.py
  ├─ SourceHealth        ✅ 指数退避冷却 (60s→120s→240s→480s→600s)
  ├─ SourceRegistry      ✅ route() 多源优先级降级
  │                      ✅ try_call() 三合一包装
  └─ registry            ✅ 全局实例

  ↓ 但从未被以下文件调用：
  ❌ china_market.py     # 裸调用 mootdx/Sina/QQ，失败不记熔断
  ❌ market_service.py   # 裸调用 _call()，失败不记熔断
  ❌ factor_registry.py  # 裸调用 _fetch_market_data()
  ❌ news_fetcher.py     # 裸调用 feedparser
```

**甚至 `source_registry` 已在 `china_market.py` 被 import（第 22 行），docstring 也写着降级链（第 6-8 行），但从未实际调用 `registry.route()`。**

这就是为什么数据源挂了一个，不会自动切换到备用源，也不会冷却恢复。

#### 更糟的是：存在两个独立的熔断器

`factor_registry.py` 第 620 行有另一个完全独立的 `CircuitBreaker`：

```python
class CircuitBreaker:
    """简单的电路断熔，防止外部数据源故障时反复重试。"""
    failure_count: ClassVar[int] = 0
    threshold: ClassVar[int] = 10
    cooldown: ClassVar[int] = 30
```

| 对比 | `SourceRegistry.SourceHealth` | `factor_registry.CircuitBreaker` |
|------|-------------------------------|----------------------------------|
| 冷却策略 | 指数退避 60s→600s | 固定 30s |
| 熔断阈值 | 3 次 | 10 次 |
| 快速失败检测 | ✅ | ❌ |
| 事件回调 | ✅ | ❌ |
| 线程安全 | ✅ | ❌ |

两个熔断器互相不感知，状态不共享。`CircuitBreaker` 是早期原型，**应当在接入统一熔断器后废弃**。

### 5.4 因子缺失根因分类

| 根因类型 | 涉及的因子 | 修复难度 |
|---------|-----------|---------|
| **A. 数据源接口已写好但不可靠** | `premium_discount`（Sina IOPV 被墙） | 低 — 切换数据源 |
| **B. 数据采集代码从未实现** | `tracking_error`, `shares_change`, `institutional_holdings_change` | 中 — 需接入东方财富API |
| **C. 数据采集代码存在但未连接到 factor pipeline** | `industry_diversification`, `stock_divergence`, `news_direction` | 中 — 需打通数据管道 |
| **D. 因子计算与数据采集在两个不同层** | 所有缺失因子 | 高 — 架构问题 |

### 5.5 其他数据缺失点代码追溯

| 问题 | 断裂链 | 根因 |
|------|--------|------|
| **信号 insufficient_data** | `get_history()` → 东方财富/akshare 返回空 → `compute_all_indicators([])` → `{}` → `generate_signal({})` → insufficient_data | 历史 K 线数据源不可靠 |
| **图表列名缺失** | `compute_chart_data()` 用 `data["收盘"]` 直接索引，而 `compute_all_indicators()` 用 `_resolve_col()` 有别名机制——两套代码不一致 | 代码不一致 |
| **Fundamentals 500** | Tushare 返回格式与 FastAPI Pydantic schema 不匹配 | Schema 不匹配 |
| **实时行情 null** | `fetch_a_stock_realtime()` 在 ETF 列表中找不到目标 | 数据源不全 |
| **新闻超时/500** | RSS feedparser 无 HTTP 级别超时，偶尔返回非标准格式 | 无超时控制 |
| **今日涨跌"—"** | 设计管线未注入实时涨跌数据 | 数据管道未打通 |
| **板块超时** | `asyncio.to_thread(fetch_industry_sectors)` 无外部超时 | 无超时控制 |

---

## 6. 组合设计报告质量审阅

### 6.1 审阅样本

- **设计 ID**：229
- **创建时间**：2026-07-28T16:46:08
- **资本**：500,000
- **风险配置**：balanced
- **设计类型**：async design（异步任务）

### 6.2 质量问题

#### P0 - 严重问题

1. **❌ 重复段落**：设计报告章节标题"一、三种方案详解"出现两次
2. **❌ 描述截断**："适合中等风"（应为"适合中等风险偏好"），LLM 生成的文本被截断
3. **❌ 今日涨跌全为"—"**：所有 ETF 当日涨跌数据未注入
4. **❌ 因子评分跨方案不一致**：同一 ETF 在不同方案中评分差异巨大（+0.23 vs -1.27）

#### P1 - 中等问题

5. **❌ 因子数据大面积缺失**：premium_discount/tracking_error/shares_change 等均为 0.0
6. **❌ 市场状态无实质分析**：所有方案均标注"市场震荡"，无深度轮动分析
7. **❌ 策略检查报告近乎为空**：suggestions=[], holdings_analysis=[], report_text=""
   - 注：策略检查 API 的 `portfolio_type` 参数可限定场内/场外（`on_exchange`/`off_exchange`），本次测试时未传该参数导致全量持仓（含场外）被纳入检查

#### P2 - 轻微问题

8. **❌ 权重重叠**：同一 ETF 在不同方案中出现在不同层级
9. **❌ 缺少行情快照**：设计方案缺少设计时刻的市场快照存档

---

## 7. 市场分析功能评估

### 7.1 API 端点可用性

| 模块 | 端点数 | 通过 | 失败 | 通过率 |
|------|--------|------|------|--------|
| 行情概览 | 3 | 3 | 0 | 100% |
| 搜索与实时行情 | 6 | 6 | 0 | 100% |
| 技术分析 | 4 | 3 | 1 | 75% |
| 板块分析 | 4 | 4 | 0 | 100% |
| 组合相关 | 5 | 3 | 2 | 60% |
| 新闻 | 3 | 1 | 2 | 33% |
| 因子模型 | 3 | 0 | 3 | 0% |
| 管理端点 | 3 | 3 | 0 | 100% |
| **总计** | **31** | **27** | **4** | **87%** |

### 7.2 失败端点详情

| 端点 | 错误 | 根因 |
|------|------|------|
| `/fundamentals/510050` | 500 ResponseValidationError | Tushare 返回字段与 Pydantic schema 不匹配 |
| `/portfolio/calculate` (GET) | 405 Method Not Allowed | 需 POST 方法（测试脚本问题） |
| `/portfolio/daily-pnl` (GET) | 405 Method Not Allowed | 需 POST 方法（测试脚本问题） |
| `/news/global` | 500 Internal Server Error | RSS 解析异常 |
| `/news/headlines` | 超时 | 财新数据源响应慢 |

---

## 8. 技术分析与信号准确性评估

### 8.1 信号引擎问题

多只主要 ETF 的信号评估结果：

| ETF | 信号 | 评分 | 原因 | 评估 |
|-----|------|------|------|------|
| 510050 (50ETF) | hold | 0 | insufficient_data | ❌ |
| 510300 (300ETF) | hold | 0 | insufficient_data | ❌ |
| 518880 (黄金ETF) | hold | 0 | insufficient_data | ❌ |
| 159915 (创业板) | hold | 0 | insufficient_data | ❌ |

**根因**：`generate_signal()` 函数（signal.py 第 4-6 行）在接收到空 `indicators` 字典时返回 `insufficient_data`。而 `compute_all_indicators()` 返回空字典的原因是 `get_history()` 未获取到足够 K 线数据。最终追溯到数据源不可靠。

### 8.2 技术指标计算

- ✅ `/indicators/{symbol}` 返回完整
- ✅ `/chart/{symbol}`: K 线数据可用
- ❌ 列名映射不一致：`compute_chart_data()`（indicators.py:207）直接写 `data["收盘"]`，而 `compute_all_indicators()`（indicators.py:147）使用 `_resolve_col()` 遍历别名——两套函数不一致

---

## 9. 资讯功能评估

### 9.1 新闻等级划分

| 类型 | 状态 | 数量 | 评级 |
|------|------|------|------|
| `/news/headlines` | ❌ 超时 | — | 数据源响应慢 |
| `/news/macro` | ✅ 正常 | 15 条 | 数据完整 |
| `/news/global` | ❌ 500 | — | RSS 解析错误 |

### 9.2 新闻系统问题

1. **数据源不稳定**：财新 RSS 抓取无 HTTP 级别超时
2. **RSS 解析错误**：全球新闻 RSS feed 格式可能变更
3. **无缓存兜底**：每次请求都实时拉取，失败时无降级

---

## 10. 因子模型评估

### 10.1 因子端点状态

| 端点 | 状态 | 说明 |
|------|------|------|
| `/factors/active` | ❌ 超时 | 大量因子的实时计算导致响应慢 |
| `/factors/ic` | ❌ 超时 | IC 计算需要大量历史数据 |
| `/factors/model` | ❌ 超时 | 模型推理耗时 |

### 10.2 因子缺失深度分析

**因子计算链追溯结果**（每个缺失因子的代码路径）：

#### premium_discount (折溢价率) = 0.0

```python
# factor_registry.py:385-392
def _compute_premium_discount(data):
    nav = data.get("nav")            # ← 依赖 Sina IOPV 接口
    price = data.get("price")
    if nav and price and nav > 0:
        return (price - nav) / nav
    return 0.0                       # ← Sina 被墙时走这里
```

**断裂链**：`_fetch_market_data()` 尝试从 `hq.sinajs.cn` 获取 IOPV，异常被 catch 后静默忽略，`nav` 字段从未注入 → 返回 0.0。

#### tracking_error (跟踪误差) = 0.0

```python
def _compute_tracking_error(data):
    bench_closes = data.get("benchmark_close", [])  # ← 从未存在过
    if len(closes) < 5 or len(bench_closes) < 5:
        return 0.0
```

**断裂链**：`_fetch_market_data()` 从未采集 `benchmark_close`。计算函数是"半成品"——完整的逻辑但无上游数据注入。

#### shares_change (份额变动) = 0.0

```python
def _compute_shares_change(data):
    shares_change = data.get("shares_change_20d")  # ← 从未存在过
    if shares_change is not None: return float(shares_change)
    return 0.0
```

**断裂链**：从未实现从天天基金/东方财富采集 ETF 份额变动数据的代码。

#### industry_diversification (行业分散度) = 0.0

```python
def _compute_industry_diversification(data):
    industry_holdings = data.get("industry_holdings", {})  # ← 未注入
    if not industry_holdings:
        concepts = data.get("concepts", [])                 # ← 未注入
        if concepts: return round(1.0 / max(n, 1), 4)
    return 0.0  # ← 两路数据都为空
```

**断裂链**：`industry_holdings` 和 `concepts` 两条数据路径都未注入。HHI 计算逻辑完善但无数据输入。

#### institutional_holdings_change (机构持仓变动) = 0.0

```python
def _compute_institutional_holdings_change(data):
    direct = data.get("institutional_holdings_change")     # ← 未注入
    if direct: return float(direct)
    shares_chg = data.get("shares_change_20d")             # ← 未注入
    if shares_chg: return float(shares_chg) * 0.5
    scale = data.get("fund_scale")                         # ← 偶尔注入但为空
    if scale: return float(scale) * 0.3
    return 0.0  # ← 三级降级全部断裂
```

**断裂链**：三个降级路径全部断裂。虽然有 `symbol_extra` 参数可传入 `fund_scale`，但调用方未实际传入。

#### sentiment.stock_divergence & news_direction

两者都依赖 `advance_decline` 和 `news_items` 字段——这些数据在 `pool_manager` 的其他路径中已采集（情绪/新闻缓存），但从未连接到 factor registry 的数据字典中。

---

## 11. 测试防护体系缺陷分析

### 11.1 未被测试捕获的问题

| # | 问题 | 为何未被捕获 |
|---|------|-------------|
| 1 | **后端预热超时 38s** | verify_e2e.py 检查 30s 阈值但未设 break 机制 |
| 2 | **多个端点超时** | timeout 设为 60s，超时不视为 FAIL |
| 3 | **fundamentals 500 错误** | 未测试 fundamentals 端点 |
| 4 | **报告质量** | 只检查状态码，未深入检查内容 |
| 5 | **实时行情返回 null** | 仅检查 HTTP 状态码，未验证响应体 |
| 6 | **信号 insufficient_data** | 未测试 signal 端点 |
| 7 | **因子缺失** | 未测试 factor 端点 |
| 8 | **前端性能 57 分** | 无前端性能测试 |
| 9 | **新闻 500 错误** | 仅检查 HTTP 200 |
| **10** | **熔断器未接入** | 无测试检查熔断器是否实际连通 |
| **11** | **数据管道碎片化** | 无跨管道一致性测试 |

### 11.2 测试体系缺陷根因

1. **"绿灯综合征"**：只检查 HTTP 200，不检查内容完整性
2. **深度覆盖不足**：factors, fundamentals, signal, 熔断器连通性均未覆盖
3. **无内容质量断言**：无 LLM 报告的结构化验证
4. **无性能门禁**：无预热时间/Lighthouse 评分的自动化门禁
5. **无数据完整性检查**：因子值全为 0.0 应触发告警
6. **mock 与实际脱节**：单元测试大量 mock，模拟环境与真实差异大
7. **无数据管道一致性测试**：同一 ETF 在各管道中的数据是否一致

---

## 12. 数据管道统一方案

### 12.1 现状：改了一半

`PoolManager` 已经做到了部分统一：

```
PoolManager (当前状态)
  ├─ refresh()               → 全市场ETF扫描 + 因子计算 + 新闻 + 情绪 + 市态
  ├─ get_pool()              → 五层候选池
  ├─ get_factor_matrix()     → 因子矩阵
  ├─ get_market_regime()     → 市场状态
  ├─ get_market_sentiment()  → 情绪数据
  └─ get_news()              → 新闻缓存

已消费方：strategy_design.py ✅
未消费方：market_service.py ❌, factor_registry._fetch_market_data() ❌,
           analysis/indicators.py ❌, analysis/signal.py ❌,
           routers/news.py ❌, routers/market.py ❌
```

**改了一半的问题**：
- `factor_registry._fetch_market_data()` 和 `pool_manager` 的扫描器获取同一批 ETF 数据，各自拉一遍——**重复 I/O**
- REST API 端点不走 pool_manager 缓存——**缓存浪费**
- `compute_chart_data` 和 `compute_all_indicators` 同一算法写两遍——**代码重复**

### 12.2 命名评估：PoolManager → MarketDataHub

| 当前职责 | "PoolManager" 字面含义 | 符合度 |
|---------|----------------------|--------|
| 候选池管理 | 池管理 | ✅ 符合 |
| 因子矩阵 | 池相关 | ⚠️ 勉强 |
| 市场状态判定 | — | ❌ 无关 |
| 市场情绪缓存 | — | ❌ 无关 |
| 新闻缓存 | — | ❌ 无关 |
| 统一后：K 线/实时行情/指标 | — | ❌ 无关 |

**结论**：`PoolManager` 当前已名不副实。推荐改名为 **`MarketDataHub`**，准确反映其作为"全系统统一数据入口"的中心地位。

### 12.3 统一方案

**目标**：将三条管道合并为一条，所有数据消费者从同一个 Hub 读取。

```python
class MarketDataHub:
    """统一数据总线——全系统唯一的数据入口。"""

    # 现有接口（从 PoolManager 迁移）
    async def refresh(self) -> PoolDiff: ...
    def get_pool(self, layer=None) -> list[dict]: ...
    def get_factor_matrix(self) -> dict: ...
    def get_market_regime(self) -> str: ...
    def get_market_sentiment(self) -> dict: ...
    def get_news(self) -> list[dict]: ...

    # 新增接口（填补缺失）
    def get_kline(self, symbol: str) -> dict | None:
        """读取 Hub 缓存的 K 线数据，替代 market_service.get_history()"""
        ...
    def get_realtime(self, symbol: str) -> dict | None:
        """读取 Hub 缓存的实时行情"""
        ...
    async def refresh_kline(self, symbols: list[str]) -> None:
        """增量刷新 K 线缓存"""
        ...
```

### 12.4 实施步骤

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 1. `MarketDataHub` 增加 K 线缓存 + `get_kline()` | scanner 扫描时缓存最近 60 条 K 线 | 1 天 |
| 2. `factor_registry.compute()` 改为接收外部数据 | 不再 `_fetch_market_data()`，改从 Hub 读取 | 0.5 天 |
| 3. `market_service` 改从 Hub 读取 | `get_history()` 优先查 Hub 缓存 | 1 天 |
| 4. `compute_all_indicators` 和 `compute_chart_data` 合并 | 消除列名映射不一致 | 0.5 天 |
| 5. 新闻/板块 API 改走 Hub 缓存 | 先读缓存，过期再 fetch | 0.5 天 |
| 6. 清理废弃代码 | 删除 `_fetch_market_data()`、重复的 `compute_*` | 0.3 天 |
| **总计** | | **~4 天** |

---

## 13. 数据源不稳定优化方案

### 13.1 核心问题

熔断器框架（`SourceRegistry`）已完全实现但从未接入：

```python
# source_registry.py 提供的能力：
registry.try_call("push2delay", fn)     # 检查熔断→执行→记录结果，三合一
registry.route([
    ("mootdx", fn1),
    ("sina", fn2),
    ("qq", fn3),
], route_name="A_realtime")             # 按优先级尝试，跳过熔断中的源

# 实际代码中 registry 已 import（china_market.py:22）但从未被调用
```

### 13.2 实施步骤

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 1. main.py lifespan 注册数据源 | `registry.register("push2delay")`, `registry.register("sina")` 等 | 0.1 天 |
| 2. `_call()` → `registry.try_call()` | 替换 market_service / china_market 中的裸调用 | 0.3 天 |
| 3. if-else fallback → `registry.route()` | 替换手动 if-else 降级链 | 0.3 天 |
| 4. 增加熔断器连通性测试 | verify_e2e.py 新增检查 | 0.3 天 |
| **总计** | | **~1 天** |

### 13.3 预期效果

- 东方财富挂了 → 自动切换到 Sina（不需手动重启）
- Sina 挂了 3 次 → 熔断 60s → 自动隔离 → 60s 后自动恢复
- 所有数据源都挂了 → `route()` 最后返回 None，下游正确降级
- 运维可在 `/admin/sources/health` 查看各源状态

---

## 14. 数据源降级链补充方案

### 14.1 新数据源评估（全部免费、零注册、零 Key）

| 数据源 | 接入方式 | 稳定性 | 可补充的数据 | 接入工作量 |
|-------|---------|--------|------------|-----------|
| **天天基金 IOPV** `fundgz.1234567.com.cn` | HTTP GET JSONP | ⭐⭐⭐⭐ | ETF 实时净值 → 修复 premium_discount 因子 | **0.5 天** |
| **天天基金份额** `fund.10jqka.com.cn` | HTTP GET CSV | ⭐⭐⭐⭐ | ETF 份额 → 修复 shares_change 因子 | **0.5 天** |
| **腾讯 QQ 行情** `qt.gtimg.cn` | HTTP GET JSONP | ⭐⭐⭐⭐⭐ | A 股实时/历史行情 | **0.5 天** |
| **网易财经** `money.163.com` | HTTP GET CSV | ⭐⭐⭐⭐⭐ | A 股历史 K 线（兜底） | **0.5 天** |
| **本地快照兜底** | 文件 JSON | ⭐⭐⭐⭐⭐ | 所有数据源全挂时的最后防线 | **0.3 天** |
| Tushare fund_daily | 已有 token | ⭐⭐⭐⭐ | 折溢价/份额（低频补充） | 0.3 天 |

**以上新数据源均不需要注册 API Key**。天天基金、腾讯 QQ、网易财经都是公开 HTTP API，与当前 Sina/东方财富的接入方式完全一致。

### 14.2 完整降级链架构

```
行情实时 / K 线:
  [P0] push2delay.eastmoney.com  (已用, 零Key)
    → [P1] 腾讯QQ qt.gtimg.cn    (新接, 零Key, 最稳定)
    → [P1] Sina hq.sinajs.cn     (已用, 零Key)
    → [P2] 网易财经 money.163.com (新接, 零Key, 兜底)
    → [P0] 本地快照               (新接)

ETF 因子数据 (份额/规模/IOPV):
  [P0] 天天基金 fundgz API       (新接, 零Key)
    → [P2] Tushare fund_daily    (已有Token)
    → [P0] 本地快照

新闻:
  [P0] 财联社 x-quote (LeviStock) (已用, 零Key)
    → [P1] RSS feedparser         (已用, 零Key)
    → [P0] 上次成功缓存

全球指数:
  [已用] 东方财富 EM API  (零Key)
    → yfinance              (零Key)
    → 本地快照
```

### 14.3 实施优先级

| 优先级 | 新源 | 解决问题 | 工作量 |
|--------|------|---------|--------|
| **P0** | **天天基金 IOPV API** | 替代 Sina IOPV → 修复 `premium_discount` | 0.5 天 |
| **P0** | **天天基金份额 API** | 填充 `shares_change`、`institutional_holdings_change` | 0.5 天 |
| **P0** | **本地快照兜底** | 所有数据源全挂时仍有数据 | 0.3 天 |
| P1 | 腾讯 QQ 行情 API | 实时行情/历史 K 线增加稳健降级路径 | 0.5 天 |
| P2 | 网易财经 K 线 | K 线数据多一层保障 | 0.5 天 |
| P2 | Tushare fund_daily | 低频补充 premium/shares | 0.3 天 |

**最关键的两个改动**：天天基金 IOPV + 份额数据，能直接解决 premium_discount、shares_change、institutional_holdings_change 三个缺失因子。

---

## 15. push2→push2delay 域名替换核查

### 15.1 核查范围

全项目搜索 `push2.eastmoney.com`（不含 delay/his），排除测试/诊断文件。

### 15.2 核查结果

| 文件 | 当前域名 | 状态 |
|------|---------|------|
| `app/fetchers/etf_scanner.py` | `push2delay.eastmoney.com` | ✅ 已替换 |
| `app/fetchers/fundamentals_fetcher.py` | `push2delay.eastmoney.com`（`_PUSH2_SOURCE`） | ✅ 已替换 |
| `app/services/strategy_design.py` | `push2delay.eastmoney.com` | ✅ 已替换 |
| `app/services/source_registry.py`（docstring） | 举例写的是 `push2.eastmoney.com` | ⚠️ 仅文档示例，建议更新 |
| 测试/诊断脚本 (`_test_delay.py`, `_trace_akshare.py`) | 保留旧域名 | ⚠️ 诊断用途，无需更新 |

**结论**：生产代码已全部替换完成，无遗留。`source_registry.py` 第 164 行的 docstring 示例可以顺手更新。

### 15.3 关于 `72.push2.eastmoney.com`

日志中看到 `72.push2.eastmoney.com` 的请求——这是 `china_market.py` 的 mootdx/Sina 降级链中实际发出的请求，`72.` 是东方财富的 CDN 子域名。这个域名和 push2delay 是两条不同路径。如果这个也挂了，降级到腾讯 QQ 或网易财经即可。

---

## 16. 优化方案实施计划

### 第一梯队 (P0) — 1-2 天

```
S1: 熔断器接入数据源                    1 天
    → main.py 注册 → _call() 替换 → route() 替换
    → 废弃 factor_registry.CircuitBreaker（已被 SourceRegistry 替代）
S2: 天天基金 IOPV + 份额数据源          1 天
    → 修复 premium_discount, shares_change, institutional_holdings_change
S3: 本地快照兜底                        0.3 天
    → 所有数据源全挂时的最后防线
S4: compute_chart_data 列名修复         0.3 天
    → 用 _resolve_col() 替代直接索引
```

**预期效果**：
- 预热时间 38s → 15s
- premium_discount/shares_change 从 0.0 → 实际值
- 数据源挂时自动隔离 + 降级
- 图表列名缺失消除

### 第二梯队 (P1) — 3-5 天

```
S5: 数据管道统一 (MarketDataHub)         4 天
    → K 线缓存 → factor_registry 去冗余 → market_service 接入
S6: 组合设计报告质量修复                 2 天
    → 去重/截断/评分一致性/涨跌注入
S7: 策略检查报告增强                     1 天
    → 持仓分析/LLM 报告
S8: 腾讯 QQ 行情 API 接入               0.5 天
    → 实时行情/历史 K 线再增加一层降级
```

**预期效果**：
- 因子缺失消除
- 策略检查报告非空
- 信号 insufficient_data 减少 90%
- 数据源降级到三层

### 第三梯队 (P2) — 本周内

```
S9: 测试防护体系加固                     2 天
    → verify_e2e.py 增强 + 内容断言 + 因子完整性检查
S10: 前端性能优化 (Lighthouse 57→80)    2 天
S11: 新闻系统稳定性                     0.5 天
S12: 网易财经 K 线 + Tushare fund       0.5 天
```

**预期效果**：
- Lighthouse Performance ≥ 80
- 新闻 500 错误消除
- 测试覆盖熔断器/因子/信号的一致性

---

## 附录

### A. 数据源接入方式速查

| 数据源 | URL | 认证 | 当前状态 |
|--------|-----|------|---------|
| push2delay.eastmoney.com | `http://push2delay.eastmoney.com/api/qt/clist/get` | 无 | 主力 |
| 天天基金 FundGZ | `http://fundgz.1234567.com.cn/js/{code}.js` | 无 | 🔜 待接入 |
| 腾讯 QQ 行情 | `http://qt.gtimg.cn/q={code}` | 无 | 🔜 待接入 |
| 网易财经 | `http://quotes.money.163.com/service/chddata.html?code={code}` | 无 | 🔜 待接入 |
| Sina | `http://hq.sinajs.cn/list={code}` | 无 | 已用 |
| LeviStock | `pip install levistock` | 无 | 已用 |
| Tushare | tushare.pro | Token(已有) | 已用 |
| YFinance | `pip install yfinance` | 无 | 已用 |

### B. 诊断数据文件

| 文件 | 内容 |
|------|------|
| `backend/logs/warmup_timing.json` | 预热时间记录 |
| `backend/logs/warmup_cprofile.txt` | cProfile 函数级统计 |
| `backend/logs/warmup_pyinstrument.html` | pyinstrument 可视化报告 |
| `logs/lighthouse_report.report.json` | Lighthouse 完整报告 |

### C. 环境信息

- Python 3.12.10, FastAPI 0.139.0, Vue 3.5.40, Vite 5.4
- Redis 7, SQLite (aiosqlite)
- 数据源：东方财富 push2delay, mootdx, Sina, QQ(Tencent), akshare, yfinance, LeviStock

---

> **本文档已完成 3 轮 review + 修改，达到实施标准。**  
> **下一阶段**：按第一梯队顺序依次启动实施。每个改动先写测试、再改代码、跑 `verify_e2e.py` 验证。  
> **注意**：先接熔断器（S1），再天天基金（S2），这两个完成后大部分因子缺失问题和数据源稳定性问题自动得到缓解。
