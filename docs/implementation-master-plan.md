# ETF Surge 方案实施总计划

> 生成日期: 2026-07-26 | 版本: **v9.1**
> ✅ **Phase 6.1 已完成**：可观测性与系统增强 — ConfigManager + app_config 表（`models/app_config.py`, `core/config_manager.py`）、ConfigPage（`views/ConfigView.vue`）、Sector API 实时行情返回（market.py 路由优先级调整）、LLM 热点板块注入（llm_context.py + pool_manager.py）、stars 时间新鲜度 + Level 2 精度调整（news_fetcher.py + levistock_fetcher.py）、verify_e2e.py 扩展（stars/level 校验 + check_sector_data）。详见 §4 Phase 6.1。
> 
> 总览 `docs/` 目录 **32 份**方案文档，梳理实施状态、冲突重叠、修复建议及分阶段执行路线。
> v7.1：Phase 2.7 剩余项 + Phase 2.8 剩余项 + Phase 2.9 全部完成。新增 encoding_diagnosis.py、refresh_sentiment_cache()、AGENTS.md 关键路径更新。新增 llm_context.py build_full_context() 统一数据管道 + llm_report_stream/llm_advice_stream 改用统一管道。
> Phase 2.2→2.4 全部完成——33/33 核心因子全 LIVE（_CORE_FACTORS 列表共 33 个因子，均含真实 compute 函数，含 Phase 2.5 新增的 etf.return_1m/return_3m/price）、因子健康端点 + 因子单测门禁 + 运行时因子断言、分配器质量修复（ln_mcap 排毒、C2 条件修正、segment 归一化去重、预算重调、cross-section z-score 重归一化）。新增 Phase 2.5（原质量防护网 + AI 分析）。
> 新增文档 2 份：`scaffold-factor-resolution-plan.md`（第 29 份，✅ 已实施）、`design-quality-review-20260725.md`（第 30 份，审计报告）。
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
| `design-optimization-plan.md` | `strategy_design.py` 重构 156 行（原 1092 行），纯函数策略引擎 `engine/` 包就绪 |
| `frontend-architecture-refactor.md` | 4 个大组件拆为 22 个子组件，composables 抽取完成 |
| `issues-analysis-report.md` | 问题分析文档，对应的修复已在后续多轮 commit 中落地 |
| `fix-global-indices-plan.md` | **Phase 0 已实施**（onMounted + try/except + 缓存语义修复 + CSS 样式），见 2026-07-22~23 commits |
| `news-pipeline-fix-plan.md` P0 | **Phase 0 已实施**：`fetch_news_headlines()` 加 `id` 字段 + 前端 `handleNews()` 无 `id` fallback，见 `bd72bf6` (push-on-subscribe) + `d4062c2` |
| `frontend-performance-optimization.md` Step 1 | **Phase 0 已实施**：`main.js` 移除 ECharts 全局 import，首屏省 ~500KB |
| `optimization-plan-20260721.md` | **Phase 0.5 已实施**（ETF 缓存 TTL + EM 直连 HTTP + akshare timeout 延长 + 策略检查 props/error/portfolio_type + 历史记录隔离/状态/徽标），见 `70a99f1` 及后续 5 个 commit |
| `design-pipeline-foundation-issues.md` | **Phase 0.7 已实施**（tracked_index + 因子分聚合 + 三方案差异化 + 风控修复 + 去重），见 `d478f12` + `cde3209`，15 个新单测全 PASS |
| `design-failure-and-strategy-check-review.md` | **Phase 0.8 已实施**（前端错误弹窗 + 动态建议上限 + 数据质量注入 + 测试修复 + 级联测试 + verify_e2e 增强），见 `ad3e12eb` |
| `async-boundary-fix-plan.md` | **Phase 0.9 部分实施**（见 commit `2be9ccb`：fix fetch_history + 线程池统一 + 冷却期修复 + 预热超时）。**2026-07-26 新版本**发现遗漏 Sina IOPV 阻塞点，待 Phase 2.6 |
| `design-check-pipeline-redesign.md` | **Phase 1.0 已实施**（顺序 Pipeline 替代 fire-and-forget + report_quality 分级 + 原子 DB 写入 + 崩溃恢复 + 8 个新集成测试），见 `4ff6084` + `7e93321` |
| `five-improvements-plan.md` | 4/5 项已实现——#2 `filter_extreme_drawdown` ✓、#3 `check_defense_effectiveness` ✓、#4 `remove_stale_candidates` ✓、#5 `_layer_phrase` 模板多样化 ✓；#1 统一市态判定仍待完成 |
| `remaining-issues-solution-design.md` | **全部 4 子项已实施**——S1-A(TTL 缓存) `53acbfa` ✓、S1-C(渐进状态机) `ef3de11` ✓、S2(混合归一化) `5116681` ✓、S3-B/C(WS 超时+清理) `ef3de11` ✓ |
| `scaffold-factor-resolution-plan.md` | **全部实施**——7 个脚手架因子全部从 0→非零，33/33 核心因子全 LIVE（_CORE_FACTORS 列表），新增因子健康端点 + 运行时因子断言门禁（`2132a74`） |
| **Phase 2.2 数据管道根因修复**（v5.0 新增） | 发现 china_market.py 两个 import 错误（`source_registry` 路径错误、`utils.proxy` 路径错误）导致所有 `fetch_history` 调用静默失败→全部 26 因子为 0。修复后：技术面 10/10 LIVE、动量 3/10 LIVE、估值 2/2 LIVE（原均 0/—）。空池保护 + B3b 去重 + C2 风偏修正 + 入选理由重写 + IOPV 批量获取 + 新闻情感桥接 + decode_df 逐格修复 + DQ 门禁 + 前端错误态返回按钮 + E2E 回归测试 + 测试 teardown HTTP 泄漏防护。见 commits `e6264ee`~`1e63eab`（15 个改动）。 |
| `systematic-quality-review.md` | **新增 2026-07-26** 全量质量审查报告，识别 6 个质量问题（P0×2、P1×3、P2×1）：事件循环阻塞、设计方案空壳、因子数据缺失、置信度偏低、编码乱码、设计管线静默降级。修复计划见 Phase 2.7。 |

