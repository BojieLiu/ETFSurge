# 智能组合设计链路优化方案

> 版本：v1.0
> 日期：2026-07-16

---

## 一、现状问题与优化目标

### 当前链路

```
用户请求 → 实时数据采集 (~10s) → LLM 生成全量方案 (~20s) → 返回
                                    ↑ 耗时长、约束不稳定、代码不准确
```

### 核心问题

| # | 问题 | 表现 |
|---|------|------|
| 1 | LLM 不擅长数学约束 | 权重超限、三层结构执行不一、忘记包含必需标的 |
| 2 | 候选池太小 | `CANDIDATE_POOL` 仅 17 只，远不足以覆盖全市场 |
| 3 | 数据维度不足 | 缺乏资金流拆分、估值全量、行业资讯、市场情绪 |
| 4 | 性能慢 | LLM 从零生成，前端超时设 180s 仍常失败 |
| 5 | 标的代码不可靠 | LLM 输出"代码待核实"或编造代码 |
| 6 | 卡片展示不直观 | 方案名称缺失、卡片偏小 |

### 优化目标

- 全市场覆盖（1000+ ETF → 45 只候选）
- 约束 100% 遵守（权重/数量/必需标的）
- 核心流程 3~5s，用户快感从"转圈等半分钟"变为"3秒看到方案"
- 融入资讯、财报、资金面、市场情绪多维度信号
- LLM 做它擅长的事：叙事判断 + 报告撰写

---

## 二、整体架构

### 核心原则：算法做骨架 + LLM 做调优

```
                          ┌──────────────────────┐
                          │ 全市场 ETF 数据采集    │ 一次调用 fund_etf_spot_em
                          │ ~1200 只             │ ~5s
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ 硬性过滤 + 三层分类   │ 纯本地，毫秒级
                          │ ~250 只合格 ETF      │
                          └──────────┬───────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          ▼                          ▼                          ▼
  ┌───────────────┐        ┌──────────────────┐       ┌───────────────┐
  │ 核心层 30~50只 │        │ 卫星层 150~200只 │       │ 防御层 30~50只 │
  │ 宽基关键词     │        │ 排除法           │       │ 防御关键词     │
  └───────┬───────┘        └────────┬─────────┘       └───────┬───────┘
          │                          │                         │
          ▼                          ▼                         ▼
  按流动性取 TOP15          轻量筛选取 TOP30           按流动性取 TOP15
  (强制含 510300/560600)      │                    (强制含 518880/511090)
                               │
                          ┌────┴────┐
                          │ 深度扫描 │  ← 新增：重仓股新闻 + 资金流拆解
                          └────┬────┘
                               │ TOP15
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
  核心层 15 只          卫星层 15 只           防御层 15 只
          └────────────────────┼────────────────────┘
                               │
                               ▼
                     ┌─────────────────────┐
                     │ LLM 一次调用精选     │  ← 只从 45 只选 8~15 只
                     │ + 分配权重           │    prompt 约 4K tokens
                     └──────────┬──────────┘    ~5s
                                │
                                ▼
                     ┌─────────────────────┐
                     │ 算法校验 + 约束修复   │  ← 截断权重/补必需标的
                     │                     │    Pydantic 校验
                     └──────────┬──────────┘
                                │
                     ┌──────────┴──────────┐
                     ▼                      ▼
              返回方案卡片               LLM 异步生成报告
              (3~5s 可见)               (通过 WS 推送, 不阻塞)
```

### 与现有路径的关系

| 现有路径 | 改造方式 |
|---------|---------|
| `POST /portfolio/design` (算法路径) | 保留，升级数据采集 + 全市场扫描 |
| `POST /analysis/portfolio-design` (LLM 路径) | 改为新架构入口，弃用纯 LLM 生成 |
| `llm.py: generate_portfolio_design()` | 改为只做报告润色 |

---

## 三、数据采集层（全局）

### 3.1 全量 ETF 基础数据

**一次调用，解决 80% 数据需求：**

```python
async def fetch_all_etfs_base() -> list[dict]:
    """全量 ETF 基础数据（含过滤和分类所需字段）"""
    import akshare as ak
    df = ak.fund_etf_spot_em()  # 单次，~5s
    # 返回字段：代码, 名称, 最新价, 涨跌幅, 成交额,
    #           成交量, 换手率, 市盈率, 市净率, 基金规模
    #           跟踪指数, 跟踪指数代码
```

