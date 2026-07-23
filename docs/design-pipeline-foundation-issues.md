# 智能组合设计 & 策略检查 — 问题诊断与优化方案

> 版本: v2.0 | 状态: Review Complete | 日期: 2026-07-23
> 本文档独立于存量文档 `design-optimization-plan.md`（覆盖管线链路问题），
> 聚焦数据管道基础缺陷 + 组合设计质量问题的深度诊断。

---

## 关于当前架构的基本判断

**核心结论**: 架构设计正确——全市场扫描 → 数据管道 + 因子模型 → 引擎分配 → 风控。

```
etf_scanner.full_pipeline()          → Sina API 扫描 ~1500 只 ETF
    ↓
pool_manager.refresh()               → 分类、因子计算、5 层分配、截断
    ↓
strategy_design.generate_enhanced()  → 编排器
    ↓
allocation_engine.allocate()         → 按因子分排序选择 + 权重分配
    ↓
risk_controls.apply_risk_controls()  → 风控校验
    ↓
返回三套方案
```

**验证**: 实际产出的 ETF 代码（563880, 589960, 520940 等）不在 `_DEFAULT_CANDIDATES` 的 18 只硬编码中，说明 pool 有真实数据、没走 fallback。

**但管道中存在多个根本性缺陷，导致结果是错的。**

---

## 1. 问题列表

### 🔴 P0-1: 因子评分键名不匹配 → 所有 factor_score = 0.0

**位置**: `allocation_engine.py:83-87` 和 `factor_registry.py:671-686`

```python
# allocation_engine.py 中 _select_and_weight 的评分公式：
composite = (
    factor_scores.get("technical", 0.0) * 0.3   # 找不到键 → 0.0
    + factor_scores.get("momentum", 0.0) * 0.3   # 找不到键 → 0.0
    + factor_scores.get("valuation", 0.0) * 0.2  # 找不到键 → 0.0
    + factor_scores.get("sentiment", 0.0) * 0.2  # 找不到键 → 0.0
)
```

但 `factor_registry.compute()` 返回的键名是点分式：
```
technical.ma.sma_5, technical.rsi.rsi_14, technical.macd.macd,
sentiment.panic_greed_diff, china.policy.five_year_plan, ...
```

**不存在顶层键** `"technical"`、`"momentum"`、`"valuation"`、`"sentiment"` → 所有 `get()` 返回 0.0。

**影响链路**:
```
factor_score = 0.0
  → _select_and_weight 按 0.0 排序 → 退化为输入顺序
  → 三个 risk_profile 循环中 core/satellite/defense 候选列表不变
  → 三套方案选了同一批 ETF
  → 只有 layer_budget 不同（核心/卫星比例），标的完全相同
```

数据库验证（design_id=120）：所有 `factor_score` 确实为 0.0，`factor_breakdown` 中除 `china.policy.five_year_plan=0.3` 和 `technical.rsi.rsi_14=50.0` 外全 0。

---

### 🔴 P0-2: tracked_index 字段在数据管道中被丢弃

**位置**: `etf_scanner.py` 第 114 行和 137-147 行

EM API 请求了包含 `f168`（跟踪指数代码）的字段列表，但在解析返回时**没有将 f168 保存到输出 dict 中**：

```python
# 请求了 f168（第 114 行）
fields = "f12,f14,f2,f3,f62,f184,f66,f45,f168,f20,f21,f115,f116"

# 但丢弃了它（第 137-147 行）
return [{
    "symbol": item["f12"],
    "name": item.get("f14", ""),
    "amount": item.get("f62", 0) or 0,
    "fund_scale": item.get("f184", 0) or 0,
    "price": item.get("f2", 0) or 0,
    "change_pct": item.get("f3", 0) or 0,
    "turnover": item.get("f45", 0) or 0,
    "pe": item.get("f66", 0) or 0,
    "pb": item.get("f115", 0) or 0,
    # ← 缺少 tracked_index
}]
```

同样，`china_market.fetch_etf_list()`（Sina 数据源）也不返回 tracked_index。

