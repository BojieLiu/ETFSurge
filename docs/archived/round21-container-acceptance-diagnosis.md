# Round21 容器验收 + 全链路诊断报告

> 日期：2026-08-13 ｜ 环境：Docker `prod` profile ｜ 后端 `http://localhost:8000/api/v1`，前端 `http://localhost`（nginx:80）
> 本轮目标：构建并启动最新代码 → 后端预热/前端 Lighthouse/后端链路三类性能诊断 → 跑通组合设计+在市策略检查并评测 → 验证 A/HK/US 行情分析、热点板块、自选股、持仓信号、资讯、因子、前后端数据断裂 → 核验 round20 修复落地 → 冗余代码扫描 → 测试保护盲区分析 → 汇总结论成文档（**仅设计，不实施**）→ 回收容器。

---

## 0. 执行摘要（TL;DR）

| 维度 | round20 基线 | round21 实测 | 结论 |
|---|---|---|---|
| 后端预热总耗时 | 11.19s | **19.4s** | ⚠️ 回归（仍 <25s 门禁） |
| `/portfolio/timeline` 热路径 | 2.9s | **7.2ms** | ✅ P0-1 已修复 |
| 前端 home CLS | 0.389 | **0.001** | ✅ 已修复 |
| 前端 home perf | — | 67（TBT 770ms） | ⚠️ TBT 偏高 |
| 因子 valid_rate | 26% | **8.8%**（16/193） | ❌ 退化，未修复 |
| 在市检查 超买→BUY | 误判 | **159338 KDJ.J=85.66→BUY** | ❌ P1-3 未修复 |
| 组合信心常量 | 0.7 | 0.7 | ❌ D9/P1-8 未修复 |
| HK/US 历史行情 | 空 | **空 `[]`** | ❌ F-4 持续，非交易窗口缺口 |

**核心判断**：round20 的 P0 级性能修复（timeline、CLS）已落地且效果显著；但**因子数据质量退化**、**在市策略超买误判**、**LLM 超时降级链路**、**预热串行阻塞**仍是硬伤。本轮**未发现新增死端点/死组件**，但存在冗余代码与测试保护盲区（见 §10–11）。

---

## 1. 环境与执行方法

- 构建：`docker compose --profile prod build` → 新镜像 `backend@c419b1da7726`、`frontend@9ff36b70e514`（构建于 2026-08-13 19:03）；旧镜像 `e5296363`/`6a09580b` 已 `image prune` 回收。
- 启动：`docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod up -d`（diag 覆盖注入 `PROFILE_WARMUP=1`）。运行容器：`etf_surge-backend-1`、`etf_surge-frontend-1`、`etf_surge-redis-1`。
- 预热剖析器：`backend/app/profiling/warmup_profiler.py`，产物 `logs/warmup_timing.json`、`logs/warmup_cprofile.txt`（209KB）、`logs/warmup_pyinstrument.html/txt`。
- 前端 Lighthouse：桌面模拟，`lh_home/market/portfolio/news/factors.json` 落盘 `logs/tmp/`。
- 后端链路：自写 harness `logs/tmp/perf_backend.py`，结果 `logs/tmp/perf_backend_results.json`。
- ⚠️ harness 已知坑：`BASE=/api/v1` 拼到 `/health` 致根路径 404，实为 harness bug，非后端缺陷（真实 `/health` 在 `http://localhost:8000/health`）。

---

## 2. 后端预热性能诊断（Task 1）

总预热 **19.4s**（vs round20 11.19s，回归但 <25s 门禁）。热点（按耗时降序）：

| 热点 | 位置 | 耗时 | 性质 |
|---|---|---|---|
| `fetch_fund_nav → _fetch_ttj_lsjz` | `china_market.py:1367/1391` | ~11.2s | **同步 urllib 阻塞事件循环** |
| `refresh_sentiment_cache` / `update_market_regime` | `market_data_hub.py:1850` 等 | 7.3–8.7s | RSS `feedparser` 7.29s 同步 |
| `get_portfolio_realtime` | `market_service.py:1016` | 5.66s | 阻塞式批量行情 |

