# Round13 — 数据源系统性评估与宏观因子增强方案（2026-08-09）

> 状态：**方案文档，未实施**（仅记录已落地项与待实施项细化方案）
> 背景：本对话对项目数据源做了系统性实测评估（EM 根因三路线、mootdx 处置、BaoStock/TickFlow/AlphaFeed/Finnhub/RSS 源评估），并讨论了「akshare 宏观接口增强因子模型」方向。本文档将全部讨论结论、证据与待实施细化方案归档，供后续按批次实施。

---

## 1. 结论速览

| # | 主题 | 结论 | 状态 |
|---|---|---|---|
| 1 | EM 根因（push2 被拦） | **push2delay 双源路由天然兜底**，候选池可用（1618 只）；方案 A/B/C 均不需要 | ✅ 已闭环（见 §2.1） |
| 2 | mootdx 通达信线 | **非交易时段误判已纠正**，已回滚恢复；待周一交易时段复测 | ⏳ 待复测（见 §2.2/§4） |
| 3 | BaoStock | ✅ 已接入历史日 K 第三环（144 行实测） | ✅ 已实施 `055682d` |
| 4 | TickFlow | ✅ 已接入历史日 K 第四环；key 模式实时行情能力已发现（待接入决策） | ✅ 已实施日 K / ⏳ 实时链待实施（见 §3.2） |
| 5 | AlphaFeed 免费层 | ❌ 不可用（10/min 频率不够） | 已否决 |
| 6 | 7 个财经 RSS | ❌ 全部失效（404/超时/非 XML） | 已否决 |
| 7 | Finnhub 新闻 | ❌ 不适合（全英文、A 股覆盖稀疏） | 已否决 |
| 8 | akshare 宏观接口 | ✅ 89 个中国宏观接口现成可用（M2/LPR/CPI/PMI/GDP 实测通；另 Shibor/社融恢复可用、两融接口现成，见 §3.1） | ✅ 调研完成，待实施（见 §3.1） |
| 9 | 宏观增强因子模型 | ✅ 方向成立（市态/环境维度，非截面因子） | ⏳ 待实施（见 §3.1） |

---

## 2. 已落地/已闭环项（现状记录，非新方案）

### 2.1 EM 根因：push2 域名级风控 → push2delay 双源路由天然兜底

**问题**：容器内 `push2.eastmoney.com`（ETF 列表/实时行情）被 EM 主动断连（`curl: (56) Connection closed abruptly`），候选池曾观测「0」。

**系统性验证结论**：
- **非 TLS 指纹型拦截**：curl_cffi 0.15/0.16 × 全部 impersonate 版本 + 无 impersonate，宿主机/容器均被断连（方案 A 无效）
- **非 IP 封禁**：同 IP 同指纹同时刻，`push2delay.eastmoney.com` 返回 200（390B 真实 JSON）——push2 域名级风控（不同 CDN 边缘规则）
- **mootdx 不可用**：TCP 通但数据 0 行（详见 §2.2）
- **容器内实测**：`_fetch_em_etf_list('push2delay.eastmoney.com')` → **1843 行（2.5s）**；`fetch_all_etfs_base()` → **1618 行真实数据**——双源路由（`em_push2 → em_push2delay`，etf_scanner L419-425）天然工作

**已交付**：
- 方案 A（curl_cffi）`711fb8b` → 回退 `c5f8b3d`（无效，不留死代码）
- 方案 C 备选配置 `987317c`：`backend/scripts/ipv4_forward_proxy.py`（强制 IPv4 CONNECT 隧道）+ compose `EM_PROXY`（默认空=直连）——**保留作备选，当前不需要**
- 方案 B（mootdx 主链）：mootdx 协议预检失败（见 §2.2）

**经验教训**：数据源连通性验证必须区分**交易时段/非交易时段**；判定「数据源失效」需交易时段证据；连续失败探测会触发 EM 临时限流（探测克制原则：单次请求 + ≥60s 间隔）。

