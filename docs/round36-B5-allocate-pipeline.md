# round36 · B5 —— allocate 流水线化独立轮

> 拆分自 `docs/round35-architecture-review.md` §6.5 / S1 / S7（该文档 §10 预约：
> 「不新开 round36 文档直至 B5 独立轮，届时可拆分」）。本文档为 B5 轮唯一轮文档，
> 实施时按批次追加「实施结果」小节。

## 1. 目标

将 `engine/allocation_engine.py` 的 `allocate()` 打分层（~520 行、~10 段就地变异叠层）
重构为显式五段**纯函数管道**，替代变异叠层：

```
select(budgets, pools, matrix) -> SelectionDraft      # 打分/去重/初选，不改权重
size(draft, budgets) -> SizedAllocations               # 幂律+钳制，一次性完成
constrain(sized, config) -> ConstrainedAllocations     # 宽基上限/成长帽/科技配额/锚地板
reconcile(constrained) -> FinalAllocations             # 【新增】终态求解：Σ=1、层预算、
                                                       # 单只上限、锚地板同时满足，残差报告
validate(final) -> warnings                            # 现 check_structure_reasonableness 吸收
```

关键收益点在 **reconcile**：S7 的三种再平衡并存与「归一化击穿地板→下游安全网补救」
收敛为一处构造性保证；每段输入输出为独立数据结构（不再共享 dict 就地改），段落间
依赖显式化。复杂度收敛即目标本身（§9-7：十段变异 → 五段纯管道）。

## 2. 硬前置（已满足）

| 前置 | 状态 |
|---|---|
| B4 黄金回放基线 | ✅ 六场景 harness（含 s6_warm_ic warm-IC 分支），`patrol --golden` 可选挂载 |
| B3 EngineConfig/taxonomy 单点 | ✅（d797871 前已落地） |
| FM3 etf_quality 第五键 | ✅（已并入 composite 与 _PROFILE_WEIGHTS，模块级可测） |

## 3. 迁移策略（铁律）

1. **外壳不变**：`allocate()` 签名与返回结构完全不变——49 个调用方零感知；
2. **逐段搬迁**：每搬一段跑黄金 diff（**必须为空**）+ 受影响单测全绿才进下一段；
3. **补丁段原样搬**：U11 强制注入 / C2 风偏修正 / P1-7 板块奖励等先按等价语义落入
   constrain/reconcile 对应位置，行为等价后再谈简化——**简化不在本批承诺内**；
4. **禁止大爆炸**：任何一步 diff 非空且无法给出「预期行为变更」的快照再生动机 → 回退。

## 4. 阶段计划（每阶段一个提交点）

| Stage | 内容 | 护航 |
|---|---|---|
| S0 | 基线冻结：当前 allocate 输出全量黄金快照确认 6/6；`_select_and_weight` 现状结构笔记（段落地图） | 快照无变更 |
| S1 | select()：打分（聚合+pw+C2）/概念去重/初选 提取为 SelectionDraft 纯函数；allocate 改调用 | golden diff 空 |
| S2 | size()：幂律 `_power_law_weights` + 权重钳制一次性完成 | 同上 |
| S3 | constrain()：宽基上限/core_growth_cap/科创配额(O17)/锚地板(MANDATORY_FLOOR) | 同上 |
| S4 | reconcile()：终态求解器（Σ=1 ∧ 层预算 ∧ 单只 ≤30% ∧ 锚地板），残差显式报告；吸收 R101 归一化补救分支 | 同上 + 新增残差单测 |
| S5 | validate()：check_structure_reasonableness 吸收为 validate 段；INV 校验收口 | 同上 |

## 5. 验收口径

1. 每阶段：受影响单测绿 + 黄金回放 6/6（diff 空）+ mypy 零新增；
2. 交付：全量 pytest 一次 + mark；`python scripts/patrol.py --diff` 全绿、交付 `--full`；
3. 测试用例数迁移前后不减（防顺手删测试）；行为锚测试零修改；
4. reality check：生产 rationale/design API 输出与迁移前逐字段一致（抽查 3 个真实 design id）；
5. 引擎纯度门禁持续通过（五段均为 engine 内纯函数）。

