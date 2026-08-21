# round32 容器全链路诊断轮 — R99-R101（2026-08-20 盘后）

> 本文档为 **round31 R93-R98 全部实施后**（commit `842826c`）的又一次 Docker 重建 + 全链路复验结论。
> 与 round31 分离：round31 只含 R93-R98 诊断/实施；本文档独立承载 **2026-08-20 盘后全链路复验 + 新发现 R99-R100 的修复设计**（只写方案，未写修复代码，等待「开始实施」指令）。
> 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」撰写。
> 验证环境：Docker Engine 29.7.2 / Compose v5.4.0，prod profile 重建；backend 镜像 `51100c3d189b` / frontend `a4b6c8d26c9f`（复用 19h 前，见 §1 镜像复用核实）；`PROFILE_WARMUP=1`。
> 验证窗口：2026-08-20 14:51–15:5x（**A股收盘后**；信号/indicators 交易时段实测在 14:59 收盘前完成；设计/检查任务在 15:40 盘后触发 → 见 §4 R99 窗口标注）。

---

## 0. 执行摘要

### 0.1 本轮性质与核心结论

round31 的 R93-R98 已全部实施（commit `842826c`）。本轮用全新镜像复验，**确认 R93/R94/R96/R97/R98 结构化修复真实生效**，但暴露 **3 个新发现（R99-R101）**——R99/R100 集中在**设计任务降级态（partial）的因子数据路径**，R101 为**核心层宽基约束的设计侧校准**（用户决策）。

**核心结论**：

1. ✅ **R93（P0）容器级实证**：`settings.data_dir='/app/data'` 绝对路径；挂载卷 `/app/data/kline_cache.json` 本轮新写入（1,409,830B @ 14:52），镜像层 `/app/app/data/kline_cache.json` mtime 冻结在构建时（Aug 19 20:28）。「本地绿容器裂」修复真实生效。
2. ✅ **R94（P1）实证**：策略检查 696 场内 ETF composite momentum 全有真实值（512890=-0.193、159545=-1.0、518880=1.0 等），11 只 degraded 全是场外联接（0 开头代码、无因子数据，合理降级）。round31 的 13/13 全 degraded 已消除。
3. ✅ **R96（P1）实证**：设计 697 `factor_data_quality.valid_rate=0.967`（数据可用性口径）+ `ic_accumulation`（median 38/250）两维拆分生效，不再是 round31 的恒 0%。
4. ✅ **R97（P1）实证**：茅台→sh600519、腾讯→00700、阿里巴巴→09988、苹果→AAPL、特斯拉→TSLA 全命中；A股个股段 5547 行已同步（此前 30s 超时弃段）。
5. ✅ **R98（P2）实证**：/news/global 8 条中 level≥3 的 5/5 全有 ai_summary（此前 5 条 null）。
6. ⚠️ **R95（P1）受限验证**：本轮 LLM 配额耗尽（opencode_zen 429），策略检查走 rule 兜底（covered_by_llm=0/26），正文数值天然与结构化一致（rule 直接引用 format_factor_summary）；但 **LLM 正文路径无法复现验证**（待 LLM 配额恢复后补测）。
7. 🔴 **R99（P1 新发现）— R85 在 partial 降级态回归**：设计 697（design_id 681，盘后触发 + LLM 降级 → report_quality=partial）的 factor_breakdown 退化为 20 键降级版，聚合动量 `momentum=0.300` **18/18 ETF 全同占位**、`technical=0.0` 全同，rationale 引用「动量因子 +0.300」。根因：`factor_aggregate.py:81` momentum 聚合前缀误含 `china.policy.*` 静态因子，动量真实因子（etf.return_1m/3m）盘后 no_data 时，静态政策因子 0.3 污染动量聚合。full 态（round31 design 652）无此问题。
8. 🟡 **R100（P2 新发现）**：设计 697 `factor_data_quality` 报 `data_available=176/193（97%）`，但实际 factor_breakdown 退化为占位值——R96 的「数据可用性」统计口径（因子定义无 `_data_source_gaps`）与实际因子值（compute() 产出）脱节，97% 的「可用」掩盖了占位退化。
9. 🟡 **R101（P2 新发现，用户决策）— O16 大盘宽基族互斥自相矛盾**：强制锚 `CORE_ANCHORS={510300, 159338}`（`allocation_engine.py:235`）本身是 2 只**不同宽基指数**（沪深300 + 中证A500，实测相关性 0.968）被强制并存，而 O16（`allocation_engine.py:1192`）却对「非强制」大盘宽基做 ≤1 互斥剔除——同一套逻辑里「强制锚可 2 只不同宽基并存、非强制 1 只都不行」不一致，且很可能是 M7 core=2 失败的推手。用户判断：「同一指数才合并，不同宽基指数没必要合并」——M3 归一化（同一指数家族）该留，O16 互斥（不同宽基当同一族）该从「互斥剔除」改为「数量上限 + 高相关提示」。

### 0.2 关键结论判定表

