# ETF 组合设计链路重构方案

> 将当前"硬编码候选池 + 硬编码分配规则 + 三层降级链"的设计管道，
> 改为**全市场扫描 + 因子模型驱动 + 无降级路径**的架构。
> 统一的因子计算和数据管道可供全系统所有分析链路复用。

---

## 一、现状：要拆掉的东西

### 1.1 strategy_design.py — 1050 行单体

当前 `generate_enhanced_design()` 实际做了五件事：

```
① 数据采集层      compute_etf_trends / fetch_fund_flow / fetch_pe_pb / fetch_news / pool_manager.refresh
② 评分层          自算 z-score 多因子评分（与 FactorRegistry 独立）
③ 分配层（策略引擎）dynamic_core_allocation / dynamic_defense_allocation / 卫星幂律权重 / build_rationale
④ 风控层          科技集中度 C2 / 单行业 40%
⑤ 组装返回
```

其中只有 ③+④ 是"策略引擎"该管的事，其余是基础设施职责。

### 1.2 三条降级链

```
generate_enhanced_design
  ├─ 主链路: pool_manager.refresh() → 全市场扫描 + FactorRegistry 因子分
  ├─ 降级1:  scan_full_pipeline()   → scanner TOP 15（无因子分）
  └─ 降级2:  硬编码 7 只 ETF       → 半导体/AI/新能源/医药/旅游/军工/科创50
```

降级后的方案**缺失因子分和趋势数据**，入选理由中"今日涨跌""近1月走势""资金流向"全部空白。

### 1.3 外部遗留路由

| 路由 | 用途 | 问题 |
|------|------|------|
| `POST /analysis/portfolio-design` | 旧 LLM 设计（塞原始数据给 DeepSeek） | 不走引擎，全靠 LLM "直觉"，结果与因子模型路径不一致 |
| `POST /analysis/portfolio-design/stream` | SSE 流式版 | 同上 |
| `POST /portfolio/design` | 旧同步版设计 | 已被 async 取代，调用 `generate_full_design()`（v3） |
| `POST /portfolio/design-enhanced` | 旧增强版 | 功能被 async 入口合并 |

### 1.4 FactorRegistry 的假数据隐患

```python
# factor_registry.py:522 — 拉取失败时的 fallback
return sym, {
    "close": [4.0 + i * 0.01 for i in range(60)],  # 稳定的上涨序列
    "volume": [1000000 + i * 1000 for i in range(60)],
}
```

若 `fetch_history` 超时或失败，FactorRegistry 返回合成数据。下游 PoolManager 拿到包含假数据的因子分，无法辨别。

### 1.5 6 个 scaffolding 函数返回 0

| 因子 | 状态 | 原因 |
|------|------|------|
| `etf.premium_discount` | 返回 0 | 缺 IOPV 数据源 |
| `etf.tracking_error` | 返回 0 | 缺基准指数数据 |
| `etf.shares_change` | 返回 0 | 缺历史份额数据 |
| `etf.industry_diversification` | 返回 0 | 已可计算，未接 |
| `etf.institutional_holdings_change` | 返回 0 | 缺机构持仓数据 |
| `sentiment.stock_divergence` | 返回 0 | 缺个股级情绪数据 |

### 1.6 各链路数据采集重复

当前各链路各自为政，同一份数据被重复采集：

| 数据 | 设计链路 | 策略检查 | 市场研判 | 个股分析 | 板块分析 | 新闻分析 | 投顾 |
|------|----------|----------|----------|----------|----------|----------|------|
| ETF 因子分 | ⚠️ 双套 | ✅ FactorRegistry | ❌ | ❌ | ❌ | ❌ | ❌ |
| ETF 候选池 | ✅ 硬编码 20 只 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 大盘行情 | ✅ 自采 | ✅ 自采 | ✅ 自采 | ✅ 自采 | ✅ 自采 | ❌ | ❌ |
| 海外指数 | ❌ | ❌ | ✅ 自采 yfinance | ❌ | ❌ | ❌ | ❌ |
| 商品行情 | ❌ | ❌ | ✅ 自采 | ❌ | ❌ | ❌ | ❌ |
| 技术指标 | ✅ 自算 | ✅ 自算 | ✅ 自算 | ✅ 自算 | ❌ | ❌ | ❌ |
| 市场状态 | ✅ 自判 | ✅ 自判 | ❌ | ❌ | ❌ | ❌ | ❌ |
| 宏观状态 | ✅ 自判 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 板块列表 | ❌ | ❌ | ❌ | ❌ | ✅ 自采 | ❌ | ❌ |
| 资讯 | ✅ 自采 | ✅ 自采 | ✅ 自采 | ✅ 自采 | ✅ 自采 | ✅ 自采 | ❌ |
| 成分股明细 | ❌ | ❌ | ❌ | ❌ | ✅ 自采 | ❌ | ❌ |

重构后，统一管道提供 **12 项标准化数据**，各链路按需读取：

