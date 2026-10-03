# Advice Valuation Extension / 投顾估值扩展（L1 v2 草稿）

> 基于 `agents.md §3 /llm-advice/stream` 的扩展契约，不新增路由。
> 对应现状：`backend/app/routers/analysis.py:587 llm_advice_stream` → `services/llm_context.py:13 build_full_context` → `analysis/llm/reports.py:1501 _build_advice_stream_prompt`（消费槽见 `tests/test_advice_p0a_slots.py:92` P3-G）。
> 动机实证：`sess-1ef0958821864c07`（低估+基本面恶化）因无估值槽被迫拒答后编常识，且 ETF 码幻觉（`515220` 复用、`159766=旅游ETF富国` 当煤炭）。
>
> **round60 C1 修订（2026-10-02，契约与代码对齐）**
> - `:4` 的三处行号此前全错（指向 `analysis.py:498` / `reports.py:1156`），已订正为实际位置。
> - 删 `fetching_etf` phase 承诺（D3）：`etf_map` 取数是 `SECTOR_ETF_MAP` 静态表的
>   内存遍历 + substring 匹配（`analysis.py:727-735`），**零 I/O、零延迟**，
>   为瞬时操作发进度阶段是表演而非诚实。见 §6。
> - §5 标注 v1 未实现（D6），保留设计意图供后续工具化。
>
> **round60 W1-W3 修订（2026-10-02，词表覆盖率与结构清理）**
> - **W1 删 8 个结构性死词**：`价值陷阱`（被 `陷阱` 吸收）、`支撑位`/`压力位`/`阻力位`
>   （被 `支撑`/`压力`/`阻力` 吸收）、`买点`/`卖点`/`买入`/`卖出`（被裸词 `买`/`卖` 吸收）。
>   同组内存在更短条目时，长词永远不可能改变结果——删除可证明行为不变（81 条探针 0 变化）。
>   保留它们会制造「这个词生效」的错觉（round60 靠变异测试才发现「支撑位」从未承重）。
>   防再犯：`tests/test_advice_goldset_l1.py::test_no_structurally_dead_keywords`。
> - **W2 加口语入口**：`估值`（原只有 `低估`/`高估`/`市盈率`/`市净率`，故「估值低」落 general，
>   gold case E13）、`选哪个`/`买哪个`（原只有书面语 `选哪只`/`买哪只`）。
> - **W3 `风险` 升为主词 + 显式排除表**，见 §3.1。

---

## 1. 概述 / Overview

**功能描述 / Description**: 开放问按七意图路由（`general` 为兜底）；`valuation` 必调估值工具、`product` 信号才调 ETF 映射；**受限 2 步 loop（白名单 2 工具封顶）当前未实现，调度硬编码在 router**（见 §5）；缺数显式降级、不编数不编码。

**触发场景 / Trigger**: `AiAdvisor.vue` 每次提问 `POST /llm-advice/stream {query, market, session_id?}`；分类在首字节 `progress` 之后、LLM 主调用之前完成。

---

## 2. 意图分类 / Intent Taxonomy

| 意图 Intent | 示例 Queries | 加采 Extra slots | gold set |
|---|---|---|---|
| `valuation` | 低估/高估/**估值**/贵/便宜/PE/PB/分位/股息/ROE/陷阱/错杀 | `index_valuation`、`sector_valuation` | A01-A02, K04, K71-K72, E13 |
| `rotation` | 轮动/风格/成长/价值/主线 | —（复用 sector+fund_flow） | A09-A10, K52-K54 |
| `event` | 政策/降息/加息/关税/利好利空/监管/新闻/央行/美联储/决议 | news 加深（个股新闻链路） | A07-A08, K19-K24, K50-K51 |
| `allocation` | 怎么配/调仓/加仓/减仓/仓位/买卖 | `portfolio`（**前端已注入**，§8 D1） | A13-A14, K38-K42 |
| `risk` | 止损/止盈/回撤/对冲/避险/波动率/杠杆/爆仓/跌穿/平仓/套保/**风险**（排除表见 §3.1） | indicators 摘要（P1 定口径） | A05-A06, B04-B05, K10-K18, K76-K80 |
| `product` | 买哪只/选哪只/**选哪个**/**买哪个**/买什么ETF/ETF推荐/代码是多少/成分股映射/日均成交/流动性不足（§3.2） | `etf_map`（`instruments` 白名单） | A03-A04, K05-K09, K67, E18 |
| `technical` | 支撑/压力/阻力/回撤族/均线/破位/前低/前高/布林/BOLL/量能/缺口/抄底/企稳（§3.3） | `index_technical`（MA/BOLL/RSI/KDJ）+ `support_levels` | A11-A12, B06-B09, K25-K37, K56-K57 |
| `general` | 兜底 | 不加采，直接诚实降级 | D01-D06, E01-E04, gap-* |

