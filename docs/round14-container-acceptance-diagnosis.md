# Round14 容器全链路验收与诊断报告（2026-08-10）

> **性质**：全链路验收 + 性能诊断 + 质量审阅的报告与方案文档（**仅记录结论与方案，不实施**）。
> **执行环境**：Docker prod profile（backend:8000 / frontend:80 / redis），2026-08-10 最新镜像构建（backend `0e0c5cac5c6d` / frontend `2cc46a233462`），老镜像回收 ~4.7GB。
> **验收方法**：真实 API 链路（HTTP + SSE）+ 生产容器内探针 + Lighthouse + 因子/资讯/设计报告内容审阅。
> **基线参照**：AGENTS.md 软门禁阈值（watchlist ≤3s、搜索 ≤1s、factor-health ≤2s、首页 perf ≥60 / CLS <0.1）；verify_e2e 263/276。

---

## 1. 结论速览

| # | 结论 | 严重度 |
|---|---|---|
| 1 | **组合设计可用**（design 364 → 494，LLM full 报告），但 **market_context 数据缺口**：sector_momentum=[]、benchmark_stocks=[]、fund_flow 全 0、institutional_consensus=0 | P1 数据缺失 |
| 2 | **策略检查 LLM 链系统性超时**（今 7 次 5 次 ReadTimeout）→ 规则引擎兜底；根因 provider 35s 无响应 + 90s 预算被 1 轮双 provider 失败耗光（71.5s）重试无空间 | **P0 功能降级** |
| 3 | A股/港股/美股行情分析全链路**可用**（综合研判/投顾/个股/ETF/板块/概念/指数/新闻影响/搜索补全）；SSE 单次 45-170s，串行会互斥排队超时 | 提示 |
| 4 | 热点板块/个股/板块热度**加载正常**（A 15 条 / HK 10 条 / 热度 20 条） | 通过 |
| 5 | 自选增删查**功能通过**，但**列表实时价格枚举超时降级 DB-only**——后端丢 realtime 字段，首次 8.5s | **P1** |
| 6 | 持仓技术分析/信号**可用且合理**，但 3/10 与策略检查信号不一致、因子覆盖 27/39 | P1 |
| 7 | 资讯分级 frame 合理（level 重要性 + stars 新鲜度），词典盲区致部分重要新闻漏标 | P2 |
| 8 | 因子模型页 **34% 因子"负向 IC 已下架"**（样本数 0 却有 |IC|≥0.02）——伪信号下架主力技术因子 | **P0 数据可信度** |
| 9 | 前后端断裂：**apply-design 应用方案恒空操作+前端假成功**（P0）+ **watchlist 价格降级字段丢失**（P1） | **P0/P1** |
| 10 | docs 5 份方案落地核对：precommit/round12/round13 基本完整；round11 4 项残留、round10 2 项未完整 | P2 |
| 11 | 前端 Lighthouse：**首页 perf 0.58 / CLS 0.389** 不达标（summary-grid 区位移）；portfolio TBT 510ms | P1 |
| 12 | 后端冷缓存首请求 3-8.5s（watchlist 8.5s / calculate 5s），缓存命中后 <150ms | P2 性能债 |
| 13 | 测试防护盲区：单测 mock 真实函数 / 降级路径被当正常 / 一致性测试用"同输入"前提 / verify_e2e 只验 200 不验内容 | P0 机制 |
| 14 | 冗余代码残留 6 处（低危） | P3 |
| 15 | 首页/因子页盈亏数字**无涨跌色**：当日/累计盈亏全部中性深色——scoped `.summary-value`/`.stat-num` color 覆盖全局 `.text-up/.text-down`（红涨绿跌失效；因子页警告色正常） | **P1 视觉** |
| 16 | 组合方案设计展示 4 项问题：①入选理由「方向」标签概念粗映射（碳中和/科创新能源→电力设备）；②**现金仓位仅引擎表格汇总行有**，LLM 正文/卡片 header 无；③方案卡片今日涨跌幅缺失显示"—"（非交易时段 dcp=None 未显性化）；④入选理由超长（RSI+MACD+动量+市态拼接） | **P2** |
| 17 | 因子模型页：①IC 排序表**缺中文名列**（后端已返回 name 未用）；②tracking_error/shares_change **两个因子永无数据**（DB 84001 条 IC 记录中 0 条）——IC 循环传 K 线缓存缺 benchmark_close/shares_change_20d | **P2** |
| 18 | 标的分析：**输入搜索触发下拉后直接点「分析」按钮，下拉不关闭**（doAnalyze 从不关 showDropdown，仅点下拉项才关）——22 测试全绿但漏此路径 | **P2** |
| 19 | 板块热度页 **15/20 板块涨跌幅恒 0**：靠东财名称回填（`_match_em_change`），财联社题材名与东财板块体系不匹配（民爆/光通信/冰雪产业等东财无此板块） | **P2** |
| 20 | 自选列表加载慢（首次 enrich 8.5s 超时降 DB-only）+ 新增"江波龙"（301317 股票）一直"行情加载中" | **P2** |
| 21 | 港股标的分析指数补全**不全**：前端 useMarketSearch 对 index/sector 模式丢弃 market → 后端 `_search_indices` 无 market 过滤 + `limit(10)` → A 股指数占满，港股指数排不进 | **P2** |
| 22 | 港股自选 **2/3 标的行情加载中**：`_watchlist_enrich_items` 只对 A 走批量，HK 走 per-item `_realtime_one` 3s 截断（HK 降级链 `_timeout=15`）→ 必超时；实测 `get_realtime_batch` HK 批量 1.0s 出 3 只 | **P2** |
| 23 | 港股热门个股**混入基金/ETF/权证**：`hk_hot_fetcher` 用 `fs=m:128` 全市场（含基金 03033/盈富 02800、杠杆 07709、权证），`parse_hk_hot_stocks` 无类型过滤 | **P2** |
| 24 | 美股/港股综合研判**内容雷同**：build_full_context news 段无条件用 `get_news_headlines`（A 股财新/宏观），US/HK 与 A 注入同一批 A 股新闻（实测首条均"工银瑞信史宝珖"）；未用 `fetch_global_news`（道琼斯/CNBC 全球新闻源） | **P2** |
| 25 | 美股数据源缺失 4 项：①热点板块 US 返回空（get_hot_plates 明示"暂不支持"）；②板块分析按钮港股/美股置灰（sector 仅 A，round10 P2-T 有意禁用）；③美股指数选择推荐项报错（P2-AG 未修：搜索无 market 过滤返回 A 股指数，美股模式 realtime 失败）；④标的分析基本面 PE/PB 恒"数据源不可用"（fetch_current_pe_pb L281 `_is_a_stock` gate 只支持 A 股） | **P2** |

---

## 2. 重大问题详析与根因

### 2.1 策略检查 LLM 系统性超时（P0）

**现象**：`/portfolio/strategy-check-async` 今日 7 次执行 5 次 `ReadTimeout`，summary 明示"LLM 分析超时（90s 未返回，已用规则引擎兜底）"；规则引擎输出模板化（confidence 恒 0.7、文案重复 5 类）、`factor_availability 27/39`、`industry=""`。

**链路与根因**（docker logs 实证 + 代码审计）：
```
05:45:45 opencode_zen failed after 35.4s   ← provider 35s 单次超时内无响应（llm.py:1425 request_timeout=35）
05:46:21 deepseek failed after 36.1s       ← 同轮第 2 provider 也 35s 无响应
05:46:39 LLM analysis interrupted after 90.0s (CancelledError) — rule fallback
```
- **主 LLM 链路**（产生报告核心）：`portfolio_service.strategy_check`（L764）→ `wait_for(generate_strategy_check_report, timeout=_llm_timeout_for(data_quality))`——完整数据 **90s** / partial 30s / all_empty 15s（L562-575，round9 P0-5 60→90）；内部 `generate_strategy_check_report`（llm.py:1333）→ `get_agent("strategy_check").run_json(request_timeout=35.0, max_retries=1)`（L1418-1425）→ `llm_complete_with_system`（llm.py:624）timeout=35 覆写 provider 240s（L667）。
- **真正根因 = provider 端无响应 + 预算-重试不匹配**：第 1 轮双 provider 失败耗时 35.4+36.1=**71.5s**，90s 预算仅剩 18.5s，第 2 轮（max_retries=1）刚开始即被 90s 截断 → CancelledError 兜底。**不是外层截断**（90s ≥ 35s×2，配置本身配套），而是 **provider 35s 内无响应**（外部 LLM 服务慢/网络问题，与 round14 EM 网络问题同源）。
- **附加注释链路（非主报告）**：`strategy_check_worker.py:55` `_generate_check_llm_report` wait_for 30s + `:272` `_generate_check_llm_comment` wait_for 20s——调 `llm_complete`（provider 240s 未被 35 覆写），30s/20s 截断确实存在，但**失败仅丢 `llm_comment` 附加字段，不影响主报告**（L194-200 非阻塞注释）；round14 文档旧版把这两处误当主因，已修正。
- **注释误导**：llm.py:1422-1425 注释"与 P0-F 的 30s 外层预算配套"过时错误——外层实际 90s（完整档），注释未随 round9 P0-5 更新。

**影响**：策略检查对用户等于无 LLM 智能分析，仅规则摘要；且报告仍 mark "completed"（降级被当作正常完成）。

### 2.2 apply-design 前后端断裂（P0）

**现象**：前端"应用此方案"点击后 toast "已应用 xxx 方案"，但持仓**零变化**（HTTP 200、无报错）。

**根因**：
- 前端 `DashboardAiTools.vue:689` `applyPortfolioDesign(plan)` 把 **plan 对象**（`{style, allocations: [{symbol, name, layer, target_weight}]}`）原样 POST；
- 后端 `portfolio_service.py:1583-1586` 期望 **`{portfolio_type, symbols: [str], weights: {sym: w}}`** —— plan 无 symbols/weights → `symbols=[]` → 返回 `{"symbols": [], "message": "组合设计中没有指定持仓"}`（200）；
- 前端不检查响应体，直接 toast 成功 → **假完成**。
- 契约 `api-contracts/portfolio/apply-design.md:98` checklist 该项竟标 **✅**（备注"DashboardAiTools.vue:622 传入完整 plan 对象"——把 bug 姿势当通过标准，且备注行号 622 过时，实际代码在 685-697）。

