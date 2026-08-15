# round24 系统复验审计与修复方案（2026-08-14）

> 本文档为对 round23 修复落地后的**全链路复验**（Docker 重建 + 15 项审计动作）的结论与剩余问题修复设计。
> **本文档仅设计修复方案，不实施。** 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」「API 契约先于实现」撰写。
> 验证环境：Docker Desktop Engine 29.7.2，prod profile 构建启动，后端 :8000 / 前端(nginx) :80；后端镜像 `af77d81e8501`、前端 `0393067a7530`。

---

## 0. 执行摘要

### 0.1 本轮性质：复验而非首轮审计
round23（`docs/round23-system-audit-optimization.md`）是「设计不实施」审计文档，其 P0 正确性项已于 2026-08-14 通过提交 `e9e4f5c`、`4dc763c`、`6e6f2be`、`2c9c27e`、`11c04c7` 落地。本轮用**全新 Docker 镜像 + 全 15 项动作**复验：**round23 的 P0/P1/P2 修复绝大多数已生效并实证通过**（§7），同时发现 **1 处新回归风险 + 若干残留/新问题**（§0.2）。

### 0.2 验证动作与结果基线
| 动作 | 结果 |
|---|---|
| Docker 构建前后端 + 回收老镜像 | ✅ 新镜像 backend `af77d81e8501` / frontend `0393067a7530`，老镜像已回收 |
| 预热性能诊断（PROFILE_WARMUP=1） | ⚠️ 预热 19.4s，`warmup_market_cache` 13.5s 仍主导（**F1/F2/F3 未实施**） |
| `verify_e2e.py` 两次 | 269/283、269/283 通过，各 **14 项失败**（归类见 §0.3） |
| 组合设计（design 570, range_bound） | ✅ `report_quality=full`，3 方案 + 真实涨跌 + 诚实降级横幅；⚠️ 因子分极端、强板块未进池 |
| 场内策略检查（strategy-check 491, on_exchange） | ✅ **真实 LLM 报告**（8/10 `source=llm`）、KDJ 超买已修正、confidence 已真实化；⚠️ 2 条规则兜底仍 confidence=0.7 |
| A/HK/US 行情分析（§3） | ✅ 综合研判/AI投顾/个股/ETF/板块/概念/指数/搜索自动补全**全部真实可用**（含中文体），但 LLM 流慢（27–89s） |
| 热点/自选/持仓（§4） | ✅ 热点板块个股加载成功；自选添加+实时显示成功；⚠️ 美股自选无实时（F21） |
| 资讯分级 + 因子模型（§5） | ✅ 资讯分类/时区/AI 摘要生效；因子页诚实化（0 有效/38 实现/155 规划）；⚠️ 宏观 tab 混非宏观、global 分类 7/8「other」 |
| 前后端断裂（§6） | ✅ `check_routes` 全 OK；字段级抽查无断裂 |
| round23 落地核验（§7） | ✅ **P0 正确性 12 项 + 架构 6 项全部落地**；E1 架构债 + F1/F2/F3/F21/F13 等残留 |
| 前端 Lighthouse（§8） | ✅ home CLS 已修（0.389→0.0007）；⚠️ `/news` CLS **0.2077**（新问题）、root perf 69、FCP 2.0s |
| 后端链路计时（§9） | ✅ 热态全 <220ms；⚠️ **冷态** sectors/heat 5.0s、stock-hot-rank 3.8s、factor-health 3.1s、etfs 1.9s、timeline 1.8s |
| 冗余代码（§11） | 死端点 4、死函数 3、重复 import、陈旧测试 mock、临时残留文件（subagent 复核） |

### 0.3 verify_e2e 14 项失败归类（复验实测）
| 类别 | 失败项 | 性质 |
|---|---|---|
| 数据源熔断（环境） | ETF 记录数=1、成交额/规模/价格 ETF=0、候选池=0、候选池健康=None、etf_specific no_data=10、sentiment no_data=1 | 数据源 cooldown + 因子源缺数据 |
| 测试守护误报（本轮实证） | **方案数 >= 3 — 实际 0** | **verify_e2e 读错字段**（§10 缺口6），静态兜底池实际已产出 3 方案 |
| LLM 延迟 | `llm-report/stream` 10s 超时、sector-analysis 流含 CJK | 前者=冒烟超时过短；后者=**测试守护自身误报（§10 T5）** |
| 性能 | `timeline` 1.7s > 1.0s 门禁 | **冷态路径超门禁（T9）** |
| 引擎约束 | M7 balanced 核心单只权重 ≥5% — 159338 仅 1% | 因子分极端驱动（§2） |

### 0.4 问题分级（剩余 + 新发现，危害驱动）
- **P0（投资判断/数据可信度）**
  1. **候选池脆弱 → 强板块未进池 + 静态兜底未显式标注**：数据源熔断时候选池=0，但**静态兜底池已落地**（`strategy_design.py:169-222`）能产 3 套方案（verify_e2e「方案=0」是其读错字段的假失败，§10 缺口6）；真正缺口是**强板块动量未注入候选池**（R1），且静态兜底未在 UI 显著标注（R3）。
  2. **强制锚被关联度削减击穿 ≥5% 地板**：design 570 balanced 中 `159338 中证A500`(强制锚) 仅配 1%，违反 M7。根因是 `enforce_max_correlation`（`allocation_engine.py:1374`）削减高相关对时**未检查 `MANDATORY_CODES` 豁免**，击穿 allocate 内已存在的 ≥5% 地板（R2）；因子分极端（-0.96）只是触发削减的「低分方」判据，非直接淘汰。
  3. **「诚实降级」与「精确呈现」仍矛盾**：`factor_data_quality.valid_rate=0.0%` + 「方案仅供参考」横幅，但 UI/权重仍是精确的 5%/15%/21% 与精确因子分。专业投资者无法据此分辨「哪个数字可信」。
- **P1（正确性/一致性）**
  4. **规则兜底路径 confidence 表示法与 LLM 不一致**（F11 半落地）：strategy-check 491 的 159992/513010 两条规则建议 `confidence=0.7`（`source=rule`），与 LLM 条目的 high/medium 语义标签混排。规则路径实为 round18 P2-7 的 2 档数值分级（填充率 <70%→0.5、≥70%→0.7），**非硬编码**，但「数值 0.5/0.7」与「high/medium 标签」在同一屏两种表示法，且 0.7 对应「medium」语义（填充率 ≥70% 只算中等）易误读为「高置信」。
  5. **策略检查无结构化兜底标识**（T3 半落地）：`strategy-checks/{id}` 记录无 `llm_layer_ok`/`report_quality` 字段，兜底只能靠逐条 `source=rule` 或 summary 文本「已用规则引擎兜底」识读。
  6. **`/news` CLS 0.2077（新）**：资讯页布局偏移超 0.1 阈值 2 倍，F35 只修了 home 未修 news。
  7. **美股自选无实时（F21 未实施）**：watchlist 中 QQQ/AAPL/SPY `realtime.price=null`，前端无降级说明，用户误以为「没波动」。
  8. **冷态性能超标（T9 未实施）**：sectors/heat 5.0s、stock-hot-rank 3.8s、indices/global 3.7s、factor-health 3.1s、etfs 1.9s、timeline 1.8s（热态全 <220ms）。
  9. **关联度/冗余控制缺口（R24，Round 4 新增）**：design 570 实证——防御方案三重持有大盘宽基未告警（与 balanced/aggressive 口径不一致）、主题级「同主题不同发行商」冗余全方案未抓（半导体/港股药/券商 A/H）、盘后 0% 有效因子下关联度对无价格标的静默跳过且削减依赖失效因子分（A500→1% 违反 R2）。见 §12.1 R24。
  10. **信号口径三面不一致 + 综合信号降级门禁（R25，Round 5 新增）**：持仓技术面板纯技术（caption 明示排除因子/基本面）；策略检查 + 标的分析已把因子+基本面作展示列+LLM 叙述纳入，但未聚合进结构化决策信号；calm 市下 reason 只显 MACD/MA（RSI/KDJ 仅极端区 emit）与 caption 矛盾；若合成信号纳入因子会复现 R3 假精确。见 §12.1 R25。
  11. **盘后数据变薄（R26，Round 6 新增）**：降级被动推断 + 内存 last-good 重启即丢 + T-1 真实数据不持久化 → 盘后 valid_rate=0%/correlation 空/sector_momentum=[]/fund_flow=0。先例 `sentiment_cache.json` 落盘恢复已验证。见 §12.1 R26。
