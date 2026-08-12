# Round19 组合诊断（2026-08-12）：关联度 / 持仓刷新 / K线指标副图 / 成本价买卖重算 / 板块热度0 / 导航栏离线 / 自选技术分析空数据 / 港股指数补全 / 美股技术分析数据不足 / 测试防护盲区复盘

> **性质**：对用户九个问题 + 一轮测试防护盲区复盘的**分析与方案设计文档**——本份只设计不实施。
> **问题 1（§一~§六）**：「最近生成的组合里，标的之间的关联度如何」——design 514-519 实盘数据 + 60 日真实收益率相关性实测 + 代码缺口定位。
> **问题 2（§七~§十一）**：「更新组合持仓或者增删标的，需要手动刷新才会显示新的持仓数据」——前后端数据流断点定位。
> **问题 3（§十六~§十九）**：「增持时当前价即买入成本；仓位变更视作买卖、按加权平均重算成本价」——后端落库断点 + 买卖语义设计；**已确认（2026-08-12）：「调整仓位」时同步联动更新 target_weight（按新市值/总市值推算）**。
> **问题 4（§二十~§二十三）**：「A股板块热度大量涨跌幅为 0（还是没修）」——round16 P0-17① 主路径 akshare 走 push2 被 EM 风控断连、静默回退全失效旧链；push2delay 分页 300/300 真实数据已实测可行；**已确认（2026-08-12）：主路径切 EM spot 的板块名体系变化，用户接受**。
> **问题 5（§十二~§十五）**：「K 线下方增加 RSI/KDJ/MACD 三选一可切换副图（K 线与成交额固定展示）」——纯前端需求，数据层已就绪。
> **问题 6（§二十四~§二十七）**：「页面上一直展示离线状态」——后端 WS 实测正常，根因是连接生命周期绑定 Dashboard 页而展示在全局导航栏，离开首页即断连且语义误导；**阶段 1 方案 A（WS 全站常驻）已由用户确认（2026-08-12）**。
> **问题 7（§二十八~§三十一）**：「自选列表江波龙技术分析数据空、转AI分析按钮没反应」——① watchlist 存 `sz301308`（带前缀）而 `fetch_history` 入口不归一化（实测 0 vs 800 行）；② `MarketAnalysis.vue:45` WatchlistPanel 漏绑 `@analyze`；**前缀来源已排查定位（2026-08-12）：手动输入不经归一化（add_watchlist:1630 原样入库 + addItem:318 原样提交）**。
> **问题 8（§三十二~§三十五）**：「港股指数自动补全有明显改善但不全」——indices_meta HK 仅 25 条（新浪源 ~38 条无行业/主题指数 + 静态段仅恒生港股通/主流 4 条），恒生行业分类/综合行业/主题指数 0 命中；方案为静态段扩展（腾讯 `hk{sym}` 可验证 HSCI/HSF，HSAHC 等需另核）+ **行情链路排查完成（2026-08-12）：fetch_index_history 仅支持 A 股，HK 指数 K 线系统性缺失（连 HSI/HSTECH 都空），腾讯 hk{sym} 320 根实证为修复源**。
> **问题 9（§三十六~§三十九）**：「美股自选技术分析显示数据不足」——US K 线主源 akshare `stock_us_hist` 走东财被 EM 风控断连（全挂）、降级链 finnhub/alphavantage 限流失效、yfinance 被墙；**已实测 TickFlow `AAPL.US`/`SPY.US` 各 500 根（含当日收盘）升级为主修复**（P0，`_tickflow_kline` 扩 US/HK 分支）+ 新浪 `stock_us_daily` 全量兜底（SPY 6438 行）+ stale 缓存兜底（P0）+ 降级链重排（akshare 3s 快速失败、alphavantage 提前）+ 弹窗空态统一。
> **状态**：待 review 达标后进入实施（对照 docs/design-checklist.md 8 项）。
> **验证窗口**：问题 1 相关性实测数据为 **2026-08-12 收盘后**（fetch_history 真实日 K，240 根，含当日收盘）；问题 4/9 的外部行情源复测需**交易日 9:30-15:00 + 真实环境**（涨跌幅/源链盘中变化），结构/缓存逻辑验证无窗口限制（问题 9 已实测 akshare 全挂、腾讯 AAPL/QQQ 321 根）；问题 6 WS 握手、问题 7 K 线/绑定、问题 8 元数据层均为本日任意时段实测。问题 2/3/5 无行情源窗口限制。非窗口结论已打标。

---

## 一、结论摘要

1. **现有组合的「关联度管控」全部是名称/指数关键词启发式**（O16 大盘宽基族互斥 / F6 成长宽基集中度 / F0-5+O17 科创系配额 / `_normalize_segment` 板块归并），**全库没有任何基于历史收益的真实相关性计算**。`RISK_SETTINGS.max_correlation = 0.95` 是预留字段，注释自认 "Reserve for future constraints"，无任何代码消费（`rg "max_correlation"` 仅 `risk_controls.py:31` 定义处）。
2. **实测最近 balanced 组合（design 519）91 对标的中，12 对 r > 0.8（13%）**，其中 **4 对 r > 0.9**；core 层 5 只宽基两两高相关（0.81~0.98），合计权重 43%——核心层的「分散」实为「同一 A 股 beta 的 5 个切片」。
3. **存在 3 类真实相关性风险**（详见 §三）：
   - **同指数双持有**：aggressive 方案 `159338 中证A500ETF`（w=5%）+ `563360 A500ETF`（w=20.64%）跟踪**同一中证A500 指数**，合计 25.64%——本质是同一标的，r≈1.0；
   - **跨名称高相关对**：`588200 科创芯片` + `588170 科创半导体`/`159995 芯片`（半导体板块，r≈0.9+）、`513180 恒生科技` + `513050 中概互联`（r=0.899）、`513300 纳指` + `513500 标普`（defensive，r≈0.9）；
   - **强制锚高相关无标注**：`510300 沪深300` + `159338 中证A500` 实测 **r=0.983**，二者为 MANDATORY_CODES 豁免共存，但报告无任何提示。
4. **`rationale.py:44` 的「低相关性N，有效平衡组合波动」是固定文案模板**（防御层短语池按 symbol hash 随机抽取），与真实相关性无关——存在「文案声称低相关、实际无计算支撑」的诚实性缺口。

---

## 二、现状评估（实测数据）

### 2.1 数据口径与探针

- **探针（D1，2026-08-12 收盘后）**：`china_market.fetch_history(sym, "A", "daily")` 可拉取 240 根真实日 K（`tmp_probe_kline.py`：510300 首拉 1.5s、缓存后 0.1s，最新含 2026-08-12 收盘）——相关性计算的数据源可行性**已验证**。
- 相关性口径：**60 个交易日（2026-05-20 ~ 2026-08-12）日收益率 Pearson 相关系数**，日期 inner-join 对齐。

### 2.2 balanced 方案（design 519）相关矩阵实测

标的 13 只（core 5 + satellite 6 + defense 3），91 对。**r > 0.8 的高相关对（12 对）**：

| r | 标的 A | 标的 B | 合计权重 | 备注 |
|---|---|---|---|---|
| +0.983 | 510300 沪深300 | 159338 中证A500 | 10.0% | 强制锚双持有（O16 豁免） |
| +0.941 | 159338 中证A500 | 159915 创业板 | 15.0% | core 内 |
| +0.940 | 159338 中证A500 | 510500 中证500 | 18.1% | core 内 |
| +0.916 | 510300 沪深300 | 159915 创业板 | 15.0% | core 内 |
| +0.899 | 513180 恒生科技 | 513050 中概互联 | 6.8% | satellite 双中概 |
| +0.896 | 159915 创业板 | 510500 中证500 | 23.1% | core 内 |
| +0.889 | 515880 通信 | 588170 科创半导体 | 6.5% | 跨名称（通信 vs 半导体） |
| +0.882 | 510300 沪深300 | 510500 中证500 | 18.1% | core 内 |
| +0.867 | 588000 科创50 | 510500 中证500 | 23.0% | core 内 |
| +0.855 | 159915 创业板 | 588000 科创50 | 20.0% | F6 成长宽基 cap 擦线（0.2000 vs 0.20） |
| +0.846 | 159338 中证A500 | 588000 科创50 | 15.0% | core 内 |
| +0.809 | 510300 沪深300 | 588000 科创50 | 15.0% | core 内 |

**组合级指标**：91 对平均 r = **+0.298**（被 40+ 对跨资产对拉低）、中位数 +0.232、最大 +0.983。
**低相关资产（真正的分散来源）仅 5 只、合计权重 ~20%**：30年国债（avg_r +0.146）、黄金（+0.215）、消费（-0.004）、科创芯片（+0.043）、中概互联（+0.209）。

### 2.3 三套方案（design 519）双持有/高相关清单

| 方案 | 双持有/高相关组 | 合计权重 | 风险等级 |
|---|---|---|---|
| aggressive | 159338 中证A500 + 563360 A500（**同一指数**） | 25.6% | 🔴 同标的 |
| aggressive | 159995 芯片 + 588200 科创芯片（半导体） | 8.9% | 🟠 高相关 |
| balanced | 588200 科创芯片 + 588170 科创半导体（半导体） | 5.8% | 🟠 高相关 |
| balanced | 513180 恒生科技 + 513050 中概互联（r=0.899） | 6.8% | 🟠 高相关 |
| balanced | 510300 沪深300 + 159338 中证A500（r=0.983，强制锚） | 10.0% | 🟡 需标注 |
| defensive | 510300 + 159338 + 510050 上证50（三个大盘宽基） | 29.7% | 🟠 高相关 |
| defensive | 159570 港股通创新药 + 513120 港股创新药（双持有） | 6.0% | 🟠 高相关 |
| defensive | 512880 证券 + 513090 香港证券（A/港证券） | 5.9% | 🟠 高相关 |
| defensive | 513300 纳指 + 513500 标普（美股双宽基） | 6.7% | 🟡 可接受（防御配置） |

---

## 三、根因定位（代码级证据链）

### 3.1 无真实相关性计算——`max_correlation` 预留未实施

- `risk_controls.py:21-32`：`RISK_SETTINGS` 定义 `max_correlation: float = 0.95`，注释 `# Reserve for future constraints (e.g., correlation, turnover)`；
- `rg -n "max_correlation" backend/app` 仅命中定义处（`risk_controls.py:31`），**零消费**；
- 现有「相关性近似」全部为关键词启发式：`allocation_engine.py:176-198`（大盘宽基族）、`:151-168`（成长宽基）、`:95-101`（科创系）、`risk_controls.py:336-354`（F6 成长 cap）、`allocation_engine.py:66-92`（`_normalize_segment` 板块归并）——均不读历史收益。

### 3.2 同指数双持有绕过互斥——tracked_index 缺失 + 裸名漏判

- `instruments` 表**无 tracked_index 字段**（`tmp_idx.py` 实测 19 只全为 None）；`etf_index_mapping.json` 仅 68 条映射，`563360`/`159338`/`510050` 等**均无映射**；
- O16 大盘宽基族互斥（`allocation_engine.py:753-794`）只拦截**名称文本命中** `_LARGE_CAP_WIDE_BASIS_KEYWORDS`（`:176-179`，含 "中证A500"）的标的：`563360 A500ETF华泰柏瑞` 名称**不含「中证」前缀**、tracked_index 为空 → `_is_large_cap_wide_basis` 判 False → 不触发互斥 → 与强制锚 159338 同仓；
- 同理 `_is_wide_basis`（`:137-143`）的 `_A_WIDE_BASIS_KEYWORDS`（`:130-134`）也无裸 "A500"——名称归一化兜底 `_extract_index_concept`（`:43-63`）虽能把 "A500ETF华泰柏瑞" 提取为 "A500"，但该函数未被互斥判定消费。

### 3.3 跨名称高相关对无约束

- F0-5/O17 科创配额（`allocation_engine.py:447-510`）按**名称关键词**（科创/半导体/芯片/AI）匹配：588200（科创）+ 588170（科创半导体）都被计入 tech、数量 2 ≤ `TECH_MAX_COUNT=2`、权重 5.8% ≤ `0.5×satellite budget` → 通过；但 **159995 芯片与 588200 科创芯片**（同半导体板块，r≈0.9+）、**515880 通信与 588170 半导体**（r=0.889）这类**跨关键词名**组合不在任何配额内；
- `_normalize_segment`（`:66-92`）把 588200 归 "科创"、159995 归 "芯片"、515880 归 "通信"——**不同 segment**，行业集中度 HHI（`risk_controls.py:375-389`）也算不到一起；
- 恒生科技+中概互联（r=0.899）：二者均非 tech 关键词、segment 不同，**无任何约束命中**。

### 3.4 F6 成长宽基 cap 擦线通过

- balanced `layer_budget.core = 0.50`（`budgets.py:39`）→ F6 cap = `0.50 × 40% = 0.20`（`risk_controls.py:344`）；
- design 519 实测 159915+588000 = 0.1001+0.0999 = **0.2000 ≈ 0.20**（浮点下未超）——「擦线通过」，组合仍有 20% 押注成长宽基（二者 r=0.855）。

### 3.5 rationale「低相关性」文案无计算支撑

- `rationale.py:39-45`：`_DEFENSE_PHRASES` 含 `"低相关性{n}，有效平衡组合波动"`、`"{n}与权益低相关，分散尾部风险"`；
- `rationale.py:98-99`：按 `md5(symbol)` hash 从短语池**随机抽一条**——文案与组合内其它标的的真实相关性**零关联**；
- 调用点：`allocation_engine.py:537`、`strategy_design.py:364`（build_rationale）。

---

## 四、设计方案（只设计不实施）

> 实施顺序：阶段 1（数据层）→ 阶段 2（约束层）→ 阶段 3（输出层）→ 阶段 4（测试验收）。阶段 2 依赖阶段 1 的相关矩阵；阶段 3 可与阶段 2 并行。

### 阶段 1：数据层——新增纯函数引擎 `engine/correlation.py`

**目标**：为组合内/候选池标的提供真实收益相关性矩阵，替代关键词启发式成为唯一相关性事实源。

