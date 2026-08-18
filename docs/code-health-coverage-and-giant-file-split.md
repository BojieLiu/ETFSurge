# 代码健康审计：覆盖率 + 冗余测试 + 巨型文件拆分方案（2026-08-18）

> 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程（design-checklist.md 8 项）」撰写。
> **本文档仅设计修复方案与拆分方案，不实施。**
> 数据来源：全量 `pytest --cov`（2026-08-18 07:57-08:02 跑批，2149 passed / 8 skipped / 3 deselected / 16 warnings in 301.35s）。
> 覆盖数据文件：`backend/.coverage`（`/tmp/cov_backend.coverage` 备份）；报告：`/tmp/coverage_report.txt`。

---

## 0. 执行摘要

### 0.1 审计范围与结论

| 项 | 结论 |
|---|---|
| **总体覆盖率** | **72%**（18077 stmts / 5131 miss）——中位偏上，但存在 6 个 0%-20% 低覆盖文件（`main.py` 15%、`database.py` 20%、`config_manager.py` 0%、`probes.py` 0%、`app_config.py` 0%、`sync_indices_meta.py` 10%） |
| **测试冗余** | 三组重叠信号：① **3 个 strategy_check 测试文件互相重叠**（fallback/llm_timeout/timeout，83 tests 中对同一函数 `generate_strategy_check_report` 的 timeout/fallback 分支重复覆盖）；② **18 个 round 命名测试文件**（149 tests / 2755 行）游离于业务模块命名之外；③ **market_data_hub 被 79 个测试文件直接引用**（依赖爆炸，拆分时 mock 面巨大） |
| **巨型文件** | 3 个 >2000 行文件（portfolio_service 2783 / market_data_hub 2649 / llm 2278）+ 7 个 1000-2000 行；**拆分首要对象是 market_data_hub（23 生产调用方、106 方法、共享状态字段耦合为主）** |
| **业务/技术复杂度匹配** | 总量匹配（多市场×多数据源×AI 真实多轴），结构不匹配（上帝文件 + 测试重叠） |

### 0.2 关键数字

- 生产代码：`backend/app` 91 文件 / 35,738 行；测试：`backend/tests` 229 文件 / 43,106 行（**测试行数 > 生产 1.2:1**）
- 前端：`frontend/src` 138 文件 / 26,699 行（vue 15430 + js 9939 + css 1330）
- API：73 REST 路由 + 5 WS 通道；api-contracts 53 份契约

### 0.3 问题分级（危害驱动）

- **P0（结构债，拆分直接影响面最大）**
  1. **MDH-God — market_data_hub 上帝类**（2649 行 / 106 方法 / 23 生产 + 79 测试引用）：门面与全部实现耦合在同一类，`_compute_composite`/`_balance_by_industry`/`_ensure_mandatory` 等**策略引擎逻辑**混入数据管线。详见 §4。
  2. **PS-God — portfolio_service 上帝模块**（2783 行 / 44 函数）：CRUD、分配、盈亏、策略检查、导入导出、权重漂移六大职责一文件。详见 §5。
  3. **LLM-God — llm.py 职责堆积**（2278 行）：断路器/配额门禁/报告生成/流式/资讯摘要/市场报告/建议全一文件。详见 §6。- **P1（测试冗余，双刃剑——既有重叠又有真空）**
  4. **T-OVERLAP — strategy_check 三文件重叠**（§3.2）：`test_strategy_check_fallback.py`（42 tests）+ `test_strategy_check_llm_timeout.py`（26 tests）+ `test_strategy_check_timeout.py`（15 tests）对 `generate_strategy_check_report` 的 timeout/fallback 分支重复覆盖。
  5. **T-ROUND — round 命名测试游离**（§3.3）：18 文件 / 149 tests / 2755 行仍以 `test_roundNN_*` 命名，未并入业务模块（round27 已折叠 33 个早期文件，此为残余批次）。
  6. **T-MOCK-SURFACE — market_data_hub 测试依赖面过大**（§3.4）：79 个测试文件直接 import hub 单例，任何签名/行为改动需同步 79 处。
- **P2（覆盖率真空，正确性风险）**
  7. **C-VOID — 低覆盖文件清单**（§3.1）：`main.py` 15%（520 stmts / 443 miss，启动/预热/任务编排全裸奔）、`database.py` 20%、`fetchers/global_markets_fetcher.py` 45%（247 miss，美股/港股/商品数据源是业务核心）、`services/market_trends.py` 50%、`routers/ws.py` 49%、`monitor/source_events.py` 33%。
  8. **DEAD-CODE — 三处死代码/滞留函数**（§5.5）：① `llm_context.py:168-175` import 不存在的 `portfolio_service` 符号（try/except 吞错恒落空列表，从未工作）；② `_detect_regime`（`portfolio_service.py:2232`）0 生产调用 + 0 测试引用（真死代码）；③ `_cross_sectional_factor_composite`（`portfolio_service.py:1619`）0 生产调用但测试直测 4 处（仅测试引用的滞留函数）。均随方案 B 一并处理，不静默留存。
- **P2（前端/生成代码冗余，见 §7）**
  9. **FE-DEAD — 前端死 utils：0 个（初检 3 个，Review 8 全数证伪）**（§7.1）：`chartColors.js`（`AnalysisView.vue:66` import）、`pricing.js`（`TokenMonitor.vue:153` import）、`newsLevel.js`（`NewsView.vue:152` import）**全部活跃**——初检用 `grep -v "utils/$name"` 误伤了含 `../utils/xxx` 的 import 行（round11 H1 同型教训）。前端生产代码死代码实际仅 CSS 死类（FE-CSS）。
  10. **FE-CSS — 前端死样式类 ~123 个**（§7.1.1）：theme.css 94 个 0 引用类 + global.css 29 个（round11 已列未落地）。
  11. **FE-TEST-ORG — 前端测试组织错位**（§7.2）：60 个 spec，同一被测对象分散多文件（DashboardAiTools 7 个/869 行、WatchlistPanel 4 个、NewsView 3 个）且散落 `src/components/` 与 `src/test/` 两目录；批次命名（round19-batch1/2、AppComponents2）与后端 `test_roundNN_*` 同型。
  12. **BE-SCRIPTS — 后端生成/工具代码冗余**（§7.3）：`start_backend_profiled.py`/`ipv4_forward_proxy.py` 0 引用（round16/14 已标记删除未执行）；`backfill_avg_cost.py`/`run_scheduler.py`/`docker_smoke.py`/`sync_sectors.py` **2026-08-18 用户确认全部删除**（0 测试引用，`sync_sectors` 唯一生产引用在 run_scheduler 内，同批联动删）。

### 0.4 验证窗口标注（D3）

覆盖率/结构数据为**代码级静态事实**，不受交易时段影响。缺失行区间来自 `.coverage` 数据文件（2026-08-18 07:57 跑批，mock 环境），无外部行情依赖。

---

## 1. 审计方法与证据链（D1/D2）

### 1.1 覆盖率跑批命令

```bash
cd backend && python -m pytest --cov=app --cov-report=term-missing -q
# 结果: 2149 passed, 8 skipped, 3 deselected, 16 warnings in 301.35s
# 报告: python -m coverage report --include="app/*" --show-missing
```

### 1.2 模块级覆盖率（关键行）

| 模块 | Stmts | Miss | Cover | 备注 |
|---|---|---|---|---|
| **app（总计）** | 18077 | 5131 | **72%** | |
| main.py | 520 | 443 | 15% | 启动/预热/任务编排无单测 |
| database.py | 107 | 86 | 20% | 连接/会话/事务层裸奔 |
| core/config_manager.py | 71 | 71 | 0% | 全未覆盖 |
| monitor/probes.py | 53 | 53 | 0% | 全未覆盖 |
| models/app_config.py | 8 | 8 | 0% | 全未覆盖 |
| fetchers/sync_indices_meta.py | 129 | 116 | 10% | 同步元数据 |
| fetchers/global_markets_fetcher.py | 448 | 247 | 45% | 美股/港股/商品主力 |
| services/market_trends.py | 204 | 102 | 50% | |
| routers/ws.py | 120 | 61 | 49% | WS 广播/推送 |
| monitor/source_events.py | 148 | 99 | 33% | 数据源事件 |
| **services/market_data_hub.py** | 1479 | 427 | 71% | 巨型文件 |
| **services/portfolio_service.py** | 1396 | 331 | 76% | 巨型文件 |
| **analysis/llm.py** | 1049 | 278 | 73% | 巨型文件 |
| engine/allocation_engine.py | 833 | 37 | 96% | 纯函数引擎，覆盖优 |
| factors/factor_registry.py | 925 | 132 | 86% | |
| models/schemas.py | 148 | 0 | 100% | |

