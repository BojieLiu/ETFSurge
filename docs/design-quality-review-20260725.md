# ETF Surge 设计质量审阅报告

> 2026-07-25 · 对应 Design #218 · 审阅范围：分配器引擎 + 因子聚合 + 数据管道

---

## 发现的问题

### 1. 因子维度被 `ln_mcap` 支配

**严重度: P0**

**症状**: 所有 ETF 的 `valuation` 聚合分都是 25.33，因为 `style.size.ln_mcap`（市值对数）成为了 `valuation` 分类下的唯一非零因子。`composite_score` 中 `valuation × 0.2 = 5.07` 贡献绝对值远超 `technical`/`momentum` 的差异（通常 <1.0）。最终得分差异只来自微弱的动量差异，导致分配器无法有效区分 ETF。

**根因**:

```python
# factor_registry.py — aggregate_factor_scores()
CATEGORY_PREFIXES = {
    "valuation": ["style."],       # ← ln_mcap (≈25) 被归入 valuation
}
```

所有 ETF 的 `ln_mcap` 都在 25 左右且毫无区分度，却在聚合中贡献了 25 分的 baseline，淹没了真正有区分度的技术/动量因子。

**修复**:

```python
# factor_registry.py — 在聚合时排除 ln_mcap/ln_float_mcap
EXCLUDE_FACTORS = {"style.size.ln_mcap", "style.size.ln_float_mcap"}
for key, val in factor_scores.items():
    if key in EXCLUDE_FACTORS:
        continue
    ...
```

---

### 2. C2 风偏差异化修正永不触发

**严重度: P0**

**症状**: 防御型方案依然重配科创板（589850 科创50 占 15.9%），进攻型方案却没有额外偏好高风险主题。三套方案的 ETF 选择高度相似。

**根因**:

```python
# allocation_engine.py — C2 correction
has_style_factors = any(k.startswith("style.") for k in factor_scores ...)
if valuation_missing and not has_style_factors:
    # 防御型：偏好安全主题，惩罚高风险主题
    # 进攻型：偏好高风险主题
```

`has_style_factors` 检查所有 `style.*` 因子。由于 `style.size.ln_mcap = 25.33` 对所有 ETF 都存在（且非零），这个条件**永远为 False**。C2 修正码从未执行过。

**修复**:

```python
# allocation_engine.py
has_meaningful_style = any(
    k.startswith("style.") and abs(v) > 0.001
    and "ln_mcap" not in k and "ln_float" not in k
    for k, v in factor_scores.items() if isinstance(v, (int, float))
)
if valuation_missing and not has_meaningful_style:
    # C2 修正码终于能跑了
```

---

### 3. 跨层去重不覆盖同板块高相关 ETF

**严重度: P1**

**症状**:
- 平衡型/进攻型同时持有 510300（沪深300ETF）和 563520（沪深300ETF永赢）——同一指数两个产品
- 所有方案同时持有 589850（科创50）、589980（科创100）、589960（科创新能源）、589720（科创创新药）——科创板内高度相关
- 防御型中科创板 ETF 合计占比 46%，完全违背防御型定位

**根因**:

跨层去重只检查 `tracked_index` 字段：

```python
# allocate() B3 cross-layer dedup
tidx = a.get("tracked_index", "") or ""
if tidx:
    selected_tracked_indices.add(tidx)
```

问题：
1. `tracked_index` 在很多 ETF 中为空（`enrich_tracked_indices` 依赖东方财富基金页爬虫，易挂）
2. 即使非空，科创50/科创100/科创新能源的 `tracked_index` 是不同的字符串
3. 名称概念提取 `_extract_index_concept` 只在层内用（B3b），不跨层

**修复**: 三层保护

| 层 | 保护机制 | 文件 |
|:--:|:---------|:-----|
| 1 | `_extract_index_concept()` 兜底空 tracked_index | allocation_engine.py |
| 2 | `_normalize_segment()` 板块级归一化（科创50/科创100/科创新能源 → "科创"） | allocation_engine.py |
| 3 | 跨层 dedup 使用归一化后的板块名称去重 | allocation_engine.py allocate() + _select_and_weight() |

---

### 4. 卫星层预算和标的数量不足

**严重度: P1**

**症状**: 防御型卫星层仅 15%/3-6 只标的，平衡型 25%/4-6 只，进攻型 30%/5-8 只。卫星层没有足够的权重和品种来实现真正的分散化。

**根因**: `STRATEGY_META` 中的 `layer_budget` 给核心层分配 50%、卫星层仅 15-30%，现金留存 10-25% 偏高。

**修复**:

| 策略 | 原 core/satellite | 新 core/satellite |
|:-----|:-----------------:|:-----------------:|
| 防御型 | 0.50 / 0.15 | 0.40 / 0.25 |
| 平衡型 | 0.50 / 0.25 | 0.40 / 0.30 |
| 进攻型 | 0.50 / 0.30 | 0.40 / 0.35 |

同时提高核心层和卫星层的 `max_count`，使 ETF 总数从 8-12 到 10-18 只。

---

### 5. 测试防护体系漏洞（已修）

| # | 漏洞 | 修复 | 验证 |
|:-:|:-----|:-----|:----:|
| 1 | AST 分析 `return -expr` 无声遗漏 | 补上 `else: computed` 分支 | ✅ `test_core_factors_no_scaffold` |
| 2 | `known_scaffolds` 单向不缩 | 更新为空集 | ✅ |
| 3 | 无运行时因子断言 | 新增 `test_each_factor_returns_nonzero_with_mock_data` | ✅ 30/30 因子 |
| 4 | 全 mock 隔离 | `pytest.mark.integration` + 集成测试 | ✅ `-m integration` |
| 5 | verify_e2e 不查因子质量 | 新增 `GET /admin/factor-health` 端点 | ✅ verify_e2e |
| 6 | 测试间互相瞒报 | `conftest.py` 改为 pool_manager._test_mode | ✅ |

---

### 6. 剩余风险

| 风险 | 描述 | 状态 |
|:----|:-----|:----:|
| index_realtime 空 | 15s 超时不够 5 组 API 链跑完 | 待修（超时 15→45s） |
| sector_momentum 空 | 仅依赖 akshare 单数据源 | 待修（加 Sina fallback） |
| LLM design 超时 | DeepSeek 调用 90s 无有效 fallback | 已加强 fallback 内容 |
| 策略检查 portfolio_type | 不传 portfolio_type 时加载场内+场外双重持仓 | 前端已传，测试脚本需补 |
| enrich_tracked_indices | 依赖东方财富基金页正则，易挂 | 概念提取兜底已加 |

---

## 修改文件清单

| 文件 | 改动 |
|:-----|:-----|
| `app/factors/factor_registry.py` | `aggregate_factor_scores()` 排除 ln_mcap/ln_float_mcap |
| `app/engine/allocation_engine.py` | C2 条件修复 + `_normalize_segment()` + 跨层去重归一化 |
| `app/engine/budgets.py` | 提高卫星层预算（15→25%, 25→30%, 30→35%） |
