# round58 组合设计修正 + LLM 超时修复（实施轮）

> 状态：**已实施（commit `03ed659`，2026-09-28）**——Part A 的 R01/R03、Part B 的 R04/R05
> 已落地；**R02 经用户拍板暂缓**（与 round27 R48 语义互斥，见 §A3-R02 偏离登记）；
> Part A §A1 结论 ①（中证500 降权）**无引擎侧强制手段**（R01 cap 口径不含中盘，见 §A4 偏离登记）；
> R06 属运维动作，待 403 修复后在交易时段实测。
> 触发：用户反馈「平衡型方案科创50和中证500重仓是否合理」+「策略检查任务报告显示LLM超时」。
> 编号：round58（与 `round58-market-report-missing-data.md` 同轮不同主题，本文档为组合设计 + LLM 两个修复）。
> file:line 锚点核对时间：2026-09-28 16:30（北京时间，DB 存 UTC）。
> 验证窗口：**2026-09-28 为周日非交易日**——涉实时值/交易日行为的验收项先收口到可测子集（单测/mock/纯函数），实值复测标「待交易时段复测（交易日 9:30-11:30/13:00-15:00 + 真实环境）」。

---

## Part A：组合设计修正——平衡型成长风格集中度过高

### A1. 问题实证（四问法）

**数据来源**：`portfolio_designs` id=65，`created_at = 2026-09-28 08:24 UTC = 16:24 北京时间`（用户所述"下午四点多"）。`report_quality=full`，`risk_profile=balanced`。

**平衡型持仓**（10 只，核心 50% / 卫星 22% / 防御 13% / 现金 23%）：

| 标的 | 权重 | 层 | 因子分档 | 技术面 | 同类排名 | 主驱动 |
|---|---|---|---|---|---|---|
| 科创50ETF华夏 588000 | **20%** | core | 中性 | RSI 40.2中性、MACD空头、动量 **-0.821**、综合 -0.27 | 1/4 | 情绪 |
| 中证500ETF南方 510500 | **20%** | core | 中性 | RSI 34.8中性、MACD空头、动量 -0.289、综合 -0.28 | **3/4** | 情绪 |
| 港股创新药 513120 | 8.8% | sat | 中性 | RSI 52.3、MACD多头、动量 +1.077 | 1/12 | 动量 |
| 证券ETF国泰 512880 | 4.4% | sat | 中性 | RSI 31.4、MACD空头、动量 -0.536 | 2/12 | 动量 |
| 电池ETF广发 159755 | 4.4% | sat | 偏弱 | RSI 26.4超卖、MACD空头、动量 -1.519 | 4/12 | 动量 |
| 科创半导体 588170 | 4.4% | sat | 偏弱 | RSI 45.2、MACD空头、动量 -1.150 | 5/12 | 技术面 |
| 黄金ETF华安 518880 | 5% | def | 偏弱 | 近月承压、动量 -0.651 | — | — |
| 沪深300ETF 510300 | 5% | core | 中性 | RSI 29.1超卖、MACD空头 | — | — |
| 中证A500ETF 159338 | 5% | core | 中性 | RSI 30.6、MACD空头 | — | — |
| CASH | 23% | — | — | — | — | — |

**环境快照**：`market_regime=range_bound`、情绪指数 45（中性）、`advance_ratio=0.5`、`volume_ratio=1.0`、`margin_change=-1.0`（悲观）、板块动量 Top 全跌（最好 -0.71%）、`fund_flow` 空。`data_precision=coarse`（因子缺失 79%，权重 5% 档粗权重）。

**四问法**：

1. **事实 or 推断？** 科创50 20% + 中证500 20% = 40% 高弹性成长宽基是事实；"合理"与否是推断。
2. **支撑在哪？** 弱支撑：RSI 中性偏低（左侧均值回归逻辑）、科创50 同类 1/4。但中证500 同类 **3/4（倒数第二）** 却拿并列最高 20%，与"优选"自相矛盾。主驱动都是"情绪"，而两融情绪 -1.0 逆风。
3. **反例/内部矛盾**：
   - **名实不符**：顶着"平衡型"名字，40% 高 beta 成长 + 科创主题合计 24.4%（科创50 20% + 科创半导体 4.4%），防御仅 5% 偏弱负信号黄金，最大回撤标 -0.18。更像成长型，平衡全靠 23% 现金撑着。
   - **与今晨研判报告打架**：创业板 -2.68%、科创50 -2.35%，操作建议写"规避短线追高高波动科技题材"——转头平衡型重仓科创50 20%。
   - **风控没拦**：单只 20% < 30% 上限，主题 24.4% < 行业 40% 线——**风格集中度（成长）本身无约束，这是规则空白**。
