# round59 AI 投资顾问技术面问答能力（支撑位/压力位）

> 状态：**已实施（P0+P1 = R01-R14 全部落地；P2 = R15/R16/R17 暂缓登记）**。
> 实施范围经用户拍板为 P0+P1。实施期的探针取证推翻了本文三处前提，
> 修正方案与实测数据见 **§9 实施记录**（含 A1/B3 拍板结果与契约同步）。
> 本文 §1-§8 为原始方案（保留原始判断以便对照，**其中 4 处已被 §9 修正**）。
> 触发：用户在 AI 投资顾问提问「这轮A股下跌的支撑位会是怎么样的？」，回答为"仅凭当前快照，无法确认具体支撑位"（`portfolio.db` → `chat_sessions`，session `sess-008bc66ee5734992`，2026-09-28 21:57:53 北京时间）。
> 编号：round59（与两份 round58 同轮不同主题；round58 修的是 `/llm-report/stream`，本文修的是 `/llm-advice/stream`，两条链路同病未覆盖）。
> file:line 锚点核对时间：**2026-09-28 22:05（北京时间，DB 存 UTC）**。
> 运行时取证：后端进程 27320（`python -m uvicorn app.main:app --host :: --port 8000`，**无 `--reload`**，启动于 15:55:56）+ `logs/backend_stdout.log` + `token_usage.db` + `portfolio.db`。
> 验证窗口：**2026-09-28 为周一交易日、当前 22:05 已收盘**——纯函数/单测/prompt 渲染项当晚可闭环；指数日线切分、盘中价位、量能口径标「待交易时段复测（交易日 9:30-11:30 / 13:00-15:00 + 真实环境）」。

---

## 1. 根因映射（D2 证据链，全部实测/grep 实证）

### 1.1 用户实际收到的回答（原文摘要）

| 段 | 原文要点 |
|---|---|
| 结论 | 「**仅凭当前快照，无法确认 A 股的具体支撑位**。上证指数报 **3823.62 点**只能作为现价锚点……不能凭空设定 3800 点等目标」 |
| 判断依据 1 | 上证 -1.67%、沪深300 -2.22%、深成指 -3.44%、创业板 -4.53%、科创50 -4.06%；情绪 45/100 |
| 判断依据 3 | 「输入未提供成交额、北向/主力资金净流入及涨跌家数」；「行业榜单名称缺失，热力图无数值」 |
| 操作分析 | 「重点观察：前期低点、20日均线、成交量……」+「单只 ETF 偏离目标超过 ±5 个百分点再平衡」+「以上不构成投资指令」 |

### 1.2 缺失 → 根因表

| # | 现象 | 根因（file:line，2026-09-28 已核） | 类型 |
|---|---|---|---|
| **M1** | 无法给出任何支撑位 | `_build_advice_stream_prompt`（`backend/app/analysis/llm/reports.py:1391-1551`）注入槽位仅：市场背景（`:1405-1407`，**只有 `market_regime` 一个词**）/ 情绪（`:1409-1416`）/ 实时行情前 8 条 `名称:价(涨跌幅)`（`:1418-1426`）/ 资讯前 5（`:1428-1432`）/ 持仓前 5（`:1434-1441`）/ 板块·热点·热力·资金流（`:1451-1542`）。**零 K 线、零均线、零布林、零 RSI/KDJ、零前低/前高、零成交额/量能** | **采了没接线**（数据源全在，见 §1.3） |
| **M2** | 问支撑位、答板块轮动+再平衡 | `intent.py:14-38` 意图词表仅 `valuation/product/risk/event/rotation/allocation`，**无 `technical`**；「支撑位」零命中 → `classify()` 返 `general`（`intent.py:83-86`）→ 无条件追加「### 行业轮动分析框架」（`reports.py:1544-1549`，要求"分析最强/最弱板块+轮动方向+交叉验证"）+ 资金流段（`:1486-1495`）；叠加 `reports.py:1449` 「控制 800 字以内」→ 只能压缩成一句免责 | 人设错配（模板越权） |
| **M3** | 板块名在 prompt 里全是 `?` | `services/market_trends.py:113` 归一化输出 key 为 **`"sector"`**：`{"sector": str(r.get("sector_name","")), ...}`；而 `reports.py:1456` 只认两个 key：`item.get("sector_name") or item.get("name", "?")` → `sector` 命中不到 → 10 条板块全渲染 `- ?: (x.xx%)` | **字段口径断裂**（round58 已修 report 路径的 `_sector_entry`，advice 路径 `:1456` 未修） |
| **M4** | 每次调用先白等 ~6s，模型由系统随机决定 | `provider.py:55-86` `_zen_candidates()` 用 `zen_attempt_sequence()`（`:73-77`）把 Zen 目录里**全部 `-free` 模型**排成候选序列；实测 6 个连续 403 后才落到唯一可用模型。配置模型 `deepseek-v4-flash-free`（`provider.py:65`、`.env`）**从未被使用** | 配置失效 + 无健康序 |
| **M5** | 6 次 403 每次都重试，永不摘除 | `analysis/llm/gates.py:24` 的永久错误 403 特征表为 `not available in your country|Access restricted|Deposit required|credit insufficient balance`；opencode.ai 实返 **Cloudflare 裸 403**（`Server: cloudflare` + `x-opencode-log-id`，无上述任一文案）→ `_classify_permanent_error()`（`gates.py:152-179`）返 `False` → **不触发** `mark_long_cooldown` + `mark_excluded`（`gates.py:195-201`）→ 死模型永留在目录池 | 熔断漏判 |
| **M6** | 已暂存的 403 熔断没覆盖本链路 | 暂存 `client.py` 的 R05（`_r05_403_allow`/`_r05_403_record`）**只接进 `llm_complete_with_system`**（`client.py:574`/`:681`/`:739`）；投资顾问走的是 **`llm_complete_stream`（`client.py:298`）——完全没覆盖**（该函数只有 F8 通用熔断 `:335`/`:420`） | 修复落错函数 |
| **M7** | ConfigView 显示的 key 是假的 | `app_config` 表存在 `OPENCODE_ZEN_API_KEY='sk-x'`（2026-09-28 21:16 写入）。`config_manager.get()` **DB 优先**（`core/config_manager.py:100-104`），但真正发请求的 `provider.py:68` 用 `settings.opencode_zen_api_key`（启动时从 `.env` 载入）→ 该行**不影响调用**，却让 UI 显示一个不生效的 key | DB override 与运行时 provider 架构裂缝（误导性脏数据） |
| **M8** | 回答不来自最新代码 | 后端 15:55:56 启动且**无 `--reload`**；`reports.py` 改于 20:59、`client.py` 20:04、`analysis.py` 19:46 → **round58 Part A/B 暂存改动一行都没上线**；且 round58 目标端点是 `/llm-report/stream`，本链路未被覆盖 | 交付断链 |

