# Round11 代码冗余审计与清理方案（2026-08-08）

> 状态：**审计完成，方案未实施**。本文档为全项目冗余代码审计结论 + 分级清理方案，附多轮 review 修订记录。
> 范围：backend/app（业务代码）、frontend/src、backend/tests + verify_e2e、脚本/配置/数据/契约杂项。
> 方法：4 路并行只读审计（ripgrep 引用图谱 + 模式匹配），关键结论已二次抽查验证；**审计初报的 3 处误判已在 §0.2 纠正**。

---

## 0. 摘要

### 0.1 结论速览

- **冗余总量**：可归档/删除/合并约 **1.8–1.9 万行代码** + **4.8–5.7 MB 文件体积**（含重复缓存 ~308 KB；不含 docs/archived 已有归档），占后端 app（~4.3 万行）+ 前端 src（~1.6 万行）+ 测试（~3.1 万行）合计的 **17–20%**；
- **分布**：后端业务 ~2,300 行 / 前端 ~2,000–2,400 行 / 测试 ~3,200–3,900 行 / 杂项脚本+契约+临时 ~10,300–10,800 行 + 体积 ~4.8–5.7 MB（含缓存双份）；
- **风险分级**：P0 纯删除（约 **1 万行**，含一次性脚本/diag 归档）→ P1 低风险抽取合并（约 1,300 行）→ P2 需产品/行为确认（约 650 行 + 2 项行为修复，**决策已定稿**）→ P3 治理门禁（防再犯）；
- **5 项风险**（§6）：3 项 P0 级（空 DB 壳、diag 未入 gitignore、agents.md 过时）+ 2 项 P1 级注意（TTL 不一致、/indices/meta 误删风险）。

### 0.2 审计初报误判纠正（二次抽查验证后）

1. **`/indices/meta` 并非未接入前端**——`frontend/src/components/market/UnifiedAnalysis.vue:409` 实际调用 `marketApi.indicesMeta()`。审计初报将其列入「删除 6 个未接入端点」系误判，**该端点保留**。
2. **`backend/data/etf_list_cache.json` 无 latin1 mojibake**——实测 UTF-8 解码成功、JSON 解析 OK、中文名称完好（`"沪深300ETF南方"`）。初报「编码损坏」误判。真正问题仅是**路径双份**（根 `data/` 与 `backend/data/` 各一份），需统一路径而非修编码。
3. **「12 个无引用死代码文件」结论系统性失实（H1，第一轮 review 修正）**——初报按「backend/app 内无 import」判定，**未扫 `backend/tests/` 与 `backend/scripts/`**。实测 12 个文件中仅 `macro_state.py` 为真·全库零引用；`engine/design_quality.py` 被 **verify_e2e.py:1694 门禁在用**（不可删）；`services/snapshot_service.py` 被 verify_e2e.py:1856 + test_snapshot_service.py 引用；其余 10 个中 **9 个被测试文件引用、1 个（akshare_fetcher）被 scripts 目录引用**（§2.1 已逐文件列明引用点与联动删除清单）。
4. **`backend/scripts` 亦有未纳入初报的引用**：`verify.py:151` 与 `sync_indices_meta.py:47` 经 akshare_fetcher re-export 引用 `_decode_df`/`fetch_index_history`——删除 shim 需同步改这两处 import（`_decode_df` 实为 `utils/decode.decode_df` 别名，改直连；`fetch_index_history` 改从 `china_market` 导入，§2.1 已列）。

### 0.3 方案总表

| 级别 | 内容 | 预估量 | 风险 |
|---|---|---|---|
| **P0** | 纯删除（含联动删测试）：生产无引用文件（12 个，其中 design_quality 保留）、前端 14 个死组件/composables、废弃端点、空测试、一次性脚本、diag/ 残留、空 DB 壳 | ~1 万行 + 4.8–5.7 MB（含脚本/diag 归档） | 低（删测试需联动，先跑全量测试确认） |
| **P1** | 低风险抽取合并：5 处 `_safe` 族、`_cached`×4、三源 `_sync_fetch`、ws 样板、`utils/format.js`、样式统一、测试 6+1 组合并、verify_e2e 去重、契约合并 | 表头 ~1,300 行（**仅指 P1-1..7 代码抽取；测试/契约合并量另计 ~6,400，见 §7 口径说明**） | 低（改调用点需回归） |
| **P2** | 需产品/行为确认（**2026-08-08 决策定稿**）：FactorICView/FactorModelView 合并（删独立路由）、useWarmupStatus 单例、App.vue 假连接、connectTaskWs 抽 useTaskWS、hk_hot_fetcher 走 SourceRegistry、缓存路径统一（根 data/）、scaffold 注释清理（函数保留） | ~650 行 + 2 项行为修复 | 中（行为变化） |
| **P3** | 治理门禁（防再犯）：函数级 AST 未引用扫描进 CI、purgeCSS 死样式验证、.env.example 同步、diag/ 入 .gitignore、契约-路由一致性门禁 | 0 行（新增门禁） | 低（新增检查） |

---

## 1. 审计方法与范围

- **4 路并行只读子代理**（各带独立工具集，互不共享上下文）：
  1. 后端业务：`backend/app`（排除 tests），ripgrep 全库引用图谱 + 模式匹配；
  2. 前端：`frontend/src`，import 引用图谱 + 模板/样式模式匹配；
  3. 测试：`backend/tests`（226 文件）+ `backend/scripts/verify_e2e.py`（2,278 行），独立核实 round10 §9.1 结论并补充新发现；
  4. 杂项：`backend/scripts`、根目录脚本、docker 配置、api-contracts、data 缓存、临时文件。
- **二次抽查**（主代理手工验证高风险结论）：`/indices/meta`、`/llm-advice` 等端点前端调用；12 个死文件引用；`AppLayout`/`useMarketWS` 引用；`backend/data/portfolio.db` 体积；`etf_list_cache` 编码；conftest 死 fixture；`market_router` 测试引用。抽查发现 3 处初报误判（§0.2）。
- **口径**：行数为按文件字节/内容估读的近似值；「死代码」= 全库（含测试）无 import/调用，经 ripgrep 验证。

---

## 2. 后端业务代码冗余（backend/app，约 2,300 行）

### 2.1 生产无引用文件（12 个，约 1,644 行）——⚠️ 第一轮 review 修正

> **修正说明**：初报按「backend/app 内无 import」判定，漏扫 `backend/tests/` 与 `backend/scripts/`。以下为**逐文件实测后的最终定性**（引用点均已核实）：

| 文件 | 行数 | 实测引用 | 最终判定 |
|---|---|---|---|
| `services/macro_state.py` | ~247 | **全库（含测试/scripts）零引用** | ✅ 真·死文件，可直接删 |
| `fetchers/ttj_fetcher.py` | ~216 | `test_ttj_fetcher.py:7/16/25`（整文件 import+patch）、`test_s5_remaining.py:74/82` | 生产无引用；**删需连带删 test_ttj_fetcher.py 整文件 + 改 test_s5_remaining.py:71-91 段** |
| `fetchers/benchmark_stocks.py` | ~177 | `test_design_new_modules.py:192/204`（import CORE_BENCHMARK_STOCKS/judge_signal） | 生产无引用；**删需连带改 test_design_new_modules**（该文件还测 design 其他新模块，不能整删） |
| `services/market_router.py` | ~203 | `test_market_context.py:315-322`（签名断言）、`test_phase2b_policy_mypy.py:127-142`（源码路径 `open()` 断言） | 生产无引用；**删需连带删/改 2 个测试**；内部恒假分支 `batch=None`/`fallback_data=None`（:98-100/:136-138） |
| `services/market_data_adapter.py` | ~102 | `test_pool_manager_phase3.py:61` | 生产无引用；**删需连带改 test_pool_manager_phase3**（该文件主体是 pool_audit 测试，不能整删） |
| `services/snapshot_service.py` | ~138 | **verify_e2e.py:1856（section_snapshot_health 在用）+ test_snapshot_service.py:12** | ⚠️ **verify_e2e 门禁在用**——不能直接删；需先按 §4.4 删 verify_e2e section_snapshot_health + test_snapshot_service.py，再删本文件（依赖顺序，见 P0-1 步骤） |
| `engine/design_quality.py` | ~87 | **verify_e2e.py:1694（section_design_quality_gate 门禁 import validate_design_quality/check_strategies_differ）** + test_design_quality_gate.py:7 | ❌ **不可删**——verify_e2e 核心门禁在用（§4.1 已确认该 section 保留）。从删除清单移除 |
| `analysis/text_pipeline.py` | ~189 | `text_pipeline_b.py:17`（path_a）+ `test_text_pipeline.py:15` | 生产无引用（仅被同为死的 text_pipeline_b 引用）；**删需连带删 test_text_pipeline.py** |
| `analysis/text_pipeline_b.py` | ~205 | `test_text_pipeline_b.py:18`（NewsLLMAnalyzer） | 生产无引用；**删需连带删 test_text_pipeline_b.py** |
| `tasks/worker_registry.py` | ~40 | `design_tasks.py:22`（register_worker） | 生产无引用（仅被同为死的 design_tasks 引用）；随 design_tasks 一起删 |
| `tasks/design_tasks.py` | ~30 | `test_design_tasks.py:94/118/136/161/194/210`（6 处 import design_worker） | 生产无引用；**删需连带删/改 test_design_tasks.py**（该文件还测 TaskManager CRUD，见 §4.2） |
| `fetchers/akshare_fetcher.py` | ~10 | `verify.py:151`（fetch_index_history/fetch_history）、`sync_indices_meta.py:47`（_decode_df）——**均为 scripts 目录** | 生产无引用；删后需改 2 处 scripts import（`_decode_df` 实为 `utils/decode.decode_df` 别名，改直连 `from app.utils.decode import decode_df`；`fetch_index_history` 改从 `china_market` 导入）；verify.py 本身是归档候选（§5.1） |