4. **与行情一致吗？** `range_bound` + 无主线 + 成长弱势日 + 两融悲观，重仓成长宽基属左侧逆势：不算错，但属"平衡型"里最激进档。

**结论**：**部分合理，三处需修正**——① 中证500（3/4）配 20% 降到 10~15%；② 科创主题 24.4% 做近替代品合并/削权；③ 防御补实质仓位（参照同次设计的保守型：510050 20% + 512890 15% + 30年国债）。

### A2. 现有控制盘点（file:line 已核）

| 控制 | 位置 | 覆盖 | 缺口 |
|---|---|---|---|
| 核心成长宽基帽 `_cap_core_growth_wide_basis` | `allocation_engine.py:1270-1329` | 仅 core 层内 `_is_growth_wide_basis`（科创50/创业板/科创100） | **不含 satellite 层科创半导体**；不含中证500（`_is_growth_wide_basis` 不含中盘） |
| 卫星科创配额 `_constrain_satellite_tech_quota` | `allocation_engine.py` 内 | 仅 satellite 层科创系主题 | 不覆盖 core 层科创50 |
| 近替代品族合并 `_merge_substitute_family` | `allocation_engine.py:1060-1139` | `SUBSTITUTE_FAMILIES` 含"科创成长"族（科创50/科创100/创业板/双创） | **不含"科创半导体"**——`taxonomy.py:166-174` 族表无此关键词 |
| 行业集中度 HHI | `risk_controls.py` | industry 字段 | 宽基行业字段为"宽基"，不触发 |
| 结构合理性 `check_structure_reasonableness` | `allocation_engine.py:2004-2092` | INV-3/5/6 + 负信号防御提示 | 无风格集中度约束 |
| 防御锚门控 `_defense_anchors_for` | `allocation_engine.py:197-210` | defense_count=1 仅黄金 | 平衡型 defense_count=1，无红利/国债 |

### A3. 修正方案（已拍板）

#### R01：平衡型成长风格集中度软约束（新增）

**位置**：`allocation_engine.py` 的 `check_structure_reasonableness` 逐方案段（`allocation_engine.py:2034-2086`），新增 `_growth_concentration_warning`。

**规则**：对 balanced 方案，`_is_growth_wide_basis` 标的合计权重 > `balanced_growth_cap`（默认 **0.30**，占非现金总权重）→ 写 `structure_warnings`（type=`growth_style_concentration_exceeded`，含 actual/cap/profile），并在 rationale 追加提示。**软约束（告警不剔除）**，理由：
- 平衡型核心层 50% 中成长宽基占比高是因子排序结果，硬性剔除会破坏层预算闭合；
- 与 INV-4 核心成长帽（`core_growth_cap=0.40` 占核心预算）口径互补但不同——INV-4 管 core 层内占比，本约束管全方案成长占比；
- 先告警观察，连续多轮触发再考虑升级为硬约束。

**参数**：`ENGINE_CONFIG.balanced_growth_cap: float = 0.30`（新增，`budgets.py` 的 `ENGINE_CONFIG` 数据类）。

#### R02：科创族近替代品补全

**位置**：`taxonomy.py:166-174` 的 `SUBSTITUTE_FAMILIES`。

**改动**：在现有 `("科创成长", ("科创50", "科创100", "创业板", "双创"))` 中追加 `"科创半导体"`，使 588170 被识别为科创成长族 → `_merge_substitute_family` 自动将 588170 合并入 588000（保留科创50，权重 20%→24.4%），或反向保留。

**注意**：合并后科创主题权重 24.4% 仍高，但至少消除"同主题不同发行商"的虚假分散（R24/R41 教训）。