1. **纯函数接口**：
   - `correlation_matrix(closes_by_symbol: dict[str, list[float]], window: int = 60) -> dict[tuple[str, str], float]`——按日期对齐后计算 Pearson r（无 I/O，可单测）；
   - `high_correlation_pairs(matrix, threshold=0.85) -> list[tuple[r, sym_a, sym_b]]`——高相关对清单；
   - `avg_correlation(matrix, symbols) -> float`——组合加权平均相关（权重作参）。
2. **数据获取**：复用 `market_data_hub.get_history(sym, market, "daily")`（`market_data_hub.py:1181-1188`，已有 300s K 线缓存 + 多源降级链）——**后台预热**拉取组合内全部标的（n≤15，串行 ~3-5s，实测 510300 首拉 1.5s），结果按 `{symbol: closes}` 缓存（TTL 对齐 K 线 300s），**不进请求热路径**。
3. **数据不足降级**（诚实性）：某标的历史 < 30 根 → 该标的相关系数标 None，**不得用 0 或默认值冒充**；报告层输出「相关性数据不足」而非编造数值。
4. **非兜底要求**：相关系数必须来自真实 K 线序列；拉取失败时相关矩阵整体标记 `available: false`，约束层静默跳过（不阻断生成），输出层显示「关联度体检暂不可用」——**禁止 fallback 硬编码相关值**。

### 阶段 2：约束层——相关性约束接入分配/风控

**2.1 同指数双持有硬约束（P0，堵 3.2 漏洞）**
- 在 `allocation_engine` 选层后、层预算校验前插入 `_dedup_same_index(allocations)`：
  - 判定：`tracked_index` 相同 **或** `_extract_index_concept(name)` 归一化后相同（"A500ETF华泰柏瑞"→"A500" == "中证A500ETF国泰"→"A500"？——注意 `_extract_index_concept` 对 "中证A500ETF国泰" 提取出 "中证A500"、对 "A500ETF华泰柏瑞" 提取 "A500"，需统一归一化：去公司名+后缀后再去 "中证" 前缀，归一到裸指数名）；
  - 处理：同指数仅保留 factor_score 高者，剔除方权重按同层其余标的权重比例回补；**强制锚（MANDATORY_CODES）豁免剔除**但进入报告「关联度提示」；
  - 覆盖 aggressive 的 159338+563360（r≈1.0）场景。
- **关键词补漏**：`_LARGE_CAP_WIDE_BASIS_KEYWORDS` / `_A_WIDE_BASIS_KEYWORDS` 增加裸 "A500"/"A50"（子串匹配，排除词 "中证1000" 机制沿用），堵 563360 漏判。

**2.2 高相关对权重约束（P1，`max_correlation` 生效）**
- 在 `risk_controls.apply_risk_controls`（`:266-410`）风控管线末尾追加 `apply_correlation_cap(strategies, correlation_matrix)`：
  - 对每套方案，枚举组合内所有配对，r > `RISK_SETTINGS.max_correlation`（0.95）**且合计权重 > 阈值（默认 15%）** 的配对，**剔除非强制锚、factor_score 较低者**（跨层剔除时剔除 satellite 优先），权重按同层比例回补；
  - 参数可配置（`RISK_SETTINGS.max_correlation` 已存在，仅需接通 + 增 `max_pair_weight` 字段）；
  - 阈值设计依据：实测 high pair 中 r>0.95 仅 1 对（强制锚 0.983）、r>0.9 有 4 对（含 0.941/0.940/0.916）——0.95 阈值只拦「同一 beta」极端对（含同指数双持有兜底），0.85 阈值拦「半导体/中概双持有」，**两档都配**：硬剔除档 0.95 + 压重档 0.85（压至合计 ≤15%）。
- 强制锚高相关对（510300+159338 r=0.983）：**不剔除**（用户拍板强制底仓），但权重钳制不高于现状，且必须进入报告提示（见阶段 3）。

**2.3 保留语义启发式的原因**
- O16/F6/F0-5 关键词规则仍是**无数据时的第一道防线**（K 线不可用时段兜底）——阶段 2 的收益相关性约束只在其**可用**时叠加生效，两者不互斥；`max_correlation` 相关矩阵不可用时不降级阻断。

### 阶段 3：输出层——「关联度体检」区块 + 文案诚实化

**3.1 报告新增区块**（后端 `design_report.py:_build_plan_tables`（`:55`）或新增 `_build_correlation_section`；前端 `DesignResult.vue` 消费）
- 输出：`design_text` 追加「**关联度体检**」小节——① 组合加权平均相关；② 高相关对清单（r>0.85，含权重合计）；③ 同指数双持有警告（如有）；④ 相关矩阵热力图（可选，CSS 色阶）；
- **强制锚提示**：510300+159338 等强制锚高相关对，报告标注「强制底仓为政策锚，二者相关 r=0.98，属已知取舍」；
- 数据不可用 → 输出「关联度体检暂不可用（行情数据不足）」，**不得输出默认数值**。

**3.2 rationale 文案诚实化**
- `rationale.py:_DEFENSE_PHRASES` 中「低相关性N，有效平衡组合波动」/「N与权益低相关」两句改为**条件触发**：仅当该标的与组合其它标的中位数 r < 0.3（可配置）时才从池中允许抽取；否则从 `_CORE_PHRASES` 换用中性文案（如「防御配置，降低组合波动」）；
- 实现：`build_rationale`（`rationale.py:102`）签名增加可选 `correlation_median: float | None` 参数，None（矩阵不可用）时**回退中性文案，不使用「低相关」字样**——杜绝无数据冒充低相关（对照反假完成 §2）。

### 阶段 4：测试与验收

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | `correlation_matrix` 纯函数单测（构造已知序列，如 r=1.0 / -1.0 / 0 三组） | 数值误差 < 1e-6；窗口 < 30 返回 None |
| T2 | `_dedup_same_index` 单测（mock 563360/159338 同指数场景） | aggressive 方案不得同时含两只中证A500（负向：含双 A500 → FAIL） |
| T3 | `apply_correlation_cap` 单测（构造 588200+159995 r=0.9 假矩阵） | 剔除后合计 ≤15% 或低分者移除；强制锚对不剔除但标注 |
| T4 | rationale 单测：correlation_median=None 时输出不含「低相关」字样 | 负向：None 时出现「低相关」→ FAIL |
| T5 | verify_e2e 内容断言扩展 | design 详情含「关联度体检」区块且非「暂无数据」占位 |
| T6 | 前端 `DesignResult.spec.js` | 区块渲染 + 高相关对清单非空（mock 响应） |

- **验证窗口**：T2/T3/T5 需要真实 K 线路径的端到端复测标注「交易日 9:30-15:00 + 真实环境」；窗口外只验证单测与构造数据路径。

---

## 五、design-checklist 对照

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ fetch_history 240 根实测可行 | ✅ 本文 §三 全部 file:line + 实测命令 | ✅ §四阶段4 标注 | ✅ 矩阵不可用即不可用，禁兜底值 | ✅ 约束挂 risk_controls 管线、文案挂 build_rationale、区块挂 design_report | ✅ 区块四态：可用/不足/失败/空 | ✅ 相关性 O(n²×60) 微秒级；拉取放后台缓存不进热路径 | ✅ ① 文案冒充低相关（rationale:44） |

## 六、已知问题与风险

1. **强制锚高相关共存是用户拍板设计**（510300+159338，r=0.983）：方案不改变强制锚构成，仅新增报告标注——若用户接受「双大盘锚」则维持，否则另行评估锚的选择；
2. **相关性随市态漂移**：60 日窗口在牛市/熊市相关性普遍抬升，方案固定窗口口径并在报告标注「截至 YYYY-MM-DD（60 日）」；
3. **数据缺口**：`etf_index_mapping.json` 仅 68 条映射，同指数判定依赖名称归一化兜底——名称归一化需覆盖裸 "A500"/"A50"/"A100" 等变体，实施时同步补 `_extract_index_concept` 归一化单测；
4. **性能债登记**：相关矩阵拉取 13 只 ~3-5s（后台预热，非热路径）；如后续需候选池级（1600+ 只）相关性则必须引入指数级近似（按 tracked_index 聚类），本方案不涉及。

---

# 第二部分：组合持仓增删后需手动刷新才显示新数据

## 七、结论摘要（问题 2）

1. **前端主断点**：`PortfolioManager.vue` 列表数据源是 `cachedEtfs` **ref 快照**（非响应式绑定 store），而 **`onAdd` / `onRemove` 操作后没有同步该快照**（对比 `onUpdate` / `autoDistributeWeights` 都调了 `loadTab()`）→ **新增标的列表不显示、删除标的列表不消失**，只有手动点刷新（`refreshPnl` / `loadTab` / 重载页面）才同步。
2. **前端次断点**：`AppTabs` slot 恒渲染（display 切换、组件常驻不重挂载）→ `onMounted(loadTab)` 只执行一次，快照持续陈旧；`PortfolioAnalysis.refreshData`（apply-design 成功后触发）只刷新 store、不同步 `cachedEtfs`。
3. **后端断点**：组合结构变更端点（增删改 / apply-design / import）写库后**无 WS 广播、无缓存失效**——跨页面/多浏览器标签页场景，其它已挂载组件无法感知变更；`/ws/portfolio` 频道只承载行情价格推送（`{type:'realtime'}`），前端 `market.js` 也只消费 realtime。

## 八、根因定位（证据链）

### 8.1 前端：`cachedEtfs` 快照与 store 不同步（主断点）

- `PortfolioManager.vue:429`：`const cachedEtfs = ref([])`——列表快照；`:435` `paginatedEtfs` 从 `cachedEtfs` 切片；模板 `:249` `v-for="etf in paginatedEtfs"`——**展示源是快照，不是 store**；
- `cachedEtfs` 仅两处同步：`loadTab()`（`:693` `cachedEtfs.value = currentEtfs.value`）与 `refreshPnl()`（`:683` 同）；
- 增删改三操作**不一致**：
  - `onAdd`（`:588` `await store.addEtf(...)`）→ 无 loadTab；
  - `onRemove`（`:615-618` `await store.removeEtf(symbol)`）→ 无 loadTab；
  - `onUpdate`（`:612`）与 `autoDistributeWeights`（`:630`）→ **有** `await loadTab()`；
- 结果：`store.addEtf` 内部 `fetchEtfs` 更新了 store（`stores/portfolio.js:26-30`）→ `currentEtfs` computed（`:467`）变化（capital-bar / 权重合计实时变）→ 但列表快照不变 → **增删不显示/不消失**。

### 8.2 前端：组件常驻 + apply-design 链路未同步快照

- `AppTabs.vue:64-76`：panels 恒渲染（`v-if="lazy || !lazy"` 恒真），仅 class 切换 active → **子组件（PortfolioManager）挂载后常驻，切 tab 不重挂载** → `onMounted(loadTab)`（`PortfolioManager.vue:830`）只执行一次；
- `PortfolioAnalysis.vue:25`：`<DashboardAiTools @applied="refreshData" />`；`:54-58` `refreshData` 只 `store.fetchEtfs(...)`——**不同步 PortfolioManager 的 cachedEtfs** → AI 工具页「应用设计」成功后切到持仓 tab，若 PortfolioManager 已挂载则仍显示旧快照。

### 8.3 后端：结构变更无广播（跨页面/多标签页断点）

- 结构变更端点全部纯 REST 写库：`portfolio.py:64-66`（POST /etfs）、`:69-74`（PUT）、`:77-81`（DELETE）、`:106-124`（apply-design）、`:156+`（import）——**无 `manager.broadcast`**；
- `/ws/portfolio` 频道存在（`ws.py:115-124`）但仅被 `market_refresh.py:23` 广播 `{type:'realtime', data: quotes}`（行情价格）；
- 前端 `stores/market.js:42` 连接 `/ws/portfolio`，`:59-88` onmessage 仅处理 `type === 'realtime'`（合并价格到 `realtimeData`）——**无任何结构变更消息类型分支**；
- 结论：同一浏览器**多标签页**或**其它已挂载页面**（如 Dashboard 组合摘要）在别处增删标的后，无法感知变更 → 手动刷新。

## 九、修复方案（按优先级，只设计不实施）

### 方案 A（P0，前端主断点——一行级最小修复 + 根因消除）

1. **一致性补齐**（最小改动）：`onAdd` / `onRemove` 末尾补 `await loadTab()`（与 `onUpdate` 对齐）——立即解决「增删不显示/不消失」；
2. **根因消除（推荐）**：移除 `cachedEtfs` 快照层——`paginatedEtfs` / `totalPages` / 空态判断直接基于 `currentEtfs`（computed 响应式）计算；`loadTab` / `refreshPnl` 里的快照同步行删除；分页语义由 `currentEtfs` 派生。**消除整类「store 已更新、快照未同步」问题**（apply-design、import、autoDistribute 均自动受益），不再依赖「每次操作后调 loadTab」的纪律性约定；
3. `PortfolioAnalysis.refreshData` 保持（store 全量刷新），快照层移除后列表自动响应。

### 方案 B（P1，后端广播 + 前端订阅——覆盖跨页面/多标签页）

1. **后端**：新增组合结构变更广播——`portfolio.py` 的 POST/PUT/DELETE /apply-design /import 成功后 `await manager.broadcast("portfolio", {"type": "portfolio_changed", "data": {"portfolio_type": ..., "symbols": [...]}})`（复用 `ws.py:70` 的 manager 单例；广播为异步协程、5s 超时保护已有 `ws.py:64`，失败不影响写库响应）；
2. **前端**：`stores/market.js` onmessage 增加 `type === 'portfolio_changed'` 分支 → 调 `usePortfolioStore().fetchEtfs()` 全量（on_exchange + off_exchange）——**已挂载组件与其它标签页自动刷新**；防抖 1s 防连发（批量操作触发多次广播）；
3. **多标签页**：各标签页独立 WS 连接 → 一页增删、其它页实时同步；关闭标签页/断线走既有重连机制（`market.js:106-114`）。

