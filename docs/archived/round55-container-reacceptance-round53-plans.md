# round55 容器全链路诊断 — round53 实施批 + round54 前端抛光复验（2026-09-12 周六盘后/周末）

> 本文档为独立 round55 文档，不改写被诊断的 round53 / redundant-review / round54 文档。
> 诊断对象：HEAD `f59fb17`（round53 实施批 `d976508` + 遗留批 + round54 前端抛光 `7c062b6` + LLM 对话追问 `58ed2cc` + 模型展示 `7f4a23c/0976181` + P0 视觉抛光 `f59fb17`）。
> 验证环境：Docker Engine 29.7.2，prod profile + diag overlay（PROFILE_WARMUP=1）。
> 验证窗口：2026-09-12 周六 21:37-22:30（**周末非交易日**：实时类结论标「周末形态」，盘中路径不复测；R146/R173-A 盘中结论沿用 round53 §12，不在本轮复测）。
> 容器 21:43 启动，21:44:31 warmup 完成（36.8s）；三容器 Up 全程无重启。
> 探针产物：`C:/Users/Public/etf_probe/`（build54.log / rt54.json / d34.json / c108.json / fh54.json / newsall54.json / dhc54.out / e2e54b.out / pytest54.out / vitest54.out，会话级临时目录不入仓）。

---

## 0. 执行摘要

### 0.1 核心结论（一句话/项）

| # | 结论 | 状态 |
|---|---|---|
| 1 | **构建干净**：backend/frontend 双镜像一次构建成功，0 pip resolver ERROR、0 apt 故障（TUNA 补丁持续生效） | ✅ |
| 2 | **R179 存续确认**：双 warmup 告警仍并存（新 `[warmup-budget] 36.8s` + 旧 `Warmup took 37.0s`，与 §6 拍板「暂缓登记」一致，不行动） | 📋 维持 |
| 3 | **R180 存续确认**：空 keyword `kind=all` 仍返回 30 条（与暂缓登记一致） | 📋 维持 |
| 4 | **R181 修复在新数据上保持**：design 34（三方案 33 持仓行）同指数重复 0 处，Σ=1.0、单只≤0.2 全合规 | ✅ 维持 |
| 5 | **R177/R178 维持**：sector 创新药=BK1106、index 红利=19、all=13；news/all 27=15+4+8 精确闭合 | ✅ 维持 |
| 6 | **R173 周末形态维持**：realtime/portfolio 38 条零 0 价零 0 涨跌（15 nav + 23 实时） | ✅ 维持 |
| 7 | **因子积累中健康**：6 个 no_data 全为「IC 积累中」真分支（14/14/14/4/4/2 vs 9-06 的 9/9/9/1/1/1），周末未灌水（R183 修复生效旁证） | ✅ 维持 |
| 8 | **R186（P2，新）**：envelope 类 LLM 兜底绕过 F1-9 识别 —— check 108 summary 明写「已用规则引擎兜底」而 `is_fallback=False/llm_layer_ok=True/quality=full` | 🆕 待拍板 |
| 9 | **R187（P3，新）**：`UnifiedAnalysis.vue:107` 无守卫 `metadata.value` → vitest 9 个 Unhandled Rejection（551 绿但噪音，7f4a23c 引入） | 🆕 待拍板 |
| 10 | **R188（P3，新）**：`test_fetch_market_data_success_still_works` 在 `-n auto` 下偶发 FAIL（SourceRegistry 全局熔断跨用例污染，单跑绿） | 🆕 待拍板 |
| 11 | **性能债增量**：`/admin/factor-health` 6.22s（>2s 阈值，round53 为 1.41s；周末数据源慢 + 候选池 37 只全量计算） | ⚠️ 登记 |
| 12 | **data_health_check 宿主跑 >5min 未完成**：Sina K-line HTTP 456（周末限流）+ 全池 fetch_history 逐只失败拖慢，无单项超时熔断 | ⚠️ 观察（环境性为主） |
| 13 | **verify_e2e 部分跑**：124 PASS / 2 FAIL（①TCP ::1 硬编码在 Docker Desktop NAT 下不可达，环境性；②策略检查 120s 窗口周末不够，task 61 随后 completed） | ⚠️ 环境性 |
| 14 | **pytest 全量**：3222 passed / 1 failed（R188 同项）/ 11 skipped，294s | ✅（除 R188） |
| 15 | **vitest**：44 文件 551 passed（R187 噪音另计） | ✅（除 R187） |
| 16 | **冗余评审落地核验**：P1-1（safe_call 零残留）/ P1-4 / P2-3（main.py 1289→874 行）维持；**allocation_engine.py 1721→1870 行**（P1-5 未启动，继续膨胀） | ⚠️ P1-5 加急信号 |
| 17 | **R190（P2，新，设计附录 §7）**：LLM 免费层 Zen 全灭/b_ai 余额 0/OpenRouter 唯一可用，`route()` + 三表重设计方案入档 | 🆕 待拍板 |

### 0.2 遗留清单（承接 round53 §6 + §8.4/§10.4/§11.3）

| round53 遗留/小批 | 本轮状态 |
|---|---|
| R146/R173-A 盘中复测 | ✅ round53 §12 已闭环，本轮周末不复测，维持关闭 |
| off_exchange check 触发 | ⏳ 维持（本轮 task 56 用默认组合，off_exchange 仍未触发） |
| R174 浏览器四态走查 | ⏳ 维持（本轮新增 round54 UI 改动，四态走查范围扩大，见 §6#5） |
| R179/R180 暂缓登记 | 📋 本轮实测存续，维持暂缓 |
| R185-C 徽章（P3） | ⏳ 维持暂缓 |
| P1-5 allocation_engine 拆分 | ⏳ 未启动且文件 +149 行，见 §6#4 |
| R182/R183/R184/R185-A/B、data_health_check 口径、R181-C、LLM 多轮 | ✅ 本轮生产口径抽验无回归（§2） |