### 2.2 mootdx：非交易时段误判 → 已回滚恢复

**过程**：
1. 2026-08-09（**周日 22:43 非交易时段**）测试 mootdx：TCP 连（0.6s）但 `quotes/bars/index` 全 0 行 → 曾误判「协议不匹配」→ 移除 mootdx（`ceb2260`）
2. 用户质疑「之前一直通？与交易时间有关吗？」→ 复盘发现：历史实测（R6-F1/R9 P0-4 的「0.35s 真实行情」）均为**交易时段**；通达信非交易时段 quotes 空是预期行为；TCP 连接成功=协议握手正常（真不匹配应在 setup 阶段失败）
3. **已回滚**（`7bcab09` = revert ceb2260），mootdx 全代码+测试恢复（13 文件）

**附带修复**：mootdx 依赖 tdxpy（`mootdx/server.py` import `tdxpy.constants`）——方案 A 清理时卸载 tdxpy 致 mootdx import 崩（3 测试挂），已重装。教训：卸载 pip 包前先 `rg` 反向依赖。

**待办**：周一交易时段复测（见 §4）。

### 2.3 BaoStock + TickFlow 历史日 K 已接入（`055682d`）

- **BaoStock**（开源免费、无 token、盘后 T+1）：`_baostock_history()`（bs.login + query_history_k_data_plus，run_in_thread 12s，前复权，指数 bs_code 显式）；fetch_history ETF 日线链第 3 环（sina→netease→baostock）；fetch_index_history akshare 失败→baostock 备用
- **TickFlow 免费层**（用户注册 key）：`_tickflow_kline()`（klines.get 1d/1w/1M，无 key 短路）；日线链第 4 环（…→baostock→tickflow）；key 存 `.env`（`TICKFLOW_API_KEY`，gitignore 覆盖，未入库）
- 实测：BaoStock 144 行收盘 4.751；TickFlow 宿主机+容器 500 行收盘 4.751——三源（EM/腾讯/BaoStock/TickFlow）交叉一致
- 容器依赖：`tickflow>=0.1.17`（python 3.14 无 0.2.x wheel，0.1.24 同 API 容器实测通过）
- **限制**：TickFlow CN_ETF 池只有标的清单无价格字段 → 未用作候选池源；BaoStock/TickFlow 均盘后更新无实时

---

## 3. 待实施项（细化方案）

### 3.1 宏观接口增强因子模型（P1 + P2）

**背景**：政策/宏观源调研结论——官方 RSS 全失效（实测 404/超时）、官方页面解析成本高；**`macro_fetcher.py`（R5-2-10）已实现四源并行抓取**（`fetch_lpr` / `fetch_money_supply` / `fetch_cpi_ppi` / `fetch_bond_yields` + `fetch_all_domestic_macro` 聚合，24h 成功/1h 失败缓存），akshare 另有 89 个中国宏观接口可扩展。宏观数据与因子模型天然契合：全市场单一值 = 现有 `MARKET_LEVEL_FACTOR_CODES`（P1-10）同类，截面恒等、不参与截面 IC。

**现状接口（macro_fetcher.py 已有实现 + 2026-08-09 实测补充）**：