| 判定 | 项目 |
|---|---|
| ✅ 真正生效 | R93（data_dir 绝对路径）、R94（composite momentum 真实值）、R96（valid_rate 两维拆分）、R97（个股搜索全市场）、R98（global 摘要 5/5）、R87（口径统一）、R92（realtime 7 字段） |
| ⚠️ 受限验证 | R95（LLM 正文路径，quota 耗尽无法复现）、R85（full 态 ✅ / partial 降级态回归 → R99） |
| ❌ 新发现 | R99（momentum 聚合误含静态政策因子 → 占位污染）、R100（factor_data_quality 口径与实际值脱节）、R101（O16 大盘宽基族互斥自相矛盾 → 软约束化） |
| 历史已知（非本轮） | M7 core=2、etf_specific no_data=10（IC 积累期）、sentiment no_data=1、timeline 1.23s 硬门禁——均 round31 §2.6 已记载 |

### 0.3 验证窗口标注（D3）

本轮执行于 2026-08-20 14:51–15:5x。**R97（个股搜索）、R88（signal/indicators）在 14:59 收盘前完成交易时段实测**；设计 697 / 检查 696 在 15:40 盘后触发（LLM 配额耗尽 + 收盘后数据源）。**R99/R100 需区分**：R99 的「momentum 聚合误含 china.policy.*」是代码级结构事实（`factor_aggregate.py:81`），不受窗口影响；但「盘后 etf.return_* no_data 触发占位」是窗口依赖的触发条件——交易时段内 etf.return_* 有值时不触发。R100 是口径层结构事实，不受窗口影响。**R101 无窗口依赖**（宽基相关性基于 kline_cache 历史日收益实算，非实时行情）。美股相关标「待美股时段复测」。

---

## 1. 环境构建与启动（阶段 1）

| 项 | 结果 |
|---|---|
| Docker | 29.7.2 / Compose v5.4.0，无遗留容器 |
| 构建+启动 | **9s**（backend COPY 变更层重建，依赖层全缓存；frontend 缓存复用） |
| 后端就绪 | warmup **39.9s**（>30s 预算，round31 为 51.2s，历史软债同量级） |
| 前端存活 | http://localhost HTTP 200；`/health` 200（正确路径 `/health` 非 `/api/v1/health`） |
| 老镜像回收 | 无 dangling（0B） |

### 1.1 前端镜像复用核实（用户质询，重要）

用户指出「前端镜像并没有更新」——核实结论：

- 前端镜像 `a4b6c8d26c9f` 创建于 **2026-08-19 19:12:34**（19h 前），确实**未重建**。
- **复用安全**：19:12:34 之后 `frontend/` 目录唯一变更 = `4e47ac4`（round30 实施）的 `frontend/src/test/WatchlistPanel.spec.js`（+29 行，**测试文件**，不进 `npm run build` 产物）。生产代码零变更，dist 无需重建。
- 注意：round31 文档记载 frontend 镜像 `f343b2ab5af6`，与当前 `a4b6c8d26c9f` 不同——镜像中途重建过一次，两 ID 均指向 19h 前，不影响本轮结论。
- **教训**：诊断汇报「镜像复用」必须附 `docker images` ID+CreatedAt + 源码 diff 论证复用安全，不能只引构建日志 `Built` 字样。

### 1.2 R93 容器级实证

- `settings.data_dir='/app/data'`、`isabs=True`（正则 `:///?(.*)` 保留第 4 斜杠修复生效）
- 挂载卷 `/app/data/kline_cache.json` = 1,409,830B @ Aug 20 14:52（本轮容器新写入）
- 镜像层 `/app/app/data/kline_cache.json` = 1,068,535B @ Aug 19 20:28（mtime 冻结在构建时，负向断言成立）
- 挂载卷 `/app/data/portfolio.db` = 55MB @ Aug 20 14:54（活跃）

---

## 2. 全链路诊断（阶段 2）+ 对照 round31 验证矩阵

### 2.1 预热任务与定时刷新

- ✅ ETF cache warmup 1618 items；IC restore 20 entries；instruments 7249 rows（A股个股 5547 + A股ETF 1582 + 美股 120；港股段 FAILED：`stock_hk_main_board_spot_em`/`stock_hk_spot` 源不可用，外部数据源）
- ✅ 板块缓存循环 ~60s（14:55:17→14:56:18→14:57:19→14:58:21→14:59:21）
- ✅ 市态+情绪循环 ~120s（14:54:16→14:56:17→14:58:17，regime=range_bound）
- ✅ 资讯缓存循环 ~120s（h=15 m=8/9 g=8）
- ✅ design-data warmup 38 pool symbols kline cached（R59④）
- ⚠️ `fund_hk_etf_spot_em` akshare 缺属性（外部源降级链内）
- ⚠️ sector_fetcher 8 个 popular concept placeholder（round31 同）

### 2.2 关键端点实测（热态）

| 端点 | 本轮 | round31 基线 | 结论 |
|---|---|---|---|
| /market/signal/600519 | 301ms，`data_available=true, signal=sell, score=-1.5` | 722ms | ✅ 更快，交易时段 |
| /market/indicators/00700 | 1.8s，`ma5=446.28` | 1.9s / ma5=445.8 | ✅ 交易时段 |
| /market/sectors/concept | 11ms | 139ms | ✅ 预拉命中 |
| /market/watchlist | 冷 5.3s → 热 11-18ms | 热 2.5s | ⚠️ 冷缓存超 3s 软门禁，热态正常 |
| /factors/active | 28ms，valid=0/no_data=27/static=11 | 同 | ✅ reason 已「IC 积累中」 |