| 数据管道产出 | 设计链路 | 策略检查 | 市场研判 | 个股分析 | 板块分析 | 资讯分析 | 投顾 |
|-------------|----------|----------|----------|----------|----------|----------|------|
| `factor_matrix` | ✅ 读取 | ✅ 读取 | ⬜ 可选 | ✅ 候选池内 | ❌ | ❌ | ❌ |
| `candidates` | ✅ 读取 | ✅ 读取 | ❌ | ❌ | ❌ | ❌ | ❌ |
| `market_regime` | ✅ 读取 | ✅ 读取 | ✅ 读取 | ✅ 增强 | ✅ 增强 | ✅ 增强 | ✅ 智能注入 |
| `macro_regime` | ✅ 读取 | ❌ | ✅ 读取 | ❌ | ❌ | ❌ | ✅ 智能注入 |
| `market_sentiment` | ✅ 读取 | ✅ 读取 | ✅ 读取 | ❌ | ❌ | ✅ 读取 | ✅ 智能注入 |
| `sector_momentum` | ✅ 读取 | ❌ | ✅ 读取 | ❌ | ✅ 增强 | ✅ 读取 | ✅ 智能注入 |
| `index_realtime` | ✅ 读取 | ❌ | ✅ 读取 | ❌ | ❌ | ❌ | ✅ 智能注入 |
| `us_indices` | ❌ | ❌ | ✅ 读取 | ❌ | ❌ | ❌ | ✅ 智能注入 |
| `commodities` | ❌ | ❌ | ✅ 读取 | ❌ | ❌ | ❌ | ✅ 智能注入 |
| `industry_sectors` | ❌ | ❌ | ❌ | ❌ | ✅ 读取 | ❌ | ❌ |
| `concept_sectors` | ❌ | ❌ | ❌ | ❌ | ✅ 读取 | ❌ | ❌ |
| `news` | ❌ | ❌ | ✅ 读取 | ✅ 读取 | ✅ 读取 | ✅ 读取 | ✅ 智能注入 |

**仍需自采的仅 2 项**：
1. 板块成分股（板块分析专用，数据量大且绑定板块代码，不适合全局缓存）
2. 候选池外标的行情/指标（个股分析用，无法预知用户查哪个标的）

统一管道搭好后可消除 **90% 以上的重复采集**，管道数据源普遍优于旧链路裸调（如 `us_indices` 经 `market_service.get_global_indices` 封装降级链，优于 `_fetch_all_market()` 直接调 yfinance）。

---

## 二、新架构

### 2.1 核心设计原则

- **一套数据管道**：所有因子计算、市场状态、行情数据由 FactorRegistry + pool_manager 统一产出。只采集一次。
- **多个消费者**：组合设计、策略检查、市场研判、个股/板块分析从同一个数据管道读标准化输出
- **策略引擎是纯函数**：engine/ 包不碰外部 I/O，只消费数据管道的输出
- **无降级**：数据管道失败则链路失败，不出劣质方案

### 2.2 分层架构

```
                         ┌────────────────────────────────────────────┐
                         │           基础数据层（外部源）               │
                         │  akshare / china_market / yfinance / ...   │
                         └───────────────────┬────────────────────────┘
                                             │
                         ┌───────────────────▼────────────────────────┐
                         │             统一数据管道                     │
                         │                                            │
                         │  pool_manager.refresh()                    │
                         │    ├─ 全市场扫描    (etf_scanner)           │
                         │    ├─ 行业/概念分类  (ETFClassifier)        │
                         │    └─ 因子计算      (FactorRegistry)        │
                         │       ├─ 技术因子 (MA/RSI/MACD/KDJ/...)     │
                         │       ├─ 风格因子 (规模/动量)               │
                         │       ├─ ETF 因子 (稳定性/折溢价/...)       │
                         │       ├─ 情绪因子 (恐慌贪婪/新闻热度)       │
                         │       └─ 政策因子 (十四五/双循环/...)       │
                         │                                            │
│  产出:                                      │
│    factor_matrix     {symbol: {24 维因子分}} │
│    candidates        core/satellite/defense  │
│    market_regime     市场状态                │
│    macro_regime      宏观状态                │
│    market_sentiment  市场情绪指数            │
│    sector_momentum   行业动量 TOP N          │
│    index_realtime    A 股大盘实时行情         │
│    us_indices        海外指数实时行情         │
│    commodities       国内+海外商品行情        │
│    industry_sectors  行业板块列表             │
│    concept_sectors   概念板块列表             │
│    news              资讯标题/摘要/等级       │
                         └──────────┬──────┬──────┬──────┬────────────┘
                                    │      │      │      │
              ┌─────────────────────┘      │      └───────────────┐
              ▼                            ▼                      ▼
   ┌────────────────────┐      ┌────────────────────┐   ┌──────────────────────┐
   │ 组合设计 (走引擎)   │      │ 分析链路 (共用因子)  │   │ LLM 分析 (增强       │
   │                    │      │                    │   │ context)             │
   │ engine/allocate()  │      │ strategy_check     │   │ market_report        │
   │ → 3 套方案         │      │ indicators.py      │   │ sector_analysis      │
   │                    │      │ symbol_analysis    │   │ llm_news_analysis    │
   └────────────────────┘      │ sector_analysis    │   │ llm_advice           │
                               └────────────────────┘   └──────────────────────┘
```

### 2.3 数据管道产出详表

