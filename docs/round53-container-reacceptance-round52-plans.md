# round53 容器全链路诊断 — round52 方案 A-F 实施落地复验 + 回归扫描（2026-09-04 周五盘后）

> 本文档为 **round52 复验轮**（独立 round53 文档，不改写被诊断的 round52 文档）。
> 诊断对象：HEAD `5c7a206`（含 round52 方案 A-F 实施 `a83cd9f` + gitignore `5c7a206`，即 round52 诊断之后全部落地代码）。
> 验证环境：Docker Engine 29.7.2，prod profile + diag overlay（PROFILE_WARMUP=1 cProfile）。
> 验证窗口：2026-09-04 周五 18:22-19:25（**盘后**，日频数据已发布；盘中实时类标注「待交易时段复测」）。
> 容器 18:22 启动，18:23:27 warmup 完成（35.6s）；三容器 Up 全程无重启。
> 探针产物：`C:/Users/Public/etf_probe/`（build53.log / probe53_*.py+out / newsall.json / dhc53.out，会话级临时目录不入仓）。

---

## 0. 执行摘要

> **决策状态**：round52 方案 A-F 已于 `a83cd9f` 全部实施。本轮 = 落地后容器复验，
> **R170/R171/R172/R173/R175/R176/R177/R178 修复全部实测生效**（R174 前端 scope 过滤按实现+单测确认，浏览器级走查留待下轮）。
> 新发现 R179/R180（P3×2，低危）；环境项无（build53 零 apt 故障，TUNA 补丁生效）。

### 0.1 核心结论（一句话/项）

| # | 结论 | 状态 |
|---|---|---|
| 1 | **R170 warmup 归因生效**：新格式告警 `[warmup-budget] 预热总耗时 35.6s 超过预算阈值 30.0s…（分段 top3: instruments_sync 25.4s/indices_meta_sync 10.1s/etf_cache 0.2s）——见 logs/warmup_timing.json`；`warmup_timing.json` 新增 `sequence_segments`（7 段全覆盖）+ `sequence_total_ms` + `sequence_uncovered:[]`，35.6s 归因闭环（instruments 25.4s + indices_meta 10.1s = 35.5s） | ✅ 修复确认 |
| 2 | **R171 holdings 市值/份额生效**：check 85（task 30 触发）holdings 15/15 `shares_held`+`market_value` 非空且数值自洽（159338: 58000×1.198=69484 ✓） | ✅ 修复确认 |
| 3 | **R172 base 回退生效**：裸跑（无 --base）`verify_allocation_invariants.py` exit=0 | ✅ 修复确认 |
| 4 | **R173 off 估值链生效**（盘后形态）：`/market/realtime/portfolio` off 15 只 estimate_source=nav 且 **change_pct 全非 0**（round52 时 nav 分支硬编码 0）——nav `daily_change_pct` 接通；盘中 ti 实时估值路径**待交易时段复测** | ✅ 修复确认（盘后形态） |
| 5 | **R176 asset_type 归一生效**：calculate 三形态 on(15)/off(15)/无(30) 现价=0 共 **0 只**（round52 场内 15 只 ¥0.00/+0.00% 消失）；场外 tracked_index 与 ti 场内标的逐只一致（022449=-0.42 ↔ 159338=-0.42；011613=-2.06 ↔ 588000=-2.06） | ✅ 修复确认 |
| 6 | **R175 unavailable 语义生效**（盘后无缺价窗口）：daily-pnl items=15 无 `daily_pnl=None`、无双 0 行；缺价时 None 语义待故障注入单测兜底（TDD 已有用例） | ✅ 修复确认 |
| 7 | **R177 搜索三缺口生效**：sector 创新药=BK1106、index 红利低波=3 条（H30269/H20269/931446）、index 红利=19 条、all 创新药=13 条混合（ETF+板块+指数）；indices_meta 1106 行（round52: 635）；HTTP 层与直调一致性恢复（方案 D 超时包裹生效，无 10s 超时告警） | ✅ 修复确认 |
| 8 | **R178 news/all 生效**：26 条 = headlines 15 + macro 3 + global 8 精确闭合，level 26/26 覆盖（1:1,2:10,3:3,4:7,5:5）、stars 26/26、时间降序至 18:30:30 | ✅ 修复确认 |
| 9 | ~~**R148/R150 真断链维持**~~ → **口径对齐诊断推翻（§7）**：data_health_check 1 FAIL 系检查器裸 compute() 缺 symbol_extra 注入的**口径误报**；生产路径（hub.get_factor_matrix 链路）7/7 critical 因子实测 OK、全候选池 37 只覆盖率 35/35~37/37 | ❌→✅ 检查器缺陷（非生产断链） |
| 10 | **构建环境修复确认**：backend 镜像二次构建 EXIT=0 且 **0 条 pip resolver ERROR**（round52 时 3 条）、无 apt 故障（TUNA 192b8c9 生效） | ✅ 修复确认 |
| 11 | **WS 全链路健康**：直连 `:8000/api/v1/ws/news|portfolio|task-notifications` 与经 nginx `:80` 均握手 101 OK（诊断初期 403 系探针误用裸路径，非回归） | ✅ |
| 12 | **R146 premium_discount 盘后 31/31=0**：维持「待交易时段复测」（round52 §6 拍板#3 留下轮） | ⏳ 维持 |

### 0.2 遗留清单（承接 round52 §4.4）