**R92 验证**：watchlist 23 条 realtime 全部统一 7 字段（as_of/change_pct/data_source/estimate_source/is_estimated/price/volume），`field-count distribution = {7: 23}` ✅。

**WS 链路**：/api/v1/ws/news 订阅即推快照 ✅；/api/v1/ws/portfolio hello ✅；/api/v1/ws/market 连接正常（无首帧推送，广播通道设计，非 bug）✅。

### 2.3 对照 round31 R93-R98 验证矩阵

| round 项 | round31 预期 | 本轮实测 | 结论 | 证据 |
|---|---|---|---|---|
| R93 | data_dir 绝对路径 + 挂载卷落盘 | `data_dir='/app/data'`，挂载卷 kline_cache 14:52 写入，镜像层 mtime 冻结 | ✅ PASS | §1.2 |
| R94 | composite momentum 非 0 | 检查 696 场内 ETF momentum=-0.193/-1.0/1.0 等真实值，11/26 degraded 全为场外联接 | ✅ PASS | §2.4 |
| R95 | 正文数值与结构化一致 | rule 兜底正文数值天然一致（covered_by_llm=0）；LLM 路径无法验证 | ⚠️ 受限 | §2.4 |
| R96 | valid_rate 数据可用性口径 | design 697 valid_rate=0.967 + ic_accumulation 38/250 | ✅ PASS | §2.4 |
| R97 | 个股搜索命中 | 茅台→sh600519、腾讯→00700、阿里→09988、苹果→AAPL、特斯拉→TSLA | ✅ PASS | §2.5 |
| R98 | global 桶 level≥3 摘要 | 5/5 非 null | ✅ PASS | §2.5 |

### 2.4 策略检查 696（R94/R87/R95 验收）

`POST /strategy-check-async` → task 696 completed（~90s，LLM 节流下完成）：

- ✅ R94：26 持仓中 15 只场内 ETF composite `momentum` 全有真实值（-0.281/-0.193/-1.0/1.0/-0.567/-0.37/0.551/0.09 等）；11 只 degraded 全是场外联接（022449/007467 等 0 开头代码，因子覆盖 0%，合理降级）。
- ✅ R87：summary「因子覆盖 38.5%」= report_text「分项覆盖 38.5%」，口径统一。
- ⚠️ R95：`covered_by_llm=0, covered_by_rule=26`（LLM 超时走 rule 兜底），report_text 由 rule 模板生成，数值直接引用结构化 factor_summary（如 512890 `KDJ.J 109.79（超买区）`），**天然一致**；但 LLM 正文的数值一致性（R95 核心验收）无法复现验证。

### 2.5 搜索 / 资讯 / 数据健康

- ✅ R97：`market=A&keyword=茅台` → sh600519（stock）；`market=HK&keyword=腾讯` → 00700；`market=HK&keyword=阿里巴巴` → 09988；`market=US&keyword=苹果` → AAPL；`market=US&keyword=特斯拉` → TSLA。
- ✅ R98：/news/global 8 条，level≥3 的 5 条全有 ai_summary（0 null）。
- ✅ data_health_check 10/10 PASS（stale cache 诚实降级标注：510300/512480/511090/518880 live data empty → stale cache）。

### 2.6 设计 697（R85/R96 验收 + R99/R100 实证）

`POST /design-async {capital:500000}` → task 697 completed（~80s），**design_id=681，report_quality=partial**（LLM 降级）：

- ✅ R96：`factor_data_quality={valid_rate:0.967, degraded:false, data_available:176, data_available_pct:0.967, ic_accumulation:{median_samples:38,target_days:250}}`——两维拆分生效。
- 🔴 R99：18 只 ETF 的 `factor_breakdown` **全部 20 键降级版**，`momentum=0.300` **18/18 全同占位**、`technical=0.0` 全同；rationale 引用「动量因子 +0.300」（512890 等）。对比 round31 design 652（full）momentum 真实差异化（+0.163/+2.659/+0.530）——**R85 在 partial 降级态回归**。
- 🟡 R100：factor_data_quality 报「数据可用率 97%」与 factor_breakdown 实际退化（20 键、momentum 占位）矛盾——口径脱节。

**根因链（R99，代码级定位）**：
```
factor_aggregate.py:81  CATEGORY_PREFIXES["momentum"] = ["etf.return_", "etf.change_pct", "china.policy.", "technical.signal."]
  → 盘后 etf.return_1m/return_3m/change_pct 全部 no_data（未产出，factor_breakdown 无这些键）
  → momentum 聚合唯一非零源 = china.policy.five_year_plan = 0.3（静态政策因子）
  → momentum = 0.3（18/18 全同占位）
  → build_rationale（engine/rationale.py）引用「动量因子 +0.300」
```
`china.policy.*`（五年规划/战略新兴/双循环，静态政策契合度）被误归入 momentum 聚合前缀，动量真实因子缺失时静态政策因子污染动量。

