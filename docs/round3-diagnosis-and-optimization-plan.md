# ETF Surge — 第三轮全链路诊断与优化修复方案 (v1.0)

> 生成时间: 2026-08-01
> 环境: Docker (Python 3.14 + Node 24 Alpine + Redis 8)，prod profile 生产态
> 诊断方式: Docker 容器内运行 + 前后端性能诊断工具（PROFILE_WARMUP=1 pyinstrument/cProfile、Lighthouse 13.4、perf_diag）
> 状态: **诊断完成，方案待多轮 review 至实施标准（尚未实施）**

---

## 一、执行摘要

本次诊断在 Docker 生产态环境下对 ETF Surge 完成第三轮全链路评估，覆盖：构建部署、预热性能、组合设计/策略检查报告质量、A/HK/US 多市场行情分析、热点板块/自选/持仓信号/资讯/因子模型、前后端数据契约、前端 Lighthouse、后端全链路性能、测试防护体系。

### 核心结论

| 维度 | 状态 | 关键发现 |
|------|------|---------|
| 预热性能 | ⚠️ 需优化 | 10.6s（门禁 15s 内但主要耗时可消除） |
| 组合设计报告 | ⚠️ 数据准确性 bug | 指数涨跌幅放大 100 倍（0.72→72%） |
| 策略检查报告 | ❌ 严重 | LLM 超时降级后 `report_text` 为空 |
| 多市场行情 | ⚠️ 港股不可用 | 预热期 6 个数据源熔断误伤，港股 realtime 全 null |
| HK/US 研判报告 | ❌ 数据混入 | market_data 未按市场过滤，报告大谈 A 股 |
| 前后端契约 | ⚠️ 1 处断裂 | `sectors/heat` dict vs 前端 array |
| 因子模型 | ⚠️ Z04/Z06 未修 | etf_specific 10 因子无数据；IC 被全 0 批次覆盖 |
| 前端性能 | ⚠️ dashboard 未达标 | Lighthouse P60，CLS 0.538（门禁 0.1） |
| 后端性能 | ⚠️ 5 个慢端点 | factor-health 3.2s、realtime/portfolio 3.0s |
| 测试防护 | ❌ 6 类盲区 | 断言深度不足、降级视为成功、结构耦合退化等 |
| 历史问题清单 | ⚠️ 8/15 已修 | Z01/Z02/Z03/Z08/Z10/Z11/Z12/Z14 ✅；Z04/Z06/Z09/Z15 ⚠️/❌；Z07（LLM 错误率，429 现实现象仍存在但代码层分类监控已落地）、Z13（中文 URL 编码，客户端文档问题，非服务端 bug）、Z05（SSL 连接池，cProfile 显示未完全生效）|

### 问题清单总览（本轮 11 项 N + 4 项遗留 Z）

| 类别 | 数量 | 对应 ID |
|------|------|---------|
| 数据准确性（报告/行情） | 3 | N02（涨跌幅×100）、N04（HK/US 混 A 股）、N09（拼音搜索无数据） |
| 数据完整性（缺失/为空） | 3 | N01（策略检查报告空）、N06（IC 全 0 覆盖）、Z04（etf_specific 无数据） |
| 功能缺陷（熔断/断裂/超时） | 4 | N03（港股熔断）、N05（sectors/heat 断裂）、N07（自选 realtime null）、Z15（HK realtime 未覆盖） |
| 性能问题（预热/运行时/前端） | 5 | N08（预热 10.6s）、N10（dashboard CLS）、N11（echarts 打包）、Z06（IC 后台不累积）、Z09（zscore 假 PASS） |
| 测试防护缺口 | 6 | 见第四章 4.1 节（6 类根因） |

---

## 二、诊断环境与方法

### 2.0 15 项诊断动作 ↔ 文档章节映射

