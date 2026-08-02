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

## R4-07 🟡 全球指数涨幅异常（日经 +4.03%、韩国 +17.91%）
- **现象**：indices/global 中日经225 +4.03%、韩国综合指数 +17.91%（2026-08-02 非交易时段，数据为上次收盘）；涨幅显著高于其他市场（美股 +0.5~1%）。
- **待核实**：是否为数据源返回真实异常行情，还是字段单位/口径错误（如把累计涨幅当单日）。对照美股/A股涨幅水平，17.91% 单日涨幅在成熟市场极罕见，疑似口径问题。

## R4-08 🟢 已修复确认（相对 round3 清单）
- 预热 2.47s（round3 N08 曾 10.6s）✅
- 策略检查报告正文非空（round3 N01 / U2）✅
- 设计报告标题不再重复（combination-design-review F1.1）✅
- 市态正确传递（range_bound → 报告「市态：震荡」）✅
- sectors/heat 契约修复（N05：dict{"items":[...]} 前端可用）✅
- 港股实时行情恢复（N03：513010/513120 有价格）✅
- 搜索自动补全正常（代码/中文/拼音）✅
- watchlist realtime 注入正常（N07 修复）✅

## R4-09 🟡 个股分析（symbol-analysis）数据注入缺失
- **现象**：`symbol-analysis/stream` 对 600519（贵州茅台）产出报告明确声明「技术指标（空）、历史K线（无）、基本面数据缺失」——虽然诚实降级，但**关键数据管道未注入**。
- **对照**：同一组合的 510300 ETF 分析有基本面概览；`/indicators/600519`、`/history/600519`、`/fundamentals/600519` 端点单独可用。
- **影响**：个股类 AI 分析报告因缺数据而无法给出估值/趋势/信号判断，质量打折（LLM 本身表现良好，问题在编排器数据采集）。
- **待定位**：`backend/app/routers/analysis.py` symbol_analysis_stream 的上下文采集逻辑（只采集了 realtime+news，未采集 indicators/history/fundamentals）。

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
