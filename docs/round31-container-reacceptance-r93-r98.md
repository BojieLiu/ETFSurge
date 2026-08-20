# round31 交易时段复验轮 — 容器全链路诊断 R93-R98（2026-08-20）

> 本文档为 **round30 R85-R92 全部实施后**的又一次 Docker 重建 + 交易时段全链路复验结论。
> 与 round30 分离：round30 只含 R85-R92 设计/实施；本文档独立承载 **2026-08-20 交易时段复验 + 新发现 R93-R98 的修复设计**（只写方案，未写修复代码，等待「开始实施」指令）。
> 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」撰写。
> 验证环境：Docker Engine 29.7.2 / Compose v5.4.0，prod profile 重建；backend 镜像 `fb5c3d51090d` / frontend `f343b2ab5af6`；`PROFILE_WARMUP=1`。
> 验证窗口：2026-08-20 10:26–11:5x（**周四 A股/港股交易时段内**；美股盘后 → AAPL/TSLA 相关标「待美股时段复测」）。

---

## 0. 执行摘要

### 0.1 本轮性质与核心结论

round30 的 R85-R92 已全部实施（commit `4e47ac4`）。本轮用全新镜像在**交易时段**复验，**确认结构化修复真实生效，但暴露 6 个新缺陷（R93-R98）**。

**核心结论：R85/R87/R92/R77/R70b/R89 的结构化目标真正生效**（设计用真实差异化因子、三处口径统一、realtime 契约归一、设计 3/3 非 CASH、concept 热态 139ms）；但：

1. **R93（P0）— R86 修复自身的「本地绿容器裂」**：`config.py:148` 正则 `^sqlite(?:\+\w+)?:///+(.*)` 对容器 4 斜杠 URL 贪婪吃掉前导 `/` → `data_dir` 解析为**相对路径** `app/data` → kline_cache.json 仍写镜像层 `/app/app/data`（重启即丢），挂载卷 `/app/data` 从未被读写。**本地恰绿是因为 Windows 盘符**——正是 round30 §12.2 预言的「本地绿、容器裂」缺陷在 R86 修复自身身上复现。
2. **R94（P1）— 动量跨路径不一致**：设计 rationale 有真实动量（512890=-0.385），策略检查 composite momentum 恒 0.0（13/13 degraded）——`_collect_strategy_data`（strategy_check.py:108）与设计路径（`_refresh_impl` 喂 `_kline_cache` 列式）数据源不一致。
3. **R95（P1）— 报告正文（LLM/rule 文本层）数值源不一致**：正文「512890 KDJ J=6.16超买」vs 结构化 `KDJ.J 84.49` vs `/market/indicators` 84.49；159545 正文 6.90 vs 90.11；量比 -9.86 负值异常；518880 SMA 3.07/13.06 vs 实测 9.02/8.99；**record 793（11:59 北京）「港股类合计权重 10%」vs 同批 holdings_json 实测 13%（权重合算错误，R95 第三类）**。**6.90 值在 round30 §2.2.1（record 754）已记载且本轮回现 → 固定数据源问题，非幻觉/波动**。「港股内部联动性高」判断有实测支撑（同市场对 0.34-0.55），round30 否定样本用错（A 股红利对照）。
4. **R96（P1）— factor_data_quality valid_rate 口径误导**：技术因子已真实计算（样本 240/250），指标仍报「缺失 100%、方案仅供参考」，与正文引用真实 RSI 自相矛盾。
5. **R97（P1）— R91 根因实证**：instruments 表无 A股个股段（容器启动 sync「A股个股 TIMED OUT 30s / 港股 FAILED」，表内仅 etf 1582 + US 120）→ 茅台/腾讯/苹果个股搜索 0；`_STATIC_A_STOCK_BASE` 静态兜底未兜住。
6. **R98（P2）— R90 global 桶摘要缺口**：/news/global 8 条中 5 条 level≥3 无 ai_summary（rule 兜底未覆盖 global 桶）。

### 0.2 关键结论判定表

