# ETF Surge — round2 未修复问题：根因分析与修复方案 (v1.0)

> 生成时间: 2026-08-01
> 前置: `docs/round2-issue-verification-report.md`（验证结论：Z06 回归、Z04 恶化、F1-1/F1-9/F2-1/F3-3/F3-4/F3-5 未修复、T 系列 12/14 未落地）
> 本文档: 针对上述**未修复/未达标**项做根因深挖 + 可实施修复方案（先契约 → 先失败单测 → 实现 → e2e 验证）
> 状态: v1.0 初稿，待 review

---

## 一、未修复问题全景

| # | 问题 | 严重度 | 状态来源 |
|---|------|--------|---------|
| U1 | 港股实时行情 null（F1-1/N03） | 🔴 高 | 实测 API None，直调数据源正常 |
| U2 | 策略检查报告正文空（F1-9/N01） | 🔴 高 | task 66 completed 但 report_text len=0 |
| U3 | IC 数据全 0 覆盖（Z06/N06） | 🔴 高 | e2e IC 检查 FAIL，ConstantInputWarning |
| U4 | etf_specific 10 因子无数据（Z04/F3-4） | 🔴 高 | factors/active no_data=10 |
| U5 | 组合计算 8.2s（F2-1） | 🟡 中 | calculate 实测 8.2s（验收 <2s） |
| U6 | 设计现金仓位 19-24%（F3-3/Z11） | 🟡 中 | balanced 19%（验收 ≤15%） |
| U7 | 预热 6.6s（Z05/N08） | 🟡 中 | warmup_market_cache 6.45s |
| U8 | sectors/heat 契约断裂（F2-3/N05） | 🟡 中 | dict vs 前端 array |
| U9 | HK/US 报告混入 A 股数据（F1-3/F1-4/N04） | 🟡 中 | market_data 未按市场过滤 |
| U10 | sentiment 因子无数据（F3-5） | 🟡 中 | 4 因子全 no_data |
| U11 | 核心层跨方案重叠 >1（F1-8） | 🟢 低 | 平衡∩进攻 2 只 |
| U12 | T 系列防护 12/14 未落地 | 🔴 高（结构性） | verify_e2e 无新 section |

---

## 二、逐项根因分析

### U1: 港股实时行情 null

**现象**：`GET /market/realtime/00700?asset_type=HK` 返回 None；容器内直调 `_tencent_realtime(['00700'],'HK')` 返回 475.2 +0.72%（数据源正常）。

**根因链**（已实证，market_service.py:1058-1085）：

```
get_asset_realtime('00700', 'HK')
  ├─ asset_type != "US" → 走通用分支
  ├─ ① fetch_a_stock_realtime('00700')   ← A 股路径先跑
  │    ├─ mootdx（可能熔断 open）
  │    ├─ tencent A 股查询 00700 → 空
  │    └─ sina A 股查询 00700 → 空
  │    └─ route() 对空结果调用 record_failure → sina/tencent 熔断计数 +1
  ├─ ② fetch_hk_stock_realtime('00700')  ← HK 降级链
  │    ├─ sina provider：已被①污染 open → 跳过
  │    ├─ tencent provider：已被①污染 open → 跳过
  │    └─ dongfang provider：可能 open → 跳过
  │    └─ 全部跳过 → 空 → 5.5s 等待超时 → None
```

**关键点**：
1. `get_asset_realtime` 对 HK 标的**未按 asset_type 分流**——先跑 A 股路径，A 股路径对非 A 股代码的"空结果"被 `registry.route` 的 `if data:` 判断计为失败（source_registry.py:242-248），污染 HK 数据源熔断状态；
2. round2 F1-1 方案（HK 代码补 `.HK` 后缀 + tencent 归一化）只修了 provider 内部前缀，**没修 `get_asset_realtime` 的路由顺序**；
3. round3 N03 诊断的"熔断误伤"与此同根因。

