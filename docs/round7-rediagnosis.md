# Round7 复诊与性能诊断报告（Rediagnosis）

> 状态：**诊断完成，未开始实施**（本轮仅诊断 + 方案设计，待 review 至实施标准后另行实施）
> 范围：在 Docker 全新构建的 HEAD `0c78db8` 栈上，逐项重新执行 round6 的 15 步诊断，并与 round6 文档 (`docs/round6-diagnosis-and-optimization-plan.md`) 对照。
> 环境：docker compose（prod 态）+ `docker-compose.diag.yml` 临时 override（仅加 `PROFILE_WARMUP=1`），Chrome 150 headless Lighthouse 13.4.1。
> 日期：2026-08-04。

---

## 0. 执行摘要

本轮在**全新容器环境**（无旧缓存、无 `~/.mootdx/config.json` 的 BESTIP）上重建并启动前后端，逐项执行 15 步诊断。核心结论：

- **核心 API 契约健康**：`backend/scripts/verify_e2e.py` 274/286 通过（容器环境；2026-08-04 本地复测 271/283，12 FAIL 全为数据源/LLM 环境类）；本轮实测设计、策略检查、A/港/美多市场研判、个股/板块/概念/指数分析、自选、热点、持仓信号、因子模型均可用且质量大多为专业级。
- **但 3 个 round6 已记录的问题在本环境正式复现/劣化**：预热 128s（R6-02/08 复现）、shared_executor 线程池 100% 饱和（R6-11 复现）、搜索**个股名称维度**空（US/HK instruments 表空；R6-10 复现扩展——A 股中文名尽力复测已可命中，缺口集中在 US/HK）。
- **1 个 round6 声称已修复但本环境输出未对齐**：R6-05 RSI 失真——`factor_definitions.yaml` 已声明 `standardization: raw`，但 design 方案的 `factor_breakdown.rsi_14` 实测为 z-score 值域（-0.26），rationale 仍以 z-score 值判超卖失真。
- **前端性能短板**：Lighthouse performance=0.55（LCP 3.2s、CLS 0.393、TBT 580ms、未用 JS 85KiB、echarts/axios vendor 各 >1s 主线程）。
- **数据源冷却窗口**是部分 verify_e2e 失败的主因之一（akshare/dongfang 冷却、mootdx 冷启动、LLM 30s 超时并列，三者共覆盖 12 项失败中的大多数；实测无单源崩溃）。

总体判断：**方案与报告逻辑质量可被专业投资者接受；性能（预热/线程池/前端首屏）与个股搜索/因子数据路径是最需优先治理的硬伤。**

---

## 1. 十五步结论对照表

| # | 步骤 | round6 已记录 | 本轮实测（全新容器） | 结论 |
|---|------|-------------|--------------------|------|
| 1 | 后端预热性能诊断 | warmup 6.9s | **128.4s**（market_cache 64s + etf_cache 64s） | 🔴 复现且劣化 |
| 2 | 组合设计 + on_exchange 策略检查 | 质量达标/LLM 超时 | 设计 3 方案可读预算合理；策略检查 LLM 30s 超时走规则兜底 | 🟡 LLM 兜底为主 |
| 3 | A/港/美行情分析 | 综合研判优 | 3 研判 + 个股/板块/概念/指数优；AI 投顾空模板；US/HK 个股名称搜索空（A 股已命中） | 🟡 搜索/US-HK/投顾缺陷 |
| 4 | 热点板块/热股加载 | 加载成功 | 热点板块 15 条、热股 A 股 50 条加载正常；**热股外盘 HK/US=0（与 US/HK instruments 空同源缺陷，见 P15/P3）** | 🟡 外盘热股缺失 |
| 5 | 自选功能 | 正常 | 添加/获取/删除全通；新建条目不回 realtime（P12） | 🟢 正常（小缺口） |
| 6 | 持仓技术分析/信号 | 信号合理 | 10 ETF 信号准确（MACD/MA/RSI 依据充分） | 🟢 正常 |
| 7 | 资讯分级与智能分析 | 分级不合理 | 宏观混入无关、国际全 1 级 1 星（分级不合理） | 🔴 复现 |
| 8 | 因子模型状态 | no_data=10 | total33=valid25/no_data5/static3，avg_ic0.0718（较 round6 改善） | 🟡 改善 |
| 9 | 前后端数据断裂排查 | 弱断裂修复 | 搜索契约一致（keyword）；断裂集中在个股名称维度 | 🟡 聚焦个股 |
| 10 | round6 问题清单核对 | — | 6 项修复 / 4 项复现（见 §5） | ⚠️ 见清单 |
| 11 | 前端 Lighthouse | 前端 vendor 大 | performance 0.55，LCP3.2s/CLS0.393/未用JS 85KiB | 🔴 performance 短 |
| 12 | 后端全链路性能 | 线程池饱和 | shared_executor 64/64、预热128s、历史K线>120s、llm-report>30s | 🔴 复现 |
| 13 | 测试防护盲区 | — | 契约+mock 缺数据源降级/并发/预热高峰/前端渲染等 14 类场景 | ⚠️ 见 §6 |
| 14 | 结论+方案文档 | — | 本文档（多轮 review） | — |
| 15 | 回收容器/配置 | — | 见 §8 | — |

---

## 2. 问题清单（按影响分级）

### 🔴 高优（性能 / 数据完整性硬伤）

- **P1 预热 128.4s**：`warmup_market_cache`（64139ms）+ `warmup_etf_cache`（64137ms）均 ~64s。
  - 根因：ⅰ) 容器内 `~/.mootdx/config.json` 无 BESTIP（本轮 removed / 全新），mootdx `Quotes.factory()` 空转；ⅱ) `etf_list_cache.json` 快照时间戳（镜像层 vs 挂载卷）跨 4h 阈值（`etf_scanner.py:353`，`CACHE_TTL=14400`）→ 触发全量 1618 只扫描。
  - 影响：服务启动到可提供设计/策略检查长达 2 分钟+；`verify_e2e` 预热 gate FAIL。
- **P2 shared_executor 线程池 100% 饱和**：`active=64/64`。批量历史 K 线请求（因子/技术指标逐标地）塞满默认 64 线程池，阻塞预热与其他端点。
- **P3 个股名称搜索空**：`keyword=茅台` → 0；US/HK instruments 表 `US=0, HK=0`。已拆分根因：
  - **US=0 是代码缺失**：`scripts/sync_instruments.py` 的 `collect_all()` 只打包 A-stock/A-etf/HK-stock 三段，**US 段未实现**（确定性代码缺失）。
  - **HK=0 是数据源问题**：代码有 HK 同步，但 akshare HK 源失败/未同步成功。
  - **A 股"茅台"尽力复测已可命中**：`search?keyword=茅台` → `sh600519/贵州茅台`（hits=1），`恒生/半导` 同样命中。**早期快照"茅台=0"是数据窗口/未同步所致，非 `like` 结构缺陷**；`routers/market.py:257` 的 `Instrument.name.ilike("%茅台%")` 逻辑工作正常（256 行为 symbol 匹配；以此为据，勿再改 A 股搜索结构）。
- **P4 前端 performance 0.55**：LCP 3.2s / SpeedIndex 5.0s / TBT 580ms / **CLS 0.393** / 未用 JS 85KiB；`vendor-echarts` + `vendor-axios` 各 >1s 主线程。
  - ⚠️ CLS 口径注：round6 记录首页 CLS 曾在 R5-0-3 降至 0.189，本复测 0.393 为不同首屏/并发口径下的值，可能与 round6 修复未落到本轮首屏或测试页面差异有关——按**回归视角审慎解读**，不作为纯劣化断言；仍需 O10 治理。

### 🟡 中优（质量 / 逻辑）

