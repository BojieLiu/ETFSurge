# round25 容器验收与优化方案（2026-08-16）

> 本文档为对 round24 修复全部落地后的**新一轮 Docker 重建 + 16 项验收动作**的结论与剩余问题修复设计（含 R40 盘后无动量注入、R41 近替代品冗余控制盘后绕过，均本轮新增设计）。
> **本文档仅设计修复方案，不实施。** 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」「API 契约先于实现」撰写。
> 验证环境：Docker Desktop Engine 29.7.2 / Compose v5.3.1，prod profile 重建启动，后端 :8000 / 前端(nginx) :80；后端镜像 `d72406e9b115`、前端 `522fe39105cb`。PROFILE_WARMUP=1 启动（预热诊断）。

---

## 0. 执行摘要

### 0.1 本轮性质：round24 落地后的新一轮全量验收
round24（`docs/round24-reverification-and-fixes.md`）的 R1-R26 已全部实施并推送（memory：Batch1 d9a734e / Batch2 98b98a7 / R20 8841dda / Batch3 6b13948+0272150）。本轮用**全新 Docker 镜像 + 16 项动作**复验：**round24 R1-R26 绝大多数已生效并实证通过**（§7），同时发现 **1 个 P0 信号口径矛盾 + 3 个 P1 前后端/数据断裂 + 若干 P2 治理残留**（§0.3）。

### 0.2 验证动作与结果基线
| # | 动作 | 结果 |
|---|---|---|
| 1 | Docker 构建前后端 + 回收老镜像 | ✅ 新镜像 backend `d72406e9b115` / frontend `522fe39105cb`，老镜像已被同名 tag 替换回收 |
| 2 | 预热性能诊断（PROFILE_WARMUP=1） | ⚠️ 预热 20.0s，`warmup_market_cache` 13.3s(66%) + `warmup_global_indices` 6.6s(33%)（**F1/F2/F3/F3b 未实施 = R6 未做**） |
| 3 | 组合设计 577 + 场内策略检查 610（on_exchange） | ✅ 设计 report_quality=full、R2/R3/R24 生效；⚠️ 策略检查 LLM 429 兜底（design 背靠背耗尽配额）、因子分两路径矛盾（P0） |
| 4 | A/HK/US 行情分析全能力 | ✅ 综合研判/个股/板块/概念/搜索自动补全真实可用（真实财报/指数）；⚠️ indices/global 返 0 条、LLM first_byte 25-57s |
| 5 | 热点 + 自选 | ✅ 热点板块个股加载成功；⚠️ **watchlist 列表 5s 超时退化 DB-only（无 realtime/无 realtime_unavailable 徽标）** |
| 6 | 持仓技术信号 | ✅ 10 只全部 data_available + reasons 非空，F10 超买→hold 生效；信号与理由自洽 |
| 7 | 资讯分级 + 智能分析 | ✅ R16 英文分类生效（global 2/8 other）、R15 无 ETF日报；⚠️ R17 摘要 cap=6 全被 headlines 独占、macro 仍混非宏观 |
| 8 | 因子模型页 | ✅ R22 avg_ic 统一（0.2121）；honest（valid=0/no_data=27/static=11/38 实现/155 规划） |
| 9 | 前后端断裂排查 | ✅ check_routes 73 路由全 OK；⚠️ **字段级断裂 2 处**（watchlist realtime_unavailable、综合信号 composite_decision） |
| 10 | round24 方案落地核验 | ✅ R1-R26 中 22 项实证生效；⚠️ R6/R7/R9/R10/R17/R25/R26 残余（§7） |
| 11 | 前端 Lighthouse（7 路由） | ✅ /news CLS 0.001（R8 修复）、全站 CLS 0.001；⚠️ root perf 69（<90）、portfolio-analysis a11y 82（<90） |
| 12 | 后端链路性能（冷/热） | ✅ 热态全 <50ms；⚠️ 冷态 sectors/heat 4.7s、indices/global 10.2s、stock-hot-rank 2.3s、etfs 2.0s；watchlist 恒 5.05s |
| 13 | 测试防护缺口分析 | ⚠️ verify_perf symbol-analysis 用错路径（假 OK）；R25 死代码无集成测试拦截 |
| 14 | 冗余代码识别 | ✅ R18 死端点已删、check_api_usage 0 unused；⚠️ R25 综合信号前后端死代码、scripts import 断裂、20+60 临时残留文件 |
| 15 | 综合结论 + 优化修复方案 | 本文档（R27-R41 修复设计，达实施标准不实施） |
| 16 | 回收容器 + 归档 + commit/push | 见 §13 与结尾 |

### 0.2b verify_e2e 复验（279/291 通过，12 项失败归类）
| 类别 | 失败项 | 性质 |
|---|---|---|
| 数据源熔断（环境） | ETF 记录数=1、有成交额/规模/价格 ETF=0、etf_specific no_data=10、sentiment no_data=1 | 数据源 cooldown + 周末盘后 |
| LLM 全链 429 | llm-advice len=0、sector-analysis 流空壳 | 本轮 design+strategy-check+行情分析把 free-tier 配额打爆（R39 印证） |
| 性能 | 预热 20.0s > 20s gate、timeline 1.3s > 1.0s | 冷态路径（R33/R32） |
| watchlist 退化 | P3-C watchlist realtime 非空 0/23 | **R29 实证**（5s 超时退化 DB-only） |

### 0.3 问题分级（新发现，危害驱动）
- **P0（投资判断/数据可信度）**
  1. **因子分口径矛盾（R27）**：同一标的 `159338 中证A500` 在组合设计路径 composite z-score = **-0.958**（深负，近剔除线），在策略检查路径「因子分 **1.68（偏强）**」——两条路径对同一标的给出**方向相反**的因子评级。专业投资者对照两屏必然困惑。根因（经本轮 code 复核修正）：设计用 `factor_registry.compute()` 跨截面 z-score 复合（`allocation_engine.py:401-405` 加权求和、`:623` 取整，输入经 `factor_registry:1484` z 化 + `factor_aggregate.py:50` 取反均值回复类因子）→ `159338` 得 **-0.958**；策略检查用 `portfolio_service._rule_based_suggestion`（函数起 `:1634`）的 `avg_factor` = **原始因子值（含原始量纲政策因子 `china.policy.* +8.97`）的朴素均值**（`portfolio_service.py:1662-1664`），再经 R21 分档映射为「偏强 1.68」。注意：**KDJ 实际已被 z 化取反**（非主因），+1.68 主要由原始政策因子拉高。两者量纲、聚合口径完全不同，却共用「因子分」字样。修复设计见 §2.7。
  2. **R25 综合信号是前后端双断的死代码（R28，用户提问驱动复核）**：`composite_decision` 后端已计算并附加到内部 `factor_breakdowns`（`portfolio_service.py:1045` 调 `_attach_composite_decisions`，函数体 `:1521-1564`，经 `app/analysis/signal.composite_signal_with_gate` 聚合），但 `holdings_analysis` 序列化（`:1220-1271`）**未拷贝该字段** → API 响应无 `composite_decision`；前端 `SignalPanel.vue:34` 渲染「🧮 综合信号」卡、`:60` 定义 `compositeDecision` prop，但**无任何父组件传值**（`AnalysisView.vue:48` 只传 `:indicator-data :signal :loading`，grep 确认全前端无一处向其传此 prop）。综合信号从计算到渲染全链路断裂，功能实际不存在。单测 `SignalPanel.r25.spec.js` 直传 prop 渲染通过 → 假绿（无测试验证父组件取数链路）。这违反 AGENTS.md「脚手架零容忍」。详见 §2.5。
- **P1（正确性/一致性）**
  3. **watchlist 列表 5s 超时退化 DB-only（R29，含超时根因，用户提问驱动）**：`routers/market.py:849` 对 `_watchlist_enrich_items` 设 5s 超时，冷缓存下整体 enrich 超时 → 回退 `:852-857` 的 DB-only 行（**无 realtime、无 realtime_unavailable、无 realtime_note**）→ 前端 `WatchlistPanel.vue:141/148/153` 最终 `v-else` 渲染「行情加载中」且**永不翻回**（除非某次成功）。R20「美股暂无实时」徽标在列表路径**永不出现**。实测 GET 5016ms、0/23 条带 realtime。**超时根因（三层，代码级事实）**：① 外部实时源限流/冷却——`get_realtime_batch` 冷却期实测 **7.4s**（撑破自身 2s 内层超时，`:641-642`）、HK/US per-item `_realtime_one` 单只 **8s**（`:616`）；② 代码格式不匹配（自选存 `"02800.HK"` 而批量返 `"02800"`，`:678-680`）→ 精确匹配 0 命中 → 健康标的误甩进 8s per-item 慢路径；③ **`resolve_symbol_to_code` 同步阻塞事件循环**（`:705-719`，仅对非法代码触发，但同步调用 `wait_for` 无法中断）→ 内外层超时（2s/5s）对其**全部失效** → 实测 **9-15s 卡死**（`:709-710`）。5s 外层超时是 round9 P0-4 事后熔断（防旧实现 29.9s），**不是病因**——病根是外部源慢 + 同步阻塞。修复（收盘快照兜底）见 §2.6 / §12.1 R29。
  4. **indices_meta/instruments 启动同步在容器内断裂（R30）**：`instruments_sync.py:29` / `indices_meta_sync.py:27` 用 `from scripts.sync_* import collect_all`，但 `backend/.dockerignore`（round9 P2-7）**把 `scripts/` 整个排除出镜像** → 容器内 `/app/scripts/` 不存在 → 启动同步**静默失败**（日志 `No module named 'scripts'`）。`sync_instruments.py`/`sync_indices_meta.py` 是**生产代码**（被 services 层 import），却与 `verify_e2e.py`/`check_routes.py` 等测试脚本同置于被 dockerignore 排除的 `scripts/` 目录。round14 P2-AG「恒生港股通系列进表」在容器内从未生效，搜索恒缺该系列。
  5. **R17 三桶 AI 摘要未达验收（R31）**：`enrich_news_summaries(cap=6)`（`market_data_hub.py:1932`）合并三桶后按重要性取前 6，headlines 恒占满 → macro 0/3、global 0/8 摘要。round24 R17 验收口径「三桶均有摘要覆盖」未满足。
  6. **冷态性能超标（R7 未实施，R32）**：sectors/heat 4.7s、indices/global 10.2s、stock-hot-rank 2.3s、etfs 2.0s、designs 875ms（热态全 <50ms）。预热未覆盖这些冷拉取路径。
  7. **预热 20s（R6 未实施，R33）**：`warmup_market_cache` 13.3s（`fetch_fund_nav` 10.8s + SSL do_handshake 4.3s 无 Session 复用 + macro 3s + news 8s）。F1/F2/F3/F3b 全部未实施。
  8. **LLM 跨任务限流预算缺失（R39，本轮实证 + code 复核修正）**：design 577 LLM 报告成功后 strategy-check 610 立即 429（`[rate-limited] 429 Too Many Requests`）→ 规则兜底。round23 F7/F8/F9 熔断（`llm.py:62`）+ F3-6 重试 + R5-1-6 诊断把「429 后降级」做完整。**修正原「背靠背无协调」表述**：design↔strategy_check 已被 `_design_semaphore=asyncio.Semaphore(1)`（`task_manager.py:46`，用于 `strategy_check_worker.py:73`/`task_manager.py:257-262`）**互斥串行化**，并非并发撞配额；但**无调用间隔冷却、无 token 预算**——信号量释放后下一任务在刚耗尽的配额上立即发起，且 `enrich_news_summaries`（`market_data_hub.py:1932`）**完全在信号量之外**独立发 LLM 调用。故「无跨任务配额协调」结论成立，机制描述需修正。第二次 verify_e2e 的 `llm-advice len=0`、`sector-analysis 空壳` 即 LLM 全链 429 空流印证。修复设计见 §2.8。