### 3.2 硬性过滤条件

| 条件 | 作用 | 数据来源 |
|------|------|---------|
| 基金规模 > 1 亿元 | 剔除迷你 ETF | `fund_etf_spot_em` |
| 日均成交额 > 1000 万 | 保证可交易性 | `fund_etf_spot_em` |
| 场内 ETF | 排除 LOF/封闭式 | 代码前缀（5/6/0/3/1） |
| 成立满 1 年 | 排除次新 ETF | `fund_etf_fund_info_em`（可降级） |
| 排除纯债/货币 | 债券由用户独立管理 | 名称关键词 |

### 3.3 三层自动分类

**核心层（宽基指数 ETF）**—— 名称含以下关键词：
```
沪深300、中证500、中证A500、中证1000、上证50、
创业板、科创50、科创100、中证2000、深证100、
MSCI A50、上证180、上证380、中证800
```

**防御层（跨资产/避险 ETF）**—— 名称含以下关键词：
```
黄金、白银、原油、商品、国债、国开、进出口、
标普500、纳斯达克、纳指、恒生、H股、中概互联、
日经、德国30、法国CAC、全球、美元债、短融
```

**卫星层**—— **排除法**：核心层和防御层之外的**全部归入卫星层**。不依赖关键词匹配。

### 3.4 层内排序公式

#### 核心层 / 防御层
```
score = 0.50 × log(日均成交额_rank) + 0.50 × log(基金规模_rank)
```
纯看流动性和规模，确保选到市场最主流的宽基和避险资产。

强制插入（即使得分不在前 15）：
```
核心层: 510300(沪深300ETF), 560600(中证A500ETF)
防御层: 518880(黄金ETF), 511090(30年国债ETF)
```

#### 卫星层 —— 两轮筛选

**第一轮：轻量筛选（170→30，纯本地）**

```
score = 0.20 × 流动性_rank
      + 0.15 × 规模_rank
      + 0.15 × |涨跌幅|_rank          ← 弹性信号
      + 0.10 × 换手率_rank
      + 0.10 × 主力净流入_rank         ← 资金共识
      + 0.15 × 所属板块涨跌幅_rank      ← 行业热度
      + 0.15 × 关键词新闻匹配度         ← 资讯热度（标题关键词匹配）
```

**第二轮：深度扫描（30→15，新增 API 调用）**

对 TOP 30 只进行深度数据采集（并行，5s 超时兜底）：

```
① 重仓股新闻
   └─ fund_etf_holdings_em(symbol) → TOP 5 重仓股
   └─ fetch_stock_news(code) for each → 个股新闻聚合
   └─ 产出：每只 ETF 的 "资讯热度分" + "新闻摘要"

② 资金流拆解
   └─ fetch_fund_flow_detailed(symbol) → 四类分单
   └─ 产出：机构共识度 (机构+主力 vs 散户)

③ 估值数据
   └─ fetch_hist_avg_volume(symbol) → PE/PB/20日均额
   └─ 产出：估值分位

④ 行业板块关联
   └─ 从已缓存数据中取所属板块涨跌幅
```

第二轮评分更新（加入深度数据）：

```
score = 0.10 × 流动性_rank
      + 0.10 × 规模_rank
      + 0.10 × 涨跌幅_rank
      + 0.10 × 机构共识度_rank        ← 新增：机构买入散户卖出 → 高分
      + 0.10 × 主力净流入_rank
      + 0.10 × 板块涨跌幅_rank
      + 0.25 × 资讯热度_rank          ← 新增：基于重仓股新闻
      + 0.15 × 估值安全边际_rank      ← 新增：低估值分位 → 高分
```

---

## 四、资讯数据集成（新增）

### 4.1 数据源

| 数据源 | 覆盖范围 | 时效 | 接口 |
|--------|---------|------|------|
| 财联社快讯 | 全市场实时快讯，含财报/政策/异动 | 实时 | 已存在 |
| 东方财富个股新闻 | 个股+行业新闻 | 日频 | 已存在：`fetch_stock_news()` |
| 东方财富研报 | 机构研究报告 | 日频 | 已存在：`fetch_research_reports()` |
| ETF 重仓股 | 前 10 大持仓 | 季频 | 新增：`fund_etf_holdings_em` |

### 4.2 资讯热度提取引擎