| round52 遗留 | 本轮状态 |
|---|---|
| ① R146 盘中复测 | ⏳ 维持（盘后无 nav 发布，premium_discount 仍 0） |
| ② off_exchange check 触发 | ⏳ 本轮 task 30 用 on_exchange，off_exchange 仍未触发（维持） |
| ③ patrol --full 长跑 | ⏳ 未复测（时间预算限制，连续 3 轮遗留） |
| ④ R141 持仓市值复测 | ✅ 闭环（R171 落地后 check 85 市值 15/15 非空） |
| ⑤ R170/R171/R172 方案拍板 | ✅ 已实施且本轮实测生效 |
| ⑥ R173-R178 拍板 | ✅ 已实施且本轮实测生效（R174 见 §0.1#8 注） |

---

## 1. 环境构建与启动（阶段 1）

- 构建日志：`build53.log`（1500+ 行），`BUILD_EXIT=0`；无 pip resolver ERROR（历史 3 条为 --no-deps 拆分安装告警形态，本轮连告警都未出现——TUNA 镜像让依赖解析更稳）；无 apt 源故障（192b8c9 补丁验证通过）。
- 前端基础镜像 node:24-alpine 拉取耗时 1351.8s（网络因素，非配置）；npm install 590.3s（deprecated glob 告警为已知形态）。
- 三容器启动 18:22:47，warmup 18:23:27 完成（35.6s，超 30s 预算 → 触发 R170 新告警，见 §0.1#1）；`[warmup] sector list prefetch done (concept/industry, R89)` 正常。
- PROFILE_WARMUP=1 生效：`logs/warmup_cprofile.txt` + `logs/warmup_timing.json` 落宿主。

## 2. 全链路诊断（阶段 2）

### 2.1 端点健康与性能（盘后）

| 路径 | 本轮 | round52 | 阈值 | 判定 |
|---|---|---|---|---|
| /health | 0.23s | — | — | ✅ |
| /market/realtime/portfolio 首呼（冷） | 21.4s* | 1.32s | ≤3s | *urllib 走系统代理失真，curl 复测 warm 0.56s ✅ |
| /admin/factor-health | 1.41s | 4.67s（首呼） | ≤2s | ✅ 好转（性能债清偿：round52 登记的 IC tracker 冷启动已改善） |
| /admin/llm/health | 19.0s | 22.05s | — | ⚠️ 性能债（provider 生态劣化，维持登记） |
| /market/sectors/heat | 2.25s | 2.55s | — | ✅ 维持 |
| /factors/active | 38 条 / zero_ratio_scope=ic_batch | 同 | — | ✅ R166 口径保持 |
| /admin/lifespan-warmup | redis_available=true | 同 | — | ✅ R165 维持 |
| WS 三链路（直连+nginx） | 101 OK | 101 OK | — | ✅ |
| nginx / | 200 / 0.23s | — | — | ✅ |

### 2.2 主动触发新数据验证（延续 round51/52 方法）

1. `POST /portfolio/design-async`（balanced, 500000, enhanced）→ task 29 completed → **design 19** 入库（report_quality=full，31 etf_count）。
2. `POST /portfolio/strategy-check-async`（on_exchange）→ task 30 completed（~80s）→ **check 85** 入库（**llm_layer_ok=true / is_fallback=false**——LLM 层成功，非兜底）。

### 2.3 design 19 层预算复验（R162/R163 维持）

| 方案 | Σetf | cash | 层分布 | budget | GAP | target_amount | 判定 |
|---|---|---|---|---|---|---|---|
| defensive | 1.0000 | .25 | core .45/sat .20/def .10/cash .25 | .50/.20/.15 | 0.0000 | 0/11 mismatch | ✅ |
| balanced | 1.0000 | .28 | core .45/sat .22/def .05/cash .28 | .50/.22/.13 | 0.0000 | 0/10 mismatch | ✅ |
| aggressive | 1.0000 | .10 | core .55/sat .30/def .05/cash .10 | .60/.30/.05 | 0.0000 | 0/13 mismatch | ✅ |

层预算超标：无（三方案）；单只最大权重 0.28 ≤ 30% ✅。与 round52 design 16 数字同构（balanced 完全一致）→ R162/R163 修复稳定维持。

### 2.4 check 85 内容复验（R171 + LLM 层）

- holdings 15/15 `shares_held`+`market_value` 非空且自洽（159338: 58000×1.198=69484；588000: 18800×1.668=31358.4；510880: 9800×3.438=33692.4）；
- summary「市态：震荡；因子覆盖 66.7%」与 market_regime=range_bound 一致；报告含逐标的因子/信号/建议表；
- `llm_layer_ok=true / is_fallback=false`——上游 provider 生态本轮改善（round52 时 502/429 重试链吃满 30s 预算），LLM 层真实成功。

### 2.5 R177 深探记录（先误判后澄清，留方法论教训）

- 诊断初期用 `?q=` 参数搜索 0 条（round52 §8.2 文档简写），一度误判「修复未生效」；纠正为端点实际参数 `keyword`（`market.py:84`）后三缺口全部命中。前端 `api/index.js:43` 实传 `keyword`，无真断裂。
- 深探中顺带实证：indices_meta 1106 行（R177-B 同步生效 + R177-C 静态段红利低波 H30269/H20269/931446 在库）；sectors 表 0 行（R177-A 缓存优先后表仅兜底，符合设计）；`fetch_concept_sectors(600)` 容器内直跑 512 条含创新药 BK1106（外部源盘后可达）。

### 2.6 数据健康（宿主跑 data_health_check）

