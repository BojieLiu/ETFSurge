# v6 架构迁移计划：数据管道聚合（MarketDataHub 统一入口）

> 生成日期: 2026-07-31 | 版本: v6.1-实施标准草案
> 范围: 将新闻/政策、实时行情/指数/商品、因子原始数据等多条取数链路聚合到 `MarketDataHub` 单一入口
> 约束: 本文件为实施规格（非代码）。实施前需逐 Phase 评审并通过验证标准。

---

## 0. 当前状态（基于未提交工作树，Phase 31 重命名后）

**已完成的重命名（脚手架，未提交）**
- `pool_manager.py` 已删除；原 `PoolManager`（1131 行）整体迁入 `backend/app/services/market_data_hub.py`，现为 `class MarketDataHub`（L85），单例 `market_data_hub = MarketDataHub()`（L1131）。
- 源码中 `from ..services.pool_manager import pool_manager` 已无真实 import；残留仅为注释/docstring（`allocation_engine.py:416`、`analysis.py:72/247`、`llm_context.py:28`、`portfolio_service.py:423/671/678`、`strategy_design.py:4/128/320`、`task_manager.py:8/430`）。
- `market_service.py:989` 已改为 `from .market_data_hub import market_data_hub`，无悬空 import。
- 测试部分迁移：`test_pool_manager.py` 等已改，但仍有 8 个测试文件含 `pool_manager` 字符串（见 Phase 0）。

**Hub 已具备的能力**
- `get_news()`（L1107）：返回缓存新闻，**120s TTL**；`refresh_news()`（L1115）合并 `fetch_news_headlines()` + `fetch_macro_news()` 入 `_news_cache`。
- `get_index_realtime()`（L957）：全球指数实时（缓存）。
- `get_pool` / `get_kline` / `get_factor_matrix` / `get_sector_*` / `get_market_regime` / `get_market_sentiment` / `refresh`（全市场刷新）。

**尚未聚合（本计划核心目标）**
- 新闻/政策：router/service/worker 仍**直连** `news_fetcher`（见 §2 清单）。
- 实时行情/指数/商品/基本面/搜索：`market_service` 被 router 直连，`MarketDataHub` 无对应委托方法。
- 因子原始数据：`factor_registry` 直连 `china_market.fetch_history`、`fundamentals_fetcher.fetch_advance_decline_ratio`，与 hub 池刷新重复取数。

---

## 1. 目标架构

```
                 所有调用方（router / service / worker / factor）
                                │ 只认 MarketDataHub
                                ▼
                    ┌───────────────────────────────┐
                    │        MarketDataHub          │
                    │  (统一数据管道入口 / 单一真相源) │
                    │  - 缓存 + TTL + 后台刷新中枢    │
                    │  - 委托 market_service 取实时   │
                    │  - 因子原始数据从自身缓存供给   │
                    └───────┬───────────────┬───────┘
                            │               │
                  ┌─────────▼───┐    ┌──────▼──────────┐
                  │ market_service│   │  PoolManager 逻辑 │
                  │ (内部 provider)│   │ (已并入 hub)      │
                  │ 实时/基本面/搜索│   │ 池/K线/因子/市态  │
                  └─────────┬───┘    └──────┬──────────┘
                            │               │
                            ▼               ▼
                    fetchers/* (china_market, global_markets,
                    news_fetcher, fundamentals_fetcher …)
```

**设计约束**
1. `MarketDataHub` 是**唯一**被 router/service/worker/factor 导入的数据入口。
2. `market_service` 降级为**内部 provider**：保留实现，仅被 hub 引用，router 不再直接 import。
3. `fetchers/*` 仅被 hub 与 `market_service` 引用；上层模块禁止直接 import `fetchers`。
4. 因子计算与池刷新**共用同一份** K线/基本面缓存，消除重复取数。
5. 所有缓存 TTL 与后台刷新节奏由 hub 统一管理（§5）。

---

## 2. 聚合范围清单（精确位置，实施时先 grep 复核）