> **⚠️ 合并设计（与问题 6 方案 A 同通道，一次改造满足两个问题）**：问题 2 方案 B 的**后端广播**与问题 6 方案 A 的**前端全站连接**是同一 `/ws/portfolio` 通道的两面，**必须合并实施**（顺序：先问题 6 方案 A 连接提升 → 后本方案广播+分流）：
> - **通道**：复用 `/ws/portfolio`（`ws.py:115-124`），不新增端点；
> - **消息类型**：`realtime`（行情价格，`market_refresh.py:23` 既有广播）+ `portfolio_changed`（结构变更，本方案新增）——前端按 `msg.type` 分流（`market.js:67` realtime 分支保留、新增 portfolio_changed 分支）；
> - **载体**：问题 6 方案 A 将连接提升到 App.vue 全站常驻后，`portfolio_changed` 才能被**所有页面/标签页**接收（现状仅 Dashboard 连接时广播无消费者）——**问题 6 的连接改造是问题 2 广播消费的前提**；
> - **风险联动**：问题 6 风险 2（非首页页收到 realtime 的重复刷新/竞态）与本方案 fetchEtfs 防抖 1s 同源——统一在 `market.js` onmessage 分流层处理（realtime 合并去重 + portfolio_changed 防抖）；

### 方案 C（可选，诚实性/一致性标注）

- 新增标的的实时行情依赖 `market_data_hub` 行情缓存（300s TTL），刚添加时列表可能显示价格占位——**不改**（属数据源刷新节奏，非结构变更问题）；若需即时价格可在 add 响应后单独 `fetchRealtime`（`market.js:130-133`）一次，列为可选增强。

## 十、验收与 design-checklist 对照

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | 前端 vitest：`PortfolioManager` 增删用例（现有 `PortfolioManager.features.spec.js` / `selection.spec.js` 扩展） | onAdd 后列表含新标的（**不调 loadTab → FAIL**）；onRemove 后列表不含已删标的 |
| T2 | 前端 vitest：`portfolio_changed` 消息处理（mock WebSocket） | 收到该类型消息 → portfolio store 触发 fetchEtfs（**仅处理 realtime → FAIL**） |
| T3 | 后端 pytest：增删端点广播（mock manager） | POST/PUT/DELETE /apply-design 成功后调用 `manager.broadcast("portfolio", ...)` 一次 |
| T4 | 手动走查 | ① 持仓 tab 内增删即时更新；② AI 工具 apply-design → 持仓 tab 自动更新（组件常驻场景）；③ 双浏览器标签页一页增删、另一页自动刷新（**需 WS 可达，交易时段/非交易时段均可验结构变化**） |

**design-checklist 对照**：

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ 前端代码路径已读（PortfolioManager/AppTabs/market.js） | ✅ §八 全部 file:line | ✅ 结构变更无窗口限制；realtime 字段非交易时段可能为空已标注 | ✅ 方案 B 广播真实结构数据，无兜底值 | ✅ 广播挂 portfolio.py 端点、订阅挂 market.js onmessage | —（列表四态已具，方案不改渲染层） | ✅ 广播消息小、前端防抖 1s；无新增 IO | ✅ ① 快照与 store 双源（cachedEtfs） |

## 十一、已知问题与风险（问题 2）

1. **方案 B 广播与行情广播共用频道**：`/ws/portfolio` 同时承载 `realtime`（价格）与 `portfolio_changed`（结构）两类消息，前端需按 type 分流——消息结构向后兼容（realtime 消费逻辑不变）；
2. **快照层移除影响分页**：`cachedEtfs` 还承载「loadTab 失败重试时的旧数据保留」语义（`:687-706`）——移除后需用 loading/error 状态显式替代（加载中显示 spinner、失败显示错误态而非旧列表），对照四态要求；
3. **多标签页广播频率**：批量导入/均分权重会触发多次广播——前端防抖合并刷新，后端无需节流（广播负载极小）。

---

# 第三部分：K 线下方增加 RSI/KDJ/MACD 可切换副图

## 十二、结论摘要（问题 5）

1. **需求**：「K 线和成交额固定展示，下方副图由用户在 RSI / KDJ / MACD 中**三选一**切换展示」——即 K 线 + 量图固定、指标区**互斥单选**。
2. **现状差距**：
   - **TechnicalAnalysisModal（弹窗，WatchlistPanel/SectorHeatMap 技术分析入口）**：K 线图仅 2 个 grid（K 线+MA / 成交量），**无任何指标副图**，RSI/KDJ/MACD 仅以文本单元格展示——**与用户描述「K线下方只展示了成交额」完全吻合，是主战场**；
   - **AnalysisView（技术分析页）**：已有 K 线+量+MACD/KDJ/RSI 三副图，但为 **checkbox 多选**（`ControlPanel.vue:37-39`），非用户要的「三选一」单选；成交量还是独立开关（F14），非「固定展示」；
3. **数据层已就绪、后端零改动**：`GET /market/chart/{symbol}`（`compute_chart_data`，indicators.py:213）已返回 rsi/kdj/macd **完整序列**（P2-4 落地）；且 TechnicalAnalysisModal 的 `load()` **已并行调用 `marketApi.chart`**（`TechnicalAnalysisModal.vue:244`）并将结果存入 `chartData`（`:251`）——**弹窗只差渲染，序列数据现成**。

## 十三、现状证据链

- `TechnicalAnalysisModal.vue:129-184` `klineOption`：grid 仅 `[{top:30, height:'58%'}, {top:'72%', height:'16%'}]`（`:166-169`）、series 仅 candlestick+MA+volume bar（`:138-160`）——无指标系列；指标文本在 `:56-67` ta-grid 单元格（来自 `ind`，indicators 端点标量值）；
- `TechnicalAnalysisModal.vue:241-251` `load()`：`Promise.allSettled` 并行取 `indicators / signal / chart / fundFlow`，`chartData.value = chartPayload`——**chart 端点已调、序列已在手**；
- `AnalysisView.vue:112-122` `indicatorToggles`：ma5/10/20/60、boll、volume、macd、kdj、rsi 全为 checkbox 模型；`:88-96` 默认 `showMACD=true / showKDJ=false / showRSI=false`；`:277-283` grid 高度按开关叠加计算；
- `AnalysisView.vue:360-429`：MACD（柱+DIF/DEA）、KDJ（K/D/J 三线）、RSI（线 + 70/30 超买超卖 markLine）副图渲染完整——**可作为弹窗复用的渲染模板**；**但 MACD 的 `xAxis/yAxis/series` gridIndex 写死 `2`（`:365-379`）而 KDJ（`:388`）/RSI（`:413`）用 `grids.length` 动态索引——volume 关闭时 MACD 引用不存在的 grid → 副图不渲染（2026-08-12 用户实测「MACD 没数据」的根因）**；`gridHeights`（`:277`）`macd/kdj/rsi = 20/18/18`——KDJ/RSI 副图高度仅 ~16% 总高（用户实测「太窄没注意到」）；
- 后端 chart 数据实测（2026-08-12）：`/market/chart/510300|159995|513180|00700|AAPL` 的 `macd.dif/dea/histogram` 均为 **30 根且全非 None**（KDJ/RSI 全量 240-320 根）——**MACD 无数据是前端渲染问题、非数据源问题**；
- `ControlPanel.vue:35-39`：checkbox 渲染（`toggle-{key}` testid），F14 成交量独立开关；
- 后端：`indicators.py:264-289`（MACD 截断 30 根 P2-5、KDJ/RSI 全量序列 P2-4）、`market.py` chart 端点（`compute_chart_data` 出口）——**无改动点**。

## 十四、修复方案（只设计不实施）

### 阶段 1（P0，主需求）：TechnicalAnalysisModal 增加三选一指标副图

1. **副图渲染**：`klineOption` 增加第三 grid + 指标 series——数据直接从现有 `chartData.value` 取（`d.macd.dif/dea/histogram`、`d.kdj.k/d/j`、`d.rsi`），渲染模式**复制 AnalysisView:360-429 的三段**（或抽共享 composable，见阶段 3）；
2. **切换器**：新增 `activeIndicator = ref('macd')`（默认 MACD），弹窗 K 线图顶部（legend 行）加「RSI / KDJ / MACD」三选一 segmented 控件（复用项目 `AppTabs` 变体或新建小组件）；
3. **grid 布局**：`K线 58%→46%`、`量图 16%→14%`、`指标 ~20%`（弹窗高度有限，比例经小屏实测校准）；
4. **数据不足守卫**：`chartData` 无对应序列（如 `d.rsi` 为空数组/全 None）时，该项切换禁用并提示「数据不足」——**不渲染空副图、不显示假指标**（对照反假完成）；
5. **量图叠加成交额**（用户原话「成交额」）：弹窗量图现仅 volume bar；参考 `AnalysisView.vue:349-357`（F14）叠加 `d.amount` 序列为右侧刻度线——chartData.amount 已有，一行级增强，可并入阶段 1 或列为可选项。

### 阶段 2（P1，交互统一）：AnalysisView 改三选一单选 + 量图固定

> **2026-08-12 用户实测反馈**：当前 AnalysisView 勾选指标后 **KDJ/RSI 副图太窄（18% 高度，几乎注意不到）**，且 **MACD 直接不显示**——已定位为两个前端渲染问题（见 §十三 证据链补充），纳入本阶段一并修复：

1. **MACD gridIndex 写死 bug（P0 级，先修）**：`AnalysisView.vue:365-379` MACD 的 `xAxis/yAxis/series` 全部**写死 `gridIndex/xAxisIndex/yAxisIndex: 2`**，而 KDJ（`:388`）/RSI（`:413`）用 `grids.length` 动态索引——**volume 开关关闭时 grids 少一个，MACD 引用不存在的 grid → 副图不渲染（表现为「MACD 没数据」）**；改为 `const macdGridIdx = grids.length`（push 前取），与 KDJ/RSI 同模式；
2. **副图高度提升**：`gridHeights`（`:277`）`macd/kdj/rsi` 从 `20/18/18` 提升（建议 `22/24/24`，RSI 因 yAxis 固定 0-100 需最高），保证可读——单选后单指标 grid 占比 = 指标高度 / (main50+volume22+指标高度+10)；
3. `ControlPanel.vue`：macd/kdj/rsi 从 checkbox 改为 **radio 单选组**（互斥，默认 MACD）；`toggle-volume` 移除（成交量固定展示，`showVolume` 恒 true——顺带使 volume 恒在，降低 gridIndex 错位触发面，但动态索引仍必须做）；
4. `AnalysisView.vue`：`showMACD/showKDJ/showRSI` 三个 bool → `activeIndicator: 'macd'|'kdj'|'rsi'` 单值；grid 高度计算简化为 `main + volume + 1 指标`（`:277-284` 叠加逻辑删除）；MA/BOLL 开关保留（主图叠加，与指标区互斥无关）；
5. 同步更新依赖 `toggle-macd/kdj/rsi/volume` testid 的既有测试（`AnalysisView.spec.js`、`ChartComponents.spec.js` 等）。

### 阶段 3（P1，去重）：抽取共享指标渲染

- 新建 `composables/useIndicatorSeries.js`（纯函数：输入 chartData + indicator key → 输出 grid/series/xAxis/yAxis 片段），AnalysisView 与 TechnicalAnalysisModal 共用——**避免两处复制 3 段 series 代码**（MACD/KDJ/RSI 各 ~20 行）；切分粒度按「grid 高度、xAxis、yAxis、series」四元组，两组件各自组装 option。

### 阶段 4（测试与验收）

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | TechnicalAnalysisModal 新建 spec（mock chart 端点响应含 rsi/kdj/macd 序列） | 默认渲染 MACD 副图（grid 数=3）；切换 KDJ → MACD grid 消失、KDJ grid 出现（负向：切换后 MACD 仍渲染 → FAIL） |
| T2 | TechnicalAnalysisModal 数据不足用例 | 无 rsi 序列时 RSI 项禁用/提示，不渲染空副图（负向：渲染空 RSI grid → FAIL） |
| T3 | AnalysisView.spec.js 扩展 | 选 RSI 后 MACD 副图不渲染（互斥断言）；volume 固定渲染（移除开关后仍显示量图） |
| T4 | 手动走查 | WatchlistPanel/SectorHeatMap 弹窗三选一切换正常；技术分析页同交互；小屏（弹窗宽度）三 grid 无重叠 |
| T5 | 前端 `npm run build` + 既有全量 vitest | 无回归 |

**design-checklist 对照**：

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ chart 端点已调用（弹窗 :244）、序列已含（indicators.py:264-289） | ✅ §十三 全部 file:line | —（无外部行情源新增调用） | ✅ 数据不足禁用项，不渲染空图/假值 | ✅ 切换器 → 副图渲染（真实消费 chartData 序列） | ✅ 加载/空/数据不足/错误态沿用弹窗既有 | ✅ 纯前端渲染，无新增 IO；composable 去重 | ✅ ① 文本指标冒充图（现弹窗只有文本值） |

## 十五、已知问题与风险（问题 5）

1. **MACD 序列截断 30 根（已确认 2026-08-12：改为全量）**：`indicators.py:270-278`（P2-5 为减负载截断 `_macd_tail=30`）——**移除截断、MACD 与 KDJ/RSI 一致全量返回**；注意负载回弹（chart 响应增大，P2-5 当初截断原因），实施后量一次 chart 端点耗时（性能软门禁登记），超阈值再考虑前端滚动截取（渲染层截断不伤数据完整性）；
2. **弹窗小屏布局**：三 grid（K线/量/指标）在窄弹窗高度有限——grid 高度比例需小屏实测，必要时指标区固定像素高度（如 90px）而非百分比；
3. **既有测试破坏**：checkbox 改 radio + 移除 toggle-volume 会破坏 `AnalysisView.spec.js` / `ChartComponents.spec.js` 中按 testid 断言的用例——阶段 2 需同步改断言（保留 testid 名称可减少破坏面，但语义「多选→单选」必须体现）；
4. **交互语义确认（2026-08-12 用户补充反馈）**：AnalysisView 现状可**同时**展示 MACD+KDJ+RSI（用户实测发现 KDJ/RSI 太窄 + MACD 不显示——前者是高度 18% 不足、后者是 gridIndex 写死 bug，均已在 §十四 阶段 2 纳入修复）；改单选是需求明确要求（用户原话「当中的一个」）——「组合模式」开关（单选 / 全部显示）仍列为可选增强，默认单选。

---

# 第四部分：增持/仓位变更按买卖操作重算成本价

## 十六、结论摘要（问题 3）