**影响**: 整个管道不知道"哪些 ETF 追踪同一个指数"，无法做同指数去重。

**后果验证**（design_id=120）:
```
核心层 4 只全部追踪中证 A500:
  563880  A500ETF汇添富    12%
  563860  中证A500ETF海富通  12%
  563800  A500ETF广发      12%
  563660  A500ETF银河      12%
  合计 48% → 同一个指数买了 4 遍
```

---

### 🔴 P0-3: 市场快照缓存从未被写入

**位置**: `pool_manager.py` 第 104-106 行和第 354-356 行

```python
# __init__ 中声明（第 104-106 行）
self._sector_momentum_cache: list[dict] | None = None
self._sector_momentum_cache_ts: float = 0
self._index_realtime_cache: list[dict] | None = None

# getter 只读取不写入（第 354-356 行）
def get_index_realtime(self) -> list[dict]:
    return self._index_realtime_cache or []   # 永远是 []
```

全文搜索确认：这两个变量**只有声明和读取，没有任何赋值操作**。

**影响**: `_build_market_context()` 返回的 `index_realtime`、`sector_momentum` 始终为空数组，`market_snapshot_json` 中确实为空：
```json
{"index_realtime": [], "sector_momentum": [], "benchmark_stocks": []}
```

→ LLM 报告 prompt 没有实时指数和板块数据，AI 只能写空洞的分析。

---

### 🔴 P0-4: _compute_composite 的 factor_sum 扭曲（与 P0-1 同根因）

**位置**: `pool_manager.py` 第 260-263 行

```python
def _compute_composite(self, item, layer, regime="neutral"):
    factor_scores = item.get("factor_scores", {})
    factor_sum = sum(factor_scores.values()) if factor_scores else 0
```

这是与 P0-1 相同的键名不匹配问题的第二个影响面。`sum(factor_scores.values())` 对所有因子分求和，但多数因子分为 0.0（因缺少 K-line 数据），有效值主要来自 `china.policy.five_year_plan=0.3` 和 `technical.rsi.rsi_14=50.0`。RSI 中性值 50 被当成正分累加，扭曲了层内排序。**修复 P0-1 后需同步调整此处的求和策略**（改为均值或加权和，避免 RSI 中性值主导排序）。

---

### 🔴 P0-5: `current_regime` 始终为 "neutral"

**位置**: `pool_manager.py` 第 102 行

```python
def __init__(self):
    ...
    self.current_regime: str = "neutral"   # 初始化
```

`current_regime` 在 `__init__` 中初始化为 `"neutral"`，但整个类中**没有代码更新这个值**。`_LAYER_WEIGHTS` 表的 key 使用 `"bull"`、`"bear"`、`"correction"`、`"neutral"`（而非 `"bull_strong"`、`"range_bound"`），而 `get_market_regime()` 返回的是 `"range_bound"`——两者不匹配。

**影响**: `_compute_composite()` 中 `w = layer_weights.get(regime, layer_weights.get("neutral", ...))` 因 regime 不匹配（传入了 `"range_bound"` 而非 `"neutral"`）走了 fallback。当前因为 `regime` 传的一直是 `self.current_regime = "neutral"` 没变过，所以每次取的权重不变。

**修复**: 在 `update_market_regime()` 中同步更新 `self.current_regime`，且映射表 key 需与 `get_market_regime()` 返回值一致（统一用 `"bull_strong"`、`"range_bound"` 等，而非 `"bull"`、`"neutral"`）。

---

### 🟠 P0-6: `_ensure_mandatory` 硬编码代码到层的映射

**位置**: `pool_manager.py` 第 246-255 行

```python
if code in ("510300", "560600"):
    target = LAYER_CORE
elif code in ("518880",):
    target = LAYER_DEFENSE
elif code == "511090":
    target = LAYER_DEFENSE
```

这是一个最小化的硬编码保底——只针对 4 个强制保留的代码。如果新增强制代码需要手动维护。建议改为从 `etf_scanner.DEFENSE_REQUIRED` 和 `CORE_REQUIRED` 动态推断。

