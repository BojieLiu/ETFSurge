# Round8 复诊与性能诊断报告（Rediagnosis）

> 状态：**诊断完成，未开始实施**（本轮仅诊断 + 方案设计，待 review 至实施标准后另行实施）
> 范围：在 Docker 全新构建的 HEAD `3c7906d`（round7 O1-O30 优化项已实施）栈上，重新执行 15 步诊断，验证 round7 修复效果并定位新问题。
> 环境：docker compose（prod 态）+ `docker-compose.diag.yml` 临时 override（`PROFILE_WARMUP=1` + 诊断注入 entrypoint），Chrome headless Lighthouse 13.4.1。
> 日期：初稿 2026-08-05；2026-08-07 复诊增补（§5.1D-K、O10-O12/O15-O27、§6 第二波盲区）。

---

## 0. 执行摘要

本轮在含 round7 O 项修复的最新代码上重建并启动前后端，逐项执行 15 步诊断。核心结论：

- **round7 高优项实质改善**：预热 128s → 3.27s（P1 修复，etf_cache 走快照）；线程池饱和未复现（P2 缓解）；news-impact 空洞 → 完整分析（P16 修复）；资讯分级合理（P9 修复）；自选新条目带实时行情（P12 部分修复）。
- **但 R7-O3 引入新 P0-新 启动阻塞**：美股 instruments 同步段（`stock_us_spot_em`）在事件循环线程上裸同步调用 akshare，**该接口在当前环境永久卡死** → `asyncio.wait(timeout=60)` 超时回调无法触发、uvicorn 永不 bind 端口、后台循环全停摆。诊断注入绕过 US 段后服务才可启动；且绕过后 A股/港股/ETF 段仍累计同步阻塞约 120s（pyinstrument 证据）。
- **round7 多个中低优项仍复现/恶化**（注：本节为 2026-08-05 初诊口径，08-07 复诊修正为 no_data=6，见 O25）：个股名称搜索空（P3，`600519/00700/AAPL` 全空，instruments US=0 且 A股个股段空）；AI 投顾全缺失（P7，投顾快照注入空）；热股外盘空（P15）；562950 消费电子→食品饮料（P23）；因子模型恶化（P8，no_data 5→10、avg_ic +0.07 → -0.07）；设计"今日涨跌"从 None 转为虚假极端值（P22 转化，-42.6%）。
- **前端性能未改善**：Lighthouse performance 0.54（round7 0.55 持平），LCP 3.2s、CLS 0.393、TBT 690ms、unused JS 85KiB（全部来自 vendor-echarts 559KB 全量打包）。
- **数据断裂**：港股 K 线全链路失败（finnhub 403 → alphavantage 空 → get_k_data 空，`/history/00700` 返回 0 根）；hub 缓存断裂（`get_index_realtime()=0`/`get_sector_momentum()=0`/`_global_indices_cache` 空 dict → 投顾快照缺指数/板块，但 `/indices/global` 接口有数据——两套缓存未同步）。

总体判断：**round7 O 项修复使预热/线程池/资讯链路达标，但引入新启动阻塞（P0-新），且搜索/投顾/港股数据/因子表现/前端性能等硬伤未随 O 项收敛；测试防护体系（R7-O13 SKIP 豁免、无启动超时 gate、断言"有值"非"值域"）未能拦截。**