- **P2（治理/清理）**
  9. root perf 69（R9 未达标）、portfolio-analysis a11y 82（R10 未达标）（R34）。
  10. verify_perf.py symbol-analysis 用错路径（R35）——`/analysis/symbol/510050` 404 → 恒 0.00s 假 OK，性能软门禁盲区（同 R19「读错数据源」类）。
  11. 因子分极端值 + R3 残余（R36）：510300=-0.986、159338=-0.958、511090=+3.066 极端 z-score；`data_precision` 标注 coarse/bucket 但 `etfs[].factor_score` 与 `design_text` 表格仍精确小数。
  12. indices/global 返 0 条（盘后/冷却）（R37）。
  13. 临时残留文件（R38）：backend `_*.py`/`test_deepseek.py`/`apply_*.py` 20 个、logs `*.py` 60 个未跟踪 scratch。
  14. **盘后无动量注入：收盘快照"写了不读" + 首启空窗（R40，本轮新增设计）**：`get_sector_momentum()`（`market_data_hub.py:1652`）只返回内存缓存（120s TTL）或 `[]`，**从不读**已落盘的 `sector_momentum` 快照。写入侧 `_persist_snapshot_after_refresh`（`:1363`，as_of=15:30）在 `post_market/after_hours` 成功刷新后**已落盘** `sector_momentum` 快照，但读取侧缺失 → 盘后 120s 缓存超时、 live `compute_sector_momentum`（外部源）失败时，动量静默变为 `[]`。`market_data_hub.py:704` 注释已写明预期「盘后为空 → R26 快照兜底」，但 `pool` 快照有读取路径（`_load_pool_snapshot` `:900`），`sector_momentum` 快照**从未接读取兜底**（已知半途缺口）。**衍生子问题（用户提问）**：若**收盘后才首次启动**软件，磁盘上尚无快照；快照只在「成功刷新」时写入（`:940`→`:1363`），若首启 live 源即失败（率限/冷却，正是"盘后无动量"本因），则快照永远写不出 `[]`/缺失 → 兜底无物可兜底，首启盘后必定无动量。修复设计见 §2.3 / §12.1 R40。
  15. **近替代品冗余控制盘后被整体绕过 + 告警前端不呈现（R41，用户提问驱动）**：平衡型方案出现「芯片 + 半导体设备」「港股创新药 + 港股通创新药」同主题双入选——二者均为 `_SUBSTITUTE_FAMILIES`（`allocation_engine.py:716-719`）同族近替代品（单测 `test_round24_r24_correlation.py:39/52` 已断言应识别）。但 `near_substitute_pairs` 调用点（`allocation_engine.py:1618`）**嵌套在 `enforce_max_correlation` 内部**，而该函数只在 `if corr_matrix:` 时调用（`strategy_design.py:408`）。盘后/非交易窗口 `corr_matrix` 为空 → `enforce_max_correlation` 整函数不跑 → `near_substitute_pairs` 连带不跑（既不告警也不削权），仅留 `correlation_unchecked=True` 泛化标注。**讽刺点**：R24 设计 `near_substitute_pairs` 的初衷正是"独立于 K 线相关系数、降级盲（r=None）也能识别"（`allocation_engine.py:714-715`），结果它被门控在"必须有 corr_matrix"的调用里——**最该在盘后工作的控制恰好在盘后被关掉**。第二层：即便盘中触发，`risk_metrics.correlation_warnings`（含 near_substitute 条目）前端 `DesignResult.vue` **完全不渲染**（仅渲染 `correlation_unchecked` `:93-95`）→ 用户也看不到冗余提示（R28 类死输出）。第三层：`near_substitute_pairs` 仅为告警层、不自动合并/削权（`test_risk_controls.py:250` 注释"标注存在且不含被削减标的"）；子母主题（芯片=宽基底、半导体设备=子行业）双持=对设备段超配。修复设计见 §2.4 / §12.1 R41。

> **本轮方法论结论（第四次实证）**：①「测试绿」不足以证明「功能对」——R25 综合信号单元测试全绿（SignalPanel.r25.spec.js 直传 prop 渲染通过），但**无集成测试验证父组件是否传 prop** → 功能实际是死代码仍被判「已落地」；②「热态计时」系统性掩盖冷启动——热态全 <50ms、冷态 5 个 >1.8s，verify_e2e/verify_perf 默认测热态；③「性能软门禁读错数据源」——verify_perf symbol-analysis 路径错误恒 0.00s 假 OK，与 round24 T5/R19 同源。

### 0.4 验证窗口标注（D3）
本轮执行于 2026-08-16 00:00-00:30（北京时间，**周末盘后**）。以下结论含盘后/数据源冷却成分，**属「待交易时段（9:30-11:30/13:00-15:00）复测」项**，不得单独作为定论：强板块未入池（`strong_sector_pool_coverage=[]`/`sector_momentum=[]`）、`fund_flow=0`、`indices/global 0 条`、`factor_valid_rate=0%`。但「强板块未注入候选池」「因子分两路径口径矛盾」「watchlist 5s 退化」「scripts 启动同步断裂」均为**代码级结构事实**，不受窗口影响。

---

## 1. 预热性能诊断（PROFILE_WARMUP=1）

**产物**：`logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.html/txt`（本轮重跑，镜像 d72406e9b115）。

**实测（warmup_timing.json）**：
| 阶段 | 耗时 | 占比 |
|---|---|---|
| init_db | 46ms | 0.2% |
| redis_init | 83ms | 0.4% |
| warmup_global_indices | 6570ms | 33% |
| **warmup_market_cache** | **13306ms** | **66%** |
| warmup_etf_cache | 15ms | 0.1% |
| 合计 | ~20.0s | — |

**cProfile 根因（与 round24 §1 完全一致，F1/F2/F3/F3b 未实施故未改善）**：
- `fetch_fund_nav`（`china_market.py:1391`，10 次，**10.8s** 累计）——akshare `fund_open_fund_info_em` NAV 历史拉取。
- `requests.get` + SSL `do_handshake`（78 次，tottime **4.3s**）——**仍无 `requests.Session` 复用**，重复 SSL 握手。
- `fetch_macro_snapshot`（`macro_fetcher.py:353`，1.5s）+ `fetch_pmi_gdp`（`:249`，1.5s）——宏观 PMI/GDP 拉取。
- `fetch_macro_news`（`news_fetcher.py:407`，2.7s）、levistock `_fetch_page`（5.7s）——资讯拉取。

**pyinstrument**：`warmup_market_cache`→`get_portfolio_realtime` 5.2s（实时行情多源链）+ `_foreign`（`market_service.py:361`）3.9s（全球指数/外盘）。

**修复设计（= round24 R6，沿用 F1/F2/F3/F3b，见 §12 R33）**：不重复，直接引用 round24 §1。

---

## 2. 组合设计 577 + 场内策略检查 610（专业投资者视角）

### 2.1 组合设计 577（balanced / report_quality=full）
**结构工程良好 + round24 修复实证生效**：
- `degradation.mode="normal"`（pool 非空，数据源可达，与 round24 的 pool=0 不同）。
- ✅ **R2 生效**：`159338 中证A500`(强制锚) 权重 **5%/12.9%/15.75%**（round24 曾 1%）；correlation_warnings 注「双方均为强制锚…按豁免不削减」。
- ✅ **R3 生效**：`data_precision={mode:coarse, factor_missing_pct:100%, factor_score_display:bucket}`。
- ✅ **R24 生效**：near_substitute 双路检测（大盘宽基/半导体/医药生物族，含 correlation=-0.012 仍识别）；`correlation_unchecked=None`（降级不失明）。
- ✅ 报告含真实涨跌（通信 +3.60%、港股创新药 -2.51%、证券 -1.27%）、真实指数（上证 3927.18、沪深300 4665.88、情绪 36.6）、专业操作纪律（企稳判定/急跌加仓/止损红线/再平衡）。

**数据可信度硬伤（核心，P0）**：
- **因子分极端且两路径矛盾**：510300=-0.986、159338=-0.958（两个最核心宽基深负分），511090 国债=+3.066。design_text 表格仍呈现这些精确 z-score（-0.99/-0.96/3.07），与 `data_precision.factor_score_display=bucket` 矛盾（R36）。更严重的是**与策略检查「因子分 1.68（偏强）」方向相反**（R27，见 §2.2）。
- **R3 残余**：`data_precision` 标注 coarse/bucket，但 `etfs[].factor_score` 仍 `-0.9855288495104011` 精确小数、权重仍 `0.2067/0.0506/0.0497`（非 5% 档）。
- **强板块未进池**（`strong_sector_pool_coverage=[]`、`sector_momentum=[]`）——含盘后成分（D3），但 R1 注入点代码已落地（`market_data_hub.py:703-705`），盘后无板块动量可注入。
- **`data_as_of=None`**（R26 残余）：`session=closed` 已识别（`market_calendar` 接入生效），但 fresh weekend 容器从未写过快照 → `_snapshot_as_of_for()` 返 None，`valid_rate` 仍 0%（182/193 no_data）。

