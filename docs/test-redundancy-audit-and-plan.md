# 测试冗余审计报告与整理规划

> 生成日期：2026-08-15 ｜ 范围：`backend/tests/`（pytest 套件）+ `logs/`/`backend/_test_*.py`（临时脚本）
> 方法：静态分析（导入目标 / 测试函数名 / 与业务测试的共享符号配对）+ 逐文件读取比对（4 个去重点）。只读，未改动任何文件。
> 状态：**Round 1 修订版**（已达实施标准：每个早期文件给出精确目标文件 + 拆分 + 处置，去重点有裁决证据）。

---

## 1. 现状盘点

| 维度 | 位置 | 文件数 | pytest 收集 | CI/门禁 |
|---|---|---|---|---|
| 业务维度测试 | `backend/tests/test_{design,factor,portfolio,market,...}.py` | 194 | ✅ | ✅ pre-commit |
| round 维度测试 | `backend/tests/test_{round14-24,phase0-5,z03-z29}_*.py` | 42 | ✅ 同属一套 | ✅ pre-commit |
| 临时脚本 | `logs/*.py`、`logs/round*/test_*.py`、`backend/_test_*.py`、`backend/test_deepseek.py` | ~60 | ❌（urllib 手测活服务） | ❌ |

- 全量一次性收集 **1995 个用例** —— 业务与 round 测试在运行层**已是同一套**，感知到的"两套"只是文件名前缀不同。
- `backend/tests/` 是 Python package（`__init__.py` 存在）；**8 个文件**用 `from tests.db_fixtures import ...` 绝对导入共享 fixtures（早期 round 中仅 `phase1`/`phase5` 用到）。
- `logs/` 下所有 `.py` **未被 git 跟踪**（0 tracked），属工作区散落草稿，不影响 CI。

---

## 2. 冗余分析结论

**核心发现：round 测试绝大部分是"独有回归护栏"，并非业务测试的重复拷贝。**

- 对每个 round 文件做"共享符号配对"：其 top 业务 peer 多为**弱匹配**（仅共享 `as`/`app`/`market` 等通用符号），测试函数名几乎完全不同 → 互补覆盖而非重复。
- 跨文件"高重叠"主要是共享核心模块：`FactorRegistry` 被 46 文件引用、`app.engine` 28、`portfolio_service` 26 —— 健康的共享核心多角度测试。
- round 文件间**无大规模复制粘贴**：同名 helper 几乎都是 1 次出现。
- **真正需裁决的重复只在 4 处**（见 §4b），已逐文件读取比对给出证据化裁决。

> 因此"合并"= **明确保留有价值的回归护栏 + 去掉 roundXX 命名噪音 + 清理散落脚本**，而非删除 round 测试。

---

## 3. "早期 round"边界

| 分类 | 文件 | 处置 |
|---|---|---|
| **早期（待折叠，去 roundXX 名）** | round14(3) / round15(5) / round18(3) / round19(6) / round20(3) / round22(2) / phase0-2,5(5) / z03-z29(6) = **33 文件** | 折叠进对应业务测试文件，删原文件 |
| **当前活跃（保留 round24_ 名）** | round24(8) | 暂留，round 关闭后同流程折叠 |

**边界依据**：`round24` 为当前活跃轮（memory 记录 2026-08-15 实施中），`round20/22/23` 已归档/关闭；故除 `round24` 外均为早期。若用户认定某轮仍活跃，可将该轮从 §4 表中抽出保留。

---

## 4. 逐文件处置规划（early round → 精确目标业务文件）

> 动作：`fold`=把测试函数并入目标文件后删原文件（保留函数体 + 来源注释 `# folded from <原文件>: <原因>`）；`prune`=断言已被业务测试完全覆盖、直接删除；`new`=目标不存在、新建模块名文件。
> 多子系统文件**按测试类拆分**到多个目标（见"拆分"列）。

