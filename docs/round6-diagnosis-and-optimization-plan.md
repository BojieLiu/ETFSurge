# ETF Surge — 第六轮全链路诊断与优化修复方案 (v1.0)

> 诊断环境：Docker prod 集群（backend :8000 / frontend :80 / redis :6379），镜像 `etf_surge-backend:latest (66ee9f07d4ec)`、`etf_surge-frontend:latest (d3785559a5cf)`，2026-08-03 构建（工作树 HEAD `e4a59aa` + 本轮 build 修复）。
> 诊断方法：预热 profiler（PROFILE_WARMUP=1）、组合设计/策略检查实测（LLM deepseek 主 + opencode_zen 备）、A/HK/US 全链路 API 实测、Lighthouse 13.4.1（4 页面）、verify_e2e 全量 22 模块（266/278）、perf_diag 全端点、代码级修复状态核查、容器内 mootdx 专项验证。
> 状态图例：🔴 严重 / 🟡 中 / 🟢 正常 / ✅ 已验证修复
> 本方案为**实施标准设计**，按 AGENTS.md 契约先行 + TDD 流程执行；本轮**不实施**（除 §六 构建回归修复——为镜像构建成功的必要前置，已在诊断中顺手完成）。
> **诊断配置回收**：docker-compose.yml 为诊断临时启用的 `PROFILE_WARMUP=1` 与 `./backend/logs:/app/logs` volume，**回收容器时一并移除**（见 §九）。

---

## 一、执行摘要

本轮（round6）在 Docker prod 环境完成 15 项诊断动作（构建回收 / 预热诊断 / 设计+策略检查 / 多市场分析 / 热点 / 自选 / 持仓 / 资讯 / 因子 / 数据断裂 / docs 清单 / 前端 Lighthouse / 后端性能 / 测试防护 / 文档）。核心结论：

1. **round5 修复主体已验证生效**：R5-0-1（A500 入核心）、R5-0-2（核心层重叠 0）、R5-0-4（红利 ≤15%）、R5-1-2（rule 兜底 holdings_analysis 骨架）、R5-1-5（IC 周期计算 + 26 条持续更新）、R5-1-6（最后错误透传 + LLM 快速失败）、R5-2-5（HK/US 报告本地指数）、R5-09（news/stock 键归一化）、P0-2/P1-3/P1-4/P1-5/P2-2/P2-4/P2-6 全部实测 PASS；前端首页 Lighthouse P56→P89（CLS 0.388→0.189）。**（测试基线：后端单测 1328 + 前端 342，均绿——但仅宿主机，见 §7.2-①）**
2. **发现 2 项严重构建/运行回归（round5 R5-2-4 实施引入）**：①mootdx 0.11.7 依赖 `httpx<0.26` 与项目 `httpx>=0.27` 冲突 → `docker build` ResolutionImpossible 必失败；②`--no-deps` 安装漏 tenacity → 容器内 mootdx `ModuleNotFoundError`。**后端单测 1328 在宿主机全绿但镜像无法构建**——Docker 构建从未纳入测试门禁（§七 1）。
3. **mootdx 容器内空转是性能劣化总根因**：`Quotes.factory()` 无 server 参数时依赖 `~/.mootdx/config.json` BESTIP 缓存，宿主机有（180.153.18.172:80）、**全新环境（容器/CI）无** → 降级链第一环空转 → report A 首测 **309s**（round5 62.7s）、策略检查"加载持仓"阶段 **55s**、预热 market_cache **6.2s**、verify_e2e shared_executor 64/64 饱和。复制 config 后 report A → **52.5s**（§三/§五/§六）。
4. **A01 预热门禁字段不匹配静默失效**：verify_e2e 读 `total_elapsed/duration_ms`，`/api/v1/system/warmup` 只返回 `elapsed_seconds` → 门禁**恒走"未启用"分支恒 PASS**（§七 2）。
5. **数据源降级面仍在**：东财 push2/index 接口限流（RemoteDisconnected）→ `get_index_realtime()` 空 → 设计报告"今日涨跌"全缺、AI 投顾无指数数据（R5-07/R5-1-3 注入不完整）；sector/concept 分析 limit=200 截断 → 半导体（BK1036）404；US 个股名称搜索空；sentiment/style 因子仍全 no_data。
6. **测试防护体系新增 6 类盲区**（§七）：Docker 未入门禁、门禁自检失效、mock 数据形态脱节、验收口径宽松、LLM 端到端断言缺失、LHCI 未接入。

---

## 二、诊断环境与方法（步骤 0-1）

| 项 | 值 |
|---|---|
| Docker 镜像 | etf_surge-backend:latest (66ee9f07d4ec)、etf_surge-frontend:latest (d3785559a5cf)（老镜像已回收） |
| 容器 | backend-1 :8000 / frontend-1 :80 / redis-1 :6379，/health 200 |
| 后端诊断工具 | 内置 WarmupProfiler（PROFILE_WARMUP=1）+ perf_diag.py 全端点 + verify_e2e 22 模块 |
| 前端诊断工具 | Lighthouse 13.4.1 + Chrome（首页/市场分析/组合分析/资讯 4 页面） |
| LLM | deepseek 主（成功）/ opencode_zen 备（500 频繁） |

