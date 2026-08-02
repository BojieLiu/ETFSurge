# v6 架构迁移计划：数据管道聚合（MarketDataHub 统一入口）

> 生成日期: 2026-07-31 | 版本: v6.2-实施标准（第 2 轮 review 修订）
> 范围: 将新闻/政策、板块/基本面/行情历史、实时行情/指数/商品、因子原始数据等多条取数链路聚合到 `MarketDataHub` 单一入口
> 约束: 本文件为实施规格（非代码）。每 Phase 独立 commit，实施前逐 Phase 评审并通过验证标准。

---

## 0. 当前状态（Phase 33 重命名已提交并推送，`62904e2`/`72b85b6` 后）

**已完成的重命名（已提交 `62904e2`，随后的 38 项存量测试失败也已修复并提交 `7ccb71d`）**
- `pool_manager.py` 已删除；原 `PoolManager`（1131 行）整体迁入 `backend/app/services/market_data_hub.py`，现为 `class MarketDataHub`（L85），单例 `market_data_hub = MarketDataHub()`（L1131）。
- 源码中 `from ..services.pool_manager import pool_manager` 已无真实 import；残留仅为注释/docstring（`allocation_engine.py:416`、`analysis.py:72/247`、`llm_context.py:28`、`portfolio_service.py:423/671/678`、`strategy_design.py:4/128/320`、`task_manager.py:8/430`）。
- 测试部分迁移：`pool_manager` 目前仅出现在测试文件的 docstring/注释/测试方法名中（无 `.pool_manager.` mock 路径）；`test_s5_remaining.py` 的 `pool_manager` 断言是**功能断言**（验证模块已删除），必须保留。Phase 0 只清理 docstring 文案。

**Hub ↔ market_service 关系（重要更正）**
- `market_service.py:989` **已**懒导入 hub：`from .market_data_hub import market_data_hub`，且 L990 正确调用 `market_data_hub.get_kline_rows(symbol, max_age=300)`，**无 NameError、无 bug**。
- 结论：采用「hub 委托 market_service + 双方均懒导入」模式，无导入期循环，计划可行。market_service 作为内部 provider 已被 hub 反向引用，符合设计。

**Hub 已具备的能力**
- `get_news()`（L1107）/ `refresh_news()`（L1115，合并 headlines+macro 入单一无标签缓存）/ `get_index_realtime()`（L957）/ `get_pool` / `get_kline` / `get_kline_rows` / `get_factor_matrix` / `get_sector_momentum` / `get_sector_heat` / `get_hot_plates` / `get_market_regime` / `get_market_sentiment` / `refresh`。

**尚未聚合（本计划核心目标，见 §2 全量清单）**
- 新闻/政策、板块、基本面、行情历史：router/service/worker/factor 仍**直连** `fetchers.*`。
- 实时行情/指数/商品/搜索：`market_service` 被 router/service/task **直连**，hub 无对应委托方法。
- 因子原始数据：`factor_registry` 直连 `china_market.fetch_history`、`fundamentals_fetcher.fetch_advance_decline_ratio`。

---

## 1. 目标架构

```
         所有上层模块（router / service / worker / factor / task）
                          │ 只认 MarketDataHub
                          ▼
              ┌───────────────────────────────┐
              │        MarketDataHub          │
              │  (统一数据管道入口 / 单一真相源) │
              │  - 分类缓存 + TTL + 后台刷新中枢 │
              │  - 委托 market_service 取实时    │
              │  - 因子原始数据从自身缓存供给    │
              └───────┬───────────────┬───────┘
                      │               │
            ┌─────────▼────┐   ┌──────▼──────────┐
            │ market_service│  │  PoolManager 逻辑 │
            │(内部 provider)│  │ (已并入 hub)      │
            └─────────┬────┘   └──────┬──────────┘
                      │               │
                      ▼               ▼
              fetchers/* (china_market, global_markets,
              news_fetcher, sector_fetcher, levistock,
              fundamentals_fetcher, etf_scanner …)
```