| # | 早期 round 文件 | 子系统 | 精确目标文件 | 拆分 / 动作 |
|---|---|---|---|---|
| 1 | test_phase0_7 | factors/engine/design | `test_factor_registry.py` + `test_design_integration.py` | 因子聚合/去重/行业集中/合并 → factor_registry；design worker 落库 → design_integration。fold |
| 2 | test_phase1_diagnosis_fixes | llm/async/design | `test_system_diagnosis_fixes.py` + `test_llm_prompt_format.py` + `test_design_pipeline_integration.py` | ipv4 monkey/akshare probe/verify_e2e import → system_diagnosis；llm comment/cache → llm_prompt_format；pipeline 状态 → design_pipeline_integration。（含 db_fixtures 导入，搬函数时保留该 import 行）fold |
| 3 | test_phase2a_data_quality | config/factors/sentiment/search | `test_data_source_fallback.py` + `test_decode.py` + `test_sentiment_factors.py` + `test_factor_compute_functions.py` + `test_search_sector_index.py` | 直连禁用/编码 → data_source_fallback+decode；情绪权重 → sentiment_factors；溢价折价 → factor_compute_functions；search hk/us fallback → search_sector_index。fold |
| 4 | test_phase2b_policy_mypy | factors/policy | **new `test_policy_factors.py`**（无现成业务文件） | 五年规划/双循环/政策对齐映射/yaml 定义/mypy 零错。fold/new |
| 5 | test_phase5_architecture | llm-provider/tasks/config | `test_llm_provider_failover.py` + `test_task_db_persistence.py` | provider dataclass/failover → llm_provider_failover；task 生命周期/ttl/prune → task_db_persistence。（含 db_fixtures 导入）fold |
| 6 | test_round14_apply_design_factors | routers/factors(IC) | `test_portfolio_apply_design.py` + `test_factors_router.py` | apply-design 400/契约 → portfolio_apply_design；`_status_of()` 状态判定/MIN_TRADING_DAYS → factors_router。**与 `test_factor_ic_sample_count` 不重复**（后者测序列化）。fold |
| 7 | test_round14_llm_budget_consistency | llm | `test_llm_stream_retry.py` | budget/retries/provider slow within budget。fold |
| 8 | test_round14_p2_market | market/fetchers | `test_watchlist_dirty.py` + `test_market_service_hk.py` | 路由批处理/缓存版本 → watchlist_dirty；us/hk compute/pe_pb → market_service_hk。fold |
| 9 | test_round15_amount_unit | etf_scanner | `test_etf_scanner.py` | 规模单位 wan/yi/快照契约/scale 告警。fold |
| 10 | test_round15_bear_growth_trim | engine/risk | `test_risk_controls.py` | 熊市成长剔除/强制锚豁免/权重守恒/中性 noop。fold |
| 11 | test_round15_composite_scale | factors | `test_factor_compute_functions.py` | 复合分缩放/主导因子/legacy 兼容/pct_rank。fold |
| 12 | test_round15_directional_ic | factors | `test_factor_rsi_consistency.py` | rsi/kdj 超买取反/动量方向/正IC加权/冷启动。fold |
| 13 | test_round15_guard_baseline | fetchers/source | `test_source_page_fixes.py` | 源存活/degraded/akshare 降级。fold |
| 14 | test_round18_p03_p11 | rationale/text | `test_rationale_industry_sanity.py` | 增/减/持平理由文案约束。fold |
| 15 | test_round18_p04 | timeline/database | `test_timeline_joins_tasks.py` + `test_data_health.py` | timeline 缓存/分页 → timeline_joins_tasks；db 计数显著性 → data_health。fold |
| 16 | test_round18_p1_p2 | etf-scanner/realtime | `test_etf_scanner.py` + `test_spot_single_flight.py` | 资产类型归一 → etf_scanner；fill 率/缺价回填 → spot_single_flight。fold |
| 17 | test_round19_batch1 | portfolio/watchlist/broadcast | `test_f15_f20_data_integrity.py` + `test_portfolio_list.py` + `test_portfolio_apply_design.py` | etf 增改/均价股数持久化 → f15_f20_data_integrity；watchlist CRUD → portfolio_list；apply_design 广播 → portfolio_apply_design。fold |
| 18 | test_round19_p1 | correlation/rationale/alloc | **new `test_correlation.py`** + `test_rationale_causal_chain.py` + `test_large_cap_wide_basis_exclusion.py` | correlation.py 纯函数 → **new test_correlation.py**；build_rationale 相关性措辞 → rationale_causal_chain（或 new test_rationale_correlation.py）；_dedup_same_index/_is_large_cap → large_cap_wide_basis_exclusion。fold |
| 19 | test_round19_p3 | portfolio/pnl | `test_portfolio_model.py` + `test_portfolio_etfs_price.py` | 买卖加权/已实现盈亏/adjust → portfolio_model；select_search 回填均价 → portfolio_etfs_price。fold |
| 20 | test_round19_p4 | fetchers/pagination | `test_warmup_perf.py` + `test_china_market_degradation.py` | 分页/push2delay akshare 降级 → warmup_perf；degraded banner → china_market_degradation。fold |
| 21 | test_round19_p8 | fetchers/hk | `test_market_service_hk.py` + `test_hk_em_fetcher.py` | hk 板块/alpha 码/未覆盖 → market_service_hk；a 指数 akshare 链 → hk_em_fetcher。fold |
| 22 | test_round19_p9 | fetchers/tickflow | `test_tickflow_quotes.py` + `test_nav_source_fallback.py` | tickflow kline → tickflow_quotes；us 链降级 → nav_source_fallback。fold |
| 23 | test_round20_engine_fixes | engine(signal/rationale/corr/alloc) | `test_allocation_engine_fixes.py` + `test_risk_controls.py` + `test_rationale_causal_chain.py` + `test_signal_consistency.py` | 见 §4b 点2 详细裁决（按类拆分 + 1 处 prune） |
| 24 | test_round20_strategy_check_p05_p18 | strategy-check/fetchers | `test_strategy_check_timeout.py` + `test_strategy_check_fallback.py` + `test_nav_source_fallback.py` + `test_tickflow_quotes.py` | 15s 超时 → strategy_check_timeout；rule 回退/置信度 → strategy_check_fallback；fetch_history hk 链 → nav_source_fallback；tickflow kline 英文键 → tickflow_quotes。fold |
| 25 | test_round20_timeline_p01 | timeline/cache | `test_timeline_joins_tasks.py` | ttl 缓存/分页 miss/limit 透传。fold |
| 26 | test_round22_e5_correlation_unchecked | strategy_design | `test_strategy_design.py` | correlation_unchecked 标志（交易/非交易窗口）。fold |
| 27 | test_round22_engine_redesign | engine/budgets | `test_allocation_engine_fixes.py` + `test_cash_and_overlap.py` + `test_large_cap_wide_basis_exclusion.py` | profile 规格/层计数/预算上限 → allocation_engine_fixes；现金上限 → cash_and_overlap；层计数单调 → large_cap_wide_basis_exclusion。fold |
| 28 | test_z03_factors_active | factors | `test_factor_registry.py` + `test_factors_router.py` | 静态/计算因子状态 → factor_registry；active 端点契约 → factors_router。fold |
| 29 | test_z05_ssl_pool | fetchers/conn-pool | **new `test_connection_pool.py`**（无现成业务文件） | 共享 client 单例/http_get_json/连接池统计/admin 路由。fold/new |
| 30 | test_z11_degradation | strategy_design | `test_strategy_design.py` + `test_design_integration.py` | 空池静态模式/降级 → strategy_design；pipeline 异常回退 → design_integration。fold |
| 31 | test_z25_stock_hot_rank | sector/enrich | `test_sector_stocks_mapping.py` + `test_market_data_hub_pool.py` | 行业映射 → sector_stocks_mapping；batch 行业优先/enrich 失败 → market_data_hub_pool。fold |
| 32 | test_z26_strategy_check_coverage | strategy-check | `test_strategy_check_fallback.py` + `test_strategy_check_llm_timeout.py` | rule 覆盖决策 → strategy_check_fallback（**比对后 prune 与 `test_llm_failed_suggestions_still_rule_filled` 等重复者**）；llm 报告缓存 → strategy_check_llm_timeout。fold（部分 prune） |
| 33 | test_z29_search | search/market | **new `test_search.py`**（无单一业务文件覆盖 34 用例） | 跨市场 search 排序/去重/fallback/资产类型。fold/new |

