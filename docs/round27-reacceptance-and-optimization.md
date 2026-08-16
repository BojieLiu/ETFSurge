# round27 容器重建 + 全量验收与优化方案（2026-08-16）

> 本文档为 round25 R27-R41 + round26 Q1-Q7 全部实施（commit `cd70cdf`/`2fce555`）后的**新一轮 Docker 重建 + 16 项全量验收**结论与剩余问题修复设计。
> **本文档仅设计修复方案，不实施。** 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」撰写。
> 验证环境：Docker Desktop Engine 29.7.2 / Compose v5.3.1，prod profile 重建启动，后端 :8000 / 前端(nginx) :80；PROFILE_WARMUP=1（预热诊断）。后端镜像 `57f4f62f6946`、前端 `9023f33bda60`。

---

## 0. 执行摘要

### 0.1 本轮性质
round25（`docs/round25-container-acceptance-and-optimization.md`）与 round26（`docs/round26-search-autocomplete-data-gaps.md`）的 R27-R41 / Q1-Q7 已在 `cd70cdf`（数据可信度+搜索缺口）与 `2fce555`（R39 LLMQuotaGate + R27 单标的口径 + R28-b 接线 + R37）两 commit 中实施。本轮用**全新 Docker 镜像 + 16 项动作**复验落地情况，并识别出**实施后仍残留的 14 项问题（R42-R55）**。

