# Archived / 归档文档

本目录存放**已完成使命**的历史文档（诊断计划、评审产物、交接、根因分析），保留审计价值但不再作为活跃依据。


## 最近一次归档（2026-10-03，round61 容器全链路诊断收尾）

并入本目录（逐项核对「§决策点是否全闭/已转出」+「全仓路径引用数」后判定）：
- `round56-container-reacceptance-round55-fixes.md`（round56 容器复验 + round55 实施批复）
  —— **归档依据**：§6 全部 10 个决策点已闭或已转出并记录在 round57 §4.3：
  #1 R191 → round57 §2.5 维持关闭；#2 DOC-1 → 已实施进常驻模板；#3 patrol → round57 §2.8 已跑；
  #4 P1-5 → 活跃身份迁至 `round35-architecture-review.md` + `round36-B5-allocate-pipeline.md` +
  `redundant-review.md`（不再依赖 round56）；#5 四态走查 → round57 §2.8；#6 Lighthouse → round57 §2.8
  → round61 §2.8 复测；#7 性能债基线 → round57 §2.1 重建 → round61 §2.1 复测；
  #8 R192/D → round57 §2.2 生产实证关闭；#9 R194-G → round57 §2.4 半生效转 R199 → round61 已实施；
  #10 R195-H → round57 §2.3 后端就绪 → round61 §2.4 复验 CASH 行三方案齐。
  **路径引用数 = 0**（16 处「round56 §x」短名引用经逐一核对均为散文/注释语义指针，非 `docs/` 路径）。
- `v7-p2-dsh-harness-comparison.md`（v7 P2 第三方 Harness `dsh` 探针记录）——一次性调研产物，
  **全仓外部引用数 = 0**（唯一引用来自同为调研产物的 v7-p1.5，未构成活跃语义）。
- `evals-report.md`（Agentic Evals 10 用例 100% 快照，2026-08-30）——**可重生成产物**
  （`python -m scripts.evals.report --out <path>`），数据已过期于 HEAD。

> **引用同步**：`backend/scripts/evals/report.py:6` 的用法示例由 `--out docs/evals-report.md`
> 改为 `--out <path.md>` 并加注「历史快照已归档至 docs/archived/evals-report.md」
> （该参数 `default=None`，脚本本身不会写归档路径，故仅改文档字符串）。
> `docs/round57-*.md` 头部补「归档提示」段，声明其 round56/55 引用指归档件。
> 代码注释与契约中的「round56 §4.2 方案D/G/H」「round56 §6#n」等**短名引用按既有惯例未改写路径**
> —— 与 2026-09-18 归档 round53/54/55 时的处理一致（那批同样保留 35/8/9 处短名引用）。
> 改写它们需触碰 15+ 代码/契约/前端文件并使 pre-commit 文档短路失效，收益仅是路径可点击。
>
> **不归档保留于 `docs/` 顶层**（本轮逐份核对引用数后维持）：
> `round61-container-fullchain-diagnosis.md`（当前轮）、`round57`（12 处引用 + round61 对照基准）、
> `round58-market-report-missing-data.md`（30 处引用）、`round58-portfolio-design-llm-fix.md`（5 处 `docs/` 路径引用：
> `backend/app/engine/budgets.py:237`、`allocation_engine.py:2011`、`known-env-issues.md:100` + 2 测试）、
> `round59-advice-technical-support-level.md`（21 处引用 + round61 对照基准）、
> `advice-goldset-design.md`（=round60，19 处引用，含 goldens 与 2 个 goldset 测试）、
> `round35-architecture-review.md`（**40 处引用**，engine/factors/core/pytest.ini/audit_async_blocking + 20 测试）、
> `round36-B5-allocate-pipeline.md`（4 处：`allocation_engine.py`、`core/loop_watchdog.py`、
> `probe_design_pipeline_profile.py`、`known-env-issues.md`）、`redundant-review.md`（11 处，含 **AGENTS.md**、
> `check_test_baseline.py`、`verify_e2e.py`）、`etfsurge-agentic-upgrade-v7.md`（6 处代码/测试引用）、
> `v7-p1.5-langgraph-comparison.md`（**记录的决策仍生效**：`app/agentic/lg_agent.py` 在生产 + 3 测试在跑，
> 属「why we did it this way」类内容）、`engine-dedup-layers.md`（round57 引用 + 自身「结论」节 3 项待做未闭）、
> `design-checklist.md`（常驻设计清单）、`known-env-issues.md`（常驻环境问题档案）、
> `patrol-orchestration-plan.md`（常驻流程）、`prompt-templates/`（常驻模板）、`api-contracts/`（活跃契约）、
> README/AGENTS（项目说明）。
>
> ⚠️ **本轮附带修复（2026-10-03）**：上一会话对 round53/54/55 的归档处于**半完成态**——
> 文件已移入本目录且内容逐行一致（383/157/230 行），但 git 未 stage（` D` + `??`）。
> 若当时执行 `git commit -a`（不含 untracked），会提交删除而不含新增 → **三份文档从仓库消失**。
> 已 `git add` 修正，git 现识别为 rename（`R`）。**教训**：归档必须用 `git mv` 并确认
> `git status --porcelain` 显示 `R` 而非 `D`+`??`。


