# ETF Surge — 全面诊断与优化修复方案

> 测试日期: 2026-07-29
> 测试环境: Docker Compose (dev profile), Python 3.12, Node 18, Redis 7

---

## 目录

1. [诊断概要](#1-诊断概要)
2. [后端预热性能诊断](#2-后端预热性能诊断)
3. [组合设计与策略检查](#3-组合设计与策略检查)
4. [市场行情分析质量评估](#4-市场行情分析质量评估)
5. [技术分析与综合信号评估](#5-技术分析与综合信号评估)
6. [资讯页面质量评估](#6-资讯页面质量评估)
7. [因子模型评估](#7-因子模型评估)
8. [前端性能诊断 (Lighthouse)](#8-前端性能诊断-lighthouse)
9. [后端全链路性能诊断](#9-后端全链路性能诊断)
10. [测试防护体系分析](#10-测试防护体系分析)
11. [优化与修复方案](#11-优化与修复方案)
12. [实施优先级](#12-实施优先级)

---

## 1. 诊断概要

### 发现问题数量: **18项**
- **P0 (阻塞性)**: 6项
- **P1 (重要)**: 6项
- **P2 (一般)**: 4项
- **P3 (建议)**: 2项

### 关键问题摘要

| 领域 | 问题 | 严重度 |
|------|------|--------|
| 后端预热 | ETF缓存预热7.8s (akshear demjson 解析瓶颈) | P0 |
| 组合设计 | 设计报告无"今日涨跌"数据, 每日涨跌列全为空 | P1 |
| 组合设计 | 同一ETF在不同方案中的多因子评分不一致 | P1 |
| 策略检查 | 120s超时, 因子计算数据获取太慢 | P0 |
| 技术分析 | 布林带带宽始终为0 (计算无效) | P0 |
| 因子模型 | 因子IC管道断裂: 33个因子全部no_data, 4层链路完全不通 | P0 |
| 板块数据 | 行业/概念板块默认仅返回80条,实际全量496/513条 | P1 |
| 前端性能 | Lighthouse Performance评分29 (极低) | P0 |
| 前端性能 | LCP 26.6s (极其严重) | P0 |
| 前端性能 | 大量未使用JavaScript (~9900ms可优化) | P0 |
| 资讯分级 | 新闻level/stars分级标准不够透明 | P2 |
| 交易时间 | 市场已收盘但系统显示"closed"(港股A股均closed) | P2 |
| 测试防护 | verify_e2e未覆盖因子IC计算校验、布林带校验 | P1 |
| 测试防护 | 单元测试未模拟慢速外部数据源场景 | P2 |
| LLM报告 | 生成耗时30s, 存在实时性风险 | P1 |
| 文档编码 | design_text 中文出现乱码(ISO-8859-1存储问题) | P2 |
| 因子模型 | IC Tracker代码类型错误: _get_ic_sample_count使用list索引str | P1 |
| 代码迁移 | MarketDataHub重命名未完成: 10处遗留旧代码点待清理 | P1 |
| 板块数据 | 行业/概念板块默认仅返回80条,实际全量496/513条 | P1 |
| 因子模型 | 因子IC管道断裂: 33个因子全部no_data, 4层链路完全不通 | P0 |

---

## 2. 后端预热性能诊断

### 2.1 诊断方法

通过 `WarmupProfiler` 模块 (启用 `PROFILE_WARMUP=1`)，在启动时自动捕获预热各阶段的耗时、cProfile CPU 分析、pyinstrument 调用链追踪。

### 2.2 诊断结果

```
总预热耗时: ~10.1s
├── init_db: 0.83s (DB初始化)
├── redis_init: 0.074s (Redis缓存初始化)
├── warmup_market_cache: 0.196s (行情缓存预热)
├── warmup_global_indices: 1.20s (全球指数缓存预热)
└── warmup_etf_cache: 7.81s (ETF扫描预热) ← 瓶颈！
```

### 2.3 根因分析

**核心瓶颈: ETF 扫描预热 7.81s**

cProfile 数据表明:

| 函数 | 耗时 | 占比 | 说明 |
|------|------|------|------|
| `etf_scanner._sina_tencent_provider` | 7.59s | 97% | Sina/Tencent数据源获取 |
| `akshare.fund_etf_category_sina` | 5.32s | 68% | 新浪ETF分类解析 |
| `akshare.demjson.decode_string` | 6.56s | 84% | demjson非标准JSON解析 |
| 网络I/O (recv_into) | 1.48s | 19% | HTTPS请求 |

**根因: `akshare` 使用 `demjson` 库解析东方财富/新浪返回的非标准 JSON 数据，解析效率极低。** 该库使用纯 Python 实现，循环遍历字符流逐字解析，导致 CPU 密集型惩罚。

### 2.4 pyinstrument 调用链

```
MainThread: 8.937s
├── _regime_sentiment_refresh_loop: 6.597s (其中6.466s为sleep)
└── lifespan: 0.413s
    └── _warmup_global_indices: 0.588s
        └── get_global_indices: 0.575s (HTTP请求)
```

---

## 3. 组合设计与策略检查

### 3.1 组合设计执行

- **设计请求**: 平衡型, 50万资金
- **状态**: 成功 (quick_ready)
- **方案数**: 3套 (防御型/平衡型/进攻型)
- **ETF总数**: 34只

### 3.2 报告质量评估

| 评估维度 | 评分 | 说明 |
|----------|------|------|
| 逻辑性 | ★★★★☆ | 三种方案分层清晰, 风控合理 |
| 可读性 | ★★★☆☆ | 使用Markdown表格, 终端渲染不佳; 有重复标题 |
| 数据完整性 | ★★☆☆☆ | "今日涨跌"列全为空; 核心技术面分数缺失 |
| 准确性 | ★★★☆☆ | 同一ETF在不同方案分数不同(如563880在防御型0.37, 平衡型-1.16) |
| 投资判断 | ★★★★☆ | 风格定位合理, 防御型配债券黄金, 进攻型卫星仓位更高 |
| 市场匹配 | ★★★☆☆ | 市场判为"震荡格局", 但未充分利用最新行情数据 |

### 3.3 策略检查执行

- **请求**: portfolio_type=on_exchange, 50万资金
- **状态**: 失败 (120s超时)
- **错误信息**: "策略检查超时（120s）"
- **根因**: 策略检查需要计算33维因子, 其中因子计算依赖从东方财富/eastmoney 抓取全市场数据, 抓取40+页数据后超时

### 3.4 发现的问题

**P1: 每日涨跌数据缺失**
- `design_text` 和 API 返回中的 `今日涨跌` 列全部为 `—`
- 前端用户无法看到当天涨跌情况
- 根因: `get_factor_matrix()` 或 `get_pool()` 未在设计中包含实时价格变动

**P1: 因子评分方案间不一致**
- 563880(A500ETF汇添富)在防御型评分为0.37, 在平衡型为-1.16
- 同一ETF的因子分数不应因方案不同而变化
- 根因: 因子计算每次调用重新执行或依赖缓存状态

**P0: 策略检查超时**
- 120s 超时后无结果
- 根因: 因子计算需要拉取东方财富全量数据, 无有效缓存/降级策略

---

## 4. 市场行情分析质量评估

### 4.1 测试范围

| 端点 | 状态 | 耗时 | 质量评估 |
|------|------|------|----------|
| GET /market/realtime | PASS | 0.48s | 8个主要指数, 数据完整 |
| GET /market/indices/global | PASS | 0.62s | A股/港股/日经/美股, 但序列化格式有问题 |
| GET /market/sectors/industry | PASS | 0.03s | 80个(默认) / 496个(不限量) |
| GET /market/sectors/concept | PASS | 0.03s | 80个(默认) / 513个(不限量) |
| GET /market/sentiment | PASS | 0.11s | 涨跌分布/涨停板数据完整 |
| GET /market/hot-plates | PASS | 0.03s | 热点板块+上涨原因 |
| POST /analysis/llm-report | PASS | 30.30s | 结构化分析报告, 1806字 |
| POST /analysis/llm-news-analysis | PASS | N/A | 新闻影响分析, 板块级影响评估 |
| POST /analysis/llm-advice | FAIL | N/A | 入参问题(query字段缺失) |

### 4.2 质量评估

**综合研判 (LLM Report): ★★★★☆**
- 市场阶段判断合理("横盘消化", "range_bound")
- 包含宏观流动性、板块轮动、资金行为等维度
- 数据引用具体(如"创业板指+1.58%", "科创50-0.72%")
- 亮点: 提到了地缘政治风险(伊朗导弹袭击)、AI板块波动等

**板块/概念分析: ★★☆☆☆ (受限于默认限额)**
- 默认仅返回各80条(limit=80), 实际全量行业496条、概念513条, 覆盖仅~16%
- 热点板块包含涨跌原因
- 连续涨停板统计合理
- 概念板块POPULAR_CONCEPTS兜底机制会产生虚拟占位条目(code为空/价格0)

**市场情绪: ★★★★☆**
- 涨跌分布、涨停板数据详实
- 资金流向数据可用
- 但存在十进制显示问题(如"2.15万亿"显示为"2.15ä¸‡äº¿")

**AI投顾 (LLM Advice): ★★☆☆☆**
- POST请求入参定义模糊, 使用 `query` 字段时报错
- 接口适配性需要提升

### 4.3 发现的问题

**P2: 全局指数序列化问题**
- `market/indices/global` 返回的某些对象以字符串形式序列化(如 `@{symbol=...}`)，而非标准JSON对象
- 影响前端消费

**P1: 行业/概念板块默认仅返回80条, 严重不全**
- 路由 Query 默认 limit=80, 但实际全量分别为496/513条
- 用户只能看到 ~16% 的板块数据
- fetch_concept_sectors 内部有 POPULAR_CONCEPTS 兜底插入虚拟占位条目

**P2: 文本编码问题**
- 市场情绪中的中文数字(如"万亿")显示为乱码
- design_text 中的中文也存在编码问题

---

## 5. 技术分析与综合信号评估

### 5.1 测试标的

| 标的 | 代码 | 信号 | 评分 | 技术指标 |
|------|------|------|------|----------|
| 沪深300ETF | 510300 | hold | -1.5 | MACD死叉空头, MA5<MA20, RSI=40.8 |
| 黄金ETF | 518880 | buy | 2.0 | MACD偏多, MA5>MA20多头排列 |
| 法国ETF | 513080 | hold | -1.5 | MACD死叉空头, MA5<MA20 |
| 30年国债ETF | 511090 | hold | 1.5 | RSI=65.4偏强, MACD金叉多头 |

### 5.2 质量评估

| 评估维度 | 评分 | 说明 |
|----------|------|------|
| 指标完整性 | ★★★☆☆ | MA系列完整, MACD有, RSI有, KDJ有 |
| 信号逻辑 | ★★★★☆ | 信号与指标逻辑一致 |
| 数据准确性 | ★★☆☆☆ | 布林带数据无效(全部为0) |
| 实时性 | ★★★★☆ | 价格数据合理 |
| 多样性 | ★★★★☆ | 涵盖多种资产类型 |

### 5.3 发现的问题

**P0: 布林带(Bollinger Bands)计算无效**
- 所有标的的布林带数据: `{ma: 0, upper: 0, lower: 0, bandwidth: 0}`
- `bandwidth=0%` 意味着计算完全失败
- 信号报告中仍然引用 "布林带宽窄(0.0%) 变盘前兆"，这是错误的投资信号
- **根因**: `get_factor_matrix()` 或技术指标计算中的某个环节无法正确计算布林带

**P2: RSI超卖/超买标记逻辑偏差**
- 518880(黄金ETF) RSI=0.1 标记为"超卖区域"，但其价格数据合理
- RSI=0.1 在正常情况下几乎不可能，可能是数据窗口不足导致的计算错误

---

## 6. 资讯页面质量评估

### 6.1 测试结果

| 端点 | 状态 | 数据量 | 质量 |
|------|------|--------|------|
| GET /news/headlines | PASS | 多条 | 含标题/内容/时间/来源/等级/stars |
| GET /news/macro | PASS | 多条 | 宏观新闻分级 |
| GET /news/global | PASS | 多条 | 英文国际新闻 |
| POST /analysis/llm-news-analysis | PASS | 长文本 | AI综合分析 |

### 6.2 等级划分评估

新闻 `level` 和 `stars` 的分布:

| 级别 | stars | 数量占比 | 示例 |
|------|-------|----------|------|
| level=1 | 3星 | 少数 | "基金经理清仓式离任"(人员变动) |
| level=2 | 4星 | 多数 | "美联储利率决议来袭"(市场焦点) |
| 未标注 | - | 部分 | 国际英文新闻部分缺失level |

**评估: ★★★☆☆**
- 分级存在但不完整，国际新闻的 level 未标注
- 分级标准不够透明，用户无法理解为何某些新闻被标为 level 2 vs level 1
- AI 新闻分析质量较高，能够针对新闻内容做板块级影响分析和判断

### 6.3 发现的问题

**P2: 国际新闻分级缺失**
- 国际新闻(RSS源)缺少 `level` 和 `stars` 字段
- 影响前端统一展示

**P3: 新闻时效性标记**
- 部分新闻的 `time` 字段格式不统一

---

## 7. 因子模型评估

### 7.1 因子状态

| 类别 | 因子数 | 有效IC | 警告 | 无数据 |
|------|--------|--------|------|--------|
| china_specific | 3 | 0 | 0 | 3 |
| etf_specific | 10 | 0 | 0 | 10 |
| microstructure | 10 | 0 | 0 | 10 |
| sentiment | 4 | 0 | 0 | 4 |
| style | 2 | 0 | 0 | 2 |
| technical | 14 | 0 | 0 | 14 |
| **合计** | **33** | **0** | **0** | **33** |

### 7.2 质量评估

**评分: ★☆☆☆☆**

- 33个因子全部未实际计算(IC值全部为None)
- 因子注册表完整但实际计算链路断裂

### 7.3 根因分析: 4层链路断裂

```
GET /factors/active 中 ic_value 全部为 None
  └─ registry._last_ic_batch = {} (从未被更新)
       └─ compute_periodic_ic() 返回空dict
            ├─ factor_values 未传入(market_data为None)
            └─ _fetch_market_data() 返回空数据
                 └─ fetch_history 从东方财富获取K线失败/超时
```

**第1层: _last_ic_batch 从未被有效更新**

`factor_registry.py:1131-1136`:
```python
ic_batch = ic_tracker.compute_periodic_ic(result, market_data, window=1)
if ic_batch:  # <- 空dict时条件不满足
    self._last_ic_batch = ic_batch
```
即使IC计算返回，也会被`if ic_batch:`过滤（空dict视为False）。

**第2层: compute_periodic_ic 返回空**

`ic_tracker.py`:
```python
if not factor_values or not market_data:
    return {}  # <- 任一为空就直接返回
```
需要 `factor_values`（因子值）和 `market_data`（行情K线）同时非空。

**第3层: _fetch_market_data() 半弃用但非直接原因**

该函数 docstring 明确标注 `[DEPRECATED]`，原话：
> "新代码应通过 MarketDataHub.get_kline() 获取 K 线数据。Will be removed in Phase 20."

但在实际运行时，pool_manager 会注入 market_data 到 compute()（`pool_manager.py:377`），
所以 compute() 不会进入 `_fetch_market_data()` 分支。
IC 计算使用的就是 pool_manager 注入的数据。

目前的 `_fetch_market_data()` 仍存在于 factor_registry 中（line 777-961），
仅在以下情况被调用：
1. `warm_cache()` — 预热K线缓存（line 968）
2. `compute()` 中 market_data 为 None 时作为兜底（line 995）

**第4层: MarketDataHub 已存在但 factor_registry 未连接**

实际情况：
- `MarketDataHub = PoolManager`（`market_data_hub.py:10`），两者是同一个类
- `PoolManager.get_kline()` 返回 `{close:[], high:[], low:[], volume:[]}` 格式的K线数据
- `pool_manager` 在调用 `registry.compute()` 时已注入 `market_data=cached_kline`（`pool_manager.py:377`）
- `factor_registry.compute()` 收到注入的 market_data 后直接使用（`line 991-993`），不会调用 `_fetch_market_data()`
- 但 `factor_registry._fetch_market_data()` 代码本身仍存在且未被移除（半弃用状态）

所以从 pool_manager 路径进入时 market_data 有数据，IC 计算有条件执行。
但 IC 全部为 None 的真实原因是：**有两个调用路径，只有一条迁移完成了**。

| 调用方 | 传入 market_data | 数据路径 | 是否完成迁移 |
|--------|:---:|---------|:---:|
| `pool_manager.get_factor_matrix()` (line 375) | ✅ 注入 cached_kline | MarketDataHub | ✅ 已完成 |
| `portfolio_service.strategy_check` (line 406) | ❌ 未传入 | `_fetch_market_data()` | ❌ 未迁移 |

`portfolio_service.strategy_check()` 直接调用 `factor_registry.compute(symbols)`
（line 406: `factor_task = factor_registry.compute(symbols)`），没有传 market_data，
导致进入 `_fetch_market_data()` 旧路径 — 这就是策略检查超时的真正原因。

IC 计算在 `compute()` 内部（line 1120-1146），依赖 market_data 非空。
当 strategy_check 触发 compute() 时：
1. market_data 从 `_fetch_market_data()` 获取，大概率因超时返回空数据
2. IC 计算跳过（market_data 为空）
3. `_last_ic_batch` 从未被有效更新
4. GET /factors/active 看到全部 None

**追加Bug: IC sample count 函数代码错误**

`ic_tracker.py` 的 `_get_ic_sample_count()` 方法:
```python
def _get_ic_sample_count(self, factor_code: str) -> int:
    if factor_code not in self._records:  # BUG: _records 是 list[dict], 不是 dict
        return 0
    rec = self._records[factor_code]  # BUG: 列表不支持 str 索引
    if isinstance(rec, dict):
        return len(rec)
    return 0
```
`self._records` 类型为 `list[dict[str, Any]]`，`factor_code not in self._records` 是在列表元素(dict)中搜索字符串，永远返回True。后续的 `self._records[factor_code]` 列表的字符串索引会抛出 TypeError，但被外层 try/except 静默吞掉。这个函数从一开始就没正常工作过。

### 7.4 发现的问题

**P0: 因子IC计算管道完全断裂**
- 4层链路层层阻隔, 33个因子IC全部为None
- 半弃用代码(_fetch_market_data)与新因子框架不兼容
- 组合设计虽然能用因子评分, 但无法评估因子有效性

**P1: IC Tracker 代码含有类型错误**
- _get_ic_sample_count 错误使用 list 索引字符串
- 外层 try/except 将错误静默吞掉, 从未被捕获
- 修复后可能会暴露更多潜在问题

---

## 8. 前端性能诊断 (Lighthouse)

### 8.1 评分概览

| 指标 | 得分 | 等级 |
|------|------|------|
| **Performance** | **29** | 🔴 极差 |
| Accessibility | 96 | 🟢 优秀 |
| Best Practices | 92 | 🟢 良好 |
| SEO | 91 | 🟢 良好 |
| Agentic Browsing | 37 | 🔴 差 |
| **PWA** | N/A | - |

### 8.2 核心Web指标

| 指标 | 值 | 得分 | 状态 |
|------|----|------|------|
| **First Contentful Paint (FCP)** | **4.6s** | 0.14 | 🔴 极差 |
| **Largest Contentful Paint (LCP)** | **26.6s** | 0.00 | 🔴 极其严重 |
| Total Blocking Time (TBT) | 310ms | 0.77 | 🟡 一般 |
| **Cumulative Layout Shift (CLS)** | **0.58** | 0.11 | 🔴 差 |
| Speed Index (SI) | 8.8s | 0.16 | 🔴 差 |

### 8.3 优化机会

| 机会 | 预估节省 | 说明 |
|------|----------|------|
| **减少未使用的JavaScript** | **~9900ms** | 大量npm依赖未被Tree-shaking |
| **压缩JavaScript** | **~8250ms** | Dev模式未压缩, 生产环境会改善 |
| 减少未使用的CSS | 0ms | 已较优化 |
| 最小化CSS | 0ms | 已较优化 |

### 8.4 根因分析

**P0: LCP 26.6s — 极其严重**
- 根因: Vue Dev Server(开发模式)按需打包, 无代码分割/懒加载
- 所有Vue组件和依赖首次加载时构建, 导致首屏JS尺寸巨大
- 生产构建(nginx + 静态文件)将大幅缓解, 但CLS和未使用JS问题依然存在

**P0: Performance 29分**
- 主要原因: 大量未使用JavaScript + 长首屏加载时间
- 次要原因: CLS 0.58说明布局稳定性差, 可能有未设置宽度的图片/组件

**P1: CLS 0.58**
- 布局位移较大, 可能与动态内容加载有关
- 图表组件(ECharts)加载后可能改变布局

---

## 9. 后端全链路性能诊断

### 9.1 端点响应时间

| 端点 | 耗时 | 状态 |
|------|------|------|
| GET /health | 0.04s | 🟢 极快 |
| GET /portfolio/etfs | 0.04s | 🟢 极快 |
| GET /news/headlines | 0.01s | 🟢 极快 |
| GET /factors/active | 0.00s | 🟢 极快(内存数据) |
| GET /factors/model | 0.00s | 🟢 极快(内存数据) |
| GET /market/hot-plates | 0.03s | 🟢 极快 |
| GET /market/sectors/industry | 0.03s | 🟢 极快 |
| GET /market/indicators/510300 | 0.06s | 🟢 极快 |
| GET /market/signal/510300 | 0.09s | 🟢 极快 |
| GET /market/sentiment | 0.11s | 🟢 极快 |
| GET /market/realtime | 0.48s | 🟢 快 |
| GET /market/indices/global | 0.62s | 🟢 快 |
| **POST /analysis/llm-report** | **30.30s** | 🔴 慢 |
| **POST /portfolio/strategy-check-async** | **>120s** | 🔴 超时 |
| **POST /portfolio/design-async** | **~30s** | 🟡 可接受但偏慢 |

### 9.2 关键发现

1. **GET端点普遍优秀**: 所有GET端点响应时间<1s, 缓存利用率高
2. **LLM报告30s**: 属于合理范围(LLM推理时间), 但有优化空间
3. **策略检查超时**: 因子计算管道阻塞, 需要数据获取优化
4. **预热10s**: 启动时间需要考虑生产部署的优雅启动策略

### 9.3 发现的问题

**P1: LLM超时配置风险**
- LLM报告有90s超时保护, 但策略检查仅有120s
- 市场数据波动期间, 外部API响应可能更慢

**P2: 缺少性能基准测试**
- 无定期性能回归测试
- 无法检测性能退化

---

## 10. 测试防护体系分析

### 10.1 当前测试防护体系

| 测试类型 | 覆盖范围 | 状态 |
|----------|----------|------|
| 单元测试(pytest) | 后端单测(7个用例) | 存在 |
| 前端测试(vitest) | 基础组件测试 | 存在 |
| E2E验证(verify_e2e.py) | 核心链路存活检查 | 存在 |
| pre-commit门禁 | Vue构建检查 | 存在 |

### 10.2 为何未能识别以上问题

| 问题 | 测试疏漏 | 原因分析 |
|------|----------|----------|
| 布林带计算为0 | verify_e2e 未校验指标数据质量 | verify_e2e只检查HTTP状态码和字段存在性, 不校验数据值的合理性 |
| 因子IC全为0 | 单测mock了所有因子计算 | 单测使用mock, 不会捕获真实因子计算链路的断裂 |
| 策略检查超时 | 单测使用超短超时mock | 未测试真实数据获取场景下的性能 |
| 预热10s瓶颈 | 无预热性能断言 | 未对预热时间设性能门限 |
| 前端Performance 29分 | 无前端性能CI门禁 | pre-commit只检查构建, 不做性能评分 |
| 设计报告"今日涨跌"为空 | verify_e2e不检查字段值 | E2E只检查"有数据", 不检查"数据合理" |
| 新闻分级缺失 | 未校验所有数据源的level字段 | 测试未覆盖国际新闻的字段完整性 |
| CLS 0.58 | 无前端布局稳定性测试 | 未引入Lighthouse门禁 |

### 10.3 核心缺陷

1. **验证深度不足**: verify_e2e只检查HTTP可达性和字段存在性, 不做数据质量校验
2. **Mock掩盖问题**: 单测大量使用mock, 不暴露真实数据管道的断裂
3. **无性能门禁**: 预热时间、API响应时间、首屏加载时间无门禁
4. **缺少E2E数据校验**: 未对关键字段值做合理性校验(如布林带≠0)
5. **边界场景缺失**: 外部数据源超时、国外数据源无分类等场景未覆盖

---

## 11. 优化与修复方案

### 11.1 P0 级别修复

#### F1: akshare demjson 解析优化
**问题**: ETF预热7.8s, demjson占5.3s

**方案**:
```python
# 方案A: 使用 orjson 替代 demjson (高风险)
# 方案B: 缓存首次解析结果 (中风险)  
recommended: 方案C - 使用标准 json.loads + 预处理清理非标字符
- 在 etf_scanner 中对 akshare 返回数据做预处理
- 用正则清理非标准JSON字符后使用 json.loads (标准C实现)
- 预计可将 demjson 的5.3s降至<0.5s
```

**验证**: 预热耗时 <3s

#### F2: 布林带计算修复
**问题**: 所有标的 bandwidth=0

**方案**:
- 检查 `compute_bollinger_bands()` 或等值函数中的除法/窗口逻辑
- 确保足够窗口期(至少20个bar)
- 增加 `assert bandwidth > 0` 的保护断言

**验证**: 对所有标的执行 `GET /market/indicators/{symbol}`, 检查 bandwidth > 0

#### F3: 策略检查超时修复
**问题**: 因子计算拉取全量数据超时

**方案**:
```python
- 增加因子缓存层: 在 TaskManager 中缓存因子矩阵(60s TTL)
- 增加数据获取超时熔断: 每页数据获取 >5s 则跳过
- 添加降级模式: 当外部数据源不可用时使用缓存
- 增加分页并发获取: 使用 asyncio.gather 并发拉取多页
```

**验证**: 策略检查在 <60s 内完成
- F16 因子IC管道修复也影响策略检查的数据获取性能

#### F4: 前端 Performance 优化
**问题**: Lighthouse Performance 29分, LCP 26.6s

**方案**:
- 生产构建(生产环境自动解决): npm run build 启用压缩/代码分割
- 代码分割: 对路由级组件使用 `defineAsyncComponent` 懒加载
- Tree-shaking: 检查 ECharts 按需引入, 减少包体积
- CSS优化: 提取关键CSS内联
- 图片优化: 设置明确宽高以避免CLS

**验证**: 生产构建后 Lighthouse Performance > 70

#### F5: 因子计算通道修复
**问题**: 所有因子IC为0

**方案**:
- 在 `factor_registry.py` 中添加 `compute_ic()` 的完整实现
- 使用回测数据计算因子IC值
- 添加定期IC更新(每小时)
- 增加IC值域校验: IC不应为0
- F16 详细描述了IC管道修复方案, 两方案需同步实施

**验证**: GET /factors/active 中 avg_ic 不应全为0

### 11.2 P1 级别修复

#### F6: 每日涨跌数据补全
**方案**: 在组合设计的 response 中添加 `change_pct` 字段, 从实时行情数据获取

#### F7: LLM报告性能优化
**方案**:
- 实现流式响应(SSE)以改善用户体验
- LLM推理超时控制, 截断后返回部分结果
- 缓存常见问题的LLM回复(5分钟TTL)

#### F8: 同一ETF跨方案评分一致性
**方案**: 将因子评分从设计阶段分离, 预计算后缓存, 各方案共享同一评分

#### F9: 因子缓存机制
**方案**:
- 因子矩阵使用 Redis 缓存, TTL 60s
- 缓存命中时直接返回, 避免重复计算

### 11.3 P2 级别修复

#### F10: 全局指数序列化修复
**方案**: 修复 `market_service.get_global_indices()` 中的返回值格式, 确保使用dict而非对象

#### F11: 中文编码修复
**方案**: 使用 UTF-8 编码存储和传输所有数据, 确保数据库和JSON编码一致

#### F12: 新闻分级统一
**方案**: 对国际新闻也执行 level/stars 计算

### 11.4 P3 级别建议

#### F13: 添加性能基准CI
**方案**: 在 CI 中集成 Lighthouse CI, 设定性能门禁

#### F14: 添加数据质量断言
**方案**: 在 verify_e2e 中添加数据值合理性检查

### 11.5 新增 P0/P1 修复（基于第2轮深入诊断）

#### F15: 板块数据默认限额修复 (P1)
**问题**: 行业板块默认80条(全量496), 概念板块默认80条(全量513), 且概念含虚拟占位条目

**方案**:
```python
# 方案A (推荐): 路由层提高默认limit
# market.py line 258, 270
async def industry_sectors(limit: int = Query(500)):  # 80 -> 500
async def concept_sectors(limit: int = Query(500)):   # 80 -> 500

# 方案B: 去除fetch_concept_sectors的POPULAR_CONCEPTS兜底逻辑
# POPULAR_CONCEPTS 插入的虚拟条目没有 sector_code, price=0, 无法消费
# 改为: 真实数据达不到60条时才补充, 且补充分支应设置sector_code
```

**验证**: GET /sectors/industry 返回 >=300 条; GET /sectors/concept 返回 >=300 条; 无空code或价格为0的虚拟条目

#### F16: 因子IC计算管道修复 (P0)
**问题**: 4层链路断裂导致33个因子IC全部为None

**方案A (推荐)**: 完成 MarketDataHub 迁移，消除旧路径

核心发现：这不是"新建数据管道"的问题，而是**迁移不完整**。
`MarketDataHub = PoolManager` 已就绪，但 `portfolio_service` 和 `factor_registry` 仍走旧路径。

三步修复：

**Step 1 — portfolio_service 改用 pool_manager 获取因子数据**

```python
# portfolio_service.py - strategy_check 改用 get_factor_matrix
# 旧: factor_scores = await factor_registry.compute(symbols)
# 新: 通过 pool_manager 获取（已含 MarketDataHub 缓存注入）
from ..services.pool_manager import pool_manager  # 全局实例

factor_scores = await pool_manager.get_factor_matrix(symbols)
```

**Step 2 — factor_registry.compute() 兜底路径改为 MarketDataHub**

```python
# factor_registry.py - 当未注入 market_data 时走 MarketDataHub
# 而非调用 _fetch_market_data()
from ..services.pool_manager import PoolManager

async def compute(self, symbols, market_data=None):
    if market_data is None:
        # 走 MarketDataHub 路径
        hub = PoolManager()
        market_data = {}
        for sym in symbols:
            kline = hub.get_kline(sym)
            if kline:
                market_data[sym] = kline
            else:
                logger.warning("[factor] No cached kline for %s", sym)
                market_data[sym] = {"close": [], "high": [], ...}
```

**Step 3 — 清理旧代码**

- 移除 `_fetch_market_data()` 方法（整个 185 行代码）
- 或者保留但标记为 `@deprecated` 并在下次大版本移除
- 删除 `_get_cached_kline()` / `_cache_kline()` 等辅助函数

**附加修复**: `_get_ic_sample_count()` 的类型错误

#### F17: 完成 MarketDataHub 重命名迁移清单 (P1)

**背景**: `MarketDataHub = PoolManager` 别名已创建 (`market_data_hub.py:10`)，pool_manager 已完成迁移，
但有多处遗留代码仍引用旧函数名或全局缓存。以下为完整的清理清单。

**所有待重命名/移除的代码点:**

| # | 位置 | 行 | 内容 | 动作 | 风险 |
|---|------|-----|------|------|------|
| 1 | `factor_registry.py` | 629-630 | `_kline_cache: dict` + `_kline_cache_ts: float` 全局变量 | 删除 | 低 (pool_manager 已有同名缓存) |
| 2 | `factor_registry.py` | 631 | `KLINE_CACHE_TTL: float = 300.0` | 删除 | 低 |
| 3 | `factor_registry.py` | 634-644 | `_get_cached_kline()` 函数 | 删除 | 低 (pool_manager.get_kline() 替代) |
| 4 | `factor_registry.py` | 647-653 | `_set_kline_cache()` 函数 | 删除 | 低 |
| 5 | `factor_registry.py` | 777-961 | `_fetch_market_data()` 整个方法 (185行) | 移除或标记@deprecated | 中 (需确认无其他外部调用) |
| 6 | `factor_registry.py` | 963-969 | `warm_cache()` 方法 (调用了 _fetch_market_data) | 改为调 PoolManager.get_kline() | 中 |
| 7 | `factor_registry.py` | 995 | `compute()` 中 else 分支调用了 `_fetch_market_data()` | 改为走 MarketDataHub | 高 (核心路径) |
| 8 | `portfolio_service.py` | 406 | `factor_registry.compute(symbols)` 未传 market_data | 改为 pool_manager.get_factor_matrix() | 高 (策略检查路径) |
| 9 | `pool_manager.py` | 121 | `self._kline_cache = {}` 兼容旧字段名 | 移除兼容垫片 | 低 |
| 10 | `china_market.py` | 160, 264 | 注释引用 `_fetch_market_data` | 更新注释 | 低 |

**注意**: 第5项 `_fetch_market_data()` 本身还调用了 `china_market.fetch_history` 和独立的新浪 IOPV
获取逻辑。在移除前需确认这些能力已由 pool_manager.refresh_kline() 覆盖。

**Step-by-step 实施顺序:**

```
第1天 — 安全清理 (低风险)
  1. pool_manager.py:121 — 移除 _kline_cache 兼容垫片
  2. factor_registry.py:629-653 — 删除全局缓存变量和辅助函数
  3. china_market.py:160,264 — 更新注释

第2天 — 核心迁移 (高风险)
  4. portfolio_service.py:406 — 改为 pool_manager.get_factor_matrix()
  5. factor_registry.py:995 — compute() 兜底改为 MarketDataHub

第3天 — 清理验收
  6. factor_registry.py:777-969 — 移除或标记 _fetch_market_data() + warm_cache()
  7. 跑 verify_e2e.py 确认全链路正常
  8. 检查 GET /factors/active 是否不再全为 None
```

**验证**:
- `grep -r "_fetch_market_data" backend/` 返回空 (除了注释中的提及)
- `grep -r "_kline_cache" backend/` 返回空 (除了 pool_manager 内部)
- `verify_e2e.py` 全 PASS
- `GET /factors/active` 中至少出现 3+ 因子 |IC| > 0

```python
# 修复 ic_tracker.py
def _get_ic_sample_count(self, factor_code: str) -> int:
    # 旧: if factor_code not in self._records:  # BUG: list 不能 in 搜索 str
    # 新: 统计 records 中该 factor_code 的出现次数
    return sum(1 for r in self._records if isinstance(r, dict) and r.get("factor_code") == factor_code)
```

**方案B (彻底修复)**: 重构IC计算为新管道
- 在 pool_manager 中新增 `get_market_data_for_ic()` 方法, 统一数据出口
- 移除 `FactorRegistry._fetch_market_data()` 的 DEPRECATED 状态或彻底删除
- 将IC计算移入池管理器的后台周期性任务
- 修复 `_get_ic_sample_count` 的类型错误

**验证**: GET /factors/active 中 avg_ic 不应全为0; 至少有3个以上因子的|IC|>0.02

---

## 12. 实施优先级

**P0 (阻塞性) - 第1-7天**

- **F1**: akshare demjson解析优化 - 2天 (第1-2天)
- **F2**: 布林带计算修复 - 1天 (第3天, 依赖F1)
- **F3**: 策略检查超时修复 - 2天 (第4-5天, 依赖F2)
- **F4**: 前端Performance优化 - 3天 (第4-6天, 可并行F3)
- **F5**: 因子计算通道修复 - 2天 (第6-7天, 依赖F3)
- **F16**: 因子IC计算管道修复 - 2天 (第2-3天, 可并行F1)

**P1 (重要) - 第2-8天**

- **F6**: 每日涨跌数据补全 - 1天 (第3天, 依赖F1)
- **F7**: LLM报告性能优化 - 1天 (第4天, 依赖F6)
- **F8**: 跨方案评分一致性 - 1天 (第3天, 依赖F1)
- **F9**: 因子缓存机制 - 1天 (第8天, 依赖F5)
- **F15**: 板块数据默认限额修复 - 1天 (第1天, 独立)
- **F17**: MarketDataHub重命名清理 - 3天 (第2-4天, 可并行F15)

**P2 (一般) - 第3-9天**

- **F10**: 全局指数序列化修复 - 1天 (第4天, 依赖F8)
- **F11**: 中文编码修复 - 1天 (第3天, 依赖F1)
- **F12**: 新闻分级统一 - 1天 (第4天, 依赖F11)

**P3 (建议) - 第5-10天**

- **F13**: 性能基准CI - 2天 (第7-8天, 依赖F4)
- **F14**: 添加数据质量断言 - 1天 (第6天, 依赖F3)

## 附录

### A. 测试环境

```
后端: FastAPI (Python 3.12, uvicorn --reload)
前端: Vue 3 (Node 18, Vite dev server)
数据库: SQLite (async, aiosqlite)
缓存: Redis 7
LLM: OpenCode Zen (deepseek-v4-flash-free)
Docker: Compose v5.3.1, Engine 29.6.2
```

### B. 测试命令参考

```bash
# 后端预热诊断
PROFILE_WARMUP=1 uvicorn app.main:app --reload

# 查看预热报告
docker exec backend-dev cat /app/logs/warmup_timing.json
docker exec backend-dev cat /app/logs/warmup_pyinstrument.txt

# 前端Lighthouse
lighthouse http://localhost:5173 --output=json --output-path=report.json

# 端到端验证
python scripts/verify_e2e.py

# 后端性能基准
python scripts/measure_warmup.py
```

### C. 已知数据源

| 数据源 | 用途 | 稳定性 |
|--------|------|--------|
| eastmoney (push2) | ETF列表/行情 | 稳定 |
| Sina | 实时行情 | 稳定 |
| Tencent (gtimg) | 批量行情 | 偶有超时 |
| akshare | ETF分类/基金数据 | demjson CPU瓶颈 |
| yfinance | 全球指数 | 受网络限制 |
