# AI 投顾 Gold Set 设计 / Advice Gold Set Design

> 状态：**设计稿（未实施）**。本文定义「怎么测」；§16 因 2026-10-02 矩阵评审拍板，
> 附带定义「怎么改」3 项（持仓槽 D1 / 跨资产 S8 / scope 守卫 D8）——**仍是方案，未动代码**。
> 被测对象：`POST /api/v1/analysis/llm-advice/stream`（`backend/app/routers/analysis.py:587`），
> 前端 `frontend/src/components/market/AiAdvisor.vue`（挂载于 `views/MarketAnalysis.vue:51`）。
> 背景轮次：round59（技术面/关键价位接线，commit `1fcd1c0`）、L1v2（意图路由，commit `95f3c31`）。
> 建议实施轮次：round60（C1-C4 修复 8 项 + L1/L2 gold set → P1 L3 → P2 抽读，拆分见 §16.9）。
> 决策留痕：§13.1（已决 4 项）/ §4.1（评审中自我修正 3 处）/ §15（探针原始取证）。

---

## 0. 一句话

把 AI 投顾拆成**三层可确定性判分**的断言（L1 意图路由 / L2 prompt 槽位 / L3 答案质量），
每层配一族 gold case；L1+L2 零网络零 LLM 进 CI 硬门禁，L3 真 LLM 跑离线带稳定性统计。
配套 8 项缺陷修复（§16，其中 D1/D2/D5/D8 为本文评审新增），按 4 个 commit 落地（§16.9）。

---

## 1. 现状取证（先证明缺口真实存在，不是预设立场）

| # | 事实 | 证据 |
|---|---|---|
| E1 | advice 链路的 gold case 数 = **0** | `backend/scripts/evals/` 只有工具层用例（`goldens/demo.jsonl` 10 条 `get_realtime_quote` 类），无一条 `classify_all` / `_build_advice_stream_prompt` |
| E2 | 意图断言共 **24 处 / 22 条去重问句**，但**全部走 `classify()` 单值**，0 处断言 `classify_all()` 的有序复合列表 | `tests/test_advice_p0a_slots.py:132-198`（3 valuation + 1 复合 + 2 risk + 2 product + 4 负例 + 3 other + 4 technical 正 + 3 technical 负 + 2 优先级）；`intent.py:103-106` 是唯一被测函数，`:80-100` 的 `classify_all` 生产调用方（`analysis.py:661`）**只被 1 条复合用例间接覆盖** |
| E2b | 覆盖缺口（实测）：event/rotation/allocation 各仅 1 条（`:162-164`），且 **0 条**覆盖英文、跨资产、持仓自指、对比多只、追问指代、HK/US/EU 市场维度 | 同上 + `intent.py:17-44` 词表全中文、`_has_product` 需 6 位码锚（`:50`） |
| E3 | evals 未接入 patrol 与 pre-commit | `scripts/patrol.py` 的 golden 层只有 `"L-golden": engine_golden_replay.py`；pre-commit 16 段无 evals 段（`docs/patrol-orchestration-plan.md:1.3` 显式声明 evals 不在范围） |
| E4 | 唯一运行时 advice 检查把 timeout / 任何异常判为 **PASS** | `scripts/verify_e2e.py:884-915`：`:909-910` 只查非空 + 5 个模板串缺席；`:913` `except requests.Timeout: check(..., True, ...)`、`:915` `except Exception: check(..., True, ...)` → **端点死了 / 45s 超时也全绿**。query 硬编码 `"当前A股市场怎么配置"`（`:892`），只覆盖 1 个意图 |
| E5 | 断言只到「非空」，未到「内容对」 | E4 只查 5 个模板串缺席 + 非空 |

**结论**：不是「gold set 太小」，是**三层里没有任何一层被断言过质量**。E2 的 24 处断言只锁住
「主意图分类结果」，从未锁住「分类对了之后 prompt 装了什么」「prompt 装的东西模型有没有照着答」，
且因全部用 `classify()` 单值，**复合命中的顺序与完整性无人看守**——而 `analysis.py:727` 的
`etf_map` 门恰恰依赖复合结果（`"product" in intents` 而非 `primary == "product"`）。

---

## 2. 目标 / 非目标

### 2.1 目标（DoD 口径）

1. **意图路由**：7 意图 + general 的分类结果（有序列表）被断言，含消歧与复合命中。
2. **槽位接地**：prompt 里出现/不出现哪些段、顺序、字数上限、`technical_intent` 分支差异被断言。
3. **答案质量**：真 LLM 回答被规则判「有没有编造（ETF 码/点位/持仓/不存在的数）、有没有混列支撑阻力、
   有没有空转拒答、有没有超字数」。
4. **失败诚实性**：数据源缺失时，期望答案是显式降级，不是兜底数据（AGENTS.md 反假完成条款）。

### 2.2 非目标（本轮明确不做）

- 不做 LLM-as-judge 的主观质量分（先做规则轨；judge 作为 P2 可选）。
- **gold set 本身不改产品代码**；但 §16 的 2 项配套修复（持仓槽 D1 / 跨资产 S8）经 §4 评审
  拍板纳入本轮，故本文档同时承担这 2 项的**方案**职责（仍只写方案，不实施）。
- 不覆盖其它 LLM 链路（`llm-report` / `sector-analysis` / `symbol-analysis`），尽管它们共用
  `general_analyst.md`，共用系统提示词这一事实只在 §8 记一条跨链路风险。

---

## 3. 三层分解与确定性边界

| 层 | 被测函数 | 确定性 | 依赖 | 判分方式 | 执行档 |
|---|---|---|---|---|---|
| **L1 意图** | `classify_all(query)`（`app/analysis/intent.py:80`） | 完全确定（纯 substring） | 无 | `exact_match` 有序列表 | T0 每次提交 |
| **L2 槽位** | `_build_advice_stream_prompt(query, ctx)`（`app/analysis/llm/reports.py:1501`） | 完全确定（纯拼接） | fixture ctx | 段存在/缺席 + 顺序 + 字数 + 不变式 | T0 每次提交 |
| **L3 答案** | `run_stream_with_cache` 的 `full_text` | 非确定（温度 0.5，`registry.py:32`） | 真 LLM + 8h 结果缓存 | 规则轨（正则/集合/计数） | T1 夜间 / 发版前 |
| L4 SSE/多轮（扩展） | `_sse_stream` + `ChatSessionStore` | 确定（mock LLM 后） | mock | 事件序列 | T0（可选） |

**为什么 L1/L2 是主战场**：L3 的非确定性会逼出「重跑三次看方差」的维护成本，而 L1/L2 恰好是
round59 病灶的真实成因（M2「问支撑位答板块轮动」= `technical_intent` 没置位；
`sess-1ef0` ETF 码幻觉 = `etf_map` 空守卫缺失）。这两层零成本、可进硬门禁、能直接防回归。

**L3 为何仍要做**：分类对、槽位对，模型仍可能不照着答。round59 的 R12/R13/R14 就是针对
「模型不照 prompt 答」的三条硬约束——但**至今没有一条断言它们被遵守**。

---

## 4. 同类产品场景矩阵（领域知识归纳 → 本产品映射）

> **可信度声明**：本节 S1-S10 的产品形态归纳是**推断**，来源为公开形态常识，**未抓取真实用户问句**。
> 「本产品现状」一列已全部改为实测/`file:line` 可查（2026-10-02 评审中逐条补验，原稿三处偏轻/偏重，见 §4.1 修正记录）。
> 每行右侧的「期望答案形态」是本节核心产出——它区分「数据能答」与「只能诚实降级」，决定 gold case 的期望值写法。

| # | 产品形态 | 代表 | 用户典型问法（archetype） | 依赖能力 | 本产品现状（实测） | **gold 期望形态** | 评审决议 |
|---|---|---|---|---|---|---|---|
| S1 | 全能搜索型 | 同花顺 i问财 / 东财爱问 | 「roe>15 且 pe<20 的票」「今天涨停的板块」 | 结构化条件筛选 | ✗ **全产品都没有**：`/market/search` 是名称/拼音 `ilike`（`market.py:70-87`），非条件筛选；投顾 prompt 只有板块涨跌榜 15 条（`llm_context.py:80`） | `degrade` + 给筛选方法 | **不做**（若做是独立项目，gold 不假装它存在） |
| S2 | 行情诊断型 | 同花顺 / 东财个股页 | 「这只票 MACD 金叉了吗」 | 单标的技术指标 | ✓ 独立链路 `/symbol-analysis/stream`（`analysis.py:961`） | 引导到标的分析 / 说明边界 | **锁定** |
| S3 | 组合诊断型 | 雪球组合 / 天天基金 | 「我的组合有什么问题」「今天为什么跌」 | 持仓级归因 | ✅ **已修**（C4 `9910d51`）：前端注入 `context.portfolio`（3 字段），全链路实证通过。修前：槽线上恒空，服务端数据齐全却纯前端未传 | `answer`（归因深度受 §5 行数上限约束） | **已落地**（§16.1 + §19） |
| S4 | 估值比较型 | 集思录 / 韭菜公社 | 「哪些低估」「历史分位多少」 | 估值分位 + 比价 | ✓ 5 指数（`analysis.py:700-701`，渲染 `[:6]` `reports.py:1631`）+ 8 板块（`reports.py:1642`）；**结论列恒「待验」**（`valuation.py:68-69` + 从不传 roe） | 结构表 + `as_of` + 结论列；缺数整行「待验」 | **锁定**；但见 D8 |
| S5 | 事件解读型 | 财联社 / 东财快讯 | 「降息利好哪些板块」 | 事件→板块映射 | ✓ news 5 条（`reports.py:1546`）；**0 条断言「不得引申未给出的新闻」** | 基于给定条目标注影响 | **锁定** |
| S6 | 择时/技术型 | 雪球大V / TradingView | 「支撑位在哪」「要不要抄底」 | 关键价位 + 触发条件 | ✓ round59 `support_levels`；**但仅 000001/000300 两个指数**（`_technical.py` 默认符号） | 价位表 + 触发/失效条件；无数据走 R13 三件套 | **锁定** |
| S7 | 调仓/配置型 | 持牌智能投顾 | 「现在该配多少红利」 | 目标权重 + 偏离度 | △ 引擎有确定性分配能力（`app/engine/`），投顾链路 `include_portfolio=False`（`analysis.py:621`） | **指向 `/portfolio/design-async`**，不报精确权重 | **锁定**（符 README「LLM prose is decoration on top of engine output」） |
| S8 | 跨资产/风格 | 各类智能投顾 | 「黄金和原油配哪个」「成长还是价值」 | 多资产配置 | ✅ **已修**（C3 `9aa4229`）：`include_commodities=True` + 显式注入 + 复用 `_format_commodities`，空槽整段省略。**刻意不加新意图**（仍是 `general`，商品按基础槽注入，故 L1 基线不动）。`global_liquidity` 仍采了不注入（I-2，未修） | `answer`（商品段有值）/ `degrade`（空窗） | **已落地**（§16.2 + §19） |
| S9 | 对话式追问 | ChatGPT 类 | 「那它估值呢」「换成银行的呢」 | 指代消解 + 上下文继承 | ✓ `chat_history` 10 条 / 8K（`chat_session.py:29-31`）；**0 条断言「不得与首轮矛盾」** | 继承首轮口径 | **锁定** |
| S10 | 风险/合规 | 全部持牌产品 | 「能亏多少」「爆仓风险」 | 风险量化 | △ `risk` 意图无专属槽；`general_analyst.md:6` 已强制「必须说明风险和适用场景」，但 **0 条断言模型照做** | 定性风险 + 适用场景 | **锁定** |
| **S11** | **归因（新增）** | 东财「今日异动」/ 雪球复盘 | 「今天大盘为什么跌」「是资金还是消息面」 | 事件+资金+板块交叉归因 | △ **能力已具备**（news 5 + 板块涨跌 10 + 热点 8 + 资金流向 1 行）但 event/rotation 之外**无任何断言** | 基于已注入槽归因，区分「可归因/不可归因」 | **新增**（最高频日常场景） |
| **S12** | **能力边界（新增）** | 全部 AI 产品 | 「你能做什么」「这个数据准吗」「你会不会编数字」 | 自我边界声明 | △ 无断言。且 README 反幻觉五点（`README.md:20-24`）是产品存在理由 | 诚实声明覆盖范围 + 缺数纪律 | **新增**（信任建立/崩塌点） |