- **P2（治理/清理）**
  9. 冗余/死代码（§11）：死端点 4、死函数 3、重复 import、陈旧测试 mock、临时残留文件。
  10. 资讯 tab 内容质量：macro 混「ETF日报」非宏观、global 7/8「other」（英文标题无中文分类器覆盖）、ai_summary 仅 headlines。
  11. root perf 69（FCP 2.0s）、portfolio-analysis a11y=82。
  12. 测试守护 T5 CJK 检测误报（§10）——真实中文流被误标「空壳」。

> **本轮方法论结论（第三次实证）**：①「测试绿」不足以证明「功能对」——T5 的 CJK 守护对**真实中文流误报失败**，而它本应拦截「空壳」；②「热态计时」系统性掩盖冷启动——本轮 15 个端点热态全 <220ms、冷态 5 个 >1.8s，而 verify_e2e 默认测热态。**结论：任何「性能/内容正确」结论必须标注冷/热态与编码方式。**

### 0.5 产品/owner 决策记录（实施前已采纳，避免实施漂移）
| 项 | 决策 | 影响 |
|---|---|---|
| R2 因子分口径 | **宽基因子分仅影响排序、不影响淘汰**（采纳推荐①）；核心层单只下界仍用 `MANDATORY_CODES ≥5%` 地板，且受层预算闭包约束（Σ核心下界 ≤ core_budget≈0.40，核心数 >7 下界让位） | 实施 R2 时**不得**把宽基改成「完全免疫因子分/近似等权」，因子信号在核心层保留排序作用 |
| R18 DELETE design/config 端点 | **已定**：`DELETE /portfolio/designs/{id}` → **直接删**（端点+契约+handler `delete_design` portfolio.py:357，已确证 0 调用者）；`DELETE /admin/config/{key}` → **保留端点 + 在 `ConfigView` 补「重置为 .env」按钮**（闭环 override 生命周期，否则 PUT 覆盖后无撤销路径）。`GET/PUT /admin/config` 已被 `ConfigView.vue` 调用，DELETE 是半成品补全而非死代码 | 实施 R18：designs 端点整链删；config 端点保留 + 补前端重置按钮（handler `delete_override` config_manager.py:114 仅此一处调用，保留） |
| R1 强板块注入 / R3 区间降级 / R20 复用 US 源 / R6-R7 性能 | 采纳推荐（强板块 TopN 强制进评分 + 静态兜底显式标注；降级态权重「等权/粗略」+ 红字缺失 N% + 因子分区间；美股复用 F39 源 + 静默 null 作 fallback） | 直接进实施清单 |

---

## 1. 后端预热性能诊断（PROFILE_WARMUP=1）

**产物**：`logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.html/txt`（本轮重跑）。

**实测（warmup_timing.json）**：
| 阶段 | 耗时 | 占比 |
|---|---|---|
| init_db | 54.7ms | 0.3% |
| redis_init | 96.6ms | 0.5% |
| warmup_global_indices | 5764ms | 30% |
| **warmup_market_cache** | **13505ms** | **69%** |
| warmup_etf_cache | 23ms | 0.1% |
| 合计 | ~19.4s | — |

**cProfile 根因（与 round23 §1.1 一致，F1/F2/F3 未实施故未改善）**：
- `requests.get`（40 次，14.5s 累计）——**仍无 `requests.Session` 复用**，SSL `do_handshake` 累计 4.2s。
- `fetch_fund_nav`（`china_market.py:1391`，10 次，5.8s）——akshare `fund_open_fund_info_em` NAV 历史拉取。
- **新增突出项（round23 未单列）**：`fetch_macro_snapshot`（`macro_fetcher.py:353`，5.3s）+ `fetch_pmi_gdp`（`macro_fetcher.py:249`，5.3s）——宏观数据（PMI/GDP）拉取占预热 ~10.6s，是除 NAV 外的第二热源。
- `refresh_news` / `fetch_global_news`（4.95s）、`fetch_sina_page_global_index`（3.38s）。
- `safe_call`（`async_utils.py:74`）仍存在（D1 deprecated 别名保留，非本轮新增开销）。

**修复设计（不实施）**——沿用 round23 F1/F2/F3，补充宏观项：
- **F1**：数据层改 `requests.Session` + `HTTPAdapter(pool_connections/pool_maxsize)` + 重试，消除重复 SSL 握手（预期削 30–50% 握手）。
- **F2**：`warmup_market_cache` 内 NAV + 宏观拉取改 `asyncio.gather` + 限并发信号量；确认 `main.py:201` 的 10s 超时真正穿透。
- **F3**：预热降精度（NAV 近 60 日、宏观仅 PMI/GDP 摘要）。
- **F3b（新增）**：宏观源（`macro_fetcher`）预热可延迟/后台化——其 10.6s 非首屏关键路径，可移出同步预热。
- **验收**：`warmup_market_cache` ≤ 8s、总预热 ≤ 15s、SSL 累计 ≤1.5s。

---

## 2. 组合设计 + 场内策略检查复验（专业投资者视角）

### 2.1 组合设计 570（range_bound / report_quality=full）
**结构工程良好（round22 引擎约束 E1–E5 已落地）**：3 方案（防御/平衡/进攻）、层预算（核心/卫星/防御/现金）、10/10/12 只、真实今日涨跌（如 515880 +3.60%、159570 -2.51%、513120 -2.57%）、`factor_data_quality` 诚实降级（`valid_rate=0.0%` + 「方案仅供参考」）。

**数据可信度硬伤（核心）**：
- **因子分极端且驱动错误权重**：510300 因子分 **-0.99**、159338 **-0.96**（两个最核心宽基反而最深负分），直接导致平衡方案 159338 仅 **1%**（M7「核心单只 ≥5%」失败）、510300 在防御方案仅 5%。宽基被因子分系统性压低到接近剔除线，是**口径问题**（因子分与「宽基底仓」角色冲突）。
- **`strong_sector_pool_coverage=[]`、`sector_momentum=[]`**：强势板块完全未进候选池（F13），方案与市场热点脱节。
- **`fund_flow` 全 0**（total_symbols:0）——资金流源熔断未显式标注。
- **预期年化 8%/11%/16% 为静态基线**（报告自注「震荡市态调整系数为 0」），非数据驱动。
- **「仅供参考」与「精确呈现」矛盾**：valid_rate 0% 时仍给出精确权重与精确因子分，专业投资者无法判断可信边界。

**专业判断**：框架可用、结构专业（相关度告警、层预算、真实涨跌都在），但**数据基础不足以支撑精确配置**。结论同 round23 §2.1，但「诚实降级」已从「缺失」变为「横幅 + 精确数字并存」——降级诚实了，数字没诚实。

> **验证窗口标注（D3）**：本轮审计执行于 2026-08-14 19:00–19:45（北京，**盘后窗口**）。`strong_sector_pool_coverage=[]`、`sector_momentum=[]`、`fund_flow 全 0`、`候选池=0` 均含数据源熔断/盘后成分，**属「待交易时段（9:30-11:30/13:00-15:00）复测」项，不得单独作为「强板块未进池」的定论依据**。但「强板块未注入候选池」是**代码级结构事实**（`strong_sector_pool_coverage` 字段恒由空 sector_momentum 驱动），R1 的修复方向不受窗口影响。