## 最近一次归档（2026-09-18，round56 复验完成 + round53/54/55 承接映射收敛后）

并入本目录（均已完成使命，无活跃实施依据身份）：
- `round53-container-reacceptance-round52-plans.md`（round53 round52 A-F 落地复验：R170/R171/R172/R173/R175/R176/R177/R178 实测生效；遗留 R146/R173-A 由 §12 闭环，其余迁 round55 §0.2；R181/R183/R185-A/B 方案已被代码实施并由测试锁定）
- `round55-container-reacceptance-round53-plans.md`（round55 round53 实施批 + round54 抛光复验：R181 无复发、R177/R178/R173 维持；新发现 R186/R187/R188 已由 round56 §0 #2-4 生产实证关闭，R189/E′关闭，R191 经 09-14 交易时段复测消散；仅剩 R192/R195 转 round56/新轮跟踪）
- `round54-frontend-polish.md`（round54 前端 UI 打磨：代码已落地 `7c062b6/f59fb17`，vitest 552 绿 + build 绿；剩余浏览器四态走查已迁 round56 §6 跟踪项 #5，不再以本文档为活跃依据）

> 归档后引用统一指向 `docs/archived/...`。**同步更新**：`backend/tests/test_chat_session.py:2`、`backend/tests/test_large_cap_wide_basis_exclusion.py:482`、`backend/tests/test_r185a_config_hot_reload.py:2`、`backend/tests/test_r185b_config_surface.py:1`、`backend/app/core/market_calendar.py:84/109`、`frontend/src/test/FactorModelView.spec.js:200` 六处硬路径 `docs/round53-*.md` → `docs/archived/round53-*.md`；`round55 §8.3` 内对 `docs/round54-frontend-polish.md` 的引用 → `docs/archived/round54-frontend-polish.md`。代码注释中「round53 §x」「round55 §x」为语义指针，移动后仍可读。
> 不归档保留于 `docs/` 顶层：`round56-container-reacceptance-round55-fixes.md`（当前活跃，R192/R195 待实施 + R193/R194 设计约束）、`round35-architecture-review.md`（P1-5/B5 拆分依据仍活跃）、`round36-B5-allocate-pipeline.md`（P1-5 独立轮未启动）、`design-checklist.md`（常驻设计清单）、`engine-dedup-layers.md`（仍被代码引用）、`known-env-issues.md`（常驻环境问题档案）、`patrol-orchestration-plan.md`（常驻流程）、`prompt-templates/`（常驻模板）、`api-contracts/`（活跃契约）、`redundant-review.md`（P1-5 + R185-C 未闭）、`etfsurge-agentic-upgrade-v7.md`（v7 规格仍被代码引用）、`v7-p1.5-langgraph-comparison.md` / `v7-p2-dsh-harness-comparison.md`（现行决策依据）、`evals-report.md`（evals 输出目标）、README/AGENTS（项目说明）.

## 最近一次归档（2026-08-30，round39 容器全链路复验完成 + 五份旧 round 文档承接映射收敛后）