**11/12 PASS，1 FAIL = 5 个 critical factor 全空**（ln_mcap/ln_float_mcap/shares_change/institutional_holdings_change/industry_diversification）——初判与 round51/52 一致；**后经 §7 口径对齐诊断证实为检查器口径误报**（生产路径 7/7 OK），详见 §7。

### 2.7 已知性能债登记（软门禁，增量）

| 路径 | 本轮 | round52 | 阈值 | 处置 |
|---|---|---|---|---|
| /admin/llm/health | 19.0s | 22.05s | — | ⚠️ 维持登记（略好转，provider 生态探测耗时） |
| /market/sectors/heat 首呼 | 2.25s | 2.55s | — | 观察（好转） |
| patrol --full | 未复测 | >2min | — | ⚠️ 连续 3 轮遗留 |
| ~~factor-health~~ | ~~4.67s~~→1.41s | 4.67s | ≤2s | ✅ 清债 |

---

## 3. 分析结果质量审查（阶段 3 · 四问法）

对 check 85（LLM 层成功）与 design 19（三方案）逐句审查：

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 结论分级 | 修复建议 |
|---|---|---|---|---|---|
| design19「现金仓位 25/28/10%」 | 事实 | 文本三方案现金行 25/28/10 与 cash_row 完全一致；Σ=1.0000 | ✅ | 合理 | — |
| design19 balanced ETF 表（510300 ≈10% 等） | 事实 | strategies_json weight/amt 与文本逐项对应（amt=capital×weight，0 mismatch） | ✅ | 合理 | — |
| design19 文本涨跌引用 | 事实 | vs realtime/portfolio 逐项抽验 0 偏差（>0.35% 阈值） | ✅ | 合理 | — |
| check85「市态：震荡」 | 事实 | market_regime=range_bound；510300 -0.11%/159338 -0.42% 窄幅 | ✅ 一致 | 合理 | — |
| check85「因子覆盖 66.7%」 | 事实 | summary 与报告正文一致 | ✅ | 合理 | — |
| check85 逐标的 shares_held/market_value | 事实 | 15/15 非空，抽 3 只乘积自洽 | ✅ | 合理 | — |
| check85 LLM 建议（买入/减仓） | 推断 | LLM 层成功（llm_layer_ok=true），无兜底混入；factor_breakdown 键在 | ✅ | 合理 | — |
| design19「黄金ETF…维持上涨0.65%」 | 事实 | 518880 daily_change_pct=+0.65 与 realtime 一致 | ✅ | 合理 | — |
| design19 aggressive「159338+563360 同方案并存」（2026-09-04 用户追加） | 事实 | 同跟踪中证A500（563360 tracked_index 脏值 "A50" 致去重键失效）→ Σ25% 同指数敞口；入选理由自曝「同类排名 2/2」 | —（与行情无关，属结构缺陷） | **不合理（R181，P2）** | 方案 C（数据映射修正 + 去重键交叉验证守卫），并入下轮实施小批 |

**汇总**：可采信 8 条 / 需修正 0 条 / 臆断 0 条 / 失效 0 条；**不合理 1 条**（R181，2026-09-04 用户审视追加——诊断阶段四问法未覆盖「结构合理性」维度，见 §4.2 R181 行与模板改进）。

**数据准确性抽查**：权重和=1−现金 ✓✓✓；target_amount=capital×weight ✓；占位检测（RSI 50.0 / 动量 +0.300）未出现 ✓；as_of=2026-09-04 盘后 ✓；balanced `factor_score` 字段为文字评级（「中性」）非数值——1 只显示 None 系 defensive 表样本字段名差异（非占位，不扣分）。

---

## 4. 问题分析与修复方案（阶段 4，只写方案不写代码）

### 4.1 R 系列新发现（本轮 R179/R180，均 P3）

| 编号 | 发现 | 根因机制链（file:line） | 严重度 |
|---|---|---|---|
| R179 | **双 warmup 告警并存**：R170 新格式 `[warmup-budget]`（:744 走 `_format_warmup_budget_warning`）与旧格式 `Warmup took 35.8s (threshold 30s)`（main.py:1261-1268，7.5 P2 遗留）同次超预算时先后输出——同一事实两条告警，观测口径冗余 | `_warmup_sequence_task` finally（:736-748）超预算打新告警；lifespan 尾部 `_warmup_duration = time.time() - app.state._startup_ts`（:1262-1268）再打旧告警。两处计时段不同（sequence 全序 vs startup 至 lifespan 尾）但信息重叠 90% | P3（观测噪音，非缺陷） |
| R180 | **search 空 keyword 不一致**：`kind=symbol|all` 空 keyword 返回 30 条（instruments 全表前 30），`kind=sector|index` 返回 0 条——三种调用方行为不一致；前端 `useMarketSearch.js:62-63` 有 `if (!q) return` 守卫（真实用户不可达），但 MCP/脚本直调可触发 | `market.py:87-91`：`_search_sectors/_search_indices` 对空 kw 直接 `return []`；symbol 段无 kw 时 stmt 不加 where → 全表 limit 30。O30 设计时只对 sector/index 收口 | P3（防御性收口，无真实用户伤害） |
| R181 | **同指数重复配置未被去重**：design 19 aggressive core 层同时持有 159338（中证A500ETF国泰 5%）+ 563360（A500ETF华泰柏瑞 20%）——同一中证A500 指数 Σ25% 敞口；563360 入选理由自曝「同类候选池排名 2/2」（分配器已知同类）；用户 2026-09-04 审视设计方案时发现 | 去重键 = `tracked_index` 归一化 segment（allocation_engine.py:469-485 `_dedup_same_index` 按概念分组）；563360 的 tracked_index 被**记为 "A50"**（正确应 "A500"，design19 strategies_json 实读）→ `normalize_segment("A50")="A50" ≠ "A500"` → 两 ETF 落入不同组 → 去重失效。名称提取层正确（实测 `extract_index_concept("A500ETF华泰柏瑞")="A500"`），脏值出在数据源侧：etf_scanner.py:157 tracked_index 关键词映射（非种子 ETF 运行时提取），"A500" 被截成 "A50" 的映射/正则缺陷待实施轮定位。**去重逻辑本身无缺陷**（锚豁免/同组合并在位），属「写入口径与消费口径无一致性断言」根因类（R163/R177 同型） | P2（分配质量缺陷：25% 单指数集中 + 挤占其它核心敞口；不违反硬风控——单只≤30%/层预算均合规） |