**优先级 Priority**（复合命中时）：`valuation > product > risk > event > rotation > technical > allocation > general`。
> round59：`technical` 置于 `rotation` 之后、`allocation` 之前——支撑位问题常同时含
> 「买点/加仓」字样，若排在 `allocation` 之后会被抢走并再次退回泛泛而谈。
> round60 W3：补了 risk×event 配对用例（C09/C10）——此前**没有任何用例同时命中这两族**，
> 故把两者在链内对调无人发现（变异测试发现）。优先级链每一对相邻/关键配对都需有用例。

例：“低估+基本面+ETF映射”判 `valuation` 主路由 + `product` 子任务（拼 ETF 行），不压扁。
例（round59）：「这轮A股下跌的支撑位会是怎么样的？能不能买点」判 `technical`（非 `allocation`）。
例（round60 W3）：「降息对我的持仓有什么风险」判 `risk` 主路由 + `event` 复合（C09）。
例（round60 W2）：「红利和银行ETF选哪个」判 `product`（此前因缺 `选哪个` 落 `general`，E18）。

**分类方法 Classifier**（混合两档）：
1. 关键词先判（零成本，§3 清单）；零命中直接 `general`（小模型第二档 deferred——v1 关键词覆盖已够，省一次 LLM 调用；后续模糊问复发再加）。
2. 存量关键词不改：sector/news 沿用 `routers/analysis.py:161-184`。

---

## 3. 新增关键词清单（收紧版）/ Keywords

### 3.1 `risk`：主词表 + **显式排除表**（round60 W3 修订）

* 主（命中即判）：`止损/止盈/回撤/对冲/避险/波动率/杠杆/爆仓/跌穿/平仓/套保/`**`风险`**
* **排除表（优先于一切，命中即 return False）**：`风险提示`、`风险和适用场景`
  > W3 前「风险」单用不判 risk，需搭配 `怎么办/如何应对/怎么控`（辅助门）。W3 起
  > `风险` 升为主词，辅助门随之冗余并删除，其精确性由排除表承担。
  > **为什么必须显式写出来**：原来「风险提示有哪些」不判 risk 是**巧合**——该串不含任何
  > risk 主词，辅助门根本没被询问。若将来有人为别的目的把 `风险提示` 加进主词表，
  > 每篇报告都会被路由成 risk，且**静默失效**。排除表把巧合变成声明。
  > **只收可证的两条**：`general_analyst.md:6` 要求每篇答案写「潜在风险和适用场景」，
  > 故「风险和适用场景」是产品自身词汇；「风险提示」见本文件历史与
  > `tests/test_advice_p0a_slots.py:155`。曾试列 `风险揭示/风险警示/风险收益/风险偏好`
  > 四条，但**无法用任何证据判断**该不该判 risk（例：「风险收益比怎么算」判 risk 也说得通），
  > 故不放进排除表——排除表的每一条都是一次假阴性，只收可证的一条。
* 其余规则不变：`防御+加仓/减仓/调仓`、`安全垫`；回撤族（带后缀）豁免 risk。

### 3.2 `product`：必须带 ETF 锚，禁裸“买”