### 0.2 验证动作与结果
| # | 动作 | 结果 |
|---|---|---|
| 1 | Docker 构建 + 回收老镜像 | ✅ 新镜像 backend `57f4f62f6946` / frontend `9023f33bda60`，老镜像被同名 tag 替换回收 |
| 2 | 预热性能诊断（PROFILE_WARMUP=1） | ⚠️ **预热 34.5s（round25 为 20s，回归）**；cProfile/pyinstrument 定位 F1/F2 未实施 + R32 新增 12.8s 失败路径（R44） |
| 3 | 组合设计 600 + 场内策略检查 537（on_exchange） | ✅ R28 综合信号接通、R41-a 近替代品解耦、R2/R4/R5/R21/R24 生效；⚠️ R27 方向仍相反（R42）、策略检查 LLM 恒 75s 超时（R43）、综合信号恒 hold（R52） |
| 4 | A/HK/US 行情分析全能力 | ✅ 三地个股/板块/综合研判/搜索/指数全真实可用，Q2/Q3/Q4/Q6 修复实证；⚠️ first_byte 34-78s（R49） |
| 5 | 热点 + 自选 | ✅ 热点加载成功、自选 add/get 正常；⚠️ watchlist 收盘兜底周末全 None → 0/23 带 realtime（R45） |
| 6 | 持仓技术信号 | ✅ 6 只 data_available + reasons 自洽；✅ R28 综合信号已接通 |
| 7 | 资讯分级 + 智能分析 | ✅ R16 英文分类；⚠️ ai_summary 全 null（LLM 配额耗尽） |
| 8 | 因子模型页 | ✅ R22 avg_ic 统一 0.2665；⚠️ valid=0/no_data=27（fresh 容器周末） |
| 9 | 前后端断裂排查 | ✅ check_routes PASS；✅ R28/R29/Q5 字段级断裂已修复 |
| 10 | round25/26 落地核验 | ✅ 20 项全落地/部分落地；⚠️ R27/R29/R36/R40 四项目标未完全达成（§10） |
| 11 | 前端 Lighthouse（4 路由） | ✅ R8 CLS 全 0.001；⚠️ root perf 75<90、portfolio-analysis a11y 82<90（R51） |
| 12 | 后端链路性能（冷/热） | ✅ 热态全 <0.21s；⚠️ 冷态 watchlist 5.86s/stock-hot-rank 4.89s/indices 4.07s/search 6.87s |
| 13 | 测试防护缺口分析 | ⚠️ 7 类缺口（§13）——R27 跨屏方向、R29 兜底失败、R36 结构化字段、R40 首启空窗均无测试拦截 |
| 14 | 冗余代码 | ✅ backend 根 scratch 0；⚠️ logs/*.py 224 个残留、测试文件 220 个 |
| 15 | 综合结论 + 修复方案 | 本文档（R42-R55 修复设计，达实施标准不实施） |
| 16 | 回收容器 + 归档 + commit/push | 见 §15 与结尾 |

### 0.3 问题分级（本轮新发现，危害驱动）
- **P0（投资判断/数据可信度）**
  1. **R42 — R27 残余：因子分两屏方向仍相反**。设计屏 composite z-score 用**全候选池截面**（159338 = **-0.958**，深负）；策略检查屏「因子分」用**13 持仓截面** z-score（`_cross_sectional_factor_composite`，`portfolio_service.py:1586`，159338 = **+0.16**）。方法已统一（均为 z-score），但**参考群体不同**（全池 vs 持仓），同一标的仍呈方向相反。R27 验收口径「两屏方向一致」未达成。专业投资者对照两屏仍会困惑。详见 §2.7。
- **P1（正确性/性能）**
  2. **R43 — 策略检查 LLM 恒 75s 超时**：`_llm_timeout_for`（`portfolio_service.py:818-833`）对「数据完整」场景设 75s 超时（round14 P0-B 90→75），但 DeepSeek 流式首字节实测 34-78s（本轮 advice 53.9s / symbol 34.6-71.7s / sector 78.2s）→ 策略检查 LLM **几乎必然超时**（本轮日志 `[strategy_check] LLM analysis interrupted after 75.0s ... CancelledError`）→ 恒落规则兜底。R39 LLMQuotaGate 解决了 429 硬撞，但**未解决超时**——专业投资者永远看不到真正的 AI 策略检查报告。详见 §2.2。
  3. **R44 — 预热 34.5s 回归（R32 反噬 + F1/F2 未实施）**：`warmup_timing.json` 总耗时 34513ms（round25 为 20s）。R32 新增 `warmup_sector_cache` 12.8s，但其底层 `_compute_industry_momentum` 本轮**失败**（`Connection aborted`，日志）→ 12.8s 纯空转；F1（fund NAV 16.7s）+ F2（SSL 握手 15s 无 Session 复用）仍未实施。详见 §1。
  4. **R45 — R29 残余：收盘快照兜底周末落空**：R29 的 5s 超时回退改走 `_last_close_fallback`（T-1 收盘），但该函数依赖历史 K 线源；周末/源冷却时**兜底自身也返回 None** → watchlist 实测 **0/23 条带 realtime**、0 条带 `is_estimated`（「估」徽标永不出现），前端仍显示「行情暂不可用」/「暂无实时」。R29 的「收盘快照兜底」在快照源也断时无第二层兜底。详见 §2.6。
  5. **R46 — R40 残余：首启空窗无快照可读**：R40-a 读取兜底代码已落地（`get_sector_momentum` `market_data_hub.py:1658`），但快照只在**成功刷新时写入**（R40-b 仅放宽「非空才写」，未解决「首启 live 源失败则永无快照」）。本轮 fresh 容器首启 live 源失败（Connection aborted）→ 磁盘无快照 → `sector_momentum=[]`、`strong_sector_pool_coverage=[]`，设计强板块注入失效。详见 §2.3。
  6. **R52 — 综合信号结构性恒 hold（用户 review 驱动新增）**：本轮 13 只持仓 `composite_decision.signal` **全部 hold**，即便 `technical_signal` 有 buy（513120/159869）也有 sell（512890/159545/512000/561560）。根因两层（代码级）：①**结构性**——`composite_signal`（`signal.py:34`）`score=0.4技术+0.4估值+0.2动量`，估值/动量分项在周末因子缺失时恒 0（`_COMPOSITE_FACTOR_MAP` `portfolio_service.py:1533-1537` 的 `valuation.*`/`momentum.*` 键无命中 → `_attach_composite_decisions:1571-1574` 记 0.0），只剩 `0.4×技术 ∈ [-0.4,+0.4]`，永远够不到 ±0.5 的 buy/sell 阈值（`signal.py:40-45`）；②**门禁失效**——`composite_signal_with_gate` 的 `factor_valid_rate<0.6` 降级门禁（`signal.py:85`）本应拦住，但 `_attach_composite_decisions:1556-1558` 把 valid_rate 算成 `filled_count/total_count`（「有真实因子值的持仓数」=13/13=100%，技术类因子即算 filled），而非「估值/动量分项覆盖率」→ 门禁误判「数据完整」，放行估值/动量恒 0 的假综合信号，还标 `degraded=false`。专业投资者看到「综合信号恒持有」= 一个永不给出方向的假信号。详见 §2.8。
  7. **R53 — 美股/港股指数分析数据源未路由（用户 review 驱动新增）**：美股指数 tab 选「标普500」(SPX) → symbol-analysis 返回 `unsupported_market: US`，技术指标/K线/PE/PB 全退化（LLM 诚实降级为「仅资讯定性分析」）。根因（代码级）：`get_asset_realtime`（`market_service.py:1233-1246`）对 `asset_type=index` 的 US/HK 分支**显式返回「该市场指数暂不支持」**（round16 P0-22④ 的「过防护」，当时防「美股 tab 选 GEM 港股指数 → A 股路径报错」），但**美股指数实时数据源其实存在**——`_GLOBAL_INDEX_DEFS`（`:141-163`）含标普500（`^GSPC`）/纳斯达克（`^IXIC`）/道琼斯（`^DJI`）/恒生（`^HSI`），`get_global_indices`（`:269`）经 `_foreign`（`:361`）真实拉取；且**符号错位**：`indices_meta` 存 `SPX`，global indices 用 `^GSPC`。K 线（`chart` → `get_market_history`）对美股指数亦未接 yfinance/alphavantage（美股个股 AAPL 有 500 行，指数无）。PE/PB 指数级估值无源，保持诚实降级正确。详见 §2.9。
- **P2（治理/呈现）**
  8. **R47 — R36 残余：结构化字段仍精确小数**：`data_precision` 元数据标注 `factor_score_display=bucket`/`weight_display=coarse`，design_text LLM 表格已桶化（≈5%/偏弱），但**结构化 API `etfs[].factor_score`（-0.9855288495104011）与 `etfs[].weight`（0.2067）仍精确小数**，与元数据矛盾。
  9. **R48 — R41-c 未实现**：近替代品仅告警（R41-a/b 已生效），不合并/留一。平衡型仍双持「588170 科创半导体 + 588200 科创芯片」「159570/513120 医药生物」，防御型仍三持大盘宽基（510300+159338+510050）。
  10. **R49 — LLM 流式 first_byte 34-78s**：无进度心跳之外的可视化，专业投资者不可接受。
  11. **R50 — logs/*.py 224 个 scratch 残留**：R38 删了 backend 根 20 个，但 `logs/round{8,16,18,20}/*.py` 224 个未清理（已 gitignore，磁盘残留）。
  12. **R51 — R34 残余**：root perf 75（<90，round25 为 69）、portfolio-analysis a11y 82（<90），F4/F5 未实施。
  13. **R54 — 美股指数种子表混入 ETF + 彭博代码重复（用户 review 驱动新增）**：美股指数 tab 搜索「标普」同时冒出「标普500指数」(SPX)、「SPDR标普500ETF」(SPY)、「标普500指数(彭博代码)」(^GSPC)——**指数搜索污染了 ETF**。根因（代码级）：`_STATIC_EXTRA_INDICES`（`sync_indices_meta.py:153-209`）美股段混入 3 条 ETF（`:192` SPY=SPDR标普500ETF、`:200` SOXX=iShares半导体ETF、`:204` XLB=SPDR材料指数ETF，均 `index_type=price` 冒充指数）+ 3 条重复（`:201-203` ^GSPC/^DJI/^IXIC 与 SPX/DJI/IXIC 重复，仅「彭博代码」后缀）；而 SOXX/XLB **不在** `HKUS_ETF_MAP`（`market_service.py:600-626`，美股 ETF 基座仅 SPY/QQQ/IVV/VOO/VTI/GLD/SLV/FXI/KWEB/EEM/DIA/IWM）→ 个股/ETF tab 搜 SOXX/XLB 反而搜不到（双向错位）。详见 §2.10。
  14. **R55 — 因子模型页 27 因子恒 no_data（IC 增量计算、无历史回填，用户 review 驱动新增）**：`factors/active` 显示 valid=0/no_data=27/static=11，27 个非静态因子全部「no_data（积累中）」。根因（代码级）：`_status_of`（`factors.py:99-138`）要求 `sample_count ≥ 250` 交易日（`MIN_TRADING_DAYS=250`，`:35`）且 t≥2/|IR|≥0.5 才判 valid；而 `sample_count` 语义=`count(distinct trade_date)`（`ic_tracker.py:352`），IC 由 `_ic_persistence_loop`（`main.py:442`）**增量计算**（`save_ic_batch_to_db` 用 `_beijing_today()` 打当天日期，`ic_tracker.py:302`）——**无历史回填**。生产库 `factor_ic_records` 实测仅 **3 个 distinct trade_date**（2026-08-14~16）→ 所有因子 sample_count=3 < 250 → 恒 no_data，需运行 ~1 年（250 交易日）才翻绿。IC 是截面统计量，本可从已有 ~320 天 K 线缓存反推历史截面 IC 一次性回填，但当前实现无此能力。详见 §2.11。

### 0.4 验证窗口标注（D3）
本轮执行于 2026-08-16 19:29-20:00（北京时间，**周日盘后**）。以下结论含盘后/数据源冷却成分，属「待交易时段（9:30-11:30/13:00-15:00）复测」：sector_momentum=[]、watchlist realtime 0/23、factor valid_rate=0%、ai_summary null。但「因子分两屏方向相反（R42）」「策略检查 LLM 75s 超时（R43）」「预热 34.5s（R44）」「R29/R40 兜底链断裂（R45/R46）」均为**代码级结构事实，不受窗口影响**。

---

## 1. 预热性能诊断（PROFILE_WARMUP=1）

**产物**：`logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.txt/html`（本轮镜像 `57f4f62f6946`）。

**实测（warmup_timing.json）**：
| 阶段 | 耗时 | 占比 | 备注 |
|---|---|---|---|
| init_db | 41.5ms | 0.1% | |
| redis_init | 72.9ms | 0.2% | |
| warmup_global_indices | 5807ms | 17% | |
| **warmup_market_cache** | **15723ms** | **46%** | round25 为 13306ms |
| warmup_etf_cache | 20ms | 0.1% | |
| **warmup_sector_cache** | **12846ms** | **37%** | **R32 新增**；底层失败 |
| 合计 | **34513ms** | — | **round25 为 20s → 回归 +14.5s** |

**cProfile 根因（F1/F2/F3/F3b 未实施，故未改善；R32 引入新成本）**：
- `fetch_fund_nav`（`china_market.py:1391`，13 次，累计 **16.7s**）——akshare 基金 NAV 历史拉取（F1 降精度未实施）。
- SSL `do_handshake`（149 次，tottime **15-16s**）——**仍无 `requests.Session` 复用**（F2 未实施）。
- `stock_zh_a_spot`（akshare，24.1s）——A 股全市场行情快照。
- `_fetch_us_list`（`sync_instruments.py:238`，**9.1s**）——R30 把 `sync_instruments` 移入 `app/fetchers` 后，启动同步新增美股列表拉取；经 `_ipv4_getaddrinfo`（`config.py:23`，226 次累计 **13.7s** DNS 慢）。
- `warmup_sector_cache` → `compute_sector_momentum` → `_compute_industry_momentum`（`market_trends.py:68`，**12.8s 但失败** `Connection aborted`）——R32 预热覆盖了板块冷路径，但底层外部源失败，纯空转。

**pyinstrument**：`_warmup_market_cache` 6.6s（主线程）+ `_warmup_sector_cache` 4.8s（失败）+ `_guarded`/`_fetch_us_list` 4.3s（DNS 3.98s）+ `_foreign` 3.1s。

**修复设计（= R44，见 §15.1）**。

---

## 2. 组合设计 600 + 场内策略检查 537

### 2.1 组合设计 600（report_quality=full）
**结构工程良好 + round25/26 修复实证生效**：
- `degradation.mode="normal"`（pool 非空）。
- ✅ R2 强制锚豁免：510300/159338 权重 + correlation_warnings「双方均为强制锚…按豁免不削减」。
- ✅ R24/R41-a 近替代品解耦：三方案均出 near_substitute 告警（大盘宽基/半导体/医药生物/券商族，含 correlation=-0.012 盘后仍识别）。
- ✅ design_text 真实（三方案对比表/层预算/真实涨跌/权重≈5%桶/因子评级偏弱偏强）。

**数据可信度硬伤（核心）**：
- **R42 因子分两屏方向相反**（见 §2.7）：设计 `etfs[].factor_score` = 全池截面 z（510300=-0.986、159338=-0.958、511090=+3.066），策略检查「因子分」= 13 持仓截面 z（159338=+0.16）。两屏对同一标的仍方向相反。
- **R47 R3 残余**：`etfs[].factor_score`（-0.9855288495104011）与 `etfs[].weight`（0.2067）仍精确小数，与 `data_precision`（coarse/bucket）矛盾；design_text 表格已桶化但结构化字段未桶化。
- **R46 R40 残余**：`sector_momentum=[]`、`strong_sector_pool_coverage=[]`（首启空窗）。
- `data_as_of=None`（R26 残余，fresh 容器无快照）、`factor_valid_rate=0.0%`（factor_missing_pct=100%）仍产出精确分数。
- **R48 R41-c 未实现**：防御型三持大盘宽基（510300 5% + 159338 5% + 510050 20.67%）、平衡型双持半导体（588170+588200）、进攻型双持医药（159570+513120）——near_substitute 仅告警不合并。
- 集中度：防御型 510050 单只 20.67%（防御风格下单只超 20% 偏高）。

### 2.2 场内策略检查 537（on_exchange，13 只持仓）
- ✅ **R28 综合信号接通（P0 死代码已修）**：holdings_analysis 每项含 `composite_decision`（signal/score/degraded/reason/components），前端 `AnalysisView.vue:52` 传 `:composite-decision` + `SignalPanel` 渲染。
- ✅ R5 兜底透明：summary「LLM 分析超时（75s 未返回，已用规则引擎兜底）」。
- ✅ R4 confidence=medium、R21 分档标签「因子分 0.16（中性）」、R20 单标的 tech_signal「HOLD，真实信号」。
- ⚠️ **R43 LLM 恒 75s 超时**：日志 `[strategy_check] LLM analysis interrupted after 75.0s (timed out or cancelled: CancelledError)`——LLM 报告从未生成，恒规则兜底。
- ⚠️ **R42 因子分方向相反**：159338 设计 -0.958 vs 检查 +0.16（见 §2.7）。

### 2.3 盘后无动量注入（R46，R40 首启空窗残余）
**现象**：设计 `sector_momentum=[]`、`strong_sector_pool_coverage=[]`——R40-a 读取兜底代码已在（`market_data_hub.py:1658`），但 fresh 容器首启 live 源失败（日志 `_compute_industry_momentum failed: Connection aborted`）→ 磁盘无快照 → `_load_latest_snapshot_sync("sector_momentum")` 返回 None → 仍 `[]`。

**根因（代码级）**：R40-b 仅放宽「非空才写」，未解决「首启 live 源失败 → 永无快照可写」。快照只在 `refresh` 成功时写入（`_persist_snapshot_after_refresh`），首启失败则写不出快照，读取兜底无物可读。

**修复设计**：见 §15.1 R46。

### 2.4 近替代品冗余仅告警不合并（R48，R41-c 未实现）
R41-a（解耦）与 R41-b（前端渲染）已生效，但 R41-c（平衡/防御型合并或留一）未实现——方案仍双持同族近替代品（见 §2.1 R48）。

### 2.5 综合信号接通（R28 已修复，本轮实证）
`composite_decision` 后端序列化（LLM + 规则兜底两路径）→ 前端 `AnalysisView.vue:52` 传 prop → `SignalPanel` 渲染「🧮 综合信号」卡。R28-a/b/c 全部落地，P0 死代码消除。

### 2.6 自选收盘快照兜底周末落空（R45，R29 残余）
**现象**：GET watchlist 5.86s、0/23 条带 realtime、0 条带 `is_estimated`（「估」徽标永不出现）。

**根因**：R29 的 5s 超时回退走 `_watchlist_close_fallback`（`market.py:952`）→ 逐条 `_last_close_fallback`（0.8s 超时）→ 该函数依赖历史 K 线源 → 周末/源冷却时**兜底自身也 None** → 行 `realtime=None` + `_degraded`（A 股）或 `realtime_unavailable`（US/HK）。R29 解决了「裸 DB 行」，但「收盘快照兜底」在快照源也断时无第二层兜底。

**修复设计**：见 §15.1 R45。

### 2.7 因子分两屏方向仍相反（R42，R27 残余）
**根因（本轮实证）**：
- 设计路径：`etfs[].factor_score` = `factor_registry.compute()` 跨**全候选池**截面 z-score 加权复合（`allocation_engine.py:401-405/:623`）→ 159338 = **-0.958**（深负，近剔除线）。
- 策略检查路径：`_cross_sectional_factor_composite`（`portfolio_service.py:1586`）对每个因子键在**组合内 13 只持仓**上 z-score 归一 → 159338 = **+0.16**（中性略正）。
- **方法已统一（均 z-score），但参考群体不同（全池 vs 持仓）** → 同一标的在两屏方向仍相反。R27 验收口径「两屏方向一致」未达成。策略检查对「相对全池的强弱」无感知——一只在全池垫底（-0.958）的标的，若其持仓组合整体更弱，会在持仓截面里显示「中性偏正」（+0.16）。

**修复设计**：见 §15.1 R42。

### 2.8 综合信号结构性恒 hold（R52，用户 review 驱动新增）
**现象（用户提问）**：「现在组合持仓里的标的，所有综合信号都是持有，这合理吗？」——经查，本轮 13 只持仓 `composite_decision.signal` **全部 hold**（`degraded=false`），即便 `technical_signal` 有 buy（513120/159869）也有 sell（512890/159545/512000/561560）。「综合信号」等于一个永不给出方向的假信号。

**根因（代码级，两层）**：
1. **结构性：估值/动量恒 0 → 技术单项永远够不到阈值**。`composite_signal`（`app/analysis/signal.py:34`）聚合公式 `score = 0.4×技术 + 0.4×估值 + 0.2×动量`，buy 阈值 +0.5、sell 阈值 -0.5（`:40-45`）。`_attach_composite_decisions`（`portfolio_service.py:1571-1574`）按 `_COMPOSITE_FACTOR_MAP`（`:1533-1537`）聚合三分项——但周末 `factor_scores` 只有技术类因子（RSI/KDJ/MACD），`valuation.*`/`momentum.*` 键无命中 → `components["valuation"]=0.0`、`components["momentum"]=0.0`。于是 `score = 0.4×技术 ∈ [-0.4, +0.4]`，即使技术封顶 +1.0（最强买）也只有 0.4 < 0.5 → **数学上永远 hold**。
2. **门禁失效：valid_rate 口径错**。`composite_signal_with_gate` 有降级门禁（`signal.py:85`：`factor_valid_rate<0.6` → `degraded=true, signal=None`，避免「因子缺失仍合成假结论」）。但 `_attach_composite_decisions:1556-1558` 把 valid_rate 算成 `filled_count/total_count`（`:1022-1030` 的「有真实因子值的**持仓数**/持仓总数」= 13/13 = 100%，技术类因子即算 filled），**而非「估值/动量分项覆盖率」** → 门禁看到 valid_rate=100% ≥ 60%，误判「数据完整」，放行估值/动量恒 0 的假综合信号，标 `degraded=false`。

