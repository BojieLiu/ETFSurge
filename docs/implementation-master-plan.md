# ETF Surge 方案实施总计划

> 生成日期: 2026-07-31 | 版本: **v40.1**
> ✅ **Phase 40.1 已完成**（2026-07-31）：**LLM 超时三层对齐修复** — 日志取证确认服务商无故障（TCP/TLS 秒级成功，失败全为 ReadTimeout），根因为三层超时错位（provider 90s/60s、task_manager LLM 阶段 150s、design_report 内层 240s 永远够不到）；方案 A 对齐放宽：`.env` 与 `config.py` 默认值 `LLM_PRIMARY/FALLBACK_TIMEOUT 90/60 → 240/240`，`task_manager.py` LLM 阶段 `timeout=150 → 240`，免费模型高峰排队不再必然 partial。详见下方 v40.1。
> ✅ **Phase 40 已完成**（2026-07-31）：实施 `docs/z_fixes_design_v5.3.md` — **7 项问题修复**：Z22(watchlist 脏数据自愈：名称解析 + 独立会话回写 + symbol 格式/行情存在性校验 + name 空串兜底) + Z25(热门个股 volume/turnover/sector 补全) + Z26(策略检查规则引擎兜底：20s LLM 超时预算 + 覆盖率 100% + source 字段 + action 枚举硬约束) + Z05(共享 httpx.Client 连接池：4 处 urlopen 统一改造 + `/admin/sources/connection-pool` 握手可观测) + Z03(`/factors/active` 权威 status/reason/sample_count/last_computed_at，china_specific 静态因子 ic_value=null 不再硬编码 0) + Z11(design 降级契约：static_pool/partial_data 模式 + degradation 字段贯穿 + 静态池 STRATEGY_META 层预算等权分配 3 套方案) + Z20(搜索统一分档排序契约 `_sort_search_results`)。契约驱动 + TDD：新增 7 份契约（`api-contracts/`：watchlist-v2 / stock-hot-rank-v2 / strategy-check-v2 / ssl-connection-pool / active-v2 / design-degradation / search-sorting）+ 7 个测试文件 43 用例全 PASS，既有相关套件 69/70 PASS（唯一失败为基线即有的真实网络集成测试）。详见下方 v40.0。
> ✅ **文档归档（2026-07-29 v20.1）**：8 份已全部实施/已替代的方案文档归档至 `docs/archived/` — `optimization-master-plan.md`、`optimization-master-plan-v2.md`、`performance-diagnosis-and-optimization-plan.md`、`fix-plan-master.md`、`fix-plan-pool.md`、`s5-markethub-design.md`、`system-performance-and-quality-review.md`、`fundamental-flow-factors-evaluation.md`。
> ✅ **Phase 21 已完成**（2026-07-29）：修复 4 个前端单测失败（useMarketSearch + useSectorAnalysis mock 目标错误） + UI Phase 3(Steps 6-8)。详见下方 v21.0。
> ✅ **Phase 27 已完成**（2026-07-30）：实施 `docs/system-diagnosis-and-optimization-plan.md` 子集 — F1(timeline select 导入 P0) + F2(A股搜索降级 levistock P1) + F4(max_tokens 8192→12288) + F5(删除 reasoning_content fallback) + F19(因子 industry 注入) + F15/F16/F20/F22(verify_e2e 加固：跨市场搜索/M14 门禁/china_specific 完整性/预热门禁收紧)。契约驱动 + TDD：新增 `api-contracts/market/search.md` 与 `tests/test_system_diagnosis_fixes.py`（15 用例全 PASS）。详见下方 v27.0。
> ✅ **Phase 28 已完成**（2026-07-30）：推进 `docs/system-diagnosis-and-optimization-plan.md` 的**遗漏项 + 推迟项**。详见下方 v28.0。
> ✅ **Phase 29 已完成**（2026-07-30）：实施诊断方案 6 项修复 — Z01(import time 模块级) + Z02(US 行情：修复 Finnhub/TwelveData 函数名冲突 + FRED _API_BASE 覆盖) + Z03(china_specific IC 显示修复) + Z04(etf_specific 数据注入) + Z10(信号阈值放松 ±1.5) + Z11(设计熔断器静态池兜底)。契约驱动 + TDD：单测扩至 36 用例全 PASS。详见下方 v29.0。
> ✅ **Phase 30a 已完成**（2026-07-31）：实施 `docs/v5_diagnostic_and_optimization_plan.md` — Z21(WatchlistPanel.vue formatPct 修复) + Z23(fetch_hot_plates levistock 异常兜底) + Z24(LLMAdviceRequest 去重，仅保留一个带 market 字段的模型) + Z15(verify_e2e section_search 修复) + Z16(verify_e2e 新增 section_fundamentals)。详见下方 v30.0。
> ✅ **Phase 39 已完成**（2026-07-31）：实施 `docs/z27-task-persistence-redesign.md`（v2.1）— **任务持久化 DB 唯一真相源重构**：新增 `TaskRecord` 表；`TaskManager` 改 DB-backed async（删除 JSON 双轨 `tasks.json`），保留期 7 天/100 条；任务完成时 `record_id` 回写（design→`portfolio_designs.id`，check→`strategy_check_records.id`）；WS `task_update` 补齐 `record_id`+`task_type`；`GET /tasks/{id}` 补齐契约 11 字段；limit 默认值统一 20；启动收敛把遗留非终态任务标记 failed；前端 taskStore/App.vue/TaskIndicator/DashboardAiTools 适配（含修复历史列表 `checks` ReferenceError）。契约驱动 + TDD：更新 `api-contracts/portfolio/tasks.md`（§2.4.1 状态枚举 + §2.4.2 WS 契约），新增 `tests/test_task_db_persistence.py`（18 用例）+ 共享 fixture `tests/db_fixtures.py`，结构性适配 12 个既有测试文件；verify_e2e 新增 `task-persistence` 模块；后端 pytest（除 slow 网络）PASS、前端 273 用例 PASS + build 通过。详见下方 v39.0。
> ✅ **Phase 35 已完成**（2026-07-31）：实施 `docs/v5_z15_z29_implementation_design.md` — **Z29**（搜索自动补全不完善）：`search_hk_us` 重写为「静态基座(ETF+个股) + akshare 全量 spot 缓存 + ETF 实时 enrich」三级搜索，`include_stocks` 按分支生效，`asset_type` 统一为市场代码(HK/US)，默认模式跨市场合并(A股ETF→A股个股→HK→US，≤30)；前端 WatchlistPanel 传 include_stocks + selectSuggestion 回填 asset_type。**Z15**（verify_e2e 强化）：消灭恒过断言、新增 hk-market/us-market/factor-health 模块、section_fundamentals 严格化、sector rotation 门禁、修复 section_admin 重复定义。契约驱动 + TDD：新增 `api-contracts/market/search.md` v3.0 与 `tests/test_z29_search.py`（14 用例全 PASS），前端新增 WatchlistPanel.spec.js（4 用例）+ useMarketSearch 编码防护测试，npm run build 通过。详见下方 v38.0。
> ✅ **Phase 30b 已完成**（2026-07-31）：实施 `docs/v5_diagnostic_and_optimization_plan.md` 剩余项 — Z27(TaskManager persist path 修复) + Z26(策略检查 LLM prompt min_suggestions 下限) + Z17(板块轮动路由 `/sectors/rotation` + `/sectors` `type` 参数默认值防 422) + Z25(frontend API 新增 `getSectorRotation`)。契约驱动 + TDD：扩 `test_v5_diagnosis_fixes.py` 至 14 用例全 PASS。详见下方 v31.0。
> ✅ **Phase 20 已完成**（2026-07-29）：综合诊断剩余项 — F1(布林带列名前缀匹配修复 P0) + F2(板块默认限额 80→500 P1) + F3(ic_tracker 类型错误 P1) + 11 个新单测。详见下方 v20.0。
> ✅ **Phase 16 已完成**（2026-07-29）：P1/P2 剩余项 — S5(K线缓存统一) + S7(策略检查LLM报告) + S11(新闻重试) + S12(网易财经K线)。详见下方 v16.0。
> ✅ **Phase 15 已完成**（2026-07-29）：诊断计划 P0/P1 剩余项 — S1(CircuitBreaker废弃) + S2(shares_change数据注入) + S9(fund_shares字段)。详见下方 v17.0。
> ✅ **Phase 14 已完成**（2026-07-29）：诊断计划 P0 项实施 — S1(熔断器market_service接入) + S2(天天基金IOPV) + S3(本地快照兜底) + S4(chart列名修复) + S8(QQ Tencent IOPV降级)。详见下方 v14.0。
> ✅ **Phase 13e 已完成**（2026-07-29）：LLM Provider 链路诊断修复 — 移除熔断器误伤 + 修复 system_override 被静默丢弃。详见下方 v13.2。
> ✅ **Phase 13d 已完成**（2026-07-28）：诊断计划剩余项实施 — LLM 熔断保护 + 引擎级 fallback + 超时缩减 + 报告内容校验 + SSL 会话复用 + 预热退化告警。详见下方 v13.1。
> ✅ **Phase 13 已完成**（2026-07-28）：系统综合诊断与优化 — 基于 `docs/system-diagnosis-and-optimization-plan.md`。详见下方 v13.0。
> ✅ **Phase 12 已完成**：系统优化与质量保障 Phase 1-4 — 基于 `docs/archived/optimization-master-plan-v2.md`。详见下方 v12.0。
> ✅ **Phase 6.1 已完成**
> ✅ **Phase 6.2 已完成**：组合管线与报告质量修复 — Fix A (task_manager.py 校验降级)、问题 2 规则驱动风险检测 (portfolio_service.py _compute_risk_warnings)、test_decode.py (9/9 PASS)、TestP4 恢复、报告渲染排版优化 (DesignResult.vue CSS)。详见 `docs/design-report-quality-fix-plan.md`。：可观测性与系统增强 — ConfigManager + app_config 表（`models/app_config.py`, `core/config_manager.py`）、ConfigPage（`views/ConfigView.vue`）、Sector API 实时行情返回（market.py 路由优先级调整）、LLM 热点板块注入（llm_context.py + pool_manager.py）、stars 时间新鲜度 + Level 2 精度调整（news_fetcher.py + levistock_fetcher.py）、verify_e2e.py 扩展（stars/level 校验 + check_sector_data）。详见 §4 Phase 6.1。
> ✅ **Phase 7 已完成**：系统质量诊断修复 (system-quality-diagnosis)
> ✅ **Phase 11 已完成**（2026-07-28）：性能诊断与优化 — OPT-01~OPT-16 基于 `docs/archived/performance-diagnosis-and-optimization-plan.md`。详见下方 v11.0。
> ✅ **Phase 7 已完成**：系统质量诊断修复 (system-quality-diagnosis) — 池弹性 CRITICAL 日志 (`pool_manager.py:438`)、`/admin/metrics` 端点 (`admin.py`)、`get_portfolio_realtime()` 15s 缓存 (`market_service.py:617`)、`fetch_all_etfs_base()` 熔断路由 (`etf_scanner.py:264-282`)、`verify_e2e.py` 增强 (risk_warnings/response_time/metrics)、`test_performance_benchmark.py` (6 端点 gate)、`test_pool_resilience.py` (5 用例)。详见 `docs/archived/system_quality_diagnosis_report.md`§7。
> ✅ **Phase 8 已完成**：去重造轮子 (wheel-unreinvention) — `analysis/indicators.py` → pandas-ta、`factors/factor_registry.py` 11 个 compute 函数 → pandas-ta、`sentiment_fetcher.py` 动态权重 + 情绪惯量、`market_trends.py` 精简计算层、`risk_controls.py` 阈值配置化。新增 47 个单测。详见下方 §v9.8。
> ✅ **Phase 9 已完成**：剩余策略缺口闭环（2026-07-27 代码审计驱动）— Market Analysis Phase D(1-3): llm_advice_stream 新增 market 参数 (LLMAdviceRequest)、AiAdvisor.vue 传递 marketTab 到 API、build_full_context 按市场获取数据。Phase E(1-3): _build_report_prompt() 扩展为 6 节（含 0. 全景速览 + 5. 操作建议）、llm_report_stream 改为真流式 (agent.run_stream)、include_sectors=True 启用板块数据。Sector Phase 4: generate_advice() 改用 hot_plates/sector_heat、_build_design_report_prompt() 新增概念板块 + 热点板块段落。Phase 5: _inject_market_context() 公共函数。Phase 3b+6: useSectorAnalysis.js 涨跌幅颜色 helpers、api/index.js 新增 6 个板块 API 方法、SectorHeatMap.vue 组件。verify_e2e.py 新增 analysis 模块 + news/global 检查。API 清理：/hot-plates /stock-hot-rank /wind 前端标记已接入。
> ✅ **Phase 10 已完成**：收尾剩余任务（2026-07-27 第二次迭代）— SectorHeatMap.vue 嵌入 MarketAnalysis.vue（含快速栏「板块」按钮 + 锚点滚动）。verify_e2e.py section_portfolio 扩展 10 个新端点（calculate / daily-pnl / pnl-history / drift-check / export / tasks / timeline / apply-design）。Playwright 新增 7 个 spec 文件（09-portfolio-manager / 10-market-tabs / 11-watchlist / 13-ai-advisor / 14-sector-analysis / 15-symbol-analysis / 16-token-monitor）。
> 
> 总览 `docs/` 目录 **29 份活跃 + 归档**方案文档，梳理实施状态、冲突重叠、修复建议及分阶段执行路线。
> **新归档（2026-07-27 v10.3）**：`frontend-logic-sink-plan.md`（Sprints 1-4 全部完成）、`e2e-testing-plan.md`（16/12 spec 覆盖）、`factor-model-extension-plan.md`（IC 追踪器全部实施）、`sector-concept-optimization-plan.md`（Phase 1-6 全部实施）。
> v7.1：Phase 2.7 剩余项 + Phase 2.8 剩余项 + Phase 2.9 全部完成。新增 encoding_diagnosis.py、refresh_sentiment_cache()、AGENTS.md 关键路径更新。新增 llm_context.py build_full_context() 统一数据管道 + llm_report_stream/llm_advice_stream 改用统一管道。
> Phase 2.2→2.4 全部完成——33/33 核心因子全 LIVE（_CORE_FACTORS 列表共 33 个因子，均含真实 compute 函数，含 Phase 2.5 新增的 etf.return_1m/return_3m/price）、因子健康端点 + 因子单测门禁 + 运行时因子断言、分配器质量修复（ln_mcap 排毒、C2 条件修正、segment 归一化去重、预算重调、cross-section z-score 重归一化）。新增 Phase 2.5（原质量防护网 + AI 分析）。
> 新增文档 2 份：`archived/scaffold-factor-resolution-plan.md`（第 29 份，✅ 已实施）、`design-quality-review-20260725.md`（第 30 份，审计报告）。
> 💡 **关键依赖变化**：因子数据从 "15/26 LIVE" → **33/33 全 LIVE**（_CORE_FACTORS 共 33 个，均含真实 compute 函数：新增 etf.return_1m/return_3m/price，修 valuation 死代码 + momentum 聚合分类）。

---

## 目录

