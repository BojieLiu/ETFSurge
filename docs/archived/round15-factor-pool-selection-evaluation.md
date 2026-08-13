# Round15 — 候选池选择方式与因子打分体系科学性评估及修复方案（2026-08-10，2026-08-11 review 修订）

> **状态**：方案文档，**未实施**（仅分析与设计，不含代码改动）。2026-08-11 经多轮 review：修正 §4.1/§4.2/§4.4/§4.5 事实错误（KDJ 非 raw、fund_scale 单位=亿、±5.0 clip 归因、layer_count 按策略区分），细化 §5 方案一/二/三/四与 §10 9-F1/9-F2 至实施标准，统一 §6/§11 批次表。
> **性质**：对话评估结论归档。评估对象 = 候选池生成链路（`etf_scanner` + `market_data_hub`）与因子打分体系（`factor_registry` + `aggregate_factor_scores` + `_compute_composite`）。
> **内容**：① 三层科学性评估结论；② 3 个真实缺陷的证据链（file:line 锚点）；③ 对应修复方案设计（含伪代码）；④ 附带发现（双重标准化）；⑤ 落地顺序与验收口径。
> **实施约束**：按本文档分批实施，每批独立 commit、可回退；任何改动须保住 `verify_e2e.py` 全 PASS + 负向断言测试（防假完成）。

---

## 1. 结论速览

| 维度 | 评价 | 关键锚点 |
|---|---|---|
| 工程韧性 | ⭐ 优秀（多源/熔断/兜底/强制保底） | `market_data_hub._refresh_impl`（L476） |
| 粗筛（流动性优先） | ⭐ 专业，符合 ETF 投资第一原则 | `etf_scanner.layer_ranking`（L601） |
| 候选池数量（漏斗/容量） | ✅ 漏斗逐级收窄、余量 2.5:1 合理；**容量魔法数无校准**（并入阶段二） | `full_pipeline` top_n=25（L855）/ `MAX_PER_LAYER`（L142） |
| 因子计算广度 | ⭐ 33 维 + 真值保留（`_raw` 键） | `factor_registry.compute`（L1399） |
| 精排（composite） | ⚠️ **量纲魔法数与单位错配 → 流动性/规模分量死值（≈0），第二排序维度失效**（2026-08-11 修正：非「规模主导」，见 §4.2） | `_compute_composite`（L940） |
| 因子聚合 | ⚠️ **raw 值污染 + 等权 + 方向性缺失** | `aggregate_factor_scores`（def L1047，聚合 L1078-1098） |
| 优化闭环 | ⚠️ **IC 有跟踪无反馈，权重无校准** | `ic_tracker` / `_LAYER_WEIGHTS`（L119） |
| 分配器（下游消费链） | ⚠️ **只调预算、不调选择——core 层熊市无绝对防线**；组合风险参数零接线（§9） | `_select_and_weight`（L272）/ `RiskSettings`（risk_controls L31） |
| 候选池入口数据质量 | 🔴 **P0 单位 bug：amount 万元被当元比较 → 真实活跃 ETF 全被误杀、僵尸标的放行（§4.6）** | `filter_etfs`（L554）/ `_tencent_gtimg_chunk`（L214） |

**一句话**：工程上稳健可用；量化上属「有数据的启发式排序」，缺量纲对齐、方向处理与 IC 驱动权重优化三步。**下游分配器延续同一缺口：市态只改预算不改选标的，组合风险（相关性/波动/回撤）声明而未接线；进攻方案核心层存在"熊市死拿高 beta 成长宽基"风险（详见 §9）。**

---

## 2. 评估对象与范围

| 模块 | 函数 | 职责 |
|---|---|---|
| `backend/app/fetchers/etf_scanner.py` | `fetch_all_etfs_base` / `filter_etfs` / `classify_etf` / `layer_ranking` / `full_pipeline` | 全市场扫描 → 过滤 → 粗分类 → 层内 Top 25 |
| `backend/app/services/market_data_hub.py` | `refresh` / `_refresh_impl` / `_assign_layer` / `_compute_composite` / `_balance_by_industry` / `_deduplicate_by_index` / `_ensure_mandatory` | 因子打分、5 层归层、均衡化、截断、强制保底 |
| `backend/app/factors/factor_registry.py` | `compute` / `aggregate_factor_scores` / `_standardize` | 33 维因子计算 + 标准化 + 顶层键聚合 |
| `backend/app/engine/` | `allocate` / `budgets` / `risk_controls` | 消费候选池与因子分做最终分配 |

评估边界：**主文档评估"选什么进池子"与"因子分如何排序"的选择科学性**；分配器 `allocate()` 及其消费链（层预算 / 层内优选 / 风控管线）的评估见 **§9**（含熊市 behavior 分析）。

---

## 3. 现状评估：合理的设计（保持不动）

| 设计 | 位置 | 为什么合理 |
|---|---|---|
| 规模+成交额粗筛 | `layer_ranking` L622-646（30% 成交额百分位 + 70% 规模百分位） | ETF 投资第一约束是流动性：规模大 → 冲击成本小、跟踪误差小、清盘风险低。粗筛目的本来就是淘汰"不可交易"，不是选"最优" |
| 混合归一化 `z*0.7 + mm*0.3` | `compute` L1512-1527 | 解决经典问题：截面全负 z-score 时头部标的仍得正分 |
| 市态感知权重切换 | `_LAYER_WEIGHTS` L119-138 + `_normalize_regime` | bull/bear/correction 换权重方向正确 |
| 行业均衡化 | `_balance_by_industry` L979-1021（segment 分组取 top1） | 防单一行业霸榜，符合分散化目标 |
| 强制保底 + last-good-pool | `MANDATORY_CODES` L108 / `_refresh_impl` L660-688 | 工程韧性扎实 |
| `_raw` 键真值保留 | `compute` L1499-1501 | 报告展示用真实 RSI/MACD，杜绝 z-score 值被当原始值展示（R6-F4 已修复的同类问题） |

---

## 4. 真实缺陷（证据链）

### 4.1 【严重】缺陷一：technical 聚合量纲污染 + 方向性缺失

**锚点**：`factor_definitions.yaml`（`rsi_14` 等 `standardization: raw`）→ `compute` L1471（裸键原样写入 0-100）+ L1492（raw 因子跳过标准化）→ `aggregate_factor_scores` L1078-1098（`technical.` 前缀等权求均值）。

**机理**（已核实源码 + yaml，2026-08-11 review 修订）：

```
生产链路（_CORE_FACTORS，factor_registry L691-744）technical 类共 15 因子：
  sma_5/10/20/60、macd、bandwidth、vol_ratio、atr_14、vwap、
  kdj.k_value/d_value/j_value、signal.overall  → 14 个 zscore（z 经 clip ±5.0 后混合归一化，量纲 ±19）
  rsi_14                                       → 1 个 raw（0-100 原始值）★唯一污染源
technical 顶层键 = Σ(所有 technical. 前缀非零键) / N    ← 等权均值（aggregate_factor_scores L1098）
```

**（review 纠偏）**：原文档称「RSI-14/24、KDJ K/D/J（standardization=raw）」为**事实错误**——
1. **KDJ 六个 code（k/d/j 及 k_value/d_value/j_value）在 `factor_definitions.yaml` 中全部为 `zscore`**，走 zscore 混合归一化路径（量纲 ±19），不产生 0-100 污染；
2. **`rsi_24` 虽在 yaml 声明 `raw`，但不在 `_CORE_FACTORS`（L691-744）**，生产链路（market_data_hub 调 `compute()` 时不传 codes）默认不计算，不参与 technical 聚合；
3. 实际 raw 污染源**只有 `rsi_14` 一个**——但 technical 均值分母恰为 15（technical 类因子总数），RSI=70 的单个贡献仍达 ≈70/15≈4.67 分（z-score 因子截面均值≈0），**「0-100 基底值主导均值」结论依然成立**（数值近似不变，污染源范围收窄）。

**后果**：
1. **0-100 基底值主导均值**：RSI=70 的标的光 rsi_14 一项为 technical 均值贡献 ≈70/15≈4.67 分，而全部 z-score 因子的贡献均值是 0 → 区分度被基底淹没。
2. **方向性缺失 → 奖励追高**：RSI>70（超买）贡献高分；且与自身 `signal.overall` 矛盾——`_compute_signal_overall`（factor_registry L311，RSI 分段 L316-323）明确 `RSI>70 → score -= 0.4`（超买减分），而 raw RSI 聚合路径却在加分（`technical.signal.overall` 本身也进 technical 聚合，同池内自相矛盾）。**两个信号互相打架**。
3. **（原「KDJ 双重叠加」删除）**：KDJ 为 zscore，无 0-100 污染；但其方向性同样缺失——KDJ 超买（K/D/J 高位）在 zscore 中为正值加分，与均值回归哲学相悖，归入方案一「方向化」一并处理（KDJ 用 zscore 自身符号处理而非 neutral_value 变换，见 §5.1）。

**判定**：数值 bug 级问题（非风格偏好）。语义上"超买=负信号"在系统内已有明确先例（signal.overall），raw 聚合路径未对齐。

### 4.2 【严重】缺陷二：composite 量纲魔法数与数据源单位错配 → 流动性/规模分量被压成死值（≈0），第二排序维度失效

**锚点**：`_compute_composite` L968-974（完整代码见 L940-976）：

```python
score = w["factor"] * factor_sum                # factor_sum = 4 顶层键和（technical/momentum/valuation/sentiment），常态 ±10 内
      + liquidity_weight * amount * 1e-9        # ← 魔法数：amount 数据源单位=万元（腾讯源）
      + scale_weight * scale * 1e-9             # ← 魔法数：fund_scale 数据源单位=亿（缓存实证）
      + (opp，仅非 core 层)
```

**实证（2026-08-07 缓存 `backend/data/etf_list_cache.json`，同一份数据）**：510300 `amount=447469（万元）`、`fund_scale=1193.85（亿）`；588000 `amount=774023（万元）`、`fund_scale=906.21（亿）`；159516 `amount=488980（万元）`、`fund_scale=407.37（亿）`。代入上式：

- `amount × 1e-9 = 447469 × 1e-9 ≈ 4.5e-4` → ×liquidity(0.20) ≈ **0.0001 分**；
- `scale × 1e-9 = 1193.85 × 1e-9 ≈ 1.2e-6` → ×scale(0.25) ≈ **0 分**；
- 故 composite ≈ `w["factor"] × factor_sum` —— **排序实际纯因子主导**。

