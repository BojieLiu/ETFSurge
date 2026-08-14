# round23 系统审计与优化修复方案（2026-08-14）

> 本文档为「Docker 构建启动 + 全链路验证 + 性能诊断 + 测试防护审计 + 冗余代码梳理」的综合结论与修复设计。
> 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」要求撰写。**本文档仅设计修复方案，不实施。**
> 验证环境：Docker Desktop 4.86 / Engine 29.7.2，prod profile + `docker-compose.diag.yml`（注入 `PROFILE_WARMUP=1`）构建启动，后端 :8000 / 前端 :80。

---

## 0. 执行摘要

### 0.1 验证动作与基线
| 动作 | 结果 |
|---|---|
| Docker 构建最新前后端镜像 | ✅ `etf_surge-backend:89b26d0bd17b` / `etf_surge-frontend:37b13c832ad9` |
| 启动 + 预热性能诊断 | ⚠️ 预热 ~19s，数据源经容器代理可达（warmup `all_done=true`） |
| `verify_e2e.py` 两次运行 | 269/280、271/282 通过；两次各 **11 项失败**（数据/LLM 相关） |
| 组合设计（design-async, id=554, balanced） | ⚠️ `report_quality=partial`；因子 valid_rate 8.24%；强板块未进候选池 |
| 场内策略检查（strategy-check-async, on_exchange, task=462） | ❌ **LLM 层 19s 超时→100% 规则引擎兜底**；KDJ 超买误判 BUY；confidence 硬编码 0.7 |
| A/HK/US 行情分析 / 热点 / 自选 / 持仓 / 资讯 / 因子 | 见 §2.3–§2.5（subagent 报告） |
| 前端 Lighthouse | 子路由 98–99，但 **根路由 perf=67**（首屏 JS 阻塞） |
| 后端链路计时 | 多数 <200ms；`timeline` 1.2–1.5s（超 1.0s 门禁）、`etfs(on_exchange)` ~2.9s（逼近 3s 阈值） |
| 3 份文档落地核验 | redesign/round22 已落地（5/5）；round21 为诊断文档，P1-3/KDJ/confidence/因子率/美股热点 仍未修 |
| 冗余代码 | 见 §6（subagent 报告） |

### 0.2 问题分级（设计阶段结论，全部经 lead 独立复核）
- **P0-A 投资判断被系统性误导（危害最高：错的方向比没有数据更危险）**
  1. **资讯 `level` 是分类非重要性**，前端 `>=4` 当重要 → **利空(3) 永不推送、利好(4) 必推**；且 `冲突/军事/制裁/战/核` 在 L4「利好」词表 → 战争标红为利好（§2.4 A1，F22/F23）。
  2. **KDJ 超买（J>80）被映射为 BUY/increase**，5 例超买误判 2 例（159516 J=98.7 + RSI=39.9 → 最强买入）（§2.2/§2.3d，F10，round21 P1-3 未修）。
  3. **新闻时间戳慢 8 小时**（UTC 直显），且与 `news/stock/*` 北京时间**两套时区并存** → 无法判断隔夜/盘中（§2.4 A3，F24）。
- **P0-B 用错误统计包装弱因子（"测试绿+数字漂亮+结论错"）**
  4. **`sample_count` 虚高 ~240×**（4306 行 / 仅 18 天），`MIN_IC_SAMPLES=30` 开机 1h 即被全部跨过 → "有效 16" 无统计含义；`|IC|=0.27` 实为 1.7σ 却配 n=4306 展示（§2.5 B1，F25）。
  5. **「平均 \|IC\|」实为带符号均值**，0.0449 vs 真实 0.2368（**5.3×**），同屏两个"平均|IC|"相差 5 倍（§2.5 B2，F26）。
  6. **因子数据完整性塌陷**：design valid_rate 8.24%、有效16/宣称193=8.3%，却输出精确权重（§3.1/§2.5 B3，F12/F33）；且"有效16"本身系 IC 口径造假所致（§2.5 B1/F25）。
- **P0-C 已死路径（改一半 / 迁移遗留，能力永久失效）**
  7. `zero_ratio` 取错对象 → 恒 `{}`，"区分数据缺失 vs IC 无效"从未生效（§3.2b C1，F27）。
  8. AI 摘要 `str(level) in ("重大","利好")` 恒 False（level 已 int）→ 重要性维度失效（§3.2b C4，F28）。
  9. 场内策略检查 LLM 超时→100% 规则兜底且**以 `completed` 静默冒充**（§2.2/§4，T3 升 P0）。
- **P1**
  10. LLM provider：zen 永久 429（`FreeUsageLimitError` 额度耗尽）→ **决策改为 zen 主 + deepseek 备 + 模块级 TTL 熔断**（§4.1，F7/F8/F9/F9b）；F8 升回 P0。
  11. 资讯页只调 headlines，`macro/global/stock/research` 4 端点 UI 不可达且各自有缺陷（§2.4 A4，F29）。
  12. 候选池熔断→设计 0 方案 + 强板块未进池（§3.2，F13）。
  13. 前端根路由首屏 67（§1.3，F4/F5）；`timeline` 超 1.0s、`etfs` 逼近 3s、**`factor-health` 冷态 3.27s、`news-impact` 17.8–19.9s**（§1.2）。
  14. 测试防护：软放行 + 统计口径无自校验 + **缓存掩盖冷启动** + harness 编码无护栏（§5，T1–T11）。
- **P2（治理/清理）**
  15. 冗余/死代码（§6，含 `analyze_news` 未接线、`LLM_FALLBACK_PROVIDER` 死配置）、孤立 avg_cost 20 条（§3.3）、`up_ratio` 命名歧义（§2.3，F20）、港美自选无实时（F21）。
- **架构分层与冗余整改（§10，独立于上述正确性与性能项）**：engine 纯度泄漏 / `source_registry` 反向依赖 / god-object / 透传冗余 / 死代码，5 类问题 + 7 项整改（A1/A2/B1/C1/D1/E1/E2），经 Round 1–3 评审已达实施标准（不实施）。
- **round20 合并归档（§11）**：round20（纯诊断）20 项问题已在后续代码提交中 13 项落地、6 项由本档 F/章节跟踪（仅 F35 home CLS 为净新增开放项）；已归档至 `docs/archived/round20-container-acceptance-diagnosis.md`。

> **本轮方法论警示（两次实证）**：① gp-2 v1 用 shell-curl 传中文产生 **4 个假 P0**（三端点"崩溃"+全站"乱码"），复测全部推翻；② 我自己用热缓存测 `factor-health` 得 168ms 判 ✅，实际冷态 3.27s。**结论：任何"审计结论"必须标注测量方式与缓存状态，否则既会虚报也会漏报**（T8/T9）。

---

## 1. 性能

### 1.1 后端预热性能诊断（`PROFILE_WARMUP=1`）
产物：`logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.html/txt`。

**实测（`warmup_timing.json`）**：
| 阶段 | 耗时 | 占比 |
|---|---|---|
| init_db | 46.5ms | 0.2% |
| redis_init | 79.3ms | 0.4% |
| warmup_global_indices | 4977ms | 26% |
| **warmup_market_cache** | **13855ms** | **73%** |
| warmup_etf_cache | 12ms | 0.1% |
| 合计 | ~18.97s | — |

**cProfile/pyinstrument 根因**：
- 预热**纯 I/O bound**（CPU 仅 2.66s / 14.1s）。主导：`china_market.py:fetch_fund_nav` / `_fetch_ttj_lsjz` / akshare `fund_open_fund_info_em` 共约 10 次 NAV 历史拉取，每次 ~1.5–2.2s；realtime 拉取 ~5.7s。线程时间累计 ~22s（线程池并发）。
- **`requests.get` 而非 `requests.Session`**：SSL 握手累计 ~5.5s（`ssl.py:do_handshake`），每次请求新建连接，无连接复用。
- **`main.py:201` `asyncio.wait_for(refresh_market_cache(), timeout=10)` 实际未生效**：计时记录 13.8s > 10s，说明该超时未真正约束预热调用（疑似内部自起后台任务或超时未穿透）。属诊断发现，需复核。

**修复设计（不实施）**：
- F1：数据层改 `requests.Session`（含 `HTTPAdapter(pool_connections/pool_maxsize)` + 重试），消除重复 SSL 握手，预计削减 30–50% 握手耗时。
- F2：`warmup_market_cache` 内 NAV 拉取改为并发（`asyncio.gather` + 限并发信号量），并确认 `timeout=10` 真正穿透（或在 `refresh_market_cache` 内部加 `wait_for`）。
- F3：预热阶段降低精度要求（如 NAV 历史仅取近 60 日），缩短单请求耗时。
- 验收：`warmup_market_cache` ≤ 8s，总预热 ≤ 15s；SSL 握手累计 ≤ 1.5s。

### 1.2 后端链路性能
`curl -w time_total`（预热后热态，单发）：
| 端点 | 状态 | 耗时 | 阈值 | 判定 |
|---|---|---|---|---|
| /health | 200 | 4ms | — | ✅ |
| /market/search?market=A | 200 | 26ms | ≤1s | ✅ |
| /market/indices/global | 200 | 4ms | — | ✅ |
| /market/sectors/heat | 200 | 4ms | — | ✅ |
| /market/hot-plates | 200 | 4ms | — | ✅ |
| /market/realtime/portfolio | 200 | 445ms | — | ✅ |
| /portfolio/etfs?on_exchange | 200 | **2.92s** | ≤3s | ⚠️ 逼近 |
| /portfolio/designs | 200 | 1.24s | — | ✅ |
| /portfolio/timeline | 200 | **1.49s** | ≤1.0s | ❌ 超门禁 |
| /factors/active | 200 | 153ms | — | ✅ |
| /news/headlines | 200 | 4ms | — | ✅ |
| /market/sentiment | 200 | 173ms | — | ✅ |
| /admin/factor-health | 200 | 168ms（热）/ **3.27s（冷）** | ≤2s | ❌ 冷态超门禁 |
| /market/stock-hot-rank | 200 | 193ms | — | ✅ |
| /analysis/news-impact | 200 | **17.8–19.9s** | — | ❌ 同步阻塞（§2.4） |

> **缓存掩盖效应（重要方法论）**：`factor-health` 我首测 168ms 判 ✅，gp3 独立测得 **11.17s**——差 66×。复测确认：**首呼 3.27s，二呼 0.0s**（ETag/TTL 命中）。即**同一端点的"性能结论"完全取决于测量时缓存是否已热**，而现有 `verify_e2e` 计时**默认测到的是热态** → **系统性低估冷启动/首用户体验**。这解释了为何"性能门禁全绿"而用户仍感慢。修复见 T9。

**结论**：热态下除 `timeline`（>1.0s 门禁，即 verify_e2e 失败项之一）与 `etfs`（2.9s，逼近 3s）外均优；但**冷态**下 `factor-health` 3.27s（gp3 环境 11.17s）、`news-impact` 17.8–19.9s 均明显超标。二者均为"持仓/组合 + 实时价 + NAV"聚合路径，瓶颈同源（§1.1 的 NAV 串行拉取 + DB/聚合）。
- 修复设计：对 `timeline` 强化 30s TTL 缓存（已部分存在 `_TIMELINE_CACHE`，但实测仍 1.2–1.5s，需查缓存键命中/序列化成本）；`etfs` 实时价改批量 `get_realtime_batch` + NAV 并发（复用 F2）。
- 验收：`timeline` ≤ 0.8s、`etfs` ≤ 2.0s（热态）。