---

### 🟠 P1-1: 行业集中度风控使用了错误字段

**位置**: `risk_controls.py` 第 169-173 行

```python
# 3. 行业集中度 (HHI)
sector_weights: dict[str, float] = {}
for a in allocations:
    sec = a.get("layer", "其他")  # ← 用的"层名"core/satellite/defense，不是真实行业
```

层名只有 3 个值（core/satellite/defense），行业集中度 HHI 永远算不出来——这是个**逻辑无效的检查**。

---

### 🟠 P1-2: 三方案 ETF 标的完全相同

**数据验证**: 三个方案的 ETF 列表完全一致，仅卫星层权重（8%/12%/18%）和现金比例（30%/20%/10%）不同。

**根因链**:
```
factor_score=0 → 引擎无法排序 → 所有标的评分相同
→ 每次 _select_and_weight 返回前 N 个相同
→ 三次循环用同一份候选池 → 三方案一致
```

---

### 🟠 P1-3: 防御层缺乏真正的防御资产

**数据验证**:
```
防御层(4只, 5%):
  520940  港股通恒生ETF华安     1%   → 港股权益
  520930  恒生生物科技ETF国泰   1%   → 港股权益
  520920  恒生科技ETF天弘       1%   → 港股权益
  520840  港股通恒生科技ETF华安  1%   → 港股权益
```

4 只全部是港股权益，没有黄金、国债等与 A 股低相关的防御资产。且各 1% 的配置即使涨 10% 对组合贡献只有 0.1%，属"羽毛级配置"。

---

### 🟠 P1-4: 策略检查报告模板化

**数据验证**（`strategy_check_records.id=34`）:

| 字段 | 内容 | 问题 |
|---|---|---|
| `factor_summary` | "当前因子数据暂不可用，具体因子详情未提供" | 全部 10 只持仓相同 |
| `tech_signal` | "买入信号指示器" | 全部 10 只持仓相同 |
| 建议数 | 3 条（增红利、减黄金、持A500） | 全部 medium confidence |
| 风险提示 | 2 条 concentration | 未覆盖 volatility、correlation 等 |

**根因**: LLM prompt 要求基于因子数据 + 技术信号分析，但这些数据本身是空/默认值，LLM 只能写模板化判断。

---

### 🟡 P2-1: design_text 为 NULL

所有 `portfolio_designs` 记录的 `design_text` 列均为 NULL。LLM 全文报告未持久化到数据库。

---

### 🟡 P2-2: 中文字段存储编码问题

数据库中 `strategies_json` 等 TEXT 字段以 latin-1 编码存储 UTF-8 中文，读取时需 `bytes.decode('latin-1')` 再 `encode('utf-8')` 才能还原。

---

## 2. 问题关系图

```
数据源层                         数据管道层                        引擎层                         输出层
─────────                       ──────────                      ──────                        ──────
Sina/EM API                      池管理器                          分配引擎                       方案
│                                 │                                 │                             │
├─ f168 丢弃 ──P0-2──→          ├─ 无 tracked_index              ├─ 同指数重复 ──P1-2──→       ├─ 4只A500
│                                 │    → 无法去重                   │    → 3方案一致               │   48%同指数
├─ 字段正常                      ├─ factor_scores 点分键          ├─ _select_and_weight         ├─ 三方案相同
│                                 │    (键名不匹配)                  │   评分用顶层键               │
│                                 │         ↓                       │         ↓                   │
│                                 │  P0-1: 永远 0.0 ←────────────── 永远 0.0                     │
│                                 │                                 │                             │
├─ 指数实时数据                  ├─ _index_realtime_cache          ├─ _build_market_context()     ├─ 市场快照空
│                                 │    P0-3: 从未写入 ──────────→    → 空数组                      │
│                                 │                                 │                             │
│                                 ├─ _compute_composite            ├─ 排序用 sum(值)              │
│                                 │    P0-4: RSI=50 扭曲           │    + 0.3 政策因子             │
│                                 │                                 │                             │
Layer 分配                       ETFClassifier                    risk_controls                  策略检查
├─ defense 层                    ├─ industry 字段正常             ├─ P1-1: 行业集中度用 layer   ├─ factor_summary 为空
│   港股被分入                    │                                 │    → 无效检查                │    → 模板化输出
├─ 黄金/国债未强制保底            └─ 概念字段可用                  └─ defense 小仓位未拦截       └─ tech_signal 都一样
```

