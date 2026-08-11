# Round12 合并实施计划（round10 容器复诊断 47 项 + round11 代码冗余 29 项 = 76 项）

> **性质**：将 round10-container-rediagnosis.md（47 项）与 round11-code-redundancy.md（29 项，P2 已决策定稿）合并为**可执行分批实施计划**。本计划**仅编排，不实施**。
> **日期**：2026-08-08 · **基线**：pytest 1112 passed（backend/pytest_full.log，2026-08-02 固化）/ vitest 390 / verify_e2e 口径（数据源类 FAIL 属环境）。
> **依赖文档**：`docs/round10-container-rediagnosis.md`、`docs/round11-code-redundancy.md`（细项与 file:line 以原文档为准，本文档只做编排与裁决）。

---

## 0. 总原则

1. **顺序**：先行稳 → 后行为。
   - 第 1 批：round11 P0（纯删除，零行为风险）——先清冗余，缩小后续改动面；
   - 第 2 批：round10 P0（数据完整性/功能阻断）——核心正确性问题；
   - 第 3 批：round10 P1 + round11 P1（数据源补全 + 低风险抽取合并，两轮无重叠可并行）；
   - 第 4 批：round10 P2 + round11 P2（质量体验 + 行为变更，P2 已定稿）；
   - 第 5 批：round10 P3 + round11 P3（门禁防再犯，**应在 P0/P1 各自落地后立即接**，见 §3 依赖）。
2. **重叠裁决**：round11 实测修正的结论**优先于** round10 旧结论（round11 §4.1 已逐项核实）；方向冲突以**先决策的定稿**为准（见 §1）。
3. **验收门槛**：每批跑 `pytest`（全量，基线重跑后以新数为准）+ `npm run build` + `verify_e2e.py`（数据源类 FAIL 按 round10 §9 口径豁免）+ 前端 vitest。
4. **每步独立 commit**，可回退。

---

## 1. 重叠项裁决（先看这里）

| round10 项 | round11 项 | 裁决 | 理由 |
|---|---|---|---|
| P3-J 测试冗余治理 | P1-8 + P3-6（测试合并 226→~199） | **round10 P3-J superseded 由 round11 承接**（保留其『抽 FakeAsyncSession/FakeHub』目标） | round11 已实测修正 P3-J 的 3 处错误（status==200 空转不成立、design_quality_gate 保留、verify_e2e 次数修正） |
| P0-A AI 投顾数据槽位错配 | P0-3 删 `/llm-advice` **非 stream 版** | ⚠️ **P0-A 对象错误——对象待重診（stream 或非 stream）** | round10 P0-A 引用 analysis.py:368-373（非 stream 端点，L356 TODO 未接入前端）；但**用户复现证据（round10 §9.2#7 实测 POST /llm-advice 12.9s/554 字/「暂无实时指数数据」）来自非 stream**，与 stream 措辞「（暂无数据）」不符——两候选对象均需排查，不能只转 stream（详见 §3 红线 2） |
| P3-A + P3-G 门禁（stream 内容契约） | （round11 无对应项） | ⚠️ **门禁对象随 P0-3 删非 stream + P0-A 重診转向而改**：P3-A 改断言 `/llm-advice/stream` SSE 输出含真实指数关键词；P3-G 改「stream 注入 context key ⊆ `_build_advice_stream_prompt` 消费 key」契约 | 非 stream 删除后 P3-A/G 不能对着不存在端点写断言；round11 无等价 stream 内容门禁，需批 5 补建 |
| P2-H 双缓存路径统一（建议 backend/data） | P2-5 缓存统一根 data/（**已定稿**） | **P2-H 以 P2-5 为准**（superseded） | P2-5 用户已决策根 data/；P2-H 方向相反（backend/data/） |
| P1-J ③ benchmark_close 映射扩全 | P2-7 scaffold 保留函数 | 不冲突 | P1-J 补数据源、P2-7 保留计算函数，互补 |

---

## 2. 分批方案表

### 批次 1：round11 P0 纯删除（零行为 · 先做减法）

> 前置依赖：无（但 P0-1 内有内部依赖顺序，见 round11 §8.1）。

