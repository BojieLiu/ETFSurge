# 市场感知联动 + 数据源替换 · 综合实施方案

> 文档版本: **v4** — 2026-07-26 审计更新
> ⚠️ **2026-07-26 审计发现**：以下 §4（数据源替换）已通过 Phase 4.1 独立实施，`roadmap-data-source-unified.md` 为替代文档，§4 内容作为历史参考保留。
> ⚠️ **§5（市场感知联动）大部分未实施**。`core/market_context.py` 和 `services/market_router.py` 从未创建。`market-analysis-optimization-plan.md` Phase D/E 部分覆盖了 AiAdvisor 流式改造和 MarketReport market 字段，但 **非全部**：LLM prompt 未注入市场上下文，`_build_report_prompt()` 无 Section 0/5 增强，regime 缓存仍为单市场，前端未传递 market 参数。详见 §5 底部状态矩阵。
> ⚠️ **§7（实施阶段）已过时**，应参考 `implementation-master-plan.md` Phase 2.9（LLM 上下文管道统一）+ Phase 5.1（市场感知联动评估）以获取最新实施路线。
> 
> 对应议题: (1) 功能与市场选择脱节 (2) yfinance 连通性问题
> 评审历史: v1 自审发现 9 项 → 委派 reviewer 发现 8 项 → v2 修复 17 项 → v3 增加 akshare 降级内容 + 自审通过 → v4 审计状态更新

---

## 目录

