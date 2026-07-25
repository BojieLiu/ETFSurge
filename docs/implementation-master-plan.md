# ETF Surge 方案实施总计划

> 生成日期: 2026-07-25 | 版本: v5.0
> 总览 `docs/` 目录 **28 份**方案文档，梳理实施状态、冲突重叠、修复建议及分阶段执行路线。
> v5.0 基于 v4.2 后一轮密集修复（15 个问题，涵盖数据源 import 错误、空池保护、因子聚合、风偏差异化、去重、入选理由、IOPV/NAV 抓取、新闻情感桥接、中文编码等；参见 commits `e6264ee`~`1e63eab`）审计更新。
> Phase 2.2 全部完成——因子数据从全 0 恢复到 15/26 个非零因子（含技术面 10/10 LIVE）、策略区分度、去重、编码修复、DQ 测试门禁。
> 新增未规划项：china_market.py import 修复、空池保护、C2 风偏基准分、B3b 指数概念去重、IOPV 批量抓取、change_pct 因子、新闻情感桥接、单例 teardown HTTP 泄漏防护、DB 编码修复脚本。
> 💡 **关键依赖变化**：Phase 2.x 全部完成，无剩余 Block 项。

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
| `async-boundary-fix-plan.md` | **Phase 0.9 已实施**（事件循环阻塞修复 + 线程池统一 32 worker + 冷却期污染修复 + 启动预热超时 + full_pipeline 45s 超时 + 异步 lint 测试），见 `2be9ccb` |
| `design-check-pipeline-redesign.md` | **Phase 1.0 已实施**（顺序 Pipeline 替代 fire-and-forget + report_quality 分级 + 原子 DB 写入 + 崩溃恢复 + 8 个新集成测试），见 `4ff6084` + `7e93321` |
| `five-improvements-plan.md` | 4/5 项已实现——#2 `filter_extreme_drawdown` ✓、#3 `check_defense_effectiveness` ✓、#4 `remove_stale_candidates` ✓、#5 `_layer_phrase` 模板多样化 ✓；#1 统一市态判定仍待完成 |
| `remaining-issues-solution-design.md` | **全部 4 子项已实施**——S1-A(TTL 缓存) `53acbfa` ✓、S1-C(渐进状态机) `ef3de11` ✓、S2(混合归一化) `5116681` ✓、S3-B/C(WS 超时+清理) `ef3de11` ✓ |
| **Phase 2.2 数据管道根因修复**（v5.0 新增） | 发现 china_market.py 两个 import 错误（`source_registry` 路径错误、`utils.proxy` 路径错误）导致所有 `fetch_history` 调用静默失败→全部 26 因子为 0。修复后：技术面 10/10 LIVE、动量 3/10 LIVE、估值 2/2 LIVE（原均 0/—）。空池保护 + B3b 去重 + C2 风偏修正 + 入选理由重写 + IOPV 批量获取 + 新闻情感桥接 + decode_df 逐格修复 + DQ 门禁 + 前端错误态返回按钮 + E2E 回归测试 + 测试 teardown HTTP 泄漏防护。见 commits `e6264ee`~`1e63eab`（15 个改动）。 |

### 1.2 部分完成