| 判定 | 项目 |
|---|---|
| ✅ 真正生效 | R85（数据可用性，真实差异化因子）、R87（三处口径统一 33.3%）、R92（realtime 恒 7 字段）、R77（3/3 非 CASH）、R70b（report full）、R89（concept 热态 139ms） |
| ✅ 交易时段通过 | R88（600519 signal `data_available=true`、00700 indicators `ma5=445.8`） |
| ❌ 失效 / 未达成 | R86 落盘（R93）、R91 搜索（R97）、R90 global 桶（R98） |
| ⚠️ 需修正 | R88 个股未入 Hub 缓存（组合持仓全为 ETF）、R83 TSLA「维护中」文案（盘前非故障）、verify_e2e/patrol 部分 FAIL（结构性：M7 core=2、etf_specific no_data） |

### 0.3 验证窗口标注（D3）

本轮执行于 2026-08-20 10:26–11:5x（周四 A股/港股交易时段内）。R97（个股搜索盘中）、R98（资讯实时）为交易时段实测；**R93-R96 均为代码级结构事实，不受窗口影响**。美股相关（AAPL/TSLA 盘中、SPY indicators 25s 超时）标「待美股时段复测」。

---

## 1. 环境构建与启动（阶段 1）

| 项 | 结果 |
|---|---|
| Docker daemon | 重启成功，29.7.2（Compose v5.4.0） |
| 旧容器清理 | 无遗留 |
| 构建+启动 | **12.7s**（backend 镜像 `fb5c3d51090d` 全新 3min、frontend `f343b2ab5af6` 复用 15h 前构建） |
| 后端就绪 | warmup **51.2s**（>30s 预算，与 round30 53.8s 同量级；`sector list prefetch done (R89)` 生效） |
| 前端存活 | http://localhost HTTP 200 |
| 老镜像回收 | 无 dangling（0B） |
| **🔴 R93 首日发现** | 容器内 `settings.data_dir="app/data"`（**相对路径**）→ 本轮 10:28 仍写 `/app/app/data/kline_cache.json`（1,349,073B），挂载卷 `/app/data/kline_cache.json`（01:12 本地产物）从未被容器读写 |

**Compose v5.4.0 坑**：`--profile` 须放子命令前（`docker-compose --profile prod up -d --build`），`up` 后置会报 unknown flag。

---

## 2. 全链路诊断（阶段 2）

### 2.1 预热任务核验

- ✅ 板块缓存循环 60s（11:23:50→11:24:50→11:25:52→11:26:53，30 momentum rows + 13-15 hot plates）
- ✅ 市态+情绪循环 120s（11:25:29 regime range_bound / 11:25:37 sentiment persisted）
- ✅ 资讯缓存循环 120s（h=20 m=4 g=8，新浪 15 条 + RSS 全球 8 条）
- ✅ ETF cache warmup 1618 items；IC restore 20 entries（回填 243 交易日跳过）
- ✅ instruments-sync：**A股个股段 TIMED OUT 30s / 港股 FAILED**（→ R97）；etf 1582 + 美股 120 写入
- ✅ indices_meta 635 rows；design-data warmup 38 pool symbols kline cached（R59④）
- ⚠️ `get_pool() main pool is empty`（10:27:29 预热早期，10:28:14 refresh 完成后恢复）
- ⚠️ sector_fetcher 8 个 popular concept「not found → appending placeholder」

### 2.2 关键端点实测

| 端点 | 结果 |
|---|---|
| /market/signal/600519 | **722ms，`data_available=true, signal=sell, score=-1.5`**（MACD死叉+MA5<MA20）✅ 交易时段 |
| /market/indicators/00700 | **1.9s，`data_available=True, ma5=445.8`** ✅ 交易时段 |
| /market/sectors/concept | 热态 **139ms / 500 条**（R89 预拉命中）✅ |
| /market/watchlist | 热态 2.5s；**23 条 realtime 全部统一 7 字段**（R92 ✅） |
| /factors/active | valid=0 / no_data=27 / static=11；reason 已由「数据源未接入」→「IC 积累中（240/250 交易日）」 |
| WS | /api/v1/ws/news 订阅即推快照 ✅；/api/v1/ws/portfolio hello ✅；/api/v1/ws/market 连接正常 |

**WS 路径坑**：正确路径是 `/api/v1/ws/...`（非 `/ws/...`，后者 403）。

### 2.3 设计任务 652（R85 核心验收）

`POST /design-async {"capital":500000}` → task 652 completed（~45s，LLM 节流下仍产 full）：