---

## 4b. 去重裁决（4 处，证据化）

**点1 — round14 apply_design_factors ↔ test_factor_ic_sample_count【fold，不 prune】**
- `test_factor_ic_sample_count` 测 `get_active_factors()` 返回含非空 `sample_count`（序列化）。
- round14 `TestFactorMinSampleProtection` 测 `factors_router._status_of()` 的状态判定（`samples=0 → no_data`）+ `MIN_TRADING_DAYS` 常量。
- 二者 concern 不同，**无重叠**。round14 两个类分别归 `test_portfolio_apply_design.py`（apply-design 契约）与 `test_factors_router.py`（IC 状态）。

**点2 — round20 engine_fixes 信号守卫 ↔ test_signal_consistency / test_t_series_guards【部分 prune】**
- 业务已覆盖：`test_signal_consistency.test_kdj_overbought_not_buy`（参数化 J=85.7/98.7 → hold）、`test_t_series_guards.test_kdj_overbought_not_buy`（J=98.7）、`test_kdj_85_overbought_not_buy`（J=85.7）——均断言 J≥80 不得 BUY。
- round20 `test_kdj_j_over_100_no_buy`（J=101.67）的"超买不得 BUY"边界已被上述 J≥80 守卫**完整覆盖** → **prune**。
- round20 `test_rsi_over_80_no_buy`、`test_oversold_rsi_not_blind_decrease` 在业务文件中**无对应** → **fold** 入 `test_signal_consistency.py`。
- 其余类（overlap penalty / max_correlation / structure / rationale 措辞）归 `test_allocation_engine_fixes.py` / `test_risk_controls.py` / `test_rationale_causal_chain.py`，均 fold。

