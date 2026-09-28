# LLM Report Follow-up / 综合研判追问 (llm-report/stream)

> A 端：`POST /api/v1/analysis/llm-report/stream` 扩展追问。复用 `ChatSessionStore`
>（LRU100 / TTL30min / SQLite24h / 历史10轮+8K截断），模式照抄 `llm-chat-session.md`
>（advice 多轮）。差异仅一处：本会话市场快照**会话内冻结**（首轮冻结，追问不重采），
> 而 advice 是 60s 复用后重采。

## 1. 概述 / Overview

**功能描述 / Description**: 首报生成后，用户可就报告内容追问（为什么判震荡/哪几个板块背离/风险点展开）。
请求携带可选 `query` + `session_id`；`done.metadata` 返回本轮生效 `session_id`。

**触发场景 / Trigger**: MarketReport 组件首报完成后追问；“基于最新数据重判”= 丢 session 走首报。

---

## 2. 端点定义 / Endpoint

```
POST /api/v1/analysis/llm-report/stream   （既有端点扩展，SSE 不变）
```

### 请求体 / Request Body

```json
{
  "symbols": null,
  "market": "A",
  "query": "为什么判震荡？",
  "session_id": "sess-abc123"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| symbols | array \| null | 否 | 既有语义不变 |
| market | string | 否 | 默认 `"A"`；追问跨 market 自动开新会话 |
| query | string \| null | 否 | 空/缺失=首报生成；非空=追问 |
| session_id | string \| null | 否 | None=新会话；无效/过期自动开新不报错 |

### SSE 事件流 / Event Stream（契约不变，done 扩展 metadata）

| 事件 | data | 变更 |
|---|---|---|
| progress | `{phase, message}` | 不变 |
| token | `{token}` | 不变 |
| done | `{full_text, metadata, disclaimer}` | **metadata 新增 `session_id`** |
| error | `{code, message}` | 不变 |

---

## 3. 会话语义 / Session Semantics

1. **首报**：`query` 空 → 全量 `build_full_context`，冻结 `ctx(indices/regime/sentiment/domestic_macro/as_of)` + 首报摘要进会话；
2. **追问**：命中 → 读冻结快照 + `render_history` 注入，**不重采**（mock 断言 0 调用）；
3. **prompt 槽**：`## 冻结快照（as_of=..）` + `## 对话历史` + `## 本轮问题` + 硬约束“只引用快照内数值，超出声明不得编数”；
4. **隔离**：`session_type=report`，与 advice/symbol 串话则开新；跨 `market` 自动开新；
5. **落库**：done 时 `user + assistant` 入内存 + SQLite upsert（失败不阻塞）；
6. **护栏**：历史 ≤10 轮、token ≤8K、内存 TTL 30min / SQLite 24h、LRU 100。

## Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches contract | ☐ | ☐ | POST path 不变 |
| Request body fields match | ☐ | ☐ | query/session_id 可选 |
| done.metadata.session_id 每轮返回 | ☐ | ☐ | 新=新 id，追问=原 id |
| 无效 id 自动开新不报错 | ☐ | ☐ | 回归保护 |
| 冻结期内追问 0 重采 | N/A | ☐ | 单测 mock 断言 |
| 空历史不注入对话槽 | N/A | ☐ | |
| Loading/streaming/done/error 四态 | ☐ | N/A | progress/token/done/error |

---

## 4. 报告数据段（round58）

> 状态：2026-09-28 实施落地。**接口 schema 不变**（请求/响应/SSE 事件均未改），
> 本节锁定的是 `_build_report_prompt` 生成的 prompt 数据段清单与**占位/口径纪律**——
> LLM 的报告内容质量完全由这些输入决定（R79/R80/M1-M7 同构缺数问题）。

### 4.1 新增/改造的 prompt 数据段

