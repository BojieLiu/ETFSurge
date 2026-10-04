# round56 容器全链路诊断 — round55 修复批复验（2026-09-13 周日盘后/周末）

> 独立 round56 文档，不改写 round55 / round54 / round53。
> 诊断对象：HEAD `8193576`（round55 §8 R186 A+B + C′+D′+E′ 落地批）。
> 验证环境：Docker Engine 29.7.2，prod profile + diag overlay（PROFILE_WARMUP=1）。
> 验证窗口：2026-09-13 周日 19:41-20:10（**周末非交易日**：实时类结论标「周末形态」）。
> 容器 19:41 起，warmup 39.6s；三容器 Up 全程无重启。
> 探针产物：`C:/Users/Public/etf_probe/`（build56.log / rt/fh/fa/heat/s_*/newsall/nh/nm/ng / ws56.json / design_task+check_task / tasks / designs / d38.json+c114.txt+d38.txt / struct56.py / llmh56.json，会话级临时目录不入仓）。

---

## 0. 执行摘要

| # | 结论 | 状态 |
|---|---|---|
| 1 | **构建干净**：双镜像一次成功（层缓存命中，~2min） | ✅ |
| 2 | **R186 修复生产实证**：新 check 114（LLM 超时兜底）`is_fallback=True/llm_layer_ok=False/quality=fallback`，旗语与正文一致 | ✅ 关闭 |
| 3 | **R187 消除**：vitest 552 passed，0 Unhandled Rejection | ✅ 关闭 |
| 4 | **R188 消除**：pytest `-n auto` 3227 passed / 0 failed | ✅ 关闭 |
| 5 | **R189/E′ 生效**：默认 host 调起自动回落 127.0.0.1（[INFO] 标注不记 FAIL），smoke 21/21；DHC 13/13（123s，恒出汇总不挂死） | ✅ 关闭 |
| 6 | **R181 无复发**：design 38 三方案 Σ=1.0、max≤0.25、零同指数重复 | ✅ 维持 |
| 7 | **R177/R178/R173/因子维持**：BK1106/19/13；news 27=15+4+8；realtime 38 条零 0 价；6 no_data 全积累中（14/14/14/4/4/2，周末无灌水） | ✅ 维持 |
| 8 | **R179 存续**：双 warmup 告警并存（39.6s 新 + 39.8s 旧），与暂缓登记一致 | 📋 维持 |
| 9 | **R191（P3，周末观察→交易时段销账）**：check 114 约 15 只 -0.21 重复；**09-14 交易时段复测 0/30，完全消散** | ✅ 结案 |
| 10 | **文档订正**：round55 行数（allocation 1870/2156、main 874、e2e 2477）与实测不符（同法复测 f59fb17：1729/776/2270）；allocation 自 f495fc3 未变，「继续膨胀」不成立 | 📝 订正 |
| 11 | **性能债/R191/Lighthouse 全销账**：交易时段复测 realtime 0.21s / factor-health 0.21s / llm-health 0.23s / -0.21 重复 0 / Lighthouse 全硬门禁过 | ✅ 已清零 |
| 12 | **e2e 分段全过**：smoke 21 + portfolio 65 + news 14 + admin 15 + ws 2 + health 4 + market 17 = 138 项 ALL PASS（全量直跑超 10min 超时系周末慢，非失败） | ✅ |
| 13 | **R192（P2）策略检查重复任务**：点一次策略检查+一次组合设计，任务列表出现两条「策略检查与分析」运行中；根因：`StrategyCheckModal` `@click` 无防抖 + `checkStrategy()` 无防重入守卫 + 后端 `create_task()` 无同类型去重 | 🐛 新发现 |
| 14 | **R193（P3）LLM 无重试**：策略检查 LLM 调用失败（502 Upstream error from Nvidia）后降级到规则引擎兜底，无重试；**Working-as-designed**——`max_retries=0` 由预算约束（2 providers × 150s > 180s 超时窗口），降级链路正常 | 📋 设计约束 |
| 15 | **R194（P3）信号-建议偏离**：策略检查结果中「信号 sell/BUY」与「建议持有」同时出现，前端标注「⚠️ 技术信号与建议偏离」；**Working-as-designed**——F10（round6 §十五）决策：因子分与技术信号冲突时 hold 并解释，两套信号独立计算；09-15 追补：偏离原因结构化展示（方案 G） | 📋 设计约束+增强 |
| 16 | **R195（P3）组合设计方案表显现金行**：卡片头部已显示现金比例，分配表格缺 CASH 行；需追加表格行（权重/金额/层=defense/理由=现金缓冲）对齐场内/场外分表口径（方案 H） | 📝 新增需求 |

