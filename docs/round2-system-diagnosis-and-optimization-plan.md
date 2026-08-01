# ETF Surge — 第二轮全链路诊断与优化方案

> 生成时间: 2026-07-31
> 环境: Docker (Python 3.14-slim + Node 24 Alpine + Nginx + Redis 8)
> 执行范围: 15 项全链路验证（步骤 1-15，见 §0 索引表）
> 状态: v1.2（已完成三轮 review，达到实施标准）

---

## 〇、步骤 × 章节 索引

| 步骤 | 内容 | 章节 | 状态 |
|:---:|------|------|:---:|
| 0 | Docker 构建镜像 + 回收老镜像 + 启动 prod 栈 | §2 前置 | ✅ 完成（含 2 个阻断 bug 修复） |
| 1 | 后端预热性能诊断 | §2.1 | ✅ |
| 2 | 组合设计 + 策略检查 + 报告审阅 | §3 | ✅（发现因子数据不一致等） |
| 3 | A/港/美股行情分析全链路测试 | §4 | ✅（market 参数失效等） |
| 4 | 热点板块/个股加载验证 | §5.1 | ✅ |
| 5 | 自选功能验证 | §5.2 | ✅（港股行情不通） |
| 6 | 持仓技研与综合信号评估 | §5.3 | ✅（akshare 熔断窗口技研空） |
| 7 | 资讯分级 + AI 智能分析评估 | §5.4 | ✅（分级不合理） |
| 8 | 因子模型页面评估 | §5.5 | ✅（7 no_data） |
| 9 | 前后端数据断裂排查 | §6 | ✅（6 个断裂点） |
| 10 | system-diagnosis-and-optimization-plan.md 问题清单验证 | §7 | ✅（12/15 已修或部分修） |
| 11 | 前端 Lighthouse 评分与性能诊断 | §2.2 | ✅（首页 60 分） |
| 12 | 后端全链路性能诊断 | §2.3 | ✅（组合计算 8.2s） |
| 13 | 测试防护体系失效分析 | §8 | ✅（6 类盲区） |
| 14 | 汇总文档 + 多轮 review | 本文档 | 🔄 进行中 |
| 15 | 回收容器进程 | 待执行 | ⏳ |

## 一、执行摘要

本轮对 ETF Surge 执行了 15 步全链路诊断，全程在 Docker prod 形态（nginx + backend + redis）下运行。

### 1.1 核心结论

| 维度 | 状态 | 说明 |
|------|------|------|
| 镜像构建与启动 | ✅ 修复 2 个阻断 bug | `config.py` extra_forbidden + prod 容器 `DATABASE_URL` 指向 Windows 路径（空库） |
| 预热性能 | ✅ 1.77s | 历史 38s → 3s → 1.77s，主瓶颈为全球指数/新闻串行网络 I/O |
| 组合设计 | ✅ 3 套方案 | 结构完整但现金仓位 22-32% 偏高、因子数据与实际指标不一致 |
| 策略检查 | ⚠️ LLM 超时降级 | report_text 为空，规则引擎兜底（Z07 持续） |
| 多市场分析 | ⚠️ 市场参数失效 | market=HK/US 仍输出 A 股数据；AI 投顾上下文全缺失 |
| 前后端断裂 | ❌ 6 个断裂点 | **生产模式 WebSocket 全链路 404**（nginx 缺 upgrade 代理）最严重 |
| 问题清单 Z01-Z15 | ✅ 12/15 已修或部分修 | Z04 未达标（etf_specific 仍 4 个 no_data）、Z07/Z11 部分改善 |
| 前端性能 | ⚠️ 首页 60 分 | CLS 0.538、TBT 410ms、3 个 8 秒级慢 API |
| 后端性能 | ⚠️ 组合计算 8.2s | calculate/pnl-history 串行行情调用，数据源熔断放大 |
| 测试防护 | ❌ 6 类盲区 | 拓扑/环境/内容/数据源运行时/时序/脚本卫生 |

### 1.2 本轮最重要发现（Top 5）

1. **prod 容器使用空数据库**：`backend/.env` 的 `DATABASE_URL` 是 Windows 绝对路径，prod 服务经 `env_file` 注入后 Linux 容器解析无效，所有业务表（instruments/持仓/自选）落到容器内新建的空库 → 搜索默认分支空、持仓全无、自选无行情。**已修复**（docker-compose 覆盖为容器路径 + `config.py extra="ignore"`）。
2. **生产模式 WebSocket 全链路断裂**：前端连接 `/api/v1/ws/*`，后端路由存在，但 nginx 只配置了 `location /api`（无 upgrade 头）与 `location /ws`，缺少 `/api/v1/ws` 的 WebSocket 代理 → 实时行情推送、任务通知、设计报告推送在生产环境全部失效（Lighthouse 控制台可见 404 握手失败）。
3. **A 股技术分析链路依赖单一数据源**：历史 K 线 `fetch_history` 空时降级 `get_k_data`（akshare），akshare 熔断时 history/indicators/signal/chart 全线 `insufficient_data`（本次实测捕捉到该窗口）。
4. **设计引擎因子数据与实际指标不一致**：设计报告称 562320 "RSI 2.4 超卖、信号偏多"，实际 RSI=65.3、signal=hold；589720 设计标"信号偏多"实际 signal=sell(-1.5)。方案 rationale 与真实技术面矛盾。
5. **LLM 上下文数据缺失与市场参数失效**：`llm-advice` 回答"所有字段均为暂无/未知"；`llm-report` 传 `market=HK/US` 仍输出 A 股数据；`symbol-analysis` 技术指标空、历史 K 线无；`sector-analysis` 半导体板块成分股错位（返回软件股）。

---

## 二、测试配置与性能诊断工具

### 2.1 后端预热性能诊断（步骤 1）

- 工具：内置 `WarmupProfiler`（cProfile + pyinstrument + 分段计时），`PROFILE_WARMUP=1` 启用（已写入 `backend/.env`，随 env_file 注入）。
- 启用前发现阻断 bug：`Settings` 为 `extra_forbidden`，新增环境变量 `PROFILE_WARMUP` 导致启动崩溃 → 修复 `config.py` 增加 `extra="ignore"`。
- 结果：

| 阶段 | 耗时 | 占比 |
|------|------|------|
| warmup_global_indices | 1468.7ms | 83% |
| init_db | 139.9ms | 8% |
| redis_init | 80.3ms | 5% |
| warmup_market_cache | 58.9ms | 3% |
| warmup_etf_cache | 17.5ms | 1% |
| **总计** | **1765ms** | |

- 诊断：主瓶颈为全球指数 + 新闻的**串行同步网络请求**（`run_sync` 线程池逐源拉取，cProfile 显示 refresh_news 1.595s/23 次 requests.get、SSL context 重复创建 23-26 次）。优化方向：指数/新闻 `asyncio.gather` 并行化、连接池复用。

### 2.2 前端 Lighthouse 评分（步骤 11）

工具：Lighthouse 13.4.1（Chrome headless），对 Docker nginx 形态 4 个核心页面评分：

| 页面 | Performance | Accessibility | Best-Practices | SEO | 关键指标 |
|------|:---:|:---:|:---:|:---:|------|
| `/`（Dashboard） | **60** | 96 | 92 | 91 | FCP 2.0s / LCP 3.2s / TBT 410ms / **CLS 0.538** |
| `/market-analysis` | **97** | 96 | 96 | 91 | FCP 1.5s / LCP 2.4s |
| `/portfolio-analysis` | **76** | 82 | 92 | 91 | FCP 2.0s / LCP 3.9s |
| `/news` | **96** | 94 | 96 | 91 | FCP 1.4s / LCP 2.0s |

首页问题定位（`lh_details`）：
- **3 个 8 秒级慢 API**：`pnl-history` 8528ms、`calculate off_exchange` 8287ms、`calculate on_exchange` 8257ms（Dashboard 首屏串行触发）
- **控制台错误**：`Market WS 发生错误` + `ws://localhost/api/v1/ws/portfolio` 握手 404（WS 断裂）
- **CLS 0.538**：summary-grid / nav-status 在数据异步到达后布局偏移
- **TBT 410ms / 主线程 2.4s**：echarts 等大库 JS 执行

### 2.3 后端全链路性能诊断（步骤 12）

perf_diag 49 端点扫描：**46/49 通过**（3 个 405 为脚本用 GET 调 POST 端点，非后端缺陷）。

| 慢端点 | 耗时 | 根因 |
|--------|------|------|
| `/portfolio/calculate` (on/off_exchange) | 8257-8287ms（约 8.2s） | 组合计算对每只持仓串行调实时行情 + 历史 K 线 |
| `/portfolio/pnl-history` | 8528ms | 同上，跨多期计算 |
| `/market/realtime/portfolio` | 1886-4470ms | 依赖单只 A 股行情降级链（mootdx 熔断时慢） |
| `/market/watchlist` | 1071-2327ms | 逐条目行情填充 |
| `/market/indices/global` | 1425-1530ms | 多源串行拉取 |

---

## 三、组合设计与策略检查审阅（步骤 2）

### 3.1 执行结果

- `POST /portfolio/design-async`（balanced/50 万/A 股）：completed，产出 **3 套方案**（防御/平衡/进攻），每套含 core/satellite/defense/cash 四层、多因子评分、入选理由，权重和 = 1.0，无占位符残留。
- `POST /portfolio/strategy-check-async`（`portfolio_type=on_exchange`）：completed，针对场内 **10 只标的**（159338 中证A500ETF 20%、518880 黄金ETF 13%、510880 红利 8%、512000 券商 8% 等），产出按标的建议（hold 为主，规则引擎）。

### 3.2 报告质量审阅（结合最新行情逐项核对）

| 维度 | 结论 | 证据 |
|------|------|------|
| 逻辑性 | ✅ 合格 | 四层结构清晰（核心 40%/卫星 25-35%/防御 3%/现金 22-32%），层预算不超 |
| 可读性 | ✅ 合格 | design_text 7KB，含方案对比总览、每标的入选理由 |
| 数据完整性 | ❌ 缺口 | `market_context.index_realtime` 为空；design_text"今日涨跌"列为 `—` |
| 准确性 | ❌ **严重** | 562320 设计称 RSI 2.4 超卖/信号偏多，实际 RSI=65.3 signal=hold；589720 设计标偏多，实际 sell(-1.5) |
| 投资认知 | ⚠️ 存疑 | 防御型方案配置科创创新药/科创芯片卫星层（12-13%），风格匹配度差 |
| 方案合理性 | ⚠️ 现金偏高 | 防御 32% / 平衡 27% / 进攻 22% 现金仓位（Z11 残余） |
| 风格匹配 | ⚠️ 部分 | regime=range_bound + 情绪中性下 3 套方案分层正确，但防御型含高波动科创主题 |

次要问题：design_text 标题"## 一、三种方案详解"重复（模板拼接）；策略检查 LLM 超时降级规则引擎（`report_text` 为空）。

### 3.3 任务失败定位

两任务均 completed（未失败）。策略检查内部 LLM 超时（summary 标注"LLM 分析超时…规则引擎兜底"），结合性能诊断归因于 Z07（LLM 429 限流，Retry-After 长达 8 小时），属既有延期项而非本轮新缺陷。