| # | 诊断动作 | 执行结果 | 对应章节 |
|---|---------|---------|---------|
| 1 | Docker 构建前后端 + 回收老镜像 | ✅ 成功，旧镜像自动回收 | 附录 A |
| 2 | Docker 启动前后端 | ✅ 3 容器 Up，/health 200 | 附录 A |
| 3 | 后端预热性能诊断 | ⚠️ 10.6s，见 N08 | 附录 A / N08 |
| 4 | 组合设计 + on_exchange 策略检查 + 报告审阅 | ⚠️ 设计正常、策略检查报告空（N01）、涨跌幅 bug（N02） | N01/N02 |
| 5 | A/HK/US 行情分析全链路 | ⚠️ 港股熔断（N03）、HK/US 报告混 A 股（N04）、US 投顾质量良好 | N03/N04 |
| 6 | 热点板块与个股加载 | ✅ 11 板块 + 领涨股完整，热度 Tab 断裂（N05） | N05 |
| 7 | 自选功能 | ⚠️ A 股添加正常、港股 422（N03 连锁）、realtime 间歇 null（N07） | N07 |
| 8 | 持仓技术分析与综合信号 | ✅ indicators 完整、信号 BUY/SELL 分布合理、与策略检查一致 | 附录 A |
| 9 | 资讯等级划分与智能分析 | ✅ 1-5 星分布合理、AI 影响分析质量良好、个别星等可优化 | 附录 A |
| 10 | 因子模型页面 | ⚠️ Z01/Z03 已修、Z04 未修、IC 全 0 覆盖（N06） | N06 |
| 11 | 前后端数据断裂排查 | ❌ 1 处确认（sectors/heat） | N05 |
| 12 | docs 问题清单核对 | ⚠️ 8/15 已修，见执行摘要 | 第三章 🅿️2 |
| 13 | 前端 Lighthouse | ⚠️ dashboard P60/CLS 0.538（N10）、echarts 打包（N11） | N10/N11 |
| 14 | 后端全链路性能 | ⚠️ 46/49，5 慢端点 | 附录 A |
| 15 | 防护体系缺口分析 | ❌ 6 类根因 | 第四章 |

### 2.1 环境

- Docker Desktop 29.6.2，`docker compose --profile prod` 生产态（backend + nginx frontend + redis）
- backend: Python 3.14-slim，uvicorn 单进程
- frontend: Node 24 Alpine 构建产物，nginx stable-alpine 托管（80 端口）
- 数据库: SQLite (`/app/data/portfolio.db`，volume 挂载 `./data`)

### 2.2 诊断工具

| 工具 | 用途 | 关键输出 |
|------|------|---------|
| PROFILE_WARMUP=1 + WarmupProfiler | 预热阶段 pyinstrument + cProfile + 分段计时 | `warmup_timing.json` / `warmup_pyinstrument.txt` / `warmup_cprofile.txt` |
| Lighthouse 13.4 (npx) | 前端性能评分（desktop preset） | `logs/lighthouse/*.json` |
| perf_diag.py | 后端全链路 49 端点计时 | `perf_diag_results.json` |
| verify_e2e.py | 端到端功能门禁（分模块） | 44+53+31+4 PASS / 4 FAIL |
| 容器内直调 | 绕过熔断器验证数据源真实可用性 | tencent 港股 00700 直调正常 |

---

## 三、问题清单与根因分析

### 🅿️0 — 阻塞性/严重问题（本轮新发现）

#### N01: 策略检查报告 `report_text` 为空（高）

| 属性 | 值 |
|------|-----|
| 现象 | 策略检查任务 status=completed，但 `report_text` 为空字符串、`holdings_analysis=[]`、`covered_by_llm=0`、10 条建议全部 `source=rule` |
| 复现 | `POST /portfolio/strategy-check-async {portfolio_type: on_exchange}` → 轮询至 completed → `GET /strategy-checks/205` |
| 根因 | ① LLM 调用 `asyncio.wait_for(20s)` 超时（llm.py:1177，实测含 fallback 重试共 ~25s）→ 规则引擎兜底；② 兜底路径（llm.py:1186-1193）只返回 `summary + 空 suggestions/holdings_analysis/risk_warnings`，`report_text` 未生成（strategy_check_worker.py:154 落库 `""`）；③ LLM 供应商 opencode_zen 429 配额耗尽（Retry-After 12.7h）放大触发概率 |
| 影响 | 前端"策略检查"Tab 显示空白报告，用户只能看到 hold 建议，无任何投资分析 |
| 涉及文件 | `backend/app/analysis/llm.py:1171-1193`（超时 20s + 兜底）、`backend/app/tasks/strategy_check_worker.py:154`、`backend/app/analysis/prompts/v1/strategy_check.md` |