**修复方案**：
- **R1（核心）**：`get_asset_realtime` 按 asset_type 分流——`asset_type == "HK"` 时**跳过 A 股查询**，直接走 `fetch_hk_stock_realtime`；`asset_type == "A"` 时跳过 HK 查询。
- **R2（熔断语义）**：`SourceHealth.record_failure` 区分"provider 正常但查无此标的"（空列表）与"provider 异常"——空结果不计入失败阈值（或降权）。修改 `source_registry.route()` 中 `if data:` 分支：空列表记录为"未命中"事件（success=False 但 failures 不加），仅 HTTP 4xx/5xx/异常/超时计入熔断。
- **R3（回归测试）**：`tests/test_market_service_hk.py`：`get_asset_realtime('00700','HK')` 在 mock `fetch_hk_stock_realtime` 返回数据时返回该数据，且断言**未调用 `fetch_a_stock_realtime`**。
- **验收**：连续 10 次 `GET /market/realtime/00700?asset_type=HK` 均返回价格；e2e 新增 `section_hk_realtime`。

---

### U2: 策略检查报告正文空

**现象**：task 66 completed，`report_text len=0`、`covered_by_llm=0`、`covered_by_rule=10`。

**根因链**（已实证）：

```
strategy_check（portfolio_service.py:402）
  ├─ 数据采集（30s 超时）
  ├─ LLM 分析：wait_for(20s)（portfolio_service.py:536）
  │    ├─ opencode_zen 429 → fallback deepseek → 仍慢/失败
  │    └─ 20s 超时 → 捕获 (TimeoutError, CancelledError) → llm_result = 空结构（:557-564）
  │         ├─ summary: "LLM 分析超时…已用规则引擎兜底"
  │         ├─ suggestions: []  ← 关键：空
  │         ├─ holdings_analysis: []  ← 空
  │         └─ risk_warnings: []
  ├─ 后处理：holdings_analysis 为空 → factor_summary 回填逻辑空转
  └─ strategy_check_worker.py:141-155 落库
       ├─ suggestions_json = []（但随后 rule 引擎生成 10 条 rule 建议——实际来自另一处）
       ├─ report_text = result.get("report_text", "") or ""  ← 字段不存在 → ""
```

**关键点**：
1. `llm.py::generate_strategy_check_report`（1171-1193）在超时时返回的空 dict **没有 `report_text` 字段**；`portfolio_service.py` 兜底同样无；
2. **rule 引擎在别处生成**（`strategy_check_worker` 或 `generate_strategy_suggestions`）——task 结果里 10 条 rule hold 说明 rule 建议存在但**正文 Markdown 从未组装**；
3. F1-9 方案只覆盖了"异常捕获 + usage 留痕"（已落地），**未包含"兜底正文生成"**——这是方案设计的遗漏，不是实施缺陷。

**修复方案**：
- **R1（兜底正文）**：在 `portfolio_service.py` 的 `result` dict（:675-690）中**新增 `report_text` 键**——新增 `_build_rule_fallback_report(market_data, factor_breakdowns, merged_suggestions, regime, data_quality) -> str`，用已生成的 `merged_suggestions`（rule 建议已存在，:662）渲染结构化 Markdown：市态结论 → 逐标的因子/信号/漂移表 → 风险提示 → 操作建议。当前问题正是 `merged_suggestions` 存在但无正文渲染层。
- **R2（状态语义）**：`report_text` 为空时任务标记 `failed` 而非 `completed`（诚实收敛，前端可提示"LLM 分析失败，已展示规则摘要"）。
- **R3（超时预算）**：LLM 超时从 20s → 60s（对齐设计任务 240s 的下限），并确保 fallback provider 在超时后仍有尝试机会（当前 CancelledError 会取消整条 fallback 链，需在 wait_for 外包装重试）。
- **R4（单测）**：`test_strategy_check_fallback.py`：mock `wait_for` 抛 TimeoutError → 断言返回含 `report_text` 且长度 >500、含市态/因子/风险三节。
- **验收**：强制 20s 超时场景下 `report_text` 非空；e2e `section_report_nonempty` 断言长度 >500。

---

### U3: IC 数据全 0 覆盖（Z06 回归）

**现象**：`/factors/ic` 0 条、`/factors/active` 30 因子 no_data、日志 `ConstantInputWarning`、`ic_persistence` 持续 "no IC data to persist"。

**根因链**（已实证）：