- **P5 策略检查 LLM 恒 30s 超时** → 规则兜底成为常态；`portfolio_service` 数据采集自身也 `timed out after 30s, using partial results`。
- **P6 R6-05 RSI 失真未对齐（本轮实测复现，根因已定位）**：
  - 实测：design 390 的 `strategies[].etfs[].factor_breakdown["technical.rsi.rsi_14"] = -0.26`（z-score 值域），rationale 显示"RSI -0.26 超卖"等失真值。
  - **根因**：`market_data_hub.get_factor_matrix()`（市场数据管线）对所有 `factor_scores` 调 `_normalize_matrix()`（`(v-mean)/std`）做**截面 z-score 归一化，不区分 YAML 的 `standardization`**——即使 `factor_definitions.yaml` 声明 `rsi_14: raw`、`rationale.py` 也预留 `rsi_14_raw` 读取，但 `factor_registry._RAW_KEEP` 只保留 `technical.macd.macd` 的 raw，**没有 rsi_14**。故本应读 `rsi_14_raw`（不存在）→ 回退到被 z-score 化的 `rsi_14`。
  - 说明：这不是 `factor_registry._standardize` 的问题（它有 raw 分支未变换），而是 **factor_breakdown 消费的是 `get_factor_matrix` 强制 z-score 后的矩阵**这条独立路径。round6 声称 R6-05 已修仅覆盖 `factor_registry.factor_scores`，未覆盖此消费路径。
- **P7 AI 投顾返回"全数据缺失"降版模板**（指数/板块/新闻注入空），与同一时刻 A 股研判 index_realtime 完整相矛盾；与 `news-impact` 的"内容为空"同源（注入断裂，见 P16）。
- **P8 因子模型状态与数据缺失**：`/factors/active` total=33，`valid=25, no_data=5, static=3, avg_ic=0.0718`（较 round6 的 no_data=10/avg_ic 0.0246 已改善）；`etf_specific` 三因子（premium_discount/tracking_error/shares_change）仍无数据；且 `/factors/model` 端点**未输出 `valid/no_data/warn` 聚合汇总字段（实测为 null）**，前端无法直接读取模型健康度。
- **P9 资讯分级不合理**：宏观 tab 混入个股/营销；国际重磅新闻全 `level=1, stars=1`。
- **P10 指数/ETF 分析缺估值与 K 线**：指数分析开头"技术指标（空）/历史K线（无）/PE/PB 不可用"。（**顺延：暂未排 O 项**，与 P8 因子估值数据源同源，待 O20 数据语义落地后复评）

### 🟢 低优 / 补充

- **P11 持仓 `/portfolio/etfs` 的 `price` 字段为 null**（realtime 端点有价）。
- **P12 自选新建条目 realtime 为 null**（列表批量 realtime 正常）。
- **P13 港股 ETF 搜索返回 A 股同名 ETF 兜底**（恒生科技返回 A 股 ETF 而非港股 03066）。（**顺延：暂未排 O 项**，与 P3 US/HK instruments 同步缺口同源，待 instruments 同步修复后复评）
- **P14 成交额>10 的 ETF 仅 1 只**、自选候选 0（数据源冷却窗口所致，非代码缺陷）。
- **P15 热股外盘空缺**：`/market/stock-hot-rank?market=HK/US` 均返回 0 条（A 股 50 条正常）——与 US/HK instruments 空同源；热点板块 15 条 / 热股 A 股 50 条加载正常（步骤 4）。
- **P16 news-impact 智能分析空洞**：传入 4 条真实头条（沙特阿美/BP/美联储/司尔特）仍返回 `summary="新闻内容为空"` 的空洞结论——LLM 收到空正文，`news` 未真正送入分析。与 P7（llm-advice 全缺失模板）同属上下文注入断裂；专业投资者会认定资讯智能分析**不可用**。
- **P17 AI 工具默认不落工具列表（状态残留，UX）**：进入「AI工具」tab 后默认停在上次离开时的界面（通常为「任务列表」历史方案），且列表顶部是近期无新记录时的**旧方案**。根因三层：
  1. **AppTabs 面板常驻**（`src/components/ui/AppTabs.vue:71` 用 `:hidden="modelValue !== tab.value"`，等价 v-show）——`DashboardAiTools` 组件实例跨 tab 切换**从不销毁**，内部 `activeCoreFeature`/`designStep`/`designTab`/`expandedPlan` 及 `DesignHistory.statusFilter` 全部残留；
  2. **无「重新进入」复位机制**——hidden 面板不触发生命周期钩子，`DashboardAiTools` 不感知父级 tab 变化，`activeCoreFeature` 停留在上次值（如 `'history'`）；
  3. **`onMounted` 持久化恢复放大问题**（`DashboardAiTools.vue:186-206`）——`taskStore.getDesignState()` 会恢复上次已完成的设计结果/loading 态，跨刷新也「默认」跳旧状态。
  - 用户预期：进入 AI 工具应默认展示**工具列表**（智能设计 / 策略检查 / 任务列表三入口），历史方案需显式点开。
- **P18 核心层大盘宽基重叠（A500/A50/A100 同现）**：平衡方案核心层实测（design 398，2026-08-04 08:51，F4/F6 修复**前**数据，但当前代码仍存在此盲区）：
  `沪深300(510300,5.1%) + 中证A500(560600,5.1%) + 中证A50(563080,11.7%) + A100(562000,11.6%) + 创业板(159915,11.6%)`——**4 个宽基中 3 个是大盘/超大盘**（沪深300/A500/A50/A100 相关性 ~0.95+），核心层 52% 权重押注同一「大盘 beta」，分散失效、单只权重摊薄。
  - 根因：`MANDATORY_CODES` 强制注入沪深300+A500 双锚后，核心层仍可自由选入 A50/A100/上证50 等大盘宽基——现有约束只覆盖：M3 家族归一化（同指数风格切片）、B3 segment 去重（A50/A100/A500 分属不同 segment）、P1-1 验收3（仅「中证500家族 ≤1」）、F6 成长宽基权重（仅科创50/创业板类，不含 A50/A100/上证50）。**无「大盘宽基族」数量互斥**。
- **P19 卫星层科创标的数量集中（权重配额不防数量）**：所有方案卫星层均出现多个科创系标的（design 398：balanced 8 只卫星中 **4 只科创**——科创创新药/科创新能源/科创AI/科创芯片设计，权重合计 14.6% < 卫星预算 50% 配额 15% → 权重裁剪放行；aggressive 2/5、defensive 2/4）。
  - 根因：F0-5 科技 trim（`allocation_engine.py:377-440`）只约束**科创权重合计 ≤ budget×40%/50%**，不约束**标的数量**；B3 segment 去重按「概念」分组（创新药/新能源/AI/芯片设计分属不同 segment），拦不住同属科创风格的多个标的——卫星层失去主题分散作用，科创系同向波动集中暴露。