| 接口 | 状态 | 用途 |
|---|---|---|
| `fetch_lpr`（LPR 1Y/5Y） | ✅ 已实现 | 降息/加息周期 |
| `fetch_money_supply`（M2/M1/M0） | ✅ 已实现 | M2 同比拐点 |
| `fetch_cpi_ppi`（CPI/PPI 月度） | ✅ 已实现 | 通胀环境 |
| `fetch_bond_yields`（国债收益率） | ✅ 已实现 | 无风险利率 |
| `fetch_all_domestic_macro` | ✅ 已实现聚合 | LLM 上下文（include_macro） |
| **Shibor** | ✅ **2026-08-09 实测恢复、未接入**（`macro_china_shibor_all`，2341 行 2.2s；R5-2-10「失效」注释已过时，macro_fetcher.py:7 已更正） | 银行间流动性（比 LPR 灵敏） |
| **社融** | ✅ **2026-08-09 实测恢复、未接入**（`macro_china_shrzgm`，136 行 1.5s） | 信用扩张信号（与 M2 互补） |
| **两融（大盘级）** | ✅ 接口现成（`macro_china_market_margin_sh/sz`，沪深融资融券余额/买入额，3968/3770 行 0.7/0.5s；项目**未接入**，待 §3.1 纳入） | 杠杆资金情绪（日频数据、环境维度定位） |
| **PMI / GDP** | ⏳ 待新增（`macro_china_pmi_yearly` 月频 / `macro_china_gdp` **季度**，实测 250/82 行） | 荣枯线/经济周期（GDP 用季度接口，匹配季频因子与滞后标注） |

> 实测（2026-08-09 非交易时段）：M2 222 行 1.3s、LPR 1574 行 1.9s、CPI 477 行 8.6s（yearly 接口实测值，仅作「akshare 东财源慢、需 15s+ 超时」佐证；月度沿用既有 `fetch_cpi_ppi`）、PMI 250 行 4.3s、GDP 82 行（季频 2006-2026）1.6s——均来自东财数据中心/新浪（非 push2 反爬范围）。

**P1：市态判定增强 `detect_market_regime`**

- **扩展 `macro_fetcher` 而非新建模块**：新增 `fetch_pmi_gdp()`（PMI + GDP 两源，`run_in_thread` + 15s 超时，并入 `fetch_all_domestic_macro`）；新增 `fetch_macro_snapshot()` 聚合（M2 同比 / PMI / LPR 1Y 三指标，复用既有 24h 缓存键 `macro:*`，失败降级返回 None）
- `detect_market_regime` 加可选参数 `macro: dict | None = None`（默认 None，**现有调用零影响**）：
  - PMI < 50 → 风险偏下（防御倾向）
  - M2 同比环比下行（货币收紧）→ 风险偏下
  - LPR 同比下调（降息周期）→ 风险偏上
  - 修正规则：现有输出 + 宏观同向叠加、宏观冲突时**保持现有输出**（宏观为辅助非主导）
- 调用点：`market_data_hub.get_market_regime()` 组装时传入 macro snapshot
- 验收：单测覆盖「macro=None 行为不变」「PMI<50 偏防御」「三指标全 None 降级」；真实链路 `fetch_macro_snapshot()` 返回非空

**P2：宏观环境因子（MARKET_LEVEL 类）+ LLM 上下文**

- **注册位置（两处，缺一不可）**：
  - `factor_registry.py`（`register_computer`，~L1015）：注册 **5 个 compute 函数**——月频 3：`macro_m2_trend`（M2 同比 3 月斜率 → -1/0/+1）、`macro_pmi_level`（PMI ≥50 → 1，<50 → 0）、`macro_lpr_direction`（LPR 1Y 同比 → -1/0/+1）；**季频 1：`macro_gdp_trend`**（GDP 同比增速分位 → 环境分级 -1/0/+1，季度级）；**日频数据/环境定位 1：`margin_leverage_trend`**（沪深融资余额合计 20 日变化率 → -1/0/+1，杠杆资金情绪，2026-08-09 补充）
  - `routers/factors.py:72`：把 **5 个** code 加入 `MARKET_LEVEL_FACTOR_CODES` 集合（否则 `/factors/active` 不会以 static 标注，L130 过滤依赖该集合）