| 项 | 关键点 | 备注 |
|---|---|---|
| round11 P0-1 | 后端 12 死文件联动删除（**macro_state 直删；design_quality 保留**；ttj/text_pipeline/worker_registry+b 连带删测试；benchmark/market_router/adapter 连带改测试；**先删 verify 段 + test 再删 snapshot_service**） | 依赖顺序已注明，见原文档 |
| round11 P0-2 | 前端 14 死组件/composables（8 直删 + 6 连带改测试） | — |
| round11 P0-3 | 废弃端点：`/llm-report`、`/llm-advice`（**非 stream**）、`/llm-news-analysis`、`/portfolio-review`（非 stream）、`/search/stocks`；**保留 `/indices/meta`** | ⚠️ **联动 verify_e2e**：删非 stream 前先删 verify_e2e.py:756-757 的 `POST /llm-report`/`POST /llm-advice` 检查段（否则 404 不在白名单 → section_analysis 必红）；round11 P0-3 原案漏此联动。**例外**：若批 1 开工前裁定保留 `/llm-advice` 非流端点（红线 2①），则仅删其余 4 端点、暂缓删 `/llm-advice` |
| round11 P0-4 | 空测试 3 + 死 import 4 + 越权测试 | — |
| round11 P0-5 | 脚本/diag 归档 + 空 DB 壳清理 | — |
| round11 P0-6 | 契约归档（agents.md 表段更新 + 2 契约 files 归档） | 依赖批 2 的 P0-A 重診结果（agents.md 表端点与实现对齐）；非依赖 P0-1 |

### 批 2：round10 P0 数据完整性/功能阻断（6 项）

> 前置依赖：批 1（死端点/缓存路径清理后，P0 各端点行为更可测）。**P0-A 需先重诊（见 §3 红线）再实施**。

| # | 关键点 |
|---|---|
| P0-A | ⚠️ **对象待重診（两候选，详见 §3 红线 2）**：① 先回查用户实际访问版本（非 stream 证据 vs stream 前端）——**此项在批 1 开工前完成**（影响 P0-3 端点去留）；② 若确认走 stream：验证 `/llm-advice/stream` 是否真存在「暂无数据」回退，在则改 stream `build_full_context` 注入链（3 市场 indices/sectors 非空才输出）；③ 若确认用户用的是非 stream 且裁定保留该端点（P0-3 暂缓删）：P0-A 按原案修非 stream `generate_advice` 槽位；④ 关闭条件：stream 实探含真实指数值 → 用户版本/缓存问题，非代码 bug |
| P0-B | strategy_check report_text 标题吃 fallback_count/ratio |
| P0-C | factor_registry K线采集多级降级 + cache 兜底（10/10 全空 → 明示数据源不可用） |
| P0-D | 首页 perf 52 / CLS 0.389：容器 aspect-ratio + 骨架屏同构 |
| P0-E | watchlist enrich 超时降级单标的轻量快照 + 前端"行情加载中" |
| P0-F | `_llm_timeout_for` 数据分级口径（技术因子覆盖率 ≥60%）→ partial 30s |

### 批 3：round10 P1 + round11 P1（数据补全 + 抽取合并）

> 前置：批 2（P0-C 的降级链保证 P1 数据源修复基于稳定底座）；round11 P1-8 依赖批 1 清理后的文件基线。

**round10 P1（10 项）**：P1-A factor-health 缓存并发；P1-B 表格时间戳；P1-C 负 IC 降权；P1-D 卫星负分不给权；P1-E watchlist「—」；P1-F L1 分级校准；P1-G industry 兜底（instruments+Classifier）；P1-H 防御型披露；P1-I provider_timeout 30-40s 参数化（与 P0-F 配套）；P1-J warn 通道细分 + benchmark 映射扩；shares_change 降级评估。

**round11 P1（10 项）**：P1-1 `_cached×4` 统一；P1-2 `_safe×5` 统一；P1-3 `_sync_fetch` 参数化；P1-4 `_ws_loop` 抽取；P1-5 超时/TTL/映射常量归拢（**先定 etf_list 300 vs 3600**）；P1-6 format.js；P1-7 样式统一；P1-8 测试 6+1 合并（226→~199）；P1-9 verify_e2e 去重（2278→~1970）；P1-10 契约合并。