**（review 纠偏，重大）**：原文档判断「规模实际主导排序」**已被实证推翻**。原机理假设「若 `fund_scale` 单位为元：2000 亿（2e11）×1e-9 = 200 → 规模项超因子分一个数量级」——实测 `fund_scale` 单位是**亿**（非元），`*1e-9` 与数据源单位错配，**规模项被量纲压成 ≈0**。量纲错配的根因结论不变，但方向相反：不是「规模主导」，而是「规模/流动性维度被压成死值、完全失效」。

**后果**：
1. **第二排序维度失效，粗筛与精排脱节**：`layer_ranking` 粗筛用「30% 成交额百分位 + 70% 规模百分位」排序（L622-646），而精排 composite 的 liquidity/scale 项≈0 → 粗筛淘汰「不可交易」后，精排只按因子分排序，**粗筛的流动性/规模信息在精排中全部丢失**——流动性好的大 ETF 与流动性差的标的在 composite 上无法区分（原文档「两层排序高度同源、精排几乎无增量信息」同样不成立，两层从「重复」变成「脱节」）。
2. **静态兜底标的独享流动性分（同池两种 amount 口径）**：`WIDE_BASIS_STATIC`（etf_scanner L65-88）amount 单位为**元**（如 510300 `2_000_000_000`）→ `amount×1e-9 = 2.0` → ×0.20 = **0.4 分**；腾讯源真实标的 amount 单位为**万元**（447469）→ ≈0 分。**同一候选池两种 amount 口径并存，静态兜底标的流动性分虚高**——这是 §4.6 单位 bug 在 composite 层的第三处复现（§4.6.2 缺陷二只覆盖了 `layer_ranking` 的 `max_amount > 100000` 判定，未覆盖此处）。
3. **权重比例无真实语义**：`_LAYER_WEIGHTS`（L119-138）的 factor/liquidity/scale 权重（如 core bull 0.55/0.20/0.25）中后两项对真实数据（万元/亿）实际为**死值**，仅 factor 权重生效——「偏好比例」的含义从未成立。
4. **P6 非交易时段分支同样失真**（L958-965）：`liquidity_weight 减半、scale_weight 增补 liquidity 的一半`——意图「非交易时段以规模排序为主」，但 scale 单位亿 → scale_weight 再大也 ≈0，该分支形同虚设。

**判定**：与 §4.6 同源的「数据源单位契约缺失」在 composite 层的表现；修复方向不变（方案二统一量纲，§5.2 已按实证重写）。注意 **amount 单位修复（方案四）会先让 liquidity 项恢复区分度**（4.47e9×1e-9=4.47），而 scale 项仍死——见 §5.4 连锁反应。

### 4.3 【中】缺陷三：权重无实证闭环（有度量、无优化）

**锚点**：`_LAYER_WEIGHTS` L119-138（手调）vs `ic_tracker`（有跟踪）。

**机理**：
1. `_LAYER_WEIGHTS` 的 0.55/0.40/0.25 全部是启发式，无校准来源。
2. `ic_tracker` 持续计算 33 因子 IC，但 **IC 从不反馈到聚合权重或排序权重**——只用于管理端展示。
3. 33 因子等权聚合（`aggregate_factor_scores` L1078-1098）隐含"所有因子同等重要"假设；高相关因子（sma_5/10/20/60）隐性重复计权。
4. IC 长期为负（有效性反转）的因子仍照常计分，无剔除/翻转机制。

**最可惜**：度量基础设施已建好，只差"IC 加权聚合 / IC 衰减 + 权重校准"闭环。

### 4.4 【附带发现】双重标准化

**锚点**：`compute` L1526-1527（`combined * 5.0` 混合归一化）→ pool `factor_scores` → `get_factor_matrix`（market_data_hub L1568-1581）→ `_normalize_matrix` L1499-1555（再次截面 z-score）。

**数据流（已核实源码，2026-08-11 review 修订）**：
1. `compute()` 返回原始 3 段键（39 项，`_CORE_FACTORS` L691-744）；
2. `aggregate_factor_scores`（L1046-1101）返回**「原始键 + 4 顶层键」并集**（`result = dict(factor_scores)` 保留全部原始键，再附加 technical/momentum/valuation/sentiment）→ pool `item["factor_scores"]` 同时含 `technical.rsi.rsi_14`（0-100 原始值）与 `technical`（聚合均值）；
3. `_compute_composite`（L946-949）只取 4 顶层键求和（P0-4 注释「避免原始点分键双倍计数 + RSI=50 主导排序」——已知问题，未根治）；
4. `get_factor_matrix`（L1568-1581）从 pool `factor_scores` 构建 `{symbol: {全键}}` 矩阵 → `_normalize_matrix`（L1499-1555）对**非 raw 键**再做截面 z-score（raw 跳过 L1539-1541）→ `allocate()` 消费。

**机理**：池内 `factor_scores` 已是 compute() 混合归一化的产物（z-score 因子量纲 ±19、rsi_14 为 0-100 raw），`_normalize_matrix` 又对顶层键与 z-score 原始键做一次截面 z-score。

**影响**：
- 纯 z-score 部分数学上满足 `z(z(x)) = z(x)`（线性变换无损，无实际危害）；
- 但 min-max 分量（0.3 权重）经二次 z-score 后比例失真；4 顶层键（technical/momentum/valuation/sentiment）同样被二次截面 z-score；
- **（review 纠偏）**：原文档称「两处 clip 阈值独立（compute ×5 vs `_normalize_matrix` ±5.0）」不实——±5.0 winsorization 在 `factor_registry._standardize`（L27 `ZSCORE_CLIP_BOUND = 5.0`，L65-75），`_normalize_matrix` 内无 clip；
- **后果**：`allocate()` 排序用的 `get_factor_matrix()`（二次 z-score 口径）与 `factor_breakdown` 展示的 pool `factor_scores`（混合归一化口径）是两套口径，展示分与排序分可能不一致；且 `_select_and_weight` L344 对矩阵再调 `aggregate_factor_scores` 为幂等 no-op（4 顶层键无点分前缀），属历史遗留冗余调用。

**建议**：独立立项做"唯一真实来源"收敛，不并入方案一/二/三。

### 4.5 【评估】候选池生成数量合理性（2026-08-11 补充）

**评估对象**：候选池从全市场到各层的数量配置，是否给下游分配器足够的"选择空间"。

**实际数量链路（源码逐级核实）**：

| 环节 | 数量配置 | 锚点 |
|---|---|---|
| 全市场扫描 → 硬过滤 | 数千只 → `filter_etfs`（≥1亿规模、≥1000万成交额、排除纯债/货币） | etf_scanner L504-560 |
| 分层粗筛 | **每层 top_n=25**（core / satellite / defense） | `layer_ranking` L855-857（P2 修复：15 提升到 25） |
| 层内去重 + 强制保底 | 同指数家族合并（B2）、510300/159338 与 518880/511090 注入 | _refresh_impl L639-643 |
| 最终截断 | **core 8 / satellite 20 / defense 10 / opp 8 / research 10** | `MAX_PER_LAYER` L142-148 |
| 分配器消费 | balanced/aggressive：core 5（含 2 强制→选 3）、satellite 8、defense 1；defensive：core 4（含 2 强制→选 2）、satellite 6、defense 2（**review 修正：原文档「core 5/satellite 8/defense 1-2」仅对 balanced/aggressive 成立**） | `layer_count`（budgets L24/40/56） |

**合理性判断：总体合理，漏斗设计正确。**

**✅ 合理之处**：
1. **漏斗逐级收窄**：几千 → 25 → 8/20/10 → 消费 3-8；每级都是"质量优先"筛选，且不在源头一步定死——"候选池给分配器足够选择空间"的语义正确。
2. **余量充足（关键）**：core 池 8 vs 选 3、satellite 20 vs 8、defense 10 vs 1-2 ≈ **2.5:1**。保证"选择"是真正的选择，而非"只有这么多、不得不选"；core 若仅 3 个候选则因子排序失去意义。
3. **强制保底 + 截断保护**：`_truncate_with_mandatory_protection`（R5-0-1）先剔除后补回，防止 510300/159338 在 25→8 中被挤出（P1-1 A500 缺失的历史根因已修复）。

**⚠️ 待改进点（与 §4.3 缺陷三同源）**：
1. **数量魔法数无校准依据**：`top_n=25`、`MAX_PER_LAYER=8/20/10/8/10` 全为手调值，无"为什么 core=8 而非 6/12"的实证闭环——**并入 §5.3 阶段二校准框架**（同用回放数据，网格搜索层容量使 forward rank-IC 最优即可定参）。
2. **边界脆弱：core=8 紧贴 layer_count.core=5 的下限**：若未来 layer_count.core 上调（如 6），扣 2 强制后仅 4 个可选，选择余量进一步收窄。建议设显式约束 `MAX_PER_LAYER.core ≥ layer_count.core + 3`，防后续调参静默踩坑。

**结论**：数量设计整体科学——「粗筛淘汰不可交易 → 精排留给因子区分 → 余量保选择空间」层次正确；真正的短板是**数量本身也是无校准的手调参数**，与 §4.3 权重无实证闭环为同一根问题，随阶段二一并校准，不单独开新缺陷。

### 4.6 【P0 缺陷四】amount 单位错配：真实活跃 ETF 被整体误杀（2026-08-11 补充）

**现象**：用户提问「半导体设备/游戏等强势板块为何不在组合设计方案里」→ 定位为候选池入口数据 bug，非设计使然。

**根因链**：
- 数据源：`_tencent_gtimg_chunk`（etf_scanner L214）从腾讯 gtimg 取 `parts[37]` 作为 `amount`——**单位为万元**。实证：510300 `amount=447469`（=44.7 亿元成交额，真实）、588000 `amount=774023`（=77.4 亿元）、159516 半导体设备国泰 `amount=488980`（=48.9 亿元）。
- 过滤阈值：`MIN_AVG_AMOUNT = 10_000_000`（etf_scanner L54，注释「元 (1000万)」）——**单位为元**。
- 误杀逻辑：`filter_etfs`（L554）`if amount > 0 and amount < MIN_AVG_AMOUNT: continue` → 万元值 447469 直接与 1000万 比较 → **447469 < 10_000_000 → 判「成交额不足」→ 剔除**。

