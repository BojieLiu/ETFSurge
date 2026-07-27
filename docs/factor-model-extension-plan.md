# ETF Surge 因子模型扩展方案

> 版本: v5.0 | 日期: 2026-07-27 | 状态: **已实施回顾**
>
> ✅ **本文档已根据当前代码重写（2026-07-27 全量审计）**：
> - 反映 33 因子全 LIVE 的当前架构（而非旧版 12 因子）
> - 反映 engine/ 纯函数包架构（而非旧的 strategy_design.py）
> - IC 追踪器（Phase 7.1.1）已实施完毕，仅 A5(verify_e2e) 未完成
> - YAML 定义层（167 因子）方向已转为 "IC 验证后决定取舍"

---

## 一、现状全景

### 1.1 因子模型四层架构

ETF Surge 的因子模型经过 Phase 2.2→2.5 的实施，已形成完整四层架构：

| 层级 | 文件 | 当前状态 | 
|:-----|:-----|:--------:|
| **定义层** | `factor_definitions.yaml` | 167 个因子定义，6 大类（对标 Barra/华证/申万） |
| **计算层** | `factor_registry.py` | **33 个核心因子全 LIVE**（`_CORE_FACTORS` 列表，均含真实 compute 函数） |
| **评估层** | `ic_tracker.py` | Spearman IC / ICIR 完整实现，compute() 中已集成 IC batch compute + threshold alert，API 端点 (`/factors/ic`) 已暴露，`save_ic_batch_to_db()` 已持久化 |
| **应用层** | `engine/allocation_engine.py` + `engine/rationale.py` + `engine/budgets.py` | 纯函数分配器，通过因子分排序 + cross-section z-score 标准化接入 |

### 1.2 33 核心因子全景

`factor_registry.py` 中 `_CORE_FACTORS` 列表定义了 33 个核心因子：

| 类别 | 因子数 | 因子代码 | 说明 |
|:-----|:------:|:---------|:-----|
| style.size | 2 | `ln_mcap`, `ln_float_mcap` | 对数总市值/流通市值 |
| technical.ma | 4 | `sma_5/10/20/60` | 5/10/20/60 日均线 |
| technical.rsi | 1 | `rsi_14` | 14 日 RSI |
| technical.macd | 1 | `macd` | MACD |
| technical.bollinger | 1 | `bandwidth` | 布林带宽 |
| technical.volume | 2 | `vol_ratio`, `vwap` | 量比、VWAP |
| technical.atr | 1 | `atr_14` | 14 日 ATR |
| technical.kdj | 3 | `k_value`, `d_value`, `j_value` | KDJ 三值 |
| technical.signal | 1 | `overall` | 综合信号 |
| etf.* | 10 | `price`, `premium_discount`, `change_pct`, `return_1m`/`return_3m`, `tracking_error`, `shares_change`, `amount_stability`, `industry_diversification`, `institutional_holdings_change` | ETF 专有因子 |
| sentiment | 4 | `panic_greed_diff`, `stock_divergence`, `news_heat`, `news_direction` | 情绪因子 |
| china.policy | 3 | `five_year_plan`, `strategic_emerging`, `dual_circulation` | 政策因子 |

**合计：33 个核心因子，65 个 compute 函数（含辅助）。**

### 1.3 YAML 定义层全景

YAML 文件中定义了 167 个因子，按数据可得性和 ETF 应用价值评估：