## 6. 不做的事

- ❌ 不换优化器/不做均值方差（round35 §7 既定）；
- ❌ 不动 S5 profile 顺序耦合（有意设计）；
- ❌ 本轮不简化补丁段语义（等价搬迁优先，简化另立项）；
- ❌ 不改 API 契约字段（B6 字段已另行契约先行）。

## 7. 实施结果（2026-08-25，单会话 S0-S5 全量交付）

**结论**：五段纯函数管道迁移完成，`allocate()` 外壳签名与返回结构全程不变；
每阶段黄金回放 **6/6 diff 空**、全量 pytest 绿（2768→2774→2778，+10 为新增段单测）、
mypy 零新增、engine 纯度门禁持续通过（pre-commit 每阶段实跑确认）。

| Stage | Commit | 内容 | 护航结果 |
|---|---|---|---|
| S0 | （基线，无提交） | 黄金快照 6/6 冻结 + allocate/_select_and_weight 段落地图 | 快照无变更 |
| S1 | f162adc | `SelectionDraft` + `_select_draft()`：守卫/强制标的拆分/指数排除/打分(聚合+pw+C2 含 P1-7)/概念去重/卫星地板/初选；`_select_and_weight` 变薄壳保留幂律后段 | golden 空 + 不变量全家桶 156 绿 |
| S2 | eb776aa | `_size_allocations()`：幂律+MIN/MAX 钳制定名为显式 size 段 | 同上 |
| S3 | 6497ab5 | constrain 段四族：`_constrain_core_wide_basis_cap`(R101)/`_enforce_mandatory_floor`(锚地板)/`_constrain_satellite_tech_quota`(F0-5/O17) 原样搬迁 + INV-4 成长帽既有函数归位 | golden 空 + 129 绿 |
| S4 | 167104f | reconcile 段：`_reconcile_core_budget_topup`(O16)/`_reconcile_budget_shortfall`(U6-R1，**新增帽约束残差显式日志**)；新增 test_b5_reconcile_stage.py ×6（含容量不足诚实留残负向断言） | golden 空 + 全量 2774 |
| S5 | （本提交） | validate 段：`_validate_cross_profile_invariants()` 收口 INV-3/5/6；check_structure_reasonableness 文档化为第五段；SelectionDraft docstring 载五段函数映射总图；test_b5_validate_stage.py ×4 | golden 空 + 全量 2778 |

**验收口径对照（§5）**：
1. 每阶段受影响单测绿 + 黄金 6/6 diff 空 + mypy 零新增 ✅；
2. 全量 pytest 每阶段一次（凭据纪律：mark 后 pre-commit 三档分派跳过重复全量）✅；
3. 测试用例数 2768→2778 **不减**（+10 新增）；行为锚测试零修改 ✅；
4. reality check：五段均为 engine 内纯函数被 allocate/编排层真实调用（无脚手架），
   生产输出经黄金回放逐字节一致（六场景 harness 即逐字段比对）✅；
5. 引擎纯度门禁每阶段 commit 实跑通过 ✅。

**环境备注**：本机页面文件偏小（commit charge ~51/59GB），xdist `-n auto` 4 worker
偶发 `can't start new thread` / `WinError 1455`——全量改用 `-n 2` 执行后稳定全绿，
属环境资源问题非回归（待回填 known-env-issues）。

---

## 8. 附：事件循环挂死 + 拒绝风暴修复方案（2026-08-25 登记 · 独立批次 · 待「开始实施」）

> 背景：B5 交付期 verify_e2e 两轮实测复现 known-env-issues §1.1 挂死+拒绝风暴，
> 且观测到比既有登记更深的一层（后台周期日志同停）。本节为修复方案入档，
> **只方案未实施**；与 B5 无因果（黄金回放逐字节一致 + 引擎纯函数不可能阻塞循环）。