* 主：`买哪只/选哪只/`**`选哪个`**/**`买哪个`**`/买什么ETF/买什么etf/ETF推荐/etf推荐/代码是多少/成分股映射/日均成交/流动性不足`
  > round60 W2：`选哪只` 是书面语，用户口语更常说 `选哪个`/`买哪个`；原词表只收书面语，
  > 导致「红利和银行ETF选哪个」落 general（gold case E18）。实测 4/81 探针零误伤。
* 代码形态：6 位数字 + 上下文含 `ETF/买/换成` 才判；裸 6 位板块码（如 `881001`）不判。
* 排除：裸`买/卖/加仓`归 `allocation`；个股推荐红线（`general_analyst.md:11`）——product 只许 ETF。
* `买什么ETF` 与 `买什么etf` 两份、`ETF推荐` 与 `etf推荐` 两份**不是冗余**：
  子串匹配区分大小写，各自承重（keyword meta-test 会因缺任一条而红）。

### 3.3 `technical`：主+辅两档，禁与技术无关词碰瓷（round59 新增）

* 主（命中即判）：`支撑/压力/阻力/均线/破位/前低/前高/布林/BOLL/缺口/量能/抄底/企稳`
  > round60 W1 删除了 `支撑位`/`压力位`/`阻力位`——它们被同组更短的 `支撑`/`压力`/`阻力`
  > 吸收（同组内长词被短词遮蔽 ⇒ 永不可能改变结果，81 条探针 0 变化）。**用户仍可输入
  > 「支撑位」并正确命中**，因为 `支撑` 是它的子串；删除只是不让词表**假装**这三条存在。
  > 防再犯：`test_no_structurally_dead_keywords`。
* 回撤族（**必须带位/到，裸「回撤」归 risk**）：`回撤位/回撤到/回踩到/反弹到`
  > `回撤` 已是 `risk` 主词（§3.1）且 `risk` 在优先级链更前，故 technical 不可再收裸
  > `回撤`，否则「回撤太大怎么办」会被误判 technical。改用带后缀形态消歧。
* 排除（**必须不判 `technical`**，防误伤既有意图）：
  * `最大回撤/回撤太大/止损/止盈/对冲/避险/波动率/杠杆` → `risk`（§3.1）
  * 「买点到了吗/能不能加仓」**无技术词** → `allocation`
  * 「风险提示有哪些」→ `general`（靠 §3.1 的**排除表**，非本节规则）
* 正反例（`backend/scripts/advice_evals/goldens/l1_intent.jsonl` 单测锁定，括号内为 case id）：
  * 正：`这轮A股下跌的支撑位会是怎么样的`→technical（A11）；`回撤到多少支撑`→technical（B06）；
    `上证均线在哪`→technical（A12）；`支撑位跌破要不要减仓`→technical（B07，技术词胜出，
    **不得**被 `allocation` 抢走）
  * 反：`回撤太大怎么办`→risk（B04）；`最大回撤是多少`→risk（B05）；
    `买点到了吗`（无技术词）→allocation（B10）
  * 优先级：`轮动到支撑位`→rotation（B09）；`支撑位在哪，能不能加仓`→technical（B08）

---

## 4. 槽位定义 / Slots

### 4.1 基础槽（每次常驻，复用 60s 会话快照 `chat_session.py:170`）

`market_regime`、`market_sentiment`、`market_data`（指数）、`sector_momentum`、`hot_plates`、`sector_heat`、`fund_flow`、`news`、`commodities`（round60 C3 起，此前投顾是唯一不注入商品的链路）。P3-G 约束不变：router 注入 ⊇ prompt 消费。

### 4.2 `index_valuation: array`

```json
[{ "symbol": "000300", "name": "沪深300", "pe_ttm": 12.5, "pb": 1.8,
   "pe_pct_5y": 0.35, "pb_pct_5y": 0.40, "as_of": "2026-09-16" }]
```

### 4.3 `sector_valuation: array`

```json
[{ "sector_code": "BKxxx", "sector_name": "银行", "pe_ttm": 6.1, "pb": 0.62,
   "roe_ttm": 0.11, "dividend_yield": 0.055, "pe_pct": 0.2,
   "profit_growth": -0.02, "as_of": "2026-09-16" }]
```

### 4.4 `etf_map: array`（只读 `instruments`，禁裸写码）

```json
[{ "sector_or_index": "银行", "symbol": "512800", "name": "银行ETF华宝" }]
```

> 反例：`515220=煤炭ETF国泰` 不许当银行；`159766=旅游ETF富国` 不许当煤炭（`sess-1ef0` 实证）。

### 4.5 `index_technical: array`（round59，仅 `technical` 意图注入）

```json
[{ "symbol": "000001", "name": "上证指数", "close": 3823.62,
   "ma5": 3840.1, "ma10": 3862.4, "ma20": 3880.0, "ma60": 3901.7,
   "boll_upper": 3955.2, "boll_mid": 3880.0, "boll_lower": 3804.8,
   "rsi": 41.2, "kdj_j": 22.5, "as_of": "2026-09-28", "data_source": "sina" }]
```

- **只读缓存**：请求链内禁止同步 `refresh_kline`（冷刷新实测 42-75s）；未命中 → 整段省略 + 异步后台 refresh。
- **缺 `as_of` 的数值一律以 `（数据源暂不可用）` 占位**，禁止填 0。
- 缺层整段省略（§2.2 降级纪律），**禁止**用相邻层数值顶替。

### 4.6 `support_levels: object`（round59，engine 纯函数产物）

```json
{ "as_of": "2026-09-30", "price_now": 3842.2,
  "indicators": { "ma5":3864.23, "ma10":3890.23, "ma20":3905.64, "ma60":3904.04,
                  "boll_upper":3989.53, "boll_mid":3905.64, "boll_lower":3821.74 },
  "dynamic":   [{ "level":"MA20","value":3905.64,"kind":"resist","basis":"20日均线，跌破则趋势转弱" }],
  "structural":[{ "level":"近60日低点","value":3741.11,"kind":"support","basis":"前低，跌破则打开空间" }],
  "fib": { "s1":3881.13,"s2":3854.40,"s3":3827.66,
           "anchor_low":3741.11,"anchor_high":3967.68,
           "anchor_low_index":68,"anchor_high_index":114,"k_primary":3,
           "fib_unavailable_reason": null,
           "fib_levels":[{ "level":"回撤 38.2%","value":3881.13,"kind":"resist","basis":"..." },
                         { "level":"回撤 61.8%","value":3827.66,"kind":"support","basis":"..." }] } }
```

- **Fib 只有一族三档，方向由 `kind` 逐档标注**（round59 实施修正）。
  方案原稿另要求一族「反弹阻力位」`L* + ratio×(H*−L*)`，但它与支撑族**代数恒等**
  （`L* + r·span ≡ H* − (1−r)·span` ⇒ `R(38.2%)≡S(61.8%)`、`R(50%)≡S(50%)`、
  `R(61.8%)≡S(38.2%)`）。同时输出会让模型在同一答案里读到
  「支撑 3827.66」与「阻力 3827.66」两个互斥标签。故取消该族，
  方向改由每档 `kind` 承担（`kind` 取值仅 `support`/`resist`）。
- **方向标注规则（本契约最高风险项）**：`value < price_now` → `support`；
  `value > price_now` → `resist`；`value == price_now` → **不输出**（无法归类）。
  跌势中位于现价上方的回撤位是阻力，标成支撑是硬错误
  （实测 000001 现价 3842.20 落在回撤区内部：`S1/S2` 在上方=阻力，`S3` 在下方=支撑）。
- **恒真不变式**（替代原稿的 `S3<S2<S1<P_now`，后者只在**上涨**趋势成立，
  而提问场景恰是下跌行情）：标 `support` 的必在现价下方、标 `resist` 的必在上方、
  两族不得出现在同一列表。跨 `dynamic`+`structural`+`fib_levels` 的价位不得重复。
- **Fib 锚点选取**：枚举全部 ≥5% 的分形上涨段，取**最近一段其回撤区仍覆盖现价**
  （`S3 < price_now < S1`）者；若全部不覆盖 → `fib_unavailable_reason =
  "no_upleg_brackets_price"`，三档全不输出（实测 000300 沪深300 命中此路径）。
- **锚点稳定性**：`k=3` 与 `k=5` 两组分形若选出不同锚点 → 禁用 Fib，
  `fib_unavailable_reason = "anchor_unstable_k3_k5"`。
- **Bollinger 口径**：`ddof=1`（样本标准差），与 `pandas_ta` 一致；
  用 `ddof=0` 会使同一标的在 `/market/indicators` 与本槽位出现两个不同的下轨值。
- 日线级口径，盘中 tick 级支撑位不覆盖（`as_of` 缺失即禁引用该值）。

### 4.7 `commodities: array`（round60 C3 实施，跨资产问答）

**为什么加**：投顾是**唯一**不注入商品的 LLM 链路（`analysis.py:623`
`include_commodities=False`），而 README 首段把「黄金/原油/白银」列为产品六大资产类别之一。
即产品定位覆盖跨资产，投顾链路却对「黄金和原油配哪个」落 `general`（实测，见 gold case E10）。
故 C3 起按**基础槽**注入（与 `market_regime`/`news` 同款，不加新意图、不做意图触发加采）。

```json
[ { "name": "黄金", "price": 2380.5, "change_pct": 0.62 },
  { "name": "原油", "price": 71.34,  "change_pct": -1.15 } ]
```

- **渲染复用**：`reports.py:123 _format_commodities`，与市场报告链（`llm-report`）同一渲染器，
  禁止写第二份格式。规范化别名（GC/黄金/GOLD/XAU → 黄金 等）由该函数内 alias 表承担。
- **行数上限**：规范化后 ≤6 行（`_format_commodities` 自带 `commodities[:6]` 兜底）；
  上游 `llm_context.py:170-176` 另有 `[:10]` 截断 + 15s 超时。
- **空槽整段省略**：不得渲染兜底数字。盘后/非交易时段上游允许返回 `[]`
  （`china_market.fetch_futures_realtime` 8s 超时、失败静默空列表），
  这是**合法空窗**而非故障，模型应说「商品实时数据暂不可用」，不得用上一交易日数值冒充。
- **与 scope 守卫的关系**：本槽是**跨资产**数据，不受 §4.8 的 A 股 scope 限制；
  但反之，query 问 A 股标的时**不得**用商品行情替代（scope 守卫同样适用）。

### 4.8 scope 声明行（round60 C3 实施，D8）

> **问题（D8）**：`_VALUATION_KWS` 含 `贵`/`便宜`（`intent.py:19`），所以「恒生科技贵不贵」
> 「黄金现在贵吗」「美股和A股哪个估值低」等问句都会命中 `valuation`；但取数硬编码 5 个
> A 股指数（`analysis.py:700-701`），**给港股/黄金/美股问句端上一张 A 股估值表**。
> 同根因还命中技术面槽（实测 E08「纳斯达克跌破支撑位了吗」→ `technical`，而技术面仅
> 覆盖 `000001`/`000300`）与 ETF 映射槽（E07「港股红利ETF推荐」→ 注入 A 股 `510880`）。

**契约**：query 命中非 A 股资产线索（`港股/恒生/H股/纳指/标普/美股/黄金/原油/白银/国债`）
时，prompt 必须**显式声明覆盖范围**，且被声明不适用的槽降级为「参考背景」：

```
本产品估值/技术面/板块数据仅覆盖 A 股宽基与行业指数；该问题涉及的标的属非 A 资产，
以下表格不适用于它，请勿据此下结论。
```

- **不改词表**：删 `贵`/`便宜` 会砸掉 S4 估值主族（「红利是不是价值陷阱」）。问题不在分类，
  在**数据 scope 与提问 scope 不匹配**。
- **不改取数**：推荐方案只加声明行（保留「顺带告知 A 股估值如何」的信息量）；
  备选方案是按 scope 拦取数（更干净，但少一段有用信息且需新增 scope 判定函数）。
- **反向要求**：A 股问句**不得**出现该声明行（防过度触发）；gold case 必须含
  「A股和港股谁更便宜」这类**跨市场比较**反例——此时声明行应出现且 A 股表保留为参考。

---

## 5. 受限 2 步 loop / Constrained Loop

> **状态：v1 未实现（round60 C1 标注，D6）**。下列工具与调度规则是**设计意图**，
> 不是当前行为。实际调度硬编码在 `analysis.py:673-735` 的两个 `if` 分支里
> （`valuation` 意图才拉估值；`"product" in intents` 才填 `etf_map`），
> 没有工具注册、没有 `max_steps`、没有模型自主调度。
> 保留本节是为了给后续工具化一个可执行的规格，而不是让读者以为它已经存在。
> 判据（round60）：**契约承诺的行为，要么有真实延迟/价值可展示，要么从契约删掉——
> 不留假承诺**。同理，零 I/O 的操作不配 progress phase（见 §6 `fetching_etf` 的删除理由）。

白名单仅 2 工具，`max_steps=2`，`run_sync` + `wait_for` 包裹，禁循环内裸 IO（AGENTS 陷阱项）：

```
valuation.query(scope: "index"|"sector", ids?: string[])
  -> index_valuation / sector_valuation（失败整块待验，不编数）

etf.lookup(sector_or_index: string)
  -> etf_map（未命中只给板块名，不编码）
```

调度（写死，不由模型自由定）：
1. `valuation` 意图必调 `valuation.query`（1 步）；
2. 仅当含 product 信号或追问要码时调 `etf.lookup`（第 2 步）；
3. `risk` 禁调 product；`general` 禁入 loop。

后校验：数无 `as_of` 不许下结论；码不在表不许输出；违例打回显式降级。

---

## 6. 输出格式 / Response

SSE 事件沿用 `agents.md §6.1`，新增 `progress.phase`：`fetching_valuation`（前端仅新增 phase 分支，不改消费逻辑）。

> **round60 C1 删除（D3）**：原契约还承诺 `fetching_etf`，代码从未实现，且**不应该实现**——
> `etf_map` 的取数是 `SECTOR_ETF_MAP` 静态字典的内存遍历 + substring 匹配
> （`analysis.py:727-735`），无网络、无 DB、无重计算，为瞬时操作发「正在查询…」进度阶段
> 属于对用户的表演。对比 `fetching_valuation`：25s 预算、5 指数并发外呼
> （`analysis.py:697-721`），那才是真延迟，配 progress 合理。
> 因此本契约只保留 `fetching_valuation` 一个 phase。

`done.full_text` 对 `valuation` 意图必须为结构表：

```
| 指数/板块 | PE分位 | PB分位 | ROE-TTM | 股息率 | 结论(错杀/陷阱/待验) | as_of+来源 |
```

缺数整行 `待验`。`product` 子任务另起“ETF 映射”行（码必出自 `etf_map`）。

### 请求示例 / Request Example

```
POST /api/v1/analysis/llm-advice/stream
Content-Type: application/json

{ "query": "现在有哪些板块和指数是比较低估的？基本面变差的是哪些？", "market": "A" }
```

### 成功响应示例 / Success Example

`progress(calling_model)` → `progress(fetching_valuation)` → `token*`（结构表，银行 PB 0.62/分位 20% / ROE 11% / 结论待验…）→ `done{full_text, metadata{session_id}, disclaimer}`。
### 降级示例 / Degraded Example
估值源全失败 → 表全行 `待验` + “估值源暂不可用（as_of 缺失），已用涨跌+资讯仅做定性，请收盘后重问”，不报 N/M 正常。

### `technical` 意图输出格式（round59）

`done.full_text` 对 `technical` 意图必须为**关键价位表 + 触发/失效条件**，且**不注入**
「行业轮动分析框架」与「资金流向」段（问支撑位却答板块轮动 = round59 M2 病灶）：

```
**上证指数 · 支撑位**（as_of 2026-09-30）
| 档位 | 点位 | 类型 | 依据 |
|---|---|---|---|
| 回撤 61.8% | 3827.66 | 支撑 | 上一轮上涨段 [3741.11, 3967.68] 回撤 61.8% |
| BOLL下轨 | 3821.74 | 支撑 | 布林下轨，波动率下沿，非刚性支撑 |
| 近60日低点 | 3741.11 | 支撑 | 前低，跌破则打开下方空间 |

**上证指数 · 阻力位**（as_of 2026-09-30）
| 档位 | 点位 | 类型 | 依据 |
|---|---|---|---|
| 回撤 50.0% | 3854.40 | 阻力 | 上一轮上涨段 [3741.11, 3967.68] 回撤 50% |
| MA5 | 3864.23 | 阻力 | 5日均线，短线强弱分界 |
| 回撤 38.2% | 3881.13 | 阻力 | 上一轮上涨段 [3741.11, 3967.68] 回撤 38.2% |
| MA20 | 3905.64 | 阻力 | 20日均线，跌破则趋势转弱 |
| BOLL上轨 | 3989.53 | 阻力 | 布林上轨，反弹压力参考 |
```

- 支撑族与阻力族**分行 + 方向标注**（`类型` 列 + 依据文字双重标注）；
  现价上方的回撤档归阻力、现价下方的归支撑，逐档判定而非整族一刀切。
- 字数上限 **1200**（非 technical 意图保持 800）。
- **诚实拒答三件套**（R13）：无技术面数据时输出「缺哪些数 / 去哪看 / 判断规则」，
  **禁止**只写「无法确认」——`sess-008bc66ee5734992` 的具体病灶。
- Fib 不可用（无覆盖现价的上涨段 / 锚点不稳）→ Fib 三档不输出 +
  「未识别到有效上涨段，Fib 回撤位不可用」说明。
- 负向硬约束入 prompt：支撑位与阻力位不得混列；无数据输出占位，禁止编造点位。

### 6.1 `technical` 意图的**数据可用性三档**（round60 C3 实施，D2）

问题：冷缓存时 prompt 既无价位数据、也无占位标记，却要求「先给关键价位表」
（实测 311 字 prompt）。R13 三件套挂在「若数据缺失或标注占位」的条件上——
冷缓存两个条件都不成立，指令自相矛盾，直接邀请模型编点位。

契约：框架第 1 步按**槽位是否非空**分流（三档互斥，不得同时出现）：

| 档 | 判据（`support_levels` / `index_technical`） | 框架第 1 步必须为 |
|---|---|---|
| **T-全空** | 两者皆空 | 插一行「（本轮无技术面/关键价位数据：日线源未返回，**禁止输出任何点位**）」+「**禁止输出支撑/阻力档位表与任何点位数字**，改按下方三件套回答」 |
| **T-仅技术面** | `index_technical` 非空、`support_levels` 空 | 「仅可引用上方技术面段的 MA/BOLL/RSI/KDJ 数值（带 `as_of`）作为参考，**禁止自行推断档位或未列出的点位**」 |
| **T-完整** | `support_levels` 非空 | 维持现状「先给关键价位表（档位/点位/类型/依据），再给结论」 |

- 字数上限 **1200** 三档一致；R13 三件套三档都在（`technical_intent` 即注入）。
- 判据只看槽位非空，**不看意图**——三档的意图都是 technical。

### 6.2 跨资产问句的输出（round60 C3，S8）

问「黄金和原油配哪个」时 `primary_intent = general`（**不加新意图**，见 §2 决策），
但商品段已在 prompt 内，期望回答形态为 `answer` 而非 `degrade`：

- 必须引用 §4.7 商品段内的名称与数值，并标注盘后/空窗（禁止用上一交易日数值冒充）。
- 允许比较与给倾向性判断；**禁止**给出精确目标权重（那属 `/portfolio/design-async` 的引擎职责，
  符合 README「LLM prose is decoration on top of engine output」）。
- 商品段为空时降级为「商品实时数据暂不可用」，并说明可在 `/market` 商品页查看。



---

## 7. 错误码 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | query 缺失/非 string |
| 502 | Bad Gateway | LLM 调用失败（含小模型分类失败，已回退 general 则不抛） |
| 500 | Internal Server Error | 未预期异常 |

---

## 8. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| 路由不变 method+path | ☑ | ☑ | 复用 `/llm-advice/stream`；`check_routes` 83 路由一致 |
| 请求体 query/market/session_id | ☑ | ☑ | 沿用 `llm-chat-session.md` |
| 请求体 `context.portfolio` 由前端注入 | ☑ | ☑ | **D1 round60 C4**（`9910d51`）：契约早已允许 `context` 对象透传，后端 `analysis.py:652` 一直在读，此前前端从不发 → 持仓段恒空。字段形状 `{symbol, name, target_weight}`；**不得**外泄 `avg_cost`/`shares_held`（前端用例断言整个请求体不含这两个键） |
| SSE 新增 phase 可渲染 | ☑ | ☑ | 仅 `fetching_valuation`（删除理由见 §6） |
| valuation 输出为结构表+as_of | ☐ | ☑ | **prompt 侧已具备并有 gold case；answer 侧待 L3 真 LLM 判定**（P1）。缺数整行待验 |
| ETF 码 ⊆ instruments | ☐ | ☑ | prompt 侧两条守卫齐备（白名单 + 无表禁码）；**answer 侧「模型是否真的没编码」待 L3** |
| **product 意图空 map 也须出禁码守卫** | N/A | ☑ | **D5 round60 C2**（`1654fc1`）：守卫原挂在 `valuation_intent` 上，纯 product 问句拿不到 = 编码窗口。变异验证：改回旧条件，L2 gold 与 router 用例同时变红 |
| 全空降级不报正常 | ☐ | ☑ | prompt 侧两条守卫（§6「不得下低估/高估结论」「不得编造任何 ETF 代码」）；**answer 侧待 L3** |
| 加载/空/错误/慢数据四态 | ☑ | N/A | `AiAdvisor.vue`：loading 禁用 + streaming 气泡 + progress 条 + error 块 + hint 空态 |
| `technical` 意图输出关键价位表 | ☐ | ☑ | **prompt 侧** round59 R09/R12 具备，按 §6.1 三档分流；**answer 侧待 L3**。1200 字 |
| **冷缓存 technical 不得要求出价位表** | N/A | ☑ | **D2 round60 C3**（`9aa4229`）：无数据无占位却要求出表 = 编点位邀请函。三档互斥，变异验证 2/2 killed |
| 支撑/阻力两族分行 + 方向标注 | N/A | ☑ | round59 R02b 负向用例（engine 侧不变式 + prompt 渲染） |
| 诚实拒答三件套（禁只写「无法确认」） | ☐ | ☑ | **prompt 侧** R13 三件套 + 禁空转措辞已注入；**answer 侧「模型是否照做」待 L3**——这是 round59 病灶所在，目前无任何断言看守 |
| **非 A 股标的出 scope 声明行** | N/A | ☑ | **D8 round60 C3**（`9aa4229`）：静态探针 4/4 复现（恒生/黄金/美股/标普均被端上 A 股表），修复后 A 股问句不触发、跨市场比较句触发。变异验证 2/2 killed |
| **跨资产问句有商品行情支撑** | ☑ | ☑ | **S8 round60 C3**（`9aa4229`）：`include_commodities=True` + 显式注入 + 复用 `_format_commodities`。空槽整段省略（盘后空窗为合法非故障）。**注意 flag 本身无用例能看守则功能会无声死掉，故有专门断言采集参数的用例** |
| **缓存命中可见** | ☑ | ☑ | **D4 round60 C4**（`9910d51`）：`_sse_stream` 丢弃 `cached` → 前端徽标恒不可达。已透传，SSE 边界双向用例（命中带 / 未命中不带） |
| **端点可达性门禁不得吞异常** | N/A | ☑ | **D7 round60 C4**（`9910d51`）：`verify_e2e` 原把超时与任何异常判 PASS = 运行时门禁不存在。改为重试一次后判 FAIL，并有 meta-test 走 AST 守门禁自身 |
| disclaimer | ☑ | N/A | 沿用既有 |

**勾选口径（round60 立规，避免把「prompt 写了」当成「功能成了」）**：

- **☑ = 该层的实现存在且有自动化断言看守**（prompt 装配层、或前端请求层、或门禁本身）。
- **☐ = 只有 prompt 侧具备，answer 侧（模型是否照做）尚无断言** —— 这不是漏勾，是**如实标注 L3 的缺口**。
  当前 5 行 ☐ 全部指向同一件事：真 LLM 判定（P1，需交易窗口）。这 5 行是 P1 的验收清单，
  不是待补的实现。

Refs: `docs/advice-goldset-design.md`（gold set 与变异测试记录）、
`backend/scripts/advice_evals/goldens/`（L1 143 条 / L2 16 条）。

---

## 9. 设计清单映射 / Design-Checklist Mapping

| # | 项 | 本契约状态 |
|---|---|---|
| 1 | 可行性探针 | 已做 2026-09-17（非交易时段16:xx，结论打“待交易时段复测”；组间≥60s，单次取数）：A `ak.stock_zh_index_value_csindex('000300')` ✓ 20行/0.3-0.6s，列=日期/指数代码/市盈率1/市盈率2/股息率1/股息率2（无PB），09-16收盘新鲜（14.60/16.82/2.63%/2.34%）；B1 `stock_board_industry_summary_ths` ✓ 90行/1.0s但纯动量无估值，B2 `stock_board_industry_spot_em` ✗ 单接口代理抖动（17.push2 RemoteDisconnected，待复测），B3 `stock_industry_pe_ratio_cninfo(date='20260916')` ✓ 120行/0.4s，列=行业编码/名称/静态PE三口径（加权/中位数/算术平均，无PB/ROE/股息）；C `fetch_current_pe_pb('600000')` ✓ 0.9s=PE6.87/PB0.94 |
| 2 | 证据链 | L2 口径暂定PE-only v1：指数用A源（近20日分位诚实标注+快照积累建长期分位），板块用B3静态PE现值+自建快照；PB/ROE/股息v1标待验，不编数。分位计算式待实施时数字代入 |
| 3 | 验证窗口 | 已标：估值/板块快照非窗口打“待交易时段复测”（`sess-1ef0` 09:33 正中空窗） |
| 4 | 非兜底/真实调用/四态 | §6+§8 已定，验收回查 |
| 7 | 复杂度审计 | 已定：`wait_for`+`run_sync`+批量+60s 快照复用；loop 封顶 2 步 |
| 8 | 已知模式 | 已声明：格式断言（分位 None）、mock 理想输入（限流空表）、契约盲区（新槽必进本文件）、降级无门禁（全空断言） |
| 1b | round60 C1 可行性探针 | §4.7 商品段：复用 `reports.py:123 _format_commodities`（市场报告链已在用），上游 `llm_context.py:170-176` 已封装 15s 超时 + `[:10]`，故本槽**无新取数风险**；唯一新增风险是 prompt 体积（≤6 行）。§4.8 scope 判定为**纯 substring 判定**（无网络），探针成本为零 |
| 2b | round60 C1 证据链 | D2 三档判据＝槽位非空（`support_levels`/`index_technical`），实测冷缓存 prompt 311 字且要求出表（见设计文档 §15.2）；D8 触发链＝`intent.py:19` 的 `贵`/`便宜` → `analysis.py:673,700-701` 硬编码 5 个 A 股指数，取数与提问 scope 不匹配 |
| 3b | round60 W1-W3 验证窗口 | 词表改动**不依赖行情真值**（`classify_all` 是纯函数），故不受 D3 窗口约束；实测 blast radius 用 81 条探针（gold set 全量 + 15 条自拟），**非生产流量**——仓库无真实用户问句语料（238 个 chat session 仅 1 条不同问句）。真 LLM 侧（P1）仍须交易窗口 |
| 4b | round60 W1-W3 非兜底 | 死词删除为**可证明行为中立**（0/81 变化）；词表新增的每个词都有「唯一触发词」用例，避免删掉该词结果不变而无人发现（这正是 round60 前 44/88 词条零覆盖的成因） |
| 5b | round60 W1-W3 真实调用点 | `classify_all` 生产调用方仅 `analysis.py:661`（已 grep 确认）；`classify` 仅测试用，meta-test 钉住两者一致而非迁移调用方 |

## 10. 关键词正反例（单测锁定用）

> **round60 C0 起，正反例的权威载体是 gold set**，不在本文件：
> `backend/scripts/advice_evals/goldens/l1_intent.jsonl`（143 条，含有序复合列表断言）
> + `backend/tests/test_advice_goldset_l1.py`。
> 本节保留为**人读摘要**；新增用例时请改 jsonl（每条带 `source`/`notes`），不要只改这里。

* 正：`止损线设哪`→risk；`回撤太大怎么办`→risk；`买哪只银行ETF`→product；`512800现在能买吗`→product；`哪些板块低估`→valuation（优先于 product）。
* 反：`风险提示有哪些`→general；`买点到了吗`（裸买）→allocation；`881001怎么看`（裸板块码）→sector-analysis 既有链路，不判 product。
* round59 正：`这轮A股下跌的支撑位会是怎么样的`→technical；`回撤到多少支撑`→technical；`上证均线在哪`→technical；`支撑位跌破要不要减仓`→**technical**（技术词胜出，不被 `allocation` 抢走）。
* round59 反：`回撤太大怎么办`→risk；`最大回撤是多少`→risk（均不因含「回撤」判 technical）；`买点到了吗`（无技术词）→allocation。
* round60 W1-W3 后：W3 把「风险」升为主词，故 `风险提示有哪些` 仍→general（靠**排除表**，不再靠辅助门巧合），而 `我的持仓风险有点大`→risk（新增覆盖）。
  W2 补 `估值`/`选哪个`/`买哪个` 后，`美股和A股哪个估值低`→valuation、`红利和银行ETF选哪个`→product。