### 1.3 关键量化证据

`token_usage.db` → `usage_records`（一次调用 = 多行，每候选模型一行）：

| id | function_name | model | success | sec | 备注 |
|---|---|---|---|---|---|
| 63478 | run_stream | `nemotron-3.5-lightning-free` | 0 | 0.8 | **403 Forbidden** |
| 63479 | run_stream | `mimo-v2.5-free` | 0 | 0.8 | **403** |
| 63480 | run_stream | `jev-1.13-free` | 0 | 0.8 | **403** |
| 63481 | run_stream | `ling-3.0-flash-fin-free` | 0 | 1.0 | **403** |
| 63482 | run_stream | `nemotron-3-ultra-free` | 0 | 0.8 | **403** |
| 63483 | run_stream | `longcat-2.5-preview-free` | 0 | 0.8 | **403** |
| **63484** | **run_stream** | **`space-bunny-free`** | **1** | **14.1** | **`prompt_tokens=1430` / `completion_tokens=976`** |

- **7 个候选里 6 个 403**：单次调用固定白等 ≈ 6s，且该代价在 21:52、21:57 两轮完全复现。
- **`prompt_tokens=1430`**：整份"投资顾问"上下文仅 1430 token —— 这是 M1 最硬的量化佐证（对照 `generate_news_summary` 仅 ~650-740 token 就能产出可用摘要）。
- 服务端响应头实证实际服务模型 ≠ 配置模型：`x-zen-model: space-bunny-free`、`x-opencode-upstream-model-id: space-bunny`（`logs/backend_stdout.log` 21:57:41）。

### 1.4 数据侧现状：**接线，不是新建能力**

| 能力 | 位置 | 状态 |
|---|---|---|
| 指数日线（~500 根 / 2 年） | `services/hub/_kline.py`（`KlineMixin`，`_KLINE_CACHE_TTL=86400.0` 于 `:15`；24h TTL + 磁盘持久化 + 过期标记；由 `services/market_data_hub.py:46` 混入 facade，`:118` 启动即加载磁盘缓存） | ✅ 现成 |
| 指数取数入口 | `KlineMixin.get_kline` / `refresh_kline`（`hub/_kline.py`；`market_data_hub.py:233` warmup 已预热 `_known[:40]`） | ✅ 现成 |
| `compute_ma` / `compute_macd` / `compute_rsi` / `compute_kdj` / `compute_bollinger` | `app/analysis/indicators.py:21/44/77/86/103` | ✅ 现成 |
| BOLL 下轨 = 动态支撑、上轨 = 压力 | `indicators.py:103`（`ma±2σ`，含 `bandwidth`） | ✅ 现成 |
| 支撑/压力/Pivot/Donchian/ZigZag | `factors/factor_definitions.yaml:2234/2247/1971/2261` 有定义 | ❌ **无 compute 函数**（本轮不依赖，见 §3 R02b） |
| `/market/indicators/{symbol}`、`/signal`、`/chart`、`/history` | `routers/market.py:582/621/656/62` | ✅ 端点存在，**LLM 链路零调用** |
| A 股宽基指数符号 | `000001` 上证 / `000300` 沪深300 / `399001` 深成指 / `399006` 创业板 / `000688` 科创50 / `000016` / `000905` / `000852`（`services/market_service.py:146-152` `_GLOBAL_INDEX_DEFS`；另见 `fetchers/china_market.py:491` `_SH_INDEXES`） | ✅ 现成 |

