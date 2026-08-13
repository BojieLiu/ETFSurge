# ETF Surge — 组合引擎系统性重构设计（组合分配框架）

> **状态**：设计稿（design-only），不实施。需单独批准方可进入实现（遵循 round21「设计级、不实施」约定）。
> **关联**：round21 §12 #10–14。本设计将五症状归因为同一根因并给出统一修复框架。
> **作者**：Sisyphus ｜ **日期**：2026-08-13 ｜ **版本**：v2（经 Momus 计划评审 + 自查修订：补可行性探针、细化 4 项阻断性方案）

---

## 0. 修订记录
- **v1（初稿）**：根因 + 6 不变量 + 目标架构 + 迁移 + 测试。
- **v2（本版）**：Momus 评审 + 自查发现 4 项阻断性问题——(a) INV-4 无 β 数据源；(b) INV-6 与 `dynamic_layer_budget` 各 regime 冲突；(c) 进攻防御层 3 只的真实机制（MANDATORY 强制注入）；(d) 「目标数量」回退算法缺失——已逐一细化方案。新增 §2.5 可行性探针、§4.1 ProfileSpec 精确字段、§4.3 回退阶梯与强制注入感知、§6 regime 固定 + fixture 反例。

---

## 1. 背景与触发
round21 五症状（design_id=534，北京 2026-08-13 19:19 实证）：
| 症状 | 实测 |
|---|---|
| 平衡核心 67% 高 beta 成长 | 核心 0.30 = 沪深300+中证A500+创业板(0.1001)+科创50(0.0999)，创业板+科创50 占 67% |
| 卫星数倒挂 | 卫星 防御 2 / 平衡 6 / 进攻 2 |
| 标的数倒挂 | 总标的 防御 10 / 平衡 13 / 进攻 8 |
| 进攻压舱过保守 | 防御层 19%（30年国债+黄金+10年地债）+ 现金 25% = 44% 非权益 |
| LLM 报告静默降级 | `report_quality=partial` / `generated_at=None`，前端只显方案表 |

根因：**缺统一风险预算框架，配置（`STRATEGY_META`）不是真相源**；三处未接线/强制逻辑（成长宽基上限死 helper、卫星不对称过滤、防御层 MANDATORY 强制注入）使实际组合由隐式交互涌现，倒挂必然反复。

---

## 2. 根因分析（证据链，v2 修正）

### 2.1 配置层
`backend/app/engine/budgets.py:13-60`（`STRATEGY_META`）：`layer_budget` 三方案完全相同（`core 0.50/sat 0.20/def 0.15`）；风险区分全压 `layer_count`（def `4/6/2`、bal `5/8/1`、agg `5/8/1`）。`layer_count` 在引擎里仅作软上限（§2.2）。

### 2.2 引擎层（v2 修正机制）
- `layer_count` 作 `max_count` 软上限：`allocation_engine.py:865/1053/1147`（传入 `_select_and_weight`）。
- **卫星不对称过滤（#11 真因）**：`_filter_satellite_by_profile:610`——`balanced` 返回全量候选（`:626`），`defensive`/`aggressive` 走 suitability 打分 + `KEEP_RATIO` 裁剪（def 0.6 / agg 0.7 / bal 0.8，`:673-677`）→ 平衡 6 / 防御·进攻 2 的直接成因。宽基剔除 `:1041`；卫星下限补全 `:1063` 仅保 floor=4，**非目标**。
- **核心层无成长宽基上限（#10 真因）**：`_is_growth_wide_basis:162`（判 科创50/创业板/科创100/双创 为高 beta 成长宽基）**已定义但从未被调用**（grep 确认仅定义+注释）；F6「核心成长宽基≤40%」约束从未接线 → 创业板/科创50 按宽基核心入选，占核心 67%。数据侧：`etf_scanner` 静态池（`:72/:74`）与 `market_data_hub._assign_layer:465`（`industry==宽基指数`→core）把创业板/科创50 标为 core。故核心是「成长宽基占比上限」约束缺失，而非打标错误。
- **进攻防御层 3 只（#13 真因，v2 追踪明确）**：`MANDATORY_CODES={"510300","159338","518880","511090"}`（`:233`）。`_select_and_weight` 对命中 MANDATORY 的候选**无视 `max_count` 强制注入**（`:306-327`，权重 0.03），合并时 mandatory 始终返回（`:606`）；随后 `strategy_design.py` 强制标的权重下限后处理把 518880/511090 抬到 5%（`:1164-1188`）。故即便 `layer_count.defense=1`，防御层仍得 518880+511090+1 只 = 3 只 / 19%。**非 `max_count` 失效，是 MANDATORY 强制注入。**