### 2.2 场内策略检查 491（on_exchange）—— 从「失败」到「合格但有残留」
- **✅ LLM 报告已真实**：summary 为 LLM 撰写（「当前市场处于震荡格局…增持港股创新药、游戏及黄金ETF，减持券商与港股红利低波」），8/10 建议 `source=llm`，含具体止损/加仓条件（「若跌破 120 日线或 RSI<40 则减仓」）。
- **✅ KDJ 超买修正（F10）**：159338 KDJ.J=75.73 → `hold`；159516 曾 J=98.7 → 现 `hold`（RSI 41.46 偏弱）。超买→BUY 已消除。
- **✅ confidence 真实化（F11 LLM 路径）**：high/medium（非硬编码 0.7）。
- **✅ 风险提示专业**：集中度（中证A500 20% 偏高）、波动、折溢价流动性、因子与价格背离（drift）四类，`affected_symbols` 精准。
- **⚠️ 残留 1**：2/10 条规则兜底建议（159992、513010）`confidence=0.7`（`source=rule`），与 LLM 条目 high/medium 混排。规则路径已是 round18 P2-7 的 2 档数值分级（`portfolio_service.py:1509-1511`：填充率 <70%→0.5、≥70%→0.7），非硬编码——但**同屏两种置信度表示法（数值 0.7 vs 标签 high）语义不统一**，且 0.7 实为「中等」却易读作「高置信」。
- **⚠️ 残留 2**：`strategy-checks/{id}` 记录**无 `llm_layer_ok`/`report_quality`/`coverage` 字段**——兜底只能靠逐条 `source` 或 summary 文本识读（T3 半落地）。
- **⚠️ 残留 3**：建议 reason 引用原始因子值（「政策规划因子+8.97」「战略新兴+8.14」），量纲不统一、投资者无法解读。

**专业判断**：**可作为投顾建议的骨架，但需补「兜底显式标识 + 规则置信度真实化 + 因子值可读化」**。

---

## 3. A/HK/US 行情分析全能力复验（步骤3）

**实证来源**：容器内 Python `urllib` 显式 UTF-8（避免 shell-curl 编码误报，round23 教训）。

| 能力 | 实测 | 结论 |
|---|---|---|
| 搜索自动补全 A | `keyword=银` → 10 只（银轮/银河磁体…）；`茅台` → 贵州茅台 | ✅ |
| 搜索自动补全 HK | `腾讯`+`include_stocks=true` → 腾讯控股；`00700` → 腾讯控股 | ✅（需 `include_stocks`，前端已传） |
| 搜索自动补全 US | `apple`/`AAPL` → 苹果 | ✅（同上） |
| 综合研判 `llm-advice/stream` 中文 | 「当前市场怎么看？」→ 200/19s/741 中文字符，含真实指数（上证 3927.18、创业板 +1.12%、恒生 -1.10%） | ✅ 真实非模板 |
| 个股 `symbol-analysis/stream` | 600519 → 200/27s/「贵州茅台…」 | ✅ |
| 板块 `sector-analysis/stream` | BK0735 → 200/89s/「一、板块…」 | ✅（但 89s 极慢） |
| 概念分析 `sectors/concept` | CPO概念 +3.18% 主力净流入 114.9 亿、领涨天洋新材 | ✅ |
| 指数 `indices/global` | 首呼 3693ms / 二呼 22ms（sina 冷拉取） | ✅（数据源冷却时 0 条） |
| ETF 实时 `realtime/510880` | price 3.296 / +0.7% | ✅ |

**专业判断**：**能力全覆盖、内容真实**，AI 研判引用了真实指数与板块数据，非模板话术。**唯一实质问题是延迟**：symbol-analysis 27s、sector-analysis 89s（deepseek 流式生成，无降级提示、无进度心跳之外的可视化）。§9 冷态性能问题同源。

---

## 4. 热点 / 自选 / 持仓技术分析（步骤4-6）

- **热点（步骤4）**：`hot-plates` 13 条（光通信 +2.88%，领涨蓝盾光电「5天5板」真实）、`sectors/heat` 20 条（电子 heat 565616 真实）、`stock-hot-rank` 50 条（太极实业 -3.49% 真实）——**全部加载成功且数值真实**。
- **自选（步骤5）**：`POST /market/watchlist {"symbol":"510500"}` → 201 落库，GET 立即带实时（7.998 / +0.23%）。**添加+获取+显示链路正常**。⚠️ 实时覆盖 18/21：**QQQ/AAPL/SPY（美股）`realtime.price=null`**（F21 未实施，无降级说明）。
- **持仓技术分析（步骤6）**：`/market/signal/{159338,159516,518880}` 均返回 `signal=hold`（159338 KDJ.J=75.73、159516 原 J=98.7 现 hold）——**F10 超买修正已生效**。strategy-check 的 `holdings_analysis` 含 KDJ/RSI/MACD 因子摘要与 `factor_availability 32/39`、`tech_signal=HOLD/SELL 真实信号`——指标与信号自洽、与最新行情匹配。

---

## 5. 资讯分级 + 因子模型（步骤7-8）

### 5.1 资讯（步骤7）
- **分类/级别（F22/F23）**：headlines 15 条 `category {other:8, positive:6, negative:1}`、`level {2:8, 5:6, 4:1}`；global 8 条含 `risk:1`（「Treasury yields rise as U.S. threatens…」→ risk/level4，**利空不再标红为利好**）。分类着色正确（risk→橙、positive→红、negative→绿）。
- **时区（F24）**：`time=2026-08-14 18:58:53`（北京时间），与东财个股新闻同口径。
- **AI 摘要（F28）**：headlines 5/15 有 ai_summary（单轮上限 5 生效），重要性驱动。
- **⚠️ 残留**：① macro tab 4 条含「ETF日报：产业趋势没有变…」非宏观内容（宏观过滤 `_is_macro_relevant` 偏松）；② global 8 条中 7 条 category=「other」（英文标题无中文关键词分类器覆盖）；③ ai_summary 仅覆盖 headlines 桶，macro/global 恒 0；④ 高负载下 headlines/macro/global 曾瞬态返 0（`_news_bucket` 懒刷新与后台任务刷新竞争，见 §9）。

### 5.2 因子模型页（步骤8）
- **诚实化已落地（F25/F26/F27/F32/F33）**：`/factors/active` summary `{valid:0, no_data:27, static:11, avg_ic:0.2134, min_samples:250, observable_days:60, significant:0, observable:0}`；`zero_ratio` **非空**（style.size.ln_mcap 等 0.0）；`/factors/model` `implemented=38 / planned=155`（不再虚报 193）。
- **专业判断**：页面现在诚实呈现「0 个因子统计显著（18 天 < 250 交易日门槛）、38 实现/155 规划、无数据 27」——**这是对的**。但 `avg_ic 0.2134`（/active）与 `0.3221`（/model）同屏两值不一致（两处聚合范围不同），建议统一口径（§12 R22）。

---

## 6. 前后端数据断裂排查（步骤9）

- **`check_routes.py`**：全路由契约双向比对 **全部 [OK]**，无断裂。
- **字段级抽查**：`portfolio/etfs`（symbol/name/price/change_pct/target_weight 等 16 字段齐）、`sectors/concept`（前端用 `sector_name`，后端返回 `sector_name` ✓）、`sentiment`（`limit_up_seal_rate` 与 `up_ratio` 双字段兼容返回，F20 无断裂）、`indices/global`、`watchlist` 均对齐。
- **结论**：**无前后端数据断裂**。round23 §3.2b 的 C1/C2/C4 三处断裂已修复（§7）。

---

## 7. round23 方案落地核验（步骤10）