1. **需求**：① 新增标的时**当前价即作为买入成本**（avg_cost）；② 仓位变更**视作买入/卖出**，按当前盈亏与操作份额**加权平均重算成本价**。
2. **现状断点**：
   - **`add_etf` / `update_etf` 不落库 `avg_cost` / `shares_held`**（schema 与模型列均有，`portfolio_service.py:128-146` 构造时未传、`:186-207` 未处理）——前端添加/编辑成本实际写不进 DB，`PortfolioManager.vue:819-820` 的乐观更新（`etf.avg_cost = ...`）**掩盖了该 bug**：界面显示成功、刷新后还原；
   - **无「当前价即成本」**：添加表单成本价手填（`PortfolioManager.vue:99-102`），搜索选中（`:554-556`）不自动带价；
   - **无买卖加权语义**：成本编辑是**直接覆盖**（`:804-827` `saveCostBasis` → `store.updateEtf`），无「增持加权 / 减持实现盈亏」计算；
   - **累计盈亏已依赖成本字段**：`calculate_cumulative_pnl`（`portfolio_service.py:1743+`）用 `avg_cost×shares_held` 算 `cost_basis` / `market_value`（`:1771-1773`），份额缺失时按目标权重估算（`:1798-1833`）——**落库修复后该链路数据即真实**。

## 十七、现状证据链

- 模型字段存在：`models/portfolio.py:18-19`（`avg_cost` / `shares_held` 列）+ `:25-27`（`cost_basis` property）；schema `PortfolioETFCreate`/`PortfolioETFUpdate` 均含两字段（`models/schemas.py:14-15/:31-32`）；
- **`add_etf` 丢弃成本**：`portfolio_service.py:134-142` 构造 `PortfolioETF(...)` 仅传 symbol/name/short_name/asset_type/target_weight/portfolio_type/tracked_index——前端 `PortfolioManager.vue:592-593` 传的 `avg_cost`/`shares_held` 被静默丢弃；
- **`update_etf` 丢弃成本**：`:193-204` 只处理 name/target_weight/is_active/portfolio_type/short_name/tracked_index——`PortfolioManager.vue:806-807` 编辑成本/份额传了也不生效；
- 前端乐观更新掩盖：`PortfolioManager.vue:819-820`（保存后本地赋值）→ 刷新后 `get_etfs`（`:427-429` 读 DB）还原；
- 累计盈亏链路：`portfolio_service.py:1771-1833`（真实份额：cost_basis=avg_cost×shares、market_value=shares×price；估算份额：target_amount/avg_cost）；
- 当前价可得性：前端 `pnlMap[etf.symbol].current_price`（`:311/:508`）；搜索响应 `searchResults`（`:526-527`，含 realtime 字段、R28 已确认可带价）；后端 `market_data_hub.get_portfolio_realtime` / `_with_realtime_prices`（`portfolio.py:29-53`）。

## 十八、修复方案（只设计不实施）

### 阶段 1（P0，先决 bug）：后端落库 `avg_cost` / `shares_held`

1. `add_etf`：构造函数补 `avg_cost=data.avg_cost, shares_held=data.shares_held`；
2. `update_etf`：补 `if data.avg_cost is not None: etf.avg_cost = data.avg_cost`、`if data.shares_held is not None: etf.shares_held = data.shares_held`；
3. 前端 `saveCostBasis` 的乐观更新保留（与落库一致后无害）；
4. **负向断言**：`add_etf` 传 avg_cost/shares_held → 落库后 `get_etfs` 返回值非空（当前行为传了也不存 → FAIL）。

### 阶段 2（P0，需求①）：添加标的目标当前价即成本

1. **前端**：`selectSearch`（`PortfolioManager.vue:554-556`）选中后自动填 `form.avg_cost = r.realtime?.price`（搜索响应带 realtime 时），用户可编辑覆盖；同时按现有 `formatShares` 估算逻辑（`:507-511`）预填 `form.shares_held`（可选，默认不填则沿用「按权重估算」提示）；
2. **后端兜底**：`add_etf` 中若 `avg_cost` 为空且 `shares_held` 非空 → 用 `market_data_hub` 实时价补 `avg_cost`（`_with_realtime_prices` 同通道，拿不到时保持 None 并标注「成本未知」，**不伪造价格**）；
3. 前端表单提示更新：成本价输入框 placeholder 改为「默认自动填入当前价」。

### 阶段 3（P0，需求②）：仓位变更 = 买卖操作（加权平均成本）

**后端**（在 `portfolio_service.py` 新增纯函数 + 端点）：
1. 纯函数 `recompute_cost_after_trade(old_shares, old_avg_cost, delta_shares, price) -> {new_avg_cost, new_shares, realized_pnl}`：
   - 买入（delta>0）：`new_avg_cost = (old_shares*old_avg_cost + delta*price) / (old_shares + delta)`；`realized_pnl = 0`；
   - 卖出（delta<0，`new_shares ≥ 0`）：`new_avg_cost` 不变；`realized_pnl = (price - old_avg_cost) * (-delta)`；
   - 首仓（old_shares 空/0）：`new_avg_cost = price`；
   - 边界：卖出超份额 → 400；price 缺失 → 400（**不用假价**）；
2. `update_etf` 扩展**语义参数** `adjust: {delta_shares, price} | null`——`adjust` 存在时走加权重算，否则维持「直接覆盖」（审计/导入场景）；REST `PUT /etfs/{symbol}` 接受 `{delta_shares, price}` 或 `{avg_cost, shares_held}` 两态（互斥校验）；
3. 端点响应携带 `realized_pnl`（卖出时）+ 新 `avg_cost/shares_held`——前端展示「已实现盈亏」提示。

**API 契约（PUT /etfs/{symbol}，实施前后端对齐）**：

```jsonc
// 请求（两态互斥，同传 400）
{ "delta_shares": 100, "price": 4.75 }          // 态1 买卖调整：正=增持 / 负=减持；price 缺省时后端取实时价（拿不到 400）
{ "avg_cost": 4.5, "shares_held": 1000 }        // 态2 直接覆盖（导入/纠错，不联动 target_weight）
// 响应 200
{
  "symbol": "510300", "name": "沪深300ETF",
  "avg_cost": 4.625, "shares_held": 1100,        // 态1 重算后 / 态2 覆盖后
  "target_weight": 0.052,                        // 仅态1：联动更新（新市值 ÷ 组合总市值，见下）
  "realized_pnl": 0,                             // 仅态1：卖出时为 (price-avg_cost)×(-delta)，买入恒 0
  "trade": { "delta_shares": 100, "price": 4.75, "side": "buy" }   // 仅态1：操作回显（前端提示用）
}
// 校验规则：delta_shares 与 avg_cost/shares_held 互斥（同传 400）；delta_shares=0 → 400；
// 卖出后 shares_held<0 → 400；price 缺省取实时价失败 → 400（不用假价）
```

**target_weight 联动口径**（用户已确认：联动）：`new_target_weight = new_market_value / Σ(active 持仓 shares×price)`（新市值 = 操作后 shares×price；分母含操作后全组合）；写回后按 `calculate_allocation` 现金口径收敛（`现金 = total_capital × (1 − Σtarget_weight)`，Σ 超限时按既有归一化逻辑压缩）。

**前端**：
4. 成本/份额编辑弹窗（`:795-827`）改为**两种模式**：
   - 「调整仓位（买卖）」：输入操作份额（正=增持/负=减持）+ 默认当前价（可改）→ 调 `adjust` 语义 → 展示重算后的 avg_cost 与 realized_pnl；**同时联动更新 `target_weight`**（用户已确认：按操作后新市值 ÷ 组合总市值推算，见 §十九 风险 4）——`PUT /etfs/{symbol}` 响应返回新 target_weight，前端一并刷新；
   - 「直接设置成本/份额」（导入/纠错）：原覆盖语义（保留，**不联动 target_weight**）；
5. 表格份额列 `@dblclick`（`:306`）进入「调整仓位」编辑（非直接改值），列表新增「已实现盈亏」列（可选）。

### 阶段 4（测试与验收）

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | 后端 pytest：`recompute_cost_after_trade` 三分支 | 买入加权（old=100@1.0 + 100@2.0 → avg=1.5）；卖出成本不变 + realized_pnl 正确；首仓 avg=price（**负向：卖出超份额不报错 → FAIL**） |
| T2 | 后端 pytest：`add_etf`/`update_etf` 落库 | 传 avg_cost/shares_held → `list_etfs` 返回一致值（**负向：当前行为丢弃 → FAIL**） |
| T3 | 后端 pytest：`adjust` 语义 | PUT `{delta_shares:-50, price}` → shares 减少、avg_cost 不变、realized_pnl 返回；**联动场景 PUT 返回新 target_weight（按新市值/总市值推算）** |
| T4 | 前端 vitest：`PortfolioManager` | 搜索选中 → avg_cost 自动填当前价；「调整仓位」弹窗增持后展示重算成本（mock API） |
| T5 | 手动走查 | 添加标的成本自动带当前价；增持/减持后列表成本与累计盈亏更新；刷新后数据保持（落库验证） |

**design-checklist 对照**：

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ 字段/链路均已存在（模型列 + calculate_cumulative_pnl） | ✅ §十七 全部 file:line | —（价格兜底失败需交易时段复测「成本未知」标注） | ✅ price 缺失 → 400/标注，不伪造 | ✅ adjust 挂 PUT /etfs、重算纯函数供 calculate_cumulative_pnl 复用 | ✅ 表单/弹窗四态沿用 | ✅ 纯函数重算 O(1)；实时价取价复用既有通道 | ✅ ① 乐观更新掩盖不落库（saveCostBasis:819） |

## 十九、已知问题与风险（问题 3）

1. **历史数据（已确认 2026-08-12：需要存量迁移）**：已存在持仓的 avg_cost/shares_held 多数为 NULL（此前不落库）——阶段 1 修复只对新写入生效；**实施「按当前价补录成本」批量迁移**：
   - 范围：`portfolio_etfs` 中 avg_cost 为 NULL 且 is_active 的持仓；
   - 口径（用户已确认）：用 `market_data_hub` 实时价/最近收盘价写 `avg_cost`（`_with_realtime_prices` 同通道；拿不到价则保持 NULL 并列出清单，**不伪造**）；
   - `shares_held` 保持 NULL（继续按目标权重估算份额）或按 `target_amount/avg_cost` 一并估算——实施时二选一（默认仅补 avg_cost，估算份额已有 `calculate_cumulative_pnl:1798+` 逻辑）；迁移为一次性脚本 + 迁移后对比累计盈亏口径变化（估算 → 实际成本）；
2. **估算份额与真实份额混用**：`calculate_cumulative_pnl` 对无份额持仓按目标权重估算（`:1798+`）——修复后新持仓有真实成本，估算分支仅剩存量数据；盈亏口径需在报告标注「估算」vs「实际」；
3. **前端乐观更新移除风险**：阶段 1 落库后 `saveCostBasis` 乐观更新与真实值一致，但若 `update_etf` 未来再改字段需同步——建议改为「await 后刷新」（问题 2 方案 A 移除快照层后自然达成）；
4. **买卖语义与权重分配的关系（已确认 2026-08-12：联动）**：仓位变更（shares）时**同步更新 `target_weight`**——「调整仓位（买卖）」模式下按操作后 `新市值 ÷ 组合总市值` 推算并写回 target_weight（更新权重合计后需按既有归一化/现金逻辑收敛，对照 `calculate_allocation` 的现金 = `total_capital × (1 − Σtarget_weight)` 口径）；「直接设置成本/份额」模式不联动（导入/纠错场景）。

---

# 第五部分：A股板块热度涨跌幅大量为 0

## 二十、结论摘要（问题 4）

1. **现象**：A股板块热度（`/sectors/heat` → SectorHeatMap）大量板块 `change_pct = 0`；**round16 P0-17① 已诊断并实现修复主路径，但主路径当前失败、静默回退到全面失效的旧链，「修了但没修好」**。
2. **实测根因链（2026-08-12，探针复现）**：
   - **主路径失败**：`get_sector_heat`（`market_data_hub.py:1464-1472`）优先走 `fetch_sector_heat_em` → `_ak_industry_sectors` → `ak.stock_board_industry_spot_em()` **8.5s 后抛 `RemoteDisconnected`**（akshare 内部硬编码 `push2.eastmoney.com`，被 EM 域名级风控断连）→ 返回空 → **静默回退财联社**；
   - **回退链 ① 财联社 sign 失效**：`fetch_cls_plate_changes`（`sector_fetcher.py:507+`）静态 sign `ef1ec7886be706a0b722d7e7bf3c0054` 实测 `errno=50101` → 0 条（plate_code 精确 join 20/20 链路不可用）；
   - **回退链 ② 东财名称回填命中率 5%**：`fetch_em_sector_changes` 只拉 **pn=1 单页**（`sector_fetcher.py:483` `pn=1&pz=500`，实测 **服务端 pz 上限 100，每 fs 只回 100 条**）→ 行业+概念各 100 条，覆盖不全；且财联社概念名（光通信/民爆/冰雪产业/国资云）与东财板块名体系不匹配，`_match_em_change`（`market.py:627-644`）三级匹配实测 **20 条热度仅命中 1 条**；
   - **结果**：`nonzero_ratio = 1/20 = 5%`，`degraded: true` 已标记（P0-17③，`market.py:615-624`）但**仅打 warning 日志，前端/用户不可见**——用户看到满屏 0 且无任何提示。
3. **已验证的修复路径**：push2delay 通道可用（项目 `_EM_HOST` 即 `push2delay.eastmoney.com`，`core/market_context.py`）——探针 `pn=1..3` 分页拉 **300 个行业板块、非零涨跌幅 300/300**（东财 BK 行业体系，f3 涨跌幅真实）。**绕过 akshare、直连 push2delay 分页拉全即可恢复真实涨跌幅**。

## 二十一、现状证据链