---

## 1. 环境构建与启动（阶段 1）

- Docker Desktop daemon 初始未运行（`com.docker.service` Stopped），手动拉起后正常。构建 21:37:42→21:43:51（约 6min，round53 时前端 base 拉取 1351s，本轮层缓存命中）。
- 构建日志 `build54.log`：`Image etf_surge-backend Built` + `Image etf_surge-frontend Built`；pip resolver ERROR 0 条；apt 故障 0 条。
- 三容器 21:43 起 Up：backend :8000、frontend :80、redis :6379，全程无重启。
- warmup 36.8s（>30s 预算 → R170 新告警触发，分段 top3: instruments_sync 25.2s / indices_meta_sync 11.5s / etf_cache 0.1s；与 round53 的 25.4/10.1/0.2 同构）；**旧格式 `Warmup took 37.0s` 同次输出**（R179 存续实证）。
- `indices_meta` 1106 行（与 round53 一致）；IC 启动恢复 24 条；lifespan-warmup `redis_available=true`；nav-warmup cycle=1 `pool_empty`（周末无持仓池预热，诚实标注）。
- 前置：`backend/.env` 含 DEEPSEEK_API_KEY / OPENCODE_ZEN_API_KEY / OPENROUTER_API_KEY（LLM 链路可跑；本轮 openrouter 502 属 provider 生态，非配置缺失）。
- 宿主代理坑：`HTTP_PROXY=http://127.0.0.1:7897` 常驻；WS 探针初次 3/3 握手超时系代理吞噬，`proxy=None` 直连后全通（模板 §环境步骤6 再验证）。

## 2. 全链路诊断 + 对照验证（阶段 2）

### 2.1 端点健康与性能（周末）

| 路径 | 本轮 | round53 | 阈值 | 判定 |
|---|---|---|---|---|
| /health（根路径） | 200 | 200 | — | ✅ |
| nginx / | 200 / 0.21s | 200 / 0.23s | — | ✅ |
| /market/realtime/portfolio | 200 / 1.54s，38 条，0 价 0 只、0 涨跌 0 只 | —（R173 盘后形态） | ≤3s | ✅（周末形态：15 nav + 23 实时） |
| /admin/factor-health | 200 / **6.22s**，symbols 24-25/39 healthy | 1.41s | ≤2s | ⚠️ 退化登记（§2.5） |
| /admin/llm/health | 200 / 17.1s | 19.0s | — | ⚠️ 性能债维持（略好转） |
| /market/sectors/heat | 200 / 2.69s | 2.25s | — | ✅ 维持 |
| /factors/active | 38 条 / zero_ratio_scope=ic_batch / no_data=6 / static=12 / warn=20 | 同口径 | — | ✅ R166 口径保持 |
| WS 直连 :8000 三链路 | 握手 OK（news 快照 622B / portfolio 38B / task-notifications 无快照但握手 OK） | 101 OK | — | ✅ |
| WS 经 nginx :80 三链路 | 握手 101 OK | 101 OK | — | ✅ |

### 2.2 主动触发新数据验证

1. `POST /portfolio/design-async`（balanced, 500000, enhanced）→ task 55 completed → **design 34** 入库（report_quality=full，31 etf_count，text 8059 字）。
2. `POST /portfolio/strategy-check-async`（默认空体）→ task 56 completed → **check 108** 入库（report 8833 字；flag 矛盾见 R186）。

### 2.3 design 34 层预算 + 结构五问复验（R162/R163/R181 维持）

- 三方案 Σ=1.0000（含 CASH 行），现金 25/23/15%，单只最大 0.20 ≤ 30% ✅。
- **结构五问**：防御（510300 沪深300 + 159338 中证A500 + 512890 红利低波 + 510050 上证50…）、平衡（+588000 科创50 +510500 中证500…）、进攻（+159915 创业板 +510500…）——**同方案内 normalize 层面无同指数重复，563360 未出现** ✅ R181 无复发。
- market_context：regime=range_bound、session=closed、factor_data_quality.degraded=True（38/193 可用，诚实降级标注）✅。

### 2.4 check 108 内容复验（R171 + R186）

- report 正文 15 只逐标的因子/信号/建议表，因子分真实离散值（0.09/-0.02/0.44/-0.05/-0.79/0.17…0.93/0.95），非占位 ✅。
- summary 全文（c108_summary.txt）：`LLM 网关返回错误信封（30s，已用规则引擎兜底）（最后错误: [envelope] openrouter/nvidia/nemotron-3-ultra-550b-a55b:free: Upstream error from Nvidia: Service temporarily overloaded (code=502)）（市态：震荡；因子覆盖 33.3%）`。
- **矛盾**：`is_fallback=False / llm_layer_ok=True / report_quality=full`（DB 实读）——见 R186。
- regime=range_bound，与 design 34 一致 ✅；因子覆盖 33.3%（周末 5/15）诚实 ✅。

### 2.5 R177/R178 深探（维持）

- `keyword=创新药 kind=sector` → 1 条 BK1106 ✅；`keyword=红利 kind=index` → 19 条 ✅；`kind=all` → 13 条 ✅。
- news/all 27 = headlines 15 + macro 4 + global 8 精确闭合 ✅（macro 3→4 为内容增量，非口径漂移）。
- 空 keyword `kind=all` → 30 条（R180 存续，与暂缓登记一致）。

