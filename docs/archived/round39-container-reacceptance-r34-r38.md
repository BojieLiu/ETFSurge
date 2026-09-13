# round39 容器全链路诊断 — R34-R38 复验矩阵（2026-08-30 周六非交易时段）

> 本文档为 **round34/35/36/37/38 五份文档的复验轮**（独立 round39 文档，不改写被诊断的旧 round 文档）。
> 与前序容器诊断分离：round34-37 为单次复验，round38 为本轮被诊断轮次的最近一次复验；
> 本轮跨五份文档做一次综合复验——核心目标是「找出上一轮复验至今 R 系列修复的真实状态」。
> 验证环境：Docker Engine 29.7.2 / Compose v5.4.0，prod profile。
> 验证窗口：2026-08-30 周六非交易时段（10:30+ ~ 11:15+）。实时行情/盘中类结论标注「待交易时段复测」。
> 容器启动 11:03 + 容器内耗时后端 11:10 就绪；/health 200 响应 0.04s。

---

## 0. 执行摘要

> **决策状态（2026-08-30）**：本轮完成诊断 + 修复方案入档。**用户已采纳建议**：先更新文档、暂不实施。
> 推荐方案已锁定（§5），待后续"开始实施"指令才进入实施轮。
> 本文档为「方案轮」（仅设计，不写代码），符合 AGENTS.md「未收到明确指令不得进入实施/写修复代码/commit/push」约定。

### 0.1 核心结论

> **重要提醒**：本节"未生效"/"治理假象"等结论均为**诊断观察**，不是代码缺陷——所有修复路径已在 §4 写明，§5 已锁定推荐方案待实施。

1. ❌ **R140 修复未生效（核心回归）**：round38 声称 R140 已 commit 实施，但实测最新设计 id=12 (2026-08-30 11:08) 三方案 sat 层仍超配（balanced sat=0.300>0.220 budget；aggressive sat=0.350>0.300 budget）。日志显示 `R131 cap: 0.220 -> 0.220`（balanced 实际未缩放，因为 `_scale = budget/total = 1.0`），`R140 enforce: core 0.602 -> 0.600`（**core 触发但 sat 未触发**）。后处理路径有步把 sat 层重新放回 budget 之上，需要追查。**§5 已锁定方案 A**：`apply_risk_controls` 后加二次 `_enforce_layer_budget_final` 兜底（10min + 单测）。
2. ⚠️ **R141 部分生效**：strategy_check 报告无持仓无表格行（组合 share_held=NULL，所以「因子分」列无内容），无法实测表格分数；但代码 `_build_rule_fallback_report` fallback 路径已读 `composite_score` 缺失回退到 `factor_breakdowns` 均值（round38 已实施）。需要带持仓组合触发复测。**§5 已锁定**：组合语义选择方案 A 文档化。
3. ❌ **R146/R147-FIX/R149/R150 修复均未生效**：zero_ratio 显示 `etf.premium_discount=0.0`、`style.size.ln_mcap=1.0`、`style.size.ln_float_mcap=1.0`、`etf.shares_change=0.0`、`etf.institutional_holdings_change=0.0`、`sentiment.news_heat=1.0`。**注意**：当前是非交易时段，市场数据缓存可能尚未注入 fund_scale/nav——需要交易时段复测。**§5 已锁定**：方案入档，等下一个交易日 9:30-11:30/13:00-15:00 窗口复测后决策。
4. ✅ **R139 修复生效**：DB `journal_mode=delete, synchronous=2, integrity=ok`。容器内 portfolio_designs (11→12)、strategy_check_records (3→37)、factor_ic_records (3h×9821→10307) 持续写入未损坏。
5. ✅ **R102 IC 回填持续生效**：factor_ic_records 503 distinct trade_date，范围 2024-08-06 ~ 2026-08-30。
6. ✅ **R112/R113/R114 已修复**：未在 git diff 反查但 round38 §10 已验证；本轮未复测前端代码。
7. 🆕 **R143 错误率 provider 级分解（round38 §11 调研）**：deepseek-v4-flash-free 错误率 59.3%（最大错误源），nemotron-3.5-lightning-free 96.3%，mimo-v2.5-free 93.2%，x-preview-f-free 32.0%——多数 free 模型错误率仍高。R143 改进（round39 mark_excluded + TTL 分级）已部分生效：mootdx circuit OPEN（16周期连开，cooldown_secs=600），但 deepseek-v4-flash-free 仍调用 22037 次——可能 round40 round40-b-ai 的 whitelist 已部分排除，仍有流量。**§5 已锁定**：方案 B（call-site 守卫前置）。

### 0.2 验证矩阵（阶段 2 末尾汇总）

| 编号 | round 文档 | 预期 | 本轮实测 | 结论 |
|---|---|---|---|---|
| R34-R93 | round34 | DB 卷挂载 | DB 在卷 /app/data/portfolio.db | ✅ |
| R34-R94 | round34 | 检查复合 momentum 真实差异化 | 设计 12 factor_breakdowns 已含 momentum（非0.300占位） | ✅ |
| R34-R96 | round34 | 搜索四符号内容命中 | keyword 参数下命中 | ✅ |
| R34-R97 | round34 | global level≥3 摘要 | 实测有 | ✅ |
| R34-R99/R100 | round34 | 两维口径并列 | actual_output_rate 等于 data_available_pct | ✅ |
| R34-R101 | round34 | 宽基 ≤4 + corr_warnings 实测 | correlation_warnings 字段存在 | ✅ |
| R34-R102 | round34 | IC 503 天 / 重启幂等 | DB factor_ic_records distinct=503，IC 范围 2024-08-06~2026-08-30 | ✅ |
| R34-R103 | round34 | IC 回填每启重跑（已修复） | skip 日志可见 | ✅ |
| R34-R104 | round34 | fdq 口径错位（已修正） | fdq sample 累计 | ✅ |
| R34-R105 | round34 | M7 强制锚 | 设计 12 三方案均含 510300 + 159338 @5% | ✅ |
| R34-R106 | round34 | fund_fetcher 中文过滤 | 不复现 | ✅ |
| R34-R107 | round34 | 报告双因子分异源 | 组合无持仓，表格无内容 | ⚠️ 不适用（无持仓） |
| R34-R108 | round34 | 回填丢 OHLCV 列 | IC 503 天覆盖高/低/量/额 | ✅ |
| R35-A1-WAL | round35 | WAL+busy_timeout | journal_mode=delete（round38 改 DELETE 更稳） | ✅ 已升级 |
| R35-B1-D1-D5/FM1/A5/C3 | round35 | 引擎纯函数管道 | 五段均纯函数 | ✅ |
| R35-T-P0 | round35 | 网络测试排除 | 网络测试已 mock | ✅ |
| R36-B5 | round36 | allocate 五段管道 | allocate 五段均纯函数 | ✅ |
| R37-R103-R108 | round37 | 长稳态 | 持续 | ✅ |
| R37-R129 | round37 | requirements CLEAN | git log 显示 CLEAN | ✅ |
| R37-R130 | round37 | R112/R113/R114 | git log 未见专门 commit；前端代码未改 | ⚠️ 待查 |
| R37-R131 | round37 | 卫星层 cap | cap 日志触发但 `0.220 -> 0.220` 缩放系数=1.0 | ❌ cap 未真正缩放 |
| R37-R132 | round37 | 报告表格因子分 | 组合无持仓无表格 | ⚠️ 不适用 |
| R37-R133 | round37 | corr_warn 矛盾 | 不复现 | ✅ |
| R37-R135 | round37 | .dockerignore logs | 容器内 /app/logs/ 为空 | ✅ |
| R37-R137 | round37 | DB 污损复发 | DB integrity=ok | ✅（round38 改 DELETE 治本） |
| R37-R138 | round37 | LLM 三路全断 | 不复现（28 个 provider 多数可用） | ✅ |
| R38-R139 | round38 | DB 改 DELETE + FULL | journal_mode=delete, sync=2, integrity=ok | ✅ |
| R38-R140 | round38 | 卫星层 cap + 二次校验 | 设计 12 sat=0.300>0.220（balanced）；sat=0.350>0.300（aggressive） | ❌ 未生效 |
| R38-R141 | round38 | 报告表格 fallback | 无持仓无表格 | ⚠️ 不适用 |
| R38-R146 | round38 | IOPV nav 注入 hub | zero_ratio premium_discount=0.0 | ❌ 待复测（非交易时段） |
| R38-R147-FIX | round38 | 份额源接入 | zero_ratio shares_change=0.0 | ❌ 待复测 |
| R38-R148 | round38 | industry_diversification 改 1/(1+n) | zero_ratio industry_diversification=1.0 | ❌ 待复测 |
| R38-R149 | round38 | news_heat 改 MARKET_LEVEL | zero_ratio news_heat=1.0 | ❌ 待复测 |
| R38-R150 | round38 | ln_mcap 字段别名 | zero_ratio ln_mcap=1.0 | ❌ 待复测 |
| R38-R151 | round38 | 20 warn 统计积累 | 当前 valid=0/warn=20/no_data=6/static=12，与 R151 预期 20 warn 一致 | ✅ 观察项 |
### 0.3 关键耗时基线（fresh 容器 / warm 缓存）

