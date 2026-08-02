# ETF Surge — 第五轮全链路诊断与优化修复方案 (v1.0)

> 诊断环境：Docker prod 集群（backend :8000 / frontend :80 / redis :6379），镜像 `etf_surge-backend:latest (58d441568575)`、`etf_surge-frontend:latest (67ef197df43c)`，2026-08-02 构建（工作树 HEAD `0ee4882`）。
> 诊断方法：预热 profiler（PROFILE_WARMUP=1）、组合设计/策略检查实测（LLM opencode_zen 主 + deepseek 备）、A/HK/US 全链路 API 实测、Lighthouse 13.4.1、verify_e2e 全量 22 模块、契约系统排查、代码级修复状态核查。
> 状态图例：🔴 严重 / 🟡 中 / 🟢 正常
> 本方案为**实施标准设计**，按 AGENTS.md 契约先行 + TDD 流程执行；本轮**不实施**。
> **诊断配置回收**：docker-compose.yml 为诊断临时启用的 `PROFILE_WARMUP=1` 与 `./backend/logs:/app/logs` volume，**回收容器时一并移除**（恢复生产默认，见 §十三）；`LOG_LEVEL=INFO` 保留（与 dev profile 的 R4 决策对齐，收窄生产日志级别省预热开销）。

---

## 一、执行摘要

本轮（round5）在 Docker prod 环境完成 15 项诊断动作。核心结论：

1. **round4 大量修复已生效**：R4-11 前端 4 处弱断裂全修复、R4-18 verify_e2e 门禁自检恢复（264/278 正常打印总结并 exit 1）、R4-21 场外盈亏口径修复（-21.44% → -0.89%）、P1-4 今日涨跌降级显式化、P1-5 FRED 海外流动性注入、P1-7 A 股个股灌库（5533 行）、R4-05 batch 逗号分隔、R4-25/26/27/28 前端与搜索修复、P0-2 HK/US 指数过滤（详见 §四/§七）。
2. **仍有 4 项严重问题未修复**：R5-01 设计真实链路 A500 未入核心（P1-1 门禁 FAIL）、R5-02 核心层跨方案重叠（P1-2 门禁 FAIL）、R5-03 首页 Lighthouse P56/CLS 0.388（R4-19/P1-8 未实施）、R5-04 组合计算仍 5.1s（P2-1 未达标）。
3. **3 项中等问题**：R5-05 LLM 主 provider 429 限流导致设计任务失败/策略检查降级、R5-06 sentiment/etf_specific 因子 no_data（F19 未实施）+ IC 仅请求驱动、R5-07 llm-advice 上下文注入关键词覆盖不全。
4. **测试防护体系**：verify_e2e 已能抓住 P1-1/P1-2（本轮 14 FAIL 中 2 项为设计质量门禁），但**单测 mock 候选池与真实候选池结构脱节**（mock 池含 560600、真实池被 MAX_PER_LAYER 截断）是 P1-1"修了但没生效"未被发现的核心根因（详见 §九）。

---

## 二、诊断环境与方法（步骤 0-1）

| 项 | 值 |
|---|---|
| Docker 镜像 | etf_surge-backend:latest (58d441568575)、etf_surge-frontend:latest (67ef197df43c)（旧镜像已回收） |
| 容器 | backend-1 :8000 / frontend-1 :80 / redis-1 :6379，/health 200 |
| 后端诊断工具 | 内置 WarmupProfiler（cProfile + pyinstrument + 分段计时），PROFILE_WARMUP=1（docker-compose prod backend 临时配置 + ./backend/logs volume 暴露报告；回收时移除） |
| 前端诊断工具 | Lighthouse 13.4.1 + Chrome（本地全局安装） |
| E2E 门禁 | verify_e2e.py 全量 22 模块组（264/278 通过、14 FAIL、exit 1） |

## 三、后端预热性能诊断（步骤 1）

**总时长 3357ms（3.36s）**（round4 2.47s；门禁 20s，✅ 远低于失败线）。

| 分段 | 耗时 | 占比 | 对比 round4 |
|---|---|---|---|
| warmup_market_cache | 2095ms | 62% | 2244ms → 基本持平 |
| warmup_global_indices | 1089ms | 32% | **3.9ms → 1089ms（新增热点，round4 为缓存命中/快速失败，本轮冷拉 17 项全球指数 1.09s）** |
| init_db | 55.8ms | 2% | 76.6ms → 略降 |
| redis_init | 84ms | 2% | 74.5ms → 持平 |
| warmup_etf_cache | 32ms | <1% | 73.9ms → 持平（file cache hit） |

**热点**（pyinstrument）：`warmup_market_cache → get_portfolio_realtime → _call → run_sync 同步等待 1.015s`（外部慢源超时截断已生效，P2-1 的 wait_for 3s 截断在预热路径复用）；`_foreign 0.089s`（全球指数 CPU 部分，剩余 1s 为网络等待）。

**结论**：预热 3.36s 远低于 20s 失败线 ✅；新热点 `warmup_global_indices` 冷拉 1.09s（round4 缓存命中仅 3.9ms）——非交易时段东财指数源慢响应，属数据源时序波动；`get_portfolio_realtime` 内 1.0s 同步等待为持续热点（P2-1 修复不彻底，见 R5-04）。

## 四、组合设计 + on_exchange 策略检查审阅（步骤 2）

### 4.1 执行结果与失败定位

- **design task 132 首次失败**（"方案生成超时，数据源响应过慢"，stage 停在"数据采集与策略计算中"，45s 超时）。结合后端性能日志定位根因链：
  1. **LLM 主 provider（opencode_zen）持续 429 Too Many Requests**（13:02-13:04 多次，含预热期 3 次 + 我并发提交 strategy-check 133 争抢配额）；
  2. design pipeline DATA 阶段 45s 预算（task_manager.py:291 OPT-06）在数据源慢 + run_sync 池饱和（queue depth 9-10）叠加下耗尽；
  3. 策略检查 133 同因走 LLM 60s 超时 → rule 兜底（诚实降级，任务 completed）。
  - **处置**：等限流缓解后重试，task 134 成功（75s，completed，design 352）。
- **design 352（capital=500k）**：三套方案（防御/平衡/进攻）层预算完整、现金 15%、报告 full。候选池仅 **14 只**（core 8/satellite 4/defense 2 左右，正常应 8+20+10+…）——数据源故障期池缩小，方案选择空间受限。
- **strategy-check 133（on_exchange）**：completed，report_text 完整（2965 字，逐标的表格 + 风险提示 + 操作建议分标的分段），suggestions 10 条（9 hold + 1 increase），risk_warnings 1 条（LLM 超时 warning 级 + 降级标注）。

### 4.2 报告质量审阅（结合最新行情，专业投资者视角）

**设计 352**：
- ✅ 市场环境段数据准确：创业板指+3.1%/科创50+3.0%/深证成指+2.2%/上证+0.7%；韩国+17.9%/日经+4.0%（与 R4-07 确认的真实行情一致）；恒生国企-0.4%。
- ✅ 市态 range_bound（震荡）正确传递；情绪指数 45.0 中性；三层框架（核心守正/卫星出奇/防御托底）逻辑清晰；配置建议"先再平衡，不因单日大涨改变节奏"合理；风险提示（高弹性品种追高、30 年国债久期）与量化操作纪律（企稳判定/急跌加仓/止损红线）具体可执行。
- ✅ P1-4 已实施：今日涨跌列显示"数据源不可用"（非空"—"）；P2-6 已实施：预期年化==当前预期年化附显式说明（"震荡市态调整系数为 0，属设计行为"）。
- ⚠️ 见 R5-01/R5-02（方案结构问题）。

**策略检查 133**：
- ✅ 三段式 reason（触发依据/操作节奏/风险纪律，R4-22 生效）；report_text 完整（N01 保持）；LLM 超时诚实降级（summary 标注 + risk_warnings warning 级）。
- ⚠️ **holdings_analysis 恒为空**（rule 兜底路径不产出持仓分析）→ 行业集中度检查在兜底路径被静默跳过（无"仅覆盖1个行业"误报，但**也没有任何行业分布分析**）——P0-1 的"空行业保护"以"无数据"形态达成，非注入达成。
- ⚠️ 10 条建议 9 hold + 1 increase：LLM 超时时 B3 验收"非清一色 hold"勉强达标（2 种动作），但 hold 占比 90% 仍偏高（rule 决策表对中性因子分一律 hold）。

### 4.3 专业投资者总评

设计报告逻辑/可读/数据自洽性良好，**但方案结构未达 round4 验收**（A500 缺失 + 核心层重叠）且行情数据源降级（今日涨跌全缺）——**当前不建议直接采信方案结构**，须先修复 R5-01/R5-02。策略检查在 LLM 可用时可信（数据 10/10、建议带因子依据）；LLM 429 期间输出仅为规则兜底，参考价值有限。