### 4.1 评审中的三处自我修正（四问法纪律留痕）

| 原稿断言 | 修正后 | 修正依据 |
|---|---|---|
| S1「只有板块涨跌榜 15 条」 | **全产品无条件筛选能力**（`/market/search` 是名称 ilike） | 读 `market.py:70-87` |
| S8「✗ 跨资产」笼统 | **产品在定位内、投顾链路装死**（README 六类资产 vs `include_commodities=False`）→ **已于 C3 `9aa4229` 修复** | 读 `README.md:7` + `analysis.py:623` |
| 「D1 需同步改 `LLMAdviceRequest` 契约」 | **纯前端改动**：契约已定义 `context` 对象透传（`llm-chat-session.md:29,38`），后端已在读 `context.portfolio`（`analysis.py:652`） | 读契约 + 路由 |

### 4.2 矩阵产出的 4 条设计决定

1. **「诚实降级」必须是一等公民期望值**。S1 一族（因子条件筛选）**永久**答不了；S3/S8 经 §16 修复后
   转 `answer`。gold set 若只测「答对」，会把 S1 判成失败并驱动 AI 去编数据——与 AGENTS.md 反假完成
   条款相反。故期望值分两型：`answer`（须有数据支撑）与 `degrade`（须显式声明边界），后者同样算 pass。
2. **S4 是唯一「必须出表」的族**，因此 `as_of` / `verdict` 列的断言最严。但注意 S4 与 D8 的交叉：
   非 A 股标的的估值问题也会命中 valuation 意图并拉 A 股表 → 需 scope 守卫（§8 D8）。
3. **S9 使多轮成为一等场景**：`classify_all` 对追问（「那它贵不贵」）照样命中 valuation，
   但**槽位是新的**——所以 L2 gold case 必须带 `session_id + chat_history` 维度。
4. **S11 是最高频且最被忽视的场景**：能力已具备（新闻/板块/资金/热点四槽齐备），却零断言。
   本轮 gold set 必须新增 `attribution` 族，否则「今天为什么跌」这类日常问题永远无人看守。
5. **S12 是产品的信任契约**：README「Why this exists」把幻觉列为产品存在的五个理由之一
   （`README.md:20-24`）。故 L3 负向用例（禁编 ETF 码 / 禁编点位 / 禁空转拒答）**不是可选增强，
   而是核心承诺的验收**——此立场须写进 §10 门禁论证，避免将来被当「加分项」砍掉。

---

## 5. Case Schema（在 `scripts/evals` 现有 jsonl 上扩展，不另立格式）

现有格式（`scripts/evals/harness.py:28-36` + `scorers/rule_scorer.py:90-107`）：
`{id, type, question, tool|steps, arguments, expect, notes}`，5 类题型（quote/factor/format/refusal/multi_step）。

本方案**新增 4 类 advice 题型**，沿用同一条 jsonl 管道（`load_goldens` 直接可读）：

```jsonc
{
  "id": "I-20",
  "type": "intent",                    // 新增：intent | prompt | answer | sse
  "question": "支撑位跌破要不要减仓",
  "market": "A",                       // 新增：对应 LLMAdviceRequest.market
  "ctx_fixture": "fx/tech_warm.json",  // 新增：L2/L4 用，fixture 路径（见 §9）
  "session": {                         // 新增：L4 多轮用
    "history": [{"role": "user", "content": "上证现在什么位置"}],
    "frozen_ctx": "fx/general_warm.json"
  },
  "expect": {
    // intent 型
    "intents": ["technical", "allocation"],   // 有序，与 classify_all 严格相等
    "primary": "technical",
    // prompt 型
    "sections_present": ["## 技术面", "### 关键价位（支撑与阻力分族列出，不得混列）"],
    "sections_absent":  ["### 行业轮动分析框架", "### 资金流向"],
    "must_include":     ["控制 1200 字以内", "落在现价上方的回撤位是阻力不是支撑"],
    "must_not_include": ["SNAPSHOT_SHOULD_NOT_APPEAR"],   // 死槽防泄漏
    "order": ["## 市场背景", "## 技术面", "## 实时行情", "### 关键价位（支撑与阻力分族列出，不得混列）"],
    // answer 型
    "answer_mode": "degrade",                 // answer | degrade（见 §4 决定 1）
    "must_contain_any": ["缺哪些数", "去哪里看", "判断规则"],   // R13 三件套
    "must_not_contain_any": ["无法确认", "暂无数据"],
    "codes_forbidden": ["515220", "159766"],  // 表外 ETF 码（sess-1ef0 实证过的两个）
    "codes_allowed": ["512800", "510300"],
    "max_chars": 1200,
    "min_support_rows": 1, "min_resist_rows": 1,
    "no_mixed_family_row": true                // 支撑/阻力不得同行
  },
  "severity": "block",                 // block | warn | xfail（§8）
  "source": "contract §3.3",           // contract§X | 同类S4 | round59-R13 | 线上 sess-xxxx | probe-2026-10-02
  "notes": "round59 正例，防 allocation 抢走 technical"
}
```

**为什么扩字段而不是新建 harness**：`_resolve_path`（`rule_scorer.py:20-33`）只支持列表下标，
不支持 dict-key 下标，advice 的 prompt 是**长字符串**、answer 是**自由文本**，两者都不适合
field_path 表达。所以新增 4 个 scorer 而非复用 `score_quote`。

---

## 6. 用例分布与样例

### 6.1 分布（L1 **143** / L2 26 / L3 30 / L4 10 = **209** 条）

> **L1 计数为实测修正**：初稿估 60 条，实际落地 143 条（分布见下表 + §17 变异测试记录）。
> 差额全部来自变异测试暴露的覆盖缺口，不是注水——每条新增用例都由一次「删掉规则但无人报警」
> 的实测驱动。design-checklist 第 2 项（证据链）要求数量结论有实测支撑，此处即。

| 层 | 子族 | 条数 | 难度 |
|---|---|---|---|
| **L1 intent（实测 143）** | `keyword` 每词一条 | **70** | 易 |
| | `disambig` 消歧对 | 23 | 中 |
| | `single` 单意图正例 | 14 | 易 |
| | `composite` 复合命中（有序列表） | 8 | 中 |
| | `negative` 越界/无关 | 6 | 易 |
| | `gap-*` 能力缺口（en/hkus/cross/portfolio/compare/anaphora） | 22 | 难 |
| L2 prompt | 槽位存在/缺席矩阵（15 槽 × 满/空/半空） | 13 | 中 |
| | technical 分支差异（含/不含 关键价位、资金流向、轮动框架、1200/800） | 6 | 中 |
| | **商品槽（S8 修复后新增）** | 3 | 中 |
| | **scope 守卫（D8 修复后新增）** | 4 | 难 |
| L3 answer | 正例（S4 估值表 / S6 价位表 / S10 风险定性 / **S11 归因** / **S12 能力边界**） | 14 | 中 |
| | **负例（假完成猎手）** | 12 | 难 |
| | 诚实降级（S1 / 修前 S3+S8） | 4 | 中 |
| L4 sse | 事件序列 / phase / session_id 回传 / 缓存路径 / 错误帧 | 10 | 中 |

其中 **25 条** `source` 以 `gap-`/`D` 开头（已知缺口，含 D1/D8 触发条件），
**25 条**来自契约 §2/§3（迁移 `test_advice_p0a_slots.py:132-198` 的既有用例）。
「唯一触发词」是 `keyword` 族的写作约定——变异测试第一轮发现大量用例里目标词被同类词
兜住（删掉目标词结果不变），故每个词至少要有一条**只有它能命中**的用例。

### 6.2 L1 样例（全部为 `classify_all` 实测输出，非推断）

探针命令见 §12 §D1，结果逐条如下（`python -c "from app.analysis.intent import classify_all; ..."`）：