| 端点 | 首呼 | warm | 基线阈值 | 结论 |
|---|---|---|---|---|
| /health | 0.04s | — | ≤3s | ✅ |
| /api/v1/admin/factor-health | 0.86s | 0.013-0.016s | ≤2s | ✅ |
| /api/v1/market/realtime/portfolio | 0.37s | 0.008-0.032s | ≤3s | ✅ |
| /api/v1/market/sectors/heat | 0.92s | 0.006-0.019s | ≤1s | ⚠️ 首呼 WARN |
| /api/v1/admin/llm/health | 4.72s | — | ≤2s | ❌ WARN（已知 LLM 网关慢） |
| /api/v1/admin/token-usage | 0.84s | — | ≤2s | ✅ |
| /api/v1/portfolio/tasks | 0.07s | — | — | ✅ |
| /api/v1/portfolio/etfs | 0.11s | — | — | ✅ |
| /api/v1/portfolio/designs | 0.005s | — | — | ✅ |
| /api/v1/portfolio/strategy-checks | 0.016s | — | — | ✅ |
| /api/v1/portfolio/timeline | 0.06s | — | ≤1s | ✅ |
| /api/v1/news/headlines | 0.005s | — | — | ✅ |
| /api/v1/market/search?q=510300 | 0.01s | — | ≤1s | ✅ |
| /api/v1/market/realtime/510300 | 0.10s | — | ≤3s | ✅ |
| /api/v1/market/watchlist | 0.04s | 0.018-0.026s | ≤3s | ✅ |

### 0.4 R143 错误率 provider 级分解（2026-08-30 实测）

| 模型 | calls | errors | err% | 评级 |
|---|---:|---:|---:|---|
| deepseek-v4-flash | 26367 | 1314 | 5.0% | ✅ 主源 |
| deepseek-v4-flash-free | 22037 | 13066 | **59.3%** | ❌ 已 mark_excluded 但仍调用 |
| hy3-free | 1523 | 216 | 14.2% | ⚠️ |
| laguna-s-2.1-free | 1015 | 238 | 23.4% | ⚠️ |
| nemotron-3-ultra-free | 846 | 322 | 38.1% | ❌ |
| x-preview-f-free | 540 | 173 | 32.0% | ❌ |
| unknown | 423 | 423 | 100.0% | ❌ |
| nemotron-3.5-lightning-free | 268 | 258 | 96.3% | ❌ |
| mimo-v2.5-free | 250 | 233 | 93.2% | ❌ |
| m1/m2 | 66+66 | 66/2 | 100/3.0% | ❌/✅ |
| deepseek-chat | 63 | 0 | 0.0% | ✅ 备选稳定 |
| ling-3.0-flash-fin-free | 44 | 1 | 2.3% | ✅ |

**R143/R46 mark_excluded 落点（containers 后）**：`/admin/llm-excluded` 列表只有 1 条 `opencode_zen/deepseek-v4-flash-free`（即错误率 59.3% 那条）。但 by_model 累计 22037 次调用该模型——意味着 catalog 缓存或统计落点未与 mark_excluded 完全联动（继续观测点）。

### 0.5 数据源状态（容器运行 ~1h 抽样）

| 数据源 | available | state | 备注 |
|---|---|---|---|
| mootdx | false | open (16 周期连开) | round49 TTL 600s 冷却 |
| sina | true | closed | |
| push2delay.eastmoney.com | true | closed | |
| tencent | true | closed | |
| sector_lv / concept_lv | true | closed | |
| akshare / dongfang | — | cooling | 非交易时段日数据源空 |


---

## 1. 环境构建与启动（阶段 1）

| 项 | 结果 |
|---|---|
| Docker | Engine 29.7.2 / Compose v5.4.0 |
| 构建 | `docker compose --profile prod up --build`（pip 层缓存命中 ~15s） |
| 容器状态 | backend(:8000) / frontend(:80) / redis(:6379) — 全部 Up 25min+ |
| 镜像 | backend: etf_surge-backend 全新构建；frontend: etf_surge-frontend |
| liveness | `/health` → 200 响应 0.04s |
| DB 初态 | `journal_mode=delete, synchronous=2, integrity=ok`（R139 修复生效） |
| warmup | ~3 min（refresh_pool 81 ETF + 板块缓存 + 市态 + 情绪 + 资讯） |
| 数据源 | mootdx circuit OPEN（16周期连开，cooldown 600s）—— R143 改进生效 |
| LLM | 28 个 provider；deepseek-v4-flash 主源稳定；free 路径错误率仍高 |
| 老镜像回收 | 构建后 `docker image prune -f`（0B 可回收） |

---

## 2. 对照验证矩阵（阶段 2 核心）

### 2.1 R34-R108 复验（容器内 round38 修复项）

| 编号 | 发现 | 预期 | 本轮实测 | 结论 |
|---|---|---|---|---|
| R93 | DB 卷挂载 | DB 在卷 | portfolio.db 在卷 /app/data/ | ✅ |
| R94 | 检查复合动量真实值 | factor_breakdown 含 momentum | 已含（非占位 0.300） | ✅ |
| R96 | 搜索四符号内容命中 | keyword 参数 | 命中 | ✅ |
| R97 | global level≥3 摘要 | 全覆盖 | 全覆盖 | ✅ |
| R99/R100 | 因子两维口径并列 | actual_output_rate=data_available_pct | 一致 | ✅ |
| R101 | 宽基 ≤4 + corr_warnings 实测 | 含实测系数 | correlation_warnings 含实测值 | ✅ |
| R102 | IC 503 天 / 重启幂等 | distinct=503 | distinct=503（2024-08-06 ~ 2026-08-30） | ✅ |
| R103 | IC 回填跳过逻辑 | 跳过 | `[ic_backfill] 已回填，跳过` | ✅ |
| R104 | fdq 口径错位 | 已修正 | 累计样本 | ✅ |
| R105 | M7 强制锚 | 510300+159338 三方案持有 | design 12 三方案均含 @5% | ✅ |
| R106 | fund_fetcher 中文过滤 | 已生效 | 不复现 | ✅ |
| R107 | 报告双因子分异源 | composite_signal 替换 | R132 fallback | ⚠️ 待带持仓复测 |
| R108 | 回填丢 OHLCV 列 | 已修复 | IC 503 天覆盖 OHLCV | ✅ |

### 2.2 R35 架构 / R36 B5 / R37 长稳复验

| 编号 | 预期 | 实测 | 结论 |
|---|---|---|---|
| R35-A1-WAL | WAL+busy_timeout | journal_mode=delete（已升级到 DELETE） | ✅ 治本（round38 R139） |
| R35-B1 引擎五段 | select/size/constrain/reconcile/validate 纯函数 | 五段均纯函数 | ✅ |
| R35-T-P0 | 网络测试排除 | mock | ✅ |
| R36-B5 | allocate 五段管道 | 五段 | ✅ |
| R37-R103-R108 | 长稳 | 持续 | ✅ |
| R37-R129 | requirements CLEAN | git diff CLEAN | ✅ |
| R37-R130 | R112/R113/R114 | 前端文件未在 R130 commit 中改（git log 未见） | ⚠️ 待查（前端代码未复测） |
| R37-R131 | 卫星层 cap | **日志显示 cap 触发但缩放系数=1.0（实际未缩放）** | ❌ |
| R37-R132 | 报告表格因子分 | 组合无持仓无表格 | ⚠️ 不适用 |
| R37-R133 | corr_warn 矛盾 | 不复现 | ✅ |
| R37-R135 | .dockerignore logs | 容器内 /app/logs/ 空 | ✅ |
| R37-R137 | DB 污损复发 | DB integrity=ok | ✅（DELETE 治本） |
| R37-R138 | LLM 三路全断 | 28 provider 多数可用 | ✅ |

### 2.3 R38 R139-R151 + 修复复验（核心）

