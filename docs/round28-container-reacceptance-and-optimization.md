# round28 容器重建 + 全量验收与优化方案（2026-08-17）

> 本文档为 round27 R42-R55 全部实施（commit `0c3a1b4`/`f57583e`/`5b0c2fa`）后的**新一轮 Docker 重建 + 16 项全量验收**结论与剩余问题修复设计。
> **本文档仅设计修复方案，不实施。** 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」撰写。
> 验证环境：Docker Desktop Engine 29.7.2 / Compose v5.4.0，prod profile 重建启动，后端 :8000 / 前端(nginx) :80；PROFILE_WARMUP=1（预热诊断，`docker-compose.diag.yml` override）。后端镜像 `07c7d24b3f2b`、前端 `70efdabd47f0`。
> 验证窗口：2026-08-17 23:42–24:00（北京时间，**周一盘后**）。盘后/数据源冷却成分见 §0.4。

---

## 0. 执行摘要

### 0.1 本轮性质
round27 的 R42-R55 及 F1/F2/F3/F3b 已在 `0c3a1b4`（P0+P1）+ `f57583e`（P2+测试折叠）+ `5b0c2fa`（R51/F3/F3b）三 commit 中实施。本轮用**全新 Docker 镜像 + 16 项动作**复验落地情况，识别出**实施后仍残留/新引入的问题**。**核心结论：round27 的 5 项 P1 修复中 R52/R53/R54/R45/R44 已真正生效，但 R43、R55 两项「修复」因只改外层未改内层（R43）或只在启动时跑一次且前置未就绪（R55）而无效；同时 commit `5b0c2fa` 的 F3 重构新引入「全球指数预热双重执行」回归。**

