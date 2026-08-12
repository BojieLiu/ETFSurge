# Round16 容器验收诊断（2026-08-11）— 性能/数据质量/断裂/测试盲区全链路诊断与优化方案

> **性质**：容器验收诊断（对标 round14 流程）——构建最新代码 → 全链路功能验收 → 性能诊断 → 数据质量审阅 → 测试盲区归因 → 冗余清理 → 优化方案（**本份只设计不实施**）。
> **验证窗口**：2026-08-11（周一，交易日）12:47-13:50 UTC+8；外部数据源（akshare/东财/新浪）可用性波动属运行环境常态，本诊断结论标注「数据源冷却期实测」处需交易时段复测。
> **环境**：Docker prod profile（`docker-compose.yml` + `docker-compose.diag.yml` 诊断 override，`PROFILE_WARMUP=1`）；commit `1fa316c`；后端 8000 / 前端 80。

---

## 一、诊断范围与方法

| 阶段 | 动作 | 结果落点 |
|---|---|---|
| 1 构建 | `docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod up -d --build`，回收老镜像 | §2 |
| 2 预热诊断 | `PROFILE_WARMUP=1` WarmupProfiler（pyinstrument + cProfile + `/system/warmup`） | §2.1 |
| 3 组合设计+策略检查 | `POST /portfolio/design-async`（balanced 50w）→ design_id=506；`POST /portfolio/strategy-check-async`（on_exchange）→ task 384 | §3.1/§3.2 |
| 4 三市场分析 | llm-report / llm-advice / symbol-analysis / sector-analysis / search（A/HK/US） | §3.3 |
| 5-9 功能验收 | hot-plates / stock-hot-rank / watchlist / signals / news / factors | §3.4-3.8 |
| 10 断裂排查 | 前端 47 API + 4 SSE + 3 WS 全量比对 + design 506 运行时验证 | §3.9 |
| 11 docs 落地 | round14/round15 四文档方案核对（静态 + 运行时） | §4 |
| 12 前端性能 | Lighthouse 13.4.1 五页面 | §2.2 |
| 13 后端性能 | 15 条热点链路冷/热态耗时 | §2.3 |
| 14 测试盲区 | 本轮发现 vs 测试防护体系归因 | §5 |
| 15 冗余 | 41 项清理清单（P0×24/P1×13/P2×4） | §6 |

> **方法约束**（design-checklist D1-D3）：所有结论附 `file:line` 与实测命令输出；外部数据源结论标注验证窗口；非交易时段结论打标「待复测」。

---

## 二、性能诊断结论

### 2.1 后端预热（PROFILE_WARMUP=1，产物 `logs/warmup_timing.json` / `warmup_cprofile.txt` / `warmup_pyinstrument.txt`）

预热总耗时 **12861.5ms**（分段累计）/ 墙钟 7.6s（后台并行），瓶颈：

| 分段 | 耗时 | 占比 | 根因（cProfile 证据） |
|---|---|---|---|
| warmup_market_cache | 7366.8ms | 57% | `get_portfolio_realtime` 网络等待 2.68s；`fetch_fund_nav` 10 次累计 15.08s（akshare `fund_open_fund_info_em` 5.9s）；`fetch_macro_snapshot` 单次 **7.49s**（12 个 HTTPS 串行连接累计 7.5s） |
| warmup_global_indices | 5405.5ms | 42% | 12 个 HTTPS 连接累计 7.5s（urllib3 `create_connection` 4.88s） |
| init_db / redis_init / etf_cache | 88.5ms | <1% | 正常 |

**结论**：预热 7.6s 达标（≤25s 门禁），但 market_cache 段 7.4s 全部为网络 IO 等待，`fetch_macro_snapshot` 单点 7.49s 是最优优化目标（串行→并发 or 缓存延长）。

### 2.2 前端 Lighthouse（13.4.1，五页面）

| 页面 | performance | accessibility | LCP | TBT | **CLS** | 备注 |
|---|---|---|---|---|---|---|
| **home（Dashboard）** | **55** | 96 | 3.4s | 570ms | **0.389** | mainthread 2.8s、unused-js 85KiB |
| market | 99 | — | 2.0s | 30ms | 0.001 | — |
| portfolio | 99 | 100 | 2.0s | 30ms | 0.001 | — |
| factors | 99 | 100 | 2.0s | 30ms | 0.001 | — |
| news | 97 | 94 | 2.0s | 160ms | 0.034 | — |

**结论**：home 是唯一不达标页（perf 55 < 60 软门禁）；**CLS 0.389 超标 3.9 倍**（阈值 <0.1）——round14 P1-G 声称已修复（`SummaryCards.vue:200-209` min-height + 骨架屏），但**无实测记录**（见 §5 盲区④）。market/portfolio/factors/news 全部优秀，说明问题集中在 Dashboard 首页（组件集 + 数据加载时序），非全局构建问题。

### 2.3 后端热点链路（冷/热态，`scripts_diag/task13_latency.json`）

| 链路 | 冷态 | 热态 | 基准 | 结论 |
|---|---|---|---|---|
| **watchlist** | **5.65-7.75s** | 10-20ms | ≤3s | **冷态超标 ~2 倍**（round14 P2-AF 已做 per-item 超时分级，但冷缓存首拉仍全量触网） |
| stock_hot_rank | 3.33-4.7s | 150-330ms | — | 冷态超标（东财热搜首拉） |
| global_indices | 2.97-5.11s | 10-20ms | — | 冷态超标（24h 磁盘缓存失效后首拉） |
| sector_heat | 2.56-3.72s | 10ms | — | 冷态超标 |
| indicators | 1.84-1.99s | 70-90ms | ≤2s | 冷态贴线（K 线首拉） |
| search / factor_health / signal / chart | 60-90ms / 20ms / 80ms / 70ms | 同 | ≤1s/≤2s | 达标 |
| designs_list | 660-890ms | 660-890ms | — | **热态偏高且不降**（DB 查询无缓存，见 §7 P0-8） |

**结论**：热态全达标，问题集中在「首次请求触网」冷缓存路径——watchlist 冷态 7.75s 是最严重项（前端首屏加载即触发）。

---

## 三、功能验收结论

### 3.1 组合设计（design_id=506，quality=full）

**执行**：`POST /portfolio/design-async` `{risk_profile:balanced, capital:500000, mode:enhanced}` → task 383 → completed（refresh 25.77s + LLM 报告 105s）。

**数据正确性（核心验收）**：

| 校验项 | 结果 | 证据 |
|---|---|---|
| 今日涨跌幅 vs 实时行情 | **15/15 匹配** | `scripts_diag/design_pct_verify.json`（510300 -0.65%/-0.65、588000 -1.58%/-1.58 等） |
| RSI vs 指标接口 | **15/15 匹配**（取整误差 <0.6） | `scripts_diag/design_ind_verify.json` |
| MACD 方向 vs 指标接口 | **15/15 一致** | 同上 |
| 方案结构 | 防御 47/20/12、平衡 50/22/12、进攻 50/20/12（core/sat/defense） | design 506 `strategies` |
| 报告正文 | ⚠️ **结尾「报告生成失败」占位符，quality 却=full** | `design_506_report.md:66` |

**审阅发现（专业投资者视角）**：
- ✅ 涨跌幅/RSI/MACD 与最新行情**完全匹配**，数据管线准确；
- ✅ 三套方案风格区分合理（防御用红利低波+上证50 压舱、进攻用科创50+中证500 博弹性），权重层预算合规（Σ≤1 且留现金）；
- ❌ **P0-1 反假完成**：LLM 报告第二段（市场环境与配置建议）返回空 → `llm.py:1646` `result or "报告生成失败"` 兜底 → `task_manager.py:445-465` 只验 `len(llm_analysis)>0` 标 `quality=full`——**用户看到的是「方案表格完整 + 市场分析占位符」，被标记为 full 会误导**（"报告生成失败"这 6 个字是 LLM 空响应的证据，却出现在"完整报告"里）；
- ⚠️ akshare 熔断期间 `_compute_fund_flow` 返回空（资金流因子缺失），候选池 26 只（正常 1618→过滤后），但静态池兜底未打降级标记到报告。

### 3.2 on_exchange 策略检查（task 384）

**执行**：`POST /portfolio/strategy-check-async` `{capital:500000, portfolio_type:"on_exchange"}` → completed，coverage 11/11。

**审阅发现**：
- ✅ **规则引擎兜底生效**：LLM 73s ReadTimeout 全超时 → `covered_by_rule=11, covered_by_llm=0`（round14 P0-B 的兜底设计按预期工作，覆盖率 100%）；
- ❌ **P0-2 名称显示**：`510300` 显示为「510300 ETF」（名称未命中回退），专业用户会困惑；
- ❌ **P0-3 因子分口径不一**：`159338 因子分 1.00 → increase`，而 `518880 因子分 6.32 → hold`——规则引擎的 increase/hold 阈值与因子分尺度不匹配（-0.72 判"弱"、-0.43 判"中性"、6.32 判"中性区间"），文案口径混乱；
- ❌ **P1-4 模板化文案**：全部 11 条置信度 0.7、理由模板同质（"持有逻辑不变…关注 RSI 超卖"重复），规则引擎兜底的可读性/专业度不足（可接受，但应注明"规则引擎兜底"而非冒充 LLM 分析——当前报告已注明 ⚠️，✅）；
- ⚠️ LLM 全超时说明 `_llm_timeout_for` 75s 预算在真实排队下仍不足（73s 截断），P0-B 虽兜底但 LLM 分析实际从未成功过——**规则引擎是唯一输出源**。

### 3.3 三市场行情分析（A/HK/US）

| 链路 | A | HK | US | 结论 |
|---|---|---|---|---|
| 综合研判 llm-report/stream | ✅ 77.8s | ✅ 33.5s | ✅ 26.8s | **A 明显慢于 HK/US（2-3 倍）** |
| AI 投顾 llm-advice/stream | ✅ 66.8s | ✅ 33.3s | ✅ 19.1s | 同上 |
| 个股分析 symbol-analysis | ✅ 茅台 18.7s | ✅ 腾讯 39s | ✅ 苹果 30.6s | 全通 |
| ETF 分析 | ✅ 510300 25s | — | — | 全通 |
| 行业板块分析 | ✅ 半导体 34.2s | 友好提示 | 友好提示 | HK/US 按 P2-AL 缺数据 |
| 概念分析 | ✅ 新能源 59.8s（首次 90s 超时） | — | — | LLM 排队时可能超时 |
| 指数分析 | ✅ A 指数搜索正常 | — | ❌ US 指数搜索 0 命中 | 见 P0-22 |
| 搜索补全 | ✅ 510300→ETF/茅台→600519 排序正确 | ✅ 腾讯/00700 | ✅ AAPL（❌ Apple 英文名） | 见 P0-6 |

**审阅发现**：
- **P0-22 US 指数搜索断裂（取代 P0-5）**：`indices_meta` 表 588 条**无美股指数**（`sync_indices_meta.py` 数据源仅 A/港股/行业/概念）；且 `_search_indices`（`market.py:249-252`）market 过滤只处理 A/HK，**US 分支缺失** → 搜「道琼斯/纳斯达克」0 命中、搜「标普」返回港股 GEM/HKL；选中后 realtime 失败报错（详见 §3.24）；
- **P0-6 US 英文名搜索断裂**：`HKUS_STOCK_MAP`（`market_service.py:634`）AAPL 仅中文名"苹果"；`include_stocks` 时 spot 源（akshare）冷却失败 + 本地 `instruments` 表 **US 段 0 条**（同步逻辑在 `sync_instruments.py:91-116` 的 `collect_all` 已含 A股/ETF/港股/港股ETF/美股五段，但美股段 `stock_us_spot_em` 在当前网络环境黑洞 20s 超时失败、港股段受东财源冷却影响——**根因是数据源失败非同步逻辑缺失**）→ 搜 "Apple" 0 命中（round14 R6-F9 声称修复，但降级链依赖的表段从未成功填充）；
- **P1-3 A 股 LLM 链路慢**：llm-report 77.8s vs HK 33.5s vs US 26.8s——A 股上下文采集（新闻 120s 循环 + 板块缓存）与 LLM 排队叠加；概念分析 LLM 排队时可 90s 超时（复测 59.8s 通，属偶发排队非固定 bug）；
- ✅ 搜索排序契约（`_sort_search_results`）正确：精确代码 > 前缀 > 名称匹配，A 股实测首条即目标。

### 3.4 热点板块/个股（任务 5）✅

- hot-plates 14 个板块全部返回（含 secu_code/change/stock_count/lead_stocks/up_reason）；
- stock-hot-rank 50 只全部返回（rank/code/name/price/change_pct/concept_tags）；
- 数据源为东财+同花顺（冷却期有降级，但 14+50 均有真实数据非兜底）。

### 3.5 自选功能（任务 6）✅

- 添加 159919 → 201（id=18）；列表 17 只**全部带实时价**（510300 4.728/-0.65%、AAPL 308.26/-1.62%、00700 470.8/-2.2%）；重复添加 409 防重；
- 实时价格与设计报告涨跌幅一致（510300 -0.65% 双端吻合）；
- 结论：自选添加/获取/显示链路完整，A/HK/US 混合正常。

### 3.6 持仓技术分析与综合信号（任务 7）✅

- 11 只持仓 signal 全部返回：buy×3（159338/159516/510300）、hold×5、sell×2（159545/512000）；
- 交叉验证：signal + indicators（RSI/KDJ）数据一致；
- ⚠️ **两套信号口径并存**：`/market/signal/{sym}`（技术信号 buy/hold/sell）vs 设计报告 factor_scores（综合信号 -0.17 等）——510300 技术信号 buy 而因子综合信号中性（-0.17），用户界面需区分（非 bug 但易混淆）。

### 3.7 资讯分级与智能分析（任务 8）✅

- level 分布 1-5 齐全（`{1:2,2:14,3:6,4:7,5:2}`），level 5 为重大政策/业绩新闻合理；
- stars 全 4/5 为**时间新鲜度口径**（`news_fetcher.py:226-259`：<1h→5★、<6h→4★），财联社电报滚动源正常；
- news-impact 智能分析返回 `impact_scope/affected_holdings/summary/disclaimer`，降准新闻有实质分析（沪深300ETF 直接受益）；
- 结论：分级合理、智能分析可用。⚠️ 但 round15 基线 B 的 news 分级**测试用例失效**（见 §5 盲区②）。