**设计约束**
1. `MarketDataHub` 是**唯一**被上层模块导入的数据入口。
2. `market_service` 为**内部 provider**：保留实现，仅被 hub 引用；上层不得直接 import。
3. `fetchers/*` 仅被 hub 与 `market_service` 引用；上层模块禁止直接 import `fetchers`（探针除外，见 §3 例外）。
4. 因子计算与池刷新**共用同一份** K线/基本面缓存。
5. 缓存 TTL 与后台刷新由 hub 统一管理（§5）。

---

## 2. 全量聚合清单（实施时先 grep 复核；行号基于当前工作树）

> 范围：上层模块 = `routers/ services/ tasks/ factors/`（不含 `market_data_hub.py`/`market_service.py` 自身，`fetchers/` 内部互引、启动引导 `main.py` 除外）。

### 2.1 新闻 / 政策 → `hub.get_news_*`
| 文件:行 | 当前直连 | 目标方法 |
|--------|---------|---------|
| `routers/admin.py:111` | `news_fetcher.get_akshare_pool_stats` | `get_akshare_pool_stats()` |
| `routers/analysis.py:25` | `fetch_news_headlines, fetch_macro_news`（顶层 import） | `get_news_headlines()`/`get_news_macro()` |
| `routers/analysis.py:163` | 同上（函数内 live） | 同上 |
| `routers/analysis.py:286` | 同上 | 同上 |
| `routers/news.py:5` | `fetch_news_headlines` | `get_news_headlines()` |
| `routers/ws.py:93` | `fetch_news_headlines` | `get_news_headlines()` |
| `services/llm_context.py:95` | `fetch_news_headlines, fetch_macro_news` | `get_news_headlines()`/`get_news_macro()` |
| `services/market_router.py:159` | `fetch_news_headlines, fetch_macro_news, fetch_global_news` | `get_news_headlines()`/`get_news_macro()`/`get_news_global()` |
| `services/portfolio_service.py:14` | `fetch_news_headlines, fetch_macro_news` | 同上 |
| `tasks/news_refresh.py:9` | `fetch_news_headlines` | `refresh_news()` |
| `tasks/report_worker.py:40` | `fetch_news_headlines, fetch_macro_news` | `get_news_headlines()`/`get_news_macro()` |

### 2.2 板块 → `hub.get_sector_*`（hub 已有部分，补齐）
| 文件:行 | 当前直连 | 目标方法 |
|--------|---------|---------|
| `routers/analysis.py:26` | `sector_fetcher` | `get_sector_momentum()`/`get_hot_plates()`（hub 已有） |
| `routers/market.py:21` | `sector_fetcher` | 同上 |
| `services/market_router.py:194` | `sector_fetcher.fetch_industry_sectors, fetch_concept_sectors` | `get_sector_industry()`/`get_sector_concept()`（新增） |

### 2.3 基本面 / 行情历史 → `hub.get_*` / `hub.get_kline_rows`
| 文件:行 | 当前直连 | 目标方法 |
|--------|---------|---------|
| `routers/analysis.py:30` | `fundamentals_fetcher.fetch_fund_flow, fetch_hist_avg_volume` | `get_fund_flow()`/`get_hist_avg_volume()`（新增） |
| `services/macro_state.py:186` | `fundamentals_fetcher.fetch_market_sentiment` | `get_market_sentiment()`（hub 已有） |
| `services/portfolio_service.py:13` | `fundamentals_fetcher.fetch_fundamentals` | `get_fundamentals()` |
| `services/portfolio_service.py:11` | `china_market.fetch_a_stock_batch/fetch_fund_nav/fetch_hk_stock_realtime/fetch_index_realtime` | `get_realtime()`/`get_fund_nav()`/`get_realtime()`/`get_index_realtime()` |
| `services/portfolio_service.py:12` | `global_markets_fetcher.fetch_us_etf_realtime` | `get_realtime(asset_type="US")` |
| `services/portfolio_service.py:706` | `china_market.fetch_index_realtime` | `get_index_realtime()` |
| `services/strategy_design.py:286` | `fundamentals_fetcher.fetch_fund_flow` | `get_fund_flow()` |
| `services/market_trends.py:348` | `china_market.fetch_history` | `get_kline_rows()`（含 fallback） |
| `factors/factor_registry.py:516` | `fundamentals_fetcher.fetch_advance_decline_ratio` | `get_advance_decline()`（新增，缓存） |
| `factors/factor_registry.py:807` | `china_market.fetch_history` | `get_kline_rows()`（含 fallback） |