---

## 四、多市场行情分析测试（步骤 3）

### 4.1 覆盖矩阵

| 功能 | A 股 | 港股 | 美股 | 结论 |
|------|:---:|:---:|:---:|------|
| 综合研判（llm-report） | ✅ 质量好 | ⚠️ 数据错 | ⚠️ 数据错 | **market 参数未生效**：HK/US 仍输出 A 股指数 |
| AI 投顾（llm-advice） | ❌ | ❌ | ❌ | 上下文全缺失（"所有字段均为暂无/未知"） |
| 个股分析（symbol-analysis） | ⚠️ 技术面空 | ❌ 行情空 | ⚠️ 技术面空 | 600519 输出"技术指标：空、历史K线：无"；00700 实时行情 {} |
| ETF 分析 | ⚠️ 技术面空 | — | ⚠️ | 同个股分析 |
| 板块分析（sector-analysis） | ❌ 成分股错位 | — | — | BK0447 半导体返回立方控股/昆仑万维等软件股 |
| 概念分析 | ✅ | — | — | Kimi 概念成分股正确、分析质量尚可 |
| 指数分析 | ✅ | — | — | 000300 宏观传导逻辑清晰 |
| 搜索自动补全 | ✅ | ✅ | ✅ | DATABASE_URL 修复后全市场命中（510300/盈富/SPY/00700/AAPL） |

### 4.2 内容审阅

- **质量尚可**：A 股综合研判（数据准确、逻辑清晰）；指数分析与 Kimi 概念分析。
- **严重问题**：
  1. `llm-report` 的 `market` 参数未传导到数据采集（HK/US 分支仍采 A 股数据）——前端 MarketReport 切 tab 得到的是 A 股报告。
  2. `llm-advice` 上下文注入失败（`_inject_market_context`/`build_full_context` 产出空数据），AI 投顾回答基于"数据缺失"而非真实行情。
  3. `symbol-analysis` 技术指标/历史 K 线缺失（K 线依赖 akshare，熔断窗口放大）。
  4. **系统提示词内容泄漏到输出**（回答开头出现"我们只需要回答用户的问题…"等 prompt 指令文本）——LLM 输出未做隔离/后处理。
  5. 板块成分股错位：BK0447（半导体）返回 IT 服务/软件股，成分股映射错误。

---

## 五、热点 / 自选 / 技研 / 资讯 / 因子评估（步骤 4-8）

### 5.1 热点板块与个股（步骤 4）✅

- `hot-plates` 11 条（AI应用/机器人概念/算力工程/芯片产业链等，含涨幅/领涨股数/原因）
- `stock-hot-rank` 50 条（长鑫科技/德明利/兆易创新等，含概念标签）
- `wind` / `sectors/concept` / `sectors/industry` / `sectors/rotation` 均正常

### 5.2 自选功能（步骤 5）⚠️

| 用例 | 结果 |
|------|------|
| 添加 A 股 510300 | ✅ 201（名称正确"沪深300ETF华泰柏瑞"） |
| 添加美股 SPY | ✅ 201（**名称兜底为 "SPY"**，realtime 无 name 字段） |
| 添加港股 00700/02800.HK | ❌ 422（**港股实时行情 null**，存在性校验不过） |
| 重复添加 | ✅ 409 |
| 中文 symbol | ✅ 422 |
| GET 含实时行情 | ⚠️ A 股 realtime **间歇性为空**（mootdx 熔断窗口），美股稳定 |
| PUT 更新备注 | ✅ 200 |

### 5.3 持仓技研与综合信号（步骤 6）⚠️

场内 10 只持仓信号（K 线正常时）：

| 标的 | 权重 | 信号 | 依据 |
|------|:---:|:---:|------|
| 159338 中证A500ETF | 20% | **sell -2.0** | MACD 死叉空头、MA5<MA20 空头排列 |
| 159992 创新药ETF | 5% | sell -1.5 | MACD 偏空 |
| 513120 港股创新药ETF | 5% | sell -1.5 | MACD 偏空 |
| 510880 红利ETF | 8% | hold +1.0 | RSI 62.9 偏强、金叉多头 |
| 159545 恒生红利低波 | 5% | hold 0.0 | RSI 62.4、KDJ 超买死叉 |
| 159516 半导体设备 | 4% | hold -1.0 | RSI 31.2 偏弱、MACD 死叉空头 |
| 159869 游戏ETF | 5% | — | 本轮未单独拉信号 |
| 512000 券商ETF | 8% | — | 同上 |
| 513010 恒生科技ETF | 3% | — | 同上 |
| 518880 黄金ETF | 13% | — | 同上 |

评估结论：
- 信号引擎能输出明确 buy/sell（score ±2，**Z10 已改善**），与 range_bound 市态判断一致、逻辑合理。
- **严重问题**：akshare 熔断窗口期 history/indicators/signal 全线 `insufficient_data`（实测捕捉）；设计时点因子数据与实际指标不一致（见 §3.2）。

### 5.4 资讯页面（步骤 7）⚠️

- 数据源正常：headlines 30 / macro 15 / global 8 / 个股资讯 10 / 研报 761。
- **分级不合理**：关键词法（`classify_news_level`）将国际微观新闻评为中高等级——"斯特兰蒂斯召回 127 万辆" 1★3、"纽约州指控赌博" 1★3、"埃森哲与 IBM 合作" 4★5、5 星新闻有 5 条。评级未纳入与 A 股 ETF 组合的相关性维度。
- AI 智能分析：`news-impact` 结构化返回（impact_scope/summary/disclaimer）可用，但篇幅简短、内容泛化，未结合具体持仓。

### 5.5 因子模型（步骤 8）⚠️

33 个活跃因子状态：

| 状态 | 数量 | 明细 |
|------|:---:|------|
| valid | 20 | technical 13（RSI 0.50/MACD 0.44/KDJ 0.63-0.74 等）+ etf_specific 7（含 industry_diversification 0.13） |
| static | 3 | china_specific policy 因子（Z03 已修：不再计 no_data） |
| warn | 3 | stock_divergence / ln_mcap / ln_float_mcap（ic=0.0） |
| no_data | **7** | etf_specific 4（premium_discount/tracking_error/shares_change/institutional_holdings_change）+ sentiment 3（panic_greed_diff/news_heat/news_direction） |

- `factor-health` 200 + ok（Z01 已修）；IC 端点 23 条非空（Z06 已修）；avg_ic 0.22。
- **Z04 未达标**（验收 etf_specific no_data < 3，实际 4）；**sentiment 3 因子为新增 no_data**（情绪数据管道缺失）。

---

## 六、前后端数据断裂排查（步骤 9）

实测 20+ 端点 + 前端源码审计 + Lighthouse 网络瀑布，确认 6 个断裂点：

| # | 断裂点 | 形态 | 影响 |
|---|--------|------|------|
| B1 | **生产模式 WebSocket 404** | 前端连 `/api/v1/ws/*`，nginx 缺该路径的 upgrade 代理（`location /api` 无 upgrade 头、`location /ws` 不匹配 `/api/v1/ws`） | 实时行情推送、任务通知、设计报告推送在生产环境全失效；dev 模式靠 Vite 代理掩盖 |
| B2 | `/market/sectors/heat` 404 | 前端 `SectorHeatMap.vue` 调用 `marketApi.getSectorHeat()`，后端无此路由（数据在 hub 内部有，未暴露） | 板块热度组件降级/报错 |
| B3 | `marketApi.sectorAnalysis/marketAnalysis` 未定义 | `UnifiedAnalysis.vue` 调用不存在的方法，走 fallback `fetch /search` | 个股/板块深度分析功能降级为空壳 |
| B4 | 单只 A 股 realtime 间歇性 null | `fetch_a_stock_realtime` 降级链 mootdx→sina **缺 tencent 一级**（批量链有 tencent） | 自选/持仓单只行情偶发缺失 |
| B5 | 港股实时行情全 null | `fetch_hk_stock_realtime` 链路不通（多次 422/空） | 港股自选添加失败、港股分析无数据 |
| B6 | `market=A` 个股搜索降级错误 | instruments 表无 stock 行时降级到 ETF 搜索而非个股（"贵州茅台"返回 0） | A 股个股搜索失败 |

其余端点（rotation/industry-cls/watchlist/hot-plates/stock-hot-rank/wind/factors/admin 等）实测全部 200。

---

## 七、问题清单验证（步骤 10）

`docs/system-diagnosis-and-optimization-plan.md`（v4.0）Z01-Z15 逐项验证：

| ID | 问题 | 本轮状态 | 证据 |
|----|------|---------|------|
| Z01 | factor-health 500 | ✅ 已修 | HTTP 200 + ok |
| Z02 | 美股行情 null | ✅ 已修 | SPY 742.9 有值 |
| Z03 | china_specific 3 因子 no_data | ✅ 已修 | 状态均为 static |
| Z04 | etf_specific 10 因子无数据 | ❌ **未达标** | 仍 4 个 no_data（验收要求 <3）；industry_diversification 已修复；修复方案见 §9.5 专项 |
| Z05 | SSL 预热握手重复 | ✅ 改善 | 预热 1.77s（历史 38s→3s） |
| Z06 | 因子 IC 全空 | ✅ 已修 | 23 条 IC 非空，avg_ic 0.22 |
| Z07 | LLM 42.4% 错误率 | ⚠️ 改善未达标 | 23.2%（462/1995），429 限流持续（Retry-After 8h） |
| Z08 | sources/health 空 | ✅ 已修 | 返回非空数组 |
| Z09 | sigma 值异常 | ✅ 已修 | signal score 均在 ±2 |
| Z10 | 信号引擎保守 | ✅ 改善 | 有 buy/sell 输出（score ±2） |
| Z11 | 非交易时段设计失败 | ⚠️ 部分 | 现金 22-32%（非 100%），但现金仍偏高 |
| Z12 | 缺少运行时 profiling | ✅ 已修 | PROFILE_WARMUP 全套报告 |
| Z13 | 中文搜索 URL 编码 | ✅ 非服务器 bug | 后端 str 天然支持，客户端编码即可 |
| Z14 | pre-commit 仅前端 | ✅ 已修 | 已含密钥/构建/API 覆盖/异步审计/mypy/pytest/冒烟 |
| Z15 | verify_e2e 覆盖不足 | ✅ 部分 | 已含 US/HK 搜索、factor-health、IC、search；但见 §8.2 盲区 |

结论：**12/15 已修或部分修；Z04 未达标，Z07/Z11 部分改善**。本轮新发现（未列入旧清单）：B1 WS 生产断裂、B2-B6 断裂点、AK 线单源依赖、HK 行情链路、LLM 上下文缺失、市场参数失效、因子数据不一致、sentiment 因子无数据、搜索排序缺陷、资讯分级缺陷。

---

## 八、测试防护体系分析（步骤 13）

### 8.1 为什么 16 项 e2e 失败中有噪音