## 五、多市场行情分析（步骤 3）

| 链路 | 结果 | 备注 |
|---|---|---|
| A 综合研判 llm-report | ✅ 62.7s | 数据准确（与设计报告一致）；**P1-5 海外流动性段已注入**（美债10Y 4.68%/VIX 17.09/联邦基金利率 3.63%） |
| HK 综合研判 llm-report | ✅ 26.3s | **P0-2 生效：无 A 股指数混入**；但"港股、美股、大宗商品今日暂无数据"——HK 指数源缺失（数据源，诚实降级） |
| US 综合研判 llm-report | ✅ 32.7s | P0-2 生效无 A 股指数；美股指数"暂无数据"（数据源） |
| AI 投顾问答 llm-advice | 🟡 | **R5-07：注入关键词过窄**——"当前A股市场怎么配置？"不命中"大盘/今天/最新/走势/行情"任一关键词 → 无 market_snapshot 注入 → 回答全"暂无数据"降级模板，不可采信 |
| 个股分析 600519 | ✅ 48.5s | 技术面完整；基本面 PE/PB"数据源不可用"标注（P1-3 注入链存在，akshare 源不可用） |
| ETF 分析 510300 | ✅ 26.7s | 同上 |
| 港股分析 513010 | ✅ 138.4s | 实时行情空 → 以最近日 K 收盘价 0.628（2026-07-31）为基准，诚实降级 |
| 美股分析 513500 | ✅ 57.9s | 产品属性分析完整 |
| 板块分析半导体 | ✅ 46.6s | 成分股结构（模拟芯片/SoC/设备/封测/IP）完整 |
| 概念分析 AI | ✅ 32.6s | 含《新闻联播》资讯催化（8/2 上半年电子信息制造业数据） |
| 指数分析沪深300 | ✅ 31.9s | 估值缺失标注 + 宏观产业信号 |
| 搜索补全 | ✅ | 代码/中文/拼音全通（510300 1 条、茅台 1 条、huangjin 10 条、恒生科技 12 条）；A 股个股（P1-7 生效）、HK 个股（腾讯 1 条）；US 个股（apple）0 条——akshare spot 源不可用（R4-26 失败缓存 1h 生效） |

**专业投资者视角**：AI 输出整体逻辑严谨、诚实降级到位（无数据不捏造）；HK/US 报告纯净度修复（P0-2）✅；**R5-07（AI 投顾无上下文）与数据源降级（PE/PB、HK/US 指数缺）直接削弱投顾可信度**——投顾问答当前不可采信，综合研判可信但数据完整性受数据源影响。

## 六、热点/自选/技研/资讯/因子（步骤 4-8）

- 热点板块 11 个（AI应用/机器人/算力/芯片等）✅、热门个股 50 只（利欧/天娱/蓝色光标等，涨跌幅真实）✅、sectors/heat 20 项（含 change_pct 字段，R4-11-1 ✅；值为 None 系数据源）。
- 自选 A/HK/US 添加 201 + 列表实时价回显 ✅（510300 4.653/腾讯 475.2/AAPL 308.91/茅台 1350.6）。
- 持仓技研 10 只 indicators 完整（RSI/MACD/KDJ），signal 与策略检查一致（513010 buy→increase、159338 sell→hold、159516 弱 RSI 31.2→hold）✅。
- 资讯等级分布合理（headlines 30 条 level 1×3/2×13/3×5/4×7/5×2；global 8 条 level1）✅；news-impact 智能分析质量良好（impact_scope 方向/板块/概念结构化 + affected_holdings **100% 属于当前组合**，F14 过滤生效）。
- 因子：factors/active total=33、**valid=21/no_data=7**（round4 19 valid/11 no_data → 改善；style 2 因子已修复）；**sentiment 4 因子仍全 no_data**（R5-06）；etf_specific 5 valid/2 warn/3 no_data。
- **factors/ic 冷启动返回 0 条**——`_last_ic_batch` 仅请求驱动更新（R1"后台周期 compute"未实施）；verify_e2e 跑完（触发 compute）后 19 条。**B1 验收（valid≥10 且非请求驱动）未达标**。

## 七、前后端数据断裂排查（步骤 9）

- ✅ **R4-11 四处弱断裂全部修复**（代码 + 运行时字段双重验证）：SectorHeatMap change_pct（后端 heat item 已有该字段）、AnalysisView KDJ/RSI 子图（chart 数据含 kdj/rsi）、FactorICView 分类选项（china_specific/etf_specific）、FactorModelView tooltip（factor entry 含 category 字段）。
- ✅ 其余 20+ 链路字段契约一致（R4-12 维持）。
- 🟡 R4-06 news/stock 键归一化**部分修复**：返回键含 title/content/time/url（英文键已加）但**中文键"关键词/文章来源"残留**（双键并存，契约仍不一致）。

## 八、docs 问题清单验证（步骤 10）

### 8.1 round4 findings（R4-01~R4-29）+ plan P0-P3 验收

| 项 | 状态 | 证据 |
|---|---|---|
| P0-1 策略检查行业注入（R4-01） | 🟡 部分 | rule 兜底路径 holdings_analysis 恒空 → 行业检查被跳过（无误报但也无分析）；LLM 路径注入逻辑在（portfolio_service.py:659-665） |
| P0-2 HK/US 指数过滤（R4-13） | ✅ 修复 | HK/US llm-report 实测无 A 股指数（_filter_indices_for_market 生效） |
| P0-3 verify_e2e 自检（R4-18） | ✅ 修复 | 全量跑完正常打印"264/278 通过"并 exit 1（不再 UnboundLocalError 必崩） |
| P1-1 核心层含 A500（R4-15） | 🔴 **FAIL** | 三方案核心层均无 560600/159338；verify_e2e design-quality 门禁同判 FAIL（R5-01） |
| P1-2 核心层重叠 ≤1（R4-14） | 🔴 **FAIL** | 平衡∩进攻重叠 3 只 [159915, 562000, 588000]（剔除公共底仓后）；门禁同判 FAIL（R5-02） |
| P1-3 个股分析基本面注入（R4-09） | ✅ 修复（数据源受限） | asset_type 归一化 + PE/PB 注入链在（routers/analysis.py:734-775）；akshare 源不可用时显式标注"数据源不可用" |
| P1-4 今日涨跌降级显式化（R4-02） | ✅ 修复 | design 352 表格显示"数据源不可用"（非"—"） |
| P1-5 海外流动性接入（R4-23） | ✅ 修复 | A 综合研判含美债 10Y 4.68%/VIX 17.09/联邦基金利率 3.63% |
| P1-6 场外盈亏口径（R4-21） | ✅ 修复 | pnl-history 总盈亏 -0.89%（round4 -21.44%）；019633 半导体联接C +3.08%（round4 -81%）；黄金联接C +0.87%（round4 +179%） |
| P1-7 个股搜索本地化（R4-29） | ✅ 修复 | instruments 7093 行（stock A 5533）；搜"茅台"命中 sh600519 1 条 |
| P1-8 首页 CLS（R4-19） | 🔴 **FAIL** | Lighthouse 首页 P56/CLS 0.388（未达 ≥60/≤0.1；R5-03） |
| P2-1 组合计算 ≤3s（R4-16） | 🔴 **FAIL** | /portfolio/calculate 5.10s（round4 5.1s，无改善；R5-04） |
| P2-2 realtime/batch 契约（R4-05） | ✅ 修复 | symbols=510300,510880,518880 返回 3 条 |
| P2-3 news/stock 键归一化（R4-06） | 🟡 部分 | 英文键已加，中文键残留（双键并存） |
| P2-4 前端 4 处弱断裂（R4-11） | ✅ 修复 | 见 §七 |
| P2-6 预期收益显式化（R4-03） | ✅ 修复 | design_text 显式说明"震荡市态调整系数为 0" |
| R4-25 技术分析弹窗（前端） | ✅ 修复 | signalText 改 computed + reasons 渲染（代码验证） |
| R4-26 搜索提速 | ✅ 修复 | 稳态 0-16ms（失败缓存 1h 生效） |
| R4-27 指数代码泄露 | ✅ 修复 | llm.py 指数行 lstrip('^')（代码验证） |
| R4-28 研判 tab 切换 | ✅ 修复 | MarketReport.vue watch + genSeq 序号守卫（代码验证） |
| P3-1 tasks/designs 列表 | 🟡 未实施（暂缓） | tasks 572ms / designs 570ms |
| P3-3 watchlist 提速 | 🔴 未实施且劣化 | 4525ms（round4 首次 2.27s） |

