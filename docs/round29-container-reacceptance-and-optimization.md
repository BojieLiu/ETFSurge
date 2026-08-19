# round29 容器重建 + 全量验收与优化方案（2026-08-19）

> 本文档为 round28 R56-R67 及「代码健康 + 巨型文件拆分」方案全部实施后的**新一轮 Docker 重建 + 16 项全量验收**结论与剩余问题修复设计。
> **本文档仅设计修复方案，不实施。** 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」撰写。
> 验证环境：Docker Desktop Engine 29.7.2 / Compose v5.4.0，prod profile 重建启动，后端 :8000 / 前端(nginx) :80；`PROFILE_WARMUP=1`（预热诊断，`docker-compose.diag.yml` override）。后端镜像 `b01ec96cd6c2`、前端 `5b55e189d243`。
> 验证窗口：2026-08-19 00:53–01:20（北京时间，**周三凌晨盘后**）。盘后/数据源冷却成分见 §0.4。

---

## 0. 执行摘要

### 0.1 本轮性质
round28 的 R56-R67 已在 `6935ac9` + `3807497` + `76b15ef` 实施；「代码健康 + 巨型文件拆分」方案已全批次实施并 push。本轮用**全新 Docker 镜像 + 16 项动作**复验落地情况，识别出**「修复已落地但运行时目标未达成」的残留问题**。

**核心结论：round28 的 R56/R57/R61/R62/R63/R67/R50 已真正生效；但 R58/R59/R60 三项「修复」因共同根因——「盘后 K 线数据源（mootdx/tickflow）不可用 → K 线缓存从未被填充」——而运行时结果与修复前相同或仅部分改善。这是一个「前置条件未满足 → 级联失效」的系统性问题，非单个修复点的 bug。**

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
| 15 | 综合结论 + 修复方案 | 本文档（R68-R76 修复设计，达实施标准不实施） |
| 16 | 回收容器 + 归档 + commit/push | 见 §16 与结尾 |

### 0.3 问题分级（本轮新发现，危害驱动）
- **P0（投资判断/数据可信度）**
  1. **R68 — 「K 线缓存冷」级联失效（R58/R59/R60 的共同根因）**：盘后 mootdx/tickflow 两源均不可用（`tickflow 429 Too Many Requests`、`mootdx returned empty`），`refresh_kline` 从未成功 → `_kline_cache_rows` 恒空 → 三个下游修复全部失效：①IC 回填 3 次重试后放弃（R58）→ 因子模型仍 27 因子 no_data；②组合设计 K 线冷建库超时（R59）→ 设计失败；③symbol-analysis K 线兜底取空（R60）→ 600519 技术面「K线为空」。**「方法已应用但目标未达成」的典型——修复代码在、测试绿，但运行时结果与修复前相同。**
- **P1（正确性/性能）**
  2. **R69 — 组合设计仍超时失败（R59 目标未达成）**：设计 595 走完「off-hours 降级（R59⑤）→ skip_refresh 重试（R59②）」全链，仍在数据采集阶段 90s 超时（`task 595 timed out`）。根因：skip_refresh 只跳过 `refresh()`，但后续 `get_history`/K 线采集仍逐一走 tickflow（429），单标的 500 根 K 线串行/并发受限 → 冷建库 >90s。R59③（K 线缓存落盘 `data/kline_cache.json`）已实现但**该文件从未被成功生成**（见 R68），故冷启动无缓存可加载。
  3. **R70 — 策略检查 LLM 仍不可见（R57 生效但配额节流）**：R57（内层 `connect=15s→60s`）已生效——LLM 从 15s `CancelledError` 变为 103.6s 才放弃。但最终失败原因是 `JSONDecodeError`：`opencode_zen` 配额耗尽 429 → 全局暂停 60s + DeepSeek 每次调用被 `llm_quota_gate` 节流 5.7-6.5s → 103.6s 内未能完成 JSON 结构化输出。专业投资者仍拿不到 AI 策略检查报告，但**换了一个失败原因**（配额节流而非连接超时）。
  4. **R71 — sectors/concept 端点 36.8s 冷 / 17.1s 热（persistent 性能债）**：akshare `stock_board_concept_index_ths` 单次调用 45.7s 累计（cProfile），且「热态」仍 17s——概念板块表未进缓存或 TTL 过短，每次请求触发 THS 概念板块全量拉取。预热已覆盖 sector/etf/indices，但 concept 列表未纳入。
