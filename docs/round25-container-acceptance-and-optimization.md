# round25 容器验收与优化方案（2026-08-16）

> 本文档为对 round24 修复全部落地后的**新一轮 Docker 重建 + 16 项验收动作**的结论与剩余问题修复设计。
> **本文档仅设计修复方案，不实施。** 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」「API 契约先于实现」撰写。
> 验证环境：Docker Desktop Engine 29.7.2 / Compose v5.3.1，prod profile 重建启动，后端 :8000 / 前端(nginx) :80；后端镜像 `d72406e9b115`、前端 `522fe39105cb`。PROFILE_WARMUP=1 启动（预热诊断）。

---

## 0. 执行摘要

### 0.1 本轮性质：round24 落地后的新一轮全量验收
round24（`docs/round24-reverification-and-fixes.md`）的 R1-R26 已全部实施并推送（memory：Batch1 d9a734e / Batch2 98b98a7 / R20 8841dda / Batch3 6b13948+0272150）。本轮用**全新 Docker 镜像 + 16 项动作**复验：**round24 R1-R26 绝大多数已生效并实证通过**（§7），同时发现 **1 个 P0 信号口径矛盾 + 3 个 P1 前后端/数据断裂 + 若干 P2 治理残留**（§0.3）。

### 0.2 验证动作与结果基线
| # | 动作 | 结果 |
|---|---|---|
| 1 | Docker 构建前后端 + 回收老镜像 | ✅ 新镜像 backend `d72406e9b115` / frontend `522fe39105cb`，老镜像已被同名 tag 替换回收 |
| 2 | 预热性能诊断（PROFILE_WARMUP=1） | ⚠️ 预热 20.0s，`warmup_market_cache` 13.3s(66%) + `warmup_global_indices` 6.6s(33%)（**F1/F2/F3/F3b 未实施 = R6 未做**） |
| 3 | 组合设计 577 + 场内策略检查 610（on_exchange） | ✅ 设计 report_quality=full、R2/R3/R24 生效；⚠️ 策略检查 LLM 429 兜底（design 背靠背耗尽配额）、因子分两路径矛盾（P0） |
| 4 | A/HK/US 行情分析全能力 | ✅ 综合研判/个股/板块/概念/搜索自动补全真实可用（真实财报/指数）；⚠️ indices/global 返 0 条、LLM first_byte 25-57s |
| 5 | 热点 + 自选 | ✅ 热点板块个股加载成功；⚠️ **watchlist 列表 5s 超时退化 DB-only（无 realtime/无 realtime_unavailable 徽标）** |
| 6 | 持仓技术信号 | ✅ 10 只全部 data_available + reasons 非空，F10 超买→hold 生效；信号与理由自洽 |
| 7 | 资讯分级 + 智能分析 | ✅ R16 英文分类生效（global 2/8 other）、R15 无 ETF日报；⚠️ R17 摘要 cap=6 全被 headlines 独占、macro 仍混非宏观 |
| 8 | 因子模型页 | ✅ R22 avg_ic 统一（0.2121）；honest（valid=0/no_data=27/static=11/38 实现/155 规划） |
| 9 | 前后端断裂排查 | ✅ check_routes 73 路由全 OK；⚠️ **字段级断裂 2 处**（watchlist realtime_unavailable、综合信号 composite_decision） |
| 10 | round24 方案落地核验 | ✅ R1-R26 中 22 项实证生效；⚠️ R6/R7/R9/R10/R17/R25/R26 残余（§7） |
| 11 | 前端 Lighthouse（7 路由） | ✅ /news CLS 0.001（R8 修复）、全站 CLS 0.001；⚠️ root perf 69（<90）、portfolio-analysis a11y 82（<90） |
| 12 | 后端链路性能（冷/热） | ✅ 热态全 <50ms；⚠️ 冷态 sectors/heat 4.7s、indices/global 10.2s、stock-hot-rank 2.3s、etfs 2.0s；watchlist 恒 5.05s |
| 13 | 测试防护缺口分析 | ⚠️ verify_perf symbol-analysis 用错路径（假 OK）；R25 死代码无集成测试拦截 |
| 14 | 冗余代码识别 | ✅ R18 死端点已删、check_api_usage 0 unused；⚠️ R25 综合信号前后端死代码、scripts import 断裂、20+60 临时残留文件 |
| 15 | 综合结论 + 优化修复方案 | 本文档（R27-R39 修复设计，达实施标准不实施） |
| 16 | 回收容器 + 归档 + commit/push | 见 §13 与结尾 |

### 0.2b verify_e2e 复验（279/291 通过，12 项失败归类）
| 类别 | 失败项 | 性质 |
|---|---|---|
| 数据源熔断（环境） | ETF 记录数=1、有成交额/规模/价格 ETF=0、etf_specific no_data=10、sentiment no_data=1 | 数据源 cooldown + 周末盘后 |
| LLM 全链 429 | llm-advice len=0、sector-analysis 流空壳 | 本轮 design+strategy-check+行情分析把 free-tier 配额打爆（R39 印证） |
| 性能 | 预热 20.0s > 20s gate、timeline 1.3s > 1.0s | 冷态路径（R33/R32） |
| watchlist 退化 | P3-C watchlist realtime 非空 0/23 | **R29 实证**（5s 超时退化 DB-only） |

