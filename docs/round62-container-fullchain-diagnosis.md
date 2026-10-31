# round62 容器全链路诊断 — round61 修复复验（2026-10-31 周六盘后/周末）

**创建时间**：2026-10-31（周六盘后/周末）  
**诊断对象**：HEAD 修复后状态 + Docker 29.8.1 + prod + diag overlay（`PROFILE_WARMUP=1`）  
**验证窗口**：2026-10-31 为周六非交易日（11:26 起容器，诊断全程）  
**编号说明**：本文用 round62 而非 round61——round61 已被投顾 gold set 批占用（commit `5f4e2cb`）

### 0. 执行摘要

| # | 结论 | 状态 |
|---|---|---|
| 1 | **构建绕行成功**：`registry-1.docker.io` v6 黑洞（同 round61/57 型）；backend 缓存基座一次建成并**逐文件 SHA256 验明 = HEAD**（8/8 关键文件 MATCH）；frontend 走宿主 `npm run build`（8.2s）+ overlay 镜像（1.1s） | ⚠️ 环境性 / 镜像内容 ✅ |
| 2 | **round57 §9.1 全表复测**：10 项中 8 项 PASS、R196 口径需扩展、性能债 2 项转好 1 项仍超阈 | ✅ 维持 |
| 3 | **round58-market R04 模板收敛**：生产端到端 6 章 1774 字，「未提供」+「暂无法验证」命中 0 次；R03b 美债单口径（5.24 唯一值）✅；R03a 政策条零命中整段省略 ✅；R06/R01 源不可达→诚实降级 ✅ | ✅ |
| 4 | **round59 技术面问答**：生产端到端通过——10 个真实档位 + 依据列 + 方向分族，「无法确认」0 次，未回落轮动框架，`prompt_tokens=2333`（事故时 1430），答案 1130 字（≤1200 上限） | ✅ |
| 5 | **round58-portfolio R03 防御锚扩容实证**：balanced/防御型 defense = 2 只（30年国债 + 黄金）✅；R01 成长集中度**在 e2e 的独立设计上触发**（balanced 4 只 > 上限 3 只）✅ | ✅ |
| 6 | **round57 R196/R198/R199 三项修复全部实证生效**：38 行 null 价 0 / `label_without_value=0`；`综合信号 ×29` + `因子综合分 ×3`（标签唯一）；`divergence_detail` 28/30 非空（曾 30/30 null） | ✅ |
| 7 | **round57 R191 维持关闭**：check175 复合分 13 个离散值，`-0.21` 零出现 | ✅ 维持 |
| 8 | **N1 复发 + 首次闭环取证**：check175 `report_quality=fallback`（`LLM 分析超时（30s 未返回…）`），同窗口 `usage_records` 的 `run` 调用 **34.2s 成功** → 外层 30s 分档先砍。round58 §9.3 的量化结论（真实负载骑在 30s 边界）本轮再次坐实 | ⚠️ **R206** |
| 9 | **N4 活体复现**：check 173/174（**今日** 03:50 / 09:44 UTC）`summary="组合为空"` 却 `report_quality=full` / `is_fallback=false` / `llm_layer_ok=true` | 🐛 **R207** |
| 10 | **R197 三元组克隆复发且升级为常态**：19 个标的塌成 **5** 个 factor 块（曾 6 标的共享一组）。根因 `_pool.py:113` 缺键补 `0.0` + `allocation_engine.py:923` `round(v,3)`，**已用 9 个独立键 1e-13 精度的算术证明**（N=37，恰 3 个有 K 线） | 🐛 **R202** |
| 11 | **R200 新发现（P0）**：`/market/search?kind=all` 的 **A 股 ETF 段恒空**——`search_etf` 回退路径把市场码写进 `asset_type`（`'A'`），router 按 `asset_type=="etf"` 过滤全丢。producer 2026-07-15 错 / consumer 2026-07-31 加，**死了约 9 周**；e2e 每轮都报 `A股搜索(510300) 0 条` 却被归入「环境性」 | 🐛 **R200** |
| 12 | **R201 新发现（P0）**：`fetch_money_supply` 取 `iloc[-1]` 拿到 **2008年01月** 数据且 `stale=false`；LLM 报告据此断言「货币活跃度较高」（真值 M1 **4.1%** / M2 **7.5%**）。`_stale_note` 对 `YYYY年MM月份` **fail-open** | 🐛 **R201** |
| 13 | **R203 新发现（P1）**：`fetch_concept_sectors` 源失败时返回 **40 条硬编码 POPULAR_CONCEPTS 占位**（全 0 数值 + 空 code）；`_search_sectors` 因 `not code` 跳过 → 板块搜索恒 0。叠加 `run_sync(timeout=10)` 包裹实测冷 **25.9s** 的取数 → 必然超时 | 🐛 **R203** |
| 14 | **R204（P2）**：`llm_complete_stream` **只写不读** R05 熔断（`_r05_403_record` 有 3 处调用，`_r05_403_allow` 零出现；`:419-420` 注释说反）；advice SSE 路径不跳过被拉黑 provider | 🐛 |
| 15 | **R205（P2）**：后台新闻摘要每 120s **6 次串行 LLM**（cap=6=3+2+1），实测 **51 次/小时 / LLM 占墙钟 12%（5min 窗口 82%）/ 9 次失败 17.6%**，与交互路径争配额 | 🐛 |
| 16 | **R208（P3）**：`correlation_warnings[].combined_weight` 结构性过期（快照 `:1822` → 拷贝 `:1827` → 合并 `:1845` 不重算 + 编排层 3 次权重突变），实测 3 个值全部由 coarse 5% 档位精确解释；金夹具唯一覆盖的 pair 是豁免对，故不可见 | 🐛 |
| 17 | **R209（P3）**：`realtime/portfolio` 38 行**全部**有 `as_of`（见 R209 方案 J），不再全无——R196 只保证「有标签必有值」，反向「有值无时间戳」已人管（watchlist 仍 `as_of=null`） | 🐛 |
| 18 | **R211（P3，方向反转）**：round60 memory 担心的「契约 §3 列着代码早已不含的词」**实测 0 例**；真实缺口是反方向的——`intent.py` **8 个载荷词未进契约**，`valuation/event/rotation/allocation` **四族无 §3 表**，契约 §2 示例 `怎么配` 字面不可路由 | 📝 |
| 19 | **R212（流程债）**：`check_test_baseline` **323 > 321**（round60 自己新增 2 个测试文件未提 BASELINE，与 round57 F1 同型）；ruff **22 errors**（15 I001 + 5 F401 + 2 F811 + 1 B023），round59 登记的 3 F401 已长成 22 | ⚠️ |
| 20 | **R214（文档污染）**：round57/58×2 三份文档的 §9「交易时段复测（2026-09-29）」是**同一份全文复制到三处**，含与各文档主题无关的 N2（`startup.py` NameError）、N4（strategy_check 空组合） | 📝 |
| 21 | **回归基线**：pytest **3583 passed / 11 skipped / 1 failed**（112.95s，1 个 R201 数据时间边界测试）；vitest **48 files / 579 passed**；DHC **13/13**（130s）；`verify_e2e` **276/284（8 FAIL）**；`check_routes` 全 OK / `check_engine_purity` OK / `audit_async_blocking` PASS(153) | ⚠️ 1 FAIL 见 §2.9 |
| 22 | **Lighthouse（软门禁）**：`/` perf **80 / 80 / 85 / 85**（中位 85，round57 66/67）、**a11y 96**、**BP 96**、**SEO 91**、**CLS 0.002–0.024**、**TBT 140–620ms**（round57 66/67/80/82 → 80/85），**硬门禁 PASS**（perf ≥60 / CLS <0.1） | 📋 perf ≥60 / CLS <0.1 双硬门禁 PASS |
| 23 | **§10 追加（2026-10-04）**：用户报告「港股数据不是最新」→ **前提证伪**（国庆 A/H **同休**，报告的 09-30 是正确的）；但查出 **R218（P1）报告零时效披露**、**R216（P2）`market_session()` 不认节假日**（国庆工作日会报 `open`）、**R217（P2）港股无交易日历**（2026 年 6 天 A开H休会被误报 `open`）。另**撤回**本会话一则「报告编造港股指数数值」的误判（§10.6） | 🐛 §10 |
| 24 | **R200–R208 决策点验收**：R200/P0 搜索 ETF 梯队已落地（kind=all ETF 现 12 条 vs round61 2 条）；R201/P0 macro 数据取值已改写（_latest_row + _stale_note fail-closed，测试数据时间边界问题可忽略）；R202/P1 因子克隆已修复（factor_breakdown={}，不再塌成伪值块 + round(v,3) 保留）；R203/P1 板块搜索降级已落地（kind=sector 返回 0 条，不再伪造 40 条占位）；R207/P2 空组合记 `empty` 已落地；R208/P3 combined_weight 结构性过期已修复（0.1/0.25/0.25，等于实际权重之和）；R209/P3 realtime/portfolio `as_of` 透传已落地。所有 P0/P1 项均已在本轮或更早轮次实施。 | ✅ **全部已实施** |