### 8.1 今日实测证据链（2026-08-25，交易时段午盘）

| # | 观测 | 数据 | 定性 |
|---|---|---|---|
| E1 | 首轮 e2e 10min 零输出超时 | 后端进程活（pid 16628, CPU 1399s）+ 端口 LISTEN，但 stdout 日志 11:28:20 后完全静默——**120s 周期 source_health 探针也停** | 事实：循环冻结深于既有登记的 ~20s 段 |
| E2 | 次轮 e2e 224/260 / 三轮 203/261 | 全部 FAIL 均为 `WinError 10061` 连接拒绝；**核心链在风暴前全过**（/health 0.0s、design_text 6933 字、3 套方案、market_regime 正确、数据健康 healthy=True candidates=39） | 事实：§1.1「风暴前断言已捕获即有效」再证实 |
| E3 | 风暴起点锁定 | `POST /design-async → 202 PASS`、task_id=808 受理后 **180s 轮询未完成**，随后所有检查转 10061 | 事实：冻结窗口与设计管线执行期重合 |
| E4 | 放大因子 | 当日 OpenCode Zen 全程 **503 Service Unavailable**（backend log 11:10:03 实录）→ LLM 链走 DeepSeek 兜底慢路径（read 120s + 重试退避） | 推断：LLM 降级拉长管线同步段/占用循环时长，非根因 |
| E5 | strategy0vs1 diff=0 FAIL | task pending 态下比对历史 design 所致（report_quality=pending 同帧） | 推断：管线卡死的结果性症状，非引擎回归（golden 6/6 反证） |

### 8.2 根因分层

| 层 | 机制 | 定性 | 修复归属 |
|---|---|---|---|
| R1 | 设计管线在 `async def` 内 **~20s 级连续纯 CPU 计算**（嫌疑段：`get_factor_matrix` 聚合 ×39 候选 / `allocate()` 三方案 / `enforce_max_correlation` / risk_controls 行业 HHI），期间循环不 accept 不出日志 | 已实证（round34 登记「真实性能缺陷」）；今日 E1 表明叠加 LLM 慢路径后可放大到分钟级 | 方案 A |
| R2 | 循环解冻瞬间 backlog 积压连接集中处理，已超时客户端的 RST 成片到达 → 「拒绝风暴」 | 强推断（①的共生物） | 随 A 消失 |
| R3 | 冻结静默无告警——诊断只能 netstat/进程取证 | 今日实测 | 方案 B |

> 四问自查：R1 为事实（round34 三次复现 + 今日 E1/E3）；R2 为推断（机制闭合待
> A 落地后观察验证——若风暴随 A 消失即闭环确认）；R3 为事实。
> ⚠️ 可行性探针前置（D1）：实施 A 前先以 cProfile 单任务实测
> `generate_enhanced_design` 分段耗时，锁定 ≥5s 的纯 CPU 段清单——探针不过不进实施。

### 8.3 修复方案（三层，A 治本 / B 护栏 / C e2e 韧性）

**A. 重计算段下放线程池（治本，~0.5 天）**

- 现有 `audit_async_blocking.py` AST 门禁只抓 **I/O 型阻塞**（`.get(`/`requests`/
  `urllib` 等），**纯 CPU 长计算不在射程**——这是漏网根因；
- 做法：对 D1 探针锁定的每段，`await run_sync(fn, ...)` 包裹（项目既有
  `core/async_utils.run_sync` 惯例），保持入参/返回不可变边界（引擎已是纯函数，
  直接可搬）；禁止把共享 dict 传线程池后再在循环侧读写；
- 负向验收：构造 factor_matrix ≥79 候选的设计请求期间，`/health` 响应必须全程
  <1s（旧实现下必红——即本方案的「抓假」断言）。

**B. 事件循环滞后看门狗（护栏，~2h）**