| id | 问句 | 期望 `classify_all` | 来源 |
|---|---|---|---|
| I-01 | 哪些板块低估 | `["valuation"]` | contract §10 |
| I-03 | 红利是不是价值陷阱 | `["valuation","rotation"]` | 新增（价值 命中 rotation 词表，intent.py:34） |
| I-04 | 恒生科技贵不贵 | `["valuation"]` | 新增（贵 → valuation，intent.py:19） |
| I-11 | 回撤太大怎么办 | `["risk"]` | contract §10 |
| I-15 | 当前市场风格偏向成长还是价值？是否该调仓？ | `["rotation","allocation"]` | **UI 占位文案本体**（AiAdvisor.vue:25） |
| I-20 | 支撑位跌破要不要减仓 | `["technical","allocation"]` | contract §10 round59 正 |
| I-24 | 风险提示有哪些 | `[]` → general | contract §10 反 |
| I-25 | 881001怎么看 | `[]` → general | contract §10 反 |
| I-27 | 哪些板块低估？买哪只ETF？ | `["valuation","product"]` | test_chat_session_endpoint.py:209-218 |
| I-29 | What is the support level of SSE index? | `[]` → general | **缺口**（词表纯中文） |
| I-30 | 我的持仓该减仓吗 | `["allocation"]` | **缺口**（分类对但 portfolio 槽空，见 D1） |
| I-31 | 黄金和原油现在配哪个 | `[]` → general | **缺口 S8**（实测落 general） |
| I-32 | 港股科技和红利怎么选 | `[]` → general | **缺口 S8** |
| I-33 | 它估值贵不贵 | `["valuation"]` | **缺口 S9**（追问无指代，分类照样命中） |
| I-34 | 512880和512890哪个更稳 | `[]` → general | **缺口**（6 位码无 `_CODE_CTX_KWS` 锚，intent.py:50） |

**I-29/I-31/I-32/I-34 的期望值一律是 `[]`（general）而非"正确意图"**——gold set 锁的是
**当前真实行为**，不是理想行为。理想行为作为 §13 的词表扩充提案单列，不混进 gold set
（否则 gold set 永远是红的，没人会看）。

### 6.3 L2 样例（三条实测 prompt 的段序）

探针：给定同一份满 ctx，分别置 `technical_intent` / `valuation_intent` / 都不置。

| 段 | general | valuation | technical |
|---|---|---|---|
| `## 对话历史` | 依 session | 依 session | 依 session |
| `## 市场背景` | ✓ | ✓ | ✓ |
| `## 技术面` | ✓（**无条件**，reports.py:1531） | ✓ | ✓ |
| `## 实时行情` | ✓ | ✓ | ✓ |
| `## 近期资讯` / `## 持仓信息` | 依数据 | 依数据 | 依数据 |
| `### 行业板块涨跌` / `### 热点板块` / `### 板块热力` | ✓ | ✓ | ✓ |
| `### 关键价位` | — | — | ✓（reports.py:1601-1602） |
| `### 资金流向` | ✓ | ✓ | **✗**（reports.py:1606 被 technical 抑制） |
| `### 估值快照` / `### ETF 映射` | 依数据 | 依数据 | 依数据 |
| `### 行业轮动分析框架` | ✓ | ✓ | **✗**（reports.py:1668） |
| 字数上限 | 800 | 800 | **1200** |

**三条实测发现的断言点**：

- `## 技术面` 在**非 technical 意图下也注入**（`reports.py:1531` 无条件调用）→ L2 断言
  「general 意图的 prompt 里也有 MA/RSI/KDJ」——这是数据不是 bug，但要冻结，否则将来
  有人「优化」成 technical-only 会静默改变 general 回答的信息量。
- 空 ctx + `technical_intent=True` → prompt **既无价位数据也无占位标记**，却要求
  「1. 先给关键价位表」（实测 311 字，见 §12 §D1 输出）。这是**全套 gold case 里
  幻觉风险最高的一格**，列为 L3 头号负例。
- `support_levels` 形状必须是 `{symbol: {...}}`（`_technical.py:239-257`）。传成单指数 dict
  时 `_format_support_levels` 遍历字段名、`rows==0` → **整段静默消失**（实测），
  不报错不告警。L2 必须有一条形状失配用例钉住这个降级行为。

---

## 7. 冻结不变式（12 条，带实测证据）

L2 里「断言出现什么」易、「断言不出现什么」难。以下为**当前真实成立、后续不得回退**的不变式：

| # | 不变式 | 证据 |
|---|---|---|
| I-1 | `market_snapshot` **永不出现**在 advice prompt | `analysis.py:239-241` 写入，`reports.py:1510-1658` 无 `ctx.get("market_snapshot")`；实测三分支均 False |
| I-2 | `global_liquidity` / `domestic_macro` 永不出现 | `llm_context.py:195-226` 采集（advice 未关这两个开关）但 prompt 无消费；实测 `4.1` / `50.1` 均未出现 |
| I-3 | `technical_intent` ⇒ 无「行业轮动分析框架」**且**无「资金流向」 | `reports.py:1606`, `:1668` |
| I-4 | 非 technical ⇒ 两段都在 **且** 字数 800 | 实测段序表 |
| I-5 | technical ⇒ 字数 1200 + R13 三件套 + R14 硬约束 | `reports.py:1687-1695` |
| I-6 | `## 持仓信息` 只渲染 ≤5 行、权重为 `%` 格式 | `reports.py:1549-1556`；实测 `- 沪深300ETF(510300): 30.0%` |
| I-7 | 估值空 + `valuation_intent` ⇒ 出现「估值数据暂不可用（as_of 缺失）」 | `reports.py:1648-1651`；实测命中 |
| I-8 | `etf_map` 空 + `valuation_intent` ⇒ 出现「无 ETF 映射表：不得编造任何 ETF 代码」 | `reports.py:1658-1662`；实测命中 |
| I-9 | prompt 内 ETF 码 ⊆ `SECTOR_ETF_MAP` | `analysis.py:727-735`；`test_chat_session_endpoint.py:218` 已锁 `159766` 缺席 |
| I-10 | 估值结论列**恒为「待验」** | `engine/valuation.py:68-69`（`roe is None → 待验`）+ advice 从不传 roe（`analysis.py:693,716`） |
| I-11 | 支撑族全在现价下方、阻力族全在上方、跨族不混列、跨桶不重值 | `engine/support_levels.py:230-241,312-333,384-391`；实测 000001 渲染 支撑 3741.11/3827.66、阻力 3905.64/3881.13 |
| I-12 | Fib 不可用时三档不输出 + 出人话原因 | `support_levels.py:336-355` + `reports.py:1412-1417,1487-1492`；实测 `no_upleg_brackets_price` → 「未识别到仍覆盖现价的有效上涨段」 |

**I-10 值得单独强调**：v1 无 ROE 源，所以「低估/陷阱/合理」三个结论**永远不可能出现**，
估值表的「结论」列恒为「待验」。gold set 若不把这条冻结，将来有人接上 ROE 会以为测试坏了——
而这恰恰是**期望的能力升级**，届时应同步改契约与本条。

---

## 8. 已知缺陷 → xfail 负向用例（先记录，不在本轮修）

`severity: "xfail"` 语义：**当前必然失败**，一旦变绿说明缺陷被意外修掉/行为变了，需人工确认。
xfail 不计入 pass_rate，但计入「缺陷未修」看板。

| # | 缺陷 | 证据 | gold case 形态 | 本轮处置 |
|---|---|---|---|---|
| **D1** | **`##持仓信息` 槽线上恒空**：前端从不发 `context.portfolio`，但 UI 文案承诺「结合…您的组合」 | `AiAdvisor.vue:117` 只发 `{query, market}`；全前端 grep 无 `context.portfolio`；`analysis.py:652` 已支持读取；契约已定义 `context` 透传（`llm-chat-session.md:29,38`） | 修复前 L3-xfail；修复后转 `answer` 族 | **已修** C4 `9910d51`：前端注入 3 字段；全链路实证 + 5 条前端用例 |
| **D2** | 冷缓存 technical：**无数据无占位、仍要求出价位表** | 实测 311 字 prompt（§6.3、§15.2） | L3-xfail：`must_not_contain_any` 形如 `\d{4}\.\d{2}` 的点位数字（除非来自 fixture） | **已修** C3 `9aa4229`：三档指令分流；变异 2/2 killed |
| **D8** | **valuation 意图对非 A 股标的答非所问**：「恒生科技贵不贵」「黄金贵吗」命中 `valuation`，但 `analysis.py:700-701` 硬编码 5 个 A 股指数 → 给港股/黄金问题端上一张 A 股估值表 | `intent.py:19`（`贵`/`便宜`）+ `analysis.py:673,700-701`；实测 I-04「恒生科技贵不贵」→ `["valuation"]`。**静态探针已确证 4/4**（港股/黄金/美股/标普均被注入沪深300等 5 行，A 股对照组正常），scope 声明行当前不存在 | L2-xfail：非 A 股标的 + valuation ⇒ 期望出现 scope 声明行 | **已修** C3 `9aa4229`：槽无关 scope 声明行；静态探针 4/4（§18）；变异 2/2 killed |
| D3 | `fetching_etf` phase 契约有、代码无 | `advice-valuation.md:180,257` vs `analysis.py:761-765` 仅 1 个 phase | L4-xfail | **已处理** C1 `fba61d5`：删契约（零 I/O 不配 progress，理由入契约 §6） |
| D4 | `done.cached` 被 `_sse_stream` 丢弃 → 前端「（缓存）」徽标不可达 | `analysis.py:122-131` 未透传 `cached`；`AiAdvisor.vue:97` 已在读 `m.cached` | L4-xfail | **已修** C4 `9910d51`：`_sse_stream` 透传；SSE 边界双向用例 |
| D5 | `etf_map` 空守卫挂在 `valuation_intent` 而非 product | `reports.py:1658` | L2-xfail：product 意图 + 空 map ⇒ 无守卫文案（= 允许编码的窗口） | **已修** C2 `1654fc1`：`product_intent` flag + 守卫条件；变异双层 killed |
| D6 | §5「受限 2 步 loop（2 个白名单工具）」完全未实现 | `advice-valuation.md:157-174` vs `analysis.py:673-735` 硬编码 if | 文档-代码漂移登记（非 case） | **已处理** C1 `fba61d5`：§5 标注 v1 未实现并指明真实调度位置 |
| D7 | advice 运行时检查把异常 / 超时判 PASS | `verify_e2e.py:913,915` | 登记为「E4 需修」 | **已修** C4 `9910d51`：重试一次后判 FAIL；meta-test 走 AST 守门禁，变异 4/4 |