**与 R28 的关系**：R28（round25）把综合信号从「前后端死代码」接成了「真实渲染」，但接通后暴露出「内容质量缺陷」——R28 解决了「看不看得到」，R52 是「看到的内容是恒 hold 的假信号」。两者不矛盾，R52 是 R28 接通的下一层问题。

**修复设计**：见 §15.1 R52。

### 2.9 美股/港股指数分析数据源未路由（R53，用户 review 驱动新增）
**现象（用户提问）**：美股标的分析「指数」tab 选「标普500」→ 输出 `unsupported_market: US`，技术指标、最近 30 条 K 线、PE/PB 估值均不可用，报告退化为「基于有限资讯的定性分析」。诚实降级本身正确（不虚构指标、正确识别资讯里 SPX=Shopee Express 并剔除），但**美股指数实时数据源其实存在、只是没路由**。

**根因（代码级，两层）**：
1. **过防护切断数据源**：`get_asset_realtime`（`market_service.py:1233-1246`）对 `asset_type=index` 的 US/HK 分支显式返回 `{"unsupported_market": _idx_market, "error": "该市场指数暂不支持"}`——这是 round16 P0-22④ 的「过防护」（当时防「美股 tab 选 GEM 港股指数 → A 股路径查无 → 前端报错」），对所有 US/HK 指数一刀切。但 `_GLOBAL_INDEX_DEFS`（`:141-163`）已含标普500（`^GSPC`）/纳斯达克（`^IXIC`）/道琼斯（`^DJI`）/恒生（`^HSI`），`get_global_indices`（`:269`）经 `_foreign`（`:361`）真实拉取这些指数实时价/涨跌幅——**数据源是通的，只是 `asset_type=index` 路径没去查它**。
2. **符号错位**：`indices_meta` 表存 `SPX`（标普500），global indices 用 `^GSPC`（Yahoo 代码）——即便把路由接上，也需 `SPX→^GSPC`、`IXIC→^IXIC`、`DJI→^DJI`、`HSI→^HSI` 的符号映射。

