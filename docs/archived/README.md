# Archived / 归档文档

本目录存放**已完成使命**的历史文档（诊断计划、评审产物、交接、根因分析），保留审计价值但不再作为活跃依据。

## 最近一次归档（2026-08-22，round34 容器复验完成 + round33 §8 R102 已实施并容器内首验通过后）
并入本目录（均已完成使命，无活跃实施依据身份）：
- `round33-container-reacceptance-r99-r101.md`（round33 R99-R101 复验全 PASS + §8 R102 方案；R102 已由 commit `38a194d` 实施、round34 全新镜像容器内首验 PASS——distinct trade_date 245→502、census warn=12/no_data=15 与本地一致、重启幂等）
> 归档后引用统一指向 `docs/archived/...`。同步更新：**无**（全仓无 `docs/round33-*.md` 硬路径引用；代码注释中「round33 §8」为语义指针，移动后仍可读）。
> 不归档保留于 `docs/` 顶层：`round34-container-reacceptance-r102-r108.md`（当前活跃，R102 首验结论 + 新发现 R103-R108 修复方案 + T-A/S-A/M-A 讨论级设计待实施）、`design-checklist.md`（常驻设计清单）、`patrol-orchestration-plan.md`（常驻流程）、`prompt-templates/`（常驻模板）、`api-contracts/`（活跃契约）、README/AGENTS（项目说明）。

## 最近一次归档（2026-08-21，round33 容器复验完成 + round32 R99-R101 实施并容器内复验生效后）
并入本目录（均已完成使命，无活跃实施依据身份）：
- `round30-container-reacceptance-and-optimization.md`（round30 容器复验+优化：R85-R92 诊断/实施，已被 round31 R93-R98 与 round32 R99-R101 承接并实证）
- `round31-container-reacceptance-r93-r98.md`（round31 R93-R98 复验：data_dir 绝对路径/动量跨路径/报告数值一致性/valid_rate 拆分/个股搜索兜底/资讯摘要；已被 round32 实施承接）
- `round32-container-reacceptance-r99-r100.md`（round32 R99-R101 修复设计：momentum 剔静态政策因子/因子质量产出率口径两维/宽基软上限≤4；已由 commit `a60f173` 实施、round33 全新镜像容器内复验全 PASS）
> 归档后引用统一指向 `docs/archived/...`。同步更新：**无**（全仓无 `docs/round3[0-2]*.md` 硬路径引用；模板示例 `round31-xxx.md` 为占位符，保留于 AGENTS.md / prompt-templates/container-fullchain-diagnosis.md 不需改）。
> 不归档保留于 `docs/` 顶层：`round33-container-reacceptance-r99-r101.md`（当前活跃，R99-R101 复验结论 + 待复测项 R95/E1/E2/E3）、`design-checklist.md`（常驻设计清单）、`patrol-orchestration-plan.md`（常驻流程）、`prompt-templates/`（常驻模板）、`api-contracts/`（活跃契约）、README/AGENTS（项目说明）。

## 最近一次归档（2026-08-16，round25 验收完成 + round23/24 被 round25 承接后）
并入本目录（均已完成使命，无活跃实施依据身份）：
- `round23-system-audit-optimization.md`（round23 系统审计设计文档：P0 正确性 12 项 F7-F28 + 架构 6 项已在 round23/24 落地并实证；残余 F1/F2/F3/F13/F21/E1/F11/T3 已由 round24 R1-R26 与 round25 R27-R39 承接）
- `round24-reverification-and-fixes.md`（round24 复验审计 + R1-R26 修复设计：26 项已全部实施并推送（d9a734e/98b98a7/8841dda/6b13948/0272150），round25 复验 22 项生效；残余 R6/R7/R9/R10/R17/R25/R26 由 `docs/round25-container-acceptance-and-optimization.md` R27-R39 承接）

> 归档后引用统一指向 `docs/archived/...`。同步更新：`backend/app/routers/factors.py`、`backend/tests/test_f15_f20_data_integrity.py`、`test_f25_ic_daily_pipeline.py`、`test_f31_news_partial.py`、`test_round24_r22_avg_ic.py`、`test_t_series_guards.py`、`api-contracts/portfolio/design-precision.md` 的 docstring/注释路径引用。
> 不归档保留于 `docs/` 顶层：`round25-container-acceptance-and-optimization.md`（当前活跃，R27-R39 达实施标准待实施）、`design-checklist.md`（常驻设计清单）、`test-redundancy-audit-and-plan.md`（测试冗余规划，round24 折叠待执行）。

