# round58 组合设计修正 + LLM 超时修复（实施轮）

> 状态：**已实施（commit `03ed659`，2026-09-28）**——Part A 的 R01/R03、Part B 的 R04/R05
> 已落地；**R02 经用户拍板暂缓**（与 round27 R48 语义互斥，见 §A3-R02 偏离登记）；
> Part A §A1 结论 ①（中证500 降权）**无引擎侧强制手段**（R01 cap 口径不含中盘，见 §A4 偏离登记）；
> **R06 运维排查已完成（commit `688ad45`）——真因是 OpenCode Zen 免费层被服务商策略封锁
> （非 key 权限），系统已自愈，端到端 `report_quality=full` 验收达成，详见 §D。**
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
| R06 运维排查 | ✅ **已完成（commit `688ad45`）** | 结论见下方 §R06；**无需改代码/配置**，系统已自愈，验收口径已达成 |

**消费方同步核查**：方案提到前端 `StrategyCheckResult.vue` 的 `fallback_reason` 分类需加
`forbidden` 分支。实查：前端**无 `fallback_reason` 字段消费点**（`rg` 零命中），该字段尚未
落地，故无分支可加——不是遗漏，是方案对消费方现状判断有偏。

---

### C. 验收结论

- pytest 全量 3340 passed / 0 failed；mypy 151 文件 Success；engine 纯度 / async 门禁 / P3-6 基线全过。
- R04/R05 的负向断言含：403 不误标超时、403 优先于 429、单 provider 连 2 次 403 后第 3 次
  零探测、两 provider 全拉黑时立即失败且文案含 403/permission。
- **未做真机验证**：R06 未执行 → `report_quality=full` 仍待 403 修复后 + 交易时段实测。

### D. R06 实施回填（2026-09-28，commit `688ad45`）

**§B3 四步逐步结论（与文档预期不同的关键点：真因不是 403）**

| 步骤 | 结论 | 证据 |
|---|---|---|
| 1. 确认 provider/model 配置 | `LLM_PRIMARY_PROVIDER=opencode_zen`、`LLM_FALLBACK_PROVIDER=deepseek`、`LLM_MODEL=OPENCODE_ZEN_MODEL=deepseek-v4-flash-free` | `backend/.env`（key 全程掩码，未入仓） |
| 2. 确认 key/模型权限 | **key 有效**（能鉴权到策略层），但 Zen 免费层被**服务商策略**封锁 | 见下表 |
| 3. 改 model 配置 | **不改**——换名无效，改主提供方反而卸掉可用的 OpenRouter 层 | `provider.py:160` OR 层挂载条件是 `primary_id=="opencode_zen"` |
| 4. 验证 `report_quality=full` | ✅ **达成**：端到端 29.5s（预算 90s）、`is_fallback=False`、真实 usage 10254 tokens | 见下 |

**Zen 免费层实测（三模型全废，探针判 NO_GO）**

| 模型 | 状态 | 响应体要点 |
|---|---|---|
| `deepseek-v4-flash-free`（当前配置） | **400** | `Upstream request failed: Model is unavailable.` |
| `jev-1.13-free` | **403** | `FreeTierError: OpenCode's free tier can only be used from within OpenCode` |
| `ling-3.0-flash-fin-free` | **403** | 同上 |

→ **FreeTierError 是服务商策略（免费层仅允许从 OpenCode 客户端内部发起），不是 key 权限问题，
也不是配置名写错**。这修正了 §B2 的假设——当时把 7 次快 403 归因为「key 对模型无权限」；
实际是整层被封，403 只是其中一支，配置模型那支是 400。R04/R05 的分类与熔断仍然正确
（403 归因、403 连击拉黑），只是真因类别比 §B2 描述的更宽。

**可用层实测 + 端到端验收**

- `deepseek / deepseek-flash` → 200；json mode / plain / 8k max_tokens 三形态全通。
- OpenRouter 免费层 `nvidia/nemotron-3-ultra-550b-a55b:free` → 200、content 非空、2.7s
  （`probe_openrouter_free_models.py` 判 **GO**）——故 OR 中间层值得保留。
- **端到端（真实 DB design #74，30 只非现金持仓，去重后 19 标的）**：
  - 耗时 **29.5s / 34.9s**，`STRATEGY_CHECK_READ_S` 预算 90s → **WITHIN BUDGET**；
  - `summary` 206 字且引用真实数据（上证50/科创50/中证500/创业板权重、`range_bound`、
    +0.10σ 未达 0.5σ 阈值）→ 非模板兜底；
  - `is_fallback(summary) = False` → **report_quality = full** ✅；
  - `usage_records` 实证：`success=1 / provider=deepseek / model=deepseek-flash /
    prompt 2370 + completion 7884 = 10254 tokens / 27.2s`（真 LLM 生成，非缓存非兜底）。

