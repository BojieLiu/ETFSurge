# ETF Surge 方案实施总计划

> 生成日期: 2026-07-22
> 版本: v1.0
> 总览 `docs/` 目录 18 份方案文档，梳理实施状态、冲突重叠、修复建议及分阶段执行路线。

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
| `five-improvements-plan.md` | #2 `filter_extreme_drawdown` √、#3 `check_defense_effectiveness` √ | #1 统一市态判定、#4 收益风险调整、#5 策略检查对齐 |
| `market-awareness-and-data-source-plan.md` | Stooq 已在全球指数降级链中引用 | 市场联动：MarketReport 忽略 `market` prop、AiAdvisor 硬编码、组合设计无 `market` 参数等 |
| `factor-model-extension-plan.md` | 因子注册表从 12 个扩展到 ~30 个计算函数 | YAML 中 167 个远未全覆盖；IC 追踪器从未运行 |

### 1.3 未开始

| 文档 | 优先级 | 关键依赖 |
|------|--------|---------|
| `fix-global-indices-plan.md` | **P0** | 无（独立） |
| `sector-concept-optimization-plan.md` | **P0** | 无（独立） |
| `optimization-plan-20260721.md` | **P0** | 数据管道/策略检查/历史记录链路修复，backend + frontend 多处改动 |
| `frontend-ui-optimization-plan.md` | **P1** | 曾实现后回滚，需重新实施 |
| `frontend-testing-safety-net.md` | **P1** | 前端架构重构已就绪 |
| `frontend-performance-optimization.md` | **P1** | 无（独立） |
| `market-awareness-and-data-source-plan.md` | **P2** | Sector/Pool 数据管道就绪后 |
| `source-registry-optimization-plan.md` | **P2** | 无（独立） |
| `config-management-plan.md` | **P2** | 无（独立） |
| `data-source-monitoring-plan.md` | **P3** | 依赖 SourceRegistry 增强 |
| `factor-model-extension-plan.md` | **P3** | 远期优化 |

---

## 2. 冲突与重叠分析

### 2.1 🔴 重大重叠：三份文档争夺"数据源改造"领地

**涉及的文档**：

| 文档 | 重心 | 变更范围 |
|------|------|---------|
| `source-registry-optimization-plan.md` | 将 china_market 核心函数接入 SourceRegistry.route() | ~30 行，3 个函数 |
| `data-source-monitoring-plan.md` | 新增 SourceEventStore 全链路事件记录 | 新文件 + 5 API + 前端页面 |
| `market-awareness-and-data-source-plan.md` §4 | 重写美股 _route_us 链路（Stooq 主力） | ~50 行，3 条新路由函数 |

**冲突点**：
1. **SourceRegistry 同一处代码被三份文档同时修改**：source-registry 要加 `china_market` 回调，data-source-monitoring 要加 `on_event` 钩子，market-awareness 没有涉及 SR 但会改变 SR 管理的路由
2. **时间顺序冲突**：如果先做 data-source-monitoring 的 event hook，source-registry 的 china_market 接入就自动获得事件记录；如果先做 source-registry 接入，data-source-monitoring 需要适配
3. **市场感知方案的数据源替换**（yfinance → Stooq）也涉及 `_route_us()`，该函数是 SourceRegistry 已有的"业主"，改动需与 SR 状态管理一致

**修复建议 → 合并为「数据源统一改造计划」**（合并后文档可代替此三份）：

```
数据源统一改造 (合并替代三份文档)
├── Phase A: 美股路由重写 (from market-awareness §4)
│   ├── _route_us_stooq() 新链路 (Stooq→TwelveData→Finnhub)
│   ├── 全球指数：Stooq 提升为 Sina 后的第 2 优先
│   └── yfinance 降为 deprecation 状态
├── Phase B: China market 接入 SourceRegistry (from source-registry §P0-A)
│   ├── fetch_a_stock_realtime() → registry.route()
│   ├── fetch_a_stock_batch() → registry.route()
│   ├── fetch_hk_stock_realtime() → registry.route()
│   └── 前置修复：price=0 过滤
├── Phase C: 健康探针补全 (from source-registry §P0-B + data-source-monitoring §5.3)
│   ├── 新增 mootdx/sina/tencent/akshare/levistock 探针
│   └── 探针也写 SourceEventStore
├── Phase D: SourceEventStore (from data-source-monitoring)
│   ├── SourceRegistry 加 on_event 回调钩子
│   ├── 新增 source_events 表 + event store
│   ├── 新增监控 API
│   └── 前端监控页面
└── 验证: verify_e2e.py 扩展 + 前端数据源状态页
```