| 产出 | 类型 | 来源 | 内容 |
|------|------|------|------|
| `factor_matrix` | `dict[str, dict]` | FactorRegistry.compute | 每只候选 ETF 的 24+ 维因子分（已 z-score 标准化） |
| `candidates` | `dict[str, list[Candidate]]` | pool_manager.get_pool | core/satellite/defense 三层候选，含 industry/concepts |
| `market_regime` | `str` | market_trends.detect_market_regime | bull_strong / bear / correction / defensive_rotate / neutral |
| `macro_regime` | `dict` | macro_state.detect_macro_regime | 利率方向、外部风险、通胀、增长 |
| `market_sentiment` | `dict` | sentiment_fetcher | sentiment_index + sentiment_label |
| `sector_momentum` | `list[dict]` | market_trends.compute_sector_momentum | 申万一级行业 20 日排名变化 |
| `index_realtime` | `list[dict]` | china_market.fetch_index_realtime | A 股大盘指数实时点位/涨跌 |
| `us_indices` | `list[dict]` | market_service.get_global_indices | 海外指数（标普500/纳斯达克/道琼斯/日经/恒生等） |
| `commodities` | `list[dict]` | market_service.get_commodities + china_market.fetch_futures_realtime | 国内商品（沪金/沪银/原油期货等）+ 海外商品（黄金/原油/白银） |
| `industry_sectors` | `list[dict]` | sector_fetcher.fetch_industry_sectors | 行业板块列表（含涨跌幅/成交额），levistock 主源 + akshare 降级 |
| `concept_sectors` | `list[dict]` | sector_fetcher.fetch_concept_sectors | 概念板块列表，同上 |
| `news` | `list[dict]` | news_fetcher.fetch_news_headlines + fetch_macro_news | 资讯标题+摘要+等级，缓存 120s |

### 2.4 新包结构

```
backend/app/
├── engine/                         ← 新建：纯策略引擎
│   ├── __init__.py
│   ├── allocation_engine.py        ← 核心分配器（纯函数）
│   ├── budgets.py                  ← 层预算 + 预期收益
│   ├── rationale.py                ← 基于因子分的入选理由
│   └── risk_controls.py            ← 因子暴露集中度风控
│
├── services/
│   ├── strategy_design.py          ← 重写为薄编排器（约 200 行）
│   ├── pool_manager.py             ← 维持，数据管道核心
│   ├── market_trends.py            ← 维持，regime 检测
│   ├── macro_state.py              ← 维持
│   └── ...
│
├── factors/
│   ├── factor_registry.py          ← 增强：删除假数据、补 KDJ/综合信号、修 scaffolding
│   ├── factor_definitions.yaml     ← 维持
│   └── ic_tracker.py               ← 维持
│
├── fetchers/
│   ├── etf_scanner.py              ← 维持
│   ├── etf_classifier.py           ← 维持
│   └── ...
│
├── analysis/
│   ├── indicators.py               ← 改为包装层，实现委托给 FactorRegistry
│   └── signal.py                   ← 维持
│
└── tasks/
    ├── design_tasks.py             ← 微调 import 路径
    └── ...
```

### 2.5 数据管道缓存策略

| 数据 | TTL | 说明 |
|------|-----|------|
| `factor_matrix` + `candidates` | 120s | pool_manager.refresh 内部缓存 |
| `market_regime` | 60s | 市态变化慢，可随数据管道一起刷 |
| `macro_regime` | 300s | 宏观数据变化更慢 |
| `market_sentiment` | 120s | 随数据管道 |
| `sector_momentum` | 120s | 随数据管道 |
| `index_realtime` | 15s | A 股大盘，独立高频刷新 |
| `us_indices` | 60s | 海外指数变化慢，随数据管道 |
| `commodities` | 60s | 商品行情变化较慢，随数据管道 |
| `industry_sectors` / `concept_sectors` | 120s | 板块数据日频变化，随数据管道 |
| `news` | 120s | 随数据管道刷新，与现有 news_fetcher 缓存共享 |

**注意**：编排器不单独缓存——它读取 pool_manager 的缓存。数据管道由全局 APScheduler 触发刷新（见 `backend/app/tasks/market_refresh.py`：行情 15s，资讯 30s）。

---

## 三、各链路复用方案

### 3.1 组合设计（新链路核心）

**入口**：`POST /portfolio/design-async`

**数据流**（详见 §2.5，此处摘要）：

```
编排器:
  1. pool_manager.refresh()     → factor_matrix + candidates + 市场上下文
  2. engine/allocate() × 3      → 3 套方案（纯函数，无 I/O）
  3. DB 持久化 + WS 推送

复用数据管道: factor_matrix + candidates + regime + macro + sentiment   ✅ 全部
策略引擎: engine/allocate()                                              ✅ 核心
```

### 3.2 策略检查分析

**入口**：`POST /portfolio/strategy-check-async`

**当前**：`strategy_check()` 在 `portfolio_service.py:322` — 自己调 `factor_registry.compute()` 和 `compute_etf_trends()`，但只对用户持仓的几只 ETF 计算，无全市场对比。

**复用方案**：

```
当前 (自己拉):
  factor_scores = await factor_registry.compute(持仓_symbols)   ← 只算持仓

复用后 (从数据管道拿全市场因子分，持仓对标全市场):
  factor_matrix = orchestrator.factor_matrix   ← 编排器已算好全市场 ~45 只
  user_symbols = [e.symbol for e in 持仓]
  user_factors = {sym: factor_matrix[sym] for sym in user_symbols}
  # 额外获取全市场同层对标
  benchmark = top_5_in_same_layer(user_factors, candidates)
```