**点3 — round19_p1 + round20 相关性措辞 ↔ 业务 rationale【fold，不 prune；彼此去重】**
- grep 确认业务 `test_rationale_*.py` **无** "低相关" 措辞测试（`test_rationale_causal_chain` 测的是 `rank_info` 归因，不同 concern）。
- 故 round19_p1 `TestRationaleCorrelationGuard` 与 round20 `TestP1_2DeterministicLowCorrPhrase` 是**该行为的唯一护栏** → 均 fold 入 rationale 文件（建议 new `test_rationale_correlation.py`）。
- ⚠️ 注意：此二 round 文件在该 concern 上**彼此重叠**（都测 correlation_median→"低相关"）。折叠时只保留一套边界用例（如 median=None/0.1/0.6/0.7），删另一套重复者。

**点4 — z26 strategy_check_coverage ↔ test_strategy_check_fallback【fold，比对后 prune】**
- z26 的 `test_llm_timeout_rule_covers_all` / `test_llm_partial_coverage_rule_fills_gap` / `test_llm_full_coverage_no_rule_needed` / `test_rule_suggestion_decision_table` 与 `test_strategy_check_fallback.test_llm_failed_suggestions_still_rule_filled` / `test_rule_fallback_holdings_has_tech_signal_field` 在"LLM 超时→rule 回退覆盖" concern 上**可能重叠**。
- 裁决：z26 全部 fold 入 `test_strategy_check_fallback.py` + `test_strategy_check_llm_timeout.py`；落地时**逐函数比对**，若业务文件已等价覆盖则 prune，否则保留。
- `test_action_enum_restricted` / `test_second_call_hits_llm_report_cache` / `test_llm_failure_not_cached` 业务文件中未见 → 必 fold。

---

## 5. 边界与风险（实施前必读）