### 3.8 因子模型（任务 9）⚠️ 数据积累期

- 38 因子分 6 类；`summary {valid:0, warn:0, no_data:27, static:11, avg_ic:0.1469}`；
- 3 static（政策识别因子无 IC 正常）；**27 no_data**（IC 样本 10-11 < 30，round14 P0-C 最小样本保护生效）；
- ⚠️ 页面显示 `valid=0` 属数据积累期正常态（容器刚重建，IC 样本需 ≥30 才发布），但**前端无「数据积累中」的引导文案**（用户可能误判因子全部失效）；avg_ic=0.1469 已现初步区分度。

### 3.9 前后端断裂排查（任务 10）

**无 404 断裂**：47 API + 4 SSE + 3 WS 全部命中后端路由（子代理逐条比对）。

**3 处契约偏差（用户可见）**：

| # | 位置 | 偏差 | 影响 | 严重度 |
|---|---|---|---|---|
| **B3** | `portfolio.py:266-275` get_design 转换层白名单仅 `symbol/name/layer/target_weight/selection_rationale` | **丢弃 `daily_change_pct`**（strategies 有 -0.65、plans 无） | 设计详情/历史方案「今日涨跌」列恒显示「数据源不可用」（`DesignResult.vue:89`） | **P0** |
| **B4** | `market_refresh.py:23` 广播 `{type:realtime,data}`；`stores/market.js:59-75` 只处理顶层 `msg.symbol` | **行情 WS 推送前端不消费** | 前端不消费 WS 推送 → 行情更新受 `_PORTFOLIO_REALTIME_TTL=15` 应用缓存节流（`market_service.py:997-999` 为 TTL 常量非轮询），WS 通道空转 | **P1** |
| B1 | `UnifiedAnalysis.vue:458` 传 `market`；`analysis.py:176-181` SymbolAnalysisRequest 无该字段 | Pydantic 忽略 extra，HK/US 上下文丢失（靠 asset_type 分流兜底） | 影响有限 | P2 |
| B2 | `DashboardAiTools.vue:414` 读 `taskData.design_id`；design-async 响应无此字段 | 靠 WS/轮询兜底 | 极端时序可空 | P2 |
| B6 | `WatchlistPanel.vue:129` `null>=0`（外层 `v-if="item.realtime"` 已拦截 realtime 缺失） | realtime 存在但 `change_pct=null` 时误判红涨 | 配色语义错误 | P2 |

### 3.10 任务列表双显示缺陷（2026-08-11 补充诊断，复现实证）

**现象**：点一次「组合设计」+ 一次「策略检查」，打开「任务列表」（DesignHistory 面板）看到**两个「智能组合设计」任务，且策略检查任务不可见**。

**复现实证**（后端运行中实测，`scripts_diag/` 探针）：
- `POST /portfolio/design-async` → task 387（design）；`POST /portfolio/strategy-check-async` → task 388（check）；`/tasks` 返回 `type: design/check` 区分正确——**后端任务创建与查询链路无问题**；
- `GET /portfolio/timeline` 在 387/388 处于 running/pending 时**两者均不可见**；387 完成后才以 design_items（record 508）出现。

**根因（三处叠加，`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `backend/app/routers/portfolio.py:505-506` `get_timeline` 的 `task_items` 查询 `where(TaskRecord.task_type == "design")` | **check 类型任务的 running/pending/failed 状态永不进 timeline**——check 仅在完成落库 `strategy_check_records` 表后才出现（`check_items`，529-539 行）。用户点策略检查后、完成前，历史列表里该任务"消失" |
| R2 | `frontend/src/views/DashboardAiTools.vue:597-598` `loadHistoryList` 的 `runningTasks` 过滤 `t.type === 'design'` | **check 的 running 任务同样不合成**——前端也不显示运行中的策略检查 |
| R3 | R1 + `DashboardAiTools.vue:599-603` runningTasks 合成条（`id:null, _type:'design'`）与 timeline `task_items` 中同一条 running design 任务**重复显示** | **同一次设计操作出现 2 条「智能组合设计」**（1 条来自 timeline task_items、1 条来自前端 runningTasks 合成） |

**用户感知**：设计任务 running 期间 → timeline 1 条（task_items）+ 前端合成 1 条 = 2 条「智能组合设计」；策略检查 running 期间 → 0 条「策略检查」。与截图现象（22:35 = 14:35 UTC 的 385 design + 386 check）完全吻合。

### 3.11 策略检查「新加标的 + 操作/仓位矛盾」（2026-08-11 补充诊断，复现实证）

**现象**：策略检查报告中出现 `510300 ETF`（默认名，非用户自建名称）且建议 `increase` 但仓位 50% → 30%（**增仓却降仓，明显矛盾**）。

**复现实证**（`scripts_diag/analyze_check389.py`，task 389）：
- `510300 | action=increase | cur=0.5 sug=0.3 | conf=0.7 | src=rule`——矛盾实锤；
- 对比 task 384（round16 诊断时）：`510300 | increase | 0.2 → 0.24` 正常——**权重 0.2→0.5、名称变默认名的数据变化来自 apply-design 测试路径**（见下 R2）。

**根因（两处叠加，`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `backend/app/services/portfolio_service.py:1260` `_rule_based_suggestion` increase 分支 `suggested = min(cur * 1.2, 0.30)` | **30% 单只风控上限截断污染 action 语义**：当 `cur > 0.25`（如 0.5）时 `cur*1.2 > 0.30` → `min` 取 0.30 **低于 cur** → 输出 "increase 但 suggested < current" 的自相矛盾建议。`decrease` 分支（1268 行 `max(cur*0.7, 0.0)`）同理：cur 很小时 suggested 可能 ≥ cur |
| R2 | `backend/app/services/portfolio_service.py:1601-1602` `apply_portfolio_design` added 分支 `name=f"{symbol} ETF"` + `update_etf` 只改权重不改名称 | **apply-design 产生「幽灵标的」**：目标不在现有持仓时静默插入 `name="510300 ETF"` 默认名记录（id=21）→ 用户看到"莫名奇妙新加的标的"且名称非自建。round16 诊断时 apply-design 测试（`{symbols:['510300','518880']}`）触发此路径 |
| R3 | `backend/tests/test_z26_strategy_check_coverage.py` 仅断言 `action ∈ {increase,decrease,hold}` + 字段存在（80-82 行） | **测试盲区**：无「action 方向 vs suggested_weight」一致性断言——矛盾建议全绿通过（round16 §5 盲区① 的又一实例） |

**用户感知链**：apply-design 测试插入 510300（默认名）→ 用户对新增标的不明 → 该标的因子分高（3.24）+ buy 信号 → 规则引擎 increase 分支 → `min(0.5*1.2, 0.30)=0.30` → "建议增仓至 30%"（实际低于当前 50%）→ 操作与仓位矛盾。

### 3.12 本地后端假死（事件循环被同步 HTTP 阻塞，2026-08-11 补充诊断，py-spy 实证）

**现象**：本地 `uvicorn --host ::`（round8 O21 双栈模式）跑着跑着所有请求超时（`/system/warmup`、`/admin/thread-pool` 均 15s 超时），进程存活（17260，128 线程、379MB）、8000 端口 LISTENING，但**事件循环假死**——表现为"后端崩溃"。

**py-spy 实证**（`py-spy dump --pid 17260`）：
- **MainThread（事件循环）卡在**：`_realtime_one`(market.py:664) → `get_asset_realtime`(market_service.py:1178) → `_route_us`(market_service.py:1261) → `_td`(1253) → `fetch_realtime_twelvedata`(global_markets_fetcher.py:542) → `run_in_thread`(async_utils.py:67 `future.result(timeout=8)`)；
- **ThreadPoolExecutor-1 多个 worker 卡在** `requests.get`（akshare `fund_etf_fund_info_em` 基金净值等同步源，与预热 `fetch_fund_nav` 同源慢）。

**根因（R1 主因 + R2 加剧，`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `market_service.py:1236-1265` `_route_us` 标 `async def` 但内部 `_td()/_fh()/_tf()` 是**同步闭包**直接调用同步 fetcher，且 `source_registry.py:240` `registry.route` 用 `result = fn()` **同步执行 provider** | **async 陷阱**（AGENTS.md「async def ≠ 非阻塞」gotcha 直接违反）：US 实时行情请求在事件循环主线程上同步执行 `fetch_realtime_twelvedata` → 内部 `run_in_thread` 的 `future.result(8s)` **同步阻塞事件循环**。`_route_us` 虽有 `async def` 签名但 `await` 链断裂（未 `await run_sync(...)`） |
| R2 | 慢源并发叠加 | TwelveData/Finnhub 同步 HTTP（8s 超时）+ akshare 基金净值（线程池 worker 占满）→ 53 个 ESTABLISHED 连接堆积、ThreadPoolExecutor 打满 → 事件循环短暂恢复也无法处理新请求（worker 全忙） |

**为何测试防护未识别**（对应 §5 盲区①③）：单测 mock 掉真实 fetcher（`_td/_fh/_tf` 不触网）→ 同步阻塞路径不被覆盖；性能门禁（verify_perf 未接线）无「事件循环响应性」断言；本地 `--host ::` 双栈 + 慢源只在真实网络环境复现。

**为何"修过又复现"（历史追溯）**：

| 历史修复 | 内容 | 与本次关系 |
|---|---|---|
| `e493581`（2026-07-26）「fix: resolve thread pool exhaustion and page loading latency」 | mootdx 全局锁序列化 → 线程池 64 worker 打满 → 所有 API 超时（**backend hung 症状与本次相同**） | **修复的是线程池/锁层**；本次 `_route_us` 同步阻塞事件循环主线程是**不同根因**，未被该修复覆盖 |
| `2be9ccb`/`e2cd9da`（2026-07-24/26）「event-loop blocking fix / async boundary fix」 | factor_registry `_fetch_market_data` 同步 fetch_history 阻塞 → `asyncio.to_thread` + Semaphore(8)；新增 `audit_async_blocking.py` AST 审计 | 只覆盖 factor_registry 等直接调用；**`_route_us` 的「async def 内嵌套同步闭包 + registry.route 参数传递」模式未被 AST 审计捕获** |
| `ebaec4f`（2026-08-09）「round11 P1 dedupe」 | `_safe`/`_cached`/IOPV sync-fetch 收敛 | 未触及 `_route_us` |

**审计盲区机制**（`audit_async_blocking.py`）：`:123-127` `_is_inside_nested_def` 跳过「async def 内嵌套同步 def」的调用；`:144` `continue` 直接跳过嵌套节点——`_route_us` 的 `_td()` 是嵌套同步闭包，其内部 `run_in_thread`（黑名单项 `:38`）**被跳过**；外层 `_route_us` 只含 `_td()` 的**定义与引用**（`registry.route([...])` 参数传递），AST 静态扫描不跨闭包追踪 → **`python backend/scripts/audit_async_blocking.py` 实测 85 文件 0 违规**。同类「async def 内闭包同步调用」模式（`_fh`/`_tf` 同理）全部漏网。

### 3.13 因子「数据缺失」双视图数量不一致 + sample_count 语义错配（2026-08-11 补充诊断）

**现象**（截图）：因子页「IC 排序」表显示 6 个「无数据」，而「因子分类」卡片统计 27 个「无数据」——**两边缺失数量不一致**。

**复现实证**（`scripts_diag/factor_gap_analysis.py` + `factor_frontend_sim.py`）：
- `/factors/active` 全 38 因子：`ic_value is None` = **17**（含 static 11 个 + 真缺失 6 个）；`status == 'no_data'` = **27**；前端排序表（排除 static 后 27 行）「无数据」= **6**（ic null）、「有效」= **21**（有 IC 值且 |IC|≥0.02）；
- DB `factor_ic_records` **87278 条**历史 IC 记录（累积充分），最新批次 21 因子 IC 值 0.0273~0.6818 均**有效计算成功**，但 `sample_count` **全为 0**；
- 容器内 `ic_tracker._records` len=0、`registry._sample_counts` 空、`_last_ic_batch` 靠启动 `restore_ic_from_db` 恢复 22 条。

**根因（三处叠加，`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `factors.py:305`（分类 `no_data_count = sum(status=="no_data")`）vs `FactorModelView.vue:115`（排序表 badge `ic_value === null`） | **两个视图"无数据"判定口径不同**：分类按后端 `status`（含 P0-C 样本保护误判），排序表按 `ic_value` 是否 null——21 个「有 IC 值但 status=no_data」的因子在排序表显示"有效"、在分类算"无数据" → 6 vs 27 不一致 |
| R2 | `factor_registry.py:1725-1731` `_sample_counts` 统计「本批次**非零符号数**」（≈11 只 ETF）；`factors.py:27` `MIN_IC_SAMPLES=30` 期望「**IC 累积周期数** ≥30」 | **sample_count 语义错配**：统计的是单批非零符号数（恒 <30），不是 IC 历史累积周期数 → P0-C（factors.py:119）永远判 no_data，即使 IC 已累积 87278 条 |
| R3 | `ic_tracker.py:254-263` `_get_ic_sample_count` 读 `self._records`；`record()`（120 行）仅 `compute` 内调用（factor_registry.py:1698-1702）；候选池空时 periodic compute 不执行（main.py:451 `if _syms and _kline`）→ `_records` 恒空 → DB `sample_count` 恒 0 → 启动恢复（factor_registry.py:1794 `if v>0`）过滤掉 0 → **sample_count 死循环为 0** |

**「数据缺失」真相**：21 个因子 IC **实际有效**（0.0273~0.6818，DB 87278 条历史佐证），**不是数据缺失**——是 `sample_count` 计数 bug（R2+R3）导致 P0-C 误标 no_data + 双视图口径不一致（R1）共同造成的**显示层误判**。6 个真缺失（ic_value=null 且非 static：`tracking_error`/`shares_change`/`industry_diversification`/`institutional_holdings_change`/`ln_mcap`/`sentiment.news_direction` 等）需查 `_data_source_gaps` 单独处理。