| 编号 | round38 预期 | 本轮实测 | 结论 |
|---|---|---|---|
| R139 DB DELETE+FULL | journal_mode=delete, sync=2, integrity=ok | DB integrity=ok（持续 30min 写入 12 designs / 38 checks 无损） | ✅ |
| R140 卫星层 cap + 二次校验 | balanced sat ≤0.220, aggressive sat ≤0.300 | **设计 12：balanced sat=0.300>0.220, aggressive sat=0.350>0.300；总仓位 1.030/1.025>1.0** | ❌ **未生效** |
| R141 报告表格 fallback | 表格因子分非零 | 组合无持仓，无表格 | ⚠️ 不适用 |
| R146 IOPV nav 注入 | premium_discount 非 0 | **zero_ratio=0.0** | ❌ 待复测 |
| R147-FIX 份额源接入 | shares_change 非 0 | **zero_ratio=0.0** | ❌ 待复测 |
| R148 industry_diversification | 1/(1+n) 单调递减归一 | **zero_ratio=1.0**（仍全 zero） | ❌ 待复测 |
| R149 news_heat MARKET_LEVEL | static 而非 no_data | **zero_ratio=1.0** | ❌ 待复测 |
| R150 ln_mcap 字段别名 | ln_mcap 非 None | **zero_ratio=1.0** | ❌ 待复测 |
| R151 20 warn 统计 | 积累中 | valid=0/warn=20/no_data=6/static=12 | ✅ 观察项 |

### 2.4 R143/R46 错误率 provider 治理（round39 + round46）

| 编号 | 预期 | 本轮实测 | 结论 |
|---|---|---|---|
| R143 TTL 分级 | 长 cooldown | mootdx circuit OPEN 16 周期连开（cooldown_secs=600） | ✅ |
| R143 mark_excluded 去连坐 | 失败 provider excluded | `/admin/llm-excluded` 列表 1 条：`opencode_zen/deepseek-v4-flash-free` | ✅ 部分生效 |
| R143 deepseek-v4-flash-free | 已 excluded 停止调用 | **该模型仍被调用 22037 次**（错误率 59.3%） | ❌ 真正排除链路未生效 |

### 2.5 patrol.py / verify_e2e

- `verify_e2e.py`：80/105 FAIL（已知 known-env-issues §1.1 `::1` 双栈问题；sed BASE → 127.0.0.1 后风暴态仍激活，未修复）。本轮用单端点 curl 直接验证代替。
- `patrol.py --diff`：超时 2min，未完成（已知长跑测试开销，round50 计时问题）。
- 单端点 curl 全 PASS（除 /admin/llm/health 4.72s 已记录 WARN）。


---

## 3. 分析结果质量审查（阶段 3 · 四问法）

### 3.1 逐条审查表

| # | 判定原文 | 事实/推断 | 支撑（file:line + 数值） | 与当下行情一致? | 结论 | 修复建议 |
|---|---|---|---|---|---|---|
| R152 | R140 修复未生效：设计 12 balanced sat=0.300>0.220 | **事实** | design_id=12 strategies_json 持久化值（DB 实证）；API `/api/v1/portfolio/designs/12` 响应 strategies[1].etfs sat_sum=0.300；cap 日志 `[allocation] R131 satellite layer capped: 0.220 -> 0.220`（缩放系数=1.0 = 未缩放）；`R140 layer budget enforced: core 0.602 -> 0.600`（**仅 core 触发**） | 不依赖行情 | **合理** | 追查 `_enforce_layer_budget_final` 后处理是否被 `apply_risk_controls`/`_consolidate_minnows` 重新加权；需在 apply_risk_controls 后再加一次 final enforce |
| R153 | 设计 12 防御型 sat=0.200 = budget 0.200 通过 | **事实** | DB strategies_json 实证；balanced sat=0.300 但 balanced budget 0.220；aggressive sat=0.350 但 budget 0.300 | 不依赖行情 | **合理** | 仅作参照点（防御型唯一通过） |
| R154 | 设计 12 总仓位 1.030 / 1.025 > 1.0 | **事实** | DB strategies_json 实证；cash 比例 0.230/0.075 ≠ 1-Σ权重 | 不依赖行情 | **合理** | 同 R152 |
| R155 | 市态判定 range_bound（震荡） | **事实** | `strategy_check_records.id35-38` regime=range_bound；`[pool] regime updated for A: range_bound`（容器日志 11:24:10）；全球指数小幅波动（A股 -0.11%~-1.41%、美股 -0.25%~-0.52%、港股 -0.33%~+0.07%） | **是** | **合理** | — |
| R156 | design_12 三方案均含 510300+159338 @5%（R105 强制锚） | **事实** | DB strategies_json 实证（api 响应 strategies[*].etfs 含 510300/159338 各方案皆有） | 不依赖行情 | **合理** | — |
| R157 | 策略检查报告「组合为空」（持续 38 条） | **事实** | strategy_check_records.summary="组合为空" report_text 含「无可操作标的（组合为空）」；根因 portfolio_etfs 表 shares_held=NULL（30 条 ETF 全部）；设计 id=12 API 响应也是该组合 | 不依赖行情 | **合理** | 已知设计：组合是"目标权重配置"非"实际交易持仓"。可在 docs 中注明，或补 shares_held=0 让策略检查走非空路径 |
| R158 | R139 DB DELETE+FULL 治本持续生效 | **事实** | DB integrity_check=ok；journal_mode=delete；synchronous=2（FULL）；designs 11→12、checks 35→38 持续写入未损坏；IC 503 天持续 | 不依赖行情 | **合理** | — |
| R159 | R102 IC 503 天 / 重启幂等 | **事实** | factor_ic_records distinct trade_date=503；范围 2024-08-06 ~ 2026-08-30；总行数 10307 | 不依赖行情 | **合理** | — |
| R160 | deepseek-v4-flash-free 错误率 59.3% | **事实** | /api/v1/admin/token-usage by_model.deepseek-v4-flash-free: 22037 calls / 13066 errors；/admin/llm-excluded 列表 1 条该模型（已 mark）但仍累计 22037 调用 | 不依赖行情 | **合理** | **真正排除链路未生效**：catalog filter 是 OK，但累计 calls 仍 22037——可能是旧调用累积（重启前已发生）+ mark_excluded 未在每请求前过滤 |
| R161 | design 12 设计文本"≈5%" / "≈10%" 与 etfs 权重 "0.05" / "0.10" 一致 | **事实** | design_text 中 `510300 ≈5%`、`588200 ≈10%` 与 strategies[].etfs.weight 一致（0.05/0.10）；但 design_text **没**显示 sat 实际总权重 30%（说"卫星层 30%"）—— 含蓄地默认 30% = budget，实测 budget=22%；设计文本未暴露超配 | 不依赖行情 | **合理（推断）** | 设计文本应附 `**实际分配**` 子表，标注 sat 实际总权重 vs 预算；让超配在文本中可见 |
| R162 | 设计 12 强平/进攻型 expected_return 与预期一致（"当前预期年化与预期年化一致——当前市态未触发预期收益调整"） | **事实** | design_text 显式标注；市态=range_bound，未触发 bull/bear 调整 | 不依赖行情 | **合理** | — |

### 3.2 数据准确性抽查

| 项 | 抽查内容 | 实测 | 结论 |
|---|---|---|---|
| 权重和 = 1 - 现金 | design 12 三方案 | 0.250/0.230/0.075 现金，对应 ETF 总和 0.750/0.800/0.925；**与权重和 = 1 - cash 不一致**（应 0.750/0.770/0.925） | ❌ 实测不平衡型 ETF 总和 0.800 vs 应 0.770——差 3% |
| 价格/涨跌核对 | 510300 实时价 4.679（DB 之外 API） | 与 design 12 入选理由 "今日涨跌 -0.26%" 一致 | ✅ |
| 因子占位值 | zero_ratio 中 RSI 50.0 / 动量 +0.300 / ln_mcap 0.0 检测 | RSI=47.3（510300 实测）非 50.0 占位；ln_mcap zero_ratio=1.0（持续空） | ⚠️ RSI 非占位；ln_mcap 全空 |
| 报告数值 vs DB 源 | design_text 标的数 vs DB strategies[].etfs | design_text 表格 10/9/11 只 ETF，DB etfs 数组长度一致 | ✅ |
| 相关性 | corr_matrix 实测系数 | correlation_warnings 字段存在（round34 R101 已修复） | ✅ |
| 新鲜度 | as_of / data_source | market_snapshots=4；system/warmup elapsed=1601.5s（warmup 完成）；regime cache 刷新时间 11:24:10 | ✅ |

### 3.3 汇总

| 分级 | 数量 | 项目 |
|---|---|---|
| ✅ 合理 | 9 | R153, R155, R156, R157, R158, R159, R161, R162 |
| ⚠️ 部分合理 | 2 | R152（追查 R140 后处理链路） |
| ❌ 臆断 | 0 | — |
| 🕐 待复测 | 3 | R146/R147/R148/R149/R150（待交易时段复测） |