### 0.2 验证动作与结果
| # | 动作 | 结果 |
|---|---|---|
| 1 | Docker 构建 + 回收老镜像 | ✅ 新镜像 backend `07c7d24b3f2b` / frontend `70efdabd47f0`，老镜像被同名 tag 替换回收 |
| 2 | 预热性能诊断（PROFILE_WARMUP=1） | ❌ **预热 54.3s（round27 为 34.5s，继续恶化）**；根因=新引入「全球指数预热双重执行」18.4s（R56） |
| 3 | 组合设计 + 场内策略检查（on_exchange） | ⚠️ **组合设计本轮超时失败**（119.5s）；策略检查完成但 **R43 仍无效**（LLM 15s 失败恒规则兜底）；R52 修复生效（综合信号诚实降级） |
| 4 | A/HK/US 行情分析全能力 | ⚠️ AI 投顾/个股/板块/美股指数内容高质量；**HK 00700 整链 DATA_UNAVAILABLE**；A 股/美股个股分析 K线/指标注入断裂（R60） |
| 5 | 热点 + 自选 | ✅ 热点加载成功；自选 R45 修复生效（is_estimated + 诚实 null）；⚠️ indicators asset_type 恒 "A"（R62） |
| 6 | 持仓技术信号 | ✅ 技术信号 data_available + reasons 自洽；R52 综合信号诚实降级 |
| 7 | 资讯分级 + 智能分析 | ✅ 分级合理（F22/F23/F28）；⚠️ ai_summary 全 null（R65） |
| 8 | 因子模型页 | ❌ **R55 无效**——IC 回填启动时「K 线缓存未就绪」跳过且不重试 → 27 因子仍 no_data（R58） |
| 9 | 前后端断裂排查 | ⚠️ indicators asset_type 恒 "A"（US/HK 标的错标）；strategy-check-result coverage=null |
| 10 | round27 落地核验 | 5 项生效（R44/R45/R52/R53/R54）、2 项无效（R43/R55）、1 项部分（R42）、1 项未达（R51）、1 项未做（R50） |
| 11 | 前端 Lighthouse（4 路由） | ⚠️ portfolio a11y 仍 82（R51 无效，R64）；**news CLS 0.198 新回归**（R63）；root perf 73/portfolio 71 仍 <90 |
| 12 | 后端链路性能（冷/热） | ✅ 热态全 <0.21s；⚠️ 冷态 watchlist 5.87s/search 8.13s/indicators_00700 8.93s |
| 13 | 测试防护缺口分析 | ⚠️ 三类新缺口（§13）——global_indices 基数、R43 内层超时、R55 前置未就绪均无测试拦截 |
| 14 | 冗余代码 | ⚠️ logs/*.py 224 个（R50 未清理）；backend 根 4 个 git-tracked scratch |
| 15 | 综合结论 + 修复方案 | 本文档（R56-R67 修复设计，达实施标准不实施） |
| 16 | 回收容器 + 归档 + commit/push | 见 §16 与结尾 |

### 0.3 问题分级（本轮新发现，危害驱动）
- **P0（投资判断/数据可信度）**
  1. **R43-无效 — 策略检查 AI 报告仍永不可见**（round27 R43 修复未达目标）：round27 设计「外层超时 75s→180s」，但**内层** `generate_strategy_check_report`（`llm.py:1662`）的 `httpx.Timeout(connect=15.0, ...)` 仍在 15s 触发 `CancelledError`（本轮日志 `[strategy_check] LLM analysis interrupted after 15.0s (CancelledError)`）→ 恒落规则兜底。summary「LLM 分析超时（15s 未返回，已用规则引擎兜底）」。专业投资者仍永远看不到真正的 AI 策略检查报告。详见 §2.2 / R57。
- **P1（正确性/性能）**
  2. **R56 — 全球指数预热双重执行（commit `5b0c2fa` F3 重构新引入回归）**：`main.py:268` 独立 `asyncio.create_task(_warmup_global_indices())`（commit `25ad8147` 旧逻辑）+ `main.py:334` F3 重构后 sequence 内**再次**调用 `_warmup_global_indices()`。两者并发启动、同时 miss 24h 缓存 → 各自网络拉取 → `warmup_timing.json` 两条记录 5953.9ms + 12433.95ms = **18.4s 双重预热**（日志「全球指数缓存预热完成（网络拉取）」×2）。round27 仅一条 5807ms 记录，本轮为回归。详见 §1。
  3. **R58 — R55 IC 回填无效（前置未就绪 + startup-once 不重试）**：round27 R55 落地 `_backfill_ic_history_task`（`main.py:556`），但日志「[ic_backfill] K 线缓存未就绪，跳过历史回填」——回填任务在 startup 时跑一次，此刻 K 线缓存尚未预热，**跳过即永不再试**（startup-once）。生产库 `factor_ic_records` 仅 4 个 distinct trade_date（2026-08-14~17）→ 27 因子仍恒 no_data。R55 的「修复」代码在但结果未达成。详见 §2.11。
  4. **R59 — 组合设计本轮超时失败**：`design-async` 提交后 119.5s 超时，错误「方案生成超时，数据源响应过慢，请稍后重试」（盘后数据源冷却 + 预热未完成时首呼撞冷）。round27 同类动作成功（600），本轮失败暴露「设计链路对盘后/冷启动的鲁棒性不足」。
  5. **R60 — symbol-analysis K线/指标注入断裂**：A 股个股 600519、美股 AAPL 的 AI 分析正文均诚实标注「历史K线为空、技术指标为空」，但同窗口 `/market/indicators/600519` 返回完整 MA/RSI/KDJ/MACD（ma5=1335.97）、`/market/history/510300` 返回 240 交易日——**指标端点有数据、分析端点没注入**，两路径数据源不一致。专业投资者拿到的 AI 报告缺技术面。
  6. **R61 — 港股 00700 整链 DATA_UNAVAILABLE**：`/market/realtime/00700` 返回 null、`/market/indicators/00700` 返回 `data_available=false`（K线<30）、`symbol-analysis` 返回 `DATA_UNAVAILABLE`。港股行情/分析整链在盘后不可用（数据源冷却）。
- **P2（治理/呈现）**
  7. **R62 — indicators asset_type 恒 "A"（US/HK 标的错标）**：`/market/indicators/{symbol}` 对 00700、AAPL 均返回 `asset_type: "A"`（应为 HK/US）——前后端字段级断裂。
  8. **R63 — news CLS 0.198 新回归**：round27 四路由 CLS 全 0.001，本轮 `/news` CLS=0.198（>0.1 阈值 FAIL）。
  9. **R64 — R51 无效：portfolio-analysis a11y 仍 82**：round27 R51 改 `theme.css` 对比度，但 portfolio-analysis a11y 仍 82（<90），未改善。
  10. **R65 — 资讯 ai_summary 全 null**：headlines/macro/stock 的 `ai_summary` 全 null（LLM 配额门禁让位主链路 + 无回填）。
  11. **R66 — R42 部分达成：因子分跨屏数值仍不一致**：标签已统一（「相对候选池/单标的」），但 design `etfs[].factor_score`（159338=-0.9007）vs 策略检查「因子分」（159338=-0.08）**数值仍差一个量级**——标签一致 ≠ 数值一致。
  12. **R67 — backend 根 4 个 git-tracked scratch**：`add_filtered_tab.py`/`fix_dashboard_ui.py`/`fix_market_tabs.py`/`verify_design.py` 已提交进 git（一次性调试脚本）。

### 0.4 验证窗口标注（D3）
本轮执行于 2026-08-17 23:42-24:00（**周一盘后**）。以下结论含盘后/数据源冷却成分，属「待交易时段复测」：HK 00700 整链不可用（R61）、watchlist realtime 部分 null、symbol-analysis K线/指标注入空（R60）、组合设计超时（R59）。但「全球指数预热双重执行（R56）」「R43 内层 15s 超时（R57）」「R55 回填跳过（R58）」「indicators asset_type 恒 A（R62）」「news CLS 回归（R63）」均为**代码级结构事实，不受窗口影响**。

---

## 1. 预热性能诊断（PROFILE_WARMUP=1）

**产物**：`logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.txt/html`（本轮镜像 `07c7d24b3f2b`）。

**实测（warmup_timing.json，总耗时 39371.9ms）**：
| 阶段 | 耗时 | 占比 | 备注 |
|---|---|---|---|
| init_db | 43.8ms | 0.1% | |
| redis_init | 81.6ms | 0.2% | |
| warmup_etf_cache | 23.7ms | 0.1% | |
| **warmup_global_indices（第 1 次）** | **5953.9ms** | 15% | **双重执行之一** |
| **warmup_global_indices（第 2 次）** | **12433.95ms** | 32% | **双重执行之二** |
| **warmup_market_cache** | **20835ms** | 53% | 10s 超时未生效 |
| 合计 | **39371.9ms（~54.3s 墙钟）** | — | **round27 为 34.5s → 再恶化 +20s** |

**根因（代码级，本轮实证）**：
- **R56 双重 global_indices**：`main.py:268` 独立 task（旧逻辑残留）+ `main.py:334` F3 重构后 sequence 内再次调用。两者并发 miss 缓存 → 18.4s 双重网络拉取。`git blame` 确认 line 334 由 `5b0c2fa`（F3/F3b）新增，line 268 由 `25ad8147`（2026-08-09）已有。**F3 重构时未删除旧独立 task，是典型「重构遗漏」回归。**
- **warmup_market_cache 20.8s（10s 超时失效）**：`_do_market_warmup` 的 `asyncio.wait_for(refresh_market_cache(), timeout=10)` 本应 10s 截断，但 `refresh_market_cache` → `get_portfolio_realtime` 内部是**多条 `run_sync`（线程池，各 8s 超时）顺序/并发**，线程池任务无法被 `asyncio.wait_for` 打断 → 墙钟 20.8s。
- **demjson decode 105.7s 累计 CPU**（cProfile `demjson.py:6182(decode)`）：akshare 纯 Python JSON 解析器为最大 CPU 热点；`ETF_FAST_JSON=1` 的 fast-json shim（`main.py:78`）**未默认启用**。
- `fetch_fund_nav`（`china_market.py`）11.67s（F1 已后台化但冷启动仍重）。
- DNS 首次解析 4.4s（`_ipv4_getaddrinfo`，R44 缓存命中后缓解，但每个新 host 首次仍慢）。
- `_backfill_ic_history_task` 4.25s（R55 回填，见 R58）。

**修复设计**：R56（删重复 task）见 §14.2；其余见 §14.2。

---

## 2. 组合设计 + 场内策略检查

### 2.1 组合设计（本轮超时失败，R59）
`POST /design-async {"capital":500000}` → 202 提交，但轮询 119.5s 后 `status=failed`、错误「方案生成超时，数据源响应过慢」。盘后数据源冷却 + 预热未完成首呼撞冷 → 设计链路超时。

> ⚠️ **证据口径说明**：本轮设计任务失败，无新鲜设计样本。§2.4 R66 及 §9 矩阵中引用的 design 605（`factor_score=-0.9007` 等）为**上一容器会话 12:01 创建的历史设计**（`created_at=2026-08-17T04:01:44Z`，早于 R47 commit `f57583e` 12:14）。R47（结构化字段桶化）据此判定需谨慎——代码级已实施（`_apply_precision_bucketing`），但历史样本为 pre-R47，不能作为「未生效」证据。

**修复设计**：见 §14.1 R59（详细五项设计见 §14.4）。

### 2.2 场内策略检查（on_exchange，13 只持仓，R57）
策略检查 45.3s 完成，但 summary =「**LLM 分析超时（15s 未返回，已用规则引擎兜底）**（市态：震荡；因子数据0/13正常）」。

- ✅ **R52 修复生效**：13/13 持仓 `composite_decision` = `{signal: null, degraded: true, reason: "因子数据缺失 66.7%：综合信号不可用（退化为纯技术信号…）"}`——不再「恒 hold 假信号」，改为诚实降级。
- ✅ R42 标签生效：reason 含「因子分口径：相对候选池」/「单标的」。
- ❌ **R57（R43 无效）**：日志 `[strategy_check] LLM analysis interrupted after 15.0s (timed out or cancelled: CancelledError)`。根因见 §2.2 详述——round27 R43 只改外层 `_llm_timeout_for`（`portfolio_service.py:818-834`，75s→180s），未改内层 `httpx.Timeout(connect=15.0)`（`llm.py:1662`）。
- ⚠️ `strategy-check-result` 响应无 `coverage` 字段（契约 `strategy-check-v2.md` 要求 `coverage.coverage_pct=1.0`）。

**R43/R57 根因（代码级）**：`portfolio_service.py:1071` `asyncio.wait_for(generate_strategy_check_report(...), timeout=180)`（外层已 180s）→ `generate_strategy_check_report`（`llm.py:1640-1690`）→ `get_agent("strategy_check").run_json(..., request_timeout=httpx.Timeout(connect=15.0, read=90.0, ...))`。DeepSeek 连接/响应 >15s → 内层 connect 超时先触发 `CancelledError` → `except BaseException`（`llm.py:1664`）捕获 → 返回「LLM 分析超时（15s 未返回）」。**外层 180s 从未有机会生效。**

**修复设计**：见 §14.1 R57。

### 2.3 综合信号诚实降级（R52 已修复，本轮实证）
`composite_decision.signal=null + degraded=true + reason 含缺失占比`——R52 修复真实生效，专业投资者不再被「恒 hold」误导。

### 2.4 因子分跨屏数值仍不一致（R66，R42 部分达成）
标签已统一，但数值仍异：design 159338 `factor_score=-0.9007`（全池截面 z）vs 策略检查 159338「因子分 -0.08」。**「相对候选池」标签下两屏数值差一个量级**，说明参考群体/加权复合方式仍未真正统一（可能：design 用 `factor_registry.compute()` 全维加权，策略检查用 `get_factor_matrix()` 另一套）。**注**：design 侧证据为历史设计 605（12:01 创建），策略检查侧为本轮新鲜结果；跨屏数值差异存在时间窗口（12:01 vs 23:48 因子矩阵可能漂移），需交易时段同窗口复测确认。

---

## 3. A/HK/US 行情分析（AI 内容审阅）

**first_byte 实测**：advice 67.8s / 600519 111.6s / 510300 54.9s / AAPL 26.4s / SPX 69.6s / 板块 82.4s（**R49 未修复，first_byte 26-111s**）。

- **AI 投顾（综合研判）✅ 高质量**：真实数据（科创50 +4.14% > 创业板 +3.14% > 沪深300 +1.61%）、强势板块（光通信/芯片/PCB/机器人）、风险（法国 30Y 4.86%）、三档配置（均衡/进攻/防御）+ 操作规则。逻辑严谨、数据完整。
- **个股 600519 ✅ 内容高质量，⚠️ K线/指标注入空**：基本面（2026H1 营收 922.78 亿 +1.30%、归母 -1.95%）、资讯催化、风险、操作建议均专业；且诚实标注「PE_TTM 与半年报年化 PE 不一致」。但「历史K线为空、技术指标为空」——而 `/market/indicators/600519` 同窗口返回完整 MA/RSI/KDJ（**R60 注入断裂**）。
- **个股 AAPL ✅ 内容高质量，⚠️ 同上 K线空**：Q3 FY2026 营收 1094 亿 +16%、净利 +27%、正负面催化、风险；技术面诚实「K线缺失无法判断趋势」。
- **港股 00700 ❌ 整链不可用（R61）**：realtime null + indicators false + analysis `DATA_UNAVAILABLE`。
- **美股指数 SPX ✅ R53 修复生效**：返回真实分析，诚实「当前数据源未提供标普500（SPX）的 PE/PB 等估值指标」——不再 `unsupported_market`。
- **板块 BK0735 ✅ 高质量**：88 成分股/73涨15跌、资金面（主力净流入 4.35 亿）、技术面（MA5/10/20 推算）、产业逻辑（存储涨价×AI算力×国产替代）。
- **搜索自动补全 ✅**：A/港/美全通，中文回显正确（「银」→ 银轮股份/银之杰…；「腾讯」→ 00700）。

**专业投资者是否接受**：AI 投顾/板块/美股指数/个股（基本面部分）达专业水准；但 **A 股/美股个股分析缺技术面（R60）、港股整链不可用（R61）、first_byte 26-111s（R49）**，专业投资者对「个股分析缺技术指标」不可接受。

---

## 4. 热点 + 自选

- **热点 ✅**：hot-plates 光通信 +4.03%（英伟达 Spectrum-X 量产催化，lead 天洋新材 4天4板）；stock-hot-rank 50 条加载成功（冷 4.05s）。
- **自选 ✅ R45 修复生效**：23 条；部分带 `realtime`（`is_estimated:true, estimate_source:"last_close", as_of`），部分诚实 `realtime:null + data_unavailable:true + realtime_note:"非交易时段无行情（数据源维护中）"`；add 重复 409 去重正确。
- ⚠️ **R62**：`/market/indicators/00700`、`/indicators/AAPL` 返回 `asset_type:"A"`（错标，应为 HK/US）。

---

## 5. 持仓技术分析

- 技术信号 ✅：`/market/signal/{symbol}` 返回 `data_available:true` + reasons（MACD/KDJ/MA/BOLL 自洽）。
- ⚠️ 表观矛盾：510300 `signal=hold, score=-0.5`，但 reasons 含「MACD偏多」「MA多头排列」+「KDJ超买」——score 计算口径不透明（KDJ 超买即给负分？），专业投资者无法从 -0.5 推导出「偏多」结论。

---

## 6. 资讯

- 分级 ✅：符合 F22/F23/F28 契约（`level`=int 重要性、`category`=极性、`stars`=新鲜度）。茅台中报「negative」、汇丰宏观「stars=5」分类合理。
- ❌ **R65 ai_summary 全 null**：headlines/macro/stock 的 `ai_summary` 全 null——新闻智能分析未生成（LLM 配额门禁让位主链路，无重试/回填）。

---

## 7. 因子模型

- ❌ **R58（R55 无效）**：`/factors/active` 仍 `valid=0 / no_data=27 / static=11`，summary `min_samples=250 / observable=0`。
- 日志实证：「[ic_backfill] K 线缓存未就绪，跳过历史回填」（启动时 K 线未预热）+ `[ic_restore] restored 20 IC entries`。
- 生产库 `factor_ic_records`：`119 条 / 4 个 distinct trade_date（2026-08-14~17）`——回填从未成功落库。

---

## 8. 前后端断裂排查

- ⚠️ **R62**：indicators asset_type 恒 "A"（US/HK 标的错标）。
- ⚠️ strategy-check-result 无 `coverage` 字段（契约要求）。
- ✅ 其余字段级断裂（R28 composite_decision / R29 realtime_unavailable / 中文回显）已修复。

---

## 9. round27 方案落地核验（完整矩阵）

| ID | round27 状态 | 本轮实测 | 判定 |
|---|---|---|---|
| R42 因子分口径 | 待实施 | 标签已加（相对候选池/单标的），数值仍异（-0.9007 vs -0.08） | ⚠️ 部分达成（R66） |
| R43 LLM 超时 | 待实施 | 外层 180s 已改，内层 connect=15s 仍 15s 失败 | ❌ 无效（R57） |
| R44 预热回归 | 待实施 | sector warmup 后台化（`main.py:316`） | ✅ 生效 |
| R45 watchlist 兜底 | 待实施 | is_estimated/last_close + 诚实 null + 时间戳 | ✅ 生效 |
| R46 首启空窗 | 待实施 | push2delay fetcher 已接（`sector_fetcher.py:426`） | ✅ 生效（代码级） |
| R51 a11y 对比度 | 待实施 | theme.css 改，但 portfolio a11y 仍 82 | ❌ 无效（R64） |
| R52 综合信号恒 hold | 待实施 | degraded=true + signal=null + 诚实 reason | ✅ 生效 |
| R53 美股/港股指数 | 待实施 | SPX 返回真实分析（诚实降级 PE/PB） | ✅ 生效 |
| R54 指数种子表 | 待实施 | SOXX/XLB 移入 HKUS_ETF_MAP（`market_service.py:637`） | ✅ 生效 |
| R55 IC 回填 | 待实施 | 回填启动时 K 线未就绪跳过，不重试 | ❌ 无效（R58） |
| R47 结构化字段桶化 | 待实施 | 代码级已实施（`_apply_precision_bucketing` strategy_design.py:972/990）；本轮设计失败无新鲜样本 | ✅ 代码级（待复测） |
| R48 近替代品合并 | 待实施 | 未实测（设计本轮失败） | 待复测 |
| R49 first_byte 进度 | 待实施 | first_byte 26-111s（SSE 有 progress 事件） | ⚠️ 部分 |
| R50 logs 清理 | 待实施 | logs/*.py 仍 224 | ❌ 未做 |
| F1/F2 预热优化 | 待实施 | Session 复用 + NAV 后台化已落地，预热仍 54s | ⚠️ 部分 |

**核验结论**：round27 的 14 项修复中 **5 项真正生效**（R44/R45/R52/R53/R54）、**2 项无效**（R43 只改外层、R55 前置未就绪）、**1 项部分**（R42 标签一致数值异）、**1 项未达**（R51）、**1 项未做**（R50）。R43/R55 的「修复」是**「方法已应用但目标未达成」的典型**——代码改了、测试绿了，但运行时结果与修复前相同。

---

## 10. 前端 Lighthouse（4 路由）

| 路由 | perf | a11y | CLS | 备注 |
|---|---|---|---|---|
| / | 73（round27 75↓） | 96 | 0.001 | FCP 1.9s / TBT 440ms / SI 8.6s |
| /market-analysis | 86 | 100 | 0.001 | |
| /portfolio-analysis | 71 | 82 | 0.001 | a11y 仍 82（R64） |
| /news | 84 | 95 | **0.198** | **CLS 新回归（R63）** |

- ❌ F4/F5（Lighthouse perf≥90 / a11y≥90 硬门禁）仍未实施——无 CI 卡点。
- ❌ R63：news CLS 0.198（round27 为 0.001，>0.1 FAIL）。
- ❌ R64：portfolio-analysis a11y 82（R51 无效）。

---

## 11. 后端链路性能（冷/热态）

| 端点 | 热态 | 冷态（首呼） | 判定 |
|---|---|---|---|
| /portfolio/etfs | 40ms | — | ✅ |
| /market/hot-plates | 10ms | — | ✅ |
| /market/stock-hot-rank | — | 4.05s | ❌ 冷态 |
| /market/search 银 | — | 5.07s | ❌ 冷态 |
| /market/watchlist | — | 5.87s | ❌ 冷态 |
| /market/indicators/00700 | — | 8.93s | ❌ 冷态 |
| /market/sectors/industry | — | 6.68s | ❌ 冷态 |

**结论**：热态全 <210ms；冷态 5 个端点 >4s。预热覆盖了 sector/etf/indices 缓存，但 watchlist/search/stock-hot-rank/indicators 冷路径仍未覆盖。

---

## 12. 测试防护缺口分析（为何现有测试未识别）

1. **R56（global_indices 双重执行）**：`test_warmup_sequence.py` 只验「串行执行/失败隔离」，**无测试断言「每个预热任务只被 create_task 一次」**（基数/调用次数）。F3 重构在 sequence 里重复添加 `_warmup_global_indices()`，无任何测试拦截。
2. **R57（R43 内层超时）**：`test_strategy_check_llm_timeout.py` mock 整个 LLM 调用链（`llm_chain_env` fixture），只验「`_llm_timeout_for` 返回 180s」「summary 文案」，**从不验 `llm.py:1662` 内层 `httpx.Timeout(connect=15.0)` 与 DeepSeek 慢首字节的真实交互**。测的是「外层超时值改了」，不是「AI 报告能产出」。
3. **R58（R55 回填跳过）**：R55 测试 mock 240 天 K 线后直接调回填函数，**不覆盖「startup 时 K 线缓存未就绪 → 跳过」的真实前置条件**，也不验「跳过后是否重试」。
4. **R62（asset_type 恒 A）**：indicators 测试只验 A 股标的，无 US/HK 标的的 asset_type 断言。
5. **R63（news CLS）**：Lighthouse 无 CI 门禁（F4/F5 未实施），CLS 回归无人拦截。

**共性**：同 round27 §13——测试验「方法已应用」非「目标已达成」，且 mock 快乐路径、不测「前置未就绪」「内层超时」「基数」等结构事实。

---

## 13. 冗余代码

- ⚠️ `logs/round{8,16,18,20}/*.py`：**224 个**（R50 未清理，gitignore 磁盘残留）。
- ⚠️ **backend 根 4 个 git-tracked scratch（R67）**：`add_filtered_tab.py`、`fix_dashboard_ui.py`、`fix_market_tabs.py`、`verify_design.py`——一次性调试脚本已提交进 git。
- ⚠️ 测试文件 225 个（round27 为 220）。
- ✅ backend/app 生产模块 91 个 py、scripts/archive 12 个已归档。

---

## 14. 修复方案总表（R56-R67，不实施）

### 14.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R57 | P0 | 策略检查 LLM 仍 15s 失败（内层 connect=15s 先于外层 180s） | ①`llm.py:1662` 的 `httpx.Timeout(connect=15.0)` → **connect=60.0**（对齐 DeepSeek 慢连接/慢首字节实测 34-78s，read 保持 90s）；②或改为「外层 180s + 内层 connect 用 provider.timeout」双口径；③LLM 失败 summary 已区分 timeout/rate_limited（R5-1-6），保留 | ①交易时段背靠背 design→strategy-check 至少一次产出真 LLM 报告（非规则兜底）；②负向：connect=15s 不再先于外层触发 | `llm.py:1655-1662`、`portfolio_service.py:1071-1079` |
| R56 | P1 | 全球指数预热双重执行（F3 重构遗留） | 删除 `main.py:267-268` 独立 `asyncio.create_task(_warmup_global_indices())`（sequence 内 `:334` 已覆盖） | ①单测：warmup_timing 仅 1 条 global_indices 记录；②负向：禁止 `_warmup_global_indices` 被 create_task 两次 | `main.py:267-268` |
| R58 | P1 | R55 回填启动时 K 线未就绪跳过且不重试 | ①回填任务改为**延迟执行 + 重试**（K 线缓存就绪后触发，或预热完成后再次尝试，失败退避重试 ≤3 次）；②或回填改为「预热 sequence 末尾」执行（此刻 K 线已就绪） | ①单测（抓假负向）：mock K 线缓存未就绪 → 回填「稍后重试」而非「永久跳过」；②生产库 factor_ic_records distinct trade_date ≥ 60（可观察） | `main.py:556/_backfill_ic_history_task`、`ic_tracker.py` |
| R59 | P1 | 组合设计盘后/冷启动超时失败（根因与优化详见 §14.4） | ①采集并发化 + 单源快速失败降级；②超时→降级而非失败；③K 线缓存持久化；④预热覆盖设计数据（五项完整设计见 §14.4） | ①盘后/冷启动首呼 design 产出降级方案（非「方案生成超时」失败）；②冷启动数据采集 ≤30s；③负向：不得用「方案生成超时」掩盖数据源冷却 | `market_data_hub.refresh`、`strategy_design.py`、`task_manager.py`、`china_market.py` |
| R60 | P1 | symbol-analysis K线/指标注入断裂（指标端点有数据、分析端点没注入） | ①symbol-analysis 数据采集统一走 `/market/indicators` 同源 fetcher（`fetch_history`/`compute_indicators`），确保 A 股/美股个股 K 线注入 LLM prompt；②采集失败才诚实降级（保留当前诚实标注） | ①交易时段 600519/AAPL 分析正文含 MA/RSI/KDJ 数值；②负向：指标端点有数据时分析端点不得「K线为空」 | `analysis/llm.py:generate_symbol_analysis` 采集段、`market_service.py` |
| R61 | P1 | 港股 00700 整链 DATA_UNAVAILABLE | ①排查港股实时/历史数据源冷却（腾讯 hk{code}/akshare 港股）的降级链；②港股 realtime 失败回退 last-good/收盘快照（同 R45 模式）；③analysis 采集不到港股数据时给「港股数据源维护中」而非泛化 DATA_UNAVAILABLE | ①交易时段 00700 realtime 非 null；②盘后至少 last_close 快照兜底 | `market_service.py:get_asset_realtime`、`market.py:_last_close_fallback` |
| R66 | P2 | R42 部分：因子分跨屏数值仍不一致（design -0.9007 vs check -0.08，待同窗口复测） | ①明确 design `etfs[].factor_score` 与策略检查「因子分」**共用同一复合函数**（`aggregate_factor_scores` + 同一参考群体）；②加跨屏一致性单测：同标的 design vs check 因子分方向一致且量级一致 | ①负向：159338 两屏数值量级一致（禁 -0.9007 vs -0.08）；②单测断言两屏 | `allocation_engine.py`、`portfolio_service.py:1586` |

### 14.2 性能

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R56 | P1 | （同上，预热双重执行） | 同上 | | |
| R63 | P2 | news CLS 0.198 回归 | ①定位 `/news` 路由布局位移源（图片/异步内容无占位）；②news 列表项固定高度/骨架屏占位 | ①CLS <0.1；②Lighthouse CI 门禁（F4/F5 落地） | `NewsView.vue`、`vite.config.js` |
| R64 | P2 | portfolio-analysis a11y 82（R51 无效） | ①跑 Lighthouse a11y 明细定位未达标的对比度元素（非全局 theme.css，是 portfolio-analysis 局部组件）；②针对性修对比度 | ①portfolio-analysis a11y ≥90 | `PortfolioAnalysis.vue`、`AnalysisView.vue` |
| R65 | P2 | 资讯 ai_summary 全 null | ①新闻摘要生成失败后回填/重试（配额空窗后补跑）；②或降级为规则摘要 | ①headlines 高重要性条目 ai_summary 非 null | `market_data_hub.enrich_news_summaries` |

### 14.3 治理 / 呈现

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R62 | P2 | indicators asset_type 恒 "A" | ①`/market/indicators/{symbol}` 按 symbol 推断市场（HK/US/A），正确返回 asset_type；②补 US/HK 标的单测 | ①00700 → asset_type=HK、AAPL → asset_type=US | `market_service.py:get_indicators` |
| R67 | P2 | backend 根 4 个 git-tracked scratch | ①删除 `add_filtered_tab.py`/`fix_dashboard_ui.py`/`fix_market_tabs.py`/`verify_design.py` 或移 `scripts/scratch/` | ①backend 根无 scratch .py | `backend/` |
| R50 | P2 | logs/*.py 224 个 | ①删除 `logs/round{8,16,18,20}/*.py`（磁盘清理） | ①磁盘无 logs/*.py | `logs/` |

### 14.4 R59 设计链路优化详细设计（P1，用户追问驱动展开）

> 本节为 R59 的实施级展开，含「为何之前未出现」的历史对照证据，与五项优化（①→⑤）的设计 + 验收 + 负向断言。

#### 14.4.0 根因回顾（代码级 + 日志实证）

**现象**：本轮（2026-08-17 23:48，周一深夜）`POST /design-async` → task 559 在数据采集阶段超时失败（`task_manager.py:294` 的 `asyncio.wait_for(generate_enhanced_design(), timeout=DESIGN_DATA_TIMEOUT=90s)` 触发 `TimeoutError` → `task_manager.py:570-571` 报「方案生成超时，数据源响应过慢」）。

**日志证据（`logs/backend.log`，23:48:32 → 23:50:26）**：
- `23:48:32 MarketDataHub: scanned 79 ETFs`
- `23:48:34 get_history fetch_history empty for sz399975/sz399812/sh931071... → trying get_k_data`（冷 K 线缓存 + 慢降级路径）
- `23:48:48 _mootdx_realtime exception + mootdx returned empty → cooling + akshare returned empty → cooling`
- `23:48:52 em sector changes fetch failed (push2.eastmoney.com ... Remote end closed) + cls plate_list errno=50101 (sign 失效)`
- `23:48:58 _mootdx_history exception for 688981/600519 (period=daily)` ← **此后 88s 无任何日志**（采集阻塞在慢数据源）
- `23:50:26 [design_pipeline] task 559 timed out`

**三层根因**：①盘后数据源大面积冷却（mootdx/akshare/push2/cls 四源同时失败）；②冷 K 线缓存全量建库（`market_data_hub.refresh` → `refresh_kline` 42-75s，`task_manager.py:292-293` 注释预警）；③采集**串行累积**——每个失败源各自等到内部超时才轮到下一个，无「快速失败降级」，总耗时 = 各源之和而非最慢单源。

#### 14.4.1 为何之前未出现（历史对照，`logs/backend.log.1`）

**结论：不是新引入的重大回归，而是 90s 硬预算在「冷启动 + 深夜」下余量极薄（历史实测 88s），round27 修复叠加了一点延迟把余量吃掉了。**

历史对照（2026-08-14 02:20 深夜冷启动，`logs/backend.log.1`）：
- 同样大面积数据源冷却（`mootdx returned empty → cooling`、`akshare returned empty → cooling`、`_compute_industry_momentum failed: Connection aborted`）。
- 但设计**成功**：`02:20:58 MarketDataHub: refresh complete (v1, 38 total) in 51.1s`，`[strategy_design] refresh took 51.13s`——数据采集 51.1s + 后续步骤 ~37s ≈ **88s，只差 2s 就超 90s**。

**本轮为何从 88s 涨到 >90s**：round27 的 3 个「修复」各加了一点延迟，累积吃掉 2s 余量：
1. **R46**（sector momentum 换 push2delay）：旧代码 `_compute_industry_momentum` 用 akshare 硬编码 push2（被阻断）→ **15s 内快速失败**（`Connection aborted`）；R46 改为 push2delay 能返回数据（本轮 30 momentum rows），但**引入了额外的 push2 sector changes fetch**（`23:48:52 em sector changes fetch failed (push2.eastmoney.com m:90+t:2/:3)` 带重试）。
2. **F3**（sector cache 后台化，`5b0c2fa`）：设计时可能撞未就绪的冷 sector cache → 设计链路自行触发 `update_sector_cache`（`23:48:50`）。
3. **R55**（IC 回填任务）：启动时多一个后台任务，占线程池/网络。

**本质**：90s 是「热缓存 ~10s / 冷缓存 42-75s」之间留的余量，但「冷缓存 + 深夜四源冷却」的叠加从未在历史窗口被精确触发过（历史深夜设计都在热缓存窗口，历史冷启动设计都在数据源健康窗口）。本轮首次同时满足两者，把 88s 的历史极限推过 90s。

#### 14.4.2 五项优化设计（治本 + 配套）

| # | 优先级 | 优化 | 设计 | 验收（含负向断言） | 文件指向 |
|---|---|---|---|---|---|
| ① | P0 | **采集并发化 + 单源快速失败降级** | `market_data_hub._refresh_impl` 内相互独立的步骤（indices / sector momentum / kline 缓存 / factor matrix）从串行改为 `asyncio.gather(..., return_exceptions=True)`，每个源各自 `asyncio.wait_for(短超时)`；单源失败**立即降级**（Redis last-good / 磁盘快照），不再各自等到内部超时上限 | ①冷启动 `refresh` ≤30s（当前 51-88s+）；②负向：任一源超时不得阻塞其它源（单源失败 ≤ 其短超时即返回）；③单测 mock 四源并发，断言总耗时 = max(单源) 非 sum | `market_data_hub.py:573/619/460`、`strategy_design.py:246` |
| ② | P0 | **超时→降级而非失败** | `task_manager.py:294` 的 `wait_for` 超时路径不再直接 `TimeoutError → failed`，改为：捕获超时后，用已采集的部分数据 + 快照兜底产出**降级方案**（复用 `degradation.mode/static_pool_used` 机器），标注「盘后数据源冷却，部分数据为快照」 | ①盘后首呼 design 返回降级方案（`degradation.mode=degraded`）而非 failed；②负向：禁止「方案生成超时」空响应掩盖数据源冷却 | `task_manager.py:570-577`、`strategy_design.py` |
| ③ | P1 | **K 线缓存持久化** | `_kline_cache_rows`（`market_data_hub.py:370`）落盘 `data/kline_cache.json`，启动加载、24h 内复用（同 `indices_cache.json` / sector momentum 快照模式）；消除重启后 42-75s 冷建库 | ①重启后首次 design 不触发全量 `refresh_kline`（K 线缓存命中）；②负向：24h 过期后诚实重建而非复用过期数据 | `market_data_hub.py:370/754-764` |
| ④ | P1 | **预热覆盖设计数据** | 预热 sequence 增「因子矩阵 + 候选池 K 线缓存」预热（后台 + 预算，复用 F3 模式），使启动后首呼 design 即热 | ①启动后首呼 design `refresh` ≤10s（热缓存）；②负向：预热不阻塞 startup 就绪 | `main.py:_warmup_sequence_task` |
| ⑤ | P2 | **盘后显式降级策略** | 检测非交易时段（复用 D3 窗口判断）→ design 数据采集主动走快照/缓存路径，不尝试实时源干等超时 | ①盘后 design 秒级返回降级方案；②负向：不得用实时源超时冒充「正在采集」 | `strategy_design.py`、`market_data_hub.refresh` |

**优先级关系**：②见效最快（失败→可用降级方案，用户永远能拿到东西）；①是治本（「会超时」→「不会超时」）；③消除 42-75s 冷建库（治冷启动的根）；④⑤是配套（缩短窗口、减少触发）。①②③合起来即 R59 的完整落地形态。

---

## 15. 分两批实施建议（不实施，等待指令）

- **批1（P0/P1 正确性/性能）**：R57（策略检查 LLM 内层超时）、R56（预热双重执行）、R58（IC 回填重试）、R59（设计链路降级）、R60（symbol-analysis K线注入）、R61（港股数据源降级链）。
- **批2（P2 治理）**：R62（asset_type）、R63（news CLS）、R64（portfolio a11y）、R65（资讯摘要）、R66（因子分跨屏数值）、R67（scratch 清理）、R50（logs 清理）。

> **当前状态：等待「开始实施」指令，不写任何修复代码。**（R56-R67 设计就绪）

---

## 16. 多轮 review 记录

- **Round 1（证据链核查）**：对照代码逐条核查 file:line。修正 2 处：①R56 双重执行定位——line 268（`25ad8147` 旧逻辑）与 line 334（`5b0c2fa` F3 重构新增）两处并存，`git blame` 确认；②R57 内层超时定位——`llm.py:1662` `httpx.Timeout(connect=15.0)` 而非外层 `_llm_timeout_for`。其余核查通过：`_backfill_ic_history_task`（`main.py:556`）、`_COMPOSITE_FACTOR_MAP`（`portfolio_service.py:1537`）、`HKUS_ETF_MAP`（`market_service.py:610-638`）、`_STATIC_EXTRA_INDICES`（`fetchers/sync_indices_meta.py:153`）。

- **Round 2（R43/R55「无效」判定加固）**：R43/R55 从「未实施」更正为「已实施但无效」——代码在（`_llm_timeout_for` 返回 180s、`_backfill_ic_history_task` 存在），但运行时结果与修复前相同（LLM 仍 15s 失败、因子仍 no_data）。这是「方法已应用 vs 目标已达成」的区分，与 round27 §13 共性一致。

- **Round 3（证据时效核查，本次完成）**：发现 design 605 证据为**历史样本**（`created_at=2026-08-17T04:01:44Z` = 12:01 北京，早于 R47 commit `f57583e` 12:14）。据此修正 3 处：①§2.1 增「证据口径说明」标注 design 605 为 pre-R47 历史设计；②§9 矩阵 R47 从「⚠️ 未生效」更正为「✅ 代码级（待复测）」（`_apply_precision_bucketing` strategy_design.py:972/990 已实施）；③R66 增「待同窗口复测」限定（design 12:01 vs check 23:48 因子矩阵可能漂移）。避免把「历史样本」误当「当前代码行为」。

- **Round 4（R59 展开 + 「为何之前未出现」历史对照，本次完成）**：用户追问「组合设计为何超时 + 后续如何优化」触发。深挖 `logs/backend.log`（task 559 时间线）定位三层根因（盘后四源冷却 + 冷 K 线缓存建库 42-75s + 串行累积超时）。历史对照 `logs/backend.log.1`（2026-08-14 02:20 深夜冷启动设计 task 454）发现：**同样的大面积数据源冷却下设计却成功**——`refresh complete in 51.1s`，数据采集 ~88s，只差 2s 就超 90s。结论：**非新引入重大回归，而是 90s 硬预算余量极薄（历史 88s），round27 的 R46/F3/R55 三个修复各加一点延迟把 2s 余量吃掉了**。据此把 R59 展开为五项优化（§14.4.2：①采集并发化+快速失败 ②超时→降级而非失败 ③K线缓存持久化 ④预热覆盖设计数据 ⑤盘后显式降级），并补充「为何之前未出现」证据链（§14.4.1）。file:line 经 grep 确认：`task_manager.py:294/570-571`、`market_data_hub.py:370/460/573/619/754-764`、`strategy_design.py:246/500/694`。

> **当前状态（Round 1-4 完成）**：R56-R67 均达实施标准（精确 file:line + 根因 + 验收 + 负向断言）；R59 已展开为五项实施级优化设计并附历史对照证据。本文档**不写任何修复代码**，等待「开始实施」指令。
