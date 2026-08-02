# 用户反馈问题修复与测试防护体系分析（round5-ux 批次）

> 范围：2026-08-02 晚用户连续反馈的 16 项问题（交互/数据/性能/映射），含已修复 12 项（清单 ✅）、
> 方案待实施 4 项、误报 1 项；并对每个 bug 做「为何测试防护未发现」根因分析与弥补方案。
> 状态：**修复方案均已评审通过并提交；测试防护弥补方案为设计（未实施）**。

## 一、问题清单总览

| # | 问题 | 类别 | 状态 | 修复/方案 commit 或文档 |
|---|------|------|------|--------------------------|
| 1 | 因子模型 30 因子无数据、政策因子 0 有效 | 后端数据 | 🟡 方案待实施 | IC 仅请求驱动（R1 未实施）→ round5 R5-1-5；政策因子为 Z03 静态设计 |
| 2 | 策略检查 LLM 超时（429 限流→rule 兜底） | 后端稳定性 | 🟡 方案待实施 | 退避 cap 与 60s 预算冲突；P0 方案（对话中提出）：原因留痕 + cap 适配，见 §三 |
| 3 | 持仓技术分析"所有标的一样" | 前端疑似 | ⚪ 误报/待确认 | 实测代码+数据源均正常（5 标的 signal 各异）；疑 PWA 旧缓存；顺带发现场外技研链路 bug（见 #17） |
| 4 | 技术分析切换周期无效 | 前端交互 | ✅ 已修复 | `eb0afae`：indicators/signal 未传 period + 缺 watch(period) |
| 5 | 自选添加后数据为空 | 前后端性能 | ✅ 已修复 | `804bd21`：watchlist 串行富化 + POST 无 realtime |
| 6 | 板块分析报告"未提供 K线/成交额/资金流" | 后端 prompt | ✅ 已修复 | `88f4b75`：sector_data 行情快照未注入 prompt |
| 7 | 板块概念映射不全（芯片/光模块 404） | 后端映射 | ✅ 已修复 | `f141e43`：前端固定 industry，概念名只在概念表 |
| 8 | 指数分析数据缺失/错位 | 后端数据 | ✅ 已修复 | `498bb2b`：get_asset_realtime 无 index 分支，000001→平安银行 |
| 9 | 自动补全选定后显示"名称(代码)" | 前端 UX | ✅ 已修复 | `a617319`：改为"代码 名称" |
| 10 | 搜索自动补全约 1s | 前端性能 | ✅ 已修复 | `86634ee`：debounce 300→200 + abort + seq + 60s 缓存 |
| 11 | 标的分析输入框 placeholder 截断 | 前端 UX | ✅ 已修复 | `843f319`：文案精简 + title |
| 12 | 标的分析自动补全完全不工作 | 前端交互 | ✅ 已修复 | `7355202`：@input 未写回 searchQuery |
| 13 | 标的分析点"分析"无动作 | 前端交互 | ✅ 已修复 | `67053cd`：pickSearchItem 未同步 searchQuery + 空输入静默 |
| 14 | 市场 tab 切换残留旧市场分析/投顾回答 | 前端交互 | ✅ 已修复 | `e93138e`：两个组件缺 watch(marketTab) 重置 |
| 15 | 行情研判切换市场自动触发 LLM | 前端交互 | ✅ 已修复 | `8aba789`：watch 里自动 generate() 移除 |
| 16 | A 股研判缺国内宏观/流动性数据 | 后端数据 | 🟡 方案待实施 | 方案（对话中提出，未入库）：macro_fetcher + `domestic_macro` 上下文段，见 §三 |
| 17 | （顺带发现）场外基金技术分析失败 | 后端数据 | 🟡 方案待实施 | `taTarget` 用场内 ETF 代码 + assetType='index' 查询 → 021458/022449"暂无数据" |

## 二、已修复 bug 根因与回归测试

### 前端交互接线类（#4/#9/#12/#13/#14/#15）