**K线/PE/PB 单独说明**：K 线（`chart` → `get_market_history`）对美股指数未接 yfinance/alphavantage（美股个股 AAPL 实测 500 行，指数无）；PE/PB 指数级估值无可靠源，保持诚实降级正确，不应硬凑。

**修复设计**：见 §15.1 R53。

### 2.10 美股指数种子表混入 ETF + 彭博代码重复（R54，用户 review 驱动新增）
**现象（用户提问）**：美股「指数」tab 搜「标普」同时冒出「标普500指数」(SPX)、「SPDR标普500ETF」(SPY)、「标普500指数(彭博代码)」(^GSPC)——指数搜索被 ETF 污染；反向在「个股/ETF」tab 搜 SOXX/XLB 却搜不到（它们被错放进了指数表）。

**根因（代码级）**：`_STATIC_EXTRA_INDICES`（`sync_indices_meta.py:153-209`）美股段混入：
- **3 条 ETF 冒充指数**：`:192` `SPY`（SPDR标普500ETF）、`:200` `SOXX`（iShares半导体ETF）、`:204` `XLB`（SPDR材料指数ETF），均 `index_type=price`、`source=static`，被 `indices_meta` 同步入库 → 指数搜索污染。
- **3 条彭博代码重复**：`:201-203` `^GSPC`/`^DJI`/`^IXIC` 与 `:191/:193/:194` 的 `SPX`/`DJI`/`IXIC` 完全重复（仅「(彭博代码)」后缀）。
- **双向错位**：SOXX/XLB 不在 `HKUS_ETF_MAP`（`market_service.py:600-626`，美股 ETF 基座仅 SPY/QQQ/IVV/VOO/VTI/GLD/SLV/FXI/KWEB/EEM/DIA/IWM）→ 个股/ETF tab 搜不到这两个真 ETF。

**为何不建议合并 tab（用户追问）**：合并是治标——指数与个股/ETF 是不同资产类型（基准 vs 可交易标的）、数据源与分析语义都不同，且 A 股侧本就分开。根治 R53（指数分析接源）+ R54（种子表卫生）后，两 tab 语义清晰且各自可用。

**修复设计**：见 §15.1 R54。

### 2.11 因子模型页 27 因子恒 no_data（R55，用户 review 驱动新增）
**现象（用户提问）**：「现在很多因子没有数据，分析一下看看是什么原因，能不能修复？」——`factors/active` 显示 `valid=0 / no_data=27 / static=11`，27 个非静态因子全部「no_data（积累中）」。

**根因（代码级，实证）**：
1. **IC 显著性门槛高**：`_status_of`（`routers/factors.py:99-138`）要求 `sample_count ≥ 250` 交易日（`MIN_TRADING_DAYS=250`，`:35`，约 1 年）且 t≥2/|IR|≥0.5 才判 valid；`60 ≤ sample_count < 250` 仍判 no_data（「可观察」）。
2. **sample_count 是「累计交易日数」**：语义 = `count(distinct trade_date)`（`ic_tracker.py:352`）——即 IC 被计算过的天数，不是 K 线历史深度。
3. **IC 是增量计算、无历史回填**：`_ic_persistence_loop`（`main.py:442`）每 120s 循环，`save_ic_batch_to_db`（`ic_tracker.py:278`）用 `_beijing_today()`（`:302`）打**当天**日期，每天只累计 1 个样本；`compute_periodic_ic`（`:193`）只算「当前」截面 IC。**没有任何从历史 K 线反推过去截面 IC 的回填机制**。
4. **实证**：生产库 `factor_ic_records` 表 `distinct trade_date = 3`（2026-08-14~16），每因子 sample_count=3 < 250 → 恒 no_data。fresh 容器/DB 重置后需运行 ~1 年才翻绿。

**与 R52 的区别（易混）**：R52 是「因子**值**缺失」（估值/动量因子周末无值 → 综合信号恒 hold）；R55 是「因子 **IC 显著性**样本不足」（因子模型页的 valid/no_data 状态）——两个独立问题。技术因子（RSI/KDJ/MACD）**值**有（从 K 线算），但它们的 **IC 样本也只有 3 天**。

**能否修复**：能。IC 是截面统计量（某日全市场因子分与未来收益的秩相关），可从已有 ~320 天 K 线缓存对每个历史交易日 T 反推截面 IC 一次性回填，因子立即达到 250 天门槛。需 `factor compute` 支持「历史快照」输入（目前只算「当前」因子分）。

**修复设计**：见 §15.1 R55。

---

## 3-9. 各验收动作要点（详见 §0.2 表，此处列关键证据）

### 3. A/HK/US 行情分析（全能力真实可用，唯一问题是延迟）
- 综合研判：上证 3927.18（+0.01%）、range_bound，first_byte **53.9s**。
- 个股 600519：PE 36.48 / 2026H1 营收 907 亿 +1.47% / 归母 -1.95% / Q2 环比 -36%，first_byte 71.7s。
- 个股 00700 HK：Q2 营收 2047.9 亿 +11% / 回购 / 南向 56.16 亿，PE/PB 诚实标注不可用，first_byte 36.6s。
- 个股 AAPL US：Q3 营收 1094 亿 +16% / 净利 +27% / PE 34.63，first_byte 34.6s。
- 板块 电子 BK1201：13183.76 +1.78% / 主力净流出 -64.7 亿背离 / ETF 净流出 596 亿，first_byte 78.2s。
- 概念 500 条（CPO +3.18%）；指数 indices/global 真实（R37 已修复）。
- 搜索补全 A/HK/US 全通；费城→SOX、恒生港股通高股息低波动（H11148）——Q4/Q6 已修复。
- HK K 线 00700/09988/01810=320 行、AAPL=500 行——Q2/Q3 已修复。

### 4. 热点 + 自选
- 热点 hot-plates 13 条（光通信 +2.88%）、sectors/heat 电子 565616.5、stock-hot-rank 50 条——加载成功。
- 自选 POST 201 + GET 正确；但列表实时见 R45。

### 5. 持仓技术分析
- 6 只全 `data_available=True` + reasons（MACD/KDJ/RSI/MA/BOLL）自洽；R28 综合信号接通（§2.5）。

### 6. 资讯
- R16 英文分类生效（category=neutral/risk）；headlines 15/macro 5/global 8。
- ⚠️ ai_summary 全 null（LLM 配额耗尽，R39 gate 生效后新闻摘要让位于主链路）。

### 7. 因子模型
- R22 avg_ic 统一 0.2665（active/model 一致）；valid=0/no_data=27/static=11（fresh 容器周末 sample<250）。

### 8. 前后端断裂
- check_routes PASS；R28 composite_decision / R29 realtime_unavailable / Q5 quickSelect 字段级断裂均已修复。

---

## 10. round25/26 方案落地核验（完整矩阵）

### round25 R27-R41
| ID | 状态 | 证据 |
|---|---|---|
| R27 因子口径 | ⚠️ **未完全达成** | 方法统一（均 z-score），但参考群体不同 → 方向仍相反（R42） |
| R28 综合信号 | ✅ 已修复 | composite_decision 序列化 + 前端 wiring |
| R29 watchlist 兜底 | ⚠️ 部分 | 代码路径 + 前端 4 态在；`_last_close_fallback` 周末全 None（R45） |
| R30 scripts 迁移 | ✅ 已修复 | indices_meta 容器内同步 641 行 |
| R31 新闻分桶 | ✅ 已实现 | 3/2/1 配额代码在；ai_summary null 因 LLM 429 |
| R32 预热板块 | ⚠️ 反噬 | 新增 12.8s 且底层失败（R44） |
| R33 预热性能 | ❌ 未实施 | F1/F2/F3 仍缺失，预热 34.5s |
| R34 root perf/a11y | ⚠️ 未达标 | root 75<90、a11y 82<90（R51） |
| R35 verify_perf | ✅ 已修复 | 真 SSE 端点 |
| R36 精度表格 | ⚠️ 部分 | design_text 桶化；结构化字段仍精确（R47） |
| R37 indices/global | ✅ 已修复 | 返真数据 |
| R38 临时文件 | ⚠️ 部分 | backend 根 0；logs 224 个残留（R50） |
| R39 LLMQuotaGate | ✅ 已实现 | 429→60s 暂停 + throttle；但 75s 超时未解（R43） |
| R40 板块动量快照 | ⚠️ 部分 | 读取兜底在；首启空窗无快照（R46） |
| R41 近替代品 | ⚠️ 部分 | a/b 生效；c 合并未实现（R48） |