- **P2（治理/呈现）**
  5. **R72 — 资讯分类欠分类**：`哥伦比亚强震已致304人死亡`（自然灾难，契约应 major=5）、`欧洲股市录得去年末以来最长连跌`（市场利空，应 ≥3）、`俄方：瑞典扣留涉俄货船`（地缘，应 ≥4）均被判为 `other`（level 1）。本地关键词分类器未覆盖「强震/连跌/扣留」等场景。
  6. **R73 — 资讯 stars 公式与文档不符**：headlines 多条 level=1 条目 stars=5，与契约 `stars = min(level + freshness, 5)`（level 1 + freshness ≤2 → stars ≤3）矛盾。需确认实现是否有隐藏的 boost。
  7. **R74 — 策略检查因子口径标签矛盾**：`summary="因子数据13/13正常"` vs `composite_decision.reason="因子数据缺失 66.7%"` vs `factor_availability={"filled":26,"total":39,"ratio":"26/39"}`——「13/13 正常」「缺失 66.7%」「26/39 已填」三者口径互斥，专业投资者无法判断因子数据真实可用性。
  8. **R75 — 组合设计/策略检查在「IC 回填 CPU 饱和」期间请求被抢占**：IC 回填（R58）CPU 循环独占事件循环期间，`GET /tasks/{id}` 轮询请求超时（实测 75.6s）。R58 的已知性能债（回填慢 ~10s/compute）在冷启动 + 设计并发时放大为可用性事故。
  9. **R76 — A 股个股中文名搜索（茅台）返回 0 结果**：`instruments` 表 A 股个股 0 条，搜索完全依赖 levistock 降级 `get_all_stocks`，盘后/源冷时静默返回空（无 WARNING 日志）→ 「茅台」搜不到 600519。

### 0.4 验证窗口标注（D3）
本轮执行于 2026-08-19 00:53–01:20（**周三凌晨盘后**）。以下结论含盘后/数据源冷却成分，属「待交易时段复测」：AAPL 整链 DATA_UNAVAILABLE、600519 技术面 K 线空（R60）、A 股个股搜索空（R76）、组合设计超时（R69）、IC 回填放弃（R68）。但「sectors/concept 热态 17s（R71）」「策略检查因子口径矛盾（R74）」「资讯分类欠分类（R72）」「stars 公式不符（R73）」「预热墙钟 56.5s 超预算（R68 前半）」均为**代码级结构事实，不受窗口影响**。

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

---

## 3. A/HK/US 行情分析（AI 内容审阅）

**first_byte 实测（R49 已生效）**：advice 0.053s / 600519 0.007s / 00700 0.004s / AAPL 0.005s / sector 0.01s —— 从 round28 的 26-111s 全面改善到毫秒级。

- **AI 投顾（综合研判）✅ 高质量**：真实数据（上证 3990.30 +0.19%、深成指 -0.56%、创业板 -0.92%、科创50 +0.11%）、市场阶段判断（横盘消化）、风格（扩散初期：农业种植/机器人/光通信多点开花）、资金行为（存量主导）、风险（欧洲股市连跌/地缘/大宗商品）、三档配置（进攻/平衡/防御 + 权重表）。逻辑严谨、数据与最新行情匹配。
- **个股 600519 ✅ 基本面高质量，❌ 技术面空（R60）**：基本面真实（2026H1 营收 922.78 亿 +1.30%、归母 445.17 亿 -1.95%、Q2 环比 -36%）、机构预测、估值推算（动态 PE 18.9x）、资讯催化、风险提示均专业；但「技术面分析 - 数据限制：提供的技术指标为空，历史K线无数据」—— 而 `/market/indicators/600519` 同窗口返回 `data_available=false`（K线 <30）。**R60 的 Hub 缓存兜底（`get_kline_rows_any`）已实现，但缓存为空（R68）→ 兜底取空 → 仍诚实标注 K 线空。**（诚实降级本身正确，问题是 K 线数据源盘后不可用。）
- **个股 00700 ✅ 完整高质量（R61 已生效）**：真实完整技术面（MA5=446.28/MA10=463.38/MA20=461.79/MA60=453.43 空头排列、RSI 41.97、KDJ K=17.03 D=27.59 J=-4.09 超卖、MACD DIF=-2.38 DEA=2.31 柱 -9.40 动能增强、布林带中下轨）、基本面（南向净买入 5.34 亿、年内回购 267 亿港元）、历史 K 线关键节点。round28 的「00700 整链 DATA_UNAVAILABLE」已彻底修复。
- **个股 AAPL ❌ DATA_UNAVAILABLE**：`/market/realtime/AAPL` 有数据（price 310.745 +1.69%），但 `history/AAPL` 空（美股 K 线源盘后不可用）→ symbol-analysis 数据全空 → `DATA_UNAVAILABLE`。R53 的美股指数分析（SPX）本轮未复测。
- **板块 BK1036（半导体）❌ 「暂无数据」**：`sector_code=BK1036` 在 `sectors/industry` 表**确实存在**（496 条中含 BK1036 半导体），但 sector-analysis 返回 `板块「BK1036」数据源暂无数据（板块表未收录或数据源缺失）`——成分股数据源盘后缺失，错误文案「板块表未收录」误导（板块表已收录）。
- **搜索自动补全 ✅（keyword 参数）**：`银`→银行ETF博时/富国/南方；`腾讯`→腾讯云(板块)/腾讯济安(指数)/00700(港股)；`苹果`→AAPL/苹果概念；`AAPL`→苹果。中文回显正确。
  - ⚠️ **R76**：`茅台` 返回 0 结果（`instruments` 表 A 股个股 0 条，levistock 降级 `get_all_stocks` 盘后静默返回空）。

