# ETF Surge 方案实施总计划

> 生成日期: 2026-07-22 | 版本: v2.0
> 总览 `docs/` 目录 **22 份**方案文档，梳理实施状态、冲突重叠、修复建议及分阶段执行路线。
> v2.0 新增 `market-analysis-optimization-plan.md`、`news-pipeline-fix-plan.md`、`roadmap-data-source-unified.md` 三份文档的处理。

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
| `five-improvements-plan.md` | 5 项改进全部实现 (`filter_extreme_drawdown` + `check_defense_effectiveness` + `remove_stale_candidates` + `_layer_phrase` 模板多样化 + 统一市态 `get_market_regime`)，见 `engine/risk_controls.py` + `engine/rationale.py` |

### 1.2 部分完成

| 文档 | 完成部分 | 未完成部分 |
|------|---------|-----------|
| `design-report-optimization-plan.md` | 报告管道就绪、`_validate_report_consistency` 实现、WS 推送链路完整 | A2（预期收益随市态调整）、C1（全市场净流入信号）、C2（卫星层科技 ETF） |
| `five-improvements-plan.md` | #2 `filter_extreme_drawdown` ✓、#3 `check_defense_effectiveness` ✓ | #1 统一市态判定、#4 收益风险调整、#5 策略检查对齐 |
| `market-awareness-and-data-source-plan.md` | Stooq 已在全球指数降级链中引用；§4 数据源替换已转入 `roadmap-data-source-unified.md` | §5 市场感知联动（MarketReport 忽略 `market` prop、AiAdvisor 硬编码、组合设计无 `market` 参数等）—— 此部分与 `market-analysis-optimization-plan.md` Phase D/E 有重叠，**建议以 market-analysis 方案为准实施** |
| `factor-model-extension-plan.md` | 因子注册表从 12 个扩展到 ~30 个计算函数 | YAML 中 167 个远未全覆盖；IC 追踪器从未运行 |

### 1.3 已替代 (v2.0 新增)

| 文档 | 替代状态 | 替代者 |
|------|---------|--------|
| `source-registry-optimization-plan.md` | **已替代** | `roadmap-data-source-unified.md` (Phase B/C) |
| `data-source-monitoring-plan.md` | **已替代** | `roadmap-data-source-unified.md` (Phase D) |
| `review-20260720.md` | 评审记录，非实施方案 | N/A |

### 1.4 未开始

| 文档 | 优先级 | 关键依赖 | 预估工时 |
|------|--------|---------|---------|
| `fix-global-indices-plan.md` | **P0** | 无（独立） | ~2h |
| `optimization-plan-20260721.md` | **P0** | 无（多个改动不冲突） | ~40min |
| `news-pipeline-fix-plan.md` P0 | **P0** | 无（WS 新闻修复，后端+前端共 6 行） | ~15min |
| `news-pipeline-fix-plan.md` P1 | **P1** | P0 (fetch_news_headlines 加 id 先做) | ~2h |
| `sector-concept-optimization-plan.md` | **P1** | 无（Phase 1-2 独立） | ~8h |
| `market-analysis-optimization-plan.md` | **P1** | Phase A-C 须按序；D/E 独立 | ~13-19h |
| `frontend-ui-optimization-plan.md` | **P1** | 曾实现后回滚，需测试安全网就绪后重做 | ~8h |
| `frontend-testing-safety-net.md` | **P1** | 前端架构重构已就绪 | ~11h |
| `frontend-performance-optimization.md` | **P1** | 无（独立） | ~1h |
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

### 2.7 🟢 sector-concept vs market-analysis Phase C 的兼容性

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

### 3.5 增量阶段划分建议（v2.0）

新增两条独立轨道：

**Track C: 新闻管道修复**（独立于其他任务）
```
news-pipeline-fix-plan.md
├── P0 (WS id + 前端 fallback)    → Phase 0（极低成本，高收益）
├── P1 (新浪源 + 关键词修复)      → Phase 1（独立实施）
└── P2 (stars 新鲜度)             → Phase 6 可选
```

**Track D: 市场分析重构**（新增大方案，建议走独立轨道）
```
market-analysis-optimization-plan.md
├── Phase A (统一搜索后端)          → Phase 1 或 Phase 2
├── Phase B (统一分析编排)          → Phase 2（与 A 可并行）
├── Phase C (前端合并组件)          → Phase 3（依赖 A+B）
├── Phase D (AI 顾问流式+数据)      → Phase 2 或 3（独立）
└── Phase E (报告质量提升)          → Phase 3（独立，但 prompt 须与其他方案协调）
```