```python
def extract_hot_keywords(headlines: list[dict]) -> list[tuple[str, float]]:
    """
    从每日头条中提取热点关键词，按重要性加权。
    输入: 财联社快讯 + 宏观新闻
    输出: [("半导体", 15), ("人工智能", 9), ("新能源", 6.5), ...]
    """
    keywords = {}
    for item in headlines:
        title = item.get("title", "")
        level = item.get("level", 1)   # 1~5
        star = item.get("stars", 1)    # 1~5
        weight = level * star * 0.5    # 加权系数
        
        # 提取行业/主题关键词
        for kw in SECTOR_KEYWORDS:     # 预定义行业关键词库
            if kw in title:
                keywords[kw] = keywords.get(kw, 0) + weight
                break                  # 一条新闻只匹配一个关键词
    
    return sorted(keywords.items(), key=lambda x: -x[1])[:10]
```

### 4.3 重仓股新闻聚合（深度扫描环节）

```python
async def calc_etf_news_heat(etf_symbol: str) -> dict:
    """计算某只 ETF 的资讯热度和方向"""
    # 1. 获取重仓股
    holdings = fetch_top_holdings(etf_symbol)   # fund_etf_holdings_em
    # 2. 并行获取重仓股新闻
    tasks = [fetch_stock_news(code) for code in holdings[:5]]
    all_news = await asyncio.gather(*tasks)
    # 3. 聚合
    positive = sum(1 for n in all_news if n.get("level", 0) >= 4)
    negative = sum(1 for n in all_news if n.get("level", 0) == 3)
    total = len(all_news)
    return {
        "heat_score": min(total / 10, 1.0),                    # 0~1
        "sentiment": (positive - negative) / max(total, 1),    # -1~1
        "headlines": [n["title"] for n in all_news[:3]],       # 摘要
    }
```

### 4.4 资讯在卫星层评分中的用法

```
卫星层 ETF 评分 (第二轮):
  score = ... + 0.25 × heat_score × (1 + sentiment × 0.3)
  
  解释: 资讯热度高的 ETF 获得基础加分
        如果资讯方向偏利好 (sentiment > 0)，额外加分
        如果资讯方向偏利空 (sentiment < 0)，折价
```

---

## 五、市场核心指标股追踪（新增）

### 5.1 为什么需要指标股

大盘指数（沪深300、上证指数）只能告诉你"市场涨了还是跌了"，但**为什么涨、谁在涨**，指数说不清楚。一批核心指标股的实时表现，比指数更能反映市场结构的真实状态：

| 指标股 | 映射含义 | 代码 | 关联 ETF |
|--------|---------|------|---------|
| 贵州茅台 | 消费复苏强度、外资风向 | 600519 | 消费ETF(159928) |
| 宁德时代 | 新能源产业链景气度 | 300750 | 新能源ETF(515030) |
| 招商银行 | 银行板块、利率预期 | 600036 | 银行ETF(512800) |
| 中信证券 | 券商、市场情绪活跃度 | 600030 | 证券ETF(512880) |
| 中芯国际 | 半导体、科技自主 | 688981 | 半导体ETF(512480) |
| 中国平安 | 保险、大盘价值 | 601318 | — |
| 迈瑞医疗 | 医药创新、医疗器械 | 300760 | 医药ETF(512010) |
| 中国中免 | 消费升级、免税政策 | 601888 | — |
| 海光信息 | 国产算力、AI信创 | 688041 | AI人工智能ETF(561300) |
| 美的集团 | 制造业龙头、家电 | 000333 | — |
| 万华化学 | 化工周期、原材料 | 600309 | — |
| 比亚迪 | 新能源车、整车制造 | 002594 | 新能源车ETF(515700) |

LLM 看到这些**指标股今日的涨跌幅 + 相关新闻**后，可以做出远比"沪深300涨了1.2%"更丰富的市场判断。

### 5.2 指标股选取逻辑

指标股不是固定的死名单，而是**按当前市场结构动态调整**的：