### 2.7 测试基线

- ✅ pytest：**2515 passed / 7 skipped**（round28 基线 2041，round31 2515）
- ✅ npm test：**499/499**（patrol L5-frontend PASS，含 build）
- ⚠️ patrol --full：exit 1（737.5s）——L1-unit PASS / **L2-e2e 270/287（17 FAIL）** / L2-health PASS / L2-smoke SKIP / **L3-perf timeline 1.23s 硬门禁 FAIL** / L4-routes+purity+async PASS / L5-frontend PASS
- ⚠️ verify_e2e 独立跑：271/287（16 FAIL），20 项 [FAIL] 归类：
  - **性能/负载伪失败（LLM 节流 + e2e 争池）**：design-async 15s 超时、策略分析提交超时、health 超时、watchlist 7.1s、timeline 1.2s、任务 695 running、ETF 记录数（设计任务失败连带）
  - **结构性（历史已知，round31 §2.6 已记载）**：M7 core=2（510050+512890）、etf_specific no_data=10（含 return_1m/3m，IC 积累期）、sentiment no_data=1、P1-1 宽基锚缺失、F7 卫星层 ≥4 只

### 2.8 前端 Lighthouse（软门禁）

| 页面 | 采样 | Performance | Accessibility | Best Practices | SEO | LCP | CLS | TBT |
|---|---|---|---|---|---|---|---|---|
| 首页 / | 第1次（原） | 71 ✅ | 96 ✅ | 96 ✅ | 91 ✅ | 3.0s ✅ | 0.001 ✅ | 560ms ⚠️ |
| 首页 / | 第2次（补采） | 76 ✅ | 96 ✅ | 96 ✅ | 91 ✅ | 3.1s ✅ | 0.001 ✅ | 400ms ✅ |
| 首页 / | **中位数** | **74** ✅ | 96 ✅ | 96 ✅ | 91 ✅ | **3.05s** ✅ | 0.001 ✅ | **480ms** ✅ |
| /dashboard | 第1次（原） | 98 ✅ | 100 ✅ | 100 ✅ | 91 ✅ | 2.3s ✅ | 0.001 ✅ | 30ms ✅ |
| /dashboard | 第2次（补采） | 98 ✅ | 100 ✅ | 100 ✅ | 91 ✅ | 2.2s ✅ | 0.001 ✅ | 50ms ✅ |
| /dashboard | **中位数** | **98** ✅ | 100 ✅ | 100 ✅ | 91 ✅ | **2.25s** ✅ | 0.001 ✅ | **40ms** ✅ |

- 补采时间：2026-08-20 22:46（prod profile :80，chrome-headless-shell `--headless --no-sandbox --disable-gpu`，与第1次同口径）。
- Performance/CLS 硬门禁全过；TBT 中位数 480ms（首页）/ 40ms（dashboard）**均 ≤ 500ms 参考阈值**——首页 560ms 单点 warn 被补采拉回达标。SI（补采新测）：首页 6.7s、dashboard 1.1s。
- 两轮各 2 次采样取中位数（模板要求 2 次采样）；「待补采」项已完成。原始报告：`data/lighthouse_home_2.json` / `data/lighthouse_dashboard_2.json`。

> 注：第2次运行末尾 `chrome-launcher` 清理临时 profile 目录报 `EPERM`（长路径 `\\?\C:\Users\...\Temp\lighthouse.xxxxx`），属报告生成后清理阶段的权限告警，不影响已落盘的 JSON 报告（已验证解析有效）。

---

## 3. 分析结果质量审查（阶段 3，四问法）

**审查对象**：设计 697（design_id 681）+ 策略检查 696 报告逐句四问。

### 判断质量矩阵

| 判断原文 | 事实/推断 | 数据支撑（file:line+数值） | 与当下行情一致? | 结论 | 修复建议 |
|---|---|---|---|---|---|
| 512890 rationale「动量因子 +0.300」 | 事实（factor_breakdown momentum=0.3） | fb.momentum=0.3，18/18 全同；round31 design 652 同标的 momentum 差异化 | ❌ 占位值冒充真实动量 | **失效→R99** | momentum 聚合剔除 china.policy.* |
| factor_breakdown technical=0.0（18 只） | 事实 | fb 20 键，technical.signal.overall=0.0 | ❌ 技术因子未产出 | **失效→R99** | 同上（技术因子盘后 no_data） |
| factor_data_quality「数据可用率 97%」 | 事实（valid_rate=0.967） | `_factor_data_quality_report` data_available=176/193 | ❌ 与 fb 实际退化矛盾 | **部分合理→R100** | 口径对齐实际 compute() 产出 |
| 「综合信号中性 +0.06」（512890） | 推断 | fb 聚合值 +0.06 | ⚠️ 基于占位 momentum 0.3 聚合 | 部分合理（依赖 R99） | R99 修复后复评 |
| 检查 696「因子覆盖 38.5%」三处一致 | 事实 | summary=report_text=38.5% | ✅ | 合理（R87 ✅） | — |
| 检查 696 场内 ETF composite momentum（-0.193 等） | 事实 | holdings composite_decision.components.momentum | ✅ 真实差异化 | 合理（R94 ✅） | — |
| 检查 696 场外联接 11 只 degraded | 事实 | 0 开头代码，因子覆盖 0% | ✅ 合理降级 | 合理 | — |
| 检查 696 正文「512890 KDJ.J 109.79（超买区）」 | 事实 | factor_summary 结构化值，与 /market/indicators 一致 | ✅ rule 直接引用 | 合理 | LLM 路径待补测 |