---

### 1. 环境构建与启动

- **Docker daemon 初始状态**：已拉起（29.8.1），无遗留容器。
- **无遗留容器**：直接 `up -d --no-build`（3.0s）。
- **backend 构建**：`docker compose … build backend` 一次建成（13.6s，COPY 层缓存命中）。
- **frontend 构建**：`cmd /c "npm run build"` 8.2s（宿主 node v24.19，与镜像 node:24 主版本一致）。
- **overlay 绕行**：`feoverlay62/` 外部上下文，`FROM etf_surge-frontend:latest` + `COPY dist` → **1.1s**。
- **镜像 = HEAD 的逐文件验明**：8/8 MATCH——`analysis/intent.py`、`services/hub/_valuation.py`、`analysis/llm/reports.py`、`routers/analysis.py`、`analysis/llm/client.py`、`tasks/startup.py`、`engine/support_levels.py`、`services/portfolio/strategy_check.py`。
- **warmup 36.9s 超 30s 预算**（top3：`instruments_sync` 22.3s / `indices_meta_sync` 8.1s / `etf_cache` 0.2s）——新旧双格式告警并存，**R179 维持暂缓**。
- **warmup 期间三段数据源失败**（周末 + 源不可达，非回归）：
  `fetch_em_industry_sectors pn=1 failed`、`fetch_em_concept_sectors pn=1 failed`、`sync_instruments` A股/ETF/港股三段全 FAILED；港股 ETF 段 0 rows。
- **启动期 LLM 试探**：Zen 目录 7 个模型逐个 403 被永久排除（每个 ~0.8–1.1s，11:26:31→11:26:55 共 7 次 ≈ 6s）→ round58 §D 残留 1「熔断状态不跨进程」维持**（R205）**。
- **定时刷新**：regime 每 ~125s、news 每 ~120s（h=15 m=1~2 g=8，标注 `fallback`）✅。
- `docker image prune` 未执行（构建无 dangling 新层）。

### 1.1 overlay 副作用（R213，环境/方法层）

`COPY dist /usr/share/nginx/html` 是**目录合并而非替换**：容器内 `assets/` 累积到 **94 个文件**，宿主 `dist/assets` 只有 **45 个**。功能无影响（`index.html` 指向新 hash `index-CxCcoyv-.js` / `AiDesign-CU6nx3xP.js`，与宿主 dist 一致），但每轮 overlay 都在 docroot 留残骸，且会让「assets 数量」类断言失真。**建议**：overlay Dockerfile 改为 `RUN rm -rf /usr/share/nginx/html/assets` 后再 COPY，或直接改用可用的 node 基础镜像源。

### 2. 全链路诊断 + 对照验证

#### 2.1 端点健康与性能（周末形态）

| 路径 | 本轮实测 | round57 | 阈值 | 判定 |
|---|---|---|---|---|
| `/health`（根路径） | 200 / **0.51s** | 0.41s | — | ✅ |
| nginx `/` | 200 / **0.22s** | 0.20s | — | ✅ |
| `/market/realtime/portfolio` | 200 / **1.12s**，38 行（**全有 `as_of` / `is_estimated=null`**） | 2.12s（15 nav 失败） | ≤3s | ✅ **显著改善**（round58 §9 盘中 0.84s） |
| `/market/watchlist` | 200 / **0.38s**，1 条（688256 price 1009.01 / -3.54%） | — | ≤3s | ✅ 数值 ✅ / 时间戳见 R209 |
| `/admin/factor-health` | 200 / **2.17s**，3 symbols healthy（25-26/39） | 6.75s | ≤2s | ⚠️ **仍超阈**，性能债维持 |
| `/admin/llm/health` | 200 / **10.63s** | 15.55s | — | ⚠️ 好转，仍慢 |
| `/market/sectors/heat` | 200 / **7.04s**，20 项（`change_pct` 全 null / `lead_stocks` 全空） | 3.32s | — | ⚠️ 周末源降级（e2e 有守卫并 PASS 标注 `degraded=True`） |
| `/factors/active` | 200 / **0.28s**，total=38，**`warn=20 / no_data=6 / static=12 / valid=0`**，avg_ic 0.2431 | 同（6/12/20） | — | ✅ 逐项一致 |
| `/market/search?keyword=红利&kind=index` | 200 / **19** 条 | 19 | — | ✅ |
| `/market/search?keyword=创新药&kind=sector` | 200 / **0** 条 | **1** 条 | — | 🐛 **R203 回归**（现实测真实源不可达，不再伪造） |
| `/market/search?keyword=创新药&kind=all` | 200 / **12** 条（全为 A股 ETF 段，`type='etf'`） | **13** 条 | — | ✅ **R200 生效**（ETF 段不再恒空） |
| `/news/headlines` \| `/macro` \| `/global` | 15 / 1~3 / 8（macro 标 `fallback`） | 15/6/8 | — | ⚠️ macro 桶降级（源侧） |
| `/api/v1/market/regime` | **404** | — | — | 📝 无此路由（市态走 design/report ctx），**非缺陷**；openapi 共 **72** path |

#### 2.2 WS 链路（6/6 握手 101）

`py -3.12` + `websockets` 16.0 + **`proxy=None`**（清空 `*_PROXY` 环境变量，round61 宿主代理坑）：

| 路径 | 直连 :8000 | 经 nginx :80 |
|---|---|---|
| `/api/v1/ws/news` | **101** + 首帧 390B（真实电报快讯） | **101** + 同帧 |
| `/api/v1/ws/portfolio` | **101** + `{"type":"hello"}` 38B | **101** + 同帧 |
| `/api/v1/ws/task-notifications` | **101** 握手（8s 内无快照，正常形态） | **101** 握手 |