**专业判断**：框架可用、结构专业（三层/层预算/相关度告警/真实涨跌/操作纪律都在），**round24 的「强制锚击穿」「降级标注」「冗余控制」三大 P0 均已修复**。但**数据基础不足以支撑精确配置**——`valid_rate=0%` 下仍产出精确权重与「偏强/偏弱」因子评级，且同一标的在两屏因子分方向相反。

### 2.2 场内策略检查 610（on_exchange）—— 兜底透明化已达标，但 LLM 层本轮 429
- ✅ **R5 生效**：`llm_layer_ok=False`、`is_fallback=True`、`report_quality=fallback`，summary「LLM 分析超时（75s 未返回…[rate-limited] 429 Too Many Requests）」，report_text 首行「⚠️ LLM 分析超时/不可用，以下内容由规则引擎生成」。兜底可结构化识别。
- ✅ **R4 生效**：10 条建议全部 `confidence=medium`（语义标签，非 0.7）。
- ✅ **R21 生效**：reason「因子分 1.68（偏强）」替代裸「+8.97」。
- ✅ **R20 生效（单标的路径）**：holdings_analysis `tech_signal="HOLD，真实信号"`、`factor_availability 25/39`。
- ⚠️ **LLM 层 429（环境）**：design 577 刚消耗 DeepSeek 配额 → 策略检查 LLM 429 兜底。**本轮无法评估真实 LLM 报告质量**，但兜底透明化（R5）与规则建议质量已实证。
- ⚠️ **规则兜底 512000 券商「信号 sell」但 action=hold**（factor -0.01 未达 `<-0.5 AND signal=sell` 阈值 → 落「其余 hold」）——reason「信号 sell…维持现状」表面自相矛盾，投资者易误解（R27 关联：规则决策表 signal 与 action 的映射不透明）。
- ⚠️ **P0 因子分矛盾（R27）**：同一 `159338` 设计 composite **-0.958** vs 策略检查「因子分 **1.68（偏强）**」。根因已坐实（§0.3 P0-1，经 code 复核修正）：策略检查 `avg_factor` = 原始因子值（含 `china.policy.* +8.97` 等异构量纲原始值）的朴素均值（`portfolio_service.py:1662-1664`，函数 `_rule_based_suggestion` 起 `:1634`），KDJ 实际已 z 化取反、非主因；设计 composite = 截面 z-score 加权（`:623`）。两者共用「因子分」字样、量纲完全不同。修复设计见 §2.7。

### 2.3 盘后无动量注入：收盘快照「写了不读」+ 首启空窗（R40，本轮新增设计）

**现象**：盘后运行 `strategy_design` 四处 `get_sector_momentum() or []`（`:346/723/760/801`）全部为空 → 设计 / 强板块注入（`market_data_hub.py:703-712` 的 2.6 强板块动量注入候选池）拿不到板块动量，方案与市场热点脱节。

**根因（代码级结构事实，不受验证窗口影响）**：
1. **读取侧缺失（主缺口）**：`get_sector_momentum()`（`:1652`）只返回 `_sector_momentum_cache`（120s TTL）或 `[]`，**从不调 `_load_latest_snapshot_sync("sector_momentum")`**。写入侧 `_persist_snapshot_after_refresh`（`:1363`）在 `post_market/after_hours` 成功刷新后**已落盘** `sector_momentum` 快照（as_of 用 15:30）。即"写了不读"。
2. **对照 `pool` 快照有完整读取路径**：`_load_pool_snapshot()`（`:1386`）→ `_load_latest_snapshot_sync("pool")`（`:900`），盘后重启能读 T-1 池。但 `sector_momentum` 快照的读取兜底**从没接上**。
3. **注释已写明预期却未实现**：`market_data_hub.py:704`「读板块动量缓存（交易时段由 `_refresh_market_snapshot` 填充；**盘后为空 → R26 快照兜底**）」——兜底只给 `pool` 做了，`sector_momentum` 半途而废。属已知但未闭环缺口。
4. **首启空窗（用户提问衍生的子缺口，R40-b）**：快照**只在成功刷新时写入**（`refresh` 成功 → `:940` → `:1363` 守卫 `post_market/after_hours`）。若**收盘后才首次启动**软件，磁盘上尚无快照；若首启那次 `compute_sector_momentum`（外部 akshare 源）即失败（率限 / 数据源冷却——正是"盘后无动量"本因），则：
   - 缓存保持 `[]` → `_persist_snapshot_after_refresh` 把 `sm = get_sector_momentum() or []` = `[]` 落盘成**空壳快照**；
   - 读者兜底读到 `[]`，**无物可兜** → 首启盘后必定无动量，且快照被空壳污染。
   - 反之，若首启 refresh 成功且 akshare 返回当日收盘板块数据（日频板块涨跌盘后可得），快照正常写入 → 后续读取兜底能拿到。故"首启能否拿到"取决于首启那次 live 刷新是否成功，而非"是否盘后"。

**修复设计（实现就绪，不实施）**：
- **R40-a 读取兜底**：`get_sector_momentum()` 改写——① 缓存新鲜（<120s）直接返回；② 缓存过期/空**且** `market_session()` ∈ `post_market/after_hours`（或缓存从未填充）→ `_load_latest_snapshot_sync("sector_momentum")`，若快照 as_of 为**今日** 15:00/15:30 则返回并 `logger.info`（盘后注入收盘动量）；③ 盘中缓存失效**不**用快照（避免昨日收盘冒充盘中实时），保持 `[]` 触发既有降级。复用既有 `_load_latest_snapshot_sync`（`:85`），零新增原语。
- **R40-b 写入侧放宽 + 防空壳**：`_persist_snapshot_after_refresh` 的 session 守卫放宽——**只要 refresh 成功且 `sector_momentum` 非空即落盘**（不只 `post_market/after_hours`），使盘中/收盘任一时点成功刷新都留下 last-good 快照，封堵首启空窗；且**空 `[]` 不写快照**（避免空壳污染兜底）。读取侧仅在无 live 缓存时回退快照，故放宽写入不违反"快照盖过实时"意图。
- **验收口径**：① 单测（抓假负向）— mock 无 live 缓存 + 注入今日快照 → 盘后 `get_sector_momentum()` 必返回非空前两条；盘中同条件必返回 `[]`。② 真实链路 — 盘后重启 `restart.bat` 后跑 `verify_e2e` 设计链路，`sector_momentum` 非 `[]`、`strong_sector_pool_coverage` 非 `[]`。③ 首启空窗 — 清空快照表后盘后首启，refresh 失败场景快照不得为 `[]` 空壳（写侧守卫）。

### 2.4 近替代品冗余控制盘后被整体绕过 + 告警前端不呈现（R41，用户提问驱动）

**现象（用户实测）**：平衡型方案同时入选「芯片 + 半导体设备」「港股创新药 + 港股通创新药」——二者均为同主题近替代品，双持属主题集中而非分散。

**根因（代码级结构事实，不受验证窗口影响）**：
1. **调用被 corr_matrix 门控（主缺口）**：`near_substitute_pairs`（`:746`，文本/主题族匹配，独立于 K 线 r）调用点在 `allocation_engine.py:1618`，**嵌套在 `enforce_max_correlation` 函数内部**；而 `enforce_max_correlation` 只在 `if corr_matrix:` 时调用（`strategy_design.py:408`）。盘后/非交易窗口 `_correlation_matrix_for` 返空 → `corr_matrix` falsy → `enforce_max_correlation` 整函数不跑 → `near_substitute_pairs` 连带不跑（既不告警也不削权），仅留 `correlation_unchecked=True` 泛化标注（`:417`）。
2. **设计意图与实现矛盾**：R24 注释明写 `near_substitute_pairs`「独立于 K 线相关系数，**降级盲（r=None）也能识别**」（`allocation_engine.py:714-715`），但它被放在"必须有 corr_matrix"才执行的 `enforce_max_correlation` 里 → **最该在盘后/降级时工作的控制，恰好在盘后被关掉**。单测 `test_round24_r24_correlation.py:39/52` 断言的「科创芯片+科创半导体」「港股创新药+港股通创新药」近替代品识别，在交易窗口内能触发，在盘后窗口内完全不执行。
3. **告警前端不呈现（R28 类死输出）**：即便盘中触发，`risk_metrics.correlation_warnings`（含 `near_substitute` / `unevaluated` 条目）前端 `DesignResult.vue` **不渲染**——grep 确认该组件仅渲染 `correlation_unchecked`（`:93-95`），不渲染 `correlation_warnings` 数组。故用户即便在盘中拿到带近替代品告警的方案，也看不到冗余提示。
4. **仅为告警层、不自动合并**：`near_substitute_pairs` 只 `warnings.append`，不削权不合并（`test_risk_controls.py:250` 注释"标注存在且不含被削减标的"）。且 `enforce_max_correlation` 对 r≥0.9 才削权（`:1524`），而子母主题（芯片=宽基底、半导体设备=子行业）真实 r 常 <0.9 → 连高相关削减层也触发不了 → 双持完全无约束。

**修复设计（实现就绪，不实施）**：
- **R41-a 解耦门控**：把 `near_substitute_pairs` 调用从 `enforce_max_correlation` 内移出，作为**独立冗余控制层**在 `strategy_design.py` 的 risk-control 段始终执行（文本检测本就独立于 `corr_matrix`，应无条件跑）；`correlation_unchecked` 场景仍照常标注 `unevaluated`（r=None），但近替代品主题族识别不再依赖 corr_matrix。
- **R41-b 前端呈现**：`DesignResult.vue` 渲染 `risk_metrics.correlation_warnings` 中 `type ∈ {near_substitute, unevaluated}` 条目（如「芯片 / 半导体设备 同主题近替代品，建议保留其一」），与既有 `correlation_unchecked` 提示并列。
- **R41-c（可选增强，非必须）**：对同族近替代品在平衡/防御型中做**合并或留一**（保留流动性更好/更宽基的一只，或合并合计权重并打标），使冗余控制从"仅告警"升级为"实质性收敛"——进攻型可放宽但至少标注。
- **验收口径**：① 单测（抓假负向）— mock `corr_matrix={}`（盘后）跑 risk-control，`near_substitute_pairs` 仍返回「芯片+半导体设备」「港股创新药+港股通创新药」对，且不依赖 r。② 真实链路 — 盘后跑 `verify_e2e` 设计链路，三方案 `correlation_warnings` 含 near_substitute 条目；前端 `DesignResult.spec.js` 新增断言渲染该条目（负向：不渲染 → FAIL）。③ 单测断言 `enforce_max_correlation` 调用点不再包裹 `near_substitute_pairs`（解耦）。