| round23 项 | 状态 | 复验证据（本轮实测/代码） |
|---|---|---|
| F7/F8/F9/F9b LLM 熔断 | ✅ 已实施 | `llm.py:55-121` 模块级 `_circuit` CLOSED/OPEN/HALF_OPEN；strategy-check 491 走 deepseek 成功 |
| F10 KDJ 超买→hold | ✅ 已实施 | `signal.py:105-111`；实测 159338/159516 `signal=hold` |
| F15 孤立 avg_cost | ✅ 已实施 | `database.py:123-128` 清洗 + `portfolio_service.py:211` 拦截 |
| F20 up_ratio→limit_up_seal_rate | ✅ 已实施 | `levistock_fetcher.py:252-259`；sentiment 双字段返回 |
| F22/F23 资讯 category+level | ✅ 已实施 | `levistock_fetcher.py:131-162`；`newsLevel.js` category 着色、risk→橙 |
| F24 新闻时区北京 | ✅ 已实施 | `news_fetcher.py:18` `_SHA_TZ`；实测 time=北京时间 |
| F25 IC 日频管线 | ✅ 已实施 | `ic_tracker.py:279-358` 日频 1 行 + t≥2/IR≥0.5；实测 valid=0（诚实） |
| F26 avg_ic 绝对值均值 | ✅ 已实施 | `factors.py:230/416/448` `sum(abs(v))/len`；实测 0.2134 |
| F27 zero_ratio 取对对象 | ✅ 已实施 | `factors.py:470` 读 `_ic_tracker._zero_ratio`；实测非空 |
| F28 AI 摘要 int 判定 | ✅ 已实施 | `market_data_hub.py:1699-1701`；实测 headlines 5 条摘要 |
| F29/F31 资讯五 tab + 冷启动 partial | ✅ 已实施 | `news.py` 五端点 + `X-News-Partial` 头；`news_fetcher.py:302` 不再混 macro |
| F32 min_samples 契约 | ✅ 已实施 | `factors.py:238/461` 补 min_samples/observable_days/significant/observable |
| F33 implemented/planned | ✅ 已实施 | `/factors/model` implemented=38/planned=155 |
| F34 timeline TTL | ✅ 已实施（冷态仍慢） | `portfolio.py:553-660`；实测热 6ms / 冷 1826ms |
| F35 home CLS | ✅ 已实施 | GlobalIndicesStrip 骨架高度对齐；实测 home CLS 0.389→**0.0007** |
| F36/F39 HK/US K线 | ✅ 已实施 | E2E 跨市场搜索/历史 K 线通过 |
| F37/F38 相关度约束/低相关措辞 | ✅ 已实施 | design 570 相关度告警 + 确定性措辞 |
| F40 评分注释一致 | ✅ 已实施 | design 570 因子分注释与实际一致 |
| §10 架构 A1/A2/B1/C1/D1/E2 | ✅ 已实施 | `core/factor_aggregate.py`、`core/regime.py`、`core/source_registry.py`、`check_engine_purity.py`（pre-commit 第 14 段）、`design_quality.py` 已删 |
| §10 E1 portfolio_service 拆分 | 🔲 未实施（已知架构债） | `portfolio_service.py` 仍 2448 行（§11 保留） |
| F1/F2/F3 预热性能 | 🔲 未实施 | 预热仍 19.4s（§1） |
| F13 候选池兜底+强板块入池 | 🔲 未实施 | 候选池=0→方案=0；`strong_sector_pool_coverage=[]`（§2.1） |
| F21 港美自选无实时 | 🔲 未实施 | 实测 QQQ/AAPL/SPY realtime=null（§4） |
| F11 confidence 真实化 | ⚠️ 半落地 | LLM 路径 high/medium；规则路径仍 0.7（§2.2） |
| T3 llm_layer_ok 兜底标识 | ⚠️ 半落地 | design 有 report_quality；strategy-check 记录无 llm_layer_ok（§2.2） |
| T5 三端点冒烟 | ⚠️ 落地但有误报 | sector-analysis CJK 检测对 JSON 转义中文误报（§10） |

**核验结论**：round23 的 P0 正确性 12 项（F7-F28）与架构 6 项（A1/A2/B1/C1/D1/E2）**全部落地并实证生效**。残留项为：F1/F2/F3（预热性能）、F13（候选池）、F21（美股自选实时）、E1（架构债）、F11/T3（半落地）。**round23 §11 的 round20 映射结论维持成立。**

---

## 8. 前端 Lighthouse（步骤11）

Lighthouse 13.4.1 / Chrome headless，7 条真实路由（`/`、`/market-analysis`、`/portfolio-analysis`、`/news`、`/token-monitor`、`/source-monitor`、`/admin/config`）：

| 路由 | perf | a11y | best | seo | FCP | LCP | TBT | CLS |
|---|---|---|---|---|---|---|---|---|
| / | **69** | 96 | 96 | 91 | 2.04s | 3.13s | 1ms | **0.0007** ✓ |
| /market-analysis | 85 | 96 | 96 | 91 | 2.09s | 3.39s | 0ms | 0.0007 |
| /portfolio-analysis | 68 | **82** | 96 | 91 | 2.10s | 3.77s | 1ms | 0.0007 |
| /news | 87 | 95 | 100 | 91 | 1.49s | 1.92s | 0ms | **0.2077** ❌ |
| /token-monitor | 89 | 92 | 96 | 91 | 2.01s | 3.19s | 0ms | 0.0007 |
| /source-monitor | 86 | 96 | 96 | 91 | 2.02s | 3.73s | 0ms | 0.0007 |
| /admin/config | 99 | 96 | 100 | 91 | 1.50s | 1.94s | 0ms | 0.0007 |

**结论**：
- ✅ **F35 已修**：home CLS 0.389 → 0.0007。
- ❌ **新问题 `/news` CLS=0.2077**（>0.1 阈值 2 倍）——资讯页布局偏移，F35 未覆盖 news 页。
- ⚠️ **root perf 69（<90 目标）**：FCP 2.0s、LCP 3.13s。首屏主 JS 阻塞（render-blocking）仍存，F4/F5（懒加载/manualChunks）未实施。
- ⚠️ **portfolio-analysis a11y=82**（对比度不足，<85）。

---

## 9. 后端链路性能（步骤12，冷/热态区分）

| 端点 | 冷态 | 热态 | 判定 |
|---|---|---|---|
| /health | 46ms | 21ms | ✅ |
| /sectors/heat | **5014ms** | 5ms | ❌ 冷态 |
| /stock-hot-rank | **3817ms** | 220ms | ❌ 冷态 |
| /indices/global | **3693ms** | 22ms | ❌ 冷态 |
| /admin/factor-health | **3142ms** | 8ms | ❌ 冷态（>2s） |
| /portfolio/etfs | **1872ms** | 34ms | ⚠️ 冷态逼近 |
| /portfolio/timeline | **1826ms** | 6ms | ❌ 冷态（>1.0s 门禁） |
| /portfolio/designs | 1132ms | 6ms | ⚠️ 冷态 |
| /factors/active | 11ms | 4ms | ✅ |
| /news/headlines | 6ms | 32ms | ✅ |

**结论（T9 实证）**：热态全 <220ms，冷态 6 个端点 >1.1s。根因：冷态触发实时数据懒拉取（sina 全球指数/东财板块/热榜/持仓 NAV），预热未覆盖这些路径。**verify_e2e 默认测热态 → 门禁永远绿、首用户永远慢**（round23 T9 未实施）。

---

## 10. 测试防护缺口分析（步骤13）

**为何现有测试体系未识别上述问题（含本轮 1 处新误报）**：

1. **T5 冒烟守护自身误报（本轮实证）**：`verify_e2e.py:842` 用 `any("\u4e00"<=ch<="\u9fff" for ch in line)` 检测 SSE 流「含 CJK」，但 SSE `data: {"token": "\u8d35\u5dde"}` 是 **JSON 转义**（`\uXXXX`），原始字节里没有裸中文 → 对**真实中文流**（symbol-analysis 600519「贵州茅台」、sector-analysis「一、板块」均实测有中文）误报「空壳/模板」。**一个本应拦截「空壳」的守护，反而对真实内容报错**——这是「测试绿+结论错」的反面：「测试红+功能对」。
2. **规则兜底 confidence=0.7 无测试**：F11 只测 LLM 路径 confidence 非硬编码，规则路径 `_rule_based_suggestion` 仍 0.7 无断言（T7 跨字段一致性未覆盖 confidence 字段）。
3. **T3 结构化兜底标识未落地**：strategy-check 无 `llm_layer_ok`/`report_quality`，测试无法断言「LLM 兜底必须被识别」，只能靠 summary 文本（脆弱）。
4. **冷态性能无测量（T9）**：计时默认热态，冷态 5s 的 sectors/heat 无任何门禁触发。
5. **候选池=0 软放行（T1）**：`verify_e2e` 对「候选池=0/方案=0」仍标注「数据源熔断时可能为 0」软放行——空方案被合法化通过（F13 未落地故测试未收紧）。
6. **「方案数 >= 3」检查读错字段（本轮新实证）**：`verify_e2e.py:1472-1483` 从 `GET /portfolio/designs?limit=1`（**摘要列表端点**）读 `latest.get("strategies")`，但列表端点只返回 `{id, capital, risk_profile, status, report_quality, etf_count}`，**不含 `strategies`/`plans`**（实测确认，`strategies` 仅存在于 `/designs/{id}` 详情端点）→ 该检查对**每个设计恒报「实际 0」**，是**恒假失败**。它与 T5 CJK 误报同源：**测试守护读错数据源**，制造「方案=0」假象，掩盖了静态兜底池其实已产出 3 方案的事实。