### 2.6 数据源健康（data_health_check 宿主跑，未完成）

- 第 1 节：Sina 实时 ✅，**Sina K-line FAIL（HTTP Error 456，周末限流）**。
- 第 2 节卡死：全池 `fetch_history failed … too few data points: 0` 逐只刷屏（617 行），>5min 无汇总输出，进程超时终止。检查器对「全源周末不可达」无单项超时/熔断，属检查器鲁棒性缺口（环境性触发，见 §4.2 映射）。

### 2.7 对照验证矩阵（round53 §0.1/§6/§7/§8 + redundant-review 行动清单）

| round 项 | round53 预期 | 本轮实测 | 结论 | 证据 |
|---|---|---|---|---|
| R170 warmup 归因 | 新告警生效 | 36.8s 新告警 + 分段 top3 同构 | PASS（维持） | backend log 21:44:31 |
| R171 holdings 市值 | 15/15 非空自洽 | check 108 正文 15 只因子表（holdings_analysis 结构字段为空，检查默认组合无持仓快照） | PASS（维持，形态说明见注） | c108.json report_text |
| R173 off 估值 | nav change_pct 非 0 | 周末 15 nav + 23 实时，0 涨跌 0 只 | PASS（周末形态） | rt54.json |
| R176 0 价 | 0 只 | zero_price=0 | PASS | rt54.json |
| R177 搜索 | 三缺口命中 | BK1106 / 19 / 13 | PASS | s_sec/idx/all.json |
| R178 news/all | 闭合 | 27=15+4+8 | PASS | newsall54.json |
| R179 双告警 | 暂缓登记 | 双告警存续 | 不适用（维持暂缓） | backend log |
| R180 空 kw | 暂缓登记 | 30 条存续 | 不适用（维持暂缓） | s_empty.json |
| R181 去重 | 方案 C 落地 | design 34 零重复 | PASS（维持） | d34.json |
| R182/R184 文案分流 | 落地 | （容器 API 层无回归；浏览器级走查留 §6#5） | PASS（API 层） | factive reasons 6/6 积累中分支 |
| R183 交易日历 | 落地 | 9-06→9-12 非交易日无灌水（ln_float_mcap 仅 +1，内为交易日积累） | PASS（维持） | fa2.json |
| DHC 口径修复 | 落地 | 生产路径 7/7（§2.1 factor-health symbols healthy）；检查器自身周末 >5min 未完成（新缺口见 §4.2） | PASS（生产侧）/ 检查器鲁棒性新缺口 | fh54.json / dhc54.out |
| R185-A/B 热生效+清单 | 落地 | lifespan-warmup redis ok；配置页未做浏览器走查 | PASS（后端侧） | lifespan-warmup |
| LLM 多轮 1+2 | 落地 | （本轮未做会话级功能走查，单测 21+14 在位；走查并入 §6#5） | 不适用（待走查） | — |
| redundant P1-1 | safe_call 删除 | 全仓零命中 | PASS | grep |
| redundant P1-2 | 桥接抽取 | （代码在位，未复测探针） | PASS（维持） | — |
| redundant P1-3 | e2e 精简 | 2633→**2477 行**（继续下沉） | PASS（方向维持） | 行数实测 |
| redundant P1-4 | 测试合并 | pytest 3222（+6 vs 3216） | PASS | pytest54.out |
| redundant P1-5 | allocation 拆分 | **未启动，1721→1870 行（+149）** | FAIL（债务扩大） | 行数实测 |
| redundant P2-3 | main 抽 startup | main.py 1289→**874 行** | PASS（超预期） | 行数实测 |
| redundant P2-4 | 凭据合一 | （本轮未触门禁） | 不适用 | — |

注：R171「holdings 15/15」在本轮 check 108 为报告正文表（holdings_analysis 结构空——默认空体触发的检查无持仓快照，属触发方式差异非回归；R171 字段逻辑本身未动）。

### 2.8 已知性能债登记（软门禁，增量）

| 路径 | 本轮 | round53 | 阈值 | 处置 |
|---|---|---|---|---|
| /admin/factor-health | **6.22s** | 1.41s | ≤2s | ⚠️ 新登记（周末慢源 + 37 只全量；交易时段复测确认是否常态退化） |
| /admin/llm/health | 17.1s | 19.0s | — | ⚠️ 维持登记 |
| patrol --full | 未跑 | 未跑（§6#4 已改规则） | — | 按新规则：下次代码变更交付时跑（见 §6#3） |
| data_health_check 宿主全量 | >5min 未完成 | 11/12（盘后） | — | ⚠️ 新登记（检查器无单项超时，见 §4.2） |

### 2.9 回归基线

- `verify_e2e --host 127.0.0.1`：124 PASS / 2 FAIL（§2.7/§4.1 环境性归因；task 61 随后 completed 证 120s 窗口系周末性不足）。注：脚本默认 `BASE=http://[::1]:8000` 在 Docker Desktop Windows NAT 下 TCP 不可达，须显式 `--host 127.0.0.1`（新发现的环境适配项，见 §4.1 R189）。
- 后端 pytest `-n auto`：3222 passed / 1 failed（R188）/ 11 skipped，294.88s。
- 前端 vitest：44 文件 551 passed，7.25s（+9 Unhandled Rejection 见 R187）；容器前端镜像构建成功 = 编译门禁过。

---

