# round35 架构评估轮 — D1-D5 确证缺陷 + S1-S7 结构性问题 + B1-B6 重构批次方案；§11 异步任务系统评估 + §12 数据管线评审与调度决策 + §13 全后端架构评估(A1-A5/C1-C8) + 并行追加节：测试防护体系评审 / 前端架构评估(R123-R128) §15 因子模型评估(FM/FS 系)（2026-08-22 周六；**方案定稿未实施**）

> 本文档为策略引擎（`backend/app/engine/`）的首次系统性架构评估与重构方案。
> 方法：全量逐行阅读引擎 7 文件 + 纯度门禁脚本 + 编排层交界（strategy_design.py），
> 并以 explore 子代理核查输入侧（factor_registry / ic_tracker / hub 池构建）。
> 依据 AGENTS.md「设计流程」（docs/design-checklist.md 八项清单，自查见 §9）+
> 「反假完成机制」+「四问法质量审查」撰写。
> 与 round34 的关系：round34 §R104/R105 为本方案第二批（引用不重复）；
> 其余批次均为本轮新发现。所有结论均有 `file:line` 实证（§4-§5）。
> 2026-08-22 追加 §13：全后端架构评估（三路并行探查：异步阻塞 / 数据缓存 / 分层耦合），
> 覆盖策略引擎之外的 services/tasks/fetchers/factors/monitor 数据层，问题编号 A1-A5（必修/排期）、
> C1-C8（记录在案），与引擎专项的 D/S/B 编号体系互不冲突。
> **§12 为并行会话产物**：数据管线设计评审（fetchers/hub/factors 三层）+ APScheduler
> 调度二选一专项决策（建议 B 案，未实施）。
> **§16 为并行会话产物**：前后端测试防护体系评审（pytest / vitest / pre-commit / patrol
> 四层；含冗余与覆盖缺口清单、P0-P2 优化批次，未实施）。
> **§17 为并稿产物**（2026-08-23 多轮 review）：批次命名消歧（r34-B 系 vs 本档 B 系）+
> 全局排期波次总图 + design-checklist 跨节补查——**实施排期以 §17 为入口**。
> **§14 为追加节**：前端架构评估（第三会话产物），发现编号 R123-R128 沿全局 R 序列
> 连续（round34 §9 止于 R122），批次编号 FE1-FE5（避开引擎 F 系列、§11 A/C 系列、
> §13 P 系列批次号）。
> **§15 为因子模型（引擎输入侧）评估**：聚合语义与决策正确性深读——FM1 IC 衰减方向反转
> （🔴 确定性 bug）/ FM2 IC 加权尺度失配 / FM3-FM4 覆盖缺口 / FS 卫生项；与 §12 管线卫生层
> 互补不重叠（合并残留已由 §12.5-P2-1 登记，本章不重复）。
>
> ✅ **编号已并稿定稿**（2026-08-23）：§11 异步任务 / §12 数据管线 / §13 全后端架构(A/C 系)
> / §14 前端架构(R123-R128, FE 系) / §15 因子模型(FM/FS 系) / §16 测试防护(P0-P2 批次)——
> 六节编号唯一；跨节引用一律带「§N.」前缀消歧（注意 P0/P1/P2 在不同节含义不同：
> §11/§12 用作问题编号，§13 用于分级标注，§16 用作修复批次优先级）。

---

## 0. 执行摘要

### 0.1 核心结论

1. ✅ **总体判断：架构方向正确且高于平均水准，主要债务不在范式而在实现演化**。
   「纯函数引擎 + AST 纯度门禁 + 配置 fail-fast 校验 + 诚实降级」的组合是本项目最值钱的
   工程资产（§3 保持清单），不需要推翻重来。真正的债集中在两处：
   **allocation_engine.py 的演化式膨胀**（1955 行、~10 段就地变异叠层、顺序约束只活在注释里）
   与**中文子串关键词分类器的脆弱性**（三套"宽基"概念并存 + 排除词补丁累积）。
2. 🔴 **发现 1 个门禁级缺陷（D1）**：`check_engine_purity.py` 对相对导入存在检测盲区——
   `rationale.py:238` 的 `from ..analysis.signal import composite_signal` 实际绕过门禁，
   引擎层真实依赖了 `app.analysis` 包（分层声明「engine 只能依赖 core/自身」当前不成立，
   §4.1）。运行时无 I/O 危害（该函数是纯函数），但破坏分层边界守护的完备性与可信度。
3. 🟠 **发现 4 个一致性缺陷（D2-D5）**：MANDATORY_CODES 双份字面量集合、_COMPANY_NAMES
   双份**已漂移**名单（~90 vs ~80 条）、allocate 内基于 layer 名的 HHI 死计算（恒被下游
   覆盖）、rationale 双写导致 O24 归因链在生产输出中丢失（§4.2-4.5）。
4. 🟡 **结构性问题 7 项（S1-S7，非 bug）**：上帝模块 / 子串分类器 / 六层去重叠加 /
   魔法数字散落 / profile 顺序耦合 / 收益指标为静态常量 / 权重再平衡三方案并存且跨段互破
   （§5）。按投入产出排入 B3-B6 批次，其中两项明确「不做」（§7 防过度工程）。
5. 📐 **实施分六批（B1-B6，§6）**：B1 缺陷修复（~0.5-1 天，零行为变化或仅恢复丢失功能）→
   B2 引用 round34 R104/R105 既定方案 → B3 配置收敛+分类器合并 → B4 黄金快照回放
   harness（后续一切引擎改动的安全网）→ B5 allocate 流水线化（独立轮，依赖 B4）→
   B6 收益指标持仓推导（渐进）。一至四批不动输出语义，可放心推进。

### 0.2 关键判定表

| 判定 | 项目 |
|---|---|
| 🔴 门禁级缺陷 | D1 纯度门禁相对导入盲区（rationale.py:238 绕过 check_engine_purity.py） |
| 🟠 一致性缺陷 | D2 MANDATORY_CODES 双源（allocation_engine:296 vs pool_balancing:25）、D3 _COMPANY_NAMES 双份漂移（allocation_engine:28-43 vs pool_balancing:66-78）、D4 layer 名 HHI 死计算（allocation_engine:1535-1540 恒被 risk_controls:389-422 覆盖）、D5 rationale 双写丢 rank_info（strategy_design:466-475 覆盖引擎侧 ：665-672） |
| 🟡 结构性问题 | S1 上帝模块、S2 子串分类器三套宽基概念、S3 六层去重叠加、S4 魔法数字散落、S5 profile 顺序耦合、S6 静态收益指标、S7 再平衡三方案并存 |
| ✅ 设计亮点（保持） | 纯函数+门禁、budgets fail-fast INV-1~4、诚实降级贯穿、强制锚四道防线、不变量双保险（§3） |
| 🚫 明确不做 | 换均值方差优化器、大爆炸重写 allocate、ML 替换关键词分类、合并六层去重代码（§7） |

### 0.3 验证窗口标注（D3 清单项）

本轮为代码级静态评估，全部结论**无交易时段依赖**（纯函数行为可离线复现）。
涉及运行时链路的验收（patrol --diff / e2e / verify_perf）在实施批次执行时跑；
黄金快照场景②（盘后无相关矩阵路径）恰好覆盖非交易时段行为，无待复测项。

---

## 1. 评估范围与方法

| 项 | 内容 |
|---|---|
| 全量阅读 | `backend/app/engine/{allocation_engine,budgets,risk_controls,rationale,correlation,pool_balancing,composite_signal}.py`（合计 ~3500 行）+ `backend/scripts/check_engine_purity.py` |
| 交界核查 | `backend/app/services/strategy_design.py`（generate_enhanced_design 编排流）、`backend/app/analysis/signal.py`（被 rationale 引用） |
| 输入侧调查 | explore 子代理：factor_registry 熔断/降级、ic_tracker 口径（R104 现状确认未修复）、hub 池构建管线、remove_stale 锚点保护现状（R105 确认未实施） |
| 未覆盖 | composite_signal.py 仅池层打分用途核查（135 行全读）；correlation.py 尾部 avg_correlation（低风险，抽查） |

---

## 2. 引擎现状全景（证据链）

### 2.1 分层与数据流

```
market_data_hub（I/O 层）
  ├─ get_factor_matrix()   z-score 归一化因子矩阵 {sym: {因子键}}
  ├─ get_pool(layer)       三层候选池（≤56 只，同指数去重+行业均衡+强制锚保障）
  ├─ get_market_regime()   市态标签
  └─ get_sector_momentum() 当日板块涨幅榜
        │ 纯数据注入（A1 round23 参数化，engine 不 import registry 私有态）
        ▼
engine.allocate(risk_profile, regime, factor_matrix, candidates,
                sector_momentum, factor_definitions, ic_series)     [纯函数]
  顺序生成 defensive→balanced→aggressive 三方案：
    每方案 = core/satellite/defense 三层各自 _select_and_weight()
             （锚注入@3% → segment 去重 → IC 加权聚合 → profile 权重 → C2 关键词修正
              → concept 组留最优 → 幂律权重 softmax(0.08) → 1%~30% 钳制）
    + ~10 段就地后处理（宽基上限/预算补顶/成长帽/U11 强制引入/科技配额/C2 注入 588000
      /防御锚门控/同指数去重/锚地板抬升/预算缺口均摊）
        ▼
risk_controls.apply_risk_controls(...)                                [纯函数]
    remove_stale(R77 全删保护) → 月跌剔除(-40%) → 防御减半(3m<-10%) → 小仓位合并(<2%)
    → 单只≤30% → 红利≤15% → 红利层归属 → F6 成长帽(核心预算×40%) → 9-F1 熊市压负分成长
    → 层预算钳制(超支缩放，释放额隐式转现金) → HHI 行业集中度 → Σ>1.0 归一化
        ▼
strategy_design.generate_enhanced_design（编排层，部分越界改权重，见 S7/D5）
    enforce_max_correlation(r≥0.9 合计≤25%，锚豁免+5%地板安全网)
    → apply_near_substitute_warnings(文本族无条件合并留一)
    → portfolio_concentration_check(平均 r>0.8 组合级告警)
    → wide_basis_high_corr_warnings(r>0.95 软提示)
    → check_structure_reasonableness(INV-3/5/6 运行时校验)
```

### 2.2 防线纵深盘点（现状有效的保护机制）

| 保护 | 位置 | 说明 |
|---|---|---|
| 强制锚·池层 | pool_balancing.ensure_mandatory(:136-160) + truncate_with_mandatory_protection(:163-170) | 扫描缺失时注入、截断保护 |
| 强制锚·引擎层 | allocation_engine:392-416 注入@3%、:1503-1533 地板抬到 5% | 现金优先、非强制标的按比例扣 |
| 强制锚·关联度豁免 | enforce_max_correlation:1721-1729 双锚仅标注、单锚 keep 方不削 | 防 A500/300 互削击穿地板 |
| 强制锚·尾部安全网 | :1815-1822 任一锚 <5% 强制抬回 | 防御性兜底（正常 no-op） |
| 数据故障防伪装 | risk_controls.remove_stale R77 全删保护(:173-192) | 全部无价量时跳过删除+WARNING，防 100% 现金假失败 |
| 相关矩阵缺失诚实 | correlation.py:11-12 <30 根标 None 不冒充；strategy_design E5 correlation_unchecked 标注 | 盘后不误报不静默 |
| 近替代品降级盲补偿 | apply_near_substitute_warnings 无条件执行（r=None 时标 unevaluated 待复算） | K 线不可用时仍控主题冗余 |
| 配置 fail-fast | budgets.py:184-186 导入期 build+validate，INV-1~4 违反即崩 | 杜绝配置倒挂静默产出 |
| 措辞守卫 | rationale.py:104 低相关措辞仅 median_r<0.3 允许；:96-102 core/defense 过滤"卫星"句 | 反「文案冒充数据」 |

---

## 3. 设计亮点（保持清单——重构中不得丢失的行为）

1. **纯函数引擎 + CI 门禁**：确定性、可重放、可单测（check_engine_purity.py AST 扫描）。
2. **单一真相源 + fail-fast**：ProfileSpec(frozen) 从 STRATEGY_META 构造，加载期校验。
3. **诚实降级贯穿**：None 不转 0（factor_registry R85）、stale/unavailable 显式标注、
   全删保护、correlation_unchecked、unevaluated——本方案的任何重构必须保持这些语义。
4. **强制锚四道防线**（§2.2 表）——纵深而非单点。
5. **不变量双保险**：加载期 INV-1~4 + 运行时跨方案 INV-3/5/6。
6. **归因可解释**：selection_rationale / factor_breakdown / 主驱动因子——D5 修复的正是
   该特性在生产路径的意外丢失。

---

## 4. 确证缺陷（bug 级，含证据与修复方向）

### 4.1 D1（🔴 门禁级）纯度门禁相对导入盲区

**现象**：`python scripts/check_engine_purity.py` 报 OK，但 engine 层实际依赖 app.analysis 包。

**根因**（两处对照即闭环）：

```python
# scripts/check_engine_purity.py:46-53 —— 只取 node.module，丢弃 level
elif isinstance(node, ast.ImportFrom):
    if node.module:
        yield node.module          # ← 相对导入时 = "analysis.signal"，无 "app." 前缀

# :68-70 —— 前缀匹配永远落空
for pkg in FORBIDDEN_PACKAGES:      # 含 "app.analysis"
    if name == pkg or name.startswith(pkg + "."):
```

```python
# backend/app/engine/rationale.py:238 —— 实际违规点（try 包裹 :250-259 有 fallback）
from ..analysis.signal import composite_signal
```

AST 中相对导入 `from ..analysis.signal import X` 的 `node.module == "analysis.signal"`
（包前缀由 level=2 隐式表达），`:68` 的 `startswith("app.analysis")` 永不命中。

**影响**：分层声明失真（README「zero dependencies outside itself」当前不实）；
未来任何经相对导入的上层依赖都不会被拦截。运行时本身无害——
`analysis/signal.py:14-51 composite_signal` 与 `_cap`(:4-11) 是纯函数（pandas 仅在同文件
更下方的 td_sequential 使用）。

**同名陷阱（实施必读）**：`engine/composite_signal.py` 是**另一个模块**——池层打分
`compute_composite(item, layer, regime…)`（层×市况权重表+流动性/规模百分位，供
market_data_hub 用），与本缺陷无关。下沉目标文件必须命名为 `engine/signal.py`，禁止
并入 composite_signal.py 造成语义混淆。

**修复方向（双管齐下）**：① 门禁解析 level（B1-F1a）；② `_cap + composite_signal`
下沉至 `engine/signal.py`，`analysis/signal.py` 头部改为
`from ..engine.signal import composite_signal, _cap  # re-export（上层→下层合法方向）`
保持既有调用点兼容，`rationale.py` 改 `from .signal import composite_signal`（B1-F1b）。

### 4.2 D2 MANDATORY_CODES 双份字面量集合

```python
# allocation_engine.py:294-296
CORE_ANCHORS = {"510300", "159338"}
DEFENSE_ANCHORS = {"518880", "511090"}
MANDATORY_CODES = CORE_ANCHORS | DEFENSE_ANCHORS

# engine/pool_balancing.py:25 —— 字面量重复定义
MANDATORY_CODES = {"510300", "159338", "518880", "511090"}
```

