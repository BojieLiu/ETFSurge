# Archived / 归档文档

本目录存放**已完成使命**的历史文档（诊断计划、评审产物、交接、根因分析），保留审计价值但不再作为活跃依据。

## 归档原则
- **已实施完成的计划**：如 `round2`-`round9` 各轮诊断与优化计划（round9 于 commit `b2fd04c` 落地；round8 的 O 项 + interaction/theme 重设计于 commit `b300bfa` 落地；round7 于 `3c7906d`、round6 的 F/R 项于 `0c78db8`）——活跃计划见 `docs/round10/round11/round12` 三份
- **一次性诊断/评审产物**：方案评审（design_225/227、combination-design-review 等）、diag 日志（`logs/diag/*`、`diag/out/*` 迁入）、单标的诊断输出
- **被后续轮次覆盖的交接/根因**：`handoff.md`（2026-07-25）、`ROOT_CAUSE.md`
- **不归档**：`api-contracts/`（活跃契约）、`backend/app/analysis/prompts/`（运行时）、`.sisyphus/`（工具私有状态）、README/AGENTS（项目说明）、`docs/round10-container-rediagnosis.md`（活跃待实施）、`docs/round11-code-redundancy.md`（活跃待实施）、`docs/round12-implementation-plan.md`（活跃待实施）

## 最近一次归档（2026-08-09，round9 实施完成后）
并入本目录：
- `round9-container-rediagnosis.md`（round9 容器化全链路复诊断 C1-C5 + P0-P3 47 项，已实施，commit `b2fd04c`；被 round10/11/12 以文本引用，无路径依赖）

> 归档后引用统一指向 `docs/archived/round9-container-rediagnosis.md` 等（仓库根相对路径）。

> **活跃计划（未实施）**：`docs/round10-container-rediagnosis.md`、`docs/round11-code-redundancy.md`、`docs/round12-implementation-plan.md`（三者互引，须留根目录）。

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