**实证（缓存快照 2026-08-07，同一份数据两种口径重跑）**：

| | 现状（bug） | 单位修正（×10000） |
|---|---|---|
| `filter_etfs` 通过 | 392 只 | 1121 只 |
| 159516 半导体设备国泰 | ❌ 误杀 | ✅ 通过，卫星层 **rank 5** |
| 159558 半导体设备易方达 | ❌ 误杀 | ✅ 通过，卫星层 rank 27 |
| 159869 游戏ETF华夏 | ❌ 误杀 | ✅ 通过，卫星层 rank 66 |
| 512480 半导体国联安 | ❌ 误杀 | ✅ 通过，卫星层 rank 28 |
| 卫星层 TOP25 | 全为 589xxx（amount=0/fund_scale=0 僵尸标的） | 159516 半导体设备、159995 芯片、512880 证券、515880 通信等真实活跃标的 |

**连带污染**：现状卫星层 TOP25 全为 `589990 科创综指 / 589980 科创100 / 589960 科创新能源 / 589720 科创创新药 / 589560 科创AI` 等 **amount=0 且 fund_scale=0** 的标的——它们通过过滤是 L554-560 的**降级分支**（`amount=0 时跳过金额过滤`）放行的。真实数据齐全的标的反而被误杀，**「数据缺失的僵尸标的被放行、真实活跃标的被剔除」排序逻辑完全颠倒**。

**影响面**：
1. 核心层被掩盖：510300/159338 等靠 `WIDE_BASIS_STATIC` 静态兜底（L65-88）才保住 → 看似正常，掩盖 bug；
2. 卫星层被污染：候选池只含「腾讯无成交数据」的标的，流动性/规模优势失真；
3. 强势主题系统性缺席：半导体设备（407 亿规模）、游戏（90 亿）全部出局——用户观察到的问题；
4. 波及 `layer_ranking` 金额可用性判定（L633 `max_amount > 100000`）：真实金额被砍到万元量级后仍 >100000，走了「有成交数据」分支但比较值失真；
5. **波及 composite 层（§4.2 第三处复现）**：amount（万元）与 `WIDE_BASIS_STATIC` 静态 amount（元，2e9）同池混入 `_compute_composite` 的 `amount*1e-9`——静态标的 liquidity 分 ≈2.0×w，腾讯源真实标的 ≈0，排序失真。

**修复方向（见 §5.4）**：源头统一单位（推荐，×10000）或 filter 内归一化。

#### 4.6.1 防漏复盘：为何三层面都没发现（2026-08-11）

| 层面 | 为什么漏了 | 本质 |
|---|---|---|
| **设计** | ① 数据源字段**单位契约缺失**——`amount` 无「万元/元」元数据声明，多源（Sina/Tencent/EastMoney/akshare）形态差异只做了字段名兼容（`_get_col` 按名字兜底），**未做量纲归一化层**；② `MIN_AVG_AMOUNT` 注释写「元」但取值与真实数据源单位不符，**常量语义与数据源脱节**；③ 多源降级链（工程韧性亮点）恰好让「腾讯源返回万元、新浪源返回 0」两种形态并存，**降级分支（amount=0 跳过过滤）成了错误数据的避风港**。 | 数据契约只到「列名」层级，没到「量纲」层级 |
| **代码走读** | ① `parts[37]` 裸索引无单位注释，走读无法从代码面看出万元口径；② 误杀是**静默**的——日志只报 `filter_etfs: 1624 -> 392`（L574），数量级看起来像「正常过滤掉小 ETF」，无异常信号；③ 核心层靠静态兜底「看起来正常」，**候选池分层结果只存内存、不落盘**，事后无法核对「被过滤的是什么」；④ 正向路径（真实标的全量通过）从未被验证过，走读只验证了逻辑分支存在。 | 静默降级 + 无数据快照可审计 |
| **测试防护** | ① 单测全部 mock 外部源，**mock 数据单位是测试作者自造的「元」**——测试数据永远正确、生产数据单位错误，**mock 隔离了真实数据形态**，天然测不出单位 bug；② 无「真实缓存快照回归测试」——若用 `etf_list_cache.json` 做 fixture 断言「510300/159516 等基准标的必须通过 filter」，bug 当天就能抓住；③ `verify_e2e.py` 只验「200/非空/数量」不验**内容正确性**——core 有 510300 就 PASS，不检查卫星层是否被僵尸标的霸榜；④ 无「候选池数据健康度」断言（如「卫星层 amount>0 占比 ≥ X%」）。 | mock 屏蔽真实数据形态 + 断言只到「存在性」不到「内容性」 |

**共性根因一句话**：三层面都止步于「结构正确」（字段名、分支、数量），而**从未验证「数据内容语义正确」（真实成交额量级、真实标的入选）**——正对应反假完成清单中「内容断言」维度在候选池环节的缺失。修复 bug 之外，需把「真实数据快照回归 + 内容断言」补进防护体系（见 §7 验收口径补充）。

#### 4.6.2 兜底逻辑评估：WIDE_BASIS_STATIC 静态兜底合理吗？（2026-08-11）

**结论：意图合理，实现有三个实质缺陷，且在本 bug 中恰好成为「掩盖者」。**

**意图为什么合理**：候选池 Top25 按涨幅/规模排序，主流宽基当日涨幅小会被挤出；`CORE_REQUIRED` 注入（`layer_ranking` 的 required，仅查候选池 items）静默失效 → 核心层缺宽基锚。F0-5 步骤 B 保证 510300/159338 永远在场，符合「核心层 = 市场 Beta 底仓」的组合设计——**这层判断没问题**。

**缺陷一：静态金额是拍脑袋的过期值**（对比 2026-08-07 缓存真实值）：

| ETF | 静态 fund_scale | 静态 amount | 真实 scale | 真实 amount（万元→亿元） |
|---|---|---|---|---|
| 510300 沪深300 | 900亿 | 20亿 | **1193.85亿** | 447469万 = **44.7亿** |
| 510500 中证500 | 800亿 | 15亿 | **445.08亿** | 292672万 = 29.3亿 |
| 510050 上证50 | 700亿 | 10亿 | **211.39亿** | 156699万 = 15.7亿 |
| 588000 科创50 | 600亿 | 8亿 | **906.21亿** | 774023万 = **77.4亿** |
| 159915 创业板 | 500亿 | 7亿 | **673.04亿** | 761315万 = **76.1亿** |
| 159338 中证A500 | 550亿 | 9亿 | **287.14亿** | 369112万 = **36.9亿** |
| 512890 红利低波 | 200亿 | 3亿 | **321.35亿** | 90346万 = 9.0亿 |
| 515080 中证红利 | 150亿 | 2亿 | **116.99亿** | 31522万 = 3.2亿 |
| 518880 黄金ETF | 400亿 | 12亿 | **0**（腾讯无数据） | 0 |
| 511090 30年国债 | 300亿 | 5亿 | **312.81亿** | 470269万 = **47.0亿** |

静态值注入候选池后参与因子计算（规模因子），**规模排序失真**（588000 静态 8亿 vs 真实 77.4亿，差近 10 倍）——注释说「静态兜底」，实际金额规模全凭当时手写。

**缺陷二：静态 amount 单位是「元」，腾讯源是「万元」——单位 bug 的第二处土壤**：静态 `amount: 2_000_000_000`（=20亿元，元口径），腾讯源 `447469`（万元口径）。同一候选池两种口径并存，`layer_ranking` 的 `max_amount > 100000` 金额可用性判定（§4.6 影响面第 4 点）数值语义完全不同。**这不是孤例，而是同一根单位契约缺失问题在兜底层的复现。**

**缺陷三：兜底掩盖了数据管道错误**：本次单位 bug 中，510300/588000/159338 全被 filter 误杀（万元 vs 元），**静态兜底把它们救回来了 → 核心层「看起来正常」** → 无法从核心层发现任何异常。兜底本意是「数据源缺这条标的」，实际成了「数据源单位错了但表象正常」的遮羞布。卫星层没有静态兜底，所以 159516/159869 被误杀后毫无补救 → 用户才看到「半导体设备缺席」——**有兜底的层（core）一切正常，无兜底的层（satellite）僵尸霸榜，表象不对称正是 bug 难发现的原因之一**。

**单位 bug 修复后的重新定位**：单位修正后，510300/588000/159338 等真实规模前列标的天然进 Top25，**静态兜底触发率会大降**——应从「常态机制」降级为「纯数据缺失保护」。建议方向（不实施，仅立标）：
1. **清单瘦身**：静态条目只保留 `symbol/name/layer`，删掉硬编码 `fund_scale/amount`——金额规模完全依赖实时数据，避免过期失真；
2. **兜底触发告警**：M2 现有 WARNING 只查 required 未命中；应加「兜底触发即告警」，若某标的连续 N 轮靠兜底进场（数据管道有故障），暴露而非静默救场；
3. **待单位 bug 修复后重新评估**：若修复后各标的自然入选，WIDE_BASIS_STATIC 实际只剩 518880（黄金，腾讯无成交数据）等少数真实缺口——清单可大幅缩水。

#### 4.6.3 降级链盲区：多源防"源挂"，防不了"源没挂但数据错"（2026-08-11）

**背景问题**：成交数据是否完全依赖腾讯？其他源（EM/akshare）能否降级？

**答案**：降级链存在但**永远不会在字段级触发**——熔断路由只防「源挂」，防不了「源没挂但数据单位错了」。

**数据源链（`fetch_all_etfs_base` L342-454，经 SourceRegistry 熔断路由）**：

| Provider | 数据 | amount 来源 | 单位 |
|---|---|---|---|
| **Provider 1** Sina + Tencent（默认主源） | Sina 给列表（代码/名称/价格），腾讯 gtimg 补成交额/规模/PE | `_tencent_gtimg_chunk` L214 `parts[37]` | **万元** ← bug 源头 |
| **Provider 2** EastMoney push2 直连 | `_fetch_em_etf_list` L328 `f72=成交额` | 东财字段 | **元** |
| **Provider 3** akshare spot（最终兜底） | `fund_etf_spot_em` | 东财同源 | **元** |