## 3. 分析结果质量审查（阶段 3 · 四问法 + 结构五问）

对象：design 34（三方案正文，8059 字，LLM 层成功 quality=full）与 check 108（规则兜底正文，8833 字）。

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 结论分级 | 修复建议 |
|---|---|---|---|---|---|
| design34「现金 25/23/10→25/23/15%」 | 事实 | strategies_json Σ=1.0，CASH 行 0.25/0.2298/0.15 与总览表一致 | ✅（ session=closed，周末现金偏高合理） | 合理 | — |
| design34 防御型 ETF 表（RSI 35.7/MACD 空头/动量 -0.052 等） | 事实 | 逐项具体离散值，非占位（RSI≠50.0、动量≠+0.300）；综合信号 +0.19/+0.23 等 | ✅ | 合理 | — |
| design34「当前预期年化与预期年化一致——震荡市态调整系数为 0」 | 推断→事实化 | 自带调整依据（市态=range_bound，market_context 实读一致） | ✅ | 合理 | — |
| design34 511090「综合信号 -1.97 为负，作防御层配置需谨慎」 | 推断 | 自带结构提示脚注，负信号防御标的如实警示 | ✅（诚实标注优于静默配置） | 合理 | — |
| check108「市态：震荡」 | 事实 | market_regime=range_bound；design 34 同值交叉一致 | ✅ | 合理 | — |
| check108「因子覆盖 33.3%」 | 事实 | 周末部分可用（5/15）；summary 与正文一致 | ✅（诚实降级） | 合理 | — |
| check108 逐标的因子分（0.44/-0.79/0.93/0.95…） | 事实 | 离散真实值；report_text 表格实读 | ✅ | 合理 | — |
| check108 逐标的建议（大面积「维持现状…RSI…<30…不追高杀跌」） | 推断（规则模板） | 模板复读 across 15 行，信息量低但与「规则引擎兜底」自洽 | ✅（形态诚实，旗语不诚实） | 部分合理 | R186 修旗语后，模板建议应标「规则建议」前缀 |
| check108 `is_fallback=False/quality=full` | 事实（DB 值） | 与 summary「已用规则引擎兜底」直接矛盾 | —（内部矛盾） | **不合理（R186，P2）** | §4.1 方案 A |
| design34 结构五问（三方案同指数重复） | 事实 | 33 持仓行逐方案分组查重，0 重复；563360 未出现 | —（结构维度） | 合理（R181 无复发） | — |

**汇总**：可采信 8 条 / 需修正 1 条（建议模板标注）/ 臆断 0 条 / 失效 0 条；**不合理 1 条**（R186 旗语矛盾）。
**数据准确性抽查**：Σ=1−现金 ✓✓✓；target_amount 口径（strategies_json weight/amt 一致，design 34 沿用）✓；占位检测（RSI 50.0/动量 +0.300/ln_mcap 0.0）未出现 ✓；as_of/session=closed 周末诚实 ✓；regime 双端一致 ✓。

---

## 4. 问题分析与修复方案（阶段 4，只写方案不写代码）

### 4.1 R 系列新发现（本轮 R186/R187/R188 + R189 环境项）

| 编号 | 发现 | 根因机制链（file:line） | 严重度 |
|---|---|---|---|
| R186 | **envelope 类 LLM 兜底绕过 F1-9 识别，旗语与正文矛盾**：check 108 summary=`LLM 网关返回错误信封（30s，已用规则引擎兜底）…502…因子覆盖 33.3%`，而 DB `is_fallback=False/llm_layer_ok=True/report_quality=full`。round24 R5「结构化兜底标识」对此类失效；前端「LLM 层降级」徽章不显示；quality 口径污染（full 含兜底） | `reports.py:24-41` `_classify_llm_failure_cause` 新增第 1 分支（round51 R164）产出 `LLM 网关返回错误信封…` 前缀 → `strategy_check.py:319-325` F1-9 兜底识别仅匹配 3 前缀（`LLM 分析超时/配额耗尽/解析失败`），envelope 前缀漏网 → `_llm_failed` 保持 False → `:669-671` 旗语全绿。机制类：「分类器新增分支，识别器未同步」（R163/R177 同型：写入口径与消费口径无一致性断言） | P2（旗语错误：用户与监控看到 full，实际为规则兜底；内容本身诚实，故非 P1） |
| R187 | **vitest 9 个 Unhandled Rejection**：`UnifiedAnalysis.vue:107` `const m = metadata.value` 无守卫；单测 mock 的 useLLMStream 未提供 metadata → computed 求值抛 `Cannot read properties of undefined`。551 用例仍绿（错误在渲染后抛，不挂断言），但污染门禁输出可信度 | `UnifiedAnalysis.vue:105-109`（7f4a23c「模型名展示」引入：`modelLine = computed(() => metadata.value…)`）；`UnifiedAnalysis.spec.js` mock 缺 metadata 键。生产暂安全（hook 恒返 metadata ref），属测试卫生 + 脆弱点 | P3 |
| R188 | **pytest `-n auto` 下 `test_fetch_market_data_success_still_works` 偶发 FAIL**：`KeyError: 'close'`；日志 `SourceRegistry circuit open for factor.history → returning empty data`。同 worker 内先行用例熔断了全局 factor.history → 本用例空数据。单文件跑 3/3 绿 | `factor_registry.py:1307` 熔断返回空 + `SourceRegistry` 进程级单例跨用例共享；`test_factor_registry_gather_timeout.py:68-72` 断言未考虑熔断态。pre-commit 全量用 `-n auto`，此 flake 可随机咬门禁 | P3 |
| R189 | **verify_e2e 默认 `BASE=http://[::1]:8000` 在 Docker Desktop Windows NAT 下 TCP 不可达**：本轮 e2e 首跑即 `[FAIL] TCP 端口 8000 可达 (::1)`；`--host 127.0.0.1` 后续跑 124 PASS。容器端口映射 `0.0.0.0:8000` 本身正常 | `verify_e2e.py:89` 硬编码 `[::1]`（round36 O21 钉死）；Docker Desktop NAT v6 回环不通（环境适配债）。AGENTS.md「verify_e2e 依赖 ::1 监听」假设在本机直跑成立、容器诊断不成立 | P3（环境适配，非产品缺陷） |