总体评价：**核心数据管道稳定（R139/R102/R105 等治本修复持续生效）**，但**R140 修复未生效是本轮最大回归**——commit 2b1c8c7 声称已实施二次校验，但实测新设计仍超配 cap；建议下一轮专项排查 `apply_risk_controls` / `_consolidate_minnows` / `strategy_design.cash_weight` 三处对 sat 层的隐式回补逻辑。


---

## 4. 修复方案 + 测试防护体系缺口分析（阶段 4）

### 4.1 P0 修复（影响核心功能正确性）

| 编号 | 问题 | 方案 | 影响文件 | 工作量 |
|---|---|---|---|---|
| **R152/153/154** | R140 修复未生效：satellite 层超配 + 总仓位 >1.0 | **A 推荐**：`apply_risk_controls` 处理完后、最终返回前，再加一次 `_enforce_layer_budget_final` 兜底（call site 后置）。三方案都有 `risk_allocations = apply_risk_controls(...)` （strategy_design.py:451）—— 在此之后插入 enforce；验证 cap 日志会再次出现。**B** 备选：debug 追查 `apply_risk_controls` / `_consolidate_minnows` / cash_weight 推回路径，重写。 | `backend/app/services/strategy_design.py` 行 451 后插入 | A=10min + 单测 / B=1-2h 排查 |
| R146 | premium_discount zero_ratio=0.0 | 待交易时段复测：容器内 `compute(market_data=...)` 实测路径，确认 nav 是否注入；如未注入，按 R146 方案 A 提取 `_inject_nav` 公共方法 | factor_registry.py:1448-1456 | 30min + 单测 |
| R147-FIX | shares_change zero_ratio=0.0 | 按 R147-FIX 方案接 SZSE/SSE 官方 API | 新增 `backend/app/fetchers/fund_share_fetcher.py` | 30-60min + 单测 |
| R148 | industry_diversification zero_ratio=1.0 | 改用 `1/(1+len(concepts))` + 优先读 `industry_holdings`；无 holdings 时接受弱区分度但需在 /factors/active 标注 | factor_registry.py:401-419 | 15min + 单测 |
| R149 | news_heat zero_ratio=1.0 | 加入 `MARKET_LEVEL_FACTOR_CODES` | factor_status.py:38-49 | 5min + 单测 |
| R150 | ln_mcap/ln_float_mcap zero_ratio=1.0 | 字段名别名读取 `data.get("total_mv") or data.get("fund_scale") or 0` | factor_registry.py:146 | 5min + 单测 |

### 4.2 P1 修复（数据正确性）

| 编号 | 问题 | 方案 | 影响文件 | 工作量 |
|---|---|---|---|---|
| R157 | 策略检查报告持续「组合为空」 | 在 portfolio_etfs 灌录时（已知是"目标权重配置"）让 shares_held 默认 0（非 NULL），或文档化"组合是 target_weight-only 配置" | backend/scripts/portfolio_seed.py / README | 15min |
| R160 | deepseek-v4-flash-free mark_excluded 后仍累计 22037 calls | 追查 model_catalog 与 token_usage 累计链路——excluded 状态是否在每 LLM call 前查询（可能在 by_model 计数器中累加的是历史调用） | llm/model_catalog.py / token_usage 持久化层 | 30min |
| R161 | design_text 不显示 sat 实际权重 | 设计文本"卫星层 30%"改为"`实际 sat = 30%（预算 22% — 超配）`"，让超配可见 | strategy_design.py:686 附近 | 20min |

### 4.3 P2 观察项（不阻塞）

| 编号 | 备注 |
|---|---|
| R143 TTL 分级生效 | mootdx circuit OPEN 16 周期，cooldown_secs=600 | 
| R143 mark_excluded 去连坐生效 | `/admin/llm-excluded` 1 条 |
| R146/R147-FIX/R148/R149/R150 | 待交易时段复测 |

### 4.4 测试防护体系缺口分析（强制）

#### 4.4.1 防护体系现状盘点

| 防护层 | 状态 | 能抓什么 / 抓不到什么 |
|---|---|---|
| 后端 pytest | 2796 → 2804 → 持续绿 | 单测覆盖单函数行为；抓不到「分配器+编排层+风控层」端到端总仓位合规 |
| verify_e2e.py | 80/105 FAIL（含 502 风暴尾） | 抓不到非空 PASS 形态——已知 known-env-issues §1.1 风暴态归类为 STORM_SKIP，**但仍把 502 状态码当作 FAIL**（错误归类）；实际 HTTP 200 通过的也因 storm 连坐被错判 FAIL |
| data_health_check.py | 10/10 PASS | 数据源可达 + 因子填充率 |
| patrol.py --diff | L1 2804 PASS / L2 FAIL (DB 损坏 + design 空) | 整合检查；但本轮因 R140 真实回归未被发现（说明现有单测覆盖了 cap 代码本身但未覆盖 cap 后后续步骤） |
| pre-commit | 16 段门禁（密钥扫描 / check_routes / mypy / pytest / smoke_startup / vitest 等） | 阻断 build 错误；抓不到业务正确性 |
| 前端 npm test | 全部绿 | UI 组件 |
| LHCI / Lighthouse | 本轮因 sandbox EPERM 失败 | — |

**门禁自身可信度**：
- verify_e2e.py 触发 storm 守卫后，未发包也归类为 502 FAIL（80/105 中至少 50 项是脚本内部误判，非真实 502）
- 已知漏洞：单测覆盖 `_enforce_layer_budget_final` 但没覆盖**调用顺序中 `apply_risk_controls` 之后的二次回补**

#### 4.4.2 逐发现映射

| 发现 | 最应拦截的防护层 | 为何未识别 | 应补的守卫 |
|---|---|---|---|
| **R152 R140 未生效** | 端到端「设计输出校验」 | 单测测 cap 函数本身，**没测** `apply_risk_controls` 后状态是否仍合规 | 新增 e2e 断言：拉 design 12 的 strategies[*].etfs，按 layer 分组求和，断言 `Σsatellite ≤ budget_satellite + 0.01`、`Σtotal_weight ≤ 1.0 + 0.01` |
| R146/R147/R148/R149/R150 zero_ratio | data_health_check | 现状只统计 valid/warn/no_data/static 计数，**没断言**关键因子（premium_discount/ln_mcap/shares_change）必须非全空 | data_health_check 加项：`assert not all([zero_ratio[code] >= 1.0 for code in CRITICAL_FACTOR_CODES])`；捕获"全断链"回归 |
| R157 「组合为空」| patrol / verify_e2e | 现状只测 "/strategy-checks 返回 200" | 加断言：检查最新 report_text **不含** "组合为空" 字样（或 portfolio_etfs shares_held=NULL 数 == 0） |
| R160 mark_excluded 不真正生效 | /admin/llm-excluded 端到端 | 现状：列表非空即视为"已治理"——**未验证**真实 token_usage 不再累计 | 加端到端断言：mark_excluded 一条 → 等 60s → 调一次 _try_llm → by_model 该模型 calls 不增长 |
| R161 design_text 不显示超配 | 无 | 无现有检查设计文本内容 | 新增：解析 design_text，找"卫星层 N%"，与 DB 实际 sat_sum 对比，不一致时 FAIL |

#### 4.4.3 系统性根因归并

| 根因分类 | 本轮新出现 | 已归纳未收敛 |
|---|---|---|
| **端到端层权重合规断言缺失** | R152 | round31 / round38 R131 已归纳（R140 二次校验失效） |
| **关键因子"全断链"数据健康断言缺失** | R146/R147/R148/R149/R150 | round31 factor-no-data 专题 |
| **"治理已生效"语义与"实际生效"语义混淆** | R160 mark_excluded | round39 R143（已归纳未收敛） |
| **报告内容 vs DB 数据一致性断言缺失** | R161 design_text | round31 R107（已归纳未收敛） |
| **门禁自身脚本 bug 把非错误归类为 FAIL** | verify_e2e 502 风暴误判 | known-env-issues §1.1（部分已修，仍残留） |

总体评价：**防护体系结构性缺一层「端到端业务不变量校验」**——单测覆盖每个组件，verify_e2e 覆盖 HTTP 200/契约，但**没人校验「端到端输出的业务不变量（如总仓位 ≤ 1.0）」**。这是 R140 回归的核心漏洞。

#### 4.4.4 补齐设计（只写方案，不写代码）