> 结论：**M1 的修复是把已有能力接进 advice prompt**，不需要新增数据源。⚠️ 但复杂度并非"零风险"——`market_data_hub.py:114-115` 实录冷 `refresh_kline` 需 **42-75s**，故 R01 写死"只读缓存 + 未命中降级占位"（见 §3 R01 硬约束、§6 第 7 项）。

---

## 2. 本轮口径拍板：支撑位用「多证据交叉 + 斐波那契回撤位」

### 2.1 ⚠️ 方向陷阱（本方案最高风险项，必须写死）

**下跌行情中，从本轮高点往下量 Fib，得到的是"反弹阻力位"，不是支撑位。**

设本轮下跌高点 `H_now`、当前价 `P_now`：

| 算式 | 语义 | **不得**标为 |
|---|---|---|
| `H_now − 0.382×(H_now − P_now)` | 从本轮高点起算的**反弹**目标 | ❌ 支撑位 |
| `H_now − 0.5×(H_now − P_now)` | 同上，50% 反弹位 | ❌ 支撑位 |
| `H_now − 0.618×(H_now − P_now)` | 同上 | ❌ 支撑位 |

**真正的支撑位必须取自「上一轮上涨段」的斐波那契回撤**：识别近 N 交易日内最后一根显著上涨段 `[L*, H*]`（`H*` 为本轮下跌起点），则

```
S1 = H* − 0.382 × (H* − L*)      # 上涨段的 38.2% 回撤
S2 = H* − 0.500 × (H* − L*)      # 50% 回撤
S3 = H* − 0.618 × (H* − L*)      # 61.8% 回撤
```

同时该上涨段的**反弹阻力位**（本轮下跌的向上目标）为 `L* + 0.382/0.5/0.618 × (H* − L*)`，与上面三个支撑位方向相反、**必须分行标注**，否则 LLM 会把阻力说成支撑 —— 这是本轮最容易产生硬错误的地方。

**负向断言（必须能失败）**：给定构造数据（已知 `L*`/`H*`），渲染出的支撑位必须满足 `S3 < S2 < S1 < P_now`；若任何一行把反弹阻力位写进支撑行 → **FAIL**。

### 2.2 支撑位证据分层（多证据交叉）

| 层 | 档位 | 依据（必须在回答里逐档给出） | 数据源 |
|---|---|---|---|
| **动态** | `MA20` / `MA60` | 「动态支撑，跌破则趋势转弱」 | `indicators.py:21` |
| **动态** | `BOLL` 下轨 | 「波动率下沿，非刚性支撑」 | `indicators.py:103` |
| **结构** | 近 60 / 120 交易日最低 | 「前低，破则打开空间」 | `_kline.py` |
| **结构** | 上一轮上涨段起点 `L*` | 「涨段起点」 | 同上 |
| **Fibonacci** | `S1/S2/S3` | 「上一轮上涨段 `[L*,H*]` 回撤 38.2/50/61.8%」 | 同上（**新纯函数**，§3 R02b） |
| **量能**（可选，缺失则整段省略） | 近 5 / 20 日均量比、成交密集区 | 「放量下跌 vs 缩量回踩」 | 日线 `volume`（**注意**：Sina/Tencent 主路径可能无 volume，见 §3 R05 探针） |

**降级纪律（防假完成）**：任一层无数据 → **该层整段省略**，并统一用 R80 规范占位「（数据源暂不可用）」；**禁止**用相邻层数值顶替、禁止 LLM 自行补一个"大致位置"。
**Fib 专项降级**：若未识别到显著上涨段（`H*−L*` 不足阈值或分形不稳定）→ **Fib 三档全部不输出**，并显式声明「未识别到有效上涨段，Fib 回撤位不可用」——**不得用任意两点硬凑一个 Fib**。

### 2.3 上涨段识别口径（可实现定义，待 §3 P1 探针验证）

1. 取近 `N=120` 交易日日线（`asset_type=index`, `period=daily`）。
2. 分形极值：左右各 `k=3` 根均为更低（低点）/更高（高点）。
3. 逆序扫描分形点，取**最后一对 `(L*, H*)`** 满足 `H* > L*` 且 `(H*−L*)/L* ≥ 5%`，且 `H*` 之后到 `P_now` 为单调下行段（允许 ≤2 根中间反弹）。
4. 若不满足 → Fib 不可用（走 §2.2 降级）。
5. **稳定性要求**：`k=3` 与 `k=5` 两组参数下 `L*/H*` 结论一致；不一致则输出「锚点不稳定」并禁用 Fib。

---

## 3. 实施清单

> 门禁治理（AGENTS.md 门禁替换制）：**本轮不新增任何 pre-commit / patrol 门禁段**，全部改动落在既有 16 段覆盖范围内（④前端 build / ⑨mypy / ⑪pytest / ⑮engine 纯度 / ⑥async 审计）。

### P0（止血：不新增外部数据源，超时风险零）