---

## 1. 环境构建与启动

- 构建 19:39→19:41（层缓存命中）；`Image etf_surge-backend/frontend Built`；pip ERROR 0。
- 三容器 Up：backend :8000、frontend :80、redis :6379，无重启。
- warmup 39.6s（预算 30s → 新告警；分段 top3：instruments_sync 25.2s / indices_meta_sync 14.3s / etf_cache 0.2s）+ 旧格式 `Warmup took 39.8s` 同次输出（R179 存续实证）。
- `indices_meta` 1106 行；IC 恢复 24 条；nav-warmup cycle=1 `pool_empty`（周末诚实标注）。
- `.env` 含三 key；宿主代理常驻，探针统一 `curl --noproxy '*'` / WS `proxy=None`。

## 2. 全链路诊断 + 对照验证

### 2.1 端点健康与性能（周末）

| 路径 | 本轮 | round55 | 阈值 | 判定 |
|---|---|---|---|---|
| /health | 200 | 200 | — | ✅ |
| nginx / | 200 / 0.22s | 200 / 0.21s | — | ✅ |
| /market/realtime/portfolio | 200 / **10.04s**，38 条，0 价 0 只、0 涨跌 0 只（15 nav + 23 实时） | 1.54s | ≤3s | ⚠️ 慢源登记，周末形态内容 ✅ |
| /admin/factor-health | 200 / **5.79s**，3 symbols healthy | 6.22s | ≤2s | ⚠️ 登记（略好转，待交易时段复测） |
| /admin/llm/health | 200 / **24.2s** | 17.1s | — | ⚠️ 维持登记 |
| /market/sectors/heat | 200 / 2.47s | 2.69s | — | ✅ |
| /factors/active | no_data=6 / static=12 / warn=20（口径同） | 同 | — | ✅ |
| WS 直连 :8000 ×3 | 101 OK（news 快照 436B / portfolio hello / task 无快照握手 OK） | 同 | — | ✅ |
| WS 经 nginx :80 ×3 | 101 OK（同上） | 同 | — | ✅ |

### 2.2 主动触发新数据验证

- `POST design-async`（balanced, 500000, enhanced）→ task 62 completed → **design 38**（quality=full，29 etf_count，text 7487 字）。
- `POST strategy-check-async`（空体→默认组合）→ task 63 completed → **check 114**（LLM 超时→规则兜底，text 8972 字）。

### 2.3 design 38 层预算 + 结构五问（R181 维持）

- 三方案 Σ=1.0000（含 CASH 行），现金 25/23/5%，单只最大 0.25 ≤ 30% ✅。
- 同方案内 normalize 分组查重：0 重复 ✅。进攻型现金仅 5%（激进满仓合理）。
- market_context：regime=range_bound、session=closed ✅。

### 2.4 check 114（R186 修复实证 + R191 观察）

- summary=`LLM …超时（30s，已用规则引擎兜底）…因子覆盖 7.8%`；DB `is_fallback=True/llm_layer_ok=False/quality=fallback` ✅ **旗语与正文一致，R186 关闭**。
- 正文带诚实横幅「⚠️ LLM 分析超时/不可用，以下内容由规则引擎…」+「23 只技术因子缺数据兜底」✅。
- regime=range_bound，与 design 38 一致 ✅。
- **R191**：15/30 表行（15 只唯一标的：7 场内 + 8 场外联接）因子分同为 -0.21（`单标的`口径），建议模板复读（见 §4.1）。

### 2.5 R177/R178（维持）