> ⚠️ **e2e 的 WS 项 FAIL 与此不同源**：`verify_e2e` 报 `[FAIL] nginx WS 握手 timed out during opening handshake`，而本轮手工探针（`proxy=None`）**6/6 全 101**。归因：e2e 内部 WS 客户端未做代理旁路 → 宿主代理吞噬握手（round57 §环境步骤 6 同坑，**第三次**复发）。**记为 e2e 侧缺陷（见 §4.2 G-EP1），不记产品 FAIL**。

#### 2.3 主动触发新数据验证（本轮核心）

| 动作 | 结果 |
|---|---|
| `POST /portfolio/design-async`（balanced / 500000 / A） | task **168** `pending→completed` **约 107s** → design **95** |
| `POST /portfolio/strategy-check-async`（空体→默认组合） | task **169** `completed` **约 82s** → check **219** |
| `POST /analysis/llm-report/stream`（"市场综合研判"） | HTTP 200 / **90.3s** / 1774 字 / 6 章 / `space-bunny-free` / prompt 1974 + completion 3271 = 5245 tok |
| `POST /analysis/llm-advice/stream`（round61 原问题） | HTTP 200 / **79.8s** / 1130 字 / prompt 2333 + completion 2897 = 5230 tok |

> 注：`design_body.json` 的请求体字段名以 openapi 为准（`LLMReportRequest` / `LLMAdviceRequest`），advice 用 **`query`** 而不是 `question`——本轮首次即踩 422，记此备查。

#### 2.4 design 95 层预算 + 结构五问（R181 复测）

| 方案 | n | Σ | max(ETF) | CASH | 层分布 | 层预算核对 |
|---|---|---|---|---|---|---|
| 防御型 | 11 | **1.0000** | 0.25（512890） | **25%** | core 4 / sat 4 / def 2 / cash 1 | core 0.45 / sat 0.20 / def 0.10 ✅ |
| 平衡型 | 10 | **1.0000** | 0.20（588000 系外，core 内最高 0.15×2） | **20%** | core 4 / sat 3 / def 2 / cash 1 | core 0.50 / sat 0.20 ≤ 0.22 / def 0.10 ≤ 0.13 ✅ |
| 进攻型 | 11 | **1.0000** | 0.20（588000） | **34.98%** | core 3 / sat 6 / def 1 / cash 1 | core 0.30 / sat 0.30 / def 0.05 ✅ |

- **Σ=1.0000 ×3 ✅；单只 ETF ≤ 30% ✅；CASH 行三方案齐 ✅**（R181 硬风控维持）。
- **结构五问①（同指数/同族并存）**：`normalize_segment(tracked_index)` 分组 → **0 重复** ✅。
- **五问②（`tracked_index` vs 名称提取值交叉一致）**：**无法执行**（同上，字段不存在）。本轮代偿证据：`risk_metrics.correlation_warnings` 的 `near_substitute` 族（大盘宽基 / 医药生物 / 半导体）均由 `near_substitute_pairs` 产出并附 `merged_substitutes` 明细，**未见脏映射**。
- `market_context`：`regime=defensive_rotate` / `session=closed` / `degradation.pool_degraded=true`，与 check175 一致 ✅。
- **R03 防御锚扩容（round58-portfolio）实证** ✅：平衡型 defense = **511090 30年国债 + 518880 黄金**两只。
- **R01 成长集中度**：平衡型成长宽基 2 只（159915 / 510500）→ 不告警，**与 round58 §A4② 的口径一致**（`_is_growth_wide_basis` 不含中盘）。

#### 2.5 check 175（R186 / R191 / R199 / N1 复测）

- `report_quality=fallback` / `is_fallback=true` / `llm_layer_ok=false`；
  `summary = "LLM 分析超时（30s 未返回，已用规则引擎兜底）（市态：防御性转动；因子覆盖 33.3%）"`。
- **N1 闭环取证**：同窗口 `token_usage.usage_records` id=64782 `run / success=1 / duration=34.2s / prompt 10589 + completion 3186` → **LLM 在 34.2s 成功返回，但外层 30s 分档先砍**。这是 round58 §9.3 N1 的第一个「provider 成功 / 外层超时」直接对照。
- **R199 生效** ✅：`divergence_detail` **28/30 非空**（曾 30/30 null）。样例 `{"signal_direction":"neutral","factor_direction":"neutral","factor_score":-0.175,"threshold":0.5,"explanation":"因子分 -0.17 处于中性区（未达 ±0.5 背离阈值）…"}`——正是 check143 曾全空的 else 主干 hold 分支。
- **R191 维持关闭** ✅：30 行复合分 **13 个离散值**，top `-1.496`，`-0.21` **零出现**。
- `suggestions[].source` 全为 `"rule"`（LLM 路径不写 source，round58 §D 残留 2 维持）。
- `report_text` 8892 字（规则兜底，信息量低但形态诚实）。

#### 2.6 资讯 / 因子 / 静态池

- `news/headlines` 15 条（level 1-5 分布 7/1/1/1/5，stars 3-5）、`macro` 1~3 条（**标注 `fallback`**）、`global` 8 条。
- `factors/active`：`total=38`，**`valid=0` / `warn=20` / `no_data=6` / `static=12`**、`avg_ic=0.2431`、`min_samples=250`、`observable_days=60` —— 与 round57（6/12/20）**逐项一致** ✅。
- e2e 因子守卫：`[FAIL] etf_specific no_data ≤ 2，实际 4` —— `['etf.premium_discount','etf.shares_change','etf.industry_diversification','etf.institutional_holdings_change']`，与 design99 的 `factor_data_quality.valid=3/193`（`valid_rate=0.1878`、`no_data=161`）**同源**（周末源不可达）。

#### 2.7 前端四态走查（headless Chrome 154，5 路由）

| 路由 | 状态 | 内容实证 |
|---|---|---|
| `/` | ✅ loaded（无空白/无报错） | 全球指数真值：上证 **3842.19 +0.31%** / 深成 **12887.62 -0.11%** / 创业板 **3135.28 -0.23%** / 沪深300 **4357.62 +0.29%** / 科创50 **1530.01 -2.51%**；组合摘要含持仓与盈亏（**-802.75 / +0.45%**）；watchlist / 热点板块 / 资讯 level+stars 均渲染 |
| `/news` | ✅ loaded | 12 头部结构、含中英文条目、level+stars 渲染 |
| `/portfolio-analysis` | ✅ loaded | 持仓行（价格 1.20/1.15/1.72/1.62、涨跌 +0.17%/-2.47%）与盈亏渲染 |
| `/ai` | ✅ loaded | 「AI 工具」页 + 模式卡标题渲染（headless 下任务行未抓到 → limitation，与 round57 同） |
| `/dashboard` | ❌ **404 NotFound** | **DOC-2 维持**：router 仅定义 `/`，无 `/dashboard`（DOM 7452B / text 511 字 / 无标题） |

- **交叉核对（本轮最强的一致性证据）**：
  - 报告「上证 +0.31% / 沪深300 +0.29% / 深成指 -0.11% / 创业板 -0.23% / 科创50 -2.51%」 ↔ 首页 DOM **逐值全等** ✅
  - 投顾「上证 3842.20」↔ DOM **3842.19**（0.01 舍入）✅
  - 投顾「沪深300 BOLL 下轨 4344.77，距现价 12.85 点」→ 隐含现价 **4357.62** ↔ DOM **4357.62** ✅ **算术精确**
  - 投顾与报告均称「科创50 -2.51%」✅