**共性根因**：Vue 组件的事件处理器「只调用了子逻辑、未同步状态源」，或「缺少对 prop 变化的 watch 重置」。
这类 bug 全部是**接线层缺失**，不是数据/逻辑错误——组件内部函数本身正确，但用户操作路径没有完整接线。

| # | 根因（文件:行） | 修复 | 回归测试 |
|---|----------------|------|---------|
| 12 | `UnifiedAnalysis.vue` @input 只调 `search.onSearchInput()` 不写回 `search.searchQuery`（恒空→永不触发搜索） | 新增 `onInput(e)` 先写回再触发 | `UnifiedAnalysis.spec.js`：symbol 输入 → searchQuery 更新 |
| 13 | `pickSearchItem` 只写 `query/symbol`，`doAnalyze` 读 `search.searchQuery`（旧值/空 → 静默 return） | pickSearchItem 同步写回 searchQuery；空输入加"请输入标的代码或名称"提示 | +2 用例（同步/空提示） |
| 4 | `api/index.js` indicators/signal 不接受 period；`fetchChart` 只给 chart 传 period；无 watch(period) | api 加 period 参数；三请求统一传 `period.value`；`watch(period, fetchChart)` | `AnalysisView.spec.js`：切 weekly/monthly → 三请求带新 period |
| 15 | `MarketReport.vue` watch(marketTab) 里自动 `generate()`（R4-28 旧逻辑） | 移除自动生成，切换只 stopStream+清空，按钮空态由用户触发 | `MarketReport.spec.js`：切换后 startMock 不调用 |
| 14 | UnifiedAnalysis/AiAdvisor 均无 watch(marketTab) 重置 | 两个组件加 watch：stopStream + 清空 result/response/输入/补全状态 | `UnifiedAnalysis.spec.js`：A→US 清空全状态 |
| 9 | `useMarketSearch` 补全/选定格式 `名称 (代码)` | 改为 `代码 名称`（updateCompletion + acceptCompletion） | +1 用例（代码前置、无括号） |

### 后端数据错位/缺失类（#6/#8/#17）

| # | 根因（文件:行） | 修复 | 回归测试 |
|---|----------------|------|---------|
| 8 | `get_asset_realtime` 无 `asset_type=="index"` 分支 → 000001 走 A 股路径返回**平安银行 11.63**（指数分析拿到错位行情） | 加 index 分支：`fetch_index_realtime`（新浪 s_sh 三级降级）+ 本地缓存兜底 | `test_china_market_degradation.py`：index realtime 不得返回股票价 |
| 6 | `sector_analysis_stream` prompt 只有 name/成分股/资讯——`sector_data` 已含成交额/主力净流入/换手率/涨跌家数但**未注入** | prompt 增加"板块实时行情"段（sector_snapshot），引导资金面/技术面定量分析 | 手动验证（实测数据 4647亿/94.97亿） |
| 17 | 场外基金 `taTarget` → `{sym: tracked_index(场内ETF代码), assetType:'index'}` → `fetch_index_history(513120)` 查错 | **未实施**（方案：taTarget 对场内代码用 assetType='A'；或后端解析真实指数） | 无 |

### 后端映射/性能类（#5/#7/#10）

| # | 根因 | 修复 | 回归测试 |
|---|------|------|---------|
| 7 | 前端 sector 模式固定 `sector_type:'industry'` → 概念名只在概念表 → 404；`_normalize_sector_code` 支持双表但调用处只传单表 | `sector_analysis_stream` 取行业+概念**双表**合并归一化 | `test_analysis_gate_quality.py`：概念名合并表命中 |
| 5 | `watchlist_list` 串行逐 item 实时富化（N×0.5-2.4s）；POST 响应无 realtime → 添加后等数秒 | 并行 `asyncio.gather` + 3s 超时截断；POST 响应带 `realtime`；前端乐观插入 | `test_watchlist_dirty.py`：POST 含 price/change_pct/volume |
| 10 | 搜索 1s = 前端 debounce 300ms + 无竞态；后端实测 4-14ms 非瓶颈 | debounce 200ms + AbortController + seq 守卫 + 60s 关键词缓存 | `useMarketSearch.spec.js`：seq 丢弃/缓存命中/debounce |