### 2.5 综合信号前后端双断（R28，用户提问驱动复核）

**现象（用户提问）**：「之前说加综合信号，加在哪里了？」——经查，综合信号（composite_decision）后端已计算、前端已有 UI 卡片，但用户实际**看不到** → 整链路断裂。

**加在哪了（两个互不相通的点）**：
1. **后端：计算 + 挂内部对象（已做）**：`portfolio_service.py:1045` 调用 `_attach_composite_decisions(factor_breakdowns, data_quality)`（函数体 `:1521-1564`），对每只持仓的 `factor_breakdowns` 附 `composite_decision` 字典（技术+因子聚合，因子填充率<60% 标 `degraded`）；纯函数计算在 `app/analysis/signal.py` 的 `composite_signal_with_gate`（单测 `test_round24_r25_signal.py` 已覆盖降级门禁）。
2. **前端：UI 卡片 + prop（已做）**：`SignalPanel.vue:34` 渲染「🧮 综合信号」卡（含 `degraded` 降级徽标 / `signal` / `score`）；`:60` 定义 `compositeDecision` prop。

**为什么看不到（R28 双断死代码，根因）**：
- **断点 A — 后端不序列化**：`holdings_analysis` 序列化循环（`portfolio_service.py:1220-1271`）只从 `factor_breakdowns` 读 `factor_scores` / `technical_signal` 写进响应（`h["factor_summary"]` / `h["tech_signal"]`），**从不拷贝 `composite_decision`**（grep 确认循环内无 `composite_decision` 引用）→ API 响应无该字段。
- **断点 B — 前端无父组件传值**：`AnalysisView.vue:48` 只传 `:indicator-data :signal :loading` 给 `SignalPanel`，**从不传 `:composite-decision`**（grep 确认全前端 `views/`+`components/` 无一处向 SignalPanel 传此 prop）→ `compositeDecision` 恒 `undefined`，`SignalPanel.vue:34` 的 `v-if="compositeDecision && !loading"` 恒 false → 卡片永不渲染。

**测试假绿（违背反假完成机制）**：`SignalPanel.r25.spec.js` 直传 `compositeDecision` prop 渲染 → 单测绿；但**无集成测试验证「父组件是否从 API 响应取 composite_decision 并传给 SignalPanel」**——验证「组件能渲染」而非「数据链路通」，教科书级「测试绿+功能假」。

**修复设计（实现就绪，不实施；原归 批1 P0，见 §14）**：
- **R28-a（断点 A）**：`holdings_analysis` 序列化时从 `factor_breakdowns[sym]` 拷贝 `composite_decision` 入 `h`（与 `factor_summary`/`tech_signal` 同位置）；字段缺失时整字段不出现（不填默认，诚实降级）。
- **R28-b（断点 B）**：`AnalysisView.vue` 从 API 响应（holdings_analysis 每项或顶层 `composite_decision`）取出并 `:composite-decision="..."` 传给 `SignalPanel`；缺失时 prop 为 undefined（卡片不渲染，非空白冒充）。
- **R28-c（抓假集成测试）**：新增——mock API 响应含 `composite_decision` → 断言 `AnalysisView` 经 `SignalPanel` 渲染出「🧮 综合信号」卡；mock 响应**不含**该字段 → 断言卡片不渲染（负向：断点任一侧回退即 FAIL）。
- **验收口径**：① 单测 `portfolio_service` 断言 `holdings_analysis` 每项含 `composite_decision`（与 factor_summary 同路径拷贝）；② 前端 `AnalysisView.spec.js` 断言传 prop 且 `SignalPanel` 渲染（负向：不传 → FAIL）；③ 真实链路 浏览器走查持仓分析页可见「🧮 综合信号」卡（非空白/旧值冒充）。

---

### 2.6 自选列表「行情加载中」永不翻回：5s 超时退化 + 收盘快照兜底缺口（R29，用户提问驱动）

**现象（用户提问）**：「现在自选列表一直显示行情加载中，是不是也应该用收盘快照？」——经查，自选 GET 列表 0/23 条带 `realtime`，前端 `WatchlistPanel.vue:141/148/153` 落入最终 `v-else` 渲染「行情加载中」且**永不翻回**（除非后续某次 enrich 成功）。R29 根因是「5s 超时整体退化」，而非「未用收盘快照」——但收盘快照兜底**本可避免空窗**，这里确实缺失。

**为什么超时（三层根因，代码级事实）**：
- **① 外部实时源限流 / 冷却（主因）**：`get_realtime_batch` 冷却期实测 **7.4s**（`market.py:641-642`），撑破其自身 2s 内层超时；HK/US 单只 `_realtime_one` 实测 **8s**（`:616`）。冷缓存（首拉 / 长时间无请求）下源端冷却最严重。
- **② 代码格式不匹配（放大）**：自选存 `"02800.HK"`，批量刷新返 `"02800"`（`:678-680`）→ 精确匹配 0 命中 → 健康标的被误甩进 8s per-item 慢路径，拖累整体耗时。
- **③ `resolve_symbol_to_code` 同步阻塞事件循环（最隐蔽）**：`:705-719` 仅对非法代码触发，但其内部是**同步调用**，`asyncio.wait_for(timeout=2)` 无法中断它 → 内外层超时（2s/5s）对其**全部失效** → 实测 **9-15s 卡死**（`:709-710`）。这是「为什么 5s 超时仍卡 9-15s」的真凶。

**5s 外层超时的定位**：`market.py:849` 的 5s 超时是 round9 P0-4 的**事后熔断**（防旧实现 29.9s 整页卡死），**不是病因**——它只是把「卡 29.9s」变成「5s 后退化为 DB-only」，但退化行（`:852-857`）只回裸 DB 行，**无 `realtime`、无 `realtime_unavailable`、无 `realtime_note`** → 前端所有 `v-if`/`v-else-if` 落空 → 永久「行情加载中」。实测 GET 5016ms / 0/23 条带 realtime。

**收盘快照为何没兜住（缺口点）**：`_last_close_fallback`（`market_service.py:1316`，经 `fetch_history` 取 T-1 收盘、标 `is_estimated=True` + `as_of`）**本可做兜底**，但 `market.py:803` 仅对 `US/HK` 调用（`if _at in ("US","HK")`）→ **A 股超时 / 退化路径一律走 `_degraded`，不补收盘快照**。于是 A 股（自选主力）一旦超时即空白，而港股/美股即便有快照兜底也因 R20 源缺失/超时未必能取到；且退化主路径（`:852-857`）根本**没走 `_last_close_fallback`，只返裸 DB 行**。

**修复设计（实现就绪，不实施；归 批1 P1，见 §14）**：
- **R29-a（退化路径补收盘快照兜底）**：`_watchlist_enrich_items` 的 5s 超时回退行（`:852-857`）**不再返回裸 DB 行**——改为对每条 item 调用 `_last_close_fallback`（跨 A/HK/US，资产类型无关，已有实现），写入 `realtime`（含 `is_estimated=True`、`as_of=T-1 收盘`）；再加一层 5s-TTL 报价缓存（当前已有时序缓存，复用即可）避免每次冷拉。前端据此渲染「估」徽标（`WatchlistPanel.vue:127-131`，R20 机制）而非「行情加载中」。
- **R29-b（放开资产类型门控）**：`market.py:803` 的 `if _at in ("US","HK")` 放宽——**A 股超时也走 `_last_close_fallback`**（A 股同样有历史收盘可兜底，无理由排除）；`_last_close_fallback` 本就资产类型无关。仅当历史源也失败时再 `_degraded`（诚实降级，非空白冒充）。
- **R29-c（可选，根因消减）**：② 代码格式不匹配在 `:678-680` 做归一化（去掉 `.HK` 后缀或统一大小写）再匹配，避免健康标的误入慢路径；③ 将 `resolve_symbol_to_code` 同步调用包 `run_sync`/`to_thread`（AGENTS.md「async def ≠ 非阻塞」铁律），使 2s 超时**真实生效**，杜绝 9-15s 卡死。
- **验收口径**：① 单测（抓假负向）mock `get_realtime_batch` 超时 → 断言回退行 item 的 `realtime.is_estimated=True` 且 `realtime.as_of` 为 T-1 收盘、**非 `realtime: null`**；② 前端 `WatchlistPanel.spec.js` 断言超时场景下显示「估」徽标而非「行情加载中」；③ R29-c 落地后单测断言 `_resolve_symbol_to_code` 经 `run_sync` 包裹，2s 超时即中断（mock 慢同步 → 2s 内抛 `TimeoutError`，非 9-15s）。

---

### 2.7 因子分两路径口径矛盾（R27，code 复核修正 + 实施就绪）

**根因（修正，代码级事实，不受验证窗口影响）**：
- 设计路径：`factor_registry.compute()` 跨截面 z-score（`:1484`）→ `aggregate_factor_scores`（`app/core/factor_aggregate.py:50`，均值回复类因子 KDJ 取反）→ `allocation_engine.py:401-405` 分类加权求和 → `:623` `round(composite,3)`。159338 = **-0.958**。
- 策略检查路径：`_rule_based_suggestion`（`:1634`）`avg_factor`（`:1662-1664`）= `factor_scores` 字典**原始值朴素均值**，混入异构量纲原始政策因子（`china.policy.* +8.97`）→ 被拉正至 **+1.68**，再经 `:1738-1740` 内联分档映射为「偏强」。
- **原 doc「KDJ≈77 主导」不准确**：KDJ 已被 z 化取反（见 `:120` 注释），+1.68 主因是原始政策因子。两路径量纲/聚合口径不同却共用「因子分」字样 → 同标的方向相反。

**修复设计（采纳方案 a，实施就绪，不实施）**：
- `portfolio_service.py:1662-1664` 朴素均值替换为设计同源复合分：
  ```python
  from app.core.factor_aggregate import aggregate_factor_scores
  from app.factors.factor_registry import factor_registry
  def _design_style_score(fs: dict, pw=None) -> float:
      agg = aggregate_factor_scores(fs or {}, definitions=factor_registry._factors)
      pw = pw or {"technical": .3, "sentiment": .2, "momentum": .3, "valuation": .2}
      return float(sum(agg.get(k, 0.0) * w for k, w in pw.items()))
  avg_factor = _design_style_score(factor_score)   # 替换 :1662-1664
  ```