**自愈机制实测生效**：Zen 腿 400 属确定性失败，circuit breaker 记 permanent error →
`[circuit] opencode_zen:deepseek-v4-flash-free permanent error — long-cooldown + excluded + OPEN`，
单腿 0.8s 快失败不吃预算，随后 DeepSeek 承接。**故本轮不需要任何代码/配置改动**——
R05 熔断 + 既有 F8 熔断已把「确定性失败重试烧预算」的根因治住（§B2 根因 3）。

**已知残留（登记，不在本轮）**
1. `model_catalog` 排除/熔断状态**不跨进程**，每次重启首调仍付 ~0.8s Zen 试探（相对 90s
   预算可忽略，登记为性能债观察项）；
2. `generate_strategy_check_report` 的 LLM 路径 **不给 suggestions 写 `source` 字段**
   （实测 `{None: 19}`；规则兜底路径才写 `source="rule"`），也不产 `divergence_detail`
   ——R199 的 detail 覆盖的是规则兜底路径。属既有形态，本轮未改，已回填 known-env-issues §1.2b。

**Refs**：`docs/known-env-issues.md` §1.2b（新增条目，含「别改模型名 / 别改主提供方」两条禁令）。

---

## F. 交易时段复测（2026-09-29 周二 13:00-15:00 下午盘，commit 待回填）

> 窗口说明：2026-09-29 为**交易日**，13:00 下午盘开盘后开跑。方法：真实源 + 真实
> LLM，无 mock；HTTP 走进程内 `TestClient`（`::1` 字面量在本机解析不稳，见
> known-env-issues §1.1），异步任务端点那一轮**开启 lifespan**（否则任务 worker 不存在）。

### 9.1 通过项（实盘实证）

| 项 | 结论 | 证据 |
|---|---|---|
| **R04 模板收敛**（用户原始抱怨「3 处输入未提供/暂无法验证」） | ✅ **0 次** | 端到端 `llm-report/stream` 产出 2366-2432 字 / 6 章 / 28.2s / 无 SSE error；全文「未提供」+「暂无法验证」命中 **0** 次 |
| **组合设计端到端** | ✅ 真 LLM 报告 | task 132：`running(5s) → quick_ready(30s) → completed(110s)`；日志 `[design_pipeline] report saved to design_id=75 (6342 chars, quality=full)` |
| **R03 平衡型防御锚扩容** | ✅ 生效 | design 75 balanced 防御层 = **2 只**：`30年国债ETF鹏扬` + `黄金ETF华安`（改前仅黄金 1 只） |
| **R197 三元组克隆** | ✅ 未复现 | 三方案 0 个出现「≥3 标的同 (return_1m, return_3m)」元组 |
| **R198 信号标签唯一** | ✅ 生效 | design 75 报告正文：`综合信号 x0` / `因子综合分 x1`（脚注改名已在实盘报告可见） |
| **R199 divergence_detail** | ✅ 生效 | 策略检查兜底行实测 `divergence_detail = {signal_direction: neutral, factor_direction: neutral, factor_score: -0.314, threshold: 0.5, explanation: ...}`——正是 check143 曾 30/30 为 null 的主干 hold 分支 |
| **R196 「有标签必有值」** | ✅ 盘中 0 例外 | `/market/realtime/portfolio` 38 行、场外 15 只、null 价 0 只、`label_without_value=0`、`priced=38/38` |
| **R06 端到端**（§D） | ✅ | 直连路径 29.5s / 34.9s、`is_fallback=False`、`usage 10254 tokens` |
| **性能债：realtime/portfolio** | ✅ 大幅改善 | **0.84s**（round57 周末基线 16.67s，~20×） |
| **性能债：admin/llm/health** | ✅ 大幅改善 | **1.11s**（周末基线 15.55s，~14×） |
| **性能债：admin/factor-health** | ⚠️ 仍超阈值 | 6.59s（周末 6.75s；阈值 ≤2s）→ 维持性能债登记 |

### 9.2 未通过 / 环境性（逐项归因，不含糊）