| 文档 | 完成部分 | 未完成部分 |
|------|---------|-----------|
| `design-report-optimization-plan.md` | 报告管道就绪、`_validate_report_consistency` 实现、WS 推送链路完整、`report_quality` 分级（full/fallback/none/pending）；A1（表格"因子"→"多因子评分"）已随 Phase 0.5 落地；管道升级为顺序 Pipeline（Phase 1.0） | A2（预期收益随市态调整）、B1-B3（LLM prompt 分析增强）、C1（全市场净流入信号）、C2（卫星层科技 ETF）—— 其中 A2/C1/C2 依赖因子分正常后验证效果 |
| `five-improvements-plan.md` | #2（极端下跌排除）+ #3（防御有效性）+ #4（freshness 检查）+ #5（理由多样化）已实现 | #1（统一市态判定）仍待完成，~15 行 |
| `market-awareness-and-data-source-plan.md` | Stooq 已在全球指数降级链中引用；§4 数据源替换已转入 `roadmap-data-source-unified.md` | §5 市场感知联动（MarketReport 忽略 `market` prop、AiAdvisor 硬编码、组合设计无 `market` 参数等）—— 此部分与 `market-analysis-optimization-plan.md` Phase D/E 有重叠，**建议以 market-analysis 方案为准实施** |
| `factor-model-extension-plan.md` | 因子注册表从 12 个扩展到 ~30 个计算函数；异步边界修复（Phase 0.9）后因子计算基于真实数据 | YAML 中 167 个远未全覆盖；IC 追踪器从未运行 |
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
| `design-check-quality-report.md` 剩余 P1-P3 | **P1** | 14/19 项已落地；Phase 0.7+ 全部就绪 | ~1h | 剩余 5 小项（~20行），参见 §4 Phase 1.1 后期 |
| `news-pipeline-fix-plan.md` P1 | **P1** | 依赖 P0 已实施（Phase 0 完成） | ~2h | — |
| `sector-concept-optimization-plan.md` | **P1** | Phase 1-2 独立可先行；Phase 4 依赖 LLM prompt 合并 | ~8h | — |
| `market-analysis-optimization-plan.md` | **P1** | Phase A-C 须按序；D/E 独立；Phase 0.7/0.9 已就绪 | ~13-19h | — |
| `frontend-ui-optimization-plan.md` | **P1** | 曾实现后回滚，需测试安全网就绪后重做 | ~8h | — |
| `frontend-testing-safety-net.md` | **P1** | 前端架构重构已就绪 | ~11h | — |
| `frontend-performance-optimization.md` (Step 2-3) | **P1** | Step 1 已实施（Phase 0）；Step 2-3 待做 | ~1.5h | — |
| `five-improvements-plan.md` #1 | **P1** | 独立，~15 行 | ~15min | — |
| `roadmap-data-source-unified.md` | **P2** | 整合三份原方案，实施顺序详见自身依赖图 | ~3-5天 | — |
| `market-awareness-and-data-source-plan.md` §5 | **P2** | **建议以 market-analysis Phase D/E 替代** | — | — |
| `config-management-plan.md` | **P2** | 无（独立） | ~8h | — |
| `design-report-optimization-plan.md` A2/C1/C2 | **P2** | 依赖因子分正常（Phase 0.7 已完成） | ~2h | — |
| `e2e-testing-plan.md` | **P3** | 前端 UI 稳定后（避免维护成本过高） | ~16h | — |
| `factor-model-extension-plan.md` | **P3** | 远期优化 | — | — |

---

## 2. 冲突与重叠分析

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

**修复建议 → 以 market-analysis Phase D 为准**：
- `market-analysis-optimization-plan.md` Phase D 有完整可执行的代码（`_build_advice_stream_prompt`、池管理器注入、market 参数）
- market-awareness §5 中的 MarketContext 路由层**暂缓**，等 market-analysis Phase D+E 落地后评估是否需要额外路由层
- 在 `implementation-master-plan.md` 中将 market-awareness §5 从 Phase 5 降级为 **Phase 5 (可选)**

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
Phase 1: five-improvements #1 + design-report A2/C1/C2 验证效果
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

### 3.2 冲突修复：市场分析方案领先于市场感知方案

**决策**：以 `market-analysis-optimization-plan.md` Phase D 和 Phase E 的代码级方案为准，
替代 `market-awareness-and-data-source-plan.md` §5 的大部分内容。

**处理方式**：
- `market-analysis-optimization-plan.md` → **保留，优先实施**
- `market-awareness-and-data-source-plan.md` §5 → **降级**，标记为"待 market-analysis 落地后评估"

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
├── P1-1~P1-4 (差异化 + 分类 + 强制标的 + 拼接 bug) → ✅ P1-1(已随C1+profile权重+C2实现) + P1-3(强制标的)已实施；❌ P1-2(分类) + P1-4(拼接) → Phase 1.1 后期
├── P2-1~P2-4 (混合归一化 + weight + 摘要 + target_weight) → ✅ P2-1(S2)已实施；❌ P2-2~P2-4 → Phase 1.1 后期
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

### Phase 0.9 — 异步边界修复与线程池统一 ✅ 已完成

**来源**: `async-boundary-fix-plan.md`

**状态**: ✅ 2026-07-24 已全部实施并验证。6 个 Phase + 10 个文件改动。

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

### Phase 1.1 — 数据层增强 & 统一市态（P1）