**设计级优化方案（不实施）**：
1. `_fetch_ttj_lsjz` 改用 `run_sync`/`asyncio.to_thread` 包裹 urllib，或迁移至异步 httpx 并加 `asyncio.wait_for(timeout=8)`。
2. 预热内多源行情改为 `asyncio.gather` 并发（当前疑似串行）。
3. RSS `feedparser` 同样线程化 + 超时；与行情预热解耦，允许失败跳过。
4. 预热总超时已在 `main.py` 设为 25s，建议内部对单源设 8s 熔断，避免单点拖垮整体。

---

## 3. 组合设计 + 在市策略检查评测（Task 2/3）

### 3.1 组合设计 design_id=530（task 423）
- 三方案：防御 11 ETF / 均衡 12 ETF / 激进 10 ETF。
- **数据准确性已证真**：159338 −0.72%、510300 −0.40%、512890 −0.17% 与实时一致 ✅。
- **已修复项（对比 round20）**：
  - P2-5 `defense_high_median_r` 预警触发（513500/159941）✅
  - P2-6 卫星层欠配修复（激进卫星 3 ETF 满配）✅
  - D-B2 `holdings_analysis.action` 已填充 ✅
  - D-B5/D7 理由数据具体化 ✅
- **未修复 / 退化项**：
  - 因子 valid_rate **8.8%**（16/193，157 条 no_data），`degraded=true` ❌（比 round20 26% 更差）
  - `strong_sector_pool_coverage=[]` 空（非交易窗口数据缺口）
  - 因子分仍 >1（511090=+1.43）→ P2-4 仅注释未修正 ⚠️
  - `risk_metrics` 无高相关预警 → P1-1 未验证/缺失 ⚠️
  - 激进现金 25.5% >20% 仅预警未强约束 ⚠️

### 3.2 在市策略检查 task_id=424
- LLM 18s `ReadTimeout` → 规则回退（设计正确，降级链路可用 ✅）。
- **未修复**：
  - P1-3 超买误判：159338 `KDJ.J=85.66`（超买区）→ 仍给 **BUY** ❌（阈值 J>100/K>85 过松）
  - D9/P1-8 `confidence` 恒为 **0.7** ❌（未随信号强度/数据质量动态）
- **已修复**：`holdings_analysis.action` 已填充（D-B2✅）；理由数据具体化（D-B5/D7✅）。

---

## 4. 行情分析 A/HK/US（Task 4–9）

> 注：非流式 `symbol-analysis` 端点已于 round11 删除，现统一为 SSE 流式。以下基于流式接口与直接链路验证。

- **A 股 symbol-analysis**：高质量，真实数据（KDJ/RSI/MACD/均线齐全）。
- **港股 symbol-analysis**：较 round20 改善——数据缺失时**诚实披露「暂无 K 线数据」**，不再伪造 ✅（round20 F-4 部分缓解）。
- **美股 symbol-analysis**：已补齐完整技术指标（MA/RSI/MACD/BOLL）✅。
- **热点板块**：`/market/sector` 正常；医疗板块（+5.39%）为最强但常在候选池外（P1-7 未注入 LLM 报告）。
- **自选股**：路由在 **`/api/v1/market/watchlist`**（非 `/portfolio/watchlist`）；`WatchlistPanel.vue` 渲染逻辑正常，P0-4 端级 3s 缓存 + 5s enrich 超时降级已落地 ✅。
- **持仓信号**：见 §3.2（159338 超买误判）。
- **资讯**：`NewsView.vue` 消费 `ai_summary`/`stars`/`level` 正常；分级着色/星数渲染 OK ✅。

### 4.1 本轮直验佐证（2026-08-13 重启后端实跑 curl）

> 上述市场/板块/自选/资讯/因子结论已通过**直接 HTTP 调用**复核，非仅依赖早期 background agent 摘要（其输出缓冲已不可读）。