1. [问题概述](#1-问题概述)
2. [当前状态分析](#2-当前状态分析)
3. [目标架构](#3-目标架构)
4. [数据源替换方案](#4-数据源替换方案)
5. [市场感知联动方案](#5-市场感知联动方案)
6. [API 契约变更](#6-api-契约变更)
7. [实施阶段](#7-实施阶段)
8. [功能-市场兼容矩阵](#8-功能-市场兼容矩阵)
9. [风险与缓解](#9-风险与缓解)
10. [文件改动清单](#10-文件改动清单)
11. [验收标准](#11-验收标准)

---

## 1. 问题概述

### 1.1 两个独立问题

**问题 A — 功能与市场选择脱节**：前端有完整的市场 Tab 体系（A股/港股/美股/全球），但核心分析功能（行情研判、AI 顾问、组合设计等）忽略了用户选中的市场，始终按 A 股逻辑运行。

**问题 B — yfinance 连通性问题**：美股数据源目前以 yfinance 为主力，无代理时境内难以稳定连接，亟需替换为其他境内可直连的免费数据源。

### 1.2 关联性

两个问题天然耦合：要实现"切换到美股 Tab 做行情研判"，必须先解决"美股数据从哪里来"。因此合并为一个方案。

---

## 2. 当前状态分析

### 2.1 市场 Tab → 子组件的联动现状

```
marketTab ('A'|'HK'|'US'|'global')
  │
  ├─ WatchlistPanel   ✅ 按 asset_type 过滤展示
  ├─ IndexAnalysis    ✅ 按 market 字段过滤下拉列表
  ├─ SectorAnalysis   ✅ 请求板块列表时传 &market=
  ├─ SymbolAnalysis   ✅ 传 asset_type 给后端
  │
  ├─ MarketReport     ❌ 接收 prop 但从不使用；请求 payload 无 market 字段
  ├─ AiAdvisor        ❌ 接收 prop 但从不使用；context 写死 market: 'A'
  ├─ DashboardAiTools (组合设计)  ❌ 设计请求无 market 参数
  └─ SectorAnalysis (LLM分析)    ❌ SSE 端点无 market 参数
```

### 2.2 后端各端点的市场感知现状

| 端点 | 采集的数据范围 | 是否有市场过滤 | LLM 是否感知市场 |
|------|--------------|--------------|----------------|
| `/llm-report/stream` | `get_all_realtime()` 全量 A 股 | 硬编码 A 股指数(`000001`等) | ❌ |
| `/llm-advice/stream` | 流式版 **无数据注入**（非流式版有关键词检测） | 无 | ❌ |
| `/llm-advice` (非流式) | pool_manager（A 股） | 关键词识别（A股专属词） | ❌ |
| `/sector-analysis/stream` | `fetch_industry_sectors`（A股） | 无 | ❌ |
| `/symbol-analysis/stream` | 由 asset_type 决定数据源 | 仅 asset_type 参数 | ❌（LLM prompt 不含市场上下文） |
| `/portfolio/design-async` | pool_manager 候选池（仅 A 股 ETF） | 无 | N/A（引擎驱动） |
| `/market/realtime/{symbol}` | 由 asset_type 路由 | asset_type | — |
| `/market/history/{symbol}` | 由 asset_type 路由 | asset_type | — |

### 2.3 美股数据源现状

| 数据源 | 现有封装 | 功能 | 境内稳定性 | 免费额度 | API Key |
|--------|---------|------|-----------|---------|---------|
| **yfinance** | `yfinance_fetcher.py` | 实时+历史+指数 | ⚠️ 无代理不稳定 | 无限制 | 不需要 |
| **Stooq** | `stooq_fetcher.py` (181行) | 实时+批量+历史+全球指数 | ✅ 稳定 | 无限制 | **不需要** |
| **Twelve Data** | `twelvedata_fetcher.py` (116行) | 实时+历史日线 | ✅ 稳定 | 800次/天 | ✅ 已配置 |
| **Finnhub** | `finnhub_fetcher.py` (117行) | 实时+历史K线+新闻 | ✅ 稳定 | 60次/分 | ✅ 已配置 |
| **Alpha Vantage** | `alphavantage_fetcher.py` (111行) | 实时+历史日线 | ✅ | ⚠️ **仅25次/天** | ✅ 已配置 |

> 关键发现：`market_service.py` 中的 `_route_us()` 当前链路为 `TwelveData → Finnhub → AlphaVantage → yfinance`，**未包含 Stooq**。Stooq 仅在全球指数链路中作为新浪之后的第 2 优先源。

### 2.4 港股数据源现状

| 数据源 | 现有封装 | 功能 | 境内稳定性 |
|--------|---------|------|-----------|
| **China Market (新浪→QQ→EM)** | `china_market.py` `fetch_hk_stock_realtime()` | 实时行情 | ✅ 三级降级链 |
| 港股历史 | `china_market.py` 内 akshare 港股 K 线 | 历史数据 | ✅ |

### 2.5 新闻数据源现状（重要限制）

| 新闻源类型 | 来源 | 语言 | 覆盖市场 |
|-----------|------|------|---------|
| 财联社快讯 | `levistock` | 中文 | A 股 |
| 宏观新闻 | `news_fetcher` (CCTV/百度) | 中文 | 宏观 |
| 国际新闻 | `news_fetcher` (MarketWatch/CNBC RSS) | 英文 | 全球（通用） |
| 东方财富公告 | `news_fetcher` | 中文 | A 股 |

**结论：当前无专有港股新闻源（如港交所披露、香港经济日报），也无专有美股新闻 API（如 Benzinga、Seeking Alpha）。所有 LLM 分析端点的新闻输入对于 HK/US 市场是不充分的。**

### 2.6 市态检测依赖链

```
detect_market_regime()
  └─ compute_etf_trends(symbols)          # 需传入对应市场指数代码
       └─ _fetch_single_trend(symbol)
            └─ fetch_history(symbol, asset_type="A", ...)  # ⚠️ asset_type 硬编码 "A"
```

整条链都假设 A 股数据。港股/美股需要走完全不同的数据路径。

### 2.7 akshare 依赖分析（覆盖全库）

akshare 在代码库 5 个模块中共约 15 处使用。按其在降级链中的位置可分为三类：

#### 第一类：已是降级链末梢（无需改动，8 处）

| 位置 | akshare 调用 | 当前优先级 | 非 akshare 主源 |
|------|-------------|-----------|----------------|
| `china_market.py` A 股历史日线 | `stock_zh_a_hist()` | mootdx→Sina→**akshare** | mootdx + Sina |
| `china_market.py` A 股分钟线 | `stock_zh_a_hist_min_em()` | Sina→**akshare** | Sina 分时 |
| `china_market.py` 港股实时 | `stock_hk_spot_em()` | Sina→QQ→**akshare** | Sina + QQ |
| `etf_scanner.py` ETF 扫描 | `fund_etf_spot_em()` | Sina列表→腾讯gtimg→**akshare** | Sina + GTIMG |
| `sector_fetcher.py` 板块/概念 | 多处 `ak.stock_board_*` | levistock→**akshare** | levistock |
| `sector_fetcher.py` 全量股票 | `stock_info_a_code_name()` | levistock→**akshare** | levistock |
| `news_fetcher.py` 新闻 | 多处 `news_*` | 补充源 | levistock 财联社 + RSS |

> 这 8 处 akshare 已处于降级链底端，akshare 不稳定不影响核心功能，仅丢失辅助数据（如基金规模、PE）。

#### 第二类：akshare 是唯一数据源（需要补降级，4 处）

| 位置 | akshare 调用 | 风险 | 可替代源 |
|------|-------------|------|---------|
| `china_market.py` 期货/商品 | `futures_foreign_commodity_realtime()` | 商品行情不可用 | **Stooq** GLD/USO/SLV |
| `china_market.py` 指数历史日线 | `stock_zh_index_daily()` | 指数图表不可用 | mootdx / 新浪指数日线 |
| `china_market.py` 港股/US 历史 | `stock_hk_hist()` / `stock_us_hist()` | HK/US 历史图表不可用 | **Stooq** 历史K线 |
| `market_trends.py` 板块动量 | `stock_board_industry_name_em()` | 市态判断降级 | **sector_fetcher** (levistock) |

> 这 4 处需要在各自模块中增加非 akshare 的降级链路，具体方案见 [4.6 节](#46-akshare-统一降级策略)。

#### 第三类：关键缺口 — ETF 候选池的 akshare 影响

`etf_scanner.py` 的 `fetch_all_etfs_base()` 数据链为 Sina 列表→腾讯 gtimg→akshare。前两源已提供代码/名称/成交额/规模等核心字段，akshare 失败时：
- **影响**：缺失基金规模/PE/PB 等辅助字段
- **不影响**：ETF 列表、代码、价格、成交量等核心数据
- **组合设计**：仍能正常运行，仅辅助排序字段缺失

---

## 3. 目标架构

### 3.1 核心原则

1. **市场上下文贯穿全链路**：前端 Tab → API 参数 → Service 层数据路由 → LLM prompt 注入，层层传递
2. **增量改造，不破坏现有功能**：A 股默认行为不变，仅当显式传入市场参数时才切换
3. **按市场路由数据源**：不同市场走不同的数据源链，通过 `SourceRegistry` 熔断器自动降级
4. **LLM prompt 按市场注入**：不同市场给不同的指数、新闻、情绪数据
5. **能力透明**：每个功能明确标注在哪些市场可用，不可用时给用户友好提示而非静默失败

### 3.2 分层架构

```
┌─ Frontend ──────────────────────────────────────────────┐
│  MarketAnalysis.vue  (marketTab: 'A'|'HK'|'US'|'global')│
│    │  marketTab 传到所有子组件                            │
│    ├─ MarketReport   → POST /llm-report/stream {market}  │
│    ├─ AiAdvisor      → POST /llm-advice/stream {market}  │
│    ├─ SectorAnalysis → POST /sector-analysis/stream {mkt}│
│    └─ SymbolAnalysis → POST /symbol-analysis/stream {mkt}│
│  DashboardAiTools                                         │
│    └─ DesignAsync   → POST /design-async {market}        │
└──────────────────────────────────────────────────────────┘
                         │  market 参数
                         ▼
┌─ Backend ────────────────────────────────────────────────┐
│  Router Layer                                              │
│    resolve_market_context(market) → MarketContext          │
│    MarketContext 决定: index_symbols, regime_broad_index,  │
│                       news_sources, data_source_order,      │
│                       available_features                   │
│                                                           │
│  Service Layer                                             │
│    market_router.py:                                       │
│    ├─ get_market_indices(market)       → 按市场路由指数   │
│    ├─ get_market_realtime(market, sym) → 按市场路由行情   │
│    ├─ get_market_history(market, sym)  → 按市场路由K线   │
│    ├─ get_market_regime(market)        → 按市场判断市态   │
│    ├─ get_market_news(market)          → 按市场选新闻源   │
│    └─ get_market_sectors(market)       → 按市场选板块数据 │
│                                                           │
│  Data Source Layer                                        │
│    A股 : china_market (mootdx→Sina→QQ)                   │
│    港股: china_market (Sina→QQ→EM) + Finnhub(兜底)        │
│    美股: Stooq → TwelveData → Finnhub                     │
│    全球: 新浪海外指数 → Stooq → TwelveData                │
│                                                           │
│  SourceRegistry (熔断器)                                   │
│    自动隔离失败源, 按优先级尝试下一个                       │
│                                                           │
│  LLM Prompt Layer                                         │
│    prompt 首行注入: "当前分析市场: {market_title}"           │
│    数据注入: 只传对应市场的数据, 杜绝混入其他市场           │
└──────────────────────────────────────────────────────────┘
```

---

## 4. 数据源替换方案

### 4.1 美股实时行情：新建 `_route_us_stooq()` 链路

当前 `market_service.py` 中 `_route_us()` 链路是 `TwelveData → Finnhub → AlphaVantage → yfinance`。**需要重写为**：

```python
def _route_us_stooq(symbol: str) -> dict | None:
    """美股行情新链路：Stooq 为主力，TwelveData/Finnhub 为备用。"""
    return registry.route([
        ("stooq",       lambda: _call(stooq_fetcher.fetch_us_etf_realtime, symbol, timeout=6)),
        ("twelvedata",  lambda: _call(twelvedata_fetcher.fetch_realtime, symbol, timeout=8)),
        ("finnhub",     lambda: _call(finnhub_fetcher.fetch_realtime, symbol, timeout=8)),
    ])
```

### 4.2 美股批量行情

```python
def _route_us_batch(symbols: list[str]) -> list[dict] | None:
    """美股批量行情：Stooq 批量（单次请求全部），降级为逐个 TwelveData。"""
    return registry.route([
        ("stooq",       lambda: _call(stooq_fetcher.fetch_us_batch, symbols, timeout=12)),
        ("twelvedata",  lambda: [_call(twelvedata_fetcher.fetch_realtime, sym) for sym in symbols]),
    ])
```

### 4.3 美股历史 K 线

```python
def _route_us_history(symbol: str, period: str = "daily") -> list[dict]:
    """美股历史 K 线。"""
    return registry.route([
        ("stooq",       lambda: _call(stooq_fetcher.fetch_stooq_history, symbol, period, timeout=15)),
        ("twelvedata",  lambda: _call(twelvedata_fetcher.fetch_history, symbol, 60, timeout=10)),
        ("finnhub",     lambda: _call(finnhub_fetcher.fetch_candles, symbol, "D", timeout=10)),
    ]) or []
```

### 4.4 全球指数

```python
# get_global_indices() 现有链路改为:
async def _foreign(sym, name, region):
    # 第1优先：新浪
    # 第2优先：Stooq
    # 不再 fallback 到 yfinance
    # 两源均失败 → 占位返回 {available: False}
```

### 4.5 yfinance 处理策略

```python
# yfinance_fetcher.py 顶部新增:
"""
[DEPRECATED] This module is kept for users who have proxy access.
Prefer Stooq (stooq_fetcher) or TwelveData (twelvedata_fetcher) for US data.
Only works when YFINANCE_PROXY env var is set.
"""

def fetch_us_etf_realtime(symbol: str) -> dict | None:
    import os
    if not os.environ.get("YFINANCE_PROXY"):
        return None  # 无代理时静默跳过
    ...
```

**不做代码删除**，仅从所有路由链路中移除其优先级。

### 4.6 akshare 统一降级策略

akshare 作为代码库中最不稳定的数据源之一，统一降低其到所有降级链路的末位。涉及 4 处"唯一依赖"的修补：

#### 修补 4.6.1：期货/商品行情 — 增加 Stooq 降级

```python
# china_market.py fetch_futures_realtime()
# 当前: 仅 akshare → 改为: Stooq 商品ETF 主源 → akshare 期货兜底

COMMODITY_ETF_MAP = {
    "gold":   ("GLD", "黄金"),
    "silver": ("SLV", "白银"),
    "oil":    ("USO", "原油"),
}

async def fetch_futures_realtime() -> list[dict]:
    """商品/期货行情。Stooq 商品ETF主源，akshare 国内期货兜底。"""
    from ..fetchers.stooq_fetcher import fetch_us_batch
    etf_codes = [v[0] for v in COMMODITY_ETF_MAP.values()]
    stooq_data = await run_sync(fetch_us_batch, etf_codes, timeout=12)
    if stooq_data:
        results = []
        for d in stooq_data:
            name = COMMODITY_ETF_MAP.get(d.get("symbol","").upper(), (None, d.get("symbol","")))[1]
            results.append({
                "symbol": d["symbol"], "name": name,
                "price": d["price"], "change_pct": d["change_pct"],
                "change_amount": d.get("change_amount", 0),
                "volume": d.get("volume", 0), "asset_type": "futures",
            })
        return results
    # 降级: akshare 国内期货（现有逻辑）
    return _akshare_futures_fallback()
```

#### 修补 4.6.2：指数历史 K 线 — 增加 Sina/mootdx 降级

```python
# china_market.py fetch_index_history()
# 当前: 仅 akshare → 改为: mootdx 指数日线 → akshare 兜底

def fetch_index_history(symbol: str, period: str = "daily") -> list[dict]:
    with no_proxy():
        # 第一优先: mootdx（通达信协议，免费稳定）
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        df = client.index(symbol=symbol, frequency=9)  # 9=日线
        if df is not None and not df.empty:
            return _mootdx_to_standard(df)
        # 第二优先: Sina 指数日线
        rows = _sina_index_history(symbol)
        if rows:
            return rows
    # 第三优先: akshare（现有逻辑）
    return _akshare_index_fallback(symbol, period)
```

#### 修补 4.6.3：港股/美股历史 K 线 — 增加 Stooq 降级

```python
# china_market.py fetch_history() 中 asset_type in ("HK","US") 分支
# 改为:

if asset_type == "US":
    from ..fetchers.stooq_fetcher import fetch_stooq_history
    rows = await run_sync(fetch_stooq_history, symbol, period, timeout=15)
    if rows:
        return rows
elif asset_type == "HK":
    from ..fetchers.stooq_fetcher import fetch_stooq_history
    rows = await run_sync(fetch_stooq_history, symbol, period, timeout=15)
    if rows:
        return rows
# 最后 fallback 到 akshare（现有）
return _fetch_akshare_history(symbol, asset_type, period)
```

#### 修补 4.6.4：板块动量 — 改用 sector_fetcher（已自带双源降级）

```python
# market_trends.py compute_sector_momentum()
# 改为: 使用 sector_fetcher 替代直接调 akshare

def compute_sector_momentum(top_n: int = 10) -> list[dict]:
    from ..fetchers.sector_fetcher import fetch_industry_sectors
    sectors = fetch_industry_sectors(limit=100)  # levistock→akshare 双源
    if not sectors:
        return []
    # 按涨跌幅排序取前 top_n
    sectors.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    return [
        {"sector": s["sector_name"], "rank_current": i+1,
         "change_pct": s.get("change_pct", 0)}
        for i, s in enumerate(sectors[:top_n])
    ]
```

#### akshare 降级后全链路示意

```
数据源统一优先级规则:
  [1] Stooq / Sina / mootdx / levistock / Tencent gtimg
  [2] Twelve Data / Finnhub（需 API key，有额度限制）
  [3] akshare（不稳定，仅做末位兜底）
  [4] yfinance（仅代理模式）
```

### 4.7 数据源健康探针更新

```python
# main.py
async def _register_health_probes():
    # 新增: Stooq
    register_probe("stooq", lambda: _call(stooq_fetcher.fetch_us_batch, ["SPY"], timeout=6), timeout=10)
    # 保留: Twelve Data
    register_probe("twelvedata", lambda: _call(twelvedata_fetcher.fetch_realtime, "SPY", timeout=8), timeout=12)
    # 保留: Finnhub
    register_probe("finnhub", lambda: _call(finnhub_fetcher.fetch_realtime, "SPY", timeout=8), timeout=12)
    # 移除: yfinance (不再作为健康探针)
```

---

## 5. 市场感知联动方案

### 5.1 MarketContext 数据类（新增文件）

```python
# backend/app/core/market_context.py (新文件)

from dataclasses import dataclass, field
from typing import Any

MARKET_INDEX_MAP = {
    "A":  {"000001", "399001", "399006", "000688", "000300"},
    "HK": {"^HSI", "^HSCE", "^HSTECH"},
    "US": {"^GSPC", "^IXIC", "^DJI"},
    # "global" 无聚合 key — 单独处理
}

MARKET_TITLE_MAP = {
    "A": "A股",
    "HK": "港股",
    "US": "美股",
    "global": "全球市场",
}

@dataclass
class MarketContext:
    market: str  # "A" | "HK" | "US" | "global"

    @property
    def index_symbols(self) -> set[str]:
        return MARKET_INDEX_MAP.get(self.market, set())

    @property
    def title(self) -> str:
        return MARKET_TITLE_MAP.get(self.market, "未知市场")

    @property
    def regime_broad_index(self) -> str | None:
        """市态判断用的基准指数。global 无单一基准 → None。"""
        return {"A": "000001", "HK": "^HSI", "US": "^GSPC"}.get(self.market)

    @property
    def supports_sector_analysis(self) -> bool:
        """板块分析仅 A 股有成熟数据源。"""
        return self.market == "A"

    @property
    def supports_portfolio_design(self) -> bool:
        """组合设计仅 A 股有完整候选池。"""
        return self.market == "A"

    @property
    def supports_regime_detection(self) -> bool:
        """市态判断仅 A/US 有可行数据。"""
        return self.market in ("A", "US")

def resolve_market_context(market: str) -> MarketContext:
    """统一的市场上下文解析入口。默认 A 股保持向后兼容。"""
    if market not in ("A", "HK", "US", "global"):
        market = "A"
    return MarketContext(market=market)
```

### 5.2 数据路由 Service 层（新增文件）

```python
# backend/app/services/market_router.py (新文件)

from ..core.async_utils import run_sync
from ..fetchers import stooq_fetcher, twelvedata_fetcher, finnhub_fetcher
from ..fetchers.china_market import fetch_hk_stock_realtime, fetch_hk_history
from ..services.source_registry import registry

# 辅助: 包装 run_sync 统一超时
async def _call(fn, *args, timeout=8):
    return await run_sync(fn, *args, timeout=timeout)

# ── 指数路由 ──

async def get_market_indices(market: str) -> list[dict]:
    """按市场返回相关指数行情。"""
    from .market_service import get_indices as get_a_indices, get_global_indices

    if market == "A":
        return await get_a_indices() or []

    # HK/US/global → 从全球指数中过滤
    global_data = await get_global_indices() or {}
    region_map = {"HK": "港股", "US": "美股", "global": None}
    target_region = region_map.get(market)
    if target_region is None:
        # global: 展平所有
        flattened = []
        for region_list in global_data.values():
            flattened.extend(region_list)
        return flattened
    return global_data.get(target_region, [])

# ── 实时行情路由 ──

async def get_market_realtime(market: str, symbols: list[str] | None = None) -> list[dict]:
    """按市场路由实时行情。"""
    if market == "A":
        from .market_service import get_all_realtime
        data = await get_all_realtime()
        if symbols:
            sym_set = set(symbols)
            return [d for d in data if d.get("symbol") in sym_set]
        return data

    elif market == "HK":
        if not symbols:
            return []
        results = []
        for sym in symbols:
            items = await _call(fetch_hk_stock_realtime, sym, timeout=8)
            if items:
                results.extend(items)
        return results

    elif market == "US":
        if not symbols:
            return []
        batch = await _call(stooq_fetcher.fetch_us_batch, symbols, timeout=12)
        if batch:
            return batch
        # 降级: TwelveData 逐个
        results = []
        for sym in symbols:
            d = await _call(twelvedata_fetcher.fetch_realtime, sym, timeout=8)
            if d:
                d["asset_type"] = "US"
                results.append(d)
        return results

    elif market == "global":
        # 聚合: A股 + US(Stooq) + HK + 全球指数
        from .market_service import get_all_realtime
        a_data = await get_all_realtime() or []
        indices_data = await get_market_indices("global")
        return a_data + indices_data

# ── 历史K线路由 ──

async def get_market_history(market: str, symbol: str, period: str = "daily") -> list[dict]:
    """按市场路由历史K线。"""
    if market == "A":
        from .market_service import get_history
        return await get_history(symbol, "A", period)

    elif market == "HK":
        hk_history = await _call(fetch_hk_history, symbol, period, timeout=15)
        if hk_history:
            return hk_history
        # 降级: Stooq (港股ETF)
        return await _call(stooq_fetcher.fetch_stooq_history, symbol, period, timeout=15) or []

    elif market == "US":
        stooq_data = await _call(stooq_fetcher.fetch_stooq_history, symbol, period, timeout=15)
        if stooq_data:
            return stooq_data
        td_data = await _call(twelvedata_fetcher.fetch_history, symbol, 60, timeout=10)
        if td_data:
            return td_data
        fh_data = await _call(finnhub_fetcher.fetch_candles, symbol, "D", timeout=10)
        return fh_data or []

    elif market == "global":
        return await get_market_history("A", symbol, period)  # 默认回退

# ── 新闻路由 ──

async def get_market_news(market: str, max_count: int = 10) -> list[dict]:
    """按市场选择新闻源。
    注：当前仅 A 股有专有新闻源（财联社/宏观）。HK/US 通过国际通用新闻补充。
    """
    from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news, fetch_global_news

    headlines = await _call(fetch_news_headlines, timeout=8) or []
    macro = await _call(fetch_macro_news, timeout=8) or []
    global_news = await _call(fetch_global_news, timeout=8) or []

    all_news = headlines + macro + global_news
    return all_news[:max_count]

# ── 板块路由 ──

async def get_market_sectors(market: str, sector_type: str = "industry") -> list[dict]:
    """按市场选择板块数据源。
    当前仅 A 股有成熟板块数据（申万/东财）。HK/US 返回空列表。
    文档第 8 章标记为"不适用"而非静默失败。
    """
    if market != "A":
        return []
    from ..fetchers.sector_fetcher import fetch_industry_sectors, fetch_concept_sectors
    if sector_type == "concept":
        return await _call(fetch_concept_sectors, 200, timeout=10) or []
    return await _call(fetch_industry_sectors, 200, timeout=10) or []
```

### 5.3 各端点的具体改造

#### 5.3.1 MarketReport (`/llm-report/stream`)

**前端改动** (`MarketReport.vue`):
```javascript
const result = await startMarketStream('/llm-report/stream', {
  symbols: null,
  market: props.marketTab,   // ← 新增
}, (token) => { marketReport.value += token })
```

**后端改动** (`analysis.py` `llm_report_stream`):
```python
class LLMReportRequest(BaseModel):
    symbols: list[str] | None = None
    market: str = "A"   # ← 新增

async def llm_report_stream(req: LLMReportRequest):
    ctx = resolve_market_context(req.market)

    # 按市场采集数据
    market_data = await get_market_realtime(ctx.market)
    indices = await get_market_indices(ctx.market)
    news = await get_market_news(ctx.market)

    # 仅 A 股计算技术指标（HK/US 无足够历史数据暂不计算）
    indicators = {}
    if ctx.market == "A":
        for item in market_data[:5]:
            try:
                hist = await asyncio.wait_for(get_history(...), timeout=30)
                ind = compute_all_indicators(hist)
                if ind: indicators[item["symbol"]] = ind
            except Exception:
                continue

    # LLM prompt 首行注入市场标识
    enriched_news = [{"title": f"【{ctx.title} · 市场分析】"}] + news

    # regime 注入
    regime = get_market_regime_sync(ctx.market)
    ...
```

#### 5.3.2 AiAdvisor (`/llm-advice/stream` **重要**)

> ⚠️ 特别注意：`llm_advice_stream` 流式版当前**没有任何数据注入逻辑**（不同于非流式 `llm_advice` 的关键词注入）。需要重新实现数据注入。

**前端改动** (`AiAdvisor.vue`):
```javascript
const context = {
  include_market_data: true,
  include_news: true,
  market: props.marketTab,   // ← 改为动态
}
```

**后端改动** (`analysis.py` 新增 `llm_advice_stream` 的数据注入逻辑):
```python
@router.post("/llm-advice/stream")
async def llm_advice_stream(query: str = Query(...), context: dict | None = None):
    ctx_dict = context or {}
    market = ctx_dict.get("market", "A")
    market_ctx = resolve_market_context(market)

    # 数据注入（参考非流式版 llm_advice 的 smart injection）
    injection_lines = []
    q = query.lower()

    # 市态 & 情绪（按市场）
    if any(kw in q for kw in ["大盘", "今天", "最新", "走势", "行情"]):
        regime = get_market_regime_sync(market_ctx.market)
        injection_lines.append(f"· 市场状态 ({market_ctx.title}): {regime}")
        # 指数行情
        indices = await get_market_indices(market_ctx.market)
        for item in indices[:5]:
            injection_lines.append(
                f"· {item.get('name','?')}: {item.get('price','N/A')} ({item.get('change_pct',0):+.2f}%)"
            )

    # 新闻
    if any(kw in q for kw in ["政策", "利好", "利空", "新闻", "资讯"]):
        news = await get_market_news(market_ctx.market)
        for n in news[:5]:
            injection_lines.append(f"· {n.get('title','')[:100]}")

    # 构建 prompt（含市场标识）
    prompt = f"当前分析市场: {market_ctx.title}\n\n"
    if injection_lines:
        prompt += "市场快照:\n" + "\n".join(injection_lines) + "\n\n"
    prompt += f"用户提问: {query}\n\n请给出专业、简洁的回答..."

    agent = get_agent("advice")
    return _sse_stream(agent.run_stream(prompt))
```

#### 5.3.3 SectorAnalysis (`/sector-analysis/stream`)

**后端改动**:
```python
class SectorAnalysisRequest(BaseModel):
    sector_code: str
    sector_type: str = "industry"
    sector_name: str = ""
    market: str = "A"  # ← 新增

    # 处理逻辑:
    # - market != "A" → 返回空数据，LLM prompt 加"该市场暂无板块数据"
    # - A 股 → 现有逻辑
```

**前端改动**: `SectorAnalysis.vue` 的 `analyzeSector()` 调用传 `market: props.marketTab`。但需注意前端的 `useSectorAnalysis` 在 `marketTab === 'global'` 时已跳过板块列表请求，保持该行为。

#### 5.3.4 SymbolAnalysis (`/symbol-analysis/stream`)

**后端改动**:
```python
class SymbolAnalysisRequest(BaseModel):
    symbol: str
    name: str = ""
    asset_type: str = "A"

    # LLM prompt 增加:
    # "当前分析 {ctx.title} 标的 {symbol}"
    # 注入对应市场的实时行情 + 历史数据
```

**前端改动**: `SymbolAnalysis.vue` 已传 `asset_type: props.marketTab`，不需额外改动。

#### 5.3.5 Portfolio Design (`/design-async`)

**后端改动** (`portfolio.py` + `strategy_design.py`):
```python
# portfolio.py
@router.post("/design-async")
async def portfolio_design_async(task: dict):
    capital = task.get("capital", 500000)
    constraints = task.get("constraints")
    market = task.get("market", "A")  # ← 新增

    if market != "A":
        return JSONResponse(status_code=202, content={
            "task_id": None,
            "status": "unsupported",
            "message": f"组合设计当前仅支持 A 股市场，{market} 市场暂不支持",
        })

    # 现有逻辑不变
    ...

# strategy_design.py
async def generate_enhanced_design(capital=..., constraints=..., market="A"):
    # 增加市场参数入口，当前仅 A 股有候选池
    # 未来扩展见第 8 章
```

#### 5.3.6 Market Regime Detection（重要依赖链改造）

**market_trends.py** — 改造整个依赖链：

```python
def detect_market_regime(
    market: str = "A",
    trends: dict | None = None,
    index_realtime: list[dict] | None = None,
) -> str:
    """基于市场选择判断市态。"""
    if market == "global":
        return "unknown"  # global 无单一市态

    broad_index = {"A": "000001", "HK": "^HSI", "US": "^GSPC"}.get(market, "000001")
    # 从 trends 或 index_realtime 提取信号
    ...
```

**pool_manager.py** — regime 缓存改为多市场：
```python
# 之前: self._regime_cache: str | None = None
# 改为:
self._regime_cache: dict[str, str] = {}       # {'A': 'bull', 'HK': 'correction'}
self._regime_cache_ts: dict[str, float] = {}   # 按市场记录时间戳
REGIME_TTL = 60

def get_market_regime(self, market: str = "A") -> str:
    """按市场获取市态。"""
    import time
    now = time.time()
    cached = self._regime_cache.get(market)
    ts = self._regime_cache_ts.get(market, 0)
    if cached and (now - ts) < self.REGIME_TTL:
        return cached
    return cache.get(market) or "range_bound"

async def update_market_regime(self, market: str = "A") -> None:
    """按市场异步刷新市态。"""
    if market == "global":
        return
    broad_index = {"A": "000001", "HK": "^HSI", "US": "^GSPC"}.get(market, "000001")
    # 拉取对应市场的趋势数据
    trends = await compute_etf_trends([broad_index], market=market)
    index_realtime = await get_market_indices(market)
    regime = detect_market_regime(market, trends, index_realtime)
    self._regime_cache[market] = regime
    self._regime_cache_ts[market] = time.time()
```

**`compute_sector_momentum` 改为使用 sector_fetcher（消除 akshare 直接依赖）**:

```python
# market_trends.py — 替换原有的 akshare stock_board_industry_name_em 调用
# 改为用 sector_fetcher.fetch_industry_sectors()（levistock→akshare 双源降级）

def compute_sector_momentum(top_n: int = 10) -> list[dict]:
    from ..fetchers.sector_fetcher import fetch_industry_sectors
    sectors = fetch_industry_sectors(limit=100)  # levistock 主源
    if not sectors:
        return []
    sectors.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    return [
        {"sector": s["sector_name"], "rank_current": i+1,
         "change_pct": s.get("change_pct", 0)}
        for i, s in enumerate(sectors[:top_n])
    ]
```

**`_fetch_single_trend` 增加 market 参数**:
```python
async def _fetch_single_trend(symbol: str, market: str = "A") -> dict:
    if market == "A":
        # 现有: fetch_history(symbol, "A", "daily")
        ...
    elif market == "US":
        # 新增: Stooq 历史
        from ..fetchers.stooq_fetcher import fetch_stooq_history
        rows = await asyncio.to_thread(fetch_stooq_history, symbol, "daily")
        ...
    elif market == "HK":
        # 新增: akshare 港股历史
        from ..fetchers.china_market import fetch_hk_history
        rows = await asyncio.to_thread(fetch_hk_history, symbol, "daily")
        ...
```

#### 5.3.7 Search (`/market/search`)

```python
@router.get("/search")
async def search(keyword: str = "", market: str = Query("A")):  # ← 新增 market
    """根据市场搜索。当前 Instrument 表主要含 A 股，HK/US 降级到各自源。"""
    if market == "A":
        # 现有逻辑：本地 Instrument 表
        ...
    elif market == "HK":
        # 降级: 新浪港股搜索（或返回空 + 提示）
        ...
    elif market == "US":
        # 降级: Stooq（或返回空 + 提示）
        ...
    elif market == "global":
        return await search(keyword, "A")  # 默认 A 股
```

### 5.4 LLM Prompt 市场注入

#### 5.4.1 所有流式端点的统一注入

所有分析端点在构建 LLM prompt 时，在首行注入：

```
**分析要求：**
- 分析市场：{ctx.title}
- 回答必须严格基于输入的 {ctx.title} 数据
- 不要混入其他市场的数据或分析
- 如果输入数据中没有该市场的有效数据，在报告中说明
```

#### 5.4.2 `general_analyst.md` prompt 改造

```markdown
# 原: "你是专业的中国金融市场投资顾问"
# 改为:
你是专业的 ETF 投资组合策略分析师。根据输入的"分析市场"字段调整分析范围。
如果分析市场为"港股"，重点分析恒生系列指数和港股 ETF；
如果分析市场为"美股"，重点分析标普/纳指/道指和美股 ETF；
如果分析市场为"全球市场"，综合分析全球主要指数和跨市场机会。
```

### 5.5 实施状态矩阵（2026-07-26 审计）

> 以下矩阵基于当前代码库交叉验证，标记 §5 各子项的实际实施状态。

| §5 子项 | 计划内容 | 实际代码状态 | 覆盖阶段 | 说明 |
|---------|---------|:-----------:|:--------:|------|
| 5.1 MarketContext | `core/market_context.py` 新文件 | ❌ **未创建** | — | 文件不存在 |
| 5.2 market_router | `services/market_router.py` 新文件 | ❌ **未创建** | — | 文件不存在 |
| 5.3.1 MarketReport | 前端传 market, 后端过滤 | 🟡 **部分实现** | Phase 2.9 | `LLMReportRequest` 含 `market` 字段，但 `llm_report_stream` 流式端点仍硬编码 A 股符号集，前端未传 market 参数 |
| 5.3.2 AiAdvisor | 前端传 market, 后端数据注入 | 🟡 **部分实现** | Phase D/2.9 | 后端改用 `build_full_context()` + `_build_advice_stream_prompt()`，但 **无 market 参数**（始终走 A 股管道），前端 `marketTab` prop 存在但 **未传 API** |
| 5.3.3 SectorAnalysis | 增加 market 参数 | ❌ **未实现** | — | `SectorAnalysisRequest` 无 market 字段 |
| 5.3.4 SymbolAnalysis | 注入 market 上下文 | ❌ **未实现** | — | `SymbolAnalysisRequest` 无 market 字段 |
| 5.3.5 Portfolio Design | 增加 market 参数 + 非A提示 | ❌ 待验证 | — | 未在 `portfolio.py` 中确认 |
| 5.3.6 Regime 检测 | `_regime_cache: dict[str,str]` + `get_market_regime(market)` | ❌ **未实现** | — | 仍为 `_regime_cache: str` 单市场，无 market 参数 |
| 5.4.1 统一注入 | 所有端点首行"分析市场" | ❌ **未实现** | — | 无端点在 LLM prompt 首行注入 market 标题 |
| 5.4.2 general_analyst.md | prompt 改为按市场动态 | ❌ **未实现** | — | `general_analyst.md` 未修改 |

**结论**：§5 市场感知联动的**10 项**子任务中，**0 项完全实现**、**2 项部分实现**、**8 项未实现**。该方案作为完整方案独立实施的决策仍然有效。`market-analysis-optimization-plan.md` Phase D/E 仅覆盖了后端数据管道层面（`build_full_context()`），未涉及市场感知联动的核心——**market 参数的端到端传递和 LLM prompt 的市场上下文注入**。

---

## 6. API 契约变更

### 6.1 变更总览

| 端点 | 方法 | 当前参数 | 新增参数 | 兼容性 |
|------|------|---------|---------|--------|
| `/llm-report/stream` | POST | `{symbols}` | `{market: "A"}` | ✅ 缺省 = "A" |
| `/llm-advice/stream` | POST | `query + context` | `context.market` | ✅ 通过 context 透传，缺省 = "A" |
| `/sector-analysis/stream` | POST | `{sector_code, type, name}` | `{market: "A"}` | ✅ 缺省 = "A" |
| `/symbol-analysis/stream` | POST | `{symbol, name, asset_type}` | `asset_type` 等效 market | ✅ 已有字段复用 |
| `/design-async` | POST | `{capital, constraints}` | `{market: "A"}` | ✅ 缺省 = "A" |
| `/market/search` | GET | `?keyword=` | `&market=A` | ✅ 可选参数 |
| `/market/realtime/batch` | GET | `symbols + asset_type` | 无变化 | — |

### 6.2 MarketContext 新增依赖

| 新增文件 | 职责 |
|---------|------|
| `backend/app/core/market_context.py` | `MarketContext` 数据类 + `resolve_market_context()` |
| `backend/app/services/market_router.py` | 5 个按市场路由函数 (`get_market_*`) |

---

## 7. 实施阶段

> ⚠️ **2026-07-26 审计更新**：以下阶段划分基于 v3 文档撰写时的架构。Phase 4.1 已独立实施数据源改造（`roadmap-data-source-unified.md`），Phase 2.9 已统一 LLM 上下文管道（`build_full_context()`）。**§7 仅作为历史参考保留**，最新实施路线请参考：
> - 数据源改造：`roadmap-data-source-unified.md` v3.0（已实施）
> - 市场感知联动：`implementation-master-plan.md` Phase 5.1（待评估）
> - LLM 数据管道：`implementation-master-plan.md` Phase 2.9（已实施）
> - AI Advisor 流式改造：`market-analysis-optimization-plan.md` Phase D（部分实施，缺市场感知）
> - 市场报告增强：`market-analysis-optimization-plan.md` Phase E（部分实施，缺 prompt 增强）

### 7.0 阶段零：akshare 降级修补（1天）

| # | 任务 | 文件 | 工时 |
|---|------|------|------|
| 0.1 | 期货/商品：增加 Stooq 商品ETF作主源，akshare降级 | `china_market.py` | 1h |
| 0.2 | 指数历史K线：增加 mootdx 指数日线作主源 | `china_market.py` | 1.5h |
| 0.3 | 港股/US历史K线：增加 Stooq 历史K线作主源 | `china_market.py` | 1h |
| 0.4 | 板块动量：`compute_sector_momentum` 改用 `sector_fetcher` | `market_trends.py` | 0.5h |
| 0.5 | 验证：akshare 离线时所有功能可降级运行 | — | 1h |

### 7.1 阶段一：数据源替换（2天）

| # | 任务 | 文件 | 工时 |
|---|------|------|------|
| 1.1 | 新增 `_route_us_stooq()` 作为美股主力链路 | `market_service.py` | 1.5h |
| 1.2 | 重写 `get_global_indices()` 移除 yfinance 备选 | `market_service.py` | 1h |
| 1.3 | yfinance 标注 deprecated + 仅代理模式 | `yfinance_fetcher.py` | 0.5h |
| 1.4 | 更新健康探针：注册 Stooq、移除 yfinance | `main.py` | 0.5h |
| 1.5 | 跑 `verify_e2e.py` 验证美股行情/全球指数 | — | 1h |

### 7.2 阶段二：市场上下文基础设施（3天）

| # | 任务 | 文件 | 工时 |
|---|------|------|------|
| 2.1 | 新增 `MarketContext` 数据类 | `core/market_context.py` | 1h |
| 2.2 | 新增 `market_router.py`（5 个路由函数） | `services/market_router.py` | 4h |
| 2.3 | 改造 `_fetch_single_trend` 支持多 market 参数 | `market_trends.py` | 2h |
| 2.4 | 改造 `detect_market_regime` 支持多 market | `market_trends.py` | 1.5h |
| 2.5 | pool_manager regime cache 改为 `dict[str, str]` | `pool_manager.py` | 1h |
| 2.6 | pool_manager 新增 `get_market_regime(market)` | `pool_manager.py` | 0.5h |
| 2.7 | `general_analyst.md` prompt 改为按市场动态 | `analysis/prompts/v1/` | 0.5h |

### 7.3 阶段三：前端+后端联动改造（3天）

| # | 任务 | 文件 | 工时 |
|---|------|------|------|
| 3.1 | MarketReport 传 market + 后端改造 | `MarketReport.vue` + `analysis.py` | 2h |
| 3.2 | AiAdvisor 传 market + 后端**重写流式数据注入** | `AiAdvisor.vue` + `analysis.py` | 3h |
| 3.3 | design-async 增加 market 参数 + 校验 | `portfolio.py` + `strategy_design.py` | 1.5h |
| 3.4 | sector-analysis 增加 market 参数 | `analysis.py` + `SectorAnalysis.vue` | 1.5h |
| 3.5 | symbol-analysis 注入 market 上下文 | `analysis.py` | 1h |
| 3.6 | 搜索增加 market 参数 | `market.py` + `SymbolAnalysis.vue` | 1h |
| 3.7 | 前端 Tab 切换时取消进行中的 SSE 请求 + 显示加载态 | 各 `.vue` 文件 | 1h |

### 7.4 阶段四：E2E 验证 + 边缘 case 修复（1.5天）

| # | 任务 | 类型 | 工时 |
|---|------|------|------|
| 4.1 | `verify_e2e.py` 增加美股行情测试：`verify_us_market()` → 调用 Stooq 验证 SPY | 自动化 | 0.5h |
| 4.2 | `verify_e2e.py` 增加港股行情测试：`verify_hk_market()` → 调用 Sina/QQ 验证 00700 | 自动化 | 0.5h |
| 4.3 | `verify_e2e.py` 增加市场切换测试：`verify_market_context()` → 验证 MarketContext 正确性 | 自动化 | 0.5h |
| 4.4 | 手动测试：美股非交易时段 Stooq 返回处理 | 手动 | 0.5h |
| 4.5 | 手动测试：Tab 快速切换时 SSE 取消无报错 | 手动 | 0.5h |
| 4.6 | 手动测试：数据源全部不可用时的降级行为 | 手动 | 0.5h |
| 4.7 | API 契约文档更新 (`api-contracts/`) | 文档 | 1h |

**总计工作量：约 10.5 人天**（含阶段零 1 天 + 阶段一 2 天 + 阶段二 3 天 + 阶段三 3 天 + 阶段四 1.5 天）

---

## 8. 功能-市场兼容矩阵

> 此矩阵明确了每个功能在各市场的能力，不可用时给予友好提示。

| 功能 | A 股 | 港股 | 美股 | 全球 |
|------|------|------|------|------|
| 行情研判 (MarketReport) | ✅ 完整分析 | ✅ 港股指数分析 | ✅ 美股指数分析 | ✅ 全球综合 |
| AI 投资顾问 | ✅ 完整 | ✅ 有限（港股数据注入） | ✅ 有限（美股数据注入） | ✅ 综合 |
| 板块 LLM 分析 | ✅ 完整（申万行业） | ❌ 不适用（无板块数据源） | ❌ 不适用（无板块数据源） | ❌ 不适用 |
| 个股/ETF 分析 | ✅ 完整 | ✅ 有限（历史数据支撑有限） | ✅ 有限（Stooq 历史） | N/A |
| 组合智能设计 | ✅ 完整 | ⏳ 返回友好提示 | ⏳ 返回友好提示 | N/A |
| 策略检查 | ✅ 完整 | ⏳ 返回友好提示 | ⏳ 返回友好提示 | N/A |
| 市态判断 | ✅ 完整 | ⏳ 数据源有限 | ✅ 基础判断 | ❌ 无意义 |
| 搜索 | ✅ 本地表 | ⚠️ 降级搜索 | ⚠️ 降级搜索 | ✅ A 股降级 |

> ✅ = 实现；⏳ = 功能不适用但返回明确提示；⚠️ = 功能可用但数据有限；❌ = 功能不可用

### 8.1 板块分析各市场说明

- **A 股**：有申万一级行业（levistock + akshare）和东财概念板块，数据成熟
- **港股**：恒生行业分类存在但未接入；LLM 分析板块时返回"港股暂无板块分析数据"
- **美股**：GICS 行业分类未接入；同上处理
- **组合设计非 A 市场友好提示示例**：
  ```json
  {
    "status": "unsupported",
    "message": "组合设计当前仅支持 A 股市场（沪市/深市 ETF）。港股和美股市场的组合设计功能正在规划中。",
    "strategies": []
  }
  ```

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Stooq 在部分网络环境下 SSL 握手慢 | 中 | 低（超时降级） | 已有 `no_proxy()` 隔离；超时 6s 后自动降到 Twelve Data |
| Twelve Data 800次/天并发不够 | 低 | 中 | 仅做备用源，不频繁调用；Finnhub(60次/分) 补充；将来可扩展 |
| 港股历史 K 线数据不稳定 | 中 | 中 | akshare 港股日线 + Stooq 港股 ETF 双源降级 |
| `llm_advice/stream` 数据注入需从零写 | **高** | **中** | 参考非流式版 `llm_advice` 的 smart injection 逻辑，提取为公共函数 |
| 现有 LLM prompt 有 A 股硬编码措辞 | 高 | 低 | v2 已规划 prompt 改造任务 (2.7) |
| pool_manager 仅 A 股候选池 | 高 | 中 | 组合设计对非 A 市场返回明确提示 |
| 无专有 HK/US 新闻源，LLM 分析质量下降 | **高** | **中** | 当前阶段未承诺新闻增强；通过通用国际新闻 (MarketWatch RSS) 兜底；后续可评估 Finnhub News API |
| 前端 Tab 切换中断 SSE 导致用户困惑 | 中 | 低 | 阶段三 (3.7) 处理：取消 in-flight 请求 + 显示加载态 |
| `verify_e2e.py` 依赖外部数据源，测试不稳定 | 中 | 低 | 增加 retry 和 timeout；区分网络测试和逻辑测试 |

---

## 10. 文件改动清单

### 10.1 新增文件（2个）

```
backend/app/core/market_context.py        # MarketContext 数据类 + resolve_market_context()
backend/app/services/market_router.py      # 5 个按市场路由函数
```

### 10.2 修改文件（13个）

```
# ── 后端 (10个) ──
backend/app/main.py                           # 健康探针：注册 Stooq，移除 yfinance
backend/app/fetchers/yfinance_fetcher.py       # 标记 deprecated + 仅代理模式
backend/app/fetchers/china_market.py           # akshare 降级: 期货→Stooq 商品ETF; 指数历史→mootdx; HK/US历史→Stooq
backend/app/services/market_service.py         # _route_us_stooq(); get_global_indices() 改链路
backend/app/services/market_trends.py          # detect_market_regime() 多市场; compute_sector_momentum() 改用 sector_fetcher
backend/app/services/pool_manager.py           # regime cache 改为 dict[str,str]
backend/app/routers/analysis.py                # 4 个端点增加/使用 market 参数
backend/app/routers/market.py                  # search 增加 market 参数
backend/app/routers/portfolio.py               # design-async 增加 market 参数
backend/app/services/strategy_design.py        # generate_enhanced_design 增加 market 参数
backend/app/analysis/prompts/v1/general_analyst.md  # 改为市场动态 prompt

# ── 前端 (3个) ──
frontend/src/components/market/MarketReport.vue     # 传 marketTab 到 API
frontend/src/components/market/AiAdvisor.vue        # 传 marketTab + context.market
frontend/src/components/market/SectorAnalysis.vue   # LLM 分析传 market
frontend/src/views/DashboardAiTools.vue             # designAsync 传 market
```

### 10.3 无需修改（已有足够功能）

```
stooq_fetcher.py            # 功能完整
twelvedata_fetcher.py        # 功能完整
finnhub_fetcher.py           # 功能完整
# china_market.py 已移入 10.2 修改列表（akshare 降级修补）
source_registry.py           # 熔断器可直接复用
news_fetcher.py              # 国际新闻源可直接用
sector_fetcher.py            # A股板块功能完整，其他市场返回空
```

---

## 11. 验收标准

### 11.1 数据源替换（阶段一完成后）

- ✅ **[自动化]** `get_market_realtime("US", ["SPY", "QQQ"])` 通过 Stooq 返回有效价格
- ✅ **[自动化]** `get_market_history("US", "SPY", "daily")` 返回 ≥ 20 条日线
- ✅ **[自动化]** `get_global_indices()` 中"美股"组包含标普/纳指/道指且 `available=True`
- ✅ **[手动]** 断开 Stooq 网络后，美股请求通过 Twelve Data 或 Finnhub 返回数据
- ✅ **[自动化]** `verify_e2e.py` 全 PASS（含新增美股/港股测试）

### 11.2 市场感知（阶段二/三完成后）

- ✅ **[手动]** Tab = "港股" → 点"生成市场研判" → 报告内容以恒生指数为主
- ✅ **[手动]** Tab = "美股" → AI 顾问问"今天大盘怎么样" → 回答标普/纳指走势
- ✅ **[手动]** Tab = "A股" → 组合设计正常返回三套方案
- ✅ **[手动]** Tab = "港股" → 组合设计返回 `{"status": "unsupported", "message": "..."}`
- ✅ **[手动]** Tab = "全球" → 行情研判覆盖全球主要指数
- ✅ **[手动]** Tab 快速切换 → 旧 SSE 被取消，新请求正常开始，无 500 错误
- ✅ **[自动化]** 前端加载状态正常，无白屏/JS 错误
- ✅ **[自动化]** 后端日志无新增 WARNING/ERROR 级异常

### 11.3 边界情况

- ✅ **[手动]** 美股非交易时段 → Stooq 返回前一交易日数据
- ✅ **[手动]** 全部数据源不可用 → 各端点返回结构化空值 + LLM 说明"暂无有效数据"
- ✅ **[手动]** 港股 Tab 做板块分析 → 提示"该市场暂无板块分析数据"
- ✅ **[自动化]** 港股 Tab 做组合设计 → API 返回 `status: unsupported`

### 11.4 akshare 降级验收（阶段零完成后）

- ✅ **[手动]** 断开 akshare 网络（或 mock 其超时）后：
  - ✅ 期货/商品行情仍通过 Stooq 商品ETF返回数据
  - ✅ 指数历史K线仍通过 mootdx/Sina 返回数据
  - ✅ 港股/US历史K线仍通过 Stooq 返回数据
  - ✅ 板块动量/市态判断仍通过 levistock 返回数据
  - ✅ ETF 候选池仍能正常生成（Sina 列表 + gtimg 补充）
  - ✅ 组合设计仍能正常运行
- ✅ **[自动化]** `verify_e2e.py` 全 PASS（含新增降级用例）

---

> **下一步**：此 v3 文档通过最终 Review 后，按阶段顺序实施。每个阶段完成后跑对应验收测试，方可进入下一阶段。
