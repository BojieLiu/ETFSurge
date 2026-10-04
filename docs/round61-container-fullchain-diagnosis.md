# round61 容器全链路诊断 — round57/58×2/59 批复验（2026-10-03 周六盘后/周末）

> 独立 round61 文档，**不改写** round56/57/58×2/59 任何一份（它们只读作对照基准）。
> 诊断对象：HEAD `683040f`（round60 投顾 gold set + 八项修复批全部落地后的状态）。
> 验证环境：Docker Engine 29.7.2，prod profile + diag overlay（`PROFILE_WARMUP=1`）。
> 验证窗口：**2026-10-03 为周六非交易日**（11:26 起容器，18:51–21:00 诊断）——
> 实时类结论一律标「周末形态」；**涉外部行情源的结论标「待交易时段复测」**。
> 探针产物：`C:/Users/Public/etf_probe/`（build60-*.log / report60.sse / advice60.sse /
> report60_full.txt / advice60_full.txt / struct60.txt / r197.txt / prec.txt / fb60.txt /
> macro60.txt / ctx.txt / m2.txt / ms.txt / lh_*.json / lh60.txt / dom_*.html / dom60.txt /
> e2e60.log / e2e_fails.txt / dhc60.log / pytest60.log / vitest60.log / patrol60.log /
> ws60.py / feoverlay60/），会话级临时目录不入仓。
>
> **编号说明**：本文用 **round61** 而非 round60——round60 已被投顾 gold set 批占用
> （commit `6684282`…`683040f`，方案见 `docs/advice-goldset-design.md`）。

---

## 0. 执行摘要

| # | 结论 | 状态 |
|---|---|---|
| 1 | **构建受阻后绕行成功**：`registry-1.docker.io` 仍 blocked（v6 黑洞，与 round57 同型）；backend 缓存基座一次建成（13.6s）并**逐文件 SHA256 验明 = HEAD**（8 个关键文件全 MATCH）；frontend 走宿主 `npm run build`（8.2s）+ overlay 镜像（1.1s） | ⚠️ 环境性 / 镜像内容 ✅ |
| 2 | **round57 §9.1 全表复测：10 项中 8 项 PASS、R196 口径需扩展、性能债 2 项转好 1 项仍超阈** | ✅ 维持 |
| 3 | **round58-market R04 模板收敛：生产端到端 6 章 1774 字，「未提供」+「暂无法验证」命中 0 次**；R03b 美债单口径（5.24 唯一值）✅；R03a 政策条零命中整段省略 ✅；R06/R01 源不可达→诚实降级 ✅ | ✅ |
| 4 | **round59 技术面问答：生产端到端通过**——10 个真实档位 + 依据列 + 方向分族，「无法确认」0 次，未回落轮动框架，`prompt_tokens=2333`（事故时 1430），答案 1130 字（≤1200 上限） | ✅ |
| 5 | **round58-portfolio R03 防御锚扩容实证**：balanced/防御型 defense = 2 只（30年国债 + 黄金）✅；R01 成长集中度**在 e2e 的独立设计上触发**（balanced 4 只 > 上限 3 只）✅ | ✅ |
| 6 | **round57 R196/R198/R199 三项修复全部实证生效**：38 行 null 价 0 / `label_without_value=0`；`综合信号 ×29` + `因子综合分 ×3`（标签唯一）；`divergence_detail` 28/30 非空（曾 30/30 null） | ✅ |
| 7 | **round57 R191 维持关闭**：check175 复合分 13 个离散值，`-0.21` 零出现 | ✅ 维持 |
| 8 | **N1 复发并首次闭环取证**：check175 `report_quality=fallback`（`LLM 分析超时（30s 未返回…）`），同窗口 `usage_records` 的 `run` 调用 **34.2s 成功** → 外层 30s 分档先砍。round58 §9.3 的量化结论（真实负载骑在 30s 边界）本轮再次坐实 | ⚠️ **R206** |
| 9 | **N4 活体复现**：check 173/174（**今日** 03:50 / 09:44 UTC）`summary="组合为空"` 却 `report_quality=full` / `is_fallback=false` / `llm_layer_ok=true` | 🐛 **R207** |
| 10 | **R197 三元组克隆复发且升级为常态**：19 个标的塌成 **5** 个 factor 块（曾 6 标的共享一组）。根因 `_pool.py:113` 缺键补 `0.0` + `allocation_engine.py:923` `round(v,3)`，**已用 9 个独立键 1e-13 精度的算术证明**（N=37，恰 3 个有 K 线） | 🐛 **R202** |
| 11 | **R200 新发现（P0）**：`/market/search?kind=all` 的 **A 股 ETF 段恒空**——`search_etf` 回退路径把市场码写进 `asset_type`（`'A'`），router 按 `asset_type=="etf"` 过滤全丢。producer 2026-07-15 错 / consumer 2026-07-31 加，**死了约 9 周**；e2e 每轮都报 `A股搜索(510300) 0 条` 却被归入「环境性」 | 🐛 **R200** |
| 12 | **R201 新发现（P0）**：`fetch_money_supply` 取 `iloc[-1]` 拿到 **2008年01月** 数据且 `stale=false`；LLM 报告据此断言「货币活跃度较高」（真值 M1 **4.1%** / M2 **7.5%**）。`_stale_note` 对 `YYYY年MM月份` **fail-open** | 🐛 **R201** |
| 13 | **R203 新发现（P1）**：`fetch_concept_sectors` 源失败时返回 **40 条硬编码 POPULAR_CONCEPTS 占位**（全 0 数值 + 空 code）；`_search_sectors` 因 `not code` 跳过 → 板块搜索恒 0。叠加 `run_sync(timeout=10)` 包裹实测冷 **25.9s** 的取数 → 必然超时 | 🐛 **R203** |
| 14 | **R204（P2）**：`llm_complete_stream` **只写不读** R05 熔断（`_r05_403_record` 有 3 处调用，`_r05_403_allow` 零出现；`:419-420` 注释说反）；advice SSE 路径不跳过被拉黑 provider | 🐛 |
| 15 | **R205（P2）**：后台新闻摘要每 120s **6 次串行 LLM**（cap=6=3+2+1），实测 **51 次/小时 / LLM 占墙钟 12%（5min 窗口 82%）/ 9 次失败 17.6%**，与交互路径争配额 | 🐛 |
| 16 | **R208（P3）**：`correlation_warnings[].combined_weight` 结构性过期（快照 `:1822` → 拷贝 `:1827` → 合并 `:1845` 不重算 + 编排层 3 次权重突变），实测 3 个值全部由 coarse 5% 档位精确解释；金夹具唯一覆盖的 pair 是豁免对，故不可见 | 🐛 |
| 17 | **R209（P3）**：`realtime/portfolio` 38 行**全部**无 `as_of`/`data_source`——R196 只保证「有标签必有值」，反向「有值无时间戳」无人管；watchlist 同样 `as_of=null` | 🐛 |
| 18 | **R211（P3，方向反转）**：round60 memory 担心的「契约 §3 列着代码早已不含的词」**实测 0 例**；真实缺口是反方向的——`intent.py` **8 个载荷词未进契约**，`valuation/event/rotation/allocation` **四族无 §3 表**，契约 §2 示例 `怎么配` 字面不可路由 | 📝 |
| 19 | **R212（流程债）**：`check_test_baseline` **323 > 321**（round60 自己新增 2 个测试文件未提 BASELINE，与 round57 F1 同型）；ruff **22 errors**（15 I001 + 5 F401 + 2 F811 + 1 B023），round59 登记的 3 F401 已长成 22 | ⚠️ |
| 20 | **R214（文档污染）**：round57/58×2 三份文档的 §9「交易时段复测（2026-09-29）」是**同一份全文复制到三处**，含与各文档主题无关的 N2（`startup.py` NameError）、N4（strategy_check 空组合） | 📝 |
| 21 | **回归基线**：pytest **3583 passed / 11 skipped / 0 failed**（112.95s）；vitest **48 files / 579 passed**；DHC **13/13**（130s）；`verify_e2e` **267/276（9 FAIL）**；`check_routes` 全 OK / `check_engine_purity` OK / `audit_async_blocking` PASS(153) | ⚠️ 9 FAIL 见 §2.9 |
| 22 | **Lighthouse（软门禁）**：`/` perf **66/67/80/82**（中位 73，round57 66/67）、a11y 96、BP 96、SEO 91、CLS 0.002–0.041、TBT 140–620ms；`/dashboard` perf 98/99 — **仍是 404 页**（DOC-2 维持） | 📋 perf ≥60 / CLS <0.1 双硬门禁 PASS |

---

## 1. 环境构建与启动

- **Docker daemon 初始为停机态**（`com.docker.service` Stopped、`docker info` 报
  `npipe:////./pipe/dockerDesktopLinuxEngine` 不存在）→ 拉起 Docker Desktop 后 20s 内就绪
  （Server 29.7.2）。**这是 round57 §环境步骤 0 前置预检的又一次实证**：daemon 没起时
  后续 `build` 会报误导性错误。
- **无遗留容器**（`docker ps -a` 空），直接 `up -d --no-build`（3.0s）。
- **backend 构建受阻后的处置**：
  - `docker compose … build backend` **一次建成 13.6s**（COPY 层缓存命中）。
  - `… build frontend` **失败**：`node:24-alpine` → `registry-1.docker.io:443` v6 黑洞，
    `connecting to registry-1.docker.io:443: dial tcp [2a03:2880:…]:443: connectex`。
    与 round57 §1 **同型同因**（构建日志 `build60-frontend.log`）。
  - **overlay 绕行**：宿主 node v24.19（与镜像 node:24 主版本一致）`npm run build` **8.2s**
    → 经 `feoverlay60/`（外部上下文，绕开 `frontend/.dockerignore` 对 dist 的排除）
    `FROM etf_surge-frontend:latest` + `COPY dist` → **1.1s**。
- **镜像 = HEAD 的逐文件验明**（round57 方法，不靠 COPY 缓存显示）：`docker cp` 8 个关键文件
  与宿主 SHA256 对比，**8/8 MATCH**：`analysis/intent.py`、`services/hub/_valuation.py`、
  `analysis/llm/reports.py`、`routers/analysis.py`、`analysis/llm/client.py`、
  `tasks/startup.py`、`engine/support_levels.py`、`services/portfolio/strategy_check.py`。
- **warmup 30.6s 超 30s 预算**（top3：`instruments_sync` 22.3s / `indices_meta_sync` 8.1s /
  `etf_cache` 0.2s）——新旧双格式告警并存（30.6s + 30.7s），**R179 维持暂缓**；
  N3 维持性能债登记。
- **warmup 期间三段数据源失败**（周末 + 源不可达，非回归）：
  `fetch_em_industry_sectors pn=1 failed: Remote end closed connection`、
  `fetch_em_concept_sectors pn=1 failed`、
  `sync_instruments` **A股个股段 / A股ETF段 / 港股段 三段全 FAILED**（全部数据源不可用）；
  港股ETF段 0 rows。
- **启动期 LLM 试探**：Zen 目录 7 个模型逐个 403 被永久排除
  （`[circuit] opencode_zen:<model> permanent error → long-cooldown + excluded + OPEN`，
  每个 ~0.8–1.1s，18:51:31→18:51:55 共 7 次 ≈ 6s）→ round58 §D 残留 1
  「熔断状态不跨进程」**维持**（R205）。
- **定时刷新**：regime 每 ~125s（20:34:20 / 20:36:25 / 20:38:31 …）、news 每 ~120s
  （h=15 m=1~2 g=8，标注 `fallback`）✅。
- `docker image prune` 未执行（构建无 dangling 新层，round57 实测回收 0B）。

### 1.1 overlay 副作用（R213，环境/方法层）

`COPY dist /usr/share/nginx/html` 是**目录合并而非替换**：容器内 `assets/` 累积到
**94 个文件**，宿主 `dist/assets` 只有 **45 个**。功能无影响（`index.html` 指向新 hash
`index-CxCcoyv-.js` / `AiDesign-CU6nx3xP.js`，与宿主 dist 一致），但每轮 overlay 都在
docroot 留残骸，且会让「assets 数量」类断言失真。**建议**：overlay Dockerfile 改为
`RUN rm -rf /usr/share/nginx/html/assets` 后再 COPY，或直接改用可用的 node 基础镜像源。

---

## 2. 全链路诊断 + 对照验证

### 2.1 端点健康与性能（周末形态）