**关键事实**：
1. **其他源能获取成交额，且单位还是对的（元）**——EM 直连 `f72`、akshare `fund_etf_spot_em` 都是元口径，与 `MIN_AVG_AMOUNT = 10_000_000`（元）天然匹配。**若当前数据来自 EM/akshare，本 bug 根本不会发生**；
2. **但降级链永远轮不到它们**：熔断路由触发条件是 **Provider 整体失败**（`len < 50`、抛异常、连续 3 次失败冷却），**无字段级质量判定**。Provider 1 只要 Sina 列表 ≥50 且 gtimg 返回非空映射即整体"成功"——**腾讯返回的万元值被当作有效数据直接通过，EM/akshare 永不参与**；
3. **缓存快照证实当前数据来自腾讯**：`511360 amount=2255325`（=225.5 亿，万元口径）、`588000 amount=774023`（=77.4 亿，万元口径）；1624 只中 393 只 amount=0（含 518880 黄金 ETF，腾讯对它有价无成交额字段）——正是这些 0 值走 L554 降级分支放行，成为卫星层僵尸标的入口。

**暴露的架构缺口（比单位 bug 更深的根）**：

| 层面 | 现状 | 缺口 |
|---|---|---|
| 降级触发 | Provider 整体失败才切源 | **无字段级质量判定**——单位错、全 0、量级离谱都不触发降级 |
| 跨源一致性 | 无交叉校验 | 腾讯 774023（万元）vs EM 7.74e9（元），同标的差 1e4 倍——**无任何检查发现"同一只 ETF 两个源成交额差一万倍"** |
| 熔断语义 | 连续失败才冷却 | 数据"返回了但单位错"不算失败，永远不会冷却腾讯 |

**一句话**：多源降级链防的是「源挂了」，防不了「源没挂但数据错了」。本次单位 bug 恰好落在降级链盲区——腾讯源"稳定返回错误口径"，以熔断器视角它是个健康源。

**修复建议（并入 §5.4 一并考虑）**：
1. **必做**：单位修复后，腾讯与 EM 的 amount 应量级一致（元）；加**跨源量级一致性校验**——同标的腾讯 vs EM 成交额差 >100 倍即告警（防单位错配复发）；
2. **可选**：降级链增加**字段级健康度**（如"amount>0 占比 <30% 视为可疑，自动切 EM"）——把「数据错」纳入熔断语义；
3. **连带发现**：518880 黄金 ETF 腾讯无成交额字段（amount=0）是真实缺口，靠 WIDE_BASIS_STATIC 静态兜底（§4.6.2 缺陷三场景）——单位修复后它依然是静态清单保留的少数真实理由之一。

---

## 5. 修复方案（只设计，不实施）

### 5.1 方案一：raw 因子方向化 + 显式聚合映射（修缺陷一）

**核心思路**：聚合前统一到「语义分」——越高越好，方向显式声明。**基于 review 实证（§4.1）**：raw 污染源只有 `rsi_14` 一个（生产链路），KDJ 为 zscore 走「取负翻转」路径，不再用 neutral_value 变换。

**设计**：
1. **YAML 增加可选字段**（`factor_definitions.yaml`）：
   ```yaml
   - code: "technical.rsi.rsi_14"
     standardization: "raw"
     direction: "-1"          # 新增：-1 = 反向信号（超买为负），默认 +1
     neutral_value: 50        # 新增：区间中性点（仅 raw 区间因子需要）
   ```
   标注 `direction: "-1"` + `neutral_value: 50` 的：`rsi_14`（唯一 raw 区间因子）；`rsi_24` 同规则（虽不在 `_CORE_FACTORS`，加入后自动生效）；`etf.return_*` 等动量类保持 `+1`。
2. **`FactorDefinition` 增加 `direction` / `neutral_value` 字段**，`load_definitions` L1021-1037 解析（默认 direction=+1、neutral_value=None）。
3. **聚合前变换（两种模式，review 修订——原文档只设计了 raw 一种）**：
   - **raw 区间因子**（`standardization == "raw"` 且 `neutral_value` 非空）：
     ```
     signal = (neutral - val) / neutral          # RSI=70 → -0.4；RSI=30 → +0.4；范围 [-1, 1]
     ```
     与 `signal.overall` 的"超卖加分/超买卖出"语义完全一致（L318-319 `RSI>70 → score -= 0.4`）。
   - **zscore 均值回归因子**（KDJ k/d/j，zscore 量纲 ±19，中性点=0）：超买=正值加分需翻转 → `signal = -val`（KDJ 高位→负分）。无需 neutral_value。
   - zscore 动量类因子（sma/macd/vol 等）方向保持 +1 不变；`_raw` 键保留链路不变（报告零影响）。
   **作用域（关键）**：方向化变换**只作用于聚合输入的副本**，不写回 `factor_scores` 原始裸键——`_normalize_matrix`（L1499，raw 跳过 L1539-1541）保留的 0-100 真实值（rationale / factor_breakdown 展示用）不得被 transform 污染。实施时若原地改 dict 会破坏真实值保留链路，必须 `copy` 后再变换。
4. **聚合从纯前缀匹配改为「显式聚合映射 + 方向」**（`aggregate_factor_scores`，新增 `CATEGORY_AGG` 表）：
   ```python
   CATEGORY_AGG = {
       "technical": [("technical.ma.",      +1, None),
                     ("technical.macd.",    +1, None),
                     ("technical.rsi.",     -1, "symmetric50"),   # raw 区间: (50-val)/50
                     ("technical.kdj.",     -1, "negate"),        # zscore: -val
                     ("technical.signal.",  +1, None),
                     ("technical.bollinger.", +1, None),
                     ("technical.volume.",  +1, None),
                     ("technical.atr.",     +1, None)],
       # momentum/valuation/sentiment 前缀保持现有 CATEGORY_PREFIXES（L1066-1071）
   }
   ```
   说明：当前 `_CORE_FACTORS` 的 technical 类共 15 因子（§4.1 清单），映射表覆盖全部前缀；未来加因子改 yaml 声明（direction）即可，不必改聚合代码。**单一来源约束**：方向（±1）与变换模式最终以 `FactorDefinition.direction`（yaml）为准，CATEGORY_AGG 内的方向列仅为默认/文档值——实施时聚合阶段按 key 查 FactorDefinition 决定变换，避免两处配置漂移。

**影响面**：
- `factor_scores` → `_compute_composite` → 候选池排序（有意为之，池子会变）；
- `verify_e2e.py` 的 510300/518880 在场 & factor variance 断言大概率仍满足（强制保底机制钉住核心标的），但需评审；
- 单测：`test_factor_matrix_respects_raw`、`test_market_context`、`test_design_*` 中 technical 值断言需更新；
- 前端展示链路零影响。

**验证**：新增负向断言单测（细化）——"构造 RSI=75 与 RSI=50 两只标的（其余 technical 因子设为 0），断言修复后 `technical(RSI=75) < technical(RSI=50)`"（修复前 RSI=75 因 raw 0-100 贡献 ≈75/15=5 分而更高；该断言修复前必失败，防方向化缺失回归）。

### 5.2 方案二：composite 分量统一量纲（修缺陷二）

**核心思路**：所有分量先统一到可比量纲（[0,1] 或 [-1,1]），权重才有语义。**基于 review 实证（§4.2）**：当前 liquidity/scale 分量因 `*1e-9` 与数据源单位（万元/亿）错配被压成 ≈0——方案二的目标不是「限制规模主导」（原文档动机，已被实证推翻），而是**恢复第二排序维度（流动性/规模）的区分度**。

**设计**（`_refresh_impl` 层内先收集截面向量，再算分）：

```python
score = (
    w["factor"]    * tanh(factor_sum / 6.0)                              # [-1,1]，防极端 z 支配
  + w["liquidity"] * _pct_rank(item["amount"], layer_amounts)            # [0,1]
  + w["scale"]     * _pct_rank(item["fund_scale"], layer_scales)         # [0,1]
  + (w.get("opp", 0) * opp_score if layer != "core" else 0)              # [0,1]
)
```

- `tanh(factor_sum/6)`：6≈3σ，极端 z-score 不支配（factor_sum 常态 ±10 → tanh 域 [-0.93, 0.93]）；
- `_pct_rank`：层内截面百分位，彻底消除绝对量级——**对单位不敏感**（同列同单位即可），但金额过滤（§4.6 方案四）必须先修，否则池内标的构成错误，百分位排序无意义；
- 四分量量纲统一后，`_LAYER_WEIGHTS` 的 0.55/0.40/0.25 才恢复"偏好比例"的真实含义。

**数据流（实施必需）**：`_refresh_impl`（L476）在层内**先收集截面向量** `layer_amounts` / `layer_scales`（按层汇总 amount/scale），再逐 item 调用 `_compute_composite`（L940）并传入本层向量供 `_pct_rank` 使用（现状为逐 item 独立计算，无跨 item 上下文）。**接口变更（review 细化）**：`_compute_composite(self, item, layer, regime, layer_amounts=None, layer_scales=None)`——向后兼容：`layer_amounts=None` 时回退旧 `*1e-9` 路径，保证 research 层等不改写处行为不变。量纲统一**仅覆盖 core/satellite/defense 三层**；research 层（L974 `amount*1e-9` 兜底，amount 修复后自然恢复区分度）与 opp 分量（L952 默认 0.5）维持现状不改写。

**依赖**：**先落方案四（amount 单位修复）再评估本方案效果**——amount 修复后 liquidity 项先恢复（510300 `4.47e9×1e-9=4.47` 分），方案二再统一 scale 量纲，两方案配合才完整；否则层内 `_pct_rank` 对「静态 amount（元）+ 腾讯 amount（万元）」混合口径的排序仍失真（§4.2 后果 2）。

**影响面**：
- `_compute_composite` & 依赖它的 `_balance_by_industry` / `_truncate_with_mandatory_protection`；
- 池子会更接纳"高因子小盘 ETF"（修复前 scale/liquidity 死值无区分；修复后大标的在 scale 维占优，但因子分权重 0.55 仍主排序）；
- 所有 composite 相关测试阈值按新量纲重定。