### round26 Q1-Q7
| ID | 状态 | 证据 |
|---|---|---|
| Q1 指数引导 | ✅ 已修复 | placeholder「ETF 请切个股/ETF 模式」 |
| Q2/Q3 HK K 线 | ✅ 已修复 | 00700/09988/01810=320 行 |
| Q4/Q6 指数种子 | ✅ 已修复 | 费城 SOX、恒生港股通高股息低波动 H11148 |
| Q5 quickSelect | ✅ 已修复 | `searchQuery.value = ex.code` |
| Q7 美股指数 | ✅ 已修复 | 随 Q6 |

**核验结论**：round25/26 共 26 项中 **15 项完全达成、8 项部分达成、2 项未实施（R33）、1 项反噬（R32）**。核心 P0（R28 综合信号死代码）已消除；但 R27/R29/R36/R40 四个「口径/兜底」类修复因**参考群体/兜底链/结构化字段/首启空窗**四个更深层的子问题，目标未完全达成。

---

## 11. 前端 Lighthouse（4 路由）
| 路由 | perf | a11y | CLS |
|---|---|---|---|
| / | 75（round25 69） | 96 | 0.001 ✓ |
| /market-analysis | 87 | 96 | 0.001 ✓ |
| /portfolio-analysis | 72（round25 77 ↓） | 82 | 0.001 ✓ |
| /news | 97 | 95 | 0.001 ✓ |

- ✅ R8 CLS 全 0.001（修复保持）。
- ❌ R9/R34：root perf 75（<90，FCP 2.0s / TBT 440ms / speed-index 5.7s）。
- ❌ R10/R34：portfolio-analysis a11y 82（对比度不足）。
- ⚠️ portfolio-analysis perf 77→72 微降（LCP 3.7s、TBT 600ms）。

---

## 12. 后端链路性能（冷/热态）
| 端点 | 热态 | 冷态（首呼） | 判定 |
|---|---|---|---|
| /portfolio/timeline | 20ms | — | ✅ |
| /admin/metrics | 0ms | — | ✅ |
| /factors/active | 0ms | — | ✅ |
| /news/headlines | 0ms | — | ✅ |
| /portfolio/designs | 20ms | — | ✅ |
| /portfolio/etfs | 40ms | — | ✅ |
| /market/stock-hot-rank | 210ms | 4.89s | ❌ 冷态 |
| /market/sectors/heat | 20ms | 3.12s | ⚠️ 冷态 |
| /market/indices/global | 0ms | 4.07s | ⚠️ 冷态 |
| /market/watchlist | 30ms（3s 端级缓存） | 5.86s | ❌ 冷态 |
| /market/search 银 | — | 6.87s | ❌ 冷态 |

**结论**：热态全 <210ms（R7 已基本达标）；冷态 4 个端点 >3s（watchlist 5.86s / search 6.87s / stock-hot-rank 4.89s / indices 4.07s）。R32 预热只覆盖了 sector cache（且失败），未覆盖 stock-hot-rank/indices/search/watchlist 冷路径。

---

## 13. 测试防护缺口分析（为何现有测试未识别）

1. **R42（因子分跨屏方向）**：`test_round25_r27_factor_caliber.py` 只断言策略检查**内部**截面一致性（`comps["159338"] < comps["510300"]`），从不比「设计全池 z（-0.958）」vs「检查持仓 z（+0.16）」的**跨屏方向**。方法统一 ≠ 方向一致，测试未验证后者。
2. **R45（watchlist 兜底失败）**：`test_round25_r29_watchlist_close_fallback.py` mock `_last_close_fallback` 返数据（快乐路径）；真场景（兜底自身周末失败）被 `test_fallback_miss_honest_degrade` 断言为「realtime=None 是诚实降级」，**未标为用户可见缺口**。测试不抓「兜底链整体断裂」。
3. **R47（R36 结构化字段）**：`test_round25_r36_precision_tables.py` 只验 design_text **表格**桶化（「偏弱」/「≈20%」），不验 `etfs[].factor_score`/`weight` **结构化字段**（仍 -0.9855/0.2067）。元数据与数据矛盾无断言。
4. **R46（R40 首启空窗）**：`test_round25_r40_sector_momentum_snapshot.py` 的 `test_snapshot_empty_stays_empty` 断言「无快照 → `[]`」为**正确行为**，不标「用户盘后无动量」为缺口。
5. **R43（LLM 75s 超时）**：无测试量 LLM 首字节延迟或断言超时足够；R5 兜底透明使测试绿，但用户永不见 AI 报告。
6. **R44（预热回归）**：预热 profiler 只写报告不设预算断言；R33 未实施，无门禁拦截 20s→34.5s 回归。
7. **R49（first_byte 慢）**：verify_perf 软门禁（WARN 不 FAIL），且阈值 5s 远低于实际 34-78s。

**共性**：测试验证「方法已应用」而非「目标已达成」（方向一致/兜底有效/字段桶化/首启可用），且全部 mock 外部依赖的快乐路径，未测「兜底链也断」的复合失败场景。

---

## 14. 冗余代码
- ✅ backend 根 scratch `_*.py`/`apply_*.py`/`test_deepseek.py`：0 个（R38 已删 20+）。
- ⚠️ `logs/round{8,16,18,20}/*.py`：**224 个**未清理（已 gitignore，磁盘残留；round8=20/round16=88/round18=16/round20=99/tmp=1）。
- ⚠️ 测试文件 220 个（backend/tests）：`test-redundancy-audit`（a828fe9）折叠 33 早期文件后仍 220 个，round24 起的 8 个专项文件待关闭后同流程折叠。

---

## 15. 修复方案总表（R42-R55，不实施）