### 8.2 combination-design-review 验收（A 系）

| 验收 | 结果 | 证据 |
|---|---|---|
| A1 核心层 3-4 只/单只 ≥5% | ✅ | 防御 4 只、平衡/进攻 5 只（510300 5.19% 压线） |
| A2 核心层含 A500 与沪深300 | 🔴 FAIL | 三方案均无 560600/159338（R5-01） |
| A3 中证500家族 ≤1 | ✅ | 平衡 core 仅 510500 1 只 |
| A4 卫星层无宽基 | ✅ | 卫星=科创主题+红利低波（562000 在核心层而非卫星） |
| A5 无"required 未命中"WARNING | ✅ | 日志仅 WideBasisInject 注入成功 |
| A6 强制标的 560600 必须出现（M7⑤） | 🔴 FAIL | 560600/159338 均未出现在任何方案（含核心/卫星/防御） |
| A8/A9 标题唯一/无空行堆叠 | ✅ | design_text "## 一、三种方案详解" 1 次 |
| A12 今日涨跌真实或显式降级 | ✅ | "数据源不可用" |
| M1 红利类合计权重 ≤15% | 🔴 FAIL | 防御 core 563020=16.96%、进攻卫星 563020=16.43% > 15% |

> 注：combination-design-review 验收总表 A7/A10/A11 三项（A7=单测断言、A10=理由列≤80字、A11=名称无截断）本轮未逐项实测——A7 属单测范畴（代码存在 test_allocation_engine_fixes.py 等 allocation 相关单测但未在本轮运行复验），A10/A11 需人工走查 design_text 渲染效果（理由列存储已截断显示"…"，精确字数与名称截断未量化）；三项复验已列入 §十二 验收总表 R5-0-5。

### 8.3 factor-and-strategy-check-review 验收（B 系）

| 验收 | 结果 | 证据 |
|---|---|---|
| B1 因子 valid≥10 且非请求驱动 | 🔴 FAIL | valid=21 达标，但 **IC 仅请求驱动**（R1 后台周期 compute 未实施，冷启动 /factors/ic=0） |
| B2 策略检查无"先完成再停留 loading" | 🟡 前端代码有 registerTaskCompletion 对称逻辑（未做浏览器实测） | — |
| B3 LLM 超时建议 ≥2 种动作 | 🟡 勉强 | 9 hold + 1 increase（2 种动作，hold 占比 90% 仍高） |
| B4 LLM 超时风险提示 warning 级+标注 | ✅ | risk_warnings "LLM 分析超时，风险提示基于规则引擎部分数据，完整性受限" |
| B5 数据可用时 hold 占比 <80% | 🟡 本次 LLM 超时无法判定（rule 兜底路径 hold 90%） | — |

## 九、测试防护体系分析（步骤 13）

### 9.1 本轮 14 个 verify_e2e FAIL 归因

| FAIL | 根因类别 |
|---|---|
| P1-1 A500 未入核心 / P1-2 重叠 3 只 | **单测 mock 池与真实池结构脱节**（见 9.2） |
| 候选池 0 / ETF 数据缺失×4 / 热门个股 0 / 池健康 None | 数据源熔断（非交易时段 + akshare/东财不可用）——真实反映，门禁正确 FAIL |
| shared_executor 64/64 | 线程池饱和（性能回归，verify_e2e 新增强的运行时检查抓到了） |
| etf_specific no_data=5 / sentiment no_data=4 | F19（R68-R72）未实施——内容语义断言（门禁已加） |
| LLM llm-report 30s 超时 | 外部依赖慢/限流（门禁正确 FAIL，阈值 30s 合理） |
| 20 只持仓全估算（无 avg_cost） | 数据录入缺失，非系统 bug |

### 9.2 核心根因：P1-1/P1-2"修了但没生效"为何未被识别

- **实施时验证路径**：allocation_engine 单测（test_allocation_engine.py）用 **mock 候选池**（560600 直接出现在 core 候选里）→ 断言"核心层含 A500"通过 → 声称修复。
- **真实链路**：560600 经 `etf_scanner.full_pipeline` 注入 core（WideBasisInject ✅ 日志）后，被 `market_data_hub._refresh_impl` 第 6 步 **`MAX_PER_LAYER[core]=8` 截断 + `_balance_by_industry` 挤出**（`_ensure_mandatory` 在截断**前**执行，截断后无二次校验）→ 候选池实际无 560600 → 引擎 `MANDATORY_CODES` 强制注入无从触发。
- **盲区**：①单测 mock 的池结构（含 560600）≠ 生产池结构（截断后不含）；②M2 的"required 未命中 WARNING"校验只在 etf_scanner 层，market_data_hub 截断后无校验点；③verify_e2e design-quality 门禁需真实生成 design（LLM 依赖、耗时长），round4 实施验证疑似未在真实链路复跑。

**对照 round4 test-gap-analysis 六类根因**：R5-01/R5-02 是第 1 类（内容语义断言缺失）的**未收敛实例**——门禁已补（M7/P1-1/P1-2 断言在 verify_e2e），但**实施验收环节未执行真实链路复验**；本轮新增根因类别：**测试数据（mock 池）与生产数据管道（候选池组装/截断）结构脱节**。

### 9.3 防护体系现状

- ✅ verify_e2e 门禁自检恢复（P0-3）：正常打印总结 + exit code 一致（264/278、14 FAIL）。
- ✅ design-quality 门禁能真实抓住 A500 缺失/重叠超标（本轮 FAIL）。
- ❌ 单测对"数据管道级"缺陷无覆盖（mock 池绕过了 MAX_PER_LAYER 截断逻辑）。
- ❌ F19 因子 no_data 无后台 compute 修复（R1 未实施），B1 验收（非请求驱动）未落地。
- ❌ LHCI 门禁仍**未接入 CI**（round4 R4-19 遗留）：本轮 Lighthouse 仍是手动跑，P56/CLS 0.388 无自动化拦截。

## 十、优化修复方案（P0-P2）

> 按 AGENTS.md 契约先行 + TDD 流程执行；本轮**不实施**。

### 🅿️0 阻断性（专业投资者可信度）

**R5-0-1：候选池强制标的二次校验（P1-1 真实链路失效根因）**
- `market_data_hub._refresh_impl`：`_ensure_mandatory` 从"截断前"移到"截断后"（L535 → L544 之后），并在截断后对 `MANDATORY_CODES ∪ CORE_REQUIRED` 做二次校验（缺失 → 从 flat 找回注入 + WARNING，与 etf_scanner 层 `_log_missing_required` 对齐）。
- 或在 `MAX_PER_LAYER` 截断时**保护强制标的**（`balanced[:max_n]` 前先剔除 MANDATORY_CODES，截断后再补回）。
- 验收：`get_pool("core")` 恒含 560600/510300（数据源可用时）；verify_e2e design-quality 的 A500 断言 PASS（真实 design 复验，非单测 mock）。

**R5-0-2：核心层跨方案重叠修复（P1-2 真实链路复验）**
- 在 allocation_engine 现有 `_prev_core_used` 去重逻辑（L554-565）基础上，补"兜底放宽"分支的回归用例：`_deduped_non_mandatory < 2` 时允许重叠的**豁免范围**应仅限"公共底仓 + 强制标的"，不能整体放开（当前 balanced/aggressive 重叠 3 只说明豁免过宽）。
- 验收：真实 design 三方案任意两两核心层重叠（剔除公共底仓与强制标的）≤1；verify_e2e diversity 门禁 PASS。

**R5-0-3：首页 CLS 修复（P1-8 实施）**
- 已定位：Dashboard `summary-grid`（指标卡容器，top 1489px 高 725px）无固定 min-height，数据注入后高度 0→725px 导致 CLS 0.388。
- 实施：指标卡容器按内容上限预留 min-height（或骨架屏定高）；WS 行情推送改 `transform` 避免重排（P1-8 子步骤 2 原方案）。
- 验收：Lighthouse 首页 3 次采样中位数 P≥60、CLS≤0.1；LHCI 配置接入 CI（`npx lhci autorun`）。