| 数据管道产出 | 复用方式 |
|-------------|----------|
| `factor_matrix` | 直接取持仓 ETF 的因子分，免自己算 |
| `candidates` | 同层对标：持仓半导体 vs 全市场卫星 ETF 排名 |
| `market_regime` | LLM prompt 注入市场背景 |
| `market_sentiment` | 同上 |

### 3.3 市场综合研判

**入口**：`POST /analysis/llm-report`（流式版 `POST /analysis/llm-report/stream`）

**当前**：

```python
1. _fetch_all_market()          ← 自采：指数+商品+实时行情        ~25s
2. get_history() × 5           ← 自采：拉 K 线算技术指标          ~30s
3. compute_all_indicators()    ← 自算：MA/MACD/RSI/KDJ/Bollinger
4. _collect_news()             ← 自采：资讯标题                  ~10s
5. LLM generate_market_report()
```

**复用方案**（优先级 P1）：

```
复用:
  ├─ news                   ← 当前自采，改为管道输出
  ├─ market_regime           ← 当前告缺，编排器免费有
  ├─ macro_regime            ← 当前告缺
  ├─ market_sentiment        ← 当前告缺
  ├─ sector_momentum         ← 当前告缺
  ├─ index_realtime          ← 当前自采，可复用
  ├─ us_indices              ← 当前自采(yfinance)，改为管道输出
  ├─ commodities             ← 当前自采，改为管道输出
  └─ factor_matrix           ← 可选替代部分 compute_all_indicators

额外所需:
  └─ 指定标的 K 线指标        ← 画图格式，factor_matrix 不兼容

↓

LLM prompt 增强：
  当前: "上证指数 +0.5%，深证成指 -0.3%，新闻标题..."
  增强: "当前市场状态: 震荡市(neutral)，情绪指数 62(偏乐观)
         宏观: 利率下行，外部风险中等
         行业动量 TOP 5: 半导体(+2.1%)、通信(+1.5%)..."
```

| 数据管道产出 | 复用方式 |
|-------------|----------|
| `market_regime` | 注入 LLM prompt，让研判有市态背景 |
| `macro_regime` | 同上 |
| `market_sentiment` | 同上 |
| `sector_momentum` | 同上 |
| `index_realtime` | 替代 `_fetch_all_market()` 的 A 股大盘部分 |
| `us_indices` | 替代 yfinance 自采的海外指数 |
| `commodities` | 替代 `get_commodities()` 自采的商品行情 |
| `factor_matrix` | 可选：替代 `compute_all_indicators()` 的部分指标 |
| `news` | 从管道直接取，免自采 |

**接入方式**：编排器产出作为唯一输入。llm-report 端点改为接收编排器的 `market_context` 参数，无编排器可用时直接返回失败（502）。

**应急路径处理**：不保留 fallback。`_fetch_all_market()` 和 `_collect_news()` 等自采+静默吞错的逻辑删除。llm-report 的可用性依赖于编排器的正常运行，与组合设计链路一致。

### 3.4 技术分析

**入口**：`indicators.py`（被 `compute_all_indicators()` 前端消费） + `signal.py`

**复用方案**（极高潜力，双向合并）：

| indicators.py 的函数 | FactorRegistry 有？ | 操作 |
|---------------------|---------------------|------|
| `compute_ma` | ✅ sma_5/10/20/60 | 删除 indicators 副本 |
| `compute_ema` | ❌ 仅 MACD 内部有 | 注册为 `technical.ma.ema_12` 等 |
| `compute_macd` | ✅ | 删除副本 |
| `compute_rsi` | ✅ rsi_14 | 删除副本 |
| `compute_kdj` | **❌ 独有** | 注册为新因子 |
| `compute_bollinger` | ✅ bandwidth | 删除副本 |
| `compute_all_indicators` | — | 保留为兼容包装层，委托给 FactorRegistry |

**signal.py** 中的 `generate_signal()` 注册为 composite factor，使综合买卖信号进入因子分矩阵，可被风控使用。

### 3.5 板块分析和个股分析

**入口**：`POST /analysis/sector-analysis`、`POST /analysis/symbol-analysis`

| 端点 | 当前自采内容 | 可复用编排器产出 |
|------|-------------|-----------------|
| `sector-analysis` | 板块成分股 → LLM | `industry_sectors` / `concept_sectors` 从管道直接取板块列表和行情，免自采；`sector_momentum` 作为 LLM prompt 补充。**成分股仍需自采**（管道不提供） |
| `symbol-analysis` | `get_history` + `compute_all_indicators` + 资讯 | `factor_matrix[code]` 含 24 维因子分 |

**symbol-analysis 的复用价值最高**：当前每次请求拉一次 `fetch_history`（5-10s）再算一遍指标。换成从 FactorRegistry 拿因子分，不仅省时间，还能附带"该 ETF 在全市场同层的因子排名"。

**注**：symbol-analysis 的复用前提是查询标的在 pool_manager 候选池中（~45 只 ETF）。用户查询的任一股、不在候选池中的 ETF、港美股标的无法命中 `factor_matrix`，应 fallback 到自采（`fetch_history` + `compute_all_indicators`）。

### 3.6 AI 投资顾问 + 资讯 AI 分析