### 汇总

- **可采信 N=4** / **需修正 M=2**（R99 关联：动量占位、综合信号聚合）/ **失效 K=2**（momentum +0.300、technical 0.0 占位）/ **部分合理 K=1**（factor_data_quality 口径）
- **总体评价**：R85 的「真实差异化因子」在 **full 态**（round31 design 652）真实生效，但 **partial 降级态**（盘后 + LLM 降级）下因子数据退化为占位值，且 R96 的「数据可用率 97%」口径掩盖了退化——说明 R85 修复只覆盖了 full 态因子路径，降级态因子路径仍是占位兜底；R96 修了 valid_rate 的「误导呈现」，但「数据可用性」统计口径与实际 compute() 产出仍脱节。

### 数据准确性抽查

- 权重：设计 697 三方案 cash 24.1%/23.0%/9.5%（与 round31 design 652 相同），Σweights+cash≈1 ✅
- 占位检测：设计 697 `momentum=0.300` 18/18 全同 + `technical=0.0` 全同 → **占位值命中（R99）**；round31 design 652 无占位 ✅
- 新鲜度：设计 697 market_context index_realtime 有值（上证 3903.21 market_status=open 缓存未刷新）；fund_flow 全 0（akshare 熔断，诚实空）
- 相关性：设计 697 盘后 corr_matrix 缺失 → correlation_unchecked=True（诚实降级标注，非静默跳过）

---

## 4. 新发现问题（阶段 4，R99-R100）

### 4.1 R99（P1）— R85 在 partial 降级态回归：momentum 聚合误含静态政策因子

**症状**：设计 697（design_id 681，report_quality=partial）18/18 ETF 的 `factor_breakdown.momentum=0.300` 全同占位、`technical=0.0` 全同，rationale 引用「动量因子 +0.300」。round31 design 652（full）同场景 momentum 真实差异化。

**根因链**（代码级）：
```
factor_aggregate.py:79-84  CATEGORY_PREFIXES
  "momentum": ["etf.return_", "etf.change_pct", "china.policy.", "technical.signal."]
  → 盘后 etf.return_1m/return_3m/change_pct 全部 no_data（factor_registry.compute() 未产出）
  → momentum 聚合唯一非零源 = china.policy.five_year_plan = 0.3（静态政策因子，18 只全同）
  → momentum = 0.3（占位）
  → engine/rationale.py build_rationale 引用「动量因子 +0.300」
```
**性质**：`china.policy.*`（五年规划/战略新兴/双循环）是静态政策契合度，非动量因子，误归入 momentum 聚合前缀（`factor_aggregate.py:81`）。full 态（交易时段 etf.return_* 有值）被真实动量稀释不显；partial 降级态（盘后动量数据 no_data）静态因子独占动量聚合 → 占位污染。**代码级结构事实，但触发条件窗口依赖（盘后/动量数据缺失）**。

### 4.2 R100（P2）— factor_data_quality「数据可用性」口径与实际因子值脱节

**症状**：设计 697 `factor_data_quality.data_available=176/193（97%）`，但实际 factor_breakdown 退化为 20 键 + momentum 占位——97% 的「可用」掩盖了占位退化。

**根因**：`_factor_data_quality_report`（strategy_design.py:998-1058）R96 修复后的「数据可用性」统计口径 = 因子定义无 `_data_source_gaps`（定义层面），而 factor_breakdown 的实际值 = `factor_registry.compute()` 产出（计算层面）。盘后 K 线数据源不可用 → compute() 未产出 etf.return_* 等因子，但 `_data_source_gaps` 未标这些因子为「缺失」（K 线缓存可能有历史数据），导致「97% 可用」与「实际退化为占位」矛盾。

### 4.3 R101（P2）— O16 大盘宽基族互斥自相矛盾（用户决策）

**症状**：M7 门禁核心层 core=2（510050+512890 或 510300+588000）长期失败（round31 §2.6 + 本轮 e2e 复现）。追因发现 O16 互斥约束与强制锚设计自相矛盾。

**实测相关性（近 120 交易日日收益，kline_cache 实算）**：

| 配对 | 相关性 |
|---|---|
| 沪深300(510300) × 中证A500(159338) | 0.968 |
| 沪深300 × 中证500(510500) | 0.857 |
| 沪深300 × 上证50(510050) | 0.872 |
| 中证A500 × 中证500 | 0.935 |
| 沪深300 × 红利低波(512890)（对照） | 0.054 |