**R5-0-4：红利类权重上限约束（M1 收敛，用户决策 D1）**
- 现象：防御 core 563020 红利低波 16.96%、进攻卫星 563020 16.43%，均超 M1 红利类上限。
- 决策范围说明：用户决策 D1 原文为"防御型方案红利类权重上限 15%"；本方案**扩展为全方案校验**（平衡/进攻卫星层红利类同样收 15%）——实施时按此口径，并在实施记录中注明扩展决策（如需严格回到 D1 原文，仅约束防御型，则 8.2 表 M1 行需相应调整 FAIL 判定）。
- 实施：allocation_engine 分配后校验红利类（tracked_index 含"红利"或名称含"红利"）合计 ≤15%，超出时按比例下调并补足同层其他标的；risk_controls 补红利专项约束（行业集中度已有，红利类横跨核心/卫星两层，需层间合计校验）。
- ⚠️ 既有单测 `test_defensive_dividend_cap_15`（test_allocation_engine_fixes.py:203）**仅覆盖防御型核心红利上限**（自带候选含 512890/515080 红利 ETF，防御型超 15% 时会 FAIL）——**未覆盖平衡/进攻卫星层红利约束**（本轮真实 FAIL 恰在进攻卫星 563020 16.43%），且真实链路选中的红利标的 563020 不在 mock 候选里（§九 9.2 "mock 池与真实池结构脱节"盲区的实例）；实施时补全方案（卫星层）用例 + 将 563020 纳入 mock 候选。勿向 `_base_candidates` 注入红利标的（会波及共用该池的 M4 测试）。
- 验收：真实 design 三方案红利类合计 ≤15%（verify_e2e design-quality 新断言）。

**R5-0-5：combination-design-review A7/A10/A11 复验（补测项）**
- 实施批次复验三项：A7（allocation 单测断言：中证500家族只选 1 只/卫星不足 4 只不混宽基/强制标的缺失行为（不静默成功）——运行 test_allocation_engine_fixes.py 确认存在且通过）、A10（design_text 理由列 ≤80 字：量化检查存储字符串）、A11（名称无截断：设计报告名称列无 "…" 截断残句）。
- 验收：三项复验结论记入实施记录，A10/A11 不达标时并入 F3 R4/R5 修复。

### 🅿️1 高优先级

**R5-1-1：LLM 429 限流治理（R5-05）**
- 现象：opencode_zen 预热期 3 次调用 + 任务并发 → 429；设计任务 45s DATA 超时、策略检查 60s LLM 超时。
- 前置核实：`llm.py` **已有** 429 退避重试（`_rate_limit_wait()` F3-6：优先 Retry-After、cap 30s，否则指数退避 3s×2^attempt，重试 2 轮后降级）——本轮 429 持续 2 分钟且设计任务 45s 内失败，说明**现有退避在预热并发场景失效**（预热期多任务同时打满配额、45s DATA 预算内退避来不及），而非退避机制缺失。
- 实施：①预热期 LLM 调用错峰（预热完成后再触发 news 摘要等）；②**评估现有 F3-6 退避失效原因**（预热并发打满配额 → 提高退避轮数或预热期静默跳过 LLM 附属调用）；③design/check 任务提交加**互斥或限流**（同一时间仅 1 个 LLM 任务）；④设计任务 DATA 阶段 45s 预算在数据源熔断期动态放宽或明确失败提示。
- 验收（可自证，不依赖外部配额承诺）：①应用侧任意时刻至多 1 个 LLM 任务在跑（互斥生效，可观察 /portfolio/tasks 并发 LLM 阶段任务数）；②429 时任务按退避重试且**不失败降级**（除非超时预算耗尽）；③观察点：设计任务 completed 且非 rule 兜底、token-usage 管理接口无 429 级联失败。

**R5-1-2：策略检查兜底路径 holdings_analysis 补全（P0-1 收敛）**
- rule 兜底路径（LLM 超时）目前 holdings_analysis 恒空 → 行业集中度检查静默跳过。
- 实施：rule 兜底时**用 factor_breakdown/industry_map 生成 holdings_analysis 骨架**（symbol/name/weight/factor_summary/industry），使行业分布分析在兜底路径也存在（数量级正确，标注"规则引擎生成"）。
- 验收：LLM 超时时 strategy-check 报告仍含逐标的持仓分析 + 行业覆盖提示（≥7 行业不再误报，缺失时 WARN+标注）。

**R5-1-3：llm-advice 上下文注入关键词扩展（R5-07）**
- 根因：注入分支关键词（大盘/今天/最新/走势/行情/板块/行业…）覆盖不全，"当前A股市场怎么配置"不命中。
- 实施：①关键词补"市场""A股""股票""指数""配置"等高频词；或②**无条件注入** market_snapshot（指数/市态/情绪/新闻摘要，成本为零——数据来自缓存）。
- 验收：任意投顾问题回答含实时市场数据（数据源可用时），无"暂无数据"式全降级模板。

**R5-1-4：F19 因子 no_data 修复（R68-R72 实施）**
- sentiment 4 因子全 no_data（panic_greed_diff/stock_divergence/news_heat/news_direction）——根因 1（sentiment_history 缺失）+ 根因 4（akshare 源）。
- 实施：R68（fetch_market_sentiment 维护 20 日 sentiment_index 滚动数组持久化）；R69（注入 advance_decline）；R70 已部分实施（style 已 valid）；R71（_FUND_SHARES_CACHE 失败缓存破绽修复）。
- 验收：数据源可用后 sentiment 因子 ≥2 个 valid/warn；verify_e2e factor-thresholds 的 sentiment 断言 PASS。

**R5-1-5：IC 后台周期计算 + 启动恢复（factor-and-strategy-check R1 + 补充）**
- 根因（完整链路）：①`_last_ic_batch` 仅带 market_data 的 compute 更新（请求驱动）；②`main.py:342-364` **已有** IC persistence loop（每 120s 把 `_last_ic_batch` 经 `ic_tracker.save_ic_batch_to_db` 持久化到 DB）；③但 `/factors/ic` 端点（factors.py:283-289）**只读内存 `_last_ic_batch`、不回读 DB** → 重启后内存态丢失 → IC 空（DB 中有历史数据但端点读不到）。
- 实施：①**优先**启动钩子在 lifespan 末尾从 DB 恢复 `_last_ic_batch`（遵循 factor_registry.py:1237-1244 的覆盖保护：仅 abs(val)>0.001 才覆盖）；②补充 main.py 120s 循环内调 `factor_registry.compute(带 market_data 缓存)`（复用已有 K 线缓存，不触网）作为周期刷新。
- 验收：容器重启后 /factors/ic 不依赖任何请求即返回非空（样本≥3 的因子，数据来自 DB 恢复或首次 compute）；B1 验收"非请求驱动"达标。

**R5-1-6：策略检查 LLM 超时诊断与快速失败（用户反馈 #2，2026-08-02）**
- 背景：策略检查把 LLM 调用包在 60s 预算（portfolio_service.py:576）；429 持续时 `_rate_limit_wait` 尊重 Retry-After（cap 30s）→ 每轮等待 30s × 3 轮 = 90s > 60s → 必超时走 rule 兜底；且超时 summary 只写"LLM 分析超时（60s 未返回）"，用户/日志**无法区分限流与真超时**（本轮用户实测仍触发该文案）。
- 实施：①`llm.py` 新增模块级 `_last_llm_error` + `get_last_llm_error()`（每次 provider 失败记录 `{provider_id}: {exc}`，429 前缀 `[rate-limited]`/连接超时 `[timeout]`；成功清空）；②`_rate_limit_wait(attempt, resp_headers, cap=30.0)` 参数化 cap（默认 30 不变）；③**调用链透传（cap 生效路径须完整）**：`generate_strategy_check_report` 经 `get_agent("strategy_suggestions").run()` → `llm_complete_with_system`（runtime.py:55-81；**自包含实现，不调 `llm_complete`**，其签名已含 `max_retries`/`retry_delay` 参数，llm.py:556-654）——①agent run 层新增 `rate_limit_cap` 透传参数（默认不传行为不变），策略检查场景传 `max_retries=1, rate_limit_cap=10.0`；②**`llm_complete_with_system` 内部重试等待（当前固定 `retry_delay`，llm.py:650）须接入 `_rate_limit_wait(cap)`**——否则 cap 传了不生效，429 时仍按固定 3s 等待 ×2 轮 ≈ 6s（可接受但 cap 10s 约束落空）；最坏 2 轮×(调用2s×2源+等待≤10s)≈28s < 60s 预算，快速失败；④`portfolio_service.strategy_check` 超时兜底 summary 追加 `最后错误：{get_last_llm_error() or '未知'}`。契约：内部实现改动，不涉 API 契约。
- TDD（新文件 `tests/test_strategy_check_llm_timeout.py`，6 用例）：429 时 summary 含 provider/429；连接超时含 [timeout]；`_rate_limit_wait(attempt=3, cap=10)` ≤10s；成功返回后 `get_last_llm_error()` 为空；mock agent run 断言 `rate_limit_cap=10` 透传到 `llm_complete_with_system`（mock 点 `app.analysis.runtime.llm_complete_with_system`，对齐 test_agent_registry.py:81）；既有 `test_llm_rate_limit.py` 不破坏（默认 cap 30 不变）。
- 验收：真实 429 时策略检查任务 ≤40s 完成（不 60s 干等），summary 含"最后错误：opencode_zen 429 Too Many Requests"；verify_e2e 策略检查 completed（LLM 失败时 rule 兜底但任务不 failed）。根治（全局 LLM 信号量 + 429 任务排队）见 R5-1-1 ③。