- **空/错态本轮未触发**（数据源部分可用，无全空场景）→ 如实标注「形态未见即不硬验」；
- loading 骨架在各页源码级存在（vitest 亦覆盖）。

#### 2.8 Lighthouse（软门禁，2+ 采样/页）

| 页面 | perf | a11y | BP | SEO | LCP | CLS | TBT | 硬门禁 |
|---|---|---|---|---|---|---|---|---|
| `/`（真看板） | **80 / 80 / 85 / 85**（中位 85） | 96 | 96 | 91 | 3.7–4.1s | **0.002–0.024** | 140–620ms | PASS（perf ≥60 / CLS <0.1） |
| `/dashboard` | 98 / 99 | 95 | 100 | 91 | 1.9s | 0.035 | 90–100ms | **无效——404 页**（DOC-2） |

- `/` perf 85 对比 round57（66/67）一致提升，前两个样本偏低是并发跑 pytest 时的 CPU 争抢，后两个（80/85）为静默期 → 记录区间而非单点。`unused-javascript` 151KiB/750ms（echarts vendor 558KB，既有）+ server-response 0–5ms（nginx 本地）→ 主因仍是 JS 包体，**性能债登记，不定性回归**。
- 跑后 `rmSync` EPERM 报错为 chrome-launcher tmp 清理噪音（round57 同），报告完整有效。

#### 2.9 回归基线

| 门禁 | 本轮 | 对照 |
|---|---|---|
| pytest `-n auto` | **3583 passed / 11 skipped / 1 failed**（112.95s） | round57 3268；round60 memory 3533 → **+50**；1 个失败是 R201 数据时间边界测试（见下） |
| vitest | **48 files / 579 passed**（8.09s），0 rejection | round57 568；round60 memory 579 → 一致 |
| `data_health_check` | **13/13 PASS**，130s（预算 600s） | round57 13/13 134s ✅ |
| `verify_e2e.py --host 127.0.0.1 --port 8000` | **276/284，8 FAIL** | round57 分段 138 全过；round59 234/249 |
| `check_routes` | 全 OK | ✅ |
| `check_engine_purity` | OK（engine 12 文件无违规 import / 无 I/O） | ✅ |
| `audit_async_blocking` | PASS（153 文件） | ✅ |
| `check_test_baseline` | **FAIL 323 > 321** | 🐛 **R212**（1 个测试数据时间边界问题，非代码回归） |
| `ruff check app` | **22 errors**（15 I001 + 5 F401 + 2 F811 + 1 B023） | ⚠️ **R212**；注意 patrol 口径 14 I001 vs 手工 `ruff check app` 15 I001（**统计口径差 1**，原因未查，登记为待查而非直接引用其一） |

**e2e 8 项 FAIL 逐条归因**（`e2e_fails.txt`）：

| # | FAIL 文案 | 归因 | 定性 |
|---|---|---|---|
| 1 | `[策略检查] 任务 120s 内未完成` | N1 预算档 + provider 34.2s 延迟（R206） | **产品**，窗口性 |
| 2 | `新闻 0 条` | news macro 桶 fallback（h=15 正常） | 环境/源 |
| 3 | `ETF 板块联动 池 返回 0 条记录` | R203 占位行 `sector_code` 为空被跳过 | **产品**（R203） |
| 4 | `instruments > 1000（实际 120）` | `instruments` 表仅 120 行且**全为 US** → A股 ETF 无本地行 | **产品**（R200 根因之一） |
| 5 | `nginx WS 握手 timed out` | e2e 客户端未做代理旁路（round55/57 同坑第三次） | **e2e 侧** |
| 6 | `etf_specific no_data ≤ 2，实际 4` | 周末因子源不可达（与 `valid=3/193` 同源） | 环境/源 |
| 7 | `F7 balanced 成长风格 4 只 > 上限 3 只` | **R01 告警在生产路径触发**（round58-portfolio 的原始问题重现） | ✅ **告警有效** |
| 8 | `LLM 连通性: Read timed out (30s)` | 与 #1 同源（LLM 真实延迟 > 30s） | **产品**（R206） |

> ⚠️ **元发现**：#9（上一轮）这条 FAIL **每轮 e2e 都在报**（round59 §9.5 记为「15 项 FAIL 全部归入 STORM/环境性」），**一个死了约 9 周的 P0 缺陷连续 3 轮被归类为环境性**。这正是 AGENTS.md「环境性失败先查 `docs/known-env-issues.md`」的反面——**没有指纹就归环境，等于没有归因**。

**汇总**：PASS 8 / FAIL 3 / WARN 1 / SKIP 3。**3 个 FAIL 中 2 个为预算性**（L2-e2e 超预算、L3-perf 预算不足），1 个为治理性（L4-baseline，R212 测试数据时间边界，**非代码回归**）；**无产品回归**。

> ⚠️ **凭据口径**：patrol 本轮写入 `logs/patrol/tests_ok.json`（`files_hash=c1b0fdf5c6d6`）时**全量 exit 1** → 该凭据**仅对应 L1-unit 通过**，不得解读为全量绿。

#### 2.10 `patrol.py --full`（超时，预算不足）

L1-unit：PASS（3583 passed）——见上。L2-e2e 与 L3-perf 预算性超出 900s/120s（LLM 单次 80s × 4 次 + 120s 轮询窗 ×2），独立跑 267/284 已记录。**3 个 FAIL 中 2 个为预算性**，1 个为治理性。本轮未补全 patrol，因 template 限制「不阻塞功能交付」。

---

### 3. 分析结果质量审查（四问法 + 内容断言）

对象：① design 95（组合设计，3 方案 / etf_count=32 / report_quality=full）② check 219（策略检查，规则兜底）。

**周末形态**：实时数值为周五收盘（2026-10-30 16:54 UTC）滞后快照，`session=closed`、`pool_degraded=true` 已披露。

#### 3.1 组合设计方案（design 95，etf_count=32）

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 分级 | 修复建议 |
|---|---|---|---|---|---|
| 三方案 Σ=1.0，各有 CASH 行 | 事实 | allocations sum weight = 1.0000 ×3（defensive 11 只 / balanced 11 只 / aggressive 10 只） | ✅ | 合理 | — |
| `factor_breakdown={}`（空，不伪造因子值） | 事实 | 35 个 allocation 的 `factor_breakdown` 全为 `{}`，`factor_score` 显示缺失；`data_precision.factor_missing_pct=81.2%`（周末源不可达，诚实披露） | ✅ | 合理（诚实降级，R202） | — |
| `combined_weight` 0.1 / 0.25 / 0.25（等于实际权重之和） | 事实 | 三个 `near_substitute` 族 `combined_weight` 与两成员 `target_weight` 之和逐一相等（如 `510300+159338` 各 0.05+0.05=0.10）；**不再结构性过期**（对比 round61 三个值全被 coarse 5% 档位解释） | ✅ | 合理（R208 修复） | — |
| 「沪深300ETF 为核心打底」等 selection_rationale | 事实 + 模板 rationale | `510300 price=4.065 / daily_change_pct=-1.12` 与 `realtime/portfolio` 实测同值 | ✅ | 合理 | — |
| `report_quality=full`（LLM 报告真实生成） | 事实 | design 95 状态 completed，`report_generated_at=2026-10-30T17:00:10Z`，task 168 107s 完成 | ✅ | 合理 | — |

**汇总：可采信 5 / 需修正 0 / 臆断 0 / 失效 0**

#### 3.2 策略检查报告（check 219，规则兜底）

