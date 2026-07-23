# ETF Surge 方案实施总计划

> 生成日期: 2026-07-23 | 版本: v3.0
> 总览 `docs/` 目录 **23 份**方案文档，梳理实施状态、冲突重叠、修复建议及分阶段执行路线。
> v3.0 新增 `design-pipeline-foundation-issues.md` 深度诊断文档的处理；Phase 0 和 Phase 0.5 标注 ✅ 已完成；新增 Phase 0.7 处理管道基础缺陷（P0 级 Bug）；修复 v2.0 中 `five-improvements-plan.md` 内部状态不一致的问题。

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
| `five-improvements-plan.md` | 4/5 项已实现——#2 `filter_extreme_drawdown` ✓、#3 `check_defense_effectiveness` ✓、#4 `remove_stale_candidates` ✓、#5 `_layer_phrase` 模板多样化 ✓；#1 统一市态判定仍待完成（需 `portfolio_service.py` + `strategy_check_worker.py` 改动 ~15 行） |

### 1.2 部分完成

| 文档 | 完成部分 | 未完成部分 |
|------|---------|-----------|
| `design-report-optimization-plan.md` | 报告管道就绪、`_validate_report_consistency` 实现、WS 推送链路完整；A1（表格"因子"→"多因子评分"）已随 Phase 0.5 落地 | A2（预期收益随市态调整）、B1-B3（LLM prompt 分析增强）、C1（全市场净流入信号）、C2（卫星层科技 ETF）—— 其中 A2/C1/C2 依赖 Phase 0.7（因子分正常后验证效果） |
| `five-improvements-plan.md` | #2（极端下跌排除）+ #3（防御有效性）+ #4（freshness 检查）+ #5（理由多样化）已实现 | #1（统一市态判定）仍待完成，~15 行，作为 Phase 1 条目 |
| `market-awareness-and-data-source-plan.md` | Stooq 已在全球指数降级链中引用；§4 数据源替换已转入 `roadmap-data-source-unified.md` | §5 市场感知联动（MarketReport 忽略 `market` prop、AiAdvisor 硬编码、组合设计无 `market` 参数等）—— 此部分与 `market-analysis-optimization-plan.md` Phase D/E 有重叠，**建议以 market-analysis 方案为准实施** |
| `factor-model-extension-plan.md` | 因子注册表从 12 个扩展到 ~30 个计算函数 | YAML 中 167 个远未全覆盖；IC 追踪器从未运行 |
| `design-pipeline-foundation-issues.md` | **新诊断文档**（2026-07-23），基于代码审计 + DB 数据验证，发现 4 个 P0 + 3 个 P1 + 2 个 P2 级缺陷 | 全部待实施——Phase A 数据基础修复 + Phase B 引擎修复 + Phase C 质量提升，映射为 **Phase 0.7** |

### 1.3 已替代 (v2.0 新增)

| 文档 | 替代状态 | 替代者 |
|------|---------|--------|
| `source-registry-optimization-plan.md` | **已替代** | `roadmap-data-source-unified.md` (Phase B/C) |
| `data-source-monitoring-plan.md` | **已替代** | `roadmap-data-source-unified.md` (Phase D) |
| `review-20260720.md` | 评审记录，非实施方案 | N/A |

### 1.4 未开始（v3.0 更新）

| 文档 | 优先级 | 关键依赖 | 预估工时 |
|------|--------|---------|---------|
| `design-pipeline-foundation-issues.md` | **P0** | 自身 Phase A→B→C 按序；与 Phase 0.5 互补不冲突 | ~5h |
| `news-pipeline-fix-plan.md` P1 | **P1** | 依赖 P0 已实施（Phase 0 完成） | ~2h |
| `sector-concept-optimization-plan.md` | **P1** | Phase 1-2 独立可先行；Phase 4 依赖 LLM prompt 合并 | ~8h |
| `market-analysis-optimization-plan.md` | **P1** | Phase A-C 须按序；D/E 独立 | ~13-19h |
| `frontend-ui-optimization-plan.md` | **P1** | 曾实现后回滚，需测试安全网就绪后重做 | ~8h |
| `frontend-testing-safety-net.md` | **P1** | 前端架构重构已就绪 | ~11h |
| `frontend-performance-optimization.md` (Step 2-3) | **P1** | Step 1 已实施（Phase 0）；Step 2-3 待做 | ~1.5h |
| `five-improvements-plan.md` #1 | **P1** | 独立，~15 行 | ~15min |
| `roadmap-data-source-unified.md` | **P2** | 整合三份原方案，实施顺序详见自身依赖图 | ~3-5天 |
| `market-awareness-and-data-source-plan.md` §5 | **P2** | **建议以 market-analysis Phase D/E 替代** | — |
| `config-management-plan.md` | **P2** | 无（独立） | ~8h |
| `factor-model-extension-plan.md` | **P3** | 远期优化 | — |
| `e2e-testing-plan.md` | **P3** | 前端 UI 稳定后（避免维护成本过高） | ~16h |

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