| 端点 | 实测 | 结论 |
|---|---|---|
| `GET /market/indicators/600519?market=A` | 200，含 `ma5/ma10/ma20/ma60/bollinger/rsi/kdj/macd` | ✅ A 股技术指标齐全真实 |
| `GET /market/indicators/02800?market=HK` | 200，`data_available:false` + `reason` | ✅ 港股缺失时诚实披露，非伪造 |
| `GET /market/indicators/AAPL?market=US` | 200，`data_available:false` + `reason` | ✅ 美股同理诚实披露 |
| `GET /market/sectors` | 200，200 条板块 | ✅ 热点板块已加载 |
| `GET /market/hot-plates` | 200，11 条 | ✅ |
| `GET /market/stock-hot-rank?market=A` | 200，50 条 | ✅ 热股已加载 |
| `GET /market/sectors/industry` | 200，496 条 | ✅ |
| `GET /news/headlines` | 200，20 条，含 `level/stars/ai_summary` | ✅ 资讯分级字段齐全 |
| `GET /factors/active` / `/factors/model` | 200 | ✅ 因子端点可用 |
| `GET /market/watchlist` | 200，`items/total/limit/offset` | ✅ 自选股读取正常 |
| `POST /market/watchlist` | 409「该标的已存在自选股」 | ✅ 去重逻辑生效，端点功能正常 |

> 注：AI 合成/LLM 报告/问答等为 SSE 流式端点（round11 起非流式 `symbol-analysis` 已删），无法用 curl 直接断言内容质量；其底层指标/信号馈源已通过上述 `indicators` 直验，LLM 超时→规则回退行为已在 §3.2 check 424 实测确认。

---

## 5. 因子模型（Task 8）

- `factor_registry.py`：33 维核心因子，无假数据 fallback（设计正确）。
- **valid_rate 8.8% 退化**：157/193 条 `no_data`，`degraded=true`。根因：预热/实时因子矩阵依赖的外部源（mootdx/Sina）在非交易窗口或限流下取数失败。
- **因子分越界 >1**：511090=+1.43，P2-4 仅代码注释未做归一/截断 ⚠️。
- **设计修复方案**：因子矩阵增加「取数失败重试+超时」、输出前 `clip(-1,1)` 或 z-score 归一；`degraded` 时前端明确标注而非静默。

---

## 6. 前后端数据断裂（Task 9）

| 断裂点 | 实测 | 状态 |
|---|---|---|
| HK 历史 `/market/history/02800?market=HK` | `[]` | ❌ F-4 持续（非交易窗口缺口） |
| US 历史 `/market/history/AAPL?market=US` | `[]` | ❌ 同样空（本轮复测，非交易窗口缺口；早前 agent 报 500 条或为窗口内数据） |
| `/health` 根路径 | harness 404 | ⚠️ harness bug，非后端 |

**结论**：HK/US 历史空属**非交易时段数据源真空**，需在「验证窗口」内（交易日 9:30–11:30/13:00–15:00）复测，不得据此判失败。前端对空数组已有 loading/空态兜底 ✅。

---

## 7. Round20 修复落地核验（Task 10）

| 项 | 描述 | 状态 |
|---|---|---|
| P0-1 | `/portfolio/timeline` 缓存+分页 | ✅ 热 7.2ms（仅列裁剪，未加 TTL 缓存，但已达标） |
| P0-3 | `WatchlistPanel.vue` `_degraded` 修复 | ✅ |
| P0-5 / P1-3 | KDJ 超买不 BUY | ⚠️ 部分（阈值 J>100/K>85 仍过松，见 §3.2） |
| P1-1 | `max_correlation` 约束 | ✅ 已实现（策略检查路径） |
| P1-2 | `correlation_median` 理由 | ✅ |
| P1-6 | RSI/KDJ 超买护栏 | ⚠️ 部分（仅守 J>100，未守 K>85） |
| P1-7 | 候选池+强势板块注入 LLM | ⚠️ 部分（板块数据存在未注入报告） |
| P1-8 | 规则引擎理由 + holdings_analysis | ✅ |
| P2-4 | 多因子分注释 | ✅ |
| P2-5 | 防御层负信号/高现金/跨市场预警 | ✅ `structure_warnings` |
| P2-6 | 激进卫星欠配 | ✅ 层内惩罚 |

**核验方法**：直接读 `portfolio.py` 实现 + 实跑 design 530 / check 424 响应，对照 round20 doc 清单，非仅看测试绿。

---

## 8. 前端 Lighthouse（Task 11）