| 路径 | 本轮实测 | round57 | 阈值 | 判定 |
|---|---|---|---|---|
| `/health`（根路径） | 200 / **0.51s** | 0.41s | — | ✅ |
| nginx `/` | 200 / **0.22s** | 0.20s | — | ✅ |
| `/market/realtime/portfolio` | 200 / **2.12s**，38 行（**0 null 价 / 0 有标签无值**） | 16.67s（15 nav 失败） | ≤3s | ✅ **显著改善**（round58 §9 盘中 0.84s） |
| `/market/watchlist` | 200 / **0.38s**，1 条（688256 寒武纪 price 1009.01 / -3.54%，`as_of=null`） | — | ≤3s | ✅ 数值 ✅ / 时间戳见 R209 |
| `/admin/factor-health` | 200 / **5.91s**，3 symbols healthy（25-26/39） | 6.75s | ≤2s | ⚠️ **仍超阈**，性能债维持 |
| `/admin/llm/health` | 200 / **10.63s** | 15.55s | — | ⚠️ 好转，仍慢 |
| `/market/sectors/heat` | 200 / **7.04s**，20 项（`change_pct` 全 null / `lead_stocks` 全空） | 3.32s | — | ⚠️ 周末源降级（e2e 有守卫并 PASS 标注 `degraded=True`） |
| `/factors/active` | 200 / **0.28s**，total=38，`warn=20 / no_data=6 / static=12 / valid=0`，avg_ic 0.2431 | 同（6/12/20） | — | ✅ 逐项一致 |
| `/market/search?keyword=红利&kind=index` | 200 / **0.22s**，**19** 条 | 19 | — | ✅ |
| `/market/search?keyword=创新药&kind=sector` | 200 / **5.87s**（冷），**0** 条 | **1** 条 | — | 🐛 **R203 回归** |
| `/market/search?keyword=创新药&kind=all` | 200 / **0.26s**，**2** 条（全为 index 段） | **13** 条 | — | 🐛 **R200 回归** |
| `/news/headlines` \| `/macro` \| `/global` | 15 / 1~3 / 8（macro 标 `fallback`） | 15/6/8 | — | ⚠️ macro 桶降级（源侧） |
| `/api/v1/market/regime` | **404** | — | — | 📝 无此路由（市态走 design/report ctx），**非缺陷**；openapi 共 **72** path |

### 2.2 WS 链路（6/6 握手 101）

`py -3.12` + `websockets` 16.0 + **`proxy=None`**（清空 `*_PROXY` 环境变量，round55 宿主代理坑）：

| 路径 | 直连 :8000 | 经 nginx :80 |
|---|---|---|
| `/api/v1/ws/news` | **101** + 首帧 341B（真实电报快讯） | **101** + 同帧 |
| `/api/v1/ws/portfolio` | **101** + `{"type":"hello"}` 38B | **101** + 同帧 |
| `/api/v1/ws/task-notifications` | **101** 握手（8s 内无快照，正常形态） | **101** 握手 |

> ⚠️ **e2e 的 WS 项 FAIL 与此不同源**：`verify_e2e` 报
> `[FAIL] nginx WS 握手 timed out during opening handshake`，而本轮手工探针（`proxy=None`）
> **6/6 全 101**。归因：e2e 内部 WS 客户端未做代理旁路 → 宿主代理吞噬握手（round57 §环境步骤 6
> 同坑，**第三次**复发）。**记为 e2e 侧缺陷（见 §4.2 G-EP1），不记产品 FAIL**。

### 2.3 主动触发新数据验证（本轮核心）

| 动作 | 结果 |
|---|---|
| `POST /portfolio/design-async`（balanced / 500000 / enhanced） | task **140** `pending→completed` **41s** → design **79** |
| `POST /portfolio/strategy-check-async`（空体→默认组合） | task **141** `completed` **82s** → check **175** |
| `POST /analysis/llm-report/stream`（"市场综合研判"） | HTTP 200 / **90.3s** / 1774 字 / 6 章 / `space-bunny-free` / prompt 1974 + completion 3271 = 5245 tok |
| `POST /analysis/llm-advice/stream`（round59 原问题） | HTTP 200 / **79.8s** / 1130 字 / prompt 2333 + completion 2897 = 5230 tok |

> 注：`design_body.json` 的请求体字段名以 openapi 为准（`LLMReportRequest` / `LLMAdviceRequest`，
> advice 用 **`query`** 不是 `question`——本轮首次即踩 422，记此备查）。

### 2.4 design 79 层预算 + 结构五问（R181 复测）

| 方案 | n | Σ | max(ETF) | CASH | 层分布 | 层预算核对 |
|---|---|---|---|---|---|---|
| 防御型 | 11 | **1.0000** | 0.25（512890） | **25%** | core 4 / sat 4 / def 2 / cash 1 | core 0.45 / sat 0.20 / def 0.10 ✅ |
| 平衡型 | 10 | **1.0000** | 0.20（588000 系外，core 内最高 0.15×2） | **20%** | core 4 / sat 3 / def 2 / cash 1 | core 0.50 / sat 0.20 ≤ 0.22 / def 0.10 ≤ 0.13 ✅ |
| 进攻型 | 11 | **1.0000** | 0.20（588000） | **34.98%** | core 3 / sat 6 / def 1 / cash 1 | core 0.30 / sat 0.30 / def 0.05 ✅ |

- **Σ=1.0000 ×3 ✅；单只 ETF ≤ 30% ✅；CASH 行三方案齐 ✅**（R181 硬风控维持）。
- **结构五问①（同指数/同族并存）**：`normalize_segment(tracked_index)` 分组 → **0 重复** ✅。
  ⚠️ **口径更正**：round57 §4.2 建议的「按 `factor_breakdown.tracked_index` 分组」在 HEAD
  **已不可执行**——`factor_breakdown` 是扁平 `因子名→值` 字典（39/37 键），**无 `tracked_index`
  键**；本轮改按 `symbol` 分组 + 名称/族表人工核对，结论同为 0 重复。
- **五问②（`tracked_index` vs 名称提取值交叉一致）**：**无法执行**（同上，字段不存在）。
  本轮代偿证据：`risk_metrics.correlation_warnings` 的 `near_substitute` 族
  （大盘宽基 / 医药生物 / 半导体）均由 `near_substitute_pairs` 产出并附 `merged_substitutes`
  明细，**未见脏映射**。
- `market_context`：`regime=range_bound` / `session=closed` / `degradation.pool_degraded=true`，
  与 check175 一致 ✅。
- **R03 防御锚扩容（round58-portfolio）实证** ✅：平衡型 defense = **511090 30年国债 + 518880 黄金**
  两只（改前仅黄金 1 只）；防御型同为 2 只。
- **R01 成长集中度**：平衡型成长宽基 2 只（159915 / 510500）→ 不告警，**与 round58 §A4② 的口径
  登记一致**（`_is_growth_wide_basis` 不含中盘）。**但 e2e 侧独立设计（task 147）触发**
  `[FAIL] F7 balanced 成长风格 4 只 > 上限 3 只` → **告警机制在生产路径确实会触发** ✅。

### 2.5 check 175（R186 / R191 / R199 / N1 复测）

- `report_quality=fallback` / `is_fallback=true` / `llm_layer_ok=false`；
  `summary = "LLM 分析超时（30s 未返回，已用规则引擎兜底）（市态：震荡；因子覆盖 33.3%）"`。
- **N1 闭环取证**：同窗口 `token_usage.usage_records` id=64782 `run / space-bunny-free /
  **success=1 / duration=34.2s** / prompt 10589 + completion 3186` → **LLM 在 34.2s 成功返回，
  但外层 30s 分档先砍**。这是 round58 §9.3 N1 的第一个「provider 成功 / 外层超时」直接对照。
- **R199 生效** ✅：`divergence_detail` **28/30 非空**（曾 30/30 null）。样例
  `{"signal_direction":"neutral","factor_direction":"neutral","factor_score":-0.175,
  "threshold":0.5,"explanation":"因子分 -0.17 处于中性区（未达 ±0.5 背离阈值）…"}`
  —— 正是 check143 曾全空的 else 主干 hold 分支。
- **R191 维持关闭** ✅：30 行复合分 **13 个离散值**，top `-1.496`，`-0.21` **零出现**。
- `suggestions[].source` 全为 `"rule"`（LLM 路径不写 source，round58 §D 残留 2 维持）。
- `report_text` 8892 字（规则兜底，信息量低但形态诚实）。

### 2.6 资讯 / 因子 / 静态池

- `news/headlines` 15 条（level 1-5 分布 7/1/1/1/5，stars 3-5）、
  `macro` 1~3 条（**标注 `fallback`**）、`global` 8 条。
- `factors/active`：`total=38`、**`valid=0` / `warn=20` / `no_data=6` / `static=12`**、
  `avg_ic=0.2431`、`min_samples=250`、`observable_days=60` —— 与 round57（6/12/20）**逐项一致** ✅。
- e2e 因子守卫：`[FAIL] etf_specific no_data ≤ 2，实际 4` ——
  `['etf.premium_discount','etf.shares_change','etf.industry_diversification',
  'etf.institutional_holdings_change']`，与 design79 的 `factor_data_quality.valid=3/193`
  （`valid_rate=0.1878`、`no_data=161`）**同源**（周末源不可达）。

### 2.7 前端四态走查（headless Chrome 154，5 路由）

| 路由 | 状态 | 内容实证 |
|---|---|---|
| `/` | ✅ loaded（无空白/无报错） | 全球指数真值：上证 **3842.19 +0.31%** / 深成 **12887.62 -0.11%** / 创业板 **3135.28 -0.23%** / 沪深300 **4357.62 +0.29%** / 科创50 **1530.01 -2.51%**；组合摘要含持仓与盈亏（**-802.75 / +0.45%**）；watchlist / 热点板块 / 资讯 level+stars 均渲染 |
| `/news` | ✅ loaded | 12 头部结构、含中英文条目、level+stars 渲染 |
| `/portfolio-analysis` | ✅ loaded | 持仓行（价格 1.20/1.15/1.72/1.62、涨跌 +0.17%/-2.47%）与盈亏渲染 |
| `/ai` | ✅ loaded | 「AI 工具」页 + 模式卡标题渲染（headless 下任务行未抓到 → limitation，与 round57 同） |
| `/dashboard` | ❌ **404 NotFound** | **DOC-2 维持**：router 仅定义 `/`，无 `/dashboard`（DOM 7452B / text 511 字 / 无标题） |

- **交叉核对（本轮最强的一致性证据）**：
  - 报告「上证 +0.31% / 沪深300 +0.29% / 深成指 -0.11% / 创业板 -0.23% / 科创50 -2.51%」
    ↔ 首页 DOM **逐值全等** ✅
  - 投顾「上证 3842.20」↔ DOM **3842.19**（0.01 舍入）✅
  - 投顾「沪深300 BOLL 下轨 4344.77，距现价 12.85 点」→ 隐含现价 **4357.62**
    ↔ DOM **4357.62** ✅ **算术精确**
  - 投顾与报告均称「科创50 -2.51%」✅
- **空/错态本轮未触发**（数据源部分可用，无全空场景）→ 如实标注「形态未见即不硬验」；
  loading 骨架在各页源码级存在（vitest 亦覆盖）。

### 2.8 Lighthouse（软门禁，2+ 采样/页）

| 页面 | perf | a11y | BP | SEO | LCP | CLS | TBT | 硬门禁 |
|---|---|---|---|---|---|---|---|---|
| `/`（真看板） | **66 / 67 / 80 / 82**（中位 73） | 96 | 96 | 91 | 3.7–4.1s | **0.002–0.041** | 140–620ms | PASS（perf ≥60 / CLS <0.1） |
| `/dashboard` | 98 / 99 | 95 | 100 | 91 | 1.9s | 0.035 | 90–100ms | **无效——404 页**（DOC-2） |

- `/` perf 与 round57（66/67）**一致**；前两个样本偏低是并发跑 pytest 时的 CPU 争抢，
  后两个（80/82）为静默期 → 记录区间而非单点。`unused-javascript` 151KiB/750ms
  （echarts vendor 558KB，既有）+ server-response 0–5ms（nginx 本地）→ 主因仍是 JS 包体，
  **性能债登记，不定性回归**。
- 跑后 `rmSync` EPERM 报错为 chrome-launcher tmp 清理噪音（round57 同），报告完整有效。

### 2.9 回归基线

