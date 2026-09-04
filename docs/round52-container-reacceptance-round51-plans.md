# round52 容器全链路诊断 — round51 方案 A-F 落地复验 + 回归扫描（2026-09-02 周二盘后）

> 本文档为 **round51 复验轮**（独立 round52 文档，不改写被诊断的 round51 文档）。
> 诊断对象：HEAD `56df5ed`（含 round51 方案 A-F 实施 `a9f704d` + 持仓重灌 `3fb66b1` + R169 科创板守卫 `56df5ed`，即 round51 诊断之后全部落地代码）。
> 验证环境：Docker Engine 29.7.2，prod profile + diag overlay（PROFILE_WARMUP=1 cProfile）。
> 验证窗口：2026-09-02 周二 16:24-17:05（**盘后**，日频数据已发布；盘中实时类标注「待交易时段复测」）。
> 容器 16:24:59 启动，16:25:39 warmup 完成（1618 items）；三容器 Up 全程无重启。
> 探针产物：`C:/Users/Public/etf_probe/probe20-33.out` + `openapi.json` + `build52.log`（诊断临时目录不入仓）。

---

## 0. 执行摘要

> **决策状态**：round51 方案 A-F 已于 `a9f704d` 全部实施。本轮 = 落地后容器复验，
> **全部 7 项修复实测生效**（R162/R163/R165/R166/R167/R168 + R164 语义修正）。
> 新发现 R170-R172（P2×1 + P3×2），无 P0/P1。环境项：构建期 apt 源故障（已打可逆补丁，见 §1）。

### 0.1 核心结论（一句话/项）

| # | 结论 | 状态 |
|---|---|---|
| 1 | **R162 现金悬空修复生效**：design 16（HEAD 代码 16:30 触发）三方案 total 全部 =1.0000，cash_row 与 1−non_cash 完全一致（GAP ±0.0000）；同库对照 design 15（旧代码产物）GAP +0.05 依旧 → 归因清晰指向 round51 方案 A+B（a9f704d） | ✅ 修复确认 |
| 2 | **R163 target_amount 脱节修复生效**：design 16 三方案 target_amount 全 consistent（无 +36% 形态残留） | ✅ 修复确认 |
| 3 | **R165 NAV Redis 自愈生效**：`/admin/lifespan-warmup` 报 `redis_available=true`（round51 为 false、3 周期 0 ok）；本轮 cycle 1 因 `pool_empty` 0 任务执行，但 redis 连接可用性判断已正确 | ✅ 修复确认 |
| 4 | **R167/方案D envelope 结构化生效**：日志出现 `[envelope] openrouter/nvidia/nemotron-3-ultra-550b-a55b:free: Upstream error from Nvidia: Service temporarily overloaded (code=502)`——带 provider/model 上下文的结构化错误，非裸 `'choices'` KeyError | ✅ 修复确认 |
| 5 | **R164 语义修正生效**：check 67 文案「LLM 分析超时（30s 未返回）」对应日志 `[strategy_check] LLM analysis interrupted after 30.0s (timed out or cancelled: CancelledError)`——为**真预算耗尽**（上游 502/429 重试链吃满 30s），非 envelope 伪装超时；文案与真因一致 | ✅ 修复确认 |
| 6 | **R166/方案E 口径隔离生效**：`/factors/active` 响应含 `zero_ratio_scope: "ic_batch"` + `zero_ratio_note`（明示「两口径不可互替」） | ✅ 修复确认 |
| 7 | **R168/方案F 金标补量生效**：`goldens/` 13(demo)+5(quotes)+46(round51-expansion)=64 条 ≥ v7 §5.5 P1 目标 50 | ✅ 修复确认 |
| 8 | **R169 科创板守卫生效**：`/market/realtime/588200` price=1.14（非 mootdx ×10 形态），change_pct=-1.72 与绕行源一致 | ✅ 修复确认 |
| 9 | **R140 持续生效**：design 16 三方案 layers ≤ budget 全 OK；design_text 层比例（25%/28%/10%）与实际数据一致（round51 R161 伴生项随方案 A 收敛） | ✅ 持续 |
| 10 | **R141 前置就绪 + 表格因子分非零**：持仓 30/31 只 shares_held 已灌（3fb66b1）；check 67 表格 15 只因子分 -0.71~+0.13 全非零 | ✅ 持续 |
| 11 | **R139 DB 治理持续**：integrity=ok / journal=delete / sync=2；本轮写入 design 16 + check 67 无损 | ✅ 持续 |
| 12 | **R146 premium_discount 仍全 0**（31/31=0.0，盘后采样）——与 round51 一致，**待交易时段复测**后终判 | ⏳ 待复测 |
| 13 | **R148/R150 真断链维持**：industry_diversification 31/31=0.0、ln_mcap IC 口径 zero=1.0 且矩阵缺键；data_health_check 11/12（critical 断链 FAIL 与 round51 一致） | ❌ 存量断链 |
| 14 | **新发现 R170 warmup 预算口径分裂**：启动日志 `[warmup-budget] 39.8s 超预算告警`，同刻 `warmup_timing.json` total=7.46s（6 records）——budget 计时覆盖 7 任务（main.py:651-661），timing 只记 6 项，~32s 差额无归属，**预算告警无法归因** | ❌ P2 新发现 |
| 15 | **新发现 R171 check holdings 无市值字段**：check 67 `holdings_json` 15 只均无 `market_value`/`shares_held` 键（市值总和=0）——round51 遗留④「R141 持仓市值列复测」的验证路径在 check 输出 schema 中**不存在**（预期与实现不符） | ⚠️ P3 新发现 |
| 16 | **新发现 R172 守卫脚本 [::1] 默认值不适配容器**：`verify_allocation_invariants.py:31 DEFAULT_BASE="http://[::1]:8000"` 裸跑时挂死/超时（容器 0.0.0.0 v4 端口映射 + 宿主代理劫持 [::1]）；`--base http://localhost:8000` 实测 PASS；patrol.py:470-475 显式传 host 不受影响 | ⚠️ P3 新发现 |
| 17 | **构建环境故障（已处置）**：`deb.debian.org`（Fastly 146.75.122.132）实测 695 B/s + `trixie/main Packages` 404 → apt 层 exit 100 构建失败；切 TUNA 镜像 1789 kB/s 提速 ~2500×，gcc 安装成功。**backend/Dockerfile 已打可逆补丁（工作树未提交，待拍板保留/还原）** | ⚠️ 环境项（已缓解） |
| 18 | **LLM provider 生态持续劣化**（观察项）：opencode_zen 54.8% err（27772/15210）、openrouter 48.4%（910/440）、b_ai 31.3%；deepseek 主源 4.7% 稳定；excluded 机制在位（opencode_zen/deepseek-v4-flash-free） | ⚠️ 观察 |

### 0.2 验证矩阵（round51 → round52 对照）