### 4.2 测试防护体系缺口分析

**1) 防护体系现状（本轮实测）**：a83cd9f 新增 9 个测试文件（test_r171/r173/r175/r176/r177/r178/warmup_sequence/r44_allocation + 前端 3 个 spec）全部在位并在 pre-commit 全量 3138 绿中；本轮容器实测与单测断言互证（R171 字段、R177 keyword、R178 去重、R172 回退、R170 分段）。缺口集中在**文档-实现一致性**层（见 2))。

**2) 逐发现映射**：

| 发现 | 最应拦截的防护层 | 为何未识别 | 应补的守卫 |
|---|---|---|---|
| R179 | smoke_startup / lifespan 观测 | 两告警分别有测试（warmup_sequence 覆盖新格式）但无「同窗口旧格式应退役」断言 | 若拍板退役旧告警（方案 A），补负向断言：超预算时日志**不得**再出现旧格式 `Warmup took .* (threshold` 行 |
| R180 | check_routes / 端点级单测 | 空参数形态未入测试矩阵（test_r177 只测真关键词）；前端守卫掩盖了 API 层裸露 | 端点单测补空 keyword × 4 kind 一致性断言（symbol/all 也应返回 []，或 sector/index 返回全量热门——**二选一语义收口**） |
| R181 | 引擎单测（去重）+ design 验收断言 | ① 单测用例的 tracked_index 都是干净值（"沪深300"/"中证A500"），无「"A50" vs "A500" 近形异义」负向用例；② 诊断阶段 3 四问法只做了**内容真实性**抽查（涨跌/权重和/占位值），无「**同指数重复**」结构合理性断言——Σ=1/预算/单只上限全过掩盖了组合结构缺陷 | ① 单测负向：两个 tracked_index 分别为 "A50"/"A500" 的同族候选 → `_dedup_same_index` 必合并（以名称提取交叉验证兜底后）；② patrol/诊断清单加「同方案内 normalize_segment(tracked_index) 唯一性」结构断言（轴：same-index 重复 → 必 FAIL） |

**3) 系统性根因归并**：①「文档简写 vs API 实参」一致性（本轮 R177 误判根因：round52 §8.2 记 `?q=` 而实参 `keyword`，无契约级拦截——归并 round51 R163「写入口径与消费口径无一致性断言」同型，本轮新出现于文档层）；②「多版本并存不退役」（R179，round35 注释收敛同型教训）；③其余历史类（两缓存域/静默降级）本轮**零新增实例**——R173/R175/R176/R177 修复后未复现。

**4) 补齐设计（只写方案）**：

- **方案 A（P3，R179）**：退役 lifespan 尾旧告警（main.py:1261-1273 删除 elif/info 分支，保留 sequence finally 新告警为唯一出口）；或保留旧告警但仅在 `PROFILE_WARMUP=0`（无 timing 数据）时输出。验收负向：mock sequence 35s → 日志恰好 1 条 warmup 告警。
- **方案 B（P3，R180）**：`market.py` search 入口对空 keyword 统一返回 `[]`（:87 前置 `if not kw: return []`），4 kind 行为一致；或按 O30 意图给 symbol 段补空守卫。验收负向：`?keyword=&kind=all` 0 条 + 单测 4 kind 全绿。
- **方案 C（P2，R181，2026-09-04 用户追加）**：同指数重复配置治本，两步——
  - **C-1 数据侧**：定位 etf_scanner.py:157 关键词映射中 "A500→A50" 截断缺陷并修正 563360 映射为 "A500"；全量扫描候选池 tracked_index 脏值（形态：名称含 A500 而 tracked_index="A50"、名称含「科创100」而 tracked_index="科创10" 等截断形态），逐个修正；
  - **C-2 守卫侧（推荐同批）**：`_dedup_same_index` 分组键改为「tracked_index 归一值 ⊕ 名称提取归一值」交叉验证——两者不一致时取名称提取值 + logger.warning（防映射表再漂移）；单测负向：tracked_index 分别为 "A50"/"A500" 的双候选必被合并；
  - 验收：① 重新触发 aggressive 设计 → 三方案内 normalize_segment(tracked_index) 无重复（CASH 除外）；② Σ=1/层预算/单只≤30% 维持全 PASS（R140 钳制在位，去重回补不影响资金守恒）；③ design19 形态（159338+563360 并存）不可复现。
  - 排期：**并入下一轮实施小批**（与 data_health_check 口径修复/R179/R180 同批，2026-09-04 拍板节奏——未收到「round实施」不动代码）。