### 2.3 现有校验器缺位
`check_structure_reasonableness:1367` 仅查 3 项（负信号防御 / 防御高相关 / 进攻现金>20%），缺数量单调 / 成长占比 / 压舱不变量 → 倒挂静默产出（即 round21 §10「测试盲区」）。

### 2.4 根因小结
配置非真相源 + 三处未接线/强制逻辑（成长宽基上限死 helper、卫星不对称过滤、防御层 MANDATORY 强制注入）→ 倒挂必然反复。

### 2.5 可行性探针（D1，v2 新增，实施前必跑）
- **P1 β 数据源**：grep 确认 `factor_definitions.yaml` 声明 `style.volatility.beta_60d/250d`（`:374/:384`）但 `factor_registry` **无任何 compute 函数**（全仓 grep 仅 YAML 出现）→ 因子矩阵永不含 β。「读 β 字段」不可行；改用**已建成的 `_is_growth_wide_basis` 关键词分类器**作 β 代理（创业板/科创50=高 β 成长），无需新数据源。可选增强：在 `market_data_hub` 用 K 线 vs 沪深300 算真实 β 注入因子（非阻断）。
- **P2 INV-6 vs regime**：跑 `dynamic_layer_budget` 三方案×全 regime，列表 `(core,sat,def,cash)`，确认越界（实测 bear 进攻 cash 0.258/def 0.20、bull 进攻 cash 0.13/def 0.12），据此定 regime clamp 值（§4.2 INV-6）。
- **P3 候选池宽度**：交易时段数卫星候选（非宽基），确认 `satellite_count` 目标 3/5/7 可达；不足走 §4.3 回退阶梯（质量地板），非交易窗口用 `_DEFAULT_CANDIDATES` 宽度作下界。

---

## 3. 设计目标
### 3.1 In scope
ProfileSpec 单一可校验真相源 + 加载期不变量校验；引擎严格消费配置（目标数量 + 核心成长占比上限 + 防御强制注入感知）；校验器扩展；纯函数、无 I/O。
### 3.2 Out of scope
前端 LLM 报告降级标注（#14 单列）；LLM 报告管线超时；因子计算 / 数据源 / 行情管道（`market_data_hub` 仅作候选池输入，不改其取数逻辑）。

---

## 4. 目标架构（v2 细化重大方案）

### 4.1 单一可校验真相源 ProfileSpec（v2 精确字段）
`budgets.py` 新增（替换 `STRATEGY_META` 裸 dict）：
```python
@dataclass(frozen=True)
class ProfileSpec:
    id: str
    label: str
    color: str
    portfolio_name: str
    positioning: str
    expected_return: float
    max_drawdown: float
    sharpe_ratio: float
    layer_budget: dict[str, float]      # {core,satellite,defense}，sum+cash==1
    layer_count: dict[str, int]         # {core,satellite,defense}，目标数量
    core_growth_cap: float             # INV-4：核心层成长宽基占比上限（占 core 预算）
    expected_characteristics: str
    # c2_adjust：现状为死配置（仅 budgets.py:25/41/57 定义，引擎从未消费；
    #   C2 逻辑用硬编码 _RISKY/_SAFE_THEMES）。重构中标记 deprecated，保留字段不消费，后续清理。
```
加载期由 `STRATEGY_META` 构造 `ProfileSpec` 并跑 §4.2 不变量校验；违反→导入即抛。`dynamic_layer_budget:63` 改为在 `ProfileSpec` 上做 regime 调整，返回仍满足闭合 + regime clamp（INV-6）。