**修复规格（v1）**：
1. `llm.py` 兜底路径生成结构化 Markdown 正文（至少包含：市态结论、逐标的因子/信号/漂移分析、风险提示、操作建议），复用 `strategy_check` 已收集的 `holdings_analysis` 数据；
2. LLM 超时从 20s 提升到 60s，并增加 fallback provider（deepseek）自动重试（确认现有 retry 链路已覆盖 `strategy_check` agent）；
3. `report_text` 为空时任务应标记为 `failed` 而非 `completed`（诚实收敛状态）；
4. e2e 增加断言：`report_text` 非空且长度 > 500。

#### N02: 设计报告指数涨跌幅放大 100 倍（高）

| 属性 | 值 |
|------|-----|
| 现象 | 报告称"上证指数涨72.0%"（实际 +0.72%）、"沪深300涨85.0%"（实际 +0.85%）；但深证成指 2.21 正确写"涨2.2%" |
| 根因 | `llm.py::_fmt_pct()` 用 `abs(v) > 1` 启发式判断单位：change_pct=0.72 被误判为小数比例（0.72→×100=72%）；而数据管道中 A 股指数 change_pct=0.72 本身就是百分数（0.72%） |
| 影响 | 专业投资者看到 72% 涨幅必然质疑报告可信度；报告同时称"涨72%"又判 range_bound，逻辑自相矛盾 |
| 涉及文件 | `backend/app/analysis/llm.py:1483-1492`（`_fmt_pct`）、数据管道 `market_service.py`（指数 change_pct 单位） |

**修复规格（v1）**：
1. **统一数据单位**：`market_service.py` 指数 realtime 的 change_pct 统一为"百分数值"（0.72 = 0.72%），文档注释明确；
2. `_fmt_pct()` 改为显式单位参数或直接透传（不再用 abs>1 启发式）——对已知百分数字段不再 ×100；
3. 新增单测 `tests/test_llm_prompt_format.py`：`_fmt_pct(0.72) == "0.7%"`、`_fmt_pct(-5.4) == "-5.4%"`；
4. 设计报告 prompt 增加"指数涨跌幅已为百分数，直接引用勿换算"指令（prompt 防御）。

#### N03: 港股实时行情全 null（高）

| 属性 | 值 |
|------|-----|
| 现象 | `GET /market/realtime/00700?asset_type=HK` 返回 null；`realtime/batch` HK 返回 []；自选添加港股 422"无法解析该标的" |
| 根因 | 预热期间 sina/tencent/dongfang/mootdx 等 6 个源连续失败触发熔断（`SourceHealth.record_failure` 阈值 3），熔断窗口内 `registry.route` 跳过所有 HK provider；**容器内直调 `_tencent_realtime(['00700'],'HK')` 返回正常数据（475.2 +0.72%）**——数据源可用，被熔断器误伤 |
| 影响 | 港股行情、自选、技术分析全部不可用；用户无法查看港股标的 |
| 涉及文件 | `backend/app/services/source_registry.py`（熔断逻辑）、`backend/app/fetchers/china_market.py`（HK 降级链） |

**修复规格（v1）**：
1. **熔断与空结果分离**：`route()` 中"provider 返回空列表"不应计入失败计数（数据源正常但无该标的 ≠ 源故障）；仅 HTTP 4xx/5xx、网络异常、超时计入；
2. 预热期保护：预热数据拉取失败不计入熔断（`operation=="warmup"` 或降低阈值）；
3. 熔断恢复探测：冷却结束后首个请求应为 half-open 探测（成功即关闭熔断），当前 `available()` 已实现但需确认；
4. e2e 增加 `section_hk_realtime`：断言 `GET /market/realtime/00700?asset_type=HK` 非 null（当前缺失）。

#### N04: HK/US 研判报告混入 A 股数据（高）