**测试盲区**（对应 §5 盲区①）：`test_round14_apply_design_factors.py` 仅断言 IC 样本<30 时 `no_data`（P0-C 正确性），**无「sample_count 语义」断言**——未发现 `_sample_counts` 统计的是符号数而非周期数；前端 `FactorModelView.spec.js` 无「排序表 vs 分类 no_data 数量一致」断言。

### 3.14 候选池「修复有效性 + 卫星层数量萎缩」评估（2026-08-11 补充诊断）

**用户疑问**：候选池修复了吗？入选标的和修复前差不多但数量萎缩（尤其卫星层），是否合理？

**实证**（容器 + 宿主机对比）：
- **快照机制有效**：`fetch_all_etfs_base()` 宿主机/容器均 **0.0s 返回 1624 只**（快照 `etf_list_cache.json` 命中，真实数据）；
- **分层链路有效**：`full_pipeline()` 容器内 **0.01s** 产出 core 33 / satellite 30 / defense 7（70 只）——快照→过滤→分类→分层全正常；
- **候选池不稳定**：设计 391 触发 refresh 后 `admin/metrics` pool=25（healthy），但**冷却期后 `get_pool()` 又空**（0）——候选池"昙花一现"，依赖数据源冷却状态（mootdx/akshare/dongfang 冷却时 refresh 产出受限）；
- **设计 391**（pool 25）：卫星层 2-4 只（防御 2 / 平衡 4 / 进攻 2）；**设计 506**（round16，pool 26）：卫星 2-3 只——**两轮入选标的"差不多"**（562990/562600/589720/562950 反复出现）。

**结论**：
1. **候选池修复有效**（快照 1624 + 分层 70 只 + 双源路由均正常）——**不是"没修复"**；
2. **25 vs 70 的差异** = `MAX_PER_LAYER` 截断（core 8/satellite 20/defense 10，`market_data_hub.py:142-148`）+ `_balance_by_industry` 行业均衡收敛（`_refresh_impl` 从 flat 1618 重新分层后截断）——**设计上限内的正常收敛**；
3. **卫星层入选 2-4 只** = **层预算约束的正常结果**（`budgets.py:23/39/55` satellite 预算 20-22%，50 万资金卫星约 10-11 万，每只 2-5% 权重 → 只能选 2-4 只），**非 bug**；
4. **入选标的"差不多"** = 卫星层按 composite_score 排序取头部（562990/562600/589720 等高分标的稳定靠前）——**合理收敛**，但暴露**候选多样性不足**：头部标的高度重合（同一批 ETF 反复入选），卫星层 30 只候选实际只有 ~6 只在方案中出现。

**待改进点（非阻塞）**：卫星层候选多样性（头部集中）、候选池稳定性（数据源冷却期应保留 last-good pool 而非清空——`market_data_hub.py:678-688` 已有 last-good 保护但仅对「refresh 产空」生效，冷却期 refresh 受限产出 25 只时直接覆盖）。

### 3.15 Dashboard「跟踪指数」列：场内空 / 场外=场内 ETF 代码（2026-08-11 补充诊断）

**现象**（截图 + DB 实证）：Dashboard 持仓表「跟踪指数」列——**场内 11 只全部为空**（`tracked_index=None`），**场外 10 只显示场内 ETF 代码**（022449→159338、012762→510880…）。

**DB 实证**（`scripts_diag/dump_tracked_index.py`）：
- 场外 10 只 `tracked_index` = 对应场内 ETF 代码（如 `022449 华泰中证A500ETF联接C → 159338`）；
- 场内 11 只 `tracked_index` **全 None**（510300/159338/518880 等）。

**结论：场外合理、场内不合理**：

| 项 | 是否合理 | 依据 |
|---|---|---|
| 场外 tracked_index = 场内 ETF 代码 | ✅ **合理（设计行为）** | `portfolio_service.py:380-383`：场外联接基金无实时净值，用对应场内 ETF 涨跌幅**估算当日盈亏**（`estimate_source: "tracked_index"`）；`taTarget.js:5` + `AnalysisView.vue:126-137`：技术分析查对应 ETF K 线——两处均有注释说明 |
| 场内 tracked_index 空 | ❌ **不合理** | 场内 ETF 本应填**真实指数**（510300→沪深300 000300、159338→中证A500）。候选池已含 tracked_index（`etf_scanner.py:377` f168 东财字段 + `market_data_hub.py:514/517-523` F10 enrich），但 **`portfolio_etfs` 持仓表从未被 enrich**——`enrich_tracked_indices`（etf_scanner.py:757-796，从东财基金页抓「跟踪标的」）只在候选池 `_refresh_impl` 调用，持仓表添加时 `add_etf`（portfolio_service.py:128-141）用请求参数（前端不传 → None） |

**连带语义不一致**：若补全场内 tracked_index=真实指数名，PnLDetailTable 的「跟踪指数」列将**混显两种语义**——场内=指数名、场外=ETF 代码。需统一展示口径（场外显示"联接：159338"或"对应场内 159338"）。

**方案裁决（用户建议"场内场外都放具体指数"）**：**合理，采纳**。但**不能直接改数据层**——场外 `tracked_index`（场内 ETF 代码）是 `build_price_map`（portfolio_service.py:346-351）、盈亏估算（380-383）、taTarget 技术分析（AnalysisView.vue:126-137）的**功能依赖 key**，改成指数名会破坏 3 处。正确做法：**数据层保持双语义，展示层统一反查**——场内显示真实指数名（回填后）、场外经 `tracked_index`（场内代码）反查该 ETF 的真实指数名显示（`probe_tidx_map.py` 实证 159338→中证A500、518880→黄金 可反查，WIDE_BASIS_STATIC 10 只 + f168 缓存 53 条作数据源）。详见 §7 P0-14。

**测试盲区**：`AnalysisView.spec.js:35` mock 场内 `tracked_index: null` 固化现状；无「持仓表 tracked_index 完整性」断言（场内 ETF 应非空）。

### 3.16 持仓技术分析：K 线红跌绿涨 + 周期标注不可见 + 无涨跌幅（2026-08-11 补充诊断）

**现象**（截图：159516 半导体设备ETF 技术分析页）：① K 线**涨绿跌红**（与项目「红涨绿跌」约定相反）；② 周期标注几乎不可见；③ 无涨跌幅展示。

**根因（三处，`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `AnalysisView.vue:277` + `TechnicalAnalysisModal.vue:141` candlestick `itemStyle: { color: CANDLE_DOWN, color0: CANDLE_UP }`；成交量 `volumeColors`（AnalysisView.vue:254、TechnicalAnalysisModal.vue:136）涨日用 CANDLE_DOWN | **K 线颜色写反**：`chartColors.js:43-44` 定义 `CANDLE_UP=红/涨`、`CANDLE_DOWN=绿/跌`（注释"red for up / green for down"意图正确），但 ECharts candlestick 的 **`color`=阳线（涨）**、**`color0`=阴线（跌）**——代码把 `color` 赋了 `CANDLE_DOWN`（绿）、`color0` 赋了 `CANDLE_UP`（红）→ **涨绿跌红**，与约定相反；成交量同理 |
| R2 | `AnalysisView.vue:416` 周期标注 `title.text = ${seriesName} · K线 ${periodLabel}`，`textStyle: { fontSize: 12, color: '#888' }` | **周期标注存在但可见性差**：12px 浅灰（#888）在浅色背景上几乎不可见（O26 已从纯周期增强为"标点名+周期"，但字号/对比度仍不足）——用户误以为"无周期显示" |
| R3 | `AnalysisView.vue:421-434` K 线 tooltip 仅显示 OHLC（开/收/高/低），无涨跌幅；页面无独立「今日涨跌」区块（对比 TechnicalAnalysisModal.vue:29-35 有 `v-if="priceInfo"` 的「今日涨跌」行） | **持仓技术分析页（AnalysisView）无涨跌幅展示**——涨跌幅只在 tooltip 悬停（203 行 tooltip formatter 有，但 421-434 实际渲染无），且无固定区块 |

**测试盲区**（对应 §5 盲区①）：`AnalysisView.spec.js` 无「K 线颜色=红涨绿跌」断言（CSS/视觉零覆盖）——属①型；无「周期标注可见/存在」断言；无「涨跌幅区块存在」断言——三类问题全绿通过。

### 3.17 自选列表增加「技术分析 / AI 分析」按钮（2026-08-12 补充诊断，功能增强建议）

**用户建议**：自选列表是否也支持技术分析和 AI 分析按钮？

**可行性结论：完全可以，现成模式复用（低风险增强）**：

| 现状 | 位置 |
|---|---|
| 自选列表行内仅「✏️ 编辑备注 / 🗑️ 移除」 | `WatchlistPanel.vue:140-142` |
| 自选点击 → `selectItem` → emit `select-symbol` → MarketAnalysis 滚动到 UnifiedAnalysis（symbol 模式 AI 分析） | `WatchlistPanel.vue:234-236`、`MarketAnalysis.vue:98-101` |
| **板块热点已有完整双按钮模式**：「📈 技术」（`openTechnical` → TechnicalAnalysisModal，含 assetType 按市场推断）+「🤖 AI 分析」（`emitAnalyze` → UnifiedAnalysis externalTrigger）；TechnicalAnalysisModal 还有 `@ai` 事件从技术分析直接切 AI 分析 | `SectorHeatMap.vue:112-113/121-128/190-200` |

**复用路径**：WatchlistPanel 行内加「📈 技术 + 🤖 AI 分析」按钮 → 技术分析复用 `TechnicalAnalysisModal`（assetType 按 item.market/asset_type 推断——自选 A/HK/US 混合正好需要，参照 SectorHeatMap `openTechnical` 190-200 行）；AI 分析复用 MarketAnalysis `externalTrigger` 机制（emit `analyze` 事件，参照 SectorHeatMap `emitAnalyze` 182-188 行）。**零新后端接口**（`/market/chart`/`indicators`/`signal` + `/analysis/symbol-analysis/stream` 均已存在）。

**测试盲区**：`WatchlistPanel.spec.js` 无行内分析按钮断言；`SectorHeatMap.spec.js` 已有技术弹窗用例可作复用参照。

### 3.18 港股自选：搜索补全慢 + 添加后列表加载慢（2026-08-12 补充诊断，实测复现）

**现象**（截图 + 实测）：港股自选对话框自动补全慢（好几秒）；添加后列表"要很多时间才有反应并显示数据"。

**实测数据**（`scripts_diag/probe_hk_speed.py` + `probe_hk_add.py`）：
- **搜索**：`09988` 4.09s、`00700` 1.47s（**慢**）；`腾讯`/`阿里巴巴` 0.009-0.039s（**快**，静态基座命中 + akshare 已熔断短路）；A 股 `510300` 5.38s（同样慢但用户未感知）；
- **添加**：POST add `09988.HK` **0.122s**（快，非瓶颈）；
- **列表加载**：GET watchlist（19 只）**19.2s**（**主瓶颈**——添加后前端等待的就是这个）。

**根因（两处，`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `market_service.py:744-756` `search_hk_us` 的 spot 拉取 `asyncio.gather(fetch_hk_spot_list, fetch_us_spot_list)` **无条件执行**（各 4s 超时），无论静态基座（737-742）是否已命中；`09988/00700` 均在 HKUS_STOCK_MAP（618-619 行）但搜索仍等 spot | **搜索补全慢**：首次搜索（akshare 未熔断）时 spot 拉取 4s 超时等待，即使代码/名称已在静态基座命中。`腾讯` 快仅因 akshare 已熔断短路 |
| R2 | `market.py:693-699` `_watchlist_enrich_items` 三市场批量**串行**（A→HK→US，各 `_batch_for` 4s 超时）+ 慢源冷却时必超时 + HK 未命中 per-item 8s | **列表加载慢（19.2s）**：19 只自选含 A+HK+US → A 批量 4s + HK 批量 4s + US 批量 4s + 未命中 per-item 叠加。round16 诊断时 watchlist 冷态 7.75s，本轮 19.2s（自选扩容 + 多市场叠加更明显） |

**测试盲区**（对应 §5 盲区③性能门禁）：verify_perf 未接线，watchlist 加载 19.2s 无任何门禁拦截；搜索耗时无阈值断言。

### 3.19 A股板块热度涨跌幅大量 0 + 技术分析按钮失效（2026-08-12 补充诊断，实测复现）

**现象**（截图 + 实测）：板块热度排行 20 个板块约 15 个涨跌幅 **+0.00%**（仅 CRO/CMO +1.99、MRDL +1.78、MLCC +2.0 等 5 个非零）；「领涨股」列空。

**实测数据**（`scripts_diag/probe_plate_chg.py` + `probe_em_backfill.py` + `probe_cls_join.py`）：
- `sectors/heat?limit=20`：items=20、nonzero=**5**（与截图一致）；
- 财联社 `plate_list`（`fetch_cls_plate_changes` 依赖源）：**errno=50101（sign 失效）** → 返回空 → plate_code join 回填路径废；
- 东财名称回填（`_match_em_change` 三级匹配）：**5/20 命中**（CRO/CMO、MLCC 等东财板块体系无对应板块名）；
- `push2.eastmoney.com` 主源 RemoteDisconnected → 走 push2delay（100+100 行）。