### 2.4 实时行情 / 指数 / 商品 / 搜索 → `hub` 委托 `market_service`
| 文件:行 | 当前直连 | 目标方法 |
|--------|---------|---------|
| `routers/analysis.py:19`（顶层） | `market_service` 多方法 | `get_realtime*` |
| `routers/analysis.py:162` | `get_all_realtime, get_indices, get_commodities` | `get_all_realtime()`/`get_global_indices()`/`get_commodities()` |
| `routers/market.py:10`（顶层）, `:18`(levistock) | `market_service`/`levistock_fetcher` | `get_realtime*`/`get_commodities()`/`search_*` |
| `services/llm_context.py:85` | `market_service.get_all_realtime` | `get_all_realtime()` |
| `services/llm_context.py:110` | `market_service.get_commodities` | `get_commodities()` |
| `services/market_router.py:31,32,73,112,126` | `market_service.get_indices/get_global_indices/get_all_realtime/get_history` | `get_global_indices()`/`get_all_realtime()`/`get_history()` |
| `services/market_router.py:83,97,134` | `china_market/global_markets_fetcher`（港股/全球实时） | `get_realtime()`（hub 委托 market_service） |
| `services/portfolio_service.py:18,674` | `market_service.get_history/get_indices/get_commodities` | `get_history()`/`get_global_indices()`/`get_commodities()` |
| `tasks/market_refresh.py:9` | `market_service.get_portfolio_realtime` | `get_portfolio_realtime()` |
| `tasks/report_worker.py:39,67` | `market_service.get_all_realtime/get_indices/get_commodities/get_history` | `get_all_realtime()`/`get_global_indices()`/`get_commodities()`/`get_history()` |

> **例外（不纳入聚合，DoD 豁免）**
> - `main.py:202` `etf_scanner` 启动引导扫描 —— 属 lifespan bootstrap，保留。
> - `monitor/probes.py:18,26,34,65,85` 实时探针 / `get_akshare_pool_stats` —— 探针需**直连数据源**以检测源可用性，经 hub 缓存会失真；保留直连并加注释说明。但 `probes.py:85` 的 `get_akshare_pool_stats` 若仅为统计展示，可改 `hub.get_akshare_pool_stats()`（见 2.1）。

---

## 3. 分阶段实施

> 每 Phase 独立 commit，可单独 revert。每步先 `pytest` 再 `verify_e2e`。

### Phase 0 — 重命名收尾（baseline 清理）
**目标**：清理重命名残留，确保测试全绿、baseline 干净。
- 将 §0 所列源码注释/docstring 中的 `pool_manager` 改为 `market_data_hub`（纯注释，无逻辑变更）。
- 清理测试文件中 `pool_manager` 字符串（仅 docstring/注释，无 mock 路径需改）。
- 断言：`git grep -nE "from .*pool_manager import|import pool_manager" backend/app` 仅匹配 `market_data_hub.py` 内部（若有）。
- **验证**：`cd backend && python -m pytest` 全绿；`python scripts/verify_e2e.py` 全 PASS。
- **回滚**：`git checkout` 注释/测试改动。