- ✅ R77：`3/3 strategies have valid non-CASH ETFs`；卫星层 3/4/5 只/plan（round30 631 为 0）
- ✅ R70b：`report_quality=full`（报告 5515 字符）
- ✅ R85 数据可用性：**rationale 全用真实差异化因子**——RSI 44.1/56.7/36.3/26.6/66.6 各不相同、动量 +0.163/+2.659/+0.530、综合信号 +0.04/-0.14/+0.29；factor_breakdown 含真实 z-score（sma_5=-0.502、rsi_14=44.1）；**无「RSI 50.0 / 动量 +0.300 / 信号 -0.34 全同值」占位**（负向断言 PASS）
- ❌ R96：`factor_data_quality={valid:0, no_data:182, valid_rate:0.0}` + `data_precision.factor_missing_pct=100`——与正文真实 RSI 自相矛盾
- 结构：防御 core2(510050+512890)+sat3+def2+cash24.1%；平衡 core2(510300+510500)+sat4+cash23.0%；进攻 core2(510300+588000)+sat5+cash9.5%
- 价格 7/7、8/8 全有值（verify_e2e 的 0/18 是负载降级期另一设计）
- market_context：regime=range_bound、sentiment_index=47.49 中性、fund_flow 全 0（akshare 熔断，诚实空）、strong_sector_coverage=[]

### 2.4 策略检查 783（R87 验收 + R94/R95 实证）

`POST /strategy-check-async` → task 653 completed（record 783，LLM full）：

- ✅ R87：summary「因子覆盖 33.3%」= report_text「分项覆盖 33.3%（技术✓/估值✗/动量✗）」= factor_availability `{filled:1,total:3,ratio:1/3,components}`；**无「13/13 无兜底」残留**
- ❌ R85 下游：13/13 composite 仍 `degraded=true, signal=null`，components `{technical: 0.75/-1.0, valuation: 0.0, momentum: 0.0}`（R94）
- ❌ R95：正文「512890 KDJ J=6.16超买」vs 结构化 `KDJ.J 84.49（超买区）` vs /market/indicators j=84.49；「159545 KDJ J=6.90超买」vs 90.11/90.10；「量比-9.86 资金流出」（量比应 ≥0）；「518880 价格站上 SMA5/10(3.07/13.06)」vs 实测 ma5=9.02/ma10=8.99

### 2.5 搜索 / 资讯 / 数据健康

- ❌ R91：茅台→0、腾讯→2（板块+指数，无 00700）、苹果→1（板块，无 AAPL）、半导体→17（ETF 正常）→ R97
- ❌ R90 部分：headlines level≥3 全有 ai_summary；**/news/global 8 条中 5 条 level≥3 null**（Bessent lv5、Japan exports lv4、India chip lv4）→ R98；macro 1/2 null
- ✅ data_health_check 10/10 PASS（Sina realtime/kline、因子方差>0.01、候选池、DB、熔断器）

### 2.6 测试基线

- ✅ pytest：**2476 passed / 7 skipped**（round28 基线 2041）
- ✅ npm test：**499/499**（39 文件）
- ⚠️ patrol --full：exit_code=1；L1-unit PASS / L2-e2e **271/290（19 FAIL）** / L2-health PASS / L3-perf **timeline 1.72s + metrics 1.36s 硬门禁 FAIL** / L4-routes+purity+async PASS / L5-frontend PASS
- ⚠️ verify_e2e 独立跑：251/281（30 FAIL，多为并发负载伪失败：design 提交 15s 超时、timeline 2.2s、watchlist 7.1s——诊断自身 design/check 与 e2e 争池）；**patrol 内 L2-e2e 干净态 271/290 为准**
- **L2-e2e 19 FAIL 归类**：①M7 三方案核心层仅 2 只（门禁 [3,5]）——设计 652 结构性事实，需设计侧复核；②etf_specific no_data=10（amount_stability/change_pct/return_1m/return_3m 等）——return_1m/3m 本可从 K 线算，疑与 R94 同根；③sentiment no_data=1（news_heat）；④industry change_pct/main_inflow 空；⑤SPY indicators 25s 超时（美股盘后源）；⑥timeline/metrics 超 1s

---