**前置依赖**: Phase 0.7~1.0 完成（因子分正常 + 管道可靠 + 异步边界修复 + 报告分级）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 1.1.0 | Five-improvements #1：统一市态判定（策略检查复用 pool_manager） | `five-improvements-plan.md` #1 | ~15min | 无（独立） |
| 1.1.1 | Sector 数据采集扩容（行业+概念 concurrent；复用 Phase 0.7 A3 的缓存写入入口） | sector-concept Phase 1 | 4h | Phase 0.7 A3 |
| 1.1.2 | PoolManager sector_cache 写入扩展（基于 A3 已有入口） | sector-concept Phase 2 | 3h | 1.1.1 |
| 1.1.3 | APScheduler 新增 60s 板块刷新任务 | sector-concept Phase 2 | 1h | 1.1.2 |
| 1.1.4 | 新闻关键词分类修复（移中性词、清冲突词） | news-pipeline-fix P1.1+P1.2 | 0.5h | 无 |
| 1.1.5 | 新增 `fetch_sina_roll_news()` HTTP 源 | news-pipeline-fix P1.3 | 1h | 无 |
| 1.1.6 | 重写 `fetch_macro_news()` 降级链（新浪优先） | news-pipeline-fix P1.4 | 0.5h | 1.1.5 |
| 1.1.7 | 重写 `fetch_global_news()` 降级链 | news-pipeline-fix P1.5 | 0.5h | 无 |
| 1.1.8 | market-analysis Phase A（统一搜索后端） | market-analysis §3 | 3-4h | 无 |
| 1.1.9 | market-analysis Phase B（统一分析编排端点） | market-analysis §4 | 1-2h | 无（与 1.1.8 可并行） |
| 1.1.10 | P1-2: 防御层分类修复（跨境→卫星层） | design-check-quality §3 P1-2 | ~3行 | 无 |
| 1.1.11 | P1-4: risk_controls.py 拼接 bug 修复 | design-check-quality §3 P1-4 | ~1行 | 无 |
| 1.1.12 | P2-2: holdings_analysis 注入 weight 字段 | design-check-quality §3 P2-2 | ~5行 | 无 |
| 1.1.13 | P2-3: 策略检查摘要增强 | design-check-quality §3 P2-3 | ~10行 | 无 |
| 1.1.14 | P2-4: target_weight 默认值 0.0 修复 | design-check-quality §3 P2-4 | ~1行 | 无 |

**验证**:
- LLM 报告不再显示"暂无板块热力数据"
- 新闻源日志含 `[news] 新浪财经返回 N 条`，`fetch_macro_news` 改动前 ≤24s → 改动后 ~0.3s
- `GET /market/search?keyword=茅台&market=A` 返回 `type:"stock"` 结果
- 策略检查的 regime 与设计方案一致（统一市态判定）
- 防御层黄金/国债分类正确（非跨境→卫星层误归）
- risk_controls 拼接 no error；holdings_analysis 含 weight 字段；strategy check 摘要内容充实；target_weight 默认为 0

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

### Phase 2.2 — 数据管道根因修复与测试门禁 ✅ **全部完成（v5.0 新增）**

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

### Phase 2.3 — 质量防护网 + AI 分析增强 + 设计报告增强

**前置依赖**: Phase 0.7~1.0 完成；Phase 2.1 ✅ + Phase 2.2 ✅ 全部完成

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 2.2.1 | AppButton/AppCard/AppTabs/AppInput/AppModal 单测 | frontend-testing-safety-net Phase A | 4h | 无 |
| 2.2.2 | useDashboardData composable 单测 | frontend-testing-safety-net Phase B | 1h | 无 |
| 2.2.3 | E2E spec 扩充到 10-15 条 | frontend-testing-safety-net Phase B/C | 6h | 无 |
| 2.2.4 | verify_e2e.py 全局指数检查修复 | fix-global-indices-plan 根因 #7 | 0.5h | 无 |
| 2.2.5 | market-analysis Phase C（前端 UnifiedAnalysis 合并组件） | market-analysis §5 | 4-5h | Phase 1.1.8+1.1.9 (A+B) |
| 2.2.6 | market-analysis Phase D（AI 顾问流式+数据管道） | market-analysis §6 | 2-3h | 无（可并行） |
| 2.2.7 | market-analysis Phase E（市场报告质量提升） | market-analysis §7 | 2-3h | 无（可并行） |
| 2.2.8 | design-report A2：预期收益随市态动态调整 | `design-report-optimization-plan.md` A2 | ~20行 | Phase 0.7 B1（因子分正常） |
| 2.2.9 | design-report C1：全市场净流入信号注入 LLM 报告 | `design-report-optimization-plan.md` C1 | ~30行 | Phase 0.7 验证通过 |
| 2.2.10 | design-report C2：卫星层增加科技 ETF 选项 | `design-report-optimization-plan.md` C2 | ~15行 | Phase 0.7 验证通过 |