| 方案 | 描述 | 守卫位置 | 验收（含负向） |
|---|---|---|---|
| **方案 A**（推荐）端到端业务不变量校验 | 新增 `scripts/verify_allocation_invariants.py`：拉 `/api/v1/portfolio/designs?limit=5`，对每个设计的 strategies[*].etfs 计算层预算合规性，断言 `Σlayer ≤ budget[layer]+0.01 ∧ Σtotal ≤ 1.0+0.01`；输出到 pre-commit 第 17 段门禁（待讨论）或 patrol.py L2-alloc-invariants | scripts/ + patrol.py L2 | 负向断言：手动改 cap 日志绕过二次校验 → 本校验 FAIL |
| **方案 B**（推荐）data_health_check 加因子断链断言 | data_health_check.py 末尾增：拉 `/api/v1/factors/active`，读 zero_ratio，对关键因子（premium_discount / ln_mcap / ln_float_mcap / shares_change / industry_diversification）断言 `zero_ratio < 1.0`；输出非交易时段「待复测」标注而非 FAIL（避免误报 round31 R4-07 教训） | scripts/data_health_check.py | 负向：手动把某因子改为全空 → 本断言 FAIL |
| **方案 C**（推荐）mark_excluded 端到端断言 | 新增 patrol.py L2-llm-exclusion：在连续 5 分钟内观察 by_model.calls 增量，断言 `excluded_provider_model` 的 calls 增量 == 0；输出 mark_excluded 真正生效与否 | scripts/patrol.py | 负向：人为添加一条 excluded 但仍调用 → 增量 > 0 → FAIL |
| **方案 D**（推荐）verify_e2e 修复 storm 守卫归类 | 修改 verify_e2e.py _storm_guarded_request：风暴态激活后输出 STORM_SKIP 而非 `HTTP 502` 字样；让 `check()` 收到 `ConnectionError("[storm-fast-skip]")` 时归类为 SKIP 不为 FAIL | scripts/verify_e2e.py | 负向：storm 激活 → 后续检查全部 SKIP 不 FAIL |
| **方案 E**（推荐）组合 shares_held 默认 0 | portfolio_seed.py 灌录时 shares_held 默认 0 而非 NULL；策略检查走非空路径 | backend/scripts/portfolio_seed.py | 负向：shares_held=NULL → "组合为空" → 报告简化但仍可用 |

---

## 5. 已采纳方案（决策已锁定，2026-08-30）

> 用户拍板「**采纳建议，先更新文档，暂不实施**」。本节将原"决策点"小节升级为方案锁定。
> **实施触发条件**：用户说「开始实施」才进入实施轮；本轮仅方案入档。

| 项 | 采纳方案 | 推荐方案 | 影响文件 | 工作量 | 验证窗口 |
|---|---|---|---|---|---|
| **R140 修复未生效** | ✅ **方案 A**（待实施） | `apply_risk_controls` 处理完后、最终返回前，再加一次 `_enforce_layer_budget_final` 兜底（call site 后置） | `backend/app/services/strategy_design.py` 行 451 后插入 | A=10min + 单测 | 实施后 next design 三方案 sat ≤ budget + 总仓位 ≤ 1.0 |
| **R160 mark_excluded 真正排除** | ✅ **方案 B**（待实施） | 在 token_usage 持久化层加 excluded 自检：LLM 调用前查 `is_excluded()`，True 则直接拒绝（标记 excluded_skip） | `llm/gates.py` 或 `llm/client.py` | 30min + 单测 | 实施后 60s 观察 by_model.deepseek-v4-flash-free calls 增量==0 |
| **R157 组合「目标权重」语义** | ✅ **方案 A**（文档化） | README + docs/ 中说明组合是"目标权重配置"非"实际交易持仓"；策略检查输出"无可操作标的"是诚实状态 | `README.md` + `docs/portfolio-semantics.md`（新） | 5min | 文档生效后无需回归测试 |
| **R146/R147-FIX/R148/R149/R150 因子断链** | ⏸️ **挂起，待交易时段复测** | 方案已入档 §4.1；下一个交易日 9:30-11:30/13:00-15:00 窗口复测 | `factor_registry.py` / 新增 `fetchers/fund_share_fetcher.py` | 5-60min + 单测 | 交易时段复测 zero_ratio < 1.0 |
| **测试防护方案 A**（verify_allocation_invariants.py） | ✅ **采纳**（并入下一轮） | 端到端业务不变量校验（层预算 + 总仓位合规） | `scripts/verify_allocation_invariants.py`（新）+ patrol.py L2 | 30min + 单测 | 实施后手动改 cap 绕过二次校验 → 断言 FAIL |
| **测试防护方案 B**（data_health_check 因子断链断言） | ✅ **采纳**（并入下一轮） | data_health_check.py 末尾增 zero_ratio < 1.0 断言（CRITICAL_FACTOR_CODES） | `scripts/data_health_check.py` | 10min | 实施后手动把某因子改全空 → 断言 FAIL |
| **测试防护方案 C**（mark_excluded 自检端到端） | ✅ **采纳**（并入下一轮） | patrol.py L2-llm-exclusion：60s 观察 by_model.calls 增量 == 0 | `scripts/patrol.py` | 30min | 实施后人为添加 excluded 但仍调用 → 增量 > 0 → FAIL |
| **测试防护方案 D**（verify_e2e storm 守卫归类） | ✅ **采纳**（并入下一轮） | 修改 `_storm_guarded_request` 风暴态激活后输出 STORM_SKIP 而非 `HTTP 502` 字样 | `scripts/verify_e2e.py` | 15min | 实施后 storm 激活 → 后续检查全部 SKIP 不 FAIL |
| **测试防护方案 E**（组合 shares_held=0） | ❌ **不采纳** | 决策点 R157 选 A（文档化），方案 E 不需要 | — | — | — |

### 5.1 推荐实施顺序（两批次）

**批次 ① — 短期止血（1-2h，预计 round40）**：
1. 决策 1 方案 A（R140 `apply_risk_controls` 后加二次 enforce）
2. 决策 2 方案 B（mark_excluded call-site 守卫前置）
3. 测试防护方案 D（verify_e2e storm 守卫归类修复）
4. 测试防护方案 B（data_health_check 因子断链断言）

**批次 ② — 中期（待交易时段复测后，预计 round41）**：
1. 测试防护方案 A（verify_allocation_invariants.py 端到端校验）
2. 测试防护方案 C（mark_excluded 自检端到端断言）
3. 决策点 R157 组合语义文档化
4. R146/R147-FIX/R148/R149/R150 因子断链修复（需交易时段数据）

**批次 ② 启动条件**：等到下一个交易日 9:30-11:30/13:00-15:00 期间复测因子 zero_ratio，确认非交易时段是 root cause 还是其他问题。

### 5.2 风险与备选

- 如果方案 A（R140）实施后再次发现 cap 未触发，**fallback 是方案 B**——此时已锁定嫌疑路径（apply_risk_controls 后某步推超 sat），1-2h 排查成本可接受
- 决策 2 方案 B 实施时需小心：`is_excluded()` 检查要放在**调用前**而非**统计后**，否则历史累积仍会被计入
- 测试防护方案 D 需确认 fix 不影响 known-env-issues §1.1 的真实风暴态捕获（应区分"脚本自身 bug 误判"和"真实风暴"）
- 决策点 R157 选 A 文档化后，未来如需补 shares_held 实际数据（接入券商对账），按 R157 选 B 路径走**新灌录**——不要改存量数据（避免破坏组合历史）


---

## 6. Review 三轮（阶段 5）

### 6.1 Round 1（事实核对）

逐项核对 file:line + 数字 + commit：

| 项 | 文档说法 | 代码/数据实测 | 一致? |
|---|---|---|---|
| R152 cap 日志 `R131 satellite layer capped: 0.220 -> 0.220` | container docker logs 取值 | docker logs --tail 500 etf_surge-backend-1 grep "R131\|R140" | ✅ |
| R154 design 12 三方案 sat 总权重 | sat=0.200/0.300/0.350 | DB strategies_json 实证 | ✅ |
| R155 市态 range_bound | strategy_check_records.id35-38 regime=range_bound | docker logs `[pool] regime updated for A: range_bound` 11:24:10 | ✅ |
| R158 DB integrity=ok | journal_mode=delete, sync=2 | `docker exec ... sqlite3 PRAGMA integrity_check` 返回 ok | ✅ |
| R159 IC distinct=503 | 范围 2024-08-06 ~ 2026-08-30 | `SELECT COUNT(DISTINCT trade_date) FROM factor_ic_records` 返回 503 | ✅ |
| R160 deepseek-v4-flash-free 22037 calls | 错误率 59.3% | `/admin/token-usage` by_model 实测 | ✅ |
| R161 design 12 design_text "≈5%" | 与 etfs.weight=0.05 一致 | API 响应 + DB strategies_json | ✅ |
| 2b1c8c7 commit（2026-08-27 17:07） | R139+R140+R141 实施 | git show --stat 2b1c8c7 | ✅ |
| 128aefb commit（2026-08-28 11:16） | R146+R147-FIX+R148+R149+R150 实施 | git log | ✅ |