## 最近一次归档（2026-08-14，round22 落地 + round21 被 round23 覆盖 + round20 合并至 round23 后）
并入本目录（均已完成使命，无活跃实施依据身份）：
- `engine-refactor-spec-round22.md`（round22 引擎重设计实现批次：E1–E5 5/5 落地，commit `3269c8b` + `4eb2d4d`；实现已合流，规格退出活跃）
- `design-portfolio-engine-redesign.md`（round22 引擎重设计 v2 设计规格：#10–#14（INV-1~6）5/5 实现，commit `3269c8b`）
- `round21-container-acceptance-diagnosis.md`（纯诊断文档，声明"本轮未做代码改动"；其未修复项 KDJ超买→BUY / confidence=0.7 / 因子 valid_rate / 美股 hot-rank 已由 round23 §8（F10/F11/F12…）实锤并承接）
- `round20-container-acceptance-diagnosis.md`（纯诊断文档，自声明"本份只设计不实施"；20 项问题中 13 项已在后续 round21/22/23 代码提交中落地、6 项由 round23 §8/§6 跟踪（仅 F35 home CLS 为净新增开放项）；已无活跃实施依据身份，归并至本目录，承接映射见 `docs/round23-system-audit-optimization.md` §11）

> 归档后引用统一指向 `docs/archived/...`。同步更新：`docs/round23-system-audit-optimization.md` §7 三处表格引用、`backend/app/services/strategy_design.py:404` 与 `backend/app/engine/budgets.py:15` 的 docstring 路径引用（均改指 `docs/archived/`）。
> 不归档保留于 `docs/` 顶层：`round23-system-audit-optimization.md`（当前活跃，§10 架构整改未实施）、`design-checklist.md`（常驻设计清单）。

## 归档原则
- **已实施完成的计划**：如 `round2`-`round19` 各轮诊断与优化计划（round19 关联度 P1 于 commit `a842bb2` 落地、round18 于 `a3f6643`、round17 于 `2e5da5c`+`bcee936`、round16 于 `fab74d1`、round14/15 于 2026-08-11 批次、round13 宏观 5 因子于 commit `5a7e336` 落地；round12 全部批次于 2026-08-09 落地；round9 于 commit `b2fd04c` 落地；round8 的 O 项 + interaction/theme 重设计于 commit `b300bfa` 落地；round7 于 `3c7906d`、round6 的 F/R 项于 `0c78db8`）——活跃计划见 `docs/round23-system-audit-optimization.md`
- **一次性诊断/评审产物**：方案评审（design_225/227、combination-design-review 等）、diag 日志（`logs/diag/*`、`diag/out/*` 迁入）、单标的诊断输出
- **被后续轮次覆盖的交接/根因**：`handoff.md`（2026-07-25）、`ROOT_CAUSE.md`
- **不归档**：`api-contracts/`（活跃契约）、`backend/app/analysis/prompts/`（运行时）、`.sisyphus/`（工具私有状态）、README/AGENTS（项目说明）、`docs/design-checklist.md`（常驻设计清单）

## 最近一次归档（2026-08-13，round20 诊断完成、round18/19 落地核对后）
并入本目录：
- `round19-asset-correlation-analysis.md`（round19 组合诊断：关联度/持仓刷新/K线指标副图/成本价买卖重算/板块热度0/导航栏离线/自选技术分析空数据/港股指数补全/美股技术分析数据不足/测试防护盲区复盘；P1 correlation 引擎 + 同指数去重 + 低相关措辞接线已实施 commit `a842bb2`；未落地项 max_correlation 约束等由 round20 §5.2/§8 承接）
- `round18-container-acceptance-diagnosis.md`（round18 容器验收诊断：性能/数据质量/断裂/测试盲区；P0-1~P2-7 方案大部分已实施 `a3f6643`；剩余项 timeline 缓存/D1/D4/D7/D9 由 round20 §5.1/§8 承接）
- `round17-pending-items.md`（round17 待排期项 P2-6/P2-8/P1-2/LLM-1/P3-6，已实施 `2e5da5c`+`bcee936`）
- `round16-container-acceptance-diagnosis.md`（round16 容器验收诊断 P0 22 项 + P1 8 项 + P2 9 项，已实施 `fab74d1`）
- `round15-factor-pool-selection-evaluation.md` / `round15-process-review.md` / `round15-test-guard-baseline.md`（round15 三份：因子池评估/过程审查/测试防护基线，均已实施 2026-08-11）
- `round14-container-acceptance-diagnosis.md`（round14 容器验收诊断 P0-A~P3-J，已实施 2026-08-11）