### 2.3 watchlist 实时价格静默缺失（P1）

**现象**：`GET /market/watchlist` 14/14 无 realtime 价格（后端 enrich 超时降级丢字段）；首次请求 8.5s。

**根因**：
- `market.py:803` enrich 整体 5s 超时 → DB-only 降级（**丢 realtime 字段**，响应无 realtime 键）；
- 慢源链：mootdx/akshare/dongfang 全熔断（status=open）→ 批量行情失败 → HK/US per-item 3s×N 超预算；
- 前端 `WatchlistPanel.vue:127-134` 已有 `v-if="item.realtime"` + v-else "行情加载中（数据源弱）"**降级占位**——真实缺口在后端丢字段，前端占位已实现。

### 2.4 因子伪 IC 下架（P0 数据可信度）

**现象**：/factors/active 中 13/38 因子（34%）warn"负向预测已下架：|IC|≥0.02，样本数 0"——**样本数 0 但有显著 IC**；技术主力因子（sma_5/10/20/60、bollinger、atr、vwap、kdj）全部被下架。

**根因**：`routers/factors.py:116-120` 对 `ic_val` 判 `abs(ic_val)>=threshold` 时无**最小样本保护**；`ic_val` 来自 `registry._last_ic_batch`——样本数 0 时 IC 被计算/回填（可能来自单样本或陈旧序列），形成伪强负相关。

**影响**：因子模型页主力因子全部标记"已下架"，与设计/策略检查实际使用（factor_summary 仍填 RSI/MACD）相矛盾，用户对因子可信度丧失信心。

### 2.5 市场数据缺口（P1）

- design 494 `market_context.sector_momentum=[]` / `benchmark_stocks=[]` → **LLM 报告 §2 大量"板块轮动剧烈""行业分化"论断无板块动量数据支撑**（仅由 ETF 涨跌幅推断）；
- `fund_flow` total_net_inflow=0.0（positive/negative 全 0，total_symbols=26）→ 数据源采集失败兜底；
- `institutional_consensus=0 / margin_change=-1 / volume_ratio=1.0` → 疑似占位值；
- 根因：设计时刻 `_compute_industry_momentum` RemoteDisconnected 失败 ×N（容器 EM 连接被断，与 round9 C4 同源）。

### 2.6 信号跨端点不一致（P1）

- 直接 `/market/signal/{sym}` vs 策略检查 `holdings_analysis.tech_signal`：**7/10 一致、3 只反向**（159338 buy vs HOLD、510880 hold vs BUY、159992 hold vs HOLD 口径 +159545 等）；
- 根因：holdings_analysis 用因子综合信号（factor_score+技术）、/market/signal 用纯 K 线；**测试 test_signal_consistency.py monkeypatch 固定"同输入"掩盖了真实链路数据差异**。

### 2.7 前端首页性能不达标（P1）

- Lighthouse：**home perf 0.58**（CLS 0.389 严重超 0.1、TBT 490ms、LCP 3.2s、主线程 2.5s+4 long tasks）；
- CLS 主源 `div.summary-grid`（总仓位/盈亏汇总卡片区，boundingRect 高 916px）——数据到达后从 Skeleton/空态**撑开布局**；
- portfolio 0.78（TBT 510ms）、market 0.87、news 0.97。

### 2.8 后端冷缓存性能（P2 已知性能债）

- 首请求（冷缓存）：watchlist 8.5s / calculate 5.1s / stock-hot-rank 3.3s / indices-global 3.9s / search 6.25s（极端）；
- 第二次：28-151ms（TTL 缓存命中）；
- 根因：预热（6.1s）覆盖有限 + 慢源（mootdx/akshare/dongfang 熔断）首访拉取；
- 对照 AGENTS.md 软门禁：搜索 ≤1s（冷 6.25s 超）、watchlist ≤3s（冷 8.5s 超）。

### 2.9 首页/因子页盈亏数字涨跌色失效（P1 视觉）

**现象**：首页 SummaryCards 的"当日盈亏/累计盈亏"全部显示中性深色，无红涨绿跌（截图 1150×519 像素分析：红像素 0、绿像素 13——仅图标零星）；累计盈亏卡"总累计盈亏 -X"、"场内累计盈亏 +Y"同色。

**根因**（CSS 特异性）：
- 全局 `theme.css:516-517`：`.text-up { color: var(--color-text-up) }` / `.text-down { color: var(--color-text-down) }`（红涨绿跌，变量 L115-116 定义正确）——特异性 **(0,1,0)**；
- `SummaryCards.vue:270-274` scoped 规则 `.summary-value { color: var(--color-text-primary) }` 编译后为 `.summary-value[data-v-xxx]`——特异性 **(0,2,0)** **大于**全局 .text-up；
- 5 处盈亏数字（L23/L36 当日×2、L78/L98/L118 累计×3）虽绑定 `text-up`/`text-down` 类，但被更高特异性的 `.summary-value` color 覆盖 → 全部渲染为中性 `--color-text-primary`；
- 同类检查（全仓 8 组件）：**同型问题共 2 处**——
  1. `SummaryCards.vue:270-274` `.summary-value`（上文，首页 5 处盈亏）；
  2. `FactorModelView.vue:665-669` scoped `.stat-num { color: var(--color-text-primary) }` 同样 (0,2,0) 覆盖 L31 `text-up`（有效因子数）、L61 `avgIcClass`（平均 |IC| ≥0.03 的 text-up 分支）——**L38 `text-warn` 不受影响**（组件内 L923 已有 scoped `.text-warn`，定义在 `.stat-num` 之后，同特异性靠后胜出，警告色正常）；即因子页实际失效 2 条绑定路径（L31 全部 + L61 高值分支）；
  - 其余 6 组件不受影响：WatchlistPanel 用**私有** `.up/.down` 类（L463-464 自带 color，不依赖全局 .text-up）；SectorHeatMap `.row-change`/`.row-rank-chg`（L282/284）无 color 定义；TechnicalAnalysisModal/DesignResult 宿主为裸 `<span>`；PnLDetailTable/PortfolioManager 的 `<td>` 无 scoped color。

**影响**：首页核心指标与因子模型页头部统计的可读性受损（方向/状态失去红绿编码；黄色警告色正常），色弱用户唯一依赖 ± 符号仍保留（`signed()` L165-168）——降级不致命但违背红涨绿跌约定。

**来源**：round6 F24 重写卡片布局时引入的回归（L194-196 注释含 F24 改动历史）；jsdom（`vitest.config.js css:false`）不层叠 CSS → 单测断言 class 存在但颜色从未被验证 → 回归逃逸。

### 2.10 组合方案设计展示问题 4 项（P2）

**现象**（用户反馈 + design 494 实证）：
1. 入选理由首句「方向」叙述（如"医疗器械ETF华夏 — 医药生物方向"）部分标签**概念粗映射**；
2. 全文报告（LLM 正文）**不展示现金仓位**，方案卡片 header 也无；
3. 方案卡片「今日涨跌幅」列全显示"—"（dcp=None）；
4. 入选理由超长（每句 RSI+MACD+技术面评分+动量+综合信号+市态拼接，可读性差）。

**逐项根因**：
1. **方向标签**：`rationale.py:157-173` 的「{industry}方向」句式来自 `etf_classifier.py` 关键词规则。已验证：医疗器械→医药生物（L66）、科创创新药→医药生物（L68）**符合申万分类，合理**；但 碳中和→电力设备（L62）、新能源→电力设备（L59/144）是**概念→行业粗映射**——碳中和/科创新能源指数成分含电力设备（光伏/电池）**也含环保/公用事业/汽车**，归"电力设备"过窄（design 494 实测：589960 科创新能源 tracked_index 缺失走 name 匹配置信度 0.70）。rationale 的 O23 可信度机制（宽基覆盖/低置信兜底）本身设计正确，问题在**分类表标签粒度**。
2. **现金仓位**：`design_report.py:92-103` plan_tables 有「现金仓位」汇总行（设计 494 实测 `| 现金仓位 | 20% | 15% | 39% |`）；但 `llm.py:1766-1772` prompt 明确"不需要重述 ETF 标的/权重/理由" → **LLM 正文无现金**；`DesignResult.vue:48-54` 卡片 header 只显示 ETF 数量/核心/卫星/防御%，**无现金%**；`llm.py:1908-1920` plan_tables 为空时 fallback 也无现金。**衍生 bug**：卡片 header "X 只 ETF"（`DesignResult.vue:48` `allocations.length`）把 CASH 计入——设计 494 实测防御型 allocations=10 但 ETF=9（CASH=1）→ 显示"10 只 ETF"错误计数。
3. **今日涨跌幅**：`strategy_design.py:367-404` 三源注入 daily_change_pct，设计 494 全部 None（round14 非交易时段/数据源熔断）→ 前端 `DesignResult.vue:80-84` 显示"—"。`design_report.py:189-191` 引擎表格已显性化"数据源不可用"（P1-4），**前端卡片未同步**。
4. **入选理由超长**：`rationale.py:134-250` 拼接 5-6 个句子（资产介绍+方向+RSI+MACD+技术面评分+动量+综合信号+市态）——信息全但冗长；方向句「名称—方向」与后面 RSI 等技术句混排，可读性差。

**影响**：方案设计展示是核心交付面——现金仓位缺失误导用户（看不到资金分配全貌）；涨跌幅"—"无法区分"数据缺失"与"0 涨跌"；理由超长降低可读性；方向标签粒度不准影响信任。

### 2.11 因子模型页：IC 表缺中文名 + 两因子永无数据（P2）

**现象**（用户反馈 + 实证）：
1. IC 排序表只有「因子代码/分类/IC 值/有效性/样本数」5 列，无中文名列（截图 26 行全英文 code）；
2. `etf.tracking_error`（跟踪误差）与 `etf.shares_change`（规模变化率）在因子页显示"无数据"——DB `factor_ic_records` 84001 条记录中**这两个因子 0 条**（其余 31 个 distinct factor 都有），summary `no_data: 2` 即它们。