1. [文档全景看板](#1-文档全景看板)
2. [冲突与重叠分析](#2-冲突与重叠分析)
3. [修复方案](#3-修复方案)
4. [分阶段实施路线图](#4-分阶段实施路线图)
5. [附录：各方案摘要](#5-附录各方案摘要)

---

## 1. 文档全景看板

### 1.1 已完成

| 文档 | 说明 |
|------|------|
| `archived/design-optimization-plan.md` | `strategy_design.py` 重构 156 行（原 1092 行），纯函数策略引擎 `engine/` 包就绪 |
| `frontend-architecture-refactor.md` | 4 个大组件拆为 22 个子组件，composables 抽取完成 |
| `archived/issues-analysis-report.md` | 问题分析文档，对应的修复已在后续多轮 commit 中落地 |
| `fix-global-indices-plan.md` | **Phase 0 已实施**（onMounted + try/except + 缓存语义修复 + CSS 样式），见 2026-07-22~23 commits |
| `news-pipeline-fix-plan.md` P0 | **Phase 0 已实施**：`fetch_news_headlines()` 加 `id` 字段 + 前端 `handleNews()` 无 `id` fallback，见 `bd72bf6` (push-on-subscribe) + `d4062c2` |
| `frontend-performance-optimization.md` Step 1 | **Phase 0 已实施**：`main.js` 移除 ECharts 全局 import，首屏省 ~500KB |
| `archived/optimization-plan-20260721.md` | **Phase 0.5 已实施**（ETF 缓存 TTL + EM 直连 HTTP + akshare timeout 延长 + 策略检查 props/error/portfolio_type + 历史记录隔离/状态/徽标），见 `70a99f1` 及后续 5 个 commit |
| `design-pipeline-foundation-issues.md` | **Phase 0.7 已实施**（tracked_index + 因子分聚合 + 三方案差异化 + 风控修复 + 去重），见 `d478f12` + `cde3209`，15 个新单测全 PASS |
| `design-failure-and-strategy-check-review.md` | **Phase 0.8 已实施**（前端错误弹窗 + 动态建议上限 + 数据质量注入 + 测试修复 + 级联测试 + verify_e2e 增强），见 `ad3e12eb` |
| `async-boundary-fix-plan.md` | **Phase 0.9 部分实施**（见 commit `2be9ccb`：fix fetch_history + 线程池统一 + 冷却期修复 + 预热超时）。**2026-07-26 新版本**发现遗漏 Sina IOPV 阻塞点，待 Phase 2.6 |
| `design-check-pipeline-redesign.md` | **Phase 1.0 已实施**（顺序 Pipeline 替代 fire-and-forget + report_quality 分级 + 原子 DB 写入 + 崩溃恢复 + 8 个新集成测试），见 `4ff6084` + `7e93321` |
| `five-improvements-plan.md` | 4/5 项已实现——#2 `filter_extreme_drawdown` ✓、#3 `check_defense_effectiveness` ✓、#4 `remove_stale_candidates` ✓、#5 `_layer_phrase` 模板多样化 ✓；#1 统一市态判定仍待完成 |
| `remaining-issues-solution-design.md` | **全部 4 子项已实施**——S1-A(TTL 缓存) `53acbfa` ✓、S1-C(渐进状态机) `ef3de11` ✓、S2(混合归一化) `5116681` ✓、S3-B/C(WS 超时+清理) `ef3de11` ✓ |
| `archived/scaffold-factor-resolution-plan.md` | **全部实施**——7 个脚手架因子全部从 0→非零，33/33 核心因子全 LIVE（_CORE_FACTORS 列表），新增因子健康端点 + 运行时因子断言门禁（`2132a74`） |
| **Phase 2.2 数据管道根因修复**（v5.0 新增） | 发现 china_market.py 两个 import 错误（`source_registry` 路径错误、`utils.proxy` 路径错误）导致所有 `fetch_history` 调用静默失败→全部 26 因子为 0。修复后：技术面 10/10 LIVE、动量 3/10 LIVE、估值 2/2 LIVE（原均 0/—）。空池保护 + B3b 去重 + C2 风偏修正 + 入选理由重写 + IOPV 批量获取 + 新闻情感桥接 + decode_df 逐格修复 + DQ 门禁 + 前端错误态返回按钮 + E2E 回归测试 + 测试 teardown HTTP 泄漏防护。见 commits `e6264ee`~`1e63eab`（15 个改动）。 |
| `systematic-quality-review.md` | **新增 2026-07-26** 全量质量审查报告，识别 6 个质量问题（P0×2、P1×3、P2×1）：事件循环阻塞、设计方案空壳、因子数据缺失、置信度偏低、编码乱码、设计管线静默降级。修复计划见 Phase 2.7。 |

### 1.2 部分完成

| 文档 | 完成部分 | 未完成部分 |
|------|---------|-----------|
| `archived/design-report-optimization-plan.md` | 报告管道就绪、`_validate_report_consistency` 实现、WS 推送链路完整、`report_quality` 分级（full/fallback/none/pending）；A1（表格"因子"→"多因子评分"）已随 Phase 0.5 落地；管道升级为顺序 Pipeline（Phase 1.0） | A2（预期收益随市态调整）、B1-B3（LLM prompt 分析增强）、C1（全市场净流入信号）、C2（卫星层科技 ETF）—— 其中 A2/C1/C2 依赖因子分正常后验证效果 |
| `five-improvements-plan.md` | #2（极端下跌排除）+ #3（防御有效性）+ #4（freshness 检查）+ #5（理由多样化）已实现 | #1（统一市态判定）仍待完成，~15 行 |
| `market-awareness-and-data-source-plan.md` | Stooq 已在全球指数降级链中引用；§4 数据源替换已转入 `roadmap-data-source-unified.md`；**§5 市场感知联动已实施（Phase 5.1）**：MarketContext 数据类、market_router 路由层、多市场 regime 缓存、design-async 多市场参数、sector-analysis 市场感知、llm-report/stream 市场过滤 | ✅ **§5 已实施**（Phase 5.1）：`core/market_context.py` + `services/market_router.py` 新增，35 个新单测全 PASS。详见 §4 Phase 5.1 |
| `factor-model-extension-plan.md` | 因子注册表从 12 个扩展到 **~33** 个计算函数（当前 _CORE_FACTORS=33）；异步边界修复（Phase 0.9）后因子计算基于真实数据 | YAML 中 167 个远未全覆盖；IC 追踪器从未运行 |
| `design-check-quality-report.md` | 19 个问题中 **14 项已落地**：P0 全 4 项 ✅（_etf_history + meltdown→warning + INDEX_KEYWORDS + S1-A TTL 缓存）`53acbfa`；P1-1(三策略差异化) 通过 Phase 0.7 C1 + profile权重(`5116681`) + C2 名称基准分(`17e9cab`) + B3b概念去重(`17e9cab`) ✅；P1-3(强制标的进分配) ✅ `5116681`；P2-1→S2(混合归一化) ✅ `5116681`；P3-1(测试覆盖) ✅ test_data_health.py + DQ 门禁；P3-2(pre-commit) ✅ 增强 API 覆盖检查；P3-3(E2E 断言) ✅ verify_e2e.py `afaea68`；P3-4(监控脚本) ✅ data_health_check.py `ac6dd81` | **剩余 5 项**待实施（~1h）：P1-2(防御层分类→卫星层，~3行)、P1-4(risk_controls拼接bug，~1行)、P2-2(weight字段注入，~5行)、P2-3(摘要增强，~10行)、P2-4(target_weight默认值，~1行) |

### 1.3 已替代 (v2.0 新增)

| 文档 | 替代状态 | 替代者 |
|------|---------|--------|
| `archived/source-registry-optimization-plan.md` | **已替代** | `roadmap-data-source-unified.md` (Phase B/C) |
| `data-source-monitoring-plan.md` | **已替代** | `roadmap-data-source-unified.md` (Phase D) |
| `archived/review-20260720.md` | 评审记录，非实施方案 | N/A |

### 1.4 未开始（v4.0 更新）

| 文档 | 优先级 | 关键依赖 | 预估工时 | 备注 |
|------|--------|---------|:-------:|------|
| `design-check-quality-report.md` 剩余 P1-P3 | **P1** | 18/19 项已落地 | ✅ 全部完成 | Phase 1.1 全部实施（剩余 P2-4 target_weight 默认值已修） |
| `news-pipeline-fix-plan.md` P1 | **P1** | 依赖 P0 已实施（Phase 0 完成） | ~2h | — |
| `sector-concept-optimization-plan.md` | **P1** | Phase 1-2 独立可先行；Phase 4 依赖 LLM prompt 合并 | ~8h | — |
| `market-analysis-optimization-plan.md` | **P1** | Phase A-C 须按序；D/E 独立；Phase 0.7/0.9 已就绪 | ~13-19h | — |
| `frontend-ui-optimization-plan.md` | **P1** | 曾实现后回滚，需测试安全网就绪后重做 | ~8h | — |
| `frontend-testing-safety-net.md` | **P1** | 前端架构重构已就绪 | ~11h | — |
| `frontend-performance-optimization.md` (Step 2-3) | **P1** | Step 1 已实施（Phase 0）；Step 2-3 待做 | ~1.5h | — |
| `five-improvements-plan.md` #1 | **P1** | 独立，~15 行 | ~15min | — |
| `archived/scaffold-factor-resolution-plan.md` | **P1** | 已实施（✅ 7 个 scaffold 因子全部从 0→非零） | 0（已完成） | 已在 `e5b6139` 中落地 |
| `roadmap-data-source-unified.md` | **P2** | 整合三份原方案，实施顺序详见自身依赖图 | ~3-5天 | — |
| `config-management-plan.md` | **P2** | 无（独立） | ~8h | — |
| `archived/design-report-optimization-plan.md` A2/C1/C2 | **P2** | 依赖因子分正常（Phase 0.7 已完成） | ~2h | — |
| `e2e-testing-plan.md` | **P3** | 前端 UI 稳定后（避免维护成本过高） | ~16h | — |
| `factor-model-extension-plan.md` | **P0** | 实施就绪（v4.0 已重写） | Phase 7.1.1 | 当前版本 v4.0，反映 33 因子架构 + IC 追踪器激活方案 | 冲突与重叠分析

### 2.1 🔴 重大重叠：数据源改造三合一（已解决）

**涉及的文档**：
- `roadmap-data-source-unified.md` ← **已创建，替代以下三份**：
  - `archived/source-registry-optimization-plan.md`
  - `data-source-monitoring-plan.md`
  - `market-awareness-and-data-source-plan.md` §4

**状态**: ✅ 已解决。`roadmap-data-source-unified.md` v2.0 已发布，完成代码审计 + 冲突消除。

### 2.2 🔴 新冲突：两份新文档争夺同一代码域

**涉及的文档**：
- `market-analysis-optimization-plan.md` Phase D（增强 `/llm-advice/stream` 池管理器注入）
- `market-awareness-and-data-source-plan.md` §5（市场感知路由层 MarketContext）

**冲突点**：
- 两份方案都要改 `analysis.py` 的 `llm_advice_stream()` 和 `llm.py` 的 prompt builder
- market-analysis Phase D 有具体代码实现，market-awareness §5 是更宏大的路由层设计
- 如果先做 market-awareness §5（路由层），market-analysis Phase D 的改动需适配；反之 market-analysis 的改动要在市场感知路由层重复做

**修复建议 → 已通过 Phase 5.1 解决**：
- `market-awareness-and-data-source-plan.md` §5 市场感知联动已通过 Phase 5.1 全栈实施
- 新增 `core/market_context.py` + `services/market_router.py`
- 各端点均已增加 market 参数感知
- 在 `implementation-master-plan.md` 中 Phase 5.1 标记为 ✅ 已完成

### 2.3 🟡 重叠：两份文档同时修改 LLM 报告 prompt

**涉及的文档**：
- `market-analysis-optimization-plan.md` Phase E（在报告中添加「综合研判结论」+「操作建议」）
- `archived/design-report-optimization-plan.md` A2/C1/C2（预期收益调整、净流入信号、卫星层科技 ETF）
- `sector-concept-optimization-plan.md` Phase 4（LLM prompt 热点板块注入）

**重叠点**：
- 三份文档都修改 `_build_report_prompt()`（`llm.py`）
- market-analysis Phase E 改动 prompt 结构（增加 section 0 + 5）
- design-report 改动 prompt 内容（增加数据字段）
- sector-concept 改动 prompt 内容（增加板块排行段落）

**修复建议**：
- **先做 market-analysis Phase E**（增加 prompt 结构——综合结论、操作建议、跨周期对比要求）
- **再做 design-report 数据增强**（在已有结构框架内填充数据）
- **最后做 sector-concept Phase 4**（热点板块注入，具体段落插入到操作建议之前）
- 三份文档的 prompt 改动应**在同一个合并 session 中协调完成**，避免反复改同一文件

### 2.4 🟡 重叠：market-analysis Phase C 改动 MarketAnalysis.vue

**涉及的文档**：
- `market-analysis-optimization-plan.md` Phase C（UnifiedAnalysis.vue 合并 3 组件 → 4 卡片布局）
- `frontend-ui-optimization-plan.md` Phase 1-2（card 模板统一 + Tab 迁移）

**重叠点**：
- market-analysis Phase C 在 MarketAnalysis.vue 中删除 3 个组件引用、替换为 1 个
- frontend-ui Phase 1-2 在同一文件中手工 card → AppCard、手工 tab → AppTabs
- **同一文件被两份方案修改**，合并时会产生 git 冲突

**修复建议 → 先做 Phase C，再做 UI 优化**：
1. 先实施 market-analysis Phase C（组件合并，改变 DOM 结构）
2. 再在合并后的结构上实施 UI 优化（AppCard/AppTabs 替换）
3. 这样 Phase C 的 DOM 变动是"目标结构"，UI 优化在此基础上做替换，不会出现冲突

### 2.5 🟡 依赖：两份新文档需要验证扩展

**涉及的文档**：
- `news-pipeline-fix-plan.md` §8（验证方案：curl + WS 链路）
- `e2e-testing-plan.md`（Playwright E2E）
- `archived/optimization-plan-20260721.md`（verify_e2e.py 扩展）

**关系**：
- news-pipeline 的 WS 验证（`wscat`）当前没有自动化
- e2e-testing-plan 没有覆盖新闻 WS 推送场景
- optimization-plan 的 verify_e2e.py 扩展也没有覆盖 WS

**建议**：在 news-pipeline P0 修复后，立即更新 `verify_e2e.py` 增加 `--module news` 检查（含 WS id 字段检查），WS 链路的 E2E 可推迟到 e2e-testing-plan 实施时再做。

### 2.6 🟢 无冲突但有顺序依赖：前端三个优化方案

**涉及的文档**：
- `frontend-ui-optimization-plan.md`
- `frontend-performance-optimization.md`
- `frontend-testing-safety-net.md`

**关系**：这三个文档相互独立无冲突，但实施顺序有依赖建议：
1. **先做 testing**（给 UI 重构提供安全网）
2. **再做 performance**（`main.js` 删一行即可，极低成本高收益，与 UI 不冲突）
3. **再做 UI 优化**（需要测试防护来防止回滚重演）

### 2.7 🔴 新冲突：foundation-issues 与存量文档争夺同一代码域

**涉及的文档**：
- `design-pipeline-foundation-issues.md` Phase A/B（`pool_manager.py`、`etf_scanner.py`、`factor_registry.py`）
- `archived/design-optimization-plan.md` P1/P2/P3（`strategy_design.py`、`design_report.py`、`llm.py`）

**冲突点**：
- foundation-issues Phase A 改 `etf_scanner.py`（追加 `tracked_index`），Phase 0.5 的 `_fetch_em_etf_list()` 也在同一文件同一函数内新增了 EM 源——但两者改不同的字段/路径，**无实质冲突**。
- foundation-issues Phase B 改 `pool_manager.py`（因子分聚合 + 去重），design-optimization-plan 的 P1/P2/P3 也改 `strategy_design.py`/`llm.py` 传递更多数据给 LLM——**属于管道上下游关系，非冲突**：Phase B 修复后，P1/P2/P3 的 LLM 数据注入才有意义。
- foundation-issues Phase C3（`design_text` 修复）与 design-report-optimization 的报告管道有重叠——但 C3 是 DB 持久化诊断，design-report 是 prompt 内容增强，**技术路径不同，不冲突**。

**修复建议**：
- foundation-issues 的 Phase A/B 作为 Phase 0.7 优先实施（P0 级）
- design-optimization-plan P1/P2/P3 和 design-report 其余项**延到 Phase 0.7 之后验证效果**——因子分正常后，这些优化才真正有效
- 在 `implementation-master-plan.md` 中将 design-optimization-plan P1/P2/P3 的剩余工作从 Phase 1/2 移到 **Phase 1 (后置项)**

### 2.8 🟡 重叠：foundation-issues Phase A3（市场快照缓存）vs sector-concept Phase 1-2（板块缓存）

**涉及的文档**：
- `design-pipeline-foundation-issues.md` A3（写入 `_index_realtime_cache` + `_sector_momentum_cache`）
- `sector-concept-optimization-plan.md` Phase 1-2（行业+概念 concurrent 采集，写入 `_sector_momentum_cache`）

**重叠点**：
- 两份文档都要写 `_sector_momentum_cache` 这个字段
- foundation-issues A3 在 `pool_manager.refresh()` 末尾统一写入，是**最小化实现**（~50 行）
- sector-concept Phase 1-2 要重写 `compute_sector_momentum()` 增加概念板块、增加 APScheduler 刷新任务，是**完整方案**（~8h）

**修复建议 → 以 foundation-issues A3 为先，sector-concept 在 Phase 1 中扩展**：
1. 先实施 foundation-issues A3（写入基础设施，让 LLM 报告不再为空）
2. 在后续 Phase 1 实施 sector-concept Phase 1-2 时，**复用 A3 已建立的缓存写入点**，只替换 `compute_sector_momentum()` 的采集逻辑
3. 这样 A3 的 ~50 行不会被浪费，sector-concept 也无需重新设计写入口

### 2.9 🟢 foundation-issues B1（因子分聚合）是后续所有优化生效的前提

**涉及的文档**：
- `design-pipeline-foundation-issues.md` B1（因子分键名聚合）
- `five-improvements-plan.md` #1（统一 regime，依赖因子分正常）
- `archived/design-report-optimization-plan.md` A2/C1/C2（预期收益、净流入信号、卫星层科技 ETF）
- `strategy_check_worker.py`（策略检查模板化，P1-4 根因为因子分全为 0）

**关系**：
- B1 修复后 `factor_score != 0`，引擎排序正常 → 三方案差异化 → 策略检查数据充实
- B1 不依赖其他文档的改动，可独立先行实施
- 所有其他设计管线优化项**应先验证 B1 修复效果再投入**，避免在错误数据上做优化

**建议实施顺序**：
```
Phase 0.7: B1 → A1/A2 (tracked_index) → A3 (缓存写入)
              ↓
Phase 1: five-improvements #1 + design-report A2/C1 验证效果（C2 已实现基础版，详见代码分析）
              ↓
Phase 2: sector-concept Phase 1-2 (扩展板块缓存数据)
```

### 2.10 🟢 旧冲突状态更新（v3.0）

v2.0 中以下冲突已被后续实施落地或自然消解：

| 旧冲突 | 状态 | 说明 |
|--------|------|------|
| §2.4: market-analysis Phase C vs frontend-ui Phase 1-2 | ✅ 消解 | Phase 0.5 落地后，市场分析页面当前结构稳定，两方案可顺序实施 |
| §2.5: 验证扩展依赖 | ✅ 已覆盖 | verify_e2e.py 经修复后新增新闻模块检查 + WS 链路检查 |

### 2.11 🟢 sector-concept vs market-analysis Phase C 的兼容性

**涉及的文档**：
- `sector-concept-optimization-plan.md` Phase 3（Sector API 实时行情返回）
- `market-analysis-optimization-plan.md` Phase C（删除 SectorAnalysis.vue 组件）

**关系**：
- sector-concept Phase 3 在 `pool_manager.py` 和 `routers/market.py` 添加新 API，**不依赖前端组件**
- market-analysis Phase C 删除的是前端 `SectorAnalysis.vue`，但新的 `UnifiedAnalysis.vue` 仍支持 sector 类型分析
- **兼容性良好**：sector API 后端完成后，前端 UnifiedAnalysis.vue 直接调用该 API 即可
- 建议实施顺序：先做 sector Phase 1-3（数据后端），再做 market-analysis Phase C（前端合并）

---

## 3. 修复方案

### 3.1 冲突修复：数据源改造三合一（已解决）

`roadmap-data-source-unified.md` 已创建，替代三份原文档。无需进一步操作。

### 3.2 冲突修复：市场分析方案 vs 市场感知方案（2026-07-26 重新评估）

**2026-07-26 审计更新**：此前决策"以 market-analysis Phase D+E 替代 market-awareness §5"基于 Phase D+E 全部完成的假设。
经代码交叉验证，**该假设不成立**——Phase D+E 仅实现了后端数据管道统一层，**market-aware 的端到端数据流和 LLM prompt 增强均未完成**。

**新决策**：
- `market-awareness-and-data-source-plan.md` §5 市场感知联动已通过 **Phase 5.1 全栈实施**
- 新增 `core/market_context.py`（MarketContext 数据类）、`services/market_router.py`（5 个路由函数）
- `routers/analysis.py` 使用 MarketContext 按市场过滤；`routers/portfolio.py` design-async 接受 market 参数
- `services/pool_manager.py` regime 缓存改为 `dict[str,str]` 支持多市场
- 35 个新单测全 PASS

**处理方式**：
- `market-awareness-and-data-source-plan.md` §5 → **✅ 已实施（Phase 5.1）**
- `market-analysis-optimization-plan.md` → **状态保持 Partially**，Phase D/E 的 market 参数端到端传递已由 Phase 5.1 补齐

### 3.3 冲突修复：LLM prompt 三路合并

**决策**：三份文档（market-analysis Phase E、design-report A2/C1/C2、sector-concept Phase 4）都修改 `_build_report_prompt()`。
合并策略：

```
_build_report_prompt() 最终结构（合并后）
├── Section 0: 综合研判结论        ← market-analysis Phase E 新增
├── Section 1-4: 原有结构           ← 不变
├── Section 4b: 热点板块排行        ← sector-concept Phase 4 新增
└── Section 5: 操作建议            ← market-analysis Phase E 新增

数据增强（嵌入到各section中）：
- 预期收益随市态调整               ← design-report A2
- 全市场净流入信号                 ← design-report C1
- 卫星层科技 ETF 提示              ← design-report C2
```

### 3.4 重复归档

| 文档 | 标记 | 替代文档 |
|------|------|---------|
| `archived/source-registry-optimization-plan.md` | **已归档——被 roadmap-data-source-unified.md 替代** | `roadmap-data-source-unified.md` |
| `data-source-monitoring-plan.md` | **已归档——被 roadmap-data-source-unified.md 替代** | `roadmap-data-source-unified.md` |
| `archived/review-20260720.md` | 评审记录，非实施方案 | N/A |
| `market-awareness-and-data-source-plan.md` §4 | **已纳入 roadmap-data-source-unified.md** | `roadmap-data-source-unified.md` |

### 3.5 新冲突修复：foundation-issues 集成

**决策**：`design-pipeline-foundation-issues.md` Phase A/B 的修复项均为 P0 级，应在 Phase 0.5 之后、Phase 1 之前实施。

**处理方式**：
- foundation-issues Phase A（数据基础修复：tracked_index + 缓存写入 + 防御保底）→ **Phase 0.7 优先队列**
- foundation-issues Phase B（引擎修复：因子分聚合 + 去重 + 风控修复）→ **Phase 0.7 优先队列**，B4 仅 1 行可随时插入
- foundation-issues Phase C（质量提升：三方案差异化 + regime 映射 + design_text）→ **Phase 0.7 (C2/C3)** 或 **Phase 1 (C1)**，根据 B1 完成状态决定

**实施顺序**（详见 §4 Phase 0.7）：
```
A1/A2 (tracked_index, ~7行) → A3 (缓存写入, ~50行) → B1 (因子分聚合, ~30行)
→ B4 (行业集中度, ~1行) → B5 (防御权重门槛, ~30行) → B2/B3 (去重, ~55行)
→ C2 (regime映射, ~10行) → C3 (design_text, 排查)
→ C1 (三方案差异化, ~30行, 验证B1完成后)
```

### 3.6 重复归档更新（v3.0）

| 文档 | 标记 | 替代文档 | 说明 |
|------|------|---------|------|
| `fix-global-indices-plan.md` | **已实施**，移出冲突清单 | — | Phase 0 完成 |
| `archived/optimization-plan-20260721.md` | **已实施**，移出冲突清单 | — | Phase 0.5 完成 |
| `five-improvements-plan.md` | **4/5 已实施**，#1 待完成 | — | #2-#5 已落地，#1 作为 Phase 1 条目 |

### 3.7 增量阶段划分建议（v4.0，基于 v3.0 更新）

Phase 0 (✅ 已完成), Phase 0.5 (✅ 已完成), Phase 0.7 (✅ 已完成) 移出增量划分。

新增 Phase 0.8 / 0.9 / 1.0（均已实施）：

| 新增阶段 | 来源文档 | 内容 | 状态 |
|---------|---------|------|:----:|
| **Phase 0.8** | `design-failure-and-strategy-check-review.md` | 前端错误弹窗 + 动态建议上限 + 数据质量注入 + 测试修复 | ✅ 已实施 |
| **Phase 0.9** | `async-boundary-fix-plan.md` | 事件循环阻塞修复 + 线程池统一 + 冷却期污染 + 预热超时 | ✅ 已实施 |
| **Phase 1.0** | `design-check-pipeline-redesign.md` | 顺序 Pipeline + report_quality + 原子写入 + 崩溃恢复 | ✅ 已实施 |
| **Phase 2.1**（v4.2） | `remaining-issues-solution-design.md` + `design-check-quality-report.md` | 10/15 项已实施 | ✅ **已并入 Phase 2.2** |
| **Phase 2.2**（v5.0 新增） | 15 个修复项：数据源 import 修复 + 空池保护 + B3b dedup + C2 风偏 + 入选理由 + IOPV + 新闻情感 + change_pct + 编码 + DQ 门禁 + 前端返回 + E2E 回归 + teardown 防护 | 全部完成 | ✅ **全部完成** |
| **Phase 2.3**（v6.0 新增） | 4 项测试防护缺口修复 + 7 个脚手架因子全 LIVE + LLM fallback 增强。运行时因子断言门禁、因子健康端点、conftest _test_mode 重构、集成测试 marker | `e5b6139` `2132a74` | ✅ **已实施** |
| **Phase 2.4**（v6.0 新增） | 分配器引擎质量修复：ln_mcap 排毒、C2 条件修正、segment 归一化去重、预算重调；工作区：cross-section z-score 重归一化、segment 字段注入 | `4ace706` `98025ad` + 工作区 | ✅ **已实施** |
 
 现有轨道编号更新（原 Phase 1 → 移为 Phase 1.1，起始依赖前移经过 Phase 0.7-1.0）：
```
Track C: 新闻管道修复
├── P0 (WS id + 前端 fallback)    → Phase 0 (✅ 已实施)
├── P1 (新浪源 + 关键词修复)      → Phase 1.1（独立实施）
└── P2 (stars 新鲜度)             → Phase 6 可选

Track D: 市场分析重构
├── Phase A (统一搜索后端)          → Phase 1.1（可先行）
├── Phase B (统一分析编排)          → Phase 2（与 1.8 可并行）
├── Phase C (前端合并组件)          → Phase 3（依赖 A+B）
├── Phase D (AI 顾问流式+数据)      → Phase 2 或 3（独立）
└── Phase E (报告质量提升)          → Phase 3（独立，但 prompt 须与其他方案协调）

Track E: 数据管道质量提升
├── P0-1~P0-4 (_etf_history + meltdown→warning + INDEX_KEYWORDS + S1-A TTL) → ✅ 全部已实施 (53acbfa)
├── P1-1~P1-4 (差异化 + 分类 + 强制标的 + 拼接 bug) → ✅ 全部已实施 (Phase 0.7 + 1.1)
├── P2-1~P2-4 (混合归一化 + weight + 摘要 + target_weight) → ✅ 全部已实施 (Phase 2.1 + 1.1)
└── P3-1~P3-4 (DQ门禁 + pre-commit增强 + E2E断言 + 数据健康脚本) → ✅ 全部已实施 (a5028fa/c72b0ac/afaea68/ac6dd81)
```

### 3.8 增量阶段划分建议（v2.0/v3.0 存档）

> 以下为 v2.0 的原始轨道划分，保留供参考。实际以 §4 路线图为准。

```
Track C: 新闻管道修复（独立于其他任务）
news-pipeline-fix-plan.md
├── P0 (WS id + 前端 fallback)    → Phase 0（极低成本，高收益）✅
├── P1 (新浪源 + 关键词修复)      → Phase 1（独立实施）
└── P2 (stars 新鲜度)             → Phase 6 可选

Track D: 市场分析重构（新增大方案，建议走独立轨道）
market-analysis-optimization-plan.md
├── Phase A (统一搜索后端)          → Phase 1 或 Phase 2
├── Phase B (统一分析编排)          → Phase 2（与 A 可并行）
├── Phase C (前端合并组件)          → Phase 3（依赖 A+B）
├── Phase D (AI 顾问流式+数据)      → Phase 2 或 3（独立）
└── Phase E (报告质量提升)          → Phase 3（独立，但 prompt 须与其他方案协调）
```

<!-- v2.0 原始 Track C/D 已移至 §3.8 存档，此处不再重复 -->

---

## 4. 分阶段实施路线图

### Phase 0 — 快速胜利 ✅ 已完成

**状态**: ✅ 2026-07-22~23 已全部实施并验证。涉及 4 个方案的 7 项独立任务：

| # | 任务 | 源文档 | 状态 |
|---|------|--------|:----:|
| 0.1-0.3, 0.5 | 全球指数修复（onMounted + try/except + 缓存语义 + CSS） | `fix-global-indices-plan.md` | ✅ |
| 0.4 | `main.js` 移除 ECharts 全局 import | `frontend-performance-optimization.md` Step 1 | ✅ |
| 0.6-0.7 | 新闻 WS 推送修复（后端 id + 前端 fallback + push-on-subscribe） | `news-pipeline-fix-plan.md` P0 | ✅ |

**关键 commits**: `d4062c2` (push-on-subscribe), `bd72bf6` (news WS 链路修复), `c192711` (market calendar), `2beee3c` (美股 region), 及 global indices 系列.

**验证结果**: verify_e2e.py 全 PASS + 浏览器确认全球指数显示 + NewsView WS 推送正常。

### Phase 0.5 — 核心链路修复 ✅ 已完成

**状态**: ✅ 2026-07-22~23 已全部实施并验证。来源于 `archived/optimization-plan-20260721.md`，共 8 项任务，覆盖数据管道韧性 + 策略检查 + 历史记录。

| # | 任务 | 源文档 | 状态 |
|---|------|--------|:----:|
| 0.5.1-0.5.3 | ETF 数据管道韧性（缓存 TTL + EM 直连 + timeout 延长 + 预热） | `archived/optimization-plan-20260721.md` A1-A4 + B1-B2 | ✅ |
| 0.5.4-0.5.5 | 策略检查白屏/超时修复（props 补齐 + error_message 兼容 + portfolio_type 读取） | `archived/optimization-plan-20260721.md` C1-C3 | ✅ |
| 0.5.6 | 历史记录 Promise.all catch 隔离 | `archived/optimization-plan-20260721.md` D1-D2 | ✅ |
| 0.5.7-0.5.8 | 历史记录状态徽标 + 运行中合并 + WS design_id 回调 | `archived/optimization-plan-20260721.md` E1-E5 + F1-F3 | ✅ |

**关键 commits**: `70a99f1` (Phase 0.5 主体), `77e246a` (timeout + stale cleanup), `63522df` (back button), `431170c` (filter pills), `751bc30` (19 个新测试)。

**验证结果**: 设计生成正常跳转 + 策略检查不白屏/按所选组合执行 + 历史记录加载不整体白屏 + 状态徽标正确显示 + 19 个组件测试全 PASS。

### Phase 0.7 — 数据管道基础修复（P0 级，新增） ✅ 已完成

**来源**: `design-pipeline-foundation-issues.md`

**状态**: ✅ 2026-07-23 已全部实施并验证。涉及 10 项代码改动 + 15 个新单测。

**目标**: 修复数据管道的 4 个 P0 级 + 3 个 P1 级缺陷——因子评分、tracked_index、市场快照缓存、regime 映射、风控。

**背景**: Phase 0.5 解决了"数据能不能跑通"的问题。Phase 0.7 解决"数据是否正确"的问题。当前所有因子评分 = 0.0（键名不匹配）、三方案 ETF 完全相同（排序退化）、defense 层全是港股权益无真实防御（黄金/国债缺失）。

**实施顺序**: 严格按 A→B→C 顺序，每步完成后通过对应 V# 验证。

| # | 任务 | 对应修复 | 文件 | 预估 | V# 验证 |
|---|------|---------|------|:----:|:-------:|
| 0.7.1 | 追加 tracked_index（EM 源） | P0-2 A1 | `etf_scanner.py:137-147` | ~5行 | V1 |
| 0.7.2 | 透传 tracked_index（pool 管道） | P0-2 A2 | `pool_manager.py:133-139` | ~2行 | V1 |
| 0.7.3 | 写入市场快照缓存（指数 + 板块动量） | P0-3 A3 | `pool_manager.py` 新增 `_refresh_market_snapshot()` | ~50行 | V4 |
| 0.7.4 | 因子分键名聚合（点分键→顶层键） | P0-1, P0-4 B1 | `factor_registry.py` 新增 `_aggregate_factor_scores()` | ~30行 | V3 |
| 0.7.5 | 防御资产强制保底（黄金/国债） | P1-3 A4 | `pool_manager._ensure_mandatory()` 复用已有逻辑 | 0行 | V5 |
| 0.7.6 | 行业集中度风控修复（industry 字段） | P1-1 B4 | `risk_controls.py:172` 一行：`layer`→`industry` | ~1行 | V8 |
| 0.7.7 | 防御层最小权重门槛（≥2%） | P1-3 B5 | `risk_controls.py` 新增 `_consolidate_minnows()` | ~30行 | V6 |
| 0.7.8 | 候选池去重（同指数保留规模最大） | P1-2 B2 | `pool_manager.py` 新增 `_deduplicate_by_index()` | ~40行 | V2 |
| 0.7.9 | 分配引擎去重保护 | P1-2 B3 | `allocation_engine._select_and_weight` 加 `selected_indices` | ~15行 | V2 |
| 0.7.10 | regime 映射修复（key 对齐） | P0-5 C2 | `pool_manager._LAYER_WEIGHTS` 表 key ≈ `get_market_regime()` 返回值 | ~10行 | V10 |
| 0.7.11 | design_text 持久化修复（排查+修复） | P2-1 C3 | `task_manager.py` / `design_report.py` 诊断 WS write-back | 排查 | V9 |
| 0.7.12 | 三方案差异化（C1，依赖 B1 完成后验证） | P1-2 C1 | `allocation_engine.allocate()` 按 `profile_key` 过滤卫星候选 | ~30行 | V7 | ✅ |

**关键 commits**: `db8197b` (Phase 0.7 全部改动)。

**验证结果**: 15 个 Phase 0.7 单测全 PASS + 34 个存量测试全 PASS（4 个 pre-existing 失败非本阶段改动引起）+ API 字段确认。

**依赖关系**:
```
0.7.1 → 0.7.2 → 0.7.8  (tracked_index 链)
0.7.4 ─────────────→ 0.7.12  (因子分正常后三方案差异化)
0.7.4 → [后续所有依赖因子分的优化]
```

**验证**: 实施后跑 `verify_e2e.py` + 针对 V1-V10 逐项检查。详见 foundation-issues §5 验证标准表。

### Phase 0.8 — 设计失败修复与策略检查增强 ✅ 已完成

**来源**: `design-failure-and-strategy-check-review.md`

**状态**: ✅ 2026-07-24 已全部实施并验证。共 7 项修复 + 3 个新测试文件/增强。

| # | 任务 | 源文档 | 关键 commit |
|---|------|--------|:----------:|
| 0.8.1 | 前端错误详情弹窗（AppModal） | §2-方案1 | `ad3e12eb` |
| 0.8.2 | 动态建议上限（持仓分档 5/8/12） | §2-方案2 | `ad3e12eb` |
| 0.8.3 | 数据质量元信息注入 prompt | §2-方案3 | `ad3e12eb` |
| 0.8.4 | 单测修复（mock 路径 + error-dict 测试） | §2-方案4 | `ad3e12eb` |
| 0.8.5 | 级联故障集成测试（test_design_cascade_failure.py） | §2-方案5 | `ad3e12eb` |
| 0.8.6 | verify_e2e 增强（候选池探针 + INFRA/BUG 区分 + 质量断言） | §2-方案6 | `ad3e12eb` |
| 0.8.7 | 候选池修复（china_market ETF 数据源 + Sina 降级） | §4 — | `8894537` |

**验证结果**: 10 个涉及文件改动，252 行新增，37 行删除；所有存量测试 + 新增测试全 PASS。

### Phase 0.9 — 异步边界修复与线程池统一 🟡 部分完成

**来源**: `async-boundary-fix-plan.md`（v1.3，2026-07-24）

**状态**: 🟡 部分实施（commit `2be9ccb`）。`fetch_history`→`asyncio.to_thread` 修复完成，但**同函数的 Sina IOPV 批量获取遗漏**。2026-07-26 重写文档为 v2.0（最终版），剩余修复见 Phase 2.6。

| # | 任务 | 对应修复 | 文件 |
|---|------|---------|------|
| 0.9.0 | 修复 `_fetch_market_data` 同步 await（P0） | `fetch_history`→`asyncio.to_thread` + Semaphore(8) | `factor_registry.py` |
| 0.9.1 | 统一线程池 — `run_sync` 改用 `_shared_executor`（P1） | 默认 executor→共享池 32 workers | `async_utils.py` |
| 0.9.2 | 冷却期污染修复（P1.5） | `_last_refresh_ts` 失败后清除 | `pool_manager.py` |
| 0.9.3 | 启动预热加超时保护（P2） | ETF 缓存 + 因子导入加 `wait_for(60)` | `main.py` |
| 0.9.4 | full_pipeline 超时 120→45s + 耗时日志（P3） | 快速失败 + 可观测性 | `pool_manager.py` |
| 0.9.5 | 测试防护增强（P4） | async_boundaries + async_lint + verify_e2e 增强 | 3 个测试文件 |

**关键 commit**: `2be9ccb`（10 文件，493 行新增，119 行删除）。

**验证结果**: 事件循环响应测试 PASS、AST lint 扫描 PASS、verify_e2e 线程池断言 PASS、服务重启后健康检查正常。

### Phase 1.0 — 设计/策略检查顺序管道重构 ✅ 已完成

**来源**: `design-check-pipeline-redesign.md`

**状态**: ✅ 2026-07-24 已全部实施并验证。12 个文件改动，588 行新增。

| # | 任务 | 说明 |
|---|------|------|
| 1.0.0 | PoolManager NameError 修复 | `task_manager.py` 中 `_generate_and_save_report` 的 `pool_manager` 未 import |
| 1.0.1 | 顺序 Pipeline 替代 fire-and-forget | `design_pipeline()` 5 阶段顺序执行 + WS 推送进度 |
| 1.0.2 | `strategy_check_pipeline()` 重构 | 同理，WS 进度推送 |
| 1.0.3 | `report_quality` 分级 + DB 模型扩展 | pending/full/fallback/none，`report_generated_at` 时间戳 |
| 1.0.4 | 去除嵌套超时（单层 provider timeout） | strategy_design.py 30s + portfolio_service.py 45s 移除 |
| 1.0.5 | 崩溃恢复 — `report_quality="pending"` 记录 | main.py lifespan 扫描 >5min 的 pending→fallback |
| 1.0.6 | 前端 report_quality 驱动 UI 状态 | 移除 60s 硬编码 `reportStale` 猜测 |
| 1.0.7 | 8 个新集成测试 + verify_e2e 增强 | test_design_pipeline_integration.py |
| 1.0.8 | Provider 超时调整（primary 90s, fallback 60s） | 原均为 120s |

**关键 commits**: `4ff6084`（管道重构主体）、`7e93321`（前端 report_quality 状态驱动）。

**验证结果**: 8 个 pipeline 集成测试全 PASS；verify_e2e `design_text` 检查升级（长度+内容）；POST /design-async 返回完整报告率从 0% 提升到预期 >90%。

### Phase 1.1 — 数据层增强 & 统一市态（P1）✅ **全部完成**

**状态**: ✅ 2026-07-25 全部实施并验证。共 7 个 commit（`1f6d00e`~`89862be`）。

**前置依赖**: Phase 0.7~1.0 完成（因子分正常 + 管道可靠 + 异步边界修复 + 报告分级）

#### 计划内任务
| # | 任务 | 源文档 | 落地方式 | commit |
|---|------|--------|---------|:------:|
| 1.1.0 | 统一市态判定 | `five-improvements-plan.md` #1 | `portfolio_service.py:406-409` 调用 `pool_manager.get_market_regime()` | — |
| 1.1.1 | Sector 概念板块数据采集 | sector-concept Phase 1 | `market_trends.py`: `_compute_industry_momentum()` + `_compute_concept_momentum()` 合并输出 | `1b6cdb0` |
| 1.1.2 | PoolManager sector_cache 扩展 | sector-concept Phase 2 | `update_sector_cache()` + `_hot_plates_cache`/`_sector_heat_cache` | `1b6cdb0` |
| 1.1.3 | 板块数据 60s 定时刷新 | sector-concept Phase 2 | `tasks/sector_refresh.py` + `main.py` 后台 `asyncio.create_task` 循环 | `1b6cdb0` |
| 1.1.4 | 新闻关键词分类修复 | news-pipeline-fix P1.1+P1.2 | `levistock_fetcher.py`: 移4中性词, 清冲突词 | `8c18858` |
| 1.1.5 | `fetch_sina_roll_news()` HTTP 源 | news-pipeline-fix P1.3 | `news_fetcher.py`: 新浪 HTTP 直连, requests+no_proxy, 5s 超时 | `8c18858` |
| 1.1.6 | 重写 `fetch_macro_news()` 降级链 | news-pipeline-fix P1.4 | 三级: 新浪→CLS→财联社; 删除 CCTV/百度(≤24s) | `8c18858` |
| 1.1.7 | 重写 `fetch_global_news()` 降级链 | news-pipeline-fix P1.5 | RSS→akshare global_cls, 加每源独立日志 | `8c18858` |
| 1.1.8 | market-analysis Phase A（统一搜索） | market-analysis §3 | `GET /market/search` 已多源; 新增 `market=A` 参数支持个股搜索 | `030c739` |
| 1.1.9 | market-analysis Phase B（编排端点） | market-analysis §4 | 各 analysis streaming 端点已就绪 | — |
| 1.1.10 | P1-2: 防御层分类修复 | design-check-quality §3 P1-2 | `pool_manager.py:328-333`: 跨境→卫星层 | — |
| 1.1.11 | P1-4: risk_controls 拼接 bug | design-check-quality §3 P1-4 | `risk_controls.py:43-44`: 明确括号 | — |
| 1.1.12 | P2-2: holdings_analysis 注入 weight | design-check-quality §3 P2-2 | `portfolio_service.py:498-500`: weight_map 回填 | — |
| 1.1.13 | P2-3: 策略检查摘要增强 | design-check-quality §3 P2-3 | `portfolio_service.py:514-533`: 市态+行业+数据质量 | — |
| 1.1.14 | P2-4: target_weight 默认值 | design-check-quality §3 P2-4 | `models/portfolio.py`: Column `default=0.05` | `8c18858` |

#### 额外新增（超出原计划范围）
| 改項 | 说明 | commit |
|------|------|:------:|
| Sina 时间戳 ISO 格式转换 | `datetime.fromtimestamp(ts)` 替代 `str(ctime)`，解决跨源按字符串排序错乱 | `030c739` |
| Sina 正文内容 | `summary`→`intro`→`content` 三级降级；实际数据中 `intro`~70字 | `030c739` |
| RSS 正文内容 | 新增 `summary` 作为 `content` 字段（~150字） | `030c739` |
| 文章 URL 透传 | 新浪(`url`/`wapurl`)、RSS(`link`) 传入 `url` 字段 | `89862be` |
| 前端「查看原文」链接 | NewsView.vue 在 `item.url` 存在时显示链接，`target=_blank` | `89862be` |
| 搜索添加 `market=A` 参数 | `/market/search` 支持 `market=A` 查个股，返回 `type:"stock"` | `030c739` |
| `test_risk_controls.py` | 重写, 14 个测试覆盖 P1-4 回归/drawdown/defense/stale/minnows | `0733690` |
| `test_portfolio_model.py` | 6 个测试覆盖 default/schema 验证 | `0733690` |
| `test_news_pipeline.py` | 4 个测试覆盖三级降级链行为 | `0733690` |
| `test_pool_manager_layer.py` | 8 个测试覆盖行业→层映射 | `0733690` |
| `test_news_classification.py` 增强 | +5 反向断言(中性词不标利空/异动词精度) | `0733690` |

**剩余验证项**（所有项目已验证通过）:
- ✅ LLM 报告不再显示"暂无板块热力数据"（概念+行业双源）
- ✅ 新闻源日志含 `[news] 新浪财经返回 N 条`，宏观源耗时 ≤24s → ~0.3s
- ✅ `GET /market/search?keyword=茅台&market=A` 返回 `type:"stock"` 结果
- ✅ 策略检查 regime 与设计方案一致（统一 `pool_manager.get_market_regime()`）
- ✅ 防御层黄金/国债归防御层，跨境/港股归卫星层
- ✅ risk_controls 入选理由无拼接错误 | holdings_analysis 含 weight | target_weight 默认 0.05
- ✅ 新闻展示财联社/新浪财经/RSS 三源混排，时间从新到旧

### Phase 2.1 — 数据管道质量提升 ✅ **全部完成（合并入 Phase 2.2）**

> **v5.0 更新**：Phase 2.1 已全部完成，所有 15 项已实施。新增 Phase 2.2 包含本轮 session 全部 15 个修复。
> 
> **前置依赖**: Phase 0.7~1.0 完成

**已实施项（✅ 15 项，含 6 项新增未规划）**：

| # | 项 | 提交 | 说明 |
|---|------|:----:|------|
| S1-A | TTL 60s 缓存 | `53acbfa` | pool_manager.refresh() 60s TTL，二次点击不触发 I/O |
| S1-C | 渐进状态机（quick_ready + completed_with_errors） | `ef3de11` | 分配完成即推送方案，LLM 报告后台继续 |
| S2 | 混合归一化（因子分 5x 放大 + profile 权重 + 强制下限） | `5116681` | z-score×5 + 三层差异化权重 + 强制标的不低于 5% |
| S3-B/C | WS broadcast 5s 超时 + 60s 清理 | `ef3de11` | 慢客户端不阻塞整体广播；自动清理僵尸连接 |
| P0-1~P0-3 | _etf_history + meltdown→warning + INDEX_KEYWORDS | `53acbfa` | 管道基础质量修复 |
| P1-1 | 三策略差异化 | 多 commit | Phase 0.7 C1 + profile权重 `5116681` + C2 风偏分 `17e9cab` + B3b 去重 `17e9cab` |
| P1-3 | 强制标的进分配（MANDATORY_MIN_WEIGHT） | `5116681` | 5% 权重下限 + 扣现金/非强制等比例降 |
| P3-2 | pre-commit 增强（API 调用覆盖检查） | `c72b0ac` | 检测前端定义了但未调用的 API 方法 |
| P3-3 | verify_e2e 增强（数据质量断言 + 任务一致性） | `afaea68` | 逐区域价格存在性检查 + 任务列表一致性 |
| P3-4 | 数据管道健康检查脚本 | `ac6dd81` | `scripts/data_health_check.py` 5-section 检查 |
| 🆕 | F10 tracked_index 补充 | `17e9cab` | `enrich_tracked_indices()` 东方财富网页爬取 + JSON 缓存 |
| 🆕 | C2 名称风偏基准分 | `17e9cab` | `_select_and_weight` 估值数据稀疏时按名称 +/- 补偿 |
| 🆕 | 新闻情感桥接 | `a5028fa` | pool_manager step 3c 注入 news_heat/news_direction sentiment |
| 🆕 | IOPV 批量 + change_pct 因子 | `783e188` | Sina 批量 NAV 抓取 → premium_discount 可用 |
| 🆕 | DQ 测试门禁 | `a5028fa` | DQ1-DQ5 防止回归 |
| 🆕 | verify_design.py 验证管道 | `afaea68` | `scripts/verify_design.py` 验证管线输出 |
| 🆕 | china_market.py import 修复 | `e6264ee` | `source_registry` 路径改正 + `utils.proxy` 路径改正 → 因子数据恢复正常 |

### Phase 2.2 — 数据管道根因修复与测试门禁 ✅ **全部完成（v5.0+v6.0 扩展）**

> 发现并修复了导致所有因子数据为 0 的根因（china_market.py import 错误），完成 15 个改动项。
>
> 修复前：因子全 0（26/26 STUB）、空池常报、策略不分、入选理由占位符"今日%"、同指数 ETF 重复。
>
> 修复后：技术面 10/10 LIVE、动量 3/10 LIVE、估值 2/2 LIVE、空池保护、策略差异化、指数概念去重（B3b）、入选理由使用真实 RSI/MACD 因子分、IOPV 批量获取 → premium_discount 可用、新闻情感桥接 → sentiment 非零、DQ 测试门禁、E2E 回归测试。

**来源**: 本轮 session 15 个修复项（commits `e6264ee`~`1e63eab`）

**关键 commits**: `e6264ee`（空池保护 + C2 + B3b + 入选理由 + DQ 门禁）、`783e188`（IOPV + change_pct）、`0b2187f`（编码修复 + repair_encoding.py）、`9fc0c11`（新闻情感 + conftest 防护）、`547a698`（E2E 回归）、`1e63eab`（data_health 兼容）

**测试验证**:
- test_design_optimization_plan.py: 19 个（DQ1-5 + P0-4）✅ 15 passed
- test_pool_manager.py: 11 个 ✅ 11 passed
- test_integration_pipeline.py: 1 个 ✅ 1 passed（25.5s）
- test_risk_controls.py: 7 个 ✅ 7 passed
- 前端 npm run build: 730 modules ✅

### Phase 2.3 — 脚手架因子全 LIVE + 测试防护缺口修复 ✅ **全部完成（v6.0 新增）**

> 从 P3-1/3-3 的剩余缺口出发：原有 26 个核心因子中仍有 7 个为 0（硬编码 scaffold），测试防护缺少运行时断言 + 因子健康端点 + conftest 重构 + 集成测试。
>
> **修复前**：26/26 STUB（v5.0 后 15/26 LIVE，11 个 scaffold 仍为 0），`test_core_factors_no_scaffold` 门禁未通过，conftest mock 阻碍集成测试。
>
> **修复后**：33/33 全 LIVE（`e5b6139`：7 个 scaffold → 非零 + 后续新增 KDJ/信号/政策因子 + Phase 2.5 新增 etf.return_1m/return_3m/price），运行时因子断言门禁（33/33 因子验证）、因子健康端点 `GET /admin/factor-health`、conftest `_test_mode` 替代全局 mock、`test_factor_integration_live.py` + `@pytest.mark.integration`、LLM fallback 报告文本增强（含方案说明 + 风控 + 操作建议）。

| # | 任务 | 提交 | 说明 |
|---|------|:----:|------|
| 2.3.1 | 7 个 scaffold 因子接入真实数据源（premium_discount/tracking_error/shares_change 等） | `e5b6139` | IOPV 数据 + 份额变化率 + 跟踪误差；后加 KDJ/信号/政策因子共 30/30 全 LIVE |
| 2.3.2 | 运行时因子断言门禁（test_each_factor_returns_nonzero_with_mock_data） | `2132a74` | 33/33 因子断言非零，防止未来 scaffold 回归 |
| 2.3.3 | 因子健康端点 GET /admin/factor-health | `2132a74` | 返回每个 symbol 的 live/non-zero ratio，verify_e2e 注册 factor 模块 |
| 2.3.4 | conftest _test_mode 重构（替代全局 mock） | `2132a74` | test-mode 抑制 teardown HTTP 泄漏，不阻塞真实数据 |
| 2.3.5 | 因子集成测试 marker + test_factor_integration_live.py | `2132a74` | `@pytest.mark.integration` 隔离 live 测试 |
| 2.3.6 | LLM fallback 报告增强 | `2132a74` | 包含方案方法论 + 风控约束 + 操作建议 |

**测试验证**:
- 33/33 运行时因子断言 ✅
- test_core_factors_no_scaffold: 33/33 因子非零 ✅
- verify_e2e factor module: 每个 symbol ≥40% 非零 ✅

### Phase 2.4 — 分配器引擎质量修复 ✅ **全部完成（v6.0 新增）**

> 分配器引擎质量问题：ln_mcap 淹没问题、C2 条件永不触发、去重不充分、预算不匹配、cross-section 因子未归一化。
>
> **修复前**：valuation 维度被 ln_mcap≈25 淹没（technical 0.5 vs valuation 5.0）、C2 风偏修正因 `has_style_factors` 始终为 True 不触发、同概念 ETF 跨层重复选择、核心 50% 预算占用过多。
>
> **修复后**：valuation 聚合排除 ln_mcap/ln_float_mcap → 技术面/动量分不再被淹没、C2 真正常开（防御+安全奖励 0.8 penalty -1.5、进攻+风险奖励 1.5）、segment 归一化（科创50/100/新能源/创新药→"科创"）跨层+层内去重、卫星预算从 15/25/30→25/30/35、core max_count 3/4/4→4/5/5、cross-section z-score 重归一化（worktree）、segment 字段注入 `pool_manager step 3a`（worktree）。

| # | 任务 | 提交 | 说明 |
|---|------|:----:|------|
| 2.4.1 | 估值聚合排毒（排除 ln_mcap/ln_float_mcap） | `4ace706` | 防止 log-scale 市值 ~25 淹没问题 |
| 2.4.2 | C2 条件修正（has_meaningful_style 排除 size 因子） | `4ace706` | ln_mcap 移除后 C2 真正常开 |
| 2.4.3 | segment 归一化 + 跨层/层内去重 | `4ace706` `98025ad` | _normalize_segment + _extract_index_concept 兜底 |
| 2.4.4 | 卫星/核心预算重调 | `4ace706` | 核心 50→40%，卫星 15/25/30→25/30/35% |
| 2.4.5 | cross-section z-score 重归一化 | worktree | get_factor_matrix → _normalize_matrix |
| 2.4.6 | segment 字段注入（pool_manager step 3a） | worktree | 为系统化去重提供基础字段 |

**测试验证**:
- test_design_optimization_plan.py: DQ1-DQ5 ✅
- test_engine: 差异化、去重、风控约束 ✅

### Phase 2.5 — 质量防护网 + AI 分析增强 + 设计报告增强

**前置依赖**: Phase 0.7~1.0 完成；Phase 2.1 ✅ + Phase 2.2 ✅ + Phase 2.3 ✅ + Phase 2.4 ✅ 全部完成

| # | 任务 | 源文档 | 状态 | 预估工时 | 前置依赖 |
|---|------|--------|:----:|:-------:|---------|
| 2.5.1 | AppButton/AppCard/AppTabs/AppInput/AppModal 单测 | frontend-testing-safety-net Phase A | ✅ 已实施（43 个用例覆盖 5 个组件所有常见交互） | 4h | 无 |
| 2.5.2 | useDashboardData composable 单测 | frontend-testing-safety-net Phase B | ✅ 已实施（35 个用例覆盖全部 computed + 异步方法 + 响应式） | 1h | 无 |
| 2.5.3 | E2E spec 扩充到 10-15 条 | frontend-testing-safety-net Phase B/C | ✅ 已实施（5 个 spec 文件，24 个测试用例：smoke×5 + regression×3 + navigation×6 + wizard×5 + theme/assets×5） | 6h | 无 |
| 2.5.4 | verify_e2e.py 全局指数检查修复 | fix-global-indices-plan 根因 #7 | ✅ 已实施 | 0.5h | 无 |
| 2.5.5 | market-analysis Phase C | market-analysis §5 | ✅ 已实施 | 4-5h | Phase 1.1.8+1.1.9 |
| 2.5.6 | market-analysis Phase D（AI 顾问流式+数据管道） | market-analysis §6 | ✅ 已实施 | 2-3h | 无 |
| 2.5.7 | market-analysis Phase E（市场报告质量提升） | market-analysis §7 | ✅ 已实施 | 2-3h | 无 |
| 2.5.8 | design-report A1+A2+A3 | `archived/design-report-optimization-plan.md` | ✅ 已实施 | — | Phase 0.7 |
| 2.5.9 | design-report B1：黄金入选理由增强 | `archived/design-report-optimization-plan.md` B1 | ✅ 已实施（commit 584ad20） | ~10行 | 无 |
| 2.5.10 | design-report B2：国债久期风险提示 | `archived/design-report-optimization-plan.md` B2 | ✅ 已实施（commit 584ad20） | ~3行 | 无 |
| 2.5.11 | design-report B3：LLM prompt 量化规则 | `archived/design-report-optimization-plan.md` B3 | ✅ 已实施 | — | 无 |
| 2.5.12 | design-report C1：全市场净流入信号注入 | `archived/design-report-optimization-plan.md` C1 | ✅ 已实施（commit f6d47d3：利用现有 akshare stock_individual_fund_flow 聚合全池资金流向注入 LLM prompt） | ~30行 | 无 |
| 2.5.13 | design-report C2：卫星层增加科技 ETF | `archived/design-report-optimization-plan.md` C2 | ✅ 已实现（基础版，`engine/allocation_engine.py` L443-467；含集成缺口） | ~15行 | 无 |

**验证**:
- `npm test` 全绿 + `npm run test:e2e:smoke` 全绿
- 市场分析页面由 6 卡片降为 4 卡片，所有分析功能正常
- AI 顾问流式渲染，返回有实质数据的回答
- 市场研判报告含「综合研判结论」+「操作建议」
- 设计方案预期收益根据市态动态调整（非硬编码）
- 卫星层包含宽基科技 ETF 选项（科创50/588000，浓度>60%时自动引入）

### Phase 2.6 — 异步边界修复收尾 ✅ **全部完成**

**来源**: `async-boundary-fix-plan.md`（v2.0，2026-07-26）

**说明**: Phase 0.9 遗留的唯一线上阻塞点（Sina IOPV `urllib.request.urlopen`）+ 预防性措施。

| # | 任务 | 文件 | 优先级 | 状态 |
|---|------|------|:------:|:----:|
| 2.6.1 | **Sina IOPV `urllib.request.urlopen` → `await run_sync()`** | `factor_registry.py:839-866` | **P0** | ✅ 已修复 |
| 2.6.2 | `macro_state.py` 死代码修复 | `macro_state.py:94-171` | **P1** | ✅ 已修复 |
| 2.6.3 | 设计管线并发限流（`asyncio.Semaphore(1)`） | `task_manager.py` | **P1** | ✅ 已实施 |
| 2.6.4 | 创建 CI 审计脚本 `scripts/audit_async_blocking.py` | 新建文件 | P2 | ✅ 已创建 |
| 2.6.5 | 增强异步边界单测（补 Sina IOPV mock） | `tests/test_async_boundaries.py` | P2 | ✅ 已增强 |
| 2.6.6 | 线程池深度监控增强（ERROR 级别） | `async_utils.py` | P2 | ✅ 已增强 |
| 2.6.7 | 更新 AGENTS.md 开发约定 | `AGENTS.md` | P2 | 🟡 待补充 |
| 2.6.8 | 端到端验证：设计+策略检查不阻塞 | `verify_e2e.py` | **P0** | ✅ 已验证 |

**验证结果**:
- `python scripts/audit_async_blocking.py` — [PASS] 0 违规 (88 files)
- `pytest tests/test_async_boundaries.py ::test_sina_iopv_fetch_uses_run_sync` — PASS
- `pytest tests/test_async_lint.py` — 2/2 PASS

---

### Phase 2.7 — 系统性质量修复 ✅ **全部完成**

**来源**: `systematic-quality-review.md`（2026-07-26）

**说明**: 6 个质量问题的系统性修复，覆盖设计方案管线和因子数据管道。

| # | 任务 | 文件 | 优先级 | 状态 |
|---|------|------|:------:|:----:|
| 2.7.1 | 设计方案 post-condition 校验：每个 strategy ≥1 只非 CASH ETF | `task_manager.py` | **P0** | ✅ 已修复 |
| 2.7.2 | `compute()` 空数据告警：空 dict 时 logger.error | `factor_registry.py` | **P0** | ✅ 已修复 |
| 2.7.3 | 编码诊断：DB 直接读取确定断裂点 | `scripts/encoding_diagnosis.py` | **P1** | ✅ 已新增 |
| 2.7.4 | 因子降级缓存：fallback 到过期 K 线 | `factor_registry.py` | **P1** | ✅ 已实施 |
| 2.7.5 | 置信度规则化：基于 filled_count/total_count 覆盖 | `portfolio_service.py` | **P1** | ✅ 已实施 |
| 2.7.6 | 状态机验证阶段：空策略拒入 completed | `task_manager.py` | P2 | ✅ 已实施（同 2.7.1）|
| 2.7.7 | factor_summary 输出到因子级别可用性 | `portfolio_service.py` | P2 | ✅ 已实施 |
| 2.7.8 | 设计列表增加 etf_count 元数据 | `portfolio.py` | P2 | ✅ 已实施 |
| 2.7.9 | 市态缓存异步刷新 | `pool_manager.py` + `main.py` | P2 | ✅ 已实施 |
| 2.7.10 | 区分数据不足 vs 信号中性 | `portfolio_service.py` | P2 | ✅ 已实施 |
| 2.7.11 | AGENTS.md E2E 检查项修正 | `AGENTS.md` | P2 | ✅ 已更新 |
| 2.7.12 | AGENTS.md 关键路径更新 | `AGENTS.md` | P2 | ✅ 已更新 |

**验证结果**:
- `pytest tests/test_strategy_design.py` — PASS（空池返回 error）
- `pytest tests/test_database.py::test_database_encoding_roundtrip` — PASS
- `pytest tests/test_strategy_check_async.py` — 3/3 PASS（含 confidence 值级断言）
- `pytest tests/test_factor_registry.py::test_compute_with_empty_fetch_returns_zeros` — PASS

---

### Phase 2.8 — 测试防护增强 ✅ **全部完成**

**来源**: `systematic-quality-review.md §9`（2026-07-26）

**说明**: 填补测试防护的 4 层结构性缺口，防止同类问题再次逃逸。

| # | 任务 | 文件 | 修复缺口 | 状态 |
|---|------|------|:--------:|:----:|
| **G1 — AST 扫描增强** | | ① | | |
| 2.8.1 | 新增 `test_no_direct_sync_call_in_async_function` | `tests/test_async_lint.py` | ① | ✅ 已新增 + PASS |
| **G2 — 真实路径集成测试** | | ② | | |
| 2.8.2 | 新增 `test_compute_with_empty_fetch_returns_zeros` | `tests/test_factor_registry.py` | ② | ✅ 已新增 + PASS |
| 2.8.3 | 编排器集成测试（标记为 slow） | `tests/test_design_optimization_plan.py` | ② | ✅ 已新增（@pytest.mark.slow，需手动执行）|
| 2.8.4 | 新建 `test_strategy_design.py` | `tests/test_strategy_design.py` | ② | ✅ 已新建 + PASS |
| **G3 — 值级质量断言** | | ③ | | |
| 2.8.5 | 增强 `test_strategy_check_async.py`：confidence 值级断言 | `tests/test_strategy_check_async.py` | ③ | ✅ 已增强 + PASS |
| 2.8.6 | 增强 `test_design_optimization_plan.py`：σ 格式断言 | `tests/test_design_optimization_plan.py` | ③ | ✅ 已增强 + PASS |
| 2.8.7 | 增强 `test_pool_manager.py`：market_context 断言 | `tests/test_pool_manager.py` | ③ | ✅ 已增强 + PASS |
| 2.8.8 | 增强 `scripts/verify_e2e.py`：设计质量检查 | `scripts/verify_e2e.py` | ③ | ✅ 已增强 |
| **G4 — 编码 roundtrip** | | ④ | | |
| 2.8.9 | 新建 `tests/test_database.py`：编码 roundtrip | `tests/test_database.py` | ④ | ✅ 已新建 + PASS |

**验证结果**:
- `pytest tests/test_async_lint.py` — 2/2 PASS（含新增 `test_no_direct_sync_call`）
- `pytest tests/test_factor_registry.py::test_compute_with_empty_fetch_returns_zeros` — PASS
- `pytest tests/test_strategy_design.py::test_empty_candidate_pool_returns_error` — PASS
- `pytest tests/test_database.py::test_database_encoding_roundtrip` — PASS
- `pytest tests/test_strategy_check_async.py` — 3/3 PASS

---

### Phase 2.9 — LLM 流式数据管道统一 ✅ **全部完成**

**源文档**: `docs/llm-stream-data-pipeline-unification.md`

**问题**：三个 LLM 端点（AI 顾问/市场报告/设计报告）各自独立采集数据，导致市场报告缺少行业板块、AI 顾问缺少因子评分，加数据要改 N 处。

**方案**：新增 `build_full_context()` 公共数据管道函数，三个端点统一调用。

**预估**：~170 行 / 2-3 小时

| # | 任务 | 源文档 | 落地方式 | 状态 |
|---|------|--------|---------|:----:|
| 2.9.1 | 新增 `build_full_context()` 函数（新建 llm_context.py） | §3·步骤1 | `backend/app/services/llm_context.py` — `build_full_context()` 统一采集(regime/sentiment/indices/sectors/news/market_data/commodities/fund_flow)，所有字段带 try/except | ✅ 已完成 |
| 2.9.2 | 改造 `llm_report_stream` 改用 `build_full_context` | §3·步骤2 | `backend/app/routers/analysis.py` — 替换原有 5 路 asyncio.gather 为统一上下文管道 | ✅ 已完成 |
| 2.9.3 | 改造 `llm_advice_stream` 改用 `build_full_context` | §3·步骤3 | `backend/app/routers/analysis.py` — 替换原有 7 处独立 pool_manager getter 调用为统一管道 | ✅ 已完成 |
| 2.9.4 | 统一 prompt 模板化 | §3·步骤5 | 已具备 `load_prompt()` 基础设施，prompt 模板文件可在后续增量创建 | ✅ 基础设施就绪 |
| 2.9.5 | 验证：语法检查 + 模块导入 + 后端单测 | §3·步骤6 | 模块导入通过，pool_manager 单测 13/13 PASS | ✅ 已验证 |

---

### Phase 3.1 — 前端 UI 重构（✅ 已完成，2026-07-26）

**前置依赖**: Phase 2.5 测试防护已就绪 ✅（2.5.1-2.5.3 全部实施：18 个 spec 文件，175 个用例，含 AppComponents 43 条 UI 组件测试 + useDashboardData 35 条 composable 测试 + E2E 24 条）

**实施明细**:

| # | 任务 | 源文档 | 状态 | 备注 |
|---|------|--------|:----:|------|
| 3.1.0 | E2E 截图基线建立 | frontend-testing-safety-net C4 | ✅ 完成 | 新增 `e2e/specs/02-visual.spec.js`（4 个截图基线测试：Dashboard 加载态、Dashboard 骨架屏、PortfolioAnalysis、MarketAnalysis）；本地运行 `npm run test:e2e:visual` 生成基线 |
| 3.1.1 | Dashboard 手工 card → AppCard（7 区块） | frontend-ui-optimization Phase 2 | ⏭️ 递延 | 涉及 7 个子组件内部重构，复杂度高；6/7 已迁移至 Phase 3.2（AllocationPieChart/AllocationTable/PnLBarChart/PnLDetailTable/SummaryCards），CapitalInputBar 因自定义 SVG 彩色 header 保留现状 |
| 3.1.2 | Dashboard 手工 tab → AppTabs | frontend-ui-optimization Phase 2 | ✅ 完成 | Dashboard.vue: 手动 `.tabs`/`.tab` 替换为 `<AppTabs variant="soft" full-width>` |
| 3.1.3 | PortfolioAnalysis tab → AppTabs | frontend-ui-optimization Phase 2 | ✅ 完成 | PortfolioAnalysis.vue: 手动 `.pa-tabs`/`.pa-tab` 替换为 `<AppTabs variant="line">`；测试同步更新 |
| 3.1.4 | MarketAnalysis/TokenMonitor/DesignResult tab → AppTabs | frontend-ui-optimization Phase 2 | ⏭️ 部分递延 | MarketAnalysis 为 data-filtering tabs（非内容切换），不适合 AppTabs panel 模式；DesignResult 已在 Phase 3.2 完成迁移；TokenMonitor 内嵌在 card header 中 |
| 3.1.5 | Vite chunk 优化（vendor-vue/axios/echarts 分层） | frontend-performance Step 2 | ✅ 完成 | `vite.config.js`: 新增 `vendor-vue`(vue/vue-router/pinia/vue-echarts)、`vendor-axios` 分块 |
| 3.1.6 | 移除 `plugins/echarts.js` 残留文件 | frontend-performance Step 3 | ✅ 完成 | 文件已删除（main.js 中 import 在 Phase 2.5 已移除）；添加 CSS backward-compat 别名变量到 theme.css |
| 3.1.7 | Chart 子组件渲染测试 | frontend-testing-safety-net C2 | ⏭️ 递延 | 依赖 3.1.1 的 DOM 结构确定；留待后续 |
| 3.1.8 | 剩余 4 个 composable 单测 | frontend-testing-safety-net §1 | ✅ 完成 | 新增 `useLLMStream.spec.js`(6), `useSectorAnalysis.spec.js`(10), `useMarketSearch.spec.js`(11), `useMarketWS.spec.js`(6) = **33 个新测试**；修复 vitest.config.js 缺少 `@` alias |
| 3.1.9 | task.js localStorage 防抖写入 | frontend-performance Step 4 | ✅ 完成 | 新增 `_saveDebounced()` 函数（300ms 合并窗口），`updateTask` 中的写入改为防抖 |

**验证结果**:
- `npm test`: **22 文件 / 210 测试全绿** ✅（新增 33 个 composable 用例）
- `npm run build`: **构建成功**， chunk 分层验证：
  - `vendor-vue`: 479 KB (vue/vue-router/pinia/vue-echarts)
  - `vendor-axios`: 46 KB
  - `echarts`: 200 KB
  - 应用代码按 route 懒加载分割

**侧边任务完成**:
- ✅ 清理 `plugins/echarts.js` 残留文件
- ✅ theme.css 添加向后兼容 CSS 变量别名（`--color-primary`, `--color-border`, `--color-text-muted` 等）

### Phase 3.2 — AppCard 迁移 + DesignResult AppTabs（✅ 已完成，2026-07-26）

**范围**: 3.1 中递延的前端 UI 重构项

| # | 任务 | 状态 | 备注 |
|---|------|:----:|------|
| 3.2.1 | AllocationPieChart → AppCard | ✅ 完成 | `<section class="card chart-card">` → `<AppCard>`，移除手写 card CSS |
| 3.2.2 | AllocationTable → AppCard | ✅ 完成 | `<section class="card table-card">` → `<AppCard>` |
| 3.2.3 | PnLBarChart → AppCard | ✅ 完成 | `<section class="card chart-card">` → `<AppCard>` |
| 3.2.4 | PnLDetailTable → AppCard | ✅ 完成 | subtitle 移至 AppCard `header-action` slot |
| 3.2.5 | DesignResult tab → AppTabs | ✅ 完成 | 手动 `.design-tabs`/`.tab-btn` → `<AppTabs variant="line">`，history badge 外移共用 |
| 3.2.6 | changeClass.spec.js 顶层 await 修复 | ✅ 完成 | `const DashboardAiTools = await import()` → `beforeAll` 内动态导入 |
| 3.2.7 | SummaryCards → AppCard (layout="horizontal") | ✅ 完成 | 新增 AppCard `layout="horizontal"` 变体：icon 左、内容右，flex-row 排列；7 个子卡片全部迁移；icon 背景色通过 CSS 自定义属性 `--app-card-icon-bg` 动态控制 |

**递延说明**: CapitalInputBar 因自定义 SVG 彩色 header 保留现状。Chart 渲染测试（原 3.1.7）因 AppCard 不改变 DOM 结构，无需额外测试。

**验证结果**:
- `npm test`: **22 文件 / 212 测试全绿** ✅（新增 2 个 AppCard horizontal layout 测试）
- `npm run build`: **构建成功** ✅，chunk 分层验证正确

### Phase 4.1 — 数据源系统改造（大方案，独立轨道）✅ **已实施（仅 D7 待完成）**

此阶段完全对应 `roadmap-data-source-unified.md` 的四个子阶段。详见该文档。

**状态**: 所有子任务均已实施（4.1.2 全球指数链路已稳定运行，虽未纳入 SourceRegistry 但由 EM 批量接口+Sina+Finnhub 覆盖 14 指数，verify_e2e.py 有断言保护）。`roadmap-data-source-unified.md` 已更新为 v3.0 回顾文档。

| # | 任务 | 源阶段 | 状态 | 说明 |
|---|------|--------|:----:|------|
| 4.1.1 | 美股 `_route_us()` 链路重写 | roadmap Phase A | ✅ 已实施 | 当前为 `TwelveData→Finnhub`。Stooq API 已关(404/Cloudflare)，`stooq_fetcher.py` 已删除；AlphaVantage(25次/天)和 yfinance(境内不稳定) 已移出链路 |
| 4.1.2 | 全球指数链路统一 | roadmap Phase A4 | ✅ 已实施 | `_foreign()` 实际降级链: EM(东方财富批量缓存) → Sina → Sina页面爬取(欧洲) → Finnhub → 占位符。未纳入 SourceRegistry.route() 因为 EM 批量接口一次调用覆盖全部 14 指数，效率远高于 route() 单标的链式模式。verify_e2e.py §section_market 已有 HK/US 三大指数价格断言 + 逐区域有价验证。`_route_us()` 已改为 TwelveData→Finnhub 并通过 registry.route() |
| 4.1.3 | China market 3 核心函数接入 SourceRegistry | roadmap Phase B | ✅ 已实施 | `fetch_a_stock_realtime` / `fetch_a_stock_batch` / `fetch_hk_stock_realtime` 均已使用 `registry.route()` |
| 4.1.4 | price=0 过滤前置修复 | roadmap Phase B | ✅ 已实施 | `_filtered()` 辅助函数在 china_market.py:424 实现，provider lambda 层过滤 |
| 4.1.5 | 补齐健康探针 | roadmap Phase C | ✅ 已实施 | `monitor/probes.py` 已含 8 探针（6 数据源 + 2 线程池），`main.py` 调用 `register_all_probes()` |
| 4.1.6 | SourceRegistry on_event 回调 | roadmap Phase D2-D4 | ✅ 已实施 | `source_registry.py` 已含 `set_event_callback` + `route_name` + `get_states` + `circuit_breaker_status` |
| 4.1.7 | SourceEventStore | roadmap Phase D1 | ✅ 已实施 | `monitor/source_events.py` 完整实现（内存环5000条 + SQLite异步刷盘 + 7天清理） |
| 4.1.8 | 数据源监控 API | roadmap Phase D6 | ✅ 已实施 | `routers/admin.py` 已含 4 个端点（health/timeline/failures/circuit-breakers） |
| 4.1.9 | 前端数据源监控面板 | roadmap Phase D7 | ✅ 已实施 | `frontend/src/components/SourceMonitor.vue` 新建，含源状态矩阵 + ECharts 堆叠柱状图(1h/6h/24h) + 失败事件表格。路由 `/source-monitor`，导航"📡 数据源"。参照 `TokenMonitor.vue` 风格。后端 admin API 4 端点已就绪（D6），`api-contracts/admin/sources.md` 已创建 ✅ |

**实施后的并行分析**（历史记录，用于未来参考）:
- Track 1 (Phase A+B): 实际完全并行，无文件冲突
- Track 2 (Phase C): 已独立实施，仅改 main.py + 新建 probes.py
- Track 3 (Phase D): D1-D6 中只有 D2-D4 需独占 source_registry.py，D1/D5/D6/D7 均独立

**验证**: `verify_e2e.py` + admin API curl 命令
```bash
# 数据源健康检查
curl -s "http://localhost:8000/api/v1/admin/sources/health"
curl -s "http://localhost:8000/api/v1/admin/sources/circuit-breakers"
curl -s "http://localhost:8000/api/v1/admin/sources/events/timeline?hours=1"
```

### Phase 5.1 — 市场感知联动 ✅ 已完成

> **状态**: ✅ 2026-07-26 全栈实施完成。commit `2371815`，13 files，+1022/-63 lines。
>
> **来源**: `market-awareness-and-data-source-plan.md` §5

**前置依赖**: Phase 4.1（数据源改造）已就绪；Phase 2.9（LLM 上下文管道）提供数据基础设施

#### 实施内容

| # | 任务 | 对应文件 | 说明 |
|---|------|---------|------|
| 5.1.1 | MarketContext 数据类 | `backend/app/core/market_context.py` (新) | MarketContext @dataclass + resolve_market_context() 工厂函数，支持 A/HK/US/global 四市场 |
| 5.1.2 | Market Router 路由层 | `backend/app/services/market_router.py` (新) | 5 个 async 路由函数：get_market_indices/realtime/history/news/sectors |
| 5.1.3 | SectorAnalysis market 感知 | `routers/analysis.py` | SectorAnalysisRequest 增加 market 字段；非 A 市场返回友好空提示 |
| 5.1.4 | MarketReport market 过滤 | `routers/analysis.py` | llm-report/stream 使用 MarketContext.major_symbols 按市场过滤主要标的 |
| 5.1.5 | 组合设计 market 参数 | `routers/portfolio.py` + `services/strategy_design.py` | design-async 接受 market；非 A 返回 status=unsupported |
| 5.1.6 | 多市场 Regime 缓存 | `services/pool_manager.py` | _regime_cache 改为 dict[str,str]；get/update_market_regime 接受 market 参数 |
| 5.1.7 | LLM 上下文市场感知 | `services/llm_context.py` | build_full_context() 接受 market 参数，传递给 get_market_regime(market) |
| 5.1.8 | 前端 API 适配 | `frontend/src/api/index.js` | designAsync 传递 market 参数 |

#### 新增文件
- `api-contracts/market/market-context.md` — API 契约文档
- `core/market_context.py` — MarketContext 数据类（index_symbols/title/regime_broad_index/supports_*）
- `services/market_router.py` — 5 async 路由函数，按市场分发到正确数据源

#### 测试验证
- `tests/test_market_context.py` — 35 个新单测，全部 PASS
- 覆盖：4 市场全部属性、边界情况（空字符串/大小写/空格）、regime 缓存、llm-report 过滤
- 存量单测（analysis_contract/async_lint/database 等 45 个）全部 PASS
- 前端 `npm run build` 构建通过

### Phase 6.1 — 可观测性与系统增强 ✅ **2026-07-26 已全部实施**

| # | 任务 | 源文档 | 状态 | 变更文件 |
|---|------|--------|:----:|---------|
| 6.1.1 | SourceEventStore（source_events 表 + API） | roadmap Phase D (D1+D6) | ✅ 已实施 | `monitor/source_events.py` + `admin.py` 端点 |
| 6.1.2 | 前端数据源监控页面 | roadmap Phase D7 | ✅ 已实施 | `components/SourceMonitor.vue` + `/source-monitor` 路由 |
| 6.1.3 | ConfigManager + app_config 表 | config-management §4.1-4.3 | ✅ 已实施 | **新增**: `models/app_config.py`, `core/config_manager.py`, `api-contracts/admin/config.md`; **修改**: `database.py`, `routers/admin.py` |
| 6.1.4 | 前端 ConfigPage | config-management §5 | ✅ 已实施 | **新增**: `views/ConfigView.vue`; **修改**: `router/index.js`, `App.vue`, `api/index.js` |
| 6.1.5 | Sector API 实时行情返回 | sector-concept Phase 3 | ✅ 已实施 | `routers/market.py` — 交换 get_sectors_local 与 sector_fetcher 优先级，移除 TODO 注释 |
| 6.1.6 | LLM prompt 热点板块注入 | sector-concept Phase 4 | ✅ 已实施 | `services/llm_context.py` — 注入 hot_plates/sector_heat; `services/pool_manager.py` — 新增 get_hot_plates()/get_sector_heat() |
| 6.1.7 | `stars` 引入时间新鲜度 + 新闻 Level 2 精度调整 | news-pipeline-fix P2 | ✅ 已实施 | `fetchers/news_fetcher.py` — 新增 _compute_stars(); `fetchers/levistock_fetcher.py` — 移除 Level 2 时间词 |
| 6.1.8 | `news_fetcher` 验证脚本更新 verify_e2e.py | news-pipeline-fix §8 | ✅ 已实施 | `scripts/verify_e2e.py` — 新增 stars/level 字段校验 + check_sector_data() 函数, 注册 sectors 模块 |

**验证**: 配置页 GET/PUT/恢复 ✅ 已实施 + 板块数据实时行情带涨跌颜色 ✅ 已实施 + stars 字段含时间新鲜度 ✅ 已实施 + verify_e2e.py --module sectors ✅ 已实施

### Phase 6.2 — 数据预热可见性与 Dashboard 加载体验优化 ✅ **2026-07-27 已全部实施**

| # | 任务 | 源文档 | 状态 | 变更文件 |
|---|------|--------|:----:|---------|
| 6.2.1 | Warmup Status API (GET /api/v1/system/warmup) | 本方案 | ✅ 已实施 | **新增**: routers/system.py, api-contracts/system/warmup.md; **修改**: main.py (warmup 状态初始化 + 预热任务状态追踪) |
| 6.2.2 | Backend unit tests (warmup status + endpoint) | 本方案 | ✅ 已实施 | **新增**: tests/test_warmup_status.py (5 tests, all mock) |
| 6.2.3 | Frontend useWarmupStatus.js composable | 本方案 | ✅ 已实施 | **新增**: composables/useWarmupStatus.js (5s polling, 120s timeout, phase title derivation) |
| 6.2.4 | Dashboard multi-phase loading UX | 本方案 | ✅ 已实施 | **修改**: views/Dashboard.vue (warmup banner + fetchAttempted separation) |
| 6.2.5 | Fix useDashboardData.js loading/empty conflated bug | 本方案 | ✅ 已实施 | **修改**: composables/useDashboardData.js (added fetchAttempted ref, fixed empty portfolio deadlock) |
| 6.2.6 | Nav bar warmup indicator | 本方案 | ✅ 已实施 | **修改**: App.vue (nav-warmup pulsing dot + label) |
| 6.2.7 | Frontend API registration (systemApi) | 本方案 | ✅ 已实施 | **修改**: api/index.js (added systemApi.warmup()) |

**验证**: Backend tests 5/5 PASS + npm run build (741 modules, 0 errors) + Nav bar shows warming-up pulse indicator + Dashboard skeleton with phase text

### Phase 7.1 — 远期优化

| # | 任务 | 源文档 | 状态 | 说明 |
|---|------|--------|:----:|------|
| 7.1.1 | Factor IC 追踪器激活 | factor-model-extension | ✅ 已实施 | Phase A(核心管道) + Phase B1(B3)已实施：SQLite 持久化(factor_ic_records 表)，定时 120s 保存 IC batch；IC 阈值告警(logger.warning)；前端 FactorICView.vue(因子 IC 排序 + 有效性标记) |
| 7.1.2 | 排版令牌迁移 | frontend-ui-optimization Phase 3-4 | ✅ 已实施 | 51 处排版令牌迁移（font-size + font-weight → font: var(--text-*) shorthand），跨 26 个组件文件 |
| 7.1.3 | SVG 图标替换 emoji | frontend-ui-optimization Phase 3 | ✅ 已实施 | 创建 icons.js 图标系统\uff0826 个\u10e6��\u51� SVG 图\u6807\uff0bemoji 映\u5c04）\uff1bAppCard 通过 resolvedIcon computed 自\u52a8渲\u67d3 SVG\uff1bE2E 测\u8bd5适\u914d |
| 7.1.4 | 响应式补齐 | frontend-ui-optimization Phase 4 | ❌ 待实施 | 移动端适配 |
| 7.1.5 | 进一步 E2E 增强 + 剩余 UI 组件单测 | frontend-testing-safety-net C1/C3 | ✅ C1 + C3 均已实施 | C1\uff1aAppTable(7) + AppSelect(9) + Skeleton(9) 单测\uff0cAppComponents2.spec.js 25/25 通过\uff1b修复 AppTable density class bug\uff1bC3\uff1aCharts E2E(4) + News E2E(4) + 技术分析 E2E(5) = 13 条新增 spec |
| 7.1.6 | design-report B1-B3（LLM prompt 分析增强）+ C2（科技ETF分散） | design-report-optimization B1/B2/B3/C2 | ✅ **全部已实施** | B1（黄金动量入选理由）→ `engine/rationale.py:60-63`；B2（国债久期风险提示）→ `engine/rationale.py:64-65`；B3（LLM prompt 量化规则）→ `analysis/prompts/v1/design_report.md:68`；C2（科技集中度→科创50 ETF分散）→ `engine/allocation_engine.py:443-458` |

---

## 5. 附录：各方案摘要

### 5.1 文档状态速查表（v4.2 更新）

| 文档 | 类型 | 状态 | 影响模块 | 关键阶段 | 备注 |
|------|------|------|---------|:--------:|------|
| async-boundary-fix-plan.md (v1.3) | 修复方案 | 🟡 **部分实施 (Phase 0.9)** | factor_registry + async_utils + pool_manager + main.py | Phase 0.9 → 2.6 | v2.0 已发布，剩余修复见 Phase 2.6 |
| async-boundary-fix-plan.md (v2.0) | 修复方案 | ❌ 待实施 | factor_registry.py:839-866 | Phase 2.6 | 2026-07-26 更新，修复遗漏 Sina IOPV 阻塞 |
| systematic-quality-review.md | 审计报告 | ❌ 待实施 | 全系统 | Phase 2.7 | 2026-07-26 新增，6 个质量问题 |
| config-management-plan.md | 实施方案 | ✅ **已实施 (Phase 6.1.3+6.1.4)** | 后端 admin + 前端 ConfigPage | Phase 6.1 | ConfigManager + ConfigView.vue + api-contracts |
| data-source-monitoring-plan.md | 实施方案 | ❌ **已替代** | — | — | 被 `roadmap-data-source-unified.md` 替代 |
| **design-check-pipeline-redesign.md** | **重构方案** | ✅ **已实施 (Phase 1.0)** | **task_manager + design_pipeline + DB + 前端** | **Phase 1.0** | 12 文件，588 行，8 新集成测试 |
| design-check-quality-report.md | 质量审计 | ✅ **19/19 已实施** | 全链路 | Phase 1.1/2.1 | P2-4(target_weight 默认值) 代码已验证含 `else 0.1` 兜底 ✅ |
| design-failure-and-strategy-check-review.md | 修复方案 | ✅ **已实施 (Phase 0.8)** | 前端 + portfolio_service + llm + tests | Phase 0.8 | 10 文件，252 行 |
| archived/design-optimization-plan.md | 实施方案 | ✅ 已实施 | strategy_design + engine/ | Phase 0.5 前 | — |
| **design-pipeline-foundation-issues.md** | **诊断+修复方案** | ✅ **已实施 (Phase 0.7)** | **etf_scanner + pool_manager + factor_registry + risk_controls + allocation_engine** | **Phase 0.7** | 15 新单测，9 文件，1428 行 |
| archived/design-report-optimization-plan.md | 实施方案 | ✅ **已实施** | llm.py + design_report.py + engine/rationale.py + engine/allocation_engine.py | Phase 2.2 | A1/A2/A3 ✅ B1/B2/B3 ✅ C1 ✅；C2 ✅（`engine/allocation_engine.py:443-458` 科技集中度>60%卫星预算→自动科创50 ETF(588000)分散） |
| e2e-testing-plan.md | 实施方案 | ⚠️ 部分实施 | frontend/e2e/ | Phase 7.1 | 基础设施（playwright.config.js + server utils + package.json 脚本）已就绪 ✅；已实现 6/12 个 spec 文件（01-smoke / 02-visual / 03-navigation / 04-wizard-design / 05-theme-assets / 12-regression）。全量 12-spec 计划未实施 |
| factor-model-extension-plan.md | 实施方案 | ✅ **v4.0 已重写** | factor_registry.py + ic_tracker.py + routers/factors.py | Phase 7.1.1 | 已全面重写：反映 33 因子全 LIVE 架构 + engine/ 包 + IC 追踪器两阶段激活方案（Phase A: 核心管道 + API 端点；Phase B: 持久化 + UI） |
| five-improvements-plan.md | 实施方案 | ✅ **全部完成** | risk_controls.py + rationale.py + portfolio_service.py | Phase 1.1 | #1 统一市态已落地（`portfolio_service.py:406-409`）|
| fix-global-indices-plan.md | 修复方案 | ✅ **已实施 (Phase 0)** | market_service + GlobalIndicesStrip | Phase 0 | — |
| frontend-architecture-refactor.md | 实施方案 | ✅ 已实施 | 全部前端组件 | — | — |
| frontend-performance-optimization.md | 优化方案 | ⚠️ Step 1 已实施 | main.js + vite.config.js | Phase 3.1 | Step 2-3 待做 |
| frontend-testing-safety-net.md | 测试方案 | ⚠️ Phase A/B 已完成 | frontend/test + e2e | Phase 2.5/3.1 | 18 spec 文件/175 条/UI 组件 43 条；Phase C（截图基线+Chart测试+剩余E2E）待做 |
| frontend-ui-optimization-plan.md | 优化方案 | ❌ 已回滚 | 全部前端视图 | Phase 3.1 | 需测试防护就绪 |
| archived/issues-analysis-report.md | 问题分析 | ✅ 已修复 | 全局 | — | — |
| market-analysis-optimization-plan.md | 实施方案 | 🟡 **部分完成（2026-07-26 审计修正）** | market router + analysis router | Phase 2.5 → 5.1 | Phase A/B/C ✅；Phase D/E 🟡（后端数据管道已实现，但 market 参数端到端传递和 LLM prompt 增强未完成）。详见 §4 Phase 5.1 状态矩阵 |
| market-awareness-and-data-source-plan.md | 实施方案 | ✅ **§5 已实施（Phase 5.1）** | core/market_context + services/market_router + 端市场感知接入 | Phase 5.1 | §4 已转 `roadmap-data-source-unified.md`；§5 市场感知联动全栈实施：MarketContext 数据类、market_router 路由层、多市场 regime 缓存、design-async 多市场参数、sector-analysis 市场感知。35 个新单测全 PASS。commit `2371815` |
| news-pipeline-fix-plan.md | 修复方案 | ✅ **全部完成** | news_fetcher + levistock_fetcher + NewsView.vue | Phase 1.1 | P0+P1 全部实施（新浪源/关键词/降级链）|
| archived/optimization-plan-20260721.md | 实施方案 | ✅ **已实施 (Phase 0.5)** | etf_scanner + 前端 + 后端链路 | Phase 0.5 | 全部 8 项完成 |
| **remaining-issues-solution-design.md** | **实施方案** | ✅ **全部已实施**（已从 staged→committed） | **pool_manager + task_manager + ws + factor_registry** | **Phase 2.1** | S1-A(TTL) `53acbfa`、S1-C(渐进) `ef3de11`、S2(归一化) `5116681`、S3-B/C(WS) `ef3de11` |
| archived/review-20260720.md | 评审报告 | N/A | N/A | — | 非实施方案 |
| roadmap-data-source-unified.md | 实施方案 | ✅ **已实施（D7除外）** | china_market + market_service + source_registry + monitor | Phase 4.1 | 替代三份原方案。v3.0 已更新为回顾文档。Phase A/B/C/D1-D6 均已实施 |
| sector-concept-optimization-plan.md (v3.0) | 实施方案 | ✅ Phase 1-6 全部实施 | market_trends + pool_manager + llm.py + market.py + analysis.py + 前端 | Phase 1.1/6.1 | 数据采集+缓存写入+60s定时刷新 ✅; Phase 3 (API实时行情) ✅ 已实施(Phase 6.1.5); Phase 4 (LLM注入) ✅ 已实施(Phase 6.1.6); Phase 5-6 借由 build_full_context 统一数据管道覆盖 |
| archived/source-registry-optimization-plan.md | 实施方案 | ❌ **已替代** | — | — | 被 roadmap 替代 |
| **archived/scaffold-factor-resolution-plan.md** | **修复方案** | ✅ **全部实施** | **factor_registry + 测试** | **Phase 2.3** | 7 个脚手架因子全 LIVE（33/33），因子健康端点，运行时断言门禁 |
| **design-quality-review-20260725.md** | **审计报告** | N/A | allocation_engine + factor_registry + budgets | — | 非实施方案 |

### 5.2 冲突汇总（v4.0 更新）

| 冲突 | 涉及文档 | 重要性 | 解决方式 | 状态 |
|------|---------|--------|---------|:----:|
| 数据源改造三文档抢同一代码域 | source-registry + data-source-monitoring + market-awareness §4 | 🔴 | 合并为 `roadmap-data-source-unified.md` | ✅ 已解决 |
| foundation-issues 与存量文档改同一代码域 | foundation-issues Phase A/B + design-optimization P1/P2/P3 | 🔴 | 上下游关系非冲突；Phase 0.7 优先实施，其余延后验证 | ✅ 已解决 |
| 市场分析 vs 市场感知抢 `llm_advice_stream()` | market-analysis Phase D + market-awareness §5 | 🔴 | Phase 5.1 全栈实施：新增 MarketContext 数据类 + market_router 路由层 + 多市场感知接入；market-awareness §5 从规划变为已实施 | ✅ Phase 5.1 已完成 (commit `2371815`) |
| foundation-issues A3 与 sector-concept Phase1-2 抢缓存入口 | foundation-issues A3 + sector-concept Phase 1-2 | 🟡 | 先 A3（最小化实现），sector-concept 在已有入口上扩展 | ✅ 已解决 |
| LLM prompt 被三文档同时修改 | market-analysis Phase E + design-report A2/C1/C2 + sector-concept Phase 4 | 🟡 | 同步实施，统一修改 `llm.py`，先做结构后加数据 | 待实施 |
| 同一页面被两方案同时改动 | market-analysis Phase C + frontend-ui Phase 1-2 | 🟡 | 先实施 Phase C（DOM 结构），再在目标结构上做 UI 优化 | 待实施 |
| 全球指数降级链分歧 | fix-global-indices vs market-awareness | 🟡 | 统一链路，已写入 roadmap-data-source-unified | ✅ 已落地 |
| UI 重构曾回滚，需要测试防护 | frontend-ui-optimization + frontend-testing-safety-net | 🟡 | 先做 testing 再做 UI | 待实施 |
| 管道 redesign 文档与已实施代码不一致 | design-check-pipeline-redesign.md 标记"未实施"但代码已落地 | 🟢 | 更新状态为"已实施"，记录 commit 引用 | ✅ 本版已修复 |
| async-boundary 文档标记"待实施"但已落地 | async-boundary-fix-plan.md vs 2be9ccb | 🟢 | 更新状态为"已实施" | ✅ 本版已修复 |
| quality-report 文档与 uncommitted 代码不一致 | design-check-quality-report.md P0-1/P0-2/P0-3 vs 工作区变更 | 🟢 | 更新状态为"部分实施"，标注哪些已实现待 commit | ✅ 本版已修复 |

### 5.3 关键依赖图（v4.0 更新）

```
Phase 0 (快速胜利 7 项)        ✅ 已完成
  ├── 0.1-0.5 fix-global-indices + perf
  └── 0.6-0.7 news-pipeline P0

Phase 0.5 (核心链路修复)       ✅ 已完成

Phase 0.7 (数据管道基础修复)   ✅ 已完成
  ├── 0.7.1-0.7.2 tracked_index 链  → 0.7.8 候选池去重
  ├── 0.7.3 市场快照缓存写入        → Phase 1.1 sector 扩展
  ├── 0.7.4 因子分键名聚合           → 0.7.12 三方案差异化
  │                                  → Phase 2.2 design-report 增强
  ├── 0.7.5-0.7.7 防御层修复
  ├── 0.7.10 regime 映射修复
  └── 0.7.11 design_text 诊断

Phase 0.8 (设计失败修复)       ✅ 已完成
  ├── 前端弹窗 + 建议上限 + 数据质量注入
  └── 级联测试 + verify_e2e 增强

Phase 0.9 (异步边界修复)       ✅ 已完成
  ├── 事件循环阻塞 + 线程池统一
  └── 冷却期污染 + 预热超时 + 测试防护

Phase 1.0 (顺序管道重构)       ✅ 已完成
  ├── 顺序 Pipeline + report_quality
  └── 原子写入 + 崩溃恢复 + 8 集成测试

Phase 1.1 (数据层增强+统一市态)   依赖 Phase 0.7~1.0
  ├── 1.1.0 five-improvements #1  独立
  ├── 1.1.1-1.1.3 sector cache      → Phase 6.1 LLM prompt
  ├── 1.1.4-1.1.7 news-pipeline P1  → 新闻模块功能完整
  └── 1.1.8-1.1.9 market-analysis A+B → Phase 2.2 (Phase C 依赖)

Phase 2.1 (数据管道质量提升)    ✅ 全部完成（合并入 Phase 2.2）
Phase 2.2 (数据管道根因修复)    ✅ 全部完成（15 项）
Phase 2.3 (脚手架因子全 LIVE)   ✅ 全部完成（33/33 核心因子全 LIVE）
Phase 2.4 (分配器引擎质量修复)  ✅ 全部完成（ln_mcap 排毒 + C2 修正 + segment 去重 + 预算重调 + z-score）

Phase 2.5 (质量防护网+市场分析+设计报告)   依赖 Phase 0~2.4   ⚠️ 2.5.1-2.5.3 测试安全网 + 2.5.5-2.5.13 全部 ✅
  ├── 2.5.1-2.5.3 测试安全网        → 为 Phase 3.1 提供防护 ✅（18 个 spec 文件，175 个用例，含 AppComponents 43 条）
  ├── 2.5.5  market-analysis C       ✅ 已实施（依赖 Phase 1.1.8+1.1.9）
  ├── 2.5.6-2.5.7  market-analysis D/E ✅ 已实施
  ├── 2.5.8 A1/A2/A3 ✅ / 2.5.9 B1 ✅ / 2.5.10 B2 ✅ / 2.5.11 B3 ✅
  └── 2.5.12 C1 ✅（资金流向注入LLM prompt）/ 2.5.13 C2 ✅（卫星层科技集中度>60%时自动引入588000）

Phase 2.7 (系统性质量修复)   依赖 Phase 2.6  ✅ 全部完成
  ├── 2.7.1-2.7.2 设计方案校验+空数据告警(P0) ✅
  ├── 2.7.3-2.7.5 编码诊断+因子缓存+置信度规则化(P1) ✅
  ├── 2.7.6-2.7.8 状态机+因子可用性+etf_count(P2) ✅
  ├── 2.7.9 市态缓存异步刷新(P2) ✅
  └── 2.7.11-2.7.12 AGENTS.md 更新 ✅

Phase 2.8 (测试防护增强)    依赖 Phase 2.7  ✅ 全部完成
  ├── 2.8.1 G1 AST扫描增强 ✅
  ├── 2.8.2-2.8.3 G2 真实路径集成测试 ✅（含 @pytest.mark.slow）
  ├── 2.8.4 test_strategy_design.py 新建 ✅
  ├── 2.8.5-2.8.7 G3 值级质量断言增强 ✅
  ├── 2.8.8 verify_e2e 增强 ✅
  └── 2.8.9 G4 编码 roundtrip ✅

Phase 2.9 (LLM 流式数据管道统一)  ✅ 全部完成（`backend/app/services/llm_context.py`）
  ├── 2.9.1 build_full_context() 函数      ~70行 ✅
  ├── 2.9.2 llm_report_stream 改用统一管道  ✅
  ├── 2.9.3 llm_advice_stream 改用统一管道  ✅
  └── 2.9.5 验证：模块导入+单测全通过      ✅

Phase 3.1 (前端 UI 重构)         依赖 Phase 2.5 测试防护

Phase 4.1 (数据源改造 A/B/C/D1-D6) ✅ 已实施, D7 独立待实施

Phase 5.1 (市场感知联动)          ✅ 已完成（MarketContext + market_router + 多市场感知）

Phase 6.1 (可观测性增强)         ✅ 全部完成 — ConfigManager + ConfigPage + Sector API 实时行情 + LLM 热点注入 + stars 新鲜度 + verify_e2e 扩展

Phase 7.1 (远期优化)             无紧急依赖

Phase 11 (性能诊断与优化)         ✅ 2026-07-28 全部完成 — OPT-01~OPT-16 基于 `docs/archived/performance-diagnosis-and-optimization-plan.md`
   ├── OPT-01: 熔断器集成 fundamental_fetcher（push2 熔断检查）
   ├── OPT-02: _compute_fund_flow 快速降级
   ├── OPT-03: run_in_thread executor 参数
   ├── OPT-04: Semaphore(8) 并发限流
   ├── OPT-05: SourceRegistry 全覆盖 fundamental_fetcher
   ├── OPT-08/16: 回归测试套件 test_regression.py（17 红绿切换测试）
   ├── OPT-10: run_in_thread 全代码库 40+ 调用点审计
   ├── OPT-13: AST 审计脚本 scripts/audit_pool_usage.py
   └── OPT-15: SourceRegistry 三优化——try_call、fast-fail、指数退避
```

### 5.4 轨道总览（v4.0 更新）

```
🔧 数据管道基础修复 Track（完成 4 个阶段）
  Phase 0.7 (foundation-issues) ✅ → Phase 0.8 (design-failure review) ✅
  → Phase 0.9 (async-boundary) ✅ → Phase 1.0 (pipeline-redesign) ✅
  → Phase 2.1 (quality-report 剩余项)

📰 新闻管道修复 Track
  Phase 0 (WS 修复, ✅) → Phase 1.1.4-1.1.7 (数据源增强) → Phase 6.1.7-6.1.8 (星+验证)

📊 市场分析重构 Track（~13-19h）
  Phase 1.1.8-1.1.9 (搜索+路由后端) → Phase 2.2.5-2.2.7 (前端+流式+报告)

📋 设计报告增强 Track（~2h）
  Phase 2.2.8-2.2.10 (预期收益 + 净流入 + 科技ETF)

🔌 数据源统一改造 Track
  Phase 4.1 (A/B/C/D1-D6 ✅ 已实施) → Phase 6.1.2 (D7 前端 ✅ 已实施) → Phase 6.1.3-6.1.4 (配置管理待实施)

🛡️ 数据管道质量提升 Track（新增，~3-4h）
  Phase 2.1.0-2.1.12 (引擎修复 + 策略检查增强 + 测试防护 + E2E 断言)
```

---

## 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| **v11.1** | 2026-07-28 | **Phase 11.1 — Fetcher 合并重组**。按业务域将 18 个 fetcher 合并为 11 个。组1: `global_markets_fetcher.py` — 合并 7 个全球行情/宏观数据源（em_global/yfinance/alphavantage/twelvedata/finnhub/tushare/fred），保留 fred 的 async httpx 架构备用。组2: `fundamentals_fetcher.py` — 合并 3 个资金流/情绪/两融数据源（fundamental_fetcher/margin_fetcher/sentiment_fetcher），修复同组跨文件引用。清理 `stooq_fetcher` 悬空 import（market_router.py）。删除 7 个旧全局 fetcher + 3 个旧组2 fetcher 文件。更新 10 个调用方文件的 import 路径。36/36 测试通过。 |
| **v11.0** | 2026-07-28 | **Phase 11 — 性能诊断与优化（OPT-01~OPT-16）** 全部完成。基于 `docs/archived/performance-diagnosis-and-optimization-plan.md`。OPT-01: 熔断器集成（`fundamental_fetcher.py` push2 熔断检查）✅。OPT-02: `_compute_fund_flow` 快速降级 ✅。OPT-03: `run_in_thread` 新增 `executor` 参数 ✅。OPT-04: `_compute_fund_flow` Semaphore(8) 并发限流 ✅。OPT-05: SourceRegistry 全覆盖（`fundamental_fetcher` 接入）✅。OPT-08/16: 回归测试套件 `test_regression.py`（17 个用例，红绿切换门禁）✅。OPT-10: `run_in_thread` 全代码库 40+ 调用点审计（long vs shared 池分流）✅。OPT-13: AST 审计脚本 `scripts/audit_pool_usage.py` ✅。OPT-15: SourceRegistry 三优化——`try_call()` 包装器、fast-fail 检测（<500ms 硬失败）、指数退避冷却（60s→120s→240s→480s→600s max）✅。API 契约 `api-contracts/admin/circuit-breaker.md` 新增。`test_source_registry_optimizations.py` 14 个新单测 ✅。总计 31 个新单测 + 17 个回归测试，存量 58 个全 PASS。详见 §4 Phase 11。 |
| v1.0 | 2026-07-22 | 初次生成，覆盖全部 18 份文档 |
| v2.0 | 2026-07-22 | 新增 3 份文档处理 + 新轨道 + 冲突分析；调整 Phase 0/1/2/3 |
| v3.0 | 2026-07-23 | 新增 `design-pipeline-foundation-issues.md`（23 份文档）；Phase 0/0.5 标记 ✅ 完成；新增 Phase 0.7（12 项 P0/P1 修复）；修复 `five-improvements-plan.md` 内部状态不一致；新增 §2.7-2.11 冲突分析；新增 §3.5-3.8 修复方案；更新 §4 路线图；更新附录 |
| v4.0 | 2026-07-24 | 新增 4 份文档（27 份总数）；Phase 0.7 确认 ✅；新增 Phase 0.8/0.9/1.0 全部 ✅；重算剩余 Phase 1.1~7.1 排序；新增 Phase 2.1（质量审计剩余项）；更新附录全部表格 + 依赖图 + 轨道总览；同步各方案文档状态 |
| v4.1 | 2026-07-25 | 新增 `remaining-issues-solution-design.md`（28 份）；Phase 2.1 中 S1-A(TTL 缓存)、S1-C(渐进状态机)、S2(混合归一化)、S3-B/C(WS 清理+超时) 已实施（staged）；更新文档状态表 + 任务列表 |
| v4.2 | 2026-07-25 | 基于 10+ 个新增 commit 审计更新：Phase 2.1 确认 10/15 项 ✅（含 staged→committed），6 项新增未规划已落地（F10 enrich、C2风偏分、新闻情感桥接、IOPV批量、DQ门禁、verify_design）；剩余 5 小项合并入 Phase 1.1 后期；track E 轨道状态同步更新；设计检查质量报告状态重写；文档状态表 v4.2 刷新 |
| **v5.0** | 2026-07-25 | 15 个修复项全部完成：china_market.py import 错误根因修复（所有 26 因子从 0→非零）；空池保护 + B3b dedup + C2 风偏修正 + 入选理由重写 + IOPV 批量 + 新闻情感桥接 + change_pct 因子注册 + decode_df 逐格修复 + DB 编码修复脚本 + conftest teardown 防护 + 前端错误态返回按钮 + E2E 回归测试 + DQ 门禁 + test_data_health.py pytest 兼容。Phase 2.1 全部完成 ✅。新增 Phase 2.2（数据管道根因修复）✅ 全部完成。Phase 2.2→2.3 重编号。所有剩余项均无 Block。 |
| **v6.0** | 2026-07-25 | 基于 v5.0 后 7 个新 commit（5f484e6~98025ad）+ 工作区改动审计更新。文档总数 28→30。Phase 2.3（脚手架因子全 LIVE + 测试防护缺口修复）✅ 完成——7 个 scaffold → 非零（26/26 全 LIVE）、运行时因子断言门禁、因子健康端点。Phase 2.4（分配器引擎质量修复）✅ 完成——ln_mcap 排毒、C2 修正、segment 去重、预算重调、cross-section z-score。Phase 2.3→2.5 重编号。 |
| **v6.1** | 2026-07-25 | Phase 1.1 ✅ 全部完成（`1f6d00e`~`89862be` 共 7 commit）。新闻管道：新浪 HTTP 直连源、三级降级链(新浪->CLS->财联社)、关键词精度修复(P1.1/P1.2)。板块数据：概念+行业双源动量、60s 定时刷新循环。时间戳 Unix->ISO 转换。搜索端新增 `market=A` 个股支持。正文 content 字段补齐（新浪 intro/RSS summary）。文章 URL 透传 + 前端"查看原文"。测试防护：4 个新测试文件 + 1 个增强，共 35 个新测试用例。设计质量审计 18/19 全部落地。5 项改进方案全部完成。 |
| **v7.0** | 2026-07-26 | Phase 2.6 + 2.7 + 2.8 全部完成。2.6：Sina IOPV urlopen->run_sync 修复(P0)、macro_state 死代码线程池包装(P1)、设计管线 Semaphore(1) 并发限流(P1)、CI 审计脚本 audit_async_blocking.py 创建(P2)、线程池 ERROR 告警(P2)、test_sina_iopv_fetch 单测(P2)。2.7：设计方案逐策略非空校验(P0)、compute() 空数据 error 告警(P0)、因子降级缓存(P1)、置信度规则化(P1)、factor_availability 报告(P2)、etf_count 元数据(P2)、verify_e2e 质量断言(P2)。2.8：test_no_direct_sync_call_in_async_function(G1)、test_compute_with_empty_fetch(G2)、test_empty_candidate_pool(G2)、test_strategy_check confidence 断言(G3)、test_database roundtrip(G4)。 |
| **v7.1** | 2026-07-26 | Phase 2.7 剩余项 + 2.8 剩余项 + Phase 2.9 全部完成。2.7.3：新增 encoding_diagnosis.py 编码诊断脚本 ✅；2.7.9：市态缓存异步刷新（refresh_sentiment_cache + main.py 120s 定时循环）✅；2.7.11-2.7.12：AGENTS.md 更新 ✅。2.8.3：编排器 slow 集成测试 ✅；2.8.6：σ 格式断言增强 ✅；2.8.7：market_context 完整性断言 ✅。2.9.1：新增 llm_context.py（build_full_context 统一数据管道）✅；2.9.2-2.9.3：llm_report_stream + llm_advice_stream 改用统一管道 ✅。后端单测 pool_manager 13/13 PASS，设计优化单测通过（不含slow）。 |
| | **v7.2** | 2026-07-26 | Phase 4.1 状态审核。全量代码审计发现 roadmap-data-source-unified.md v2.0 中的实施方案绝大部分已被后续 commits 落地。Phase A/B/C/D1-D6 均已实施，仅 D7（前端数据源监控面板）待完成。`roadmap-data-source-unified.md` 更新为 v3.0 回顾文档。`implementation-master-plan.md` Phase 4.1 更新为 ✅ 已实施状态。 |
| | **v7.3** | 2026-07-26 | Phase 4.1 全部完成：4.1.2（全球指数链路）代码审计确认实际为 EM→Sina→Finnhub 而非计划所述 TwelveData，verify_e2e.py 已含 HK/US 三大指数断言，状态修正为 ✅。4.1.9（前端数据源监控面板 D7）实施完成：新建 SourceMonitor.vue（TokenMonitor 风格，含 ECharts 堆叠柱状图 + 源状态矩阵 + 失败事件表格）、路由 `/source-monitor`、导航"📡 数据源"、`api-contracts/admin/sources.md` 契约。`api/index.js` 新增 4 个 adminApi 源监控方法。npm run build 验证通过。 |
| | **v9.0** | 2026-07-26 | **Phase 5.1 全栈实施完成**：市场感知联动。新增 `core/market_context.py`（MarketContext 数据类，4 市场） + `services/market_router.py`（5 路由函数）。修改 `routers/analysis.py`（SectorAnalysisRequest.market、llm-report/stream 市场过滤、非 A 板块分析友好提示）、`routers/portfolio.py`（design-async market 参数，非 A 返回 unsupported）、`services/pool_manager.py`（regime 缓存 dict[str,str] 多市场）、`services/strategy_design.py`（market 参数入口）、`services/llm_context.py`（market 参数透传）、`frontend/src/api/index.js`（designAsync 传 market）。`api-contracts/market/market-context.md` 契约。35 个新单测全 PASS，存量 45 个全 PASS，npm run build 通过。commit `2371815`。 |
| | **v9.5** | 2026-07-27 | **Factor model display on AI tools page** | 备注见下方 |
| | | | **已实施：** |
| | | | - 新增 `GET /api/v1/factors/active` 端点（routers/factors.py）：返回已注册计算函数的因子列表，按 category 分组，附带 IC 值、标准化方式、阈值、有效性状态 |
| | | | - 新增 `api-contracts/factors/active.md` API 契约 |
| | | | - 新增 `tests/test_factors_router.py` 10 个单测全部 PASS（contract conformance） |
| | | | - 新增 `frontend/src/components/FactorModelView.vue`：可展开分类卡片 + 因子行(IC色条/IC值/截断简介) + hover 浮层(完整元数据+有效性状态) + ECharts IC 柱状图 |
| | | | - `frontend/src/views/DashboardAiTools.vue` 集成 FactorModelView，位于 AI 工具卡片下方 |
| | | | - `frontend/src/api/index.js` 新增 `factorsApi.getActive()` |
| | | | - npm run build 通过 |
| | |
| | | **v9.4** | 2026-07-27 | **Phase 7.1.6 Sprint 1 P0/P1 前端逻辑下沉** | 备注见下方 |
| | | | **已实施：** |
| | | | - P0: Dashboard 财务指标去重（useDashboardData.js 7 个 computed 改用后端字段：total_pnl/total_amount/weighted_change_pct/cash_weight/cash_amount） |
| | | | - P0: 35 个 useDashboardData 单测全 PASS |
| | | | - P1: 设计方案后端新增 `plans` 字段（get_design API），前端 `fetchDesignDetail`/`onHistorySelect` 直接使用 |
| | | | - 后端 `routers/portfolio.py` get_design() 新增 plans 映射 |
| | | | - 前端 `DashboardAiTools.vue` 两处 strategies→plans 转换消除 |
| | | | - 修复 DashboardAiTools.vue 编码损坏（UTF-16 LE → UTF-8 无 BOM，恢复 emoji 和中文字符） |
| | | | - 新增 `docs/frontend-logic-sink-plan.md` 方案文档（v2 版，32 份→33 份） |
| | | | - 23 前端测试文件 237 单测全 PASS，npm run build 通过 |
| | |
| | **v9.3** | 2026-07-26 | **Phase 7.1.2-7.1.5 实施（UI 优化 + 测试补齐）** | 备注见下方 |
| | | | **已实施：** |
| | | | - 7.1.2 排版令牌迁移：51 处，26 个组件 |
| | | | - 7.1.3 SVG 图标系统：icons.js + AppCard 集成 |
| | | | - 7.1.5 C1: AppTable/AppSelect/Skeleton 单测 25/25 PASS |
| | | | - 修复 AppTable density class bug |
| | | | **还剩：** 7.1.4 响应式、C3 E2E(Charts + 技术分析) |
| |
| | **v9.2** | 2026-07-26 | **Phase 7.1.1 实施（IC 追踪器激活）** | 备注见下方 |
| | | | **已实施：** |
| | | | - build_forward_returns() + compute_periodic_ic() 到 ic_tracker.py |
| | | | - _last_ic_batch + IC compute 集成到 factor_registry.py compute() |
| | | | - GET /api/v1/factors/ic API 端点（routers/factors.py） |
| | | | - api-contracts/factors/ic.md API 契约 |
| | | | - verify_e2e.py 扩展 IC 端点检查 |
| | | | - tests/test_ic_tracker.py 16 个单测全部 PASS |
| | | | **还剩：** Phase B(IC 持久化 + UI) |
| |
| | **v9.1** | 2026-07-26 | **Phase 7.1 文档审计更新** | 2026-07-26 | **Phase 7.1 文档审计更新** — 基于代码交叉验证，6 份方案文档对齐当前代码。关键发现：7.1.6 B1/B2/B3/C2 全部已实施（`engine/rationale.py` B1+B2 ✅、`design_report.md` B3 ✅、`allocation_engine.py` C2 ✅）；`factor-model-extension-plan.md` 已重写为 v4.0（反映 33 因子架构 + IC 追踪器方案）；`frontend-ui-optimization-plan.md` Phase 1 Step 1 已在 theme.css L121-124 完成；`e2e-testing-plan.md` 基础设施就绪但有 6/12 个 spec；`frontend-testing-safety-net.md` 准确。详见 `AGENTS.md` 评估记录。 |
| | | | | |
| | **v9.8** | 2026-07-27 | **Phase 8 — 去重造轮子 (wheel-unreinvention)** | 备注见下方 |
| | | | **已实施：** |
| | | | - `analysis/indicators.py` → pandas-ta：MA/EMA/MACD/RSI/KDJ/Bollinger 全部改用 pandas-ta，保持接口不变 |
| | | | - `factors/factor_registry.py` 11 个 compute 函数 → pandas-ta：SMA_5/10/20/60、RSI_14、MACD、Bollinger_BW、ATR_14、KDJ_K/D/J |
| | | | - `fetchers/sentiment_fetcher.py` 动态权重 + 情绪惯量：基于市态的条件权重（牛市机构共识更重，熊市涨跌比更重），动量修正 |
| | | | - `services/market_trends.py` 精简计算层：新增 `_compute_trend_from_prices()` 使用 pandas-ta 计算 MA 乖离率/波动率/最大回撤 |
| | | | - `engine/risk_controls.py` 阈值配置化：`MAX_SINGLE_WEIGHT` 等常量替换为 `RiskSettings` dataclass |
| | | | **新增测试：** `test_indicators.py` (27 用例), `test_factor_compute_functions.py` (20 用例) |
| | | | **新增契约：** `api-contracts/common/internal-indicators-contract.md`, `api-contracts/factors/registry.md` |
| | | | **改动文件：** 5 源文件 + 2 测试文件 + 2 契约文件
| |
| | **v9.9** | 2026-07-27 | **Phase 9 — 系统性能与质量增强 (system-performance-quality)** | 详见 `docs/archived/system-performance-and-quality-review.md` |
| | | | **已实施（阶段一+二）：** |
| | | | **B1** — 修复 `market_service.py:667` `cache_set` UnboundLocalError：将 `cache_set` import 移至 `get_portfolio_realtime()` 函数顶部，删除重复 import |
| | | | **B2** — 全局异常处理器：在 `main.py` lifespan 中添加 `loop.set_exception_handler()`，捕获未处理的协程异常并记 ERROR 日志 |
| | | | **A1-A2** — WarmupProfiler 时序采集集成：收集三个 warmup 任务到 `_warmup_tasks` 列表，使用 `asyncio.wait()` 等待任务完成后再停止 profiler |
| | | | **C1** — `check_routes.py`：路由契约验证脚本，按 `(method, path)` 比对 `app.routes` 与 `api-contracts/**/*.md` 中的路由描述，支持 `--json`/`--actual-only` 模式 |
| | | | **D** — 响应时间门限：`verify_e2e.py` 新增 `_check_response_time()` 函数，为 `/market/indices/global`、`/market/search`、`/portfolio/designs`、`/portfolio/etfs`、`/news/headlines`、`/admin/token-usage` 六个端点添加 P95 响应时间门限检查 |
| | | | **E1+H** — 前端构建优化：`vite.config.js` 集成 `rollup-plugin-visualizer`（ANALYZE 模式生成 `dist/stats.html`），设置 `chunkSizeWarningLimit: 500` 和 `assetsInlineLimit: 4096` |
| | | | **新增测试：** `test_route_contract.py` (14 用例) — 覆盖 `_parse_contract_method` 6 种模式、`load_expected_routes` 目录扫描、`compare_routes` 6 种场景 |
| | | | **改动文件：** `backend/app/main.py`、`backend/app/services/market_service.py`、`backend/scripts/verify_e2e.py`、`backend/scripts/check_routes.py`（新）、`backend/tests/test_route_contract.py`（新）、`frontend/vite.config.js` |
| |
| | **v10.0** | 2026-07-27 | **Phase 10 — 候选池与数据链路修复 (pool-fix-plan)** | 详见 `docs/archived/fix-plan-master.md` + `docs/archived/fix-plan-pool.md` |
| | | | **已实现：** |
| | | | **F1** — `_ETF_PREFIXES` 加入 `"52"` (`china_market.py`)，支持 520xxx 港股通 ETF 路由 |
| | | | **F2** — `_fetch_em_etf_list` 修复字段映射：新增 `f72=成交额` 替换 `f62=换手率→amount`，`f62→turnover`，`f45→volume`，修复沪市 ETF amount=0 根因 |
| | | | **F3** — `CORE_KEYWORDS` 新增 科创50/创业板/中证500；`DEFENSE_KEYWORDS` 移除 恒生/H股/中概（港股非防御资产） |
| | | | **F4** — `layer_ranking` 改用 scale 做主排序：amount 可用时 30/70 加权，不可用时仅用 scale；`top_n` 从 15 提升至 25 |
| | | | **F5** — `pool_manager.py` 新增 `_balance_by_industry()` 行业均衡化：每 segment 取 top 1 后再按得分补齐 |
| | | | **F6** — `pool_manager.py` 新增 `_is_market_hours()` 非交易时段检测；`_compute_composite` 非交易时段 liquidity 权重减半 |
| | | | **F7** — `factor_registry.py` 修复 bare `except Exception: pass` → 带日志的 `except Exception as e: logger.warning(...)` |
| | | | **F8** — `verify_e2e.py` 新增 `check_data_quality()` 数据质量校验模块（字段完整性 + 候选池覆盖） |
| | | | **F9** — 测试更新：`test_design_new_modules.py` 12 测试同步关键词变更（分类预期 + 注释） |
| | | | **F10** — `docs/implementation-master-plan.md` 更新至 v10.0 |
| | | | **改动文件：** `backend/app/fetchers/etf_scanner.py`、`backend/app/fetchers/china_market.py`、`backend/app/services/pool_manager.py`、`backend/app/factors/factor_registry.py`、`backend/scripts/verify_e2e.py`、`backend/tests/test_design_new_modules.py` |
| |
| | | **v10.1** | 2026-07-27 | **Phase 10.1 — mootdx 超时防护 + 前端性能** | 续 Phase 10 |
| | | | **已实现：** |
| | | | **F11** — `china_market.py` 新增 `_run_mootdx_with_timeout()` 函数，使用 `concurrent.futures.ThreadPoolExecutor(max_workers=1)` 包裹 mootdx socket 读操作（`client.quotes` / `client.bars`），8s 硬超时，解决 P0 mootdx TCP read 挂死线程池问题 |
| | | | **F12** — `frontend/vite.config.js` 优化 chunk 拆分：`vendor-echarts`（echarts+vue-echarts）与 `vendor-vue` 分离，新增 `vendor-marked` 独立 chunk；`chunkSizeWarningLimit` 提升至 700KB |
| | | | **改动文件：** `backend/app/fetchers/china_market.py`、`frontend/vite.config.js` |
| |
| |
| | | | | **v12.0** | 2026-07-28 | **Phase 12 — 系统优化与质量保障 (optimization-master-plan-v2)** | 详见下方 |
| | | | | | | **P0 — 数据与报告质量修复（Q01-Q04）：** |
| | | | | | | **Q01** — `task_manager.py` 分配引擎输出有效性门禁：全部 3 方案仅 CASH 时标记为 failed，report_quality=empty，保存到 DB |
| | | | | | | **Q02** — `models/strategy_check.py` 新增 report_text 列 + to_dict() 序列化；`database.py` 迁移；`strategy_check_worker.py` 存储 report_text 到记录 |
| | | | | | | **Q03** — `task_manager.py` report_quality 4 级体系：full/partial/empty/failed 替代旧 binary full/fallback |
| | | | | | | **Q04** — `design_report.py` LLM 一致性校验增强：空 ETF 追加修正脚注 + WARNING 日志 |
| | | | | | | **P1 — 系统稳定性修复（S01-S04）：** |
| | | | | | | **S01** — `fundamentals_fetcher.py` push2→push2delay 域名替换 + 熔断器接入 (record_success/record_failure) + run_sync import 修复 |
| | | | | | | **S02** — `factor_registry.py` advance_decline timeout 5s→2s，减少阻塞循环 |
| | | | | | | **S03** — `main.py` A04: 启动时清理积压 stuck 任务（状态=running >5min 标记为 failed） |
| | | | | | | **S04** — `core/logging.py` numba.core.ssa DEBUG 日志降级到 WARNING |
| | | | | | | **P2 — 性能优化（P01-P03）：** |
| | | | | | | **P01** — `frontend/src/styles/theme.css` 新增 loading-container min-height 200px 等 CSS，降低 CLS |
| | | | | | | **P02** — `etf_scanner.py` 新增 ETF_LIST_CACHE 内存缓存（TTL 300s），减少热启动 warmup 时间 |
| | | | | | | **P03** — `warmup_profiler.py` pyinstrument async_mode=disabled→enabled |
| | | | | | | **P3 — 可维护性增强（A01-A04）：** |
| | | | | | | **A01** — `verify_e2e.py` 新增预热时间 CI 门禁（首次预热 ≤30s 失败线、≤15s 警告线） |
| | | | | | | **A02** — `pool_manager.py` sentiment 缓存持久化：每次刷新写入 data/sentiment_cache.json，失败时从文件恢复 |
| | | | | | | **A03** — `verify_e2e.py` report_quality 一致性断言：quality=full 必须有真实 ETF；quality=empty 必须全 CASH |
| | | | | | | **新增契约：** `api-contracts/portfolio/report-quality.md`、`api-contracts/portfolio/strategy-check-report.md` |
| | | | | | | **新增测试：** `tests/test_report_quality.py` (7/7 PASS)、`tests/test_remaining_fixes.py` (10/10 PASS) |
| | | | | | | **改动文件：** `backend/app/tasks/task_manager.py`、`backend/app/tasks/design_report.py`、`backend/app/tasks/strategy_check_worker.py`、`backend/app/fetchers/fundamentals_fetcher.py`、`backend/app/fetchers/etf_scanner.py`、`backend/app/factors/factor_registry.py`、`backend/app/main.py`、`backend/app/core/logging.py`、`backend/app/profiling/warmup_profiler.py`、`backend/app/services/pool_manager.py`、`backend/app/models/strategy_check.py`、`backend/app/database.py`、`backend/scripts/verify_e2e.py`、`frontend/src/styles/theme.css`、`backend/tests/test_design_new_modules.py`、`api-contracts/portfolio/report-quality.md`（新）、`api-contracts/portfolio/strategy-check-report.md`（新）、`backend/tests/test_report_quality.py`（新）、`backend/tests/test_remaining_fixes.py`（新） |
| | | | | **已实现（后端）：** |
| | | | | **B3.1** — task_manager.py get_task() 确保 progress/stage/status 始终有值 |
| | | | | **B2.5** — portfolio_service.py new summary.by_type field |
| | | | | **B2.3** — market.py search include_stocks param; search_etf type field |
| | | | | **B3.2** — market.py unified GET /sectors route |
| | | | | **B2.1** — portfolio.py GET /timeline endpoint |
| | | | **已实现（前端）：** |
| | | | | **Sprint 1.2** — DashboardAiTools.vue uses data.plans directly |
| | | | | **Sprint 2.1** — single timeline API call; **2.2** unified search; **2.3** by_type PnL |
| | | | | **Sprint 3** — useTaskPolling.js, remove stale check, sector URL unified |
| | | | | **Sprint 4.1** — watchlist CRUD uses fetchWatchlist() |
| | | | **新增契约：** api-contracts/portfolio/timeline.md; updated pnl-history.md, market/all.md |
| | | | **改动文件：** 5 backend + 8 frontend + 3 contract |
| |
| | | **v10.3** | 2026-07-27 | **Phase 10.3 — 文档方案 v2 重写 + TokenMonitor AppTabs 迁移** | 4 份文档重审计、重设计，实施可行项 |
| | | | **方案重设计：** |
| | | | **UI 优化 v2** — 基于 8 路由代码审计完全重写：发现 old plan 的 Phase 1 两项已自然解决；Dashboard/PortfolioAnalysis 已用 AppTabs ✅；MarketAnalysis 的「市场切换」实为 filter 非 tab，AppTabs 不适用 ⛔；TokenMonitor 的 tab-btn ✅ 已迁移；NewsView/SourceMonitor/FactorIC 手工 card → 低优先级推迟 |
| | | | **system-performance 更新** — §9 优先级表全面重写，12 项逐一标注状态 |
| | | | **testing-safety-net 更新** — 更新 test count 256，验收标准第 5 项 ✅ |
| | | | **performance doc** → 已归档至 `docs/archived/` |
| | | | **已实现：** |
| | | | **TokenMonitor → AppTabs** — 替换手工 `tab-group`/`tab-btn` 为 `<AppTabs v-model>`，删除 `switchGranularity()` 函数，新增 `watch(granularity, fetchData)`，新增 `granularityTabs` 数据。TokenMonitor 单测 3 条 ✅ |
| | | | **改动文件：** `frontend/src/components/TokenMonitor.vue`、`frontend/src/test/TokenMonitor.spec.js`（新）、`frontend/src/test/ChartComponents.spec.js`（已有）、`docs/frontend-ui-optimization-plan.md`（v2 重写）、`docs/frontend-testing-safety-net.md`、`docs/archived/system-performance-and-quality-review.md`、`docs/implementation-master-plan.md` |
| |
| | **v11.1** | 2026-07-27 | **Phase 12 — 全面优化实施 (optimization-master-plan)** | 详见 `docs/archived/optimization-master-plan.md` |
| | | | **已实现（P1-严重修复）：** |
| | | | **FIX-09** — 因子缺失值语义化。`factor_registry.py` 所有 41 个 compute 函数改为在数据不足时返回 `None`（而非 `0.0`/`50.0`/`1.0`），区分「计算为零」和「数据缺失」。`compute()` 不再将 None→0.0，z-score 标准化排除 None。`aggregate_factor_scores()` 跳过 None 值。`allocation_engine.py` composite 评分跳过 None 类别（权重重分配）。新增 `test_factor_missing_value_semantics.py`（44 个分支测试覆盖缺失值、混合值、全 None 等场景） |
| | | | **已实现（P0-阻塞修复）：** |
| | | | **FIX-20** — `strategy_design.py` 事件循环阻塞修复。`_build_market_context` 和 `_compute_fund_flow` 改为 `async def`，使用 `asyncio.gather()` 并发获取全市场 fund flow（58 个标的从串行 58s→并行 8s）。`generate_enhanced_design` 中改用 `await _build_market_context()` 避免阻塞事件循环 |
| | | | **FIX-12c** — `strategy_design.py` 新增 `_validate_target_amount_consistency()` 函数。验证所有策略中 target_amount = capital × weight，不一致时记录 WARNING 日志 |
| | | | **FIX-05** — `routers/factors.py` 三个端点（`/model`、`/active`、`/ic`）新增 60s TTL 响应缓存和 Cache-Control/ETag HTTP 头，减少重复聚合计算 |
| | | | **FIX-11** — `pool_manager.py` `_deduplicate_by_index()` 增强。当 `tracked_index` 为空时使用名称推断概念去重（ETF + 联接C 合并），保留 fund_scale 最大（或纯 ETF 优先于联接C）的标的 |
| | | | **已审计（无需改动 — 前期已实施）：** |
| | | | **FIX-08** — `engine/rationale.py` 模板已修复，无 `{daily_change}%` 占位符（前期 Phase 6.2 已处理） |
| | | | **FIX-12** — 前端 ECharts 按需加载：所有组件已使用 `echarts/core` 子导入，无全量 `import * as echarts`（前期已处理） |
| | | | **FIX-13** — `rollup-plugin-visualizer` 已在 devDependencies 中、vite.config.js 已配置（前期 Phase 9 已处理） |
| | | | **FIX-14** — 路由级组件代码分割：所有路由已使用 `() => import()` 动态导入（前期 Phase 3.1 已处理） |
| | | | **FIX-02** — `china_market.py` 模块级 `requests.Session()` 共享复用，7 个调用点全部使用统一 session，避免每次调用创建新 SSL 连接（P1） |
| | | | **FIX-04** — `pool_manager.py` `_refresh_market_snapshot` 改为 `asyncio.gather` 并发获取指数行情和板块动量（P1） |
| | | | **FIX-06** — 新闻 TTL 统一缩减：headlines 120→60s, macro/global/stock 300→60s，降低资讯延迟（P2） |
| | | | **FIX-07** — `portfolio_service.py` `_build_price_map` 中港/美/NAV 行情获取从串行 for 循环改为 `ThreadPoolExecutor` 并发（P2） |
| | | | **FIX-10** — 新增 `_compute_confidence()` 纯函数，始终基于因子覆盖率计算置信度（不限 LLM source_confidence）。`strategy_check()` 返回值新增 `data_confidence` 字段（P2） |
| | | | **FIX-21** — `strategy_check_worker.py` 新增外层 120s `asyncio.wait_for` 超时保护，防止管线无限制挂起（P1） |
| | | | **FIX-03** — `cache_service.py` `RedisCache.init()` 添加 `if self.available: return` 幂等退出，`get/set/mget/mset` 惰性自动初始化（P2） |
| | | | **FIX-15** — 新增 `.lighthouserc.yml` Lighthouse CI 配置（3 页 × 3 次运行，性能≥60%, 无障碍/最佳实践/SEO≥80%）（P3） |
| | | | **改动文件：** `backend/app/fetchers/china_market.py`、`backend/app/core/ttl.py`、`backend/app/services/pool_manager.py`、`backend/app/services/portfolio_service.py`、`backend/app/tasks/strategy_check_worker.py`、`backend/app/services/cache_service.py`、`.lighthouserc.yml`、`docs/archived/optimization-master-plan.md`、`docs/implementation-master-plan.md` |
| | **v13.0** | 2026-07-28 | **Phase 13 — 系统综合诊断与优化 (system-diagnosis-and-optimization)** | 详见下方 |
| | **v13.1** | 2026-07-28 | **Phase 13d — 剩余诊断项实施 (LLM熔断+引擎fallback+内容校验+SSL复用)** | 详见下方 |
| | | | **已实现（P0 — 修复阻塞问题）：** |
| | | | **P0-1** — 因子 Z-score winsorization：`factor_registry.py` 新增 `ZSCORE_CLIP_BOUND = 5.0`，`_standardize()` zscore 分支返回前 clip 到 [-5, 5] 并记录极端值日志 |
| | | | **P0-2** — 市态判定单日涨跌幅阈值：`market_trends.py` `detect_market_regime()` 新增 `daily_change_pct` 参数，<-5%→panic、-5%~-3%→correction、>+5%→bull_strong、>+3%→bull_weakening |
| | | | **P0-3** — LLM 报告一致性增强：`design_report.py` `_validate_report_consistency()` 新增重复章节标题检测 + 去重、空白行折叠（4+→2）、fixes_applied 汇总日志 |
| | | | **P0-4** — Chart 500 错误修复：`market.py` chart 端点增加 `try/except` 包裹 + `_empty_chart_response()` fallback，KeyError 和通用异常均返回空结构 |
| | | | **P0-5** — 修复 margin_fetcher 未定义引用：`fundamentals_fetcher.py` line 724 `margin_fetcher.fetch_margin_balance` → `fetch_margin_balance`（合并后残留引用） |
| | | | **P0-6** — 三方案差异化：`allocation_engine.py` 新增跨方案 ETF 重叠度限制，后序方案对已选标的减 1.5σ 惩罚分 |
| | | | **已实现（P1 — 性能优化）：** |
| | | | **P1-1** — 预热超时缩减：`main.py` market_cache 25s→10s, global_indices 30s→15s；global_indices 新增 `indices_cache.json` 1h 本地缓存跳过检查 |
| | | | **P1-2** — factor-health 60s TTL 缓存：`admin.py` `/factor-health` 端点新增内存缓存避免每次触发 15s 全量计算 |
| | | | **P1-3** — 线程池队列深度监控：`async_utils.py` 新增 `get_queue_depth_spike_count()` 计数器 + 线程安全锁 |
| | | | **P1-4** — 前端 CLS 修复：`ChartPanel.vue` 图表容器添加 `min-height: 350px`，loading 状态加 `min-height: 300px` |
| | | | **已实现（P2 — 防护体系增强）：** |
| | | | **P2-1** — `verify_e2e.py` 新增 API 5xx 零容忍检查（`section_api_5xx_check`）、因子 Z-score 合理性门禁（`section_factor_zscore_check`）、方案差异化度 Jaccard 校验（`section_solution_diversity_check`） |
| | | | **P2-2** — 新增 8 个单测：4 个 winsorization 测试（`TestStandardizeWinsorization`）、5 个市态判定每日涨跌幅测试、3 个报告一致性测试 |
| | | | **P2-3** — 数据源 fallback 测试：`test_data_source_fallback.py` 18 个测试（主源成功跳过备用、空结果触发降级、异常触发降级、熔断跳过、HTTP 4xx/5xx 硬失败、冷却恢复、健康指标验证） |
| | | | **P2-4** — CI 门禁配置：`.lighthouserc.yml`（Lighthouse CI 3 次运行，Perf≥60%, 无障碍/SEO≥80%）、`backend/scripts/check_perf_budget.py`（预热≤5s, API avg≤3s, max≤10s） |
| | | | **改动文件：** `backend/app/factors/factor_registry.py`、`backend/app/services/market_trends.py`、`backend/app/tasks/design_report.py`、`backend/app/routers/market.py`、`backend/app/main.py`、`backend/scripts/verify_e2e.py`、`backend/tests/test_factor_registry.py`、`backend/tests/test_report_quality.py`、`backend/app/fetchers/fundamentals_fetcher.py`、`backend/app/engine/allocation_engine.py`、`backend/app/core/async_utils.py`、`backend/app/routers/admin.py`、`backend/tests/test_data_source_fallback.py`、`frontend/src/components/analysis/ChartPanel.vue`、`.lighthouserc.yml`、`backend/scripts/check_perf_budget.py`、`docs/implementation-master-plan.md` |
| | **v13.1** | 2026-07-28 | **Phase 13d — 诊断计划剩余项实施 (剩余 system-diagnosis-and-optimization 项)** | 详见下方 |
| | | | **已实现（P0 — LLM 熔断 + 引擎 fallback + 超时缩减）：** |
| | | | **P0-CB1** — LLM 熔断保护：`llm.py` `generate_design_report()` 新增 SourceRegistry 熔断器检查，熔断打开时跳过 LLM 调用直接返回引擎 fallback；LLM 成功/失败记录到 SourceRegistry 健康状态 |
| | | | **P0-CB2** — 引擎级 fallback 内容：`llm.py` 新增 `_build_engine_fallback()` 函数，基于策略数据和市态生成结构化降级报告（含因子评分、层预算、风险提示），即使 LLM 不可用也能返回有意义的报告 |
| | | | **P0-CB3** — 超时缩减：`config.py` `llm_primary_timeout` 90s→30s, `llm_fallback_timeout` 60s→30s，用户等待从最长 300s→120s |
| | | | **已实现（P1 — 报告内容校验 + SSL 会话复用）：** |
| | | | **P1-V1** — 设计报告内容校验：`design_report.py` 新增 `_validate_design_text()` 函数（检查方案详解标题、重复标题检测、截断描述、最小长度 200 字）、`_count_repeated_headers()` 工具函数 |
| | | | **P1-SSL1** — SSL 会话复用：`news_fetcher.py` 新增模块级 `_http_session = requests.Session()`，替换原 `requests.get()` 调用，复用 TCP + SSL 连接 |
| | | | **已实现（P2 — 预热退化告警）：** |
| | | | **P2-W1** — 预热性能退化告警：`main.py` lifespan 末尾新增预热耗时计算，超 30s→WARNING 日志提示，15-30s→INFO 记录 |
| | | | **新增测试（TDD 先写后实现）：** |
| | | | **T1** — `test_llm_circuit_breaker.py` 5 个测试（熔断打开跳过 LLM、熔断关闭正常调用、失败记录到 SourceRegistry、引擎 fallback 含策略数据、空策略处理） |
| | | | **T2** — `test_design_report_validation.py` 9 个测试（完整报告无警告、缺少章节、重复标题、过短、截断、空报告、无/有重复标题、无标题） |
| | | | **T3** — `test_ssl_session.py` 3 个测试（Session 实例验证、请求头验证、模块级属性验证） |
| | | | **改动文件：** `backend/app/config.py`、`backend/app/analysis/llm.py`、`backend/app/tasks/design_report.py`、`backend/app/fetchers/news_fetcher.py`、`backend/app/main.py`、`backend/tests/test_llm_circuit_breaker.py`（新）、`backend/tests/test_design_report_validation.py`（新）、`backend/tests/test_ssl_session.py`（新）、`docs/implementation-master-plan.md` |
| | **v13.2** | 2026-07-29 | **Phase 13e — LLM Provider 链路诊断修复 (plan v1.2)** | 详见下方 |
| | | | **已修复（P0 — LLM 熔断误伤 + system_override 丢弃）：** |
| | | | **FIX-CB** — 熔断器误伤修复：`llm.py` `generate_design_report()` 移除 circuit breaker 检查 (`registry._health().available()`)、`record_success()`/`record_failure()` 及 `_CIRCUIT_BREAKER_NAME` 常量。Provider failover 链（OpenCode Zen → DeepSeek）本身是充分的防护，熔断器在 Provider 短暂不可用时导致空报告误伤。引擎 fallback (`_build_engine_fallback()`) 保留作为 LLM 异常时的最后防线 |
| | | | **FIX-SO** — `system_override` 静默丢弃修复：`AgentRuntime.run()` 新增 `kwargs.get("system_override", self.system_prompt)` 处理，使得 `generate_design_report()` 传入的 `system_override=load_prompt("design_report.md")` 能被正确使用（原被静默忽略，始终使用 agent.default prompt） |
| | | | **新增测试（TDD）：** |
| | | | **T1** — `test_runtime_system_override.py` 4 个测试（system_override 覆盖、fallback 到默认、其他 kwargs 传递、无 kwargs 调用） |
| | | | **T2** — `test_llm_circuit_breaker.py` 更新至 5 个测试（熔断检查已移除：LLM 异常→引擎 fallback、LLM 成功→返回 LLM 内容、fallback 含策略数据、空策略、空市态） |
| | | | **改动文件：** `backend/app/analysis/llm.py`、`backend/app/analysis/runtime.py`、`backend/tests/test_runtime_system_override.py`（新）、`backend/tests/test_llm_circuit_breaker.py`（更新）、`docs/implementation-master-plan.md` |
| | **v13.3** | 2026-07-29 | **Phase 13f — 行号修复 | `strategy_design.py` 修复 CRITICAL 日志行号（原 hard-coded 1092 调整为当前 125） | 1 行 |
| | **v14.0** | 2026-07-29 | **Phase 14 — 诊断计划 P0 项实施 (system-diagnosis S1-S4/S8)** | 详见下方 |
| | | | **S4 — compute_chart_data 列名修复 (P0)**： |
| | | | **P0** — `compute_chart_data()` 改用 `_resolve_col()` 替代直接硬编码 `data["收盘"]` 索引。修复 English/Chinese 列名混用场景下的 KeyError。新增 `COL_MAP` 条目 `"开盘"` 和 `"成交量"`。 |
| | | | **测试：** `test_indicators.py::TestComputeChartData::test_english_column_names` — 验证 English 列名（close/open/high/low/volume）正确解析。 |
| | | | **改动文件：** `backend/app/analysis/indicators.py`、`backend/tests/test_indicators.py` |
| | | | **S3 — 本地快照兜底 (P0)**： |
| | | | **P0** — 新增 `snapshot_service.py`：线程安全的本地 JSON 文件快照服务，支持按 key 存取、TTL 过期、文件锁并发保护、损坏文件自动清除。 |
| | | | **测试（11 个）：** `test_snapshot_service.py` — save/load/expired/clear/clear_all/thread_safety/non_serializable/sanitize_key/corrupted_file/empty_data/concurrent_same_key |
| | | | **改动文件：** `backend/app/services/snapshot_service.py`（新）、`backend/tests/test_snapshot_service.py`（新） |
| | | | **S2 — 天天基金 IOPV 数据源 (P0)**： |
| | | | **P0** — 新增 `ttj_fetcher.py`：天天基金 fundgz 实时估值 API 封装，含 SourceRegistry 熔断器集成。提供 `fetch_etf_iopv()` 和 `fetch_etf_shares()`（stub）。解析 JSONP 格式 `jsonpgz({...})`。 |
| | | | **测试（5 个）：** `test_ttj_fetcher.py` — success/network_error/empty_result/circuit_open/stub_shares |
| | | | **改动文件：** `backend/app/fetchers/ttj_fetcher.py`（新）、`backend/tests/test_ttj_fetcher.py`（新） |
| | | | **S1 — 熔断器接入 market_service (P0)**： |
| | | | **P0** — 新增 `_call_with_cb()`：`market_service.py` 的 SourceRegistry 电路断路器感知调用包装，含可选内存缓存。`get_all_realtime()` 改用 `_call_with_cb()`。 |
| | | | **测试（6 个）：** `test_market_service_cb.py` — success/circuit_open/failure/cache_success/get_all_realtime/empty_result |
| | | | **改动文件：** `backend/app/services/market_service.py`、`backend/tests/test_market_service_cb.py`（新） |
| | | | **S8 — 腾讯 QQ 行情作为 IOPV 降级源 (P1)**： |
| | | | **P1** — `factor_registry._fetch_market_data()` 新增 QQ Tencent IOPV 降级：Sina 数据不足时自动尝试 `qt.gtimg.cn` 获取 ETF IOPV。双源自动切换，日志记录切换事件。 |
| | | | **改动文件：** `backend/app/factors/factor_registry.py` |
| | | | **综合测试结果：** 77 个测试通过（含新增 22 个），1 个跳过 |
| | **v17.0** | 2026-07-29 | **Phase 15 — 诊断计划 P0/P1 剩余项 (S1 CircuitBreaker废弃 + S2 shares注入)** | 详见下方 |
| | | | **S1 — 废弃 factor_registry.CircuitBreaker (P0 complete)**： |
| | | | **P0** — 移除 `factor_registry.CircuitBreaker` 类（类级熔断器），替换为 `SourceRegistry` 的 `factor.history` 源健康追踪。`is_open()` → `source_h.available()`，`record_failure()` → `source_h.record_failure()`，`record_success()` → `source_h.record_success()`。迁移 `test_async_boundaries.py` 和 `test_factor_registry.py` 中对应测试到 SourceRegistry。 |
| | | | **S2 — ETF 份额数据注入 (P0 partial)**： |
| | | | **P0** — `etf_scanner.py` 新增 `f85`(基金份额) 和 `f84`(基金规模备用) 字段查询与映射。`pool_manager.py` 将 `fund_shares` 注入 `symbol_extra` 数据管道。`factor_registry._fetch_market_data()` 透传 `fund_shares` 供 `_compute_shares_change` / `_compute_institutional_holdings_change` 消费。 |
| | | | **S9 — push2delay 字段增强 (P2)**： |
| | | | **P2** — ETF 扫描 URL 新增 `f84`/`f85` 字段，增强数据源交付能力。 |
| | | | **综合测试结果：** 83 个测试通过（原有 77 + 增量 6），1 个跳过 |
| | | | **改动文件：** `backend/app/factors/factor_registry.py`、`backend/app/fetchers/etf_scanner.py`、`backend/app/services/pool_manager.py`、`backend/tests/test_factor_registry.py`、`backend/tests/test_async_boundaries.py`、`docs/implementation-master-plan.md` |
| | **v16.0** | 2026-07-29 | **Phase 16 — P1/P2 剩余项 (S5 K线缓存 + S7 LLM报告 + S11新闻重试 + S12网易财经)** | 详见下方 |
| | | | **S5 — K线缓存统一 (P1)**： |
| | | | **P1** — `pool_manager.py` 新增 K 线缓存 (`_kline_cache`)，`get_kline()` 和 `refresh_kline()` 方法。`factor_registry.compute()` 调用改为优先使用 `market_data` 参数（缓存命中时减少 1 次重复 I/O），缓存过期时自动刷新重试。 |
| | | | **S7 — 策略检查报告增强 (P1)**： |
| | | | **P1** — `strategy_check_worker.py` 新增 `_generate_check_llm_comment()`：基于持仓分析结果调用 LLM 生成简短市场研判（150 字以内）。非阻塞设计，LLM 失败不影响主流程。`result.llm_comment` 字段供前端消费。 |
| | | | **S11 — 新闻系统稳定性 (P2)**： |
| | | | **P2** — `news_fetcher.py` 新增 `urllib.error` 导入（HTTP 500 重试准备）。数据源层已有超时包裹和 session 复用。 |
| | | | **S12 — 网易财经 K 线 (P2)**： |
| | | | **P2** — `china_market.py` 新增 `fetch_history_netease()` 函数：通过 `quotes.money.163.com` 获取历史 K 线，作为 mootdx/Sina 之外的降级兜底。CSV 格式，支持日线，自动区分上海(0前缀)/深圳(1前缀)。 |
| | | | **综合测试结果：** 93 个测试通过（3 个预置 pool_manager 外部依赖失败不属本次变更），1 个跳过 |
| | | | **改动文件：** `backend/app/services/pool_manager.py`、`backend/app/tasks/strategy_check_worker.py`、`backend/app/fetchers/china_market.py`、`backend/app/fetchers/news_fetcher.py`、`docs/implementation-master-plan.md` |

| | **v18.0** | 2026-07-29 | **Phase 18 — S10 前端性能优化 (Lighthouse)** | 详见下方 |
| | | | **S10 — 前端性能优化 (Lighthouse 57 -> 80)**： |
| | | | **P2** — `vite.config.js`：`cssCodeSplit: true`（路由级 CSS 分片，之前为 monolithic）、`modulePreload: { polyfill: false }`（entry chunk 预加载提示）。`index.html`：新增 `X-DNS-Prefetch-Control`、`link rel=modulepreload`、Content-Security-Policy 和外部数据源 preconnect。`package.json`：`@vue/compiler-sfc` 从 dependencies 移至 devDependencies（减少 130KB+ bundle 体积）。 |
| | | | **综合测试结果：** 前端构建成功 (5.67s)，32 个预缓存条目 (1140KB)，0 编译错误。后台 71 tests pass (3 pre-existing). |
| | | | **改动文件：** `frontend/vite.config.js`、`frontend/index.html`、`frontend/package.json`、`docs/implementation-master-plan.md` |
| | **v19.0** | 2026-07-29 | **Phase 19 — S5 剩余项实施 + S2 shares修复 + 未对齐项** | 详见下方 |
| | | | **S5 Step 6 — MarketDataHub 别名 (MarketDataHub = PoolManager)**： |
| | | | **P1** — 新建 `market_data_hub.py` 模块，`MarketDataHub = PoolManager` 别名。提供统一的 `get_kline_rows()`、`get_kline_symbols()` 接口。`api-contracts/market/market-data-hub.md` 契约文档。现有 `PoolManager` 引用无需修改。 |
| | | | **S5 Step 7 — get_history 全量接入 Hub 缓存**： |
| | | | **P1** — `market_service.get_history()` 改为优先查 `pool_manager.get_kline_rows()`，缓存命中直接返回，miss 降级到 `fetch_history()`。 |
| | | | **S2 — fetch_etf_shares 从 stub 改为真实 API 调用**： |
| | | | **P0** — `ttj_fetcher.fetch_etf_shares()` 从 `return None` stub 改为调用 push2delay API (f85 字段) 获取实时基金份额数据。包含 SourceRegistry 熔断器集成。 |
| | | | **新增 API 契约：** `api-contracts/market/market-data-hub.md` |
| | | | **综合测试结果：** 79 tests pass (0 pre-existing failures)，1 skipped |
| | | | **改动文件：** `backend/app/services/market_data_hub.py`（新）、`backend/app/fetchers/ttj_fetcher.py`、`backend/tests/test_s5_remaining.py`（新）、`api-contracts/market/market-data-hub.md`（新）、`docs/implementation-master-plan.md` |
| | **v20.1** | 2026-07-29 | **Phase 20 — 综合诊断剩余项修复 + CI/断言补全 + 文档归档** | 详见下方 |
| | | | **版本表:** v20.0 = F1(布林带)+F2(板块限额)+F3(ic_tracker); v20.1 = F13(CI)+F14(断言)+test修复+cleanup+归档8份文档 |
| | | | **F13 — Lighthouse CI 性能基线 (P3)**： |
| | | | 新增 `.github/workflows/performance.yml` — push/PR 到 main 时构建前端生产包、启动后端+Redis、运行 Lighthouse CI（Performance >= 50, LCP < 8s, TBT < 500ms）。新增 `.lighthouserc.js` — 本地 LHCI 桌面预设配置，上传至 temporary-public-storage。 |
| | | | **F14 — verify_e2e 技术指标质量断言 (P3)**： |
| | | | `verify_e2e.py` — 新增 `section_indicator_quality()`，检查 510300 的布林带有效性（upper > ma > lower, bandwidth > 0.001）。注册到 MODULES 调度。 |
| | | | **预置测试修复**： |
| | | | `test_design_optimization_plan.py` — `test_dq2_aggregate_factor_scores_aggregates_categories` 中 valuation key (`style.size.ln_mcap`) 被 `_EXCLUDE_FROM_VALUATION` 排除。新增 `etf.price.dividend_yield`: 0.6 使 valuation 聚合可计算。 |
| | | | **F1 — 布林带列名前缀匹配修复 (P0)**： |
| | | | `indicators.py` — pandas-ta 0.7+ 将 std 参数以浮点数形式编码至列名（如 `BBB_20_2.0_2.0`），原代码硬编码整数字符串（`BBB_20_2_2`）导致全部 4 条布林带值静默降为 0。改用列名前缀匹配（`BBB_20_`），兼容任意 pandas-ta 版本。 |
| | | | **F2 — 行业/概念板块默认限额修复 (P1)**： |
| | | | `market.py` — `industry_sectors` 和 `concept_sectors` 默认 limit 从 80 提升至 500，覆盖全量数据（行业 496 条、概念 513 条），移除 16% 覆盖率限制。 |
| | | | **F3 — ic_tracker._get_ic_sample_count 类型错误修复 (P1)**： |
| | | | `ic_tracker.py` — 原代码将 `list[dict]` 按 `dict` 使用（`factor_code not in self._records` 和 `self._records[factor_code]`），在 str 索引 list 时静默返回 0。改为遍历统计匹配记录数。 |
| | | | **新增测试：** `tests/test_diagnosis_remaining_fixes.py`（11 个新用例：4 布林带值校验 + 5 ic_tracker 样本计数 + 2 板块限额 API 契约） |
| | | | **综合测试结果：** 93 个相关测试通过（除 1 个标记为 @pytest.mark.slow 的集成测试需要真实数据源），0 回归 |
| | | | **改动文件：** `backend/app/analysis/indicators.py`、`backend/app/routers/market.py`、`backend/app/factors/ic_tracker.py`、`backend/tests/test_diagnosis_remaining_fixes.py`（新）、`backend/scripts/verify_e2e.py`、`backend/tests/test_design_optimization_plan.py`、`.github/workflows/performance.yml`（新）、`.lighthouserc.js`（新）、`docs/implementation-master-plan.md` |
| | **v21.0** | 2026-07-29 | **Phase 21 — 契约驱动 + 测试驱动：修复 4 个失败前端单测 + UI Phase 3 (Steps 6-8)** | 详见下方 |
| | | | **问题：** |
| | | | 1. 4 个前端单测失败（useMarketSearch 2 个 + useSectorAnalysis 2 个）— mock 目标从 `fetchJson` 误指向为 `../utils/fetchJson`，但真实 composable 已改用 `../api` (axios-based `marketApi`)。 |
| | | | 2. UI Phase 3 Steps 6-8 未实施（`frontend-ui-optimization-plan.md` v2 确认） |
| | | | **修复（TDD）：** |
| | | | **T1 — useMarketSearch mock 修复**：`vi.mock('../utils/fetchJson')` → `vi.mock('../api')`，所有 `fetchJson` 引用改为 `marketApi.search`。响应格式改为 `{ data: [...] }` 匹配 axios 封装。 |
| | | | **T2 — useSectorAnalysis mock 修复**：同上，`vi.mock('../utils/fetchJson')` → `vi.mock('../api')`，`fetchJson.mockResolvedValue([])` → `marketApi.getSectors.mockResolvedValue({ data: [] })`，参数断言从 URL 字符串匹配改为对象匹配。 |
| | | | **UI Phase 3 Step 6 — chartColors.js 抽象**：新建 `frontend/src/utils/chartColors.js`，提供 `CHART_COLORS`（8 色调色板，匹配 `--chart-1..--chart-8` CSS 变量）、`chartColor(name)`、`getChartColor(index)`、`histogramColor(value)`、`CANDLE_UP`/`CANDLE_DOWN` 常量。`AnalysisView.vue` 中 20 处硬编码 hex 值（`#22c55e`/`#ef4444`/`#3b82f6`/`#f59e0b`/`#a855f7`/`#94a3b8`/`#1e293b`）全部替换为 chartColors 引用。 |
| | | | **UI Phase 3 Step 7 — Skeleton 加载状态统一**：确认 `Skeleton.vue`（`frontend/src/components/ui/Skeleton.vue`）已完整实现（6 种变体 + shimmer 动画），被 Dashboard.vue 使用。无需额外实施。 |
| | | | **UI Phase 3 Step 8 — 响应式断点统一**：`Dashboard.vue` 和 `PortfolioManager.vue` 中 `@media (max-width: 480px)` → `@media (max-width: 640px)`，对齐全局 640/768/1024 三级断点体系。 |
| | | | **验证结果：** 256 个前端单测全部通过（25 个 spec 文件，0 失败）。 |
| | | | **改动文件：** `frontend/src/utils/chartColors.js`（新）、`frontend/src/components/AnalysisView.vue`、`frontend/src/test/useMarketSearch.spec.js`、`frontend/src/test/useSectorAnalysis.spec.js`、`frontend/src/views/Dashboard.vue`、`frontend/src/components/PortfolioManager.vue`、`docs/frontend-testing-safety-net.md`（状态更新）、`docs/frontend-ui-optimization-plan.md`（状态更新）、`docs/implementation-master-plan.md` |
| | **v22.0** | 2026-07-29 | **Phase 22 — 综合诊断 Phase 1：一击必杀（系统恢复运行基础）** | 详见下方 |
| | | | **来源：** `docs/comprehensive-diagnosis-report.md` §§11-12 |
| | | | **P0.5 — 全局 IPv4 优先策略（System Recovery）：** |
| | | | `backend/app/config.py` — 新增 `enable_ipv4_only()` / `disable_ipv4_only()` 辅助函数，模块加载时自动启用 IPv4，规避东方财富 CDN 的 IPv6 路由问题。`_original_getaddrinfo` 保存原始函数实现可逆恢复。 |
| | | | **P0.1 — 修复策略检查 LLM 导入错误：** |
| | | | `backend/app/tasks/strategy_check_worker.py` — 将 `_generate_check_llm_report()` 和 `_generate_check_llm_comment()` 中的 `from ..analysis.llm import llm_provider` / `llm_provider.chat()` 替换为 `from ..analysis.llm import llm_complete` + `asyncio.wait_for(llm_complete(prompt), timeout=X)`，适配 LLM 模块重构后的函数签名（string→string 而非 {content} dict）。 |
| | | | **P0.6 — 修复 LLM Advice 422 错误：** |
| | | | `backend/app/routers/analysis.py` — 将 `POST /api/v1/analysis/llm-advice` 端点签名从 `query: str = Query(...)`（触发 FastAPI 422）改为 `req: LLMAdviceRequest`（Pydantic 模型 request body）。新增 `LLMAdviceRequest` 模型类（含 `query: str` 和 `context: dict | None` 字段）。同步更新 `test_analysis_contract.py::test_llm_advice` 从 `?query=xxx` 改为 `json={"query": ...}`。 |
| | | | **P0.2 — 修复设计报告生成过渡到 completed：** |
| | | | 确认 `task_manager.py` 中 `design_pipeline` 已实现完整状态机（LLM 成功→completed, LLM 失败/异常→completed_with_errors, 超时→failed, 空策略→failed）。`generate_design_report()` 有 35s 外层 timeout 保护。新增 3 个单测验证所有过渡路径。 |
| | | | **P1.4 — 修复数据源探针准确性：** |
| | | | `backend/app/monitor/probes.py` — akshare 探针从 `stock_zh_a_hist()`（历史 K 线）改为 `stock_sector_spot_em()`（板块热点，系统实际使用的函数），更准确反映 akshare 数据源的可用性。 |
| | | | **新增单测：** `tests/test_phase1_diagnosis_fixes.py`（15 个用例：P0.5 IPv4 ×3、P0.1 LLM import ×5、P0.6 422 修复 ×1、P0.2 状态过渡 ×3、P1.4 探针 ×2、P3 E2E ×1） |
| | | | **验证结果：** 15/15 新单测 PASS；`test_analysis_contract.py::test_llm_advice` 修复后 PASS；无回归。 |
| | | | **改动文件：** `backend/app/config.py`、`backend/app/tasks/strategy_check_worker.py`、`backend/app/routers/analysis.py`、`backend/app/monitor/probes.py`、`backend/tests/test_phase1_diagnosis_fixes.py`（新）、`backend/tests/test_analysis_contract.py`、`docs/comprehensive-diagnosis-report.md`（状态更新）、`docs/implementation-master-plan.md` |

| | **v23.0** | 2026-07-29 | **Phase 23 - Diagnosis Phase 2a: Factor & Data Quality** | see below |
| | | | **Source:** `docs/comprehensive-diagnosis-report.md` \S\11-12 |
| | | | **P1.2d - Margin swap to akshare: (fundamentals_fetcher.py)** |
| | | | Replace `_fetch_szse()` / `_fetch_sse()` urllib HTTP (404) with `akshare.stock_margin_szse()` + `akshare.stock_margin_sse()`. Remove `_SZSE_URL`, `_SZSE_HEADERS`, `_SSE_URL`, `_SSE_HEADERS`, `urllib.request`/`json` dependencies. |
| | | | **P1.2e - Remove north_flow + add volume_ratio: (fundamentals_fetcher.py)** |
| | | | Remove `north_flow` from `SENTIMENT_WEIGHTS` and `_REGIME_WEIGHTS`, replace with `volume_ratio`. Delete `fetch_north_flow()` func. Add `_fetch_volume_ratio()` (akshare, 5d/20d avg volume ratio). Update `calc_sentiment_index()` signature and logic. New 4-dim weights: advance_ratio=0.30, margin_change=0.30, volume_ratio=0.20, inst_consensus=0.20. |
| | | | **P1.5 - HTTP connection pool expansion: (china_market.py)** |
| | | | Add `HTTPAdapter(pool_connections=30, pool_maxsize=60)` to shared `_session()`. |
| | | | **P1.1 - Market context fix:** Verify pool_manager has index_realtime, sector_momentum with fallback handling. |
| | | | **P1.2a - News factor pipeline:** Verify `_compute_news_heat()` / `_compute_news_direction()` receive data via `data.get("news_items", [])`. |
| | | | **P1.2b - premium_discount fix:** Verify `_compute_premium_discount()` uses `data.get("nav")` + `data.get("price")` (IOPV data from Sina/QQ). |
| | | | **P0.4 - Encoding:** Verify `config.py` sets `env_file_encoding = "utf-8"`. |
| | | | **New tests:** `tests/test_phase2a_data_quality.py` (18 cases) |
| | | | **Result:** 18/18 new tests PASS; Phase 1 15/15 also PASS; total 33/33 zero regression. |
| | | | **Affected files:** `backend/app/fetchers/fundamentals_fetcher.py`, `backend/app/fetchers/china_market.py`, `backend/tests/test_phase2a_data_quality.py` (new), `docs/implementation-master-plan.md` |

| | **v25.0** | 2026-07-29 | **Phase 25 - Frontend Optimization + Test Hardening** | see below |
| | | | **Source:** `docs/comprehensive-diagnosis-report.md` |
| | | | **P2.1 - ECharts lazy import:** Code already uses echarts/core/charts/components/renderers paths (tree-shakable). Removed full echarts from vendor-echarts manualChunks, only vue-echarts wrapper remains, ~800KiB saving. |
| | | | **P2.2 - Route lazy loading:** All 8 routes already use () => import(...) dynamic imports. No change needed. |
| | | | **P2.3 - Tree-shaking config:** Added rollupOptions.treeshake with moduleSideEffects=false, propertyReadSideEffects=false, tryCatchDeoptimization=false. |
| | | | **P2.4 - nginx Gzip:** Added full gzip config (on, min_length 1024, comp_level 6, types for JS/CSS/JSON/SVG/XML, vary header). |
| | | | **P3.1 - LLM import check (verify_e2e):** section_llm_import() verifies from app.analysis.llm import llm_complete works. |
| | | | **P3.2 - Task status assertion (verify_e2e):** section_task_status() checks design history has completed status records. |
| | | | **P3.3 - Cross-market search (verify_e2e):** section_search() tests HK (盈富基金) and US (SPY) search endpoints. |
| | | | **P3.4 - Source health check (verify_e2e):** section_admin() checks /admin/sources/health. |
| | | | **P3.5 - Encoding validation (verify_e2e):** section_encoding() checks for replacement chars in Chinese text. |
| | | | **P3.7 - Factor IC quality (verify_e2e):** section_factor_ic() checks /factors/ic endpoint. |
| | | | **Affected files:** frontend/vite.config.js, frontend/nginx.conf, backend/scripts/verify_e2e.py |

| | **v26.0** | 2026-07-30 | **Phase 26 — 架构优化：连接池配置 + 缓存持久化 + 任务生命周期** | 详见下方 |
| | | | **来源：** docs/comprehensive-diagnosis-report.md\|
| | | | **P4.1 — LLM 提供商策略模式（已验证已有完整实现）：** 确认 provider.py 已有 ProviderConfig dataclass + get_configured_providers() + call_with_failover() failover 链。5 个单测验证。
| | | | **P4.2 — 连接池可配置化：** config.py 新增 pool_connections(30)/pool_maxsize(60)；china_market.py _session() 从 settings 读取。
| | | | **P4.3 — 缓存持久化：** database.py 新增 _set_cache/_get_cache/_clear_cache TTL 缓存抽象（Redis 就绪接口，当前 fallback 到内存 dict）。
| | | | **P4.4 — 异步任务超时监控：** 验证 TaskManager 已有 created_at 时间戳、prune_tasks() 清理方法、TASK_TYPES TTL 配置。6 个单测验证生命周期管理。
| | | | **新增单测：** tests/test_phase5_architecture.py（16 用例：P4.1 LLM 策略 ×5、P4.2 连接池 ×3、P4.3 缓存 ×3、P4.4 生命周期 ×5）
| | | | **验证结果：** 16/16 新单测 PASS；之前所有 Phase 1-4 的 47/47 也 PASS；合计 63/63 无回归。
| | | | **改动文件：** backend/app/config.py、backend/app/database.py、backend/app/fetchers/china_market.py、backend/tests/test_phase5_architecture.py（新）、docs/implementation-master-plan.md\|
| | **v27.0** | 2026-07-30 | **Phase 27 — 系统诊断方案实施（契约驱动 + TDD）** | 详见下方 |
| | **v28.0** | 2026-07-30 | **Phase 28 — 系统诊断方案：偏差对齐 + 遗漏/推迟项** | 详见下方 |
| | | | **来源：** `docs/system-diagnosis-and-optimization-plan.md` |
| | | | **偏差对齐（先于遗漏项，回到方案字面）：** |
| | | | **D1 — F2 实现对齐：** 原 v27.0 将 `search(market="A")` 降级写成 levistock `fetch_all_stocks`；方案字面为「fallback 到 ETF 模式」。改为调用 `search_etf(keyword)`（与 F2 方案字面一致），并更新 `api-contracts/market/search.md` 第 5 条。 |
| | | | **D2/D3 — F16 门禁对齐：** `verify_e2e.py` search / drift-check 慢查询门禁由 10.0s 收紧到方案字面 5.0s。 |
| | | | **D4 — F20 完整性对齐：** china_specific 断言由 `no_data < count` 改为方案字面 `valid_count > 0`（数据真正可用而非仅非全缺失）。 |
| | | | **F6 — LLM 重试 (P3)：** `llm.py` `llm_complete` / `llm_complete_with_system` 外层增加 `for attempt in range(max_retries+1)` 重试循环，全供应商失败后重试 1 次（间隔 3s），常量 `LLM_MAX_RETRIES=1` / `LLM_RETRY_DELAY=3.0`。 |
| | | | **F8 — calculate 并行化 (P4)：** `portfolio_service.build_price_map` 改为异步并行：`asyncio.gather` 并发 A/HK/US/指数四批（各用 `run_sync` 包裹同步 I/O），NAV 兜底同样并行。公开签名 `async def build_price_map(etfs) -> dict` 不变。 |
| | | | **F14 — aiosqlite 日志降级 (P11)：** `core/logging.py` 预热期间 `logging.getLogger("aiosqlite").setLevel(WARNING)`，消除每条 SQL 的前后 DEBUG 字符串格式化开销。 |
| | | | **F3 — HK/US 跨市场搜索 (P2)：** `market_service.search_hk_us` 以静态 `HKUS_ETF_MAP` 为基础匹配，并实时补充行情（`get_asset_realtime` 经项目统一实时管道 TwelveData/Finnhub/HK 源）附加 `price`/`change_pct`；实时失败降级为仅静态结果（不抛错）。注：方案原文提 yfinance/akshare，但本项目已因境内不稳定移除 yfinance（见 `_route_us`），故采用既有实时管道等价补充。 |
| | | | **F7 — LLM 健康探针 (P3)：** 新增 `GET /api/v1/admin/llm/health`（并发探测所有已配置供应商、最小 prompt、`max_tokens=16`、不写 token_store、失败结构化返回不抛 500）。契约 `api-contracts/admin/llm-health.md`。 |
| | | | **F9 — ETF 扫描并行批处理 (P5)：** `etf_scanner._tencent_gtimg_batch` 由「逐块串行 HTTP」改为 `_tencent_gtimg_chunk` + `ThreadPoolExecutor` 并发（≤8 worker，小批量≤2 块走串行）；单块失败互不影响。 |
| | | | **F11 — demjson→orjson/json 守卫 shim (P5)：** 新增 `core/fast_json.py` `install_demjson_shim()`，用 orjson/json 快路径替换 akshare 的 `demjson.decode`，非严格 JSON 自动回退原 demjson；仅 `ETF_FAST_JSON=1` 时于启动期安装，默认不影响主路径。 |
| | | | **F12 — 前端 prod 构建调优 (P6)：** 修复 v25.0 P2.3 的 `treeshake: { moduleSideEffects: false }` 缺陷——该配置令 rollup 丢弃副作用入口（`main.js`→`app.mount`），导致生产构建只产出空 vendor chunk、无可执行 `<script>`，线上白屏。改为保留 rollup 默认副作用探测（仅 `propertyReadSideEffects:false`）；并新增 `build.target:'es2020'`、`cssTarget:'chrome80'`、函数式 `manualChunks`（按包名可靠拆分 vendor-vue/echarts/axios/marked）。`npm run build` 现已产出真实入口脚本 + 合理 vendor 分块。 |
| | | | **F13 — CLS 修复 (P6)：** `App.vue` `.main` 增加 `min-height: 70vh`，为异步路由视图加载预留垂直空间，避免内容塌陷造成的布局偏移（配合 `.lighthouserc.js` 的 CLS<0.1 硬门禁）。 |
| | | | **F17 — verify_e2e LLM 连通性 (P3)：** `verify_e2e.py` `section_llm_import` 新增 `GET /admin/llm/health` 连通性探针（端点恒 200；探测失败记为 degraded 不阻断 e2e）。 |
| | | | **F18 — Lighthouse CI 门禁：** `.lighthouserc.js` Performance 改为 `error` 硬门禁 `minScore 0.6`（方案字面 >60 最低线），CLS 设为 `error` `maxNumericValue 0.1`；`.github/workflows/performance.yml` 注释对齐 F18。 |
| | | | **F10 — 预热缓存 (P9)：** 经核查 `etf_scanner.fetch_all_etfs_base` 已实现内存缓存 + 文件缓存（`data/etf_list_cache.json`，4h TTL），满足「后续启动直接读取」，故 F10 视为已满足（本 turn 未额外改动，依赖 F9 加速首次扫描）。 |
| | | | **契约：** 新增 `api-contracts/admin/llm-health.md`（F7）；更新 `api-contracts/market/search.md`（F2 D1 / F3）。 |
| | | | **新增/扩展单测：** `tests/test_system_diagnosis_fixes.py` 扩至 **26 用例全 PASS**（F3×3 / F6 经 F4/F5 覆盖 / F7×4 / F9×2 / F11×2 / F14 经导入验证 / F19×3 等）；前端 `npm run build` 通过。 |
| | | | **来源：** `docs/system-diagnosis-and-optimization-plan.md` |
| | | | **F1 — timeline 端点 500 (P0)：** `backend/app/routers/portfolio.py` 的 `get_timeline()` 补 `from sqlalchemy import select`（函数内仅 import 了模型类与 json，缺失 `select` 导致 NameError 500）。 |
| | | | **F2 — A 股搜索断裂 (P1)：** `backend/app/routers/market.py` `search(market="A")` 在本地 `Instrument` 表为空（未预装）时，新增 levistock `fetch_all_stocks` 实时降级，按 keyword 过滤返回真实 A 股个股，杜绝 0 结果断链。HK/US 维持 `search_hk_us` 不变。 |
| | | | **F4 — LLM max_tokens (P3)：** `backend/app/analysis/llm.py` 三处 `max_tokens` 8192 → 12288（llm_complete 请求体、默认参数、stream 默认），确保 reasoning 模型留出 content 产出预算。 |
| | | | **F5 — 删除 reasoning_content fallback (P3)：** `llm_complete` / `llm_complete_with_system` 移除 `if not content: content = message.get("reasoning_content", "")`。reasoning_content 是模型内部思维链（scratchpad），非交付物；content 为空时 JSON 场景由调用方结构化 fallback、文本场景由引擎摘要兜底。下游 `_extract_json` 已在空文本时抛错并被各调用方 try/except 捕获。 |
| | | | **F19 — 因子 industry 注入 (P8)：** `backend/app/services/pool_manager.py` 的 `symbol_extra`（内联构建 + `_build_symbol_extra`）新增 `industry` / `concepts` 字段。三个 `china_specific` 因子（`five_year_plan` / `strategic_emerging` / `dual_circulation`）依赖 `data["industry"]`，此前因字段缺失恒为默认值 → IC 过滤全 no_data；注入后跨截面有变异，IC 可计算。 |
| | | | **F15 — verify_e2e 跨市场搜索覆盖：** `backend/scripts/verify_e2e.py` section_market 新增 `market=A/HK/US` 三组搜索断言（200 + 有结果 + 10s 门禁）。 |
| | | | **F16 — 响应时间门禁：** section_portfolio 为 `/timeline`、`/calculate` 增加 5s 慢查询门禁（`_check_response_time`）。 |
| | | | **F20 — 因子完整性检查：** section_factors 新增 `/factors/active` 断言 `total>=30` 且 `china_specific` 类别 `no_data_count < count`（F19 回归防护）。 |
| | | | **F22 — 预热门禁收紧：** section_health 预热失败线 30s→20s、警告线 15s→10s。 |
| | | | **契约：** 新增 `api-contracts/market/search.md`（F2 `market=A` 降级行为契约）。 |
| | | | **新增单测：** `backend/tests/test_system_diagnosis_fixes.py`（15 用例：F4 max_tokens=12288 ×1、F5 空 content 不泄露 reasoning ×2、F19 三因子 industry 消费 ×12）。 |
| | | | **验证结果：** 15/15 新单测 PASS；因子/LLM/pool 相关既有套件 77 PASS（3 个 pool_manager 用例为预存失败，与本次改动无关，已用 `git stash` 验证）。 |
| | | | **改动文件：** `backend/app/routers/portfolio.py`、`backend/app/routers/market.py`、`backend/app/analysis/llm.py`、`backend/app/services/pool_manager.py`、`backend/scripts/verify_e2e.py`、`backend/tests/test_system_diagnosis_fixes.py`（新）、`api-contracts/market/search.md`（新）、`docs/implementation-master-plan.md` |
| | | | **未实施（本期范围外，待后续 Phase）：** F3(HK/US 实时查询增强)、F6(LLM 重试)、F7(LLM 健康探针端点)、F8(calculate 并行化)、F9-F14(预热/前端性能)、F17(Lighthouse CI)、F18 等，见原方案实施路标。

| | **v40.0** | 2026-07-31 | **Phase 40 — z_fixes_design_v5.3 七项问题修复实施** | 详见下方 |
| | | | | **来源：** `docs/z_fixes_design_v5.3.md`（7 项：Z22/Z25/Z26/Z05/Z03/Z11/Z20） |
| | | | | **Z22 — watchlist 脏数据修复：** `WatchlistCreate.symbol` 加 `pattern=^[0-9A-Za-z.\-]+$`（拒绝中文）+ `asset_type` 默认 `"A"`；POST 增加行情存在性校验（无效代码 422）+ name 空串兜底；GET 增加脏数据自愈：`CODE_PATTERN` 不匹配或行情为 None → `market_service.resolve_symbol_to_code()` 名称反查（instruments 表精确/包含 → fetch_all_stocks 兜底）→ 独立短会话 `UPDATE watchlist` 回写（避免 rollback 影响主循环 session；唯一约束冲突仅 warning 不阻塞，响应仍用解析后的行情）。 |
| | | | | **Z25 — 热门个股补全：** `market_data_hub.get_stock_hot_rank` 新增 `_enrich_stock_hot_rank`：批量行情（`fetch_a_stock_batch`）join volume/turnover/price/change_pct + 行业映射 `get_stock_industry_map`（tushare stock_basic，1h 缓存）补 sector，批量行情自带 sector 优先；任一补全失败不阻塞主流程，字段留空/0。 |
| | | | | **Z26 — 策略检查覆盖率规则兜底：** `portfolio_service.strategy_check` ① LLM 调用加内层 20s 显式超时预算；② 新增 `_rule_based_suggestion`（因子分均值 + 技术信号 + regime 决策表，increase≤30% 风控 / decrease×0.7 / hold，confidence=0.7，source='rule'）；③ LLM 建议补 source='llm' + action 硬约束为 increase/decrease/hold；④ 响应新增 `coverage`（total_holdings/covered_by_llm/covered_by_rule/coverage_pct=1.0）；⑤ LLM prompt 增加「输出硬约束」段（action 小写枚举 + weight 字段必填）。 |
| | | | | **Z05 — SSL 连接池：** `global_markets_fetcher` 新增共享 `httpx.Client` 单例（limits 20/5 keepalive）+ `_http_get_json`，4 处 `urllib.request.urlopen`（Tencent/TwelveData/Finnhub/AlphaVantage）统一改造；新增 `get_connection_pool_stats()`（底层 pool `num_connections` 内省，容错 0）+ `/api/v1/admin/sources/connection-pool` 端点（provider + handshakes + reused）。 |
| | | | | **Z03 — 因子分类明细：** `factor_registry` 新增 `_sample_counts`/`_last_computed_at`（compute 时记录）；`/factors/active` 每因子新增 `status`(valid/warn/no_data/static) + `reason` + `sample_count` + `last_computed_at`；china_specific 三静态因子 `ic_value=null`（移除硬编码 0）+ `ic_threshold=0` + `status='static'`，不计入 summary valid/warn/no_data/avg_ic。 |
| | | | | **Z11 — design 降级契约：** `strategy_design` 新增 `STATIC_CORE_POOL`（6 只，中性元数据）+ `_build_static_pool_strategies`（STRATEGY_META.layer_budget 层内等权，生成 defensive/balanced/aggressive 3 套方案，不再硬编码权重/单方案）；空候选池、管线异常、部分因子缺失三分支统一暴露 `degradation` 字段（mode=static_pool/partial_data/normal + reason + factor_matrix_empty + pool_empty + static_pool_used + timestamp）。 |
| | | | | **Z20 — 搜索排序契约：** `market_service` 新增 `_sort_search_results`（7 档：精确代码→代码前缀→精确名称→名称前缀→名称包含→拼音首字母→其他；同档内 etf<stock、市场序 A<HK<US<index/commodity、symbol 字典序，确定性）；`search_etf` 本地表路径接入排序。 |
| | | | | **契约（新增 7 份）：** `api-contracts/market/watchlist-v2.md`、`market/stock-hot-rank-v2.md`、`portfolio/strategy-check-v2.md`、`admin/ssl-connection-pool.md`、`factors/active-v2.md`、`portfolio/design-degradation.md`、`market/search-sorting.md` — 均含行为契约 + Frontend-Backend Checklist + 测试清单。 |
| | | | | **测试（TDD，43 用例全 PASS）：** `tests/test_watchlist_dirty.py`（10）、`test_z25_stock_hot_rank.py`（6）、`test_z26_strategy_check_coverage.py`（5）、`test_z05_ssl_pool.py`（7）、`test_z03_factors_active.py`（3）、`test_z11_degradation.py`（4）、`test_z20_search_sort.py`（8）；既有相关套件回归 69/70 PASS（唯一失败 `test_orchestrator_returns_valid_strategies` 为基线即有的真实网络集成测试，已用 `git stash` 验证与本批改动无关）。 |
| | | | | **验证结果：** 后端新增 43 用例全 PASS；`verify_e2e.py` 全模块 PASS（本地启动后端后验证）；前端 `npm run build` 通过（pre-commit 门禁）；本地 `start.ps1 -Local` 前后端启动健康检查通过。 |
| | | | | **改动文件：** 后端 12（routers/market.py、services/market_service.py、models/schemas.py、services/market_data_hub.py、fetchers/sector_fetcher.py、services/portfolio_service.py、analysis/llm.py、fetchers/global_markets_fetcher.py、routers/admin.py、routers/factors.py、factors/factor_registry.py、services/strategy_design.py）、测试 7（新）、契约 7（新）、文档 2（implementation-master-plan.md + z_fixes_design_v5.3.md 状态）。 |

| | **v40.1** | 2026-07-31 | **Phase 40.1 — LLM 超时三层对齐（240s）修复** | 详见下方 |
| | | | | **背景：** Phase 40 验证期间观察 task 10/12 `completed_with_errors, quality=partial`。日志取证：`connect_tcp/TLS 均秒级成功`（服务商无故障），失败全为 `ReadTimeout(TimeoutError())`（免费模型 `deepseek-v4-flash-free` 高峰排队 >90s）；`CancelledError` 精确落在 task_manager LLM 阶段 150s 预算处（22:48:57+150s=22:51:27），非任务层 240s。 |
| | | | | **根因：** 三层超时错位 — provider 层 primary 90s/fallback 60s（.env）→ 单次必撞墙；`task_manager.py` LLM 阶段外层 150s（两次 provider 尝试后即被掐断）；`design_report.py` 内层 240s 永远够不到。 |
| | | | | **修复（方案 A 对齐放宽）：** `.env` `LLM_PRIMARY_TIMEOUT/LLM_FALLBACK_TIMEOUT 90/60 → 240/240`；`app/config.py` 默认值 30/30 → 240/240（Docker 无 .env 回落一致）；`task_manager.py` LLM 阶段 `timeout=150 → 240` + 注释更新；`design_report.py` 240s 保持。`strategy_check` 20s 预算（Z26 契约，快速降级设计）不受影响。 |
| | | | | **验证：** settings 加载 = 240/240；`test_llm_provider_failover.py` 11/11 PASS；task/design 相关套件 25/25 PASS；后端重启健康 200；预期效果：免费模型高峰有完整 240s 排队窗口，fallback 链（240s+240s）在任务层 240s 内可完成 1 轮完整尝试，不再必然 partial。 |

| | **v39.0** | 2026-07-31 | **Phase 39 — Z27 任务持久化重构（DB 唯一真相源）实施** | 详见下方 |
| | | | | **来源：** `docs/z27-task-persistence-redesign.md`（v2.1，已通过两轮独立审查） |
| | | | | **验收锚点（A1-A8）：** A1 重启后 `GET /tasks` 仍返回任务（同 DB 两实例单测 + 手工重启验证）；A2 design 任务 `record_id` 可关联 `GET /designs/{id}`；A3 check 任务 `record_id` 可关联 `GET /strategy-checks/{id}`；A4 `GET /tasks/{id}` 返回契约 11 字段；A5 `tasks.json` 不再被创建/读写；A6 WS `task_update` 携带 `record_id`+`task_type`；A7 启动遗留非终态任务→failed；A8 pytest/verify_e2e/npm test/build 全 PASS。 |
| | | | | **后端：** ① 新增 `models/task.py`（`TaskRecord`：task_type/status/progress/stage/params_json/result_json/error_message/record_id/created_at/completed_at，`to_dict` 输出 `task_id` 契约键）+ `database.py`/`models/__init__` 注册；② `task_manager.py` 重构为 DB-backed async：删除 `_save/_load/_persist_path/DEFAULT_PERSIST_PATH/_next_id/JSON 读写`，`create_task/get_task/update_task/list_tasks/prune_tasks` 全 async（session_factory 注入 D10 + 模块级 `async_session` 惰性解析 D11），保留期 `RETENTION_TERMINAL_DAYS=7`/`MAX=100`（单条 SQL 剪枝，活跃任务永不清理）；③ `_notify` 增 `record_id`+`task_type`；④ `design_pipeline` 全调用加 `await`，成功/`completed_with_errors`/空分配路径回写 `record_id=design_id`（M8 顺序：空分配在 design_id 产生后补发 WS）；⑤ `strategy_check_worker`（本地 `_notify` 同步补 `record_id`+`task_type=check`）、`report_worker`（`task_type=report`）、`worker_registry.dispatch` 适配 await；⑥ `routers/portfolio.py`：`GET /tasks/{id}` 返回契约全量 dict、`GET /tasks` limit 默认 20（契约/路由/前端统一）、POST 端点 await；⑦ `main.py` A04 重写为 DB-backed `_cleanup_stuck_tasks`（pending/running/quick_ready→failed+「后端重启，任务中断」）。 |
| | | | | **前端：** `task.js` store `_normalizeTask` 增 `recordId`（record_id || design_id 推导）、`completed_with_errors` warning toast；`App.vue` WS 处理按 `task_type` 初始化任务类型/label + `record_id`/`design_id` 回写；`TaskIndicator.vue` check 任务点击跳 `/portfolio-analysis`、`completed_with_errors` 可点击、`quick_ready`/`completed_with_errors` 中文状态文案；`DashboardAiTools.vue` 修复 `loadHistoryList` 引用未定义 `checks` 的 ReferenceError（改用 timeline `data.items`，删除 designRes/checkRes 死代码）；`api/index.js` `listTasks` 默认 20。 |
| | | | | **契约：** `api-contracts/portfolio/tasks.md` — §2.3 状态枚举补 `quick_ready`/`completed_with_errors`；新增 §2.4.1 状态枚举语义、§2.4.2 WS `task_update` 消息契约（`record_id`/`task_type` 必填）；Checklist 追加 7 项。 |
| | | | | **测试（TDD）：** 新增 `tests/db_fixtures.py`（共享 fixture：session 级独立 SQLite 测试库，建齐 tasks+portfolio_designs+strategy_check_records 三表，D10 注入）+ `tests/conftest.py` 注册 + `tests/test_task_db_persistence.py`（**18 用例**：契约字段/重启恢复/排序分页/保留期剪枝/活跃永不清理/record_id 关联/A5 无 JSON/A7 收敛/A6 WS record_id）；结构性适配 12 个既有测试文件（test_design_tasks/test_design_status/test_design_pipeline_integration/test_v5_diagnosis_fixes/test_phase0_7/test_phase1_diagnosis_fixes/test_phase5_architecture/test_report_quality/test_solution_design_plan/test_market_context/test_design_optimization_plan 等，MagicMock→AsyncMock、task_id 不硬编码、同库双实例替代 JSON 重启）；`verify_e2e.py` 新增 `section_task_persistence`（POST design-async → 轮询终态 → 契约字段 + `GET /designs/{record_id}` 关联 + 列表含 record_id）并注册 `task-persistence` 模块。 |
| | | | | **验证结果：** 后端 pytest（`-m "not slow and not integration"`）**全量 PASS**（含适配后 194+ 用例；唯一 slow 网络用例 `test_orchestrator_returns_valid_strategies` 为基线即有的环境性失败，实时数据管道 0 标的）；前端 **273 用例 PASS**（28 文件，含新增 TaskIndicator.spec.js 5 用例 + DashboardAiTools.history.spec.js 2 用例 + taskStore recordId 3 用例 + App.spec WS 2 用例）。 |
| | | | | **改动文件：** 后端 10（models/task.py 新、database.py、models/__init__.py、tasks/task_manager.py、tasks/strategy_check_worker.py、tasks/report_worker.py、tasks/worker_registry.py、routers/portfolio.py、main.py、scripts/verify_e2e.py）、测试 15（test_task_db_persistence.py 新、db_fixtures.py 新、conftest.py 新、12 个适配）、前端 9（stores/task.js、App.vue、TaskIndicator.vue、DashboardAiTools.vue、api/index.js、4 个 spec）、契约 1（tasks.md）、文档 2（implementation-master-plan.md、z27-task-persistence-redesign.md 状态）。 |
| | **v38.0** | 2026-07-31 | **Phase 35 — Z15(verify_e2e强化) + Z29(搜索自动补全) 实施** | 详见下方 |
| | | | | **来源：** `docs/v5_z15_z29_implementation_design.md`（v2.1，仅 Z15 + Z29 两项） |
| | | | | **Z29 — 后端搜索（4 处改动）：** ① `HKUS_STOCK_MAP` 静态个股基座（15 港股 + 18 美股龙头，离线可用）；② `china_market.py` 新增 `fetch_hk_spot_list`/`fetch_us_spot_list`（akshare spot，6h 长 TTL 缓存，列名兼容 + HK 代码 zfill(5) 补零，失败返回 [] 绝不抛）；③ `search_hk_us` 重写为三级搜索（静态基座 → include_stocks 时 spot 动态补充 → 仅 type=="etf" 命中实时 enrich），`asset_type` 统一为市场代码 `"HK"/"US"`、`type` 为 `"etf"/"stock"`，归一化 symbol 去重基座优先（`盈富基金` 恰好一条不误标 stock）；④ `/market/search` 路由重写：`market=HK/US` 透传 include_stocks，`market=null/global` 跨市场合并（search_etf 过滤非 ETF 行 + `_search_a_stocks` instruments→levistock 降级链 + HK→US 排序，各段 top10 总计 ≤30，(market,symbol) 去重）。 |
| | | | | **Z29 — 前端（2 处）：** WatchlistPanel `doSearch` 传 `{include_stocks:true}`；`selectSuggestion` 对 HK/US 结果回填 `form.asset_type`（否则 AAPL/00700 按 A 股入库无行情）。 |
| | | | | **Z15 — verify_e2e C1-C9：** C1 section_search 消灭恒过（510300/盈富基金/SPY 逐条断言非空）；C2/C3 新增 `hk-market`/`us-market` 模块（个股 + ETF 基座，market 字段校验）；C4 `factor-health` 别名薄包装；C5 section_fundamentals 严格化（500/异常 → FAIL，清理乱码标签）；C6 check_sector_data 追加 `/sectors/rotation` 轮动门禁；C7 删除弱版 section_admin 重复定义（sources/health 并入强版）；C8 模块注册 + main() 特判元组补 factor-health；C9 F15 断言 HK/US URL 补 `&include_stocks=true`。 |
| | | | | **契约：** `api-contracts/market/search.md` 更新至 v3.0（market=null 跨市场语义 / include_stocks 按分支生效 / asset_type=市场代码 / 截断排序约束 / HK-US 个股响应示例）。 |
| | | | | **测试：** 后端新增 `tests/test_z29_search.py` **14 用例全 PASS**（个股搜索/中英文名/静态兜底/include_stocks 语义/基座优先去重/asset_type 市场代码/spot 不 enrich/路由级跨市场合并+排序+去重/levistock 降级链）；既有 F3 × 3 回归通过；相关套件 140 用例全 PASS；前端新增 WatchlistPanel.spec.js 4 用例 + useMarketSearch 编码防护 1 用例全 PASS，`npm run build` 通过。 |
| | | | | **验证结果：** 后端 `python -m pytest` 分段回归全绿（0-75% 段在批量运行中全 PASS；其余 25% 段 201 用例含 test_z29_search 14 用例 + F3 回归全 PASS；另 140 个相关用例全 PASS）；verify_e2e `search,hk-market,us-market,fundamentals,sectors,admin` 模块全 PASS（factor-health 的 2 项因子 IC 断言依赖线上数据管道，本机离线环境下 pool 为空故失败，与本次改动无关）；前端 Playwright 实测：00700→asset_type=HK / AAPL→US / 600519→A 全部命中且回落正确、无 console error；`npm run build` 通过。 |
| | | | | **实施后加固（本批次追加）：** spot 拉取改并发（`asyncio.gather`，串行 10s×2 → 并发 10s）+ 失败/空结果短缓存 60s（网络不可用时每次搜索不再重复阻塞，首击 ~9s → 后续瞬时）；`selectSuggestion` 对 A 股结果显式回落 `asset_type='A'`（防止先选 AAPL(US) 再选 A 股标的使用错误市场类型入库）。 |
| | | | | **改动文件：** `backend/app/services/market_service.py`（HKUS_STOCK_MAP + search_hk_us 重写）、`backend/app/routers/market.py`（search 路由 + _search_a_stocks）、`backend/app/fetchers/china_market.py`（2 个 spot fetcher）、`backend/app/core/ttl.py`（2 个 6h TTL）、`backend/scripts/verify_e2e.py`（C1-C9）、`backend/tests/test_z29_search.py`（新）、`frontend/src/components/market/WatchlistPanel.vue`、`frontend/src/components/market/WatchlistPanel.spec.js`（新）、`frontend/src/test/useMarketSearch.spec.js`、`api-contracts/market/search.md`、`docs/implementation-master-plan.md` |
| | | | | **已知问题（非本方案范围）：** 前端全量 `npm test` 中 TokenMonitor「renders granularity tab labels」1 例失败为**预存 flake**（隔离运行通过、与本次改动无关，已用 git stash 验证）；R4/R5 设计风险照旧（HK 个股实时 enrich 前缀 bug 由「个股一律不 enrich」规避；US spot 境内网络不可用时降级静态基座）。 |


| | | | | **来源：** `docs/architecture-migration-plan-v6.md`（v6.3） |
| | | | | **Phase 0 — 重命名收尾 (1313c6f)：** 清理 17 个源文件/测试中 pool_manager 注释残留；grep 终检空。 |
| | | | | **Phase 1 — 新闻聚合 (d9099b6)：** hub 新增带标签新闻桶（headlines/macro/global）+ 懒刷新；9 个新闻直连点改向 hub；main.py 新增 120s news 循环。 |
| | | | | **Phase 2 — 板块/基本面/历史聚合 (94e4a07)：** hub 新增 8 个委托方法；8 个直连点改向；修复 macro_state await 同步方法的真 bug。 |
| | | | | **Phase 3 — 实时/指数/商品/搜索聚合 (c531958)：** hub 新增 12 个 market_service 委托方法；8 个直连点改向；market_router 成为纯委托层。 |
| | | | | **Phase 4+5 — 因子收尾 + DoD 终检 (22086c8)：** 辖剩 15 个 fetcher 直连点全部改向 hub（levistock/sector/china_market/global/news）；修复 global_markets_fetcher.fetch_history 死代码重定义（mypy 解析错误签名）。 |
| | | | | **DoD 验证：** (1) 上层无 fetchers 直连 0；(2) 上层无 market_service 直连 0（但 market.py watchlist CRUD 保留，组合管理范围免除）；(3) factor_registry 无直连。全量 852 passed / 0 failed；mypy 93 文件 Success；npm build 通过；E2E 关键路由 200。 |
| | | | | **改动文件：** hub +27 个公共方法；10 个源文件迁移；6 个测试更新；2 个新测试文件；AGENTS.md + implementation-master-plan.md |

| | **v36.0** | 2026-07-31 | **Phase 33 — 数据管道入口改名 (pool_manager → MarketDataHub)** | 详见下方 |
| | | | | **背景：** pool_manager 名不副实—它早已从“ETF 候选池管理”沿变为“全市场数据入口”（20 个公开方法中只有 get_pool/get_by_code 与池相关）。本次彻底改名——不是架构统一，而是命名纠正，为将来的 god-object 拆分腾出干净名称。 |
| | | | | **实施内容：** git mv pool_manager.py → market_data_hub.py（保留 git 历史）；类 PoolManager → MarketDataHub；单例 pool_manager → market_data_hub；删除旧别名文件与 pool_manager re-export；修复潜在 NameError（analysis.py:373/446 传 pool_manager 但未 import，admin.py:227）+函数参数名更新；全部测试 mock 路径迁移。 |
| | | | | **测试：** 全量 795 passed / 38 failed（均为预存在失败：缺少模块的 fetcher 测试、网络依赖、因子聚合旧账），改名带来 0 新失败。E2E 16/16 PASS。 |
| | | | | **改动文件：** backend/app/services/market_data_hub.py（重命名+类改名）、backend/app/services/pool_manager.py（删除）、源文件 9 个（NameError 修复）、测试 17 个 + conftest.py + scripts 2 个（mock 路径迁移）、AGENTS.md、docs/implementation-master-plan.md |

| | **v35.0** | 2026-07-31 | **Phase 32 — Z18 新闻 AI 分析管道增强** | 详见下方 |
| | | | | **来源：** `docs/v5_diagnostic_and_optimization_plan.md` Z18 |
| | | | | **Z18 — 新闻 AI 分析管道增强 (中)：** fetch_news_headlines 原只返回 3-5 条（仅依赖财联社主源）。修复：新增 fetch_eastmoney_news() 作为财经头条补充源（_ak akshare 线程池保护，4s 超时），插入财联社与宏观新闻之间。同时增强 analyze_news() LLM prompt—新增情绪指数(0-100)、版块影响列表(正面/负面)、新闻一致性检查。 |
| | | | | **改动文件：** backend/app/fetchers/news_fetcher.py（新增 fetch_eastmoney_news）、backend/app/analysis/llm.py（analyze_news prompt增强）、docs/implementation-master-plan.md（本版本更新） |

| | **v34.0** | 2026-07-31 | **Phase 30e — v5 诊断方案最终项：Z19 修复** | 详见下方 |
| | | | | **来源：** `docs/v5_diagnostic_and_optimization_plan.md` |
| | | | | **Z19 — report_quality 提升 (P2)：** `/portfolio/designs` list endpoint 原只载入 design_text/strategies_json 等大字段，但忽略了 report_quality 和 report_generated_at，导致前端列表页无法显示报告状态。修复：在 load_only 列表和返回 dict 中均新增 report_quality/report_generated_at。详情端点已有该字段，无需变更。 |
| | | | | **改动文件：** backend/app/routers/portfolio.py（Z19）、docs/implementation-master-plan.md（本版本更新） |

| | **v33.0** | 2026-07-31 | **Phase 30d — v5 诊断方案实施：Z31/Z32/Z33 修复** | 详见下方 |
| | | | | **来源：** `docs/v5_diagnostic_and_optimization_plan.md` |
| | | | | **Z31 — 行情分析页 Tab 切换无效 (中)：** SectorHeatMap 组件未接收 marketTab prop，切换 A/HK/US/global 标签时该组件不响应。修复：SectorHeatMap.vue 新增 defineProps({ marketTab }) + watch(() => props.marketTab, fetchData)；父组件 MarketAnalysis.vue 的 SectorHeatMap 改为 SectorHeatMap marketTab="{{" marketTab "}}" 。 |
| | | | | **Z32 — 新闻 AI 智能分析 prompt 方向错误 (中)：** llm.py:798 批量分析 prompt 写“对组合调仓的潜在启示”（无组合上下文）；llm.py:823 单条分析 prompt 写“对组合的影响”。修复：批量改为“对市场的潜在影响及启示”；单条新增 has_holdings 判断—有持仓时“对组合的影响”+ 无持仓时“对市场整体的影响”。 |
| | | | | **Z33 — 线程池误列在数据源 admin 页面 (低)：** SourceMonitor.vue 将 threadpool_main/threadpool_akshare 探针混在数据源表格中。修复：enrichedSources 新增 category 字段（data/system），表格新增类型列以示区分。 |
| | | | | **改动文件：** backend/app/analysis/llm.py（Z32）、frontend/src/components/market/SectorHeatMap.vue（Z31）、frontend/src/views/MarketAnalysis.vue（Z31）、frontend/src/components/SourceMonitor.vue（Z33）、docs/implementation-master-plan.md（本版本更新） |

| | **v32.0** | 2026-07-31 | **Phase 30c — v5 诊断方案验证：Z22/Z28/Z29/Z30 单元测试覆盖** | 详见下方 |
| | | | | **来源：** docs/v5_diagnostic_and_optimization_plan.md |
| | | | | **Z22 — 个股 watchlist 行情 (P1)：** get_asset_realtime 已正确处理 stock asset_type。新增单元测试验证 600519(stock) 和 510300(A) 两种资产类型均能返回 price/change_pct。 |
| | | | | **Z28 — watchlist 字段一致性 (P3)：** get_watchlist 返回的 
ealtime dict 使用英文 key（price/change_pct/volume），无中文字段名。新增单元测试验证字段名纯 ASCII。 |
| | | | | **Z29 — 搜索中文编码 (P3)：** FastAPI Query 参数自动处理 URL 编码/解码。新增单元测试验证中文关键词 贵州茅台 的 URL 编解码往返。 |
| | | | | **Z30 — LLM 数据管道完整性 (中)：** uild_full_context 在数据源失败时不会崩溃（异常静默降级）。新增单元测试验证结构完整性 + 异常安全。 |
| | | | | **新增单测：** 	ests/test_v5_remaining_fixes.py（8 用例：Z22×2、Z28×2、Z29×2、Z30×2）。全 PASS。 |
| | | | | **改动文件：** ackend/tests/test_v5_remaining_fixes.py（新）、docs/implementation-master-plan.md（本版本更新） |

| | **v31.0** | 2026-07-31 | **Phase 30b — v5 诊断方案剩余项：TaskManager/策略检查/板块轮动** | 详见下方 |
| | | | | **来源：** `docs/v5_diagnostic_and_optimization_plan.md` |
| | | | | **Z27 — TaskManager persist path 修复 (P1)：** `DEFAULT_PERSIST_PATH` 原为 `app/tasks/../data/tasks.json` → `backend/app/data/tasks.json`（不存在的目录）。**修复：** 改为 `../../data/tasks.json` → `backend/data/tasks.json`。 |
| | | | | **Z26 — 策略检查建议覆盖全 (P2)：** `generate_strategy_check_report` LLM prompt 仅有 `max_suggestions` 上限，LLM 倾向于跳过无因子数据的标的，建议数不足。**修复：** 新增 `min_suggestions = max(3, holdings_count // 2)` 下限 + prompt 中改为"建议条数范围: {min}~{max} 条（下限{min}条，必须覆盖每个持仓标的至少一条建议）"。 |
| | | | | **Z17 — 板块轮动 422 (P2)：** `/api/v1/market/sectors` 路由中 `type` 参数为 `Query(...)`（必需），前端未传参时返回 422。**修复：** `type` 改为 `Query("industry")`（默认值）；新增 `/sectors/rotation` 路由暴露 `fetch_sector_industry_cls`；前端 `api/index.js` 新增 `getSectorRotation()`。 |
| | | | | **Z25 — 热门个股 API 丰富 (P2)：** 前端 `marketApi` 新增 `getSectorRotation` 接口。 |
| | | | | **新增单测：** `tests/test_v5_diagnosis_fixes.py` 扩至 **14 用例全 PASS**：新增 Z27×4(persist path / create-get / list / update)、Z26×1(function signature)、Z17×1(fetch_sector_industry_cls callable)、Z25×1(stock_hot_rank callable)。 |
| | | | | **改动文件：** `backend/app/tasks/task_manager.py`（Z27）、`backend/app/analysis/llm.py`（Z26）、`backend/app/routers/market.py`（Z17）、`frontend/src/api/index.js`（Z17/Z25）、`backend/tests/test_v5_diagnosis_fixes.py`（扩至14用例）、`docs/implementation-master-plan.md`（本版本更新） |

| | **v30.0** | 2026-07-31 | **Phase 30a — v5 诊断方案实施：契约驱动 + TDD 修复6项问题** | 详见下方 |
| | | | | **来源：** `docs/v5_diagnostic_and_optimization_plan.md` |
| | | | | **Z21 — 510300 涨跌幅-112% 显示bug (P0)：** `frontend/src/components/market/WatchlistPanel.vue` `formatPct()` 中 `(pct * 100).toFixed(2)` 将 API 返回的百分比值（-1.12 = -1.12%）错误地乘以 100，导致显示 -112%。**修复：** 去掉 `* 100`，改为 `pct.toFixed(2) + '%'`。 |
| | | | | **Z23 — 热点板块 404 (P0)：** `backend/app/fetchers/sector_fetcher.py` `fetch_hot_plates()` 在 levistock `get_sector_hot_plates()` 抛出异常时未捕获，导致路由 500/404。**修复：** 在内部 `_p()` 函数中添加 `try/except`，捕获异常后返回空列表。 |
| | | | | **Z24 — AI 投资顾问 HTTP 500 (P0)：** `backend/app/routers/analysis.py` 中存在两个 `LLMAdviceRequest` 类定义（L131+L224），第二个覆盖第一个，`market` 字段丢失。前端发送 `{query, market}` 时 market 被 Pydantic 静默丢弃。**修复：** 删除第二个重复定义（L224-227），仅保留第一个完整模型（含 `query: str, market: str = "A", context: dict|None = None`）。 |
| | | | | **Z15 — verify_e2e 补充 (P1)：** `backend/scripts/verify_e2e.py` 的 `section_search()` 原使用 `requests.post(..., json={"query": ...})`，但 `/search` 路由实际为 `GET /api/v1/market/search?keyword=...`，该测试从未正确运行过。**修复：** 改为 `requests.get(params={"keyword": ...})`；新增 A 股搜索(510300) + HK(盈富基金) + US(SPY) 三项测试，含返回列表校验。 |
| | | | | **Z16 — 基本面 500 检查 (P2)：** verify_e2e 未覆盖 fundamentals 端点。**修复：** 新增 `section_fundamentals()`，测试 `/api/v1/market/fundamentals/510300` 端点可达。 |
| | | | | **新增单测：** `backend/tests/test_v5_diagnosis_fixes.py`（9 用例：Z21×1(纯逻辑)、Z23×3(异常兜底/正常返回/路由异常)、Z24×2(market字段/query必填)、Z22×2(get_asset_realtime stock/非ETF)、Z15×1(section_search 存在性)）。全 PASS。 |
| | | | | **改动文件：** `frontend/src/components/market/WatchlistPanel.vue`（Z21）、`backend/app/fetchers/sector_fetcher.py`（Z23）、`backend/app/routers/analysis.py`（Z24）、`backend/scripts/verify_e2e.py`（Z15/Z16）、`backend/tests/test_v5_diagnosis_fixes.py`（新）、`docs/implementation-master-plan.md`（本版本更新） |

| | **v29.0** | 2026-07-30 | **Phase 29 — 系统诊断方案剩余项：契约驱动 + TDD 实施六处修复** | 详见下方 |
| | | | | **来源：** `docs/system-diagnosis-and-optimization-plan.md` |
| | | | | **Z01 — factor-health 500 (P0)：** `backend/app/routers/admin.py` `get_factor_health()` 使用的 `time.time()` 作用域外缺失 `import time`，导致函数调用 500。**修复：** 将 `import time` 提升至模块顶部。 |
| | | | | **Z02 — 美股行情 null (P1)：** `global_markets_fetcher.py` 合并三个数据源后函数名冲突——三个同名的 `fetch_realtime`、`_request`、`_get_apikey`、`_API_BASE` 互相覆盖，Python 只保留最后一个（Finnhub），导致 TwelveData 不可达。FRED 的 `_API_BASE` 在 Finnhub 之后定义，覆盖了 Finnhub URL。**修复：** 统一为各数据源独立命名（`_AV_API_BASE`/`_TD_API_BASE`/`_FRED_API_BASE`、`_get_av_apikey`/`_get_td_apikey`、`_av_request`/`_td_request`/`_request(FH)`、`fetch_realtime_alphavantage`/`fetch_realtime_twelvedata`/`fetch_realtime(FH)`）；`_route_us()` 的 `_td()` 路由改为 `fetch_realtime_twelvedata`。**验证：** Finnhub SPY=729.46 -1.54% ✅ / TwelveData SPY=729.46002 -1.54% ✅ |
| | | | | **Z03 — china_specific IC 显示 (P1)：** `backend/app/routers/factors.py` `get_active_factors()` 中，三个 china_specific 静态映射因子（`five_year_plan` / `strategic_emerging` / `dual_circulation`）在 `_last_ic_batch` 为空时 `ic_value` 为 None（非空则赋 `self._last_ic_batch.get(f["code"])`），前端显示异常。**修复：** 当 `ic_value` 为 None 时，静态因子赋 `ic_value=0`，避免前端表格 `ic_value` 空缺。 |
| | | | | **Z04 — etf_specific 数据注入 (P0)：** 10 个 etf_specific 因子的 `_compute_*` 函数已全部存在，但依赖字段如 `benchmark_close`（tracking_error）、`shares_change_20d`（shares_change）、`industry`/`concepts`（industry_diversification）在 `_fetch_market_data()` 中未被填充至 market_data，导致这些因子一直返回默认值。**修复：** `_fetch_market_data()` 在 NAV 批量获取后，将 `symbol_extra` 中的 `benchmark_close`、`shares_change_20d`、`industry`、`concepts`、`institutional_holdings_change`、`fund_scale` 等字段注入 market_data（不覆盖已有字段）。 |
| | | | | **Z10 — 信号阈值放松 (P2)：** `backend/app/analysis/signal.py` `generate_signal()` 原先 BUY/SELL 阈值为 `>= 2` / `<= -2`，信号过于保守；最高可达分约 7 分，±2 导致大量信号落入 hold 区间。**修复：** 阈值下调至 `>= 1.5` / `<= -1.5`，同时保留 hold 区间位于 0 附近（-1.0~+1.0 仍为 hold）。 |
| | | | | **Z11 — 设计熔断器兜底 (P3)：** `backend/app/services/strategy_design.py` 原实现在数据管道（`get_factor_matrix`/`get_pool`）全部断裂时直接返回 `strategies: []` 错误。**修复：** 空候选池时（`total_candidates == 0`），改为使用静态池（`pool_manager.etf_pool` 或硬编码 6 只核心 ETF：沪深300/上证50/黄金/国债/创业板/科创50）作为兜底。静态池按 `layer` 分发至 core/satellite/defense 三层，后续引擎可正常运作。同时 `get_factor_matrix` 调用包裹在 `try/except` 中，失败时 `factor_matrix = {}` 而非抛错。 |
| | | | | **新增单测：** `tests/test_system_diagnosis_fixes.py` 扩至 **36 用例全 PASS**：新增 Z01×1、Z03×1、Z04×4（industry_diversification/premium_discount/tracking_error/shares_change）、Z10×3（high_moderate_edge）、Z11×1（fallback graceful）。 |
| | | | | **改动文件：** `backend/app/routers/admin.py`（Z01）、`backend/app/routers/factors.py`（Z03）、`backend/app/factors/factor_registry.py`（Z04）、`backend/app/analysis/signal.py`（Z10）、`backend/app/services/strategy_design.py`（Z11）、`backend/app/fetchers/global_markets_fetcher.py`（Z02 名称冲突修复）、`backend/app/services/market_service.py`（Z02 _route_us 更新）、`backend/tests/test_design_cascade_failure.py`（Z11 兜底适配）、`backend/tests/test_system_diagnosis_fixes.py`（测试扩至 36 用例）、`docs/implementation-master-plan.md`（本版本更新） | |
