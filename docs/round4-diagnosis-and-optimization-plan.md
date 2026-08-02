# ETF Surge — 第四轮全链路诊断与优化修复方案 (v1.0)

> 诊断环境：Docker prod 集群（backend :8000 / frontend :80 / redis :6379），构建快照 = `4c27cca` 之后的工作树（**注**：诊断期间并行 agent 提交了 `ba80488`（combination-design-review 批次 1-4 实现）与 `f99bb79`（docs），本报告针对**构建时快照**实测；凡涉及 ba80488 已修复项的结论已标注）。
> 诊断方法：预热 profiler（PROFILE_WARMUP=1）、组合设计/策略检查实测、A/HK/US 全链路 API 实测、Lighthouse 13.4.1、verify_e2e 全量、契约系统排查（子代理）。
> 状态图例：🔴 严重 / 🟡 中 / 🟢 正常

---

## 一、执行摘要

本轮（round4）在 Docker prod 环境完成 15 项诊断动作。核心结论：

1. **大量 round3 修复已生效**（预热 10.6s→2.47s、策略检查报告非空、IC 全 0 修复、港股行情恢复、搜索补全、sectors/heat 契约修复等，见 §四）。
2. **仍有 6 项严重问题**：R4-01 策略检查行业集中度误报、R4-13 HK/US 报告混 A 股（N04 修了一半）、R4-15 组合设计方案验收未达标（A500 缺失 + A100 混卫星）、R4-18 verify_e2e 门禁必崩、R4-19 首页 Lighthouse P<60 + CLS 0.41、R4-21 场外累计盈亏口径失真（用户报障 -21.44%，已入 P1-6 高优先级）。
3. **测试防护体系失效的直接证据**：verify_e2e.py `print_summary` UnboundLocalError 必崩（全 PASS 也崩），LHCI 门禁从未接入 CI——「门禁存在但空转」。
4. 并行 agent 提交 `ba80488` 声称实现 combination-design-review R1-R79，**需在最新代码上复验**（本报告 R4-15 基于构建时快照）。

---

## 二、诊断环境与方法（步骤 1-2）

| 项 | 值 |
|---|---|
| Docker 镜像 | etf_surge-backend:latest (cd50778e)、etf_surge-frontend:latest (a6bb3085) |
| 容器 | backend-1 :8000 / frontend-1 :80 / redis-1 :6379，/health 200 |
| 后端诊断工具 | 内置 WarmupProfiler（cProfile + pyinstrument + 分段计时），PROFILE_WARMUP=1 |
| 前端诊断工具 | Lighthouse 13.4.1（playwright headless-shell，生产 nginx） |
| E2E 门禁 | verify_e2e.py 全量 22 模块组 |

## 三、后端预热性能诊断（步骤 3）

**总时长 2.47s**（历史：38s → 3s → 1.77s → round3 10.6s → 本轮 2.47s）。

| 分段 | 耗时 | 占比 |
|---|---|---|
| warmup_market_cache | 2243.9ms | 91% |
| init_db | 76.6ms | 3% |
| redis_init | 74.5ms | 3% |
| warmup_etf_cache | 73.9ms | 3% |
| warmup_global_indices | 3.9ms | <1% |

**热点**（pyinstrument）：`warmup_market_cache → get_portfolio_realtime → run_sync 同步等待 1.48s`（外部数据源慢响应，疑似单只行情等待）。`warmup_global_indices` 3.9ms（round2 F2-5 的 gather 并行化已生效）。

**结论**：预热远低于 20s 失败线；唯一持续热点是 `get_portfolio_realtime` 内 1.48s 同步等待 → 见 P3-3 修复项。

## 四、组合设计 + on_exchange 策略检查审阅（步骤 4）

### 4.1 执行结果
- design 327（balanced, 500k）：completed，report_quality=full，三套方案（防御/平衡/进攻）层预算完整、现金 15%。
- strategy-check 234（on_exchange）：completed，holdings_analysis 10/10、suggestions 10（8 LLM + 2 rule）、risk_warnings 4、report_text 完整（N01 修复 ✅）。

### 4.2 报告质量审阅（结合最新行情）
**良好**：市态正确注入（range_bound →「市态：震荡」）；建议均带理由与置信度；rule 兜底明确标注（诚实降级）；风险提示含 affected_symbols。