## 3. 分析结果质量审查（阶段 3，四问法）

**审查对象**：设计 652 + 策略检查 783 报告逐句四问。

### 判断质量矩阵

| 判断原文 | 事实/推断 | 数据支撑（file:line+数值） | 与当下行情一致? | 结论 | 修复建议 |
|---|---|---|---|---|---|
| 「RSI 44.1 中性」510050 | 事实 | 设计652 fb `technical.rsi.rsi_14=44.1` | ✅ | 合理 | — |
| 「动量因子 -0.163」510050 | 事实 | fb `momentum=-0.163`（return_1m=-0.676/return_3m=0.387） | ✅ | 合理 | — |
| 「综合信号中性 +0.04」510050 | 事实 | fb 真实聚合值 | ✅ | 合理 | — |
| 「RSI 26.6 超卖」588200 | 事实 | fb rsi_14=26.6 <30 | ✅ | 合理 | — |
| `factor_data_quality valid=0/valid_rate=0%`「缺失 100%」 | **推断（IC 门禁非数据缺失）** | F25② `_status_of` 样本 230-243/250（/factors/active） | ❌ 与正文真实因子值矛盾 | **部分合理→R96** | 指标拆「数据可用 vs IC 积累」两维 |
| `fund_flow total_net_inflow=0` | 事实（诚实空） | 日志 `_compute_fund_flow: akshare circuit open` | ✅ 熔断期 | 合理（需标注） | 报告标注「资金流数据源不可用」 |
| 「RSI 44.02 低位回升」159338 | 事实 | 783 structured + /market/indicators | ✅ | 合理 | — |
| 「KDJ J=6.16 超买」512890 | **推断** | structured `KDJ.J 84.49（超买区）`；indicators j=**84.49** | ❌ **正文数值错误** | **失效→R95** | 正文与结构化/indicators 同源 |
| 「KDJ J=6.90 超买」159545 | **推断** | structured `KDJ.J 90.11`；indicators j=**90.10** | ❌ **数值错误** | **失效→R95** | 同上 |
| 「量比-9.86 资金流出」159545 | 事实但异常 | 783 正文 | ❌ 量比负值 | 需修正 | 量比负值兜底/校验 |
| 「价格站上 SMA5/10(3.07/13.06)」518880 | 推断 | indicators ma5=**9.02**/ma10=**8.99** | ❌ **数值错误** | **失效→R95** | LLM 引用值校验 |
| composite `momentum=0.0` 13/13 | 事实 | 783 holdings composite_decision | ⚠️ 设计 rationale 有真实动量 | **部分合理→R94** | 策略检查动量与设计同源 |
| 「因子覆盖 33.3%」三处一致 | 事实 | 783 summary/report_text/factor_availability | ✅ 口径统一 | **合理（R87 ✅）** | — |
| 「港股 13% 集中度」 | 事实 | 783 风险提示（5+5+3=13%） | ✅ 同 round30 口径 | 合理 | — |
| 「港股相关资产合计权重 10%」（record 793） | **推断（权重合算）** | 同批 holdings_json 实测 159545+513120+513010=**13%**；portfolio_etfs 实测 13%；791 同批报告写 13% | ❌ **与结构化合计矛盾** | **失效→R95** | 「合计权重」类表述与 holdings_json 权重和一致性校验 |
| 「港股内部联动性高」（record 793） | **推断** | 港股内部 pairwise 实测（239 交易日日收益）：513120×513010=**+0.548**、513010×159545=**+0.452**、513120×159545=**+0.336**；跨市场对照 513120×512890=+0.120 | ✅ 同市场对正相关 | **合理** | 支撑须选同市场对（round30 §2.2.1 用 A 股红利 512890 为对照是样本错误） |
| 「医药类合计 10% + 港股类合计 13%」并存（record 792） | 事实（口径未排重） | 513120 被同时计入医药类与港股类 | ⚠️ 分类归属冲突 | **需修正** | 分类口径排他（港股类 159545+513120+513010，医药类 A 股口径） |

### 汇总