### 1.3 巨型文件缺失行区间（拆分前基线）

- **market_data_hub.py**（427 miss，71%）：集中缺失在 `_persist_snapshot_sync` 失败分支、`refresh()` 全链路异常路径、`_build_symbol_extra`/`_enrich_symbol_extra`、US/HK 各实时入口、`_refresh_news_buckets_safe` 失败分支。
- **portfolio_service.py**（331 miss，76%）：`update_etf` 的 tracked_index 解析失败分支、`_fetch_realtime_price` 降级、`export/import_portfolio` 错误路径、`calculate_cumulative_pnl` 部分分支、`_compute_risk_warnings` 部分行业分支。
- **llm.py**（278 miss，73%）：`generate_advice` 全链路（1140-1296 整段）、`_circuit_*` 若干状态转换、`generate_design_report` 的 LLM 失败路径、`run_stream_with_cache` 部分分支。

---

## 2. 巨型文件拆分方案总览

> **核心原则（回应用户质疑——拆分不偏离"统一数据管线"原设计）：**
> 拆分对象是**类内部实现**，不是门面本身。`MarketDataHub` 从"门面+全实现"变成"门面+委派"；公共 API 签名零变化；协作对象为私有实现不得被外部 import。策略引擎逻辑（`_compute_composite` 等）外移到 `engine/` 纯函数包。

| 方案 | 目标文件 | 拆分方式 | 影响面 | 优先级 |
|---|---|---|---|---|
| A | market_data_hub.py | 门面保留 + 实现拆 7 个协作对象 + 策略逻辑入 engine | 23 生产 + 79 测试（mock 面大，需兼容层） | **P0** |
| B | portfolio_service.py | 按六大职责拆 6 个模块 + `__init__.py` re-export 兼容 | 3 生产 + 28 测试 | P0 |
| C | analysis/llm.py | 按「客户端/门禁断路器/报告生成/资讯摘要」拆 4 模块 + re-export | 8 生产 + 32 测试 | P0 |

> **通用策略**：所有拆分均采用 **re-export 兼容层**（旧 `from app.services.portfolio_service import strategy_check` 继续可用），分 3 步走：① 先拆实现+re-export（行为零变化，测试全绿）；② 再迁移消费者到新路径（`rg` 确认旧引用清零）；③ 最后删除 re-export。**绝不一刀切**（参照 round14 apply-design 断裂教训）。

---

## 3. 覆盖率审计详情 + 冗余测试识别

### 3.1 覆盖率真空清单（P2 C-VOID）

低覆盖文件按**业务危害**排序（非仅覆盖数字）：

1. **fetchers/global_markets_fetcher.py（45%，247 miss）**：美股/港股/商品行情是核心业务（R20/R53/R54 全在这个文件出过问题），45% 覆盖意味着未来改这里极易回归。
2. **main.py（15%）**：启动预热、`refresh_market_cache`、后台任务编排、IC 回填调度（R55/R56/R58 全在这层）——round28 已证明这层是 bug 高发区，0 覆盖 = 每次回归都逃逸到 E2E。
3. **routers/ws.py（49%）**：WS 广播/连接管理，前端实时性依赖，断裂即"静默无推送"。
4. **database.py（20%）**：连接池/会话生命周期，是"改一次炸一片"的底层。
5. **monitor/source_events.py（33%）**：数据源健康监控，运维价值被测试覆盖忽略。
6. **services/market_trends.py（50%）**、**fetchers/sector_fetcher.py（58%）**、**tasks/design_report.py（58%）**。

> **注意**：低覆盖 ≠ 必须补测。`main.py`/`database.py`/`probes.py` 属**胶水/启动代码**，对它们的单测投入产出比低（mock 面巨大、断言脆弱），更适合靠 `verify_e2e.py` + `smoke_startup.py` 链路保护。**补测优先给 fetchers/global_markets_fetcher.py 与 routers/ws.py**（业务价值高、断裂代价大）。

### 3.2 冗余测试组 1：strategy_check 三文件重叠（P1 T-OVERLAP）

三个测试文件全部 import `generate_strategy_check_report`（`app/services/portfolio_service.py:1562`）并覆盖其 **timeout → 规则兜底** 分支：

| 文件 | tests | 行数 | 重叠点 |
|---|---|---|---|
| test_strategy_check_fallback.py | 42 | 967 | `test_llm_timeout_generates_report_text` / `test_llm_timeout_rule_covers_all` / `test_llm_partial_coverage_rule_fills_gap` |
| test_strategy_check_llm_timeout.py | 26 | 500 | `test_data_complete_timeout_is_180_not_75` / `test_timeout_tiers_unchanged` / `test_second_call_hits_llm_report_cache` |
| test_strategy_check_timeout.py | 15 | 330 | `test_generate_strategy_check_report_catches_cancelled` / `test_strategy_check_cancelled_error_usage_record` / `test_timeout_log_message_shape` |

**识别依据**（证据链）：
- 三文件 83 个 test 中约 **15-20 个**围绕「LLM 超时/失败 → 规则兜底 → 报告生成」同一行为矩阵，按 timeout 层（15s/45s/60s/75s/180s）、兜底类型（全空/部分/数据质量）、错误类型（429/超时/服务错）反复排列组合。
- 该类测试**不是错**——timeout 分层与兜底矩阵是 round28 R43/R57 的核心回归防线。**问题是组织方式**：3 个文件按「测试批次」而非「被测单元」切分，新增 timeout 层时不知道该往哪个文件加，必然继续叠新文件。

**处理建议**（不是删除，是合并重组）：
- 将三文件合并为一个 `test_strategy_check_timeout_matrix.py`（或并入业务模块 `test_portfolio_service_strategy_check.py`），用 `pytest.mark.parametrize` 收敛同构用例（如 5 个不同 timeout 层 = 1 个参数化用例）。
- 预计 83 tests → 40-50 tests，行数 1797 → ~1000，**覆盖不变**。
- 合并时保留 round28 语义（timeout 分层不可合并成单一断言）。

### 3.3 冗余测试组 2：round 命名测试游离（P1 T-ROUND）

18 个 `test_roundNN_*` 文件 / 149 tests / 2755 行，未并入业务模块命名（round27 `a828fe9` 已折叠 33 个早期文件，此批为残余）。

| 文件 | tests | 行数 | 归属业务模块（建议并入） |
|---|---|---|---|
| test_round28_fixes.py | 28 | 651 | 按测试内容分入 portfolio/market/factors 对应模块 |
| test_round24_batch3.py | 13 | 209 | strategy/portfolio |
| test_round24_r24_correlation.py | 13 | 202 | engine/correlation |
| test_round25_r41_near_substitute_ungated.py | 7 | 186 | engine/allocation |
| test_round24_r20_watchlist_us.py | 6 | 172 | services/market_service |
| test_round24_r26_snapshot.py | 8 | 151 | services/market_data_hub（快照持久化） |
| test_round24_r22_avg_ic.py | 8 | 150 | factors/ic_tracker |
| ...（余 11 个同模式） | | | |

**识别依据**：与 `a828fe9` 折叠的 33 个文件同属「round 验收批次测试」，命名带轮次号 = 按时间而非按被测单元组织，未来维护者无法通过文件名定位。

**处理建议**：随巨型文件拆分一并迁移——测试文件跟随被测代码模块移动（`market_data_hub` 拆分后，相关 round 测试并入新模块测试文件）。**先拆分后迁移测试**，避免二次搬迁。

### 3.4 冗余测试组 3：market_data_hub 测试依赖面过大（P1 T-MOCK-SURFACE）