**修复设计（不实施）**：见 §12 表 T 系列。

---

## 11. 冗余/死代码（步骤14，subagent 交叉复核）

**死端点（0 生产调用，删除需同批删 `api-contracts/` 契约条目，否则 `check_routes` 双向比对 exit 1）**：
| 路由 | 位置 | 处理 |
|---|---|---|
| `GET /market/sentiment` | `market.py:468`（自注「未接入前端」） | 删路由 + 契约 + `get_market_emotion` |
| `GET /market/sectors`（统一 wrapper） | `market.py:502` | 删 wrapper + 契约（保留 industry/concept 处理器） |
| `DELETE /admin/config/{key}` | `admin.py:216` | **保留 + `ConfigView` 补「重置为 .env」按钮**（owner 决策：闭环 override 生命周期） |
| `DELETE /portfolio/designs/{id}` | `portfolio.py:356` | **直接删**（端点+契约+handler，0 调用者，owner 决策：没必要存在） |

**死函数/字段**：`apply_strategy_suggestions`（`portfolio_service.py:1901`，删路由级联）、`get_market_emotion`（`market_data_hub.py:1903`）、`llm_provider` 字段（`config.py:70`，0 读取者）。

**重复/未用 import**（`analysis.py`）：`asyncio` 重复导入、`market_data_hub` 3 次导入、`generate_market_report/advice/sector_analysis/symbol_analysis` 未用导入。

**陈旧测试 mock**（`frontend/src/**/*.spec.js` 多处）：`listDesigns`/`listStrategyChecks`/`applyStrategy`/`analysisApi` 指向已删 API（`portfolioApi` 实际为 `getDesign`/`getStrategyCheckDetail`/`getTimeline`）。

**临时残留文件**：`backend/scripts/_findings_redundant_review.md`（已并入 round23）、`backend/_check_*.py`/`_fix_*.py`/`_measure_*.py`/`apply_*.py` 等 15+ 个一次性探针、`frontend/.lh/`（7 个 Lighthouse JSON ~5MB）、`frontend/lh_root.json`。

> 注：`/admin/*`（metrics/factor-health/llm-health 等）、`/factors/model`、`/market/sectors/{industry,concept,rotation}`、`/market/realtime*`、`/news/{macro,global,stock,research}` 为**测试/ops 覆盖面，保留**（非死代码，勿误删）。`docker-compose.diag.yml` + `warmup_profiler.py` 是预热诊断承重件，保留。

---

## 12. 修复方案总表（不实施）

> 复用 round23 已实施项不再重复；下表仅列**残留 + 本轮新发现**项。