| 门禁 | 本轮 | 对照 |
|---|---|---|
| pytest `-n auto` | **3583 passed / 11 skipped / 0 failed**（112.95s） | round57 3268；round60 memory 3533 → **+50** |
| vitest | **48 files / 579 passed**（8.09s），0 rejection | round57 568；round60 memory 579 → 一致 |
| `data_health_check` | **13/13 PASS**，130s（预算 600s） | round57 13/13 134s ✅ |
| `verify_e2e.py --host 127.0.0.1 --port 8000` | **267/276，9 FAIL** | round57 分段 138 全过；round59 234/249 |
| `check_routes` | 全 OK | ✅ |
| `check_engine_purity` | OK（engine 12 文件无违规 import / 无 I/O） | ✅ |
| `audit_async_blocking` | PASS（153 文件） | ✅ |
| `check_test_baseline` | **FAIL 323 > 321** | 🐛 **R212** |
| `ruff check app` | **22 errors**（15 I001 + 5 F401 + 2 F811 + 1 B023） | ⚠️ **R212** |
| `patrol.py --full` | 见 §2.10 | — |

**e2e 9 项 FAIL 逐条归因**（`e2e_fails.txt`）：

| # | FAIL 文案 | 归因 | 定性 |
|---|---|---|---|
| 1 | `[策略检查] 任务 120s 内未完成` | N1 预算档 + provider 34.2s 延迟（R206） | **产品**，窗口性 |
| 2 | `新闻 0 条` | news macro 桶 fallback（h=15 正常） | 环境/源 |
| 3 | `ETF 板块联动 池 返回 0 条记录` | R203 占位行 `sector_code` 为空被跳过 | **产品**（R203） |
| 4 | `instruments > 1000（实际 120）` | `instruments` 表仅 120 行且**全为 US** → A 股 ETF 无本地行 | **产品**（R200 根因之一） |
| 5 | `nginx WS 握手 timed out` | e2e 客户端未做代理旁路（round55/57 同坑第三次） | **e2e 侧** |
| 6 | `etf_specific no_data ≤ 2，实际 4` | 周末因子源不可达（与 `valid=3/193` 同源） | 环境/源 |
| 7 | `F7 balanced 成长风格 4 只 > 上限 3 只` | **R01 告警在生产路径触发**（round58-portfolio 的原始问题重现） | ✅ **告警有效** |
| 8 | `LLM 连通性: Read timed out (30s)` | 与 #1 同源（LLM 真实延迟 > 30s） | **产品**（R206） |
| 9 | **`A股搜索 (510300) 返回 HTTP 200，但结果 0 条`** | **R200** —— 与本轮手工探针「创新药 all=2（全 index 段）」独立互证 | **产品 P0** |

> ⚠️ **元发现**：#9 这条 FAIL **每轮 e2e 都在报**（round59 §9.5 记为「15 项 FAIL 全部归入
> STORM/环境性」），**一个死了约 9 周的 P0 缺陷连续 3 轮被归类为环境性**。这正是 AGENTS.md
> 「环境性失败先查 `docs/known-env-issues.md`」的反面——**没有指纹就归环境，等于没有归因**。

### 2.10 `patrol.py --full`（1385.53s，exit 1）

| 档 | 结果 | 归因 |
|---|---|---|
| L1-unit | **PASS**（3583 passed） | — |
| L2-health | **PASS**（DHC 13/13） | — |
| L2-alloc-invariants | **PASS** | — |
| L2-llm-exclusion | **PASS** | — |
| L4-routes / L4-purity / L4-async | **PASS** ×3 | — |
| L5-frontend | **PASS**（vitest 579 + build） | — |
| **L2-e2e** | **FAIL — timeout after 900s** | ⚠️ **预算性**：本轮独立跑的 `verify_e2e` 耗时 ~25min（LLM 单次 80s × 4 次 + 120s 轮询窗 ×2），900s 预算不足。**不定性回归**（独立跑 267/276 已记录） |
| **L3-perf** | **FAIL — timeout after 120s** | ⚠️ **预算性**：周末慢源（factor-health 5.91s / llm-health 10.63s / heat 7.04s，合计已超 120s）→ 维持性能债 |
| **L4-baseline** | **FAIL — 323 > 321** | 🐛 **R212**（治理债，round60 自身引入） |
| L4-ruff | **WARN — 22 errors**（14 `I001` + 5 `F401` + 2 `F811` + 1 `B023`；21 可 `--fix`） | ⚠️ **R212**；注意 patrol 口径 14 I001 vs 手工 `ruff check app` 15 `I001`（**统计口径差 1**，原因未查，登记为待查而非直接引用其一） |
| L2-smoke / L2-startup / L-golden | SKIP（不在该模式/档位范围） | — |

**汇总**：PASS 8 / FAIL 3 / WARN 1 / SKIP 3。**3 个 FAIL 中 2 个为预算性**（L2-e2e、L3-perf），
1 个为治理性（L4-baseline）；**无产品回归**。

> ⚠️ **凭据口径**（round57 §0#18 教训）：patrol 本轮写入 `logs/patrol/tests_ok.json`
> （`files_hash=c1b0fdf5c6d6`）时**全量 exit 1** → 该凭据**仅对应 L1-unit 通过**，
> 不得解读为全量绿。

---

## 3. 分析结果质量审查（四问法 + 结构五问）

对象：① report60（LLM 6 章 1774 字）② advice60（round59 原问题 1130 字）
③ design79 `design_text`（7306 字）④ check175 `report_text`（8892 字，规则兜底）。
**周末形态**：涨跌为周五收盘滞后，`session=closed` / `pool_degraded=true` 已披露。

### 3.1 端到端研判报告（report60）

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 分级 | 修复建议 |
|---|---|---|---|---|---|
| 「A股处于横盘消化期」（`range_bound`） | 事实 | `ctx.market_regime=range_bound`；design79 snapshot 同值 | ✅ | 合理 | — |
| 上证 +0.31 / 沪深300 +0.29 / 深成指 -0.11 / 创业板 -0.23 / 科创50 -2.51 | 事实 | 首页 DOM **逐值全等**（3842.19/4357.62/12887.62/3135.28/1530.01） | ✅ | 合理 | — |
| 「量能数据缺失，本节不做趋势单边判断」 | 事实（诚实降级） | `get_market_breadth = {}`（push2delay 不可达，round58 §9.2 同型）；R04 模板收敛条件式生效 | ✅ | 合理 | — |
| 「板块Top5数据缺席，不进一步外推行业排名」 | 事实（诚实降级） | `ctx.sector_momentum=[]` / `hot_plates=[]` / `sector_heat=[]` | ✅ | 合理 | — |
| 「两融情绪与余额变化均为 -1.00，指向存量资金降杠杆」 | 推断 | prompt 未含 `margin_change`（`ctx.market_sentiment` 只有 `{sentiment_index:50, label:中性}`）→ **-1.00 疑为模型沿用新闻/常识推断** | ⚠️ 支撑不足 | **臆断** | R201-②：prompt 缺该字段时禁止给方向性结论 |
| 「LPR 1y 3.00% / 5y 3.50%」 | 事实 | `ctx.domestic_macro.lpr = {3.0, 3.5, 2026-09-20, stale:false}` ✅ | ✅ | 合理 | — |
| 「PMI 49.4，仍处收缩区间」并写入 §5 风险提示 | 事实 + 推断 | `ctx.pmi_gdp.pmi = {value:49.4, date:"2025-08-31", stale:true, note:"数据滞后至2025-08…"}` | ⚠️ **数据滞后 13 个月，报告未加时效限定** | **部分合理** | R215：prompt 侧要求「stale=true 的值必须显式标注日期」 |
| 「M1 同比 20.54%、M2 同比 18.88%，货币活跃度较高」 | **失效** | `ctx.money_supply = {m1_yoy:20.54, m2_yoy:18.88, date:"2008年01月份", stale:false}`；**真实最新行（2026年08月份）为 M1 4.1% / M2 7.5%**（akshare 224 行实测，row0=2026-08 / row223=2008-01） | ❌ **与真实货币数据相反** | **失效** | **R201（P0）** |
| 「CPI +0.8%、PPI +3.8%，价格环境由低通胀转向成本端回升」 | 事实 + 推断 | `ctx.cpi_ppi = {cpi_yoy:0.8, ppi_yoy:3.8, date:"2026年08月份"}`（**行选取正确**，`_latest_row` 生效） | ✅ 数值真实 | 合理 | — |
| 「美债10年期 5.24%、联邦基金 3.88%、VIX 16.39」 | 事实 | `ctx.global_liquidity = {us_10y:5.24, vix:16.39, fed_rate:3.88}`；全文 `5.xx` **唯一值 5.24** → **R03b 去重生效**（`domestic_macro.bond_yields.us_10y=5.28` 未进 prompt） | ✅ | 合理 | — |
| 「美元与油价没有行情快照」 | 事实（诚实降级） | `ctx.commodities = []` | ✅ | 合理 | — |
| 「科创50与沪深300单日相对差达到 2.80 个百分点」 | 事实（算术） | -2.51 - (+0.29) = -2.80 ✅ | ✅ | 合理 | — |
| 「维持中性仓位…偏离目标权重 ±5 个百分点即再平衡」 | 规则模板 | 与 round58 R08 口径一致 | — | 合理 | — |
| **免责话术计数** | 事实 | 「未提供」**0**、「暂无法验证」**0**、「无法确认」**0** → **R04 模板收敛生产实证通过** | ✅ | 合理 | — |

**汇总**：可采信 **11** 条 / 需修正 **2** 条（PMI 时效、两融 -1.00 缺支撑）/ **臆断 1** 条（两融方向）/ **失效 1** 条（M1/M2 2008 数据）。

### 3.2 AI 投资顾问：round59 原问题（advice60）

| 判断原文 | 事实/推断 | 数据支撑 | 一致? | 分级 |
|---|---|---|---|---|
| 输出「## 关键价位表」含 支撑 5 档 + 阻力 5 档 | 事实 | 3827.66/3821.74/3741.11/4344.77/4323.57 与 3854.40/3864.23/3890.23/4400.00/4453.20 | ✅ | 合理 |
| 方向标注不变式（round59 §9.3①）：标 support 必在现价下方 / resist 必在上方 | 事实 | 上证现价 3842.19–3842.20：支撑 5 档全 < 3842.2 ✅；阻力 3 档全 > ✅。沪深300 4357.62：支撑 4344.77/4323.57 < ✅；阻力 4400/4453.20 > ✅。**两族无混列** | ✅ | 合理 |
| 「上证61.8%回撤 3827.66 = 上涨段[3741.11, 3967.68]回撤位，距现价仅 14.53 点」 | 事实 + 算术 | 3842.20 - 3827.66 = **14.54**（差 0.01，舍入）✅ | ✅ | 合理 |
| 「沪深300 BOLL 下轨 4344.77，距现价 12.85 点」 | 事实 + 算术 | 4344.77 + 12.85 = **4357.62** ↔ DOM 实测 **4357.62** ✅ **精确** | ✅ | 合理 |
| 「沪深300 RSI 32.90、KDJ-J 0.06，超卖明确，但超卖不等于底部确认」 | 事实 + 推断 | prompt 含 RSI/KDJ（round59 R01 口径） | ✅ | 合理 |
| 「近5/20日均量比分别仅 0.90 和 0.93，说明增量资金尚未明显入场」 | 事实 + 推断 | 量能档有值 → **round59 §7 待复测项 ③ 本轮闭环** ✅ | ✅ | 合理 |
| 「MACD 多头」等方向词 | 推断 | 未在 prompt 快照中逐项复核（本轮未截 prompt） | ⚠️ 未取证 | **未判定**（取证不足，不计臆断） |
| 「无法确认」式空转 | 事实 | **0 次** ✅ | ✅ | 合理 |
| 回落「行业轮动分析框架」 | 事实 | **0 次** ✅ → R09 生效 | ✅ | 合理 |
| 答案 1130 字 ≤ 1200 上限 | 事实 | 1130 ≤ 1200 → **R12 达标**（round59 曾 1605 超 34%） | ✅ | 合理 |
| `prompt_tokens` 2333 | 事实 | 2333（事故时 1430）→ 接线确实带上了技术面数据 | ✅ | 合理 |

**汇总**：可采信 **10** 条 / 需修正 **0** / 臆断 **0**（1 条未取证）/ 失效 **0**。
**round59 验收口径本轮全部达成**，含 §7 三项待交易时段复测中的第 ③ 项（量能档）。

### 3.3 组合设计方案（design79 `design_text` 7306 字）

