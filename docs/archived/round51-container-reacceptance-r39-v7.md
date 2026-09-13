# round51 容器全链路诊断 — R39 方案落地复验 + round40-50 实施轮回归扫描（2026-08-31 周一盘后）

> 本文档为 **round39 方案落地后的复验轮**（独立 round51 文档，不改写被诊断的 round39/v7 文档）。
> 诊断对象：HEAD `a8bf0d3`（含 round40-46 + v7 P0-P3 共 18 commit，round39 之后全部落地代码）。
> 验证环境：Docker Engine 29.7.2，prod profile + diag overlay（PROFILE_WARMUP=1 cProfile）。
> 验证窗口：2026-08-31 周一 19:43-20:35（**盘后**，日频数据已发布；盘中实时类标注「待交易时段复测」）。
> 容器 19:42:57 启动，19:43:04 `/health` 200（0.02s）；三容器 Up 全程无重启。
> 探针产物：`C:/Users/Public/etf_probe/probe*.out`（1-16 全套，诊断临时目录不入仓）。

---

## 0. 执行摘要

> **决策状态（2026-08-31 用户拍板）**：**采纳方案 A-F 全部建议，先更新文档、暂缓实施**。
> 方案 A-F 状态 = 已采纳、待「开始实施」指令触发（AGENTS.md「未收到明确指令不得写修复代码」约定，与 round39 拍板模式一致）。
> **与 round39 最大差异**：round39 的 R140/R146-R150 结论全部基于 08-30 05:20 前的旧代码
> （R140 修复 commit `b2e6078` 于 08-30 13:31 落地，晚于 design 12-14 生成时刻）；
> 本轮**主动触发新数据**（design 15 + strategy_check 62/63）用当前 HEAD 代码复测，结论随之修正。
> **与 round39 最大差异**：round39 的 R140/R146-R150 结论全部基于 08-30 05:20 前的旧代码
> （R140 修复 commit `b2e6078` 于 08-30 13:31 落地，晚于 design 12-14 生成时刻）；
> 本轮**主动触发新数据**（design 15 + strategy_check 62/63）用当前 HEAD 代码复测，结论随之修正。

### 0.1 核心结论（一句话/项）