**根因链**（代码级）：
```
CORE_ANCHORS = {"510300", "159338"}（allocation_engine.py:235）——强制锚 = 2 只不同宽基指数（沪深300 + 中证A500，相关性 0.968），被强制并存
O16（allocation_engine.py:1192-1233）——核心层「非强制」大盘宽基 ≤1（defensive）/ ≤0（balanced/aggressive），超出按 factor_score 剔除
  → 同一套逻辑里「强制锚可 2 只不同宽基并存、非强制 1 只都不行」不一致
  → 核心层候选被 O16 剔除后只剩强制锚 2 只 → M7 core=2 失败
```
**性质**：O16 把「不同宽基指数」（沪深300/A500/上证50/深证100/中证800…）按「相关性 ~0.95+」一刀切成「同一大盘 beta」做互斥，粒度过粗。实测上证50×沪深300=0.872、上证50×中证500=0.696——不同指数间有真实差异化，非「同一指数」级别（同一指数家族切片相关性 ~0.99+）。**用户判断**：「同一指数才合并（M3 归一化该留），不同宽基指数没必要合并（O16 互斥该改）」——方向正确，且戳中「强制锚 2 只不同宽基并存 vs 非强制 1 只互斥」的内在矛盾。

**补充发现（O16 边界漏洞）**：O16 互斥边界（`allocation_engine.py:181-186`）仅限大盘/超大盘，注释明确「中证500 属中盘、科创50 属成长，均不在此列」；但实测中证500×沪深300=0.857、中证500×中证A500=0.935——中盘与大A联动显著强于注释假设，却**不在互斥范围内**，核心层可塞「沪深300+中证A50+中证500价值+中证500成长+中证500增强」这类高相关组合而 O16 管不到。

**用户决策（2026-08-20 收口）**：① 核心层宽基数量上限取 **≤4**（含强制锚）；② **中证500 纳入宽基识别**（覆盖上述边界漏洞，中盘高相关组合纳入上限计数）；③ R99/R100 采用 **A+B 双保险**（剔前缀 + 缺数据显式 None；口径对齐 compute() 实际产出 + 新增「实际产出率」字段）。据此 §5.1 方案已锁定。

---

## 5. 修复方案（R99-R101，只写方案，不写代码，等待「开始实施」）

### 5.1 修复方案总表

| ID | 级 | 方案 A / B + 推荐 | 影响范围（file:line） | 验收（含负向断言） |
|---|---|---|---|---|
| R99 | P1 | **A+B（已决策）**：**A** `CATEGORY_PREFIXES["momentum"]` 剔除 `china.policy.*`（政策因子归入独立的 policy 维度或直接不参与 momentum 聚合），momentum 聚合仅保留 `etf.return_*`/`etf.change_pct`/`technical.signal.*`；**B** momentum 聚合在源因子全 no_data 时返回 None（不设置 momentum 键），消费方显式标注「动量不可用」而非 0.3 占位 | `factor_aggregate.py:81`、`composite_signal.py` 消费处 | ①设计任务（含盘后 partial）momentum 不再恒 0.300；②**负向**：momentum 数据缺失时 factor_breakdown 无 momentum 键或显式 null，不得出现 0.300 全同值；③**负向**：china.policy.five_year_plan=0.3 不再进入 momentum 聚合（单测断言） |
| R100 | P2 | **A+B（已决策）**：**A** `_factor_data_quality_report` 的「数据可用性」改为统计 `factor_registry.compute()` **实际产出**的因子键数（对齐 factor_breakdown 真实值），非定义层 `_data_source_gaps`；**B** 同时新增「实际产出率」字段（compute() 产出键数 / 定义键数）与「定义就位率」并列 | `strategy_design.py:998-1058`、`factor_registry.py` compute() 返回处 | ①设计 697 类场景 data_available 与实际 factor_breakdown 键数一致；②**负向**：factor_breakdown 退化为占位值时 data_available 不得报 97% |
| R101 | P2 | **A（已决策；B 不采用）**：保留 M3 归一化（同一指数家族合并）；O16 从「互斥剔除」改为「数量上限 + 高相关提示」——核心层大盘宽基设数量上限（**≤4，含强制锚；中证500 纳入宽基识别**），相关性 >0.95 的配对（如沪深300×A500）给 `correlation_warnings` 提示「高相关、分散有限」而非硬剔除；B 方案（仅放宽互斥阈值 defensive ≤2 / balanced/aggressive ≤1）不采用 | `allocation_engine.py:1192-1233`（O16 互斥）、`:176-205`（宽基识别，扩展覆盖中证500）、`CORE_ANCHORS` 消费处 | ①核心层允许不同宽基指数并存（尊重「不同指数不合并」判断）；②M7 core ≥3 达成（核心层候选不再被 O16 剔到只剩强制锚）；③**负向**：核心层大盘宽基数量不超 4（防塞满高相关宽基）；④**负向**：沪深300×A500 等 >0.95 配对出现 correlation_warnings 提示（不静默） |

### 5.2 分批建议（不实施，等待指令）