79 个测试文件直接 import `market_data_hub`（含单例 `market_data_hub = MarketDataHub()`），意味着 hub 任何行为改动 = 79 处 mock/断言联动。这是拆分的**最大技术风险**，也是拆分的**最大收益点**（拆后测试面收敛到门面 + 各协作对象子集）。

### 3.5 测试总体评估

- 43K 测试行 / 18K 生产 stmts ≈ **2.4 测试行 per stmt**——偏高，但含大量断言/注释/mock 噪音，不直接等于冗余。
- **72% 覆盖 + 2149 passed**：覆盖不算低，但与 43K 测试行数不匹配——**测试多但集中在已覆盖区**（引擎/因子/模型 96%-100%），**低覆盖区（数据源/启动/WS）恰是高风险区**。这是「测试资源错配」而非「测试过多」。
- 冗余测试的正确处理是**合并重组**（如 §3.2），**不是删除**——删测试会直接砸 round 验收矩阵。

---

## 4. 方案 A：market_data_hub.py 拆分（P0，最高优先）

### 4.1 现状

- 2649 行 / **106 方法** / 模块级单例 `market_data_hub = MarketDataHub()`（`market_data_hub.py:2649`）
- 23 个生产文件 + 79 个测试文件引用
- **耦合结构实证**（`sed -n '361,2649p'` 统计）：类内 69 个不同 `self.xxx` 引用，其中**高频引用全是共享状态字段**——`self._pool`(15)、`self._kline_cache_rows`(12)、`self._sector_momentum_cache`(9)、`self._by_code`(8)、`self._index_realtime_cache`(8)、`self._refresh_lock`(8)。**方法间互调稀疏，共享状态字段是主要耦合点**——拆分的关键设计是「共享状态字段留在门面，协作对象通过注入访问」，而非「把字段搬进协作对象」（搬了会引入协作对象间状态同步问题）。

### 4.2 设计原则（回应「拆分是否偏离统一数据管线原设计」）

| 保留（原设计意图） | 拆出（实现细节） |
|---|---|
| `MarketDataHub` 门面类 + 单例，公共 API 全部保留 | 各功能簇实现拆为协作对象（私有） |
| 统一缓存协调（kline 缓存、快照、预热） | 策略引擎逻辑（`_compute_composite` 等）外移 engine/ |
| 统一降级链（多源 failover 集中管理） | 纯数据获取/解析逻辑（fetcher 层） |

**判定**：原始设计「统一数据管线」= 单一入口 + 缓存协调 + 降级集中，这是**门面职责**，拆分后完全保留；拆分只解决「门面把实现全塞进一个类」的问题。**不偏离原设计，反而是补全**。

### 4.3 目标结构

```
app/services/market_data_hub.py          ← 门面（保留类 + 单例 + 全部公共方法签名）
app/services/hub/
    __init__.py                          ← 导出 MarketDataHub + 全部模块级符号（兼容）
    _snapshot.py                         ← 快照持久化（_snapshot_db_path/_snapshot_as_of_for/_persist_snapshot_sync/_load_latest_snapshot_sync——原模块级函数迁入）
    _kline.py                            ← K线/历史/缓存（get_kline/get_history/refresh_kline/mark_kline_stale/_persist_kline_cache_sync...）
    _realtime.py                         ← 实时行情（get_realtime/get_all_realtime/get_portfolio_realtime/get_indices/get_global_indices/get_commodities/get_hk_*/get_us_*...）
    _sector.py                           ← 板块/热点（get_sector_momentum/get_hot_plates/get_sector_heat/get_sector_industry/get_sector_concept/get_sector_stocks/get_fund_flow...）
    _news.py                             ← 资讯（get_news/get_news_headlines/get_news_macro/get_news_global/get_news_stock/refresh_news/enrich_news_summaries...）
    _regime_sentiment.py                 ← 市态/情绪（update_market_regime/get_market_regime/refresh_sentiment_cache/get_market_sentiment...）
    _pool.py                             ← 候选池（get_pool/get_by_code/_rebuild_index/get_factor_matrix/get_akshare_pool_stats...）（注：`_refresh_impl`/`refresh` 及内嵌的 `_scan_pipeline`/`_warm_kline_concurrent`（784/790）为门面编排方法，见 §4.4，**均不归本模块**）
    _fundamentals.py                     ← 基本面/选股（get_fundamentals/get_fund_nav/get_stock_hot_rank/get_research_reports...）
app/engine/
    composite_signal.py                  ← 从 hub 迁入：_compute_composite/_pct_rank（纯函数）
    pool_balancing.py                    ← 从 hub 迁入：_balance_by_industry/_assign_layer/_ensure_mandatory/_deduplicate_by_index（纯函数）
```

> **re-export 保留清单（拆包时不得遗漏）**：`ALL_LAYERS` 及 `LAYER_CORE/LAYER_SATELLITE/LAYER_DEFENSE/LAYER_OPPORTUNISTIC/LAYER_RESEARCH`（`conftest.py:26`、`test_market_data_hub_pool.py:17-19` import）、`_snapshot_as_of_for`（`strategy_design.py:845` import）、`PoolDiff`、`_strong_sector_etfs`（测试引用）。Step 1 全部通过 `hub/__init__.py` re-export，否则 import 断裂。

### 4.4 协作对象间依赖

- 门面持有全部协作对象实例；协作对象之间**不互相 import**，共享状态通过门面注入（如 `_kline` 需要 `_snapshot` 持久化路径，由门面构造时注入）。
- **共享状态字段归属原则**（实证驱动）：`self._pool`/`_kline_cache_rows`/`_sector_momentum_cache`/`_news_buckets`/`_by_code`/`_index_realtime_cache` 等**高频共享字段一律留在门面**，协作对象通过构造函数注入「门面引用 + 字段访问器」使用——**不做字段搬迁**（避免协作对象间状态同步分叉）。
- **编排方法留门面**（实证驱动）：`refresh()`（685-739）与 `_refresh_impl()`（766-1126）横跨池构建（`_assign_layer`/`_deduplicate_by_index`/`_ensure_mandatory`/`_compute_composite`/`_balance_by_industry`）、K线预热（`refresh_kline`）、板块（`get_sector_momentum`）、资讯（`refresh_news`）、快照（`_persist_snapshot_after_refresh`/`_load_pool_snapshot`）多簇——**属门面级编排，不归任何协作对象**；内部对纯策略函数的调用在 Step 2 后指向 `engine/` 模块。
- 纯逻辑（`composite_signal.py`/`pool_balancing.py`）**零依赖**，被协作对象/门面调用。
- 依赖方向：`engine/`（纯函数）← `hub/*`（有 I/O）← `market_data_hub.py`（门面）← `routers`/`tasks`/`services`。**不允许反向**。

### 4.5 迁移步骤（三步走，行为零变化）

1. **Step 1 — 抽实现 + re-export**（预计 1 次 commit）
   - 新建 `app/services/hub/` 包，把**方法体 + 模块级函数**（`_snapshot_db_path`/`_parse_stock_list`/`_strong_sector_etfs`/`_rule_news_summary`/`PoolDiff` 等 10 个，见 `market_data_hub.py:38-341`）按簇搬入（**只搬实现，签名不动**）。
   - `MarketDataHub` 门面改为 `self._kline = HubKline(self)` 等组合，方法体变成一行委派。
   - `from app.services.market_data_hub import market_data_hub` **继续可用**（单例不变）。
   - 验证：全量 pytest（2149）+ `verify_e2e.py` 全 PASS。**此步行为零变化，是回归锚点。**