**验证**:
- `npm test` 全绿 + `npm run test:e2e:smoke` 全绿
- 市场分析页面由 6 卡片降为 4 卡片，所有分析功能正常
- AI 顾问流式渲染，返回有实质数据的回答
- 市场研判报告含「综合研判结论」+「操作建议」
- 设计方案预期收益根据市态动态调整（非硬编码）
- 卫星层包含宽基科技 ETF 选项（科创50/创业板）

### Phase 3.1 — 前端 UI 重构（重新实施，防回滚）

**前置依赖**: Phase 2.2 测试防护就绪（避免 UI 回滚重演）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 3.1.1 | Dashboard 手工 card → AppCard（7 区块） | frontend-ui-optimization Phase 2 | 4h | 2.2.1 (AppCard 单测) |
| 3.1.2 | Dashboard 手工 tab → AppTabs | frontend-ui-optimization Phase 2 | 1h | 2.2.1 (AppTabs 单测) |
| 3.1.3 | PortfolioAnalysis tab → AppTabs | frontend-ui-optimization Phase 2 | 1h | 同上 |
| 3.1.4 | TokenMonitor / MarketAnalysis / DesignResult tab → AppTabs | frontend-ui-optimization Phase 2 | 2h | 同上 |
| 3.1.5 | Vite chunk 优化（vendor-vue/axios/echarts 分层） | frontend-performance Step 2 | 0.5h | 无 |
| 3.1.6 | 各页面 ECharts 清理重复注册 | frontend-performance Step 3 | 1h | 0.4 |

**验证**: 逐页面视觉验证 + `npm test` 全绿 + `npm run build` 确认 chunk 拆分

### Phase 4.1 — 数据源系统改造（大方案，独立轨道）

此阶段完全对应 `roadmap-data-source-unified.md` 的四个子阶段。详见该文档 §依赖关系与推荐顺序。

| # | 任务 | 源阶段 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 4.1.1 | 美股 `_route_us_stooq()` 新链路（Stooq→TwelveData→Finnhub） | roadmap Phase A | 2h | 无 |
| 4.1.2 | 全球指数链路统一 + TwelveData/Finnhub 加入 | roadmap Phase A (A4) | 2h | 无 |
| 4.1.3 | China market 3 核心函数接入 SourceRegistry | roadmap Phase B | 3h | 无 |
| 4.1.4 | price=0 过滤前置修复 | roadmap Phase B | 1h | 无 |
| 4.1.5 | 补齐 7 个健康探针（新建 `monitor/probes.py`） | roadmap Phase C | 2h | 无 |
| 4.1.6 | SourceRegistry 加 on_event 回调 | roadmap Phase D (D2-D4) | 1h | 无 |

**并行策略**:
- **Track 1**: 4.1.1 + 4.1.2 + 4.1.3 可并行（不同文件，互不冲突）
- **Track 2**: 4.1.5 独立（仅修改 main.py + 新建 probes.py）
- **Track 3**: 4.1.6 是串行瓶颈，须最后做

**验证**: verify_e2e.py + 长稳运行观察降级是否正常工作

### Phase 5.1 — 市场感知联动（可选，待评估）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 | 备注 |
|---|------|--------|---------|---------|------|
| 5.1.1 | 后端 MarketContext 路由层 | market-awareness §5.2 | 6h | 4.1.1-4.1.3 | ⚠️ 若 market-analysis Phase D+E 已满足需求，此任务可取消 |
| 5.1.2 | MarketReport market prop 传递 | market-awareness §5.3 | 2h | 5.1.1 | 已在 market-analysis Phase E 中部分实现 |
| 5.1.3 | AiAdvisor market 上下文 | market-awareness §5.3 | 2h | 5.1.1 | 已在 market-analysis Phase D 中实现 |
| 5.1.4 | 组合设计 market 参数 | market-awareness §5.3 | 2h | 5.1.1 | — |
| 5.1.5 | LLM prompt 市场上下文注入 | market-awareness §5.4 | 2h | 5.1.1 | — |

**验证**: 切换到美股 Tab → 所有功能使用美股数据