`verify_e2e.py` 本轮 185/201 通过，16 项失败完整构成（多次运行合并统计）：
- 性能 gate（真实捕获）：`search?market=HK` 5.6s、`portfolio/calculate` 8.1-8.2s 超 5s gate（2 项；另 1 项 `search` 默认分支在部分运行中 >5s 属同一慢源）
- **数据/时序 flaky（9 项）**：510300/518880/511090 `7/33 live factors`×3、`方案数>=3 实际 0`、`510300 in allocation`、`BB upper/ma/lower 全 0`（K 线空窗）、`risk_warnings 含未知类型`、`任务 26 到 quick_ready 未终态`、`设计历史端点 422`
- **脚本自身缺陷（4 项）**：`GET /market/etfs` 404、`GET /admin/sources` 404（过期端点）；快照/LLM 模块导入 `No module named 'app'`（PYTHONPATH）；`POST /daily-pnl` 422（参数）

### 8.2 防护失效根因（6 类盲区）

| 盲区 | 机制 | 漏掉的问题 |
|------|------|-----------|
| 拓扑盲区 | e2e 直连 `localhost:8000` 绕过 nginx | B1 WS 生产断裂、代理配置错误 |
| 环境盲区 | e2e 在本地（dev 有 `DATABASE_URL` 覆盖）运行 | prod 容器空库（本轮 P0 bug） |
| 内容盲区 | 只断言 200/非空，不校验内容正确性 | LLM 上下文缺失、market 参数失效、成分股错位、搜索排序错误 |
| 数据源运行时盲区 | 单测全 mock 外部网络；e2e 不覆盖熔断窗口降级 | 单只行情 null、K 线空导致技研 insufficient_data |
| 时序 flaky | 因子 live 数依赖后台 60s/120s 刷新，硬阈值 | e2e 自身不稳定，掩盖真实状态 |
| 脚本卫生 | 过期端点、PYTHONPATH 依赖、WS 测试缺库时"跳过即 PASS" | 失败噪音污染，削弱门禁可信度 |

---

## 九、优化修复方案

### 🅿️0 — 阻断性修复（已实施 2 项，剩余 2 项）

| ID | 问题 | 修复方案 | 涉及文件 | 验收条件 |
|----|------|---------|---------|---------|
| F0-1 ✅ | prod 容器空库 | `backend` 服务 environment 增加 `DATABASE_URL=sqlite+aiosqlite:////app/data/portfolio.db` 覆盖 Windows 路径 | `docker-compose.yml` | 容器内 `SELECT COUNT(*) FROM instruments` = 1544 |
| F0-2 ✅ | Settings extra_forbidden | `Settings.Config` 增加 `extra="ignore"` | `backend/app/config.py` | 任意无关环境变量不导致启动崩溃 |
| F0-3 | **WS 生产断裂** | nginx.conf 增加 `location /api/v1/ws`（`proxy_pass http://backend:8000` + upgrade 头，置于 `location /api` 之前）；或前端统一改 `/ws/*` | `frontend/nginx.conf` | `wscat -c ws://localhost/api/v1/ws/portfolio` 握手成功 |
| F0-4 | **A 股 K 线单源依赖** | `get_history` 降级链增加 sina K 线/levistock 源；akshare 熔断期间从 `indices_cache.json`/内存缓存兜底；`get_k_data` 失败不再返回空而标记 stale | `backend/app/services/market_service.py`、`backend/app/fetchers/china_market.py` | akshare 熔断时 `history/indicators/signal` 仍有数据（stale 标记） |
| F0-5 | **候选池 = 当日涨幅 Top25**（核心层偏离主流宽基） | 详见「§9.6 专项：候选池修复」：A 候选池改成交额排序（`fid=f6`）+ 分页失败重试不 break → B 主流宽基静态兜底注入（510300/510500/510050/588000 等）使 `CORE_REQUIRED/DEFENSE_REQUIRED` 生效 → C 板块配额防科创包场 → D 卫星 ≥4 只 → E C2 惩罚触发条件修正 | `backend/app/fetchers/etf_scanner.py`、`backend/app/engine/allocation_engine.py` | 方案 core 含主流宽基；卫星 ≥4；防御型科创卫星 ≤10% |

### 🅿️1 — 高优先级（数据质量与正确性）

| ID | 问题 | 修复方案 | 涉及文件 | 验收条件 |
|----|------|---------|---------|---------|
| F1-1 | 港股实时行情全 null | 排查 `fetch_hk_stock_realtime`（`china_market.py` 实际降级链 **sina → tencent → dongfang(_em_hk_realtime)**）与代码归一化（HK 代码无 `.HK` 后缀） | 涉及：`backend/app/fetchers/china_market.py` | `realtime/00700?asset_type=HK` 返回价格 |
| F1-2 | 单只 A 股实时行情间歇性 null | `fetch_a_stock_realtime` 降级链补 tencent（与批量一致：mootdx→tencent→sina） | 涉及：`backend/app/fetchers/china_market.py` | 连续 10 次 `realtime/510300` 无 null |
| F1-3 | LLM 上下文数据缺失 | 修复 `llm-advice`/`symbol-analysis` 的 `build_full_context` 采集链路（market 分支参数传导 + K 线注入） | 涉及：`backend/app/services/llm_context.py`、`backend/app/routers/analysis.py` | llm-advice 回答引用真实行情数据 |
| F1-4 | `llm-report` market 参数失效 | 后端按 `market` 参数切换指数/板块/资讯采集（HK/US 分支） | 涉及：`backend/app/routers/analysis.py`、`backend/app/analysis/llm.py` | `market=HK` 报告含恒生指数 |
| F1-5 | 设计因子数据不一致 | 统一设计引擎与 `indicators` 端点的 K 线来源与时点；rationale 从 factor_scores 取 RSI 时校验数据新鲜度 | 涉及：`backend/app/engine/`、`backend/app/factors/factor_registry.py` | 设计报告 RSI 与实际 `indicators` 一致 |
| F1-6 | 板块成分股错位 | 修复 BK0447 等板块成分股映射（sector 代码→成分股接口错位） | 涉及：`backend/app/services/market_data_hub.py`（get_sector_stocks） | 半导体板块返回半导体成分股 |
| F1-7 | LLM 输出未后处理 | 对 LLM 流式输出做系统提示词隔离（system prompt 与用户内容严格分段）+ 输出首段过滤已知泄漏模式 | 涉及：`backend/app/analysis/llm.py`、`backend/app/routers/analysis.py` | 输出无"我们只需要回答…"类泄漏 |
| F1-8 | **组合设计投资合理性**（方案与市场脱节） | 详见「§9.7 专项：投资合理性评估」：R1 因子数据正确性（RSI K 线口径对齐 + 估值字段按资产类别禁用）→ R2 market_context 填充 → R3 rationale 绑定标的属性 → R4 候选池多样性（见 F0-5）→ R5 信号聚合「双弱不判多」约束 | 涉及：`backend/app/engine/rationale.py`、`backend/app/analysis/signal.py`、`backend/app/factors/factor_registry.py`、`backend/app/services/llm_context.py` | core 重叠 ≤1 只；防御型科创卫星 ≤10%；rationale 无模板缺陷；market_context 非空 |

### 🅿️2 — 中优先级（性能与断裂修复）

| ID | 问题 | 修复方案 | 涉及文件 | 验收条件 |
|----|------|---------|---------|---------|
| F2-1 | 组合计算 8.2s | `calculate_allocation`/`daily_pnl` 对持仓行情/K 线改 `asyncio.gather` 并行 + 15s 缓存（注意：缓存会降低数据新鲜度，15s 与 `portfolio:realtime` 一致可接受） | 涉及：`backend/app/services/portfolio_service.py` | calculate < 2s（多次采样中位数） |
| F2-2 | 首页 Lighthouse 60 | Dashboard 慢 API 并行加载 + 骨架屏（消除 CLS）+ 路由级代码分割（echarts 按需）+ 关键 API 预热缓存 | 涉及：`frontend/src/views/Dashboard.vue`、`frontend/src/router/index.js`、`vite.config.js` | 首页 Performance ≥ 85（3 次采样中位数），CLS < 0.1 |
| F2-3 | `/market/sectors/heat` 404 | 后端暴露 `GET /market/sectors/heat`（hub 已有 `get_sector_heat`，数据源实测正常）或前端改调 `sectors/rotation`。详见「§9.8 专项步骤 B」 | 涉及：`backend/app/routers/market.py`、`frontend/src/components/market/SectorHeatMap.vue` | 前端 SectorHeatMap 无 404 |
| F2-4 | `marketApi.sectorAnalysis/marketAnalysis` 未定义 | 前端定义方法并接通 `/analysis/symbol-analysis/stream`、`/analysis/sector-analysis/stream`（详见「§9.8 专项步骤 D」，删除 fallback 假成功分支） | 涉及：`frontend/src/api/index.js`、`frontend/src/components/market/UnifiedAnalysis.vue` | UnifiedAnalysis 真实分析可用 |
| F2-5 | 预热指数/新闻串行 | `warmup_global_indices` 内 `asyncio.gather` 并行拉取 | 涉及：`backend/app/main.py` | 预热 < 1.0s |
| F2-6 | **热点板块/热门个股字段契约不匹配 + 信息不足** | 详见「§9.8 专项步骤 A/C」：A 后端字段归一化（`get_hot_plates`/`get_sector_heat`/`get_stock_hot_rank`，`stock_list`/`tag` 用 `ast.literal_eval` 安全解析）→ C 热门个股行增强（price/sector/turnover/concept chips） | 涉及：`backend/app/services/market_data_hub.py`、`backend/app/fetchers/sector_fetcher.py`、`frontend/src/components/market/SectorHeatMap.vue` | 热点板块 ≥10 行；个股行含 price/sector/turnover/chip |
| F2-7 | **热门个股/板块无快速分析入口** | 详见「§9.8 专项步骤 E/F」：个股行「技术分析」（indicators+signal 弹窗）+「AI 分析」（emit → UnifiedAnalysis symbol 模式）；板块行「AI 分析」（UnifiedAnalysis 扩展 externalTrigger 支持 sector 模式）；`cls` 板块代码归一化 | 涉及：`frontend/src/components/market/SectorHeatMap.vue`、`frontend/src/views/MarketAnalysis.vue`、`backend/app/routers/analysis.py` | 点击后自动聚焦分析区并触发真实分析 |
| F2-8 | **资讯 AI 智能分析「无反应」** | 详见「§9.9 专项步骤 A」：改为**行内展开**——结果直接显示在对应新闻卡片内（`impactTarget` + toggle/切换/失败重试），删除页面底部面板 | 涉及：`frontend/src/components/NewsView.vue` | 点击后结果出现在该条卡片内，无滚动、无跳转 |
| F2-9 | **资讯分析质量偶发「不合理」** | 详见「§9.9 专项步骤 B」：prompt 增加硬约束「若新闻与组合标的无直接关联，明确说明『无直接影响』，不得强行关联」（实测 3 条样本 LLM 已较克制，此约束用于压制单条波动） | 涉及：`backend/app/analysis/llm.py`（`analyze_news_impact` prompt） | 3 条基线样本（降准/半导体停产/黄岩岛）结论均合理，且无强行关联 |

### 🅿️3 — 低优先级（质量完善）