**根因链（老问题未修好，`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `sector_fetcher.py:469-517` `fetch_cls_plate_changes` 依赖财联社静态 sign（`_CLS_SIGN` 464 行）；**sign 已失效 errno=50101**（463-465 行注释明确预警"sign 失效时回退东财名称回填（现状）"） | **round14 P2-AE 的「plate_code join 20/20」只在 sign 有效时成立**；sign 失效后降级到东财名称回填，命中率暴跌至 5/20 → 15/20 板块涨跌幅 0。**已知降级路径从未被监控/修复** |
| R2 | `market.py:587-588` `_match_em_change` 名称三级匹配（608-625 行）；财联社板块名（CRO/CMO、MLCC、民爆）与东财板块体系（印制电路板、CRO、民爆用品）**不同名** | **东财名称回填结构性低命中**：5/20，无法根治 |
| R3 | `sector_fetcher.py:417-422` `fetch_sector_heat` 用财联社 `lv.get_sector_heat()`——**无涨跌幅字段**（428 行注释"财联社板块热度无涨跌幅字段 → 热度行涨跌幅恒 0（O19）"）；而 **`_ak_industry_sectors`（59-89 行，akshare 东财行业板块）自带完整字段**：change_pct/lead_stock_name/code/chg/up/down_count/amount | **源选型缺陷**：热度排行选了无涨跌幅的财联社源，而非自带完整数据的东财 akshare 源 |
| R4 | `SectorHeatMap.vue:112/190-200` 板块条目「📈 技术」按钮 `openTechnical(item)` → `symbol: item.symbol \|\| item.code`——但 sectors/heat 条目**无 symbol/code 字段**（仅 rank/name/heat_index/rank_change/is_new/plate_code/change_pct，实证） | **板块技术分析按钮坏**：`techModal.symbol=undefined` → `/market/chart/undefined` 404；「领涨股」列同样因后端无 lead_stocks 字段而空 |

**测试盲区**（对应 §5 盲区①）：`sectors_heat` 无「涨跌幅非零率 ≥ 阈值」断言（sign 失效后 5/20 全绿通过）——属①型（内容正确性只验非空）；`SectorHeatMap.spec.js` 无「技术按钮 symbol 非空」断言（undefined symbol 用例缺失）。

### 3.20 港股热门股票技术分析无数据：HK K 线降级链 8s 超时截断在腾讯 fallback 前（2026-08-12 补充诊断，实测复现）

**现象**（截图 + 实测）：港股热门股票（stock-hot-rank market=HK，如 09988 阿里巴巴-W）点「技术分析」→ TechnicalAnalysisModal 指标全空（RSI/MACD/KDJ/MA/BOLL 全"—"，data_available=false）。

**实测数据**（`scripts_diag/probe_hk_ta.py` + `probe_hk_ta2.py` + `probe_hk_ta3.py` + `probe_tx_hk.py`）：
- 港股热门股票条目字段完整：`symbol`（09988/00700）+ `market: HK`（前端 assetType 推断正确）；
- `chart/09988?asset_type=HK` **恒 8.6-8.8s 返回 closes=0**（多次复现）；`chart/00700` 1.9s 320 根成功（**同一源不同结果**）；
- 腾讯港股 K 线源（`web.ifzq.gtimg.cn`）宿主机直测 **0.3s / 320 根**，三代码（09988/00700/02513）全部正常——**数据源本身没问题**；
- 后端日志铁证（16:20:54-56）：`get_history fetch_history empty for 09988 (HK), trying get_k_data` → chart 空 → **16:20:56 `tencent hk kline fallback hit (320 rows)`**（下一轮请求才成功）。

**根因（`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `market_service.py:32` `_call` 默认 **timeout=8**；`get_history`（1321 行）`_call(fetch_history, ...)` 用默认 8s；而 `_fetch_akshare_history`（`china_market.py:1584-1626`）内部降级链 **akshare(8s) → finnhub → alphavantage → 腾讯** **串行** | **HK K 线"时好时坏"**：akshare 未冷却时链长（akshare 8s 超时 + finnhub + alphavantage ≈ >8s），`_call` 在**腾讯 fallback（1620-1626）执行前**超时截断 → 返回 None → chart 空；akshare 冷却短路后链短 → 腾讯可达 → 成功。用户点技术分析大概率撞上未冷却态 → 无数据 |
| R2 | `get_history` 1344-1351：`fetch_history` 超时后走 `get_k_data`（akshare 直查）**也依赖 akshare**——akshare 熔断时同样空 | 兜底链与主链同源，超时截断后无独立兜底 |
| R3 | 腾讯 fallback 位置在 `_fetch_akshare_history` 内部最末（1620-1626），被 akshare/finnhub/alphavantage 串行耗时拖累 | 腾讯源（容器内唯一可用 HK K 线链）**未前置**，成为"最后才轮到的兜底" |

**测试盲区**（对应 §5 盲区①③）：`test_hk_kline_fix.py:51` 只测腾讯 fallback **被调用**（mock 返回 None），未测「akshare 慢时腾讯仍可达」（8s 超时截断场景 0 覆盖）；`verify_perf` 无「HK chart ≤3s」阈值（8.8s 空响应无拦截）。

### 3.21 港股指数自动补全不全："恒生港股通" 0 命中（2026-08-12 补充诊断，实测复现）

**现象**（截图 + 实测）：港股标的分析页指数搜索框输入"恒生港股通"补全 **0 命中**；"港股通"仅 1 个（CES100 中证港股通精选100）。用户预期"恒生港股通"系列应有多个指数。

**实测数据**（`scripts_diag/probe_hk_index.py` + `probe_index_db.py`）：
- `search?keyword=恒生港股通&kind=index&market=HK`：**0 hits**；
- `恒生`：7 个（HSI/HSCEI/HSTECH/HSCCI/HSMBI/HSMOGI/HSMPI——恒生系列但不含"恒生港股通"）；
- `港股通`：**1 个**（CES100）；
- indices_meta 表：**HK 38 条 / 总 588 条**，含"港股通/沪港通/深港通"仅 **1 条**。

**根因（`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | indices_meta 表 **无任何写入/同步逻辑**（全仓 grep：仅 search.py 定义模型 + market.py:233-258 读取；`get_indices_meta`/`search_indices` 均只读，market_service.py:885-942） | **表数据是一次性历史导入的静态快照**，无增量更新机制——"恒生港股通"系列（真实世界存在多个：恒生港股通中国内地银行、恒生港股通高股息率、恒生港股通央企等，中证指数官网/东财指数列表均有）**从未进表** → 搜索恒缺 |
| R2 | `_search_indices`（market.py:227-261）只查 indices_meta 表，**无动态补源**（对比个股搜索有 instruments→levistock→spot 多级降级，指数搜索无任何降级链） | 表缺数据 → 搜索恒缺；指数数据源（东财指数列表/中证指数官网）从未接入 |

**测试盲区**（对应 §5 盲区①）：`test_search_indices` 无「'恒生港股通' 类关键词命中 ≥N」断言（表数据不全全绿通过）——属①型（内容正确性只验非空）；无「HK 指数表 ≥ 阈值条数」断言。

### 3.22 美股添加自选自动补全慢（2026-08-12 补充诊断，实测复现）

**现象**（截图 + 实测）：美股自选对话框搜索"QQQ"（Invesco QQQ Trust）补全 **7.4s** 才有反应。

**实测数据**（`scripts_diag/probe_us_search.py`）：
- `QQQ` include_stocks=true：**7.4s** / include_stocks=false：**0.022s**（差异 = spot 拉取 + ETF enrich）；
- `AAPL`（US stock）：0.028s（快——spot 已冷却短路 + stock 不 enrich）；`SPY`：0.9s；
- A 股 `510300`：5.9s（同样慢，P0-16 同源）。

**根因链（与问题 8 港股同源 + 美股 ETF 特有叠加，`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `market_service.py:744-756` spot 拉取无条件执行（HK+US 各 4s 并发）——**P0-16 已记录** | 首次搜索（akshare 未冷却）等 spot 4s |
| R2 | `market_service.py:849-864` `_enrich` 对 `type=="etf"` 命中调 `get_asset_realtime(US)`（8s wait_for）；`get_asset_realtime` → `_route_us`（1236-1265）→ `registry.route` **同步执行** `_td` 闭包 → `run_in_thread` 阻塞事件循环（8s/源）——**P0-11 关联** | **搜美股 ETF（QQQ/SPY）时事件循环被同步阻塞数秒**：spot 4s + enrich 阻塞叠加 → 7.4s；QQQ 是 ETF 所以比 AAPL（stock 不 enrich）慢 |

**测试盲区**（对应 §5 盲区③）：`test_search_hk_us` 无「ETF 命中 enrich 不得阻塞事件循环」断言（`_route_us` 同步阻塞场景 0 覆盖）；verify_perf 无「US 搜索 ≤1s」阈值。

### 3.23 市场 tab 切换后标的分析输入框未清空（2026-08-12 补充诊断，前端交互 bug）

**现象**（截图 + 实测）：市场 tab 从港股切换到美股，标的分析（UnifiedAnalysis）输入框**残留港股内容**。