| 大类 | 定义数 | 数据可得性 | ETF 应用价值 | 处置建议 |
|:-----|:------:|:---------:|:----------:|:--------|
| **technical**（技术） | 58 | 🟢 OHLCV 可算 | 🟡 冗余多（排列组合） | IC 验证后筛 5-8 个不共线的扩充 |
| **style**（风格） | 37 | 🟡 需要财务数据 | 🟢 价值/质量/成长是 ETF 核心 | **优先扩容，ROI 最高** |
| **china_specific**（A股特有） | 13 | 🟡 北向/两融/涨跌停 | 🟢 A股 ETF 独特 alpha | **第二阶段重点** |
| **microstructure**（微观结构） | 10 | 🟡 tick 级 | 🟢 中 — ETF 流动性筛选 | 补充 2-3 个 ETF 专用因子 |
| **theme**（主题） | 29 | 🔴 ESG/专利/网红 | 🔴 与 ETF 无关 | ❌ 跳过 |
| **alternative**（另类） | 20 | 🔴 需付费数据 | 🔴 边际收益低 | ❌ 跳过 |

> **当前状态**：IC 追踪器已激活。下一步——IC 验证驱动 YAML 因子扩容。

### 1.4 策略引擎集成方式

当前 `allocate()` 使用 `factor_scores`（来自 `factor_registry.compute()` 的 33 维因子分）通过以下步骤构建分数：

1. **因子分聚合**：各因子按类别（technical/momentum/valuation/industry/premium_discount）聚合为复合分
2. **z-score 标准化**：cross-section 标准化（混合归一化：z-score×0.7 + min-max×0.3）
3. **C2 风偏修正**：根据 market regime 调整因子权重（defensive 加价值权重，aggressive 加动量权重）
4. **LN_MCAP 排毒**：消除市值主导效应

## 二、IC 追踪器现状

### 2.1 已实现的能力

`backend/app/factors/ic_tracker.py` 中的 `ICTracker` 类提供了完整的 IC 计算能力：

| 方法 | 功能 | 状态 |
|:-----|:-----|:----:|
| `compute_ic()` | 单期 Spearman rank IC | ✅ 已实现 |
| `compute_ic_series()` | 多期 IC 序列 | ✅ 已实现 |
| `record()` | 记录因子值 | ✅ 已在 compute() 中调用 |
| `compute_icir()` | ICIR = mean(IC)/std(IC) | ✅ 已实现 |
| `compute_ic_series_fast()` | 向量化快速 IC 计算 | ✅ 已实现 |

### 2.2 已集成的调用点

在 `factor_registry.py` 的 `compute()` 方法末尾（~line 1050）：

```python
# Record for IC tracking
try:
    for sym in symbols:
        if sym in result and result[sym]:
            for code, value in result[sym].items():
                if abs(value) > 0.001:
                    ic_tracker.record(sym, code, value)
except Exception:
    pass
```

### 2.3 已实施的功能（原缺失项状态更新）

| # | 缺陷 | 原优先级 | 当前状态 |
|:-:|:-----|:-------:|:-------:|
| 1 | 无 forward_returns 数据管道 | P0 | ✅ `build_forward_returns()` 在 ic_tracker.py 已实现 |
| 2 | 无 API 端点查看 IC 统计数据 | P0 | ✅ `/factors/ic` 端点已暴露，`/factors/active` 含分类视图 |
| 3 | 无定期 IC 计算 + 聚合 | P1 | ✅ `compute_periodic_ic()` 在 factor_registry.compute() 中集成 |
| 4 | 无 IC 结果持久化 | P1 | ✅ `save_ic_batch_to_db()` + `FactorICRecord` 模型 |
| 5 | 无因子有效性排序 UI | P2 | ✅ `FactorICView.vue` + `FactorModelView.vue` 均已实现 |
| 6 | 无 IC 阈值告警 | P2 | ✅ `factor_registry.py` compute() 末尾已集成日志告警 |

### 2.4 唯一未实施的项

| # | 任务 | 影响 | 优先级 | 预估 |
|:-:|:-----|:-----|:-----:|:----:|
| A5 | verify_e2e.py 扩展 IC 端点检查 | 确保 e2e 覆盖 IC 链路 | P2 | 15min |

## 三、IC 追踪器实施回顾（2026-07-27）

### 3.1 总体策略（实施完毕）

两阶段均已实施完毕（2026-07-27 审计确认）：