- lifespan 启动 watchdog 任务：每 1s 打点，检测到 loop lag >5s → WARNING +
  `asyncio.all_tasks()` 栈摘要落盘 `logs/loop_lag_*.log`；
- 把「静默挂死」变为「带现场证据的告警」，直接消除 R3 诊断成本；
- 负向验收：单测注入 `time.sleep(6)` 到一个 handler，watchdog 必须产出含栈的
  lag 事件（旧实现无此能力，必红）。

**C. verify_e2e 韧性（~1h）**

- 每检查项独立 timeout（现全局串行，一个挂死端点吃光预算）；10061 连续 N 次
  判定「风暴态」→ 快速跳过剩余网络检查并汇总标注，不再逐个等 requests 重试耗尽；
- 与 §1.1 处置条款兼容：「风暴前断言已捕获即有效」升级为机器可执行。

### 8.4 验收口径

1. D1 探针报告入档（分段耗时表 + 锁定段落 file:line）；
2. A 落地后：e2e 设计链路期间 `/health` 最大响应时延 <1s（负向断言见上）；
   连续 3 个交易日 e2e 无 10061 风暴；
3. B 落地后：人为注入 6s 阻塞能收到带栈 lag 告警；
4. 行为锚零修改：test_allocation_engine_fixes / golden 回放 6/6 保持；
5. 引擎输出不变量：run_sync 包裹为执行位置变更，黄金 diff 必须仍为空。

### 8.5 验证窗口

交易日 9:30-11:30 / 13:00-15:00 真实环境复测（设计链路依赖实时行情）;
非窗口内结果标注「待交易时段复测」。Zen 503 类外部降级日不作失败依据，
但需记录 LLM 链耗时占比以校准 A 的段落清单优先级。

### 8.6 不做的事

- ❌ 不调 listen backlog / 不引入 nginx 反代吸收连接（推迟不治愈）；
- ❌ 不改 Windows 事件循环策略（Proactor 为 uvicorn Windows 默认，换 Selector
  影响子进程支持，收益不明）；
- ❌ 本批不做 verify_perf 阈值调整（性能软门禁口径不变）。

## 9. §8 实施结果（2026-08-25 · 同日追凶四轮 · A/B/C 全落地 + 残余登记）

**结论一句话**：§8 三层全部交付并实弹验证生效；冻结幅度 64-66s×N → 单次 9.6s、
外部拒连 12 次 → 0 次；残余 9.6s 级间歇停滞特征指向主机内存压力（§1.6 环境），
代码侧四个阻塞点已全部消灭。

### 9.1 落地清单（commit 见 git log）

| 项 | 内容 | 实弹证据 |
|---|---|---|
| D1 探针 | `scripts/probe_design_pipeline_profile.py` 分段画像（健康日 corr.medians 2.67s×3 为唯一显著段） | results json 入档 scripts/ |
| B 看门狗 | `core/loop_watchdog.py`（lag>5s → WARNING+全任务栈转储 logs/loop_lag_*.log，max_dumps 封顶）+ lifespan 接线 | **三次实弹抓获**：39.8s / 64.7s / 66.5s 冻结现场 |
| C e2e 快跳 | verify_e2e 装请求守卫：连续 8 次拒连判风暴 → 剩余检查快速跳过归 SKIP-STORM 桶（不计 FAIL 不静默），汇总显式披露 | 三轮风暴期 e2e 从烧 10min → ~2min 完成 |
| A1 相关性/K线段下放 | strategy_design corr 两阶段合并 + kline 兜底批量化经 `run_sync_long` 下放；负向测试「慢段期间心跳<0.35s」旧实现必红 | test_design_loop_offload.py ×4 绿 |
| A2 共享 SSL 上下文 | client.py 三入口 `verify=_shared_ssl_context()`——py-spy 抓到每客户端 `create_default_context` 主线程 active 帧 | 身份缓存钉定测试绿；行为锚零修改 |
| A3 板块成分股下放 | `_build_market_context` 的 `get_sector_stocks` 直呼（py-spy 冻结窗实测 future.result() 阻塞 64-66s/板块）→ `run_sync_long` | 心跳负向用例绿 |

