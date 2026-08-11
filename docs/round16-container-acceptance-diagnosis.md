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
| 指数分析 | ✅ A 指数搜索正常 | — | ❌ US 指数搜索 0 命中 | 见 P0-5 |
| 搜索补全 | ✅ 510300→ETF/茅台→600519 排序正确 | ✅ 腾讯/00700 | ✅ AAPL（❌ Apple 英文名） | 见 P0-6 |

**审阅发现**：
- **P0-5 US 指数搜索断裂**：`indices_meta` 表 588 条**无美股指数**（`sync_indices_meta.py` 数据源仅 A/港股/行业/概念）；且 `_search_indices`（`market.py:249-252`）market 过滤只处理 A/HK，**US 分支缺失** → 搜「道琼斯/纳斯达克」0 命中、搜「标普」返回港股 GEM/HKL；
- **P0-6 US 英文名搜索断裂**：`HKUS_STOCK_MAP`（`market_service.py:634`）AAPL 仅中文名"苹果"；`include_stocks` 时 spot 源（akshare）冷却失败 + 本地 `instruments` 表 **US 段 0 条**（同步逻辑在 `sync_instruments.py:91-116` 的 `collect_all` 已含 A股/ETF/港股/港股ETF/美股五段，但美股段 `stock_us_spot_em` 在当前网络环境黑洞 20s 超时失败、港股段受东财源冷却影响——**根因是数据源失败非同步逻辑缺失**）→ 搜 "Apple" 0 命中（round14 R6-F9 声称修复，但降级链依赖的表段从未成功填充）；
- **P1-7 A 股 LLM 链路慢**：llm-report 77.8s vs HK 33.5s vs US 26.8s——A 股上下文采集（新闻 120s 循环 + 板块缓存）与 LLM 排队叠加；概念分析 LLM 排队时可 90s 超时（复测 59.8s 通，属偶发排队非固定 bug）；
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
> | P0-5 | ✅search实测 | ✅market:249+sync_indices | ✅重启后 | ✅种子兜底 | ✅搜索框 | — | ✅同步超时 | ✅⑥ |
> | P0-6 | ✅search实测 | ✅sync_instr:91+ms:634 | ✅交易时段 | ✅name_en兜底 | ✅搜索框 | — | ✅降级链超时 | ✅⑥ |
> | P0-7 | ✅factors实测 | ✅factors/active | — | ✅引导文案 | ✅FactorModelView | ✅四态 | — | ✅④ |
> | P0-8 | ✅task13 | ✅task13_latency | — | — | ✅designs列表 | — | ✅缓存/索引 | — |

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

**P0-5 US 指数搜索修复**
- 证据：`sync_indices_meta.py` 无美股源；`market.py:249-252` 无 US 分支；实测「道琼斯」0 命中。
- 修复：`sync_indices_meta` 增加美股指数种子（DJI/IXIC/GSPC 等，参照 `market_service.py:156-158` 静态映射）；`_search_indices` 加 US 过滤分支。
- 验收：搜「道琼斯/纳斯达克/标普」market=US → 命中对应指数；重启后 indices_meta 含美股段。

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

### P1 级（性能/体验）

**P1-1 行情 WS 推送消费修复（B4）**
- 证据：`stores/market.js:59-75` vs `market_refresh.py:23`。
- 修复：前端 WS onmessage 增加 `msg.type==='realtime'` 分支消费 `msg.data`。
- 验收：WS 收到推送 → realtimeData 更新（不再受 `_PORTFOLIO_REALTIME_TTL=15` 缓存节流，前端实时刷新）。

**P1-2 watchlist 冷态 7.75s（2.3 最严重）**
- 证据：`task13_latency.json`。
- 修复：冷态首拉并行化/降并发；per-item 超时分级已有（P2-AF），重点查批量首拉是否串行；预热覆盖 watchlist 常用标的。
- 验收：冷态 ≤3s。

**P1-3 A 股 LLM 链路 77.8s vs HK/US 30s**
- 证据：`task4_result.json`/`task4b_result.json`。
- 修复：A 股上下文采集（新闻/板块）与 LLM 调用并行；LLM 排队加超时分级（>45s warn、>90s 降级规则）。
- 验收：A 股 llm-report ≤45s；概念分析排队不超 90s。

**P1-4 前端 home 页 performance 55（LCP 3.4s/TBT 570ms/CLS 0.389）**
- 证据：`lh_home_round16.json`。
- 修复：① 修 CLS：Dashboard 组件加载态占位（骨架屏/固定尺寸）——round14 P1-G 方向对但未落实完整；② TBT：首屏减少主线程长任务（组件懒加载/分包）；③ unused-js 85KiB：按路由分包。
- 验收：home perf ≥60、CLS <0.1（Lighthouse 实测记录）。

**P1-5 预热 fetch_macro_snapshot 7.49s（2.1）**
- 证据：`warmup_cprofile.txt`。
- 修复：macro 拉取 12 个 HTTPS 串行→并发（asyncio.gather）或 24h 缓存。
- 验收：预热 ≤5s。

### P2 级（测试防护/体验优化，随轮次排期）

**P2-1 基线 B news 分级用例修复**（盲区②）：修函数名引用 + 断言形态 + SKIP 计数门禁。
**P2-2 verify_perf 接入**（盲区③④）：pre-commit 软门禁 + watchlist 冷态阈值 + 台账。
**P2-3 契约字段完整性 e2e**（盲区⑤）：get_design 字段断言。
**P2-4 依赖表同步守卫**（盲区⑥）：instruments US/HK>0 + indices_meta 美股段守卫。
**P2-5 策略检查 LLM 预算复核**（3.2 ⚠️）：73s 截断说明 75s 预算不足，复核 `_llm_timeout_for`。
**P2-6 两套信号口径 UI 区分**（3.6 ⚠️）。
**P2-7 冗余清理**（§6，按批次 + 门禁验证）。
**P2-8 数据源冷却告警**：akshare/dongfang 冷却时 `/sources/health` 前端展示 + 报告降级标记。

---

## 八、实施顺序与验收口径

1. **P0 批次**（P0-1→P0-6→P0-4→P0-3→P0-2→P0-7→P0-8）：每项单测 + verify_e2e 对应断言；P0-1/P0-4 负向断言必含「全兜底时不得标 full/不得缺字段」。
2. **P1 批次**（P1-1→P1-2→P1-3→P1-4→P1-5）：性能修复后 Lighthouse/耗时实测记录到提交说明。
3. **P2 批次**：测试防护（P2-1/2/3/4）优先于体验项（P2-5/6/7/8）。
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
| 断裂排查 | 子代理报告（表 A-D，§3.9 摘录） | 文档内已摘录 |
| 冗余清单 | 子代理报告（41 项，§6 摘录） | 文档内已摘录 |

> **以上为诊断结论与优化方案（只设计不实施）。** 实施按 §8 批次在后续轮次执行，每项以 §7 的验收口径为准。