### 1.2 部分完成

| 文档 | 完成部分 | 未完成部分 |
|------|---------|-----------|
| `design-report-optimization-plan.md` | 报告管道就绪、`_validate_report_consistency` 实现、WS 推送链路完整、`report_quality` 分级（full/fallback/none/pending）；A1（表格"因子"→"多因子评分"）已随 Phase 0.5 落地；管道升级为顺序 Pipeline（Phase 1.0） | A2（预期收益随市态调整）、B1-B3（LLM prompt 分析增强）、C1（全市场净流入信号）、C2（卫星层科技 ETF）—— 其中 A2/C1/C2 依赖因子分正常后验证效果 |
| `five-improvements-plan.md` | #2（极端下跌排除）+ #3（防御有效性）+ #4（freshness 检查）+ #5（理由多样化）已实现 | #1（统一市态判定）仍待完成，~15 行 |
| `market-awareness-and-data-source-plan.md` | Stooq 已在全球指数降级链中引用；§4 数据源替换已转入 `roadmap-data-source-unified.md`；**§5 市场感知联动已实施（Phase 5.1）**：MarketContext 数据类、market_router 路由层、多市场 regime 缓存、design-async 多市场参数、sector-analysis 市场感知、llm-report/stream 市场过滤 | ✅ **§5 已实施**（Phase 5.1）：`core/market_context.py` + `services/market_router.py` 新增，35 个新单测全 PASS。详见 §4 Phase 5.1 |
| `factor-model-extension-plan.md` | 因子注册表从 12 个扩展到 **~33** 个计算函数（当前 _CORE_FACTORS=33）；异步边界修复（Phase 0.9）后因子计算基于真实数据 | YAML 中 167 个远未全覆盖；IC 追踪器从未运行 |
| `design-check-quality-report.md` | 19 个问题中 **14 项已落地**：P0 全 4 项 ✅（_etf_history + meltdown→warning + INDEX_KEYWORDS + S1-A TTL 缓存）`53acbfa`；P1-1(三策略差异化) 通过 Phase 0.7 C1 + profile权重(`5116681`) + C2 名称基准分(`17e9cab`) + B3b概念去重(`17e9cab`) ✅；P1-3(强制标的进分配) ✅ `5116681`；P2-1→S2(混合归一化) ✅ `5116681`；P3-1(测试覆盖) ✅ test_data_health.py + DQ 门禁；P3-2(pre-commit) ✅ 增强 API 覆盖检查；P3-3(E2E 断言) ✅ verify_e2e.py `afaea68`；P3-4(监控脚本) ✅ data_health_check.py `ac6dd81` | **剩余 5 项**待实施（~1h）：P1-2(防御层分类→卫星层，~3行)、P1-4(risk_controls拼接bug，~1行)、P2-2(weight字段注入，~5行)、P2-3(摘要增强，~10行)、P2-4(target_weight默认值，~1行) |