**问题**：
- 🔴 **R4-01 行业集中度误报**：「仅覆盖1个行业，最大行业占比76%」——组合实际覆盖 ≥7 行业。根因：`_compute_risk_warnings`（portfolio_service.py:926-945）读 `h.get("sector")`，而 `holdings_analysis` 无 sector/industry 字段 → 全归空行业。**误导性风险提示**。
- 🟡 **R4-02 今日涨跌列空**：design 327 表格「今日涨跌」全为 —；verify_e2e 对 design 331 同检查 PASS（41 单元格）→ 与数据源当日数据可用性耦合（数据源降级时静默缺失）。
- 🟡 **R4-03 预期收益未调整**：expected_return == expected_return_current（8/11/16%）——市场状态调整逻辑未生效或未接入。

### 4.3 任务失败定位
本轮两个任务均成功。历史失败模式（LLM 超时 → rule 兜底）本轮未触发，但 verify_e2e 触发 task 95/98 时策略检查走兜底路径（holdings_analysis 用 rule 补齐，行为符合 Z26 设计）。

## 五、多市场行情分析（步骤 5）

| 链路 | 结果 | 备注 |
|---|---|---|
| 实时行情 A/HK/US（6 只） | ✅ 全通 | 513010 0.628 / 513500 2.509，N03 修复 |
| 综合研判 llm-report | ✅ 1915 字 | 市场全景+指数+矛盾分析 |
| AI 投顾问答 llm-advice | ✅ 818 字 | 有市场背景注入 |
| 个股分析 600519 | ✅ 38.7k 字 | 🟡 前端路径技术面完整；基本面（PE/PB）未注入（R4-09） |
| ETF 分析 510300 | ✅ 35.3k 字 | 有基本面概览 |
| 港股分析 513010 | ✅ 41k 字 | 内容混 A 股（R4-13） |
| 美股分析 513500 | ✅ 28.7k 字 | 内容混 A 股（R4-13） |
| 板块分析半导体 | ✅ 46.7k 字 | |
| 概念分析 AI | ✅ 57k 字 | |
| 指数分析 | ✅ 17 项 available | 韩国 +17.91%/日经 +4.03% 为周五真实行情（R4-07 已确认正常） |
| 搜索补全（代码/中文/拼音） | ✅ 全通 | HK 搜索 5.5s 超门禁（verify_e2e FAIL）——**已由 R4-26 修复**（spot 失败缓存 1h + 超时 4s，稳态 0-16ms） |

**专业投资者视角**：AI 输出整体逻辑严谨、诚实降级到位（无数据不捏造）；但 R4-09（个股数据缺失）与 R4-13（HK/US 混 A 股）直接削弱研判可信度，**当前不建议专业投资者直接采信 HK/US 综合研判与个股深度分析**。

## 六、热点/自选/技研/资讯/因子（步骤 6-10）

- 热点板块 11 个（题材理由+领涨股）✅、热门个股 50 只 ✅、sectors/heat 修复 ✅（N05）。
- 自选 A/HK/US 添加 201 + realtime 回显 ✅（N07 修复）。
- 持仓技研 10 只全量指标 ✅，signal 与策略检查基本一致（518880 口径差异待核）。
- 资讯等级分布合理（1:19/2:8/3:6/4:11/5:1）✅，AI 智能分析质量良好 ✅；`/news/stock` 中文键隐患（R4-06）。
- 因子：188 模型完整、33 活跃（19 valid/11 no_data/3 static）——N06 IC 全 0 修复 ✅、Z04 部分（5/10）、sentiment 4 个 IC 样本<3、style 2 个缺数据源。

## 七、前后端数据断裂排查（步骤 11）

- 🔴 R4-13 HK/US 混 A 股（见 §五）。
- 🟡 R4-05 realtime/batch 逗号分隔只返回 1 条（前端未用，契约隐患）。
- 🟡 R4-06 news/stock 中文键（前端未消费，契约隐患）。
- 🟡 R4-11 前端 4 处弱断裂（SectorHeatMap 涨跌幅、Chart KDJ/RSI 子图、FactorIC 分类过滤、FactorModel tooltip）——均有防御不崩溃。
- ✅ 其余 20+ 链路字段契约一致。

## 八、docs 问题清单验证（步骤 12）