| ID | 问题 | 修复方案 | 验收条件 |
|----|------|---------|---------|
| F3-1 | 资讯分级不合理 | `classify_news_level` 增加相关性加权（A 股/组合相关关键词加权、国际微观降级），财联社源评级复核 | 验收："召回/赌博"类国际新闻 ≤ 2 星 |
| F3-2 | 搜索排序缺陷 | 跨市场合并前先做全局精确匹配（symbol==kw 优先于首字母模糊）；`market=A` 个股搜索降级到 levistock 个股 | 验收：`search?keyword=SPY` 首条为 SPY；`market=A&keyword=贵州茅台` 返回茅台 |
| F3-3 | 设计现金仓位偏高 | 预算引擎对 range_bound 市态的现金上限收紧（22-32% → ≤15%），非交易时段才有高现金 | 验收：balanced 方案现金 ≤ 15% |
| F3-4 | Z04 etf_specific 4 因子 | 详见「§9.5 专项：Z04 修复方案」：A NAV 降级链（premium_discount）→ B benchmark_close 注入（tracking_error，分批宽基先行）→ C 份额数据源（shares_change + institutional_holdings_change 同时复活）→ D IC/状态展示修复 | 验收：etf_specific no_data < 3，且 no_data 因子 reason 明确标注缺失字段 |
| F3-5 | sentiment 3 因子无数据 | 接通 panic_greed_diff（涨跌分布）、news_heat/news_direction（资讯情绪）数据管道 | 验收：sentiment no_data = 0 |
| F3-6 | LLM 429 限流 | 增加指数退避重试（尊重 Retry-After）+ provider 轮换 + 高峰排队（成本权衡：免费模型限流是常态，可接受降级） | 验收：单次分析失败前至少 2 次重试 |
| F3-7 | 自选美股名称 | `get_asset_realtime` US 分支补充 name 字段（静态基座映射） | 验收：自选 SPY 显示 "SPDR S&P 500 ETF" |

### 🅿️4 — 测试防护补强（步骤 13 落地）

| ID | 措施 | 拦截目标 |
|----|------|---------|
| T1 | e2e 增加 nginx 拓扑层（`http://localhost` 走 nginx 的 WS 握手 + /api 代理测试） | B1 WS 断裂（防回归能力最强） |
| T2 | e2e 增加 prod 容器 DB 完整性断言（instruments > 1000 **且 portfolio_etfs/watchlist 非空**——P0 bug 同样清空它们） | 空库回归 |
| T3 | e2e 增加内容级断言：①llm-advice 回答不含"暂无/未知"；②llm-report `market=HK` 含恒生指数；③板块成分股与板块名匹配（半导体含半导体股）；④搜索 `keyword=SPY` 首条 symbol=SPY；⑤LLM 输出不含"我们只需要"类泄漏 | 内容盲区（含排序/泄漏） |
| T4 | 修复 e2e 过期端点（/market/etfs、/admin/sources）、PYTHONPATH（`sys.path.insert(0, backend)`）、`POST /daily-pnl` 参数（对照契约补全请求体）、WS 缺库"跳过即 PASS"改为 SKIP 计数 | 失败噪音 |
| T5 | factor-health 门限改为多次采样取中位数 + 数据就绪等待（最多 30s） | 时序 flaky |
| T6 | 数据源熔断演练：通过 `admin/config` 或环境变量强制置 mootdx/akshare 熔断态，验证降级链输出非空 | 数据源运行时盲区 |

### 🔬 专项：Z04 etf_specific 因子无数据修复方案（细化）

> 对应 F3-4。本节给出可直接开工的实施级方案：根因定位（含代码行号）、10 因子数据依赖清单、4 步修复（A-D，含伪代码）、TDD 测试计划与量化验收条件。

#### 9.5.1 问题现象与影响

- `GET /api/v1/factors/active` 实测：etf_specific 类别 10 因子中 **6 个 valid、4 个 no_data**，Z04 验收（no_data < 3）未达标。
- no_data 的 4 个：`etf.premium_discount` / `etf.tracking_error` / `etf.shares_change` / `etf.institutional_holdings_change`。
- 附带影响：① 这 4 个因子全 0.0 被 IC 过滤，不参与 avg_ic 与因子评分；② `factors/active` 的 no_data reason 统一显示「尚未计算 IC（数据不足）」，**误导排障方向**（实际是数据源未接入，而非样本不足）；③ 设计引擎（`engine/rationale.py`）无法引用这些因子，削弱方案理由的 ETF 专属维度。

#### 9.5.2 根因分析（三层缺口叠加）

**缺口① 数据源未注入（主因）** — `market_data_hub.py::_build_symbol_extra`（L936-948）目前只产出 `fund_scale / fund_shares / industry / concepts` 4 个字段；而 `factor_registry.py::_fetch_market_data`（L960-972）的 Z04 注入循环**已支持** `benchmark_close / shares_change_20d / institutional_holdings_change` —— 注入代码在，上游数据源缺失，形成"接口就位、无数据可注"。

**缺口② IC 过滤导致"永远 no_data"（次因）** — `ic_tracker.py::compute_periodic_ic`（L156）只收集 `abs(value) >= 0.001` 的因子值。数据缺失的因子恒返回 0.0 → 被过滤 → 永远进不了 `_last_ic_batch` → `factors.py`（L144-145）判为 no_data。

**缺口③ 真实数据源存在但未接入** — 三个现成资源未被消费：
| 资源 | 位置 | 现状 |
|------|------|------|
| ETF→基准指数映射 | `backend/data/etf_index_mapping.json`（45 条） | 只有指数**名称**，无指数**代码**；未被任何代码读取 |
| 基金 NAV 接口 | `fund_fetcher.py::fetch_fund_nav`（天天基金） | 已封装，未接到 premium_discount 降级链 |
| 指数元数据 | `indices_meta` 表（`symbol`/`name`/`index_type`） | 仅覆盖宽基（sh000300 等），行业指数代码缺失 |

#### 9.5.3 10 因子数据依赖清单

| 因子 | 依赖字段 | 当前数据源 | 状态 | 修复步骤 |
|------|---------|-----------|:---:|:---:|
| `etf.amount_stability` | volume 序列 | K 线 | ✅ valid | — |
| `etf.change_pct` | change_pct | K 线 | ✅ valid | — |
| `etf.return_1m` / `etf.return_3m` | close 序列 | K 线 | ✅ valid | — |
| `etf.price` | price | K 线/实时 | ✅ valid | — |
| `etf.industry_diversification` | industry / concepts | hub 注入 | ✅ valid | — |
| `etf.premium_discount` | **nav** + price | Sina/QQ IOPV（无外网即缺） | ❌ no_data | **A** |
| `etf.tracking_error` | **benchmark_close** + close | 无（mapping 未消费） | ❌ no_data | **B** |
| `etf.shares_change` | **shares_change_20d** | 无（fund_fetcher 仅 NAV 快照） | ❌ no_data | **C** |
| `etf.institutional_holdings_change` | institutional_holdings_change / **shares_change_20d** / fund_scale | 无 | ❌ no_data | **C** |

#### 9.5.4 修复步骤（按成本排序）

**步骤 A — premium_discount NAV 降级链（低）**

- 文件：`backend/app/factors/factor_registry.py`（`_fetch_market_data` L953-958 的 IOPV 抓取块）
- 改动：Sina/QQ IOPV 命中率不足或抛异常时，对剩余 symbols 调 `market_data_hub.get_fund_nav(sym)`（天天基金日频净值）注入 `nav`。
- 伪代码：
```python
# 现有 except 块（L957-958）后追加降级
missing = [s for s in symbols if not (data.get(s) or {}).get("nav")]
for sym in missing:
    try:
        nav = await market_data_hub.get_fund_nav(sym)   # {"nav": float}
        if nav and nav.get("nav"):
            data.setdefault(sym, {})["nav"] = nav["nav"]
    except Exception:
        continue
```
- 口径注意：NAV 为日频、IOPV 为盘中实时，降级后折溢价口径变为「收盘折溢价」，需在因子定义/文档注明（不回退为 0.0 假数据）。

**步骤 B — tracking_error benchmark_close 注入（中）**

- 文件：`backend/data/etf_index_mapping.json`（补 index_code）、`backend/app/services/market_data_hub.py::_build_symbol_extra`
- 改动：
  1. mapping 扩展为 `{"510300": {"index_name": "沪深300指数", "index_code": "sh000300"}}`；行业指数代码用 akshare `index_zh_a_hist` / `index_stock_info` 一次性补全后固化（45 条手工核对）。
  2. `_build_symbol_extra` 读 mapping，取指数代码，从指数历史（hub.get_history 支持指数或指数缓存）取最近 20 日 close 填 `benchmark_close`。
- 伪代码：
```python
mapping = _load_etf_index_mapping()          # {"510300": {"index_code": "sh000300"}}
for sym in symbols:
    idx_code = mapping.get(sym, {}).get("index_code")
    if not idx_code:
        continue                              # 无代码的 ETF 跳过，不阻塞其他因子
    closes = await _fetch_index_closes(idx_code, days=20)   # hub 历史或指数缓存
    if len(closes) >= 5:
        result[sym]["benchmark_close"] = closes
```
- 风险控制：行业指数历史接口成本高 → **分批实施**，第一批发 mapping 中的宽基（沪深300/中证500/上证50/创业板指等），行业指数随 mapping 补全跟进。

**步骤 C — shares_change / institutional_holdings_change 份额数据（中）**

- 文件：`backend/app/fetchers/fund_fetcher.py`（新增 `fetch_fund_shares_history`）、`backend/app/services/market_data_hub.py::_build_symbol_extra`
- 改动：
  1. `fund_fetcher.py` 新增 `fetch_fund_shares_history(symbol) -> {"shares_20d_change": float}`：天天基金 `fund_fund_shares_em`（份额规模变化）取最近 2 期份额计算变化率。
  2. `_build_symbol_extra` 注入 `shares_change_20d`；该字段同时喂 `_compute_shares_change`（直接用）与 `_compute_institutional_holdings_change`（×0.5 折扣代理）→ **两因子同时复活**。
- 伪代码：
```python
async def fetch_fund_shares_history(symbol: str) -> dict | None:
    # ak.fund_fund_shares_em(symbol) → DataFrame(份额日期/份额)
    rows = await run_sync(ak.fund_fund_shares_em, symbol, timeout=15)
    if len(rows) >= 2:
        cur, prev = rows.iloc[-1]["份额"], rows.iloc[-2]["份额"]
        if prev and prev > 0:
            return {"shares_20d_change": round((cur - prev) / prev, 4)}
    return None
```
- 风险控制：份额数据日更/周更，20 日窗口可能不足 → 退化为「最近一期变化率」并在 reason 注明；抓取加 24h 缓存 + 失败静默（沿用现有熔断框架）。

**步骤 D — IC/状态展示修复（低中）**