2. **Step 2 — 策略逻辑外移 engine/**（1 次 commit）
   - `_compute_composite`/`_balance_by_industry`/`_assign_layer`/`_ensure_mandatory`/`_deduplicate_by_index`/`_pct_rank`/`_truncate_with_mandatory_protection`/`_recheck_mandatory_after_truncate` 迁入 `engine/composite_signal.py` + `engine/pool_balancing.py`。
   - **纯函数实证**（Review 3/4）：8 个函数体内 0 个 `self.`/`ak.`/`requests`/`urllib`/`httpx`/`await` 引用；其中 4 个已是 `@staticmethod`（`_deduplicate_by_index`/`_truncate_with_mandatory_protection`/`_pct_rank`/`_balance_by_industry`），另 4 个带 `self` 参数但体内无 self 引用（`_assign_layer`/`_ensure_mandatory`/`_recheck_mandatory_after_truncate`/`_compute_composite`，实为误标的方法）——外移时去掉 `self`/`@staticmethod` 直接改为模块级纯函数即可，**零行为变化、零 I/O**。
   - 补纯函数单测（engine 层测试可 100% 覆盖，成本低）。
   - 验证：pytest + verify_e2e。
3. **Step 3 — 消费者迁移 + 删 re-export**（1-2 次 commit）
   - `rg "from app.services.market_data_hub import"` 全量改为直接 import 门面（不变）或协作对象（仅当确实需要内部能力时，**尽量不改**——门面已够用）。
   - 测试文件：79 个 import hub 的测试文件**无需改动**（门面签名零变化）；仅当测试直接操作内部状态（如 `_kline_cache`）时迁移到新路径。
   - 删除 re-export 前 `rg` 确认 0 残留。

### 4.6 风险与对策

| 风险 | 对策 |
|---|---|
| **79 测试文件 mock 面** | Step 1 行为零变化，门面签名不动 → 测试不改。若测试触及 `_persist_snapshot_sync` 等私有方法（`rg` 显示 `test_sector_momentum.py` 直测 snapshot 私有函数），Step 3 单独迁移 |
| **循环依赖** | 协作对象间禁止 import；共享状态靠门面注入（构造参数），不做全局单例嵌套 |
| **单例初始化顺序** | `market_data_hub = MarketDataHub()` 在模块底部实例化，拆包后保持同位置；门面构造时按序组装协作对象 |
| **kline 缓存/快照持久化** | `_snapshot_db_path`/`_load_latest_snapshot_sync`/`_persist_snapshot_sync` 留在门面或独立 `_snapshot.py`，供 `_pool`/`_kline` 通过注入使用，**不做重复实现** |
| **性能回退** | 拆分是「移动方法体 + 一行委派」，无新增 I/O；Step 1 后用 `verify_perf.py` 对比基线 |

---

## 5. 方案 B：portfolio_service.py 拆分（P0）

### 5.1 现状

- 2783 行 / 44 函数；3 个有效生产调用方（`routers/portfolio.py` 直接 import 11 个函数、`tasks/strategy_check_worker.py` 2 处 lazy import `strategy_check`、`services/market_service.py:1063` lazy import `list_etfs`）＋ 28 个测试文件。**注**：`services/llm_context.py:171` 虽 import `portfolio_service`，但该对象不存在（死代码，见 §5.5）——不视为有效调用方。
- 六大职责：① ETF CRUD（list/add/update/remove）② 价格映射（build_price_map/_build_price_map_async）③ 权重分配（calculate_allocation/weight_drift）④ 盈亏（calculate_daily_pnl/cumulative_pnl）⑤ 策略检查（strategy_check + 全部 `_rule_*`/`_factor_*` 辅助）⑥ 导入导出（export/import）。

### 5.2 目标结构

```
app/services/portfolio_service.py       ← 门面 re-export（Step 1 保持，Step 3 删除）
app/services/portfolio/
    __init__.py                         ← re-export 全部原符号（Step 1-2 兼容层）
    crud.py                             ← list_etfs/add_etf/update_etf/remove_etf/_resolve_tracked_index
    pricing.py                          ← build_price_map/_build_price_map_async/_get_etf_attr/_split_symbols/_fetch_realtime_price/_clear_price_map_cache
    allocation.py                       ← calculate_allocation/recompute_cost_after_trade/calculate_weight_drift
    pnl.py                              ← calculate_daily_pnl/calculate_cumulative_pnl
    strategy_check.py                   ← strategy_check + _collect_strategy_data/_build_llm_fail_summary/_llm_timeout_for/_is_failed_result/_empty_portfolio_diagnosis + 全部 _rule_*/_factor_*/_compute_risk_warnings/_compute_indicators（`_detect_regime` 为死代码，不随簇搬迁，Step 3 删除）
    design.py                           ← apply_portfolio_design
    transfer.py                         ← export_portfolio/import_portfolio
    formatting.py                       ← _factor_hint/_factor_strength_band/format_factor_summary/_normalize_confidence/_compute_confidence
```

### 5.3 依赖与边界

- `strategy_check.py` 簇（约 1300 行，871-2252 区间：`strategy_check` 主函数 + `_rule_*`/`_factor_*`/`_build_rule_fallback_*` 辅助 + `_compute_risk_warnings`/`_compute_indicators`）是最大单簇，且依赖 `market_data_hub`/`analysis.llm`（`generate_strategy_check_report`）——拆分后依赖方向仍为 `portfolio/strategy_check.py` → `hub`/`llm`，**不引入新环**。
- `pricing.py` 被 `crud.py`（实时价补充）与 `routers` 复用，独立成模块后无环。
- 模块间通过 `portfolio/__init__.py` re-export 互相引用时注意只引公共符号，不引私有。

### 5.4 迁移步骤（同方案 A 三步走）

1. Step 1：搬方法体到 `portfolio/` 子模块 + `__init__.py` re-export 全部符号 → 测试全绿（28 个测试文件 import 路径不变）。
2. Step 2：内部依赖梳理——`strategy_check.py` 内 `_build_llm_fail_summary`/`_llm_timeout_for`/`_collect_strategy_data` 等私有辅助随簇搬迁，确认无跨簇私有引用。
3. Step 3：消费者改 import 路径（`routers/portfolio.py` 从 `portfolio_service` 改到 `portfolio/` 子模块）+ 删 `__init__.py` re-export。

### 5.5 风险与对策

| 风险 | 对策 |
|---|---|
| `routers/portfolio.py` import 11 个函数 | Step 1 re-export 保持零变化；Step 3 一次性改 1 个文件的 import |
| **`llm_context.py:171` 引用不存在的 `portfolio_service` 对象（死代码）** | **实证**：`rg "portfolio_service = "` 全 app 无定义；`llm_context.py:168-175` 段 try/except 吞掉 ImportError 后恒落 `context["portfolio"] = []`——**该段从未工作过**。**测试联动（Review 10 补）**：`include_portfolio` 参数有 **15 处调用点**（生产 `analysis.py:319/414` + 测试 5 文件 `test_llm_context_market/test_macro_factors/test_macro_fetcher/test_market_isolation/test_market_service_hk`），且 `rg` 确认**无任何调用方依赖 `context["portfolio"]` 返回值**（生产/测试均无断言该键）。**删除方案（二选一，均需同步 15 处调用点）**：①**保留参数签名、标注 deprecated**（改动面最小，参数保留但段删除后恒不注入该键）；②删参数 + 同步清理 15 处调用点（彻底，但需改 2 生产 + 5 测试文件）。**推荐 ①**（低风险，符合「绝不一刀切」）。 |
| **`_detect_regime`（`portfolio_service.py:2232`）无调用点（死代码）** | **实证**：全文件仅 2232 定义一行，0 调用；`rg "_detect_regime" tests/` 0 引用。`_collect_strategy_data` 内市态取自 `market_data_hub.get_market_regime`（非本函数）。随方案 B Step 3 删除；**删除前 DoD**：`rg "_detect_regime"` 全库（含 tests/）0 残留后再删 |
| **`_cross_sectional_factor_composite`（`portfolio_service.py:1619`）无生产调用点，仅测试引用** | **实证**：生产代码 0 调用（1215/1700 注释确认弃用，round28 R42）；但 `test_round25_r27_factor_caliber.py` 有 4 处断言直测其行为——**属「仅测试引用的滞留函数」**，不得直接删。方案 B Step 3 时三选一：①接通回 `_attach_composite_decisions`（若 R42 语义允许）；②标注 `# dead` 移入待清理清单（测试随之迁/删）；③保留并在新模块测试中显式标注「遗留实现」。**不静默留存**（AGENTS.md 脚手架零容忍） |
| ~~strategy_check 与 apply_design 共享 `_collect_strategy_data`~~ | **已证伪**（Review 5）：`rg` 确认 `_collect_strategy_data`（932）仅被 `strategy_check` 内部调用，`apply_portfolio_design`（2254-2312）不使用——**无需跨簇共享安排**，随 `strategy_check.py` 内聚即可 |
| 28 个测试文件 | 与方案 A 相同：Step 1 不动测试；Step 3 按 `rg` 结果迁移 |