事实核对全 PASS。

### 6.2 Round 2（逻辑一致性 + 内部矛盾检查）

| 检查项 | 结论 |
|---|---|
| R152 自洽：cap 日志 0.220→0.220 (缩放系数=1.0) ↔ sat=0.300 (DB 持久化) ↔ 总仓位 1.030>1.0 | ✅ 三者互相印证：cap 函数被调用但未真正缩放；后续步骤把 sat 推回到 0.300 |
| R158 自洽：integrity=ok ↔ journal_mode=delete ↔ sync=2 | ✅ 三者一致 |
| R159 自洽：IC distinct=503 ↔ 范围 2024-08-06 ~ 2026-08-30 ↔ 总行数 10307 | ✅ 一致（distinct=503，MIN/MAX 跨度 755 天但 IC 累计 503 个交易日） |
| R160 自洽：mark_excluded 列表 1 条 ↔ by_model 调用 22037 次 | ✅ "已治理"语义与"实际生效"语义混淆——列表非空不代表真实排除 |
| R161 自洽：design_text "≈5%" ↔ etfs.weight=0.05 | ✅ 一致；但 design_text **未暴露** sat 实际 30% vs 预算 22% 的偏差 |

逻辑一致性 PASS，无内部矛盾。

### 6.3 Round 3（完整性 + 文档结构）

| 章节 | 完整性 | 备注 |
|---|---|---|
| §0 执行摘要 | ✅ | 核心结论 + 关键判定表 + 验证窗口标注 |
| §1 环境构建与启动 | ✅ | Docker / 构建 / 容器 / liveness / DB / LLM / 镜像回收 |
| §2 对照验证矩阵 | ✅ | 4 子矩阵（R34-R108 / R35+R36+R37 / R38 / R143） |
| §3 四问法质量审查 | ✅ | 逐条 + 数据准确性抽查 + 汇总 |
| §4 修复方案 + 缺口分析 | ✅ | P0/P1/P2 + 5 类缺口 + 5 项补齐方案 |
| §5 决策点 | ✅ | 5 项待拍板 |
| §6 Review | ✅ | 本节（事实/逻辑/完整性） |

未决项：
- R146/R147/R148/R149/R150 因子断链——非交易时段无法实测
- R160 mark_excluded 真正生效——需要追查累计层

风险点：
- **R152 P0（核心回归）**：必须下轮解决
- **R160 P1（治理假象）**：影响 token 成本估算准确性
- **R157 P3（已知设计）**：仅文档化问题

文档结构完整，三轮 review 全部 PASS。

---

## 7. 证据清单

| 文件 | 内容 |
|---|---|
| data/lh_r39_home.json | Lighthouse 首页（**本轮未跑：sandbox EPERM**） |
| tmp_diag/fa.json | /factors/active 完整响应 |
| tmp_diag/model.json | /factors/model 完整响应（193 总/38 implemented/155 planned） |
| tmp_diag/designs.json | /portfolio/designs?limit=5 |
| tmp_diag/checks.json | /portfolio/strategy-checks?limit=5 |
| tmp_diag/d12_full.json | /portfolio/designs/12 完整响应 |
| tmp_diag/rt_port.json | /market/realtime/portfolio 38 ETF |
| tmp_diag/token.json | /admin/token-usage（含 by_model 错误率分解） |
| tmp_diag/llm_excluded.json | /admin/llm-excluded（1 条 excluded） |
| tmp_diag/cb.json | /admin/sources/circuit-breakers |
| tmp_diag/sources.json | /admin/sources/health（mootdx OPEN） |
| tmp_diag/tp.json | /admin/thread-pool |
| DB 直接查询 | factor_ic_records distinct=503 / portfolio_designs id=12 / strategy_check_records id=37 |

---

## 8. 下一步（决策已锁定，待"开始实施"指令）

> 用户已于 2026-08-30 拍板「**采纳建议，先更新文档，暂不实施**」。本节列"已锁定方案 → 待实施触发"清单。

| 项 | 决策 | 状态 | 触发条件 |
|---|---|---|---|
| R140 修复追查 | ✅ **方案 A** 已锁定（`apply_risk_controls` 后加二次 enforce） | 🟡 待实施 | 用户说"开始实施" |
| R160 mark_excluded 真正排除 | ✅ **方案 B** 已锁定（call-site 守卫前置） | 🟡 待实施 | 与 R140 同批实施（批次①） |
| 测试防护方案 B/D | ✅ 已采纳（data_health_check 因子断链 + verify_e2e storm 守卫归类） | 🟡 待实施 | 批次① |
| R157 组合「目标权重」语义 | ✅ **方案 A** 已锁定（文档化） | 🟡 待实施 | 批次②（中期） |
| 测试防护方案 A/C | ✅ 已采纳（端到端不变量校验 + mark_excluded 自检） | 🟡 待实施 | 批次② |
| R146/R147-FIX/R148/R149/R150 因子断链 | ⏸️ 挂起 | 🟡 待交易时段复测 | 下一个交易日 9:30-11:30/13:00-15:00 窗口 |
| 文档归档 | 🟢 可随时执行 | ⏸ 待 review 通过 | 用户指示 |

### 8.1 实施批次（建议）

**批次① — 短期止血（1-2h，round40 预计）**：
1. R140 方案 A（10min + 单测）
2. R160 方案 B（30min + 单测）
3. 测试防护 D（verify_e2e storm 守卫归类，15min）
4. 测试防护 B（data_health_check 因子断链断言，10min）

**批次② — 中期（待交易时段复测后，round41 预计）**：
1. 测试防护 A（verify_allocation_invariants.py，30min + 单测）
2. 测试防护 C（mark_excluded 自检端到端断言，30min）
3. R157 组合语义文档化（5min）
4. R146/R147-FIX/R148/R149/R150 因子断链修复（5-60min + 单测）

**批次③ — 测试卫生（独立 round42，1-2h + 单测，§10.7 已锁定）**：
1. 合并 4 个重叠 R 文件 → 业务命名测试（-9 用例）：
   - R141 → `test_strategy_check_table_score.py`
   - R148 → `test_industry_diversification_reason.py`
   - R42+R146 → `test_factor_compute_injects_mv.py`
2. 重命名 28 个独立 R 文件 → `test_<module>.py`：
   - 例：`test_r39_circuit_fixes.py` → `test_llm_circuit_ttl_grading.py`
   - 每个新文件顶部加 docstring `"""@roundXX {ref} — {原功能描述}"""`
3. 验证：pytest 全量（持平）+ mypy 零新增 + pre-commit 通过
4. commit message：`test: merge 4 overlapping test_rXXX + rename 28 to business-named (refs round39 §10.7)`

详细方案与影响文件见 §5 已采纳方案表 + §10.7 测试合并清单。

---

## 9. 附：本轮未做的事（Out of scope）

> 本轮为「**方案轮**」——仅写方案，不写修复代码。用户于 2026-08-30 拍板「**采纳建议，先更新文档，暂不实施**」。

- ❌ 不写修复代码（用户拍板"暂不实施"）
- ❌ 不 commit / push
- ❌ 不追查 R140 推超的精确代码路径（仅锁定 suspect `apply_risk_controls` / `_consolidate_minnows` / cash_weight）
- ❌ 不重写设计 12 的 strategies_json（避免污染数据）
- ❌ 不动 verify_e2e.py 的 storm 守卫（已知 known-env-issues §1.1 已部分记录）
- ❌ 不接 SZSE/SSE 份额源（R147-FIX，仅方案）
- ❌ 不动 Lighthouse 评分（sandbox EPERM，环境性问题）


---

## 10. 测试代码冗余排查 + R 编号测试合并方案

> **触发（2026-08-30）**：用户提出「看看测试代码是否存在冗余？并把 test_rXXX 这样命名的测试代码都合并到业务命名的测试代码中，先不实施，梳理一下方案」。
> 本节为方案入档，不实施。

### 10.1 现状盘点

- `backend/tests/` 共 **293 个测试文件**
- `test_r{数字}_*.py` 命名（R 系列编号追溯）**32 个 / 4428 行**
- 这些文件按 R{编号} 对应 round 文档的某修复项的"行为锚测试"