- **批 1（P1 正确性）**：R99（momentum 聚合剔除静态政策因子 + 缺数据显式 None）。
- **批 2（P2 口径 + 设计侧校准）**：R100（factor_data_quality 实际产出率口径）、R101（O16 互斥 → 软约束 + 相关性提示）。
- **测试增强随批**：R99 负向「momentum 缺失无 0.300 占位」单测 +「china.policy 不入 momentum」单测；R100「data_available 与 compute() 产出键数一致」断言；R101「核心层宽基数量上限 + >0.95 配对 correlation_warnings」断言（含负向：宽基数量不超上限、高相关配对不静默）。
- **验证窗口**：R99 的「盘后 etf.return_* no_data 触发」需盘后复测；「momentum 聚合剔除 china.policy」代码级无窗口依赖。R100 无窗口依赖。R101 无窗口依赖（相关性实算基于 kline_cache，非实时行情）。

---

## 6. 测试防护体系缺口分析（阶段 4 强制）

### 6.1 防护体系现状（本轮实测）

| 层 | 状态 | 能抓到 | 抓不到 |
|---|---|---|---|
| 后端单测（2515 passed） | ✅ | R93-R98 的 46 个用例（data_dir 正则、momentum 跨路径、_reconcile、valid_rate 拆分、搜索兜底、global 摘要） | R99（momentum 聚合占位污染）——无「momentum 缺数据时不得 0.300」负向断言 |
| verify_e2e.py（271/287） | ⚠️ 16-20 FAIL（多为负载伪失败） | 设计/检查任务跑通、搜索命中、R92 字段 | 设计 697 的 momentum 占位——e2e 验「设计任务完成」「price 非 None」，不验「momentum 差异化」 |
| data_health_check（10/10） | ✅ | 数据源、因子方差>0.01、候选池 | 因子聚合占位污染 |
| patrol --full（exit 1） | ⚠️ L3-perf timeline 1.23s 硬门禁 | pytest/门禁/npm | 同上 |
| pre-commit 门禁 | ✅ | 密钥/路由/build/mypy/async/pytest | 同上 |
| 前端 npm test（499） | ✅ | 组件测试 | — |

### 6.2 逐发现映射

| 发现 | 最应拦截的防护层 | 为何未识别（file:line + 具体断言） | 应补的守卫（缺口类型） |
|---|---|---|---|
| R99 momentum 0.300 占位 | 后端单测 | 无「momentum 聚合剔除 china.policy.*」用例；R85 的负向断言（无「动量 +0.300 全同」）只在 full 态设计验证，未覆盖 partial 降级态 | **内容语义断言缺失**（聚合结果占位值检测） |
| R100 data_available 口径脱节 | 后端单测 + e2e | R96 的 valid_rate 用例验「valid_rate>0」，未验「valid_rate 与实际 compute() 产出键数一致」 | **内容语义断言缺失**（口径与实际产出对齐） |
| R101 O16 互斥与强制锚矛盾 | verify_e2e M7 门禁 | M7 core ∈[3,5] 已拦截「core=2」现象，但**归因到 O16 互斥剔除**的链条未在测试层显式断言——e2e 只验「core=2 失败」，不验「O16 剔除是否与强制锚矛盾」；宽基相关性（0.968/0.857）无测试层实测断言，靠代码注释「~0.95+」声称 | **内容语义断言缺失**（约束自洽性 + 相关性实测断言） |

### 6.3 系统性根因归并

1. **降级态因子路径无占位检测**（本轮新出现）：R85 的「真实差异化因子」只在 full 态验证，partial 降级态（盘后 + LLM 降级）的因子路径仍可退化为占位值，且无守卫拦截。与 R96 同源：因子数据质量的门禁集中在「呈现层」而非「计算层实际产出」。
2. **统计口径与计算产出脱节**（本轮新出现）：R96 修了 valid_rate 的「误导呈现」，但「数据可用性」统计定义层（_data_source_gaps），与实际 compute() 产出脱节——门禁验证「口径正确」而非「口径对应真实数据」。
3. **设计约束的自洽性无测试层断言**（R101，本轮新出现）：O16 互斥与强制锚（2 只不同宽基并存）矛盾、O16 边界漏中证500——这些是「约束逻辑」缺陷，现有测试验「结果符合门禁」（core=2 FAIL），不验「约束本身是否自洽/是否覆盖高相关中盘」。宽基相关性靠注释声称（~0.95+），无 kline_cache 实测断言。

**总体评价**：防护体系结构性缺「因子计算层实际产出的占位/退化检测」与「设计约束自洽性断言」两层——现有守卫验「因子值非空」「因子方差>0.01」「valid_rate 口径」「core 数量」，但都未验「聚合结果是否被静态/占位因子污染」「约束是否与强制锚自洽」「相关性声称是否有实测支撑」。

### 6.4 补齐设计（只写方案）

**守卫 S1（拦截 R99）**：新增单测——momentum 聚合在源因子（etf.return_*）全 no_data 时，结果不得为 0.300 全同占位（要么 None、要么显式「动量不可用」）；china.policy.five_year_plan 不参与 momentum 聚合。
- 方案 A：`test_factor_aggregate.py` 增用例，构造「etf.return_* 缺失 + china.policy=0.3」输入，断言 momentum 聚合结果 ≠ 0.3（或不存在 momentum 键）。
- 方案 B：verify_e2e 增「设计任务 factor_breakdown momentum 差异化」断言（≥2 个不同值，非全同 0.3）。
- 推荐 A（单测更快更准，B 受 e2e 负载 flaky）。
- **负向**：守卫后，同类「静态因子污染聚合」必 FAIL；但不得为数据源环境偶发加过度断言（盘后动量缺失是真实状态，守卫应验「占位值」而非「动量必须有值」）。

