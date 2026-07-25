# Scaffold Factor Resolution Plan

> 将 7 个当前硬编码返回 0.0 的脚手架因子接入真实数据源，使注册的 30 个因子全部生效。

## 背景

FactorRegistry 注册了 30 个因子（`_CORE_FACTORS`）。经静态代码分析（`test_core_factors_no_scaffold`），其中 7 个函数在所有代码路径下都只返回 0/0.0——没有接入任何数据源，被称为"脚手架因子"。

```python
# 典型脚手架模式：
def _compute_XXX(data: dict) -> float:
    """Description -- DATA SOURCE TBD."""
    return 0.0
```

7 个脚手架因子分为三类：

| 类别 | 因子 | 聚合影响 | 优先级 |
|------|------|---------|--------|
| **格式不匹配** | `etf.amount_stability` | 拖低 momentum 聚合 | P1 |
| **数据未传入** | `etf.tracking_error`、`etf.shares_change` | 拖低 momentum 聚合 | P1 |
| **数据源待接入** | `etf.institutional_holdings_change`、`etf.industry_diversification` | 拖低 momentum 聚合 | P2 |
| **市场广度** | `sentiment.panic_greed_diff`、`sentiment.stock_divergence` | 占 sentiment 位 | P2 |

当前 30 因子现状：23 个 LIVE，7 个 STUB。目标：30/30。

---

## 1. `etf.amount_stability` — 参数名不匹配

### 现状

```python
def _compute_amount_stability(data: dict) -> float:
    # data 中 amount 字段从未存在（Sina K-line 不提供成交额，只提供成交量）
    amounts = data.get("amount", [])
    if len(amounts) < 20:
        return 0.0
    mean = statistics.mean(amounts[-20:])
    return mean / max(amounts[-1], 0.01)
```

`_fetch_market_data` 的 `fetch_one()` 函数中，Sina K-line（`chddata` API）返回的 DataFrame 列名在清洗后映射为 `"volume"`（成交量，股数），不是 `"amount"`（成交额，元）。所以 `data.get("amount", [])` 永远返回空列表 `[]` → `len(amounts) < 20` → `return 0.0`。

关键是：**Sina 历史 K-line 根本不提供成交额字段**，只有成交量（股数）。过去用 `"amount"` 参数名可能是参照了其他数据源的字段名，但 Sina 源没有这个字段。

### 修复方案

**方案 A（推荐，~1 行）**：将参数名改为 `"volume"`

```python
volumes = data.get("volume", [])
```

同时修正逻辑从"成交额稳定度"为"成交量稳定度"。功能不变。

**方案 B（更准确）**：在 `_fetch_market_data` 中增加 `"amount"` 字段，从 gtimg 获取成交额（ETF 成交额 = `volume * price`）。

### 验收标准

- `test_core_factors_no_scaffold` 不再标记 `etf.amount_stability` 为 stub
- `etf.amount_stability` 在 `_aggregate_factor_scores` 中产生非零值

### 工作量

方案 A：~1 行，5 分钟。方案 B：~5 行，15 分钟。

---

## 2. `etf.tracking_error` — 无跟踪指数行情

### 现状

```python
def _compute_tracking_error(data: dict) -> float:
    # data 中 benchmark_close 从未存在
    benchmark = data.get("benchmark_close", [])
    etf_close = data.get("close", [])
    if len(benchmark) < 20 or len(etf_close) < 20:
        return 0.0
    return float(np.std([e - b for e, b in zip(etf_close[-20:], benchmark[-20:])]))
```

需要 ETF 跟踪指数的每日行情（`benchmark_close`），当前数据管道不提供。

### 修复方案

**核心思路**：在 `_fetch_market_data` 中增加跟踪指数 K 线拉取。