| 项 | 现象 | 归因 |
|---|---|---|
| **R06 全市场宽度** | `fetch_market_breadth()` 3 次全返 `{}` | **源不可达**（push2delay；13:00 前曾成功取到 total=100/up=21/down=56/成交额 2.45e10，证明确为间歇性）。设计行为正确：回退 `{}` → prompt 走「（数据源暂不可用）」占位，未报 0 家伪值 |
| **R01 板块与风格段** | `compute_sector_momentum()` 连续 2 次返 **0 行**（各 ~14s，命中内部 15s 超时） | **源不可达**，非接线缺陷。`update_sector_cache` 只在 `if momentum:` 时写缓存，故空返回即保持空；`get_sector_momentum` 盘中不回退快照（设计如此，诚实降级）。同窗口 `hot_plates` 正常（11 行）→ 佐证是板块动量源单点问题 |
| **策略检查走异步任务时回落** | task 131：`report_quality=fallback` / `is_fallback=true`，summary `LLM 分析超时（15s 未返回…`，`因子覆盖 16.7%` | **新发现，需用户决策（见 §9.3）**：非本轮回归 |

### 9.3 新发现（超出本轮清单，待决策）

**N1：策略检查「数据空」档预算 15s < 现役 provider 实测延迟 27-31s**

- 链路事实（同一 key、同一 prompt 形态）：`_llm_timeout_for(data_quality)` 对
  `all_empty` 返 **15s**（`strategy_check.py:735-736`），本轮因子覆盖 16.7% 命中该档；
  而唯一可用 provider（`deepseek-flash`，强开 reasoning）实测 **27.2s / 29.5s / 31.5s**。
- 故 15s 档**在物理上不可能成功**——只要 provider 活着就必然超时兜底。
- 性质：**非本轮回归**。该预算阶梯写于「无 provider 可用」时期（当时恒落兜底，档位无实际影响）；
  R06 修好链路后该档位才第一次显形。design 报告不受影响（另一档 120s，实测 110s 完成 quality=full）。
- 建议（需拍板，本轮未实施）：`all_empty` 档 15s → 30s 起（与 `partial` 档对齐），或改为
  「按 provider 实测 p95 延迟取档」。**未擅自改**：属预算/时延权衡，且有
  `tests/test_round14_llm_budget_consistency.py` 锁定预算-重试一致性。

**N2：`app/tasks/startup.py:373` 调 `_kline_warmup_symbols()` 但该函数未定义于本模块**

- 实证：warmup 日志 `design-data warmup failed (non-fatal): name '_kline_warmup_symbols' is not defined`。
- 根因：该函数**只定义在 `app/main.py`**（同文件另有 `_kline_warmup_holdings_symbols`），
  `startup.py` 未导入；且 `main.py:26` 反向 import `startup.py`，**直接补 import 会成循环依赖**。
- 影响：design-data warmup 的 K 线预热段**从未执行**，被宽 `except` 吞成 non-fatal，
  该段 `_mark["success"]=False`（与 warmup 面板 `market_cache: success=false` 一致）。
  非功能性中断——设计任务按需取 K 线仍 110s 完成 quality=full——但预热收益丢失。
- 归属：**本轮两批 commit 均未触碰 `app/tasks/startup.py`**（`git diff 1e7a5c3..HEAD` 空），
  属存量缺陷。修法需把 helper 下沉到共享模块（`tasks/` 或 hub）再双向引用 → 动模块结构，需拍板。

**N3：warmup 30.8s 超 30s 预算阈值**（`instruments_sync 21.8s` / `indices_meta_sync 8.8s`）→ 维持性能债登记。

### 9.4 与「待交易时段复测」清单的对照

| 原清单项 | 本轮结论 |
|---|---|
| round57 #6 性能债（realtime / fh / llm-health） | ✅ 两项大幅改善，factor-health 仍超阈 |
| round58-market R06 实额/家数 | ⚠️ 源间歇不可达（行为正确，取数失败） |
| round58-market R08 hsgt 近 5 日 | ✅ 早已按「停更」口径落地（最后可得 2024-08-16），无「近 5 日」可取 |
| round58-market 端到端报告实值引用 | ✅ 报告真产出且 0 免责话术；板块/家数未引用系**源不可达**（非接线问题） |
| round58-portfolio R01 成长占比告警 | ✅ 口径正确：balanced 22.4% / aggressive 27.8% 均 ≤30% cap → 不告警（符合设计） |
| round58-portfolio R03 defense ≥2 | ✅ 实证 2 只（黄金+30年国债） |
| round58-portfolio R04/R05 `report_quality=full` | ⚠️ 直连路径达成；**异步任务路径**因 N1 预算档回落（待决策） |
| L2-e2e 环境性 FAIL | 本轮以进程内 TestClient 绕开 `::1` 解析问题完成上述实值验收；`verify_e2e.py` 本身仍待干净后端复测 |