> **P0-1 联动清单**（删除顺序与配套改动）：
> ① 直接删：`macro_state.py`（唯一真·零引用）；
> ② 删文件 + 连带删测试：`ttj_fetcher`（+test_ttj_fetcher.py、test_s5_remaining.py:71-91 段）、`text_pipeline`/`text_pipeline_b`（+test_text_pipeline.py、test_text_pipeline_b.py）、`worker_registry`+`design_tasks`（+test_design_tasks.py 中 design_worker 相关用例）；
> ③ 删文件 + 连带改测试（保留测试其余部分）：`benchmark_stocks`（改 test_design_new_modules.py:190-210）、`market_router`（删 test_market_context.py:315-322 + test_phase2b_policy_mypy.py:127-142）、`market_data_adapter`（改 test_pool_manager_phase3.py:61 附近）、`akshare_fetcher`（改 scripts 两处 import）；
> ④ **依赖顺序**：`snapshot_service` 需先删 verify_e2e section_snapshot_health + test_snapshot_service.py 再删；`design_quality` **保留**（verify_e2e 门禁在用）。
> **验收**：pytest 全量绿（1112 passed，删测试后以剩余数为准）+ verify_e2e 全 PASS（design_quality_gate 仍生效）。

### 2.2 重复实现的工具函数/模式（约 350 行可合并）

- **`_cached` 缓存包装 ×4**（几乎逐行相同，均为 `sync_memory_cache.get → producer() → set`）：`news_fetcher.py:83-91`、`levistock_fetcher.py:23-31`、`sector_fetcher.py:31-39`、`macro_fetcher.py:26-38`（fail-cache 变体）→ **抽 `services/cache_service.py` 的 `cached(key, producer, ttl_key)`**，4 处改调用（~40 行）；
- **线程池+超时包装 `_safe/_exec/_ak/_call` ×5**：`news_fetcher.py:40-47/62-80`、`levistock_fetcher.py:18-20`、`sector_fetcher.py:25-28`、`market_service.py:32-46`（含 CancelledError），另 `fund_fetcher.py:88`、`global_markets_fetcher.py:476/542/582/639/687` 裸调 `run_in_thread`——底层都是 `core/async_utils.run_in_thread/run_sync` → **`core/async_utils.py` 增加统一 `_safe_call(fn, timeout, executor, log_prefix)`**（~60-100 行）；
- **`factor_registry.py` 3 个同构 `_sync_fetch`**：:700-707（sina）、:743-752（qq）、:789-802（em），均为「run_sync + urlopen + decode」三段式 → **抽参数化 `_http_get_sync(url, headers, decode)`**（~40 行）；
- **router 级私有缓存**：`routers/factors.py:26-42` 自行实现 TTL 缓存（`_CACHE/_get_cached/_set_cache/_build_cache_key`），与 `cache_service.sync_memory_cache` 重叠 → 改用 `sync_memory_cache`（~17 行）；
- **`routers/ws.py:73-164` 5 个 WS 端点**重复 `connect → while 收包 → ping/pong → disconnect` 模式 → **抽 `_ws_loop(websocket, on_message)`**（~40 行）；
- **`routers/market.py:540-629`、`analysis.py:264-296/716-728` 大量 `asyncio.wait_for(hub.get_xxx(), timeout=15)` + `to_thread` 样板**（10+/15+ 处）→ **抽 `_with_timeout(coro, t)` 委托函数**（~30 行）；
- **Hub 门面 13 个单行委托**（`market_data_hub.py:1717-1784`）：有架构价值保留，但可用类级装饰器压缩样板（~60-90 行，可选）。

### 2.3 重复常量/配置（约 60 行归拢）

- **超时秒数硬编码 ≥10 处**：`_SRC_TIMEOUT=5`（news_fetcher:28）、`_AK_TIMEOUT=4`（:44）、`_TIMEOUT=8`（levistock:15）、`_TIMEOUT=10`（sector_fetcher:18）、`_TIMEOUT=8`（fund_fetcher:30）、`_TIMEOUT=8`（ttj_fetcher:34）、`_TIMEOUT=10/10/10/15`（global_markets_fetcher:380/481/587/816）、`_TIMEOUT=8`（china_market）、`FETCH_TIMEOUT=45`（routers/analysis.py:34）、`DEFAULT_SYNC_TIMEOUT=8`（core/async_utils.py:12）→ **集中到 `core/async_utils.py` 或 `core/constants.py`**；
- **TTL 散落 vs `core/ttl.py` 声明「集中定义」不符**：`ETF_CACHE_TTL=300`（etf_scanner:24，与 `CACHE_TTL["etf_list"]=3600` **不一致**！）、`KLINE_CACHE_TTL=300.0`（factor_registry:665）、`_SPOT_SHARES_TTL=3600.0`（china_market:501）、`_FUND_NAV_TTL=86400`（china_market:1130）、`_HK_ROWS_TTL=60.0`（hk_hot_fetcher:40）、`_SUCCESS_TTL/_FAIL_TTL`（macro_fetcher:22-23）、`_PRICE_MAP_TTL=15.0`（portfolio_service:202）、`_PORTFOLIO_REALTIME_TTL=15`（market_service:995）、`_GLOBAL_INDICES_TTL=30`（market_service:176）→ **并入 `CACHE_TTL`，先解决 etf_list 300 vs 3600 矛盾**；
- **指数符号映射 3 份**：`global_markets_fetcher.py:74-96` `EM_SYMBOL_MAP`、:159-168 `TENCENT_SYMBOL_MAP`、:255-264 `HK_SYMBOL_MAP`（`^HSI/^HSCE` 重复）+ `market_service.py:148-170` `_GLOBAL_INDEX_DEFS`（HK/US 重复）→ 各源映射保留，「our_symbol→显示名」抽共享表；
- **push2 域名 fallback**：`hk_hot_fetcher.py:27` `_EM_HOSTS` 与 `sector_fetcher.py:454` push2/push2delay 切换逻辑重复 → 统一到 `core/market_context.py`。

### 2.4 无价值/冗余代码（约 320 行）