### 15.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R42 | P0 | 因子分两屏方向相反：设计=全池截面 z（159338=-0.958），检查=13 持仓截面 z（+0.16） | **采纳方案(a) 统一参考群体（决定）：** 策略检查的「因子分」不再用 13 持仓截面 z（`_cross_sectional_factor_composite`，`portfolio_service.py:1586`），改为复用设计同源的全池截面复合分——`market_data_hub.get_factor_matrix()` 已产出的全池截面 z（即设计 `allocation_engine:401-405/:623` 的输入），对每只**场内持仓**按其 symbol 查全池 z 行做 `aggregate_factor_scores` 分类加权复合。**场外联接基金（不在池内，如 022449）**回落 `_within_symbol_factor_composite`（`:1628`，绝对口径），并在 reason 显式标注「因子分（单标的口径，场外联接无池内截面）」诚实降级。**方案(b) 标签补全（配套）：** 两屏 reason 均加参考群体字样——设计「因子分（相对候选池）」，策略检查场内持仓「因子分（相对候选池）」，场外「因子分（单标的）」。删除 `_cross_sectional_factor_composite` 的持仓截面语义（或保留仅供单测但不再被 `_rule_based_suggestion` 主路径调用）。 | ①单测（抓假负向）：同标的（场内）design `etfs[].factor_score` 与 strategy_check「因子分」**方向一致**（159338 两屏同负，禁再出现「设计 -0.958 vs 检查 +0.16」）；②场外持仓 reason 含「单标的口径」标注；③负向断言：禁止对持仓子集重做截面 z 冒充全池 z | `portfolio_service.py:1586-1625/:1628/:1675/:1775-1779`、`market_data_hub.get_factor_matrix`、`allocation_engine.py:401-405/:623` |
| R45 | P1 | watchlist 收盘兜底周末落空（`_last_close_fallback` 自身失败） | ①`_watchlist_close_fallback`（`market.py:952`）加第二层兜底：`_last_close_fallback` None 时回退 Redis last-good 报价（`cache_service.py:105` 已支持 Redis，`quote_key` 写入侧延长 TTL 至 24h 使其跨周末存活）；②双断（realtime + 快照 + last-good 全无）时，前端 `WatchlistPanel.vue:140/147` 的「行情暂不可用」文案升级为「非交易时段无行情（数据源维护中）」+ 显式时间戳，诚实区分「没波动」vs「没数据」；③last-good 命中时标注 `data_source="stale"` + `as_of`（与 `_degraded` 区分） | ①单测（抓假负向）：mock `_last_close_fallback` 返 None + 注入 Redis last-good → 行 realtime 非 None 且 `data_source=stale`；②三断场景断言「诚实的维护中标注 + 时间戳」而非空白冒充；③Redis last-good TTL 24h 断言 | `market.py:952-992`、`cache_service.py:105`、`market_service.py:_last_close_fallback`、`WatchlistPanel.vue:127-153` |
| R46 | P1 | R40 首启空窗：live 源失败 → 永无快照可读 | ①首启 `refresh` 失败时，从 **新浪行业 spot**（`ak.stock_sector_spot(indicator="新浪行业")`，**D1 探针已通过**：49 行含「涨跌幅」字段，盘后可用）**单独兜底拉一次**写 `sector_momentum` 快照（**注意：东财 `stock_board_industry_name_em` 探针实测被阻断 ProxyError，勿用**；新浪行业与设计 `SECTOR_ETF_MAP` 板块名匹配度需在实施时验证）；②快照 as_of 非今日时，设计链路/报告显式标注 `sector_momentum.as_of`（诚实呈现快照时效，替代当前 `data_as_of=None`）；③写侧已放宽「非空即写」（R40-b），补「首启失败路径也尝试写」 | ①单测：mock live 源失败 + 注入新浪行业板块数据 → 快照非空写入；②盘后首启 `verify_e2e` 设计链路 `sector_momentum` 非 []；③快照 as_of 非今日时前端/报告显式标注；④新浪行业名与 `SECTOR_ETF_MAP` 匹配度断言 | `market_data_hub.py:1658/:1363`、`market_trends.py:68`、`ak.stock_sector_spot` |
| R52 | P1 | 综合信号结构性恒 hold（估值/动量恒 0 + 门禁 valid_rate 口径错）：`composite_signal`（`signal.py:34`）`0.4技术+0.4估值+0.2动量`，周末估值/动量恒 0 → `0.4×技术∈[-0.4,+0.4]` 永不够 ±0.5 阈值 → 恒 hold；且 `_attach_composite_decisions:1556-1558` 的 valid_rate=「持仓级填充率」13/13=100% 而非「分项覆盖率」→ 门禁不降级、标 `degraded=false` | **采纳「分项覆盖率门禁 + 诚实降级」：** ①`_attach_composite_decisions` 改算**分项覆盖率**——对 `_COMPOSITE_FACTOR_MAP` 三分项（technical/valuation/momentum）统计「有真实因子值（非 0、非兜底默认）的分项数 / 3」，作为 `factor_valid_rate` 传入 `composite_signal_with_gate`；估值/动量分项全缺（周末）→ valid_rate=1/3<0.6 → `degraded=true, signal=None`（诚实「综合信号不可用，退化为纯技术信号」，技术 buy/sell/hold 仍由 `technical_signal` 字段独立呈现，不丢信息）。②（配套）分项缺失但未达降级阈值（≥2 分项可用）时，对可用分项**权重归一**（如缺估值 → `score=0.4技术+0.2动量 / 0.6`），避免缺失分项静默稀释分数；③前端 `SignalPanel` 的 `degraded` 徽标（round24 R25 已渲染）在 `signal=None` 时显示「因子缺失，综合信号不可用」而非「hold」 | ①单测（抓假负向）：mock 估值/动量分项无值（仅技术类因子）→ `composite_decision.degraded=true` 且 `signal=None`（禁再出现「degraded=false + signal=hold」的假综合信号）；②单测：三面齐全（技术+估值+动量均有真实值）→ 综合信号**能产出 buy/sell**（负向：三面齐全仍恒 hold → FAIL）；③权重归一单测：缺估值时 score 不被 0.4 权重稀释（断言与归一后一致） | `portfolio_service.py:1556-1558/:1571-1574/:1022-1030`、`app/analysis/signal.py:34/:40-45/:85`、`SignalPanel.vue` |
| R53 | P1 | 美股/港股指数分析数据源未路由：`get_asset_realtime`（`market_service.py:1233-1246`）对 `asset_type=index` 的 US/HK 显式返回「该市场指数暂不支持」（round16 P0-22④ 过防护），但 `_GLOBAL_INDEX_DEFS`（`:141-163`）已含 ^GSPC/^IXIC/^DJI/^HSI、`get_global_indices`（`:269`）经 `_foreign`（`:361`）真实拉取；符号错位（indices_meta 存 SPX vs global 用 ^GSPC）；K 线 `fetch_index_history`（`china_market.py:1465`）**只处理 HK（腾讯 hk{code}）/A（akshare）**，US 指数被误路由（`SPX` 字母→走 HK 腾讯→空；`^GSPC` 非字母→走 A akshare→空）。**D1 探针已通过**：新浪 `ak.stock_us_daily('.INX')` 返回 **5693 行**（2004-01-02~2026-08-14）——美股指数 K 线**数据源有**，只是符号错位（代码传 ^GSPC，新浪要 `.INX`；alphavantage 免费层对 SPX 返 0 不可用） | ①`get_asset_realtime` 的 US/HK 指数分支改查 `get_global_indices`（**符号映射** SPX→^GSPC、IXIC→^IXIC、DJI→^DJI、HSI→^HSI 等，`_GLOBAL_INDEX_DEFS` 已含全表）；②美股指数 K 线走**新浪 `stock_us_daily`**（**符号映射** ^GSPC→`.INX`、^IXIC→`.IXIC`、^DJI→`.DJI`，探针已确认 5693 行；`fetch_index_history` 增 US 分支调 `stock_us_daily`）；③PE/PB 指数级估值保持诚实降级（无源不虚构）；④指数 tab 选标普500 → 出真实指数分析（非 `unsupported_market`） | ①单测（抓假负向）：mock `_lookup_index_market` 返 US + 注入 get_global_indices ^GSPC → realtime 非 None 且无 `unsupported_market`；②符号映射单测：SPX→^GSPC、^GSPC→.INX 命中；③美股指数 K 线 ≥250 行（探针已确认 5693 行）；④`fetch_index_history("^GSPC")` 不再误路由到 HK/A 分支 | `market_service.py:1233-1246/:141-163/:269/:361`、`china_market.py:1465/:1684-1725`、`market.py:503`（chart）、`market_data_hub.get_market_history` |
| R54 | P2 | 美股指数种子表混入 ETF + 彭博代码重复：`_STATIC_EXTRA_INDICES`（`sync_indices_meta.py:153-209`）美股段混入 SPY/SOXX/XLB 三条 ETF（`:192/:200/:204`）+ ^GSPC/^DJI/^IXIC 三条重复（`:201-203`）；SOXX/XLB 不在 `HKUS_ETF_MAP`（`market_service.py:600-626`）→ 双向错位 | ①`_STATIC_EXTRA_INDICES` 删 SPY/SOXX/XLB 三条 ETF + ^GSPC/^DJI/^IXIC 三条重复（保留 SPX/DJI/IXIC 即可）；②SOXX/XLB 补进 `HKUS_ETF_MAP`（个股/ETF tab 正确命中）；③`indices_meta` 同步后指数搜索不含 `type=etf` 条目 | ①单测（抓假负向）：美股指数搜索「标普」只出 SPX 一条（不含 SPY/^GSPC）；②个股/ETF 搜索 SOXX/XLB 命中（type=etf）；③`_STATIC_EXTRA_INDICES` 无 `index_type` 伪装的 ETF 条目 | `sync_indices_meta.py:153-209`、`market_service.py:600-626`（HKUS_ETF_MAP）、`market.py:227`（_search_indices） |
| R55 | P1 | 因子模型页 27 因子恒 no_data：IC 显著性需 `sample_count≥250` 交易日（`MIN_TRADING_DAYS=250`，`factors.py:35`），但 IC **增量计算**（`save_ic_batch_to_db` 用 `_beijing_today()` 打当天日期，`ic_tracker.py:302`）、**无历史回填** → 生产库 `factor_ic_records` 仅 3 个 distinct trade_date → 所有因子 sample_count=3 < 250 → 恒 no_data，需运行 ~1 年才翻绿 | **采纳「IC 历史回填」：** ①新增 `backfill_ic_history` 任务——复用 K 线缓存，对每个历史交易日 T 用「截至 T 的因子分」算截面 IC（`compute_periodic_ic` 需支持历史快照输入：新增 `factor_values_by_day` 参数或独立 `compute_ic_series`），一次性落库 IC；②`factor compute` 支持历史快照（对每个 T 重放 K 线截断到 T 算因子分）；③回填后 `_status_of` 翻「可观察」（探针实测 A 股 ETF K 线 **240 交易日**，回填得 ~239 IC 样本，差 250 门槛 ~11 天——**回填后先到「可观察」，再自然积累 ~11 个交易日到「有效」**，符合用户「要做、接受等自然积累」决策；如需立即翻「有效」则回填用更深源 BaoStock/TickFlow 拉 ≥250 天历史，可选增强）；④回填作为后台一次性任务（启动或手动触发），不阻塞请求 | ①单测（抓假负向）：mock 240 天 K 线 + 注入历史因子分 → `factor_ic_records` distinct trade_date ≥ 230；②`_status_of` 对回填后样本断言「可观察」而非「积累中（<60）」；③负向：无回填时不得谎报 valid（保持诚实积累中）；④复杂度审计：回填为一次性批量计算，无请求路径 IO | `ic_tracker.py:193/:278/:302/:352`、`main.py:442`（_ic_persistence_loop）、`factor_registry.compute`、`factors.py:99-138`（_status_of） |