### 4.3 与 round52 文档的关系

- round52 §0.2 验证矩阵 13 项中 R170/R171/R172/方案D/R164 语义等全部由本轮实测闭合（§0.1 表）；R148/R150 存量断链维持原判。
- round52 §7-§9 方案 A-F 与本轮实测逐项对上（§0.1#4-8）；R174 前端改动以单测+实现确认，浏览器四态走查留待下轮（诚实标注）。
- round52 §2.4 性能债：factor-health 已清偿（1.41s ≤ 2s）；llm/health 维持；patrol --full 三轮未复测维持。

---

## 5. 三轮 Review 记录（阶段 5）

### 5.1 Round 1 — 事实核对

| 项 | 核对 | 结论 |
|---|---|---|
| R170 新告警 | 日志 18:23:27 `[warmup-budget] …（分段 top3: instruments_sync 25.4s/indices_meta_sync 10.1s/etf_cache 0.2s）` 原文摘录 + timing json 7 segments 实读 | ✅ |
| R171 | holdings_json 直读 15/15 + 3 只乘积手工复核 | ✅ |
| R172 | 裸跑 exit=0 实测（宿主，无 --base） | ✅ |
| R173 盘后形态 | realtime/portfolio off 15 只 nav 非零实读 | ✅（盘中形态标注待复测） |
| R176 | calculate 三形态 0 只 0 价 + ti 一致性抽 2 只 | ✅ |
| R177 | keyword 参数 4 组实测 + 容器内 `sed -n 205,275p market.py` 实读 | ✅ |
| R178 | newsall.json 26=15+3+8 闭合 + level 分布实读 | ✅ |
| R162/R163 | design 19 DB 直读 Σ/GAP/mismatch/预算超标 | ✅ |
| R179/R180 | main.py:1261-1273 与 market.py:87-91 实读 | ✅ |
| WS 101 | 直连+nginx 双路径实测（403 定性为探针路径误用） | ✅ |

### 5.2 Round 2 — 逻辑一致性

- §0.1#4「R173 盘后生效」与盘中 ti 估值路径**不矛盾**：盘后走 nav `daily_change_pct`（round52 §7.3 方案 B），盘中走 quotes 内 ti 实时价（方案 A）——两分支独立，盘中分支标注「待交易时段复测」不矛盾。✅
- §0.1#7 R177「HTTP 层与直调一致」与 §2.5 初期 0 条记录自洽：0 条系探针参数误用（q= vs keyword），非代码断链——§2.5 已如实记录误判与澄清过程。✅
- §2.3 design19 与 round52 design16 数字同构（balanced 层分布完全一致）说明分配器输出稳定，R162/R163 无回归。✅
- check85 `is_fallback=false` 与 round52「openrouter 48.4% err」不矛盾：本轮 provider 生态改善（L07 兜底 + excluded 机制），LLM 层真实成功。✅

### 5.3 Round 3 — 完整性

- 验证窗口标注：R173 盘中路径 / R146 premium_discount 均标「待交易时段复测」（§0.1#4/#12）。✅
- 未复测项诚实标注：R174 浏览器四态走查、patrol --full、off_exchange check（§0.2）。✅
- 未决项清单：① R146 盘中复测（下轮）② R173-A 盘中复测（下轮交易时段）③ patrol --full（→ 已拍板关闭，§6#4）④ R179/R180 拍板（→ 已拍板暂缓，§6#1/#2）⑤ R148/R150 critical 断链（→ §7 已推翻定性，待检查器口径修复拍板）。均入 §0.2/§4.1/§6。✅
- 诊断合规性：本轮全程未写修复代码（唯一产物 = 本文档 + 探针脚本不入仓）。✅

**结论**：三轮 review 通过，文档达到「方案轮定稿」标准。

---

## 6. 决策点（2026-09-04 用户已拍板）

> **拍板结果**：#1/#2 暂缓登记；#3 选「先口径对齐诊断」；#4 关闭遗留。
> 拍板与推荐不一致处：#1/#2 未采纳「合并实施」推荐——维持已知存量观察，不写代码。

| # | 决策 | 拍板 | 状态 | 落实 |
|---|---|---|---|---|
| 1 | R179 双告警去留 | **暂缓**（不退役旧告警，登记观察） | 📋 已登记 | 双告警并存为已知观测噪音；若后续观测受扰再启动方案 A |
| 2 | R180 空 keyword 收口 | **暂缓**（登记观察） | 📋 已登记 | API 层裸露 + 前端守卫在位；真实用户不可达，不投入 |
| 3 | R148/R150 critical 断链 | **先口径对齐诊断**（推荐采纳） | ✅ 诊断完成（§7 推翻定性）+ **修复方案拍板：并入下一轮实施小批（与 R179/R180 及后续 P2/P3 小批合并），不马上实施** |
| 4 | patrol --full 长跑 | **关闭遗留**（推荐采纳） | ✅ 已闭环 | 依据：`git diff a83cd9f..5c7a206` 仅 .gitignore +4 行，实施轮已跑全量 3139 绿 + patrol——复测对象零变化；规则改为「下次代码变更交付时照常跑」 |

---

## 7. 决策#3 执行：R148/R150 口径对齐诊断（2026-09-04 用户拍板「先口径对齐诊断」，只读实验）

### 7.1 三口径盘点