**验证（负向断言重设计，review 修正）**：原断言「规模 2000 亿 + factor_sum=+9 应 > 规模 30 亿 + factor_sum=0（当前相反）」在真实数据口径下**不成立**（修复前 2000 亿标的 scale 分也≈0，factor_sum=+9 者本来就更高——原断言在修复前就已通过，抓不住回归）。新断言两条：
- **区分度恢复断言（防「第二维度仍死」回归）**：同层构造 A（fund_scale=2e11 元 = 2000 亿、factor_sum=0）与 B（fund_scale=3e9 元 = 30 亿、factor_sum=0），balanced 市态断言 `composite(A) > composite(B)`（修复前两者 scale 分都≈0 无法区分 → 修复前必失败）。
- **因子主导性断言（防量纲统一后反被规模压死）**：同层构造 A（2000 亿、factor_sum=+9）与 B（2000 亿、factor_sum=0），断言 `composite(A) > composite(B)` 且 factor 项贡献占比 > 50%。

### 5.3 方案三：IC 驱动聚合 + 权重校准闭环（修缺陷三，最大价值）

#### 阶段一：IC 加权聚合（短期，低风险，建议先做）

**前置能力缺口（review 确认）**：当前 `ic_tracker` 只保留**最近一批**截面 IC（`_last_ic_batch`，factor_registry L1596-1603），历史 IC 在 DB 表 `factor_ic_records`（`factor_code / ic_value / ic_ir / sample_count / computed_at`，main.py L416-433 每 120s 落库）累积——**但没有任何「取某因子近 N 日 IC 序列」的查询方法**（`compute_ic_series` L95 存在但无调用方）。阶段一实施需先新增该能力。

```python
# 1. 新增能力：registry.get_ic_series(factor_code, days=20) -> list[float]
#    （按 computed_at 取近 N 批，DB 查询；IC 样本 < 5 批 = 冷启动 → 回退等权，保持现有行为）
# 2. IC 加权聚合（替代 aggregate_factor_scores 顶层键内的等权均值，L1098）：
#    direction 翻转：mean_ic_i < 0 且 |mean_ic_i| > IC_FLIP_THRESHOLD(=0.03)
#      → 因子值取负（x'_i = -x_i）后按 w_i = |mean_ic_i| 参与聚合
#    未翻转因子：w_i = max(mean_ic_i, 0) * exp(-λ * age_i)
#    top_key = Σ(w_i · x'_i) / Σ(w_i)        # Σw_i == 0（全部 IC≈0）→ 回退等权
# 3. 参数：λ = ln2/20 ≈ 0.035（IC 半衰期 20 日，可配置）；IC_FLIP_THRESHOLD = 0.03
```

- 纯增量系数，不动现有结构，风险最低；
- 冷启动（IC 样本 < 5 批）：回退等权，保持现有行为（§8 风险 2）；
- **作用域与顺序（review 细化）**：仅替换 `aggregate_factor_scores` 顶层键内的等权均值 → 与方案一（方向化+显式映射）**同一函数顺序落地**（§6 批间依赖：先方案一合并映射表，再在其上叠加 IC 权重）；**变换顺序不可反——先方向化（语义修正）、再 IC 加权（有效性修正）**；
- **IC 对象**：IC 以 `compute()` 的原始键因子（39 项）为对象计算（现有 `compute_ic` L69-93 Spearman 秩相关），加权作用域为顶层键内的原始键子集。

#### 阶段二：`_LAYER_WEIGHTS` 参数校准（中期，离线研究先行）

前提：项目已有 `get_history` / `_kline_cache` 历史通道可离线重放。

1. **数据构建**：每日候选池快照 + factor_matrix + 未来 5/20 日收益（rolling join）；
2. **因子评价**：Rank IC、ICIR、半衰期——回答"哪些因子真有效、有效期多长"；
3. **权重校准**：网格搜索 / scipy 优化 `_LAYER_WEIGHTS` 与顶层键内子权重，目标 = 层内 selection 的 forward rank-IC（带约束：保持层预算语义、强制保底与行业均衡机制不动）；
4. **层容量校准（§4.5 改进点）**：同时网格搜索 `top_n`（25）与 `MAX_PER_LAYER`（8/20/10），验证"多取候选是否提升最终选中标的的 forward rank-IC、还是只增加噪声"；对 core 设硬约束 `MAX_PER_LAYER.core ≥ layer_count.core + 3` 保选择余量；
5. **Walk-forward 验证**：时间外样本检验防过拟合；IC 低于阈值的因子权重归零或翻转。

产出：校准报告（每层每市态最优权重 + 层容量 + 因子有效性排序），**验证有效后才上线替换手调值**。

#### 阶段三（可选，长期）：风险校正

- composite 增波动率惩罚：`score -= λ · (层内截面归一化的 rolling vol)`；
- 评价目标从"forward 收益"升级为"收益/回撤"，避免选到高波动追涨标的。

### 5.4 方案四：amount 单位统一 + 单位契约声明 + 跨源一致性校验（修缺陷四，P0，独立小批次）

**问题（review 实证确认，2026-08-07 缓存）**：`_tencent_gtimg_chunk` L214 `parts[37]` 单位是**万元**（510300 amount=447469 万 = 44.7 亿），`filter_etfs` L554 用 `MIN_AVG_AMOUNT = 10_000_000`（**元**）比较 → 真实活跃 ETF（510300/159516/159869 等）被整体误杀，卫星层被 amount=0 僵尸标的（589xxx）霸榜。全链路只有腾讯源（万元口径）会触发；EM/akshare 源（元口径）与阈值天然匹配（§4.6.3）。

**单位契约实证表（review 补充——原文档「待实测确认」项已有答案）**：

| 字段 | 腾讯 gtimg 实际单位 | filter 阈值（匹配？） | composite `*1e-9` 效果 |
|---|---|---|---|
| `amount`（parts[37]） | **万元**（510300=447469） | `MIN_AVG_AMOUNT=10_000_000`（元）→ **错配，误杀** | 万元×1e-9≈0（死值，§4.2） |
| `fund_scale`（parts[45]） | **亿**（510300=1193.85） | `MIN_FUND_SCALE=1.0`（**亿**）→ **匹配** | 亿×1e-9≈0（死值，§4.2） |
| `turnover`（parts[38]） | 换手率（无单位问题） | 无过滤 | — |
| `WIDE_BASIS_STATIC.amount` | 硬编码**元**（2e9） | 不经过 filter | 元×1e-9=2.0（静态标的虚高，§4.2 后果 2） |

**方案 A（推荐）：源头统一——腾讯源 amount 换算为元**
```python
# _tencent_gtimg_chunk L214
amount = float(parts[37] or 0) * 10000   # gtimg 成交额单位=万元 → 统一为元（单位契约在此声明）
```
- 一处修复，`filter_etfs` / `layer_ranking`（L633 `max_amount > 100000`）/ composite `amount*1e-9` / `WIDE_BASIS_STATIC` 静态值全部对齐"元"口径；
- **fund_scale 不需换算**（亿 与 `MIN_FUND_SCALE=1.0` 匹配），但须在 `_tencent_gtimg_chunk` L222 加单位契约注释：`# gtimg 总市值单位=亿，与 MIN_FUND_SCALE(亿) 匹配；composite 的 scale*1e-9 对此单位≈0（方案二根治）`；
- 方案 B（filter 内量级归一化）：维持「不推荐为主方案，可作防御性兜底」的定位（原表述保留）。

**连锁反应（review 补充——方案四单独落地后的行为变化，实施前必须知悉）**：
1. `filter_etfs` 通过数 392 → 1121（§4.6 实证），候选池构成完全改变——**所有下游阈值断言（verify_e2e 等）需按新池复跑**；
2. composite 的 liquidity 项**恢复区分度**：510300 amount=4.47e9 → `×1e-9=4.47` → ×0.20 ≈ 0.9 分（修复前 ≈0）——liquidity 维度复活；
3. scale 项仍死（亿×1e-9≈0）——**量纲问题只修一半**，方案二（§5.2 `_pct_rank`）必须跟进，否则「规模维度失效」残留；
4. research 层（L974 `amount*1e-9`）从死值恢复为真实排序（4.47 分量级）——正向副作用；
5. `layer_ranking` 的 `max_amount > 100000` 判定语义恢复正常（4.47e9 元 vs 阈值 10 万，差距两个数量级，判定稳定）。

**必做：跨源量级一致性校验（§4.6.3 建议 1，review 细化实现位置）**
- **实现位置**：`fetch_all_etfs_base`（L342-454）Provider 1（Sina+Tencent）成功后、写缓存前——对 gtimg 返回的 amount 做**绝对量级检查**：`0 < amount < 1e6`（万元口径残留特征值，如 447469）→ `logger.warning` 告警「amount 疑似万元口径」；
- **同源双口径检查（更稳，建议主）**：腾讯 amount（×10000 后）与 EM 源（元）同标的交叉比对，差 >100 倍即告警（防单位错配复发）；
- 可选增强（不纳入本批）：连续 N 轮告警自动切 EM（§4.6.3 建议 2，字段级健康度纳入熔断语义）。

**验收（DoD，对照 §4.6 实证表）**：
1. `filter_etfs` 通过数 ≥ 1000（修复前 392）；
2. 159516/159869/512480 等真实活跃标的出现在卫星层候选（修复前被误杀）；
3. 卫星层 TOP25 不再全为 589xxx amount=0 僵尸标的；
4. 以 `backend/data/etf_list_cache.json`（2026-08-07 快照，1624 只，已实证存在）为固定输入做快照回归测试（`pytest`，断言上述 1-3）；
5. 跨源校验：构造腾讯万元口径 amount（447469）与 EM 元口径（4.47e9）同标的 fixture → 断言触发告警日志（负向断言防回归）；
6. **fund_scale 单位契约断言（review 新增）**：快照回归中 510300 的 `fund_scale` 必须为 1193.85（亿口径）→ 若未来数据源返回元（1.19e11）则契约测试失败（防 parts[45] 单位漂移）。

---

## 6. 落地顺序与批次

| 批次 | 内容 | 风险 | 理由 | Commit 建议 |
|---|---|---|---|---|
| P0 | 9-F1（core 市态绝对防线，§10.1） | 低 | 独立可先行（用现有 composite 口径），成本最低价值最高（§11 合并顺序第 1 位） | 独立 commit + 负向断言 + verify_e2e 全跑 |
| P0 | 方案四（amount 单位统一 + 单位契约 + 跨源校验，§5.4） | 低 | 修候选池入口数据 bug，影响面最大且独立；先落单位基座，后续方案一/二/三的评估才有真实数据 | 独立 commit + 快照回归测试 + verify_e2e 全跑 |
| P0 | 方案一（raw 方向化 + 显式聚合映射） | 中 | 修方向性 bug，语义矛盾最伤；先落映射基座 | 独立 commit + verify_e2e 全跑 |
| P0 | 方案三·阶段一（IC 加权聚合） | 低 | 纯增量，在映射基座之上叠加 IC 权重 | 独立 commit，含负向断言 |
| P1 | 方案二（量纲统一） | 中 | 让权重比例恢复真实含义，配合 P0 才有效果 | 独立 commit + 对照单测 |
| P1 | 方案三·阶段二（权重校准 + §4.5 层容量） | 中 | 离线研究先行，数据驱动替代手调 | 先产出报告再动参数 |
| P2 | 阶段三 + 双重标准化收敛（§4.4） | 高 | 重构性质，独立排期 | 单独立项 |