### 4.2 测试防护体系缺口分析

**1) 防护体系现状（本轮实测）**：pytest 3222 绿（-n auto，294s）/ vitest 551 绿（+9 未处理 rejection）/ e2e 部分 124 PASS / 容器构建双镜像成功。缺口集中在**旗语层**与**门禁自身鲁棒性**。

**2) 逐发现映射**：

| 发现 | 最应拦截的防护层 | 为何未识别 | 应补的守卫 |
|---|---|---|---|
| R186 | strategy_check 单测（兜底识别） | F1-9 识别器的 3 前缀断言写死；round51 R164 在 reports.py 新增第 4 前缀时无「识别器同步」测试 | 单测：envelope 文案（`LLM 网关返回错误信封…`）输入 → `_llm_failed=True` 且 `is_fallback=True/quality=fallback`；负向：现有 3 前缀维持 + 第 4 前缀必 FAIL（旧实现必红） |
| R186（结构） | 契约/一致性门禁 | 兜底文案前缀无单一事实源（reports.py 与 strategy_check.py 各写一份字符串） | 长治：前缀常量收敛到一处（如 `core/llm_fallback_prefixes.py`），两边同引；check_routes 式「写入口径与消费口径一致」断言 |
| R187 | 前端单测 | spec mock 形状与 hook 实际返回不一致（缺 metadata）；computed 无 `?.` 防御 | spec 补 metadata 缺失形态 + 组件侧 `metadata?.value`；负向：mock 去 metadata 时旧实现必抛 rejection |
| R188 | pytest 并行隔离 | 全局 SourceRegistry 熔断跨用例；单测未隔离熔断器状态 | 用例级 fixture：进出重置 factor.history 熔断（或 mock 熔断器）；负向：先强制熔断再跑本用例，旧实现必 FAIL |
| DHC >5min | data_health_check 自身 | 全池逐 symbol fetch 无单项超时/总数预算；周末全源慢时检查器先于被检挂掉 | 检查器加单项超时（如 15s/symbol）+ 总预算 + 超时诚实记 WARN（防「门禁先挂」掩盖真实结论） |
| e2e ::1 | verify_e2e 自身 | BASE 硬编码；容器诊断拓扑与本机直跑不同 | 启动段先做可达性自检（::1 不通自动回落 127.0.0.1 并标注，不记 FAIL） |

**3) 系统性根因归并**：
①「分类器新增分支、识别器未同步」（R186；round51 R163/R177/§4.2① 同型再现，本轮新实例——**round2/3 已归纳未收敛**：写入口径与消费口径无一致性断言仍在漏）；
②「门禁自身无超时/回落」（DHC、e2e ::1；新出现——门禁脚本把环境最优态当不变量）；
③「全局单例跨用例污染」（R188；新出现于并行维度——-n auto 放大）；
④「前端 mock 与 hook 形状漂移」（R187；§4.2 已有「前端 mock 掩盖真实契约」类再现）。
总体评价：防护体系缺的不是「更多断言」，而是「**口径一致性**（字符串前缀两处手写）+ **门禁自身鲁棒性**（超时/回落/隔离）」两层。

**4) 补齐设计（只写方案，不写代码）**：

- **方案 A（P2，R186）**：`strategy_check.py:320-325` 前缀元组追加 `"LLM 网关返回错误信封"`（1 行）；单测 2 用例（envelope 文案 → fallback 三旗语；回归旧 3 前缀）。验收负向：check 108 同形态复现时 `is_fallback=True/quality=fallback`；旧实现跑新用例必 FAIL。影响范围：`strategy_check.py:319-325` + 1 测试文件。
- **方案 B（P2，R186 长治，推荐同批）**：抽 `core/llm_fallback_prefixes.py`（FALLBACK_PREFIXES 元组），reports.py 分类器与 strategy_check 识别器同引；加一致性单测（分类器全分支输出前缀 ∈ FALLBACK_PREFIXES）。验收：任一新增文案分支不同步必红。
- **方案 C（P3，R187）**：`UnifiedAnalysis.vue:107` 改 `metadata?.value`（+ `|| ''` 兜底已在下行）；spec mock 补无 metadata 形态。验收负向：去 metadata mock 下旧实现 9 rejection复现、新实现 0。
- **方案 D（P3，R188）**：`test_factor_registry_gather_timeout.py` 加 autouse fixture 重置 SourceRegistry 熔断（或 monkeypatch 熔断器为闭合）；验收：`-n auto` 全量重跑本文件所在 worker 不 FAIL。
- **方案 E（P3，R189 + DHC）**：verify_e2e 启动段可达性自检回落（::1→127.0.0.1，标注不记 FAIL）；data_health_check symbol 级 `wait_for(15s)` + 总预算 + 超时记 WARN。验收负向：周末重跑 DHC 必出汇总（不再无输出挂死）。