- 文件：`backend/app/routers/factors.py`（L144-145 reason）、`backend/app/factors/ic_tracker.py`（L156 过滤处）
- 改动：
  1. `factors.py::_status_of` 的 no_data reason 区分两类：**「数据源未接入（缺 nav/benchmark_close/shares_change_20d）」**与**「IC 未累积（样本 <3）」**，依据因子定义元数据 + `_sample_counts` 判定。
  2. `ic_tracker.py` 在过滤处统计全 0.0 因子的零值占比 `_zero_ratio`，随 `/factors/ic` 输出（`zero_ratio` 字段），避免"数据缺失"被误报为"IC 无效"。
- 验收：`factors/active` 每个 no_data 因子的 reason 明确指向缺失字段，不再笼统显示"数据不足"。

#### 9.5.5 TDD 测试计划（先写失败单测）

`tests/test_factor_etf_specific.py` 新增：

| 用例 | 断言 |
|------|------|
| `test_premium_discount_with_nav` | mock data 含 nav+price → 返回值非 0 |
| `test_tracking_error_with_benchmark` | mock close+benchmark_close（5 日以上）→ 非 0 且 ≤0.05 |
| `test_shares_change_from_20d` | mock shares_change_20d → 因子直接生效 |
| `test_institutional_holdings_change_proxy` | mock shares_change_20d → 因子 = 值 × 0.5 |
| `test_symbol_extra_injects_benchmark` | mock hub `_build_symbol_extra` + mapping → `benchmark_close` 注入 |
| `test_no_data_reason_specifics` | mock ic_batch 为空 → reason 区分「数据源缺失」vs「IC 不足」 |

集成用例：`test_factor_ic_etf_specific` — 用场内 10 只 ETF 的 K 线（mock 网络）+ 注入 symbol_extra，断言 etf_specific `no_data_count < 3`。

#### 9.5.6 验收条件（量化）

1. `GET /api/v1/factors/active`：etf_specific `no_data_count` 从 **4 → ≤2**。
2. 复活的因子进入 `_last_ic_batch`，纳入 valid/warn 统计（先解决"无数据"，不要求 IC 质量达标）。
3. `factors/active` 剩余 no_data 因子 reason 明确标注缺失字段。
4. `python -m pytest tests/test_factor_etf_specific.py` 全绿；全量 pytest 无新增失败。
5. 回归：`verify_e2e.py` 全 PASS（含 factor-health 检查）。

#### 9.5.7 风险与回退

| 风险 | 缓解 |
|------|------|
| 行业指数代码补全成本高 | 分批：宽基先行，mapping 无代码的 ETF 跳过 benchmark_close，不阻塞其他因子 |
| 天天基金接口限流 | 份额抓取 24h 缓存 + 失败静默（沿用熔断框架） |
| NAV 日频 vs IOPV 实时口径差异 | 文档注明口径；若折溢价失真，premium_discount 保留 no_data 并明确标注（**不回退为 0.0 假数据**） |
| IC 质量波动（avg_ic 可能下降） | 仅展示不熔断；IC 低于 threshold 已有 B3 告警机制 |

---

### 🔬 专项：候选池修复 — 组合设计核心层偏离主流宽基（P0/P1）

> 对应新增 F0-5（候选池来源）与 F1-8（选标/去重）。本节给出实施级方案：现象（方案快照证据）、根因链（含代码行号）、修复步骤 A-E（含伪代码）、TDD 测试计划与量化验收条件。

#### 9.6.1 问题现象与影响（方案快照 `logs/design_latest_full.json` 实证）

| 现象 | 快照证据 | 投资影响 |
|------|---------|---------|
| 核心层无主流宽基 | 三套方案 core 全部是「价值/增强/成长」变体宽基：562320 沪深300价值、562330 中证500价值、563080 中证A50、562340 中证500成长、563030 中证500增强、562000 A100；**最主流的 510300 沪深300ETF / 510500 中证500ETF / 510050 上证50ETF / 588000 科创50ETF 全部缺席** | 方案与市场主流配置脱节，投资者难以对齐基准 |
| 卫星层被科创系包场 | 589720 科创创新药、589420 科创芯片设计、589560 科创人工智能、589960 科创新能源——名称全部带「科创」 | 风格高度集中，未达卫星层分散目的 |
| 卫星数量偏少 | 防御型/进攻型各仅 2 只卫星（预算引擎 `layer_count.satellite=8` 上限远未用满） | 卫星层失去「多赛道分散」的意义 |
| 防御型配 25% 科创卫星 | 防御稳健组合 satellite=589720(12.58%)+589420(12.42%) | 与「防御」风偏矛盾（详见 §9.7） |

#### 9.6.2 根因链（三层叠加）

1. **候选池 = 当日涨幅 Top25（主因）**
   - `etf_scanner.py::_fetch_em_etf_list`（L180-197）按 `fid=f3`（涨跌幅降序）分页拉全市场 ETF → 当日涨幅榜被题材/小盘 ETF 占满，主流宽基当日涨幅进不了 Top25 → **被挤出候选池**。
   - 分页 `except: break`（L196-197）：任一分页失败即静默中断，只返回部分数据，加剧候选池偏斜。
   - `full_pipeline`（L622-646）在各层 `layer_ranking(top_n=25)` 再截断一次，池子进一步收窄。

2. **强制清单注入静默失效（CORE_REQUIRED/DEFENSE_REQUIRED 形同虚设）**
   - `layer_ranking(..., required=CORE_REQUIRED)`（L644-646）的 required 注入逻辑（L512-524）**只从候选池 `items` 里查找** `510300`/`560600`/`518880`/`511090`；候选池里没有 → `found=None` → **静默跳过，不报错、不补录**。
   - 结果：`CORE_REQUIRED=["510300","560600"]` 从未生效，方案里 core 全是涨幅榜里的变体宽基。

3. **板块去重拦不住「科创系」**
   - `allocation_engine.py::allocate` L247-260 `concept_groups` 按 `tracked_index` 归一化前缀去重（科创50/科创100/科创新能源 → 科创），每组仅留最高分。
   - 但 589720（创新药）/589420（芯片设计）/589560（人工智能）/589960（新能源）**归一化后分属 医药/电子/计算机/新能源 四个不同概念组** → 名称都带「科创」却各自入选 → 去重逻辑对「同主题不同概念名」失效。

4. **卫星少 = 候选池窄的必然结果**
   - core 层被变体宽基占满（见现象 1）+ 卫星候选本身不足（涨幅榜上科创系集中）→ `_filter_satellite_by_profile`（L307-347）KEEP_RATIO 裁剪后只剩 2 只。

5. **C2 防御型科创惩罚失效（放大 4 的影响）**
   - `allocation_engine.py` L219 `valuation_missing = abs(factor_scores.get("valuation",0)) < 0.001`：防御型对科创的 `c2_bonus=-1.5`（L229-234）**只在 `valuation_missing` 时生效**。
   - 实际估值因子非零（虽然值是错位的假信号，如 589720 估值 -0.462）→ 条件不满足 → 惩罚分支不进 → 防御型仍配 25% 科创卫星。

#### 9.6.3 修复步骤（按成本排序）

**步骤 A — 候选池来源改为规模/成交额排序（P0，核心）**

- 文件：`backend/app/fetchers/etf_scanner.py::_fetch_em_etf_list`（L180-197）
- 改动：
  1. 分页排序 `fid=f3`（涨跌幅）→ **`fid=f6`（成交额）** 或 `fid=f12`（代码序全市场遍历）；主流宽基成交额/规模恒居前列，天然留在池内。
  2. `except: break`（L196-197）改为：**重试 1 次 → 仍失败则记录 WARNING 并继续下一页**（不静默丢页）。
- 伪代码：
```python
for page in range(1, 20):
    url = (f"http://push2delay.eastmoney.com/api/qt/clist/get?"
           f"pn={page}&pz=100&po=1&np=1&fs=m:1+t:2&fields={fields}&fid=f6")  # 成交额降序
    for attempt in range(2):                      # 重试 1 次
        try:
            with no_proxy():
                r = _req.get(url, timeout=5, headers=headers)
            data = r.json()
            diff = data.get("data", {}).get("diff")
            if diff:
                all_items.extend(diff)
            break
        except Exception:
            if attempt == 1:
                logger.warning("EM ETF list page %d failed, skip", page)   # 不 break，继续下一页
```

**步骤 B — 主流宽基静态兜底注入（P0，使强制清单生效）**

- 文件：`backend/app/fetchers/etf_scanner.py::full_pipeline`（L622-646）
- 改动：维护主流宽基静态清单（510300/510500/510050/588000/159915/511090/518880 等），`full_pipeline` 组装候选池后**将清单成员从 `instruments` 表（静态元数据：规模/名称/代码）补录进对应层**，不依赖当日涨幅榜。
- 效果：`layer_ranking(required=CORE_REQUIRED)` 的注入（L514-524）从此能找到 510300/560600 → 强制清单真正生效。

**步骤 C — 板块配额（P1，防科创包场）**

- 文件：`backend/app/engine/allocation_engine.py::allocate`（L247-260 去重处）
- 改动：去重按归一化概念组后，**每组最多保留 composite 前 2 名**；另增加「科创系」聚合约束：名称含科创/半导体/芯片的候选合计 ≤ 卫星层预算的 50%。
- 伪代码：
```python
# 概念组去重后追加主题配额
tech_candidates = [s for s in survived if any(t in s["name"] for t in
                    ("科创", "半导体", "芯片", "AI", "人工智能"))]
if sum(w for w in tech_candidates) > s_budget * 0.5:
    # 按 composite 降序保留，超出部分裁剪（权重回补其余卫星）
```

**步骤 D — 卫星数量下限（P1）**

- 文件：`backend/app/engine/allocation_engine.py::_filter_satellite_by_profile`（L341-347）
- 改动：KEEP_RATIO 裁剪后 `keep_count = max(4, ...)`（预算允许时卫星 ≥ 4 只）；候选不足 4 时从 core 层未入选者按 composite 降序补足。

**步骤 E — C2 惩罚触发条件修正（P1）**

- 文件：`backend/app/engine/allocation_engine.py` L219-228
- 改动：估值信号需「有意义的非零」才视为可用——排除字段错位值（黄金等无估值概念标的的 +3.9 类假信号）与 `ln_mcap/ln_float_mcap`（L220-221 已有排除，扩展到估值维度）；否则判定 `valuation_missing=True` → 防御型科创惩罚分支正常触发。

#### 9.6.4 TDD 测试计划（先写失败单测）

`tests/test_design_candidate_pool.py` 新增：

| 用例 | 断言 |
|------|------|
| `test_pool_sorted_by_amount` | mock EM 列表接口响应 → `_fetch_em_etf_list` 请求 URL 含 `fid=f6` |
| `test_pool_page_fail_continues` | mock 第 1 页抛异常 → 不抛错、返回第 2 页起数据、WARNING 日志 |
| `test_core_required_injected` | mock 候选池无 510300 → `full_pipeline` 输出 core 含 510300（静态兜底） |
| `test_defense_required_injected` | mock 候选池无 518880 → 输出 defense 含 518880 |
| `test_sector_quota` | mock 全科创候选 → 归一化概念组每类 ≤2、科创系合计 ≤ 卫星预算 50% |
| `test_satellite_min_count` | mock 因子矩阵 → 每方案卫星 ≥ 4 |
| `test_c2_penalty_defensive_kcb` | mock 估值因子为错位值（黄金 +3.9）→ 防御型科创候选 c2_bonus=-1.5 生效 |