- `:1738-1740` reason 与决策阈值 `:1696-1733` 改用同 z 量纲；R21 `_factor_strength_band`（`:90-110`）仅喂 z 化复合分（禁止对异构原始值 mean 再分档）。
- **验收口径**：①单测：同标的 design 屏 `composite` 与 strategy_check `avg_factor` 方向一致（159338 两屏同负）；②集成：design_text 表格与 strategy_check 报告「因子分」数值同口径；③负向断言：禁止对 `china.policy.*` 等异构原始值直接 mean 冒充 z-score 强度。

### 2.8 跨任务 LLM 限流预算缺失（R39，code 复核修正 + 实施就绪）

**根因（修正，代码级事实）**：
- 现有层：`analysis/llm.py` per-provider 熔断 `_circuit`（`:62`，429→立即 OPEN，TTL 300s）、`llm_complete` 重试 `max_retries+1=3`（`:387`）、`_rate_limit_wait`（`:124`）、429→`RuntimeError`（`:494`）。模块级共享态 `_last_llm_error`（`:24`）已存在——但是**按 provider 的熔断态，非跨任务配额**。
- design↔strategy_check 已被 `_design_semaphore=asyncio.Semaphore(1)`（`task_manager.py:46`）互斥串行，**非并发撞配额**；但**无调用间隔冷却、无 token 预算**，信号量释放即发；`enrich_news_summaries`（`market_data_hub.py:1932`，`llm_complete(max_retries=0)` `:1175`）**在信号量之外**独立调用。故「无跨任务配额协调」结论成立，机制描述需从「背靠背并发」修正为「串行但无冷却/预算 + news 在圈外」。

**修复设计（集中式 LLMQuotaGate，实施就绪，不实施）**：
- 位置：`analysis/llm.py` 模块级单例（邻近 `_circuit` `:62`）：
  ```python
  class LLMQuotaGate:
      inter_call_cooldown = 8.0   # 任意两次 LLM 调用最小间隔（跨任务）
      quota_cooldown = 60.0       # 429 后全局暂停
      _last = 0.0; _exhausted_until = 0.0
      async def acquire(self, min_gap=None):
          gap = min_gap or self.inter_call_cooldown
          now = time.monotonic()
          wait = max(0.0, self._last + gap - now, self._exhausted_until - now)
          if wait > 0: await asyncio.sleep(wait)
          self._last = time.monotonic()
      def mark_exhausted(self, secs=None):
          self._exhausted_until = time.monotonic() + (secs or self.quota_cooldown)
  llm_quota_gate = LLMQuotaGate()
  ```
- 集成（三调用点零改动）：`llm_complete`（`:370`）/ `llm_complete_with_system`（`:724`）/ `llm_complete_stream`（`:500`）**入口** `await llm_quota_gate.acquire()`；`_is_429` 命中处（`:453`/`:825`）`mark_exhausted()`。design_report.py:524 / strategy_check_worker.py:138 / market_data_hub:1932 经公共层自动覆盖。`acquire` 保证任意两次 LLM 调用间隔 ≥ `inter_call_cooldown`、429 后全局 `quota_cooldown` 暂停（后续调用直落兜底不硬撞）。
- 前端：strategy-check 已有 `is_fallback`/`report_quality`（`strategy_check_worker.py:174-176`），增 `fallback_reason∈{rate_limited,timeout,error}`，限流显「⏳ 限流降级」（区别于红「分析失败」）；design WS（`design_report.py:618`）限流时传 `rate_limited:true`。
- **验收口径**：①单元：`LLMQuotaGate` mock 时钟断言间隔冷却 + 429 后全局暂停；②集成：背靠背 design→strategy-check 不再硬撞 429（或快速限流降级且前端显「限流」）；③`enrich_news_summaries` 受同一 gate 约束（grep 确认所有 LLM 调用经 `llm_complete*`）。

---

## 3. A/HK/US 行情分析全能力复验（步骤4）

| 能力 | 实测 | 结论 |
|---|---|---|
| 综合研判 `llm-advice/stream` | 200 / 31.7s / first_byte 25.1s / 1204 字，真实指数（上证+0.01%、创业板+1.12%、情绪 36.6） | ✅ 真实非模板 |
| 个股 `symbol-analysis/stream` 600519 | 200 / 21.7s / 2262 字，真实财报（PE 36.48、2026H1 营收 907 亿 +1.47%、归母净利 -1.95%、Q2 环比 -36%） | ✅ 真实深度 |
| 板块 `sector-analysis/stream` BK0735 | 200 / 71.5s / first_byte 56.9s / 2954 字（4814.94 点 -0.21%、涨 187/跌 314） | ✅（但 71.5s 极慢） |
| 概念 `sectors/concept` | 500 条（CPO +3.18%、F5G +3.09%） | ✅ |
| 指数 `indices/global` | **0 条** + 冷态 10.2s（sina 源冷却，warmup 已拉但端点返 0） | ⚠️ R37 |
| 搜索自动补全 A/HK/US | 银→30、茅台→600519、腾讯→3、apple→AAPL | ✅（UTF-8 正确） |

**专业判断**：能力全覆盖、内容真实（LLM 引用真实财报/指数/板块数据，非模板话术）。**唯一实质问题是延迟**：first_byte 25-57s（deepseek 流式生成，无进度心跳之外的可视化），与 §8 冷态性能同源。indices/global 0 条为盘后/冷却（D3），但 warmup 已拉取却返 0 需查缓存键口径（R37）。

---

## 4. 热点 / 自选 / 持仓技术分析（步骤5-6）

- **热点（步骤5）**：hot-plates 13 条（光通信 +2.88%，蓝盾光电「5天5板」）、sectors/heat 20 条（电子 565616.5，degraded=False）、stock-hot-rank 50 条——**全部加载成功且数值真实**。
- **自选（步骤5）**：POST 512480 → 201 带 realtime(1.077/+0.84%)；GET 22→23 条。**添加+获取+显示链路正常**。⚠️ **但 GET 列表 5s 超时退化 DB-only**（R29，见 §0.3 P1-3）：0/23 条带 realtime，US/HK 无「暂无实时」徽标。
- **持仓技术分析（步骤6）**：10 只 `/market/signal` 全部 `data_available=true` + `reasons` 非空（MACD/KDJ/RSI/MA/BOLL）。**F10 超买→hold 生效**（159516 J=94.2→hold、159992 J=82.9→hold、518880 J=82.9→hold、159338 KDJ 超买死叉→hold）。信号与理由自洽（MACD 金叉+MA 多头→buy 513120/159869；死叉+空头→sell 159545/512000）。⚠️ 中性区 RSI/KDJ 不出现在 reasons（510880/513010）——R25 caption 一致性问题仍在。

---

## 5. 资讯分级 + 因子模型（步骤7-8）

### 5.1 资讯（步骤7）
- ✅ **R16 生效**：global 8 条仅 2/8「other」（risk/positive/neutral/major 已分类），较 round24 7/8 大幅改善。
- ✅ **R15 生效**：macro 无「ETF日报」软文；⚠️ 仍混「宇树 IPO 被倒卖」「CPO 龙头资金净流入」等非宏观。
- ⚠️ **R17 未达验收（R31）**：`cap=6` 全被 headlines 独占，macro 0/3、global 0/8 `ai_summary`。
- ⚠️ 分类细节：「黎巴嫩谴责以色列袭击」→ `major` 而非 `risk`（地缘军事应 risk）。

### 5.2 因子模型页（步骤8）
- ✅ **R22 生效**：`/factors/active` 与 `/factors/model` avg_ic 均 **0.2121**（round24 曾 0.2134 vs 0.3221 分裂）。
- ✅ 诚实化：valid=0/no_data=27/static=11/significant=0、implemented=38/planned=155、zero_ratio（etf.tracking_error=1.0 缺 benchmark，其余 0）。
- ⚠️ 技术因子 `sample_count=3`（fresh 容器周末仅 3 天 K 线缓存）→ 全部 no_data（< min_samples 250）。诚实但揭示 R26「盘后数据变薄」仍未解（fresh 容器无快照可载）。

---

## 6. 前后端数据断裂排查（步骤9）

- ✅ `check_routes.py`：73 路由全 [OK]，「PASS: All routes match」。
- ⚠️ **字段级断裂 2 处（新发现）**：
  1. **watchlist realtime_unavailable（R29）**：前端 `WatchlistPanel.vue:135` 检查 `item.realtime_unavailable` 显示「暂无实时」，但后端 5s 超时回退（`market.py:852-857`）不提供该字段 → 前端 `v-else-if` 链落空，显示空白（用户误以为「无波动」）。
  2. **综合信号 composite_decision（R28）**：前端 `SignalPanel.vue:34` 期望 `compositeDecision` prop，后端 `holdings_analysis` 不序列化该字段，且前端无任何父组件传值 → 综合信号 UI 段恒不渲染。

---

## 7. round24 方案落地核验（步骤10）