- **注释掉的 scheduler 块**：`main.py:274-293`（20 行注释）+ `main.py:347` `app.state.scheduler = None` + :496-498 死分支 → 删除（~25 行）；
- **未接入前端的废弃端点**（二次核实）：`routers/analysis.py:248-353` `/llm-report`（106 行）、:356-380 `/llm-advice`（25 行）、:383-404 `/llm-news-analysis`（22 行）、:449-480 `/portfolio-review`（约 55 行）、`routers/market.py:317-357` `/search/stocks`（42 行）——**均为非 stream 版本，前端使用 stream 版（`/llm-report/stream` 见 MarketReport.vue:58、`/llm-advice/stream` 见 AiAdvisor.vue:53），非 stream 版无调用**。端点小计约 **250 行**。⚠️ **`/indices/meta` 保留**（§0.2-1 纠正）。另删 5 个 `# DEPRECATED: unused schema`（`models/schemas.py:152-211`，~60 行）+ 注释 scheduler（main.py:274-293，~25 行）+ 重复 import（analysis.py:1-2/:20/:25/:26，3 行）≈ **320 行**；
- **重复 import**：`routers/analysis.py:1-2` 重复 `import asyncio`；:20/:25/:26 三行重复 `from ..services.market_data_hub import market_data_hub` → 清理（3 行）。

### 2.5 双轨/遗留（保留或待决策）

- `engine/` 纯函数引擎 vs 旧 LLM 路径：**新路径活跃**（strategy_design.py:14-17 调用 engine），旧路径已在 analysis.py:433-435 标注废弃并迁移到 `/portfolio/design-async`——无无人调用的旧引擎，仅废弃端点残留（§2.4 已覆盖）；
- `factor_registry.py:403` `Scaffolding functions` 标注——**⚠️ 2026-08-08 复核修正：该区内 `_compute_premium_discount`/`_compute_tracking_error` 已在 :567-568 注册进 `_FACTOR_FUNCTIONS` 且在用（round10 §5.5 确认折溢价率 IC=0.1321 生效），非待接入脚手架**。改为：保留函数，仅清理误导性的 `# --- Scaffolding functions ---` 注释标题（1 行，见 P2-7）；
- **遗留待验证**（大文件函数级死代码，详见 §9——此处不展开）：`routers/admin.py`、`monitor/source_events.py`、`tasks/task_manager.py`、`analysis/llm.py`（82KB）、`factor_registry.py`、`market_data_hub.py`、`portfolio_service.py`——P3-1 的 AST 门禁跑通后自动覆盖。

---

## 3. 前端代码冗余（frontend/src，约 2,000–2,400 行）

### 3.1 无生产引用组件/文件（约 1,700 行含配套测试）

**生产+测试均无引用（8 个组件/composables）**：

| 文件 | 规模 | 建议 |
|---|---|---|
| `components/layout/PageContainer.vue` | ~31 | 删除 |
| `components/layout/PageHeader.vue` | ~52 | 删除（App.vue 用内联 `.page-header`） |
| `components/ui/AppAvatar.vue` | ~85 | 删除 |
| `components/ui/AppBadge.vue` | ~77 | 删除 |
| `components/ui/SvgIcon.vue` | ~22 | 删除 |
| `composables/useChartView.js` | ~52 | 删除（无引用，其内部 fetchJson 手拼 URL 与 marketApi 重复） |
| `composables/useTaskPolling.js` | ~71 | 删除（无引用） |
| `utils/fetchJson.js` | ~10 | 删除（仅被死代码 useChartView 引用） |

**仅被测试引用、无生产引用（6 个，含 AppLayout——其 App.spec.js:44/54/62/85/128/193/234 大量 mock 引用，M5 修正从「均无引用」组移入）**：`components/layout/AppLayout.vue`（~370，测试 mock 引用，router 未挂载）、`components/ui/AppTable.vue`（~228，仅 AppComponents2.spec.js）、`components/ui/AppPagination.vue`（~221，仅被 AppTable import 死链）、`components/ui/AppToast.vue`（~154，仅 App.spec.js:45 mock 形式；toast 实际由 App.vue 内联 + stores/toast.js 渲染）、`composables/useMarketWS.js`（~52，与 stores/market.js **逐行重复**、仅 useMarketWS.spec.js 引用）、`composables/useSectorAnalysis.js`（~119，仅 useSectorAnalysis.spec.js 引用）。

**死代码的配套测试**（一并清理）：`test/useMarketWS.spec.js`（~66）、`test/useSectorAnalysis.spec.js`（~95）、AppComponents2.spec.js 中 AppTable 测试块、App.spec.js 中 AppLayout/AppToast mock（需同步改）。合计 **14 个文件**（8 无引用 + 6 仅测试引用）。⚠️ **useNewsWS.js:11 注释提到 useMarketWS**（"Mirrors useMarketWS"）——删除后更新该注释。

### 3.2 未使用 import（4 行）

- `views/Dashboard.vue:130` `import VChart from 'vue-echarts'`（模板无 `<VChart>`，仅 149 行 `use([...])` 注册）→ 删 1 行；
- `api/index.js:86-87` `export const analysisApi = {}` 空对象无引用 → 删 2 行；
- `components/PortfolioManager.vue:395` import `changeClass` 但 500 行自定义 `getChangeClass` 并用后者 → 二选一（1 行）。

### 3.3 重复工具函数（约 150 行可合并）

- **千分位 `formatNum` 4 处逐字重复**（`toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})` + 正则回退）：`dashboard/AllocationTable.vue:51-58`、`PnLDetailTable.vue:62-64`、`SummaryCards.vue:158-160`、`components/PortfolioManager.vue:492`（:497/:504/:511 同族）→ 抽 `utils/format.js` 的 `formatNum(v, digits)`（~25 行）；
- **涨跌幅 `formatChange`/`(pct>0?'+':'')+pct.toFixed(2)+'%'` ≥9 处**：GlobalIndicesStrip.vue:103、AllocationTable.vue:65、PnLDetailTable、SummaryCards.vue:174、SectorHeatMap.vue:70/109、TechnicalAnalysisModal.vue:32/42、WatchlistPanel.vue:204、AnalysisView.vue:203 → 并入 `utils/format.js`（~30 行）；
- **金额「亿/万」缩写 4 处**：AnalysisView.vue:201、SectorHeatMap.vue:170-178、TechnicalAnalysisModal.vue:192-194、WatchlistPanel.vue:209-211 → 抽 `formatAmount`（~25 行）；
- **时间 `pad(2)` 3 处**：SourceMonitor.vue:268/328、TokenMonitor.vue:193（已有 `utils/formatDate.js` 未复用）→ 统一（~10 行）；
- **涨跌色 class 内联**（`utils/changeClass.js` 已抽出但多处未用）：FactorICView.vue:181-182、FactorModelView.vue:249/272/282、PortfolioManager.vue:500、SummaryCards/SectorHeatMap/TechnicalAnalysisModal 模板内联 `>=0?'text-up':'text-down'` → 统一用 `changeClass`（~8 行 + 消除不一致）。

### 3.4 重复组件/样式（约 350 行）

- **`FactorICView.vue`（~250，路由 `/factor-ic`）vs `FactorModelView.vue`（~700，DashboardAiTools 内嵌）**：同一数据源 `factorsApi.getIC/getActive`、同为「统计卡+因子表+阈值 0.02/0.03+text-up/down」UI、分类标签映射逐字重复 → **P2 决策**：保留 FactorModelView（更丰富：tooltip/IC 柱状图/折叠）为唯一实现，FactorICView 路由复用或移除（去重 ~300-400 行）；
- **`.btn-primary/.btn-secondary` scoped 样式 6 处**（FactorICView:384-390、FactorModelView:765-766、AiAdvisor.vue:96-108、UnifiedAnalysis.vue:526-538、WatchlistPanel.vue:338-349、ConfigView.vue:280-297）→ 统一为 AppButton 或抽公共 `.btn`（~50 行）；
- **`text-up/text-down` scoped 重复 7 处且颜色不一致**（theme.css:516-517 已全局定义；#f97316/#c62828/var 差异）：FactorICView:372-373、FactorModelView:750-751、GlobalIndicesStrip:264-265、PortfolioManager:1042-1043、AllocationTable:148-149、PnLDetailTable:145-146、SummaryCards:312-313（后 4 处带 `!important`）→ 删 scoped 定义统一走 theme.css（~15 行 + 修复颜色不一致）；
- **卡片布局模板重复**（SummaryCards/PortfolioManager/GlobalIndicesStrip 各自手写 stat-card）→ 抽 `StatCard` 公共组件（低优先级，~30-60 行）。

### 3.5 死样式（约 280 行，建议 purgeCSS 验证后删）