**专业投资者是否接受**：AI 投顾/茅台基本面/腾讯完整分析达专业水准，first_byte 毫秒级体验达标；但 **A 股个股缺技术面（R60）、美股个股 DATA_UNAVAILABLE、板块分析「表已收录却报未收录」、个股中文名搜不到（R76）**，专业投资者对「技术面缺失」与「板块/个股数据链路盘后不可用」不可接受。

---

## 4. 热点 + 自选

- **热点 ✅**：`hot-plates` 返回真实数据（农业种植 +9.95%，lead 金健米业 2天2板、农发种业 2天2板，reason 含全球粮食危机催化）；`stock-hot-rank` 50 条（京东方A +6.41%、一鸣食品 +10% 16天11板、爱丽家居 +10.01% 21天12板）。
  - ⚠️ `hot-plates` 首次请求 60s 超时（冷 + 与 IC 回填 CPU 饱和争抢事件循环），二次 0s；`stock-hot-rank` 首次 56.6s（同因），热态 0.44s。
- **自选 ✅（R45 延续 + 全链路）**：22 条；部分带 `realtime`（`is_estimated:true, estimate_source:"last_close"`），部分诚实 `realtime:null + data_unavailable:true + realtime_note:"非交易时段无行情（数据源维护中）"`。add（513050 → id=28）→ DB 持久化 → GET 返回 → DELETE 204 全链通过；重复 add 409 去重正确。

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
- ⚠️ **R73 stars 公式不符**：多条 level=1 条目 stars=5（契约 `stars = min(level + freshness, 5)` 下 level 1 + freshness≤2 应 ≤3）。需确认实现是否有隐藏 boost（如财联社 editorial +1 只应作用于 level 非 stars）。
- ⚠️ **R65 覆盖不完整**：headlines 7/12 非 null（round28 全 null，已改善），但 macro 2/7、global 1/8 仍 null —— 规则摘要 `_rule_news_summary` 仅覆盖 headlines 高重要性条目，macro/global 未回填。
- 智能分析（AI）：因 LLM 配额耗尽（R70 同源），本轮新闻 AI 摘要走规则兜底，未观测到真 LLM 摘要。

---

## 7. 因子模型

- ❌ **R58 回填放弃（R68 级联）**：`/factors/active` 仍 `valid=0 / no_data=27 / static=11 / observable=0`。
- 日志实证：`[ic_backfill] K 线缓存未就绪（第 1/2/3 次检查），30s/60s/120s 后重试（R58）` → `[ic_backfill] K 线缓存未就绪（重试 3 次后放弃），历史回填跳过——预热未完成或 refresh_kline 未执行（R58）`。
- 生产库 `factor_ic_records`：`177 条 / 6 个 distinct trade_date（2026-08-14~19）`——round28 为 4 个，略有进展（重试机制生效期间捕到 2 个新交易日），但远未达 ≥60 目标。
- 根因链：`refresh_kline` 依赖 `fetch_history` → mootdx 空 + tickflow 429（盘后）→ `_kline_cache_rows` 从未填充 → ①IC 回填放弃（R58）；②因子模型 no_data；③R60/R69 同根。

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