| # | 结论 | 状态 |
|---|---|---|
| 1 | **R140 层预算二次 enforce 生效**：design 15（HEAD 代码 20:07 触发）三方案 sat 全部 ≤ budget，无超配、无总仓位越界 | ✅ 修复确认 |
| 2 | **R141 表格因子分生效**：strategy_check 62（HEAD 代码触发）逐标的表格「因子分」列非零（-0.47 ~ +0.80），与 reason 引用同源 composite_score | ✅ 修复确认 |
| 3 | **round39 的 R146-R150「因子断链」结论系口径误用**：其证据 `/factors/active` 的 `zero_ratio` 挂在 `ic_tracker._zero_ratio`（app/factors/ic_tracker.py:242），口径为「参与 IC 计算批次样本」（no_data 因子仅 4 个交易日样本），**不是当前因子矩阵零值占比** → 「断链」判定证据链错位，需换口径重判（见 §2.3） | ⚠️ 结论修正 |
| 4 | **新发现 R162 现金悬空**：enforce 缩放卫星层后 cash 行不回补——design 15 balanced `total=0.9500`（cash 行 0.2300 vs expected 0.2800，GAP +0.05），aggressive `total=0.9752`（GAP +0.0248）→ 5%/2.5% 资金既不在持仓也不在现金 | ❌ P1 新发现 |
| 5 | **新发现 R163 target_amount 与权重脱节**：`_validate_target_amount_consistency`（strategy_design.py:692）在 R140 enforce（:707）**之前**执行，缩放后校验形同虚设——design 15 balanced 4 只标的 target_amount=50000/25000 vs 权重×资本=36650/18350（+36%） | ❌ P1 新发现 |
| 6 | **新发现 R165 NAV Redis 预热失效**：`/admin/lifespan-warmup` 报 `redis_unavailable`（3 周期 0 ok），但容器内实测 `redis_cache_sync.ping()=True`——根因 `RedisCacheSync._ensure_client` 失败缓存（cache_service.py:208-217 `_init_done=True` 后永不重试），warmup 首轮 ping 时 redis 未就绪，失败被永久缓存 → round45 option C（commit 853fcf2）治本目标实际未达成 | ❌ P1 新发现 |
| 7 | **新发现 R167 openrouter 错误信封误判**：`client.py:127 data["choices"]` 直取——openrouter 返 200-with-error-envelope 时 KeyError 被外层 `except Exception` 吞为 WARNING（日志 `failed after 2.8s: 'choices'`），且 reports.py:649 失败分类（只认 429/json 关键字）将其伪装成「LLM 分析超时」——本轮 strategy_check 62 实际因它触发规则兜底（非真超时） | ❌ P2 新发现 |
| 8 | **R160 mark_excluded 真生效**：180s 增量观察 excluded 模型 `deepseek-v4-flash-free` calls 增量=0（round44 方案 C 口径）；但其 by_model 累计 21706 次为历史存量，非新调用 | ✅ 修复确认 |
| 9 | **R139 DB 治理持续生效**：journal=delete/sync=2/integrity=ok，全程写入（designs 14→15、checks 61→63）无损 | ✅ 持续 |
| 10 | **verify_e2e 容器外挂死**（e2e.out 0 字节）= known-env-issues §1.1 `::1` 双栈已知问题（round39 同），单端点 curl 全 PASS 替代 | ⚠️ 环境性 FAIL（非回归） |
| 11 | **v7 三阶段落地核实**：P0 MCP 4 server（quote/factor/portfolio/news）+ P1 agent_loop/executor 护栏（白名单/循环检测/写确认/步数预算）+ P2 evals harness+ci_gate+trace_store 代码均在；金标集 18 条（demo 13 + quotes 5），未达 v7 §5 P1 目标 50 条 | ✅ 代码在 / ⚠️ 金标欠量 |
| 12 | **耗时退化**：factor-health 首呼 0.86s→3.92s、realtime/portfolio 0.37s→5.05s（详见 §2.4，登记性能债不阻断） | ⚠️ WARN |

### 0.2 验证矩阵（round39 → round51 对照）

| round39 项 | round39 预期 | 本轮实测（HEAD a8bf0d3） | 结论 |
|---|---|---|---|
| R140 sat 超配 | 修复后 sat ≤ budget | design 15（新触发）：balanced sat=0.22=budget ✓ aggressive sat=0.30=budget ✓ total ≤1.0 ✓ | ✅ **生效**（round39 ❌ 系旧代码产物） |
| R141 表格因子分 | 非零 | check 62 表格 -0.47~+0.80 非零、与 reason 同源 | ✅ **生效** |
| R146 premium_discount | nav 注入后非 0 | `/factors/active` zero_ratio=0.0（IC 4 日样本口径）；design15 实际 31 只全 0.0 | ⚠️ **口径修正**：no_data=IC 未达 60 日下限；矩阵值仍 0 待核（见 §2.3） |
| R147-FIX shares_change | 非 0 | IC 有值（ic=0.0179, 4 样本）+ 设计 breakdown 无该键 | ⚠️ 同上，待重判 |
| R148 industry_diversification | 非 0 | reason「截面无差异（常量输出）」+ design15 全 0 | ❌ 真断链（唯一有代码证据的） |
| R149 news_heat | 非 0 | `/factors/active` 报 static zero_ratio=1.0；design15 实际 31 只全 1.92 **非零** | ⚠️ 口径误用（实际已生效） |
| R150 ln_mcap | 非 0 | zero_ratio=1.0；design15 breakdown 无该键 | ❌ 真断链 |
| R139 DB DELETE | integrity=ok | delete/sync=2/ok，持续写入无损 | ✅ 持续 |
| R143 mark_excluded | excluded 停止调用 | 180s 增量=0（方案 C 实测）；存量 21706 为历史 | ✅ **真生效**（round39 ❌ 判定修正） |
| R151 20 warn 统计 | 积累 | summary valid=0/warn=20/no_data=6/static=12 | ✅ 与 round39 一致 |