### 批 4：round10 P2 + round11 P2（质量/体验 + 行为）——P2 已定稿

**round10 P2（17 项）**：P2-A LLM 短缓存；P2-B nginx /health；P2-C 非 hold 差异化；P2-D 报告时间戳；P2-E 容器弱源 QA；P2-F LLM 报告短缓存；P2-G 行情新鲜度（非交易日标注）；P2-H superseded；P2-I 评分渲染不可用而非 50；P2-J watchlist 添加 ≤3s；P2-K 板块阈值 ±20%+主源换东财；P2-L 添加框联动+placeholder；P2-M 港股板块 f100 归「其他」；P2-N 弹窗 assetType；P2-O 港股 ETF 识别；P2-P 组合页加载态；P2-Q 美股搜索 market 过滤；P2-R 美股热点；P2-S 美股宏观；P2-T 板块模式禁用。

**round11 P2（7 项，定稿）**：P2-1 FactorICView/FactorModelView 合并（删路由，getIC 并入）；P2-2 warmup store 单例；P2-3 真实 wsConnected；P2-4 useTaskWS；P2-5 根 data 端口；P2-6 hk SourceRegistry；P2-7 scaffold 注释清（不删函数）。

### 批 5：round10 P3 + round11 P3（门禁防再犯）

> 前置：**按门禁细分**——P3-A/B/C（批 2 修复后立即接，防回退）；P3-E/F/G（批 3 后）；P3-D（Lighthouse 进 CI，需批 2 P0-D 落地才有拦截对象）；P3-H/I（批 4 P0-F/P1-I/P2-G 落地后）；round11 P3-1/AST（批 3 合并后跑，减少存量噪音）；P3-5 check_routes（P0-6 契约归档后）。

**round10 P3（11 项）**：P3-A llm-advice 内容门禁（**→ 改 stream 输出断言**，见裁决表）；P3-B 策略一致断言；P3-C watchlist realtime；P3-D Lighthouse 进 CI；P3-E 负 IC 下架；P3-F 容器弱源集测；P3-G 契约（**改 stream context key**，裁决表）；P3-H LLM 超时分级；P3-I 精度+新鲜度；P3-J superseded→round11；P3-K mock 基线 857→1112 修正。

**round11 P3（6 项）**：P3-1 AST 门禁；P3-2 purgeCSS；P3-3 .env.example 同步；P3-4 diag/ gitignore；P3-5 check_routes 接 CI；P3-6 测试冗余基线（~199）。

---

## 3. 依赖顺序红线

1. **round11 P0-1（snapshot_service 删除）**：必须先删 verify_e2e 的 section_snapshot_health + test_snapshot_service.py，再删 service——反了会挂 verify_e2e。
2. **round10 P0-A 对象待重診（两候选）**：用户复现证据（round10 §9.2#7：POST `/llm-advice` 非 stream → 12.9s/554 字/「暂无实时指数数据」）与前端**当前版本**（AiAdvisor.vue:53 only stream）不一致——**非 stream 与 stream 都需排查**：① 若用户用的是非 stream（旧前端/缓存/API 命令）→ P0-A 按原案修非 stream（**但 P0-3（批 1）默认删非 stream 端点——故端点去留裁定须前置到批 1 开工前**：若裁定保留非 stream，则 P0-3 暂缓删该端点、改仅删其余 4 端点；若裁定删除，则 P0-A 非流分支无从修，直接走 stream 分支）；② 若用户是 stream → 修 stream 注入链；③ 关闭条件：stream 实探输出含真实指数值 → 用户版本/缓存问题，非代码 bug；若仍「（暂无数据）」→ stream 注入缺数据，改 stream。**结论：P0-A 实施前必须先回查用户实际访问版本，不能预设对象；且本次回查应在批 1 开工前完成，否则影响 P0-3 端点去留**。
3. **round10 P3-J superseded**：合并 6 组的动作由 round11 P1-8 执行，避免重复改同一批文件（round 10 P3-J 若人手会与 P1-8 冲突）。
4. **round11 P1-8 需先等批 2 P0-C**：factor_registry 降级链改了后，测试文件中对 K线无数据的 mock 才统一；否则 P1-8 合并时 mock 口径不稳定。
5. **round10 P2-F（LLM 报告缓存）依赖 P1-I（provider_timeout）**：缓存命中后才能避免每次 60-120s；无 P1-I 时 P2-F 缓存未命中仍需等满超时。
6. **门禁先于「验收在 P0/P1 各自落地后立即接」**：P3-A/B/C 挂在 verify_e2e，需在 P0-A/B/C 后马上接，防回退；P3-D/E 依赖 P0-D/P1-C。