### 4.3 与 round53/round54 文档的关系

- round53 §0.1 全部修复结论本轮维持（R181/R177/R178/R173/R146 盘中结论沿用 §12；R174/R185-C/off_exchange 维持未决）。
- round53 §8.4/§10.4/§11.3 小批：后端侧无回归；LLM 多轮会话未做功能走查（§6#5）。
- round54 前端抛光：容器构建成功 + vitest 551 绿；R187 为该批引入的唯一噪音；四态走查并入 §6#5。
- redundant-review：P1-5 未启动且 +149 行（§6#4）；其余 P1/P2 维持。

---

## 5. 三轮 Review 记录（阶段 5）

### 5.1 Round 1 — 事实核对

| 项 | 核对 | 结论 |
|---|---|---|
| 构建双镜像成功 | build54.log `Built` ×2 + `docker compose ps` 三 Up | ✅ |
| 双 warmup 告警 | backend log 21:44:31 两条原文（36.8s 新格式 + 37.0s 旧格式） | ✅ |
| R177 三组 | s_sec=BK1106 / s_idx=19 / s_all=13 实读 | ✅ |
| R178 闭合 | 27=15+4+8（nh/nm/ng/all 四文件） | ✅ |
| realtime 周末 | 38 条 / 0 价 0 只 / 0 涨跌 0 只 / nav=15 | ✅ |
| design 34 | Σ=1.0×3 / max 0.2 / 零同指数重复 / regime 一致 | ✅ |
| check 108 矛盾 | summary 全文 183 字 + DB 三旗语实读 | ✅ |
| R186 机制链 | reports.py:24-41 × strategy_check.py:319-325/669-671 实读 | ✅ |
| R187 | vitest54.out 9 rejection + UnifiedAnalysis.vue:107 + 7f4a23c | ✅ |
| R188 | pytest54.out FAIL 行 + 单文件 3 passed 复核 | ✅ |
| e2e 124/2 | e2b.out 计数 + task 61 completed 后验证 | ✅ |
| pytest 3222/1 | pytest54.out 尾行 | ✅ |
| vitest 551 | vitest54.out 尾行 | ✅ |
| 行数三项 | allocation 1870 / e2e 2477 / main 874（实测） | ✅ |
| safe_call 零命中 | grep 空 | ✅ |

### 5.2 Round 2 — 逻辑一致性

- R186「内容诚实、旗语不诚实」与四问法「部分合理/不合理」分级自洽：正文规则表可采信，DB 旗语不可采信——两者分离标注，不矛盾 ✅。
- check 108 `llm_layer_ok=True` 与 openrouter 502 不矛盾：True 是 bug（漏识别）的输出，不是「LLM 真成功」——§4.1 已定性 ✅。
- e2e task 61「120s FAIL」与随后 completed 不矛盾：窗口不足（周末慢）vs 最终成功，两层事实并存 ✅。
- factor-health 6.22s vs round53 1.41s：样本/数据源周末慢 + 候选池全量，非口径变化；记退化待交易时段复测，不定性为回归 ✅。
- DHC「>5min 未完成」与 round53「11/12」不矛盾：宿主跑 + 周末 Sina 456 + 全池逐只失败放大；容器内生产路径（factor-health symbols healthy）正常 ✅。

### 5.3 Round 3 — 完整性

- 验证窗口标注：全部实时/行情结论标周末形态；R146/R173-A 盘中结论明确沿用 round53 §12、不复测 ✅。
- 未复测诚实标注：R174 + round54 四态 + LLM 多轮走查（§6#5）、patrol --full（§6#3）、Lighthouse（§6#6）✅。
- 未决项清单：R186/R187/R188/R189 拍板（§6#1/#2）、R190 重设计拍板（§7）、factor-health 复测（§6#7）、P1-5（§6#4）✅。
- 诊断合规性：全程未写修复代码（唯一产物=本文档 + 会话级探针不入仓）✅。

**结论**：三轮 review 通过，文档达到「方案轮定稿」标准。

---

## 6. 决策点（#1 已拍板，其余待定）

> **拍板结果（2026-09-12）**：#1 采纳推荐——方案 A+B 同批（1 行前缀 + 前缀常量收敛 + 3 用例），未收到「round实施」不动代码。
> 拍板后收尾：① 本节已回填；② memory 同名事实随状态更新。

| # | 决策 | 选项 + 推荐 + 影响范围 | 状态 |
|---|---|---|---|
| 1 | R186 envelope 兜底识别 | **已拍板：方案 A+B 同批**（A：`strategy_check.py:319-325` 追加 `"LLM 网关返回错误信封"` 前缀 + 2 用例；B：新建 `core/llm_fallback_prefixes.py`，reports.py 分类器与 strategy_check 识别器同引 + 一致性单测）。备选（仅 A）未采纳——省几分钟但留第四次复发口子（三现同型：R163→R177→R186）。影响 `strategy_check.py:319-325`、`reports.py:24-41`、新建 `core/llm_fallback_prefixes.py` + 3 用例 | ✅ 已实施（本批 commit，见 §8） |
| 2 | R187/R188/R189 + DHC/E2E 鲁棒 | **已拍板并实施：方案 C′+D′+E′**（本轮 review 修订后定稿：C′ 扩到 3 vue 同型 + 缺键形态锁定；D′ 落 `test_factor_registry_gather_timeout.py` autouse 复位 + 开路负向；E′ 抄 R172 回落 + TCP-INFO + DHC 单项 180s/总量 600s WARN 恒汇总）。影响 3 vue + 1 spec + 1 pytest 文件 + 2 脚本 | ✅ 已实施（本批 commit，见 §8） |
| 3 | patrol --full | round53 §6#4 规则「下次代码变更交付时跑」——本轮后 HEAD 已含前端抛光 + 对话追问后端变更，**下次实施轮交付时照常跑**，本轮不补跑 | 📋 按规则执行 |
| 4 | P1-5 allocation 拆分 | 文件实测 **2156 行**（文档原记 1870 已过时，+435 vs 1721 基线；顶层 30 def）。**独立 round**（redundant-review 原定），不与 P2/P3 小批混批 | ⏳ 待排期（独立 round，须先出完整迁移图） |
| 5 | 浏览器四态走查 | R174 + round54 抛光页 + LLM 多轮会话 + R182/R184 文案分流，合并为一次 UI 走查专项（需交易时段 + 真浏览器） | ⏳ 待排期 |
| 6 | Lighthouse | 本轮未执行（容器内无 Chrome/预算）。明确登记遗留，下轮与 #5 合批或单独跑 | 📋 遗留登记 |
| 7 | factor-health 6.22s | 交易时段复测：若回落 ≤2s 则销账（周末性）；若维持则按性能债排期优化 | ⏳ 待复测 |