两文件同在 engine 包内（pool_balancing 自述「Dependency direction: engine <- hub/*」，
从 allocation_engine/budgets import 完全合法）。今日恰好一致，锚点增删时漂移是时间问题
（历史上 560600→159338 换锚事件证明过该集合会变）。另 risk_controls.py:63 在函数体内
延迟 `from .allocation_engine import MANDATORY_CODES`——第三处引用点。

**修复方向**：真相源上移 budgets.py（它已是 meta 单一真相源），allocation_engine
re-export 保兼容（risk_controls 调用点零改动），pool_balancing 删本地定义改 import（B1-F2）。

### 4.3 D3 _COMPANY_NAMES 双份副本**已经漂移**

```python
# allocation_engine.py:28-43 —— ~90 条，含 round19 P1-② 修复注释（长名优先）
_COMPANY_NAMES = ["华泰柏瑞", "柏瑞", "天弘基金", "广发基金", … , "金元顺安"]

# engine/pool_balancing.py:66-78 —— deduplicate_by_index 函数内局部副本 ~80 条
# 缺「华泰柏瑞/柏瑞/天弘基金/广发基金/金元顺安」等条目
```

除名单内容漂移外还有**行为差异**：pool_balancing 版替换前按长度降序排序
（`sorted(..., key=len, reverse=True)`，:79），allocation_engine 版按列表序迭代（:59-60）。
后者正是 round19 P1-② 修过的 bug 类（子串公司名先行剥除导致指数概念提取失败）——
当时靠手工把「华泰柏瑞」排前缓解，未根治。

**修复方向**：名单并集收敛单源 + 两处统一采用长度降序排序（严格更安全，属既有意图的
根治而非行为变更）；名称提取函数本身的统一放 B3 分类器合并（B1 先只共享常量，
控制爆炸半径）（B1-F3）。

### 4.4 D4 allocate 内基于 layer 名的 HHI 死计算

```python
# allocation_engine.py:1535-1540 —— 以 layer 名当“行业”算集中度
for a in allocations:
    sec = a.get("layer", "其他")          # ← core/satellite/defense，与持仓内容无关
    sector_weights[sec] = ... + a.get("weight", 0.0)
hhi = sum(w ** 2 for w in sector_weights.values())
# :1562-1567 写入 strategy["risk_metrics"]["sector_concentration"/"sector_breakdown"]
```

编排层紧随其后调用 `apply_risk_controls`（strategy_design:445-450），其内部用**真实
industry 字段**重算并整体覆盖 `strategy["risk_metrics"]`（risk_controls:389-403 计算、
:419-422 写入）。因此引擎侧计算恒为「层预算平方和」（同一 profile+regime 下近似常量），
对持仓完全不敏感——既误导中间调试，也是无效功。

**修复方向**：删除引擎侧该段（连同 ：1562-1567 的写入），sector_concentration 由
apply_risk_controls 单点产出。allocate 在测试侧有 20 文件 / 38 处 import·调用引用
（2026-08-22 grep 实测），删除后跑受影响测试：
若有用例直接断言 allocate 返回值里的 sector_concentration，属于「断言实现细节」，
改断言口径到 apply_risk_controls 之后（B1-F4，唯一可能触碰测试基线的 F 项，方案见 §6.1）。

### 4.5 D5 rationale 双写导致 O24 归因链在生产输出中丢失

```python
# 引擎侧 allocation_engine.py:655-672 —— 带 rank_info（排名 N/M + 主驱动因子）
rank_info = {"rank": selected.index((composite, cand, factor_scores)) + 1,   # ← O(n²) 且靠元组相等匹配，脆弱
             "total_candidates": len(scored),
             "dominant_factor": _dominant_factor(...)}
rationale = build_rationale(code=sym, layer=layer, strategy=strategy,
                            factor_scores=factor_scores, regime=regime,
                            rank_info=rank_info)          # 注意：meta 未传 → asset_name=裸代码
results.append({..., "selection_rationale": rationale})

# 编排层 strategy_design.py:466-475 —— 重调且【不传 rank_info】，整体覆盖
a["selection_rationale"] = build_rationale(
    code=code, layer=a.get("layer", "satellite"), strategy=s.get("id", "balanced"),
    meta=sym_meta, factor_scores=a.get("factor_breakdown", {}), regime=market_regime,
    industry=..., correlation_median=corr_medians.get(code))   # ← 生产最终生效的版本
```

**后果**：O24 特性（回答「为什么选它而非同类」的候选池排名 N/M + 主驱动因子）在最终
API 输出中不存在；引擎侧那次调用的 rank 计算是白做的，还生成了 asset_name 为裸代码的
中间文案。四问法审查：「生产 rationale 无排名归因」为事实（file:line 如上）；推断
「曾计划编排层透传但漏掉」无直接证据——无论哪种，双签名各说各话的现状应收敛。

**修复方向**：引擎把 rank_info 存入分配 dict（内部键 `"_rank_info"`，随 factor_breakdown
一起返回）；编排层 `build_rationale(..., rank_info=a.pop("_rank_info", None))` 转发；
顺带把 ：661 的 `selected.index(...)` 改为循环中直取下标（O(n) 且不依赖元组相等）。
前端/API 契约无字段变化（selection_rationale 本就是 str）（B1-F5）。

---

## 5. 结构性问题分级（非 bug，重构对象）

| # | 问题 | 证据摘要 | 危害 | 批次 |
|---|---|---|---|---|
| S1 | **上帝模块**：allocation_engine.py 1955 行；allocate() ~520 行、~10 段就地变异叠层（R101 宽基上限 ：1261-1289 → O16 预算补顶 ：1290-1319 → INV-4 成长帽 ：1320-1324 → U11 强制引入 ：1335-1368 → F0-5 科技配额 ：581-652 → C2 注入 ：1449-1473 → 同指数去重 ：1501 → 锚地板 ：1503-1533 → 缺口均摊 ：1545-1560），顺序约束仅存在于注释（如 risk_controls:54-56「顺序不可反」） | file:line 如左 | 新改动只能继续叠补丁；回归面无法局部推理 | B5（依赖 B4） |
| S2 | **中文子串分类器为核心语义层**：_is_wide_basis(:142-148)/_is_growth_wide_basis(:162-173)/_is_large_cap_wide_basis(:200-211) 三套"宽基"概念并存，各有排除词补丁（中证1000 排除词表 ：195-197、裸 A500/A50 补丁 ：189-190、R101 实测后补中证500 :187-188） | 同左 | 新 ETF 命名变化即误判；每类边界事故都要打补丁 | B3 |
| S3 | **六层冗余控制叠加**：池层 deduplicate_by_index(pool_balancing:57-133) → segment 去重(allocate:1177-1185) → concept 组留最优(_select_and_weight:543-556) → 同指数去重(_dedup_same_index:956-1026) → 关联度上限(enforce_max_correlation:1680+) → 近替代品族合并(_merge_substitute_family:847-914)。部分是有意的降级盲互补（K 线相关性盘后不可用时靠文本族），但组合语义无人说得清 | 同左 | 排查「为什么 A/B 没被合并」需通读六层 | B3 契约文档化（不合并代码） |
| S4 | **魔法数字散落**：c2_bonus ±0.8/±1.5/-0.3(:488-533)、softmax 温度 0.08(:348)、科技配额 40%/50%(:582)、TECH_MAX_COUNT=2(:584)、宽基上限 4(:1262)、卫星负分地板 -2.0(:565)、重叠惩罚 -1.5(:535-536)、相关性阈值 0.9(:1683)/0.95(:217)/0.8(:920)/0.35(:1871)、MANDATORY_MIN_WEIGHT 0.03(:300)/地板 0.05(:303) | 同左 | budgets.py 号称单一真相源却只覆盖预算/数量/growth_cap；调参需读全文找常量 | B3 |
| S5 | **profile 顺序耦合**：三方案顺序生成，aggressive 吃 balanced 的 -1.5 惩罚残留（_used_satellite 等 ：1161-1167、:1378-1393），输出依赖生成顺序 | 同左 | 无法并行/单方案请求；差异化效果难归因。属有意设计，记录为约束即可 | 记录不动 |
| S6 | **收益指标为静态常量**：expected_return/sharpe/max_drawdown 取自 STRATEGY_META（budgets:29-67），regime 微调 ±0.04 封顶（adjust_expected_return:288-297），与实际持仓无关；而编排层手里有真实 K 线相关矩阵（correlation.py）可估组合波动 | 同左 | 用户看到的是营销数字不是模型估计 | B6 渐进 |
| S7 | **权重再平衡三方案并存 + 跨段互破**：层内比例回补(:124-129,:209-214,:1001-1026)、剩余容量水填充(:1066-1083,:1296-1313)、缺口等分(:1551-1560)；apply_risk_controls 的 Σ>1.0 归一化(:406-410)可能击穿锚地板，靠 enforce_max_correlation 尾部安全网(:1815-1822)下游补救——「补丁治补丁」 | 同左 | 约束满足是偶然达成而非构造保证 | B5 reconcile |

---

## 6. 实施批次 B1-B6（实施细化）

> 通用纪律：TDD（先失败测试后实现）；测试命名按 round34 §11 规范
> （`test_{业务域}_{行为}.py`，docstring 带「round35 Dx (docs/round35-architecture-review.md §x.x)—」指针）；
> 开发期只跑受影响测试 + mypy，验收期 patrol 全量一次。

### 6.1 B1 —— P0 缺陷修复（D1-D5，~0.5-1 天）

#### F1a 门禁堵相对导入

**改动** `scripts/check_engine_purity.py`：

```python
def _iter_imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, 0
        elif isinstance(node, ast.ImportFrom):
            yield (node.module or ""), (node.level or 0)

def _resolve(module: str, level: int, pkg_parts: list[str]) -> str:
    """level=0 → 原样；level=n → 按文件所属包上跳 n-1 层拼接绝对路径。
    例：app/engine/rationale.py（pkg_parts=["app","engine"]）
      · from .budgets import X      (level=1) → app.engine.budgets   ✓合法
      · from ..analysis.signal import X (level=2) → app.analysis.signal → 命中禁入"""
    if level <= 0:
        return module
    base = pkg_parts[: len(pkg_parts) - (level - 1)]
    if not base:
        return module          # 超出顶层（engine 一级包结构不会出现），保守放行
    return ".".join(base + ([module] if module else []))
```

`check_file` 内由 path 计算 `pkg_parts`（path 相对 `app/` 的父目录拆分），
对 resolve 结果做原有前缀匹配。

**测试** `backend/tests/test_check_engine_purity_gate.py`：
- 正向：tmp_path 构造含 `from .budgets import X` 的伪引擎文件 → check_file 无违规；
- **负向**：构造含 `from ..analysis.x import y` 的文件 → 断言违规列表非空且消息含
  "app.analysis.x"（防「门禁静默通过」回归）；
- 边界：`from . import budgets`（module=None）→ 解析为 app.engine.budgets 合法。

#### F1b composite_signal 下沉

**改动**：新建 `backend/app/engine/signal.py`，原样迁入 `analysis/signal.py` 的
`_cap`(:4-11) 与 `composite_signal`(:14-51)（纯函数，无 pandas）；`analysis/signal.py`
头部加 `from ..engine.signal import _cap, composite_signal  # re-export 下沉兼容`；
`engine/rationale.py:238` 改 `from .signal import composite_signal`。
`composite_signal_with_gate` 留在 analysis（业务门禁语义属上层），自动经 re-export 生效。

**测试** `test_engine_signal_sink.py`：
- 平价：589720 案例 t=-0.408/v=-0.462/m=1.047 → signal="hold" 非 buy（双弱不判多回归锚）；
  cap 边界 m=9 → components.momentum==1.0；
- 方向：`grep -n "^from\|^import" app/engine/*.py` 无 app.analysis/app.services 前缀
  （脚本门禁为主断言，此为快速自检）；
- 兼容：`from app.analysis.signal import composite_signal` 旧路径 import 仍可用。

#### F2/F3 常量单源收敛

**改动**：budgets.py 增加 `CORE_ANCHORS / DEFENSE_ANCHORS / MANDATORY_CODES /
MANDATORY_MIN_WEIGHT / MANDATORY_FLOOR`（值原样搬移）；allocation_engine 改为
`from .budgets import ...` + 模块级 re-export（risk_controls:63 调用点零改动）；
pool_balancing.py:25 删本地字面量改 import。_COMPANY_NAMES 并集收敛至单处
（暂挂 allocation_engine，B3 迁 taxonomy.py），**两处提取函数统一改为长度降序替换**
（根治 P1-② 类子串剥除 bug，属既有注释声明的意图）。

**测试** `test_engine_anchor_single_source.py`：
- 一致性：`allocation_engine.MANDATORY_CODES is budgets.MANDATORY_CODES`（对象同一性，
  防再次复制）；pool_balancing.MANDATORY_CODES 同理；
- **负向**：monkeypatch budgets.MANDATORY_CODES 增加假锚 → pool_balanced 视野同步可见
  （若仍是独立副本则 FAIL——能抓住「改了一半」）；
- 名称提取：`_extract_index_concept("科创100ETF汇添富")=="科创100"`、
  `"沪深300ETF华夏"=="沪深300"`、"A500ETF华泰柏瑞" 不残留"柏瑞"（len-desc 排序生效）。

#### F4 删 layer 名 HHI 死计算

**改动**：删除 allocation_engine:1535-1540 计算块与 ：1562-1567 的 risk_metrics 写入。
**步骤**：先 grep 测试中对 `allocate(` 返回值 `sector_concentration` 的直接断言
（预期少量，属「断言实现细节」）→ 这些用例改为对 `apply_risk_controls()` 输出断言
→ 再删代码。若某用例断言的是「层权重平方和」这一具体数值，说明它在锁死实现——
按反假完成原则改写为行业口径断言，不保留双重口径。

**测试** `test_sector_concentration_industry_only.py`：
- 正向：apply_risk_controls 输出的 sector_concentration 与手算 industry-HHI 一致；
- **负向**：构造 industry 全缺失的持仓 → 断言 fallback 到 layer 的行为**有且仅有**一处
  （风控层），且 allocate 返回值不再携带 sector_concentration 键。

#### F5 rank_info 带出（恢复丢失功能）

**改动**：_select_and_weight 循环改为 `enumerate(selected)` 直取下标（消 ：661 的
`selected.index(...)`）；results dict 增加 `"_rank_info": rank_info`；编排层
strategy_design:466-475 增加 `rank_info=a.pop("_rank_info", None)` 转发。

**测试** `test_rank_info_in_production_rationale.py`：
- 正向：走完整编排流（mock hub 最小夹具）→ 最终 etfs[].selection_rationale 含
  「同类候选池排名 \d+/\d+」与「主驱动因子」；
- **负向**：若把编排层转发行注释掉（模拟回归），上述断言 FAIL（测试能抓假）。

**B1 验收**：`python scripts/check_engine_purity.py` OK；
`pytest tests/test_check_engine_purity_gate.py tests/test_engine_signal_sink.py
tests/test_engine_anchor_single_source.py tests/test_sector_concentration_industry_only.py
tests/test_rank_info_in_production_rationale.py` 绿；
patrol --diff 全绿；verify_e2e 不低于基线（M7 四连 FAIL 属 R105 已知非回归，B2 后转绿）。

### 6.2 B2 —— R104/R105（引用 round34，不重复）

按 `docs/round34-container-reacceptance-r102-r108.md` 既定细化执行：
R104 ic_tracker.get_sample_counts_by_code 聚合查询 + _factor_data_quality_report 参数化 +
strategy_design:924 调用点切换；R105 remove_stale_candidates 循环 MANDATORY_CODES 豁免
（先例 risk_controls:71）+ removed 日志。验收含 M7 e2e 四连 FAIL 转绿。
**依赖**：无（与 B1 可并行，建议 B1 先合避免同文件冲突——两者都触 strategy_design.py）。

### 6.3 B3 —— EngineConfig 收敛 + 分类器合并（1-2 天，前置 B4 快照先行）

#### F6 EngineConfig dataclass

budgets.py 新增 frozen dataclass，收纳 S4 全部散落数字（每个字段注明来源 file:line），
沿用 ProfileSpec 模式做加载期校验（新增 INV-7：阈值序合理性，如 wide_basis_warn 0.95 ≥
corr_cap 0.9 ≥ concentration_avg 0.8；tech_quota_defensive ≤ tech_quota_aggressive）。
allocation_engine 各消费点改为读 config。**不改任何默认值**——纯搬家。

#### F7 分类器合并

新建 `engine/taxonomy.py`：`classify_etf(meta) -> Classification`（dataclass：
wide_basis / growth_style / large_cap_family / tech_theme / substitute_family 五个布尔/
枚举标签），tracked_index 结构化字段优先、名称子串兜底、排除词表（中证1000 等）
单点维护；三个 _is_* 函数改为薄包装委托（保持既有 import 路径兼容，risk_controls:16
的 `_is_growth_wide_basis` 引用不断）。

**前置快照（可行性探针位）**：合并前先固化现行为——对 STATIC_CORE_POOL + 当前线上池
夹具逐只跑三个 _is_* + _substitute_family，输出 JSON 基线；合并后 diff 必须为空。
**测试** `test_etf_classification_snapshot.py`（基线对比）+
`test_taxonomy_edge_cases.py`（中证1000≠宽基族、裸 A500 命中、科创芯片 industry=半导体
不算 growth 宽基——历史事故案例全数入册）。

### 6.4 B4 —— 黄金快照回放 harness（~1 天，B5/B6 安全网，可与 B3 并行起步）

**范围界定**：只覆盖引擎纯层管道（allocate → apply_risk_controls → enforce_max_correlation
→ apply_near_substitute_warnings → check_structure_reasonableness），固定输入含
预构造相关矩阵——不进 generate_enhanced_design（那有 I/O，属 e2e 职责）。

**夹具** `backend/tests/fixtures/engine_golden/`：五组输入 JSON——
① 正常盘中（满因子+满相关矩阵）；② 盘后（corr_matrix={}，验证 unevaluated/
correlation_unchecked 路径）；③ 因子矩阵全空（静态池兜底入口前的纯层表现）；
④ bear regime；⑤ 稀薄池（触发 U11 强制引入 + F0-5 补足路径）。
每组附「预期特征清单」（如：三方案卫星数严格递增、锚权重 ≥0.05、无同指数双持）。

**runner** `backend/scripts/engine_golden_replay.py`：读夹具 → 跑纯管道 → 归一化输出
（权重 ε=1e-6、排序稳定化）→ 与快照 diff；`--update` 显式重生成（commit message 必须说明
动机）。接入 patrol.py 作为可选段 `--golden`（默认 diff 模式跑，不增 pre-commit 段——
遵循 round34 §13「不为常规项加门禁段」纪律）。

**验收**：五场景首跑建基线；人为注入一个扰动（如温度 0.08→0.09）→ diff 能报出全方案
权重漂移（**负向**：工具必须能红）。

### 6.5 B5 —— allocate 流水线化（3-5 天，独立轮，硬前置=B4 基线就绪）

将 allocate() 拆为显式五段纯函数管道，替代 ~10 段就地变异叠层：

```
select(budgets, pools, matrix) -> SelectionDraft      # 打分/去重/初选，不改权重
size(draft, budgets) -> SizedAllocations               # 幂律+钳制，一次性完成
constrain(sized, config) -> ConstrainedAllocations     # 宽基上限/成长帽/科技配额/锚地板
reconcile(constrained) -> FinalAllocations             # 【新增】终态求解：Σ=1、层预算、
                                                       # 单只上限、锚地板同时满足，残差报告
validate(final) -> warnings                            # 现 check_structure_reasonableness 吸收
```

关键收益点在 reconcile：S7 的三种再平衡并存与「归一化击穿地板→下游安全网补救」收敛为
一处构造性保证；每段输入输出为独立数据结构（不再共享 dict 就地改），段落间依赖显式化。
**迁移策略**：外壳 `allocate()` 签名与返回结构完全不变；内部逐段搬迁，每搬一段跑黄金
diff（必须为空）+ 受影响单测；U11/C2 注入等「补丁段」先原样搬入 constrain/reconcile
对应位置，行为等价后再谈简化（简化不在本批承诺内）。

### 6.6 B6 —— 收益指标持仓推导（渐进，不设截止）

编排层已有 correlation_matrix 时：组合波动估计 = wᵀ(σ⊙ρ⊙σ)w（σ 可先取分层历史波动
近似），替换/并列 STRATEGY_META 静态值；UI 标注来源（model_estimate vs reference_static）。
涉及 API 契约字段新增 → 按 AGENTS.md 契约先行流程走 api-contracts/portfolio/ 补契约。
本批不阻塞其它批次，作为 B5 后的性能/表达力增强独立推进。

---

## 7. 不做的事（防过度工程，评审重点核对项）

| 不做 | 理由 |
|---|---|
| ❌ 换均值方差/风险平价优化器 | z-score 化因子分不是协方差优化的合法输入；黑盒输出无法支撑 selection_rationale 可解释性；与项目确定性价值观冲突。现有「评分排序+幂律+后验约束」与产品定位匹配 |
| ❌ 大爆炸重写 allocate() | 2400 测试大量绑定中间行为，一次性重写必然引入语义漂移且无法二分定位。按 B5 分段 + 黄金 diff 护航 |
| ❌ ML 分类器替换关键词表 | ~百只 ETF 封闭集，tracked_index 结构化数据已足够；ML 引入不可解释性与训练维护负担，收益为负 |
| ❌ 合并六层去重代码 | 降级盲互补是有意冗余（盘后 corr=None 路径靠文本族兜底），强行合并会把最需要鲁棒的路径变脆。B3 只做契约文档化 |
| ❌ 为 round35 新增 pre-commit 门禁段 | 遵循 round34 §13 结论；黄金回放挂 patrol --golden 可选项即可 |
| ❌ 动 S5 profile 顺序耦合 | 有意差异化设计，当前无并行/单方案需求；记录为已知约束 |

---

## 8. 全局验收口径（各批共用）

1. `cd backend && python scripts/patrol.py --diff` 全绿；交付时 `--full` 一次。
2. verify_e2e ≥ 279/291 基线；M7 四连 FAIL 在 R105（B2）落地后应转绿，此后计入回归。
3. `python scripts/check_engine_purity.py` OK，且负向 fixture 用例（B1-F1a）证明门禁
   对 level=2 相对导入确实会 FAIL（门禁自身可被测试抓假）。
4. B4 落地后：`patrol --golden` 五场景 diff 为空；任何引擎行为变更必须有伴随的
   快照重生成 + commit 说明。
5. 全量测试用例数迁移前后不减（防「顺手删测试」）；mypy 零新增。
6. 反假完成 reality check：F5 修复后的生产 rationale 必须真实出现在 design API 输出中
   （rg 前端/详情接口消费 selection_rationale 确认链路，非仅单测引用）。

---

## 9. design-checklist 八项自查（docs/design-checklist.md）

| # | 检查项 | 本方案结论 |
|---|---|---|
| 1 | 可行性探针 | 引擎为纯函数，无外部数据假设需探测。等价性探针 = B3/B5 前置的分类器快照与黄金基线先行（§6.3/§6.4，先固化后动手）；门禁修复算法已在本档 §4.1 用两个真实 import 语句推演验证（rationale level=2 → 命中禁入；allocation_engine:16 `.budgets` level=1 → 合法） |
| 2 | 证据链 | 每个缺陷/问题均含 file:line + 关键代码摘录（§4-§5）；无「笼统感觉代码乱」类结论 |
| 3 | 验证窗口 | 全部结论无交易时段依赖（纯函数）；黄金场景②显式覆盖盘后 corr=None 路径；e2e/patrol 在实施期任意时段可跑（§0.3） |
| 4 | 非兜底数据 | 本方案不新增数据源输出；D5 修复恰是消除「理由文案丢失真实归因」的假完成；F4 删除的是误导性中间态而非功能 |
| 5 | 真实调用点 | 全部改动位于既有活跃调用链（allocate 49 callers / apply_risk_controls 16 callers / generate_enhanced_design 17 callers，codegraph blast radius）；signal 下沉经 re-export 保持旧路径兼容；无新增端点/函数 |
| 6 | 四态 UI | 后端纯层重构不涉 UI，豁免（B6 若动 API 字段将按契约先行 + 前端走查另行过此项） |
| 7 | 复杂度审计 | 零新增网络/DB/文件调用；B1-F1b 下沉反而消除一层跨包依赖；B5 目标即复杂度收敛（十段变异 → 五段纯管道） |
| 8 | 已知问题模式 | 对照 round14 五类盲区：主要触碰「格式断言」（F4 可能遇到断言实现细节的存量用例，处理策略已写入 §6.1-F4）；其余四类（mock 理想输入/契约盲区/CSS/降级无门禁）不适用——降级路径反而被黄金场景②纳入锁定 |

---

## 10. 排期、依赖与 round34 关系

```
B1(P0 缺陷, 0.5-1d) ──┬─→ B2(=round34 R104/R105, 已细化) ─→ M7 转绿
                      └─→ B3(EngineConfig+taxonomy, 1-2d) ←─ 快照先行
B4(黄金 harness, ~1d，可与 B3 并行起步)
B3 + B4 ──→ B5(流水线化, 3-5d 独立轮) ──→ B6(收益推导, 渐进)
```

- B1 与 B2 都触 strategy_design.py，建议 B1 先合；B3/B5 动引擎主体，必须在 B4 基线之后。
- round34 第一批（R104+R107）与本方案 B1/B2 天然衔接：R104 落地后 fdq 口径可信，
  B3 调参才有可靠观测面。
- 本文档为 round35 唯一轮文档；实施时按批次追加「实施结果」小节（commit + 验收输出），
  不新开 round36 文档直至 B5 独立轮（届时可拆分）。

---

## 11. 异步任务系统设计评估（2026-08-22 并行会话产物）

> 评估对象：`backend/app/tasks/`（task_manager / strategy_check_worker / design_report /
> market_refresh）+ `main.py` lifespan 后台编排（:340-1031）+ WS 推送层（routers/ws.py）+
> 任务提交端点（routers/portfolio.py:360-479）。方法：符号索引定位 + 核心文件全量阅读
> （task_manager.py 634 行 / strategy_check_worker.py 286 行等）。
> **结论仅入档未实施**；与本方案 B1-B6 批次零文件交集，不影响排期（§11.4）。
> 验证窗口：代码级静态评估，无交易时段依赖。

### 11.1 总体判断

**架构方向正确且成熟度高于典型同规模项目**——与引擎层评估（§0.1）同构的结论：
债务不在范式选型而在实现细节。三类异步子系统职责划分清晰：

| 子系统 | 组成 | 现状 |
|---|---|---|
| 用户长任务 | TaskManager(DB-backed) + design/check worker + WS 推送 | 核心链路健康 |
| 常驻刷新循环 | sector 60s / regime+sentiment 120s / news 120s / IC 120s / health 120s | 手写 while True，生命周期管理薄弱（P0-2） |
| 启动预热编排 | 串行 sequence + 预算门禁 + profiler | 最完善（O2/F3b/R44/R59④ 多轮打磨） |

**设计亮点（应保持）**

| 设计 | 证据 | 价值 |
|---|---|---|
| DB-backed 任务状态（Z27） | task_manager.py:62-88；重启恢复 main.py:704-725 | tasks 表唯一真相源，重启后非终态诚实标 failed，不留僵尸 pending |
| quick_ready 渐进状态机 | task_manager.py:429-433 | 方案秒级可见，不等 240s LLM 报告 |
| 分层超时 + 三级降级链 | 90s 数据 → skip_refresh 30s → 静态降级（task_manager.py:27-30, :300-345） | 盘后/冷启动永远有可用输出且诚实标注 degradation |
| 反假完成占位检测 | task_manager.py:513-526 `_FAIL_PLACEHOLDERS` / `_ENGINE_FALLBACK_MARKERS` | LLM 兜底文案不得标 quality=full，与仓库纪律一致 |
| 全局 LLM 信号量 | task_manager.py:49 + strategy_check_worker.py:73 | 防 DeepSeek 配额并发打满 → 429 级联 |
| 预热串行化 + 预算门禁 | main.py:542-575（O2/F3b） | 修复过真实线程池饱和回归（round7 64/64 饱和） |

### 11.2 问题清单

#### P0 —— 真实缺陷（建议优先修）

1. 🔴 **用户任务 fire-and-forget 无强引用**：portfolio.py:407 / :436 直接丢弃
   `asyncio.create_task()` 返回值。事件循环对 task **只持弱引用**，未被引用的任务可能
   被 GC 中途回收——design 任务全程最长 ~6 分钟（90+30+240s），风险窗口不小。
   main.py:359 预热处已有正确写法（`app.state._market_warmup_task` + 注释「强引用防 GC
   回收未完成任务」），说明坑已知但未应用到路由层用户任务。修复成本一行级。
2. 🔴 **常驻循环吞 CancelledError + 关停不优雅**：6 个后台任务（health_loop main.py:619 /
   sector :631 / regime :644 / news :667 及内嵌 enrich :661 / IC 持久化 :787 /
   IC 回填 :924）全部：① 裸 create_task 不存引用（同问题 1）；②
   `except (Exception, asyncio.CancelledError)` 捕获后 continue——Python 3.8+ 的取消请求
   被静默吞掉，未来显式 cancel 会发现取消不掉；③ shutdown 段（main.py:978-983）只关
   scheduler/token_store/source_event_store，循环靠 loop 关闭隐式兜底，DB 写入可能被
   拦腰截断。
3. 🔴 **WS 推送超时策略不一致**：TaskNotifyManager.broadcast（task_manager.py:192-203）
   与 DesignReportManager.broadcast（design_report.py:32-43）都是裸 `await send_text()`，
   而 ConnectionManager（ws.py:64）有 5s wait_for 保护。`_notify` 在 pipeline 内
   inline await——TCP 缓冲僵死的客户端会阻塞广播循环，进而阻塞整个 design_pipeline 的
   stage 推进甚至终态落库与完成通知。

#### P1 —— 体验与一致性问题

4. 🟠 **全局信号量排队无反馈**：design 与 check 共享 `Semaphore(1)`
   （task_manager.py:49 + strategy_check_worker.py:73）。LLM 报告最长占锁 240s，
   期间所有新任务排队；排队中的任务停留 `pending`，无队列位置、无预计等待
   （task_manager.py:264 的 waiting 日志用户不可见）。另外没有按参数去重——相同参数
   连点两次会排两个完整管线。
5. 🟠 **无任务取消机制**：用户无法取消已提交的任务（卡在 LLM 240s 里只能干等）。
   `TASK_TYPES` 里的 `ttl: 600`（task_manager.py:51-55）是 Z27 从 JSON TTL 改 DB 后
   遗留的死配置——要么实现要么删（§12.5-P2#2 同一登记，实施时一并处理）。
6. 🟡 **死代码**：strategy_check_worker.py:20-61 `_generate_check_llm_report` 与
   :245 `_generate_check_llm_comment` 功能重复，前者全仓库零调用点（仅定义处命中）。
   按脚手架零容忍条款应删除。

#### P2 —— 卫生问题

| 问题 | 证据 | 说明 |
|---|---|---|
| 读路径执行清理 | list_tasks → prune_tasks()（task_manager.py:166） | 前端轮询 GET /tasks 时每次触发 DELETE 扫描，写放大小但没必要，可节流到分钟级 |
| 文档漂移 | market_refresh.py:1-5 | docstring 称「APScheduler 每 3 秒拉取、写 Redis + WS 推送」——scheduler 已禁用、无 Redis 写入、无 3s 循环，实际只做 portfolio 频道广播（§12.7-B 第一步删除该文件调度入口时一并重写） |
| 注释尸体 | main.py:597-616 | 「Scheduler temporarily disabled for diagnostics」整块注释——§12.7 已决策 B 案，随第一步删除，不再二选一 |
| 逐 stage DB 往返 | update_task 每次开新会话 | 一条管线 ~10 次顺序会话开关；单用户 SQLite 下可接受，记为已知性能债即可 |

### 11.3 优化建议（按投入产出排序）

| # | 改动 | 解决 | 规模 |
|---|---|---|---|
| 1 | 统一后台任务容器：模块级 `set[asyncio.Task]` + `add_done_callback(tasks.discard)`；路由层 worker、6 个 lifespan 任务、news enrich 子任务全部注册；shutdown 时逐个 `cancel()` + `gather(return_exceptions=True)` 优雅收尾 | P0-1/2 | ~30 行 |
| 2 | 循环异常处理改只捕 `Exception`（CancelledError 自然传播），配合容器实现真正可关停 | P0-2 | 数行 |
| 3 | 两个 notify manager 加 5s `wait_for`，死连接即摘除——模式照抄 ws.py:64 | P0-3 | ~10 行 |
| 4 | 任务取消 API：有了任务容器后可直接按 task_id cancel；DB 记 status=cancelled + worker 捕获 CancelledError 落终态 | P1-5 | 小 |
| 5 | 排队可见性：acquire 信号量前先写 `stage="排队中"` 并推 WS；可选按参数哈希对活跃任务去重 | P1-4 | 小 |
| 6 | 卫生批：删 `_generate_check_llm_report` / ttl 字段 / APScheduler 注释块，修 market_refresh docstring 与 README 架构表 | P1-6/P2 | 小 |

### 11.4 与 B1-B6 批次的关系、选型结论与验收口径

- **零文件交集，可并行排期**：本节改动域 = tasks/ + main.py lifespan + WS 推送层；
  B1-B6 = engine/ + strategy_design.py 编排交界。唯一共同触点 strategy_design.py 在
  本节仅作为调用方阅读、不改动。两主线互不阻塞。
- **选型结论：不引入 Celery/arq 等外部队列**——单机 SQLite、单用户场景下进程内
  asyncio 是对的选型，重队列只会增加部署面和故障面。这套系统的问题不在架构选型，
  而集中在进程内任务的生命周期管理细节：强引用、取消传播、慢客户端背压三处，
  恰好都是低成本高回报的修复。修完 P0 后整体设计就相当扎实了。
- **验收口径（实施时）**：patrol --diff 全绿 + verify_e2e 不低于 279/291 基线；
  存量并发用例（test_concurrency_guard / test_restart_persistence_two_instances /
  test_startup_recovery_marks_stuck_failed 等）不回归；新增负向用例
  （如「shutdown 后无 pending 循环存活」「慢客户端不阻塞 pipeline 推进」）。
- **已知债登记**：update_task 逐 stage DB 往返（P2）记入性能债清单，本轮不处理。

### 11.5 实施细化（P0 三项 → 可实施粒度）

#### T-① 后台任务容器（解 P0-1 强引用 + P0-2 取消传播）

**新模块** `backend/app/core/background_tasks.py`（~40 行）：

```python
"""进程内后台任务容器——强引用防 GC + 优雅关停（round35 §11-T-①）。"""
import asyncio

_tasks: set[asyncio.Task] = {}

def spawn(coro, *, name: str | None = None) -> asyncio.Task:
    """替代裸 asyncio.create_task：注册强引用 + 完成自动摘除。
    lifespan 常驻循环与路由层用户任务提交全部改走此入口。"""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task

async def shutdown_all(timeout: float = 10.0) -> list[Exception]:
    """lifespan shutdown 调用：逐个 cancel → gather 收尾。
    CancelledError 是正常取消路径，不计入异常。"""
    for t in _tasks:
        t.cancel()
    results = await asyncio.gather(*_tasks, return_exceptions=True)
    errs = [r for r in results
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError)]
    _tasks.clear()
    return errs
```

**接线点**（全量清单，防改一半）：

| 现状调用点 | 改法 |
|---|---|
| main.py:619/:631/:644/:667（health/sector/regime/news 循环）+ 内嵌 enrich :661 | `spawn(loop_xxx(), name="loop-health")` 等 |
| main.py:787/:924（IC 持久化/IC 回填） | 同上 |
| routers/portfolio.py:407/:436（design/check 用户任务） | `spawn(worker(...), name=f"task-{task_id}")` |
| market_data_hub.py:529 `_asyncio2.create_task` | 并入容器顺带正名（§13-C5 补遗） |

**配套改动**：① 六个循环的 `except (Exception, asyncio.CancelledError)` 改为只捕
`Exception`（CancelledError 自然传播，取消才真正生效）；② lifespan shutdown 段
（main.py:978-983）在关闭 scheduler/token_store 之前调 `await shutdown_all()`，
返回异常列表打 ERROR 日志；kline 缓存 flush 挂在其后（§12-P0-3 的管线侧要求在此落地）。

**测试** `test_background_tasks_container.py`（含负向）：
- 正向：spawn 的任务完成后集合自动清空（无泄漏）；
- **负向①（抓 GC 回收）**：构造仅弱引用场景对照——裸 create_task 引用丢弃 vs spawn
  注册，前者可被模拟回收路径中断、后者必须存活至完成（锁定强引用语义）；
- **负向②（抓取消吞没）**：spawn 一个 while True 循环 → `shutdown_all()` → 断言任务
  终止且耗时 < timeout（旧实现吞 CancelledError 会拖满超时——本测试对旧代码必红）；
- 边界：空集合上调 shutdown_all → 立即返回空列表。

#### T-② WS 推送背压统一（解 P0-3）

`task_manager.py:192-203` 与 `design_report.py:32-43` 两处 broadcast 的裸
`await send_text()` 改为 ws.py:64 同款模式：`await asyncio.wait_for(ws.send_text(p), timeout=5)`，
超时/异常客户端本轮标记、循环后统一摘除（不在迭代中删集合元素）。

**测试** `test_ws_broadcast_backpressure.py`：
- **负向**：mock 一个 send_text 永挂起 + 一个正常客户端 → 正常端仍收到消息、僵死端被
  摘除、广播总耗时 ≈5s 封顶（旧实现永久阻塞——对旧代码必红）；
- 正向：全健康客户端均收到且顺序一致。

---

## 12. 数据管线设计评审 + 调度二选一决策（并行会话产物，2026-08-22）

> 本节为独立并行会话产物（与 §0-§10 策略引擎评估同日）：对 **fetchers 源层 → market_data_hub
> 编排层 → factor_registry 因子消费层** 三层数据管线的架构评审，及 APScheduler「恢复 vs 删除」
> 专项决策。方法：三路 explore 并行探查 + 基础设施一手审读（`cache_service.py` / `async_utils.py`
> / `hub/_kline.py`）。纯评审零代码改动。全部结论 `file:line` 实证。

### 12.1 总体结论

**架构分层合理**：「fetchers（多源降级）→ hub（统一管道+缓存+调度）→ factor_registry（纯计算）」
三层职责清晰，降级语义层层递进且**无假数据政策执行到位**。主要短板集中在「运维一致性」（死调度、
关停清理）与「并发防护均匀度」（单飞、缓存上限），而非骨架问题。

四类系统性问题：①调度层死链路；②并发防护不均匀（全库仅一处 single-flight）；③缓存无界增长；
④caller-wraps 约定脆弱。

### 12.2 设计亮点（保持清单——后续优化不得丢失的行为）

| 设计 | 实证 |
|---|---|
| 多源降级+熔断：优先级链、冷却指数退避 60→600s、快速失败(<500ms)即熔断、空结果=miss≠failure | `core/source_registry.py:33-62, 248-263` |
| 降级链完整且诚实：源级熔断 → hub 保 last-good+`_degraded` 标记 → T-1 SQLite 快照 → 静态池+`degradation.mode` 显式标注 | `market_data_hub.py:444-505`, `strategy_design.py:342-402, 962-1011` |
| 双线程池隔离：64 workers 快池 vs 8 workers 长任务池，队列深度饱和监控 | `core/async_utils.py:20-24, 103-114` |
| kline 缓存冷启动治理：磁盘 JSON 原子落盘(tmp+os.replace)、全失败轮也刷 mtime 防 TTL 误杀(R68)、长池隔离防饿死(R68) | `hub/_kline.py:184-200, 307-340` |
| 无假数据政策 IC 侧闭环：零值过滤按因子差异化容差(1e-6/0.001)、zero_ratio 追踪、signal_absent 防幸存者偏差 | `ic_tracker.py:220-243, 318-319` |

### 12.3 P0 正确性/可靠性

**P0-1 调度器禁用形成死链路** 🆕 —— APScheduler 整块注释（"Scheduler temporarily disabled
for diagnostics"），`app.state.scheduler = None`（`main.py:597-616, 670`）。后果：
`tasks/market_refresh.py::refresh_market_cache`（行情→WS 广播）不再周期运行，仅 warmup 执行一次；
README 承诺的「5-15s 行情缓存刷新」完全靠请求驱动兜底。专项决策见 §12.7。

**P0-2 `_TIMEOUT` 模块级遮蔽 bug** 🆕 —— `global_markets_fetcher.py` 中 `_TIMEOUT = 10`
定义三次(:380/:481/:587)，随后 FRED 段 `_TIMEOUT = 15`(:842) 在 import 时覆盖为最终值。
AV/TwelveData/Finnhub 的 fetch 函数在调用时读模块全局 → 实际超时全是 15s 而非设计的 10s。
修复方向：改为每源常量（`_AV_TIMEOUT = 10` 等），一行修复消除歧义。

**P0-3 后台循环吞 CancelledError + 关停不清理**（= §11 P0-2 同一问题：§11 列的是 6 个
create_task 调用点 main.py:619/:631/:644/:661/:787/:924，本条列的是对应 except 行
:628/:641/:664/:746，同一批循环的两个切面；修复以 §11.3 建议 #1/#2 统一任务容器为主，
本条补充管线侧要求：shutdown 时 kline 缓存 flush）—— 四个循环的
`except (Exception, asyncio.CancelledError)` 把取消也吞了（`main.py:628, 641, 664, 746`）；
shutdown 只关 None 调度器，循环任务未跟踪未取消、缓存未 flush（`main.py:976-983`）。
修复方向：except 分支拆开（CancelledError 应 re-raise 或 break）；shutdown 显式 cancel 循环 task 集 + flush kline 缓存。

**P0-4 因子矩阵疑似双重计数** 🆕 —— `refresh_pool` 把 `aggregate_factor_scores` 的结果
（顶层聚合键 + 原始 dot 键都保留，`core/factor_aggregate.py:120`）写入 pool 的 `factor_scores`；
`get_factor_matrix` 再对所有数值键做截面 z-score（`hub/_pool.py:142-155`），数值过滤不排除
`{code}_raw` 键（而 `factor_aggregate.py:127-128` 排除了）→ `technical.macd.macd`、聚合键
`technical`、`*.macd_raw` 可能同时进入矩阵，MACD 类信号在下游分配权重中被隐性叠加。
修复方向：`get_factor_matrix` 白名单化输入键（或复用 aggregate 排除规则），并核对
`strategy_design.py:324` / `strategy_check.py:1044` 两个消费方预期口径。

**P0-5 round34 已知 R 系列根因补充实证**（方案已定稿于 round34，此处仅确认根因）：

| 编号 | 本轮补充实证 |
|---|---|
| R104 口径分裂 | fdq 用内存截面计数(`strategy_design.py:1074`)，`/factors/active` 用 DB distinct trade_date(`routers/factors.py:145-158`)，同阈值不同分母 → warn=0 vs warn=12 |
| R108 回填丢列 | 列收集只取 close+dates(`main.py:851-858`)，truncated 重建时 open/high/low/volume 全空(`main.py:882-893`) → 7 因子历史 IC 永久缺失 |
| R106 无守卫 | `fund_fetcher.py:76` 入口仍无 6 位数字校验 |

### 12.4 P1 性能债（软门禁，登记排期）

**P1-a 缓存击穿无 single-flight**：全库唯一单飞是 spot 列表 `_spot_inflight`
（`china_market.py:961-988`）。行情 miss 无去重：`get_realtime_batch` 并发 miss 各自触发
`fetch_a_stock_batch`（`market_service.py:1091-1117`）；3s `_asset_realtime_cache` 同为
"读穿透、fetch 后才写"。建议抽象 `with_singleflight(key, factory)` 工具套住 quote batch /
asset realtime / refresh_kline 三个热点——与 r34-B4（round34 §10「indices/tasks 收敛
store 单飞」）同主题，可合批。

**P1-b N+1 逐符号 IO**：

| 位置 | 规模 | 现状缓解 |
|---|---|---|
| `_enrich_symbol_extra`：benchmark+shares 双任务 | 66 符号 ≈ 120 任务，Sem(8)+60s 总闸（`hub/_kline.py:383-437`） | 有界但重 |
| `_compute_fund_flow` | 池内每符号 1 次，Sem(8)/8s each（`strategy_design.py:808-816`） | 有界 |
| `refresh_kline` | 每符号 1 次 fetch_history，20s each（`hub/_kline.py:290-305`） | Sem(5) |
| IC 回填 `compute()` ×500 天 | CPU 密集驻留事件循环，仅 `sleep(0)` 让步（`main.py:877-903`） | 无 |

shares 逐符号抓取正是 round34 S-A（FundShareSnapshot 快照表）要解决的问题——实施 S-A 即顺带
消解该项大头；IC 回填建议移入 `run_sync_long`。

**P1-c 缓存无界增长**：`_kline_cache_rows` 只增不删（symbols union，`hub/_kline.py:326`）、
`_kline_stale_flags` 永不清理（`:26`）、`_FUND_SHARES_CACHE` 条目永不清除（`:73-76`）、
`_simple_cache` 无任何修剪（`market_service.py:26`）、`MemoryCache` 过期条目仅被读时惰性清除
无后台清扫（`cache_service.py:17-27`）。建议统一加 size cap/LRU；配合已规划的
`data/patrol_factor_growth.json` 快照停滞判定（round34 §10 P0）形成增长可观测。

**P1-d sentiment/news 双源分歧**：pool 的 `sentiment.news_heat` 等由 `refresh_pool` 事后注入
市场级新闻值（`market_data_hub.py:358-384`），而 `compute()` 走 F12 逐股新闻链
（`factor_registry.py:1315-1334`）——两条路径可产生不一致的同名因子；且 `news_heat` 未列入
`MARKET_LEVEL_FACTOR_CODES`（`routers/factors.py:85-96`），降级为市场级时仍参与 IC 统计。
建议明确唯一权威路径，另一路只读不写。

### 12.5 P2 代码卫生（顺手清）

| # | 问题 | 实证 |
|---|---|---|
| 1 | 合并残留：孤儿 NAV 注入循环落在第一个 except 内（幂等但死代码）+ 第二个 except 兜 NameError | `factor_registry.py:1270-1275` |
| 2 | 死变量/死配置：`_etf_list_cache` 定义未用；`TASK_TYPES.ttl=600` 声明未用 | `etf_scanner.py:25`, `task_manager.py:51-55` |
| 3 | 「TODO 未接入前端」×3 个已注册端点（脚手架零容忍清单候选） | `routers/market.py:518, 628, 692` |
| 4 | deprecated `_fetch_market_data` 标注 Phase 20 移除但仍可达，且其空结果计 failure 与 `route()` miss 语义相悖 | `factor_registry.py:1155-1161, 1204→1231` |
| 5 | 编码缺口：`sector_fetcher` akshare 助手直接取中文列名未经 `_decode_df`；`sync_indices_meta` hk/ths 函数同样裸取——akshare 返 latin1 乱码时静默取空 | `sector_fetcher.py:58-222, 315-342`; `sync_indices_meta.py:71-152` |
| 6 | 弱线程安全：Finnhub 配额计数 list 无锁；共享 requests.Session 多线程 GET；若干模块级 dict 无锁（CPython 原子读写下属可接受，登记即可） | `global_markets_fetcher.py:600-609`; `news_fetcher.py`; `hk_hot_fetcher.py` |
| 7 | 嵌套 run_in_thread 三层（margin_change→margin_balance→_fetch_szse→_p），每次白耗 2 个线程位 | `fundamentals_fetcher.py:1006, 738, 697` |

### 12.6 结构性建议（非紧急，方向级）

1. **统一缓存原语**：当前四套并存——`memory_cache`(L1)+`redis`(L2)、fetcher 层
   `sync_memory_cache`、hub 实例 dict、各模块散装 dict。TTL 表虽集中在 `core/ttl.py`，
   但 hub 各 mixin TTL 全部硬编码散落。收敛为一个带容量上限 + 统计埋点的缓存原语供四处复用。
2. **single-flight 标准化**：一个 `with_singleflight(key, factory)` 工具替换散落的
   lock/event 手写模式（现仅 china_market 一处）。
3. **caller-wraps 加固**：fetcher 层大量 sync def 裸调 urllib/akshare/yfinance，依赖
   「调用方包 run_sync」口头约定（`audit_async_blocking` 只查 async def 内部）。给裸 IO 函数加
   `@blocking_io` 标记或 lint 规则，防新增调用方漏包。
4. **可观测闭环**：round34 §10 P0 的 startup_behavior.json + factor_growth 快照落地后，
   「冷启动时长 / 缓存增长 / 源健康」三项形成巡检闭环，§12.4 各项从此有基线数据。

### 12.7 调度二选一专项决策（建议 B 案）

#### 12.7.1 决定性的三个实证

1. **禁用原因可考**：`git log -S "Scheduler temporarily disabled"` 定位到 `2be9ccb`
   （2026-07-24，"fix: resolve event-loop blocking … unify thread-pool architecture"）。
   调度器是在**事件循环阻塞 + 线程池饱和治理**（design-check-pipeline-redesign，即 mootdx
   空转→64 worker 打满的 R6-F10 危机期）中被注释掉的。至今一个月无人回切。
2. **`/ws/portfolio` 不是死信道**：`portfolio_changed` 广播存活且承重——
   `routers/portfolio.py:34-45` 增删改持仓/apply-design 时广播，前端 `market.js:107-113`
   消费做多标签页 1s 防抖同步。死的只是 market_refresh 的**定时 realtime 行情推送**。
3. **前端有「等推送」的死消费端**：`market.js:88-104` 专门为 `{type:'realtime'}` 格式写的
   分支已静默一个月；行情更新实际靠 REST TTL 轮询兜底。

#### 12.7.2 方案对比

**方案 A：恢复调度器**

| 收益 | 风险 |
|---|---|
| 真·主动推送 UX；前端消费端现成（`market.js:91-104`）；多标签页共享一次刷新 | **复活禁用时的原始问题**——当初正是在池饱和危机中砍掉，恢复=推翻稳定性结论且无新证据 |
| 数据新鲜度与流量解耦 | **空闲空转打源**：7×24 每 3~15s 全组合批量 ≈ 每天 1~3 万次免费源调用，封禁风险放大，非交易时段纯浪费 |
| README 口径不动 | 双调度范式并存（裸 asyncio 循环 + APScheduler 长期共存） |
| 负载平稳可预测 | 前置依赖未修（P0-3 CancelledError/shutdown） |

**方案 B：删除定时推送链路（维持请求驱动）**

| 收益 | 风险 |
|---|---|
| 零空闲负载——契合最硬约束「data layer has to survive flaky providers」 | `market.js:88-104` realtime 分支变死代码需同步清理 |
| 符合脚手架零容忍；消除「文档说有、运行时没有」的不一致源 | 多标签页不搭车（A 页拉取不惠及 B 页）——但这是已运行一个月的现状，非新增损失 |
| 一个月运行实证稳定；删除只是把现实写进代码与文档 | 冷启动首呼延迟由第一访问者承担（warmup+kline 磁盘缓存+last-good 三层已缓解） |
| 维护面变小；无需先修 P0-3 即可安全落地 | 未来多客户端/常开大屏场景需重新设计（届时 B4 单飞本就是前置） |
| | 删除边界必须精准：只删 market_refresh 调度与 realtime 广播，**绝不碰 portfolio_changed**（独立在 routers/portfolio.py） |

#### 12.7.3 建议：B 的强化变体（两步实施）

推荐理由（按权重）：①收益不对称决定性——A 的核心收益（无人访问时的热数据）在自托管单用户
盘中使用场景几乎不存在，核心成本（空转打源封禁）却全额存在；②禁用语境即池饱和治理的一部分，
一个月无回切诉求说明请求驱动已被实际接受；③ETF 决策粒度下 15s TTL 轮询足够。

- **第一步（纯删除，~0.25 天）**：删 `main.py:597-616` 注释块 + `app.state.scheduler=None`
  (:670) + `tasks/market_refresh.py` 调度入口与 realtime 广播 + `market.js:88-104` 死分支 +
  文档同步（README 架构图 market_refresh 行 / AGENTS.md / api-contracts ws/portfolio 契约
  realtime 段）。**红线：portfolio_changed 一行不动。**
- **第二步（可选增强，~0.5 天）：事件驱动推送**——把 realtime 广播从定时驱动改为回源事件驱动：
  挂在 `get_portfolio_realtime` 15s 缓存实际回源成功之后（`market_service.py:1132` 一带），
  谁触发刷新就向所有连接广播一次。有人看才推、推的是刚回源的新数据；正好补上 B 唯一的真实损失
  （多标签页搭车：A 页拉取 → 广播 → B 页自动更新）；前端消费端无需改动。

决策树：

```
单标签页使用为主          → 纯 B（第一步即可）
常开多标签页 / 未来多客户端 → B + 第二步（事件推送）
出现「无人访问也要热数据」真需求 → 才考虑 A
                             └─ 且必须：交易时段门控 + 先修 P0-3 + 池饱和监控确认
```

### 12.8 与 round34 / §0-§10 批次对照

| 发现 | 归宿 |
|---|---|
| R103/R104/R106/R108 根因实证（§12.3-P0-5） | ✅ round34 已有实施方案（第一/二/四批），本轮仅补证据 |
| shares N+1（§12.4-P1-b 部分） | ✅ 将被 round34 S-A（FundShareSnapshot）顺带解决 |
| quote 单飞（§12.4-P1-a） | ⚠️ 与 r34-B4（round34 §10 前端批次「indices/tasks 收敛 store 单飞」）同主题，建议合批 |
| **P0-1 调度死链路、P0-2 _TIMEOUT 遮蔽、P0-3 CancelledError 治理、P0-4 矩阵双重计数、§12.5 卫生批** | 🆕 新发现，round34 与 §0-§10 均未覆盖，需新立项（单项均 ≤0.5 天，P0-3 约 0.5-1 天） |

### 12.9 验收口径（若实施 §12.7 第一步）

1. `verify_e2e` 全 PASS（≥279/291，M7 四连 FAIL=R105 已知非回归）+ `patrol --diff` 全绿；
2. 多标签页手工走查：改持仓 → 另一标签页 1s 内自动刷新（确认 `portfolio_changed` 未被误伤）；
3. `grep` 确认 market_refresh 无残留调用点（反假完成清单第 1 条）；
4. 启动日志不再出现 scheduler 相关告警；`/health` 正常。

---

## 13. 全后端架构评估（2026-08-22 追加：异步阻塞 / 数据缓存 / 分层耦合）

> 本节覆盖前述各节之外的**横切面**：①并发正确性总检（同步阻塞实锤 / 超时覆盖 / 线程池参数 /
> create_task 卫生）②数据持久化拓扑与缓存一致性 ③分层违规与配置管理。方法：三路 explore
> 并行探查 + 官方两道 AST 门禁复核 + 扩展模式补扫。与 §11（任务系统）、§12（数据管线）
> 重叠的发现直接交叉引用不重复展开。全部结论 `file:line` 实证；纯评审零代码改动。
> 问题编号 A1-A5（P0/P1 必修排期）、C1-C8（记录在案），与 D/S/B/F 编号体系互不冲突。

### 13.1 总体判断

**架构总体合理且工程纪律高于同规模项目平均水准**——分层意图清晰、纯函数引擎有 AST 门禁、
~240 测试文件 + pre-commit 15 段门禁 + patrol 编排是真实资产（口径详见 §16）。真问题集中在
**两个全新隐患**（A1 数据完整性 / A2 分层死结）+ 门禁盲区若干；不需要独立的「架构轮」，
按 §13.7 搭既有批次即可。

### 13.2 保持清单（务实取舍，明确不动）

| 设计 | 判定理由 |
|---|---|
| SQLite ×3 文件而非 PG/MySQL | 单用户本地工具量级匹配，换库纯成本无收益 |
| 单进程 asyncio 循环而非 Celery/MQ | 与 §11.4 选型结论一致；design/check/report 三型 worker 的量级不需要分布式任务系统 |
| 预热序列串行化 + 三级诚实降级（R59④/R69） | 面对不可靠外部源的正确姿势，实战打磨产物 |
| run_sync 线程池包裹同步 IO | 方向正确，问题只在池参数（A3），不在范式 |
| 函数体内 lazy import 破环 | Python 解循环依赖的常规手段；密度高指向模块边界该拆，而非 import 方式本身错误 |

### 13.3 P0 —— 现在就该修（合计 ~1 天）

#### A1（🔴 数据完整性）portfolio.db 双写者且无 WAL —— 全新发现

同一 `portfolio.db` 存在两条独立写入路径：

```python
# database.py:28-33 —— SQLAlchemy 引擎（默认 AsyncAdaptedQueuePool：pool_size=5 + max_overflow=10）
create_async_engine(settings.database_url, echo=False, connect_args={"timeout": 30})

# hub/_common.py:122-142 —— 裸 sqlite3 直连写同一文件（经 to_thread，_snapshot.py:38/:42 触发）
conn = sqlite3.connect(db_path, timeout=10)   # 写 market_snapshots
```

- 全仓无任何 `PRAGMA journal_mode=WAL`（仅 verify_e2e.py 查过 table_info）——默认 rollback
  journal 下写者互斥、读阻塞写
- 写峰叠加：IC 持久化循环 120s/轮 ~114 条语句（ic_tracker.py:308-351，每因子 upsert +
  count(distinct) + update）+ 启动回填最多 ~2 万条语句（ic_tracker.py:428-502）
  + 用户请求写 designs/tasks + 快照落盘并发
- 现状靠 timeout 兜底：SQLAlchemy 侧最坏 **30s BUSY 阻塞**；崩溃场景可能留损坏 journal

修复方向（最小代价）：engine connect 事件挂 `PRAGMA journal_mode=WAL` + `busy_timeout=30000`
（WAL 对既有 DB 为在线操作免迁移）；raw sqlite3 连接同步加 busy_timeout。
可选加固：快照写入并入 SQLAlchemy 引擎或独立文件，消除双写者拓扑。

#### A2（🔴 结构死结）factors → services 模块级反向依赖 —— 全新发现

```python
# factor_registry.py:62 —— 模块级 import（非 lazy）：import 时即建立 factors→services 依赖
from ..services.market_data_hub import market_data_hub as _hub
```

- 后果：任何 import factor_registry 的代码在 import 时即拉起整个 services 链
  （registry→hub→market_service→china_market…），拖慢启动并放大循环 import 风险；
  与 README 架构图「factors 在 services 之下平级」矛盾
- 同向 lazy 另有 3 处（:1184/:1281/:1302）+ factors→fetchers 1 处（:1136 macro_fetcher）
- 更广的耦合面（佐证模块边界问题）：market_service↔market_data_hub **双向互 lazy**
  （market_service.py:1859 ↔ market_data_hub.py:602/:644）；lazy import 密度极端者
  hub/_realtime.py（21 处/170 行 ≈ 12.4%）
- 与 R104 同文件纠缠，越晚拆越贵

修复方向：_hub 的使用点改为函数内 lazy 或参数注入（registry 已有 `_set_kline_cache`
注入先例）。只消模块级这一处即可，不必大动。

### 13.4 P1 —— 下轮排期（三项）

#### A3（🟠 稳定性）64 线程池队列无界 + 超时不杀线程 —— 对 §12 保持清单的补充限定

§12.2 将「双线程池隔离」（`core/async_utils.py:20-24, 103-114`）列为设计亮点——隔离本身成立，
但两个池参数有隐患：

- 共享池队列**无上限**，仅监控告警（深度 >8 WARN / >16 ERROR log）——饱和时延迟级联而非快速失败
- `wait_for` 超时只是放弃等待，**线程继续跑**——外部源黑洞时线程泄漏累积
- 历史实证：mootdx 空转曾打满 64/64（R6-F10），当时修的是调用侧，池本身仍是裸的

修复方向：共享池换有界队列（~128），满则快速拒绝返回结构化降级；已知慢源（mootdx）
单独小池隔离。不引入复杂框架。

#### A4（🟠 一致性）缓存碎片化三个具体断点 —— §12 结构性建议①的落地清单

§12.6-① 已给方向（统一缓存原语），本节补齐**可立即执行的断点**：

1. **SyncMemoryCache 与 memory_cache 实为两个 store**：cache_service.py docstring 声称
   「底层共享同一进程空间」，实际各自 `_store`/`_lock`（:176-177）——同步 fetcher 层与
   async 层同名 key 可双份漂移。修法：薄代理委托，或至少先改 docstring 说真话
2. **Redis 仅 init 探测一次可用性**（cache_service.py:72-90）：运行中挂掉 → get 静默返 None
   → 回源风暴风险；挂掉期间 set 静默丢弃。修法：失败计数触发周期性重探
3. **registry 第二 K 线域仍存活**：`factor_registry._kline_cache` 模块级 300s TTL
   （factor_registry.py:801-803），仅 deprecated `_fetch_market_data`（:1154-1175）使用；
   :1194 注释自认历史断裂过。§12.5-P2#4 已标 deprecated 可达但未提及其私有缓存域——
   删除时须连同该缓存一起清（搭 R104 车）
4. 顺手清理死代码：database.py:9-20 `_memory_cache/_set_cache/_clear_cache`（全仓 grep 无调用者）

另：TTL 常量 ≥8 种散落（KLINE_CACHE_TTL=300、_KLINE_CACHE_TTL=86400、_FUND_SHARES_TTL=86400、
_GLOBAL_INDICES_OK_TTL、_PORTFOLIO_REALTIME_TTL、_LAST_GOOD_TTL、hub _cache_ttl=60、
factors 响应缓存 60s）vs core/ttl.py 只覆盖 quote/news/sector 三类——收敛时一并入表。

#### A5（🟡 门禁完备性）官方 async 门禁盲区 —— D1 教训的第二实例

`audit_async_blocking.py` 报 OK（121 文件扫描），扩展模式补扫抓到实锤：

| 盲区成因 | 实锤位置 | 危害评估 |
|---|---|---|
| async 内直接文件 IO 无此 pattern | **hub/_regime_sentiment.py:114/:124** open() 在 async refresh_sentiment_cache 内 | 小文件写、120s 循环，低频但真实阻塞点 |
| async worker 内同步 sqlite 未拦 | **monitor/source_events.py:226** sqlite3.connect 在 async _cleanup_worker 内；token_usage._flush_batch 同步 executemany 每 100 条或 5s 直跑 | 批量小（<10ms 级），登记级 |
| async def 内嵌套 sync def 不扫 | token_usage `_query`（幸被 ：149 to_thread 包裹） | 当前无害，属漏网机制 |
| session 对象 `.get(` 不匹配 | fetchers 各处均在 sync 函数内 | 当前无害 |
| 直接导入 urlopen 不匹配 | sync_instruments.py:301（sync 函数内） | 当前无害 |

**与 §4.1 D1 对照：两道 AST 门禁各有一个盲区，都是被对抗式扫描发现的**——D1 的负向
fixture 思路（B1-F1a 测试）同样适用于本门禁：门禁自身需要被测试。与 §12.6-③ caller-wraps
加固互补：@blocking_io 标记治「调用方忘包」，本节三条 pattern 治「扫描器看不见」。

修复方向：补三条 pattern（各 ~5 行）+ 修实锤 2 处（open/sqlite 改 to_thread）。

### 13.5 记录在案 C1-C8（下轮排期或顺带修，不立项）

| # | 问题 | 证据 | 处置时机 |
|---|---|---|---|
| C1 | 巨型文件 Top6：market_service 1990 / allocation_engine 1955 / china_market 1907 / factor_registry 1819 / strategy_check 1737 / routers/market 1418（24 端点） | ReadAllLines 实测（含空行） | 只在因其它原因改动时顺带切分（strangler），不为拆而拆 |
| C2 | routers→fetchers 直连绕过 services（6 处 lazy） | analysis.py:707/:720/:741、admin.py:107、market.py:720/:725 | 改到对应端点时下沉 hub 层 |
| C3 | services→routers 常量倒置 | strategy_design.py:1056 从 routers.factors 导入 _status_of 等 4 常量 | 常量挪 factors/ + routers 转发，~半小时，可搭 B1/R104 车 |
| C4 | tasks→routers 广播基建住错层 | news_refresh.py:10、market_refresh.py:10 import routers.ws manager | WS 层再动时迁移 ConnectionManager 到 core/ |
| C5 | fire-and-forget create_task——**已由 §11 P0-1/P0-2 深入覆盖**（路由层 GC 弱引用风险 + 6 循环吞 CancelledError），仅补遗一处：market_data_hub.py:529 `_asyncio2.create_task(...)` 模块别名怪味建议顺手正名 | §11 已证 | 并入 §11.3 建议 #1 任务容器统一处理 |
| C6 | 配置双轨冲突 | etf_scanner.py:127 读 DATA_DIR vs settings.data_dir 已存在；strategy_check.py:269 读 LLM_PRIMARY_PROVIDER vs settings.llm_primary_provider 已存在；YFINANCE_PROXY 同值读 3 次（global_markets_fetcher:295/:326/:349）；INSTRUMENTS_SYNC_* 三文件重复读 | 双轨两处收进 Settings；其余散落 os.environ 21 处（9 文件）低频开关可留 |
| C7 | kline 用全局单一时间戳管所有 symbol 新鲜度 | hub `_kline_cache_ts`（_kline.py:234-248 max_age 判据） | 随 R103+R108 批次（R103 正是判据问题） |
| C8 | engine 两点纯度瑕疵（I/O 层面干净，D1 之外） | engine/composite_signal.py:44-54 datetime.now() 墙钟依赖（输出随调用时刻变）；依赖 app.core.regime/factor_aggregate（README「零外部依赖」表述过强） | 记录；B5 流水线化时一并处理 |

### 13.6 明确不做（防过度工程）

1. ❌ 微服务化/进程拆分——单用户工具，IPC 成本 > 收益
2. ❌ 换 PostgreSQL——除非出现多进程并发写或分析型大查询需求（当前均无）
3. ❌ 全面 DI 框架 / Repository 抽象层——会把 lazy import 问题换成注册表问题
4. ❌ 缓存一次性大迁移——认同 §12.6-① 统一原语的方向，但节奏为「先修 A4 断点（语义层），
   新代码必须走统一原语，存量按触点渐进收编」，不做 big-bang 替换
5. ❌ 主动大规模拆分巨型文件——测试覆盖好、行为稳定，纯结构重构风险收益比为负

### 13.7 与既有批次的搭车计划

| 本节项 | 搭车对象 | 说明 |
|---|---|---|
| A2 factors 反向依赖 | R104（round34 第一批）/ B2 | 同文件，先消模块级 import 再动 fdq 口径 |
| A4-③ registry K 线域删除 | R104 | deprecated 路径连缓存一起清 |
| C3 services→routers 常量 | B1 或 R104 | 半小时级顺带 |
| A5 门禁补盲 | B1-F1a 同性质 | 复用负向 fixture 思路，可并入 B1 提交 |
| C5 补遗（`_asyncio2` 别名） | §11.3 建议 #1 任务容器 | 顺带正名 |
| A1 WAL | 独立小 commit | 不依赖任何批次，随时可做 |
| A3 线程池有界化 | 独立小轮 | 建议下一批数据源相关改动前落地 |

**一句话总结：骨架对、纪律好；要修的是两个全新隐患（WAL 缺失 / factors 反向依赖）
+ 三项 P1（线程池无界 / 缓存断点 / 门禁补盲），A1+A2 合计 ~1 天可搭车，无需独立架构轮。**

### 13.8 验收口径补充（本节各项落地时）

1. patrol --diff 全绿 + verify_e2e ≥279/291 基线不变（本节改动均不触引擎输出语义）；
2. A1 落地后断言 `PRAGMA journal_mode` 查询返回 wal（verify_e2e 或一次性脚本）；
3. A2 落地后 `grep -n "^from \.\." backend/app/factors/factor_registry.py` 顶层无
   `from ..services`（模块级引用清零，函数体内 lazy 不限）；
4. A5 落地后扩展 pattern 的负向 fixture 用例入册（同 §8 第 3 条「门禁自身可被抓假」思路）；
5. A3 落地后人为注入慢源 → 断言队列满时快速拒绝而非无限排队（能抓假的负向用例）。

### 13.9 实施细化（A1 / A5 → 可实施粒度）

#### T-A1 WAL 启用（数据完整性，独立小 commit）

**接线点①** `backend/app/database.py` —— create_async_engine 之后挂 connect 事件
（SQLAlchemy 2.0 标准做法，挂 sync_engine）：

```python
from sqlalchemy import event

engine = create_async_engine(settings.database_url, echo=False,
                             connect_args={"timeout": 30})

@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")      # 对既有 DB 为在线操作免迁移，
                                                # 且持久化到 DB 文件（设一次全局生效）
    cur.execute("PRAGMA busy_timeout=30000")    # per-connection 属性，须每次设
    cur.close()
```

**接线点②** `backend/app/services/hub/_common.py:122-142` —— 裸 sqlite3 直连侧只补
per-connection 属性（journal_mode=WAL 已由 DB 文件持久化，无需重设）：

```python
conn = sqlite3.connect(db_path, timeout=10)
conn.execute("PRAGMA busy_timeout=30000")
```

**测试** `test_sqlite_wal_mode.py`（含负向）：
- 正向：初始化后对 portfolio.db 查询 `PRAGMA journal_mode` == "wal"；
- 正向：并发读写冒烟（一写者循环写 + 一读者循环读 2s）→ 无 BUSY 异常；
- **负向**：临时移除 pragma 配置跑同一并发冒烟（对照组）→ 断言对照组可复现 BUSY/
  阻塞而实验组不出现（证明测试本身能区分两种模式，防恒绿）。
- 注意：Docker 卷与备份工具兼容性——WAL 模式下 `-wal/-shm` 伴生文件随 DB 生成，
  data/ 目录 volume 挂载已覆盖，无额外动作；但「拷贝单 db 文件备份」需改为
  `VACUUM INTO` 或三文件同拷（README 部署说明补一行）。

#### T-A5 audit_async_blocking 三条补盲 pattern（含分级设计）

| # | 新 pattern | 级别 | 理由 |
|---|---|---|---|
| P-a | `open(` 直接出现在 async def 体（非 await/to_thread 包裹） | **FAIL** | 实锤 hub/_regime_sentiment.py:114/:124；文件写虽小但属真实事件循环阻塞 |
| P-b | `sqlite3.` 家族（connect/execute/executemany/commit）出现在 async def 体 | **FAIL** | 实锤 monitor/source_events.py:226、token_usage._flush_batch |
| P-c | async def 内嵌套 sync def 含阻塞调用且**未经** run_sync/to_thread/wait_for 调用 | **WARN**（人工复核，不阻断） | 合法用法存在（token_usage._query 经 :149 to_thread 包裹即合法）——自动区分调用方式 AST 复杂度高，先 WARN 观察误报率再考虑升级 |

配套实锤修复 2 处：_regime_sentiment 两处 open 改 `run_in_thread`；source_events.py:226
改 to_thread。

**测试**（扩展 `test_audit_async_blocking.py` 或新建 fixture 用例，对齐 B1-F1a 思路）：
- **负向×2**：tmp_path 构造含 `open()` 与 `sqlite3.connect()` 的伪 async 函数 → 各自命中
  （防门禁静默通过回归）；
- **边界**：`await run_sync(open_and_write)` 形态 → 不报（豁免路径仍生效）；
- 嵌套 WARN 场景：嵌套 sync def 含阻塞 + 被 to_thread 调用 → 不报；未被包装 → WARN。

---

## 14. 前端架构评估（追加节，2026-08-22 会话三，R123-R128 + FE1-FE5）

> 触发：用户要求「评估一下当前前端架构是否合理？有哪些可以优化的地方？」。
> 定位：round34 §9 是页面级 UI/性能走查审计（R109-R122），本节下沉到架构层——
> store 归属、数据流拓扑、目录分层、横切基建。两节互补不重叠。
> 方法：三个 explore 子代理并行审计（①结构规模盘点 ②stores 与数据流拓扑
> ③API 层与横切关注点），关键结论经 file:line 人工复核，死 action 与绕过模式由
> 两个代理独立发现互证。**全部为评估结论，未写任何修复代码。**

### 14.0 口径标注（D2/D3）

- 静态代码审计，无交易时段依赖；性能数字仅引用 round34 R110 实测值（D3 打标沿用）。
- 「零调用者」= grep src/ 生产代码无调用点（src/test/ 引用不计）；行数统计排除 src/test/。
- 孤儿组件扫描经三重交叉验证：import 正则全量提取 × `app.component` 全局注册反查（零命中）
  × auto-import 插件反查（vite.config.js 无 unplugin-vue-components）。

### 14.1 结构规模盘点（事实基线）

| 维度 | 实测 |
|---|---|
| 总规模 | 70 文件 / 17,204 行（.vue 45 个 15,253 行；.js 25 个 1,951 行；不含 src/test/） |
| 超 300 行文件 | 21 个（全 .vue）：PortfolioManager **1165** / FactorModelView **1034** / views/DashboardAiTools **722** / SourceMonitor 718 / App.vue 694 / TokenMonitor 615 / AnalysisView 594 / UnifiedAnalysis 570 / WatchlistPanel 516 / StrategyCheckResult 483 / NewsView 454 / AppTabs 449 / DesignResult 438 / TechnicalAnalysisModal 426 / AppModal 374 / AppTooltip 373 / ConfigView 346 / Dashboard 327 / SectorHeatMap 326 / AppInput 321 / SummaryCards 316 |
| 路由 | 7 页全懒加载 ✓；无嵌套路由、无 catch-all 404 |
| 目录 | views/ 仅 4 文件 vs components/ 40 文件（ui 8 / design 6 / market 6 / dashboard 7 / analysis 3 / 根 10） |
| 组件卫生 | 零孤儿（40/40 有非测试引用点）、零全局注册、显式 import 可追踪 |
| stores | market 249 行 / task 200 / warmup 110 / portfolio 82 / toast 21 / loading 19 |
| api 层 | api/index.js 116 行单实例 timeout 60s，六模块共 71 方法 |

### 14.2 发现总表

| 编号 | 级别 | 一句话 | 关键证据 |
|---|---|---|---|
| R123 | P1 | Store 层职责失守——10 个死 action 与组件直调并存（双重事实源） | market store fetchRealtime/fetchIndicators/fetchSignal/fetchHistory/getQuote 零调用者 |
| R124 | P1 | 数据获取三轨并行、无归属约定——round34 R110 重复请求的结构根因 | indices 页面级 composable 三处触发 / tasks 三路并行 / search 三份实现 |
| R125 | P2 | views/components 分层倒挂 | 4/7 路由指向 components/；views/DashboardAiTools 被 components 内嵌 |
| R126 | P2 | 横切关注点分散——错误处理未中心化 + WS 基建三份拷贝 + AGENTS.md 幽灵引用 | interceptor 仅日志，~15 处 catch→toast 手工接线 |
| R127 | P2 | 四态 UI 两极分化——API 失败渲染成空态 | SourceMonitor/TokenMonitor 无 error 分支 |
| R128 | P3 | 大文件与休眠状态清单 | PortfolioManager 1165 行单父叶子；loading store 全休眠 |

### 14.3 正面清单（架构资产——实施时勿破坏）

1. **HTTP 层组织**：api/index.js:4 单 axios 实例 + 六模块对象；全仓无第二处 axios 直调；
   SSE 走 useLLMStream 的 fetch+AbortController 属合理特例（:47-49 注释明确设计意图）。
2. **路由与分包**：7 页全 `() => import()` 懒加载 + manualChunks 四路分包 + drop_console。
3. **WS 生命周期卫生**：三路实现（stores/market.js / useNewsWS / useTaskWS）均有指数退避+
   抖动+stopped 守卫+心跳（market/news 30s ping）+定时器清理；Dashboard.vue:217/:222
   on/off 配对正确；未发现内存泄漏。
4. **跨 store 耦合极低**：仅两条边且各有正当理由（market→portfolio 变更联动 market.js:110-111；
   task→toast 终态通知 task.js:116）。
5. **token 底座完整**：theme.css 705 行全谱系 token；`var(--…)` 采用 1925 处 vs 硬编码 hex
   236 处（采用率约 89%）——与 round34 R117 结论一致。
6. **依赖纪律**：7 个运行时依赖零重复职能（单一图表库 echarts/vue-echarts、无 moment/dayjs、
   无 lodash、无 UI 框架包袱）。

### 14.4 R123（P1）：Store 层职责失守——死 action 与组件直调并存

Store 不是缺失而是**被绕过**——「有 store 的架构外观 + 无 store 的实际数据流」：

**A. market store 五个 REST action 零调用者**
- 定义于 stores/market.js:172-190、:237-239 的 fetchRealtime/fetchIndicators/fetchSignal/
  fetchHistory/getQuote——grep src/ 生产代码零命中；realtimeData 实际只由 WS onmessage 喂入（:91-120）。
- 同域端点被组件直调替代：AnalysisView.vue:511-513（chart/indicators/signal）、
  PortfolioManager.vue:683-684（indicators/signal）、TechnicalAnalysisModal.vue:320-323
  （indicators/signal/chart/fundFlow）。
- 后果：indicators/signal/history ref 从未被生产代码写入 = 永不更新的死状态。

**B. portfolio store 九个 action 死五个**
- fetchDailyPnl/fetchPnLHistory/fetchDriftCheck/exportPortfolio/importPortfolio 零调用者；
  同域端点被 PortfolioManager.vue:705/755/788/809 与 useDashboardData.js:93-94/:112 直调。
- strategyResult（portfolio.js:9）从未被写入；活着的仅 CRUD 四个。

**C. loading store 整体休眠**
- 仅 App.vue:118 渲染 overlay，无任何代码调 show/hide。

**危害**：将来「修缓存」改的是 store action，而真实数据走直调路径——改了不生效。
后端 check_api_usage 门禁只覆盖 api/index.js 方法层，store action 层无对应防线。

### 14.5 R124（P1）：数据获取三轨并行、无归属约定

三种拓扑并存且无规则决定何时用哪种：

```
① API→store→组件       ETF/watchlist CRUD、任务列表(task.js:22/:51 _fetchPromise 单飞)、warmup(warmup.js:89 单例轮询)   ✅ 健康
② API→composable→组件  indices(useDashboardData.js:67)、search(useMarketSearch.js:82)、SSE(useLLMStream)               ⚠️ 页面级作用域不跨页共享
③ API→组件直调         分析图表、design 任务详情与轮询(DashboardAiTools 十余处 :259-712)、板块热度(SectorHeatMap.vue:276-282)、admin 监控(TokenMonitor.vue:175-177 等)、因子(FactorModelView.vue:599)   ⚠️ 各自为政
```

四个实例化代价（round34 R110「indices ×3 / tasks ×2」重复请求的**结构根因在此**）：

1. **indices ×3**：唯一 fetcher 在 useDashboardData（composable 页面级作用域非 store），
   Dashboard 内 mount refreshAll(:213) + route watch(:227) + 30s poll(:218) 三处触发；
   GlobalIndicesStrip 纯 props 消费无法共享缓存。
2. **tasks 三路并行**：store listTasks 单飞（App.vue:215 + useTaskWS 回填 :51）‖
   DashboardAiTools 逐任务 getTask 轮询 design 5s(:450-484)/strategy 3s(:537-571)
   直调 portfolioApi.getTask 仅经 updateTask 回写 ‖ useTaskWS 兜底 getTask(:92)；
   WS 完成事件与轮询竞态去重仅靠组件本地 finalizedDesignIds Set(:375)。
3. **search 三份独立实现**：useMarketSearch composable（200ms 防抖 + 60s Map 缓存，
   UnifiedAnalysis ×3 实例 :132-134）vs WatchlistPanel.vue:312-323 内联（300ms 零缓存）
   vs PortfolioManager.vue:545-547 内联（300ms 零缓存）。
4. **watchlist 每次 mutation 双倍 GET**：store action 内部已 refetch（market.js:217 add/
   :223 update/:229 remove/:234 batch），WatchlistPanel 再 fetchItems()（:355/:369/:385）
   → 每次 mutation 2× GET /market/watchlist；addWatchlist 全程 3 次。

### 14.6 R125（P2）：views/components 分层倒挂

- router/index.js：**7 条路由中 4 条指向 components/**（PortfolioAnalysis/NewsView/
  TokenMonitor/SourceMonitor），仅 3 条指向 views/。
- views/ 4 文件中 DashboardAiTools.vue（722 行）反被 components/PortfolioAnalysis.vue:33
  当组件内嵌——目录名与用途互为倒置。
- components/ 根目录混装三类：路由页(4) + 千行重型功能组件(PortfolioManager/FactorModelView/
  AnalysisView) + chrome(TaskIndicator/TaskProgress/GlobalIndicesStrip)。
- 附带：/portfolio-analysis meta.title 为空串（App.vue page-header 不渲染）；无 catch-all 404。
- 危害：按「views=页面」惯例找页面扑空；round34 B7 IA 重组若不先归位目录语义，
  路由迁移会同时触碰两套约定。

### 14.7 R126（P2）：横切关注点分散

1. **错误处理未中心化**：interceptor 只打日志后原样 reject（api/index.js:11-25），
   错误 UI 由 ~15 处组件各自 catch→toast 手工接线（PortfolioManager.vue:724,768,796,813,
   848,867,889；DashboardAiTools.vue:440,617,661,678,723,727 等）；无统一错误规范化/重试机制。
2. **WS 基建三份拷贝**：WS_BASE 相同构造逻辑在 stores/market.js:7-10、useNewsWS.js:4-8、
   useTaskWS.js:5-8 重复三处；心跳不对称——market/news 有 30s ping，task WS 无 heartbeat；
   market store onMessageCallbacks 数组无自动清理机制（当前唯一消费者 Dashboard 配对正确，
   属潜在风险非现行 bug）。
3. **AGENTS.md 幽灵引用**：文档声称 composables/useMarketWS.js 存在与 /ws/market/{symbol}、
   /ws/design-report/{session_id} 通道——实际前端 src 对这两通道零消费（grep 仅测试引用），
   useMarketWS.js 不存在（market WS 逻辑在 stores/market.js，连接的是 /ws/portfolio）。

### 14.8 R127（P2）：四态 UI 两极分化——空态冒充错误态

- **标杆**：FactorModelView 五态齐备（loading :12 / error :18-19 / empty :173,:316 /
  degraded :26 / accumulating :84）；DashboardAiTools 进度/失败/重试完整。
- **反面**（违反 AGENTS.md 反假完成表第 5 条「交互四态」与 README honest degradation 承诺的前端半边）：
  - SourceMonitor.vue：模板只有 v-if="loading"/v-else（:4-9），四处 catch 仅 logger.error
    （:214/:220/:226/:232）→ API 全挂渲染成「暂无数据源记录」**空态而非错误态**。
  - TokenMonitor.vue 同型（catch :184 仅日志，无 error 分支）。
  - PortfolioManager 初载闪空态：v-if="!currentEtfs.length"（:223）在首拉期间显示
    「还没有 ETF」——portfolio store 82 行纯透传零 loading 标志。
  - NewsView loadNews 失败静默清列表（:251-254 catch 后 loading=false，无用户提示）。

### 14.9 R128（P3）：大文件与死代码清单

- PortfolioManager 1165 / FactorModelView 1034 行——均为单父叶子组件风险可控，
  拆分收益中等，随 B3/B7 触及时顺手处理。
- 死代码汇总：R123 所列 10 个死 action + strategyResult + loading store 整体 +
  两个幽灵 WS 通道（文档级）。

### 14.10 与 round34 §10 B1-B7 及本文档其他节的关系

- 本节不推翻 round34-B1-B7（round34 §10 前端 UX 批次），是为其补结构层根因：
  **r34-B4（R110 in-flight 去重）若不立
  「服务器状态归 store」的归属约定，重复请求会随新页面继续繁殖**——FE1 是 r34-B4 的前置收口。
- FE5 目录归位应由 round34-B7（IA 重组）吸收同批执行（都要动路由与页面归属，避免两次动同批文件）。
- FE2 与 round34 B1 console 卫生同域可搭车；FE3 与 §12 的 portfolio_changed 讨论同域
  （同一个 market store）。

### 14.11 FE1-FE5 批次建议（待用户决策，未排期未实施）

| # | 内容 | 量级 | 核心文件 | 验收口径（含负向断言） |
|---|---|---|---|---|
| FE1 | Store 收口：R123 每个 action 二选一（组件改走 store / 删 action）；修 watchlist 双拉（删 store 内部 refetch 或组件侧重复调用之一） | 0.5 天 | stores/market.js、stores/portfolio.js、stores/loading.js、WatchlistPanel.vue | rg 死 action 名生产代码零命中或全部有真实调用点（对齐反假完成第 1 条）；watchlist mutation 后 GET 请求数 ==1（改前 ==2） |
| FE2 | 四态补齐：SourceMonitor/TokenMonitor 补 error 分支；portfolio store 加 loading 标志消除初载闪空态；NewsView 失败提示 | 0.5 天 | SourceMonitor.vue、TokenMonitor.vue、stores/portfolio.js、NewsView.vue | 断网场景四页显示错误态而非空态（负向：改前必现空态冒充） |
| FE3 | 横切收口：WS_BASE 抽公共常量（进阶抽 useWebSocketChannel 基座统一心跳/退避）；interceptor 加统一错误规范化（toast 决定权留给调用方）；补齐 task WS 心跳 | 0.5 天 | 三 WS 实现、api/index.js | grep WS_BASE 构造唯一；错误响应统一 shape |
| FE4 | AGENTS.md 修正：删 useMarketWS.js 幽灵引用与两个零消费 WS 通道描述（或标注「预留未接通」） | 10 分钟 | AGENTS.md | 文档与代码一致 |
| FE5 | views/components 归位——并入 round34 B7 执行，不单独提前 | 随 B7 | router/index.js、各页面 | 路由全部指向 views/ 或明确新约定；components/ 根只留非路由组件 |

建议顺序：FE4（随手）→ FE1+FE2（一批 ~1 天，高杠杆）→ FE3（随 round34 B4 同批）→ FE5（随 B7）。

### 14.12 一句话结论

前端架构骨架（单实例 API 层、懒加载路由、token 体系、WS 卫生、依赖纪律）健康，
不需要重写；真正的债是「**约定写了但没执行**」——store 被绕过形成双重事实源（R123）、
数据获取无归属规则（R124）、四态执行两极分化（R127）。优先 FE1+FE2 小成本高杠杆收口，
其余随既有批次顺流而下。

---

## 15. 因子模型评估（聚合语义与决策正确性，2026-08-22 追加）— FM/FS 系发现

> 本章聚焦 factors/ 的**聚合语义与决策链正确性**，与 §12 数据管线评审（卫生/调度层）互补
> 不重叠——§12.5-P2-1 已登记的合并残留本章不重复立项。方法：factor_registry.py 核心段
> （数据装配 ：1154-1408、compute 尾部 IC 记录 :1618-1719、restore/refresh :1721-1815）、
> ic_tracker.py 全文、core/factor_aggregate.py 全文直读；消费链经 codegraph blast radius +
> explore 子代理 + 全库 grep 序列方向核验。
> 编号规则：FM = 因子缺陷（bug 级）/ FS = 因子结构性问题，与 D/S/A/C/P/FE 系列互不冲突。

### 15.0 验证窗口标注

静态代码级结论，无交易时段依赖（FM1 权重方向可用单调序列离线推演复现）。
FM2 实际量级影响需 IC 序列 ≥IC_MIN_BATCHES(5) 批后实测对照——当前普遍冷启动等权，
影响未显性化，恰是低成本修复窗口。

### 15.1 总评与判定表

**总评**：因子层骨架健康（YAML 单一事实源 / None 语义诚实降级 / Newey-West + 250 日
三重门槛 / 引擎纯度参数注入）。核心矛盾一句话：**38 个实现因子中 14 个（37%）从不进入
composite 决策链；进入决策链的部分，IC 自适应加权存在方向反转（FM1）与尺度失配（FM2）
两处缺陷，实际运行状态接近「等权+噪声」**。

| 判定 | 项目 |
|---|---|
| 🔴 确定性缺陷 | FM1 IC 衰减方向反转：refresh_ic_series 新→旧构建 vs _ic_decay_mean 假设旧→新；fdq reversed() 第二显影取到最旧值 |
| 🟠 设计缺陷 | FM2 IC 加权尺度失配：warm 因子权重 ≈ mean_ic(0.02~0.05) < 冷启动 1.0，「毕业即降权」~30× |
| 🟠 覆盖缺口 | FM3 14/38 因子零决策贡献（etf_specific×6 全孤儿 + policy×3 + macro×5）；FM4 valuation 顶层键在实现集下结构性空转 |
| 🟡 结构性问题 | FS1 零值阈值三处各自为政（tracking_error 特判已证明复发模式）；FS2 双缓存域/双口径包袱（R85/R104 既定，仅登记） |
| ✅ 保持清单 | YAML 方向单一来源、IC None 不写 0、日频 upsert 防虚高 + signal_absent 防生存者偏差、valid 三重门槛、纯度参数注入（§15.2） |

### 15.2 保持清单（后续改动不得丢失）

1. **YAML 单一事实源**：方向/中性点/标准化在 factor_definitions.yaml；聚合方向化以
   definitions 优先（factor_aggregate.py:100-109），CATEGORY_AGG 内置表仅兜底。
2. **IC None 语义**：样本<3 / 常量输入返回 None 不写 0（ic_tracker.py:138-151 U3/N06）；
   _last_ic_batch 覆盖保护（factor_registry.py:1656-1695 Z06）。
3. **日频 upsert + signal_absent 落库**：(code, trade_date) upsert 防「刷新次数冒充交易日」
   （ic_tracker.py:281-352 F25①）；近零 IC 标记落库防生存者偏差（F30）。
4. **valid 三重门槛**：≥250 交易日 且 t≥2(Newey-West) 且 \|IR\|≥0.5（routers/factors.py
   _status_of :137-142）——统计诚实，不谎报有效。
5. **引擎纯度参数注入**：definitions/ic_series 经 strategy_design.py 注入 engine
   （check_engine_purity.py AST 强制），engine 不 import registry 私有态。
6. **排除逻辑的实证注释链**：F1-5 价格≠估值、R99 政策因子剔出 momentum——每条排除都有
   设计文档指针，改动前必读（factor_aggregate.py:75-91）。

### 15.3 FM1（🔴 确定性缺陷）IC 衰减方向反转

**现象**：「近因衰减加权」实为「反近因衰减」——窗口内最旧的 IC 批拿最大权重，
近期恶化的因子被历史好批托住均值，自适应失效方向与设计意图相反。

**证据链（闭环三步 + 第二显影）**：

```python
# ① 构建（factor_registry.py refresh_ic_series）：缓存契约 = 最新在前
#    :1785 .order_by(FactorICRecord.computed_at.desc())
#    :1806 注释自证「rows 已按 computed_at 降序 → 序列顺序即最新在前」
#    :1807-1812 按迭代序 append → [最新, …, 最旧]

# ② 传递：三个消费方直传不反转（全库 grep 无 [::-1]/reverse 作用于该缓存）
#    strategy_design.py:432 → allocation_engine.py:451/:1249 → aggregate_factor_scores
#    market_data_hub.py:351 同款；strategy_check.py:1010 同款

# ③ 消费（core/factor_aggregate.py:38-47 _ic_decay_mean）：假设旧→新序
#    weights[i] = exp(-lam * (n - 1 - i)) → i=n-1（末位=最旧批）权重 1.0 最大
#    docstring「最新批权重 1，越旧按 exp(-λ·age) 衰减」的假设落空

# ④ 第二显影（strategy_design.py fdq :1100-1104）：注释同样认定缓存「最新在前」，
#    但 for _v in reversed(_ic) + break 取到的是【最旧】值冒充「最近一个非 None」
#    → _status_of 的 ic_val 输入错位（同一根因的第二处独立消费方读错）
```

**量级**：λ=ln2/20≈0.0347、窗口 20 批时新旧权重比 ≈ e^(λ·19) ≈ 1.93× 反向
（正确行为应 newest=1.0 / oldest≈0.52，现状 oldest=1.0 / newest≈0.52）。
当前 IC 普遍 <5 批走等权路径，影响尚未显性化；随积累放大。

**测试缺口佐证**：refresh_ic_series 无覆盖测试（codegraph blast radius 标注 no covering
tests）；tests/test_factor_aggregate.py 唯一 IC 用例（:73-77）只验「注入不回归」，不断言
序列顺序语义——正是 round14 五类盲区之「mock 理想输入掩盖缺陷」的实例。

**修复方向（单一归一点）**：refresh_ic_series 构建改为升序（旧→新）——则 _ic_decay_mean
末位=最新 ✓、fdq reversed() 后取到最新 ✓，两个消费方同时回归各自注释声明的语义；
或改 _ic_decay_mean 公式为 exp(-λ·i) 并同步修 fdq 取值方向。二选一后必须：
- 补钉死顺序的负向测试 ×2：构造已知单调 IC 序列断言加权均值偏向新端；
  构造含 None 序列断言 fdq 取到的是最新非 None 值；
- 动手前审计 _ic_series_cache 全部读取点（当前已知三处：aggregate 注入链 /
  fdq strategy_design.py:1075-1105 / strategy_check.py:1010——第三处读取语义实施时核对）；
- 行号漂移注记：strategy_design.py 本轮评估期间正被并行批次编辑（实测漂移 ±30 行，
  如 ic_series 注入点 431→432），实施时以函数名锚定。
- 归宿建议：并入 B1 同级（一行级修复+测试；文件面与 B1 不相交——
  factor_aggregate/factor_registry vs engine/* 与 strategy_design 编排段，可并行）。

### 15.4 FM2（🟠 设计缺陷）IC 加权尺度失配——毕业即降权

**现象**（factor_aggregate.py:147-159）：冷启动因子（序列 <IC_MIN_BATCHES=5 批）
weight=1.0；warm 因子 weight=max(mean_ic, 0)。ETF 截面典型有效 \|IC\| 仅 0.02~0.05
（佐证：YAML 默认 ic_threshold=0.02 factor_registry.py:1086；真实弱因子 vol_ratio
IC=0.001 见 ic_tracker.py:245-249 口径核对注）→ **通过验证的好因子权重 ~0.03 vs
无任何证据的冷启动因子 1.0，差 ~30 倍**。IC 积累越多伤害越大——与「数据多了更准」
直觉相反，越晚修代价越高。

四问法自查：①事实=权重公式本身（file:line 如上）；②推断「伤害随积累放大」支撑=mean_ic
直接作为分子进权重；③无内部矛盾；④与当下一致性=待 IC ≥5 批后实测对照（15.0 标注）。

**修复方向**：相对化 w = max(mean_ic,0)/ref，ref=池内 warm 因子中位 \|IC\|，且保底
max(w, 1.0)（不低于等权基线）；或 softmax/rank 变换。改动集中 core/factor_aggregate.py
单文件。注意：会改变 composite 输出——若 B4 黄金快照夹具注入非空 ic_series，基线需显式
再生（--update + commit 说明动机）；建议排在 B4 基线固化之后小批实施。

### 15.5 FM3/FM4（🟠 覆盖缺口）37% 因子零决策贡献 + valuation 键结构性空转

**FM3 孤儿因子清单**（CATEGORY_PREFIXES 仅四类前缀 factor_aggregate.py:83-88，对照
_BUILTIN_COMPUTERS 38 个注册因子 factor_registry.py:675-718 逐一核对，14 个不匹配任何
前缀）：

| 组 | 因子 | 说明 |
|---|---|---|
| etf_specific ×6（全孤儿） | premium_discount / tracking_error / shares_change / amount_stability / industry_diversification / institutional_holdings_change | 折溢价是 ETF 最特有的估值信号、份额变动=资金流向；注意 "etf.price." 前缀**不匹配** "etf.premium_discount"（差一词即漏接） |
| policy ×3 | five_year_plan / strategic_emerging / dual_circulation | R99 从 momentum 剔除后没有新家 |
| macro ×5 | m2_trend / pmi_level / lpr_direction / gdp_trend / margin_leverage_trend | MARKET_LEVEL 截面恒等无 IC 可理解，但目前连 regime 条件权重的用途也没有 |

这些因子照常计算并出现在 /factors/active 与 LLM 上下文中，制造「模型丰富」的观感，
但对选基定权零贡献——叙事与实现脱节。

**FM4 valuation 键结构性空转**（FM3 的加重情节）：valuation 前缀覆盖 style.* 与 etf.price.*
（:86），但 style.size.ln_mcap/ln_float_mcap 被 _EXCLUDE_FROM_VALUATION 显式排除
（:91,:132-135）、etf.price 整键排除（:130）、股息率子键（etf.price.dividend_yield 类）
无实现——**38 因子实现集下 valuation 顶层键永远不产出**。后果：_PROFILE_WEIGHTS 三风偏
各 0.2 的 valuation 槽位恒零贡献，composite 实际由 technical/momentum/sentiment 三分构成，
名义权重被隐性放大 ~25%；`_valuation_is_meaningful`（allocation_engine.py:118-127）的
「黄金/债券类恒 False」分支实际对全部标的恒 False。

**修复方向**：为 ETF 特有因子建第五顶层键（etf_quality 或 flow+quality 拆分），将
premium_discount/tracking_error/shares_change 接入 composite（顺带复活 valuation 语义槽）；
policy/macro 二选一——显式标注「仅展示」从核心叙事分离，或做 regime 门控条件权重。
**前置探针**：premium_discount（IOPV 链区分度）/ shares_change（衔接 round34 S-A
FundShareSnapshot）/ benchmark_close（round34 T-A）的数据可用性达标后才进实施清单（D1 纪律）。

### 15.6 FS 系（🟡 结构性问题）

| # | 问题 | 实证 | 归宿 |
|---|---|---|---|
| FS1 | 零值阈值三处各自为政：record 过滤 abs>0.001（factor_registry.py:1646，仅影响内存样本计数）/ 聚合过滤 abs>0.001（factor_aggregate.py:125）/ zero_ratio 按因子特判 tracking_error=1e-6 其余 0.001（ic_tracker.py:231-235） | tracking_error 特判已证明该问题会复发；premium_discount 日常 ±0.1% 有被当占位零的风险（合法值被过滤→IC 样本系统性偏少） | 卫生级：抽 `is_meaningful_value(code, val)` 单点判定 + 各因子合法值域文档化 |
| FS2 | 双缓存域/双口径包袱：模块级 _kline_cache（factor_registry.py:996-1015）vs hub._kline_cache_rows（R85 已桥接 :1193-1202 但两套并存）；fdq 内存口径 vs DB 口径（=round34 R104 已闭因）；_sample_counts 内存/DB 双轨（restore 时同步 :1756-1764） | file:line 如左 | ✅ R85/R104 既定方案覆盖，仅登记不重复立项；sentiment/news 双路径分歧另见 §12.5-P1-d |

### 15.7 观察项（暂不立项，记录在案）

1. **技术类共线性投票膨胀**：sma_5/10/20/60 + MACD 高相关，同一「趋势维度」在 technical
   键内合计投 4+ 票——建议子类别二级聚合（trend/reversal/volatility/volume 各一票）或
   池内正交化后再聚合。
2. **250 日 valid 门槛 vs 产品现实**：系统上线时长 <250 交易日 → 绝大多数因子长期
   no_data/warn，valid 状态在可预见未来不可达。统计上诚实没错，但可引入分层置信
   （如 60 日 provisional 单独标色）或收缩估计，让 IC 信息更早以保守方式参与而非二值等待。
3. **YAML 方向语义缺测试锁定**：KDJ negate / RSI symmetric50 全靠 YAML 手填正确，
   一次手误=全池反向选基——建议「方向语义快照」单测（每因子典型行情输入→期望符号）进 CI。

### 15.8 与既有批次对照及实施排序

| 发现 | 归宿 |
|---|---|
| FM1 | 🆕 建议并入 B1 同级（一行归一 + 顺序钉死负向测试 ×2；文件面与 B1 不相交可并行） |
| FM2 | 🆕 建议 B4 黄金基线固化后小批实施（composite 输出变化需快照再生说明） |
| FM3/FM4 | 🆕 新立项小批；前置探针 premium_discount/shares_change/benchmark_close（衔接 round34 S-A/T-A） |
| FS1 | 卫生级捎带任一批次（遵循「不为常规项加门禁段」纪律） |
| FS2 | ✅ R85/R104 既定覆盖，仅登记 |
| 观察项 ×3 | 记录不动/独立轮 |

**验收口径（FM 批次）**：patrol --diff 全绿 + 交付期 --full 一次；FM1 新增顺序钉死测试 ×2 绿；
FM2 若实施附黄金场景① diff 说明 + 手算等价探针；verify_e2e ≥279/291（M7 四连 FAIL=R105
已知非回归）。

### 15.9 design-checklist 八项自查

| # | 检查项 | 本章结论 |
|---|---|---|
| 1 | 可行性探针 | FM1/FM2 纯代码序推演无需外部探针；FM3 数据可用性探针为实施前置（未过不出方案） |
| 2 | 证据链 | 全部 file:line 实测（strategy_design.py 因并行编辑存在 ±30 行漂移已标注，实施以函数名锚定） |
| 3 | 验证窗口 | 静态结论无交易时段依赖；FM2 量级实测挂 IC≥5 批条件（15.0） |
| 4 | 非兜底数据 | 不新增数据输出；FM1/FM2 修复恰是消除「自适应加权名不符实」的特性假象 |
| 5 | 真实调用点 | 全部位于活跃调用链（aggregate_factor_scores 12 callers / refresh_ic_series 由 main.py 循环驱动）；无新增端点/函数 |
| 6 | 四态 UI | 后端纯逻辑层，豁免 |
| 7 | 复杂度审计 | 零新增网络/DB/文件调用；FS1 收敛反而降低判定复杂度 |
| 8 | 已知问题模式 | 触碰 round14 五类盲区之「mock 理想输入掩盖缺陷」——现有 aggregate 测试用对称/理想输入掩盖了顺序与尺度缺陷；新测试必须含非对称序列负向断言 |

---

## 16. 前后端测试防护体系评审（2026-08-22 并行会话产物）

> 评估对象：① 后端 pytest 体系（backend/tests/ 240 个 test_*.py + 双层 conftest + socket guard）；
> ② 巡检编排 patrol.py（L1-L5 九层）；③ 提交门禁 .githooks/pre-commit（15 段 + 文档短路）；
> ④ 全量凭据 tests_ok_marker（round30 方案 B）；⑤ verify_e2e / smoke_startup / verify_perf /
> data_health_check 四脚本；⑥ 前端 vitest（39 spec / ~504 用例）+ Playwright E2E（16 spec）。
> 方法：三路 explore 子代理并行探查（前端测试体系 / 后端测试组织 / 门禁编排层）+
> 对照 docs/patrol-orchestration-plan.md 设计初衷逐项核对落地度。纯评审零代码改动，
> 全部结论 file:line 实证。验证窗口：静态评审无交易时段依赖。

### 16.1 总体判断

**五层编排成熟度高于典型同规模项目，骨架不需要推翻**：分层职责清晰
（pre-commit=提交语义门禁、patrol=开发循环巡检，互补不合并——patrol 设计文档 §8-1 明确约定）；
退出码四级语义严格（SKIP 必带 reason、绝不静默算通过）；AST 门禁 + 基线差分只拦新增死代码；
tests_ok_marker 凭据把「验收全量 + patrol L1 + pre-commit 全量」三重折叠为一次
（实测 patrol --full 共 737.5s：L1-unit 120.5s / L2-e2e 543s / L2-health 42.7s / L3-perf 9.95s /
L5 18.55s，凭据有效时每次逻辑提交省 ~2min）。

问题集中在三类：**编排不对称**（两个入口各守一半检查面，16.3）、**若干覆盖盲区**
（前端组件/WS/API 层、四态之 slow 态，16.4）、**少量冗余与空心测试**（16.5-16.6）。

### 16.2 设计亮点（保持清单——后续优化不得丢失的行为）

| 设计 | 实证 | 价值 |
|---|---|---|
| socket guard 结构性防 mock 泄漏 | backend/conftest.py（F23）：未 mock 的真实网络调用抛 NetworkBlockedError 响亮失败 | 全库单测可信度基石——808 处 mock.patch 下泄漏不可能静默通过 |
| 凭据指纹机制 | tests_ok_marker.py:50-73（mtime_ns+size md5 覆盖 app/tests/scripts/requirements.txt/pytest.ini/conftest.py 全文件）+ :45 TTL 60min + :127-129 head_sha 校验 | 失效方向安全（失效→恢复全量而非跳过）；单测覆盖含负向场景 |
| e2e 选测映射哲学 | patrol.py:84-117,180-204：路由精确映射 + 共享层/未知路径保守全量兜底 | 「映射过时的最坏后果是多跑不是漏跑」 |
| verify_e2e 内容级断言 | SSE 中文内容检测(:56-81)、warmup 计时门禁(:126-157)、5xx 零容忍(:1470)、design price 非 None(:2540-2542) | 远超「HTTP 200 检查」；唯一豁免 section_analysis（:801-802 注释明示只验状态码） |
| 近期测试负向断言纪律 | r94-r107 系列（test_no_double_value 正则扫双值等）+ 前端 finding spec（not.toContain 联接基金代码） | 符合反假完成「测试要能抓假」 |
| engine 包全覆盖 | 8 个模块均有直接测试文件，allocation_engine 16+ 文件厚覆盖 | 纯函数可测性的兑现 |

### 16.3 P0 编排不对称（结构性问题，建议优先治理）

1. 🔴 **vitest 不在任何提交门禁**：pre-commit 仅 `npm run build`（pre-commit:116-142），
   npm test 只在 patrol L5。改 frontend/src/* 直接 commit 时 ~500 个前端用例一道不跑，
   纯靠开发者自觉跑 patrol——**当前最大的门禁漏洞**。
2. 🟠 **patrol --full 缺静态卫生段**：secret 扫描 / mypy / check_api_usage /
   audit_unused_symbols / check_unused_styles / docker build 冒烟 / check_test_baseline 七项
   只在 pre-commit；verify_e2e / data_health_check / npm test 又只在 patrol。
   **不存在覆盖全部检查项的单一命令**——交付前 `--full` 全绿 ≠ 卫生段通过。
3. 🟠 **无 CI 兜底**：仅 .github/workflows/performance.yml（Lighthouse + 弱源容器测试），
   无 pytest/vitest CI。`git commit -n` 一键绕过全部本地防线且无远程二次拦截。
4. 🟡 **mypy 未安装时静默跳过**：pre-commit:245 `command -v mypy` 分支无任何 echo 提示——
   换机克隆后类型检查悄悄消失，违反自家「绝不静默降级」（对照 docker 段 :286-303 有 warn）。
5. 🟡 **verify_perf 的 pre-commit 段近乎死代码**：仅 perf 脚本/pre-commit 自身变更触发
   （:407-422）且 `|| true` 恒不阻断；日常性能门禁实际由 patrol L3 承担
   （round34 §13 已列移交标注待办）。

### 16.4 覆盖缺口

#### 后端

| # | 缺口 | 实证 | 影响 |
|---|---|---|---|
| B-1 | 6 个 @pytest.mark.network 真网络测试默认运行 | pytest.ini addopts 只排除 integration+slow；test_global_indices.py:345,369 + test_news_sort_order.py:90,100,142,155 每次 `python -m pytest` 都打真实 Sina/Caixin 接口 | 违反 AGENTS.md「外部网络必须 mock」+ 套件环境性 flaky 源 |
| B-2 | 删除测试文件零捕获 | pre-commit 选测 --diff-filter=ACM 排除 DELETED；patrol 档2 只跑变更文件且无用例数校验 | round34 §11 T2 测试迁移的现实风险：迁移中丢用例不会被任何门禁抓住 |
| B-3 | composite_signal / pool_balancing 单文件薄覆盖 | 仅 test_engine_pure_functions.py（其余 6 个 engine 模块均多文件厚覆盖） | 两模块边界回归面薄 |
| B-4 | check_test_baseline 基线过期失真 | 基线 ≤197 vs 实际 240 文件 | 已降级为提示不阻断（round34 §13），但数字误导 |

#### 前端

| # | 缺口 | 实证 |
|---|---|---|
| F-1 | 13 组件裸奔/仅 stub | ConfigView（零测试）；Dashboard/MarketAnalysis（仅 wsAndSourceGuards.spec.js:39-57,:186-192 源码断言）；CapitalInputBar/AllocationTable/ErrorOverlay/SourceMonitor/ChartPanel（零 mount 测试或仅间接）；DesignWizard/StrategyCheckModal/TaskProgress/AppTooltip（仅 stub） |
| F-2 | useTaskWS / useWarmupStatus / api/index.js 零测试 | api 层被 39 个 spec 全部 vi.mock('../api') 替换——axios baseURL/拦截器无人验证 |
| F-3 | 四态之 slow 态零覆盖 | grep slow/慢速 无命中（loading/empty/error 三态覆盖良好，如 NewsView 行内错误重试 :459-473、UnifiedAnalysis 429 分类文案）；UI 四态**行为**缺陷（空态冒充错误态）另见 §14 R127，修复归 FE2——本条只管测试覆盖缺口 |
| F-4 | coverage 完全未开启 | vitest.config.js 无 coverage 键、无阈值、未装 @vitest/coverage-* ——裸奔面积无法量化追踪 |
| F-5 | setup.js 全局静音 console.warn/error | Vue 运行时告警永不暴露，削弱测试抓假能力 |
| F-6 | 文档漂移 | AGENTS.md 引用的 composables/useMarketWS.js 不存在（WS 行情逻辑实际在 stores/market.js connectWS/disconnectWS/onWSMessage，有测试覆盖）。= §14 R126-3 同一发现，修复动作归 FE4 |

### 16.5 冗余清单

1. **rXXX 系列与业务域测试重叠**（确认 round34 §11 T2 归位必要性）：
   test_r90_news_classification vs test_news_classification.py 同函数增量回归；
   strategy_check 域 4 文件（r87/r94/table_score/timeout_matrix）；
   factor IC 域 5 文件（ic_tracker/ic_tracker_constant/factor_ic_sample_count/f25_ic_daily_pipeline/r96）；
   r85 vs test_factor_registry.py。
2. smoke_startup/routes/purity/async/npm-build 在 pre-commit 与 patrol 双跑——
   脚本便宜（≤2s），**可接受，不治理**。
3. FakeWebSocket 三套重复实现（marketStore.p1-1.spec.js:13-22 / wsAndSourceGuards.spec.js:22-35 /
   useNewsWS.spec.js:5-22 各自造轮子）——应抽 src/test/helpers 共享。
4. p1k-pnl-color.spec 与 SummaryCards.spec 部分 mount 重叠（角度不同，容忍）。

### 16.6 空心测试（反假完成的反面教材——能抓假的测试自己先假了）

| 位置 | 问题 |
|---|---|
| marketStore.p1-1.spec.js:52-54 | 负向用例空测试体（恒绿占位） |
| DashboardAiTools.spec.js:313-334 | 注释自认 "can't easily instantiate"——恒真 typeof 断言 + 两用例只验 mock 本身 rejects，未挂载组件验证行为 |

### 16.7 优化建议（三档优先级，均未实施）

**P0 一行级修复（合计 ~0.5 天）**

1. pytest.ini addopts 改 `-m "not integration and not slow and not network"`
   （B-1；需要真网络时 `-m network` 显式跑）；
2. mypy 缺失分支补 echo 提示（16.3-4，对齐 docker 段 warn 风格）；
3. 修 2 处空心测试（16.6）：补真实负向断言或删除占位；
4. marker 措辞修正：patrol 整体 exit≠0 时 pre-commit:356 不应打「patrol 已全量验证」
   （mark 只认证 L1-unit；latest.json 实证存在 L2-e2e FAIL 但凭据有效的组合）；
5. 删 pre-commit 死代码 perf 段或落实 round34 §13 移交标注（16.3-5）。

**P1 小专项（~1-2 天）**

6. pre-commit 补 npm test 段（触发条件对齐前端 build 段 frontend/src/* 变更；
   vitest 全量实测 ~18s）（16.3-1）；
7. round34 §11 T2 迁移配套负向验收自动化：迁移前后 `pytest --collect-only -q` 用例计数比对
   写入 T2 验收步骤（B-2 前置安全网）；
8. FakeWebSocket 抽公共 helper + setup.js 改「收集告警并断言无意外告警」模式（F-5）；
9. 更新/废弃 check_test_baseline 基线（B-4）；AGENTS.md 修正 useMarketWS 引用（F-6，
   与 §14 FE4 是同一动作，实施时合并执行，不重复立项）。

**P2 排期项**

10. 前端 13 裸奔组件补 mount 测试，顺序：ErrorOverlay → CapitalInputBar → AllocationTable →
    ConfigView → 其余；round34 §10 B1-B7 动到哪个组件就顺带补测哪个；
11. 开启 @vitest/coverage-v8（先 report 不 gate，观察两周再收紧阈值）（F-4）；
12. composite_signal / pool_balancing 从 test_engine_pure_functions.py 拆独立测试文件补边界用例
    （B-3）;
13. 团队化前提下的最小 GitHub Actions（pytest + vitest），使 -n 绕过有远程兜底（16.3-3）。

### 16.8 明确不做（防过度工程）

| 不做 | 理由 |
|---|---|
| ❌ 消除 smoke/routes/purity/async/build 双跑的统一调度 | 成本 > 收益，脚本本身 ≤2s |
| ❌ 立即上覆盖率硬门禁 | 先有 report 数据再谈阈值 |
| ❌ rXXX 归位扩大范围 | 维持 round34 §11 原方案即可 |

### 16.9 与既有批次的关系 + 验收口径

- **与 round34 §11 T1-T4（测试命名重组）衔接**：B-2（删除零捕获）是 T2 迁移的前置风险，
  16.7-P1-7 的计数比对应写入 T2 验收步骤；
- **与 round35 B1-B6（引擎重构）及 §11/§12 各专项零文件交集**：本节改动域 =
  .githooks/pre-commit + backend/pytest.ini + backend/scripts/tests_ok_marker.py +
  前端测试基建（vitest.config/setup/helpers），不影响既有排期；
- **验证窗口**：静态评审结论无交易时段依赖；P0/P1 实施后 patrol --diff 即可验证；
- **验收口径（实施时）**：
  ① patrol --diff 全绿；
  ② 新增 npm test 门禁段须含负向验证（故意改坏一个前端组件断言 → pre-commit 必须拦截）；
  ③ network 排除前后全量用例数核对一致（防顺手误删）；
  ④ 空心测试修复后须能构造出使其 FAIL 的场景（证明非恒绿）。

### 16.10 实施细化（重大修改项——T-P1-6 新增门禁段）

> 按 AGENTS.md 门禁治理约定：「新增门禁须说明与现有段的差异化价值」。本节把
> 16.7-P1-6 从一句话建议细化为可直接实施的规格；其余 P0 各项为一行级改动，
> 落点已含于条目描述，不另立规格。

#### 差异化价值声明

现有 15 段中前端相关仅两处：前端 build 段（④，验「能编译」）与 check_api_usage 段
（⑤，api/index.js 死方法审计）。**vitest 行为回归不在任何提交时防线内**——500 个用例
只在 patrol L5（开发循环手动命令）执行。本段补的正是「行为回归 × 提交时点」这一空格：
build 验编译契约、本段验组件行为、patrol L5 提供交付前全量兜底，三层互补非重复。

#### 改动规格（.githooks/pre-commit）

插入位置：紧跟前端 build 段之后（现 :142 一带），复用同一 FRONTEND_STAGED 判定避免重复
git diff 调用：

```bash
# ── 段⑥'：前端单测（vitest, round35 §16-T-P1-6）──────────────────
if [ "${SKIP_FRONTEND_TESTS}" = "1" ]; then
    echo "[pre-commit] SKIP_FRONTEND_TESTS=1, 跳过前端单测"
elif [ -n "$FRONTEND_STAGED" ]; then
    echo "[pre-commit] ▶ 前端 src 变更 → vitest run ..."
    if ! (cd frontend && cmd /c "npx vitest run" ); then
        echo "✗ vitest 失败，commit 已阻止"; exit 1
    fi
fi
```

**关键设计决策**：
1. 触发口径与 build 段完全一致（`frontend/src/*` + `index.html` + `vite.config.js` +
   `package.json`；`frontend/public/` 不触发）——一个判定变量驱动两段，行为可预期；
2. 独立跳过变量 `SKIP_FRONTEND_TESTS=1`（不复用 SKIP_FRONTEND_BUILD——测试与构建是
   两个独立维度，紧急热修时允许只跳测试不跳构建验证）；
3. 跑全量不用 --changed：jsdom 下 setup.js 级联影响跨 spec，related 模式有漏测面，
   且全量实测仅 ~18s（patrol latest.json L5=18.55s 含 build，纯 test 更短）；
4. 外层 timeout 兜底 300s（对齐 F23「门禁不得无限挂起」纪律）。

#### 验收（含负向）

1. **正向**：正常前端 commit → 该段执行且绿，耗时 ≤30s；
2. **负向①**：故意改坏任一 spec 断言 → staged commit 必须被拦截且输出失败 spec 名；
3. **边界①**：仅改 frontend/public/* → 不触发（零耗时增加）;
4. **边界②**：纯后端 commit → 不触发；
5. **跳过**：SKIP_FRONTEND_TESTS=1 → 跳过且有 echo 提示（对齐 docker/mypy 段风格）；
6. **治理登记**：15 段 → 16 段，同步更新 AGENTS.md「门禁治理约定」的段数与清单行
   （该约定自身要求段数同步，2026-08-23 数字口径）。

---

## 17. 并稿总排期 + 批次命名消歧（2026-08-23 多轮 review 追加）

> 本节为多轮 review 的编排收拢：不新增技术发现——①批次命名总表与跨文档消歧规则；
> ②全部批次一览 + 依赖 DAG + 推荐执行波次；③并稿后全局 design-checklist 补查。
> 实施时以本节为排期入口；技术细节仍以各原节为准（本节每行均带来源指针）。

### 17.1 ⚠️ 批次命名消歧（跨文档 B 系撞号）

**冲突事实**：round34 §10 前端 UX 批次编号 **B1-B7**（已采纳入档）与本档 §6 引擎重构
批次 **B1-B6** 同号不同物——r34-B4 = R110 in-flight 去重（前端数据层），本档 B4 =
黄金快照回放 harness（引擎安全网）。实施排期时极易误读。

**消歧规则**（不改名的理由）：本档 B1-B6 在 §0-§10 内数十处引用且与 F/D/S 系强绑定
（B1-F1a 等），整体改名漏改风险高；round34 B1-B7 已采纳不宜回改。采用**文档前缀约定**：

| 写法 | 含义 |
|---|---|
| `B#` / `§6-B#` | 本档引擎重构批次（§6.1-§6.6） |
| `r34-B#` | round34 §10 前端 UX 批次 |
| `T1-T4` | round34 §11 测试命名重组批次 |
| D/S/F、A/C、FM/FS、R12x/FE、P0-x(§11/§12)、T-Px(§16) | 各节自有系列互不冲突 |

本次 review 已修正的既有歧义引用：§12.4-P1-a 与 §12.8 表「§10 B4」→ r34-B4；
§14.10 三处裸 B# → round34-B#；§15.8-FM2 归宿补 §6-B4 前缀。

### 17.2 全部批次总表（来源指针 + 文件域冲突检查）

| 波次 | 批次 | 来源 | 内容一句话 | 量级 | 文件域 |
|---|---|---|---|---|---|
| ① | A1-WAL | §13.9-T-A1 | portfolio.db 启 WAL + busy_timeout | 小 commit | database.py / hub/_common.py / README 一行 |
| ① | §12-P0-2 | §12.3 | _TIMEOUT 遮蔽拆每源常量 | 一行 | global_markets_fetcher.py |
| ① | T-P0×5 | §16.7 | network 排除 / mypy 提示 / 空心测试 / marker 措辞 / perf 死段清理 | ~0.5d | pytest.ini / pre-commit / 2 个前端 spec / patrol 打印 |
| ② | B1 | §6.1 | 引擎 D1-D5 缺陷修复，**吸纳 A5 门禁补盲 + C3 常量倒置 + FM1 IC 方向归一** | 0.5-1d | engine/* / strategy_design 编排段 / check_engine_purity.py / core/factor_aggregate.py |
| ② | B2 | §6.2 | = round34 R104/R105，含 A2 factors 反向依赖搭车 | r34 既定 | ic_tracker / factor_registry / risk_controls / strategy_design |
| ②支线 | §11-T①②③ | §11.5 | 任务容器 + 循环异常治理 + WS 背压统一 | ~1d | core/background_tasks.py(新) / main.py lifespan / task_manager / design_report / routers |
| ②支线 | FE1+FE2 | §14.11 | store 死 action 收口 + watchlist 双拉 + 四态补齐（顺带 §16-T-P2-10 裸奔组件补测） | ~1d | stores/* / WatchlistPanel / SourceMonitor / TokenMonitor / NewsView |
| ③ | §12.7-B 第一步 | §12.7.3 | 删调度死链路 + market.js realtime 死分支 + 文档同步 | ~0.25d | main.py 注释块 / tasks/market_refresh / market.js:88-104 / README/AGENTS/契约 |
| ③ | §12-P0-4 | §12.3 | 因子矩阵双重计数白名单化 + 双消费方口径核对 | 小 | hub/_pool.py + strategy_design/strategy_check 核对 |
| ③ | §11 建议#4/#5/#6 | §11.3 | 取消 API / 排队可见性 / 卫生批（依赖 T-① 容器就位） | 小~中 | task_manager / strategy_check_worker |
| ④ | B3 | §6.3 | EngineConfig 收敛 + taxonomy 分类器合并（快照先行） | 1-2d | budgets / allocation_engine / engine/taxonomy.py(新) |
| ④ | §6-B4 | §6.4 | 黄金快照回放 harness（B5/B6/FM2 安全网） | ~1d | tests/fixtures/engine_golden(新) / scripts/engine_golden_replay.py(新) / patrol --golden |
| ⑤ | FM2 | §15.4 | IC 加权尺度相对化（composite 输出变化 → 快照显式再生） | 小批 | core/factor_aggregate.py 单文件 |
| ⑤ | FE3 | §14.11 | WS_BASE 抽公共 + interceptor 错误规范化 + task 心跳 | 0.5d | 三 WS 实现 / api/index.js |
| ⑤ | T-P1 剩余 | §16.7 #7-9 | T2 计数比对自动化 / FakeWebSocket helper / console 收集 / 基线更新 | ~1d | pre-commit / src/test/helpers / AGENTS.md(FE4 同动作) |
| ⑥ | B5 | §6.5 | allocate 流水线化五段管道（独立轮，硬前置 §6-B4） | 3-5d | allocation_engine.py 内部重构 |
| ⑥ | B6 | §6.6 | 收益指标持仓推导（渐进，契约先行） | 渐进 | 编排层 + API 契约 + UI 标注 |
| ⑥ | FM3/FM4 | §15.5 | 第五顶层键接入 etf_quality（前置探针 premium_discount/shares_change/benchmark_close） | 新立项小批 | factor_aggregate + registry 接入 |
| ⑥ | A3/A4 | §13.4 | 线程池有界化 / 缓存断点收敛 | 独立小轮 | async_utils / cache_service |
| ⑥ | FE5 | §14.11 | views/components 归位（并入 round34-B7 执行） | 随 r34-B7 | router/index.js + 页面归属 |
| ⑥ | §12.7-B 第二步 | §12.7.3 | 事件驱动推送增强（可选） | ~0.5d | market_service 回源点广播 |
| ⑥ | T-P2 余项 | §16.7 #11-13 | coverage 开启 / engine 两模块拆测 / 最小 CI | 渐进 | vitest.config / GitHub Actions |

### 17.3 依赖 DAG 与推荐执行波次

```
波次① 清台小改（全部独立，合计 ≤1 天）
   A1-WAL ┬ §12-P0-2 ┬ T-P0×5     ← 三者零文件交集，一个下午可全清
          ┴──────────┴───────────
波次② 三线并行（文件域互斥，~1.5 天）
   主线:  B1 ──→ B2（都触 strategy_design.py，B1 先合；A2/C3/A5/FM1 已吸纳进 B1/B2）
   支线α: §11-T①②③（tasks/main.py/ws 域）
   支线β: FE1+FE2（前端域）
波次③ 调度收敛 + 卫生（~0.5 天，依赖波次②容器就位更稳）
   §12.7-B 第一步 + §12-P0-4 + §11 建议#4/#5/#6
波次④ 引擎深化前置（B3 ‖ §6-B4 可并行起步，~2 天）
   B3（分类器快照先行）‖ §6-B4（黄金基线五场景首跑）
波次⑤ 依赖就绪项（~1.5 天）
   FM2（硬前置 §6-B4 基线固化）+ FE3（随 r34-B4）+ T-P1 剩余（#7 挂 round34-T2）
波次⑥ 独立轮 / 渐进（不设统一截止）
   B5（硬前置 §6-B4）→ B6 渐进；FM3/FM4（探针过才立项）；A3/A4；FE5（随 r34-B7）；
   §12.7-B 第二步（可选）；T-P2 余项
```

**关键路径**：波次①②③④ 合计约 **5-6 个工作日**到达「引擎可安全深改」状态（§6-B4 就绪），
B5 另计 3-5 天独立轮。全程验收口径沿用 §8 全局口径 + 各节自有验收块。

### 17.4 并稿后 design-checklist 全局补查（跨节项，不重复各节自查）

| # | 检查项 | 全局结论 |
|---|---|---|
| 1 | 可行性探针 | 各节自含：FM3 数据探针前置（未过不出方案）、B3 分类器快照先行、§6-B4 黄金基线先行——「先固化后动手」贯穿 |
| 2 | 证据链 | 全部 file:line 实证；strategy_design.py ±30 行并行漂移已标注（实施以函数名锚定）|
| 3 | 验证窗口 | 全部结论静态可离线复现；运行时验收（patrol/e2e/perf）在实施期任意时段执行；无待交易时段复测项 |
| 4 | 非兜底数据 | 各修复方向均为消除假象（D5 归因丢失 / FM1 反向衰减 / R127 空态冒充错误态 / FM1 测试 mock 理想输入），无新增兜底路径 |
| 5 | 真实调用点 | 各批次验收块均含 reality check 条目；无新增端点（除既定契约先行项 B6/FM3） |
| 6 | 四态 UI | FE2 补行为缺陷 + §16-F3 补测试覆盖，两线闭环 |
| 7 | 复杂度审计 | 波次①-⑤ 全部零新增网络/DB/文件调用；新增文件仅 background_tasks/taxonomy/engine_golden_replay 三个纯本地模块；T-P1-6 新门禁段实测耗时 ~18s 有预算 |
| 8 | 已知问题模式 | round14 五类盲区对照：F4/FM1 触碰「格式断言/mock 理想输入」（处理策略已入各节）；门禁自身可被抓假（B1-F1a/T-A5 负向 fixture）为本轮新增纪律 |

**实施标准声明**：截至本节，§0-§16 各批次均已具备「改动内容 + 落点 file:line + 测试名
（含负向）+ 验收口径」四要素；唯一例外 FE5 与 r34-B7 绑定（随其方案细化）、B6 为渐进
批次按契约先行流程逐项出方案。本文档达到实施标准——**收到「开始实施」指令前不动任何代码**。

---

## 18. 冗余清理专项（RC 系）— 仓库级冗余识别 · 处置分级 · 波次⓪清台批

> 2026-08-23 定稿（三轮 review 达标：RC-R1 作者自查 / RC-R2 子代理独立交叉复核 / RC-R3 终检，
> 留痕见 18.10）。原独立成稿 `docs/redundancy-cleanup-plan.md` 按用户裁决并入本文，**原文件已删除**；
> 本节即该专项的唯一载体。性质：**只设计未实施**。
>
> 定位：本文 §0-§17 的**补集**——已排期重构批次（B/A/C/FE/FM/T 系列）此处只做索引引用、
> 不重复设计；本节新增的是彼时未覆盖的仓库级冗余：垃圾文件 / 怪目录 / 数据目录漂移 /
> 过期注释与幽灵引用 / WS 幽灵通道判定。
>
> 编号消歧（沿 §17.1 惯例）：本节条目一律使用 **RC-** 前缀（RC-A/RC-B/RC-C/RC-D 四类；
> RC-R1~R3 为本节 review 轮次编号），与既有 B1-B6（引擎）、A1-A5/C1-C8（§13）、
> FE/FM/FS/T 系列、R123-R128（前端发现）互不冲突；跨节引用一律带 RC- 前缀或 18.x 节号。
> 本节批次**不改动 §17.2 总表与 §17.3 DAG**（二者已定稿）——执行关系：**波次⓪（18.6）
> 先于 §17.3 波次①执行**，其余 RC-D 各项随原归属批次不变。
>
> 工具基线（2026-08-23 实测）：`check_api_usage.py` → API methods total 54, Unused 0；
> `audit_unused_symbols.py` → P3-1 OK, unused stock 0（baseline `{}`）。
> 即符号级静态审计当前全绿，剩余冗余集中在「跨层死 action / 落点漂移 / 仓库卫生」三类，
> 正是静态工具的盲区（AGENTS.md 反假完成机制所指「改了不被人调用的路径」需人工 grep 验证）。

### 18.0 执行摘要

| 判定 | 数量 | 说明 |
|---|---|---|
| ✅ 已被历史轮次消化 | 11 项 | round23 死端点清单 9 项中 8 项已删、`news/research` 被 F29 接通、`dailyPnl/getPnl` 已合并（frontend/src/api/index.js:59 注释自证）、§12.5 #1 孤儿 NAV 双 except 已随 round36 ruff 清理消失 |
| 🗑️ A 类：可直接删除（零风险） | 4 组 | 本地垃圾文件/怪目录/gitignore 缺口，见 18.2 |
| 📝 B 类：注释·配置级小联动 | 4 项 | 过期 TODO ×3、死符号对 ×2、ttl 键二选一、AGENTS 幽灵引用，见 18.3 |
| 🔁 C 类：数据落点收敛（活漂移） | 6 组 | 现役写入 4 处（C1 sentiment_history→app/data、C4 etf_scanner→backend/data、C5 _regime_sentiment→backend/data、C6 market_service→app/data）+ 残留清理 2 组（C2/C3），见 18.4 |
| 📋 RC-D 类：归并本文既定批次 | 5 组 | FE1+FE2 / §12.7-B / 幽灵 WS 判定（design-report 三选项裁决） / 测试归位 / 大文件拆分，见 18.5 |
| ⛔ 明确不做 | — | 沿用本文 §7 / §13.6 / §15.7 防过度工程清单 |

核心判断：**代码库的"死端点/死符号"层面已经相当干净**（三轮审计工具全绿 + round23/35 清单基本消化），
当前真正的冗余债在两处：①前端 store 层死 action 群（R123，已排 FE1）；②**数据文件落点三分天下**
（项目根 data/ 正牌 vs backend/app/data/ 包内残留 vs backend/data/ 空壳），彼时未收录于 §0-§17，是本节最大增量。

---

### 18.1 方法与证据口径

- 工具复跑：`python scripts/check_api_usage.py`（54/54 有调用点）、
  `python scripts/audit_unused_symbols.py`（unused=0，baseline 空）→ 符号级零发现。
- 逐项重验 round23 `_findings_redundant_review.md` 的 9 个死端点 + 死代码表（rg 词界 grep，
  生产代码 = frontend/src + backend/app + scripts/verify_e2e.py 三域）。
- 逐项重验本文 §12.5（P2 代码卫生 7 项）、§14.9 R128、§16.5（测试冗余）现状。
- 新增扫描域（彼时未收录）：git ls-files 跟踪状态、未跟踪垃圾盘点、数据目录三方对比、
  WS 通道前后端对账、config 数据路径推导链。

---

### 18.2 RC-A 类 — 可直接删除（零风险，静态验证充分）

#### RC-A1 `backend/E< U+F03A >/` 怪目录树（5 个文件）

- 路径：`backend/E/ETF_Surge/data/{portfolio.db, source.db, token_usage.db}`（目录名含私用区字符
  U+F03A，是 Windows 盘符冒号的变体字形）。
- 证据：三个 db 最后写入 **2026-07-29 15:26**，此后一个月无更新；正牌活跃库在项目根 `data/`
  （portfolio.db 56MB，2026-08-23 14:54 仍在写）。成因推断：某次进程把 `E:` 当相对目录名创建
  （cwd=backend 时 `E:\ETF_Surge\data` 被拆成相对路径段）。
- 处置：整树删除。删除前 `Get-ChildItem -Recurse` 二次确认为 3 db 共 5 文件即可。
- 风险：零——时间戳 + 无任何代码引用该怪名路径（rg 全仓无命中）双证。

#### RC-A2 日志/调试垃圾（backend 根目录 13 个文件 + 根目录 9 张截图）

- backend：`bs2.log cr.log crash.log full_pytest.log md3.log pytest_full.log pytest_full2.log
  rtc.log xdist1.log xdist2.log _debug_out.txt _debug_output.txt` —— 均未跟踪（`git status --ignored` 实证）。
- 其中 **`mypy_errors.txt` 是唯一被 git 跟踪的垃圾** → 需 `git rm --cached backend/mypy_errors.txt` 并入 .gitignore。
- 根目录：`audit-config/dashboard/dashboard-full/dashboard-mobile/dashboard/market/news/portfolio/source/token-viewport.png` ×9 —— 未跟踪截图。
- 处置：本地删除 + .gitignore 补条目（见 A4）。

#### RC-A3 数据目录探针残留（项目根 `data/round34*` ×20）

- `round34_probe_sa.py / round34_assert_check.py / round34_assert_design.py / round34_probe_task734.py /
  round34_ic_date_ranges.py`（诊断脚本）+ `round34_*.json/md` ×15（探针产物）。
- 证据：全部为 round34 会话的一次性探针/抓取物；`.gitignore` 已含 `data/` 故不入库，纯本地噪音。
- 处置：移入 `logs/` 或直接删除（按 round16 惯例「先归档到 logs/roundXX/ 再删」，此处价值低可直接删）。

#### RC-A4 .gitignore 缺口（防再繁殖）

现缺条目（对照实测未跟踪项）：

```gitignore
# 追加
frontend/coverage/
.opencode/
audit-*.png
backend/mypy_errors.txt   # 配合 git rm --cached
/backend/E*/               # 防 U+F03A 怪目录复发（锚定 backend 下 E 开头大写目录，
                           # 不用裸 E*/ 避免误伤未来合法目录）