**D1/D2 仍是本文档最重要的两条产出**：都是「测试全绿、功能假」的样本——D1 让 UI 承诺落空、
D2 直接邀请模型编点位。两者都**不能靠现有 24 处 `classify()` 断言发现**。
**D8 是评审新增**：它与 S8 同源——投顾链路只装 A 股数据，却对全资产提问照答不误。
**D5 是评审新增**：与 `sess-1ef0` ETF 码幻觉同源，且比它更隐蔽——当时修的是「有表时禁裸写」，
漏了「无表时也禁编」这条守卫挂在错误的意图上。

---

## 9. Fixture 工程（L2 的前置依赖）

`ctx_fixture` 是 JSON 文件，放 `backend/scripts/advice_evals/fixtures/`，命名 `<intent>_<warm|cold>.json`：

| fixture | 内容 | 用途 |
|---|---|---|
| `general_warm.json` | 满槽（含 `market_snapshot`/`global_liquidity`/`domestic_macro` 诱饵值） | I-1/I-2 死槽防泄漏 |
| `tech_warm.json` | `technical_intent=true` + 2 指数 `index_technical` + `support_levels`（000001 有 Fib / 000300 Fib 不可用） | I-11/I-12、支撑阻力分族 |
| `tech_cold.json` | 同上但两槽为空 | D2 冷缓存 |
| `shape_mismatch.json` | `support_levels` 传成单指数 dict（非 `{symbol:...}`） | §6.3 静默降级 |
| `val_warm.json` | `valuation_intent=true` + 5 指数 + 8 板块估值（verdict 全「待验」） | I-10、估值表格式 |
| `val_degraded.json` | `valuation_intent=true`，两估值槽空、`etf_map` 空 | I-7/I-8 |
| `session2.json` | `chat_history` 非空 + `frozen_ctx` | S9 多轮 |

**两条硬规则**（否则 gold set 会自己造假）：

1. **必须清 LLM 结果缓存**：`_REPORT_CACHE` TTL 8h（`llm/cache.py:11`）、key 含 prompt sha（`:13-20`）。
   L3 重跑若不清缓存，第二次全部命中缓存文本 → 「稳定性 100%」是假的。照抄
   `tests/conftest.py:174-176` 的清理逻辑。
2. **fixture 必须自证真实**：每个 fixture 顶部带 `provenance`（取数时间/来源/脚本命令）。
   手写的假数值若被模型当成真引用，gold set 反而在训练幻觉。

---

## 10. 评分与门禁接入

### 10.1 三档严重度

| severity | 含义 | 阈值 |
|---|---|---|
| `block` | 破坏既有能力/放行幻觉 | 100% |
| `warn` | 质量退化但可用 | ≥95% |
| `xfail` | 已知缺陷（D1-D7） | 不计分 |

### 10.2 门禁替换制合规（AGENTS.md 2026-09-09 硬约束）

> 「新增任何门禁必须说明**替代/合并哪一现有段**，16 段为硬上限」。

**本方案不新增段**，理由：

- L1/L2 是 **`test_advice_p0a_slots.py` 的自然延伸**——该文件已持有 24 处意图断言
  （`:132-198`）与 P3-G 槽位覆盖 AST 检查（`:92-124`）。gold case 落地为
  `tests/test_advice_goldset_l1_l2.py`，属既有测试族扩容，不构成新门禁段。
- 命名收敛为既有 §⑬「测试数基线」的一部分，不新立基线凭据。
- L3 真 LLM **不进 pre-commit**（网络 + 费用 + 非确定性），只进 patrol 的**可选**层，
  且 patrol 已有 `L-golden`（`engine_golden_replay.py`）这一「快照 diff 型」范式；
  advice L2 复用同一范式而非另立一层。

### 10.3 执行档

| 档 | 内容 | 触发 | 预计耗时 |
|---|---|---|---|
| **T0** | L1 + L2（零网络、零 LLM） | pre-commit / `patrol --diff` | <3s |
| **T1** | L3 子集 26 条 × 3 重复（真实 LLM） | 夜间 / 发版前 | ~10min |
| **T2** | L3 全量 + L4 + 人工抽读 | 每周 / 改动 `reports.py`/`intent.py` 后 | ~30min |

**L3 稳定性口径**：同一 case 跑 3 次，规则评分 3 次全过才算 pass；出现分歧则报「不稳定」
而非「失败」（温度 0.5 下规则如字数边界可能抖动，需人工看）。

---

## 11. 与既有资产的关系

| 既有 | 关系 |
|---|---|
| `tests/test_advice_p0a_slots.py:132-198`（24 处 `classify()` 断言） | gold set L1 **迁移**它们（`source: "contract §10"`），并**改用 `classify_all()` 断言有序列表**——两处断言不同函数，不算重复维护 |
| `tests/test_advice_p0a_slots.py:92-124`（P3-G 槽位覆盖） | 保留为不变式单测，gold set 只补「顺序/分支/负向」 |
| `tests/test_report_quality.py:327-391`（R12/R13，prompt 侧） | 保留；gold L3 补 **answer 侧**（模型是否照 prompt 做）——两者不重叠 |
| `scripts/evals/`（工具层 harness，`load_goldens` + 5 scorer） | 复用 `load_goldens`；**新增 4 scorer、不改**既有 5 类题型，避免污染 agentic 评测 |
| `scripts/evals/goldens/*.jsonl`（demo 9 + quotes 5 + round51-expansion 34 = **48** 条） | 不动；advice gold 放独立目录 `scripts/advice_evals/goldens/` |
| `advice-valuation.md §10` | 词表扩到 14 条（补缺口族）后成为 gold 的 `source` |

---

## 12. 设计清单映射（`docs/design-checklist.md` 8 项）

| # | 项 | 本设计状态 |
|---|---|---|
| 1 | 可行性探针（D1） | ✅ 已做：`classify_all` 16 问句实测 + `_build_advice_stream_prompt` 4 种 ctx 实测（输出见 §6.2/§6.3 与本文档会话记录）。探针纯函数、无网络、零副作用，无需 60s 间隔 |
| 2 | 证据链（D2） | ✅ 每条不变式/缺陷均带 `file:line` 或实测输出；**未落任何无实测的量化结论**（教训见 memory `warmup-两阶段复活-2026-09-29`：前几轮三次纠正错误估计） |
| 3 | 验证窗口（D3） | ⚠️ **待补**：L3 真 LLM 判定涉及行情真值，需在交易日 9:30-11:30 / 13:00-15:00 复测一轮；非窗口跑的 L3 结果打「待交易时段复测」，不得作为通过依据 |
| 4 | 非兜底数据 | ✅ §7-I-10（结论列恒「待验」）与 §9 硬规则 2（fixture 自证真实）直指此项 |
| 5 | 真实调用点 | ✅ L1/L2 直接调生产函数（非 mock 副本）；L3 走真实端点 |
| 6 | 四态 UI | ➖ 不适用（纯测试资产，无 UI 改动） |
| 7 | 复杂度审计 | ✅ T0 零 I/O；T1/T3 限流与缓存清理已列（§9 硬规则 1、§10.3） |
| 8 | 已知问题模式 | ✅ 格式断言→空槽口径统一；mock 理想输入→fixture 强制冷/热两态；契约盲区→§8 D3-D6 漂移登记 |

**四问法自审（对本文档每条结论）**：

- 「advice 无 gold case / 无 CI 接入」= **事实**（E1/E3，grep 可查）。
- 「L1/L2 是主战场」= **推断**，支撑：round59 两条病灶的成因都在 prompt 组装层（`technical_intent` 未置位、`etf_map` 守卫缺失），非 LLM 随机性；反例：R13 三件套被模型忽略**只有** L3 能发现 → 故 L3 不可省。分级：**合理**。
- 「同类产品 12 类形态」= **推断（领域知识）**，无实测支撑 → 分级：**已人工审并拍板**
  （2026-10-02 评审，决议见 §4 最右列；S1/S3/S8 三行经补验修正后定案，S11/S12 新增）。
- 「130 条」= **推断**，无历史吞吐数据 → 分级：**部分合理**，需 T0 落地后按实际耗时调整。
- 「D8 是评审新增的独立缺陷」= **推断**（代码路径可查，但未在真服务上跑出「港股问题端上 A 股表」
  的实况）→ 分级：**部分合理**，修复前需一次线上复现取证。

---

## 13. 评审已决（2026-10-02）与剩余待决

### 13.1 已决（7 项，决议已写入本文）

| 议题 | 决议 | 落点 |
|---|---|---|
| S8 跨资产是否属投顾职责 | **纳入职责，补槽位**（不加新意图，按基础槽无条件注入） | §16.2 |
| S3 / D1 持仓槽 | **本轮修**（纯前端 3 行） | §16.1 |
| 是否新增 S11 归因 / S12 能力边界 | **新增** | §4 表 + §6.1 分布 |
| gold 锁当前行为还是目标行为 | **锁当前行为** | §6.2 缺口族期望值写法 |
| **D2** 冷缓存 technical | **本轮修**（三档指令按槽位可用性分流） | §16.4 |
| **D3/D4/D5/D7** 4 条小缺陷 | **本轮修**；D4 实现、D3 删契约、D5 修守卫条件、D7 重试后判 FAIL | §16.5-16.7 |
| **S1** 因子条件筛选 | **立项**（独立项目），本轮 gold 期望标 `degrade` | §4 S1 行 + §6.2 |

### 13.2 实施期需监控的风险（非待决）

1. **单轮 8 项修复 + 130 条 gold case 偏大** → 拆 4 commit（C1-C4）+ 2 阶段，见 §16.9。
   超时优先砍 P1/P2，**不可砍 C1-C4**（缺陷修复 ≠ 测试资产）。
2. **C3 是风险最高项**：同时动 prompt 生成的三处分支（technical 三档 / scope 行 / 商品段）。
   建议该 commit 单独 review。
3. **验证窗口**：L3 真 LLM 判定须在交易日 9:30-11:30 / 13:00-15:00 复测一轮，
   非窗口结果打「待交易时段复测」，不得作为通过依据（D2/D8 的线上实况取证同此约束）。