1. `etf_scanner.enrich_tracked_indices()` 已实现 F10 缓存 → `tracked_index` 字段已有数据
2. `_fetch_market_data` 中对于已知跟踪指数的 ETF，从 `symbol → tracked_index` 映射中获取指数名称
3. 使用 `fetch_history()` 拉取指数 K 线（指数代码映射表需预定义，如 `沪深300=000300`、`上证科创100=000685`、`黄金9999=AU9999`）
4. 将指数收盘价作为 `benchmark_close` 加入 data dict

⚠️ **指数代码映射风险**：不同指数对应不同的数据源代码格式。Sina 使用的指数代码格式与 ETF 不同（比如指数前缀 `s_sh000300` vs ETF 前缀 `sh510300`）。需要一个完整的指数代码映射表。

### 依赖

- `tracked_index` 字段必须已填充（`enrich_tracked_indices` 已实现但可能缓存为空）
- 需要指数代码 → Sina/网易可识别的格式对应表

### 验收标准

- 对于已知跟踪指数的 ETF（如 510300 → 沪深300），`benchmark_close` 不为空
- `tracking_error` 返回非零值（正常应 < 0.05）
- `test_core_factors_no_scaffold` 不再标记

### 工作量

~30 行（`_fetch_market_data` 扩展 + 指数代码映射），1-2 小时。

---

## 3. `etf.shares_change` — 份额变动数据未获取

### 现状

```python
def _compute_shares_change(data: dict) -> float:
    shares_change = data.get("shares_change_20d")
    if shares_change is not None:
        return float(shares_change)
    return 0.0
```

逻辑没有问题——参数定义对了。问题是 `data` 中 `shares_change_20d` 这个 key 从未被写入。

### 修复方案

**方案 A（推荐，~10 行）**：在 `_fetch_market_data` 中，通过 akshare `fund_etf_fund_info_em(code)` 获取 ETF 最新份额，与 20 天前份额比较。

⚠️ **风险**：该接口已被代理封禁（测试时对 589980/589950 等代码崩溃）。需要降级方案。

**方案 B（降级）**：从 gtimg 获取 ETF 份额数据（字段 45-46）。gtimg 的 ETF 实时行情在字段 `45` 处有份额数据。

```python
# gtimg field 45 = 份额（份）
shares_field = ...
shares_current = ...
# 无历史份额，假设不变 → 变化率 = 0
```

**方案 C（最简，推荐）**：用 `fund_scale`（Scanner 已有的数据）作为近似。忽略 20 日变化，直接返回 0（stub 状态不变但定义为"数据不可用"）。

### 工作量

方案 C：0 行（保持 stub）。方案 A：~15 行（含降级链）。方案 B：~5 行（gtimg 解析，需验证字段 45 是否为份额）。

---

## 4. `etf.institutional_holdings_change` — 标注"数据源 TBD"

### 现状

```python
def _compute_institutional_holdings_change(data: dict) -> float:
    """Institutional holdings change -- institutional data source TBD."""
    return 0.0
```

注释里写明了数据源待定。修复需要接入东方财富 F10 机构持仓页面。

### 修复方案

**方法**：使用与 `enrich_tracked_indices` 相同的 F10 解析模式，解析 `fundf10.eastmoney.com/{code}.html` 中的机构持仓信息。

1. 在 `_fetch_market_data` 末尾增加 F10 持仓解析
2. 解析页面中的"机构持有份额"或"机构持仓比例"

⚠️ **风险**：与 `fundf10.eastmoney.com` 同源的问题——如果页面结构变化或代理封禁，数据不可用。

### 工作量

~20 行（与现有 F10 enrichment 重用缓存 + 限速逻辑），1-2 小时。

---

## 5. `etf.industry_diversification` — 标注"数据源 TBD"

### 现状

```python
def _compute_industry_diversification(data: dict) -> float:
    """Industry diversification -- holdings data source TBD."""
    return 0.0
```

与 `institutional_holdings_change` 同类型。需要 ETF 持仓的行业分布数据。

### 修复方案

**方法**：利用 `ETFClassifier.batch_classify` 已有的行业分类结果。如果 ETF 被分类为 "宽基指数"，则行业分散度 ≈ 1.0（高度分散）；如果是 "主题指数" 或行业名只有一个，则分散度 ≈ 0.3。