---

## 6. 方案 C：analysis/llm.py 拆分（P0）

### 6.1 现状

- 2278 行 / 8 生产调用方 + 32 测试文件。
- 职责混杂：断路器（`_circuit_*` 10 函数）、配额门禁（`LLMQuotaGate`）、报告缓存（`_REPORT_CACHE_*`）、流式（`llm_complete_stream`）、健康检查、5 类报告生成（market/advice/news/strategy/symbol/sector/design）。

### 6.2 目标结构

```
app/analysis/llm.py                    ← re-export 门面（Step 1-2），Step 3 删除
app/analysis/llm/
    __init__.py                         ← re-export（Step 1-2）
    client.py                           ← llm_complete/llm_complete_stream/llm_complete_with_system/_check_key/run_stream_with_cache/_rate_limit_wait
    gates.py                            ← LLMQuotaGate/_circuit_*/reset_circuit/_record_llm_error/get_last_llm_error/_clear_llm_error
    cache.py                            ← _REPORT_CACHE_*/get_cached_report/put_cached_report
    reports.py                          ← generate_design_report/generate_strategy_check_report/generate_strategy_suggestions/generate_market_report/generate_advice/generate_sector_analysis/generate_symbol_analysis/_build_report_prompt/_build_engine_fallback/_build_market_overview/_format_indices/_format_commodities
    news.py                             ← generate_news_summary/analyze_news_impact/_news_body_text
    health.py                           ← llm_health_check/_fetch_global_liquidity
    prompts.py                          ← load_prompt/SYSTEM_PROMPT/strip_internal_leak/_LEAK_PATTERNS
```

### 6.3 依赖注意

- `gates.py` 被 `client.py`/`reports.py` 依赖（超时/配额判断），`client.py` 被 `reports.py` 依赖。依赖方向 `gates ← client ← reports`，无环。
- `_build_engine_fallback` 只在 `llm.py` 内部被 `generate_design_report` 使用（`llm.py:1897`；`task_manager.py:492` 仅注释引用）——随 `reports.py` 内聚即可，无外部消费者。
- `_fetch_global_liquidity`（1100 行）被 `generate_market_report`（1094 行）调用——`health.py` 依赖方向为 `reports → health`（reports 调 health 取流动性），与 `llm_health_check`（admin 路由调用）共置 health.py 合理。
- prompt 文件（`prompts/v1/*.md`）路径 `_PROMPT_DIR = Path(__file__).parent / "prompts" / "v1"`——拆包后 `__file__` 变化，**必须改为显式 `Path(__file__).parent.parent / "prompts" / "v1"`**，否则 prompt 加载断裂（round14 同型教训）。

### 6.4 风险

| 风险 | 对策 |
|---|---|
| `_PROMPT_DIR` 路径变化 | 拆分后立即单测 `load_prompt("general_analyst.md")` 返回非空（现有 test_llm_prompt_format.py 可拦截） |
| `llm_health_check` 被 admin 路由调用 | 签名不变；`health.py` 依赖 `client.py` |
| 循环依赖 `client ↔ gates`（llm_complete 检查配额） | gates 独立无依赖，client 单向依赖 gates；若 client 需回调 gate 状态，通过参数注入 |

---

## 7. 前端生产/测试 + 后端生成代码冗余审计（2026-08-18 增补）

> 本节审计 `frontend/src` 生产/测试代码与后端生成/工具代码冗余，与 §3（后端测试冗余）互补。
> **增量复核说明**：`docs/archived/round11-code-redundancy.md`（2026-08-08）已做过一轮全量冗余审计，本节验证其 P0/P1/P2 落地情况 + 识别 round12-28 新产生的冗余。

### 7.1 前端生产代码冗余

**审计方法**：对 `src/components`/`src/views`/`src/composables`/`src/utils`/`src/stores`/`src/api` 逐一 `grep` 交叉引用（含 Vue 懒加载 `import()` 与 kebab-case 两种匹配），标记 0 生产引用项。方法学防误报：组件类验证含 `import()` 懒加载、`components:` 注册、kebab-case 三种形态；CSS 类排除动态拼接（`:class="{ 'x': cond }"`、`mt-${n}`）。

> **⚠️ 方法学教训（Review 8，round11 H1 同型）**：初检用 `grep -v "utils/$name"` 排除定义文件，**误伤了所有 `import ... from '../utils/<name>'` 行**（该行含 `utils/<name>` 子串）——导致 3 个活跃 utils（chartColors/pricing/newsLevel）被误报为死代码。**正确排除条件 = 仅排除定义文件完整路径（`$f`），不排除含模块名前缀的行。** 前端 utils 实际 0 死代码。此教训已写入 §8.4 防再犯。

**结果**：

| # | 项 | 规模 | 证据 | 结论 |
|---|---|---|---|---|
| FE-1 | ~~`src/utils/chartColors.js`~~ | ~25 行 | **证伪**：`AnalysisView.vue:66` import `chartColor/CHART_COLORS/CANDLE_UP/CANDLE_DOWN/histogramColor` | 活跃，保留 |
| FE-2 | ~~`src/utils/pricing.js`~~ | ~40 行 | **证伪**：`TokenMonitor.vue:153` import `calcCost/modelCostFromBuckets` | 活跃，保留 |
| FE-3 | ~~`src/utils/newsLevel.js`~~ | ~35 行 | **证伪**：`NewsView.vue:152` import 5 个导出；遗留双 spec 归位问题见 §7.2 | 活跃，保留 |
| FE-4 | theme.css 死类 | 94 个类 | 全库（vue/css/html）0 引用，见 §7.1.1 | 清理（round11 P3 已计划，未落地） |
| FE-5 | global.css 死类 | 29 个类 | `animate-*` 11 个（fade/pulse/shimmer/wiggle/spin/slide）+ `flex-*` 4 个 + `grid-cols-*` 7 个 + `items-stretch`/`justify-start`/`ml-auto`/`mr-auto`/`no-print`/`print-only`/`stagger-children` 7 个——全库 0 引用（round11 已列） | 清理 |

**排除项**（初检误报，已复核为活跃）：
- `NewsView`/`SourceMonitor`/`TokenMonitor`：初检 0 引用，实为 **router 懒加载**（`src/router/index.js:25/37/31`），活跃。
- `ChartPanel`/`ControlPanel`/`SignalPanel`/`AnalysisView`/`CapitalInputBar`/`TechnicalAnalysisModal`/`PortfolioManager`/`TaskProgress`/`AppCard`/`AppInput`/`AppSelect`/`AppTooltip`：初检 0，复核均被引用（`AppCard` 32 处、`AppTooltip` 24 处、`AppInput` 17 处等），活跃。
- `DashboardAiTools.vue`（view）：初检 0 引用，实为 `PortfolioAnalysis.vue:33` import，活跃。
- API 层：`marketApi`/`portfolioApi`/`newsApi`/`factorsApi`/`systemApi`/`adminApi` 全部方法均有真实调用点，**无死 API 方法**。

**7.1.1 theme.css 死类明细（94 个，全 0 引用）**

分三类：
- **布局工具类**（约 60 个）：`mt-1..8`/`mb-1..8`/`ml-1..4`/`mr-1..4`/`px-2..6`/`py-1..4`/`p-0`/`top-0`/`bottom-0`/`left-0`/`right-0`/`inset-0`/`w-full`/`max-w-full`/`min-w-0`/`overflow-*`/`rounded-*`/`shadow-*`/`transition-*`/`hover-*`/`active-scale`/`cursor-*`/`select-*`/`pointer-events-*`
- **语义类**（约 15 个）：`btn-cancel`/`btn-remove`/`btn-success`/`btn-trigger`/`content-placeholder`/`bg-inverse`/`data-panel-loading`/`focus-ring`/`focus-ring-error`/`sr-only`/`invisible`/`visible`/`text-brand`/`text-brand-hover`/`text-display`/`text-body-lg`
- **z-index 类**（约 8 个）：`z-dropdown`/`z-fixed`/`z-modal`/`z-popover`/`z-sticky`/`z-toast`/`z-tooltip`（组件内已改用 inline `z-index: var(--z-index-*)`，见 `PortfolioManager.vue:951` 等）