**入口**：`POST /analysis/llm-advice`、`POST /analysis/llm-news-analysis`、`POST /analysis/news-impact`

**AI 投资顾问当前问题**：LLM 仅凭训练数据回答（可能截止于数月前），用户问"今天大盘怎么样"时无法给出准确回答，或直接回复"我无法获取实时数据"。

**方案**：端点上自动注入管道的 `market_context`，让 LLM 每次回答都有最新的行情、新闻、政策作为依据。零额外采集成本（管道已缓存）。

```python
# 重构后 llm-advice 端点
@router.post("/llm-advice")
async def llm_advice(query: str = Query(...), context: dict | None = None):
    # 自动从管道注入市场上下文（如有）
    ctx = context or {}
    mc = get_orchestrator_context()   # 管道缓存，TTL 120s，零成本
    if mc:
        ctx["market_snapshot"] = _build_advice_context(query, mc)
    advice = await generate_advice(query, ctx)
    return {"advice": advice, ...}
```

**智能注入策略**（根据 query 关键词决定注入哪些维度，避免每次塞 2000+ tokens）：

| 用户提问特征 | 注入的管道数据 | 预估额外 tokens |
|-------------|---------------|----------------|
| 含"大盘""今天""最新""走势" | `index_realtime` + `news` 前 5 条 | ~800 |
| 含"半导体""新能源""板块""行业" | `sector_momentum` + 相关行业 news | ~600 |
| 含"政策""利好""利空""监管" | `news` 前 10 条 + `market_sentiment` | ~1000 |
| 含"宏观""利率""GDP""经济" | `macro_regime` + `market_regime` | ~300 |
| 含"推荐""买""卖""持仓""仓位" | `market_regime` + `market_sentiment` + `news` 前 5 | ~900 |
| 以上都不匹配（通用问答） | `market_regime` + `market_sentiment`（最轻量） | ~200 |

**系统提示约束**（防止 LLM 反驳注入的数据）：

```
以下市场数据采集于 {datetime}，可能存在数分钟延迟，请以实际行情为准。
这些数据的优先级高于你的训练知识，如果与训练数据冲突，以此为据。
```

| 端点 | 复用潜力 | 说明 |
|------|---------|------|
| `llm-advice` | 高（P1） | 管道数据按 query 关键词智能注入，零额外采集成本，解决 LLM 数据滞后和幻觉 |
| `llm-news-analysis` | 高 | 新闻原文、`market_sentiment`、`sector_momentum` 均从管道获取，免自采 |
| `news-impact` | 低 | 输入是用户给的新闻+持仓，不需编排器数据 |

### 3.7 复用汇总

| 链路 | 复用数据管道？ | 复用策略引擎？ | 当前重复采集数 | 接入后节约 | 优先级 |
|------|---------------|---------------|--------------|-----------|--------|
| **组合设计** | ✅ 全部 | ✅ 核心 | 6 路自采 | 核心链路本身 | P0 |
| **策略检查** | ✅ factor_matrix + candidates | ❌ 不需要 | 3 路自采 → 1 路查表 | ~30s | P0 |
| **技术分析** | ✅ 注册为 Factor | ❌ 不需要 | 6 个冗余函数 | ~50 行代码 | P0 |
| **市场综合研判** | ✅ 全部（regime/sentiment/index/us/commodities/news） | ❌ 不需要 | 6 路自采 → 0 | ~55s | P1 |
| **板块分析** | ✅ industry_sectors + concept_sectors + sector_momentum | ❌ 不需要 | 部分自采（板块列表免了，成分股仍需） | ~10s + 保留成分股自采 | P2 |
| **个股分析** | ✅ factor_matrix | ❌ 不需要 | 每次省 fetch_history | ~5-10s/次 | P2 |
| **资讯 AI 分析** | ✅ news + regime/sentiment | ❌ 不需要 | 免自采新闻 | ~10s | P2 |
| **AI 投资顾问** | ✅ 智能注入 news/regime/sentiment/index | ❌ 不需要 | 解决 LLM 数据滞后和幻觉 | 零额外采集成本 | P1 |

---

## 四、删除清单

### 4.1 strategy_design.py 内部（~840 行可删）

| 代码 | 行号 | 删除原因 |
|------|------|----------|
| `CANDIDATE_POOL` | 74-114 | 被 pool_manager 全量动态池取代 |
| `_NEWS_KEYWORD_MAP`（引用） | 240 | 未定义变量，引用处所在的 `map_news_to_etfs()` 整体废弃，随函数一并删除 |
| `power_law_weights()` | 119-132 | 权重分配改用因子分归一化 |
| `generate_full_design()` | 137-197 | v3 编排器 |
| `map_news_to_etfs()` | 206-269 | 新闻影响以因子维度纳入 FactorRegistry |
| `dynamic_core_allocation()` | 274-327 | 改因子分驱动 |
| `dynamic_defense_allocation()` | 330-380 | 改因子分驱动 |
| `generate_enhanced_design()` 主体 | 676-1050 | 替换为新编排器 |
| 降级链路 pool_ready → scanner → hardcoded | 793-835 | 无降级 |
| 科技集中度 C2 + 单行业 40% | 925-977 | 改为因子暴露检测 |

### 4.2 冗余路由和辅助函数