---

## 4. 分阶段实施路线图

### Phase 0 — 快速胜利（独立，极低成本，10 项任务）

| # | 任务 | 源文档 | 预估工时 | 说明 |
|---|------|--------|---------|------|
| 0.1 | GlobalIndicesStrip 加 onMounted | fix-global-indices-plan.md | 0.5h | 1 行 import + 1 行调用，解决"永远空" |
| 0.2 | get_global_indices() 加 try/except | fix-global-indices-plan.md | 0.5h | 防止 500 |
| 0.3 | 修复缓存语义 (update → 全量赋值) | fix-global-indices-plan.md | 0.5h | 3 行改动 |
| 0.4 | main.js 移除 ECharts 全局 import | frontend-performance-optimization.md | 15min | 删 1 行，首屏省 ~500KB |
| 0.5 | GlobalIndicesStrip 补 CSS 样式 | fix-global-indices-plan.md | 0.5h | 组件样式缺失 |
| 0.6 | 后端 `fetch_news_headlines()` 加 `id` 字段 | news-pipeline-fix-plan.md P0.1 | 15min | 4 行代码（hashlib md5），WS 推送从不出现在列表→正常推送 |
| 0.7 | 前端 `handleNews()` 加无 `id` fallback | news-pipeline-fix-plan.md P0.2 | 15min | 修改 `if (!item \|\| item.id == null)` 为更健壮的守卫 |

**验证**:
- verify_e2e.py + 浏览器打开 Dashboard 确认全球指数可显示
- 浏览器打开 NewsView，等待 30s 确认 WS 推送的新闻出现在列表顶部

### Phase 0.5 — 核心链路修复（P0，数据管道 + 策略检查 + 历史记录）

**来源**: `optimization-plan-20260721.md`

**目标**: 修复智能组合设计/策略检查/历史记录三大核心功能的 P0/P1 阻塞问题

| # | 任务 | 文件 | 改动 | 预估工时 |
|---|------|------|------|---------|
| 0.5.1 | ETF 缓存 TTL 修正 + last-good 兜底 | `etf_scanner.py` | `CACHE_TTL.get("etf_scanner", 120)` → `CACHE_TTL["etf_list"]`；模块级 `_last_good_etfs` 兜底 | 1h |
| 0.5.2 | East Money 直连 HTTP 新数据源 | `etf_scanner.py` | 新增 `_fetch_em_etf_list()` 直连东方财富 push2 API 获取全量 ETF 列表 | 2h |
| 0.5.3 | akshare timeout 延长 + ETF 缓存预热 | `etf_scanner.py` + `main.py` | ak 超时 8→25s；启动时 `_warmup_etf_cache()` | 0.5h |
| 0.5.4 | 策略检查 taskStatus props 补齐 | `DashboardAiTools.vue` | `StrategyCheckResult` 加 `task-status` / `task-progress` / `task-stage` prop 传递 | 1h |
| 0.5.5 | task.error → task.error_message 兼容 | `DashboardAiTools.vue` + `strategy_check_worker.py` | 前端读 `task.error_message \|\| task.error \|\| fallback`；后端 worker 从 `task.params` 读 `portfolio_type` | 1h |
| 0.5.6 | 历史记录 Promise.all 加 catch 隔离 | `DashboardAiTools.vue` + `portfolio.py` | `Promise.all([...].map(p => p.catch(...)))`；`list_strategy_checks` 加异常保护 | 1h |
| 0.5.7 | 模型新增 status/error_message 字段 | `portfolio_design.py` + `task_manager.py` | `PortfolioDesign.status` / `error_message`；保存时写入状态；路由返回 status | 1.5h |
| 0.5.8 | 前端历史记录状态徽标 + 运行中合并 | `DesignHistory.vue` + `DashboardAiTools.vue` | 状态徽标渲染；`loadHistoryList` 合并 running 任务；`onHistorySelect` 类型分发 | 2h |

**验证**:
- 设计生成：输入金额 → 生成三套方案 → 自动跳转结果页
- 策略检查：弹窗选择组合类型 → 不白屏 → 不超时 → 按所选组合执行
- 历史记录：加载不因任一路径失败整体白屏；状态徽标正确显示

### Phase 1 — 数据层 & 新闻管道修复（P0/P1 阻塞）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 1.1 | Sector 数据采集扩容（行业+概念 concurrent） | sector-concept Phase 1 | 4h | 无 |
| 1.2 | PoolManager sector_cache 写入入口 | sector-concept Phase 2 | 3h | 1.1 |
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