并入本目录（均已完成使命，无活跃实施依据身份）：
- `round34-b7-ia-reorg-subplan.md`（round34 B7 全域 IA 重组子方案 v2 ——"待最终批准"状态已 12+ 天无新引用；其方案内容已被 round35 架构评估 / round49 FE5 / round38 实证实施结果取代）
- `round34-container-reacceptance-r102-r108.md`（round34 R102 容器内首验 + 新发现 R103-R108 修复方案 + T-A/S-A/M-A 讨论级设计；R103-R108 已由 round37 三小时长稳实证 + round38 R139/R146/R147-FIX/R148/R149/R150 实施并承接）
- `round37-container-reacceptance-r103r108-b5s19.md`（round37 R103-R108 长稳态 + R129-R138 新发现；已被 round38 三小时长稳验证 + round39 跨文档对照承接）
- `round38-container-reacceptance-verify.md`（round38 R139-R151 + R143/R146/R147-FIX 复验；已被 round39 §0-§9 全面验证矩阵 / §10 测试合并方案承接）

> 归档后引用统一指向 `docs/archived/...`。**同步更新**：`docs/round35-architecture-review.md` 第 404 行一处硬路径引用 `docs/round34-container-reacceptance-r102-r108.md` → `docs/archived/round34-container-reacceptance-r102-r108.md`（加"2026-08-30 归档"标注）。代码侧、测试 docstring、其他文档无硬路径引用（"round34 §X"语义指针移动后仍可读）。
> 不归档保留于 `docs/` 顶层：`round39-container-reacceptance-r34-r38.md`（当前活跃轮文档，§0-§10 完整方案入档）、`design-checklist.md`（常驻设计清单）、`engine-dedup-layers.md`（round35 B3-S3 契约文档，仍被业务引用）、`known-env-issues.md`（常驻环境问题档案，引用 round36 §1.1）、`patrol-orchestration-plan.md`（常驻流程）、`prompt-templates/`（常驻模板）、`api-contracts/`（活跃契约）、README/AGENTS（项目说明）。

## 最近一次归档（2026-09-13，round55 容器全链路复验完成 + round39/51/52 承接映射收敛后）

并入本目录（均已完成使命，无活跃实施依据身份）：
- `round39-container-reacceptance-r34-r38.md`（round39 全面验证矩阵 + §5 决策 5 项；待复测 R146–R150 已由 round53 §12 闭环，R143 已由 round51 §0.2 实测修正 ✅，遗留 R152/P0 已随 round53 批次落地）
- `round51-container-reacceptance-r39-v7.md`（round51 方案 A–F 已实施 `a9f704d` 且 round52 §0.2 实测生效；遗留 5 项：R146→§12 关闭、off_exchange→round55 §0.2、patrol→§6#4 规则关闭、R141→R171 落地关闭、R168→64 条关闭）
- `round52-container-reacceptance-round51-plans.md`（round52 13 项矩阵由 round53 §4.3 全部闭合；方案 A–F 已实施 `a83cd9f` 且 round53 §0.1 实测生效；遗留已迁 round53 §6）

> 归档后引用统一指向 `docs/archived/...`。同步更新：**无**（全仓无 `docs/round39-*.md` / `docs/round51-*.md` / `docs/round52-*.md` 硬路径引用；代码注释中「round51 §x」「round52 §x」为语义指针，移动后仍可读）。
> 不归档保留于 `docs/` 顶层：`round53-container-reacceptance-round52-plans.md`（当前活跃，§6 决策待拍板 + R186 系列引用）、`round54-frontend-polish.md`（四态走查 pending）、`round55-container-reacceptance-round53-plans.md`（当前轮）、`design-checklist.md`（常驻设计清单）、`engine-dedup-layers.md`（仍被代码引用）、`known-env-issues.md`（常驻环境问题档案）、`patrol-orchestration-plan.md`（常驻流程）、`prompt-templates/`（常驻模板）、`api-contracts/`（活跃契约）、`redundant-review.md`（P1-5 + R185-C 未闭）、`etfsurge-agentic-upgrade-v7.md`（v7 规格仍被代码引用）、`v7-p1.5-langgraph-comparison.md` / `v7-p2-dsh-harness-comparison.md`（现行决策依据）、`evals-report.md`（evals 输出目标）、README/AGENTS（项目说明）。

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