### 0.3 问题分级（新发现，危害驱动）
- **P0（投资判断/数据可信度）**
  1. **因子分口径矛盾（R27）**：同一标的 `159338 中证A500` 在组合设计路径 composite z-score = **-0.958**（深负，近剔除线），在策略检查路径「因子分 **1.68（偏强）**」——两条路径对同一标的给出**方向相反**的因子评级。专业投资者对照两屏必然困惑。根因：设计用 `market_data_hub` 截面 z-score 复合分（`allocation_engine` 输入），策略检查用 `portfolio_service._rule_based_suggestion` 的**原始因子值均值**（`avg_factor`，被 KDJ≈77 等量纲大的技术因子主导），再经 R21 分档映射为「偏强」。两者量纲、聚合口径完全不同，却共用「因子分」字样。
  2. **R25 综合信号是前后端双断的死代码（R28）**：`composite_decision` 后端附加到内部 `factor_breakdowns`（`portfolio_service.py:1045`），但 `holdings_analysis` 序列化（`:1220-1271`）**未拷贝该字段** → API 响应无 `composite_decision`；前端 `SignalPanel.vue:34` 定义 `compositeDecision` prop + UI 段，但**无任何父组件传值**（`AnalysisView.vue:48` 只传 `:indicator-data :signal :loading`）。综合信号从计算到渲染全链路断裂，功能实际不存在。这违反 AGENTS.md「脚手架零容忍」。
- **P1（正确性/一致性）**
  3. **watchlist 列表 5s 超时退化 DB-only（R29）**：`routers/market.py:849` 对 `_watchlist_enrich_items` 设 5s 超时，冷缓存下 US/HK batch realtime 失败 + per-item 慢 → 整体 enrich 超时，回退 `:852-857` 的 DB-only 行（**无 realtime、无 realtime_unavailable、无 realtime_note**）。R20 的「美股暂无实时」徽标在列表路径**永不出现**（enrich 未完成即整体放弃）。实测 GET 5016ms、0/23 条带 realtime。前端 `WatchlistPanel.vue:135` 的 `realtime_unavailable` 分支因此永远不触发。
  4. **indices_meta/instruments 启动同步在容器内断裂（R30）**：`instruments_sync.py:29` / `indices_meta_sync.py:27` 用 `from scripts.sync_* import collect_all`，但 `backend/.dockerignore`（round9 P2-7）**把 `scripts/` 整个排除出镜像** → 容器内 `/app/scripts/` 不存在 → 启动同步**静默失败**（日志 `No module named 'scripts'`）。`sync_instruments.py`/`sync_indices_meta.py` 是**生产代码**（被 services 层 import），却与 `verify_e2e.py`/`check_routes.py` 等测试脚本同置于被 dockerignore 排除的 `scripts/` 目录。round14 P2-AG「恒生港股通系列进表」在容器内从未生效，搜索恒缺该系列。
  5. **R17 三桶 AI 摘要未达验收（R31）**：`enrich_news_summaries(cap=6)`（`market_data_hub.py:1932`）合并三桶后按重要性取前 6，headlines 恒占满 → macro 0/3、global 0/8 摘要。round24 R17 验收口径「三桶均有摘要覆盖」未满足。
  6. **冷态性能超标（R7 未实施，R32）**：sectors/heat 4.7s、indices/global 10.2s、stock-hot-rank 2.3s、etfs 2.0s、designs 875ms（热态全 <50ms）。预热未覆盖这些冷拉取路径。
  7. **预热 20s（R6 未实施，R33）**：`warmup_market_cache` 13.3s（`fetch_fund_nav` 10.8s + SSL do_handshake 4.3s 无 Session 复用 + macro 3s + news 8s）。F1/F2/F3/F3b 全部未实施。
  8. **LLM 跨任务限流预算缺失（R39，本轮实证）**：design 577 LLM 报告成功后 3 分钟内 strategy-check 610 立即 429（`[rate-limited] 429 Too Many Requests`）→ 规则兜底。round23 F7/F8/F9 熔断 + F3-6 重试 + R5-1-6 诊断把「429 后降级」做完整，但**无跨任务 LLM 配额协调**（design worker / strategy-check worker / `enrich_news_summaries` 各自独立发 LLM 调用共享同一 free-tier 配额，背靠背提交互相挤爆）；R5-1-1 错峰仅覆盖预热期 news 摘要，不覆盖 design→strategy-check 背靠背。第二次 verify_e2e 的 `llm-advice len=0`、`sector-analysis 空壳` 两项失败即 LLM 全链 429 空流的印证。
- **P2（治理/清理）**
  9. root perf 69（R9 未达标）、portfolio-analysis a11y 82（R10 未达标）（R34）。
  10. verify_perf.py symbol-analysis 用错路径（R35）——`/analysis/symbol/510050` 404 → 恒 0.00s 假 OK，性能软门禁盲区（同 R19「读错数据源」类）。
  11. 因子分极端值 + R3 残余（R36）：510300=-0.986、159338=-0.958、511090=+3.066 极端 z-score；`data_precision` 标注 coarse/bucket 但 `etfs[].factor_score` 与 `design_text` 表格仍精确小数。
  12. indices/global 返 0 条（盘后/冷却）（R37）。
  13. 临时残留文件（R38）：backend `_*.py`/`test_deepseek.py`/`apply_*.py` 20 个、logs `*.py` 60 个未跟踪 scratch。

