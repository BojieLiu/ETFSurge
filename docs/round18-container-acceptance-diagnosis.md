# Round18 容器验收诊断（2026-08-12）— 性能/数据质量/断裂/测试盲区全链路诊断与优化方案

> **性质**：容器验收诊断（对标 round14/round16 流程）——构建最新代码 → 全链路功能验收 → 性能诊断 → 数据质量审阅 → 测试盲区归因 → 冗余清理 → 优化方案（**本份只设计不实施**）。
> **验证窗口**：2026-08-12（周三）19:20-20:10 UTC+8，**非交易时段**——外部数据源（akshare/东财）冷却，涉及外部源结论标注「冷却期现象，待交易时段复测」。
> **环境**：Docker prod profile（`docker-compose.yml` + `docker-compose.diag.yml` 诊断 override，`PROFILE_WARMUP=1`）；commit `bcee936`（round17 实施后最新）；后端 8000 / 前端 80。
> **基线**：round16 诊断（2026-08-11 交易日）数据用于对照。

---

## 一、诊断范围与方法

| 阶段 | 动作 | 结果落点 |
|---|---|---|
| 1 构建 | `docker compose --profile prod build` + 回收老镜像 + up（PROFILE_WARMUP=1） | §2.1 |
| 2 预热诊断 | WarmupProfiler（pyinstrument + cProfile + warmup_timing.json） | §2.1 |
| 3 组合设计+策略检查 | `POST /portfolio/design-async`（balanced 50w）→ design_id=519；`POST /portfolio/strategy-check-async`（on_exchange）→ task 407 | §3.1/§3.2 |
| 4 三市场分析 | llm-report / llm-advice / symbol-analysis / sector-analysis / search（A/HK/US） | §3.3 |
| 5-9 功能验收 | hot-plates / stock-hot-rank / watchlist / signals / news / factors | §3.4-§3.8 |
| 10 断裂排查 | 前端 52 API + 4 SSE + 3 WS 全量比对 + timeline/metrics 运行时验证 | §3.9 |
| 11 docs 落地 | round16/round17 方案核对（静态 + 运行时） | §4 |
| 12 前端性能 | Lighthouse 13.4.1 五页面 | §2.2 |
| 13 后端性能 | 17 条热点链路 ×3 次耗时 | §2.3 |
| 14 测试盲区 | 本轮发现 vs 测试防护体系归因 | §5 |
| 15 冗余 | 死端点/死代码/遗留文件清理清单 | §6 |
| 16 方案 | P0-P2 分级（本份不实施） | §7 |

> **方法约束**（design-checklist D1-D3）：结论附 `file:line` 与实测命令输出；外部数据源结论标注验证窗口；非交易时段结论打标「待交易时段复测」。

---

## 二、性能诊断结论

### 2.1 后端预热（PROFILE_WARMUP=1，产物 `logs/warmup_timing.json` / `warmup_cprofile.txt` / `warmup_pyinstrument.txt`）

预热墙钟 **9.0s** / 分段累计 **14675ms**（≤25s 门禁达标），瓶颈（cProfile 证据）：

| 分段 | 耗时 | 占比 | 根因 |
|---|---|---|---|
| warmup_market_cache | 8543.7ms | 58% | `fetch_fund_nav`×10 累计 24.6s（akshare `fund_open_fund_info_em` 10.5s + `_fetch_ttj_lsjz` 16.0s，线程池摊薄）；`fetch_macro_snapshot` 单次 **9.0s**（12 个 HTTPS 串行） |
| warmup_global_indices | 5835.9ms | 40% | 12 个 HTTPS 连接累计（urllib3 create_connection + SSL 握手） |
| init_db / redis_init / etf_cache | 294ms | 2% | 正常 |
| DNS/SSL 网络等待 | getaddrinfo 5.06s + SSL 4.5s | — | 预热主体为网络等待非 CPU |

**结论**：预热 9.0s 达标（round16 交易日 7.6s；差异为非交易时段数据源冷却）。`fetch_macro_snapshot` 9.0s 与 `fetch_fund_nav` 24.6s 为最优优化目标（串行→并发 or 缓存延长），与 round16 §2.1 同源，**非本轮新问题**。

### 2.2 前端 Lighthouse（13.4.1，五页面，prod 80 端口）

| 页面 | performance | LCP | TBT | **CLS** | round16 对照（perf/CLS） |
|---|---|---|---|---|---|
| **home（Dashboard）** | **46** | 3.6s | 950ms | **0.389** | 55 / 0.389 |
| market | **41** | 3.6s | 1450ms | **0.389** | 99 / 0.001 |
| portfolio | **40** | 3.7s | 1420ms | **0.389** | 99 / 0.001 |
| factors | **37** | 4.1s | 1560ms | **0.389** | 99 / 0.001 |
| news | **34** | 4.1s | 2130ms | **0.389** | 97 / 0.034 |