- **P20 因子模型 5 个 etf_specific 因子 no_data（根因三分）**：`/factors/active` 实测 no_data=5（`etf.premium_discount`/`etf.tracking_error`/`etf.shares_change`/`etf.industry_diversification`/`etf.institutional_holdings_change`），另 `sentiment` 3 个（`panic_greed_diff`/`stock_divergence`/`news_direction`，F19 已落地、akshare 冷却时 no_data）。
  - **共同机制**：底层数据字段全缺 → 因子截面输出常量 0.0 → 标准化阶段 `std_v < 1e-10` 跳过（`factor_registry.py:1219`）→ IC 因零方差无法计算 → `ic_val=None` → no_data。
  - **① 数据管道可用性（初判代码缺口——复核修正为环境失败）**：`etf.premium_discount` 依赖 `nav`——**代码已有三级 nav 源**：`factor_registry.py:916-1020` 批量 IOPV（Sina `hq.sinajs.cn` http + QQ `qt.gtimg.cn` 双源降级）+ `factor_registry.py:1021-1034` `_missing_nav` 补拉 `market_data_hub.get_fund_nav`（TTJ 日净值，24h 缓存，`market_data_hub.py:1867`）——**no_data 的直接根因是用户环境三级源全失败**（Sina/QQ 均为 http 明文接口，数据源冷却/网络禁用时全挂；TTJ 日净值 24h 缓存未命中时同样失败）。O18 方向修正为「先诊断现有源失败原因 → 再补 https 东财源」，而非「从零新建」（初版文档误判"全库无 IOPV fetcher"，系检索转义失败所致——已复核代码确认管线存在）。
  - **② 链路已接但指数映射不全（代码缺口）**：`etf.tracking_error` 依赖 `benchmark_close`，但 `_WIDE_BASIS_INDEX_CODES`（`market_data_hub.py:1189`）只映射 6 只老宽基（510300/510500/510050/588000/159915/510880）——**A50(563080)/A100(562000)/A500(560600) 等新宽基无指数映射 → benchmark_close 注入不到**。
  - **③ 链路已接但数据源空/冷却 + reason 误报（数据+语义缺口）**：`etf.shares_change`/`etf.institutional_holdings_change` 依赖 akshare `fetch_etf_shares_outstanding`（F19 R71 已防失败缓存，冷却时仍 no_data）；`etf.industry_diversification` 的 concepts fallback（`_compute_industry_diversification` → 1/n）**上游 concepts 为空**（`_build_symbol_extra` 注入 `entry.get("concepts", [])` 但 ETF 候选无概念标签）→ 恒 0.0 常量；且该因子**不在 `ET_SPECIFIC_GAP_CODES`**（`factor_registry.py:588`）→ reason 误报「IC 未累积（样本 <3）」而非「数据源未接入」。
- **P21 IC 数值无含义解释（UX）**：`FactorModelView.vue`（因子模型页）与 `FactorICView.vue`（因子 IC 监控页）均只显示 `ic_value` 数值与 `✅有效/⚠️低于阈值` 状态（`FactorModelView.vue:136-140`），**无 IC 定义/正负含义/阈值分档说明**——用户看到 0.07/-0.04 无法判断含义；`avgAbsIC` 也无解读。已有 `AppTooltip` 组件与 `tooltip-rich` 模式（静态因子说明 `FactorModelView.vue:55`）可复用。
- **P22 设计方案「今日涨跌」数据源不可用（fallback 死代码 + 无快照兜底）**：实测 design 398 **全部标的 `daily_change_pct`/`price` 均为 None**（前端显示「数据源不可用」）。根因三层：
  1. 候选池 `get_by_code().change_pct` 缺失（数据源冷却时 pool_entry 为兜底条目，无实时涨跌）；
  2. **fallback 死代码**（`strategy_design.py:259-267`）：`fm = factor_matrix.get(code, {})` 后查 `fm.get("change_pct")`——但 factor_matrix 的键是 **`etf.change_pct`**（键名不匹配），且该值是 **z-score 归一化值**（398 实测 -0.33~1.35，非真实涨跌幅）→ fallback **恒失败**；
  3. 无第三级兜底——`etf_list_cache.json` 快照含真实 `change_pct`（如 560950=1.358），K 线 close 序列也可算（`_compute_change_pct` 已有现成逻辑），均未接入。
- **P23 入选理由行业标签与实际标的不符（562950 消费电子 → 「食品饮料方向」）**：用户截图防御型方案中 **562950 消费电子ETF易方达** 的 rationale 显示「食品饮料方向」——**明显不合理**（消费电子属电子行业，非食品饮料）。**根因已定位（非标签错标，是分类规则子串误匹配）**：
  - `ETFClassifier` 实测（`etf_classifier.py`）：562950 的 tracked_index="中证消费电子" 或 name="消费电子ETF易方达" → 命中 `_NAME_RULES:80`（`etf_classifier.py:28` 起的名称规则表）与 `_INDEX_RULES:145`（`etf_classifier.py:136` 起的指数规则表）的 **`("消费", "食品饮料", ...)`**——`_match` 是 `keyword in text` **子串匹配**，`"消费" in "消费电子"` = True → 误归食品饮料（**confidence=0.85 高置信度错误**）；
  - **影响面**：所有名称/tracked_index 含「消费」的标的（消费电子/消费50/消费龙头/消费红利/消费医药/港股消费等）均可能被误归「食品饮料」——规则表对宽泛关键词无精确性防护；
  - **通用缺陷（保留）**：`build_rationale`（`rationale.py:137-138`）行业文案**无名称/指数交叉校验、无分类置信度门槛**——`industry` 标签一旦错（或为 unknown），理由直接失真。
- **P25 策略检查 LLM 恒超时 + 数据缺失（采集超时全丢弃 + 超时设置失衡）**：
  - **① 数据缺失直接根因——采集超时全丢弃（注释与实现不符）**：`portfolio_service.py:603-609`——`asyncio.gather(indicators_task, factor_task, return_exceptions=True)` 外包 `wait_for(timeout=30)`，**wait_for 超时会取消整个 gather，已部分完成的结果也拿不到** → 日志写「using partial results」但实际赋 `indicators, factor_scores = {}, {}` **全空** → `factor_breakdowns` 空 → `data_quality.all_empty=True` → LLM 收到空上下文输出「数据缺失」结论。**数据缺失是采集超时丢弃导致，非 LLM 问题**；与 P2（线程池饱和→指标/K线慢）联动。
  - **② LLM 超时设置失衡**：策略检查 LLM `wait_for(timeout=30)`（`portfolio_service.py:685`）——对比：设计报告 90s（`report_worker.py:90`）、Provider httpx 层 240s（`config.py`）、外层管线 120s（`strategy_check_worker.py:91`）。**30s 是全线最紧**；round6 F9 从 60s 降 30s 的动机是「用户等待减半」，但数据采集也占 30s——**总等待没减，只是把 LLM 挤没了**（采集用满 30s 后 LLM 实际剩余不足，恒超时 → 规则兜底常态，round7 P5 确认）。
  - **③ 规则兜底文案不专业**：兜底 summary 固定「LLM 分析超时（30s 未返回）」+ `data_quality` 未进兜底文案——专业投资者看到的是「数据缺失」而非「超时原因 + 已有数据摘要」。
- **P26 技术分析图表无当前周期/类型可视化（UX）**：`AnalysisView.vue` 图表标题区两分支均不完整——
  - **K线分支**（`AnalysisView.vue:407-411`）：title = `periodLabel`（如「日线」），但为 **12px/#888 左上角浅灰小字**（F15 已实现但过弱），且**不含图表类型**（K线）与标的名；
  - **分时分支**（`AnalysisView.vue:181`）：title = `seriesName`（仅标的名，居中），**无「分时」类型标识**——用户切到分时后图表内无从得知当前是分时图；
  - **模式按钮选中态**（`ControlPanel.vue:17-18`）：`mode-btn--active` 样式存在（`ControlPanel.vue:70` brand-600 高亮），但仅颜色差异、无 aria-pressed，视觉区分弱——用户反馈「没有标记展示当前选中哪个」。
  - 周期下拉（AppSelect）自身有回显，但**图表区域与选择控件的对应关系**不直观（F15 只解决 K 线周期、未覆盖分时类型）。
- **P27 自选添加后列表不更新 + 新条目后三列为空**：
  - **① 添加后列表不更新（前端数据流断裂）**：`WatchlistPanel.vue` 列表数据源是**本地 `items` ref**（`fetchItems()` 内 `items.value = store.watchlist` 拷贝，218-228 行），但 `addItem`（259-273 行）成功后**只关 modal、未调 `fetchItems()`**——注释（267 行）声称「store 已乐观插入（POST 带 realtime）并后台刷新」，但 store 乐观插入（`market.js:154`）改的是 `store.watchlist`，**组件本地 `items` 副本不响应** → 列表不出现新条目，需手动刷新（刷新后 `fetchItems` 重新拷贝才可见）。
  - **② 新条目后三列为空（realtime=null）**：store 乐观插入 `realtime: added.realtime || null`（`market.js:154`）；后端 `add_watchlist` POST 响应带 realtime（`market_service.py:1452`），但数据源冷却时 `get_asset_realtime` 返回 None（P12 同源）→ 前端 `v-if="item.realtime"`（`WatchlistPanel.vue:124-131`）不渲染 → 后三列（最新价/涨跌幅/成交量）显示「—」。**刷新后批量 GET /watchlist 有 realtime**（P12：列表批量正常）→ 验证了「主动刷新才能看到完整数据」。