### Phase 1 — 新闻/政策聚合（最高优先）
**目标**：新闻/政策成为 hub 单一取数点；`refresh_news` 支持分类缓存；请求路径不再 live fetch。
- **重定义 `refresh_news()`（修复 B2）**：分别 fetch headlines/macro/global 并存入**带标签**缓存桶（stock 新闻按标的单独取，见下）：
  ```python
  async def refresh_news(self):
      headlines = fetch_news_headlines() or []
      macro = fetch_macro_news() or []
      global_news = fetch_global_news() or []      # news_fetcher.py:369 已存在
      self._news = {"headlines": headlines, "macro": macro, "global": global_news}
      self._news_ts = time.time()
  def _news_bucket(self, key):
      if self._news and (time.time() - self._news_ts) < self.NEWS_TTL:
          return self._news.get(key, [])
      return []   # 缓存 miss 由调用方降级 live 或触发 refresh
  def get_news_headlines(self): return self._news_bucket("headlines")
  def get_news_macro(self): return self._news_bucket("macro")
  def get_news_global(self): return self._news_bucket("global")
  def get_news_stock(self, symbol): return fetch_stock_news(symbol) or []  # news_fetcher.py:402，按标的
  def get_akshare_pool_stats(self): return fetch_akshare_pool_stats()  # 直接委托
  def get_news(self): return sum(self._news.values(), []) if self._news else []
  ```
- 将 §2.1 全部直连点改为调用上述方法，删除对应 `from ..fetchers.news_fetcher import ...`。
- `main.py` 后台循环新增 news 刷新，周期 120s（与 regime/sentiment 同批）。
- **测试**：新增 `tests/test_market_data_hub_news.py` —— (a) 直连路由到 hub；(b) `get_news_headlines` 仅 headlines、`get_news_macro` 仅 macro（不串味）；(c) `get_news_global` 来自 global 桶、`get_news_stock(symbol)` 透传 `fetch_stock_news(symbol)`；(d) TTL 内命中缓存不触发 `fetch_*`；(e) `refresh_news` 调 `fetch_news_headlines`+`fetch_macro_news`+`fetch_global_news` 各一次（stock 按标的单独取）。现有 news 路由测试改为 `mock.patch("app.services.market_data_hub.market_data_hub.get_news_headlines")`。
- **验证**：`pytest`；`verify_e2e.py`（news 用例 PASS）；`grep` 终检 §2.1 清单行号不再含 `news_fetcher` 直连（hub/market_service 除外）。
- **回滚**：按文件独立 commit。

### Phase 2 — 板块 / 基本面 / 行情历史聚合
**目标**：板块、基本面、K线历史经 hub 取数，消除散落直连。
- Hub 新增方法（按需懒导入对应 fetcher，或复用已有）：`get_sector_industry()` / `get_sector_concept()`（封装 `sector_fetcher.fetch_industry_sectors`/`fetch_concept_sectors`）；`get_fund_flow()` / `get_hist_avg_volume()`（封装 `fundamentals_fetcher`）；`get_fundamentals()` / `get_fund_nav()`（委托 market_service 或 fundamentals_fetcher）；`get_advance_decline()`（封装 `fundamentals_fetcher.fetch_advance_decline_ratio`，缓存）。
- `get_kline_rows(sym)` 已存在（L860）但缓存 miss 返回 `None`（L874）：factor_registry / market_trends 调用 `china_market.fetch_history` 的标的常超出池缓存，**必须加 fallback**（不新增子类，直接在原方法内追加降级）：
  ```python
  def get_kline_rows(self, symbol, max_age=300):
      rows = <复用现有缓存查找逻辑，原 L860-L874 命中路径>
      if rows is not None:
          return rows
      from ..fetchers.china_market import fetch_history   # 降级 live
      return fetch_history(symbol, "A", "daily")
  ```
- 将 §2.2 / §2.3 全部直连点改为 hub 方法，删除对应 `fetchers.*` import（macro_state.py:186 的 `get_market_sentiment` 直接用 hub 已有方法）。
- **测试**：新增 `tests/test_market_data_hub_data.py` —— 各新增方法正确委托；`get_kline_rows` 缓存命中与 fallback 两条路径；因子值改造前后一致（fixture 回归）。
- **验证**：`pytest`；`verify_e2e.py`（design 用例三套方案 + 正确 regime）。
- **回滚**：独立 commit。