集成用例：`test_design_core_contains_wide_basis` — mock 完整管道 → 三套方案 core 至少含 1 只主流宽基（510300/510500/510050/588000 之一）。

#### 9.6.5 验收条件（量化）

1. 组合设计三套方案：core 层至少 1 只来自主流宽基清单（510300/510500/510050/588000/159915）。
2. 每方案卫星 ≥ 4 只；防御型方案科创系卫星权重 ≤ 10%。
3. 归一化概念组在卫星层不重复（每组 ≤1 只入选权重位，或 ≤2 只候选）。
4. `pytest tests/test_design_candidate_pool.py` 全绿。

#### 9.6.6 风险与回退

| 风险 | 缓解 |
|------|------|
| 成交额排序冷门时段失真（开盘首分钟） | 合并规模 `fund_scale` 加权（复用 layer_ranking 现有 30/70 加权逻辑）；极端情况回退代码序全量池 |
| 静态兜底清单引入流动性差的同名 ETF | 清单仅取 instruments 表内**规模最大**的同代码 ETF，并带成交额校验 |
| 配额裁剪导致预算未用满 | 裁剪回收的权重按 composite 顺序回补其余卫星；不引入 CASH 膨胀 |

---

### 🔬 专项：组合设计投资合理性评估（含证据）

> 对应新增 F1-8。本节先给出**证据化的问题清单**（方案快照 + 代码交叉验证），再给出修复优先级映射。候选池根因已在 §9.6 覆盖，本节聚焦**因子数据正确性 → 市场上下文 → 理由生成 → 信号聚合**四层。

#### 9.7.1 现象证据（全部来自 `logs/design_latest_full.json` 实测）

**A. 三套方案高度重叠，差异仅剩预算参数机械缩放**

| 维度 | 证据 | 问题 |
|------|------|------|
| core 重叠 | 562320 出现 3/3 套、563080/562330/562340/563030 各 2/3 套 | 三方案核心几乎相同，未体现风偏差异 |
| satellite 重叠 | 589720 出现 3/3 套、589420 2/3、589560 2/3 | 卫星亦高度重叠 |
| 唯一差异 | 权重 + 现金（32%/27%/22%）+ 参数（er 0.08/0.11/0.16、mdd -0.12/-0.18/-0.35） | 方案 = 预算模板机械缩放，非因子驱动差异化 |

**B. 因子数据正确性（选标依据本身不可信）**

| 证据 | 实测值 | 问题 |
|------|--------|------|
| RSI 全面异常 | 方案内 RSI 全部 <3（562320 RSI 2.4、562330 1.4、563080 1.0、562340 0.4、589720 0.2、518880 0.3） | 真实 RSI（562320 实测 ~65.3）严重不符；K 线来源/口径 bug（F1-5 同源） |
| 黄金「估值因子 +3.926」 | 518880 黄金 ETF 出现估值因子 +3.926、技术面 +2.833，而 MACD 为负、RSI 0.3 | 字段错位：黄金无 PE 估值概念；技术面正分与负向指标自相矛盾 |
| 信号自相矛盾 | 589720 技术 -0.408 / 估值 -0.462 却判「综合信号偏多」 | 单靠动量 +1.047 拉平；信号聚合规则需复核 |

**C. rationale 模板错位（理由与标的属性不符）**

| 证据 | 问题 |
|------|------|
| 589850 科创50 / 589980 科创100 被套「作为组合压舱石，低波动宽基」模板（rationale.py L15 短语池） | 高波动成长指数被冠「压舱石/低波动」——模板未绑定标的实际波动属性 |
| 562320 rationale 截断为「…作为组合压」；562330 出现「在方案中在方案中」重复拼接 | 模板字符串拼接缺陷 |
| 562000 标注「unknown方向」 | tracked_index 提取缺失（F10 富集失败） |

**D. market_context 数据缺失（方案与市场大环境脱节）**

| 字段 | 快照值 | 期望 |
|------|--------|------|
| `index_realtime` | 0 条 | ≥3 条（上证/深成/创业板） |
| `sector_momentum` | 0 条 | ≥5 条（领涨/领跌板块） |
| `fund_flow` | 全 0（total_symbols=18 但净流入 0） | 非全 0 的实际资金流 |
| `benchmark_stocks` | 0 条 | 若干龙头股信号 |

→ 编排器/LLM 完全没有市场大环境输入，方案仅由因子分机械排序生成，与「市场行情匹配度」脱节（F1-3/F1-4 同源）。

#### 9.7.2 根因分级与修复映射

| 级别 | 根因 | 涉及文件 | 对应 F 表 |
|------|------|---------|----------|
| R1 | 因子数据正确性：RSI K 线口径 bug、估值字段错位 | `backend/app/factors/factor_registry.py`、`backend/app/services/market_data_hub.py` | F1-5（已有） |
| R2 | market_context 采集链路缺失（index_realtime/sector_momentum/fund_flow 全空） | `backend/app/services/llm_context.py`、`backend/app/routers/analysis.py` | F1-3/F1-4（已有） |
| R3 | rationale 模板未绑定标的属性（按 layer 固定套用短语池） | `backend/app/engine/rationale.py` | F1-8 新增 |
| R4 | 候选池多样性（涨幅榜 Top25 → 无主流宽基、科创包场） | `backend/app/fetchers/etf_scanner.py`、`backend/app/engine/allocation_engine.py` | F0-5 / F1-8（§9.6 专项） |
| R5 | 信号聚合复核：技术+估值双弱判「偏多」 | `backend/app/analysis/signal.py`（或因子聚合处） | F1-8 新增 |

#### 9.7.3 修复优先级（实施顺序）

1. **R1 因子数据正确性**（最高优先——选标依据错了，后面全错）：RSI 与 `indicators` 端点对齐（F1-5 验收）；估值因子按资产类别禁用（黄金/债券类剔除估值字段）。
2. **R2 market_context 填充**：修复 index_realtime/sector_momentum/fund_flow 采集（F1-3/F1-4）。
3. **R3 rationale 绑定标的属性**：按 layer + 标的波动率/风格选模板短语，废弃固定「压舱石」；修复字符串拼接缺陷（截断/重复）。
4. **R4 候选池多样性**：§9.6 专项步骤 A-E。
5. **R5 信号聚合复核**：技术/估值/动量加权规则加「双弱不判多」约束，单因子极端值设封顶。

#### 9.7.4 验收条件（量化）

1. 三套方案 core 重叠 ≤1 只（或方案间 Jaccard 相似度 < 0.5）；卫星重叠 ≤1 只。
2. 防御型方案科创系卫星权重 ≤ 10%；方案 RSI 与 `indicators` 端点一致（F1-5 同验收）。
3. rationale 无模板拼接缺陷（无截断、无「在方案中在方案中」重复）；科创50/科创100 不再出现「压舱石/低波动」措辞。
4. `market_context`：index_realtime ≥3 条、sector_momentum ≥5 条、fund_flow 非全 0。
5. 无「技术+估值双弱却判偏多」信号输出（R5 约束生效）。

---

### 🔬 专项：热点板块/热门个股数据修复 + 快速分析入口（P2）

> 覆盖 F2-3（/sectors/heat 404）与新增 F2-6（字段契约修复）/F2-7（快速分析入口）。本节含实测证据（三个数据源全部返回正常，问题在字段契约与路由）+ 隐藏断裂（UnifiedAnalysis 分析 API 未接线）+ 修复步骤 A-F + TDD 计划 + 量化验收。

#### 9.8.1 问题现象与影响（用户观察 + 实测）

| 现象 | 实测证据 | 影响 |
|------|---------|------|
| 热点板块 tab 显示为空 | `fetch_hot_plates(15)` 实测返回 **11 条**（字段 `secu_name`/`up_reason`/`plate_stock_up_num`/`stock_list`，其中 `stock_list` 是**字符串化的列表**）；前端模板（SectorHeatMap.vue L39-45）读的是 `plate_name \|\| name`、`reason \|\| hot_reason`、`lead_stocks \|\| stocks` → **字段全不匹配 → 每行渲染为空** | 用户看到"热点板块是空的"，实为数据被前端丢弃 |
| 板块热度 tab 报 404 | 前端 `getSectorHeat` → `GET /market/sectors/heat`；后端 market.py 路由清单**无此路由**（F2-3 记录在案）；但 `fetch_sector_heat(20)` 实测返回 **20 条正常**（plate_code/rank/cur_heat/rank_change/is_new/plate_name） | 数据源活着，路由缺失 → 404 |
| 热门个股信息太少 | 前端 stock tab（L82-90）只渲染 `name`/`symbol`/`change_pct`；hub enrich 后数据（market_data_hub.py L1405-1455）实有 `price`/`change_amt`/`turnover`/`volume`/`sector`/`tag`（含 `concept_tag` 概念标签，字符串形式） | 用户无法判断个股成色与所属板块 |
| **隐藏断裂：UnifiedAnalysis 分析入口实际没接 API** | `frontend/src/api/index.js` 的 `marketApi` **没有** `sectorAnalysis`/`marketAnalysis` 方法；UnifiedAnalysis.vue L182-184 用 `marketApi.sectorAnalysis?.()`（可选链）→ undefined → 走 L190-197 fallback，仅返回「✅ 查询完成」字符串，**未调用任何真实分析接口** | AI 分析入口形同虚设；快速入口若不先修此断裂，做了也白做 |

#### 9.8.2 根因分析

| # | 根因 | 涉及文件 |
|---|------|---------|
| R1 | 热点板块/板块热度/热门个股三处**前端字段契约与后端数据源字段不一致**（历史演进中数据源换过字段名，前端模板未同步） | `frontend/src/components/market/SectorHeatMap.vue` L39-45/L59-69/L82-90、`backend/app/fetchers/sector_fetcher.py` L336-375 |
| R2 | `/market/sectors/heat` 路由缺失（数据源存在、hub 有方法、仅未暴露） | `backend/app/routers/market.py`（F2-3） |
| R3 | `stock_list`/`tag` 以**字符串形式**存于数据源行内，前端无解析层（直接当数组/对象用 → undefined） | `backend/app/fetchers/sector_fetcher.py`、`backend/app/services/market_data_hub.py` L1405-1455 |
| R4 | UnifiedAnalysis 依赖的 `marketApi.sectorAnalysis/marketAnalysis` **从未定义**，可选链静默降级为 fallback 假成功 | `frontend/src/api/index.js`、`frontend/src/components/market/UnifiedAnalysis.vue` L182-197 |
| R5 | SectorHeatMap 无任何事件发射（不像 WatchlistPanel 有 `@select-symbol`），热点行无法联动分析区 | `frontend/src/components/market/SectorHeatMap.vue` |

#### 9.8.3 修复步骤（按依赖排序）

**步骤 A — 后端字段归一化（R1/R3，保持前端契约稳定）**

