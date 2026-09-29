# round58 市场综合研判缺数治理（P0 接线 + P1 增强）

> 状态：**已实施（commit `03ed659`，2026-09-28）**——P0-1~P0-5 + P1-6~P1-9 全部落地；
> P2-2 并入 P0-3a、P2-3 并入 P1-8（见 §2）。**实施期发现 §2 P2-3 的探针结论与真实数据
> 不符，R08 实施口径已调整**（详见 §3.1 R08 条 + §8 偏离登记）。P2-1 个股级 moneyflow 维持暂缓。
> 触发：用户报告"市场综合研判存在很多数据缺失"（2026-09-26，模型 space-bunny-free 输出 6 章报告，3 处"输入未提供/暂无法验证"）。
> file:line 锚点核对时间：2026-09-26（HEAD 现状，见 §1）。
> 验证窗口：**2026-09-26 为周六非交易日**——凡涉实时值/交易日行为的验收项先收口到可测子集（prompt 含值/占位/单测），实值复测标「待交易时段复测（交易日 9:30-11:30/13:00-15:00 + 真实环境）」。

## 1. 缺失 → 根因映射（D2 证据链，全部已 grep 实证）

| # | 报告抱怨 | 根因（file:line，2026-09-26 已核） | 类型 |
|---|---|---|---|
| M1 | 成交量变化、涨跌家数比缺失 | `fetch_market_sentiment` 已算 `advance_ratio/volume_ratio/margin_change`（`backend/app/fetchers/fundamentals_fetcher.py:1056`），`hub.get_advance_decline` 现成（`backend/app/services/hub/_realtime.py:116`）；但 `_build_report_prompt` 无 `sentiment` 参数（`backend/app/analysis/llm/reports.py:237`），`llm_report_stream` 组 prompt 时不传（`backend/app/routers/analysis.py:464`） | 采了没接线（R79 同构） |
| M2 | 板块/风格"输入未提供行业涨跌" | `build_full_context` 已采 `sector_momentum/hot_plates/sector_heat`（`backend/app/services/llm_context.py:77-96`），但 `llm_report_stream` 只取 regime/sentiment/market_data/indices/commodities/news（`analysis.py:398-403`），sector 三件套采完即丢；`_build_report_prompt` 无 sector 参数 | 采了没接线（最大断点） |
| M3 | 政策信号空 | `macro_news` 恒传 `[]`（`analysis.py:466`），`_build_market_overview` 宏观政策段永空（`reports.py:181`）；A 股 `news` 已混入 `get_news_macro`（`llm_context.py:141`）但 prompt 不区分政策类 | 死参数 |
| M4 | 美债 5.17% vs 5.18% 双口径 | `global_liquidity.us_10y`（FRED，`llm_context.py:184`）与 `domestic_macro.bond_yields.us_10y`（akshare，`macro_fetcher.py:77`）同指标双源并列注入（`reports.py:253-272`），LLM 照抄两数 | 去重缺失 |
| M5 | 指数有价无量 | mootdx 分支有 `volume`（`china_market.py:1338`）但 Sina/Tencent 主路径无量；`_build_market_overview` 只渲染 price/change_pct（`reports.py:148`） | 字段丢弃 |
| M6 | 油价缺失 | `fetch_futures_realtime` 经 akshare 外盘（`china_market.py:1126`，8s 超时即 `[]`）；`_format_commodities` 按中文名过滤 6 品种（`reports.py:119`），`WTI/布伦特/CL` 等英文名对不上即被丢 | 源脆弱 + 过滤错位 |
| M7 | 北向/ETF申赎/成交额 | 北向自 2024-08 监管禁实时披露（`docs/archived/comprehensive-diagnosis-report.md:333`，P1.2e 已删）；`fund_share_fetcher.py` 报告链零引用；全市场成交额可用 `push2delay clist` 同接口求和（`fundamentals_fetcher.py:936`）但无人调 | 源边界 + 未接线混合 |

## 2. P2 探针结论（D1，2026-09-26 周六单次探测，脚本 `/tmp/opencode/round58_p2*.py`）