| 来源 | 项 | 状态 |
|---|---|---|
| round2-unfixed | U1 港股 null / U2 报告空 / U3 IC 全0 / U7 预热 6.6s / U8 sectors-heat | ✅ 修复 |
| round2-unfixed | U4 etf_specific | 🟡 部分（5/10） |
| round2-unfixed | U5 组合计算 8.2s | 🟡 5.1s 未达 <3s |
| round2-unfixed | U6 现金仓位 | 🟡 15% 恒高待核 |
| round2-unfixed | U9 HK/US 混 A 股 | 🔴 未修复（R4-13） |
| round2-unfixed | U10 sentiment | 🟡 有数据 IC 样本不足 |
| round2-unfixed | U11 核心层重叠 >1 | 🟡 未修复（平衡∩进攻 3 只，已入 P1-2） |
| round2-unfixed | U12 T 系列防护 | 🟡 verify_e2e 部分落地 |
| round3 | N01/N02/N03/N05/N06/N07/N08/N09 | ✅ 修复 |
| round3 | N04 HK/US 混 A 股 | 🔴 半修复（indices 未过滤） |
| round3 | Z04 / Z06 / Z09 / Z15 | 🟡/✅（Z09 ✅、Z15 部分） |
| combination-design-review | 验收1/3 | ✅ |
| combination-design-review | 验收2（A500 入核心）/验收4（卫星无宽基） | 🔴 FAIL（R4-15） |
| factor-and-strategy-check-review | 三问题 | ✅ 修复（因子 19 valid / 建议带理由） |

## 九、测试防护体系分析（步骤 13，详见 `_round4_test-gap-analysis.md`）

**6 类根因**：
1. 内容语义断言缺失（R4-01/03/09/13；R4-07 已确认为真实行情、不设门禁，见 findings）
2. HTTP 契约层无覆盖（R4-05/09）
3. 前端 mock 掩盖真实契约（R4-11）
4. 门禁阈值=历史问题值（R4-14/16）
5. **门禁脚本自身可信度未验证**（R4-18 verify_e2e 必崩；R4-19 LHCI 未接入 CI）
6. 多市场/多形态未覆盖（R4-06/13）

## 十、优化修复方案（P0-P3）

> 本方案为**实施标准设计**，按 AGENTS.md 契约先行 + TDD 流程执行；本轮**不实施**。

### 🅿️0 阻断性（本轮必须修，不修则专业投资者不可信）

**P0-1：策略检查行业集中度修复（R4-01）**
- `strategy_check_worker` 产出 `holdings_analysis` 时注入 `sector`/`industry` 字段——**数据源唯一定夺**：从 `market_data_hub` 候选池条目（`item.get("industry")`，与设计任务同一来源）构建 `symbol→industry` 映射，失败时回退 `ET_SPECIFIC` 因子矩阵的 `industry` 字段；不再保留「factor_matrix 或行业映射」二选一。
- `_compute_risk_warnings` 增加空行业保护：若 `sector_weights` 中空串权重 >0 且 `unique_sectors<=2`，降级为 WARN 而非 HIGH，并标注「行业数据缺失（数据源未覆盖）」。
- 验收：strategy-check 报告的行业集中度提示在组合覆盖 ≥7 行业时不再误报「仅覆盖1个行业」；行业缺失时输出 WARN+标注而非 HIGH（单测 mock 空行业断言）。

**P0-2：HK/US llm-report 指数过滤（R4-13 / N04 补全）**
- `llm_report`/`llm_report_stream`：`indices` 按 `market_ctx.index_symbols` 过滤（对齐 market_data 的 N04 修复）；`commodities` 同理按市场过滤。
- 验收：`POST /analysis/llm-report {"symbols":["513010"],"market":"HK"}` 报告中无「上证指数/深证成指/沪深300」等 A 股指数引用；单测覆盖（mock indices 含 A/HK，断言 prompt 只含 HK 指数）。

**P0-3：verify_e2e.py print_summary 修复（R4-18）**
- `print_summary` 加 `global PASS, FAIL, SKIP`（或改用返回值累计），消除 UnboundLocalError。
- 追加**门禁自检**：verify_e2e 结束必须打印 "X/Y 通过"，且 exit code 与 FAIL 数一致；在 CI 中验证「全 PASS 时 exit 0」。
- 验收：`python scripts/verify_e2e.py --module zscore` 正常打印总结并 exit 0。