### Phase 2 — 质量防护网 + AI 分析增强

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 2.1 | AppButton/AppCard/AppTabs/AppInput/AppModal 单测 | frontend-testing-safety-net Phase A | 4h | 无 |
| 2.2 | useDashboardData composable 单测 | frontend-testing-safety-net Phase B | 1h | 无 |
| 2.3 | E2E spec 扩充到 10-15 条 | frontend-testing-safety-net Phase B/C | 6h | 无 |
| 2.4 | verify_e2e.py 全局指数检查修复 | fix-global-indices-plan 根因 #7 | 0.5h | 无 |
| 2.5 | market-analysis Phase C（前端 UnifiedAnalysis 合并组件） | market-analysis §5 | 4-5h | Phase 1.8+1.9 (A+B) |
| 2.6 | market-analysis Phase D（AI 顾问流式+数据管道） | market-analysis §6 | 2-3h | 无（可并行） |
| 2.7 | market-analysis Phase E（市场报告质量提升） | market-analysis §7 | 2-3h | 无（可并行） |

**验证**:
- `npm test` 全绿 + `npm run test:e2e:smoke` 全绿
- 市场分析页面由 6 卡片降为 4 卡片，所有分析功能正常
- AI 顾问流式渲染，返回有实质数据的回答
- 市场研判报告含「综合研判结论」+「操作建议」

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
| 7.6 | design-report 预期收益随市态调整 + C1/C2 | design-report-optimization A2/C1/C2 | LLM prompt 数据增强 |

---

## 5. 附录：各方案摘要

### 5.1 文档状态速查表

| 文档 | 类型 | 状态 | 改行数 | 影响模块 | 备注 (v2.0) |
|------|------|------|-------|---------|-------------|
| config-management-plan.md | 实施方案 | ❌ 未实施 | ~400 行 | 后端 admin + 前端 ConfigPage | — |
| data-source-monitoring-plan.md | 实施方案 | ❌ **已替代** | ~500 行 | — | 被 `roadmap-data-source-unified.md` 替代 |
| design-optimization-plan.md | 实施方案 | ✅ 已实施 | — | strategy_design + engine/ | — |
| design-report-optimization-plan.md | 实施方案 | ⚠️ 部分 | ~100 行 | llm.py + design_report.py | A2/C1/C2 未完成 |
| e2e-testing-plan.md | 实施方案 | ❌ 未实施 | ~800 行 | frontend/e2e/ spec 文件 | 建议推迟到 Phase 7 |
| factor-model-extension-plan.md | 实施方案 | ⚠️ 部分 | ~200 行 | factor_registry.py | 远期优化 |
| five-improvements-plan.md | 实施方案 | ⚠️ 部分 | ~60 行 | risk_controls.py | — |
| fix-global-indices-plan.md | 修复方案 | ❌ 未实施 | ~50 行 | market_service + GlobalIndicesStrip | Phase 0 中 |
| frontend-architecture-refactor.md | 实施方案 | ✅ 已实施 | — | 全部前端组件 | — |
| frontend-performance-optimization.md | 优化方案 | ❌ 未实施 | ~15 行 | main.js + vite.config.js | Phase 0/3 |
| frontend-testing-safety-net.md | 测试方案 | ❌ 未实施 | ~400 行 | frontend/test + e2e | Phase 2 |
| frontend-ui-optimization-plan.md | 优化方案 | ❌ 已回滚 | ~200 行 | 全部前端视图 | Phase 3 |
| issues-analysis-report.md | 问题分析 | ✅ 已修复 | — | 全局 | — |
| **market-analysis-optimization-plan.md** | **实施方案** | **❌ 未实施** | **~400 行** | **analysis router + llm.py + MarketAnalysis.vue + AiAdvisor.vue** | **⬅️ v2.0 新增** |
| market-awareness-and-data-source-plan.md | 实施方案 | ❌ 未实施 | ~500 行 | 路由 + Service + LLM | §4 已转 roadmap；§5 待评估 |
| **news-pipeline-fix-plan.md** | **修复方案** | **❌ 未实施** | **~70 行** | **news_fetcher.py + levistock_fetcher.py + NewsView.vue** | **⬅️ v2.0 新增，P0 独立** |
| optimization-plan-20260721.md | 实施方案 | ❌ 未实施 | ~80 行 | etf_scanner + strategy_check_worker + DesignHistory + 前端 DashboardAiTools | Phase 0.5 |
| review-20260720.md | 评审报告 | N/A | — | N/A | 非实施方案 |
| **roadmap-data-source-unified.md** | **实施方案** | **❌ 未实施** | **~330 行** | **china_market + market_service + source_registry + monitor** | **⬅️ v2.0 新增，替代三份** |
| sector-concept-optimization-plan.md | 实施方案 | ❌ 未实施 | ~300 行 | market_trends + pool_manager + llm.py | Phase 1/6 |
| source-registry-optimization-plan.md | 实施方案 | ❌ **已替代** | ~70 行 | china_market + main.py | 被 `roadmap-data-source-unified.md` 替代 |