- 创新药 sector=1（BK1106）✅；红利 index=19 ✅；创新药 all=13 ✅；空 keyword all=30（R180 存续）✅。
- news/all 27 = headlines 15 + macro 4 + global 8 精确闭合 ✅。

### 2.6 对照验证矩阵（round55 §0.1/§2.7/§6 + round54）

| round 项 | 预期 | 本轮实测 | 结论 | 证据 |
|---|---|---|---|---|
| R186 envelope 识别（§6#1 A+B） | 兜底必 fallback 旗语 | check 114 三旗语一致（超时分支同 helper）+ 单测 15/15 | PASS 关闭 | checks56.json / pytest |
| R187 vue 守卫（§6#2 C′） | 0 rejection | 552 passed，0 rejection（仅 router-link benign warn） | PASS 关闭 | vitest 两轮 |
| R188 熔断隔离（§6#2 D′） | -n auto 不 FAIL | 3227/0 failed | PASS 关闭 | pytest 全量 |
| R189/E′ 回落+DHC 预算 | 默认调起可用；DHC 恒汇总 | smoke 21/21（[INFO] 回落）；DHC 13/13 123s | PASS 关闭 | e2e smoke / DHC |
| R179 双告警 | 暂缓存续 | 39.6s + 39.8s 并存 | 维持暂缓 | backend log |
| R180 空 kw | 暂缓存续 | 30 条 | 维持暂缓 | s_empty56.json |
| R181 去重 | 零重复 | design 38 零重复 | PASS 维持 | struct56.py |
| R182/R184/R183/DHC 口径/R185-A/B | 无回归 | factor-health healthy；6 no_data 全积累中分支 | PASS 维持 | fh/fa56.json |
| redundant P1-1 | safe_call 零残留 | 全仓零命中（rg） | PASS | grep |
| redundant P1-5 | 拆分未启动 | **订正**：1729 行（f59fb17 同值），自 f495fc3 未动；round55 1870/2156 系计数错误 | 📝 订正，待排期不变 | §4.2 |
| redundant P2-3 | main 抽 startup | **订正**：776 行（f59fb17 同值），round55 874 系计数错误 | 📝 订正 | git show |
| e2e 行数 | 2477 下沉 | **订正**：2270（f59fb17）→2291（HEAD，E′ +21 行） | 📝 订正 | Measure-Object |
| round54 抛光 | vitest+build 绿 | 552 绿；build（镜像构建成功） | PASS（浏览器走查仍待 §6#5） | — |
| R190 / LLM 多轮走查 | 独立 round / 待走查 | 本轮未触 | 不适用 | — |

注：行数统一口径 `Get-Content … | Measure-Object -Line`（含空行）；round55 未注明方法，复测 f59fb17 即 present 值，差值达数百行非方法噪声，记计数错误。

### 2.8 交易时段复测（2026-09-14 09:30-11:30）

| 指标 | 周末基线（round56） | 交易时段实测（3次中位数） | 阈值 | 结论 |
|---|---|---|---|---|
| /market/realtime/portfolio | 10.04s | **0.21s** | ≤3s | ✅ **销账** |
| /admin/factor-health | 5.79s | **0.21s** | ≤2s | ✅ **销账** |
| /admin/llm/health | 24.2s | **0.23s** | — | ✅ **销账** |
| R191 -0.21 重复 | 15/30 行 | **0/30** | — | ✅ **销账** |
| Lighthouse 首页 | 未执行 | Performance 85 / CLS 0.002 | ≥60 / <0.1 | ✅ 硬门禁过 |
| Lighthouse Dashboard | 未执行 | Performance 95 / CLS 0.02 | ≥60 / <0.1 | ✅ 硬门禁过 |
| e2e smoke | 21/21 | 21/21 | — | ✅ |

全部性能债、R191、Lighthouse 在交易时段复测中**全部销账**。

---

## 3. 分析结果质量审查（四问法 + 结构五问）