### 4.2 不变量清单（v2 修正 INV-4/INV-6，全部可机检）
- **INV-1** 预算闭合：每方案 `core+sat+def+cash==1.0`（cash 引擎算）。
- **INV-2** 预算随风险单调：`defense_budget` 防御≥平衡≥进攻；`satellite_budget` 防御≤平衡≤进攻；`cash` 防御≥平衡≥进攻。
- **INV-3** 层数量随风险单调（目标）：`satellite_count` 防御<平衡<进攻（建议 **3/5/7**）；`defense_count` 防御≥平衡≥进攻（建议 **3/1/1***）；`core_count` 持平或递增（建议 4/5/6）。*进攻 `defense_count=1`（仅黄金）。
- **INV-4** 核心成长宽基占比上限（v2 改占比上限，非 raw β）：`core_growth_cap` 防御≤平衡≤进攻（建议 **0.20/0.40/0.60**，占 core 预算）。用 `_is_growth_wide_basis` 判成长宽基；平衡型创业板+科创50 占比 67%→**≤40%**。（raw β 表为可选增强，非阻断。）
- **INV-5** 总标的数单调（输出）：`total` 进攻≥平衡≥防御。
- **INV-6** 进攻压舱约束（v2 regime-aware）：**静态 base** `aggressive.defense_budget≤0.05`（仅黄金）、`cash≤0.10`；`dynamic_layer_budget` 在任意 regime 对进攻型 clamp：`defense≤0.10`（bear 可至 0.10）、`cash≤0.10`（bear 可至 0.15）。防御性轮动可抬防御/平衡防御，但进攻防御/现金被钳制在下界。

### 4.3 引擎严格消费配置（v2 细化算法）
- **目标数量而非仅上限**：`_select_and_weight` 以 `layer_count[profile][layer]` 为目标；`max_count` 仍 = 目标（硬上限，禁超）。不足走**回退阶梯**（质量地板，非静默少选、非劣质填充）：
  1. 去掉 `_filter_satellite_by_profile` 的 suitability/`KEEP_RATIO` 裁剪（`:673`）；
  2. 去掉卫星负分排除（`:472`，`score>-0.3`）；
  3. 从统一候选池（全部 candidates）补，带**质量地板** `factor_score > -0.5`（可配），且卫星层排除宽基（`:1041`）、防御型排除科技（`:1076`）；
  4. 仍不足 → 接受少选并写 `structure_warning`（fail-soft，绝不强制填充劣质标的）。
  卫星层同时废除 `:626` 的「balanced 全量 / def-agg 裁剪」不对称，统一按 `satellite_count[profile]` 目标 + 既有 tech 50% 配额选取；**移除 `:1063` 的硬 floor=4（或降为 ≤ `layer_count` 目标）**，避免与防御型 `satellite_count=3` 目标冲突（否则 floor 会强撑防御卫星到 4 只，违背 INV-3）。
- **核心成长宽基占比上限（#10，v2 可行方案）**：核心选完后算 growth_wide_basis 权重占比；若 > `core_growth_cap[profile]`，按 `factor_score` 降序逐个移除最低分成长宽基，权重按其余核心占比回补（或归现金），直至 ≤ cap。**接线 `_is_growth_wide_basis`（替代死 helper）**。直接把平衡核心成长占比压到 ≤40%。
- **防御层资产递减 + 强制注入感知（#13，v2 修正机制）**：将 `MANDATORY_CODES` 拆为 core 锚（510300/159338）与 defense 锚（518880/511090）；defense 锚注入**受 `layer_count[profile].defense` 门控**——仅当 `defense_count≥1` 注入，且注入数 ≤ `defense_count`。进攻 `defense_count=1` → 仅注入 518880（黄金），511090 不进进攻防御层。防御层按 `defense_count` 目标 + 资产递减（进攻仅黄金，防御可含债/金/货币）选取。
- **regime clamp（INV-6）**：`dynamic_layer_budget` 返回前对进攻型钳制 `defense≤0.10`、`cash≤0.10`（bear 现金≤0.15）；其余方案保持 INV-2 单调。