### 🅿️2 中优先级

**R5-2-1：组合计算与 watchlist 提速（P2-1/P3-3 收敛）**
- calculate 5.10s（门禁 3s）未改善；watchlist 4525ms（round4 2.27s 更慢）。
- 实施：`_build_price_map_async` 单源 wait_for 3s 截断已存在但收益未达——查慢源具体标的；watchlist 实时行情改 `fetch_a_stock_batch` 批量拉取（P3-3 原案）。
- 验收：calculate ≤3s、watchlist 首次 <800ms（verify_e2e 门禁收紧）。

**R5-2-2：news/stock 键归一化收尾（P2-3）**
- 现状双键并存（title/content/time/url + 关键词/文章来源残留）。
- 实施：①**契约先行**——更新 `api-contracts/news/all.md`（stock 契约在其 L107-116，末尾 checklist L210 处打勾；删除中文键字段，声明键集 == headlines）+ 末尾 checklist 打勾；②`fetch_stock_news` 归一化后**只输出英文键**（删中文键）；③前后端逐字段核对。
- 验收：`/news/stock/{symbol}` 键集 == headlines 键集（e2e 断言）。

**R5-2-3：warmup_global_indices 冷拉优化**
- 预热新增热点 1.09s（round4 3.9ms）。实施：全球指数预热改为"缓存命中即跳过 + 失败快速降级"（与 R4-26 失败缓存模式一致）。
- 验收：读 `backend/logs/warmup_timing.json` 的 `total_duration_ms` < 2500ms（手工或 CI 脚本直读 JSON；**勿依赖 `check_perf_budget.py`**——其路径拼接 `Path(__file__).parent.parent/'backend'/'logs'` 解析为 `backend/backend/logs/`（不存在）且读 `total_ms` 而 JSON 字段为 `total_duration_ms`，运行即"baseline not found"；若要用它需先修脚本）。**不改** verify_e2e A01 门禁——其阈值 20s/10s 用于 CI 泛化门禁，且 A01 仅在 PROFILE_WARMUP=1 时实测、未启用时恒 PASS，不承担 2.5s 断言。

**R5-2-4：mootdx 依赖与降级链简化（C4-1，对应 R5-12）**
- 背景：requirements 无 mootdx（`_mootdx()` lazy import 的 ImportError 被 warning 吞，降级链第一环空转）；7709 端口当前网络不可达（通达信官方 IP 亦超时，与交易时间无关）。
- 实施（默认方案 B，按实施期宿主网络可达性决策）：**方案 B（推荐）**——从实时/批量行情降级链移除 mootdx 环节（从未生效，Sina/Tencent 兜底已实测正常），删除 `_MOOTDX_CLIENT`/`_MOOTDX_EXECUTOR` 等 mootdx 超时包装；**方案 A**——若宿主确认 7709 可达则 requirements 补 `mootdx` 并保留降级链。TDD：现有单测中 mock mootdx 环节的改为直接 mock Sina/Tencent，**点名更新 `tests/test_timeout_resilience.py:52`（`test_mootdx_has_socket_timeout` monkeypatch `_MOOTDX_CLIENT`，移除后会 AttributeError）**。契约：内部实现改动，不涉 API 契约。
- 验收：无 mootdx ImportError 噪音；实时/批量行情在 Sina/Tencent 可达时正常；相关单测全过。

**R5-2-5：llm_report 指数链路对齐（C4-2，对应 R5-13）**
- 背景：`llm_report`/`llm_report_stream` 的 indices 用 `get_indices()`（Sina 三级降级，仅 A 股指数）→ HK/US 报告 indices 空；`get_global_indices()`（17 指数多源降级 + 24h 磁盘缓存，含港股/美股段）有数据未用。
- 实施：indices 采集改 `get_global_indices()` 展平 → `_filter_indices_for_market`（P0-2 口径）按市场过滤；A/GLOBAL 保持全量。契约：indices 响应结构不变，契约先行核对即可（`api-contracts/analysis/llm-report.md` 无需改字段）。TDD：mock get_global_indices 返回 A/HK/US 段，断言 HK 报告仅注入 HK 段。
- 验收：HK/US llm-report indices 非空（数据源可用时含对应市场指数）；verify_e2e 增 HK/US 报告指数非空断言。

**R5-2-6：东财 API 抗限流（C4-3，对应 R5-14）**
- 背景：push2 实时接口被出口 IP 限流（RemoteDisconnected，宿主机+容器一致）；同域 push2delay（1843 只 ETF）可用但未降级。
- 实施：①东财/akshare 调用补 `User-Agent` + `Referer`（行情页）；②失败指数退避重试 2 次；③push2 被拒时降级 push2delay（延迟接口字段兼容）；④与 R5-2-9 联动纳入熔断。契约：内部实现改动，不涉 API 契约。TDD：mock 东财失败 → 断言退避重试与 push2delay 降级。
- 验收：限流窗口内重试/降级后仍能取数（或降级 push2delay 成功）；候选池/ETF/今日涨跌不因东财限流而全缺（数据源可用时）。

**R5-2-7：akshare 商品接口签名适配（C4-4，对应 R5-15）**
- 背景：`futures_foreign_commodity_realtime()` 现需 `symbol` 参数，旧无参调用 TypeError → 商品恒空。
- 实施：`fetch_futures_realtime` 按新签名传 symbol（常用外盘品种列表：NYMEX 原油/COMEX 黄金/白银等），失败静默（非交易时段允许为空）；或改用其他商品源。契约：内部实现改动，不涉 API 契约。TDD：单测覆盖新签名调用。
- 验收：商品行情非恒空（数据源可用时）；无 TypeError。

**R5-2-8：PE/PB 备用源与失败缓存（C4-5，R5-10 管道项）**
- 背景：`fetch_current_pe_pb` 依赖 `ak.stock_zh_a_hist`（东财日线估值列，fundamentals_fetcher.py:270-312；东财挂 → None）→ 个股分析基本面段恒"数据源不可用"。
- 实施：增加备用源（akshare 其他估值接口/新浪）+ 复用 R4-26 失败缓存模式（失败/空缓存 1h，避免反复触发慢源）。契约：内部实现改动，不涉 API 契约。TDD：mock 主源失败 → 备用源返回。
- 验收：akshare 挂时 PE/PB 仍可用（备用源可用时）或显式"数据源不可用"（不静默）；个股分析报告基本面段在源可用时非恒缺。

**R5-2-9：熔断器接线 akshare/东财（C4-6，R5-10 管道项）**
- 背景：akshare/dongfang 内部直连绕过 SourceRegistry 熔断（熔断器 closed 且失败计数 0，防护形同虚设）。
- 实施：将 akshare 东财调用包装进 registry.route（对齐 china_market 其他链路熔断语义）；sources/health 与 circuit-breakers 如实反映。契约：内部实现改动，不涉 API 契约。TDD：mock 东财连续失败 → 断言熔断 open + 冷却。
- 验收：东财失败被熔断计数并冷却（sources/circuit-breakers 可见）；health 如实反映 akshare/dongfang 失败。