```python
# 固定底仓（10 只，覆盖主要行业板块）
CORE_BENCHMARK_STOCKS = {
    "600519": {"name": "贵州茅台", "sector": "消费"},
    "600036": {"name": "招商银行", "sector": "金融"},
    "300750": {"name": "宁德时代", "sector": "新能源"},
    "600030": {"name": "中信证券", "sector": "券商"},
    "601318": {"name": "中国平安", "sector": "保险"},
    "300760": {"name": "迈瑞医疗", "sector": "医药"},
    "600309": {"name": "万华化学", "sector": "化工"},
    "000333": {"name": "美的集团", "sector": "家电"},
    "002594": {"name": "比亚迪", "sector": "新能源车"},
    "688981": {"name": "中芯国际", "sector": "半导体"},
}

# 动态增补（3~5 只，基于今日卫星层 TOP 5 ETF 的重仓股排名前列者）
# 如果今日卫星层排名第一的是 AI人工智能ETF，
# 就把它的第一大重仓股（如海光信息/科大讯飞）加入指标股列表
DYNAMIC_STOCKS = _top_holdings_of(_top_satellite_etfs(5))
```

这样**底仓永远有 10 只核心指标股**，同时每天的指标股能反映当天最热的赛道。

### 5.3 指标股数据采集

```python
async def fetch_benchmark_stocks() -> list[dict]:
    """采集市场核心指标股的价格、涨跌幅、资金流、新闻"""
    stocks = CORE_BENCHMARK_STOCKS + DYNAMIC_STOCKS   # 共 13~15 只
    
    # 并行采集三类数据
    prices, flows, news_list = await asyncio.gather(
        _fetch_stocks_realtime([s.code for s in stocks]),  # 行情
        _fetch_stocks_fund_flow([s.code for s in stocks]),  # 资金流
        _fetch_stocks_news([s.code for s in stocks]),       # 新闻
        return_exceptions=True,
    )
    
    result = []
    for stock in stocks:
        price = prices.get(stock.code, {})
        flow = flows.get(stock.code, {})
        news = news_list.get(stock.code, [])
        
        # 合成关键判断
        retail_sentiment = (flow.get("medium", 0) + flow.get("small", 0)) / max(abs(flow.get("super_large", 0)), 1)
        inst_sentiment = flow.get("super_large", 0) + flow.get("large", 0)
        
        result.append({
            "symbol": stock.code,
            "name": stock.name,
            "sector": stock.sector,
            "price": price.get("price"),
            "change_pct": price.get("change_pct"),
            "institutional_net_inflow": inst_sentiment,
            "retail_net_inflow": retail_sentiment,
            "top_news": [n["title"] for n in news[:2]],
            "signal": _judge_signal(inst_sentiment, retail_sentiment, price.get("change_pct", 0)),
        })
    
    return result
```

### 5.4 指标股出现在哪里

#### 给 LLM 的上下文

```
【市场核心指标股】
消费(茅台)    涨跌幅:+0.8%  机构+0.5亿 散户-0.2亿 → 机构增配消费
金融(招行)    涨跌幅:-0.3%  机构-1.2亿 散户+0.8亿 → 机构出货，警惕
新能源(宁德)  涨跌幅:+2.5%  机构+3.2亿 散户-0.5亿 → 机构看好，今日热点
                ├─ 新闻: 宁德时代Q2财报超预期，营收同比+45%
                └─ 信号: ✅ 机构积极布局
科技(中芯)    涨跌幅:+1.8%  机构+0.8亿 散户+0.1亿 → 温和看多
                ├─ 新闻: 中芯国际14nm良率突破
                └─ 信号: ✅ 温和上涨
```

#### 市场情绪指数中的贡献

```python
market_sentiment = (
    0.20 × 涨跌家数比
    + 0.20 × 机构共识度           ← 指标股的机构净买入/卖出方向
    + 0.15 × 指标股涨跌比          ← 新增：13~15 只指标股中上涨比例
    + 0.15 × 北向资金
    + 0.15 × 两融
    + 0.15 × 指标股新闻情绪        ← 新增：基于指标股新闻的利好/利空比例
)
```

### 5.5 指标股 vs ETF 重仓股新闻的区别

| | ETF 重仓股新闻（第 4.3 节） | 市场指标股追踪（本节） |
|--|--------------------------|---------------------|
| 用途 | 为特定 ETF 打分（这只 ETF 有没有新闻热度） | 判断整体市场环境（今天市场在炒什么） |
| 范围 | 只限 30 只卫星候选的重仓股 | 固定 10 只核心指标股 + 动态 3~5 只 |
| 产出 | 各 ETF 的 `news_heat_score` | 市场环境快照（给 LLM 做宏观判断） |
| 调用时机 | 卫星层第二轮评分时 | 与数据采集并行，全局仅一次 |