> **编号约定（重要，防跨文档混淆）**：
> - 本文问题编号 **P-新#**（§2 起，P0-新/P1-新/…）与方案编号 **O#**（§7，O1-O12、O15-O27；**O13/O14 未使用，编号保留缺口**）均为 **round8 独立序列**，与 `docs/round7-rediagnosis.md` 的 O1-O30 **同名但不同指**（例：本文 O15=消费电子分类，round7 的 O15=AI 工具落列表）。
> - 引用 **round7 文档**的问题/方案一律写 **`R7-P#` / `R7-O#`**（例：R7-O18=premium_discount nav 源加固、R7-P3=个股搜索）；未加 `R7-` 前缀的 P/O 编号均指本文。
> - §0/§1/**§5** 对照表内圆括号编号（P1/P2/P9/P16…）为 round7 问题编号（该几节以对照 round7 为主，保留裸编号以减少噪音）。

> **决策记录（2026-08-07 用户拍板，实施轮按此执行）**：
> | # | 决策点 | 拍板结果 |
> |---|--------|---------|
> | 1 | O1 instruments 同步改造方式 | **两者结合**：全改 `run_sync`/`to_thread`（线程池）+ 改独立后台任务 + 段级超时/环境开关（文档原推荐方案 A+B 全要） |
> | 2 | O21 IPv6 修复 | **方案一**：uvicorn 监听 `[::]:8000`（同时覆盖 IPv4） |
> | 3 | O9 concept_tags 契约 | **方案一**：后端平铺填充 `tag.concept_tag`（不改契约字段） |
> | 4 | O17 视觉治理 | **合并实施**：连同 `docs/interaction-redesign.md` + `docs/frontend-theme-redesign.md` 一起做 |
> | 5 | §5.1C 三方案专业审视"取向" | **落地**：压卫星 ≤20% + 精简 core 大盘叠加 + 防御抬至 15-20%，排入 O16 同批实施 |
> | 6 | Lighthouse performance ≥0.7 | **软目标**（不设 pre-commit 硬门禁；仅作为实施效果衡量） |
> | 7 | O25 premium_discount/tracking_error/shares_change | **接受"加降级链/换源"成本**（不再降级为 static，优先补齐数据源） |
> | 8 | O24 分析失败 | **方案 A**（已定稿）：失败分类 + 可重试，不改 provider；**根因已定性（2026-08-07 容器实测）＝主因 O22 前缀（sh688981→DATA_UNAVAILABLE 7s 失败）+ 次因 LLM 慢（56s 被 45s 超时误杀）**；超时分级复用 llm.py 限流参数；B 留作后续可选增强 |

---

## 1. 十五步结论对照表

| # | 步骤 | round7 | 本轮实测（HEAD 3c7906d） | 结论 |
|---|------|--------|--------------------------|------|
| 1 | 后端预热性能诊断 | 128.4s | 预热 3.27s（market_cache 3.10s/etf_cache 8ms 快照）——**口径**：warmup_sequence 按序执行（main.py:263-268，instruments 同步在末段 `_background_instruments_sync`），3.27s 为绕过 US 段后的指标，若启用 US 段则卡死（见 P0-新）；**P0-新的 US instruments 同步裸阻塞（R7-O3 引入，O1 覆盖）→ 绕过前 uvicorn 永不 bind（P0-新）**；绕过 A/港/ETF 段仍累计 ~120s | 🟡 预热修复，R7-O3 引入新阻塞 |
| 2 | 组合设计 + on_exchange 策略检查 | 质量达标/LLM 超时 | 设计 3 方案约束合规（权重和=1.0、核心必备 510300+560600、层预算），报告结构完整（风险/止损/再平衡齐全）；策略检查 coverage_pct=1.0；LLM 429→规则兜底（llm=0/rule=10） | 🟡 LLM 兜底仍常态 |
| 3 | A/港/美行情分析 | 综合研判优/投顾空/搜索 US-HK 空 | 三市场研判、个股/板块/概念/指数分析均专业级；**投顾仍"暂无实时指数"（R7-P7 复现）**；**港股个股 K 线与实时价脱钩（00700: 492.2 vs 9.49-17.6）** | 🟡 投顾/港股数据缺陷 |
| 4 | 热点板块/热股加载 | 外盘热股缺失 | 热点 15 条/热股 A 股 50 条加载正常；**HK/US 热股 0 条（R7-P15 复现）**；concept_tags 字段 50/50 空、heat change_pct 20/20 空 | 🟡 字段断裂 |
| 5 | 自选功能 | 正常（小缺口） | 增/查/改/删全通，新条目带 realtime；**但 3 缺口：新条目 name 未解析（=代码）、sh688981 realtime None（O22）、列表 N+1 慢查询 2.68s（O9）** | 🟡 功能通/字段缺口 |
| 6 | 持仓技术分析/信号 | 信号合理 | 10 ETF 信号全返回且与规则引擎 9/10 一致；指标（MA/RSI/KDJ/MACD）准确 | 🟢 正常 |
| 7 | 资讯分级与智能分析 | 分级不合理（复现） | headlines 2-5 星分级合理；llm-news-analysis 33 条新闻 → 情绪量化+Top3 板块+4 深度启示（专业级）；global 1 星 7 条待优化 | 🟢 修复 |
| 8 | 因子模型状态 | valid25/no_data5/avg_ic 0.07 | **valid19/no_data10/avg_ic -0.0747（08-05 初诊口径；复诊修正：valid23/no_data6/avg_ic +0.0262，见 O25）**；IC 21 条全有值但 12 负 9 正（mean -0.0672）；sample_count 全空 | 🔴 恶化（初诊口径） |
| 9 | 前后端数据断裂排查 | 弱断裂修复 | **港股 K 线全链路失败**；**hub 缓存断裂（投顾快照空）**；设计涨跌幅虚假极端值 | 🔴 新增断裂 |
| 10 | round7 问题清单核对 | — | 4 修复 / 7 复现 / 3 转化（口径：修复=P1/P6/P9/P16，复现=P3/P4/P5/P7/P15/P23/P25，转化=P2缓解/P8恶化/P22，部分=P12）（见 §5） | ⚠️ 见清单 |
| 11 | 前端 Lighthouse | 0.55 | **0.54（持平）**；LCP 3.2s/CLS 0.393/TBT 690ms/unused JS 85KiB | 🔴 未改善 |
| 12 | 后端全链路性能 | 线程池饱和/预热 128s | 预热 3.27s（R7-P2 未复现）；**设计 71.7s（pre-allocate 同步阻塞）**；watchlist 2.68s（N+1）；港股 history 2.2s+空 | 🟡 部分改善 |
| 13 | 测试防护盲区 | — | R7-O13 SKIP 豁免、无启动超时 gate、断言"有值"非"值域"（见 §6） | ⚠️ 见 §6 |
| 14 | 结论+方案文档 | — | 本文档（多轮 review） | — |
| 15 | 回收容器/配置 | — | 见 §8 | — |

---

## 2. 问题清单（按影响分级）

### 🔴 高优（性能 / 数据完整性硬伤）

- **P0-新 启动阻塞（R7-O3 引入的回归）**（注：以下为**当前网络环境**实测——`stock_us_spot_em` 探针 2 分钟无返回；在数据源可用环境下可能为慢而非卡死，但裸同步阻塞事件循环的风险不变）：`scripts/sync_instruments.py:41` 的 `_fetch_akshare_list` 对美股段 `stock_us_spot_em` 做**裸同步调用**（未走 `run_sync`/`asyncio.to_thread`），在当前网络环境下该接口**永久卡死**（独立探针 `ak.stock_us_spot_em()` 2 分钟无返回）→ 阻塞事件循环线程 → `main.py:463` 的 `asyncio.wait(_warmup_tasks, timeout=60)` 超时回调无法触发（事件循环被同步占用）→ uvicorn 永不完成 lifespan startup、端口永不 bind、后台循环（sector 60s/news 120s/regime 120s）全停摆。
  - pyinstrument 证据（绕过 US 段后）：A股 `stock_zh_a_spot_em` 72.4s、港股 `stock_hk_main_board_spot_em` 30.9s、ETF `fund_etf_spot_em` 17.2s——**4 段全部在事件循环线程上同步执行**（`collect_all()` 的 `asyncio.gather` 并发失效），累计拖慢启动约 120s。
  - 影响：**在当前网络环境下服务无法在 R7-O3 代码下完成启动**；诊断注入（跳过 US 段）才可运行。（数据源可用环境下可能为慢而非卡死，但裸同步阻塞事件循环的风险不变）
  - 根因：R7-O3 为修 R7-P3（US instruments 空）补了 US 段，但**未遵循项目的 `run_sync` 线程池规范**（AGENTS.md「async def ≠ 非阻塞」）；且 instruments 同步**无环境变量开关/超时保护**（`main.py:170` `_background_instruments_sync` 无条件调用 `sync_instruments_table()`）。
- **P1-新 港股 K 线全链路失败**：`/market/history/00700?asset_type=HK` 返回 **0 根**。日志链：finnhub `stock/candle 00700` → **403 Forbidden**（免费 token 失效）→ alphavantage `TIME_SERIES_DAILY` → 200 但空 → akshare `get_k_data` → 空。而 symbol-analysis 的 K 线（9.49-17.6）来自另一缓存/错误源，与实时价（492.2 港元）相差数十倍——**港股技术分析整体失真**（LLM 主动声明数据矛盾）。
- **P2-新 hub 缓存断裂（投顾快照空）**：`llm-advice` 输出"暂无实时指数数据/板块热力/资金流"（R7-P7 复现）。根因：`_build_advice_market_snapshot` 的 `hub.get_index_realtime()` 返回 0、回退 `market_service._global_indices_cache.get("A股")` 为空 list、`hub.get_sector_momentum()` 返回 0 → 快照仅 39 字符（只有市态+情绪）。**但 `/market/indices/global`（3345B）与 `/market/sectors/industry`（1204B）接口有数据**。真实根因（非 key 不匹配）：`market_service.py:492-505` 非交易时段 stale 分支会把各 region 值重建为**空 list 并写回缓存**（`stale[region] = []`）——快照读到的 `_global_indices_cache["A股"]` 已被清空；而 `/indices/global` 走 `hub.get_global_indices()` 的独立路径（含 `_global_indices_last_ok` 兜底）不受影响——**两套缓存写入/降级路径不同步**。
- **P3-新 前端 performance 未改善（0.54，R7-P4 持平）**：LCP 3.2s / CLS 0.393（严重）/ TBT 690ms / SpeedIndex 4.1s / unused JS 85KiB / mainthread 3.0s / bootup 1.2s。根因：① `vendor-echarts` 559KB **全量打包**（unused 85KiB 全部来自它）；② CLS 0.393 布局抖动（R7-P30② 骨架屏高度不匹配——skeleton 240px vs 实际 840px）；③ TBT 690ms 主线程长任务（vendor JS 解析执行）。

### 🟡 中优（质量 / 逻辑 / 数据字段）

- **P4-新 个股名称搜索空（R7-P3 复现/退化）**：`search?keyword=茅台` → 0 条（round7 尽力复测可命中，本轮 A 股个股段全空）、`00700` → 0（HK instruments 2613 条却搜不到）、`AAPL` → 0（**instruments US=0**，R7-O3 补的 US 同步未成功）。`510300`（ETF）/`科创50`/`恒生`（中文）可命中 → 搜索个股段（`_search_a_stocks`/`search_hk_us`）断裂，ETF/指数/板块段正常。
- **P5-新 设计报告"今日涨跌"虚假极端值（R7-P22 转化）**：round7 是 None（数据源不可用），本轮变成**荒谬数值**——510050 `-23.40%`、562870 证券ETF `-42.60%`、562990 碳中和 `-30.90%`、518880 黄金 `-10.70%`、511090 30年国债 `+13.90%`，全部超出 A 股 ETF ±10% 涨跌幅限制。报告照实展示并基于其展开分析 → **严重损害专业可信度**。且 562950 消费电子 → "食品饮料方向"（R7-P23 复现）。
- **P6-新 因子模型恶化（R7-P8 复现/恶化）**：`/factors/active` valid 19 / warn 1 / **no_data 10**（round7 为 no_data 5；**注：此为 08-05 初诊快照；08-07 复诊修正为 valid23 / no_data 6 / avg_ic +0.0262（见 O25），数字变化反映数据源可用性而非代码回归**）/ static 3 / **avg_ic -0.0747**（round7 +0.0718）；`/factors/ic` 21 条 IC 全有值但 **12 负 9 正**（mean -0.0672）——sma_60 -0.44、kdj.d -0.43、vol_ratio -0.43、vwap -0.42、MA 系列 -0.39 等技术类因子当前市态**信号反向失效**；仅综合信号 overall +0.62、布林带宽 +0.56、新闻热度 +0.32 有效。`sample_count` 全空（无样本量/显著性信息）。初诊 no_data 10（etf_specific 缺失）；复诊修正 6 项（etf 3 + sentiment 3，见 O25）。
- **P7-新 策略检查 LLM 仍兜底（R7-P25 复现，原因变化）**：本轮 LLM `429 Too Many Requests`（opencode 429 → DeepSeek 成功但策略检查路径仍超时）→ `covered_by_llm=0 / covered_by_rule=10`、summary 固定"LLM 分析超时"、无深度定性分析。规则引擎建议本身合理（factor+signal 驱动），但专业投资者会质疑"策略建议有多少来自真实分析"。
- **P8-新 设计任务耗时 71.7s（性能）**：pre-allocate 阶段（数据采集 30.5s + 预分配 41s）在事件循环线程上同步执行——与 P0-新 同源（instruments/factor 同步 akshare 阻塞），非线程池问题（R7-P2 线程池本轮空闲）。纳入 O1 覆盖范围（pre-allocate 数据采集段同源改造）。
- **P9-新 字段级数据断裂（多端点）**（含 watchlist 慢查询）：
  - `stock-hot-rank` 的 `concept_tags` 字段 50/50 全空（契约 F2-6 声明，实际标签在嵌套 `tag.concept_tag`）——**契约与实现不一致**；
  - `sectors-heat` 的 `change_pct` 20/20 全空（热度排行缺涨跌幅；**修复口径与 O19 协调**：数据源本身无该字段，验收改「非 null（可为 0）」，由 O19 兜底 0（唯一方案；换源仅作可选增强））；
  - `stock-hot-rank` 的 `sector` 字段空；
  - watchlist 新添条目 name 未解析（510050 name='510050'，Z22 契约要求 realtime 名兜底但 realtime name 空时未从 instruments 补名）；**带 sh/sz 前缀的 A 股股票条目（如 `sh688981` 中芯国际）realtime None（无论新添还是历史，见 O22）**；**watchlist 列表 2.68s（逐条查实时行情，N+1 查询，随条目线性变慢）**。

### 08-07 复诊新增问题索引（2026-08-07 第二轮诊断，详见 §5.1/§7）

> 以下问题在 08-07 复诊发现，未占用 §2 上方 P-新# 编号（避免与初诊问题清单混排）；实施轮清点问题请以本节索引 + §5.1/§7 为准，勿只按 §2 P-新 清点。

| 问题 | §5.1 小节 | O# | 一句话 |
|------|-----------|-----|--------|
| 设计任务 45s DATA 预算不足（冷缓存超时） | §3 详审 | O10 | 冷缓存首次设计 42-75s 被 45s 预算截断 |
| 前端任务状态机：失败无法二次触发/残留 | §7 O11 | O11 | 失败态无重试入口、持久化残留 |
| 历史列表 join tasks：失败任务隐形 | §7 O12 | O12 | timeline 不 join tasks → 失败任务不可见 |
| 消费电子误归食品饮料 | §5.1A | O15 | R7-P23 根因深化 |
| 平衡方案文案与分配矛盾 | §5.1B | O16 | rationale 宽基风格两套语义 |
| 前端字号小/未铺满 | §7 O17 | O17 | 14px / max-width 1200px |
| 报告今日涨跌 100 倍 bug | §7 O18 | O18 | ×100 单位 + 非实时源 |
| 板块热度卡片消失 | §5.1D | O19 | change_pct=null toFixed 崩溃 |
| 热点个股技术分析缺 K 线图 | §5.1E | O20 | 数据已拉未渲染 |
| 自动补全 2 秒延迟 | §5.1F | O21 | localhost IPv6 回退 |
| 自选 A 股股票实时为空 | §5.1G | O22 | sh/sz 前缀匹配失败 |
| 分析输入框只显示代码 | §5.1J | O23 | pickSearchItem 绕过 composable |
| 标的分析失败 | §5.1K | O24 | 前缀 symbol/LLM 慢（SSE 空） |
| 因子模型 6 项数据缺失 | §2 P6-新 + §6 | O25 | etf_specific/sentiment 缺口 |
| 板块技术分析点位口径 | §5.1H | O26 | 点位=板块指数未标注 |
| 基本面市值数据缺失 | §5.1I | O27 | _fetch_market_data 未注入 total_mv |

### 🟢 低优 / 已修复确认

- **✅ 已修复**：预热 3.27s（R7-P1）；线程池饱和未复现（R7-P2）；资讯分级合理（R7-P9，headlines 2-5 星）；news-impact 完整分析（R7-P16）；自选新条目 realtime（R7-P12 部分）；on_exchange 过滤生效（10/10 场内）；factor-summary 与指标一致（R7-P6 RSI 一致性：design factor_breakdown 未见 z-score 失真，RSI 47.47 vs 指标 48.45 基本一致）。
- **⚠️ 分级主观偏差（R7-P9 残余）**：港股科技集体大涨（阿里/腾讯/百度齐涨）仅 2 星偏低；美国移民政策新闻 4 星偏高——分级规则存在主观性。（**顺延**：暂未排 O 项，属分级规则阈值调优，非阻塞项）

---

## 3. 组合设计 & 策略检查（步骤 2）详审

**设计（design 415，capital 500k，balanced）**：
- ✅ 三套方案 defensive/balanced/aggressive（11/13/11 只），**约束全部合规**：总权重和=1.0（CASH 20.27%/15.05%/28.78%）、核心层必备 510300+560600、单只权重 1%-30% 无越界、层预算基本符合（防御 core 46.85%≤50%、平衡 core 44.24%≤45%、进攻 core 26.8%≤40%）。
- ✅ LLM 报告结构完整（17779 字符）：方案对比总览表、三种方案详解（逐标的表：权重/因子评分/RSI/MACD/今日涨跌/建仓建议/入选理由）、市场环境与配置建议（指数/板块/市态/情绪）、风险提示（9 处"风险"）、量化操作纪律（止损 1、再平衡 1、回撤 7、仓位 8）。
- ❌ **今日涨跌虚假极端值**（-42.6%/-23.4%/-10.7%/+13.9%，见 P5-新）——报告照实展示并基于其分析，专业可信度受损。
- ❌ **行业归属错乱**：562950 消费电子ETF → "食品饮料方向"（R7-P23 复现）；562000 A100ETF 核心层但理由写"卫星仓位"。
- ⚠️ 风格匹配：进攻型核心层 27%（预算 40%）+ 现金 29%，在震荡偏乐观（range_bound + 情绪 63.6）市态下略保守，但"分批建仓留缓冲"逻辑自洽。

**策略检查（task 233，on_exchange，10 只场内持仓）**：
- ✅ `on_exchange` 过滤生效：10 条建议全为场内 ETF；`coverage_pct=1.0`（rule 10/10）、`data_confidence=high`、`factor_availability` 23-24/34。
- ✅ 规则引擎建议逻辑自洽：159338 A500（因子1.40 hold）、510880 红利（因子2.41 buy 8→9.6%）、518880 黄金（因子5.36 buy 13→15.6%）、创新药技术面 sell 但因子正→hold（背离处理合理）。
- ❌ `covered_by_llm=0`（LLM 429）→ 无深度定性分析；`industry` 字段全空 + 行业集中度 risk_warning（63% 权重行业数据缺失）。

**专业投资者视角**：方案框架专业（三层结构、风格分层、风险纪律）、约束合规、报告可读性强——**框架可接受**；但"今日 -42.6%"这类财务数据会直接打回质疑数据管道可信度，"消费电子=食品饮料"进一步削弱行业分析信任。

**本地现场复现（2026-08-07，冷/热缓存对比）**：
- 连续触发两次设计（`POST /portfolio/design-async`），轮询 task 状态计时。**首次（冷缓存）DATA 阶段实测 42-75s**：progress=10「数据采集与策略计算中」卡到 42s 仍前进；期间 50s 处 `/portfolio/tasks/{id}` 查询出现 `TimeoutError`（事件循环被 DATA 内同步 IO 短暂占用）——已逼近 design_pipeline 的 **45s DATA 预算**（`task_manager.py:291`，OPT-06）。
- 冷缓存差异：随后 task 237（热缓存，`_kline_cache`/`_cached_pool` 已建）DATA 阶段仅 ~10s 即过，总 ~28s 成功，report_quality=full。
- **根因（新发现，非 O1 的 instruments 阻塞）**：`generate_enhanced_design` 首次调用触发 `market_data_hub.refresh()` 全市场扫描 + 全量建 K 线缓存（Semaphore(5) 逐只 20s 上限），本地数据源慢（实测：新浪 1.4s / 东财 push2 6.5s / akshare fund_etf_spot 21.4s），使首次 DATA 逼近/突破 45s 预算 → `asyncio.TimeoutError` → `task_manager.py:527` 报"方案生成超时，数据源响应过慢，请稍后重试"（用户本地实际操作报错即此路径）。**间歇性**：冷缓存/数据源慢时必现，热缓存/源快时成功。

***

## 4. 多市场行情分析（步骤 3）详审

| 链路 | 结果 | 专业审阅 |
|------|------|---------|
| A 股综合研判 | ✅ 指数 10 项全（科创50 +4.78% 领涨、上证 3878.43 +1.47%、沪深300 4658.15） | 优秀 |
| 港股研判 | ✅ 恒指 25915.82 +0.24%、恒科 4933.07 +0.97%、情绪 44.1 中性偏谨慎 | 优秀 |
| 美股研判 | ✅ 标普 7736.52 +1.79%、纳指 26584.99 +2.59%、VIX 15.86 低位 | 优秀 |
| A 股投顾 | ❌ "暂无实时指数/板块/资金流/新闻"（P2-新 hub 缓存断裂，R7-P7 复现） | 不可用 |
| 个股 600519 | ✅ PE 36.48/PB 9.67、MA 系统、MACD 红柱收缩、KDJ 超买死叉、量价、行业资金流、风险提示 | 专业级 |
| ETF 510300 | ✅ 规模 995 亿、单日净流入 93 亿、资金迁移逻辑 | 专业级 |
| 港股个股 00700 | ⚠️ 回购信息详实，但 **K 线 9.49-17.6 vs 实时 492.2 脱钩**（LLM 主动声明），技术指标失真 | 数据断裂 |
| 板块 BK1036 | ✅ 半导体 2610.97 +5.72%、主力净流入 129.64 亿、5 只核心标的 | 专业级 |
| 概念 BK1152 | ✅ HBM 2441.77 +7.77%、28涨0跌、资金面/技术面/催化/风险 | 专业级 |
| 指数 000001 | ✅ PE 10.21/PB 1.16、均线/MACD/KDJ/布林、操作建议表格、仓位管理 | 专业级 |
| 搜索补全 | ✅ 中文关键词/代码前缀/kind=index 均正常；❌ 个股维度空（P4-新） | 部分 |

**结论**：研判/个股/板块/概念/指数分析质量整体专业级（数据翔实、逻辑链完整、风险提示充分）；**投顾（数据缺失）与港股个股（K 线失真）是硬伤**；AI 端点均为 `/stream` 流式（非流式路由 404，前端用 stream 契约一致，仅文档滞后）。

---

## 5. round7 问题清单核对（步骤 10）

| round7 | 问题 | 本轮状态 | 证据 |
|--------|------|---------|------|
| P1 | 预热 128s | ✅ 修复（3.27s） | warmup_timing.json |
| P2 | 线程池饱和 | ✅ 缓解（空闲） | executor stats 0/64 |
| P3 | 个股名称搜索空 | ❌ 复现/退化（茅台/00700/AAPL 空） | search 实测 + instruments US=0 |
| P4 | 前端 0.55 | ❌ 复现/未改善（0.54） | Lighthouse |
| P5 | 策略检查 LLM 超时 | ⚠️ 复现（429 限流→兜底） | task 233 |
| P6 | RSI 失真 | ✅ 修复（指标一致） | design factor_breakdown vs indicators |
| P7 | AI 投顾全缺失 | ❌ 复现（快照空） | llm-advice 实测 |
| P8 | 因子 no_data/IC | ⚠️ 恶化（初诊 no_data 5→10；复诊修正 valid23/no_data6/avg_ic +0.0262，见 O25；avg_ic 初诊转负） | /factors/active+ic |
| P9 | 资讯分级 | ✅ 修复（headlines 2-5 星） | news 实测 |
| P12 | 自选 realtime | ✅ 部分修复（新条目有 realtime；name 未解析） | watchlist 实测 |
| P15 | 热股外盘空 | ❌ 复现（HK/US 0 条） | stock-hot-rank 实测 |
| P16 | news-impact 空洞 | ✅ 修复（完整分析） | news-impact 实测 |
| P22 | 设计今日涨跌 None | ⚠️ 转化（虚假极端值 -42.6%） | design 415 |
| P23 | 消费电子→食品饮料 | ❌ 复现（根因深化，见 §5.1A O15） | design 415/416-418 |
| P25 | 策略检查数据缺失 | ⚠️ 复现（规则兜底常态） | task 233 |

---

## 5.1 本轮新发现（本地实测）

### §5.1A R7-P23 根因深化——562950 消费电子被误判「食品饮料」（O15）

**现象**：方案 `strategies_json` 中 `562950 消费电子ETF易方达` 的 `tracked_index="消费"`、`industry="食品饮料"`。

**两条根因叠加**（磁盘代码已实测：
1. **数据源头截断**（`etf_scanner.py:172` + `_extract_index_keyword:177`）：`INDEX_KEYWORDS["消费"]="消费"`（无"消费电子"），`name="消费电子ETF易方达"` 含"消费"→ tracked_index 回填为 **"消费"**（丢"电子"）。`etf_scanner.py:838` 用 `tracked_index or _extract_index_keyword(name)`，f168 为空时即触发。
2. **分类逻辑漏洞**（`etf_classifier.py:181-189`）：`_classify_by_name(tracked_index, name)` **tracked_index 优先**，命中 `("消费","食品饮料")` 后**直接返回，不再看 name 的"消费电子"**。**R7-O23 已修 `_NAME_RULES["消费电子"]` 但这场景走不到 name**。

**修复方向（归入 O15，见 §7）**：① `INDEX_KEYWORDS` 加 `"消费电子"` 且 `_extract_index_keyword` 改**最长匹配优先**；② `_INDEX_RULES` 加 `("消费电子","电子")`，或 tracked_index 命中时若 name 含更精确方向（"电子"）优先采用 name；③ 补 562950 单测。

### §5.1B 平衡方案文案与分配自相矛盾（O16）

**现象**（balance 方案，plan[1]）：
- `510500 中证500ETF南方`（core，16.98%）文案末尾「**核心层配置，大盘价值代表性**」——中证500 是**中盘**宽基，被说成"大盘价值"错误。
- `562000 A100ETF华宝`（core，16.94%）文案末尾「**A100ETF华宝卫星仓位，高弹性品种**」——与 `layer=core` **直接矛盾**；A100 为大盘宽基，非"高弹性"。

**分配本身合理**（两标的均 core、17%、宽基中盘+大盘互补，无风控违规）；**问题在文案生成** `engine/rationale.py`：
- `_style_probe`（rationale.py:52-71）宽基关键词**漏了 "A100"**（只含"中证A"/"A50"，`rationale.py:69`）→ `562000` 被误判为 `theme_satellite` → 从 `_THEME_SATELLITE_PHRASES` 抽到"卫星仓位，高弹性品种"。
- 中证500 被归为 `low_vol_wide`（`rationale.py:68` 含"中证500"）→ 从 `_CORE_PHRASES` 抽到"核心层配置，大盘价值代表性"（rationale.py:16，本为大盘价值模板）。
- **根本缺陷**：`build_rationale` 的宽基判定（148-159，`_WIDE_BASIS_HINTS` 含 A100）与 `_style_probe` 的判定（52-71，不含 A100）**两套宽基语义不一致**；短语池把"压舱石低波"（中性）与"价值代表/高弹性"（风格限定）**混在一个池里按 symbol hash 随机抽**，易命中不符风格的句子。

**修复方向（归入 O16，见 §7）**：统一两处宽基关键词清单（把 A100/A500 等并入 `_style_probe`）；短语池按**标的真实风格**（meta.tracked_index 中的市值/风格提示）而非仅 symbol hash 选句；给 core 宽基明确"中盘/大盘"中性描述，杜绝"价值代表/高弹性"套在宽基上。

### §5.1C 三方案专业审视——市态匹配度 / 风险预算 / 核心重叠（design #418，balanced）

**市场背景（market_snapshot）**：市态 `range_bound`（震荡）、情绪 `谨慎`（sentiment 34.2，advance_ratio **0.14**，市场广度极差）；指数上证 +0.32%、深成指 +1.15%、创业板 +1.79%、沪深300 +0.8%、科创50 强；美股闭市走弱（标普 -0.18%、纳指 -0.06%、道指 -0.85%）。**涨跌比 0.14 → 权重拉指数但个股普跌，弱分歧/缩量分化市**，专业上应显著降低风险偏好、收卫星、抬现金与防御。

**三方案资产结构**：

| 方案 | core | satellite | defense | cash |
|------|------|-----------|---------|------|
| ① 防御型 | 47.0% | 21.6% | 11.8% | 20.3% |
| ② 平衡型 | 44.3% | **30.4%** | 10.3% | 15.0% |
| ③ 进攻型 | 26.7% | **33.8%** | 10.7% | **28.8%** |

**认可点**：防御层黄金+30年国债双配、红利低波纳入（符合震荡避险需要）；核心以大盘宽基为主的抗跌取向；三档卫星仓位递增（①→②→③）方向正确；中证500/A100 补中盘仍具分散价值。

**专业审视发现的问题（仅供参考）**：
1. **③ 进攻型名实矛盾——最大现金 28.8% + 最高卫星 33.8%**：进攻型本应低现金+高权益，现金却三档中最大，与"进攻"语义冲突。设计上应明确定「震荡市降权/收卫星」或「释出现金做真进攻」。
2. **震荡+涨跌比 0.14 下卫星系统性偏高**：②30.4%、③33.8% 全为科创/创新药/AI/消费电子/医疗器械等高 Beta 成长方向；弱分歧市逆风且拥挤，应把卫星压到 ≤20%（风险预算与市态不符）。
3. **防御层偏薄且核心高相关重叠**：防御仅 ~10-11%（②③），安全缓冲不足；方案① core 里 510300+560600+510050+563020 四个大盘宽基高相关叠加 ~47%，风格分散不足（应"1-2 大盘宽基 + 中盘 + 红利对冲"而非四只同向巨头）。
4. **单标股份偏集中**：方案①上证50（510050）权重 **20.06%** + 与沪深300/A500 高度相关叠加，接近单风格集中上限。

**结论**：① 防御型契合当前震荡市特性、但核心重叠与防御层偏薄削弱抗跌性；② 平衡型较合理但 satellite 30% 处于上限、defense 10% 偏薄；③ 进攻型当前氛围下名实最不匹配（最大现金却最高成长卫星）。**取向（已拍板：与 O16 同批实施）**：统一压低卫星至 ≤20% + 精简 core 大盘叠加（选 2-3 只真正分散的宽基）+ 防御抬至 15-20%。

### §5.1D 热点板块排行「板块热度」卡片消失（O19）
- **现象**：A 股行情下点击「板块热度」tab，卡片消失（`SectorHeatMap.vue`，`activeTab='heat'`）。
- **根因（实测 20 条数据 + 代码）**：
  1. **数据 `change_pct` 恒为 null**：`/market/sectors/heat`（market.py:633 `"change_pct": r.get("change_pct")`）直接从 `get_sector_heat`（market_data_hub.py:1320）透传；A 股走 `sector_fetcher.fetch_sector_heat` **财联社板块热度本身不含涨跌幅** → 20 条全部 `change_pct=null`。
  2. **前端 `toFixed` 崩溃**：`SectorHeatMap.vue:63-67` `v-if="item.change_pct !== undefined"` 只挡 `undefined` 不挡 `null`；`item.change_pct.toFixed(2)` 对 `null` 抛 **TypeError** → 该 data-row 渲染中断 → 卡片消失。
- **为何 R7-O28 没修**：R7-O28 只解决「加载中（dataList=[]）用骨架占位」的**异步空态闪烁**；本条是「**有数据但字段为 null**」的渲染期崩溃，两条触发路径不同、表象同为"卡片消失"，R7-O28 覆盖不到。
- **修复方向（仅设计）**：前端 `SectorHeatMap.vue:63` `v-if` 改 `item.change_pct != null`（同时挡 null/undefined）；后端 `market.py:633` 把 null 兜底为 0（唯一方案，与 §7 O19 一致，不采用剔除列）。补 `SectorHeatMap.spec.js` 用例「change_pct=null 时不报错、卡片正常渲染」。
- **验收**：① A 股「板块热度」20 行正常渲染（无空白/不消失）；② 无控制台 TypeError；③ 新增前端单测通过。

### §5.1E 热点个股技术分析缺 K 线图（O20）
- **现状（实测代码）**：`TechnicalAnalysisModal.vue`（热点/自选个股点「分析」弹出的技术分析）`load()` 已并行拉取 K 线 chart 数据（`marketApi.chart`，line 167）+ 资金流（line 168），但**仅用 closes 算今日涨跌**（`computeChangePct`），**从未用 echarts 渲染 K 线图**——弹窗只显示 RSI/MACD/KDJ/MA/BOLL 指标卡 + 综合信号 + 今日涨跌 + 主力净流入文本。即注释 O28② 自承「旧弹窗仅指指标卡片，无 K 线涨跌、无资金流」——数据管道已通，仅缺 candlestick 渲染。
- **可复用**：`AnalysisView.vue:157-275` 已实现完整 K 线 echarts option（candlestick + vol + MA + dataZoom，register 用 `CandlestickChart/BarChart/LineChart/DataZoomComponent`，line 44-56）；`ChartPanel.vue` 是纯展示 wrapper。
- **期望（用户）**：技术分析展示 K 线图，并与今日涨跌幅、资金流入流出并列。
- **修复方向（仅设计）**：① 在 `TechnicalAnalysisModal.vue` 复用 AnalysisView 的 K 线 option 构建（抽公共 `useKlineOption` composable）接入 candlestick；② 弹窗高度/布局适配 K 线（可能需放大 modal width >420px）；③ 资金流用柱状叠加或并列区。
- **验收**：① 热点个股技术分析弹窗出现 K 线图（含均线、量能、缩放）；② 图示与今日涨跌/资金流一致；③ `npm run build` 通过 + 前端单测覆盖。

### §5.1F 行情/自动补全「2~3 秒」延迟——根因是 localhost 走 IPv6 慢路径（O21）
- **现象**：添加自选标的的自动补全（`/market/search`）要 2~3s 才出选项；进一步发现**整个 `/market/*` 乃至纯静态接口全部固定 ~2.05s**。
- **关键实测（probe）**：
  - `openapi.json`、`system/warmup`、`admin/thread-pool` 等**不碰业务/数据源**的接口也恒 ~2.05s → 排除搜索逻辑与行情。
  - `127.0.0.1:8000` TCP connect=**0.027s**（瞬时）；`localhost:8000` connect=**2.061s**。
  - `socket.getaddrinfo('localhost')` → 返回 `[('::1',8000), ('127.0.0.1',8000)]`（**IPv6 优先**）。
- **根因**：uvicorn 监听 `0.0.0.0`（**IPv4 only**），而 `localhost` 解析把 `::1`（IPv6）排在前；每次连接先试 `::1` → 无人监听 → **失败约 2s 才回退 127.0.0.1**。前端若直接以 `localhost` 连后端（或 WS/用户手输），每次请求白白背负 ~2s。这是**环境/部署层**问题，才是「自动补全慢」的真因。
- **为何看似"搜索慢"**：前端 vite 代理本身用 `127.0.0.1`（快），但用户浏览器若直连后端 `localhost:8000`（CORS 直连 / 非 vite proxy / prod nginx 反代到 localhost:8000）即命中慢路径；300ms debounce 只是叠加。
- **修复方向（仅设计）【已拍板：方案一】**：① uvicorn 监听 `[::]:8000`（绑定同时含 IPv4，`0.0.0.0` 是 v4-only）——**首选**；② 统一所有直连/WS/反向代理目标为 `127.0.0.1`；③ 系统防火墙让 `::1` 立即拒绝而非超时 2s。
- **验收**：`localhost:8000` 任一接口 connect <0.1s；自动补全接口耗时 <0.1s（与 §7 O21/§9 口径一致）；无 2s 恒定延迟。

### §5.1G 自选里 A 股股票后几列为空——`get_asset_realtime` 前缀不匹配（O22）
- **现象**：添加「中芯国际」后，自选条目名称正常但价格/涨跌/成交量为空（`realtime=null`）。
- **关键实测**：
  - watchlist 接口返回：`A sh688981 中芯国际 -> realtime=None`；其余条目（600519/510300/AAPL/00700…）realtime 全正常。
  - `instruments` 表 A 股**股票** symbol 带前缀（`sh688981`/`sz000001`/`sz300750`），A 股 **ETF** symbol 纯数字（`510300`/`159300`）。
  - `/market/search?keyword=688981` 返回 `('A','sh688981','中芯国际')`（带前缀）→ 前端 `selectSuggestion` 原样入库。
  - 直接调 `fetch_a_stock_realtime('sh688981')` 与 `('688981')` **均返回** `[{'symbol':'688981', price:126.01}]`（**08-05 初诊·宿主机环境**：底层能取到数据但**返回 symbol 恒为纯数字 `688981`**）。
- **根因**：`get_asset_realtime` 的 A 股路径用 `if item["symbol"] == symbol` 精确比对（market_service.py:1141）。**且复诊（08-07 容器环境，实施依据）实测 fetch 层对带前缀输入取不到数据**：`fetch_a_stock_realtime('sh688981')` → 空，`('688981')` → `[('688981',128.5)]`——带 `sh/sz` 前缀的 symbol 在底层源（tencent/sina/mootdx）取数阶段就失败（两次环境差异：宿主机源能剥前缀、容器内源对带前缀直接失败；**以容器/生产环境为准**）。属**入库 symbol 形态（带前缀）与实时取数（纯数字）口径不一致**（A 股股票带 sh/sz 前缀 vs ETF 纯数字）。
- **修复方向（仅设计，归 O22，2026-08-07 修正）**：① **根本修法**——`fetch_a_stock_realtime` 入口剥 `sh/sz/bj` 前缀再取数（底层源拿到纯数字）；② `get_asset_realtime` 比对层同步剥前缀（双保险）；③ search A 股股票规约纯数字 symbol 返回；④ `add_watchlist`/`selectSuggestion` 入库时规约前缀。四项落地后，既有 `sh688981` 自选也立即恢复实时（无需删除重加）。
- **验收**：① 自选 `sh688981` 后三列有值且与 `/realtime` 一致；② 新添加任意 A 股股票（如宁德时代 sz300750）自选实时正常；③ 无 realtime=null 的 A 股股票条目。

### §5.1H 板块技术分析「点位」口径——当前是板块指数点位，非成分股（O26）
- **用户疑问**：BK1326（半导体设备）板块分析报告里"指数报 50118.43 点、上涨 2.00%""支撑 48000/46000"——这些点位是**什么标的**的点位？是**板块指数本身**。
- **确认**：板块分析的行情数据来自板块指数（东财 `push2delay` 板块行情，BK 代码对应板块指数点位与涨跌幅），不是成分股均价，也不是沪深大盘指数。报告"显著跑赢大盘（沪指+0.49%）"是板块指数 vs 上证指数对比。
- **实测（2026-08-07 容器内 sector-analysis/stream BK1326）**：报告首段"半导体设备板块今日表现强势，板块指数报收 50118.43 点"——**点位数字在，但全文无"板块指数点位"显式标签**（`板块指数`/`点位` 关键词均缺失）→ **O26 未修复**，缺显式口径标注。
- **问题**：① 报告未明确标注"点位 = 板块指数点位（BK1326）"，专业读者易误读为成分股或某指数；② 技术面"支撑 48000/46000"为板块指数历史区间推算，未注明周期（5/10 日均线在哪段 K 线计算）。
- **修复方向（仅设计，归 O26）**：① 报告模板首段标注"板块指数点位（BK1326，来源东财板块行情）"（prompt analysis.py:776 仅有技术面提示，首段/资金面需补）；② 技术面注明均线周期与数据区间；③ 若用户期望"成分股加权/等权点位"，需另接板块成分行情聚合（新数据管道）。
- **验收**：板块报告首段明确"本报告点位为板块指数（BKxxxx）点位"；技术面标注均线周期。

### §5.1I 基本面数据缺失——style/valuation 因子依赖的市值与基本面字段无数据源注入（O27）
- **用户疑问**：因子模型/个股分析中基本面数据（市值、估值）缺失。
- **确认**：`_fetch_market_data` 只注入 K 线（close/high/low/volume/change_pct）+ `fund_shares`（Z04 仅 fund_scale/fund_shares/industry/concepts）+ IOPV nav + sentiment 字段。**`total_mv` / `float_mv`（→ style.size.ln_mcap / ln_float_mcap）与 PE/PB（→ valuation 类）没有在 `_fetch_market_data` 中注入**——它们只在 `refresh_pool` 路径（`_build_symbol_extra` 之外的 refresh 全量路径）才可能有。`compute()` 直接调用时 `data[sym]` 无 total_mv → `_compute_ln_mcap` 返回 0 → 截面全 0 → IC 过滤或 no_data。
- **DB 佐证**：`style.size.ln_mcap`/`ln_float_mcap` 有 IC（-0.2256，样本 284）——说明 **refresh_pool 路径有数据**（部分 ETF 有 total_mv），但**compute 直调路径（如单标的分析）缺** → 同一因子不同路径数据不一致。
- **修复方向（仅设计，归 O27）**：① `_fetch_market_data` 补注入 total_mv/float_mv（复用 refresh_pool 的市值字段或加 akshare 单标的市值接口）；② 统一 compute 与 refresh_pool 的 symbol_extra 注入口径；③ 单标的分析缺基本面时显式标注"数据源未注入"而非静默 0。
- **验收**：① compute 直调路径 ln_mcap/ln_float_mcap 与 refresh 路径数值一致；② 无"全 0 截面"的 style 因子；③ 单测断言 compute 直调含 total_mv 注入。

### §5.1J 标的分析输入框只显示代码，不显示名称（O23）
- **现象（用户反馈，2026-08-07）**：综合/标的分析页顶部输入框，下拉选中标的（如中芯国际 `sh688981`、上证50ETF `510050`）后，输入框只显示代码，不显示标的名称；用户期望显示「代码 + 名称」。
- **根因（代码定位）**：`UnifiedAnalysis.vue:305-314` 的 `pickSearchItem(item)` 直接 `activeSearch.value.searchQuery.value = item.symbol`（只写 symbol），**未复用 `useMarketSearch.js` 的 `selectSearchItem`（`名称 (代码)`，`useMarketSearch.js:132-138`）或 `acceptCompletion`（`代码 名称`，`:47-54`）**——组件层绕过了 composable 已有的"代码+名称"回显逻辑；搜索框模板 `:value="activeSearch.searchQuery.value"`（`:26`）只绑定 searchQuery。
- **证据**：`UnifiedAnalysis.spec.js:158-166` 断言 `searchQuery.value` 为 `'510050'` 纯代码（**断言固化的正是 bug 行为**）；`useMarketSearch.spec.js:47-59` 的"代码+名称"测试因组件绕过 composable 而**与组件行为断层**。
- **修复方向（仅设计，归 O23）**：`pickSearchItem` 改为复用 `selectSearchItem`（或按 `acceptCompletion` 的 `代码 名称` 格式写回 `searchQuery`），并在 doAnalyze 时对「代码+名称」混合串正确解析 symbol（现有 `doAnalyze` 的 `looksLikeCode` 正则 `^[0-9A-Za-z.]+$` 对含空格/中文的混合串会解析失败，需同步处理——`F7 R19` 名称→代码解析路径已覆盖中文名，但"代码 名称"混合串需先截取首个 token）。
- **验收**：① 下拉选中后输入框显示「代码 名称」或「名称 (代码)」；② doAnalyze 对混合串能正确取到 symbol 并分析成功；③ `UnifiedAnalysis.spec.js` 更新为断言"代码+名称"回显（替换固化 bug 的旧断言）。

### §5.1K 标的分析"分析失败"——AI 未返回内容/数据源异常（O24，方案 A 已拍板，根因已定性）
- **现象（用户反馈，2026-08-07）**：标的分析出现"分析失败"。
- **根因（2026-08-07 容器内正确路径复测，替代旧推断）**：`/api/v1/analysis/symbol-analysis/stream` 三变体实测：
  - `sh688981` + name 空 → **7.0s 失败 `DATA_UNAVAILABLE 数据源暂不可用`**（**主因 = O22 前缀问题**：带前缀致后端取数失败，直接抛结构化错误码）；
  - `688981` + name 空 → 24s 成功（33051 chars）；`688981` + name='中芯国际' → **56s 成功（47346 chars，慢但成功）**（**次因 = LLM 慢**：56s > 45s 硬超时会被误杀）；
  - `name=''` 不影响成功（排除此前假设）；前端 `useLLMStream.js:74-75` SSE error 抛 `parsed.message` → 能透传 DATA_UNAVAILABLE 原文但无分类。
- **修复方向（仅设计，归 O24，方案 A 已拍板）**：① SSE 空内容时区分"LLM 不可用（429/超时）"与"上下文缺失/数据源不可用"两类文案（复用 `llm.py` `_last_llm_error` 分级）；② 失败可重试（配合 O11 状态机 `canRetry`）；③ 名称解析覆盖「代码+名称」混合串（O23 联动）；④ **后端 symbol 前缀归一化（O22 联动，主因修复）**；⑤ 超时从 45s 分级（对齐 R7-O5 的 LLM 90s，避免误杀 56s 慢请求）+ 给 symbol-analysis 传 `max_retries`/`cap` 复用限流参数。
- **验收**：① 分析失败时给出可操作的错误分类与重试入口；② 纯代码输入分析成功且报告含正确名称；③ `sh688981` 分析不再因前缀失败（O22 联动验证）；④ 前端单测覆盖"SSE 空→失败态 + 重试"；⑤ 429 场景显示"请求过于频繁"分类文案。

---

## 6. 测试防护盲区（步骤 13）

为何测试体系未能识别上述问题：

1. **R7-O13 名称搜索 SKIP 豁免**（`verify_e2e.py:284`）：`茅台/腾讯/apple` 名称搜索返回 0 条时 `skip=True`（理由"数据源冷却/未同步——O13 语义告警，非代码缺陷"）→ P4-新 个股搜索空**持续绿灯**。
2. **启动无超时上限**：`section_health` 只查端口可访问 → R7-O3 US instruments 阻塞启动（120s+/卡死）只要最终能起（或绕过）即 PASS；`test_async_boundaries`/`test_async_lint` 只扫 `app/` 包，**未覆盖 `scripts/sync_instruments.py` 的裸同步 akshare**。
3. **断言"有值"非"值域合理"**：设计报告 -42.6% 涨跌幅 PASS——注意 `test_design_daily_change_fallback` 的**兜底函数单测本身含值域断言**（`0.0 < abs(dcp) < 0.1`），但设计报告**注入管道未被端到端覆盖**（注入点未生效，-42.6% 仍透传）——这正好解释了为何测试通过而 P5 仍在；`concept_tags` 空 PASS。
4. **单测 mock 假设缓存有数据**：`test_advice_index_fallback` 等 mock 了 `hub.get_index_realtime()` 返回数据 → "hub 缓存空（stale 分支清空）+ 回退缓存未命中"的真实断裂不被测。
5. **前端无性能预算门禁**：pre-commit 只跑 `npm run build`（编译检查），无 Lighthouse/CLS/TBT 阈值 → performance 0.54 / CLS 0.393 不受控。
6. **外部数据源真实失败不覆盖**：finnhub 403、alphavantage 空只在真实环境暴露（单测全 mock）。
7. **N+1/慢端点无门禁**：watchlist 2.68s 响应时间 gate 宽松。

> 注：verify_e2e 另有 S3 门禁（`verify_e2e.py:1733`，SKIP 数 >3 整体判 FAIL）——R7-O13 名称搜索的 SKIP 豁免受总量约束，但单轮 3 条名称搜索（A/HK/US 各 1）SKIP 不触发 S3，P4-新 仍可持续绿灯。

### 第二波盲区（O15–O27 批次，2026-08-07 复诊新增）——五条系统性模式

前 7 条盲区聚焦"数据源不可用/启动阻塞/值域"，但 O15–O27 暴露的是**测试与实现"同构"**的更深层问题——mock 永远喂完美数据、断言永远验"存在"不验"正确"。逐条归因：

1. **mock 数据永远是"完美形态"，从不喂畸形输入**
   - O22（sh688981 前缀）：`test_asset_type_parametrized.py:30-32` mock 的返回 symbol 与请求**逐字相同**（`_fake` 直接 `return [{"symbol": fetch_symbol}]`），测试符号 `600519`/`00700` 无前缀 → 永不触发"带 sh/sz 前缀输入"分支 → 严格等值匹配 bug（`market_service.py:1141`）永不暴露。
   - O27（total_mv 缺失）：`test_factor_registry.py:160-169` 把 `_fetch_market_data` 整体 `AsyncMock` 且 mock 数据自带 `total_mv: 500e9` → 注入逻辑根本没执行 → "注入路径缺 total_mv" 永不暴露。
   - O19（change_pct=null）：`SectorHeatMap.spec.js` 全部 12 用例 `change_pct` 恒为数值（`:82 :103`），无 null 用例 → `null.toFixed` TypeError 永不触发。
2. **断言"非空/存在/成功"而非"值域/一致性/标签"**
   - O25（no_data=6）：`test_z03_factors_active.py:122-129` 断言 `status=="no_data"`、`summary["no_data"]==1`——**计数有断言但 reason 文案无断言**；缺口因子集合 → reason 完整链路无集成测试。
   - O26（点位标签）：`test_prompt_data_integrity.py:96-102` 断言"点位数值注入 prompt"（`"3500.5" in prompt`），但**不断言"板块指数点位"这个标注标签**——回归成裸数值无标签照样 PASS。
   - O22：`test_watchlist_dirty.py:125` 断言 `realtime is not None`——只证明"完美输入有值"，证明不了"前缀输入有值"。
3. **关键路径被整体 mock 或绕过，测试与实现"同构"、bug 被固化**
   - O23（输入框只显示代码）：`UnifiedAnalysis.spec.js:158-166` 断言 `searchQuery.value` 为 `'510050'` 纯代码——**断言固化的正是 bug 行为**；composable 层 `useMarketSearch.spec.js:47-59` 的"代码+名称"测试（`'510300 沪深300ETF'`）因组件 `pickSearchItem` 绕过 composable（`UnifiedAnalysis.vue:305-314` 直接写 `item.symbol`）而**与组件行为断层**——composable 测试绿 ≠ 组件行为正确。
   - O27：`_fetch_market_data` 被 `AsyncMock` 短路（`test_factor_registry.py:160`），且 `test_factor_pipeline_fixes.py:63-86` 只做**源码文本断言**（`inspect.getsource` 不含 `or 100e9`）——没跑注入路径。
4. **端到端覆盖面窄且分层错位**
   - verify_e2e **不调 `/market/watchlist` API**（只查 DB 行数 `section_db_integrity:1443`）、**不调 `sector-analysis/stream`**（`section_analysis:713-771` 只测 llm-report/advice + sectors/heat 字段）、**完全不覆盖前端渲染层** → O19/O22/O23/O26 这类"数据形态+渲染/匹配"bug 只能靠单测，而单测又只喂完美形态。
   - `verify_e2e section_factor_thresholds:1539-1541` 有 `sentiment no_data = 0` 门限，但 O25 的 6 因子缺口（news_direction/panic_greed_diff/stock_divergence 等）**不在 ET_SPECIFIC_GAP_CODES 集合**（`factor_registry.py:588-596` 只含 etf 四因子+industry_diversification）→ 缺口 reason 走"IC 未累积"兜底（2026-08-07 容器实测证实：6 项 no_data reason 全为「IC 未累积（样本 <3）」），e2e 负向文案检查（不含"尚未计算 IC"）拦不住。
5. **无"输入形态变体"参数化与"跨路径一致性"断言**
   - 全库无 `sh688981`/`sz300750` 这类带前缀输入的参数化用例（O22）；无"compute 直调 vs refresh_pool 两路径数值一致"断言（O27）；无"板块点位有标注标签"断言（O26）；无"news_scope=market 时 news_direction 是否应跳过计算"决策测试（O25）。

> 共同根因一句话：**测试验证的是"代码自述的行为"，不是"用户需求的验收"**——mock 数据与断言都从实现抄，回归时 bug 与断言一起固化。修复方向见 §7 O22/O23/O25/O26/O27 的验收标准（新增畸形输入参数化、reason 文案断言、跨路径一致性、组件层行为断言）。

---

## 7. 优化方案（设计完成，未实施）

### O1（P0-新/P8-新 修复）instruments 同步全链路改造【已拍板：A+B 两者结合】
- **背景（实测）**：90s 持续高频压测（8 并发，模拟 4 段同步 + pre-allocate 打满东财出口）中，东财在 45-60s 窗口出现间歇性黑洞——挂起样本最长 **30.2s**（>requests timeout=15），其余时段快速断开（0.1-7s）。即东财对高频请求**动态切换黑洞/快速断开**，黑洞期 akshare 每页最多等 15s×3 重试+退避 ≈ 49s。
- **A. 阻塞修复【已拍板：两者结合】**：`scripts/sync_instruments.py` 全部 akshare 调用改走 `run_sync`/`asyncio.to_thread`（`app/core/async_utils.py` 已有 `_long_running_executor`）**且** instruments 同步改为**独立后台任务**（启动后异步执行，不阻塞 lifespan）——两者同时落地：线程池保证不占事件循环，后台任务保证启动不被数据源慢拖累。
- **B. 段级超时 + 环境开关**：每段加 `asyncio.wait_for` 超时（如 US 段 20s）；`sync_instruments_table()` 支持环境变量开关（如 `INSTRUMENTS_SYNC_DISABLED=1` 跳过）；失败段记录并继续，不阻塞整体启动。
- **C. pre-allocate 数据采集段同源改造（P8）**：设计任务的 pre-allocate 阶段（数据采集 30.5s + 预分配 41s，`strategy_design.py`）在事件循环线程上同步执行 akshare/factor 采集——同样改走 `run_sync`/`to_thread` 并加超时，避免设计任务 71.7s 阻塞。
- **D. 单测防护**：新增 `scripts/sync_instruments` 的 async-lint 检查（裸同步调用拦截）；启动 gate 测试（`asyncio.wait` 60s 内必须完成）。
- **E. fetch_paginated_data 层整体超时/页数上限**：`stock_us_spot_em` 需拉 138 页（total=13713/100），黑洞期每页 ≈49s 暴露面过大——为 `fetch_paginated_data` 增加**整体超时**（如整段 60s 封顶）与**页数上限/终止阈值**（连续 N 页失败即放弃），或改用东财单次大 `pz`（如 pz=5000）请求替代逐页；任一项失败仅降级该段。
  - **验收**：① `docker compose --profile prod up`（无诊断注入）在 <90s 内完成启动且 health 200；② `scripts/sync_instruments.py` 与 pre-allocate 采集无裸同步 akshare 调用（async-lint 通过）；③ 任一数据源段失败仅降级该段，不阻塞整体启动；④ 设计任务耗时 <30s（不含 LLM）；⑤ `fetch_paginated_data` 在黑洞/快速断开场景下**整体 60s 内必然结束**（新增含黑洞模拟的单测，用本地黑洞 socket 验证 ≤60s 退出）。

### O2（P1-新 港股 K 线）港股数据源链修复
- finnhub 403 → 换有效 token 或走 alphavantage 主源；alphavantage 空 → 解析其实际返回结构（可能字段名不同）；akshare `get_k_data` 空 → 加日志区分"无数据"与"解析失败"；**对 K 线与实时价做一致性校验**（差异 >50% 时标记数据源异常而非透传）。
  - **验收**：① `/market/history/00700?asset_type=HK` 返回 >100 根 K 线且最新日期为当日/前一日；② 港股 symbol-analysis 的 K 线最高价与实时价差异 <50%（不再出现 9.49 vs 492.2）；③ 数据源失败时 history 返回结构化错误而非静默空数组。

### O3（P2-新 hub 缓存断裂）缓存一致性修复
- `_build_advice_market_snapshot` 的指数回退从 `_global_indices_cache["A股"]` 改为读**与 `/indices/global` 相同的缓存/管道**（或直接调 `get_global_indices()`，含 `_global_indices_last_ok` 兜底）；`get_sector_momentum()` 空时回退 `get_sector_industry()`；补充"hub 缓存空"的降级测试。
  - **验收**：① `llm-advice`（query 含"上证指数/板块"）输出含实时指数点位与板块涨跌幅；② `_build_advice_market_snapshot` 在 `_global_indices_cache["A股"]` 为空时仍能回退到 `_global_indices_last_ok`/接口管道；③ 新增单测覆盖"缓存空 + 回退路径"场景。

### O4（P4-新 个股搜索）instruments 表同步与搜索修复
- US 段同步修复后（O1）重灌 instruments；确认 `_search_a_stocks` 降级链（levistock→akshare）可用；`search_hk_us` 检查为何 HK 2613 条搜不到 00700（可能 market 字段/过滤逻辑）；verify_e2e R7-O13 从 SKIP 改为 FAIL（数据源修复后）。
  - **验收**：① `search?keyword=茅台`、`search?keyword=00700&market=HK&include_stocks=true`、`search?keyword=AAPL&market=US&include_stocks=true` 均非空；② `verify_e2e.py` R7-O13 名称搜索改为 FAIL 门禁（数据源修复后不再 SKIP）；③ instruments 表 US>0。

### O5（P5-新 设计涨跌幅）涨跌幅值域校验
- 设计/报告管道对 `change_pct` 加**值域校验**（A 股 ±10%、HK ±30%、美股 ±50% 之外标记"数据源异常"）；R7-P22 的 fallback 死代码修复（factor_matrix 键名 `etf.change_pct` vs `change_pct` 不匹配）；接入 etf_list_cache 快照真实涨跌幅。**依赖顺序：先落 O18（修单位 ×100 + 单一口径）再上本值域校验，否则 -42.6% 输入会永久拦截值域 gate。**
  - **验收**：① 新 design 报告的"今日涨跌"无超出 A ±10% / HK ±30% / US ±50% 的值；② 值域异常时标注"数据源异常"而非透传；③ `test_design_daily_change_fallback` 增加设计报告端到端注入断言。

### O6（P6-新 因子模型）IC 加权与淘汰机制
- 按 IC 正负/显著性淘汰或降权负 IC 因子（sma_60/kdj.d/vol_ratio/vwap）；补 `sample_count`（样本量+显著性）；no_data 因子（**etf_specific + sentiment 数据源缺口，6 项集合见 O25**）修复数据源或标注"未接入"（ET_SPECIFIC_GAP_CODES 补全，含 sentiment 三因子缺口键，见 O25⑦）。
  - **验收**：① `/factors/active` avg_ic ≥ 0（初诊 -0.0747；**复诊实测 +0.0262 已满足，以复诊值为验收基线**）；② `/factors/ic` 每条含非空 `sample_count`；③ no_data 因子从复诊基线 6 降至 ≤2（数据源可用时）。

### O7（P7-新/R7-P25 策略检查 LLM）超时与降级文案
- LLM 超时从 30s 放宽（与设计报告 90s 对齐）；数据采集超时改为**部分结果保留**（`wait_for` 取消 gather 改为 `gather(return_exceptions=True)` + 单独超时）；兜底 summary 含"超时原因 + 已有数据摘要"，而非固定文案。
  - **验收**：① 策略检查任务在 LLM 可用时 `covered_by_llm > 0`；② 采集超时时 `factor_breakdowns` 保留已完成部分（非全空）；③ 兜底 summary 含超时原因与数据摘要。

### O8（P3-新 前端性能）echarts 按需 + CLS 治理【已拍板：performance≥0.7 为软目标，非硬门禁】
- echarts 全量 559KB → **按需引入**（`echarts/core` + 用到的图表）；CLS 0.393 → 骨架屏/占位高度匹配（热点 tab 15 条 840px 占位）；TBT 690ms → vendor 拆分/懒加载。
  - **验收**：① `npm run build` 后 vendor-echarts 拆分为按需 chunk（体积显著下降）；② Lighthouse performance ≥ 0.7、CLS ≤ 0.1、unused JS < 20KiB。

### O9（P9-新 字段断裂）契约对齐【已拍板：concept_tags 后端平铺填充，不改契约】
- `concept_tags` 填充（从 `tag.concept_tag` 平铺，**按已拍板不改契约字段**）；`sectors-heat.change_pct` 填充；watchlist 新条目 name 从 instruments 补名；sh688981 前缀代码行情兼容；watchlist 列表改批量行情查询（消除 N+1）。
  - **验收**：① `stock-hot-rank` 的 `concept_tags` 非空；② `sectors-heat` 的 `change_pct` 非 null（可为 0，与 O19 兜底口径一致）；③ watchlist 新条目 name 为真实名称；④ watchlist 列表耗时 <1s（10 条目）。

### O10（新：设计任务 45s DATA 预算不足，冷缓存首次超时）设计预算弹性化 + 缓存预热点
- **问题**：`design_pipeline` 的 DATA 阶段 `asyncio.wait_for(generate_enhanced_design(...), timeout=45)`（`task_manager.py:291`，OPT-06）在**冷缓存 + 本地慢源**下实测 42-75s 被截断 → `TimeoutError` → 前端报"方案生成超时，数据源响应过慢"（用户本地首次操作即命中，间歇必现）。热缓存时仅 ~10s 成功。伴生：DATA 内同步 IO 短暂占用事件循环，期间 `/portfolio/tasks/{id}` 查询也超时。
- **A. 预算弹性化**：45s → 可配置（`DESIGN_DATA_TIMEOUT` env，默认 90s）或按缓存命中选择（冷缓存 120s / 热缓存 45s）。
- **B. 消除首次全量建缓存**：冷启动时 `refresh_kline` 全量（Semaphore(5) × 20s/只）改为小样本 + 超时降级；K 线缓存提前到启动预热（对齐 R7-O1 的 etf_list_cache 预热），避免 design 首次承担。
- **C. 复用 O1-C**：DATA 阶段裸同步 akshare 采集改 `run_sync`/`to_thread`，避免事件循环被占导致连任务查询都超时。
- **D. 单测**：新增"冷缓存设计首次 DATA ≤ 预算" gate 测试；mock 慢源（单只 kline 2s）断言不超预算。
  - **验收**：① 冷缓存首次设计在 DATA 预算内完成（不报"方案生成超时"）；② 热缓存设计 DATA <15s；③ 设计期间 `/portfolio/tasks/{id}` 始终可查询（事件循环不被占）；④ 新增单测覆盖冷/热缓存两态。

### O11（新：前端任务状态机纠偏——失败无法二次触发/残留）
- **问题（实测）**：设计失败后 `designStep` 停 `'loading'` + `activeCoreFeature='design'`，`DashboardAiTools.vue:13` 的工具列表在 `activeCoreFeature` 非空时不渲染 → 失败界面无"重新生成"入口、无法二次触发；`exitCoreFeature:337` 把失败态当 loading 持久化；复位仅依赖 `docs/interaction-redesign.md` 所述组件 `active` 的 `true→false`（`resetToTools.spec.js` 未覆盖"同 tab 内失败后重复触发"）。
- **设计状态机**（已单独成稿 `docs/interaction-redesign.md`，D1/D2/D3）：`idle→drafting→running→result|failed`，failed 是终态且带 `canRetry`，可停留/重试/返回；仅持久化 `result` 与暂存 `running{taskId}`，failed 不入 localStorage。
- **验收**：① 失败卡带「重试一次」+「返回」，二者均可操作；② 同 tab 内失败后再次进入回到 idle（不残留）；③ WS 完成 + 轮询只 finalize 一次（taskId 幂等）；④ 退出持久化 running，再进恢复 loading。

### O12（新：历史列表 join tasks——失败任务从"隐形"到可见）
- **问题（实测）**：`/portfolio/timeline`（portfolio.py:466-508）只查 `portfolio_designs`/`strategy_check_records`，**从不 join `tasks` 表** → Stage 2 就失败未写库的设计任务（如 #234 rec=None）在历史列表**永远看不到**（前端"任务/历史"既不含它，taskStore 失败即 removeTask）→ 用户只看到成功方案，失败任务"凭空消失"，与进度卡面的失败形成矛盾观感。
- **D2（已拍板）后端 `/portfolio/timeline` join `tasks` 表**：并入 `task_type='design'` 任务，失败项带 `status='failed'`+`error_message`，前端 DesignHistory 显示"❌失败"+可点错误详情+重试；已完成且已有 design 记录的不重复。
- **验收**：① 触发一次 Stage2 失败后 `/timeline` 返回 `failed`+`error_message`；② 前端历史列表正确渲染失败项与错误详情/重试；③ 已写库成功项不因 join 重复。

### O15（R7-P23 根因深化，见 §5.1A）消费电子类指数避免误归「食品饮料」
- `INDEX_KEYWORDS` 加 `"消费电子"` 且 `_extract_index_keyword` 改**最长匹配优先**（先长词后短词，避免"消费"截走"消费电子"）；`etf_classifier._INDEX_RULES` 加 `("消费电子","电子")`；tracked_index 命中时若 name 含更精确方向优先用 name。
- **验收**：① 562950 `industry='电子'` 且 `tracked_index!='消费'`（为"消费电子"或含电子）；② 新增 562950 分类单测；③ `_extract_index_keyword('消费电子ETF')` 返回 `消费电子` 而非 `消费`。

### O16（设计：平衡方案文案与分配一致，见 §5.1B）rationale 宽基风格统一【已拍板：并入 §5.1C 取向（压卫星≤20% + 精简 core 叠加 + 防御 15-20%）同批实施】
- `rationale._style_probe` 与 `build_rationale` 的宽基关键词清单**统一**（`_style_probe` 并入 A100/A500 等）；`_layer_phrase` 改为按**标的真实风格/市值**（tracked_index 中的中盘/大盘/成长/价值提示）选句，而非仅 symbol hash 随机抽；core 宽基用"中盘/大盘宽基"中性描，杜绝"大盘价值代表性/高弹性品种"套在宽基 ETF。
- **验收**：① balance 方案 510500 文案不再含"大盘价值代表性"（改"中盘宽基"等中性句）；② 562000（core）不再出现"卫星仓位/高弹性"字样；③ 新增 `test_rationale_layer_not_conflict`（layer=core 时短语不含"卫星"）。

### O17（新：前端可用性——字号过小 + 内容未铺满页面）【已拍板：合并实施 interaction-redesign.md + frontend-theme-redesign.md】
- **问题（实测/用户反馈）**：全局默认字号偏小（实测根字号 14px，`global.css`/`theme.css` `--font-size-base` 及组件 px），财报密集区可读性差；多数页面有固定 `max-width`（约 1200-1280px，实测 Dashboard 主容器 1200px 且宽屏左右留白 >200px）；
- **方向**：① 根字号 `--font-size-base` 提到 15-16px（实测 14px → 15px+），正文/表格/卡片统一优化；② 主内容容器放宽（`max-width: 1440px` + 无大留白）；③ 卡片网格改自适应填满；④ 保持红涨绿跌等既有主题符号不变。**细则见 `docs/interaction-redesign.md` 视觉治理段（字号 scale、容器 `width: min(100%, 1440px)`、网格 `repeat(auto-fill, minmax(...))`）。**
- **验收**：① 核心页面（Dashboard/行情/组合/分析）正文 ≥15px 且内容宽度 ≥ 视口 92%；② `npm run build` 通过、样式不破坏现有红涨绿跌测试；③ Lighthouse 不劣化。

### O18（新：报告「今日涨跌」与实际行情脱节 + 100 倍单位 bug）
- **问题（实测，design #418 报告 vs 实时 `/market/realtime/batch`）**：
  - 上证50ETF 报告「跌 23.40%」（实时 **+0.73%**，方向都反）；黄金ETF 报告「跌 10.70%」（实时 **+0.13%**）——两者被**放大 100 倍**且与盘面矛盾。
  - 多数标的方案/报告值普遍比实时偏高 2-5 倍：510300 方案 1.131 vs 实时 0.79、159915 5.684 vs 1.64、588000 4.279 vs 1.06、510500 2.439 vs 1.24、562950 5.674 vs 2.41。
- **根因链（代码定位）**：
  1. **单位×100 bug（主因）**：`tasks/design_report.py:155` `dcp_txt = f"{dcp * 100:.2f}%" if abs(dcp) < 1 else f"{dcp:.2f}%"`——当 `daily_change_pct` 已是**百分数值**（-0.234=-0.234%）时错误再 ×100 → -23.40%。`abs(dcp)>=1` 分支才不乘，故低幅标的才爆炸。
  2. **数据源非实时**：`daily_change_pct` 来自 **pool 缓存 `change_pct` / K 线 `close` 差**（`strategy_design.py:296-330` S6 注入），非 `/realtime` 实时快照 → 与盘中实时系统性脱节。
  3. **单位口径混用**：`strategy_design.py:305-330` 将「pool 百分值」直接赋与「K 线小数值×100」两种口径混入同字段，line 155 被迫用 `abs(dcp)<1` 试探 → 成为定时炸弹。
- **修复方向（仅设计）**：① 统一 `daily_change_pct` 为唯一口径（推荐**百分比**），删除 `abs(dcp)<1` 乘 100 分支，恒 `f"{dcp:.2f}%"`；② 报告注入改为读 `/realtime` 实时 `change_pct`（或标注数据时间戳，避免与盘面脱节）；③ 新增「报告值 vs 实时值误差门禁」单测/校验。
- **验收**：① 510050/518880 报告值不再出现 ≥10 倍的极端涨跌（与实时偏差 <5 个百分点）；② `daily_change_pct` 单一口径；③ 新增 `test_report_dcp_consistency`（报告 DCP 与 /realtime 偏差在阈值内）。

### O19（新：热点板块「板块热度」card 消失——null `toFixed` 崩溃，见 §5.1D）
- 前端 `SectorHeatMap.vue:63` `v-if="item.change_pct !== undefined"` 挡不住 `null`；`item.change_pct.toFixed(2)` 对 null 抛 TypeError → data-row 渲染中断 → 卡片消失。A 股 `/market/sectors/heat`（market.py:633）`change_pct` 恒 null（财联社板块热度无涨跌幅）。
- **修复方向**：`v-if` 改 `item.change_pct != null`（同时挡 null/undefined）；后端 market.py:633 把 null 兜底为 0（与 O9 验收②「非 null 可为 0」对齐，推荐唯一方案，不采用剔除列）。
- **验收**：① A 股 heat 20 行正常渲染、无控制台 TypeError；② `SectorHeatMap.spec.js` 新增「change_pct=null 不报错、卡片正常渲染」用例通过。

### O20（新：热点/自选个股技术分析补 K 线图，见 §5.1E）
- 现状：`TechnicalAnalysisModal.vue` 已拉 K 线 + 资金流却只算今日涨跌未画图；`AnalysisView.vue:157-275` 已有完整 candlestick option（可抽成 `useKlineOption` composable 复用）。
- **修复方向**：抽 `useKlineOption` 复用 K 线 option；弹窗接入 candlestick + 均线 + 量能 + dataZoom；布局适配（modal 加宽）；资金流并列展示。
- **验收**：① 弹窗出现可缩放 K 线图；② 图示与今日涨跌/资金流一致；③ `npm run build` 通过 + 前端单测覆盖。

### O21（新：行情/自动补全 2 秒延迟——`localhost` IPv6 回退，见 §5.1F）【已拍板：方案一，uvicorn 监听 `[::]:8000`】
- 实测：`openapi.json`/`system/warmup`/`admin/thread-pool` 等静态接口恒 ~2.05s；`localhost:8000` connect=2.06s 而 `127.0.0.1:8000`=0.03s；`getaddrinfo('localhost')` IPv6 优先。
- **根因**：uvicorn 监听 `0.0.0.0`（IPv4-only），`localhost` 先连 `::1`（无人监听）→ ~2s 回退 `127.0.0.1`。属环境/部署层。
- **修复方向【已拍板：方案一】**：uvicorn 监听 `[::]:8000`（含 v4）——首选；备选：统一直连/WS/nginx 反代目标为 `127.0.0.1`；或防火墙让 `::1` 立刻拒绝。
- **验收**：`localhost:8000` 任一接口 connect <0.1s；自动补全即时。

### O22（新：自选 A 股股票后几列为空——`get_asset_realtime` 前缀匹配失败，见 §5.1G）
- 现象：自选添加「中芯国际」(`sh688981`)后实时列为空；`fetch_a_stock_realtime` 返回纯数字 `688981`，`get_asset_realtime` 用 `item["symbol"]==symbol` 精确比对 `sh688981` 永不命中 → realtime=null。
- **排查补充（2026-08-07 容器内实测）**：`fetch_a_stock_realtime('sh688981')` → **[] 空**（带前缀导致底层源 tencent/sina/mootdx 取数失败）；`('688981')` → `[('688981', 128.5)]`；tencent/sina 对纯数字输入输出 symbol 统一为 `688981`。**结论：带前缀在 fetch 层就取不到数据，比对层剥前缀救不了空数据。**
- **修复方向（修正）**：根本修法为 `fetch_a_stock_realtime` 入口先剥 `sh/sz/bj` 前缀再取数（让底层源拿到纯数字）；`get_asset_realtime` 比对层同步剥前缀（双保险）；search/入库规约纯数字 symbol。
- **验收**：① `sh688981` 自选实时有值；② 新加任意 A 股股票自选实时正常；③ 无 A 股股票 realtime=null；④ 补 `market_service` 单测「带前缀 A 股 symbol 也能匹配实时」；⑤ 补 `china_market` 单测「fetch_a_stock_realtime 入口剥前缀后底层源收到纯数字」。

### O23（新：标的分析输入框只显示代码——`pickSearchItem` 绕过 composable，见 §5.1J）
- `UnifiedAnalysis.vue:305-314` `pickSearchItem` 只写 `searchQuery=symbol`，未复用 `useMarketSearch.js:132-138 selectSearchItem`（`名称 (代码)`）——组件层绕过 composable 的"代码+名称"回显；`UnifiedAnalysis.spec.js:158-166` 断言固化了"只显示代码"的 bug 行为。
- **修复方向**：`pickSearchItem` 复用 `selectSearchItem`/`acceptCompletion` 的「代码 名称」回显；`doAnalyze` 对「代码+名称」混合串解析 symbol（先截首个 token，`looksLikeCode` 正则需兼容空格/中文）。
- **验收**：① 下拉选中后输入框显示「代码 名称」或「名称 (代码)」；② 混合串能正确分析（symbol 解析成功）；③ `UnifiedAnalysis.spec.js` 更新为"代码+名称"断言。

### O24（新：标的分析"分析失败"——SSE 空内容/数据源异常，见 §5.1K）【已拍板：方案 A——失败分类 + 可重试，不改 provider】
- `UnifiedAnalysis.vue:386-390`：SSE 空 `fullText` → "AI 未返回内容"；SSE 异常 → "网络错误"。
- **根因定性（2026-08-07 容器内复测，正确路径 `/api/v1/analysis/symbol-analysis/stream`）**：
  - `sh688981` + name 空 → **7.0s 失败 `DATA_UNAVAILABLE 数据源暂不可用`**（**主因 = O22 前缀问题**，带前缀直接致分析失败，比 realtime 空更严重）；
  - `688981` + name 空 → 24s 成功；`688981` + name='中芯国际' → **56s 成功（慢但成功）**——**次因 = LLM 慢**（56s > 45s 硬超时会被误杀），name='' 无影响；
  - 前端 `useLLMStream.js:74-75` SSE error 抛 `parsed.message` → 能透传 DATA_UNAVAILABLE 原文（"数据源暂不可用"），但 `UnifiedAnalysis:390` 笼统加"分析失败："前缀、无分类处理。
- **修复方向【方案 A 细化】**：① **失败分类**——后端复用 `llm.py` 的 `_last_llm_error`（`[rate-limited]` 429 / `[timeout]`）分级返回，前端据此显示差异化文案（"请求过于频繁请稍后重试" vs "数据源无响应" vs "标的信息不完整"）；② **可重试**——失败卡带「重试一次」（配合 O11 `canRetry`），点击后带退避重发；③ **超时分级**——`symbol-analysis/stream` 的 45s 硬超时放宽至 LLM 阶段 90s（对齐 R7-O5），避免慢但正常的请求被误杀（实测 56s 成功请求被 45s 误杀）；④ **复用限流参数**——给 symbol-analysis 调用传 `max_retries`/`cap`（现状未传，llm.py 重试机制未生效）；⑤ 联动修复：名称解析覆盖混合串（O23）、**后端 symbol 前缀归一化（O22，主因）**。
- **验收**：① 失败给可操作分类 + 重试入口；② 纯代码输入分析成功且名称正确；③ `sh688981` 分析不因前缀失败（**O22 修复后回归验证**）；④ 前端单测覆盖"SSE 空→失败态 + 重试"；⑤ 429 场景下前端显示"请求过于频繁"文案而非笼统"网络错误"。

### O25（新：因子模型 6 项数据缺失 + 1 项 warn——etf_specific/sentiment 数据源缺口，见 §2 P6-新 与 §6 盲区）【已拍板：接受加降级链/换源成本，不降级 static】
- 现象：因子模型页 summary `no_data=6, warn=1`（**2026-08-07 容器内运行时实测 `/factors/active`**：valid=23 / warn=1 / no_data=6 / static=3 / avg_ic=+0.0262；08-05 初诊为 no_data=10，数字变化反映数据源可用性而非代码回归）。
- **运行时 no_data 集合（实测）**：`etf.premium_discount` / `etf.tracking_error` / `etf.shares_change` / `sentiment.panic_greed_diff` / `sentiment.stock_divergence` / `sentiment.news_direction` —— **6 项（修正此前 DB 推断的 5 项，漏 `stock_divergence`）**，reason **全部为笼统「IC 未累积（样本 <3）」**。
- **为何 reason 全是「IC 未累积」而非「数据源未接入」**：`ET_SPECIFIC_GAP_CODES`（factor_registry.py:588-596）只含 etf 4 因子 + industry_diversification，`GAP_FIELD_MAP`（factors.py:16-19）只含 style.size 两键——**sentiment 三因子不在任何缺口集合** → `_status_of` 查 `_data_source_gaps` 无记录 → 落「IC 未累积」兜底；且本次运行 `_data_source_gaps` 为空（IC 周期 compute 未触发缺口记录路径）。**与 §6 盲区第 4 条判定一致。**
- 各因子根因：① premium_discount：`nav` 缺口（IOPV 链 + TTJ 兜底失败）；② tracking_error：`benchmark_close` 缺口（仅宽基映射注入）；③ shares_change：`shares_change_20d` 缺口（东财源失败）；④ news_direction：news_scope=market 降级 → 截面无区分度；⑤⑥ panic_greed_diff/stock_divergence：情绪/涨跌比源停更，截面全 0。
- **修复方向（已拍板：加降级链/换源）**：① premium_discount：确认 IOPV/TTJ 源被墙根因（R7-O18 同链）并加显式超时/重试/备用源；② tracking_error：`_WIDE_BASIS_INDEX_CODES` 扩覆盖 or 行业 ETF 用申万行业指数 close 注入；③ shares_change：`fetch_etf_shares_outstanding` 加降级链（东财 → 天天基金）或换接口；④ news_direction：news_scope=market 时标注「无个股级区分度」而非硬算全 0（或跳过计算）；⑤⑥ sentiment：情绪源恢复后自动补齐（R5-1-5 120s 周期 compute）；**⑦ 缺口集合补全：`ET_SPECIFIC_GAP_CODES` 增加 sentiment 三因子缺口键，让 reason 能落到「数据源未接入」而非笼统「IC 未累积」。**
- **验收**：① no_data 从 6 降至 ≤2（仅剩真外部源不可用项）；② 每个 no_data 因子 reason 能区分「数据源未接入」vs「IC 未累积」（补 sentiment 缺口键后验证）；③ 新增单测 `test_factor_gap_reasons.py` 断言 6 项缺口与 reason 文案（sentiment 因子 reason 含对应缺口字段）。

### O26（新：板块技术分析点位口径不清——点位是板块指数非成分股，见 §5.1H）
- 板块分析报告点位（如 BK1326 报 50118.43 点）来自东财板块指数行情；**2026-08-07 容器内实测 sector-analysis/stream（BK1326）61.1s 返回 40087 chars——首段"板块指数报收 50118.43 点"点位数字在，但全文无"板块指数点位"显式标签（`板块指数`/`点位` 关键词均缺失）→ O26 未修复，方案仍有效**。
- **修复方向**：报告首段标注"板块指数（BKxxxx）点位"+ 技术面注明均线周期/数据区间（prompt analysis.py:776 仅有技术面提示，首段/资金面需补显式口径）。
- **验收**：板块报告首段含"板块指数（BKxxxx）点位"表述；技术面注明均线周期。

### O27（新：基本面/市值数据缺失——`_fetch_market_data` 未注入 total_mv/float_mv，见 §5.1I）
- `_fetch_market_data` 注入字段不含 total_mv/float_mv/PE/PB；`compute()` 直调时 style.size 因子（ln_mcap/ln_float_mcap）输出全 0 → 截面无区分度。refresh_pool 路径有市值数据 → **同因子两路径不一致**。
- **修复方向**：`_fetch_market_data` 补注入市值字段（复用 refresh 路径）；统一 symbol_extra 口径；缺失时显式标注。
- **验收**：① compute 与 refresh 两路径 ln_mcap 一致；② 无全 0 截面 style 因子；③ 单测断言直调路径注入 total_mv。

---

## 8. 回收与清理

- 容器：`docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod down`（移除 backend/frontend/redis 容器与 etf_surge_default 网络）。
- 临时文件：删除 `docker-compose.diag.yml`、`data/diag_entrypoint.py`、`data/_diag_*.py`、`data/_diag_*.json/md/sse` 等诊断产物。
- 诊断注入说明：本轮因 P0-新 阻塞必须用 `data/diag_entrypoint.py`（非产品代码）绕过 US instruments 段才能启动；O1 落地后应删除注入并可正常启动。

---

## 8.5 实施顺序与依赖拓扑 + 风险与回滚（新增，供实施轮排期）

### 依赖拓扑（实施轮必须遵守的先后关系）

```
O1 ──┬─→ O4（US 同步修复后才能重灌 instruments 搜索）
     ├─→ O10-C（pre-allocate 同步 IO 改造，消除事件循环占用）
     └─→ O21（部署层，独立可并行）
O18 ──→ O5（先修 ×100 单位 + 单一口径，再上值域校验，否则 -42.6% 永久拦截 gate）
O22 ──→ O24（前缀归一化是分析失败主因，先修 O22 再验证 O24）
O23 ──→ O24（名称混合串解析）
O9  ──→ O19（change_pct 兜底 0 口径协调：O9 验收「非 null 可为 0」与 O19 兜底 0 唯一方案一致）
O15/O16/§5.1C ──→ 同批实施（消费电子分类 + rationale 文案统一 + 三方案取向）
```

### 建议批次（按依赖 + 风险从低到高）

| 批次 | O 项 | 理由 |
|------|------|------|
| **批次 1（P0/P1 数据正确性）** | O1、O18、O5、O2、O3 | 启动阻塞 + 涨跌幅 ×100 + 港股 K 线 + hub 缓存断裂，全部后端数据正确性硬伤，先修先验 |
| **批次 2（搜索/因子）** | O4、O6、O25、O27、O7 | 依赖 O1（US instruments）；因子缺口集合与 reason 补全（O25⑦）先行，O6 淘汰机制后置 |
| **批次 3（前缀/分析）** | O22、O23、O24 | O22 主因先行；O24 依赖 O22+O23 |
| **批次 4（前端）** | O8、O17、O19、O20、O11、O12 | 前端独立；O11/O12 状态机与历史列表可独立交付 |
| **批次 5（性能/收尾）** | O10、O9、O16+§5.1C、O21、O26 | O10 依赖 O1-C；O21 部署层独立；O26 prompt 小改 |

> 说明：O15/O16 亦为批次 2/4 边缘项，可按实施轮人力并入相邻批次；§5.1C 取向与 O16 同批（已拍板）。

### 风险与回滚

| O 项 | 风险 | 回滚/缓解 |
|------|------|----------|
| O1（lifespan/启动路径重构） | 最高：改启动序列可能引入新的启动失败或后台任务静默失效 | 回滚=还原 `main.py` lifespan 改动；缓解=启动 gate 测试（<90s health 200）+ 日志显式记录各段完成；后台任务失败仅降级不阻塞 |
| O21（uvicorn 监听 `[::]`） | 中：影响 nginx 反代/WS 直连目标；`::` 绑定在部分云环境需 DNS64/防火墙配合 | 回滚=还原 `0.0.0.0`；缓解=先验证 prod nginx 反代目标与 WS 握手，connect 实测 <0.1s 后再合入 |
| O24（45s→90s 超时放宽） | 中：增加用户等待上限；若限流参数未同步，可能放大 429 重试风暴 | 回滚=还原超时值；缓解=超时分级（LLM 90s / 数据源 45s）+ `max_retries`/`cap` 复用 llm.py 限流 |
| O5（值域校验） | 中：校验阈值可能误杀真实极端行情（如港股单日 ±30% 上限） | 依赖顺序先 O18；阈值可配（env）；误杀时标记"数据源异常"而非丢弃数据 |
| O25（降级链/换源） | 低：外部数据源（IOPV/TTJ/东财）不可用时不回退 static | 已拍板接受成本；每源降级链独立超时/重试，失败仅降级该因子 |

> **通用实施纪律**：每个 O 项先写/改测试（TDD）→ 实现 → `verify_e2e.py` 全 PASS → commit；批次内不得跳过依赖顺序（见拓扑）；每批次结束后跑一次全量后端单测 + 前端 `npm run build`。

---

## 9. 实施标准（Checklist，供后续实施轮使用）

> **使用说明**：① 本 checklist 与 §7 各 O 项验收**并读**——未列出的验收项以 §7 为准（如 O10④ 冷热缓存两态单测、O11④ 退出持久化 running、O12② 前端渲染失败项、O17③ Lighthouse 不劣化、O24③ sh688981 回归验证，均已在 §7 验收定义，实施轮按 §7 执行）；② **依赖顺序**：O5 先落 O18；O4 依赖 O1；O10 依赖 O1-C；O24 依赖 O22/O23；§7 各 O 项已标注。

- [ ] 单测（O1）：`backend/tests/test_instruments_sync_async.py`（裸同步拦截 + 段超时 + 开关）新增并通过；**async-lint 裸同步拦截通过（验收②）；任一段失败仅降级不阻塞启动（验收③）**；O1 验收④⑤（设计任务 <30s、黑洞 socket 60s 内结束）覆盖
- [ ] 单测（O3）：`backend/tests/test_advice_hub_cache_empty.py`（hub 缓存空 + 回退 key 匹配）新增并通过
- [ ] 单测（O5，**先落 O18 再上本值域校验**）：`backend/tests/test_design_change_pct_range.py`（涨跌幅值域校验）新增并通过；**扩展 `test_design_daily_change_fallback` 加设计报告端到端注入断言**（§6 盲区第 3 条指出的缺口）
- [ ] 单测（O4）：`backend/tests/test_search_stock_by_code.py`（600519/00700/AAPL 搜索非空）新增并通过
- [ ] 单测：`backend/tests/test_etf_consumer_electronics.py`（O15：562950 分类=电子、非食品饮料 + `_extract_index_keyword('消费电子')`）新增并通过
- [ ] 单测：`backend/tests/test_rationale_layer_not_conflict.py`（O16：layer=core 短语不含"卫星/高弹性"，宽基中性描述）新增并通过
- [ ] 单测：`backend/tests/test_report_dcp_consistency.py`（O18：报告 DCP 单口径 + 与 /realtime 偏差阈值 gate；510050/518880 不再 ≥10 倍极端）新增并通过
- [ ] verify_e2e：R7-O13 名称搜索从 SKIP 改 FAIL（数据源修复后）；启动 gate（<90s）；history HK 非空
- [ ] 前端（O8）：echarts 按需引入后 `npm run build` 通过；Lighthouse performance ≥ 0.7（软目标）、CLS ≤ 0.1、unused JS < 20KiB
- [ ] 前端（O17）：核心页面正文 ≥15px、内容宽度 ≥ 视口 92%；`npm run build` 通过；确保样式不破坏红涨绿跌（Lighthouse 不劣化，见 O17 验收③）
- [ ] 前端（O19）：`SectorHeatMap.spec.js` 新增「change_pct=null 不报错、卡片正常渲染」用例通过；A 股 heat 20 行正常、无 TypeError
- [ ] 前端（O20）：`TechnicalAnalysisModal` 接入 K 线图（复用 `useKlineOption`）；新增「弹窗出现 K 线 + 与今日涨跌/资金流一致」单测；`npm run build` 通过
- [ ] 部署（O21）：uvicorn 监听 `[::]:8000`（已拍板方案一）；`localhost:8000` 任一接口 connect <0.1s；自动补全接口耗时 <0.1s（替代"肉眼即时"表述）
- [ ] `docker compose --profile prod up` 无需诊断注入即可启动；`verify_e2e.py` 全 PASS
- [ ] 后端（O22）：`market_service` 单测「带前缀 A 股 symbol（sh688981）也能匹配实时」通过；**`china_market` 单测「fetch_a_stock_realtime 入口剥前缀后底层源收到纯数字」通过（验收⑤，根本修法验证）**；自选 `sh688981` 后三列有值
- [ ] 后端（O25）：`test_factor_gap_reasons.py` 断言 no_data 缺口集合（6 项：premium_discount/tracking_error/shares_change/news_direction/panic_greed_diff/stock_divergence）+ reason 文案（sentiment 因子含缺口字段，非笼统「IC 未累积」）；no_data ≤2（外部源恢复后）
- [ ] 后端（O26）：板块分析报告首段含"板块指数（BKxxxx）点位"表述 + 技术面注明均线周期；单测断言报告含该标注
- [ ] 后端（O27）：`compute()` 直调路径注入 total_mv/float_mv；`test_factor_compute_injects_mv.py` 断言 ln_mcap 两路径一致、无全 0 截面
- [ ] 后端（O9）：`stock-hot-rank.concept_tags` 非空；`sectors-heat.change_pct` 非 null（可为 0）；watchlist 新条目 name 真实名称；watchlist 列表耗时 <1s（10 条目）
- [ ] 后端（O2）：`/market/history/00700?asset_type=HK` 返回 >100 根且最新为当日/前一日；symbol-analysis 港股 K 线最高价与实时价差异 <50%
- [ ] 后端（O6）：`/factors/active` avg_ic ≥ 0；`/factors/ic` 每条含非空 `sample_count`；no_data ≤2（复诊基线 6，数据源可用时）
- [ ] 后端（O7）：策略检查 LLM 可用时 `covered_by_llm > 0`；采集超时时 `factor_breakdowns` 保留已完成部分；兜底 summary 含超时原因与数据摘要
- [ ] 后端（O10）：冷缓存首次设计 DATA 阶段 ≤90s（默认 `DESIGN_DATA_TIMEOUT`，冷缓存 120s，见 O10-A）不报"方案生成超时"；热缓存设计 DATA <15s；设计期间 `/portfolio/tasks/{id}` 始终可查询；新增冷/热缓存两态单测（O10 验收④）
- [ ] 前端（O11）：失败卡带「重试一次」+「返回」均可操作；同 tab 失败后再次进入回 idle；WS 完成 + 轮询只 finalize 一次；退出持久化 running、再进恢复 loading（O11 验收④）
- [ ] 后端（O12）：触发一次 Stage2 失败后 `/timeline` 返回 `failed`+`error_message`；前端历史列表正确渲染失败项与错误详情/重试（O12 验收②）；成功项不因 join 重复
- [ ] 前端（O23）：`UnifiedAnalysis.spec.js` 更新为「下拉选中后输入框显示 代码+名称」断言；混合串 doAnalyze 分析成功
- [ ] 前端（O24）：`UnifiedAnalysis.spec.js` 新增「SSE 空 → 失败态 + 重试入口」用例；纯代码输入分析成功且名称正确；`sh688981` 分析不因前缀失败（O22 修复后回归验证，O24 验收③）；429 场景显示"请求过于频繁"分类文案

