# Round 4 诊断发现清单（过程记录，草稿）

> 本文档为执行过程中的临时发现记录，最终结论与修复方案见交付文档。
> 状态图例：🔴 严重 / 🟡 中 / 🟢 正常

## R4-01 🔴 策略检查「行业集中度风险」误导性输出（新发现）
- **现象**：strategy-check 234 报告风险提示「行业集中度风险：仅覆盖1个行业，最大行业占比76%」，affected_symbols 为全部 10 只场内持仓。
- **事实核对**：场内组合实际覆盖券商(512000)、半导体设备(159516)、创新药(159992/513120)、游戏(159869)、黄金(518880)、红利(510880/159545)、港股科技(513010)、宽基(159338) 等 ≥7 个行业；最大单只持仓 159338 权重 20%。
- **根因**：`backend/app/services/portfolio_service.py:926-945` `_compute_risk_warnings` 依赖 `h.get("sector") or h.get("industry")`；而 `holdings_analysis`（strategy_check_worker 产出）未注入 sector/industry 字段 → 全部归入空串行业，`unique_sectors=1`，空行业权重=总权重 76%。
- **影响**：严重误导投资者（把多行业组合误判为单行业集中）；同逻辑下 `affected_symbols` 全量误报。
- **涉及文件**：`backend/app/services/portfolio_service.py`、`backend/app/tasks/strategy_check_worker.py`（缺字段注入）。

## R4-02 🟡 设计报告「今日涨跌」列为空（—）
- **现象**：design 327 design_text 表格中「今日涨跌」列全部为 `—`。
- **历史关联**：combination-design-review.md F3.3「今日涨跌缺失 = 数据注入时机 + falsy 丢弃」修复项。
- **待核实**：是否仍为 falsy 丢弃或数据源无当日数据。

## R4-03 🟡 方案预期收益与「当前预期收益」完全一致
- **现象**：三套方案 expected_return == expected_return_current（8%/11%/16%）。
- **待核实**：市场状态是否应触发预期收益调整（budgets.py dynamic_layer_budget / 预期收益调整逻辑）。

## R4-05 🟡 API 契约：realtime/batch 逗号分隔参数只返回 1 条
- **现象**：`GET /market/realtime/batch?symbols=510300,510880,518880` 只返回 1 条（510300）；`?symbols=a&symbols=b&symbols=c` 重复参数形态返回 3 条正确。
- **根因**：HTTP 层 FastAPI list[str] Query 对逗号分隔的解析与 datahub 内部逻辑组合后只取第一条（容器内直接调用 `get_realtime_batch(["510300","510880","518880"])` 返回 3 条，说明问题在 HTTP 解析层而非数据层）。
- **影响**：前端当前未使用该端点（自选走 watchlist 单只循环、组合走内部调用），影响面有限；但契约文档若声明逗号分隔形态即为隐患。
- **验证**：`_test_batch_http.py` 4 种参数形态对比。

## R4-06 🟡 API 一致性问题：/news/stock/{symbol} 返回中文键（非前端断裂）
- **现象**：`GET /news/stock/159338` 返回 `新闻标题`/`新闻内容`/`发布时间`/`新闻来源`/`新闻链接` 中文键；而 headlines/macro/global 均用英文键 title/content/source/url。
- **根因**：`backend/app/fetchers/news_fetcher.py:389` `fetch_stock_news` 用 `ak.stock_news_em`（东方财富，中文键列），仅过 `_attach_level`（只打 level/stars/time），未做键归一化。
- **影响**：**前端当前不消费该端点**（NewsView 仅用 newsApi.headlines/newsImpact），因此无用户可见断裂；但 API 契约不统一，任何未来消费该端点的客户端都会读到 None 标题。属契约隐患。
- **涉及文件**：`backend/app/fetchers/news_fetcher.py`（缺 `_normalize` 步骤）。

## R4-07 ✅ 已确认为正常数据：韩国指数 +17.91%、日经 +4.03% 为 2026-07-31（周五）真实行情
- **现象**：indices/global 中韩国综合指数 +17.91%、日经225 +4.03%（2026-08-02 非交易时段，数据为上次收盘），涨幅显著高于美股（+0.5~1%）。
- **核实结论**：**用户确认韩国指数周五确实大涨 17.91%**，属真实行情，非数据异常（非单位/口径错误）。日经 +4.03% 同属真实行情数据，无异常证据。
- **处置**：不涉及修复；本轮不设涨幅合理性门禁（避免对真实行情误报）。