```
factor compute（factor_registry.py:1054）
  ├─ _fetch_market_data 拉 K 线 → 部分因子值全部相同（常量）→ 数据源波动
  ├─ ic_tracker.record(sym, code, value) 只记 abs(value)>0.001
  ├─ compute_periodic_ic（ic_tracker.py:126）
  │    ├─ build_forward_returns → 某些标的收益常量
  │    ├─ spearmanr(常量) → ConstantInputWarning + NaN
  │    └─ compute_ic（:69-85）→ NaN → 0.0
  ├─ ic_batch = {code: 0.0, ...}（非空但全 0）
  ├─ factor_registry.py:1219 `self._last_ic_batch = ic_batch`  ← 无条件覆盖
  └─ /factors/ic 过滤 abs(val)>0 → 空；/factors/active 判 no_data
       └─ ic_persistence 循环读 _last_ic_batch → 全 0 → "no IC data to persist"
```

**关键点**：round2"23 条 IC"是**时序性假阳性**（当时 K 线恰好有差异）；一旦出现常量输入批次，`_last_ic_batch` 被全 0 覆盖且**永不恢复**（后台循环只在非空时保存，但 0 值被过滤后 count=0）。

**修复方案**：
- **R1（常量检测）**：`compute_ic`（ic_tracker.py:69-85）对 `vals.nunique()==1` 或 `rets.nunique()==1` 直接返回 `None`（跳过该因子），不再走 spearmanr 返回 0；
- **R2（防覆盖，需配合 R1 的 None 语义）**：`factor_registry.py:1217-1219` 覆盖前过滤——`ic_batch` 中 `value is None` 的因子跳过；仅当剩余批次含任一 `abs(val)>0.001` 时覆盖 `_last_ic_batch`；否则保留旧值并打 WARNING（注意 R1 返回 None 时此处不能对 None 做 `abs()`，需先过滤）；
- **R3（零值统计）**：`compute_periodic_ic` 的 `_zero_ratio` 已实现（ic_tracker.py:166-169），确保 `/factors/ic` 输出它，前端可区分"数据缺失"与"IC 无效"。
- **R4（单测）**：`test_ic_tracker.py` 增加常量输入用例：`compute_ic([1,1,1],[1,2,3]) is None`；`test_factor_registry_ic_overwrite.py`：mock 全 0 批次 → `_last_ic_batch` 保留旧值。
- **验收**：触发 3 次 factor-health 后 `/factors/ic` 非空；e2e `section_factor_ic` 稳定 PASS（不再依赖时序）。

---

### U4: etf_specific 10 因子无数据（Z04）

**现象**：`/factors/active` etf_specific 10 因子全 no_data；`test_factor_etf_specific.py` 6 用例全绿（mock 数据）。

**根因**（本轮复核修正——注入代码已实现，问题在运行时数据源可达性 + U3 过滤叠加）：
1. **注入管线已完整存在**：`factor_registry.py:976-1019` 已实现 NAV 降级（F3-4 步骤A）、sentiment 注入（F3-5）、etf_specific 字段注入（benchmark_close/shares_change_20d/institutional_holdings_change）；`market_data_hub.py:1033-1095` 已实现 `_enrich_symbol_extra`（宽基 benchmark_close + 份额变化 + 24h 缓存）——round2 §9.5 步骤 A-D **已实施**；
2. **运行时数据源不可达（静默失败）**：IOPV（Sina/QQ）容器内命中率低；`fetch_etf_shares_outstanding`（天天基金份额接口）在容器内失败时被 `except: continue`/`except Exception: logger.debug` 静默吞掉（market_data_hub.py:1088-1089）——注入循环跑了但没有数据可注；
3. **U3 的 IC 全 0 过滤叠加放大**：即使部分因子注入成功，全 0 批次覆盖 `_last_ic_batch` 后仍判 no_data——**Z04 修复必须前置 U3**；
4. 单测用 mock 注入数据 → 管线逻辑正确，但**不验证真实数据源可达性**（单测盲区）。