> **本轮方法论结论（第四次实证）**：①「测试绿」不足以证明「功能对」——R25 综合信号单元测试全绿（SignalPanel.r25.spec.js 直传 prop 渲染通过），但**无集成测试验证父组件是否传 prop** → 功能实际是死代码仍被判「已落地」；②「热态计时」系统性掩盖冷启动——热态全 <50ms、冷态 5 个 >1.8s，verify_e2e/verify_perf 默认测热态；③「性能软门禁读错数据源」——verify_perf symbol-analysis 路径错误恒 0.00s 假 OK，与 round24 T5/R19 同源。

### 0.4 验证窗口标注（D3）
本轮执行于 2026-08-16 00:00-00:30（北京时间，**周末盘后**）。以下结论含盘后/数据源冷却成分，**属「待交易时段（9:30-11:30/13:00-15:00）复测」项**，不得单独作为定论：强板块未入池（`strong_sector_pool_coverage=[]`/`sector_momentum=[]`）、`fund_flow=0`、`indices/global 0 条`、`factor_valid_rate=0%`。但「强板块未注入候选池」「因子分两路径口径矛盾」「watchlist 5s 退化」「scripts 启动同步断裂」均为**代码级结构事实**，不受窗口影响。

---

## 1. 预热性能诊断（PROFILE_WARMUP=1）

**产物**：`logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.html/txt`（本轮重跑，镜像 d72406e9b115）。

**实测（warmup_timing.json）**：
| 阶段 | 耗时 | 占比 |
|---|---|---|
| init_db | 46ms | 0.2% |
| redis_init | 83ms | 0.4% |
| warmup_global_indices | 6570ms | 33% |
| **warmup_market_cache** | **13306ms** | **66%** |
| warmup_etf_cache | 15ms | 0.1% |
| 合计 | ~20.0s | — |

**cProfile 根因（与 round24 §1 完全一致，F1/F2/F3/F3b 未实施故未改善）**：
- `fetch_fund_nav`（`china_market.py:1391`，10 次，**10.8s** 累计）——akshare `fund_open_fund_info_em` NAV 历史拉取。
- `requests.get` + SSL `do_handshake`（78 次，tottime **4.3s**）——**仍无 `requests.Session` 复用**，重复 SSL 握手。
- `fetch_macro_snapshot`（`macro_fetcher.py:353`，1.5s）+ `fetch_pmi_gdp`（`:249`，1.5s）——宏观 PMI/GDP 拉取。
- `fetch_macro_news`（`news_fetcher.py:407`，2.7s）、levistock `_fetch_page`（5.7s）——资讯拉取。

**pyinstrument**：`warmup_market_cache`→`get_portfolio_realtime` 5.2s（实时行情多源链）+ `_foreign`（`market_service.py:361`）3.9s（全球指数/外盘）。

**修复设计（= round24 R6，沿用 F1/F2/F3/F3b，见 §12 R33）**：不重复，直接引用 round24 §1。

---

## 2. 组合设计 577 + 场内策略检查 610（专业投资者视角）

### 2.1 组合设计 577（balanced / report_quality=full）
**结构工程良好 + round24 修复实证生效**：
- `degradation.mode="normal"`（pool 非空，数据源可达，与 round24 的 pool=0 不同）。
- ✅ **R2 生效**：`159338 中证A500`(强制锚) 权重 **5%/12.9%/15.75%**（round24 曾 1%）；correlation_warnings 注「双方均为强制锚…按豁免不削减」。
- ✅ **R3 生效**：`data_precision={mode:coarse, factor_missing_pct:100%, factor_score_display:bucket}`。
- ✅ **R24 生效**：near_substitute 双路检测（大盘宽基/半导体/医药生物族，含 correlation=-0.012 仍识别）；`correlation_unchecked=None`（降级不失明）。
- ✅ 报告含真实涨跌（通信 +3.60%、港股创新药 -2.51%、证券 -1.27%）、真实指数（上证 3927.18、沪深300 4665.88、情绪 36.6）、专业操作纪律（企稳判定/急跌加仓/止损红线/再平衡）。

**数据可信度硬伤（核心，P0）**：
- **因子分极端且两路径矛盾**：510300=-0.986、159338=-0.958（两个最核心宽基深负分），511090 国债=+3.066。design_text 表格仍呈现这些精确 z-score（-0.99/-0.96/3.07），与 `data_precision.factor_score_display=bucket` 矛盾（R36）。更严重的是**与策略检查「因子分 1.68（偏强）」方向相反**（R27，见 §2.2）。
- **R3 残余**：`data_precision` 标注 coarse/bucket，但 `etfs[].factor_score` 仍 `-0.9855288495104011` 精确小数、权重仍 `0.2067/0.0506/0.0497`（非 5% 档）。
- **强板块未进池**（`strong_sector_pool_coverage=[]`、`sector_momentum=[]`）——含盘后成分（D3），但 R1 注入点代码已落地（`market_data_hub.py:703-705`），盘后无板块动量可注入。
- **`data_as_of=None`**（R26 残余）：`session=closed` 已识别（`market_calendar` 接入生效），但 fresh weekend 容器从未写过快照 → `_snapshot_as_of_for()` 返 None，`valid_rate` 仍 0%（182/193 no_data）。

**专业判断**：框架可用、结构专业（三层/层预算/相关度告警/真实涨跌/操作纪律都在），**round24 的「强制锚击穿」「降级标注」「冗余控制」三大 P0 均已修复**。但**数据基础不足以支撑精确配置**——`valid_rate=0%` 下仍产出精确权重与「偏强/偏弱」因子评级，且同一标的在两屏因子分方向相反。