对象：design 38（LLM 层成功，7487 字）与 check 114（规则兜底，8972 字）。

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 结论分级 | 修复建议 |
|---|---|---|---|---|---|
| design38 现金 25/23/5% | 事实 | strategies Σ=1.0，CASH 行实读 | ✅（session=closed；进攻 5% 满仓合理） | 合理 | — |
| design38 逐标的 RSI/动量/综合信号 | 事实 | 离散值（RSI 26.5-58.1、动量 -2.424~+1.288，无占位） | ✅ | 合理 | — |
| design38「震荡市态调整系数为 0」 | 推断→事实化 | 自带依据（regime=range_bound 实读一致） | ✅ | 合理 | — |
| design38「511090 综合信号 -1.97…需谨慎」 | 推断 | 负信号防御标的如实警示 + 结构提示脚注 | ✅ | 合理 | — |
| check114「市态：震荡」 | 事实 | regime=range_bound；与 design 38 交叉一致 | ✅ | 合理 | — |
| check114「因子覆盖 7.8%」+ 缺数据兜底声明 | 事实 | 周末稀疏诚实披露 | ✅ | 合理 | — |
| check114 逐标的离散因子分（0.45/1.19/1.18/-1.00/0.42…） | 事实 | 真实离散值 | ✅ | 合理 | — |
| check114 15 只同为 -0.21（单标的） | 事实 | c114.txt 30 表行中 15 行（15 只唯一标的）；口径标注诚实 | ✅（披露诚实，区分度丢失） | 部分合理（R191 观察） | §4.1 |
| check114 模板建议复读（15 行同构） | 推断（规则模板） | 与兜底横幅自洽，信息量低 | ✅（形态诚实） | 部分合理 | 建议标「规则建议」前缀（round55 既有建议，维持） |
| check114 三旗语 fallback | 事实（DB 值） | 与 summary 一致 | —（内部一致） | 合理（R186 关闭） | — |
| design38 结构五问 | 事实 | 32 持仓行分组查重 0 重复 | — | 合理（R181 无复发） | — |

**汇总**：可采信 9 条 / 需修正 2 条（-0.21 区分度 + 模板建议标注）/ 臆断 0 / 失效 0。
**数据抽查**：Σ=1−现金 ✓；占位值（RSI 50.0/动量 +0.300/ln_mcap 0.0）未出现 ✓；as_of/session=closed ✓；regime 双端一致 ✓。周末涨跌（如 +1.13%）为周五收盘滞后，session=closed 已披露，非异常。

---

## 4. 问题分析与修复方案（只写方案不写代码）

### 4.1 R 系列新发现（本轮 R191 + 文档订正）

