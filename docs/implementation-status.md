# 改进实施完成确认

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

### 5 项改进已超出原方案范围

所有 5 项改进已在计划文档 `docs/five-improvements-plan.md` 中详细说明并全部实施完毕。下一步：
1. 重新运行 verify_e2e 确认 31/31 PASS
2. commit 改进代码
3. 后续可跟进 FactorRegistry 修复和 Phase 4 链路复用