- `market_data_hub.py:1464-1472`：P0-17① 主路径 `fetch_sector_heat_em(limit)` → 空则回退 `fetch_sector_heat`（财联社）；
- `sector_fetcher.py:59-89` `_ak_industry_sectors`：`ak.stock_board_industry_spot_em()`，**`except Exception: return None` 无日志**（失败静默）；实测 8.5s `ConnectionError: RemoteDisconnected`（akshare `stock_board_industry_em.py:41` 拉 `push2.eastmoney.com` 被断连）；
- `sector_fetcher.py:425-460` `fetch_sector_heat_em`：`_ak_industry_sectors()` 返回空 → `return []`（无告警）；
- `sector_fetcher.py:507-540` `fetch_cls_plate_changes`：静态 sign 失效 `errno=50101` → `{}`（round14 P2-AE 已知，注释「回退东财/0 兜底」）；
- `sector_fetcher.py:463-498` `fetch_em_sector_changes`：`pn=1&pz=500`（实测每 fs 只回 100 条）、hosts 含 push2delay（此源可用，200 条）——但只覆盖 1/3 行业 + 概念 100 条；
- `market.py:588-614`：回填优先级 cls(plate_code) → em(名称) → `0` 兜底；`:611-613` 值域校验 ±10；
- `market.py:615-624`：P0-17③ 非零率 <50% → `degraded: true`（仅日志 + 端点标记，前端 SectorHeatMap 未消费）；
- `market.py:627-644` `_match_em_change`：精确/包含/斜杠首段三级匹配——实测 19/20 未命中（东财 300 细分行业体系 vs 财联社概念名，如「酿酒」→东财无「酿酒行业」命名、「民爆」→无）；
- **可用通道**：`core/market_context.py` `EM_PUSH_HOST = push2delay.eastmoney.com`（实测行业板块分页 300 条全真实涨跌幅）。

## 二十二、修复方案（只设计不实施）

### 阶段 1（P0，主路径恢复）：push2delay 直连行业板块替代 akshare

1. 新建 `fetch_em_industry_sectors(limit=None)`（`sector_fetcher.py`）：仿 `fetch_em_sector_changes` 的 push2delay 通道，`fs=m:90+t:2` + **分页循环 pn=1..N（每页 pz=200 实回 100，拉到 `<100` 为止，实测共 300 个行业板块）**，字段 `f12/f14/f3/f6/f62/f20`（代码/名称/涨跌幅/成交额/总市值/主力净流入）→ 输出与 `_ak_industry_sectors` **兼容**的 rows（`sector_code/sector_name/change_pct/amount/main_inflow/...`）；
2. `fetch_sector_heat_em` 改为：push2delay 直连优先 → akshare 兜底 → 空则回退财联社；**任一环节失败打 ERROR 日志**（不再静默）；
3. 领涨股（P0-18）：push2delay clist 无领涨股字段——**降级为空数组**（现财联社回退路径也是空）；如需补齐，按 `fs=b:BKxxxx` 成分接口取 f3 排序首只（成本高，列为可选）；
4. 输出排序：按成交额降序作为热度（沿用 `fetch_sector_heat_em:440` 现有语义）。
   - **口径确认（2026-08-12 用户接受）**：主路径切换后板块名从财联社概念名变为东财 BK 细分行业名（属预期展示口径变化，见 §二十三 风险 1）。

**输出字段映射表（`fetch_em_industry_sectors` 实施编码依据）**：

| push2delay clist 字段（f12/f14/f3/f6/f62/f20） | 输出键（与 `_ak_industry_sectors` 兼容） | 说明 |
|---|---|---|
| f12（板块代码，如 BK1592） | `sector_code` | 入库/回填用 |
| f14（板块名称） | `sector_name` | 展示名 |
| f3（涨跌幅%，-10~10 已过 `_sector_change_pct` 校验） | `change_pct` | ±10 值域校验（P2-3） |
| f6（成交额） | `amount` | 热度排序依据（按成交额降序） |
| f62（主力净流入） | `main_inflow` | 资金流（可空） |
| f20（总市值） | `total_market` | 可空 |
| —（clist 无领涨股） | `lead_stock_*` | 降级空（阶段 1 第 3 点） |

### 阶段 2（P1，回退链增强）：东财名称回填分页 + 归一化

1. `fetch_em_sector_changes` 补分页（pn=1..N 拉全行业 300 + 概念 400+），覆盖财联社名「证券/酿酒/军工」等原单页缺失板块；
2. `_match_em_change` 增加归一化：去「行业/概念/板块」后缀 + 静态别名表（`酿酒→酿酒行业、证券→证券Ⅱ、军工→国防军工` 等，按实测 MISS 清单补）；
3. 财联社 sign 动态化（根治，工作量大列为 P2）：从 cls.cn 页面/接口提取动态 sign 或换免 sign 接口——恢复 plate_code 精确 join（20/20 命中）。

### 阶段 3（P1，诚实性）：0 兜底改 null + degraded 前端可见

1. `market.py:611-613`：回填全失败时 `change_pct` 从 `0` 改 `None`——前端 SectorHeatMap 显示「—」并整行 tooltip「涨跌幅数据源异常」；**涨跌幅未知不再冒充 0%**（对照反假完成）；
2. `degraded: true` 前端消费：SectorHeatMap 顶部提示条「部分板块涨跌幅数据源异常（实时回填失败）」——用户不再困惑「为什么全是 0」；
3. 契约：`api-contracts/market/sectors-heat.md`（若有）同步 change_pct 可空语义。

### 阶段 4（P2，监控）：失败可见性

1. `_ak_industry_sectors` / `fetch_sector_heat_em` 失败打 ERROR 日志（当前 `except: return None` 静默）；
2. 非零率按日统计记录（`source_health.py` 或日志），跌破阈值告警——**防止再出现「修了没修好」无人发现**（round16 P0-17③ 只打了一次 warning，无趋势跟踪）。

### 阶段 5（测试与验收）

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | 探针级单测（mock urllib）：`fetch_em_industry_sectors` 分页循环 | pn 递增到 `<100` 为止；返回 ≥80 条、字段与 `_ak_industry_sectors` 兼容 |
| T2 | 后端 pytest：`get_sector_heat(20)` 优先路径 | 返回 EM spot 格式（change_pct 真实非零）；`fetch_em_industry_sectors` 抛错时回退链触发且打 ERROR 日志（**负向：静默吞异常 → FAIL**） |
| T3 | 端点实测（交易时段）：`/sectors/heat` | 非零率 ≥90%（**负向：现状 1/20 = 5% → FAIL**）；`degraded: false` |
| T4 | 前端 vitest：SectorHeatMap | change_pct=null 显示「—」+ 提示条；degraded=true 显示提示（负向：null 显示 0% → FAIL） |
| T5 | 手动走查 | 板块热度页涨跌幅真实非零；数据源异常时提示可见 |

**design-checklist 对照**：

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ push2delay 分页 300/300 非零实测可行 | ✅ §二十一 全部 file:line + 实测命令 | ✅ 端点实测标「交易时段」；结构/字段验证无窗口限制 | ✅ 回填失败 → null + 提示条，禁止 0 冒充 | ✅ fetch_sector_heat_em 已被 get_sector_heat 调用（:1468） | ✅ 前端四态含数据源异常提示条 | ✅ 分页循环 3 次请求、60s TTL 缓存；领涨股降级可控 | ✅ ① 0 兜底冒充（market.py:613）+ 静默吞异常（sector_fetcher.py:88） |

## 二十三、已知问题与风险（问题 4）

1. **东财行业体系变化（已确认 2026-08-12：用户接受）**：push2delay 返回的是东财 BK 细分行业（300 个，如「通信线缆及配套」），与财联社热度概念名体系不同——阶段 1 主路径用 EM spot 的板块列表**替代**财联社热度排行（热度=按成交额排序），板块名与用户熟悉的财联社概念名（光通信/民爆）不同，属**展示口径变化**——**用户已确认接受**；主路径按方案落地（不再保留财联社双轨），但阶段 2 回退链的名称归一化/别名表仍实施（财联社回退时兜底）；
2. **push2delay 可用性依赖**：当前容器内可用（历史已验 1843 行），但为第三方接口——阶段 4 的失败可见性 + 分页重试是必要护栏；
3. **akshare 版本升级**：若 akshare 未来改走 push2delay 或接口变更，阶段 1 的 push2delay 直连可继续兜底（双保险）；
4. **存量 0 数据**：修复前已展示的 0 是「数据缺失冒充」，修复后新数据真实——历史截图/缓存不追溯。

---

# 第六部分：导航栏一直展示「离线」状态

## 二十四、结论摘要（问题：页面上一直展示离线状态）

1. **现象**：导航栏连接状态徽标（「已连接/连接中/离线」，`App.vue`）在非首页页面**一直显示「离线」**，用户质疑是否合理。
2. **实测结论**：**后端 WS 正常**（探针 `ws://localhost:8000/api/v1/ws/portfolio` 握手成功、收到 `{"type":"hello"}`）、Vite WS 代理配置正确（`vite.config.js:51-52`）——**不是连接故障，是前端连接生命周期与展示位置错位**。
3. **根因**：
   - `connectWS` 仅在 **Dashboard（`/` 首页）`onMounted` 调用**（`Dashboard.vue:202`）、`disconnectWS` 在 `onUnmounted`（`:216`，`stopped=true` 且不再重连）——**离开首页即断连**；
   - 展示位置在 **App.vue 全局导航栏**（常驻所有页面）——「连接者（Dashboard）」与「展示者（App）」生命周期不同步：非首页页面连接已断，导航栏却照常显示状态徽标；
   - **初始态也是「离线」**：`wsConnected` 初始 `false`（`market.js:16`），页面加载后未完成握手（或用户直接进非首页路由）即显示「离线」；
   - **语义误导**：`disconnected` →「离线」（`App.vue:164`）混同了「主动断开（按需连接，设计如此）」「重连中」「连接失败」三种状态——用户误以为系统/网络故障。
4. **是否合理**：**按需连接（仅首页连行情 WS）合理，但全局展示该状态不合理**——应①生命周期提升为全局（或②展示与路由解耦），③状态语义区分「未连接（按需）/重连中/异常」。

## 二十五、现状证据链

- `App.vue:155-164`：`connectionStatus = marketStore.wsConnected ? 'connected' : 'disconnected'`（round11 P2-3 已接真实状态）；`:33-34` 导航栏常驻渲染状态圆点+文字；
- `Dashboard.vue:202`：`marketStore.connectWS((data) => {…全局指数更新…})`（onMounted）；`:216` `marketStore.disconnectWS()`（onUnmounted）——**连接生命周期绑定首页**；
- `market.js:31-37` `connectWS`：`stopped=false` + `doConnect`；`:39-47` 创建 `/ws/portfolio`；`:49-57` `onopen → wsConnected=true`；`:94-98` `onclose → wsConnected=false` + `scheduleReconnect`；`:106-114` 指数退避重连（上限 8s）；`:116-128` `disconnectWS → stopped=true`（**重连停止**）；
- `router/index.js:5-13`：`/` = Dashboard；`/portfolio-analysis`、`/market-analysis`、`/news` 等非首页路由——进入即 Dashboard 卸载 → 断连 → 导航栏「离线」；
- 后端 WS 可用：`ws.py:115-124` portfolio_ws（hello）；探针握手实测成功。

## 二十六、修复方案（只设计不实施）

### 阶段 1（P0）：连接生命周期与展示解耦——**方案 A 已确认（2026-08-12 用户选定）**

- **方案 A ✅（已选定，全站常驻行情连接）**：`App.vue` 挂载时 `marketStore.connectWS()`、卸载时 `disconnectWS()`——WS 轻量（单连接 + 30s heartbeat），全站共享行情实时更新；Dashboard 的全局指数更新回调迁移至 App.vue 或 store 内建（`market.js` 的 `onMessageCallback` 保留，App.vue 传入）。
  - **实施步骤（落地路径）**：
    1. `App.vue`：`onMounted` 加 `marketStore.connectWS()`（含全局指数更新回调，从 `Dashboard.vue:202-211` 迁移）；`onUnmounted` 加 `marketStore.disconnectWS()`；
    2. `Dashboard.vue`：删除 `:202-211` 的 `connectWS` 调用与 `:216` 的 `disconnectWS`（连接职责移交 App）；Dashboard 的指数更新逻辑若依赖回调，改由 App.vue 传入（或移入 `market.js` store 内建 `realtimeData` 消费）；
    3. `market.js`：`connectWS` 保持幂等（重复调用不建多连接——`stopped=false` + 已存在连接时跳过）；`disconnectWS` 仅 App 卸载时调用；
    4. 回归：`marketStore.p1-1.spec.js` 与 Dashboard/App 相关 spec 同步调用点变更。
  - 效果：导航栏状态真实反映 WS 健康，且任何页面一致；顺带让非首页页面也能收到 realtime 行情推送（WatchlistPanel 等受益）；
  - **⚠️ 与问题 2 方案 B 合并**：本阶段（连接全站常驻）是问题 2 方案 B（`portfolio_changed` 广播消费）的**前提**——合并设计见问题 2 §九 方案 B「⚠️ 合并设计」段落（一次改造满足两个问题，先本阶段后广播分流）；
- **方案 B（未选，备选）**：导航栏状态徽标**仅 Dashboard 路由显示**（`useRoute().name === 'dashboard'`），非首页路由隐藏徽标（或显示中性文案「行情连接按需」）——改动最小，但「连接中/异常」在其它页面仍不可见。

### 阶段 2（P1）：状态语义细分（两种方案都适用）

1. `market.js` 状态机扩展：`stopped`（主动断开）与 `reconnecting`（onclose 后重连中）分离——新增 `wsStatus: 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'stopped'`；
2. `App.vue` 文案对齐：`idle/stopped` → 「行情连接未启用（按需）」或隐藏；`reconnecting` → 「连接中...」；连续重连失败 N 次（如 5 次）→ 「行情通道异常」+ tooltip 显示最近错误（区别于「离线」的故障暗示）；
3. 初始态不再显示「离线」：页面加载未连接时显示中性态（如灰点无文字），避免「一进来就离线」的误读。

### 阶段 3（P2，可观测）

- 导航栏状态 tooltip：最近一次连接事件（时间 + 原因：主动断开/失败/重连）——`market.js` 记录 `lastEvent = {at, reason}`；
- `source_health.py` 增加 WS 连接数/健康（后端 `ws.py` 暴露 active_connections 计数，可选）。