### 4.4 分配后校验器扩展（`check_structure_reasonableness:1367`）
新增断言（写 `risk_metrics.structure_warnings`，与现有风格一致；严重越界可升级为 `AllocationError` 由 `strategy_design.py` 决定 fail/降级，不产畸形组合）：
- INV-3 层数量单调（输出级，对比 ProfileSpec 目标）；
- INV-4 核心成长宽基占比 ≤ `core_growth_cap`；
- INV-5 总标的数单调；
- INV-6 进攻压舱（regime 感知，用 clamp 后边界）。

### 4.5 错误处理
加载失败 / 不变量违反 → 导入即崩（fail-fast）；运行时越界 → 结构化 `AllocationError`（含违反不变量 + 实际值），调用方降级而非静默。

---

## 5. 迁移步骤（v2 补探针 + 精确配置，每阶段可回滚）
- **Phase 0 — 配置可校验化 + 新进攻配置 + regime clamp**：
  - 加 `ProfileSpec` + 加载期 INV-1~6 校验。
  - **改 `STRATEGY_META` 进攻型 `layer_budget` 为 `core 0.60/sat 0.30/def 0.05/cash 0.05`（sum 1.0，满足 INV-6）**；`defense_count` 进攻 = 1（仅黄金）；`core_growth_cap` 三方案 0.20/0.40/0.60。
  - `dynamic_layer_budget` 加进攻 clamp（INV-6）。跑探针 **P2** 确认各 regime 不越界。
  - 验收：导入 `budgets.py` 不报错；`dynamic_layer_budget` 三方案×全 regime 满足 INV-2/6。
- **Phase 1 — 核心成长宽基占比上限（#10）**：接线 `_is_growth_wide_basis` + 占比回退算法（§4.3）。跑探针 **P1** 确认分类覆盖创业板/科创50。验收：平衡核心成长宽基占比 ≤0.40。
- **Phase 2 — 卫星去不对称 + 目标数量（#11/#12）**：废除 `:626` 不对称 + 回退阶梯（§4.3）。实施前跑探针 **P3**（确认卫星池宽度）。验收：卫星数 防御<平衡<进攻；总标的数 进攻≥防御。
- **Phase 3 — 防御层资产递减 + 强制注入感知（#13）**：拆分 `MANDATORY_CODES` + `defense_count` 门控（§4.3）。验收：进攻现金 ≤0.10 且防御层 ≤0.05（仅黄金）。
- **Phase 4 — 校验器扩展 + 单测**：`check_structure_reasonableness` 加 INV-3/4/5/6；补 §6 单测。验收：pytest 全绿，倒挂组合被拦截。
- 每 Phase 后跑 `pytest` + `verify_e2e.py` + 实跑 `design-async` 查 DB 最新 design 核对（reality check）。

---

## 6. 测试策略（v2 regime 固定 + fixture 反例，TDD）
所有测试 pin `regime="range_bound"`（`dynamic_layer_budget`≈恒等，断言确定）。**反例 fixture**：构造 design-534 式倒挂输出（sat `2/6/2`、core 成长 67%、total `8/13/10`、进攻 cash 0.25/def 0.19）喂 `check_structure_reasonableness` → 断言返回 INV-3/4/5/6 违规。
- `test_core_growth_cap`：平衡核心成长宽基权重 ≤ `core_growth_cap`(0.40)，创业板+科创50 占比 <0.40（具体值，非恒绿）。
- `test_layer_count_monotonic`：ProfileSpec 配置满足 satellite 防御<平衡<进攻、defense 反向（配置级）；另 `test_engine_layer_count` 跑引擎（range_bound）输出满足单调（输出级）。
- `test_total_instrument_monotonic`：引擎输出（range_bound）total 进攻≥平衡≥防御。
- `test_aggressive_low_ballast`：引擎输出（range_bound）进攻 cash≤0.10、防御权重≤0.05。
以上均能失败（反例 = 旧倒挂组合 / 旧配置）。