**逐项根因**：
1. **中文名列缺失**：后端 `/factors/active` L268 已返回 `name`（YAML `factor_definitions.yaml` 中文名优先，`_get_factor_name` 兜底；38 注册因子全部有中文名）；前端 `FactorModelView.vue:105` IC 表只渲染 `f.code`，未用 `f.name`——**纯前端遗漏**（分类卡片 L184 已用 f.name）。
2. **tracking_error/shares_change 永无数据**（设计缺陷，多层根因）：
   - **主因**：`factor_registry.compute` L1419-1421——`market_data` 外部注入时 `pass`，**symbol_extra 完全被忽略**（benchmark_close/shares_change_20d 只在 `_fetch_market_data` 路径 L1327-1336 Z04 合并）；
   - **触发**：IC 循环（`main.py:446`）`compute(_syms, market_data=_kline)` 传 K 线缓存（仅 close/high/low 等列，无 benchmark_close/shares_change_20d）→ 两因子对每只 ETF 返回 0.0；
   - **放大**：`ic_tracker.compute_periodic_ic` L169 `if abs(val) < 0.001: continue`——0.0 全跳过；tracking_error 合法值 0.001~0.02（映射外 ETF 无 benchmark_close 返回 0）→ 有效样本 <3 → L191 `len(common) < 3: continue` → **永不产生 IC**；
   - **对比**：正常路径 `market_data_hub.py:564` `compute(symbols, symbol_extra=symbol_extra, market_data=cached_kline)` 传 symbol_extra → tracking_error/shares_change 在因子评分里有值（`institutional_holdings_change`/`industry_diversification` 有 IC 记录且 max_samples=1849 佐证同族因子正常）。

**影响**：因子页两个核心质量因子（跟踪误差/规模变化）永远无 IC，用户无法评估其有效性；IC 表缺中文名降低可读性（33 个技术/风格因子 code 需对照记忆）。

### 2.12 标的分析：点「分析」后自动补全下拉不关闭（P2）

**现象**（用户反馈，截图 1746×319 顶部搜索区）：输入标的代码/名称 → 补全下拉弹出 → **直接点「🔍 分析」按钮** → 分析开始（loading）但**下拉框一直挂着不收回去**。

**根因**（代码审计 + 单测复现）：
- `UnifiedAnalysis.vue` 下拉显示由 `activeSearch.showDropdown` 控制（L39 `v-if`）；关闭逻辑集中在 composable `useMarketSearch.selectSearchItem`（L140-146，点下拉项路径）；
- **`doAnalyze`（L358）从不关闭 `showDropdown`**——点「分析」按钮（L52 `@click="doAnalyze"`）路径直接进入分析，`showDropdown` 保持 true → 下拉常驻；
- L176 的 `showDropdown=false` 只在 `resetSearch`（切 tab）时执行，分析路径不覆盖；
- **测试盲区**：`UnifiedAnalysis.spec.js` 22 用例中 `pickSearchItem` 场景（L158-173）只断言输入框回显/符号解析，**不断言 `showDropdown` 关闭**；点「分析」按钮路径无任何用例——22 全绿但 bug 逃逸（临时复现测试 `doAnalyze 后 showDropdown 仍 true` FAIL 证实）。

**影响**：分析加载期间下拉遮挡页面、视觉污染；用户需手动点输入框外或 Escape 才能收回——交互缺陷。

### 2.13 板块热度页涨跌幅恒 0（P2）

**现象**（用户反馈"热点板块排行里的涨跌幅为 0 未解决"，截图 1775×1149 为「板块热度」tab 20 行）：多数板块（上海国资/民爆/光通信/食品饮料/冰雪产业等）涨跌幅显示 +0.00%，少数（乳业奶粉/MLCC/黄金概念）有真实值。

**根因**（宿主机+容器实测）：
- heat 端点 `sectors/heat`（market.py:549-583）change_pct = 东财名称回填 `_match_em_change`（L585-602：精确/包含/首段三级匹配）；未命中兜底 0（L579-581）；
- **东财板块体系无财联社题材板**：全量抓取东财行业 496 + 概念 504 + 地域 31 = 1031 个板块，民爆/光通信/PTA/钛白粉/制冷剂/猪肉/证券/食品饮料/乳业 **全部不存在**（仅冰雪经济/精准诊断/啤酒/上海板块/其他通信设备等近似）——名称匹配任何取值都无法覆盖；
- 实测 `fetch_em_sector_changes` 203 条映射（pz=500 截断）对 heat 20 板仅命中 5（乳业奶粉、MLCC、CRO/CMO、绿色电力、国资云，CRO/CMO 计 1 个）；容器内 push2.eastmoney.com 部分断连（EM 问题，round12 已诊断）加剧；
- **根治验证**：财联社 `plate_list` 接口（`/web_quote/plate/plate_list`，type=industry 54 + concept 399 = 453 板，page=500）带 `change` 涨跌幅 + `secu_code`（如 cls80424）——**与 heat 的 `plate_code` 同源同码**，按 code 精确 join 实测 **20/20 全部命中**（光通信 0.0077/民爆 -0.0114/食品饮料 -0.0081 等真实值，含负涨跌）。

**影响**：板块热度页核心信息（涨跌幅）大量缺失显示 0.00%，用户无法判断板块强弱，信任受损。

### 2.14 自选列表加载慢 + 江波龙行情加载中（P2）

**现象**（用户反馈，截图 1783×784 自选列表）：①自选列表加载特别慢；②新增"江波龙"（301317 创业板存储芯片股）后一直显示"行情加载中"。

**逐项根因**：
1. **列表慢**：watchlist 实时 enrich（`_watchlist_enrich_items` market.py:624-770）整体 5s 超时（P0-4）→ 数据源慢（mootdx/akshare/dongfang 熔断）时批量失败 `_skip_a_per_item`（L660）→ A 股 DB-only、**未注入 `realtime:null`** → 前端显示"行情加载中"占位（实际已降级）；首次 8.5s（round14 诊断 P1 确认）。注意**并发结构已存在**（L661 gather，非旧版串行）；
2. **江波龙 301317 行情加载中（asset_type 归一化缺失 + 超时失配）**：
   - 搜索结果返回 `type:"stock"`（market.py:283）→ 添加入库 asset_type="stock"（`add_watchlist` L1542 透传前端值）；
   - `_watchlist_enrich_items` 的 `_a_items` 过滤（L644 `(it.asset_type or "A") == "A"`）**只认 "A"** → "stock" 被排除出 A 股批量路径（`get_realtime_batch` 4s）→ 走 per-item `_realtime_one`；
   - `_realtime_one` 外层 `wait_for(timeout=3)`（market.py:639）截断，而 `get_asset_realtime("301317","stock")` else 分支（market_service.py:1216 `fetch_a_stock_realtime`，A 股行情降级链）`_timeout=15`（market_service.py:1173：`8 if asset_type=="A" else 15`，stock≠A 取 15）→ **3s vs 15s 必超时** → realtime None → 前端"行情加载中"。（注：`add_watchlist` 入库时 market_service.py:1536 也已用 stock 拉过一次 realtime——3s 截断发生在每次 enrich 阶段，是独立于入库的重复调用。）

**影响**：自选是高频入口，慢加载 + 新股行情缺失直接影响使用。

### 2.15 港股标的分析指数补全不全（P2）

**现象**（用户反馈，截图 1945×389 搜索区）：港股 tab 下标的分析切**指数模式**，自动补全下拉只列出少量指数，港股指数（恒生/国企/红筹等）缺失或排不上。

**根因**（代码审计）：
- 前端 `useMarketSearch.js:82`：`...(mkt && kind === 'all' ? { market: mkt } : {})`——**只有 `kind==='all'` 才传 market**；index/sector 模式（`kind='index'`/`'sector'`）**丢弃 market** → 港股 tab 搜指数不过滤 HK；
- 后端 `_search_indices`（market.py:225-250）：**无 market 参数** + `limit(10)`（L242）——查全部 `indices_meta`（A股约 562 + 港股 38 + 行业/概念数百，scripts/sync_indices_meta.py docstring 声称数），港股指数被 A 股占满前 10 截断；`IndexMeta` 表依赖 `scripts/sync_indices_meta.py` 手动同步（main.py 启动只调 `sync_instruments_table`，**未调 indices 同步**）——表可能不全/过期加重；
- 截图仅 4 文字带（2 个下拉项）——limit(10) 且匹配度排序后港股指数难进。

**影响**：港股指数分析入口残缺（恒生/国企指数搜不到），与 A 股 tab 指数补全体验不一致。

### 2.16 港股自选 2/3 标的行情加载中（P2）

**现象**（用户反馈，截图 1874×568 港股自选列表）：3 个港股标的中 2 个一直"行情加载中"（截图像素分析：y=382-396/440-454 灰 1738/1748 大量灰色占位，仅 y=496-511 红 158 有真实行情）。

**根因**（代码审计 + 宿主机实测）：
- `_watchlist_enrich_items`（market.py:624-770）只对 `asset_type=="A"` 走批量 `get_realtime_batch`（L644-653 `_a_items`）；**HK 条目走 per-item `_realtime_one`**（L635-642 `wait_for(timeout=3)`）；
- `get_asset_realtime(sym, "HK")`（market_service.py:1187-1200）内部 `_timeout=15`（L1173 非 A 分支）——4 级降级链（Sina→Tencent→东财→TickFlow，china_market.py:950-961），冷门股/东财断连时 >3s → **3s 必截断** → None → 前端"行情加载中"（quote-cache fallback miss 时）；
- 1/3 成功：腾讯/阿里等热门股 Sina/Tencent 1.7s 内返回（或 `_asset_realtime_cache` 3s 短缓存命中）；
- **批量路径已验证可用**：宿主机 `get_realtime_batch(['00700','09988','03690'], 'HK')` **1.0s 并发返回 3 只**（腾讯 471.0/阿里 127.1/美团 93.75）——并行远优于 per-item 3s 截断；
- 与 P2-AF（江波龙 `asset_type="stock"` 排除批量）同根：**非 A 类型未纳入批量路径**。

**影响**：港股自选是核心场景（跟踪港美股持仓），2/3 无行情直接不可用。

### 2.17 港股热门个股混入基金/ETF/权证（P2）

**现象**（用户反馈，截图 1855×1186 热门个股列表 29 行）：港股热门个股榜混入基金（盈富基金 02800、南方恒生科技 03033）、杠杆 ETF（南方最多两倍做多海力士 07709）等非普通股。

