# 冗余/死代码交叉复核（round23 · 复核 subagent C）

> 只读复核，未改任何代码。基线：`_findings_redundant.md`、`docs/round23-system-audit-optimization.md` §6/§3.2b/§8。

## 1. 死端点最终判定表

| 端点 | 当前 file:line | 判定 | 证据 |
|---|---|---|---|
| `GET /market/sentiment` | market.py:489 | **删** | 0 引用（FE/verify_e2e/tests 皆无）；:488 自带 `# TODO: 未接入前端`。级联死：hub `get_market_emotion`(market_data_hub.py:1907) |
| `GET /sectors/industry-cls` | market.py:517 | **删** | 0 引用；与保留端点 `/sectors/rotation`(:535) 调用**同一** `get_sector_industry_cls` → 纯重复路由，删后服务仍活 |
| `GET /sectors/{sector_code}/stocks` | market.py:523 | **删路由，留服务** | 路由 0 引用；但 `get_sector_stocks` 有活调用：analysis.py:547、strategy_design.py:726 |
| `GET /sectors/{plate_code}/popular` | market.py:529 | **删** | 0 引用；级联死 hub:2029 |
| `GET /signal/debug/{symbol}` | market.py:395 | **删** | 0 引用 |
| `GET /market/wind` | market.py:656 | **删** | 0 引用。⚠️ :655 注释「前端已接入 marketApi.getMarketWind」**是过期谎言**——api/index.js:27-50 无此方法，注释须同删 |
| `POST /apply-strategy` | portfolio.py:133 | **删** | FE 仅 `utils/changeClass.spec.js:32` mock 了**并不存在**的 `applyStrategy`（portfolioApi 无此法）→ 陈旧 mock 同删。级联死：`apply_strategy_suggestions`(portfolio_service.py:1891) |
| `POST /news-impact/stream` | analysis.py:725 | **删** | FE 用非流式 api/index.js:90。⚠️ `NewsImpactRequest`(analysis.py:186) 被 :231 共用，**不可删** |
| `GET /news/research/{symbol}` | news.py:30 | **删** | 0 引用；级联死 `get_research_reports`(hub:2101) |

**保留名单核对（C 判定正确）**：`/sectors/rotation`←verify_e2e:868；`/realtime/batch`←test_realtime_batch_comma.py+test_optimization.py:158；`/factors/model`←test_factors_model_summary.py:21；`/news/macro|global`←verify_e2e:715/729；`/news/stock`←test_news_sort_order.py:379。

### ⛔ 实施阻断项（C 完全漏掉，最重要）
`check_routes.py:104-119` **双向**比对 api-contracts↔路由（含 `not_found_in_app`），`.githooks/pre-commit:94` 硬阻断。删路由必须**同批**删契约条目，否则 commit 必失败：
`market/all.md:308,309`｜`market/sectors.md:132,144,156`｜`market/hot-plates.md:116,145`｜`portfolio/strategy.md:120,196,197`｜`analysis/agents.md:23`｜`analysis/sse-streaming.md:126`｜`news/all.md:13,128`。另更新 pre-commit:95 文案「83 路由」→ 74。

## 2. 死代码/重复最终判定表