- **可采信 N=10** / **需修正 M=5** / **臆断 K=0** / **失效=4**（R95 家族：KDJ J×2、SMA、港股权重 10%）
- **总体评价**：R85/R87/R92 修复在**结构化数据层**真实生效（因子值、口径、契约均实证正确）；但**报告正文（LLM/rule 文本生成层）存在数值源不一致**——同一标的同一指标，structured 与正文数值不同（512890 KDJ J：84.49 vs 6.16；793 港股合计 10% vs 结构化 13%），说明文本生成路径仍引用另一数据源，需「正文数值与结构化值一致性校验」（含聚合口径）。「港股内部联动性高」判断本身有实测支撑（同市场对 0.34-0.55），但 round30 §2.2.1 的否定样本用错（A 股红利对照）。

### 数据准确性抽查

- 权重：设计 652 三方案 cash=24.1%/23.0%/9.5%，Σweights+cash≈1 ✅
- RSI：512890 报告 56.74 vs indicators 57.09（接近，窗口差）⚠️ 可接受
- 占位检测：RSI 50.0/动量 +0.300/ln_mcap 0.0 **本轮设计/检查全无** ✅（R85 ② 生效）
- 相关性：设计 correlation_warnings 含实测 r=0.94/0.985（159338×510500）✅ 有实证
- 新鲜度：设计 as_of/data_fetched_at 有值；fund_flow 熔断期诚实空

---

## 4. 新发现问题（阶段 4，R93-R98）

### 4.1 R93（P0）— R86 修复自身「本地绿容器裂」：data_dir 解析为相对路径

**症状**：容器内实测 `settings.data_dir="app/data"`（**相对路径**）；`_kline_cache_path()="app/data/kline_cache.json"`；本轮 10:28 仍写 `/app/app/data/kline_cache.json`（镜像层 1,349,073B），挂载卷 `/app/data/kline_cache.json`（01:12 宿主机产物）从未被容器读写。

**根因链**（`config.py:148`）：
```
_resolve_data_dir 正则 ^sqlite(?:\+\w+)?:///+(.*)
  容器 URL sqlite+aiosqlite:////app/data/portfolio.db（4 斜杠 = 绝对路径语义）
  → :// 吃掉 3 个斜杠后，/+ 贪婪吃掉第 4 个 → 捕获 app/data/portfolio.db（丢前导 /）
  → Path().parent = "app/data"（相对路径）
  → 容器 CWD=/app 下解析为 /app/app/data（源码目录，镜像层，docker compose down/up 即丢）
本地恰绿：sqlite+aiosqlite:///E:/ETF_Surge/data/... Windows 盘符使相对值仍为绝对（isabs True）
```
**性质**：正是 round30 §12.2 预言的「本地绿、容器裂」同类缺陷，**在 R86 修复自身身上复现**——单测在本地跑恰好通过，容器环境裂。

### 4.2 R94（P1）— 动量跨路径不一致

**症状**：设计 652 512890 `momentum=-0.385`（fb 含 return_1m=0.14/return_3m=0.514 真实）；策略检查 783 同标的 composite `momentum:0.0`，13/13 全 degraded。

**根因**：策略检查 `_collect_strategy_data`（strategy_check.py:108）因子采集路径与设计路径（`_refresh_impl:330-342` 喂 `_kline_cache` 列式缓存）动量数据来源不一致；`_component_coverage_stats`（strategy_check.py:798）判 momentum 组件 0 填充。同一只 ETF 两条路径动量数据一有一无。

### 4.3 R95（P1）— 报告正文（LLM/rule 文本层）数值源不一致

**症状**：①783 正文「512890 KDJ J=6.16超买」vs 结构化 `KDJ.J 84.49（超买区）` vs /market/indicators j=**84.49**；②「159545 KDJ J=6.90超买」vs 90.11/90.10；③「量比-9.86 资金流出」（量比应 ≥0）；④「518880 价格站上 SMA5/10(3.07/13.06)」vs 实测 ma5=9.02/ma10=8.99；⑤**（2026-08-20 用户质询补录）record 793（11:59 北京）「港股相关资产合计权重10%」vs 同批 holdings_json 实测 13%**。

**关键佐证**：**6.90 值在 round30 §2.2.1（record 754）已记载且本轮回现**——record 790-792 结构化 factor_summary 恒 90.11/84.49（与 /market/indicators 一致），而正文恒 6.90/6.16 → **固定数据源问题，非 LLM 幻觉/行情波动**。