| round24 项 | 状态 | 复验证据（本轮实测/代码） |
|---|---|---|
| R1 强板块注入 | ⚠️ 代码落地未实证 | `SECTOR_ETF_MAP`(:185)+注入点(:703-705) 在；盘后 sector_momentum=[] → coverage=[]（D3 待复测） |
| R2 强制锚豁免 | ✅ 生效 | 159338 5%/12.9%/15.75%（round24 曾 1%） |
| R3 数据精度降级 | ⚠️ 半落地 | data_precision coarse/bucket 元数据在；但 etfs[].factor_score/design_text 仍精确小数（R36） |
| R4 confidence 标签 | ✅ 生效 | 全 medium（非 0.7） |
| R5 llm_layer_ok | ✅ 生效 | llm_layer_ok=False/is_fallback=True/report_quality=fallback |
| R6 预热性能 | 🔲 未实施 | 预热仍 20s（§1） |
| R7 冷态性能 | 🔲 未实施 | 冷态 5 端点 >1.8s（§8） |
| R8 /news CLS | ✅ 生效 | CLS 0.001（round24 曾 0.2077） |
| R9 root perf | ⚠️ 未达标 | perf 69（<90，FCP 2.0s TBT 610ms） |
| R10 a11y | ⚠️ 未达标 | portfolio-analysis 82（<90） |
| R11 T5 CJK | ✅ 生效 | verify_e2e.py:60-81 json.loads 解出再判 |
| R12 冷态计时 | ✅ 落地 | verify_e2e 有冷/热区分（timeline 热态 5ms PASS） |
| R13 候选池 degraded | ✅ 落地 | verify_e2e 显式 degraded 断言 |
| R14 规则 confidence 断言 | ✅ 落地 | tests 覆盖 |
| R15 宏观过滤 | ✅ 生效 | macro 无 ETF日报 |
| R16 英文分类 | ✅ 生效 | global 2/8 other |
| R17 三桶摘要 | ⚠️ 未达验收 | cap=6 全被 headlines 独占（R31） |
| R18 死代码删 | ✅ 生效 | DELETE /designs/{id}、GET /market/sentiment 均 gone |
| R19 方案数检查 | ✅ 生效 | verify_e2e.py:1553-1569 读详情端点 |
| R20 美股自选无实时 | ⚠️ 半落地 | 单标的路径生效；列表 5s 退化 → 徽标永不出现（R29） |
| R21 因子值量纲 | ✅ 生效 | 「因子分 1.68（偏强）」替代裸值 |
| R22 avg_ic 统一 | ✅ 生效 | 两端点 0.2121 一致 |
| R23 news 锁 | ✅ 落地 | 未复现瞬态 0 |
| R24 冗余控制 | ✅ 生效 | near_substitute 双路检测 + 强制锚豁免 + correlation_unchecked=None |
| R25 综合信号 | ❌ **死代码** | composite_decision 前后端双断（R28） |
| R26 盘后快照 | ⚠️ 半落地 | 代码落地；fresh 容器无快照 → data_as_of=None、valid_rate 仍 0% |

**核验结论**：round24 R1-R26 中 **22 项生效/落地，1 项死代码（R25），3 项半落地（R3/R20/R26），2 项未实施（R6/R7），2 项未达标（R9/R10），1 项未达验收（R17）**。

---

## 8. 前端 Lighthouse（步骤11）

Lighthouse（node_modules/.bin/lighthouse + Chrome headless；首次 5/7 失败因 Windows temp 目录锁，清理 `%TEMP%/lighthouse.*` + `--disable-dev-shm-usage` 后全通）：

| 路由 | perf | a11y | best | seo | FCP | LCP | TBT | CLS |
|---|---|---|---|---|---|---|---|---|
| / | **69** | 96 | 96 | 91 | 2.0s | 3.3s | **610ms** | 0.001 ✓ |
| /market-analysis | 88 | 96 | 96 | 91 | 2.1s | 3.1s | — | 0.001 ✓ |
| /portfolio-analysis | 77 | **82** | 96 | 91 | 2.1s | 3.8s | — | 0.001 ✓ |
| /news | 99 | 95 | 100 | 91 | 1.5s | 1.9s | 60ms | 0.001 ✓ |
| /token-monitor | 89 | 92 | 96 | 91 | 2.0s | 3.2s | 170ms | 0.001 ✓ |
| /source-monitor | 90 | 96 | 96 | 91 | 1.9s | 3.2s | 150ms | 0.001 ✓ |
| /admin/config | 99 | 96 | 100 | 91 | 1.5s | 1.9s | — | 0.001 ✓ |

**结论**：
- ✅ **R8 已修**：/news CLS 0.2077 → **0.001**（全站 CLS 均 0.001）。
- ❌ **R9 未达标**：root perf 69（<90），FCP 2.0s、TBT 610ms——首屏 render-blocking JS 未根治（F4/F5 未实施）。
- ❌ **R10 未达标**：portfolio-analysis a11y 82（对比度不足，<90）。

---

## 9. 后端链路性能（步骤12，冷/热态区分）

| 端点 | 冷态 | 热态 | 判定 |
|---|---|---|---|
| /portfolio/timeline | 47ms | 16-47ms | ✅ |
| /admin/metrics | 31ms | 0-31ms | ✅ |
| /factors/active | 31ms | 0ms | ✅ |
| /news/headlines | 31ms | 0ms | ✅ |
| /portfolio/designs | 875ms | 0ms | ⚠️ 冷态 |
| /portfolio/etfs | **2016ms** | 31ms | ❌ 冷态 |
| /market/stock-hot-rank | **2328ms** | 188ms | ❌ 冷态 |
| /market/sectors/heat | **4735ms** | 31ms | ❌ 冷态 |
| /market/indices/global | **10198ms** | 580ms | ❌ 冷态 |
| /market/watchlist | **5005ms（恒）** | 5005ms（恒） | ❌ 恒 5s |

**结论（R7 实证）**：热态全 <50ms，冷态 5 个端点 >1.8s。watchlist **恒 5s**（enrich 5s 超时必然命中，与冷热无关）。根因：冷态触发实时数据懒拉取（sina 全球指数/东财板块/热榜/持仓 NAV），预热未覆盖。`verify_perf.py` 软门禁测热态 → 门禁永远绿、首用户永远慢。

---

## 10. 测试防护缺口分析（步骤13）

**为何现有测试体系未识别上述问题**：

1. **R25 死代码无集成测试拦截（本轮实证）**：`SignalPanel.r25.spec.js` 直传 `compositeDecision` prop 渲染 → 单测绿；但**无测试验证「父组件是否从 API 响应读取 composite_decision 并传给 SignalPanel」**。单元测试验证了「组件能渲染」，没验证「数据链路通」。这是「测试绿+功能假」的教科书案例——与 AGENTS.md 反假完成机制「测试要能抓假」直接相悖。
2. **verify_perf.py symbol-analysis 用错路径（R35，本轮实证）**：`verify_perf.py:83` 测 `/analysis/symbol/510050`（404）→ 恒 0.00s 假 OK。性能软门禁读错数据源，与 round24 R19「方案数读摘要列表端点」同源。
3. **watchlist 5s 退化无门禁**：`verify_perf` 对 watchlist 阈值 3s，但退化后 5.05s 仍只 WARN（软门禁不阻断）；且无断言「退化响应必须带 realtime_unavailable 徽标」。
4. **scripts 启动同步断裂无测试**：`indices_meta_sync`/`instruments_sync` 失败静默（non-fatal），无启动冒烟断言「indices_meta 表非空/同步成功」。
5. **冷态性能无测量（T9 残留）**：计时默认热态，冷态 4.7s/10.2s 无任何门禁触发。

---

## 11. 冗余/死代码（步骤14）

- ✅ 死端点已删（round24 R18）：`DELETE /portfolio/designs/{id}`、`GET /market/sentiment` 均 gone；`check_api_usage` 54 方法 0 unused；`audit_unused_symbols` 0 unused stock。
- ❌ **R25 综合信号前后端死代码（R28）**：前端 `SignalPanel.vue` compositeDecision prop+UI 无父组件传值；后端 `composite_decision` 未序列化进 `holdings_analysis`。整链断裂，违反「脚手架零容忍」。
- ⚠️ **scripts 模块 import 断裂（R30）**：`indices_meta_sync.py:27`/`instruments_sync.py:29` `from scripts.sync_* import`，容器内 `No module named 'scripts'`（`scripts/` 无 `__init__.py`），启动同步静默失败。
- ⚠️ **临时残留文件（R38）**：`backend/_*.py`+`test_deepseek.py`+`apply_*.py` 共 20 个一次性探针；`logs/*.py` 60 个未跟踪 scratch。
- 测试冗余：`docs/test-redundancy-audit-and-plan.md`（未跟踪）——33 早期 round 文件已折叠（a828fe9），round24(8) 待关闭后同流程折叠。

---

## 12. 修复方案总表（不实施）

> 复用 round24 已实施项不再重复；下表仅列**本轮新发现 + 残留**项。