| 属性 | 值 |
|------|-----|
| 现象 | `POST /analysis/llm-report/stream {market: HK}` 生成的报告大谈"创业板指涨3.06%、上证50 -0.12%"；US 报告同样以 A 股指数为主，仅顺带提及恒生/纳指 |
| 根因 | `llm_context.py` 第 3 步 `index_realtime` **已按市场过滤**（F1-4，53-68 行，有 `tests/test_llm_context_market.py` 覆盖）；真正的泄漏在第 5 步 `market_data = get_all_realtime()`（全量 A 股实时）**未按 market 过滤**；`analysis.py::llm_report_stream`（~389 行）对 `market_data` 的过滤条件只按 `asset_type in ("index","futures")`，A 股指数全部放行；`_build_market_overview` 硬编码"A股市场"标题 |
| 影响 | HK/US 市场研判严重失实，专业投资者无法使用 |
| 涉及文件 | `backend/app/services/llm_context.py`、`backend/app/routers/analysis.py`、`backend/app/analysis/llm.py::_build_market_overview` |

**修复规格（v1）**：
1. `build_full_context` 的 `market_data` 按 `market` 过滤（HK → HK 标的/指数，US → US 标的/指数）；
2. `_build_market_overview` 标题动态化（`### {market}市场`），指数分组按 region 注入；
3. e2e 增加 `section_market_isolation`：HK 报告必须包含恒生指数数据且不得包含创业板/上证50（内容断言）。

---

### 🅿️1 — 高优先级

#### N05: 前后端数据断裂 `sectors/heat`（中）

| 属性 | 值 |
|------|-----|
| 现象 | 后端 `GET /market/sectors/heat` 返回 `{"items":[...],"total":N}`（dict），前端 `SectorHeatMap.vue:216` `Array.isArray(resp.data)` 期望数组 → `dataList=[]`，板块热度 Tab 空白 |
| 根因 | 后端响应结构（dict）与前端契约（array）不一致，`verify_e2e.py section_api_5xx_check` 只断言 HTTP 200 不断言结构 |
| 涉及文件 | `backend/app/routers/market.py:468`（sectors_heat）、`frontend/src/components/market/SectorHeatMap.vue:216` |

**修复规格（v1）**：二选一（推荐后端归一化为数组，与 hot-plates 保持一致）：`sectors_heat` 返回 `list[dict]`；前端 `dataList.value = Array.isArray(resp.data) ? resp.data : (resp.data?.items ?? [])` 双兼容。

#### N06: IC 数据被全 0 批次覆盖（中）

| 属性 | 值 |
|------|-----|
| 现象 | `/factors/active` 33 因子中 30 个 `no_data`；`/factors/ic` 在 factor-health 请求后出现 26 条但后台不再累积；日志 `ConstantInputWarning: An input array is constant` |
| 根因 | `factor_registry.compute()` 某批次因子值全为常量（数据源异常）→ `compute_periodic_ic` 返回全 0 批次 → `self._last_ic_batch = ic_batch` **无条件覆盖**之前的有效批次；`ic_persistence` 循环读 `_last_ic_batch`，全 0 批次导致 `abs(val)<0.0001` 全部跳过 → 永久失去 IC 数据 |
| 涉及文件 | `backend/app/factors/factor_registry.py:1214-1239`、`backend/app/factors/ic_tracker.py:69-85` |

**修复规格（v1）**：
1. `compute_ic` 对常量输入（`vals.nunique()==1` 或 `rets.nunique()==1`）返回 `None`/NaN 而非 0，调用方跳过该 code；
2. `_last_ic_batch` 覆盖策略：仅当新批次非空且含有效 IC（非 0 占比 > 阈值）时覆盖；否则保留旧值并告警；
3. `ic_persistence` 保存前过滤 NaN/0 值（已有 `abs<0.0001 continue`，需补充 NaN）；
4. 单测：`tests/test_ic_tracker.py` 增加常量输入场景。

#### N07: 自选 A 股 realtime 间歇性 null（中）

| 属性 | 值 |
|------|-----|
| 现象 | watchlist 列表 A 股标的 `realtime=null`（SPY 正常）；直接 `GET /market/realtime/510050` 有时 null 有时正常 |
| 根因 | `market_service._call(fetch_a_stock_realtime, symbol)` 8s 超时；容器内直调返回正常（3.033）但经 API 层间歇超时；叠加 mootdx 熔断导致降级链变长 |
| 涉及文件 | `backend/app/services/market_service.py:32-46`（`_call` 超时 8s） |

**修复规格（v1）**：① `_call` 超时按 asset_type 区分（HK/US 可放宽到 12-15s）；② 增加同步超时结果短缓存（3s TTL）避免重复 8s 等待；③ watchlist enrichment 串行改为 `asyncio.gather` 并发。