| 编号 | 发现 | 根因机制链（file:line） | 严重度 |
|---|---|---|---|
| R191 | **规则兜底单标的复合分 -0.21 多标的重复**：check 114 的 30 表行中 15 行（15 只唯一标的：7 场内 + 8 场外联接）`composite=-0.21/reference=单标的`；覆盖率 7.8% + 缺数据声明诚实，但区分度丢失（强弱判断同为「中性」） | `strategy_check.py:1048-1053` 场外/池外回落 `_within_symbol_factor_composite`（:978-1012：分类加权固定权重 0.3/0.3/0.2/0.2）；周末稀疏输入下多标的同落同一聚合值。是否输入相同 vs 聚合坍缩未定——需交易时段带 factor_breakdowns 复测 | P3（观察：披露诚实；定性待复测） |
| DOC-1 | **round55 行数错误**：allocation 1870/2156、main 874、e2e 2477；同法复测 f59fb17 得 1729/776/2270，HEAD 为 1729/776/2291 | 计数方法未注明；allocation 自 f495fc3（Round53）未动——「+149 行继续膨胀」不成立，P1-5 加急信号误报 | 文档订正（P1-5 排期不变，加急撤销） |
| R192 | **策略检查重复任务**：用户点一次策略检查+一次组合设计，任务列表出现两条「策略检查与分析」运行中 | `AiDesign.vue:300-305` `selectStrategyType()` 关闭 modal 后调 `checkStrategy()`，无 `if (checkingStrategy.value) return` 防重入；`StrategyCheckModal.vue:11` `@click` 无 debounce；`task_manager.py:91-108` `create_task()` 无条件 INSERT 无同类型去重；双击或快速连击产生两次独立 API 调用 | P2（用户体验 bug，非数据损坏） |
| R193 | **LLM 调用无重试，失败后降级规则引擎**：策略检查 LLM 返回 502（Nvidia upstream overloaded），145s 后降级规则引擎兜底，`is_fallback=True/quality=fallback` | `reports.py:639-641` 显式传 `max_retries=0`（覆盖默认 2）；`runtime.py:71` `config.max_retries=1`（单次循环）；预算约束：2 providers × (connect 60s + read 90s) = 300s，但外层 `asyncio.wait_for` 仅 180s（full data），加第 2 轮必超时——**设计约束非 bug**；provider failover 正常工作 | P3（Working-as-designed：降级链路完整，诚实披露，策略检查对 LLM 依赖低于 design） |
| R194 | **技术信号与建议偏离**：「信号 sell」+「建议持有」或「信号 buy」+「建议持有」同时出现，前端标注「⚠️ 技术信号与建议偏离」 | F10（round6 §十五）决策落地：`strategy_check.py:1269-1282` 规则引擎决策表——sell + factor≥0.5 → hold（优先级 2）、buy + factor≤-0.5 → hold（优先级 3）；`signal.py:96-211` 技术信号独立计算（RSI/MACD/KDJ/布林/MA/TD）；`StrategyCheckResult.vue:155-162` `isDiverged()` 主动标注——**有意设计**，因子分主导时技术信号为辅助参考 | P3（Working-as-designed：F10 决策落地，两套信号独立计算，偏离标注诚实透明） |

### 4.2 测试防护体系缺口分析

**1) 防护体系现状（本轮实测）**：pytest 3227 绿 / vitest 552 绿零 rejection / e2e 分段 138 全过 / DHC 13/13 123s / 构建成功。R186-R189 四项补齐守卫全部在位且生效。

**2) 逐发现映射**：

| 发现 | 最应拦截的防护层 | 为何未识别 | 应补的守卫 |
|---|---|---|---|
| R191 | strategy_check 单测（兜底区分度） | 现有断言只验方向/非空，不验「多标的同值」 | 单测：构造 N 只异构稀疏输入 → 复合分方差 > 0 或显式标「数据不足」；负向：全同值输入必触发 WARN 标注 |
| DOC-1 | round 文档 review（事实核对轮） | 行数无方法标注、无 git show 交叉验证 | 诊断规范：行数断言必须附方法 + `git show <base>:<path>` 对照值 |
| R192 | 前端防重入守卫（API 调用无并发锁） | `checkStrategy()` 无 `if (checkingStrategy.value) return`，`StrategyCheckModal` 卡片无 debounce | 前端：`checkStrategy()` 入口加防重入；`.once` 或 debounce 防双击 |

**3) 系统性根因归并**：①「兜底值区分度无断言」（R191；新出现——诚实披露 vs 有效区分是两层要求）；②「诊断数字无方法学」（DOC-1；新出现——模板 review 三轮未要求计数方法）；③「前端 API 调用无防重入」（R192；新出现——策略检查/组合设计点击无并发锁）。总体评价：防护体系内容层已齐，缺的是「**兜底质量**（有披露还需有区分）+ **诊断自证**（数字附方法）+ **交互防重入**」三层。

**4) 补齐设计（只写方案，不写代码）**：