1. **`tests.db_fixtures` 绝对导入（phase1、phase5 用到）**：Phase 1 仅在 `tests/` 内搬函数、不建子目录，`from tests.db_fixtures import` 在任何 `tests/*.py` 中均有效，**无需改动**。仅当未来做 §6 Phase 2 子目录重组时，须保留 `tests/db_fixtures.py` 在根目录。
2. **需新建的业务文件（4 个）**：`test_policy_factors.py`(#4)、`test_correlation.py`(#18)、`test_connection_pool.py`(#29)、`test_search.py`(#33)。新建时遵循既有 pytest 约定（asyncio_mode=auto，mock 外部 IO）。
3. **命名冲突（测试函数 + fixture 都要查）**：折叠时不仅查 `test_*` 同名，还要查 **`@pytest.fixture` 同名**——fixture 重定义会直接令 pytest 收集报错（不仅是测试名冲突）。
   - **实测冲突案例**：`test_z26_strategy_check_coverage.py:39` 定义了 `strategy_env`，而目标文件 `test_strategy_check_fallback.py:53` **已定义同名 fixture**。折叠 z26 时**必须丢弃 z26 的 `strategy_env` 副本**，复用目标文件的。
   - 其余 early round 自定义 fixture 须随测试迁移：
     - `test_round15_guard_baseline.py:18` `clean_rolling(monkeypatch)` → 入 `test_source_page_fixes.py`（迁移前确认目标无同名）。
     - `test_round20_timeline_p01.py:90` `_clear_cache()` autouse → 入 `test_timeline_joins_tasks.py`（迁移前确认目标无同名）。
     - 通用规程：折叠任一 round 文件前，先 `grep -n "@pytest.fixture" <文件>` 列出其 fixture，逐个在目标文件 `grep "def <fixture>"`；同名则丢弃 round 副本、复用目标；异名则随测试迁入。
4. **大体量文件**：`test_z29_search`(34 用例) 整体入 new `test_search.py`；`test_round20_engine_fixes`(16 用例) 按 §4b 拆 4 个目标。
5. **折叠顺序建议**：按子系统分批（factors→engine→portfolio→strategy_check→fetchers→rationale→design→timeline），每批后跑 `pytest --collect-only` 校验用例数不丢。
6. **模块级 helper 必须随测试迁移（关键）**：多目标拆分的 round 文件普遍含模块级 helper，拆分到不同目标文件时若遗漏会致 `NameError`。实测含 helper 的文件：`test_round22_engine_redesign`(6)、`test_round15_amount_unit`(4)、`test_round20_timeline_p01`(4)、`test_z29_search`(5)、`test_round20_engine_fixes`(2)、`test_round19_p1`(2)、`test_round22_e5_correlation_unchecked`(2) 等。
   - **单目标折叠**：helper 随文件整体移入目标即可。
   - **多目标拆分**（如 #23 round20、#18 round19_p1、#27 round22）：若同一 helper 被落到**不同**目标文件的测试共用（典型：`_base_candidates()`/`_factor_matrix()` 在 round20 被 allocation/risk/rationale/signal 多类共用），二选一：① 在每个目标文件内**复制该 helper**（小重复可接受）；② 提升到共享模块 `tests/db_fixtures.py` 或新建 `tests/_shared_helpers.py` 供多文件 import。优先 ①（避免引入新共享依赖），仅当复制 ≥3 份时选 ②。
7. **保留溯源注释，但去 roundXX 文件名**：折叠时把原文件 docstring 里的 round/issue 引用（如 `round14 P0-A`、`docs/archived/round14-*.md §2.2`）作为 `# folded from <原文件>: <round/issue 引用>` 注释保留在测试上方，便于审计回溯；仅删除 `test_round*/phase*/z*` 文件名本身。

---

## 6. 整理方案（分阶段）

### Phase 1 — 折叠早期 round 测试（直接满足用户指示）
- 对 §4 的 33 个早期文件：将其 `test_*` 函数整体移入精确目标文件（保留函数体 + 来源注释），删除原 `test_round*/phase*/z*` 文件。
- 4 个去重点按 §4b 裁决：点2 删 `test_kdj_j_over_100_no_buy`；点3 二文件彼此去重；点4 比对后删重复。
- 新建 §5.2 的 4 个业务文件。

### Phase 2（可选）— 按模块子目录重组
- 目标：`tests/engine/`、`tests/factors/`、`tests/services/`、`tests/routers/`、`tests/fetchers/`、`tests/analysis/`、`tests/models/`。
- 约束：保留 `tests/db_fixtures.py` + `tests/__init__.py` 在根（8 文件绝对导入）。
- 风险：移动 236 文件改动大，分批且每批 `pytest --collect-only` 校验。

### Phase 3 — 清理临时脚本
- `logs/*.py`、`logs/round*/`（git 未跟踪，直接删或移 `scripts/scratch/`）。
- `backend/_test_*.py`、`backend/test_deepseek.py`（下划线前缀，pytest 已忽略）按需归档。

### Phase 4 — round24 关闭后
- round24(8) 文件按 Phase 1 同流程折叠，去掉 `round24_` 前缀。

---

## 7. 验证口径（每阶段门禁）

1. 折叠/移动前后 `python -m pytest --collect-only -q` 用例数**不变**（无测试丢失）。
2. 全量 `python -m pytest` 仍全绿；pytest-xdist `-n auto` 可并行。
3. `python scripts/verify_e2e.py` 仍全 PASS。
4. pre-commit 门禁（check_routes / mypy / audit_async_blocking）通过。

---

## 8. Review 迭代记录

- **Round 1（初稿）**：仅给通用目标（`test_factor_*` 等），去重点标"需判定"未实查。
- **Round 1 review 发现缺口**：① 目标文件名模糊不可直接执行；② 4 处去重未读源码比对；③ 未处理 db_fixtures 导入 / 新建文件 / 函数名冲突 / 大文件；④ round 边界未给依据。
- **Round 1 修订（本版）**：读取 4 个去重点及候选业务文件给出证据化裁决；§4 升级为精确目标 + 按类拆分；新增 §4b（裁决）、§5（边界风险）、§3（边界依据）。
- **Round 2 review 发现缺口**：① 多目标拆分的 round 文件含模块级 helper（实测 `round22_engine_redesign` 6 个等），拆分时须随测试迁移（§5.6）；② 除测试函数名外，**fixture 同名也会致 pytest 收集报错**——实测 `z26.strategy_env` 与目标 `test_strategy_check_fallback.strategy_env` 冲突，须丢弃 z26 副本（§5.3）；③ 溯源注释应保留 round/issue 引用而非整段删除（§5.7）。
- **Round 2 修订**：补 §5.3（fixture 冲突 + 实测案例 + 通用规程）、§5.6（helper 迁移）、§5.7（溯源注释）。**现已达实施标准**：每个早期文件有精确目标 + 拆分 + 处置；4 去重点有裁决证据；fixture/helper/函数名/大文件/新建文件等实施风险均覆盖。
- 后续若执行，建议在 Phase 1 每批后回写实际用例数变化，作为实施留痕。
