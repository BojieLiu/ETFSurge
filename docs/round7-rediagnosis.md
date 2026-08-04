# Round7 复诊与性能诊断报告（Rediagnosis）

> 状态：**诊断完成，未开始实施**（本轮仅诊断 + 方案设计，待 review 至实施标准后另行实施）
> 范围：在 Docker 全新构建的 HEAD `0c78db8` 栈上，逐项重新执行 round6 的 15 步诊断，并与 round6 文档 (`docs/round6-diagnosis-and-optimization-plan.md`) 对照。
> 环境：docker compose（prod 态）+ `docker-compose.diag.yml` 临时 override（仅加 `PROFILE_WARMUP=1`），Chrome 150 headless Lighthouse 13.4.1。
> 日期：2026-08-04。

---

## 0. 执行摘要

本轮在**全新容器环境**（无旧缓存、无 `~/.mootdx/config.json` 的 BESTIP）上重建并启动前后端，逐项执行 15 步诊断。核心结论：

- **核心 API 契约健康**：`backend/scripts/verify_e2e.py` 274/286 通过；本轮实测设计、策略检查、A/港/美多市场研判、个股/板块/概念/指数分析、自选、热点、持仓信号、因子模型均可用且质量大多为专业级。
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
| 13 | 测试防护盲区 | — | 契约+mock 缺数据源降级/并发/预热高峰/前端渲染四类场景 | ⚠️ 见 §6 |
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
  - **A 股"茅台"尽力复测已可命中**：`search?keyword=茅台` → `sh600519/贵州茅台`（hits=1），`恒生/半导` 同样命中。**早期快照"茅台=0"是数据窗口/未同步所致，非 `like` 结构缺陷**；`routers/market.py:256` 的 `Instrument.name.ilike("%茅台%")` 逻辑工作正常（以此为据，勿再改 A 股搜索结构）。
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
- **P10 指数/ETF 分析缺估值与 K 线**：指数分析开头"技术指标（空）/历史K线（无）/PE/PB 不可用"。

### 🟢 低优 / 补充

- **P11 持仓 `/portfolio/etfs` 的 `price` 字段为 null**（realtime 端点有价）。
- **P12 自选新建条目 realtime 为 null**（列表批量 realtime 正常）。
- **P13 港股 ETF 搜索返回 A 股同名 ETF 兜底**（恒生科技返回 A 股 ETF 而非港股 03066）。
- **P14 成交额>10 的 ETF 仅 1 只**、自选候选 0（数据源冷却窗口所致，非代码缺陷）。
- **P15 热股外盘空缺**：`/market/stock-hot-rank?market=HK/US` 均返回 0 条（A 股 50 条正常）——与 US/HK instruments 空同源；热点板块 15 条 / 热股 A 股 50 条加载正常（步骤 4）。
- **P16 news-impact 智能分析空洞**：传入 4 条真实头条（沙特阿美/BP/美联储/司尔特）仍返回 `summary="新闻内容为空"` 的空洞结论——LLM 收到空正文，`news` 未真正送入分析。与 P7（llm-advice 全缺失模板）同属上下文注入断裂；专业投资者会认定资讯智能分析**不可用**。

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

**盲区四类**：
1. **真实数据源降级**：单测全 mock → mootdx 空转、冷启动 BESTIP、历史 K 线 RemoteDisconnected 路径零覆盖。
2. **并发压力**：verify_e2e **顺序同步**，测"启动后稳态"，不测启动预热高峰；shared_executor 64/64 需并发才触发（预热 gate 也仅特殊配置 PROFILE_WARMUP 才真实断言）。
3. **数据源冷却 State 语义**：`akshare/dongfang=cooldown` 被标 **PASS**，不判定"数据缺失资格"、不告警 → 成交额/候选缺失加速通过。
4. **前端渲染性能**：契约只测 HTTP 状态，不测 LCP/CLS/未用 JS → 仅 Lighthouse 暴露。

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

> 实施优先级建议：P1/P2/P3（性能+个股搜索）→ P4（前端）→ P5/P6/P7（LLM/RSI/投顾质量）→ P8/P9/P10（因子/资讯/估值）。

---

## 8. 回收（步骤 15）

部署完成后执行：`docker compose down --remove-orphans --rmi local`（回收容器与本地镜像）、删除 `docker-compose.diag.yml` 临时 override、恢复 `docker-compose.yml`/`.env`（移除 PROFILE_WARMUP）、清理诊断脚本（`_diag_*.py`、`_*.json`、`_lh_report.json`、diag/probe_followups.py）。