```

验收：追加后 `git status --short` 中上述四类不再出现。

---

### 18.3 RC-B 类 — 注释/配置级小联动（不动行为语义）

#### RC-B1 `market.py` 过期 TODO 注释 ×3（端点全是活的）

| 行 | 端点 | 活性证据 |
|---|---|---|
| market.py:524 | `GET /indices/meta` | 前端真实调用 UnifiedAnalysis.vue:460（`marketApi.indicesMeta()`），api/index.js:33 定义 |
| market.py:634 | `GET /fundamentals/{symbol}` | verify_e2e.py:2446 覆盖 |
| market.py:698 | `GET /sectors/rotation` | :699 注释自证非死代码（verify_e2e/tests 覆盖）——TODO 与保留注释并存自相矛盾 |

处置：三处 TODO 注释改为事实描述（如「接入点：UnifiedAnalysis.vue:460」）或直接删除 TODO 行。
零行为变化；check_routes 契约不受影响（不动路由本体）。

#### RC-B2 etf_scanner 死符号对 `_etf_list_cache` + `ETF_CACHE_TTL`（R1 修正扩容）

- 证据：
  - `_etf_list_cache = {}`（etf_scanner.py:29）——round11 P1-5 TTL 归一（:25 注释自证「不再散落本地常量」）后的遗留容器，生产代码零读写；
  - `ETF_CACHE_TTL = _CACHE_TTL["etf_list"]`（etf_scanner.py:30）——同批归一的兼容别名，除定义外全仓零引用；
  - ⚠️ **有测试引用**（R1 补验推翻初版「tests 无引用」结论）：`tests/test_remaining_fixes.py:88-101`
    `test_p02_etf_cache_defined` 为空心存在性断言（try import etf_scanner → except try import china_market →
    except `pytest.skip`），只断言 isinstance(dict) 与 >=60，无任何行为价值——本文 §16.6 空心测试同类。
- 处置：删 etf_scanner.py:29-30 两行 + **整段删除** `test_p02_etf_cache_defined`（两符号消失后该测试
  恒走 skip 分支，留之即恒绿占位噪音）。
- 风险：零——china_market.py 无同名符号（rg 实证），try-import-B 分支本就不可达。

#### RC-B3 `TASK_TYPES[*]["ttl"]` 声明与消费断裂（二选一）

- 声明：task_manager.py:51-53（design/check/report 各 ttl=600）。
- 断裂证据：运行时零读取——task_manager.py 内无 `["ttl"]`/`.get("ttl")` 命中；
  R1 补验全仓（app+tests+scripts）所有 `ttl` 命中均属其他模块的独立参数
  （cache_service/macro_fetcher/factors._get_cached/tests_ok_marker 等），无一处作用于 TASK_TYPES；
  但 tests/test_task_db_persistence.py:445-448 **断言每个 task_type 必须有 ttl** —— 测试在保护一个没人消费的字段。
- 处置二选一（建议 ①，改动最小且保住过期任务清理语义的可能性）：
  ① 在任务淘汰逻辑真正读 `TASK_TYPES[task_type]["ttl"]` 接通；
  ② 删 ttl 键 + 同步删 :445 断言块。
  ⚠️ 若选 ② 需先确认没有依赖 TTL 的隐式行为（grep `600` 于 task_manager.py 全文复核一次）。

#### RC-B4 AGENTS.md 幽灵引用（FE4 批次的本文实证补充）

- AGENTS.md:177 「composables/useMarketWS.js」——该文件在 frontend/src 全域不存在（rg 零命中）。
- AGENTS.md:194 WebSocket 路径表列出 5 条，其中 `/ws/market/{symbol}`、`/ws/design-report/{session_id}`
  前端零连接（前端实际只连 `/ws/news` useNewsWS.js:25、`/ws/task-notifications` useTaskWS.js:39、
  `/ws/portfolio` stores/market.js:65）。
- 处置：并入本文 FE4 批次（§14.11，10 分钟量级），本文提供精确行号。

---

### 18.4 RC-C 类 — 数据落点收敛（并入前 round35 最大盲区）

#### 现状三方对比（2026-08-23 实测，RC-C 类总览）

| 目录 | 内容 | 时间戳 | 判定 |
|---|---|---|---|
| 项目根 `data/` | portfolio.db 56MB / kline_cache.json 2.65MB / token_usage.db 8.9MB / source.db 8.3MB | 08-23 14:54~14:57 活跃 | ✅ 正牌（config.py:16 `_PROJECT_DIR/"data"` + docker-compose.yml:46 `./data:/app/data`） |
| `backend/app/data/` | portfolio.db(08-19) / kline_cache.json(08-19) / etf_list_cache.json(08-04) / tasks.json(07-31) / source.db / token_usage.db / sentiment_cache.json / **sentiment_history.json(08-23 活跃，C1)** / **indices_cache.json(现役，C6)** | 混合 | 🔴 历史残留 **+ 两处现役写入**（C1 sentiment_history、C6 indices_cache） |
| `backend/data/` | portfolio.db / source.db / token_usage.db 全部 0 字节；etf_list_cache.json(C4)、sentiment_cache.json(C5)、**etf_index_mapping.json(C4 姊妹项，读写活跃)** 宿主运行时在此生成/刷新 | — | ⚠️ 空壳 db + **三家现役 json 写入方（C4×2/C5）** |

> 同族根因盘点：手拼相对路径 data 的活代码共 **5 处**（C1 fundamentals_fetcher:782 /
> C4 etf_scanner:145+:828 / C5 _regime_sentiment:107+:121 / C6 market_service:194+main.py:443 fallback），
> 另 hub/_kline.py:114-121 保留同款 fallback（R86 已加 WARNING 且 settings.data_dir 优先，暂不动）。
> R86/R93 已保证运行时 `settings.data_dir` 非空且为绝对路径（config.py:142-171 model_validator：
> DATA_DIR env → database_url 解析目录 → 回退模块常量 `_DATA_DIR`）——统一改造可安全依赖它。


#### RC-C1（活漂移，优先）`fundamentals_fetcher.py:782` sentiment_history 写入包内

```python
# fundamentals_fetcher.py:781-782
os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sentiment_history.json"
# dirname×2(abspath(app/fetchers/xxx.py)) = backend/app → 写 backend/app/data/sentiment_history.json
```

- 实证：该文件 LastWriteTime = 2026-08-23 14:54（今天仍在写），与正牌 kline_cache 同分钟刷新 → 双落点并行。
- 触发点：`:1110 _persist_sentiment_history`（情绪计算产出时持久化）/ `:1092 _load_sentiment_history`
  （加载）——情绪计算有降级链，非交易时段亦可触发，验证窗口无强约束。
- 同源先例：hub/_kline.py:114-121 是同族问题的**成功修复样例**（settings.data_dir 优先 + 源码目录
  fallback 带 R86 WARNING）；etf_scanner 的 P1-11「已修」实为失败案例（见 C4，少一级 ../）——
  C1 的改造模式应以 _kline/R86 为模板而非 P1-11。
- **实施细化（重大修改项，按此粒度执行）**：
  1. TDD 先写失败单测（放 tests/test_remaining_fixes.py 或新文件 test_data_dir_convergence.py）：
     monkeypatch `settings.data_dir = tmp_path` → 调 `_SENTIMENT_HISTORY_FILE` 构造（或抽出的
     `_sentiment_history_path()` 函数）→ 断言路径前缀 == str(tmp_path)。当前实现该断言必失败。
     建议顺手把 :781-782 的内联拼接重构为模块函数 `_sentiment_history_path() -> str`，可测性最好。
  2. 实现：`_SENTIMENT_HISTORY_FILE` 改为惰性求值（函数内拼 `getattr(settings, "data_dir", "") or _DATA_DIR`，
     import 处 `from ..config import settings, _DATA_DIR`），与 _kline.py:112 模式一致但**去掉源码目录 fallback**——
     R93 保证 data_dir 非空，`or _DATA_DIR` 只是双保险。
  3. 旧落点文件处置：app/data/sentiment_history.json 为 len≤3 滑动窗、价值低，**直接不迁移**（重启自然重建）；
     删除该文件防混淆。
  4. 验收（18.7 第 3 条强化——原文 off-by-one 引用一并修正）：删除旧文件 → 触发一轮情绪计算（调 `/api/v1/market/sentiment` 相关服务路径或等
     warmup 定时任务）→ 断言项目根 `data/sentiment_history.json` 生成且 JSON 内容含 sentiment_history 键非空
     （真实值断言，非仅存在性）→ `app/data/` 不再出现新文件。
- 风险评估：低。读写同函数域（:1092/:1110 同文件），不存在新旧路径读 写不一致窗口；唯一外部影响是
  重启后首个计算周期滑动窗从空重建（历史仅 3 个点，自愈）。


#### RC-C4（RC-R1 新增发现）`etf_scanner._etf_cache_file()` 宿主分支路径 bug —— P1-11 修复不彻底

```python
# etf_scanner.py:140-145（实测原文）
if os.path.exists("/app/data"):
    return os.path.join("/app/data", "etf_list_cache.json")