---

## 3. 修复方案

### Phase A: 数据基础修复

解决数据链路的漏接问题——数据已经取了但没传下去。

| 修复项 | 对应问题 | 文件 | 改动说明 | 预估 |
|---|---|---|---|---|
| A1. 追加 tracked_index | P0-2 | `etf_scanner.py:137-147` | `_fetch_em_etf_list()` 返回 dict 增加 `"tracked_index": item.get("f168", "")`。Sina 源没有 tracked_index，管道会在 EM 回退路径中获得该字段 | ~5行 |
| A2. 透传 tracked_index | P0-2 | `pool_manager.py:133-139` | `flat.append()` 增加 `"tracked_index": item.get("tracked_index", "")` | ~2行 |
| A3. 写入市场快照缓存 | P0-3 | `pool_manager.py:new` | 新增 `_refresh_market_snapshot()` 方法，调用 `get_global_indices()` 写入 `_index_realtime_cache`、调用 `compute_sector_momentum()` 写入 `_sector_momentum_cache`。在 `refresh()` 末尾调用 | ~50行 |
| A4. 防御层强制保底 | P1-3 | `pool_manager.py` | 不新增代码。复用现有 `_ensure_mandatory()`（第 202-203 行）和 `MANDATORY_CODES`（第 30 行）。518880 和 511090 已在其中 | 0行 |

**A 阶段依赖**: 无。可以独立先行验证。

---

### Phase B: 引擎修复

解决评分和风控的逻辑错误。

| 修复项 | 对应问题 | 文件 | 改动说明 | 预估 |
|---|---|---|---|---|
| B1. 因子分键名聚合 | P0-1, P0-4 | `factor_registry.py:new` | 新增 `_aggregate_factor_scores()`：将 `technical.*`、`sentiment.*` 等点分键均值计算为顶层键。在 `pool_manager.refresh()` 步骤 3b 调用 | ~30行 |
| B2. 候选池去重 | P1-2 | `pool_manager.py:new` | 新增 `_deduplicate_by_index()`：同层同 `tracked_index` 的 ETF 只保留 `fund_scale` 最大的。**依赖 A1/A2 完成** | ~40行 |
| B3. 分配引擎去重保护 | P1-2 | `allocation_engine.py` | `_select_and_weight` 增加 `selected_indices` 参数，跳过已选指数。可与 B2 并行 | ~15行 |
| B4. 行业集中度修复 | P1-1 | `risk_controls.py:172` | 一行改动：`sec = a.get("layer", "其他")` 改为 `sec = a.get("industry") or a.get("layer", "其他")` | ~1行 |
| B5. 防御层最小权重门槛 | P1-3 | `risk_controls.py:new` | 新增 `_consolidate_minnows()`：合并 defense 层中权重 < 2% 的小仓位到最大的防御标的中 | ~30行 |

**B 阶段依赖**: B2 依赖 A1/A2。B1 可独立先行。

---

### Phase C: 方案质量提升

在前两个阶段修复的基础上，进一步优化方案差异化。

| 修复项 | 对应问题 | 文件 | 改动说明 | 预估 |
|---|---|---|---|---|
| C1. 三方案差异化 | P1-2 | `allocation_engine.py` | `allocate()` 中按 `profile_key` 过滤卫星层候选列表。**依赖 B1（因子分正常后才能按行业区分）** | ~30行 |
| C2. regime 映射修复 | P0-5 | `pool_manager.py` | `_LAYER_WEIGHTS` 表 key 与 `get_market_regime()` 返回值对齐 | ~10行 |
| C3. design_text 修复 | P2-1 | `task_manager.py` / `design_report.py` | 诊断 WS write-back：检查 `compose_and_push_report` 中 `design_id` 是否传入、DB commit 是否成功 | 排查 |

