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
| `general` | 兜底 | 不加采，直接诚实降级 |

**优先级 Priority**（复合命中时）：`valuation > product > risk > event > rotation > allocation > general`。
例：“低估+基本面+ETF映射”判 `valuation` 主路由 + `product` 子任务（拼 ETF 行），不压扁。

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