**核验结论**：round28 的 13 项修复中 **7 项真正生效**（R56/R57/R61/R62/R63/R67/R50）、**3 项「已实施但级联失效」**（R58/R59/R60，共同根因 R68：K 线缓存冷）、**2 项部分**（R64/R65）、**1 项待复测**（R66）。R58/R59/R60 是「方法已应用、前置条件未满足、目标未达成」的典型——修复代码在、单测绿，但盘后 K 线数据源不可用导致三者的共同前置（已填充的 K 线缓存）无法满足。

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
5. **R72/R73（资讯分类/stars）**：news 分类单测覆盖了「停牌/违约/机构名」等词表治理场景，但无「自然灾难→major」「市场连跌→negative」「地缘扣留→risk」的**新增场景负向断言**；stars 公式无「level=1 且 stars=5 应失败」的断言。
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

## 14. 修复方案总表（R68-R76，不实施）

### 14.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R68 | P0 | K 线缓存冷级联失效（R58/R59/R60 共同根因） | ①**K 线缓存落盘「部分成功也落盘」**：`refresh_kline` 改为每个 symbol 成功即写缓存 + 定期落盘，而非仅 `updated>0` 整体落盘；②**盘后 K 线源降级链**：mootdx 空 + tickflow 429 时回退 last-good 收盘快照（同 R45 模式），保证盘后至少有 T-1 收盘 K 线；③**启动时若磁盘缓存存在则必加载**（已实现 `_load_kline_cache_sync`，但需保证有数据可加载——依赖①） | ①盘后冷启动后 `get_kline_rows_any(510300)` 非空；②因子模型 valid 因子数 >0；③负向：K 线缓存空时 IC 回填/设计/分析三链须**诚实降级并重试**，而非静默放弃 | `hub/_kline.py:175/265`、`factor_registry.py:1326`、`main.py:75` |
| R69 | P1 | 组合设计仍超时失败（R59 目标未达成） | ①R68 落地后，skip_refresh 重试走磁盘缓存 K 线（消除逐标的 tickflow 冷建库）；②设计数据采集的 K 线部分**并发上限 + 单标的短超时**（现 Semaphore(5)×20s 但 tickflow 429 时每标的仍重试）；③「数据采集超时」时用已采集部分 + 快照**产出降级方案**而非 failed（R59② 的「超时→降级」仍未真正产出方案） | ①盘后首呼 design 产出 `degradation.mode=degraded` 方案（非「方案生成超时」失败）；②负向：禁止「方案生成超时」空响应 | `task_manager.py:570`、`strategy_design.py`、`hub/_kline.py` |
| R70 | P1 | 策略检查 LLM 配额节流 → 规则兜底 | ①策略检查 LLM 失败后，summary 明确区分「配额耗尽（429）」vs「超时」vs「JSON 解析失败」，并给出可读原因；②配额耗尽时**主动降级为结构化规则报告**（现有规则兜底已做，但 summary 文案「LLM 分析超时（104s 未返回）」掩盖了真实原因「配额耗尽 + JSONDecodeError」）；③（可选）策略检查 LLM 结果 JSON 解析加 `response_format=json_object` 或重试 | ①配额耗尽时 summary 含「配额」关键词而非「超时」；②负向：不得用「超时」掩盖 429/JSONDecodeError | `llm.py` 策略检查段、`strategy_check_worker.py` |
| R70b | P2 | 设计报告 LLM 仍 `connect=15.0`（同 R57 类脆弱点） | `reports.py:750` `generate_design_report` 仍 `httpx.Timeout(connect=15.0, read=120.0)`——strategy_check 路径（`reports.py:538`）已改 60s，但设计报告路径未改，DeepSeek 慢连接 >15s 时同样 `CancelledError`。注释标「connect 15s 防 429/挂起」为刻意取舍，但应评估是否对齐 60s 或加「慢连接重试」 | ①设计报告在 DeepSeek 慢首字节时能产出（非引擎兜底）；②负向：connect 15s 不再先于 read 120s 触发 | `reports.py:750` |
| R74 | P2 | 策略检查因子口径矛盾（13/13 vs 缺失66.7% vs 26/39） | ①统一「因子可用性」单一口径：summary 与 composite_decision.reason 与 factor_availability 三处用同一数值（如「因子填充 26/39 = 66.7%，综合信号降级」）；②summary 的「因子数据 N/M 正常」改为「因子填充率 X%」 | ①三处数值一致；②负向：禁止「13/13 正常」与「缺失 66.7%」并存 | `strategy_check_worker.py`、`portfolio_service.py` |