- `styles/global.css` L242-318 布局工具类（`.section/.grid-cols-*/.sm:*/md:*/lg:*/.flex*/.gap-*/.m-*`，全库无使用）~75 行 + L379-400 `.animate-*`/`.stagger-children`（含 8 条 nth-child）~22 行；
- `styles/theme.css` L493-511 文本工具类（仅 `.text-mono/.text-up/.text-down` 在用）~15 行、L521-598 `.bg-*/.flex-*/.items-*/.gap-*/.p-*/.px-*/.m-*/.w-full` 等 spacing/宽度 ~70 行、L602-680 `.rounded-*/.shadow-*/.transition-*/.hover-*/.focus-ring` ~60 行、L693-710 `.btn-success/.btn-trigger/.btn-cancel/.btn-remove` ~20 行、L715-731 loading 类疑似死 ~15 行。

### 3.6 注释/debug 残留（少量）

- `stores/task.js:60,122` 残留 `console.warn`（2 处，可改 logger）；
- `App.vue:153` 注释自述 `Connection status (mock...)`——`connectionStatus` 硬编码 `'connected'`，导航栏「已连接」是**假状态** → **P2 行为修复**：接入 stores/market.js 的 `wsConnected` 或删除（~10 行）；
- 各组件「旧实现 xxx」说明性注释约 40 处（变更历史残留，低优先级，可批量精简）。

### 3.7 新旧并存（2 项行为级）

- **WebSocket 三套**：① `stores/market.js:39-111`（在用，Dashboard.vue:202）；② `composables/useMarketWS.js`（与①逐行重复、生产零引用 → 删，P0）；③ `App.vue:201-296` `connectTaskWs` 直接 `new WebSocket('/api/v1/ws/task-notifications')` 未抽封装 → **P2**：抽 `useTaskWS` composable 与 useNewsWS 对齐（~50 行重构，不增量）；
- **useWarmupStatus 双实例轮询**：`App.vue:120,193` 与 `Dashboard.vue:136,171,196` 各自 `startPolling()`，两个独立闭包各跑 5s setInterval 轮询 `/api/v1/system/warmup` → **P2 行为修复**：改模块级单例或 Pinia store 共享（省一半 warmup 请求）。

---

## 4. 测试代码冗余（backend/tests + verify_e2e，约 3,200–3,900 行）

### 4.1 round10 §9.1 结论独立核实（本次实测修正）

| §9.1 结论 | 本次核实 | 处置 |
|---|---|---|
| 226 个测试文件 | ✅ 准确 | 保留 |
| 6 强重复组主体成立 | ✅ 成立，但 **3 处归组偏差**：test_market_context.py 主体非 hub 组、test_pool_manager_phase3.py 主体是 pool_audit/adapter、test_pool_manager_layer.py 是复制实现 | 按 §4.2 修正归组 |
| `_FakeSession`/FakeHub 重复 | ✅ 方向对，实测 `_FakeSession` 8 文件、FakeHub 9 文件（文档"10+"略高估） | 抽 conftest fixture |
| conftest 4 个 R73 fixture 死代码 | ✅ 仅 test_shared_fixtures.py 自引用 | 迁移或删 |
| verify_e2e search 9+ 次 | ⚠️ 修正为 **8 处直连**（L257/274/293/888/2135/2148/2169/2191），循环展开 ~12 次检查 | 按 §4.3 收窄 |
| verify_e2e designs 6 次 | ⚠️ 实测 **9 次**（文档低估） | 按 §4.3 收窄 |
| 纯 `status==200` 空转 ~40 处 | ❌ **不成立**：抽查 32 处全部带字段级断言；真实弱断言是 `len(x)>0`/`isinstance(x,list)` ~25 处 | §4.4 修正 |
| `section_design_quality_gate` 与单测逐字重复 | ❌ **不成立**：e2e 是真 HTTP 集成检查（含 M7/P1-1/F7 断言），单测是纯函数；仅 section_snapshot_health 重复属实 | 保留 gate（其依赖 engine/design_quality.py 为活跃门禁，不得删，§2.1）；删 snapshot_health（依赖顺序：先删 verify_e2e section + test_snapshot_service.py，再删 snapshot_service.py，§2.1 P0-1④） |
| test_ssl_session 无用 / test_p01_theme_css 范围外 | ✅ 准确 | 删除 |
| 注释掉的用例为 0 | ✅ 准确（grep 无匹配） | — |

### 4.2 测试组合并方案（6 强组 + 1 新发现，约 2,600 行）

| 组 | 文件数 | 实测清单 | 合并目标 | 预估节省 |
|---|---|---|---|---|
| **search** | 6 | test_z29_search（~282）、z20_search_sort（~150）、search_stock_by_code（~85）、us_search_fallback（~50）、search_budget_usname（~133，混测 F3-3/F3-7）、search_sector_index（~162） | **6→2**：z29 主文件吸收 fallback 双文件 + z20 排序；sector_index 保留 kind 契约独立 | ~420 |
| **pool_manager** | 4 | test_pool_manager（~254）、pool_manager_layer（~87，**复制实现**）、pool_manager_phase2（~124）、pool_manager_phase3（~124，主体是 pool_audit/adapter） | **拆归 3 文件**：pool 主体合并 phase2；layer 改调真实 `MarketDataHub._refresh_impl`（消除复制实现）；phase3 拆归 pool_audit/adapter 各自文件 | ~250 |
| **market_data_hub** | 4 | test_market_data_hub_pool（~105）、_news（~112）、_realtime（~112，10 个模板化 forward 用例）、test_market_context（~322，**归组错误**） | **3→1**（pool/news/realtime 合并，`_make_hub` 抽 conftest）；market_context 独立 | ~200 |
| **strategy_check** | 11 | fallback（~288）、llm_fallback（~46）、summary（~35，**与 llm_fallback 重复可整删**）、llm_timeout（~130，含 `inspect.getsource` 脆弱断言）、timeout（~85）、partial_data（~112，`_llm_timeout_for` 15/30/90 重断言）、divergence、industry、async（~51，弱）、round9_strategy_check（~100+，含复制实现）、z26_coverage（~190，strategy_env fixture 与 fallback **逐字重复** + 无效 patch） | **11→3**：①纯函数/超时分级合并（llm_fallback+summary+partial_data+llm_timeout）；②rule 兜底管线合并（fallback+z26+round9）；③async 弱测删除。`_build_llm_fail_summary` 4 文件、`_llm_timeout_for` 3 文件、strategy_env fixture 全部收敛 | ~700 |
| **news** | 11 | classification（~163）、level_classification（~65）、round9_news_level（~76）、impact（~55）、impact_content_fallback（~55）、impact_quality（~200+，`fake_run_json` ×8）、sort_order（~300+）、macro_filter（~56）、pipeline（~75+）、stock_news_keys（~100+）、heat_scope（~70+） | **11→3**：①level/stars 词表合并（classification+level+round9+macro_filter）；②impact 合并（impact+content_fallback+quality）；③sort_order/pipeline/keys/heat_scope 合并 | ~800 |
| **global_indices** | 2 | test_global_indices（~325）、test_global_indices_fix（~125） | **2→1** | ~150 |
| **TaskManager CRUD**（新发现） | 2 | test_design_tasks.py:15-62 与 test_task_db_persistence.py:30-146 同测六组 CRUD | **2→1**（保留更全的 test_task_db_persistence；test_design_tasks 中 design_worker 用例随 §2.1 design_tasks.py 删除） | ~80 |

> 注：标题「6 强组」+ 新增 TaskManager 组 = **7 组**；search 合并估算 420 含 fallback 双文件吸收，与 §4.1「_FakeSession 8 文件」口径一致。

### 4.3 verify_e2e 内部去重（约 300 行，从 ~2,278 → ~1,970）