#### R03：平衡型防御锚扩容

**位置**：`budgets.py` 的 `STRATEGY_META["balanced"]["layer_count"]`。

**改动**：`"defense": 1 → 2`。

**效果**：`_defense_anchors_for("balanced")` 返回 `{518880, 511090}`（黄金 + 30年国债），防御层从 5% 黄金变为 5% 黄金 + 5% 国债（或按因子分分配）。与防御型（defense_count=2）对齐，平衡型不再"防御只有一只黄金"。

**副作用**：现金从 23% 降至 18%（防御预算 13% 不变，锚从 1→2 只各 5% = 10%，剩余 3% 按因子分给防御候选）。

### A4. 测试（T4：并入既有主题文件）

| R | 宿主文件 | 负向断言 |
|---|---|---|
| R01 成长集中度 | `test_allocation_engine_fixes.py` | balanced 成长占比 >30% 时 structure_warnings 含 `growth_style_concentration_exceeded`；≤30% 时不告警 |
| R02 科创族合并 | `test_round24_r24_correlation.py` 或 `test_allocation_engine_fixes.py` | 科创50+科创半导体同持 → `_merge_substitute_family` 合并为 1 只 |
| R03 防御扩容 | `test_engine_pool_balancing.py` 或 `test_allocation_engine_fixes.py` | balanced 方案 defense 层含 2 只（黄金+国债） |
| 回归 | `test_risk_controls.py` | 现有 RISK-CONTROL 用例全绿 |

---

## Part B：LLM 超时修复——403 分类 + 熔断 + 模型排查

### B1. 问题实证

**数据来源**：`strategy_check_records` id=149（2026-09-28 08:28 UTC = 16:28 北京时间），`llm_layer_ok=false`，`is_fallback=true`，`report_quality=fallback`。`summary`：`LLM 分析超时（143s 未返回，已用规则引擎兜底）（最后错误: Client error '403 Forbidden' for url 'https://openrouter.ai/api/v1/chat/completions'）`。

**日志时间线**（`backend/logs/backend.log`，北京时间 16:26–16:28）：

| 时间 | 事件 |
|---|---|
| 16:26:08–12 | `opencode_zen` 连吃 **7 个 fast 403**（每次 ~0.8s），`chat/completions` 直接拒 |
| 16:26:1x–16:27:43 | 又一条 `opencode_zen` 腿挂死，**空耗满 90s** 读预算后失败 |
| 16:27:43–44 | 切到 `openrouter`：第一次 POST 也是 **403**（1.2s） |
| 16:27:45 | `openrouter` 回一个 200（是否属于本任务存疑），之后 45s 无进展 |
| 16:28:30 | 外层 `wait_for` 砍掉（`interrupted after 143.4s … CancelledError`），落规则兜底 |

**系统性问题**：`usage_records` 中 `generate_strategy_check_report` 445 次调用、**0 成功**。新闻/研判能靠 failover 爬到 `space-bunny-free` 存活，策略检查（JSON 模式 + 长 prompt + `max_retries=0`）每次都在预算烧光前全军覆没。

### B2. 根因

1. **403 是主因，"超时"是误标**。`_classify_llm_failure_cause`（`backend/app/analysis/llm/reports.py:30-49`）只有 envelope/429/parse 三个分支，else 一律归"超时"——403 掉进 else。R70/R164 修过的同类缺口换了个状态码复发。
2. **403 = 该 key 对该模型无访问权**，重试多少次都没用。今天新闻链路也一样：`nemotron/jev/mimo/longcat` 等免费模型全 403，只有 `space-bunny-free` 能通。
3. **预算被一腿 hanging 吃掉**：7 个 fast 403 只花了 ~6s，真正的浪费是那条 90s 挂死腿 + 确定性 403 后的继续重试。熔断器没有对"连续 403"开断。

### B3. 修正方案（已拍板）

#### R04：`_classify_llm_failure_cause` 加 403 分支

**位置**：`backend/app/analysis/llm/reports.py:30-49`。