**根因（`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `UnifiedAnalysis.vue:166-177` marketTab watch 清空逻辑**只清 `search`（symbol 实例）**：`if (search.searchQuery) search.searchQuery.value = ''`（174 行）+ `search.searchResults/showDropdown`（175-176 行）；**`sectorSearch`/`indexSearch` 实例的 searchQuery 完全没清**（全文件仅 `activeSearch` computed 131-133 行引用它们，无任何清空点） | **指数/板块模式输入残留**：用户停留在指数模式输入"恒生港股通"（indexSearch.searchQuery 有值）→ 切 tab 到美股 → 输入框 v-model 绑 `activeSearch.searchQuery`（=indexSearch，132 行）→ 残留港股内容；symbol 模式（search 实例）不受影响——所以"标的分析输入框没清空"集中在指数/板块模式 |

**测试盲区**（对应 §5 盲区①）：`UnifiedAnalysis.spec.js` 无「marketTab 切换后 sector/index 模式输入框清空」断言（只测 symbol 模式或未测切换场景）——属①型（交互行为断言缺失）；三实例清空逻辑 0 覆盖。

### 3.24 美股标的分析输入指数报错：round14 P2-AM 未落地（2026-08-12 补充诊断，实测复现）

**现象**（截图 + 实测）：美股标的分析指数模式输入"SPX"/"标普"→ 搜索 0 命中或混入港股指数，选中后 realtime 失败报错。**round14 P2-AM 已诊断同类问题（"美股 tab 推荐项含 A 股指数 → realtime 失败"）但未落地**。

**实测数据**（`scripts_diag/probe_us_index.py` + `probe_us_index2.py`）：
- `SPX`（kind=index, market=US）：**0 命中**；`道琼斯`/`纳斯达克`/`纳指`：0；`标普`：**2 个港股指数**（GEM/HKL）；
- `GEM`（kind=index, market=US）：0 命中——**`_search_indices` 只搜 name/pinyin/first_letter，不搜 symbol**；
- `realtime/GEM?asset_type=index`：**失败**（港股指数在美股分析上下文报错）。

**根因（`file:line`，对应 round14 P2-AM 三处修复均未做）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `market.py:241-247` `_search_indices` **不搜 `symbol`**（仅 name/pinyin/first_letter ilike） | 输入指数代码（SPX/道琼斯代码）0 命中 |
| R2 | `market.py:249-252` market 过滤**只处理 HK/A**，**market=US 无分支** → 全市场 ilike | 美股 tab 名称搜索混入港股/A 股指数（标普→GEM/HKL） |
| R3 | indices_meta 表**无美股指数**（588 条全 A/HK，见 §3.21 P0-20 同根因） | 即便过滤正确也无 US 指数可返回 |
| R4 | 选中港股指数（GEM）做美股分析 → realtime `asset_type=index` 取数失败 → 前端报错 | 指数 realtime 对跨市场标的无防护 |

**测试盲区**（对应 §5 盲区①）：`test_search_indices` 无「market=US 只返回 US 指数」断言（混入 HK 指数全绿通过）——属①型；无「指数代码（symbol）可搜」断言。

### 3.25 候选池误杀活跃板块 ETF：快照成交额异常（2026-08-12 补充诊断，实测复现）

**现象**：候选池修复后，半导体设备（159516）、游戏（159869）、恒生科技（513010）等**近期强势板块未入选**设计方案卫星层。

**实测数据**（`scripts_diag/probe_satellite_pool.py` + `probe_missing_etf.py` + `probe_gtimg_raw.py`）：
- 5 只强势板块 ETF 快照分类均为 `satellite`，金额/规模正常；但 **`filter_etfs` 全被过滤**（快照 1618 → 过滤后 395）；
- 快照 `amount`（元）：159516=48.9 万、513010=6.2 万、512480=17.6 万、159995=9.8 万、159869=8.6 万——**全部 < `MIN_AVG_AMOUNT=1000 万`（etf_scanner.py:54）** → 被 `filter_etfs`（610 行）过滤；
- **gtimg 原始接口实测真实成交额**：159516=**9.7 亿**（97155 万）、513010=**1.6 亿**、512480=**2.9 亿**——**快照 amount 比真实值低估 ~2000 倍**。

**根因（`file:line`）**：

| # | 位置 | 缺陷 |
|---|---|---|
| R1 | `etf_list_cache.json`（快照，ts 2026-08-04，age≈7.8 天）的 `amount` 数值异常：快照 amount 48.9 万 vs gtimg 实时 97155 万，**差 ~2000 倍**（非 round15 §5.4 已修的 ×10000 单位问题——万元→元仅 1e4 倍，此差 2e3 倍需 ×2e7）；实测为陈旧快照抓取时的异常值（半日/盘中早段成交 vs 全天量、或历史某时点非活跃成交快照）| **快照 amount 低估真实成交额 ~2000 倍** → 全部跌破 `MIN_AVG_AMOUNT=1000 万` → 活跃板块 ETF 被 `filter_etfs`（etf_scanner.py:610）误杀，未进候选池 → 设计方案卫星层缺半导体/游戏/恒生科技；与 round15 §5.4（数据源层 ×10000 已修）是同根因两层：数据源已修、缓存未重建 |
| R2 | 候选池构建依赖**旧快照 amount**（`filter_etfs` 用快照字段），refresh 未用**实时成交额**覆盖 | 快照陈旧时，成交额过滤基于过期/异常数据——活跃板块因"虚拟低流动性"而非真实状态被排除 |

**结论**：**不合理**——半导体/游戏/恒生科技未入选是 `filter_etfs` 基于**异常快照成交额**的误杀，非设计偏好或板块本身流动性不足。活跃板块 ETF 真实成交额上亿（gtimg 实测），应正常入选候选池。

**测试盲区**（对应 §5 盲区①型断言缺失；盲区表无「候选池金额与实时一致」专项，P0-23④ 若落地可回填盲区表）：无「候选池 `filter_etfs` 后在池 ETF 成交额 vs 实时行情一致」断言，且现有 `test_round15_amount_unit.py` 只验 ×10000 单位换算（数据源层）、不验缓存层 amount——异常快照数据导致活跃板块误杀全绿通过。

---

## 四、docs 落地核对（任务 11）

### round14-container-acceptance-diagnosis.md（28 方案）

- **implemented 15**：P0-A/B/C/D、P1-K、P2-U/W/X/Z/AD/AE/AH/AI/AJ/AK；
- **partial 10**：P1-E（资金流缺口仍无标注）、P1-F（信号口径测试未按文档改）、P1-G（CLS 未实测——本轮实测 0.389 超标，**证明该 partial 判断正确**）、P2-I（残留清理未完成）、P2-V（LLM 现金正文未做）、P2-Y（IC 表前端测试缺失）、P2-AF（前端骨架屏未做）、P2-AG（indices_meta 未接入启动链——本轮 US 指数搜索 0 命中佐证）、P2-AM/AN（美股指数/港股 PE 未全落地）；
- **missing 3**：P2-H（冷缓存改善）、**P2-AL（HK/US 板块分析——本轮实测返回友好提示）**、P2-AN 港股分支。

### round15-factor-pool-selection-evaluation.md

- 落地：amount 单位 ×10000、raw 方向化 + CATEGORY_AGG、IC 加权聚合、composite 量纲统一（pct_rank）、9-F1 core 市态绝对防线；
- **未落地**：9-F2（C2 词表仍硬编码 `allocation_engine.py:366-397`）、9-F3（组合风险参数 `max_correlation/max_turnover_rate` 零消费）、9-F4（权重校准脚本无）。

### round15-process-review.md ✅ 全部落地（AGENTS.md + design-checklist.md 8 项）

### round15-test-guard-baseline.md ⚠️ 关键失效项

- 基线 A 降级链三态 partial（fetch_history 仅 1 态）；
- **基线 B news 分级用例失效**（见 §5 盲区②）；
- 基线 C 主用例落地；基线 D 去 mock 未达；**基线 E verify_perf 脚本存在但未接 pre-commit、无运行记录**（本轮 watchlist 冷态 7.75s 超标未被任何门禁发现）。

---

## 五、测试防护盲区分析（任务 14）——为什么这些没被发现

| # | 盲区 | 本轮实证问题 | 根因（file:line） | 修复方向 |
|---|---|---|---|---|
| ① | **内容正确性只验非空** | 「报告生成失败」标 quality=full | `task_manager.py:445-465` 只查 `len(llm_analysis)>0`；`llm.py:1646` `result or "报告生成失败"` | 报告质量判定加「占位符/失败标记」黑名单 + 负向断言（含"报告生成失败"即 partial） |
| ② | **测试探测错误目标必 SKIP** | 基线 B news 分级用例从不生效 | `test_round15_guard_baseline.py:70-74` 探测 `_grade_news`/`grade_news`，真实函数是 `levistock_fetcher.classify_news_level`（返回 int 非二元组） | 修函数名引用 + 断言形态；**门禁补「SKIP 数=0」检查** |
| ③ | **性能门禁无接线** | verify_perf 从未运行 | 脚本存在但 pre-commit 无调用、`data/perf_baseline.jsonl` 不存在 | 接 pre-commit（软门禁：超阈值 warn 不阻断）或至少纳入 CI |
| ④ | **软门禁无实测记录** | round14 P1-G CLS 修复无 Lighthouse 记录 | `.lighthouserc.yml` warn 非 error + CI continue-on-error | 修复时记录实测值；home 页 CLS 实测进验收清单 |
| ⑤ | **契约偏差无 e2e 覆盖** | B3 daily_change_pct 丢弃未被发现 | `verify_e2e.py` 未断言 plans[].allocations 字段完整性 | e2e 加「get_design 返回字段 vs strategies 字段」一致性断言 |
| ⑥ | **依赖表同步无守卫** | instruments US/HK 段 0 条、indices_meta 无美股 | `sync_instruments.py:91-116` 五段同步逻辑存在但美股段 20s 超时黑洞、港股段受东财源冷却 → 表段空置；无「表段非空」守卫测试 | 启动守卫：instruments US/HK >0、indices_meta 含美股；段同步失败显式告警（现 `collect_all` 仅 ERROR 日志，无前端/验收暴露） |
| ⑦ | **冷启动性能无阈值** | watchlist 冷态 7.75s 超标 | 无冷启动性能门禁 | verify_perf 加冷态首拉阈值（或预热覆盖） |
| ⑧ | **LLM 慢路径无分级** | A 股 llm-report 77.8s / 概念 90s 超时 | LLM 排队无分级告警 | 耗时分段记录 + 超阈值 warn 日志 |

**共性根因**：测试防护体系强调「测试绿」但缺乏「内容真实性 + 性能实测 + 契约字段完整性」三层；SKIP 用例不被计数；软门禁（verify_perf/Lighthouse）声明存在但从未实际接线运行——**「存在但未运行」与「不存在」在验收上等价**。

---

## 六、冗余代码清理方案（任务 15，41 项）

**第一批 P0 文件级**：删 `docker-compose.diag.yml`、`scripts_diag/` 整目录（**先按附录把诊断产物归档到 `logs/round16/` 再删**）、`scripts_diag_test_analysis.md`、`start_backend_profiled.py`；`git rm` backend 根一次性脚本（`_*.py` 前缀（诊断时点快照 18-22 个，按前缀模式删除防漏）+ fix/add/apply/verify×5 + mypy_errors.txt）；本地清 `data/_diag_*.py`×23、`data/` 日志产物、`backend/data/` dump。

**第二批 P0 代码级**：删死代码符号（`PortfolioReviewRequest`、`disable_ipv4_only`、`backend_port`/`frontend_dev_port`、`analysisApi` 空对象）；删死端点（market.py `sentiment`/`industry-cls`/`{code}/stocks`/`{plate}/popular`/`signal/debug`/`wind`、portfolio.py `apply-strategy`、analysis.py `news-impact/stream`）；删死元数据（`max_correlation`/`max_turnover_rate`/`c2_adjust`）。

**第三批 P1**：与 verify_e2e 联动的死端点逐条确认（fundamentals/sectors-rotation/realtime-batch/macro/global/strategy-checks-list 等 9 项）；archive 12 脚本团队决策；scheduler 死注释（main.py:283-302）。

**第四批 P2**：data 路径 4 处双轨统一（`core/paths.py`）、SENTIMENT_TTL 收敛、KLINE/私有 TTL 统一。

> 删除任何端点须同步删 `api-contracts/` 契约段并跑 `check_routes.py`；回归目标 `test_route_contract.py` / `verify_e2e.py` / `test_optimization.py`。

---

## 七、优化与修复方案（P0-P2 分级，本份不实施）

> 对照 design-checklist 8 项：每方案标注证据链（file:line）、非兜底要求、真实调用点、复杂度审计。

### P0 级（功能正确性/数据质量，必做）

**P0-1 设计报告「报告生成失败」占位符防漏（反假完成）**
- 证据：`llm.py:1646` + `task_manager.py:445-465`；实证 design 506 报告 `design_506_report.md:66`。
- 修复：`task_manager` 报告判定加内容黑名单（含「报告生成失败」/空段落 → quality=partial + 明确标注）；`llm.py` 返回前校验；补负向测试（mock LLM 返回空 → 断言 quality=partial 非 full）。
- 验收：重跑设计 → 空 LLM 时 quality=partial；verify_e2e 加「design_text 不含『报告生成失败』」断言。

> **design-checklist 8 项对照**（P0-1~P0-8 统一落表，①探针=实证命令已跑、②证据链=file:line+实测、③验证窗口=外部源结论、④非兜底=禁假值、⑤真实调用=前端/路由消费、⑥四态=UI、⑦复杂度=超时/批量/缓存、⑧已知模式=round14 §4 盲区）：
> | 方案 | ①探针 | ②证据 | ③窗口 | ④非兜底 | ⑤调用 | ⑥四态 | ⑦复杂度 | ⑧模式 |
> |---|---|---|---|---|---|---|---|---|
> | P0-1 | ✅design506 | ✅llm:1646+tm:445 | — | ✅黑名单 | ✅verify_e2e | — | ✅串行无IO | ✅① |
> | P0-2 | ✅task384 | ✅check_384:22 | — | ✅降级标记 | ✅前端报告 | — | — | ✅① |
> | P0-3 | ✅task384 | ✅check_384全表 | — | ✅阈值对齐 | ✅worker | — | — | ✅① |
> | P0-4 | ✅design506 | ✅portfolio:266 | — | ✅字段透传 | ✅DesignResult | — | — | ✅⑤ |
> | P0-6 | ✅search实测 | ✅sync_instr:91+ms:634 | ✅交易时段 | ✅name_en兜底 | ✅搜索框 | — | ✅降级链超时 | ✅⑥ |
> | P0-7 | ✅factors实测 | ✅factors/active | — | ✅引导文案 | ✅FactorModelView | ✅四态 | — | ✅④ |
> | P0-8 | ✅task13 | ✅task13_latency | — | — | ✅designs列表 | — | ✅缓存/索引 | — |
> | P0-9 | ✅复现387/388 | ✅portfolio:505+DA:597 | — | ✅类型正确 | ✅DesignHistory | ✅四态 | — | ✅⑤ |
> | P0-10 | ✅复现389 | ✅ps:1260+1601 | — | ✅方向校验 | ✅策略检查 | — | — | ✅① |
> | P0-11 | ✅py-spy实证 | ✅ms:1236+sr:240 | ✅本地复测 | — | ✅US实时 | — | ✅run_sync隔离 | ✅③ |
> | P0-12 | ✅复现21因子 | ✅fr:1725+ic:254+fx:305 | ✅候选池恢复后 | ✅语义修正 | ✅FactorModelView | — | — | ✅① |
> | P0-13 | ✅容器/宿主对比 | ✅mh:678+bd:23 | ✅冷却期复测 | ✅last-good保留 | ✅设计链路 | — | — | ✅③ |
> | P0-14 | ✅DB实证11/10 | ✅ps:128+es:757 | — | ✅指数名回填 | ✅PnLDetailTable | — | — | ✅① |
> | P0-15 | ✅截图+源码 | ✅av:277+cc:43 | — | ✅红涨绿跌 | ✅AnalysisView | ✅四态 | — | ✅④ |
> | P0-16 | ✅实测09988 4s | ✅ms:744-756 | ✅复测<200ms | ✅免spot | ✅搜索框 | — | ✅缓存 | ✅③ |
> | P1-7 | ✅实测19.2s | ✅market:693-699 | ✅复测≤3s | ✅并行+DB-only | ✅watchlist | — | ✅gather并行 | ✅③ |
> | P0-17 | ✅实测5/20+50101 | ✅sf:469-517+59-89 | ✅复测≥15/20 | ✅东财源直取 | ✅SectorHeatMap | — | ✅源切换 | ✅② |
> | P0-18 | ✅实测无symbol | ✅SHM:190-200 | ✅复测领涨K线 | ✅领涨股symbol | ✅技术按钮 | ✅禁用态 | — | ✅④ |
> | P0-19 | ✅实测8.8s空+日志 | ✅ms:32+cm:1620 | ✅复测≤3s×3 | ✅腾讯前置 | ✅TA弹窗 | — | ✅超时放宽 | ✅③ |
> | P0-20 | ✅实测0命中+38条 | ✅ms:885-942只读 | ✅复测≥3命中 | ✅表数据补全 | ✅指数搜索 | — | ✅同步幂等 | ✅② |
> | P0-21 | ✅实测QQQ 7.4s | ✅ms:1236-1265 | ✅复测≤1s | ✅静态基座+spot价 | ✅搜索框 | — | ✅enrich异步 | ✅③ |
> | P0-22 | ✅实测SPX 0命中 | ✅market:241-252 | ✅复测≥3命中 | ✅US指数数据 | ✅指数分析 | ✅友好错误 | — | ✅② |
> | P0-23 | ✅实测低估~2000x | ✅es:54+610+gtimg | ✅复测含强势板块 | ✅实时金额覆盖 | ✅候选池 | — | ✅异常护栏 | ✅⑥ |

**P0-2 策略检查 510300 名称回退「510300 ETF」**
- 证据：task 384 report（`check_384_report.md:22`）。
- 修复：名称回退前先查 `instruments`/`etf_list_cache`；回退文案改为「未识别标的(510300)」并打 degrade 标记。
- 验收：重跑策略检查 → 名称正确或显式降级标记。

**P0-3 规则引擎因子分阈值与文案口径统一**
- 证据：`check_384_report.md`（159338 1.00→increase、518880 6.32→hold、-0.72 弱 vs -0.43 中性）。
- 修复：`strategy_check_worker.py`/规则引擎阈值表对齐因子分尺度（明确 6.32 为何 hold——若为防御层规则请文档化）；文案去模板化（按层/方向差异化）。
- 验收：同一因子分区间 → 同一信号建议；文案非全模板。

**P0-4 设计详情涨跌幅字段恢复（B3）**
- 证据：`portfolio.py:266-275` 白名单；实测 strategies 有 `daily_change_pct=-0.65`、plans 无。
- 修复：get_design 转换层白名单补 `daily_change_pct/price/factor_score`；`DesignResult.vue` 保持现有 null 兜底。
- 验收：`GET /designs/506` → plans[].allocations[].daily_change_pct=-0.65；verify_e2e 加字段完整性断言。

**P0-6 US 英文名搜索修复（instruments US 段数据源降级链）**
- 证据：`instruments` 表 US=0/HK=0（实测）；`market_service.py:634` AAPL 仅中文名；`search_hk_us` 降级链依赖空表；`sync_instruments.py:240-260` `_fetch_us_list` **已有**东财主源+新浪降级链（round9 P0-4 修正，前 6 页 120 只）。
- 根因：`sync_instruments.py:118-124` `_guarded` 用 `asyncio.wait_for(coro, 20.0)` 包裹**整个 coro**——主源 `stock_us_spot_em` 卡满 20s 时降级链（新浪）被 `CancelledError` 一起取消、永不执行 → 段空置。
- 修复：① `_guarded`/`_fetch_us_list` 拆分主源与降级链**独立超时**（主源 5s 内失败即切新浪，降级链再 8s/页）；② `HKUS_STOCK_MAP` 补 name_en 字段作静态兜底；③ `search_hk_us` US 降级查 name_en。
- 验收：搜 "Apple"/"Tencent" → 命中；重启后 instruments US/HK >0（交易时段复测确认数据源恢复后同步成功）。

**P0-7 因子页面数据积累期引导（3.8 ⚠️）**
- 证据：`factors/active` summary `no_data:27`。
- 修复：前端 FactorModelView 对 `valid=0 & no_data>0` 显示「数据积累中（样本 N/30）」引导文案。
- 验收：无有效因子时页面不呈现"全失效"误判。

**P0-8 designs_list 热态 660-890ms 不降（2.3）**
- 证据：`task13_latency.json`。
- 修复：列表查询加 Redis/内存缓存（TTL 30-60s）或加索引；复杂度审计：仅读 DB 无网络，优先排查 N+1。
- 验收：热态 <300ms。

**P0-9 任务列表双显示 + 策略检查运行中不可见（3.10）**
- 证据：`portfolio.py:505-506` task_items 仅查 design 类型；`DashboardAiTools.vue:597-603` runningTasks 仅合成 design 且与 timeline 重复；实测 387/388 running 时 timeline 均不可见、design 完成前会双显示。
- 修复：
  ① **后端** `get_timeline` task_items 查询放宽为 `task_type.in_(["design", "check"])`，check 任务按 `record_id` 关联（R1）；task_items 条目补 `task_id` 字段（R3 去重依赖，现 554 行已有）；
  ② **前端** `loadHistoryList` runningTasks 过滤放宽为 `['design','check'].includes(t.type)`，合成条 `_type` 用 `t.type`（R2）；
  ③ **前端** 合成 runningTasks 前按 `task_id` 过滤掉 timeline `items` 中已存在的任务（R3——同一 running design 只显示一条，消除双显示）。
- 验收：点一次设计 + 一次策略检查 → 任务列表显示 1 条「智能组合设计」+ 1 条「策略检查与分析」，running 期间两者均可见、无重复；对应前端单测（DesignHistory/history 渲染）+ verify_e2e timeline 断言（running 任务可见性 + 类型正确）。

**P0-10 策略检查「增仓却降仓」矛盾建议 + apply-design 幽灵标的（3.11）**
- 证据：`portfolio_service.py:1260` increase 分支 `suggested = min(cur*1.2, 0.30)`（cur=0.5 → 0.30 低于当前）；`:1601-1602` apply-design added 分支 `name=f"{symbol} ETF"`；实测 task 389 `510300 increase 0.5→0.3`（矛盾）、task 384 同标的 `0.2→0.24`（正常）。
- 修复：
  ① **action/suggested 一致性**：`_rule_based_suggestion` 各分支在返回前做方向校验——`increase` 时 `suggested = max(suggested, cur)`（至少不降仓）、`decrease` 时 `suggested = min(suggested, cur)`（至少不升仓）、`hold` 时 `suggested = cur`；单只 30% 上限仅在 `increase` 目标超限时提示「已达/接近 30% 风控上限，建议维持」而非输出降仓矛盾值（R1）；
  ② **apply-design 幽灵标的**：`apply_portfolio_design` 对 `symbol not in etf_dict` 的新增标的，名称先查 `instruments`/`etf_list_cache` 补真实名，查不到才用默认名且**标记 `_degraded: true`** 供前端提示；同时 `update_etf` 补名称回填（目标存在但名为默认名时更新为真实名）（R2）；
  ③ **测试补强**：`test_z26_strategy_check_coverage.py` 加「action 方向 vs suggested_weight」一致性断言（increase→sug>cur、decrease→sug<cur、hold→sug==cur），含 cur=0.5 超 30% 上限场景（R3，防回归）。
- 验收：重跑策略检查 → 任一 `increase` 建议 `suggested_weight > current_weight`（或显式标注"已达上限"）；apply-design 新增标的名称非默认名或带 degrade 标记；单测负向断言（构造 cur=0.5 因子高+buy → 不得输出 increase 0.3）。

**P0-11 本地后端假死：`_route_us` 同步阻塞事件循环（3.12）**
- 证据：py-spy 实证 MainThread 卡 `_route_us → _td → fetch_realtime_twelvedata → run_in_thread`（`market_service.py:1236-1265`、`global_markets_fetcher.py:542`、`async_utils.py:67`）；`source_registry.py:240` `registry.route` 同步执行 provider；本地实测所有 API 15s 超时（进程存活假死）。
- 修复：
  ① **`_route_us` 改为真异步**：provider 闭包调用包 `await run_sync(...)`（或 `_td/_fh/_tf` 改为 async + `await`），`registry.route` 增加 async 变体或调用方先 `await run_sync(registry.route, providers)` 整体提交线程池——**确保同步 HTTP 永不在事件循环主线程执行**（R1，AGENTS.md async gotcha 修复）；
  ② **US 路径整体限时**：`get_asset_realtime` US 分支对 `_route_us` 已有 15s `_timeout` 概念但未真正 wait_for——补 `asyncio.wait_for(_route_us(symbol), timeout=8)`（R1 兜底）；
  ③ **慢源并发控制**：`fetch_realtime_twelvedata`/`fetch_realtime` 超时从 8s 收紧（TD 免费层 0.5s 正常），`run_in_thread` executor 参数核对（`_route_us` 内部应走 `long` 池避免占满 shared 64 worker）（R2）；
  ④ **事件循环响应性门禁**（对应 §5 盲区③）：verify_perf 加「并发 US 请求时事件循环延迟 <100ms」探针；**audit_async_blocking 补闭包追踪**（R3：`_is_inside_nested_def` 跳过嵌套 def 时，仍需扫描被外层 async def 捕获的同步闭包体内阻塞调用——对 `registry.route([(name, closure)])` 参数形态做 AST 追踪；同类 `_fh`/`_tf` 一并覆盖），防同类「async def 内闭包同步调用」再漏网。
- 验收：本地 `--host ::` 跑 10 并发 US 实时请求 → 事件循环保持响应（其它请求 <100ms）；py-spy 抓栈无 MainThread 在 `run_in_thread`/`requests`；verify_perf 事件循环探针通过。

**P0-12 因子「数据缺失」双视图不一致 + sample_count 语义错配（3.13）**
- 证据：`factors.py:305` vs `FactorModelView.vue:115` 双口径；`factor_registry.py:1725-1731` sample_count 统计非零符号数（恒<30）vs `factors.py:27` MIN_IC_SAMPLES=30 期望周期数；`ic_tracker.py:254-263` `_get_ic_sample_count` 读空 `_records`；实测 21 因子 IC 有效但 sample=0、DB 87278 条历史佐证。
- 修复：
  ① **sample_count 语义修正**（R2 主因）：`_sample_counts` 改为统计「该因子 IC 累积周期数」——`compute_periodic_ic` 成功产出 IC 时对 code 计数 +1（或从 DB `factor_ic_records` 按 `factor_code` 分组 count 作为样本数），替换当前「单批非零符号数」语义；`MIN_IC_SAMPLES=30` 对齐「≥30 个 IC 周期」；
  ② **`_get_ic_sample_count` 修复**（R3）：从 DB `factor_ic_records` 按 factor_code count（替代空 `_records`），或 `record()` 在 periodic compute 路径也触发；候选池空时显式告警（`main.py:451` 分支加日志）；
  ③ **双视图口径统一**（R1）：排序表「无数据」badge 改用 `f.status === 'no_data'`（与分类一致）而非 `ic_value === null`；或后端对「有 IC 值但 sample<MIN」的因子提供独立 `sample_pending` 标注（前端显示"积累中"而非"有效/无数据"二选一）；
  ④ **真缺失因子单独处理**：6 个 ic_value=null 因子（`tracking_error`/`shares_change`/`industry_diversification`/`institutional_holdings_change`/`ln_mcap`/`sentiment.news_direction`）查 `_data_source_gaps` 逐一定位数据源未接入点；
  ⑤ **测试补强**：`test_round14_apply_design_factors.py` 加「sample_count>0 时不得判 no_data」正反断言 + 「双视图 no_data 数量一致」前端断言。
- 验收：候选池恢复后 `/factors/active` 有 IC 的因子 `sample_count > 0` 且不再误判 no_data；排序表与分类 no_data 数量一致；6 个真缺失因子各有明确 reason（数据源未接入 vs 样本不足）。

**P0-13 候选池冷却期稳定性 + 卫星层候选多样性（3.14）**
- 证据：容器 full_pipeline 70 只（core 33/sat 30/def 7）正常，但 `admin/metrics` pool=25、冷却期后 `get_pool()` 空；`market_data_hub.py:678-688` last-good 保护仅对「refresh 产空」生效，冷却期受限产出 25 只时直接覆盖；设计 506/391 卫星入选 2-4 只且头部标的重合（562990/562600/589720 反复出现）。
- 修复：
  ① **last-good 保护扩展**（R1）：`_refresh_impl` 当 refresh 产出显著低于上次成功 pool（如 <50%）且数据源有冷却时，**保留 last-good pool** 而非覆盖——冷却期候选池不"昙花一现"；
  ② **冷却期显式标注**（R2）：refresh 受限时 `_pool` 标记 `_degraded` + 设计降级标记（`strategy_design.py:284-301` degradation 已存在，补充触发条件）；
  ③ **卫星层候选多样性**（R3，非阻塞优化）：`_balance_by_industry` 后对头部集中做多样化兜底（参照 etf_scanner `_inject_satellite_theme_quota` round6 F4 思路，按主题/行业保底注入非头部标的），减少"同一批标的反复入选"；
  ④ **测试补强**：`test_design_candidate_pool.py` 加「冷却期 refresh 保留 last-good」断言 + 「卫星层候选 > 阈值（如 8）」断言。
- 验收：数据源冷却期 `get_pool()` 保持上次成功 pool（非空）；设计请求在冷却期不降级到 6 只静态池；卫星层候选 ≥8 只且非全部头部重合。

**P0-14 持仓表 tracked_index 缺失（场内空 / 场外=场内 ETF 代码）（3.15）**
- 证据：DB 实证场内 11 只 `tracked_index=None`、场外 10 只=场内 ETF 代码；`add_etf`（portfolio_service.py:128-141）用请求参数（前端不传→None）；`enrich_tracked_indices`（etf_scanner.py:757-796）仅在候选池 `_refresh_impl` 调用（market_data_hub.py:517-523），持仓表从不 enrich；`AnalysisView.spec.js:35` mock 场内 null 固化现状；`probe_tidx_map.py` 实证场内指数名可拿（WIDE_BASIS_STATIC 10 只 + f168 缓存 53 条）且场外→场内→指数名可反查。
- **方案裁决（用户建议"场内场外都放具体指数"）**：**采纳展示层统一为具体指数，数据层保留双语义**——场外 `tracked_index`（场内 ETF 代码）是 `build_price_map`（portfolio_service.py:346-351）、盈亏估算（380-383）、taTarget 技术分析（AnalysisView.vue:126-137）的**功能依赖 key**，改成指数名会破坏 3 处；正确做法是展示层反查。
- 修复：
  ① **场内 tracked_index 回填**（R1）：持仓添加/列表加载时对 `tracked_index` 空的场内 ETF 调 `enrich_tracked_indices`（东财「跟踪标的」→ 真实指数名，如 510300→沪深300指数）或复用候选池 `_by_code` 的 tracked_index；`add_etf` 增加候选池查询兜底；
  ② **展示层统一为具体指数**（R2，采纳用户建议）：PnLDetailTable「跟踪指数」列渲染函数——**场内**直接显示 `tracked_index`（真实指数名）；**场外**取 `tracked_index`（场内 ETF 代码）→ 反查该 ETF 的 `tracked_index`（真实指数名）显示（如 022449→159338→"中证A500"）。反查源：候选池 `_by_code` / f168 缓存 / 持仓表已回填的场内 tracked_index——**数据层不动，功能零破坏**；
  ③ **测试补强**：`AnalysisView.spec.js` 场内 mock 改非空 tracked_index；加「场内持仓 tracked_index 非空」断言 + 「场外展示=场内反查指数名」断言（负向：场内 None / 场外反查失败 → FAIL）。
- 验收：场内持仓「跟踪指数」列显示真实指数名（510300→沪深300指数）；场外显示对应指数名（022449→中证A500）而非 ETF 代码；场外盈亏估算/技术分析功能不回归（tracked_index 数据层未改）。

**P0-15 持仓技术分析：K 线红跌绿涨 + 周期标注不可见 + 无涨跌幅（3.16）**
- 证据：`AnalysisView.vue:277`/`TechnicalAnalysisModal.vue:141` candlestick `color: CANDLE_DOWN`（涨绿）；`chartColors.js:43-44` 语义正确但消费处 color/color0 赋反；`AnalysisView.vue:416` 周期标注 12px #888 不可见；`AnalysisView.vue:421-434` tooltip 无涨跌幅、页面无涨跌区块。
- 修复：
  ① **K 线颜色修正**（R1）：candlestick `itemStyle` 改为 `color: CANDLE_UP（涨/红）、color0: CANDLE_DOWN（跌/绿）、borderColor/borderColor0` 同步；成交量 `volumeColors` 涨日用 CANDLE_UP、跌日用 CANDLE_DOWN——`AnalysisView.vue:277/254` + `TechnicalAnalysisModal.vue:141/136` 共 4 处；
  ② **周期标注增强**（R2）：`AnalysisView.vue:416` title `textStyle` 从 `{fontSize:12, color:'#888'}` 改为 `{fontSize:14, color:'#333', fontWeight:'600'}`（或引入主题 token），并在 ControlPanel 周期下拉旁显式显示当前周期徽标；
  ③ **涨跌幅区块**（R3）：AnalysisView 顶部（ChartPanel 上方）加「今日涨跌」行（复用 TechnicalAnalysisModal 的 `computeChangePct` 逻辑：K 线 close[-1] vs close[-2]，`text-up/text-down` 着色），与「收 X.XXX」并列；tooltip 加涨跌幅行；
  ④ **测试补强**（对应 §5 盲区①）：`AnalysisView.spec.js` 加「candlestick itemStyle color=CANDLE_UP（红涨）」源码级断言（参照 round14 P1-K 的 fs.readFileSync 模式）+ 「周期标注非 #888 浅灰」断言 + 「今日涨跌区块存在」断言。
- 验收：技术分析页 K 线红涨绿跌（与项目约定一致，`AnalysisView.spec.js` 源码断言）；周期标注清晰可见（字号 ≥14、对比度足够）；页面显式显示今日涨跌幅；TechnicalAnalysisModal 同步修正。

**P0-16 港股自选搜索补全慢：spot 拉取无条件执行（3.18）**
- 证据：实测 `09988` 搜索 4.09s（静态基座 618-619 行已含，但 `market_service.py:750-756` spot 拉取无条件等待 4s）；`腾讯` 0.009s（akshare 熔断短路才快）。
- 修复：
  ① **base 命中提前返回**（R1 主因）：`search_hk_us` 静态基座（`base`）命中且非空时，**跳过 spot 拉取直接返回**（spot 仅作 base 未命中时的补充）；或 spot 拉取与 base 匹配**并行不阻塞**（base 命中 → 立即返回 base 结果，spot 结果异步丢弃或下轮缓存）；
  ② **spot 缓存**：`fetch_hk_spot_list`/`fetch_us_spot_list` 结果加 TTL 缓存（30-60s，复用 `_asset_realtime_cache` 模式），避免每次搜索重复 4s 拉取；
  ③ **测试补强**：`test_search_hk_us` 加「静态基座命中时不触发 spot 拉取」断言（mock spot 慢 → base 命中应毫秒级返回）。
- 验收：`09988`/`00700` 搜索 <200ms（静态基座命中免 spot）；`腾讯`/`阿里巴巴` 不受影响；A 股搜索不受影响。

**P0-17 A股板块热度涨跌幅大量 0：财联社 sign 失效 + 源选型缺陷（3.19）**
- 证据：实测 `sectors/heat` nonzero=5/20（截图一致）；`fetch_cls_plate_changes` 依赖的财联社 `plate_list` 返回 **errno=50101（sign 失效）**；东财名称回填 5/20；`_ak_industry_sectors`（`sector_fetcher.py:59-89`）自带完整字段（change_pct/lead_stock/up-down/amount）但 heat 未用。
- 修复（按优先级）：
  ① **源切换**（根治）：`get_sector_heat` A 股改走 `_ak_industry_sectors`（东财行业板块 spot，自带真实涨跌幅 + 领涨股 + 成交额），热度排行与涨跌幅同源一致；akshare 失败时回退财联社 + 现有回填链；
  ② **sign 失效自愈**：`_CLS_SIGN` 失效（errno≠0）时**自动从财联社页面/接口刷新 sign**（或降级为东财名称回填并**显式标记 degraded**，而非静默 0）；
  ③ **监控**：`sectors_heat` 加「涨跌幅非零率」指标（nonzero/total），低于阈值（如 <50%）时告警日志 + 端点返回 `degraded: true`；
  ④ **测试补强**（对应 §5 盲区①）：`test_sectors_heat` 加「非零率 ≥ 50%」断言（负向：全 0 时 FAIL）+ 「东财回填命中 ≥10/20」断言。
- 验收：sectors/heat 20 个板块非零 ≥15；涨跌幅与东财板块行情一致（抽 3 个对比）；「领涨股」列有数据。

**P0-18 板块热度「技术分析」按钮失效：条目无 symbol（3.19）**
- 证据：`SectorHeatMap.vue:112` 技术按钮 → `openTechnical`（190-200 行）`symbol: item.symbol || item.code`；但 sectors/heat 条目实证仅 `rank/name/heat_index/rank_change/is_new/plate_code/change_pct`——**无 symbol/code** → `techModal.symbol=undefined` → `/market/chart/undefined` 404；「领涨股」列同因后端无 lead_stocks 空。
- 修复：
  ① **技术分析对象改为领涨个股**（正确语义）：后端 heat 条目补 `lead_stocks: [{symbol, name, change_pct}]`（akshare 源自带 `lead_stock_code/name/chg`，见 P0-17 源切换）；前端 `openTechnical` 传领涨股 symbol；无领涨股时按钮禁用；
  ② **板块指数技术分析**（可选增强）：若用户希望看板块整体 K 线，后端 `/market/chart/{sector_code}` 支持板块指数（东财 `bk` 代码 `m:90+t:2` 的板块行情，现有 chart 需扩展）——**本轮仅做 ①**，②列入 P2 排期；
  ③ **测试补强**：`SectorHeatMap.spec.js` 加「技术按钮点击后 symbol 非空且=领涨股」断言（负向：条目无 symbol 时按钮禁用或报错，不得发 undefined 请求）。
- 验收：板块热度「📈 技术」点击 → 领涨个股 K 线弹窗正常加载（非 404）；无领涨股板块按钮禁用；`SectorHeatMap.spec.js` 负向用例通过。

**P0-19 港股热门股票技术分析无数据：HK K 线降级链 8s 超时截断（3.20）**
- 证据：实测 `chart/09988?asset_type=HK` 恒 8.6-8.8s 空（多次复现）；`chart/00700` 1.9s 成功（同源不同结果）；腾讯源宿主机直测 0.3s/320 根正常；日志铁证 `get_history fetch_history empty` → chart 空 → **下一轮** `tencent hit 320 rows`。
- 修复（按优先级）：
  ① **腾讯 K 线前置**（根治，容器内唯一可用 HK 链）：`_fetch_akshare_history` HK 分支把 `_fetch_tencent_hk_history` **提前到 akshare 失败后立即执行**（finnhub/alphavantage 之后才轮到腾讯的串行顺序改为：akshare → 腾讯，finnhub/alphavantage 仅当腾讯也空时才试）；或 `fetch_history` HK 分支（`china_market.py:1536-1537`）直接先试腾讯再走 `_fetch_akshare_history`；
  ② **`_call` 超时放宽**：`get_history`（1321 行）对 HK/US 链 `_call(fetch_history, ..., timeout=20)`（链 4 源串行最坏 ~20s），避免 8s 截断在腾讯前；
  ③ **`get_history` 腾讯独立兜底**：`get_k_data`（1344-1351）失败后补 `_fetch_tencent_hk_history`（HK 专用，不依赖 akshare 链），与主链独立；
  ④ **测试补强**（对应 §5 盲区③）：`test_hk_kline_fix` 加「akshare 慢（mock 8s 超时）时腾讯仍可达」断言（负向：8s 截断返回空 → FAIL）；verify_perf 加「HK chart ≤3s」阈值软门禁。
- 验收：`chart/09988`（HK）稳定返回 ≥300 根 K 线 ≤3s（连续 3 次复测）；indicators/signal data_available=true；`test_hk_kline_fix` 负向用例通过。

**P0-20 港股指数自动补全不全："恒生港股通" 0 命中（3.21）**
- 证据：实测 `恒生港股通` 搜索 0 命中、`港股通` 1 个（CES100）；indices_meta 表 HK 38 条含"港股通"仅 1 条；**表无任何写入/同步逻辑**（静态历史快照，market_service.py:885-942 只读）。
- 修复：
  ① **补全表数据**（立即见效）：从东财指数列表（`push2 clist?fs=m:1+s:2` 或 akshare `index_stock_info`）+ 中证指数官网补充"恒生港股通"系列（恒生港股通中国内地银行/高股息率/央企/科技等）及主流港股指数，写入 indices_meta（含 name/pinyin/first_letter/market=HK）；
  ② **接入指数同步机制**（根治）：启动/定时任务同步指数列表到 indices_meta（参照 `sync_instruments.py:91-116` 的五段同步模式——指数段接入 `collect_all`），数据源失败时保留 last-good 不覆盖；
  ③ **搜索降级链**（可选增强）：`_search_indices` 表未命中时降级 akshare/东财指数实时列表（对照个股搜索的 instruments→levistock→spot 多级降级模式）；
  ④ **测试补强**（对应 §5 盲区①）：`test_search_indices` 加「'恒生港股通' 命中 ≥3」断言 + 「HK 指数表 ≥60 条」断言（负向：表空/命中 0 → FAIL）。
- 验收：搜索"恒生港股通"命中 ≥3 个港股指数；"港股通"命中 ≥5；HK 指数表 ≥60 条；重启后数据不丢（同步逻辑幂等）。

**P0-21 美股添加自选自动补全慢：US ETF enrich 同步阻塞事件循环（3.22）**
- 证据：实测 `QQQ` 搜索 7.4s（include_stocks=false 0.022s）；`AAPL` 0.028s（stock 不 enrich）；根因 `_route_us`（`market_service.py:1236-1265`）`registry.route` 同步执行 `_td` 闭包 → `run_in_thread` 阻塞事件循环（P0-11 关联路径）。
- 修复（与 P0-11 联动，P0-16 后实施）：
  ① **enrich 非阻塞化**（R2 主因）：`_enrich`（849-864）调 `get_asset_realtime` 前先判 `_route_us` 是否已修（P0-11 落地后事件循环不阻塞）；未修期间**跳过 ETF enrich 或仅用缓存价**（spot 已带价则直接用，不再二次实时）——搜索补全**不需要实时价**，返回静态基座 + spot 价即可；
  ② **P0-11 优先落地**：`_route_us` 改异步（provider 走 `run_sync`/`asyncio.to_thread` 而非同步阻塞）——根治美股实时链路阻塞，enrich 自然恢复；
  ③ **测试补强**（对应 §5 盲区③）：`test_search_hk_us` 加「ETF 命中时事件循环可响应（并发 ping 不被阻塞）」断言（负向：`_route_us` 同步阻塞时 ping 延迟 >1s → FAIL）；verify_perf 加「US 搜索 ≤1s」阈值软门禁。
- 验收：`QQQ`/`SPY` 搜索 ≤1s（静态基座 + spot 价，enrich 不阻塞）；并发请求不受影响；P0-11 落地后 enrich 恢复实时价。

**P0-22 美股标的分析输入指数报错：round14 P2-AM 未落地（3.24，与 P0-20 联动；取代 P0-5）**
- 证据：实测 `SPX`（kind=index, market=US）0 命中；`标普` 混入港股 GEM/HKL；`GEM` 搜索 0（不搜 symbol）；realtime/GEM asset_type=index 失败；`sync_indices_meta.py`（backend/scripts/）仅 A/HK 源（59/85 行）**无美股源**。round14 P2-AM 三处修复（`_search_indices` 签名 + L95/L188 透传 + useMarketSearch L82 去 kind==='all' 限制）**未落地**。
- 修复（对应 round14 P2-AM + 本诊断 R1-R4）：
  ① **market=US 过滤**（R2）：`_search_indices`（market.py:249-252）补 `elif market.upper() == "US": stmt = stmt.where(IndexMeta.market == "US")`；
  ② **指数代码可搜**（R1）：`_search_indices` 的 or_ 加 `IndexMeta.symbol.ilike(f"%{kw}%")`（对照 `search_indices` market_service.py:923 已含 symbol）；
  ③ **补美股指数数据**（R3，与 P0-20 联动）：indices_meta 补充主流美股指数（SPX/道琼斯/纳斯达克/标普500/VIX 等，market=US），P0-20 的同步机制一并覆盖；
  ④ **跨市场 realtime 防护**（R4）：指数 realtime 按 `symbol.market` 路由，跨市场标的显式报「该市场指数暂不支持」而非裸失败（前端展示友好错误）；
  ⑤ **测试补强**（对应 §5 盲区①）：`test_search_indices` 加「market=US 只返回 US 指数」断言（负向：混入 HK/A 指数 → FAIL）+「SPX 代码可搜」断言。
- 验收：美股 tab 搜"SPX"/"标普"命中 ≥3 个美股指数；不混入港股指数；选中后 realtime 正常或友好提示；`test_search_indices` 负向用例通过。

**P0-23 候选池误杀活跃板块 ETF：快照成交额异常（3.25）**
- 证据：实测 5 只强势板块 ETF 快照 amount 48.9/6.2/17.6/9.8/8.6 万，全 < `MIN_AVG_AMOUNT=1000 万`（etf_scanner.py:54）被 `filter_etfs`（610 行）过滤；gtimg 原始接口实测真实成交额 9.7/1.6/2.9 亿——**快照低估 ~2000 倍**；设计方案卫星层因此缺半导体设备/游戏/恒生科技。**与 round15 §5.4（数据源层 ×10000 已修）同根因两层：数据源已修、缓存未重建，实施勿重复修数据源**。
- 修复：
  ① **refresh 用实时成交额覆盖**（根治）：候选池 refresh 时对 `filter_etfs` 前的快照金额，用实时 gtimg/东财成交额覆盖（或 filter_etfs 在 amount 存疑时回退实时查询），避免陈旧快照误杀；
  ② **快照刷新**：`etf_list_cache.json` 过期后（本轮 age≈7 天）refresh 重建，不长期复用异常快照；
  ③ **异常值护栏**：filter_etfs 对 `amount` 与同板块中位数偏离 >10 倍（或与历史不一致）时打 WARNING + 该标的走实时成交额补查，不静默按低值过滤——防「虚拟流动性误杀」再发；
  ④ **测试补强**（对应 §5 盲区①型；盲区表无「候选池金额与实时一致」专项，落地后可回填盲区表）：`test_design_candidate_pool` 加「活跃板块标杆 ETF（159516/513010/512480）在候选池」断言（负向：被快照异常过滤 → FAIL）；对照 `test_round15_amount_unit.py`（只验 ×10000 单位层）补缓存层 amount 断言。
- 验收：候选池含 159516/159869/513010 等强势板块；`filter_etfs` 后活跃 ETF 成交额与实时行情一致；**P0-13 的 last-good 池在 refresh 金额恢复正常后重建（不固守异常快照构建的旧 pool）**；`test_design_candidate_pool` 负向用例通过。

### P1 级（性能/体验）

**P1-1 行情 WS 推送消费修复（B4）**
- 证据：`stores/market.js:59-75` vs `market_refresh.py:23`。
- 修复：前端 WS onmessage 增加 `msg.type==='realtime'` 分支消费 `msg.data`。
- 验收：WS 收到推送 → realtimeData 更新（不再受 `_PORTFOLIO_REALTIME_TTL=15` 缓存节流，前端实时刷新）。

**P1-2 watchlist 冷态 7.75s（2.3 最严重）**
- 证据：`task13_latency.json`。
- 修复：冷态首拉并行化/降并发；per-item 超时分级已有（P2-AF），重点查批量首拉是否串行；预热覆盖 watchlist 常用标的。
- 验收：冷态 ≤3s。

**P1-3 A 股 LLM 链路 77.8s vs HK/US 30s（3.3）**
- 证据：`task4_result.json`/`task4b_result.json`。
- 修复：A 股上下文采集（新闻/板块）与 LLM 调用并行；LLM 排队加超时分级（>45s warn、>90s 降级规则）。
- 验收：A 股 llm-report ≤45s；概念分析排队不超 90s。

**P1-4 前端 home 页 performance 55（LCP 3.4s/TBT 570ms/CLS 0.389）（2.2）**
- 证据：`lh_home_round16.json`。
- 修复：① 修 CLS：Dashboard 组件加载态占位（骨架屏/固定尺寸）——round14 P1-G 方向对但未落实完整；② TBT：首屏减少主线程长任务（组件懒加载/分包）；③ unused-js 85KiB：按路由分包。
- 验收：home perf ≥60、CLS <0.1（Lighthouse 实测记录）。

**P1-5 预热 fetch_macro_snapshot 7.49s（2.1）**
- 证据：`warmup_cprofile.txt`。
- 修复：macro 拉取 12 个 HTTPS 串行→并发（asyncio.gather）或 24h 缓存。
- 验收：预热 ≤5s。

**P1-6 自选列表增加「技术分析 / AI 分析」按钮（3.17，功能增强）**
- 证据：`WatchlistPanel.vue:140-142` 行内仅编辑/移除；`SectorHeatMap.vue:112-113/121-128/190-200` 已有完整双按钮模式（TechnicalAnalysisModal + assetType 市场推断 + `@ai` 切换）；后端接口全部已存在。
- 修复：
  ① **WatchlistPanel 行内加双按钮**：「📈 技术」→ 复用 `TechnicalAnalysisModal`（assetType 按 `item.market/asset_type` 推断，参照 SectorHeatMap `openTechnical` 190-200 行——自选 A/HK/US 混合必须）；「🤖 AI 分析」→ emit `analyze` 事件 → MarketAnalysis `externalTrigger` 触发 UnifiedAnalysis symbol 模式（参照 SectorHeatMap `emitAnalyze` 182-188 行）；
  ② **MarketAnalysis 接线**：WatchlistPanel 增加 `@analyze` 监听 → `onQuickAnalyze`（复用热点行路径）；TechnicalAnalysisModal `@ai` 事件联动 AI 分析（与 SectorHeatMap:127 一致）；
  ③ **测试补强**：`WatchlistPanel.spec.js` 加「行内技术/AI 按钮存在且点击触发」断言 + 「HK/US 标的 assetType 推断正确」断言。
- 验收：自选列表每行显示「📈 技术 + 🤖 AI 分析」；点击技术 → K 线弹窗（HK/US 按正确市场取数）；点击 AI → UnifiedAnalysis symbol 模式自动分析；零新后端接口。

**P1-7 自选列表加载慢：三市场批量串行（3.18）**
- 证据：实测 GET watchlist（19 只）**19.2s**（A 批量 4s + HK 批量 4s + US 批量 4s 串行 + per-item 叠加）；`market.py:693-699` 三市场 `_batch_for` 顺序执行；round16 时 7.75s → 本轮 19.2s（自选扩容后恶化）。
- 修复：
  ① **批量并行化**（R2 主因）：三市场 `_batch_for` 改为 `asyncio.gather` 并发（A/HK/US 同时拉取，最坏 4s 而非 12s）；per-item 兜底保留；
  ② **批量结果缓存**：`get_realtime_batch` 结果按 (symbols, asset_type) 加 TTL 缓存（5-10s，复用 `_asset_realtime_cache` 模式），列表频繁刷新不重复触网；
  ③ **慢源熔断优先**：akshare/mootdx 冷却时批量立即降级 DB-only（`_degraded` 标记），不等 4s 超时（source_registry 已有熔断，确认 `get_realtime_batch` 走 registry 短路）；
  ④ **测试补强**（对应 §5 盲区③）：verify_perf 加 watchlist 加载阈值（冷态 ≤3s、热态 ≤500ms）——接入 pre-commit 软门禁。
- 验收：watchlist 加载 ≤3s（19 只 A+HK+US 混合）；热态 ≤500ms；冷态慢源时 DB-only 快速降级（不 19s 卡死）。

**P1-8 市场 tab 切换后标的分析输入框未清空（3.23，前端交互 bug）**
- 证据：`UnifiedAnalysis.vue:166-177` marketTab watch 只清 `search`（symbol 实例）；`sectorSearch`/`indexSearch` 实例无任何清空点（全文件仅 activeSearch computed 引用）→ 指数/板块模式输入残留。
- 修复：
  ① **三实例统一清空**：marketTab watch 补清 `sectorSearch`/`indexSearch`（searchQuery/results/showDropdown 同 `search`）——抽 `_resetSearchInstance(search)` 工具函数复用，避免再漏；
  ② **switchMode 同步清**：`switchMode`（153-155 行）切换模式时清**新激活**实例的 searchQuery（防"切模式不清"同类残留）；
  ③ **测试补强**（对应 §5 盲区①）：`UnifiedAnalysis.spec.js` 加「marketTab 切换后 index/sector 模式输入框为空」断言（负向：残留内容 → FAIL）+「switchMode 切换后新实例 searchQuery 为空」断言。
- 验收：指数/板块模式输入后切 tab → 输入框清空；symbol 模式回归不破坏；`UnifiedAnalysis.spec.js` 负向用例通过。

### P2 级（测试防护/体验优化，随轮次排期）

**P2-1 基线 B news 分级用例修复**（盲区②）：修函数名引用 + 断言形态 + SKIP 计数门禁。
**P2-2 verify_perf 接入**（盲区③④）：pre-commit 软门禁 + watchlist 冷态阈值 + 台账。
**P2-3 契约字段完整性 e2e**（盲区⑤）：get_design 字段断言。
**P2-4 依赖表同步守卫**（盲区⑥）：instruments US/HK>0 + indices_meta 美股段守卫。
**P2-5 策略检查 LLM 预算复核**（3.2 ⚠️）：73s 截断说明 75s 预算不足，复核 `_llm_timeout_for`。
**P2-6 两套信号口径 UI 区分**（3.6 ⚠️）。
**P2-7 冗余清理**（§6，按批次 + 门禁验证）。
**P2-8 数据源冷却告警**：akshare/dongfang 冷却时 `/sources/health` 前端展示 + 报告降级标记。

**P2-9 契约偏差收口（B1/B2/B6，§3.9）**：
- B1 `analysis.py:176-181` SymbolAnalysisRequest 补 `market` 字段（Pydantic 显式声明，防 extra 静默忽略）+ 单测「传 market 字段被解析」断言；
- B2 `design-async` 响应补 `design_id`（或前端 `DashboardAiTools.vue:414` 改从 WS/轮询可靠取值）+ 契约测试「design-async 响应含 design_id」断言；
- B6 `WatchlistPanel.vue:129` 判空改为 `change_pct != null && change_pct >= 0`（null 不渲染涨跌色，显示「—」）+ 单测「change_pct=null 不标色」断言。
- 验收：三处契约偏差消除，对应负向断言通过。

---

## 八、实施顺序与验收口径

1. **P0 批次**（P0-1→P0-6→P0-4→P0-3→P0-2→P0-7→P0-8→**P0-9→P0-10→P0-11→P0-12→P0-13→P0-14→P0-15→P0-16→P0-17→P0-18→P0-19→P0-20→P0-21→P0-22→P0-23**）：每项单测 + verify_e2e 对应断言；P0-1/P0-4 负向断言必含「全兜底时不得标 full/不得缺字段」；P0-9 含前端 DesignHistory/history 渲染单测 + timeline running 可见性断言；P0-10 含「action 方向 vs suggested_weight」一致性断言（负向：increase 不得输出 sug<cur）；P0-11 含并发 US 请求事件循环响应性探针 + py-spy 栈验证；P0-12 含「sample_count>0 不判 no_data」断言 + 双视图数量一致断言；P0-13 含冷却期 last-good 保留断言 + 卫星层候选阈值断言；P0-14 含「场内持仓 tracked_index 非空」断言；P0-15 含 K 线颜色源码断言 + 涨跌幅区块断言；P0-16 含「静态基座命中免 spot」断言；P0-17 含「sectors_heat 非零率 ≥50%」断言 + 东财回填命中断言；P0-18 含「技术按钮 symbol=领涨股非空」断言（负向：undefined symbol 不得发请求）；P0-19 含「akshare 慢时腾讯仍可达」断言 + HK chart ≤3s 软门禁；P0-20 含「'恒生港股通' 命中 ≥3」断言 + HK 指数表 ≥60 条断言；P0-21 含「ETF 命中时事件循环可响应」断言 + US 搜索 ≤1s 软门禁（与 P0-11 联动）；P0-22 含「market=US 只返回 US 指数」断言 + SPX 代码可搜断言（与 P0-20 联动）；P0-23 含「活跃板块标杆 ETF 在候选池」断言（负向：快照异常过滤 → FAIL）。
2. **P1 批次**（P1-1→P1-2→P1-3→P1-4→P1-5→**P1-6→P1-7→P1-8**）：性能修复后 Lighthouse/耗时实测记录到提交说明；P1-6 功能增强含前端单测（按钮存在 + assetType 推断）；P1-7 含 watchlist 加载阈值软门禁（≤3s）；P1-8 含前端单测（tab 切换后 index/sector 输入框清空断言）。
3. **P2 批次**：测试防护（P2-1/2/3/4）优先于体验项（P2-5/6/7/8/9）。
4. **每批 DoD**：测试绿 + 现实证真（真实调用点/非兜底数据/内容断言）+ 性能记录；pre-commit 全绿。
5. **收尾**：冗余清理按 §6 批次执行；容器重建复测（交易时段验证窗口）。

> **非交易时段/数据源冷却期结论**（标"待复测"）：候选池 26 只（静态池兜底）、资金流因子缺失、US spot 源失败、hot-plates 部分来源冷却——以上在交易时段 + 数据源恢复后复测确认。

---

## 附：本轮诊断产物索引

> 清理约定：`scripts_diag/` 属诊断残留（§6 第一批删除），实施前先将下表 scripts_diag 产物**归档到 `logs/round16/`** 再删目录。

| 产物 | 路径 | 处置 |
|---|---|---|
| 预热报告 | `logs/warmup_timing.json` / `warmup_cprofile.txt` / `warmup_pyinstrument.txt+html` | 保留（logs/） |
| Lighthouse 报告 ×5 | `logs/lh_{home,market,portfolio,factors,news}_round16.json` | 保留（logs/） |
| 设计 506 详情/报告 | `scripts_diag/design_506_utf8.json` / `design_506_report.md` | 归档到 `logs/round16/` |
| 策略检查 384 | `scripts_diag/check_384_result.json` / `check_384_report.md` | 归档到 `logs/round16/` |
| 涨跌幅/指标核验 | `scripts_diag/design_pct_verify.json` / `design_ind_verify.json` | 归档到 `logs/round16/` |
| 后端耗时 | `scripts_diag/task13_latency.json` | 归档到 `logs/round16/` |
| 三市场分析链路 | `scripts_diag/task4_result.json` / `task4b_result.json` / `task4c_result.json` | 归档到 `logs/round16/` |
| 批量验证 | `scripts_diag/task5_9_result.json` / `task8_detail.json` / `search_verify.json` | 归档到 `logs/round16/` |
| 搜索/板块/指数探针 | `scripts_diag/probe_*.py`（19 个：hk_speed/hk_add/hk_index/hk_ta×3/index_db/index_json/plate_chg/plate_fields/tx_hk/us_index×2/us_search/em_backfill/cls_join/full_pipeline/pool_snapshot） | 归档到 `logs/round16/`（源码保留可复跑） |
| 链路探针（task3/4/5/6/7/8） | `scripts_diag/task3_*.py`（9 个）`task4_hot.py` `task4b_symbol_sector.py` `task4c_us_index.py` `task5_watchlist*.py` `task6_signal.py` `task7_news.py` `task8_factors*.py` `task12_latency.py` `task12_warm_cold.py` | 归档到 `logs/round16/` |
| 数据核查探针 | `scripts_diag/dump_*.py` / `ic_check_db.py` / `factor_gap_analysis.py` / `compare_factors.py` / `us_history_check.py` / `us_realtime_check.py` / `check_*.py`（check_call_chain/check_circuits/check_kline_inproc/check_route_inproc） | 归档到 `logs/round16/` |
| 板块/指数核查 | `scripts_diag/cls_*.py`（5 个）`em_board_*.py`（2 个）`heat_match_check.py` / `test_sina_direct.py` | 归档到 `logs/round16/` |
| 核验脚本 | `scripts_diag/verify_design_indicators.py` / `verify_design_pct.py` / `verify_search.py` / `fetch_check384.py` / `fetch_design506.py` / `analyze_check389.py` / `analyze_design391.py` / `factor_frontend_sim.py` / `restore_weights.py` | 归档到 `logs/round16/` |
| Lighthouse 解析 | `scripts_diag/parse_lh*.py` / `run_lighthouse_pages.py` / `list_sources.py` / `decode_sse.py` / `ctx_compare.py` | 归档到 `logs/round16/` |
| 断裂排查 | 子代理报告（表 A-D，§3.9 摘录） | 文档内已摘录 |
| 冗余清单 | 子代理报告（41 项，§6 摘录） | 文档内已摘录 |

> **以上为诊断结论与优化方案（只设计不实施）。** 实施按 §8 批次在后续轮次执行，每项以 §7 的验收口径为准。
