# round29 容器重建 + 全量验收与优化方案（2026-08-19）

> 本文档为 round28 R56-R67 及「代码健康 + 巨型文件拆分」方案全部实施后的**新一轮 Docker 重建 + 16 项全量验收**结论与剩余问题修复设计。
> **本文档仅设计修复方案，不实施**（R75 主根因已于 `13839b3` 落地；R81 前端缺陷例外：2026-08-19 会话中定位后直接修复，见 §14.5 / §16 Round 9）。依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」撰写。
> 验证环境：Docker Desktop Engine 29.7.2 / Compose v5.4.0，prod profile 重建启动，后端 :8000 / 前端(nginx) :80；`PROFILE_WARMUP=1`（预热诊断，`docker-compose.diag.yml` override）。后端镜像 `b01ec96cd6c2`、前端 `5b55e189d243`。
> 验证窗口：2026-08-19 00:53–01:20（北京时间，**周三凌晨盘后**）。盘后/数据源冷却成分见 §0.4。

---

## 0. 执行摘要

### 0.1 本轮性质
round28 的 R56-R67 已在 `6935ac9` + `3807497` + `76b15ef` 实施；「代码健康 + 巨型文件拆分」方案已全批次实施并 push。本轮用**全新 Docker 镜像 + 16 项动作**复验落地情况，识别出**「修复已落地但运行时目标未达成」的残留问题**。

**核心结论：round28 的 R56/R57/R61/R62/R63/R67/R50 已真正生效；但 R58/R59/R60 三项「修复」因共同根因——「K 线缓存冷（进程重启清空内存缓存 + R59③ 落盘从未生效，数据源本身盘后可用——Round 8 实测证伪『源不可用』）」——而运行时结果与修复前相同或仅部分改善。这是一个「前置条件未满足 → 级联失效」的系统性问题，非单个修复点的 bug。**

### 0.2 验证动作与结果
| # | 动作 | 结果 |
|---|---|---|
| 1 | Docker 构建 + 回收老镜像 | ✅ 新镜像 backend `b01ec96cd6c2` / frontend `5b55e189d243`，老镜像被同名 tag 替换回收 |
| 2 | 预热性能诊断（PROFILE_WARMUP=1） | ⚠️ 预热序列 19.8s（round28 为 39.4s，R56 双重执行已消除）；但墙钟 56.5s（IC 回填等待 + K 线缓存建库空转）仍超 30s 预算 |
| 3 | 组合设计 + 场内策略检查（on_exchange） | ❌ **设计仍超时失败**（R59 降级路径触发但 K 线冷建库仍超时）；策略检查完成但 **LLM 仍超时**（103.6s，R57 内层 15s→60s 已生效，但配额节流 + JSONDecodeError 仍落规则兜底） |
| 4 | A/HK/US 行情分析全能力 | ⚠️ AI 投顾/茅台/腾讯内容高质量；**港股 00700 整链已可用**（R61 生效）；**A 股 600519 技术面仍空**（R60 依赖冷缓存失效）；美股 AAPL `DATA_UNAVAILABLE`；板块 BK1036「暂无数据」 |
| 5 | 热点 + 自选 | ✅ 热点加载成功（真实数据）；自选 add/fetch/display 全通（409 去重、is_estimated 兜底） |
| 6 | 持仓技术信号 | ✅ 信号 data_available + reasons 自洽；⚠️ score 口径不透明（MACD偏多+MA多头 → hold -0.5） |
| 7 | 资讯分级 + 智能分析 | ⚠️ R65 规则摘要生效（headlines 7/12 非 null）；⚠️ 分类欠分类（自然灾难/市场波动/地缘 → other level 1）；⚠️ stars 公式与文档不符 |
| 8 | 因子模型页 | ❌ **仍 valid=0/no_data=27**（R58 回填放弃——K 线缓存 3 次重试后仍冷）；factor_ic_records 4→6 个 distinct trade_date，远未达 ≥60 |
| 9 | 前后端断裂排查 | ✅ R62 生效（00700→HK/AAPL→US）；⚠️ 策略检查「因子数据缺失 66.7%」vs factor_availability「26/39 已填」标签矛盾 |
| 10 | round28 落地核验 | 7 项生效（R56/R57/R61/R62/R63/R67/R50）、3 项级联失效（R58/R59/R60）、2 项部分（R64/R65）、1 项待复测（R66） |
| 11 | 前端 Lighthouse（4 路由） | ✅ news CLS 0.198→0.029（R63 生效）；⚠️ portfolio a11y 82→86 仍 <90（R64 部分）；root perf 74 / portfolio 77 仍 <90 |
| 12 | 后端链路性能（冷/热） | ✅ 热态全 <0.21s（除 concept）；❌ **sectors/concept 36.8s 冷 / 17.1s 热**（persistent）；sectors/industry 20s 冷；watchlist 5.9s 冷 |
| 13 | 测试防护缺口分析 | ⚠️ 「盘后数据源失败 → K 线缓存冷 → 级联失效」集成场景无测试拦截（§5） |
| 14 | 冗余代码 | ✅ 历史清理全落地（BE-1~6/BP-1~13/R67/R50）；当前干净（backend 根仅 conftest.py、15 个合法脚本、10 个归档、210 测试文件） |
| 15 | 综合结论 + 修复方案 | 本文档（R68-R84 修复设计，R75/R81 已落地） |
| 16 | 回收容器 + 归档 + commit/push | 见 §16 与结尾 |

### 0.3 问题分级（本轮新发现，危害驱动）
- **P0（投资判断/数据可信度）**
  1. **R68 — 「K 线缓存冷」级联失效（R58/R59/R60/R77 的共同根因）**：**归因修正（08-19 实测）：数据源盘后可用（fetch_history 240 rows / push2delay 200）**，真正失效点是「进程重启清空内存 K 线缓存 + R59③ 落盘从未生效（`data/kline_cache.json` 不存在）→ 冷缓存期因子全空」→ 四个下游修复全部失效：①IC 回填 3 次重试后放弃（R58）→ 因子模型仍 27 因子 no_data；②组合设计 K 线冷建库超时（R59）→ 设计失败；③symbol-analysis K 线兜底取空（R60）→ 600519 技术面「K线为空」；④组合设计「100%现金」失败（R77，本地复盘新增，见 §2.5）。**「方法已应用但目标未达成」的典型——修复代码在、测试绿，但运行时结果与修复前相同。**
   1b. **R77 — 组合设计「100%现金」失败（R68 第 4 下游症状 + 潜伏缺陷触发）**：`backend/logs/backend.log` 实证 task 571-582（08-18 15:52-16:08 收盘后）+ task 597（08-19 11:33 午休）共 9 次报 `分配引擎未输出有效ETF标的：所有方案均为100%现金`。失败链路：数据源故障（`run_sync queue depth=17-18 POOL SATURATION`、`threadpool_main returned empty → cooling`）→ 因子数据全空 → `get_factor_matrix()` 返回 `{"510300":{},...}`（真值 dict，内层全空）→ `factor_matrix_empty=False` 静态池兜底被绕过（`strategy_design.py:305` 只判外层）→ 引擎 0 分仍选出 4 只 core → `risk_controls.py:160-193 remove_stale_candidates` 把每个 ETF 判「no price/return data」**全删**（无全删保护）→ 三方案全 CASH → `task_manager.py:370` 报错。**引入时间**：`remove_stale_candidates` 于 commit `e727001`（2026-07-20）引入、`factor_matrix_empty` 于 `9b1fa2e`（2026-07-31）引入，均为**潜伏缺陷**；报错首次出现 08-18 15:52，旧日志（backend.log.1/.2/.5）0 次——触发条件「池非空 + 因子全空」由 R68（进程重启清空 K 线缓存 + 落盘未生效 + 线程池饱和，非源不可用——Round 8 归因修正）首次同时满足，非新写代码。
- **P1（正确性/性能）**
  2. **R69 — 组合设计仍超时失败（R59 目标未达成）**：设计 595 走完「off-hours 降级（R59⑤）→ skip_refresh 重试（R59②）」全链，仍在数据采集阶段 90s 超时（`task 595 timed out`）。根因：skip_refresh 只跳过 `refresh()`，但后续 `get_history`/K 线采集仍逐一走 tickflow（429），单标的 500 根 K 线串行/并发受限 → 冷建库 >90s。R59③（K 线缓存落盘 `data/kline_cache.json`）已实现但**该文件从未被成功生成**（见 R68），故冷启动无缓存可加载。
  3. **R70 — 策略检查 LLM 仍不可见（R57 生效但配额节流）**：R57（内层 `connect=15s→60s`）已生效——LLM 从 15s `CancelledError` 变为 103.6s 才放弃。但最终失败原因是 `JSONDecodeError`：`opencode_zen` 配额耗尽 429 → 全局暂停 60s + DeepSeek 每次调用被 `llm_quota_gate` 节流 5.7-6.5s → 103.6s 内未能完成 JSON 结构化输出。专业投资者仍拿不到 AI 策略检查报告，但**换了一个失败原因**（配额节流而非连接超时）。
  4. **R71 — sectors/concept 端点 36.8s 冷 / 17.1s 热（persistent 性能债）**：**归因修正（Round 13 复核，两点分开）**——①**端点热路径** `get_sector_concept`（`hub/_sector.py:113`）→ `fetch_concept_sectors`（`sector_fetcher.py:240`：levistock → akshare `stock_board_concept_spot_em` → 名称补充 `_ak_concept_sectors_v2`），主源**已缓存 60s**（`core/ttl.py:26` `sector_concept`），但**补充源 `_ak_concept_sectors_v2()`（`sector_fetcher.py:259`）在 `cached()` 之外、每请求必跑**（主源结果 <60 条即触发 `stock_board_concept_name_em` 全量拉取）→「热态」17s 由此而来；②**预热 45.7s THS 热点（cProfile）来自 `_background_indices_meta_sync`（`main.py:238-245`，120s 预算）**，非端点——`sync_indices_meta_table()` → `sync_indices_meta.py:102/129` 的 `ak.stock_board_industry_index_ths`/`stock_board_concept_index_ths`（各 ~600 条），且走 `asyncio.to_thread`（主线程池）与请求争池。**原「THS 概念板块未缓存、每次请求全量拉取」表述不准确**——THS 不在 `/sectors/concept` 热路径，概念主源有 60s 缓存，真正的洞是「补充分支未入缓存」+「后台索引同步占主池」。
  4b. **R79 — 市场综合研判「国内流动性：本次数据未提供国内利率信号」——双层断裂（采集未接线 + 源超时）**：用户反馈驱动（2026-08-19 午间）。①**结构性（主因）**：`llm_context.py:199-207` 采集 `ctx["domestic_macro"]`（LPR/中美国债/M0-M2/CPI-PPI/PMI-GDP 六源，20s 预算），但 `llm_report_stream`（`analysis.py:309-389`）只取 regime/sentiment/market_data/indices/commodities/news，**从不读 domestic_macro**；`_build_report_prompt`（`reports.py:140-207`）签名无该参数，全 prompt 无任何国内利率数据（`macro_news` 也传空列表，`analysis.py:387`）——而模板第 3 章（`reports.py:186`）明确要求「国内流动性：货币与利率信号」。全后端 grep `domestic_macro` 仅 llm_context（生产者）/macro_fetcher（源）/测试，**0 生产消费点**——「采集了没接上」死数据；LLM 写「未提供」是诚实表现。②**数据源层**：日志实证 `backend.log` 08-18 14:43/15:35/22:03 三条 `build_full_context partial errors: ['domestic_macro: ']`（空错误 = `asyncio.wait_for` 20s 超时）→ `{"unavailable": true}`（`llm_context.py:206`）；5 个 akshare 源整包 20s 拉不完，且各带 1h 失败缓存。**即便修好注入，源也常超时——两层都要修。**
  4c. **R80 — 市场综合研判行情数据与最新数据对不上（多缓存域 + 静默旧值 + 无 as_of）**：用户反馈驱动。报告内「A股市场」指数来自 `_index_realtime_cache`（`_refresh_market_snapshot` 60s 后台刷新，`market_data_hub.py:526`）→ `get_global_indices`（30s 缓存）；「主要标的行情」来自 `get_all_realtime()`（`market_service.py:108` → `fetch_index_realtime`，15s per-request 缓存）；页面「最新数据」走独立请求 + WS 15s 推送——**同一指数三条独立通路、时效窗口不同**，报告内可自相矛盾、报告 vs 页面更必然有时差。**静默旧值**：`_refresh_market_snapshot` 失败分支（`market_data_hub.py:615-618`）仅 `if cache is None: = []`——旧值无失效标注保留；`get_index_realtime()`（`hub/_realtime.py:8-10`）无 TTL 检查；报告 builder `_build_market_overview`（`reports.py:107`）`idx.get('price','N/A')` **不读 `available` 字段**、无「数据截至 XX:XX」标注——旧值/None 被当当前行情写进 prompt。当日日志显示 `_index_realtime_cache` 正常刷新（08-19 11:19，17 条）、无刷新失败 → 主因是**快照 vs 实时时效差** + 报告内缓存域不一致 + 无 as_of 标注，而非大规模源故障。
  10. **R78 — 自选股列表「非交易时段无行情（数据源维护中）」——源全部可用，请求自毁式并发（2026-08-19 12:43-12:47 本地复验，午休窗口）**：用户反馈 A 股自选最新价/涨跌幅/成交量全显示「数据源维护中」。实测**证伪「源不可用」**：单发 `fetch_a_stock_batch` 0.25s/4行、sina 1.33s、tencent 1.02s、tickflow 1.26s、sina_history 0.06s/240行；熔断器 mootdx/sina/tencent/sina_history/push2delay 全 closed；池空闲时 watchlist API **3.81s 返回全量真实行情**。真凶是**请求自身四层自毁机制**：①**批量超时泄漏孤儿任务**——`_batch_for` 2s `wait_for` 超时只取消 await，底层 `run_sync` future 不取消（`async_utils.py:116-118` `run_in_executor` 无法中断同步任务），HK/US 批量 gather 的 N×`get_asset_realtime`（内部超时 8-15s）继续占 64-worker 池 8-15s；②**背景刷新争池**——sector 每 60s / regime 每 120s / news / IC series 与请求争抢线程池，日志实锤 `run_sync queue depth=9→22 (fn=fetch_history) POOL SATURATION!`（12:43:16 / 12:44:51）；③**收盘兜底 22 路并发洪泛**——`_watchlist_close_fallback`（`market.py:1033` `asyncio.gather`）同一秒向 money.finance.sina.com.cn 发 12+ 并发 K 线请求 → Sina 限流返回 **200 空体**（日志 `getKLineData?symbol=sh510500 200 None`，单发探针 0.06s/240 行）→ 全 None；④**quote TTL 不一致**——`get_realtime_batch` 批量成功只写 5s TTL（`market_service.py:1029-1031` `_QUOTE_TTL["A"]=5`），24h last-good（`_LAST_GOOD_TTL`）仅 `get_asset_realtime` per-item 路径写（`:1380`），批量失败后 per-item 又被 `_skip_markets` 跳过 → last-good 从未建立 → miss。另：enrich 循环内 `_last_close_fallback` 顺序执行无单条超时（每条内部预算 8-10s）→ N 只自选必撞 5s 外层 → 已算出的部分 good 数据被 TimeoutError 整体丢弃；`_last_close_fallback` 成功时也丢 `change_pct`/`volume`（`:1464-1465` 恒 None，K 线 rows 里 prev close 与 volume 本可算）。**间歇性根因**：12:34/12:44 撞上 sector 刷新（12:44:52 `update_sector_cache`）→ 5.8s 超时；12:47 池空闲 → 3.81s 成功——同一请求成败取决于池子那一刻是否被后台刷新占用。
  11. **R81 — 港股板块热度「AI 分析」报「请输入标的代码或名称」（前端 externalTrigger 写错搜索实例，2026-08-19 用户反馈驱动）**：港股「板块热度」tab 行点「🤖 AI 分析」报空输入错误。链路：`SectorHeatMap.vue:206` emit `{mode:'sector', query, name}` → `MarketAnalysis.vue:71` 设 externalTrigger → `UnifiedAnalysis.vue:310` watch 置 `activeMode='sector'` 后**只写回 `search.searchQuery`（symbol 实例）**，而 `doAnalyze()`（`:384`）读的是 `activeSearch.searchQuery`（sector 模式 = `sectorSearch`，恒空）→ 命中 `:387`「请输入标的代码或名称」。**同 round26 Q5 `quickSelect` 缺陷类（当时已修 `:325` 用 `activeSearch.value.searchQuery`），externalTrigger 路径漏修**。后端对 HK 板块本有 Phase 5.1 友好提示（`analysis.py:517-533`「当前市场暂无板块分析数据，请切换到 A 股」），但前端空输入守卫抢先报错，掩盖了真实行为。**已修复**（`UnifiedAnalysis.vue:314` 改 `activeSearch.value.searchQuery`）+ 2 回归用例，31 前端测试 + build 全绿（§14.5）。
  12. **R82 — 美股自选「暂无实时」——US 实时批量 2s 窗口短于 twelvedata 实际延迟（2-6s），批量超时后整组跳过 per-item，全 US 降级（2026-08-19 13:5x 实测复现，用户反馈驱动）**：用户反馈美股自选（AAPL 等）最新价有值但涨跌幅/成交量「暂无实时」。实测 watchlist 响应 3.88s：TSLA/QQQ/SPY `src=stale` 三字段全值（无 unavail 标记）、AAPL `price=310.03 chg=None vol=None is_estimated=True realtime_unavailable=True`。链路：①`_batch_for("US")` 批量超时 **2s**（`market.py:776`），而 twelvedata 从当前网络实测 **2-6s/次**（日志 13:53:37 建连 → 13:53:39-43 才响应；13:56:50 建连 → 13:56:51 批量已超时取消）→ 批量必超时（`market.py:785` WARNING `[watchlist] US batch realtime failed` 实证）；②批量失败 → `_skip_markets` 含 US（`market.py:821-830`）→ **8s per-item 兜底（`market.py:751`，本可容纳 twelvedata 延迟）被整组跳过** → 所有 US realtime=None；③降级链（`market.py:941-965`）：quote-cache(5s TTL) 命中 → stale 全值（TSLA/QQQ/SPY 态）；未命中 → `_last_close_fallback` 只回 price（`market_service.py:1461-1466` chg/vol 恒 None、`is_estimated=True`）→ `realtime_unavailable=True`（AAPL 态）；收盘兜底再失败（tickflow 429）→ realtime=null + `_degraded` → 三列全「暂无实时」；④前端 `WatchlistPanel.vue:135-159`：`realtime_unavailable` 且字段缺失 → 「暂无实时」。**附带 bug**：批量被 `wait_for` 取消后 `get_asset_realtime` 在 `market_service.py:1259` 抛 CancelledError，`:1374-1380` 的 last-good 写入不执行 → AAPL 每次请求都重新退化（last-good 缓存永远建立不起来）。**放大因素**：首测 watchlist **27.6s**——取消的 `asyncio.to_thread` 任务（twelvedata `_TIMEOUT=10s`）无法中断、继续占线程池，fallback 排队（同 R78③ 孤儿任务机制）。**额度盘点**：twelvedata **800次/天**（宽裕）慢、finnhub **60次/分**（紧）快（实测 ~1s、200 OK、`X-Ratelimit-Remaining:59`）但在 `_route_us`（`market_service.py:1388-1426`）排第二，2s 窗口内轮不到；tickflow 免费层限流 429。**「finnhub 前置」不可取**：4 只美股按 5s 刷新 ≈ 48/min 撞 60/min 上限，只是把配额烧在最快的源上。**修复设计（配额优先，见 §14.1 R82）**：方案 A 放宽 US 批量窗口 2s→7s + 外层联动、保持 twelvedata 主源；方案 B 快返回 + 后台刷新；方案 C twelvedata `/quote` 逗号分隔批量端点（计费方式需探针）；护栏 finnhub `X-Ratelimit-Remaining` 配额感知。