> 归档后引用统一指向 `docs/archived/roundXX-*.md` 等（仓库根相对路径）。同步更新：`backend/tests/test_round14_*.py`、`backend/tests/test_round15_*.py`、`backend/scripts/verify_perf.py`、`backend/scripts/verify_e2e.py`、`backend/scripts/check_test_baseline.py`、`frontend/src/**`（DashboardAiTools/useMarketSearch/FactorModelView/SummaryCards/p1k-pnl-color.spec 等）的 docstring/注释路径引用。

## 最近一次归档（2026-08-11，round13 实施完成后）
并入本目录：
- `round13-data-source-evaluation.md`（round13 宏观 5 因子 + 两融已实施，commit `5a7e336`/`777cabf`）
- `round12-implementation-plan.md`（round10 47 项 + round11 29 项合并实施计划，§8 writeback 全部批次 2026-08-09 落地）
- `round10-container-rediagnosis.md`（容器化复诊断 47 项方案，经 round12 实施落地；被 round14 以文本引用，无路径依赖）
- `round11-code-redundancy.md` + `round11-code-redundancy-analysis.md`（冗余审计 P0 batch 实施于 `7d09833`，P2 决策定稿、P3 门禁落地）
- `precommit-gating-optimization.md`（门禁优化设计，已实施——.githooks/pre-commit 现 372 行含 docs 短路 + pytest 触发面收紧，round14 §4 核对确认 13 段门禁全落地）

> 归档后引用统一指向 `docs/archived/round10-container-rediagnosis.md` 等（仓库根相对路径）。同步更新：`backend/tests/test_advice_p0a_slots.py`、`backend/tests/test_factor_p0c_stale.py` 的 docstring 路径引用。

## 最近一次归档（2026-08-09，round9 实施完成后）
并入本目录：
- `round9-container-rediagnosis.md`（round9 容器化全链路复诊断 C1-C5 + P0-P3 47 项，已实施，commit `b2fd04c`；被 round10/11/12 以文本引用，无路径依赖）

> 归档后引用统一指向 `docs/archived/round9-container-rediagnosis.md` 等（仓库根相对路径）。

## 最近一次归档（2026-08-07 之后，round8 实施完成后）
并入本目录：
- `round7-rediagnosis.md`（round7 O1-O30 已实施，commit `3c7906d`）
- `round8-rediagnosis.md`（round8 O1-O27 已实施，commit `b300bfa`）
- `interaction-redesign.md`（交互状态机重构，随 round8 `b300bfa` 实施）
- `frontend-theme-redesign.md`（字号/铺满/视觉治理，随 round8 `b300bfa` 实施）

> 归档后引用统一指向 `docs/archived/round7-rediagnosis.md` 等（仓库根相对路径）。

## 最近一次归档（2026-08-04）
并入本目录：
- `round6-diagnosis-and-optimization-plan.md`（已实施，commit `0c78db8`）
- `design_225_review.md` / `design_227_review.md` / `strategy_check_report.md`（原 `data/`）
- `advice_A.md` / `advice_US.md` / `design_307_report.md` / `design_text_368.md` / `report_A.md` / `report_HK.md` / `report_US.md` / `symbol_510050.md` / `symbol_600519.md`（原 `logs/diag/` 与 `diag/out/`）
- `handoff.md`（原仓库根）、`ROOT_CAUSE.md`（原 `backend/tests/`）

> README 中 round6 引用已统一指向 `docs/archived/round6-diagnosis-and-optimization-plan.md`。
