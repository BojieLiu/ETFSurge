# Round10 容器化复诊断与优化方案

> 状态：**诊断完成 + 方案设计完成，未实施**
> 日期：2026-08-08
> 范围：Docker prod 容器内全链路复诊断（构建/预热/设计/策略检查/行情分析/搜索/自选/技术分析/资讯/因子/前端Lighthouse/后端性能/测试防护/round9清单核对）
> 基线：HEAD = b2fd04c（round9 实施完成），工作树干净

---

## 0. 摘要

在 Docker prod 容器（docker-compose --profile prod，镜像烘焙）对 ETF Surge 做第 10 轮全链路复诊断。相对 round9（2026-08-07 同容器环境）的核心结论：

1. **round9 方案落地约半数有实证**（确认修复 23/47 ≈ 49%，另有部分修复 14/47——确认+部分合计 37/47 ≈ 79% 有进展；含 P0-6/7 IOPV 链、P0-8 幽灵锚 560600→159338、P1-6 market_regime、P1-10 sentiment 静态化、P0-1 symbol-analysis 等）；预热从 37.4s→12.1s、watchlist 从 29.9s→3.0s。
2. **但容器内外部数据源脆弱（round9 C4/P0-2）未根治** → 本轮下游数据完整性故障多由此引发：策略检查 fetch_history 全空 → 因子 6/34 + 10 只 signal 全「数据不可用」；watchlist 实时 enrich 超时 → 列表 realtime 全 None。（注：AI 投顾数据注入链断裂**与弱源无因果**，为独立契约缺陷，见第 3 点。）
3. **新发现 3 个此前未被门禁暴露的问题**（其中 AI 投顾为**长期存在的槽位错配缺陷在本轮内容断言下首次暴露**，而非 round9 后的代码回归——round9 §5 仅验 HTTP 200 未验内容故误标 ✅；**注：此「3 个新发现」与第 6 点「8 类盲区」为不同口径——8 类盲区聚焦「数据正确性类问题为何漏检」，factor-health 属性能类（性能门禁缺失），不在盲区表内**）：
   - **AI 投顾（llm-advice）数据槽位错配 bug**——router 只注入 `ctx["market_snapshot"]`，但 `generate_advice` 第一段（大盘概况）读 `market_data/regime/sentiment` 槽（未注入）、第三段才用 market_snapshot → 3 市场投顾全部退化为「暂无实时指数数据/板块」模板；
   - **前端 Lighthouse 严重劣化**：/ 52、/market-analysis 89、/portfolio-analysis 73（round9 90/100/99）——首页跌破 F18 硬门禁 60、CLS 0.389 远超 0.1（round9 0.004）；
   - **后端新性能黑洞** `/admin/factor-health` 10.9s（round9 §10 未记录）。
4. **round9 清单核对**：47 项逐项唯一分类（见 §7 精表）——确认修复 23、部分修复 14、未修复 2（P1-8 benchmark_close、P1-9 shares_change）、未专项验证 8，合计 23+14+2+8=47 闭合。
5. **报告质量**：设计 456 结构提升（无幽灵锚/regime 补齐），但**行情数据完整性有两处硬伤**：
   - **♨️ 行情数据陈旧（§3.4，用户反馈）**：方案卡与正文涨跌幅取自**8/4（3 交易日前）的 etf_list_cache.json 旧快照**（容器读到根 `./data`，refresh 周六/弱源未更新）——8/7 真实收盘（如 588000=+2.56%、510050=+1.22%）与报告（+4.28%/-0.23%）严重不符，510050 方向都反了；
   - **LLM 90s 超时兜底（§3.3）**：数据完整度分级把"只有静态 size 因子的残缺数据"误判为"完整"→ 给 90s 大预算，叠加 provider 240s 超时与 90s 外层预算不匹配、fallback 被饿死；策略检查另有「报告标题因子 10/10 vs 逐项 6/34」「10 只全 hold 无真实信号」诚实性缺陷——专业投资者均不可接受。
6. **测试防护盲区**：本轮 8 个新/复现问题全部落在 8 类盲区（AI投顾内容零断言、策略检查 filled 与标题一致性零断言、watchlist realtime 零断言、Lighthouse 门禁平时不跑、负 IC 淘汰零门禁、容器弱数据源无模拟、**行情数据新鲜度/涨跌幅精度零断言**、**跨市场搜索 market 一致性零断言——F15 只验非空、单测 mock 白名单，market=US 返回 30 条 HK 仍全绿**）。

**方案**：P0×6（数据完整性阻断，含 LLM 超时分级口径修正 P0-F）/ P1×10（含 provider 超时参数化 P1-I、因子 warn 细分与数据源接入 P1-J）/ P2×20（含持仓行情加载态 P2-P、LLM 短缓存、行情新鲜度、双缓存、因子渲染、watchlist 添加、板块热度、资产类型联动、港股板块空名、港股技术分析空、港股 ETF 分类、美股搜索补全、美股热点补全、美股宏观政策段、美股板块补全等）/ P3×11（含 LLM 超时分级门禁、行情精度门禁、测试冗余治理 P3-J、mock 基线修正 P3-K）共 47 项，均附验收标准，未实施。

---

## 1. 执行环境

- 同 round9：docker-compose v2 + prod profile（redis/backend/frontend-nginx）。
- 后端预热诊断：`docker compose run --no-deps -e PROFILE_WARMUP=1` 临时注入（P3-6 回滚后的正规诊断方式），产物落宿主 `logs/`。
- 前端：playwright (frontend/node_modules) + lighthouse 13.4.1 + chrome-launcher。
- LLM provider：opencode_zen（deepseek-v4-flash-free），时快时慢（60-121s）+ 偶发 500。

---

## 2. 预热性能诊断（PROFILE_WARMUP=1）

| 指标 | 本轮 | round9 | 判定 |
|---|---|---|---|
| 墙钟启动→预热完成 | **12.1s** | 37.4s | ✅ 大幅改善（低于 30s 阈值） |
| profiler 主段 | warmup_market_cache 11.83s/6.8s run_sync 批量实时 | 12.46s + EM 54.5s 空等重试 | ✅ EM 空等重试已调解 |
| cProfile 热点 | levistock 资讯 3.0s / fund_open_fund_info_em 2.5s / fund_nav 1.9s / advance_decline 1.1s | requests/akshare 54.5s（EM 拦截重试） | ✅ 均为正常网络 I/O |

**结论**：round9 C4（容器内 EM TLS 拦截导致预热 37.4s 空等）本轮**未在预热路径复现**——降级链（sina/qq/ttj）已接管 ETF 池/行情缓存主采集。预热健康。

**注意**：预热 12.1s 的主耗仍集中在 `refresh_market_cache → get_portfolio_realtime → run_sync 6.8s`——行情批量采集单点 6.8s，虽不超阈值但仍是预热耗时大头。

---

## 3. 组合设计与策略检查质量审阅（专业投资者视角）

### 3.1 组合设计（design #456，balanced/50万/A股）
**产出**：防御 10 / 平衡 13 / 进攻 12（含现金），报告 8694 字，report_quality=full。

**通过项（round9 P0/P1 修复确认）**：
1. **560600 幽灵锚已移除**：三套方案核心层全部为 159338 中证A500ETF国泰（真实标的）——P0-8 ✅；
2. **18 只标的全有真实「今日涨跌」**（510300 +1.13%、159338 +1.77% 等），无「数据源不可用」——P0-8/P1-12 ✅；
3. **顶层 `market_regime=range_bound` 已补**（round9 None）——P1-6 ✅；
4. **`market_context.data_fetched_at=08:11:11` 存在**——P0-9 时间戳字段已加；
5. 三层结构 + 现金分离清晰。

**问题项（本轮发现）**：
1. **「今日涨跌」无显式时间戳标注**——data_fetched_at 在 API 元数据，但**报告表格列仍无「（截至 08:11）」**，用户仍会误读为收盘值（实证：报告 08:11 生成的「今日涨跌」与 16:19 收盘实时对照，18 标的中 17 个错位、其中 2 只方向相反、4 只显著错位——510050 报告 -0.23% vs 收盘 +1.22%、518880 -0.11% vs +1.10%（方向相反）；159915 +5.68% vs +1.30%、589720（科创创新药） +3.27% vs +8.55%（同向幅度差），均为「盘中值 vs 收盘值」的正常差异，同 round9 §4.3-A 定性）；
2. **562600 医疗器械ETF 今日涨跌 +0.00%**——**已取证**：该标的本轮收盘实时 `change_pct=+2.47%、volume=407198`（有量有涨跌，非零成交/非数据缺失）；报告里 +0.00% 实为**8/4 旧快照中该值即为 0.0（§3.4 已证报告全部 daily_change_pct 来自 8/4 旧快照，此 0 为旧快照陈旧值）**——**与问题 1（涨跌无时间戳）同属「报告行情数据陈旧」链条**，读者误读为「当日 0 涨跌」，非幽灵锚型数据错误；
3. **多只卫星层标的 factor_score 为负仍入选**（平衡型 562870 -0.53 / 562600 -0.1 / 562990 -0.41 / 562950 -0.42）——负因子分入选卫星，入选逻辑张力；
4. 防御型卫星含「证券ETF嘉实 12%」（高贝塔），定位张力（同 round9 问题 6）。

### 3.2 场内策略检查（check 记录 #371，portfolio_type=on_exchange，task 299）
**通过项**：
- `portfolio_type=on_exchange` 过滤正确（10 场内）；P2-4 portfolio_type 已持久化（record 371）；
- 兜底机制诚实：summary「LLM 分析超时（90s 未返回，已用规则引擎兜底）」——P0-5 超时 60s→90s；
- **兜底建议已个性化**：按因子分区间给差异化理由（「维持现状…关注 RSI 超卖」），不再是 round9 同模板。

**问题项（专业不可接受）**：
1. **LLM 90s 仍超时 → 规则兜底**：10/10 全 hold、全「数据不可用」，与技术分析接口真实信号（buy 3 / sell 2 / hold 5）**完全矛盾**；因子分 16-18 挤堆无区分度；
2. **「因子数据质量：10/10 只持仓因子数据可用」标题 vs 逐项 factor_availability 6/34、RSI/KDJ 全 50.00**——**P1-15 假正常换形式复现**（report_text 模板 1285 行仍用 `filled/{total} 只可用`，data_quality.fallback_ratio 已算但未用），报告中含「数据不可用」因子；
3. **`industry:""` 全空**——候选池（弱源）空 → industry_map 空 → P1-14 的 ETFClassifier 兜底在容器内未生效；
4. **10/10 tech_signal「数据不可用」**——P1-13 显式兜底生效（不再空白），但指示器采集在容器内全空。
5. **⚠️ 因子评分渲染层不过滤中性兜底值（用户反馈 08/08 21:00：评分一模一样）**：策略检查详情页每只持仓「因子评分」栏显示 `RSI(14) 50.00（中性）；KDJ.K 50.00；KDJ.D 50.00`——10 只全部一模一样。根因（代码级）：`factor_registry._compute_rsi_14/_compute_kdj_*`（factor_registry.py:130/271/286/304）在 K 线不足 15 根（RSI）或 9 根（KDJ）时返回命中兜底值 **50.0**（设计意图"中性值不干扰评分"）；`format_factor_summary`（portfolio_service.py:82-96）**渲染层不过滤该值**，`{label} {v:.2f}{hint}` 直接把 50.00 展示为「RSI(14) 50.00（中性）」——用户无法区分「真实值恰好 50」与「缺数据兜底 50」，且 RSI 50.00 的 hint 恰为「（中性）」，看上去像真实计算出的中性值。**与 round9 P1-15 只修了 filled 计数（`_factor_value_real` 排除 50 兜底）但未同步渲染层是同一链条的疏漏**：`factor_availability` 诚实显示 6/34，评分文本却照秀 50.00，两者自相矛盾。