**P0-4：首页 CLS 修复（R4-19）**
- 子步骤 1（复现定位）：本地 prod 构建 + Lighthouse 对 `/` 与 `/dashboard` 各采样 3 次，记录 CLS 数值与「偏移发生帧」——确认是否由 Dashboard 首屏并行 API（realtime/portfolio、indices、news、sectors/heat）数据到达时序触发（数据注入 → 卡片高度变化 → 布局偏移）。
- 子步骤 2（改动清单）：①卡片容器按内容上限预留固定 `min-height`（定位组件：Dashboard 指标卡 grid 容器，见 `frontend/src/components/dashboard/`）；②WS 推送更新（realtime 行情）改 `transform: translate` 或绝对定位，避免触发重排；③若根因是首屏折叠内容（above-the-fold 为空），调整渲染顺序先出骨架。
- 子步骤 3（CI 门禁）：LHCI 配置接入 CI（`npx lhci autorun`，预算 performance≥60、CLS≤0.1）。
- 验收：Lighthouse 首页 CLS ≤ 0.1、Performance ≥ 60（3 次采样中位数），LHCI 在 CI 中通过。

### 🅿️1 高优先级（数据质量/方案质量）

**P1-1：combination-design-review 验收补齐（R4-15）**（大型修改，跨 ba80488 复验 + 候选池 + 引擎 + verify_e2e，拆 4 子步骤）
- 子步骤 1（复验基线）：在最新代码（含 ba80488）上重新生成 design，核对三方案核心层是否含 A500（560600/159338）且卫星层无宽基——先确认现状，记录偏差。
- 子步骤 2（CORE_REQUIRED 缺口）：若 A500 未入核心，修复候选池强制注入（`MANDATORY_CODES`/`CORE_REQUIRED` 逻辑，`engine/allocation_engine.py` + `market_data_hub` 候选池），确保 560600/159338 进入候选池且被强制保留。
- 子步骤 3（M5 卫星排除）：卫星层 backup 补足时排除 `industry == "宽基指数"`（`allocation_engine.py` 步骤 D），并**按名称/指数语义补判**（A100 562000 industry=unknown 的漏网，见 R4-29 同类问题）——A100 不得入卫星。
- 子步骤 4（门禁落地）：design-quality 断言进 verify_e2e（三方案核心含 A500+沪深300、卫星层无宽基）；附「组合文档 M/P ↔ 本方案」术语映射（M5=卫星宽基排除、CORE_REQUIRED=核心强制注入、U11=跨方案去重，对应本 plan P1-2）。
- 验收：design 新纪录三方案核心层含 A500+沪深300、卫星层无宽基（verify_e2e design-quality 模块自动断言）。

**P1-2：U11 核心层跨方案重叠 ≤1（R4-14）**
- 分配引擎（`engine/allocation_engine.py` allocate() 核心层选取段）：三方案核心层候选去重——每方案核心层选取时排除前序方案已占用的核心标的；**保留沪深300（510300）为公共底仓的例外**（强制标的，不计入重叠上限），重叠上限 = 公共底仓 1 只。
- 补充判定规则：重叠计数仅统计「非强制、非公共底仓」的核心标的；`_dedup_segment` 归一化覆盖 上证50/中证A50/科创50 家族（现仅覆盖科创前缀与中证500/300 家族，R4-14 同源缺陷）。
- 验收：verify_e2e diversity 检查阈值收紧为「任意两方案核心层重叠（剔除公共底仓）≤1」。

**P1-3：个股分析基本面注入 + asset_type 归一化（R4-09）**
- `symbol_analysis_stream`：采集 `get_market_fundamentals(symbol)` 注入 prompt（PE/PB/ROE 缺失时明确标注数据源不可用）；`asset_type` 枚举归一化（'stock'→'A'），`get_history` 失败时按 'A' 重试。
- 验收：600519 报告含基本面段（估值数据缺失时显式标注），单测覆盖 asset_type 归一化路径。

**P1-4：今日涨跌列数据源降级显性化（R4-02）**
- 实施：`design_text` 生成（`_build_plan_tables`）时若当日涨跌数据缺失，输出「数据源不可用」而非空 `—`；verify_e2e R10 区分「真实 0%」与「缺失」（依据 data_available/_stale 标记）。
- 验收：数据源降级时 R10 记为 WARN 而非 PASS；design 表格缺失涨跌显示「数据源不可用」。