> 拍板后固定收尾：① 拍板结果回填本节；② memory 同 name 覆盖更新（勿新建重复条目）。

---

*诊断产物：C:/Users/Public/etf_probe/（build54.log + rt/d34/c108/fh/newsall/dhc/e2e/pytest/vitest + c108_summary.txt，会话级临时目录）；容器诊断完成后回收。未收到「round实施」不写修复代码。*

---

## 7. LLM 链路重设计（R190，设计附录，非诊断发现）

> 来源：资讯 `ai_summary` 全 rule 现象深挖（2026-09-12 夜间，宿主实测）→ 独立于容器诊断的 LLM 可用性专项。
> 状态：⏳ 独立 round 待排期（本轮 review：文档锚点 `provider.py:73-77` 已漂移——该文件不存在，
> 已拆为 `client.py`/`gates.py`/`model_catalog.py`；`zen_attempt_sequence` 实为
> `model_catalog.py:221`，`_filter_*` 在 `112/122`，`is_middle_layer_active` 在
> `gates.py:272`，`skip_llm` 在 `hub/_news.py:77-83`。实施前按新锚点重定位 + 分 3 期，
> 一期复用 R186 的 `core/llm_fallback_prefixes.py` 常量）。
> 与既有决策关系：R186（envelope 识别）是本节机制 1（DEAD 终态）的特例先行，两者同批实施不冲突。

### 7.1 实测证据链（宿主，token_usage.db + 直调探针）

| # | 事实 | 证据 |
|---|---|---|
| 1 | 近 24h 全函数口径：openrouter 187 ok / 74 fail，zen 146 fail / 0 ok，**deepseek 0 调用，b_ai 0 调用** | `data/token_usage.db` group by provider（探针脚本会话级临时目录，不入仓） |
| 2 | Zen 免费层全灭：`deepseek-v4-flash-free` → 400 "Model is unavailable"（上游下架、目录残留）；ling/mimo/nemotron×2 → 400 "free tier can only be used in OpenCode"（免费仅限 IDE） | `scripts/probe_zen_model_list.py` + 补探（生产同款 body，各 1 次） |
| 3 | OpenRouter 可用：免费池 22 个，`cohere/north-mini-code:free` 实测 200 OK；但生产池按参数降序首选 `nvidia/nemotron-3-ultra`，正撞 Nvidia 上游 502 | 补探 + `backend.log` 21:30 `[envelope] ... Upstream error from Nvidia (code=502)` |
| 4 | b.ai：`deepseek-v4-flash` → 400 `insufficient_user_quota, balance=0`（账号级，与模型无关）；`qwen3.8-flash` → **200 OK**（"全系不可用"结论已订正） | 补探各 1 次 |
| 5 | 付费 DeepSeek key 有效（`.env` SET），24h 零调用 | 同表 1 |

### 7.2 五个结构问题（非补丁能解）

1. **发现 ≠ 健康**：目录 600s 刷新只解决"有什么"，健康全靠调用撞墙；列表端点撒谎（下架模型照常广告）时"动态"建立在假输入上。
2. **状态全在内存**：排除表/熔断/skip 标记重启归零，死模型每 boot 复活（134 次 Zen 400 的来源之一）。
3. **排除逻辑散装三处**：`zen_attempt_sequence` 只查熔断不查排除表（`provider.py:73-77`）、`_b_ai_candidates` 查、`_filter_*` 刷新时查 —— 互相打架。
4. **`skip_llm` 变质**：原假设"Zen 偶发溢出"，Zen 永久死亡后中间层标记常驻 → 后台摘要**按设计**永久 rule（`hub/_news.py:74-83`）。
5. **花钱无决策**：`insufficient_user_quota` 的 400 形态不在永久错误 pattern 内（仅配了 403 + `credit insufficient`，`gates.py:20-24`），b.ai 半开复探永动机；且路由无"免费全灭是否花钱"策略，DeepSeek 默认永不启用。

### 7.3 重设计：`route()` + 三张表

调用方只声明意图（`task=interactive|background, quality_floor, max_cost`），不再点名模型：