### 12.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R1 | P0 | 候选池=0（数据源熔断）+ 强板块未进池（`strong_sector_pool_coverage=[]`、`sector_momentum=[]`）。**注：静态兜底池已落地（`strategy_design.py:169-222` `_build_static_pool_strategies` + `:307` pool_empty 分支），熔断时能产出 3 套静态方案**——「方案=0」实为 verify_e2e 读错字段的假失败（§10 缺口6）。真正缺口是**强板块动量未注入候选池** | ①**强板块注入点**：在 `market_data_hub._refresh_pool` 构建 `flat`（`market_data_hub.py:506-517`）并 `enrich_tracked_indices`（`:520-525`）之后插入——读 `get_sector_momentum()` TopN（按 `change_pct`/`momentum`）→ 经「板块→代表 ETF」映射表映射其 ETF → 以 `hot_sector` 标记追加进 `flat`（带 `composite_score` 保底值防被截断挤出）；**子任务**：若无现成板块→ETF 映射，需先建 `SECTOR_ETF_MAP`（行业/概念→核心 ETF 代码），否则强板块无法落地为候选；② 候选池健康 `total_candidates` 在 `get_pool` 返回非空时自动回充——last-good 已保，补 `mode` 从 `static_pool`→`normal` 显式切换 + 报告标注「数据源已恢复」；③ 静态兜底方案 `DesignResult.vue` 加黄色「静态兜底方案·非交易时段/数据受限」徽标 + `expected_return=None` 已诚实，补「预期收益未测算」红字 | 强板块覆盖率 >0；熔断→静态兜底方案（显式标注）非 0 方案；板块→ETF 映射存在且覆盖主要行业 | `market_data_hub`(`_refresh_pool` :506-517 flat / :520-525 enrich)、`strategy_design` |
| R2 | P0 | **强制锚被关联度削减击穿 ≥5% 地板（design 570 实证 + 代码复核修正）**：balanced 方案中 `159338 中证A500` 仅配 **1%**，违反 M7「核心单只 ≥5%」。根因（代码复核修正）：`CORE_ANCHORS={"510300","159338"}`（`allocation_engine.py:235`）本享 `MANDATORY_CODES` 豁免且 allocate 内已有 ≥5% 地板后处理（`allocation_engine.py:1261-1295`）；但 `enforce_max_correlation`（`allocation_engine.py:1374`，round20 P1-1）对高相关对削减低因子分一方时**未检查 MANDATORY_CODES 豁免/地板**，把强制锚 159338 削到 1%，击穿已应用的楼板。**即「楼板已存在，被关联度控制覆盖」**，非「无地板」。注：用户已采纳「因子分仅影响排序不影响淘汰」——core 层因 `CORE_ANCHORS` 本就豁免因子淘汰，漏洞在关联度削减未继承该豁免 | ①**`enforce_max_correlation` 须继承 MANDATORY_CODES 豁免**：强制锚（沪深300/中证A500/黄金/国债）永不被削减、权重永不低于 `MANDATORY_MIN_WEIGHT`(0.03)/floor(0.05)；高相关对中一方为强制锚→改削非强制一方，双方皆强制则只标不削；②「因子分仅影响排序」不变式保留（core 层因子分不驱动淘汰，与 `_cap_core_growth_wide_basis` 核心数下限 `:784` 正交）；③验证：159338/510300 等强制锚单只 ≥5% 恒成立、M7 通过、层预算不超支、weight-不归一化不变式保持 | 强制锚单只 ≥5% 恒成立（关联度削减不击穿）；M7 通过；enforce_max_correlation 跳过 MANDATORY_CODES | `allocation_engine.py:1374`(enforce_max_correlation)、`:1261-1295`(地板后处理)、`:235`(CORE_ANCHORS)、`:784`(_cap_core_growth_wide_basis) |
| R3 | P0 | 「仅供参考」横幅 + 精确数字并存 | valid_rate<阈值时：因子分显示为区间/「N/A」、权重标注「等权/粗略」；前端卡片红字「因子数据缺失 N%」 | 降级态不再呈现精确到 1% 的权重 | `strategy_design.py`、`DesignResult.vue` |
| R4 | P1 | 规则兜底 confidence 为数值 0.5/0.7（2 档），与 LLM 的 high/medium 标签表示法不一致（F11 半落地，非硬编码） | 统一 confidence 表示法（全站语义标签 high/medium/low 或全站数值）；规则路径 0.7 语义明确为「中等」或升为 3 档 | 同屏不再两种表示法；0.7 不误读为高置信 | `portfolio_service.py:1491` |
| R5 | P1 | strategy-check 无 llm_layer_ok/report_quality（T3 半落地） | 记录 + API 补 `llm_layer_ok`/`report_quality`/`coverage` 字段；兜底时 `report_quality=fallback` 且 `llm_layer_ok=false` | 兜底可结构化识别，非仅 summary 文本 | `strategy_check_worker`、`portfolio.py` |
| R24 | P1 | **关联度/冗余控制缺口（design 570 实证 + `enforce_max_correlation` 代码复核，2026-08-14 关联度评估新增）**：控制**已存在**——`enforce_max_correlation`（`allocation_engine.py:1374`，round20 P1-1）对 r≥0.9 高相关对非 CASH 持仓做「合计权重封顶 25% + 削减低因子分方 + 其余比例回补」，矩阵缺失时置 `correlation_unchecked=True`（`strategy_design.py:414-416`）。但：①**降级盲**：盘后 `valid_rate=0.0%`（182/193 no_data）时相关系数 `r=None` → 所有对相关对静默跳过、控制变 no-op，仅内部 `correlation_unchecked` 标志（未前端化）；防御方案三重持有大盘宽基（`510300`+`159338`+`510050`≈31%）因此 `correlation_warnings=0`，与 balanced/aggressive（已报 `510300↔159338` corr 0.983）口径不一致；②**仅 pairwise 非组合级**：只约束单对相关对合计≤25%，不优化组合整体分散（3 只大盘各自 pairwise 受限仍集体冗余可过）；③**主题双发漏**：同主题不同发行商（`588170 科创半导体`+`588200 科创芯片`、`513120 港股创新药`+`159570 港股通创新药`、`512880 证券`+`513090 香港证券`）若 r<0.9 或价格缺失则不约束；④**削减依赖失效因子分且击穿强制锚地板**：降级态 `factor_score` 为垃圾值，`balanced` 把 `159338`(**强制锚**) 削到 **1%**（违反 R2 核心≥5% 地板，因 `enforce_max_correlation` 未检查 `MANDATORY_CODES`）——同一对相关对两方案削减方向相反（`aggressive` 削 `510300` 留 A500） | ①`correlation_unchecked` 须前端化（标「关联度未校验」），杜绝降级态静默 no-op；②**近替代品双路检测**（除相关系数外独立一层）：基于 `tracked_index`/行业聚类/名称语义识别「同主题不同发行商」近替代品——半导体 `588170`/`588200` 同属科创半导体簇、港股药 `513120`/`159570` 同属 HK 生物科技、券商 `512880`/`513090` A/H 券商；对相关对即便 `r` 略<0.9 或价格缺失也约束/合并（复用 `_deduplicate_by_index` 的 tracked_index 思路扩到「同指数族」），使控制不依赖 K 线相关系数（降级时不失明）；③跨方案一致触发（含 `上证50↔沪深300` 重叠，根源是降级盲修①后自然一致）；④无价格对改发 `correlation unevaluated` 告警而非 `r=None` 跳过；⑤削减决策**继承 MANDATORY_CODES 豁免且不信失效因子分**：`enforce_max_correlation` 削减前检查 `MANDATORY_CODES`——强制锚（沪深300/中证A500/黄金/国债）永不被削、永不低于 floor（**同时修 R2 击穿**）；非强制方优先削；双方强制则只标不削；降级态因子分不可信时改保留更宽基/流动性更好的非强制锚或显式标「冗余待交易时段复算」；⑥评估组合级分散约束（当前仅 pairwise 0.9 封顶 25%）：加组合平均 pairwise 相关 / 最大相关簇权重上限，防「3 只大盘各自受限仍集体冗余」 | 防御方案大盘重叠告警；主题双发被识别/合并；降级态不静默漏报；`correlation_unchecked` 前端可见；R2 核心≥5% 不被关联度削减破坏 | `backend/app/engine/allocation_engine.py:1374`（`enforce_max_correlation`）、`strategy_design.py:380`（`_correlation_medians_for`）、`strategy_design.py:414-416`（`correlation_unchecked`）、`correlation_warnings` 生成处 |
| R25 | P1 | **信号口径三面不一致 + 综合信号降级门禁（2026-08-14 信号一致性评估新增）**：①持仓技术分析 `SignalPanel` 纯技术（caption「不含因子与基本面」，`market.py:366 /signal`→`generate_signal` 仅 RSI/KDJ/MACD/MA/BOLL/TD）；②策略检查 + 标的分析**已把因子(33维 `factor_scores`)+基本面(PE/PB/规模)作为展示列+LLM 叙述纳入**（`portfolio_service.py:12-43` F11 中文映射、`:637-670 get_fundamentals`；`analysis.py:623-633/685-692` 基本面注入 LLM），但因子/基本面**未聚合进结构化 buy/sell/hold 决策信号**（结构化信号=技术+LLM）；③三面口径不一致（持仓纯技术、另两面 LLM 含因子基本面但结构化信号不含）；④Q1 误导：calm 市下 `generate_signal` reason 只 emit MACD+MA（RSI/KDJ 仅极端区才 emit，RSI 40-60 中性不发），caption 却承诺 RSI/KDJ；⑤若把因子+基本面聚合成综合信号，盘后 `valid_rate=0%` 会复现 R3 假精确 | ①**不替换**技术信号，保留纯技术卡；②新增独立「综合信号」卡/字段，复用 `composite_signal`（`signal.py:4`，0.4技术+0.4估值+0.2动量），因子缺失时**退化为纯技术或显式标「因子缺失」降级徽标**（R3 门禁）；③最优先落地**策略检查**（数据已齐），标的分析多市场不均作可选附加；④持仓技术面板中性区补 info 级 reason（如「RSI=52 中性」）或弱化 caption，消除 Q1 误导 | 三面信号口径一致（或显式区分纯技术 vs 综合）；综合信号在 `valid_rate<阈值` 时不报合成结论；策略检查决策信号与展示的因子/基本面数据一致；calm 市下 RSI/KDJ 在 reason 中可见 | `frontend/src/components/analysis/SignalPanel.vue:17`、`backend/app/routers/market.py:366`、`backend/app/services/portfolio_service.py:12-43/:637-670`、`backend/app/analysis/signal.py:4/:51`、`backend/app/routers/analysis.py:623-633/685-692` |
| R26 | P1 | **盘后数据变薄优化（快照持久化 + 显式盘后模式，2026-08-14 盘后优化评估新增）**：根因——盘后/熔断时因子源(akshare/mootdx)/实时价/板块动量/资金流全不可达，design 570 实测 `valid_rate=0.0%`(182/193 no_data)、correlation 矩阵空(`correlation_unchecked=True`)、`sector_momentum=[]`、`fund_flow=0`。当前应对三缺陷：①降级被动推断（数据空才降级），`get_market_status("A股")`(`market_calendar.py:26`) 已存在却未接入设计/分析链路；②`last-good` 池(`market_data_hub.py:485` `_last_good=dict(self._pool)`)/`_kline_cache`/`_last_ic_batch`(`factor_registry.py:776/1006`) 全内存、**重启即丢**→盘后重启=全空=静态兜底；③盘后 T-1 真实数据不持久化→白白丢。先例：`sentiment_cache.json` 落盘+失败恢复(A02, `market_data_hub.py:1545-1557`) 已验证可行 | ①显式盘后模式：设计/分析入口用 `get_market_status` 判 session，`closed`→`post_market` 走快照路径，响应带 `session=closed, as_of=T-1 15:00`；②**快照持久化（存储+触发+过期）**：新建 `data/snapshot.db`（SQLite）或复用 `portfolio.db` 加 `market_snapshot` 表，字段 `kind`(factor_matrix/pool/sector_momentum/fund_flow/kline)/`payload`(JSON)/`as_of`(上一交易日 15:00)/`written_at`；**写触发**：`_refresh_pool` 成功且 `total_new>0` 写 pool+sector+fund_flow、因子矩阵成功计算后写 factor_matrix、可加收盘定时任务兜底；**读触发**：`post_market` 下 `get_pool`/`get_factor_matrix`/`get_sector_momentum` 优先读快照（带 `as_of`），实时失败回退快照（A02 模式，复用 `market_data_hub.py:1545-1557` 的 restore 逻辑扩展到全量）；**过期**：新交易日 `is_trading_time()` 为真且已产生实时数据后快照标 stale、强制实时（避免 T-1 当实时）；③**`as_of` 贯穿响应 schema**：`market_context`/`design`/`strategy-check` 响应加 `data_as_of`+`session` 字段，前端统一渲染「数据截至 {as_of}（盘后）」红字（反 R3 假实时）；修正 `correlation_unchecked` 语义=仅连 T-1 快照 K 线都没有才置，盘后应有 T-1 K 线→关联度可算只标 `as_of=T-1`；④源降级链保留+盘后快照优先（省盘后冷态开销；**注意**：R7 交易时段冷态仍须预热覆盖，R26 只解盘后冷态，二者互补不替代） | 盘后设计不再「0%+静态兜底」→「T-1 因子分+标注」；correlation 盘后有值(`as_of=T-1`)；重启盘后不丢快照；前端显著标「盘后模式·数据截至 T-1」；快照消费必带 `as_of` 红字(反 R3 假实时)；新交易日开盘后快照过期强制实时 | `backend/app/core/market_calendar.py:26`、`backend/app/services/market_data_hub.py:485/1545-1557`、`backend/app/factors/factor_registry.py:776/1006` |