### 0.3 耗时基线（fresh 容器 / 本轮实测）

| 端点 | 首呼 | warm | round39 基线 | 结论 |
|---|---|---|---|---|
| /health | 0.05s | 0.01s | 0.04s | ✅ |
| /api/v1/admin/factor-health | **3.92s** | 0.01s | 0.86s | ⚠️ 退化 4.5×（性能债） |
| /api/v1/market/realtime/portfolio | **5.05s** | 0.01s | 0.37s | ⚠️ 退化 13×（性能债；可能与 R146 nav 注入相关，待交易时段复测） |
| /api/v1/market/sectors/heat | 0.97s | 0.02s | 0.92s | ✅ |
| /api/v1/market/watchlist | 0.02s | 0.03s | 0.04s | ✅（items=0 空表，功能正常） |
| 其余 14 端点 | ≤0.5s | — | — | ✅（probe3.out 全录） |
| /admin/llm/health | — | — | 4.72s | ⚠️ 未复测（LLM 网关慢已知） |

### 0.4 LLM provider 现状（by_provider，HEAD 代码 26min 窗口）

| provider | calls | errors | err% | 评级 |
|---|---:|---:|---:|---|
| deepseek | 25692 | 1199 | 4.7% | ✅ 主源稳定 |
| opencode_zen | 26798 | 14757 | 55.1% | ❌ 503/21s 空响应频发 |
| openrouter | 623 | 321 | 51.5% | ❌ 403 + 'choices' KeyError（R167） |
| unknown | 605 | 450 | 74.4% | ❌ |
| b_ai | 31 | 10 | 32.3% | ⚠️ round40 新接入 |
| fake | 155 | 2 | 1.3% | — 测试流量 |

mark_excluded 实时性：180s 窗口内 excluded 模型增量=0（round44 方案 C 守卫实测通过）。

### 0.5 数据源状态（容器运行 ~50min 抽样）

| 数据源 | available | cooldown | 备注 |
|---|---|---|---|
| mootdx / sina / push2delay / tencent / sector_lv / concept_lv / sina_history / levistock | true | 60s | 8 源正常 |
| akshare / dongfang | false | 600s | 非交易时段冷却（round39 一致） |

---

## 1. 环境构建与启动（阶段 1）

| 项 | 结果 |
|---|---|
| 构建 | `docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod up --build -d`（pip 层全缓存命中，构建 <15s） |
| 容器 | backend(:8000)/frontend(:80)/redis(:6379) 三件套 Up 26min+ 无重启 |
| 启动 | 19:42:57 started server → 19:43:04 /health 200（0.02s） |
| warmup | ETF cache 1618 items、板块/市态/情绪/资讯循环全启动；mootdx bestip ERROR（请手动运行 python -m mootdx bestip，容器内无配置——已知环境项） |
| 老镜像回收 | `docker image prune -f`（回收 1 dangling layer，0B 可回收） |
| diag overlay | PROFILE_WARMUP=1 生效（cProfile enabled，pyinstrument 不可用跳过） |

---

## 2. 全链路诊断明细（阶段 2）

### 2.1 存活与回归门禁