### 14.2 性能

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R71 | P1 | sectors/concept 36.8s 冷 / 17.1s 热 | ①概念板块列表（`stock_board_concept_index_ths`）纳入缓存（Redis/磁盘快照，TTL 如 1h），热态命中缓存；②预热 sequence 增「concept 板块预热」（后台 + 预算，同 F3 模式）；③THS 概念板块用 `ETF_FAST_JSON=1` shim 加速 demjson（45.7s 累计 CPU） | ①热态 concept ≤1s；②冷态 ≤10s；③负向：热态不得重新触发 THS 全量拉取 | `sector_fetcher.py:479`、`market_trends.py:128`、`main.py` |
| R75 | P2 | IC 回填 CPU 饱和抢占请求 | ①IC 回填的时光回溯循环（~10s/compute × 500 交易日）**分批 yield 让出事件循环**（每 N 次 compute `await asyncio.sleep(0)`）；②回填放低优先级（独立线程池或 `asyncio.to_thread`），不占主事件循环 | ①回填期间 `/health` 与 `/tasks/{id}` 延迟 <1s；②负向：回填期间普通请求不得超时 | `ic_tracker.py`、`main.py:_backfill_ic_history_task` |

### 14.3 治理 / 呈现

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R72 | P2 | 资讯分类欠分类（自然灾难/市场波动/地缘 → other） | ①词表补「强震/地震/海啸/台风/洪水/灾难」→major=5；「连跌/暴跌/收跌/走弱」→negative≥3；「扣留/扣押/袭击/开战」→risk≥4；②补负向单测 | ①强震→5、连跌→3、扣船→4；②负向：三类不得落入 other | `news_fetcher.py` 分类段 |
| R73 | P2 | 资讯 stars 公式与文档不符 | ①核对 stars 计算实现，若有隐藏 boost 需与契约 `stars=min(level+freshness,5)` 对齐或更新契约；②补「level=1 → stars≤3」断言 | ①level=1 且 stars=5 不再出现 | `news_fetcher.py` stars 段 |
| R65 | P2 | 资讯摘要 macro/global 仍 null | ①规则摘要 `_rule_news_summary` 扩展到 macro/global 高重要性条目；②或复用 headlines 的规则摘要生成器 | ①macro/global 高重要性条目 ai_summary 非 null | `market_data_hub.enrich_news_summaries`、`news_fetcher.py` |
| R64 | P2 | portfolio-analysis a11y 86（R51/R64 延续） | ①跑 Lighthouse a11y 明细定位未达标对比度元素（portfolio-analysis 局部组件，非全局 theme.css）；②针对性修对比度 | ①portfolio-analysis a11y ≥90 | `PortfolioAnalysis.vue`、`AnalysisView.vue` |
| R76 | P2 | A 股个股中文名搜索（茅台）返回 0 | ①`_search_a_stocks` 的 levistock 降级失败时**回退 instruments 表 + 拼音首字母**（当前 instruments 表 A 股个股 0 条是数据缺口，需补同步）；②levistock 失败加 WARNING 日志（当前静默）；③兜底到 `market_data_hub.search_etf` 前先尝试拼音匹配 | ①「茅台」→600519；②负向：levistock 失败不得静默空 | `market.py:379 _search_a_stocks`、`sync_instruments.py` |

### 14.4 R68/R69 详细设计（P0/P1，级联根因 + 设计链）

#### 14.4.0 根因链（代码级 + 日志实证）

```
盘后 mootdx 空 + tickflow 429（限流）
  → fetch_history 全链失败（hub/_kline.py:284 run_sync(fetch_history, timeout=20)）
  → refresh_kline 的 _kline_cache_rows 从未填充（updated=0，不触发 _persist_kline_cache_sync）
  → data/kline_cache.json 从未生成（R59③ 落盘形同虚设）
  → 三下游级联失效：
      ① IC 回填 _wait_for_kline_rows 3 次重试后放弃 → 因子模型 no_data（R58）
      ② 组合设计 skip_refresh 后仍逐标的 tickflow K 线采集 → 90s 超时（R69）
      ③ symbol-analysis Hub 缓存兜底 get_kline_rows_any 取空 → 600519「K线空」（R60）
```

**关键证据**：`data/kline_cache.json` 不存在（`ls` No such file）；`factor_ic_records` 6 个 distinct trade_date；`docker logs` 大量 `tickflow 429`；`600519 history=0 / indicators data_available=false`。

#### 14.4.1 修复优先级