> **review 注**：本表已并入 9-F1；§11「合并迭代顺序」表为**最终执行顺序**（含 9-F2/9-F3/9-F4），两表一致，以 §11 为准。

**批间依赖**：P0（IC 加权）与 P0（raw 方向化）**虽无数据依赖，但两者都改写 `aggregate_factor_scores`**（方案一改显式聚合映射、方案三改顶层键等权→IC 加权）——**同函数并行合并必冲突**，批次表改「同 PR 顺序落地」：先合并方案一（映射表），再在映射表之上叠加方案三（IC 加权系数），**变换顺序不可反（先方向化、再 IC 加权，§5.3 阶段一）**。**方案二依赖方案四与方案一双前置**（review 修正原「仅依赖方案一」）：amount 单位修复（方案四）是层内 `_pct_rank` 正确性的数据前提，方向化（方案一）校正 factor_sum 后量纲统一才是真分数。**方案四与 9-F1 独立于其余方案**（改 `etf_scanner` 数据源层 / 风控管线，不碰 `aggregate_factor_scores`），可先行落地——方案四是其余方案评估的"真实数据前提"（§4.6.3），9-F1 成本最低价值最高（§9.2 结论）。

---

## 7. 验收口径

功能交付（每批）：**DoD = 测试绿 + 现实证真双证**：

| 检查 | 方法 | 假完成信号 |
|---|---|---|
| 真实链路 | `rg` 确认改动函数有真实调用点 | 0 调用 = 脚手架 |
| 非兜底 | 设计响应抓真实因子值，非全 0/默认 | 全默认 = 假实现 |
| 内容断言 | technical 键值分布变化符合预期（raw 方向化后超买不再加分） | 只验 200/非空 = 空壳 |
| 引用同步 | 改动后 `rg` 旧名无残留 | 旧名残留 = 改一半 |
| 回归门禁 | `verify_e2e.py` 全 PASS + `pytest` 全量 + `npm run build` | — |

新增**负向断言**（方案一/二/四各一条，2026-08-11 review 修订断言 2）：
1. 方案一：构造 RSI=75 与 RSI=50 两只标的（其余 technical 因子=0），断言 `technical(RSI=75) < technical(RSI=50)`（修复前 RSI=75 因 raw 0-100 贡献 ≈5 分而更高）；
2. 方案二：同层构造 A（fund_scale=2000 亿、factor_sum=0）与 B（fund_scale=30 亿、factor_sum=0），balanced 市态断言 `composite(A) > composite(B)`（修复前两者 scale 分都≈0 无法区分；**原断言「30 亿+factor_sum=+9 > 2000 亿+factor_sum=0」在真实单位下修复前已成立，抓不住回归，已废弃**，见 §5.2 验证）；
3. 方案四：① 构造腾讯万元口径 amount（447469）输入 `filter_etfs` → 必须通过（修复前被误杀，§5.4 验收 1-3）；② 构造腾讯/EM 同标的 amount 差 1e4 倍 fixture → 跨源校验必须触发告警（§4.6.3）；③ **fund_scale 单位契约断言**：510300 `fund_scale=1193.85`（亿）固定值断言（§5.4 验收 6）。

**候选池内容断言（§4.6.1 测试防护缺口 ③④ 的落实，方案四验收必做）**：
- 以 `etf_list_cache.json` 为固定输入做**真实快照回归测试**：断言 510300/159516/159869/512480 必须通过 `filter_etfs` 且进入对应层（修复前 159516/159869/512480 被误杀、510300 靠静态兜底）；
- **数据健康度断言**：卫星层候选 amount>0 占比 ≥ 90%（修复前大量 589xxx amount=0 僵尸标的霸榜）；核心层 amount 量级 ≥ 1e8（元口径，防万元残留）。

**池子多样性基线对比**（可选，量化方案一/二效果）：选中标的数、行业熵、小规模 ETF 入选率，修复前后对比。

---

## 8. 风险与边界

1. **池子构成变化**：方案一/二会实质改变候选池排序 → `verify_e2e.py` 的 510300/518880 在场 & factor variance 断言可能波动；评审断言口径而非强行满足阈值（强制保底机制确保核心标的在池，预期仍 PASS）。
2. **冷启动**：IC 加权在 IC 样本不足时须回退等权（阶段一设计内），避免冷启动抖动。
3. **方向哲学一致性**：raw 因子方向（均值回归 vs 动量）必须与 `signal.overall` / `rationale.py` 的判定措辞统一，防止方案落地后报告文案与分数的语义再次分叉。
4. **双重标准化（§4.4）**：属重构，单独立项；在收敛前，改动方案一/二时注意两个口径都会被消费（`get_factor_matrix` 消费方 = `allocate`；pool `factor_scores` 消费方 = rationale/factor_breakdown）。
5. **不改动范围（§5 方案）**：§5 方案一/二/三均不触碰 `allocate()` 分配器、`budgets.py`、`risk_controls.py` 与前端展示链路。**§9/§10 追加方案例外**：9-F1~9-F4 按 §11 批次明确触碰分配器/风控模块（`_select_and_weight`、C2 词表、`RiskSettings`、参数源），触碰范围以 §10 各小节为准，不改动前端展示链路。

---

## 9. 分配器与风控逻辑评估（下游消费链，2026-08-10 追加）

> **触发场景**：实际设计结果中进攻方案核心层重仓科创50/创业板指，引发「熊市是否会死拿高 beta 宽基」的质疑。本章完整评估 `allocate()` → `dynamic_layer_budget()` → `_select_and_weight()` → `apply_risk_controls()` 的消费链。
> **性质**：本章评估与 §4 同样为**方案文档，未实施**；新发现的缺陷编号延续为 **9.x**（与 §4.x 同域），修复方案延续 §5 的表现形式另列于 §10。

### 9.1 评估对象

| 模块 | 函数 | 职责 |
|---|---|---|
| `engine/budgets.py` | `STRATEGY_META` / `dynamic_layer_budget` | 三方案层预算 + 市态动态调整 |
| `engine/allocation_engine.py` | `allocate`（L608）/ `_select_and_weight`（L272）/ `_filter_satellite_by_profile`（L562）/ 幂律配权 `exp((s-max)*0.08)`（L259，函数定义 L254）/ O16 大盘宽基互斥（L748）/ 强制标的后处理（L973） | 层内优选 + 权重分配 + 跨方案差异化 |
| `engine/risk_controls.py` | `apply_risk_controls`（L213）/ `filter_extreme_drawdown`（L48）/ `check_defense_effectiveness`（L90）/ F6 成长宽基集中度（L281） | 质量检查 + 硬约束 + 集中度 |
| 判定函数 | `_is_large_cap_wide_basis`（L188）/ `_is_wide_basis`（L137）/ `_is_growth_wide_basis`（L157）/ `_is_tech_theme`（L99） | 大盘宽基 / 宽基 / 成长宽基 / 科创主题识别 |

**关键事实（已核实源码）**：
- **科创50/创业板指是成长宽基，不是大盘宽基**：`_LARGE_CAP_WIDE_BASIS_KEYWORDS`（L176）含沪深300/中证A500/上证50 等，**不含**科创50/创业板 → O16（L748）的大盘宽基互斥**管不到它们**；而 `_GROWTH_WIDE_BASIS_KEYWORDS`（L151）明确列出科创50/创业板/双创 → F6（risk_controls L281）对它们**单独设 40% 上限**。
- **定层**：科创50/创业板是宽基指数 → `_assign_layer` 归 **core 层**（market_data_hub L463，`industry == "宽基指数"` → LAYER_CORE）。

### 9.2 【用户发现】熊市行为疑问：熊市会不会死拿科创50/创业板指？

**用户观察**：当前（牛市/强市环境）进攻方案核心层重仓科创50和创业板指。**疑问**：这套逻辑在熊市会不会"大力加仓"（或至少不撤）高 beta 成长宽基？

**回答：不会"加仓"，但存在「熊市钝化」风险——核心层选标的只有相对排序，没有市态绝对防线。**

#### 机制拆解（熊市进攻方案 core 层全链路）

1. **熊市预算响应**（`dynamic_layer_budget("aggressive", "bear")`）：
   - base `{core:0.50, satellite:0.20, defense:0.15}` → 经 defensive_rotate/bear 分支、bear 现金保护后：
     - core ≈ **0.477**（几乎不动，0.50→0.477）
     - satellite ≈ **0.065**（大幅压缩，0.20→0.065）
     - defense ≈ **0.20**（抬升，0.15→0.20）
     - cash ≈ **0.258**（bear 现金保护 10% × 减核心/卫星）
   - **结论**：熊市弹性靠「砍卫星 + 抬防御 + 留现金」，**核心层预算几乎不变**。而科创50/创业板指在 core 层 → 核心层的巨大预算继续分配给它们。
2. **核心层内部选标的 = 纯因子相对排序**（`_select_and_weight`）：
   - composite = Σ(因子分 × 风偏权重)；aggressive 的 momentum 权重 0.45 最大。
   - **core 层没有绝对分数门槛**——只取 top-N（N=3，扣除 2 只强制锚后的 core_max_count，L697）。卫星层有 P1-D 负分过滤（L424，factor ≤ -0.3 不给权），**core 层没有**。熊市因子分普遍转负时，科创50/创业板即使 composite 为负也可能仍排在前 3。
   - 幂律配权 `exp((s-max)*0.08)`（L259）是**相对**衰减：只要相对排名靠前，负分也照样按比例拿权重。