| 符号 | file:line | 判定 | 证据 |
|---|---|---|---|
| `analysisApi = {}` | api/index.js:85-86 | **删** | 仍为空；全仓仅 `changeClass.spec.js:35` mock 键（非真 import）→ 一并清 |
| `dailyPnl` / `getPnl` | api/index.js:57 / :59 | **合并（低优）** | 同 `POST /portfolio/daily-pnl` 同参，但**入参顺序相反**（`(totalCapital,type)` vs `(type,totalCapital)`）→ 合并须改 3 处调用方，非纯删 |
| `PortfolioReviewRequest` | analysis.py:259 | **删** | 全仓仅定义 1 处，0 引用 |
| `max_turnover_rate` | risk_controls.py:32 | **删** | 全仓仅定义；同类 `max_correlation`(:31) 活（strategy_design.py:400）→ 勿连坐 |
| `c2_adjust` | budgets.py:35,52,69,95,97,117 | **删（非零引用）** | C 称「无 callers」**不准**：有 6 处装配管线（:117 从 meta 读入），仅**无消费方** → 清理需动 6 行 |
| `llm_provider` | config.py:70、.env:5 | **删** | 全后端 0 读取（已被 `llm_primary/fallback_provider` 取代） |
| `llm_fallback_provider` | config.py:84、.env:11 | **接通（勿删）** | provider.py:49 只读 primary；fallback 分支 :68 **硬编码 deepseek**，仅读 `llm_fallback_timeout`(:80)；:44 docstring 谎称读取。tests(test_llm_provider_failover.py:68、test_llm_stream_retry.py:53) 有引用，删字段会挂测试 |
| `backend_port`/`frontend_dev_port` | config.py:93-94 | **删** | 全仓 0 读取（start.ps1/restart.bat/compose 均未用） |
| `analyze_news` | llm.py:1055（import 于 analysis.py:15） | **决策：接通或删** | 词界 grep 确认**仅定义 1 处**，0 调用（analysis.py:251 调的是 `analyze_news_impact`）→ 死 import + 未暴露能力 |

## 3. subagent C 误判修正

1. **`portfolio/{designs,strategy-checks}` 列表端点判死 = 误判 → 必须保留。** FE 确实只用 timeline，但两者被 verify_e2e:135/262/296/372/1424/1737 与 :534 覆盖，且 tests/test_portfolio_list.py、test_performance_benchmark.py:65 断言 → 按 §6.1 口径为「非死代码」。（§6.2b 第 2 条应撤销）
2. **`c2_adjust` 非「零引用」**，见上表（6 处装配）。
3. **`max_turnover_rate` 结论正确**，但 C 未指出 `/sectors/industry-cls` 与 `/sectors/rotation` 是同实现重复——删前者才是零风险的真正理由。
4. **C 漏报 check_routes 契约门禁**（§1 阻断项）与 **market.py:655 过期注释**。
5. `docker-compose.diag.yml`：C 建议删除，§6.4 已修正为保留（本轮 `PROFILE_WARMUP=1` 承重件）——以 §6.4 为准。

## 4. 新增发现（散点）

- `portfolio_service.py:1010` 用 `os.environ.get("LLM_PRIMARY_PROVIDER")` 绕过 pydantic settings，与 provider.py:49 双口径 → 配置漂移风险（非死代码，建议统一）。
- `ic_tracker.py:179` `self._zero_ratio` 是**只写属性**（唯一读方 factors.py:377 取错对象）→ 会被 `audit_unused_symbols` 误报为死代码，**严禁删除**，它是 F27 的修复靶点。
- `market_data_hub.py:1705` 的 `("重大","利好")` 字面分支恒不命中，看似死分支，实为 F28 类型迁移 bug。

## 5. 与 §3.2b 断裂清单的交叉核对（bug ≠ 死代码）

| 断裂 | file:line | 性质 | 是否被 §6 误归类 |
|---|---|---|---|
| C1 zero_ratio 取错对象 | factors.py:377 vs ic_tracker.py:179 | 调用中但恒 `{}`，**bug** | ❌ 未误归类（§6 未收录）✅ |
| C4 `str(level)` 恒 False | market_data_hub.py:1705 | 该行仍执行（`stars>=4` 或分支生效），**bug** | ❌ 未误归类 ✅ |
| C2 `summary.min_samples` 缺键 | FactorModelView.vue:73 | 静默回退 30，**契约缺失 bug** | ❌ 未误归类 ✅ |

结论：§6 死代码清单**未混入**这 3 类断裂，分类干净。风险仅在实施期——上述 3 处的「看起来没被用」代码（尤其 `_zero_ratio`）不得被顺手删掉，须走 F27/F28/F32 修复。