#### N08: 预热性能 10.6s 未达目标（中）

| 属性 | 值 |
|------|-----|
| 现象 | 预热总耗时 10571ms：`warmup_market_cache` 6378ms、`warmup_global_indices` 4026ms |
| 根因（cProfile 实证） | ① `fetch_fund_nav` 12 次调用累计 7.5s、**SSL 握手 36 次 3.2s**（与 Z05"已修连接池复用"矛盾——cProfile 显示仍新建连接）；② `fetch_cailian_telegraph` 单次 3.5s（levistock 财联社分页抓取）；③ `fetch_margin_balance` 2.5s；④ LOG_LEVEL=DEBUG 下 `logging.debug` 1.87s |
| 涉及文件 | `backend/app/fetchers/china_market.py`（fetch_fund_nav/_session）、`backend/app/fetchers/levistock_fetcher.py:160`、`backend/app/core/logging.py` |

**修复规格（v1）**：
1. `fetch_fund_nav` 强制复用模块级 `requests.Session()`（核实 Z05 修复是否被回退/未生效）；
2. `fetch_cailian_telegraph` 抓取页数限制（当前疑似全量分页），或移出预热改为按需；
3. 预热期 `LOG_LEVEL=INFO` 覆盖 DEBUG（容器内 `LOG_LEVEL=DEBUG` 导致 1.9s 日志开销）；
4. 验收：预热 < 5s。

#### N09: 拼音搜索无数据（中）

| 属性 | 值 |
|------|-----|
| 现象 | `search?keyword=guizhou/gzmt/maotai` 返回 0；诊断时 `instruments` 表 1544 条全部为 ETF（`A stocks=0`），个股拼音数据缺失 |
| 根因 | `sync_instruments.py::collect_all()`（71-90 行）**已实现** A 股个股同步（`stock_zh_a_spot_em` → `asset_type="stock"` 含 pinyin/first_letter），但诊断时表内无个股——最可能是**上次同步运行时 akshare 处于熔断态（附录 C 显示 akshare open），`collect_all` 的 gather 中个股段异常被吞掉**（81-83 行仅打印 WARN 后 continue），全量替换逻辑（105 行 `delete(Instrument)` 后 add_all）把表清成只剩 ETF |
| 影响 | 前端搜索框输入拼音（如"gzmt"）无自动补全 |
| 涉及文件 | `backend/scripts/sync_instruments.py:71-90,104-110`（同步失败静默 + 全量替换）、`backend/app/routers/market.py::search` |

**修复规格（v1）**：
1. `collect_all` 对 akshare 失败的段记录 ERROR 日志并在同步报告中统计各段行数；全量替换前校验至少一段成功，否则保留旧表（避免"全清空只剩 ETF"）；
2. search 对 A 股拼音降级：instruments 无个股命中时 fallback levistock 拼音接口；
3. 同步改为增量 upsert（保留已有行，失败段不删）；
4. e2e 增加 `section_search_pinyin`（`guizhou` 应命中贵州茅台或返回非空）。

#### N10: 前端 dashboard CLS 0.538 严重超标（中）

| 属性 | 值 |
|------|-----|
| 现象 | Lighthouse dashboard: CLS 0.538（`.lighthouserc.js` 硬门禁 0.1，超 5 倍）；Performance 60 恰在 0.6 门禁边缘 |
| 根因 | 异步数据加载后图表/卡片尺寸变化导致布局抖动（骨架屏与真实内容高度差）；PWA/图表容器未预留尺寸 |
| 涉及文件 | `frontend/src/views/Dashboard.vue`、`frontend/src/components/dashboard/*.vue` |

**修复规格（v1）**：① 图表容器固定 min-height；② 数据加载中占位高度与真实内容一致；③ 字体/图标加载 preload。

#### N11: 前端 echarts 全量打包（低）

| 属性 | 值 |
|------|-----|
| 现象 | `vendor-echarts.js` 558.88KB（gzip 184KB），为最大传输资源（占 portfolio 349KB 传输的一半）；Lighthouse "Reduce unused JavaScript" 建议省 600ms |
| 根因 | vite.config.js 将 echarts/zrender 整体 chunk 化，未按需 tree-shaking；部分组件 `import VChart from 'vue-echarts'` 全量引入 |
| 涉及文件 | `frontend/vite.config.js:77`、`frontend/src/components/analysis/ChartPanel.vue` 等 |