### 3.7 增量阶段划分建议（v3.0，基于 v2.0 更新）

Phase 0 (✅ 已完成) 和 Phase 0.5 (✅ 已完成) 移出增量划分。
新增 Phase 0.7 轨道（独立于其他任务）：
```
design-pipeline-foundation-issues.md  → Phase 0.7
├── Phase A (数据基础修复)       → Phase 0.7-A
├── Phase B (引擎修复)           → Phase 0.7-B
└── Phase C (质量提升)           → Phase 0.7-C（部分延至 Phase 1）
```

现有轨道编号更新（原 Phase 1 → 编号不变，但起始依赖前移经过 Phase 0.7）：
```
Track C: 新闻管道修复
├── P0 (WS id + 前端 fallback)    → Phase 0 (✅ 已实施)
├── P1 (新浪源 + 关键词修复)      → Phase 1（独立实施）
└── P2 (stars 新鲜度)             → Phase 6 可选

Track D: 市场分析重构
├── Phase A (统一搜索后端)          → Phase 1（可先行）
├── Phase B (统一分析编排)          → Phase 2（与 1.8 可并行）
├── Phase C (前端合并组件)          → Phase 3（依赖 A+B）
├── Phase D (AI 顾问流式+数据)      → Phase 2 或 3（独立）
└── Phase E (报告质量提升)          → Phase 3（独立，但 prompt 须与其他方案协调）
```

### 3.8 增量阶段划分建议（v2.0 存档）

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

### Phase 1 — 数据层增强 & 统一市态（P1）

**前置依赖**: Phase 0.7 完成（因子分正常 + tracked_index 到位）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 1.0 | Five-improvements #1：统一市态判定（策略检查复用 pool_manager） | `five-improvements-plan.md` #1 | ~15min | 无（独立） |
| 1.1 | Sector 数据采集扩容（行业+概念 concurrent；复用 Phase 0.7 A3 的缓存写入入口） | sector-concept Phase 1 | 4h | Phase 0.7 A3 |
| 1.2 | PoolManager sector_cache 写入扩展（基于 A3 已有入口） | sector-concept Phase 2 | 3h | 1.1 |
| 1.3 | APScheduler 新增 60s 板块刷新任务 | sector-concept Phase 2 | 1h | 1.2 |
| 1.4 | 新闻关键词分类修复（移中性词、清冲突词） | news-pipeline-fix P1.1+P1.2 | 0.5h | 无 |
| 1.5 | 新增 `fetch_sina_roll_news()` HTTP 源 | news-pipeline-fix P1.3 | 1h | 无 |
| 1.6 | 重写 `fetch_macro_news()` 降级链（新浪优先） | news-pipeline-fix P1.4 | 0.5h | 1.5 |
| 1.7 | 重写 `fetch_global_news()` 降级链 | news-pipeline-fix P1.5 | 0.5h | 无 |
| 1.8 | market-analysis Phase A（统一搜索后端） | market-analysis §3 | 3-4h | 无 |
| 1.9 | market-analysis Phase B（统一分析编排端点） | market-analysis §4 | 1-2h | 无（与 1.8 可并行） |

**验证**:
- LLM 报告不再显示"暂无板块热力数据"
- 新闻源日志含 `[news] 新浪财经返回 N 条`，`fetch_macro_news` 改动前 ≤24s → 改动后 ~0.3s
- `GET /market/search?keyword=茅台&market=A` 返回 `type:"stock"` 结果
- 策略检查的 regime 与设计方案一致（统一市态判定）

### Phase 2 — 质量防护网 + AI 分析增强 + 设计报告增强