```
Phase A: 建立 forward_returns 管道 + IC 计算任务 + API 端点  ✅
         （build_forward_returns, compute_periodic_ic, /factors/* 端点）
Phase B: IC 结果持久化 + 因子有效性排序 + IC 阈值告警      ✅
         （SQLite 持久化, FactorICView/FactorModelView 组件, 日志告警）
```

### 3.2 Phase A —— 核心管道（✅ 已实施）

#### A1: 建立 forward_returns 数据管道

**文件**: `backend/app/factors/ic_tracker.py` 新增 `build_forward_returns()`

**需求**：从 market_data（K 线数据）提取未来 N 日收益率作为 forward_returns。

```python
def build_forward_returns(
    market_data: dict[str, dict[str, Any]],
    symbols: list[str],
    window: int = 1,
) -> pd.Series:
    """从 market_data 的 close 价格序列构建 forward returns。
    
    Args:
        market_data: {symbol: {close: [float, ...]}}
        symbols: 标的列表
        window: forward 窗口（1=次日收益）
    
    Returns:
        Series: {symbol: forward_return}
    """
    returns = {}
    for sym in symbols:
        data = market_data.get(sym, {})
        close = data.get("close", [])
        if len(close) < window + 1:
            returns[sym] = 0.0
            continue
        cur = close[-1]
        fut = close[-1 - window]
        returns[sym] = (cur - fut) / fut if fut != 0 else 0.0
    return pd.Series(returns)
```

**验证方式**：单测验证 `build_forward_returns()` 正确计算。

#### A2: 新增 `compute_periodic_ic()` 方法

**文件**: `backend/app/factors/ic_tracker.py`

```python
def compute_periodic_ic(
    self, 
    factor_values: dict[str, dict[str, float]],
    market_data: dict[str, dict[str, Any]],
    window: int = 1,
) -> dict[str, float]:
    """Compute IC for each factor code across all symbols.
    
    Returns:
        {factor_code: ic_value}
    """
    forward_rets = build_forward_returns(market_data, list(factor_values.keys()), window)
    ic_results = {}
    
    # Group by factor code
    factor_by_code: dict[str, dict[str, float]] = {}
    for sym, factors in factor_values.items():
        for code, val in factors.items():
            if code not in factor_by_code:
                factor_by_code[code] = {}
            factor_by_code[code][sym] = val
    
    for code, values in factor_by_code.items():
        fv = pd.Series(values)
        # Align with forward returns
        common = fv.index.intersection(forward_rets.index)
        if len(common) < 3:
            ic_results[code] = 0.0
            continue
        ic_results[code] = self.compute_ic(fv[common], forward_rets[common])
    
    return ic_results
```

**验证方式**：单测验证 mock 数据下的 IC 计算。

#### A3: 在 factor_registry.py 中添加 IC 计算调用

在 `compute()` 方法末尾的 IC recording 块之后，添加 `compute_periodic_ic()` 调用并缓存结果：

```python
# Compute IC for current batch
try:
    if result and market_data:
        ic_batch = ic_tracker.compute_periodic_ic(result, market_data, window=1)
        self._last_ic_batch = ic_batch  # 暂存供 API 使用
except Exception as e:
    logger.debug("[factor] IC batch compute failed: %s", e)
```

**验证方式**：单测验证 `_last_ic_batch` 正确填充。

#### ✅ A4: 新增 API 端点 `GET /api/v1/factors/ic`（含 `/model`, `/active`）

**文件**: `backend/app/routers/factors.py`（**新建** — 当前不存在 factors 路由）

参照 `routers/market.py` 的 APIRouter 模式，新文件结构：
```python
from fastapi import APIRouter
from ..factors.factor_registry import registry
from ..factors.ic_tracker import ic_tracker

router = APIRouter(prefix="/api/v1/factors", tags=["factors"])

@router.get("/ic")
async def get_factor_ic():
    # 返回 FactorRegistry._last_ic_batch 中的数据
    ...

@router.get("/ic/{factor_code}")
async def get_factor_ic_detail(factor_code: str):
    ...
```

