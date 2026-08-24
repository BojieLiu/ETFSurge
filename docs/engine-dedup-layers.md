# 引擎去重六层契约（round35 B3-S3 契约文档化）

> 来源：docs/round35-architecture-review.md §5-S3 / §6.3。
> 定位：**只写清组合语义，不合并代码**——降级盲互补是有意冗余（§7 明确不做合并）：
> 盘后 K 线相关系数不可用（r=None）时，文本族层仍能兜底控制主题冗余；
> 强行合并会把最需要鲁棒的路径变脆。
> 排查「为什么 A/B 没被合并」时按本文逐层对号；改动任一层前必读相邻层的互补关系。

## 分层总览（按管线执行顺序）

| # | 层 | 位置 | 作用域 | 判定口径 | 动作 | 豁免 |
|---|---|---|---|---|---|---|
| 1 | 池层同指数去重 | `pool_balancing.deduplicate_by_index` | 候选池构建（进引擎**前**） | `tracked_index` 或剥公司名后的名称概念（taxonomy.extract_index_concept）相同 | 同指数仅留一只 | — |
| 2 | segment 板块去重 | `allocation_engine._select_and_weight` 内 concept-dedup | 单方案单层打分后、取 top 前 | `normalize_segment(tracked_index or 提取概念)` 相同（科创50/100/新能源→科创；中证500价值→中证500） | 每板块仅留 composite 最高者 | — |
| 3 | 同指数双持有硬约束 | `allocation_engine._dedup_same_index` | 分配完成后（层内） | 与层 1 同源归一（再剥「中证」前缀） | 剔除低分者，权重按同层比例回补 | 强制锚全组豁免（510300+159338 双锚并存，报告提示） |
| 4 | 关联度上限 | `allocation_engine.enforce_max_correlation` | 全策略分配后（编排层调用） | 两两 r ≥ cap(0.9) 且合计 > 25% | 削低因子分一方至「合计=阈值」（下限 MIN_WEIGHT），削出权重按其余标比例回补；risk_metrics.correlation_warnings 标注 | 双方强制锚仅标注不削；单锚永作 keep 方 |
| 5 | 近替代品族合并 | `apply_near_substitute_warnings` → `_merge_substitute_family`（族表 taxonomy.SUBSTITUTE_FAMILIES） | 全策略分配后，与层 4 正交 | 文本族匹配（半导体/医药生物/券商/大盘宽基/科创成长/黄金/国债）或归一化概念 ∈ 五前缀族 | **无条件合并留一**（保留流动性更优/更宽基者），被并方权重并入保留方；r 缺失照常执行（降级盲主防线） | 无锚豁免之外：R105 后强制锚组整组豁免 |
| 6 | 高相关软提示 | `wide_basis_high_corr_warnings` | 核心层宽基配对（r>0.95） | 双方均命中大盘宽基族 | 仅 correlation_warnings 提示，不剔除不削权 | r=None 跳过 |

另有组合级视角补充：`portfolio_concentration_check`（平均 pairwise r > 0.8 且标的 ≥3 → concentration 告警，不动持仓）。

## 为什么是六层而不是一层

- **层 1/2/3 是确定性文本层**：零外部依赖，任何时段可执行；粒度从池构建 → 层内选择 → 层后硬约束逐级收窄。
- **层 4 是价格证据层**：依赖真实 K 线相关矩阵；盘后 r=None 时整体跳过（诚实跳过，不误杀）。
- **层 5 是层 4 的降级盲互补**：r 不可用时靠命名语义仍然约束「同一主题买三只」类冗余；r 可用时与层 4 叠加形成双保险（先价格后语义，顺序见 strategy_design 编排）。
- **层 6 是披露层**：只增透明度不改分配，服务「分散有限」的用户知情权。

## 已知边界（历史事故即测试）

- 中证1000 含「中证100」子串 → 大盘族排除词优先（test_taxonomy_edge_cases）。
- 裸 A500/A50 必须命中大盘族（round19 P1-②）。
- 科创芯片 industry=半导体 → 成长宽基判否（行业字段优先于关键词）。
- 中证500 计入大盘族数量上限 ≤4（R101 实测相关性推翻旧注释假设）。
- 医药族多标的涌入时会经层 5 合并收缩卫星数——FM2 重做时须关注该级联（见 memory round35-B3B4FM2 条目）。

## 改动纪律

1. 任一层的判定口径变化 → 先跑 `tests/test_etf_classification_snapshot.py`（28 只冻结基线）+ `tests/test_taxonomy_edge_cases.py`；
2. 涉及输出数值变化 → `python scripts/engine_golden_replay.py` diff 为空才可提交（有意变更须 --update 并在 commit message 说明动机）;
3. 新增第七层前先回答：它与层 4/5 的降级盲互补关系是什么？答不清就不加（§7 防过度工程）。