**前置依赖**: Phase 0.7 完成（因子分正常后设计报告优化才有意义）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 2.1 | AppButton/AppCard/AppTabs/AppInput/AppModal 单测 | frontend-testing-safety-net Phase A | 4h | 无 |
| 2.2 | useDashboardData composable 单测 | frontend-testing-safety-net Phase B | 1h | 无 |
| 2.3 | E2E spec 扩充到 10-15 条 | frontend-testing-safety-net Phase B/C | 6h | 无 |
| 2.4 | verify_e2e.py 全局指数检查修复 | fix-global-indices-plan 根因 #7 | 0.5h | 无 |
| 2.5 | market-analysis Phase C（前端 UnifiedAnalysis 合并组件） | market-analysis §5 | 4-5h | Phase 1.8+1.9 (A+B) |
| 2.6 | market-analysis Phase D（AI 顾问流式+数据管道） | market-analysis §6 | 2-3h | 无（可并行） |
| 2.7 | market-analysis Phase E（市场报告质量提升） | market-analysis §7 | 2-3h | 无（可并行） |
| 2.8 | design-report A2：预期收益随市态动态调整 | `design-report-optimization-plan.md` A2 | ~20行 | Phase 0.7 B1（因子分正常） |
| 2.9 | design-report C1：全市场净流入信号注入 LLM 报告 | `design-report-optimization-plan.md` C1 | ~30行 | Phase 0.7 验证通过 |
| 2.10 | design-report C2：卫星层增加科技 ETF 选项 | `design-report-optimization-plan.md` C2 | ~15行 | Phase 0.7 验证通过 |

**验证**:
- `npm test` 全绿 + `npm run test:e2e:smoke` 全绿
- 市场分析页面由 6 卡片降为 4 卡片，所有分析功能正常
- AI 顾问流式渲染，返回有实质数据的回答
- 市场研判报告含「综合研判结论」+「操作建议」
- 设计方案预期收益根据市态动态调整（非硬编码）
- 卫星层包含宽基科技 ETF 选项（科创50/创业板）

### Phase 3 — 前端 UI 重构（重新实施，防回滚）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 3.1 | Dashboard 手工 card → AppCard（7 区块） | frontend-ui-optimization Phase 2 | 4h | 2.1 (测试防护) |
| 3.2 | Dashboard 手工 tab → AppTabs | frontend-ui-optimization Phase 2 | 1h | 2.1 |
| 3.3 | PortfolioAnalysis tab → AppTabs | frontend-ui-optimization Phase 2 | 1h | 同上 |
| 3.4 | TokenMonitor / MarketAnalysis / DesignResult tab → AppTabs | frontend-ui-optimization Phase 2 | 2h | 同上 |
| 3.5 | Vite chunk 优化（vendor-vue/axios/echarts 分层） | frontend-performance Step 2 | 0.5h | 无 |
| 3.6 | 各页面 ECharts 清理重复注册 | frontend-performance Step 3 | 1h | 0.4 |

**注意**: Phase 3 须在 Phase 2 测试防护就绪后才实施，以避免 UI 回滚重演。
**注意**: market-analysis Phase C 已改变了 MarketAnalysis.vue 的 DOM 结构，UI 优化在此基础上做 AppCard/AppTabs 替换。

**验证**: 逐页面视觉验证 + `npm test` 全绿 + `npm run build` 确认 chunk 拆分

### Phase 4 — 数据源系统改造（大方案，独立轨道）

此阶段完全对应 `roadmap-data-source-unified.md` 的四个子阶段。详见该文档 §依赖关系与推荐顺序。

| # | 任务 | 源阶段 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 4.1 | 美股 `_route_us_stooq()` 新链路（Stooq→TwelveData→Finnhub） | roadmap Phase A | 2h | 无 |
| 4.2 | 全球指数链路统一 + TwelveData/Finnhub 加入 | roadmap Phase A (A4) | 2h | 无 |
| 4.3 | China market 3 核心函数接入 SourceRegistry | roadmap Phase B | 3h | 无 |
| 4.4 | price=0 过滤前置修复 | roadmap Phase B | 1h | 无 |
| 4.5 | 补齐 7 个健康探针（新建 `monitor/probes.py`） | roadmap Phase C | 2h | 无 |
| 4.6 | SourceRegistry 加 on_event 回调 | roadmap Phase D (D2-D4) | 1h | 无 |