## R4-08 🟢 已修复确认（相对 round3 清单）
- 预热 2.47s（round3 N08 曾 10.6s）✅
- 策略检查报告正文非空（round3 N01 / U2）✅
- 设计报告标题不再重复（combination-design-review F1.1）✅
- 市态正确传递（range_bound → 报告「市态：震荡」）✅
- sectors/heat 契约修复（N05：dict{"items":[...]} 前端可用）✅
- 港股实时行情恢复（N03：513010/513120 有价格）✅
- 搜索自动补全正常（代码/中文/拼音）✅
- watchlist realtime 注入正常（N07 修复）✅

## R4-09 🟡 个股分析（symbol-analysis）基本面数据未注入 + asset_type 参数脆弱性
- **现象 A（前端真实路径）**：`asset_type="A"` 时 600519 报告技术面完整（RSI 66.11/KDJ/MACD/均线/30日K线全有），但明确标注「输入数据未包含 PE、PB、ROE 等财务指标」→ **fundamentals 未注入 prompt**。
- **现象 B（参数脆弱性）**：`asset_type="stock"`（非前端形态，但 API 不校验）时 `get_history` 返回 0 条（`get_history("600519","A")` 正常 240 条）→ 技术指标全空、报告诚实降级。
- **根因**：`backend/app/routers/analysis.py:676-736` symbol_analysis_stream 已采集 realtime+history+indicators 并注入 prompt（L719-721），**唯一缺失是 fundamentals**（`get_market_fundamentals` 未调用）；`get_history` 对非标准 asset_type 静默失败且无归一化。
- **影响**：个股分析缺估值维度（PE/PB 不可得），专业投资者无法判断估值水平；API 对任意 asset_type 无校验有数据缺失风险。
- **修复方向**：prompt 注入 fundamentals（缺失时明确标注数据源）+ asset_type 枚举归一化（'stock'→'A'）。

## R4-10 🟢 资讯 AI 智能分析质量良好
- llm-news-analysis 200：市场情绪指数 40/100 偏悲观、影响板块 3 类（资源能源/人工智能科技/国际贸易）、风险提示 6 条、含"新闻一致性检查"段落、与市场现状（A 股科技回落、能源价格飙升）逻辑自洽。

## R4-11 🟡 前后端弱断裂（4 处，均有防御代码不崩溃，但功能缺失）
来源：系统化契约排查（explore 子代理，对照前端消费字段与后端实际响应）。
1. **SectorHeatMap.vue:61-65 读 `item.change_pct`**：后端 `/market/sectors/heat`（market.py:502-512）item 仅 rank/name/heat_index/rank_change/is_new/plate_code，无 change_pct → 热度行涨跌幅恒不显示。
2. **AnalysisView.vue:242,336,361 读 chart 的 `d.kdj`/`d.rsi`**：后端 `compute_chart_data`（indicators.py:262-272）只出 dates/opens/highs/lows/closes/volumes/ma*/bollinger/macd，无 kdj/rsi → KDJ/RSI 子图恒不渲染。（TA 面板走 /market/indicators 不受影响）
3. **FactorICView.vue:53-54 分类过滤用 'china'/'etf'**：后端 /factors/ic 归一化为 `china_specific`/`etf_specific`（factors.py `_get_factor_category`）→ 选「A股特有/ETF」过滤恒为空。
4. **FactorModelView.vue:279 读 `item.category`**：后端 /factors/active 的 factor entry（factors.py:182-195）无该字段（分类在父级 categories[].name）→ tooltip 类别显示空。
另注：stores/market.js fetchRealtime（/market/realtime/portfolio）无前端调用者（链路假设与实现不符，非断裂）。

## R4-12 🟢 一致链路确认（无断裂）
portfolio/calculate、daily-pnl、etfs、pnl-history、import/export/drift-check、indices/global、watchlist、sectors、hot-plates、stock-hot-rank、indicators/signal、search、news/headlines、news-impact、SSE 4 端点、factors/ic+active（除 R4-11 两项）、admin/token-usage+sources/health+config、system/warmup、design-async/tasks/strategy-check/designs/timeline 全部字段兼容（含双字段 fallback）。