| 口径 | 测法 | 数据注入 | 结果 |
|---|---|---|---|
| ① data_health_check `test_factor_chain_integrity`（:284-358） | 对 4 只代表 ETF **裸 `FactorRegistry.compute()`**（无 symbol_extra） | 无 Z04 注入（fund_scale/industry/shares_change_20d 全缺） | 5 因子 0/4 → FAIL |
| ② round41 交易复测（memory 429a17c + eb319fe） | 盘中生产路径（symbol_extra 注入） | 经 `_build_symbol_extra`+`_enrich_symbol_extra` | 6/7 OK（shares_change 因 akshare 列名 bug 除外） |
| ③ 本轮生产全链路（§7.2 实验②） | `hub.refresh()` → `get_pool()` → factor_scores（与 design 管线同源） | 完整注入（fund_scale 真值 + 份额源） | **7/7 OK** |

### 7.2 双路径对照实验（2026-09-04 盘后实测，宿主 backend cwd，产物 caliber.out/caliber2.out）

**实验①**（裸 compute vs 手工补注入）：
- 路径 A（裸 compute，= 检查器口径）：premium_discount 4/4 ✅、news_heat 4/4 ✅、**ln_mcap 0/4、ln_float_mcap 0/4、shares_change 0/4、institutional_holdings_change 0/4（值=0.0 占位）、industry_diversification 0/4（值=0.0）**——与检查器 FAIL 输出逐项一致；
- 路径 B（`_enrich_symbol_extra` 注入后 compute）：shares_change 0/4→**4/4**（-5.66/-2.07 真值）、institutional_holdings_change 0/4→**4/4**（×0.5 代理生效）——Z04 注入差异是这两因子「断链」的全部根因；
- 注：实验① B 路径 fund_scale/industry 用 0/unknown 占位（非生产真值），故 ln_mcap/industry_diversification 仍 0/4——由实验② 定案。

**实验②**（生产全链路 `hub.refresh()` → `get_pool()`）：**7/7 critical 全 OK**，全候选池 37 只覆盖率：
`premium_discount 37/37、ln_mcap 36/36、ln_float_mcap 36/36、shares_change 35/35、institutional_holdings_change 37/37、news_heat 37/37、industry_diversification 37/37`（抽样 510300 全 7 项有值：ln_mcap 9.3841 / shares_change -1.6136 / industry_div 3.0209 等）。

### 7.3 结论：5 因子「断链」定性推翻

1. **生产链路无断链**——7 个 critical 因子在真实 design 管线取数路径下全部有值（35/35~37/37）；data_health_check 的 FAIL 只反映「裸 compute 无注入」这一检查器自身的取数方式，**不反映生产现实**；
2. **历史结论修正**：round51/52「critical 断链 FAIL 与 round51 一致」实为连续 3 轮对同一检查器缺陷的复读——检查器自 round40 B 方案落地起即带此口径缺陷，从未与生产口径交叉验证（**检查器可信度缺口**：门禁自己从未被验过生产等效性）；
3. **round41 记忆与检查器无矛盾**：「6/7 OK」用生产路径（注入），shares_change 0/4 系当时 akshare 列名 bug（eb319fe 已修，本轮实测 35/35 恢复）；
4. **遗留真问题只有一条**：检查器与生产口径不等效——修复属**门禁治理**（小批），原估「5 因子 × 5 数据源接入治本轮」不再需要。

### 7.4 检查器旁证缺陷（顺带发现）

`test_factor_chain_integrity` docstring 声称「非交易时段全 None 属预期，全空时输出 WARN 不计入 FAIL」（data_health_check.py:272-274）——**代码实际无条件 FAIL**（:346-352 无时段分支），注释与实现矛盾（R171「文档 vs 实现漂移」同型）。

### 7.5 治本范围重估（供后续拍板）

| 项 | 原估 | 重估 |
|---|---|---|
| 5 因子 × 5 数据源接入治本轮 | P0/P1 独立轮（大） | **不需要**——生产链路已全通 |
| data_health_check 口径修复 | — | P2 小批：`test_factor_chain_integrity` 改走 hub.refresh→get_pool（或裸 compute 补 symbol_extra 注入）+ 非交易时段 WARN 分支兑现 docstring + 负向断言；改后 data_health_check 应 12/12 |
| 观测口径纪律 | — | 检查器结论入 round 文档前先做「生产等效性」交叉验证（本轮教训，归并「门禁存在但未实际执行/从未验过等效性」根因类） |

> **实施排期（2026-09-04 用户拍板）**：上述 data_health_check 口径修复（P2）**并入下一轮实施小批**，与 R179（双告警退役）/ R180（空 keyword 收口，均现为暂缓登记、若解禁则同批）及后续累积的 P2/P3 小批合并执行——**不马上实施**，未收到「round实施」不动代码。

---

## 8. 追加发现（2026-09-06 用户审视因子模型页，R182/R183 + IC 积累方案拍板）

### 8.1 现象与定性：因子模型页 6 个「无数据」= 统计纪律的诚实表达，非故障

用户在因子模型 tab 看到 6 个因子「无数据」。API 实测（`/factors/active`，2026-09-06 20:40）`summary.no_data=6`，逐个对应：
`etf.premium_discount`（9/250 天）、`etf.shares_change`（9/250）、`etf.institutional_holdings_change`（9/250）、`etf.industry_diversification`（1/250）、`style.size.ln_mcap`（1/250）、`style.size.ln_float_mcap`（1/250）。