**关键发现（数据铁证）**：
- **CLS 五页恒 0.3885205676603475**（浮点级一致，round16 home 同数值）——home 的 CLS 0.389 是 round16 存量问题（round14 P1-G 声称修复无实测，round16 §5 盲区④已指出），**本轮扩散到全部页面**；
- **扩散根因**：非交易时段数据源冷却 → 页面首屏 API（watchlist/sector_heat/global_indices 冷态 2.3-8.6s）慢 → loading 占位→内容填充高度变化 → 全页 CLS/LCP/TBT 恶化。Lighthouse mobile 模拟（4x CPU + 慢网络）放大该效应；
- 长任务归因：`vendor-axios-DPD2LaFy.js` 580ms（`other` 类型非 scriptEvaluation）+ `vendor-vue-BHBe1R-m.js` 418ms——axios chunk 上的长任务 attribution 异常（47KB 脚本不应 580ms），疑似主线程 API 等待/状态更新被归因；
- unused-js 85KiB（vendor-echarts-CKk97MSv.js 558KB 中 183KB 加载 87KB 浪费）。

**结论**：环境因素（数据源冷却）主导本轮评分下跌（LCP/TBT/CLS 全受首屏 API 慢影响），**须交易时段复测区分**；存量问题 = home CLS 0.389（P1-G 从未实测）+ echarts 分包。**软门禁**：home 46 < 60 记录性能债。

### 2.3 后端热点链路（17 条 ×3 次，`logs/round18/task13_latency.json`）

| 链路 | run1(冷) | run2/3(热) | 基准 | 结论 |
|---|---|---|---|---|
| **watchlist** | 2336ms | 29-38ms | ≤3s | ✅ **P1-2 修复生效**（round16 冷态 7.75s → 2.3s 达标） |
| designs_list | 1688ms | 9-25ms | — | ✅ P0-8 缓存生效（round16 热态 660-890ms → 9ms） |
| **timeline** | **2323/2328/2395ms 恒定** | 同 | — | ❌ **P0：热态不降**（见 §7 P0-1） |
| **metrics** | **1735/1661/1659ms 恒定** | 同 | — | ❌ **P0：热态不降**（见 §7 P0-2） |
| sector_heat | 8587ms | 28-30ms | — | ⚠️ 冷态 8.6s（akshare 冷却触网，见 §3.4） |
| stock_hot_rank | 2897ms | 141-152ms | — | ⚠️ 冷态 2.9s（东财热搜首拉） |
| global_indices | 3116ms | 9-16ms | — | ⚠️ 冷态 3.1s（24h 磁盘缓存失效后首拉） |
| signal_510300 | 1905ms | 61-76ms | ≤2s | 冷态贴线（K 线首拉） |
| factor_health | 3124ms | 12-29ms | ≤2s | 冷态 3.1s |
| search / indicators / chart / realtime / factors / indices_meta / news / hot_plates | — | 9-249ms | ≤1s/≤2s | ✅ 达标 |

**结论**：热态除 timeline/metrics 外全达标；watchlist 冷态 P1-2 修复验证通过。**新发现 P0 级热态慢端点：timeline 2.3s、metrics 1.7s（均恒定不降）**。

---

## 三、功能验收结论

### 3.1 组合设计（design_id=519，quality=full）

**执行**：`POST /portfolio/design-async` `{risk_profile:balanced, capital:500000, mode:enhanced}` → task 406 → completed（refresh ~44s + LLM 报告 ~90s quick_ready）。

**数据正确性（核心验收）**：

| 校验项 | 结果 | 证据 |
|---|---|---|
| 今日涨跌幅 vs 实时行情 | **27/27 匹配**（mismatch=0） | `logs/round18/pct_verify.txt`（510300 0.42/0.42、515880 2.94/2.94、513050 -2.16/-2.16） |
| RSI/MACD vs factor_breakdown | rationale 引用的 RSI/MACD 与 factor_breakdown 值一致（510300 RSI 49.57、588200 RSI 23.8 超卖）；实时接口比对仅覆盖涨跌幅 | `pct_verify.txt` + design_detail.json |
| 方案结构 | 防御 14 只 + 平衡 14 只 + 进攻 9 只（含 CASH） | design 519 `strategies` |
| report_quality | **full，无「报告生成失败」占位符** | P0-1 修复验证 ✓ |
| degradation 透传 | `{mode:normal, pool_degraded:false, factor_matrix_empty:false}` | P2-8 修复验证 ✓ |
| plans 字段 | `daily_change_pct` 已透传（510300 0.42） | P0-4 修复验证 ✓ |

**审阅发现（专业投资者视角）**：

| # | 发现 | 级别 | 证据 |
|---|---|---|---|
| D1 | 报告「多因子评分（0~1）」注释与数据矛盾——表中 511090=-1.90、588200=1.28、159995=2.45（负值/超 1 与注释不符） | P2 | `design_report.md` 表格 + 注释 |
| D2 | 进攻方案卫星层仅 9%（预算 20% 未用满）+ 现金 27%——「锐意进取」定位与 42% 非进攻仓位偏差（候选池冷却期收敛所致，交易时段复测） | P2 | strategy3 layer_budget satellite 0.2 vs 实际 0.089 |
| D3 | design `etfs[].price=None`（实时接口有价 4.748）——候选池条目无 price 字段，S6 注入（strategy_design.py:389-393）取不到 | P1 | design_detail.json vs `/market/realtime` |
| D4 | 防御方案 510050 单只 20%、进攻 563360 21%+159915 19%——接近 30% 风控上限（合规但集中） | P3 | strategies 权重 |
| D5 | 报告正文「39只候选ETF主力净流出约0亿元」——fund_flow 数据缺失被描述为 0 亿（诚实但价值低） | P3 | design_report.md |