4. **D8 修复前需先取证** —— **静态部分已完成（2026-10-02 23:46），live 部分改期**。
   静态探针（纯 prompt 组装，零 I/O，**不受验证窗口约束**）：4/4 非 A 股问句
   （恒生科技/黄金/美股科技/标普500）均被注入沪深300等 5 行 A 股估值表，A 股对照组正常，
   scope 声明行不存在 → 缺陷本体确证。
   **live 探针（模型实际怎么说话 → 严重度评级）刻意不在当晚跑**：当时 23:46 非交易时段，
   按 design-checklist D3，非窗口结果只能打「待交易时段复测」、**不得作为失败/成功依据**——
   即花 ~2.5 分钟买一个当天不能用的结论。改并入下一次交易窗口的一次运行，
   与 P1 的 L3 真 LLM 评估同批做。详见 §18。
5. ~~**8 个结构性死词是否删除**~~ → **已解决（W1，`6acbf1f`）**：全部删除 + 新增
   `test_no_structurally_dead_keywords` 防再犯。见 §17.3。
6. ~~**3 个入口摩擦点是否修**~~ → **已解决（W2+W3，`6acbf1f`）**：`估值`、`选哪个`/`买哪个`
   加入词表；裸 `风险` 升为主词并把「巧合」换成**显式排除表**（§4.1 记录了为何只收可证的
   两条）。三条 gap 用例（E13/E17/E18）随之从 gap 转为正常覆盖，`source` 已改。
7. **C0 实测把 L1 从 60 条推到 143 条**，总量随之从 130 升到 209（§6.1）。
   若 P0 工时吃紧，优先砍 P1/P2，**不要砍 L1**——L1 是后续 4 个修复 commit 的基线与兜底。

---

## 14. 落地清单（按 §16.9 的 commit 拆分）

```
# C1 契约/文档对齐（零代码）
api-contracts/analysis/advice-valuation.md   # 删 fetching_etf(D3) / 标注 §5 loop(D6) / 修 :4 行号 / 新增 §4.7 商品槽

# C2 intent flag + L1 gold
backend/app/routers/analysis.py             # D5: user_ctx["product_intent"]
backend/tests/test_advice_goldset_l1.py     # L1 64 条（pytest，零 I/O）
backend/scripts/advice_evals/goldens/l1_intent.jsonl
api-contracts/analysis/advice-valuation.md  # §10 词表扩到 14 条

# C3 prompt 层修复（风险最高，单独 review）
backend/app/routers/analysis.py             # S8: include_commodities=True
backend/app/analysis/llm/reports.py         # D2 三档指令 / D8 scope 行 / S8 商品段(复用 _format_commodities) / D5 守卫条件
backend/scripts/advice_evals/fixtures/*.json  # §9 七份 + commod_warm/commod_empty/tech_cold/tech_warm_no_levels/val_hk_scope
backend/tests/test_advice_goldset_l2.py     # L2 26 条

# C4 前端 + 运行时门禁
frontend/src/components/market/AiAdvisor.vue     # D1: 发 context.portfolio
frontend/src/test/AiAdvisor.spec.js              # D1 断言请求体含 portfolio
backend/scripts/verify_e2e.py                    # D7: 超时重试一次后判 FAIL
backend/tests/test_verify_e2e_advice_gate.py    # D7 门禁 meta-test

# 跨切面
backend/scripts/advice_evals/scorers.py      # intent_scorer / prompt_scorer（纯函数）
docs/advice-goldset-design.md               # 本文档
```

P0（C1-C4）DoD：T0 全绿 + 全部 case `file:line` 可溯 + `source` 字段非空 + xfail 计数与 §8 一致 +
**8 项修复各有「修复前失败 / 修复后通过」的用例对（红→绿可演示）**。

---

## 15. 附录：探针取证记录（2026-10-02，纯函数、零网络、零副作用）

### 15.1 L1 意图探针

```bash
cd backend && python -c "
from app.analysis.intent import classify_all
for q in ['哪些板块低估','红利是不是价值陷阱','恒生科技贵不贵','买哪只银行ETF',
          '512800现在能买吗','最大回撤是多少','回撤太大怎么办','美联储降息对A股有什么影响',
          '当前市场风格偏向成长还是价值？是否该调仓？','这轮A股下跌的支撑位会是怎么样的',
          '上证均线在哪','回撤到多少支撑','支撑位跌破要不要减仓','买点到了吗','我该加仓还是减仓',
          '风险提示有哪些','881001怎么看','今天天气怎么样','哪些板块低估？买哪只ETF？',
          'What is the support level of SSE index?','我的持仓该减仓吗','黄金和原油现在配哪个',
          '港股科技和红利怎么选','它估值贵不贵','512880和512890哪个更稳']:
    print(q, '->', classify_all(q) or 'general')
"
```

实测输出（已逐条抄进 §6.2 表）：其中 **5 条**落 `general` 却被用户视为明确意图
（英文问句 / 跨资产 / 港股对比 / 双标的对比 / 无锚 6 位码），这是缺口族存在的直接证据。

### 15.2 L2 prompt 探针（同一份满 ctx，仅切 `technical_intent` / `valuation_intent`）

实测段序见 §6.3 表；三条补充实测：

| 探针 | 输入 | 输出（关键部分，完整版省略） |
|---|---|---|
| 空 ctx | `{}` | 200 字；`### 行业轮动分析框架` **无条件出现**；`800 字以内` |
| valuation 意图 + 全空 | `{"valuation_intent": True}` | 275 字；出现「估值数据暂不可用（as_of 缺失），不得下低估/高估结论」与「无 ETF 映射表：不得编造任何 ETF 代码」两条守卫 |
| **technical 意图 + 全空** | `{"technical_intent": True}` | **311 字；无任何价位数据、无「（数据源暂不可用）」占位，却要求「1. 先给关键价位表（档位\|点位\|类型\|依据）」** → D2 |
| 只有 portfolio | `{"portfolio":[...]}` | 258 字；`- 沪深300ETF(510300): 30.0%`（`%` 格式、≤5 行） |
| 技术面满 + `support_levels` 形状正确 | `{symbol: {...}}` | 支撑族 `近60日低点 3741.11` / `回撤 61.8% 3827.66`；阻力族 `MA20 3905.64` / `回撤 38.2% 3881.13`；两族不混列 |
| `support_levels` 形状**错误**（传单指数 dict） | 非 `{symbol:...}` | **整段静默消失**，不报错、不告警（`rows==0` → `return []`） |

诱饵值实验：在 ctx 塞入 `market_snapshot='SNAPSHOT_SHOULD_NOT_APPEAR'`、
`global_liquidity={'us_10y':4.1}`、`domestic_macro={'pmi':50.1}`，三种意图分支的 prompt 中
**均不出现**（`snapshot leak: False` / `liuyuan: False` / `us_10y: False` / `pmi: False`）→ I-1、I-2 成立。

### 15.3 探针未覆盖（不得据此下结论）

- 真 LLM 回答质量（L3）：未跑，`§12` 第 3 项标注「待交易时段复测」。
- SSE 帧序列（L4）：未跑，本文档对 `analysis.py:122-131` 的判断来自代码走查，非实测。
- 冷缓存**真实**触发条件（`hub.get_index_technical` 缓存未命中）：本文只用构造 ctx 模拟，
  未启动服务验证「线上真的会冷」。D2 的严重度评级基于代码路径推断，**待 T2 实测确认**。
- D8 的线上实况（港股/黄金问题端上 A 股估值表）：未跑，仅代码路径可查，**待修复前取证**。

---

## 16. 配套修复方案（设计，本轮不实施）

> 契约优先（AGENTS.md「API 契约流程」强制）：三项修复均**先改契约**再改代码。
> 每项给出「改什么 / 怎么验 / 风险 / 是否阻断」，实施轮再展开为 TDD 任务。

### 16.1 D1 — 持仓槽接通（纯前端）

| 项 | 内容 |
|---|---|
| 改什么 | `AiAdvisor.vue:117` 发送体加 `context.portfolio`；数据源 `stores/portfolio.js`（已有 `load()`，`portfolio.js:25`）或 `portfolioApi.list()` |
| 契约 | **无需新增**：`LLMAdviceRequest.context` 已是对象透传（`llm-chat-session.md:29,38`），后端 `analysis.py:652` 已在读 `context.portfolio`。仅在 `advice-valuation.md §8` 勾上「portfolio 由前端注入」并注明字段形状 |
| 字段形状 | `[{symbol, name, target_weight}]`（与 `portfolio_etfs` 一致；`models/portfolio.py:6-29`，`target_weight` 为小数） |
| 怎么验 | L2 gold：`session.frozen_ctx=fx/portfolio_warm.json` ⇒ 出现 `## 持仓信息` 且 ≤5 行、`%` 格式（`reports.py:1549-1556`）。L3 gold：`answer_mode=answer`，且不得出现表外持仓名 |
| 风险 | ① 前端多一次请求（持仓已在 store 缓存则零成本）② 持仓含 `avg_cost` 时是否外泄成本价——**建议只传 3 字段，不传成本/份额**（成本价是用户隐私且 prompt 无用途） |
| 是否阻断 | 是（D1 的 UI 承诺要么兑现要么改文案） |

### 16.2 S8 — 商品槽注入（跨资产纳入职责）

| 项 | 内容 |
|---|---|
| 改什么 | ① `analysis.py:623` `include_commodities=False` → `True`；② `_build_advice_stream_prompt` 新增 `### 商品行情` 段，**复用** `_format_commodities()`（`reports.py:123-148`，市场报告链已在用，别写第二份）。**C3 `9aa4229` 已实施，与方案一致，无偏差** |
| 契约 | `advice-valuation.md` 新增 §4.7 `commodities` 槽定义 + §6 输出格式（表格 or 列表，与市场报告一致） |
| 取数 | `hub.get_commodities()` → `market_service.get_commodities()`，`llm_context.py:170-176` 已封装（15s 超时 + `[:10]` 截断）；上游 `china_market.fetch_futures_realtime()` 8s 超时、**失败静默返回 `[]`**（允许盘后空窗） |
| 怎么验 | L2 gold：`fx/commod_warm.json` ⇒ 出现 `### 商品行情` 且 ≥1 行；`fx/commod_empty.json` ⇒ 整段省略**且**不出现兜底数字。L1 gold：「黄金和原油现在配哪个」期望值仍为 `general`（**不加新意图**，见下） |
| 为什么不加 `cross_asset` 意图 | 加意图需动优先级链（`intent.py:14-15`）+ 契约 §2/§3 + 新 flag，成本高而收益小：商品槽是**基础槽**（每轮常驻、≤6 行），问不问都在 prompt 里，意图只影响「该不该触发额外加采」。本轮用「无条件注入基础槽」而非「意图触发加采」——与 `market_regime`/`news` 同款。**若日后发现跨资产问题需要专属框架（如相关性与替代关系），再加意图不迟** |
| 风险 | ① 每轮多一次 15s 超时的外呼（`llm_context` 内 try/except 不阻塞，但**首字节后**才发生，故不伤 R49 首字节契约）② prompt 体积 +6 行 |
| 是否阻断 | 否（可独立成一个 commit） |