同时在 `backend/app/main.py` 中注册：`app.include_router(factors_router)`

路由：
```
GET /api/v1/factors/ic
  → 返回 {factors: [{code, name, ic_value, category, ic_ir}], updated_at}

GET /api/v1/factors/ic/{factor_code}
  → 返回 {code, name, ic_value, ic_history: [time_series]}
```

**API 契约**（`api-contracts/factors/ic.md`，新建，参照 `contract_template.md`）：

```json
GET /api/v1/factors/ic
Response 200:
{
  "factors": [
    {
      "code": "technical.rsi.rsi_14",
      "name": "14日RSI",
      "category": "technical",
      "ic_value": 0.035,
      "ic_ir": 0.42,
      "sample_count": 156
    }
  ],
  "updated_at": "2026-07-26T10:30:00"
}
```

**验证方式**：`verify_e2e.py` 扩展 + curl 测试。

#### 新增/修改文件清单

| 操作 | 文件 | 说明 |
|:----|:-----|:-----|
| ✅ 已建 | `api-contracts/factors/ic.md` | IC API 契约 |
| ✅ 已建 | `backend/app/routers/factors.py` | factors 路由（3 端点）|
| ✅ 已改 | `backend/app/main.py` | 已注册 factors_router |
| ✅ 已改 | `backend/app/factors/ic_tracker.py` | 含 build_forward_returns + compute_periodic_ic + save_ic_batch_to_db |
| ✅ 已改 | `backend/app/factors/factor_registry.py` | 含 _last_ic_batch + IC compute + threshold alert |
| ⏳ 待改 | `backend/scripts/verify_e2e.py` | 添加 IC 端点检查（A5） |
| ✅ 已建 | `backend/tests/test_ic_tracker.py` | IC 追踪器单测 |

#### A5: 扩展 verify_e2e.py

在 `check_factor_health.py` 或直接扩展 `verify_e2e.py`，增加 IC 端点检查：

```python
# IC 端点检查
resp = requests.get(f"{BASE}/api/v1/factors/ic")
assert resp.status_code == 200
data = resp.json()
assert "factors" in data
assert len(data["factors"]) > 0
# 每个因子应有 ic_value 字段
for f in data["factors"]:
    assert "code" in f
    assert "ic_value" in f
```

### 3.3 Phase B —— 增强与持久化（✅ 已实施）

#### B1: SQLite 持久化 IC 记录

在 `backend/app/models/` 中新增 `factor_ic.py`：

```python
class FactorICRecord(Base):
    __tablename__ = "factor_ic_records"
    id = Column(Integer, primary_key=True)
    factor_code = Column(String, nullable=False, index=True)
    ic_value = Column(Float, default=0.0)
    ic_ir = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)
    computed_at = Column(DateTime, default=datetime.utcnow)
```

#### B2: 因子有效性排序前端组件

**文件**: `frontend/src/components/FactorICView.vue`（新建）

提供：
- 因子列表按 `|ic_value|` 降序排列
- 有效（`|IC| > 0.02`）vs 无效标记
- ICIR 一致性指标
- 因子类别筛选

#### B3: IC 阈值告警

在 `factor_registry.py` 中为每个 FactorDefinition 添加 IC 检查：

```python
# After computing IC batch
for code, ic_val in ic_batch.items():
    definition = self._factors.get(code)
    if definition and abs(ic_val) < definition.ic_threshold:
        logger.warning(
            "[factor] IC below threshold for %s: ic=%.4f < threshold=%.4f",
            code, ic_val, definition.ic_threshold,
        )
```

## 四、实施计划（Phase 7.1.1）

### 4.1 实施顺序