| round51 项 | round51 状态 | 本轮实测（HEAD 56df5ed） | 结论 |
|---|---|---|---|
| 方案 A+B（R162/R163） | 已采纳待实施 | design 16 三方案 GAP ±0.0000 + target_amount consistent | ✅ **已实施且生效** |
| 方案 C（R165） | 已采纳待实施 | redis_available=true（round51 false） | ✅ **已实施且生效** |
| 方案 D（R164/R167） | 已采纳待实施 | [envelope] 结构化日志 + check67 文案=真预算耗尽 | ✅ **已实施且生效** |
| 方案 E（R166） | 已采纳待实施 | zero_ratio_scope=ic_batch + note 在响应 | ✅ **已实施且生效** |
| 方案 F（R168） | 已采纳待实施 | goldens 64 条 ≥50 | ✅ **已实施且生效** |
| R140 层预算 | ✅ 生效 | design 16 layers ≤ budget ×3 | ✅ 持续 |
| R141 表格因子分 | ✅ 生效 | check 67 因子分 -0.71~+0.13 全非零 | ✅ 持续（市值列验证路径缺失→R171） |
| R160 mark_excluded | ✅ 生效 | excluded 列表在位（1 项）；180s 增量观察本轮未做 | ✅ 配置在位（增量口径未复测，诚实标注） |
| R139 DB 治理 | ✅ 持续 | integrity=ok，持续写入无损 | ✅ 持续 |
| R146 premium_discount | ⏳ 待交易复测 | 31/31=0.0（盘后） | ⏳ 维持待交易时段复测 |
| R148 industry_diversification | ❌ 真断链 | 31/31=0.0 | ❌ 维持 |
| R150 ln_mcap | ❌ 真断链 | IC zero=1.0 + 矩阵缺键（holdings 无该因子键） | ❌ 维持 |
| R149 news_heat | ✅ 生效 | design 16 矩阵 31/31=2.4 非零 | ✅ 持续 |
| data_health_check | 11/12 | 11/12（critical 断链 FAIL 同 round51） | ✅ 一致 |
| patrol L2-llm-exclusion | ✅ | 本轮未跑 patrol（预算限制） | ⚠️ 未复测 |

### 0.3 耗时基线（fresh 容器 / 本轮实测）

| 端点 | 首呼 | warm | round51 基线 | 结论 |
|---|---|---|---|---|
| /health | 0.22s | 0.23s | 0.05s | ✅（路径含宿主网络层，口径同 probe 直连 :8000） |
| /api/v1/admin/factor-health | **4.67s** | 0.53/1.52s | 3.92s / 0.01s | ⚠️ 退化 5.3×（性能债登记；IC tracker 冷启动统计） |
| /api/v1/market/realtime/portfolio | 1.32s | 0.21s | **5.05s** / 0.01s | ✅ 好转 3.8×（round51 归因「nav 注入相关」未复现——R165 redis 修复后合理；待交易时段复测确认） |
| /api/v1/market/sectors/heat | 2.55s | 1.10s | 0.97s / 0.02s | ⚠️ 退化 2.6×（轻度，登记观察） |
| /api/v1/market/watchlist | 0.23s | — | 0.02s | ✅ |
| /api/v1/admin/llm/health | **22.05s** | — | 4.72s | ⚠️ 退化 4.7×（性能债登记；LLM 网关探测链外部依赖慢，与 provider 生态劣化同源） |
| 其余路由（openapi 71 paths 抽样 17） | ≤0.9s | — | — | ✅（probe20 全录） |

### 0.4 LLM provider 现状（by_provider，累计窗口）

| provider | calls | errors | err% | 评级 |
|---|---:|---:|---:|---|
| deepseek | 25692 | 1199 | 4.7% | ✅ 主源稳定 |
| opencode_zen | 27772 | 15210 | 54.8% | ❌ 503/空响应频发（excluded 1 模型在位） |
| openrouter | 910 | 440 | 48.4% | ❌ 403/502/429（envelope 已结构化，R167 修复后可归因） |
| unknown | 605 | 450 | 74.4% | ❌ |
| b_ai | 32 | 10 | 31.3% | ⚠️ round40 新接入 |
| fake | 155 | 2 | 1.3% | — 测试流量 |

### 0.5 数据源状态（容器运行 ~40min 抽样）

| 数据源 | available | 备注 |
|---|---|---|
| sina / push2delay / tencent / sector_lv / concept_lv 等 | true | 正常（probe24：8 源中 7 true） |
| mootdx | false（cooldown 120s，failures=0） | bestip 缺配置致 `_mootdx_realtime exception`（known-env-issues 已知环境项，round51 一致）；R169 守卫下 588xxx 不走 mootdx |

---

## 1. 环境构建与启动（阶段 1）

| 项 | 结果 |
|---|---|
| 前置 | Docker daemon 未运行 → 用户授权后启动 Docker Desktop（10s 就绪） |
| 首次构建 | **失败**：apt 层 exit 100。探针实测：`apt-get update` 695 B/s（7min15s 仅 303 kB）+ `trixie/main/binary-amd64/Packages` 404（Fastly 节点 146.75.122.132）。44h 前构建可成功 → 判定为**当下网络/CDN 环境故障，非代码回归** |
| 处置 | `backend/Dockerfile` RUN 块前置 `sed` 将 apt 源切至 TUNA（mirrors.tuna.tsinghua.edu.cn）——探针验证 1789 kB/s + gcc 安装成功后落补丁；**该补丁在工作树未提交**（`git diff backend/Dockerfile` 可见，+5/-2），待拍板保留或还原 |
| 二次构建 | 成功（EXIT=0；pip resolver ERROR×3 为 pandas_ta/mootdx --no-deps 拆分安装的已知告警形态，历史轮一致） |
| 容器 | backend(:8000)/frontend(:80)/redis(:6379) 三件套 Up 无重启 |
| 启动 | 16:24:59 启动 → 16:25:39 warmup 完成：ETF cache 1618 items、板块/市态/情绪/资讯循环全启动 |
| warmup 预算 | `39.8s 超过预算阈值 30.0s` 告警（但 timing json 仅 7.46s → R170 口径分裂，见 §4.1） |
| diag overlay | PROFILE_WARMUP=1 生效（cProfile enabled，pyinstrument 不可用跳过——与 round51 一致） |
| mootdx | bestip ERROR（容器缺 /root/.mootdx/config.json，已知环境项） |

---

## 2. 全链路诊断明细（阶段 2）

### 2.1 存活与回归门禁

- 路由面：openapi 实测 **71 paths**（round51「19/19」为探针子集口径）；抽样 17 端点全 200（probe20）。
- WS：`/api/v1/ws/news`、`/api/v1/ws/portfolio` 容器内握手 101 OK（probe31）。
- verify_e2e：本轮未跑全量（::1 双栈已知问题 + 代理劫持 [::1] 502，known-env-issues §1.1）；单端点 curl 全 PASS 替代。
- verify_allocation_invariants：`--base http://localhost:8000` 实测 **PASS**（「1 designs 全部合规」）；默认 `[::1]` 裸跑挂死 → R172。DB 侧等效断言（cash 一致性 + target_amount + Σtotal≤1.01）对 design 16 全 PASS。
- data_health_check（宿主跑，容器无 scripts/）：**11/12 PASS，1 FAIL = 5 个 critical factor 全空**（ln_mcap/ln_float_mcap/shares_change/institutional_holdings_change/industry_diversification）——与 round51 完全一致。
- patrol --full：本轮未跑（时间预算限制，登记遗留）。