### 报告质量类（#1 相关顺带、round5 补充）

| 修复 | commit | 说明 |
|------|--------|------|
| 入选理由不再截断（≤80 字 → 完整保留） | `581633a` | 旧 `_compress_rationale` 砍掉估值/资金流/市态尾部；竖线转义防表格拆裂 |
| SummaryCards 优化（分组/正负号/tooltip/刷新指示） | `98f0bb6` | 修负数百分比丢负号 bug；CLS 安全（常驻占位） |

## 三、待实施方案（4+1 项）

1. **#1 因子 IC 后台计算**（R1，round5 R5-1-5）：`_last_ic_batch` 仅请求驱动，重启后 30 因子全 no_data；后台循环补 `compute_periodic_ic`。
2. **#2 策略检查 LLM 超时**（P0 两项）：①超时 summary 透传最后失败原因（429/超时区分）；②`_rate_limit_wait` cap 参数化（策略检查 cap 10s + max_retries=1）——60s 预算内快速失败。根治需 R5-1-1（全局 LLM 信号量 + 429 任务排队）。
3. **#16 国内宏观数据管道**：`macro_fetcher.py`（LPR/中美利差/M2/CPI-PPI，akshare 实测 4/6 可用）+ `llm_context` 加 `domestic_macro` 段 + 契约补字段 + 8 用例。
4. **#17 场外基金技术分析**：`taTarget` 对 tracked_index 为场内代码时改 `assetType='A'`（或后端解析真实指数代码）。
5. （顺带）**#3 疑 PWA 缓存**：确认用户强刷后是否恢复；若仍异常需浏览器 Network 抓包。

## 四、测试防护体系漏洞分析——为何未发现这些 bug

### 4.1 按 bug 类型归纳（12 个清单内已修复 bug；顺带 2 项 rationale 截断/SummaryCards 未纳入分类）

| 类型 | bug 数 | 测试防护缺失点 | 根因 |
|------|--------|----------------|------|
| **前端交互/接线**（#4/#9/#12/#13/#14/#15，含 watch 缺失子类） | 6 | 现有组件测试**全 mock composable/store**，测的是"mock 后直接调内部方法"的 happy path，**从未断言「真实用户输入流」（input 事件 → 状态写回 → 请求触发）**；#14/#15 的 watch 缺失（prop 变化无重置）同样测不到 | 测试替身隔离了组件与真实状态的联动：mock 的 `useMarketSearch` 返回 stub，`searchQuery` 是否被写回无人断言 → 接线断点静默通过；无"prop 切换 → 状态重置"测试矩阵 |
| **后端资产类型分支缺失**（#8） | 1 | `get_asset_realtime` 测试只覆盖 A/HK/US，**漏 index/gold 等分支**；且测试断言"非空"而非"值正确" | 分支覆盖不全——枚举资产类型未参数化 |
| **prompt 数据注入缺失**（#6） | 1 | prompt 构建测试只断言"结构存在/标题唯一"，**不断言关键数据段（realtime/板块快照）已注入** | 测试关注格式而非数据完整性 |
| **集成层传参错误**（#7） | 1 | `_normalize_sector_code` 有单测（纯函数），但**调用处传单表**是集成层 bug——单测测不到调用方 | 路由层无集成测试（mock hub + 断言映射结果） |
| **性能/串行化**（#5/#10） | 2 | 性能问题（串行富化 5-12s、debounce 300ms）**无基准断言**——功能测试通过但耗时退化无感 | 缺少性能预算门禁（后端响应时间、前端 debounce 常量） |
| **UX 展示**（#11 placeholder） | 1 | placeholder 长文案截断属视觉细节，无断言 | 视觉类问题依赖人工走查（Lighthouse/截图） |

