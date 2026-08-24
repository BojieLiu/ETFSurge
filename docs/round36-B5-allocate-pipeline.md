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