- 文件：`backend/app/services/market_data_hub.py`（`get_hot_plates` L958、`get_stock_hot_rank` L1389）与 `backend/app/fetchers/sector_fetcher.py` L336-375
- 改动：
  1. `get_hot_plates`：`secu_name→name`、`up_reason→reason`、`plate_stock_up_num→stock_count`；`stock_list` 用 `ast.literal_eval` 安全解析成数组 → `lead_stocks`（元素取 `secu_code/secu_name`）。
  2. `get_stock_hot_rank` enrich 时把 `tag` 字符串解析为 `concept_tags: [...]` 数组（同样 `ast.literal_eval` + try/except 兜底）。
- 伪代码：
```python
def _parse_stock_list(s: str) -> list[dict]:
    if isinstance(s, list):
        return s
    try:
        return ast.literal_eval(s) if s else []
    except Exception:
        return []
```

**步骤 B — 新增 `GET /market/sectors/heat` 路由（R2，F2-3）**

- 文件：`backend/app/routers/market.py`
- 改动：新增端点，调 `market_data_hub.get_sector_heat(limit)`（数据源已实测正常），响应归一化 `plate_name→name`、`cur_heat→heat_index`、保留 `rank_change`/`is_new`。
- 契约（对齐 api-contracts/market/）：
```json
{ "items": [{ "rank": 1, "name": "AI智能体", "heat_index": 13501.4,
              "rank_change": 5, "is_new": 0, "plate_code": "cls82558" }], "total": 20 }
```

**步骤 C — 热门个股信息增强（前端 stock tab）**

- 文件：`frontend/src/components/market/SectorHeatMap.vue` L74-92
- 改动：行内新增展示 `price`（现价）、`sector`（所属板块）、`turnover`（成交额，万/亿格式化）、`concept_tags`（前 2-3 个概念标签 chip）。
- 样式：复用现有 `text-up/text-down`（红涨绿跌）；概念标签用轻量 chip 样式。

**步骤 D — UnifiedAnalysis 分析 API 接线修复（R4，前置条件）**

- 文件：`frontend/src/api/index.js` + `frontend/src/components/market/UnifiedAnalysis.vue`
- 改动：
  1. `marketApi` 新增真实方法（对齐后端已验证端点）：
```js
symbolAnalysis: (data) => api.post('/analysis/symbol-analysis/stream', data),
sectorAnalysis: (data) => api.post('/analysis/sector-analysis/stream', data),
```
  2. UnifiedAnalysis `doAnalyze` 改用 `useLLMStream().start()`（复用 MarketReport/AiAdvisor 已验证的 SSE 模式）：
     - `symbol` 模式 → `POST /analysis/symbol-analysis/stream`（body: `{symbol, name, asset_type}`）
     - `sector` 模式 → `POST /analysis/sector-analysis/stream`（body: `{sector_code, sector_name, sector_type, market}`）
     - 删除 fallback 假成功分支（L190-197）。
- 效果：AI 分析从「✅ 查询完成」变为真实流式分析内容（修复隐藏断裂）。

**步骤 E — 快速分析入口（R5，用户核心需求）**

- 文件：`frontend/src/components/market/SectorHeatMap.vue`、`frontend/src/views/MarketAnalysis.vue`
- 设计（复用 WatchlistPanel → `@select-symbol` → `selectedSymbol` → UnifiedAnalysis 既有联动模式，MarketAnalysis.vue L45/L92/L154-161）：

  1. **个股行**（stock tab）加两个按钮：
     - 「技术分析」→ 打开轻量弹窗 `TechnicalAnalysisModal`（复用后端 `GET /market/indicators/{symbol}` + `GET /market/signal/{symbol}`，展示价格/RSI/MACD/KDJ/MA + 综合信号与方向）
     - 「AI 分析」→ `emit('analyze', { mode: 'symbol', query: code, name })` → MarketAnalysis 设置 `selectedSymbol`（既有链路，自动触发 UnifiedAnalysis symbol 模式分析）→ `scrollTo('symbol')`
  2. **板块行**（hot/heat tab）加「AI 分析」按钮：
     - `emit('analyze', { mode: 'sector', query: plate_code, name: plate_name })` → UnifiedAnalysis 需支持外部触发 sector 模式：扩展 props 为 `externalTrigger: { mode, query, name }`，watch 后设置 `activeMode` + `query` + `doAnalyze()`（替代/兼容现有 `selectedSymbol`）
  3. 交互细节：点击后滚动到 `anchorSymbol`（复用现有 `scrollTo('symbol')`），分析区自动聚焦触发；技术分析弹窗内支持「转 AI 分析」二次跳转。

**步骤 F — 后端板块代码映射兜底**

- 文件：`backend/app/routers/analysis.py`（`/sector-analysis/stream` 内）
- 改动：热板块/热度的 `cls` 前缀代码（cls82558）在 sector 分析前做代码归一化（截断前缀取数字段 82558 → 匹配 BK/行业板块），映射失败返回结构化错误而非空结果。

#### 9.8.4 TDD 测试计划

后端 `tests/test_sector_heat.py` 新增：

| 用例 | 断言 |
|------|------|
| `test_sectors_heat_route` | `GET /market/sectors/heat?limit=20` → 200，items 含 name/heat_index/rank_change |
| `test_hot_plates_normalized` | mock `fetch_hot_plates` 返回原始字段 → hub 输出含 name/reason/lead_stocks 数组 |
| `test_stock_list_parse_safe` | `stock_list` 为非法字符串 → 返回 `[]` 不抛错 |
| `test_stock_hot_rank_concept_tags` | enrich 后含 `concept_tags` 数组 |
| `test_cls_code_normalized` | sector 分析入口 cls82558 → 归一化成功（mock LLM） |

前端 `src/test/SectorHeatMap.spec.js` 新增：

| 用例 | 断言 |
|------|------|
| `renders_hot_plates` | mock hot-plates 响应（原始字段）→ 行显示 name/reason/lead stocks |
| `renders_sector_heat` | mock sectors/heat 响应 → 行显示 name/heat_index/rank_change |
| `renders_stock_extra` | mock stock-hot-rank 响应 → 行显示 price/sector/turnover/concept chips |
| `emit_analyze_symbol` | 点击「AI 分析」→ emit `analyze {mode:'symbol', query:'688825'}` |
| `emit_analyze_sector` | 点击板块行「AI 分析」→ emit `analyze {mode:'sector', query:'cls82558'}` |
| `technical_modal_opens` | 点击「技术分析」→ 弹窗出现并请求 indicators/signal |

#### 9.8.5 验收条件（量化）

1. 热点板块 tab 显示 ≥10 行（名称 + 涨跌幅 + 领涨股 + 上榜理由），无空行。
2. 板块热度 tab 200 无 404，显示名称/热度/排名变化（↑↓）。
3. 热门个股行显示 price/sector/turnover/概念标签（≥2 个 chip），且红涨绿跌正确。
4. UnifiedAnalysis 的 symbol/sector 分析返回**真实流式内容**（非「✅ 查询完成」）。
5. 热门个股「AI 分析」→ 分析区自动聚焦并触发；「技术分析」弹窗展示 indicators+signal。
6. `pytest tests/test_sector_heat.py` + `npm test`（新增用例）全绿。

#### 9.8.6 风险与回退

| 风险 | 缓解 |
|------|------|
| `ast.literal_eval` 解析失败 | try/except 返回 `[]`；绝不 eval |
| 热板块 `cls` 代码与 BK 板块映射不全 | 归一化失败返回结构化错误（`{detail: "板块映射失败"}`）+ 前端降级为搜索 |
| SSE 流式接入回归 | 复用已验证的 `useLLMStream`（MarketReport/AiAdvisor 同款）；保留 60s 超时与取消 |
| 弹窗与移动端布局 | 技术分析弹窗限宽 + 可滚动；按钮行在窄屏折行 |

---

### 🔬 专项：资讯 AI 智能分析 UX 与质量（P2）

> 覆盖新增 F2-8（面板无反馈）与 F2-9（分析质量约束）。本节含实测证据：后端 `/analysis/news-impact` 链路**功能完全正常**（3 条新闻实测均返回完整结构且结论合理），「没反应」根因是前端 UX 缺陷；「不合理」为单条 LLM 输出波动，prompt 加硬约束压制。

#### 9.9.1 问题现象与影响（用户观察 + 实测）

| 现象 | 实测证据 | 影响 |
|------|---------|------|
| 点击「AI 智能分析」后前端「没反应」 | 后端 `/analysis/news-impact` 实测 3 次均返回完整 `{impact_scope, affected_holdings, summary, disclaimer}`；前端 `NewsView.vue` L63-90 面板模板字段全部匹配；axios 拦截器 `(response) => response` 不包装（api/index.js:12）→ 数据链路通。**但面板 `<section v-if="impactPanel">` 渲染在新闻列表 `<ul>` 之后（页面最底部）**，按钮 `:disabled="analyzing"` 文字不变（L54）、无自动滚动/锚点/提示 → 面板出现在视口外，用户感知「没反应」 | 用户以为功能坏了；实际结果被丢弃在页面底部不可见 |
| 分析结论「不太合理」 | 3 条实测：①央行降准→利好 A 股宽基/金融地产 ✅；②日本硅岛半导体停产→只列相关 2 只（159516/159338），明确「对券商黄金影响有限」✅ 克制未硬凑；③黄岩岛自然保护法（与组合无关）→明确「半导体无直接关联」、利好黄金避险 ✅。**LLM 本身判断合格**，偶发「不合理」为单条输出波动（非确定性） | 用户对 AI 结论信任度下降 |

#### 9.9.2 根因分析

| # | 根因 | 涉及文件 |
|---|------|---------|
| R1 | **面板渲染位置在页面底部 + 无滚动/loading 反馈**：点击后结果不可见 = 感知「没反应」（UX 缺陷，非功能断裂） | `frontend/src/components/NewsView.vue` L54/L62-90 |
| R2 | prompt 缺「无直接关联时明确声明」硬约束：LLM 偶发将无关新闻强行关联持仓（本轮实测未触发，属概率性风险） | `backend/app/analysis/llm.py` L840-866 |

#### 9.9.3 修复步骤（按依赖排序）

**步骤 A — 前端交互重构：行内展开（R1，方案 A 已确认）**

- 文件：`frontend/src/components/NewsView.vue`
- 设计原则：分析是针对**某一条**新闻的，结果必须出现在**该条新闻卡片内**（而非页面底部面板）——结果与所分析新闻强关联、不打断阅读位置、无需滚动。
- 改动：
  1. 新增状态：`impactTarget`（当前展开分析的新闻 id）、`impactPanel`（结果数据）、`analyzing`（全局 loading）。
  2. 模板：在每条新闻卡片 meta 区（L50-57）下方加条件渲染展开区：
  ```vue
  <div v-if="impactTarget === item.id" class="impact-inline">
    <div v-if="analyzing" class="impact-loading">🤖 AI 分析中…</div>
    <div v-else-if="impactPanel" class="impact-inline-body">
      <!-- 复用原面板内容：summary / impact_scope / affected_holdings / disclaimer -->
      <button class="impact-close" @click="impactTarget = null; impactPanel = null">✕</button>
    </div>
  </div>
  ```
  3. 交互规则：
     - 点击某条「AI 智能分析」→ `impactTarget = item.id`，该条卡片下方展开 loading → 完成后在该条卡片内展示结果。
     - 分析中点击其他新闻 → 忽略（按钮全局 `:disabled="analyzing"`），避免竞态。
     - 点击已展开的条目 → 收起（toggle）；或点展开区 ✕ 收起。
     - 分析失败 → 该条展开区显示错误文案 + 重试按钮，而非全局 toast 后无痕。
  4. 删除原页面底部 `<section v-if="impactPanel">` 面板（L62-90 迁移进卡片内）。
