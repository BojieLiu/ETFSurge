# round8 三份文档问题清单核对结果（2026-08-07 容器内实测）

## docs/round8-rediagnosis.md（O1–O27）

| O项 | 结论 | 证据（容器实测） |
|---|---|---|
| O1 instruments 同步 | ⚠️ 部分修复 | 后台化生效（1571 rows 未阻塞启动）；A股个股段 30s TIMEOUT（容器 EM 源被拦） |
| O2 港股 K 线 | ❌ 未修复 | `/market/history/00700?asset_type=HK` 返回 **0 bars**（验收要求 >100） |
| O3 hub 缓存断裂 | ✅ 未复现 | llm-advice 注入市场快照正常（3 市场 llm-report 成功） |
| O4 个股搜索 | ❌ 未修复 | `search?keyword=茅台`、`600519`、`apple` 均 0 命中（instruments A股个股段未同步） |
| O5 涨跌幅值域 | ✅ 修复 | design 426 全部 29 个涨跌样本在 ±10% 内 |
| O6 IC 加权淘汰 | ❌ 未修复 | 13/28 负 IC 因子仍标 valid；reason 文案"IC -0.4490 ≥ 阈值 0.02"逻辑错误 |
| O7 策略检查 LLM | ⚠️ 部分修复 | 兜底 summary 含超时原因 ✓；实测 LLM 仍 60s 超时（covered_by_llm=0） |
| O8 前端性能 | ✅ 修复 | Lighthouse perf：首页 90 / 行情 100 / 组合 99（≥0.7 软目标达成） |
| O9 字段断裂 | ⚠️ 部分修复 | concept_tags 50/50 非空 ✓；watchlist 不传 name 补名 ✗（name=代码）；watchlist 列表 29.9s（验收<1s 未达标） |
| O10 设计预算 | ✅ 未复现超时 | 热缓存设计任务成功（des.426）；冷缓存场景未测 |
| O11 前端状态机 | ✅ 修复 | DashboardAiTools.stateMachine/resetToTools/taskStore 单测绿（388 全绿） |
| O12 timeline join | ✅ 修复 | portfolio.py:477 join TaskRecord；当前无 failed 任务可展示（机制在） |
| O15 消费电子分类 | ✅ 修复 | design 426 中 562950 方向标注"电子" |
| O16 rationale 风格 | ✅ 修复 | 宽基理由为"宽基底仓/提供β"，未见"大盘价值/高弹性"错配 |
| O17 字号/铺满 | ✅ 修复 | theme.css 16px/container 1600px；Lighthouse 无劣化 |
| O18 涨跌幅×100 | ✅ 修复 | design 426：510050 报 -0.23%（复诊时 -23.40%）、518880 -0.11%（-10.70%） |
| O19 heat null 崩溃 | ✅ 修复 | sectors/heat 20 条 change_pct 兜底 0；前端无 console TypeError |
| O20 K线图 | ⚪ 未直接验证 | TechnicalAnalysisModal 存在、无 console error（视觉需人工） |
| O21 IPv6 双栈 | ❌ 容器内未修复/回归 | 容器内 `--host ::` 拒 IPv4（uvicorn 设 V6ONLY）→ Docker 端口映射全失效；已改 0.0.0.0；本地 Windows 场景 OK |
| O22 带前缀A股 | ✅ 修复 | watchlist 中 sh688981 中芯国际 price=128.5 正常 |
| O23 输入框回显 | ✅ 修复 | UnifiedAnalysis.spec 20 tests 绿 |
| O24 标的分析 | ❌ **回归 bug（功能全挂）** | symbol-analysis/stream 全线 STREAM_ERROR：`llm_complete_stream() got an unexpected keyword argument 'rate_limit_cap'`（O24 实施时 analysis.py:923-926 透传了不支持参数） |
| O25 因子 no_data | ⚠️ 部分修复 | reason 已区分（数据源未接入/截面无差异）✓；no_data 仍 6（容器 EM 源被拦，属外部源不可用） |
| O26 板块点位口径 | ✅ 修复 | 板块报告含"板块指数报8455.59点"（标题含 BK1600） |
| O27 市值注入 | ⚪ 未专项验证 | — |

## docs/interaction-redesign.md（P1–P7 状态机）
- ✅ 前端 42 文件 388 用例全绿，覆盖：失败→重试→running（stateMachine 4）、失败不残留（resetToTools 2）、WS/轮询幂等（timer 3）、历史列表含 failed（DesignHistory 10）、taskStore 生命周期（8）、timeline 渲染（DashboardAiTools.history 2）。

## docs/frontend-theme-redesign.md（字号/铺满）
- ✅ theme.css 字号令牌已放大（base 15→16px）、容器 1600px、写死字号 var() 化；Lighthouse performance 90-100 无劣化；全局 JS 无 console error。