**R5-2-10：国内宏观/流动性数据管道（用户反馈 #16，2026-08-02）**
- 背景：A 股 llm-report"国内流动性：输入数据无直接货币/利率信号"——`build_full_context` 无宏观段。akshare 实测（宿主机直连）：LPR（`macro_china_lpr`，1.8s，最新 2026-07-20：LPR1Y=3.0/LPR5Y=3.5）、中美国债收益率（`bond_zh_us_rate`，0.5s，2026-07-31：cn_10y=1.7141/us_10y=4.75、中国 10Y-2Y 期限利差字段 0.454）、M0/M1/M2（`macro_china_money_supply`，0.4s）；**CPI/PPI 数据滞后至 2025-09（今值 nan）→ 必须 stale 标注**；Shibor/社融接口（`macro_china_shibor`/`macro_china_society_financing`）已失效，不纳入。
- 实施：①新 `app/fetchers/macro_fetcher.py`：`fetch_lpr()/fetch_bond_yields()/fetch_money_supply()/fetch_cpi_ppi()`——`run_in_thread` + try/except + 24h 成功缓存 + 1h 失败缓存（R4-26 模式）；CPI/PPI 今值 nan 或日期 >3 个月 → 返回 `{"stale": true, "note": "数据滞后至YYYY-MM（数据源），仅作趋势参考"}`；②`llm_context.build_full_context` 加 `include_macro: bool = True` 参数 + `domestic_macro` 段（`market="A"` 时注入；4 源 `asyncio.gather`；全失败 `{"unavailable": true}`——LLM 显式写"宏观数据源不可用"，对齐 P1-4 诚实降级）；③契约先行：`api-contracts/analysis/llm-report.md` 为端点级文档（无 market_data/context 段）；**参照 `api-contracts/analysis/agents.md`（L67 附近）的 market_data 结构惯例**，新增 `domestic_macro` 字段说明（可空对象：`lpr/bond_yields/money_supply/cpi_ppi/unavailable`；HK/US 省略），实施时先读契约现状再按最小 diff 补充。受益面：llm-report/设计报告/策略检查/投顾全部走 build_full_context，一处加段全链路生效。
- TDD（新文件 `tests/test_macro_fetcher.py` 8 用例 + `test_llm_context_market.py` 扩展 2 用例）：LPR 取最后一行字段映射；bond_yields 利差计算；CPI/PPI 今值 nan/日期>3月 → stale=true；akshare 异常 → None + 1h 失败缓存（二次调用不调源）；24h 成功缓存；market='A' → context 含 domestic_macro；market='HK' → 无该段；4 源全失败 → unavailable=true。**mock 引用 >5 处必须抽 fixture（F21 R76 冻结基线，最新统计口径见项目 memory 记录）**。
- 验收：真实 A 股 llm-report 的 `domestic_macro` 含 LPR+中美利差+M2；报告"国内流动性"段出现实质数据（如"LPR 3.0% 按兵不动、中美 10Y 利差约 300bp"），不再"输入数据无直接信号"；东财限流窗口 unavailable=true 显式标注不编造。

**R5-2-11：场外基金技术分析链路修复（用户反馈 #17，2026-08-02）**
- 背景：两处同一缺陷实例——①`PortfolioManager.vue taTarget`（L644-647）对 `tracked_index` 存在时返回 `{sym: tracked_index, assetType: 'index'}`；②`AnalysisView.vue getActiveAssetType()`（L128-134，驱动技术分析 tab 查询 L439）同样对场外 tracked_index 返回 `'index'`。场外联接基金 tracked_index 存的是**场内 ETF 代码**（019671→513120、021458→159545、022449→159338，DB 实测）→ `fetch_index_history('513120')` 用 ETF 代码查指数：021458/022449 返回空（"暂无数据"）、019671 碰巧 akshare 容错返回 ETF 数据（不可靠依赖）。
- 实施：**两处同步修正**——`taTarget` 与 `getActiveAssetType` 对 `tracked_index` 为场内 ETF 代码（前缀 `_ETF_PREFIXES`：51/52/15/16/56/58/59，与后端 `_is_etf_code` 对齐）时返回 `{sym: tracked_index, assetType: 'A'}`（查 ETF 自身 K 线）；仅真实指数代码（000xxx/399xxx/HSI 等）才用 `assetType: 'index'`。可抽公共 helper（如 `resolveTaTarget(etf)`）避免两处漂移。契约：内部前端实现改动，不涉 API 契约。
- TDD：`PortfolioManager.spec.js` 与 `AnalysisView.spec.js` 各补"场外标的 → assetType='A' 且 sym=tracked_index"用例（mock marketApi.indicators 断言参数）；"指数代码 tracked_index → assetType='index'"用例；场内 ETF（tracked_index=None）不回归用例。
- 验收：持仓展开**与 AnalysisView 技术分析 tab** 的场外基金均显示数据（对应场内 ETF 的 K 线指标），无"暂无数据"；A 股场内标的不回归（tracked_index=None 路径不变）。

### 🅿️3 测试防护体系弥补（R5-3 批次，来源：docs/user-feedback-fixes-review.md §5）

> 依据 12 个清单内已修复 bug 的归因（6 个前端交互接线盲区 + 后端分支/prompt/集成层盲区 + 性能无门禁），
> 本批为**测试能力建设**，与业务修复解耦、独立批次 4 实施；每项均先写失败测试再实现（AGENTS.md TDD）。

**R5-3-1：前端交互组件测试改「真实 composable + mock 网络」**
- 目标组件：UnifiedAnalysis / AiAdvisor / MarketReport / WatchlistPanel / AnalysisView（5 个含输入/补全/切换的组件）。
- 现状：spec 全 mock 业务 composable（如 `useMarketSearch` 返回 stub）→ 状态写回链路无人断言（#12/#13 接线断点静默通过的根因）。
- 实施：改造现有 spec——**不再 mock 业务 composable**，用真实 `useMarketSearch` 等 + 只 mock `api` 层（axios）；断言模式：`input 事件 → searchQuery 写回 → debounce → api 调用参数` 全链路；新增「prop 变化（marketTab/activeTab/period）→ 状态重置/请求重发」断言矩阵。
- TDD：对 5 个组件各补 1 个"真实输入流"用例（如 UnifiedAnalysis：`input.setValue('5100')` → 断言 api.search 以 `5100` 调用）；回归：#12/#13/#14/#15 的既有用例改造为走真实输入流。
- 验收：5 组件 spec 无 mock composable；前端全量测试通过。

**R5-3-2：后端 asset_type 分支参数化测试**
- 现状：`get_asset_realtime` 测试只覆盖 A/HK/US，漏 index/gold 等（#8 指数错位未被捕获）。
- 实施：`@pytest.mark.parametrize` 覆盖 `A/ETF/HK/US/index` 全分支，断言「返回值与分支匹配」（index 不得返回股票价；HK 不走 A 股路径——U1/N03 回归）。
- 验收：参数化用例全过；新增分支（如 gold/oil）时强制补参。

**R5-3-3：prompt 数据完整性断言**
- 现状：sector/symbol/index 分析的 prompt 测试只断言结构/标题（#6 板块快照未注入未被捕获）。
- 实施：对 `sector_analysis_stream`/`symbol_analysis_stream` 的 prompt 构建（mock hub 返回非空数据）断言**关键数据段已注入**（板块快照字段、realtime price 出现在 prompt 文本中）；数据为空时断言显式降级文案（"数据源不可用"）而非静默。
- 验收：prompt 注入/降级两类断言存在且通过。

**R5-3-4：路由层集成测试（覆盖调用处传参）**
- 现状：`_normalize_sector_code` 有纯函数单测，但调用处传单表（#7 概念 404）测不到。
- 实施：对 `sector_analysis_stream` mock `market_data_hub`（行业+概念双表）+ `_sse_stream` 断言「概念名映射成功、SSE 首包含板块行情段、无 404」；对 `watchlist_list` mock `get_asset_realtime` 断言并行化（慢源不拖累）。
- 验收：路由层集成测试存在且通过。

**R5-3-5：性能预算门禁**
- 现状：#5（watchlist 串行 5-12s）/ #10（debounce 300ms）功能测试通过但耗时退化无感。
- 实施：后端——`watchlist_list`/`calculate` 增加响应时间基准测试（慢源 mock 下断言 < 阈值，如 watchlist 5 标的 <3s）；前端——debounce 等常量快照测试（`SEARCH_DEBOUNCE_MS === 200`，防回归到 300）。
- 验收：性能基准测试存在且通过；常量快照防回归。

## 十一、实施批次（用户决策：分批实施，每批验收 + verify_e2e 全绿）

```
批次 1（P0）            ← 本批先行（verify_e2e design-quality 门禁为验收基准）
  R5-0-1 (候选池强制标二次校验)  R5-0-2 (重叠修复)  R5-0-3 (首页 CLS + LHCI 接入)
  R5-0-4 (红利上限)  R5-0-5 (A7/A10/A11 复验)
批次 2（P1）
  R5-1-1 (LLM 限流)  R5-1-2 (策略检查兜底持仓分析)  R5-1-3 (llm-advice 注入)
  R5-1-4 (F19 因子)  R5-1-5 (IC 后台计算)  R5-1-6 (LLM 超时诊断与快速失败)
批次 3（P2）
  R5-2-1 (calculate/watchlist 提速)  R5-2-2 (news 键收尾)  R5-2-3 (预热优化)
  R5-2-4 (mootdx 降级链)  R5-2-5 (报告指数链路)  R5-2-6 (东财抗限流)
  R5-2-7 (商品签名)  R5-2-8 (PE/PB 备用源)  R5-2-9 (熔断器接线)
  R5-2-10 (国内宏观管道)  R5-2-11 (场外技研链路)
批次 4（测试防护弥补，见 §十 R5-3 节）
  R5-3-1 (前端真实 composable 测试)  R5-3-2 (asset_type 参数化)
  R5-3-3 (prompt 完整性断言)  R5-3-4 (路由集成测试)  R5-3-5 (性能预算门禁)
```