---

## 4. 实施顺序与依赖

```
Phase A (数据漏接)
  A1 tracked_index 追加 ── A2 透传到 pool ──┐
  A3 市场快照写入 ──────────────────────────┤
  A4 防御层保底 (0行改动) ──────────────────┤
                                            ↓
Phase B (引擎修复)                      B 可部分并行
  B1 因子分键名聚合 ── 可独立先行 ────────→ 完成后 factor_score != 0
  B2 候选池去重     ── 依赖 A1/A2 完成后
  B3 分配引擎去重保护 ── 可与 B2 并行
  B4 行业集中度     ── 1 行改动，随时可做
  B5 防御权重门槛   ── 独立
                                            ↓
Phase C (质量提升)                      需 B1 完成后
  C1 三方案差异化 ── 依赖 B1
  C2 regime 映射修复 ── 独立
  C3 design_text 修复 ── 独立
```

**建议实施顺序**: A1 → A2 → A3 → B1 → B2/B3 → B4/B5 → C1 → C2 → C3。每步完成后验证。

---

## 5. 验证标准

实施后逐项验证，全部通过视为修复完成：

| # | 验证项 | 方法 | 对应修复 |
|---|---|---|---|
| V1 | `tracked_index` 出现在 ETF 数据中 | 启动后端，触发扫描，检查返回 dict 含 `tracked_index` | A1, A2 |
| V2 | 核心层无同指数重复 | 触发设计方案，core 中无同 `tracked_index` 的多只 ETF | B2 |
| V3 | `factor_score` 非零 | 方案中至少一只 ETF 的 `factor_score != 0.0` | B1 |
| V4 | 市场快照非空 | `market_context.index_realtime` 或 `sector_momentum` 有数据 | A3 |
| V5 | 防御层含黄金或国债 | defense 列表包含 518880 或 511090 | A4 |
| V6 | 防御层每只权重 >= 2% | defense 中无低于 2% 的仓位 | B5 |
| V7 | 三方案至少 40% 标的不同 | 三组 ETF 代码交集比例 < 60% | C1 |
| V8 | 行业集中度用真实行业 | `risk_controls` 中 `sec` 来自 `industry` 而非 `layer` | B4 |
| V9 | `design_text` 非 NULL | `portfolio_designs` 最新记录的 `design_text` 列 | C3 |
| V10 | verify_e2e.py 全 PASS | 跑 `python scripts/verify_e2e.py` | 全部 |

---

## 6. 与存量文档的关系

| 本文档（新） | `design-optimization-plan.md`（存量） |
|---|---|
| P0-1: 因子评分键名不匹配 | P0: regime 检测传错参数 |
| P0-2: tracked_index 丢弃 | P0.5: akshare 超时无 fallback |
| P0-3: 缓存从未写入 | P1: 实时指数未传 LLM |
| P0-4: `_compute_composite` 求和扭曲 | P2: 板块动量未传 LLM |
| P0-5: `current_regime` 未更新 | P3: 非交易时段无数据 |
| P0-6: `_ensure_mandatory` 硬编码映射 | P4-a/b/c/d: filter_etfs 列名乱码+静默降级+前端感知 |
| P1-1: 行业集中度用 layer 名 | P5-a/b: LLM prompt 规则强化+一致性校验日志 |
| P1-2: 三方案一致（根因 chain） | — |
| P1-3: 防御层无黄金/国债 | — |
| P1-4: 策略检查模板化 | — |
| P2-1: design_text 为 NULL | — |
| P2-2: DB 编码问题 | — |

**两者互补不冲突**。建议实施时先处理本文档的 P0 级问题（B1+A1~A3），再处理存量文档的 P4 级问题（列名乱码）。因为 B1 修复后需要正常的数据源来验证效果。

---

> **下一步**: 本文档达到实施标准后，从 Phase A 开始逐步实施。每完成一项验证对应 V# 条目。