### 16.3 D8 — scope 守卫（非 A 股标的不得端 A 股表）

| 项 | 内容 |
|---|---|
| 问题 | 「恒生科技贵不贵」「黄金现在贵吗」「美股科技贵吗」命中 `valuation`（`intent.py:19` 的 `贵`/`便宜`），但 `analysis.py:700-701` 硬编码 5 个 A 股指数 ⇒ 给港股/黄金问题端一张 A 股估值表 |
| 改什么（推荐方案） | 在 `_build_advice_stream_prompt` 加**一行 scope 声明**而非改取数逻辑：识别 query 中的非 A 资产线索（`港股/恒生/H股/纳指/标普/黄金/原油/白银/美股/国债`）⇒ 命中时在估值表前插入「本产品估值数据仅覆盖 A 股宽基/行业指数；该标的属非 A 资产，以下表格不适用于它，请勿据此下结论」，并把估值表降级为「参考背景」 |
| 备选方案 | 改 `analysis.py:673` 的取数门（仅 query 为 A 股 scope 时才拉估值）——更干净，但少了「顺带告诉用户 A 股估值如何」的额外信息，且要新增 scope 判定函数 |
| 为什么不改词表 | 把 `贵`/`便宜` 从 `_VALUATION_KWS` 删掉会砸掉 S4 主族（「红利是不是价值陷阱」）。**问题不在分类，在数据 scope 不匹配** |
| 怎么验 | L1 gold：非 A 股估值问句仍命中 `valuation`（锁当前分类行为）。L2 gold：`fx/val_hk_scope.json` ⇒ 出现 scope 声明行；A 股估值问句 ⇒ **不**出现（防过度触发） |
| 风险 | scope 关键词过宽会误伤 A 股问句（如「A股和港股谁更便宜」应保留估值表）→ gold case 必须含该反例 |
| 是否阻断 | ~~建议随 S8 同批修~~ → **已于 C3 `9aa4229` 与 S8 同批落地**（同源：投顾只装 A 股数据却对全资产提问照答不误） |

### 16.4 D2 — 冷缓存 technical 不再要求出价位表

| 项 | 内容 |
|---|---|
| 问题 | `technical_intent` 且两槽皆空时，prompt（实测 311 字）**无价位数据、无占位标记**，却要求「1. 先给关键价位表（档位\|点位\|类型\|依据）」。R13 三件套挂在「若数据缺失或标注占位」的条件上——冷缓存时两个条件都不成立，指令自相矛盾 |
| 改什么 | `_build_advice_stream_prompt` 的 technical 分支按数据可用性分三档：<br>**T-全空**（`support_levels` 与 `index_technical` 皆空）→ 插入「（本轮无技术面/关键价位数据：日线源未返回，禁止输出任何点位）」，框架第 1 步改为「**禁止输出支撑/阻力档位表与任何点位数字**，改按下方三件套回答」；<br>**T-仅技术面**（`index_technical` 有、`support_levels` 空）→ 第 1 步改为「仅可引用上方技术面段的 MA/BOLL/RSI/KDJ 数值（带 as_of），**禁止自行推断档位或未列出的点位**」；<br>**T-完整** → 维持现状（「先给关键价位表…」） |
| 不改什么 | 不改 R13 三件套、不改 1200 字上限、不改 `support_levels` 取数（`_technical.py:206-237` 仍是 cache-only + 异步补刷） |
| 怎么验 | L2 gold 三条：`fx/tech_cold.json` ⇒ 出现「禁止输出任何点位」+ 不出现「先给关键价位表」；`fx/tech_warm_no_levels.json` ⇒ 出现「禁止自行推断档位」；`fx/tech_warm.json` ⇒ 出现「先给关键价位表」。<br>L3-xfail 留存：`tech_cold` 跑真 LLM ⇒ 答案不含任何 `\d{4}\.\d{2}` 点位（修复后应转 pass） |
| 风险 | 模型可能过度谦卑（明明有数据也拒答）→ 三档判据必须严格按**槽位非空**而非按意图，三条 gold 用例互斥 |
| 是否阻断 | 是（与 gold set 同批，否则「改了行为、断言还锁旧行为」） |

### 16.5 D5 — `etf_map` 空守卫挂到正确意图

| 项 | 内容 |
|---|---|
| 问题 | `reports.py:1658` 的「无 ETF 映射表：不得编造任何 ETF 代码」挂在 `valuation_intent` 上。纯 product 问句（`primary == "product"`）拿到空 map 时**守卫不出现** → 一个允许编 ETF 码的窗口，正是 `sess-1ef0` 幻觉（`515220` 当银行、`159766` 当煤炭）的同类入口 |
| 改什么 | ① `analysis.py:661-672` 增 `user_ctx["product_intent"] = ("product" in intents)`（与 `valuation_intent` 同模式；**注意用 `in intents` 而非 `primary ==`**，理由见 §1 结论：`analysis.py:727` 的 etf_map 门也是这个判据，两处必须一致）；② `reports.py:1658` 守卫条件改为 `ctx.get("product_intent") or ctx.get("valuation_intent")` |
| 怎么验 | L2 gold：`product` 意图 + 空 map ⇒ 出现守卫文案（修复前不出现）；`valuation` 意图 + 空 map ⇒ 仍出现；`general` 意图 ⇒ 不出现（防过度触发） |
| 风险 | 复合命中（`["valuation","product"]`）时守卫仍出现——正确，两族都需要禁码 |
| 是否阻断 | 是（反幻觉硬约束，属 §4.2 决定 5 的核心承诺） |

### 16.6 D3 + D4 — 契约假承诺二选一（建议：实现 D4，删承诺 D3）

| # | 缺陷 | 建议 | 理由 |
|---|---|---|---|
| **D4** | `done.cached` 被 `_sse_stream:128-131` 丢弃 → 前端「（缓存）」徽标不可达（`AiAdvisor.vue:94-98` 已在读 `m.cached`） | **实现**（1 行）：`metadata['cached'] = data['cached'] if data.get('cached')` | 缓存命中是真实存在的路径（`llm/client.py` 8h TTL，key 含 prompt sha），前端已写好消费代码。契约 `AGENTS.md §6.1` 与实现只差透传一行——**实现比改文档便宜，且让 8h 缓存的省时收益对用户可见** |
| **D3** | `fetching_etf` phase 契约有（`advice-valuation.md:180,257`）、代码无 | **删契约，不实现** | 反直觉但更诚实：`etf_map` 取数是**纯内存 dict 遍历 + substring 匹配**（`analysis.py:727-735`，`SECTOR_ETF_MAP` 是静态表），**零 I/O、零延迟**。为一个瞬时操作发「正在查询…」进度阶段是表演而非诚实。对比 `fetching_valuation`（25s 预算、5 指数并发外呼）——那个才配得上 progress |

两条的共同判据（写进实施轮 review checklist）：**契约承诺的行为，要么有真实延迟/真实价值可展示，要么从契约删掉——不留假承诺，也不为契约演 fake progress。**

### 16.7 D7 — `verify_e2e` 不再把超时判 PASS

| 项 | 内容 |
|---|---|
| 问题 | `verify_e2e.py:913,915`：`except requests.Timeout: check(..., True, "LLM 慢——不算模板回归")`、`except Exception: check(..., True, ...)`。端点死掉 / 45s 超时 → advice 运行时门禁**照样全绿** |
| 改什么 | 超时/异常改为**重试一次（timeout=90s）后判 FAIL**；同时把该症状指纹登记进 `docs/known-env-issues.md`（LLM 侧慢，`docs/design-checklist.md` 第 8 项「已知问题模式」要求） |
| 为什么不是 `skip=True` | `check(label, ok, detail, skip=False)` 有 skip 通道（`verify_e2e.py:92-95`），另有 STORM_SKIP 机制（round36 §8-C 为事件循环拒绝风暴专设）。用 skip 只会**把我们要堵的洞重新打开**——环境慢有专用通道（STORM_SKIP）处置，advice 超时没有理由走 skip |
| 为什么不是直接判 FAIL | 单次 45s 超时确有环境噪声成分。重试一次既压噪声又保留信号：重试仍失败 = 端点真有问题 |
| 怎么验 | 这条本身是门禁代码，用**门禁的 meta-test** 验证（既有范式：`tests/test_*.py` 里已有 `test_patrol_orchestration.py` / `test_tests_ok_marker.py` 守门禁自身）——断言 advice 异常分支不再出现 `check(..., True, ...)` |
| 风险 | 网络抖动会让 verify_e2e 偶发红 → 已知问题模式表登记 + 重试覆盖。**这是正确的红**，比永远绿好 |
| 是否阻断 | 是（否则本轮 gold set 再好，运行时仍无人守） |

### 16.8 文档债修正（零代码，D3 之外的契约对齐）

- `advice-valuation.md §5`「受限 2 步 loop（2 个白名单工具）」与代码不符（`analysis.py:673-735` 硬编码 if）：
  二选一——删掉该节，或标注「v1 未实现，调度硬编码于 router」。**推荐标注**（保留设计意图，供后续工具化）。
- `advice-valuation.md:4` 三处行号全错（指向 `analysis.py:498` / `reports.py:1156`，实际 `:587` / `:1501`）。
- `advice-valuation.md:257` 的 `fetching_etf`（D3）：**删**（依 §16.6 判据）。
- `AGENTS.md §6.1` 的 `done.cached`（D4）：**保留 + 实现**。

### 16.9 修复顺序（8 项，单轮风险控制）