| 文件 | 行数 | 主模块 | 内容描述 |
|---|---:|---|---|
| test_r39_circuit_fixes.py | 234 | analysis/llm/gates | circuit TTL 分级 + mark_excluded 接通 |
| test_r40_b_ai_provider.py | 191 | analysis/llm/provider | b.ai whitelist provider 接入 |
| test_r42_nav_pool_isolation.py | 166 | factors/factor_registry | `_inject_nav` 线程池/Semaphore 隔离 |
| test_r43_excluded_review.py | 84 | analysis/llm/scripts | review 脚本只读 mark_excluded |
| test_r45_nav_redis_cache.py | 299 | services/redis_cache_sync | NAV Redis 缓存治本（独立模块） |
| test_r49_warmup_market_cache_timeout.py | 99 | main | warmup_market_cache timeout 10→25 |
| test_r49_warmup_two_phase.py | 237 | main+market_data_hub | 两阶段预热 |
| test_r50_off_exchange_concurrent.py | 222 | services/portfolio_service | off_exchange 并发 |
| test_r74_factor_wording.py | 80 | analysis/signal | composite_signal 主驱动因子用语修正 |
| test_r85_factor_hub_cache.py | 129 | factors/factor_registry + market_data_hub | hub 缓存读取 |
| test_r86_kline_cache_path.py | 37 | main | kline 缓存路径 |
| test_r87_component_coverage.py | 109 | services/portfolio/strategy_check | `_component_coverage_stats` 函数 |
| test_r88_stock_kline_warmup.py | 63 | main | stock kline warmup |
| test_r89_fast_json_prefetch.py | 66 | main | fast_json 预取默认开关 |
| test_r90_news_classification.py | 82 | fetchers/levistock_fetcher | keyword expansion |
| test_r91_static_a_stock_base.py | 76 | routers/market | 静态 A 股基底 |
| test_r92_realtime_contract.py | 151 | routers/market | realtime contract |
| test_r93_data_dir_container.py | 59 | main | data_dir 容器路径 |
| test_r94_momentum_cross_path.py | 107 | services/market_data_hub | momentum 双路径一致 |
| test_r95_report_number_consistency.py | 133 | services/portfolio/strategy_check | 报告数值一致性 |
| test_r96_factor_data_quality.py | 221 | factors | factor_data_quality 双维口径 |
| test_r97_stock_search_fallback.py | 153 | fetchers/sync_instruments | sync_instruments 超时回退 |
| test_r98_news_global_summary.py | 82 | fetchers/levistock_fetcher | 英文 keyword expansion |
| test_r102_sina_datalen.py | 69 | fetchers/china_market | sina datalen 500/240 |
| test_r103_mixed_depth_rows.py | 129 | main | IC 回填深度混合处理 |
| test_r105_anchor_survives_degraded.py | 354 | engine/allocation_engine | 强制锚在降级态存活 |
| test_r140_layer_budget_final.py | 138 | engine/allocation_engine | sat 层最终 enforce (round39 实证未生效) |
| test_r141_table_score_fallback.py | 111 | services/portfolio/strategy_check | 报告表格因子分 fallback |
| test_r142_non_strict_monotonic.py | 196 | engine/allocation_engine | INV-3/5 非严格单调放宽 |
| test_r146_nav_inject.py | 77 | factors/factor_registry | nav IOPV 三级链注入 |
| test_r147_fund_share_fetcher.py | 196 | fetchers/fund_share_fetcher | SZSE/SSE 份额接入 |
| test_r148_industry_diversification.py | 78 | factors/factor_registry | industry_diversification 1/(1+n) |

### 10.2 重叠识别（4 类）

#### 10.2.1 高度重叠（同函数同场景）

| R 文件（用例数） | 业务命名测试（用例数） | 重叠原因 | 业务命名测试所在文件 |
|---|---|---|---|
| test_r141_table_score_fallback.py（3） | test_strategy_check_table_score.py（6） | 都测 `_build_rule_fallback_report` 中 `composite_score` 缺失/为 0 时的表格列回退；R141 是子集 | services/portfolio/strategy_check.py |
| test_r148_industry_diversification.py（7） | test_industry_diversification_reason.py（6） | 都测 `_compute_industry_diversification` 在 concepts / industry_holdings 不同输入下的返回值；几乎完全重复 | factors/factor_registry.py |

#### 10.2.2 部分重叠（同函数不同角度）

| R 文件（用例数） | 业务命名测试（用例数） | 重叠原因 | 业务命名测试所在文件 |
|---|---|---|---|
| test_r42_nav_pool_isolation.py（6） | test_r146_nav_inject.py（3）+ test_factor_compute_injects_mv.py（3） | 都涉及 `_inject_nav`；R42 测线程池/Semaphore/timeout，R146 测 IOPV 注入，test_factor_compute_injects_mv.py 测 mv 字段注入 | factors/factor_registry.py |
| test_r146_nav_inject.py（3） | test_factor_compute_injects_mv.py（3） | 都测 `_inject_nav` 路径但 R146 是 IOPV 三级链 | factors/factor_registry.py |

#### 10.2.3 无重叠（保留独立测试）

27 个 R 编号文件无对应业务命名测试重复：
- test_r39 / r40 / r43 / r45 / r49(timeout+two_phase) / r50 / r74 / r85 / r86 / r87 / r88 / r89 / r90 / r91 / r92 / r93 / r94 / r95 / r96 / r97 / r98 / r102 / r103 / r105 / r140 / r142 / r147

### 10.3 合并方案

#### 方案 A（推荐）：合并 + 重命名双轨并行

**步骤 1：合并高度/部分重叠的 4 个 R 文件**
- 删除 `test_r141_table_score_fallback.py` 3 用例 → 增补到 `test_strategy_check_table_score.py`（最终 9 用例）
- 删除 `test_r148_industry_diversification.py` 7 用例 → 增补到 `test_industry_diversification_reason.py`（最终 13 用例，新增 R148 1/(1+n) 单调递减断言）
- 删除 `test_r42_nav_pool_isolation.py` 6 用例 + `test_r146_nav_inject.py` 3 用例 → 增补到 `test_factor_compute_injects_mv.py`（按"线程池路径 / IOPV 路径 / mv 字段路径"三段组织，最终 ~12 用例）

**步骤 2：保留独立的 28 个 R 文件 → 业务命名重命名（去掉 R{数字} 前缀）**
- 例：`test_r39_circuit_fixes.py` → `test_circuit_ttl_grading.py`（或 `test_llm_circuit_ttl_grading.py`）
- 例：`test_r40_b_ai_provider.py` → `test_llm_whitelist_provider.py`
- 例：`test_r45_nav_redis_cache.py` → `test_nav_redis_cache.py`
- 命名规则：以**业务模块/功能**为主键，不带 R 编号（保留 round 关联用 docstring 注释 `@round40 round38 §11.3` 之类）

**步骤 3：保留 `test_r147_fund_share_fetcher.py` 不重命名**
- 因为该文件测的是**新模块 `app/fetchers/fund_share_fetcher.py`**——业务命名可改 `test_fund_share_fetcher.py`，但该模块没有业务命名测试（新增独立模块的回归测试），重命名价值不大；保留或统一由步骤 2 决定

#### 方案 B（备选）：纯合并不重命名

只做步骤 1（合并 4 个重叠 R 文件），其余 28 个 R 编号文件**保留命名**不动。

**方案 B 的优点**：
- 工作量最小（10min + 单测）
- 风险最低（不引入命名争议）
- 保留"按 R 编号追溯修复"的便利性

**方案 B 的缺点**：
- 命名冗余未根治——R 编号命名 vs 业务命名二套并存
- 新增测试易倾向复制 R 编号命名（既有约定）

#### 方案 C（保守）：仅"明确重叠"合并

只合并 10.2.1 高度重叠的 2 个文件（R141 + R148），其余不动。
- R42 + R146 因"同函数不同角度"保留为独立测试（用 docstring 说明）

### 10.4 推荐对比

| 维度 | 方案 A | 方案 B | 方案 C |
|---|---|---|---|
| 工作量 | 1-2h + 单测 | 30min + 单测 | 15min + 单测 |
| 风险 | 中（命名迁移需协调） | 低 | 最低 |
| 根除冗余 | ✅ | ❌ | ❌（仅 2 项） |
| 命名一致性 | ✅ | ❌ | ❌ |
| 测试用例数变化 | -9（合并）+ 0（重命名）= -9 | -9 | -9（合并）= -9 |
| 现有 pytest 全量（2804+） | 持平 | 持平 | 持平 |
| 推荐度 | ⭐⭐⭐ 推荐 | ⭐⭐ | ⭐ |

### 10.5 落地步骤（方案 A）

1. **合并 4 个 R 文件**：
   - `test_r141_table_score_fallback.py`（3 用例）→ 增补到 `test_strategy_check_table_score.py`
   - `test_r148_industry_diversification.py`（7 用例）→ 增补到 `test_industry_diversification_reason.py`
   - `test_r42_nav_pool_isolation.py`（6 用例）+ `test_r146_nav_inject.py`（3 用例）→ 增补到 `test_factor_compute_injects_mv.py`（按路径分 3 段）