- **P2（治理/呈现）**
  5. **R72 — 资讯分类欠分类**：`哥伦比亚强震已致304人死亡`（自然灾难，契约应 major=5）、`欧洲股市录得去年末以来最长连跌`（市场利空，应 ≥3）、`俄方：瑞典扣留涉俄货船`（地缘，应 ≥4）均被判为 `other`（level 1）。本地关键词分类器未覆盖「强震/连跌/扣留」等场景。
  6. **R73 — 资讯 stars 公式与文档不符**：headlines 多条 level=1 条目 stars=5，与契约 `stars = min(level + freshness, 5)`（level 1 + freshness ≤2 → stars ≤3）矛盾。**归因修正（Round 13 复核）**：非「实现有隐藏 boost」——`_compute_stars`（`news_fetcher.py:228-240`）是 **round9 P2-1 刻意解耦设计**：stars=纯新鲜度（<1h→5★、<6h→4★、<24h→3★、<72h→2★、更旧→1★），与 level 完全无关；**是契约过时且自相矛盾**（`api-contracts/news/all.md:84` 写 `min(level+freshness,5)`、同文件 `:3` v3.0 写「stars 纯语义化=level」、`classification.md:16` 写「新鲜度维度」——三处互相打架）。**修复方向 = 更新契约对齐实现（新鲜度口径）**，非改实现；且 R83 已采纳移除徽章数字星 → 展示影响消失，R73 降为「契约文档对齐」（P3）。
  7. **R74 — 策略检查因子口径标签矛盾**：`summary="因子数据13/13正常"` vs `composite_decision.reason="因子数据缺失 66.7%"` vs `factor_availability={"filled":26,"total":39,"ratio":"26/39"}`——「13/13 正常」「缺失 66.7%」「26/39 已填」三者口径互斥，专业投资者无法判断因子数据真实可用性。
  8. **R75 — 组合设计/策略检查在「IC 回填 CPU 饱和」期间请求被抢占**：IC 回填（R58）CPU 循环独占事件循环期间，`GET /tasks/{id}` 轮询请求超时（实测 75.6s）。R58 的已知性能债（回填慢 ~10s/compute）在冷启动 + 设计并发时放大为可用性事故。**已修复（2026-08-19，commit `13839b3`）**：根因 = `compute()` 内 per-symbol 同步循环调用 `run_in_thread(get_advance_decline)`（`future.result()` 同步阻塞事件循环），回填 500 次 compute 累计冻结 loop ~16min。修复 = advance_decline 改 `compute()` 开头 `await run_sync` 单次获取 + 60s TTL 模块缓存注入每只 symbol，删除同步阻塞分支。验证：/health 50s+→6ms、indices/global 17-19s→25ms、386 factor 测试通过。**剩余可选优化（不阻塞）**：回填时光回溯循环每 N 次 compute `await asyncio.sleep(0)` 让出 + 低优先级，见 §14.2。
  9. **R76 — A 股个股中文名搜索（茅台）返回 0 结果**：`instruments` 表 A 股个股 0 条（数据缺口），搜索完全依赖 levistock 降级 `get_all_stocks`，**空结果静默**（`market.py:415-435` 仅异常打 WARNING、空返回不打）→ 「茅台」搜不到 600519。
  13. **R83 — 资讯徽章显示抽象（用户反馈驱动，2026-08-19）：`[4 其他]` 混排两个正交维度**：新闻卡徽章（`NewsView.vue:85-86`）将 `stars`（新鲜度数字：4=<6h，`news_fetcher.py:228`）与 `category`（分类文字「其他」）塞在同一徽章。数字「4」须知道映射表才可读（用户第一反应误为数组序号/重要程度），且与顶部「最低重要性筛选」按钮的 `★★★★ 重要`（`NewsView.vue:46`）视觉撞车——「4」极易被误读为重要程度 4 级，实际二者是解耦维度。更本质的冗余：新鲜度的原始信息就是 `time`，meta 行已显示绝对时间（`NewsView.vue:101`），数字星是时间的二次编码，重复且更抽象。**已采纳方案 1（用户决策）**：徽章只留 category 彩色文字标签（重大/利好/利空/风险/提醒），`other` 类不显示标签（灰色左边框+灰标题已表意）；meta 行时间改相对时间（`3小时前`/`刚刚`，悬浮 title 显示精确时间）；数字星彻底移除。设计见 §14.3 R83。
  14. **R84 — 美股标的搜索 TQQQ 无自动补全（用户反馈驱动，2026-08-19）**：美股「标的分析」输入 `TQQ` 无任何补全（实测 `GET /market/search?keyword=TQQ&market=US&include_stocks=true` → `[]`；QQQ/SPY/AAPL 正常）。三级搜索全断，其中**含一级错误推断修正**：①静态基座 `HKUS_ETF_MAP`（14 只美股 ETF，`market_service.py:610-641`）+ `HKUS_STOCK_MAP`（18 只个股，`:644-660`）为 curated 列表，**无 TQQQ**；②EM spot `fetch_us_spot_list`（`china_market.py:1037-1088`，akshare `stock_us_spot_em`）**双重失败**——网络层：`72.push2.eastmoney.com` 实测 16 页仅 5 页成功（约 70% 页 `RemoteDisconnected`，间歇性断连而非域名不可达），而 `push2delay.eastmoney.com` **16/16 页全通**（换域名可修稳定性）；**数据层（此前错误推断的修正）：`fs=m:105,m:106,m:107` 为纯股票列表，实测 Q 区整个缺失、T 区 100 只（TEMD→TBF）无 TQQQ/TLT、S 区无 SPY/SOXL——EM 美股 spot **从来不含 ETF**，换域名/等网络恢复对 TQQQ 均无效**；③instruments US 段 0 行——同步失败：`sync_instruments.py:276-281` 新浪美股 JSONP 解析**假设数组 `callback([...])`，实际返回对象 `CallbackList[]({...})`** → `raw.find("[")` 取到 `CallbackList[]` 的空 `[]` → `JSONDecodeError` → 降级链从未生效（每轮直落 `RuntimeError`「美股段全部数据源不可用」）；且该接口每页固定 20 条、按市值降序，前 6 页 120 只也不含 TQQQ。**关键新发现**：新浪 suggest `suggest3.sinajs.cn/suggest/type=41&key=TQQQ`（0.1s）**含 ETF 且命中 TQQQ**（「纳斯达克指数ETF-ProShares三倍做多」）、SOXL/SPXL/QQQ 全中，GBK 编码，天然前缀匹配，当前代码 **0 引用**——可用作搜索兜底源。修复设计见 §3.2 / §14.3 R84 / §15。

### 0.4 验证窗口标注（D3）
本轮执行于 2026-08-19 00:53–01:20（**周三凌晨盘后**）。以下结论含盘后/数据源冷却成分，属「待交易时段复测」：AAPL 整链 DATA_UNAVAILABLE、600519 技术面 K 线空（R60）、A 股个股搜索空（R76）、组合设计超时（R69）、IC 回填放弃（R68）。但「sectors/concept 热态 17s（R71）」「策略检查因子口径矛盾（R74）」「资讯分类欠分类（R72）」「stars 公式不符（R73）」「预热墙钟 56.5s 超预算（R68 前半）」均为**代码级结构事实，不受窗口影响**。R79/R80（08-19 午间用户反馈驱动，午休 12:43 前后）同理：根因为代码级结构事实（采集未接线、多缓存域、无 as_of、不读 available），不受交易窗口影响；其中 R80 的时效差幅度在交易时段放大、盘后各源收敛于 last-good 值（差异被掩盖）。**R82（08-19 13:5x 复现，美股自选「暂无实时」）同理**：根因为「批量超时窗口（2s）vs 源实际延迟（2-6s）不匹配」的结构事实——延迟是网络路径决定（twelvedata 境外源），非交易时段决定；盘中 twelvedata 延迟可能因源负载变化而异，但 2s 窗口对 2-6s 延迟始终偏紧，「暂无实时」降级不依赖交易窗口。附带验证：finnhub 200 OK 与 `X-Ratelimit-Remaining` 观测同样不受交易窗口影响。**R84（08-19 美股搜索 TQQQ 补全缺失，用户反馈驱动）同理**：根因为代码级/数据层结构事实——EM 美股 spot（`fs=m:105..107`）纯股票不含 ETF（Q 区缺失为全量分页实测，与交易时段无关）、72.push2 间歇断连与 push2delay 稳定性为网络路径实测、sync 新浪 JSONP 解析 bug 为静态代码缺陷——均不受交易窗口影响；新浪 suggest type=41 兜底源的可用性（含 ETF 命中）为同环境实测，无需交易时段复测。

---

## 1. 预热性能诊断（PROFILE_WARMUP=1）

**产物**：`logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.txt/html`（本轮镜像 `b01ec96cd6c2`）。

**实测（warmup_timing.json，总耗时 19766.2ms）**：
| 阶段 | 耗时 | 占比 | 备注 |
|---|---|---|---|
| init_db | 49.9ms | 0.3% | |
| redis_init | 71.2ms | 0.4% | |
| warmup_etf_cache | 24.8ms | 0.1% | |
| **warmup_global_indices** | **6707.3ms** | 34% | **单次执行（R56 已修复，round28 为 18.4s 双重）** |
| **warmup_market_cache** | **12913.0ms** | 65% | 行情缓存预热，仍为最大项 |

**墙钟对照**：`warmup_timing.json` 序列合计 19.8s，但日志 `[warmup-budget] 预热总耗时 56.5s 超过预算阈值 30.0s`。差异来源：`_backfill_ic_history_task` 等待 K 线缓存（`_wait_for_kline_rows` 20s+30s+60s+120s 退避）与 `refresh_kline` 冷建库空转，两者不在 timing 三阶段内但占用 lifespan 墙钟。

**根因（代码级，本轮实证）**：
- **R56 ✅ 已修复**：`warmup_global_indices` 仅 1 条记录（6707.3ms），round28 的「独立 task + sequence 内重复」双重执行（18.4s）已消除。
- **R68 K 线缓存冷建库空转**：pyinstrument 显示 `_backfill_ic_history_task → _wait_for_kline_rows → sleep 13.4s`（在等 K 线缓存就绪，但缓存从未就绪）；cProfile 显示 `requests.get` 102.9s 累计（245 次网络调用，大量 tickflow 429）。
- **CPU 热点（cProfile，57s 总）**：
  | 热点 | 累计 | 说明 |
  |---|---|---|
  | akshare `stock_board_concept_index_ths` | 45.7s | 概念板块 THS 全量拉取（单次调用） |
  | akshare `demjson.py:decode` | 25.6s | 纯 Python JSON 解析器（round28 已识别，`ETF_FAST_JSON=1` shim 未默认启用） |
  | `_ipv4_getaddrinfo` | 12.5s（313 次） | 强制 IPv4 DNS 解析，每个新 host 首次 ~2-4s |
  | `fund_open_fund_info_em` | 9.7s | 基金净值同步 |
  | `_fetch_us_list` | 9.5s | 美股列表拉取 |

**修复设计**：见 §7.2（R68/R71）。

---

## 2. 组合设计 + 场内策略检查

### 2.1 组合设计（本轮仍超时失败，R69）
`POST /design-async {"capital":500000}` → task 595，148s 后 `status=failed`、`error_message="方案生成超时，数据源响应过慢"`。

**日志时间线**（`docker logs`）：
- `00:57:28 [strategy_design] off-hours + pool cached — skipping realtime refresh, using last-good pool (R59⑤ off-hours degrade, 36 by_code)` — R59⑤ 生效，用 last-good 池。
- `00:59:14 [design_pipeline] task 595 data collection timed out after 90s — retrying with skip_refresh degrade (R59②)` — 数据采集仍 90s 超时。
- `00:59:14 [strategy_design] skip_refresh=True — using last-good/snapshot pool (R59② degrade retry)` — 降级重试启动。
- `00:59:41 GET https://api.tickflow.org/v1/klines?symbol=159570.SZ ... 429 Too Many Requests`（多次）— K 线逐标的走 tickflow，被限流。
- `00:59:55 [design_pipeline] task 595 timed out` — 降级重试仍超时。

**根因**：R59② 的 `skip_refresh=True` 只跳过 `refresh()`（扫描 + 池刷新），但设计链后续仍需为选中 ETF 逐一采集 K 线（`get_history` → tickflow），盘后 tickflow 429 限流 → 冷建库 >90s。R59③（K 线缓存落盘 `data/kline_cache.json`）代码在（`hub/_kline.py:175 _persist_kline_cache_sync`），但 `data/kline_cache.json` 文件**从未被生成**（`ls data/kline_cache.json` → No such file），因为 `_persist` 仅在 `refresh_kline updated>0` 时触发，而 `refresh_kline` 从未成功过（R68）。

### 2.2 场内策略检查（on_exchange，13 只持仓，R70）
策略检查 task 596 完成（约 114s），但 `llm_layer_ok=false`、`is_fallback=true`、`report_quality="fallback"`。