3. **C2 名称修正（L358-396）放大了进攻方案的追高风险**：`_RISKY_THEMES` 含"科创/半导体/AI"等；aggressive 且 valuation 无有效区分度时，命中风险主题 **+1.5，命中安全主题 -0.3** → 在估值数据缺失的行情里，科创50/创业板**被名称加分**，恰与熊市应降风险的方向相反。
4. **F6 兜底存在但上限偏宽**（risk_controls L281-299）：科创50/创业板/etc. 合计 ≤ core_budget×40% = 0.477×0.4 ≈ **19%**。即熊市核心层仍可容纳约 19% 的成长宽基，且**未约束单只**。作为对比，防御预算也只有 20%——成长集中度上限与防御层预算同量级。
5. **真正会触发剔除的只有下游风控**：`filter_extreme_drawdown`（月跌 < -40%，L48）/ `check_defense_effectiveness`（防御层 3 月跌 < -10% 减半，L90）——前者阈值对 A 股 ETF 几乎不可达（见 §9.4 缺陷 9.4），后者只管 defense 层，管不到 core 层的高 beta。

#### 结论

- **"熊市大力加仓"不会发生**（没有加仓路径；卫星被砍、现金增多）。
- **"熊市死拿不放"会发生**：核心层红利/保底锚之外的非强制名额，靠**相对 factor 排序**竞争，**无市态绝对防线**；科创50/创业板在动量分转负后仍可能靠（a）相对排名领先（b）C2 名称 +1.5（c）F6 仅限合计 40%——留在核心层拿到接近全仓的主要权重。对 aggressive 方案而言这是**配置哲学的一部分**（进攻型 = 接受高 beta），但当前实现**没有把"市态转熊"显式转化为"核心层降 beta"**，只砍了不痛不痒的卫星层。
- **建议方向**（详见 §10 9-F1）：给 core 层加"市态绝对防线"——动量/情绪聚合分为负且市态为 bear/correction 时，成长宽基降权或降到 defense 预算口径；将 F0-5 已在卫星层验证的 `factor ≤ 阈值不给权` 模式**扩展到 core 层**。

### 9.3 合理性总评

| 维度 | 评价 |
|---|---|
| 工程成熟度 | ⭐ 优秀——强制保底、去重、回补、预算用满、跨方案互斥，防御性编码到位 |
| 纯函数设计 | ⭐ 全引擎零 I/O，可测性极佳 |
| 风偏差异化 | ⚠️ C2 名称关键字是硬编码启发式，±1.5 力度大、易漏判新主题 |
| 因子消费 | ⚠️ 直接消费 §4 缺陷一/二量纲污染的因子分，上游 bug 在下游两级放大 |
| 组合风险 | ⚠️ **相关性/波动率/回撤目标全部只声明未接线**（见 9.5 缺陷 9.3） |
| 市态响应 | ⚠️ **只调预算、不调选择**——核心层在熊市近乎无响应（见 9.2） |

### 9.4 新增缺陷明细（证据链）

#### 9.4.1 【严重】缺陷 9.1：核心层无市态绝对防线（高 beta 死拿）

- **锚点**：`_select_and_weight` L434-440（core 层取 top-N 无分数门槛）vs 卫星层 P1-D（L424-432）有 `> -0.3` 过滤；`dynamic_layer_budget` bear 分支（budgets L100-107）只调预算不调选择。
- **机理**：市态转熊只影响「每层预算」，不影响「层内选谁」。core 层唯一的质量防线是下游风控的 -40% 月跌（几乎不可达）与 F6 的合计 40% 上限（偏宽）。
- **后果**：科创50/创业板指等成长宽基在熊市依然可占核心层最大份额，与「市态 note 建议以防御为主」的文案互相矛盾。

#### 9.4.2 【中】缺陷 9.2：C2 名称关键字修正——硬编码信任词表

- **锚点**：`allocation_engine` L358-396，`_RISKY_THEMES`/`_SAFE_THEMES` 写死中文词表。
- **机理**：判定建立在 ETF 名称而非数据上；`valuation/sentiment 无区分度时` 触发（L380 `valuation_missing and not has_meaningful_style`），即「数据缺时用名字猜风险」。系数 ±1.5（相对因子分常态 ±5，占比 30%）力度激进；新增主题（信创/数据要素等）会漏判，词表是隐性回归源。
- **（review 补充）**：确切系数为 defensive +0.8/-1.5、aggressive +1.5/-0.3、balanced 无分支（见 §10.2 表）；`budgets.py` 的 `STRATEGY_META.c2_adjust`（L25/41/57）声明系数**实际未被消费**（死元数据）。

#### 9.4.3 【严重】缺陷 9.3：组合风险参数零接线（相关性/波动率/回撤目标为空壳）

- **锚点**：`RiskSettings.max_correlation=0.95` / `max_turnover_rate=0.50`（risk_controls L31-32）注释 `Reserve for future constraints`，全代码库无消费方；`STRATEGY_META.max_drawdown`（budgets L21/51）只进前端展示文案。
- **机理**：声明了相关性上限、换手上限、最大回撤目标，**没有一个参与实际计算**。实际约束有：单只≤30%（L245-248）、红利类合计≤15%（L250-259）、成长宽基合计≤core×40%（F6 L281-299）、**行业集中度（L315-329）实为「最大行业权重 ≤ √0.40 ≈ 63%」的间接钳制**（review 修正：L322 触发条件 `hhi >= 0.40`，L324 压缩目标 `target_weight = 0.40**0.5`，并非严格「HHI<0.40」）、层预算校验（L301-313）、归一化（L331-336）等。
- **后果**：方案声称的「最大回撤 -35%」无任何机制保证；组合层面（相关性/联合波动/VaR）无约束，与候选池排序同样落在「单资产启发式」层面。

#### 9.4.4 【中】缺陷 9.4：`filter_extreme_drawdown` 阈值 -40% 几乎不可达（死规则）

- **锚点**：risk_controls L48-87。A 股 ETF 月跌 40% 在涨跌停制度下需连续近跌停半个月，现实中罕见（除 2015 分级基金）。该规则形同虚设，却给验证者造成"已有绝对防线"的假象——这是 §9.2 结论中把 Downstream 风控误认为核心层防线的**来源**（§9.2 结论第 5 点与「结论」段的直接关联点）。

#### 9.4.5 【中】缺陷 9.5：三层权重体系割裂 + 魔法数无校准

- `_LAYER_WEIGHTS`（候选池排序用，market_data_hub L119）≠ `_PROFILE_WEIGHTS`（层内优选用，allocation_engine L346-350）≠ 幂律指数 `0.08`（L259）≠ 重叠惩罚 `-1.5`（L395）——五组数字互不联动、全部手调无校准来源，延续 §4.3 缺陷三的「无实证闭环」到消费链。

### 9.5 与 §4 上游缺陷的联动（下游放大链）

```
§4.1 raw 量纲污染（technical 超买加分）
  └→ §4.2 composite 量纲死值（liquidity/scale 分量≈0，排序纯因子主导）
       └→ allocation_engine 直接消费 get_factor_matrix（L339）
            ├→ 上游高分标的在分配层二次获高分（幂律配权放大差距）
            └→ C2 +1.5 名称加分叠加 → 科创主题在 aggressive 双重虚高
```

修复优先级上，**§4 上游缺陷要先修**；下游只做市态防线（§10 9-F1）是等价且最便宜的独立补丁。

---

## 10. 分配器/风控修复方案（只设计，不实施，延续 §5 批次）

> 以下方案与 §5 方案一/二/三无冲突，可在任一上游修复后独立落地；9-F1 成本最低、价值最高，建议最先。

### 10.1 9-F1：core 层市态绝对防线（修缺陷 9.1，最高价值）

**核心思路**：把卫星层已验证的「负分不给权」（P1-D，L424-432）的判定模式扩展到 core，并用市态门控成长宽基。

**关键分歧点——本方案以 B 为默认（决策完成，非待拍板）**：
- 方案 A（彻底）：熊市 core 成长宽基负分即剔除，名额回补红利/宽基锚；
- 方案 B（温和，**默认实施**）：负分成长宽基权重压到 MIN_WEIGHT（1%）+ 释放预算回流 defense；
- 决策依据：与「进攻型 = 接受高 beta」哲学兼容（A 在熊市剥夺 aggressive 全部进攻敞口，过于激进），同时切断"熊市死拿"。A 保留为配置开关 `core_bear_growth_policy: "trim"|"remove"`（默认 `trim`），后续回测数据支持再切换。

**实现位置（review 细化——改为风控管线内新检查函数，规避跨层回流复杂度）**：
- **不建议在 `_select_and_weight` 内实现**：该函数逐层独立、无跨层上下文（core/defense 是独立调用），回流 defense 需要 allocate 层协调；
- **建议**：新增 `risk_controls.apply_core_bear_growth_trim(strategy, layer_budget, regime)`，插入 `apply_risk_controls`（L213）管线中 **F6（L281-299）之后、层预算校验（L301-313）之前**：
  - F6 先压成长宽基**合计** ≤ core×40%；9-F1 再压**负分单只**到 1%——两段互补，顺序不可反（若 9-F1 在前，F6 的等比压缩会把 1% 权重再压下去，语义混乱）；
  - 层预算校验在后：defense 吸收释放额后若超预算会被压缩回 budget（L307-313），超限部分隐式转现金——**行为可预期，无需额外处理**（也无需改 budgets）；
- **regime 参数可得性（实施时核对）**：`apply_risk_controls` 签名需能拿到当前市态（现状签名不含则扩展，调用链上游 `allocate` 已有 regime）；
- **`factor_score` 键的三个非 composite 特例（review 确认，必须排除）**：
  1. 强制标的（L308）：`factor_score = factor_matrix[sym]["technical"]`——是 technical 单因子值，非 composite；
  2. U11 去重回补的新宽基（L861）：`factor_score = _cscore(...)`——四因子等权和，非带风偏权重的 composite；
  3. C2 引入的 588000（L950）在 satellite 层，不进 core_alloc。
  排除方式：`a.get("symbol") in MANDATORY_CODES` 跳过强制标的；U11 回补标的在 core 层出现路径少，实施时核对（必要时以来源标记/`selection_rationale` 前缀识别后同样跳过）。

**完整伪代码（合并原两段，review 修订）**：