**守卫 S2（拦截 R100）**：`_factor_data_quality_report` 增「实际产出率」字段 = compute() 产出键数 / 定义键数，与「定义就位率」并列；单测断言两者一致（或实际产出率 ≤ 定义就位率且差异可解释）。
- 方案 A：在 R96 的 valid_rate 单测基础上增「产出率」断言。
- 方案 B：verify_e2e 增「设计 factor_data_quality 与实际 factor_breakdown 键数一致」断言。
- 推荐 A。
- **负向**：factor_breakdown 退化时 data_available 不得报 97%。

**守卫 S3（拦截 R101）**：核心层大盘宽基约束自洽性断言——（a）O16 互斥/数量上限与强制锚不矛盾（允许不同宽基并存，但数量有上限）；（b）宽基相关性实测断言（kline_cache 实算，非注释声称）；（c）>0.95 配对出现 correlation_warnings 提示。
- 方案 A：`test_allocation_engine.py` 增用例——构造「沪深300 + 中证A500 + 上证50」三只不同宽基入核心层，断言（软约束后）不被全部互斥剔除、数量不超上限、>0.95 配对有 warning。
- 方案 B：verify_e2e 增「M7 core 达标 + 宽基相关性提示」断言。
- 推荐 A。
- **负向**：约束软化后核心层不得塞满高相关宽基（数量上限守卫）；沪深300×A500 配对必须有 correlation_warnings（不静默）；但不得为「不同指数并存」加过度断言（允许 2 只不同宽基并存是用户决策，守卫验「上限」而非「互斥」）。

---

## 7. 多轮 review 记录（阶段 5，Round 1-3）

- **Round 1（实证 + 根因定位）**：逐条对照运行时输出。R99 经设计 697（design_id 681）factor_breakdown momentum=0.300 18/18 全同 + technical=0.0 实证，根因定位 `factor_aggregate.py:81` momentum 前缀含 `china.policy.*`；R100 经设计 697 factor_data_quality data_available=176/193 与 factor_breakdown 20 键退化矛盾实证；R101 经 kline_cache 实测相关性（沪深300×A500=0.968、沪深300×中证500=0.857、上证50×沪深300=0.872）+ M7 core=2 复现，根因定位 O16 互斥与 CORE_ANCHORS 强制锚矛盾。R93-R98 逐项复测：R93 容器 data_dir 绝对路径、R94 检查 696 composite momentum 真实值、R96 valid_rate=0.967、R97 全市场个股搜索、R98 global 摘要 5/5。
- **Round 2（file:line 复核 + 一致性）**：确认 `factor_aggregate.py:79-84`（CATEGORY_PREFIXES momentum 前缀）、`:81`（china.policy. 误含）、`engine/rationale.py`（build_rationale 消费 factor_breakdown）、`strategy_design.py:998-1058`（_factor_data_quality_report）、`strategy_design.py:459-474`（build_rationale 调用点）、`allocation_engine.py:176-205`（_LARGE_CAP_WIDE_BASIS_KEYWORDS/_is_large_cap_wide_basis）、`:235`（CORE_ANCHORS）、`:1192-1233`（O16 互斥）锚点与代码一致。前端镜像 `a4b6c8d26c9f`（19h 前）复用安全论证（生产代码零变更，仅 test 文件改动）成立。
- **Round 3（完整性 + 窗口标注）**：R99 标注「代码级结构事实 + 盘后触发条件」双维度；R100 标注无窗口依赖；R101 标注「用户决策 + 无窗口依赖（相关性实算基于 kline_cache）」；R95 标注「LLM 配额耗尽受限验证，待恢复补测」；Lighthouse 采样 1 次标注「待补采」；e2e 16-20 FAIL 归因区分（负载伪失败 vs 结构性历史已知）。

---

## 8. 待交易时段/美股时段复测项

- **R99 交易时段复测**：交易时段内 etf.return_* 有值，momentum 聚合被真实动量稀释，占位不显——需在交易时段确认「剔除 china.policy.* 后 momentum 仍正确聚合真实动量」。
- **R95 LLM 正文路径**：LLM 配额恢复后触发策略检查，验证 `_reconcile_report_numbers` 对 LLM 正文的数值一致性覆盖。
- **美股（AAPL/TSLA/SPY）**：本轮盘后，realtime/indicators 标「待美股时段复测」。
- **Lighthouse 补采**：首页/dashboard 各补 1 次采样，取中位数 → **已完成（2026-08-20 补采）**，见 §2.8 更新。

> **当前状态**：仅诊断 + 方案设计，**未实施**。等待「开始实施」指令（R99-R101 修复 + 守卫 S1/S2/S3）。R101 设计侧参数已锁定（上限 ≤4 / 中证500 纳入宽基识别 / A 方案）。R99·R100 采用 A+B 双保险。