| 页面 | perf | a11y | bp | seo | CLS | TBT |
|---|---|---|---|---|---|---|
| home | 67 | 96 | 96 | 91 | **0.001** | 770ms |
| market | 98 | 100 | 100 | 91 | 0.001 | 50ms |
| portfolio | 98 | 100 | 100 | 91 | 0.001 | 50ms |
| news | 97 | 94 | 100 | 91 | 0.07 | 140ms |
| factors | 98 | 100 | 100 | 91 | 0.001 | 40ms |

- **CLS 修复确认**：home 0.001（round20 0.389）✅。
- **遗留**：home **TBT 770ms** 偏高，源于首屏多路实时行情/WS 订阅阻塞主线程，建议路由级懒加载 + 首屏骨架屏 + WS 节流。

---

## 9. 后端链路性能（Task 12）

- `/portfolio/timeline` 热 **7.2ms**（round20 2.9s → 修复 P0-1）✅。
- 其余数据链路热路径 **<80ms**（含 `/market/realtime/portfolio`、`/market/fund-flow/159338` 6.2ms）。
- ⚠️ `/market/stock-hot-rank`：A=3.5s、US=**5.2s** —— round20 US 慢路径**持续未解**，根因 US 热榜外部源（yfinance/akshare 美股）同步阻塞，需 `run_sync`+超时+缓存。
- harness `/health` 404 为 bug（见 §1），不影响真实健康。

---

## 10. 测试保护盲区分析（Task 13）

**为什么测试没拦住本轮暴露的问题？**

1. **恒绿断言**：单测多以「HTTP 200 / 非空」为通过条件，未断言**内容正确性**（如因子 valid_rate 阈值、KDJ 超买不应 BUY）。→ 假完成（AGENTS.md 反假完成机制）未被测试捕获。
2. **Mock 冒充实现**：因子/行情外部源在单测中被 mock，真实 `no_data` 退化路径（valid_rate 8.8%）无人测。
3. **非交易窗口缺口被静默**：HK/US 历史空数组在测试中当作「正常空」，未区分「真无数据」vs「数据源失败」。
4. **LLM 超时降级未覆盖**：check 424 的 18s 超时回退仅在生产偶发，单测未模拟 LLM 超时后的规则分支质量。
5. **性能无硬门禁**：timeline 曾 2.9s、US 热榜 5.2s，性能为软门禁，测试不阻断。
6. **阈值常量未契约化**：`confidence=0.7`、KDJ 阈值 J>100/K>85 散落代码，无契约/单测约束。

**修复方案（测试侧，不实施）**：
- 新增负向断言用例：全兜底时不得报「正常」；超买 KDJ 不得 BUY；valid_rate<阈值时标记 degraded。
- 引入「真实调用点」grep 门禁（CI 中 `rg` 确认新端点有前端/路由引用，否则标 dead）。
- 性能基线写入 `scripts/verify_perf.py` 软门禁，超阈登记「已知性能债」。
- LLM 超时注入测试，验证规则回退报告结构完整。

---

## 11. 冗余代码（Task 14）

`grep` 标记统计（backend/app）：

| 文件 | 标记数 | 备注 |
|---|---|---|
| `engine/allocation_engine.py` | 6 | TODO/FIXME 集中于层预算边界 |
| `routers/market.py` | 6 | 含 P0-4 watchlist 缓存 TODO |
| `tasks/task_manager.py` | 1 | — |
| `factors/factor_registry.py` | 1 | — |
| `engine/rationale.py` | 1 | — |

- 未发现**死端点/死组件**（无 `设计了不被调用` 的路由；前端组件均有引用）。
- 主要为**遗留 TODO 注释**与未实现的护栏（如 KDJ K>85 阈值、因子 clip），与 §3/§5 未修复项重叠——建议并入对应修复任务清理，而非独立删。

---

## 12. 汇总结论 + 优化/修复方案（设计级，待实施）

**P0（性能/正确性硬伤）**
1. US 热榜 `/market/stock-hot-rank?market=US` 5.2s → `run_sync`+超时+缓存。
2. 因子 valid_rate 8.8% 退化 → 取数重试/超时 + 输出 `clip(-1,1)` + degraded 显式标注。
3. 预热 19.4s 串行阻塞 → urllib/feedparser 线程化 + `gather` 并发 + 单源 8s 熔断。