# P1-11 (round9 §4.3-B 附带①): 宿主分支路径修正 `../../data`——旧实现
# `os.path.dirname(__file__)/../data` 解析到 backend/app/data/（多带一层 app/，
# 文件不存在）→ ...正确为项目根 data/。
return os.path.join(os.path.dirname(__file__), "..", "..", "data", "etf_list_cache.json")
```

- **矛盾实证**：`dirname(abspath(etf_scanner.py))` = `backend/app/fetchers`，上两级 = **backend/**，
  再拼 data → `backend/data/etf_list_cache.json`——注释声称「正确为项目根 data/」，实际少一级
  （需三级 `../../../data`）；同函数 docstring :134「③宿主机开发回落 backend/data（现状路径）」
  与 :136-138 P1-11 注释**自相矛盾**，实际行为与 docstring 一致、与 P1-11 声称的修复目标相反。
- 防线失守原因：test_etf_cache_persist.py:29-36 宿主用例断言过弱（仅 `"data" in path` 且不以
  `/app` 开头）——backend/data 与项目根 data 都能通过，抓不住错位。
- 危害：宿主机开发的 ETF 列表缓存落点与「正牌 data_dir」约定背离（同族漂移成员之一，
  与 C1/C5/C6 同根因）；且持续污染 backend/data 目录（与 C5 两家叠加），加剧 18.4 三方对比的混乱。
- **实施细化（二选一，建议 A）**：
  - **A（推荐）：并入 C1 同批统一改造**——`_etf_cache_file()` 删除手拼相对路径分支，改为
    `DATA_DIR env → settings.data_dir or _DATA_DIR` 两级（容器 `/app/data` 分支可保留为
    data_dir 的等价快路径，或直接删——容器内 R93 已解析 data_dir=/app/data，属冗余防御）；
    同步把 test_etf_cache_persist.py 宿主用例断言收紧为 `path.startswith(str(项目根 data))`
    或 monkeypatch data_dir 后精确相等断言（负向：backend/data 前缀必须失败）。
  - B（最小改）：仅补一级 `../../../data`——修掉表象但保留第四种路径推导风格，不推荐。
- 与 C2 的关系：C4 修复后 app/data/etf_list_cache.json(08-04) 确认成为纯残留，随 C2 整目录删除。
- **R3 扩容（同文件姊妹项）**：etf_scanner.py:826-829 `_TRACKED_INDEX_CACHE` = dirname×3 +
  `data/etf_index_mapping.json` → **backend/data 第三家写入方**（:835 读/:846 写皆活跃，
  `_save_tracked_index_cache`）；且 round34 曾因该文件脏值出真实 bug（test_fund_fetcher_guard.py:4
  「518880 → 黄金9999」映射错乱根因即此文件）。随 C4 方案 A 一并改 `settings.data_dir or _DATA_DIR`
  （同一文件两处常量，一个 commit 收口）。

---


#### RC-C5（RC-R2 子代理发现）`_regime_sentiment.py:107/:121` sentiment_cache 写入 backend/data

```python
# hub/_regime_sentiment.py:107（写）/ :121（读，A02 crash-recovery 双拷贝）
_cache_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
# dirname(hub/_regime_sentiment.py)=backend/app/services/hub → 上三级=backend/
# → backend/data/sentiment_cache.json
```

- 触发链：main.py:696 `_regime_sentiment_refresh_loop`（120s 无条件循环）→ refresh_sentiment_cache →
  刷新成功即持久化 / 失败时回读——**backend/data 目录的第二家现役写入方**（第一家见 C4）。
- 危害（分环境）：容器内 `__file__=/app/app/services/hub/...` 上三级恰为 `/app`（挂载卷）——**容器内碰巧正确**；
  宿主机则落到 backend/data 持续污染。这种「容器对、宿主错」的巧合正是该模式难以被发现的原因
  （与 C4 的「宿主机错落点」互为镜像）。
- 处置：与 C1/C4/C6 同批统一改 `settings.data_dir or _DATA_DIR`（同一 commit 串成「落点收敛」主题；
  写/读两处拷贝一并改）。验收同 18.7：全仓手拼相对路径 data 模式归零。


#### RC-C6（RC-R2 子代理发现）`market_service.py:188-195` indices_cache 写入包内 app/data —— **现役**

```python
# market_service.py:188-195 _get_cache_db_path()
data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
# dirname(services/market_service.py)=backend/app/services → 上两级=backend/app
# → backend/app/data/indices_cache.json；:204 读 / :225 写 / :232 import 时加载
```

- 定性：app/data 目录的**现役写入方**（非历史残留）——直接推翻初版 C2 把该目录整体归因为
  「R86/P1-11 前 fallback 时代产物」的说法。
- 危害（分环境）：容器内 `__file__=/app/app/services/market_service.py` 上两级 = `/app/app` → 写
  **镜像层 /app/app/data**（非挂载卷，容器重建必丢 + 镜像膨胀）——与 etf_scanner 旧注释自述的
  「旧实现在镜像层 /app/app/data 必丢」完全同款；宿主机写包内 app/data（错位但持久）。
  两环境皆错，是四项中危害最实的一处。
- 处置：并入 C1/C4/C5 同批收敛（改 `settings.data_dir or _DATA_DIR`）；已有 indices_cache.json(1MB+)
  数据可保留在旧位置由新代码自然重建，或手动迁移一次（内容为指数 OK 缓存，价值低，建议不迁移）。
- **R3 补充（关联点）**：main.py:441-446 `_probe_ok_cache_mtime()` 是本缓存的 mtime 探测器，
  settings.data_dir 优先 + dirname×3 fallback——fallback 段与 C6 同源，随 C6 一个 commit 收口。


#### RC-C2 `backend/app/data/` 残留清单（R2 修正：删除前置扩容）

portfolio.db(372KB)/kline_cache.json(1.07MB)/etf_list_cache.json/tasks.json/source.db/token_usage.db/sentiment_cache.json
—— 多数对应 R86/P1-11 修正前的 fallback 时代产物（tasks.json 另见 round23-A5 对 backend/data/tasks.json
的前案）；~~整目录~~ ~~C1+C4 后即可删~~ **R2 修正：硬前置 = C1+C4+C5+C6 四项全部落地**
（否则 etf_list_cache(C4)、indices_cache(C6)、sentiment 相关(C1/C5)都会删了再生）。
四项落地后整目录删除；删除前最后确认 `settings.data_dir` 在本地启动日志中解析为项目根
（main.py 启动 WARNING 缺席即可）+ 一轮 warmup 后 `git status`/时间戳复核无新生成。


#### RC-C3 `backend/data/*.db` 0 字节空壳 ×3

- 从未写入（0 字节）；Docker 挂载点是项目根 `./data`（docker-compose.yml:46/:93）。
- ~~backend/data 无消费者~~（R1 修正：etf_scanner 是写入方之一，见 C4；**R2 再修正：_regime_sentiment
  是第二家**，见 C5——但 3 个 0 字节 db 仍非两者所写（它们只写 *.json），成因候选为 cwd=backend 下以
  相对路径跑 sqlite 的历史操作，如 scripts/archive/repair_encoding.py:5 `DB = "data/portfolio.db"`）。
- 处置：删除 3 个空壳 db。**排在 C4/C5 之后执行**（二者不修则该目录持续被 json 写入，
  db 本身虽不会再生，但目录语义未清前删除易造成「已收敛」错觉）。

> C 类共同收益：消除「备份了错误副本」「清缓存清错地方」「容器重建丢数据」三类事故土壤；
> 这正是 round16 冗余清理 41 项同类问题的延续（round16 §6 先归档再删口径沿用）。

### 18.5 RC-D 类 — 归并本文既定批次（索引，不重复设计）

| # | 内容 | 本文补充的现状实证 | 归属批次 |
|---|---|---|---|
| D1 | 前端 store 死 action 收口：market.js:172-190/:237 五个 REST action 零调用者 + indicators/signal/history 死 ref；portfolio.js 九个 action 死五个(:44/:49/:55/:61/:66) + strategyResult 双源(store :9 vs DashboardAiTools.vue:195)；loading store 整体休眠（仅 App.vue:96 读 active，无 show/hide 调用者） | 本轮逐一重验**全部仍存留** | 本文 §17.3 波次②支线β FE1+FE2（~1 天） |
| D2 | 调度死链路 + market.js realtime 分支判定 | market.js:91 分支仍在 | 本文 §12.7-B 第一步（§17.3 波次③） |
| D3 | 幽灵 WS 通道处置：ws.py:86 `market/{symbol}`、:128 `design-report/{session_id}` 前端零连接（前端实际只连 news/task-notifications/portfolio 三通道，见 B4） | R1 实证：design-report **不是纯死端点**——worker 侧 design_report.py:524/:592/:613/:624/:631 五处活跃 `report_manager.broadcast`，ws.py:128-146 为接收端；但前端 DashboardAiTools.vue:520/:549 已走 REST 轮询拿详情（detailRes.data），WS 推送实为发向虚空的冗余链。处置三选一见下方细化 | FE4 文档先行 + 端点处置挂本文 §12.7-B 同批 |

| D4 | 测试归位：rXXX vs 业务域重叠 4 组、FakeWebSocket 三套抽共享 | 未重验（round34-T2 既定） | 本文 §16-T 系列 |
| D5 | 大文件拆分 PortfolioManager.vue 1165 行 / FactorModelView.vue 1034 行 | 行数待实施时复核 | 随 r34-B3/B7 |

**D3 细化（重大修改项）——design-report 幽灵 WS 三选项裁决**：

| 选项 | 内容 | 量级 | 影响 |
|---|---|---|---|
| ③-a 标注预留（最保守） | 仅改 AGENTS.md/契约标注「预留未接通」，代码不动 | 10 分钟 | 零风险；但虚空推送照旧，每次 LLM 设计任务仍序列化+发送无人接收的消息 |
| ③-b 断写保读（推荐） | 删 ws.py:128-146 端点 + report_manager.broadcast 改为 no-op/移除调用点（5 处），报告持久化与 REST 查询路径不动（DashboardAiTools 轮询已闭环）；report_manager 的 register/unregister/is_running/mark_running 若仅服务 WS 则一并评估删除 | ~0.5 天 | 需同步删 api-contracts 中 design-report WS 契约条目（check_routes 双向比对硬门禁，round23 复核 §1 教训）；verify_e2e 若覆盖该 WS 需同批调整 |
| ③-c 前端接通 | DashboardAiTools 改订阅 WS 推送替代轮询 | ~1 天 | 功能增强超出「清理」范畴，不建议在本专项内做 |

前置核查（③-b 执行前必做）：rg 确认 report_manager 除 design_report.py/ws.py 外无第三消费方；
`is_running`/`mark_running` 是否被防重复启动逻辑依赖（:517/:521 在用——若删 broadcast 但保留
运行态标记，则 report_manager 不能整体删，只删 broadcast/register/unregister）。

---

### 18.6 实施计划（波次⓪「清台批」+ 与 §17.3 波次衔接）

```
波次⓪ 清台批（本文新增，全部独立小 commit，合计 ~0.5-1 天；C4-C6 并入后量级上调）
  ⓪-A 垃圾清理        A1 怪目录 → A2 日志/截图(+git rm mypy_errors.txt) → A3 round34 探针 → A4 .gitignore
                       （一个下午可全清；每步后 git status 应干净）
  ⓪-B 注释/配置级      B1 三处 TODO → B2 死符号对(+删 test_p02_etf_cache_defined) → B4 AGENTS 幽灵引用
                       （FE4 可提前吸收）（B3 ttl 二选一单独 commit，先跑 test_task_db_persistence 定方向）
  ⓪-C 数据落点收敛     四处现役漂移统一改 `settings.data_dir or _DATA_DIR`（同一主题分 2 个 commit）：
                       commit-1 = C1 sentiment_history（TDD：先写「落点 == settings.data_dir」失败单测 →
                       抽 _sentiment_history_path() + 惰性求值 → 删旧落点文件 → 触发一轮情绪计算验证
                       新落点内容非空，见 RC-C1 细化）+ C5 同款（写/读两处）
                       commit-2 = C4 etf_scanner（方案 A，含收紧 test_etf_cache_persist 宿主用例为负向断言；
                       同文件姊妹项 :826-829 etf_index_mapping 一并收口）
                       + C6 market_service indices_cache（含 main.py:443 mtime 探测 fallback）
                       → C2 整目录删（硬前置 commit-1+commit-2 均落地）→ C3 空壳 db 删（排 C4/C5 之后防再生）
衔接：⓪ 完成后再进本文 §17.3 波次①（A1-WAL 等），RC-D 类随原波次执行不变。
```

依赖关系：⓪-C 与 §17.3 波次①零文件交集可并行；⓪-A/B 无任何前置；⓪-C 内部顺序
**C1∥C5 ∥ C4∥C6（四个收敛项可并行开发、按主题分 2 commit）→ C2 → C3**（C2/C3 有硬依赖，见各节）。
**不建议**把 ⓪ 与引擎 B1 批混在同一 commit（文件域隔离原则，AGENTS.md 选择性 add 白名单惯例）。

### 18.7 验收口径（波次⓪共用）

1. 静态：`git status --short` 无本批目标垃圾；`rg "_etf_list_cache|ETF_CACHE_TTL|TODO: 未接入前端"`
   归零于生产代码（B1/B2）；`rg "useMarketWS" AGENTS.md` 归零（B4/D3 文档部分）；
   **C 类总闸（双模式并集 + 白名单，R3 实测定稿）**：
   `rg 'os\.path\.dirname\(__file__\)' app -g "*.py"` ∪
   `rg 'os\.path\.dirname\(os\.path\.dirname' app -g "*.py"`，
   命中并集（R3 实测 11 行，含注释）按白名单核对：
   允许保留 = hub/_kline.py:117/:126（R86 fallback 暂不动）、warmup_profiler.py:50（logs 域合法落点，
   与 data 约定无关）、config.py:79 与 etf_scanner.py:143（注释行）；
   **其余全部归零**（C1 fundamentals_fetcher:782、C4 etf_scanner:145+:828、C5 _regime_sentiment:107/:121、
   C6 market_service:192、main.py:443 fallback 随 C6）。
2. 行为：⓪-C 各收敛项新增单测绿 + `verify_e2e.py` 全 PASS（fundamentals 端点 :2446 项必须 PASS）；
   ⓪-C 收尾跑一次 `patrol.py --full`（行为变更项按 AGENTS.md 验收期全量 1 次惯例），其余小 commit 用 `--diff`。
3. 反假完成自查：C1/C4 验证必须看到**新落点文件真实生成且内容非空**（非仅"没报错"），
   且旧落点不再新生成；C4 宿主用例的负向断言必须能失败（monkeypatch backend/data 前缀时断言红）；
   B3 若选接通路线，须有「ttl 到期任务被淘汰」的可观察行为断言，不许只留字段。
4. 性能软门禁：本批无热点路径改动，登记无新增性能债。

### 18.8 明确不做（防过度工程）

- 不重排 round35 已否决项（换均值方差优化器 / 大爆炸重写 allocate / ML 分类器等，本文 §7）。
- 不动 `scripts/archive/` 12 个归档脚本（已是归档态，有历史取证价值）。
- 不删 `docker-compose.diag.yml`（round23 §6.4 已裁决：PROFILE_WARMUP 承重件）。
- 不动并行会话工作区现场：`M backend/scripts/verify_e2e.py`、`M tests/test_r103_*.py/test_r105_*.py`
  为他人未提交修改，⓪ 批提交一律选择性 `git add` 白名单，严禁 `-A`。
- `docs/round35-architecture-review.md` 当前**未跟踪**——它是资产不是垃圾，应尽快单独 commit 入库（本批顺带提醒，不代做）。

### 18.9 design-checklist 八项自查

| 项 | 自查 |
|---|---|
| D1 可行性探针 | 本轮全部结论基于 rg/ls/timestamps 只读探测，无外部网络依赖，无需交易窗口 |
| D2 证据链 | 每项均给 file:line 或命令输出（RC 各节表格）；工具基线见文首 |
| D3 验证窗口 | ⓪-C1 触发一轮情绪计算可在任意时段验证（内部计算非行情窗口强依赖）；其余为静态清理 |
| D4 非兜底 | C1 验收明确要求真实文件生成非空；禁止「删了就行」式口头验收 |
| D5 真实调用点 | B1 三端点均给出活调用方；D3 删通道前置条件=先断 worker 推送链 |
| D6 四态 UI | 本批不触 UI |
| D7 复杂度审计 | C1 改动为常量替换级，无新增 IO/循环 |
| D8 已知问题模式 | 手拼相对路径 data 已实证 **4 处活代码**（18.4 盘点）+ hub/_kline fallback 第 5 处 → 实施时**强烈建议**同步落一条轻量 AST/lint 规则候选（如 patrol L4-ruff 自定义或 pre-commit 新段——按 AGENTS.md 门禁治理约定，新增须说明与既有 16 段的差异化价值：现有段无「文件落点约定」检查），不强制立项但登记为防复发首选 |

---

### 18.10 Review 记录（三轮 review 留痕）

#### RC-R1（2026-08-23，作者自查 · 证据链复核轮）

方法：对初版 7 个证据薄弱点逐一重验（全仓 rg 扩域 + 源码原文比对），4 处确认、2 处推翻、1 处细化。

| # | 初版表述 | R1 裁决 | 处置 |
|---|---|---|---|
| 1 | B2「tests 无引用，删定义行即可」 | ❌ **推翻**：tests/test_remaining_fixes.py:88-101 	est_p02_etf_cache_defined try-import 引用该符号（空心存在性断言）；连带发现 ETF_CACHE_TTL(etf_scanner.py:30) 同为零消费死别名 | B2 扩容为「死符号对+整段删测试」，见 RC-B2 |
| 2 | C3「backend/data 无消费者」 | ❌ **推翻**：etf_scanner.py:145 宿主分支 dirname(__file__)+../../data 实际解析到 backend/data；docstring:134 与 P1-11 注释(:136-138)自相矛盾——**新增 C4 路由 bug**（P1-11 修复少一级 ../） | 本节新增 RC-C4 细化（方案 A 并入 RC-C1 同批）；RC-C3 改排其后 |
| 3 | B3「运行时零读取」只验了 task_manager.py 单文件 | ✅ 升级为全仓证据：app+tests+scripts 全部 ttl 命中均属其他模块独立参数，无一处作用于 TASK_TYPES | RC-B3 补记 |
| 4 | C1「改读 settings.data_dir」未论证空串风险 | ✅ 确认可安全依赖：config.py:142-171 R93 validator 保证 data_dir 非空绝对（env→URL 解析→回退 _DATA_DIR）；仍建议 or _DATA_DIR 双保险 | RC-C1 实施细化 4 步落地 |
| 5 | D3「worker 可能仍推送」未实证 | ✅ 实证：design_report.py 五处活跃 broadcast(:524/:592/:613/:624/:631) + ws.py:128-146 接收端；前端 DashboardAiTools.vue:520/:549 已走 REST 轮询 → WS 链冗余但非纯死端点 | D3 三选项裁决表 + 前置核查清单 |
| 6 | app/data/portfolio.db(08-19) 写入方未定位 | ⚠️ 保持未知但登记候选：scripts/archive/repair_encoding.py:5 相对路径 DB（cwd 敏感）；不阻塞处置（C2 在 C1+C4 后整目录删，删除前有时间戳复核兜底） | RC-C2 注记 |
| 7 | sentiment_history 触发点未验证 | ✅ :1110 情绪计算产出时持久化 / :1092 加载；非交易时段可验证 | RC-C1 补触发点 |

其他修订：A4 .gitignore 的 E*/ 收紧为 /backend/E*/（防误伤）；18.6 波次⓪ 量级上调至 ~0.5-1 天并固化
⓪-C 内部顺序 C1∥C4 → C2 → C3；18.7 验收补 ETF_CACHE_TTL 归零、C4 归零、负向断言要求、
⓪-C 收尾 patrol --full。