### 15.2 性能

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R43 | P1 | 策略检查 LLM 恒 75s 超时 | ①`_llm_timeout_for`（`portfolio_service.py:818-833`）「数据完整」分支 75s→**180s**（对齐 design-report 的 120s 并留余量，策略检查报告 token 更长；首字节即 34-78s）；②超时前用「进度心跳」告知前端仍在生成（非静默）；③LLM 失败时 summary 显式区分 `rate_limited/timeout/error`（R39 已设计 `fallback_reason`，本轮落地） | ①交易时段背靠背 design→strategy-check 至少一次产出真 LLM 报告（非规则兜底）；②`fallback_reason` 正确分类 | `portfolio_service.py:818-833`、`strategy_check_worker.py:138`、`design_report.py:524` |
| R44 | P1 | 预热 34.5s 回归（R32 反噬 + F1/F2 未实施） | ①**R32 回滚**：`warmup_sector_cache` 的 `compute_sector_momentum` 改**后台异步**（不阻塞 startup 就绪），或移出 warmup 关键路径；②**F2 落地**：`requests.Session` 复用（149 次 SSL 握手 → 1 次，省 ~15s）；③**F1 落地**：fund NAV 降精度/后台化（省 16.7s）；④`_fetch_us_list` 的 `_ipv4_getaddrinfo` DNS 缓存（省 ~9s） | ①预热 ≤15s（R33 阈值）；②warmup_timing.json 各阶段占比合理；③sector cache 失败不再拖长 startup | `main.py:_warmup_sector_cache`、`china_market.py:1391`、`config.py:23`、`sync_instruments.py:238` |
| R49 | P2 | LLM first_byte 34-78s | ①SSE 流式前先发「正在调用模型」事件 + 进度条（非空白 spinner）；②可选：缓存热点问题（综合研判/板块）的结果按 (query, data_as_of) 键，交易日同源复用 | ①首字节前有可见进度；②同 query 二次请求 ≤ 缓存命中时间 | `analysis.py:_sse_stream`、`llm.py` |