- **R01 指数技术面注入 advice prompt**：新增 `ctx["index_technical"]` 槽，对 `000001` + `000300`（+ `399006` 视耗时）取日线 → `indicators.py` 算 MA5/10/20/60 + BOLL 上下轨 + RSI + KDJ → 在 `reports.py:1418`「实时行情」之前插入「## 技术面」段，逐值标注。**每指数一行，含 `as_of`**。
  ⚠️ **硬约束：只读缓存，禁止在请求链同步 `refresh_kline`** —— `market_data_hub.py:114-115` 实录「refresh_kline **42-75s**，round28 §14.4 冷启动超时根因之一」。缓存未命中/已过期时：降级为「（数据源暂不可用）」占位 + 异步投递后台 refresh，**不得**让 SSE 首字节等待。优先复用 `market_data_hub.py:233` warmup 已预热的宽基指数。
- **R02a 支撑位纯函数**（放 `app/engine/`，过 `check_engine_purity.py` AST 门禁；签名 `def compute_support_levels(bars: list[dict], cfg: SupportCfg) -> SupportLevels`）：输出动态层（MA20/MA60/BOLL 下轨）+ 结构层（60/120 日低点）+ 上涨段 `[L*,H*]`。
- **R02b Fib 支撑位**（同文件，纯函数）：按 §2.1 公式输出 `S1/S2/S3` **与** `R1'/R2'/R3'` 反弹阻力位，**两族分行、方向标注**；锚点不稳/无上涨段 → 返 `None` 并附 `fib_unavailable_reason`。
- **R03 板块名口径修复**：`reports.py:1456` 的 `item.get("sector_name") or item.get("name", "?")` → 增补 `item.get("sector")`（对齐 `market_trends.py:113`）。
- **R04 403 认永久错误**：`gates.py:24` 的 403 特征补 `forbidden|access denied|log-id|x-opencode-log-id` 兜底 → 首次 403 即 `mark_excluded` + `mark_long_cooldown`（`gates.py:195-201` 已就位，无需新写）。
- **R05 R05 熔断补进 stream 路径**：把暂存 `client.py` 的 `_r05_403_allow` / `_r05_403_record` 同样接入 `llm_complete_stream`（`client.py:298-539`），对齐 `llm_complete_with_system:574/681/739` 的三处调用点。
- **R06 清理误导性 override**：删除 `app_config` 的 `OPENCODE_ZEN_API_KEY='sk-x'` 行；补单测锁「`config_manager.get()` 返回值 == provider 实际使用的 key」（暴露 M7 架构裂缝，先锁不修）。
- **R07 重启后端**：当前进程无 `--reload`，R01-R06 不重启不生效。

### P1（让人设对题 + Fib 锚点探针）

- **R08 `technical` 意图**：在 `intent.py:14-38` 增 `technical` 词表（支撑/压力/阻力/回撤/均线/量能/破位/前低/前高/布林/缺口/抄底/企稳），并插入 `_PRIORITY`（建议置于 `rotation` 之后、`allocation` 之前 —— 支撑位问题常含"买点/加仓"字样，需避免被 `allocation` 抢走）。契约同步 `api-contracts/analysis/advice-valuation.md §2-§3`。
- **R09 technical 专用模板**：`technical` 意图下**不注入**「行业轮动分析框架」（`reports.py:1544-1549`）与资金流段（`:1486-1495`），改为「**关键价位表（档位 | 点位 | 类型(支撑/阻力) | 依据）+ 触发条件 + 失效条件**」。
- **R10 Fib 锚点探针（D1 前置，R02b 实施前必做）**：单次探测脚本，对 `000001`/`000300`/`399006` 各取近 120 日线，实测：①日线可达性；②`k=3` vs `k=5` 锚点是否一致；③输出档位与合理性；④单指数计算耗时。**探测克制**：单次探测，失败后 ≥60s 间隔；**探针结论不成立 → R02b 不进实施清单**。
- **R11 prompt 顺序修正**：指令块（`reports.py:1443-1449`）从数据段**之前**移到**之后**（`:1551` 前收尾），避免被 8 个数据段淹没。
- **R12 字数上限**：technical 意图 800 → **1200**（`:1449`），非 technical 保持 800（价位表 + 依据放不下 800）。
- **R13 诚实拒答模板**：无技术面数据时，输出「缺哪些数 / 去哪看 / 判断规则」三件套，**禁止**只写"无法确认"（针对本次回答的具体病灶）。
- **R14 负向硬约束入 prompt**：显式写「支撑位与阻力位不得混列；无数据输出占位，禁止编造点位」（对冲 §2.1 符号风险）。

### P2（防复发 / 可观测）

- **R15 回传真实服务模型**：SSE `done` 元数据带**实际服务模型**（取响应头 `x-zen-model`），前端展示真实值而非配置值 —— 现在 UI 显示 `deepseek-v4-flash-free`，而实际是 `space-bunny-free`，属展示性撒谎。
- **R16 403 失败率告警**：`token_usage` 面板加「403 占比」（>30% 告警）。当前 6/7 静默烧 6s 无任何提示。
- **R17 round58 scope 扩展**：把 `/llm-advice/stream` 纳入 round58 缺数治理清单（sector/量能/成交额），避免 report 修完 advice 再犯。