| 端点 | 实测次数 | 去重目标 |
|---|---|---|
| `/market/search` | 8 处直连（展开 ~12 次） | **8→2**：保留 section_search（L2135-2157）一处；删 section_market L257-306（L257 与 L888 的 check_data_quality 重复）、L274/293 与 L2148/L2169/L2191 对消（hk/us-market section 的 00700/AAPL/茅台 均与 L274/293 重复） |
| `/portfolio/designs` | 9 处（实际请求约 13 次：limit=1×6 + limit=5×2 + 详情×5；**终审 M-1 修正**） | **9→3**（designs?limit=1 模式 L135/L350/L426/L1399/L1676/L2055 六处收敛） |
| `POST /design-async` | 5 次 | **5→2** |
| `/factors/ic` | 3 次 | **3→1** |
| `/factors/active` | 3 次 | **3→1** |
| `/admin/factor-health` | 3 次（含 3 次采样） | **3→1** |
| `/admin/sources/health` | 3 次 | **3→1** |
| `/market/indices/global` | 3 次 | **3→1** |
| `/health` | ~6 次 | 轮询内复调合理，保留 |

### 4.4 弱断言/复制实现/死代码（约 250 行）

- **`len(x)>0`/`isinstance(x,list)` 弱断言 ~25 处**（test_news_sort_order.py:93/145、test_news_pipeline.py:38/54/69、test_llm_circuit_breaker.py:105/115、test_system_diagnosis_fixes.py:215/229、test_design_optimization_plan.py:151/154/202/372/533/574、test_s5_remaining.py:62、test_etf_scanner.py:73/107 等）→ 升级字段级或删除（~60 行）**（归属 P1-8：随 6+1 组合并一并升级，不进 P0-4）**；
- **复制实现反模式 2 处**：test_pool_manager_layer.py:30-44 手写 `_apply_layer_assignment`、test_round9_strategy_check.py:30-38 手写三元表达式 → 改调真实函数（~60 行）**（归属 P1-8：随对应组合并同步消除）**；
- **脆弱源码断言 3 类**：test_search_stock_by_code.py:18-25 读 verify_e2e.py 源码、test_satellite_quality_gate.py:11 同、test_strategy_check_llm_timeout.py:94-96 `inspect.getsource`、test_phase2b_policy_mypy.py/test_async_lint.py AST 静态检查 → 合并/改造为契约测试**（归属 P1-8：随各组合并同步改造，不再保留 `inspect.getsource` 类断言）**；
- **空测试 2 处**：test_pool_manager.py:186-189、test_pool_manager_phase2.py:111-117（函数体仅 pass）→ 删除；
- **死 import 4 处**：test_pool_manager.py:7-8（patch/datetime）、test_pool_manager_phase3.py:6（datetime）、test_news_impact.py:5（json）、test_global_indices.py:5（json）→ 清理；
- **删除**：test_ssl_session.py（~30，测实现细节恒绿）、test_remaining_fixes.py:89-97 test_p01_theme_css（~10，后端测前端 CSS 越权）、section_snapshot_health（~25，与 test_snapshot_service.py L28-52 重复）。

### 4.5 死 fixture（conftest）

- `mock_akshare`（L46）、`mock_run_sync`（L57）、`mock_hub`（L69）、`mock_registry_health`（L94）**仅 test_shared_fixtures.py 自引用**（226 个业务测试 0 引用）→ **归属 P1-8**：① 优先迁移 `mock_hub` 替换 9 文件 FakeHub（§4.2 已列）；② 其余 3 个若无消费方则连带删 test_shared_fixtures.py（~150 行）；③ 不进 P0-4（避免与 P1-8 抽 conftest 冲突）；
- `task_db`/`task_mgr` 被约 14 文件广泛使用（非死，保留）。

---

## 5. 杂项冗余（脚本/配置/数据/契约，约 10,300–10,800 行 + 4.8–5.7 MB）

### 5.1 backend/scripts 一次性诊断脚本（约 1,363 行，归档 `scripts/archive/`）

**保留（AGENTS.md/pre-commit/生产引用）**：verify_e2e.py（2278，核心门禁）、data_health_check.py（183）、encoding_diagnosis.py（103）、check_api_usage.py（104，pre-commit:117）、audit_async_blocking.py（289，pre-commit:141）、smoke_startup.py（178，pre-commit:245）、sync_instruments.py（312，生产 import）、run_scheduler.py（60，round6 调度）、docker_smoke.py（80，已立项未接线）、check_routes.py（182，契约工具）、sync_indices/sync_indices_meta/sync_sectors.py（57/208/71，低频同步）。

**建议归档/删（一次性诊断）**：perf_diag.py（204）、_diagnose_factor.py（55）、_test_design_api.py（50）、explore_sector_sources.py（190）、news_level_audit.py（163）、probe_akshare_hk.py（36）、probe_hk_sectors.py（46）、repair_encoding.py（41，标注 One-time repair）、seed_indices.py（100）、verify.py（212，与 verify_e2e 功能重叠无引用）、audit_pool_usage.py（138，未接线）、check_perf_budget.py（128，CI 未接线）。

### 5.2 根目录脚本与一次性文件

- **保留**：start.ps1（95）、stop.ps1（52）、restart.bat（9，组合非重复）、start.bat（4，双击入口）、stop.bat（7，薄包装可选删）；
- **建议删/归档**：run_backend.bat（3，与 start.ps1 后端段重复）、run_profiled.bat（5，硬编码路径+诊断遗留）、run_diag.ps1（145，与 run_all_diagnostics.py 177 / trigger_design.py 224 / run_design_and_review.py 262 **四者功能高度重叠** → 四选一归档）、`start`（1 行文本文件 `com.docker.service`，疑似误创建异常文件，删）；
- **根目录一次性 Python 14 个**（全部无引用，归档/删，共 1,506 行）：`_apply_remaining_fixes.py`（159）、`_audit_sources.py`（47）、`_bench_cache.py`（16）、`_bench_stock_search.py`（24）、`_check_instr2.py`（13）、`_diagnose.py`（22）、`_test_llm.py`（96）、`_test_llm2.py`（135）、`_test_push2_full.py`（183）、`_test_push2headers.py`（68）、`_test_reasoning.py`（80）、`run_all_diagnostics.py`（177）、`run_design_and_review.py`（262）、`trigger_design.py`（224）。

### 5.3 Docker（无冗余，保留）

- docker-compose.yml：无未使用服务（redis/backend/frontend/backend-dev/frontend-dev 均有 profiles 区分），挂载/环境变量全部被使用；backend/Dockerfile 无重复层/无用 ARG；frontend/Dockerfile 两 stage 均被 compose 引用。**仅** `docker_smoke.py` 未接 CI（§5.1 已列）。

### 5.4 api-contracts 冗余（约 3,500–4,000 行）

- **明确可归档 3 个**：`analysis/design-v2-integration.md`（1,204B，标题误导、内容为旧 PoolManager 方案非端点契约）、`analysis/llm-provider.md`（1,348B，内容实为 Phase 4 链路复用与 LLM provider 无关）、`analysis/agents.md`（**表格段过时**：L20/L36 列 `POST /analysis/portfolio-design`、L23-24/L38-39 列 `/analysis/sector-analysis`/`symbol-analysis` 非 stream 版，实现中不存在 → 修订表格行或归档）；
- **重复契约待合并**：`market/search.md` + `search-sorting.md`（同一 `/market/search` 两版）；`market/sectors.md` + `sectors-concept.md` + `sectors-industry.md`（三份）；`portfolio/strategy.md` + `strategy-check-v2.md`；`portfolio/design.md` + `design-enhanced.md` + `design-degradation.md` + `design-v2-integration.md`（design-async 四份）；`factors/active.md` + `active-v2.md`（合并为 active-v2）；`market/watchlist.md` + `watchlist-v2.md`；`market/source-events.md` 与 `admin/sources.md`（跨目录重复 → 合并到 admin/）。

### 5.5 data 缓存路径重复（约 308 KB，P2 统一）

| 文件 | 根 `data/` | `backend/data/` | 备注 |
|---|---|---|---|
| `etf_list_cache.json` | 299,494 B（8/4 15:10） | 300,510 B（8/7 23:24） | 同缓存双份（§0.2-2：**均正常无乱码**） |
| `indices_cache.json` | 5,333 B | 5,550 B | 双份 |
| `etf_index_mapping.json` | 1,912 B | 2,335 B | 双份 |
| `portfolio.db` | **39,346,176 B（真主库）** | **0 字节空壳** | ⚠️ 若脚本误用 backend/data 路径会建空库 |