- **P28 热点板块 tab 空态体验 + 热点股票技术分析内容单薄**：
  - **① 「板块热度」tab 切换后卡片内容消失**：`SectorHeatMap.vue` 的 `switchTab`（186-191 行）先 `dataList.value = []` 再异步 `fetchData()`——**切换瞬间列表清空**且 `loading` 未置 true → 直接落入 28 行 empty-state「暂无板块数据」空态闪烁；数据源冷却时 `getSectorHeat`（210 行）返回空 → **空态持续**，用户误以为「卡片消失」。空态文案「暂无板块数据」在数据源不可用时具误导性（非真无数据）。
  - **② 热点股票技术分析缺 K线/涨跌幅/资金流**：`TechnicalAnalysisModal.vue` 的 `load()`（128-143 行）只并行调 `marketApi.indicators` + `marketApi.signal`——仅指标卡片（RSI/MACD/KDJ/MA/BOLL + 信号），**无 K 线图、无今日涨跌幅、无资金流**；而数据源均已存在：K线 `marketApi.chart`（`api/index.js:34`）、涨跌幅 `realtime`（列表行已有 price/change_pct）、资金流**后端 `get_fund_flow` 已实现**（`market_data_hub.py:1615`，东财 `fetch_fund_flow`）但**无 router 端点暴露、前端无 API 封装**——「资金流入流出」完全未接通。
- **P29 AI 投顾输入框市场切换未复原（一行缺失）**：`AiAdvisor.vue:62-68` 的 `watch(() => props.marketTab)` **已实现**市场切换重置（R5）——`stopStream()` + `response=''` + `error=''` + `loading=false`，但**漏了 `query.value = ''`**：注释（62 行）声称「旧市场的投顾回答/输入不应残留」，实际只清回答、**输入框（`v-model="query"`，13 行）残留 A 股问题时切换美股的内容**——用户从 A 切到 US 后输入框仍是 A 股问题，语义错乱（与 P27 同类「注释意图 vs 实现缺失」）。
- **P30 标的分析搜索补全缺板块/指数 + 页面加载布局抖动**：
  - **① 板块/指数无自动补全**：后端 `/search`（`market.py:73-163`）只返回 stock/etf/HK/US 段——**无板块（sectors 表 991 行）与指数（indices_meta 表 588 行）段**；前端下拉仅挂 `activeMode === 'symbol'`（`UnifiedAnalysis.vue:36`）——sector/index 模式（`query` 直接提交，103 行）**无下拉建议**，输入错名只能等空结果/404；
  - **② 页面加载布局抖动（CLS 交互体现）**：`SectorHeatMap.vue` loading skeleton 仅 **5 行（48px×5=240px）**，而 hot tab 加载后 15 条数据（~56px×15≈840px）——**加载完成撑高 ~600px**，下方 `AiAdvisor`/`UnifiedAnalysis`（标的分析输入框）被整体推下视口 → 用户打开页面（滚动位置在标的分析）后屏幕变成热点板块排行（P4 CLS 0.393 的具体交互表现）；`MarketReport`/`AiAdvisor` 无骨架占位同类。
- **P24 入选理由与入选决策缺乏因果链**：rationale 是**描述型**（行业 → 技术面 RSI/MACD → 复合因子分 → 综合信号 → 市场状态 → 层角色模板），**无「为什么选中它而非同类」的归因**——因子分排名、层内竞争、预算约束均未进理由；专业投资者看到「技术面综合评分 +4.638」无法判断该分在候选池的位次、以及是否因动量/估值/技术哪个因子主导而入选。

---

## 3. 组合设计 & 策略检查（步骤 2）详审

**设计（design 192 → 390）**：
- 三套方案 def/bal/agg，预算结构合理，CASH 预留（20.3%/15.0%/29.8%），rationale 有数据支撑。
- ⚠️ 进攻型核心层预算 0.4 实配 0.27、现金 29.8%（风格未集中在核心 beta）；`industry` 63% 权重为空（行业数据缺失）。
- ⚠️ RSI 失真（见 P6）；科技因子裁剪触发（卫星层 tech 超预算）。

**策略检查（check 193 → 314，on_exchange）**：
- ✅ `on_exchange` 过滤生效：10 条建议全为场内 ETF。
- ✅ `holdings_analysis` 用真实 RSI(14)（39-60），`factor_availability` 23-24/34。
- ❌ 全部建议 `source=rule`（LLM 无一份完成），summary 固定"LLM 分析超时（30s 未返回）"。
- ❌ `industry` 全空 + 行业集中度 risk_warning。

**专业投资者视角**：方案结构与风格表述可读、措辞专业、与市场（成长占优/情绪谨慎）大方向匹配，**逻辑上可接受**；但 LLM 兜底常态+行业数据缺失+RSI 失真使"数据完整性"被打折扣——专业投资者会质疑"策略建议究竟有多少来自真实分析"。

---

## 4. 多市场行情分析（步骤 3）详审

| 链路 | 结果 | 专业审阅 |
|------|------|---------|
| A 股综合研判 | ✅ indices=10 完整（上证+0.33/创业板+5.64/科创50+4.09，剪刀差分析） | 优秀 |
| 港股研判 | ✅ 无 A 股指数混入（R5-2-5 生效） | 优秀 |
| 美股研判 | ✅ VIX/美债/利率全 | 优秀 |
| AI 投顾 | ⚠️ 全数据缺失模板（P7） | 不可用 |
| 个股 600519 | ✅ 基本面+技术面完整 | 优秀 |
| ETF 510300 | ✅ 但 PE/PB 数据源不可用 | 良好 |
| 板块 半导体/光伏 | ✅ 均 200（R6-04 修复） | 优秀 |
| 概念 AI | ✅ 200 | 优秀 |
| 指数 000300 | ⚠️ 技术指标/K线/PB 空（P10） | 良好 |
| 搜索补全 | ⚠️ A 股已可命中（茅台/恒生/半导），US/HK 空（P3） | 缺陷在 US/HK |

> 口径注：表中"综合研判/个股分析 优秀"指的是**对应分析端点**数据驱动质量高（综合研判含完整指数行情）；与**指数分析端点**的技术指标/K线/PB 为空（P10）不是同一链路——综合研判读 `indices` 快照，指数分析端点读单标的 K 线/估值，前者数据路径完整、后者缺估值源。二者不构成矛盾。

综合研判与权益类分析（个股/板块/概念）质量高、数据驱动、逻辑严谨，专业投资者可接受；短板集中在**投顾（P7）、指数估值/ K线（P10）、US/HK 个股搜索（P3）**。

---

## 5. round6 问题清单核对（步骤 10）

| 项 | 状态 | 说明 |
|----|------|------|
| R6-01 构建回归 | ✅ 修复 | 本次 docker build 成功（mootdx 移出裸依赖 + --no-deps） |
| R6-02 mootdx 容器空转 | 🔴 复现 | 预热 market_cache 64s；全新容器无 BESTIP |
| R6-03 A01 warmup 字段 | ✅ 修复 | `/system/warmup` 返回 total_elapsed + elapsed_seconds |
| R6-04 sector/concept 404 | ✅ 修复 | BK1036/AI/光伏全 200（limit500 + F19 名称归一化） |
| R6-05 RSI 失真 | 🔴 未对齐 | 根因：`get_factor_matrix` 强制 z-score（不尊重 YAML raw），`_RAW_KEEP` 无 rsi_14；详见 P6 |
| R6-07' advice 注入空 | 🔴 复现 | AI 投顾全数据缺失模板 |
| R6-08 预热劣化 | 🔴 复现 | 128s |
| R6-10 US 个股搜索空 | 🔴 复现扩展 | US/HK instruments 表空（US=0 代码缺失、HK=0 数据源）；A 股中文名已命中 |
| R6-15 summary 文案 | ✅ 修复 | llm.py:1408 动态时长 + 诊断后缀 |