**P1（策略正确性问题）**
4. P1-3 超买误判：KDJ 阈值收紧（J>100 **且** K>85 才判超买，超买不 BUY）。
5. D9/P1-8 `confidence` 动态化：随信号强度/数据质量/因子 valid_rate 调整，写入契约。
6. P1-7 强势板块注入 LLM 报告（医疗 +5.39% 等）。

**P2（健壮性）**
7. home TBT 770ms → 首屏懒加载 + 骨架屏 + WS 节流。
8. 激进现金 >20% 强约束（当前仅预警）。
9. 冗余 TODO 清理并入上述任务。

**P1（组合设计质量 — design 534 @2026-08-13 19:19 实证）**
> 以下基于最新设计 **design_id=534**（DB `created_at` 2026-08-13 11:19:51 UTC = 北京 19:19，用户实际查看版本）。该设计 `report_quality=partial`、`report_generated_at=None`，LLM 叙述层超时未生成（同策略检查 424 的 18s ReadTimeout），`design_text` 仅引擎渲染方案表。标的数量取自 design_text 对比表与 `strategies_json` 实算，一致。

10. **平衡型核心 67% 高 beta 成长**：核心层（0.30）= 沪深300(0.05)+中证A500(0.05)+创业板(0.1001)+科创50(0.0999)，创业板+科创50 占核心 **67%**。`allocation_engine` 把创业板/科创50 当宽基核心按因子分选入 core，**核心层无 beta/波动率上限** → 平衡型实为成长倾斜组合。修复：核心层加 beta/波动率上限，平衡型不得 2/3 压在高 beta 成长。

11. **卫星数量倒挂（选择 bug）**：卫星数 防御 2 / 平衡 6 / 进攻 2 —— 进攻型卫星反而最少，与风险档次反向。修复：卫星数量/广度随 `risk_profile` **单调递增**（防御≤平衡≤进攻，建议 2 / 4–6 / 5–7），解开进攻型卫星卡 2 的上限。

12. **标的数量倒挂**：总标的数 防御 10 / 平衡 13 / 进攻 **8** —— 进攻型比防御型还少。根因同 #11（卫星卡 2）+ 进攻型核心仅 3 只。修复：核心+卫星选择随风险档次放大，保证 **进攻型标的数 ≥ 防御型**。

13. **进攻型层结构过保守**：进攻型 防御层 19%（30年国债 5.1%+黄金 5.1%+10年地债 8.7%）+ 现金 25% = **44% 非权益压舱**，对"进攻"方案偏保守。修复：进攻型防御层压到最低（仅黄金 ~5%）、现金 <10%，权重让给核心+卫星。

14. **LLM 报告超时降级无提示**：design 534 `report_quality=partial` 但前端静默只显方案表，用户易误以为"报告只有方案内容"。修复：前端对 `report_quality=partial` / `generated_at=None` 明确标注「分析叙述缺失 / LLM 降级」，而非静默；后端可补持久化降级原因字段。

**验证窗口要求**：US/HK 历史、热点板块、因子矩阵需在**交易日 9:30–11:30/13:00–15:00 + 真实环境**复测，非窗口结果打标「待交易时段复测」。

---

## 13. 多轮 Review 记录

- **R1（自审）**：补预热热点 call-path 与文件:行；修正 US 历史「500 条」早前误报（本轮直测为空，归因为非交易窗口）；将「测试盲区」从清单提升为独立 §10。
- **R2（对照 round20 契约）**：确认 P0-1/P0-3/CLS 实测达标，P1-3/P1-7/D9 仍为开放项，未在 round20 实施清单中闭环。
- **待实施前最后核对**：所有「已修复」结论均来自实跑响应或源码直读，非测试绿推断（符合反假完成机制）。

---

## 14. 容器回收（Task 15）

诊断完成，按用户要求回收容器进程：

```bash
docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod down
# 或仅停容器：docker stop etf_surge-backend-1 etf_surge-frontend-1 etf_surge-redis-1
# 可选清理：docker container prune -f
```

> 注：本轮**未做代码改动**（仅文档 + 诊断产物），`git status` 应无源码变更；新构建镜像已落地，旧镜像已回收。