**修复规格（v1）**：统一 `echarts/core` 按需注册（charts/components/renderers 显式导入），预计可减半；保留 vendor-echarts 分 chunk 但体积降至 ~250KB。

---

### 🅿️2 — 中优先级（历史清单遗留）

| ID | 状态 | 问题 | 修复要点 |
|----|------|------|---------|
| Z04 | ❌ 未修 | etf_specific 10 因子全无数据（`no_data_count=10`） | 实现 10 个 ETF 特有因子数据源（折溢价/份额/跟踪误差等），见旧方案 P0 |
| Z06 | ⚠️ 部分 | IC 无后台累积（被全 0 批次覆盖） | 见 N06 修复规格 |
| Z09 | ⚠️ 假 PASS | e2e zscore 检查因 factor-health 结构变化静默退化 | 见 §4.3 门禁调整（结构断言 + 真 zscore 校验） |
| Z15 | ⚠️ 部分 | HK realtime 未覆盖、US ETF 搜索偶发超时 | 新增 `section_hk_realtime`；US 搜索超时调大 gate |

---

## 四、测试防护体系补强方案（§2.0 第 15 项 / round2 第 13 项任务结论）

### 4.1 为什么测试防护体系未识别这些问题（6 类根因）

| # | 根因 | 证据 | 修复方向 |
|---|------|------|---------|
| 1 | **断言深度不足**：e2e 只验 HTTP 状态码/字段存在，不验结构契约、内容语义 | sectors/heat dict vs array 仍 PASS；HK/US 报告混 A 股仍 PASS | verify_e2e 增加结构/内容断言层 |
| 2 | **降级路径视为成功**：LLM 超时 rule fallback 被 e2e 当 PASS | 策略检查 report_text 空仍 PASS | 降级=WARN/FAIL，报告非空为硬门禁 |
| 3 | **结构耦合退化**：断言与被测响应结构强耦合，改结构后静默退化 | zscore 检查对 symbols 结构无断言仍 PASS | 断言前先校验响应结构 |
| 4 | **请求驱动掩盖**：e2e 检查本身触发 compute，掩盖后台缺陷 | IC 端点 26 条在 e2e 触发后出现，后台无累积 | 后台循环独立验证（读 DB 而非请求驱动） |
| 5 | **门禁可跳过**：预热计时检查在 PROFILE_WARMUP 未设置时 SKIP | prod 部署天然跳过预热门禁 | 门禁默认启用，SKIP 需显式白名单 |
| 6 | **单测/集成分层盲区**：1045 单测全过但问题全在集成层 | LLM prompt 格式、熔断行为、契约断裂均无单测 | 新增 prompt 格式化/熔断/契约单测 |

### 4.2 verify_e2e.py 新增模块（v1 规格）

```python
def section_hk_realtime(host, port):
    """港股实时行情（N03 防护）"""
    r = requests.get(f"{BASE}/market/realtime/00700?asset_type=HK", timeout=15)
    check("港股实时行情非空", r.status_code == 200 and r.json() is not None)

def section_report_nonempty(host, port):
    """策略检查报告非空（N01 防护）"""
    # 断言 report_text 长度 > 500，否则 FAIL

def section_market_isolation(host, port):
    """HK/US 报告市场隔离（N04 防护）"""
    # HK 报告含恒生、不含创业板/上证50

def section_contract_shape(host, port):
    """前后端契约结构（N05 防护）"""
    # sectors/heat 断言 list（或与前端契约一致的结构）

def section_ic_persistence(host, port):
    """IC 后台累积（N06 防护）"""
    # 不触发 compute，直接查 DB FactorICRecord 数量 > 0

def section_search_pinyin(host, port):
    """拼音搜索（N09 防护）"""
    # search?keyword=guizhou 应命中贵州茅台或返回非空
```

### 4.3 门禁调整

| 门禁 | 现状 | 调整为 |
|------|------|--------|
| 预热时间 | PROFILE_WARMUP 未设置时 SKIP | 默认启用，>15s FAIL |
| LLM 降级 | WARN 不阻断 | 降级时对应报告断言 FAIL |
| factor-health | 200 + ok | + 结构断言（symbols 格式）+ 真 zscore 校验 |
| 响应契约 | 仅状态码 | + 结构/内容断言层 |