**修复方案**：
- **前置**：先修 U3（IC 防覆盖），否则因子算出来也被过滤。
- **R1（数据源可达性诊断）**：容器内分别验证 3 个上游：`get_fund_nav`（天天基金 NAV）、`fetch_etf_shares_outstanding`（份额）、Sina/QQ IOPV——对失败项打 WARNING 级日志（当前 debug 静默），并输出到 `sources/health` 便于排查；
- **R2（降级链验证与补全）**：premium_discount 的 NAV 降级链已存在（factor_registry.py:983 → `market_data_hub.get_fund_nav` → `china_market.fetch_fund_nav` → `fund_fetcher.fetch_fund_nav`）——本轮先**验证该链在容器内各环节的可达性**（哪个环节失败），失败环节打 WARNING 并尝试替代源（如 akshare `fund_open_fund_info_em` 直连）；仍失败才保留 no_data（**不回退 0.0 假数据**）；
- **R3（份额源替换）**：`fetch_etf_shares_outstanding` 若天天基金不可达，降级 `akshare.fund_fund_shares_em`（round2 §9.5 步骤C 原方案）；缓存已有（24h）；
- **R4（reason 明确化）**：`factors.py::_status_of` no_data reason 区分"数据源未接入（缺 nav/benchmark_close/shares_change_20d，列出具体缺字段）"与"IC 未累积"——按 `_data_source_gaps`（已有字段）判定；
- **R5（单测补运行时断言）**：`test_factor_etf_specific.py` 增加"注入字段存在但值为空 → reason 指向缺失字段"用例；e2e 触发真实 compute 后断言 no_data ≤2。
- **验收**：`etf_specific no_data ≤2`；`valid+warn ≥6`；每个 no_data 因子 reason 标注缺失字段；`sources/health` 能看出哪个上游失败。

---

### U5: 组合计算 8.2s

**现象**：`POST /portfolio/calculate` 实测 8.2s（round2 验收 <2s，完全未改善）。

**根因**（portfolio_service.py:240-315）：
1. `build_price_map`（:84-194）已用 `asyncio.gather` 并行——A/HK/US/指数四路并发，**不是主瓶颈**；
2. 第二遍 fundamentals（:295-315）：`run_sync(get_fundamentals, sym, timeout=8)` 10 个标的 gather，但**每个标的内部 8s 超时**，`asyncio.wait_for(..., timeout=10)` 总预算 10s——实测 8.2s 说明某个标的 fundamentals 数据源接近超时；
3. `_FUNDAMENTALS_CACHE` 有 15s TTL（`_PRICE_MAP_TTL=15.0`，portfolio_service.py），**每次请求都可能触发重新拉取**——8.2s 实测即某标的 fundamentals 数据源接近 8s 超时；
4. e2e `section_portfolio` 的 gate 已放宽到"中位数 <2s、首拉不计入"（verify_e2e.py:529-537）——**门禁被放宽，掩盖了真实慢**。

**修复方案**：
- **R1（fundamentals 降级）**：`get_fundamentals` 增加快速失败——数据源 3s 无响应即返回空 dict（结构化空），不占满 8s；总预算从 10s 降到 5s。
- **R2（并行度限制）**：10 个标的 fundamentals 用 `asyncio.Semaphore(4)` 限并发，避免 10 路同时打同一数据源触发限流。
- **R3（缓存预热）**：预热阶段预拉持仓 fundamentals 填充 `_FUNDAMENTALS_CACHE`。
- **R4（e2e 门禁还原）**：`section_portfolio` calculate gate 从"中位数 <2s + 首拉豁免"改回硬门禁 <3s（首拉计入），防止再次掩盖回归。
- **验收**：calculate 连续 3 次采样中位数 <2s。

---

### U6: 设计现金仓位偏高（F3-3/Z11）

**现象**：balanced 现金 19%、defensive 24%、aggressive 19%（round2 验收 balanced ≤15%）。

**根因**（budgets.py + allocation_engine.py）：
1. `dynamic_layer_budget`（budgets.py:59-114）对 `range_bound` **无任何分支**（仅 defensive_rotate/bear/correction/bull_strong 有调整）——balanced 基础预算 0.45+0.30+0.10=0.85 → 理论现金 15%；
2. **实际现金 19% > 15%**：`_select_and_weight` 按候选数量与 `max_count` 分配，**候选池/层数量不足以用满预算**——core 5 只、satellite 4 只、defense 1-2 只，power-law 分配后权重和 < 预算，剩余转 CASH；
3. round2 F3-3 方案（range_bound 收紧现金 ≤15%）**只写了"预算引擎收紧"但未指明分配不满的问题**——修复预算上限不解决"分配不满"。