```
Phase A (P0) — 核心管道
├── A1: build_forward_returns() 
├── A2: compute_periodic_ic() 
├── A3: factor_registry.py 集成
├── A4: API 端点 + 契约
├── A5: verify_e2e.py 扩展
└── ✅ 验证：后端单测 + verify_e2e.py

Phase B (P1-P2) — 增强
├── B1: SQLite 持久化
├── B2: 前端 IC View 组件
├── B3: IC 阈值告警
└── ✅ 验证：全链路 PASS
```

### 4.2 依赖关系

```
A1 ─→ A2 ─→ A3 ─→ A4 ─→ A5
                 ↓
                 B1 ─→ B2
                 ↓
                 B3
```

A1-A5 无外部依赖，可独立推进。B1-B3 依赖 A3（compute() 中已有 IC batch）。

### 4.3 测试策略

| 层级 | 工具 | 覆盖范围 |
|:-----|:-----|:---------|
| 后端单测 | pytest | build_forward_returns(), compute_periodic_ic(), API 端点 |
| E2E | verify_e2e.py | GET /api/v1/factors/ic 响应结构 |
| API 契约 | api-contracts/factors/ic.md | 请求/响应结构一致性 |

### 4.4 验收标准

```
[PASS] GET /api/v1/factors/ic → 200 + 含 factors 数组
[PASS] 每个因子含 code/ic_value/ic_ir/sample_count
[PASS] updated_at 为有效 ISO 时间戳
[PASS] 后端单测全部通过
[PASS] verify_e2e.py 全 PASS
```

## 五、YAML 167 因子处置建议

以下建议基于 2026-07-26 代码审计，供 Phase B 之后参考：

| 大类 | 处置 | 理由 |
|:-----|:-----|:------|
| technical | IC 验证后精选 5-8 个不共线因子 | 58 个中大量排列组合（如 sma_3/7/15 等价于现有 sma_5/10/20） |
| style | **优先扩容**，选 5-10 个高频可算的 | 价值/质量/成长是 ETF 核心 alpha 来源 |
| china_specific | 第二阶段，选 3-5 个 | 北向资金/两融余额对 A 股 ETF 有意义 |
| microstructure | 补充 2-3 个 | ETF 流动性筛选有价值 |
| theme | ❌ 跳过 | 数据不可得或与 ETF 无关 |
| alternative | ❌ 跳过 | 需付费数据，边际收益低 |

## 六、相关文件索引

| 文件 | 说明 |
|:-----|:------|
| `backend/app/factors/ic_tracker.py` | IC 追踪器（ICTracker 类 + compute_ic_series_fast） |
| `backend/app/factors/factor_registry.py` | 因子注册表（33 核心因子 + 65 compute 函数） |
| `backend/app/engine/allocation_engine.py` | 核心分配器（基于因子分排序） |
| `backend/app/engine/rationale.py` | 入选理由生成 |
| `backend/app/engine/budgets.py` | 层预算 + 预期收益调整 |
| `backend/app/routers/factors.py` | **新建** — factors API 路由 |
| `api-contracts/factors/ic.md` | **新建** — IC 追踪 API 契约 |
| `backend/tests/test_ic_tracker.py` | **新建** — IC 追踪器单测 |
| `backend/scripts/verify_e2e.py` | **修改** — 扩展 IC 检查 |

---

## 七、Review Checklist

实施前逐项确认：

- [ ] 1.1 因子四层架构描述准确，与当前代码一致
- [ ] 1.2 33 核心因子列表与 `_CORE_FACTORS` 完全对齐
- [ ] 2.3 缺失功能编号正确，P0/P1/P2 分级合理
- [ ] Phase A 实施方案代码示例与实际逻辑一致
- [ ] A4 路由前缀 `/api/v1/factors/ic` 不与现有路由冲突
- [ ] 新增文件清单完整（7 个文件）
- [ ] 依赖图（A1→A2→A3→A4→A5）正确
- [ ] 验收标准可实现
- [ ] Phase B 可作为独立后续阶段