**并行策略**:
- **Track 1**: 4.1 + 4.2 + 4.3 可并行（不同文件，互不冲突）
- **Track 2**: 4.5 独立（仅修改 main.py + 新建 probes.py）
- **Track 3**: 4.6 是串行瓶颈，须最后做

**验证**: verify_e2e.py + 长稳运行观察降级是否正常工作

### Phase 5 — 市场感知联动（可选，待评估）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 | 备注 |
|---|------|--------|---------|---------|------|
| 5.1 | 后端 MarketContext 路由层 | market-awareness §5.2 | 6h | 4.1-4.3 | ⚠️ 若 market-analysis Phase D+E 已满足需求，此任务可取消 |
| 5.2 | MarketReport market prop 传递 | market-awareness §5.3 | 2h | 5.1 | 已在 market-analysis Phase E 中部分实现 |
| 5.3 | AiAdvisor market 上下文 | market-awareness §5.3 | 2h | 5.1 | 已在 market-analysis Phase D 中实现 |
| 5.4 | 组合设计 market 参数 | market-awareness §5.3 | 2h | 5.1 | — |
| 5.5 | LLM prompt 市场上下文注入 | market-awareness §5.4 | 2h | 5.1 | — |

**验证**: 切换到美股 Tab → 所有功能使用美股数据

### Phase 6 — 可观测性与系统增强

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 6.1 | SourceEventStore（source_events 表 + API） | roadmap Phase D (D1+D6+D7) | 6h | 4.6 |
| 6.2 | 前端数据源监控页面 | roadmap Phase D7 | 4h | 6.1 |
| 6.3 | ConfigManager + app_config 表 | config-management §4.1-4.3 | 4h | 无 |
| 6.4 | 前端 ConfigPage | config-management §5 | 4h | 6.3 |
| 6.5 | Sector API 实时行情返回 | sector-concept Phase 3 | 3h | 1.1 |
| 6.6 | LLM prompt 热点板块注入 | sector-concept Phase 4 | 2h | 1.2 + 1.3 |
| 6.7 | `stars` 引入时间新鲜度 + 新闻 Level 2 精度调整 | news-pipeline-fix P2 | 1h | 无 |
| 6.8 | `news_fetcher` 单独验证脚本更新 verify_e2e.py | news-pipeline-fix §8 | 0.5h | 0.6+0.7 |

**验证**: 数据源状态页可查 + 配置页读写正常 + 板块数据实时行情带涨跌颜色

### Phase 7 — 远期优化

| # | 任务 | 源文档 | 说明 |
|---|------|--------|------|
| 7.1 | Factor IC 追踪器激活 | factor-model-extension | 评估是否需要更多因子，不急于实施 |
| 7.2 | 排版令牌迁移 | frontend-ui-optimization Phase 3-4 | 视觉效果深化 |
| 7.3 | SVG 图标替换 emoji | frontend-ui-optimization Phase 3 | 美观度提升 |
| 7.4 | 响应式补齐 | frontend-ui-optimization Phase 4 | 移动端适配 |
| 7.5 | Playwright E2E 全覆盖 | e2e-testing-plan | 12 个 spec 文件全覆盖 |
| 7.6 | design-report B1-B3（LLM prompt 分析增强） | design-report-optimization B1-B3 | LLM prompt 深层分析增强 |

---

## 5. 附录：各方案摘要

### 5.1 文档状态速查表（v3.0 更新）