#### RC-R2（2026-08-23，子代理独立交叉复核）

方法：read-only 子代理独立通读全文 + 抽验 5 项关键判定（C4/C1/B1/D1/B4）+ 高置信度找漏。
**5/5 抽验成立**（含 PortfolioManager.vue 同名本地函数干扰项的排除、useMarketWS 全仓 glob 零命中等
细节均复核通过）；**找漏命中 2 处文档未收录的同族漂移**，均为作者初扫遗漏：

| # | 子代理发现 | 作者复验 | 处置 |
|---|---|---|---|
| 1 | `_regime_sentiment.py:107/:121` 写/读双拷贝落点 = **backend/data**（dirname(hub)+上三级），120s 循环持续写——文档未收录的第三处活漂移 | ✅ 源码原文复验属实（A02 crash-recovery 机制） | 新增 RC-C5 |
| 2 | `market_service.py:188-195` indices_cache 落点 = **backend/app/data** 且 :232 import 加载/:225 现役写——**推翻 C2「app/data 全为历史残留」归因，「C1+C4 后整目录删」会删了再生** | ✅ 源码原文复验属实 | 新增 RC-C6；C2 硬前置扩为 C1+C4+C5+C6；18.7 验收 rg 扩为全 app 手拼路径模式扫描 |