### 2.2 🟡 二级重叠：市场感知 vs 全球指数修复

**涉及的文档**：
- `market-awareness-and-data-source-plan.md` §5（市场感知联动）
- `fix-global-indices-plan.md`

**重叠点**：
- 全球指数链路中的 Stooq 优先级调整在两个文档中都有提及，但细节不同
- `fix-global-indices.md` Fix #5 提议加 Twelve Data + Finnhub 到全球指数链；`market-awareness.md` 提议用 Stooq 替代 yfinance（但没有说把 Twelve Data/Finnhub 加到全球指数链）

**冲突点**：`fix-global-indices.md` Fix #5 和 `market-awareness.md` §4.4 对全球指数链路走向有细微分歧：
- fix-global-indices: Sina → Stooq → TwelveData → Finnhub → Yfinance
- market-awareness: Sina → Stooq（不再 fallback 到 Yfinance，也不提 TwelveData/Finnhub）

**修复建议**：以 fix-global-indices 的链路为准（更完整的多层降级）。统一链路：
```
_FOREIGN 链路 (统一):
Sina(4s) → TwelveData(6s) → Finnhub(6s) → Stooq(8s) → placeholder
```

### 2.3 🟡 范围重叠：板块概念优化与 LLM 报告增强

**涉及的文档**：
- `sector-concept-optimization-plan.md`（全链路 6 Phase）
- `design-report-optimization-plan.md`（C1 全市场净流入信号）

**重叠点**：
- sector-concept Phase 4 涉及 LLM prompt 注入（`llm.py` 中的 `_build_design_report_prompt`）
- design-report-optimization 也涉及 `_build_design_report_prompt` 的数据增强

**冲突**：无直接冲突，但 sectors Phase 4 中"热点板块排行"段落的注入位置必须与 design-report 优化后的 prompt 结构兼容。

**修复建议**：先做 sector-concept Phase 1-2（数据采集+缓存），再做 Phase 4（LLM prompt）。design-report 的 C1 可独立实施。

### 2.4 🟢 无实质冲突但有依赖：前端三个优化方案

**涉及的文档**：
- `frontend-ui-optimization-plan.md`
- `frontend-performance-optimization.md`
- `frontend-testing-safety-net.md`

**关系**：这三个文档相互独立无冲突，但实施顺序有依赖建议：
1. **先做 testing**（给 UI 重构提供安全网）
2. **再做 performance**（`main.js` 删一行即可，极低成本高收益，与 UI 不冲突）
3. **再做 UI 优化**（需要测试防护来防止回滚重演）

### 2.5 🔴 方案已被替代的文档

| 文档 | 替代状态 | 替代者 |
|------|---------|--------|
| `review-20260720.md` | 仅为评审报告，非实施方案 | N/A |

---

## 3. 修复方案

### 3.1 冲突修复：数据源改造三合一

创建统一的 `docs/roadmap-data-source-unified.md`，替代 `source-registry-optimization-plan.md` + `data-source-monitoring-plan.md` + `market-awareness-and-data-source-plan.md` §4。

**解决思路**：
1. 以 `source-registry-optimization-plan.md` 为核心骨架（因为它最接近现有代码结构）
2. 吸收 `market-awareness §4` 的 Stooq 路由作为 Phase 1
3. 吸收 `data-source-monitoring` 的 event store 作为 Phase 4+

### 3.2 冲突修复：全球指数链路统一

在 `fix-global-indices-plan.md` 中更新链路为：
```
Sina(4s) → TwelveData(6s) → Finnhub(6s) → Stooq(8s) → placeholder
```
并以该链路为基准实施。

### 3.3 重复归档

将以下已被替代的文档标记为「已归档——被 XXX 替代」：

| 文档 | 标记 | 替代文档 |
|------|------|---------|
| `review-20260720.md` | 评审记录 | N/A |

### 3.4 增量阶段划分建议

建议将 section-concept 和 design-report-optimization 的 LLM prompt 改动协调为：
- Sector Phase 1-2（数据采集 + 缓存）→ **无冲突**，独立实施
- Sector Phase 4（LLM prompt）+ design-report C1（净流入信号）→ **同步实施**，统一修改 `llm.py`