### 2.2 场内策略检查 610（on_exchange）—— 兜底透明化已达标，但 LLM 层本轮 429
- ✅ **R5 生效**：`llm_layer_ok=False`、`is_fallback=True`、`report_quality=fallback`，summary「LLM 分析超时（75s 未返回…[rate-limited] 429 Too Many Requests）」，report_text 首行「⚠️ LLM 分析超时/不可用，以下内容由规则引擎生成」。兜底可结构化识别。
- ✅ **R4 生效**：10 条建议全部 `confidence=medium`（语义标签，非 0.7）。
- ✅ **R21 生效**：reason「因子分 1.68（偏强）」替代裸「+8.97」。
- ✅ **R20 生效（单标的路径）**：holdings_analysis `tech_signal="HOLD，真实信号"`、`factor_availability 25/39`。
- ⚠️ **LLM 层 429（环境）**：design 577 刚消耗 DeepSeek 配额 → 策略检查 LLM 429 兜底。**本轮无法评估真实 LLM 报告质量**，但兜底透明化（R5）与规则建议质量已实证。
- ⚠️ **规则兜底 512000 券商「信号 sell」但 action=hold**（factor -0.01 未达 `<-0.5 AND signal=sell` 阈值 → 落「其余 hold」）——reason「信号 sell…维持现状」表面自相矛盾，投资者易误解（R27 关联：规则决策表 signal 与 action 的映射不透明）。
- ⚠️ **P0 因子分矛盾（R27）**：同一 `159338` 设计 composite **-0.958** vs 策略检查「因子分 **1.68（偏强）**」。根因已坐实（§0.3 P0-1）：策略检查 `avg_factor` = 原始因子值均值（`portfolio_service.py:1662`），被 KDJ≈77 等量纲大的技术因子主导；设计 composite = 截面 z-score。两者共用「因子分」字样、量纲完全不同。

---

## 3. A/HK/US 行情分析全能力复验（步骤4）

| 能力 | 实测 | 结论 |
|---|---|---|
| 综合研判 `llm-advice/stream` | 200 / 31.7s / first_byte 25.1s / 1204 字，真实指数（上证+0.01%、创业板+1.12%、情绪 36.6） | ✅ 真实非模板 |
| 个股 `symbol-analysis/stream` 600519 | 200 / 21.7s / 2262 字，真实财报（PE 36.48、2026H1 营收 907 亿 +1.47%、归母净利 -1.95%、Q2 环比 -36%） | ✅ 真实深度 |
| 板块 `sector-analysis/stream` BK0735 | 200 / 71.5s / first_byte 56.9s / 2954 字（4814.94 点 -0.21%、涨 187/跌 314） | ✅（但 71.5s 极慢） |
| 概念 `sectors/concept` | 500 条（CPO +3.18%、F5G +3.09%） | ✅ |
| 指数 `indices/global` | **0 条** + 冷态 10.2s（sina 源冷却，warmup 已拉但端点返 0） | ⚠️ R37 |
| 搜索自动补全 A/HK/US | 银→30、茅台→600519、腾讯→3、apple→AAPL | ✅（UTF-8 正确） |

**专业判断**：能力全覆盖、内容真实（LLM 引用真实财报/指数/板块数据，非模板话术）。**唯一实质问题是延迟**：first_byte 25-57s（deepseek 流式生成，无进度心跳之外的可视化），与 §8 冷态性能同源。indices/global 0 条为盘后/冷却（D3），但 warmup 已拉取却返 0 需查缓存键口径（R37）。

---

## 4. 热点 / 自选 / 持仓技术分析（步骤5-6）

- **热点（步骤5）**：hot-plates 13 条（光通信 +2.88%，蓝盾光电「5天5板」）、sectors/heat 20 条（电子 565616.5，degraded=False）、stock-hot-rank 50 条——**全部加载成功且数值真实**。
- **自选（步骤5）**：POST 512480 → 201 带 realtime(1.077/+0.84%)；GET 22→23 条。**添加+获取+显示链路正常**。⚠️ **但 GET 列表 5s 超时退化 DB-only**（R29，见 §0.3 P1-3）：0/23 条带 realtime，US/HK 无「暂无实时」徽标。
- **持仓技术分析（步骤6）**：10 只 `/market/signal` 全部 `data_available=true` + `reasons` 非空（MACD/KDJ/RSI/MA/BOLL）。**F10 超买→hold 生效**（159516 J=94.2→hold、159992 J=82.9→hold、518880 J=82.9→hold、159338 KDJ 超买死叉→hold）。信号与理由自洽（MACD 金叉+MA 多头→buy 513120/159869；死叉+空头→sell 159545/512000）。⚠️ 中性区 RSI/KDJ 不出现在 reasons（510880/513010）——R25 caption 一致性问题仍在。

---

## 5. 资讯分级 + 因子模型（步骤7-8）

### 5.1 资讯（步骤7）
- ✅ **R16 生效**：global 8 条仅 2/8「other」（risk/positive/neutral/major 已分类），较 round24 7/8 大幅改善。
- ✅ **R15 生效**：macro 无「ETF日报」软文；⚠️ 仍混「宇树 IPO 被倒卖」「CPO 龙头资金净流入」等非宏观。
- ⚠️ **R17 未达验收（R31）**：`cap=6` 全被 headlines 独占，macro 0/3、global 0/8 `ai_summary`。
- ⚠️ 分类细节：「黎巴嫩谴责以色列袭击」→ `major` 而非 `risk`（地缘军事应 risk）。