## R4-13 🔴 round3 N04 未完全修复：HK/US llm-report 仍混入 A 股指数
- **现象**：`POST /analysis/llm-report {"symbols":["513010"],"market":"HK"}` 报告引用「上证指数 3832.26 +0.72%、深证成指、创业板指、沪深300、科创50」；`market="US"` 同样混入 A 股指数。
- **根因**：`backend/app/routers/analysis.py:158-241` llm_report 中 `market_data` 已按 `market_ctx`（major_symbols/index_symbols）过滤（L198-209，N04 修复点），但 **`indices`（L187 `get_indices()` 全量）与 `commodities` 未按市场过滤**，直接传入 `generate_market_report` → LLM 引用 A 股指数。
- **影响**：专业投资者对 HK/US 研判会读到 A 股数据，投资判断被污染。属数据准确性（round3 分类中 N04 声称已修，实际只修了一半）。

## R4-14 🟡 U11 未修复：核心层跨方案重叠仍 >1
- **现象**：design 327 三方案核心层重叠：防御∩平衡={563020,510300}、防御∩进攻={563080,510300}、**平衡∩进攻={159915,588000,510300}（3 只）**；三方案共有 {510300}。
- **round2-unfixed U11 验收**：核心层跨方案重叠 ≤1 → FAIL。
- **影响**：三套方案差异度不足（进攻/平衡同质化高），方案选择意义被稀释。

## R4-15 🔴 combination-design-review 验收未达标（2 项 FAIL）
- **验收2「核心层出现中证A500（560600 或 159338）与沪深300」**：三方案核心层均无 560600/159338（防御核心 510300/563020/510050/563080；平衡 510300/588000/159915/510500/563020；进攻 510300/588000/563080/562000/159915）→ **FAIL**（只有沪深300，A500 仍缺失）。
- **验收4「卫星层无宽基（A100/中证500/沪深300）」**：防御卫星含 562000 A100ETF、平衡卫星含 562000 A100ETF → **FAIL**（A100 宽基仍混入卫星层）。
- 验收1（核心 4-5 只、权重 ≥5%）、验收3（中证500 家族 ≤1）→ PASS。
- **影响**：combination-design-review 的 P1/P2 修复方案未完全落地（A500 未入核心池、A100 未从卫星排除）。

## R4-16 🟡 U5 部分改善：组合计算仍 5.1s
- **现象**：`POST /portfolio/calculate` 5.1s（历史 8.2s，round2-unfixed U5 目标 <3s）→ 改善未达标。
- 场内/场外各 5.1s，瓶颈疑在行情拉取（预热同源：get_portfolio_realtime 1.48s 同步等待）。
- daily-pnl 0.0s ✅。

## R4-17 🟢 docs 修复确认（N01/N02/N03/N05/N06/N07/N08/N09/Z06/Z15 部分）
- N01 策略检查报告空 → 修复 ✅（report_text 完整）
- N02 涨跌幅×100 → 修复 ✅（portfolio realtime 28 项 |chg|≤50）
- N03 港股熔断 → 修复 ✅（513010/513120 有价格）
- N05 sectors/heat 断裂 → 修复 ✅
- N06 IC 全 0 → 修复 ✅（19 非零）
- N07 自选 realtime null → 修复 ✅
- N08 预热 10.6s → 修复 ✅（2.47s）
- N09 拼音搜索无数据 → 修复 ✅（huangjin 10 条）
- Z06 IC 后台累积 → 修复 ✅（factor_ic_records 21913 条、后台 saved 19 records）
- Z15 HK realtime 覆盖 → 部分 ✅（港股三大指数 available=True；verify_e2e 有 section_hk 检查）