### Phase 3 — 实时行情/指数/商品/搜索聚合（最大）
**目标**：`market_service` 不再被上层直连；修复 `market_service.py:989` 的 `pm` NameError。
- Hub 新增委托方法（方法内**懒导入** `market_service`，双方懒导入无循环）：
  `get_realtime` / `get_all_realtime` / `get_asset_realtime` / `get_portfolio_realtime` / `get_global_indices` / `get_commodities` / `get_indices_meta` / `get_history` / `get_fundamentals` / `search_etf` / `search_indices`。
  实现模板：`def get_realtime(self, symbols, asset_type="A"): from ..services.market_service import get_realtime_batch; return get_realtime_batch(symbols, asset_type)`
- `market_service.py:989` 已正确懒导入并调用 `market_data_hub.get_kline_rows`（无 bug），Phase 3 **无需修复**该处；本 Phase 仅新增 hub→market_service 委托方法，并移除上层对 `market_service` 的直连 import。
- 将 §2.4 全部直连点（`routers/analysis.py:19/162`、`routers/market.py:10/18`、`llm_context.py:85/110`、`market_router.py:31/32/73/83/97/112/126/134`、`portfolio_service.py:18/674`、`market_refresh.py:9`、`report_worker.py:39/67`）改为 hub 方法，删除 `from ..services.market_service import ...`。
- `market_router.py` 经此 Phase 后成为 hub 的纯委托层（其内部可保留聚合逻辑，但取数全部经 hub）。
- **测试**：新增 `tests/test_market_data_hub_realtime.py` —— hub 方法正确透传参数给 `market_service`（mock `market_service`）；`routers/market.py`/`analysis.py` 路由测试改为断言 hub 调用；`market_service` 单测保持。
- **验证**：`pytest`；`verify_e2e.py`；`cd frontend && npm run build` + 行情页走查。
- **回滚**：独立 commit（router 与 market_service 修复成对 revert）。

### Phase 4 — 因子原始数据收尾
**目标**：`factor_registry.py` 完全经 hub 取数，无 fetcher 直连。
- 确认 §2.3 中 `factor_registry.py:516`（`get_advance_decline`）、`:807`（`get_kline_rows` + fallback）已在 Phase 2/3 完成；本 Phase 仅做收尾与回归。
- 扫描 `factor_registry.py` 是否还有其他 `source_registry`/fetcher 直连，若有同样汇入 hub。
- **测试**：`tests/test_factor_integration.py` 断言 hub 调用；改造前后同标的因子分一致回归。
- **验证**：`pytest`；`verify_e2e.py`。

### Phase 5 — 刷新中枢 / 文档 / 终检
- `main.py` 后台循环统一：sector(60s) + regime/sentiment(120s) + news(120s) 全部经 hub。
- `AGENTS.md` 关键路径：`pool_manager` → `market_data_hub`。
- 若对外字段变化（预期不变），补/更新 `api-contracts/`。
- **DoD 全量 grep 终检**（见 §9 修正后命令）。
- **验证**：`npm run build` + `verify_e2e.py` + `pytest` + `python scripts/data_health_check.py`。

---

## 4. Hub 接口契约（新增/委托方法签名）