### 阶段 4（测试与验收）

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | 前端 vitest：`market.js` 状态机 | connectWS→connecting；onopen→connected；disconnectWS→stopped（**负向：disconnectWS 后仍显示 connected → FAIL**） |
| T2 | 前端 vitest：`App.vue` 导航栏 | 非 Dashboard 路由 + wsStatus=stopped → 不显示「离线」文案（中性态/隐藏）；**负向：stopped 时仍渲染「离线」→ FAIL** |
| T3 | 手动走查 | 首页 WS 握手后显示「已连接」；切到持仓/分析/资讯页**仍显示「已连接」**（方案 A 全站常驻）；后端停掉后显示「连接中/异常」而非「离线」 |
| T4 | 既有 spec 回归 | `marketStore.p1-1.spec.js`（connectWS 用例）同步状态机字段 |

**design-checklist 对照**：

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ WS 握手实测成功（后端正常，问题在展示层） | ✅ §二十五 全部 file:line + 实测命令 | —（无外部行情源新增） | ✅ 状态区分真实连接/重连/主动断开，无假「已连接」 | ✅ connectWS 调用点唯一（Dashboard.vue:202）→ 方案 A 迁移 App.vue | ✅ idle/connecting/connected/reconnecting/stopped 五态文案 | ✅ WS 单连接常驻开销极小（30s heartbeat） | ✅ ① 生命周期错位（连接者/展示者不同步）+ 语义混淆 |

## 二十七、已知问题与风险

1. **方案 A 的资源开销（已确认 2026-08-12：暂不考虑多用户）**：WS 全站常驻 = 后端连接数随在线用户线性增长——**当前单用户本地/小规模场景，WS 承载限制不实施**；多用户部署时再评估 `ws.py` ConnectionManager 上限（文档保留此风险项供未来参考）；
2. **方案 A 的行为变化**：非首页页面将收到 realtime 推送（现 WatchlistPanel 等靠 REST 轮询）——需确认无重复刷新/竞态（问题 2 的 WS 消费改造与本方案同源，可一并设计）；
3. ~~方案 B 的信息损失~~（未选，仅备选）：非首页页面看不到行情通道异常——方案 A 已选定，此风险不适用；

---

# 第七部分：自选列表（江波龙）技术分析空数据 + 转AI分析无反应

## 二十八、结论摘要（问题：自选里江波龙技术分析数据空、转AI按钮没反应）

1. **现象**：自选列表（WatchlistPanel）点江波龙「技术分析」→ TechnicalAnalysisModal 弹窗**数据为空**；弹窗内「🤖 转 AI 分析」按钮**点击无反应**。
2. **实测根因（两个独立断点）**：
   - **数据空**：watchlist 里江波龙存的 symbol 是 **`sz301308`（带交易所前缀）**（`data/portfolio.db` watchlist id=19，其余 18 条均不带前缀）——而 `fetch_history` 主路径（`china_market.py:1488-1545`）**入口不归一化前缀**，直接透传 `sz301308` 给 `_mootdx_history` / `_sina_history_cb`（二者不认前缀）→ **0 行**；实测对照：`fetch_history('301308')` = 800 根、`fetch_history('sz301308')` = 0 根 → `indicators` 返回 `data_available=False`（`market.py:344-347`）→ 弹窗空数据；
   - **AI 按钮无反应**：`MarketAnalysis.vue:45` 的 `<WatchlistPanel @select-symbol="onSelectSymbol" />` **漏绑 `@analyze`**——`WatchlistPanel.vue:164` 收到弹窗 `@ai` 后 `emit('analyze', ...)`，但上层无人消费（对照 `SectorHeatMap` 在 `MarketAnalysis.vue:48` 有 `@analyze="onQuickAnalyze"`）→ 弹窗关闭但无任何 AI 分析动作。
3. **附带发现（排除项）**：搜索接口正常（`keyword` 参数，实测 `search?keyword=江波龙` 返回 `symbol='301308'` 不带前缀、`asset_type='stock'`）——`sz301308` 前缀**非搜索接口产生**，来自其它录入路径（手动输入/热点入口），属存库规范缺口。

## 二十九、现状证据链

- `data/portfolio.db` watchlist：`(19, 'sz301308', '江波龙', 'A', ...)`——唯一带前缀记录（19 条中）；
- `china_market.py:1488-1545` `fetch_history`：`asset_type="A"` 分支直接透传 symbol（`:1524` `_mootdx_history(symbol)`、`:1527` `_sina_history_cb(symbol)`）——**入口无前缀归一化**；对照 `:237/:286/:1458` 内部函数有 `symbol[2:] if startswith(("sh","sz","bj"))` 剥前缀逻辑，但主入口未应用；
- 实测：`fetch_history('sz301308')`=0（mootdx 空 1.6s）、`fetch_history('301308')`=800（0.1s）；`hub.get_market_history` 同口径；
- `market.py:341-354` indicators 端点：`len(hist) < 30` → `{"data_available": False, "reason": "K线数据不足..."}` → 前端弹窗空态；
- `WatchlistPanel.vue:164` `@ai="(p) => { techModal = null; emit('analyze', ...) }"`（弹窗→自选面板链路通）；`WatchlistPanel.vue:176` `defineEmits(['select-symbol', 'analyze'])`；
- `MarketAnalysis.vue:45` `<WatchlistPanel ... @select-symbol="onSelectSymbol" />`——**无 @analyze**；`:48` `<SectorHeatMap ... @analyze="onQuickAnalyze" />`（对照存在）；
- `MarketAnalysis.vue:71` `onQuickAnalyze({mode, query, name})`——已有 AI 分析入口实现（滚动到分析区 + UnifiedAnalysis），仅缺 WatchlistPanel 绑定。

## 三十、修复方案（只设计不实施）

### 阶段 1（P0，数据空治本）：`fetch_history` 入口统一归一化

- `fetch_history`（`china_market.py:1488`）入口首行加前缀剥离：`code = symbol[2:] if str(symbol).lower().startswith(("sh", "sz", "bj")) else symbol`（复用 :237 既有逻辑），后续所有分支用归一化 code——**任何带前缀 symbol 全链路可用**（watchlist/自选/搜索/深链均受益）；
- 负向断言：`fetch_history('sz301308')` 返回与 `fetch_history('301308')` 一致（≥30 行）——**当前 0 行 → FAIL**。

### 阶段 2（P0，AI 按钮）：补绑 `@analyze`

- `MarketAnalysis.vue:45` 补 `@analyze="onQuickAnalyze"`（与 `:48` SectorHeatMap 一致，一行级修复）；
- 负向断言：`WatchlistPanel` 弹窗 `emit('analyze')` 后触发 `onQuickAnalyze`（mock 冒烟）——当前无人消费 → FAIL。

### 阶段 3（P1，存库规范 + 存量清洗）

1. watchlist 添加路径统一 symbol 归一化（去 sh/sz/bj 前缀）——后端 `add_watchlist` 入库前 strip 前缀 + 前端 `selectSearch` 用搜索返回的规范化 symbol；
2. 存量清洗：`sz301308 → 301308`（启动迁移或一次性脚本，`UPDATE watchlist SET symbol='301308' WHERE symbol='sz301308'`）；
3. 顺带排查 `portfolio_etfs` / 其它表的 symbol 前缀规范一致性（当前 ETF 均不带前缀）。

### 阶段 4（P1，弹窗空态明确化）

- `TechnicalAnalysisModal` 对 `data_available=false` 显示明确空态：「该标的无 K 线数据（数据源缺失或代码不规范）」+ 重试按钮（现状 error 态仅「指标加载失败」）；
- 「转 AI 分析」按钮在无 K 线时**仍可用**（AI 分析走 `analysis` 端点、不依赖弹窗 K 线数据），确保「空数据不阻塞 AI 分析」。

### 阶段 5（测试与验收）

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | 后端 pytest：`fetch_history` 前缀归一化 | `fetch_history('sz301308')` ≥30 行且与 `'301308'` 对齐（**负向：现状 0 行 → FAIL**） |
| T2 | 后端 pytest：watchlist 入库归一化 | `add_watchlist('sz301308')` 落库为 `'301308'`（**负向：原样入库 → FAIL**） |
| T3 | 前端 vitest：`MarketAnalysis` 绑定 | `WatchlistPanel` `@analyze` 存在且触发 `onQuickAnalyze`（**负向：无绑定 → FAIL**） |
| T4 | 手动走查 | 江波龙技术分析弹窗出 K 线/指标；点「转 AI 分析」跳到 AI 分析区并出结果；存量 `sz301308` 清洗后全链路正常 |

**design-checklist 对照**：

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ 实测 301308 vs sz301308（800 vs 0 行）| ✅ §二十九 全部 file:line + 实测命令 | —（无新增行情源；K 线验证任意时段） | ✅ data_available=false 显示明确空态，AI 按钮不依赖 K 线 | ✅ fetch_history 入口归一化（所有调用方受益）+ @analyze 绑定补上 | ✅ 弹窗空态/错误态明确化 | ✅ 归一化 O(1)；清洗一次性脚本 | ✅ ① 带前缀 symbol 静默空数据（fetch_history:1488）+ 事件漏绑 |

## 三十一、已知问题与风险

1. **前缀来源已定位（2026-08-12 排查完成）**：`add_watchlist`（`market_service.py:1630-1654`）**原样入库不归一化**；前端 `WatchlistPanel.addItem`（`:318`）对原始输入 `split(/\s+/)[0]` 后原样提交——**用户手动输入带前缀代码（如 `sz301308`）即产生前缀记录**；搜索建议路径（`selectSuggestion` :298 用 `marketApi.search` 返回的 symbol，实测不带前缀）不会产生——修复 = 阶段 3 的入库归一化（后端 strip 前缀）+ 可选前端 `addItem` 提交前归一化（双保险）；
2. **归一化副作用**：`fetch_history` 入口剥前缀对所有调用方生效——需回归 HK（5 位数字）与 ETF（6 位数字）不受影响（剥前缀仅命中 sh/sz/bj 开头，HK/US 分支在 `:1536` 之后不受影响）；
3. **watchlist 与 portfolio 双表规范**：当前 `portfolio_etfs` 均不带前缀——统一为「存库不带前缀」后，前端展示/跳转需确认不依赖原始输入（`watchlist` 与 `portfolio_etfs` 交叉引用场景）。

---

# 第八部分：港股指数自动补全不全

## 三十二、结论摘要（问题：港股指数的自动补全有明显改善，但还是不全）

1. **现象**：搜索框港股指数联想（`/search?kind=index&market=HK` → `indices_meta` 表）——round16 P0-20/P0-22 静态段补齐后「恒生」搜索已能命中 13 条（明显改善），但**恒生行业/主题指数仍缺失**：实测「红筹」「恒生医疗」「恒生互联网」「恒生高股息」「恒生消费」「恒生金融」均 **0 命中**。
2. **根因**：`indices_meta` 表 HK 指数仅 25 条，来源为 ① 新浪港股指数源 `ak.stock_hk_index_spot_sina()`（`sync_indices_meta.py:67-90`，新浪港股指数列表本身仅 ~38 条、无行业/主题细分）② 静态兜底段 `_STATIC_EXTRA_INDICES`（`sync_indices_meta.py:145-159`，仅恒生港股通系列 6 条 + HSI/HSCEI/HSTECH/HSCCI）——**恒生行业分类/综合行业/主题指数（金融/地产/医疗保健/互联网/高股息等）两个源都不覆盖**。
3. **修复方向**：静态兜底段扩展（确定性最高，机制已验证）+ 可选数据源增强（东财港股指数列表）。

## 三十三、现状证据链

- `market.py:227-230` `_search_indices`：`indices_meta` 表 name/pinyin/first_letter ilike；`:96` kind=index 分支（market 透传）；
- `data/portfolio.db` indices_meta：HK 25 条（HSI/HSTECH/HSCEI/HSCCI/GEM/HKL + 中证香港系列 + 恒生港股通 H11141-46）；
- 实测搜索（kind=index, market=HK）：「恒生」13 条、「恒生科技」1 条、「恒生指数」1 条；**「红筹/恒生医疗/恒生互联网/恒生高股息/恒生消费/恒生金融」0 条**；
- `sync_indices_meta.py:67-90` `_fetch_sina_hk_indices`：`ak.stock_hk_index_spot_sina()`（新浪源 ~38 条，无行业/主题指数）；
- `sync_indices_meta.py:145-159` 静态段：恒生港股通系列（H11141-46）+ HSI/HSCEI/HSTECH/HSCCI（+HSMPI/HSMOGI/HSMBI 在中证系列段）——无恒生行业分类/综合行业/主题指数；
- `sync_indices_meta.py:195-204`：静态段必然入表（不依赖外部源状态）——**扩展静态段即可保证补全**；
- 附带探测：东财 push2delay `fs=m:128`/`m:128+t:3` 返回港股个股/牛熊证（**非指数**，fs 代码不正确，不作为数据源路径）；新浪源为当前唯一可用 HK 指数列表。

## 三十四、修复方案（只设计不实施）

### 阶段 1（P0，静态段扩展——确定性补全）

`_STATIC_EXTRA_INDICES`（`sync_indices_meta.py:145-169`）HK 段追加常见恒生指数（**symbol 实施时以恒生官网/东财代码核对**，以下为建议清单）：

| symbol（待核对） | 名称 | 类别 |
|---|---|---|
| HSCI | 恒生综合指数 | broad |
| HSF | 恒生金融分类指数 | industry |
| HSP | 恒生地产分类指数 | industry |
| HSU | 恒生公用事业分类指数 | industry |
| HSC | 恒生工商业分类指数 | industry |
| HSCIE/HSCIM/HSCII/HSCICD/HSCICS/HSCIH/HSCIF/HSCIPC/HSCIT/HSCIC | 恒生综合行业 10 项（能源/原材料/工业/非必需消费/必需消费/医疗保健/金融/地产建筑/资讯科技/综合企业） | industry |
| HSAHC | 恒生医疗保健指数 | theme |
| HSII | 恒生互联网科技业指数 | theme |
| HSHYLDI | 恒生高股息率指数 | theme |
| HSHKBIO | 恒生香港上市生物科技指数 | theme |