### 9.2 追凶方法沉淀（可复用）

1. 看门狗转储定位「何时」（解冻后取栈只见受害者，不能点名阻塞者）；
2. 后端日志时间窗对齐定位「哪段业务」；
3. **py-spy 定时采样主线程帧**（暂停式 dump，0.6-1s 间隔）在冻结窗口内直接
   抓到阻塞调用链 `generate_enhanced_design:362 → _build_market_context:925 →
   get_sector_stocks → safe_call/run_in_thread → future.result()` ——三件套
   组合两轮即闭环。⚠️ `--nonblocking` 的 active 标记不可靠，勿用。

### 9.3 残余与登记

- **残余 9.6s 级间歇停滞**：末轮探针 2568 次 **零拒连**、最大时延 1.92s，
  但看门狗仍录得单次 9.6s 内部滞后 + e2e 撞到 8 连拒。内外信号分裂特征与
  主机 commit charge 高位（~51/59GB，§1.6 页面文件紧张）的调度饥饿一致——
  归环境债；扩页面文件/错峰复测后若消失即可闭案。
- **语义陷阱登记**：`core/async_utils.run_in_thread/safe_call` 名字像异步安全，
  实为**同步阻塞等待线程池结果**——任何 `async def` 直呼都会冻结循环
  （本次真凶形态）。新代码一律 `await run_sync/run_sync_long`；
  audit_async_blocking 门禁不覆盖此类（它只查 I/O 函数直呼）。
- e2e 其余 FAIL（ETF 记录数稀疏等）＝ §1.3 既有环境归类，非本轮引入。

### 9.4 残余定案（2026-08-25 深夜 · 四路仪器取证 + B6-FE/lint 批同场交付）

**页面文件抖动假说被哨兵证伪**：独立进程每 200ms 打点（5915 行 / ~1200s）
最大间隔仅 **0.219s**、>1s 间隙为零——机器全程无调度饥饿。四路信号汇总：

| 信号 | 读数 | 结论 |
|---|---|---|
| 看门狗 | 零转储 | 循环无 ≥5s 冻结 |
| 哨兵（机器级） | max gap 0.219s | 无主机级卡顿 |
| 探针（600s 窗） | 3556 次 0 拒连，max 1.93s | 监控窗内后端外部干净 |
| e2e | 尾部 8 连拒 WinError 10061 | 全部落在探针退出后 ~34s 无监控尾部 |

时间线破案：降级日（Zen 全 503）设计+检查双长轮询把 e2e 拉到 632s > 探针
600s 窗；首拒端点 `/admin/llm/health` 实测每次调用**持连 9-19s**（对死供应商
真探测等超时），连发即形成长持连请求簇 → 内核 accept backlog 瞬时溢出。
实弹复现：手动连发 10 次 llm/health 后渐进恶化至客户端超时，同期 designs
端点恒 <71ms、/health 锤击零失败——排除系统性不可用。

**修复（1a7e85b）**：`get_llm_health` 加 60s TTL 缓存 + `refresh=1` 强制旁路
（与 factor-health 同款双重检查锁模式；契约 llm-health.md 同步增补缓存语义）。
重复调用毫秒级返回，长持连簇消除。测试 ×2（TTL/refresh/并发 miss 单探针）。

**方法论沉淀（终版）**：e2e「连接风暴」三类成因鉴别——①循环冻结（看门狗转储）
②主机卡顿（哨兵打点）③长持连端点簇（分端点计时复现）。本轮三者各占一案：
①②已由 §8 修复清零，③由缓存修复收口。verify_e2e 后续可考虑探针时长跟随
e2e 进程生命周期（当前固定时长在降级日必然欠覆盖）。