| 判断原文 | 事实/推断 | 数据支撑 | 一致? | 分级 |
|---|---|---|---|---|
| 三方案 Σ=1.0 / CASH 齐 / 单只 ≤30% / 零同族重复 | 事实 | §2.4 表 | ✅ | 合理 |
| 「综合信号」与「因子综合分」标签唯一 | 事实 | `综合信号 ×29` + `因子综合分 ×3` → **R198 修复生效** ✅ | ✅ | 合理 |
| 「30年国债ETF鹏扬与权益低相关，分散尾部风险」+ 脚注「因子综合分 -4.32 为负，作防御层配置需谨慎」 | 事实 + 诚实警示 | `structure_warnings=[{type:"negative_signal_in_defense", symbol:"511090", factor_score:-4.322}]` | ✅（警示与配置自洽） | 合理 |
| 「同类候选池排名 2/4」「3/4」「1/12」 | 事实 | `selection_rationale` 原文 | ✅ | 合理 |
| **「动量因子 +0.007」×10 / 「+0.004」×5** | **失效（输入层）** | 19 标的的 `factor_breakdown` 塌成 5 块（§4.1 R202）：`_pool.py:113` 缺键补 0.0 → 34 个标的每个缺键拿到**同一浮点**（9 键 1e-13 精度证明 N=37/3 有 K 线） | ❌ 文本按标的呈现为实测，实为同一列均值 | **失效** | **R202（P1）** |
| 「主驱动因子：情绪」×7 | 推断（输入层失真） | `_dominant_factor` 取 \|贡献\| 最大者 = 被克隆的 `sentiment` 值 | ⚠️ 输入存疑 | 部分合理 |
| `risk_metrics.correlation_warnings[].combined_weight` 0.1536 / 0.0972 / 0.0742 | **失效（陈旧快照）** | 与持久化 `weight`（0.10+0.10 / 0.10 / 0.05）矛盾；三值全部由 coarse 5% 档位精确解释（§4.1 R208） | ❌ 同一 JSON 内两种精度 | **失效** | **R208（P3）** |
| `near_substitute` 半导体族 `correlation: -0.117` | 事实（数值） | 与「同主题近替代品」标签**方向矛盾**（负相关的两只芯片 ETF）；但 note 已声明「关联度约束不依赖 K 线相关系数」，族判定不依赖该值 | ⚠️ 内部观感矛盾，非逻辑错误 | 部分合理 | 建议把 `correlation` 字段在 note 已免责时省略（R208 邻近项） |
| 平衡型 defense 2 只（黄金 + 30年国债） | 事实 | §2.4 → **R03 生效** ✅ | ✅ | 合理 |

**汇总**：可采信 **8** 条 / 需修正 **3** 条（主驱动因子、combined_weight、半导体 correlation 展示）/
**失效 2** 条（动量 +0.007 群、`combined_weight`）/ 臆断 0。

**数据准确性抽查**：
- 权重：Σ = 1 − CASH ✅（三方案）
- 占位值检测：经典占位（RSI 50.0 / 动量 +0.300 / ln_mcap 0.0）**未出现**；
  但 `+0.007 / +0.004` 群是**更隐蔽的占位**（列均值伪影），已单列 R202
- `as_of` / `session`：`data_as_of = null`（design79 snapshot）、`session=closed` ✅ 已披露；
  但 `realtime/portfolio` 38 行**全无 as_of**（R209）
- `data_source` / `estimate_source`：realtime 38/38 `estimate_source=null`、`is_estimated=false`
  → **R196「有标签必有值」0 例外** ✅
- regime 双端一致：design79 `range_bound` ↔ check175 `震荡` ↔ report60 `range_bound` ✅

### 3.4 策略检查报告（check175，规则兜底）

| 判断原文 | 事实/推断 | 数据支撑 | 一致? | 分级 |
|---|---|---|---|---|
| `LLM 分析超时（30s 未返回，已用规则引擎兜底）` + `因子覆盖 33.3%` | 事实 | DB summary 原文；`is_fallback=true` / `llm_layer_ok=false` → **R186 三旗语一致** ✅；同窗口 provider **34.2s 成功** → 归因精确（R206） | ✅ | 合理 |
| 30 行建议含因子分 + 模板建议 | 事实+模板 | 13 个离散值 | ✅（形态诚实、信息量低） | 合理 ×N / 模板复读 |
| `divergence_detail` 28/30 非空 + 阈值解释 | 事实 | §2.5 样例 → **R199 生效** ✅ | ✅ | 合理 |
| `-0.21` 零出现 | 事实 | 13 离散值 → **R191 维持关闭** ✅ | ✅ | 合理 |
| 「市态：震荡」 | 事实 | `market_regime=range_bound` ↔ design79 一致 ✅ | ✅ | 合理 |

**汇总**：可采信 5 类 / 需修正 0 / 臆断 0 / 失效 0。
**数据源健康面板里 4 个源处于 cooldown**（`push2delay.eastmoney.com` failures=2、
`akshare` / `levistock` / `dongfang` cooldown、`mootdx` cooldown）——与 §2.6 的因子/宽度降级同源。

---

## 4. 问题分析与修复方案（只写方案不写代码）

### 4.1 R 系列新发现

| 编号 | 发现 | 根因机制链（file:line） | 严重度 |
|---|---|---|---|
| **R200** | **`/market/search?kind=all` A 股 ETF 段恒空**：手测「创新药」`all` 从 round57 的 13 条掉到 **2 条**（且全是 index 段）；`market=A` 路径不经过滤故仍能搜到 → 掩盖了问题。e2e 每轮报 `A股搜索(510300) 0 条` | ① `china_market.py:1903-1909`（同族错 `:1866-1871`）`fetch_etf_list` 回退路径把**市场码写进 `asset_type`**（`"asset_type":"A"`）且**不产出 `market`/`type`** 键 → ② `market_service.py:578-626` `search_etf` 直传该形状（SQL 路径另有 `type:"etf"`，但 `instruments` 表只有 120 行全 US → SQL 路径对 A 股 ETF **恒空**，100% 走回退）→ ③ `market.py:168` `a_etf = [r for r in a_etf if r.get("asset_type")=="etf"]` **全丢** → ④ 连带 `market_service.py:732/754` 排序契约同错（`type_rank = 0 if asset_type=="etf"`，把 A 股 ETF 排到个股层）。**时序**：producer 错于 `c519c7a`(2026-07-15)，consumer 加于 `72ad22d`(2026-07-31) 且设计文档 `docs/archived/v5_z15_z29_implementation_design.md:257` 明确按「`asset_type` 就是 etf/stock」推理 → **两者从未对齐，死约 9 周** | **P0** |
| **R201** | **宏观货币数据取到 2008 年且不标 stale**：报告断言「M1 20.54% / M2 18.88%，货币活跃度较高」，真值 **M1 4.1% / M2 7.5%**（2026年08月份）。`stale=false`，note 空 | ① akshare `macro_china_money_supply` 服务端 `sortTypes:-1` **无客户端重排** → **最新在前**（实测 row0=2026年08 / row223=2008年01）→ ② `macro_fetcher.py:120` `row = df.iloc[-1]` **取到最老一行** → ③ `_stale_note:33-48` 只认 `YYYY-MM-DD`/`YYYY-MM`，对 `YYYY年MM月份` 走 `else` 分支 `strptime` 抛 `ValueError` 被 `except` 吞掉 → **`return False, ""`（fail-open）**。**同源第二处（预测）**：`macro_fetcher.py:568-570` `fetch_macro_snapshot` 的 `m2_vals[-1]/[-3]` → M2 slope 取 2008 差分，`m2_direction=-1`「货币收紧」，且**该腿不输出任何日期** → 无任何 staleness 兜底。**同文件已有正确实现却未统一**：`_latest_row:215-221` 的私有 `_parse` 会 `replace("年","-")`，`fetch_cpi_ppi:167-168` 正是用它取到了正确的 2026年08月份 | **P0** |
| **R202** | **R197 因子克隆复发并升级为常态**：19 个标的塌成 **5** 个 `factor_breakdown` 块（13+5+1+1+1 分布）。`综合信号` 之外的 `动量因子 +0.007`（10 只）/ `+0.004`（5 只）被 LLM 报告按标的呈现为实测 | ① 上游 `[推断]` K 线预热饥饿：只有 3/37 标的在因子计算时有 K 线（510300/511090/518880）→ ② `factor_registry.py:443-460` 等价格因子返 `None`（不是 0.0）→ ③ `core/factor_aggregate.py:149-151` `if not values: continue` → 顶层 `momentum`/`technical`/`sentiment` **键不创建** → ④ ★`hub/_pool.py:113` `values = [matrix[s].get(key, 0.0) for s in symbols]` **缺键当 0.0**，`:124` z 分数后 34 个标的每个缺键拿到**同一浮点** → ⑤ `allocation_engine.py:923` `k: round(v, 3)`（**无条件**，非 coarse 专属）使 10 个符号的字典**逐字节相同**；`MANDATORY_CODES`（`budgets.py:26-28` = 510300/159338/518880/511090）走 `:332` **免 round** → 4 个「唯一」块其实是**同一浮点的未舍入版**（`round(159338_block,3) == 588200_block` 全 37 键为 True）→ ⑥ `strategy_design.py:484-494` 用该字典拼 rationale、`analysis/llm/reports.py:1152` `f"{v:.3f}"` 进 LLM 表格。**算术证明**：以 159338 的未舍入值为 `v0=-mean/std`，9 个独立键解出的 `(N-3)` 全部 = **34.0000000000000x**（1e-13）→ N=37 恰 3 个有数据 | **P1** |
| **R203** | **板块搜索恒空 + 占位数据外泄**：`kind=sector` 对 创新药/半导体/黄金/科创 **全部 0 条**（round57 为 1 条）；`fetch_concept_sectors` 返回 40 条**硬编码占位**（`sector_code=""`、price/change_pct/volume/main_inflow 全 0、`lead_stock_*` 空） | ① 源不可达（启动日志两条 `fetch_em_*_sectors pn=1 failed: Remote end closed connection`）→ ② `sector_fetcher.py:258-269` 补充分支失败 → ③ `:271-292` 遍历 `POPULAR_CONCEPTS`（**40 条硬编码**）对未命中项**追加占位行**并 `return rows[:limit]`（`:294`）——实测 **40/40 全是占位**，`etf` 概念列表 100% 伪造 → ④ `market.py:244` `if not name or not code: continue` → 占位被跳过 → ⑤ `market.py:234-240` `_collect()` 把 `fetch_industry_sectors(200)`+`fetch_concept_sectors(600)` 塞进**同一个 `run_sync(timeout=10)`**，而实测 `fetch_concept_sectors(600)` **冷 25.9s / 热 0.00s** → **必然 10.04s 超时**（手工探针两次实测 10.04s / 10.02s）→ ⑥ 回落 `sectors` 表兜底，而该表**自 O30 起无写入者**（`_search_sectors` docstring `:208-211` 已记载）→ 恒 0。**附带**：占位行若被 `compute_sector_momentum` 消费即污染 round58 R01 的板块段（当前 `get_sector_momentum=0` 行，未证实污染，记为待验） | **P1** |
| **R204** | **R05 403 熔断在 SSE 路径只写不读**：advice/report 的 `run_stream` 路径永不跳过被拉黑的 provider；`client.py:419-420` 的注释把 `:335` 的 `_circuit_allow` 说成 `_r05_403_allow` | `client.py:430/467/477` 调 `_r05_403_record`（写）；`_r05_403_allow` 只出现在 `:55`(def) / `:597` / `:762-763`，**全在 `llm_complete_with_system`（def `:563`）内**；`llm_complete_stream`（def `:298`）内 `:335` 是 `_circuit_allow`（F8 TTL 熔断，非 R05）。**净效果**：R05 状态被填充后在这条路径上被忽略 | **P2** |
| **R205** | **后台新闻摘要 LLM 扇出**：每 120s 一次 `enrich_news_summaries()`（`main.py:405-425` 循环 → `:419` `_spawn`），cap=6 分桶配额（head 3 / macro 2 / global 1，`hub/_news.py:67-70`）→ **6 次串行 LLM**。实测 **51 次/小时**、LLM 累计 **448.8s/小时 = 墙钟 12%**（最近 5min 窗口 **82%**）、**9/51 失败（17.6%）**；单次 1.9–16.9s。与交互路径（report 79s / advice 83s / check 82s）争同一配额。`skip_llm` 闸（`_news.py:77-83` `is_middle_layer_active`）未生效 | `main.py:405-425`（120s 循环 + `_spawn`）→ `hub/_news.py:84-124`（分桶配额 + `stars>=4 or level>=4`）→ `:105` `await generate_news_summary(...)` 逐条串行。启动期首次调用轮盘 Zen 全目录 7 模型 ≈ 6s（round58 §D 残留 1「熔断不跨进程」维持）。**失败 9 次**：`thinkingmachines/inkling:free`(openrouter 403) + 7 次 Zen 403（18:51:31-55 启动段） | **P2** |
| **R206** | **N1 复发 + 首次拿到「provider 成功 / 外层超时」对照**：check175 fallback，summary「LLM 分析超时（30s 未返回…）」，因子覆盖 33.3% | `strategy_check.py:735-739` `_llm_timeout_for` → `all_empty=15 / partial=30 / 完整=180`；`:221` `all_empty = filled_factor_count==0`；`:260` 取档 → `:670` `report_quality = "fallback" if _llm_failed else "full"`。**本轮实测**：同窗口 `usage_records` id=64782 `run / success=1 / duration=34.2s / prompt 10589 + completion 3186` → **LLM 34.2s 成功，外层 30s 先砍**。round58 §9.3 的量化（真实 prompt 4,642 tok、端到端 27.2/29.5/31.5s 骑在 30s 边界）本轮以 10,589 tok 的更大负载再次坐实 | **P2** |
| **R207** | **N4 活体复现**：`summary="组合为空"` 却 `report_quality=full` / `is_fallback=false` / `llm_layer_ok=true`。**今日**产生 2 条（check 173 @03:50 UTC、174 @09:44 UTC），非历史遗留 | `strategy_check.py:84-92` 空组合分支 `return {"summary":"组合为空…", "suggestions":[], "empty_diagnosis":diag}` —— **不返 `report_quality`** → `strategy_check_worker.py:131` `report_quality=result.get("report_quality","full") or "full"` **兜底成 full** → 列默认值也偏 full（`database.py:102`、`models/strategy_check.py:41`，读侧 `:61` 再兜一次）。`:665-667` 注释声称枚举是 full/partial/fallback/empty，但 `:670` **只产出 full/fallback**；design 侧 `task_manager.py:423-432` 已有 `empty` 档 → **枚举存在，strategy-check 侧从不产出** | **P2** |
| **R208** | **`combined_weight` 结构性过期**：同一 JSON 内 `correlation_warnings[].combined_weight=0.0742` 与 `etfs[].weight=0.05` 并存 | `allocation_engine.py:1050-1056` `near_substitute_pairs` 产 `combined_weight` → `:1822` 快照 → `:1827` `entry = dict(np)` 拷贝 → `:1845` `_merge_substitute_family` **改权重但不重算**（`:1115-1120` 把被合并者权重并入存活者）→ 再叠加编排层 3 次突变：`strategy_design.py:654`（无 `daily_change_pct` 置 0）、`:685`→`:1293` **coarse 5% 档位取整**、`:707`→`:785-828` 层预算缩放。**实测三值全部由 5% 档位精确解释**：0.1536→`round(1.536)=2`→0.10×2；0.0972→`round(1.944)=2`→0.10；0.0742→`round(1.484)=1`→0.05。**金夹具不可见的原因**：唯一被覆盖的 pair (510300,159338) 是 `CORE_ANCHORS`，`strategy_design.py:1097-1099` 豁免合并 → 权重从快照到输出不变 | **P3** |
| **R209** | **`realtime/portfolio` 38 行全无 `as_of` / `data_source`**：R196 只保证「有标签必有值」，反向「**有值无时间戳**」无人管；watchlist 同样 `as_of=null`。新鲜度无法从响应自证 | `market_service.py:578-626` / `:1308-1340` 的 `_fetch_one` 只在 `estimate_source` 分支写标签，不写 `as_of`；`routers/market.py:874-901` 归一化保留该形状（round57 R196 的修复范围如此）。实测 38/38 `value_without_as_of` | **P3** |
| **R210** | **`sectors/heat` 20 项 `change_pct` 全 null + `lead_stocks` 全空** | 周末源降级；e2e 有守卫并 PASS 标注 `degraded=True`（round19 段） | **P3**（观察） |
| **R211** | **契约/注释漂移三处**：① `_technical.py:13` docstring 声称 `idx:<symbol>` 命名空间键，实为**专用 dict + 裸 symbol**（`:224` 读 / `:310` 写，全仓无 `idx:` 串）——**docstring 与自己的设计理由不符**，且测试 `test_llm_context_market.py:450` 锁的是裸 symbol；② `intent.py` **8 个载荷词未进契约**（`市盈率`/`市净率`/`pe`/`pb`/`roe`/`持有`/`代码`/`配置`/`买`/`卖`），`valuation`/`event`/`rotation`/`allocation` **四族无 §3 表**，契约 §2 示例 `怎么配` **字面不可路由**（关键词是 `配置`）；③ **方向反转**：round60 memory 担心的「契约 §3 列着代码早已不含的词」**实测 0 例**——§3.1/§3.2/§3.3 全部词条与代码一致，W1 删除的 8 个死词正确地不在代码里 | **P3** |
| **R212** | **门禁债**：`check_test_baseline` **323 > 321**（round60 新增 `test_advice_goldset_l1.py` / `test_advice_goldset_l2.py` 等 2 个文件未提 BASELINE —— 与 round57 F1 同型）；`ruff check app` **22 errors**（15 `I001` import 排序 + 5 `F401` 未用 import + 2 `F811` `admin.py:364` 函数内重导入 `BaseModel`/`Field` + 1 `B023` `main.py:508` 闭包未绑定循环变量 `_sem`）。round59 §9.3 登记的「3 处存量 F401」已长成 22 | **流程** |
| **R213** | **overlay 使容器 assets 累积到 94（宿主 45）**：`COPY dist` 是合并非替换 | 见 §1.1 | **环境/方法** |
| **R214** | **文档污染**：round57 §9、round58-market §9、round58-portfolio §9 三处「交易时段复测（2026-09-29）」是**同一份全文复制**（含 N1/N2/N3/N4/§D 全部），其中 N2（`startup.py` NameError）与 N4（strategy_check 空组合）**与所在文档主题无关**（N2 属 round57 容器、N4 属 round58-portfolio，却出现在 round58-market 里） | 三份文档 §9 内容逐字相同（已抽样比对标题序列） | **文档** |
| **R215** | **stale 值未在正文加时效限定**：PMI `date=2025-08-31 / stale=true`（滞后 13 个月）被报告直接写成「PMI 持续低于 49.4」并进入 §5 风险提示，无日期限定 | `macro_fetcher.py:33-48` 正确产出 `stale=true` + note，但 `_build_market_overview` 渲染与 prompt 硬约束未要求「stale 值必须带日期」 | **P3** |