### 1.3 前端性能（Lighthouse 13.4.1 / Chrome headless）
| 路由 | perf | a11y | best | seo |
|---|---|---|---|---|
| /dashboard | 99 | 100 | 100 | 91 |
| /factors | 99 | 100 | 100 | 91 |
| /market | 99 | 100 | 100 | 91 |
| /news | 99 | 94 | 100 | 91 |
| /portfolio | 98 | 100 | 100 | 91 |
| /analysis | 99 | 100 | 100 | 91 |
| **/** | **67** | 96 | 96 | 91 |

**根因（仅 `/` 首屏 67）**：FCP 2.0s、LCP 3.1s、Speed Index **8.9s**、TBT 660ms、Interactive 4.4s。Lighthouse 机会项：
- **Render-blocking requests**：首屏主 JS 阻塞渲染（无 `async`/`defer` 或路由级懒加载）。
- **Reduce unused JavaScript：可省 450KB**。
- Missing source maps for large first-party JS；contrast ratio（a11y 在 news 降为 94）；robots.txt 无效；阻止 b/f 缓存。
- 子路由 98–99 是因为 SPA 壳已缓存、客户端导航即时——**根因只在首屏**。

**修复设计（不实施）**：
- F4：路由级 `defineAsyncComponent` / `import()` 懒加载，首屏仅加载壳 + 当前路由 chunk。
- F5：Vite `build.rollupOptions.output.manualChunks` 拆 vendor；`index.html` 脚本 `module` + 预连接（`rel=preconnect`）API 域。
- F6：补 source map（仅 dev/内部构建）；修对比度；修 robots.txt。
- 验收：`/` perf ≥ 90，Speed Index ≤ 3s，unused JS ≤ 100KB。

---

## 2. 报告质量与正确性（专业投资者视角）

### 2.1 组合设计 554（balanced / range_bound / report_quality=partial）
- 结构工程良好：3 套方案（防御/平衡/进攻），含层预算、相关度告警（balanced 中 510300/159338 相关 0.983 已削减低分标的）、结构告警（aggressive inv3 卫星数非单调）。**round22 引擎约束（E1–E5）已落地**（§7）。
- **数据可信度硬伤**：
  - `factor_data_quality.valid_rate = 0.0824`（157/193 无数据），报告自注"因子数据完整性降级…方案仅供参考"——但 UI/权重仍呈现为精确决策，**诚实降级与精确呈现相互矛盾**。
  - `strong_sector_pool_coverage = []`：**当前强势板块（sector_momentum 显示高带宽内存 +1.98%、重组蛋白 +1.75% 等）未纳入候选池**——直接违背用户"当前强势板块是否加入候选池"的验收点。
  - `fund_flow` 全 0（`total_symbols:0`）——资金流数据源熔断未显式标注。
  - 设计因子分（如 159338 = -0.40）与策略检查因子分（159338 = 1.27）**对同一标的给出相反量级**——两套因子计算路径（稀疏矩阵 vs 逐标的 32/39）不一致，专业投资者无法据此对齐认知。
- 专业判断：**框架可用、数据基础过薄不能支撑精确配置**。建议：valid_rate < 阈值时强制弱化权重精度、前端显著提示"仅供参考"、强板块必须进入候选池（否则方案与市场脱节）。

### 2.2 场内策略检查 462（on_exchange）—— 任务失败诊断
- **任务失败表现**：`summary` = "LLM 分析超时（19s 未返回，已用规则引擎兜底）（最后错误: ReadTimeout）"；`coverage = {covered_by_llm:0, covered_by_rule:10}`——**AI 报告 100% 规则兜底，零定性研判**。
- **根因（结合后端性能诊断 §4）**：`provider.py` 默认 `LLM_PRIMARY_PROVIDER=opencode_zen` 永久返回 **429**；每次 LLM 调用先试它（含 F3-6 重试 + 指数退避），烧光 `_llm_timeout_for` 的 15/30/75s 预算后才落到 DeepSeek → ReadTimeout。属 provider 配置/熔断缺陷，非模型能力问题。
- **报告内容硬伤（即使规则兜底也应正确）**：
  - ❌ **KDJ 超买误判 BUY**：`159338` KDJ.J=85.66（标注超买区）→ `tech_signal=BUY` → `action=increase`；`159516` KDJ.J=98.68（超买）→ BUY/increase。超买应谨慎/卖出，矛盾。此即文档核验中 **P1-3（KDJ 超买→BUY）历史项仍未修复**的实锤。
  - ❌ **confidence 硬编码 0.7**：10 条建议全部 `confidence:0.7`（D9/P1-8 未修），置信度字段失真。
  - 因子摘要与信号存在不一致（如 `512000` 因子分 0.48 中性但 `tech_signal=SELL`、最终却 `hold`，逻辑自洽性弱）。
- 专业判断：**不可作为可执行的投顾建议**。超买=买入是严重分析错误；且无任何宏观/定性判断。修复见 §4 + §2.2 修复项。

### 2.3 A/HK/US 行情分析、综合研判、AI 投顾、个股/ETF/板块/概念/指数分析、搜索自动补全

**实证来源**：`backend/scripts/_findings_market.md`（**v2，含反查更正**）+ 原始响应 `backend/scripts/_evidence/*.json|txt`（盘后窗口 `market_status=closed`）。

> ⚠️ **方法论更正（重要）**：subagent v1 用 Git Bash 下 `curl -d '{"query":"中文"}'`，Windows/Git-Bash 会破坏 UTF-8，制造了 3 个"CRITICAL/BROKEN 流式端点" + "mojibake" 的**误报**。本轮用容器内 `urllib` 显式 `.encode('utf-8')` 重新验证，**后端正产**，下列 v1 中的 F16–F19 为误报，已从缺陷表移除。教训：中文体端点必须用 Python urllib（显式 UTF-8）验证，shell 引号 curl 不可信（§9 测试缺口补充 T8）。

| 能力 | 实测 | 结论 |
|---|---|---|
| 搜索自动补全 | `search?keyword=银&market=A` → 10 只真实 A 股；`market=HK` → 恒生中国企业 86.0/-0.83% | ✅ 真实即时补全（A+HK） |
| 综合研判数据源 | sentiment / wind（催化：玻纤/CPO/CRO）/ sectors/rotation（电子化学品 +3.09% 含资金流）/ indices/global（价格+涨跌幅） | ✅ 真实非兜底 |
| `POST /analysis/llm-report/stream` | 56KB 真实中文《市场环境研判报告》流式返回 | ✅ 真实 |
| `POST /analysis/llm-advice/stream`（**中文体，UTF-8 复测**） | HTTP 200，26KB 中文分析流式返回（`query:"当前市场怎么看？"` 正常无 422） | ✅ **v2 更正：中文提问可用，v1 的 422 是 curl 编码误报** |
| `POST /analysis/symbol-analysis/stream`（`{"symbol":"600519"}`） | HTTP 200，56KB | ✅ **v2 更正：v1 的 date 序列化报错是误报** |
| `POST /analysis/sector-analysis/stream`（`{"sector_code":"BK0735"}`） | HTTP 200，81KB | ✅ **v2 更正：v1 的 0 字节空 body 是误报** |
| ETF 分析 `GET /market/realtime/510880` | price 3.267 / -0.18% 真实 | ✅ |

**仅余真实缺陷**：
- ⚠️ **`up_ratio` 字段语义歧义（非数据矛盾，v2 更正）**：`/market/sentiment.up_ratio="65.00%"`，同时 `up_ratio_num="37"`、`up_open_num="20"`、`up_down_dis:{rise 1444 / fall 3977}`。计算 `37/(37+20)=64.9%`——这是**涨停封板率**（limit-up seal rate），并非"上涨占比"（真实约 26%）。**字段本身正确、来源直传东财**，问题在**命名与展示**：投资者易把"up_ratio 65%"误读为"65% 股票上涨"。属透明度/命名问题，非计算错误（F20 降为 P2 命名修正，详见 §8）。
- 三条流式端点**真实可用**，但 §4 的 zen 429 仍会导致它们**慢/偶发兜底**（属 provider 问题而非端点 bug）。

### 2.3b 热门板块 / 热门个股（步骤4）
- `sectors/heat`、`hot-plates`、`stock-hot-rank`：**数值真实**（rank/heat_index/change_pct/lead_stocks 的 last_px 与 change 均为真实行情）。
- ✅ **v2 更正：文本字段编码正常**。容器内 `urllib` 复测 `hot-plates.name = ['医药','光通信','军工','液冷IDC','芯片产业链']`，**无 mojibake / 无 surrogate**。v1 的"乱码"是 shell curl 破坏响应字节所致，误报，F19 移除。

### 2.3c 自选股（步骤5）
- ✅ `POST /market/watchlist {"symbol":"600519"}` → 409「该标的已在自选列表中」（幂等防重，正确）；`GET /market/watchlist` 20 条，600519 贵州茅台带实时 1350.03 / -0.39%。
- ⚠️ **实时覆盖 12/20**：8 条港美标的（09988.HK、QQQ 等）**静默缺 price/change_pct**，前端无任何降级说明 → 用户误以为"没波动"。

### 2.3d 持仓技术分析与综合信号（步骤6）
原始指标真实且自洽（240 日历史，RSI/KDJ/MACD 与价格一致）。全量扫描 10 只场内 ETF：

| symbol | KDJ.J | signal | score | 判定 |
|---|---|---|---|---|
| 159338 | **85.7** | **buy** | 1.5 | ❌ 超买→买入 |
| 159516 | **98.7** | **buy** | 2.5 | ❌ 极端超买 + RSI 39.9 偏弱，却给最强买入 |
| 159992 | 92.8 | hold | 1.0 | ✅ |
| 513120 | 93.1 | hold | 1.0 | ✅ |
| 518880 | 97.3 | hold | 1.0 | ✅（但 score 1.0 偏买、标签 hold，标签与分值不同源） |

- ❌ **确认 KDJ 超买→BUY 缺陷（5 例超买中 2 例误判）**，且**不是统一坏**而是**逻辑不一致**——说明超买约束根本不在信号主路径上，命中与否取决于其它因子偶然抵消。159516（J=98.7 + RSI=39.9 → 最强 BUY）是最恶劣反例。
- 结论：与 §2.2 的策略检查报告是**同一根因**（`portfolio_service.py` 信号合成未把 KDJ 超买作为反向/谨慎约束），F10 需同时覆盖 `tech_signal` 生成与 `_rule_based_suggestion` 两处。

### 2.4 资讯分级与 AI 智能分析（步骤7）

**实证来源**：`backend/scripts/_findings_news_factor.md` + `backend/scripts/_evidence_gp3/*.json`。以下 P0 项**已由 lead 独立复核确认**（读源码 + 容器内实测），非单方报告。

#### ❌ A1 [P0] `level` 是「分类」而非「重要性」，前端当重要性用 → **利空被系统性降权**
- 后端定义（`levistock_fetcher.py` docstring 实读）：`5=重大/紧急, 4=利好, 3=利空, 2=提醒/关注, 1=其他`——**这是类别编号，不是单调的重要性刻度**（4 利好 > 3 利空 只是分类序号，不代表利好比利空更重要）。
- 前端（`frontend/src/utils/newsLevel.js:6-11` 实读）：`lvl>=4 → {color:'red', label:'重要'}`；`isImportant(level) = level>=4`，且注释明写"important items 实时推送 + 进页 toast"。
- **后果（投资危害）**：**任何利空（3）永远进不了重要推送，任何利好（4）必推**；用户若用"重要性 ≥4"筛选，会把**全部利空隐藏**——牛市噪音全留、风险预警全丢。这是比"数据缺失"更危险的**方向性偏置**。
- **叠加缺陷**：L4「利好/重要正面」词表（`levistock_fetcher.py:42-45` 实读）把 `冲突/军事/干预/制裁/战/核` 与 `降准/降息/利好/超预期` **并列同级**。本项目 UI 红=涨（AGENTS.md §conventions），于是**战争/制裁被标红为"重要利好"**，语义完全相反。且 `"战"` 是子串匹配 → 误命中 `挑战/战略/战术`。
- 实测误标样本：`菲律宾央行行长称二季度增长令人失望` → level 4（仅因命中"央行"）；`创业板新能源ETF（159076）多头格局稳固`（**基金硬广**）→ level 4 标红；反之 `股票策略私募7月平均收益-9.50%`、`广达：AI服务器订单可见度至2028年` → level 1 灰。

#### ❌ A3 [P0] 新闻时间戳慢 8 小时（UTC 直显给用户）
容器内实测（lead 亲验）：
```
time = "2026-08-14 03:14:31"   sort_time = 1786677271
UTC(sort_time) = 2026-08-14 03:14:31   ← 与 time 完全相等
北京时间应为    = 2026-08-14 11:14:31
容器: TZ=（未设）  date → Fri Aug 14 03:19:26 UTC 2026
```
- 根因：容器 `TZ` 未设 → 进程 UTC；`time` 字段按本地时区格式化后**原样下发**，前端 `NewsView.vue:61` 直接渲染。
- **同产品两套时区**：`news/stock/*` 的 time 来自东财、已是北京时间 → 用户在同一页看到相差 8h 的两类时间戳。
- 危害：盘中快讯显示"02:17"，投资人**无法判断隔夜/盘前/盘中**，直接影响交易时点判断。

#### ⚠️ A4/C6 [P1] 资讯页信息量仅 1/5，且 4 个端点自身也坏
- `frontend/src/api/index.js:88-91` **只调 `/news/headlines`** → `macro` / `global` / `stock` / `research` 四个端点 **UI 完全不可达**（后端有、前端不接 = 事实死功能）。
- 且这 4 个本身有缺陷：`macro` 3 条**全与 headlines 重复**且**无一条中国宏观**（无 CPI/PMI/社融）；`global` 8 条 `source` 全为 `"RSS"`、`id` 全缺、`ai_summary` 全 None；`stock/510300` 最新为 **2026-07-28（17 天前）**；`research/{510300,512880,159915}` **全部空数组**。
- 冷启动时 headlines 与 macro **各只返回 1 条且是同一条**（缓存刷新窗口内返残缺数据，**无"不完整"标识**）——属"半成品静默上屏"。

#### ❌ C4 [P0-断裂] AI 摘要的 level 分支恒不命中（迁移遗留）
`market_data_hub.py:1705` 实读：`str(n.get("level","")) in ("重大","利好")`——但 `level` 早已是 **int**，此条件**永远为 False**。于是"重要新闻优先生成 AI 摘要"退化为**只看 `stars>=4`（新鲜度）**，重要性维度完全失效。

#### ✅ 唯一亮点：`news-impact` AI 分析质量合格（非兜底、非填充）
- 正向：韩国 ICT 出口 +140.6% → `方向:利好 / 板块:A股电子`，`affected_holdings=[510300]`，资本开支传导逻辑成立。
- **负向测试通过**（关键）：Anthropic IPO + 债/金组合 → `affected_holdings=[]` + "无直接关联，整体影响中性"——**不是通用话术**，说明有真实判别力。
- 不足：偏浅（沪深300 电子权重低属二阶影响；无幅度/时间窗/置信度）；黄金实为 risk-on 轻微利空却写"影响有限"。
- **性能债**：同步 POST **17.8s / 19.9s**；`ai_summary` 仅覆盖 headlines 桶且每轮上限 5 条 → 18 条中仅 5 条有摘要。
- 本轮该链路**无 429**，与 §4 单 provider 决策方向一致。

### 2.5 因子模型页（步骤8）

**页面结构是诚实的**：统计条显示「已接入 38 / 有效 16 / 低于阈值 9 / 无数据 2 / 静态 11」，四态齐备，`no_data` reason 具体到缺失字段（如 `etf.tracking_error`：79 只缺 `benchmark_close`）。**但它伪装了统计显著性**——

#### ❌ B1 [P0] `sample_count` 虚高约 240 倍 + 有效性判据违背业内标准（F25 完整设计见 §8 F25）
容器内 DB 实测（lead 亲验 `factor_ic_records`）：
```
etf.change_pct         4306 行 | 仅跨 18 个自然日 | 去重 ic_value 仅 62 个
technical.atr.atr_14   4306 行 | 仅跨 18 个自然日 | 去重仅 64 个
sample_count 取值 = 4306/4305/4304…  ← 即 DB 行数本身
时间跨度 2026-07-26 → 2026-08-14
```
- 根因：`ic_tracker.py:245` 的 `sample_count = await self._get_ic_sample_count_db(...)`，而该函数（`:253-268` 实读）就是 `count(*) from factor_ic_records where factor_code=?` **+1**——**统计的是"刷新次数"，不是"独立 IC 周期数"**。刷新循环约 121s 一次 ⇒ 4306 行 / 18 天 ≈ **239 行/天**，即把"1 天 1 期"膨胀成"1 天 239 期"。
- 讽刺点：该函数 docstring 明写目的是"统计 IC 累积周期数…对齐 ≥30 个 IC 周期"（round16 P0-12 修的是"恒 0 误标 no_data"），**修过头到了反面**：现在 `MIN_IC_SAMPLES=30`（`factors.py:29`）在**开机约 1 小时后被全部因子自动跨过** → "有效 16" 无统计含义。
- **统计误导**：每批 IC 是单期截面 Spearman（N≈40，SE≈0.16）⇒ `|IC|=0.27` 仅 **1.7σ**（不显著），却配 `n=4306` 展示，读者会当成 ~18σ 的铁律。
- **生存者偏差**：`ic_tracker.py:240` `if abs(ic_val) < 0.0001: continue` → 恰好接近 0 的批次被丢弃，落库序列系统性高估 |IC|。
- **量级不合常理**（旁证因子本身可疑）：`bollinger.bandwidth -0.72`、`premium_discount -0.61`、`macd 0.45`、`etf.price 0.27`（**原始价格水平**竟有预测力）；`ln_mcap` 与 `ln_float_mcap` 的 IC/样本数**完全相同** → 重复因子。

**业内标准对照（为何"有效 16"是假结论）**：
- IC 应按**日频**算（当日因子 vs 次日收益，一天 1 点），单日截面 N≈40 时 `SE(IC)≈1/√N≈0.16`，**单日 IC 几乎永远不显著**，业内从不以单日判因子。
- 判"因子有效"看 **IC 序列**：`IC_mean / IC_std / IR=IC_mean/IC_std / t=IC_mean×√T/IC_std`；经验门槛 **`|IR|≥0.5` 可用、`≥1.0` 优秀、`t≥2`（95% 置信）才算显著**。
- 要在典型 `|IC_mean|≈0.03, IC_std≈0.10` 下达到 `t≥2`，需 **T≈250 个交易日**（约 1 年）。**业内几乎不用 <60 天**。→ 当前 **18 天** 连门槛 1/10 都不到，**按任何标准都不可能有"有效因子"**。
- 行业还做 **5/10 组分层的多空收益验证** + **Newey-West 调整**（日频 IC 自相关） + **OOS 滚动窗口**；缺失批次**标记不删**（避免生存者偏差）。

> **结论**：F25 不是把 4306 改成 18，而是把"计数刷新次数 + 30 门槛"整套换成"日频 1 行 + t/IR 显著性门槛 + 分层验证"。**按业内标准，本系统当前 0 个因子能算统计有效**——18 天的自相关刷新数据，连 t≥2 的零头都不够。F25 的诚实结果就是"全部积累中"，这正是对的。详见 §8 F25。

#### ❌ B2 [P0] 「平均 |IC|」实为**带符号**均值，同屏自相矛盾 5 倍
- `routers/factors.py:363` 实读：`avg_all_ic = round(sum(all_ic_vals)/len(all_ic_vals), 4)` ——**带符号求和**，正负相互抵消。
- 前端 `FactorModelView.vue:62` 实读标签为「**平均 |IC|**」，显示 `0.0449`；真实 `mean(|IC|)` = **0.2368**（差 **5.3×**）。
- 同一页面下方的 IC 排序卡自行取绝对值 ≈0.2368 ⇒ **同屏两个"平均|IC|"相差 5 倍**。分类级同病（`etf_specific` 报 0.0055 vs 真实 0.2416）。
- 危害：0.0449 会让人判定"因子全无效"，0.2368 会判定"因子很强"——**同一页给出两个相反结论**。

#### ❌ C1 [P0-断裂] `zero_ratio` 恒为空 → "区分数据缺失 vs IC 无效"能力永久失效
`routers/factors.py:377` 读 `getattr(registry, "_zero_ratio", {})`，但 `_zero_ratio` 实际挂在 **ic_tracker 实例**上（`ic_tracker.py:179`，全局仅此两处引用）→ `getattr` 永远取不到，`zero_ratio` **恒 `{}`**。round16 P2-1/F3-4 想要的"零值占比 1.0 = 数据源未接入"判别力**从未生效过**。

#### ⚠️ C2/B3 其它
- **C2**：前端读 `summary.min_samples`（`FactorModelView.vue:73`），后端 summary 无此键 → 静默回退硬编码 30（字段契约缺失）。
- **B3**：`factors/model.total=193` vs `active.total=38`；`alternative 20` / `theme 29` / `microstructure 10` **整类零实现**，`style 37→2`、`technical 65→14`。**有效 16 / 宣称 193 = 8.3%**，与设计 554 的 `valid_rate=0.0824` 精确吻合（§3.1 同源）。缓解因素：`/factors/model` 前端 0 调用点，当前不上屏。

---

## 3. 数据完整性与正确性

### 3.1 因子数据完整性塌陷
- 设计 554 自报 `valid_rate 0.0824`（8%）；因子页（§2.5）同理呈降级态。89% 因子无数据却仍参与打分与方案生成→**权重决策建立在 8% 真实数据上**，属"假完成"风险（AGENTS.md 反假完成 §2）。
- 修复设计：valid_rate < 0.6 时 (a) 引擎降权/转等权；(b) 前端卡片级红字"因子数据缺失 N%";(c) 设计报告顶部强制横幅，不得弱化。

### 3.2 候选池脆弱 + 强板块未进池
- verify_e2e 失败项：`候选池总数量 >= 20 — total_candidates=0`；`方案数 >= 3 — 实际 0`。即**数据源熔断时候选池=0→设计产出 0 方案**，而测试注明"数据源熔断时可能为 0"——属于软放行，让"空结果"通过（§5）。
- `strong_sector_pool_coverage=[]`：强势板块未注入候选池，方案与市场热点脱节。
- 修复设计：候选池增加"静态兜底池"（历史优质 ETF 名单）避免 0；强板块动量 TopN 强制进入候选评分；0 方案时设计接口应明确返回 `degraded/no_data` 而非静默成功。

### 3.2b 前后端断裂清单（步骤9，已核实）
**真实断裂（3 处，均为"改一半/迁移遗留"）**：
| ID | 断裂 | 性质 |
|---|---|---|
| C1 | `factors.py:377` 取 `registry._zero_ratio`，实际挂 `ic_tracker`（`:179`）→ 恒 `{}` | 取错对象，能力永久失效（F27） |
| C4 | `market_data_hub.py:1705` `str(level) in ("重大","利好")`，level 已是 int → 恒 False | 类型迁移遗留（F28） |
| C2 | 前端读 `summary.min_samples`，后端无此键 → 静默回退 30 | 字段契约缺失（F32） |

**✅ 已核实无断裂**（避免误判为问题）：
- Vite 代理顺序正确——`vite.config.js:51-53` 中 `/api/v1/ws` 排在 `/api` 之前（符合 AGENTS.md §conventions 的坑位要求）。
- WS 路径对齐：前端 `/api/v1/ws/news` = `ws.py:96`。**AGENTS.md 里写的 `/ws/news` 属文档漂移**（少了 `/api/v1` 前缀），建议顺手修文档。
- `portfolio/etfs`、`realtime/portfolio`、`drift-check`、`timeline`、`designs` 字段逐个核对齐全（`realized_pnl`/`trade` 由 PUT 动态注入，`portfolio.py:95-99` 确认）。

### 3.3 数据完整性：孤立 avg_cost
- verify_e2e 失败项：`无孤立 avg_cost — 半成本持仓 20 条`（有成本无份额）。属导入/落库路径缺陷（round19 P3 系列已修部分，此 20 条残留）。
- 修复设计：写入 `avg_cost` 必须同时 `shares_held>0` 或显式"估算"标记；导入校验拦截；前端已"按估算处理"但后端不应落脏数据。

---

## 4. LLM Provider 可靠性（步骤2失败根因）

**现象**：`opencode_zen` 在日志中每轮 `429 Too Many Requests`；`llm-report/stream`、`llm-advice/stream` 验证失败（超时/空）；策略检查 LLM 19s 超时。

**429 的真实原因（单次探针实证，2026-08-14 容器内）**：
```
POST https://opencode.ai/zen/v1/chat/completions  → 429
{"type":"error","error":{"type":"FreeUsageLimitError",
 "message":"Error from provider (Console): Rate limit exceeded. Please try again later."}}
响应头：无 Retry-After / 无任何 rate-limit / quota 头
```
- 配置实测：`.env` **显式**设 `LLM_PRIMARY_PROVIDER=opencode_zen`、`LLM_FALLBACK_PROVIDER=deepseek`、`OPENCODE_ZEN_MODEL=deepseek-v4-flash-free`（免费档模型）、key 长度 67 有效存在。
- 结论：**不是 key 失效、不是我方请求过频**——错误类型 `FreeUsageLimitError` 表明是**免费额度用尽**（账号级配额，非每分钟限速）。空闲时刻单发一次仍 429 ⇒ **持久态**，重试永远无用。
- 次生问题：服务端**不返回 Retry-After**，`_rate_limit_wait`（`llm.py:55`）只能盲目指数退避 `3s*2^attempt`（cap 30s），退避越等越亏。

**"降级链没生效"的四层真相（分开看）**：
1. **路由层其实生效了**：日志可见 zen 429 后立刻转 `api.deepseek.com` 200 OK，`llm-report/stream` 产出 56KB 真实报告。所以 failover **不是坏的**——坏的是**延迟与预算**，不是正确性。
2. **无跨调用熔断**：round20 P0-5 的跳过集合 `_rate_limited`（`llm.py:650`）是**函数内局部变量**，只在**单次** `llm_complete()` 生命周期有效。每个新调用都重新探一遍必死的 primary → 每调用固定交 **2.1–2.4s "过路费"**（TLS+请求+429）。策略检查 10 只持仓 = 10 次以上重复缴费。
3. **流式路径连"单次跳过"都没有**：`llm_complete_stream()`（`llm.py:415-621`）**没有** `_rate_limited` 集合——每一轮 attempt 都重试 zen；整轮全失败后走 `_rate_limit_wait(attempt, None)` 盲目退避（3s→6s→…），直接吃掉外层预算。这解释了 `llm-report/stream` 慢、`llm-advice/stream` 空。
4. **预算与超时严重错配**：`.env` `LLM_PRIMARY_TIMEOUT=240` / `LLM_FALLBACK_TIMEOUT=240`（单请求 240s），而外层 `_llm_timeout_for` 只给 15/30/75s。策略检查实测 19s 时外层 `ReadTimeout` 掐断——**此时 fallback 往往还在路上**，成果被丢弃。用户感知的"降级链没生效"= **降级还没跑完就被上层超时杀掉**。

**修复设计（不实施）**：

### 4.1 目标架构：zen 主 + deepseek 备 + 模块级 TTL 熔断（用户 2026-08-14 决策）

**决策**：`opencode_zen` 作 **primary（免费层，能用就省钱）**，`deepseek` 作 **fallback（付费，可靠兜底）**；外加**跨调用、带 TTL 的熔断**，使 zen 持久 429 时**零探测、零过路费**直接走 deepseek，且额度恢复后能自动复探。

**为何这比"只用 deepseek"更优**：zen 是免费层，正常时省 deepseek 费用；缺陷只是"额度会用尽"。问题不在"该不该用 zen"，而在"每次都撞死 primary 缴过路费"。熔断正是为消除这个过路费而设——**保留免费层红利、又不被其拖死**。

**为何此前"单 provider"建议被推翻**：那是为规避"每调用重探 zen"而采取的简化；但正确解法是修熔断（让它跨调用共享 + 带 TTL），而非放弃免费层。

#### 状态机（核心设计）
熔断状态**必须是模块级（`analysis/llm.py` 顶部 `dict` 或单例），绝不能是函数局部**（当前 `_rate_limited` 是 `llm.py:650` 函数局部，每次调用重建 = 形同虚设）。

| 状态 | 行为 | 触发转移 |
|---|---|---|
| **CLOSED** | zen 当主直接用；deepseek 待命 | 收到 `429 / FreeUsageLimitError / timeout` → 记失败，计数达阈值 → **OPEN** |
| **OPEN** | 熔断窗口（TTL，建议 5–10 min）内**所有请求跳过 zen、直接 deepseek，零探测零过路费** | TTL 到期 → **HALF_OPEN** |
| **HALF_OPEN** | 下个请求**试一次 zen**：成功 → **CLOSED**（恢复免费层，清零计数）；又 429 → 回 **OPEN**（重置 TTL） | 见上 |

**关键参数决策**：
- **触发要"快"**：zen 的 429 是"额度耗尽"（`FreeUsageLimitError`），**非瞬时抖动**，不应像现在 F3-6 那样重试 + 盲目退避。`llm.py:55 _rate_limit_wait` 在无 `Retry-After` 时 `3s*2^attempt`（cap 30s）纯浪费 → **收到 429 立即判死、转 deepseek、置 OPEN**（即 F9c）。
- **TTL 取值**：免费档额度常按**分钟/小时/日**重置，建议默认 **300s（5min）**；HALF_OPEN 复探失败重置为 300s。
- **deepseek 也要纳入同一套熔断**（避免"zen 挂→deepseek 独腿→deepseek 也挂→无兜底"）：deepseek 进 OPEN 时，**快速转规则兜底**并打 `report_quality=fallback` + `llm_layer_ok=false`（T3），绝不静默冒充 AI 报告。
- **两种失败区别对待**：`429/FreeUsageLimitError`（额度类，持久）→ 直接 OPEN 不复试；`5xx/timeout`（瞬态）→ 保留有限重试（≤2 次）再判。

#### 具体改动点（不实施）
1. **provider 顺序**：`LLM_PRIMARY_PROVIDER=opencode_zen`（`.env:10`，**恢复此值**）、`LLM_FALLBACK_PROVIDER=deepseek`（`.env:11`，**恢复并真正读取**——当前 `provider.py` 从未读它，见 §6 死配置 F7b，需补读取逻辑使 fallback 真正生效）。`LLM_MODEL` 保持 `deepseek-v4-flash-free`（仅 zen 有效，官方走 shim→`deepseek-v4-flash`）。
2. **熔断状态提升为模块级 + TTL**（`F8`）：新建 `_circuit: dict[str, {"state","fail_count","opened_at"}]`，替换 `llm.py:650` 的局部 `_rate_limited`；`llm_complete` 与 `llm_complete_stream`（F9 补齐）共用同一状态。
3. **流式路径补齐跳过集合**（`F9`）：`llm_complete_stream()`（`llm.py:415-621`）当前**无跳过集合**，每轮 attempt 都重试 zen → 必须读同一 `_circuit`，OPEN 态直接跳过。
4. **预算与超时对齐**（`F9b`）：`LLM_PRIMARY_TIMEOUT=240`（`.env:12`）远大于外层 `_llm_timeout_for` 15/30/75s（`portfolio_service.py:779`）+ `LLM_MAX_RETRIES=2`（`llm.py:18`）。熔断 OPEN 后 deepseek 是单请求，必须让 `per-request timeout × (retries+1) + 退避 ≤ 外层预算`（建议单请求收紧到 12–20s），否则唯一有效腿的正常响应也会被外层掐断。
5. **兜底显式标注**（`T3`）：任何 provider 全失败时，任务 `report_quality=fallback` + `llm_layer_ok=false`，不得以 `completed` 静默过（AGENTS.md 反假完成）。
6. **健壮性**（`F7c`，P2）：`has_any_api_key()`（`provider.py:91`）只要 zen **或** deepseek 有 key 就返回 True；若 deepseek key 失效而 zen key 残留 → "检查通过但 providers 空"→ 含糊 `No LLM providers available`。应让它与实际入链 provider 对齐。

**验收**：
- zen 持久 429 时：日志**首跳后 5min 内 0 条** zen 请求（不再每调用 2.1–2.4s 重探）；策略检查 `covered_by_llm>0`（走 deepseek）。
- zen 额度恢复（或测试注入 200）后：≤1 个 TTL 周期内自动回 CLOSED、恢复免费层。
- 单 LLM 调用 p95 ≤ 12s；`llm-advice/stream` 中文体 200 非空。
- 模拟 deepseek 也 429 → 任务 `report_quality=fallback` 且 `llm_layer_ok=false`（非 `completed`）。

### 4.2 与"单 provider"方案对比（为何弃前者）

| 维度 | 单 provider（仅 deepseek） | **本方案（zen 主 + ds 备 + 熔断）** |
|---|---|---|
| 免费层红利 | 放弃 | **保留**（zen 正常时省钱） |
| zen 持久 429 时的过路费 | 无（zen 不在链） | **无**（熔断 OPEN 后零探测） |
| 成本 | 恒用付费 | 通常免费，仅兜底付费 |
| 实现量 | 改 1 个 env | 需新建模块级熔断（F8）+ 流式补齐（F9） |
| 风险 | deepseek 挂=总失败 | deepseek 挂→规则兜底（仍降级不冒充） |

> 结论：**本方案在不引入"每调用重探"的前提下，同时拿到免费层红利与可靠兜底**，是正确解。F7 恢复 zen 主、F8 升回 P0。

---

## 5. 测试防护缺口分析（步骤13）

**11 项 verify_e2e 失败归类**：
| 类别 | 失败项 | 性质 |
|---|---|---|
| LLM provider | llm-report/stream 超时、llm-advice/stream 空 | 根因 §4（配置） |
| 数据源熔断 | ETF 记录数=1、有成交额/规模/价格 ETF=0、候选池=0、候选池健康=None、方案数=0 | 环境 + 软放行 |
| 数据完整性 | 孤立 avg_cost 20 条 | 真实缺陷 |
| 性能 | timeline 1.2s > 1.0s gate | 真实（§1.2） |

**为何测试防护未识别**：
1. **软门禁/注释放行**：候选池、方案数失败项测试自身注明"数据源熔断时可能为 0"——把环境性失败合法化，**允许空结果通过**，恰是 AGENTS.md 反假完成机制点名的"假完成"温床（空方案 = 脚手架级输出却被标 PASS 区间）。
2. **断言层级过松**：大量断言仅校验 HTTP 200 / `len>0`，未校验"内容真值"（如设计是否真的 3 方案且含真实标的、因子分是否来自真实数据）。反假完成要求"内容断言 + 非兜底"。
3. **LLM 失败被静默降级**：策略检查 LLM 超时后返回 `completed` + 规则兜底，任务状态不失败→上层测试看到"完成"，未检测"covered_by_llm=0"。
4. **性能门禁孤立**：timeline 1.0s gate 仅单点，无回归基线对比；prod 与 e2e 环境阈值未统一。
5. **缺端到端内容契约测试**：前端期望字段 vs 后端响应无自动 diff（§9 数据断裂靠人工发现）。
6. **三条流式分析端点无冒烟覆盖**（§2.3）：`llm-advice/stream`、`symbol-analysis/stream`、`sector-analysis/stream` 目前**实际可用但零自动化覆盖**——所以本轮 v1 的"三端点全崩"误报才无从被现有测试否证，反过来说：若它们真崩了，测试同样发现不了。需补「中文提问 + 断言流非空且含 CJK」的冒烟用例。
7. **跨字段一致性无断言**（§2.3d）：KDJ 超买 vs signal、score vs label——这类**自相矛盾**只能靠"关系断言"（field A 与 field B 逻辑一致）发现，测试集中完全缺失。这是本轮唯一被独立复核确认的报告逻辑缺陷（F10）。
8. **统计口径造假无人拦截（本轮最隐蔽一类）**：`sample_count` 虚高 240×、`平均|IC|` 标签与算法差 5.3×、`zero_ratio` 恒空——**三者全部有测试覆盖的模块，却无一被发现**。原因：测试断言"字段存在/是数字/在合理区间"，从不断言**口径不变式**（样本数不得超过自然日跨度；标称 `|IC|` 必须等于 `mean(abs(ic))`；`zero_ratio` 不得恒空）。**这类缺陷是"测试绿 + 数字漂亮 + 结论错误"的完美假完成**，正是 AGENTS.md 反假完成机制针对的最高危形态（T10）。
9. **缓存把性能门禁变成摆设**：`factor-health` 热态 168ms（我判 ✅）vs 冷态 3.27s vs gp3 环境 11.17s。测试默认打热缓存 ⇒ **门禁永远绿、用户永远慢**（T9）。
10. **验证工具链本身无护栏（本轮新增教训）**：v1 用 Git Bash `curl -d '{"query":"中文"}'` 产出 4 个假缺陷（3 个"P0 端点崩溃" + 1 个"全站乱码"）。**审计工具的编码正确性没有自检**，导致"假阳性"和"假阴性"同源——同一个坏 harness 既能虚报故障、也能掩盖真故障。需在 `verify_e2e.py` 固化「中文体用 Python urllib 显式 UTF-8」并加一条自检用例（发已知中文 → 断言回显一致）。

**修复设计（不实施）**：
- T1：将"候选池=0/方案=0"由软放行改为**明确 degraded 状态断言**（允许熔断，但必须 `status=degraded` 而非静默成功），并区分"环境熔断"与"代码回归"。
- T2：新增负向内容断言（如 `covered_by_llm>0` 或显式 `llm_failed=true` 标记；因子分来源非全默认）。
- T3：策略检查任务增加 `llm_layer_ok` 字段，LLM 兜底时 `report_quality=fallback` 必须被测试识别。
- T4：性能门禁接入 `verify_perf.py` 基线，timeline/etfs 设硬上限并 CI 对比。

---

## 6. 冗余/死代码（subagent C：`backend/scripts/_findings_redundant.md`）

**6.1 死端点（0 个生产调用方，round16 已列删除但从未执行）**——直接删除：
- `routers/market.py:489` `/market/sentiment`、`:517` `/sectors/industry-cls`、`:523` `/sectors/{sector_code}/stocks`、`:529` `/sectors/{plate_code}/popular`、`:395` `/signal/debug/{symbol}`、`:656` `/market/wind`
- `routers/portfolio.py:133` `POST /apply-strategy`（前端仅 .spec.js mock，真实走 `/strategy-check-async`）
- `routers/analysis.py:725` `POST /news-impact/stream`（前端用非流式 `/news-impact`）
- `routers/news.py:30` `GET /news/research/{symbol}`（仅 round16 探针用过，现 404）

**保留**（无前端调用但被 verify_e2e/tests 覆盖）：`/market/realtime/batch`、`/factors/model`、`/news/macro|global|stock/{sym}`、`/admin/*`、`/sectors/rotation` 等——非死代码。

**6.2 重复/空实现**：
- 前端 `api/index.js:85` `export const analysisApi = {}` 空导出 → 删除。
- `api/index.js:57` `dailyPnl` 与 `:59` `getPnl` 同为 `POST /portfolio/daily-pnl` 重复 → 合并。
- 后端 `analysis.py:259` `class PortfolioReviewRequest` 零调用 → 删除。
- `engine/risk_controls.py:32` `max_turnover_rate` 零调用；`engine/budgets.py:97` `c2_adjust` 注释"死配置（引擎从未消费）" → 清理。

**6.2b 新增死代码（gp3 核实 + gp4 交叉复核）**：
- `routers/analysis.py:15` 导入 `analyze_news` 但**无调用点** → 全市场资讯综述能力已实现却未暴露。**决策点**：接通（加端点+前端 tab，配合 F29）或删除，不得静默留存（AGENTS.md 脚手架零容忍）。
- `engine/budgets.py:97` `c2_adjust`、`engine/risk_controls.py:32` `max_turnover_rate` 已在 6.2 列出；本轮追加 `.env` 死配置 `LLM_FALLBACK_PROVIDER`（§4.1，`config.py:84` 声明但 `provider.py` 从不读取 → **F7b 成立，实读 provider.py 143 行确认**）。

**6.2c gp4 交叉复核修正（重要，避免误删/误留）**：
- ✅ **`portfolio/{designs,strategy-checks}` 列表端点不是死端点**（推翻 6.2b 原"并入 §6.1 评估"的建议）：FE 虽只用 `timeline`，但被 `verify_e2e.py` 6 处（:135/262/296/372/534/1424/1737）+ `test_portfolio_list.py` / `test_performance_benchmark.py:65` 覆盖 → **保留**（属"前端未展示但测试覆盖"）。
- ⚠️ **`c2_adjust` 非"零引用"**：在 `budgets.py:35/52/69/95/97/117` 有 6 处装配管线（`:117` 从 meta 读入），但引擎**从不消费**（`:95` 注释明写"死配置"）→ 实为"死配置 + 透传管线"，清理需动 6 行而非删 1 行。
- ⚠️ **`dailyPnl`/`getPnl` 不能纯删**：入参顺序相反（`(totalCapital,type)` vs `(type,totalCapital)`，均在 `api/index.js:57/59`），合并须同步改 3 处调用方（PortfolioManager.vue:696 / useDashboardData.js:93-94 / stores/portfolio.js:45）。
- 🔒 **删路由前置硬约束（pre-commit 门禁）**：`scripts/check_routes.py` 是**双向**契约比对（actual↔api-contracts），`.githooks/pre-commit:94` 对路由/契约不一致 **`exit 1` 硬阻断**。**删任一死端点必须同批删对应契约条目**（共 7 文件 14 行，见 `_findings_redundant_review.md`），否则 commit 必失败。此点 subagent C 完全遗漏 → 若按其清单直接删会卡死 CI。
- 🔒 **删路由的级联风险（gp4 标出，实施必看）**：`/sectors/{sector_code}/stocks` 只能删路由（底层 `get_sector_stocks` 在 analysis.py:547、strategy_design.py:726 是活的）；`/market/sentiment` 删除**不影响** `get_market_sentiment`(hub:1565，5 处活调用，它调的是同名近似 `get_market_emotion`)；`/news-impact/stream` 删除时 `NewsImpactRequest`(analysis.py:186) 被 :231 共用不可删；`/sectors/industry-cls` 与保留的 `/sectors/rotation` 调同一实现，才是纯重复路由。
- 🔒 **`ic_tracker.py:179 _zero_ratio` 是只写属性**（唯一读方 factors.py:377 取错对象）→ 会被 `audit_unused_symbols` 门禁**误报为死代码，严禁删除**，它是 F27 靶点（与 §3.2b C1 同源）。
- ✅ **bug ≠ 死代码**：§3.2b 的 C1/C4/C2 三处断裂未混入本死代码清单（gp4 交叉核对干净），但实施期有真实误删风险，需按上条区分。

**6.3 诊断/临时残留清理**（gp4 复核后收敛）：
- **`backend/scripts/` agent 临时文件**（本轮产生，可删）：`_tmp_step2.py`、`_tmp_fetch2/3.py`、`_tmp_review.py`、`_step2_out.json`、`_step2_review.txt`、`_findings_*.md`、`_evidence/`、`_evidence_gp3/`（注意保留 `_findings_redundant_review.md` 为本轮复核交付物，勿删）。
- **`logs/` 现状**：全部被 `.gitignore` 覆盖（`git ls-files logs/` = 0），删除**不动 git 历史**，风险低（当前 ~76M，其中 png 28M / lighthouse 19M）。
- **🔒 不可直接删、需归档**：`logs/round20/corr_audit_out.txt`、`logs/tmp/perf_backend.py` 被 round20/round21 文档**当作证据引用** → 移入 `logs/archive/` 而非删；**必须保留**：`.unused_symbols.baseline.json`（已入库的门禁基线）、`backend.log`（RotatingFileHandler 管理）、warmup 四件产物（`warmup_timing.json`/`warmup_cprofile.txt`/`warmup_pyinstrument.html|txt`）。
- **顺序建议**：`scripts/` agent 临时 → `logs/` 散落 png/lighthouse → 证据引用文件归档（`logs/archive/`）→ 保留项不动。

**清理收益**：减少 8 个未接线端点（降低攻击面/维护认知负担）、消除前端空导出与重复 helper、清理 logs 散落文件、回收 ~76M 磁盘。建议顺序：死端点（同批删契约，§6.2c 🔒）→ agent/temp 残留 → 空/重复 API → 死类/死配置 → 日志归档。

**6.4 修正项（重要）**：subagent 建议删除 `docker-compose.diag.yml`，但**本轮性能诊断（步骤1/12）正是用它注入 `PROFILE_WARMUP=1` 完成的**——该文件功能有效、是预热性能开关的承重件，**应保留**（其注释提及的 `start_backend_profiled.py` 确实不存在，但 diag 文件本身不依赖它，仅设环境变量）。同理 `app/profiling/warmup_profiler.py` 由 `PROFILE_WARMUP` 激活、非孤儿，保留。

**清理收益**：减少 8 个未接线端点（降低攻击面/维护认知负担）、消除前端空导出与重复 helper、清理 logs 散落文件。建议顺序：死端点 → agent/temp 残留 → 空/重复 API → 死类/死配置。

---

## 7. 三份文档落地核验（步骤10）

| 文档 | 性质 | 结论 |
|---|---|---|
| docs/archived/design-portfolio-engine-redesign.md | 设计规格（v2，原"不实施"） | **已落地 round22（3269c8b）**：#10–#14（INV-1~6）5/5 实现 |
| docs/archived/engine-refactor-spec-round22.md | 实现批次 | **E1–E5 5/5 落地**（E5 相关性约束非窗口不跳过，4eb2d4d） |
| docs/archived/round21-container-acceptance-diagnosis.md | **纯诊断文档**（声明"本轮未做代码改动"） | 其内 P0-1/P0-3（round20 已落地）；**P1-3 KDJ超买→BUY、D9 confidence=0.7、因子 valid_rate、美股 hot-rank 5.2s 仍未修复**——本轮实锤（§2.2、§3.1） |

> 关键认知：round21 文档本身不是实现批次，其"问题清单"多数由 round22 间接或后续修复；**KDJ/confidence/因子率/美股热点 4 项明确仍未修复**，与本次实测一致。

---

## 8. 优化修复方案总表（不实施）

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| F1 | P1 | 重复 SSL 握手 ~5.5s | requests.Session + 连接池/重试 | SSL 累计 ≤1.5s | `fetchers/china_market.py` |
| F2 | P1 | 预热 NAV 串行 + 10s 超时未生效 | gather 并发 + 超时穿透 | 预热 ≤15s, market_cache ≤8s | `main.py:201`, `market_refresh.py` |
| F3 | P2 | 预热精度过高 | NAV 仅近 60 日 | — | `china_market.py` |
| F4 | P1 | 首屏 JS 阻塞（root 67） | 路由级懒加载 | root perf ≥90 | `frontend/src/router`, `vite.config.js` |
| F5 | P1 | 无 manualChunks | vendor 拆分 + preconnect | unused JS ≤100KB | `vite.config.js` |
| F6 | P2 | source map/对比度/robots | 补构建配置 | a11y ≥95 | `vite.config.js`, `public/robots.txt` |
| F7 | P0 | opencode_zen 作 primary 永久 429（`FreeUsageLimitError` 免费额度用尽，探针实证）；且 `LLM_FALLBACK_PROVIDER` 是死配置（`provider.py` 从不读） | **zen 主 + deepseek 备 + 模块级 TTL 熔断**（§4.1）：`.env` 恢复 `LLM_PRIMARY_PROVIDER=opencode_zen` / `LLM_FALLBACK_PROVIDER=deepseek`，并**真正读取** fallback；`LLM_MODEL` 保持 `deepseek-v4-flash-free` | 日志首跳后 5min 内 0 条 zen 请求、单调用 p95 ≤12s、`covered_by_llm>0` | `backend/.env:6,10,11,12`、`config.py:83-84`、`provider.py:49-86,91`、`portfolio_service.py:1010` |
| F7b | P2 | `LLM_FALLBACK_PROVIDER` / `LLM_PROVIDER` 死或遗留（`.env:5,11` 不被读取） | F7 一并接好读取逻辑；`LLM_PROVIDER` 遗留变量删或对齐 | 无误导性配置 | `backend/.env:5,11`、`config.py:70,84` |
| F8 | **P0**（恢复，熔断为本次方案核心） | 熔断只在单次调用内（`_rate_limited` 为函数局部 `llm.py:650`）→ 每调用重探死 primary 缴 2.1–2.4s 过路费 | **模块级 + TTL 状态机熔断**（§4.1）：CLOSED/OPEN/HALF_OPEN，429 直接 OPEN、TTL 默认 300s 后 HALF_OPEN 复探；zen 与 deepseek 共用同一状态 | zen 持久 429 时跨调用零探测；额度恢复自动回 CLOSED | `analysis/llm.py:650`（升为模块级 `_circuit`）、`:415-621` |
| F9 | **P1** | 流式路径无跳过集合（`llm.py:415-621`）+ 无 Retry-After 时盲目指数退避（`llm.py:55` 3s*2^attempt）纯浪费 | 流式补齐读同一 `_circuit`；OPEN 态直接跳过；429 不重试、快转 fallback | 不再浪费 3→6→12s 过路费 | `analysis/llm.py:415-621`、`:55` |
| F9b | **P0** | `LLM_PRIMARY_TIMEOUT=240` × retries 远超外层 15/30/75s 预算 → fallback 途中被外层掐断（策略检查 19s ReadTimeout） | 单请求超时收到 12–20s，使 `超时×(retries+1)+退避 ≤ 外层预算`；熔断 OPEN 后 deepseek 单请求不被误杀 | 无"AI 又超时"式误杀 | `backend/.env:12`、`portfolio_service.py:779`、`llm.py:18` |
| F10 | P0 | KDJ 超买→BUY 错误（实测 5 例超买误判 2 例，含 J=98.7+RSI=39.9→最强买入） | **两处同改**：(a) `tech_signal` 生成把 J>80 作为硬性谨慎/降级约束；(b) 建议合成中超买不得 `increase` | 全持仓扫描：J>80 无 buy/increase；且标签与 score 同源 | `portfolio_service.py:1196`(`tech_signal` 来源)、`:1557`(`avg_factor>0.5 and sig=="buy"→increase`)、`:60-63`(`_KDJ_HINT` 仅展示不约束)、`factor_registry.py:359`(因子分已对超买 -0.4，但 `sig` 未同步) |
| F11 | P1 | confidence 硬编码 0.7 | 由因子/信号置信推导 | 非全同值 | `portfolio_service` |
| F12 | P0 | 因子 8% 仍精确配置 | valid_rate 门控 + UI 横幅 | <0.6 强制降级提示 | `engine`, `frontend` |
| F13 | P1 | 候选池=0/强板块未进池 | 静态兜底池 + 强板块入池 | 0 方案=degraded | `market_data_hub`, `strategy_design` |
| F14 | P1 | 设计/检查因子分两路不一致 | 统一因子计算入口 | 同标的同分 | `factors/`, `strategy_design` |
| F15 | P2 | 孤立 avg_cost 20 条 | 落库校验 + 导入拦截 | 0 孤立 | `portfolio_service`, `import` |
| F16 | ~~P0~~ **已撤销（v2 误报）** | ~~`llm-advice/stream` 中文体 422~~ | 容器内 urllib 发送 UTF-8 中文体 → HTTP 200 / 26KB 中文流；v1 的 422 是 shell-curl 编码破坏误报 | — | — |
| F17 | ~~P0~~ **已撤销（v2 误报）** | ~~`symbol-analysis/stream` date 序列化崩溃~~ | v2 复测 HTTP 200 / 56KB 正常；v1 报错为 curl 误报 | — | — |
| F18 | ~~P0~~ **已撤销（v2 误报）** | ~~`sector-analysis/stream` 200 空 body~~ | v2 复测 HTTP 200 / 81KB 正常；v1 空 body 为 curl 误报 | — | — |
| F19 | ~~P1~~ **已撤销（v2 误报）** | ~~热门板块乱码~~ | 容器内 urllib 复测 `name=['医药','光通信'...]` 正常无 surrogate；v1 乱码为 shell-curl 破坏 UTF-8 误报 | — | — |
| F20 | P2 | `sentiment.up_ratio` 命名歧义（实为"涨停封板率"65%，非"上涨占比"26%） | 重命名为 `limit_up_seal_rate` 或前端标注口径 | 投资者不再误读为普涨 | `routers/market.py:491` sentiment 直传、`frontend` 展示 |
| F21 | P2 | 港美自选无实时（8/20 静默缺失） | 补港美实时源或显式标注"该市场暂无实时" | 无静默空值 | `routers/market.py` watchlist、`fetchers/` |
| **F22** | **P0** | `level` 是分类非重要性，前端 `>=4` 当重要 → **利空(3)永不推送、利好(4)必推** | **拆成两个正交字段**：`category`（利好/利空/重大/提醒）+ `importance`（1-5 单调）；前端按 importance 推送、按 category 着色 | 利空可进重要推送；筛选≥4 不再隐藏全部利空 | `levistock_fetcher.py`（level 定义与 `classify_news_level`）、`frontend/src/utils/newsLevel.js:6-11` |
| **F23** | **P0** | L4「利好」词表混入 `冲突/军事/制裁/战/核`，战争被标红为利好；`"战"` 子串误命中 `挑战/战略` | 地缘/军事/制裁移入独立 `risk` 类别（红涨语义下不得标利好色）；子串改词边界匹配 | 战争类不再判利好；`挑战/战略` 不误命中 | `levistock_fetcher.py:42-45` |
| **F24** | **P0** | 新闻 `time` 为 UTC，比北京时间**慢 8h**，且与 `news/stock/*`（东财北京时间）**两套时区并存** | 容器设 `TZ=Asia/Shanghai` 或统一在序列化层转 CST；全站时间戳单一口径 | `time` 与 `sort_time+8h` 一致；同页无双时区 | `docker-compose.yml`（TZ）、`levistock_fetcher.py` 时间格式化、`NewsView.vue:61` |
| **F25** | **P0** | `sample_count`=刷新次数（4306 行/18 天 ≈240×虚高），`MIN_IC_SAMPLES=30` 开机 1h 即失效；缺 t/IR/分层验证，单日 IC 当有效 | **重写为业内对齐的 IC 统计管线**（5 项，见下"F25 设计要点"） | 见 F25 验收；当前 0 因子合格（正确诚实） | `factors/ic_tracker.py:240,245,253-268`、`routers/factors.py:29,129,363`、`FactorModelView.vue` |
| **F26** | **P0** | 「平均 \|IC\|」实为带符号均值，与同屏 IC 卡差 5.3× | 改 `mean(abs(ic))`（或标签改为"平均 IC（带符号）"并同屏统一） | 同屏两值一致 | `routers/factors.py:363`、`FactorModelView.vue:62` |
| **F27** | **P0** | `zero_ratio` 取错对象（`getattr(registry,...)` vs 挂在 ic_tracker）→ 恒 `{}` | 从 ic_tracker 实例取；加"取不到即告警"防再次静默 | `zero_ratio` 非空，可区分缺失/无效 | `routers/factors.py:377`、`factors/ic_tracker.py:179` |
| **F28** | **P0** | AI 摘要 level 分支 `str(level) in ("重大","利好")` 恒 False（level 已是 int） | 改为按 int 重要性判定（与 F22 新字段对齐） | 重要性维度真实生效 | `services/market_data_hub.py:1705` |
| **F29** | P1 | 资讯页只调 headlines，`macro/global/stock/research` 4 端点 UI 不可达；且各自有缺陷（macro 全重复无中国宏观 / global 无 id、source 全 "RSS" / stock 滞后 17 天 / research 全空） | 前端接入 4 个 tab；后端修去重、补中国宏观源、补 id、修 research 空 | 4 端点上屏且内容非重复非空 | `frontend/src/api/index.js:88-91`、`routers/news.py`、`fetchers/news_fetcher.py` |
| **F30** | P1 | IC 生存者偏差（`abs(ic)<0.0001` 批次丢弃）+ `ln_mcap`/`ln_float_mcap` 重复因子 + `etf.price` 原始价格竟有 IC | 保留近零批次（或标记而非丢弃）；去重共线因子；审查 price 类因子是否穿越 | 序列无偏；无重复因子 | `factors/ic_tracker.py:240`、`factor_registry.py` |
| **F31** | P2 | 冷启动 headlines/macro 各返 1 条同一条，无"不完整"标识 | 缓存未热时显式 `partial:true` / degraded | 半成品不静默上屏 | `tasks/market_refresh.py`、`routers/news.py` |
| **F32** | P2 | 前端读 `summary.min_samples`，后端无此键（静默回退 30） | 后端 summary 补 `min_samples` | 字段契约齐 | `routers/factors.py` summary、`FactorModelView.vue:73` |
| **F33** | P2 | `factors/model` 宣称 193，实现 38，3 整类零实现（有效16/193=8.3%） | 下线未实现类或标注"规划中"，避免数字虚高 | 宣称=可用 | `factors/factor_registry.py`、`routers/factors.py` |
| **F34** | **P0** | ✅【已实施 `routers/portfolio.py:553-660`】**timeline 热态慢**（承接 round20 P0-1；原「无 TTL/limit/分页」判断已过时——代码已落地 30s TTL 缓存+`limit(limit+1)`裁剪+列裁剪；§1.2 的 2815-2974ms 为落地前实测） | ① 查询加 `limit`+子查询分页；② 大字段 column defer；③ 30s TTL 内存缓存（对齐 admin_metrics `admin.py:258-285`）；④ check/task 表同样裁剪 | /portfolio/timeline 热态 ≤300ms；`verify_perf` timeline 阈值 1.0s 改**硬门禁**；`verify_e2e.py:630` 阈值 5.0→1.0s | `routers/portfolio.py:529-583` |
| **F35** | **P0** | 🔲【待实施】**home CLS 0.389**（承接 round20 P0-2；§1.3 前端 perf 未单列 CLS，home 恒 `0.3885205676603475` 浮点级一致，确定性布局偏移非冷却期现象） | PerformanceObserver layout-shift 定位偏移元素（Dashboard 顶部 strip/卡片 mount 后插入）；根因修复后加 Lighthouse CLS 断言 ≤0.1 | home CLS ≤0.1；round14 P1-G「声称修复」须实测背书 | `frontend/src/views/Dashboard*.vue`（待定位） |
| **F36** | **P0** | ✅【已实施 `fetchers/china_market.py:281-318,1688`】**港股历史 K 线**（承接 round20 P0-4；代码已落 TickFlow HK 分支，`history/00700?asset_type=HK` 返回真实 K 线，symbol-analysis 不再 DATA_UNAVAILABLE） | `fetch_history`/`indicators` 的 HK 分支接 TickFlow（`hk{sym}` 320 根实证）或腾讯 `hk{sym}`；HK 指数历史（HSI/HSTECH）补齐 | `/market/history/00700?asset_type=HK` ≥30 根真实 K 线；symbol-analysis HK 不再 DATA_UNAVAILABLE；**验证窗口：交易时段** | `fetchers/china_market.py`（fetch_history HK 分支）、`factors/indicators` 路径 |
| **F37** | **P1** | ✅【已实施 `engine/allocation_engine.py:1365`、`services/strategy_design.py:373-394`】**max_correlation 高相关对权重硬约束**（承接 round20 P1-1；代码已落 `enforce_max_correlation` 高相关对合计权重 ≤ max_combined_weight，原「未实施」判断已过时） | allocation_engine 分配后校验——高相关对（r≥0.9）合计权重 ≤ 阈值（如 25%）；跨名称高相关约束；超限剔除低 factor_score 标的 + 报告标注「关联度提示」 | 方案「高相关对合计权重 ≤ 阈值」断言；task419 式组合不再 30% 高相关核心层；负向断言高相关超限→FAIL | `engine/risk_controls.py:31`、`engine/allocation_engine.py` |
| **F38** | **P1** | ✅【已实施 `engine/rationale.py:108-113`】**低相关措辞确定性插入**（承接 round20 P1-2；median<0.3 强制从低相关措辞池中选，原「hash 随机不保证出现」已修复） | 低相关标的（median<0.3）强制插入「与组合低相关」措辞（覆盖 hash 选取）或确定性匹配 | `build_rationale` 单测 `correlation_median=0.2 → 必含低相关`；负向断言无措辞→FAIL | `engine/rationale.py:108` |
| **F39** | **P1** | ✅【已实施 `fetchers/china_market.py:292-297,311`】**美股 K 线历史**（承接 round20 P1-5；代码已落 TickFlow US 分支，`history/AAPL?asset_type=US` 返回真实 K 线） | `fetch_history` US 分支接 TickFlow（`AAPL.US`/`SPY.US` 各 500 根实证）；`stock-hot-rank?market=US` 备源（新浪 levistock 美股 spot） | `/market/history/AAPL?asset_type=US` ≥30 根真实 K 线；美股盘中 `stock-hot-rank?market=US` 非空；**验证窗口：美股时段** | `fetchers/china_market.py`（fetch_history US 分支） |
| **F40** | **P2** | ✅【已实施 `app/analysis/design_report.py:194`】**多因子评分注释与数据一致**（承接 round20 P2-4；注释已改「因子综合分（可负可超 1）」，design 525 `511090=-2.31` 已符合） | 注释改为「因子综合分（可负可超 1，区别于技术信号）」或按实际分布截断 | 报告注释与数值范围一致断言 | `engine/allocation_engine.py`（综合信号注释）、design 输出 |

### F25 设计要点（业内对齐的 IC 统计管线，不实施）

> 背景：当前"有效 16"是用刷新次数冒充交易日、用 30 冒充 250 造出的假结论。本设计把整条 IC 口径换为业内标准，**预期结果是当前 0 因子合格**（18 天自相关刷新数据连 t≥2 的零头都不够），这正是诚实该有的状态。

**① 存储粒度：日频 1 行，不再每刷新存 1 行**
- `ic_tracker` 改为**每日收盘算 1 次 IC（当日期货/ETF 因子值 vs 次日收益）**，对 `factor_ic_records` 按 `(factor_code, date)` 设唯一约束，同 1 天重复刷新只 upsert 不追加。
- `sample_count` 语义改为 **`count(distinct date)`**，合理值现 ≈ 18（随运行天数增长）。彻底消除 121s 刷新注水。
- 验收：`factor_ic_records` 总行数 == 去重日数；`sample_count` 与 `max(computed_at)-min(computed_at)` 天数一致。

**② 显著性判定：`t≥2 且 IR≥0.5`，替换 `samples≥30`**
- 新增序列统计：`IC_mean = mean(ic)`、`IC_std = std(ic)`（截面内）、`IR = IC_mean/IC_std`、`t = IC_mean × √T / IC_std_with_NW`，其中 **SE 用 Newey-West 调整**（日频 IC 自相关，naive `√T` 会低估 SE）。
- `MIN_IC_SAMPLES` 由 30 → **`MIN_TRADING_DAYS = 250`**（默认建议；可配置 60 为下限预警，250 为"有效"门槛），**且必须 `t≥2`（95% 置信）AND `|IR|≥0.5`** 才标 `valid`。UI 分两档：`≥60` 标"积累中（可观察）"，`≥250 且 t≥2 且 |IR|≥0.5` 标"有效"。
- `routers/factors.py:129-130` 的 `no_data` 判定改为：`samples < MIN_TRADING_DAYS` → `no_data`（积累中）；`samples ≥ MIN` 但 `t<2 or |IR|<0.5` → `warn`（有样本但统计不显著）。
- 验收：18 天数据下所有因子状态 = `no_data`（积累中），不得出现 `valid`；注入 250+ 天仿真数据后，仅 `t≥2 且 IR≥0.5` 的因子转 `valid`。

**③ 缺失值：标记不删（修复生存者偏差）**
- `ic_tracker.py:240` 的 `abs(ic_val) < 0.0001 → continue` 改为：**标记 `signal_absent=True` 仍落库**（IC 记 0），参与"有效天数"统计但 IC 计 0，避免序列系统性偏高。
- 验收：`factor_ic_records` 含近零批次行；`zero_ratio`（F27 修对后）能反映真实"无信号"占比。

**④ 前端透明化：四指标齐展示**
- `FactorModelView.vue` 在 IC 卡同时展示 **`IC_mean`（带符号）/`IC_std`/`t`/`IR`** 四项，替换单一的 `ic_value` 均值；`avg|IC|` 必须用 `mean(abs(ic))`（与 F26 一致）。
- "有效 16" 改称"统计显著因子 N"，并标注"基于 t≥2 / IR≥0.5 / ≥250 交易日"。
- 验收：同屏不存在两个相差 5× 的"平均|IC|"；`t<2` 因子前端显式标"未显著"。

**⑤ 交叉验证（可选但强烈建议，后置）：分层多空收益**
- 对 `valid` 因子做 5 组分层的 top-bottom 多空组合收益，作为 IC 的旁证；该收益不单调或为负 ⇒ 即便 IC 显著也降级（防过拟合/伪相关）。

**预期总效果**：页面从"有效 16 / 静态 11 / 无数据 2"变为"积累中 38（0 有效）"——数字难看但**真实**；随运行满 250 交易日且因子质量达标，逐步翻绿。配合 F12 的降级横幅（"因子数据积累中，方案仅供参考"），实现 AGENTS.md 反假完成的"诚实降级"。

**迁移/数据重建**：改动②后旧 `factor_ic_records`（4306 行 × 18 天注水）**必须清空重建**（否则旧行污染 `sample_count` 与 `t`）；建议在迁移脚本里 `DELETE FROM factor_ic_records` 并重置 tracker 内存计数。

### 8.1 测试防护修复表（不实施）

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| T1 | P1 | 空结果软放行 | degraded 断言区分 | 熔断≠静默成功 | `verify_e2e.py` |
| T2 | P1 | 断言仅 200/len | 加内容/非兜底断言 | 负向可失败 | `tests/*` |
| T3 | ~~P1~~ **P0**（单 provider 后升级） | LLM 兜底不显式——无 fallback 后兜底概率上升，静默冒充 AI 报告风险变高 | 加 `llm_layer_ok` / `report_quality=fallback`，任务不得以 `completed` 静默过 | 测试可识别；462 类"100% 规则兜底"必须失败 | `strategy_check_worker`、`task_manager` |
| T4 | P2 | 性能门禁无基线 | verify_perf 基线 | CI 对比 | `scripts/verify_perf.py` |
| T5 | P1 | 三条流式端点零覆盖（现可用，但坏了也测不出） | 加冒烟：中文体 + 断言流非空且含 CJK | 三端点必测 | `tests/`、`verify_e2e.py` |
| T6 | P2 | 无文本可读性断言 | 加"无 lone surrogate / 含 CJK"断言 | 真乱码可被拦截 | `tests/` |
| T7 | P1 | 无跨字段一致性断言 | KDJ↔signal、score↔label 关系断言 | 自相矛盾可失败 | `tests/` |
| T8 | P1 | **审计 harness 无编码护栏**（本轮 4 个误报根源） | `verify_e2e.py` 统一用 Python urllib + 显式 UTF-8；加"中文回显一致"自检 | shell-curl 类误报不再发生 | `scripts/verify_e2e.py` |
| T9 | P1 | **性能计时只测热态，缓存掩盖冷启动**（factor-health 热 168ms vs 冷 3.27s，差 19×） | 计时区分「冷/热」两档；冷态单独设阈值并纳入基线 | 冷态超标可被发现 | `scripts/verify_perf.py`、`verify_e2e.py` |
| T10 | P1 | 统计口径无自校验（`sample_count` 240×虚高、`avg\|IC\|` 5.3× 偏差**均无测试**） | 加不变式断言：样本数 ≤ 自然日跨度；`avg_abs_ic` == `mean(abs(ic))` | 统计造假可被拦截 | `tests/test_factors*.py` |
| T11 | P1 | 分级语义无断言（利空永不进重要推送**无测试**） | 加断言：利空样本必须能进 importance≥4；战争类不得判利好 | 方向性偏置可失败 | `tests/`（news 分级） |

---

## 9. 多轮 review 记录（不实施，仅评审）

- **Round 1（自检）**：覆盖性能/报告/数据/LLM/测试/文档；标注 subagent 段落待补。
- **Round 2（已完成，本次）**：并入 §2.3（行情/AI 分析）、§2.4（资讯）、§2.5（因子）、§3.2b（断裂）、§6.2b（死代码）实证。**Round 2 的核心产出是"证伪"而非"新增"**：
  - **撤销 4 条误报**（F16–F19）：三条流式端点 + 全站乱码，经容器内 `urllib` 显式 UTF-8 复测均正常（原因：Git Bash 下 shell-quoted curl 破坏 UTF-8）。
  - **修正 1 条自测结论**：`factor-health` 由 ✅168ms 改为 ❌冷态 3.27s（缓存掩盖）。
  - **降级 1 条**：`up_ratio` 由"数据自相矛盾 P1"降为"命名歧义 P2"——实为涨停封板率 `37/(37+20)=64.9%`，字段本身正确。
  - **新增 12 条实锤 P0/P1**（F22–F33），其中 5 条经 lead 逐条独立复核（读源码 + 容器实测 + DB 查询）。
  - **优先级重排**：单 provider 决策后 F9b/T3 升 P0、F8/F9 降级；问题分级由"性能优先"改为 **P0-A 投资误导 / P0-B 统计造假 / P0-C 已死路径** 三类（危害驱动而非模块驱动）。
- **Round 3（终稿前需补，尚未完成）**：
  1. **F22 需先做设计决策再实施**：`level` 拆分为 `category` + `importance` 属**契约变更**（影响前端着色/推送/筛选 + WS 推送 + AGENTS.md §conventions 的"资讯分级"约定）→ 按 AGENTS.md「API 契约先于实现」，**必须先写 `api-contracts/news/` 契约**，不可直接改代码。
  2. **F25 已按业内标准重写（§8 F25 设计要点）**：不再纠结"按日去重是否变 0"——结论明确为 **"按业内标准当前 0 因子合格"**，这是诚实应有状态。**决策已定（2026-08-14）**：① `MIN_TRADING_DAYS` 默认 **250** 为"有效/显著"硬标准（不妥协），但 UI **分两档**——`≥60` 标"积累中（可观察）"、`≥250 且 t≥2 且 |IR|≥0.5` 标"有效"；② 迁移时**必须清空旧 `factor_ic_records` 重建**；③ **F25-⑤ 分层多空验证后置**，本轮先落 ①②③④。
  3. **F24 时区改动需全站核查**：设 `TZ=Asia/Shanghai` 会影响所有 `datetime.utcnow()` 调用点（`ic_tracker.py:233` 等）与 DB 已存数据的解读 → 需列全量受影响点，避免"修了显示、坏了存储"。
  4. 补 §1.3 前端 Lighthouse 冷态复测（当前 root=67 是否也受缓存影响待验）。
  5. **gp-4 冗余/死代码交叉复核已完成（2026-08-14）**，关键修正已并入 §6.1/§6.2b/§6.2c/§6.3：
     - **推翻**：`portfolio/{designs,strategy-checks}` 列表端点判死（实际 verify_e2e 6 处 + 测试覆盖，应保留）。
     - **修正**：`c2_adjust` 非"零引用"而是"死配置+6 处透传"；`dailyPnl`/`getPnl` 入参顺序相反，合并需改 3 调用方。
     - **🔒 实施前置硬约束**：删死端点**必须同批删 api-contracts 对应条目**（7 文件 14 行），否则 `.githooks/pre-commit:94` 的 `check_routes` 双向比对 `exit 1` 卡死 CI（subagent C 完全遗漏）。
     - **误删防护**：`ic_tracker.py:179 _zero_ratio` 是只写属性，会被 `audit_unused_symbols` 误报死代码 → 严禁删（F27 靶点）；删路由注意底层 `get_sector_stocks`/`get_market_emotion`/`NewsImpactRequest` 级联。
     - **清理范围收敛**：`logs/` 全被 gitignore（`git ls-files logs/`=0），删除不动 git 历史；但 `logs/round20/corr_audit_out.txt`、`logs/tmp/perf_backend.py` 被历史文档引用 → 移入 `logs/archive/` 而非删；必须保留 `.unused_symbols.baseline.json`（门禁基线）、`backend.log`、warmup 四件产物。
  6. 补 §1.3 前端 Lighthouse 冷态复测（当前 root=67 是否也受缓存影响待验）。
  7. 待 §7 文档核验交叉复核后定稿。

> **当前状态：Round 3 实质完成（gp-4 复核已并入）**。剩余未达实施标准的 3 项前置决策已在 Round 3 第 1–2 条**决策完毕**（F22 契约先行、F25 两档阈值+⑤后置），等待用户"开始实施"指令。**达到实施标准前不写任何修复代码**。

---

## 10. 架构分层与冗余整改方案（不实施）

> 本节针对「架构审查」独立结论（非 §2–§6 的正确性/性能/LLM/测试项），提出分层泄漏、反向依赖、god-object、透传冗余、死代码整改设计。
> **独立性**：不碰 §8 的 F1–F33（正确性/性能/LLM），与 round24 引擎重设计（E1–E5）正交；仅动结构/分层/冗余。
> **不实施**：本节仅设计，达到实施标准后待用户指令再落地。

### 10.0 总体 verdict
架构**方向合理**（router→service→engine/fetcher 分层意图清晰、engine 纯函数化理念正确、TDD 纪律强），但存在 **5 类已核实的"名实不符/冗余"**，均带 `file:line` 证据。不属烂架构，但有几处该修。

| 级 | 问题 | 核心证据 | 整改 |
|---|---|---|---|
| P1 | engine "纯函数无 I/O" 已泄漏 | `engine/allocation_engine.py:379` 循环内 `import factor_registry` 读私有全局态 `_factors`/`_ic_series_cache` | A1 参数化 + A2 分层门禁 |
| P1 | 下层反向依赖上层 | `fetchers/*` `from ..services.source_registry import`（5+ 文件）；`_health()` 被 18 处当公共 API | B1 下沉 `app/core/` + 改名 |
| P2 | 真实死代码/脚手架 | `engine/design_quality.py` **生产 0 调用**（仅 e2e + tests） | C1 接通或删 |
| P2 | 透传/重复抽象 | `safe_call`=`run_in_thread` 同语义（`async_utils.py:81`）；`market_service._td/_fh` 一行透传 | D1 收敛 |
| P1 | god-object + 公式重复 | `portfolio_service.py` 2448 行/39 函数 4 类职责；市态归一化两份（`risk_controls.py:39` vs `market_data_hub.py:959`）；现金/权重重算（`strategy_design.py:512,522` vs engine） | E1 拆 / E2 去重 |

### 10.1 问题清单（证据链 D2）

**P1-A engine 纯度泄漏**
- `engine/allocation_engine.py:379`：
  ```python
  from app.factors.factor_registry import FactorRegistry as _FR, registry as _fr_registry
  factor_scores = _FR.aggregate_factor_scores(
      factor_scores,
      definitions=_fr_registry._factors,                  # 读私有态
      ic_series=getattr(_fr_registry, "_ic_series_cache", None),  # 进程全局可变态
  )
  ```
- `_factors`/`_ic_series_cache` 由 I/O 填充（`factor_registry.py:1053 open()+yaml`、`:824 urllib.request.urlopen(req, timeout=8)`、`:1843 self._ic_series_cache = by_code`）。
- **后果**：engine 输出依赖进程全局可变态 → 纯函数可重放/可测性实质失效；AGENTS.md 把 engine 标「无 I/O 纯函数」是文档声明，但 `.githooks/` 13+ 门禁段**无任何分层/纯度守护**。
- 探针：`grep -rn "open(\|urllib\|requests\|sqlite3" app/engine/` → 仅 `allocation_engine.py:379` 一处经 `factor_registry` 间接引入 I/O 态，其余 engine 干净。

**P1-B 下层反向依赖上层**
- fetcher/factor 层 `from ..services.source_registry import`：`china_market.py:24,554`、`fundamentals_fetcher.py:12`、`etf_scanner.py:461`、`hk_hot_fetcher.py:24`、`sector_fetcher.py:12`（共 5+ 处）。
- `source_registry._health()` 被 `fundamentals_fetcher.py:26,31,37,336,378` + `factor_registry.py:1267` 等 18 处当**跨包公共 API** 直读（命名 `_health` 暗示私有）。
- **后果**：fetchers（下层）依赖 services（上层）→ 分层倒置；`source_registry` 错放在 `services/`。

**P2-C 死代码 / 脚手架（违反项目自身规则）**
- `engine/design_quality.py:26 validate_design_quality(strategies)`：**生产 0 调用**，仅 `scripts/verify_e2e.py:1755` 与 `tests/test_design_quality_gate.py:7` 引用。按 AGENTS.md「0 引用=脚手架，要么接通要么清理」→ 应决策。

**P2-D 透传 / 重复抽象**
- `core/async_utils.py:81` `safe_call` 实现即 `return run_in_thread(fn, *args, ...)`，docstring 自承「语义与 run_in_thread 相同」→ 零逻辑透传；再被 `fetchers/news_fetcher.py:41`、`levistock_fetcher.py:19` 的 `_safe` 二次包装（仅改默认 timeout/executor）→ **3 跳无增益**。
- `services/market_service.py:1280 _td`、`:1282 _fh` 同类一行透传。
- 调用面探针：`safe_call`/`safe_call_async`/`run_in_thread`/`run_sync` 在 ~30 个文件出现（china_market 25、fundamentals_fetcher 22、global_markets 7、market_service 9、market_data_hub 13 等）→ **删除 `safe_call`/`safe_call_async` 会触发大面积改写**，故 D1 不主张强删（见 §10.3 D1）。

**P1-E god-object + 公式重复**
- `portfolio_service.py` **2448 行 / 39 函数**，混 4 类不相干职责：CRUD(`:197-395`)、计算(`:573,680,1982,2394`)、**LLM/规则报告(`:831 strategy_check` 单函数 497 行 + `:1640 _build_rule_fallback_report`)**、导入导出(`:2193-2394`)；且与 `tasks/strategy_check_worker.py`(282 行) 职责撕裂。
- 市态归一化两份：`engine/risk_controls.py:39` 注释「与 market_data_hub._normalize_regime 同口径」 vs `services/market_data_hub.py:959`。
- 权重/现金公式在编排层重算：`strategy_design.py:512 cash_weight = round(1.0 - total_weight, 4)`、`:522 a["target_amount"] = round(capital * a.get("weight", 0), 2)`，与 engine 权重职责重叠（engine 已在 `:197/:206` 产出 `target_amount`）。

### 10.2 整改方案总表（不实施）

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| **A1** | P1 | engine 纯度泄漏 | `allocation_engine.allocate()` 显式接收 `definitions`/`ic_series` 入参；调用方 `strategy_design.py` 计算前注入（从 registry 读一次，非循环内）；删 `:379` 循环内 import | engine 内 0 处 import `factor_registry` 私有态；`pytest tests/test_*engine*.py` 全绿；同输入同输出可重放 | `engine/allocation_engine.py:379`、`services/strategy_design.py`（注入点） |
| **A2** | P1 | 分层无门禁守护 | 新增 pre-commit 第 14 段（差异化见 §10.4）：AST 校验 `app/engine/**` 不得 `import app.services|app.fetchers|app.tasks|app.analysis`、不得 `open()/urllib/requests/sqlite3/aiohttp/httpx`；违例 `exit 1` | 门禁对任意 engine 越界 import 阻断；误报率 0（纯 AST，无网络） | `.githooks/pre-commit`、`scripts/check_engine_purity.py`（新建） |
| **B1** | P1 | source_registry 反向依赖 | 迁 `app/services/source_registry.py` → `app/core/source_registry.py`；同步 5+ fetcher/factor 的 import 路径；`_health()` → `health()`（公开）+ 文档标注为公共 API | `grep -rn "services.source_registry" app/` 命中 0；`pytest tests/test_data_source_fallback.py` 全绿 | `app/core/source_registry.py`（新）、`china_market.py:24,554`、`fundamentals_fetcher.py:12`、`etf_scanner.py:461`、`hk_hot_fetcher.py:24`、`sector_fetcher.py:12`、`factor_registry.py:1267` |
| **C1** | P2 | design_quality 0 调用 | **决策（推荐删）**：其质量逻辑与 `tasks/design_report.py._validate_report_consistency` 重叠，且生产无调用 → 删除模块 + `tests/test_design_quality_gate.py` + `verify_e2e.py:1755` 引用；如需保留质量门禁则接进 `design_report.py` 后处理 | 删除后 `grep -rn "design_quality" app/ tests/` 仅剩历史注释；pytest 无悬空 import | `engine/design_quality.py`、`tests/test_design_quality_gate.py`、`scripts/verify_e2e.py:1755` |
| **D1** | P2 | 透传/重复抽象 | ① 删各 fetcher 内 `_safe` 二次包装（`news_fetcher.py:41`、`levistock_fetcher.py:19` 等），直接调 `run_sync`/`run_in_thread` 并传 `timeout`/`executor`；② 保留 `run_sync`/`run_in_thread` 为唯一规范名，`safe_call`/`safe_call_async`（`async_utils.py:74,133`）标记 deprecated 别名（短期保留控制改动面，后续轮次移除）；③ 删 `market_service.py:1280 _td`、`:1282 _fh` 透传 | `grep -rn "def _safe" app/fetchers/` 命中 0；fetcher 行为不变 | `core/async_utils.py:74,133`、`fetchers/news_fetcher.py:41`、`levistock_fetcher.py:19`、`market_service.py:1280,1282` |
| **E1** | P1 | portfolio_service god-object | 拆（详见 §10.3 E1 细化）：① 报告集群 → `services/strategy_check.py`（与 `tasks/strategy_check_worker.py` 合流）；② IO 集群 → `services/portfolio_io.py`；③ CRUD/计算留 `portfolio_service.py` | 拆分后单文件 ≤~800 行；`routers/portfolio.py`/`tasks/*`/`verify_e2e.py` 调用点仍可解析；pytest 全绿 | `services/portfolio_service.py`、`services/strategy_check.py`（新）、`services/portfolio_io.py`（新）、`tasks/strategy_check_worker.py` |
| **E2** | P1 | 公式重复 | 市态归一化：保留 `market_data_hub._normalize_regime:959`，`risk_controls.py:39` 改调 hub 版或提取 `core/regime.py` 共用；权重/现金：`strategy_design.py:512,522` 信任 engine 已产出的 `target_amount`，仅做一致性校验（现有 `:846 _validate_target_amount_consistency`） | 两份归一化合并为 1；`strategy_design` 不再重算 `target_amount`；输出值不变 | `engine/risk_controls.py:39`、`services/market_data_hub.py:959`、`services/strategy_design.py:512,522,846` |

### 10.3 重大项细化（E1 拆分函数归属表）

`portfolio_service.py` 39 函数按职责定性（行号来自 `grep def`）：

| 目标文件 | 函数（行号） | 说明 |
|---|---|---|
| **保留 `portfolio_service.py`**（CRUD/计算） | `list_etfs:197` `add_etf:205` `update_etf:269` `remove_etf:385` `recompute_cost_after_trade:153` `_recompute_target_weight:348` `calculate_allocation:573` `calculate_daily_pnl:680` `calculate_cumulative_pnl:1982` `apply_strategy_suggestions:1891` `apply_portfolio_design:1923` `_build_price_map_async:444` 等 | 核心组合计算与持久化 |
| **→ `services/strategy_check.py`**（LLM/规则报告 + 与 worker 合流） | `strategy_check:831`（497 行）`_build_rule_fallback_report:1640` `_build_rule_fallback_holdings_analysis:1414` `_rule_based_suggestion:1481` `_compute_risk_warnings:1760` `_combine_risk_warnings:1729` `_compute_confidence:1402` `_build_llm_fail_summary:750` `_is_failed_result:741` | 报告生成逻辑；`tasks/strategy_check_worker.py` 改为 import 本模块 |
| **→ `services/portfolio_io.py`**（导入导出/漂移） | `export_portfolio:2193` `import_portfolio:2254` `calculate_weight_drift:2394` | IO 与漂移计算独立成模块 |

**E1 实施前置**：`grep -rn "portfolio_service\."` 复核 `routers/portfolio.py`、`tasks/strategy_check_worker.py`、`scripts/verify_e2e.py` 的 import/调用在拆分后仍可解析；`strategy_check` 迁入后 `tasks/strategy_check_worker.py` 调用签名须同步。

### 10.4 design-checklist 8 项回查（D1-D8）

| # | 检查项 | 本设计结论 |
|---|---|---|
| 1 可行性探针 | 每整改项最小验证？ | 是：A1/B1/D1/E1 为「移动/改名/删透传」纯结构操作，探针=`grep` 确认调用点（已附 file:line）；A2 为纯 AST 静态检查，无网络/DB。 |
| 2 证据链 | 每结论有计算式+file:line+实测？ | 是：§10.1 每项带 `file:line` + 实测 grep 输出；行数来自 `wc -l`。 |
| 3 验证窗口 | 外部行情/实时源功能标窗口？ | **N/A**：纯架构重构，不触数据源；`verify_e2e.py` 需后端启动但任意时段可跑，标注「非行情依赖，非窗口也可验」。 |
| 4 非兜底数据 | 输出会不会只剩 fallback？ | N/A：无新增数据源/输出；删除项（C1）按「0 引用=脚手架」处理，不冒充实现。 |
| 5 真实调用点 | 删除/改名确认 0 悬空？ | 关键：B1 列全 5+ import 点须同步；C1/D1 删前 `grep` 确认无生产调用；E1 拆后调用点须可解析（§10.3/§10.5）。 |
| 6 四态 UI | 前端四态？ | N/A：无前端改动。 |
| 7 复杂度审计 | 新增 IO 超时/批量？ | A2 门禁纯 AST、零 IO；其余为移动/删减，不新增网络/DB/文件调用；不引入循环内 IO。 |
| 8 已知问题模式 | 对照 round14 §4 盲区 | 触碰「**降级无门禁**」：engine 纯度此前无门禁守护（A2 直接补）；删/改名须防「契约盲区」→ 本方案路由未动，不触发 `check_routes` 门禁（§10.5）。 |

### 10.5 A2 门禁的「差异化价值」（满足 AGENTS.md 门禁治理约定 2026-08-09）

> 现有 13 段门禁中**无一段 guards 分层/纯度**。现有 `check_routes`（路由↔契约）、`audit_unused_symbols`、`check_unused_styles` 三者对象互不相同（路由/符号/样式），本 A2 段对象为「**engine 层 import 边界**」，**与三者正交、不重复**。
> 价值：把 AGENTS.md 当前靠文档声明的「engine 无 I/O 纯函数」变成**可执行硬约束**，从根上阻断 P1-A 类泄漏复发（此类泄漏人工 review 极难发现，已实证泄漏 1 处）。
> 实现：新建 `scripts/check_engine_purity.py`（AST `ast.walk` 扫描 `app/engine/**/*.py`，违例打印 `file:line` + `exit 1`），在 `.githooks/pre-commit` 作为第 14 段接入，标注「新增段，差异化=分层边界守护」。

### 10.6 实施级联风险（须置顶）

- **B1 移动 `source_registry` 是破坏性改名**：5+ fetcher + `factor_registry.py:1267` 的 `from ..services.source_registry import` 必须**同批改为 `from ..core.source_registry import`**，否则 import 全崩。建议移动后跑 `python -c "import app.core.source_registry"` + 全量 pytest。
- **C1 删 `design_quality`**：`tests/test_design_quality_gate.py` 与 `verify_e2e.py:1755` 同时删引用，否则测试 import 失败。
- **D1 删 `_safe` 包装**：实施前置 `grep -rn "def _safe" app/fetchers/` 列出全部后统一改指 `run_sync`；`safe_call`/`safe_call_async` 短期保留（deprecated 别名），不强行改写 30 文件。
- **E1 拆 `portfolio_service`**：拆后须 `grep -rn "portfolio_service\."` 复核 `routers/portfolio.py`、`tasks/strategy_check_worker.py`、`scripts/verify_e2e.py` 的 import/调用全部可解析；`strategy_check` 迁到 `services/strategy_check.py` 时，`tasks/strategy_check_worker.py` 调用签名须同步。
- **不触发 `check_routes` 门禁**：本方案所有项均**不增删路由**，故 `api-contracts/` 无需改动；若实施时误动路由，须同批删契约条目（见 §6.2c 🔒）。
- **不触发 `audit_unused_symbols` 误报**：E2 删 `risk_controls.py:39` 本地归一化实现前，确认 `market_data_hub._normalize_regime` 为唯一活实现，避免删成调用方断裂。

### 10.7 多轮 review 记录（不实施，仅评审）

- **Round 1（自检，已完成）**：
  - 覆盖 5 类问题 + 8 项 checklist + 级联风险。
  - **核心修正（证伪初判）**：初判「删 `try_call`」经 grep 推翻——`try_call`（`source_registry.py:172`）被 3 测试文件（`test_data_source_fallback.py:175`、`test_regression.py:184`、`test_source_registry_optimizations.py:18`）覆盖、是熔断本体、生产经 `route()` 调用 → **改为保留，仅文档收敛**（不单列整改项，避免误删）。
  - **核心修正**：初判「`source_registry` 过度抽象」经 grep 推翻——8 fetcher 复用 `route()`，本体合理 → 改为 B1 仅修分层位置 + `_health` 泄漏。
  - 待补：`safe_call` 全量调用面（D1 实施前置）、E1 拆分函数归属表。
- **Round 2（重大项细化，已完成）**：
  - **E1 为最大项**（拆 2448 行文件），已细化 §10.3 函数归属表（报告集群/IO 集群/核心三向）。
  - **D1 收缩**：调用面探针显示 `safe_call`/`safe_call_async` 横跨 ~30 文件 → 不主张强删，改为「删 fetcher 内 `_safe` + deprecated 别名」低改动面方案。
  - **A2 门禁差异化**已明确（§10.5）。
  - **B1 importer 清单**已精确（5 fetcher + `factor_registry.py:1267`）。
  - 优先级复核：维持 P1（A1/A2/B1/E1/E2）/ P2（C1/D1）。
- **Round 3（终稿，已达成实施标准）**：
  - 补 D1 调用面探针（§10.1 P2-D）、E1 函数归属表（§10.3）。
  - 与 §8 交叉核对：确认本方案无项与 F10/F22–F33（正确性）、F1–F6（性能）重叠 → 已确认无重叠（§10.0 独立性）。
  - **结论：7 项整改（A1/A2/B1/C1/D1/E1/E2）均具备 file:line 证据 + 验收口径 + 级联风险清单，达到实施标准。等待用户"开始实施"指令，不写任何整改代码。**

> **当前状态：本节 Round 3 达成实施标准**。重大项 E1/B1 的「调用点清单」与「拆分函数归属表」已在 Round 2 细化；A2 门禁差异化已声明。达到实施标准前不写任何整改代码。

---

## 11. round20 未完项整合映射（2026-08-14 合并归档依据）

> **合并动作**：用户 2026-08-14 要求「把 round20 未做完的部分整合到 round23，然后归档 round20」。
> **核查结论（重要，纠正了「round20 仍有大量待办」的预设）**：round20 为**纯诊断文档**（自声明"本份只设计不实施"），但其 20 项问题在后续 round21/22/23 的**代码提交中已绝大多数落地**，并非"未做"。逐项的真实状态见下表——既非"全部待办"（反假完成：不得把已落地项冒充未做），也非"全空"（确有少数仍开放）。
> **归档结论**：round20 已被代码实现 + round23 跟踪双重覆盖，**无悬空待办**，可安全归档（见 §11.1）。

### 11.1 round20 20 项 → round23 / 代码 映射

| round20 项 | 级 | 真实状态 | round23 跟踪 | 代码落地证据 |
|---|---|---|---|---|
| P0-1 timeline 热态慢 | P0 | ✅ 已实施 | F34（已标记✅） | `routers/portfolio.py:553-660`（30s TTL+limit+列裁剪） |
| P0-2 home CLS 0.389 | P0 | 🔲 待实施 | F35（唯一净新增开放项） | — |
| P0-3 港美自选静默缺实时 | P0 | 🔲 待实施（已跟踪） | F21 + §2.3c | `routers/market.py` watchlist |
| P0-4 港股历史 K 线 | P0 | ✅ 已实施 | F36（已标记✅） | `fetchers/china_market.py:281-318,1688` |
| P0-5 LLM 超时 35→15s | P0 | ✅ 已实施 | §4（F7–F9） | `analysis/llm.py:648,715,1445` |
| P1-1 max_correlation 硬约束 | P1 | ✅ 已实施 | F37（已标记✅） | `engine/allocation_engine.py:1365`、`services/strategy_design.py:373-394` |
| P1-2 低相关措辞确定性 | P1 | ✅ 已实施 | F38（已标记✅） | `engine/rationale.py:108-113` |
| P1-3 KDJ 超买误判 BUY | P1 | ✅ 已实施 | F10 | `analysis/signal.py:73,105,155` |
| P1-4 ai_summary 重要性失效 | P1 | 🔲 待实施（已跟踪） | F28 | `services/market_data_hub.py:1705` |
| P1-5 美股历史 K 线 | P1 | ✅ 已实施 | F39（已标记✅） | `fetchers/china_market.py:292-297,311` |
| P1-6 信号一致性 | P1 | ✅ 已实施 | F10（同 P1-3） | `analysis/signal.py:155` |
| P1-7 候选池/板块动量 | P1 | ✅ 已实施 | —（代码层） | `engine/allocation_engine.py:320,427,639`、`services/strategy_design.py:337,738` |
| P1-8 规则引擎理由补全 | P1 | ✅ 已实施 | —（代码层） | `services/portfolio_service.py:1205,1457`、`services/strategy_design.py:409` |
| P1-9 因子 valid 率降级标注 | P1 | ✅ 已实施 | F12/F33 关联 | `services/strategy_design.py:787,795` |
| P2-1 死端点清理 | P2 | 🔲 待清理（已跟踪） | §6.1（🔒 同批删契约） | 0 生产调用方 |
| P2-2 遗留文件清理 | P2 | 🔲 待清理（已跟踪） | §6.2 | — |
| P2-3 新鲜度维度 | P2 | 🔲 待实施（已跟踪） | F24/F28 | news 时间戳/时区 §2.4 |
| P2-4 评分注释一致性 | P2 | ✅ 已实施 | F40（已标记✅） | `analysis/design_report.py:194` |
| P2-5 结构合理性检查 | P2 | ✅ 已实施 | —（代码层） | `engine/allocation_engine.py:1463` |
| P2-6 卫星欠配修复 | P2 | ✅ 已实施 | —（代码层） | `engine/allocation_engine.py:903,1123` |

### 11.2 合并结论

- **20 项中 13 项已在代码落地**（P0-1/4/5、P1-1/2/3/5/6/7/8/9、P2-4/5/6），带 `file:line` 真实调用点，非脚手架。
- **6 项由 round23 跟踪且仍未实施**（P0-2/F35、P0-3/F21、P1-4/F28、P2-1/§6.1、P2-2/§6.2、P2-3/F24），其中**仅 F35（home CLS）是 round20 真正净新增、且 round23 此前未覆盖的开放项**；其余 5 项 round23 原本已有对应 F/章节。
- **反假完成核对**：§8 的 F34/F36/F37/F38/F39/F40 原按"待实施"书写，本次据代码实证改为"✅已实施"——避免把已落地项冒充未做（AGENTS.md 反假完成 §1/§3）。
- **归档安全**：round20 全部 20 项均有归属（代码或 round23），无悬空待办 → 已 `git mv` 至 `docs/archived/round20-container-acceptance-diagnosis.md`，其跨引用已同步（见 §11.1 映射与本文末尾提交说明）。