### 2.2 主动触发新数据验证（延续 round51 方法）

1. `POST /api/v1/portfolio/design-async`（balanced, 500000, enhanced）→ task 25 completed（16:30:55，~5s）→ **design 16** 入库。
2. `POST /api/v1/portfolio/strategy-check-async`（on_exchange）→ task 26 completed（16:32:09，~78s）→ **check 67** 入库（llm_layer_ok=false / is_fallback=true）。

**design 16 层预算复验**（probe11 脚本复用，新旧同库对照）：

| 方案 | total | layers | budget | cash 一致性 | target_amount | 判定 |
|---|---|---|---|---|---|---|
| defensive | 1.0000 | core .45/sat .20/def .10/cash .25 | .50/.20/.15 | ✅ GAP 0.0000 | ✅ consistent | ✅ |
| balanced | 1.0000 | core .45/sat .22/def .05/cash .28 | .50/.22/.13 | ✅ GAP 0.0000 | ✅ consistent | ✅ |
| aggressive | 1.0000 | core .55/sat .30/def .05/cash .10 | .60/.30/.05 | ✅ GAP 0.0000 | ✅ consistent | ✅ |
| *对照 design 15 balanced（旧代码）* | *0.9500* | — | — | *❌ GAP +0.05* | *❌ 4 只 MISMATCH* | *round51 现象复现在旧记录上，归因闭环* |

**check 67 内容复验**：15 只持仓 suggestions 全量；表格因子分 -0.71~+0.13 全非零（15/15）；「LLM 分析超时」= 真预算耗尽（日志 30.0s CancelledError）；规则兜底建议与因子分/信号方向自洽。

### 2.3 因子口径与断链现状（R166 修复后口径）

- `/factors/active` 响应：`zero_ratio_scope: "ic_batch"` + note 明示「非当前因子矩阵零值占比，矩阵口径请直接抽样 factor_registry.compute() 输出，两口径不可互替」——round51 R166 的诊断方法论缺口已闭合。
- design 16 矩阵实测（31 只）：premium_discount 31/31=0.0（盘后，待交易复测）；news_heat 31/31=2.4 ✅；industry_diversification 31/31=0.0（真断链维持）；institutional_holdings_change 31/31=0.0（真断链维持）；shares_change / ln_mcap 键不在 breakdown（真断链维持）。

### 2.4 性能债登记（软门禁）

| 路径 | 本轮 | round51 | 阈值 | 处置 |
|---|---|---|---|---|
| /admin/factor-health 首呼 | 4.67s | 3.92s | ≤2s | ⚠️ 性能债（IC tracker 冷启动统计；warm 0.53s 说明仅首呼） |
| /admin/llm/health | 22.05s | 4.72s | — | ⚠️ 性能债（provider 生态劣化放大探测耗时） |
| /market/sectors/heat 首呼 | 2.55s | 0.97s | — | ⚠️ 观察 |
| /market/realtime/portfolio 首呼 | 1.32s | 5.05s | ≤3s | ✅ 好转（round51 归因项待交易复测确认） |
| patrol --full | 未复测 | >2min | — | ⚠️ 遗留 |

---

## 3. 分析结果质量审查（阶段 3 · 四问法）

对 check 67（规则兜底全量）与 design 16（三方案）逐句审查：

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 结论分级 | 修复建议 |
|---|---|---|---|---|---|
| design16 balanced「现金仓位 28%」(design_text) | 事实 | cash_row=0.2800 = 1−non_cash（R162 修复后文本与资金一致） | ✅ | 合理 | — |
| design16 三方案层比例 | 事实 | layers 与 design_text 表逐项一致（25/28/10） | ✅ | 合理 | — |
| design16 target_amount | 事实 | 全 consistent（无 +36% 形态） | ✅ | 合理 | — |
| check67「市态：震荡」 | 事实 | market_regime=range_bound；实测 588200 -1.72%/510300 -1.37% 窄幅 | ✅ 一致 | 合理 | — |
| check67 159338「因子分 0.03（中性）+ sell 信号 → hold」 | 事实+规则 | 因子分 0.03 与「中性」「维持现状」自洽；sell 下不加仓的理由已明示（「市态震荡不追涨杀跌」） | ✅ | 合理（round51 提出的「信号-建议矛盾未解释」已由文案自释） | — |
| check67 159876「因子分 -0.71 弱 + 技术卖出 → 建议减仓」 | 事实+推断 | 表格最低分 + 分批减仓风控文案 | ✅ 方向自洽 | 合理 | — |
| check67「LLM 分析超时（30s 未返回）」 | 事实 | 日志 16:32:08 `interrupted after 30.0s (CancelledError)`——真预算耗尽，上游 502/429 重试链 | ✅ | 合理（R164 修正后不再失真） | — |
| check67「因子覆盖 55.6%」 | 事实 | 与 check62 同口径 | ✅ | 合理 | — |

**汇总**：可采信 8 条 / 需修正 0 条 / 失效 0 条（round51 为 5/1/3——R162/R163/R164 三处失真全部随方案 A/B/D 落地消除）。

**数据准确性抽查**：
- 权重和：design16 三方案 =1.0000 ✓✓✓（round51：0.95❌/0.9752❌ → 全修复）
- target_amount vs capital×weight：全一致 ✓（round51 ❌ → 修复）
- 占位检测：RSI 50.0 未出现 ✓；因子分无 0 值占位（0/15）✓
- 新鲜度：design16/check67 as_of=2026-09-02 盘后 ✓
- R141 相关：holdings_json 无市值字段 → 该维度本轮**无法验证**（R171，诚实标注而非假验证）

---

## 4. 问题分析与修复方案（阶段 4）

### 4.1 R 系列发现汇总（本轮新增 R170-R172）