### 4.2 测试防护体系缺口分析

#### 1) 防护体系现状（本轮实测，不靠文档假设）

| 层 | 能抓到什么 | 抓不到什么（本轮实证） |
|---|---|---|
| pytest 3583 绿 | 结构、纯函数、契约形状 | **跨标的数据多样性**（R202）、**行序**（R201）、**跨端点字段一致性**（R200） |
| vitest 579 绿 | 组件渲染、意图词表 gold set（round60 强项） | 后端数据缺陷全部不可见 |
| `verify_e2e` 267/276 | 端点可达 + 少数内容断言 | **R200 它每轮都报却被归「环境性」**；R201/R202/R203 完全无断言 |
| `data_health_check` 13/13 | 数据源可用性 / 因子填充率 | 数据**正确性**（2008 vs 2026 无告警） |
| `check_routes` / `check_engine_purity` / `audit_async_blocking` | 路由契约 / engine 纯度 / async 阻塞 | 上述全部 |
| `check_test_baseline` | 文件数上限 | **本轮自身 FAIL（323>321）** |
| `ruff`（软门禁 WARN） | 未用 import 等 | **不阻断**，22 errors 长期累积 |
| **门禁自身可信度** | — | ⚠️ **e2e 的 9 个 FAIL 连续 3 轮未被归因**（round59 记「全部环境性」）；`check_test_baseline` 与 `ruff` 本轮**自己就是红的**而 patrol 尚未报（见 §2.10） |

#### 2) 逐发现映射：为什么防护未识别

| 发现 | 最应拦截的防护层 | 为何未识别（file:line + 具体断言/阈值） | 应补的守卫（缺口类型） |
|---|---|---|---|
| **R200** | e2e + 单测 | e2e **有**断言但被归类环境性（`verify_e2e.py:2451-2461` 只断言 `len(data) > 0`，而 `kind=all` 尾部追加 index 段 → 列表非空即 PASS）；单测 `test_search.py:389-416` 用 `_fake_search_etf` **伪造 producer 形状** `{"asset_type":"etf","type":"etf"}`——而 `search_etf` **任何代码路径都不返回该形状** | 单测：`search_etf` 回退路径返回值必须含 `market` 与 `type`；e2e：`kind=all` 时 **ETF 段单独计数**断言 >0（不能被 index 段掩盖）。**内容语义断言缺失 + 前端 mock 数据掩盖真实契约**（双重） |
| **R201** | 单测（行序）+ e2e（值合理性） | `fetch_money_supply` **零测试**（grep 仅 2 处 monkeypatch）；喂 `macro_china_money_supply` 的两个夹具 `test_macro_regime.py:84-88` / `test_macro_factors.py:54-64` **按最老在前构造**（与真实源相反）→ 主动确认了错的不变式；`_stale_note` 的 `YYYY年MM月份` 分支无测试且 **fail-open**；e2e 无宏观数值断言 | 单测：真实行序夹具（最新在前）+ 负向断言「取到的 date 必须是 max」；`_stale_note` 参数化覆盖 `YYYY年MM月份` / 非法串 **必须返 stale=True**（fail-closed）。**门禁阈值 = 历史问题值 + mock 理想输入** |
| **R202** | 单测（跨标的多样性）+ e2e（内容方差） | 25 处 `factor_breakdown` 断言**全是存在性 / 手写字面量 / 键名检查**（`test_design_integration.py:261-282` `assert fb`）；`test_factor_matrix_respects_raw.py` 的每个夹具**给所有标的喂所有键** → `_pool.py:113` 的缺键分支**从未被走过**；金夹具 `_make_factor_matrix` 用 `rng.uniform` 逐标的独立取值 → 结构上不可能复现缺键。round57 §4.2 提的 `e2e 内容断言：design factor_breakdown 三元组方差 > 0` **落地成了 `verify_e2e.py:503-517`，但读的是 `factor_score`（coarse 下已被换成字符串 → `all_fs` 空 → 守卫失效）+ `technical` 单键（被 3 个真实离群值撑大方差 → 恒 PASS）** | 单测（`hub/_pool.py` 层）：构造「N 个标的、K 个缺某键」→ 断言缺键标的**不得**获得与其它缺键标的**相同**的该键值（负向：改回 `get(key, 0.0)` 必 FAIL）；e2e：按 round57 原意改为**三元组 distinct 数 > N/2** 的内容断言，且**不得读 coarse 已被字符串化的字段**。**内容语义断言缺失（且提议被落地成了不能触发的形态）** |
| **R203** | 单测（降级不伪造）+ e2e | `sector_fetcher.py:285-292` 的占位追加**无任何负向断言**（无「源全空时不得返回 `sector_code` 为空的行」）；`_search_sectors` 的 `run_sync(timeout=10)` 与实测 25.9s 的矛盾**无预算一致性测试**（对比：`test_llm_stream_retry.py:130+` 为 LLM 预算建立了这种锁）；e2e `[FAIL] ETF 板块联动 池 0 条` **有断言但未归因** | 单测：mock 概念源抛异常 → 断言返回列表中**不得含 `sector_code` 为空的行**（负向：旧实现必含 40 条）；`_search_sectors` 预算一致性测试（`timeout` ≥ 实测冷耗时，或改为分桶各自 `run_sync` + 各自预算）。**降级无门禁 + 门禁存在但未归因** |
| **R204** | 单测（熔断对称性） | `test_llm_circuit_state.py` 只覆盖 `llm_complete_with_system`；`llm_complete_stream` 的 R05 侧**只测了 `_r05_403_record` 的写**（round59 §9.4 收窄为「补 record」），**没测读**。测试「绿」是因为只断言了记录发生 | 单测：`llm_complete_stream` 连续 2 次 403 → **第 3 次该 provider 零探测**（与 `llm_complete_with_system` 的 `:597` 断言对称）。**分支覆盖不全（与 round57 R199 同型）** |
| **R205** | 单测（后台扇出上限） | 无「每小时 LLM 调用数」上限断言；`skip_llm` 闸有测试（`test_llm_quota_protection.py:183-243`）但**不覆盖「闸失效时的兜底上限」**；启动期 Zen 目录轮盘无断言（round58 §D 残留 1 已登记） | 单测/巡检：`enrich_news_summaries` 单次 LLM 调用数 ≤ cap 的硬断言（现有实现满足，缺锁）；新增**每轮 LLM 调用预算**指标（后台占比 >X% 告警）。**门禁阈值缺位** |
| **R206** | 单测（预算余量）+ e2e | `test_llm_stream_retry.py:152-199` 锁的是「预算 ≥ `PROVIDER_COUNT × request_timeout`」（内部自洽），**不锁「预算 vs 实测 provider 延迟」**；`strategy_check.py:732` docstring 引用的 `tests/test_round14_llm_budget_consistency.py` **已不存在**（折进 `test_llm_stream_retry.py:130+`）→ 文档指针悬空；`reports.py:873` 注释写「完整 75s」实际 180s。e2e 的 `#1`/`#8` 两个 FAIL（120s 未完成 / read timeout 30s）**每轮都在报** | 单测：`_llm_timeout_for(partial)` ≥ 现役 provider 实测 p95 × 1.5（用录制的延迟样本做 fixture，负向：把档位改回 30s 必 FAIL）；**修 docstring 悬空指针**（`strategy_check.py:732` / `reports.py:873`）。**门禁阈值 = 历史问题值** |
| **R207** | e2e / 单测（质量分档） | 无「空组合记录不得记为 full」的断言；`strategy_check_worker.py:131` 的 `or "full"` 兜底无负向测试；`:665-667` 注释声称 4 档枚举 → **注释即谎言，无守卫** | 单测：空组合 → `report_quality == "empty"`（负向：现实现必为 `full`）；e2e：`/portfolio/strategy-checks` 的质量分布里 `full` 占比异常（今日 2/3 为空组合）应告警。**内容语义断言缺失** |
| **R208** | 单测（同一 JSON 内自洽） | 金夹具唯一覆盖的 pair 是 `CORE_ANCHORS` 豁免对 → 权重冻结 → `combined_weight` 恰好等于最终权重之和；`test_design_integration.py` 的手写夹具不走 coarse bucketing | 单测：构造「非豁免 pair + 触发合并」→ 断言 `combined_weight` **等于合并后两标的最终权重之和**（负向：现快照必不等）。**门禁阈值 = 历史问题值（恰好压线过关）** |
| **R209** | 单测 / e2e（新鲜度字段） | round57 R196 的守卫只断言「`estimate_source` 非空必有值」，**反向（有值必有 `as_of`）无人断言**；e2e 无 `as_of` 检查 | 单测 + e2e：`price` 非空 → `as_of` 非空。**内容语义断言缺失（单向）** |
| **R211** | 契约一致性段 | `check_routes` 的契约一致性段**不覆盖关键词**（round60 memory 已指出）；`test_advice_goldset_l1.py` 的 3 条 meta-test **直接读 `intent.py`**，锁的是「每个词有唯一触发用例」而非「契约与代码一致」 | **并入** check_routes 契约一致性段（不得新增门禁段，16 段上限）：断言 `intent.py` 的每个词表在契约中有对应行 + 契约 §3 无代码外词。**门禁存在但覆盖不全** |
| **R212** | check_test_baseline / ruff | `check_test_baseline` **本轮自己就红**（323>321）；ruff 是 patrol **软门禁 WARN 不阻断** → 22 errors 静默累积（round59 登记 3 个 F401 时是「一行级修」，本轮长成 22） | 走既有流程：或并入既有测试文件（round57 F1 决策），或提 BASELINE + review；ruff 的 `I001` 走 `--fix` 一次清掉。**门禁自身红但未阻断** |