**改动**：在现有 429 分支后加：
```python
if "403" in _low or "forbidden" in _low:
    return f"{FORBIDDEN_PREFIX}（访问被拒绝，{duration_s:.0f}s 未完成，已用规则引擎兜底）"
```
新增 `FORBIDDEN_PREFIX` 到 `backend/app/core/llm_fallback_prefixes.py`，与 `ENVELOPE_PREFIX/PARSE_FAIL_PREFIX/QUOTA_PREFIX/TIMEOUT_PREFIX` 并列。

**消费方同步**：`backend/app/analysis/llm/client.py` 的 `run_json` / `run` 捕获异常后调 `_classify_llm_failure_cause` 的位置（`reports.py:650-683`）自动生效；前端 `StrategyCheckResult.vue` 的 `fallback_reason` 分类（`rate_limited/timeout/error`）需加 `forbidden` 分支（或归 `error`，视前端现有枚举）。

#### R05：403 熔断

**位置**：`backend/app/analysis/llm/client.py` 的 `llm_complete_with_system`（或 `llm_complete`，视策略检查走哪条路径——`reports.py:648` 调 `run_json` → `runtime.py` → `llm_complete_with_system`）。

**改动**：
- 模块级 `_consecutive_403_count: dict[str, int]`（按 provider 计数）。
- 每次 provider 返回 403 → `_consecutive_403_count[provider] += 1`；非 403 → 清零。
- 某 provider 连续 403 ≥ **2 次** → 该 provider 熔断 60s（`_circuit_open_until[provider] = now + 60`），期间跳过该 provider 直接 failover。
- 全部 provider 熔断 → 立即返回失败（不再空耗预算）。

**理由**：403 是确定性失败（key 无权限），重试无意义；熔断后 failover 或兜底提前发生，避免 90s 空耗。

#### R06：策略检查模型/Key 排查（运维动作，非代码）

**步骤**：
1. 确认 `LLM_PRIMARY_PROVIDER` / `LLM_FALLBACK_PROVIDER` 当前值（`.env` 或 `settings`）。
2. 确认 `openrouter` key 是否有效、是否有 `space-bunny-free` 模型权限（今天新闻链路实测可用）。
3. 若 key 有效但策略检查模型无权限 → 改 `strategy_check` agent 的 `model` 配置（`registry.py:42-44`，当前 `model=None` 走 `settings.llm_model`）为可用模型。
4. 若 key 失效 → 更新 `.env` 的 `LLM_PRIMARY_API_KEY` / `LLM_FALLBACK_API_KEY`。

**验证**：交易时段背靠背跑 strategy-check，确认产出真 LLM 报告（`report_quality=full`）。

### B4. 测试

| R | 宿主文件 | 负向断言 |
|---|---|---|
| R04 403 分类 | `test_report_macro_injection.py` 或 `test_strategy_check_timeout_matrix.py` | `_classify_llm_failure_cause("403 forbidden", 10)` 返回含"访问被拒绝"文案；不含"超时" |
| R05 403 熔断 | `test_strategy_check_timeout_matrix.py` | 连续 2 次 403 → 第 3 次跳过该 provider；全部熔断 → 立即失败 |
| R06 运维 | — | 交易时段实测 `report_quality=full` |

---

## 实施顺序（建议）

1. **R01+R02+R03**（组合设计修正）→ 跑 `test_allocation_engine_fixes.py` + `test_round24_r24_correlation.py` + `test_risk_controls.py` → mypy → 全量 1 次 → mark。
2. **R04+R05**（LLM 修复）→ 跑 `test_report_macro_injection.py` + `test_strategy_check_timeout_matrix.py` → mypy → 全量 1 次 → mark。
3. **R06**（运维排查）→ 交易时段实测验证。

两批可分两个 commit，也可合一个（视改动面大小）。

## 验收

- **开发期**：只跑受影响测试文件 + mypy。
- **验收期**：全量 1 次 + `tests_ok_marker.py --mark`。
- **运行时**（周日可测子集）：单测全绿；mock 全空 prompt 含占位不断言失败。
- **待交易时段复测**：
  - R01：新设计 balanced 成长占比 ≤30% 或告警正确触发。
  - R02：科创50+科创半导体不再同持。
  - R03：balanced defense 含 2 只。
  - R04/R05：交易时段 strategy-check 产出真 LLM 报告（`report_quality=full`），403 时 summary 含"访问被拒绝"非"超时"。