| 编号 | 发现 | 根因机制链（file:line） | 严重度 |
|---|---|---|---|
| R170 | warmup 预算告警与 timing json 口径分裂（39.8s vs 7.46s，~32s 无归属） | `main.py:651-661` sequence 覆盖 7 任务（含 `_background_instruments_sync`/`_background_indices_meta_sync`/`_warmup_design_data`/`_warmup_sector_cache`），`_seq_elapsed`（main.py:645-674 finally）按全序计时；`warmup_timing.json` 仅 6 records（init_db/redis_init/load_llm_excluded/warmup_etf_cache/warmup_global_indices/warmup_market_cache）——instruments/design_data/sector 三段未入 timing，告警指向的 json 无法归因 | P2 |
| R171 | check holdings 无 `market_value`/`shares_held` 字段，R141「持仓市值」复测路径不存在 | `strategy_check_worker.py` holdings 构造键集：symbol/name/weight/factor_summary/industry/tech_signal/action/suggested_weight/... 无市值键；`_generate_check_llm_comment`（:218）只在 LLM 注释路径 sum `market_value`，而 holdings 本身不带该值。round51 遗留④预期「持仓市值列复测」与实际 schema 不符 | P3 |
| R172 | `verify_allocation_invariants.py:31 DEFAULT_BASE="http://[::1]:8000"` 容器场景不可达（v4 端口映射 + 宿主代理劫持 [::1] → 502/超时） | 脚本默认值按本地 `--host ::` v6only 场景硬编码（round36 §8-C 同款注释）；patrol.py:470-475 显式传 `--base http://{host}:{port}` 不受影响；仅裸跑踩坑。`--base http://localhost:8000` 实测 PASS | P3 |

**环境项（不占 R 编号）**：构建期 apt 源故障——已探针定位（695 B/s + 404）并打 TUNA 可逆补丁（backend/Dockerfile 工作树未提交）。处置选项：① 保留补丁（构建稳定性优先，注释已注明缘由）② 网络恢复后 `git checkout` 还原。回填 known-env-issues §3（构建环境类）。

### 4.2 测试防护体系缺口分析（增量）

| 发现 | 最应拦截的防护层 | 为何未识别 | 应补的守卫 |
|---|---|---|---|
| R170 | smoke_startup / lifespan 观测 | 预算告警只看 `_seq_elapsed` 总量，timing json 覆盖面无一致性断言（records 集合 ≠ sequence 任务集合时无人报错） | 负向：mock 某 warmup 段 30s → 断言 timing json 必含该段记录（或告警输出列出未覆盖段） |
| R171 | check 单测 | holdings schema 无字段级契约断言（api-contracts/portfolio/strategy-check 契约若列明 market_value 则会 FAIL） | 契约层补 `holdings[].market_value/shares_held` 字段 + 单测断言非空（shares_held 已灌 30/31，数据侧就绪） |
| R172 | patrol/脚本自身 | patrol 传参路径正确掩盖了默认值缺陷（仅裸跑触发） | 文档注明 + 可选 `--base` 默认值 localhost 回退探测（[::1] 失败自动换 localhost） |

### 4.3 补齐设计（只写方案，不写代码）

- **方案 A（P2，R170）**：warmup timing 与 budget 同口径——`_run_warmup_sequence` 每个任务包 `record(label, t0, t1)`（7 项全录），或 budget 告警消息直接内嵌未覆盖段清单。影响 `main.py:640-674` + timing 写入点。验收负向：人为让 `_warmup_design_data` sleep 35s → 告警触发且 timing json 含 design_data 记录。
- **方案 B（P3，R171）**：check pipeline holdings 增 `market_value`（= shares_held×realtime price，缺价格时诚实 null）与 `shares_held` 字段，同步 api-contracts/portfolio 契约。验收负向：shares_held>0 的持仓在 check 67 形态输出中必须带非空 market_value。
- **方案 C（P3，R172）**：脚本默认值 localhost 化或 [::1] 失败自动回退 localhost；README/patrol 文档注明容器场景用法。验收：裸跑（无 --base）在容器宿主机 PASS。
- **方案 D（环境）**：backend/Dockerfile TUNA 补丁保留/还原拍板 + known-env-issues 回填（症状指纹：apt 层 exit 100 + Fetched xx kB in xmin + 404 trixie Packages）。
- **观察项（无代码动作）**：LLM provider 劣化（opencode_zen 54.8%/openrouter 48.4%/llm-health 22s）持续监控；excluded 机制已兜底；R160 180s 增量口径下轮补测。

### 4.4 与 round51 文档的关系

- round51 §6 决策表 5 项（方案 A-F）**全部实施且本轮实测生效**（§0.2 矩阵前 5 行）。
- round51 §2.3 残余风险「premium_discount 依赖盘中 nav」——本轮盘后仍全 0，维持「待交易时段复测」，不新增结论。
- round51 遗留清单⑤项状态：① R146 盘中复测（⏳ 维持）② off_exchange check（本轮 on_exchange 亦遇 LLM 层失败，off_exchange 未触发，遗留维持）③ patrol --full 长跑（未复测）④ R141 持仓市值复测（→ R171：验证路径不存在，需先补 schema）⑤ R168 金标补量（✅ 已落地 64 条）。

---

## 5. 三轮 Review 记录（阶段 5）

### 5.1 Round 1 — 事实核对

| 项 | 核对 | 结论 |
|---|---|---|
| design16 层数字 | probe11 脚本输出（DB 直读）与 API /designs/16 双源 | ✅ |
| check67 表格 | DB report_text 直读 + 正则抽 15 行 | ✅ |
| R162/163 修复归因 | design 15（旧代码）vs design 16（HEAD）同库对照，GAP/MISMATCH 仅存在于旧记录 | ✅ |
| R165 | probe22 `redis_available:true` vs round51 `false` | ✅ |
| R167/方案D | 容器日志 `[envelope] openrouter/... code=502` 原文摘录 | ✅ |
| R164 | check67 文案 ↔ 日志 30.0s CancelledError 时间对应（16:32:08） | ✅ |
| R170 | main.py:651-661 任务清单实读 vs warmup_timing.json 6 records 实读 | ✅ |
| R171 | holdings_json 键集实读（15 只无 market_value/shares_held） | ✅ |
| R172 | 脚本 ：31 默认值实读 + 裸跑 502/timeout 实测 + `--base localhost` PASS 实测 | ✅ |
| R169 | probe24 588200 price=1.14 | ✅ |
| apt 故障 | apt_probe.out（695 B/s+404）/ apt_probe3.out（TUNA 1789 kB/s+gcc ok） | ✅ |

### 5.2 Round 2 — 逻辑一致性

- §0.1#1「R162 修复」与 §0.1#12「R146 待复测」不矛盾：前者是资金分配层（已修复），后者是数据源层（盘后 nav 未发布），互不干扰。✅
- §0.1#5「check67 文案合法」与 §0.4「openrouter 48.4% err」自洽：正是高 err 率（502/429 重试链）耗尽 30s 预算导致真超时——文案如实反映机制。✅
- §0.3 realtime/portfolio 好转（5.05s→1.32s）与 §0.1#3 R165 修复自洽：round51 归因「nav 注入链路相关」，R165 redis 修复后 NAV 走缓存 → 耗时回落，方向一致（终判待交易时段复测）。✅
- R170 两个数字（39.8s vs 7.46s）差异解释为「计时范围不同」而非数据错误：告警口径含 7 任务全序，json 只记 6 项——与 §4.1 机制链一致。✅
- R168 64 条 vs round51「18 条欠量」：46 条增量恰为 round51-expansion.jsonl，数量闭合。✅

### 5.3 Round 3 — 完整性