**根因**（代码审计 + 宿主机实测）：
- `hk_hot_fetcher._URL`（L36）：`fs=m:128`——**东财港股全市场**（股票+基金+债券+权证混杂）；
- `parse_hk_hot_stocks`（L130-143）：只取 f12/f14/f2/f3/f6/f100，**无任何类型过滤** → 按成交额排序后基金/ETF 自然上榜；
- 实测 `_fetch_hk_rows()` 100 行 spot 中 **7 个基金/ETF**（03033 南方恒生科技、02800 盈富基金、02828 恒生中国企业、07709/07747/07226 杠杆做多、07552 杠杆做空）按成交额进榜；
- **根治验证**：东财港股 fs 细分 `m:128+t:3`（主板股票）返回纯普通股（阿里巴巴/腾讯/小米/中芯国际），**零基金混入**；t:1=基金/ETF、t:2=债券、t:6=权证。

**影响**：热门个股榜混入非股票标的，榜单语义错误（用户要的是"热门个股"）。

### 2.18 美股/港股综合研判内容雷同（P2）

**现象**（用户反馈，截图 1796×1174 综合研判报告）：美股市场综合研判内容与港股重复，"像把港股的直接拿过来了"。

**根因**（代码审计 + 宿主机实测）：
- `build_full_context`（llm_context.py）指数段已按市场正确分流（US=标普/纳斯达克/道琼斯、HK=恒生，实测分离正确）；`market_data` 段 US/HK 补对应区域指数（正确）；
- **news 段（L126-138）无条件调 `get_news_headlines()`**——A 股财新/宏观新闻，不按市场过滤 → **US/HK/A 注入同一批 A 股新闻**（实测 US 与 HK 的 `context["news"]` 首条均为"工银瑞信史宝珖：从工业革命到A股行情"，15 条相同），LLM 报告新闻部分雷同；
- **未用 `fetch_global_news`**（news_fetcher.py:412-442：道琼斯 RSS/CNBC/akshare 全球资讯）——美股/港股研判本应注入全球新闻而非 A 股新闻；
- US `market_data` 仅指数（major_symbols US 股票不在 A 股 all_realtime，叠加为空）→ 报告数据单薄更依赖 news → 美股/港股报告结构高度相似。

**影响**：美股/港股综合研判失去市场差异性（新闻与 A 股雷同、无对应区域资讯），研判价值下降。

### 2.19 美股数据源缺失 4 项（P2）

**现象**（用户连续反馈 13/14/15/16，截图 4 张）：①美股热点板块数据缺失；②港股/美股标的分析"板块概念"按钮置灰；③美股指数分析选推荐项报错；④美股标的分析报告出现"数据缺失"（基本面段）。

**逐项根因**（代码审计 + 宿主机实测）：
1. **美股热点板块缺失**：`market_data_hub.get_hot_plates`（L1351-1372）`market=US` 直接 `return []`（L1363 注释"US 暂不支持，结构化提示由路由层处理"）——无美股热点数据源；`get_sector_heat` 同理。
2. **板块按钮置灰**：`MarketContext.supports_sector_analysis`（market_context.py:96-98）仅 `market=="A"`——round10 P2-T 有意禁用港股/美股板块（无本地板块数据源）；前端 UnifiedAnalysis 按钮 disabled + tooltip（测试 L202-214 确认）。
3. **美股指数分析报错**：P2-AG 未修的直接后果——`_search_indices`（market.py:225-250）无 market 过滤返回全市场指数（含 A 股），美股 tab 下拉推荐项含 A 股指数；选中后美股模式 `get_asset_realtime(A股指数, "US")` 拿不到 → 报错（L1208-1214 index fallback 本地缓存也无 A 股指数）。
4. **标的分析基本面缺失**：`fetch_current_pe_pb`（fundamentals_fetcher.py:271-301）L281 `if not _is_a_stock(symbol): return None`——**只支持 A 股**；美股/港股标的 → None → symbol_analysis（analysis.py:636-643）`fundamentals_text = "（数据源不可用，无法获取 PE/PB 等估值指标）"` → 报告中该段恒缺失标注。**实测美股实时/历史 K 线可用**（AAPL 5.8s 实时、100 行日 K，非数据源全断），缺的是基本面估值。

**影响**：美股/港股市场功能完整性不足——热点/板块/基本面/指数四项数据缺失，与 A 股体验不一致。

---

## 3. docs 5 份文档落地核对

| 文档 | 结论 | 未落地/残留 |
|---|---|---|
| precommit-gating-optimization.md | ✅ 13 段门禁全落地；pytest -n auto 90s / smoke fast 5s / P3-6 提示不阻断 / 死代码 3 个 | 文档标题仍标"未实施"（状态标注滞后） |
| round10-container-rediagnosis.md | ✅ P0-A~P3-F 大部分落地 | **P2-K**：sector_fetcher 阈值 ±20% 已放宽，展示层值域校验一致性待复核；**P2-Q 美股搜索点号归一化未做**（BRK.B vs BRKB） |
| round11-code-redundancy.md | ✅ 核心删除全落地（shim/死文件/废弃端点/14 组件） | **4 项**：data/_diag 脚本（已清，0 个）；`routers/factors.py:26-42` 私有 TTL 缓存；`Dashboard.vue:130` VChart import；缓存路径两轨并存（etf_scanner.py:124/135、market_service.py:184，round11 P2-5 的 CACHE_DIR 方案未落地） |
| round12-implementation-plan.md | ✅ EM 方案 A（curl_cffi 711fb8b→回退 c5f8b3d）+ C 备选（987317c ipv4_forward_proxy）；mootdx revert 7bcab09 保留 | — |
| round13-data-source-evaluation.md | ✅ 宏观 5 因子（m2/pmi/lpr/gdp/两融）+ TickFlow 尾环 P1/P2/P3 + 历史四环全落地 | **Shibor/社融未接入**（文档自标"去向待定"未决项，macro_fetcher.py:7） |

---

## 4. 测试防护盲区分析（为何这些问题没被拦住）

| 问题 | 现有防护 | 盲区 |
|---|---|---|
| apply-design 断裂 | `test_portfolio_apply_design.py`（mock 掉真实函数，输入理想 symbols+weights）；verify_e2e 只发空 body 验 200 | **前端真实 payload 形态从未进任何测试**；verify_e2e 不验响应内容 |
| LLM 策略检查超时 | `test_strategy_check_llm_timeout/fallback` 断言"超时→兜底 OK" | **降级被当正常路径测试**（固化错误行为）；未测"重试总耗时 > 外层预算"（1 轮双 provider 71.5s 耗光 90s 的根因形态）与 provider 连通性 |
| watchlist 价格缺失 | 单测测 enrich 逻辑（mock 慢源不存在） | 未测"数据源慢→超时→DB-only 丢 realtime 字段"端到端；前端组件测试无 realtime 缺失用例 |
| 因子伪 IC | `_status_of` 合规测试（负 IC 标 warn） | 缺**最小样本保护约束**（样本 0 时 IC 应视为无效） |
| 信号不一致 | `test_signal_consistency` monkeypatch 固定同输入 | "同输入"前提在真实链路不成立 |
| 首页 CLS | `.lighthouserc.yml` 存在但**本地 build/commit 不跑**（仅 CI workflow） | 无前端性能回归门禁 |
| 首页盈亏色失效 | `SummaryCards.spec.js` 12 用例断言**文本内容/结构存在性**（toContain 数字/文案、class 是否存在），类绑定存在性部分覆盖 | **jsdom `css:false` 不层叠 CSS**——`text-up/down` 类绑了但被 scoped `.summary-value` color 覆盖的颜色回归**任何断言都测不到**；无"读取编译后样式/源码 style 块"层级的断言（FactorModelView 同型亦无测） |
| 冷缓存性能 | 无 | 无首请求耗时断言 |

**共性根因**：单测以"契约理想形态/固定输入"测后端逻辑，**契约两侧（前端真实调用）从未联合验证**；verify_e2e 以"HTTP 200/非空"为准，不验内容正确性（反假完成清单第 3 项未落实在自动化）；降级路径被测试固化而非触发条件被测试；**前端 `vitest.config.js css:false` + jsdom 不真实层叠样式** → 颜色/布局类回归（CSS 特异性覆盖、优先级）结构性零检出。

---

## 5. 优化与修复方案（设计，不实施）

### P0-A 修复 apply-design 断裂
- **前端**：`DashboardAiTools.vue applyPlan()` 构造 `{portfolio_type: "on_exchange", symbols: [...], weights: {...}}`（从 plan.allocations 抽取 symbol→target_weight），响应检查 `applied.length>0` 才 toast 成功，否则 toast 失败并展示后端 message；
- **后端**（可选加固）：apply-design 对空 symbols 返回 400（当前 200 空操作误导）；
- **测试**：新增 verify_e2e 真实链路用例（前端等效 payload → 断言 applied 非空）；单测去 patch、用真实函数 + 契约 payload。

### P0-B 修复策略检查 LLM 超时（provider 无响应 + 预算-重试不匹配）
- **主因修复**（provider 端 35s 无响应，90s 预算被 1 轮双 provider 失败耗光 71.5s，第 2 轮无空间）：
  - **诊断优先**：确认 opencode_zen/deepseek 35s 无响应的外部原因（网络/限流/模型负载），与 round14 EM 网络问题同源排查；容器内 curl 探测两 provider 连通性与延迟；
  - **配置加固**（`llm.py:1418-1425` `run_json(request_timeout=35.0, max_retries=1)`）二选一：
    - a) `request_timeout` 调大至 60-70s **且** `max_retries=0`（仅 1 轮，重试无空间即不重试）+ `_llm_timeout_for` 完整档同步提到 ≥156s（2 providers × 70s / 0.9 + 余量；代价：真故障时等待更长）；
    - b) 保持 35s 但 `max_retries=0`（1 轮双 provider 失败立即兜底，不进入会超预算的重试）+ `_llm_timeout_for` 完整档 90s→75s（对齐 71.5s 实测最坏 + 余量）——**推荐**：故障时更快兜底，成功时不受影响；
  - **注释修正**：`llm.py:1422-1425` "与 P0-F 的 30s 外层预算配套"过时（外层实际 90s），改为引用 `_llm_timeout_for` 分级预算；`llm.py:1415-1417` 注释"< 60s 预算"同过时（60s 为 round9 前旧值）一并更新——防误导后续维护；