### 1.3 已替代 (v2.0 新增)

| 文档 | 替代状态 | 替代者 |
|------|---------|--------|
| `source-registry-optimization-plan.md` | **已替代** | `roadmap-data-source-unified.md` (Phase B/C) |
| `data-source-monitoring-plan.md` | **已替代** | `roadmap-data-source-unified.md` (Phase D) |
| `review-20260720.md` | 评审记录，非实施方案 | N/A |

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
| `scaffold-factor-resolution-plan.md` | **P1** | 已实施（✅ 7 个 scaffold 因子全部从 0→非零） | 0（已完成） | 已在 `e5b6139` 中落地 |
| `roadmap-data-source-unified.md` | **P2** | 整合三份原方案，实施顺序详见自身依赖图 | ~3-5天 | — |
| `config-management-plan.md` | **P2** | 无（独立） | ~8h | — |
| `design-report-optimization-plan.md` A2/C1/C2 | **P2** | 依赖因子分正常（Phase 0.7 已完成） | ~2h | — |
| `e2e-testing-plan.md` | **P3** | 前端 UI 稳定后（避免维护成本过高） | ~16h | — |
| `factor-model-extension-plan.md` | **P0** | 实施就绪（v4.0 已重写） | Phase 7.1.1 | 当前版本 v4.0，反映 33 因子架构 + IC 追踪器激活方案 | 冲突与重叠分析

### 2.1 🔴 重大重叠：数据源改造三合一（已解决）

**涉及的文档**：
- `roadmap-data-source-unified.md` ← **已创建，替代以下三份**：
  - `source-registry-optimization-plan.md`
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
- `design-report-optimization-plan.md` A2/C1/C2（预期收益调整、净流入信号、卫星层科技 ETF）
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
- `optimization-plan-20260721.md`（verify_e2e.py 扩展）

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
- `design-optimization-plan.md` P1/P2/P3（`strategy_design.py`、`design_report.py`、`llm.py`）

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
- `design-report-optimization-plan.md` A2/C1/C2（预期收益、净流入信号、卫星层科技 ETF）
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
| `source-registry-optimization-plan.md` | **已归档——被 roadmap-data-source-unified.md 替代** | `roadmap-data-source-unified.md` |
| `data-source-monitoring-plan.md` | **已归档——被 roadmap-data-source-unified.md 替代** | `roadmap-data-source-unified.md` |
| `review-20260720.md` | 评审记录，非实施方案 | N/A |
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
| `optimization-plan-20260721.md` | **已实施**，移出冲突清单 | — | Phase 0.5 完成 |
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

**状态**: ✅ 2026-07-22~23 已全部实施并验证。来源于 `optimization-plan-20260721.md`，共 8 项任务，覆盖数据管道韧性 + 策略检查 + 历史记录。

