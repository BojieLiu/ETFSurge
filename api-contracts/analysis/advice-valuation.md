# Advice Valuation Extension / 投顾估值扩展（L1 v2 草稿）

> 基于 `agents.md §3 /llm-advice/stream` 的扩展契约，不新增路由。
> 对应现状：`backend/app/routers/analysis.py:498 llm_advice_stream` → `services/llm_context.py:13 build_full_context` → `analysis/llm/reports.py:1156 _build_advice_stream_prompt`（消费槽见 `tests/test_advice_p0a_slots.py:91` P3-G）。
> 动机实证：`sess-1ef0958821864c07`（低估+基本面恶化）因无估值槽被迫拒答后编常识，且 ETF 码幻觉（`515220` 复用、`159766=旅游ETF富国` 当煤炭）。

---

## 1. 概述 / Overview

**功能描述 / Description**: 开放问按六意图路由；`valuation` 必调估值工具、`product` 信号才调 ETF 映射；受限 2 步 loop（白名单 2 工具封顶），缺数显式降级、不编数不编码。

**触发场景 / Trigger**: `AiAdvisor.vue` 每次提问 `POST /llm-advice/stream {query, market, session_id?}`；分类在首字节 `progress` 之后、LLM 主调用之前完成。

---

## 2. 意图分类 / Intent Taxonomy

| 意图 Intent | 示例 Queries | 加采 Extra slots |
|---|---|---|
| `valuation` | 低估/贵/PE/PB/分位/股息/ROE/陷阱/错杀 | `index_valuation`、`sector_valuation` |
| `rotation` | 轮动/风格/成长价值/主线 | —（复用 sector+fund_flow） |
| `event` | 政策/降息/关税/利好利空/新闻影响 | news 加深（个股新闻链路） |
| `allocation` | 怎么配/调仓/加仓/减仓/仓位 | `portfolio`（用户带才用，不捏造） |
| `risk` | 见 §3 | indicators 摘要（P1 定口径） |
| `product` | 见 §3 | `etf_map`（`instruments` 白名单） |
| `technical` | 支撑位/压力位/阻力位/回撤/均线/破位/前低/前高/布林/量能/缺口/抄底/企稳（round59 新增，词表见 §3.3） | `index_technical`（MA/BOLL/RSI/KDJ）+ `support_levels`（支撑/压力位） |
| `general` | 兜底 | 不加采，直接诚实降级 |

**优先级 Priority**（复合命中时）：`valuation > product > risk > event > rotation > technical > allocation > general`。
> round59：`technical` 置于 `rotation` 之后、`allocation` 之前——支撑位问题常同时含
> 「买点/加仓」字样，若排在 `allocation` 之后会被抢走并再次退回泛泛而谈。

例：“低估+基本面+ETF映射”判 `valuation` 主路由 + `product` 子任务（拼 ETF 行），不压扁。
例（round59）：「这轮A股下跌的支撑位会是怎么样的？能不能买点」判 `technical`（非 `allocation`）。

**分类方法 Classifier**（混合两档）：
1. 关键词先判（零成本，§3 清单）；零命中直接 `general`（小模型第二档 deferred——v1 关键词覆盖已够，省一次 LLM 调用；后续模糊问复发再加）。
2. 存量关键词不改：sector/news 沿用 `routers/analysis.py:161-184`。

---

## 3. 新增关键词清单（收紧版）/ Keywords

### 3.1 `risk`：主+辅两档，禁单字碰瓷

* 主（命中即判）：`止损/止盈/回撤/最大回撤/对冲/避险/波动率/杠杆/爆仓/跌穿/平仓/套保`
* 辅（必须成对）：`风险+怎么办/如何应对/怎么控`、`防御+加减调仓`、`安全垫`
* 排除：`风险提示`（`general_analyst.md:3` 每篇都有）、`风险和适用场景`单出时不判，走 `general`。

### 3.2 `product`：必须带 ETF 锚，禁裸“买”

* 主：`买哪只/买什么ETF/ETF推荐/选哪只/代码是多少/成分股映射/规模≥/日均成交/流动性不足`
* 代码形态：6 位数字 + 上下文含 `ETF/买/换成` 才判；裸 6 位板块码（如 `881001`）不判。
* 排除：裸`买/卖/加仓`归 `allocation`；个股推荐红线（`general_analyst.md:11`）——product 只许 ETF。