```python
def _compute_industry_diversification(data: dict) -> float:
    concepts = data.get("concepts", [])
    industries = data.get("industry_list", [])
    if len(industries) >= 5:
        return min(len(industries) / 20, 1.0)
    if len(concepts) >= 3:
        return 0.5
    return 0.3
```

这需要 `_fetch_market_data` 从 pool_manager 传递 `concepts` 和 `industry_list` 给 factor registry。

### 依赖

- `ETFClassifier.batch_classify` 返回的 `concepts` 列表需可访问
- pool_manager 需在 factor 调用链中传递此数据

### 工作量

~10 行（`_compute_industry_diversification` 函数）+ ~5 行（pool_manager 传递 concepts 到 data dict），30 分钟。

---

## 6. `sentiment.panic_greed_diff` + `sentiment.stock_divergence` — 市场广度数据

### 现状

两个因子都需要市场行情广度数据（涨跌家数比）：

```python
def _compute_panic_greed_diff(data: dict) -> float:
    si = data.get("sentiment_index")
    if si is not None: return (si - 50) / 50  # 0~100 → -1~1
    return 0.0

def _compute_stock_divergence(data: dict) -> float:
    ratio = data.get("advance_decline_ratio")
    if ratio is not None: return math.log(ratio)
    return 0.0
```

`sentiment_index` 和 `advance_decline_ratio` 从未被写入 data。

### 修复方案

**方法**：使用 akshare `stock_zt_pool_em`（涨停板数据）或 `stock_market_fund_flow`（资金流向）作为市场情绪的代理指标。

```python
# 替代方案：使用新闻缓存中的数据计算 sentiment_index
# pool_manager.refresh_news() 后，_news_cache 中有 level 和 stars
# → 利好新闻占比越高，sentiment_index 越高
```

具体实现可以复用 pool_manager 第 3c 步的新闻桥接逻辑，但额外计算 `advance_decline_ratio` 的代理值。

### 工作量

- `panic_greed_diff`：~5 行（复用已有新闻桥接）
- `stock_divergence`：~10 行（akshare 调用，数据源稳定但有封禁风险）

---

## 实施顺序

| 优先级 | 因子 | 预期有效性 | 风险 | 工作量 |
|--------|------|-----------|------|--------|
| **P1** | `amount_stability` | 高（改正参数名即可） | 低 | 5 min |
| **P1** | `tracking_error` | 中（需要指数 K 线） | 中（指数代码映射） | 1-2 h |
| **P1** | `shares_change` | 低（数据难获取） | 高（接口被封） | 可跳过 |
| **P2** | `industry_diversification` | 高（classifier 已有数据） | 低 | 30 min |
| **P2** | `panic_greed_diff` | 中（新闻代理） | 低 | 5 min |
| **P2** | `stock_divergence` | 中（需新数据源） | 中 | 15 min |
| **P3** | `institutional_holdings_change` | 低（TBD） | 中 | 1-2 h |

**同步约束**：每个因子修复后必须从 `known_scaffolds` 集合中移除。如果修复不完整（函数仍有 `return 0.0` 作为唯一出口），`test_core_factors_no_scaffold` 会 FAIL。这保证了无数据源的因子不会重新混入系统。

**建议首轮实施**：P1 的 `amount_stability`（5 min）+ `tracking_error`（1-2 h，与 F10 tracked_index 缓存共用了大部分基础工作）

## 测试门禁

实施后 `test_core_factors_no_scaffold` 的 `known_scaffolds` 集合需要移除已修复的因子。如果修复不完整（函数仍有全部返回 0 的代码路径），测试会 FAIL。

```python
known_scaffolds = {
    "etf.institutional_holdings_change",  # P3 — 缓接
    "sentiment.panic_greed_diff",         # P2 — 需新闻桥接工作
    "sentiment.stock_divergence",         # P2 — 需新数据源
}
```

即 7 → 3（移除 4 个已修复的）。