- 说明：静态段机制已验证（round16 P0-20/22 效果 = 用户认可「有明显改善」），本次只是把行业/主题档补齐；`source: "static"`、category 区分 broad/industry/theme；
- 同步触发：`indices_meta` 全量替换式同步（`sync_indices_meta.py:226-227`）——后端启动/手动 `sync_indices_meta_table` 后生效，无需迁移。

### 阶段 2（P1，数据源增强——可选，全量拉取）

- 若需覆盖恒生全家族（含更多主题指数），接入**东财港股指数列表**（正确 fs 代码实施时探测，如 `b:BK1077` 港股指数板块或 `secids=100.xxx` 列表接口）或恒生官网指数列表——一次性全量入库，替代静态段手写清单；
- 前置探针（D1）：实施前先探测东财/恒生源可达性与字段，失败则维持阶段 1 静态扩展。

### 阶段 3（P1，行情联动确认——**2026-08-12 排查完成，确认系统性缺口**）

- **实测：现有链路 HK 指数 K 线全空**——`get_market_history('HSCI'/'HSTECH'/'HSI', 'index')` 均 0 行：`fetch_index_history`（`china_market.py:1452-1477`）**仅支持 A 股指数**（`ak.stock_zh_index_daily(sh{code})` + BaoStock），HK 指数无分支——**连已在表的 HSI/HSTECH 点击后都拿不到 K 线**（「搜索出结果、点击无数据」是真实缺口，不止新增指数）；
- **修复源已探明**：腾讯港股指数 K 线 `hk{symbol}`（复用 `_fetch_tencent_hk_history` 模式，`web.ifzq.gtimg.cn`）——实测 `hkHSI`/`hkHSTECH`/`hkHSCI`/`hkHSF` = **320 根**；`hkHSAHC`（恒生医疗保健）= 0 根（**主题指数腾讯不覆盖**，需标注「暂无行情」或另寻源）；
- 阶段 3 落地：`fetch_index_history` 增加 HK 分支（`hk{code}` 腾讯 fqkline）——**与问题 8 静态段扩展一并实施**（补全与行情同时打通，避免半成品）；

### 阶段 4（测试与验收）

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | 同步后库断言 | `indices_meta` HK 行数 ≥ 40 且含 HSCI/HSF/恒生医疗保健/恒生互联网（**负向：现 25 条缺行业指数 → FAIL**） |
| T2 | 搜索命中断言 | `search?keyword=恒生医疗&kind=index&market=HK` ≥1 条（**负向：现状 0 条 → FAIL**）；`恒生` ≥ 20 条 |
| T3 | 手动走查 | 搜索框输入「恒生」联想完整；输入「医疗/互联网/高股息/红筹」有对应港股指数 |
| T4 | 行情联动（可选） | 点击新增指数 → 行情/K 线可用（或明确「暂无行情」而非空白） |

**design-checklist 对照**：

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ 实测缺失清单（0 命中 6 项）+ 静态段机制可用 | ✅ §三十三 全部 file:line + 实测命令 | —（元数据层，无行情窗口限制） | ✅ 静态段必然入表（不依赖源状态） | ✅ _search_indices 消费 indices_meta（market.py:227） | —（搜索四态已具） | ✅ 静态段 O(1)；全量同步一次 | ✅ ① 补全=元数据层，行情层需独立验证防半成品 |

## 三十五、已知问题与风险

1. **symbol 准确性（2026-08-12 部分验证）**：静态清单的恒生指数代码——**腾讯 `hk{sym}` K 线可反向验证**：`hkHSCI`/`hkHSF` 实测 320 根（**代码真实存在**），`hkHSAHC`（恒生医疗保健）0 根（腾讯不覆盖，需恒生官网/东财另核代码与行情源）；实施时逐条以「腾讯/东财 K 线可拉」为准验证，拉不到的标注「暂无行情」而非入表后断裂；
2. **补全与行情分层**：indices_meta 只解决搜索补全；行情/K 线覆盖是独立链路——若新增指数行情源未接入，UI 需显示「暂无行情」而非空白（阶段 3）；
3. **新浪源覆盖边界**：`stock_hk_index_spot_sina` ~38 条为新浪接口上限，行业/主题指数新浪本就不提供——静态段扩展不依赖该源，但 source 字段需保持「static」标注以区分（来源诚实性）。

---

# 第九部分：美股自选技术分析显示数据不足

## 三十六、结论摘要（问题：美股自选列表点技术分析显示数据不足）

1. **现象**：美股自选（SPY/AAPL/QQQ，asset_type=US）点技术分析 → TechnicalAnalysisModal 显示「数据不足」（`data_available=False`）。
2. **实测根因（SPY 复现，AAPL/QQQ 仅缓存未过期）**：
   - **US K 线主源全挂**：akshare `stock_us_hist`（`china_market.py:1596-1600`）走东财历史接口 → 实测 **`ConnectionError: RemoteDisconnected`（EM 域名级风控断连，与问题 4 push2 同源）**——`SPY`/`105.SPY`/`AAPL`/`105.AAPL` 全部失败；
   - **降级链失效**：finnhub（`.env` 已配 key，实测失败/限流）→ alphavantage（key 已配，免费额度易耗尽）→ **yfinance 被墙**（`fetch_history_yfinance` 存在但零调用且本环境不可达，`global_markets_fetcher.py:324-339`）→ US 无腾讯兜底（`:1536-1544` 仅 HK 有）→ 返回空；
   - **缓存过期即空**：`market_service.get_history`（`:1398-1458`）只认 Hub 300s 内缓存（`get_kline_rows` max_age=300，`:1404`）——**缓存过期后主链失败 → 直接返回空，不接任意年龄旧缓存**（`get_kline_rows_any` 存在 `market_data_hub.py:1209-1211` 但未接入）→ indicators `data_available=False`（`market.py:344-347`）→ 弹窗「数据不足」；
   - **AAPL/QQQ 正常是缓存假象**：其 300s 缓存未过期（此前成功拉过）；SPY 缓存过期/冷态 → 暴露全链失败。
3. **已验证的替代源**：
   - **TickFlow（用户已注册 key，2026-08-12 实测）——`AAPL.US`/`SPY.US` 各 500 根（2.9s/1.6s，含 2026-08-12 当天收盘 771.905）**——商业 API 免费层、无 EM 反爬、国内可达，且代码形态 `{code}.US` 与既有 `_tickflow_symbol`（`china_market.py:321-322`，实时行情已支持 A/HK/US）完全对齐——**升级为 US 主修复**（`_tickflow_kline` 加 US/HK 分支）；
   - akshare `stock_us_daily`（新浪源）——SPY 6438 行/AAPL 10008 行全量（T+1），作**全量兜底**；
   - 腾讯美股 K 线（`web.ifzq.gtimg.cn`）：`usAAPL.OQ`/`usQQQ.OQ`（NASDAQ 系）321 根，`usSPY*` 全变体 ≤1 根（NYSE Arca 不覆盖）——备选；stooq/yfinance 不可用。

## 三十七、现状证据链

- `market.py:341-354` indicators 端点：`get_market_history` 空/不足 30 → `data_available=False`；
- `market_service.py:1398-1458` `get_history`：Hub 缓存（300s）→ fetch_history（HK/US 20s）→ get_k_data（akshare 直查，US 同源也挂）→ HK 腾讯独立兜底（**US 无**）→ 空；**无任意年龄缓存兜底**；
- `china_market.py:1591-1637` `_fetch_akshare_history`：akshare `stock_us_hist`（实测 RemoteDisconnected）→ finnhub（`:1611`）→ alphavantage（`:1617`）→ HK 腾讯（`:1628`，**US 无**）→ `[]`；
- `global_markets_fetcher.py:324-339` `fetch_history_yfinance`：**零调用**（`rg` 仅定义处）；本环境 `fetch_history_yfinance("SPY","1y")` 实测 0 行 4.3s（yahoo 被墙，`YFINANCE_PROXY` 未配）；
- `market_data_hub.py:1201-1211`：`get_kline_rows`（max_age=300）与 `get_kline_rows_any`（任意年龄）并存——后者未被 `get_history` 使用；
- `market_data_hub.py:1207-1226`：F0-4 `mark_kline_stale`/`is_kline_stale` 标记机制已存在（stale 标注可透传到 `_stale` 字段，`market.py:349-353`）——**只差数据兜底接入**；
- 腾讯美股探针：`usAAPL.OQ`/`usQQQ.OQ` = 321 根（1.1s）；`usSPY`/`.OQ`/`.N`/`.A`/`.P`/`.US` = 0~1 根——**腾讯不覆盖 NYSE Arca 系（SPY）**；
- **新浪源探针（2026-08-12 收盘后）**：`ak.stock_us_daily('SPY')` = **6438 行**（4.7s）、`('AAPL')` = **10008 行**（1.8s）、`('105.SPY')` 抛 IndexError（需纯代码）——新浪美股日 K 国内可达、全量覆盖（SPY 自 2001 年）；列名为英文（date/open/high/low/close/volume）需映射；
- **TickFlow 探针（2026-08-12）**：`client.klines.get('AAPL.US'/'SPY.US', period='1d', count=500)` = **各 500 行**（2.9s/1.6s，含 2026-08-12 当天收盘 302.065/771.905）——`_tickflow_kline`（:274-313）当前仅 A 股分支（:287 SH/SZ 硬编码），但 `_tickflow_symbol`（:321-322）已定义 US/HK 代码形态（AAPL.US/00700.HK），**扩展成本低、与实时行情同构**；
- `.env`：`FINNHUB_API_KEY`/`ALPHAVANTAGE_API_KEY` 已配置但实测降级仍失败（限流/额度），不能作为可靠兜底。

## 三十八、修复方案（只设计不实施）

### 阶段 1（P0，立竿见影）：stale 缓存兜底

- `market_service.get_history`（`:1414-1445`）主链（fetch_history + get_k_data）失败后，追加 `market_data_hub.get_kline_rows_any(symbol)`：命中 → 返回旧数据 + `mark_kline_stale(symbol, True)`（F0-4 机制接入）——indicators 端点经 `is_kline_stale` 透传 `_stale` 标记（`market.py:358-361` 已有）；
- **效果**：SPY 缓存中已有 100 根（实测 `chart/SPY` closes=100）→ 缓存过期后不再「数据不足」，显示「过期数据（数据源暂不可用）」；
- 负向断言：缓存过期 + 全链失败 → 仍返回空（不接 stale）→ FAIL。

### 阶段 2（P0，源链补强——**TickFlow US 分支扩展为主修复，新浪全量兜底**）

- **TickFlow（主修复，2026-08-12 实测）**：`_tickflow_kline`（`china_market.py:274-313`）当前**只支持 A 股**（:287 硬编码 `{code}.SH/SZ`）——扩展 US/HK 分支：`{code}.US`/`{code}.HK`（复用 `_tickflow_symbol` :321-322 的映射逻辑）；实测 `AAPL.US`/`SPY.US` 各 500 根、含当日收盘（2.9s/1.6s，2026-08-12）——数据新鲜度优于新浪 T+1；
- **降级链重排（US）**：akshare `stock_us_hist`（EM 风控，3s 快速失败）→ **TickFlow（主）** → alphavantage（可用但 25 次/天限额）→ `ak.stock_us_daily`（新浪，全量兜底、无限额）→ finnhub（恒败，设 3s 短超时或跳过）；
- **SPY（NYSE 系）问题就此解决**（TickFlow `SPY.US` 500 根实证——腾讯不覆盖不再是阻塞）;
- 实现注意：TickFlow 返回 `trade_date`（str）/open/high/low/close/volume/amount 列（`_tickflow_kline` 已有解析 :298-308）；`count=500` 足够技术分析（>30 根判定线）；key 缺失时返回 [] 走下一级（现有行为）；
- 负向断言：`_tickflow_kline('SPY','US')` ≥30 行；key 缺失/tickflow 失败时降级链继续不抛错。

### 阶段 3（P1，key/限流审计 + 重试——**2026-08-12 审计完成**）

1. **finnhub 恒失败（实测 0 行）**：`fetch_candles(SPY, D)` 2.0s 返回空（免费额度/无该 ticker）——**不修复，降为最后兜底并跳过或设 3s 短超时**（避免 8s 空转）；
2. **alphavantage 当前可用但限额**：`fetch_daily_alphavantage('SPY')` 实测 **100 行成功**（2026-08-12，2026-08-11 收盘 770.56 与新浪一致）——免费 key 25 次/天易耗尽，**冷态失败根因 = akshare 8s 必超时（EM 风控）占预算 + finnhub 恒败 + alphavantage 限额窗口**；修复 = 降级链重排：akshare 失败**快速返回**（EM 风控已知，超时从 8s 降到 3s）+ alphavantage 提前到 finnhub 之前 + 新浪 `stock_us_daily` 主源（无限额）；
3. `indicators` 端点对瞬态失败**短退避重试一次**（首次失败 1s 后重试——SPY 实测 try2 曾成功，akshare 间歇恢复场景收益明显）。

### 阶段 4（P1，前端空态统一）

- `TechnicalAnalysisModal` 对 `data_available=false` 显示「数据源暂不可用（行情源异常），可重试」+ 自动重试一次（与问题 7 阶段 4 的弹窗空态改造统一实施，`_stale` 字段透传时显示「过期数据」徽标）。

### 阶段 5（测试与验收）

| # | 测试 | 断言（含负向） |
|---|---|---|
| T1 | 后端 pytest：stale 兜底 | mock 缓存过期 + fetch_history 失败 → `get_history` 返回任意年龄缓存且 `is_kline_stale=True`（**负向：不接 stale 返回空 → FAIL**） |
| T2 | 后端 pytest：TickFlow US 分支 | `_tickflow_kline('SPY','US')` ≥30 行（mock `TickFlow.klines.get` 返回 500 行）；列映射后 close 有效；key 缺失/tickflow 异常 → 返回 [] 降级链继续不抛错（**负向：抛异常中断 → FAIL**） |
| T3 | 端点实测（交易时段）：`indicators/SPY` | 数据可用或 `_stale=True`（非 `data_available=False` 无解释）；AAPL/QQQ 稳定 |
| T4 | 前端 vitest：弹窗空态 | data_available=false 显示「数据源暂不可用」+ 重试；_stale 显示「过期数据」徽标（负向：显示「数据不足」无重试 → FAIL） |
| T5 | 手动走查 | 美股自选点技术分析：有数据或明确过期/不可用提示，不再裸「数据不足」 |