**构建回归修复（§六前置）**：`docker build backend` 首次失败（ResolutionImpossible：mootdx 依赖 httpx<0.26 vs 项目 httpx>=0.27）。修复：requirements.txt 移除 mootdx 行（改 UTF-8 说明注释）+ Dockerfile 以 `--no-deps` 安装 mootdx/prettytable/tdxpy/**tenacity**（tenacity 为二次修复，见 R6-02）。新镜像 66ee9f07d4ec 构建成功。

---

## 三、后端预热性能诊断（步骤 1）

**总时长 12855ms（分段求和口径，首次采样含 mootdx 空转）/ 6.9s（墙钟并行口径）**（round5 3.36s；门禁 20s，✅ 未超失败线但劣化明显）。**注**：容器重启后二次采样为 12384ms（分段求和）/ 6.9s 墙钟——详见留存数据 `backend/logs/warmup_timing.json`；两次数值相近，结论一致。

| 分段 | 耗时（首次/二次采样） | 对比 round5 | 根因 |
|---|---|---|---|
| warmup_etf_cache | 6512 / 6291ms | 32ms → **~6.4s** | 镜像内 `app/data/etf_list_cache.json` 快照过期（ts>4h）→ 全量扫描 1617 只；且文件缓存在镜像层 `/app/app/data`（非挂载卷），容器重建必丢 |
| warmup_market_cache | 6220 / 5993ms | 2095ms → **~6.1s** | `get_portfolio_realtime → _call → run_sync` 4.5s 同步等待（mootdx 空转期 ~20s 级超时 + run_sync 池排队叠加） |
| warmup_global_indices | 3.2 / 5.5ms | 1089ms → **~4ms** ✅ | 快速失败/缓存命中路径 |
| init_db / redis_init | 42/40ms、78/55ms | 持平 ✅ | — |

**门禁失效**：verify_e2e A01 读 `wd.get("total_elapsed") or wd.get("duration_ms")`，`routers/system.py:23` 仅返回 `elapsed_seconds` → warmup_total 恒 0 → 恒 PASS（R6-03）。

**结论**：预热 6.9s < 20s ✅ 但较 round5 劣化 2-4 倍，两大热点（etf_cache 缓存不持久化 + market_cache mootdx 空转）均为可修复缺陷（R6-08）。

---

## 四、组合设计 + on_exchange 策略检查审阅（步骤 2）

### 4.1 执行结果

- **design task 158**（capital=500k）：completed 172s（LLM 阶段 ~145s，round5 75s 劣化）。三方案（防御/平衡/进攻）层预算完整、现金 15-21%。
- **strategy-check task 159**（on_exchange，capital=500k）：completed 65s（"加载持仓数据"阶段 55s → 性能热点 R6-02 关联；报告阶段 10s = LLM 500 快速失败 + rule 兜底）。

### 4.2 验收核对（round5 修复项）

| 验收 | 结果 | 证据 |
|---|---|---|
| R5-0-1 A500 入核心 | ✅ | 560600 出现在三方案核心层（防御/平衡/进攻各 7.6%/5.2%/5.45%） |
| R5-0-2 核心层重叠 ≤1 | ✅ | 剔除公共底仓（510300/560600）后两两重叠 0 只（round5 3 只） |
| R5-0-4 红利类 ≤15% | ✅ | 563020：防御 15%（core）/ 平衡 14.4%（satellite）/ 进攻 15%（satellite） |
| R5-1-2 兜底 holdings_analysis | ✅ | rule 路径非空（10 条，含 factor_summary/factor_availability 23/33/tech_signal/confidence，标注"规则引擎生成"）；industry 空 + risk_warnings WARN 诚实标注 |
| R5-1-6 最后错误透传 | ✅ | summary 含"最后错误：Server error '500 Internal Server Error' for url 'https://opencode.ai/zen/...'" |
| B3 建议 ≥2 种动作 | ✅ | 7 hold + 3 increase（hold 占比 70%，round5 90% 改善） |
| on_exchange 过滤 | ✅ | 10 条建议/分析全部场内标的，无场外混入 |
| P1-4/P2-6 显式降级 | ✅ | 今日涨跌"数据源不可用"；预期年化附"震荡市态调整系数为 0"说明 |

### 4.3 报告质量审阅（专业投资者视角）

**设计 368（design_text 7064 字符）**：
- ✅ 市场环境段数据真实自洽：上证 3809.66（-0.6%）/深证成指 13448.29（-1.0%）/创业板指 3302.55（-1.2%）/科创50 1552.89（**-5.1%**）——与 watchlist 588000 实时 -5.32% 吻合；市态 range_bound + 情绪 49.68 中性；"资金从科技成长向价值/债券迁移"的叙事逻辑清晰。
- ✅ 三层框架（核心 β / 卫星弹性 / 防御对冲）+ 量化操作纪律（企稳判定/急跌加仓/止损红线/再平衡）具体可执行，无追涨杀跌建议。
- ⚠️ **方案与文字张力**（R6-05 关联）：报告文字"科创50、芯片设计、AI 短期没止跌 1-4 周不追"，但进攻型核心层给科创50 588000 **16%** + 创业板 15% + 卫星创新药/新能源 16%——47% 高弹性配置 vs"不追"表述冲突；报告后段"3-12 个月超跌布局候选、等企稳信号"可解释，但**表格与文字脱节，未标注建仓节奏**。
- ⚠️ **同标的因子分跨方案不稳定**（R6-07）：563020 防御 core +1.11 / 平衡 -1.20 / 进攻 -1.51（差异 2.6）——疑为方案内 z-score 归一化所致，专业投资者会质疑因子稳定性。
- ⚠️ **因子分注释口径错误**：表格注"多因子评分（0~1）"，实际值域 -1.51~3.99（30年国债 3.99）。
- ⚠️ **卫星层预算未打满**：防御 satellite 预算 0.2 实配 12%（0.12），差额转现金 → 防御型现金 21%，报告未解释。
- ⚠️ **防御型单只集中**：510050 权重 21.06%（<30% 上限但偏高）；562000 "unknown方向"残留（行业映射缺失）。
- ⚠️ **技术指标数值失真**（R6-05）：表格"RSI 1.5 超卖区域 / MACD 0.4212"与真实指标（159338 RSI 39.8、MACD -0.007）尺度严重不符——rationale 生成引用的"RSI/MACD"实为归一化后因子分，名称误导。

**策略检查 159**：
- ✅ 三段式 reason、报告完整、LLM 超时诚实降级（500 快速失败 + 兜底 + 最后错误）。
- ⚠️ factor_availability 口径注记："23/33" 为 factor_registry 实时填充数（按因子值非零判定），与 `/factors/active` 的 status 统计（valid17+warn2+static3=22）口径不同，差 1 属口径差异非 bug。
- ⚠️ **summary 文案残留**（R6-15）：实际 500 快速失败（报告阶段 10s），但文案仍写"LLM 分析超时（60s 未返回）"。
- ⚠️ **信号口径不一致**（R6-06）：518880 策略检查 tech_signal=BUY（factor_registry technical.signal.overall）→ increase，但 `/market/signal/518880` = hold（market_service 规则，score 0.0）——两套信号系统分歧，用户困惑。
- ⚠️ **加载持仓 55s**（R6-02）：数据采集慢于 LLM 兜底本身。

### 4.4 专业投资者总评

设计报告逻辑/可读/数据自洽性良好，round5 方案结构缺陷（A500/重叠/红利）全部修复；**但技术指标数值失真（RSI 尺度）与"方案-文字张力"会削弱专业投资者信任**——方案可直接采信结构，指标解读需先修复 R6-05。策略检查在数据可用时可信（数据 23/33 因子、建议带依据）；**持仓加载 55s 的体验不可接受**（R6-02 修复后应大幅改善）。

---

## 五、多市场行情分析（步骤 3）

| 链路 | 结果 | 备注 |
|---|---|---|
| A 综合研判 llm-report | 🟡→✅ 309s 首测超时 → mootdx 修复后 **52.5s** | 科创50 -5.08% 等真实数据；**309s 根因 = mootdx 容器空转 + 东财限流**（R6-02） |
| HK 综合研判 llm-report | ✅ 61s | 恒生指数 26009.4 等本地指数（R5-2-5 ✅）；无 A 股指数混入（P0-2 ✅） |
| US 综合研判 llm-report | ✅ 47s | 标普500 7489.72（+0.7%）/纳指本地指数 ✅ |
| AI 投顾问答 llm-advice | 🔴 质量不合格 | **R5-1-3 注入不完整**：快照仅"市态+情绪"（len 39），`get_index_realtime()` 空（东财限流）→ 输出全"无法确认指数/资金流/北向"模板，不可采信（R6-07'） |
| 个股分析 600519 | ✅ 167.8s | 基本面 PE_TTM 36.48 注入（P1-3 ✅，round5 为"数据源不可用"）；技术面完整 |
| ETF 分析 510300 | ✅ 178.5s（首测正文空→复测成功） | **deepseek 流式偶发断流**（首测 events=1 仅 disclaimer，completion_tokens=12286 未传出；复测 events=477 完整）——无重试机制（R6-09） |
| 港股分析 513010 | ✅ 43.1s（首测正文空→复测成功） | 同 R6-09 偶发 |
| 美股分析 513500 | ✅ 57.8s | 产品属性分析完整 |
| 板块分析（BK1318 光伏） | ✅ 84.7s | 成分股/快照/资讯注入正常 |
| 板块分析（半导体 BK1036） | 🔴 404 | **sector_analysis_stream 用 `get_sector_industry(200)` 截断**，半导体当日跌幅大排名>200 → 板块映射失败（R6-04）；round5 排名靠前未暴露 |
| 概念分析（AI） | 🔴 404 | 同上（concept 200 截断） |
| 指数分析 沪深300（sh000300） | ✅ 55.5s | 修复参数后正确分析沪深300 指数（首测"沪深300"中文名 → 159656 沪深300成长ETF 错位，R20 名称解析歧义） |
| 搜索补全 | ✅ 多数 | 510300 1 条（首测 6.24s 冷缓存/热 0.05s）、茅台 1 条（P1-7 ✅）、huangjin 19 条、恒生科技 12 条、半导体 10 条；**apple 名称 0 条**（US 个股名称搜索缺，代码 AAPL 可搜，R6-10） |

**专业投资者视角**：AI 输出整体逻辑严谨、诚实降级到位；**但 AI 投顾（无指数数据）与板块分析 404 直接削弱可用性**——投顾问答当前不可采信；US 个股名称搜索缺失影响体验。

---

## 六、热点/自选/持仓/资讯/因子/断裂/清单（步骤 4-10）

- **热点** ✅：热点板块 12 个（AI应用/人形机器人/算力/智能驾驶等，含催化 reason 与 lead_stocks）、热门个股 50 只（真实涨跌幅：利欧 +10.09% 等）、sectors/heat 20 项（change_pct 字段存在但 null——数据源）。
- **自选** ✅：列表 10 条（round5 数据持久化）、重复添加 409 防重、realtime 回显真实（588000 -5.32%/茅台 1358.98 +0.62%/SPY 747.03 +0.72%）。**数据链路不一致发现**：watchlist realtime 有涨跌（腾讯/新浪源），设计报告"今日涨跌"全缺（东财源限流）——同一标的同一时刻两处数据不一致（源选择差异）。
- **持仓技研** ✅：10 只持仓 indicators 完整（MA5/10/20/60、BOLL、RSI、KDJ、MACD），signal 与策略检查基本一致（513010 buy→increase、159992 sell→hold）；**信号口径不一致**（518880：策略检查 BUY vs /market/signal hold，R6-06）。
- **资讯** ✅：headlines 30 条（level 5×10/4×5/3×2/2×11/1×2 分布合理）、macro 15 条、global 8 条；news-impact 智能分析 32.7s（"机器人IPO传闻被否认"→"无直接影响"判断准确，impact_scope 结构化）；**news/stock content 为东财行情文本**（非新闻正文，R6-13）。
- **因子** 🟡：total 33 = valid 17 / warn 2 / no_data 11 / static 3（round5 valid 21/no_data 7 → **no_data 增多**）；IC 端点 19-26 条持续更新（updated_at 每 2 分钟刷新，**R5-1-5 ✅**）；**sentiment 4 因子仍全 no_data**（"IC 未累积，样本<3 天"，R5-06 未收敛）、**style 2 全 no_data**（fund_scale 缺）、etf_specific 5 no_data（nav/benchmark_close/shares_change 缺）。
- **数据断裂（步骤 9）** ✅：verify_e2e 22 模块 **266/278**（round5 264/278），无契约断裂；R4-11 四处弱断裂运行时验证通过；R5-09 news/stock 键集英文化无中文残留。
- **docs 清单（步骤 10）**：见 §八。

---

## 七、测试防护体系分析（步骤 13）

### 7.1 本轮 12 个 verify_e2e FAIL 归因

| FAIL | 根因类别 |
|---|---|
| ETF 数据缺失×4（记录 1/有成交额 0/有换手率 0/有价格 0）+ 候选池 0 + 池健康 None | 数据源熔断（东财限流 + shared_executor 饱和期）——真实反映 |
| shared_executor active=64/64 | 线程池饱和（mootdx 空转期 run_sync 任务积压） |
| llm-report 30s 超时 | deepseek 非流式响应 52.5s > 门禁 30s——**门禁阈值对当前 LLM 延迟过紧**（round5 62.7s 也超） |
| etf_specific no_data=3 / sentiment no_data=3 | 数据源字段缺失（nav/shares）+ IC 样本不足——R5-1-4 未收敛 |
| 行业轮动 0 条 | 数据源（东财板块轮动接口限流） |
| 20 持仓无 avg_cost | 数据录入缺失，非系统 bug |
| A01 预热门禁恒 PASS（**该 FAIL 的反面**） | 字段不匹配静默失效（见 7.2-②） |

### 7.2 六类防护盲区（为何未识别）

1. **Docker 构建/运行未纳入测试门禁**（R6-01/R6-02 的直接原因）：单测（1328 后端 + 342 前端）在**宿主机**跑——本地已装旧 httpx 依赖 + 有 `~/.mootdx/config.json` + tenacity 早已存在 → mootdx httpx 冲突、tenacity 漏装、config 缺失三类问题**宿主机全部测不到**。镜像构建从未被任何 CI/门禁验证。**盲区本质**：测试环境（宿主机）≠ 部署环境（容器），无容器化构建 + 全新环境冒烟测试。
2. **verify_e2e 门禁自身无元检查**（R6-03）：A01 读 `total_elapsed/duration_ms`，端点只返回 `elapsed_seconds` → 恒走"预热计时器未启用"分支恒 PASS。round5 P0-3 只恢复了"打印总结 + exit code"，**字段匹配这类门禁自身 bug 无人检查**（无"门禁断言必须真实断言"的元测试）。
3. **mock 池 vs 真实数据形态脱节**（延续 round5 §9.2，本轮 3 实例）：①sector limit=200 截断——单测 mock 的板块表含"半导体"，真实表按涨跌排序半导体当日排 >200；②设计报告 RSI 失真——rationale 单测断言"含 RSI 字样"不断言数值尺度；③信号双系统——策略检查与 /market/signal 各自单测，无交叉一致性测试。
4. **验收口径"数据源可用不判 FAIL"过宽**：R5-1-4 验收"数据源可用后 sentiment ≥2 valid"，未达成时标注"待源恢复"——sentiment no_data 从 round5 挂到 round6 无门禁拦截（无"长时间 no_data 自动 FAIL"）。
5. **LLM 类功能无端到端断言**：R5-1-3 单测 mock 了 market_snapshot → 未发现真实链路 `get_index_realtime()` 空导致注入不完整；流式偶发断流（R6-09）无重试测试。
6. **LHCI 未接入 CI**（round5 R5-0-3 遗留）：CLS 0.189 只能手动 Lighthouse 发现，无自动化拦截。

### 7.3 与 round5 防护体系对照

round5 已补：设计质量门禁（P1-1/P1-2/M7——本轮全 PASS ✅）、因子健康门禁、性能预算 A01（**字段 bug 失效，见 7.2-②**）。新增盲区集中在：**部署环境差异（Docker）**、**门禁自身正确性**、**真实数据形态** 三类。

---

## 八、docs 问题清单验证（步骤 10）

### 8.1 round5 修复项验证（R5-01~R5-15 + 批次 1-4）

| 项 | 状态 | 证据 |
|---|---|---|
| R5-0-1 A500 入核心 | ✅ | 三方案核心层含 560600（design 158） |
| R5-0-2 核心层重叠 | ✅ | 两两重叠 0（剔除公共底仓） |
| R5-0-3 首页 CLS | 🔴 **未达标** | CLS 0.189（round5 0.388 改善，但 >0.1）；summary-grid min-height 340px 数据注入后超高 |
| R5-0-4 红利上限 | ✅ | 防御 15%/平衡 14.4%/进攻 15% |
| R5-1-1 LLM 429 治理 | 🟡 部分 | opencode_zen 500 频繁 → deepseek 降级链生效；预热错峰生效（"warmup in progress — skipping LLM"）；互斥未验证 |
| R5-1-2 兜底 holdings_analysis | ✅ | rule 路径非空（10 条骨架） |
| R5-1-3 llm-advice 注入 | 🔴 **不完整** | 无条件注入生效但指数数据空（get_index_realtime 0 条）→ 输出全降级模板 |
| R5-1-4 sentiment 因子 | 🔴 **未收敛** | 4 因子仍全 no_data（IC 样本<3 天 + 数据源） |
| R5-1-5 IC 周期计算 | ✅ | 26 条持续更新（updated_at 每 2 分钟），verify_e2e PASS |
| R5-1-6 策略检查 LLM 诊断 | ✅ | 最后错误透传 + 500 快速失败（报告阶段 10s） |
| R5-2-1 组合计算/watchlist 提速 | 🟡 部分 | watchlist 1466ms（round5 4525ms 改善 3 倍，仍>800ms 目标） |
| R5-2-2/R5-09 news/stock 键归一化 | ✅ | 英文键集无中文残留 |
| R5-2-3 预热优化 | 🔴 | 12.4-12.9s（round5 3.36s 劣化；R6-08） |
| R5-2-4 mootdx | 🔴 **容器未达标** | 宿主机 ✅（config 缓存）但容器空转（config 缺失）——验收"降级链实际可用第一环"容器环境 FAIL（R6-02） |
| R5-2-5 HK/US 指数链路 | ✅ | HK/US 报告含本地指数（R5-2-5 修复生效） |
| R5-2-6 东财抗限流 | 🟡 部分 | push2delay 双源路由已实施（verify_e2e sources: push2delay available）；但**指数链路未走双源** → get_index_realtime 仍空 |
| R5-2-7 商品签名 | 🟢 未复测 | （非本轮重点） |
| R5-2-8 PE/PB 备用源 | 🟡 部分 | 600519 PE 36.48 可用（akshare 恢复）；指数 PE/PB 仍"数据源不可用" |
| R5-2-9 熔断接线 | ✅ | verify_e2e sources/health 15 源含熔断状态；mootdx/akshare/dongfang 冷却可见 |
| R4-11 前端弱断裂 | ✅ | change_pct/kdj-rsi/分类/tooltip 运行时验证 |
| R4-25/26/27/28 | ✅ | 代码核查 + 运行时 |
| P1-7 个股搜索本地化 | ✅ | 茅台 → sh600519 1 条 |
| P3-3 watchlist 提速 | 🟡 | 1466ms（改善但未达 800ms） |

### 8.2 user-feedback-fixes-review 验证

| 项 | 状态 | 证据 |
|---|---|---|
| #3 AnalysisView 竞态 | ✅ | fetchSeq 守卫 + watch 放宽（代码核查） |
| #4/#9/#12/#13/#14/#15 接线 | ✅ | 前端代码核查 + 测试存在 |
| #5 watchlist 并行化 | ✅ | 3.9s 热缓存（round5 4525ms → 1466ms） |
| #6 板块快照注入 | ✅ | BK1318 报告含成交额/主力净流入（R5 修复生效） |
| #7 概念双表 | 🟡 | 归一化逻辑在，但 limit 截断致 404（R6-04） |
| #8 指数错位 | 🟡 | 000001 修复；"沪深300"中文名仍歧义（→159656） |
| #10 搜索提速 | ✅ | 热缓存 0.05s |
| #17 场外技研 | 🟢 未复测 | 本轮 on_exchange 场景 |

---

## 九、回收说明（步骤 15）

- docker-compose.yml：移除 **prod backend 段**的 `PROFILE_WARMUP=1` 与 `./backend/logs:/app/logs`（诊断临时配置）。**注意勿动 `backend-dev` 段的 `PROFILE_WARMUP=1`**——那是 round4 保留项（dev 预热计时），非本轮诊断配置。
- 诊断报告（warmup_timing.json / warmup_pyinstrument.* / warmup_cprofile.txt / perf_diag_results.json）保留在 `backend/logs/` 供回溯；`diag/` 目录为临时诊断脚本，回收时可删除。**建议将 verify_e2e 全量输出留存一份到 `backend/logs/e2e_round6.log`（本轮 266/278、12 FAIL 明细）**——当前无留存文件，跨轮次对比困难。
- 容器：`docker-compose --profile prod down`（或 stop）；**mootdx config 修复**（复制到容器 /root/.mootdx）为临时验证手段，正式修复见 R6-02 方案（代码级，不依赖手动复制）。

---

## 十、问题清单（R6-01 ~ R6-16）

- **R6-01 🔴 Docker 构建回归**：mootdx 0.11.7 依赖 `httpx>=0.25,<0.26` 与项目 `httpx>=0.27` 冲突 → `docker build` ResolutionImpossible（round5 R5-2-4 实施引入）。**已修复**（requirements.txt 移 mootdx + Dockerfile --no-deps，见 §六）。
- **R6-02 🔴 mootdx 容器内空转**：`_mootdx()` 用 `Quotes.factory(market='std', timeout=6)` 无 server 参数 → 依赖 `~/.mootdx/config.json` BESTIP 缓存，全新环境无该文件 → ValueError 被吞 → 降级链第一环空转。宿主机有 config（180.153.18.172:80）→ 单测/本地验证全绿。影响：report A 309s / 策略检查持仓加载 55s / 预热 market_cache 6.2s / 线程池 64/64。**已验证**：容器内显式 `server=('180.153.18.172', 80)` 0.35s 返回真实行情；复制 config 后默认路径可用。
- **R6-03 🔴 A01 预热门禁字段不匹配**：verify_e2e.py:95 读 `total_elapsed/duration_ms`，routers/system.py 只返回 `elapsed_seconds` → 门禁恒 PASS。
- **R6-04 🟡 sector/concept 分析 limit=200 截断**：`sector_analysis_stream`（analysis.py:687/689）用 `get_sector_industry/concept(200)`，当日跌幅大板块（半导体 BK1036）排名>200 → 404"板块映射失败"。round5 排名靠前未暴露。
- **R6-05 🟡 设计报告技术指标数值失真**：表格"RSI 1.5/MACD 0.4212"实为归一化因子分，与真实 RSI 39.8/MACD -0.007 尺度不符——rationale 生成将因子分标注为 RSI/MACD 名称，误导解读。
- **R6-06 🟡 信号口径不一致**：策略检查 tech_signal（factor_registry `technical.signal.overall`）vs `/market/signal`（market_service 规则信号）——518880 前者 BUY→increase、后者 hold(0.0)；两套独立信号系统无一致性保证。
- **R6-07 🟡 因子分跨方案不稳定**：563020 防御 core +1.11 / 平衡 -1.20 / 进攻 -1.51（差异 2.6）；疑为方案内 z-score 归一化。
- **R6-07' 🟡 AI 投顾指数注入空**：`get_index_realtime()` 空（东财限流）→ R5-1-3 快照仅市态/情绪 → advice 输出全"无法确认"模板。
- **R6-08 🟡 预热劣化**：12.4-12.9s（round5 3.36s）：etf_cache ~6.3-6.5s（镜像内 file cache 过期 + 不随 volume 持久化）+ market_cache ~6.0-6.2s（R6-02 关联）。
- **R6-09 🟡 LLM 流式偶发断流**：510300/513010 首测 events=1 正文空（deepseek 生成 12286 tokens 但未推流）；无重试机制。
- **R6-10 🟡 US 个股名称搜索空**：apple 0 条（代码 AAPL 可搜）；akshare spot 源不可用（round5 同）。
- **R6-11 🟡 shared_executor 64/64 饱和**：verify_e2e 运行时检查抓到（R6-02 关联：mootdx 空转期 run_sync 任务积压）。
- **R6-12 🟢 advice 契约偏差**：api-contracts/analysis/llm-report.md 写 query 为查询参数，实现（LLMAdviceRequest）在 body。
- **R6-13 🟢 news/stock content 内容质量**：content 为东财行情快照文本（"48.84 279.00..."），非新闻正文。
- **R6-14 🟢 perf_diag.py 方法错误**：calculate/daily-pnl/news-impact 用 GET 测 POST 端点 → 3 个假 FAIL。
- **R6-15 🟢 策略检查 summary 文案残留**："LLM 分析超时（60s 未返回）"与实际 500 快速失败不符（模板文案未随 R5-1-6 更新）。
- **R6-16 🟢 指数名称解析歧义**："沪深300"中文名 → 159656 沪深300成长ETF（R20 名称解析在指数/ETF 间歧义）。

---

## 十一、优化修复方案（实施标准设计，本轮不实施）

> 按 AGENTS.md 契约先行 + TDD 流程；验收可自动化断言优先；"数据源可用"判定按 round5 约定（5s 内非空）。

### 🅿️0 阻断性

**R6-F1：mootdx 容器可用性修复（R6-02，性能总根因）**
- 实施：`_mootdx()`（china_market.py:98）无 server 参数时：①优先读 `~/.mootdx/config.json`（现状）；②缺失时 fallback 探测——首调用 `mootdx.server.server(index='HQ', sync=True, limit=1)` 获取最优服务器并写 config，或直接 fallback 已知可用服务器列表 `[('180.153.18.172', 80)]`（容器实测 0.35s 可用）显式传入 `Quotes.factory(server=...)`；③探测放后台避免阻塞首请求。
- 验收：全新环境（无 config）容器内 `_mootdx()` 返回真实行情（非空）；report A ≤90s、策略检查加载持仓 ≤15s、预热 <2.5s（R5-2-3 口径）。
- TDD：`test_mootdx_*` 扩展——mock config 缺失 → 断言 fallback server 被使用（mock `mootdx.server.server`）；mock 探测失败 → 断言不阻塞 + 降级 Sina/Tencent。

**R6-F2：A01 门禁字段修复（R6-03）**
- 实施：二选一——①verify_e2e.py:95 改为读 `wd.get("elapsed_seconds")`（简单）；②端点补 `total_elapsed` 字段（routers/system.py 增加预热总时长，与 warmup_timing.json 对齐）。建议 ②（端点语义更完整）+ ①兜底。
- 验收：PROFILE_WARMUP=1 时 A01 真实断言（预热 >20s FAIL / >10s WARN 生效）。
- TDD：`test_warmup_status.py` 扩展断言响应含 total_elapsed（或 verify_e2e 读 elapsed_seconds 的集成测试）。

**R6-F3：sector/concept limit 截断修复（R6-04）**
- 实施：`sector_analysis_stream`（analysis.py:687/689）`get_sector_industry/concept(200)` → 500（与 /market/sectors 端点 limit=500 对齐）；或按名称二次查找。
- 验收：半导体（BK1036）概念（AI）板块分析不再 404（数据源可用时）。
- TDD：mock industry 列表 500 条含 BK1036 → 断言 sector_data 命中（先写 200 截断失败用例）。

### 🅿️1 高优先级

**R6-F4：设计报告技术指标源对齐（R6-05）**
- 实施：rationale 生成（engine/rationale.py）引用的 RSI/MACD 改取 `compute_all_indicators` 真实值（与 /market/indicators 同源），不再用归一化因子分标注指标名；因子分单列。
- 验收：design_text 中 RSI 值 ∈ [0,100]、MACD 与 /market/indicators 一致（抽样 3 只断言）。
- TDD：`test_rationale.py` 扩展——断言 rationale 含真实 RSI（mock indicators 返回 rsi=42.5 → 断言文本含"RSI 42.5"而非因子分）。

**R6-F5：信号口径统一（R6-06）**
- 实施：策略检查 tech_signal 改调 `/market/signal` 同源（market_service），或 factor_registry 的 technical.signal.overall 作为唯一技术信号源并让 /market/signal 复用；至少**交叉一致性断言**。
- 验收：任一标的两端 tech_signal 一致。
- TDD：参数化断言——同标的两实现输出一致（mock 因子与 K 线同数据）。

**R6-F6：advice 指数注入兜底（R6-07'）**
- 实施：`_build_advice_market_snapshot` 指数段在 `get_index_realtime()` 空时从 `get_global_indices()` 的 A 股段兜底（对齐 F1-3 已有模式，market_data_hub 内已有 A 股指数数据）。
- 验收：advice 输出含 ≥3 条指数点位（数据源可用时）；R5-1-3 验收"样本集含指数"达标。
- TDD：mock get_index_realtime 空 + get_global_indices 有 A 股段 → 断言 snapshot 含指数。

**R6-F7：etf_cache 文件缓存持久化（R6-08 一部分）**
- 实施：etf_scanner `_cache_file`（etf_scanner.py:332 `app/data/etf_list_cache.json`）改到挂载卷路径并**区分运行环境**——容器内 `/app/data/etf_list_cache.json`（与 portfolio.db 同卷），宿主机开发环境回落 `backend/data/etf_list_cache.json`（用环境变量 `DATA_DIR` 或 `os.environ.get('DOCKER')` 判定）；或预热时若缓存过期仅刷新一次并落盘。
- 验收：容器重建后预热 etf_cache <500ms（缓存命中）。
- TDD：mock 文件缺失/过期 → 断言写新缓存到新路径。

### 🅿️2 中优先级

**R6-F8：LLM 流式重试（R6-09）**：symbol/sector 流式请求在 0 事件/仅 disclaimer 时自动重试 1 次（对齐 design task 的重试语义）。TDD：mock 流空 → 断言重试。
**R6-F9：US 个股名称搜索备用源（R6-10）**：akshare spot 失败时用本地 instruments 表（含 US 段）或 yfinance 补搜。验收：apple → 非空（数据源可用时）。
**R6-F10：线程池扩容/限流（R6-11）**：shared_executor 上限评估（64→128）或 mootdx 修复后验证不再饱和（R6-F1 联动）。
**R6-F11：契约修正（R6-12）**：api-contracts/analysis/llm-report.md advice query 改 body 字段。
**R6-F12：perf_diag.py 方法修正（R6-14）**：calculate/daily-pnl/news-impact 改 POST + 请求体。
**R6-F13：summary 文案更新（R6-15）**：策略检查兜底文案区分"限流/超时/快速失败"，与 get_last_llm_error 一致。
**R6-F14：指数名称解析消歧（R6-16）**：R20 名称解析优先指数代码表（指数名 → 指数代码），ETF 名命中优先 asset_type=index 场景。
**R6-F15：设计报告补建仓节奏标注（R6-05 关联）**：方案表格加"建仓建议"列（分批/等企稳），与文字建议对齐。

### 🅿️3 测试防护弥补

**R6-F16：Docker 构建门禁**：CI（或 pre-commit 扩展）加入 `docker build backend` 冒烟——**不能用 `pip install --dry-run -r requirements.txt`**（mootdx 已移出 requirements 且 Dockerfile `--no-deps` 绕过 resolver，dry-run 永远无法捕获 R6-01 类冲突）；须实际构建镜像（或复刻 Dockerfile 的 `--no-deps` 完整安装序列做依赖解析检查）。
**R6-F17：全新环境 mootdx 冒烟（含本地）**：①容器：无 `~/.mootdx` 环境启动冒烟断言 mootdx 链不抛异常（或 source_health mootdx available）；②**本地 fresh venv**：requirements.txt 移除 mootdx 后，README/开发文档补安装指引（`pip install --no-deps "mootdx>=0.11.7" "prettytable>=3.0" "tdxpy>=0.2.7" "tenacity>=8.0"`——**须与 Dockerfile 一致带 `--no-deps`**，否则已装 httpx 0.28 的 venv 会因 mootdx 的 `httpx<0.26` 约束安装失败；或提示直接用 Docker 开发），否则 fresh venv 无 mootdx → `_mootdx()` ImportError 被吞 → 本地第一环静默空转（与 R6-02 同源）。
**R6-F18：verify_e2e 元检查**：门禁断言必须"真值断言"（如 A01 在 PROFILE_WARMUP=1 时必须读到非 0 值，否则视为门禁自身 FAIL）。
**R6-F19：真实数据形态回归**：sector 排名截断、RSI 数值尺度、信号双系统一致性——各补 1 个"真实形态"回归用例（§7.2-③）。
**R6-F20：LLM 端到端断言**：advice/symbol 报告在数据源可用时断言关键数据段注入（指数/PE 非空），mock 网络但真实管道。
**R6-F21：LHCI 接入 CI**：`npx lhci autorun` 首页 CLS ≤0.1 门禁（R5-0-3 遗留收尾）。

---

## 十二、修订记录

- v1.0 (2026-08-03)：round6 全量诊断完成（15 项动作），形成 R6-01~16 问题清单与 P0-P2 修复方案（未实施，除 R6-01 构建回归为构建必要前置已修复）。
- v1.1 (2026-08-03)：多轮 review 修订——①warmup 数字统一改为与留存 `backend/logs/warmup_timing.json` 一致（标注两次采样）；②R6-F16 dry-run 门禁改 docker build 冒烟（mootdx 已移出 requirements，dry-run 失效）；③R6-F17 补本地 fresh venv 安装指引（requirements 移除 mootdx 后的本地缺口）；④R6-F7 补容器/宿主机环境区分；⑤§九 回收说明限定 prod backend 段（backend-dev 的 PROFILE_WARMUP 为 round4 保留项）；⑥补 verify_e2e 结果留存建议。
- v1.2 (2026-08-03)：二轮 review 修订——⑦R6-F17 命令补 `--no-deps`（与 Dockerfile 一致，避免 httpx 冲突致安装失败）；⑧测试数口径统一为"后端 1328 + 前端 342"并注明宿主机局限；⑨factor_availability 23/33 与 /factors/active status 统计口径差异注记。

---

## 十三、用户反馈补充诊断（round6-ux 第二轮，2026-08-03 晚）

> 范围：用户再次反馈 3 项问题（因子数据、IC 图渲染、AI 工具页因子模型显示）。仅分析与定位，**不做实施**。
> 定位环境：本地后端（uvicorn:8000）实时 API + 前端源码；留存证据见 `diag/out/market/factors_data.json`、`/api/v1/factors/active`、`/api/v1/factors/ic` 实时响应。

### 13.1 反馈 1：因子 7 个无数据、政策因子 0 有效——数据管道是否还有问题？

**实时状态（本地后端，2026-08-03 晚）**：`total 33 = valid 23 / warn 0 / no_data 7 / static 3`（留存 `diag/out/market/factors_active_local.json`）。**注**：round6 容器快照（`diag/out/market/factors_data.json`，09:24 UTC）为 `valid 17 / warn 2 / no_data 11 / static 3`（sentiment 4 + etf_specific 5 + style 2 no_data）——两口径差异源于**数据源可用性**（容器缺 nav/benchmark_close/shares_change_20d/fund_scale 字段，本地可拿），非代码差异；下文以本地实时口径为准。

**结论：政策因子 0 有效 = 设计使然（非管道故障）；7 个 no_data 均为「IC 累计样本 <3 个交易日」（R5-1-5 于 2026-08-03 实施，累计表不足 3 天）——本地环境全部是时间未到，非管道故障。**（容器环境 etf 3 项另叠加 nav/benchmark_close/shares_change 字段缺失，R5-1-4 未收敛，见 §八）

| 因子 | 状态 | 根因定位 | 性质 |
|---|---|---|---|
| `china.policy.*` ×3（五年规划/战略新兴/双循环） | static，valid 0 | `factor_registry.py:451-492` `_POLICY_ALIGNMENT` 静态映射（行业→0/1 哑变量），reason 明确"静态政策标识因子，不计算 IC"——横截面哑变量 IC 无统计意义，Z03 静态设计（round5-ux #1 已记录） | **设计，非故障** |
| `sentiment.*` ×4（panic_greed_diff/stock_divergence/news_heat/news_direction） | no_data（"IC 未累计，样本 <3"） | R5-1-5（IC 启动恢复 + 120s 周期 compute）于 2026-08-03 实施，IC 累计表不足 3 个交易日；因子值注入链路已存在（`market_data_hub.py:464-487` news_items/sentiment_index 注入，panic_greed_diff 用新闻方向 `(news_dir-0.5)*2` 代理 sentiment_index） | **时间未到，非故障** |
| `etf.premium_discount` / `etf.tracking_error` / `etf.shares_change` | no_data（"样本 <3"，本地实时口径） | 本地：因子值可算（NAV/份额数据可拿），仅 IC 累计 <3 天；容器快照：`nav/benchmark_close/shares_change_20d` 字段缺失 → 因子值 None（R5-1-4 未收敛，§八 143 行） | **本地=时间未到；容器=字段缺失（已记录）** |
| `style.*` ×2 | 本地 valid 2（容器快照 no_data） | 依赖 fund_scale——本地数据源可拿，容器缺字段 | **本地正常** |

**展示误导（本轮新发现）**：`/factors/active` summary 将 static 单列（static_count 3），但前端 `FactorModelView.vue` stats-row（25-52 行）只显示"已接入/有效/低于阈值/无数据/平均|IC|"，**static 未展示** → 用户看到"33 已接入 = 23 有效 + 7 无数据"，另 3 个去向不明；且 `china_specific` 分类行显示"0 有效"（static 因子不算 valid），用户误读为"政策因子全坏了"。

**修复方向（不实施）**：
- F1-A（展示）：`FactorModelView.vue` stats-row 增加"静态标识 N"项（读 `summary.static`）；分类行对 static 因子标注"静态"徽标 + tooltip 解释"静态标识因子不参与 IC 统计（如政策哑变量）"；IC 判定处（`:119 abs(ic_value) >= threshold`）将 static 因子（ic_value null）与"无效/低于阈值"语义区分开（当前 static 因子落入"低于阈值"侧，被算进 warn/无效口径）。
- F1-B（数据）：容器环境 etf_specific 3 项随 R5-1-4（未收敛，fundamental 字段缺失）一并解决；本地 sentiment 4 + etf 3 无需处理，待 IC 累计满 3 个交易日后自动转 valid——可在 IC 端点 reason 注明"样本累计中"。

### 13.2 反馈 2：因子 IC 表现图文字与图案重叠

**定位**：`FactorModelView.vue:148-152` echarts BarChart（`ic-chart-container` 300px 高、容器尺寸正常，非容器问题）。

**根因**：series `label: { position: 'right' }`（307-314 行）+ `grid.right: '10%'`（282 行）只为**正值柱**预留了右侧标签空间；**负值柱从 0 向左延伸**，`position:'right'` 仍把数值标签放在柱右端（贴近 0 轴处）→ 标签压在柱身上（"文字与图案重叠"）。当前图表 top15 含大量负 IC 因子（ATR -0.44、sma_20 -0.39、vwap -0.35 等），重叠必然出现。

**修复方向（不实施）**：
- F2：`label.position` 改函数：`(p) => p.value >= 0 ? 'right' : 'left'`（echarts 支持函数返回位置）；或负值柱 label 用 `position: 'left'` + 负值方向 padding。
- 附加：`grid.right` 保持 10%（正值），负值 label 溢出由 `containLabel: true` 承接（282 行已有，配合 left 位置即可）；`labelLayout: { moveOverlap: 'shiftY' }` 防相邻柱标签互叠。

### 13.3 反馈 3：具体 AI 工具打开时，因子模型仍显示在下方（"之前说过的，好像没改掉"）

**定位**：`DashboardAiTools.vue:110` `<FactorModelView />` **无条件渲染**——无论 `activeCoreFeature` 为 null（工具列表/wizard）还是 strategy/design loading/result，因子模型概览始终显示在页面底部。

**历史核实**：`docs/user-feedback-fixes-review.md` 16 项清单中**无此项记录**（round5-ux 索引里没有"因子模型隐藏"反馈）→ 属口头反馈**未入库、未实施**——这正是"用户反馈未固化为测试用例/文档"流程缺陷的实例（§七 盲区）。

**修复方向（不实施）**：
- F3：`DashboardAiTools.vue:110` 改 `<FactorModelView v-if="!activeCoreFeature" />`（仅工具列表/初始态显示；具体工具打开后隐藏）。
- 补组件测试：`activeCoreFeature` 置为 'strategy'/'design' 时 FactorModelView 卸载、置 null 时挂载（真实输入流驱动，符合 round5-ux §5.1 模式）。

### 13.4 测试防护关联

- 反馈 1/2 暴露：**static 因子口径无测试断言**（summary.static_count 与前端展示一致性无人校验）；**图表 label 位置无快照/视觉断言**（echarts 配置正确性靠人眼）——与 §七 盲区③（mock 数据形态脱节）、盲区⑤（视觉类人工走查）同源。
- 反馈 3 暴露：**口头反馈未入库 → 无测试用例 → 无实施**——流程缺陷（round5-ux §5.4 已提出"用户反馈即测试用例"，但口头反馈无记录通道）。

### 13.5 修订记录 v1.3

- v1.3 (2026-08-03)：追加「十三、用户反馈补充诊断」——①政策因子 0 有效=Z03 静态设计（非故障），但前端 static 口径展示误导（F1-A 展示修复方向）；②7 个 no_data 分解：sentiment 4 + etf_specific 3（本地口径均"IC 样本 <3 天"=时间未到；容器口径 etf 3 叠加字段缺失 R5-1-4 未收敛）；③IC 图重叠根因=负值柱 label position:'right' 压柱身（F2 修复方向）；④因子模型未隐藏=DashboardAiTools.vue:110 无条件渲染 + 该反馈从未入库（F3 修复方向）。均未实施。

---

## 十四、用户反馈补充诊断 2：组合设计方案质量（2026-08-03 晚）

> 范围：用户对组合设计方案的 4 项设计合理性质疑 + 报告数据问题。仅分析与定位，**不做实施**。
> 证据：设计 368（task 158）三方案（截图 + `diag/out/design_text_368.md`）；代码定位 `backend/app/engine/allocation_engine.py`、`budgets.py`、`risk_controls.py`、`services/strategy_design.py`。
> 三方案结构（以留存 `diag/out/design_text_368.md` 总览取整值为准；OCR 截图精确权重未留存、且 OCR 数字不可靠，明细仅作参考）：防御 = 核心 51%（4 只：沪深300/A500/红利低波 15/上证50 21）+ 卫星 12%（2 只：科创新能源 7/科创创新药 5）+ 防御 15%（黄金/30年国债）+ 现金 21%；平衡 = 核心 46%（5 只）+ 卫星 29%（3 只：科创AI 8/科创芯片 7/红利低波 14）+ 防御 10% + 现金 15%；进攻 = 核心 42%（4 只：沪深300/A500/科创50 16/创业板 15）+ 卫星 31%（3 只：科创创新药 8/科创新能源 8/红利低波 15）+ 防御 11% + 现金 15%（留存总览 16%）。

### 14.1 Q1：卫星层仍是科创为主——为什么？

**现象**：三方案卫星层除红利低波外全部是科创主题（科创新能源/科创创新药/科创人工智能/科创芯片设计），与用户此前反馈一致（"卫星还是只有科创"）。

**根因（三层叠加）**：
1. **卫星候选池构成偏科技**：`scanner.full_pipeline`（market_data_hub.py:365）分类的 satellite 池中科创系主题 ETF 占比高；静态兜底池（strategy_design.py:21-40）卫星仅 159915/588000（宽基），又被 M5 `_is_wide_basis` 排除出卫星路径（allocation_engine.py:656）→ 卫星池只剩主题 ETF，科创主题在其中占多数。
2. **非科技卫星候选评分不足**：进攻/平衡 composite 中 momentum 权重 0.45/0.3（allocation_engine.py:265），科创系动量因子显著更高（如科创创新药 momentum +1.20）→ 医药/AI/新能源等非科技卫星在排序中被碾压；防御型 C2 虽对科创 -1.5 惩罚，但 +1.2 动量仍净胜。
3. **F0-5 步骤 C 科技配额裁剪后无可回补对象 → 权重丢失**（allocation_engine.py:353-385）：裁剪**必然执行**（科技合计超 `budget×40%`（防御）/50%（平衡/进攻）即按 composite 降序裁到 cap），但 `:374 non_tech_kept` 为空时**被裁权重直接丢弃、不回补**（`kept` 不含被裁项）→ 卫星权重缩水 → 现金膨胀。**注：防御方案输出科创 12% > tech_cap（layer_budget 0.20×40%=8%）的现象与当前代码裁剪逻辑不符，疑生成时镜像/分支版本差异，需以生成时 allocation 日志复核（见 F4 验收项）**。

### 14.2 Q2：核心层/卫星层数量配比是否合理？

**现象**：核心 4-5 只（符合 `layer_count.core=4-5` ✅）；卫星 2-3 只（`layer_count.satellite=6-8` 上限，**远未达标** ✗）；防御现金被动放大至 21%。

**根因**：①卫星候选池窄（见 14.1-1）；②B3b 概念组去重（科创系归一化每组仅留 1 只）；③F0-5 步骤 D 补足逻辑（allocation_engine.py:673-718）从 `core_candidates` 取**非宽基**补足，但核心候选全部是宽基 → 补足为空（`backup_cands=[]`）；④配额裁剪后权重不回补 → 卫星预算未打满 → 现金膨胀。**层数量失衡使卫星层失去"多赛道分散"意义**（F0-5 注释自述目标），组合弹性不足。

### 14.3 Q3：红利低波出现在卫星层是否合理？

**现象**：平衡方案红利低波 14.4%、进攻方案 15% 均落在**卫星层**。

**结论：不合理——层级错配**。红利低波是低波防御资产（R5-0-4 明确列为"防守型核心"），放卫星（进攻弹性仓位）违背资产属性。

**根因（四个叠加）**：
1. `_is_wide_basis` 关键词列表（allocation_engine.py:129：沪深300/上证50/科创50/创业板…）**不含"红利"** → 红利低波不被识别为防御/底仓属性，留在卫星池；
2. `_SAFE_THEMES` 含"红利"（allocation_engine.py:279）→ 防御型 c2_bonus +0.8 反而**推高**其评分（与进攻型 -0.3 冲突，风格信号互相打架）；
3. R5-0-4 红利上限 15% **只校验权重、不校验层归属**（risk_controls.py:246-255 仅按 weight 校验）→ 14%/15% 在卫星层不触发门禁；
4. 默认池 `_DEFAULT_CANDIDATES` 中 515080 中证红利 layer=satellite（allocation_engine.py:161）——**设计上红利类被允许进卫星**。

### 14.4 Q4：进攻核心层同时重仓科创50 + 创业板是否合理？

**现象**：进攻方案核心层科创50 16.3% + 创业板 14.7% = 31%（高 beta 成长宽基），叠加卫星层科创主题 16.4% → **成长/科技风格合计约 47%**。

**结论：不合理——风格集中度风险**。科创50 与创业板指同受成长/科技风格驱动，相关性高，双重暴露 + 卫星科创主题形成三重叠加。

**根因（四个叠加）**：
1. 核心层选择仅按 composite 排序（allocation_engine.py:268-273），进攻型 momentum 权重 0.45 → 科创50/创业板动量强、得分高，双双入选；
2. B3b 概念去重中"科创50"→segment"科创"、"创业板"→"创业板"是**不同 segment**（allocation_engine.py:70-72/316-331），互不拦截；
3. 行业集中度 HHI 按 `industry` 字段分组（risk_controls.py:272-277），两者 industry 均为"宽基" → 合计 31% < 40% 阈值不触发；
4. **无风格/相关性约束**（成长 vs 价值、宽基间 beta 相关性矩阵缺失）。

### 14.5 Q5：报告表格"今日涨跌"全为"数据源不可用"（+ RSI 失真连带）

- **今日涨跌**：round6 §五 已记录（R5-07）：`get_index_realtime()` 空（东财 push2 限流 RemoteDisconnected）→ 设计报告行情快照"今日涨跌"缺。本轮截图（设计 368 全文报告表格）证实仍在——**"多因子评分"列有值、"今日涨跌"列全"数据源不可用"**（行情注入失败而因子评分正常）。
- **RSI 失真（连带）**：报告内 RSI 值 0.2~2.4（上证50 RSI 0.2、红利低波 2.1、30年国债 2.4），真实 RSI 应在 0-100 区间——round6 §八 已记录（159338 RSI 1.5 vs 真实 39.8），本轮多标的再现。

### 14.6 修复方向（不实施）

| 编号 | 对应 | 方向 |
|---|---|---|
| F4 | 14.1/14.2 | 卫星池扩充：scanner 卫星分类补非科技主题配额（医药/消费/金融/红利/新能源）；科技配额裁剪改为"被裁权重回补非科技候选，无候选时转现金或空出预算"；**验收增加：生成日志断言科创合计 ≤ budget×40%/50%（复核 task 158 输出 12% > 8% 的版本差异）**，确保卫星层 ≥4 只 |
| F5 | 14.3 | 层归属约束：`_is_dividend_etf`（512890/515080/563020）**禁止落卫星层**（layer=satellite 且红利 → 移 core 或剔除）；默认池 515080 layer 改 core；R5-0-4 校验扩展为"权重+层归属"双条件 |
| F6 | 14.4 | 核心层风格/相关性约束：同风格高 beta 成长宽基（科创50/创业板/科创100 等）合计 ≤ 核心预算 40%（或引入宽基相关性矩阵）；行业集中度分组补充"宽基风格"维度（当前 industry 全"宽基"无法区分） |
| F7 | 14.2 | verify_e2e design-quality 门禁增加"卫星层 ≥4 只且 ≥2 个非科技主题"断言（当前无数量下限断言，F0-5 步骤 D 仅代码注释层面） |
| F8 | 14.5 | 随 R5-2-6 / R6-F6（指数实时多源降级）与 round6 §八 RSI 失真记录项一并实施 |

### 14.7 修订记录 v1.4

- v1.4 (2026-08-03)：追加「十四、用户反馈补充诊断 2：组合设计方案质量」——卫星层科创集中（卫星池窄+非科技候选评分不足+科技配额裁剪后无可回补→权重丢失）、层数量失衡（卫星 2-3 vs 6-8，补足逻辑空转致现金 21%）、红利低波层级错配（_is_wide_basis 不识别红利 + 15% 只校验权重不校验层）、进攻核心成长双重暴露（无风格/相关性约束 + 行业集中度按 industry 分组不拦截）、今日涨跌数据源不可用（R5-07 截图佐证）+ RSI 失真（round6 §八 佐证）；修复方向 F4-F8（均未实施）。

---

## 十五、用户反馈补充诊断 3：策略检查（2026-08-03 晚）

> 范围：策略检查 4 项问题（LLM 超时、操作建议与技术信号矛盾、因子评分栏抽象、news_heat 全 100）。仅分析与定位，**不做实施**。
> 证据：截图 3 张（策略检查结果页 + 持仓明细分析 ×2）+ 留存 `diag/out/check_task_159.json`（suggestions/holdings_analysis）。

### 15.1 Q1：策略检查 LLM 仍然超时（"60s 未返回"）

**现象**：截图显示"LLM 分析超时（60s 未返回，已用规则引擎兜底）（市态: 震荡; 因子数据 10/10 正常）"——注意这是**真实 60s 满超时**，不是 round6 §八 R6-15 记录的"文案残留"（那次的 500 快速失败 + 文案写 60s）。

**根因**：`portfolio_service.py:570-577`——LLM 调用 `asyncio.wait_for(llm_complete(prompt), timeout=60)`（U2 R3：超时预算 20s→60s 对齐设计任务）。**R5-1-6 的快速失败只覆盖"快速 500/429"**（服务端立即报错 → 快速兜底）；**DeepSeek 慢响应（60s 无返回）只能等满 60s**。round6 诊断时 task 159 是 500 快速失败（~10s），本次 DeepSeek 慢 → 60s 满超时——供应商行为差异，快速失败机制对"慢无响应"无效。

**修复方向（不实施）**：F9——①LLM 调用超时 60s→30s（30s 内无响应即兜底，用户等待减半）；②超时后按 `get_last_llm_error` 区分"限流(429)/慢(超时)/服务端(5xx)"写文案（R6-15 同源）；③前端任务进度页显示"LLM 分析中（最多 30s）"倒计时提示，避免用户以为卡死。

### 15.2 Q2：操作建议与持仓明细技术信号矛盾

**现象**（159992 创新药 / 513120 港股创新药 为例）：持仓明细 tech_signal=**SELL**，操作建议 action=**hold** 且 reason 自述"信号 sell，维持现状"——技术面看跌、建议却持有，文案自己承认矛盾。

**根因**（portfolio_service.py:926-931 `_rule_based_suggestion` 决策表）：SELL→decrease 仅在 **avg_factor < -0.5** 时触发；159992 因子分 +3.57（强正）→ 决策表 fall-through 到默认 hold。**两套口径冲突无协调**：持仓明细 tech_signal（:704-706）是**实时技术信号**（真实信号），操作建议基于**因子评分决策表**——技术信号与因子分背离时，规则引擎直接忽略信号（除非因子分也负），且 reason 还暴露"信号 sell"造成文案自相矛盾。

**修复方向（不实施）**：F10——①决策表增加"信号-因子背离"分支：`sig=sell 且 avg_factor ≥ +0.5` → 输出 hold 但 reason 明确解释"技术面偏空但因子分强正（+3.57），暂不追空，跌破 MA20 再降仓"；②或持仓明细 tech_signal 与操作建议 action 并列展示时标注口径（"技术信号：SELL（实时）｜操作建议：hold（因子分主导）"）；③rule 兜底 reason 禁止裸引用"信号 X"当依据而 action 与之相反（文案自洽门禁）。

### 15.3 Q3：持仓明细"因子评分"栏抽象难懂

**现象**：列内容为原始因子键值对——`sentiment.news_heat: 100.00; technical.rsi.rsi_14: 39.53; technical.kdj.d_value: -3.46`（带 σ 后缀被 OCR 识别成 c/o）——无中文名、无方向含义、无值域说明。

**根因**：`portfolio_service.py:695-697`——`factor_summary = "；".join(f"{k}: {v:.2f}σ")` 直接拼接**因子代码**（sentiment.news_heat / technical.rsi.rsi_14…）与数值，无映射/解读。

**修复方向（不实施）**：F11——因子键→中文名映射表（如 `sentiment.news_heat`→"新闻热度"、`technical.rsi.rsi_14`→"RSI(14)"）+ 方向/值域解读（RSI 39.53 → "RSI 39.5，中性偏弱"；KDJ D -3.46 → "KDJ 超卖区"）+ tooltip 完整说明；或改为前端结构化渲染（factor_summary 拆为 `[{key, label, value, hint}]` 数组，前端卡片式展示）。

### 15.4 Q4：sentiment.news_heat 全标的都是 100.00

**现象**：10 只持仓的 news_heat 全部 100.00——同一数值，无区分度，且数值恰好顶格。

**根因（数据管道缺陷，非展示问题）**：`factor_registry.py:1001-1013`——sentiment 因子注入用 **`get_news_headlines()`（全市场新闻头条）** 写入每个标的的 `news_items`（`_news[-30:]`）→ `_compute_news_heat`（factor_registry.py:224-233，30 条 stars 加权和）对**所有标的值相同**。**news_heat 被设计为"标的相关新闻热度"，实际注入的是全市场新闻** → 无区分度（全 100）+ 误导（看起来每个标的新闻热度都很高）。

**修复方向（不实施）**：F12——①news_heat 改按标的新闻（`get_news(symbol)` 标的相关新闻）；②若标的相关新闻不可用 → 该因子降级为**市态级**（全市场热度仅作 regime 输入，不进入持仓明细展示）或从 factor_summary 排除并标注"全市场新闻热度，非个股值"；③IC 计算同步修正（当前全同值导致 IC 样本无效——与 §13.1 sentiment 4 no_data 的"样本<3"部分同源）。

### 15.5 修订记录 v1.5

- v1.5 (2026-08-03)：追加「十五、用户反馈补充诊断 3：策略检查」——①LLM 60s 满超时（R5-1-6 只覆盖快速 500/429，慢响应仍等满 60s，F9 降 30s+区分文案）；②操作建议 vs 技术信号矛盾（决策表 SELL 需 avg_factor<-0.5，因子分强正时 SELL 被忽略且 reason 自曝矛盾，F10 背离分支+口径标注+文案自洽门禁）；③因子评分栏抽象（factor_summary 裸拼因子键+σ，F11 中文名+方向解读）；④news_heat 全 100（注入全市场新闻到每个标的，无区分度+误导，F12 按标的新闻或降级市态级）。均未实施。