| 路由 | 文件 | 删除原因 |
|------|------|----------|
| `POST /portfolio/design` | `portfolio.py` | 旧同步版，被 async 取代 |
| `POST /portfolio/design-enhanced` | `portfolio.py` | 功能合并到 async |
| `POST /analysis/portfolio-design` | `analysis.py` | 旧 LLM 路径 |
| `POST /analysis/portfolio-design/stream` | `analysis.py` | 同上 |
| `portfolioApi.design()`（前端） | `api/index.js` | 改为 designAsync |
| `analysisApi.portfolioDesign()`（前端） | `api/index.js` | 不再需要 |
| `analysis._fetch_all_market()` | `analysis.py:108` | llm-report 改为编排器唯一输入，不再自采行情 |
| `analysis._collect_news()` | `analysis.py:164` | 同上 |
| `analysis._MARKET_OVERVIEW_CACHE` | `analysis.py:146` | 不再需要 30s TTL 缓存，编排器统一缓存 |
| `analysis._get_cached_market_overview()` | `analysis.py:150` | 同上 |
| `analysis.get_cached_market_overview()` | `analysis.py:179` | 同上 |
| `analysis.PortfolioDesignRequest` | `analysis.py:265` | 仅被已删除的 `/portfolio-design` 路由使用 |
| `analysis.import generate_portfolio_design` | `analysis.py:14-17` | 仅被已删除的路由使用，删除路由后垃圾回收 |
| `llm.generate_portfolio_design()` | `analysis/llm.py:733` | 旧 LLM 设计路径，被引擎取代 |
| `llm._build_portfolio_design_prompt()` | `analysis/llm.py:534` | 同上 |
| `prompts/v1/portfolio_design.md` | `analysis/prompts/v1/` | 旧 LLM 设计提示词文件 |
| `analysisApi.portfolioDesignStream()`（前端） | `api/index.js` | `/portfolio-design/stream` 路由删除 |
| `market_trends.compute_etf_trends()` | `services/market_trends.py:25` | 所有消费者（设计/策略检查）改用管道後不再使用，确认无其他调用后删除 |
| `sentiment_fetcher.fetch_market_sentiment()`（自采调用） | `fetchers/sentiment_fetcher.py` | 各链路不再自采情绪，改为从管道的 `market_sentiment` 读取。保留原函数作为管道内部数据源 |

### 4.3 FactorRegistry + indicators 清理

| 代码 | 文件 | 操作 |
|------|------|------|
| 假数据 fallback（line 522-528） | `factor_registry.py` | 删除 |
| 6 个 scaffolding 函数 | `factor_registry.py` | 改为真实实现或标记 TODO |
| `compute_ma` / `compute_ema` / `compute_macd` / `compute_rsi` / `compute_bollinger` | `indicators.py` | 注册到 FactorRegistry 后删除副本 |
| `compute_kdj` | `indicators.py` | 注册为因子，保留包装层 |

### 4.4 测试文件

| 测试文件 | 影响 |
|----------|------|
| `tests/test_design_optimization_plan.py` | 预期输出全部变化，需重写 |
| `tests/test_enhanced_design.py` | 同上 |
| `tests/test_strategy_design.py` | 大部分失效 |
| `tests/test_pool_manager_phase*.py` | 维持 |
| `tests/test_factor_registry.py` | 维持 |
| `tests/test_agent_registry.py` | 维持（agent/LLM 路由本身不变，只是 prompt 内容更新） |
| `tests/test_portfolio_allocation.py` | 需确认是否依赖旧分配逻辑 |
| `tests/test_e2e.py` | 端到端测试需要在验证阶段整体重写 |

---

## 五、保留和移入 engine 包的代码

| 原代码 | 目标文件 | 说明 |
|--------|----------|------|
| `STRATEGY_META`（layer_budget/positioning） | `engine/budgets.py` | 纯配置元数据 |
| `dynamic_layer_budget()` | `engine/budgets.py` | 简化为纯函数 |
| `adjust_expected_return()` | `engine/budgets.py` | 纯函数 |
| `compute_portfolio_risk()` | `engine/risk_controls.py` | 改为用因子暴露矩阵计算 |
| `build_rationale()` | `engine/rationale.py` | 用 factor_scores 替代 trend_data |

---

## 六、FactorRegistry 修复和增强清单

| 因子 | 当前状态 | 修复方案 |
|------|----------|----------|
| `etf.premium_discount` | 返回 0 | 接入 akshare 获取 IOPV |
| `etf.tracking_error` | 返回 0 | ETF vs 基准指数 20 日标准差 |
| `etf.shares_change` | 返回 0 | 接入 akshare 历史份额 |
| `etf.industry_diversification` | 返回 0 | 用 ETFClassifier 的行业分布算 HHI |
| `etf.institutional_holdings_change` | 返回 0 | 接入 akshare 机构持仓 |
| `sentiment.stock_divergence` | 返回 0 | 标记 TODO |
| `technical.kdj.*` | **缺失** | 从 indicators.py 注册 |
| `technical.signal.overall` | **缺失** | 从 signal.py 注册 |
| 假数据 fallback（line 522-528） | 合成上涨 | 删除 |

---

## 七、实施顺序

### Phase 1：独立出纯策略引擎（无破坏性）