```python
# risk_controls.apply_core_bear_growth_trim —— 新函数，插入 apply_risk_controls 管线（F6 之后、层预算校验之前）
def apply_core_bear_growth_trim(allocations: list[dict], layer_budget: dict, regime: str) -> list[dict]:
    if regime not in ("bear", "correction", "panic"):
        return allocations
    released = 0.0
    for a in allocations:
        if a.get("layer") != "core":
            continue
        if a.get("symbol") in MANDATORY_CODES:          # 强制保底锚（510300/159338）跳过
            continue
        if _is_growth_wide_basis(a) and a.get("factor_score", 0) < 0:
            released += a["weight"] - MIN_WEIGHT         # MIN_WEIGHT = 0.01（allocation_engine L22）
            a["weight"] = MIN_WEIGHT                     # 勿用 MANDATORY_MIN_WEIGHT（0.03，L230）
    # 回流：释放额按防御权重比例加到 defense（保持 Σ=1，防预算静默丢弃）
    # defense 吸收后若超预算 → 层预算校验（L301-313）压回 budget，超限部分隐式转现金
    if released > 0:
        defense = [a for a in allocations if a.get("layer") == "defense"]
        defense_sum = sum(a.get("weight", 0.0) for a in defense)
        if defense and defense_sum > 0:
            for d in defense:
                d["weight"] = round(d["weight"] + released * (d["weight"] / defense_sum), 4)
    return allocations
```

**验证（负向断言，细化）**——基准场景（defense 未超预算）构造：市态=bear、进攻方案 core 层含 科创50（非强制、composite=-2.0）与 510300（强制），defense 层 1 只（未超预算）：
1. 科创50 权重 ≤ 1%（修复前按相对排序给 ~10%+）；
2. 510300 权重不变（强制标的豁免）；
3. `Σcore + Σdefense` 与执行前一致（释放额全部回流，无权重丢失）；
4. 市态=neutral 时函数为 no-op（不触发）。

### 10.2 9-F2：C2 词表降级为软信号（修缺陷 9.2）

**review 细化（原「±1.5/±0.8/±0.3 降为 ±0.6/±0.3」为不精确简写）**：C2 确切系数（allocation_engine L358-396，触发条件 `valuation_missing and not has_meaningful_style` L380）：

| strategy | 命中 `_SAFE_THEMES` | 命中 `_RISKY_THEMES` | 未命中 |
|---|---|---|---|
| defensive | +0.8（L384） | **-1.5**（L386） | 0 |
| aggressive | -0.3（L392） | **+1.5**（L390） | 0 |
| balanced | 无分支，恒 0 | 无分支，恒 0 | 0 |

**降级目标（明确数值）**：`risky` 方向 ±1.5 → **±0.6**（相对因子分常态 ±5，占比从 30% 降到 12%）；`safe_bonus` 0.8 → **0.3**；aggressive `safe_penalty` -0.3 保持（已是软信号量级）。只在**因子分无区分度**时生效（现状已如此，不改）。

**配置化（含死元数据清理，review 确认）**：
- 词表（`_RISKY_THEMES`/`_SAFE_THEMES`，L361-364）与系数迁到集中配置（`factor_definitions.yaml` 或 engine 内新常量模块），新增主题走配置而非改代码；
- **连带发现**：`budgets.py` `STRATEGY_META.c2_adjust`（L25/41/57）声明的系数**实际未被 `_select_and_weight` 消费**（消费的是 L358-396 硬编码）——配置化时**二选一**：让 `_select_and_weight` 改为消费 `STRATEGY_META.c2_adjust`（推荐，元数据与行为合一，且 defensive/aggressive 两套配置天然归位）或删除该元数据字段，杜绝「声明与实现脱节」；
- 远期：以波动率/回撤因子替代名称词表（见 9.4.3 关联）。

**验证**：① 词表迁移 YAML 后行为不变（回归对照：同 fixture 输入，迁移前后 composite 逐标的一致）；② 新主题（如「信创」「数据要素」）加入配置后能命中（负向断言：配置命中生效而非漏判）；③ 系数降级后 aggressive 命中科创主题的 composite 加成 ≤0.6（防降级未生效回归）。

### 10.3 9-F3：风控组合风险接线（修缺陷 9.3，中期）

**核心设计约束（review 补充——必须先于实现确认）**：`engine/` 包是**纯函数零 I/O**（AGENTS.md 约定 + budgets/risk_controls 文件头声明），组合波动率/协方差需要历史行情数据——**数据获取必须在调用侧完成，不得在 risk_controls 内做 I/O**。

**设计（分层）**：
1. **数据准备（上游，调用侧）**：在 `allocate()` 调用链上游（market_data_hub 已有 `_kline_cache` 历史通道），对**选中标的**计算 rolling 60d 收益协方差矩阵 Σ 与单标的波动率 σᵢ，随 strategy 上下文（或参数）传入 `apply_risk_controls`；
   - 冷启动：任一标的 K 线 < 60d 或 Σ 不可求逆 → 跳过本节检查（记日志，不阻断分配），防「数据缺导致全组合失败」；
2. **组合波动率上限**（接 `RiskSettings.max_drawdown`）：目标波动率 `σ_target = -max_drawdown / 2.33`（正态近似 VaR 95%，aggressive max_drawdown=-0.35 → σ_target ≈ 0.15）；
   - `σ_p = sqrt(wᵀΣw)` > σ_target 时：按**边际风险贡献** `wᵢ·(Σw)ᵢ/σ_p²` 降序，对最高贡献标的等比压缩，迭代至满足或达最大迭代（5 次），压缩释放额转现金；
3. **max_correlation 检查**：两两相关 `ρᵢⱼ > 0.95` 的高相关对，合计权重 > 阈值（默认 0.40，可配置）→ 压缩权重较小者至阈值内；
4. **max_turnover_rate（可选，第二阶段）**：需上一期持仓输入（当前无持久化持仓历史）——本期**明确标注「未接线」不冒充**，待持仓历史通道建立后再接；
5. **max_correlation / max_turnover_rate 升级**：从 `RiskSettings`（L31-32）的 Reserve 注释升级为真实消费点（`rg` 验证：两字段在 risk_controls 内有读取处）。

**验证（行为负向断言，§11 表已列）**：① 构造 ρ=0.97 高相关两只标的各 30% 权重 → 断言 9-F3 上线后合计权重被压缩至阈值内（修复前无此约束，直接通过）；② 构造 σ_p 超 σ_target 的组合 → 断言最高风险贡献标的权重下降且 Σ 权重守恒（释放额转现金）；③ 冷启动（无 K 线）→ 断言不报错、分配行为与现状一致。

### 10.4 9-F4：阈值/参数集中校准（修缺陷 9.5，并入 §5.3 阶段二）

- 幂律指数 0.08、重叠惩罚 -1.5、MIN/MAX_WEIGHT、层容量（`top_n` 25 / `MAX_PER_LAYER` 8/20/10，§4.5）等纳入离线校准框架（与 §5.3 阶段二共用回放数据）；
- 三套权重（`_LAYER_WEIGHTS`/`_PROFILE_WEIGHTS`/幂律）+ 层容量以单一校准报告驱动，杜绝各层各自手调；core 层容量硬约束 `MAX_PER_LAYER.core ≥ layer_count.core + 3` 一并校验。

---

## 11. 追加部分的验收口径（§9/§10 专用）

| 批次 | 内容 | DoD 要点 |
|---|---|---|
| 9-F1 | core 市态绝对防线 | 负向断言 4 条（§10.1 验证：bear+负分成长宽基 ≤1% / 强制锚不变 / Σ层权重守恒 / neutral no-op）+ verify_e2e 全 PASS |
| 9-F2 | C2 词表降级/配置化 | 词表迁移 YAML 后行为不变（回归对照）+ 新主题配置命中 + 系数降级生效（risky ≤±0.6）+ `c2_adjust` 死元数据二选一清理（消费或删除，`rg` 验证无残留声明） |
| 9-F3 | 风控组合风险接线 | **行为负向断言**：构造 ρ>0.95 高相关两只标的，断言 9-F3 上线后组合权重被压缩 / max_correlation 约束生效（非仅存在性）；`max_correlation`/`max_turnover_rate` 有真实消费点（`rg` 验证非脚手架） |
| 9-F4 | 阈值统一校准 | 校准报告产出 + 线上参数 = 报告推荐值（含 §4.5 层容量：`MAX_PER_LAYER.core ≥ layer_count.core + 3` 约束生效） |

**追加后的总迭代边界**：§9/§10 是 §2 评估对象（候选池+因子）的下游延伸；两者实施独立、可并行，**先修 §4 上游、再落 §10 下游**（上游 bug 不修时下游修复会被污染的量纲掩盖）。

**合并迭代顺序（§5 + §10 全部方案，按依赖排序）**：

| 顺序 | 批次 | 内容 | 依赖/理由 |
|---|---|---|---|
| 1 | 9-F1 | core 市态绝对防线 | 独立可先行（用现有 composite，成本最低价值最高） |
| 2 | P0·方案四 | amount 单位统一 + 单位契约 + 跨源校验（§5.4） | **（review 修正：原表漏掉方案四，补入第 2 位）** 候选池入口数据 bug，其余方案评估的"真实数据前提"（§4.6.3）；改 etf_scanner 数据源层，不碰 aggregate 链，可独立先行 |
| 3 | P0·方案一 | raw 方向化 + 显式聚合映射 | 修方向性 bug；先落映射基座（aggregate_factor_scores 同函数，须顺序合并） |
| 4 | P0·方案三阶段一 | IC 加权聚合 | 在映射基座之上叠加 IC 权重；纯增量系数 |
| 5 | P1·方案二 | composite 量纲统一 | **（review 修正：依赖方案四 + 方案一双前置）** amount 单位修复是层内 `_pct_rank` 正确性的数据前提；方向化校正后量纲才是真分数 |
| 6 | P1·方案三阶段二 + 9-F4 | 权重校准 + 阈值统一校准 | 离线研究先行，共用回放数据；9-F4 并入此阶段（§10.4） |
| 7 | 9-F2 | C2 词表降级/配置化 | 依赖校准报告（可用波动/回撤因子替代词表后弱化） |
| 8 | 9-F3 | 风控组合风险接线 | 中期；与阶段二/三共用回放数据 |
| 9 | P2 | 阶段三 + 双重标准化收敛（§4.4） | 重构性质，独立排期 |

> 说明：9-F1 不依赖任何上游修复即可先行落地（现有 factor_scores 口径已可用）；9-F2 与方案三阶段二存在反馈关系（词表弱化程度取决于校准报告），故排在阶段二之后。