## 十二、验收总表

| 修复项 | 验收方式 | 门禁 |
|---|---|---|
| R5-0-1 | 真实 design 核心层含 A500；候选池恒含强制标的 | verify_e2e design-quality |
| R5-0-2 | 真实 design 两两核心层重叠（剔除公共底仓与强制标的）≤1 | verify_e2e diversity |
| R5-0-3 | Lighthouse 首页 P≥60/CLS≤0.1（3 次中位数） | LHCI 接入 CI |
| R5-0-4 | 真实 design 三方案红利类合计 ≤15% | verify_e2e design-quality 新断言 |
| R5-0-5 | A7/A10/A11 复验结论记入实施记录（A10/A11 不达标并入 F3 R4/R5） | 单测 + 走查 |
| R5-1-1 | 应用侧至多 1 个 LLM 任务并发；429 退避重试不失败降级（除非超时预算耗尽） | 单测 + 任务状态观察（completed 非 rule 兜底） |
| R5-1-2 | LLM 超时报告含持仓分析+行业覆盖 | verify_e2e 新断言 |
| R5-1-3 | 任意投顾问题含市场数据 | 单测 + e2e |
| R5-1-4 | sentiment 因子 ≥2 valid/warn | verify_e2e factor-thresholds |
| R5-1-5 | 重启后 /factors/ic 非请求驱动非空（DB 恢复或首轮 compute） | verify_e2e factor_ic |
| R5-2-1 | calculate ≤3s；watchlist <800ms | verify_e2e 门禁收紧 |
| R5-2-2 | news/stock 键集==headlines（契约先行更新） | 单测 + e2e |
| R5-2-3 | warmup_timing.json total_duration_ms <2500ms | 直读 JSON（勿用 check_perf_budget.py，见 §P2 说明） |
| R5-2-4 | 无 mootdx ImportError 噪音；实时/批量行情 Sina/Tencent 正常 | 单测 + 链路验证 |
| R5-2-5 | HK/US llm-report indices 非空（数据源可用时） | verify_e2e 新断言 + 单测 |
| R5-2-6 | 东财限流窗口内重试/降级 push2delay 取数成功 | 单测 + 链路验证 |
| R5-2-7 | 商品行情非恒空（数据源可用时）、无 TypeError | 单测 + e2e |
| R5-2-8 | akshare 挂时 PE/PB 备用源可用或显式标注 | 单测 + e2e |
| R5-2-9 | 东财失败被熔断计数并冷却；health 如实反映 | verify_e2e sources + circuit-breakers |
| R5-1-6 | 真实 429 时策略检查 ≤40s 完成；summary 含最后错误原因 | 单测 + 任务状态观察 |
| R5-2-10 | A 股 llm-report domestic_macro 含 LPR+中美利差+M2；不可用时 unavailable=true | 单测 + e2e |
| R5-2-11 | 场外基金**两入口**（组合展开 + AnalysisView 技术分析 tab）均显示数据（无"暂无数据"）；A 股场内不回归 | 前端 spec + 走查 |
| R5-3-1 | 5 组件 spec 无 mock composable；真实输入流断言存在 | 前端全量测试 |
| R5-3-2 | asset_type 全分支参数化用例通过（index 不得返回股票价） | 后端单测 |
| R5-3-3 | sector/symbol prompt 注入段非空断言 + 降级文案断言 | 后端单测 |
| R5-3-4 | sector_analysis_stream 集成测试：概念名映射成功无 404 | 后端单测 |
| R5-3-5 | watchlist 并行基准 <3s；debounce 常量快照 | 性能测试 + 前端单测 |

## 十三、诊断配置回收（步骤 15）

- `docker compose --profile prod down` 停止并移除 backend/frontend/redis 容器。
- **docker-compose.yml 恢复生产默认**：移除 prod backend 的 `PROFILE_WARMUP=1`（WarmupProfiler 为诊断专用，持续开启会在每次生产重启时全程 cProfile+pyinstrument 采样并写 3 份报告到 /app/logs）与 `./backend/logs:/app/logs` volume；`LOG_LEVEL=INFO` 保留（覆盖 .env 的 DEBUG，与 dev 对齐省预热日志开销；排障需 DEBUG 时 `docker compose run -e LOG_LEVEL=DEBUG`）。
- 老镜像已在构建时回收（本轮新镜像 58d441568575/67ef197df43c 保留）。
- 诊断报告（warmup_timing.json / warmup_pyinstrument.* / warmup_cprofile.txt / perf_diag_results.json）保留在 `backend/logs/` 供回溯。

## 附录 A：本轮问题清单（R5-01 ~ R5-10）

- **R5-01 🔴** 设计真实链路 A500 未入核心层（560600 被 MAX_PER_LAYER[core]=8 截断挤出；_ensure_mandatory 在截断前执行；P1-1 门禁 FAIL）。
- **R5-02 🔴** 核心层跨方案重叠（平衡∩进攻 3 只 [159915, 562000, 588000]；P1-2 门禁 FAIL；豁免放宽分支过宽）。
- **R5-03 🔴** 首页 Lighthouse P56/CLS 0.388（summary-grid 无固定高度；P1-8 未实施；LHCI 未接入 CI）。
- **R5-04 🔴** 组合计算 5.10s（P2-1 未达标）；watchlist 4525ms 劣化。
- **R5-05 🟡** LLM 主 provider 429 限流（设计失败 + 策略检查降级；并发任务无互斥）。
- **R5-06 🟡** sentiment 4 因子 no_data（F19 未实施）+ IC 仅请求驱动（R1 未实施）。
- **R5-07 🟡** llm-advice 注入关键词覆盖不全（"市场"不在关键词表 → 无上下文回答）。
- **R5-08 🟡** rule 兜底路径 holdings_analysis 恒空（行业检查静默跳过）。
- **R5-09 🟡** news/stock 中文键残留（P2-3 部分修复，双键并存）。
- **R5-10 🟢** 数据源降级面扩大（候选池 14 只、今日涨跌全缺、HK/US 报告指数缺失、US 个股搜索空、PE/PB 全缺）——详见附录 C 数据源归因专项：约 2/3 为外部数据源问题（东财 API 限流、mootdx/7709 端口不可达），约 1/3 为管道缺陷（llm_report 指数链路、商品签名、熔断器未接线等，可修复）。
- **R5-11 🟡** 红利类权重超 M1 上限（防御 core 563020 16.96%、进攻卫星 16.43% > 15%；D1 决策未在引擎落地，修复项 R5-0-4）。
- **R5-12 🟡** mootdx 依赖缺失：requirements.txt 无 mootdx 包，容器/生产从未真正连接（ImportError 被吞）；且 7709 端口当前网络不可达（官方服务器 IP 亦超时）——**修复项 R5-2-4**（§十）。
- **R5-13 🟡** llm_report 指数链路不一致：用 `get_indices()`（Sina 主源的三级降级链，A 股指数）而非 `get_global_indices()`（17 指数多源降级 + 24h 磁盘缓存，含港股/美股段）→ HK/US 报告指数恒缺——**修复项 R5-2-5**（§十）。
- **R5-14 🟡** 东财 API 限流无降级：push2 实时被拒时不降级同域 push2delay（已验证可用，1843 只 ETF）；无 UA/Referer/重试抗限流——**修复项 R5-2-6**（§十）。
- **R5-15 🟡** akshare 接口签名变更未适配：`futures_foreign_commodity_realtime()` 现需 `symbol` 参数（旧调用 TypeError）→ 商品数据恒空——**修复项 R5-2-7**（§十）。

## 附录 B：修订记录