---

## 4. 分阶段实施路线图

### Phase 0 — 快速胜利（独立，极低成本）

| # | 任务 | 源文档 | 预估工时 | 说明 |
|---|------|--------|---------|------|
| 0.1 | GlobalIndicesStrip 加 onMounted | fix-global-indices-plan.md | 0.5h | 1 行 import + 1 行调用，解决"永远空" |
| 0.2 | get_global_indices() 加 try/except | fix-global-indices-plan.md | 0.5h | 防止 500 |
| 0.3 | 修复缓存语义 (update → 全量赋值) | fix-global-indices-plan.md | 0.5h | 3 行改动 |
| 0.4 | main.js 移除 ECharts 全局 import | frontend-performance-optimization.md | 15min | 删 1 行，首屏省 ~500KB |
| 0.5 | GlobalIndicesStrip 补 CSS 样式 | fix-global-indices-plan.md | 0.5h | 组件样式缺失 |

**验证**: verify_e2e.py + 浏览器打开 Dashboard 确认全球指数可显示

### Phase 0.5 — 核心链路修复（P0，数据管道 + 策略检查 + 历史记录）

**来源**: `optimization-plan-20260721.md`

**目标**: 修复智能组合设计/策略检查/历史记录三大核心功能的 P0/P1 阻塞问题

| # | 任务 | 文件 | 改动 | 预估工时 |
|---|------|------|------|---------|
| 0.5.1 | ETF 缓存 TTL 修正 + last-good 兜底 | `etf_scanner.py` | `CACHE_TTL.get("etf_scanner", 120)` → `CACHE_TTL["etf_list"]`；模块级 `_last_good_etfs` 兜底 | 1h |
| 0.5.2 | East Money 直连 HTTP 新数据源 | `etf_scanner.py` | 新增 `_fetch_em_etf_list()` 直连东方财富 push2 API 获取全量 ETF 列表 | 2h |
| 0.5.3 | akshare timeout 延长 + ETF 缓存预热 | `etf_scanner.py` + `main.py` | ak 超时 8→25s；启动时 `_warmup_etf_cache()` | 0.5h |
| 0.5.4 | 策略检查 taskStatus props 补齐 | `DashboardAiTools.vue` | `StrategyCheckResult` 加 `task-status` / `task-progress` / `task-stage` prop 传递 | 1h |
| 0.5.5 | task.error → task.error_message 兼容 | `DashboardAiTools.vue` + `strategy_check_worker.py` | 前端读 `task.error_message || task.error || fallback`；后端 worker 从 `task.params` 读 `portfolio_type` | 1h |
| 0.5.6 | 历史记录 Promise.all 加 catch 隔离 | `DashboardAiTools.vue` + `portfolio.py` | `Promise.all([...].map(p => p.catch(...)))`；`list_strategy_checks` 加异常保护 | 1h |
| 0.5.7 | 模型新增 status/error_message 字段 | `portfolio_design.py` + `task_manager.py` | `PortfolioDesign.status` / `error_message`；保存时写入状态；路由返回 status | 1.5h |
| 0.5.8 | 前端历史记录状态徽标 + 运行中合并 | `DesignHistory.vue` + `DashboardAiTools.vue` | 状态徽标渲染；`loadHistoryList` 合并 running 任务；`onHistorySelect` 类型分发 | 2h |

**验证**:
- 设计生成：输入金额 → 生成三套方案 → 自动跳转结果页
- 策略检查：弹窗选择组合类型 → 不白屏 → 不超时 → 按所选组合执行
- 历史记录：加载不因任一路径失败整体白屏；状态徽标正确显示

### Phase 1 — 数据层修复（P0 阻塞）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 1.1 | Sector 数据采集扩容（行业+概念 concurrent） | sector-concept Phase 1 | 4h | 无 |
| 1.2 | PoolManager sector_cache 写入入口 | sector-concept Phase 2 | 3h | 1.1 |
| 1.3 | APScheduler 新增 60s 板块刷新任务 | sector-concept Phase 2 | 1h | 1.2 |
| 1.4 | CSS 变量补齐（--color-primary 等别名） | frontend-ui-optimization Phase 1 | 0.5h | 无 |
| 1.5 | section-card 嵌套 CSS 消除 | frontend-ui-optimization Phase 1 | 0.5h | 无 |

**验证**: LLM 报告不再显示"暂无板块热力数据"；所有页面 CSS 变量正确渲染