---

## 4. 需决策/待排查清单（实施中按此处理）

| # | 状态 | 内容 | 处理 |
|---|---|---|---|
| 1 | **待排查（红色）** | round10 P0-A 实际对象待重診——非 stream（用户复现证据：12.9s/554字/「暂无实时指数数据」）vs stream（前端当前版本，措辞「（暂无数据）」）两候选 | **此项为批 1 开工前第一道 gate**（影响 P0-3 端点去留）：回查用户实际访问版本（旧前端缓存/API 命令 vs 页面流式）；再容器内侦查 stream 链 build_full_context 三市场输出；关闭条件见 §3 红线 2 ③；P3-A/G 门禁随端点删除 + P0-A 重定而改 stream（裁决表） |
| 2 | **已决策** | round11 全部 P2（7 项定稿） | 按 §8.3 执行 |
| 3 | **已决策** | 执行顺序：round 先删 11 P0 → round10 P0 → P1 → P2 → P3 | 本计划 §2 |
| 4 | 待排查 | `etf_list` TTL 300 vs 3600（round11 P1-5 前置） | round11 实施时先测两个候选值对 watchlist 刷新延迟影响 |
| 5 | 待排查 | `_has_real_factor_values` 技术因子口径 60%（round10 P0-F） | 实施前用容器内真实 factor matrix 验 60% 是否过严（会不会误标部分数据为 partial） |
| 6 | 稍后 | round10 §11 低危措辞 5 项 | 实施到对应模块时顺手修 |
| 7 | 稍后 | pytest 基线重签 | 批 1 后重跑全量，基线 1112 → 新数（删测试后下降） |
| 8 | 待排查 | round10 P1-F（L1 分级）对象随 P0-A 重裁定：若 P0-A 走 stream，P1-F 在 stream 注入链调 L1；若走非 stream（不删端点），P1-F 在原链调 | 批 2 P0-A 结论确定后传导到批 3 P1-F（M3） |
| 9 | 前置 | round11 P2-1 实施前先列 FactorICView/FactorModelView 独有功能差异清单（round11 §9） | 批 4 P2-1 开工前完成差异清单 |

---

## 5. 每批验收断言（可执行 checklist）

> **通用门槛（每批必做，与下方批次断言并列）**：DoD = 测试绿 + 现实证真——每项改动按 `AGENTS.md`「反假完成机制」过 reality check：① 新端点/函数有真实调用点（非测试引用）；② 输出含真实数据路径值（非纯 fallback/mock/占位）；③ 内容断言（非仅 HTTP 200/非空）；④ 引用同步（rg 无旧名残留）；⑤ 前端四态（loading/空/错/慢）齐全。**全量测试绿但上述不过 ≠ 完成**。

**批 1**：`pytest` 删除相关测试后全绿（不删则红 → 回滚）；`rg` 验证 12 死文件引用为 0；`verify_e2e` 除数据源类 FAIL 全 PASS（design_quality_gate 仍在）——**注意 P0-3 删非 stream 端点时同步删验证该端点的 verify_e2e 段（756-757），否则 section_analysis 必红；若裁定保留 `/llm-advice` 非流端点（红线 2①），则 verify_e2e 段保留且仅删其余端点**。

**批 2**：filled 不再骤降（P0-C，stale 缓存 ≥上轮）；`_llm_timeout_for` 单测（仅静态 → 30s）；llm-advice stream 无「暂无数据」回退（若确认保留）；首页 perf ≥60 & 3 页 CLS <0.1（**统一 dev 容器环境重测，注明基线环境避免漂移**）；watchlist 实时全非 None。

**批 3**：pytest 全绿 + 文件数 226→~199；verify_e2e 行数 ↓；es 端点行为无回归（ws/hot/sector 走查）；**前端基线（批 1 P0-2 删 14 组件后）重跑 vitest 390**。