## R4-18 🔴 verify_e2e.py 自身 bug：print_summary UnboundLocalError 必崩
- **现象**：`python scripts/verify_e2e.py --module zscore` 全部检查 PASS 后，`print_summary()` 报 `UnboundLocalError: cannot access local variable 'FAIL'`（verify_e2e.py:1610）。
- **根因**：`print_summary` 函数体 L1620 有 `FAIL += 1`（S3 skip 阈值逻辑）→ Python 将 `FAIL` 视为函数局部变量；L1610 `total = PASS + FAIL` 读取时未赋值 → UnboundLocalError。`check()` 里的 `global` 声明不影响 `print_summary`。
- **影响**：**任何模式运行 verify_e2e 都必然崩溃**（全 PASS 也崩）→ 门禁永远 exit 1（异常），且总结行（"X/Y 通过"）永远不打印。**门禁实际已失效**——CI/人工执行无法获得通过信号，崩溃被当作"失败"掩盖了真实状态。这是测试防护体系失效的最直接证据（步骤 14 核心输入）。
- **修复方向**：`print_summary` 内加 `global PASS, FAIL, SKIP` 或不用 `FAIL += 1`（改用局部变量累计）。

## 备注
- 场内持仓 10 只：159338 20% / 518880 13% / 510880 8% / 512000 8% / 159545 5% / 159992 5% / 159869 5% / 513120 5% / 159516 4% / 513010 3%（合计 76%，其余为现金）
- 场外 10 只为对应联接基金（tracked_index 映射）

## R4-19 🔴 前端首页 Lighthouse：Performance 57-59 低于门禁 60、CLS 0.41 严重超标
- **数据**（lighthouse 13.4.1 + headless-shell，生产 nginx :80，2 次采样）：
  - /（首页=Dashboard.vue）: **P57-59**、CLS **0.41**、LCP 3.4s、FCP 2.0s、TBT 430ms、SI 4.6s、主线程 2.3s、unused JS 85KB
  - /dashboard: P99、CLS 0.001、LCP 2.0s
  - /market-analysis: P97、CLS 0.001
- **判断**：round3 N10「dashboard CLS 0.538」在 /dashboard 路由已修复（CLS 0.001），但**首页 / 路由仍 P<60 + CLS 0.41 稳定复现**——首页与 /dashboard 同组件（router 均指向 Dashboard.vue），差异疑来自首页首屏并行 API 数据到达时序 + WS 消息插入导致的布局偏移（骨架屏占位 vs 数据填充）。
- **影响**：LHCI 门禁 categories:performance minScore 0.6（error）与 cumulative-layout-shift max 0.1（error）在首页必 FAIL。

## R4-20 🟡 后端全链路性能采样（2 次取均值）
- 健康（<0.3s）：health 0.02 / warmup 0.01 / indices 0.00 / realtime 510300 0.05 / search 0.07 / history 0.06 / indicators 0.06 / signal 0.07 / sectors/heat 0.01 / hot-plates 0.01 / news 0.01 / factors 0.02 / sources 0.00 / etfs 0.02 / strategy-checks 0.03
- 偏慢：watchlist 首次 2.27s（缓存后 0.01s，单只循环 get_asset_realtime × N）、tasks 0.63s 稳定（列表 JSON 解析）、designs 0.64s（大 JSON）、stock-hot-rank 0.25s、token-usage 0.24s、portfolio/calculate 5.1s（R4-16）
- 预热 2.47s（R4-08）✅

## R4-21 🔴 场外累计盈亏口径错误（-21.44% 失真，用户报障核实）
- **现象**：Dashboard 场外累计盈亏显示 -21.44%（total_capital=500000 时，pnl-history 端点复现一致）。
- **根因**：`calculate_cumulative_pnl` R64 估算分支（有 avg_cost 无 shares_held）对场外联接基金混用两个单位不匹配的数——`est_shares = 目标金额 / 场内ETF实时价`，`cost_basis = est_shares × avg_cost(联接基金单位净值)`。场内 ETF 做过份额拆分/折算，与联接基金净值数值差 2~5 倍，导致成本被错误放大/缩小。
- **失真明细**（单只盈亏率 = 场内价/联接净值 - 1，与权重无关）：半导体联接C **-81%**（0.67 vs 3.534）、券商联接C **-66%**（0.529 vs 1.553）、恒生科技联接C -43%（0.628 vs 1.109）、黄金联接C **+179%**（8.433 vs 3.023）、红利联接C **+218%**（3.304 vs 1.041）；仅净值≈场内价的品种（A500 -3.6%/创新药 +19.9%/游戏 -6.1%）相对真实。
- **补充**：019633 半导体联接C avg_cost=3.534 本身疑似录入异常（同类联接净值 1 元档），需用户核对。
- **修复方向**：off_exchange 估算改用「目标金额/avg_cost 折算份额 → 成本=本金」，市值按跟踪 ETF 涨跌幅或联接净值估；或接入天天基金等联接基金净值源。勿套用场内价公式。