#### 3) 系统性根因归并

| # | 根因 | 本轮/已归纳 | 归属发现 |
|---|---|---|---|
| **G1** | **「缺数据 → 补一个看似合理的值」的三条独立通道**（`_pool.py:113` 补 0.0 / `sector_fetcher.py:285` 补占位行 / `fetch_money_supply` 取错行而不标 stale） | **本轮新出现，且是本轮最集中的一类** | R201 R202 R203 |
| **G2** | **「降级被声明了，但声明打错了靶」**：`data_precision.note` 声明 coarse「只影响呈现」，而真正的问题在 `factor_breakdown`（未被 coarse 覆盖）；`_stale_note` 存在但对实际数据格式 fail-open | **本轮新出现** | R202 R201 R215 |
| **G3** | **「mock / 夹具比没有 mock 更坏」**：`test_search.py:389` 伪造 producer 形状、`test_macro_regime.py:84` 行序与真实源相反、`verify_e2e.py:503` 读 coarse 已字符串化的字段 | **round60 教训 #4 的扩大版**（本轮 3 处独立复现） | R200 R201 R202 |
| **G4** | **「分支/路径覆盖不全」**：R05 只测写不测读（SSE 路径）、预算档只测内部自洽不测外部余量、空组合路径无质量分档守卫 | **本轮新出现** | R204 R206 R207 |
| **G5** | **「门禁在报，但没人归因」**：e2e 的 9 个 FAIL 连续 3 轮被笼统归「环境性/STORM」；`check_test_baseline` 本轮自红 | **本轮新出现** | R200（死 9 周）、R212 |
| **G6** | **「文档/注释与代码各说各话」**：`_technical.py:13` 的 `idx:` 键、`reports.py:873` 的 75s、`strategy_check.py:732` 的已删测试文件、`strategy_check.py:665` 的 4 档枚举、契约 §2 的 `怎么配`、三份文档同文复制 | **round2/3 已归纳，本轮未收敛**（本轮又添 6 处） | R211 R212 R214 |

**总体评价**：防护体系缺的不是用例数量，而是**「跨条目/跨端点的关系断言」这一层**——
「同一列里不同标的的值应当不同」「同一 JSON 内两个字段应当自洽」「断言必须落在降级后仍然
有意义的字段上」。本轮 4 个 P0/P1（3 个）全部逃过 3583 个绿的用例，因为它们**不是单点逻辑错，
是「两个本该相等/不相等的东西之间没有关系断言」**。次要的一层是**归因纪律**：门禁报红时
「先 `rg` 定位、再判环境」这道工序本轮被跳过 3 次。

#### 4) 补齐设计（只写方案，不写代码）

> **门禁替换制**：以下全部**并入既有门禁**（②check_routes 契约一致性段 / ⑪pytest 分派 /
> ⑤check_api_usage 或 data_health_check 数值段 / ⑥audit_async_blocking 同级的新断言并入既有文件），
> **不新增任何门禁段**（AGENTS.md 16 段上限）。

- **方案 A（P0，R200）**：① `fetch_etf_list`（`china_market.py:1903-1909` / `:1866-1871`）改产
  `{"market":"A","type":"etf","asset_type":"A"}`（对齐 `search_hk_us` 的 `market_service.py:868-869`
  既有约定）；② `market.py:168` 过滤键改 `r.get("type") == "etf"`；③ `market_service.py:732/754`
  排序契约同步改 `type`。
  **守卫**：`tests/test_search.py` 断言「`search_etf` 回退路径返回值含 `market` 与 `type`」
  （负向：现实现必缺）；`verify_e2e.py` 的 A 股搜索项改为 **`kind=all` 且 ETF 段单独计数 > 0**
  （负向：现实现 ETF 段恒 0 → 必 FAIL）。
  **影响**：`china_market.py` 2 处 + `market.py:168` + `market_service.py:732/754` + 1 单测 + e2e 1 项。
  ⚠️ **不可把 `asset_type` 直接改成 `'etf'`**——`WatchlistPanel.vue:343-347`、
  `PortfolioManager.vue:594`、`UnifiedAnalysis.vue:48`、`pricing.py:195-198`、`market.py:924-939`
  五处消费方按「`asset_type` = 市场码」工作。
- **方案 B（P0，R201）**：① `macro_fetcher.py:120` 改用已有的 `_latest_row(df)`（`:222-227`，
  order-agnostic，`fetch_cpi_ppi:167` 已在用）；② `:568-570` 的 M2 slope 腿同样改 `_latest_row`
  排序后再取末值；③ `_stale_note:33-48` 补 `YYYY年MM月份` 分支（或复用 `_latest_row._parse`
  的 `replace("年","-")`），并**改为 fail-closed**（解析失败 → `stale=True` + note）。
  **守卫**：`tests/test_macro_fetcher.py` 新增「真实行序（最新在前）夹具 → 断言取到的 date == max」
  +「非法日期串 → `stale=True`」（负向：现实现必 FAIL）。
  ⚠️ **必须同时把 `test_macro_regime.py:84-88` 与 `test_macro_factors.py:54-64` 的 `_m2_df`
  夹具翻转为最新在前**——否则修复会看起来像回归（这两个夹具当前主动确认错的不变式）。
  **影响**：`macro_fetcher.py` 3 处 + 1 单测 + 2 夹具翻转。
- **方案 C（P1，R202）**：① `hub/_pool.py:113` 缺键**不补 0.0**——改为把该键标成「缺失」
  并在 `factor_breakdown` 输出时省略（或输出 `None`），使下游 LLM 表格显示「—」而不是一个
  伪值；② 若必须保留数值供引擎排序，则在 `allocation_breakdown` 之外**单独加
  `factor_breakdown_missing: [keys]`** 供 LLM 显式声明降级；③ `allocation_engine.py:923` 的
  `round(v,3)` 保持不变（它不是缺陷，是**让 R197 可被肉眼发现的必要条件**——保留它，
  让「两个标的逐字节相同」成为可断言的信号）。
  **守卫**：单测「N 标的 / K 个缺某键 → 缺键标的之间该键值必须不同，或该键必须缺失」
  （负向：改回 `get(key,0.0)` 必 FAIL）；e2e 按 round57 原意改为**三元组 distinct 数 > N/2**
  且**不得读 coarse 已字符串化的字段**。
  **影响**：`hub/_pool.py:113` + `allocation_engine.py:923`（不改）+ `strategy_design.py:484-494`
  + 2 单测 + e2e 1 项。
- **方案 D（P1，R203）**：① `sector_fetcher.py:282-292` 占位追加改为**不进入返回列表**
  （或加 `is_placeholder: true` 标记并由所有消费方过滤）；② `market.py:234-240` 把
  `fetch_industry_sectors` / `fetch_concept_sectors` **拆成两次独立 `run_sync`**（各自预算），
  或把预算提到 ≥ 实测冷耗时并加预算一致性测试。
  **守卫**：单测「概念源抛异常 → 返回列表中 `sector_code` 为空的行数 == 0」（负向：现实现为 40）；
  `_search_sectors` 预算一致性测试（对照 `test_llm_stream_retry.py` 的既有形态）。
  **影响**：`sector_fetcher.py:258-294` + `market.py:234-240` + 2 单测。
  ⚠️ **需先验占位行是否已被 `compute_sector_momentum` 消费**（本轮 `get_sector_momentum=0` 行
  未证实污染，但 `_search_sectors` 之外还有 3 个消费点）——列为方案 D 的**前置探针**。
- **方案 E（P2，R204）**：`client.py` 在 `llm_complete_stream` 内补 `_r05_403_allow` 读侧
  （位置对齐 `:335` 之后），并**修正 `:419-420` 说反的注释**。
  **守卫**：单测「SSE 路径连续 2 次 403 → 第 3 次该 provider 零探测」（与
  `llm_complete_with_system` 的 `:597` 断言对称）。**负向：现实现必 FAIL**。
- **方案 F（P2，R205）**：① `main.py:405-425` 的 120s 循环内，`enrich_news_summaries` 加
  「距上次成功 > N 分钟」冷却（当前每轮都重试 `rule` 来源条目）；② `skip_llm` 闸失效时
  追加单次调用数硬上限；③ 启动期 Zen 目录轮盘按 round58 §D 残留 1 排期（持久化排除态）。
  **守卫**：单测「两次 enrich 之间无新条目 → LLM 调用数 == 0」；巡检指标「后台 LLM 占墙钟
  比例 > 20% 告警」。**不得**用「降低 cap」冒充修复（那是把问题藏起来）。
- **方案 G（P2，R206）**：把 `_llm_timeout_for` 的 `partial` 档（`strategy_check.py:738`）
  从固定 30s 改为**按 provider 实测 p95 × 1.5**（数据源用 `token_usage.usage_records` 的
  `duration_ms` 分位数，24h 滚动）；同时**修两处悬空注释**（`strategy_check.py:732` 引用的
  测试文件已不存在、`reports.py:873` 的「75s」实际 180s）。
  **守卫**：单测「partial 档 ≥ 录制的 p95 × 1.5」（负向：改回 30s 必 FAIL）；
  e2e 的「LLM 连通性 read timeout」项按新档位重定阈值。
- **方案 H（P2，R207）**：`strategy_check.py:84-92` 空组合分支显式返回
  `report_quality="empty"` + `is_fallback=False` + `llm_layer_ok=False`；
  `strategy_check_worker.py:131` 的 `or "full"` 兜底改为「缺键即 `empty`」（配合 `task_manager.py:423`
  已有先例）；`:665-667` 注释与实现对齐。
  **守卫**：单测「空组合 → `report_quality == 'empty'`」（负向：现实现必为 `full`）。