### Phase 2 — 质量防护网

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 2.1 | AppButton/AppCard/AppTabs/AppInput/AppModal 单测 | frontend-testing-safety-net Phase A | 4h | 无 |
| 2.2 | useDashboardData composable 单测 | frontend-testing-safety-net Phase B | 1h | 无 |
| 2.3 | E2E spec 扩充到 10-15 条 | frontend-testing-safety-net Phase B/C | 6h | 无 |
| 2.4 | verify_e2e.py 全局指数检查修复 | fix-global-indices-plan 根因 #7 | 0.5h | 无 |

**验证**: `npm test` 全绿 + `npm run test:e2e:smoke` 全绿

### Phase 3 — 前端 UI 重构（重新实施，防回滚）

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 3.1 | Dashboard 手工 card → AppCard（7 区块） | frontend-ui-optimization Phase 2 | 4h | 2.1 (测试防护) |
| 3.2 | Dashboard 手工 tab → AppTabs | frontend-ui-optimization Phase 2 | 1h | 2.1 |
| 3.3 | PortfolioAnalysis tab → AppTabs | frontend-ui-optimization Phase 2 | 1h | 同上 |
| 3.4 | TokenMonitor / MarketAnalysis / DesignResult tab → AppTabs | frontend-ui-optimization Phase 2 | 2h | 同上 |
| 3.5 | Vite chunk 优化（vendor-vue/axios/echarts 分层） | frontend-performance Step 2 | 0.5h | 无 |
| 3.6 | 各页面 ECharts 清理重复注册 | frontend-performance Step 3 | 1h | 0.4 |

**验证**: 逐页面视觉验证 + `npm test` 全绿 + `npm run build` 确认 chunk 拆分

### Phase 4 — 数据源系统改造

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 4.1 | 美股 `_route_us_stooq()` 新链路 | market-awareness §4.1 | 2h | 无 |
| 4.2 | 全球指数链路统一 + TwelveData/Finnhub 加入 | fix-global-indices Fix #5 | 2h | 无 |
| 4.3 | China market 3 核心函数接入 SourceRegistry | source-registry P0-A | 3h | 无 |
| 4.4 | price=0 过滤前置修复 | source-registry §4.1 | 1h | 无 |
| 4.5 | 补齐 5 个健康探针 | source-registry P0-B | 2h | 无 |
| 4.6 | SourceRegistry 加 on_event 回调 | data-source-monitoring §5.2 | 1h | 无 |

**验证**: verify_e2e.py + 长稳运行观察降级是否正常工作

### Phase 5 — 市场感知联动

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 5.1 | 后端 MarketContext 路由层 | market-awareness §5.2 | 6h | 4.1-4.3 |
| 5.2 | MarketReport market prop 传递 | market-awareness §5.3 | 2h | 5.1 |
| 5.3 | AiAdvisor market 上下文 | market-awareness §5.3 | 2h | 5.1 |
| 5.4 | 组合设计 market 参数 | market-awareness §5.3 | 2h | 5.1 |
| 5.5 | LLM prompt 市场上下文注入 | market-awareness §5.4 | 2h | 5.1 |

**验证**: 切换到美股 Tab → 所有功能使用美股数据

### Phase 6 — 可观测性与系统增强

| # | 任务 | 源文档 | 预估工时 | 前置依赖 |
|---|------|--------|---------|---------|
| 6.1 | SourceEventStore（source_events 表 + API） | data-source-monitoring §5.1 | 6h | 4.6 |
| 6.2 | 前端数据源监控页面 | data-source-monitoring §7 | 4h | 6.1 |
| 6.3 | ConfigManager + app_config 表 | config-management §4.1-4.3 | 4h | 无 |
| 6.4 | 前端 ConfigPage | config-management §5 | 4h | 6.3 |
| 6.5 | Sector API 实时行情返回 | sector-concept Phase 3 | 3h | 1.1 |
| 6.6 | LLM prompt 热点板块注入 | sector-concept Phase 4 | 2h | 1.2 + 1.3 |

**验证**: 数据源状态页可查 + 配置页读写正常 + 板块数据实时行情带涨跌颜色

### Phase 7 — 远期优化