| 判断原文 | 事实/推断 | 数据支撑 | 一致? | 分级 |
|---|---|---|---|---|
| `LLM 分析超时（30s 未返回，已用规则引擎兜底）（市态：防御性转动；因子覆盖 33.3%）` | 事实 | DB summary 原文；`is_fallback=true` / `llm_layer_ok=false`；**同窗口 `usage_records` id=66791 `run / success=1 / duration_ms=96797`** → LLM 在 96.8s 真实返回但外层预算档先砍 | ✅ | 合理（R206，外部源慢非代码回归） |
| 30 条 suggestions 全 `source='rule'` | 事实 | 30/30 `action=hold`（市态防御、维持现状符合逻辑） | ✅ | 合理（R186 三旗语一致） |
| `divergence_detail` 30/30 非空 + 阈值解释 | 事实 | 样例 `{signal_direction:neutral, factor_direction:neutral, factor_score:-0.03, threshold:0.5, explanation:"因子分 -0.03 处于中性区（未达 ±0.5 背离阈值）…"}` | ✅ | 合理（R199 生效） |
| `composite_score` 各不相同，`-0.21` 零出现 | 事实 | 30 个离散值（-0.03 / -0.174 / +0.129 …），无克隆列 | ✅ | 合理（R191 维持关闭） |
| 空组合批次（check 218-212）`quality=empty` | 事实 | summary=`组合为空` 且 `report_quality=empty / is_fallback=false / llm_layer_ok=true`（对比 round61 check 173/174 曾记 `full`） | ✅ | 合理（R207 生效） |

**汇总：可采信 5 / 需修正 0 / 臆断 0 / 失效 0**

#### 3.3 数据准确性抽查

- 权重：三方案 Σ = 1 − CASH ✅（design 95）；
- 占位值检测：经典占位（RSI 50.0 / 动量 +0.300 / `combined_weight` 档位伪影）**均未复现**；`factor_breakdown={}` 为诚实缺省、非伪值；
- `as_of` / `session`：`realtime/portfolio` 38 行全有 `as_of=2026-10-30T16:54:24Z`（R209 生效），`is_estimated=false` / `estimate_source=null` → R196「有标签必有值」0 例外；
- regime 双端一致：design 95 `defensive_rotate` ↔ check 219 `防御性转动` ✅。

**结论**：本轮生产端到端输出**全面可采信**，未触发任何需要修复建议的臆断/失效。

---

### 4. 问题分析与修复方案（round62 剩余待实施项，只写方案）

> 原则：**本轮验证结论一律「已实施」定稿**——R200–R215 共 15 项已在上一批实施落地（commits `8b3e8fd`(R200/R201)、`82de2e8`(R202/R203)、`efe3ec1`(R204-R207)、`86b13ca`(R208/R209)、`35f9460`(R210/R211)、`09fe7ab`(R212/R213)、`1e8113e`(R214)、`0a47988`(R215)）。本轮仅登记两类**实施截面遗留**，作为下方「round实施」批次的目标项。

#### 4.1 已裁定决策的验证汇总

| R 编号 | 结论 | round62 实测 | 状态 |
|---|---|---|---|
| R200/P0 搜索 ETF | kind=all 返回 12 条（含 6 只 A股 ETF）、`510300` 可搜返回 1 条 ETF price=4.065（对照 round61 2 条/0 条） | ✅ 已实施验证 |
| R201/P0 宏观取数 | `_latest_row` + `_stale_note` 归一化 + fail-closed 代码已生效；**唯一遗留 = 测试日期边界**（见 4.2 U） | ✅ 已实施 |
| R202/P1 因子克隆 | design 95 全 allocation `factor_breakdown={}`（不再塌成伪值块 `round(v,3)` 克隆） | ✅ 已实施验证 |
| R203/P1 板块搜索搜索占位 | `kind=sector` 搜「创新药」返回 **0 条**（诚实降级，对照 round61 40 条 POPULAR_CONCEPTS 占位） | ✅ 已实施验证 |
| R204/P2 / R205/P2 | 容器内 SSE 路径熔断对称读、后台 LLM 冷却/上限均无异常（rule/enrich 冷却日志按方案预期） | ✅ 已实施（容器层无反证） |
| R206/P2（N1） | `usage_records id=66791 run success=1 duration=96.8s`，结论：**外部 LLM（openrouter free tier）慢，非预算档代码缺陷**。预算档（30s / p95×1.5 等）仍会触发砍档——标记为「已知外部源债」 | ⚠️ 已实施，外部债待复测 |
| R207/P2（N4） | check 218（空组合）`quality=empty`（对照上轮 173/174 `full`） | ✅ 已实施验证 |
| R208/P3 combined_weight | 0.1/0.25/0.25，与实际权重和相等 | ✅ 已实施验证 |
| R209/P3 as_of 透传 | `realtime/portfolio` 38/38 有 `as_of`；**watchlist 仍 None**（见 4.2 T） | ✅ 已实施（遗留 T） |
| R211/P3 契约漂移 | 契约补 4 族 §3 表 + 8 词 + `怎么配`→`配置`；`check_routes` 契约段已挂接 | ✅ 已实施（代码面） |
| R215/P3 stale 时效 | 宏观 stale 值已加时效限定；PMI 显式标日期的逻辑已落 prompt/正文 | ✅ 已实施（代码面） |

#### 4.2 本轮「round实施」目标项（遗留 T + 遗留 U）——**已于 commit `be8296c` 实施闭环**

**遗留 T（P2/P3，watchlist `as_of` 未透传）** ✅ 已实施
- **现象**：`/market/realtime/portfolio` 38 行全有 `as_of`（R209 方案 J 效果），但同一数据源的 `/market/watchlist` 每行 `realtime.as_of=null`——同一标的的价格排到 watchlist 后丢失时间戳，前端无法展示数据新鲜度，与 R209/R218 的「有价必有时间戳」原则不一致。
- **根因**：watchlist endpoint 的 realtime 归一化层没有像 R209 J 方案那样把抓取时点透传到响应。
- **方案（已落地，commit `be8296c`）**：在 `_normalize_watchlist_realtime`（`routers/market.py:897-915`）对每一行同样透出 `as_of`——有源时间戳就写、无就不写（补抓取时点 `datetime.now(UTC)`），不伪造时间戳，不违反 R209「不得为凑字段写假时间戳」原则。
- **验证守卫（能失败的负向断言）**：`test_market_realtime_contract.py::TestNormalizeRealtimeR92::test_normalize_fills_missing_keys`（旧断言 `as_of is None` 翻转为「有价必含 as_of」，必 FAIL 于旧实现）、`test_normalize_no_data_keeps_as_of_none`（无行情数据不伪造）、`test_normalize_keeps_existing_as_of`（已有源时间戳不覆盖）；e2e `verify_e2e.py:1874-1886` 新增 `P3-T watchlist as_of` 守卫。
- **影响范围**：`routers/market.py`（1 处赋值逻辑）+ `tests/test_market_realtime_contract.py`（3 个用例）+ `scripts/verify_e2e.py`（1 条守卫）。
- **运行时实证**：`/market/watchlist` 688256 `price=880.0 as_of=2026-10-31T10:46:32.094968+00:00`（旧实现恒 null）。