**优点**：涨跌幅/指标与最新行情完全匹配；三套方案风格区分合理（防御红利低波压舱/进攻芯片博弹性）；LLM 正文含具体市场数据（上证 3946.68/+0.32%、美债 4.72%、情绪 48.9）与量化操作纪律（企稳判定/止损红线/再平衡）；层预算合规（Σ≤1 留现金）。

### 3.2 on_exchange 策略检查（task 407，record 505）

**执行**：`POST /portfolio/strategy-check-async` `{capital:500000, portfolio_type:"on_exchange"}` → completed，coverage 11/11。

**审阅发现**：

| # | 发现 | 级别 | 证据 |
|---|---|---|---|
| D6 | **KDJ 显示错配**：`holdings_analysis[].factor_summary` 的 KDJ 显示归一化因子值（跨标的：159338 KDJ.K 4.25、159545 KDJ.D -9.54/KDJ.K -8.82、513010 KDJ.J -6.23、512000 KDJ.D -5.77——负数异常），而 `/market/indicators` 接口返回原始 KDJ 正常 0-100（159338 KDJ.K 84.77、159545 KDJ.K 14.74）——check 显示**未对齐指标源原始值** | **P0** | check_result.json vs `/market/indicators/{sym}` |
| D7 | 文案模板化 + **「基本面与动量共振」失真**：4 条 increase 理由完全同模板（仅因子分数字不同；decrease 模板措辞不同），且规则引擎无基本面数据（factor_availability 26/39 基本面因子多缺失）却措辞「基本面与动量共振」 | P1 | check_result suggestions |
| D8 | 512000「因子分 -0.19（中性），信号 sell，维持现状」+「关注 RSI 超卖加仓机会」——**技术卖出信号下 hold 且提示加仓，逻辑矛盾**（P0-3 阈值分级修复不完整） | P1 | check_result suggestions[7] |
| D9 | 全部 11 条 confidence=0.7 固定 + factor_availability 26/39（510300 为 25/39，13-14 因子缺失）却标 confidence=high | P2 | check_result |
| D10 | summary 诚实标注「LLM 分析超时（37s 未返回，已用规则引擎兜底）（最后错误: ReadTimeout）」+ risk_warnings 提示完整性受限 | ✅ | check_result |

**优点（P0 修复验证）**：P0-10 方向一致性（increase=cur×1.2 / decrease=cur×0.7，无 round16 的「增仓却降仓」矛盾）；P0-2 名称真实（中证A500ETF/沪深300ETF 非「510300 ETF」）；P0-3 因子分阈值分级（优/偏强/中性/弱）；LLM 超时兜底诚实标注。

### 3.3 三市场行情分析（A/HK/US）