---

## 六、市场情绪与资金行为分析（新增）

### 7.1 四类资金流拆解

改造 `fetch_fund_flow()` 为 `fetch_fund_flow_detailed()`：

```python
def fetch_fund_flow_detailed(symbol: str) -> dict | None:
    """返回四类分单数据"""
    df = ak.stock_individual_fund_flow(stock=symbol, market=market)
    # 提取四个维度
    return {
        "super_large": {"inflow": ..., "direction": "净流入/净流出"},
        "large": {"inflow": ..., "direction": ...},
        "medium": {"inflow": ..., "direction": ...},
        "small": {"inflow": ..., "direction": ...},
        # 派生指标
        "institutional_consensus": ...,     # 机构+主力 vs 散户分歧度
    }
```

**机构共识度公式：**
```
institutional_consensus = 
    (super_large_inflow + large_inflow - medium_inflow - small_inflow)
    / abs(super_large_inflow) + abs(large_inflow) + ...
    
取值范围: -1 ~ 1
> 0.3: 机构看好，散户卖出 → 看多信号
< -0.3: 机构出货，散户接盘 → 警惕信号
```

### 7.2 市场情绪指数

```python
async def fetch_market_sentiment() -> dict:
    """综合市场情绪指数"""
    tasks = [
        _fetch_advance_decline_ratio(),      # 涨跌家数比
        _fetch_market_fund_flow_summary(),   # 整体四类资金
        fetch_north_money(today, today),     # 北向资金 (已有)
        _fetch_margin_balance_change(),      # 两融变化
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    sentiment = (
        0.30 × normalize(advance_ratio)
        + 0.30 × normalize(institutional_consensus)
        + 0.20 × normalize(north_flow)
        + 0.20 × normalize(margin_change)
    )
    
    return {
        "sentiment_index": round(sentiment * 100),
        "sentiment_label": _label(sentiment),  # 亢奋/乐观/中性/谨慎/恐慌
        "institutional_direction": "净买入" if inst > 0 else "净卖出",
        "retail_direction": "净买入" if retail > 0 else "净卖出",
        "is_divergence": inst > 0 and retail < 0,  # 是否分歧
        "north_net_inflow": north_value,
        "details": {...}
    }
```

### 5.3 国家队行为的间接推断（可选）

不单独设"国家队信号"，整合到机构行为中：

```
机构行为综合信号 =
    0.50 × 超大单净流入      (直接反应机构/国家队交易)
    0.30 × 北向资金净流入    (外资+假外资通道)
    0.20 × 头部宽基ETF份额变动 (国家队入市通道)
```

---

## 七、LLM 的角色

### 7.1 LLM 做什么

**只做两件事：**
1. **从 45 只候选池中精选 8~15 只 + 分配权重**（一次调用，~5K tokens）
2. **异步生成设计报告**（不阻塞主流程）

### 7.2 LLM 看到的上下文

```
输入上下文结构:
{
  "market_environment": {
    "indices": [...],           // 大盘指数表现
    "sentiment": {...},         // 市场情绪指数
    "sector_heat": [...],       // 行业板块 TOP 10
  },
  "news_summary": [...],        // 今日精选资讯
  "candidates": {
    "core": [{                  // 15 只
      symbol, name, price, change_pct,
      pe_ttm, pb, main_net_inflow,
      "reason": "A股核心宽基"
    }],
    "satellite": [{             // 15 只
      symbol, name, price, change_pct,
      main_net_inflow, pe_ttm, pb,
      news_heat_score,           // 0~1
      news_sentiment,            // -1~1
      news_headlines: [...],     // 相关新闻摘要
      institutional_consensus,   // -1~1
      "reason": "今日资讯热点：中芯国际财报超预期+半导体板块领涨"
    }],
    "defense": [{               // 15 只
      ...
    }]
  },
  "constraints": {
    "三层结构": "必须含 core/satellite/defense",
    "核心层强制": "510300(沪深300ETF), 560600(中证A500ETF)",
    "权重范围": "1%~30%",
    "总标的": "8~15 只",
    "层预算": "防御(c55/s25/d20) 平衡(c55/s30/d15) 进攻(c50/s40/d10)",
  }
}
```

### 7.3 LLM 的输出