- **根因**：`config.py:11 _DATA_DIR = _PROJECT_DIR / "data"`（DB 用根 data/），但缓存写入路径分散——`etf_scanner.py:133`/`market_service.py:191`/`main.py:208-210`/`etf_scanner.py:675-677` 写 `backend/data/`；容器内走 `/app/data`（compose 挂载 `./data:/app/data`）→ **本地/容器路径不一致**；
- **P2 方案**：统一缓存路径（`DATA_DIR` 环境变量或缓存专用 `CACHE_DIR` 统一到根 `data/`），删除 backend/data 空 portfolio.db 与双份缓存。

### 5.6 临时文件/目录残留

- **`diag/`**（主目录 40 个 .py/.cjs + `n2/` 55 个 + `out/` 60 个 json，约 3,000+ 行 / 3-4 MB）：round8/9/10 诊断残留；**仅 `diag/out/logs_container/` 在 .gitignore:60，`diag/` 整体未忽略 → 可能被 git 跟踪** → **P0**：整目录归档或加入 .gitignore；
- **`data/_diag*.py` 21 个**（_diag_aheat.py…_diag_tasks_api.py）+ `_sse_parse.py`（约 550 行）：一次性诊断，已被 .gitignore:13 `data/` 覆盖 → 删除；
- **根目录 patch 文件 4 个**（patch_iss16.patch 53,910B / patch_market_tabs.patch 11,410B / patch_ui_polish.patch 7,814B / patch_ui_skeleton.patch 8,978B）：疑似已应用的临时补丁 → 移 docs/archived 或删（约 82 KB）；
- **一次性文本**：commit_msg_10_1.txt（720B）、tmp_gap.txt（1,775B）→ 删；
- **lighthouse_report.json 双份**：根目录 993,162B 与 data/lighthouse_report.json 1,010,607B → 删根目录副本。

### 5.7 .env 与依赖（无冗余，需同步）

- **.env.example 缺键**：OPENCODE_ZEN_API_KEY/MODEL/URL、LLM_PRIMARY_PROVIDER、LLM_FALLBACK_PROVIDER、LLM_PRIMARY_TIMEOUT、LLM_FALLBACK_TIMEOUT、TUSHARE_TOKEN、FRED_API_KEY、TWELVEDATA_API_KEY（.env:7-14/17/29）；.env.example 有而 .env 无：DATABASE_URL/BACKEND_PORT/FRONTEND_DEV_PORT/YFINANCE_PROXY → **P3**：.env.example 补齐（值用占位符），删除 BACKEND_PORT/FRONTEND_DEV_PORT（grep 无引用）；LLM_PROVIDER 两文件不一致（example=deepseek vs .env=opencode_zen）→ 同步；
- **frontend/package.json、backend/requirements.txt 均无未使用依赖**（全部 7+14 依赖与 requirements 各项均有使用点）。

---

## 6. 关键风险项（实施时优先处理）

1. **`backend/data/portfolio.db` 0 字节空壳**（§5.5）：真库在根 `data/portfolio.db`（39MB）——若任何脚本/配置误用 backend/data 路径会**静默建空库**。P0 删除空壳 + P2 统一缓存路径；
2. **`diag/` 未进 .gitignore**（§5.6）：诊断残留（含可能敏感数据）若被提交入库无法追溯。P0 归档 + 加 .gitignore；
3. **`api-contracts/analysis/agents.md` 过时**（§5.4）：表格列出的 3 个端点实现中不存在，误导新开发者。P0 修订/归档；
4. **`etf_scanner.ETF_CACHE_TTL=300` vs `CACHE_TTL["etf_list"]=3600` 不一致**（§2.3）：同缓存两个 TTL 语义冲突，可能造成缓存行为不可预期。P1 统一；
5. **`/indices/meta` 曾被审计误判待删**（§0.2-1）：UnifiedAnalysis.vue:409 在用——实施时**严禁删除**，避免回归。

---

## 7. 冗余总量汇总

| 类别 | 行数 | 体积 |
|---|---|---|
| 后端业务（backend/app） | ~2,300 | — |
| 前端（frontend/src） | ~2,000–2,400 | — |
| 测试（tests + verify_e2e） | ~3,200–3,900 | — |
| 杂项脚本（backend/scripts 归档 + 根目录一次性） | ~3,250 | — |
| 杂项契约（api-contracts 归档/合并） | ~3,500–4,000 | — |
| 临时文件（diag/ + data/_diag + patch/txt/lighthouse） | ~3,550 | ~4.5–5.4 MB |
| 重复缓存（data 双份） | — | ~308 KB |
| **合计** | **~1.8–1.9 万行** | **~4.8–5.7 MB** |

占比：后端 app（~4.3 万行）+ 前端 src（~1.6 万行）+ 测试（~3.1 万行）合计约 9 万行，冗余占 **17–20%**。

> **口径说明**（第二轮 review 修正）：§7 分项之和下限 = 2,300+2,000+3,200+3,250+3,500+3,550 = 17,800，上限 = 19,400；「合计 ~1.8–1.9 万行」与分项可加总。
> **方案行数归口**（与 §8 对应）：
> - **P0**（§8.1）≈ **1 万行** = P0-1（~1,644 联动删）+ P0-2（~1,700）+ P0-3（~320）+ P0-4（~100）+ **P0-5 归档（~6,300，含 scripts 1,363 + 根目录 1,506 + diag 3,000 + data/_diag 550 等）** + P0-6（契约，少量）；
> - **P1**（§8.2）**实际冗余远超表头「~1,300 行」**——P1-8 测试合并 2,600 + P1-9 verify_e2e 300 + P1-10 契约 3,500–4,000 即 >6,000；「~1,300」仅指 P1-1..7 代码抽取合并（`_cached`/`_safe`/format.js 等）的净行数，**测试/契约合并的减少量在 §7 分项中已计入**（测试 3,200-3,900、契约 3,500-4,000）。**排期口径**：P1 总工作量按「P1-1..7 代码抽取 ~1,300 + P1-8 测试合并 ~2,600 + P1-9 ~300 + P1-10 ~3,500」执行，表头「~1,300」为笔误级误导，实施时以本说明为准。
> - **P2/P3**：行为变更与门禁。**P2 行数 700→650（2026-08-08 决策定稿）**：P2-7 从「删 scaffold 40 行」修正为「仅清注释 1 行」（函数在用，审计误判已修正），其余决策（P2-1 合并/删路由、P2-2 单例、P2-3 接真实、P2-5 根 data/、P2-6 SourceRegistry、P2-4 重构）均已定稿，见 §8.3。

---

## 8. 清理方案（分级，未实施）

### 8.0 实施顺序总原则

先 P0（纯删除、零行为风险）→ 再 P1（抽取合并，改调用点需回归）→ P2（需产品确认的行为变更）→ P3（治理门禁）。每步独立提交，跑全量测试（后端 pytest 基线 1112、前端 vitest 390 + build）+ `verify_e2e.py` 确认无回归。

### 8.1 P0 纯删除（约 1 万行 + 4.8–5.7 MB，含联动删测试与脚本/diag 归档）