### Phase 6.1 — 可观测性与系统增强

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 6.1.1 | SourceEventStore（source_events 表 + API） | roadmap Phase D (D1+D6+D7) | 6h | 4.1.6 |
| 6.1.2 | 前端数据源监控页面 | roadmap Phase D7 | 4h | 6.1.1 |
| 6.1.3 | ConfigManager + app_config 表 | config-management §4.1-4.3 | 4h | 无 |
| 6.1.4 | 前端 ConfigPage | config-management §5 | 4h | 6.1.3 |
| 6.1.5 | Sector API 实时行情返回 | sector-concept Phase 3 | 3h | 1.1.1 |
| 6.1.6 | LLM prompt 热点板块注入 | sector-concept Phase 4 | 2h | 1.1.2 + 1.1.3 |
| 6.1.7 | `stars` 引入时间新鲜度 + 新闻 Level 2 精度调整 | news-pipeline-fix P2 | 1h | 无 |
| 6.1.8 | `news_fetcher` 单独验证脚本更新 verify_e2e.py | news-pipeline-fix §8 | 0.5h | 0.6+0.7 |

**验证**: 数据源状态页可查 + 配置页读写正常 + 板块数据实时行情带涨跌颜色

### Phase 7.1 — 远期优化

| # | 任务 | 源文档 | 说明 |
|---|------|--------|------|
| 7.1.1 | Factor IC 追踪器激活 | factor-model-extension | 评估是否需要更多因子，不急于实施 |
| 7.1.2 | 排版令牌迁移 | frontend-ui-optimization Phase 3-4 | 视觉效果深化 |
| 7.1.3 | SVG 图标替换 emoji | frontend-ui-optimization Phase 3 | 美观度提升 |
| 7.1.4 | 响应式补齐 | frontend-ui-optimization Phase 4 | 移动端适配 |
| 7.1.5 | Playwright E2E 全覆盖 | e2e-testing-plan | 12 个 spec 文件全覆盖 |
| 7.1.6 | design-report B1-B3（LLM prompt 分析增强） | design-report-optimization B1-B3 | LLM prompt 深层分析增强 |

---

## 5. 附录：各方案摘要

### 5.1 文档状态速查表（v4.2 更新）

| 文档 | 类型 | 状态 | 影响模块 | 关键阶段 | 备注 |
|------|------|------|---------|:--------:|------|
| async-boundary-fix-plan.md | 修复方案 | ✅ **已实施 (Phase 0.9)** | factor_registry + async_utils + pool_manager + main.py | Phase 0.9 | 6 个 Phase，10 文件，493 行 |
| config-management-plan.md | 实施方案 | ❌ 未实施 | 后端 admin + 前端 ConfigPage | Phase 6.1 | — |
| data-source-monitoring-plan.md | 实施方案 | ❌ **已替代** | — | — | 被 `roadmap-data-source-unified.md` 替代 |
| **design-check-pipeline-redesign.md** | **重构方案** | ✅ **已实施 (Phase 1.0)** | **task_manager + design_pipeline + DB + 前端** | **Phase 1.0** | 12 文件，588 行，8 新集成测试 |
| design-check-quality-report.md | 质量审计 | ✅ **14/19 已实施**，⚠️ 5 项待做 | 全链路 | Phase 1.1/2.1 | 14 项已落地（含 S1-A + S2 + P3-2~P3-4 + 新增未规划 DQ 门禁） |
| design-failure-and-strategy-check-review.md | 修复方案 | ✅ **已实施 (Phase 0.8)** | 前端 + portfolio_service + llm + tests | Phase 0.8 | 10 文件，252 行 |
| design-optimization-plan.md | 实施方案 | ✅ 已实施 | strategy_design + engine/ | Phase 0.5 前 | — |
| **design-pipeline-foundation-issues.md** | **诊断+修复方案** | ✅ **已实施 (Phase 0.7)** | **etf_scanner + pool_manager + factor_registry + risk_controls + allocation_engine** | **Phase 0.7** | 15 新单测，9 文件，1428 行 |
| design-report-optimization-plan.md | 实施方案 | ⚠️ 部分 | llm.py + design_report.py | Phase 2.2 | A2/C1/C2 未完成 |
| e2e-testing-plan.md | 实施方案 | ❌ 未实施 | frontend/e2e/ spec 文件 | Phase 7.1 | 建议推迟 |
| factor-model-extension-plan.md | 实施方案 | ⚠️ 部分 | factor_registry.py | Phase 7.1 | 远期优化 |
| five-improvements-plan.md | 实施方案 | ⚠️ 4/5 已实施 | risk_controls.py + rationale.py | Phase 1.1 | #1 待完成（~15min）|
| fix-global-indices-plan.md | 修复方案 | ✅ **已实施 (Phase 0)** | market_service + GlobalIndicesStrip | Phase 0 | — |
| frontend-architecture-refactor.md | 实施方案 | ✅ 已实施 | 全部前端组件 | — | — |
| frontend-performance-optimization.md | 优化方案 | ⚠️ Step 1 已实施 | main.js + vite.config.js | Phase 3.1 | Step 2-3 待做 |
| frontend-testing-safety-net.md | 测试方案 | ❌ 未实施 | frontend/test + e2e | Phase 2.2 | — |
| frontend-ui-optimization-plan.md | 优化方案 | ❌ 已回滚 | 全部前端视图 | Phase 3.1 | 需测试防护就绪 |
| issues-analysis-report.md | 问题分析 | ✅ 已修复 | 全局 | — | — |
| market-analysis-optimization-plan.md | 实施方案 | ❌ 未实施 | analysis router + llm.py + MarketAnalysis.vue | Phase 1.1~2.2 | — |
| market-awareness-and-data-source-plan.md | 实施方案 | ❌ 未实施 | 路由 + Service + LLM | Phase 5.1 | §4 已转 roadmap；§5 待评估 |
| news-pipeline-fix-plan.md | 修复方案 | ✅ P0 已实施；⚠️ P1 待做 | news_fetcher + NewsView.vue | Phase 1.1 | P0 ✅ Phase 0 |
| optimization-plan-20260721.md | 实施方案 | ✅ **已实施 (Phase 0.5)** | etf_scanner + 前端 + 后端链路 | Phase 0.5 | 全部 8 项完成 |
| **remaining-issues-solution-design.md** | **实施方案** | ✅ **全部已实施**（已从 staged→committed） | **pool_manager + task_manager + ws + factor_registry** | **Phase 2.1** | S1-A(TTL) `53acbfa`、S1-C(渐进) `ef3de11`、S2(归一化) `5116681`、S3-B/C(WS) `ef3de11` |
| review-20260720.md | 评审报告 | N/A | N/A | — | 非实施方案 |
| roadmap-data-source-unified.md | 实施方案 | ❌ 未实施 | china_market + market_service + source_registry | Phase 4.1 | 替代三份原方案 |
| sector-concept-optimization-plan.md | 实施方案 | ❌ 未实施 | market_trends + pool_manager + llm.py | Phase 1.1/6.1 | — |
| source-registry-optimization-plan.md | 实施方案 | ❌ **已替代** | — | — | 被 roadmap 替代 |