- **方案 I（P3，R208）**：`allocation_engine.py:1827` 的 `entry = dict(np)` 在 `:1845` 合并
  **之后**重算 `combined_weight`（或直接删掉该字段——它只是触发条件记录，
  `enforce_max_correlation:1905` 的写法有 note 自证）；`strategy_design.py:685` bucketing 后
  再刷一次 `risk_metrics`。
  **守卫**：单测「非豁免 pair 触发合并 → `combined_weight` == 两标的最终权重之和」
  （负向：现快照必不等）。**注意**：金夹具不可见，需新增一个**非锚** pair 的夹具。
- **方案 J（P3，R209）**：`market_service._fetch_one` 的每行补 `as_of`（源刷新时间，
  无则不写——R80 规范），`routers/market.py:874-901` 归一化保留。
  **守卫**：单测 + e2e「`price` 非空 → `as_of` 非空」。**不得**为「凑字段」写假时间戳。
- **方案 K（P3，R211）**：① 修 `_technical.py:13` docstring（改为「专用 dict + 裸 symbol」，
  并说明为何不用命名空间键）；② 契约 `advice-valuation.md` 补 `valuation`/`event`/`rotation`/
  `allocation` 四族的 §3 表 + 补 8 个未文档化词 + 把 §2 示例 `怎么配` 改为可路由的 `配置`；
  ③ **契约一致性校验并入 `check_routes` 契约段**（断言 `intent.py` 每个词表在契约有对应行 +
  契约 §3 无代码外词）。
  **守卫**：并入既有门禁段②，不新增段。
- **方案 L（P3，R215）**：prompt 侧加硬约束「`stale=true` 的值必须在其后 10 字内出现其 `date`」；
  `_build_market_overview` 渲染时把 `stale` 项加「（数据日期 YYYY-MM，源滞后）」后缀。
  **守卫**：单测（渲染含日期后缀）+ 报告内容断言（PMI 附近出现 `2025-08`）。
- **方案 M（流程，R212）**：`check_test_baseline` 或并入既有测试文件（沿用 round57 F1 决策），
  或提 BASELINE 321→323 + review；`ruff --fix` 清 21 个（I001/F401/F811），B023 需人工判定
  （`main.py:506-508` 的 `_sem` 若定义在循环外则为**误报**，需在 `noqa` 或改写消除）。
- **方案 N（环境/方法，R213）**：诊断模板 §环境步骤 追加「overlay 方案的副作用：`COPY dist`
  是合并非替换，须 `RUN rm -rf` 后再 COPY 或改用可用基础镜像源」（round57 §1 的补充）；
  探针清单追加「overlay 方案下须核对容器 assets 数量 vs 宿主 dist 数量」。
- **方案 O（文档，R214）**：三份文档 §9 去重——保留 round57 的完整版，round58×2 的 §9 改为
  「本轮复测结论（引用 round57 §9）」+ 本主题专属条目；`docs/archived/README.md` 登记。

---

## 5. 三轮 Review 记录

### 5.1 Round 1 — 事实核对

| 项 | 核对方式 | 结论 |
|---|---|---|
| 镜像 = HEAD | `docker cp` 8 文件 + SHA256 逐个对比宿主 | ✅ 8/8 MATCH（非依赖 COPY 缓存显示） |
| frontend overlay = HEAD | 容器 `index.html` 引用 `index-CxCcoyv-.js` / `AiDesign-CU6nx3xP.js`，与宿主 `dist/assets` 同名 | ✅ |
| warmup 30.6s + 双告警 | backend log `[warmup-budget]` 原文 + `30.7s` 旧格式 | ✅ |
| R196 「有标签必有值」 | 38 行 `label_without_value = 0`、`null price = 0` | ✅ |
| R197 复发规模 | 19 标的 → 5 块（`r197.txt` 全量分组表） | ✅ |
| R197 机制 | 9 个独立键解出 `(N-3) = 34.0000000000x`（1e-13）+ `round(159338_block,3) == 588200_block` 全 37 键 True + `kline_cache.json` 19 个 md5 互异（排除缓存碰撞） | ✅ |
| R198 | `综合信号 ×29` + `因子综合分 ×3` | ✅ |
| R199 | `divergence_detail` 28/30 非空 | ✅ |
| R191 | 13 离散值 / `-0.21` 零出现 | ✅ |
| R03 防御锚 | balanced + 防御型 defense = 2 只（511090 + 518880） | ✅ |
| R04 模板收敛 | 「未提供」0 / 「暂无法验证」0 / 「无法确认」0 | ✅ |
| R03b 美债去重 | 全文 `5.xx` 唯一值 5.24（`domestic_macro.bond_yields.us_10y=5.28` 未进 prompt） | ✅ |
| R01 成长告警触发 | e2e `[FAIL] F7 balanced 成长风格 4 只 > 上限 3 只` | ✅ |
| R200 | 手测「创新药」`all`=2（全 index 段）+ e2e `A股搜索(510300) 0 条` + 容器内 `search_etf` 返回 `asset_type='A'`（20/20 行） | ✅ 三方互证 |
| R200 时序 | `git blame` → producer `c519c7a`(2026-07-15) / consumer `72ad22d`(2026-07-31)；`git show 980a1c5:...` 确认 round57 基线**已存在**（非回归） | ✅ |
| R201 | akshare 实测 224 行 row0=2026年08(M1 4.1/M2 7.5) vs row223=2008年01(M1 20.54/M2 18.88)；`ctx` 实返 2008 三个值 | ✅ 数字逐位对上 |
| R201 fail-open | `_stale_note('2008年01月份')` → `(False,'')`（子代理直接执行验证） | ✅ |
| R203 占位 | 容器内 `fetch_concept_sectors(600)` → 40/40 `sector_code` 空、`price/change_pct/volume/main_inflow` 全 0 | ✅ |
| R203 超时 | 手工探针两次 `run_sync` 均 10.04s / 10.02s 超时；`fetch_concept_sectors(600)` 冷 **25.90s** / 热 0.00s | ✅ |
| R204 | `grep` `_r05_403_allow` → 仅 `:55`/`:597`/`:762-763`，全在 `llm_complete_with_system`（def `:563`）内；`llm_complete_stream`（def `:298`）零出现 | ✅ |
| R205 | `usage_records` 1h 窗口 54 条 / 51 次 news summary / 448.8s / 9 失败 | ✅ |
| R206 闭环 | `usage_records` id=64782 `run success=1 34.2s` vs check175 summary「30s 未返回」 | ✅ |
| R207 | check 173 @03:50 / 174 @09:44 UTC，`summary="组合为空"` + `full` | ✅ 今日活体 |
| R208 | 3 个 `combined_weight` 全部由 `round(w/0.05)*0.05` 精确命中；金夹具 pair 是 `CORE_ANCHORS` 豁免对 | ✅ |
| N1 档位 | `strategy_check.py:735-739` 15/30/180 | ✅ |
| pytest / vitest / DHC | 各自输出尾行 3583 / 579 / 13-of-13 | ✅ |
| Lighthouse | 4 份 json（`/`×4 + 404 页×2 复用旧文件），中位数按 round57 口径 | ✅（`/dashboard` 沿用 round57 遗留的 `lh_dash1/2.json`，本轮亦重跑 1 次） |
| DOC-2 | `dom_dash.html` 7452B / text 511 字 / 无标题 / has-404=True | ✅ 维持 |
| e2e 9 FAIL | `e2e_fails.txt` 逐条 L 行号 + 上下文 | ✅ |
| ruff 22 / baseline 323 | `ruff --output-format=concise` 逐行 + `check_test_baseline` 原文 | ✅ |

### 5.2 Round 2 — 逻辑一致性

- **R197 是「R197 复发」而非「新发现同类」**：round57 §4.1 R197 记录 design62 的 6 标的三元组克隆，
  明确留「克隆源头未定（周末陈旧 vs 共享序列 vs coarse 回退，待交易时段二分）」。本轮**证伪了
  round57 的两个候选假设**（磁盘缓存 19 个 md5 互异 → 非陈旧/共享序列；coarse 只改 weight/factor_score
  → 非 coarse 回退），并给出第三条（缺键补 0.0）+ 算术证明。**round57 §9.1 的「R197 未复测」
  与两份 round58 §9.1 的「R197 三元组克隆 ✅ 未复现」需要更正**：那次「未复现」是因为当时按
  `factor_breakdown` 的 `return_1m`/`return_3m` 直读——而 HEAD 的真实键名是 `etf.return_1m`/`etf.return_3m`，
  **旧口径读到的是不存在的键（恒 0），因此「未复现」是口径失效的假阴性**。这是本轮最重要的一条
  方法论更正，直接推翻两份 round58 文档的 PASS 结论。
- **R200 与 R203 的区分**：`all` 模式结果变少有两个独立原因（ETF 段被 `asset_type` 过滤清零
  + sector 段被占位行的空 code 跳过），二者叠加才使「创新药 13 → 2」。**不合并为一条**——
  修其一不会修另一条。
- **R201 与 R215 的区分**：R201 是**取值错**（2008），R215 是**取值对但时效未披露**（PMI 2025-08）。
  两者共用 `_stale_note`，但修一处不解决另一处。
- **R202「coarse 只是呈现」与实际**：snapshot note 声明 coarse「权重按 5% 档位呈现、因子分仅显示
  分档」——**这句本身是真的**（`_apply_precision_bucketing:1278-1296` 只改 weight 与 factor_score）。
  错的是「声明的对象」：真正被污染的 `factor_breakdown` 不在 coarse 的射程内，而 coarse 又
  **顺手关掉了唯一的方差守卫**（`verify_e2e.py:504` 读的 `factor_score` 在 coarse 下已是字符串）。
  故不是「声明撒谎」，是「诚实机制瞄错了靶 + 降级自我屏蔽」。分档定性准确。
- **R205 的 82% 窗口**必须标注口径：5 分钟窗口 82%、1 小时 12%、6 小时 2% —— 波动窗口内
  与交互请求撞车才是问题，**不是「后台长期霸占 82%」**。已按区间记录，避免 round56 §4.1 的
  「诊断数字方法学」教训（无方法标注的百分比会被误读）。
- **N4 与本轮 R207 的口径**：round58-portfolio §9.3-N4 记 108 条「组合为空」并自我推翻
  「测试污染」假设，结论是「历史产品运行记录」。本轮 check 173/174 是**今日**产生
  （03:50 / 09:44 UTC，均在本轮容器启动 18:51 之前 → 来自宿主后端进程）→ **不是历史遗留，
  是持续在产生**。这修正了 round58 的「历史」定性。
- **性能口径分离**：慢归慢、假归假。周末慢三项（fh 5.91s / llm-health 10.63s / heat 7.04s）
  已定性为源侧/窗口性；`realtime/portfolio` **2.12s 达标**（round57 16.67s → round58 盘中 0.84s
  → 本轮 2.12s，三点同量级改善，不是回归）。

### 5.3 Round 3 — 完整性

- **验证窗口标注**：实时类全标周末形态；R200/R203 的实值复测、R202 的上游成因（K 线预热饥饿）
  标「待交易时段复测」；R201/R204/R206/R207/R208 均为**确定性缺陷**（与行情源无关），不需窗口。
- **未执行/未取证诚实标注**：① 未截取 advice prompt 原文（故「MACD 多头」等方向词标
  **未判定**而非合理/臆断）；② `compute_sector_momentum` 是否消费占位行**未证实**（列为方案 D
  前置探针）；③ `/dashboard` Lighthouse 沿用 round57 遗留采样 + 本轮 1 次重跑；
  ④ **patrol 与手工 ruff 的 I001 计数差 1（14 vs 15），原因未查**，按 round56 §4.1
  「诊断数字方法学」登记为待查而非擅自采信；⑤ 容器回收待拍板（§6 #17）。
- **未决项**：R200-R215 全部登记（§6 决策点）；§4.2 方案 A-O 全部只写方案未写代码 ✅。
- **合规**：全程未写修复代码（唯一产物 = 本文档 + 探针不入仓 + host `frontend/dist` gitignored +
  探针期间在容器内执行的只读 python 片段）；未 merge、未 push。
- **工作树状态**：进入本轮时已有未提交改动（`backend/scripts/probe_*.json` 修改、
  `docs/archived/README.md` 修改、round53/54/55 的 `git mv` staged+untracked 混合、
  `tmp/` 未跟踪）→ **均为他轮遗留，本轮不动**（AGENTS.md「多会话并行同一工作树」纪律）。
  ⚠️ 登记：那 3 个 round 文档的归档处于「staged 删除 + untracked 新增」的**半完成态**，
  若后续提交必须显式核对，否则会产出「删了但没加」或反之。

### 5.4 Round 4 — patrol 回填（2026-10-03 21:16）