---

## 实施回填（2026-09-28，commit `03ed659`）

### A. Part A 逐项状态

| R | 状态 | 落点 |
|---|---|---|
| R01 成长集中度软约束 | ✅ | `allocation_engine._growth_concentration_warning`（仅 balanced，占**非现金**权重）；`ENGINE_CONFIG.balanced_growth_cap=0.30` + INV-7 范围校验；告警 `growth_style_concentration_exceeded` 含 actual/cap/profile |
| R02 科创族补全 | 📋 **暂缓（用户拍板）** | 见下方偏离登记 |
| R03 平衡型防御锚扩容 | ✅ | `STRATEGY_META["balanced"].layer_count.defense` 1→2 → 锚 `{518880, 511090}`；INV-3 防御数反向仍成立（2≥2≥1） |

### A. 偏离登记

1. **R02 暂缓（用户决策）**——方案要求把「科创半导体」并入「科创成长」族，但 `SUBSTITUTE_FAMILIES`
   里「科创半导体/科创芯片」当前在**排在前面的**「半导体」族中（`taxonomy.py` 顺序优先命中）。
   挪族会直接打破 **round27 R48** 已实现并有守卫的语义（`test_near_substitute_merge.py` 断言
   588200 科创芯片 + 588170 科创半导体设备**必须**按「半导体」族合并留一，含 3 处断言 +
   balanced/aggressive 端到端用例）。两者互斥：588170 只能归一个族。**用户拍板：不动族表**。
   残余风险登记：design 65 的「科创50 20% + 科创半导体 4.4%」同主题不同发行商仍并存
   （虚假分散未消除），R01 的成长集中度告警也**不覆盖**该形态（588170 属卫星主题股，
   非 `growth_style` 宽基）→ 留待后续轮次。
2. **§A1 结论 ①（中证500 3/4 却配 20%）本轮无引擎侧强制手段**——R01 规则按方案原文用
   `_is_growth_wide_basis`（`taxonomy.growth_style_of`）判定，而该分类器**不含中证500/中证1000**
   （方案 §A2 缺口表已列此事实）。故 design 65 形态按此口径只算 20%/74% = 27% < 30% cap，
   **不触发**告警。已用 `test_r01_cap_caliber_excludes_midcap_growth` 把该口径钉死，
   将来若把中盘成长纳入 `growth_style`，该用例会失败并提醒同步更新本文档验收口径。

### B. Part B 逐项状态

| R | 状态 | 落点 |
|---|---|---|
| R04 403 分类 | ✅ | `_classify_llm_failure_cause` 新增 403 分支并**置于 429 之前**（403 文本可能含 quota，先判 429 会误标限流）；`FORBIDDEN_PREFIX` 入 `llm_fallback_prefixes.FALLBACK_PREFIXES`（R186 口径同步，`is_llm_fallback_summary` 自动识别） |
| R05 403 熔断 | ✅ | `client._r05_403_allow/_r05_403_record`，阈值 2 次、冷却 60s，**排在 F8 熔断之前**（否则 F8 先 OPEN 会把 403 归因吃掉）；全 provider 拉黑 → 抛含 403/permission 的 RuntimeError 立即失败 |
| R06 运维排查 | 📋 未执行 | 属 repo 外动作（`.env` / key 权限），待用户执行后在交易时段实测 `report_quality=full` |

**消费方同步核查**：方案提到前端 `StrategyCheckResult.vue` 的 `fallback_reason` 分类需加
`forbidden` 分支。实查：前端**无 `fallback_reason` 字段消费点**（`rg` 零命中），该字段尚未
落地，故无分支可加——不是遗漏，是方案对消费方现状判断有偏。

### C. 验收结论

- pytest 全量 3340 passed / 0 failed；mypy 151 文件 Success；engine 纯度 / async 门禁 / P3-6 基线全过。
- R04/R05 的负向断言含：403 不误标超时、403 优先于 429、单 provider 连 2 次 403 后第 3 次
  零探测、两 provider 全拉黑时立即失败且文案含 403/permission。
- **未做真机验证**：R06 未执行 → `report_quality=full` 仍待 403 修复后 + 交易时段实测。