- **summary**：`LLM 分析超时（104s 未返回，已用规则引擎兜底）（市态：震荡；因子数据13/13正常）`
- **coverage ✅**：`{total_holdings:13, covered_by_llm:0, covered_by_rule:13, coverage_pct:1.0}` — R57 的 coverage 字段已透传（round28 缺失）。
- **R57 ✅ 生效**：日志 `[strategy_check] LLM analysis interrupted after 103.6s (timed out or cancelled: JSONDecodeError)` —— 从 round28 的「15s CancelledError」变为「103.6s JSONDecodeError」，内层 `connect=60s` 已生效，外层 180s 预算已能触达。
- **R70 根因（配额节流）**：日志链 `opencode_zen quota-exhausted → OPEN` + `llm_quota_gate throttling LLM call by 57.4s/5.8s/6.0s...` —— DeepSeek 每次调用被节流，103.6s 内未能完成 JSON 结构化输出 → JSONDecodeError → 规则兜底。
- **R74 因子口径矛盾**（见 §8）：
  - `summary="因子数据13/13正常"`
  - `holdings_analysis[0].factor_availability={"filled":26,"total":39,"ratio":"26/39"}`（即 66.7% 已填）
  - `holdings_analysis[0].composite_decision.reason="因子数据缺失 66.7%：综合信号不可用"`
  - 三处口径互斥：「13/13 正常」「26/39 已填」「缺失 66.7%」。

### 2.3 综合信号诚实降级（R52 已修复，延续生效）
`composite_decision.signal=null + degraded=true + reason 含缺失占比` —— R52 诚实降级延续生效。

### 2.4 因子分跨屏数值（R66，待同窗口复测）
本轮组合设计失败，无新鲜设计样本，R66（design vs check 因子分量级一致）无法跨屏比对，维持「待交易时段同窗口复测」。

### 2.5 组合设计「100%现金」失败（R77，本地复盘补充，2026-08-19 11:50 后诊断）
**报错**：`task_manager.py:370` `分配引擎未输出有效ETF标的：所有方案均为100%现金。因子评分均低于阈值或数据源不可用。`

**日志实证**（`backend/logs/backend.log`，task 597 现场）：
```
[async_utils] run_sync queue depth=17-18 (fn=get_history, timeout=20s) → POOL SATURATION!
[health] threadpool_main returned empty → cooling
[strategy_design] pre-allocate 23.83s candidates=30      ← 候选池 30 只，池非空！
[risk] removed stale 510300 (no price/return data)        ← 15 次刷屏，全部标的全删
[risk] removed stale 518880 (no price/return data)
[task_manager] strategy 'defensive/balanced/aggressive' has no non-CASH ETFs → filling with CASH
```

**失败链路（代码级）**：
```
数据源故障（线程池饱和 + threadpool_main cooling + K线 20s 超时队列）
  → factor_registry.compute() 拿空/不可用 market_data，缺数据一律填 0.0（factor_registry.py:1501-1506）
  → aggregate_factor_scores 顶层键全 0 不设置（factor_aggregate.py:136-138）
  → market_data_hub.py:350-353 宽 except → 所有 item["factor_scores"] = {}
  → get_factor_matrix() 返回 {"510300":{}, "159338":{}, ...}  ← 真值 dict、内层全空
  → strategy_design.py:305 factor_matrix_empty = not bool(matrix) → False ←【缺陷A：守卫被绕过】
  → 静态池兜底不触发，引擎照常 allocate（无分数门槛，0 分也选出 4 只 core）
  → risk_controls.py:160-193 remove_stale_candidates
  →   fs={} → has_price/has_return 均 False → 所有非 CASH 全删 ←【缺陷B：全删无保护】
  → strategy_design.py:566-573 空 allocations → cash_weight=1.0 → CASH 100%
  → task_manager.py:368-372 valid_count==0 → 抛出该报错
```

**两个结构性缺陷**：
- **缺陷 A**：`strategy_design.py:305` `factor_matrix_empty = not bool(factor_matrix)` 只判外层 dict——`{"510300":{}}` 是真值 → 空矩阵守卫失效，Z11 静态池兜底不触发。应改为 `not any(v for v in factor_matrix.values())`。
- **缺陷 B**：`risk_controls.py:160-193 remove_stale_candidates` 无「全删保护」——factor_matrix 全空/无 price/return 时 `fs={}` → 每个 ETF 都判 stale 删除，有效分配被清成现金且无 WARNING。数据源故障被伪装成「没有合格标的」。
- 佐证缺陷 C：`factor_registry.py` 缺数据填 0.0 而非 None，下游无法区分「真实 0」与「无数据」；`data_source=unavailable` 注解存在但 remove_stale_candidates 不读。
- 佐证缺陷 D：`market_data_hub.py:350-353` 宽 except → 任一异常所有标的 factor_scores 整体归零，静默。

**引入时间（git 历史实证）**：
| 组件 | 引入 commit | 时间 | 说明 |
|---|---|---|---|
| `remove_stale_candidates`（含 no price/return 全删） | `e727001` | 2026-07-20 | "5 quality improvements (…, **freshness**, …)" |
| `factor_matrix_empty` 判定 | `9b1fa2e` | 2026-07-31 | Z11 空池兜底 |
| 报错首次出现 | — | **2026-08-18 15:52:38**（task 571） | 之后 15:52-16:08 连发 8 次 + 08-19 11:33 |

**为何「之前没有」**：触发需「池非空（候选可删）+ 因子数据全空（全删判定成立）」同时满足。08-18 之前盘后数据源仍有 last-good 兜底 → 因子总有 price/return → 全删永不触发。08-18 收盘后 R68 级联失效（K 线源不可用）首次让条件②成立。**本质：R68 的第 4 个下游症状，非新写代码；但缺陷 A/B 本身应在数据源恢复后独立修复，防止交易时段数据源抖动时复发。**

**⚠️ 归因修正（2026-08-19 13:00 实测复核）**：原「K 线源不可用」归因**不准确**。盘后实测（同环境直接调用）：
```
fetch_history('510300', 'A', 'daily') → 240 rows ✅
_sina_history_cb('510300')           → 240 rows ✅
_baostock_history('510300')          → 151 rows ✅
push2delay 快照                      → 200 + 真实行情（510300 价格 4.673）✅
factor_registry.compute(['510300','518880']) → etf.price/etf.return_1m 均非 0 ✅（当前可用）
```
**免费数据源盘后完全可用，push2delay 也一直可用**。真正触发条件是「进程重启清空内存 K 线缓存 + R59③ 落盘从未生效（`data/kline_cache.json` 不存在）→ 冷缓存期遇到 design 请求 → 因子全空」。08-18 12:22-14:39 进程反复重启 7 次（warmup 日志实证，14:38:57 lifespan 启动日志实证），14:40:32 最后一次 `refresh_kline updated 30/30` 后，15:52 design 请求恰逢缓存未覆盖全部新扫描标的（scanned 79 → 缓存仅 30 只）→ 前 5 只 symbol 无缓存 → `_refresh_impl:334` 触发全量 refresh_kline 重试 → 线程池饱和（15:52:45 `queue depth=9 (fn=fetch_history, timeout=8s)`，15:52:12-14 大量指数 get_history 8s 超时争抢）→ 二次 compute 仍空 → 全删。**归因改为：进程重启缓存清空（R68 落盘未生效）+ R77 全删缺陷，而非数据源不可用。**

**修复设计**（见 §14.1 R77、§14.4 ④）：
1. `remove_stale_candidates` 加前置守卫：factor_matrix 全空或全无 price/return 时**跳过删除** + WARNING（诚实降级保留分配，不伪装成无合格标的）；
2. `factor_matrix_empty` 改判内层：`not any(v for v in factor_matrix.values())` → 矩阵实际为空时走 Z11 静态池兜底，从源头避免进入 allocate 产出现金；
3. 报错文案按 degradation 区分「数据源不可用」与真实低分。

---

## 3. A/HK/US 行情分析（AI 内容审阅）

**first_byte 实测（R49 已生效）**：advice 0.053s / 600519 0.007s / 00700 0.004s / AAPL 0.005s / sector 0.01s —— 从 round28 的 26-111s 全面改善到毫秒级。

- **AI 投顾（综合研判）✅ 高质量**：真实数据（上证 3990.30 +0.19%、深成指 -0.56%、创业板 -0.92%、科创50 +0.11%）、市场阶段判断（横盘消化）、风格（扩散初期：农业种植/机器人/光通信多点开花）、资金行为（存量主导）、风险（欧洲股市连跌/地缘/大宗商品）、三档配置（进攻/平衡/防御 + 权重表）。逻辑严谨、数据与最新行情匹配。
- **个股 600519 ✅ 基本面高质量，❌ 技术面空（R60）**：基本面真实（2026H1 营收 922.78 亿 +1.30%、归母 445.17 亿 -1.95%、Q2 环比 -36%）、机构预测、估值推算（动态 PE 18.9x）、资讯催化、风险提示均专业；但「技术面分析 - 数据限制：提供的技术指标为空，历史K线无数据」—— 而 `/market/indicators/600519` 同窗口返回 `data_available=false`（K线 <30）。**R60 的 Hub 缓存兜底（`get_kline_rows_any`）已实现，但缓存为空（R68）→ 兜底取空 → 仍诚实标注 K 线空。**（诚实降级本身正确；Round 8 修正：问题不是「K 线数据源盘后不可用」（实测可用），而是「重启清空缓存 + 落盘未生效」。）
- **个股 00700 ✅ 完整高质量（R61 已生效）**：真实完整技术面（MA5=446.28/MA10=463.38/MA20=461.79/MA60=453.43 空头排列、RSI 41.97、KDJ K=17.03 D=27.59 J=-4.09 超卖、MACD DIF=-2.38 DEA=2.31 柱 -9.40 动能增强、布林带中下轨）、基本面（南向净买入 5.34 亿、年内回购 267 亿港元）、历史 K 线关键节点。round28 的「00700 整链 DATA_UNAVAILABLE」已彻底修复。
- **个股 AAPL ❌ DATA_UNAVAILABLE**：`/market/realtime/AAPL` 有数据（price 310.745 +1.69%），但 `history/AAPL` 空（美股 K 线源盘后不可用）→ symbol-analysis 数据全空 → `DATA_UNAVAILABLE`。R53 的美股指数分析（SPX）本轮未复测。
- **板块 BK1036（半导体）❌ 「暂无数据」**：`sector_code=BK1036` 在 `sectors/industry` 表**确实存在**（496 条中含 BK1036 半导体），但 sector-analysis 返回 `板块「BK1036」数据源暂无数据（板块表未收录或数据源缺失）`——成分股数据源盘后缺失，错误文案「板块表未收录」误导（板块表已收录）。
- **搜索自动补全 ✅（keyword 参数）**：`银`→银行ETF博时/富国/南方；`腾讯`→腾讯云(板块)/腾讯济安(指数)/00700(港股)；`苹果`→AAPL/苹果概念；`AAPL`→苹果。中文回显正确。
  - ⚠️ **R76**：`茅台` 返回 0 结果（`instruments` 表 A 股个股 0 条，levistock 降级 `get_all_stocks` 盘后静默返回空）。

**专业投资者是否接受**：AI 投顾/茅台基本面/腾讯完整分析达专业水准，first_byte 毫秒级体验达标；但 **A 股个股缺技术面（R60）、美股个股 DATA_UNAVAILABLE、板块分析「表已收录却报未收录」、个股中文名搜不到（R76）**，专业投资者对「技术面缺失」与「板块/个股数据链路盘后不可用」不可接受。

### 3.1 市场综合研判报告问题（R79/R80，2026-08-19 午间用户反馈驱动）

用户反馈（A 股「行情综合研判」= `MarketReport.vue:58` → `/llm-report/stream`）：①报告行情数据与最新数据对不上；②报告第 3 章写「国内流动性：本次数据未提供国内利率信号」。代码 + 日志复核定位（详见 §0.3 4b/4c）：

**R79 — 「国内流动性」双层断裂（采集未接线 + 源超时）**
- **采集**：`llm_context.py:199-207` — `build_full_context` 对 A 市场采集 `ctx["domestic_macro"]`（LPR/中美国债/M0-M2/CPI-PPI/PMI-GDP 六源，`asyncio.wait_for(..., 20)`）；
- **断裂点（结构性）**：`llm_report_stream`（`analysis.py:309-389`）只取 regime/sentiment/market_data/indices/commodities/news，**从不读 `ctx["domestic_macro"]`**；`_build_report_prompt`（`reports.py:140-207`）签名无 domestic_macro 参数，全 prompt 无任何国内利率数据；`macro_news` 也传空列表（`analysis.py:387`）——「政策信号」槽位同样为空；
- 模板第 3 章（`reports.py:186`）却明确要求「国内流动性：货币与利率信号」→ LLM 手头无数据只能如实写「未提供」；
- 全后端 grep `domestic_macro`：仅 `llm_context.py`（生产者）/`macro_fetcher.py`（源）/测试 —— **0 个生产消费点**（「采集了没接上」死数据）；
- **数据源层（日志实证）**：`backend.log` 08-18 14:43:37 / 15:35:23 / 22:03:39 三条 `build_full_context partial errors: ['domestic_macro: ']` —— 空错误 = `asyncio.wait_for` 20s 超时 → `{"unavailable": true}`（`llm_context.py:206`）；5 个 akshare 源整包 20s 预算拉不完（各带 1h 失败缓存 `fail_ttl=3600`，`macro_fetcher.py:23-25`，失败后 1h 内直接 None）。**即便修好注入，源也常超时——两层都要修。**

**R80 — 行情数据与最新数据对不上（多缓存域 + 静默旧值 + 无 as_of）**
- 报告内两处行情来自**两个缓存域**：

  | 报告段落 | 数据来源 | 时效 |
  |---|---|---|
  | 「A股市场」指数（全景速览） | `_index_realtime_cache`（`_refresh_market_snapshot` 60s 后台刷新，`market_data_hub.py:526`）→ `get_global_indices`（30s 缓存） | 最长滞后 ~60s+ |
  | 「主要标的行情」 | `get_all_realtime()`（`market_service.py:108` → `fetch_index_realtime`，15s per-request 缓存） | 较新 |
  | 页面「最新数据」（指数条/watchlist） | 独立请求 + WS 15s 推送 | 最新 |

- 同一指数（如上证指数）在报告内可出现两个不同数值；报告 vs 页面更必然有时差；
- **静默旧值**：`_refresh_market_snapshot._fetch_indices` 失败分支（`market_data_hub.py:615-618`）仅 `if cache is None: = []` —— 旧值无失效标注保留；`get_index_realtime()`（`hub/_realtime.py:8-10`）无 TTL 检查直返缓存；
- 报告 builder 不读可用性：`_build_market_overview`（`reports.py:107`）`idx.get('price','N/A')` —— 不读 `available` 字段、无「数据截至 XX:XX」标注 → 旧值/None 被当当前行情写进 prompt；
- 当日日志（08-19 11:19 最新）显示 `_index_realtime_cache` 正常刷新 17 条、无刷新失败 → 「对不上」主因是**快照 vs 实时时效差** + 报告内缓存域不一致 + 无 as_of 标注，而非大规模源故障。

**专业投资者是否接受**：两项均为「报告数据可信度」问题——国内宏观分析能力结构性缺失（R79）、行情数据无时效标注且可能呈现静默旧值（R80）。修复设计见 §14.1 R79/R80。

### 3.2 美股搜索自动补全 TQQQ 缺失（R84，2026-08-19 用户反馈驱动）

用户反馈：美股「标的分析」输入 `TQQ`（预期 TQQQ）无自动补全选项。实测 `GET /api/v1/market/search?keyword=TQQ&market=US&include_stocks=true` → `[]`（0.0s），对照组 `QQQ`→1 条 / `SPY`→1 条 / `AAPL`→1 条均正常。前端链路本身无误（`UnifiedAnalysis.vue:132-134` → `useMarketSearch.js:82-86` → `/market/search`），问题全部在后端 `search_hk_us()`（`market_service.py:745-922`）的三级数据源。

**三级搜索逐级排查（实测 2026-08-19）**：