```
1. 创建 backend/app/engine/ 包
2. 移入 budgets.py（STRATEGY_META + dynamic_layer_budget + adjust_expected_return）
3. 创建 allocation_engine.py（纯函数 allocate）
4. 创建 rationale.py（基于 factor_scores）
5. 创建 risk_controls.py（基于因子暴露矩阵）
6. 编写 engine 的单测
```

### Phase 2：修复和增强 FactorRegistry

```
1. 删除假数据 fallback
2. 按优先级实现 3-4 个真实 scaffolding 函数
3. 从 indicators.py/signal.py 注册 KDJ、综合信号到 _BUILTIN_COMPUTERS
4. 验证 pool_manager.refresh() 产出合理的 factor_scores
5. 写熔断：FactorRegistry.compute 失败 >50% 符号时抛异常
```

> **Gate**：Phase 2 须通过 `tests/test_factor_registry.py` 全部用例 + `pool_manager.refresh()` 产出验证后，方可进入 Phase 3。

### Phase 3：重写编排器 + 删除旧代码（破坏性）

```
1. 重写 strategy_design.py 为薄编排器（~200 行）
2. 删除所有旧函数和降级链
3. 删除外部路由：/portfolio/design, /design-enhanced, /analysis/portfolio-design
4. 更新前端 API 引用
5. 更新测试
6. 跑 verify_e2e.py 确认核心链路通过
```

### Phase 4：其他链路接入

```
1. strategy_check() 接收编排器产出，删除自采逻辑
2. indicators.py 改为包装层，委托给 FactorRegistry
3. news 加入数据管道（pool_manager.refresh() 新增 news 产出字段）
4. llm-report 端点改为接收编排器的 market_context 作为唯一输入，删除 `_fetch_all_market()` 和 `_collect_news()` 自采逻辑
5. llm-advice 端点增加管道 context 智能注入逻辑（关键词分类 + 数据时效声明）
6. symbol-analysis 改用 factor_matrix 替代自采指标
7. 端到端验证所有链路的输出质量，重点检查：设计结果合理性、策略检查对标准确性、市场研判数据时效性、投顾 context 注入准确性
```

---

## 八、风险与备注

- **A 股日间无实时 K 线**：非交易时段 `fetch_history` 可能返回空 → 编排器抛异常而非返回空方案。此为预期行为。
- **冷启动延迟**：pool_manager 首次 `refresh()` 约 25-30s，后续调用由 120s 缓存覆盖。编排器本身无延迟。
- **因子分维度**：当前 24 个核心因子。注册 KDJ/综合信号后扩展至 27+。动量/资金流/估值通过 OHLCV 间接覆盖，可直接添加直算因子。
- **前向兼容**：组合设计的 `strategies` 数组字段结构不变（symbol/name/layer/weight/selection_rationale/factor_score），前端无需改动。策略检查、市场研判的 API 响应字段也不变。
- **indicators.py 包装层**：改为委托给 FactorRegistry 后，前端 K 线图无感知（函数签名和返回格式不变）。

---

## 九、最终架构对比

| 维度 | 当前 | 重构后 |
|------|------|--------|
| 候选池 | 20 只硬编码 ETF | 全市场扫描 ~45 只动态池 |
| 评分 | strategy_design 自算 z-score | FactorRegistry 24+ 因子标准化 |
| 核心层 | 按市态 hardcode 3-4 只 | 按因子分排名动态选取 |
| 防御层 | 按市态+宏观 hardcode | 按因子分排名动态选取 |
| 卫星层 | 双池匹配 + 自算评分 | 因子分排序 + 行业去重 |
| 降级链 | 3 层兜底 | 无降级 |
| 风控 | 行业名 hardcode | 因子暴露矩阵检测 |
| 策略引擎 | 嵌在数据采集里 | 独立纯函数包 engine/ |
| 外部路由 | 6 条（4 条冗余） | 2 条（/design-async + /apply-design） |
| 数据采集 | 6 条链路各自采 | 统一管道采 1 次，8 个消费者复用 |
| 海外指数 | 市场研判自采 yfinance | 管道 `us_indices`，数据源已封装降级链 |
| 商品行情 | 市场研判自采 | 管道 `commodities` |
| 板块数据 | 板块分析自采 | 管道 `industry_sectors` + `concept_sectors` |
| 技术分析 | 独立 indicators.py | 注册到 FactorRegistry |
| 策略检查 | 无全市场对标 | 获得全市场因子排名对比 |
| 市场研判 | 缺 regime/sentiment/macro | 注入 6 项编排器产出 |

---

## 附录：决策日志

### D1 — 全市场筛选替代硬编码池
- **时间**: 2026-07-20
- **决策**: 取消 CANDIDATE_POOL 硬编码 20 只 ETF，使用 etf_scanner.full_pipeline 全市场扫描 + pool_manager 动态池
- **原因**: 硬编码池覆盖率低（仅 20 只），缺乏行业多样性，且无法根据市态动态调整
- **影响**: 候选池从 20 只扩展到 ~45 只动态池；strategy_design.py 减少 ~40 行

### D2 — 无降级路径
- **时间**: 2026-07-20
- **决策**: 删除 pool_ready → scanner → hardcoded 三层降级链
- **原因**: 降级链产出的方案无因子分和趋势数据，入选理由大量空白，不如直接报错
- **替代方案**: 原降级链意图是保证"总有方案可用"，但质量不可接受
- **影响**: strategy_design.py 减少 ~40 行；非交易时段编排器可能抛出异常