**定性：合理（时间问题，非缺陷）**。这 6 个因子的 IC 记录从修复接通日才开始积累（round51 `a9f704d` → 8-28 起首批；round52 R150 桥接 → 9-06 首批），IC 显著性需 ≥250 交易日（t≥2 对齐业内样本量）、60 天为可观察下限（`factor_status.py:22-23, 98-100`）。样本不足时标「积累中（n/250）」而非假装显著，正是「统计说话」原则的兑现。**用户拍板采纳方案 A：自然积累，不回填**（premium_discount 等依赖盘中注入，历史回填样本质量与真实积累不等价）。

同页 12 个 `static`（3 政策 + 9 市场级宏观/情绪因子）同理非缺陷——全市场单一值 → 截面恒等 → 无 IC 语义（`factor_status.py:36-53`，round9 P1-10 / round13 §3.1 P2 设计决策），状态文案已带原因。

### 8.2 R182（P3，前端文案失真）：`no_data` 显示「无数据」误导用户

**现象**：同一页面出现语义分裂——显著徽章列显示「积累中」（:164）、横幅解释「积累未满」（:90），但用户最先看到的 **5 处**大字写「无数据」：统计卡标签（:62）、分类徽章「6 无数据」（:210）、IC 值列（:253）、警示行（:261）、排序表 IC 列（:307）。用户连续两次截图质疑（本节起因），证明第一眼印象被误导。

**根因**：`no_data` 状态的 UI 文案直接用了状态码直译，未对齐 reason（后端 reason 已精确到「IC 积累中（9/250 交易日，未达可观察下限 60）」——`factor_status.py:99`）。

**修复方案（前端 `frontend/src/views/system/FactorModelView.vue`，5 处文案 + 1 处分流）**：
- :62 统计卡标签 `无数据` → `积累中`；:210 分类徽章 → `N 积累中`；:253 / :307 IC 值列 → `积累中`；:261 警示 → `⚠️ 积累中`；
- **分流守卫**：`no_data` 还有「数据源未接入」「截面无差异（常量输出）」两个少数分支（`factor_status.py:94-97`）——按 reason 关键词分流：含「积累中」→ 显示「积累中」，否则 → 「待接入」（这两类显示「积累中」同样失真）；
- 保留：reason tooltip、:90 横幅、:164 徽章（均正确）。
- 验收负向：6 个积累因子页面任何位置不得出现「无数据」字样；「数据源未接入」类仍显示「待接入」而非「积累中」。

### 8.3 R183（P3，口径灌水）：ic_tracker 非交易日落 IC 记录

**现象**：2026-09-06 为周六（非交易日），`factor_ic_records` 仍落 31 因子记录（`trade_date='2026-09-06'`，computed_at 09:09/12:40——用户访问触发 compute 实跑）。`_beijing_today()`（ic_tracker.py:27-30）只做时区换算，**无交易日历校验**。

**影响**：非交易日记录混入使「n/250 交易日」口径缓慢灌水（每个周末 +1），稀释 t 统计的样本语义；与 `_last_trading_day_hint()`（份额源周末回退）等既有交易日纪律不一致。

**修复方案**：`record_periodic_ic` 入口加交易日校验——复用 `market_calendar` 判 A 股交易日，非交易日跳过落库（或落库但标 `is_trading_day=false` 供统计排除，推荐前者，语义干净）。验收负向：周末/节假日触发 compute 不产生新 `factor_ic_records` 行。

### 8.4 下轮实施小批清单（更新版，全部待「round实施」触发）

| # | 项 | 级别 | 来源 |
|---|---|---|---|
| 1 | data_health_check 口径修复（§7.5） | P2 | round53 §7 |
| 2 | R181 同指数重复配置（方案 C：映射修正 + 去重键交叉验证） | P2 | round53 §4.1 |
| 3 | R182 因子页 no_data 文案统一「积累中」+ 分流 | P3 | 本节 |
| 4 | R183 ic_tracker 交易日历校验 | P3 | 本节 |
| 5 | R179 双告警退役 / R180 空 keyword 收口 | P3 | 暂缓登记，解禁后同批 |

---

## 9. 用户需求追加：行情分析 LLM 对话支持追问与多轮（2026-09-06 晚）

### 9.1 需求合理性与可行性

**判定：合理，且高 ROI**——项目已有完整流式/护栏基础设施（`useLLMStream` composable、SSE 协议、OpenAI 兼容多 provider 故障转移、agentic 护栏 v7、$0.5/run 预算熔断），**不是在零基础上搭多轮，是在现有 stream 端点上叠一层会话管理**。

**痛点对照**：
- 当前 `AiAdvisor.vue` 是单轮（`response: ref('')` 覆盖式），投资人看完报告想追问"为什么这么说？换成 510300 呢？"得手动重发、AI 每次从零读数据、体验断；
- `llm-advice/stream` 接收单 `{query, market}`，无会话历史注入——是设计漏，不是技术难。

**风险点**：
- token 累积爆炸 → 必须轮数截断 + 上下文窗口管理；
- 上下文采集 5s+ 每次重跑成本高 → 必须缓存本会话市场快照；
- 越权改持仓/调组合风险 → 沿用 v7 写确认门 + 工具白名单。

### 9.2 实现方案（4 阶段可分批）

#### 阶段 1+2：会话级最小实现 + SQLite 持久化（**拍板：一起落地**）

**会话模型**：内存 `ChatSession`（LRU 上限 100，TTL 30min 无活动过期）+ SQLite `chat_sessions` 表（24h TTL 落盘，启动时加载到内存作 L1 缓存）。两层结构：内存层是热路径（每次追问先查），SQLite 层负责重启恢复与跨设备访问。