- 标 static（与 sentiment 同处理：不参与截面 IC、不撑「数据完整」判定）
- **扩展既有 `build_full_context` 宏观段**（llm_context.py L193 `include_macro` 已注入 domestic_macro）：补 PMI/GDP 两指标 + 方向标注（-1/0/+1），并输出数据截至日期（含滞后标注）——LLM 报告可引用
- **CPI 口径统一**：沿用既有 `fetch_cpi_ppi`（月度），不引入 `macro_china_cpi_yearly`（避免双口径）
- 验收：因子出现在 /factors/active（static 标注）；LLM 上下文宏观段含 PMI/GDP 真实值（非占位）；全量测试绿（含 macro_gdp_trend 滞后对齐单测断言：只用已发布值、季度对齐）

**频率定位（月/季频慢变量 + 日频环境变量，2026-08-09 讨论补充）**：
- 慢变量驱动**月级市态**（牛熊切换是季度级现象）——定位「环境/市态维度」，与快变量（行情/技术/情绪日频）互补；标准量化实践 = 慢变量调节快变量（宏观恶化 → 降低进攻性权重/总仓位上限），非直接进选股池
- 月频（M2/PMI/LPR）够做**斜率/拐点**（3 月窗口）；季频（GDP）一年仅 4 点，做**环境分级**（增速分位 -1/0/+1）而非连续数值；**两融为日频数据但作环境维度**（20 日斜率，非盘中决策）——杠杆资金情绪是经典风险偏好指标，与 sentiment 因子互补

**约束**：宏观月频/季频 + 发布滞后（CPI 月后 10 天、**GDP 季后 1.5 月**）→ ① **前视偏差红线：只用已发布值 + 滞后期**（GDP 因子用「数据截至 2026-Q2」标注，禁止用当季原始值当因子）；② 时间戳诚实标注（「数据截至 2026-07/Q2」）；③ **不参与**盘中高频决策；④ akshare 数据源（东财/新浪）需超时+熔断+缓存（延续既定模式）。

### 3.2 TickFlow 实时行情接入（P1 美股 / P2 港股 / P3 A 股）

**背景**：key 模式实测（2026-08-09）——`quotes.get(symbols≤5)` 返回完整实时快照（last_price/prev_close/OHLC/volume/amount/change_pct/turnover_rate/name），**A 股/港股/美股三市场可用**（AAPL 313.33 / 00700.HK 478.8 / 510300.SH 4.751 实测）；`get_by_universes`（全市场池）与分钟 K（intraday）需付费权限。

**能力矩阵**：

| 能力 | 免费 key | 限制 |
|---|---|---|
| 实时行情快照（按 symbol） | ✅ | **≤5 只/次** |
| 历史日/周/月 K | ✅ | 已接入（055682d） |
| 全市场池行情 | ❌ 付费 | 候选池不可行（TickFlow CN_ETF 池 1589 只/5 只每次；候选池现用 EM push2delay 1618 只——不同源清单数差异正常） |
| 分钟 K / 深度 / 流 | ❌ 付费 | — |

**接入设计**（定位：降级链**尾环**，非主环——平时 A 股 tencent/sina、美股 TwelveData/Finnhub 主用，失效才切，规避速率限制）：

- P1 美股实时（`market_service`）：现主链 **TwelveData(800 次/天) → Finnhub(60 次/分)**（yfinance 已移除，v3 起）——链尾加 `_tickflow_quotes` 环（单只查询，完美适配 5 只/次；与 TwelveData 日额度互补：TD 额度耗尽或 Finnhub 失败时切入）
- P2 港股实时（`china_market.fetch_hk_stock_realtime`）：sina→tencent→EM(akshare) 链尾加 tickflow（EM 反爬免疫）
- P3 A 股单只实时（`fetch_a_stock_realtime`）：tencent→sina→tickflow 尾环
- 通用包装 `_tickflow_quotes(symbols) -> list[dict]`：`run_in_thread` + 8s 超时 + 无 key 短路 + 字段映射（last_price→price 等）+ mock 测试
- symbol 映射：A 股 `510300`→`510300.SH/SZ`、港股 `00700`→`00700.HK`、美股 `AAPL`→`AAPL.US`
- **验收**：真实链路三市场各取 1 只非空；无 key 短路返回 []；批量 >5 只拆分或拒绝（诚实降级）