**批 4**：warmup 请求减半（P2-2）；导航栏连接真实；factor 页 active+IC 都在 ModelView；hk 板块熔断一致；美股搜索含 market 过滤 ≤500ms（P2-Q）+ 热度有数据（P2-R）。

**批 5**：verify_e2e 增 P3-A/B 断言后 AI/策略报告不 FAIL（**P3-A 为 stream 输出断言**）；新死代码 0 增长（本地 AST audit）；check_routes 有 CI 引用；diag 不被跟踪；`.gitignore` 覆盖 diag/；**P3-A/G 已改 stream 目标**（非 stream 端点已删，门禁不落空）。

---

## 6. 排期建议（4 个 commit 原子批次）

- **Commit A**：批 1 round11 P0（死代码+归档） → 重跑 pytest 新基线。
- **Commit B**：批 2 round10 P0（含 P0-A 红线排查完成）+ round10 P3-A/B/C 门禁。
- **Commit C**：批 3（P1×2）+ round10 P3-E/F/G 门禁。
- **Commit D**：批 4 P2×2 + 批 5 剩余门禁 + .env.example + AST 门禁。
- **Commit E**：契约归档最终核对（P0-6 + P1-10 收尾 + agents.md 一致性）。

> 每 Commit 含对应 round10/round11 文档引用，实施者在对应项勾选「已实施」回写。

---

## 7. 结论

76 项合并非简单累加——**关键裁决 5 处**：round10 P3-J、P2-H superseded（由 round11 承接）；round10 P0-A 对象**待重診**（非 stream 用户证据 vs stream 前端，红色待排查，§3 红线 2）；P3-A/G 门禁随端点删除**改 stream 断言**；P0-3 删非 stream **联动删 verify_e2e 检查段**。真实可执行批次 = 5 批（建议 4+1 commit）。**仅编排未实施**，随时可按批开做。

## 8. 实施回写记录（2026-08-09 全部落地）

> 按 §6 排期「实施者在对应项勾选『已实施』回写」——各批实际 commit 映射如下（全部已 push origin/main）：

| 批次 | 实际 commit | 落地内容 |
|---|---|---|
| 批 1（round11 P0 纯删除） | `7d09833` | 12 死文件 / 14 死组件 / 5 废弃端点 / 测试归档 / diag 归档 / agents.md stream 化 |
| 批 2（round10 P0 六项 + P3-A/B/C 门禁 + CLS） | `9c5971d` | AI 投顾槽位 / 报告标题诚实 / K 线 stale 兜底 / watchlist 缓存回填 / LLM 超时分级 / 门禁 |
| 批 3（round10 P1 + round11 P1） | `23eb072` `25e81d4` | factor-health 并发锁 / 负 IC 降权 / 卫星负分 / provider_timeout / 表格今日涨跌 / TTL 3600 / format.js |
| 批 4（round10 P2 + round11 P2） | `de120bb` `0e47586` `9e5039a` `5888a13` | US 搜索过滤 / 港股 f100 / assetType / 板块阈值 / 美股热点 / watchlist 超时 / useTaskWS / hk 熔断 |
| 批 5（round10 P3 + round11 P3 门禁） | `1589b3e` `8b63e29` `96dd2d8` `93f1f0d` `5c7dd4f` `5bd42c3` | pre-commit 短路 / P3-6 基线 / .env.example / check_routes CI / 死样式审计 / 容器弱源 |
| 追加（round12 收尾） | `616fd10` `6d0e9fa` `c5f8b3d` `d9e90a4` | 存量死代码清零 / LLM 报告短缓存 / EM 方案 A 评估回退 / §11 措辞 |

**收口核对（§7 结论 5 裁决 + §4 清单 9 项）**：9/9 闭环（P3-J/P2-H 由 round11 承接落地、P0-A 裁决 stream、P3-A/G 改 stream 断言、P0-3 联动 verify_e2e；P0-F 技术因子 ≥60% 口径、etf_list TTL 3600、pytest 基线重签 1554 passed 等全部落地）。

**遗留项（非本计划范围，另行排期）**：EM 根因方案 B（mootdx+bestip 主链，方案 A 容器实测无效已回退）；xdist 并行偶发竞态（未稳定复现）。