**design-checklist 对照**：

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ SPY 3 次实测（2 败 1 成）+ 腾讯 AAPL/QQQ 321 根实证 | ✅ §三十七 全部 file:line + 实测命令 | ✅ 源链复测标「交易时段」；stale/缓存逻辑无窗口限制 | ✅ stale 旧数据 + 显式标记，不冒充实时 | ✅ get_history 已被 indicators/chart 调用（market.py:341） | ✅ 弹窗四态含「过期/不可用」 | ✅ stale 兜底 O(1)；腾讯源单请求；重试有界 | ✅ ① 缓存过期即空 + 源链整体失效无兜底（get_history:1415） |

## 三十九、已知问题与风险

1. **SPY（NYSE 系）无可用源（已解决 2026-08-12，双源保障）**：原判断「腾讯不覆盖、stooq 被墙、yfinance 需代理」已过时——**TickFlow `SPY.US` 500 根实测可用（含当日收盘）+ 新浪 `stock_us_daily` 6438 行全量兜底**，SPY 不再依赖 stale 兜底；腾讯/腾讯 NASDAQ 系为备选，stooq/yfinance 仍不可用（保留为后续可选增强，不做阻塞）；
2. **stale 数据时效性**：旧缓存可能滞后数日——前端必须显式标注「过期数据（截至 YYYY-MM-DD）」而非静默展示（对照反假完成）；
3. **腾讯美股覆盖面**：NASDAQ 系（AAPL/QQQ）可用；不同交易所后缀映射（.OQ/.N/.A 等）需实施时按标的核实，未知后缀返回空不抛错；
4. **限流审计的连带影响**：降级链超时（8s+8s+10s）会拖长冷态响应——审计后对不可靠源设更短超时或跳过，避免「空转源」（性能软门禁）。

---

# 第十部分：测试防护盲区复盘（为什么现有测试没抓到 round19 的 bug）

## 四十、结论摘要

1. **round19 九个问题中的 bug 分 6 类**，现有测试防护体系（round15 基线 A-E + verify_perf.py + pre-commit 门禁）**逐类失效**；
2. **共性根因收敛为 4 条**：① 断言粒度停在「存在/非空/200」；② 降级测试验「降级发生」不验「降级对用户诚实」（空/0 被当正常）；③ 测试边界 = 组件边界（事件契约/生命周期/状态同步等「连线」层无覆盖）；④ 组合矩阵与冷态未进测试设计（默认态 + 单开关 + 有缓存）；
3. **补强方向**：断言升级（渲染位置/落库字段/冷态语义）+ 组合矩阵参数化 + 跨组件契约测试 + 环境失效建模（EM 风控/超时/限额）+ verify_e2e 边界用例——**纳入各问题实施时的测试设计，不新增门禁段**。

## 四十一、6 类 bug 与防护失效对照

| 类型 | 问题 | 本质 | 防护失效原因 |
|---|---|---|---|
| A. 外部源环境失效 | 4（EM 风控断连）、9（akshare 全挂） | 运行环境 ≠ 测试环境（CI 网络正常） | 降级链测试 mock「源可用/单源失败」，没建模「全源必败」（RemoteDisconnected/8s 超时/限额窗口） |
| B. 降级语义错误（空/0 冒充） | 4（`or 0` 兜底）、9（冷态静默空） | 「返回空/0」被测试当成正常结果 | 断言「不抛错/返回非空」，未断言「全败时必须显式标注而非静默空/0」 |
| C. 跨组件契约断链 | 2（cachedEtfs 快照）、6（connectWS 生命周期）、7b（@analyze 漏绑） | 单组件 spec 各自为政，测不到「连线」 | WatchlistPanel spec 测不到 MarketAnalysis 有无绑定；Dashboard spec 测不到 App 导航栏展示 |
| D. 内部状态组合 | 5（MACD gridIndex 写死 2，volume 关闭时暴露） | 测试只覆盖默认态/单开关 | 组合矩阵未参数化 |
| E. 写入端落库遗漏 | 3（avg_cost/shares_held 不落库） | 测试只测消费端与路由冒烟 | 211 个后端测试文件无 add_etf 字段落库断言 |
| F. 功能缺失（非回归） | 1（相关性）、8（指数覆盖） | 测试防回退、不防「功能从未存在」 | 无需求驱动的「缺失功能」测试（属设计流程 D1 探针范畴，非测试门禁） |

## 四十二、实证（现有测试断言与 bug 的错位）

- **①「验存在」不「验正确」（问题 5）**：`AnalysisView.spec.js:207-215` **已有**「关闭成交量 → MACD 不受影响」测试，断言 `series.some(s => s.name === 'MACD')`（`:214`）——**恒真**：MACD series 对象确实在数组，但其 `xAxisIndex=2` 指向 volume 关闭后**不存在的 grid**，是 ECharts 运行时渲染错位——option 结构断言看不到「渲染位置正确性」（需断言 xAxisIndex 对应的 xAxis/grid 存在）；
- **② stale 兜底测试只测「有缓存」路径（问题 9）**：`test_f0_kline_degradation.py:67-95` 先注入过期缓存再全源失败（测「有缓存时兜底成功」）——**未测「无缓存冷态 + 全源失败」**（`_kline_cache_rows` 是内存缓存、进程重启即空 → `get_kline_rows_any` 返回 None → 静默返回空，SPY 实测场景）——该路径应打 ERROR/前端显式提示，当前无语义断言；
- **③ 降级链 mock 理想输入（问题 4/9）**：`test_f0_kline_degradation.py:18-43` monkeypatch「单源失败 → 下一级」——**未 mock「EM 风控 RemoteDisconnected + akshare 内部 8s 超时」**这一真实形态，三源全败被视为不可能 → 全链失败的空/0 被当正常；
- **④ 写入端零覆盖（问题 3）**：`test_cumulative_pnl_estimation.py` 用 FakeEtf 直接构造 avg_cost（测**消费端**估算逻辑），`add_etf`/`update_etf` 仅路由冒烟/性能类引用——「前端传了被静默丢弃」无人断言；
- **⑤ 工具函数绿 ≠ 链路通（问题 7a）**：`test_asset_prefix_normalization.py` 测 `_strip_a_prefix` 工具（正确）——但 `fetch_history` 主入口（`china_market.py:1488`）**没接线调用它**，工具层测试绿掩盖调用链断裂；
- **⑥ 跨组件契约无覆盖（问题 7b/2/6）**：@analyze 事件、connectWS 生命周期（Dashboard 挂载才连）、cachedEtfs 快照（store 更新 vs 组件内部 ref）——均为跨单元问题，单组件 spec 不可见。

## 四十三、补强方向（纳入各问题实施测试设计，不新增门禁段）

| # | 补强 | 覆盖问题 | 断言形态 |
|---|---|---|---|
| 1 | **渲染位置断言**：series 的 xAxisIndex/yAxisIndex/gridIndex 必须指向存在的 xAxis/yAxis/grid | 5 | `opt.xAxes.length > s.xAxisIndex && opt.grid.length > (opt.xAxes[s.xAxisIndex].gridIndex)`（负向：写死 2 越界 → FAIL） |
| 2 | **落库断言**：add_etf/update_etf 后 SELECT 验证 avg_cost/shares_held 落库 | 3 | 传值 → `list_etfs` 返回一致值（负向：丢弃 → FAIL） |
| 3 | **冷态语义断言**：无缓存 + 全源失败 → 必须打 ERROR/返回显式不可用标记（禁止静默空/0） | 4、9 | `get_history` 空且无缓存 → 日志含 ERROR；indicators 返回 data_available=false + _stale 或明确提示 |
| 4 | **组合矩阵参数化**：指标开关关键组合（volume 关 + 各指标开） | 5 | 每组合断言指标 series 的 grid 可达 |
| 5 | **跨组件契约测试**：@analyze 绑定存在性、路由切换的 connectWS 生命周期、增删后列表刷新 | 7b、6、2 | 父组件 spec 断言子组件事件被监听；store 变更后组件列表响应 |
| 6 | **环境失效建模**：显式 mock「RemoteDisconnected/8s 超时/限额 429」的降级链测试 | 4、9 | 全源必败 → 断言走 stale 兜底或显式不可用，且超时预算收紧（akshare 3s） |
| 7 | **verify_e2e 边界用例**：带前缀 symbol（sz301308）、SPY 冷态（清缓存）、非首页导航栏状态 | 7a、9、6 | e2e 断言非「暂无数据」占位 |

**定位说明**：本部分为「测试怎么写才对」的复盘（对照 round15-test-guard-baseline 的盲区补充），不重复诊断表；实施时按「补强 #N」挂到对应问题的测试设计（问题 5 → #1/#4，问题 3 → #2，问题 4/9 → #3/#6，问题 7 → #2/#5/#7，问题 6 → #5/#7，问题 2 → #5），**不新增 pre-commit 门禁段**（对照门禁治理约定：新增门禁须说明差异化价值，本部分均为既有基线的断言深度升级）。

---

# 第十一部分：实施批次与顺序（跨问题编排）

> 各问题章节内是「分阶段」，本节是**跨问题的实施编排**（批次间有依赖，批次内可并行/串行按风险递增）。所有改动在实施时按「批次 N → 完成验收 → 批次 N+1」推进，每批次结束后跑对应验证（各问题验收表 + verify_e2e）。

## 批次 1（P0 最小/独立，低风险——先修「断链与落库」）

| 项 | 来源 | 改动 | 验证 |
|---|---|---|---|
| MarketAnalysis 补 `@analyze` | 问题 7 阶段 2 | 一行绑定（`MarketAnalysis.vue:45`） | 问题 7 T3 |
| fetch_history 入口剥前缀 | 问题 7 阶段 1 | `china_market.py:1488` 入口归一化 | 问题 7 T1（sz301308 ≥30 行） |
| watchlist 入库归一化 + 存量清洗 | 问题 7 阶段 3 | `add_watchlist` strip + `sz301308→301308` 迁移 | 问题 7 T2 |
| add_etf/update_etf 落库 avg_cost/shares_held | 问题 3 阶段 1 | `portfolio_service.py:128-146/186-207` 补写 | 问题 3 T2（负向：丢弃→FAIL） |
| AnalysisView MACD gridIndex 动态化 | 问题 5 阶段 2 第 1 条 | `AnalysisView.vue:365-379` 改 `grids.length` | 问题 5 补强 #1/#4 |

**批次 1 完成后**：江波龙全链路可用、持仓成本可落库、MACD 副图不再消失——均为独立小改，回归面最小。

## 批次 2（WS 统一改造——问题 6 方案 A 先行，问题 2 方案 B 紧随）

1. **问题 6 方案 A**（连接提升 App.vue 全站常驻 + `wsStatus` 五态 + 文案/初始态）——**先做**（`portfolio_changed` 广播消费的前提）；
2. **问题 2 方案 A**（cachedEtfs 快照移除，改响应式）——独立可并行；
3. **问题 2 方案 B**（后端 `portfolio_changed` 广播 + 前端 onmessage 分流/防抖）——依赖 1 的载体；
4. 合并验收：问题 6 T1-T3 + 问题 2 T1-T3（含跨页面/双标签页走查）。

**批次 2 完成后**：导航栏状态真实、持仓增删跨页面/标签页自动刷新。

## 批次 3（行情源修复——外部源依赖，需验证窗口配合）

1. **问题 4**：阶段 1（push2delay 直连 `fetch_em_industry_sectors`）→ 阶段 3（0→null + degraded 前端提示）→ 阶段 4（失败日志/非零率监控）；
2. **问题 9**：阶段 1（stale 兜底，先立竿见影）→ 阶段 2（`_tickflow_kline` 扩 US/HK 分支，主修复）→ 阶段 3（降级链重排：akshare 3s 快速失败 + alphavantage 提前）；
3. **问题 8**：阶段 1（静态段扩展，symbol 按 §三十五 验证）→ 阶段 3（`fetch_index_history` 加 HK 分支，`hk{code}` 腾讯源）；
4. 验证窗口标注：**交易时段 9:30-15:00 复测**（涨跌幅/源链盘中变化）；stale/TickFlow/静态段逻辑非窗口可验。

**批次 3 完成后**：板块热度非零率 ≥90%、美股（含 SPY）技术分析有数据、港股指数补全且点击有 K 线。

## 批次 4（体验与输出——前端为主，依赖批次 1 的部分结果）

1. **问题 5**：阶段 1（弹窗第三 grid + RSI/KDJ/MACD 三选一）→ 阶段 2 剩余（radio 单选 + volume 固定 + gridHeights 提升 22/24/24）→ 阶段 3（`useIndicatorSeries` composable 去重）；
2. **问题 3**：阶段 2（当前价即成本 + 后端兜底）→ 阶段 3（`recompute_cost_after_trade` + PUT adjust 语义 + target_weight 联动）→ **存量迁移**（§十九 风险 1，按当前价补录 avg_cost + 口径对比）；
3. **问题 1**：阶段 1（`engine/correlation.py`）→ 阶段 2（同指数硬约束 + 高相关压重）→ 阶段 3（报告关联度体检 + rationale 文案条件化）。

**批次 4 完成后**：指标副图可切换且不消失、成本/买卖语义完整、组合关联度可感知。

## 批次 5（收尾：测试防护补强 + 全量回归）

1. §四十三 补强 #1-#7 按问题挂入（渲染位置/落库/冷态语义/组合矩阵/契约/环境失效/e2e 边界）；
2. verify_e2e 扩展边界用例（带前缀 symbol、SPY 冷态、非首页导航栏）；
3. 后端 pytest 全量 + 前端 vitest 全量 + `npm run build` + verify_e2e 全 PASS（对照 AGENTS.md DoD：测试绿 + 现实证真）。

**批次依赖总览**：批次 2 依赖问题 6 方案 A 先行；批次 3 独立（行情源）；批次 4 依赖批次 1 的落库/前缀修复（问题 3 阶段 2/3 与问题 5 渲染）；批次 5 收尾。各批次内部项可并行时按「独立小改先行」排序。