其余修正：C4 代码块行号 :139-145 → :140-145；执行摘要 C 类 4→6 组；18.6 ⓪-C 重排为
「4 收敛项（2 commit）→ C2 → C3」；D8 升级为「4+1 处实证、强烈建议 lint 候选」。
子代理 unresolved 项说明：A 类垃圾时间戳/Git 状态与 B3/D2/D4/D5 未在其抽验范围——
B3 已由 R1 全仓验证补强，A 类为本轮 ls/git 实测原样引用，D 类为 round35 既定批次索引不重复设计。

#### RC-R3（2026-08-23，作者终检 · design-checklist 八项 + 四问法 + 一致性校对）

**四问法抽查（核心结论逐条）**：

| 结论 | 事实/推断 | 支撑 | 反例检查 | 分级 |
|---|---|---|---|---|
| C4 落点 backend/data | 事实 | etf_scanner.py:145 原文 + dirname 推导，R1/R2 两轮独立一致 | 无（docstring 反证其矛盾已被引用） | 合理 |
| B1 三端点活 | 事实 | UnifiedAnalysis.vue:460 / verify_e2e:2446+:980 | :699 Z17 保留注释与 TODO 并存自证矛盾 | 合理 |
| D1 store 死 action | 事实 | R2 全 src grep 含同名本地函数干扰项排除 | PortfolioManager 同名项已排除 | 合理 |
| C6 容器内写镜像层 | 强推断 | __file__ 容器布局自证（etf_scanner 旧注释「/app/app/data 必丢」同款布局） | 无 | 合理（标注推断依据） |