```python
# 新闻/政策（Phase 1）
def get_news(self) -> list[dict]: ...                    # 合并四桶，向后兼容
def get_news_headlines(self) -> list[dict]: ...          # 仅 headlines
def get_news_macro(self) -> list[dict]: ...              # 仅 macro
def get_news_global(self) -> list[dict]: ...             # 仅 global
def get_news_stock(self, symbol) -> list[dict]: ...      # 按标的，委托 fetch_stock_news
def get_akshare_pool_stats(self) -> dict: ...            # 委托 news_fetcher
async def refresh_news(self) -> None: ...                # 四桶分别 fetch 入缓存

# 板块（Phase 2，部分已有）
def get_sector_industry(self) -> list[dict]: ...         # 新增
def get_sector_concept(self) -> list[dict]: ...          # 新增

# 基本面 / 历史（Phase 2）
def get_fund_flow(self, *a, **k) -> Any: ...             # 新增（委托 fundamentals_fetcher）
def get_hist_avg_volume(self, *a, **k) -> Any: ...       # 新增
def get_fundamentals(self, symbol) -> dict: ...          # 委托 market_service/fundamentals_fetcher
def get_fund_nav(self, *a, **k) -> Any: ...              # 新增
def get_advance_decline(self) -> float: ...              # 新增（缓存）
def get_kline_rows(self, symbol, max_age=300): ...       # 已有 + fallback fetch_history

# 实时/指数/商品/搜索（Phase 3，委托 market_service）
def get_realtime(self, symbols, asset_type="A") -> list[dict]: ...
def get_all_realtime(self) -> list[dict]: ...
def get_asset_realtime(self, symbol, asset_type) -> dict: ...
def get_portfolio_realtime(self, holdings) -> list[dict]: ...
def get_global_indices(self) -> list[dict]: ...
def get_commodities(self) -> list[dict]: ...
def get_indices_meta(self) -> list[dict]: ...
def get_history(self, *a, **k) -> Any: ...
def search_etf(self, q) -> list[dict]: ...
def search_indices(self, q) -> list[dict]: ...
```

**向后兼容**：`get_news()` 合并结构不变；`get_pool`/`get_kline`/`get_factor_matrix`/`get_index_realtime`/`get_market_regime`/`get_market_sentiment`/`get_sector_momentum`/`get_hot_plates`/`get_sector_heat` 签名不变。新增方法为纯增量。

---

## 5. 缓存与刷新中枢

| 数据 | 缓存位置 | TTL | 刷新触发 |
|------|---------|-----|---------|
| 新闻/政策 | `MarketDataHub._news`（四桶） | 120s (`NEWS_TTL`) | `refresh_news()`（后台 120s + miss 降级 live） |
| 指数实时 | hub 内部缓存 | `get_index_realtime` 既有逻辑 | sector 循环 / 按需 |
| 池/K线/因子 | hub 内部（`refresh()`） | 全量刷新周期 | `_refresh_impl` |
| 板块/基本面/涨跌比 | hub 新增缓存或委托 fetcher | 随方法 | 首次调用 / 后台循环 |
| 实时个股/商品/搜索 | 委托 `market_service`（其自有策略） | 沿用 market_service | 调用即取（高时效，不经 hub 长缓存） |

**原则**：高时效数据走 `market_service` 实时取；低频/批量数据走 hub 缓存 + 后台刷新，保证单源真相与一致性。

---

## 6. 测试策略

1. **新增单测**（每 Phase 对应）：`test_market_data_hub_news.py` / `test_market_data_hub_data.py` / `test_market_data_hub_realtime.py` / `test_market_data_hub_factors.py`。
2. **改造现有测试**：router/service 测试改为 `mock.patch("app.services.market_data_hub.market_data_hub.<method>")` 断言 hub 调用；无 `.pool_manager.` mock 路径需改（已确认）。
3. **外部依赖必须 mock**：`news_fetcher`/`china_market`/`market_service`/`fundamentals_fetcher`/`sector_fetcher` 在单测中全部 mock，不依赖真实网络/DB（AGENTS.md）。
4. **回归**：因子值、行情展示字段改造前后一致（fixture 对比）。
5. **运行**：`cd backend && python -m pytest`（`asyncio_mode=auto`）。

---

## 7. 验证标准

每 Phase 结束必须全绿：
- `cd backend && python -m pytest` 全部通过。
- `cd backend && python scripts/verify_e2e.py` 输出全 `[PASS]`。
- Phase 3 后：`cd frontend && npm run build` 无编译错误。
- Phase 5 后：`python scripts/data_health_check.py` 全绿。