```json
{
  "plans": [{
    "style": "防御型",
    "allocations": [
      {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
       "target_weight": 0.18, "selection_rationale": "核心底仓"},
      {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
       "target_weight": 0.08, "selection_rationale": "今日中芯国际财报超预期"}
    ]
  }]
}
```

**LLM 不输出**：ETF 代码、价格、涨跌幅、估值等数据字段。这些由算法填充，保证准确性。

### 7.4 约束校验层（LLM 输出后）

```python
def validate_and_fix(plans: list[dict]) -> list[dict]:
    for plan in plans:
        # 1. 校验标的数量 8~15
        enforce_name_count(plan, 8, 15)
        
        # 2. 校验核心层含 510300/560600
        ensure_core_required(plan, ["510300", "560600"])
        
        # 3. 校验权重 1%~30%
        clip_weights(plan, 0.01, 0.30)
        
        # 4. 校验三层结构（每层至少 1 只）
        ensure_three_layers(plan)
        
        # 5. 权重归一化到 100%
        normalize_weights(plan)
        
        # 6. 校验代码有效性（必须存在于全量 ETF 列表中）
        validate_symbols(plan, ALL_ETF_SYMBOLS)
    return plans
```

---

## 八、性能预算

### 8.1 核心流程耗时

| 步骤 | 耗时 | 说明 |
|------|------|------|
| 全量 ETF 基础数据 | ~5s | `fund_etf_spot_em` 一次调用 |
| 过滤+分类+第一轮排序 | <50ms | 纯本地 |
| 深度扫描 (30 只) | ~5s | 并行拉取，5s 超时兜底 |
| LLM 精选 | ~3~5s | ~5K tokens，DeepSeek V4 |
| 算法校验+约束修复 | <50ms | Pydantic |
| **核心流程合计** | **~13~15s** | |
| LLM 异步报告 | ~5~10s | 不阻塞，通过 WS 推送 |

### 8.2 缓存策略

| 数据 | TTL | 说明 |
|------|-----|------|
| 全量 ETF 基础数据 | 60s | 盘中基本稳定，不用重复拉取 |
| 行业板块表现 | 60s | 已缓存 |
| 资金流数据 | 120s | 日频数据 |
| 北向资金 | 300s | 日频 |
| ETF 重仓股 | 3600s | 季频，一天拉一次足够 |
| 资讯/新闻 | 120s | 已缓存 |

### 8.3 降级策略

| 失败场景 | 降级行为 |
|---------|---------|
| `fund_etf_spot_em` 超时 | 使用缓存的历史数据，或直接走现有 `CANDIDATE_POOL` |
| 深度扫描超时 | 跳过第二轮，直接用第一轮 TOP 15 |
| 重仓股接口超时 | 资讯热度用纯关键词匹配（不加重仓股环节） |
| 资金流拆解超时 | 沿用现有 `main_net_inflow`（不拆四类） |
| LLM 调用失败 | 使用 `strategy_design.py` 纯算法方案（已有 fallback） |

---

## 九、前端卡片展示优化

### 9.1 卡片布局

```
┌─────────────────────────────────────────────┐
│  🛡️ 防御型  │  防御稳健组合                 │  ← 方案名称 + 颜色徽标
│──────────────┴──────────────────────────────│
│  ┌─────────────────────────────────────┐    │
│  │ ████████████████████░░░░░░░░░░░░░░ │    │  ← 三层色块分配条
│  │ 核心 55%  卫星 25%  防御 20%        │    │
│  └─────────────────────────────────────┘    │
│                                              │
│  核心  沪深300ETF              18%          │  ← 各层标的预览
│  核心  中证A500ETF             15%          │
│  卫星  半导体ETF               12%          │
│  防御  黄金ETF                  8%          │
│  + 更多 6 只 ...                            │
│                                              │
│  📊 预期年化 8%  ·  最大回撤 -12%  ·  Sharpe 1.2 │  ← 关键指标
│  🔥 情绪: 中性  ·  机构: 净买入             │  ← 市场环境微标签
│                                              │
│  ┌──────────────────────────────────┐       │
│  │         应用此方案               │       │  ← 按钮调大
│  └──────────────────────────────────┘       │
└─────────────────────────────────────────────┘
```

### 9.2 改动要点