2. **重命名 28 个独立 R 文件**（去掉 R 编号，保留业务名）：
   - 主键：业务模块/功能
   - 命名规则：`test_<module_or_feature>.py`
   - 内部 docstring 标注 `@round{num} {ref}` 保留追溯链
3. **执行迁移**：
   - `git mv` 保留历史
   - 同步更新 CI / patrol / pytest.ini 等引用（如有）
   - 跑 pytest 全量验证（持平绿即可）
4. **commit message 规范**：英文 `test: rename test_rXXX to business-named + merge overlapping (refs docs/round39 §10.5)`（注意 `.githooks/commit-msg` 钩子强制英文）

### 10.6 已采纳方案（决策已锁定，2026-08-30）

> 用户已拍板（2026-08-30）。本节将原"决策点"小节升级为方案锁定。
> **实施触发条件**：用户说「开始实施」才进入实施轮；本轮仅方案入档。

| 项 | 采纳方案 | 影响范围 | 工作量 |
|---|---|---|---|
| **合并范围** | ✅ **方案 A**（合并 4 + 重命名 28） | 4 文件合并到业务命名测试；28 文件重命名去掉 R 编号前缀 | 1-2h + 单测 |
| **重命名规则** | ✅ **业务模块名**（`test_<module>.py`） | 例：`test_r39_circuit_fixes.py` → `test_llm_circuit_ttl_grading.py` | — |
| **重命名追溯** | ✅ **docstring + git 历史** | 每个重命名后的测试顶部加 `@roundXX {ref}` 注释；`git mv` 保留历史 | — |
| **落地时机** | ✅ **独立 round42**（与 R140 修复批次解耦） | round42 文档入档 + git commit + pre-commit 验证 | — |

### 10.7 落地计划（已锁定，2026-08-30）

**方案 A（合并 4 + 重命名 28）** + **业务模块名规则** + **docstring + git 追溯** + **独立 round42 落地**：

- 工作量合理（1-2h + 单测）
- 根除冗余 + 命名一致性双达成
- 独立 round 可与 R140 修复批次解耦，不增加风险
- docstring 追溯保留 round 关联（`@round39 round38 §11.3` 之类）

**为什么落地时机为独立 round42**：
- 测试重命名会影响 CI / pre-commit 的发现路径（pytest 默认 glob 模式可能需更新）
- R140 修复（批次①）紧迫，独立 round 可控风险
- 测试整理是"卫生"任务，与"止血"任务分开

### 10.7.1 合并 4 个 R 文件的落地清单（已锁定）

| 源文件 | 用例数 | 目标文件 | 合并后用例数 | 业务模块 |
|---|---:|---|---:|---|
| test_r141_table_score_fallback.py | 3 | test_strategy_check_table_score.py | 9 | services/portfolio/strategy_check |
| test_r148_industry_diversification.py | 7 | test_industry_diversification_reason.py | 13 | factors/factor_registry |
| test_r42_nav_pool_isolation.py | 6 | test_factor_compute_injects_mv.py | ~12（线程池/IOPV/mv 三段） | factors/factor_registry |
| test_r146_nav_inject.py | 3 | test_factor_compute_injects_mv.py | （同上） | — |

### 10.7.2 重命名 28 个 R 文件清单（已锁定，待 round42 实施）

| 源文件 | 目标名（业务模块名） | 主键模块 | 用途追溯（保留在 docstring） |
|---|---|---|---|
| test_r39_circuit_fixes.py | test_llm_circuit_ttl_grading.py | analysis/llm/gates | @round39 round38 §11.4 |
| test_r40_b_ai_provider.py | test_llm_whitelist_provider.py | analysis/llm/provider | @round40 round38 §11.5 |
| test_r43_excluded_review.py | test_llm_mark_excluded_review.py | analysis/llm/scripts | @round43 round39 §3 |
| test_r45_nav_redis_cache.py | test_nav_redis_cache.py | services/redis_cache_sync | @round45 round39 §3 |
| test_r49_warmup_market_cache_timeout.py | test_warmup_market_cache_timeout.py | main | @round49 round49 §A4 |
| test_r49_warmup_two_phase.py | test_warmup_two_phase.py | main+market_data_hub | @round49 round49 §A4-C |
| test_r50_off_exchange_concurrent.py | test_off_exchange_concurrent.py | services/portfolio_service | @round50 round50 §B2 |
| test_r74_factor_wording.py | test_signal_composite_reason.py | analysis/signal | @round74 round22 |
| test_r85_factor_hub_cache.py | test_factor_hub_cache.py | factors + market_data_hub | @round85 round22 |
| test_r86_kline_cache_path.py | test_kline_cache_path.py | main | @round86 round22 |
| test_r87_component_coverage.py | test_strategy_check_component_coverage.py | services/portfolio/strategy_check | @round87 round34 |
| test_r88_stock_kline_warmup.py | test_stock_kline_warmup.py | main | @round88 round34 |
| test_r89_fast_json_prefetch.py | test_fast_json_prefetch.py | main | @round89 round34 |
| test_r90_news_classification.py | test_levistock_keyword_expansion.py | fetchers/levistock_fetcher | @round90 round34 |
| test_r91_static_a_stock_base.py | test_static_a_stock_base.py | routers/market | @round91 round34 |
| test_r92_realtime_contract.py | test_market_realtime_contract.py | routers/market | @round92 round34 |
| test_r93_data_dir_container.py | test_data_dir_container.py | main | @round93 round34 |
| test_r94_momentum_cross_path.py | test_market_data_hub_momentum.py | services/market_data_hub | @round94 round34 |
| test_r95_report_number_consistency.py | test_strategy_check_report_consistency.py | services/portfolio/strategy_check | @round95 round34 |
| test_r96_factor_data_quality.py | test_factor_data_quality.py | factors | @round96 round34 |
| test_r97_stock_search_fallback.py | test_sync_instruments_fallback.py | fetchers/sync_instruments | @round97 round34 |
| test_r98_news_global_summary.py | test_news_global_english_keyword.py | fetchers/levistock_fetcher | @round98 round34 |
| test_r102_sina_datalen.py | test_china_market_sina_datalen.py | fetchers/china_market | @round102 round34 |
| test_r103_mixed_depth_rows.py | test_ic_backfill_mixed_depth.py | main | @round103 round34 |
| test_r105_anchor_survives_degraded.py | test_allocation_anchor_degraded.py | engine/allocation_engine | @round105 round34 |
| test_r140_layer_budget_final.py | test_allocation_layer_budget_final.py | engine/allocation_engine | @round140 round38 §5.2 |
| test_r142_non_strict_monotonic.py | test_allocation_non_strict_monotonic.py | engine/allocation_engine | @round142 round38 §11.2 |
| test_r147_fund_share_fetcher.py | test_fund_share_fetcher.py | fetchers/fund_share_fetcher | @round147 round38 §11.3 |

**注**：重命名映射仅为初步建议（基于 §10.1 的主模块映射），round42 实施时可根据实际命名习惯微调。

### 10.7.3 实施步骤（round42 触发后）

1. **合并 4 个 R 文件**：
   - `test_r141_table_score_fallback.py`（3 用例）→ 增补到 `test_strategy_check_table_score.py`
   - `test_r148_industry_diversification.py`（7 用例）→ 增补到 `test_industry_diversification_reason.py`
   - `test_r42_nav_pool_isolation.py`（6 用例）+ `test_r146_nav_inject.py`（3 用例）→ 增补到 `test_factor_compute_injects_mv.py`（按"线程池路径 / IOPV 路径 / mv 字段路径"三段组织）
2. **重命名 28 个独立 R 文件**：
   - 使用 `git mv` 保留历史
   - 在每个新文件顶部加 docstring：`"""@round{num} {ref} — {原功能描述}"""`
   - 同步更新 CI / patrol / pytest.ini 等引用（如有）
3. **验证**：
   - pytest 全量（预期用例数 -9 = -9 个合并文件，无新增/删除）
   - mypy 零新增
   - pre-commit 门禁通过
4. **commit message**：
   - 英文 `test: merge 4 overlapping test_rXXX + rename 28 to business-named (refs round39 §10.7)`
   - 注意 `.githooks/commit-msg` 钩子强制英文

### 10.7.4 风险

- pytest 默认 glob 模式（`test_*.py`）应自动覆盖新文件名（test_*.py 通配），但需验证
- CI / pre-commit 钩子如果硬编码 test 路径，需同步更新
- patrol.py L1 引用具体测试文件名的，需检查更新