## R4-22 🟢 策略检查操作建议丰富化（已实施）
- **需求**：策略检查操作建议过简（一句话 reason），用户要求提高参考价值。
- **实施**：`_rule_based_suggestion` reason 升级为三段式（触发依据；操作节奏；风险纪律，如「分2次加仓/单次≤20%」「跌破MA20暂停」）；report_text 操作建议分标的分段；LLM prompt（strategy_check.md + llm.py）新增 reason 丰富化硬约束；契约 strategy-check-v2.md 补充 reason 说明；新增单测 test_reason_richness_three_parts。
- **验证**：全量 pytest 1214 passed；真实链路 reason 三段式输出。
- **注意**：验证期间发现宿主机 8000 端口被旧 uvicorn 进程（PID 24728）占用导致误验旧代码，已清理；真实链路 LLM 仍 60s 超时（85% 概率），丰富化主要惠及规则引擎兜底路径。

## R4-23 🟡 海外流动性数据管道：FRED fetcher 已就绪但未接线（用户反馈核实）
- **现象**：市场综合研判报告提示「暂未提供美债、美元、油价等全球定价因子数据，此为当前观察体系的重要盲区」。
- **核实**（代码 + 实测）：
  - `global_markets_fetcher.py` **已有 5 个 FRED fetcher**（fetch_us_10y / fetch_vix / fetch_fed_rate / fetch_cpi / fetch_nfp），`FRED_API_KEY` 已配置于 .env——但 **grep 确认全 backend 无任何调用点**，从未接入数据管道/研判 prompt。
  - 实测 FRED 全部可用：美债 10Y=4.68%、VIX=17.09、联邦基金利率=3.63%、CPI=332.57、非农=158984。
  - 美元指数：无 fetcher（需新增，akshare fx_pair_quote / macro_fx_sentiment 可提供）。
  - 油价：`get_commodities()`（ak.futures_foreign_commodity_realtime）实测返回 **0 项**（非交易时段拿不到）——LLM 说「暂未提供油价」是如实报告。
  - 地缘：无结构化源，依赖现有国际新闻（news_fetcher 已覆盖）。
- **根因**：研判 prompt（llm.py:1092）要求分析「美债、美元、油价、地缘冲突传导」，但注入数据仅 indices/commodities/news，美债/VIX/利率 fetcher 存在却未接线。
- **方案分级**（详见 round4-diagnosis-and-optimization-plan.md P1-5）：P0 接线 5 个 FRED fetcher + prompt 注入「海外流动性」段（零新依赖）；P1 新增美元指数 fetcher + 油价降级保护；P2 地缘类国际新闻注入。

## R4-24 🟢 新闻 AI 影响范围结构化（方向+板块+概念，已实施）
- **需求**：新闻 AI 智能分析的「影响范围」未明确利好/利空方向与板块/概念（用户示例：电影票房新闻只输出「A股文化传媒板块」）。
- **实施**：`news_impact.md` system prompt 与 `llm.py analyze_news_impact` 动态 prompt（有持仓/无持仓两分支）均要求 impact_scope 按「方向：利好|利空|中性；板块：xxx；概念：xxx」结构化输出；summary 亦须含方向判断。前端 `NewsView.vue` 渲染自由文本，零改动。
- **验证**：实测电影票房新闻 →「方向：利好；板块：A股文化传媒（影视院线、内容制作、发行放映）；概念：影视、票房、暑期档」；news_impact 相关 18 个单测全过。