**修复方案**：
- **R1（预算用满）**：`_select_and_weight` 分配后若 `sum(weights) < budget`，将剩余按 composite 降序回补到已选标的（每只上限 30% 风控内），**减少被动 CASH**；
- **R2（range_bound 预算）**：`dynamic_layer_budget` 对 range_bound 的 balanced 微调——satellite +0.02、defense -0.02，使理论现金 ≤13%，留 2% 机动；
- **R3（验收口径）**：现金 = `1 - sum(all non-CASH weights)`，且非交易时段（regime=panic/correction）允许高现金——验收区分时段；
- **R4（单测）**：`test_allocation_cash_budget.py`：balanced+range_bound → 现金 ≤15%；defensive 科创卫星 ≤10%（已有）。
- **验收**：balanced 方案现金 ≤15%（非交易时段除外）。

---

### U7: 预热 6.6s（fetch_fund_nav 无连接池）

**现象**：warmup_market_cache 6.45s；cProfile：`fetch_fund_nav` 10 次调用 8.2s 累计、akshare `fund_open_fund_info_em` 7.2s。

**根因**（china_market.py:969-996）：
1. round2 Z05 标"✅ 改善（1.77s）"——当时全球指数 gather 并行生效（F2-5 已修）；
2. **`fetch_fund_nav` 的 Session 复用未生效或未实施**：cProfile 显示 10 次 `fund_open_fund_info_em` 各 0.7s（非缓存命中，走真实 HTTP），每次新建连接（无复用证据）；
3. akshare 内部每次调用新建 `requests.Session`，10 只 ETF 10 次握手。

**修复方案**：
- **R1（连接复用）**：`fetch_fund_nav` 使用模块级 `requests.Session()` 连接池（round2 Z05 方案要求但需核实是否落地——cProfile 实证未生效）；akshare 无法直接复用 Session 时，改走 `fund_fetcher` 自建 Session + 天天基金 HTTP 直连。
- **R2（并发）**：10 只 ETF 的 NAV 拉取 `asyncio.gather` 并发（当前疑似串行）。
- **R3（缓存）**：NAV 结果 24h 内存缓存（日频数据），预热首次拉取后不再重复。
- **R4（日志降噪）**：预热期 `LOG_LEVEL=INFO` 覆盖 DEBUG（当前容器 DEBUG 导致 1.9s logging 开销）。
- **验收**：预热 <3s；cProfile 中 fetch_fund_nav 累计 <2s。

---

### U8: sectors/heat 契约断裂

**现象**：后端返回 `{"items":[...]}`（dict），前端 `SectorHeatMap.vue:216` `Array.isArray(resp.data)` 期望数组 → 热度 Tab 空白。

**根因**（market.py:468-486 + SectorHeatMap.vue）：
1. 后端 `sectors_heat` 响应结构为 dict（含 total）；
2. 前端直接 `Array.isArray(resp.data)` 判断，dict 不通过 → `dataList=[]`；
3. round2 F2-3 只修了 404（端点暴露），**未修响应结构契约**。

**修复方案**：
- **R1（推荐后端归一化）**：`sectors_heat` 返回 `list[dict]`（与 hot-plates 一致），total 移到响应头或省略；
- **R2（前端双兼容）**：`dataList.value = Array.isArray(resp.data) ? resp.data : (resp.data?.items ?? [])`；
- **R3（e2e）**：`section_contract_shape` 断言 `sectors/heat` 响应为 list 或与前端契约一致。
- **验收**：前端热度 Tab 显示 20 条；e2e 结构断言通过。

---

### U9: HK/US 报告混入 A 股数据

**现象**：`llm-report/stream {market:HK}` 报告大谈创业板/上证50。

**根因**（llm_context.py + analysis.py:389）：
1. `build_full_context` 第 3 步 `index_realtime` **已按 market 过滤**（F1-4 部分修复 ✅）；
2. **第 5 步 `market_data = get_all_realtime()` 未按 market 过滤**（llm_context.py:96-97）——全量 A 股实时注入；
3. `analysis.py:389` 过滤条件 `asset_type in ("index","futures")` 只挡类型不挡市场 → A 股指数全部放行；
4. `_build_market_overview`（llm.py:687）硬编码"A股市场"标题。

**修复方案**：
- **R1（market_data 按市场过滤）**：`build_full_context` 第 5 步按 `market` 过滤——HK/US 时从 `get_global_indices()` 取对应 region 标的 + 对应市场 ETF/个股，而非 `get_all_realtime()` 全量；
- **R2（标题动态化）**：`_build_market_overview` 的 `### A股市场` 改为 `### {market}市场`（传参）；
- **R3（e2e）**：`section_market_isolation`——HK 报告含恒生指数且不含"创业板/上证50"。
- **验收**：market=HK 报告引用恒生数据为主。