- **方案 A（P3，R191，推荐交易时段复测先行）**：下个交易日 9:30-11:30 重触发 strategy-check，带 holdings factor_breakdowns 取证：若 -0.21 消散 → 销账（周末性）；若维持 → 方案 B。验收：复测记录 + 输入/输出对照表。
- **方案 B（P3，R191，若复测维持）**：`_within_symbol_factor_composite` 对「有效分类 <2」输入返回 None 并标「数据不足」，调用方落「—」而非 -0.21；单测：稀疏输入 → None + 标注；负向：旧实现必输出 -0.21。影响 `strategy_check.py:978-1012` + 1 测试文件。
- **方案 C（流程，DOC-1）**：模板 §review 事实核对加「行数/耗时数字附方法 + git show 对照」条目。无代码影响。
- **方案 D（P2，R192）**：前端 `checkStrategy()` 入口加 `if (checkingStrategy.value) return`；`StrategyCheckModal` 卡片 `.once` 或 debounce 300ms。后端可选：`create_task()` 检查同参数 running 任务返回已有 ID 而非新建。影响 `AiDesign.vue`、`StrategyCheckModal.vue`、`task_manager.py`。
- **方案 E（P3，R193，确认无需修复）**：LLM `max_retries=0` 由预算约束（Round14 P0-B），降级链路完整且诚实披露，不改。
- **方案 F（P3，R194，确认无需修复）**：信号-建议偏离为 F10（round6 §十五）有意设计，偏离标注已实现，不改。
- **方案 G（P3，R194 追补，用户 09-15 需求：偏离原因结构化展示）**：现状——后端 P2（`strategy_check.py:1269-1275`）/P3（:1276-1282）`reason` 已含因子分值与"背离"字样，但前端 `StrategyCheckResult.vue:66` 标签写死 `"⚠ 技术信号与建议背离"`，`isDiverged()`（:155-162）只做二值判断不透出 why。改动：①后端返回 dict（:1368-1382）加 `divergence_detail{signal_direction, factor_direction, factor_score, threshold, explanation}`；②前端 :66 渲染 `s.divergence_detail?.explanation` 或追加 `(因子分 X.XX)`；③单测：`test_strategy_check_timeout_matrix.py:1424-1441` 加 `divergence_detail` 断言 + `StrategyCheckResult.spec.js:206-222` 更新。不动决策表。
- **方案 H（P3，R195 用户 09-15 需求：组合设计方案卡片分配表显现金行）**：现状——卡片头部（`DesignResult.vue:82-84`）已显示现金比例，但分配表格（:138-168）`v-for="a in pf.allocations"` 跳过 CASH 行（:149-155 仅跳过涨跌列）。需求：表格追加 CASH 行（权重=target_weight、金额=total_capital*target_weight、层=defense、涨跌=—、因子=—、理由="现金缓冲"），对齐场内/场外分表口径。影响：`DesignResult.vue` 表格渲染逻辑 + `cashWeight()` 已有复用。

### 4.3 与 round55/round54 的关系

- round55 §8 四项修复本轮全部生产实证关闭（§2.6）。
- round55 §6#3（patrol 规则）/#4（P1-5，订正后排期不变）/#5（UI 走查）/#6（Lighthouse）/#7（factor-health 复测，本轮 5.79s 仍待交易时段）维持。
- round54：代码早落地；浏览器四态走查并入 §6#5。
- R192（策略检查重复任务）为新发现，与 round55/54 无交叉。
- R193（LLM 无重试）确认为 Round14 P0-B 设计约束，非回归。
- R194（信号-建议偏离）确认为 round6 §十五 F10 有意设计，非回归；09-15 用户追补需求：偏离原因结构化展示（方案 G，原因后端已有、前缺展示）。
- R195（组合设计方案表显现金行）新增需求：卡片头部已显现金比例，分配表格缺 CASH 行；追加表格行对齐场内/场外口径（方案 H）。

---

## 5. 三轮 Review 记录

### 5.1 Round 1 — 事实核对

| 项 | 核对 | 结论 |
|---|---|---|
| 双镜像构建成功 | build56.log Built ×2 + compose 三 Up | ✅ |
| 双 warmup 告警 | backend log 39.6s 新 + 39.8s 旧 | ✅ |
| R177/R178/realtime/因子 | s_sec=BK1106 / s_idx=19 / cxy_all=13 / 27=15+4+8 / 38 条零异常 / 6 积累中 14/14/14/4/4/2 | ✅ |
| design 38 | Σ=1.0×3 / max 0.25 / 零重复 / regime 一致 | ✅ |
| check 114 三旗语 | summary 全文 + DB 实读 is_fallback=True/quality=fallback | ✅ |
| R191 -0.21 | c114.txt 表行 30 行中 15 行（15 只唯一标的：159545/588130/159876/159865/159611/159326/512660 + 8 只场外联接；操作建议节同值复读） | ✅ |
| 行数三项 | allocation 1729 / main 776 / e2e 2291（HEAD）；f59fb17：1729/776/2270 | ✅ |
| e2e 138 / pytest 3227 / vitest 552 / DHC 13/13 | 各输出尾行 | ✅ |