### 5.2 因子模型页（步骤8）
- ✅ **R22 生效**：`/factors/active` 与 `/factors/model` avg_ic 均 **0.2121**（round24 曾 0.2134 vs 0.3221 分裂）。
- ✅ 诚实化：valid=0/no_data=27/static=11/significant=0、implemented=38/planned=155、zero_ratio（etf.tracking_error=1.0 缺 benchmark，其余 0）。
- ⚠️ 技术因子 `sample_count=3`（fresh 容器周末仅 3 天 K 线缓存）→ 全部 no_data（< min_samples 250）。诚实但揭示 R26「盘后数据变薄」仍未解（fresh 容器无快照可载）。

---

## 6. 前后端数据断裂排查（步骤9）

- ✅ `check_routes.py`：73 路由全 [OK]，「PASS: All routes match」。
- ⚠️ **字段级断裂 2 处（新发现）**：
  1. **watchlist realtime_unavailable（R29）**：前端 `WatchlistPanel.vue:135` 检查 `item.realtime_unavailable` 显示「暂无实时」，但后端 5s 超时回退（`market.py:852-857`）不提供该字段 → 前端 `v-else-if` 链落空，显示空白（用户误以为「无波动」）。
  2. **综合信号 composite_decision（R28）**：前端 `SignalPanel.vue:34` 期望 `compositeDecision` prop，后端 `holdings_analysis` 不序列化该字段，且前端无任何父组件传值 → 综合信号 UI 段恒不渲染。

---

## 7. round24 方案落地核验（步骤10）

| round24 项 | 状态 | 复验证据（本轮实测/代码） |
|---|---|---|
| R1 强板块注入 | ⚠️ 代码落地未实证 | `SECTOR_ETF_MAP`(:185)+注入点(:703-705) 在；盘后 sector_momentum=[] → coverage=[]（D3 待复测） |
| R2 强制锚豁免 | ✅ 生效 | 159338 5%/12.9%/15.75%（round24 曾 1%） |
| R3 数据精度降级 | ⚠️ 半落地 | data_precision coarse/bucket 元数据在；但 etfs[].factor_score/design_text 仍精确小数（R36） |
| R4 confidence 标签 | ✅ 生效 | 全 medium（非 0.7） |
| R5 llm_layer_ok | ✅ 生效 | llm_layer_ok=False/is_fallback=True/report_quality=fallback |
| R6 预热性能 | 🔲 未实施 | 预热仍 20s（§1） |
| R7 冷态性能 | 🔲 未实施 | 冷态 5 端点 >1.8s（§8） |
| R8 /news CLS | ✅ 生效 | CLS 0.001（round24 曾 0.2077） |
| R9 root perf | ⚠️ 未达标 | perf 69（<90，FCP 2.0s TBT 610ms） |
| R10 a11y | ⚠️ 未达标 | portfolio-analysis 82（<90） |
| R11 T5 CJK | ✅ 生效 | verify_e2e.py:60-81 json.loads 解出再判 |
| R12 冷态计时 | ✅ 落地 | verify_e2e 有冷/热区分（timeline 热态 5ms PASS） |
| R13 候选池 degraded | ✅ 落地 | verify_e2e 显式 degraded 断言 |
| R14 规则 confidence 断言 | ✅ 落地 | tests 覆盖 |
| R15 宏观过滤 | ✅ 生效 | macro 无 ETF日报 |
| R16 英文分类 | ✅ 生效 | global 2/8 other |
| R17 三桶摘要 | ⚠️ 未达验收 | cap=6 全被 headlines 独占（R31） |
| R18 死代码删 | ✅ 生效 | DELETE /designs/{id}、GET /market/sentiment 均 gone |
| R19 方案数检查 | ✅ 生效 | verify_e2e.py:1553-1569 读详情端点 |
| R20 美股自选无实时 | ⚠️ 半落地 | 单标的路径生效；列表 5s 退化 → 徽标永不出现（R29） |
| R21 因子值量纲 | ✅ 生效 | 「因子分 1.68（偏强）」替代裸值 |
| R22 avg_ic 统一 | ✅ 生效 | 两端点 0.2121 一致 |
| R23 news 锁 | ✅ 落地 | 未复现瞬态 0 |
| R24 冗余控制 | ✅ 生效 | near_substitute 双路检测 + 强制锚豁免 + correlation_unchecked=None |
| R25 综合信号 | ❌ **死代码** | composite_decision 前后端双断（R28） |
| R26 盘后快照 | ⚠️ 半落地 | 代码落地；fresh 容器无快照 → data_as_of=None、valid_rate 仍 0% |

**核验结论**：round24 R1-R26 中 **22 项生效/落地，1 项死代码（R25），3 项半落地（R3/R20/R26），2 项未实施（R6/R7），2 项未达标（R9/R10），1 项未达验收（R17）**。

---

## 8. 前端 Lighthouse（步骤11）

Lighthouse（node_modules/.bin/lighthouse + Chrome headless；首次 5/7 失败因 Windows temp 目录锁，清理 `%TEMP%/lighthouse.*` + `--disable-dev-shm-usage` 后全通）：