**注意**：`rounded-*`/`shadow-*`/`cursor-*` 等工具类被组件内 `<style>` 局部定义使用与否需在删除前二次确认（Vue scoped style 不经过 theme.css，grep 已覆盖 `.vue` 内 class 属性，但 scoped 样式块内的选择器会命中 `.vue` 文件——本审计 grep 的是「类名出现在 `.vue` 文件任何位置」，含 scoped 块，故为可靠信号）。

### 7.2 前端测试代码冗余

**总规模**：60 个 `*.spec.js`（`src/test/` 45 个 + 散落业务目录 15 个）。

**问题 1：同一被测对象的 spec 分散多文件 + 跨目录**

| 被测对象 | spec 文件数 | 散落位置 |
|---|---|---|
| DashboardAiTools | **7** | `src/components/`×3 + `src/test/`×4，共 869 行 |
| WatchlistPanel | **4** | `src/components/market/`×2 + `src/test/`×2 |
| NewsView | **3** | `src/components/`×1 + `src/test/`×2 |
| DesignResult | 3 | 全在 `src/test/` |
| AnalysisView / SignalPanel / GlobalIndicesStrip / DesignLoading / newsLevel | 各 2 | 跨目录 |

**问题 2：批次命名与集中目录不一致**

- `src/components/DashboardAiTools.history/report/timer.spec.js`、`WatchlistPanel.p0-3.spec.js`、`src/test/round19-batch1/batch2.spec.js`、`AppComponents.spec.js`/`AppComponents2.spec.js`——按「round 批次/数字后缀」命名，非按被测单元（与后端 `test_roundNN_*` 同型问题，见 §3.3）。
- 同一组件测试分处 `src/components/`（就近）与 `src/test/`（集中）两种模式并存，维护者无法预判位置。

**问题 3：双份/同名 spec（同一被测对象测试位置重复）**

- `src/components/NewsView.spec.js`（350 行）+ `src/test/NewsView.spec.js`（183 行）——**同名冲突**，vitest `include: ['src/**/*.spec.js']` 两个都会跑，重复覆盖 NewsView。
- `src/utils/newsLevel.spec.js` + `src/test/newsLevel.spec.js`（59 行）同时测活跃的 `newsLevel.js`——合并保留一份到 `src/test/`。

**处理建议**（非删除测试，是**归位**）：
1. 确立**唯一测试目录约定**：统一到 `src/test/`（与 45 个既有文件一致），散落的 15 个 spec 移动并重命名为 `src/test/<被测单元>.spec.js`（去 round 批次/数字后缀）。
2. DashboardAiTools 7 个 spec 合并为 `src/test/DashboardAiTools.spec.js`（保留全部用例，内部按 describe 分节）。
3. WatchlistPanel 4 个 / NewsView 3 个 / DesignResult 3 个同理合并。
4. 合并后 60 → 约 30-35 个 spec 文件，**测试数不变**，仅文件组织归一。

### 7.3 后端生成/工具代码冗余

**范围**：`backend/scripts/`、根目录 `start_backend_profiled.py`、`run_scheduler` 调度链。

| # | 项 | 规模 | 证据 | 结论 |
|---|---|---|---|---|
| BE-1 | `start_backend_profiled.py`（根目录） | ~25 行 | 0 调用点 + 0 测试引用（`rg "start_backend_profiled" tests/` 无命中）；round16/20 已标记删除未执行 | **删除** |
| BE-2 | `backend/scripts/backfill_avg_cost.py` | 66 行 | 0 引用（pre-commit/AGENTS/docs/生产均无）+ 0 测试引用；round19 P3 一次性数据迁移脚本（补录历史 avg_cost，`--dry-run` 支持）——迁移完成后即死 | **✅ 用户确认删除（2026-08-18）** |
| BE-3 | `backend/scripts/ipv4_forward_proxy.py` | ~100 行 | round14 备选方案已回退（`docs/archived/round14`），0 引用 + 0 测试引用（`rg "ipv4_forward_proxy" tests/` 无命中） | **删除** |
| BE-4 | `backend/scripts/run_scheduler.py` | ~60 行 | 无任何调度机制引用（start.ps1/stop.ps1/restart.bat/docker-compose/.github 均无）+ 0 测试引用；round11 列为「round6 调度，保留」但调度已迁移 app 内 tasks | **✅ 用户确认删除（2026-08-18）** |
| BE-5 | `backend/scripts/docker_smoke.py` | ~176 行 | pre-commit 已改为内联 `docker build -t etf_surge-backend-smoke`（`pre-commit:283`），docker_smoke.py 未接线（round11「已立项未接线」）+ 0 测试引用 | **✅ 用户确认删除（2026-08-18）** |
| BE-6 | `backend/scripts/sync_sectors.py` | ~71 行 | 仅被 run_scheduler.py 引用（`run_scheduler.py:28/45/47`），0 测试引用——随 BE-4 联动删除（同批删，无残留） | **✅ 用户确认删除（2026-08-18），随 BE-4 联动** |

**已落地（round11 清理项复核）**：14 个前端死组件/文件、`scripts/archive/` 一次性诊断脚本归档、`layout/` 目录删除、`FactorModelView` 独立路由删除——均已提交（round12-28 间清理）。

**未落地（round11 残留）**：CSS 死类（FE-4/FE-5）、`stores/task.js` 两处 `console.warn` 改 logger（`task.js:60/122`）、`App.vue` 假连接（**round19 已修复**，用真实 `marketStore.wsStatus`）。

---

## 8. 前端/生成代码冗余优化方案（并入实施批次）

### 8.1 处理原则

- **死代码删除**（BE-1/BE-2/BE-3/BE-4/BE-5/BE-6）：直接删，`rg` 确认 0 引用；**BE-2/BE-4/BE-5/BE-6 用户已确认删除（2026-08-18）**，无待决策项。**前端生产代码无死 utils**（Review 8 证伪初检误报）。
- **测试归位**（§7.2）：移动+合并，测试数不变，覆盖不变。
- **CSS 清理**（FE-4/FE-5）：按 §7.1.1 三类逐类二次确认（工具类/语义类/z-index 类），确认后删除。**CSS 无对应 spec 断言死类**（Review 10 实证 `rg "sr-only|focus-ring|mt-1|grid-cols-2"` 在 spec 目录 0 命中）——清理无测试联动面。
- **⚠️ 通用规则（Review 10 补）——「删除生产代码 = 先扫测试、再联动」**：删除任何生产符号（函数/参数/模块/脚本）前，**必须执行 `rg "<符号>" tests/` 反向扫描**，按命中分三类处理：①0 测试命中 → 直接删；②测试命中但为「仅测试引用的滞留函数」（如 `_cross_sectional_factor_composite`）→ 三选一（见 §5.5）；③测试命中且为参数/API 变更（如 `include_portfolio`）→ 同步更新测试调用点或保留参数签名标注 deprecated（见 §5.5 llm_context）。**禁止「删生产、留测试」造成 ImportError/断言悬空**——这与 AGENTS.md「引用同步」反假完成检查同源。

### 8.2 并入实施批次

| 批次 | 内容 | 验证锚点 |
|---|---|---|
| **Batch 5b**（随 Batch 5 或独立） | 前端测试归位合并（§7.2，含 newsLevel 双 spec 去重）；CSS 死类清理（FE-4/FE-5） | 前端 `npm test` 全绿 + `npm run build` 通过 |
| **Batch 6**（独立，低风险） | 后端生成代码清理：BE-1~BE-6 全部删除（**用户已确认**）；`sync_sectors`（BE-6）与 `run_scheduler`（BE-4）同批删，避免残留死链 | 后端 pytest 全绿 + `verify_e2e.py` 全 PASS + `rg "backfill_avg_cost|run_scheduler|docker_smoke|sync_sectors|start_backend_profiled|ipv4_forward_proxy"` 0 残留 |

### 8.3 每批 DoD（反假完成双证）