**R3 新增发现（总闸验收口径实测暴露）**：

| # | 发现 | 处置 |
|---|---|---|
| 1 | etf_scanner.py:826-829 `_TRACKED_INDEX_CACHE`（etf_index_mapping.json）= backend/data **第三家写入方**，读写皆活跃，round34 曾因其脏值出真实 bug（test_fund_fetcher_guard.py:4） | C4 扩容吸收（同文件姊妹项，一个 commit 收口） |
| 2 | main.py:441-446 `_probe_ok_cache_mtime` 的 dirname×3 fallback 与 C6 同源 | C6 补关联点，同 commit 收口 |
| 3 | warmup_profiler.py:50 dirname×3+logs = backend/logs——**合法落点非漂移**（AGENTS.md 认可的日志域） | 18.7 总闸白名单收录 |
| 4 | 初版 18.7 总闸单一正则抓不到 C1 双层 dirname 风格 | 改双模式并集 + 白名单核对法，R3 实测 11 行命中逐行定性 |

**一致性校对修复**：C1「同源先例」原引 P1-11 为成功样例与 C4 矛盾 → 改引 _kline/R86 为模板；
C5 危害段「容器内被 /app/data 优先级掩盖」系张冠李戴（那是 etf_scanner 分支）→ 改为
「容器内碰巧正确（上三级恰为 /app），宿主机才错」的分环境表述；C6 补容器内镜像层危害
（四项中唯一两环境皆错）；「C 类共同收益」块从 C4 后移至 18.4 尾部；18.5 D 类表格断裂修复
（D3 细化移至表后）；执行摘要/盘点数同步（现役漂移 4→5 处）。

**终检判定**：✅ 达实施标准——全部结论有 file:line 实证且经两轮独立验证；4 个重大修改项
（C1/C4/C6 实施细化、D3 三选项裁决）已给到可执行粒度；验收口径含负向断言与反假完成自查；
实施顺序依赖闭环（C2/C3 硬前置收敛项）。遗留开口均为显式登记的「实施时定夺」项
（B3 二选一、D3 三选项、C6 迁移与否），不阻塞开工。