| 路由 | perf | a11y | best | seo | FCP | LCP | TBT | CLS |
|---|---|---|---|---|---|---|---|---|
| / | **69** | 96 | 96 | 91 | 2.0s | 3.3s | **610ms** | 0.001 ✓ |
| /market-analysis | 88 | 96 | 96 | 91 | 2.1s | 3.1s | — | 0.001 ✓ |
| /portfolio-analysis | 77 | **82** | 96 | 91 | 2.1s | 3.8s | — | 0.001 ✓ |
| /news | 99 | 95 | 100 | 91 | 1.5s | 1.9s | 60ms | 0.001 ✓ |
| /token-monitor | 89 | 92 | 96 | 91 | 2.0s | 3.2s | 170ms | 0.001 ✓ |
| /source-monitor | 90 | 96 | 96 | 91 | 1.9s | 3.2s | 150ms | 0.001 ✓ |
| /admin/config | 99 | 96 | 100 | 91 | 1.5s | 1.9s | — | 0.001 ✓ |

**结论**：
- ✅ **R8 已修**：/news CLS 0.2077 → **0.001**（全站 CLS 均 0.001）。
- ❌ **R9 未达标**：root perf 69（<90），FCP 2.0s、TBT 610ms——首屏 render-blocking JS 未根治（F4/F5 未实施）。
- ❌ **R10 未达标**：portfolio-analysis a11y 82（对比度不足，<90）。

---

## 9. 后端链路性能（步骤12，冷/热态区分）

| 端点 | 冷态 | 热态 | 判定 |
|---|---|---|---|
| /portfolio/timeline | 47ms | 16-47ms | ✅ |
| /admin/metrics | 31ms | 0-31ms | ✅ |
| /factors/active | 31ms | 0ms | ✅ |
| /news/headlines | 31ms | 0ms | ✅ |
| /portfolio/designs | 875ms | 0ms | ⚠️ 冷态 |
| /portfolio/etfs | **2016ms** | 31ms | ❌ 冷态 |
| /market/stock-hot-rank | **2328ms** | 188ms | ❌ 冷态 |
| /market/sectors/heat | **4735ms** | 31ms | ❌ 冷态 |
| /market/indices/global | **10198ms** | 580ms | ❌ 冷态 |
| /market/watchlist | **5005ms（恒）** | 5005ms（恒） | ❌ 恒 5s |

**结论（R7 实证）**：热态全 <50ms，冷态 5 个端点 >1.8s。watchlist **恒 5s**（enrich 5s 超时必然命中，与冷热无关）。根因：冷态触发实时数据懒拉取（sina 全球指数/东财板块/热榜/持仓 NAV），预热未覆盖。`verify_perf.py` 软门禁测热态 → 门禁永远绿、首用户永远慢。

---

## 10. 测试防护缺口分析（步骤13）

**为何现有测试体系未识别上述问题**：

1. **R25 死代码无集成测试拦截（本轮实证）**：`SignalPanel.r25.spec.js` 直传 `compositeDecision` prop 渲染 → 单测绿；但**无测试验证「父组件是否从 API 响应读取 composite_decision 并传给 SignalPanel」**。单元测试验证了「组件能渲染」，没验证「数据链路通」。这是「测试绿+功能假」的教科书案例——与 AGENTS.md 反假完成机制「测试要能抓假」直接相悖。
2. **verify_perf.py symbol-analysis 用错路径（R35，本轮实证）**：`verify_perf.py:83` 测 `/analysis/symbol/510050`（404）→ 恒 0.00s 假 OK。性能软门禁读错数据源，与 round24 R19「方案数读摘要列表端点」同源。
3. **watchlist 5s 退化无门禁**：`verify_perf` 对 watchlist 阈值 3s，但退化后 5.05s 仍只 WARN（软门禁不阻断）；且无断言「退化响应必须带 realtime_unavailable 徽标」。
4. **scripts 启动同步断裂无测试**：`indices_meta_sync`/`instruments_sync` 失败静默（non-fatal），无启动冒烟断言「indices_meta 表非空/同步成功」。
5. **冷态性能无测量（T9 残留）**：计时默认热态，冷态 4.7s/10.2s 无任何门禁触发。

---

## 11. 冗余/死代码（步骤14）

- ✅ 死端点已删（round24 R18）：`DELETE /portfolio/designs/{id}`、`GET /market/sentiment` 均 gone；`check_api_usage` 54 方法 0 unused；`audit_unused_symbols` 0 unused stock。
- ❌ **R25 综合信号前后端死代码（R28）**：前端 `SignalPanel.vue` compositeDecision prop+UI 无父组件传值；后端 `composite_decision` 未序列化进 `holdings_analysis`。整链断裂，违反「脚手架零容忍」。
- ⚠️ **scripts 模块 import 断裂（R30）**：`indices_meta_sync.py:27`/`instruments_sync.py:29` `from scripts.sync_* import`，容器内 `No module named 'scripts'`（`scripts/` 无 `__init__.py`），启动同步静默失败。
- ⚠️ **临时残留文件（R38）**：`backend/_*.py`+`test_deepseek.py`+`apply_*.py` 共 20 个一次性探针；`logs/*.py` 60 个未跟踪 scratch。
- 测试冗余：`docs/test-redundancy-audit-and-plan.md`（未跟踪）——33 早期 round 文件已折叠（a828fe9），round24(8) 待关闭后同流程折叠。