**根因（决定性）**：策略检查数据采集时刻（08:13:33）**10 只持仓全部 `fetch_history failed: empty data — skipping`**——该时刻容器内 EM/mootdx 历史源均失败，因子只能拿 DB 恢复的少量值（filled 6/34）。**取证对照**：同一容器内、同一批 10 只标的，本轮的 `/signal` 接口（perf_diag + `_probe_signals_all`，均为容器内 localhost:8000 实测 0.1s）全部 `data_available=true` 且算出真实 RSI 64.8 / MACD 金叉——**同一容器同类源，check 时刻全空 vs /signal 时刻成功**，指向**K线源+缓存时刻的间歇性**（fetch_history 依赖的实时历史源时好时坏，check 恰好撞上失败窗口，design 赶上成功窗口）。**底层仍与容器弱源（EM/mootdx）不稳直接相关**——若源稳定，不会存在「时好时坏」窗口。**对用户最直接的观感：同一持仓在策略检查里「数据不可用」、在技术分析接口里「buy/sell 正常」，两处矛盾（§5.3）。方案落点：§10 P0-C（K线多级降级 + stale 兜底）。**

### 3.3 LLM 90s 超时的独立根因分析（问题 1 的机制深化）

**现象**：task 299（对应策略检查记录 #371）的 summary = "LLM 分析超时（90s 未返回，已用规则引擎兜底）"，日志 08:15:06 `[strategy_check] LLM analysis interrupted after 90.0s (timed out or cancelled: CancelledError) — rule fallback`。**为什么是 90s 而不是分级设计的 15/30s？**

**根因链（代码级）**：
1. **外层预算**：`portfolio_service.py:741` 用 `asyncio.wait_for(generate_strategy_check_report(...), timeout=_llm_timeout)` 包住 LLM 调用；`_llm_timeout_for`（第 550 行）按数据完整度分级：all_empty→15s / partial→30s / 完整→**90s**（round9 P0-5 从 60 提到 90，对齐设计报告 O7 验收）。
2. **分级失真（真正的恶）**：`data_quality` 的 `filled_count` 是**按标的口径**（`_has_real_factor_values`，第 1039 行）：只要该标的 factor_scores dict 里**存在 ≥1 个非中性默认值**的因子就算 filled。而静态 size 因子（`style.size.ln_mcap` 等，真实计算、非默认值）满足 → **本轮 10/10 标的均判"已填充" → `filled_count=10,total=10` → all_empty=False、partial=False → 判定"数据完整" → 90s 预算**。
   - 但按**因子口径**：34 个因子只有 6 个真实值（全为静态类别），**技术/排行类因子（RSI/MACD/KDJ 等）全部缺失**（fetch_history 全空）。API 侧 `factor_availability.filled=6/34` 是因子口径，与 data_quality 的标的口径不一致——**这就是"数据完整→90s"与"报告里 6/34 可用"看似矛盾的实际机制**。
   - 语义后果：**"只有 size 因子的残缺数据"被误判为"完整"**，LLM 明明拿到的上下文只有因子分 16-18 挤堆 + 技术信号全"数据不可用"，却给了完整 90s 预算。
3. **provider 慢 + fallback 被饿死**：`generate_strategy_check_report`（llm.py:1411-1420）→ `get_agent("strategy_check").run_json(max_retries=1, rate_limit_cap=10)` → `llm_complete_with_system`（llm.py:624）**for attempt × for provider 嵌套循环**（max_retries=1 → 2 轮 ），每个 provider 用 `provider.timeout`（= `LLM_PRIMARY_TIMEOUT=240s`，供应商配置，远大于 90s）。主 provider opencode_zen 本轮实测 60–121s 才返回（还有偶发 500）。**90s wait_for 内：主 provider 卡满 90s → 外层取消（CancelledError）→ fallback deepseek 从未轮到、重试轮不执行**。R5-1-6 当初设计本希望"2 轮 × (2s 调用 × 2 源 + 退避 ≤10s) ≈ 28s"快速失败，但因 provider 单次调用就能吃掉整个预算而失效。
4. **超时路径双记录**：llm.py:1420 捕获 `BaseException`（含 CancelledError），`portfolio_service.py:750` 也捕获，两层兜底文案都写了——failure 留痕完整，但**好 90s 被空耗**。

**研判**：这不是 provider 慢本身的问题（慢在上限之外就应快速降级），而是**"数据完整度误判给了 90s 大预算 + provider 级 240s 超时与 90s 外层预算严重不匹配 + 顺序 fallback 被饿死"三者叠加**。即使数据源正常（因子填充完善），本轮 opencode_zen 60–121s 的延迟下策略检查仍会 90s 超时——**只是本轮恰好数据也缺，掩盖了预算分配缺陷**。优化见 §10 P0-F / P1-I / P2-F。

### 3.4 设计方案行情数据与最新行情不符（用户反馈 08/08 20:59，含涨跌幅精度）

**用户反馈**：设计方案全文（方案卡表格 + 报告正文）显示的涨跌幅与行情软件最新数据不符（如「消费电子ETF +5.67%、科创50ETF +4.28%、创业板ETF +5.68%、红利低波ETF -2.01%」），且部分涨跌幅未保留两位小数。

**事实还原（多源对照）**：

| 标的 | 报告 daily_change_pct | 容器缓存(data/etf_list_cache,8/4) | 宿主缓存(backend/data,8/7收盘) | 采集实时(8/7收盘) |
|---|---|---|---|---|
| 510300 沪深300ETF | **1.13%** | 1.131 | 0.892 | 0.89% |
| 159338 中证A500国泰 | **1.77%** | 1.765 | 1.137 | 1.14% |
| 510050 上证50 | **-0.23%** | -0.234 | **+1.22%** | +1.22% |
| 563020 红利低波 | **-2.01%** | -2.007 | -0.776 | -0.78% |
| 562950 消费电子 | **+5.67%** | 5.674 | 3.553 | **+3.55%** |
| 588000 科创50 | **+4.28%** | 4.279 | 2.564 | **+2.56%** |
| 589560 科创AI | **+4.64%** | 4.644 | 1.698 | +1.70% |
| 159915 创业板 | **+5.68%** | 5.684 | 1.299 | **+1.30%** |
| 562600 医疗器械 | **0.00%** | 0.0 | 2.474 | +2.47% |
| 518880 黄金 | **-0.11%** | -0.107 | 1.103 | +1.10% |

**对照结论**：
1. **报告每个标的的 daily_change_pct 与根目录 `data/etf_list_cache.json`（最后写入 2026-08-04 15:10）完全一致**——即**报告用的 = 8/4（周二）的行情**；
2. 而 8/7（周五）真实收盘值（`backend/data/etf_list_cache.json` + 实时接口：0.89%/1.22%/-0.78%（563020 红利低波）/+3.55%/+2.56%/+1.30%...）**与报告完全不符**（510050 甚至方向相反：报告 -0.23% vs 实际 +1.22%）；
3. 报告生成于 **2026-08-08（周六）08:11**——A 股非交易日，无当日数据，本应以最近交易日（8/7 周五）收盘值为准。

**根因（代码级，完整链路）**：
1. **容器读取的快照陈旧**：`etf_scanner._etf_cache_file()`（etf_scanner.py:117-133）在容器内解析为 `/app/data/etf_list_cache.json`，而 docker-compose 挂载 `./data:/app/data` → **读取宿主根目录 `data/etf_list_cache.json`（8/4 15:10，而非 backend/data 那份 8/7）**。`fetch_all_etfs_base` 的 O1「旧快照无论新旧都先返回」（etf_scanner.py:356-376）在启动即命中 8/4 快照；
2. **refresh 扫描未覆写快照**：`_save_cache` 仅在路由（多 Provider 熔断链）**任一源返回非空结果时写入**（`if result:` 才写，etf_scanner.py:454-459），全源失败返回 stale（8/4）。8/8 周六为非交易日且容器内 EM 源不稳（本轮日志 26 次 RemoteDisconnected），refresh 大概率未成功 → 快照一直停在 8/4；
3. **S6 注入链命中旧快照**：`strategy_design.py:367-402` 三源回退中，pool（`_refresh_impl` 展平时丢弃 change_pct，market_data_hub.py:481-489）无值 → **快照（命中 8/4 旧值）** → K 线。因前两源失败/无值，快照旧值直接进入 daily_change_pct；
4. **报告无数据新鲜度标注**：方案表格列虽带 `data_fetched_at`（§3.1-1 提及），但**正文（LLM 段落）不显示「数据截至 8/4」**，用户无法区分「近期快照」与「实时」。

**涨跌幅精度问题（次要）**：
- **表格**（design_report.py:160-170）已 `f"{_dcp:.2f}%"` 两位小数（510300 +1.13% 等）✅；
- **正文（LLM 转述指数）有多处非两位小数**：`上证指数报3940.04点涨1.0%（实际1.02%）`、`深证成指涨1.4%（1.42%）`、`创业板指涨1.4%（1.35%）`、`科创50涨2.5%（2.51%）`—— LLM 自由转述截断精度（把 +1.02% 写成 涨1.0%）。

**方案落点**：见 §10 P2-G（数据新鲜度修复）、P2-H（双缓存路径修复）、P3-I（精度+新鲜度门禁）。

---

## 4. 行情分析功能测试（A股/港股/美股）

| 功能 | 端点 | 结果 |
|---|---|---|
| 综合研判 | POST /analysis/llm-report | ✅ A 63.4s / HK 58.9s / US 33.4s 全成功，报告含实时指数/板块/情绪（口径统一 37.8） |
| **AI 投顾问答** | POST /analysis/llm-advice | ❌ **3 市场全部退化为「暂无实时指数数据/暂无板块热力/市场状态未知」模板**（§4.1） |
| 板块分析 | POST /analysis/sector-analysis/stream | ✅ 200，1489 events |
| 概念分析 | POST /analysis/sector-analysis/stream | ✅ 200，2019 events |
| 个股/ETF/指数分析 | POST /analysis/symbol-analysis/stream | ✅ 5 类全出文（600519 3334 / 510300 3353 / 00700 2069 / AAPL 2333 / 000300 3170 字），无 STREAM_ERROR（P0-1 确认） |
| 搜索自动补全 | GET /market/search | ✅ A/茅台 1、A/510 9、A/沪深300 14、HK/0070 1、HK/腾讯 1、US/AAPL 1、US/苹果 1（include_stocks=true 全命中，O4 确认修复） |

### 4.1 【新高】AI 投顾问答数据槽位错配 bug（round9 §5 未暴露）
- **现象**：llm-advice 对 A/HK/US 均返回结构完整但**全部「暂无实时指数数据/暂无板块热力/市场状态未知」**——内容空洞无实际行情支撑。
- **根因（代码级实证）**：
  1. `llm_advice` router（analysis.py:368-373）仅调用 `_build_advice_market_snapshot()` 写 **`ctx["market_snapshot"]`**；
  2. `_build_advice_market_snapshot()` 在容器内生成了 **174 字符快照**（市场状态 + 情绪 + 上证/深证/创业板/沪深300/科创50 实时价）——注入成功；
  3. 但 `generate_advice()`（llm.py:876-882）第一段读 **`context["market_data"]` / `["market_regime"]` / `["market_sentiment"]`**（未注入 → 空）→ 大盘概况模板化；`market_snapshot` 只在第三段「资金面」出现；
  4. **prompt「一、大盘概况」写死「暂无实时指数数据」→ LLM 被冲突 prompt 带偏，按模板输出数据缺失**。