### 5.2 冲突汇总（v2.0 更新）

| 冲突 | 涉及文档 | 重要性 | 解决方式 |
|------|---------|--------|---------|
| 数据源改造三文档抢同一代码域 | source-registry + data-source-monitoring + market-awareness §4 | 🔴 → ✅ | **已解决** → 合并为 `roadmap-data-source-unified.md` |
| 市场分析 vs 市场感知抢 `llm_advice_stream()` | market-analysis Phase D + market-awareness §5 | 🔴 | **以 market-analysis 为准**，market-awareness §5 降级为可选 |
| LLM prompt 被三文档同时修改 | market-analysis Phase E + design-report A2/C1/C2 + sector-concept Phase 4 | 🟡 | 同步实施，统一修改 `llm.py`，先做结构后加数据 |
| 同一页面被两方案同时改动 | market-analysis Phase C + frontend-ui Phase 1-2 | 🟡 | 先实施 Phase C（DOM 结构），再在目标结构上做 UI 优化 |
| 全球指数降级链分歧 | fix-global-indices vs market-awareness | 🟡 | 统一链路 Sina→TwelveData→Finnhub→Stooq→placeholder，已写入 roadmap-data-source-unified |
| UI 重构曾回滚，需要测试防护 | frontend-ui-optimization + frontend-testing-safety-net | 🟡 | 先做 testing 再做 UI |

### 5.3 关键依赖图（v2.0 更新）

```
Phase 0 (快速胜利 7 项)        独立，无依赖
  ├── 0.1-0.5 fix-global-indices + perf
  ├── 0.6-0.7 news-pipeline P0 ← 独立，极高性价比
  │
Phase 0.5 (核心链路修复)       独立（数据管道+策略检查+历史记录）
  │
Phase 1 (数据层+新闻管道)      独立但后续被消费
  ├── 1.1-1.3 sector cache    → Phase 6 LLM prompt
  ├── 1.4-1.7 news-pipeline P1 → 新闻模块功能完整
  ├── 1.8-1.9 market-analysis A+B → Phase 2.5 (Phase C 依赖)
  │
Phase 2 (测试防护+市场分析)    
  ├── 2.1-2.3 测试安全网      → 为 Phase 3 提供防护
  ├── 2.4  verify_e2e 修复
  ├── 2.5  market-analysis C  依赖 1.8+1.9 (可等可不等)
  ├── 2.6  market-analysis D  独立
  └── 2.7  market-analysis E  独立（但 prompt 须与 Phase 6.6 协调）
  │
Phase 3 (前端 UI 重构)        依赖 Phase 2 测试防护
  │
Phase 4 (数据源改造)          独立，为 Phase 5 提供前提
  │
Phase 5 (市场感知联动)        可选，依赖 Phase 4
  │
Phase 6 (可观测性增强)        独立或依赖 Phase 4
  │
Phase 7 (远期优化)            无紧急依赖
```

### 5.4 v2.0 新增轨道总览

```
📰 新闻管道修复 Track（新）
  Phase 0.6-0.7 (WS 修复) → Phase 1.4-1.7 (数据源增强) → Phase 6.7-6.8 (星+验证)

📊 市场分析重构 Track（新，大方案 ~13-19h）
  Phase 1.8-1.9 (搜索+路由后端) → Phase 2.5-2.7 (前端+流式+报告) → 与 Phase 3 UI 优化协调

🔌 数据源统一改造 Track（已有方案）
  Phase 4.1-4.6 → Phase 6.1-6.2 (EventStore+前端)
```

---

## 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-22 | 初次生成，覆盖全部 18 份文档 |
| v2.0 | 2026-07-22 | 新增 3 份文档处理：`market-analysis-optimization-plan.md` ~13-19h 新轨道、`news-pipeline-fix-plan.md` P0 快速胜利+P1 数据源增强、`roadmap-data-source-unified.md` 数据源统一方案(已验证)；新增 4 处冲突分析(含 2 处🔴)；调整 Phase 0/1/2/3 任务分配；降级 market-awareness §5 为可选；标记 2 份已替代文档 |