| # | 任务 | 源文档 | 说明 |
|---|------|--------|------|
| 7.1 | Factor IC 追踪器激活 | factor-model-extension | 评估是否需要更多因子，不急于实施 |
| 7.2 | 排版令牌迁移 | frontend-ui-optimization Phase 3-4 | 视觉效果深化 |
| 7.3 | SVG 图标替换 emoji | frontend-ui-optimization Phase 3 | 美观度提升 |
| 7.4 | 响应式补齐 | frontend-ui-optimization Phase 4 | 移动端适配 |

---

## 5. 附录：各方案摘要

### 5.1 文档状态速查表

| 文档 | 类型 | 状态 | 改行数 | 影响模块 |
|------|------|------|-------|---------|
| config-management-plan.md | 实施方案 | ❌ 未实施 | ~400 行 | 后端 admin + 前端 ConfigPage |
| data-source-monitoring-plan.md | 实施方案 | ❌ 未实施 | ~500 行 | 后端 monitor + 前端 + DB |
| design-optimization-plan.md | 实施方案 | ✅ 已实施 | - | strategy_design + engine/ |
| design-report-optimization-plan.md | 实施方案 | ⚠️ 部分 | ~100 行 | llm.py + design_report.py |
| e2e-testing-plan.md | 实施方案 | ❌ 未实施 | ~800 行 | frontend/e2e/ spec 文件 |
| factor-model-extension-plan.md | 实施方案 | ⚠️ 部分 | ~200 行 | factor_registry.py |
| five-improvements-plan.md | 实施方案 | ⚠️ 部分 | ~60 行 | risk_controls.py |
| fix-global-indices-plan.md | 修复方案 | ❌ 未实施 | ~50 行 | market_service + GlobalIndicesStrip |
| frontend-architecture-refactor.md | 实施方案 | ✅ 已实施 | - | 全部前端组件 |
| frontend-performance-optimization.md | 优化方案 | ❌ 未实施 | ~15 行 | main.js + vite.config.js |
| frontend-testing-safety-net.md | 测试方案 | ❌ 未实施 | ~400 行 | frontend/test + e2e |
| frontend-ui-optimization-plan.md | 优化方案 | ❌ 已回滚 | ~200 行 | 全部前端视图 |
| issues-analysis-report.md | 问题分析 | ✅ 已修复 | - | 全局 |
| market-awareness-and-data-source-plan.md | 实施方案 | ❌ 未实施 | ~500 行 | 路由 + Service + LLM |
| optimization-plan-20260721.md | 实施方案 | ❌ 未实施 | ~80 行 | etf_scanner + strategy_check_worker + DesignHistory + 前端 DashboardAiTools |
| review-20260720.md | 评审报告 | N/A | - | N/A |
| sector-concept-optimization-plan.md | 实施方案 | ❌ 未实施 | ~300 行 | market_trends + pool_manager + llm.py |
| source-registry-optimization-plan.md | 实施方案 | ❌ 未实施 | ~70 行 | china_market + main.py |

### 5.2 冲突汇总

| 冲突 | 涉及文档 | 重要性 | 解决方式 |
|------|---------|--------|---------|
| 数据源改造三文档抢同一代码域 | source-registry + data-source-monitoring + market-awareness §4 | 🔴 | 合并为统一实施方案 |
| 全球指数降级链分歧 | fix-global-indices vs market-awareness | 🟡 | 统一链路 Sina→TwelveData→Finnhub→Stooq→placeholder |
| LLM prompt 被两文档同时修改 | sector-concept Phase 4 + design-report-optimization C1 | 🟡 | 同步实施，统一修改 llm.py |
| UI 重构曾回滚，需要测试防护 | frontend-ui-optimization + frontend-testing-safety-net | 🟡 | 先做 testing 再做 UI |

### 5.3 关键依赖图

```
Phase 0 (快速胜利)         独立，无依赖
    │
    ▼
Phase 1 (数据层修复)      独立但后续被消费
    │                      sector cache → Phase 6 LLM prompt
    ▼
Phase 2 (测试安全网)       为 Phase 3 提供防护
    │
    ▼
Phase 3 (前端 UI 重构)     依赖 Phase 2 测试防护
    │
    ▼
Phase 4 (数据源改造)       独立，为 Phase 5 提供前提
    │
    ▼
Phase 5 (市场感知联动)     依赖 Phase 4 数据源改造
    │
    ▼
Phase 6 (可观测性增强)     独立或依赖 Phase 4
    │
    ▼
Phase 7 (远期优化)        无紧急依赖
```

---

## 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-22 | 初次生成，覆盖全部 18 份文档 |