## R4-25 🔴 技术分析弹窗「综合信号」恒为空（前端 bug）+ 信息决策性不足（已实施）
- **现象**：热门个股 → 技术分析，综合信号显示「—」但得分正常（如 002131 得分 1.5 应为买入）；仅有原始指标数值（RSI/MACD/KDJ/MA），无方向解读，难以用于决策。
- **根因**（实测后端正常：signal/indicators 返回完整 `signal=buy, score=1.5, reasons=['MACD偏多','MA5>MA20 多头排列']`）：`TechnicalAnalysisModal.vue` 的 `signalText` 是**模块级静态 const**（setup 时求值一次，signalData 尚为 null → 恒「—」），且 `reasons` 数组未渲染（模板只认单个 `reason` 字段）。
- **实施**：signalText 改 computed；渲染 `reasons` 列表；指标区补 MA5/MA10/BOLL；每个指标附方向解读（RSI 超买卖区、MACD 金叉/死叉、KDJ 金叉/死叉+J 超买卖、MA 多空排列带偏离%、BOLL 支撑/压力位）。
- **验证**：前端 309 测试全过（新增 SectorHeatMap R4-25 防回归断言）+ build 成功；后端 002131 实测 buy/1.5/reasons 完整。

## R4-26 🟢 自动补全提速：HK/US spot 失败缓存 1h + 拉取超时 4s（已实施）
- **需求**：添加自选/标的分析自动补全慢（用户询问内存/Redis/前端缓存方案）。
- **核实**：A 股 ETF/个股搜索已走本地 instruments 表（稳态 16ms）；HK/US spot 已有内存缓存（成功 6h TTL + single-flight），但**失败只缓存 60s**——akshare spot 数据源当前不可用（实测 HK/US 均返回空、各 5-6s），用户每次搜索间隔 >60s 就反复触发拉取超时 → 6-8s。
- **实施**：`china_market.py` spot 失败/空缓存 60s → **1h**（4 处）；`market_service.py search_hk_us` spot 拉取超时 15s → **4s**（快速失败降级静态基座）。
- **验证**（127.0.0.1 直连）：首次搜索 7.6s（spot 缓存 miss）→ 之后**全部 0-16ms**（失败缓存命中）；20 个搜索相关单测全过。
- **附带发现**：`localhost` 在 Windows 解析到 ::1 (IPv6)，uvicorn 仅监听 IPv4 → 每次连接先等 2s IPv6 超时（我的测量假象；vite 代理已用 127.0.0.1 不受影响）。
- **可选后续**：首次搜索仍 ~8s（1h 仅一次）——前端两段式（静态基座先行 + spot 异步补）可进一步消除。

## R4-27 🟢 综合研判报告泄露内部指数代码（已实施）
- **现象**：港股综合研判出现「恒生科技（代码 ^HSTECH，报 4829.22）…」——内部指数代码（^HSTECH 为 yahoo 风格标识）被 LLM 复述进面向用户的正文。
- **根因**：`llm.py _format_indices` 与 `_build_market_overview` 的指数行把 `(symbol)` 拼进 prompt，LLM 原样带出。
- **附注**：「中信证券明确建议增配创新药、非银金融」有新闻依据（headlines：「中信证券：调整基本结束 8月修复可期 建议增配能化、有色、非银和创新药」），非幻觉；但 LLM 之前仅部分转述（漏能化/有色），本次生成已完整转述。
- **实施**：上述格式化函数指数行去掉内部 symbol（保留名称+点位+涨跌幅）；个股行情代码保留（600519 等公开代码对用户有意义）。
- **验证**：HK 报告不再含 ^HSTECH/内部代码；13 个 prompt/报告格式相关测试全过。

## R4-28 🟢 市场综合研判切换 tab 后仍停留旧市场报告（已实施）
- **现象**：切市场 tab 后，市场综合研判仍显示上一个市场（如港股）的报告，与当前 tab 不符。
- **根因**：`MarketReport.vue` 的 `report` 只在点击「生成」时更新，marketTab 变化无 watch → 旧报告残留。
- **实施**：watch(marketTab) → `stopStream()` 取消进行中旧流 + 清空 report/error + 自动为当前市场重新生成；序号守卫（genSeq）确保快速切换时旧流 token/状态不覆盖新市场；按钮文案带市场名（生成A股研判/港股/美股）。
- **验证**：前端 311 测试全过（MarketReport 新增 2 个 R4-28 用例：切换清空+自动生成、序号守卫丢旧流）+ build 成功。
- **R4-27b 修订**：用户澄清在意的不是代码本身而是 `^` 符号观感（yahoo 风格前缀）→ 改为**保留代码、仅去掉 `^` 前缀**（^HSTECH → HSTECH；格式「恒生科技指数(HSTECH): 4829.22, 涨跌幅0.53%」）。实测 HK 报告无 `^`；prompt 格式测试 7 passed。