- v1.0 (2026-08-02)：round5 全量诊断完成（15 项动作），形成 P0-P2 修复方案（未实施）。
- v1.1 (2026-08-02)：多轮 review 修订——①R5-1-1 前置核实 llm.py 已有 F3-6 退避（改为评估失效原因）且验收去外部配额承诺；②P1-3 证据路径更正为 routers/analysis.py；③R5-1-5 根因补 DB 持久化存在但端点不回读 + 实施补启动恢复；④R5-2-3 验收改直读 warmup_timing.json（标注 check_perf_budget.py 路径/字段 bug）；⑤新增 §十三 诊断配置回收（PROFILE_WARMUP/logs volume 移除、LOG_LEVEL 保留说明）；⑥docker-compose 注释补 LOG_LEVEL 行为变更说明；⑦R5-2-2 补契约先行步骤；⑧新增 R5-0-4（M1 红利上限，含单测覆盖缺口警示）与 R5-0-5（A7/A10/A11 复验），同步补 §十一 批次 1、§十二 验收总表、附录 A R5-11；⑨8.2 表补 A7/A10/A11 未实测注记；⑩R5-0-4 决策范围显式化（D1 防御型 15% 扩展为全方案）；⑪R5-0-2 验收口径统一（剔除公共底仓与强制标的）。
- v1.2 (2026-08-02)：数据源归因专项（附录 C）——①三层实测（原始 akshare / 封装 fetcher / 管道产出）+ 宿主机 vs 容器网络对照；②更正两处误报：levistock 实为财联社通道（pip 包 levistock，`api.levistock.com` 为错误域名，源正常）、新浪 403 为缺 Referer（fetcher 已带，源正常）；③确认 mootdx 依赖缺失（requirements 无包）+ 7709 端口不可达（与交易时间无关）；④新增问题 R5-12~R5-15（mootdx 依赖、llm_report 指数链路、东财限流无降级、akshare 签名）与修复方向（§C.4，未纳入实施批次，待确认）。
- v1.3 (2026-08-02)：数据源修复方案正式化——附录 C §C.4 修复方向升级为 §十 P2 正式修复项 **R5-2-4~R5-2-9**（mootdx 降级链简化 / llm_report 指数链路对齐 / 东财抗限流 / 商品签名适配 / PE/PB 备用源 / 熔断器接线），同步补 §十一 批次 3、§十二 验收总表 6 行、附录 A R5-12~15 修复项编号引用；仍为实施标准设计，未实施。
- v1.4 (2026-08-02)：用户反馈批次方案正式化——新增 **R5-1-6**（策略检查 LLM 超时诊断与快速失败：原因留痕 + cap 参数化）、**R5-2-10**（国内宏观数据管道：macro_fetcher + domestic_macro 段 + 契约）、**R5-2-11**（场外基金技研链路：taTarget asset_type 修正）；新增 **🅿️3 测试防护弥补批次 R5-3-1~5**（前端真实 composable 测试 / asset_type 参数化 / prompt 完整性断言 / 路由集成测试 / 性能预算门禁，来源 user-feedback-fixes-review §5）；§十一 批次追加 1-6/2-10/2-11/批次 4；§十二 验收总表追加 8 行；仍为实施标准设计，未实施。

## 附录 C：数据源归因专项（2026-08-02 补充诊断）

### C.1 测试方法
三层对比 + 双环境对照：
1. **原始 akshare 直测**（绕过封装，容器内 `ak.*` 直接调用）；
2. **封装 fetcher**（`china_market` / `levistock_fetcher` / `global_markets_fetcher` 等）；
3. **管道产出**（候选池 / llm-report / watchlist / factors 等）；
4. 同一网络探测脚本在**宿主机与容器**各跑一遍（DNS + TCP + HTTP 逐域名对比）。

### C.2 归因总表

**A. 外部数据源问题（数据源真不通，~2/3）**

| 源 | 实测证据 | 判定 |
|---|---|---|
| 东财 push2 实时接口（A股 spot/全球指数/行业板块/个股信息 PE·PB/日K线） | 宿主机+容器均 `RemoteDisconnected`，重试 3 次稳定失败；同域 push2delay HTTP 200 正常；部分接口（新闻/热门股/基金净值/A股指数）间歇可用 | **出口 IP 被东财限流**（接口级、间歇性），非网络问题 |
| mootdx `standard.mootdx.com:7709` + 通达信官方服务器 202.108.24.23/119.147.212.81/112.65.136.186:7709 | 全部 TCP 超时（宿主机 24s / 容器 8s / 官方 IP 5s） | **7709 端口网络不可达**（外部），与交易时间无关（非交易时段行情服务器 TCP 仍可连） |
| 通达信官方行情服务器 7709 端口 | 同上 | 同上 |
| akshare 港股/美股 spot | 5-6s 超时返回空 | 数据源无数据（源弱/限流） |

**B. 管道缺陷（数据源可用但管道未接好，~1/3，可修复）**

| 缺陷 | 证据 | 影响 |
|---|---|---|
| llm_report 指数链路不一致 | `llm_report` 用 `get_indices()`（Sina 主源三级降级，仅 A 股指数），`get_global_indices()`（17 指数多源降级+24h 磁盘缓存，含港股/美股段）有数据却不用 → HK/US 报告 `indices=[]` | HK/US 综合研判缺指数（round5 实测"暂无数据"；归因见 §五） |
| 东财限流无降级 | push2delay（1843 只 ETF）可用但主链路不降级；fetcher 无 UA/Referer/重试 | 候选池缩小、今日涨跌缺失、PE/PB 缺 |
| mootdx 依赖缺失 | requirements.txt 无 mootdx 包，`_mootdx()` ImportError 被吞；容器从未真正连接 | 降级链第一环空转（注释声称 mootdx→Sina→Tencent） |
| akshare 商品签名变更 | `futures_foreign_commodity_realtime()` 现需 `symbol` 参数，旧调用 TypeError | 商品数据恒空 |
| PE/PB 无备用源 | `fetch_current_pe_pb` 依赖 `ak.stock_zh_a_hist` 东财日线估值列（fundamentals_fetcher.py:270-312，东财挂 → None） | 估值指标缺（仅"数据源不可用"标注；修复项 R5-2-8） |
| 熔断器未接线 akshare | akshare/dongfang 熔断器 `closed` 且失败计数 0，但实际大量失败 | 熔断防护形同虚设 |

**C. 管道已正确兜底（设计良好）**
- ✅ K 线降级链：akshare 挂 → netease/sina 兜底（240 条）；单只实时：mootdx 挂 → 腾讯/新浪兜底（change_pct 有值）
- ✅ 全球指数 `get_global_indices`：多源 + 24h 磁盘缓存；FRED（美债 4.68/VIX 17.09/利率 3.63）
- ✅ 财联社/levistock（news_telegraph_cls 17 条、market_emotion_cls、get_sector_heat 20 条）、新浪（带 Referer 200）、腾讯、新闻、基金净值

**D. 网络对照结论**：宿主机与容器行为完全一致（东财 push2/push2delay/push2his/quote、腾讯、新浪、FRED、财联社 TCP 全通）——**不存在容器独有的连通性问题**，docker bridge + 内置 DNS 健康，无需修改容器网络配置。

### C.3 关键更正（上轮误报）
- **levistock 正常**：`levistock` 是 pip 包，封装**财联社（cls.cn）签名接口**（`lv.news_telegraph_cls` / `market_emotion_cls` / `get_sector_heat` / `market_wind_cls` 全部实调正常）；上轮测的 `api.levistock.com` SSL EOF 是错误域名（与本项目无关）。
- **新浪正常**：`hq.sinajs.cn` 强制要求 `Referer: https://finance.sina.com.cn/`，fetcher 已带（K 线降级链实测 240 条）；裸测 403 为缺 Referer 所致。
- **mootdx 与交易时间无关**：非交易时段行情服务器 TCP 仍可连（数据为收盘快照）；当前不可达 = ①requirements 缺 mootdx 包（从未真正连接）+ ②7709 端口网络不可达（官方 IP 亦超时）。

### C.4 修复方案（已升级为正式修复项 R5-2-4~R5-2-9，见 §十/§十一批次 3/§十二验收总表）
| 项 | 修复方向 | 验收 |
|---|---|---|
| C4-1 mootdx 依赖 | ①requirements 补 `mootdx`（需先确认宿主 7709 端口可达）；②或从降级链移除 mootdx 环节（从未生效，Sina/Tencent 兜底已实测正常），减少无谓超时 | 无 mootdx ImportError 噪音；或降级链直接 Sina/Tencent |
| C4-2 llm_report 指数链路 | `llm_report` 的 indices 改取 `get_global_indices()` 按市场取段（对齐 market_data 的 N04 口径），HK/US 报告不再缺指数 | HK/US llm-report indices 非空（数据源可用时） |
| C4-3 东财抗限流 | fetcher 补 `User-Agent`/`Referer` + 失败重试退避 + push2 被拒时降级 push2delay | 东财接口在限流窗口内仍能取数（或降级 push2delay 成功） |
| C4-4 akshare 签名适配 | `futures_foreign_commodity_realtime(symbol=...)` 按新签名调用（或改用其他商品源） | 商品数据非恒空 |
| C4-5 PE/PB 备用源 | `fetch_current_pe_pb` 增加备用源（如新浪/其他估值接口）或 24h 缓存上次成功值（对应 R5-10 管道缺陷项） | PE/PB 在 akshare 挂时仍可用（数据源可用时） |
| C4-6 熔断器接线 | 将 akshare/东财调用纳入 SourceRegistry 熔断路径（当前内部直连绕过；对应 R5-10 管道缺陷项） | 东财失败被熔断计数并冷却，health 如实反映 |