| 项 | 核对 | 结论 |
|---|---|---|
| patrol 总时长 / exit | `patrol60.log` 尾行 `exit 1 (1385.53s)` | ✅ |
| 8 项 PASS 逐条 | L1-unit / L2-health / L2-alloc-invariants / L2-llm-exclusion / L4-routes / L4-purity / L4-async / L5-frontend | ✅ 与 §2.9 独立跑的结果一致（pytest 3583 / DHC 13/13 / vitest 579） |
| L2-e2e timeout 900s | 本轮独立 `verify_e2e` 实耗 ~25min（4 次 LLM × ~80s + 2 个 120s 轮询窗） | ✅ 归类**预算性**，非回归（独立跑 267/276 已记录） |
| L3-perf timeout 120s | 周末慢三项合计 5.91+10.63+7.04 = 23.6s 单次，全套巡检含冷缓存远超 120s | ✅ 归类**预算性** |
| L4-baseline 323>321 | `check_test_baseline.py` 原文 | ✅ **R212**（治理债） |
| L4-ruff 22 errors | patrol 报 14 I001 / 手工 `ruff check app --output-format=concise` 报 15 I001 | ⚠️ **口径差 1，原因未查** → 按 round56 §4.1「诊断数字方法学」登记为**待查**，不擅自采信任一口径 |
| tests_ok 凭据 | `files_hash=c1b0fdf5c6d6` 与 exit 1 并存 | ✅ 仅对应 L1，标注不采信为全量绿（round57 §0#18 口径沿用） |

**Round 4 结论**：§5.1–5.3 的全部事实核对在 patrol 口径下**无推翻项**；新增 1 条待查
（ruff I001 计数口径差 1）。

---

## 6. 决策点

| # | 决策 | 选项 + 推荐 + 影响范围 | 状态 |
|---|---|---|---|
| 1 | **R200 搜索 ETF 段** | **推荐方案 A**（`fetch_etf_list` 补 `market`/`type` + router 过滤改 `type` + 排序契约同步 + 2 守卫）。**P0 且已死 9 周**，且 e2e 每轮都在报却被归环境性——建议**单独一轮、优先做**。影响 `china_market.py`×2 / `market.py:168` / `market_service.py:732,754` / `test_search.py` / `verify_e2e.py` | 待拍板 |
| 2 | **R201 宏观取数** | **推荐方案 B**（3 处取数改 `_latest_row` + `_stale_note` 补格式分支并 fail-closed + **必须同时翻转 2 个测试夹具**）。P0 数据正确性。影响 `macro_fetcher.py`×3 / `test_macro_fetcher.py` / `test_macro_regime.py` / `test_macro_factors.py` | 待拍板 |
| 3 | **R202 因子克隆** | 三选一：**方案 C-1**（缺键不补 0.0，输出省略 + 加 `factor_breakdown_missing`）**推荐** / C-2（保留数值但加缺失清单）/ C-3（仅补守卫不修数据，**不推荐**——治标）。另**必须**落 round57 §4.2 提了两个月未落地的 e2e 三元组方差断言（按正确键名 `etf.return_*`）。影响 `hub/_pool.py:113` / `strategy_design.py:484-494` / 2 单测 / `verify_e2e.py` | 待拍板 |
| 4 | **R203 板块搜索 + 占位** | **推荐方案 D**（占位行加 `is_placeholder` 标记并全消费方过滤 + `_search_sectors` 拆两次 `run_sync` 各自预算）。**前置**：先验占位行是否已被 `compute_sector_momentum` 消费（探针，单次） | 待拍板 |
| 5 | **R204 SSE 熔断只写不读** | **推荐方案 E**（补 `_r05_403_allow` 读侧 + 修注释 + 对称守卫）。P2，一行级逻辑 + 1 单测 | 待拍板 |
| 6 | **R205 后台 LLM 扇出** | **推荐方案 F**（enrich 冷却 + 闸失效时硬上限 + 启动轮盘排期）。**不建议**用「降 cap」冒充修复。P2 | 待拍板 |
| 7 | **R206/N1 预算档** | **推荐方案 G**（`partial` 档按实测 p95×1.5 + 修 2 处悬空注释）。round58 §9.3 已给出量化依据（真实负载 4.6k tok 骑 30s 边界；本轮 10,589 tok / 34.2s 再次坐实）。P2。**需注意**：改预算会改既有测试的断言值 | 待拍板 |
| 8 | **R207/N4 空组合记 full** | **推荐方案 H**（空组合返回 `empty` 档，`task_manager.py:423` 已有先例）。P2。**会改动既有历史记录的展示语义** → 需确认是否回溯迁移 | 待拍板 |
| 9 | **R208 combined_weight** | **推荐方案 I**（合并后重算，或直接删字段）。P3。**注意金夹具不可见**，需新增非锚 pair 夹具 | 待拍板 |
| 10 | **R209 as_of 缺失** | **推荐方案 J**（`_fetch_one` 补 `as_of`，无源则不写）。P3。**不得为凑字段写假时间戳** | 待拍板 |
| 11 | **R211 契约/注释漂移** | **推荐方案 K**（修 3 处 + 契约补 4 族 §3 表 + 8 词 + `怎么配`→`配置` + **契约一致性校验并入 check_routes 契约段**）。P3。**不新增门禁段** | 待拍板 |
| 12 | **R215 stale 值时效** | **推荐方案 L**（渲染加日期后缀 + prompt 硬约束 + 报告内容断言）。P3 | 待拍板 |
| 13 | **R212 门禁债** | **推荐方案 M**：① 测试文件**并入既有文件**（沿用 round57 F1 决策，不提 BASELINE）**或**提 321→323 + review（**需你选**）；② `ruff --fix` 清 21 个；③ B023 需人工判定（`main.py:506-508` 的 `_sem` 若在循环外则误报）。**注**：本项在下一轮实施前会持续 FAIL，且 patrol 本轮已把它列为唯一非预算性 FAIL | 待拍板 |
| 14 | **R213 overlay 副作用** | **推荐方案 N**（模板补副作用条目 + 探针核对 assets 数量）。无代码影响 | 待拍板 |
| 15 | **R214 文档去重** | **推荐方案 O**（保留 round57 §9 完整版，round58×2 改引用 + 主题专属条目）。无代码影响 | 待拍板 |
| 16 | **门禁归因纪律**（元决策） | e2e 的 9 个 FAIL 连续 3 轮被笼统归「环境性/STORM」，致 P0 死 9 周。**推荐**：在 `known-env-issues.md` 的归因流程里加一条硬要求——「门禁 FAIL 转环境性前必须先 `rg` 定位到代码行，并写出指纹」，否则不得归类。**不新增门禁段**（写入既有归因流程） | 待拍板 |
| 17 | **容器回收** | 诊断证据已全部落盘（探针目录 + 本文），**推荐立即回收**；若需在容器内复测某项 FAIL 再起 | 待拍板 |
| 18 | **文档归档** | ✅ **已拍板并执行（2026-10-03，round61 收尾）**——归档 `round56`（§6 全 10 项已闭/已转出 + 路径引用 0）、`v7-p2-dsh-harness-comparison.md`（一次性探针，外部引用 0）、`evals-report.md`（可重生成产物）；**保留** `v7-p1.5`（其决策仍生效：`lg_agent.py` 在生产）。**附带修复**：上一会话对 round53/54/55 的归档半完成态（` D`+`??`，若 `commit -a` 会丢三份文档）已 `git add` 修正为 rename。详见 `docs/archived/README.md` 顶部条目 | ✅ 已执行 |

> 拍板后固定收尾：① 本节回填；② memory 同 name 覆盖更新。

---

## 7. 本轮验证命令备忘（复现用）

```bash
# 前置：Docker daemon 未起时先拉起（com.docker.service Stopped → Docker Desktop）
# 容器（prod + diag overlay；registry 不通时 backend 先 build，frontend 走 overlay）
docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod build backend
cmd /c "npm run build"                                   # workdir frontend（node 主版本对齐镜像）
docker build -t etf_surge-frontend:latest <含Dockerfile+dist 的外部上下文>
docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod up -d --no-build
# 镜像验明（round57 方法，不依赖 COPY 缓存显示）
docker cp etf_surge-backend-1:/app/app/analysis/intent.py <tmp> ; 对比宿主 SHA256

# 探针（宿主代理常驻 → 统一 --noproxy '*'；输出 -o 落盘，禁管道直解）
curl.exe --noproxy "*" -s -o rt.json -w "%{http_code} %{time_total}s" http://localhost:8000/api/v1/market/realtime/portfolio
# ⚠️ advice 请求体字段是 query 不是 question；llm-report 用 question（以 openapi 为准）
# WS：py -3.12 + websockets + proxy=None（清空 *_PROXY），直连 8000 与经 nginx :80 各一次
# 容器内只读探针：docker exec etf_surge-backend-1 sh -c "cd /app && PYTHONPATH=/app python /tmp/x.py"

# 门禁
python -m pytest -n auto -q                    # 3583 passed（-n auto 有页面文件风险见 known-env-issues §1.6）
cmd /c "npm test"                               # workdir frontend（579）
python scripts/data_health_check.py             # 13/13（预算 600s）
python scripts/verify_e2e.py --host 127.0.0.1 --port 8000    # 267/276
python scripts/check_routes.py ; check_engine_purity.py ; audit_async_blocking.py ; check_test_baseline.py
python -m ruff check app --output-format=concise
# Lighthouse（容器 prod 前端在 :80，勿用 dev :5173）
$env:CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
node_modules\.bin\lighthouse.cmd http://localhost/ --only-categories=performance,accessibility,best-practices,seo --output=json --output-path=<p>/lh_home_1.json --chrome-flags="--headless=new --no-sandbox --disable-gpu"
# 浏览器走查
msedge.exe --headless=new --disable-gpu --virtual-time-budget=15000 --dump-dom http://localhost/<route>
```

*诊断产物：`C:/Users/Public/etf_probe/`（会话级临时目录，不入仓）。未收到「round实施」不写修复代码。*

---

## 8. 资源回收 + 文档归档（收尾，2026-10-03 21:40）

### 8.1 资源回收

- [x] 诊断证据已落盘（探针目录 336 文件 + 本文档 + DB 快照 `struct60.txt`/`r197.txt`/`prec.txt`/`fb60.txt`）
- [x] `docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod down`
- [x] `docker ps -a` → 无本项目容器（backend/redis/network 均已 Removed）
- [x] `docker image prune -f` → 回收 0B（无新 dangling 层）

### 8.2 文档归档（已执行）

归档（`git mv`，git 识别为 rename）：

| 文件 | 归档依据 |
|---|---|
| `round56-container-reacceptance-round55-fixes.md` | §6 全 10 决策点已闭/已转出（转出记录在 round57 §4.3）；**路径引用 0** |
| `v7-p2-dsh-harness-comparison.md` | 一次性第三方 Harness 探针产物；**外部引用 0** |
| `evals-report.md` | 可重生成产物（`scripts/evals/report.py --out`），数据已过期 |

保留（逐份核对引用数后维持）：`v7-p1.5-langgraph-comparison.md`（其决策仍生效——
`app/agentic/lg_agent.py` 在生产 + 3 测试在跑）、`engine-dedup-layers.md`（自身结论节 3 项待做未闭）、
`round35`（40 引用）/ `round36-B5`（4）/ `redundant-review`（11）/ `etfsurge-agentic-upgrade-v7`（6）/
`advice-goldset-design`（19）/ `round57`（12）/ `round58×2`（30/5 路径）/ `round59`（21），
以及常驻 `known-env-issues` / `design-checklist` / `patrol-orchestration-plan` / `prompt-templates/` / `api-contracts/`。

引用同步：`backend/scripts/evals/report.py:6` 用法示例改指归档路径 + 注明；
`docs/round57-*.md` 头部补「归档提示」段。代码/契约中「round56 §x」短名引用**按既有惯例未改写**
（与 2026-09-18 归档 round53/54/55 时的处理一致，那批同样保留 35/8/9 处短名引用）。

⚠️ **附带修复**：上一会话对 round53/54/55 的归档处于**半完成态**——文件已移入 `docs/archived/`
且内容逐行一致（383/157/230 行），但 git 未 stage（` D` + `??`）。若当时执行 `git commit -a`
（只 stage 已跟踪文件的修改/删除、**不含 untracked**），会提交删除而不含新增 → **三份文档从仓库彻底消失**。
已 `git add` 修正，git 现识别为 `R`（rename）。**教训入档**：归档必须用 `git mv` 并确认
`git status --porcelain` 显示 `R` 而非 `D`+`??`。

---

## 9. 会话记忆（收尾时写）

见 memory 条目 `round61-容器全链路诊断-round57-59批复验-2026-10-03.md`。