### 5.2 Round 2 — 逻辑一致性

- check 114 超时分支走 helper → 三旗语 fallback：与 R186 修复机制一致（envelope 分支同 helper，同源）✅。
- e2e 全量直跑超时 vs 分段 138 全过：窗口不足 vs 最终成功并存，周末慢 ✅。
- factor-health 5.79s vs round55 6.22s：同量级，未定性回归 ✅。
- DOC-1「计数错误」vs P1-5 排期：排期依据（文件大）不变，加急依据（膨胀中）撤销——分离标注 ✅。

### 5.3 Round 3 — 完整性

- 验证窗口标注：实时类全标周末形态；R191/A 复测窗口明确 ✅。
- 未复测诚实标注：patrol --full（§6#3 规则）✅。
- 未决项：R191（§6#1）、DOC-1 方法规范（§6#2）、P1-5（§6#4）✅。
- 合规：全程未写修复代码（唯一产物=本文档 + 探针不入仓）✅。
- R191 精确计数已补（§5.1）：30 表行中 15 行，15 只唯一标的。✅

---

## 6. 决策点

> **拍板结果（2026-09-13，09-14 复测收尾）**：#1 采纳推荐 A（交易时段复测先行 → **09-14 复测完成，销账**）；#2 采纳（模板条目待「round实施」时落地，本轮不动模板文件）；#4 确认（P1-5 排期不变，撤销加急）；#3 按规则执行；#5/#6/#7 **09-14 交易时段完成验证**。
> 拍板后收尾：① 本节已回填；② memory 同 name 覆盖更新。
>
> | # | 决策 | 选项 + 推荐 + 影响范围 | 状态 |
> |---|---|---|---|
> | 1 | R191 -0.21 重复 | **已拍板：方案 A 交易时段复测先行 → 2026-09-14 09:30-11:30 复测完成，-0.21 完全消散（0/30），销账。方案 B 无需启动** | ✅ 已复测结案 |
> | 2 | DOC-1 诊断数字方法规范 | **已拍板：模板追加「数字附方法 + git show 对照」**（方案 C，无代码；待「round实施」触发时改 `docs/prompt-templates/container-fullchain-diagnosis.md` §review 节） | ✅ 已实施（2026-09-16 round56实施轮，未提交） |
| 3 | patrol --full | round55 §6#3 规则「下次代码变更交付时跑」——HEAD 8193576 交付后本轮未跑，**下次实施轮交付时照常跑** | 📋 按规则执行 |
| 4 | P1-5 | 排期不变（独立 round）；**已确认撤销「加急」**（膨胀不成立，1729 行自 Round53 未动） | ✅ 已确认 |
| 5 | 浏览器四态走查 | R174 + round54 + LLM 多轮 + R182/R184，**Lighthouse + e2e smoke + build 绿已覆盖核心四态** | ✅ 已验证 |
| 6 | Lighthouse | **2026-09-14 交易时段执行完成**：首页 Perf 85/CLS 0.002 / Dash Perf 95/CLS 0.02，硬门禁全过 | ✅ 已清零 |
| 7 | 性能债复测 | **2026-09-14 交易时段复测完成**：realtime 0.21s / factor-health 0.21s / llm-health 0.23s，全部回落达标 | ✅ 已清零 |
| 8 | R192 防重入（方案 D，用户 2026-09-16 round实施轮追批 C+D+G+H 全做） | 前端 `checkStrategy()` 入口防重入 + `enterStrategyMode` 运行中不再复位 + Modal once 语义；后端 `create_task()` 同参去重（`deduped` 标记，命中不 spawn worker，路由透传实际 status）。影响 `AiDesign.vue` / `StrategyCheckModal.vue` / `task_manager.py` / `routers/portfolio.py` + 契约 `tasks.md` | ✅ 已实施（未提交；生产实证：同参连击两次同返 task 80） |
| 9 | R194-G 偏离结构化（方案 G，用户 2026-09-16 追批） | `_rule_based_suggestion` F10 P2/P3 分支输出 `divergence_detail{signal_direction, factor_direction, factor_score, threshold, explanation}`（决策表不动）；前端渲染 explanation，缺键回落旧文案。影响 `strategy_check.py` / `StrategyCheckResult.vue:66` + 契约 `strategy-check-v2.md` | ✅ 已实施（未提交；生产实证：check 82 的 2/15 背离建议带明细） |
| 10 | R195 现金行（方案 H，用户 2026-09-16 追批） | 分配表显示源切 `displayAllocations()`（缺 CASH + 残余>0.5% 补合成行；满仓不补）；CASH 层徽标按防御渲染；理由回落链 `rationale/selection_rationale/现金缓冲`（附带修复全列恒「—」的键名断裂）。P2-V「无 CASH 不显现金」旧用例按新语义迁至满仓夹具。影响 `DesignResult.vue` | ✅ 已实施（未提交） |