**③ 权重合算错误（record 793/792，用户质询实证）**：
- record 793 risk_warning + 正文「港股相关资产（恒生红利低波 159545、港股创新药 513120、恒生科技 513010）**合计权重 10%**」——但同批 holdings_json 三只权重 = 0.05+0.05+0.03 = **13%**；portfolio_etfs 实测 = **13%**；791 同批报告写「13%」正确。**同一时刻四源比对：三处 13%、正文 10% → 10% 为文本层合算错误（疑漏 513010 的 3%）**。
- record 792 口径混乱：「医药类资产合计 10%」+「港股类资产合计 13%」并存——513120（港股创新药）被**重复计入**医药类与港股类，分类未排重。建议明确：港股类 = 159545+513120+513010（及联接），医药类 = A 股口径（159992 等），两口径排他。
- **对「港股内部联动性高」判断本身的判定（四问法）**：方向合理——港股内部 pairwise 实测（239 交易日日收益）513120×513010=+0.548、513010×159545=+0.452、513120×159545=+0.336（均正相关，同受美元利率/南向资金/风险偏好驱动，市场 beta 敞口集中）；但注意 round30 §2.2.1 ② 曾用「513120×512890=+0.120」否定该判断——**那是样本错误**（512890 为 A 股红利低波，跨市场对比无意义），正确测法应为港股内部对。四问法支撑必须选对对比对象。

**根因**：文本生成引用另一数据源（疑 rule 兜底或 prompt 注入旧值/z-score 值）；`format_factor_summary`（结构化，round18 P0-3 对齐 /market/indicators 原始值）与文本层未同源；**「合计权重 N%」类表述未与 holdings_json 结构化权重和做一致性校验**（R95 第三类：数值错误从单指标扩展到聚合口径）。

### 4.4 R96（P1）— factor_data_quality valid_rate 口径误导

**症状**：设计 652 `factor_data_quality={valid:0, no_data:182, valid_rate:0.0}` + `data_precision.factor_missing_pct=100`「方案仅供参考」，而 rationale 引用真实 RSI 44.1/56.7 与动量 +2.659——**meta 与正文自相矛盾**。

**根因**：`_factor_data_quality_report`（strategy_design.py:998-1058）复用 F25② `_status_of` IC 样本门禁（样本<60 天→no_data，250 样本+t/IR 才 valid）；R85 修复后**数据可用性 ≠ IC 积累**，指标未拆两维。技术因子样本已 230-243/250（接近达标），但 valid_rate 恒 0% 误导。

### 4.5 R97（P1）— R91 根因实证：instruments 无 A股个股段

**症状**：容器启动日志 `segment A股个股 TIMED OUT after 30.0s / FAILED`、`segment 港股 FAILED`；instruments 表实测仅 `etf(1582)+US(120)`，无 A股个股（0 条）与港股；search 茅台→0、腾讯→2（板块+指数，无 00700）、苹果→1（板块，无 AAPL）；`_STATIC_A_STOCK_BASE`（market.py:381）静态兜底未兜住。

**根因**：instruments 同步 A股个股段单段 30s 超时即弃全段；`_search_a_stocks`（market.py:420）空结果时未回退静态基座（或静态基座未在容器内生效）。

### 4.6 R98（P2）— R90 global 桶摘要缺口

**症状**：/news/global 8 条中 5 条 level≥3 无 ai_summary（Bessent lv5、Japan exports lv4、India chip lv4 等）；macro 1/2 null。headlines 桶 level≥3 全有值。

**根因**：`enrich_news_summaries`（_news.py:53）的 R65/R90 rule 兜底（`_rule_news_summary`，_common.py:283）未覆盖 global 桶；`_CATEGORY_KEYWORDS`/`_ENGLISH_CATEGORY_KEYWORDS`（levistock_fetcher.py:25/142）对英文标题部分未命中。

---

## 5. 修复方案（R93-R98，只写方案，不写代码，等待「开始实施」）

### 5.1 修复方案总表