- **P2-1 行业/个股主力资金流（tushare `moneyflow`/`moneyflow_hsgt`）→ 不可行**：token 存在但无该两接口权限（`tushare.pro/document/1?doc_id=108`，0.1s 即拒，非网络问题）。改走东财免费链：板块 `main_inflow`（`get_sector_industry` 已有）聚合 + P2-3 的 hsgt 历史；**个股级 moneyflow 暂缓，不立项**。
- **P2-2 政策条抽取（`fetch_macro_news` 现状）→ 可行**：缓存命中 4 条 / 0.3s，政策关键词（央行/财政/国务院/LPR/MLF/逆回购/降准/政策/会议）命中 1 条；条目自带 `level/stars/category/source`（`news_fetcher.py:264 _attach_level`）。结论：P0-3a 关键词抽取法成立，并入 P0。
- **P2-3 南向/北向历史资金流（`ak.stock_hsgt_hist_em`）→ 可行**：akshare 1.18.94，东财 datacenter-web 免费接口（无 token），默认 symbol（沪深港通）2760 行 / 2.3s，最新 `2026-09-24`（上周四），列含北向/南向净流入 + 沪深300/上证对照（**沪深300 3888.37/-1.22% 与用户报告完全一致，佐证报告 as_of≈09-24**）；symbol_map 另有北向/南向/沪股通/深股通变体。注意：①实现侧**不得硬编码中文 symbol**（Windows cp936 下字面量被 mangling，本次探针复现 KeyError；改按默认参数或程序化取 map 键）；②日频数据，**24h 缓存**，逐页拉全量 2.3s 不可放请求链。并入 P1-8。

## 3. 实施清单（已拍板项；暂缓：个股级 moneyflow）

### P0（零新源，全走缓存，超时风险零）

- **R01 sector 三件套注入 prompt**：`_build_report_prompt` 新增 `sector_momentum/hot_plates/sector_heat` 参数并渲染"强势 Top5/弱势 Top5（含涨跌幅）+ 热点板块"节；`analysis.py:464` 把 `ctx` 已有值透传。风格切换用现成宽基 proxy（大盘 `000016` vs 小盘 `000852`、价值 `000300` vs 成长 `399006`，`fetch_index_realtime` 8 指数内），不新增风格源。
- **R02 量能/宽度注入 prompt**：新增"量能与宽度"节：`advance_ratio→上涨占比/涨跌家数比`、`volume_ratio→量比`、`margin_change→杠杆情绪`（源 `fetch_market_sentiment`），指数 `volume` 有则给。缺失统一"（数据源暂不可用）"（R80 规范），LLM 不得写"输入未提供"。
- **R03a 政策条抽取（P2-2 落地）**：`macro_news` 死参改活——从 `enriched_news` 按 P2-2 关键词表抽 ≤5 条喂"宏观政策"段；零命中则该段省略（不在模板里留空话柄）。
- **R03b 美债去重（M4）**：`global_liquidity.us_10y`（FRED）为准，`domestic_macro` 渲染时跳过 `us_10y`（只留 `cn_10y + spread_bp`），prompt 加"美债以 FRED 口径为准"一行。
- **R04 模板收敛**：第 1/2 章量能/宽度改为条件式——有数必引数值，无数收敛一句"量能数据缺失，本节不做趋势单边判断"，禁每段重复"暂无法验证"（本次 3 处重复系模板逼出）。
- **R05 冻结快照扩展**：`store.set_frozen`（`analysis.py:475`）追加 sector Top5 一行 + 量能一行（沿用 `_snap_lines`，4000 字上限内），追问复用不重采。

### P1（现有 fetcher，加缓存；实值部分待交易时段复测）