- 核心路由 19/19 全 200（probe3.out）；WS `/api/v1/ws/portfolio` `/api/v1/ws/news` 握手 101（round39 文档遗漏 /api/v1 前缀写法，本轮实测补正：裸 /ws/* 会 403——**前端 vite 代理已带 /api/v1，无实际影响**）。
- verify_e2e.py 宿主挂死（0 字节输出，::1 双栈已知问题，round39 同）；单端点 curl 全 PASS。
- patrol --full 本轮未跑（超时预算限制，round39 同超时 2min 未完成——**巡检长跑问题未解，登记**）。
- data_health_check：**11/12 PASS，1 FAIL = 关键因子断链**（round39 方案 B 防护已生效能抓到断链，但见 §4.2 覆盖缺口）。
- verify_allocation_invariants（round44 方案 A）：PASS（designs 全合规）——但见 §4.2：只查上限抓不到 R162 悬空。

### 2.2 主动触发新数据验证（本轮核心方法改进）

round39 复验只读历史记录，而 design 12-14 全部生成于修复 commit 之前 → 「修复未生效」结论混淆了「代码旧」与「修复无效」。本轮改为：

1. `POST /api/v1/portfolio/design-async`（balanced, 500000, enhanced）→ task 19 completed（35s）→ design 15 入库。
2. `POST /api/v1/portfolio/strategy-check-async`（on_exchange）→ task 20 completed（35s）→ check 62 入库（off_exchange 因 LLM 超时未触发第二轮，登记）。

**design 15 层预算复验**（probe11）：

| 方案 | total | layers | budget | 判定 |
|---|---|---|---|---|
| defensive | 1.0000 | core .45/sat .20/def .10/cash .25 | .50/.20/.15 | ✅ |
| balanced | 0.9500 | core .45/sat .22/def .05/cash .23 | .50/.22/.13 | ⚠️ 无超配但 CASH_MISMATCH（R162） |
| aggressive | 0.9752 | core .55/sat .30/def .05/cash .0752 | .60/.30/.05 | ⚠️ 同上 |

**check 62 内容复验**（probe13）：15 只持仓 suggestions 全量、表格因子分 -0.47~+0.80 非零（R141 ✅）、
LLM 层失败（R167 假超时 + R164 文案失真）、规则兜底完整性 OK。

### 2.3 因子口径修正（round39 R146-R150 重判）

**证据链**：
- `/factors/active` 的 `zero_ratio` 挂在 `ic_tracker._zero_ratio`（`app/factors/ic_tracker.py:242`），语义 = 「该因子参与 IC 计算的批次里，非有意义值占比」——no_data 因子样本仅 4 个交易日（4/250），不是「当前因子矩阵零值占比」。
- round39 §0.1 用它判「premium_discount=0.0 → R146 未生效 / news_heat=1.0 → R149 未生效」——**两个方向都错**：zero_ratio=0.0 只说明 IC 批次里值非零（不代表矩阵非零），=1.0 只说明 IC 批次全无值（不代表矩阵断链）。
- 本轮 design 15 实测（probe14）：`sentiment.news_heat` 31 只**全 1.92 非零**（R149 实际已通）；`etf.premium_discount` 31 只全 0.0（R146 真断链仍在）。

**修正后状态表**：

| 因子 | /factors/active 口径 | design15 矩阵实际 | 真实判定 |
|---|---|---|---|
| etf.premium_discount | no_data, zero_ratio=0.0 | 31/31 = 0.0 | ❌ 真断链（R146 未修好或需盘中 nav） |
| etf.shares_change | no_data, ic=0.0179 | breakdown 无该键 | ⚠️ IC 有值但矩阵缺键，待核 |
| etf.industry_diversification | no_data, 常量输出 | 31/31 = 0.0 | ❌ 真断链（reason 明示「截面无差异」） |
| etf.institutional_holdings_change | no_data, ic=0.0229 | 31/31 = 0.0 | ❌ 真断链 |
| style.size.ln_mcap / ln_float_mcap | no_data, zero=1.0 | breakdown 无该键 | ❌ 真断链 |
| sentiment.news_heat | static, zero=1.0 | 31/31 = 1.92 | ✅ **实际已生效**（round39 误判） |

> 残余风险：premium_discount 依赖盘中 nav（IOPV），盘后 nav 未更新也可能全 0 —— **待交易时段复测**后才能终判 R146；industry_diversification/institutional_holdings_change 的常量输出则与时段无关，是真断链。

### 2.4 性能债登记（软门禁）

| 路径 | 本轮 | round39 | 阈值 | 处置 |
|---|---|---|---|---|
| /admin/factor-health 首呼 | 3.92s | 0.86s | ≤2s | ⚠️ 登记性能债（IC tracker 冷启动统计，warm 0.01s 说明仅首呼） |
| /market/realtime/portfolio 首呼 | 5.05s | 0.37s | ≤3s | ⚠️ 登记性能债（nav 注入链路相关，待交易时段复测归因） |
| patrol --full | >2min 超时 | 同 | — | ⚠️ 登记已知问题（round50 计时问题未解） |

---

## 3. 分析结果质量审查（阶段 3 · 四问法）

对 check 62（规则兜底全量）与 design 15（三方案）逐句审查：

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 结论分级 | 修复建议 |
|---|---|---|---|---|---|
| check62「市态：震荡」 | 事实 | hub regime=range_bound（日志 19:43-20:53 持续） | ✅ 与指数窄幅一致 | 合理 | — |
| check62 159516「因子分 0.80（偏强）」 | 事实 | comp=0.80 composite_score | ✅ 表格与 reason 同源 | 合理 | — |
| check62「因子覆盖 55.6%」 | 事实 | data_quality filled/total | ✅ | 合理 | — |
| check62 510880「信号 sell 建议 hold」 | 事实+规则 | 信号 sell + 规则兜底 hold | ⚠️ 信号与建议方向矛盾未解释 | 部分合理 | 建议文案应说明为何不跟随信号 |
| check62「LLM 分析超时（30s 未返回）」 | **失真** | 实际 openrouter error-envelope KeyError（R167）非超时 | — | **失效**（文案掩盖真因） | R167/R164 修复 |
| design15 balanced「卫星层 22%」(design_text) | 事实 | layers sat=0.22 | ✅ | 合理 | — |
| design15「现金仓位 23%」(design_text) | **失真** | cash 行 0.2300 但 expected 0.2800（R162 悬空 5%） | — | **失效**（文本与资金分配矛盾） | R162 修复 |
| design15 aggressive「防御层 5%」 | 事实 | def=0.05 | ✅ | 合理 | — |
| design15 target_amount「588200: 50000」 | **失效** | weight 0.0733×500000=36650（R163 脱节） | — | 失效 | R163 修复 |

**汇总**：可采信 5 条 / 需修正 1 条 / 失效 3 条（R162×1 + R163×1 + R164×1）。
总体评价：规则兜底内容自洽性尚可（因子分/覆盖/市态均同源真实），但 **R162/R163/R164 三处资金与文案失真会直接误导用户**（现金虚高 5%、目标金额虚高 36%、故障原因误报），均为本轮新发现。

**数据准确性抽查**：
- 权重和：defensive=1.0 ✓；balanced=0.95 ❌（R162）；aggressive=0.9752 ❌（R162）
- 报告数值 vs DB：composite_score 与表格因子分一致 ✓；target_amount ❌（R163）
- 占位检测：RSI 50.0 未出现 ✓；premium_discount 全 0（断链因子真实值非占位）✓ 诚实
- 新鲜度：check62 as_of=2026-08-31 盘后 ✓；design15 as_of 同日 ✓

---

## 4. 问题分析与修复方案（阶段 4）

### 4.1 R 系列发现汇总（本轮新增 R162-R168）

| 编号 | 发现 | 根因机制链（file:line） | 严重度 |
|---|---|---|---|
| R162 | cash 悬空（enforce 缩放后现金不回补） | strategy_design.py:663 先算 cash → :707 R140 enforce 缩放卫星层 → 缩掉权重蒸发（无回流 cash 步骤）→ design15 GAP +0.05/+0.0248 | P1 |
| R163 | target_amount 与缩放后权重脱节 | strategy_design.py:692 `_validate_target_amount_consistency` 先跑 → :707 enforce 后改 weight → target_amount 仍按旧权重（差 +36%） | P1 |
| R164 | LLM 失败文案失真（error-envelope 伪装超时） | reports.py:649-651 分类只认 429/json，KeyError('choices') 落 else → 「超时」；真因 openrouter 200+error body | P2 |
| R165 | NAV Redis 预热永久失效 | cache_service.py:208-217 `_ensure_client` 失败缓存 `_init_done=True` 永不重试 → warmup 首轮 ping 时 redis 未就绪 → 之后每轮 `ping()` 直接 False（实测 3 周期 0 ok vs 容器内手动 ping=True） | P1 |
| R166 | round39 zero_ratio 口径误用（诊断方法论） | factors.py:425 直接透出 ic_tracker._zero_ratio；诊断轮把它当矩阵零值占比 → round39 R146/R149 误判（本轮 §2.3 修正） | 方法论 |
| R167 | openrouter error-envelope KeyError | client.py:127 `data["choices"]` 直取，envelope 响应无 choices → KeyError 被 except Exception 吞为 WARNING（仅 message='choices' 无上下文） | P2 |
| R168 | v7 金标集欠量 | scripts/evals/goldens/ 18 条（demo 13 + quotes 5）vs v7 §5.5 P1 目标 50 条 | P3 |

遗留（非本轮新发现，不重复编号）：verify_e2e ::1 挂死（known-env-issues §1.1）、patrol --full 超时、mootdx bestip 容器缺配置、R141 带真实 shares_held 复测（DB 31 条持仓 avg_cost/shares_held 全 NULL——2026-08-27 灌录只落了 target_weight/first_buy_date，成本与份额从未入库，R141 表格「因子分」已非零但「持仓市值」列无从验证）。

### 4.2 测试防护体系缺口分析

**防护体系现状（本轮实测）**：

| 防护层 | 能抓 | 抓不到（本轮实证） |
|---|---|---|
| verify_allocation_invariants（round44 A） | 层超配/总仓位越限 | **R162 悬空**（只查 ≤ 上限，不查 cash 行 = 1−Σnon_cash 一致性）、R163（target_amount 不在校验范围） |
| data_health_check 关键因子断链（round39 B） | critical factor 全空 | premium_discount 盘后全 0 被正确抓到；但 **R149 news_heat 误报防护盲区**（critical 清单里没有 news_heat，否则 round39 的口径误用会被断言拦截） |
| patrol L2-llm-exclusion（round44 C） | excluded 模型仍有增量调用 | ✅ 本轮实测通过（180s 增量=0） |
| pre-commit pytest 全量 | 单测覆盖的函数行为 | R162/R163/R165 均有单测但**断言方向不完整**（见下逐项映射） |
| verify_e2e | 端到端 200/非空 | 容器外挂死（::1）；内容断言弱（「组合为空」48 字节报告也算 PASS 形态） |

**逐发现映射**：

| 发现 | 最应拦截的防护层 | 为何未识别（file:line + 具体断言/阈值） | 应补的守卫（缺口类型） |
|---|---|---|---|
| R162 | verify_allocation_invariants | scripts/verify_allocation_invariants.py:61-83 只断言 `total > budget+TOL` 与 `non_cash > 1.0+TOL` 两个上限方向；无 `abs(cash_row − (1−non_cash)) > TOL` 下限/一致性断言 | 内容语义断言缺失（负向：人为把 CASH 行权重改小 5% → FAIL） |
| R163 | pre-commit pytest（strategy_design 单测） | `_validate_target_amount_consistency`（strategy_design.py:1290）只在 enforce 前跑；单测覆盖该函数本身，不覆盖「enforce 后 target_amount 是否重算」的时序不变量 | 执行时序不变量缺失（负向：mock enforce 缩放后断言 target_amount==capital×weight 必须仍成立） |
| R164 | reports 单测 | 失败分类（reports.py:649-651）的 else 分支无「error-envelope → 不得报超时」负向用例；KeyError 无专属分类 | HTTP 契约层无覆盖（负向：mock openrouter 返 200+`{"error":{...}}` → summary 不得含「超时」） |
| R165 | smoke_startup / lifespan 观测 | RedisCacheSync 失败缓存行为无单测（cache_service.py:208-217）；`/admin/lifespan-warmup` 端点存在但 patrol/e2e 均不读 `redis_available` 字段 | 门禁存在但未实际执行（负向：mock 首轮 ping 失败→redis 就绪后断言 available 能自愈/或 warmup 报告不得假绿） |
| R166 | data_health_check 方案 B | critical 因子断言清单（data_health_check.py:258-278）不含 news_heat/口径说明；zero_ratio 透出端（factors.py:425）无口径注释防误读 | 两口径未隔离（负向：/factors/active 响应附 `zero_ratio_scope=ic_batch` 字段 + 诊断文档引用时必须带 scope） |
| R167 | LLM client 单测 | client.py:127 choices 直取无「200+error-envelope → 结构化错误」处理；单测只 mock 正常 shape | HTTP 契约层无覆盖（负向：mock envelope → 不得 KeyError，需返回结构化 provider_error） |

**系统性根因归并**（3 类）：

1. **单侧断言（只验上限不验一致性）**——R162/R163 同根：round39 补的方案 A 守卫只复制了「不超配」这半边不变量，漏了「分配完整（cash 一致）」与「派生字段同步（target_amount）」另外半边。【round39 已归纳未收敛：方案 A 落地了但只落地一半语义】
2. **失败路径文案/分类单点失真**——R164/R167 同根：LLM 失败链的异常分类与用户文案由两个模块各写一份关键字匹配，envelope 类新失败形态两边都漏。【本轮新出现】
3. **懒初始化失败缓存无自愈**——R165：round45 新引入的 sync wrapper 把「首次失败」当终态，无 TTL 重试。【本轮新出现】

**补齐设计（只写方案，不写代码）**：

- **方案 A（推荐，P1）**：verify_allocation_invariants 增 3 条断言：① `abs(cash_row − (1−Σnon_cash)) ≤ 0.005`（R162）；② 每标的 `|target_amount − capital×weight| ≤ 1`（R163）；③ Σtotal（含 cash）≤ 1.0+0.01。影响 scripts/verify_allocation_invariants.py + patrol L2。验收负向：手工构造 design15 形态（GAP 0.05）必 FAIL。
- **方案 B（推荐，P1）**：strategy_design R140 enforce 后重算 target_amount + 重算 cash 行（对齐 :663 同一公式），并把 `_validate_target_amount_consistency` 移到 enforce 之后跑第二次。影响 strategy_design.py:660-710。验收负向：mock 强制缩放 → 单测断言 target_amount 与 weight 一致 + cash 行 == 1−Σnon_cash。
- **方案 C（推荐，P1）**：RedisCacheSync._ensure_client 失败缓存加 TTL（60s 后允许重试）+ ping 失败时重置 `_init_done=False`。影响 cache_service.py:190-235。验收负向：mock 首次 ping 失败 → 60s 后 ping 成功 → available 翻 True（现实现必假 False）。
- **方案 D（P2）**：client.py:127 前置 `if "error" in data: raise ProviderEnvelopeError(...)`，reports.py 失败分类加 envelope 分支（文案「LLM 网关返回错误信封」）。验收负向：mock envelope → summary 含「错误信封」不含「超时」。
- **方案 E（P2，方法论）**：/factors/active 响应 `zero_ratio` 键改名/附注 `zero_ratio_scope: "ic_batch"`；data_health_check critical 清单补齐 news_heat 等矩阵口径因子并注明两种口径不可互替。
- **方案 F（P3）**：v7 金标集按 §5.5 阶段化补量（P1 50 条），quotes.jsonl 现仅 5 条。

### 4.3 与 round39/v7 文档的关系

- round39 §5 锁定的方案 A（R140 二次 enforce）/B（因子断链断言）/C（mark_excluded 端到端）/D（verify_e2e storm 归类）**均已实施且本轮实测通过**（R140 ✅、data_health_check ✅、patrol C ✅；D 项 verify_e2e 修复属 storm 归类，本轮挂死是 ::1 连接层，不是 storm 误判——不冲突）。
- round39 R161（design_text 暴露实际 sat）未实施——本轮 design15 design_text 仍只写「卫星层 22%」未标注 vs budget 关系；因 R140 已生效该风险降级为 R162 的伴生项（现金虚高同样未在文本暴露），并入方案 A 验收。
- v7 落地核实结论（§0.1 #11）：P0/P1/P2 代码全在且护栏齐，金标 18/50 欠量（R168）；v7 §6.5 成本阈值清理已随 ceb19a5 落地（cost.py）。

---

## 5. 三轮 Review 记录（阶段 5）

### 5.1 Round 1 — 事实核对

| 项 | 核对 | 结论 |
|---|---|---|
| design15 层数字 | probe11.out 与 API /designs/15 双源一致 | ✅ |
| check62 表格 | probe13.out 与 DB report_text 一致 | ✅ |
| zero_ratio 口径 | ic_tracker.py:242 与 factors.py:425 实读 | ✅ |
| R165 | main.py:820 ping + cache_service.py:208-217 实读 + 容器内实测 | ✅ |
| commit 时间线 | `git log` 实测 b2e6078=08-30 13:31 vs design14=05:20 | ✅ |
| 耗时数字 | probe3.out 两次采样原值 | ✅ |

### 5.2 Round 2 — 逻辑一致性

- §0.1#3「口径误用」与 §2.3 修正表互证：news_heat 在 round39 被判断链、本轮矩阵实测 1.92 非零 → round39 结论确系口径错，非数据错。✅
- §0.1#1「R140 生效」与 §0.1#4「R162 新发现」不矛盾：缩放让层合规是 R140 的目标达成；悬空是 R140 缩放与 cash 计算时序的组合副作用（R140 本身无 bug，是 cash 时序缺回补）。✅
- 验证矩阵 R143 行：round39 判 ❌、本轮 ✅ —— 差异解释为「存量 21706 为 mark 前历史调用」，与 180s 增量=0 自洽。✅

### 5.3 Round 3 — 完整性

- 验证窗口标注：premium_discount/R146 归因需交易时段复测（§2.3 已标）；realtime/portfolio 5.05s 归因同（§2.4 已标）。✅
- 未决项清单：① R146 盘中复测；② off_exchange check 未触发（LLM 层失败连锁）；③ patrol --full 长跑；④ R141 持仓市值列待灌录 shares_held 后复测；⑤ R168 金标补量。均已入 §4.1/§4.3。✅
- 风险点：方案 B 改动 cash 计算为高敏区（weight 不归一化约定），实施时必须遵守 AGENTS.md「权重不归一化」约定——方案 B 只回补 cash 行不归一化各层。✅ 已在方案 B 注明。

**结论**：三轮 review 通过，文档达到「方案轮定稿」标准。

---

## 6. 决策点（2026-08-31 用户已拍板：全部采纳，暂缓实施）

> **拍板结果**：方案 A-F 全部采纳，**先更新文档、暂缓实施**——等「开始实施」指令触发实施轮
> （TDD 逐项实施 + 验收 + 英文 commit message + push，同 round40-46 实施模式）。

| # | 决策 | 拍板 | 状态 | 影响范围 |
|---|---|---|---|---|
| 1 | R162/R163 资金悬空+金额脱节修复（方案 A+B） | 采纳 | 📋 已采纳待实施 | strategy_design.py + verify_allocation_invariants.py，~1.5h |
| 2 | R165 NAV Redis 自愈（方案 C） | 采纳 | 📋 已采纳待实施 | cache_service.py，~30min |
| 3 | R164/R167 envelope 误判（方案 D） | 采纳 | 📋 已采纳待实施 | client.py + reports.py，~40min |
| 4 | R166 口径隔离（方案 E） | 采纳 | 📋 已采纳待实施 | factors.py + data_health_check.py，~30min |
| 5 | R168 金标补量（方案 F） | 采纳 | 📋 已采纳待实施 | evals/goldens/，阶段化 P1 50 条 |

> 按 AGENTS.md 约定：以上均为已采纳方案，未收到「开始实施」不写代码。

---

*诊断产物：C:/Users/Public/etf_probe/（probe1-16.out，会话级临时目录）；容器于诊断完成后回收。*