- 伪代码：
```js
const impactTarget = ref(null)   // 当前展开分析的新闻 id
const impactPanel = ref(null)    // 最近一次分析结果
const analyzing = ref(false)

async function analyze(item) {
  // 再次点击已展开条目 → 收起
  if (impactTarget.value === item.id && impactPanel.value) {
    impactTarget.value = null; impactPanel.value = null
    return
  }
  impactTarget.value = item.id
  impactPanel.value = null
  analyzing.value = true
  try {
    const res = await newsApi.newsImpact({
      news: { title: item.title, content: item.content },
      portfolio: (store.etfs || []).map(e => ({ symbol: e.symbol, name: e.name })),
    })
    impactPanel.value = res.data
  } catch {
    impactPanel.value = { error: true }   // 展开区显示失败 + 重试
  } finally {
    analyzing.value = false
  }
}
```
- CSS：`.impact-inline` 卡片内边框高亮 + 入场淡入；`.impact-inline-body` 长文本限高滚动（max-height + overflow-y auto）。

**步骤 B — prompt 质量约束（R2）**

- 文件：`backend/app/analysis/llm.py`（`analyze_news_impact` prompt，L840-850）
- 改动：在 prompt 中追加：
  ```
  若新闻与组合内标的无直接关联，须明确回答「无直接影响」，禁止强行关联；
  只列出实际受影响的标的，宁缺毋滥；若组合为空，回答对市场整体的影响。
  ```

#### 9.9.4 TDD 测试计划

**后端（`tests/test_news_impact_quality.py`）**

1. `test_no_direct_link_explicitly_says`：mock LLM 返回含「无直接影响」的 JSON → 断言 `impact_reason` 含该字样（prompt 约束生效）。
2. `test_irrelevant_news_not_forced_into_holdings`：mock LLM 返回只含 1 只相关标的 → 断言 `affected_holdings` 不强行塞满全部持仓。
3. `test_empty_portfolio_market_scope`：portfolio 为空 → 返回 `impact_scope` 为市场整体（Z32 回归）。

**前端（`src/test/NewsView.spec.js`）**

4. `test_analyze_expands_inline`：点击某条「AI 智能分析」→ 断言该条**卡片内**出现分析区（不再依赖页面底部面板）。
5. `test_analyze_shows_loading_text`：点击后展开区显示「AI 分析中…」，完成后消失并显示结果。
6. `test_analyze_switches_target`：先分析 A 再分析 B → 断言 A 卡片内展开区消失、B 卡片内出现。
7. `test_analyze_toggle_close`：已展开的条目再次点击 → 收起（`impactTarget` 清空）。
8. `test_analyze_failure_inline`：mock 失败 → 该条展开区显示错误 + 重试按钮，页面不报全局错。

#### 9.9.5 量化验收

1. 点击某条新闻「AI 智能分析」→ 该条卡片下方**即时**展开「AI 分析中…」，成功后结果显示在该条卡片内（无滚动、无跳转）。
2. 3 条基线样本（降准/半导体停产/黄岩岛）结论合理且无强行关联（2 次运行均稳定）。
3. `pytest tests/test_news_impact_quality.py` + `npm test` 全绿。

#### 9.9.6 风险与回退

| 风险 | 缓解 |
|------|------|
| 长文本撑爆卡片 | `.impact-inline-body` 限高（max-height ~360px）+ overflow-y auto |
| 分析中切换新闻竞态 | 分析中全局禁用所有「AI 智能分析」按钮（`:disabled="analyzing"`） |
| 收起误操作 | 仅 ✕ 与再次点击触发收起；结果保留在 `impactPanel` 可重开 |
| prompt 硬约束导致 LLM 过度保守（该分析的也省略） | 约束措辞「宁缺毋滥」但保留「实际受影响标的必须列出」；基线样本回归 |

---

## 十、实施优先级路线图

```
第一梯队（P0 — 立即，预计 1 人日）
  F0-3 WS nginx 代理修复（30min）   F0-4 K 线降级链增强（半日）
  F0-5 候选池修复（成交额排序 + 宽基兜底注入，见 §9.6 步骤 A/B）
第二梯队（P1 — 本周，预计 2-3 人日）
  F1-1 港股行情 / F1-2 单只降级链 / F1-3 LLM 上下文 / F1-4 市场参数
  F1-5 因子一致性 / F1-6 成分股 / F1-7 LLM 输出后处理
  F1-8 投资合理性（§9.7 R1-R5：因子正确性→market_context→rationale→信号聚合）
第三梯队（P2 — 下迭代，预计 2-3 人日）
  F2-1 组合计算并行 / F2-2 首页性能 / F2-5 预热并行
  §9.8 专项：F2-3 sectors/heat 路由 + F2-4 UnifiedAnalysis 接线 + F2-6 字段契约/个股信息 + F2-7 快速分析入口（一个批次交付，前端为主）
  §9.9 专项：F2-8 资讯面板 UX 反馈 + F2-9 资讯分析质量约束（一个批次交付，前端为主）
  §9.6 步骤 C-E（板块配额/卫星下限/C2 惩罚修正，与 F0-5 同批或紧随）
  T1/T2 防回归测试（与 F0 修复同批交付：F0 交付即加 T1/T2，拦截两个 P0 bug 回归）
第四梯队（P3-P4 — 持续）
  F3-1~F3-7 质量完善（Z04 因子补齐见 §9.5 专项 4 步方案；Z07 限流重试可提前至 P2 并行）
  T3-T6 测试防护补强
```

> 说明：Z07（LLM 429/23.2% 错误率）影响 llm-advice/llm-report 核心体验，因免费模型限流属常态（Retry-After 可达 8h），F3-6 重试策略成本低，可提前至 P2 并行推进；T1/T2 为防回归能力最强项，与 F0 修复同批交付可拦截本轮 P0 bug 回归。

实施必须遵循 AGENTS.md「先写 API 契约 → 写失败单测 → 改代码 → 跑 verify_e2e.py → commit」流程。

---

## 附录 A：测试数据快照

- 预热: 1.765s（global_indices 1468ms 占 83%）
- 组合设计: completed，3 套方案，权重和 1.0，现金 22-32%
- 策略检查: completed（LLM 超时降级），10 只场内标的，hold 建议
- Lighthouse: 首页 60 / market 97 / portfolio 76 / news 96
- perf_diag: 46/49（3 个脚本 405），慢点 calculate 8.2s / pnl-history 8.5s / realtime/portfolio 1.9-4.5s
- e2e: 185/201（16 失败：3 性能 gate + 9 因子 flaky + 4 脚本噪音）
- LLM: 462/1995 错误（23.2%），opencode_zen 429 限流 Retry-After 8h
- 因子: 33 总 / 20 valid / 3 static / 3 warn / 7 no_data；IC 23 条，avg_ic 0.22

## 附录 B：本轮修改文件

| 文件 | 修改 |
|------|------|
| `backend/app/config.py` | `Settings.Config` 增加 `extra="ignore"` |
| `docker-compose.yml` | `backend` 服务增加 `DATABASE_URL` 容器路径覆盖 |
| `backend/.env` | 增加 `PROFILE_WARMUP=1`（诊断用） |

## 附录 C：修订记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-07-31 | 初稿：15 步诊断全量结果 + P0-P4 修复方案 + 测试防护补强 |
| v1.1 | 2026-07-31 | 首轮 review 修订：修正港股降级链顺序（sina→tencent→dongfang）、LLM 泄漏术语；补步骤索引表/持仓全表/e2e 失败完整清单/P1-P2 涉及文件列/P3 验收条件；T1/T2 提前至 P2；T3/T6 断言补全 |
| v1.2 | 2026-07-31 | 二轮 review 修订：P1/P2/P3 表头补列（涉及文件/验收条件，修复渲染错位）；T1/T2 调度措辞修正（F0 交付即加）；§5.3 持仓表补全 10 只含权重；T4 补 daily-pnl 参数修复；calculate 耗时口径统一（8.2s/8257-8287ms）；F0-4 涉及文件补全路径 |
| v1.3 | 2026-07-31 | Z04 细化：新增 §9.5 专项修复方案（根因三层缺口/10 因子依赖清单/步骤 A-D 含伪代码/TDD 测试计划/量化验收/风险回退）；F3-4 表项与 Z04 问题行改为引用专项章节 |
| v1.4 | 2026-08-01 | 新增 §9.6 专项「候选池修复」（核心层偏离主流宽基：涨幅榜 Top25 根因链 5 层 + 步骤 A-E 含伪代码 + TDD 7 用例 + 量化验收）与 §9.7 专项「投资合理性评估」（方案快照证据 A-D + 根因 R1-R5 映射 + 修复优先级 + 量化验收）；F 表新增 F0-5/F1-8；路线图更新（F0-5 进 P0、F1-8 进 P1、§9.6 步骤 C-E 进 P2） |
| v1.7 | 2026-08-01 | §9.9 专项交互方案升级为**行内展开**（用户确认方案 A）：分析结果直接显示在对应新闻卡片内（删除页面底部面板 + scrollIntoView），新增 `impactTarget` 状态与 toggle/切换/失败重试交互；TDD 前端用例更新为 5 条（展开/loading/切换/收起/失败）；量化验收与风险表同步更新 |
| v1.6 | 2026-08-01 | 新增 §9.9 专项「资讯 AI 智能分析 UX 与质量」：实测 3 条新闻（降准/半导体停产/黄岩岛）后端 `/analysis/news-impact` 链路功能正常、结论合理，定位「没反应」为前端 UX 缺陷（面板渲染在列表底部 + 无滚动/loading 反馈）+ 「不合理」为 LLM 单条波动；修复步骤 A（scrollIntoView + 按钮文字 + 锚点高亮）/B（prompt「无直接关联须明确声明」硬约束）+ TDD 5 用例 + 量化验收；F 表新增 F2-8/F2-9；路线图 P2 批次更新 |
| v1.5 | 2026-08-01 | 新增 §9.8 专项「热点板块/热门个股数据修复 + 快速分析入口」：实测三个数据源正常（hot_plates 11 条/heat 20 条/stock_hot_rank 50 条）、前端字段契约不匹配（secu_name vs plate_name 等）+ /sectors/heat 路由缺失 + 隐藏断裂（marketApi 无 sectorAnalysis 方法、UnifiedAnalysis 走 fallback 假成功）+ 修复步骤 A-F（后端归一化/新增路由/信息增强/流式接线/快速入口/代码归一化）+ TDD 计划 + 量化验收；F 表新增 F2-6/F2-7、F2-3/F2-4 细化引用 §9.8；路线图 P2 批次更新 |