1. 前端：`npm test`（vitest）全绿、`npm run build` 无编译错误
2. 后端（Batch 6）：pytest 全量不降、`verify_e2e.py` 全 PASS
3. `rg` 删除对象 0 残留（如 `rg "chartColors|pricing"` 需按定义文件路径过滤——**见 §7.1 方法学教训**；Batch 6 后 `rg "backfill_avg_cost|run_scheduler|docker_smoke|sync_sectors|start_backend_profiled|ipv4_forward_proxy"` → 0）
4. **测试联动（Review 10 补）**：每个删除项执行 `rg "<删除符号>" tests/` 反向扫描，命中测试已同步清理/迁移，无悬空 ImportError/断言（`rg` 输出 0 或仅剩已更新的引用）
5. CSS 清理后走查关键页面无样式回退（theme token 仍可用）

### 8.4 防再犯（审计方法学教训固化）

- **前端死代码审计必须用「排除定义文件完整路径」而非「排除模块名前缀」**——否则 `import '../utils/x'` 会被误伤（round11 H1 与本次 Review 8 双重复踩）。
- 建议纳入 pre-commit 审计段脚本 `check_api_usage.py` 同型：新增死代码审计脚本时，grep 排除条件统一为 `grep -v "$定义文件路径"`。
- CSS 死类审计保留 `check_unused_styles` 门禁（现有 3 个死代码门禁之一），需确认其排除条件同样使用「文件路径」而非「类名前缀」。

---

## 9. 实施顺序与回归策略

### 9.1 建议批次（本方案只设计，不实施）

| 批次 | 内容 | 验证锚点 |
|---|---|---|
| **Batch 1** | 方案 B portfolio_service 拆分 Step 1（搬实现 + re-export） | 全量 pytest + verify_e2e 全 PASS（**最低风险，3 有效生产调用方**） |
| **Batch 2** | 方案 C llm.py 拆分 Step 1 | 全量 pytest + verify_e2e |
| **Batch 3** | 方案 A market_data_hub Step 1（最高风险放后，先积累前两批经验） | 全量 pytest + verify_e2e + verify_perf 对比 |
| **Batch 4** | 方案 A/B/C Step 2（策略逻辑外移 engine/ + 内部依赖梳理） | pytest + 新增 engine 纯函数单测 |
| **Batch 5** | 方案 A/B/C Step 3（消费者迁移 + 删 re-export）+ §3.2/§3.3 测试重组 | `rg` 旧引用清零 + 全量 pytest |

> 理由：先小后大、先低风险后高风险、每批可独立回滚。市场_data_hub 放 Batch 3 是因为其 79 测试依赖面最大，前两批可验证「re-export 兼容层」策略在本项目是否顺畅。

### 7.2 每批 DoD（反假完成双证）

1. 全量 pytest（2149 passed 基线）不降
2. `verify_e2e.py` 全 PASS
3. `rg "from app.services.portfolio_service import"`（**Batch 5** 即 Step 3 后）0 残留 / `rg "from app.services.market_data_hub import"`（**Batch 5** 后）只保留门面 import——**Batch 1-4（Step 1-2）期间旧 import 仍被 re-export 支持，不做 0 残留检查**（与「行为零变化」锚点一致）
4. `verify_perf.py` 无新增 FAIL（拆分不得引入性能回退）
5. 新 engine/ 纯函数有单测且覆盖 ≥90%

---

## 10. 已知问题模式对照（design-checklist D8）

| 模式 | 本方案是否触碰 | 对策 |
|---|---|---|
| 格式断言（只看结构不看值） | 拆分不新增断言 | 拆分后测试保持原断言语义 |
| mock 理想输入 | 拆分测试沿用现有 mock | 迁移测试时保留真实值断言（test_llm_timeout 有内容断言） |
| 契约盲区 | 拆分不新增 API | 公共 API 签名零变化，契约文件无需改 |
| CSS 零覆盖 | 不涉及 | — |
| 降级无门禁 | `_build_engine_fallback` 迁移 | 保留 `test_strategy_check_*` 对 fallback 内容的断言 |

---

## 11. 多轮 review 记录

### Review 1（2026-08-18，自查）
- **发现 1**：§4.5 Step 1 的 re-export 兼容层描述不完整——`market_data_hub.py` 除类外还有模块级函数（`_snapshot_db_path`/`_persist_snapshot_sync` 等 10 个模块函数），拆分时这些也要迁入 `hub/` 包并通过 re-export 保留。
  **修订**：§4.3 补 `_snapshot.py`，§4.5 明确「方法体 + 模块级函数一起搬」。
- **发现 2**：§5.2 `portfolio/formatting.py` 的 `_normalize_confidence` 等被 `strategy_check.py` 与 `crud.py` 共用——跨簇共享符号需在 Step 2 确认归属，否则 Step 1 会遗留跨模块私有 import。
  **修订**：§5.4 Step 2 补「确认无跨簇私有引用」。

### Review 2（2026-08-18，依赖/死代码实证审查）
- **发现 3**：`llm_context.py:168-175` 的 portfolio holdings 段 import 不存在的 `portfolio_service` 符号（`rg "portfolio_service = "` 全 app 无定义），try/except 吞错后恒落空列表——**死代码**。已加入 §0.3 DEAD-CODE、§5.5。
- **发现 4**：`_detect_regime`（`portfolio_service.py:2232`）0 生产调用 + 0 测试引用（真死代码）；`_cross_sectional_factor_composite`（1619）0 生产调用但 `test_round25_r27_factor_caliber.py` 直测 4 处（仅测试引用的滞留函数，不得直接删）。已细化 §5.5 处理三选一。
- **发现 5**：`_build_market_overview`/`_format_indices`/`_format_commodities` 实际被 `_build_report_prompt`（reports 簇）调用，从 §6.2 `news.py` 移至 `reports.py`。
- **发现 6**：`portfolio_service` 目标结构中 `_is_failed_result`/`_build_llm_fail_summary`/`_llm_timeout_for`/`_collect_strategy_data` 虽位于文件 780-837 行（pnl 区后），但全部仅被 `strategy_check` 内部调用（924/1110/1069/932）——归属 `strategy_check.py` 而非 `pnl.py`，已修正 §5.2。
- **发现 7**：`market_data_hub.py` re-export 保留清单补全——`ALL_LAYERS` + `LAYER_*` 常量（`conftest.py:26`、`test_market_data_hub_pool.py:17-19`）、`_snapshot_as_of_for`（`strategy_design.py:845` 生产引用）、`PoolDiff`、`_strong_sector_etfs`。已补入 §4.3。
- **发现 8**：`market_service.py:1063` 生产 import `list_etfs`（`get_portfolio_realtime` 用）——方案 B 中 `crud.py` 有真实生产消费者，re-export 必须覆盖。

### Review 3（2026-08-18，耦合实证 + 数字核验）
- **发现 9**：`market_data_hub` 实际 **106 方法**（非 ~90）；类内耦合以**共享状态字段**为主（`self._pool` 15 处、`_kline_cache_rows` 12、`_sector_momentum_cache` 9 等），方法互调稀疏——§4.1 补充耦合结构实证，§4.4 新增「共享状态字段留门面、协作对象注入访问」原则（**不做字段搬迁**，避免协作对象间状态同步分叉）。
- **发现 10**：测试引用数统一口径核验——`market_data_hub` **79**（非 80）、`llm` **32**（非 24）、`portfolio_service` **28**（非 29）。全文已更新（§0.2/§2/§3.4/§5.1/§6.1）。
- **发现 11**：`_empty_portfolio_diagnosis`（1449 行）仅被 `strategy_check`（905 行）调用，补入 §5.2 `strategy_check.py` 簇。
- **发现 12**：§5.2 目标结构明确 `_detect_regime` 死代码**不随簇搬迁**（避免实施者误搬），Step 3 删除。