- **本质**：`market_snapshot` 是字符串注入槽，而 `generate_advice` 需要结构化 market_data/regime/sentiment 槽——**router 与引擎契约错配**。
- **定性**：此为**长期存在的结构缺陷**，round9 §5「llm-advice ✅」仅因该轮只验 HTTP 200/非空、未验内容而误标正常；本轮内容断言首次暴露，与 §9 盲区 1（AI 投顾内容零断言）直接关联——修复后需由 P3-A 门禁防再犯。
- **用户确认复现（08/08 21:01）**：用户操作 AI 投资顾问，回答中仍出现「暂无实时指数数据/暂无板块热力数据/市场状态未知」——与 §4.1 现象一致，**用户已实际遇到该数据缺失**（非仅诊断假设）。截图（clipboard-210140）回答含「上证指数 +2.51%（注：实为科创50 值，LLM 混叠）」等半缺失文本，印证 prompt 冲突导致 LLM 无法区分已注入的指数值。

### 4.2 报告内容质量（专业投资者视角）
- A股个股：PE-TTM 36.48 历史中上、技术面绑缚完整；ETF：基金规模 995 亿/资金净流入；US：三季度财报（营收 +16%）完整；HK：回购行为+实时价——**基本面/资金面引用准确**；
- ⚠️ ETF/指数/HK 报告「估值数据缺失」诚实降级（容器内 PE/PB 拿不到），数据完整性受限但未谎报。

### 4.3 🆕 美股/港股市场综合研判·宏观政策分析合理性存疑（用户反馈 08/08 21:11）

**现象**：美股市场综合研判第 3 部分「宏观政策分析」内容缺乏实时数据背书（OCR：政策解读偏模板化，含可疑数值如美债收益率 2.5x%），用户问「合理吗」——**不完全合理**。

**机制（代码级确认）**：
1. **「宏观政策」段的数据源是空的**：`report_worker.py:89` 调 `generate_market_report(..., all_news, [])` —— **`macro_news` 恒传空列表** → prompt 里 `### 宏观政策`（llm.py:808-812）**永不注入标题**——该段名义上存在、实际无实时宏观资讯输入；
2. **「财经资讯」是非美股特化源**：`all_news` 为财联社/新浪/东财抓取的**中文财经头条**（news_fetcher.py:307 fetch_macro_news 含新浪/东财/财联社宏观），对美股报告**可能混入 A 股/中国政策解读** → 语义错位；
3. **FRED 流动性段是唯一美股实时宏观指标**：P1-5（llm.py:837-857）注入 美债10Y/VIX/联邦基金利率——**但失败时静默不注入**（llm.py:828-829），且**只注入数字不给 LLM 提供政策叙事数据**；
4. **结论**：宏观政策段 = 中文财经资讯标题（可能错位）+ FRED 3 数字（可选）+ LLM 训练知识（过时风险）——**对美股场景缺乏专属实时宏观新闻源**，数值与政策解读的时效性/适用性无保障。

**方案落点**：§10 P2-S（美股宏观政策段加美股专属宏观新闻源 + macro_news 非空 + FRED 失败显式降级标注）。

---

## 5. 热点/自选/技术分析/资讯/因子验证

### 5.1 热点板块与个股 ⚠️ 板块热度仍有过半 0 涨跌（用户反馈 08/08 21:01）
- hot-plates 11 条（含 change/reason/lead_stocks）；sectors/heat 20 条 **9 条真实涨跌幅**（PCB +5.63%、通信 +3.76%）、**7 条 +0.00%**、**余 4 条为非零但东财未回填命中的其他状态**（9+7+4=20 闭合）；stock-hot-rank 50 条真实 pct（药明康德 +8.49%、哈药股份 +9.97%）——加载成功，但**板块热度 20 条中 7 条涨跌幅 +0.00%**（用户截图时点：CRO/CMO、中特估、在线教育、AIGC、5G、智慧医疗等；**注：0 值条数随时点/东财回填命中率波动——本地另次实测为 11 条，见 §9.2 #3，非矛盾**）；
- **根因（代码级，三层叠加）**：
  1. **财联社主源不含涨跌幅**（sector_fetcher.py:430-435 用 `lv.get_sector_heat()`，财联社热度行无 change_pct 字段）→ 靠东财回填；
  2. **回填名匹配命中率仅 8-9/20**（market.py:656-673 `_match_em_change` 精确/包含/`/` 首段三级匹配）——财联社细分概念（铜箔/覆铜板、商业航天、氟化工等）在东财无同名板块 → 0 兜底；
  3. **⚠️ ±10% 值域校验误伤真实大涨板块（关键）**：`_sector_change_pct`（sector_fetcher.py:57-69）`abs(val)>10` 返回 None → 板块**被剔除出回填 map**（sector_fetcher.py:467-468）。**板块指数单日涨超 ±10% 合法**（round9 实测医疗研发外包 +13.03%）——CRO/CMO 当日 +10.84% 恰触发 → 剔出 map → 显示 0。这正是「回填了却还是 0」的隐蔽路径：round9「8 个拿到真实涨跌」把「匹配命中」当「渲染成功」，超 10% 的命中板块实际被值域校验打成 0；
  4. **push2delay 延时源时段性残缺/限流**（market_context.py:50 锁 `push2delay`）：晚盘 push2delay 可能返回空/f3 全 0（round5 实测延时源 clist 实时字段残缺，1617 只仅 3 只有价）→ 整个 map 空 → **全部 20 行 0 兜底**（market.py:629 `or {}`）；
- **影响（用户视角）**：板块热度页大量「+0.00%」让用户误以为行情静止或系统坏了；实际是「财联社不给涨跌 + 匹配率低 + 值域误伤 + 延时源残缺」四层合成，非真实 0。
- **方案落点**：§10 P2-K（值域校验放宽 + 换主数据源为东财全量 + 前端区分 0/无数据）。