- **附加注释链路（非主报告，低优先）**：`strategy_check_worker.py:55`（30s）/`:272`（20s）调 `llm_complete`（240s 未被覆写）——若需保留 llm_comment 附加功能，给 `llm_complete` 增加 `request_timeout` 可选参数并传 15s/18s（当前签名无此参数，需先加），使截断语义自洽；或接受现状（失败仅丢附加字段，L194 已标注非阻塞）；
- **测试**：
  1. 新增**预算-重试一致性断言**：按 `_llm_timeout_for` 动态预算（非硬编码 90s），`max_retries=0` 时免 0.9 系数直接 `providers × request_timeout ≤ 预算`（b 方案完整档：2×35=70 ≤ 75 PASS）；`max_retries≥1` 时 `(max_retries+1) × providers × request_timeout ≤ 0.9×预算`（当前完整档 2×2×35=140 > 81 FAIL → 强制改 max_retries=0）——防"重试轮次总耗时超外层预算"回归（本轮核心 bug 形态）；**注意仅对完整档主链路成立**（partial 30s 档天然 2×35=70 > 30，需 max_retries=0 或 request_timeout<15s，属设计取舍非 bug）；0.9 系数兜 rate_limit_cap=10 退避与 retry_delay=3s 容差；
  2. 保持既有"超时→规则兜底"断言（降级路径仍被固化，但新增负向：mock provider 慢响应 → 断言在预算内完成兜底而非 CancelledError 穿透）；
  3. provider 连通性探针测试（容器内 curl 两 provider 端点，超时/失败打标）；
- **验收**：连续 3 次 strategy-check（交易时段）主报告含 LLM 分析（非规则兜底）；或故障时 summary 明示"provider 无响应（最后错误: ...）"且**在 `_llm_timeout_for` 预算内完成兜底**（按 b 方案完整档 75s；未实施 b 方案前现状 90s；不再 CancelledError 穿透）。

### P0-C 因子 IC 最小样本保护
- `routers/factors.py:116` 分支前判 `samples < MIN_IC_SAMPLES`（如 30）→ 强制 `ic_val=None` → "IC 未累积（样本 <N）"；
- **测试**：新增"样本不足不产生 warn 下架"负向断言；因子页展示改为"无数据"而非"反向已下架"。

### P0-D watchlist 后端保字段 + 前端占位核实
- 后端：enrich 超时降级时**注入 `realtime: null` 且带 `_degraded: true` 标记**（不再丢 realtime 键），使前端 v-else 占位可感知降级；
- 前端：`WatchlistPanel.vue:127-134` **已有"行情加载中（数据源弱）"占位**——核实样式/文案清晰度，需要时优化；
- **测试**：fetch mock 慢源 → 断言响应含 `realtime: null` + `_degraded`，前端显示降级占位。

### P1-E 市场数据缺口补全
- sector_momentum 失败时按 `update_sector_cache` 已有 30-row 成功路径（5:39:55 观察）补 on-demand 重试；fund_flow 空时报告层诚实标注"资金流数据源不可用"（不写"净流出0.0亿"）；
- LLM prompt 注入失败标记（与估值"诚实标注"同模式）。

### P1-F 信号口径统一
- holdings_analysis 的 tech_signal 与 /market/signal 统一数据源快照（同一次 K 线获取），或明确标注"综合信号（含因子）"与"纯技术信号"两轨并展示双值；
- **测试**：对比测试改为"同一次调用内的两份数据"而非"同输入 monkeypatch"。

### P1-G 前端 CLS 修复
- `summary-grid` 卡片容器固定 min-height / aspect-ratio；数据未到先渲染同构 Skeleton（round10 P0-D 方案）；
- 目标：CLS < 0.1、perf ≥ 0.6；
- **门禁**：CI 加 Lighthouse assert（.lighthouserc.yml 已在，接 CI workflow 或本地 pre-commit 性能段）。

### P1-K 盈亏数字涨跌色修复（scoped 覆盖）
- **修复**（两处同型，均 scoped `<style>` 内、宿主 color 规则之后追加）：
  - `SummaryCards.vue`（5 处：当日×2 累计×3）：
    ```css
    .summary-value.text-up { color: var(--color-text-up); }
    .summary-value.text-down { color: var(--color-text-down); }
    ```
  - `FactorModelView.vue`（L31 有效数 + L61 平均|IC| 高值分支）：
    ```css
    .stat-num.text-up { color: var(--color-text-up); }
    .stat-num.text-down { color: var(--color-text-down); }  /* 防御性：当前无 .stat-num 上的 text-down 绑定（L88 的 ic-stat 绑定不在覆盖域），与 text-up 对称保留 */
    .stat-num.text-warn { color: var(--color-warning-600); }  /* 防御性：L38 警告色实际未失效（组件内 .text-warn 靠后胜出），保留以防宿主规则位置变动 */
    ```
  - **特异性机理**：`.summary-value.text-up` 编译后为 `.summary-value.text-up[data-v-xxx]`——**3 个简单选择器 = (0,3,0)** > `.summary-value[data-v-xxx]` (0,2,0)，覆盖生效（非"同级靠后定义"，是更高特异性胜出）。
  - （备选方案 B `:where(.summary-value)` 降权会连带影响 `--total`/font 等派生选择器优先级，改动面不可控，不采用。）
- **测试（能抓假）**：
  1. 单测（两组件各补）：`SummaryCards` `pnlOn>0` 断言元素 class 含 `text-up`、`pnlOff<0` 含 `text-down`（正向）；`FactorModelView` 有效>0 断言 `stat-num text-up` 类存在；
  2. **源码级回归断言**（唯一能抓 CSS 覆盖的方式，jsdom css:false 不层叠）：读两组件 `.vue` 源码 style 块（`fs.readFileSync`，perfBudget.spec.js 同型先例），断言覆盖规则 `.summary-value.text-up` / `.stat-num.text-up` 等**存在**、color 为 `var(--color-text-up/down)` 宽松正则匹配（特异性 (0,3,0) 已足够，无需断言位置）；`.stat-num.text-warn` 规则若保留则同步断言——若未来删覆盖规则测试即失败；样式迁移全局时同步更新断言；
  3. 浏览器实测：首页当日盈亏红（涨）绿（跌）、累计盈亏三卡同色；因子页有效/警告/平均|IC| 上色；截图复核。
- **验收**：首页 5 处盈亏数值按正负显示 `--color-text-up`（红，含 0 值）/`--color-text-down`（绿）——注意 `>= 0` 分支使 **0 值显示红色** text-up（与既有 changeClass 惯例一致）；`.summary-value` 中性色仅作用于总仓位卡（无涨跌语义，正确）；因子页有效数/平均|IC| 高值显示红色（警告色 L38 维持现状即正确）。

### P2-H 后端冷缓存改善（已知性能债，非阻断）
- 预热阶段扩展：设计/搜索/自选常用路径预热（当前仅 market_cache/global_indices/etf_cache）；watchlist enrich 慢源熔断并行化（批量失败时 HK/US per-item 并发上限与超时落点待实施时定）；
- 挂"性能债"台账：watchlist 冷 8.5s、calculate 冷 5s、search 冷 6.25s。

### P2-I 文档残留清理（round11/round10）
- 删 `Dashboard.vue:130` VChart import；factors.py 私有缓存并入 sync_memory_cache；缓存路径统一引用 round11 P2-5 已定稿的 CACHE_DIR 方案（容器 /app/data 与宿主 backend/data 两路径并存，非"双份"）；
- round10 P2-K：sector_fetcher.py `_sector_change_pct` 已放宽 ±20%（已落地，注释标 P2-K），但对应展示层值域校验（market.py:581 <=10）与之一致性未核对，实施时复核；P2-Q 美股点号归一化（BRK.B vs BRKB）未做；
- 清理 data/ 轮次快照 round_*.json 与 logs/ 历史大日志。

### P2-U 入选理由「方向」分类标签优化（etf_classifier.py）
- **现状**：`_NAME_RULES` L62 `("碳中和","电力设备")`、L59 `("新能源","电力设备")`——概念粗映射（碳中和/科创新能源指数成分含电力设备+环保/公用事业/汽车）；`test_etf_classifier.py:33-37` 固化"新能源→电力设备"断言。
- **改法**（保持 rationale 的 O23 机制不动，只调分类表标签）：
  - 新能源/碳中和类 ETF industry 改 **"新能源"**（更贴合指数成分全貌），concepts 保留 `["电力设备","光伏","锂电池"]` 等细分；
  - `_NAME_RULES` 精确词前置：`("科创新能源","新能源")`、`("新能源","新能源")`、`("碳中和","新能源")`（含 589960 tracked_index 缺失走 name 路径的 case）；
  - `_INDEX_RULES` 同步（L144 `("新能源","电力设备")` → `("新能源","新能源")`）；
  - **副作用核对**：`market_data_hub._assign_layer`（L461-472）用 industry 判层——宽基→core、商品/固收→defense、跨境/unknown 特判、其余→satellite；"新能源"落 satellite（正确，新能源非 core/defense）；
- **测试**：更新 `test_etf_classifier.py:33-37`（新能源→新能源）；新增碳中和/科创新能源/医疗器械/科创创新药 4 用例（含 589960 无 tracked_index 走 name 路径）；`test_pool_manager.py:49/359` 的 `"515030": {"industry":"电力设备"}` 同步改"新能源"；`test_rationale_industry_sanity.py` 正常行业断言不受影响。
- **验收**：design 494 重跑 rationale 首句为"碳中和ETF易方达 — 新能源方向"；医疗器械/创新药保持"医药生物方向"不变。

