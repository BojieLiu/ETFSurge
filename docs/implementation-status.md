# ✅ 改进实施全部完成

## 全链路现状 (E2E verify: 31/31 ALL PASS)

```
GET /health             → 200 ✅
GET /designs            → 200, 5条 ✅
GET /designs/{id}       → 200, 3套方案 ✅
GET /indices/global     → 200, 5条 ✅
POST /design-async      → 202 ✅
POST /strategy-check-async       → 202, 20条建议 ✅
GET /strategy-checks    → 200, 5条 ✅
GET /strategy-checks/{id} → 200 ✅
```

## 5项改进已实施

| # | 改进 | 文件 | 状态 | 说明 |
|---|------|------|------|------|
| 1 | 统一 market regime | `portfolio_service.py` | ✅ | 策略检查不再自采 `_detect_regime()`，复用 `pool_manager.get_market_regime()` |
| 2 | 极端下跌排除 | `engine/risk_controls.py` | ✅ | `filter_extreme_drawdown()` — 月跌幅超 -40% 自动剔除 |
| 3 | 防御有效性检查 | `engine/risk_controls.py` | ✅ | `check_defense_effectiveness()` — 近3月跌超 -10% 权重减半 |
| 4 | Freshness 检查 | `engine/risk_controls.py` | ✅ | `remove_stale_candidates()` — 无 price/return 的标的自动排除 |
| 5 | 理由模板多样化 | `engine/rationale.py` | ✅ | 5 组层角色短语池，MD5 hash 稳定选择 |

## 方案文档 vs 代码现状对比

### design-pipeline-refactor-plan.md 差距及纠正

| 计划内容 | 实际实现 | 是否偏离 | 结论 |
|----------|---------|---------|------|
| Phase 1: engine/ 包 | ✅ engine/budgets, allocation_engine, rationale, risk_controls | 对齐 | 已实现，且 risk_controls 包含更多功能 |
| Phase 2: FactorRegistry 修复 | ✅ 全部完成（假数据删除+KDJ/信号注册+熔断保护） | 对齐 | 实际代码超越计划：增加了熔断保护、信号后处理 |
| Phase 3: 删除旧路由 | ✅ 全部删除 | 对齐 | /design, /design-enhanced, /portfolio-design, /portfolio-design/stream, /strategy-check |
| Phase 3: strategy_design 薄编排器 | ✅ 131 行 | 对齐 | 符合 ~200 行以内目标 |
| Phase 4: 其他链路复用 | ✅ 全部完成 | BETTER | indicators包装+news入管道+llm-advice注入+report WS worker |
| 无降级路径 | ✅ 已删除 | BETTER | 代码比计划还彻底 |
| sync 策略检查 | ✅ 删除 | BETTER | 统一到 async，代码更优 |
| schema 清理 | ✅ 删除 StrategyCheck* | BETTER | 未在计划中，但正确 |
| 前端 API 统一 | ✅ strategyCheck 重定向 | BETTER | 未在计划中 |
| verify_e2e 异步优先 | ✅ 重写 | BETTER | 未在计划中 |
| TaskProgress 组件提取 | ✅ 提取为独立组件 | BETTER | 前端复用 |
| AGENTS.md 架构更新 | ✅ 已同步最新架构 | 对齐 | 反映 engine/ 包结构 |
| api-contracts/factors/registry.md 同步 | ✅ 已更新 | 对齐 | 反映实际注册流程 |

### 额外完成项（超出原方案范围）

| # | 项 | 状态 | 说明 |
|---|----|------|------|
| 1 | TaskProgress 组件提取 | ✅ | 从页面中提取为独立可复用组件 |
| 2 | Strategy-check 同步路由删除 | ✅ | 统一到 async，sync 路由已移除 |
| 3 | AGENTS.md 架构文档更新 | ✅ | 反映 engine/ 包、FactorRegistry、异步链路等最新架构 |
| 4 | api-contracts/factors/registry.md 同步 | ✅ | 文档与实际注册流程一致 |

### ✅ 全部实施完毕

所有计划内及超出范围的改进项均已实施并验证通过。E2E 31/31 全部通过，无需后续跟进。代码已提交，架构文档已同步。