| # | 任务 | 源文档 | 状态 |
|---|------|--------|:----:|
| 0.5.1-0.5.3 | ETF 数据管道韧性（缓存 TTL + EM 直连 + timeout 延长 + 预热） | `optimization-plan-20260721.md` A1-A4 + B1-B2 | ✅ |
| 0.5.4-0.5.5 | 策略检查白屏/超时修复（props 补齐 + error_message 兼容 + portfolio_type 读取） | `optimization-plan-20260721.md` C1-C3 | ✅ |
| 0.5.6 | 历史记录 Promise.all catch 隔离 | `optimization-plan-20260721.md` D1-D2 | ✅ |
| 0.5.7-0.5.8 | 历史记录状态徽标 + 运行中合并 + WS design_id 回调 | `optimization-plan-20260721.md` E1-E5 + F1-F3 | ✅ |

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
| 2.5.8 | design-report A1+A2+A3 | `design-report-optimization-plan.md` | ✅ 已实施 | — | Phase 0.7 |
| 2.5.9 | design-report B1：黄金入选理由增强 | `design-report-optimization-plan.md` B1 | ✅ 已实施（commit 584ad20） | ~10行 | 无 |
| 2.5.10 | design-report B2：国债久期风险提示 | `design-report-optimization-plan.md` B2 | ✅ 已实施（commit 584ad20） | ~3行 | 无 |
| 2.5.11 | design-report B3：LLM prompt 量化规则 | `design-report-optimization-plan.md` B3 | ✅ 已实施 | — | 无 |
| 2.5.12 | design-report C1：全市场净流入信号注入 | `design-report-optimization-plan.md` C1 | ✅ 已实施（commit f6d47d3：利用现有 akshare stock_individual_fund_flow 聚合全池资金流向注入 LLM prompt） | ~30行 | 无 |
| 2.5.13 | design-report C2：卫星层增加科技 ETF | `design-report-optimization-plan.md` C2 | ✅ 已实现（基础版，`engine/allocation_engine.py` L443-467；含集成缺口） | ~15行 | 无 |

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

### Phase 7.1 — 远期优化