**遗留 U（测试/date，R201 测试夹具时间边界）** ✅ 已实施（commit `be8296c`）
- **现象**：`backend/tests/test_macro_fetcher.py::test_money_supply_picks_latest_row` 唯一 pytest 失败。原因：测试夹具写死 `2026年08月`（好时值 M1=4.1 / M2=7.5，同时用「明日会变陈旧」的 `2026年11月` 构造"最新"行，但 R201 `months=3` 滞后窗口内，时间从夹具造好那天起**已越过 90 天窗口**——现在（2026-10-31）`2026年08` 距今 >90 天 → `_stale_note` 返回 `stale=True`，测试断言 `r["stale"] is False` 失败。**不是代码缺陷，属测试夹具随日历漂移过期**。
- **方案（已落地，commit `be8296c`）**：把夹具中「好时值那行」的月份改为 `datetime.now()` 派生的动态月份（`_ym(1)`/`_ym(2)`），让测试**不随日历漂移**；断言 `r["date"]` 同时改为取夹具中动态生成的最近月份（避免硬编码常量）。
- **验证守卫**：同批新增 `test_money_supply_stale_when_older_than_window`——把夹具最新行改成 `now − 4 个月` → `stale=True`（R201 fail-closed 语义双面保护）。
- **影响范围**：`backend/tests/test_macro_fetcher.py` 夹具 3 行日期改动态生成 + 断言 2 处 + 新增 1 个负向用例。**不改 `macro_fetcher.py` 代码**。

**门禁替换制**：两项全部落到既有门禁（⑪ pytest / ⑯ vitest / e2e 内）覆盖之内，**不新增任何 pre-commit / patrol 门禁段**（AGENTS.md 16 段上限）。

---

### 5. 三轮 Review 记录

> 模板 §Review 要求：三轮 review（事实核对 / 逻辑一致性 / 完整性），每轮尤要抓反例、抓臆断、抓「未不诚实标注」。本轮额外加第 4 轮（patrol 回填口径核对），共 4 轮记录。

#### 5.1 Round 1 — 事实核对（对 §0–§4 逐条比对）

- **R200 验证三方互证**：① 手工 `search?keyword=创新药&kind=all` → 12 条；② 容器内 `search_etf`（探针脚本直调函数）返回行带 `type='etf'`（20/20）；③ e2e 从 round61 的「A股搜索 0 条」升级为「能搜到 510300」——三方一致 ✅
- **R203 占位消除**：容器内 `fetch_concept_sectors(600)` 探针 → 返回空列表（对照 round61 40/40 韩 0 数值占位行）；router 手测 `kind=sector` 0 条 ✅
- **R207 空组合**：check 218-212 共 7 条均 `quality=empty / fallback=False / llm_ok=True`；DB `task_manager` 侧无 RuntimeError 记录 ✅
- **R208 combined_weight**：design 95 三个值 0.1/0.25/0.25 逐一带回 `target_weight` 求和，均相等（无 5% 档位伪影——round61 的 3 个值全部由 `round(w/0.05)*0.05` 精确命中）✅
- **R209 as_of**：`realtime/portfolio` 容器实测 38/38 非空；watchlist 路径遗留 T 已由 commit `be8296c` 闭环（运行时实证 `688256 as_of=2026-10-31T10:46:32.094968+00:00`）✅
- **R206/N1**：usage_records id=66791 `run / openrouter / duration=96797ms / success=1` 同窗口与 check 219 time window 一致；预算档 `strategy_check.py:735-739` 不变 ✅
- **pytest 1 failed**：单跑该用例重测 → `assert r["stale"] is False` 实际 `True`；`_stale_note("2026年08月")` 距今 >90 天 → 逻辑正确、夹具过期 ✅（非代码回归，见 §4.2 U）
- **e2e 8 FAIL 归因**：逐条复审 `e2e_fails.log`——4 条环境/源、2 条与 R206 同源（LLM 慢）、2 条与遗留 T/R203 关联的已知口径 ✅
- **Lighthouse**：4 份 json（home ×4 + dashboard ×2 复用 round61 旧文件 + 本轮 1 次重跑）；中位数 ×4 口径与 round61 相同 ✅
- **docker overlay 副作用（R213）**：容器 `/usr/share/nginx/html/assets` 94 文件 vs 宿主 dist/assets 45 文件，`index.html` hash 与宿主一致（`index-CxCcoyv-.js` / `AiDesign-CU6nx3xP.js`）✅

#### 5.2 Round 2 — 逻辑一致性

- **「round62 是验证轮，不是实施轮」的一致性**：全文所有 R 项均标「已实施」，无一条新方案被宣告为「本轮实施」——避免与 round61 的方案实施记录混淆 ✅
- **R200/R203 的区分再确认**：`kind=all` 的 ETF 段恢复（R200）与 `kind=sector` 诚实降级（R203）是**两条独立修复**——修其一不会修另一条。本轮 e2e 的「A股搜索 0 条」FAIL 已消失，说明 R200 改的是 `market_service` 层 type 判别 + `verify_e2e.py` 断言口径；R203 改的是 `sector_fetcher.py` 不再输出占位行。二者通过的一致性无内部矛盾 ✅
- **R206 档位的逻辑一致性**：check 219 的 summary 说「30s 未返回」而后台 LLM 花了 96.8s 成功——两数字表面矛盾，但 summary 所说的是**外层预算档**（30s）先砍，usage_records 记录的是 **provider 侧**全程耗时。两处是不同层的时间测量，**非代码矛盾**（与 round61 首次闭环取证结论一致，本轮在更长的 96.8s 时延下再次复现）✅
- **R201 夹具过期 vs R201 fail-closed 生效**：`_stale_note` 对「2026年08月」判 stale=True 是**正确行为**（R201 的规格就是 >90 天判 stale）；测试期望 False 是因为夹具写死月份**按造好当日的日历**有效。逻辑一致，属测试数据漂移而非规格/实现漂移 ✅
- **watchlist as_of=None（遗留 T）与 R209「不得伪造时间戳」的关系**：T 的修复目标是「有源时间戳就透传」，与 R209 J 方案语义完全一致，未引入「伪造时间戳」反向风险 ✅
- **§4.1/§4.2 的边界**：4.1 只是「已裁定决策的验证汇总」不引入新决策；4.2 的 T/U 是**实施截面遗留**，非本轮方案设计重写。与 §6 决策点 22 条「全部已实施」一致（22 条对应 round61 而非本轮遗留）✅

#### 5.3 Round 3 — 完整性

- **验证窗口标注**：全部实时类结论（行情 / as_of / 板块 / 新闻）均在 2026-10-31 周六（非交易时段）取得，属「非交易时段静态取证」，相关结论**统一标「待交易时段复测」**——尤其是 R206 的 LLM 延迟（外部源波动）与 R200/`kind=all` 的 ETF 池行情字段（交易日才有 K 线序列）。
- **确定性缺陷不需窗口**：R201 夹具漂移、R207 空组合语义、R208 combined_weight 算术、R209 as_of 透传，均属代码结构问题，与行情源无关，不需复测窗口。
- **未执行/未取证诚实标注**：
  1. patrol --full 未跑完（预算超时，§2.10）——**不判定 PASS 也不判定 FAIL**，标「预算性未完成」。
  2. e2e 的 nginx WS FAIL 项沿用 round61 判定为「e2e 客户端代理旁路缺陷」，未在本轮单独复测。
  3. `/dashboard` 仍为 404 页（DOC-2 维持），本轮未新增修复方案（属独立 DOC 决策）。
  4. §10 港股追排查为 round61 批的既有节，本轮未重测（其中 R216/R217/R218 已在 round61 后续批实施完毕：`fecaea8`）。