| 级 | 数据源 | TQQQ 是否可能命中 | 实测结论 |
|---|---|---|---|
| ① 静态基座 | `HKUS_ETF_MAP` 14 只 US ETF（`:624-638`）+ `HKUS_STOCK_MAP` 18 只个股（`:662-679`） | ❌ | curated 列表无 TQQQ（QQQ/SPY 能搜到正因在此表） |
| ② EM spot | akshare `stock_us_spot_em` → `72.push2.eastmoney.com`，`fs=m:105,m:106,m:107`（`china_market.py:1037-1088`） | ❌ **双失败** | 网络层：72.push2 间歇断连 ~70%（16 页仅 5 页成功，`RemoteDisconnected`），`push2delay` 16/16 全通；**数据层：`fs=m:105..107` 纯股票不含 ETF**——实测全量 13765 只 Q 区整个缺失（QQQ/QQQM 不在）、T 区 100 只（TEMD→TBF）无 TQQQ/TLT、S 区无 SPY/SOXL |
| ③ instruments US 段 | `SELECT ... WHERE market='US'`（`market_service.py:850-873`） | ❌ | 0 行——启动同步失败（日志 08-19 13:50:25 `segment 美股 FAILED: 美股段全部数据源不可用`） |

**附带发现的真实 bug（修了也救不了 TQQQ，但需修）**：`sync_instruments.py:276-281` 新浪美股 JSONP 解析逻辑：