---

## 4. 契约先行

- **只追加、不重写**：`api-contracts/analysis/llm-report-chat.md` 追加「投资顾问技术面数据段（round59）」一节；`api-contracts/analysis/advice-valuation.md` 追加 `technical` 意图与词表（§2-§3）。
- 新增契约字段断言：
  - `ctx.index_technical[]`：`symbol / ma5 / ma10 / ma20 / ma60 / boll_upper / boll_lower / boll_mid / rsi / kdj_j / as_of`（`as_of` 缺失 → 禁引用该值）
  - `support_levels`：`{dynamic:[{level,value,kind,basis}], structural:[...], fib:{s1,s2,s3,resist_r1,resist_r2,resist_r3,anchor_low,anchor_high,fib_unavailable_reason?}}`
  - 板块名断言：prompt 板块段**不得出现 `?`**
- 接口 schema 不变（仍为 `/analysis/llm-advice/stream` SSE）。

---

## 5. 测试（T4：**不开新文件**，并入既有主题文件；外部网络/LLM 一律 mock）

| R | 宿主文件 | 负向断言（必须能失败） |
|---|---|---|
| R01 | `tests/test_llm_context_market.py` | `index_technical` 缺 bars 时为 `None`/`{}`，**不得**填 0 或占位数值；prompt 无 MA 段 |
| **R02b** | `tests/test_allocation_engine_fixes.py`（engine 纯函数宿主） | **构造数据下 `S3 < S2 < S1 < price`**；`fib` 与 `resist` 两族不得互相出现在同一族列表；无上涨段时 `fib_unavailable_reason` 非空且**不得**输出任何 fib 数值；`k=3`/`k=5` 不一致时禁用 fib |
| R03 | `tests/test_advice_p0a_slots.py` | 只含 `{"sector": "半导体"}` 的板块行渲染出**板块名**（非 `?`） |
| R04 | `tests/test_llm_circuit_state.py` | 裸 403 body（`Server: cloudflare` + `x-opencode-log-id`，无特征文案）→ `mark_excluded` 被调用；二次 `zen_attempt_sequence` **零**该模型 |
| R05 | `tests/test_llm_circuit_state.py` | stream 路径连续 2 次 403 → 后续调用该 provider **零探测** |
| R06 | `tests/test_cache_persistence.py` | DB override 与 provider 生效 key 不一致时**测试失败**（暴露 M7） |
| R08 | `tests/test_advice_intent_v1.py`（**当前被暂存删除，需先恢复**） | 「支撑位」「回撤到多少」「均线在哪」必须命中 `technical`；含「买点」的技术问**不得**被 `allocation` 抢走 |
| R09 | `tests/test_advice_p0a_slots.py` | technical 意图下 prompt **不得**出现「行业轮动分析框架」；非 technical 意图下**必须**出现 |
| R12/R13 | `tests/test_report_quality.py` | technical 意图下字数上限断言为 1200；无技术数据时输出含「缺哪些数/判断规则」而非仅「无法确认」 |

**契约门禁**：round58 文档 §5 的「不开新文件」约定继续遵守；`check_routes.py` 覆盖下本轮无新路由，不触发。

---

## 6. design-checklist 8 项对照

1. **可行性探针**：§3 R10 已列为 R02b 的**前置门禁**（探针未做/结论不成立 → Fib 不进实施清单）。其余 R01-R06 依赖的能力均为**已在生产的现成函数**（`indicators.py:21/103`、`_kline.py:15` TTL + `:300` Semaphore(5) + `:309` 20s 超时、`gates.py:195` 熔断三件套），无新假设。**本文档不含探针输出**——实施轮第一步必须补 §3 R10 的实测命令与结果。
2. **证据链**：§1.2 全部 `file:line` 已 grep 实证；§1.3 为 `token_usage.db` 逐行实测（6×403 + 1×200 + `prompt_tokens=1430`）；§1.4 为能力盘点含**明确的负向结果**——`technical.pivot.classic`/`technical.pivot.fib`/`technical.donchian.upper`/`technical.zigzag.zigzag` 在 `factor_definitions.yaml:2234/2247/1971/2261` 有定义，但 `rg 'pivot|donchian|zigzag|keltner' backend/app/factors/*.py` **零命中** → 无 compute 函数。**唯一未实测项**：§2.3 上涨段识别算法在真实日线上的锚点值 → 由 R10 探针补齐，不得先写码后补证据。
3. **验证窗口**：文档头已标注。纯函数/单测/prompt 渲染当晚可闭环；**Fib 锚点与量能口径标「待交易时段复测（交易日 9:30-11:30 / 13:00-15:00 + 真实环境）」**；另需在**下一个交易日收盘后**复测一次（当日 K 线定稿后 `as_of` 才可信）。
4. **非兜底数据**：§2.2 已定死「缺层整段省略 + R80 占位」；§2.2 Fib 专项降级「无上涨段则禁用 Fib，不得硬凑」；§5 每个 R 都有**能失败的负向断言**（含"缺 bars 不得填 0"、"不得出现 `?`"、"不得同时报 200/非空"）。
5. **真实调用点**：R01/R03/R04/R05/R06/R08 改动点全在生产链（`routers/analysis.py:587` → `llm_context.build_full_context` → `reports.py:_build_advice_stream_prompt` → `client.py:298`）。R02a/R02b 新函数由 R01 消费（engine 纯函数 → hub 编排 → prompt），**无 0 引用项**。
6. **四态 UI**：本轮**无新增前端页面/组件**。R15 改 SSE `done` 元数据 → 前端模型名展示复用 `AiAdvisor.vue` 既有渲染（已有 loading/错误态，见 `logs/` 实证流式可用），不新增态。若实施中发现模型名展示需新字段，再回查此项。
7. **复杂度审计**：R01/R02a/R02b **零新增网络调用**（走 `_kline.py:15` 24h TTL + 磁盘缓存，命中即纯内存）。循环内无 IO（切片/排序纯内存）。R10 探针为一次性脚本，**不进请求链**。⚠️ **已识别真实风险**：`market_data_hub.py:114-115` 实录冷 `refresh_kline` 耗时 **42-75s**（round28 §14.4 冷启动超时根因）→ R01 因此写死「只读缓存 + 未命中降级占位 + 异步 refresh」（见 §3 R01 硬约束），**不新开并发、不在请求链同步建库**。
8. **已知问题模式**（对照 round14 §4 五类）：
   - **格式断言**：R03 负向断言直接锁「不得出现 `?`」，不用 `len>0` 蒙混；
   - **mock 理想输入**：R01/R02b 的负向断言**全部覆盖全空/异常输入**（缺 bars、无上涨段、k 参数不一致、板块只有 `sector` key）；
   - **契约盲区**：§4 已先于代码写断言（Fib 两族分行、方向标注）；
   - **CSS 零覆盖**：不涉及；
   - **降级无门禁**：§2.2 + §5 双重覆盖（占位不得断言"正常"）。