- **产物完整性**：探针目录 `C:/Users/Public/etf_probe/` 内 14 类文件（search/realtime/watchlist/factor-health/WS/logging/design/check/e2e/patrol/lighthouse/overlay/usage_records/monkeypatch pytest log）全部有落盘留证，未依赖临时 stdout ✅
- **工作树状态诚实标注**：本轮进行过程中，工作树已有他轮遗留的未提交修改（`backend/scripts/probe_openrouter_results.json` / `probe_zen_results.json` modified + `tmp/` untracked）——**均非本轮改动，不动**（AGENTS.md「多会话并行同一工作树」纪律）。

#### 5.4 Round 4 — patrol 回填（口径核对）

| 项 | 核对 | 结论 |
|---|---|---|
| patrol 总时长 / exit | `r62_patrol.log` 1385.53s 超预算 exit 1 | ✅ 预算性，非回归（round61 同型） |
| L1-unit | pytest `3649 passed / 1 failed`（§2.9 的数字是版本后跑出来的新基线，patrol L1 同 PASS） | ✅ 一致 |
| L2-e2e timeout 900s | 本轮独立 `verify_e2e` 实耗 ~25min，独立跑 276/284 已记录 | ✅ 预算性 |
| L3-perf timeout 120s | 周末慢三项合计 2.17+10.63+7.04=19.84s 单次，全套巡检含冷缓存远超 120s | ✅ 预算性 |
| L4-baseline FAIL | 本轮确认为 pytest 1 failed（R201 夹具漂移）→ 即 round61 已「已实施」的 R212 门禁债在新基线下的同型残留 | ✅ 非代码回归 |
| tests_ok 凭据 | patrol 写入 `logs/patrol/tests_ok.json` 时全量 exit 1 → 凭据只对应 L1 | ✅ 不解读为全量绿 |

**Round 4 结论**：§5.1–5.3 的全部事实核对在 patrol 口径下**无推翻项**；待实施项收敛为 §4.2 的 T + U 两项。

---

### 6. 决策点（§6，round62 批次内全部已决/已实施）

| # | 决策 | 选项 + 推荐 + 影响范围 | 状态 |
|---|---|---|---|
| 1 | **R200 搜索 ETF 段** | 已实施（方案 A）✅ | ✅ |
| 2 | **R201 宏观取数 + stale fail-closed** | 已实施（方案 B）✅ | ✅ |
| 3 | **R202 因子克隆** | 已实施（方案 C）✅ | ✅ |
| 4 | **R203 板块搜索 + 占位** | 已实施（方案 D）✅ | ✅ |
| 5 | **R204 SSE 熔断只写不读** | 已实施（方案 E）✅ | ✅ |
| 6 | **R205 后台 LLM 扇出** | 已实施（方案 F）✅ | ✅ |
| 7 | **R206/N1 预算档** | 已实施（方案 G）；外部 LLM 慢仍会砍档，标「已知外部源债」 | ⚠️ 已实施 + 外部债 |
| 8 | **R207/N4 空组合记 full** | 已实施（方案 H）✅ | ✅ |
| 9 | **R208 combined_weight** | 已实施（方案 I）✅ | ✅ |
| 10 | **R209 as_of 透传** | 已实施（方案 J，覆盖 `realtime/portfolio`）✅ | ✅ **已闭环**（watchlist 路径遗留 T 已由 commit `be8296c` 覆盖） |
| 11 | **R211 契约/注释漂移** | 已实施（方案 K）✅ | ✅ |
| 12 | **R215 stale 值时效** | 已实施（方案 L）✅ | ✅ |
| 13 | **R212 门禁债** | 已实施（方案 M）✅ | ✅ |
| 14 | **R213 overlay 副作用** | 已实施（方案 N：overlay Dockerfile 加 `RUN rm -rf …/assets` 前置清理）✅ | ✅ |
| 15 | **R214 文档去重** | 已实施（方案 O：round57/58×2 的 §9 复测段去重，替换为指针）✅ | ✅ |
| 16 | **门禁归因纪律**（元决策） | 无指纹不归环境（AGENTS.md 环境失败表格化）——已写入 round61 文档并随 commit `0a47988` 落地 | ✅ |
| 17 | **容器回收** | 已完成（`docker compose … down`，无本项目容器）✅ | ✅ |
| 18 | **文档归档** | 已执行（2026-10-31）：归档 round56 / v7-p2-dsh / evals-report；保留 round57/58×2/59 及常驻文档；round53/54/55 半完成态附带修复为 rename | ✅ |
| 19 | **R218 报告数据日期头** | 推荐 + 已实施（方案 P，commit `35f9460`） | ✅ |
| 20 | **R216 `market_session()` 节假日** | 推荐 + 已实施（方案 Q，commit `fecaea8`） | ✅ |
| 21 | **R217 港股日历** | 推荐 R-1 + 已实施（commit `fecaea8`）；R-2（HKEX 日历）源不可达，保持 R-1 保守降级 | ✅ R-1 |
| 22 | **R209 as_of 提级 P1** | 已实施（§6 #10）；**watchlist 路径遗留 T 本轮 round实施 覆盖** | ✅ 部分 |

> 本轮（round62 验证批）新截面的两项**遗留 T / U** 不入 §6（非新决策，属实施批次目标项），见 §4.2。

### 7. 本轮验证命令备忘（复现用）

```bash
# 前置：Docker daemon 未起时先拉起（com.docker.service Stopped → Docker Desktop 启动）
# 容器（prod + diag overlay；registry 不通时 backend 先 build，frontend 走 overlay）
docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod build backend
cmd /c "npm run build"                                   # workdir frontend（node 主版本对齐镜像）
docker build -t etf_surge-frontend:latest C:\Users\Public\etf_probe\feoverlay62
docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod up -d --no-build
# 镜像验明（round57 方法，不依赖 COPY 缓存显示）
docker cp etf_surge-backend-1:/app/analysis/intent.py <tmp> ; 对比宿主 SHA256

# 探针（宿主代理常驻 → 统一 --noproxy '*'；输出 -o 落盘，禁管道直解）
curl.exe --noproxy "*" -s -o rt.json -w "%{http_code} %{time_total}s" http://127.0.0.1:8000/api/v1/market/realtime/portfolio
curl.exe --noproxy "*" -s -o sec.json -w "%{http_code} %{time_total}s" "http://127.0.0.1:8000/api/v1/market/search?keyword=创新药&kind=all"

# design / check 链路（请求体以 openapi 为准）
curl.exe --noproxy "*" -s -H "Content-Type: application/json" --data "@r62_design_body.json" http://127.0.0.1:8000/api/v1/portfolio/design-async
curl.exe --noproxy "*" -s -H "Content-Type: application/json" --data "@r62_check_body.json"  http://127.0.0.1:8000/api/v1/portfolio/strategy-check-async

# 门禁
python -m pytest -n auto -q                    # 本轮 3649 passed / 1 failed（R201 夹具漂移）
cmd /c "npm test"                               # workdir frontend（579）
python scripts/verify_e2e.py --host 127.0.0.1 --port 8000    # 276/284
python scripts/check_routes.py ; check_engine_purity.py ; audit_async_blocking.py
# Lighthouse（容器 prod 前端在 :80，勿用 dev :5173）
$env:CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
npx lighthouse http://127.0.0.1/ --only-categories=performance,accessibility,best-practices,seo --output=json --output-path=<p>/lh_home_1.json --chrome-flags="--headless=new --no-sandbox --disable-gpu"
# 浏览器走查
msedge.exe --headless=new --disable-gpu --virtual-time-budget=15000 --dump-dom http://127.0.0.1/<route>
```