### 2.1 新闻/政策直连（应改走 `market_data_hub.get_news_*`）
| 文件:行 | 当前直连 | 改后 |
|--------|---------|------|
| `routers/analysis.py:25,163,169-170` | `fetch_news_headlines`/`fetch_macro_news` | `get_news_headlines()` / `get_news_macro()` |
| `routers/analysis.py:286-289,528-530,563-565` | 同上（3 处） | 同上 |
| `routers/news.py:5-18` | `fetch_news_headlines` | `get_news_headlines()` |
| `routers/ws.py:93-94` | `fetch_news_headlines` | `get_news_headlines()` |
| `services/llm_context.py:95-96` | `fetch_news_headlines` | `get_news_headlines()` |
| `services/market_router.py:159-163` | `fetch_news_headlines`/`fetch_macro_news`/`fetch_global_news` | `get_news_headlines()` / `get_news_macro()` / `get_news_global()` |
| `services/portfolio_service.py:14` | `fetch_news_headlines` | `get_news_headlines()` |
| `fetchers/benchmark_stocks.py:87` | `fetch_stock_news` | `get_news_stock()` |
| `tasks/news_refresh.py:9` | `fetch_news_headlines` | `refresh_news()`（hub 内部） |

### 2.2 实时行情/指数/商品/基本面/搜索直连（应改走 hub 委托方法）
| 文件:行 | 当前直连 | 改后 |
|--------|---------|------|
| `routers/market.py:11-13,36,49,174` | `market_service.get_all_realtime` / `get_realtime_batch` / `get_indices_meta` / `get_fundamentals` / `search_*` | `market_data_hub.get_realtime*` |
| `routers/analysis.py:162` | `market_service.get_all_realtime` / `get_indices` / `get_commodities` | `get_all_realtime()` / `get_global_indices()` / `get_commodities()` |
| `monitor/probes.py:18-65` | `china_market._mootdx/_sina/_tencent/_em_hk_realtime` | 评估：经 `get_realtime()` 或保留探针（§3 Phase 4） |

### 2.3 因子原始数据直连（应改走 hub 缓存）
| 文件:行 | 当前直连 | 改后 |
|--------|---------|------|
| `factors/factor_registry.py:516` | `fundamentals_fetcher.fetch_advance_decline_ratio` | `get_advance_decline()` |
| `factors/factor_registry.py:807` | `china_market.fetch_history` | `get_kline(sym)`（hub 已缓存） |

---

## 3. 分阶段实施

> 每 Phase 独立 commit，可单独 revert。每步先 `pytest` 再 `verify_e2e`。

### Phase 0 — 重命名收尾（baseline 清理）
**目标**：消除重命名残留，确保测试全绿、baseline 干净。
- 将 §0 所列源码注释中的 `pool_manager` 改为 `market_data_hub`（纯注释，无逻辑变更）。
- 完成测试 mock 路径迁移：将 8 个仍含 `pool_manager` 的测试文件中 mock 路径 `app.services.pool_manager.pool_manager.*` → `app.services.market_data_hub.market_data_hub.*`，patch 目标与方法签名不变。
- 断言：`git grep -nE "from .*pool_manager import|import pool_manager" backend/app` 仅匹配 `market_data_hub.py` 内部（若有）。
- **验证**：`cd backend && python -m pytest` 全绿；`python scripts/verify_e2e.py` 全 PASS。
- **回滚**：`git checkout` 注释与测试改动。

### Phase 1 — 新闻/政策链聚合（最高优先）
**目标**：新闻/政策成为 hub 单一取数点，请求路径不再 live fetch。
- Hub 新增细分方法（均从 `_news_cache` 取，不二次 fetch）：
  - `get_news_headlines() -> list[dict]`
  - `get_news_macro() -> list[dict]`
  - `get_news_global() -> list[dict]`（如 `fetch_global_news` 存在）
  - `get_news_stock() -> list[dict]`（封装 `fetch_stock_news`）
  - `get_news() -> list[dict]` 保持返回合并列表（向后兼容）。