| Section 标题 | 数据源（后端符号） | 缺失时的规范输出 | R |
|---|---|---|---|
| `### 板块与风格` | `build_full_context` 的 `sector_momentum` + `hot_plates` | `（板块涨跌数据源暂不可用）`（整段，无 Top5 行） | R01 |
| `### 量能与宽度` | R06 `market_breadth`（up/down/flat/total/advance_ratio/total_amount）+ `market_sentiment` 的 `volume_ratio`/`margin_change` | 逐项 `（数据源暂不可用）`；**禁止**报 `上涨 0 家` / `共 0 家` | R02 |
| `### 资金行为` | `fetch_margin_change` + `_compute_fund_flow`（候选池口径）+ R08 `fetch_hsgt_history` | 逐项 `（数据源暂不可用）` + 「北向实时自 2024-08 起停止披露」声明 | R08 |
| `### 宏观政策` | `_extract_policy_news(enriched_news)` 关键词抽取 ≤5 条 | 零命中 → **整段省略**（不留空话柄） | R03a |
| `### 海外流动性` | FRED `global_liquidity.us_10y`（**唯一口径**） | 该段整体不出现 | R03b |

### 4.2 字段级断言

1. **板块段**：有值时 prompt 必须含真实 `sector_name` 与 `{change_pct:+.2f}%`；
   `change_pct` 缺失/非数值的行必须被跳过；`sector_momentum=[]` 时不得出现任何
   板块名或百分比（防编造）。
2. **量能段**：`total>0` 时必须渲染 `上涨 N 家` / `下跌 N 家` / `共 N 家` /
   `上涨占比 X.X%`；`total_amount` 缺失时该行单独占位，不得影响家数行。
3. **美债单口径**：`domestic_macro.bond_yields.us_10y`（akshare）**不得**出现在
   prompt；`global_liquidity.us_10y`（FRED）出现且仅出现 1 次，并附
   `以本段 FRED 口径为准`；`spread_bp`（中美 10Y 利差）保留并标 FRED 口径。
4. **政策段**：抽取命中时含条目标题；零命中时 prompt **不含**「宏观政策」四字。
5. **资金段**：`hsgt.rows` 非空时逐行渲染 `{date} 北向 X 亿 / 南向 Y 亿`；
   恒含「北向实时自 2024-08 起停止披露」字样。
6. **商品段（R07）**：英文/代码名经别名表归一——`WTI/布伦特/CL→原油`、
   `GC→黄金`、`SI→白银`、`HG→铜`；全部对不上时回退前 6 条；空列表 → 空串。
7. **模板纪律（R04）**：第 1 章的量能/家数条目为**条件式**；模板中免责话术
   「输入未提供」「暂无法验证」**各至多出现 1 次**（作为禁令被引用，不作为内容）。
8. **as_of（R09）**：`报告引用数据截至` 行拼接 指数快照 / 板块 / 宽度 / 港通
   各源时间（去重、`-` 连接）；全部缺失时不出现该行。

### 4.3 Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| 接口 schema 未变（SSE 事件/字段） | ☐ | ☐ | 本轮只改 prompt 内容 |
| 板块段含真实名+涨跌幅 / 全空占位 | N/A | ☐ | R01 负向：无编造涨跌幅 |
| 量能段缺失逐项占位、不报 0 家 | N/A | ☐ | R02 负向 |
| 美债 10Y 单口径（FRED） | N/A | ☐ | R03b 负向：双值必 FAIL |
| 政策段零命中整段省略 | N/A | ☐ | R03a 负向 |
| 商品别名归一（WTI→原油） | N/A | ☐ | R07 |
| 资金段含北向停更声明 | N/A | ☐ | R08 反幻觉 |
| as_of 多源拼接 | N/A | ☐ | R09，无源不标 |

**实现 / 验证 / 风险 / 范围外**
- 实现：`app/analysis/llm/reports.py`（新增 3 个格式化器 + `_build_report_prompt`
  扩 7 参 + R03b/R04 文案）、`app/routers/analysis.py`（`_extract_policy_news` +
  透传 + 冻结快照扩写）、`app/fetchers/fundamentals_fetcher.py`
  （`fetch_market_breadth`）、`app/fetchers/macro_fetcher.py`（`fetch_hsgt_history`）、
  `app/services/hub/_regime_sentiment.py`（2 个 hub 同步方法）。
- 验证：pytest 受影响 6 文件全绿；`check_routes` PASS（路由未变）。
- 风险：新增 2 次同步取数（宽度 5min 缓存 / 港通 24h 缓存，各 `wait_for` 15s 兜底），
  报告首字节延迟理论上界 +15s（串行）；两者均在失败时静默降级，不阻断报告。
- 范围外：个股级 moneyflow（P2-1 探针判不可行，暂缓立项）；北向**实时**数据
  （监管 2024-08 起停更，非技术问题）；报告 SSE 新增数据段事件（前端无需）。