### P2-V 现金仓位展示补全（卡片 header + LLM 正文）
- **卡片 header**（`DesignResult.vue:48-54` stats）：加"现金 x%"——从 `pf.allocations` 找 `symbol==CASH` 的 `target_weight`（×100，1 位小数），追加到核心/卫星/防御之后；`calcLayerWeight` 同型 helper 或内联；
- **CASH 计数修正**（`DesignResult.vue:48` "X 只 ETF"）：`pf.allocations.length` 会把 CASH 计入——design 494 实测防御型 allocations=10 但 ETF=9（CASH=1）→ 显示"10 只 ETF"错误；改为 `allocations.filter(a => a.symbol !== 'CASH').length`；
- **LLM 正文**（`llm.py:1766-1772` 报告任务清单）：任务点 5 改为"说明各方案现金仓位及用途（引擎表格已有数值，正文需解释配置逻辑，如现金是主动保留待投/风险缓冲）"——使 LLM 正文出现现金仓位论述；同时 `llm.py:1908-1920` plan_tables 为空 fallback 补 `- {style}: 现金仓位 {w}%` 行；
- **保留**：`design_report.py:92-103` plan_tables「现金仓位」汇总行不动（已正确）；
- **测试**：前端单测（DesignResult 补）断言 header 含"现金 x%"且 **ETF 计数排除 CASH**（负向：CASH 计入时计数错误）；后端单测（design_report/llm prompt 构建）断言 plan_tables fallback 含现金行；verify_e2e 设计链路断言 design_text 含"现金"。
- **验收**：方案卡片 header 显示 4 项统计（ETF 数[不含现金]/核心/卫星/防御+现金）；LLM 报告正文有现金仓位论述；引擎表格汇总行仍显示。

### P2-W 方案卡片今日涨跌幅缺失显性化
- **前端**（`DesignResult.vue:80-84`）：`v-else` 的"—"改为**区分缺失原因**——dcp 为 null 时显示"数据源不可用"（muted 置灰，与 `design_report.py:189-191` P1-4 口径一致），不再用可能误读为"0%"的"—"；若后端可传缺失原因字段（如 `dcp_missing_reason`）则按原因显示"非交易时段"/"数据源不可用"；
- **CASH 行语义**（`DesignResult.vue:74-86`）：`symbol==CASH` 的行今日涨跌列**不显示**"数据源不可用"——现金无涨跌幅语义，**推荐 v-if 排除整行渲染**（与 `design_report.py:153-154` 引擎表格跳过 CASH 行先例对齐）；若保留行则涨跌列渲染"—"或空（P2-V 现金%已单独展示）；
- **后端**（可选）：`strategy_design.py:397-404` dcp 注入失败时补 `a["dcp_status"] = "missing"` 标记，前端据此显示原因；
- **测试**：前端单测断言 dcp=null 渲染"数据源不可用"（负向：不得渲染"—"或"0%"）、CASH 行不显示"数据源不可用"；后端单测断言 dcp=None 时引擎表格/API 响应含 missing 标记；
- **验收**：非交易时段生成方案，卡片涨跌列显示"数据源不可用"置灰；交易时段正常显示红绿涨跌。

### P2-X 入选理由精炼（rationale.py）
- **现状**：`rationale.py:134-250` 拼接 5-6 句（资产介绍+方向+RSI+MACD+技术面评分+动量+综合信号+市态），design 494 实测单条理由 150-200 字。
- **改法**（保留信息完整性，压缩冗余）：
  - 首句「名称 — 方向」保留（P2-U 优化后标签更准）；
  - 技术面句合并：RSI+MACD 合成一句（如"RSI 59.6 中性、MACD 多头"），删"技术面综合评分 X.XXX"（低信息量绝对值）；
  - 综合信号句保留（偏多/中性/偏空 + 数值）但删"市场震荡"等重复市态句（市态已在报告层级体现）；
  - 目标：单条理由 ≤100 字，核心驱动因子（动量/技术面最高分项）保留；
- **测试**：`test_rationale_industry_sanity.py` 各断言不回归（"方向"句式保留）；新增断言：理由长度 ≤100 字（与验收口径一致）、含"方向"、含至少一个技术面关键因子（RSI/MACD/动量）；
- **验收**：design 重跑理由明显精简（≤100 字/条），方向/核心因子/风险提示信息完整。

### P2-Y 因子 IC 排序表加中文名列（前端）
- **改动**（`FactorModelView.vue` IC 排序表）：
  - 表头（L94-100）在「因子代码」后加 `<th>因子名称</th>`；
  - 行（L103-117）在 code td 后加 `<td>{{ f.name }}</td>`（后端 `/factors/active` 已返回 `name`，38 注册因子全部有中文名——YAML `factor_definitions.yaml` 优先，`_get_factor_name` 兜底）；
  - 空行（L118-120）`colspan="5"` → `colspan="6"`；
- **测试**：前端单测断言 IC 表行含 `f.name`（负向：无 name 时显示 code 兜底）；后端无改动（name 已返回）；
- **验收**：因子页 IC 排序表每行显示中文名（如「5日均线」「MACD主线」），与分类卡片一致。

### P2-Z tracking_error / shares_change 无数据修复（后端，根治）
- **修复 1（主因）**：`factor_registry.compute` L1419-1421——`market_data` 外部注入时合并 `symbol_extra`（与 `_fetch_market_data` L1327-1336 Z04 同逻辑）：
  ```python
  if market_data is not None and symbol_extra:
      for sym in symbols:
          if sym in market_data and sym in symbol_extra:
              for key in ("industry", "concepts", "benchmark_close",
                          "shares_change_20d", "institutional_holdings_change",
                          "shares_change", "fund_scale"):
                  if key in symbol_extra[sym] and key not in market_data[sym]:
                      market_data[sym][key] = symbol_extra[sym][key]
  ```
  使 IC 循环传 `market_data=_kline` 时也能拿到 benchmark_close/shares_change_20d；**注意副作用**：`market_data` 实为 `_hub._kline_cache`（main.py:443 直传），merge 会就地写回共享缓存——asyncio 单线程无并发撕裂，且与 Z04"不覆盖已有字段"语义一致（无害，但实施时知悉）；
- **修复 2（配套）**：IC 循环（`main.py:440-446`）补 `symbol_extra` 注入——`_enrich_symbol_extra(_syms, {})`（**注意签名 L1271-1275 `base_extra` 无默认值，须传 `{}`**；实现 L1285 `base_extra.get(s) or {}` 对空 dict 安全）并传给 `_reg.compute(_syms, market_data=_kline, symbol_extra=symbol_extra)`——确保 benchmark_close 真正注入（当前 IC 循环完全不调 enrich）；**独立 try/except（`except (Exception, asyncio.CancelledError)`，与 main.py:449 同型防 CancelledError 穿透）+ 短超时（`asyncio.wait_for(..., 15)`）**——`_enrich_symbol_extra` 内部 `_ENRICH_TOTAL_TIMEOUT=60s`（market_data_hub.py:1269）> IC 循环 `wait_for(..., 30)`（main.py:445），若 enrich 触网慢会耗尽整个 IC 循环预算连累其余 31 因子；失败时 `symbol_extra={}` 继续；
- **修复 3（阈值）**：`ic_tracker.compute_periodic_ic` L169 `abs(val) < 0.001` 对 tracking_error 过严（合法值 0.001~0.02，`_compute_tracking_error` L416 注释 0~0.05）——改为按因子区分：tracking_error 用 `abs(val) < 1e-6`（仅排除真 0），其余因子维持 0.001；**shares_change 值域待验收核对**（20 日份额变化率通常 >0.1%，但保守起见验收时打印真实值分布，若普遍 <0.001 则同步放宽）；
- **测试**：
  1. 单测：mock `market_data` 含 benchmark_close 序列 + symbol_extra → `compute` 后 `_compute_tracking_error` 返回非 0（修复 1 生效）；
  2. 单测：mock `compute_periodic_ic` 输入 tracking_error 值 0.005 → 不被 `abs<0.001` 跳过、产出 IC（修复 3 生效）；
  3. 集成：IC 循环跑一轮后 `_last_ic_batch` 含 `etf.tracking_error`/`etf.shares_change`，DB `factor_ic_records` 出现两因子记录；
- **验收**：因子页两因子显示有效/无效 IC（非"无数据"）；DB 两因子 IC 记录数 ≥50 条累积（与 §6#10 同口径）；`factors/active` summary `no_data` 从 2 → 0。

### P2-AD 标的分析：doAnalyze 自动关闭补全下拉（前端）
- **修复**（`UnifiedAnalysis.vue` `doAnalyze` L358 开头）：补 `activeSearch.value.showDropdown.value = false`（+ `activeSearch.value.searchResults.value = []` 清空，防残留）——覆盖**点「分析」按钮**路径（当前仅点下拉项 selectSearchItem 才关）；
- **位置**：`doAnalyze` 开头、`loading.value = true` 之前——分析开始即闭，不依赖 SSE 完成；
- **测试（能抓假）**：新增统一用例——`searchQuery='510050'` + `searchResults=[item]` + `showDropdown=true` → `doAnalyze()` → **断言 `showDropdown===false`**（负向：现在为 true FAIL，正是复现所述）；同时保留既有 `pickSearchItem` 场景断言（补 `showDropdown=false` 断言，防回退）；
- **验收**：输入关键词显示下拉 → 点「分析」按钮 → 下拉立即收起、分析正常开始；`UnifiedAnalysis.spec.js` 含"点分析按钮关下拉"负向用例。

### P2-AE 板块热度涨跌幅根治（财联社 plate_list 精确 join）
- **修复**（`sectors/heat` market.py:549-583 + `sector_fetcher.py`）：
  1. **新增 `fetch_cls_plate_changes()`**（`sector_fetcher.py`）：调财联社 `plate_list` 接口（`/web_quote/plate/plate_list`，`type=industry` + `type=concept` 各 `page=500`），返回 `{plate_code: change}`（change 为小数涨跌幅，×100 转百分比）；**120s TTL 缓存**（`ttl_key="sector_heat"`，ttl.py:30 实际值，非 60s）；
  2. **sectors_heat 用 plate_code join 优先**：`rows` 各行的 `plate_code`（财联社 cls80424 等）直接查 `fetch_cls_plate_changes` 映射 → 命中用真实涨跌幅（×100）；未命中再走既有东财名称 `_match_em_change` 兜底；两者都未命中才 0；
  3. **sign/反爬**：levistock 的 `sector_industry_cls` 用**硬编码静态 sign**（`ef1ec7886be706a0b722d7e7bf3c0054`，levistock 内部常量，站点仓库无签名逻辑）——落地时在 `sector_fetcher.py` 内置该常量并注兜底：sign 失效（401/404）时回退东财名称回填（现状），不阻断 heat 展示；