### 4.2 更深层的三个结构性原因

1. **测试与用户操作路径脱节**：单测验证"函数正确"，用户反馈暴露的是"**路径没接上**"。mock 替身让接线断点"看起来正常"——`onSearchInput()` 被调用即通过，但没人检查它读的状态是否被写入。
2. **数据类 bug 依赖真实数据形态**：000001→平安银行、板块快照未注入、概念名映射——mock 数据都是"理想形态"（000001 就返回指数），**真实数据的"代码撞车"（000001 既是上证指数又是平安银行）只有真实数据源才暴露**。
3. **性能问题无门禁**：功能正确 ≠ 体验达标。串行富化、300ms debounce 都"功能正确"，但用户感知是"慢/空"。

## 五、测试防护体系弥补方案（设计，未实施）

### 5.1 前端：交互型组件测试改为「真实 composable + mock 网络」

- **原则**：对含输入/补全/切换的组件（UnifiedAnalysis / AiAdvisor / MarketReport / WatchlistPanel / AnalysisView），测试**不 mock useMarketSearch 等业务 composable**，改用真实 composable + 只 mock `api` 层（axios/网络）——这样 `onInput 写回 → searchQuery → debounce → api 调用` 全链路在测试中真实运行。
- **新增测试模式**：
  - `input 事件 → 状态写回 → 请求参数` 断言（用户输入流）
  - `prop 变化（marketTab/activeTab/period）→ 状态重置/请求重发` 断言矩阵（对每个带 prop 的组件）
  - 所有修复 bug 的回归用例已在对应 spec（见 §二 表）——**将"用户反馈即测试用例"固化为流程**。

### 5.2 后端：分支参数化 + prompt 完整性 + 路由集成测试

- **资产类型分支参数化**：`get_asset_realtime` 测试用 `@pytest.mark.parametrize` 覆盖 A/ETF/HK/US/index/gold/oil/silver 全部分支，断言「返回值与分支匹配」（指数不得返回股票价）。
- **prompt 数据完整性断言**：sector/symbol/index 分析的 prompt 构建，增加"关键数据段已注入"断言（行情快照字段在 prompt 文本中，非空输入时）。
- **路由层集成测试**：对 sector_analysis_stream 等，mock `market_data_hub` 双表数据 + 断言「概念名映射成功、无 404」（覆盖调用处传参——纯函数单测测不到）。

### 5.3 性能门禁

- 后端：watchlist/calculate 等端点增加**响应时间基准测试**（慢源 mock 下断言并行化后 <阈值）。
- 前端：对 debounce 等常量做**常量快照测试**（SEARCH_DEBOUNCE_MS=200 断言，防回归到 300）。

### 5.4 流程固化

- **每个用户反馈必须产出：根因分析 + 修复 + 回归测试**（本轮实践：11/12 个清单 bug 带自动回归用例，#6 板块快照为手动验证——prompt 注入断言应补自动用例；#11 placeholder 为视觉类人工走查）——把"用户反馈"作为测试用例的第一来源。
- 前端 bug 修复的回归测试**必须走真实输入流**（input/click 事件驱动），禁止只调内部方法断言。

## 六、结论

- 12 个清单内已修复 bug 中，**6 个前端交互接线 bug 是测试防护最大盲区**——mock 替身隔离了状态联动，接线断点静默通过；弥补核心是「真实 composable + mock 网络」的组件测试模式。
- 后端 3 个数据类 bug（指数错位/板块快照未注入/概念映射）暴露的是「分支覆盖不全 + prompt 完整性无断言 + 集成层无测试」——分别对应 §5.2 三项。
- 4 项待实施方案（IC 后台计算 / LLM 超时 / 国内宏观 / 场外技研）已引用对应方案，属 round5 后续批次。