**P1-5：海外流动性数据接入（R4-23，用户反馈盲区）**（大型修改，拆 3 子步骤）
- 背景：市场综合研判 prompt 要求分析「美债、美元、油价、地缘冲突传导」，但注入数据缺失——`global_markets_fetcher` 已有 5 个 FRED fetcher（美债 10Y DGS10 / VIX / 联邦基金利率 / CPI / 非农，实测全部可用，`FRED_API_KEY` 已配置），**但全 backend 无调用点**；美元指数无 fetcher；油价源非交易时段返回 0。
- 子步骤 1（FRED 接线，零新依赖）：将 `fetch_us_10y / fetch_vix / fetch_fed_rate`（**首期仅此 3 个，CPI/非农暂不接入**，控制 prompt 长度）接入 `llm_context.build_full_context()` 与研判 prompt，新增「### 海外流动性」数据段（美债 10Y、VIX、联邦基金利率）；失败静默（返回 None 时不注入该段，不影响主报告）。
- 子步骤 2（美元指数 + 油价降级）：美元指数 fetcher **定夺唯一源**：akshare `fx_pair_quote`（USDCNY 等货币对）——放弃东财 DXY 映射（无稳定接口）；油价源加「交易时段拉取 + 失败降级到国内原油期货/上次成功缓存」保护（非交易时段不再空，复用 R4-26 失败缓存模式）。
- 子步骤 3（地缘新闻注入）：从 macro_news 筛选地缘/海外流动性类新闻（关键词：美联储/美债/美元/原油/地缘/关税）注入海外流动性段，给 LLM 素材。
- 验收：研判报告「海外流动性」段出现真实美债 10Y/VIX 数值（数据源正常时）；非交易时段不报错、报告仍完整；单测覆盖 FRED 接线与失败静默。

**P1-6：场外累计盈亏口径修复（R4-21，用户报障）**
- 背景：场外累计盈亏显示 -21.44% 失真——`calculate_cumulative_pnl` R64 估算分支对场外联接基金混用「场内 ETF 实时价」估算份额与「联接基金单位净值」成本（两者量级差 2-5 倍，半导体 3.53 vs 场内 0.67 等），单只盈亏率严重错配。
- 实施（**定夺唯一口径**：`portfolio_service.py calculate_cumulative_pnl` R64 分支）：
  1. off_exchange 估算改为「`est_shares = 目标金额 / avg_cost` → `cost_basis = 目标金额`」——份额按联接净值折算，成本=投入本金；
  2. 市值估算**唯一口径**：`market_value = 目标金额 × (1 + 跟踪指数估算涨跌幅)`；跟踪指数无涨跌幅数据时降级 `market_value = 目标金额`（盈亏 0，并标 `estimated=True` + 提示「净值变动暂缺」），**不采用场内 ETF 价格直接估值**；
  3. 019633 avg_cost=3.534 疑似录入异常——输出 WARN 日志提示用户核对（不改数据）。
- 验收：场外 pnl-history 单只盈亏率与「联接净值变动」语义一致（mock 用例：avg_cost 与场内价量级差 5 倍时，单只 pnl% 不再放大）；单测覆盖净值/场内价错配场景。

**P1-7：A 股个股搜索本地化（R4-29，用户体感 5-6s）**（拆 3 子步骤）
- 背景：instruments 表仅含 ETF（1544 行），A 股个股 0 行 → 个股搜索降级 levistock 外部拉取（冷缓存首次 2.7-4s）。
- 子步骤 1（灌数）：运行 `backend/scripts/sync_instruments.py` 个股段（`stock_zh_a_spot_em`，含拼音/首字母生成）灌入 instruments；确认脚本按段独立统计——个股段若失败，单独诊断（akshare 可用性/列名映射）。
- 子步骤 2（验证）：灌入后 `SELECT COUNT(*) FROM instruments WHERE asset_type='stock' AND market='A'` 应 >5000；`market=A` 与跨市场（include_stocks）搜「茅台」「宁德」「600519」稳态 <100ms。
- 子步骤 3（回归）：重启后端后重测（无冷缓存惩罚）；verify_e2e 搜索模块加「个股命中」断言（原只验 ETF）。
- 验收：instruments 表含 A 股个股（>5000 行）；搜「茅台/宁德」稳态 <100ms（重启后仍快）。

### 🅿️2 中优先级（性能/契约）

> P2-6 为补充项（review 第 1 轮发现 R4-03 无修复项，已闭合）。