**注意**：免费额度「较严格」（未公开 QPS）——尾环低频调用设计的前提；若实测批量场景 429 频繁，P3 降级为仅单只场景（技术分析页）使用。

### 3.3 政策源替代（证监会公告，暂缓）

- 证监会公告页 200 可达（221KB HTML）但结构易变——**不推荐页面解析**（维护成本高）
- 建议：宏观链现有 O7 词过滤已覆盖部分「监管/政策」关键词；如需结构化监管数据，后续单独评估（不在本批范围）

---

## 4. 待复测项

| 项 | 复测命令 | 判定 |
|---|---|---|
| mootdx（周一 9:30-15:00 交易时段，需在 `backend/` 目录下运行） | `python -c "from app.fetchers.china_market import _mootdx_realtime; print(len(_mootdx_realtime(['510050']) or []))"` | >0 → mootdx 正常，移除决定作废；仍 0 行 → 再评估（届时证据可靠） |

---

## 5. 已否决项（证据存档）

| 项 | 证据 | 原因 |
|---|---|---|
| AlphaFeed 免费层 | 实时 10/min、日 K 10/min（用户注册确认） | 频率不够降级链（候选池刷新秒级高频） |
| 财联社/新浪/东财/央行/证监会/路透/华尔街见闻 7 个 RSS | 全部 404 / 连接超时 / 非 XML（实测） | 端点已下线/变更，清单过时 |
| Finnhub 新闻 | 端点存在（60/min 免费）但全英文、A 股覆盖极稀疏（research 查证） | 语言/覆盖不匹配，对 A 股 ETF 决策无核心价值 |
| EM 方案 A（curl_cffi 换指纹） | 全版本 impersonate 被断连（实测） | 拦截非 TLS 指纹型 |
| EM 方案 B（mootdx 主链） | mootdx 数据 0 行（实测） | 非交易时段误判（见 §2.2），待复测后重判 |
| TickFlow 候选池源 | `get_by_universes` 付费权限 | 免费 key 无法全市场池查询 |

---

## 6. 验收口径与 How to apply

- **实施顺序建议**：§3.1 P1（市态增强，独立低风险）→ §3.1 P2（因子+LLM 上下文）→ §3.2 P1/P2（TickFlow 实时尾环）→ §4 mootdx 复测后决策
- 每项沿用既定规范：`run_in_thread` + 超时 + 熔断 + 缓存（宏观 24h）+ mock 测试 + 诚实降级 + 交易时段验证
- 关键记忆指针：EM push2delay（`EM根因-双源路由天然解决`）、mootdx 回滚（`mootdx移除-2026-08-09`）、BaoStock/TickFlow（`BaoStockTickFlow接入-2026-08-09`）
- **未决待用户确认**：~~§3.1 实施范围~~（P1/P2 已全做，含两融 margin_leverage_trend，f691af3+ab89166）、§3.2 实施范围（P1/P2/P3 已全做）、mootdx 复测结果后的去留（**2026-08-10 交易时段复测：normal，保留**）
- **两融已实施**（2026-08-10）：`margin_leverage_trend` 因子（沪深融资余额合计 20 日变化率 → -1/0/+1，`fetch_margin_leverage_snapshot`），注册两处（computers + MARKET_LEVEL_FACTOR_CODES）+ YAML（daily/环境定位）+ `/factors/active` static 标注；契约为 5 因子版（`api-contracts/factors/macro-factors.md`）
- **Shibor/社融去向待定**（2026-08-09 实测恢复但未接入）：可选① 进 P2 因子池（如 `shibor_trend` 流动性因子 / 社融增速因子）；② 仅进 LLM 上下文（build_full_context 宏观段补充，无因子）；③ 暂不接入——P1 市态判定保持三指标（M2/PMI/LPR）不变