- 验证窗口标注：R146 premium_discount / realtime/portfolio 归因均标「待交易时段复测」（§0.2/§2.4）。✅
- 未复测项诚实标注：R160 180s 增量口径、patrol L2、patrol --full、verify_e2e 全量（§0.2/§2.1）。✅
- 未决项清单：① R146 盘中复测；② off_exchange check 触发；③ patrol --full 长跑；④ R171 补市值 schema 后 R141 市值列复测；⑤ R170/R171/R172 方案待拍板；⑥ Dockerfile 补丁去留。均已入 §4.3/§4.4。✅
- 风险点：方案 B（R171）涉及 check 输出 schema 变更，须先更新 api-contracts 再动代码（契约先行强制约定）。✅ 已注明。
- 诊断合规性：本轮按 AGENTS.md「未收到开始实施不写修复代码」执行——唯一代码区改动为构建阻断的 Dockerfile 可逆补丁（诊断前置条件，非业务修复），已显式标注待拍板。✅

**结论**：三轮 review 通过，文档达到「方案轮定稿」标准。

---

## 6. 决策点（2026-09-02 用户已拍板）

> **拍板结果**：#1 补丁保留并提交、#3 R146 留到下轮诊断复测；#2/#4 待后续触发。

| # | 决策 | 拍板 | 状态 | 落实 |
|---|---|---|---|---|
| 1 | Dockerfile TUNA 补丁保留并提交 | 采纳 | ✅ 已提交 | commit `192b8c9`（含 known-env-issues §2 指纹回填 + 2 个门禁抓出的测试缺陷修复，已 push） |
| 2 | R170/R171/R172 修复方案 A-C | 待拍板 | 📋 方案就绪 | 未收到「round实施」不写代码 |
| 3 | R146 premium_discount 交易时段复测 | 留到下轮诊断 | 📋 已并入下轮容器诊断清单 | 复测命令已写入本文档 §4.4① |
| 4 | R172 守卫脚本 base 默认值回退（方案 C） | 待拍板 | 📋 并入 #2 实施轮 | — |

> **实施轮插曲（commit 192b8c9 附带）**：pre-commit 全量 pytest 连续 2 次抓到
> `test_run_urllib_error_returns_exit_2`（真实 urlopen `invalid:9999` 撞 F23 socket
> 守卫，单跑借道系统代理侥幸）与 `test_token_store_record_goes_to_isolated_db`
> （record 只入队不落库，跨 loop/xdist worker flush 时序 flake）——均已按 AGENTS.md
> 「外部访问必须 mock」修复为确定性写法，全量 3080 passed 复验后入 commit。

---

## 7. 用户反馈复核（2026-09-03 11:31 盘中，本地后端 `2cd9e1d`，交易时段内）

> 复核窗口：2026-09-03 11:31-12:00（**交易时段**，`is_trading_time()=True / session=open` 实测）；
> 本地后端 `--host ::`（PID 27048）+ 同一 `data/portfolio.db`（31 只持仓：场内 15 + 场外 15 联接 C）。
> 12:00 更新：据用户页面截图（场内 15 只现价 ¥0.00/涨跌幅 +0.00%、场外全部正常且现价=ti 场内标的）二次定位，
> 新增 **R176**（asset_type 口径漂移）为反馈①的直接根因，R175 降级为伴随观察项——详见 §7.1 定性修正。

### 7.1 反馈①「场内 ETF 涨跌幅都是 0」→ 定位 R173（场外估值断链，静态）+ R176（asset_type='ETF' 未入 A 股批量，页面所显直接根因）

**实测复现**（11:31-11:35 三接口对照）：

| 接口 | 场内 15 只 | 场外 15 只 | 备注 |
|---|---|---|---|
| `POST /portfolio/daily-pnl`（组合页盈亏 tab 数据源） | ✅ 全非零（0.42/-1.8/0.64…） | ✅ 全非零（estimate_source=tracked_index） | 无类型查询路径 |
| `POST /portfolio/calculate`（pricing 链路，无类型） | ✅ 全非零 | ✅ 全非零（tracked_index） | 无类型查询路径 |
| `GET /market/realtime/portfolio`（market_service 链路） | ✅ 全非零 | ❌ **15/15 change_pct=0**，`is_estimated=true, estimate_source='nav'` | 静态断链 |

**R176（本轮 11:48 用户截图所指直接根因，9-3 12:00 定位）**：前端 `getAllocation(type)` 带 `portfolio_type` 过滤调用 `/calculate`，**场内 15 只 100% 涨跌幅=现价=0**，场外正常——与截图形态完全一致（场内有值列 ¥0.00/+0.00%，场外全部正常）。

机制链（证据齐全）：
1. `list_etfs(db, "on_exchange")` 返回的 15 只 `asset_type` 全部 = **`'ETF'`**（9-1 持仓重灌 seed CSV `r51l1_inner.csv` 第 4 列即 `'ETF'`，commit 3fb66b1）；
2. `pricing.py:_split_symbols:172-174` A 股批量白名单只认 `asset_type == "A"`（HK/US 同理）→ 15 只 **四个分支全部为空**（实测 `a_symbols=0/hk=0/us=0/tracked_a=0`）→ `price_map` = 空 dict；
3. `allocation.py:39` `price_map.get(e.symbol, (0, 0))` → 现价/涨跌幅全 0；77 行基本面分支 `asset_type == "A"` 同样跳过；
4. **无类型查询为何正常**：31 只混查时 off_exchange 15 只 `asset_type='A'` 入 a_symbols，其 tracked_a（场内代码）一并入批量 → 返回的 batch 报价按 symbol 建 map → **场内 15 只意外被 ti 的批量捎带覆盖** → 看起来正常（round34-B7 起 8-27 灌录口径 asset_type='A' 时代该缺陷被掩盖）；
5. cache_key 含 symbol 列表（:37-42），`on(15 空列表)` 与 `all(30)` 键不同 → 场内过滤请求独立走空批量 → 全 0（实测 0.0s 命中空结果缓存、TTL 15s 内稳定复现）。

> **定性修正**：§7.1 早期版本把「场内全 0」归因 R175（A 股批量 3s 截断时序性静默 0）——R175 机制存在且仍是性能/语义债，但**页面截图的直接根因是 R176 数据口径**（带类型过滤 100% 复现、无类型不复现，时序解释无法涵盖此确定性）。R175 降级为伴随观察项。

**R173 根因机制链**（`market_service.py:1213-1286`，静态必现，维持原判定）：