- **R06 全市场成交额/涨跌家数**：复用 `push2delay clist`（`fundamentals_fetcher.py:936` 同接口）顺带求 `total_amount + up/down/total`，hub 方法 + 5min 缓存，注入 R02 节。备选 `fetch_all_stocks` 仅降级。
- **R07 油价/商品名映射**：`_format_commodities` 加别名表（`WTI/布伦特/CL→原油`，`GC→黄金`，`SI→白银`，`HG→铜`）；对不上时回退现有 `commodities[:6]`；全空则占位不阻断主报告。
- **R08 北向替代三件套 + hsgt 历史（P2-3 落地）**：prompt"资金行为"段改喂：两融变化（`fetch_margin_change` 现成）+ 候选池主力流（`_compute_fund_flow`，注明候选池口径非全市场）+ `stock_hsgt_hist_em` 北向/南向近 5 日净流入（24h 缓存，中文 symbol 不硬编码）；prompt 明确"北向实时自 2024-08 停更，不得索取/编造"。
  - **实施校正（2026-09-28）**：P2-3 探针的两条前提经真实调用证伪——① akshare 1.18.94
    `stock_hsgt_hist_em` 的**默认 `symbol` 就是「北向资金」**，且返回列**无「北向/南向」前缀**
    （`日期/当日成交净买额/买入成交额/卖出成交额/历史累计净买额/当日资金流向/当日余额/持股市值/…`），
    按前缀分组取列恒为 None；② 该净额序列**最后可得日 = 2024-08-16**（2761 行中 2264 行有值，
    其后为 NaN），"近 5 日净流入"不存在（探针当时读的是 `沪深300` 指数列，故误判"最新 09-24"）。
    实施口径：按**默认参数**调用（不传 symbol，口径标签用 `inspect.signature` 程序化取），
    净额按「当日…净…列优先（排除『累计』列），否则 买入额-卖出额」结构化取列；
    净额行超过 `HSGT_FRESH_DAYS=7` 即判**停更** → 返回 `stale=True` + `rows=[]` +
    `last_available`，**不返回任何数值**（给 2 年前的数当"当前资金行为"比不给更糟）。
    南向序列需程序化解析 `symbol_map` 取键，本轮**未接**（`south_net` 恒 None → prompt 侧不渲染）。

- **R09 as_of 扩展**：R80 指数快照标注扩展到 sector/量能/hsgt（各取源刷新时间，无则不标不伪造）。

## 4. 契约先行

- 接口 schema 不变（只改 prompt 内容 + 快照文本），在 `api-contracts/analysis/llm-report-chat.md` **追加**一节"报告数据段（round58）"：新增 prompt 节清单 + 字段级断言（sector 名/涨跌幅真值、美债单口径、缺失占位文案），不重写文件（round52 域总契约规则不适用此文件，但同样只追加）。

## 5. 测试（T4：不开新文件，并入既有主题文件；外部网络一律 mock）

| R | 宿主文件 | 负向断言（必须） |
|---|---|---|
| R01 sector 注入 | `test_llm_report_market_filter.py` | sector 全空时报告不得出现编造的板块涨跌幅 |
| R02 量能/R03b 去重 | `test_report_macro_injection.py` | 双 US10Y 不得同时出现；sentiment 缺失时有"暂不可用"占位 |
| R03a 政策抽取 | `test_report_macro_injection.py` | 零命中时"宏观政策"段省略（非空段落 → FAIL） |
| R04 模板收敛 | `test_report_quality.py` | 量能缺失时无"暂无法验证"重复（计数 ≤1） |
| R06 全市场额/家数 | `test_llm_context_market.py` | clist 失败时回退空 + 占位，不得报 0 家伪值 |
| R07 商品别名 | `test_global_liquidity.py` | `WTI` 输入映射到"原油"行；全空不断主报告 |
| R08 hsgt | `test_macro_fetcher.py` 或新建 hub 单测并入同文件 | 缓存 24h（二次调用零网络）；symbol 硬编码中文 → FAIL（防 cp936 坑） |

## 6. design-checklist 8 项对照

1. 探针 §2（命令+输出齐）；2. 证据链 §1（file:line 全是 09-26 现状）；3. 验证窗口：本文头 + R06/R08 实值复测标待交易时段；4. 非兜底：R02/R07/R08 占位规范 + §5 负向断言；5. 真实调用点：改动点全在 `analysis.py/llm/reports.py/llm_context.py` 生产链（R06 新增 hub 方法由 R02 消费，无 0 引用项）；6. 四态 UI：纯后端变更，前端 `MarketReport.vue` 流式/progress/error 复用现有态，不新增态；7. 复杂度：新增网络调用（clist 求和、hsgt）均为**缓存包裹 + wait_for 超时**（clist 5min、hsgt 24h、超时各 ≤15s），循环内无 IO（Top5 切片内存操作）；8. 已知模式：R08 中文 symbol 用程序化键（防 R186 类口径断裂 + 本轮实证的 cp936 mangling）；mock 理想输入→§5 全空/失败用例覆盖；降级无门禁用例（占位不断言"正常"）。