- 将 §2.1 全部直连点改为调用上述方法，删除对应 `from ..fetchers.news_fetcher import ...`。
- `main.py` 后台循环新增 news 刷新：`await asyncio.wait_for(market_data_hub.refresh_news(), timeout=15)`，周期 120s（与 regime/sentiment 同批）。
- **Before→After 示例（analysis.py:163-170）**
  ```python
  # Before
  from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news
  news = await asyncio.to_thread(fetch_news_headlines)
  macro = await asyncio.to_thread(fetch_macro_news)
  # After
  from ..services.market_data_hub import market_data_hub
  news = market_data_hub.get_news_headlines()
  macro = market_data_hub.get_news_macro()
  ```
- **测试**：新增 `tests/test_market_data_hub_news.py` —— 验证 (a) 直连调用被路由到 hub；(b) `get_news_headlines`/`get_news_macro` 从同一缓存分离且 macro 已合并；(c) TTL 内命中缓存不触发 `fetch_*`；(d) `refresh_news` 调 `fetch_news_headlines`+`fetch_macro_news` 各一次。现有 news 路由测试改为断言 hub 调用（`mock.patch("app.services.market_data_hub.market_data_hub.get_news_headlines")`）。
- **验证**：`pytest`；`verify_e2e.py`（news 用例 PASS）；`grep -rn "news_fetcher" backend/app/routers backend/app/services/*(非hub) backend/app/tasks` 仅剩 hub 内部。
- **回滚**：按文件独立 commit，单文件 revert 即可。

### Phase 2 — 实时行情/指数/商品/基本面/搜索链聚合
**目标**：`market_service` 不再被 router 直连，全部经 hub 委托。
- Hub 新增委托方法（方法内**延迟导入** `market_service`，避免循环 import）：
  - `get_realtime(symbols, asset_type="A")`
  - `get_all_realtime()`
  - `get_asset_realtime(symbol, asset_type)`
  - `get_portfolio_realtime(holdings)`
  - `get_global_indices()`
  - `get_commodities()`
  - `get_indices_meta()`
  - `get_fundamentals(symbol)`
  - `search_etf(q)` / `search_indices(q)`（查询类，可选汇入）
  - 实现模板：`def get_realtime(self, symbols, asset_type="A"): from ..services.market_service import get_realtime_batch; return get_realtime_batch(symbols, asset_type)`
- `routers/market.py`、`routers/analysis.py:162` 改为调用 hub 方法，删除 `from ..services.market_service import ...`。
- `market_service` 定位降级为内部 provider：保留实现；**不得**反向 import hub（确认当前无此 import）。
- **测试**：新增 `tests/test_market_data_hub_realtime.py` —— hub 方法正确委托 `market_service`（mock `market_service` 函数，断言参数透传）；`routers/market.py` 路由测试改为断言 hub 调用。
- **验证**：`pytest`；`verify_e2e.py`；`cd frontend && npm run build` + 行情页走查（实时/指数/商品正常）。
- **回滚**：独立 commit。

### Phase 3 — 因子原始数据链聚合
**目标**：因子计算复用 hub 缓存，消除重复取数。
- Hub 新增 `get_advance_decline() -> float`（委托 `fundamentals_fetcher.fetch_advance_decline_ratio`，缓存）。
- `factor_registry.py:516`：`fetch_advance_decline_ratio` → `market_data_hub.get_advance_decline()`。
- `factor_registry.py:807`：`china_market.fetch_history(sym,...)` → `market_data_hub.get_kline(sym)`（hub 已缓存 K线；若 `get_kline` 返回结构需适配，在 hub 内做归一化，factor_registry 不改字段语义）。
- 若 `factor_registry` 还经 `source_registry` 取其他原始数据且 hub 可供给，同样汇入。
- **测试**：`tests/test_factor_integration.py` 改为断言 hub 调用；新增回归断言——改造前后同一标的因子分一致（用固定 fixture 对比）。
- **验证**：`pytest`；`verify_e2e.py`（design 用例：三套方案 + 正确 regime）。
- **回滚**：独立 commit。