| # | 优先级 | 优化 | 设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| ① | P0 | **K 线缓存「部分成功也落盘」+ 盘后降级链** | `refresh_kline` 逐 symbol 成功即写 `_kline_cache_rows` 并**增量落盘**（而非 `updated>0` 整体落盘）；`fetch_history` 盘后降级链补「last-good 收盘快照」兜底（同 R45 模式），保证盘后至少有 T-1 收盘 K 线可缓存 | 盘后冷启动后 `get_kline_rows_any` 非空；`data/kline_cache.json` 生成 | `hub/_kline.py:175/265/284` |
| ② | P0 | **设计「超时→降级方案」真正落地** | `task_manager` 数据采集超时路径不再 `TimeoutError → failed`，改为用已采集部分 + last-good 池 + 快照 K 线**产出 `degradation.mode=degraded` 方案**（复用现有 degradation 机器） | 盘后首呼 design 产出降级方案；负向：禁「方案生成超时」空响应 | `task_manager.py:570`、`strategy_design.py` |
| ③ | P1 | **IC 回填让出事件循环** | 回填时光回溯循环每 N 次 compute `await asyncio.sleep(0)` 或 `to_thread`，消除 CPU 独占 | 回填期间请求延迟 <1s | `ic_tracker.py`、`main.py:688` |

**优先级关系**：①是治本（K 线缓存有数据，三下游全部激活）；②见效最快（设计永远能产出方案）；③消除 R75 可用性事故。

---

## 15. 分两批实施建议（不实施，等待指令）

- **批1（P0/P1 正确性/性能）**：R68（K 线缓存落盘 + 降级链）、R69（设计降级方案落地）、R70（LLM 配额诚实降级）、R71（concept 缓存）。
- **批2（P2 治理）**：R72（分类词表）、R73（stars 公式）、R74（因子口径统一）、R64（portfolio a11y）、R65（macro/global 摘要）、R75（回填让出循环）、R76（A 股个股搜索）。

> **当前状态：等待「开始实施」指令，不写任何修复代码。**

---

## 16. 多轮 review 记录

- **Round 1（证据链核查）**：对照代码与运行时输出逐条核查 file:line 与数据。修正：①R68 根因链补「`data/kline_cache.json` 不存在」的直接证据（`ls` No such file）与「`_persist` 仅在 `updated>0` 触发」的代码证据（`hub/_kline.py:301-308`）；②R57 判定从「无效」更正为「生效」（LLM 15s→103.6s，内层 connect=60s 已落地），R70 定位到配额节流 + JSONDecodeError 这一新失败原因；③搜索「bug」证伪——初测用 `?q=` 参数（实际为 `keyword`），改为正确参数后搜索正常，仅剩「茅台 0 结果」（R76）。
- **Round 2（「级联失效」框架确立）**：R58/R59/R60 从「各自无效」统一为「共享前置 K 线缓存冷（R68）的级联失效」——三者修复代码均在、单测绿，但盘后 K 线数据源不可用导致前置永不满足。这是「方法已应用 vs 目标已达成」的进阶形态：**「前置条件未满足」型失效**，与 round27 R43/R55 的「只改外层未改内层」「启动时跑一次」型失效并列。
- **Round 3（口径矛盾核查）**：R74 的「13/13 正常」vs「缺失 66.7%」vs「26/39」三处口径互斥经核对为真（strategy-check 响应三字段并存）。R73 stars 公式不符经核对契约 `stars = min(level + freshness, 5)` 与实测 level=1→stars=5 矛盾。均已定位到具体字段与文件。
- **Round 4（file:line 复核 + 新发现 R70b）**：对照代码复核关键定位——`llm/reports.py:538`（strategy_check connect=60 已改）、`:750`（`generate_design_report` 仍 connect=15.0，R57 只改了策略检查路径，设计报告路径同脆弱点，新增 R70b）；`task_manager.py:293-319`（R59② skip_refresh 重试在）、`:593-594`（「方案生成超时」仍是最终 error_msg）；`reports.py:556`（「interrupted after %.1fs (timed out or cancelled)」——timeout/cancel/JSONDecode 三类错误被同一文案吞并，印证 R70 的「超时掩盖真实原因」）。

> **当前状态（Round 1-3 完成）**：R68-R76 均达实施标准（精确 file:line + 根因 + 验收 + 负向断言）；R68/R69 已展开为实施级详细设计（§14.4）。本文档**不写任何修复代码**，等待「开始实施」指令。