### 5.2 冲突汇总（v4.0 更新）

| 冲突 | 涉及文档 | 重要性 | 解决方式 | 状态 |
|------|---------|--------|---------|:----:|
| 数据源改造三文档抢同一代码域 | source-registry + data-source-monitoring + market-awareness §4 | 🔴 | 合并为 `roadmap-data-source-unified.md` | ✅ 已解决 |
| foundation-issues 与存量文档改同一代码域 | foundation-issues Phase A/B + design-optimization P1/P2/P3 | 🔴 | 上下游关系非冲突；Phase 0.7 优先实施，其余延后验证 | ✅ 已解决 |
| 市场分析 vs 市场感知抢 `llm_advice_stream()` | market-analysis Phase D + market-awareness §5 | 🔴 | **以 market-analysis 为准**，market-awareness §5 降级为可选 | ✅ 已解决 |
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

Phase 2.1 (数据管道质量提升)    依赖 Phase 0.7~1.0
  ├── 2.1.0-2.1.4 P1 引擎修复      → 策略差异化+分类+强制标的+拼接 bug
  ├── 2.1.5-2.1.8 P2 策略检查增强
  └── 2.1.9-2.1.12 P3 测试防护增强

Phase 2.2 (测试防护+市场分析+设计报告)
  ├── 2.2.1-2.2.3 测试安全网        → 为 Phase 3.1 提供防护
  ├── 2.2.5  market-analysis C       依赖 1.1.8+1.1.9
  ├── 2.2.6-2.2.7  market-analysis D/E
  └── 2.2.8-2.2.10 design-report A2/C1/C2

Phase 3.1 (前端 UI 重构)         依赖 Phase 2.2 测试防护

Phase 4.1 (数据源改造)           独立，为 Phase 5.1 提供前提

Phase 5.1 (市场感知联动)         可选，依赖 Phase 4.1

Phase 6.1 (可观测性增强)         独立或依赖 Phase 4.1

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
  Phase 4.1.1-4.1.6 → Phase 6.1.1-6.1.2 (EventStore+前端)

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