### 3.3 `technical`：主+辅两档，禁与技术无关词碰瓷（round59 新增）

* 主（命中即判）：`支撑位/支撑/压力位/压力/阻力位/阻力/均线/破位/前低/前高/布林/BOLL/缺口/量能/抄底/企稳`
* 回撤族（**必须带位/到，裸「回撤」归 risk**）：`回撤位/回撤到/回踩到/反弹到`
  > `回撤` 已是 `risk` 主词（§3.1）且 `risk` 在优先级链更前，故 technical 不可再收裸
  > `回撤`，否则「回撤太大怎么办」会被误判 technical。改用带后缀形态消歧。
* 排除（**必须不判 `technical`**，防误伤既有意图）：
  * `最大回撤/回撤太大/止损/止盈/对冲/避险/波动率/杠杆` → `risk`（§3.1）
  * 「买点到了吗/能不能加仓」**无技术词** → `allocation`
  * 「风险提示有哪些」→ `general`
* 正反例（单测锁定）：`这轮A股下跌的支撑位会是怎么样的`→technical；
  `回撤到多少支撑`→technical；`上证均线在哪`→technical；
  `支撑位跌破要不要减仓`→technical（技术词胜出，**不得**被 `allocation` 抢走）；
  反：`回撤太大怎么办`→risk（不因含「回撤」判 technical）；`最大回撤是多少`→risk；
  `买点到了吗`（无技术词）→allocation。

---

## 4. 槽位定义 / Slots

### 4.1 基础槽（每次常驻，复用 60s 会话快照 `chat_session.py:170`）

`market_regime`、`market_sentiment`、`market_data`（指数）、`sector_momentum`、`hot_plates`、`sector_heat`、`fund_flow`、`news`。P3-G 约束不变：router 注入 ⊇ prompt 消费。

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

---

## 5. 受限 2 步 loop / Constrained Loop

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

SSE 事件沿用 `agents.md §6.1`，新增 `progress.phase`：`fetching_valuation` / `fetching_etf`（前端仅新增 phase 分支，不改消费逻辑）。

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
| 路由不变 method+path | ☐ | ☐ | 复用 `/llm-advice/stream` |
| 请求体 query/market/session_id | ☐ | ☐ | 沿用 `llm-chat-session.md` |
| SSE 新增 phase 可渲染 | ☐ | ☐ | `fetching_valuation/fetching_etf` |
| valuation 输出为结构表+as_of | ☐ | ☐ | 缺数整行待验 |
| ETF 码 ⊆ instruments | ☐ | ☐ | 负向单测锁定 |
| 全空降级不报正常 | ☐ | ☐ | 负向断言 |
| 加载/空/错误/慢数据四态 | ☐ | N/A | `AiAdvisor.vue` 补缺估值态 |
| `technical` 意图输出关键价位表 | ☐ | ☐ | round59 R09/R12，1200 字 |
| 支撑/阻力两族分行 + 方向标注 | N/A | ☐ | round59 R02b 负向 |
| 诚实拒答三件套（禁只写「无法确认」） | ☐ | ☐ | round59 R13 |
| disclaimer | ☐ | N/A | 沿用既有 |

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

## 10. 关键词正反例（单测锁定用）

* 正：`止损线设哪`→risk；`回撤太大怎么办`→risk；`买哪只银行ETF`→product；`512800现在能买吗`→product；`哪些板块低估`→valuation（优先于 product）。
* 反：`风险提示有哪些`→general；`买点到了吗`（裸买）→allocation；`881001怎么看`（裸板块码）→sector-analysis 既有链路，不判 product。
* round59 正：`这轮A股下跌的支撑位会是怎么样的`→technical；`回撤到多少支撑`→technical；`上证均线在哪`→technical；`支撑位跌破要不要减仓`→**technical**（技术词胜出，不被 `allocation` 抢走）。
* round59 反：`回撤太大怎么办`→risk；`最大回撤是多少`→risk（均不因含「回撤」判 technical）；`买点到了吗`（无技术词）→allocation。