### 12.2 性能

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R6 | P1 | 预热 19.4s（F1/F2/F3 未实施）+ 宏观 10.6s | §1 的 F1/F2/F3/F3b（Session 复用 + gather 并发 + 降精度 + 宏观后台化） | 预热 ≤15s、market_cache ≤8s | `china_market.py`、`macro_fetcher.py`、`main.py` |
| R7 | P1 | 冷态性能超标（sectors/heat 5s 等 6 端点） | 预热覆盖冷拉取路径（板块热度/热榜/全球指数/持仓 NAV）；或首呼异步 + skeleton | 冷态 ≤1s（或首呼有 loading 态） | `market_refresh.py`、`market_service.py` |
| R8 | P1 | `/news` CLS 0.2077（新） | PerformanceObserver 定位偏移元素（资讯列表/partial 横幅/WS 推送插入）；预留 min-height | /news CLS ≤0.1 | `NewsView.vue` |
| R9 | P2 | root perf 69、FCP 2.0s（F4/F5 未实施） | 路由级懒加载已部分（router 已用 import()）；补 manualChunks vendor 拆分 + 首屏关键 CSS 内联 + preconnect | root perf ≥90、unused JS ≤100KB | `vite.config.js`、`index.html` |
| R10 | P2 | portfolio-analysis a11y=82 | 修对比度 | a11y ≥90 | `PortfolioAnalysis.vue` |

### 12.3 测试防护

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R11 | P1 | T5 CJK 检测对 JSON 转义中文误报 | CJK 检测改为：解析 SSE `data: {"token":...}` 后 `json.loads` 解出 token 再判 CJK（或 `unicode_escape` 解码） | 真实中文流通过、真空壳失败 | `verify_e2e.py:842` |
| R12 | P1 | 冷态性能无测量（T9） | 计时分冷/热两档，冷态单独阈值并纳入基线 | 冷态超标可被门禁发现 | `verify_perf.py`、`verify_e2e.py` |
| R13 | P1 | 候选池=0 软放行（T1） | 空结果改显式 degraded 断言（允许熔断但须 `degraded` 非静默成功） | 空方案 ≠ PASS | `verify_e2e.py` |
| R14 | P1 | 规则 confidence 0.7 无断言（T7 扩展） | 断言规则建议 confidence 非全 0.7 | 硬编码可被拦截 | `tests/` |
| R19 | P1 | 「方案数 >= 3」检查读摘要列表端点（缺 strategies）→ 恒假失败 | `verify_e2e.py:1472` 改读 `/designs/{id}` 详情端点取 `strategies`，或列表端点补 `plans_count` 字段 | 方案数检查反映真实 plan 数 | `verify_e2e.py:1472-1483` |
| R20 | P1 | 美股自选无实时（F21 未实施，QQQ/AAPL/SPY realtime=null） | 补美股实时源（TickFlow/新浪 levistock 美股 spot，F39 已接 US K 线可复用）或前端显式标注「该市场暂无实时」 | 美股自选有实时价或显式降级标注（非静默 null） | `fetchers/china_market.py`、`routers/market.py` watchlist |
| R21 | P2 | 建议 reason 引用原始因子值（「+8.97/+8.14/+11.46」）量纲不统一、不可解读 | reason 中的因子值统一归一化（如百分位/分档「偏强/偏弱」）或标注量纲 | 投资者可解读因子强度 | `portfolio_service.py` |
| R22 | P2 | `/factors/active` avg_ic 0.2134 与 `/factors/model` 0.3221 口径不一致 | 统一两处聚合范围（同因子集）或明确标注口径差异 | 同屏两值一致 | `routers/factors.py` |
| R23 | P2 | `_news_bucket` 懒刷新与后台任务刷新竞争 → 高负载下 headlines/macro/global 瞬态返 0 | 懒刷新加锁（避免并发 refresh）或失败时回退上次非空桶 | 高负载下不返 0 条 | `market_data_hub.py:1673-1679` |

### 12.4 资讯质量 + 治理

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R15 | P2 | macro tab 混「ETF日报」非宏观 | `_is_macro_relevant` 收紧（ETF日报/基金营销类剔除） | macro 无基金软文 | `news_fetcher.py` |
| R16 | P2 | global 7/8「other」（英文标题无分类） | 英文关键词分类器（yields/rate/inflation/war 等）或 AI 分类 | global 分类非全 other | `levistock_fetcher.py` |
| R17 | P2 | ai_summary 仅 headlines | macro/global 重要项也生成摘要（控成本上限） | 三桶均有摘要覆盖 | `market_data_hub.py` |
| R18 | P2 | 冗余/死代码（§11） | `DELETE /portfolio/designs/{id}` 整链删（端点+契约+handler `delete_design`）；`DELETE /admin/config/{key}` **保留** + `ConfigView` 补重置按钮；其余死函数/重复 import/陈旧 mock/临时文件清 | check_routes 绿（config 端点保留故契约不删）+ 无 0 引用残留 | 见 §11 清单 |

---

## 13. 多轮 review 记录

- **Round 1（自检，本次完成）**：15 项动作全部执行，形成 §0–§12。核心「证伪」：① round23 P0 修复**实证通过**（非预设）；② T5 守护对真实中文流**误报**（新发现）；③ `/news` CLS 0.2077（新问题，F35 未覆盖 news）；④ 冷态性能 6 端点 >1.1s 实证（T9 残留）；⑤ F11/T3 半落地实锤（规则 confidence 0.7 + 无 llm_layer_ok）。

- **Round 2（本次完成，交叉核对 4 项前置）**：
  1. **R2/R3 引擎交叉核对**：`allocation_engine.py` 现有 `MAX_WEIGHT=0.30`（上界）+ `_cap_core_growth_wide_basis` 核心数下限 [3,5]（M7）+ water-filling 回补，**无「核心单只下界」约束**（159338 配 1% 是因子分 -0.96 驱动的结果，非引擎钳制）。R2 新增「核心单只 ≥5% 下界」与现有约束正交、不冲突（5% ≤ 30% 上界，且不影响核心数下限）。**但根因是因子分校准**（宽基被深负分），R2 的正解应落在「因子分对宽基底仓的影响解耦」而非仅加权重下界——已按此修订 R2。
  2. **R13 静态兜底核实**：`strategy_design.py:169-222` 静态兜底池**已落地**，`pool_empty` 时产出 3 套静态方案。**「方案数=0」实为 verify_e2e 读错字段的假失败**（§10 缺口6），非真实 0 方案。R1 已据实修订（删「0 方案」表述，改「强板块未进池」为核心缺口）。
  3. **R8（/news CLS）定位候选**：`NewsView.vue` 中三处动态插入源——① `v-if="partial && !loading"` partial 横幅（`:54`）、② `loading`↔`<ul>` 列表切换（`:57-58`）、③ WS 推送（`useNewsWS`）列表顶部插入——均为 layout-shift 候选。R8 修订为「PerformanceObserver 精确定位后修」，不盲改。
  4. **R18 契约条目核实**：4 个死端点对应 `api-contracts/market/all.md`（sentiment）、`market/sectors.md`（sectors wrapper）、`admin/config.md`（DELETE config）、`portfolio/design.md`（DELETE design），同批删即可通过 `check_routes` 双向比对。
  5. **新增测试守护缺口（§10 缺口6）**：「方案数 >= 3」读摘要列表端点 → 恒假失败，与 T5 CJK 误报同源（守护读错数据源）。已补 R19。