---

## 7. 验收

- **开发期**：受影响测试文件 + mypy；`python scripts/patrol.py --diff`。
- **验收期**：全量 pytest 1 次 + `python scripts/tests_ok_marker.py --mark`；`verify_e2e.py` 全 PASS。
- **运行时（周一 22:05 已收盘，可测子集）**：
  1. `rg` 确认 `market_trends.py:113` 的 `"sector"` key 在 `reports.py` 有消费点，且 prompt 板块段无 `?`；
  2. 停掉/绕开 403 后，`usage_records` 单次调用**候选行数 = 1**（不再 7 行轮盘）；
  3. prompt 渲染断言含 `上证 MA20 / BOLL 下轨 / 前低 / Fib S1-S3 与 R1'-R3'` 且两族分行；
  4. 端到端复问「这轮A股下跌的支撑位会是怎么样的？」——内容断言：出现**具体点位数字 + 依据列 + 方向标注**，且**不得**出现"无法确认"式空转。
- **待交易时段复测（交易日 9:30-11:30 / 13:00-15:00 + 真实环境）**：
  1. 盘中重问一次，确认 `as_of` 与盘中价一致、`_stale` 未误标；
  2. Fib 锚点在下一交易日收盘后复测（K 线定稿）；
  3. 量能档（近 5/20 日均量比、成交密集区）在主路径带 volume 的源上复测 —— 若 Sina/Tencent 主路径无量（round58 M5 同构问题），整层按 §2.2 省略，**不得**用 mootdx 单源的量冒充全市场口径。

---

## 8. 与 round58 的关系 / 不在本轮范围

- **互补**：round58 Part A 修 `/llm-report/stream` 的缺数（sector/量能/成交额/政策），本文修 `/llm-advice/stream` 的技术面缺数 + 403 熔断漏判。两者共用 `market_trends`/`_kline`/`indicators` 数据层，不重复造源。
- **不在本轮**：① round58 已暂存改动的提交（保持暂存态，实施轮按白名单逐文件 `git add`，禁止 `git add -A`）；② `pivot`/`donchian`/`zigzag` 的 compute 函数实现（YAML 有定义但本轮不依赖，Fib + 均线 + BOLL + 结构低点已足够）；③ 盘中实时支撑位的 tick 级追踪（当前为日线级，日线口径已在 §7 标注复测窗口）；④ 429 配额闸与 rate-limit 治理（另一条链路，本轮只治 403）。

---

## 9. 实施记录（2026-09-30）

> 实施范围：**P0 + P1（R01-R14）**——用户拍板，P2（R15/R16/R17）暂缓登记于 §9.6。
> 下文 §9.1-§9.5 记录**实施期推翻本文前提的四处取证**，以及据此的方案修正。

### 9.1 拍板状态核对（实施前置，发现三处文档状态漂移）