| ID | 级 | 方案 A / B + 推荐 | 影响范围（file:line） | 验收（含负向断言） |
|---|---|---|---|---|
| R93 | P0 | **A（推荐）**：正则改 `^sqlite(?:\+\w+)?:///?(.*)` 保留第 4 斜杠（容器 4 斜杠 `/app/data`、Windows 盘符不受影响）；validator 后置断言 data_dir 为绝对路径，非绝对则 WARNING+回退 | `config.py:137-155`、`_kline.py:114-137` | ①容器内 `settings.data_dir=="/app/data"`；②重启后 kline_cache.json 落挂载卷 `/app/data/`；③**负向**：容器内 `/app/app/data/kline_cache.json` 不再更新（mtime 冻结） |
| R94 | P1 | **A（推荐）**：策略检查因子采集对齐设计路径——`_collect_strategy_data` 的因子计算改喂 `hub._kline_cache` 列式（同 `_refresh_impl:330-342`），或对持仓复用 `get_factor_matrix` 子集；**B**：`_component_coverage_stats` momentum 判定改读 `etf.return_1m/return_3m` 键 | `strategy_check.py:108/798`、`hub/_pool.py` | ①同标的检查 composite `momentum≠0`（设计有值时）；②etf_specific return_1m/3m no_data 消除；③**负向**：检查与设计对同一标的动量方向一致（同天） |
| R95 | P1 | **A（推荐）**：报告正文数值一致性校验——文本生成后逐持仓比对 KDJ/RSI/SMA/量比 vs `factor_breakdowns` 结构化值，不一致用结构化值覆盖 + WARNING（仿 `_validate_report_consistency` 修正脚注模式）；**扩展**：正文/risk_warning 中的「合计权重 N%」类聚合表述与 holdings_json 结构化权重和做一致性校验（不一致覆盖 + WARNING）；**B**：定位文本层数据源（rule 兜底/prompt 注入）与 `format_factor_summary` 统一 | `strategy_check.py`（文本生成）、`analysis/signal.py`、LLM prompt 构建 | ①正文「KDJ J」与结构化一致（512890=84.49 非 6.16）；②量比无负值；③518880 SMA 显示 9.02/8.99 非 3.07/13.06；④**负向**：正文不得再出现 6.90/6.16/3.07/13.06/-9.86；⑤**负向**：报告「港股类合计权重」= holdings_json 结构化合计（=13%，不得出现 10%）；⑥**负向**：医药/港股分类口径排他（513120 不得重复计入两类） |
| R96 | P1 | **A（推荐）**：`_factor_data_quality_report` 拆「数据可用性」与「IC 积累」两维——数据可用性统计因子值非 None 占比（R85 修复后技术因子应有值），IC 积累单独标注「样本 N/250」；valid_rate 用数据可用性口径 | `strategy_design.py:998-1058`、`routers/factors.py _status_of` 调用处 | ①设计 652 类场景 valid_rate>0（技术因子有值）；②meta「因子缺失」不得与正文真实 RSI 并存；③**负向**：数据全空时仍报 0%（不误报正常） |
| R97 | P1 | **A（推荐）**：①instruments 同步 A股个股段改分批+降级（30s 超时拆 5s×N 段，单段失败不弃全段）；②`_search_a_stocks` 空结果时先查 `_STATIC_A_STOCK_BASE`（R91 已建，验证其挂载/导入路径）；③补 instruments 表 A股个股段启动同步（本地 5546 条已证数据可拉） | `sync_instruments.py`、`market.py:379-435`、`_STATIC_A_STOCK_BASE` 定义 | ①容器重启后 `茅台→600519`、`腾讯→00700`；②**负向**：levistock/instruments 双空时静态基座仍命中 |
| R98 | P2 | **A（推荐）**：`enrich_news_summaries`（`_news.py:53`）rule 兜底扩展到 global 桶（level≥3 全量，复用 `_rule_news_summary`，`_common.py:283`）；英文关键词补 `export/budget/beats/curb`（`_ENGLISH_CATEGORY_KEYWORDS`，`levistock_fetcher.py:142`） | `_news.py:53`、`_common.py:283`、`levistock_fetcher.py:25/142` | ①/global level≥3 条目 ai_summary 非 null；②**负向**：R90 词表命中项（attack/threat）分类正确 |

### 5.2 分批建议（不实施，等待指令）