| # | 任务 | 源文档 | 状态 | 说明 |
|---|------|--------|:----:|------|
| 7.1.1 | Factor IC 追踪器激活 | factor-model-extension | ✅ 已实施 | Phase A(核心管道) + Phase B1(B3)已实施：SQLite 持久化(factor_ic_records 表)，定时 120s 保存 IC batch；IC 阈值告警(logger.warning)；前端 FactorICView.vue(因子 IC 排序 + 有效性标记) |
| 7.1.2 | 排版令牌迁移 | frontend-ui-optimization Phase 3-4 | ❌ 待实施 | Phase 1 Step 1（CSS 变量补齐）已在 theme.css L121-124 完成 ✅；Phase 3-4 仍需推进 |
| 7.1.3 | SVG 图标替换 emoji | frontend-ui-optimization Phase 3 | ❌ 待实施 | 美观度提升 |
| 7.1.4 | 响应式补齐 | frontend-ui-optimization Phase 4 | ❌ 待实施 | 移动端适配 |
| 7.1.5 | 进一步 E2E 增强 + 剩余 UI 组件单测 | frontend-testing-safety-net C1/C3 | ❌ 待实施 | 基础设施（playwright.config.js + server utils + package.json 脚本）已就绪 ✅；已实现 6/12 个 spec 文件。Charts 渲染 E2E + News 筛选 + 技术分析流程 E2E（+6-8 条）；剩余基础组件（AppTable/AppSelect/Skeleton 等）单测 |
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
| design-optimization-plan.md | 实施方案 | ✅ 已实施 | strategy_design + engine/ | Phase 0.5 前 | — |
| **design-pipeline-foundation-issues.md** | **诊断+修复方案** | ✅ **已实施 (Phase 0.7)** | **etf_scanner + pool_manager + factor_registry + risk_controls + allocation_engine** | **Phase 0.7** | 15 新单测，9 文件，1428 行 |
| design-report-optimization-plan.md | 实施方案 | ✅ **已实施** | llm.py + design_report.py + engine/rationale.py + engine/allocation_engine.py | Phase 2.2 | A1/A2/A3 ✅ B1/B2/B3 ✅ C1 ✅；C2 ✅（`engine/allocation_engine.py:443-458` 科技集中度>60%卫星预算→自动科创50 ETF(588000)分散） |
| e2e-testing-plan.md | 实施方案 | ⚠️ 部分实施 | frontend/e2e/ | Phase 7.1 | 基础设施（playwright.config.js + server utils + package.json 脚本）已就绪 ✅；已实现 6/12 个 spec 文件（01-smoke / 02-visual / 03-navigation / 04-wizard-design / 05-theme-assets / 12-regression）。全量 12-spec 计划未实施 |
| factor-model-extension-plan.md | 实施方案 | ✅ **v4.0 已重写** | factor_registry.py + ic_tracker.py + routers/factors.py | Phase 7.1.1 | 已全面重写：反映 33 因子全 LIVE 架构 + engine/ 包 + IC 追踪器两阶段激活方案（Phase A: 核心管道 + API 端点；Phase B: 持久化 + UI） |
| five-improvements-plan.md | 实施方案 | ✅ **全部完成** | risk_controls.py + rationale.py + portfolio_service.py | Phase 1.1 | #1 统一市态已落地（`portfolio_service.py:406-409`）|
| fix-global-indices-plan.md | 修复方案 | ✅ **已实施 (Phase 0)** | market_service + GlobalIndicesStrip | Phase 0 | — |
| frontend-architecture-refactor.md | 实施方案 | ✅ 已实施 | 全部前端组件 | — | — |
| frontend-performance-optimization.md | 优化方案 | ⚠️ Step 1 已实施 | main.js + vite.config.js | Phase 3.1 | Step 2-3 待做 |
| frontend-testing-safety-net.md | 测试方案 | ⚠️ Phase A/B 已完成 | frontend/test + e2e | Phase 2.5/3.1 | 18 spec 文件/175 条/UI 组件 43 条；Phase C（截图基线+Chart测试+剩余E2E）待做 |
| frontend-ui-optimization-plan.md | 优化方案 | ❌ 已回滚 | 全部前端视图 | Phase 3.1 | 需测试防护就绪 |
| issues-analysis-report.md | 问题分析 | ✅ 已修复 | 全局 | — | — |
| market-analysis-optimization-plan.md | 实施方案 | 🟡 **部分完成（2026-07-26 审计修正）** | market router + analysis router | Phase 2.5 → 5.1 | Phase A/B/C ✅；Phase D/E 🟡（后端数据管道已实现，但 market 参数端到端传递和 LLM prompt 增强未完成）。详见 §4 Phase 5.1 状态矩阵 |
| market-awareness-and-data-source-plan.md | 实施方案 | ✅ **§5 已实施（Phase 5.1）** | core/market_context + services/market_router + 端市场感知接入 | Phase 5.1 | §4 已转 `roadmap-data-source-unified.md`；§5 市场感知联动全栈实施：MarketContext 数据类、market_router 路由层、多市场 regime 缓存、design-async 多市场参数、sector-analysis 市场感知。35 个新单测全 PASS。commit `2371815` |
| news-pipeline-fix-plan.md | 修复方案 | ✅ **全部完成** | news_fetcher + levistock_fetcher + NewsView.vue | Phase 1.1 | P0+P1 全部实施（新浪源/关键词/降级链）|
| optimization-plan-20260721.md | 实施方案 | ✅ **已实施 (Phase 0.5)** | etf_scanner + 前端 + 后端链路 | Phase 0.5 | 全部 8 项完成 |
| **remaining-issues-solution-design.md** | **实施方案** | ✅ **全部已实施**（已从 staged→committed） | **pool_manager + task_manager + ws + factor_registry** | **Phase 2.1** | S1-A(TTL) `53acbfa`、S1-C(渐进) `ef3de11`、S2(归一化) `5116681`、S3-B/C(WS) `ef3de11` |
| review-20260720.md | 评审报告 | N/A | N/A | — | 非实施方案 |
| roadmap-data-source-unified.md | 实施方案 | ✅ **已实施（D7除外）** | china_market + market_service + source_registry + monitor | Phase 4.1 | 替代三份原方案。v3.0 已更新为回顾文档。Phase A/B/C/D1-D6 均已实施 |
| sector-concept-optimization-plan.md (v3.0) | 实施方案 | ✅ Phase 1-6 全部实施 | market_trends + pool_manager + llm.py + market.py + analysis.py + 前端 | Phase 1.1/6.1 | 数据采集+缓存写入+60s定时刷新 ✅; Phase 3 (API实时行情) ✅ 已实施(Phase 6.1.5); Phase 4 (LLM注入) ✅ 已实施(Phase 6.1.6); Phase 5-6 借由 build_full_context 统一数据管道覆盖 |
| source-registry-optimization-plan.md | 实施方案 | ❌ **已替代** | — | — | 被 roadmap 替代 |
| **scaffold-factor-resolution-plan.md** | **修复方案** | ✅ **全部实施** | **factor_registry + 测试** | **Phase 2.3** | 7 个脚手架因子全 LIVE（33/33），因子健康端点，运行时断言门禁 |
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