## 7. 验收

- 开发期：受影响测试文件 + mypy；验收期全量 1 次 + `tests_ok_marker.py --mark`。
- 运行时（周六可测子集一次跑完）：mock 全空 prompt 含占位不断言失败；有值 prompt 含 sector 真名/涨跌幅、单美债口径、政策条标题；`rg` 确认 `macro_news=[]` 恒空已消除、`sector_momentum` 在 `analysis.py` 有消费点。
- 待交易时段复测：R06 实额/家数、R08 hsgt 近 5 日值、端到端报告实值引用（对照本轮用户报告 3888.37/-1.22% 同类数值出现）。

---

---

## 8. 实施回填（2026-09-28，commit `03ed659`）

### 8.1 逐项状态

| R | 状态 | 落点 |
|---|---|---|
| R01 sector 三件套 | ✅ | `reports._format_sector_section` + `analysis.py` 透传 `sector_momentum`/`hot_plates` |
| R02 量能/宽度 | ✅ | `reports._format_breadth_section`（advance_ratio/volume_ratio/margin_change + R06 家数成交额） |
| R03a 政策条 | ✅ | `analysis._extract_policy_news`（≤5 条关键词；零命中整段省略） |
| R03b 美债去重 | ✅ | `_format_domestic_macro` 删 `us_10y` 行；海外流动性段加「以本段 FRED 口径为准」 |
| R04 模板收敛 | ✅ | 第 1/2 章量能条目条件式，免责话术各至多 1 次（守卫锁死） |
| R05 冻结快照 | ✅ | `analysis.py` `_snap_lines` 加强势板块 Top5 + 量能一行（4000 字上限内） |
| R06 全市场额/家数 | ✅ | `fundamentals_fetcher.fetch_market_breadth`（clist f6，5min 缓存，失败 `{}`）+ hub `get_market_breadth` |
| R07 商品别名 | ✅ | `_format_commodities` 别名表（WTI/BRENT/CL→原油 等），未命中回退前 6 条 |
| R08 hsgt | ⚠️ 口径调整 | 见 §3.1 R08 实施校正：按停更处理，**不给数值**；南向未接 |
| R09 as_of 扩展 | ✅ | 指数快照 / 板块 / 宽度 / hsgt 四源去重拼接，无源不标 |
| 契约 | ✅ | `api-contracts/analysis/llm-report-chat.md` 追加 §4「报告数据段（round58）」（8 条字段级断言） |

### 8.2 运行时验证（真实源，非 mock，24 项断言全过）

- R06：一次运行取到真实宽度（total=100 / up=21 / down=56 / 成交额 2.45e10 元）；另一次源不可达
  → `{}`（诚实空，无 0 家/0 元伪值）。push2delay 偶发 "Remote end closed connection"，已记录。
- R08：口径程序化解析为「北向资金」，判定 **停更**（最后可得 2024-08-16、已停更 773 天），
  `rows=[]`、`as_of=None`、无任何净流入金额进入 prompt。
- 情绪面：hub 预热后 payload 含 `advance_ratio/volume_ratio/margin_change`（M1 断点闭合；
  冷启动进程只有 `{index,label}`，120s 后台循环刷新即补齐——属既有设计，非本轮缺陷）。
- prompt 实测：真实板块名、4 条政策标题（国务院常务会议系列）、FRED 单一 us_10y=5.18、
  「输入未提供/暂无法验证」在数据段 0 次、英文商品名无泄漏。
- R196 同批：`get_portfolio_realtime` 返回 38 行，无「有标签无值」行。

### 8.3 偏离登记

1. **R08 数值部分不可得**（方案前提被真实数据推翻）——按停更口径实施，见 §3.1。
   若后续找到仍在更新的等价免费源，再补「近 N 日净流入」；本轮不编造。
2. **南向序列未接**（`symbol_map` 键需程序化解析，收益低于风险）→ `south_net` 恒 None。
3. **R06 与既有 `fetch_advance_decline_ratio` 未合并**：后者是因子/情绪后台热路径（无缓存、
   熔断语义不同），合并会给它引入未经评估的缓存层；R06 独立成函数（5min 缓存）。