| 链路 | A | HK | US | 结论 |
|---|---|---|---|---|
| 综合研判 llm-report/stream | ✅ **33.9s**（round16 77.8s，快 2.3 倍） | ✅ 35.2s | ✅ 29.9s | 全部 ok 无超时 |
| AI 投顾 llm-advice/stream | ✅ 22.9s | ✅ 27.3s | ✅ 29.1s | 同上 |
| 个股分析 symbol-analysis | ✅ 600519 茅台 36.1s | ✅ 00700 腾讯 36.7s | ✅ AAPL 苹果 37.8s | 同上 |
| ETF 分析 | ✅ 510300 50.8s | — | — | 同上 |
| 板块分析 sector-analysis | ✅ 半导体 25.7s | — | — | 同上 |
| 搜索补全 | ✅ 510300→沪深300ETF/茅台→600519/沪深300(index)→sh000300 | ✅ 腾讯→00700/09988→阿里巴巴-W/恒生→13 个/**恒生港股通→6 个**（round16 0 命中，P0-20 修复✓） | ✅ **Apple→AAPL**（round16 0 命中，P0-6 修复✓）/SPY→SPDR S&P 500 ETF/**道琼斯→DJI/SPX→标普500**（round16 0 命中，P0-22 修复✓） | **13 项全命中** |

**内容质量审阅（专业投资者视角，全文存 `logs/round18/stream_*_text.md`）**：
- A 股综合研判：数据与实测一致（创业板 +1.49%/科创50 +1.61%/沪深300 +0.58%）；逻辑清晰（横盘消化/风格扩散初期）；风险分级表 + 触发条件具体（美债 4.8%/上证 3900/4000 点位）；「7连板百花医药」与新闻列表交叉验证一致 ✅；
- US AAPL：**现价 304.91 与 `/market/realtime/AAPL` 完全一致**；PE 34.5/营收 +16%/毛利率 50.1% 具体；技术位 297.9-322.5 具体；短中长期操作建议分级 ✅；
- HK 腾讯：现价 461.6 与热门榜一致；Q2 营收 2047.9 亿 +11% 具体；**诚实标注「PE/PB 数据源不可用，本报告不涉及估值水平判断」** ✅（反假完成加分项）；
- **结论：三市场产出数据准确、认知合理，达到专业投资者可接受标准**；A 股 LLM 链路性能大幅改善（77.8s→33.9s）。

### 3.4 热点板块/个股（任务 5）

- **hot-plates：15 个板块完整**（chg/stock_count/lead_stocks 含领涨股 secu_code/name/change/up_reason/up_tags）✅（P0-17/18 验证生效）；
- **stock-hot-rank：A 10 只真实**（哈药股份 8.81/+6.53%）、**HK 5 只真实**（腾讯 461.6/-1.95%）✅；**US 0 只** ❌（`stock-hot-rank?market=US` 实测空，`_fetch_us_spot` 东财美股 spot 冷却；证据=本轮 API 实测，未落盘产物）——**P1 待修**（见 §7 P1-3）；
- **sectors/heat：20 板块 degraded=True，nonzero 仅 4/20** ⚠️（API 实测 + 容器内 `_ak_industry_sectors` 直测 5.98s 返回 0 行）——P0-17 主源 `_ak_industry_sectors`（sector_fetcher.py:59-63，东财行业 spot）依赖 akshare，冷却时 0 行，降级回财联社路径 → sign 失效（round16 R1 老问题）→ 名称回填命中率暴跌 → 16/20 涨跌幅 0。**P0-17 单点依赖 akshare 的冷却盲区**（见 §7 P1-2）。

### 3.5 自选功能（任务 6）✅

- 添加 512890 → id=23（201，price=1.159/-0.34% 与设计报告一致）；列表获取带实时价；DELETE 204 生效（列表 19 只恢复原状）；
- **发现**：POST 不传 `name` 时后端不回填名称（显示「512890」非「红利低波ETF华泰柏瑞」）——前端传 name 可避免，API 契约健壮性可改进（P2）。

### 3.6 持仓技术分析与综合信号（任务 7）

- **11 只持仓 signal 全部 data_available=True，且与策略检查 tech_signal 完全一致**（159338 buy/510880 buy/159545 sell/159516 buy/159992 hold/513120 hold/513010 hold/512000 sell/159869 hold/518880 hold/510300 buy）✅；
- RSI 交叉验证一致（159516 check 40.32 vs indicators 41.27 相近）；
- **❌ KDJ 显示错配 = D6**（check factor_summary 的 KDJ 是归一化因子值，负数异常；indicators 接口正常 0-100）——**P0**（见 §7 P0-3）。

### 3.7 资讯分级与智能分析（任务 8）✅

- headlines 21 条，level 分布合理（L5 哥伦比亚地震/7连板百花医药 重大事件、L4 清仓蓝光标巨额收益 公司级、L2 高盛美联储展望 常规）；stars 全 5（时间新鲜度口径 <1h，round16 已确认）；
- news-impact 智能分析质量好：`impact_scope=利好/全球咖啡产业链`、`affected_holdings=[]`（**判断消费ETF与咖啡无直接关联→影响中性，准确**）、summary 有实质分析、disclaimer 齐全 ✅。

### 3.8 因子模型（任务 9）❌ P0-12 遗留盲区

- `factors/active`：38 因子，**IC 值计算正常有区分度**（近1月 -0.4364/近3月 -0.7545/RSI -0.5636/折溢价 0.5636），但 **status 恒 no_data（sample=11 < MIN_IC_SAMPLES=30）**；
- 38 因子构成：27 no_data + 11 static（macro/china_specific/sentiment 政策类静态因子无 IC 正常）；27 no_data 中 21 个 IC 实际有效（sample_count 语义 bug 误标，见下） + 6 个真缺失（ic_value=null：tracking_error/shares_change/industry_diversification/institutional_holdings_change/ln_mcap/ln_float_mcap——round16 §3.13 已列）；
- **根因（P0-12 未完全落地）**：`ic_tracker._get_ic_sample_count_db`（ic_tracker.py:254-273）已改为 **DB IC 周期计数**（P0-12 修复 ✓），但 `factors.py:116` `_status_of` 与 `:289` sample_count **仍读内存 `registry._sample_counts`**（非零符号数 ≈ 11 只 ETF）——**端点未接入 DB 周期计数** → no_data 恒判，与事实（IC 实际有效）不符；
- **状态波动（运行时观察）**：会话早期查询 summary valid=9/warn=15/no_data=3（avg_ic=-0.1453），后续（IC 批次更新/候选池刷新后）稳定为 valid=0/no_data=27（avg_ic=-0.0958，`logs/round18/factor_state_wave.txt` 连续 4 次一致）——两次状态未落盘于同一产物，属运行时观察；页面状态随 IC 批次波动，用户看到「数据积累中」但实际 IC 已有效（误导）；
- factor-health：510300/518880/511090 三只 25-26/39 因子 live（healthy）✅；
- **发现**：因子对象字段名为 `code`（非 factor_id）；`zero_ratio` 为空 dict。

### 3.9 前后端断裂排查（任务 10）

**无 404 断裂**：前端 52 API + 4 SSE + 3 WS 全部命中后端路由（explore 子代理逐条比对 + 运行时抽查）。

**契约偏差修复验证**：B1（SymbolAnalysisRequest market 字段，analysis.py:182 已加）✅、B2（design_id）✅、B6（change_pct null）✅、B3（daily_change_pct 透传）✅、B4（WS realtime 数组消费，stores/market.js P1-1）✅。

**新发现**：
- **死端点 ~25 个**（前端 0 引用，见 §6）；
- **死 WS 端点 2 个**（`/ws/market/{symbol}`、`/ws/design-report/{session_id}`）；
- **asset_type=etf 契约健壮性**：`fetch_history('510300','etf','daily')` 直接 return []（仅处理 A/HK/US/index，无归一化）——前端传 'A' 不受影响（chart?asset_type=A 240 根正常），但第三方/未来调用方传 'etf' 静默空（P2）。

---

## 四、docs 落地核对（任务 11）

### round17-pending-items.md（5 项，commit 2e5da5c+bcee936）

| 项 | 静态（file:line） | 动态 | 结论 |
|---|---|---|---|
| P2-6 信号口径 UI | SignalPanel.vue:15「技术信号」+ TechnicalAnalysisModal 对齐 + DesignResult.vue:86 因子分列 + spec 存在 | — | ✅ 落地 |
| P2-8 degraded 前端消费 | task_manager.py:305-311 degradation 并入 + DesignResult/SectorHeatMap 提示条 | design 519 `degradation` 透传（mode=normal） | ✅ 落地 |
| P1-2 watchlist 冷态 | market.py:703 `_batch_for` timeout=2 + _skip_markets | **冷态 2.3s（≤3s 达标）** | ✅ 落地+实证 |
| LLM-1 排队提示 | DesignLoading.vue:104-113 分级提示 + task_manager.py:455-462 WARN | — | ✅ 落地 |
| P3-6 测试文件合并 | check_test_baseline.py:30 BASELINE=208 + 4 文件已并入 | — | ✅ 落地 |

### round16-container-acceptance-diagnosis.md（关键 P0，commit fab74d1）

| 项 | 动态验证 | 结论 |
|---|---|---|
| P0-1 报告占位符 | quality=full 无「报告生成失败」 | ✅ |
| P0-4 daily_change_pct 透传 | plans[].allocations[].daily_change_pct=0.42 | ✅ |
| P0-6 US 英文名搜索 | Apple→AAPL | ✅ |
| P0-9 timeline 含 check | timeline items[0]._type=check（record 505） | ✅ |
| P0-12 IC sample_count | **ic_tracker DB 计数已修，但 factors.py 端点未接入** | ⚠️ 部分（§3.8） |
| P0-17 板块热度东财源 | degraded 字段有；**akshare 冷却时 nonzero 4/20** | ⚠️ 部分（§3.4） |
| P0-19 HK K 线腾讯前置 | chart/00700 320 根 last close 461.6（round16 8.8s 空） | ✅ |
| P0-22 US 指数搜索 | SPX→标普500、道琼斯→DJI | ✅ |
| P0-23 成交额 rescue | 强势板块 159995/588200/515880 已入选设计（round16 被误杀） | ✅ |

**round16 问题清单 3.9-3.25 修复验证**：B1-B6 全修、3.10 双显示（timeline _type 区分）、3.11 矛盾建议（方向一致）、3.12 事件循环（P0-11 run_sync）、3.15 tracked_index（PnLDetailTable）、3.16 K 线红涨绿跌（P0-15）、3.18 港股搜索慢（P0-16）、3.19 板块热度（P0-17 部分）、3.20 HK K 线（P0-19）、3.21/3.24 指数搜索（P0-20/P0-22）、3.25 候选池误杀（P0-23）——**全部修复或已验证**。

---

## 五、测试防护盲区分析（任务 14）——为什么这些没被发现

| # | 盲区 | 本轮实证问题 | 根因（file:line） | 修复方向 |
|---|---|---|---|---|
| ① | **断言目标错（P0-12 端点侧）** | factors/active status 恒 no_data（IC 实际有效） | 既有 `test_z03_factors_active.py:148`/`test_round14_apply_design_factors.py:72`/`test_sentiment_factors.py:109` 均 mock 内存 `_sample_counts` 断言 status——断言与端点实际读源一致（所以全绿），但**该源语义错误**（非零符号数 ≈11 而非 IC 周期数）→ P0-12 端点侧缺陷被测试固化 | 端点测试改 mock DB 计数源，加「DB 周期数 >30 时 status=valid」断言 |
| ② | **verify_perf 链路不全** | timeline 2.3s / metrics 1.7s 恒定慢无门禁 | `verify_perf.py:25-26` THRESHOLDS 仅 watchlist/search/factor-health/symbol-analysis/综合研判 | 补 timeline/metrics 阈值（≤1s）+ pre-commit 接线验证 |
| ③ | **显示值与指标源无一致性断言** | check factor_summary KDJ（4.25/-9.54）≠ indicators 接口（84.77/14.74） | `strategy_check_worker` factor_summary 直接拼接归一化因子值，无「与 /market/indicators 同源同值」断言 | 加「factor_summary KDJ/RSI 与 indicators 接口一致」断言（负向：负数 KDJ → FAIL） |
| ④ | **sectors/heat 非零率断言未落地** | nonzero 4/20（round16 已指出，P0-17 未补测试） | round16 §5 盲区① → P0-17 只加了 degraded 字段，未加「非零率 ≥ 阈值」断言 | `sectors_heat` 测试加「nonzero_ratio ≥ 0.5 或 degraded=true 显式标记」断言 |
| ⑤ | **外部源守卫缺失** | US stock-hot-rank 0 只 | 无「US hot rank ≥ N」守卫（数据源依赖，交易时段） | 数据源健康页/启动守卫加 US hot rank 段（对标 P2-4 instruments 段守卫） |
| ⑥ | **内容质量无断言** | 策略检查「基本面与动量共振」失真 + 模板化；报告「0~1」注释与负值矛盾 | 规则引擎 reason 模板无「措辞与数据支撑匹配」断言；LLM 报告无「注释与数值一致」断言 | 策略检查测试加「reason 不含无数据支撑措辞」负向断言；报告生成器注释与数据同源校验 |
| ⑦ | **环境依赖结论无标记** | CLS/LCP/TBT 全局恶化（数据源冷却） | 无「性能结论区分环境 vs 代码」的测量协议 | verify_perf 加环境标注（交易时段/冷却期），冷却期结论打标「待复测」 |

**共性根因**：测试防护强调「测试绿」但缺乏「**显示值 = 指标源值**」「**性能门禁链路完整**」「**内容措辞与数据支撑匹配**」三层；上一轮指出的盲区（非零率断言、verify_perf 接线）在修复方案落地时未同步补测试（**修复不留痕**）。

---

## 六、冗余代码清理方案（任务 15）

### 第一批 P0 死端点（前端 0 引用，explore 子代理确认）

| 模块 | 端点 | file:line |
|---|---|---|
| market | GET `/realtime`、`/realtime/batch`、`/realtime/{symbol}`（前端只调 realtimePortfolio）、`/signal/debug/{symbol}`、`/fundamentals/{symbol}`、`/sentiment`、`/sectors/industry`、`/sectors/concept`、`/sectors/industry-cls`、`/sectors/{code}/stocks`、`/sectors/{plate}/popular`、`/sectors/rotation`、`/sectors`、`/wind` | market.py:25/33/51/395/447/489/494/505/517/523/529/535/540/654 |
| portfolio | POST `/apply-strategy`、GET `/designs`、DELETE `/designs/{design_id}`、GET `/strategy-checks` | portfolio.py:102/186/322/460 |
| news | GET `/macro`、`/global`、`/stock/{symbol}`、`/research/{symbol}` | news.py:15/20/25/30 |
| analysis | POST `/news-impact/stream`（前端用非 stream 版） | analysis.py:725 |
| admin | GET `/sources/connection-pool`、`/thread-pool`、`/llm/health`、`/factor-health`、DELETE `/config/{key}`、`/metrics` | admin.py:104/119/132/145/216/231 |
| factors | GET `/model` | factors.py:171 |
| WS | `/ws/market/{symbol}`、`/ws/design-report/{session_id}`（前端 3 条 WS 均不连） | ws.py:85/127 |

> ⚠️ 删除任何端点须同步删 `api-contracts/` 契约段并跑 `check_routes.py`；**其中 verify_e2e 依赖项（metrics 供 verify_e2e 使用）删除前须确认调用方**（metrics 被 verify_e2e 引用，**不能删**，只修性能）。/ws/market/{symbol} 若 B4 生态保留 WS 通道则标注「待前端消费」，不做硬删。

### 第二批 P1 死代码

- `portfolio.py:548` timeline 中 `json.loads(d.strategies_json)` 结果被丢弃（死代码；与全表查询叠加拖慢 timeline 至 2.3s，P0-1 修复即删）；
- 遗留文件：`_resume_build/`（非项目简历素材，整目录移除）、`docker-compose.diag.yml`（诊断 override，归档到 logs/round18/ 后删）、`scripts_diag_test_analysis.md`（历史工作笔记，归档）；
- `logs/` 历史诊断产物（png/txt/py 探针、lh_* 旧报告）——按 round16 P2-7 惯例归档到 `logs/round16/` 后清理根目录；
- 本轮诊断产物（logs/round18/）诊断完成后归档，不残留。

### 第三批 P2

- `frontend/src/api/index.js` 中与死端点对应的 api 方法（fundamentals/sentiment 等若前端无调用则删）；`analysisApi` 空对象（round16 §6 已列未清）复核。

---

## 七、优化与修复方案（P0-P2 分级，本份不实施）

> 对照 design-checklist 8 项：每方案标注证据链（file:line）、非兜底要求、真实调用点、复杂度审计、验证窗口。

### P0 级（功能正确性/性能，必做）

**P0-1 timeline 热态 2.3s 恒定（性能 P0）**
- 证据：`portfolio.py:516-518` `select(PortfolioDesign)` **无 limit 全表查询**（500+ 条，strategies_json 大字段物化）+ `:548` 对每条 `json.loads(strategies_json)` **结果被丢弃**（dead work，属实但非耗时主因）；`:521` `select(StrategyCheckRecord)` 同全表；实测 `task13_latency.json` timeline 2323/2328/2395ms 恒定。
- 修复：①删 `:548` 无用 json.loads（design_items 不使用 strategies 变量）；②查询加 `limit(limit+1)` + 子查询分页（先查 id/created_at 再回表）；③strategies_json 大字段 column defer（select 不含该列）或拆表；④check 表查询同加 limit 与列裁剪（显式覆盖 `:521`）。
- 验收：`time curl /portfolio/timeline` 热态 ≤300ms；`verify_perf.py` 补 timeline 阈值（≤1s）并接线。
- design-checklist：①探针=task13 实测 2.3s×3 ②证据=portfolio.py:516/548 ③窗口=— ④非兜底=— ⑤调用=DesignHistory/DashboardAiTools ⑥四态=— ⑦复杂度=删死计算+分页+defer ⑧模式=round14 盲区③。

**P0-2 metrics 热态 1.7s 恒定（性能 P0）**
- 证据：`admin.py:258-285` 拉 20 条完整 strategies_json + 每条 `json.loads` 遍历统计 + 2 次全表 count（PortfolioDesign 500+ 条）；实测 metrics 1659-1735ms 恒定（`task13_latency.json`）。
- 修复：①只 select 必要列（id/status/error_message/created_at + strategies_json 延迟加载——统计用 `SELECT json_extract` 或只取 non_cash 计数列）；②设计统计加 Redis/内存缓存 TTL 30-60s（对标 P0-8 designs_list 模式）；③count 用索引覆盖。
- 验收：`time curl /admin/metrics` ≤300ms；verify_perf 补 metrics 阈值。
- 复杂度：仅 DB 读，缓存一次写；无网络。

**P0-3 策略检查 KDJ 显示错配（显示正确性 P0）**
- 证据：check_result `holdings_analysis[].factor_summary` KDJ.K 4.25/KDJ.D -9.54（负数）vs `/market/indicators/{sym}` KDJ.K 84.77/14.74（正常 0-100）——factor_summary 拼接的是**归一化因子值**（factor_registry pct_rank 后），非原始 KDJ。
- 修复：`strategy_check_worker` factor_summary 生成处改用指标源原始值（对齐 `/market/indicators`），或标注「因子标准化值（0-100 分位）」并改字段名（KDJ_rank 等）——**二选一须与前端展示口径一致**（前端 TechnicalAnalysisModal 用 indicators 接口原始值，check 报告建议对齐原始值）。
- 验收：同标的 check factor_summary KDJ 与 indicators 接口一致（±1）；负向断言：KDJ 为负数 → FAIL。
- 测试：`test_strategy_check_*` 加「factor_summary KDJ 与 indicators 一致」断言。

**P0-4 factors/active status 接入 DB IC 周期计数（P0-12 补完）**
- 证据：`ic_tracker.py:254-273` 已修 DB 计数，但 `factors.py:116` `_status_of` + `:289` sample_count 仍读 `registry._sample_counts`（内存非零符号数 ≈11）→ no_data 恒判；实测 valid=9→valid=0 状态波动。
- 修复：`factors.py` 端点改为读 DB `FactorICRecord` 按 factor_code 周期计数（复用 `ic_tracker._get_ic_sample_count_db` 或异步查询）；`_status_of` 接收 DB 计数参数；候选池 refresh 时同步刷新该计数缓存。
- 验收：IC 周期数 ≥30 的因子 status=valid（round16 §3.13 实测 DB `factor_ic_records` 已累积 87278 条历史 IC 记录佐证）；页面「数据积累中」引导（P0-7）仅在真样本 <30 时显示；无状态波动。
- **测试迁移说明（必须）**：现有 `test_z03_factors_active.py:148`/`test_round14_apply_design_factors.py:72`/`test_sentiment_factors.py:109` 均 mock 内存 `_sample_counts` 断言 status——端点改读 DB 周期计数后这些断言目标失效，须同步迁移为 mock DB 计数源并保留「样本 <30 → no_data」原断言。
- 测试：`test_factors_*` 加「DB 计数 >30 → status=valid」断言（mock 计数源）。

### P1 级（体验/数据源，随轮次排期）

**P1-1 策略检查文案模板化 + 「基本面与动量共振」失真（P0-3 补完）**
- 证据：check_result suggestions 4 条 increase 理由完全同模板；规则引擎无基本面数据（factor_availability 26/39 基本面因子多缺失）却措辞「基本面与动量共振」。
- 修复：规则引擎 reason 生成按**实际可用的因子**组装措辞（无基本面因子时措辞改为「因子评分 + 技术信号」）；hold 分支删除「关注 RSI 超卖加仓机会」的加仓暗示（与 sell 信号矛盾，D8 同修）。
- 验收：increase 理由不含「基本面」措辞（基本面因子缺失时）；512000 sell 信号下 hold 理由不再含「加仓机会」；负向断言。

**P1-2 sectors/heat 非交易时段降级优化（P0-17 补完）**
- 证据：`_ak_industry_sectors`（sector_fetcher.py:59-63）依赖 akshare 冷却 0 行 → nonzero 4/20（财联社 sign 失效降级，round16 R1 老问题未根治）。
- 修复：①东财行业 spot 加**备用直连源**（push2delay 板块接口，绕 akshare）或②财联社 sign 失效时用东财板块名称映射增强（`_match_em_change` 命中率提升）；③nonzero_ratio < 0.5 时响应显式降级 + 前端提示已做（P2-8），加「待复测」标记。
- 验收：交易时段复测 nonzero ≥15/20；冷却期 degraded=true 显式标注（已有）+ 非零率测试断言落地。

**P1-3 US 热门股票 0 只（stock-hot-rank US 段）**
- 证据：`stock-hot-rank?market=US` 0 只；`_fetch_us_spot`（china_market.py:1065）东财美股 spot 冷却返回空；round16 记忆称可用但本轮 0 命中（冷却期）。
- 修复：①东财美股 spot 加备用源（新浪/levistock 美股 spot 降级链）；②加「US hot rank ≥ N」数据源守卫（对标 P2-4）；③冷却期返回显式空 + 前端「美股热门暂不可用」标注。
- 验证窗口：交易时段复测（美股盘中/盘后东财 spot 应有数据）。

**P1-4 design etfs[].price=None（数据完整性）**
- 证据：design_detail `etfs[].price=None` 而 `/market/realtime` 有价（4.748）——`strategy_design.py:389-393` S6 注入取 `pool_entry.get('price')/last_price` 均 None（候选池条目无价格字段）。
- 修复：候选池 `_refresh_impl` 条目补 price（从实时行情批量注入）或 S6 注入失败时回查 `/market/realtime`（超时 3s 批量）。
- 验收：design 详情的 price 非 None（与 realtime 一致）；前端持仓表价格列不再「—」。

### P2 级（契约健壮性/文档/治理）

**P2-1 asset_type 归一化**：`fetch_history` 对未知 asset_type（'etf'/'fund'）归一化到 'A' 或显式 400（现静默 return []）；`get_history`/chart 端点加资产类型校验。
**P2-2 自选添加名称回填**：POST watchlist 无 name 时按 symbol 查 instruments/缓存回填名称（对标 P0-2 名称回退）。
**P2-3 报告注释与数据同源**：design_report 生成的「多因子评分（0~1）」注释改为「因子综合分（可负/可超 1，区别于技术信号）」或按实际分布生成；LLM prompt 约束注释口径。
**P2-4 进攻方案卫星层/现金**：候选池正常时卫星层预算用满（≥15%）；现金上限按风格差异化（进攻 ≤20%）；冷却期标注「候选池收敛，交易时段复测」。
**P2-5 Lighthouse 复测基线**：交易时段复测五页，区分环境 vs 代码；home CLS 0.389 专项修复（round14 P1-G 从未实测，纳入验收）；echarts 分包（vendor 拆分）。
**P2-6 死端点清理**（按 §6 第一批，先确认 verify_e2e/契约依赖再删）。
**P2-7 confidence 标定（映射 D9）**：策略检查 confidence 不再固定 0.7——按因子填充率（factor_availability 26/39）与信号一致性分级（如 <70% 填充 → confidence=medium 且说明）；负向断言：factor 填充率低时 confidence 仍 high → FAIL。

> **编号体系说明**：本轮 P0-1..P0-4 / P1-1..P1-4 / P2-1..P2-7 为**本轮独立编号**；文档中「P0-x 修复验证」字样指 round16 编号（fab74d1 已实施，§4 验证），两者不混用。

---

## 八、实施顺序与验收口径

1. **P0-1/P0-2**（timeline/metrics 性能）→ verify_perf 补阈值 → 实测 ≤300ms；
2. **P0-3**（KDJ 显示对齐 indicators 原始值）→ 负向断言；
3. **P0-4**（factors status 接入 DB 计数）→ valid 恢复 + 无波动；
4. **P1-1**（策略检查文案去模板 + 失真措辞）→ 负向断言；
5. **P1-2/P1-3**（sectors/heat 备用源 + US hot rank）→ 交易时段复测；
6. **P1-4**（design price）→ 详情 price 非空；
7. **P2 批**（归一化/名称回填/注释同源/进攻层/Lighthouse 复测/死端点/confidence）随轮次；
8. **P3 观察项**（D4 单只集中度、D5 fund_flow 净流出描述）不排期，交易时段复测后再定；
9. **性能软门禁记录**：本轮「已知性能债」清单（见下）。

> **每项 DoD**：测试绿 + 现实证真（真实调用点/非兜底数据/内容断言）+ design-checklist 8 项对照 + 性能记录；外部源项交易时段复测。

## 附：本轮已知性能债清单（软门禁记录，后续排期）

| 路径 | 实测 | 阈值/目标 | 性质 |
|---|---|---|---|
| timeline | 2.3s 恒定 | ≤300ms | P0（热态，代码问题） |
| metrics | 1.7s 恒定 | ≤300ms | P0（热态，代码问题） |
| home Lighthouse | perf 46 / CLS 0.389 | ≥60 / <0.1 | 存量（P1-G 从未实测）+ 冷却期扩散 |
| sector_heat 冷态 | 8.6s | ≤3s | 数据源冷却（交易时段复测） |
| watchlist 冷态 | 2.3s | ≤3s | ✅ 已达标（P1-2） |
| 预热 | 9.0s | ≤25s | ✅ 达标；fetch_macro_snapshot 9.0s 待优化 |