用户已拍板 8 项全修（D1/S8/D8/D2/D5/D4/D3/D7）。一轮 8 项 + 130 条 gold case 偏大，
故按「每项独立可红可绿」拆 5 个 commit，**任一 commit 单独 revert 不破坏其余**。

> **v2 修正（2026-10-02 自查）**：原 4-commit 拆分把 D5 劈成两半——C2 加 `product_intent` flag、
> C3 才在 `reports.py:1658` 消费它。这违反 AGENTS.md「脚手架零容忍」（新增未接入生产的代码不允许
> 静默留存）：C2 结束后该 flag 只写不读。注意这**不会**触发任何门禁失败（P3-G 只校验
> router 注入 ⊇ prompt 消费这一个方向，`test_advice_p0a_slots.py:92`），
> 属 review 阶段靠人眼发现的反假完成违规。故 D5 必须原子化。
>
> 另一条排序依据：**「锁当前行为」决议要求先快照 L1**。所幸 8 项修复**均不改变 `classify_all`
> 输出**（S8 特意不加新意图正是为此），故 L1 基线在整轮内稳定，可独立先行提交、不需重基线。

| commit | 内容 | 前置 | 可独立验证 | 风险 |
|---|---|---|---|---|
| **C0** | **L1 gold 64 条 + `intent_scorer` + T0 门禁接入**（纯测试资产，零 I/O） | — | L1 全绿；含缺口族 22 条（锁当前 `general`） | 低 |
| **C1** | 契约/文档对齐（D3 删 `fetching_etf` / D6 标注 §5 loop / `:4` 行号 / 新增 §4.7 商品槽） | — | 契约 grep 无残留假承诺 | 低 |
| **C2** | **D5 原子修复**：`product_intent` flag + `reports.py:1658` 守卫条件 + L2 gold 3 条（红→绿） | C1 | product 空 map ⇒ 守卫出现；general ⇒ 不出现 | 低 |
| **C3** | **prompt 层**：D2 三档指令 + D8 scope 行 + S8 商品段（复用 `_format_commodities`）+ L2 gold 13 条 | C2 | 三档互斥用例 + scope 正反例 | **高** |
| **C4** | D1 前端 + D4 透传 + D7 verify_e2e（含门禁 meta-test） | C3 | D1 请求体含 portfolio；D7 异常分支不再 `check(..., True, ...)` | 低 |
| P1 | L3 规则轨 30 条（T1 夜间 ×3 重复） | C4 | 真 LLM 稳定性统计 | 中（费用/非确定） |
| P2 | T2 抽读 + `advice-valuation.md` §2/§3/§4/§6/§10 全量同步 | P1 | 人工抽读记录 | 低 |

**为什么 C0 排最前**（三条理由）：
1. **它锁的是基线**。C3 会改 prompt 生成逻辑、C2 会加 flag；先有 L1 快照，后续任何行为变更
   都能立刻看出「动了哪条意图」，否则基线与修复后的行为混在一起，无法归因。
2. **它零风险零依赖**。不启服务、不调 LLM、不改产品代码，可在任何环境下独立完成与验证，
   而 C1-C4 都需要真链路验证。**先把能确定做完，再碰需要真环境的**。
3. **它本身就是门禁**。C0 完成后，后续 4 个修复 commit 都有 L1 绿线兜底——
   若某修复意外改变了意图分类（如未来有人给 S8 加新意图时误伤既有词表），C0 立刻报警。

**C3 是风险最高项**（同时动 prompt 生成的三处分支），须单独 review。
若超期，优先砍 P1/P2，**不可砍 C0-C4**——它们是缺陷修复与基线，不是测试资产。

---

## 17. 附录：C0 变异测试记录（2026-10-02）

断言数量不等于覆盖。「每条用例都绿」可以由一个从不看分类结果的测试集产生，
所以 C0 用**变异测试**验证自己：改坏 `intent.py`，看用例是否报警。

### 17.1 方法（一次性探针，不入库）

它会**原地改写源文件**，故不入仓（入库等于给后人留一个能改产品代码的脚本）。
要复现，方法四步：

1. 把词表条目替换为同形状的哨兵串（`"PE"` → `"__mutant_never_matches__PE"`）——
   不用「从多词上下文里删词」的写法，源码一旦换行就匹配不上（首批 59 个变异里
   **9 个静默未生效**，比不做变异更危险：它看起来像覆盖）。
2. 每个变异**独立子进程**跑全部用例（`-B` + 清 `__pycache__`）。
   同进程内改 `sys.modules` 会串扰：`关税` 变异在矩阵里报「存活」、
   单独测却报「变化」。
3. 必须 `-B` 并删 `intent.cpython-*.pyc`：一秒内连续改写会让**陈旧字节码**被复用，
   曾把 9 个能被杀的变异误报成存活。
4. `finally` 还原 + 校验字节一致。注意 `Path.write_text()` 在 Windows 会把 `\n`
   翻成 `\r\n`，把整个文件变成「已修改」——必须 `write_bytes()`。

### 17.2 结果：91 杀 / 8 存活 / 99 总

5 轮收敛（64 → 143 条）。每轮暴露两类缺口：

| 轮次 | 暴露的问题 | 处理 |
|---|---|---|
| 1 | **88 个词表条目中 44 个零覆盖**（含 `安全垫`、`防御+调仓` 两条合取规则） | 补 42 条 `keyword` 族；加结构性 meta-test 强制新词必须有用例 |
| 2 | 用例里目标词被同类词兜住（`加息` 的用例还有「美联储」） | 立「唯一触发词」约定，补 5 条 |
| 3 | 同上（`政策`/`利好`/`决议`/`风格`/`主线`/`成长`/`如何应对`/`压力`/`阻力`） | 补 10 条 |
| 4 | 同上（`市净率`/`分位`/`错杀`/`陷阱`/`PE`/`pe`/`PB`/`pb`/`roe`/`etf推荐`/`爆仓` + product×risk 优先级） | 补 12 条 |
| 5 | 裸词 `卖` 被 `卖出` 子串兜住 | 补 1 条 |

### 17.3 存活 8 项 = 8 个**可证明的结构性死词**

同一轮匹配内已存在更短的条目把它吞掉，删除它**永远不改变任何结果**：

```
价值陷阱 ⊂ 陷阱（且 ⊂ 价值，属 rotation）    支撑位 ⊂ 支撑
压力位 ⊂ 压力                              阻力位 ⊂ 阻力
买点   ⊂ 买（裸词）                        卖点   ⊂ 卖（裸词）
买入   ⊂ 买（裸词）                        卖出   ⊂ 卖（裸词）
```

这不是「测不到」，是**测也没用**——加任何用例都无法让它们变成承重词。

**已于 round60 W1（commit `6acbf1f`）全部删除**，行为不变（81 条探针 0 变化）。
防再犯：`tests/test_advice_goldset_l1.py::test_no_structurally_dead_keywords`
（同组内长词被短词遮蔽即失败，报错信息指明谁遮蔽谁）。
该 meta-test 上线当天就抓到我把 `买入`/`卖出` 留在了 allocation 组里——删了 8 个字，
自己又造回 2 个。

### 17.4 附带发现：3 个「入口摩擦」点（非缺陷，但影响转化）

这些不是分类错误，是**用户按常识说话却命中不了**：

| 现象 | 实测 | 影响 |
|---|---|---|
| 「估值」不是词表词 | `_VALUATION_KWS` 只有 `低估`/`高估`/`市盈率`/`市净率`，说「估值低」落 general（E13） | S4 估值族的最大入口词失效 |
| 「选哪个」≠「选哪只」 | 一字之差（E18→general / E20→product） | 同义问法结果分叉 |
| 「风险」单出不判 risk | 需搭配 `怎么办`/`如何应对`/`怎么控`（E17） | S10 风险族最自然的问法失效 |

三条都**不在本轮修复范围**（会改变 L1 基线，与「锁当前行为」决议冲突），
但 gold set 已把它们钉住并标注为缺口，日后扩词表时会立刻看到这几条变红。

---

---

## 18. 附录：D8 静态探针（2026-10-02 23:46，非交易时段）

**为什么分静态/live 两段**：缺陷有两个层次，证据的可用性也不同。

| | 探什么 | 依赖 | 窗口约束 | 状态 |
|---|---|---|---|---|
| **静态** | 非 A 股问句是否真被注入 A 股表 | 纯 prompt 组装（`_build_advice_stream_prompt`），零 I/O | **无**——不涉及盘中真值 | 已做：4/4 复现 |
| **live** | 模型**实际怎么说话**（会不会真的引用 A 股 PE 答港股问题） | 真实 hub 取数 + LLM | **有**（design-checklist D3） | 改期至交易窗口 |

### 18.1 静态探针结果

| 问句 | 标的类别 | `classify_all` | 注入的 A 股行 | scope 声明 | 判定 |
|---|---|---|---|---|---|
| 恒生科技贵不贵 | 港股 | `["valuation"]` | 沪深300/中证500/中证1000/上证50/创业板指 | 无 | **复现** |
| 黄金现在贵吗 | 商品 | `["valuation"]` | 同上 5 行 | 无 | **复现** |
| 美股科技股估值贵不贵 | 美股 | `["valuation"]` | 同上 5 行 | 无 | **复现** |
| 标普500现在贵吗 | 美股指数 | `["valuation"]` | 同上 5 行 | 无 | **复现** |
| 沪深300现在PE分位多少，贵吗？ | A 股（对照） | `["valuation"]` | 同上 5 行（**应当如此**） | 无 | 正常 |

**结论**：缺陷本体（取数 scope 与提问 scope 不匹配）**已确证**，不依赖行情新鲜度，
故不受 D3 验证窗口约束。触发链只有两环，都已实测：
`intent.py:19` 的 `贵`/`便宜` → `analysis.py:673` 进 valuation 分支 → `:700-701` 硬编码 5 个 A 股码。

同根因还命中另外两个槽（故 §16.3 的守卫设计做成**槽无关**而非只护估值表）：
E08「纳斯达克跌破支撑位了吗」→ `technical`，而技术面槽只有 `000001`/`000300`；
E07「港股红利ETF推荐」→ `product`，注入 A 股 `510880`。

### 18.2 live 探针为何不在当晚跑