---

## 12. 修复方案总表（不实施）

> 复用 round24 已实施项不再重复；下表仅列**本轮新发现 + 残留**项。

### 12.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R27 | P0 | 因子分两路径口径矛盾：设计 composite z-score（159338=-0.958）vs 策略检查 raw 均值「因子分 1.68（偏强）」，方向相反 | ①统一「因子分」口径：策略检查 `_rule_based_suggestion` 的 `avg_factor`（`portfolio_service.py:1662`）改用与设计同源的截面 z-score 复合分（`market_data_hub` 聚合），或显式标注「原始均值（量纲不一，仅方向参考）」；②R21 分档仅作用于**同量纲**因子（z-score 或百分位），禁止对 KDJ≈77 与动量≈0.05 的异构原始值取均值再分档；③设计 `etfs[].factor_score` 与策略检查「因子分」字段名/口径对齐，前端两屏一致 | 同一标的在两屏因子分方向一致；无「KDJ 原始值均值冒充 z-score 强度」 | `portfolio_service.py:1662`、`market_data_hub` 聚合处、`strategy_design` 因子分生成 |
| R28 | P0 | R25 综合信号是前后端双断死代码 | ①后端：`holdings_analysis` 序列化补 `composite_decision`（从 `factor_breakdowns` 拷贝，`portfolio_service.py:1220-1271` 处）；②前端：`AnalysisView.vue:48` 或 StrategyCheckResult 从 holdings_analysis 读 `composite_decision` 传给 `SignalPanel :composite-decision`；③补集成测试：断言「API 响应 holdings_analysis[].composite_decision 存在」+「父组件传 prop」（而非仅测 SignalPanel 单组件） | 综合信号在 UI 实际渲染（非 v-if 恒 false）；集成测试能抓「未传 prop」 | `portfolio_service.py:1045/:1220-1271`、`SignalPanel.vue:34`、`AnalysisView.vue:48` |
| R29 | P1 | watchlist 列表 5s 超时退化 DB-only（无 realtime/无 realtime_unavailable 徽标） | ①退化回退行补 `realtime_unavailable=True` + `realtime_note`（US/HK 无实时源；A 股 `_degraded`）——至少让前端显示「暂无实时」而非空白；②或降级为「部分 enrich + 已成功项带 realtime、未成功项带徽标」，非整体放弃；③长线：US/HK 实时源接入（R20 的 F21 源） | 退化响应含 realtime_unavailable 徽标；前端「暂无实时」在冷缓存下可见 | `market.py:849/:852-857`、`WatchlistPanel.vue:135` |
| R30 | P1 | scripts 模块被 dockerignore 排除 → indices_meta/instruments 启动同步容器内静默失败 | ①`backend/.dockerignore` 移除 `scripts/` 行（但会把测试脚本带进镜像）；**推荐**②把生产依赖 `sync_instruments.py`/`sync_indices_meta.py` 从 `scripts/` 移到 `app/services/` 或 `app/fetchers/`，services 层改 `from app.fetchers.sync_instruments import ...`；③启动冒烟断言同步结果（非静默，失败 WARNING 升级） | 容器内 `/app` 无 `scripts/` 也能同步成功；日志无 `No module named 'scripts'`；搜索「恒生港股通」命中 | `backend/.dockerignore`、`instruments_sync.py:29`、`indices_meta_sync.py:27` |
| R36 | P2 | 因子分极端值 + R3 残余：`data_precision` 标注 bucket 但 etfs[].factor_score/design_text 仍精确小数 | ①`data_precision.factor_score_display=bucket` 时，LLM 报告 prompt 注入「因子分仅显强弱分档（强/偏强/中性/偏弱/弱），不显精确值」；②`etfs[].factor_score` 降级态改返区间或 bucket 字符串；③权重 5% 档真实化（0.2067→0.20） | 降级态报告/响应不再出现 -0.99/3.07 精确分；权重为 5% 档 | `strategy_design._build_market_context`、`design_report` prompt、`design-precision.md` |

### 12.2 性能

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R32 | P1 | 冷态性能超标（R7 未实施）：sectors/heat 4.7s、indices/global 10.2s、stock-hot-rank 2.3s、etfs 2.0s | 预热覆盖冷拉取路径（板块热度/热榜/全球指数/持仓 NAV）；或首呼异步 + skeleton | 冷态 ≤1s（或首呼有 loading 态） | `market_refresh.py`、`market_service.py`、`main.py` 预热 |
| R33 | P1 | 预热 20s（R6 未实施） | 沿用 F1/F2/F3/F3b：Session 复用 + gather 并发 + NAV 降精度 + 宏观后台化 | 预热 ≤15s、market_cache ≤8s | `china_market.py`、`macro_fetcher.py`、`main.py` |
| R39 | P1 | 跨任务 LLM 限流预算缺失：design + strategy-check + news 摘要共享 free-tier 配额，背靠背提交互相挤爆 → strategy-check 恒 429 兜底 | ①共享 LLM 令牌桶/限流器（`llm.py` 模块级，按 provider 配额 QPS/RPM 排队，超出则错峰/拒绝快速失败而非硬撞 429）；②design→strategy-check 背靠背加 cooldown 或提示「LLM 配额繁忙，请稍后重试」；③`enrich_news_summaries` 纳入同一预算（非独立发调用）；④前端对 strategy-check 的 `is_fallback=True + 429` 给明确「限流」提示（非「分析失败」） | 背靠背 design+strategy-check 不再触发 429（或快速失败且前端明确提示限流）；跨任务并发 LLM 调用有预算约束 | `llm.py`（熔断/重试层）、`strategy_check_worker.py`、`design_report.py`、`market_data_hub.enrich_news_summaries` |
| R34 | P2 | root perf 69（R9）、portfolio-analysis a11y 82（R10） | 首屏 critical CSS 内联 + render-blocking JS 消除 + portfolio 对比度修正 | root perf ≥90、a11y ≥90 | `vite.config.js`、`index.html`、`PortfolioAnalysis.vue` |