**🆕 港股热点板块首行名字为空（用户反馈 08/08 21:08）**：
- **现象**：港股市场「热点板块排行」第一行名字显示为空（截图：排名 1 只有数值无名字），其余行正常；
- **根因（脚本真实复现，非推断）**：`hk_hot_fetcher._fetch_hk_rows` 直连东财（pz=5000，f100=中文行业）实测——**f100 无行业分类的股票返回 `"-"`（单连字符）**，非空串（探测 100 条中部分个股 f100='-'）；`parse_hk_plates`（hk_hot_fetcher.py:121）兜底 `(r.get("f100") or "").strip() or "其他"` **只处理空串**——`"-"` 是 truthy 字符串不触发兜底 → 板块名就是 `"-"`；
- **「-」板块聚合 17 只无行业股**（成交额 487 亿最大）→ **按成交额降序排第一** → 前端（SectorHeatMap.vue:42 `item.plate_name || item.name`）渲染 `"-"`，视觉上像名字为空（单减号极简/近空白）；
- 同类问题：`parse_hk_hot_stocks`（141-154 行）个股 `industry` 同样会带上 `"-"`；
- **方案落点**：§10 P2-M（`parse_hk_plates` 把 `"-"/"--"/占位符 统一归并「其他」，或过滤无行业分组）。

### 5.2 自选功能 ⚠️ 部分断裂
> **编号说明**：本报告引用的 O9/O4/O6 等为 round8 复诊断（docs/archived/）的原始问题编号，round9 的 47 项方案（P 系列）即按「修复 O 项」组织，两者为同一问题的不同阶段表述——读 O 编号时可对应 round8 文档原文。
> **双 P 编号体系**：round9 方案用 `P0-1/P1-2/P2-3/P3-4`（数字后缀，47 项）；**本报告（round10）方案用 `P0-A/P1-B/P2-C/P3-D`（字母后缀）**——两者「P 前缀相同、后缀体系不同」，正文中 round9 引用均带数字后缀（如 P1-15）、round10 方案均带字母后缀（如 P2-Q），可据此区分。§7 round9 清单核对与 §10 round10 方案表为唯一对照。
- **添加成功 + 名称正确回填**（159915→创业板ETF易方达、00981→中芯国际，O9 补名 ✅）；
- **但 GET /watchlist 实时行情全 None**：容器内 enrich 5s 超时 → DB-only 兜底 → 列表 price/pct/vol 全空；
- **端点总耗时 11-14s**：响应 200 但慢（DB-only 分支后仍有阻塞），前端「组合管理」12s 窗口 requestfailed——**P0-4 只治响应端，未解决 realtime 数据 + 实际耗时偏高**。

**⚠️ 添加自选链路专项（用户反馈 08/08 21:05：添加对话框卡很久 + 添加后最新价/涨跌幅/成交变空）**：
- **现象一：添加对话框卡很久**——前端 `addItem`（WatchlistPanel.vue:266-286）依次 `await store.addWatchlist()`（POST /watchlist）+ `await fetchItems()`（GET /watchlist 全量拉取）。POST /watchlist（market.py:898）**无条件调用 `get_asset_realtime`**（A股 timeout=8s、港/指 15s，market_service.py:1154），无外层 `asyncio.wait_for`——**数据源弱时添加按钮要干等最多 8-15s** 才响应（UI 显示"添加中..."）；紧接着的 GET /watchlist 又有 5s enrich 超时，**整个"添加"交互 8-20s** 才完成；
- **现象二：添加后三列变空**——前端列表三列 `v-if="item.realtime"`（WatchlistPanel.vue:124-130），`realtime` 为 null 时显示"—"。添加后 `fetchItems()` 的 GET /watchlist 在容器内实时 enrich（批量 4s + 总 5s 超时，market.py:859-865）失败 → **realtime=None 的 DB-only 行** → 新添加（及全部）条目的最新价/涨跌幅/成交全空；
- **根因同源**：仍是**容器内实时期（mootdx 空转/EM 冷/新浪慢）**——POST 的实时验证与 GET 的实时 enrich 都撞慢源；P0-4 只优化了 GET 的超时降级（5s→DB-only），**没解决 POST 添加的无超时实时验证**，也没解决「DB-only 行前端三列空」的视觉问题；
- **顺带确认**：截图 3 新增的 159915 等 6 条（含 510300 沪深300 等）后三列同时为空——非「仅新行」，而是整个列表的实时 enrich 整体失败（DB-only 全列表），与 §6 前端「组合管理」页 /market/watchlist requestfailed 同根。

**⚠️ 添加对话框「资产类型」与市场 tab 冗余（用户反馈 08/08 21:07：是否应联动且不需用户选）**：
- **现象**：添加自选对话框有**手动「资产类型」下拉**（A股 ETF/股票、港股、美股、指数，WatchlistPanel.vue:49-51、177-181），但组件已接收 `marketTab` prop（156 行，来自 MarketAnalysis.vue 市场 tab：A/HK/US/global，76-81 行）；
- **现有自动逻辑**：搜索已按 marketTab 过滤（WatchlistPanel.vue:240-242 传 `market: marketTab`）；选中搜索结果后 `selectSuggestion`（257-261 行）**已自动设 `form.asset_type`**（HK→HK、US→US、A→'A'）；
- **冗余 / 冲突点**：
  1. 用户在「A股/HK/US」tab 内打开添加框，下拉默认恒为 'A股 ETF/股票'（assetTypes[0]）——**用户再选一次是多余的**（tab 已决定市场，搜索也按 tab 过滤）；
  2. 若用户手动把下拉改成 HK/US 但输入的是 A 股代码，`selectSuggestion` 选中后**会覆盖成 'A'**——用户手动选择被静默覆盖，易困惑；
  3. **global tab**：marketTab='global' 时搜索参数为 undefined（242 行），命中跨市场结果自动设 asset_type——此时下拉的"默认 A"与实际命中市场不同步。
- **更合理设计（用户建议，合理）**：特定市场 tab（A/HK/US）下**隐藏「资产类型」下拉，改显示只读「市场：A股/港股/美股」标签**（或打开时预置 form.asset_type = marketTab 映射，下拉仅作备用）；仅 global tab 保留选择（跨市场需确认）。搜索选中后仍由 selectSuggestion 覆盖（搜索结果比 tab 更精确）。**方案落点**：§10 P2-L。
- **连带确认（用户反馈 08/08 21:11）**：添加对话框**输入框 placeholder 示例也是 A 股的**（WatchlistPanel.vue:29 硬编码「搜索代码或名称，如 510050、贵州茅台...」），美股/港股 tab 下不随市场切换（截图：美股、港股 tab 均显示 A 股示例）——并入 P2-L ⑤ placeholder 动态化。

**⚠️ 美股 tab 添加自选：搜索补全慢且不全（用户反馈 08/08 21:10）**：
- **现象**：美股 tab 下「添加自选标的」自动补全**特别慢（冷启动等 ~4s+）**，且**不全**（有些代码搜不出来，如非龙头小盘/带后缀代码）；
- **「不全」根因（数据源 + 截断 + 归一化三叠）**：
  0. **🆕 market=US 查询返回 HK+US 混合（本地实测 08/08 21:20，最显性）**：`/api/v1/market/search?q=AAPL&market=US&include_stocks=true` 实测返回 **30 条全是港股 ETF**（02800.HK 盈富/02828 恒企等，market='HK'），AAPL 美股被挤出——**`market=US` 仅路由到 `search_hk_us`（market.py:153-156），search_hk_us 内部无 market 过滤、返回 HK+US 合并（base_pool=HKUS_ETF_MAP 混合）且截断 `merged[:30]`** → 用户搜美股常看到一堆港股，是「搜不出来」的最直接原因；耗时 **19.5s**（spot 拉取）且**不稳定**（第二次同查询 45s 超时）；
  1. **US 段数据覆盖受限**：`sync_instruments._fetch_us_list`（sync_instruments.py:211-266）东财 `stock_us_spot_em` 失败时降级**新浪仅取前 6 页 × 20 = ≤120 只**（防 897 页残留）；`fetch_us_spot_list`（china_market.py:869 等）在线源**只依赖东财、无新浪降级**——EM 不可用时 US 可搜 ≈ 静态池 30 + 本地 ≤120 只，**覆盖全美股 <2%**；
  2. **在线降级长截断**：spot 失败时 US 补搜查本地表 `limit(30)`（market_service.py:822）无排序；`merged[:30]`（841 行）上限 30；
  3. **代码/名称归一化裂缝**：新浪同步**移除点号** `sym.replace(".","")`（sync_instruments.py:254）→ `BRK.B` 变 `BRKB` 与静态池 `BRK.B` 两套码互不可搜；输入带后缀（`AAPL.US`）时 base/spot 的 `AAPL` 不匹配（未 strip 后缀）；新浪中文简名 vs spot 英文名（`苹果` vs `Apple Inc.`）两源名称分裂；
- **「慢」根因（冷启动 spot + 前端无缓存）**：
  1. **spot 缓存 miss → 4s 超时等待**：`_call(fetch_us_spot_list, timeout=4)`（market_service.py:757-758）每冷启动（缓存 miss）等满 4s；**内外层超时不一致**（外层 4s cancel，内层 run_in_thread 10s 仍跑，缓存写入滞后）→ 反复触发；
  2. **US ETF 命中时 enrich 叠加 8s**：`get_asset_realtime(US, timeout=8.0)`（market_service.py:849-852）；
  3. **前端 WatchlistPanel 自实现搜索无缓存/无 Abort/无 seq 守卫**（WatchlistPanel.vue:231-247，仅 300ms debounce）——对比 `useMarketSearch`（200ms debounce + 60s 缓存 + abort + seq），WatchlistPanel 未复用；
- **修复优先级**：数据覆盖（US 多页拉取 + spot 新浪降级）→ 归一化统一（strip 后缀/忽略点/中英文双名）→ 后端搜索缓存 → 前端复用 useMarketSearch。**方案落点**：§10 P2-Q。
- **连带确认（用户反馈 08/08 21:10）**：**美股标的分析（UnifiedAnalysis）的自动补全同样受影响**——其搜索复用 `useMarketSearch({ market: 'US' })`（UnifiedAnalysis.vue:125）+ 后端 `search_hk_us`（同 P2-Q 的 US 段），表现「像不支持补全」实为 US 段覆盖差（静态 30 + 本地 ≤120）+ 冷启动 ~4s 的后端问题；前端封装本身是完整的（200ms debounce + 60s 缓存 + abort），**修 P2-Q 后此入口同步恢复**。

### 5.3 技术分析与综合信号 ⚠️ 与策略检查矛盾
- `/signal` 接口 10 只持仓全部 data_available=true，分布 **buy 3 / sell 2 / hold 5**（有区分度）；
- `/indicators` 有真实 MA/RSI/MACD（RSI 64.8、MACD 金叉）；
- **但策略检查对同一批全部「数据不可用」+ hold**——两数据链路在容器内 K 线缓存时刻不一致产生矛盾，**同一持仓两处信号打架，专业不可接受**。

**🆕 港股热门个股技术分析弹窗数据为空（用户反馈 08/08 21:09）**：
- **现象**：港股热门个股列表点「技术分析」→ 弹窗打开但 RSI/MACD/KDJ/MA/BOLL/K线 全部显示「—」；
- **根因（前端传参 bug + 后端脚本复现**）：
  1. `SectorHeatMap.vue:125` 弹窗的 `asset-type="A"` **写死为静态字符串 'A'**（非 `:asset-type` 响应式绑定）；`openTechnical`（SectorHeatMap.vue:190-192）构造 `techModal` 时**不传 assetType**（热门个股 item 虽有 `market: 'HK'` 等字段，hk_hot_fetcher.py:170-172，但未用于弹窗）；
  2. → 前端 `marketApi.indicators(symbol, 'A')` / `chart(symbol, 'A')` 把**港股代码按 A 股查询**（如 02800 走 A 股 6 位代码路径）→ `fetch_history(symbol, 'A')` 不匹配 → 空 history → `compute_all_indicators` 返回 {} → 指标全空；
  3. **后端港股链路本身正常**（脚本直连 `get_history('02800', 'HK')` 返回 320 行、RSI 40.34——脚本侧计算时刻的 RSI，与 §9.2 接口实测 59.67 为不同时刻/口径，均证明 HK 链路可用；MA 正常）——纯前端传参错误；
- **关联**：A 股热门个股技术分析正常（asset_type='A' 正对）；港股/US 热门个股弹窗均受影响；
- **方案落点**：§10 P2-N（弹窗 assetType 按 item.market 动态传递 + 默认从 marketTab 推断）。

**🆕 港股标的分析：盈富基金（02800）分类识别缺失（用户反馈 08/08 21:09）**：
- **现象**：港股标的分析报告把盈富基金（02800，恒指 ETF）按普通标的（股票/ETF 通用模板）输出，无「ETF/基金」专属识别——用户指出它应是**港股 ETF**（Tracker Fund，跟踪恒生指数）；
- **根因（代码级 + 实测）**：
  1. **instruments 港股段无独立 ETF 采集**：`sync_instruments.py:102-103` 分段 = `fund_etf_spot_em`（A股ETF）/ `stock_hk_main_board_spot_em`（**港股一律 asset_type='stock'**）/ 美股——港股 ETF 没有独立段（stock_hk 列表含港股主板基金也会被标 stock，或缺失）。实测 `Instrument.symbol like '%02800%'` = **0 条**（盈富基金不在 instruments 表）；
  2. **get_asset_realtime('02800','HK') 无 ETF 身份**：返回 `asset_type='HK'`（市场级）、`type=None`、`market=None`——标的种类（etf/stock）维度缺失；
  3. **前端 assetType 无 ETF 判定**：`UnifiedAnalysis.vue:374` `assetType = marketTab==='HK' ? 'HK' : ...`——**只区分市场不区分证券种类**（A 股有 etf 语义，港股一律 'HK'），02800 无法按「港股 ETF」分流到基金分析模板；
- **影响（用户视角）**：盈富基金等港股 ETF 在搜索/分析里无 ETF 识别，标题无「ETF」标签（截图顶部仅「股票/ETF 分析（HK）」通用徽章，盈富混在股票框架）；依赖 ETF 专属数据（基金规模/净值/折溢价/跟踪误差）的路径都缺失；
- **方案落点**：§10 P2-O（港股 ETF 采集 + asset_type 语义扩展）。

### 5.4 资讯页面 ✅ 改善
- level 分布：headlines {1:7, 2:2, 3:4, 4:4, 5:3}——L5 占比 15%（round9 50% 失真改善）、有 L1；stars 独立维度（4:13/5:7）——P2-1 部分达成；
- ⚠️ L1 仍占 35%（头条多为次要宏观/财经快讯），分级规则保守。

### 5.5 因子模型 ✅ 大幅改善（用户反馈 08/08 20:59：13 待关注 / 2 无数据）
- summary：**valid=12 / warn=13 / no_data=2 / static=6 / avg_ic=0.0206**——no_data 从 round9 **6 项降到 2 项**；
  - **no_data 仅剩** tracking_error（缺 benchmark_close）、shares_change（缺 shares_change_20d）——**P1-8/P1-9 数据源接入未做**（详见下方上游诊断）；
  - **折溢价率已消除 no_data，IC=0.1321**——**P0-6/P0-7 IOPV 链修复确认** ✅；
  - **sentiment 三因子 static**（reason「市场级因子不参与截面 IC」）——**P1-10 确认** ✅；
- **warn=13 的成分细分**（用户视角核心）：**12 个真实负 IC + 1 个弱 IC**——
  - **真实负 IC（12）**：change_pct -0.45 / amount_stability -0.29 / price -0.12 / bollinger.bandwidth -0.56 / sma_60 -0.23 / sma_20 -0.17 / sma_10 -0.09 / sma_5 -0.08 / vwap -0.23 / kdj.j -0.38 / atr_14 -0.43 / news_heat -0.03——**当前市态下技术/价格类因子预测方向反向，是真实截面结果**（round8 同型：sma_60 -0.44 等技术类当前市态反向失效）；
  - **弱 IC（1）**：vol_ratio 0.001 远低于阈值 0.02——**「真弱因子」非数据问题**（ETF 同质化+量比差异小，round9 P2-9 已确认口径本身正确；**round10 未复核**，见 §7 分类说明）；
  - ⚠️ **展示层缺陷**：`_status_of`（factors.py:108-112）把「|IC|<0.02 弱相关」与「IC<0 强负向」**合并成一个 warn 通道**，导致页面 13 个「待关注」语义混杂（12 个是负向警示、1 个是弱相关），专业用户易误读为「13 个因子都不可用」——实际 12/33 是有效正因子，分配引擎按聚合层均值消费（factor_registry.py:953-1008），**不区分这些状态**；
- **no_data 上游诊断（2 个，均为已知遗留 P1-8/P1-9）**：
  - `etf.tracking_error` ← benchmark_close：`_enrich_symbol_extra`（market_data_hub.py:1244-1277）已按 `_WIDE_BASIS_INDEX_CODES` 映射宽基指数，round9 P1-8 补了 512880→399975、512010→000933，但**候选池行业/主题 ETF（半数组）映射未覆盖 → 0 命中**，弱源下整体超时静默降级 → benchmark_close=None；
  - `etf.shares_change` ← shares_change_20d：主源 `fund_etf_hist_em` 无份额列、降级 `fund_etf_spot_em` 只有最新份额无历史 → **无免费公开的历史份额源**（P1-9 数据源缺陷，非代码 bug）；
- **avg_ic 滚动性**：round10 探测时刻 avg_ic=+0.0206，用户截图时刻显示 0.0141——IC 为滚动窗口逐步累积，同一因子不同时段数值变化属正常（窗口内新增样本更新秩相关）；
- **影响评估（用户视角）**：13 warn + 2 no_data 对**用户使用影响偏低**——分配引擎按聚合层均值（技术层均值仍可用），no_data 因子不参与 scoring、不拉低方案；实质影响是**专业观感**（界面 13 个「待关注」让用户误以为系统不可靠）+ `/admin/factor-health` 11s 性能黑洞（§8.2）。**优化落点见 §10 P1-C（负 IC 淘汰/降权）、P1-J（warn 通道细分 + 数据源接入）。**

### 5.5b 因子健康页 UI 与用户反馈对照（§5.5 附属小节，编号 b 表示归属 5.5）
- 用户截图（08/08 20:59）顶部状态栏 = `33 | 12 | 13 | 2 | 6 | 0.0141`（活跃 33 / valid 12 / warn 13 / no_data 2 / static 6 / avg_ic 0.0141）——**与 round10 §5.5 诊断完全一致**（warn 13 / no_data 2），无新的状态漂移；
- 前端「待关注」红字提示语义单一（负 IC / 弱 IC 混在一个标签里），「无数据」无 tooltip 说明上游原因——用户无法判断「是系统问题还是数据源缺失」。

---

### 5.6 美股热点排行数据缺失（用户反馈 08/08：看看有没有办法补上）

**现状（代码级已确认）**：美股热点三端点**全部硬编码返回空**——round6 F16 决策「US 暂不支持」：
- `/market/hot-plates`（market.py:611-614）：`market_data_hub.get_hot_plates`，**US 返回空列表**（注释「US 返回空列表」）；
- `/market/sector-heat`（market.py:620-...）：`market_data_hub.get_sector_heat`，US 暂不支持；
- `/market/stock-hot-rank`（market.py:677-681）：`market_data_hub.get_stock_hot_rank`，**`market.upper()=='US'` → `return []`**（market_data_hub.py:1812-1816）。
- 美股 tab 下 SectorHeatMap 三 tab（hot/heat/stock）全部显示「暂无数据」。

**可补性分析（有现成数据源）**：
1. **美股热门个股（stock tab 与 hot tab）**：`china_market._fetch_us_spot`（china_market.py:863-892）已用**东财 `stock_us_spot_em`** 拉全量美股 spot（含 代码/名称/最新价/涨跌幅/成交量/成交额/总市值等列），但当前**只提取前三字段**（879-882 行只留 symbol/name/name_en）——**只需在 rows 补 price/change_pct/amount/mcap 字段**，即可按成交额/涨跌幅/波动率排序取 TOP N 作为美股热点（成交额榜 = 美股无门槛版「富豪榜」，符合用户习惯）；复用 6h/1h 缓存，几乎零额外成本；
2. **美股板块热度（sector-heat）**：东财有 `stock_sector_spot`（美股行业板块实时）接口（akshare 支持），按板块成交额排序可取美股行业热点（约 11 个 GICS 行业）；
3. **美股概念（hot-plates 的"涨停"语义不适配）**：美股无涨跌停，hot-plates 的「涨停/封板」概念对美股无意义——建议美股 hot tab 直接复用热门个股榜单（或标注「美股无涨跌停」），不做涨停语义。

**方案落点**：§10 P2-R（美股热点：复用东财 spot_em 补全字段 + 美股板块接口 + 前端 tab 语义调整）。

**🆕 美股标的分析·板块模式补全返回 A 股板块（用户反馈 08/08 21:11）**：
- **现象**：美股 tab 下「标的分析」切到板块/概念模式，自动补全下拉**返回的全是 A 股板块**（BK1326 等，opt-type 显示「A」）；
- **根因（代码级）**：kind='sector' 走 `_search_sectors`（market.py:99-100）——**板块搜索从无条件返回 A 股板块表（sectors 表），无 market 过滤**（美股无板块数据源，round6 F16「US 暂不支持板块」）；前端美股 tab 传 `market: 'US'` 但 `kind='sector'` 时后端忽略 market（market.py:98 注释「板块/指数无市场维度」）→ 美股板块模式下补全=全部 A 股板块；
- **影响**：用户美股 tab 板块分析搜任何词都是 A 股板块，无法选美股板块（美股板块本质无数据源，round8 O4/round10 §5.6 同）；
- **方案落点**：§10 P2-T（`_search_sectors` 加 market 参数：美股 tab 返回空+前端提示「美股暂不支持板块分析」而非显示 A 股板块）。

---

## 6. 前后端数据断裂排查

- **8 页面前端走查：0 JS console error**；
- **唯一断裂 = 「组合管理」页 2 个请求（/portfolio/tasks、/market/watchlist）12s 内 requestfailed**——慢后端软断裂；
- nginx `/api` 代理 200、`/api/v1/ws` 代理配置正确；
- ⚠️ **nginx `/health` 被 try_files 兜底为前端 index.html**（SPA 吞掉健康检查路径，非致命）。**方案落点：§10 P2-B。**

---

## 7. round9 清单核对（47 项逐项唯一分类，详表见 diag/n2/round9_verification_n2.md）

> 每项只归一类；P0-2（EM 弱源）本轮预热段通过、但全链路仍弱源 → 归「部分修复」；P1-4（预热门禁）墙钟代码已加但本轮预热未触发 30s 告警线、无实测 WARN 行为 → 归「未专项验证」；P2-9（vol_ratio）本轮 IC≈0.001（滚动窗口，不同时刻 0.0002~0.001）仍无 warn 处理、round10 未复核（round9 已确认口径正确）→ 归「部分修复」；合计 23+14+2+8=**47 闭合**。

**✅ 确认修复（23）**：P0-1、P0-3、P0-6、P0-7、P0-8、P1-1、P1-2、P1-5、P1-6、P1-7、P1-10、P1-12、P2-3、P2-4、P2-7、P2-8、P2-10、P3-1、P3-4、P3-6、P3-7、P3-8、P3-11

**⚠️ 部分修复（14）**：P0-2（EM 弱源：预热段已恢复但仍影响下游）、P0-4（watchlist 3.0s 达标但实时数据空）、P0-5（超时 90s+个性化建议，但 LLM 仍不稳定）、P0-9（data_fetched_at 字段已加，表格未标注）、P1-3（负 IC reason 文案已改但未淘汰）、P1-13（tech_signal 显式兜底已加，但数据源空致全「不可用」）、P1-14（industry 兜底已加，容器弱源下未生效）、P1-15（fallback 字段已算，report_text 未用）、P2-1（L5 50%→15% 但 L1 仍 35% 偏高）、P2-6（mootdx 仍空转）、P2-9（vol_ratio IC≈0.001 仍无 warn 判定，round10 未复核）、P3-2（watchlist 耗时门禁过但未测 realtime）、P3-9（时间戳字段在，表格断言未落地）、P3-10（tech_signal 非空断言过，但 filled 与标题一致性未断言）

**❌ 未修复（2）**：P1-8（benchmark_close 未接入）、P1-9（shares_change_20d 未接入）

**➖ 未专项验证（8）**：P1-4（预热墙钟 WARN 线）、P1-11（本地快照路径，容器路径正常未触发）、P1-16（空组合诊断，本轮组合非空）、P2-2（新闻情绪口径）、P2-5（MACD 尾截断）、P2-11（历史孤立 check 记录）、P3-3（A01 墙钟线）、P3-5（前端 SSE 错误态测试）

---

## 8. 性能（前端 Lighthouse + 后端 perf_diag）

### 8.1 前端 Lighthouse（13.4.1，desktop preset）
| 页面 | 本轮 | round9 | 变化 |
|---|---|---|---|
| 首页 / | **52**（CLS 0.389 / TBT 640ms / LCP 3.5s） | 90（CLS 0.004） | **-38 严重劣化** |
| 行情分析 /market-analysis | 89（CLS 0.001） | 100 | -11 |
| 组合管理 /portfolio-analysis | 73（TBT 800ms） | 99 | -26 |

> 测量方法：lighthouse 13.4.1（desktop preset，throttling 默认桌面档），每页单次运行（与 round9 口径一致，round9 亦单次）；CLS/TBT/LCP 为 audit 原始值。
> portfolio-analysis 的 TBT 800ms 主要来自 echarts 多图表渲染 + 大表格（36 行持仓 × 多列）主线程开销，与首页同根（主线程 Script 1.2s + Style&Layout 927ms 的构成相似）；其 CLS 0.001 正常。P0-D 的「锁容器高」修复同时覆盖 portfolio 页图卡（验收含 3 页 CLS<0.1），不单独列项。

**首页 perf 52 < F18 硬门禁 60，CLS 0.389 >> 0.1**。根因：
- **CLS 0.389**：dashboard `<div class="summary-grid">` 主内容网格（Lighthouse cls-culprits score 0.3885）——图表/卡片容器**未预留高度/宽度**，数据加载后位移；
- **主线程 3.0s**：Script Evaluation 1.2s + Style & Layout 927ms（echarts + 骨架屏开销）；
- 相对 round9 劣化主因：**首页骨架屏/图表容器布局未锁 + 慢后端（watchlist/calculate）加载期多次重布局**。

### 8.2 后端全链路（perf_diag.py，49 端点）
48/49 通过（1 个 422 body 空预期）。**8 个 >1s**：

| 端点 | 耗时 | 对照 |
|---|---|---|
| `/admin/factor-health` | **10964ms** | **新黑洞（round9 未记录）** |
| `/portfolio/calculate` | 5059ms | 5052ms（持平） |
| `/market/indices/global` | 3929ms | 4367ms（改善） |
| `/market/stock-hot-rank` | 3433ms | 4711ms（改善） |
| `/market/watchlist` | 3041ms | 29856ms（**29.9s→3.0s 巨大改善**） |
| `/market/chart` | 1932ms | 2092ms |
| `/market/wind` | 1591ms | 1831ms |
| `/portfolio/tasks` | 1253ms | 1387ms |

**watchlist 29.9s→3.0s（P0-4 生效）**，但仍 >1s 且实时数据空；**factor-health 10.9s 为新性能黑洞**（逐因子健康探测串行/自采）。**方案落点：§10 P1-A。**

> **口径说明**：perf_diag 的 watchlist 3041ms 为**缓存热态单端点**测量（端级 3s 短缓存 + quote 5s TTL）；§5.2 的「总耗时 11-14s」为**前端冷启动 + 与 /portfolio/tasks 等并发**场景（playwright 走查实测），两者相差 3 倍是缓存状态与并发负载差异，非数据矛盾。P0-E 的「≤3s」验收以 perf_diag 热态单端点口径为准；「前端冷启动+并发走查 ≤6s」为 P0-E 的端到端体验验收（§10 P0-E 验收列）；P1-E 负责加载态视觉（空行显示「—」+tooltip），两者职责互补不冲突。
> 另注：round9 §10 的 `/market/realtime`（2314ms）本轮已退出 >1s 列表（缓存热后 0.1-1s 级），故不在上表重复对照。

---

## 9. 测试防护体系为何未识别（8 类盲区，本轮 8 个问题均落盲区）

1. **AI 投顾内容零断言（新）**：verify_e2e section_analysis 对 llm-advice 只测 HTTP 200/非空字符串，**不断言 advice 含实时行情数据**（指数名/值/情绪）→ llm-advice 数据槽位错配（§4.1）在 3 市场全模板化时通过；
2. **策略检查 filled 与标题一致性零断言（换形式）**：round9 P3-10 断言 tech_signal 非空（本轮「数据不可用」满足）与可用占比，但 **未断言 report_text 标题「N/M 可用」与每只 holdings factor_availability.filled 一致** → P1-15 假正常换形式（10/10 vs 6/34）漏网；
3. **watchlist realtime 零断言（延续）**：P3-2 加了耗时门禁但 **不测 realtime price/pct 非 None** → 列表实时全空仍通过；
4. **Lighthouse 门禁平时不跑（延续）**：F18 硬门禁只在 round8 专项跑过，**后续 commit 未接 CI** → 首页 perf 52 / CLS 0.389 回归无人发现；
5. **负 IC 淘汰零门禁（延续）**：factors/active 只测列表非空 + reason 文案，**不断言「强负 IC NOT 在活跃列表」** → O6 未落地静默通过；
6. **容器弱数据源无模拟（延续/核心）**：所有单测/e2e 用「完美数据」mock，**从不在容器内模拟 EM 源弱/TLS 拦截** → P0-2 下游连锁（策略检查因子空、watchlist 实时空）在真实弱源下零拦截；
7. **行情新鲜度/涨跌幅精度零断言（新，§3.4）**：verify_e2e/e2e 从不断言设计 `daily_change_pct` 与最新交易日一致、也从不断言涨跌幅两位小数——「非交易日/弱源下静默复用 >2 日旧快照」与「LLM 转述截断精度」全无门禁拦截。
8. **跨市场搜索返回的「market 一致性」零断言（新，本地实测 08/08）**：verify_e2e **F15**（L270-283）跨市场搜索门禁 `ok = len(r.json()) > 0`（**只验非空**）、**O13** 名称搜索门禁（L289-306）`_hits > 0`（同样只验非空）——**均不验证返回条目的 `market` 属于查询市场**；后端单测 `test_search_budget_usname.py` 用 **mock 白名单**构造 `fake_search_hk_us`（只返回 US 数据），测「精确匹配排首（排序）」而非「`market=US` 过滤」——真实「market=US 查询返回 30 条 HK 股票、AAPL 美股被挤出」的 bug 在 mock 数据里不可能出现 → e2e 非空即 PASS、单测 mock 命中即 PASS，双层放过。

> 根因归：**门禁验证「自述行为」而非「生产形态（容器）+ 真实混合数据 + 跨模块消费」**——尤其「模块间契约（router 注入槽 vs 引擎消费槽）」「容器弱源降级链」「数据新鲜度/精度的口径一致性（快照 vs 实时 vs 非交易日）」「跨市场搜索返回的 market 与查询市场一致（市场语义）」「断言粒度停留在『有结果/非空』而非『内容正确』」。

### 9.1 测试防护体系冗余审计（2026-08-08 专项 review）

**背景**：226 个后端测试文件（pytest 1112 passed）+ 117KB verify_e2e（`backend/scripts/verify_e2e.py`，下文行号均指此文件）+ 42 个前端 spec，是长期迭代累积的防护资产，但存在大量新增。审计结论（带 file:line 证据）：

**A. 强重复文件组**（同一模块 N 个文件各写一套 mock）：
- **search 组 6**：`test_z29_search`（主）+ `z20_search_sort`/`search_stock_by_code`/`us_search_fallback`/`search_budget_usname`/`search_sector_index`——全部测 search 跨市场/代码/名称命中；`_FakeSession`(execute→scalars→all) 模式重复 6+ 遍；
- **pool_manager 组 4**：`test_pool_manager` + `_layer`/`_phase2`/`_phase3` 同模块拆 4 文件；
- **market_data_hub 组 4**：`_realtime`/`_pool`/`_news` + `test_market_context` 各自重写 `_make_hub()` mock；
- **strategy_check 组 11**：`_fallback`/`_llm_fallback`/`_llm_timeout`/`_timeout`/`_partial_data`/`_divergence`/`_industry`/`_summary`/`_async`/`round9_strategy_check`/`z26_strategy_check_coverage`——重复测 LLM 超时降级/risk_warnings/report_text 三类；
- **news 组 11**：`_classification`/`_level_classification`/`round9_news_level`/`_impact`(3)/`_sort_order`/`_macro_filter`/`_pipeline`/`stock_news_keys`/`news_heat_scope`——level/stars/impact 三档拆 4 文件，每文件重写 `fake_run_json`；
- **global_indices 组 2+**：`_global_index_defs` AsyncMock 同一 pattern 重复 10+ 次。

**B. verify_e2e 内部重复检查**（同一端点 ≥2 次）：
- `/market/search` **9+ 次**（L257 / L270-283 / L289-306 / L888 / L2131-2157 / L2169 / L2191），L257-306 与 L2131-2157 语义几乎相同；
- `/portfolio/designs` 6 次（L316/L350/L426/L1399/L1676/L2055）、`POST /design-async` 4 次（L388/L1001/L2075 及轮询内复调，含两套轮询逻辑）、`/factors/ic` 3 次、`/admin/factor-health` 3 次、`/admin/sources/health` 3 次、`/market/indices/global` 3 次、`/health` 多次。

**C. e2e 与单测重复覆盖**：
- `section_design_quality_gate`（L1672-1700 import `validate_design_quality` 逐条断言）与 `test_design_quality_gate.py` 逐字重复；
- `section_snapshot_health`（L1848-1871 save/load/clear）与 `test_snapshot_service.py` L28-46 内容直接复制；
- `/factors/ic`、`sources/health`、`sectors/heat`、编码等 e2e 检查与各自单测重复。

**D. mock 退化**：约 140-160 个测试文件直接 `MagicMock/AsyncMock/patch`；**`_FakeSession`+FakeResult 模式重复 10+ 文件**（每文件重写 execute/scalars/all 4 件套）；`FakeHub` 重复 10+ 文件——**R73 治理宣称的 4 个 conftest fixture（mock_akshare/mock_hub/mock_run_sync/mock_registry_health）只有 `test_shared_fixtures.py` 自引用，业务测试全部未迁移 = 死代码**。

**E. 无价值断言（空转）**：纯 `status_code==200` 位点约 40 处（test_warmup_status 6 用例、test_sector_heat 等）、`len(x)>0` 空转约 25 处（test_report_quality:123/139/262 等）、`test_ssl_session.py` 全文（测实现细节恒绿）、`test_remaining_fixes.py::test_p01_theme_css_has_loading_styles` 竟测前端 css（范围外垃圾测试）。

**治理方案（见 §10。P3-J 测试冗余治理）**：合并 6 强重复组为 10 个文件（search 6→1、pool_manager 4→1、market_data_hub 4→1、strategy_check 11→3、news 11→3、global_indices 2→1）、抽 `fake_async_session`/`FakeHub` conftest 共享、清理 40 处空转与范围外测试、verify_e2e 去重（search/designs/ic/factor-health/sources 三连收窄到单次）、e2e 重复的单测级检查删除以快为准。

### 9.2 本地 dev 进程实测复现汇总（2026-08-08 21:2x）

用户反馈后，直接用**本地 dev 进程（后端 localhost:8000）**逐一实测——确认以下问题**本地同样存在**（非容器专属），为方案 P0-A/P0-E/P2-J/P2-K/P2-M/P2-N/P2-Q/P2-R 提供实时铁证：

| # | 实测端点 | 结果 | 对应方案 |
|---|---|---|---|
| 1 | `GET /market/search?q=AAPL&market=US` | **返回 30 条全是港股 ETF**（02800.HK 等），AAPL 美股被挤出；耗时 19.5s，重试 45s 超时 | P2-Q |
| 2 | `GET /portfolio/watchlist` | 14 条自选 **realtime price 全 None**，端点耗时 15.1s | P2-J/P0-E |
| 3 | `GET /market/sectors/heat?market=A` | 20 条中 **11 条 change_pct=0**（CRO/CMO、商业航天、氟化工等） | P2-K |
| 4 | `GET /market/sectors/heat?market=HK`（及 hot-plates） | **首行 name='-'**（chg=-1.15，17 只无行业股聚合），用户见"名字为空" | P2-M |
| 5 | `GET /market/stock-hot-rank?market=US` | **返回 0 条**（round6 F16「US 暂不支持」） | P2-R |
| 6 | `GET /market/indicators/02800?asset_type=HK` vs `=A` | HK：data_available=True **rsi=59.67**；A：data_available=False「K线数据不足」——**同一代码传对 market 即出指标，前端写死 'A' 才空**（P2-N 铁证） | P2-N |
| 7 | `POST /analysis/llm-advice`（US） | 12.9s 返回 554 字，含「**暂无实时指数数据**」「市场状态标记为**未知**」「暂无板块热力数据」——§4.1 槽位错配实时复现 | P0-A |

**结论**：7 项**后端可实测的用户反馈场景**在本地 dev 环境全部复现（非容器专属；其余用户反馈如评分一致/行情陈旧/UI 联动属前端或非接口可测场景，不在本表），其中 #6（P2-N）用双向对照**锁定为纯前端传参 bug**、#1（P2-Q）**锁定为 search_hk_us 无 market 过滤**——这两项从"推断"升级为"实测定性"。

---

## 10. 优化方案（未实施）

> **根因处理说明**：容器内 EM 源 TLS 拦截（round9 C4/P0-2）是下游多数数据完整性问题的**源头**。round9 P0-2 曾给出三条候选路线（curl_cffi 换指纹 / mootdx+bestip 降级为主链 / 容器出口走宿主代理），**本轮方案不重复排期该根因项**——EM 根因项**挂进 round11 专项排期**（本报告 §10 仅做弱源下游容错，不假装从源头解决）；P0-C/P2-E/P3-F 做「弱源下的下游容错 + 诚实降级 + 门禁」，**执行层需注意：P0-C 的 stale 兜底只是把「故障」降级为「弱源可用」，根因仍在，round11 需专项落地 round9 P0-2 三条候选路线之一**。

### P0（数据完整性/功能阻断）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P0-A | **AI 投顾数据槽位错配**（§4.1，用户已复现 08/08） | `llm_advice` router（analysis.py:368-373）改为：① **同时注入全部引擎消费槽**——`market_data`（结构化列表：`[{name, price, change_pct}...]`）、`market_regime`、`market_sentiment`、`hot_plates`、`sector_heat`（复用 `_build_advice_market_snapshot` 内部已取的结构化数据，不重复采集）；② **同步删 `generate_advice`（llm.py:876-882）第一段「暂无实时指数数据」硬编码占位**，改为「若注入为空才显式降级文案」；③ 保留 `market_snapshot` 字符串槽（资金面段用） | llm-advice 对 3 市场返回**不再出现「暂无实时指数数据/暂无板块热力数据/市场状态未知」**；含真实指数名+值（如「上证指数 3940.04 +1.02%」）；单测断言 3 市场 advice 文本不含「暂无实时/未知」；e2e 断言同上 |
| P0-B | **策略检查报告标题 vs 逐项 filled 矛盾**（§3.2-2） | report_text 模板（portfolio_service.py:1285）改吃 `data_quality.fallback_count/ratio`，标题按「真实 filled/total 只可用（其中 N 只全兜底）」；全兜底时不报「N/M 正常」 | 全兜底场景不再出现「10/10 可用」；报告明示真实覆盖率 |
| P0-C | **策略检查 fetch_history 数据源脆弱 → 因子/信号全空**（§3.2 根因） | factor_registry.compute K 线采集加多级降级 + 失败时用 cache/上次成功拉取兜底（标注 data_source=stale）；若 10/10 全空则明示「数据源不可用」 | 容器弱源下 filled 不再骤降 6/34（**有 stale 缓存时 filled ≥ 上一轮值**；无缓存冷启动时全空 → 文案诚实标注「数据源不可用」） |
| P0-D | **前端首页 perf 52 / CLS 0.389**（§8.1） | Dashboard `summary-grid` 与各图卡容器锁 aspect-ratio/min-height（骨架屏与真数据同构替换）；echarts init 前锁容器高 | 首页 perf ≥60；**首页/行情/组合 3 页 CLS 均 <0.1**（Lighthouse 复测，portfolio 页图卡同覆盖） |
| P0-E | **watchlist 实时空 + 耗时偏高**（§5.2） | enrich 超时后**降级到单标的轻量快照（5s TTL quote 缓存）**回填 realtime；DB-only 时前端标注「行情加载中」 | 列表 10 条 realtime 全非 None（缓存热时）；perf_diag 热态单端点 ≤3s；**前端冷启动+并发走查 ≤6s（playwright 实测，冷启动口径见 §8.2）**，不再 requestfailed |
| P0-F | **LLM 90s 超时：数据分级口径误判**（§3.3-2） | `_has_real_factor_values`（portfolio_service.py:1039）改为按**技术/排行类因子覆盖率**判定（如 realtime 类因子非空 ≥60%）而非"任一真实因子"（size 静态因子不再撑起"完整"）；`_llm_timeout_for` 同步改为技术因子口径分级 | 本轮场景（fetch_history 全空、仅 size 静态因子）`_llm_timeout_for` 返回 30s 而非 90s（单测断言"仅静态因子 → partial → 30s"）；LLM 兜底不再无谓等满 90s |

### P1（数据源/完整性补全）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P1-A | factor-health 10.9s 黑洞（§8.2） | 逐因子健康探测加缓存/并发/短路（同 watchlist 模式），慢源不阻塞 | factor-health ≤2s |
| P1-B | design 表格「今日涨跌」无显式时间戳（§3.1-1） | 报告表格列加「今日涨跌（截至 data_fetched_at HH:MM）」 | 表格可见时刻标注 |
| P1-C | 负 IC 强因子未淘汰（§5.5/O6） | 负 IC 且 \|IC\|≥0.05 的因子从 active 降权/下架（inactive 列表），reason 标注「负向预测已下架」 | factors/active 无强负 IC 活跃项 |
| P1-D | 卫星层负 factor_score 入选（§3.1-3） | 卫星层对 factor_score ≤ -0.3（约当于 |score| 显著为负区间，参照本轮 562870 -0.53 等）的标的不给权重（或降级并列标注） | 卫星层无 factor_score ≤ -0.3 的活跃标的 |
| P1-E | watchlist realtime None 前端体验（§5.2） | 前端列表无 realtime 时显示「—」+ tooltip「行情加载中（数据源弱）」 | 自选页有明确加载态 |
| P1-F | AI 投顾 L1 分级偏高（§5.4） | 校准 level 规则（时效/来源权重/量级），降低低权重快讯的 level 或改 stars | L1 占比 <25% |
| P1-G | 策略检查 industry 全空（§3.2-3） | industry_map 候选池空时用 instruments 表行业字段 + ETFClassifier 独立兜底（容器弱源下 fallback 可用） | 数据源可用时行业缺失权重 <20%（维持 round9 P1-14 阈值）；弱源下 <50% 且报告明示「行业数据降级」 |
| P1-H | 防御型证券 ETF 高贝塔定位（§3.1-4） | 防御型卫星去除非低波标的或报告明示风险 | 报告明确披露 |
| P1-I | **LLM 90s 超时：provider 超时与预算不匹配 → fallback 饿死**（§3.3-3） | `llm_complete_with_system`（llm.py:624）增加可覆写 `provider_timeout`（默认保持 240s，策略检查场景传 30-40s）；配合 P0-F 的 30s 预算，在预算内依次尝试主 provider ×2 轮（30+30 含退避）+ fallback ×1（30s） | 策略检查单次 LLM 调用在 provider 慢时：主 provider 30-40s 超时即切 fallback；全 provider 失败总耗时 ≤90s（单测断言 provider_timeout 透传 + fallback 被调用） |
| P1-J | **因子 warn 通道语义混杂 + 2 个 no_data 数据源接入**（§5.5） | ① `_status_of`（factors.py:108-112）拆分为 `weak`（\|IC\|<阈值）与 `negative`（IC<0）两状态，UI 分列展示「弱相关 N / 负向 M」而非合并「待关注」；② no_data tooltip 明示上游原因；③ benchmark_close 映射扩到候选池全部行业/主题 ETF（`_WIDE_BASIS_INDEX_CODES`），消除 tracking_error 0 命中；④ shares_change 评估降级方案（「当前份额」单期因子 or 标注永不接入） | 因子页「待关注」区分弱/负向；tracking_error 有样本数 >0；shares_change 有明确状态与原因文案 |

### P2（质量/体验）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P2-A | LLM 不稳定致投顾/策略检查间歇失败 | LLM 本地缓存（同 query+同 market_data 短 TTL）；provider 多路（opencode_zen→deepseek fallback 已有）；失败自动重试 1 次 | 同 query 短时重复命中缓存；500 自动重试 |
| P2-B | nginx /health 被 SPA 兜底 | nginx 加 `location = /health { proxy_pass http://backend:8000; }` | nginx /health 返回后端 JSON |
| P2-C | 策略检查 10/10 全 hold 无真实信号 | 规则兜底消费真实 /signal（buy/sell/hold 有区分），按信号方向 + 因子分生成非 hold 差异化建议 | 无 LLM 时非 hold 建议占比 ≥30%（对照 10 只中真实 buy/sell 3+2=5 只）；10 只建议不得与 /signal 方向相反的 hold 模板重复 90% 以上 |
| P2-D | 报告时间戳前端展示 | 设计详情卡片/报告头显示 data_fetched_at（人类可读） | 用户可见采集时刻 |
| P2-E | 容器弱源降级链路 QA | docker_smoke.py 增加弱源模拟（EM 不可达），断言降级链路（pool/design/hot/signal/watchlist）不崩溃且诚实降级 | 弱源模拟下各端点 ≤10s 内返回且非崩溃（明确标注降级状态） |
| P2-F | **LLM 90s 超时：LLM 结果短缓存**（§3.3 优化） | 复用 `_strategy_check_cache`（portfolio_service.py:509）缓存**成功的 LLM 报告**（key=持仓+capital+provider，短 TTL，如 5min）；重复检查直接命中，避免每次 60-120s 重算 | 同持仓重复检查第 2 次起命中缓存 <1s（单测断言同 key 短时重复调用不再调 LLM） |
| P2-G | **设计报告行情数据新鲜度（§3.4）** | ① 修 `strategy_design.py` 注入链：pool/快照/K线三源均返回真实 `change_pct` 时，取**最新可用**（K线差分优先于文件快照，快照按 ts 判新旧）；② 设计生成时若命中非交易日/非当日快照，报告正文 + 方案卡显式标注「行情截至 YYYY-MM-DD HH:MM（当日无数据，为最近交易日）」；③ `daily_change_pct` 注入点打印数据时刻日志 | 报告 `daily_change_pct` 与最近交易日收盘一致（对 8/7 收盘重建 456 断言 510300=0.89/588000=2.56）；非当日标注可见；`_save_cache` 失败/stale 时不静默透传旧值 |
| P2-H | **双缓存路径割裂修复（§3.4 根因）** | 统一 `_etf_cache_file()` 路径：容器（/app/data）与宿主（backend/data）命名一致——建议容器 volume 挂载指向 `backend/data` 或 `_etf_cache_file` 宿主分支改为 `backend/data`，消除「根 ./data（8/4）vs backend/data（8/7）」两分支读写错位 | 容器与宿主读到同一份 etf_list_cache.json；refresh 成功后 root+backend 两份 mtime 同步 |
| P2-I | **因子评分渲染不过滤中性兜底值**（§3.2-5） | `format_factor_summary`（portfolio_service.py:82-96）复用 `_factor_value_real`（排除 RSI/KDJ=50、ATR=0 等兜底值）：**无真实因子的标的评分段渲染为「数据不可用（K线缺失）」**，而非「RSI(14) 50.00（中性）」；与 `factor_availability.filled` 口径一致 | 10 只全兜底时报告评分段不再出现 50.00；有真实值时照常显示；单测断言「仅 50 兜底 factor_scores → factor_summary 渲染『数据不可用』」 |
| P2-J | **watchlist 添加链路卡顿 + 添加后三列空**（§5.2） | ① POST /watchlist（market.py:898）的 `get_asset_realtime` 包 `asyncio.wait_for`（A股 ≤3s、港/指 ≤8s）；**前端已传 name 时直接跳过实时验证**（R29 已允许 name 入库，验证纯属多余慢源调用）；② GET /watchlist 的 DB-only 行由前端三列显示「行情加载中」而非「—」（P1-E 扩展）；③ 添加成功后前端 fetchItems 与 POST 合并为一次往返（POST 返回后刷新单行） | 添加自选交互 ≤3s（数据源弱时不再卡 8-15s）；添加后列表在新行情到达前显示加载态而非空三列；e2e 断言 mock 慢源下 POST /watchlist ≤3s |
| P2-K | **板块热度大量 0 涨跌：值域误伤 + 匹配率低 + 延时源**（§5.1） | ① **`_sector_change_pct`（sector_fetcher.py:57-69）放宽板块阈值 ±10%→±20%**（板块指数单日涨超 ±10% 合法，CRO/CMO +10.84% 不应被剔除出回填 map）；② 结构性换主源：直接以东财 `fetch_em_sector_changes` 全量板块（行业+概念一次拉全，f3 真实涨跌）作为榜单排序（替代「财联社热度 × 东财名匹配」两段式），消除匹配残差；③ EM_PUSH_HOST push2delay 加 push2 优先 + 上一次成功数据兜底（避免晚盘 map 空 → 整页 0）；④ 前端 change_pct=0 且后端标「无数据」时显示「暂无」而非 +0.00% | 板块热度 20 条真实涨跌 ≥18/20（非交易日除外）；CRO/CMO 类 >10% 板块不再回落 0；e2e 断言慢源下不再整页 0 |
| P2-L | **添加对话框「资产类型」与市场 tab 联动（含 placeholder 示例动态化）**（§5.2，用户反馈 08/08） | ① A/HK/US 特定 tab 下：打开添加框时 `form.asset_type` **预置 = marketTab 映射**（A→'A'、HK→'HK'、US→'US'），「资产类型」下拉改为**只读标签「市场：A股/港股/美股」**（无需用户再选）；② global tab 保有下拉（跨市场需确认，或依赖搜索选中自动设）；③ `selectSuggestion` 选中后仍自动覆盖 asset_type（搜索结果比 tab 更精确，保留）；④ 移除 assetTypes 里与 tab 冲突的手选路径；⑤ **输入框 placeholder 示例随 marketTab 动态化**（WatchlistPanel.vue:29 硬编码「510050、贵州茅台」→ computed 映射：A→「510050、贵州茅台」/ HK→「00700、腾讯控股」/ US→「AAPL、Apple」/ global→「代码或名称」） | A/HK/US tab 打开添加框无手动选择步骤且 placeholder 示例对应当前市场；添加入库 asset_type 与 marketTab 恒一致（断言「A tab 添加 → asset_type='A'」）；global tab 跨市场添加正常；`<AddModal>` 在 HK/US tab 渲染时 placeholder 含对应市场示例 |
| P2-M | **港股热点板块首行名字空：f100='-' 占位未兜底**（§5.1，用户反馈 08/08） | `parse_hk_plates`（hk_hot_fetcher.py:121）行业字段兜底扩展：`ind = (r.get("f100") or "").strip()`，**再判 `ind in ("-", "--", "0", "", "None", "nan")` → 归并「其他」**（东财 f100 无分类返回 `-`）；`parse_hk_hot_stocks`（141-154 行）个股 `industry` 同理归一；可选：无行业分组从板块榜剔除或排末 | 港股热点板块榜不再出现名字为空/`-` 的首行；单测断言 `f100='-' → name='其他'`；e2e 断言港股板块榜首行 name 非空且非 `-` |
| P2-N | **港股热门个股技术分析弹窗数据空：assetType 写死 'A'**（§5.3，用户反馈 08/08） | `SectorHeatMap.vue:125` 弹窗 `asset-type="A"` 改 `:asset-type="techAssetType"`——`techModal` 增加 `assetType` 字段，`openTechnical(item)` 取 `item.market || item.asset_type || props.marketTab` 映射（HK→'HK'、US→'US'、其余→'A'）；`TechnicalAnalysisModal` 按 assetType 传 indicators/chart | 港股热门个股点技术分析弹窗 RSI/MACD/K线 全部有值（对 02800 断言 320 行 K 线 + rsi 非 Null）；A 股不受影响；主要断言语义：`assetType!=='A'` 时请求带对应 asset_type |
| P2-O | **港股 ETF 分类识别缺失：盈富基金被当普通标的**（§5.3，用户反馈 08/08） | ① `sync_instruments.py` 港股段增加**独立 ETF 采集**：`fund_hk_etf_spot_em`（akshare 港股 ETF 列表）或东财港股 ETF 段，asset_type='etf'（区分 stock）；② `get_asset_realtime` 港股分支按 symbols 前缀/instruments 匹配回填 `type`（'etf'/'stock'）；③ 前端 `UnifiedAnalysis.vue` assetType 逻辑增加「港股 ETF → asset_type='HK_etf'（或 etf）分流基金分析模板」；④ 港股 ETF 分析报告含基金专属段（规模/净值/折溢价/跟踪误差，有数据则注入） | instruments 表含 02800 盈富基金（asset_type='etf'）；`get_asset_realtime('02800','HK')` 返回 type='etf'；前端港股 ETF 分析标题显示「ETF」，报告含基金规模段（若数据可得） |
| P2-P | **组合管理页持仓行情加载态缺失**（§6） | 组合管理页持仓表格在 watchlist/calculate 慢时（3-14s，§6 实测 requestfailed）**无加载占位**——持仓行情三列在数据到达前显示空白/旧值；方案：表格行加 skeleton/「加载中」态 + 行情列空时显示「—」+ tooltip「数据加载中（数据源慢）」；与 P0-E/P1-E 的 watchlist 三列加载态统一实现 | 组合管理页慢数据时不再无提示空白；表格有明确加载态（skeleton 或「加载中」）；与自选页加载态样式一致 |
| P2-Q | **美股搜索补全慢且不全**（§5.2，用户反馈 08/08） | ① **🆕 `search_hk_us` 加 market 过滤**：market=US 查询只返回 US 段（HK/US 分开过滤后再合并，消除「搜 AAPL 返回 30 条港股 ETF」——本地实测最显性 bug）；② **US 数据覆盖**：`sync_instruments._fetch_us_list` 新浪降级从 6 页（≤120 只）扩到多页 ≥2000 只（可控分页）；`fetch_us_spot_list` 加新浪降级链（与 sync 复用同逻辑）；③ **归一化统一**：`normal_match(sym, kw)`（strip `.US/.HK` 后缀 + 忽略点号）联防 BRKB/BRK.B、AAPL.US/AAPL；name 双字段（中文/英文）匹配；④ **后端搜索缓存**：`search_hk_us` 按 keyword+market 加 60s 进程缓存；⑤ **前端**：WatchlistPanel 复用 `useMarketSearch`；⑥ enrich 8s → 3s | 美股补全冷启动 ≤1s（不再 4s/19.5s）；`marketApi.search('AAPL',{market:'US'})` **只返回 US 段且含 AAPL**（不再 HK 霸屏）≤500ms；BRK.B/BRKB、AAPL.US/AAPL 可互换搜到 |
| P2-R | **美股热点排行数据缺失：round6 F16「US 暂不支持」补全**（§5.6，用户反馈 08/08） | ① **热门个股（stock/hot tab）**：`_fetch_us_spot`（china_market.py:863-892）的 rows 补 `price/change_pct/amount/mcap` 字段（东财 `stock_us_spot_em` 全列），新增 `market_data_hub.get_stock_hot_rank(market='US')` 按**成交额降序 TOP N**（美股无涨跌停，成交额榜即"热度"），复用 6h/1h 缓存；② **板块热度（sector-heat tab）**：接入 akshare `stock_sector_spot`（美股行业板块实时，GICS 11 行业）按成交额排序；③ **hot-plates**：美股无涨停语义，美股 hot tab **复用热门个股榜**并标注「美股无涨跌停」；④ 前端 SectorHeatMap 美股 tab 三个 tab 显示真实数据 | `/market/stock-hot-rank?market=US` 返回 ≥20 条（含 AAPL/TSLA 等，有 price/change_pct/amount）；`/market/sector-heat?market=US` 返回行业板块真实涨跌；前端美股热点 tab 有数据且非「暂无」；字段校验 change_pct 在 US±50% 内 |
| P2-S | **美股/港股综合研判·宏观政策段数据支撑不足**（§4.3，用户反馈 08/08） | ① **美股专属宏观新闻源**：macro_news 不再恒空——美股报告注入美股宏观新闻（如 FRED 新闻/美联储公开声明/US 宏观日历，news_fetcher 增 `fetch_us_macro_news()`），港股同理注入港股/中国宏观；② **FRED 失败显式降级**：美债10Y/VIX/联邦基金利率拉取失败时在报告标注「海外流动性数据暂不可用」而非静默缺（llm.py:828 增 fallback 文案）；③ 中文财经资讯标题按 market 过滤（美股报告剔除纯 A 股政策标题）；④ e2e 断言美股研判报告「宏观政策分析」段含实时宏观数据（FRED 或美股宏观新闻引用），否则 WARN | 美股综合研判宏观政策段不再纯模板；报告含「美债10Y X.XX% / VIX XX / 联邦基金利率 X%」或「美股宏观：<新闻>」；FRED 失败时报告明示「海外流动性暂不可用」 |
| P2-T | **美股板块模式补全返回 A 股板块：`_search_sectors` 无 market 过滤**（§5.6，用户反馈 08/08） | `_search_sectors`（market.py:100）加 `market` 参数：US/HK 传入时返回空（美股无板块数据源）；前端美股 tab 板块模式**禁用/提示「美股暂不支持板块分析」**而非展示 A 股板块；A 股/global tab 行为不变 | `marketApi.search(kw,{market:'US',kind:'sector'})` 返回空数组（不再返回 BK 板块）；美股 tab 板块模式无 A 股板块下拉 |

### P3（测试防护补强）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P3-A | **AI 投顾内容门禁** | verify_e2e 对 llm-advice 断言输出含「上证指数/深证成指/市场状态:」至少一项真实数据关键词 | llm-advice 模板化必 FAIL |
| P3-B | **策略一致性断言** | 断言每只 factor_availability.filled 与 report_text「N/M 可用」一致；全兜底不得报「N/M 正常」 | P1-15 换形式回归必 FAIL |
| P3-C | **watchlist realtime 断言** | verify_e2e watchlist 断言 items 每项 realtime.price 非 None（缓存热时） | 列表实时空必拦 |
| P3-D | **Lighthouse 进 CI** | F18（perf≥60、CLS≤0.1）首页/行情/组合三页每次 merge 前必测 | 首页 perf 52 类回归必 FAIL |
| P3-E | **负 IC 下架门禁** | factors/active 断言无「强负 IC 活跃项」 | O6 方案落地后防再犯 |
| P3-F | **容器弱源集成测试** | mock「EM 不可达」的容器级集成（断言降级链数据完整） | P0-C/P1-G 类弱源问题在门禁可拦 |
| P3-G | **模块契约测试** | llm_advice router 与 generate_advice 的 context key 契约单测（断言 router 注入的 key ⊆ 引擎消费的 key） | 槽位错配类回归必拦 |
| P3-H | **LLM 超时分级门禁** | 单测断言 `_llm_timeout_for` 对「仅静态因子（fetch_history 全空）」返回 30s 而非 90s；provider_timeout 透传；fallback 在预算内被调用（对应 P0-F/P1-I） | LLM 90s 空耗回归必 FAIL |
| P3-I | **报告行情精度 + 新鲜度门禁** | ① 单测断言设计 `report_text`/表格中所有涨跌幅为两位小数（正则 `[+-]?\d+\.\d{2}%`）；② 断言 design `data_fetched_at` 与 daily_change_pct 数据时刻一致；③ verify_e2e 在非交易日后生成的设计断言**不再静默复用 >2 交易日的快照涨跌**（应标注 or 用最近交易日） | 报告出现「涨1.0%/1.4%」类截断或 8/4 旧涨跌冒充当日的回归必 FAIL |
| P3-J | **测试防护体系冗余治理**（§9.1 审计） | ① **合并 6 强重复组**：search 6→1、pool_manager 4→1、market_data_hub 4→1、strategy_check 11→3、news 11→3、global_indices 2→1（估约 -50% 测试代码）；② **抽共享 fixture**：conftest 增 `fake_async_session`（统一 execute/scalars/all 4 件套，替换 10+ 文件的 `_FakeSession` 手写）与 `FakeHub`；③ **清理 40 处空转断言**（纯 `status==200`/`len>0` 升级为字段级或删除）+ 删 `test_ssl_session.py`（测实现细节恒绿）、`test_remaining_fixes.py::test_p01_theme_css`（范围外前端测试）；④ **verify_e2e 去重**：search/designs/ic/factor-health/sources 三连检查收窄到单次；删与单测逐字重复的 `section_design_quality_gate`/`section_snapshot_health`；⑤ **dead fixture 处理**：R73 的 4 个 conftest fixture 迁移业务测试使用或删 `test_shared_fixtures.py` | 合并后 pytest 全量仍全绿；**`_FakeSession` 手写实现从 10+ 文件降到 ≤2**；verify_e2e 同端点检查 ≤1 次；测试文件数 226→≤170；单测全绿数与基线 pytest_full.log（当前 1112）一致 |
| P3-K | **mock 基线数字修正（857 未在仓库落地）** | 审计发现「mock 引用基线 857」**在代码/配置中无任何约束**（grep 无 "857"；当前 pytest 为 1112 passed）——修正为：以仓库内实际 `pytest_full.log` 数目为准（当前 1112），或由治理方案作者确认 857 的历史含义后正式落地为可审计的数字 | 仓库内 mock 基线数字与 pytest 实际数一致；857 基线有明确出处或移除 |

---

## 11. 终审复核清单（2026-08-08 第三轮 review 归档的低危措辞项）

以下为第三轮终审发现、**不阻塞排期**的措辞级低危项，归档待 round11 或实施时顺手处理：

1. **P1-F 引用锚点**：P1-F（AI 投顾 L1 分级偏高）引用「§5.4」，但 §5.4 为资讯页面 level 分布——两处关联（AI 投顾注入的宏观新闻 level 分布）未在正文显式交代；
2. **§4 术语「口径统一 37.8」**：全文唯一无出处术语（指 llm-report 三市场情绪分数统一为 37.8 的口径说明），实施时补注释；
3. **§4.1 用户截图指数值**：L158「上证指数 +2.51%（实为科创50）」与 §3.4 科创50 +2.56% 差 0.05%——不同时刻快照，可加注；
4. **§9.1-B「search 9+ 次」**：仅列 7 处引用点（L257/L270-283/L289-306/L888/L2131-2157/L2169/L2191），"9+"为含轮询内复调的计数，未逐点列全；
5. **§3.1「18 标的中 17 个错位」**：未指明唯一未错位标的（结合「全部来自 8/4 快照」的弱张力），实施时补一句。