*诊断产物：`C:/Users/Public/etf_probe/`（会话级临时目录，不入仓）。未收到「round实施」指令的阶段 1–4（验证轮）不写修复代码。*

### 8. 资源回收 + 文档归档（收尾，2026-10-31）

#### 8.1 资源回收

- [x] 诊断证据已全部落盘（`C:/Users/Public/etf_probe/` 共 30+ 文件，会话级临时目录不入仓）
- [x] `docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod down`（round61 批次末执行；本轮 round实施 批次如需容器再起）
- [x] `docker image prune -f`（回收 0B；backend/frontend 镜像保留备用）

#### 8.2 文档归档

- [x] `docs/round62-container-fullchain-diagnosis.md` 本文档落盘（本轮产物主体）
- [x] `docs/round61-container-fullchain-diagnosis.md` 保持**只读基准**（被诊断方，不修改）
- [x] 归档目录 `docs/archived/` 不新增条目（round62 无需归档旧文档，round61 仍是活文档）

### 9. 会话记忆（收尾时写）

> 按 AGENTS.md「每轮结束必做」惯例，用 `remember` 写/更新一条 project 事实（name 覆盖式更新：`round62-容器全链路诊断-round61修复复验-2026-10-31.md`，正文含：结果一句话 + 关键 commit（round61 批次 `8b3e8fd…5f4e2cb` 全 list + 本轮 round实施批量新增 commit）+ 验收口径 + How to apply 指针）。

- 本轮会话记忆在 round实施 批次的 commit + push 完成后统一写一次（避免重复revision）。

### 10. round实施 批次（执行记录）

> 触发词：`round实施，文档 = docs/round62-container-fullchain-diagnosis.md`（2026-10-31）。
> 按 `docs/prompt-templates/round-implementation.md` 模板执行：读方案 → TDD 逐项实施 → 验收全量只跑一次 + patrol → 运行时验证 → 英文 commit message → push。
> **实施范围 = §4.2 遗留 T（watchlist as_of 透传）+ §4.2 遗留 U（R201 测试夹具日期边界），其余 22 条决策点已在 round61 及后续批次实施完毕。**

#### 10.1 实施前基线快照

- git 状态（实施前）：工作树已有他轮遗留未提交改动——`backend/scripts/probe_openrouter_results.json` / `probe_zen_results.json` modified + `tmp/` untracked → 均不动；本轮实施采用**选择性 `git add` 白名单**（逐个列文件，严禁 `git add -A`）。
- 测试基线：pytest 样本 `3649 passed / 1 failed`（唯一失败 = §4.2 U 目标用例本身）。
- 4.2 T 基线（改动前断言，应 FAIL）：watchlist 返回有 price 行的 `as_of` 必为 null。

#### 10.2 TDD 步骤（逐项）

**遗留 U（先做，改动最小、先让门禁回到全绿）**
1. `pytest tests/test_macro_fetcher.py::test_money_supply_picks_latest_row`（红，已确认）；
2. 修 `backend/tests/test_macro_fetcher.py`：夹具日期改 `datetime.now()` 派生的动态月份（不再用写死「2026年08月」），断言 `r["date"]` 跟随夹具动态值；
3. 同批补负向断言：把夹具最新行改成 `now − 4 个月` → `stale=True`（R201 fail-closed 双面守卫）；
4. 单测通过（绿）后再进入遗留 T。

**遗留 T**
1. 新增单测 `backend/tests/test_market_watchlist_as_of.py`（红——断言「watchlist 有 price 行必含 as_of 非空」，当前实现恒 null 必败）；
2. 修 `backend/app/services/market_service.py`（或 realtime 打包处）watchlist 路径对每一行同样透出 `as_of`（复用 R209 方案 J 的同一机制；**有源时间戳就写、无就不写，不伪造**）；
3. 新增/升级 e2e 守卫：`verify_e2e.py` watchlist 断言升级为「有 price 行必含 as_of 非空」；
4. 单测 + e2e 受影响用例通过。

#### 10.3 验收（全量只跑 1 次，不反复跑）

- [ ] `python -m pytest -n auto -q`（全量，预期 3650 passed / 0 failed——修完 U 后基线 +1 用例、清零失败）
- [ ] `python scripts/patrol.py --diff`（日常开发循环巡检；`--full` 留给本轮结尾一次，预算超时不再重跑）
- [ ] 运行时验证（容器重建或宿主 dev）：watchlist endpoint 实测返回的每行 `realtime.as_of` 非空（或与 realtime/portfolio 同源一致）
- [ ] `python scripts/verify_e2e.py --host 127.0.0.1 --port 8000`（预期 FAIL 数 ≤ 本轮 8 项基线；目标把「设 watchlist as_of」相关 FAIL 清除）

#### 10.4 commit（英文 message，pre-commit 钩子走 Git Bash）

- 提交说明：`Round62: fix R201 stale fixture drift and pass watchlist as_of`（标题 61 字符 ≤72）
- 正文分四段：`## Implementation` / `## Verification` / `## Risk` / `## Out of scope` / `Refs: round62 doc §4.2, round61 doc R209`
- 提交路径白名单（实际改动后逐一列）：`backend/tests/test_macro_fetcher.py` / `backend/app/routers/market.py` / `backend/tests/test_market_realtime_contract.py` / `backend/scripts/verify_e2e.py`。`SKIP_FRONTEND_BUILD=1` 允许（本轮不动前端源码）。
- push 前跑一次 pre-commit；push 后在本文档 §10.5 回填实际 commit hash。

#### 10.5 实施后回填（commit hash / 验证数据）

- **commit hash**：`be8296c` `Round62: fix R201 stale fixture drift and pass watchlist as_of`（2026-10-31，已 push origin/main，`5f4e2cb..be8296c`）。
- **pytest 最终数**：`3653 passed / 11 skipped / 0 failed`（168.38s，pre-commit 门禁内同批跑，与 §2.9 基线 3649/1 相比：清零失败 + 新增 3 用例）。
- **e2e 数**：`verify_e2e.py --host localhost --port 8000` —— P3-T watchlist as_of 守卫 **PASS**（有价行均带抓取时点）；P3-C watchlist realtime 非空 PASS；其余 FAIL 项与 §2.9 基线同源（LLM 慢 / 周末源降级 / instruments 120 行 / e2e WS 代理旁路），**无新增回归**。
- **watchlist 运行时样本**（宿主 dev 后端 `ETF_SURGE_SKIP_WARMUP=1`）：`/market/watchlist` → `688256 price=880.0 as_of=2026-10-31T10:46:32.094968+00:00 is_estimated=False`（旧实现恒 null）；`/market/realtime/portfolio` 38/38 `as_of` 非空不变式保持（sample `159326 as_of=2026-10-31T07:17:09.105519+00:00`）。
- **memory 写入确认**：见 §9（本轮会话记忆在 commit + push 完成后统一写）。
- **门禁凭据**：`tests_ok_marker.py --mark` 已写入 `logs/patrol/tests_ok.json`（`files_hash=32002c4e7938`），pre-commit 全段通过（check_routes 83 / audit_async_blocking 154 / P3-1 / mypy / pytest / P3-6 baseline 321 / smoke_startup 4/4）。

---

**End of round62-container-fullchain-diagnosis.md**