| 文档 | 类型 | 状态 | 改行数 | 影响模块 | 备注 |
|------|------|------|-------|---------|-------------|
| config-management-plan.md | 实施方案 | ❌ 未实施 | ~400 行 | 后端 admin + 前端 ConfigPage | — |
| data-source-monitoring-plan.md | 实施方案 | ❌ **已替代** | ~500 行 | — | 被 `roadmap-data-source-unified.md` 替代 |
| design-optimization-plan.md | 实施方案 | ✅ 已实施 | — | strategy_design + engine/ | — |
| **design-pipeline-foundation-issues.md** | **诊断+修复方案** | **❌ 未实施** | **~80 行** | **etf_scanner + pool_manager + factor_registry + risk_controls + allocation_engine** | **⬅️ v3.0 新增，4 个 P0 + 3 个 P1** |
| design-report-optimization-plan.md | 实施方案 | ⚠️ 部分 | ~100 行 | llm.py + design_report.py | A2/C1/C2 未完成，延至 Phase 2 |
| e2e-testing-plan.md | 实施方案 | ❌ 未实施 | ~800 行 | frontend/e2e/ spec 文件 | 建议推迟到 Phase 7 |
| factor-model-extension-plan.md | 实施方案 | ⚠️ 部分 | ~200 行 | factor_registry.py | 远期优化 |
| five-improvements-plan.md | 实施方案 | ⚠️ 4/5 已实施 | ~60 行 | risk_controls.py + rationale.py | #1 待完成，Phase 1 |
| fix-global-indices-plan.md | 修复方案 | ✅ **已实施 (Phase 0)**| ~50 行 | market_service + GlobalIndicesStrip | Phase 0 完成 |
| frontend-architecture-refactor.md | 实施方案 | ✅ 已实施 | — | 全部前端组件 | — |
| frontend-performance-optimization.md | 优化方案 | ⚠️ Step 1 已实施 | ~15 行 | main.js + vite.config.js | Step 2-3 待做 (Phase 3) |
| frontend-testing-safety-net.md | 测试方案 | ❌ 未实施 | ~400 行 | frontend/test + e2e | Phase 2 |
| frontend-ui-optimization-plan.md | 优化方案 | ❌ 已回滚 | ~200 行 | 全部前端视图 | Phase 3 |
| issues-analysis-report.md | 问题分析 | ✅ 已修复 | — | 全局 | — |
| market-analysis-optimization-plan.md | 实施方案 | ❌ 未实施 | ~400 行 | analysis router + llm.py + MarketAnalysis.vue + AiAdvisor.vue | Phase 1-3 |
| market-awareness-and-data-source-plan.md | 实施方案 | ❌ 未实施 | ~500 行 | 路由 + Service + LLM | §4 已转 roadmap；§5 待评估 |
| news-pipeline-fix-plan.md | 修复方案 | ⚠️ P0 已实施 | ~70 行 | news_fetcher.py + levistock_fetcher.py + NewsView.vue | P0 (Phase 0) ✅；P1 待做 (Phase 1) |
| optimization-plan-20260721.md | 实施方案 | ✅ **已实施 (Phase 0.5)**| ~80 行 | etf_scanner + 前端 + 后端链路 | 全部 8 项完成 |
| review-20260720.md | 评审报告 | N/A | — | N/A | 非实施方案 |
| roadmap-data-source-unified.md | 实施方案 | ❌ 未实施 | ~330 行 | china_market + market_service + source_registry + monitor | 替代三份原方案，Phase 4 |
| sector-concept-optimization-plan.md | 实施方案 | ❌ 未实施 | ~300 行 | market_trends + pool_manager + llm.py | Phase 1/6 |
| source-registry-optimization-plan.md | 实施方案 | ❌ **已替代** | ~70 行 | china_market + main.py | 被 `roadmap-data-source-unified.md` 替代 |

### 5.2 冲突汇总（v3.0 更新）

| 冲突 | 涉及文档 | 重要性 | 解决方式 | 状态 |
|------|---------|--------|---------|:----:|
| 数据源改造三文档抢同一代码域 | source-registry + data-source-monitoring + market-awareness §4 | 🔴 | 合并为 `roadmap-data-source-unified.md` | ✅ 已解决 |
| foundation-issues 与存量文档改同一代码域 | foundation-issues Phase A/B + design-optimization P1/P2/P3 | 🔴 | 上下游关系非冲突；Phase 0.7 优先实施，其余延后验证 | ✅ 已解决 (§2.7) |
| 市场分析 vs 市场感知抢 `llm_advice_stream()` | market-analysis Phase D + market-awareness §5 | 🔴 | **以 market-analysis 为准**，market-awareness §5 降级为可选 | ✅ 已解决 |
| foundation-issues A3 与 sector-concept Phase1-2 抢缓存入口 | foundation-issues A3 + sector-concept Phase 1-2 | 🟡 | 先 A3（最小化实现），sector-concept 在已有入口上扩展 | ✅ 已解决 (§2.8) |
| LLM prompt 被三文档同时修改 | market-analysis Phase E + design-report A2/C1/C2 + sector-concept Phase 4 | 🟡 | 同步实施，统一修改 `llm.py`，先做结构后加数据 | 待实施 |
| 同一页面被两方案同时改动 | market-analysis Phase C + frontend-ui Phase 1-2 | 🟡 | 先实施 Phase C（DOM 结构），再在目标结构上做 UI 优化 | 待实施 |
| 全球指数降级链分歧 | fix-global-indices vs market-awareness | 🟡 | 统一链路，已写入 roadmap-data-source-unified | ✅ 已落地 |
| UI 重构曾回滚，需要测试防护 | frontend-ui-optimization + frontend-testing-safety-net | 🟡 | 先做 testing 再做 UI | 待实施 |