---

## 五、实施优先级

```
┌─────────────────────────────────────────────────────────────┐
│ 第一梯队（P0 — 立即实施，预计 2 人日）                       │
├─────────────────────────────────────────────────────────────┤
│  N01: 策略检查报告空         修复: 半日（兜底正文+超时+降级FAIL）│
│  N03: 港股熔断误伤           修复: 半日（空结果不计失败）       │
│  N04: HK/US 报告混 A 股      修复: 半日（market 过滤+标题动态）  │
│  N02: 涨跌幅 100 倍 bug      修复: 2小时（单位统一+单测）       │
├─────────────────────────────────────────────────────────────┤
│ 第二梯队（P1 — 本周内）                                      │
├─────────────────────────────────────────────────────────────┤
│  N05: sectors/heat 断裂      修复: 1小时                       │
│  N06: IC 全 0 覆盖           修复: 半日                        │
│  N07: 自选 realtime 间歇 null 修复: 半日（超时分级+并发）       │
│  N08: 预热 10.6s             修复: 半日（Session 复用+日志级别） │
│  N09: 拼音搜索               修复: 半日（同步个股数据）          │
├─────────────────────────────────────────────────────────────┤
│ 第三梯队（P2 — 下个迭代）                                    │
├─────────────────────────────────────────────────────────────┤
│  N10: dashboard CLS 0.538    修复: 半日（容器固定尺寸）          │
│  N11: echarts 按需打包       修复: 半日（tree-shaking）         │
│  Z04: etf_specific 因子数据   修复: 1 日                        │
├─────────────────────────────────────────────────────────────┤
│ 持续（P3 — 随迭代推进）                                      │
├─────────────────────────────────────────────────────────────┤
│  4.2 节 e2e 新模块 / 4.3 节门禁收紧                           │
└─────────────────────────────────────────────────────────────┘

实施必须遵循「先写 API 契约/单测 → 改代码 → 跑 verify_e2e.py 全 PASS →
commit」流程（AGENTS.md）。所有修复先写失败单测验证预期行为。
```

---

## 六、附录

### A. 测试运行记录

- 后端预热: 10.57s（目标 <5s，见 N08）
- 组合设计: 40.1s 引擎 + LLM 报告 90s（429 限流期间）
- 策略检查: LLM 20s 超时（含 fallback 重试实测 ~25s）降级（N01）
- 全链路 e2e: 44+53+31+4 PASS / 4 FAIL（3 个 405 为 perf_diag 脚本用 GET 调 POST 接口的误报、1 个 shared_executor 峰值；与 5 个慢端点无重叠——慢端点是 HTTP 200 但 >1s 的 5 个端点）
- Lighthouse: dashboard P60 / market-analysis P97 / portfolio P79
- 后端 perf_diag: 46/49，5 个慢端点 >1s（factor-health 3.2s / realtime-portfolio 3.0s / stock-hot-rank 1.9s / indices-global 1.3s / watchlist 1.0s）
- 单测: 1045 passed / 8 skipped

### B. LLM 供应商状态

- opencode_zen: 429 配额耗尽（Retry-After 12.7h），流式/非流式均受影响
- deepseek: fallback 可用但慢
- 影响面: 策略检查（N01）、symbol-analysis 流式超时、ai_summary 覆盖率

### C. 数据源熔断状态（诊断时点）

| 源 | 状态 | 备注 |
|----|------|------|
| mootdx | open | 预热期触发，cooldown 600s |
| sina / tencent | open | 预热期触发（N03 根因） |
| dongfang | open | 预热期触发 |
| sina_history | open | 预热期触发 |
| akshare | open | 预热期触发 |
| push2delay.eastmoney | closed ✅ | A 股主力源正常 |
| twelvedata / finnhub | closed ✅ | 美股正常 |

### D. 修订记录

| 版本 | 日期 | 修改内容 |
|------|------|---------|
| v1.0 | 2026-08-01 | 第三轮全链路诊断完成，11 项新问题（N01-N11）+ 历史清单核对 + 防护体系 6 类根因，形成优化修复方案初稿 |