1. 场外联接基金的 `tracked_index` 存的是**场内 ETF 代码**（022449→159338、011613→588000…，2026-08-27 灌录口径）；
2. `get_portfolio_realtime:1246` 盘中分支条件 `now_trading and ti in index_price_map`——`index_price_map` 键集 = **8 个指数代码** `{000001,399001,399006,000688,000300,000016,000905,000852}`（:1196），ti 是 ETF 代码 → **条件恒 False**；
3. 15 只全部落入 else → `_off_fundnav_tasks` 并发 `fetch_fund_nav`（:1268-1281）→ 该分支硬编码 `"change_pct": 0`（:1278）；
4. 结果：**盘中也不走 tracked_index 估值，永远输出 0%**——实测 11:35（盘中）15 只 estimate_source 全集 = `{'nav'}`，佐证分支从未命中。
5. 佐证二：逐只对照「场外接口值 vs 其 tracked_index 场内标的实时涨跌」——159338=+0.5% 而 022449=0、518880=+2.33% 而 000217=0……**估值源数据就在同一响应的 quotes 里（a_symbols 已含 ti），只是没被查**。
6. 佐证三：`fetch_fund_nav("022449")` 实测返回 `{"nav": 1.1751, "daily_change_pct": -1.42, "nav_date": "2026-09-02"}`——nav 分支连 T-1 涨跌都没用上，硬编码 0。

**与 daily-pnl 链路对照**：`pricing.py:_split_symbols:177-178` 把 `tracked_a`（场内 ETF 代码）并入 A 股批量 → `allocation.py:45-48` 用 `price_map.get(e.tracked_index)` 取到真实涨跌——**同一份 tracked_index 在 pricing 链路语义正确，在 market_service 链路被当指数代码比对 → 断链**。两链路口径不一致。

**R175 时序性缺陷**（用户「场内全 0」最可能的所见形态）：`pricing.py:49-58` `_a_batch` 对 A 股批量行情 **3s 整批截断**（R4-16）——超时即整批降级为空 → `price_map` 无该批 symbol → `allocation.py:39` `price_map.get(e.symbol, (0, 0))` → **场内+场外全部 change_pct=0 且 daily_pnl=0**，15s `_PRICE_MAP_CACHE` 后自愈。早盘数据源高峰/本地冷启动时必现数秒。违反「不静默降级」：0 与「行情暂不可用」语义被混淆（前端把 0 当真实涨跌渲染）。

### 7.2 反馈②「tab 选场内/场外，页面同时出现场内和场外的饼图」→ R174（scope 过滤缺口）

**根因**（`frontend/src/views/PortfolioAnalysis.vue:40-47`，盈亏 tab）：`SummaryCards`/`PnLDetailTable`/`PnLBarChart` 均响应 scope（`:activeTab="scope"` / `pnlItems` 按 scope 过滤，useDashboardData.js:24-28），**唯独两个 `AllocationPieChart`/`AllocationTable` 的渲染条件只看数据非空**：

```vue
<div v-if="allocationOn?.allocations?.length">…场内分配饼图+表…</div>
<div v-if="allocationOff?.allocations?.length">…场外分配饼图+表…</div>
```

→ scope 切「场内」时场外饼图仍在（反之亦然）——round34-B7 迁移时硬编码了「综合视图」的并排双饼图，未随 scope tab 收敛。**属 UI 一致性缺口，非数据错误**。

### 7.3 修复方案（只写方案，未实施——待拍板）

- **方案 A（P1，R173 治本）**：`get_portfolio_realtime` 盘中估值改查 quotes 内 ti 实时行情——`a_symbols` 构建时已把场内代码（5/1/6 开头）的 ti 纳入批量，quotes 里必有 ti 报价：
  ```python
  ti_quote = next((q for q in quotes if q.get("symbol") == ti), None)
  if now_trading and ti_quote and ti_quote.get("change_pct") is not None:
      quotes.append({..., "price": ti_quote["price"], "change_pct": ti_quote["change_pct"],
                     "estimate_source": "tracked_index"})
  ```
  原 `ti in index_price_map` 分支保留为 ti=指数代码形态的兼容；影响 `market_service.py:1224-1262`。验收：盘中 off 15 只 change_pct 与其 ti 场内标的逐只一致（±0）。
- **方案 B（P2，R173 兜底）**：`_fetch_one` nav 分支 `"change_pct": 0` 改为 `float(nav_data.get("daily_change_pct") or 0.0)`（fetch_fund_nav 契约已含该字段，实测 -1.42）——盘后/估值源缺失时诚实显示 T-1 净值涨跌而非假 0。
- **方案 E（P1，R176 治本，二选一）**：
  - **E-1 数据侧（推荐，最小）**：UPDATE `portfolio_etfs SET asset_type='A' WHERE asset_type='ETF' AND portfolio_type='on_exchange'`（15 只）+ 修 `r51l1_inner.csv` 第 4 列防再灌错 + `design.py:61`/`transfer.py:113` 等写 `'ETF'` 的写入点同步改 `'A'`（写入口径统一）。依据：`'A'` 是 pricing/基本面/`_split_symbols` 全链路的既定口径（hub `get_asset_realtime(symbol, "A")` 语义），DB 存 `'ETF'` 属 9-1 重灌引入的口径漂移（8-27 灌录为 'A'）。
  - **E-2 代码侧（兼容广）**：`_split_symbols` 白名单扩为 `in ("A", "ETF")`（ETF 语义上就是 A 股场内基金）——不改数据，兼容历史 DB；风险：语义上 'ETF' 未区分港/美 ETF（当前项目无此形态，实际等价）。
  - 验收（共同）：`POST /calculate?portfolio_type=on_exchange` 场内 15 只现价/涨跌幅与无类型查询逐只一致；截图中 ¥0.00/+0.00% 消失。
- **方案 C（P2，R175）**：pricing `_a_batch` 截断后 price_map 缺失的标的在 `allocation.py` 输出 `estimate_source="unavailable"`（或 `change_pct=None`），前端 `change-cell` 对 None 显示「—」（复用「行情数据暂不可用」态），**0 值不再冒充真实涨跌**；可选叠加：A股批量失败后 5s 内带退避重试一次。
- **方案 D（P3，R174 前端 2 行）**：`PortfolioAnalysis.vue:40/44` 渲染条件补 scope：`v-if="scope !== 'off_exchange' && allocationOn…"` / `v-if="scope !== 'on_exchange' && allocationOff…"`（combined 显示双饼图，单选只显示对应侧）。
- **契约注记**：方案 A/B 改 `/market/realtime/portfolio` 响应字段语义（off_exchange 条目 change_pct 可为估值值），需在 api-contracts/market 补记 off_exchange 估值口径说明；方案 C 改 daily-pnl 空值语义，需同步 api-contracts/portfolio + 前端空值渲染；方案 E-1 属 DB 数据订正（无 API 契约变化，但需在 8-27/9-1 灌录 memory 与 seed CSV 同步口径）。

### 7.4 与 §0-§6 结论的关系

- 本节发现均为**新发现**（R173/R174/R175/R176），不改变 §0 复验结论（R162-R168 修复确认均以 design/check 链路为对象，与本节 market_service/portfolio/pricing 前端链路无交集）。
- R173 与 round51 R165（NAV Redis）修复后的行为无冲突：R165 治理的是 nav 缓存预热，R173 是估值分支的**代码级条件恒假**，属 round52 §2.4 realtime/portfolio 好转归因之外的遗留估值口径问题。
- R176 为 9-1 持仓重灌（3fb66b1）引入的数据口径回归：8-27 灌录 asset_type='A' 时代 pricing 全链路正常，重灌后 seed CSV 用 'ETF' 且 pricing 白名单未覆盖 → 带类型过滤全 0。归并「数据口径漂移无 schema 级守卫」根因类（与 R163 同型：写入口径与消费口径无一致性断言）。
- R175 呼应 §4.1 R164 同型教训：**失败路径的静默值（0）冒充真实值**，归并「单侧断言/静默降级」系统性根因类。