### 5.3 关键依赖图（v3.0 更新）

```
Phase 0 (快速胜利 7 项)        ✅ 已完成
  ├── 0.1-0.5 fix-global-indices + perf
  └── 0.6-0.7 news-pipeline P0
  │
Phase 0.5 (核心链路修复)       ✅ 已完成
  │
Phase 0.7 (数据管道基础修复)   ◀── 新插入，P0 级（新增）
  ├── 0.7.1-0.7.2 tracked_index 链  → 0.7.8 候选池去重
  ├── 0.7.3 市场快照缓存写入        → Phase 1 sector 扩展
  ├── 0.7.4 因子分键名聚合           → 0.7.12 三方案差异化
  │                                  → Phase 2.8-2.10 设计报告增强
  ├── 0.7.5-0.7.7 防御层修复         → V5/V6 验证
  ├── 0.7.10 regime 映射修复         → V10 验证
  └── 0.7.11 design_text 诊断        → V9 验证
  │
Phase 1 (数据层增强+统一市态)   依赖 Phase 0.7
  ├── 1.0 five-improvements #1  独立
  ├── 1.1-1.3 sector cache      → Phase 6 LLM prompt
  ├── 1.4-1.7 news-pipeline P1  → 新闻模块功能完整
  └── 1.8-1.9 market-analysis A+B → Phase 2.5 (Phase C 依赖)
  │
Phase 2 (测试防护+市场分析+设计报告)
  ├── 2.1-2.3 测试安全网        → 为 Phase 3 提供防护
  ├── 2.4  verify_e2e 修复
  ├── 2.5  market-analysis C    依赖 1.8+1.9
  ├── 2.6-2.7  market-analysis D/E  独立
  └── 2.8-2.10 design-report A2/C1/C2  依赖 Phase 0.7 验证通过
  │
Phase 3 (前端 UI 重构)         依赖 Phase 2 测试防护
  │
Phase 4 (数据源改造)           独立，为 Phase 5 提供前提
  │
Phase 5 (市场感知联动)         可选，依赖 Phase 4
  │
Phase 6 (可观测性增强)         独立或依赖 Phase 4
  │
Phase 7 (远期优化)             无紧急依赖
```

### 5.4 轨道总览（v3.0 更新）

```
🔧 数据管道基础修复 Track（新，P0 级）
  Phase 0.7.1-0.7.12 (tracked_index + 因子分 + 缓存 + 去重 + 风控 + regime + design_text)

📰 新闻管道修复 Track
  Phase 0 (WS 修复, ✅) → Phase 1.4-1.7 (数据源增强) → Phase 6.7-6.8 (星+验证)

📊 市场分析重构 Track（~13-19h）
  Phase 1.8-1.9 (搜索+路由后端) → Phase 2.5-2.7 (前端+流式+报告) → 与 Phase 3 UI 优化协调

📋 设计报告增强 Track（~2h）
  Phase 2.8-2.10 (预期收益 + 净流入 + 科技ETF) → 依赖 Phase 0.7 B1

🔌 数据源统一改造 Track
  Phase 4.1-4.6 → Phase 6.1-6.2 (EventStore+前端)
```

---

## 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-22 | 初次生成，覆盖全部 18 份文档 |
| v2.0 | 2026-07-22 | 新增 3 份文档处理 + 新轨道 + 冲突分析；调整 Phase 0/1/2/3 |
| v3.0 | 2026-07-23 | 新增 `design-pipeline-foundation-issues.md`（23 份文档）；Phase 0/0.5 标记 ✅ 完成；新增 Phase 0.7（12 项 P0/P1 修复）；修复 `five-improvements-plan.md` 内部状态不一致；新增 §2.7-2.11 冲突分析（foundation-issues vs 存量文档）；新增 §3.5-3.8 修复方案（foundation-issues 集成 + 归档更新）；更新 §4 路线图（Phase 0-0.7-1-2 排序）；更新附录 5.1-5.4 全部表格；统一版本号连贯性 |