- **批 1（P0/P1 正确性，数据可信）**：R93（落盘路径，P0）、R94（动量跨路径）、R95（正文数值一致性，含 KDJ/量比/SMA）、R96（valid_rate 口径拆分）。
- **批 2（P1/P2 治理）**：R97（个股搜索 + instruments 分段同步）、R98（global 桶摘要兜底）。
- **测试增强随批**：R93 负向「/app/app/data 不再更新」容器断言；R94 跨路径动量一致断言；R95 正文-结构化数值一致性负向断言（6.90 家族禁回）；R96 valid_rate>0 断言；R97 静态基座命中断言。
- **验证窗口**：R97（个股搜索盘中）、R98（资讯实时）交易时段验证；R95/R96 无窗口依赖（结构化事实）。

---

## 6. 多轮 review 记录（阶段 5，Round 1-3）

- **Round 1（实证 + 根因定位）**：逐条对照运行时输出。确立 R93「R86 修复自身本地绿容器裂」——容器内 `settings.data_dir="app/data"`（相对）实测 + 正则 `:///+(.*)` 贪婪吃斜杠代码级定位（config.py:148）；R94 动量跨路径经设计 652 fb vs 检查 783 composite 对照实证；R95 正文数值源经 record 790-792 结构化恒 84.49/90.11 对照正文 6.16/6.90 实证（且 6.90 跨 round30 §2.2.1 回现）；R96 经设计 652 meta vs rationale 自相矛盾实证；R97 经 instruments 表分组探针 + sync 日志实证；R98 经 /news/global 探针实证。
- **Round 2（file:line 复核 + 一致性）**：确认 `config.py:137-155`（validator，正则 `:///+(.*)` 吃第 4 斜杠实证）、`_kline.py:114-137`（cache path）、`strategy_check.py:108`（_collect_strategy_data）、`:798`（_component_coverage_stats，修正初稿 :755-779）、`strategy_design.py:998-1058`（_factor_data_quality_report）、`levistock_fetcher.py:25/142`（_CATEGORY_KEYWORDS/_ENGLISH）+ `_news.py:53`（enrich_news_summaries）+ `_common.py:283`（_rule_news_summary，修正初稿 news_fetcher.py:265-277）、`market.py:381/420`（_STATIC_A_STOCK_BASE/_search_a_stocks，修正初稿 :379-435）、`sync_instruments.py`（分段同步）锚点与代码一致。设计 652 core=2 标注为结构性观察（非本轮修复项，需设计侧复核 M7 门禁口径）。
- **Round 3（完整性 + 窗口标注）**：补 R97/R98 验证窗口（交易时段）；R93-R96 标注为代码级结构事实不受窗口影响；patrol 负向断言映射补齐；verify_e2e 30 FAIL 与 patrol L2-e2e 19 FAIL 归因区分（负载伪失败 vs 结构性，以 patrol 干净态 271/290 为准）；口径精确化：R85「valid>0」验收点拆解为「数据可用性」（✅ 已达成，真实因子值）与「IC 积累 valid 门禁」（合理未达，样本 240/250 需时日）——后者不再视为 R85 失败，R96 只针对「valid_rate 指标误导呈现」本身。

---

## 7. 待交易时段/美股时段复测项

- **美股（AAPL/TSLA/SPY）**：2026-08-20 10:26–11:5x 为美股盘后（美东前一日晚），AAPL/TSLA 盘中 realtime、SPY indicators 25s 超时项标「待美股时段复测」。
- **R88 个股入 Hub 缓存**：组合持仓全为 ETF（13 场内+13 场外），无个股持仓 → warmup 符号集实际不含个股——实施前提偏差，需在设计侧确认是否纳入自选/关注个股。

> **当前状态：已按 §5 方案实施（round31 实施轮）**——R93-R98 全部落地（commit
> `1441b19` feat(round31): implement R93-R98 ...）；后端全量 2515 passed / 前端 499 passed；
> 运行时验证（2026-08-20 13:49–14:07 周四盘中）：R97 茅台→sh600519/腾讯→00700
> （A股个股段 5547 条已同步）、R98 /news/global level≥3 摘要 5/5 非 null；
> R93-R96 为代码级结构事实（R93 data_dir 绝对路径单测+本地实测、R94 composite
> momentum 非 0 单测、R95 正文一致性单测、R96 valid_rate 数据可用性口径实测 1.0）。