（R6-06/09/12/14/16 部分见日志/后续复验，本次主链路未直接触发；R6-11 线程池饱和**已在本轮复现**，见 P2，已从本条移出。）

---

## 6. 测试防护盲区（步骤 13）

既有体系：`backend pytest`（全 mock 外部源）+ `verify_e2e.py`（真实 HTTP 契约）。

**盲区 14 类**（1-4 环境层 / 5-14 用例与断言层，成因复盘见 6.5）：
1. **真实数据源降级**：单测全 mock → mootdx 空转、冷启动 BESTIP、历史 K 线 RemoteDisconnected 路径零覆盖。
2. **并发压力**：verify_e2e **顺序同步**，测"启动后稳态"，不测启动预热高峰；shared_executor 64/64 需并发才触发（预热 gate 也仅特殊配置 PROFILE_WARMUP 才真实断言）。
3. **数据源冷却 State 语义**：`akshare/dongfang=cooldown` 被标 **PASS**，不判定"数据缺失资格"、不告警 → 成交额/候选缺失加速通过。
4. **前端渲染性能**：契约只测 HTTP 状态，不测 LCP/CLS/未用 JS → 仅 Lighthouse 暴露。
5. **前端状态残留/生命周期**：AppTabs `:hidden` 面板常驻导致组件状态跨 tab 残留（P17），既有单测均直接挂载组件、未覆盖「切走再切回」的复位行为。
6. **宽基重叠 / 主题集中度**：既有门禁只覆盖「中证500家族 ≤1」（P1-1 验收3）与「成长宽基权重 ≤40%」（F6），未覆盖「大盘宽基族互斥」（P18）与「卫星科创数量上限」（P19）——A50/A100/A500 同现、科创 4 只同现均能通过现有测试。
7. **因子常量输出 → no_data 语义**：`/factors/active` 的 no_data 分「数据源未接入」（`_data_source_gaps`）与「IC 未累积」两分支，但**常量因子**（底层字段全缺 → 截面 std=0 → IC 跳过）未单独标注（P20）；`etf.industry_diversification` 不在 GAP_CODES → reason 误报「IC 未累积」。现有单测未覆盖「字段全缺 → 常量 → no_data reason」链路。
8. **展示数据兜底 / 标签可信度 / 归因链**：① 设计方案「今日涨跌」fallback 键名错误（`fm.get("change_pct")` vs 实际 `etf.change_pct`，且 z-score 值被当真实涨跌）**无测试覆盖**（P22）；② rationale 行业文案无名称/置信度交叉校验，错标标签直接失真（P23）；③ rationale 无归因段，无法验证「理由 ↔ 入选决策」一致性（P24）。
9. **采集超时丢弃 / 超时分层**：`wait_for` 包裹 `gather` 超时即**取消并丢弃部分结果**（策略检查采集 P25①）；LLM 超时策略检查 30s / 设计 90s / provider 240s 三层不一致，无「按数据完整性分级」的超时预算测试。
10. **图表状态可视性**：echarts title 断言（周期/类型标注）无前端测试覆盖（P26）；`mode-btn--active` 选中态仅样式无 aria/语义断言。
11. **自选添加数据流**：`addItem` 成功不触发本地列表同步（P27①）无测试覆盖——`WatchlistPanel.spec.js` 未断言「添加后列表出现新条目」；乐观插入条目 realtime=null 的渲染（「—」列）未覆盖。
12. **tab 切换状态 / 弹窗内容完整性**：`switchTab` 清空列表导致空态闪烁（P28①）无测试；`TechnicalAnalysisModal` 只测指标渲染、未覆盖 K线/涨跌幅/资金流区块（P28②）——后端 `get_fund_flow` 无端点/契约测试。
13. **投顾输入复位**：`watch(marketTab)` 漏 `query` 复位（P29）无测试——`AiAdvisor.spec.js` 未断言市场切换后输入框清空。
14. **搜索类型覆盖 / 骨架高度**：`/search` 无板块/指数段（P30①）无测试（sectors/indices_meta 表可查但未进端点）；skeleton 高度 vs 加载后高度无 CLS 断言（P30②）。

### 6.5 复盘：为什么 14 个新问题（P17-P30）全部漏检（用户 2026-08-04 审查）

三层防护（后端全 mock 单测 1421 / 前端单测 374 / verify_e2e 契约 271）数量充足但**「测对了」≠「测全了」**。P17-P30 漏检根因归为 6 类：

1. **断言验证「实现」而非「需求」**（P29/P27/P22）：测试断言方法被调用（动作），不断言用户可见行为（结果）——`AiAdvisor.spec` 断言 response 清空而非输入框清空（P29）；`WatchlistPanel.spec` 断言 addWatchlist 被调而非列表出现新条目（P27）；`strategy_design` 测试 mock pool 有 change_pct 的路径，死代码 fallback 分支零覆盖（P22）。**纠偏原则：每个交互测试补「结果级断言」（渲染了什么），而非只验「动作级」（调用了什么）。**
2. **正向用例思维，缺边界/冲突用例**（P23/P18/P19）：分类器测试每规则一条正向用例，不测规则间子串冲突（`"消费"⊂"消费电子"`，P23）；分配器测试 happy path，不构造「A50+A100+A500 同进候选」「科创 6 只」组合输入（P18/P19）。**纠偏：规则表/分配器必须配「冲突矩阵」负向用例。**
3. **组件孤立挂载，缺集成场景**（P17/P26/P28-①）：单测直接挂载组件，不经 AppTabs 包裹——`:hidden` 常驻导致的跨 tab 状态残留（P17）在测试环境不存在；echarts title 文本不读（P26）；切 tab 不清空列表不断言（P28①）。**纠偏：生命周期/跨组件场景用「父容器包裹挂载」测试。**
4. **全 mock 杀死降级分支**（P25/P20）：mock 数据源秒回 → `wait_for(30s)` 超时丢弃分支、常量因子（std=0）路径**零执行**。**纠偏：降级/超时须专项测试（盲区 1/9 落地）。**
5. **verify_e2e 是契约级非语义级**（P22/P23/P30-①）：断言字段存在，不断言值合理——`daily_change_pct` 全 None 也 PASS；rationale 行业方向错也 PASS；`/search` 无板块/指数段因契约未定义而无从断言。**纠偏：契约检查补充「语义门禁」（非空/值域/一致性）。**
6. **环境类失败被验收口径豁免**（P20）：`etf_specific no_data ≤2` 门禁真实 FAIL（实测 5）但按「数据源冷却」放行——`premium_discount` 的 **nav 三级源在用户环境全失败**（环境/数据源可用性问题，非代码缺口——复核确认管线存在）被环境口径掩盖。**纠偏：cooldown 豁免须先排除代码缺口（盲区 3 落地）。**

> 与 §6 盲区 1-4 的关系：既有 4 类盲区（真实数据源降级/并发/冷却语义/前端渲染）是「环境层」漏检；6.5 是「用例与断言层」漏检——两者叠加解释了 P17-P30 全漏。

---

## 7. 优化与修复方案（本轮不实施）