### D3 — 策略引擎剥离为纯函数
- **时间**: 2026-07-20
- **决策**: 新建 engine/ 包，allocate() 为纯函数（无 I/O 无 fallback）
- **原因**: 现有策略引擎逻辑嵌在数据采集代码中，无法独立测试，单测需 mock 8 个外部调用
- **替代方案**: 在 strategy_design.py 内部局部抽象，但引入的调用链复杂度不降反升
- **影响**: 新增 ~5 个文件，engine/ 包可纯输入输出测试

### D4 — FactorRegistry 假数据 fallback 删除
- **时间**: 2026-07-20
- **决策**: 删除 _fetch_market_data 中失败时返回合成上涨序列的逻辑
- **原因**: 合成数据使下游无法辨别因子分是真实计算还是 placeholder，导致决策依据不可追溯
- **替代方案**: 在合成数据上加标记位（is_fake），但多了每个消费者都要判断标记的复杂度
- **影响**: factor_registry.py 减少 ~7 行，编排器在数据源不可用时抛出异常

### D5 — 市场研判改为编排器唯一输入
- **时间**: 2026-07-20
- **决策**: llm-report 端点删除 _fetch_all_market() 和 _collect_news() 自采逻辑，改为编排器 market_context 作为唯一输入
- **原因**: 编排器已有全部所需数据且已缓存；旧链路自采导致重复采集和多套数据来源不一致
- **替代方案**: "有则用无则降级自采"的双轨方案，但保留自采即保留冗余代码和静默吞错模式
- **影响**: analysis.py 减少 ~80 行，llm-report 可用性依赖于编排器正常运行

### D6 — 新闻纳入数据管道
- **时间**: 2026-07-20
- **决策**: pool_manager.refresh() 新增 news 产出字段，各链路从管道读取新闻
- **原因**: 6 条链路各自独立采集资讯，造成重复；集中采集后 cache TTL 可统一控制
- **影响**: 管道产出从 8 项增至 12 项；市场研判、板块分析、资讯分析免自采新闻

### D7 — llm-advice 智能注入
- **时间**: 2026-07-20
- **决策**: AI 投资顾问端点自动从管道注入 market_context，按 query 关键词决定注入维度
- **原因**: LLM 训练数据存在截止日期，无法回答实时行情问题；全量注入 token 成本过高
- **替代方案**: 无差别全量注入（~3000 tokens），但对简单问题性价比低
- **影响**: 零额外采集成本，平均每次 +800 tokens

### D8 — 板块分析仅增强不可替代
- **时间**: 2026-07-20
- **决策**: sector_momentum 仅作为 LLM prompt 补充上下文，板块成分股仍需自采
- **原因**: compute_sector_momentum 与 fetch_industry_sectors 数据源不同、字段不同；管道不提供成分股明细
- **影响**: 板块分析复用等级定为 P2

### D9 — 个股分析候选池局限性
- **时间**: 2026-07-20
- **决策**: symbol-analysis 复用 factor_matrix 的前提是标的在候选池内，池外标的 fallback 自采
- **原因**: 候选池仅覆盖 ~45 只 ETF，无法预知用户会查询哪只个股或港美股
- **影响**: 约 30% 查询可命中 factor_matrix 免自采，其余走原路径

### D10 — 市场综合研判改为 WS async
- **时间**: 2026-07-20
- **决策**: llm-report 新增 POST /async-task?type=report 入口，后端 report_worker 异步生成
- **原因**: 耗时 15-40s，SSE 要求用户保持页面打开；WS async 用户可自由浏览
- **替代方案**: 维持 SSE stream 但用户不能离开页面
- **影响**: 新增 report_worker.py，前端可复用现有 TaskManager 状态监听

### D11 — TaskManager 泛化
- **时间**: 2026-07-20
- **决策**: DesignTaskManager → TaskManager，task_type 泛化，WorkerRegistry 注册制
- **原因**: design_tasks.py 的 task 结构含 design 专属字段，无法支持 report 等新类型
- **影响**: 3 个文件 7 处 import 更新

### D12 — Phase 2→3 设 Gate
- **时间**: 2026-07-20
- **决策**: Phase 2（FactorRegistry 修复）必须通过测试 + pool_manager 产出验证后才进 Phase 3
- **原因**: Phase 3 的新编排器依赖 Phase 2 的 FactorRegistry 产出正常因子分
- **影响**: 阻止 Phase 3 在因子系统未就绪时启动

### D13 — 前端 loading 进度条抽取通用组件
- **时间**: 2026-07-20
- **决策**: DashboardAiTools.vue 的 loading UI + 策略检查 loading 区 → 通用 TaskProgress.vue
- **原因**: 两个异步任务页面有相同进度条模式（步骤列表 + 百分比 + 文字提示），代码重复
- **影响**: 减少 ~60 行重复代码

### D14 — 数据源优于旧链路裸调
- **时间**: 2026-07-20
- **决策**: 管道数据源采用已封装降级链的服务层（market_service.get_global_indices 等），而非直接 yfinance
- **原因**: 旧链路直接调 yfinance 无降级，市场服务已封装 stooq/akshare 等更稳定来源
- **影响**: 管道数据源稳定性高于旧链路