### 8.4 验收期结论

pytest 全量 3340 passed / 0 failed；mypy 151 文件 Success；check_routes（路由未变）、
check_engine_purity、audit_async_blocking、P3-6 基线（320≤320）全过。
`patrol --full` L2-e2e FAIL 归类**环境性**（`::1` 解析失败 + 连接 STORM，known-env-issues §1.1），
非本轮回归。**实值端到端报告（真实 LLM 生成的 6 章报告）未在本轮验收**——LLM provider
403（见 round58-portfolio 文档 Part B），故 R01-R09 的 prompt 侧已用真实数据 + 单测双向锁定，
LLM 产出质量复测标 **待 403 修复后 + 交易时段**。

---

## 9. 交易时段复测（2026-09-29 周二 13:00-15:00 下午盘，commit 待回填）

> 窗口说明：2026-09-29 为**交易日**，13:00 下午盘开盘后开跑。方法：真实源 + 真实
> LLM，无 mock；HTTP 走进程内 `TestClient`（`::1` 字面量在本机解析不稳，见
> known-env-issues §1.1），异步任务端点那一轮**开启 lifespan**（否则任务 worker 不存在）。

### 9.1 通过项（实盘实证）

| 项 | 结论 | 证据 |
|---|---|---|
| **R04 模板收敛**（用户原始抱怨「3 处输入未提供/暂无法验证」） | ✅ **0 次** | 端到端 `llm-report/stream` 产出 2366-2432 字 / 6 章 / 28.2s / 无 SSE error；全文「未提供」+「暂无法验证」命中 **0** 次 |
| **组合设计端到端** | ✅ 真 LLM 报告 | task 132：`running(5s) → quick_ready(30s) → completed(110s)`；日志 `[design_pipeline] report saved to design_id=75 (6342 chars, quality=full)` |
| **R03 平衡型防御锚扩容** | ✅ 生效 | design 75 balanced 防御层 = **2 只**：`30年国债ETF鹏扬` + `黄金ETF华安`（改前仅黄金 1 只） |
| **R197 三元组克隆** | ✅ 未复现 | 三方案 0 个出现「≥3 标的同 (return_1m, return_3m)」元组 |
| **R198 信号标签唯一** | ✅ 生效 | design 75 报告正文：`综合信号 x0` / `因子综合分 x1`（脚注改名已在实盘报告可见） |
| **R199 divergence_detail** | ✅ 生效 | 策略检查兜底行实测 `divergence_detail = {signal_direction: neutral, factor_direction: neutral, factor_score: -0.314, threshold: 0.5, explanation: ...}`——正是 check143 曾 30/30 为 null 的主干 hold 分支 |
| **R196 「有标签必有值」** | ✅ 盘中 0 例外 | `/market/realtime/portfolio` 38 行、场外 15 只、null 价 0 只、`label_without_value=0`、`priced=38/38` |
| **R06 端到端**（§D） | ✅ | 直连路径 29.5s / 34.9s、`is_fallback=False`、`usage 10254 tokens` |
| **性能债：realtime/portfolio** | ✅ 大幅改善 | **0.84s**（round57 周末基线 16.67s，~20×） |
| **性能债：admin/llm/health** | ✅ 大幅改善 | **1.11s**（周末基线 15.55s，~14×） |
| **性能债：admin/factor-health** | ⚠️ 仍超阈值 | 6.59s（周末 6.75s；阈值 ≤2s）→ 维持性能债登记 |

### 9.2 未通过 / 环境性（逐项归因，不含糊）

| 项 | 现象 | 归因 |
|---|---|---|
| **R06 全市场宽度** | `fetch_market_breadth()` 3 次全返 `{}` | **源不可达**（push2delay；13:00 前曾成功取到 total=100/up=21/down=56/成交额 2.45e10，证明确为间歇性）。设计行为正确：回退 `{}` → prompt 走「（数据源暂不可用）」占位，未报 0 家伪值 |
| **R01 板块与风格段** | `compute_sector_momentum()` 连续 2 次返 **0 行**（各 ~14s，命中内部 15s 超时） | **源不可达**，非接线缺陷。`update_sector_cache` 只在 `if momentum:` 时写缓存，故空返回即保持空；`get_sector_momentum` 盘中不回退快照（设计如此，诚实降级）。同窗口 `hot_plates` 正常（11 行）→ 佐证是板块动量源单点问题 |
| **策略检查走异步任务时回落** | task 131：`report_quality=fallback` / `is_fallback=true`，summary `LLM 分析超时（15s 未返回…`，`因子覆盖 16.7%` | **新发现，需用户决策（见 §9.3）**：非本轮回归 |