---

### U10: sentiment 因子无数据

**现象**：sentiment 4 因子全 no_data。

**根因**（本轮复核修正——注入已实现，同 U4 的运行时可达性 + U3 过滤叠加）：
1. **注入已实现**：`factor_registry.py:989-1005` 已从 `get_market_sentiment()`/`get_news_headlines()` 注入 `sentiment_index/sentiment_history/news_items`（F3-5 落地）；
2. 但 `panic_greed_diff`（涨跌分布）依赖的行情分布数据、`news_heat/news_direction`（资讯情绪）依赖 `get_news_headlines()` 数据——**若 `get_market_sentiment()` 返回空或 news 为空，注入的是空值** → 因子值全 0 → 被 IC 过滤（U3）；
3. **U3 的 IC 全 0 覆盖是最终判 no_data 的直接原因**——即使注入非空，全 0 批次覆盖后仍判 no_data。

**修复方案**：
- **R1**：先修 U3（防覆盖）；
- **R2（数据源健康）**：验证 `get_market_sentiment()`/`get_news_headlines()` 在容器内返回非空（sentiment 由 120s 循环刷新，news 由 120s 循环刷新——检查循环是否正常跑）；空时 WARNING 而非静默；
- **R3（news_direction 规则化）**：`news_heat/news_direction` 从标题情绪词频统计（规则法，不依赖 LLM），确保 news 非空即可算出；
- **R4（注入非空校验）**：`factor_registry.py:989-1005` 注入前校验 `_sent`/`_news` 非空，空则跳过该字段并记录缺失。
- **验收**：sentiment `no_data=0`（在 U3 修复后）。

---

### U11: 核心层跨方案重叠 >1

**现象**：平衡∩进攻 core 重叠 2 只（510300/588000）。

**根因**（allocation_engine.py:491-524）：
1. `_used_symbols_for_overlap` 跨方案惩罚已实现（P1）——但 `penalize_symbols` 只对**后续方案**的 core 生效；
2. 防御型先用 510300/510500，平衡型惩罚后选 510300/588000（510500 被惩罚但 510300 仍最高分），进攻型再惩罚 510300/588000 仍最高分 → 重叠不可避免（高分标的太少）；
3. 候选池修复（F0-5）后 core 候选含主流宽基，**高分宽基只有 4-5 只，3 套方案必然重复**。

**修复方案**：
- **R1**：跨方案 core 去重升级——后续方案 core 若与已用标的重叠，从次高分宽基补充（强制 ≥1 只新宽基）；
- **R2**：或按 round2 验收"core 重叠 ≤1"放宽为"三套方案 core 并集 ≥6 只"（合理性优先）。
- **验收**：三套方案 core 两两重叠 ≤1 只。

---

### U12: T 系列防护 12/14 未落地

**现象**：verify_e2e.py 无 `section_hk_realtime/contract_shape/report_nonempty/market_isolation/search_pinyin/ic_persistence`；数值门限/LLM 金丝雀/契约自动化/数据卫生全缺。

**根因**：
1. round2 §九 🅿️4 是**方案**（非实施记录），后续迭代未排期；
2. 部分修复依赖基础设施（api-contracts→schema 生成器、LLM 基线样本库）未建；
3. 现有 e2e 门禁以"接口形状"为主（HTTP 200/非空），无"业务语义"断言框架——如 `section_factor_ic`（verify_e2e.py:1905）只读 `_last_ic_batch` 缓存（GET /factors/ic 不触发 compute），**验证不到后台 120s 累积循环是否在跑**（U3）；新增 `section_ic_persistence` 应直接查 DB `FactorICRecord` 数量（不触发 compute）补此盲区。