| 漂移项 | §8/§5 记载 | HEAD 实际（`e676afa`） | 处置 |
|---|---|---|---|
| round58 改动 | §8①「暂存态，白名单逐文件 add」 | **已提交** `03ed659`，暂存区为空 | 漂移记录；仍用选择性 `git add` |
| R08 测试宿主 | §5 `tests/test_advice_intent_v1.py`「暂存删除，需先恢复」 | 已被 `03ed659` 的 F1 **合并删除**（328→320），无可恢复版本 | 改挂既有宿主 `tests/test_advice_p0a_slots.py`（其 §124 注释已声明承接 L1v2 意图契约） |
| R04 前提 | M5「`gates.py:24` 特征表缺 403 兜底」 | `03ed659`（22:57，**晚于**本文写成时间 22:05）动过 `gates.py` | 逐行复核后仍需实施，但真实缺口比 M5 所述更深（见 §9.3） |

### 9.2 R10 探针实测（§3 R10 是 R02b 的前置门禁）—— 两轮探针，全部实测

**探针 1（cache 路径）结论**：§1.4 假设「指数日线走 `services/hub/_kline.py` 现成缓存」**不成立**。
`refresh_kline` 硬编码 `asset_type="A"`（`hub/_kline.py:308-310`），而
`china_market.py:1615` 只有 `asset_type=="index"` 才走 `fetch_index_history`。
故 A 股路径下缓存里的 `000001` 是**平安银行**（实测 `close=11.57`、量 89M），
而 `000001` 同时是上证指数代码（`_SH_INDEXES`，`china_market.py:491`）——
若按 R01 原样实施，prompt 会写下「上证指数 MA20=11.68」这类**静默错数据**。
同批实测：`000300` 该路径 **0 行**；`399006` 正确可达。

**探针 2（index 路径 + 涨段回溯）结论**（用户拍板 A1 + B3 后执行）：

| 指数 | index 路径 | 关键实测 |
|---|---|---|
| `000001` 上证 | ✅ 8736 行（1990-12-19 起）/ **0.8s** | `close=3842.195`（真实上证；§1.1 记录 09-28 为 3823.62，09-30 涨至 3842，口径自洽） |
| `000300` 沪深300 | ✅ 6003 行（2002-01-04 起）/ **0.4s** | `close=4357.616`；**无任何涨段的回撤区覆盖现价** |
| `399006` 创业板指 | ❌ **0 行** | 坐实 `fetch_index_history:1526` 硬编码 `f"sh{code}"` 的前缀 bug（399xxx 是深市指数，被请求成 `sh399006`） |

**探针同时证伪了 §1.4 的两处风险预估**（利好）：`refresh_kline` 拉 3 个指数仅 **4.8s**
（本文担心的 42-75s 是全量 warmup 口径）；指标计算 **2.1ms**（首个 334ms 为 pandas_ta 预热）；
日线**带 volume** → §2.2 量能层可做。故 R01 的超时硬约束守得住。

### 9.3 实施期推翻的前提（四处，均以实测为准）

**① §2.1 的 `S3 < S2 < S1 < P_now` 强制断言只在上涨趋势成立。**
实测 000001：锚点 `L*=3741.11 / H*=3967.68`，`S1/S2/S3 = 3881.13 / 3854.40 / 3827.66`，
现价 **3842.20 落在回撤区内部**（`S3 < P_now < S1`）→ `S1 < P_now` 为假，断言不成立。
而提问场景恰恰是下跌行情，故该断言在本轮场景下**永远无法满足**。
**修正**：改为恒真不变式——每档按与现价的位置定 `kind`
（`< price_now` → `support`，`> price_now` → `resist`，`==` → 不输出），
断言「标 support 必在现价下方 / 标 resist 必在上方 / 两族不混列」。

**② §2.1 的「反弹阻力位」族与支撑族代数恒等，是重复标注。**
`L* + r·span ≡ H* − (1−r)·span` ⇒ `R(38.2%)≡S(61.8%)`、`R(50%)≡S(50%)`、
`R(61.8%)≡S(38.2%)`。同时输出会让模型在同一答案里读到「支撑 3827.66」与
「阻力 3827.66」两个互斥标签。**修正**：取消该族，方向由每档 `kind` 承担。
（§2.1 只警告了「从本轮高点往下量得到的是阻力」，漏了本条恒等性。）

**③ M5 的真实缺口比所述更深：403 特征串在响应「头」里，不在「体」里。**
§1.3 的取证来自响应**头**（`Server: cloudflare` + `x-opencode-log-id`），
而 `_classify_permanent_error` 只读 `resp.text`（响应**体**），且空体直接 `return False`
——即使补了正则也仍会漏判。**修正**：特征匹配改为「响应头 + 响应体」联合扫描。
刻意**不**把「任意空体 403」判为永久：`mark_excluded` 会写入 `app_config` 的
`llm_excluded:<provider>:<model>` 并**跨重启生效**，误摘可用模型的成本高于多试一次。

**④ M7 的前提「DB override 不影响调用」不准确。**
实测 `OPENCODE_ZEN_API_KEY` **在** `provider._HOT_RELOAD_KEYS` 中，且
`routers/admin.py:242` 在 admin PUT 后调 `refresh_provider_chain` 把 DB override
patch 进 settings ⇒ 经 admin 端点写入的 override **是会热生效的**。
真实缺口是「**直接写 DB 绕过 admin handler → 不触发热加载**」。
**修正**：R06 处置改为「删除绕过热加载留下的占位行 + 测试锁住该 key 仍在
`_HOT_RELOAD_KEYS` 中」，而非断言「override 不该存在」。