---

## 8. 回滚策略

- 每 Phase 独立 commit；`git revert <phase-commit>` 单 Phase 回退。
- Phase 0/1 纯路由替换，revert 即恢复直连，无数据风险。
- Phase 2/3 涉及 hub 新增方法 + market_service 修复；revert 时 router 需同步 revert 到原直连（因独立 commit 一一对应，可成对 revert）。
- 不删除 `market_service` 实现（仅降级为内部 provider），保留回退余地。

---

## 9. 完成定义（DoD，修正 grep 模式）

全部满足方可宣布聚合完成：
1. **上层无 fetchers 直连**（含绝对 import）：
   ```
   grep -rnE "from \.\.fetchers|from app\.fetchers|from \.fetchers" \
     backend/app/routers backend/app/services backend/app/tasks backend/app/factors \
     | grep -vE "market_data_hub.py|market_service.py"
   ```
   结果为空（`fetchers/` 内部互引与 `main.py` 引导不在范围内）。
2. **上层无 market_service 直连**（含绝对 import；`market_data_hub.py` 内部委托除外）：
   ```
   grep -rnE "from \.\.services\.market_service|from app\.services\.market_service|from \.market_service" \
     backend/app/routers backend/app/services backend/app/tasks \
     | grep -vE "market_data_hub.py"
   ```
   结果为空。
3. `factors/factor_registry.py` 无 `china_market.fetch_history` / `fundamentals_fetcher.fetch_advance_decline_ratio` 直连。
4. `pytest` 全绿；`verify_e2e.py` 全 PASS；`npm run build` 通过；`data_health_check.py` 全绿。
5. 新闻、实时、因子原始数据各自**仅 hub 一处取数 + 统一 TTL**（单源真相）。
6. `monitor/probes.py` 仍直连数据源（豁免，已加注释）。

---

## 10. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| 循环 import（hub ↔ market_service） | 低 | 双方均**懒导入**；Phase 3 后立即 `pytest` 验证 |
| 新闻缓存 TTL 内 stale | 低 | miss 降级 live；后台 120s 刷新 |
| 因子值因改用 `get_kline_rows` 漂移 | 中 | Phase 2/4 fixture 回归断言一致；`get_kline_rows` 保留 `fetch_history` fallback 保证数据同源 |
| `get_news_headlines` 串入 macro 数据 | 中 | Phase 1 `refresh_news` 分桶存储，方法按桶返回（B2 修复） |
| `get_news_stock` 漏传 symbol 致 TypeError | 中 | Phase 1 明确 `get_news_stock(symbol)` 透传 `fetch_stock_news(symbol)` |
| 测试 mock 路径遗漏 | 低 | 已确认无 `.pool_manager.` 路径；router 测试改断言 hub |
| 上层遗漏直连点 | 中 | §2 全量清单 + Phase 5 DoD grep 终检 |
| 探针被误聚合致健康检查失真 | 低 | §2 例外条款明确豁免 `monitor/probes.py` |

---

## 11. 时间线（估算）

| Phase | 内容 | 估算 |
|-------|------|------|
| Phase 0 | 重命名收尾 | ~0.5h |
| Phase 1 | 新闻/政策聚合 + refresh_news 分桶 | ~1.5h |
| Phase 2 | 板块/基本面/历史聚合 | ~1.5h |
| Phase 3 | 实时/指数/商品/搜索聚合（market_service:989 已修，无需重复） | ~2h |
| Phase 4 | 因子原始数据收尾 | ~0.5h |
| Phase 5 | 刷新中枢/文档/DoD 终检 | ~0.5h |
| **合计** | **数据管道聚合** | **~7-8h** |

> 注：Phase 33 重命名 + 存量测试修复均已提交（`62904e2`/`72b85b6`/`7ccb71d`）；本计划在此基线上实施真正的入口聚合。