### 12.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R27 | P0 | 因子分两路径口径矛盾：设计 composite z-score 加权（159338=-0.958，`allocation_engine.py:623`/`:401-405`）vs 策略检查 `avg_factor` 原始因子值朴素均值（含 `china.policy.* +8.97` 异构量纲）→「因子分 1.68（偏强）」，方向相反（KDJ 已 z 化取反、非主因） | **采纳方案(a)：策略检查改用与设计同源的 z-score 复合分**。`portfolio_service.py:1662-1664` 的朴素均值替换为 `aggregate_factor_scores(fs, definitions=factor_registry._factors)`（纯函数，`app/core/factor_aggregate.py:50`）分类加权求和（权重 technical .3/sentiment .2/momentum .3/valuation .2），与 `allocation_engine:401-405` 同口径；`:1738-1740` 策略检查 reason 与决策阈值 `:1696-1733` 同步改用同 z 量纲。R21 `_factor_strength_band`（`:90-110`）仅喂 z 化复合分，禁止对异构原始值取均值再分档。设计 `etfs[].factor_score`（z-score）与策略检查「因子分」口径对齐 | ①单测：同标的 design 屏 `composite` 与 strategy_check `avg_factor` 方向一致（159338 两屏同负/同正）；②集成：design_text 表格与 strategy_check 报告「因子分」数值同口径；③负向断言：禁止对 `china.policy.*` 等异构原始值直接 mean 冒充 z-score 强度 | `portfolio_service.py:1662-1664`/`:1738-1740`/`:1696-1733`/`:90-110`、`app/core/factor_aggregate.py:50`、`allocation_engine.py:401-405/:623`、`factors/factor_registry.py:1484` |
| R28 | P0 | R25 综合信号是前后端双断死代码 | ①后端：`holdings_analysis` 序列化补 `composite_decision`（从 `factor_breakdowns` 拷贝，`portfolio_service.py:1220-1271` 处）；②前端：`AnalysisView.vue:48` 或 StrategyCheckResult 从 holdings_analysis 读 `composite_decision` 传给 `SignalPanel :composite-decision`；③补集成测试：断言「API 响应 holdings_analysis[].composite_decision 存在」+「父组件传 prop」（而非仅测 SignalPanel 单组件） | 综合信号在 UI 实际渲染（非 v-if 恒 false）；集成测试能抓「未传 prop」 | `portfolio_service.py:1045/:1220-1271`、`SignalPanel.vue:34`、`AnalysisView.vue:48` |
| R29 | P1 | watchlist 列表 5s 超时退化 DB-only（无 realtime/无 realtime_unavailable 徽标），前「行情加载中」永不翻回 | **超时根因三层（代码级）**：①外部实时源冷却 `get_realtime_batch` 实测 7.4s 撑破 2s 内层超时（`:641-642`）、HK/US per-item 8s（`:616`）；②自选存 `"02800.HK"` vs 批量返 `"02800"` 格式不匹配（`:678-680`）→ 健康标的误入 8s 慢路径；③`resolve_symbol_to_code` 同步阻塞（`:705-719`）使内外层超时对其失效 → 实测 9-15s 卡死（`:709-710`）。5s 外层超时（`:849`）是 round9 P0-4 事后熔断、非病因。**修复**：**R29-a** 超时回退行（`:852-857`）改调 `_last_close_fallback`（已有，`market_service.py:1316`，T-1 收盘 + `is_estimated=True` + `as_of`），不再返裸 DB 行 → 前端显示「估」徽标（`WatchlistPanel.vue:127-131`）而非「行情加载中」；**R29-b** 放开 `market.py:803` `if _at in ("US","HK")` → **A 股超时也走收盘快照兜底**（逻辑本资产无关）；**R29-c（可选根因消减）** `:678-680` 代码格式归一化避免误入慢路径 + `resolve_symbol_to_code` 包 `run_sync` 使 2s 超时真实生效 | ①单测（抓假负向）mock enrich 超时→行 item `realtime.is_estimated=True` 且 `as_of=T-1 收盘`、非 `realtime:null`；②前端 `WatchlistPanel.spec.js` 断言超时场景显「估」徽标非「行情加载中」；③R29-c 落地后断言 `run_sync` 包裹使 2s 中断（非 9-15s） | `market.py:849/:852-857/:641-642/:616/:678-680/:705-719`、`:803`、`market_service.py:1316`、`WatchlistPanel.vue:127-131` |
| R30 | P1 | scripts 模块被 dockerignore 排除 → indices_meta/instruments 启动同步容器内静默失败 | ①`backend/.dockerignore` 移除 `scripts/` 行（但会把测试脚本带进镜像）；**推荐**②把生产依赖 `sync_instruments.py`/`sync_indices_meta.py` 从 `scripts/` 移到 `app/services/` 或 `app/fetchers/`，services 层改 `from app.fetchers.sync_instruments import ...`；③启动冒烟断言同步结果（非静默，失败 WARNING 升级） | 容器内 `/app` 无 `scripts/` 也能同步成功；日志无 `No module named 'scripts'`；搜索「恒生港股通」命中 | `backend/.dockerignore`、`instruments_sync.py:29`、`indices_meta_sync.py:27` |
| R36 | P2 | 因子分极端值 + R3 残余：`data_precision` 标注 bucket 但 etfs[].factor_score/design_text 仍精确小数 | ①`data_precision.factor_score_display=bucket` 时，LLM 报告 prompt 注入「因子分仅显强弱分档（强/偏强/中性/偏弱/弱），不显精确值」；②`etfs[].factor_score` 降级态改返区间或 bucket 字符串；③权重 5% 档真实化（0.2067→0.20） | 降级态报告/响应不再出现 -0.99/3.07 精确分；权重为 5% 档 | `strategy_design._build_market_context`、`design_report` prompt、`design-precision.md` |
| R40 | P1 | 盘后无动量注入（收盘快照「写了不读」+ 首启空窗）：`get_sector_momentum()`（`:1652`）只返内存缓存/`[]`，不读已落盘的 `sector_momentum` 快照（写入侧 `:1363` as_of=15:30 已存在）；`pool` 有读取路径（`:900`）而 `sector_momentum` 无；`:704` 注释预期「盘后快照兜底」未实现。衍生首启空窗：快照只在成功刷新时写（`:940`→`:1363`），首启 live 源失败则写 `[]` 空壳/缺失 → 兜底无物 | **R40-a** `get_sector_momentum()` 加读取兜底：缓存新鲜直接返；过期/空且 `post_market/after_hours`→`_load_latest_snapshot_sync("sector_momentum")`，as_of 今日 15:00/15:30 则返回；盘中失效不回退快照（保 `[]`）。**R40-b** `_persist_snapshot_after_refresh` 放宽 session 守卫：refresh 成功且 `sector_momentum` 非空即落盘（不只 post_market）；空 `[]` 不写防空壳。复用 `_load_latest_snapshot_sync`（`:85`） | ①单测（抓假负向）盘后无 live 缓存+注入今日快照→返回非空前两条；盘中同条件必 `[]`；②盘后重启 `verify_e2e` 设计链路 `sector_momentum`/`strong_sector_pool_coverage` 非 `[]`；③清空快照表后盘后首启，refresh 失败场景快照不为 `[]` 空壳 | `market_data_hub.py:1652`、`:1363`、`:1386`、`:85`、`market_data_hub.py:704` |
| R41 | P1 | 近替代品冗余控制盘后被整体绕过 + 告警前端不呈现：平衡型「芯片+半导体设备」「港股创新药+港股通创新药」同主题双入选（均 `_SUBSTITUTE_FAMILIES` 同族，`test_round24_r24_correlation.py:39/52` 已断言应识别）；但 `near_substitute_pairs`（`:1618`）嵌套在 `enforce_max_correlation` 内，后者只在 `if corr_matrix:` 调用（`strategy_design.py:408`）→ 盘后 `corr_matrix` 空 → 整层跳过（仅留 `correlation_unchecked`）。设计意图「降级盲也能识别」与实现「门控在 corr_matrix」矛盾。且 `correlation_warnings` 前端 `DesignResult.vue` 不渲染（仅 `:93-95` 的 `correlation_unchecked`）→ 告警死输出。近替代品仅告警不合并 | **R41-a** 把 `near_substitute_pairs` 调用移出 `enforce_max_correlation`，作为独立冗余控制层在 `strategy_design.py` risk-control 段**始终执行**（文本检测本独立于 corr_matrix）；`correlation_unchecked` 场景仍标 `unevaluated`。**R41-b** `DesignResult.vue` 渲染 `correlation_warnings` 中 `near_substitute`/`unevaluated` 条目（与 `correlation_unchecked` 并列）。**R41-c（可选）** 平衡/防御型对同族近替代品做合并或留一（保留宽基/流动性更好者），从"仅告警"升级为"实质收敛" | ①单测（抓假负向）mock `corr_matrix={}` 跑 risk-control，`near_substitute_pairs` 仍返回两对且不依赖 r；②盘后 `verify_e2e` 三方案 `correlation_warnings` 含 near_substitute，`DesignResult.spec.js` 新增断言渲染该条目（不渲染→FAIL）；③单测断言 `enforce_max_correlation` 调用点不再包裹 `near_substitute_pairs` | `allocation_engine.py:1618`、`:746`、`:716`、`strategy_design.py:408`、`:417`、`frontend/src/components/design/DesignResult.vue:93` |

### 12.2 性能

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R32 | P1 | 冷态性能超标（R7 未实施）：sectors/heat 4.7s、indices/global 10.2s、stock-hot-rank 2.3s、etfs 2.0s | 预热覆盖冷拉取路径（板块热度/热榜/全球指数/持仓 NAV）；或首呼异步 + skeleton | 冷态 ≤1s（或首呼有 loading 态） | `market_refresh.py`、`market_service.py`、`main.py` 预热 |
| R33 | P1 | 预热 20s（R6 未实施） | 沿用 F1/F2/F3/F3b：Session 复用 + gather 并发 + NAV 降精度 + 宏观后台化 | 预热 ≤15s、market_cache ≤8s | `china_market.py`、`macro_fetcher.py`、`main.py` |
| R39 | P1 | 跨任务 LLM 限流预算缺失（修正：design↔strategy_check 已 Semaphore(1) 串行，但无冷却/预算；`enrich_news_summaries` 在信号量外） | **采纳集中式 `LLMQuotaGate` 单例**（模块级，置于 `analysis/llm.py`，贴近现有 `_circuit` 熔断 `:62`）：①在 `llm_complete`（`:370`）/ `llm_complete_with_system`（`:724`）/ `llm_complete_stream`（`:500`）入口 `await llm_quota_gate.acquire()`；②`_is_429` 命中处（`:453`/`:825`）`llm_quota_gate.mark_exhausted()`。**三调用点零改动**（design_report.py:524 / strategy_check_worker.py:138 / market_data_hub:1932 自动覆盖）。`acquire` 保证任意两次 LLM 调用间隔 ≥ `inter_call_cooldown=8s`、429 后全局 `quota_cooldown=60s` 暂停（后续调用直落兜底不硬撞）。③前端对 strategy-check 增 `fallback_reason∈{rate_limited,timeout,error}`，限流显「⏳ 限流降级」（区别于红「分析失败」）；design WS（`design_report.py:618`）限流时传 `rate_limited:true` | ①单元：`LLMQuotaGate` 单测（mock 时钟）断言间隔冷却 + 429 后全局暂停；②集成：背靠背 design→strategy-check 不再硬撞 429（或快速限流降级且前端显「限流」）；③`enrich_news_summaries` 受同一 gate 约束（grep 确认所有 LLM 调用经 `llm_complete*`） | `analysis/llm.py:62`(邻近新增类)/`:370`/`:724`/`:500`/`:453`/`:825`、`task_manager.py:46`、`strategy_check_worker.py:138`/`:73`、`design_report.py:524`/`:618`、`market_data_hub.py:1932` |
| R34 | P2 | root perf 69（R9）、portfolio-analysis a11y 82（R10） | 首屏 critical CSS 内联 + render-blocking JS 消除 + portfolio 对比度修正 | root perf ≥90、a11y ≥90 | `vite.config.js`、`index.html`、`PortfolioAnalysis.vue` |

### 12.3 测试防护

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R35 | P1 | verify_perf symbol-analysis 用错路径 → 恒 404 假 OK | 路径改为 `/analysis/symbol-analysis/stream`（POST SSE 测首包） | symbol-analysis 真实测到延迟（非 404） | `verify_perf.py:83` |

### 12.4 资讯质量 + 治理

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R31 | P2 | R17 cap=6 全被 headlines 独占，macro/global 0 摘要 | cap 改为**分桶配额**（headlines/macro/global 各 N 条，如 3/2/1），或重要性排序时跨桶均衡 | 三桶均有 ai_summary | `market_data_hub.py:1932` |
| R37 | P2 | indices/global 返 0 条（盘后/冷却） | 查 warmup 拉取后缓存键口径（warmup 已拉但端点返 0）；盘后走 last-good/快照兜底（R26 协同） | 盘后 indices/global 有 T-1 数据或显式降级标注 | `market_service.py`、`market_data_hub` |
| R38 | P2 | 临时残留文件 20+60 个 | backend `_*.py`/`test_deepseek.py`/`apply_*.py` 删或移 `scripts/scratch/`；logs `*.py` 移 `scripts/scratch/` 或 gitignore 确认 | 无一次性探针残留 | 见 §11 |