## 6. 临时文件清理清单

前提：`.gitignore` 含 `logs/`，`git ls-files logs/` = **0** → logs/ 全为本地未跟踪，删除不动 git 历史。`backend/scripts/_tmp*/_step2*/_findings_*/_evidence*` 亦全未跟踪。

**必须保留**
- `backend/scripts/.unused_symbols.baseline.json`（**已入库**；audit_unused_symbols.py:29 读为门禁基线）
- `logs/backend.log`(+`.1`)：`.env:32 LOG_FILE=logs/backend.log`，`core/logging.py:57` RotatingFileHandler(backupCount=5) 管理 → 服务运行中勿手删
- `logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.{html,txt}`：main.py:519、warmup_profiler.py:98/109/118 的活动产物，且是 §1.1 证据
- `backend/scripts/docker_smoke.py`、`verify_*.py`、`audit_*.py`、`check_*.py`（pre-commit 承重）

**可清理（按顺序）**
1. `backend/scripts/_tmp_fetch2.py`、`_tmp_fetch3.py`、`_tmp_review.py`、`_tmp_step2.py`、`_step2_out.json`(164K)、`_step2_review.txt`(34K)、`__pycache__/` — 本轮 agent 临时件，0 引用
2. `logs/` 散落诊断脚本：`analyze_coverage.py`、`analyze_lh.py`、`verify_round2_part{1,2,3}.py`、`check_*.py`、`inspect_*.py`、`dump_*.py`、`test_*.py`、`summarize_*.py`、`poll_*.py`、`split_ocr*.py`、`run_lighthouse*.py`、`trigger_factor.py`、`db_tables.py`、`deep_check_plans.py`、`*.ps1`、`logs/__pycache__/` — 全仓 0 引用
3. 快照类：`logs/*.png`（**28M**）、零散 `*.txt`（cap/cm/bfr/cb_lines/fr*/ic*/fn*/sh…）、`design_*.json`、`task3_*.md`、`step2_*.json`、`task_results.json`
4. lighthouse 历史：`lh_*.json` + `lighthouse_*`（**19M**）、`logs/lighthouse/`(5M)
5. 陈旧日志：`_backend_z29.log`、`backend_run.log`、`backend_stdout.log`、`backend_err.log`、`backend_stderr.log`、`backend_api.log`、`backend_test.log`、`build_*.log/txt`、`frontend_std*.log`、`docker_build*`

**需人工确认（勿盲删；§6.3「purge round16|round20|diag|tmp」需收敛）**
- `logs/round20/corr_audit_out.txt` 被 `docs/round20-...md:204` 当作关联度证据引用
- `logs/tmp/perf_backend.py` 被 round20:59、round21:31 引用为性能 harness
- `logs/round8|round16|round18`（合计 1.6M）为历轮归档惯例产物
→ 建议整体移入 `logs/archive/round*/` 而非删除；`logs/round20/`(11M) 内非引用大件可删。
- `backend/scripts/_findings_*.md`、`_evidence*/`（384K）：本轮审计证据，待 round23 结论落 docs/ 后再删。

`.gitignore` 已覆盖 `logs/`，无需新增；建议补 `backend/scripts/_tmp*`、`_step2*`、`_evidence*/` 防再次污染。

## 7. 与 §8 修复表一致性

- **F7b 成立**（已实读 provider.py 全 143 行）：`llm_fallback_provider` 确实从未被读取，fallback 硬编码 deepseek。修法应为**补读取**而非删配置（tests 有引用）；同条目内的 `LLM_PROVIDER`(config.py:70/.env:5) 确认可删。
- **F33 成立**（`factors/model` 宣称 vs 实现）：属「宣称虚高」，与 §6 死代码互不重叠，不受本清理影响。
- **F27/F28/F32 与本清单零冲突**，但须在清理工单里加护栏：`ic_tracker.py:179`、`market_data_hub.py:1705` 的 `("重大","利好")` 分支不得作为死代码删除。