### Review 4（2026-08-18，纯函数实证 + 编排归属）
- **发现 13**：8 个策略函数（`_assign_layer`/`_deduplicate_by_index`/`_ensure_mandatory`/`_truncate_with_mandatory_protection`/`_recheck_mandatory_after_truncate`/`_pct_rank`/`_compute_composite`/`_balance_by_industry`）体内 **0 个 `self.`/`ak.`/`requests`/`urllib`/`httpx`/`await` 引用**——全部纯函数。其中 4 个已 `@staticmethod`、4 个带 `self` 但体内无引用（误标）。外移 engine/ 只需去掉 `self`/装饰器，零行为变化。§4.5 Step 2 已补实证。
- **发现 14**：`refresh()`/`_refresh_impl()` 横跨 5+ 簇（池/K线/板块/资讯/快照）——**门面编排方法，不归任何协作对象**。§4.4 新增「编排方法留门面」原则，避免实施时把 refresh 拆进某个协作对象造成跨对象回调。

### Review 5（2026-08-18，全文一致性 + 引用核验）
- **发现 15**：§9.2 DoD 第 3 条逻辑矛盾——Batch 1（Step 1，re-export 阶段）期间旧 import 仍被支持，不应要求「0 残留」。改为 Batch 5（Step 3）后检查，并注明 Batch 1-4 期间 re-export 支持旧引用。
- **发现 16**：§5.5 原「strategy_check 与 apply_design 共享 `_collect_strategy_data`」经 `rg` 证伪——`apply_portfolio_design`（2254-2312）不使用该函数，仅 `strategy_check` 内部调用。已改为「已证伪」标注。
- **发现 17**：§0.1/§2/§4.5/§4.6/§9.1/§12 的残留「~90 方法」「80 测试」「29 测试」数字全部统一为 106/79/28（Review 3 已更新正文，本轮补 §2 总览表与摘要表）。
- **发现 18**：§4.3 `_pool.py` 误列 `_refresh_impl`——与 §4.4「编排方法留门面」矛盾，已加注释「不归本模块」。
- **发现 19**：§3.2 引用的 9 个 test 函数名逐一 `rg` 验证存在于对应三文件中，归属正确。

### Review 6（2026-08-18，调用方核验 + 行数修正）
- **发现 20**：`services/llm_context.py:171` 的 `portfolio_service` import 已证伪（不存在），方案 B 的有效生产调用方为 **3**（routers/portfolio、strategy_check_worker、market_service）而非 4。§5.1/§2/§9.1 已改。
- **发现 21**：§5.3 strategy_check 簇行数「约 800 行（871-1409）」不准确——含辅助函数实际至 2252 行，约 **1300 行**，已修正。

### Review 7（2026-08-18，最终核验）
- **发现 22**：§4.3 `_pool.py` 误列 `_scan_pipeline`/`_warm_kline_concurrent`——`grep` 确认二者是 `_refresh_impl` 内嵌函数（784/790 行，12 空格缩进），随门面编排留在 `_refresh_impl`，不归 `_pool.py`。已修正。
- **发现 23**：§9.2 DoD 引用的 `verify_perf.py`/`verify_e2e.py`/`smoke_startup.py` 均存在；`engine/` 现有模块（allocation_engine/budgets/correlation/rationale/risk_controls）与 Step 2 新增 `composite_signal.py`/`pool_balancing.py` 命名不冲突。**文档达到实施标准。**

### Review 8（2026-08-18，前端/生成代码审计 + 方法学纠错）
- **发现 24**：`chartColors.js`/`pricing.js`/`newsLevel.js` 初检「0 引用死代码」**全数证伪**——`AnalysisView.vue:66`、`TokenMonitor.vue:153`、`NewsView.vue:152` 均有真实 import。根因：初检 `grep -v "utils/$name"` 误伤含 `../utils/<name>` 的 import 行（round11 H1 同型）。§7.1 方法学教训 + §8.4 防再犯已写。
- **发现 25**：前端生产代码**无死 utils/死组件/死 API 方法**（60 个组件、全部 API 方法、全部 views/composables/stores 均验证有引用）——死代码仅 CSS 死类 123 个。
- **发现 26**：`global.css` 死类实际 **29 个**（初检写 7 个，漏了 `animate-*` 全家）——§0.3/§7.1 已修正为 123 个总计。
- **发现 27**：`backfill_avg_cost.py`（66 行）为 round19 P3 一次性迁移脚本，迁移后即死——§7.3 BE-2 建议归档 `scripts/archive/`。
- **发现 28**：`src/test/` 45 个 spec + 业务目录散落 15 个——DashboardAiTools 7 个 spec（869 行）分散两目录，为前端测试组织错位的典型样本。

### Review 9（2026-08-18，前端测试重复实证）
- **发现 29**：`src/components/NewsView.spec.js`（350 行）与 `src/test/NewsView.spec.js`（183 行）**同名冲突**，vitest `include: ['src/**/*.spec.js']` 两个都执行，重复覆盖 NewsView（内容不同但同一被测组件）。§7.2 问题 3 已补。
- **发现 30**：同名 spec 全库仅 2 组（NewsView.spec.js/newsLevel.spec.js）——`find | uniq -d` 实证，无遗漏。

### Review 10（2026-08-18，删除-测试联动审查 + 用户决策）
- **发现 31**：§5.5 llm_context 死代码段的 `include_portfolio` 参数有 **15 处调用点**（生产 `analysis.py:319/414` + 测试 5 文件），但 `rg` 确认**无任何调用方依赖 `context["portfolio"]` 返回值**——删除方案补充「保留参数标注 deprecated（推荐）或删参数+同步 15 处」二选一。§5.5 已补。
- **发现 32**：`_detect_regime`/`start_backend_profiled.py`/`ipv4_forward_proxy.py`/`backfill_avg_cost.py`/`run_scheduler.py`/`docker_smoke.py`/`sync_sectors.py` **全部 0 测试引用**——删除无测试联动面，仅 `sync_sectors` 生产引用在 `run_scheduler` 内（同批联动删）。§7.3 各 BE 行已补测试引用实证。
- **发现 33**：CSS 死类（FE-4/FE-5）无 spec 断言（`rg "sr-only|focus-ring|mt-1|grid-cols-2"` spec 目录 0 命中）——清理无测试联动面。
- **发现 34**：新增**通用规则「删除生产代码 = 先扫测试、再联动」**（§8.1）与 DoD 第 4 条「每个删除项执行 `rg "<符号>" tests/` 反向扫描」（§8.3）——覆盖此前方案只对个别项（`_cross_sectional`）考虑测试联动的缺口。
- **发现 35**：§9 子标题遗留「### 7.1」编号错误，已修正为「### 9.1」。
- **用户决策（2026-08-18）**：BE-2/BE-4/BE-5/BE-6 确认**全部删除**——§0.3/§7.3/§8.1/§8.2/§12 已同步。

### Review 完成：10 轮，35 项发现，全部修订落地。文档达实施标准，待用户指令后实施。

---

## 12. 结论

- **覆盖率 72%** 但**资源错配**：引擎/因子 96-100% 高覆盖，数据源/启动/WS 15-50% 低覆盖——正是业务断裂高发区。
- **后端测试冗余**不是「测试过多」而是「组织错位」：3 个 strategy_check 文件重叠 + 18 个 round 命名文件游离 + hub 79 测试依赖面。
- **前端冗余**以「CSS 死类 + 测试组织错位」为主：~123 个死 CSS 类（theme.css 94 + global.css 29）、同一组件 spec 分散多文件（DashboardAiTools 7 个）——多为 round11 已列项未落地 + round12-28 新积；**前端生产代码无死 utils/组件/API 方法**（Review 8 证伪初检 3 个死 utils 误报）。
- **后端生成/工具代码**：**BE-1~BE-6 全部删除（2026-08-18 用户确认）**——`start_backend_profiled.py`/`ipv4_forward_proxy.py`（确认死）+ `backfill_avg_cost`/`run_scheduler`/`docker_smoke`/`sync_sectors`（0 测试引用，`sync_sectors` 随 `run_scheduler` 联动删），其中 `docker_smoke.py` 已被 pre-commit 内联替代。
- **巨型文件拆分**采用「门面保留 + 实现拆协作 + 策略逻辑归 engine + re-export 兼容层」四件套，**不偏离统一数据管线原设计**；按 Batch 1-5 分步实施，每批可回滚；前端/生成代码冗余并入 Batch 5b/6。
- **本文档仅设计，不实施**。实施需用户明确指令。