### 15.3 治理 / 呈现

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R47 | P2 | `etfs[].factor_score`/`weight` 结构化字段仍精确小数 | ①`generate_enhanced_design` 输出降级态（`factor_score_display=bucket`）时，`etfs[].factor_score` 返分档字符串（「偏弱」）或区间，`etfs[].weight` 返 5% 档（0.20/0.25）；②exact 态保留小数。前端 `DesignResult.vue` 按 `data_precision` 选择展示 | ①coarse 态 `etfs[].factor_score` 无 -0.9855 精确值、weight 为 5% 档；②exact 态不变 | `strategy_design.py:_build_market_context`、`DesignResult.vue` |
| R48 | P2 | 近替代品仅告警不合并 | **落地 R41-c（用户决策：三型均合并留一）**：**防御/平衡/进攻三型**对 `_SUBSTITUTE_FAMILIES` 同族近替代品做**合并留一**（保留流动性更好/更宽基者，合并权重打标）——用户明确「追求集中应优先重仓单只，而非分多个同主题标的持有」，故进攻型不豁免。`near_substitute_pairs`（`allocation_engine.py:746`）检测后，在 `apply_near_substitute_warnings`（`:1490`，调用 `:1512`）之后新增 `_merge_substitute_family` 层（三型统一执行） | ①单测：三型「芯片+半导体设备」「港股创新药+港股通创新药」均只留其一；②三方案 near_substitute 告警从「仅提示」升级为「已合并」标注；③负向：进攻型不再豁免（同族双持 → FAIL） | `allocation_engine.py:746/:1490/:1512`、`strategy_design.py:408` |
| R50 | P2 | logs/*.py 224 个残留 | 删除 `logs/round{8,16,18,20}/*.py` 或移 `scripts/scratch/`；.gitignore 已覆盖，纯磁盘清理 | 磁盘无 logs/*.py | `logs/` |
| R51 | P2 | root perf 75<90、a11y 82<90 | 沿用 round24 F4/F5：首屏 critical CSS 内联 + render-blocking JS 消除 + portfolio-analysis 对比度修正 | root perf ≥90、a11y ≥90 | `vite.config.js`、`index.html`、`PortfolioAnalysis.vue` |

---

## 16. 分三批实施建议（不实施，等待指令）
- **批1（P0 数据可信度）**：R42（因子分跨屏方向统一）。
- **批2（P1 正确性/性能）**：R43（策略检查 LLM 超时）、R44（预热回归 + F1/F2）、R45（watchlist 兜底链）、R46（首启空窗）、R52（综合信号分项覆盖率门禁 + 诚实降级）、R53（美股/港股指数分析数据源路由）、**R55（IC 历史回填）**。
- **批3（P2 治理）**：R47（结构化字段桶化）、R48（近替代品合并）、R49（first_byte 进度）、R50（logs 清理）、R51（root perf/a11y）、R54（指数种子表卫生）。

> **当前状态：等待「开始实施」指令，不写任何修复代码。**（R42-R55 设计就绪）

---

## 17. 多轮 review 记录

- **Round 1（证据链核查，本次完成）**：对照代码逐条核查 §15.1 file:line。发现并修正 2 处：
  1. R43 超时源定位错误——75s 不在 `strategy_check_worker.py`，而在 `_llm_timeout_for`（`portfolio_service.py:818-833`，「数据完整」分支 75s，round14 P0-B 90→75）；worker 经 `strategy_check` 服务调用该函数。已改 R43 file:line 为 `portfolio_service.py:818-833` + worker 调用点。
  2. R48 near_substitute_pairs 调用点行号错误——round25 文档写 `:1618`（旧行号），当前 `near_substitute_pairs` 定义在 `:746`、独立层 `apply_near_substitute_warnings` 在 `:1490`、调用在 `:1512`（R41-a 解耦后已从 `enforce_max_correlation` 内移出）。已改 R48 file:line。
  其余核查通过：`_cross_sectional_factor_composite:1586`、`_within_symbol_factor_composite:1628`、`allocation_engine:401-405/:623`、`get_sector_momentum:1658`、`_watchlist_close_fallback:952`、`_fetch_us_list:238`、`near_substitute_pairs:746` 全部准确。

- **Round 2（R42 就绪度升级，本次完成）**：初稿 R42 含「方案(a)/(b)/(c)」多选项，属「设计方向」非「可实施」。已采纳**方案(a) 统一参考群体（决定）**——策略检查场内持仓「因子分」改用设计同源的 `get_factor_matrix()` 全池截面 z（非 13 持仓重做截面），场外联接回落 `_within_symbol_factor_composite` 并标注「单标的口径」；方案(b) 标签补全作配套。删除原「或退而求其次」的摇摆表述，达到实施标准（精确 file:line + 负向断言）。

- **Round 3（R45/R46 可行性 D1 审计，本次完成）**：
  1. R45 确认 `cache_service.py:105` 已支持 Redis（`redis_url` 配置），「last-good 报价跨周末存活」可行（写入侧延长 TTL 至 24h）；双断场景改诚实文案而非空白。无需新增外部依赖。
  2. R46 的「akshare 日频板块兜底」标注 **D1 探针前置**（需验证 `stock_sector_spot`/`stock_board_industry_name_em` 盘后可用），探针失败则 R46 降级为「快照 as_of 诚实标注」最小修复（不含外部源兜底）。符合 AGENTS.md D1「探针失败 → 方案不进实施清单」。

- **Round 4（design-checklist D1-D8 合规终检）**：

| 项 | D1 探针 | D2 证据链(file:line) | D3 窗口 | D4 非兜底 | D5 真实调用点 | D6 四态 | D7 复杂度 | D8 已知模式 |
|---|---|---|---|---|---|---|---|---|
| R42 | 复用 get_factor_matrix 全池 z | 1586/1628/1675/1775、allocation 401-405/623 | 否 | 是（全池真 z） | design/strategy_check 两屏 | reason 标注 | 复用矩阵，无新 IO | 量纲/群体混用 |
| R43 | — | 818-833、worker:138 | 否 | 是（真 LLM 报告） | strategy_check 链路 | 进度心跳 | 改超时值 | 超时过短 |
| R44 | — | main.py warmup、china_market:1391、config:23 | 否 | 是（Session 复用真省时） | warmup 链路 | — | 减 IO（Session 复用） | 预热回归 |
| R45 | — | 952-992、cache_service:105、Watchlist 127-153 | 否 | 是（Redis last-good） | watchlist 链路 | 维护中标注 | 缓存复用 | 兜底链断裂 |
| R46 | 探针已通过（新浪行业 49 行） | 1658/1363、market_trends:68 | 是（盘后） | 是（日频真源） | 设计强板块注入 | as_of 标注 | 复用快照 | 首启空窗 |
| R47 | — | strategy_design、DesignResult | 否 | 是（桶化非兜底） | 设计响应/前端 | bucket vs exact | 纯展示 | 元数据矛盾 |
| R48 | — | 746/1490/1512、strategy_design:408 | 否 | 是（真合并留一） | risk 控制层 | 已合并标注 | 无新 IO | 仅告警不收敛 |
| R49 | — | analysis:_sse_stream、llm.py | 否 | 是（真进度） | SSE 链路 | 进度条 | 无新 IO | 首字节慢 |
| R50 | — | logs/ | 否 | — | — | — | 磁盘清理 | 残留 |
| R51 | — | vite.config、index.html、PortfolioAnalysis | 否 | 是（critical CSS） | 首屏链路 | loading 态 | 内联 CSS | 未达标 |
| R52 | — | signal.py:34/40-45/85、portfolio_service:1556-1558/1571-1574/1022-1030 | 否 | 是（真分项覆盖率） | composite_decision 链路 | degraded 徽标 | 纯计算，无新 IO | 门禁口径错 + 权重稀释 |
| R53 | 探针已通过（新浪 .INX 5693 行） | market_service:1233-1246/141-163/269/361、china_market:1465、market.py:503 | 是（盘后） | 是（新浪真源） | index realtime/K线链路 | 诚实降级保留 | 复用新浪 stock_us_daily | 过防护 + 符号错位 |
| R54 | — | sync_indices_meta:153-209、market_service:600-626、market.py:227 | 否 | 是（删 ETF/补基座） | 指数搜索/个股ETF搜索 | 类型正确标注 | 纯数据修复 | 种子表污染 |
| R55 | 探针已通过（K线 240 天，差 250 门槛 10 天） | ic_tracker:193/278/302/352、main.py:442、factors.py:35/99-138 | 否 | 是（历史真 IC） | _ic_persistence_loop/回填任务 | 诚实积累中 | 一次性批量计算 | 增量无回填 |

- **Round 5（R52 新增，用户 review 驱动，本次完成）**：用户提问「组合持仓所有综合信号都是持有，这合理吗？」触发。经 code 复核确认两层根因：①`composite_signal`（`signal.py:34`）权重 0.4/0.4/0.2，周末估值/动量恒 0 → `0.4×技术∈[-0.4,+0.4]` 永不够 ±0.5 阈值；②`_attach_composite_decisions:1556-1558` 的 valid_rate=「持仓级填充率」13/13=100%（`_has_real_factor_values` 把技术类因子算 filled）而非「分项覆盖率」→ 门禁不降级、标 `degraded=false`。实测 13/13 持仓 signal 全 hold、components valuation/momentum 全 0。已补 §0.3 P1-6、§2.8、§15.1 R52、§16 批2。修复采纳「分项覆盖率门禁 + 权重归一 + 诚实降级」，验收含负向断言「三面齐全仍恒 hold → FAIL」。file:line 经 grep 确认：`_COMPOSITE_FACTOR_MAP:1533-1537`、`filled_factor_count:1022-1025`、`_attach_composite_decisions:1540`、`composite_signal_with_gate:58`、`composite_signal:14` 全部准确。

- **Round 6（R53/R54 新增，用户 review 驱动，本次完成）**：用户两次追问触发——①美股指数 tab 选「标普500」返回 `unsupported_market: US`；②美股个股/ETF 搜 SOX 无补全、指数搜索却冒出 ETF。经 code 复核确认：R53 根因=`get_asset_realtime`（`market_service.py:1233-1246`）对 `asset_type=index` 的 US/HK 分支 round16 P0-22④ 过防护「暂不支持」，但 `_GLOBAL_INDEX_DEFS`（`:141-163`）已含 ^GSPC/^IXIC/^DJI/^HSI 且 `get_global_indices`（`:269`）真实拉取，外加 SPX↔^GSPC 符号错位；R54 根因=`_STATIC_EXTRA_INDICES`（`sync_indices_meta.py:153-209`）美股段混入 SPY/SOXX/XLB 三条 ETF（`:192/:200/:204`）+ ^GSPC/^DJI/^IXIC 三条重复（`:201-203`），而 SOXX/XLB 不在 `HKUS_ETF_MAP`（`market_service.py:600-626`）→ 双向错位。已补 §0.3 P1-7（R53）/P2-13（R54）、§2.9/§2.10、§15.1 R53/R54、§16 批2/批3。R53 含 D1 探针前置（^GSPC 历史 K 线可得性），R54 纯数据修复无外部依赖。file:line 经 grep 确认：`_GLOBAL_INDEX_DEFS:141`、`get_global_indices:269`、`_foreign:361`、`get_asset_realtime index 分支:1233`、`HKUS_ETF_MAP:600`、`_STATIC_EXTRA_INDICES:153` 全部准确。

- **Round 7（R55 新增 + R53 细化，用户 review 驱动，本次完成）**：用户提问「很多因子没有数据，能不能修复？」+「美股缺失的技术指标/K线/基本面，数据源里有吗？」触发。R55 经实证（生产库 `factor_ic_records` distinct trade_date=3）确认：IC 显著性需 `sample_count≥250` 交易日（`MIN_TRADING_DAYS=250`，`factors.py:35`），但 IC 由 `_ic_persistence_loop`（`main.py:442`）增量计算、`save_ic_batch_to_db` 用 `_beijing_today()` 打当天日期（`ic_tracker.py:302`）、无历史回填 → 27 因子恒 no_data。修复=「IC 历史回填」（复用 K 线缓存逐历史交易日算截面 IC 落库）。R53 细化：`fetch_index_history`（`china_market.py:1465`）只处理 HK（腾讯）/A（akshare），US 指数被误路由；美股个股数据源全接通，美股指数实时价有源（`fetch_sina_global_index`）、指数 PE/PB 真无源。

- **Round 8（D1 探针执行 + 用户决策落地，本次完成）**：用户对三个产品决策拍板（①美股指数分析「需要接」；②IC 回填「要做，接受等自然积累」；③近替代品「进攻型也合并留一，追求集中=重仓单只而非同族分散」），并同意跑三个 D1 探针。探针结果：
  1. **R55 探针（K线深度）**：A 股 ETF `fetch_history("510300")` = **240 交易日**（2025-08-19~2026-08-14，Sina 源）——差 250 门槛 10 天 → 回填后 ~239 IC 样本，先到「可观察」再自然积累 ~11 交易日到「有效」（与用户「接受等自然积累」决策一致）；如需立即「有效」可选更深源（BaoStock/TickFlow）增强。
  2. **R53 探针（^GSPC K线）**：新浪 `ak.stock_us_daily('.INX')` = **5693 行**（2004-01-02~2026-08-14）——美股指数 K 线**数据源有**，只是符号错位（代码传 ^GSPC，新浪要 `.INX`）；alphavantage 免费层对 SPX 返 0 不可用。修复=符号映射 ^GSPC→.INX 复用新浪 stock_us_daily。
  3. **R46 探针（akshare 板块）**：东财 `stock_board_industry_name_em` **阻断**（ProxyError），但**新浪 `stock_sector_spot(新浪行业)` 可用**（49 行含涨跌幅）→ R46 兜底源改新浪行业 spot（板块名与 `SECTOR_ETF_MAP` 匹配度实施时验证）。
  已据此更新 §15.1 R46/R53/R55 探针标注（前置→已通过）+ R48 三型合并，并修正 R55 验收口径（回填后「可观察」而非立即「有效」）。

> **当前状态（Round 1-8 完成）**：R42-R55 均达实施标准（精确 file:line + 修复片段 + 验收 + 测试断言）；R42 由「多选项」升级为「方案(a) 决定」；R43/R48 file:line 经核查修正；R46/R53/R55 三个 D1 探针**已执行并有明确结论**（新浪行业 spot 可用 / 新浪 .INX 5693 行 / K线 240 天）；R48 采纳用户决策「三型均合并留一」；R52/R53/R54/R55 为用户 review 驱动新增。本文档**不写任何修复代码**，等待「开始实施」指令。