| 改动 | 说明 |
|------|------|
| 卡片网格从 `minmax(340px, 1fr)` 改为 `minmax(400px, 1fr)` | 调大卡片 |
| 卡片头部加方案名+图标 | `🛡️防御型` / `⚖️平衡型` / `⚔️进攻型` |
| 三层色块分配条 | core=#1976D2, satellite=#FF9800, defense=#43A047 |
| 标的预览列表 | 直接显示，不需展开 |
| 简化展开内容 | 展开后只显示完整持仓明细表 |
| 情绪/资金微标签 | 新增在市场环境栏 |

---

## 十、实施路径

### 第一阶段：数据采集层改造（P0）

| 任务 | 涉及文件 | 预估工时 |
|------|---------|---------|
| 实现全量 ETF 扫描 + 硬性过滤 | 新增 `fetchers/etf_scanner.py` | 3h |
| 实现三层自动分类 | 新增 `services/etf_classifier.py` | 2h |
| 改造 `fetch_fund_flow()` → 四类拆解 | `fetchers/fundamental_fetcher.py` | 1h |
| 实现两轮卫星层评分 | `services/strategy_design.py` | 2h |
| 实现重仓股新闻聚合 | `fetchers/news_fetcher.py` | 2h |

### 第二阶段：市场情绪模块（P1）

| 任务 | 涉及文件 | 预估工时 |
|------|---------|---------|
| 涨跌家数比 + 北向资金 + 两融 | 新增 `fetchers/sentiment_fetcher.py` | 2h |
| 实现情绪指数合成 | `fetchers/sentiment_fetcher.py` | 1h |
| 集成到 `enrich_market_context()` | `services/strategy_design.py` | 1h |

### 第三阶段：LLM 交互改造（P1）

| 任务 | 涉及文件 | 预估工时 |
|------|---------|---------|
| 重写 LLM prompt（从 45 只选） | `prompts/v1/portfolio_design.md` | 2h |
| 实现约束校验层 | 新增 `services/design_validator.py` | 2h |
| LLM 报告异步 + WS 推送 | `routers/analysis.py` + `routers/ws.py` | 3h |

### 第四阶段：前端改造（P1）

| 任务 | 涉及文件 | 预估工时 |
|------|---------|---------|
| 卡片调大 + 方案名称+图标 | `DashboardAiTools.vue` | 2h |
| 三层色块分配条 | `DashboardAiTools.vue` | 1h |
| 情绪/资金微标签 | `DashboardAiTools.vue` | 1h |

### 第五阶段：验收与测试（P2）

| 任务 | 预估工时 |
|------|---------|
| 全链路功能测试（约束/数据/性能） | 3h |
| 前端联调 | 2h |
| 边界情况覆盖（超时降级、空数据） | 2h |

---

## 十一、风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| `fund_etf_spot_em` 接口不稳定 | 全市场扫描失败 | 降级到现有 `CANDIDATE_POOL` 17 只 |
| `fund_etf_holdings_em` 限流 | 重仓股扫不出来 | 跳过深度新闻环节，用关键词匹配 |
| 四类资金流 API 代理问题 | 资金流拆解失败 | 沿用现有的 `main_net_inflow` |
| LLM 输出多次不符合约束 | 校验层反复修复 | LLM 输出不改了，全部由算法修复，LLM 只用于"选谁"不用于"定权重" |
| 一次 LLM 调用超时 | 方案出不来 | 降级到纯算法方案（已有 fallback） |

---

## 十二、核心设计决策记录

| 决策 | 选项 | 选择 | 理由 |
|------|------|------|------|
| 全市场扫描方式 | 逐只调用 vs 批量接口 | `fund_etf_spot_em` 一次调用 | 1000 只逐只调用不现实 |
| 三层分类方式 | LLM 分类 vs 规则 | 规则（关键词+排除法） | 分类是确定性问题，LLM 不可靠且慢 |
| 卫星层筛选方式 | 一轮到位 vs 两轮递进 | 两轮递进 | 170→30 轻量 → 30→15 深度，避免给全部 170 只拉数据 |
| LLM 输出权重 vs 算法定权重 | LLM 全权 vs 算法修正 | 算法修正兜底 | LLM 的 1%~30% 约束不稳定 |
| 报告同步 vs 异步 | 同步 vs 异步 | 异步（WS 推送） | 不阻塞卡片展示，提升用户体验 |
| 国家队独立信号 vs 整合 | 独立 vs 整合 | 整合到机构行为 | 没有直接 API，间接推断不准确 |