- **测试**：单测 mock `fetch_cls_plate_changes` 返回 `{cls80041: 0.0186}` → `sectors_heat` 响应 `乳业奶粉 change_pct=1.86`（×100）；负向：plate_code 未命中 → 东财兜底 → 仍 0（保持现有行为）；
- **验收**：`/sectors/heat` 20 板块全部 change_pct 非 0（实测 join 20/20）；前端板块热度 tab 无 +0.00% 假值；财联社接口异常时回退东财/0 兜底不崩。

### P2-AF 自选列表优化 + 个股行情补全（后端 enrich）
- **列表慢优化**：
  1. `_watchlist_enrich_items`（market.py:624-770）已有 gather 并发（L661），**保留并发结构**；真正问题在降级路径——批量失败 `_skip_a_per_item`（L660）后 A 股 DB-only 但**未注入 `realtime:null`**，前端无法区分"加载中"与"降级"；降级时注入 `realtime:null` + `_degraded:true`（P0-D 同型）使前端可感知；
  2. 前端：`WatchlistPanel.vue` 慢源期间显示骨架屏而非"行情加载中"占位（降级时显示"数据源弱，已降级"而非永久 loading）；
- **江波龙 301317 行情（根因 = asset_type 归一化 + 超时失配）**：
  1. **归一化**：`_watchlist_enrich_items` 的 `_a_items` 过滤（L644 `(it.asset_type or "A") == "A"`）改为**把 `"stock"` 也归入 A 股批量路径**（`asset_type in ("A", "stock")`）——搜索结果返回 `type:"stock"`（market.py:283）→ 入库 asset_type="stock"（add_watchlist L1542 透传）→ 当前被 `_a_items` 排除，走 per-item；
  2. **超时失配**：`_realtime_one`（L635-642）外层 `wait_for(timeout=3)` 截断，而 `get_asset_realtime("301317","stock")`（L1173 `8 if asset_type=="A" else 15`，stock 取 15）→ **3s vs 15s 必超时** → realtime None → 前端"行情加载中"；归一化到批量后走 `get_realtime_batch`（4s 批量）规避；
  3. **补强**：`_realtime_one` 对 A/stock 类型 timeout 3s → 5s（对齐 get_realtime_batch 4s + 余量），或确认批量路径先覆盖（推荐批量优先，per-item 降级兜底）；
- **测试**：单测 enrich 注入 `realtime:null`+`_degraded`（慢源）；单测 `asset_type="stock"` 的 301317 归入 `_a_items` → 走批量 get_realtime_batch → price 非空（当前 FAIL：被排除走 per-item 3s 截断）；前端 WatchlistPanel 慢源显示骨架屏；
- **验收**：自选首次加载 ≤3s（批量行情命中）；江波龙显示实时价格/涨跌（非"行情加载中"）。

### P2-AG 港股指数补全修复（前端传 market + 后端过滤）
- **前端**（`useMarketSearch.js:82`）：index/sector 模式也传 market（港股 tab → `market='HK'`）——`...(mkt ? { market: mkt } : {})`（去掉 `kind==='all'` 限制，或对 index 模式单独传）；sector 模式港股 tab 本就禁用，传 market 无副作用；
- **后端**（`_search_indices` market.py:225-250）：加 `market` 参数——`market='HK'` 时 `IndexMeta.market == 'HK'` 过滤 + **limit(10)→limit(20)**（放大港股指数命中面）；`market` 空保持现状（全市场）；`market='A'` 只查 A；**注意覆盖两处调用**：L95（kind=index）与 **L188（kind=all 尾部段）**——search endpoint 须把 `Query mkt` 透传进两处，否则 all 模式港股指数仍不过滤；
- **数据源补强**（`indices_meta` 表）：main.py lifespan 补调 `scripts/sync_indices_meta.py` 的 **`sync()`**（该模块导出 `async def sync()`，L171，非 `sync_indices_table`）——对齐已有 `sync_instruments_table` 模式，round14 日志"instruments-sync failed: No module named 'scripts'" 需一并排查模块路径——确保港股指数（sina `stock_hk_index_spot_sina` ~38 个，scripts/sync_indices_meta.py:5）真正落表；同步失败降级为现有表内容不阻塞启动；
- **测试**：后端单测 `_search_indices(kw, market='HK')` 只返回 HK 指数（mock IndexMeta）；前端单测 useMarketSearch index 模式请求带 `market` 参数（当前 FAIL：不带）；集成验证港股指下拉含"恒生指数"；
- **验收**：港股 tab 指数模式搜"恒生/国企" → 下拉返回恒生指数/国企指数等（非 A 股占满）；`/search?kind=index&market=HK` 只返回 HK 指数；A 股 tab 行为不变。

### P2-AH 港股自选 enrich 批量路径（根治行情加载中）
- **修复**（`_watchlist_enrich_items` market.py:624-770）：
  1. **HK 并入批量**：`_a_items` 分组扩展（精确：`_a_items` 定义 L644，批量块 L646-653）——按 asset_type 分组：`"A"/"stock"` 走 `get_realtime_batch(syms, "A")`，`"HK"` 走 `get_realtime_batch(syms, "HK")`（L984-994 非 A 分支已支持，并发 gather `get_asset_realtime`），`"US"` 走 `get_realtime_batch(syms, "US")`；**不再让 HK/stock 落 per-item `_realtime_one` 3s 截断**；**HK 批量统一加 4s 级 `wait_for` 包装**（对齐 A 批量 L649 的 4s），防止慢源冷路径越过 L803 整体 5s 预算——批量 miss 收口回退链：`batch miss → per-item（分级超时）→ DB-only + _degraded`；
  2. **`_realtime_one` 超时分级**（兜底，批量 miss 时）：**A/stock 5s**（与 P2-AF③统一，采纳其 3s→5s 建议）、**HK/US 8s**（对齐 `get_asset_realtime` 非 A `_timeout=15` 设计内的快速返回级 1.7s + 余量）；批量优先使 per-item 罕见触发；**注意 `len(_a_items) >= 2` 门槛（market.py:646）**——分组后单只 HK 会漏出批量落 per-item，需"单只也走批量（去掉门槛或按组 >=1）+ per-item 8s 兜底"双保险；
  3. 整体 5s 预算（L803）评估：批量 HK 并发 1s/3 只，A 批量 4s——5s 内可完成；若批量占时超预算，考虑整体预算按含 HK 动态放宽（如 5s→8s，round9 P0-4 的 5s 是为防慢源拖垮）；
  - **与 P2-AF 合并实施**：P2-AF（A/stock 归一化）与 P2-AH（HK/US 分组）改动同一 `_a_items`+gather 块，**建议一次统一实现"按 asset_type 分组批量"**（A/stock/HK/US 各走对应 `get_realtime_batch`），避免分两次提交产生冲突/双重迁移；
- **测试**：单测 enrich 含 HK 标的三只 → 断言走 `get_realtime_batch(...,'HK')`（当前 FAIL：走 per-item 3s 截断 None）；宿主机集成 `get_realtime_batch(['00700','09988','03690'],'HK')` 1.0s 出 3（已实测）；负向：HK 批量失败 → per-item 8s 兜底 → 前端显示降级而非"加载中"；
- **验收**：港股自选 3 标的全部显示实时价格/涨跌（<3s）；`/watchlist` HK 条目 realtime 非空；A 股自选行为不变。

### P2-AI 港股热门个股过滤（fs=m:128+t:3 主板股票）
- **修复**（`hk_hot_fetcher.py`）：
  1. `_URL`（L36）`fs=m:128` → **`fs=m:128+t:3`**（东财港股主板股票，实测纯普通股：阿里巴巴/腾讯/小米/中芯国际，**零基金/ETF/债券/权证**）；t:1=基金/ETF、t:2=债券、t:6=权证（细分实测确认）；
  2. 兼容性：`_fetch_hk_rows` 的 `last_ok` 缓存旧数据（m:128 全量）可能混入基金——缓存版本化（如 key 含 fs 参数）或清空缓存，避免旧数据回填；
  3. `parse_hk_hot_stocks` 加**双保险**：名称关键词过滤（锚定基金/ETF 特征——`*ETF`、杠杆、做多/做空、盈富/南方/安硕/道富/标普/纳指 等完整名，**勿用「恒生」前缀**（会误杀普通股恒生银行 00011）)作为 t:3 之外的兜底（防东财参数变更后混入）；
  4. **source_registry 同步**：`_fetch_hk_rows` 的 `route(target="m:128")`（L80）改 URL 后同步 `target="m:128+t:3"`——保持 `/admin/sources/circuit-breakers` 熔断观测与 URL 一致；
- **测试**：单测 `parse_hk_hot_stocks` 输入含基金行（03033/02800/07226）→ 断言被过滤、**恒生银行 00011 不被误杀**；`_URL` 断言含 `t:3`（防回归）；单测缓存版本化——last_ok 旧 t:1/m:128 基金数据**不因新 t:3 URL 回填**（防旧基金数据混入新榜）；集成 `_fetch_from_host` t:3 URL 返回纯股票（实测 50 行零基金特征）；负向：t:3 请求失败 → last_ok 含基金旧数据时仍过滤（名称兜底生效）；
- **验收**：港股热门个股榜无基金/ETF/权证（盈富/南方恒生科技/杠杆工具不出现在榜单）；普通股（腾讯/阿里/小米）正常；**HK 板块热度/成交额无显著下降核对**（t:3 板块聚合变化的副效应确认）。

### P2-AJ 美股/港股综合研判 news 按市场选源
- **修复**（`llm_context.py` build_full_context news 段 L126-138）：
  1. **按 market 选新闻源**：`market in ("US","HK")` → **`fetch_global_news`**（news_fetcher.py:412 道琼斯 RSS/CNBC/akshare 全球资讯，美股/港股研判用全球新闻）；`market in ("A","")` → 保持 `get_news_headlines`（A 股财新/宏观）；
  2. **HK 补充港股新闻**（可选，若 news_fetcher 有港股源）或叠加全球+部分 A 股宏观（保持上下文完整性）；US 用全球（道琼斯/CNBC 美股相关度最高）；
  3. **market_data 补强**（可选）：US major_symbols（SPX/QQQ/AAPL）实时——当前叠加为空，若美股实时数据源可用（TickFlow AAPL.US 等）则注入，使美股报告有美股个股行情而非仅指数；