---

## 8. 用户反馈复核②（2026-09-03 12:10 盘中）：标的分析自动补全缺失（板块搜「创新药」/ 指数搜「红利低波」无结果）→ R177

### 8.1 现象与链路

用户在标的分析（`UnifiedAnalysis.vue`）切换 **板块/指数 tab** 输入关键词，补全下拉无结果。

前端链路（代码在位，无缺陷）：`UnifiedAnalysis.vue:132-138` 三模式各建 `useMarketSearch` 实例（kind: all/sector/index）→ `doSearch()` 透传 `kind` + `market` → `GET /market/search`。**问题全在后端数据层**。

### 8.2 后端实测（三类缺口，全部实锤）

| 搜索 | 后端返回 | 直接原因 |
|---|---|---|
| `kind=sector&q=创新药` | **0 条** | `sectors` 表 **0 行**（`_search_sectors` name ilike 恒空） |
| `kind=index&q=红利低波` | **0 条** | `indices_meta` 635 行中**无任何「红利低波」系指数**（红利低波 H30269 为中证 custom 指数，不在新浪指数 spot 列表） |
| `kind=index&q=红利`（对照） | **0 条（HTTP 层）** | 本地表 13 命中 + akshare 兜底失败 → 异常被 `except` 静默（:287-288）→ 0；直调函数实测 13 条——**HTTP 层与直调结果不一致待查**（疑似 lifespan 内 sync 源超时后 akshare 冷却/代理状态差；见 §8.3-③） |
| `kind=all&q=创新药`（对照） | 30 条（但全是 bj 股票） | symbol 模式不受影响（instruments 表 7192 行健康） |

### 8.3 根因机制链（三个独立缺口）

**① sectors 表从未有写入者（板块补全恒空，静态）**
- `models/search.py:31` 定义了 Sector 表（BK 码），`_search_sectors`（market.py:205）查询它——但**全代码库无任何任务/脚本写入该表**；
- 板块实时数据实际存在于**内存缓存**（`update_sector_cache` 60s 刷新，`/sectors/concept` 实测 500 只含「创新药」（BK1027 系）、`/sectors/industry` 496 只），**key = sector_name，与 sectors 表完全脱节**；
- 结论：O30（round7 §7 P30①）设计时只建了表和查询，写入链从未落地——板块补全自设计起恒空。

**② indices_meta 同步源 akshare 语义漂移（行业/概念指数段收集恒 0，静态）**
- `sync_indices_meta.py:6-7` 声称「同花顺行业/概念指数 → ~600 个」：调用 `ak.stock_board_industry_index_ths` / `stock_board_concept_index_ths`；
- **akshare 1.18.x 实测该两接口语义已变**：签名 `stock_board_industry_index_ths(symbol='元件', start_date, end_date)` = **单板块历史 K 线**（返回日期/开高低收 7 列，实测默认参数返回单一元件板块 2020 起日线）——**不再返回板块列表**；
- 无参调用「不报错但收集 0 行」（返回 K 线 df 被按 `指数代码/指数名称` 列解析 → 无此列 → `code and name` 过滤全弃）→ `_fetch_ths_*` 两段恒空 → indices_meta 只剩新浪 spot + 静态段（635 行）；
- **可用替代接口（实测）**：`stock_board_industry_name_ths()` = 90 行、`stock_board_concept_name_ths()` = ~500 行（name+code 两列，概念表实测「创新药」= 308014 命中）——正是设计者当年想要的列表数据，接口名换成了 `_name_ths`。

**③ 红利低波系指数数据源缺位（结构性覆盖缺口）**
- 中证 custom 指数（红利低波 H30269/H20269、红利低波100 等）**不在新浪 spot 列表**（实测 sina spot「红利」11 条、「红利低波」0 条），静态兜底段也未收录；
- akshare 兜底 `_search_indices_akshare_fallback` 用的仍是同一 sina spot 源 → 兜底无效；
- 讽刺的是 `instruments` 表里有 33 只「红利低波ETF」（512890/560150/515480…）——**搜索 ETF 能搜到，搜其跟踪指数搜不到**。

### 8.4 修复方案（只写方案，未实施——待拍板）

- **方案 A（P1，缺口①）**：板块搜索改走内存缓存——`_search_sectors` 优先查 `market_data_hub.get_sector_concept()/get_sector_industry()` 的缓存列表（500+496 只，key=sector_name）按 `sector_name` contains 过滤，sectors 表查询保留为兜底（未来有写入者时自然生效）；**或**补一个与 `refresh_sector_cache` 同周期的 sectors 表 upsert（6-60s 频率低但结构更正规，还需处理 BK 码与 type 归属）。推荐前者（零写入链、缓存即真理源）。验收：板块 tab 输「创新药」出 BK 码板块 ≥1 条。
- **方案 B（P1，缺口②）**：`sync_indices_meta._fetch_ths_*` 换用 `ak.stock_board_industry_name_ths()`（90）/ `stock_board_concept_name_ths()`（~500）——列表语义与设计意图一致，且**顺带修复缺口③的 A 股行业/概念指数覆盖**（同花顺指数含医药/红利等细分主题）；symbol 列格式化时统一加交易所前缀或保留裸码（与现有 635 行去重合并）。
- **方案 C（P2，缺口③）**：静态兜底段 `_STATIC_EXTRA_INDICES` 增补中证红利系（H30269 红利低波/H20269 红利低波100/000922 中证红利/000015 上证红利等高频使用指数，symbol 用 `sh000015` 形态已有先例）；或同步源增 `ak.index_value_hist_funddb`/中证官网列表接口（成本高，静态段优先）。
- **方案 D（P2，§8.2 观察项）**：排查 `_search_indices` HTTP 层 0 vs 直调 13 的不一致——`_search_indices_akshare_fallback` 内 akshare 调用无超时包裹（`_aio.to_thread` 裸调），本地进程内实测耗时 8 段进度条 ~1s 正常，但 lifespan 同步后 akshare 会话/代理状态可能劣化；修复=兜底链加 `asyncio.wait_for`（10s）+ 失败 logger.warning 升级（现 debug 级别不可见）。
- **契约注记**：方案 A/B 均不改响应 schema（仍是 symbol/name/type/market 条目），仅数据源变化；`type: "sector"` 条目若来自缓存需补 `sector_code`（BK 码）映射——消费方（sector-analysis stream）已按 `query=name` 语义工作（`sector_fetcher.py:154` 明示「板块名称而非板块代码」），无破坏。