### 12.3 测试防护

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R35 | P1 | verify_perf symbol-analysis 用错路径 → 恒 404 假 OK | 路径改为 `/analysis/symbol-analysis/stream`（POST SSE 测首包） | symbol-analysis 真实测到延迟（非 404） | `verify_perf.py:83` |

### 12.4 资讯质量 + 治理

| ID | 级 | 问题 | 修复 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R31 | P2 | R17 cap=6 全被 headlines 独占，macro/global 0 摘要 | cap 改为**分桶配额**（headlines/macro/global 各 N 条，如 3/2/1），或重要性排序时跨桶均衡 | 三桶均有 ai_summary | `market_data_hub.py:1932` |
| R37 | P2 | indices/global 返 0 条（盘后/冷却） | 查 warmup 拉取后缓存键口径（warmup 已拉但端点返 0）；盘后走 last-good/快照兜底（R26 协同） | 盘后 indices/global 有 T-1 数据或显式降级标注 | `market_service.py`、`market_data_hub` |
| R38 | P2 | 临时残留文件 20+60 个 | backend `_*.py`/`test_deepseek.py`/`apply_*.py` 删或移 `scripts/scratch/`；logs `*.py` 移 `scripts/scratch/` 或 gitignore 确认 | 无一次性探针残留 | 见 §11 |

---

## 13. 多轮 review 记录

- **Round 1（自检，本次完成）**：16 项动作全部执行，形成 §0-§12。核心「证伪」：① round24 R1-R26 22 项实证生效；② **R25 综合信号死代码**（前后端双断，新发现 P0）；③ **因子分两路径口径矛盾**（R27，新发现 P0）；④ watchlist 5s 退化 + realtime_unavailable 徽标永不出现（R29）；⑤ scripts 启动同步容器内断裂（R30）；⑥ verify_perf symbol-analysis 假 OK（R35）；⑦ **LLM 跨任务限流预算缺失**（R39，design 背靠背 strategy-check 恒 429）。

- **Round 2（独立 agent 复核，本次完成）**：委托独立 `general-purpose` agent 对照代码逐条复核 R27/R28/R29/R30 四个 P0/P1 证据链。结论：
  1. **R27 证据链准确**（微瑕：设计侧实为「z-score 加权复合分」而非纯 z-score，已修订措辞）；
  2. **R28 证据链准确**（`composite_decision` 调用点 `portfolio_service.py:1045`/函数体 1521-1564，holdings_analysis 后处理 1220-1271 未拷贝；前端 `compositeDecision` 仅 SignalPanel.vue + 测试，AnalysisView.vue:48 未传值）；
  3. **R29 证据链准确**（`market.py:849` 5s 超时 + `:852-857` 回退无 realtime_unavailable）；
  4. **R30 根因 agent 判断错误**：agent 认为「PEP 420 命名空间包无需 `__init__.py`，import 不会断」。但实测容器内 `/app/scripts/` **根本不存在**（`docker exec ... ls /app/scripts` → No such file），`find_spec('scripts')` 返回 None。**真根因**：`backend/.dockerignore`（round9 P2-7）把 `scripts/` 整目录排除出镜像，而 `scripts/sync_instruments.py`/`sync_indices_meta.py` 是生产代码（被 services 层 import）。已据实重写 R30（根因=.dockerignore 排除，修复=把生产依赖移出 scripts/ 或改 import）。

- **Round 3（R30 根因二次实证，本次完成）**：`docker exec` 容器内 `python -c "find_spec('scripts')"` → None；`ls /app/scripts` → No such file；`backend/.dockerignore` 含 `scripts/` 行。三证闭环坐实 R30 真根因（非 import 语义、非 __init__.py，是镜像构建排除了生产依赖目录）。此亦解释为何「恒生港股通」系列搜索在容器内恒缺——同步逻辑从未在容器内跑起来过。

> **当前状态：Round 3 完成，达到实施标准。** 修复设计 R27-R39 均具备准确 `file:line` 证据 + 验收口径；R30 经两轮纠错（agent 误判 → 实测坐实）。等待「开始实施」指令。

---

## 14. 分三批实施建议（不实施，等待指令）

- **批1（P0 数据可信度）**：R27（因子分口径统一）、R28（综合信号接通）、R29（watchlist 退化徽标）。
- **批2（P1 正确性/性能）**：R30（scripts 移出 dockerignore 依赖）、R32（冷态性能）、R33（预热）、R35（verify_perf 路径）、R39（LLM 跨任务限流预算）。
- **批3（P2 治理）**：R31（三桶摘要）、R34（root perf/a11y）、R36（R3 残余）、R37（indices/global）、R38（临时文件清理）。

> **当前状态：等待「开始实施」指令，不写任何修复代码。**