**会话级接口**：
1. **后端**（`backend/app/services/chat_session.py` 新增 + `backend/app/routers/analysis.py` 改）：
   - `ChatSessionStore`（内存 LRU + SQLite 持久化双层）：`session_id → List[{role, content, ts, tool_calls?}]`，LRU 100 会话防内存爆，TTL 30min 无活动过期；
   - SQLite `chat_sessions` 表（`session_id` PK / `user_id` nullable / `created_at` / `updated_at` / `messages_json`（压缩存的 messages 数组）），24h 自动归档清理（参考 round33 P-cleanup 机制）；
   - `LLMAdviceRequest` 加 `session_id: str | None`（None=开新会话，后端在 `done` 事件 metadata 返回新建 id）；
   - 上下文构建把历史消息拼进 messages（prompt 模板新增 `{{ chat_history }}` 槽），**只注入最近 10 轮 + 总 token ≤ 8K**（超出截断），其余保留在持久层不丢；
   - 上下文缓存：本会话的 `index_realtime / sector_momentum` 在 chat_session 内复用，**避免追问时 5s 数据采集重跑**——首次轮完整采集，后续轮在缓存基础上更新（行情+板块快照 60s 内复用）。
2. **前端**（`AiAdvisor.vue` + `useLLMStream.js` 微调）：
   - `messages: ref<Array<{role, content, ts, tool_calls?}>>` 替代 `response: ref('')`，渲染消息气泡列表（用户右对齐灰底 / 助手左对齐 brand 蓝左条），跟随流式 token 追加到最后一条；
   - 现有 `useLLMStream` 接口加 `sessionId: ''` 参数；新会话（null）触发后端开新会话，`done` 事件回传 `session_id` 保存到 `ref` 用于追问；
   - **多会话支持**：本地维护 `sessions: ref<Array<{id, title, lastTs}>>` 侧边栏（轻量），点切换会加载该会话历史；
   - 输入框置底，loading 时 disable 但历史消息照常可读。
3. **护栏继承 v7**：
   - 单会话步数 ≤ 8、轮数 ≤ 10、历史 token 上限 8K（超出截断最旧轮）；
   - 单次成本仍按 $0.5 截断整会话非单轮；
   - 追问里的工具调用走 v7 MCP 白名单（quote/factor/portfolio/news）；
   - 写操作（改组合/下单）必须显式 confirm——v7 写确认门直接复用。
4. **测试覆盖**：
   - 多会话并发：模拟两个 session_id 并行问答，结果互不污染；
   - 上下文截断：注入 12 轮历史验证只保留最近 10 轮；
   - 持久化恢复：写入后重启进程（或切换新实例）应能读到原会话；
   - TTL 过期：会话 24h 后自动归档清理（用 monkeypatch 时间）；
   - 预算熔断：累计成本超 $0.5 必须截断。

#### 阶段 2：SQLite 持久化（P3，**非必须**）
- `chat_sessions` 表：session_id / created_at / updated_at / message_count（content JSON 压缩存）；
- TTL 24h 过期归档（参考 round33 P-cleanup 机制）；
- 页面刷新/重启可恢复上下文。

#### 阶段 3：UI 增强（P3）
- markdown 渲染气泡（代码块、表格）+ 复制/重新生成按钮；
- 「导出对话」按钮（剪贴板 / .md 文件）；
- 快捷键：`Cmd+K` 清空 / `↑` 翻上一题。

#### 阶段 4：智能特性（P4）
- 自动会话标题（前两轮 LLM 抽 5 词内标题）；
- sqlite-vec 跨会话语义检索；
- 自动场景化引导（持仓变动时主动问"是否重评估"）。

### 9.3 待拍板取舍（2026-09-06 晚 用户拍板：完整 B）

| 项 | 拍板 |
|---|---|
| 实施范围 | **阶段 1+2**（最小闭环 + SQLite 持久化） |
| 上下文窗口 | **最近 10 轮 + 8K token**（更连贯） |
| 持久化 | **SQLite 24h TTL** |
| 并发 | **多会话 + session_id**（直接做，避免 v2 返工） |

**结论**：阶段 1 + 2 同步实施（会话管理与持久化一并落地，避免分两批返工 + 测试联调成本），上下文窗口取 8K/10 轮的「连贯优先」档（与 GPT/DeepSeek 上下文窗口充裕度匹配），SQLite 24h TTL 走消息压缩 JSON + 启动加载。背景估时 5-8 人工时。

### 9.4 实施排期（更新版小批清单）

| # | 项 | 级别 | 来源 |
|---|---|---|---|
| 1 | data_health_check 口径修复 | P2 | round53 §7 |
| 2 | R181 同指数重复配置（方案 C） | P2 | round53 §4.1 |
| 3 | R182 因子页 no_data 文案统一「积累中」+ 分流 | P3 | round53 §8 |
| 4 | R183 ic_tracker 交易日历校验 | P3 | round53 §8 |
| 5 | R179 双告警退役 / R180 空 keyword 收口 | P3 | 暂缓登记，解禁后同批 |
| 6 | **LLM 对话多轮追问（阶段 1）** | **P2** | **本节 §9.2** |

排入下轮「round实施」按 P2 优先序执行：1 → 2 → 6。

---

*诊断产物：C:/Users/Public/etf_probe/（build53.log + probe53_*.py/.out + newsall.json + dhc53.out + caliber.out/caliber2.out，会话级临时目录）；容器于诊断完成后回收。未收到「round实施」不写修复代码。*