| 表 | 内容 | 持久化 | 更新者 |
|---|---|---|---|
| Capability（有什么） | 目录列表 + 白名单 | 内存 + 600s 刷新（现状保留） | catalog refresh |
| Health（哪个能用） | per-(provider,model)：CLOSED/OPEN/**DEAD** + 失败计数 + last_probe | **DB 持久化**，重启不丢 | 调用回写 + 定时微探针 |
| Policy（什么任务用什么） | interactive：免费优先→预算内可用付费；background：默认仅免费，streak 超限可升级 | 代码配置 | 人 |

四机制：① **DEAD 是终态**（永久错误 → DB，不再 5min 复探；仅 admin/目录版本变化复活）；② **微探针**（每 N 分钟池顶 1~2 候选最小 chat，`max_tokens=8`，目录只管上新、探针管下架）；③ **花钱显式化**（`paid_daily_cap` + 调用打标 `paid=true` 进 token 表）；④ **决策可观测**（每次 `route()` 一条 debug：选谁、跳过谁及原因）。

`skip_llm` 删除：后台任务调 `route(max_cost=0)`，无免费可用直接返回 `NO_CANDIDATE` 落 rule —— 语义等价但每次重估，无常驻 true。

### 7.4 落地节奏（与 R186 同批不冲突）

1. `route()` 外壳 + 三张表 + 决策日志，行为与现状 1:1（纯搬运）；
2. DEAD 持久化 + 微探针 + 花钱策略逐个打开（小 diff + 单测；含：`zen_attempt_sequence` 查排除表、自动排除写穿 DB、pattern 加 `400+insufficient_user_quota`、`max_retries 0→1`、rule 超 3 轮 deepseek 回填）；
3. 配置动作（不改代码）：B 白名单去 deepseek 留 qwen；admin 排除 OR 的 nvidia-550b；b.ai 充值（账单动作）；
4. 重启后看 1 小时 `by_provider` 闭环（b.ai+qwen 被走到、Zen 零复探）。

> 拍板后固定收尾：① 本节状态改已拍板；② memory 同 name 覆盖更新。

---

## 8. 本批实施记录（2026-09-13，R186 A+B + C′+D′+E′）

> 范围：§6#1（已拍板）+ §6#2（本轮 review 修订 C′/D′/E′ 后拍板定稿）；P1-5/R190/round54 走查按下述登记不动代码。

### 8.1 改动清单

| 项 | 文件 | 改动 |
|---|---|---|
| R186-B | `backend/app/core/llm_fallback_prefixes.py`（新建） | FALLBACK_PREFIXES（4 前缀）+ `is_llm_fallback_summary()`，零依赖 |
| R186-B | `backend/app/analysis/llm/reports.py:14-18,34-41` | 分类器 4 分支改由常量构造（字符串逐字一致，无行为变化） |
| R186-A | `backend/app/services/portfolio/strategy_check.py:13,315-325` | F1-9 识别改走 helper（含 envelope）；三旗语（669-671）同源修复 |
| R186 测试 | `backend/tests/test_round51_llm_envelope.py`（+3 用例） | envelope 识别 + 旧 3 前缀回归 + 分类器输出 ∈ 常量集（含接线守卫） |
| C′ | `frontend/.../UnifiedAnalysis.vue:107`、`MarketReport.vue:68`、`AiAdvisor.vue:67,113` | `metadata?.value` 三处同型 + resetChat 守卫 |
| C′测试 | `frontend/src/test/UnifiedAnalysis.spec.js`（+1 用例） | 缺键形态锁定（旧实现必抛 `Cannot read properties of undefined`，已负向实证） |
| D′ | `backend/tests/test_factor_registry_gather_timeout.py` | autouse 熔断复位 + 开路→空→复位→恢复负向用例 |
| E′ | `backend/scripts/verify_e2e.py` | `_resolve_e2e_host`（R172 同款回落）+ TCP 未命中记 INFO；显式 `--host` 不受影响 |
| E′ | `backend/scripts/data_health_check.py` | 单项 180s/总量 600s + 超时记 WARN + try/finally 恒出汇总 |

### 8.2 验证

- 受影响 pytest：164 passed（含 strategy_check 全家桶 4 文件）；mypy 门禁口径 146 文件 clean
- 全量一次：pytest `-n auto` **3227 passed / 11 skipped / 0 failed**（round55 基线 3222/1 → R188 旧 FAIL 消除 +4 新用例），随后 `tests_ok_marker --mark`
- vitest 全量：44 文件 **552 passed，0 Unhandled Rejection**（round55 基线 551 + 9 rejection → 噪音消除 +1 新用例）；`npm run build` 绿
- 运行时：宿主后端 + `verify_e2e --smoke` **21/21 ALL PASS**；DHC 超时路径合成验证（budget=2s 必 WARN 不挂死）；`_resolve_e2e_host` 闭端口回落验证
- R186 验收口径：check108 同形态 summary → `is_llm_fallback_summary=True`（经 helper 单测 + 接线守卫；生产复现待下次 envelope 触发时观察）
- R187 验收口径：去 metadata mock 下旧实现复现抛错、新实现 0 rejection ✅
- R188 验收口径：开路→空→复位→恢复因果链单测 ✅（`-n auto` 全量本轮未复发）
- R189/E 验收口径：闭端口回落默认/显式 `--host` 直通 ✅；DHC 恒汇总 ✅（周末全池慢源复测待交易时段观察）

### 8.3 登记（不动代码）

- P1-5：独立 round（2156 行现状），须先出完整迁移图
- R190：独立 round（分 3 期，锚点已订正见 §7）
- round54：代码已落地（`7c062b6/f59fb17`），文档状态同步见 `docs/round54-frontend-polish.md`；浏览器四态走查（R174+round54+LLM 多轮）待交易时段+真浏览器，见 §6#5
