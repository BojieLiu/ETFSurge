# Archived / 归档文档

本目录存放**已完成使命**的历史文档（诊断计划、评审产物、交接、根因分析），保留审计价值但不再作为活跃依据。

## 归档原则
- **已实施完成的计划**：如 `round2`-`round8` 各轮诊断与优化计划（round8 的 O 项 + interaction/theme 重设计于 commit `b300bfa` 落地；round7 于 `3c7906d`、round6 的 F/R 项于 `0c78db8`）——活跃计划见 `docs/round9-container-rediagnosis.md`
- **一次性诊断/评审产物**：方案评审（design_225/227、combination-design-review 等）、diag 日志（`logs/diag/*`、`diag/out/*` 迁入）、单标的诊断输出
- **被后续轮次覆盖的交接/根因**：`handoff.md`（2026-07-25）、`ROOT_CAUSE.md`
- **不归档**：`api-contracts/`（活跃契约）、`backend/app/analysis/prompts/`（运行时）、`.sisyphus/`（工具私有状态）、README/AGENTS（项目说明）、`docs/round9-container-rediagnosis.md`（待实施计划）

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