| # | 内容 | 细化步骤 | 验收 |
|---|---|---|---|
| P0-1 | 后端生产无引用文件（12 个，design_quality 保留） | 按 §2.1 联动清单执行：① 直接删 `macro_state.py`；② 删+连带删测试：ttj_fetcher（+test_ttj_fetcher.py、test_s5_remaining.py:71-91）、text_pipeline/b（+test_text_pipeline.py/b.py）、worker_registry+design_tasks（+test_design_tasks.py design_worker 用例）；③ 删+连带改测试：benchmark_stocks（改 test_design_new_modules.py:190-210）、market_router（删 test_market_context.py:315-322 + test_phase2b_policy_mypy.py:127-142）、market_data_adapter（改 test_pool_manager_phase3.py:61）、akshare_fetcher（改 scripts 两处 import——**注意顺序：先改 verify.py:151/sync_indices_meta.py:47 import 再执行 P0-5 归档 verify.py，或归档后免改**）；④ **依赖顺序**：先删 verify_e2e section_snapshot_health + test_snapshot_service.py 再删 snapshot_service.py；**design_quality.py 保留** | pytest 全量绿（删测试后以剩余数为准）；verify_e2e 全 PASS（design_quality_gate 仍生效）；rg 无残留 |
| P0-2 | 前端 14 个死组件/composables（§3.1） | ① rg 确认无生产引用；② 删 8 个均无引用（PageContainer/PageHeader/AppAvatar/AppBadge/SvgIcon/useChartView/useTaskPolling/fetchJson）+ 6 个仅测试引用（AppLayout/AppTable/AppPagination/AppToast/useMarketWS/useSectorAnalysis）；③ 同步改 App.spec.js/AppComponents2.spec.js/useMarketWS.spec.js/useSectorAnalysis.spec.js；④ 更新 useNewsWS.js:11 注释 | vitest 390 passed + build 绿 |
| P0-3 | 废弃端点 + 废弃 schema | ① 删 analysis.py:248-353 `/llm-report`、:356-380 `/llm-advice`、:383-404 `/llm-news-analysis`、:449-480 `/portfolio-review`（非 stream 版）；② 删 market.py:317-357 `/search/stocks`；③ ⚠️ **保留 `/indices/meta`**；④ 删 schemas.py:152-211 五个 DEPRECATED schema | 前端 build 绿（无调用断裂）；pytest 绿 |
| P0-4 | 空测试/死 import/越权测试 | 删 test_pool_manager.py:186-189、test_pool_manager_phase2.py:111-117 空测试；test_ssl_session.py；test_remaining_fixes.py::test_p01_theme_css；4 处死 import | pytest 绿 |
| P0-5 | 一次性脚本/临时文件 | ① backend/scripts 12 个一次性脚本移 `scripts/archive/`；② 根目录 14 个一次性脚本（11 个 `_*.py` + 3 个非 `_` 前缀：run_all_diagnostics.py/run_design_and_review.py/trigger_design.py，共 1,506 行；**终审 L-3 修正：14 已含全部，无重复计数**）+ run_diag.ps1 + run_profiled.bat + run_backend.bat + `start` 异常文件归档/删；③ diag/ 整目录归档 + 加 .gitignore；④ data/_diag*.py 21 个删；⑤ patch 4 个 + commit_msg_10_1.txt + tmp_gap.txt + 根目录 lighthouse_report.json 归档/删；⑥ backend/data/portfolio.db 空壳删 | git status 干净；diag 不再被跟踪 |
| P0-6 | 契约归档 | agents.md 表格段修订/归档；design-v2-integration.md、llm-provider.md 归档 | 人工核对 agents.md 表格端点与实现一致（check_routes.py 尚未接 CI，见 P3-5，P0 阶段用手工核对） |

### 8.2 P1 低风险抽取合并（表头 ~1,300 行，**仅指 P1-1..7 代码抽取**；测试合并 P1-8 ~2,600 + verify_e2e P1-9 ~300 + 契约 P1-10 ~3,500 另计，见 §7 口径说明）

| # | 内容 | 细化步骤 | 验收 |
|---|---|---|---|
| P1-1 | 统一 `_cached` ×4 | cache_service.py 加 `cached(key, producer, ttl_key)`；news/levistock/sector/macro_fetcher 改调用；单测断言缓存命中/失效 | 4 处调用点改造；相关 fetcher 单测绿 |
| P1-2 | 统一 `_safe/_exec/_ak/_call` ×5 | async_utils.py 加 `_safe_call`；5 处改调用；CancelledError 语义保留 | 全量 pytest 绿 |
| P1-3 | 三源 `_sync_fetch` 参数化 | factor_registry.py 抽 `_http_get_sync`；3 处改调用 | factor 单测绿（含 IOPV 链用例） |
| P1-4 | ws 样板抽 `_ws_loop` | ws.py 5 端点重构为循环 helper | ws 单测 + verify_e2e ws 检查绿 |
| P1-5 | 超时/TTL/映射常量归拢 | ① 超时并入 core/constants.py；② TTL 并入 CACHE_TTL，**先定 etf_list 300 vs 3600**；③ our_symbol→显示名共享表；④ push2 域名统一 | 无行为变化；常量引用一致 |
| P1-6 | 前端 utils/format.js | 抽 formatNum/formatChange/formatAmount/pad；9+ 处调用点改造 | vitest + build 绿 |
| P1-7 | 前端样式统一 | 删 text-up/text-down scoped 7 处 + btn scoped 6 处，统一走 theme.css/AppButton；修复颜色不一致 | build 绿；视觉走查无回归 |
| P1-8 | 测试 6+1 组合并 | 按 §4.2 合并表执行（search 6→2、strategy 11→3、news 11→3 等）；`_FakeSession`/FakeHub/fake_run_json 抽 conftest；消除复制实现（§4.4 归属本项）；**文件数目标修正：226→~199**（7 组合并净减 25（终审 L-1 修正，§4.2 表 4+1+2+8+8+1+1）+ 删 test_ssl_session/空测试等 ~2，合计 226-27≈199；≤170 不可达，已按实测修正） | pytest 全绿且用例数减少；文件数 226→~199 |
| P1-9 | verify_e2e 去重 | 按 §4.3 表执行（search 8→2、designs 9→3 等）；删 section_snapshot_health | verify_e2e 全 PASS；行数 ~2278→~1970 |
| P1-10 | 契约合并 | search/search-sorting 合并、sectors 三份合并、watchlist/watchlist-v2 合并、source-events 移 admin/ | 契约-路由一致性通过 |

### 8.3 P2 需产品/行为确认（约 650 行 + 2 项行为修复）——✅ 2026-08-08 决策定稿（用户采纳）

> **决策记录**：P2-1 合并到 FactorModelView 并删独立路由；P2-2 用 Pinia store 单例（接受进页不再强制刷新）；P2-3 接真实 wsConnected；P2-5 统一到根 data/；P2-6 走 SourceRegistry；P2-4 默认执行；**P2-7 已修正——不删函数，仅清注释（审计误判，函数在用）**。