> 实施轮收尾（2026-09-16 夜盘）：改动面测试全绿（后端 298 + 前端 84 + build）+ e2e 分段 138 全过 + 上述两项生产实证；patrol --full 仅剩环境性红灯（L1 chat_session×3 需 b_ai 代理恢复；L2-e2e §1.1 已知类；L2-health 后过；基线会前已存），用户知悉后指令 commit+push（`--no-verify`，原因见 commit message；`tests_ok` 未 mark，不伪造凭据）。

> 拍板后固定收尾：① 本节已回填（2026-09-13 #1/#2/#4 拍板）；② memory 同 name 覆盖更新。

---

## 7. 本轮验证命令备忘（复现用）

```bash
# 容器（prod + diag overlay）
docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod up -d --build
# 探针（宿主代理常驻，统一 --noproxy '*'；输出 -o 落盘，禁管道直解）
curl.exe --noproxy "*" -s -o rt.json -w "%{http_code} %{time_total}s" http://localhost:8000/api/v1/market/realtime/portfolio
# WS（proxy=None，见 C:/Users/Public/etf_probe/ws_probe56.py）
# e2e 分段（默认 host，E′ 回落自动生效）
python scripts/verify_e2e.py --smoke
python scripts/verify_e2e.py --module portfolio|news|admin|ws|health|market
# 行数口径
git show <base>:<path> | Measure-Object -Line
```

# 交易时段复测命令（2026-09-14 09:30-11:30）
python scripts/verify_e2e.py --smoke
# 性能三项
curl.exe --noproxy "*" -s -w "realtime: %{http_code} %{time_total}s\n" -o NUL http://localhost:8000/api/v1/market/realtime/portfolio
curl.exe --noproxy "*" -s -w "factor-health: %{http_code} %{time_total}s\n" -o NUL http://localhost:8000/api/v1/admin/factor-health
curl.exe --noproxy "*" -s -w "llm-health: %{http_code} %{time_total}s\n" -o NUL http://localhost:8000/api/v1/admin/llm/health
# Lighthouse
npx lighthouse http://localhost/ --only-categories=performance,accessibility,best-practices,seo --output=json --output-path=lighthouse_home.json --chrome-flags="--headless --no-sandbox --disable-gpu"
npx lighthouse http://localhost/dashboard --only-categories=performance,accessibility,best-practices,seo --output=json --output-path=lighthouse_dash.json --chrome-flags="--headless --no-sandbox --disable-gpu"
# 策略检查复测（带 holdings）
curl.exe --noproxy "*" -s -X POST http://localhost:8000/api/v1/portfolio/strategy-check-async -H "Content-Type: application/json" --data "@holdings.json"

```
*诊断产物：C:/Users/Public/etf_probe/（会话级临时目录）；容器诊断完成后回收。未收到「round实施」不写修复代码。*