- **测试**：单测 build_full_context(market=US) → `context["news"]` 含全球新闻（RSS/CNBC）且**不含 A 股"工银瑞信史宝珖"类**（当前 FAIL：A 股新闻）；对比 US vs HK 的 news 首条不同（防雷同）；market=A 行为不变；
- **验收**：美股综合研判新闻为全球/美股资讯（非 A 股雷同）；美股与港股报告新闻段可区分；`market_data`（若补 realtime）含美股个股行情。

### P2-AK 美股热点板块/热门个股数据源接入
- **现状**：`get_hot_plates`/`get_sector_heat`/`get_stock_hot_rank`（market_data_hub L1351-1394/L1843-1891）market=US 返回空/降级；
- **接入方案**：
  1. **美股热门个股**（优先）：`get_stock_hot_rank(market=US)` 现走 `_fetch_us_spot`（china_market.py:1065 东财美股 spot，已可用）按成交额排序——**已接通但需验证 limit 与字段**（report 当前 L1852-1875 US 分支已实现排序，问题在热点板块不是个股？）；
  2. **美股热点板块**（新）：东财美股板块接口（`fs=m:105` 美股行业板块，带涨跌幅）或 akshare `stock_us_industry_spot_em`——**两个候选源均未在仓库实测（全仓 grep 零匹配，akshare 方法历史上删除/复得多回），实施前须现场实测确认哪一可用**再接入 `get_hot_plates(market=US)` 替代 `return []`；
- **测试**：单测 mock 美股板块数据源返回 → `get_hot_plates(US)` 非空；验证 US 热点板块含真实板块名/涨跌幅；
- **验收**：美股热点板块 tab 显示板块列表（含涨跌幅/热度），非"暂不支持"空白。

### P2-AL 港股/美股板块分析数据源接入（解锁板块按钮）
- **现状**：`MarketContext.supports_sector_analysis`（market_context.py:96-98）仅 A；前端按钮 disabled（round10 P2-T）；**`_search_sectors`（market.py:199-210）对 US/HK 显式 `return []`（round10 P2-T guard，搜索链路实际拦截点）**——三处需同步解锁；
- **接入方案**：
  1. **美股板块**：`_search_sectors` 加 US 数据源（东财美股行业板块 `fs=m:105`，**实施前须现场实测**）+ `sector_analysis` 板块成分股/涨跌幅；
  2. **港股板块**：`get_hk_hot_plates`（hk_hot_fetcher.py:146 已实现港股行业板块，`fs=m:128` 成交额聚合）——**注意语义**：热度榜是成交额聚合非板块成分股，与 `sector_analysis` 成分股语义不同构，实施时区分「板块热度展示」与「板块深度分析」两档能力，或走独立港股行业行情源；
  3. `supports_sector_analysis` 扩展：`market in ("A","HK","US")` + 前端移除 disabled（保留数据源失败降级提示）；
- **测试**：美股/港股 tab 板块模式可触发 sector_analysis（非 disabled）；`/search?market=US&kind=sector` 返回美股板块（当前空）；
- **验收**：港股/美股 tab 板块概念按钮可点，板块分析正常返回；数据源失败时降级提示不报错。

### P2-AM 美股指数分析报错修复（P2-AG 前置依赖，范围三处）
- **现状**：P2-AG（index 搜索无 market 过滤）未修 → 美股 tab 下拉推荐项含 A 股指数 → 选中后美股模式 realtime 失败报错；
- **修复（P2-AG 先行，三处改动）**：①`_search_indices` 签名加 `market` 参数（market.py:225）；②`search` 路由 **L95（kind=index）与 L188（kind=all 尾段）两处调用透传 `mkt`**；③前端 `useMarketSearch`（L82）去掉 `kind==='all'` 限制让 index/sector 也传 market——美股 tab 只出美股指数；④美股指数 realtime（`get_asset_realtime US` 的 index 分支或 global_indices 美股组）确认可用；
- **测试**：美股 tab index 模式搜"标普/道琼斯" → 下拉只出美股指数；选标普500 → 分析正常（当前 FAIL：混入 A 股指数报错）；
- **验收**：美股指数分析选推荐项不再报错；下拉无 A 股指数混入。

### P2-AN 美股/港股标的分析基本面 PE/PB 接入
- **现状**：`fetch_current_pe_pb`（fundamentals_fetcher.py:271-301）`_is_a_stock` gate 只支持 A 股 → 美股/港股标的报告基本面段恒"数据源不可用"（analysis.py:636-643）；实测美股实时/历史可用，缺基本面估值；
- **接入方案**：
  1. **美股 PE/PB（拟扩展 `fetch_current_pe_pb(symbol, market="A")` 加 US/HK 分支）**：估值源（东财美股估值 / Finnhub `/stock/metrics` / TwelveData 估值）**实施前须现场实测确认哪一可用**——注意 `global_markets_fetcher` 现仅有 candles/realtime/history（无 PE/PB 端点，L98-611 grep 核对）；**签名变更影响面**：analysis.py:639（1 处）+ test_pe_pb_fallback.py 4 处单参调用需同步（加 `market="A"` 默认值兼容）；`ak.stock_us_hist` 是纯日 K **无估值列**（L1589 一致，不可作 PE 源）；
  2. **港股 PE/PB**：akshare `stock_hk_hist` 估值列或东财港股估值；
  3. 失败仍诚实标注"数据源不可用"（不伪造值，P1-3 约定保持）；
- **测试**：`fetch_current_pe_pb("AAPL","US")` → 返回 PE/PB（当前 None）；`fetch_current_pe_pb("00700","HK")` → 返回；负向：源失败 → None → 报告标注不可用（不报错）；
- **验收**：美股/港股标的分析报告基本面段显示真实 PE/PB（非恒"数据源不可用"）。


### P3-J 冗余清理
- `backend/scripts/archive/` 12 个一次性诊断脚本标注删除或移入 diag/；`start_backend_profiled.py` 无调用点（保留或删，随 P3 决策）。

## 6. 验收口径（实施后）

1. **verify_e2e 全 PASS**（含新增 apply-design 真实链路用例与策略检查 LLM 参数一致性断言）；
2. `/portfolio/apply-design` 用前端等效 payload 应用后持仓 target_weight 变化且 `applied` 非空；
3. 连续 3 次 strategy-check 无 rule fallback（或 fallback 时 summary 明示且前端可见"降级"状态）；
4. 因子页无"样本数 0 的负向 IC 下架"项；
5. watchlist 顶层 3 市场条目 price 非空或显式"加载中"占位；
6. 首页 Lighthouse perf ≥ 0.6 / CLS < 0.1；
7. docs 核对残留项清零（round11 4 项 + round10 2 项 + round13 Shibor/社融挂账决策）；
8. 首页当日/累计盈亏按正负显示红绿（截图复核：正红负绿；`>= 0` 分支下 0 值显示红色 text-up，与既有 changeClass 惯例一致）；`SummaryCards.spec.js` 与因子页测试含源码级覆盖规则断言（删覆盖规则即失败）；因子模型页有效数/平均|IC| 高值恢复红色（警告色维持现状即正确）；
9. 组合方案设计 4 项改进验收：①设计重跑 rationale 方向标签（碳中和/科创新能源→新能源，医疗器械/创新药→医药生物不变）；②方案卡片 header 含"现金 x%"且 LLM 报告正文有现金仓位论述；③非交易时段卡片涨跌列显示"数据源不可用"置灰（非"—"）；④入选理由 ≤100 字/条且含方向+核心因子；
10. 因子页改进验收：①IC 排序表每行显示中文名；②tracking_error/shares_change 显示有效/无效 IC（非"无数据"），DB 两因子 IC 记录数 **≥50 条累积**（多周期，防"恰好 1 条"假通过）且 `factors/active` summary `no_data` 从 2 → 0；
11. 标的分析下拉验收：输入关键词显示下拉 → 点「分析」按钮 → 下拉立即收起；`UnifiedAnalysis.spec.js` 含"点分析按钮关下拉"负向用例（当前 FAIL 复现）；
12. 板块热度验收：`/sectors/heat` 20 板块全部 change_pct 非 0（实测财联社 plate_code join 20/20）；前端板块热度 tab 无 +0.00% 假值；
13. 自选验收：首次加载 ≤3s；江波龙 301317 显示实时价格/涨跌（非"行情加载中"）；慢源时前端骨架屏 + 后端 `realtime:null`+`_degraded`；
14. 港股指数验收：港股 tab 指数模式搜"恒生/国企" → 下拉返回恒生指数/国企指数等（非 A 股占满）；`/search?kind=index&market=HK` 只返回 HK 指数；A 股 tab 行为不变；
15. 港股自选验收：港股自选 3 标的全部显示实时价格/涨跌（<3s）；`/watchlist` HK 条目 realtime 非空；A 股自选行为不变；
16. 港股热门个股验收：榜单无基金/ETF/权证（盈富/南方恒生科技/杠杆工具不出现）；普通股（腾讯/阿里/小米）正常；恒生银行 00011 不被误杀；HK 板块热度/成交额无显著下降；
17. 综合研判市场差异验收：美股/港股综合研判 news 段用全球/美股资讯（非 A 股雷同，news_fetcher 无港股专属源故 HK/US 共用全球 RSS）；**至少 index_realtime 与可选 market_data 可区分 US vs HK**（标普 vs 恒生）；A 股 news 行为不变；
18. 美股数据源验收：①美股热点板块 tab 显示板块列表（非"暂不支持"空白）；②港股/美股板块概念按钮可点且分析正常；③美股指数分析选推荐项不报错（P2-AG 前置：下拉无 A 股指数混入）；④美股/港股标的分析基本面显示真实 PE/PB（非恒"数据源不可用"）。

---

## 7. 附录

- 预热诊断（PROFILE_WARMUP=1）：总记 10.2s（warmup_market_cache 5.8s / global_indices 4.2s），报告 logs/warmup_pyinstrument.* 与 warmup_timing.json；
- 后端冷热对比基线：logs/task12_*.json；
- Lighthouse 原始报告：logs/lh_{home,market,news,portfolio}.json；
- 本轮诊断脚本：scripts_diag/（15+ 只读探针，未改生产代码）。