**P2-1：组合计算与预热同步等待优化（R4-16 / 预热 1.48s）**
- 调用点：`portfolio_service._build_price_map_async`（A/HK/US/指数四类并行已 gather，剩余为单源慢等待）+ `get_portfolio_realtime` 内同步等待。
- 实施：多源并行基础上增加**单源超时截断**（每源 `asyncio.wait_for` 收敛到 3s，慢源降级为空并 WARN）；预热路径同参数。
- 验收：`/portfolio/calculate` 端到端 ≤3s、预热 market_cache ≤1.5s（verify_e2e calculate 门禁收紧至 3s）。

**P2-2：realtime/batch 契约明确（R4-05）**
- **定夺唯一方案**：后端统一解析——`/market/realtime/batch` 与 `realtime` 的 symbols 参数同时支持「重复参数」与「逗号分隔」（逗号分隔按逗号 split 全量解析，不取首项），契约文档（`api-contracts/market/realtime.md`）写明两种形态等价。
- 补 e2e 多符号用例：`symbols=510300,510880` 断言返回 2 条（当前只返回 1 条）。

**P2-3：news/stock 键归一化（R4-06）**
- `fetch_stock_news` 增加中文键→英文键归一化（新闻标题→title、新闻内容→content、发布时间→time、新闻来源→source、新闻链接→url），与 headlines 一致。
- 验收：`/news/stock/{symbol}` 返回键与 headlines 一致（英文键）；单测覆盖中文键输入。

**P2-4：前端 4 处弱断裂修复（R4-11）**（4 处独立，可并行，各自验收）
- SectorHeatMap：后端 heat item 补 `change_pct` 或前端移除该条件渲染——验收：板块热度卡片涨跌列不再恒空。
- AnalysisView chart：后端 `compute_chart_data` 补 kdj/rsi 序列（或前端改 indicators 数据源）——验收：图表技术指标系列非空。
- FactorICView：分类过滤选项改 `china_specific`/`etf_specific`——验收：过滤选项与后端 categories 一致。
- FactorModelView：factor entry 补 category 字段或 tooltip 从父级映射——验收：因子模型页 tooltip 有分类。

**P2-6：预期收益市场调整显性化（R4-03）**
- 先核实：`dynamic_layer_budget`/预期收益调整逻辑（budgets.py）在 range_bound 市态下是否本应调整 `expected_return_current`——若本应调整而未生效则定位修复；若设计上该市态不调整，则在报告中对「当前预期年化 == 预期年化」给出显式说明（标注「当前市态未触发调整」），避免默认同值误导。
- 验收：design 报告对「当前预期年化 == 预期年化」给出显式说明或数值已随市态调整；单测覆盖调整逻辑的分支。

### 🅿️3 低优先级（增强，暂缓——补实施方向与验收，不排期）

**P3-1**：tasks/designs 列表响应缓存或字段裁剪（0.6s 稳定耗时）。
- 实施：`/portfolio/tasks` 与 `/portfolio/designs` 列表字段裁剪（去掉 raw_llm/超长字段）或加 30s 内存缓存。
- 验收：列表接口稳态 <200ms。

**P3-2**：style 因子数据源（fund_scale/float_mv）与 sentiment IC 累积（Z10 收尾）。
- 实施：fundamentals 拉取注入 fund_scale/float_mv 到因子矩阵（style.size.ln_mcap 依赖）；sentiment 因子 IC 样本 <3 随交易日自然累积。
- 验收：`/factors/active` style 因子不再 no_data（数据源可用时）。

**P3-3**：watchlist 首次加载优化（R4-20，批量行情替代单只循环）。
- 实施：`/watchlist` 实时行情改为 `fetch_a_stock_batch` 批量拉取（当前单只循环 2.27s）。
- 验收：watchlist 首次加载稳态 <800ms。

## 十一、实施优先级与依赖

```
P0-1 (strategy-check 行业)      ← 独立，最高优先
P0-2 (HK/US 指数过滤)           ← 独立，LLM 报告可信度
P0-3 (verify_e2e 自检)          ← 独立，防护体系地基，先行修以便后续验收
P0-4 (首页 CLS)                 ← 前端，需 CI 接入
P1-1/P1-2 (方案质量)            ← 依赖 ba80488 复验
P1-3 (个股分析数据)             ← 独立
P1-4 (今日涨跌降级)              ← 独立
P1-5 (海外流动性接入)            ← 独立，FRED fetcher 已就绪仅接线
P1-6 (场外盈亏口径)              ← 独立，误导性输出需优先
P1-7 (个股搜索本地化)            ← 独立，需 akshare 可用时跑 sync_instruments
...
```