- **Round 3（独立 reviewer 复核，本次完成）**：委托独立 agent 对照 `docs/design-checklist.md` 8 项复核。结论：**6 处证据链 citation 全部准确**；T5/R11/R19 三处测试守护误报「证真」成立。核心修正（已并入正文）：
  1. **R4 降级纠偏**：规则 confidence 非「硬编码 0.7」——`portfolio_service.py:1509-1511` 已是 round18 P2-7 的 2 档填充率分级（<70%→0.5、≥70%→0.7）。残余改为「数值 0.5/0.7 与 LLM high/medium 两种表示法不一致 + 0.7 易误读高置信」。
  2. **R2 收紧**：补「复用 `MANDATORY_CODES` ≥5% 地板（`allocation_engine.py:1261-1291`）+ 层预算闭包约束（Σ核心下界 ≤ core_budget，核心数 >7 时下界让位）」，避免破坏 weight-不归一化 + 层预算闭包不变式。
  3. **补 4 个缺失修复设计**：R20（美股自选无实时/F21）、R21（因子值量纲）、R22（avg_ic 口径不一致/F26b 断链）、R23（news 懒刷新竞争瞬态 0）。
  4. **D3 验证窗口标注**：盘后窗口数据依赖项补「待交易时段复测」标注（§2.1）。

- **Round 4（关联度专项评估，2026-08-14 收尾新增）**：拉取真实 design 570（`/portfolio/designs/570`，19:40 盘后生成、`valid_rate=0.0%`）的 `strategies[].risk_metrics.correlation_warnings` 实证。结论：引擎**能**抓宽基大盘重叠（510300↔159338 corr 0.983、159338↔510500 corr 0.939），但**漏**主题级冗余（半导体/港股药/券商 A/H 双发）、**不一致**（防御方案 上证50+沪深300 三重持有未告警）、**降级失真**（无价格对静默跳过 + 削减依赖失效因子分致 A500→1% 违反 R2）。新增 **R24**（关联度/冗余控制缺口，P1）。R24 与 R1 为兄弟项（R1=候选池脆弱，R24=入选后冗余控制），均带 **D3 交易时段复测**前提（缺口 1/2 可能部分源于盘后无价格序列的降级假象，需 9:30-11:30/13:00-15:00 重跑设计确认）。

- **Round 5（信号一致性评估，2026-08-14 收尾新增）**：针对用户三连问（持仓技术面板 reason 仅 MACD/MA / 是否该换综合信号含因子基本面 / 策略检查与标的分析是否也未纳入因子基本面）实证三个分析面。结论：①持仓 `SignalPanel` 纯技术（caption「不含因子与基本面」），calm 市下 `generate_signal` reason 仅 MACD+MA 属**条件触发非 bug**（RSI 40-60 中性、KDJ 中段不 emit，live `/signal/510300` 等证实极端态 RSI/KDJ 正常出现）；②策略检查 + 标的分析**已纳入因子(33维)+基本面(PE/PB)**作展示列+LLM 叙述（`portfolio_service.py:12-43/:637-670`、`analysis.py:623-633/685-692`），但**未聚合进结构化 buy/sell/hold 决策信号**；③三面口径不一致是真问题。新增 **R25**（信号口径三面不一致 + 综合信号降级门禁，P1）：不替换技术信号、新增独立综合信号卡（复用 `composite_signal` 并带 R3 降级门禁）、最优先落地策略检查、持仓面板中性区补 info reason 消除 Q1 误导。R25 与 R24/R3 为兄弟项（均围绕「降级诚实 + 口径一致」）。

- **Round 6（盘后数据变薄优化评估，2026-08-14 收尾新增）**：用户问「盘后数据变薄有无优化方案」。实证根因：盘后因子源/实时价/板块动量/资金流全不可达（design 570 `valid_rate=0%`、correlation 空、`sector_momentum=[]`、`fund_flow=0`）；当前降级被动推断（`get_market_status` 未接入链路）、`last-good`/kline/ic 缓存全内存重启即丢、T-1 真实数据不持久化。发现先例 `sentiment_cache.json` 落盘+失败恢复（A02, `market_data_hub.py:1545-1557`）已验证可行。新增 **R26**（盘后数据变薄优化：快照持久化 + 显式盘后模式，P1）：核心认知转「盘后=T-1 数据非无数据」→ ①接入 `market_calendar` 显式盘后模式；②因子矩阵/候选池/板块动量/资金流/K线落盘持久化（复用 A02 模式，内存 `_last_good`→持久化）；③逐字段 `as_of` 时效标注，修正 `correlation_unchecked` 语义（盘后应有 T-1 K 线→关联度可算只标 `as_of`）；④盘后快照优先省冷态开销。R26 与 R3/R24/R1 强协同（T-1 快照喂养 R1 强板块、R24 关联度、R3 标注）。R26 为 R3 兄弟项，是「降级诚实」的底层数据基座。

- **Round 7（独立 agent 复核 + R2 诊断纠错，2026-08-14 收尾新增）**：委托独立 `general-purpose` agent 对照代码逐条复核 R1–R26 的 `file:line` 引用与根因。结论分两类：
  1. **R24 / R25 / R26 引用全部准确**（`allocation_engine.py:1374`、`signal.py:4/51`、`market_calendar.py:26`、`market_data_hub.py:485/1545-1557` 等与正文一致），无需改。
  2. **R2 触发 BLOCKER（关键纠错）**：原 R2 诊断（「因子分极端驱动宽基淘汰 / 无 ≥5% 地板 / 复用 MANDATORY_CODES 地板」）与代码事实矛盾——agent 实测 `CORE_ANCHORS={"510300","159338"}`（`allocation_engine.py:235`）本就享 `MANDATORY_CODES` 豁免，且 allocate 内**已有 ≥5% 地板后处理**（`allocation_engine.py:1261-1295`）。`159338=1%` 真因是 `enforce_max_correlation`（`allocation_engine.py:1374`，round20 P1-1）削减高相关对时**未检查 `MANDATORY_CODES` 豁免**，把已落地的强制锚地板击穿。原 R2 引用 `:1261`（实为地板非 `_cap_core_growth_wide_basis` 定义（`:784`））、`:663`（`_compute_composite` 不在 allocation_engine.py，在 `market_data_hub.py:985`）亦错。已据实**重写 R2**（根因=关联度削减击穿强制锚地板，修复点移入 `enforce_max_correlation` 继承 `MANDATORY_CODES` 豁免，与 R24 fix⑤ 共用一处修复）；修正 R2 引用为 `:1374`/`:1261-1295`/`:235`/`:784`；R24 fix⑤ 同步补 `MANDATORY_CODES` 检查；R1 注入点引用更正为 `:506-517`/`:520-525`；§0.4 P0 #2 与正文一致（已无「无静态兜底」/「因子分极端驱动」矛盾表述）。

> **当前状态：Round 7 完成，达到实施标准。** 全部修复设计 R1–R26 均具备准确的 `file:line` 证据 + 验收口径 + 级联风险 + D3 交易时段复测标注；R2 经独立 agent 复核纠错（强制锚 ≥5% 地板已存在、被关联度削减击穿的根因已坐实）。分三批实施（批1 P0+P1 数据可信度 R1/R2/R3/R4/R5/R11/R13/R14/R19/R20/R24/R25/R26；批2 P1 性能 R6/R7/R8/R12；批3 P2 治理 R9/R10/R15/R16/R17/R18/R21/R22/R23）。**等待用户「开始实施」指令，不写任何修复代码。**