### 后端
- **O1 预热治理**：为 mootdx 增加启动 BESTIP 探测与重试（或容器内预写 config.json）；`etf_list_cache` 阈值改为"镜像层带快照、挂载卷仅增量刷新"，避免全量 1618 扫描。目标预热 <20s。
- **O2 线程池护栏**：批量历史 K 线改为**限流分批** + 失败快速跳过，并控制并发峰值。⚠️ 方向注：round6 曾建议 shared_executor 扩容 64→（R6-F10），本轮实测为**启动预热高峰打满**而非容量不足——**建议方向与 round6 相反（控并发而非扩容）**，需在实施前统一口径（以本轮预热高峰负载实测为准）。
- **O3 个股搜索**：① US 段在 `sync_instruments.collect_all()` 补实现（当前仅 A/HK/etf）；② HK 段排查 akshare 源同步失败；③ **A 股中文名搜索尽力复测已命中（茅台/恒生/半导），无需处理**——重点放在 US/HK 数据源补全。
- **O4 RSI 对齐**：让 `get_factor_matrix()` 对 `standardization=raw` 的因子（rsi_14 等）**跳过截面 z-score**，或把原始 0-100 值通过 `_RAW_KEEP` 保留下发，rationale 读真实 0-100（消费路径是 `get_factor_matrix`，不是 `factor_registry._standardize`）。
- **O5 LLM 超时与注入**：策略检查 LLM 由 30s 放宽到 90s（或分级降级）；投顾数据注入与 llm-report 同源（复用全局指数兜底）；**修复 `news-impact` 的新闻正文传递**（当前 `news` 未进 LLM，返回"内容为空"——与 P7/P16 同源注入断裂，一并排查 `llm-advice`/`news-impact` 两端的上下文组装）。
- **O6 因子数据路径**：对历史 K 线失败源做重试+节流；`etf_specific` 三因子补充数据源或降级为 static 并明确标注；**给 `/factors/model` 补输出 `valid/no_data/warn/static` 聚合字段**（当前为 null，前端无法读模型健康度，见 P8）。
- **O7 资讯分级**：宏观/国际分级改为"按市场相关性与重要度"智能分级，杜绝混入个股/营销。
- **O8 `/portfolio/etfs` 补充实时 price**；自选新建时联查 realtime。

### 前端
- **O9 vendor 瘦身**：echarts/axios 按需引入、配置 chunk 拆分与懒加载，消除 85KiB 未用 JS，降主线程占用。
- **O10 CLS 治理**：图表/列表渲染前固定骨架高度（aspect-ratio / min-height），消除二次撑高。

### 测试防护
- **O11** 增加"真实数据源降级"契约探针（冷启动 assert 预热 <20s）。
- **O12** 增加"预热高峰并发"负载断言（在启动阶段并发采样 shared_executor）。
- **O13** 名称搜索（茅台/apple/腾讯）补入 verify_e2e 契约集；cooldown 态升级为数据缺失告警。
- **O14** 前端 CI 接入 Lighthouse（performance ≥ 0.7 gate）。
- **O15 AI 工具默认落工具列表（P17 修复）**：
  - **推荐方案 D（局部、可测）**：`PortfolioAnalysis.vue` 向 `<DashboardAiTools>` 传 `:active="activeTab === 'tools'"` prop；`DashboardAiTools` 新增 `watch(() => props.active)`，false→true（重新进入 AI 工具 tab）时执行 `resetToTools()`——`activeCoreFeature=null; designStep='wizard'; designTab='cards'; expandedPlan=null; showHistory=false`，并通过 `:key` 或 emit 复位 `DesignHistory.statusFilter='all'`；**运行中 design 任务例外**：复位前检查 `taskStore` running 任务，有则保留现有恢复 loading 逻辑（与 `onMounted` 一致，任务不丢）。
  - 备选 C（更简单、切走即重置）：`#tools` slot 内 `<DashboardAiTools v-if="activeTab === 'tools'">`——切走销毁/切回重挂载，天然复位；缺点：wizard 表单输入与查看中的方案在切 tab 时丢失，loading 任务恢复依赖 `onMounted` 现有逻辑。
  - 备选 E（全局能力，风险面大）：AppTabs 真正实现 `lazy` 按需挂载（`v-if="lazy ? modelValue===tab.value : true"`），PortfolioAnalysis 传 `lazy`；需回归 AppTabs 全部 4 个使用方（Dashboard / PortfolioAnalysis / DesignResult / TokenMonitor），不建议本轮采用。
  - **待确认决策点**：① `onMounted` 的 `getDesignState()` 是否改为仅恢复 running 任务、不再自动恢复已完成 design 结果（消除「刷新后默认跳旧结果」）；② `DesignHistory.statusFilter` 每次进入是否强制回 'all'。
  - 测试：`DashboardAiTools` 新 spec——`active` false→true 且无任务 → 断言工具列表可见（`activeCoreFeature=null`）；有 running 任务 → 断言保持 loading；`PortfolioAnalysis.spec.js` 补 tab 切换复位断言。
- **O16 核心层大盘宽基族互斥（P18 修复）**：
  - 新增 `_is_large_cap_wide_basis(c)`（`allocation_engine.py`）：基于 `tracked_index`/`name` 识别**大盘/超大盘宽基**——沪深300/中证A500/中证A50/中证A100/上证50/上证180/深证100/中证100/中证800/MSCI中国（与 `_is_growth_wide_basis` 并列，互斥口径：大盘 vs 成长 vs 中盘）。
  - 约束：核心层「**非强制大盘宽基**」数量 ≤ 1（强制锚 510300/560600 已占 2 个大盘宽基名额；`MANDATORY_CODES` 不受影响）；balanced/aggressive 建议 ≤0（锚已覆盖大盘 beta），defensive 允许 ≤1（上证50 场景，与 R5-0-4 红利/防守定位兼容）。
  - 实现位置：**在 `allocate()` 核心层 `_select_and_weight(_core_pool, layer='core')` 调用后裁剪**（`allocation_engine.py:651-660`，不动 `_select_and_weight` 内部卫星逻辑）——校验非锚大盘宽基数量，超出按 composite 降序剔除低分者、权重按其余核心权重占比回补；兜底——剔除后核心层 <3 只时放宽至保留 ≤1 只非锚大盘宽基（保证数量下限 [3,5]，与 P1-2 兜底口径一致）；defensive 允许保留 1 只（上证50 场景）。
  - 验收：三方案核心层「非强制大盘宽基」≤1；balanced 不再出现 A50/A100 与 A500/沪深300 三锚并存；design 398 复算（若用修复后代码重跑同场景）不产生 4 宽基同现。
  - 测试：`test_large_cap_wide_basis_exclusion.py`——① 构造 A500(强制)+A50+A100+沪深300(强制) 候选 → 断言核心层非锚大盘宽基 ≤1 且被剔除者权重回补其余核心；② defensive 上证50 保留 1 只不回归；③ 剔除后候选不足时放宽兜底生效（核心层 ≥3）。
- **O17 卫星层科创数量上限（P19 修复）**：
  - 在 `_select_and_weight` 卫星层科技 trim 段（`allocation_engine.py:377-440`）增加**数量维度**：科创系（`_is_tech_theme`，含 科创/半导体/芯片/AI/人工智能——「科创创新药/科创新能源/科创AI/科创芯片设计」名称均命中）标的数量 **≤ 2 只**（与 F7 门禁「卫星 ≥4 只且 ≥2 非科技主题」呼应；8 只卫星时科创 ≤2 → 非科技 ≥6，主题多样）。
  - 与现有权重配额（≤ budget×40%/50%）**取更严**：先权重裁剪（现有），再数量裁剪——科创按 composite 降序保留至 ≤2 只，被裁权重回补其余卫星（复用现有 reclaimed 回补机制）。
  - 验收：任意方案卫星层科创系数量 ≤2 且权重 ≤ 配额；design 398 balanced（4 科创）复算后科创 ≤2。
  - 测试：`test_satellite_tech_count_cap.py`——① 8 只卫星含 4 科创（权重 14.6% < 配额 15%）→ 断言数量裁剪至 ≤2、被裁权重回补非科创；② 数量达标但权重超配额 → 权重裁剪仍生效（取更严交叉用例）；③ 非科创候选不足时被裁权重转 CASH（复用现有 432-438 行行为）。