### 8.5 与 §0-§7 结论的关系

- R177 为**存量设计缺口**（O30 只设计查询未设计写入 + akshare 接口语义漂移双重叠加），非本轮/上轮实施引入的回归；akshare 1.18.x 语义漂移与 `shares_change` 日期修复（a8bf0d3 memory）同族——**外部源接口漂移无 schema 断言拦截**，归并同一系统性根因类。
- 与 R173/R176（§7）同为「数据链路断」，但层级不同：§7 是资金分配链（pricing/market_service），本节是搜索/分析入口链（instruments/sectors/indices_meta 三表 vs 内存缓存）。

---

## 9. 用户需求复核③（2026-09-03 12:40 盘中）：资讯页「全部」tab + 新闻卡片重要等级显式标注 → R178 方案设计

### 9.1 现状盘点（实测 + 代码链）

**分类架构**（F29，round23 §2.4 A4）：资讯页 5 tab（头条/宏观/国际/个股/研报），**桶间互斥、非包含关系**：
- 后端三桶缓存 `_news_buckets`（headlines/macro/global，`_news.py:202-208`，120s TTL，R23 空桶回退）+ 两类按标的查询（stock/research）；
- 头条 = 财联社电报(15) + 东财头条，**刻意不含宏观/国际**（F29：旧实现混入后与 macro tab 实测 3 条全重复）；
- 已有但**无 HTTP 端点**的合并视图：`hub.get_news()`（`_news.py:25-30`，= 三桶 headline+macro+global 顺序拼接，仅 mcp news_server 消费）。

**重要等级数据侧（已完备，零新增计算）**：
- 每条新闻双维度：`level`（1-5 重要性，`classify_news` 关键词法 + 弱化词降级 + R16 英文兜底 + F3-1 双轨校验）+ `category`（major/positive/negative/risk/neutral/other 极性）+ `stars`（P2-1 后为**新鲜度**维度，非重要度）；
- 实测 level 覆盖：headlines 15/15、macro 9/9、global 8/8、stock 10/10 **全部非空**——「全部」tab 与等级标注的数据条件现成。

**前端等级展示（现状不对称）**：
- 筛选器（`:34` minLevel 1-5）与推送（isImportant=level≥4）已按 level 工作；
- 但卡片上 **level 无数字/星级显式标注**——R83（round29）已移除「数字星」，理由：数字星当时编码的是新鲜度（stars），与 meta 行相对时间重复；仅剩 category 文字徽章（重大/利好/利空/风险/提醒）+ 左边框色 + 标题色。
- **用户诉求映射**：卡片上要的是 **level（重要等级）** 的显式视觉锚点——现有徽章显示的是 category（极性/类型），level≥4 仅通过「重要」徽章 + 红色间接可感知，level 2/3/1 之间完全不可区分。

### 9.2 方案设计（只写方案，未实施——待拍板）

**方案 A（P1，新增「全部」tab）**：
- 后端：`news.py` 增 `GET /news/all`——复用 `_news_bucket` 三桶 + `stock/research` 不参与（按标的查询型）；合并时**跨桶去重**（复用 `_dedupe` 标题归一化，F29 实测桶间有重复史）+ 按 `sort_time` 降序 + 上限 60；复用 `_with_partial_flag`（三桶任一空 → partial 诚实标注）；
- 前端：`NewsView.vue:178` tabs 头部插入 `{ value: 'all', label: '全部' }` 并设为默认 tab；`loadNews()` 增 `newsApi.all()` 分支；WS 实时推送分流扩展到 all tab（`:279` 现仅 headlines——`_news_cache` 合并视图含三桶，推送条件 `t !== 'headlines'` 改为 `t not in ('headlines','all')` 之外的判断需反向：all/headlines 均消费推送）；
- 关键决策点：全部 tab 是否含个股/研报？**建议不含**（这两个是按 symbol 查询型，全量拉取无意义且拖慢首屏），tab 描述文案注明。
- 验收：all tab 条数 ≈ headlines+macro+global 去重后之和；空桶时 X-News-Partial 生效；WS 推送在 all tab 实时插入。

**方案 B（P2，卡片重要等级显式标注）**：
- 展示形态（两选一或组合）：
  - **B-1 星级**：恢复数字星但**改编码 level**（★★★★☆ = level 4）——与 R83 移除的旧星区分：旧星编码 stars（新鲜度，与时间重复）；新星编码 level（重要度，现在无处显示），语义不重复。位置：category 徽章右侧，灰色小字，other 类也显示（与 R83「other 不渲染」决策不冲突——那是 category 徽章）；
  - **B-2 分档徽章**：level 4-5「重要」/3「关注」/1-2 不标注（噪音最小化）——更克制但 1/2 不可分。
  - **推荐 B-1**（用户明确要「每条都有地方体现」→ 全量显示星级最贴合）。
- 与现有维度的布局关系：`[category徽章(色)] [level星级★] 标题` ——category 管颜色语义（红涨绿跌），level 星管重要度排序感知，meta 行相对时间管新鲜度——三维度各得其所；
- `newsLevel.js` 增 `mapLevelStars(level)` 纯函数（1-5 → ★/★★/★★★/★★★★/★★★★★）+ 单测；`NewsView.vue:83` 徽章处插入渲染。
- 验收：任意 tab 卡片可见星级且与 level 字段一致；minLevel 筛选与星级视觉联动（筛 level≥4 时仅 4-5 星卡片留存）。

**方案 C（P3，配套）**：level 排序切换（时间 ↓ / 重要性 ↓ toggle）——「全部」tab 条数多时按 level 排序更有用；实现为前端 sort（`sort_time` vs `level*权重+sort_time`），无后端改动。

### 9.3 影响面与契约

- 契约先行：`api-contracts/news/` 增 `all.md`（响应 schema 与 headlines 一致 + partial 语义），方案 B 无契约变化（纯前端展示，level 字段已在响应中）；
- 测试：后端 `test_news_*` 增 /news/all 合并去重/partial 用例；前端 `NewsView` 组件测试增 tab 切换与星级渲染断言；
- 复杂度审计：/news/all 为三桶内存拼接 + 去重（O(n)，n≤~40），无新增外部调用——符合性能约定，无超时风险（复用 30s run_sync 上限）。

### 9.4 与 §0-§8 的关系

- R178（本节）为**功能增强需求**（非缺陷），与 R173-R177 缺陷修复互不阻塞；数据侧 level/stars 管线（round9 P2-1/round23 F22/F23/round24 R17-R31/round29 R83）演进清晰，本方案是在其上的展示层补全——**无新数据源、无新计算，纯聚合与展示**。

---

*诊断产物：C:/Users/Public/etf_probe/（probe20-33.out + openapi.json + build52.log + apt_probe*.out，会话级临时目录）；容器于诊断完成后回收。收尾 commit：192b8c9 / 2cd9e1d（2026-09-02 push）；§7-§9 复核 2026-09-03 追加（R173-R178），方案全部待拍板，未收到「round实施」不写代码。*