### 9.4 与 §3 清单的偏差（含范围收窄）

| R | 计划 | 实际 | 依据 |
|---|---|---|---|
| R01 | 对 `000001`+`000300`(+`399006` 视耗时) 取日线 | **`000001`+`000300`**，独立命名空间缓存键 `idx:<symbol>`；`399006` 不做 | A1 拍板 + 探针（`399006` index 路径 0 行，前缀 bug 需另开 round） |
| R02b | Fib 三档 + `R1'/R2'/R3'` 两族 | Fib 三档 + 逐档 `kind`；**取消 R' 族** | §9.3② 代数恒等 |
| R05 | 「stream 路径**完全没覆盖**」 | **只读不写**：`:335` 已有 `_r05_403_allow`，缺的是 `_r05_403_record`（函数内零调用） | 范围收窄为补 record（403 连击 + 成功/空流清零） |
| R06 | 删 override + 锁「`config_manager.get()` == provider 生效 key」 | 删除占位行 + 改锁「该 key 仍在 `_HOT_RELOAD_KEYS`」 | §9.3④ 前提修正 |
| R08 | 词表含 `technical` | 同，但**裸 `回撤` 不收**（改 `回撤位/回撤到/回踩到/反弹到`） | 裸 `回撤` 已是 `risk` 主词且 `risk` 优先级更前，收裸词会让「回撤太大怎么办」误判 technical；契约 §3.3 已同步 |

### 9.5 验收结果

**契约先行**：`api-contracts/analysis/llm-report-chat.md` 追加 §5、
`advice-valuation.md` 追加 §2/§3.3/§4.5/§4.6/§6/§8/§10（均为**追加**，未重写整文件）。
`check_routes` 全 OK。

**开发期**：受影响 6 个测试文件 **166 passed**；mypy 9 文件 Success；
`check_engine_purity` OK / `audit_async_blocking` PASS(153) / `check_test_baseline` 320≤320 /
`check_routes` OK / `audit_unused_symbols` 0 增长。

**全量（验收期）**：`pytest -n auto` → **3378 passed / 11 skipped / 0 failed**（89.8s）。
首次全量出现 1 红（`test_factor_compute_injects_mv.py::test_nav_one_uses_long_running_executor`）；
定向实验确认**污染源在本轮测试代码**（排除本轮 6 个测试文件后 3212 passed / 0 failed）——
R04 用例对进程级全局 `model_catalog._exclusions` 只 `clear` 未还原，
已改为快照/还原隔离，复跑全量归零。

**运行时（真实环境，非窗口依赖项）**：
- live hub 产出 `index_technical=2`，`ctx_support_levels_keys=[000001,000300]` ⇒ 生产接线打通；
  上证 `close=3842.2 / ma20=3905.64 / boll_lower=3821.74 / rsi=40.35`，
  支撑 `[3821.74, 3741.11, 3827.66]`、阻力 7 档；沪深300 `fib_reason=no_upleg_brackets_price`。
- **端到端复问原问题**「这轮A股下跌的支撑位会是怎么样的？」→ 内容断言 9/9：
  17 个真实档位、依据列（「上涨段回撤61.8%」「BOLL下轨」「近60日低点」）、
  方向标注分族、**无「无法确认」式空转**、未回落轮动框架、
  `prompt_tokens=2380`（事故时 1430）。诚实拒答三件套**实际触发**（沪深300 Fib 不可用）。
- `verify_e2e.py` **234/249**，15 项 FAIL 全部归入 STORM/环境性（1.1s 风暴门禁），
  与既有基线同型，非本轮回归。

**已知偏差（诚实登记）**：模型实际输出 **1605 字符 > 1200 字上限（超 34%）**。
R12 的预算是软约束，方向/依据/触发/失效条件均齐备，不阻断交付；
若需硬控字数需在 prompt 侧加更硬的截断指令或后处理裁剪。

**待交易时段复测（交易日 9:30-11:30 / 13:00-15:00 + 真实环境）**：见 §7 原列三项
（盘中 `as_of` 一致性、`_stale` 未误标；Fib 锚点在下一交易日收盘后复测；
量能档在全市场口径源上复测）。本轮为盘后验证，日线已定稿。

### 9.6 暂缓项登记（P2，本轮未实施）

| R | 内容 | 暂缓原因 |
|---|---|---|
| R15 | SSE `done` 回传真实服务模型（`x-zen-model`），前端展示真值 | 涉前端改动（触发 pre-commit ④ build 段），本轮范围外 |
| R16 | token 面板「403 占比」告警（>30%） | 涉前端 Token 面板改动 |
| R17 | 把 `/llm-advice/stream` 纳入 round58 缺数治理清单 | 需改 round58 文档，与 §8①「round58 改动保持暂存」冲突 |

**另记一条新发现（不属本轮清单）**：`fetch_index_history:1526` 的 `sh` 硬编码前缀
使**全部深市指数**（399xxx / 399001 / 399006 等）在 index 路径不可达，
需单独一轮修复（按 code 前缀推导交易所，而非固定 `sh`）。