```python
start = raw.find("[")   # 实际取到 `CallbackList[]` 的空 `[]`（index 70）
end = raw.rfind("]")    # 取到 data 数组收尾（index 7097）
items = _json.loads(raw[start:end + 1])   # 子串 `[]({"count":...` → JSONDecodeError
```

新浪实际返回**对象** `CallbackList[]({"count":"17993","data":[...]})`，代码按**数组**假设解析 → 降级链**从未生效过**（每轮直落 `RuntimeError`）。且该接口每页固定 20 条、按市值降序，前 6 页 120 只（NVDA/AAPL 级别）不含 TQQQ；全量 17993 条需 900 页，30s 段超时内不可行。

**根因修正（此前推断）**：上一轮分析认为「EM spot 是唯一含 TQQQ 的数据源」——**错误**。EM 美股 spot 是纯股票列表，TQQQ 这类 ETF **从来不在该源**；换 `push2delay` 域名只能修个股搜索的连接稳定性，对 ETF 无效。

**关键新发现（可行路径）**：新浪 suggest `http://suggest3.sinajs.cn/suggest/type=41&key=TQQQ`（GBK 编码，~0.1s）：

```
TQQQ,41,tqqq,tqqq,纳斯达克指数ETF-ProShares三倍做多,,纳斯达克指数ETF-ProShares三倍做多,99,1,,,
```

- type=41 为美股/ETF suggest；`TQQ` → TQQQ 天然前缀匹配；SOXL/SPXL/UPRO/QQQ 全部命中；
- 字段 4 = 中文名（GBK），字段 7 = 重复名，字段 0 = symbol；响应经 `分号` 分隔多条；
- 当前代码 grep `suggest3|suggestvalue|type=41` **0 引用**——完全未接通的可用源。

**修复设计（已采纳，§14.3 R84 / §15 批2）**：
1. **新浪 suggest type=41 兜底（主，解决 TQQQ）**：`search_hk_us` US 分支在 EM spot 返回空时，按关键字调 suggest（GBK 解码、字段 4 中文名、`type` 按需标 etf/stock），负缓存 60s 防连续打源；毫秒级降级、不阻塞搜索；
2. **修 sync 新浪 JSONP parse bug（附带）**：`sync_instruments.py:276-281` 改按对象解析（`find("{")`~`rfind("}")` + `data` 数组），US 段至少灌入前 120 只美股个股；
3. **push2delay 换域名（附带，个股搜索有益）**：`fetch_us_spot_list` 直接调 `push2delay.eastmoney.com`（实测 16/16 页稳定 vs 72.push2 的 5/16），改善个股 spot 全量可用性（对 ETF 无效，勿误以为能救 TQQQ）。

---

## 4. 热点 + 自选

- **热点 ✅**：`hot-plates` 返回真实数据（农业种植 +9.95%，lead 金健米业 2天2板、农发种业 2天2板，reason 含全球粮食危机催化）；`stock-hot-rank` 50 条（京东方A +6.41%、一鸣食品 +10% 16天11板、爱丽家居 +10.01% 21天12板）。
  - ⚠️ `hot-plates` 首次请求 60s 超时（冷 + 与 IC 回填 CPU 饱和争抢事件循环），二次 0s；`stock-hot-rank` 首次 56.6s（同因），热态 0.44s。
- **自选 ✅（R45 延续 + 全链路）**：22 条；部分带 `realtime`（`is_estimated:true, estimate_source:"last_close"`），部分诚实 `realtime:null + data_unavailable:true + realtime_note:"非交易时段无行情（数据源维护中）"`。add（513050 → id=28）→ DB 持久化 → GET 返回 → DELETE 204 全链通过；重复 add 409 去重正确。
- **⚠️ R78（2026-08-19 12:43-12:47 午休复验，用户反馈驱动）：A 股自选「数据源维护中」——源全部可用，请求自毁式并发**：用户反馈最新价/涨跌幅/成交量全显示「非交易时段无行情（数据源维护中）」，预期非交易时段应显示收盘交易数据。实测**证伪「源故障」**：单发 `fetch_a_stock_batch` 0.25s/4行、sina 1.33s、tencent 1.02s、tickflow 1.26s、sina_history 0.06s/240行；熔断器 mootdx/sina/tencent/sina_history/push2delay 全 closed；**池空闲时 watchlist API 3.81s 返回全量真实行情**（510500=7.88 -3.73%）。真凶 = 请求自身四层自毁机制（详见 §0.3 R78）：
  - ① 批量 2s `wait_for` 超时**不取消底层 `run_sync` future** → HK/US 批量 gather 的孤儿任务继续占 64-worker 池 8-15s；
  - ② 背景刷新（sector 60s/regime 120s/news/IC series）与请求争池 → 日志实锤 `run_sync queue depth=9→22 (fn=fetch_history) POOL SATURATION!`（12:43:16 / 12:44:51）；
  - ③ `_watchlist_close_fallback` **gather 22 只并行** `fetch_history` → 同一秒向 money.finance.sina.com.cn 发 12+ 并发 → Sina 限流返回 **200 空体**（日志 `getKLineData?symbol=sh510500 200 None`，单发探针 0.06s/240 行）；
  - ④ quote 批量路径写 **5s TTL**（`_QUOTE_TTL["A"]=5`），24h last-good 仅 per-item 路径写 → last-good miss → 「维护中」。
  - **间歇性根因**：12:34/12:44 撞上 sector 刷新（12:44:52 `update_sector_cache`）→ 5.8s 超时崩；12:47 池空闲 → 3.81s 成功。同一请求成败取决于池子那一刻是否被后台刷新占用。

- **⚠️ R82（2026-08-19 13:5x 复现，用户反馈驱动）：美股自选「暂无实时」——twelvedata 慢于 2s 批量窗口**：用户反馈美股自选（AAPL）最新价有值但涨跌幅/成交量「暂无实时」。实测 watchlist 响应 3.88s：TSLA/QQQ/SPY `src=stale` 三字段全值（无 unavail 标记）、AAPL `price=310.03 chg=None vol=None is_estimated=True realtime_unavailable=True`。根因：US 批量超时 **2s**（`market.py:776`）< twelvedata 实测 **2-6s/次**（日志 13:53:37 建连 → 13:53:39-43 响应；13:56:50 建连 → 13:56:51 批量取消）→ `_batch_ok["US"]=False`（`market.py:785` WARNING 实证）→ `_skip_markets`（`market.py:821-830`）跳过全部 US per-item（8s 窗口 `market.py:751` 本可容纳）→ 降级链（`market.py:941-965`）：quote-cache 命中显示 stale 全值、未命中走 `_last_close_fallback`（只 price + `is_estimated=True`，`market_service.py:1461-1466`）或全空「暂无实时」。**附带 bug**：批量取消后 last-good 写入不执行（`market_service.py:1374-1380` 在 `:1259` 的 CancelledError 之后）→ AAPL 每次请求重复退化。finnhub 实测 ~1s 可用（200 OK、`X-Ratelimit-Remaining:59`）但排第二（`_route_us`，`market_service.py:1388-1426`），2s 窗口内轮不到；**finnhub 前置会烧穿 60/min 额度**（4 只 × 12 次刷新/min ≈ 48/min）。额度盘点与修复设计见 §0.3 R82 / §14.1 R82（方案 A：放宽批量窗口保持 twelvedata 主源；方案 B：快返回 + 后台刷新；方案 C：twelvedata `/quote` 批量端点探针；护栏：finnhub `X-Ratelimit-Remaining` 配额感知）。孤儿任务机制与 R78③ 同源（`asyncio.to_thread` 无法取消），修复合并考虑。

---

## 5. 持仓技术分析

- 技术信号 ✅：`/market/signal/{symbol}` 返回 `data_available:true` + reasons（MACD/KDJ/MA 自洽）。
- ⚠️ **score 口径不透明（延续 round28 §5）**：
  - `159338` signal=hold score=-0.5，reasons=`[MACD偏多, KDJ超买区(J=92.2), MA5>MA20 多头排列]` —— MACD偏多 + MA多头排列是偏多信号，但因 KDJ 超买给 -0.5（hold），专业投资者无法从 -0.5 推导「趋势偏多但短线超买」。
  - `159992` signal=hold score=1.0，reasons=`[RSI=60.4 偏强, MACD金叉多头, MA5>MA20 多头排列]` —— 三指标全偏多，score 仅 +1.0（hold）而非 buy，阈值映射不透明。
  - `512890` signal=hold score=-0.5，reasons=`[MACD偏空, KDJ超卖区金叉, MA5<MA20 空头排列]` —— MACD偏空 + MA空头 + KDJ超卖金叉（反转），三信号矛盾时给 -0.5 缺解释。

---

## 6. 资讯

- 分级（level/category/stars）结构符合契约字段；R65 规则摘要兜底已生效。
- ⚠️ **R72 分类欠分类**：`哥伦比亚强震已致304人死亡`（自然灾难，契约应 major=5）→ `other` level 1；`欧洲股市录得去年末以来最长连跌`（市场利空，应 ≥3）→ `other` level 1；`俄方：瑞典扣留涉俄货船`（地缘，应 ≥4）→ `other` level 1。本地关键词分类器未覆盖「强震/连跌/扣留」等。
- ⚠️ **R73 stars 公式不符**：多条 level=1 条目 stars=5（契约 `stars = min(level + freshness, 5)` 下 level 1 + freshness≤2 应 ≤3）。**Round 13 归因修正**：非实现有隐藏 boost——`_compute_stars` 是 round9 P2-1 刻意「纯新鲜度」设计（与 level 解耦），**是契约公式过时**（`api-contracts/news/all.md:84`），修复方向为契约对齐实现，见 §14.3 R73。
- ⚠️ **R65 覆盖不完整**：headlines 7/12 非 null（round28 全 null，已改善），但 macro 2/7、global 1/8 仍 null —— 规则摘要 `_rule_news_summary` 仅覆盖 headlines 高重要性条目，macro/global 未回填。
- 智能分析（AI）：因 LLM 配额耗尽（R70 同源），本轮新闻 AI 摘要走规则兜底，未观测到真 LLM 摘要。
- ⚠️ **R83 徽章显示抽象（用户反馈驱动）**：徽章 `[4 其他]` 混排新鲜度数字（4=<6h）与分类文字——数字需映射、与顶部重要性筛选 `★★★★` 撞车、且与 meta 行 time 重复（新鲜度=时间，已显示绝对时间）。**已采纳方案 1**：徽章只留分类彩色标签（`other` 不显示标签，灰边灰标题已表意），meta 行改相对时间，数字移除。设计见 §14.3 R83。

---

## 7. 因子模型

- ❌ **R58 回填放弃（R68 级联）**：`/factors/active` 仍 `valid=0 / no_data=27 / static=11 / observable=0`。
- 日志实证：`[ic_backfill] K 线缓存未就绪（第 1/2/3 次检查），30s/60s/120s 后重试（R58）` → `[ic_backfill] K 线缓存未就绪（重试 3 次后放弃），历史回填跳过——预热未完成或 refresh_kline 未执行（R58）`。
- 生产库 `factor_ic_records`：`177 条 / 6 个 distinct trade_date（2026-08-14~19）`——round28 为 4 个，略有进展（重试机制生效期间捕到 2 个新交易日），但远未达 ≥60 目标。
- 根因链：`refresh_kline` 依赖 `fetch_history`（数据源盘后实测可用，Round 8 证伪「源不可用」）→ 真实失效点是进程重启清空内存缓存 + R59③ 落盘从未生效 → `_kline_cache_rows` 冷缓存期从未填充 → ①IC 回填放弃（R58）；②因子模型 no_data；③R60/R69 同根。

---

## 8. 前后端断裂排查

- ✅ **R62 已修复**：`indicators/00700 → asset_type=HK`、`indicators/AAPL → asset_type=US`、`indicators/600519 → asset_type=A`（round28 恒 "A"）。
- ✅ 其余字段级断裂（composite_decision / realtime_unavailable / 中文回显）已修复。
- ⚠️ **R74 策略检查因子口径矛盾**（§2.2）：`summary="因子数据13/13正常"` vs `composite_decision.reason="因子数据缺失 66.7%"` vs `factor_availability.ratio="26/39"` 三处口径互斥。前端若按 summary 显示「因子正常」、按 composite 显示「信号降级」，专业投资者将看到自相矛盾的状态。

---

## 9. round28 方案落地核验（完整矩阵）

| ID | round28 状态 | 本轮实测 | 判定 |
|---|---|---|---|
| R56 预热双重执行 | 待实施 | `warmup_global_indices` 仅 1 条 6707ms | ✅ 生效 |
| R57 LLM 内层超时 | 待实施 | 内层 15s→60s，LLM 103.6s（原 15s）；coverage 字段透传 | ✅ 生效 |
| R58 IC 回填重试 | 待实施 | 重试机制生效（3 次退避），但 K 线缓存仍冷 → 放弃；factor_ic 4→6 trade_date | ❌ 级联失效（R68） |
| R59 设计链路降级 | 待实施 | off-hours 降级 + skip_refresh 重试均触发，仍 90s 超时失败；kline_cache.json 从未生成 | ❌ 级联失效（R68/R69） |
| R60 symbol-analysis K线注入 | 待实施 | Hub 缓存兜底代码在，但缓存空 → 600519 仍「K线空」 | ❌ 级联失效（R68） |
| R61 港股数据源降级链 | 待实施 | 00700 整链可用，完整技术面（MA/RSI/KDJ/MACD/布林） | ✅ 生效 |
| R62 indicators asset_type | 待实施 | 00700→HK、AAPL→US、600519→A | ✅ 生效 |
| R63 news CLS | 待实施 | news CLS 0.198→0.029（<0.1） | ✅ 生效 |
| R64 portfolio a11y | 待实施 | a11y 82→86，仍 <90 | ⚠️ 部分 |
| R65 资讯摘要 | 待实施 | headlines 7/12 非 null（原全 null）；macro/global 仍 null | ⚠️ 部分 |
| R66 因子分跨屏 | 待实施 | 本轮设计失败无样本 | 待复测 |
| R67 scratch 清理 | 待实施 | backend 根 4 个 scratch 已删（仅剩 conftest.py） | ✅ 生效 |
| R50 logs 清理 | 待实施 | logs/ 递归无历史 .py（round{8,16,18,20} 已删） | ✅ 生效 |

**核验结论**：round28 的 13 项修复中 **7 项真正生效**（R56/R57/R61/R62/R63/R67/R50）、**3 项「已实施但级联失效」**（R58/R59/R60，共同根因 R68：K 线缓存冷）、**2 项部分**（R64/R65）、**1 项待复测**（R66）。R58/R59/R60 是「方法已应用、前置条件未满足、目标未达成」的典型——修复代码在、单测绿，但 K 线缓存从未被填充（Round 8 修正：非「盘后数据源不可用」，数据源实测可用；是「重启清空内存缓存 + R59③ 落盘从未生效」）导致三者的共同前置（已填充的 K 线缓存）无法满足。

---

## 10. 前端 Lighthouse（4 路由）

| 路由 | perf | a11y | CLS | 备注 |
|---|---|---|---|---|
| / | 74 | 96 | 0.0009 | round28 73，perf 仍 <90 |
| /market-analysis | 85 | 100 | 0.0007 | |
| /portfolio-analysis | 77 | 86 | 0.0009 | a11y 82→86 改善但仍 <90（R64 部分） |
| /news | 96 | 95 | **0.029** | CLS 0.198→0.029（R63 生效）；perf 84→96 |

- ✅ R63：news CLS 0.198→0.029（<0.1 达标）。
- ⚠️ R64：portfolio-analysis a11y 86（round28 82，改善 4 分但仍 <90）。
- ❌ F4/F5（Lighthouse perf≥90 / a11y≥90 硬门禁）仍未实施——无 CI 卡点，root perf 74 / portfolio 77 无人拦截。

---

## 11. 后端链路性能（冷/热态）

| 端点 | 冷态（首呼） | 热态 | 判定 |
|---|---|---|---|
| /health | 0.06s | 0.00s | ✅ |
| /portfolio/etfs | 0.01s | 0.04s | ✅ |
| /market/hot-plates | 0.03s（首轮 60s 超时后） | 0.02s | ⚠️ 首呼曾超时（R75 争抢） |
| /market/stock-hot-rank | 0.44s | 0.21s | ✅ |
| /market/search | 0.05s | 0.04s | ✅ |
| /market/watchlist | 5.86s | 0.02s | ❌ 冷态 |
| /market/realtime/510300 | 0.11s | 0.03s | ✅ |
| /market/indicators/510300 | 0.06s | 0.06s | ✅ |
| /market/signal/510300 | 0.06s | 0.07s | ✅ |
| **/market/sectors/industry** | **20.02s** | 0.02s | ❌ 冷态 |
| **/market/sectors/concept** | **36.80s** | **17.08s** | ❌ **冷 + 热态均慢（R71）** |
| /market/indices/global | 0.50s | 0.02s | ✅ |
| /news/headlines | 0.01s | 0.03s | ✅ |
| /factors/active | 0.01s | 0.02s | ✅ |
| /market/history/510300 | 0.07s | 0.05s | ✅ |

**结论**：热态除 concept 外全 <0.5s；`sectors/concept` 是唯一「冷热均慢」的端点（36.8s/17.1s），根因 akshare THS 概念板块全量拉取未缓存（R71）。`sectors/industry` 冷 20s（首次 akshare 行业表拉取，热态已缓存）。`watchlist` 冷 5.9s（实时行情批量富化，R45 的 is_estimated 兜底未覆盖首呼冷路径）。

---

## 12. 测试防护缺口分析（为何现有测试未识别，task 13）

本轮识别的问题与测试体系的关系：

1. **R68（K 线缓存冷级联，R58/R59/R60 共同根因）**：三个修复各自的单测都**在 mock 已就绪的 K 线缓存**下验证「修复逻辑」（如 R58 测「缓存未就绪 → 重试而非跳过」、R59 测「skip_refresh 降级」、R60 测「get_history 空 → Hub 缓存兜底」），但**没有任何集成测试覆盖「盘后 mootdx/tickflow 双源失败 → refresh_kline 从未成功 → 缓存恒空 → 三个修复的前置永不满足」的真实级联场景**。单测验的是「方法已应用」，不是「目标已达成」。
2. **R69（设计超时）**：R59 测试 mock `refresh()` 与 K 线采集，不测「skip_refresh 后仍有逐标的 tickflow K 线采集」这一真实路径——`skip_refresh` 只跳过扫描，K 线采集是独立慢点，测试未断言「skip_refresh 后设计仍 ≤90s 产出降级方案」。
3. **R70（LLM 配额节流）**：R57 测试改判「不再断言 connect=15s」，但无测试模拟「opencode_zen 429 → 全局暂停 60s + DeepSeek 每次节流 5.7-6.5s → 103.6s 内无法完成 JSON 输出」的真实配额耗尽场景。测的是「内层超时值改了」，不是「配额耗尽时 AI 报告仍能产出或诚实降级」。
4. **R71（sectors/concept 36.8s/17.1s）**：无任何性能测试/基准覆盖 `sectors/concept`，Lighthouse/verify_perf 只测前端与少数热点路径。概念板块全量拉取是性能盲区。
5. **R72/R73（资讯分类/stars）**：news 分类单测覆盖了「停牌/违约/机构名」等词表治理场景，但无「自然灾难→major」「市场连跌→negative」「地缘扣留→risk」的**新增场景负向断言**；R73 归因修正后（实现为刻意纯新鲜度、契约过时），缺口变为「**契约-实现一致性断言**」（契约公式与 `_compute_stars` 口径对齐的测试），而非「level=1 且 stars=5 应失败」。
6. **R74（因子口径矛盾）**：strategy-check 测试只验「coverage 字段存在」与「degraded 字段」，不验「summary 的『13/13 正常』与 composite_decision 的『缺失 66.7%』与 factor_availability 的『26/39』三者口径一致」的跨字段一致性。
7. **R75（IC 回填 CPU 饱和抢占请求）**：无测试模拟「IC 回填 CPU 循环运行期间，/tasks/{id} 轮询请求的延迟」——R58 的已知性能债（回填慢）未转化为「并发场景下请求不被抢占」的测试。
8. **R76（A 股个股中文名搜索）**：search 测试只验 ETF/HK/US 路径，无「instruments 表 A 股个股 0 条 + levistock 失败 → 中文个股名搜索」的负向断言。

**共性**：与 round27/28 §12/§13 一脉相承——测试验「方法已应用」非「目标已达成」，mock 快乐路径，不测「前置条件未满足」的级联场景与「跨字段一致性」的结构事实。本轮新增的教训是：**三个修复共享一个前置（已填充的 K 线缓存），但没有任何测试把这个前置的失败作为输入**，导致「修复全绿但运行时全失效」。

---

## 13. 冗余代码排查（task 16）

- ✅ 历史清理全落地（round28 R50/R67 + code-health BE-1~6/BP-1~13）：
  - backend 根仅 `conftest.py`（R67 的 4 个 scratch 已删）；
  - `scripts/` 15 个合法工具（audit_*/check_*/sync_*/verify_*/smoke_startup/data_health_check/encoding_diagnosis）；
  - `scripts/archive/` 10 个归档探测脚本（probe_*/audit_*/repair_encoding 等，历史一次性诊断，已归档）；
  - `logs/` 递归无历史 .py（round{8,16,18,20} 已删）；
  - 测试文件 210（P3-6 基线 210）。
- **结论**：生产与测试代码无新增冗余；当前状态干净。本轮未发现需要新增清理的死符号/死代码（`scripts/archive/` 的 10 个归档脚本可评估是否进一步精简，但属可选项，非阻塞）。
- 注：`logs/_audit_*.py` 为本轮验收的临时脚本（gitignored，commit 前清理）。

---

## 14. 修复方案总表（R68-R84，不实施）

### 14.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R68 | P0 | K 线缓存冷级联失效（R58/R59/R60/R77 共同根因） | **Round 12 精确化（原「updated=0 永不落盘」是表象，当前代码已部分成功也落盘）**：①**落盘条件放宽**——`refresh_kline`（`hub/_kline.py:293-309`）的 `_persist_kline_cache_sync()` 从 `if updated > 0:` 内移到 `if self._kline_cache_rows:` 即可触发（含 updated==0 但内存有磁盘加载缓存的场景）——**保持磁盘缓存 mtime 新鲜，防 `_load_kline_cache_sync`（`:144`）24h TTL 判过期丢弃**；②**盘后 last-good 收盘快照兜底**——`_fetch_one`（`:281-288`）在 `fetch_history` 返回空时回退 `get_kline_rows_any(sym)` 已有缓存（保留旧值不覆盖）+ `mark_kline_stale(sym)`，保证缓存不因单次失败清空；③**refresh_kline 的 fetch 改 `run_sync_long`（long 池）**——现用 `run_sync`（主池，`async_utils.py:85` 无 executor 参数），与请求/后台任务争 64-worker 池，生产实况「池饱和饿死 refresh_kline」正是 R77/R78 同源；④`_load_kline_cache_sync`（`:131`）已实现、磁盘有数据即加载。**归因不变：数据源盘后实测可用，失效点是「重启清空内存缓存 + 落盘 mtime 不刷新/从未生成 + 池饱和饿死 fetch」** | ①重启后首呼 design 产出非空因子方案；②`data/kline_cache.json` 生成且 mtime <24h；③负向：K 线缓存空时 IC 回填/设计/分析三链须**诚实降级并重试**，而非静默放弃 | `hub/_kline.py:281-309/131-172`、`async_utils.py:85`、`main.py:75` |
| R69 | P1 | 组合设计仍超时失败（R59 目标未达成） | ①R68 落地后，skip_refresh 重试走磁盘缓存 K 线（消除逐标的 tickflow 冷建库）；②设计数据采集的 K 线部分**并发上限 + 单标的短超时**（现 Semaphore(5)×20s 但 tickflow 429 时每标的仍重试）；③「数据采集超时」时用已采集部分 + 快照**产出降级方案**而非 failed（R59② 的「超时→降级」仍未真正产出方案） | ①盘后首呼 design 产出 `degradation.mode=degraded` 方案（非「方案生成超时」失败）；②负向：禁止「方案生成超时」空响应 | `task_manager.py:570`、`strategy_design.py`、`hub/_kline.py` |
| R77 | P0 | 组合设计「100%现金」失败（R68 第 4 下游 + 潜伏缺陷） | ①`remove_stale_candidates` 加前置守卫：factor_matrix 全空或全无 price/return 时**跳过删除** + WARNING（诚实降级保留分配）；②`strategy_design.py:305` `factor_matrix_empty` 改判内层 `not any(v for v in factor_matrix.values())`——矩阵实际为空时走 Z11 静态池兜底；③报错文案按 degradation 区分「数据源不可用」与真实低分 | ①数据源故障窗口内 design 产出降级方案（非 100%现金失败）；②负向：factor_matrix 全空时 `remove_stale_candidates` 不得删除任何标的；③负向：空矩阵不得产出「所有方案均为100%现金」 | `risk_controls.py:160-193`、`strategy_design.py:305`、`task_manager.py:370` |
| R70 | P1 | 策略检查 LLM 配额节流 → 规则兜底 | ①策略检查 LLM 失败后，summary 明确区分「配额耗尽（429）」vs「超时」vs「JSON 解析失败」，并给出可读原因；②配额耗尽时**主动降级为结构化规则报告**（现有规则兜底已做，但 summary 文案「LLM 分析超时（104s 未返回）」掩盖了真实原因「配额耗尽 + JSONDecodeError」）；③（可选）策略检查 LLM 结果 JSON 解析加 `response_format=json_object` 或重试 | ①配额耗尽时 summary 含「配额」关键词而非「超时」；②负向：不得用「超时」掩盖 429/JSONDecodeError | `llm.py` 策略检查段、`strategy_check_worker.py` |
| R70b | P2 | 设计报告 LLM 仍 `connect=15.0`（同 R57 类脆弱点） | `reports.py:750` `generate_design_report` 仍 `httpx.Timeout(connect=15.0, read=120.0)`——strategy_check 路径（`reports.py:538`）已改 60s，但设计报告路径未改，DeepSeek 慢连接 >15s 时同样 `CancelledError`。注释标「connect 15s 防 429/挂起」为刻意取舍，但应评估是否对齐 60s 或加「慢连接重试」 | ①设计报告在 DeepSeek 慢首字节时能产出（非引擎兜底）；②负向：connect 15s 不再先于 read 120s 触发 | `reports.py:750` |
| R74 | P2 | 策略检查因子口径矛盾（13/13 vs 缺失66.7% vs 26/39） | ①统一「因子可用性」单一口径：summary 与 composite_decision.reason 与 factor_availability 三处用同一数值（如「因子填充 26/39 = 66.7%，综合信号降级」）；②summary 的「因子数据 N/M 正常」改为「因子填充率 X%」 | ①三处数值一致；②负向：禁止「13/13 正常」与「缺失 66.7%」并存 | `services/portfolio/strategy_check.py:196-213`（data_quality）、`services/portfolio/formatting.py:226`（`_factor_value_real`）、`analysis/signal.py:92`（composite reason） |
| R79 | P1 | 综合研判「国内流动性」未注入（双层断裂：采集未接线 + 源超时） | ①`_build_report_prompt` 增 `domestic_macro` 参数，将 LPR/中美国债/利差/M0-M2/CPI-PPI 格式化为「### 国内流动性」段（模板第 3 章槽位现成）；②`llm_report_stream` 从 ctx 取 `domestic_macro` 传入；unavailable 时注入「（国内宏观数据源暂不可用）」占位——LLM 说「数据源不可用」而非「未提供」；③采集侧：5 源各自独立短超时（现整包 20s `wait_for`，一个慢源拖死全部）；④（可选项）`macro_news` 不再传空列表，补「政策信号」槽位 | ①源可用时报告第 3 章含真实 LPR/国债数字；②unavailable 时文案为「数据源暂不可用」；③负向：prompt 不得再出现「未提供国内利率信号」 | `reports.py:140-207`、`analysis.py:309-389`、`llm_context.py:199-207`、`macro_fetcher.py:449` |
| R80 | P1 | 综合研判行情数据与最新数据对不上（多缓存域 + 静默旧值 + 无 as_of） | ①报告注入 as_of（各缓存域最近刷新时间），LLM 标注「数据截至 XX:XX」；②`_build_market_overview`/`_format_indices` 读 `available` 标记，不可用显示「数据源暂不可用」而非旧值/None；③`_refresh_market_snapshot` 失败时打 stale 标记供报告标注「指数数据可能滞后」；④报告内 indices 与 market_data 统一取同一缓存域，消除报告内自相矛盾 | ①报告含数据截至时间；②源降级时报告标注而非静默旧值；③负向：同一指数在报告内不得出现两个不同数值 | `reports.py:88-139`、`market_data_hub.py:589-656`、`hub/_realtime.py:8-10`、`market_service.py:108` |
| R78 | P1 | 自选股「数据源维护中」——源可用但请求自毁式并发（四层机制，见 §0.3/§4） | ①**收盘兜底改「缓存快照」**（根治）：每日/首次成功拉取各自选收盘写 24h 缓存，请求读缓存而非每次实时拉 22 次 K 线；`_watchlist_close_fallback` 加并发信号量 ≤3 + 单条 0.8s→3s；②enrich 循环内 `_last_close_fallback` 并行化 `asyncio.gather` + 每条 `wait_for(1.5s)`——消除顺序累计撞 5s、不丢已算数据；③**消除批量超时孤儿任务**：HK/US 批量 `get_asset_realtime` 内部超时收紧（≤3s）或改可取消的提交方式，2s 超时后池内不得残留 8-15s 任务；④`get_realtime_batch` 写 quote 改用 `_LAST_GOOD_TTL`（24h）——一次成功实时价持久化，盘后直接可作 last-good；⑤`_last_close_fallback` 补 `change_pct`（rows[-2] 前收计算）+ `volume`（rows[-1]） | ①非交易时段 A 股自选显示真实收盘价+涨跌幅+成交量（非维护中）；②池繁忙时 watchlist ≤6s 且无 `POOL SATURATION` 日志；③负向：禁止同秒 12+ 并发 Sina K 线请求；④负向：批量超时后池内不得残留 >15s 孤儿任务 | `market.py:772-787/951-957/989-992/1018-1031`、`market_service.py:1017-1032/1440-1473`、`async_utils.py:103-118` |
| R82 | P1 | 美股自选「暂无实时」——US 批量 2s 窗口短于 twelvedata 延迟（2-6s），批量超时后整组跳过 per-item（见 §0.3/§4） | **配额优先原则：保持 twelvedata 主源（800次/天宽裕），finnhub 仅作救援（60次/分不可被常规刷新烧穿），tickflow 尾环不动。**①**方案 A（最小改动）**：US 批量超时 2s→7s（`market.py:776`）+ 外层 5s 联动放宽（`market.py:1072`，仅 US 标的组存在时）——twelvedata 正常完成并写 last-good，后续请求走 3s 内存缓存 + 5s quote 缓存低频触发慢路径；②**方案 B（延迟与配额解耦）**：快返回 + 后台刷新——先用 last-good/收盘兜底快速返回（≤3s），`asyncio.create_task` 后台 7s 窗口跑完整 US 批量并写 quote 缓存，下轮请求读取新值；③**方案 C（探针验证，D1）**：twelvedata `/quote?symbol=A,B,C` 逗号分隔批量端点——单次 HTTP 往返消除「等最慢一只」，同时省调用次数；免费层按 symbol 计 credit 还是按请求计**需探针验证**，失败不进实施清单；④**护栏**：finnhub 响应头 `X-Ratelimit-Remaining`（已观测 59）配额感知，低于阈值跳过 finnhub 直接诚实降级；⑤**附带修复**：批量被取消后 last-good 不写入（`market_service.py:1374-1380` 在 `:1259` CancelledError 后不执行）——后台线程返回成功结果时仍写 `quote_key` 缓存，消除 AAPL 每次请求重复退化；孤儿任务机制与 R78③ 合并治理 | ①盘中/盘后美股自选显示真实实时价（非「估」/「暂无实时」）；②池繁忙时 watchlist ≤6s 且无孤儿任务残留；③负向：finnhub 每日配额不被常规 watchlist 刷新烧穿；④负向：批量超时后池内不得残留 >15s 任务 | `market.py:772-787/1072/821-830`、`market_service.py:1256-1264/1374-1380/1388-1426`、`global_markets_fetcher.py:509-542`、`WatchlistPanel.vue:127-159` |

### 14.2 性能

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R71 | P1 | sectors/concept 36.8s 冷 / 17.1s 热（归因修正：**端点热路径非 THS**，THS 45.7s 属预热索引同步，见 §0.3） | **端点侧**：①`fetch_concept_sectors`（`sector_fetcher.py:240`）**补充源 `_ak_concept_sectors_v2()`（`:259`）移入 `cached()` producer 内**（合并后再缓存，或对合并结果再包一层 cached）——消除「主源缓存命中但补充分支每请求重跑 `stock_board_concept_name_em`」；②概念 TTL 60s→1h（`core/ttl.py:26` `sector_concept`）——概念板块低频变化，60s 缓存过短；**预热/后台侧**：③`_background_indices_meta_sync`（`main.py:238-245`）的 THS 拉取改 `run_sync_long`（long 池）或 `to_thread(..., executor=long)`，脱离主 64-worker 池争抢；④`sync_indices_meta.py` 启用 `ETF_FAST_JSON=1` shim 加速 demjson（45.7s 累计 CPU） | ①热态 concept ≤1s；②冷态 ≤10s；③负向：热态不得重新触发 `_ak_concept_sectors_v2` 全量拉取；④负向：预热期间主池不得被 THS 拉取占满 | `sector_fetcher.py:240-268`、`core/ttl.py:26`、`main.py:238-245`、`sync_indices_meta.py:102/129` |
| R75 | P2 | IC 回填 CPU 饱和抢占请求 | **已实施（`13839b3`）**：advance_decline 同步阻塞已消除（`future.result()` → `await run_sync` + 60s TTL 缓存），/health 50s+→6ms。**残余可选优化（不阻塞）**：①回填时光回溯循环（~10s/compute × 500 交易日）每 N 次 compute `await asyncio.sleep(0)` 让出事件循环；②回填放低优先级（独立线程池或 `asyncio.to_thread`） | ①回填期间 `/health` 与 `/tasks/{id}` 延迟 <1s；②负向：回填期间普通请求不得超时 | `ic_tracker.py:194 compute_periodic_ic`、`main.py:_backfill_ic_history_task` |

### 14.3 治理 / 呈现

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R72 | P2 | 资讯分类欠分类（自然灾难/市场波动/地缘 → other） | ①`_CATEGORY_KEYWORDS`（`levistock_fetcher.py:25-145`）补词：「强震/地震/海啸/台风/洪水/灾难」→major=5；「连跌/暴跌/收跌/走弱」→negative≥3；「扣留/扣押/袭击/开战」→risk≥4（注：「地震」已在 major 表但「强震」未收录——标题用「强震」即漏）；②补负向单测（`test_news_fetcher.py` 或 levistock 分类测试） | ①强震→5、连跌→3、扣船→4；②负向：三类不得落入 other | `levistock_fetcher.py:25-145`（词表）、`news_fetcher.py:265-277`（分类入口） |
| R73 | P2 | 资讯 stars 公式与文档不符 | **归因修正：非实现 bug——`_compute_stars`（`news_fetcher.py:228-240`）是 round9 P2-1 刻意「纯新鲜度」设计（<1h→5★/…/更旧→1★），与 level 解耦**；契约 `api-contracts/news/all.md:84` 的 `min(level+freshness,5)` 过时且同文件自相矛盾（`:3` 写 stars=level、`classification.md:16` 写新鲜度维度）。修复方向：①**更新契约** all.md:84 公式 →「stars=纯新鲜度（5=<1h,4=<6h,3=<24h,2=<72h,1=更旧），与 level 解耦」，并消除 all.md:3 与 classification.md 的冲突表述；②补契约一致性断言测试（level 任意 + 新鲜度 5★ 合法）；③（R83 落地后）前端不再展示 stars 数字 → 展示层无影响 | ①契约三处口径一致；②负向：契约不再出现 `min(level+freshness,5)` 旧公式 | `news_fetcher.py:228-240`、`api-contracts/news/all.md:3/84`、`classification.md:16` |
| R65 | P2 | 资讯摘要 macro/global 仍 null | ①规则摘要 `_rule_news_summary` 扩展到 macro/global 高重要性条目；②或复用 headlines 的规则摘要生成器 | ①macro/global 高重要性条目 ai_summary 非 null | `market_data_hub.enrich_news_summaries`、`news_fetcher.py` |
| R64 | P2 | portfolio-analysis a11y 86（R51/R64 延续） | ①跑 Lighthouse a11y 明细定位未达标对比度元素（portfolio-analysis 局部组件，非全局 theme.css）；②针对性修对比度 | ①portfolio-analysis a11y ≥90 | `PortfolioAnalysis.vue`、`AnalysisView.vue` |
| R76 | P2 | A 股个股中文名搜索（茅台）返回 0 | ①**补 instruments 表 A 股个股段同步**（当前 0 条是数据缺口）——`sync_instruments.py` 的 A 股段或 levistock 个股入库；②**levistock 空结果也打 WARNING**（`market.py:415-435` 现仅异常打日志、返回空静默——补 `if not full: logger.warning(...)`）；③`_search_a_stocks` 空结果时兜底 `market_data_hub.search_etf` 前先试拼音匹配（`Instrument.pinyin`/`first_letter`） | ①「茅台」→600519；②负向：levistock 空结果不得静默（有 WARNING 日志） | `market.py:379-435 _search_a_stocks`、`fetchers/sync_instruments.py` |
| R84 | P2 | 美股搜索 TQQQ 无自动补全（用户反馈驱动，见 §3.2）——TQQQ 不在静态基座；EM spot 双重失败（72.push2 间歇断连 + `fs=m:105..107` 纯股票不含 ETF）；instruments US 段 0 行 | ①**新浪 suggest type=41 兜底（主）**：`search_hk_us` US 分支在 EM spot 空时按关键字调 `suggest3.sinajs.cn/suggest/type=41&key={kw}`——GBK 解码、字段 4 中文名、返回 `symbol/name/market=US`、`type` 按 etf/stock 标注；**负缓存 60s** 防连续打源；毫秒级降级不阻塞搜索（同 R4-26 快速失败原则）；②**修 sync 新浪 JSONP parse bug（附带）**：`sync_instruments.py:276-281` 改按对象解析（`find("{")`~`rfind("}")` + `data` 数组），US 段至少灌入前 120 只美股个股；③**push2delay 换域名（附带，仅个股有益）**：`fetch_us_spot_list` 直连 `push2delay.eastmoney.com`（16/16 页稳定 vs 72.push2 的 5/16），勿误以为能救 ETF——EM 美股列表不含 ETF 是数据层事实 | ①输入 `TQQ` → 补全 TQQQ（含中文名）；②负向：suggest 失败/超时不得阻塞搜索（毫秒级降级到基座）；③负向：US spot 源不可用时个股搜索不得全空（suggest 不依赖 EM） | `services/market_service.py:745-924`（search_hk_us；静态基座 `:610-660`）、`fetchers/china_market.py:1037-1088`、`fetchers/sync_instruments.py:276-301` |
| R83 | P2 | 资讯徽章显示抽象（`[4 其他]` 混排新鲜度数字+分类文字，用户反馈驱动） | ①徽章去数字：移除 `NewsView.vue:85` 的 `stars` 渲染（`item.stars ?? mapNewsLevel(item.level).stars`），只留 category 彩色标签（重大/利好/利空/风险/提醒）；②`other` 类不渲染标签文字（灰边灰标题已表意）；③meta 行 `NewsView.vue:101` 时间改相对时间（`3小时前`/`刚刚`，<1h=刚刚），悬浮 title 显示精确时间——新增相对时间格式化函数（基于 `item.time`/`sort_time`）；④保留 category 颜色体系与按 sort_time 排序逻辑不变 | ①徽章无裸数字；②新鲜度自然语言直接可读；③负向：`other` 类不渲染「其他」文字、页面无 `news-stars` 数字 | `NewsView.vue:85/101`、`newsLevel.js` |

### 14.4 R68/R69/R77 详细设计（P0/P1，级联根因 + 设计链）

#### 14.4.0 根因链（代码级 + 日志实证）

```
【归因修正 08-19】数据源盘后实测可用（Sina 240 rows / BaoStock 151 / push2delay 200）——
「盘后数据源不可用」是误判；真正失效点：
  进程反复重启（08-18 12:22-14:39 共 7 次，warmup/lifespan 日志实证）
  → 内存 K 线缓存（_kline_cache_rows）随进程清空
  → R59③ 落盘 data/kline_cache.json 从未生成（updated>0 才落盘，而冷缓存期 updated=0）
  → 冷缓存期因子 compute 全空
    → refresh_kline 重试（:334 前 5 只无缓存触发）被线程池饱和拖垮
      （15:52:45 queue depth=9 fetch_history 8s；15:52:12-14 指数 get_history 8s 超时争抢）
  → 四下游级联失效：
       ① IC 回填 _wait_for_kline_rows 3 次重试后放弃 → 因子模型 no_data（R58）
       ② 组合设计 skip_refresh 后仍逐标的 tickflow K 线采集 → 90s 超时（R69）
       ③ symbol-analysis Hub 缓存兜底 get_kline_rows_any 取空 → 600519「K线空」（R60）
       ④ 组合设计「100%现金」失败：池刷新成功（30 候选）但因子全空 →
          factor_matrix_empty 守卫被绕（只判外层）→ remove_stale_candidates 全删 →
          CASH 100%（R77，本地复盘新增，见 §2.5）
```

**关键证据**：`data/kline_cache.json` 不存在（`ls` No such file）；`factor_ic_records` 6 个 distinct trade_date；`docker logs` 大量 `tickflow 429`；`600519 history=0 / indicators data_available=false`。

> **Round 13 精确机制注记**：上链「R59③ 落盘从未生成（updated>0 才落盘，而冷缓存期 updated=0）」是历史事实描述；代码级精确缺口有二——①当前 `refresh_kline`（`hub/_kline.py:293-309`）在 `updated>0` 时**已含部分成功落盘**，真正的落盘缺口是 **updated==0 时不刷新磁盘缓存 mtime**，导致 `_load_kline_cache_sync`（`:144`）的 24h TTL 会把旧磁盘缓存判过期丢弃（冷启动循环放大）；②生产触发场景是**线程池饱和饿死 `refresh_kline` 的 fetch**（R78 同源），非源不可用。详见 §14.1 R68 / §14.4.1 ①。

#### 14.4.1 修复优先级

| # | 优先级 | 优化 | 设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| ① | P0 | **K 线缓存落盘保活 + 盘后降级链（Round 12 精确化）** | `refresh_kline`（`hub/_kline.py:293-309`）的 persist 触发条件由 `if updated > 0:` 放宽为 `if self._kline_cache_rows:`——**磁盘缓存 mtime 保活**（防 `_load_kline_cache_sync` `:144` 24h TTL 判过期丢弃，这是「部分成功也落盘」的本意：逐 symbol 写 rows 已有，缺口是 updated==0 时不刷新 mtime）；`_fetch_one`（`:281-288`）失败时回退 `get_kline_rows_any(sym)` 保留旧值 + `mark_kline_stale`；fetch 改 `run_sync_long`（long 池）脱离主池争抢 | 盘后冷启动后 `get_kline_rows_any` 非空；`data/kline_cache.json` 生成且 mtime 每轮刷新；池饱和时 refresh_kline 不被饿死 | `hub/_kline.py:281-309/131-172` |
| ② | P0 | **设计「超时→降级方案」真正落地** | `task_manager` 数据采集超时路径不再 `TimeoutError → failed`，改为用已采集部分 + last-good 池 + 快照 K 线**产出 `degradation.mode=degraded` 方案**（复用现有 degradation 机器） | 盘后首呼 design 产出降级方案；负向：禁「方案生成超时」空响应 | `task_manager.py:570`、`strategy_design.py` |
| ③ | P1 | **IC 回填让出事件循环** | **主根因已修（`13839b3`：advance_decline 阻塞消除，/health 50s+→6ms）**。残余可选：回填时光回溯循环每 N 次 compute `await asyncio.sleep(0)` 或 `to_thread`，消除 CPU 独占 | 回填期间请求延迟 <1s | `ic_tracker.py`、`main.py:688` |
| ④ | P0 | **设计「100%现金」防御（R77）** | `remove_stale_candidates` 加前置守卫：factor_matrix 全空或全无 price/return 时**跳过删除** + WARNING；`strategy_design.py:305` `factor_matrix_empty` 改判内层 `not any(v for v in factor_matrix.values())` → 空矩阵走 Z11 静态池兜底；报错文案按 degradation 区分「数据源不可用」 | factor_matrix 全空时不得删除任何标的；空矩阵不得产出「100%现金」失败 | `risk_controls.py:160-193`、`strategy_design.py:305`、`task_manager.py:370` |

**优先级关系**：①是治本（K 线缓存有数据，四下游全部激活）；②见效最快（设计永远能产出方案）；③R75 主根因已修（`13839b3`），此项为可选优化；④（R77）设计链最后一层防线——即使数据源故障，也诚实降级而非产「100%现金」空壳。

### 14.5 本轮已实施（R81，2026-08-19 会话，前端缺陷）

> 唯一例外于「不实施」口径：用户反馈驱动 + 前端单文件修复，定位后直接落地。

| ID | 级 | 问题 | 修复 | 验证 | 文件指向 |
|---|---|---|---|---|---|
| R81 | P1 | 港股板块热度「AI 分析」报「请输入标的代码或名称」——externalTrigger watch 只写 `search.searchQuery`（symbol 实例），doAnalyze 读 `activeSearch.searchQuery`（sector/index 模式实例恒空） | `externalTrigger` watch 置 `activeMode` 后改写 `activeSearch.value.searchQuery`（取当前模式实例），与 `quickSelect`（Q5 修复）同法；新增 2 回归用例（Q6：sector / index 模式 externalTrigger 写回 + 不再报空输入） | `vitest run UnifiedAnalysis.spec.js` → **31 passed**；`vite build` → 通过 | `UnifiedAnalysis.vue:314`、`UnifiedAnalysis.spec.js` |

### 14.6 P1 重大项实施级详细设计（Round 13 复核后，达实施标准不实施）

> 本节把 §14.1 中 P1 大项（R78/R79/R80/R82）从「修复方向」细化到「实施步骤 + 测试清单 + 风险」级别，与 §14.4（R68/R69/R77 已细化）并列。每项标注**当前行号锚点**（2026-08-19 工作区实测）与**改动点**，实施时按此执行。

#### 14.6.1 R78 — 自选收盘兜底缓存快照 + 并发治理（P1）

**改动点（5 步，对应 §14.1 R78）**：
1. **收盘兜底并发收敛**：`market.py:_watchlist_close_fallback`（`:973-1033`）`asyncio.gather`（`:1033` 现全量 22 路并发）前加 `asyncio.Semaphore(3)` 包裹 `_one`；单条 `wait_for` 0.8s→3s（`:991`）。**同时把成功拉到的收盘行写 quote 缓存（`_LAST_GOOD_TTL` 24h）**——首拉写缓存，后续请求直接读缓存（根治「每次实时拉 N 次 K 线」的洪泛），缓存 miss 才回源。
2. **enrich 循环并行化**：`market.py:_watchlist_enrich_items` 内 `_last_close_fallback`（`:952-953`，顺序执行、每条内部 8-10s）改 `asyncio.gather` + 每条 `wait_for(1.5s)`（`:989-992` 上下文）——消除 N 只顺序累计撞外层 5s（`:1072`）、已算部分不被 TimeoutError 整体丢弃。
3. **孤儿任务消除**：HK/US 批量 `_batch_for`（`:772-787`）超时只取消 await、底层 `run_sync` future 残留——`get_asset_realtime` 内部 `wait_for(_route_us, 8)`（`market_service.py:1259`）收紧到 ≤3s，或改可取消提交；2s 超时后池内不得残留 8-15s 任务。
4. **quote TTL 统一 24h**：`get_realtime_batch`（`market_service.py:1029-1031`）`_QUOTE_TTL["A"]=5` → `_LAST_GOOD_TTL`——一次成功实时价持久化，盘后直接可作 last-good。
5. **`_last_close_fallback` 补字段**：`market_service.py:1464-1466` `change_pct/volume` 恒 None → `change_pct` 用 `rows[-2]` 前收计算、`volume` 取 `rows[-1]`（K 线 rows 里本可算）。

**测试清单**：
- 正：mock `_last_close_fallback` 返回 K 线 rows → watchlist 响应含真实 `change_pct`/`volume`（非 None）。
- 正：mock 收盘兜底成功 → `quote_key` 缓存写入且 TTL=24h。
- 正：mock quote 缓存命中 → `_watchlist_close_fallback` 不再触发 Sina 请求（缓存读取路径）。
- 负：`_watchlist_close_fallback` 并发 ≤3（mock `_last_close_fallback` 内并发计数断言）。
- 负：批量超时后 `_queue_depth_spike_count` 不增长（无孤儿任务残留）。
- 集成（D3 验证窗口：非交易时段）：A 股自选显示真实收盘价+涨跌幅+成交量（非「维护中」）。

**风险/回滚**：缓存快照返回 T-1 旧值 → `is_estimated=True` + `as_of` 标注不伪装实时；单文件可回滚。

#### 14.6.2 R79 — 国内流动性注入（P1，双层修复）

**改动点（3 步，对应 §14.1 R79）**：
1. **prompt 接线**：`reports.py:140` `_build_report_prompt` 增 `domestic_macro: dict | None = None`；非 None 时将 LPR/中美国债/M0-M2/CPI-PPI 格式化为「### 国内流动性」段（模板 `:186` 第 3 章槽位现成）；`unavailable` 时注入「（国内宏观数据源暂不可用）」。
2. **stream 取数**：`analysis.py:311-328` llm_report_stream 读 `ctx.get("domestic_macro")` 传入 `_build_report_prompt`（`analysis.py:387` 现在 `[]` 占位处）；`macro_news` 若有数据不再传空。
3. **源侧独立超时**：`macro_fetcher.py:449-469` `fetch_all_domestic_macro` 现 `asyncio.to_thread` 无单源超时（一个慢源拖死整包 20s）→ 每源包 `asyncio.wait_for(..., timeout=8)`。

**测试清单**：
- 正：`_build_report_prompt(domestic_macro={"lpr": {...}, "bond_yields": ...})` → prompt 含「国内流动性」段与真实数字。
- 正：`domestic_macro={"unavailable": True}` → prompt 含「数据源暂不可用」。
- 负：prompt 不含「未提供国内利率信号」（LLM 输入侧负向断言）。
- 负：mock 一个源 sleep 15s → 其余源 8s 内返回、不被拖死（单源超时生效）。
- 集成：`verify_e2e` 或报告接口在源可用时第 3 章含真实 LPR/国债。

**风险**：prompt 变长 → token 预算增加（LLM 1200 字约束不变）；LLM 过度解读 → 限定「仅引用提供数据」。

#### 14.6.3 R80 — 行情数据 as_of + available 标注（P1）

**改动点（4 步，对应 §14.1 R80）**：
1. **as_of 来源**：`market_data_hub.py:_refresh_market_snapshot`（`:592-616`）成功刷新时记录 `_index_realtime_cache_ts`；失败分支（`:612-616`）不清 ts（保留上次成功时间）。
2. **缓存 TTL 标注**：`hub/_realtime.py:8-10` `get_index_realtime` 返回 `{"items": ..., "as_of": ts}` 或附带 `as_of` 字段；无 TTL 检查补 TTL 标注。
3. **报告读 available**：`reports.py:107` `_build_market_overview` `idx.get('price','N/A')` → 先读 `idx.get("available")`，不可用显示「数据源暂不可用」而非旧值/None；`_format_indices` 同改。
4. **报告注入 as_of**：`_build_report_prompt` 增 `as_of` 参数透传 → LLM 标注「数据截至 XX:XX」。

**测试清单**：
- 正：mock `_index_realtime_cache_ts` → 报告含「数据截至」。
- 正：`available=False` 指数 → 报告标注「数据源暂不可用」而非显示旧值。
- 负：同一指数在报告内不得出现两个不同数值（indices 与 market_data 取同一缓存域断言）。
- 集成：报告接口响应含 as_of 字段。

**风险**：as_of 语义多源（快照/实时/WS 三个域）——统一用「最新数据截至」单一口径，避免多 as_of 困惑。

#### 14.6.4 R82 — 美股自选实时批量窗口（P1，配额优先）

**改动点（方案 A 主选，对应 §14.1 R82）**：
1. **US 批量窗口放宽**：`market.py:799` `_batch_for(_us_items, "US")` 传 `timeout=7`（默认 2s 不变，仅 US 组放宽）——twelvedata 实测 2-6s/次，7s 窗口可容纳。
2. **外层联动**：`market.py:1072` `wait_for(_watchlist_enrich_items, 5)` → 仅当存在 US 标的组时放宽（如 5+US 批量耗时，设 8s）；无 US 组维持 5s（不回归）。
3. **last-good 补写**：`market_service.py:1374-1380` 批量被取消（`:1259` CancelledError）后后台线程返回成功结果时**仍写 `quote_key`（24h）**——消除 AAPL 每次请求重复退化。
4. **finnhub 配额护栏**：`global_markets_fetcher.py:509-542` 或 `_route_us`（`market_service.py:1388-1426`）读 `X-Ratelimit-Remaining`，低于阈值跳过 finnhub 直接诚实降级。
5. **方案 C 探针（D1，前置）**：twelvedata `/quote?symbol=A,B,C` 批量端点单次 HTTP 往返、计费方式（按 symbol vs 按请求）探针验证，失败不进实施。

**测试清单**：
- 正：mock twelvedata 3s 延迟 → US 批量 7s 内完成、`_batch_ok["US"]=True`、per-item 不被 `_skip_markets` 跳过。
- 正：批量成功后 quote 缓存 24h last-good 写入（AAPL 第二次请求不再退化）。
- 负：finnhub `X-Ratelimit-Remaining:5` → 跳过 finnhub 走降级（配额感知生效）。
- 负：批量超时后池内无残留任务（孤儿任务断言）。
- 集成（D3）：盘中美股自选显示真实实时价；盘后显示 last-good 收盘价（非「暂无实时」）。

**风险**：批量窗口放宽 → 慢源响应变长（≤8s 门禁）；仅 US 组放宽避免 A/HK 回归。回滚：仅改 `market.py:799/1072` 两处常量。

---

## 15. 分两批实施建议（不实施，等待指令）

- **批1（P0/P1 正确性/性能）**：R68（K 线缓存落盘保活 + long 池 + 盘后降级链）、R69（设计降级方案落地）、**R77（100%现金防御：remove_stale_candidates 全删守卫 + factor_matrix_empty 内层判空）**、R70（LLM 配额诚实降级）、R71（concept 补充分支入缓存 + TTL 1h + 后台 THS 同步 long 池/ETF_FAST_JSON）、**R78（自选收盘兜底缓存快照 + 并发信号量 + 孤儿任务消除 + 24h quote TTL + 补涨跌幅/成交量）**、**R79（国内流动性注入：prompt 接线 + 源超时）**、**R80（行情数据 as_of + available 标注）**、**R82（美股自选实时：方案 A 放宽 US 批量窗口 2s→7s + 外层联动，保持 twelvedata 主源；方案 B 快返回+后台刷新；方案 C twelvedata `/quote` 批量端点探针；护栏 finnhub `X-Ratelimit-Remaining` 配额感知；附带修复批量取消后 last-good 不写入，与 R78③ 孤儿任务合并治理）**。
- **批2（P2 治理）**：R72（分类词表）、R73（契约对齐）、R74（因子口径统一）、R64（portfolio a11y）、R65（macro/global 摘要）、**R75 残余（回填 yield/低优先级，主根因已修 `13839b3`，可选）**、R76（A 股个股搜索）、**R83（资讯徽章显示抽象：去数字星 + meta 行相对时间）**、**R84（美股搜索 suggest 兜底：新浪 suggest type=41 关键字补全 + 修 sync 新浪 JSONP parse bug + push2delay 换域名）**。

> **当前状态：等待「开始实施」指令，不写任何修复代码（R81 前端缺陷已于本轮会话直接修复，见 §14.5，不占用批1/批2）。** R77 由本地复盘（2026-08-19）补充——修复独立于 R68 数据源恢复，防止交易时段数据源抖动时复发；R78 由用户反馈驱动（2026-08-19 午休复验）——修复独立于任何数据源故障（源全部可用），根治「池繁忙时自选整列维护中」；R84 由用户反馈驱动（2026-08-19）——美股搜索 TQQQ 补全缺失，修复不依赖任何数据源恢复（suggest 为已实测可达的新源，EM spot 对 ETF 无效是数据层事实，见 §3.2）。

---

## 16. 多轮 review 记录

- **Round 1（证据链核查）**：对照代码与运行时输出逐条核查 file:line 与数据。修正：①R68 根因链补「`data/kline_cache.json` 不存在」的直接证据（`ls` No such file）与「`_persist` 仅在 `updated>0` 触发」的代码证据（`hub/_kline.py:301-308`）；②R57 判定从「无效」更正为「生效」（LLM 15s→103.6s，内层 connect=60s 已落地），R70 定位到配额节流 + JSONDecodeError 这一新失败原因；③搜索「bug」证伪——初测用 `?q=` 参数（实际为 `keyword`），改为正确参数后搜索正常，仅剩「茅台 0 结果」（R76）。
- **Round 2（「级联失效」框架确立）**：R58/R59/R60 从「各自无效」统一为「共享前置 K 线缓存冷（R68）的级联失效」——三者修复代码均在、单测绿，但盘后 K 线数据源不可用导致前置永不满足。这是「方法已应用 vs 目标已达成」的进阶形态：**「前置条件未满足」型失效**，与 round27 R43/R55 的「只改外层未改内层」「启动时跑一次」型失效并列。
- **Round 3（口径矛盾核查）**：R74 的「13/13 正常」vs「缺失 66.7%」vs「26/39」三处口径互斥经核对为真（strategy-check 响应三字段并存）。R73 stars 公式不符经核对契约 `stars = min(level + freshness, 5)` 与实测 level=1→stars=5 矛盾。均已定位到具体字段与文件。
- **Round 4（file:line 复核 + 新发现 R70b）**：对照代码复核关键定位——`llm/reports.py:538`（strategy_check connect=60 已改）、`:750`（`generate_design_report` 仍 connect=15.0，R57 只改了策略检查路径，设计报告路径同脆弱点，新增 R70b）；`task_manager.py:293-319`（R59② skip_refresh 重试在）、`:593-594`（「方案生成超时」仍是最终 error_msg）；`reports.py:556`（「interrupted after %.1fs (timed out or cancelled)」——timeout/cancel/JSONDecode 三类错误被同一文案吞并，印证 R70 的「超时掩盖真实原因」）。
- **Round 5（R77 新发现：组合设计「100%现金」失败，本地复盘 2026-08-19）**：`backend/logs/backend.log` 实证 task 571-582（08-18 15:52-16:08）+ task 597（08-19 11:33）共 9 次 `所有方案均为100%现金`。git 历史定位：`remove_stale_candidates` 引入于 `e727001`（07-20）、`factor_matrix_empty` 于 `9b1fa2e`（07-31）——均为潜伏缺陷；报错首次 08-18 15:52，旧轮转日志 0 次 → 触发条件「池非空 + 因子全空」由 R68 首次满足，属 R68 第 4 下游症状。新增 R77 修复设计（全删守卫 + 内层判空），并补入 §0.3/§2.5/§14.1/§14.4。
- **Round 6（R78 新发现：自选股「数据源维护中」根因反转，2026-08-19 午休窗口）**：用户反馈 A 股自选最新价/涨跌幅/成交量全显示「非交易时段无行情（数据源维护中）」，预期非交易时段显示收盘交易数据。初判「源冷却」被实测**证伪**——单发探针 `fetch_a_stock_batch` 0.25s/4行、sina_history 0.06s/240行，熔断器 mootdx/sina/tencent/sina_history/push2delay 全 closed，池空闲时 watchlist **3.81s 全量真实行情**。日志实证真凶：`run_sync queue depth=9→22 (fn=fetch_history) POOL SATURATION!`（12:43:16 / 12:44:51）+ `getKLineData?symbol=sh510500 200 None`（12:44:52，Sina 并发限流）+ `realtime enrich timed out after 5s → T-1 close fallback (R29)`（11:22 / 12:34）。定位四层自毁机制：批量超时泄漏孤儿任务（`run_in_executor` 无法中断同步任务）→ 背景刷新争池 → `_watchlist_close_fallback` 22 路并行洪泛 Sina → quote 5s TTL 无 last-good。新增 R78 修复设计（收盘兜底缓存快照 + 并发信号量 ≤3 + 孤儿任务消除 + 24h quote TTL + 补涨跌幅/成交量），补入 §0.3/§4/§14.1/§15。
- **Round 7（R79/R80 新发现：市场综合研判报告问题，2026-08-19 午间用户反馈驱动）**：用户反馈「A 股行情综合研判——行情数据与最新数据对不上 + 报告写『国内流动性：本次数据未提供国内利率信号』」。代码复核定位 R79 双层断裂——`llm_context.py:199-207` 采集 `ctx["domestic_macro"]` → `analysis.py:309-389` 只取 6 类键、**不读 domestic_macro** → `reports.py:140-207` `_build_report_prompt` 无该参数 → 模板 `reports.py:186` 却要求「国内流动性：货币与利率信号」；全后端 grep `domestic_macro` **0 生产消费点**（采集了没接上）。日志实证数据源层：`backend.log` 3 条 `build_full_context partial errors: ['domestic_macro: ']`（空错误 = 20s 超时）→ `{"unavailable": true}`。R80 定位多缓存域——`market_data_hub.py:526`（60s 后台 `_index_realtime_cache`）vs `market_service.py:108`（15s per-request `get_all_realtime`）vs 页面 WS（15s 推送）；`market_data_hub.py:615-618` 失败静默保留旧值；`reports.py:107` 不读 `available` 且无 as_of 标注。新增 R79/R80 修复设计（§14.1），补入 §0.3/§3.1/§15。均为 P1 报告质量/数据可信度问题，未改码。注：R78 的 §0.3 条目与 §4/§14.1/§15 由本轮并发补充，R79/R80 与 R78 同批记录（午休窗口用户反馈，代码级结构事实不受交易窗口影响）。
- **Round 8（R77/R68 归因修正：数据源盘后可用证伪，2026-08-19 13:00 实测）**：用户质疑「免费数据源收盘后应可取收盘数据、push2delay 应一直可用」→ 盘后同环境直接调用**证伪原归因**：`fetch_history('510300')` 240 rows、`_sina_history_cb` 240、`_baostock_history` 151、push2delay 200+真实行情、`factor_registry.compute(['510300','518880'])` 的 etf.price/etf.return_1m 均非 0。**数据源非不可用**。修正根因链：08-18 12:22-14:39 进程反复重启 7 次（warmup + 14:38:57 lifespan 日志实证）→ 内存 K 线缓存清空 → R59③ 落盘从未生效（updated>0 才落盘，冷缓存期 updated=0）→ 15:52 design 时 scanned 79 只但缓存仅覆盖 30 只（14:40:32 最后一次 `refresh_kline updated 30/30`）→ `_refresh_impl:334` 前 5 只无缓存触发全量 refresh_kline 重试 → 线程池饱和（15:52:45 `queue depth=9 (fn=fetch_history, timeout=8s)`、15:52:12-14 指数 get_history 8s 超时争抢）→ 二次 compute 仍空 → remove_stale 全删。同步修正 §0.3 R68、§2.5、§14.1 R68 行、§14.4.0 根因链（「盘后数据源不可用」→「重启清空缓存 + 落盘未生效」）。R77 缺陷 A/B 结论不变（仍为潜伏代码缺陷，独立于数据源状态）。
- **Round 9（R81 新发现 + 已修复：港股板块热度「AI 分析」空输入报错，2026-08-19 用户反馈驱动）**：用户反馈港股「板块热度」行点「🤖 AI 分析」报「请输入标的代码或名称」。前端定位——`UnifiedAnalysis.vue:310` externalTrigger watch 置 `activeMode='sector'` 后只写 `search.searchQuery`（symbol 实例），`doAnalyze`（`:384`）读 `activeSearch.searchQuery`（=sectorSearch，恒空）→ 空输入守卫 `:387` 抢先报错。**同 round26 Q5 quickSelect 缺陷类**（`quickSelect` 已修 `:325` 用 `activeSearch.value.searchQuery`），externalTrigger 路径漏修。修复：`:314` 改 `activeSearch.value.searchQuery.value = trig.query`；新增 Q6 回归测试 2 例（sector / index 模式 externalTrigger 写回 + `error` 不含「请输入标的代码或名称」+ startStream 收到正确 body）。验证：`UnifiedAnalysis.spec.js` 31 passed、`vite build` 通过。后端 HK 板块 Phase 5.1 友好提示（`analysis.py:517-533`）逻辑不受影响，此前被前端空输入守卫掩盖；修复后港股板块 AI 分析正常进入 sector 请求并返回友好提示。已补入 §0.3（第 11 项）、§14.5（已实施表）、本文档头部例外说明。
- **Round 10（R82 新发现：美股自选「暂无实时」——US 批量 2s 窗口 vs twelvedata 2-6s 延迟，2026-08-19 13:5x 实测复现，用户反馈驱动）**：用户反馈美股自选（AAPL）最新价有值但涨跌幅/成交量「暂无实时」。实测 watchlist 响应 3.88s：TSLA/QQQ/SPY `src=stale` 三字段全值、AAPL `price=310.03 chg=None vol=None is_estimated=True realtime_unavailable=True`。日志实证 `[watchlist] US batch realtime failed (fallback per-item)`（`market.py:785`）+ twelvedata 建连→响应 2-6s（13:53:37→13:53:39-43；13:56:50 建连→13:56:51 批量取消）。定位：`_batch_for` 2s 窗口（`market.py:776`）< twelvedata 实际延迟 → 批量必超时 → `_skip_markets`（`market.py:821-830`）跳过 US 全部 per-item（8s 窗口本可容纳）→ 降级链只回补部分字段（quote-cache stale 全值 / `_last_close_fallback` 只 price+`is_estimated=True` / 全空「暂无实时」）。附带 bug：批量取消后 last-good 写入不执行（`market_service.py:1374-1380` 在 `:1259` CancelledError 之后），AAPL 每次请求重复退化。额度盘点：twelvedata **800次/天**（宽裕）慢、finnhub **60次/分**（紧）快（实测 ~1s、200 OK、`X-Ratelimit-Remaining:59`）但排第二轮不到、tickflow 免费层限流 429；**「finnhub 前置」会烧穿 60/min**（4 只 × 12 次刷新/min ≈ 48/min）——修复须配额优先。修复设计（§14.1 R82）：方案 A 放宽 US 批量窗口 2s→7s + 外层联动、保持 twelvedata 主源；方案 B 快返回 + 后台刷新（延迟与配额解耦）；方案 C twelvedata `/quote` 逗号分隔批量端点（单次 HTTP 往返，免费层计费方式需探针）；护栏 finnhub `X-Ratelimit-Remaining` 配额感知；附带修复 last-good 不写入。孤儿任务机制与 R78③ 同源，合并治理。新增 R82 修复设计（§0.3 第 12 项 / §0.4 / §4 / §14.1 / §15），**未改码**。
- **Round 11（R83 新发现 + 方案采纳：资讯徽章显示抽象，2026-08-19 用户反馈驱动）**：用户反馈新闻卡徽章 `[4 其他]` 中的数字「4」太抽象（第一反应是数组序号/重要程度）。定位：徽章混排 `stars` 新鲜度数字（4=<6h，`news_fetcher.py:228 _compute_stars`）与 `category` 分类文字；与顶部重要性筛选 `★★★★ 重要`（`NewsView.vue:46`）视觉撞车易误读为重要度；且新鲜度=时间，meta 行已显示绝对时间（`NewsView.vue:101`）——数字星是重复的二次编码。提出 4 个优化方案（A 去数字+相对时间 / B 文字桶 / C 视觉化 / D 只去数字），**用户采纳方案 A**：徽章只留分类彩色标签（`other` 不显示标签，灰边灰标题表意），meta 行改相对时间（`3小时前`/`刚刚`），数字彻底移除。已补入 §0.3（第 13 项）、§6、§14.3、§15 批2。设计仅入档不实施，等待「开始实施」指令。
- **Round 12（R84 新发现 + 方案采纳：美股搜索 TQQQ 补全缺失，2026-08-19 用户反馈驱动）**：用户反馈美股「标的分析」输入 `TQQ` 无自动补全。实测 `/market/search?keyword=TQQ&market=US&include_stocks=true` → `[]`（QQQ/SPY/AAPL 正常），定位为后端 `search_hk_us` 三级数据源全断：①静态基座 curated 无 TQQQ；②EM spot **双失败并修正此前错误推断**——`72.push2.eastmoney.com` 间歇断连（实测 16 页仅 5 页成功，`RemoteDisconnected` 约 70%，非域名不可达；`push2delay` 16/16 全通）**且 `fs=m:105,m:106,m:107` 是纯股票列表、实测不含任何 ETF**（Q 区整个缺失、T 区无 TQQQ/TLT、S 区无 SPY/SOXL）——即「EM spot 是唯一含 TQQQ 数据源」的旧推断错误，换域名/等网络恢复对 ETF 均无效；③instruments US 段 0 行（同步失败）。附带发现真实 bug：`sync_instruments.py:276-281` 新浪美股 JSONP 解析按数组假设、实际返回 `CallbackList[]({...})` 对象 → 降级链从未生效；且每页 20 条按市值降序前 120 只不含 TQQQ。**关键新发现**：新浪 suggest `suggest3.sinajs.cn/suggest/type=41&key=TQQQ` 可达（0.1s）、**含 ETF**（TQQQ→「纳斯达克指数ETF-ProShares三倍做多」/SOXL/SPXL/QQQ 全中）、GBK 编码、天然前缀匹配、代码 0 引用——采纳为搜索兜底源。修复设计（§14.3 R84 / §15 批2）：①suggest type=41 兜底（EM spot 空时按关键字调、负缓存 60s）；②修 sync JSONP parse bug（US 段灌入前 120 只个股）；③push2delay 换域名（仅个股有益，勿误以为救 ETF）。已补入 §0.3（第 14 项）、§3.2、§14.3、§15、§0.4。设计仅入档不实施，等待「开始实施」指令。
- **Round 13（本轮：对照当前代码全量复核 + 重大项细化至实施标准，2026-08-19）**：对 doc 全部 file:line 引用与当前工作区代码（含 R75 修复 `13839b3` 后）逐条复核，修正 6 类问题：
  1. **R75 状态修正（P2→已实施）**：`13839b3`（2026-08-19）已修 advance_decline 同步阻塞（`run_in_thread`+`future.result()` → `await run_sync` + 60s TTL 缓存），/health 50s+→6ms。§0.3/§14.2/§14.4.1/§15 全部更新，「回填 yield/低优先级」降为可选残余优化。
  2. **R73 归因修正（实现非 bug，契约过时）**：`_compute_stars`（`news_fetcher.py:228-240`）是 round9 P2-1 **刻意「纯新鲜度」设计**（<1h→5★/…/更旧→1★），非「隐藏 boost」；契约 `all.md:84`（`min(level+freshness,5)`）过时且自相矛盾（`:3` stars=level、`classification.md:16` 新鲜度维度）。修复方向改为「更新契约对齐实现」；R83 移除徽章数字星后展示影响消失，R73 降为 P3 文档对齐。
  3. **R71 归因拆分（端点非 THS）**：`/sectors/concept` 热路径 = `fetch_concept_sectors`（`sector_fetcher.py:240`，主源已 60s 缓存，**补充分支 `_ak_concept_sectors_v2()` `:259` 在 cached 外每请求必跑** → 热态 17s）；预热 45.7s THS 热点来自 `_background_indices_meta_sync`（`main.py:238-245` → `sync_indices_meta.py:102/129`），非端点。修复设计改为「补充分支入缓存 + TTL 60s→1h」+「后台 THS 同步改 long 池 / ETF_FAST_JSON」。
  4. **R68 缺口精确化**：原「部分成功也落盘（而非 updated>0）」表述不准确——当前代码 `updated>0` 已含部分成功。精确缺口：①**updated==0 时不落盘 → 磁盘缓存 mtime 不刷新 → `_load_kline_cache_sync` 24h TTL 判过期丢弃**（`hub/_kline.py:144`）；②**池饱和饿死 refresh_kline**（生产实况，与 R78 同源）；③无 last-good 兜底。修复设计改为「persist 条件放宽到 `if self._kline_cache_rows`（mtime 保活）+ fetch 改 `run_sync_long`（long 池）+ 失败保留旧缓存」。
  5. **文件指针修正**：R74 → `portfolio/strategy_check.py:196-213`/`portfolio/formatting.py:226`/`signal.py:92`（原写 strategy_check_worker/portfolio_service）；R72 → `levistock_fetcher.py:25-145` `_CATEGORY_KEYWORDS`（原写 news_fetcher，且「地震」已在 major 但「强震」未收录）；R84 静态基座行号 `market_service.py:610-641/644-660`（原写 624-638/662-679）。
  6. **新增 §14.6**：R78/R79/R80/R82 从「修复方向」细化到「实施步骤（当前行号锚点）+ 测试清单（正/负向断言）+ 风险回滚」，与 §14.4（R68/R69/R77）并列达实施标准。
  另复核确认的准确引用（无修改）：`strategy_design.py:305`、`risk_controls.py:160-193`、`task_manager.py:370/593`、`reports.py:140/186/750`、`analysis.py:311-328/387`、`llm_context.py:200-207`、`market.py:772-787/821-830/1033/1072`、`market_service.py:1029/1259/1374-1380/1440-1473`、`sync_instruments.py:276-281`、`china_market.py:1037-1088`、`hub/_realtime.py:8-10`、`factor_registry.py:1489/1503`、`factor_aggregate.py:136-138`、`async_utils.py:103-118`、`global_markets_fetcher.py:509-542`、`NewsView.vue:85-86/101/46`、`WatchlistPanel.vue:135-159`。**未写任何修复代码**。

> **当前状态（Round 1-13 完成）**：R68-R84 均达实施标准（精确 file:line + 根因 + 验收 + 负向断言）；R68/R69/R77 已展开为实施级详细设计（§14.4），**R78/R79/R80/R82 已细化至实施级（§14.6：改动点 + 测试清单 + 风险回滚）**，R79/R80 为报告质量修复（§14.1），**R82 为美股自选「暂无实时」修复设计（§14.1/§14.6，配额优先原则：方案 A 放宽批量窗口保持 twelvedata 主源 / 方案 B 后台刷新 / 方案 C 批量端点探针 / finnhub 配额感知护栏），R83 为资讯徽章显示抽象修复设计（§14.3，去数字星 + meta 行相对时间），R84 为美股搜索 suggest 兜底修复设计（§14.3，新浪 suggest type=41 关键字补全 + 修 sync JSONP parse bug + push2delay 换域名），R81 为唯一已实施项**（前端 externalTrigger 写回修复，§14.5），**R75 主根因已实施（`13839b3`，§14.2 标为已实施 + 残余可选）**。**Round 8 归因修正**：R68/R77 的「盘后数据源不可用」经实测证伪——数据源盘后可用，失效点是「进程重启清空内存缓存 + 落盘 mtime 不刷新/从未生成 + R77 全删缺陷」。**Round 10 补充**：R82 根因为「US 批量 2s 窗口 vs twelvedata 2-6s 延迟」的结构性不匹配，非源故障。**Round 11 补充**：R83 根因为「徽章数字星是时间的二次编码，抽象且与 meta 行 time 重复」的前端展示问题，非数据问题。**Round 12 补充**：R84 根因为「EM 美股 spot 纯股票不含 ETF（数据层事实）+ 72.push2 间歇断连（网络层，push2delay 可修）+ sync 新浪 JSONP 解析 bug」，并发现已实测可达的新源新浪 suggest type=41（含 ETF）作为兜底。**Round 13 补充**：R75 状态修正（已实施）、R73 归因修正（契约过时非实现 bug，方向改契约对齐）、R71 归因拆分（端点热路径非 THS，补充分支未入缓存 + 后台索引同步占池）、R68 缺口精确化（mtime 保活 + long 池 + 保留旧缓存）、R74/R72/R84 文件指针修正、新增 §14.6 实施级设计。本文档除 R81 外**不写任何修复代码**，等待「开始实施」指令。

- **Round 14（2026-08-19 实施轮：R68-R84 全部落地，TDD 契约驱动）**：按本文档方案实施，先写测试与契约、再改功能代码。全部实施项（除已完成的 R75/R81/R73 契约对齐）：
  - **R68**（`hub/_kline.py`）：`refresh_kline` 落盘条件 `updated>0`→`缓存非空`（mtime 保活）、fetch 改 `run_sync_long`（long 池）、失败/空保留 last-good + `mark_kline_stale`；新增 6 测试。
  - **R69**（`task_manager.py` + `strategy_design.py`）：二次采集超时不再 failed「方案生成超时」，转 `build_static_degraded_design`（零网络静态池，`degradation.mode=degraded`）；`DESIGN_DEGRADE_RETRY_TIMEOUT` env；新增 6 测试。
  - **R77 收口**（`strategy_design.py`）：allocate 后置守卫——空矩阵 + 全现金 → 静态等权方案（`static_pool`）；测试放行引擎部分持仓（`partial_data`）。
  - **R70**（`reports.py`）：策略检查兜底 summary 按最后错误诊断区分「配额耗尽（429）/解析失败/超时」；`strategy_check.py` `_llm_failed` 识别三类文案；**R70b**：`generate_design_report` connect 15→60s。
  - **R71**（`sector_fetcher.py` + `ttl.py` + `sync_indices_meta.py`）：concept 补充分支 `_ak_concept_sectors_v2` 入缓存（1h）、`sector_concept`/`sector_concept_v2` TTL 1h、THS/新浪 4 fetch 改 `run_sync_long`；新增 5 测试。
  - **R74**（`signal.py` + `strategy_check.py`）：composite reason 自描述「分项覆盖 X% < 60%」、summary 改「因子填充率 X%（键级聚合 `factor_fill_pct`）」；新增 4 测试。
  - **R76**（`market.py`）：levistock 空结果打 WARNING、兜底分支拼音匹配（pypinyin）；新增 5 测试。
  - **R78**（`market.py` + `market_service.py`）：`_watchlist_close_fallback` Semaphore(3) + 单条 3s + 收盘行写 quote 缓存（24h，`estimate_source=last_close` 短路）；A 批量 quote TTL 5s→24h；`_last_close_fallback` 补 change_pct/volume；新增 7 测试。
  - **R79/R80**（`reports.py` + `analysis.py` + `macro_fetcher.py` + `hub/_realtime.py`）：`domestic_macro` 注入 prompt、`_MACRO_SOURCE_TIMEOUT` 单源 8s、`available=False` 渲染「数据源暂不可用」、`as_of` 时效标注（`get_index_realtime_as_of` 真实快照时间）；新增 14 测试。
  - **R82**（`market.py` + `market_service.py` + `global_markets_fetcher.py`）：US 批量窗口 2s→7s + 外层联动 5s→8s（仅 US 组）；US 路由 shield + 后台 last-good 补写；finnhub 滑动窗口配额护栏（50/min）；新增 6 测试。
  - **R83**（前端 `NewsView.vue`）：徽章去数字星、meta 相对时间（已在前轮落地，本轮 28 测试全绿）。
  - **R84**（`market_service.py`）：suggest 兜底函数改名 `_us_suggest_fallback`/`_fetch_us_suggest_sync` 规避 async-lint 误报。
  - **R81**（前端 `UnifiedAnalysis.vue`）：externalTrigger 写回（前轮已落地，31 测试全绿）。
  - **验证**：后端 2376 passed / 0 failed（全量，网络/性能类排除）；前端 497 passed + `vite build` 通过。回归校准：`test_watchlist_realtime_parallel_slow_source_not_blocking` 阈值 7→10s（R78 收盘兜底 3s 预算，并行性断言不变）。