**修复方案**（按 round3 文档 4.2/4.3 执行）：
- **R1（6 个新 section）**：见 round3 文档 §4.2 代码——`section_hk_realtime` / `section_report_nonempty` / `section_market_isolation` / `section_contract_shape` / `section_ic_persistence` / `section_search_pinyin`（签名已统一 `(host, port)`）；
- **R2（数值门限）**：`test_factors_router.py` 增加 `etf_specific no_data ≤2`、`sentiment no_data=0` 硬断言（T7）；
- **R3（LLM 金丝雀）**：固定 3 条基线样本 + 断言无泄漏/无"未包含 XX 数据"自曝/无强行关联（T8）；
- **R4（数据卫生）**：e2e 前后清理 watchlist/designs/checks 测试写入（T13）；
- **R5（门禁收紧）**：预热计时 PROFILE_WARMUP 默认启用；LLM 降级时对应报告断言 FAIL。
- **验收**：新增 section 全 PASS；对 U1/U2/U3/U8/U9 的回归检测生效。

---

## 三、实施优先级与依赖

```
┌─────────────────────────────────────────────────────────────┐
│ 第一梯队（P0 — 先修"数据正确性"根基，2.5 人日）              │
├─────────────────────────────────────────────────────────────┤
│  U3 IC 防覆盖（前置：所有因子类修复依赖它）       0.5 日      │
│  U1 港股路由分流 + 熔断语义                      0.5 日      │
│  U2 策略检查兜底正文 + failed 语义               0.5 日      │
│  U4 etf_specific 因子数据源（依赖 U3）           1.0 日      │
├─────────────────────────────────────────────────────────────┤
│ 第二梯队（P1 — 性能与契约，1.5 人日）                        │
├─────────────────────────────────────────────────────────────┤
│  U5 fundamentals 快速失败 + 并发限制             0.5 日      │
│  U6 预算用满 + range_bound 收紧                  0.5 日      │
│  U7 预热 NAV 连接池 + 并发                       0.5 日      │
├─────────────────────────────────────────────────────────────┤
│ 第三梯队（P2 — 展示与隔离，1 人日）                          │
├─────────────────────────────────────────────────────────────┤
│  U8 sectors/heat 契约    U9 HK/US 市场隔离                   │
│  U10 sentiment 因子      U11 core 重叠                        │
├─────────────────────────────────────────────────────────────┤
│ 持续（P3 — 防护补强，与上述修复同步落地）                    │
├─────────────────────────────────────────────────────────────┤
│  U12 T 系列：6 新 section + 数值门限 + 金丝雀 + 数据卫生       │
└─────────────────────────────────────────────────────────────┘

依赖关系：
  U4 依赖 U3（IC 防覆盖）——注入管线已实现，问题在上游可达性 + 过滤叠加
  U10 依赖 U3（IC 防覆盖）+ 数据管道健康（sentiment/news 120s 循环是否产出数据；U9 的市场隔离间接相关——news 数据完整性）
  U12 的 section_ic_persistence 依赖 U3 修复后才稳定
  U12 的 section_hk_realtime 依赖 U1 修复后才稳定
```

**TDD 流程**（AGENTS.md 强制）：每个修复先写失败单测 → 实现 → 跑单测 → `verify_e2e.py` 全 PASS → commit。API 契约变更（如有）先写 `api-contracts/`。

---

## 四、验收总表

| 修复 | 验收条件 | 验证方式 |
|------|---------|---------|
| U1 | 连续 10 次 HK realtime 非空 | API 实测 + e2e section_hk_realtime |
| U2 | report_text >500 字符含三节 | task 结果断言 + e2e section_report_nonempty |
| U3 | 3 次 factor-health 后 IC 非空且稳定 | API 实测 + e2e section_factor_ic |
| U4 | etf_specific no_data ≤2、valid+warn ≥6 | /factors/active 断言 |
| U5 | calculate 中位数 <2s | 3 次采样 |
| U6 | balanced 现金 ≤15%（非交易时段除外） | design plans 断言 |
| U7 | 预热 <3s | warmup_timing.json |
| U8 | 前端热度 Tab 20 条 | 浏览器 + e2e section_contract_shape |
| U9 | HK 报告含恒生不含创业板 | e2e section_market_isolation |
| U10 | sentiment no_data=0 | /factors/active 断言 |
| U11 | core 两两重叠 ≤1 | design plans 断言 |
| U12 | 6 新 section 全 PASS | verify_e2e 全量 |

---

## 附录：修订记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-08-01 | 基于 round2 验证报告，对 12 项未修复问题完成根因深挖（代码行号实证）与修复方案（含依赖/优先级/验收），待多轮 review |