---

## 7. 验收口径与反假完成（reality check）
- **真实链路实证**：实现后实跑 `POST /portfolio/design-async`（regime=range_bound 或交易日 9:30–15:00 真实环境），查 `data/portfolio.db` 最新 `portfolio_designs` 记录，核对三方案 `core/satellite/defense` 数量 + 现金 + 核心成长占比，须满足 INV-1~6。
- **非兜底数据**：因子矩阵须真实满值（交易日窗口）；非窗口实测打标「待交易时段复测」，不得 mock 冒充。β 用 `_is_growth_wide_basis` 代理，不造假。
- **引用完整性**：`grep` `strategy_design.py` / 前端 `DesignResult` 调用点，确认 design 端点仍接通（脚手架零容忍）。
- **内容正确性**：断言关键字段**实际值**（数量方向 / 占比），非仅 `200/非空`。

---

## 8. 已知风险 / 权衡（v2 更新）
- **β 数据源**：raw β 因子无 compute fn → 用 `_is_growth_wide_basis` 关键词代理（可行，覆盖创业板/科创50/科创100/双创）；真实 β 表为可选增强（`market_data_hub` 算）。不造假。
- **候选池窄（P3）**：回退阶梯带质量地板 `factor_score>-0.5`，不足则 fail-soft 写 warning，绝不强制填充劣质标的（防退化组合）。
- **强制注入**：拆分 `MANDATORY_CODES` 并 `defense_count` 门控，避免进攻防御层被债/金撑爆。
- **regime 移动**：`dynamic_layer_budget` clamp 保证 INV-2/6 各 regime 成立（Phase 0 探针 P2 验证）。
- **历史兼容**：`design_text` 结构不变；旧 design 只读。
- **c2_adjust 死配置**：Phase 0 保留字段标 deprecated，不消费，后续清理。

---

## 9. 与 round21 §12 #10–14 映射
| # | 症状 | 本设计修复点 |
|---|---|---|
| #10 | 平衡核心 67% 高 beta | §4.3 核心成长占比上限 + INV-4 + §6 `test_core_growth_cap` |
| #11 | 卫星数倒挂 | §4.3 卫星去不对称 + INV-3 + §6 `test_layer_count_monotonic` |
| #12 | 标的数倒挂 | INV-5 + §6 `test_total_instrument_monotonic` |
| #13 | 进攻压舱过保守 | §4.3 防御资产递减 + 强制注入感知 + INV-6 + §6 `test_aggressive_low_ballast` |
| #14 | LLM 报告静默降级 | **本设计不修**（前端/design_report 单列）；本设计确保引擎产出 `design_text` 结构完整，便于前端区分 partial |

---

## 10. 设计评审对照（design-checklist 8 项）
- **D1 可行性探针**：§2.5 三探针（P1 β 源 / P2 INV-6 regime / P3 池宽），均实施前跑。
- **D2 证据链**：§2 每条 `file:line`（`budgets.py:13-60/:233`；`allocation_engine.py:162/:610/:626/:673/:865/:1041/:1063/:1147/:1367`；`etf_scanner:72/:74`；`market_data_hub:465`；`strategy_design.py:1164-1188`）。
- **D3 验证窗口**：§7 交易日 9:30–15:00 + 真实环境，非窗口打标「待交易时段复测」。
- **非兜底数据**：§8 β 代理不造假、池窄 fail-soft。
- **真实调用点**：§7 grep design 端点。
- **四态 UI**：纯引擎层不涉及（#14 单列时再走四态）。
- **复杂度审计**：回退阶梯质量地板防劣质填充，无超时外部调用（纯函数）。
- **已知问题模式**：§8 六项。

---

**下一步**：设计稿 v2 已具备实施标准（根因/机制/数据可行性/回退/测试/验收均明确）。实施需用户批准——选 **B** 直接重构（按 §5 Phase 0→4）或 **C** 仅修配置接线；每阶段走 §2.5 探针 + §6 测试 + §7 reality check。