---

## 13. 多轮 review 记录

- **Round 1（自检，本次完成）**：16 项动作全部执行，形成 §0-§12。核心「证伪」：① round24 R1-R26 22 项实证生效；② **R25 综合信号死代码**（前后端双断，新发现 P0）；③ **因子分两路径口径矛盾**（R27，新发现 P0）；④ watchlist 5s 退化 + realtime_unavailable 徽标永不出现（R29）；⑤ scripts 启动同步容器内断裂（R30）；⑥ verify_perf symbol-analysis 假 OK（R35）；⑦ **LLM 跨任务限流预算缺失**（R39，design 背靠背 strategy-check 恒 429）。

- **Round 2（独立 agent 复核，本次完成）**：委托独立 `general-purpose` agent 对照代码逐条复核 R27/R28/R29/R30 四个 P0/P1 证据链。结论：
  1. **R27 证据链准确**（微瑕：设计侧实为「z-score 加权复合分」而非纯 z-score，已修订措辞）；
  2. **R28 证据链准确**（`composite_decision` 调用点 `portfolio_service.py:1045`/函数体 1521-1564，holdings_analysis 后处理 1220-1271 未拷贝；前端 `compositeDecision` 仅 SignalPanel.vue + 测试，AnalysisView.vue:48 未传值）；
  3. **R29 证据链准确**（`market.py:849` 5s 超时 + `:852-857` 回退无 realtime_unavailable）；
  4. **R30 根因 agent 判断错误**：agent 认为「PEP 420 命名空间包无需 `__init__.py`，import 不会断」。但实测容器内 `/app/scripts/` **根本不存在**（`docker exec ... ls /app/scripts` → No such file），`find_spec('scripts')` 返回 None。**真根因**：`backend/.dockerignore`（round9 P2-7）把 `scripts/` 整目录排除出镜像，而 `scripts/sync_instruments.py`/`sync_indices_meta.py` 是生产代码（被 services 层 import）。已据实重写 R30（根因=.dockerignore 排除，修复=把生产依赖移出 scripts/ 或改 import）。

- **Round 3（R30 根因二次实证，本次完成）**：`docker exec` 容器内 `python -c "find_spec('scripts')"` → None；`ls /app/scripts` → No such file；`backend/.dockerignore` 含 `scripts/` 行。三证闭环坐实 R30 真根因（非 import 语义、非 __init__.py，是镜像构建排除了生产依赖目录）。此亦解释为何「恒生港股通」系列搜索在容器内恒缺——同步逻辑从未在容器内跑起来过。

> **当前状态：Round 3 完成，达到实施标准。** 修复设计 R27-R41 均具备准确 `file:line` 证据 + 验收口径；R30 经两轮纠错（agent 误判 → 实测坐实）；R40/R41 为用户提问驱动的盘后缺口（R40 收盘快照读取+首启空窗、R41 近替代品冗余控制盘后绕过+告警前端不呈现）。等待「开始实施」指令。

---

## 14. 分三批实施建议（不实施，等待指令）

- **批1（P0 数据可信度）**：R27（因子分口径统一）、R28（综合信号接通）、R29（watchlist 超时退化：收盘快照兜底 + 放开 A 股门控，见 §2.6 / §12.1 R29；R29-c 同步阻塞根因消减可选并入）。
- **批2（P1 正确性/性能）**：R30（scripts 移出 dockerignore 依赖）、R32（冷态性能）、R33（预热）、R35（verify_perf 路径）、R39（LLM 跨任务限流预算）、**R40（盘后无动量注入：收盘快照读取兜底 + 首启空窗）**、**R41（近替代品冗余控制盘后绕过 + 告警前端不呈现）**。
- **批3（P2 治理）**：R31（三桶摘要）、R34（root perf/a11y）、R36（R3 残余）、R37（indices/global）、R38（临时文件清理）。

> **当前状态：等待「开始实施」指令，不写任何修复代码。**（R27-R41 设计就绪）

---

### 14b. 关联批次：Round26 前端走查缺口（2026-08-16，用户提问驱动，独立 doc）

用户「标的分析 / 自选 / 指数」走查报告 7 个现象，根因收敛为 3 类：**搜索/补全索引不全**（`indices_meta` 仅 632 条 US=7/HK=63、无运行时兜底；`instruments` HK=0/US=0）、**港股 K 线一致性校验误剔**（已定位 `market_service.py:1463` 把区间 high 与实时价比对→腾讯/阿里/小米/美团 chart 误丢，平安/建行不触发）、**快速选项写回缺陷**（Q5）。经 4 轮 review 全部达实施标准（精确到行 + 验收 + 测试断言），文档 **`docs/round26-search-autocomplete-data-gaps.md`**。与 R30/R37 同源（同步覆盖不足）。

---

## 15. 独立复核复审记录（2026-08-16，本轮 review，不实施）

> 本节为对 §0-§14 文档的**独立多轮复审**（区别于原 §13 自审），目的是把文档从「自认达实施标准」推到「经 code 抽查实证、无未决设计方向」的真正实施就绪。原 §13 的自审曾判定 R27-R41 全部就绪，本轮复审发现其中 **R27、R39 两项实为「设计方向」而非「可实施」**，已修正并升级。

- **Round 1（通读 + 逐条就绪度评估）**：15 项 R27-R41 中，R28/R29/R35/R38/R40/R41 已含精确 file:line + 验收 + 测试断言，达实施标准；**R27、R39 仍停留在「设计方向」（多选项未决 / 机制描述与 code 不符），未达实施标准**；其余 R30/R31/R32/R33/R34/R36/R37 为 P2 或性能软门禁项，偏笼统但可接受。
- **Round 2（code 抽查 + 未就绪项补设计）**：
  - 独立 agent 深挖 R27：确认 `avg_factor` 实际在 `portfolio_service.py:1662-1664`（原 doc 写 `:1662` 差 2 行）、函数 `_rule_based_suggestion` 起 `:1634`；**纠正「KDJ≈77 主导」为「原始政策因子 `china.policy.* +8.97` 主导」**（KDJ 已 z 化取反）。设计侧复合分 `allocation_engine.py:623`/`:401-405`、输入 z 化 `factor_registry:1484`。→ 采纳方案(a) 统一为 z-score 复合分，新增 §2.7 + 重写 §12.1 R27。
  - 独立 agent 深挖 R39：确认 design↔strategy_check 已被 `_design_semaphore=asyncio.Semaphore(1)`（`task_manager.py:46`）串行化（原 doc「背靠背无协调」不准确），但无冷却/预算且 `enrich_news_summaries` 在圈外；现有 `_circuit` 熔断在 `llm.py:62`。→ 采纳集中式 `LLMQuotaGate` 单例包最低公共层，新增 §2.8 + 重写 §12.2 R39。
  - 自 grep 抽查 R40/R41 file:line：`get_sector_momentum:1652`/`_persist_snapshot_after_refresh:1363`/`_load_pool_snapshot:1386`/`_load_latest_snapshot_sync:85`（R40 全对）；`_SUBSTITUTE_FAMILIES:716`/`near_substitute_pairs:746`/`enforce_max_correlation:1490`/`near_substitute_pairs(allocs)` 调用 `:1618`（R41 全对）。声明准确，无需改。
- **Round 3（统一验收口径 + 去矛盾）**：§2.7/§2.8 与 §12.1/§12.2 已对齐（R27 方案(a)、R39 LLMQuotaGate 在总表与细节节一致）；原 §0.3/§2.2/§12.1 中 R27 的 KDJ 误述与 R39 的「背靠背」误述已修订。无残留矛盾。
- **Round 4（design-checklist D1-D8 合规终检）**：

| 项 | D1 探针 | D2 证据链(file:line) | D3 验证窗口 | D4 非兜底 | D5 真实调用点 | D6 四态 UI | D7 复杂度审计 | D8 已知模式 |
|---|---|---|---|---|---|---|---|---|
| R27 | 复用 factor_registry z-score 跑同标的 | 1662-1664/1738/1696-1733/90-110、factor_aggregate:50、allocation:401-405/623、factor_registry:1484 | 否（代码级） | 是（用真实 z 复合） | design / strategy_check 两路径 | — | 纯函数复用，无新 IO | 量纲混用 |
| R28 | — | 1045/1521-1564/1220-1271、SignalPanel:34、AnalysisView:48 | 否 | 是（接通非兜） | grep 确认双断点 | 卡片 v-if | 序列化+传 prop，无 IO | 死代码 |
| R29 | 实测 7.4s/8s/9-15s | 849/852-857/641-642/616/678-680/705-719/803、market_service:1316 | 否 | 是（收盘快照真源） | `_last_close_fallback` 已存在 | 估徽标四态 | 缓存复用 | 超时退化 |
| R30 | docker exec 三证 | .dockerignore、sync_*.py:27/29 | 否 | 是（移生产依赖） | services 层 import | — | 移目录+改 import | dockerignore 误排 |
| R39 | — | llm.py:62/370/724/500/453/825、task_manager:46 | 否 | 是（限流直落兜底） | 三 LLM 调用点经公共层 | 限流徽标 | gate 单点无新 IO | 配额耗尽 |
| R40 | 测快照读写 | 1652/1363/1386/900/85/704 | 是（盘后） | 是（读真快照） | `_load_latest_snapshot_sync` | — | 复用既有原语 | 首启空窗 |
| R41 | 双持实测 | 1618/746/716/408/417、DesignResult:93 | 否 | 是（解耦+渲染） | risk-control 段/前端 | 告警渲染 | 解耦无新 IO | 门控矛盾 |

> **当前状态（Round 1-4 完成）**：R27、R39 已由「设计方向」升级为「实施就绪（精确 file:line + 修复片段 + 验收 + 测试断言）」；R28/R29/R30/R35/R38/R40/R41 经抽查 file:line 准确、设计就绪；R31-R34/R36/R37 为 P2/性能软门禁项，描述笼统但非阻断。本文档**不写任何修复代码**，等待「开始实施」指令。