### Phase 4 — 缓存/刷新中枢统一 + 探针
**目标**：刷新节奏全部由 hub 驱动，统一 TTL。
- `main.py` 后台循环统一：sector(60s) + regime/sentiment(120s) + news(120s) 全部经 hub 方法。
- `monitor/probes.py` 实时探针（`_mootdx/_sina/_tencent/_em_hk_realtime`）：评估改走 `market_data_hub.get_realtime()`；若探针需独立探测源健康（绕过 hub 缓存），保留直连并加注释说明。
- `benchmark_stocks.py` 同理评估。
- TTL 常量（如 `NEWS_TTL`）集中在 hub 并文档化；新增实时类 TTL 若需要。
- **验证**：`pytest`；`verify_e2e.py`；`python scripts/data_health_check.py` 全绿。

### Phase 5 — 文档/契约/收尾
- `AGENTS.md` 关键路径：`pool_manager` → `market_data_hub`（条目与示例）。
- 若对外字段变化（预期不变，仅内部路由），补/更新 `api-contracts/` 相关契约。
- 全量 grep 终检：
  - `grep -rn "from ..fetchers" backend/app/routers backend/app/services`（排除 `market_data_hub.py`/`market_service.py`）结果为空。
  - `grep -rn "from ..services.market_service import" backend/app/routers` 结果为空。
- **验证**：`npm run build` + `verify_e2e.py` + `pytest`。

---

## 4. Hub 接口契约（新增/委托方法签名）

```python
# 新闻/政策（§3 Phase 1）
def get_news(self) -> list[dict]: ...                       # 合并列表，向后兼容
def get_news_headlines(self) -> list[dict]: ...             # 来自 _news_cache
def get_news_macro(self) -> list[dict]: ...                 # 来自 _news_cache
def get_news_global(self) -> list[dict]: ...                # 来自 _news_cache
def get_news_stock(self) -> list[dict]: ...                 # 封装 fetch_stock_news
async def refresh_news(self) -> None: ...                   # 合并 headlines+macro+global 入缓存

# 实时/指数/商品/基本面/搜索（§3 Phase 2，委托 market_service）
def get_realtime(self, symbols, asset_type="A") -> list[dict]: ...
def get_all_realtime(self) -> list[dict]: ...
def get_asset_realtime(self, symbol, asset_type) -> dict: ...
def get_portfolio_realtime(self, holdings) -> list[dict]: ...
def get_global_indices(self) -> list[dict]: ...
def get_commodities(self) -> list[dict]: ...
def get_indices_meta(self) -> list[dict]: ...
def get_fundamentals(self, symbol) -> dict: ...
def search_etf(self, q) -> list[dict]: ...
def search_indices(self, q) -> list[dict]: ...

# 因子原始数据（§3 Phase 3）
def get_advance_decline(self) -> float: ...                 # 委托 fundamentals_fetcher，缓存
# get_kline(sym) 已存在，factor_registry 复用
```

**向后兼容**：`get_news()` 返回结构不变；`get_pool`/`get_kline`/`get_factor_matrix`/`get_index_realtime` 等既有方法签名不变。新增方法为纯增量，不影响现有调用方。

---

## 5. 缓存与刷新中枢

| 数据 | 缓存位置 | TTL | 刷新触发 |
|------|---------|-----|---------|
| 新闻/政策 | `MarketDataHub._news_cache` | 120s (`NEWS_TTL`) | `refresh_news()`（后台 120s 循环 + 缓存 miss 降级 live） |
| 指数实时 | hub 内部缓存 | 由 `get_index_realtime` 既有逻辑 | sector 循环 / 按需 |
| 池/K线/因子 | hub 内部（`refresh()`） | 全量刷新周期 | `_refresh_impl` |
| 实时个股/商品/基本面 | 委托 `market_service`（其自有缓存） | 沿用 `market_service` 现有策略 | 调用即取（实时性要求高，不经 hub 长缓存） |

**原则**：高时效数据（实时报价）走 `market_service` 实时取，不经 hub 长缓存；低频/批量数据（新闻、市态、因子）走 hub 缓存 + 后台刷新，保证单源真相与一致性。

---

## 6. 测试策略

1. **新增单测**（每 Phase 对应）：
   - `test_market_data_hub_news.py`：路由、缓存命中、TTL、macro 合并、refresh 调用次数。
   - `test_market_data_hub_realtime.py`：委托透传、参数正确。
   - `test_market_data_hub_factors.py`：因子复用 hub 缓存、改造前后因子值一致（fixture 回归）。