| # | 内容 | 决策（已定稿） | 细化步骤 | 验收 |
|---|---|---|---|---|
| P2-1 | FactorICView/FactorModelView 合并 | **保留 FactorModelView 为唯一实现，删独立路由 `/factor-ic`**；⚠️ 复核修正：两组件**数据源不同**（ModelView 用 `getActive`、ICView 用 `getIC`），合并非同源去重，需把 IC 统计块并入 ModelView | ① 列两组件功能差异（ModelView 独有：分类折叠/IC 柱状图/reason tooltip；ICView 独有：重试按钮/简单表格）；② ModelView 增加 IC 统计展示块（复用 `factorsApi.getIC`）；③ 删 FactorICView.vue + router 路由；④ 迁移「重试」到 ModelView | 因子页功能不丢（active 列表 + IC 统计都在 ModelView）；build 绿 |
| P2-2 | useWarmupStatus 单例化 | **Pinia store 共享单实例**（接受进页不再强制立即刷新语义） | 新建 warmup store；App.vue 与 Dashboard.vue 改读 store；仅 store 内跑一个 5s 轮询 | warmup 请求量减半；行为一致 |
| P2-3 | App.vue 假「已连接」 | **接真实 wsConnected**（stores/market.js） | connectionStatus 改读 wsConnected；连接中断时显示「未连接」 | 导航栏状态真实 |
| P2-4 | connectTaskWs 抽 useTaskWS | **默认执行（纯重构）** | App.vue:201-296 抽 composable 与 useNewsWS 对齐 | 行为不变；代码一致 |
| P2-5 | 缓存路径统一 | **统一到根 data/**（CACHE_DIR 环境变量） | config.py 定 CACHE_DIR（默认根 data/）；etf_scanner/market_service/main.py 改路径；删 backend/data 双份缓存 + 空 portfolio.db 壳 | 本地/容器路径一致；无双份 |
| P2-6 | hk_hot_fetcher 走 SourceRegistry | **统一熔断语义**（保留现有冷却参数） | `_pick_host/_record_failure/_record_success` 改走 registry.route；回归港股板块 | 熔断行为一致；hk 单测绿 |
| P2-7 | scaffold 注释清理（原「因子删除」已修正） | **不删函数**——`_compute_premium_discount`/`_compute_tracking_error` 已在 _FACTOR_FUNCTIONS 注册在用；仅清误导性注释标题 | factor_registry.py:403 删除 `# --- Scaffolding functions (保留待后续数据源接入) ---` 注释行，改为说明「已注册在用」 | 注释不再误导；函数保留 |

### 8.4 P3 治理门禁（防再犯）

| # | 内容 | 细化步骤 | 验收 |
|---|---|---|---|
| P3-1 | 函数级 AST 未引用扫描进 CI | 写 `scripts/audit_unused_symbols.py`（AST 扫描 app 内函数/类/常量，排除 `__init__` 导出与字符串引用）；pre-commit 或 CI 定期跑 | 新死代码 0 增长；存量待清理清单可追踪 |
| P3-2 | purgeCSS 死样式验证 | 引入 purgeCSS（或 postcss-purgecss）对 theme.css/global.css 验证；结果入文档 | 死样式不再新增 |
| P3-3 | .env.example 同步 | 补齐 OPENCODE_ZEN/LLM 主备/TUSHARE/FRED/TWELVEDATA 占位符；删 BACKEND_PORT/FRONTEND_DEV_PORT（**删除前先同步 .env.example 移除对应行，避免删除后文档自相矛盾**）；**LLM_PROVIDER 两文件不一致（example=deepseek vs .env=opencode_zen）同步** | .env.example 与 .env 键集一致 |
| P3-4 | diag/ 入 .gitignore | .gitignore 加 `diag/`（替换仅 logs_container 的规则；**P0-5 ③ 已归档 diag/，此条为防再犯的持久化门禁**） | diag 不再被 git 跟踪 |
| P3-5 | 契约-路由一致性门禁 | check_routes.py 接入 CI（现状无引用）；断言 agents.md 表格端点存在 | agents.md 类过时契约必 FAIL |
| P3-6 | 测试冗余基线 | 测试文件数 226→~199（§8.2 P1-8 目标）后，设基线并进 pre-commit 检查 | 测试文件数不再反弹 |

---

## 9. 遗留待验证（后续轮次）

- `routers/admin.py`、`monitor/source_events.py`、`tasks/task_manager.py` 内私有函数级死代码（大文件未逐函数验证）；
- `analysis/llm.py`（82KB）、`factor_registry.py`、`market_data_hub.py`、`portfolio_service.py` 函数级未引用扫描（P3-1 的 AST 门禁跑通后自动覆盖）；
- `FactorICView` 与 `FactorModelView` 功能差异清单（P2-1 决策前需列出各自独有功能）。

---

## 10. 多轮 review 记录

### 第一轮（双路并行：技术准确性 + 结构一致性）

发现并修订 **H1/H2/H3 + M1-M6 + L1-L2**（29 项）：

- **H1（核心技术硬伤）**：「12 个无引用死代码文件」结论系统性失实——初报只扫 backend/app，漏扫 tests/scripts。实测仅 `macro_state.py` 真零引用；`design_quality.py` 被 verify_e2e.py:1694 门禁在用（**保留**）；`snapshot_service.py` 被 verify_e2e.py:1856 + test_snapshot_service.py 引用；其余 9 个被测试引用。§2.1 重写为逐文件实测引用表 + 联动删除清单（P0-1）。
- **H2**：§2.1 与 §4 对 design_quality/snapshot_service 判定自相矛盾——统一为「design_quality 保留、snapshot_service 按依赖顺序删」（§4.1 同步）。
- **H3**：P0 预估 3,900 行严重低估（实际 ~1 万行，含 P0-5 脚本/diag 归档 ~6,800 行）——§0.1/§0.3/§8.1 重估。
- **M1/M2**：体积口径统一为 4.8–5.7 MB（含缓存 308KB）；§7 合计修正为 ~1.8–1.9 万行（分项可加总），占比 17–20%，补口径说明。
- **M3**：测试文件数目标 226→≤170 不可达（7 组合并仅净减 ~27）——修正为 ~199（P1-8/P3-6）。
- **M4**：P0-6 验收依赖未接线的 check_routes——改为人工核对。
- **M5**：§2.4 行数 292→320（端点小计 250 + schema 60 + scheduler 25 + import 3）。
- **M6/L1**：AppLayout 归组修正（移入「仅测试引用」组）；§5.1 归档脚本行数 1,600→1,363；§4.2 标题「6 强组」实为 7 组、节省 2,500→2,600；§4.3 designs 统计口径注明（9 处/12 次请求）+ search 对消行号明确。

### 第二轮（复核）

第一轮修订确认全部修复（H 级 6 项 + 交叉引用 + 可实施性核对通过）。残留 **1 高 + 3 中 + 8 低**，全部修订：

- **高-1**：P1 表头「~1,300 行」与 §4.2 测试合并 2,600 + 契约 3,500–4,000 冲突——§7 口径说明重写：P0 拆分明细（P0-1..4 ≈4,000 + P0-5 归档 ~6,300），P1 明确「~1,300 仅指代码抽取，测试/契约合并量已在 §7 分项计入」，排期口径以说明为准；
- **中-2/3**：§4.4 弱断言/脆弱断言、§4.5 死 fixture 补归属步骤（P1-8），并注明不进 P0-4 避免冲突；
- **中-4**：§2.5 与 §9 重复段落——§2.5 精简为交叉引用；
- **低-5..12**：§0.2-3「9 测试+1 scripts」精确化、§0.2-4 措辞、ttj 联动措辞统一、P0-5 注明 3 个非 `_` 前缀脚本、P3-4 与 P0-5 关系注明、P3-3 补 LLM_PROVIDER 同步与删除顺序、§0.3 P2 补 P2-4、P0-1 补 verify.py import 改动的顺序依赖。

### 第三轮（终审）

终审子代理判定：**通过（可进入实施排期，不实施）**——前两轮 41 项（29+12）修复全部核实到位，四处口径自洽、P0-1 依赖顺序/交叉关系注明、方案可直接执行。

终审残留 **1 中 + 6 低**，已处理：
- **M-1**：§4.3 designs 实际请求 12→13 次（limit=1×6 + limit=5×2 + 详情×5 算术闭合）；
- **L-1**：P1-8 净减 26→25（§4.2 表逐组相加），文件数 226-27≈199 口径同步；
- **L-3**：P0-5 ② 明确「14 个一次性脚本（11 个 `_*.py` + 3 个非 `_` 前缀），无重复计数」；
- **L-4**：§4.4 复制实现 2 处补「归属 P1-8」；
- **L-6**：§0.3/§8.2 P1 表头补「~1,300 仅指代码抽取，测试/契约另计」提示；
- **L-2/L-5 归档**（措辞级，round12 复核）：L-2 占比 17-20% vs 20-21% 约数口径；L-5 §2.5 与 §9 文件列表仍重叠（已有「详见 §9」交叉引导，可接受）。

### 第四轮（P2 决策定稿，2026-08-08 用户逐项采纳）

与用户逐项讨论 P2 的 7 个决策点并全部定稿（§8.3 已更新为定稿版）：

| 项 | 定稿决策 | 备注 |
|---|---|---|
| P2-1 | 合并到 FactorModelView，删独立路由 `/factor-ic` | ⚠️ 复核修正：两组件**数据源不同**（ModelView=`getActive`、ICView=`getIC`），合并非同源去重，需把 IC 统计块并入 ModelView |
| P2-2 | Pinia store 单实例 | 接受「进页不再强制立即刷新」语义 |
| P2-3 | 接真实 wsConnected（stores/market.js） | 删硬编码 'connected' |
| P2-4 | 默认执行（纯重构抽 useTaskWS） | 无需产品决策 |
| P2-5 | 统一缓存到根 data/（CACHE_DIR） | 删 backend/data 双份 + 空 DB 壳 |
| P2-6 | hk_hot_fetcher 走 SourceRegistry | 保留现有冷却参数 |
| P2-7 | **不删函数，仅清注释标题** | ⚠️ 审计误判修正：`_compute_premium_discount`/`_compute_tracking_error` 已在 `_FACTOR_FUNCTIONS` 注册在用（round10 §5.5 折溢价率 IC=0.1321 生效） |

**连带修正**：§2.5 scaffold 描述（函数在用，非待接入）、§0.1/§0.3/§7 P2 行数 700→650（P2-7 删 40 行→清 1 行注释）。方案总数不变（P2 仍 7 项），总量口径不变（§7 审计冗余量不随方案行数变化）。