## 十二、验收总表

| 修复项 | 验收方式 | 门禁 |
|---|---|---|
| P0-1 | strategy-check 报告断言（内容级）；空行业 WARN+标注 | verify_e2e 新检查 |
| P0-2 | llm-report market=HK/US 内容纯净断言 | verify_e2e + 单测 |
| P0-3 | verify_e2e 正常 exit 0 | CI 门禁 |
| P0-4 | Lighthouse 首页 CLS≤0.1 / P≥60（3 次中位数） | LHCI 接入 CI |
| P1-1 | design 新纪录核心层含 A500+沪深300、卫星层无宽基 | verify_e2e design-quality |
| P1-2 | 两方案核心层重叠（剔除公共底仓）≤1 | verify_e2e diversity |
| P1-3 | 600519 报告含基本面段 | 单测 + e2e |
| P1-4 | 数据源降级时 R10 记 WARN；design 表格显示「数据源不可用」 | verify_e2e R10 |
| P1-5 | 研判报告海外流动性段含真实美债 10Y/VIX；非交易时段报告仍完整 | 单测 + 链路验证 |
| P1-6 | 场外 pnl-history 单只盈亏率与联接净值变动语义一致（量级悬殊用例） | 单测 |
| P1-7 | instruments 含 A 股个股（>5000 行）；搜「茅台/宁德」稳态 <100ms | sync 脚本 + 链路验证 |
| P2-1 | `/portfolio/calculate` 端到端 ≤3s、预热 market_cache ≤1.5s | verify_e2e calculate 门禁 |
| P2-2 | batch `symbols=510300,510880` 返回 2 条 | e2e 多符号用例 |
| P2-3 | `/news/stock/{symbol}` 返回英文键 | 单测 + e2e |
| P2-4 | 4 处弱断裂各自验收（涨跌列/图表序列/过滤选项/tooltip） | 前端测试 + 走查 |
| P2-6 | design 报告「当前预期年化」显式说明 | 单测 + e2e |
| P3-1 | tasks/designs 列表稳态 <200ms | 性能采样（暂缓） |
| P3-2 | factors/active style 因子不再 no_data（数据源可用时） | 链路验证（暂缓） |
| P3-3 | watchlist 首次加载稳态 <800ms | 性能采样（暂缓） |

## 附录 A：本轮问题清单（R4-01 ~ R4-29，无 R4-04 编号，详见 `_round4_findings.md`）

## 附录 B：修订记录
- v1.0 (2026-08-02)：round4 全量诊断完成，形成 P0-P3 修复方案（未实施）。
- v1.1 (2026-08-02)：新增 P1-5 海外流动性数据接入（R4-23，FRED fetcher 已就绪仅接线）；findings 补 R4-22（策略检查建议丰富化，已实施）；R4-07 更正为已确认正常数据并删除 P2-5。
- v1.2 (2026-08-02)：新增 P1-6 场外累计盈亏口径修复（R4-21）与 P1-7 A 股个股搜索本地化（R4-29）；findings 补 R4-29（个股补全慢：instruments 无个股 + levistock 冷缓存）；R4-24~R4-28 已实施项记录于 findings。
- v1.3 (2026-08-02)：多轮 review 修订——①修复 P1-4 正文错位（内容从 P1-7 下移回）并补实施/验收；②验收总表补齐 8 个缺失 P 项（P1-4/P2-1~P2-4/P3-1~P3-3）；③统一 R4-21 严重度（执行摘要 5→6 项，P1-6 注明用户报障）；④大型修改细化：P1-1 拆 4 子步骤（含术语映射）、P1-5 拆 3 子步骤（美元指数定夺 fx_pair_quote、首期仅 3 个 FRED 指标）、P0-4 拆 3 子步骤（含复现定位）、P1-7 拆 3 子步骤、P2-4 四处在各自验收；⑤定夺「或」方案：P0-1 行业映射唯一数据源、P1-6 市值唯一口径（联接净值）、P2-2 后端统一解析；⑥P1-2 补 R4-14 编号与重叠判定规则（公共底仓例外 + 上证50/A50/科创50 家族归一化）；⑦§九 根因 1 移除 R4-07、§五 搜索行标注 R4-26 已修复；⑧P3-1~P3-3 补实施方向与验收（标暂缓）；⑨附录 A 注明无 R4-04。