当时 23:46，非交易时段。按 D3，非窗口内的行情相关验证结果只能标注
「待交易时段复测」，**不得作为失败/成功依据**。跑它要付出启后端（60-90s warmup）
加一次真实 LLM 调用（30-60s），买到的却是一个当天不可采信的观察。

而 live 探针真正提供的唯一增量信息是**严重度评级**（模型是硬答 A 股数据，
还是含糊带过）。这个问题在 P1 的 L3 真 LLM 评估里必然要问，且那条路本来就必须
在交易窗口跑。因此正确做法是**并入下一次交易窗口的一次运行**，而不是当晚单独跑一次。

### 18.3 探针脚本

未入库（一次性探针）。方法：直接调用纯函数 `_build_advice_stream_prompt`，
喂 5 个固定 symbol 的构造估值行，断言「A 股行名是否出现在 prompt 里」。
转成永久回归用例的部分见 C3 的 L2 gold case。**探针数字是构造的**，
故 C3 的 fixture 必须自带 provenance（design-checklist 第 4 项：非兜底数据）。

---

---

## 19. 附录：C0-C4 落地结果（2026-10-02）

八项修复全部落地，五个 commit，全部通过 pre-commit（含全量pytest 3533 passed、
前端 579 passed + build、check_routes 83 路由、smoke_startup、engine 纯度、
async 阻塞审计 153 文件）。

| commit | 内容 | 变异/实证 |
|---|---|---|
| `6684282` | L1 gold 143 条 + scorer + 6 条 meta-test + 本文档 | **91/99 killed**；存活 8 项全为可证明的结构性死词（§17.3） |
| `fba61d5` | 契约对齐：删 `fetching_etf` 假承诺、标注 §5 loop 未实现、订正行号、预写 §4.7/§4.8/§6.1/§6.2 | 契约 grep 无残留假承诺；199 passed |
| `1654fc1` | **D5** 守卫挂错意图 | 变异后**两层同时红**（组装层 + 接线层） |
| `9aa4229` | **S8** 商品段 + **D8** scope 声明 + **D2** 三档 + 失效 mock 修复 | **7/7 killed** |
| `9910d51` | **D1** 前端持仓槽 + **D4** cached 透传 + **D7** 端点可达性门禁 | D7 meta-test **4/4**；D1 全链路实证 |

### 19.1 计划外的发现（都不在原计划内）

| # | 发现 | 性质 | 处置 |
|---|---|---|---|
| 1 | **88 个词表条目中 44 个零覆盖**（C0 变异测试） | 测试资产缺口 | 补 70 条 `keyword` 族 + 结构性 meta-test 防再犯 |
| 2 | **8 个关键词结构性死亡**（`支撑位`⊂`支撑` 等） | 代码冗余（行为可证明不变） | 记录为提案（§13.2 item 5），未删——属产品变更 |
| 3 | **3 个入口摩擦点**（「估值」「选哪个」「风险」单用不命中） | 分类器覆盖不足 | 记录并钉住，**不修**（会动 L1 基线，与「锁当前行为」冲突） |
| 4 | **既有 mock 从未生效**（`test_chat_session_endpoint.py` patch 的是被函数内 import 遮蔽的名字） | 测试假绿 + 真实网络 I/O | C3 修正patch 目标；同文件 117.8s → 18.9s |
| 5 | **商品槽只死在一个参数上且无人看守** | 变异测试发现 | 补「断言采集参数」的用例；否则 flag 改回 False 全绿 |
| 6 | **我的变异 harness 骗了我两次**（cwd算错→全记存活；未生效变异显示为存活） | 方法论缺陷 | harness 改为「跑不出摘要报 BROKEN + 校验returncode + NO-APPLY 独立标记」 |

第 4 与第 6 条是本轮最值得记住的：两者都是**「看起来有保护，其实没有」**——
一个是 mock 形状的表演，一个是评测工具自身的假阴性。AGENTS.md 反假完成条款针对的是
产品代码的假完成，而这两条说明**测试与评测基础设施同样需要被质疑**。

### 19.2 剩余项

| 项 | 状态 | 阻塞原因 |
|---|---|---|
| **P1** L3 答案质量规则轨（30 条，含 R13 三件套 answer 侧） | 未做 | **需交易窗口**（真 LLM + 行情真值）。契约 §8 有 5 行 ☐ 全部指向它 |
| **D8 live 探针**（模型实际怎么说话 → 严重度评级） | 未做 | 同上；已并入 P1 一次运行（§18.2） |
| **P2** 契约 §2/§3/§10 与 gold set 全量同步 + T2 人工抽读 | 未做 | 无阻塞，可在任意时点做 |
| **S1** 因子条件筛选 | 已立项 | 全产品无条件筛选能力，属独立项目；本轮 gold 期望标 `degrade` |
| 8 个死词删除 / 3 个入口摩擦点 | 待拍板 | 见 §13.2 items 5-6；均会动 L1 基线或属产品变更 |

**给下一轮的一句话**：契约 §8 现在有 5 行 ☐，它们不是漏勾，是**如实标注 L3 缺口**。
P1 落地后应逐行勾上并附真 LLM 重复 3 次的稳定性数据；若某行始终无法稳定通过，
说明该约束应改写进prompt 而非留在契约里当口号。

---

## 20. 附录：本文档的时效性约定（2026-10-02 立规）

本文档同时含三类内容，混在一起会随时间变成谎言。故明确区分：

| 章节 | 性质 | 时效规则 |
|---|---|---|
| §1 现状取证、§4 现状列、§7 不变式、§8 缺陷表 | **事实陈述** | 修复落地后**必须同步更新**，并标注 commit 号（round60 C0-C4 已做，见 §19） |
| §4 场景矩阵的「产品形态」列、§12 四问法判断 | **推断/判断** | 带日期与依据；被推翻时**追加纠正行而非删旧行**（保留判断演变的可审计轨迹，教训来自 memory `warmup-两阶段复活`：三次错误估计都是因为直接覆盖了结论） |
| §16 修复方案 | **历史设计** | 保留原文不改；实施后的实际做法与方案有偏差时，在 §19 记录差异（例：D8 推荐「只加声明行不改取数」，实施完全按此，无偏差） |

**为什么立这条规**：本轮 §4 的「本产品现状」列在 8 项修复落地后立刻过时（写着
「portfolio 槽线上恒空」「投顾是唯一不注入商品的链路」，而两者都已在 C3/C4 修好）。
设计文档的**方案**部分过时无所谓（那是历史），但**现状陈述**过时会让下一轮读者
按错误的基线做判断——这与 gold set 要治的病同源：断言锁不住现实。

**自检方式**（可加进门禁，本次未加，避免新增门禁段）：
在本文档里搜「现状陈述型的过时断言」——`<过时断言关键词>` ——命中的每一处都应带
「已修/已处理 + commit」或明确的「方案原文」标注。（刻意不写出具体关键词，
否则这条自检命令会匹配到它自己，扫描结果里永远有一条噪声。）
本次执行结果：除本行外全部命中均已带标记。

Refs: §19 落地结果、§8 处置列

---

## 21. 附录：P2 契约同步（2026-10-02）

P2 的两部分，状态不同：

| 部分 | 状态 | 说明 |
|---|---|---|
| 契约 §2/§3/§10 与 gold set 全量同步 | ✅ 已做 | 本节 |
| T2 人工抽读 | ⏳ **阻塞** | 需真 LLM + 交易窗口，并入 P1 |

### 21.1 同步了什么

| 契约位置 | 改动 |
|---|---|
| §1 概述 | 「六意图」→「七意图 + general 兜底」；标注受限 loop **未实现**（与 §5 一致，不再宣称已实现） |
| §2 意图表 | 每行补 gold case id 区间，使「契约条目 ↔ 断言」可双向查；`allocation` 行标注 portfolio 已由前端注入；补两条 composite 例（risk×event、product） |
| §2 优先级 | 记录 round60 W3 发现的配对空洞：risk×event 此前无用例，链内对调无人报警 |
| §3.1 risk | 重写为「主词表 + 显式排除表」，并记录**只收可证两条**的理由（排除表每条都是一次假阴性） |
| §3.2 product | 补 `选哪个`/`买哪个`；说明 `买什么ETF`/`买什么etf` 两份**不是冗余**（大小写敏感的子串匹配） |
| §3.3 technical | **删掉已不存在的 `支撑位`/`压力位`/`阻力位`**，并说明「用户仍可输入并正确命中」的机制（`支撑` 是 `支撑位` 的子串）——删的是词表的**假装**，不是功能 |
| §3.3 正反例 | 每条补 gold case id |
| §9 设计清单 | 补 3b/4b/5b 三行：验证窗口（词表改动不受 D3 约束，但证据来自自拟探针而非生产流量）、非兜底（死词删除可证明中立 + 唯一触发词约定）、真实调用点（`classify_all` 生产调用方唯一） |
| §8 检查表 | 上一 commit 已按「该层实现且有断言看守」勾选，5 行 ☐ 明确指向 P1 |

### 21.2 同步时发现的一处真漂移

§3.3 的 technical 主词表仍列着 W1 已删除的 `支撑位`/`压力位`/`阻力位`。
这类漂移的特点是**双向都看不出问题**：契约说的词仍能命中（因为短词是它的子串），
所以功能测试全绿；而词表早已不含这三条任何人读文档都会误以为它们生效。
是写审计脚本比对「契约声明 vs `intent.py` 实际」才暴露的——手工核对不会发现，
因为读起来「支撑位/支撑/压力位/压力」看起来完全合理。

**这暴露一个门禁缺口**：契约的词表没有任何自动化校验（`test_contract_auto.py` 不覆盖
关键词）。本轮**未新增门禁段**（AGENTS.md 门禁替换制上限 16 段），而是把校验方法写进
本节；若日后要常态化，应并入既有 `check_routes` 段的契约一致性检查，而非另立一段。

### 21.3 T2 人工抽读为何仍阻塞

T2 要人读真 LLM 回答，判断「像不像一个懂行的投顾在说话」。这既需要真 LLM（温度 0.5，
不可重放），也需要交易时段的行情真值。按 design-checklist D3，非窗口结果只能标
「待交易时段复测」，故 T2 与 P1、D8 live 探针**合并为下一次交易窗口的一次运行**，
不单独提前。

Refs: §19 落地结果、§20 时效性约定、§17.3 死词处置