2. **改造现有测试**：将所有 `app.services.pool_manager.pool_manager.*` patch 路径改为 `app.services.market_data_hub.market_data_hub.*`；router 测试改为断言 hub 方法被调用（mock hub）。
3. **外部依赖必须 mock**：`news_fetcher`/`china_market`/`market_service`/`fundamentals_fetcher` 在单测中全部 mock，不依赖真实网络/DB（遵循 AGENTS.md）。
4. **运行**：`cd backend && python -m pytest`（asyncio_mode=auto）。

---

## 7. 验证标准

每 Phase 结束必须全绿：
- `cd backend && python -m pytest` —— 全部通过。
- `cd backend && python scripts/verify_e2e.py` —— 输出全 `[PASS]`（health / dataset / design_text / market_regime / news）。
- Phase 2 后额外：`cd frontend && npm run build` 无编译错误（pre-commit 门禁自动执行）。
- Phase 5 后额外：`python scripts/data_health_check.py` 全绿。

---

## 8. 回滚策略

- 每 Phase 独立 commit；回退单 Phase：`git revert <phase-commit>`。
- Phase 0/1 为纯路由替换，revert 即恢复直连，无数据风险。
- Phase 2/3 涉及 hub 新增方法；若回滚，router 需同步 revert 到 `market_service` 直连——因独立 commit 一一对应，可成对 revert。
- 不删除 `market_service` 实现（仅降级为内部 provider），保留回退余地。

---

## 9. 完成定义（DoD）

全部满足方可宣布聚合完成：
1. `grep -rn "from ..fetchers" backend/app/routers backend/app/services`（排除 `market_data_hub.py`/`market_service.py`）**结果为空**。
2. `grep -rn "from ..services.market_service import" backend/app/routers` **结果为空**（router 只认 hub）。
3. `factor_registry.py` 无 `china_market.fetch_history` / `fundamentals_fetcher.fetch_advance_decline_ratio` 直连。
4. `pytest` 全绿；`verify_e2e.py` 全 PASS；`npm run build` 通过；`data_health_check.py` 全绿。
5. 新闻、实时、因子原始数据各自**仅 hub 一处取数 + 统一 TTL**（单源真相）。

---

## 10. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| 循环 import（hub ↔ market_service） | 中 | hub 方法内**延迟导入** `market_service`；`market_service` 不反向 import hub；Phase 2 实施后立即 `pytest` 验证 |
| 新闻缓存 TTL 内 stale 导致展示旧闻 | 低 | 保留缓存 miss 降级 live；后台 120s 刷新；前端已有 loading/刷新机制 |
| 因子值因改用 `get_kline` 缓存而漂移 | 中 | Phase 3 加 fixture 回归断言，改造前后同标的因子分一致 |
| 实时行情走 hub 委托引入额外延迟 | 低 | 委托为直接函数调用，无额外 I/O；`market_service` 自身缓存不变 |
| 测试 mock 路径遗漏致 CI 失败 | 中 | Phase 0 先全量 `pytest -x`；mock 路径逐文件改 |
| router 遗漏直连点 | 中 | §2 清单 + Phase 5 全量 grep 终检 |

---

## 11. 时间线（估算）

| Phase | 内容 | 估算 |
|-------|------|------|
| Phase 0 | 重命名收尾 + 测试迁移 | ~0.5h |
| Phase 1 | 新闻/政策聚合 | ~1h |
| Phase 2 | 实时/指数/商品/基本面聚合 | ~1.5h |
| Phase 3 | 因子原始数据聚合 | ~1h |
| Phase 4 | 刷新中枢 + 探针 | ~0.5h |
| Phase 5 | 文档/契约/终检 | ~0.5h |
| **合计** | **数据管道聚合** | **~5-6h** |

> 注：Phase 31 的"重命名脚手架"已在工作树完成但未提交；本计划 Phase 0 将其收尾为可提交 baseline，Phase 1-5 为真正的聚合实施。