### 9.3 新发现（超出本轮清单，待决策）

**N1：策略检查「数据空」档预算 15s < 现役 provider 实测延迟 27-31s**

- 链路事实（同一 key、同一 prompt 形态）：`_llm_timeout_for(data_quality)` 对
  `all_empty` 返 **15s**（`strategy_check.py:735-736`），本轮因子覆盖 16.7% 命中该档；
  而唯一可用 provider（`deepseek-flash`，强开 reasoning）实测 **27.2s / 29.5s / 31.5s**。
- 故 15s 档**在物理上不可能成功**——只要 provider 活着就必然超时兜底。
- 性质：**非本轮回归**。该预算阶梯写于「无 provider 可用」时期（当时恒落兜底，档位无实际影响）；
  R06 修好链路后该档位才第一次显形。design 报告不受影响（另一档 120s，实测 110s 完成 quality=full）。
- 建议（需拍板，本轮未实施）：`all_empty` 档 15s → 30s 起（与 `partial` 档对齐），或改为
  「按 provider 实测 p95 延迟取档」。**未擅自改**：属预算/时延权衡，且有
  `tests/test_round14_llm_budget_consistency.py` 锁定预算-重试一致性。

**N2：`app/tasks/startup.py:373` 调 `_kline_warmup_symbols()` 但该函数未定义于本模块**

- 实证：warmup 日志 `design-data warmup failed (non-fatal): name '_kline_warmup_symbols' is not defined`。
- 根因：该函数**只定义在 `app/main.py`**（同文件另有 `_kline_warmup_holdings_symbols`），
  `startup.py` 未导入；且 `main.py:26` 反向 import `startup.py`，**直接补 import 会成循环依赖**。
- 影响：design-data warmup 的 K 线预热段**从未执行**，被宽 `except` 吞成 non-fatal，
  该段 `_mark["success"]=False`（与 warmup 面板 `market_cache: success=false` 一致）。
  非功能性中断——设计任务按需取 K 线仍 110s 完成 quality=full——但预热收益丢失。
- 归属：**本轮两批 commit 均未触碰 `app/tasks/startup.py`**（`git diff 1e7a5c3..HEAD` 空），
  属存量缺陷。修法需把 helper 下沉到共享模块（`tasks/` 或 hub）再双向引用 → 动模块结构，需拍板。

**N3：warmup 30.8s 超 30s 预算阈值**（`instruments_sync 21.8s` / `indices_meta_sync 8.8s`）→ 维持性能债登记。

### 9.4 与「待交易时段复测」清单的对照

| 原清单项 | 本轮结论 |
|---|---|
| round57 #6 性能债（realtime / fh / llm-health） | ✅ 两项大幅改善，factor-health 仍超阈 |
| round58-market R06 实额/家数 | ⚠️ 源间歇不可达（行为正确，取数失败） |
| round58-market R08 hsgt 近 5 日 | ✅ 早已按「停更」口径落地（最后可得 2024-08-16），无「近 5 日」可取 |
| round58-market 端到端报告实值引用 | ✅ 报告真产出且 0 免责话术；板块/家数未引用系**源不可达**（非接线问题） |
| round58-portfolio R01 成长占比告警 | ✅ 口径正确：balanced 22.4% / aggressive 27.8% 均 ≤30% cap → 不告警（符合设计） |
| round58-portfolio R03 defense ≥2 | ✅ 实证 2 只（黄金+30年国债） |
| round58-portfolio R04/R05 `report_quality=full` | ⚠️ 直连路径达成；**异步任务路径**因 N1 预算档回落（待决策） |
| L2-e2e 环境性 FAIL | 本轮以进程内 TestClient 绕开 `::1` 解析问题完成上述实值验收；`verify_e2e.py` 本身仍待干净后端复测 |