- **O18 premium_discount nav 源加固（P20-① 修复，方向修正）**：**先诊断再补源**——现有三级 nav 源（Sina http `hq.sinajs.cn` → QQ `qt.gtimg.cn` → TTJ `get_fund_nav` 日净值）在用户环境全失败，需先确认失败原因（超时/被墙/**http 明文被禁**——Sina/QQ 均为 http，若网络层禁明文则必须换 https 源）：
  1. 诊断：`fetch_etf_iopv`（`ttj_fetcher.py:90`）/ Sina / QQ 三路在用户环境逐一探测，定位失败层（source registry 事件已有记录可查）；
  2. 补 https 源：若确认 http 明文被禁 → 新增东财 push2 **https** 行情 `f236`（IOPV）字段源（复用 `EM_PUSH_HOST` 域，R61 门禁），作为 Sina/QQ 之后的第三顺位（不替换现有降级链）；TTJ 日净值保持末位兜底；
  3. 验收：用户环境 `premium_discount` 因子不再 no_data（reason 不再是「缺 nav」）；`verify_e2e etf_specific no_data ≤2` 转 PASS；
  4. 测试：`test_nav_source_fallback.py`——mock Sina 失败 → QQ 兜底、双源失败 → TTJ 兜底、三级全失败 → gap 记录「缺 nav」（三场景）；东财 https 源接入后补其单测。
- **O19 tracking_error 指数映射补全（P20-② 修复）**：`_WIDE_BASIS_INDEX_CODES`（`market_data_hub.py:1189`）补新宽基映射——560600→中证A500(`sh000510`)、563080→中证A50(`sh932000`)、562000→中证A100(`sh000903`)、563020 红利低波、按候选池实际符号补全；`benchmark_close` 覆盖后 `tracking_error` 不再因「无基准序列」no_data（数据源失败时 reason 已正确）。
  - 验收：560600/563080/562000 进核心层时 `factor_breakdown` 含非空 `benchmark_close`（数据源可用时）→ `tracking_error` 非常量；数据源失败时 reason 仍为「缺 benchmark_close」。
  - 测试：`test_benchmark_close_mapping.py`——① mock `get_market_history` → 断言 `_enrich_symbol_extra` 对新宽基注入 `benchmark_close`（close[-20:]）；② 映射表完整性：候选池快照出现的宽基符号必须已登记（缺失即 FAIL，防下次新增宽基漏配）。
- **O20 industry_diversification 数据语义 + no_data reason 修正（P20-③ 修复）**：
  1. 确认 ETF 概念标签来源：etf_scanner 候选若可打概念（东财板块字段/akshare 主题）→ 补 `concepts`；若 ETF 无概念语义 → `_compute_industry_diversification` 改用已有 `industry` 字段（候选池 industry 63% 为空，见 §3）或按 `fund_scale` 分档，避免恒 0.0 常量；
  2. `ET_SPECIFIC_GAP_CODES` 加 `etf.industry_diversification: "concepts"` → reason 修正为「数据源未接入（缺 concepts）」而非误导的「IC 未累积」；
  3. **通用改进**：`/factors/active` 对**常量因子**（截面 std=0 → IC 无法计算）给独立标注（如 reason「截面无差异（常量输出），检查底层数据」），与「数据源未接入」「IC 未累积」三分——消除「看起来像样本不足、实际是数据全缺」的误导（P20 共同机制）。
  - 验收：`/factors/active` 的 `etf.industry_diversification` reason 为「数据源未接入（缺 concepts）」或「截面无差异（常量输出）」之一（不再误报「IC 未累积」）。
  - 测试：`test_industry_diversification_reason.py`——① concepts 空 → 因子常量 0.0 → reason 独立标注「截面无差异」；② concepts 非空 → `1/n` fallback 生效（industry_diversification 有值）；③ GAP_CODES 含 `industry_diversification` → reason 走「数据源未接入」分支。
- **O21 IC 数值含义解释（P21 修复，前端）**：
  - `FactorModelView.vue`：summary 卡「平均 |IC|」stat 包 `AppTooltip`（IC 定义 + 分档）；汇总卡下方加「IC 解读」说明卡（静态文案 + 动态阈值）——**IC（信息系数）= 因子值与未来收益的 Spearman 秩相关**；正值=因子值越高未来收益越高，负值=反向；`|IC| < 0.02` 无预测力 / `0.02~0.05` 弱 / `≥0.05` 有效 / `≥0.1` 强；默认阈值 `ic_threshold=0.02`（`factors.py:158`）。
  - `FactorICView.vue`：表格「IC 值」表头 tooltip + 顶部一行小字说明（复用 `FactorModelView` 文案或抽公共说明组件 `FactorICExplain`）。
  - 测试：`FactorModelView`/`FactorICView` spec 断言说明区渲染（含阈值文案）。
- **O22 设计方案「今日涨跌」三级兜底（P22 修复）**：
  1. **修 fallback 死代码**：`strategy_design.py:259-267` 键名修正（查 `fm.get("etf.change_pct")`），并**拒绝 z-score 值当真实涨跌幅**（`etf.change_pct` 是归一化值，恒 ≠ 真实涨跌——fallback 应跳过它）；
  2. **快照兜底**：`get_by_code()` 与 factor_matrix 均缺时，从 `etf_list_cache.json` 快照读真实 `change_pct`（scanner 缓存，如 560950=1.358）注入 `daily_change_pct`；
  3. **K 线兜底**：仍缺时用 K 线 close 序列 `(close[-1]-close[-2])/close[-2]`（复用 `factor_registry._compute_change_pct` 逻辑；K 线缓存已在因子计算时获取）。
  - 测试：`test_design_daily_change_fallback.py`——pool 缺 / pool+matrix 缺 / 全缺三场景断言 daily_change_pct 三级回落且非 z-score 值。
- **O23 入选理由行业标签可信度校验（P23 修复）**：
  1. **分类规则精确化（根因修复，`etf_classifier.py`）**：`_NAME_RULES`（80 行「消费」规则前）与 `_INDEX_RULES`（145 行「消费」规则前）**各前置 `("消费电子", "电子", ["消费电子", "电子"])` 规则**（精确词优先于宽泛「消费」子串）——562950 等消费电子标的归「电子」而非「食品饮料」；**顺带评审其他宽泛关键词**（「金融」「商品」「有色」「汽车」等子串是否有类似误伤，如「汽车电子」）；
  2. **名称/指数交叉校验**（`rationale.py:137-138` 通用分支）：`asset_name`/`tracked_index` 命中宽基语义关键词（`_A_WIDE_BASIS_KEYWORDS`）而 `industry` 为具体行业（或 unknown）时，行业文案以「宽基指数」为准（与 `_is_wide_basis` 语义补判同模式）；
  3. **分类置信度门槛**：`industry` 来源置信度 <0.7（`ETFClassifier` confidence）时降级为基于名称的保守描述（不输出误导的具体行业）；
  4. 回归测试：`test_rationale_industry_sanity.py`——**562950**（tracked_index="中证消费电子" 与 name 双路径）断言 industry=「电子」；消费50/食品饮料正向用例不回归。
- **O24 入选理由增加归因链（P24 修复）**：
  - `build_rationale` 增加**归因段**（可选参数 `rank_info`，由 `strategy_design` 传入候选池排名上下文，保持纯函数）：① 综合因子分在候选池的**分位**（如「因子分 3.2 居核心候选前 25%」）；② **主导因子**（贡献最大的 1-2 个因子名 + 方向）；③ **层内竞争**（如「同类 3 只中因子分最高」）；
  - 模板化层角色句保留但置于归因之后——「描述型 → 归因型」过渡，专业投资者可验证「理由 ↔ 入选决策」一致性；
  - 测试：`test_rationale_attribution.py`——断言归因段含分位/主导因子/竞争信息；rank_info 缺省时向后兼容（无归因段）。
- **O25 策略检查数据管道 + LLM 超时分级（P25 修复）**：
  1. **采集部分结果保留**（P25①，`portfolio_service.py:598-609`）：`_compute_indicators` 与 `factor_registry.compute` **各自独立 `asyncio.wait_for`**（如各 25s，`return_exceptions` collect 部分成功），外层不再用 `wait_for(gather)` 整体取消；修复「注释 partial 实际 {} 」不一致——任一成功即保留（`data_quality.partial` 已有语义）。
  2. **LLM 超时按数据完整性分级**（P25②，`portfolio_service.py:678-686`）：`data_quality.all_empty` → **15s** 快速兜底（上下文不足，快速失败更合理）；`partial` → **30s**；数据完整 → **60s**（对齐设计报告 90s 可再放宽至 90s）。同步调整外层管线 120s → 150s（`strategy_check_worker.py:91`）。
  3. **兜底文案专业化**（P25③）：规则兜底 summary 携带 `data_quality`（N/M 因子可用 + 缺失原因），不再固定「LLM 分析超时」。
  4. **数据源联动**：采集慢根因 = 历史 K 线/因子慢（P2 线程池饱和 + 数据源冷却）——O2 并发护栏落地后自然缓解；策略检查优先复用 `market_cache`/`etf_cache` 预热缓存。
  - 测试：`test_strategy_check_partial_data.py`——① 采集单任务超时 → 断言保留另一任务结果（非全空）；② 数据完整性分级超时（all_empty 15s / partial 30s / full 60s 生效）；③ 兜底 summary 含数据质量摘要。
- **O26 技术分析图表周期/类型可视化（P26 修复，前端）**：
  1. **图表标题统一双标注**（`AnalysisView.vue`）：
     - K线分支（407-411 行）：title 改为 **`"{periodLabel} · K线 · {seriesName}"`**（周期 + 类型 + 标的名），字号 12→14px、颜色 #888→`--color-text-secondary`（F15 的强化版）；
     - 分时分支（181 行）：title 改为 **`"分时 · {seriesName}"`**（补类型标识，与 K 线对称）；
  2. **模式按钮选中态强化**（`ControlPanel.vue:17-18`）：`mode-btn--active` 增加 `aria-pressed` + 加粗（`font-weight: 600`）+ 下边框强调（视觉差异不再仅靠颜色）；
  3. 测试：`AnalysisView.spec.js` 断言 K 线 title 含周期+类型、分时 title 含「分时」；`ControlPanel.spec.js` 断言 `aria-pressed` 与 active 类同步。
- **O27 自选添加后列表即时同步 + 后三列补齐（P27 修复，前端）**：
  1. **addItem 成功后同步本地列表**（`WatchlistPanel.vue:264-267`）：`await store.addWatchlist(...)` 后调 **`await fetchItems()`**（与 removeItem/updateWatchlist 一致）——乐观插入保留（快速反馈），fetchItems 用批量 GET 补齐 realtime（批量路径有值，P12）；备选：`items` 改为 `watch(() => store.watchlist)` 响应式绑定（零拷贝，推荐一并做，消除本地副本漂移）；
  2. **realtime=null 渲染优化**（可选）：乐观条目 realtime=null 时后三列显示「加载中…」而非「—」，fetchItems 完成后自动补值（数据源冷却时最终仍为「—」，P12 后端侧待源恢复）；
  3. 测试：`WatchlistPanel.spec.js` 断言 `addItem` 后 `fetchItems` 被调用且列表出现新条目（mock `store.addWatchlist` 返回条目 + `store.fetchWatchlist`）；realtime=null 条目渲染「—」不崩溃。
- **O28 热点板块 tab 体验 + 热点股票技术分析增强（P28 修复）**：
  1. **tab 切换保留旧数据 + 明确空态**（P28①，`SectorHeatMap.vue`）：`switchTab` 不再先清空 `dataList`（保留旧数据直到新数据到达，`fetchData` 内 `loading=true` 时显示 skeleton）；`error`/空态文案区分「数据源不可用」（如「板块热度数据暂不可用，请稍后刷新」）与「暂无数据」，消除「卡片消失」误读；
  2. **技术分析弹窗增强**（P28②，`TechnicalAnalysisModal.vue`）：`load()` 增加并行获取——
     - **K线图**：`marketApi.chart(symbol, assetType, 'daily')` → echarts 迷你 K线（复用 `AnalysisView` 的 K线 option 模式）；
     - **今日涨跌幅**：`marketApi.getRealtime(symbol)`（或行内 item 传入 price/change_pct）→ 头部状态条（现价 + 涨跌幅红绿）；
     - **资金流**：后端新增 `GET /market/fund-flow/{symbol}` 端点包装 `get_fund_flow`（`market_data_hub.py:1615`），前端 `marketApi.fundFlow(symbol)` 封装 → 资金流区块（主力净流入/流出，东财字段）——**契约先行**（`api-contracts/market/fund-flow.md`）；
  3. 测试：`SectorHeatMap.spec.js` 断言切 tab 保留旧列表（fetch 前不清空）；`TechnicalAnalysisModal.spec.js` 断言 K线/涨跌幅/资金流区块渲染（mock 三 API）；后端 `test_fund_flow_endpoint.py`（mock `get_fund_flow`）。
- **O29 AI 投顾输入框市场切换复原（P29 修复，前端一行）**：`AiAdvisor.vue:63-68` 的 `watch(marketTab)` 回调补 `query.value = ''`（R5 注释「输入不应残留」的完整落地）；测试：`AiAdvisor.spec.js` 断言 `marketTab` 变化后输入框值为空、旧回答/错误清空、流停止。
- **O30 搜索补全扩展板块/指数 + 布局抖动治理（P30 修复）**：
  1. **后端 `/search` 增加板块/指数段**（P30①）：新增 `kind` 参数（`symbol`/`sector`/`index`/`all`，默认 `all`）——
     - `sector`：`sectors` 表 `name ilike %kw%`（991 行），返回 `{symbol: BK码, name, type:'sector'}`；
     - `index`：`indices_meta` 表 `name/pinyin/first_letter ilike`（588 行），返回 `{symbol: sh000001, name, type:'index'}`；
     - 保持现有 stock/etf 段不变（向后兼容，`kind` 缺省 `all` 时仅追加 sector/index 尾部）；**契约先行**（`api-contracts/market/search.md` 更新）；
  2. **前端三模式下拉**（P30①）：`useMarketSearch` 支持 `kind` 参数透传；`UnifiedAnalysis.vue:36` 的 `v-if` 从 `activeMode==='symbol'` 扩展为三模式（sector/index 模式复用下拉 + 键盘导航 + Enter 选中）；
  3. **布局抖动治理**（P30②，O10 落地点）：`SectorHeatMap.vue` skeleton 行数对齐各 tab 数据量（hot 15 / heat 20 / stock 50）或给 `.card-body` 固定 `min-height`（≈加载后高度，240px→840px 级差消除）；`MarketReport`/`AiAdvisor` 补同类骨架占位（防二次撑高）；
  4. 测试：后端 `test_search_sector_index.py`（mock sectors/indices_meta 表，断言 type 标注与 keyword 匹配）；前端 `UnifiedAnalysis.spec.js` 断言 sector/index 模式下拉渲染 + Enter 选中；`SectorHeatMap.spec.js` 断言加载前后高度差 < 阈值（骨架对齐）。

> 实施优先级建议：P1/P2/P3（性能+个股搜索）→ P4（前端）→ P5/P6/P7（LLM/RSI/投顾质量）→ P8/P9/P10（因子/资讯/估值）。

---

## 8. 回收（步骤 15）

部署完成后执行：`docker compose down --remove-orphans --rmi local`（回收容器与本地镜像）、删除 `docker-compose.diag.yml` 临时 override、恢复 `docker-compose.yml`/`.env`（移除 PROFILE_WARMUP）、清理诊断脚本（`_diag_*.py`、`_*.json`、`_lh_report.json`、diag/probe_followups.py）。