# 5项改进方案 — 审阅驱动优化

> 实施状态: ⚠️ 4/5 已完成 | 最后修订: 2026-07-24
> - #2 `filter_extreme_drawdown` — ✅ 已实施
> - #3 `check_defense_effectiveness` — ✅ 已实施
> - #4 `remove_stale_candidates` — ✅ 已实施
> - #5 `_layer_phrase` 模板多样化 — ✅ 已实施
> - #1 统一市态判定 — ❌ 待实施（映射为 master-plan Phase 1.1.0）
> 
> 基于 2026-07-20 产出质量审阅报告，5 项可落地改进。

---

## 1. 统一市场状态判定

### 现状
- **设计管线**：`pool_manager.get_market_regime()` — 综合因子+趋势+新闻
- **策略检查**：`_detect_regime()` → `compute_etf_trends()` + `fetch_index_realtime()` — 偏技术面
- 两者产出不一致：一个判 `correction`，一个判 `range_bound`

### 方案
策略检查复用 pool_manager 的市场状态，删除 `_detect_regime()` 内部自采逻辑。

```
// strategy_check() 当前
trends, index_realtime, regime = await _detect_regime(symbols)

// 改为
from ..services.pool_manager import pool_manager
regime = pool_manager.get_market_regime() or "range_bound"
trends = {}  // 如策略检查仍需趋势数据，从 factor_matrix 读取
```

### 影响
- `strategy_check()` 减少 ~15 行
- 两条管线 regime 一致，E2E 测试不冲突
- 省约 15-20s 数据采集时间（策略检查不再拉 index_realtime）

---

## 2. 自动排除极端下跌标的

### 现状
- 策略引擎不检查 ETF 跌幅，半导体 ETF 月跌 56.9% 仍以 ~6% 权重进入进攻型方案
- 核心层应当设跌幅阈值，避免"越跌越买"的风险

### 方案
在 `engine/risk_controls.py` 新增 `filter_extreme_drawdown()`，在 `apply_risk_controls()` 入口处过滤。

```python
def filter_extreme_drawdown(strategies, factor_matrix, threshold=-0.40):
    """月跌幅超过 threshold 的标的从方案中剔除。"""
    for strategy in strategies:
        etfs = strategy.get("etfs", [])
        filtered = []
        for etf in etfs:
            if etf.get("symbol") == "CASH":
                filtered.append(etf)
                continue
            fs = (factor_matrix or {}).get(etf.get("symbol", ""), {})
            ret_1m = fs.get("return_1m") or fs.get("trend.return_1m")
            if ret_1m is not None and ret_1m < threshold:
                logger.info("[risk] excluded %s (1m return %.1f%%)", etf["symbol"], ret_1m * 100)
                continue  # 剔除
            filtered.append(etf)
        strategy["etfs"] = filtered
    return strategies
```

### 影响
- 核心层不会出现月跌 >40% 的标
- 剔除的权重等比例分给同层其他标的或补充现金

---

## 3. 防御资产有效性检查

### 现状
- 黄金 ETF 在某一回测区间跌 17.2% 仍以 5-7% 权重配置在防御层
- 防御资产的"防御功能"失效时不应占据防御预算

### 方案
在 `engine/risk_controls.py` 新增 `check_defense_effectiveness()`：

```python
def check_defense_effectiveness(strategies, factor_matrix, threshold=-0.10):
    """检查防御层标的的有效性。若近3月跌幅超 threshold，降低其权重或移出防御层。"""
    for strategy in strategies:
        etfs = strategy.get("etfs", [])
        for etf in etfs:
            if etf.get("layer") != "defense" or etf.get("symbol") == "CASH":
                continue
            fs = (factor_matrix or {}).get(etf.get("symbol", ""), {})
            ret_3m = fs.get("return_3m") or fs.get("trend.return_3m")
            if ret_3m is not None and ret_3m < threshold:
                # 防御功能失效，权重减半并加注说明
                old_w = etf.get("weight", 0)
                etf["weight"] = round(old_w * 0.5, 4)
                etf["selection_rationale"] = f"{etf.get('selection_rationale', '')}【注意：近3月跌{ret_3m*100:.1f}%，防御有效性降低，权重减半】"
    return strategies
```

### 影响
- 黄金/国债等防御资产在周期内表现不佳时自动降权
- 释放的权重补充到现金或核心层

---

## 4. 候选池 Freshness 检查

### 现状
- 旅游ETF、军工ETF等缺失当日行情数据，仍出现在方案中
- 入选理由中"今日涨跌" "近3月涨跌" 全部为空

### 方案
在 `engine/risk_controls.py` 新增 `remove_stale_candidates()`，或在编排器 `generate_enhanced_design()` 中过滤：

```python
def remove_stale_candidates(strategies, factor_matrix):
    """剔除缺失行情数据的标的（price/return 全为空）。"""
    for strategy in strategies:
        etfs = strategy.get("etfs", [])
        filtered = []
        for etf in etfs:
            if etf.get("symbol") == "CASH":
                filtered.append(etf)
                continue
            fs = (factor_matrix or {}).get(etf.get("symbol", ""), {})
            has_price = fs.get("price") is not None
            has_return = fs.get("return_1m") is not None
            if not has_price and not has_return:
                continue  # 无任何行情数据 → 剔除
            filtered.append(etf)
        strategy["etfs"] = filtered
    return strategies
```

### 影响
- 方案中所有标的都有行情数据，入选理由完整
- 剔除标的权重等比例分配到同层剩余标的

---

## 5. 入选理由模板多样化

### 现状
- 每条理由按固定模板拼接："今日跌X%；资产介绍；近3月跌Y%；近1月跌Z%；均线偏离；市场状态；层角色"
- 同一模板连续出现 20+ 次，AI 模板感强

### 方案
在 `engine/rationale.py` 的 `build_rationale()` 中引入层角色短语的随机选择：

```python
import random

_CORE_PHRASES = [
    lambda n: f"在方案中作为核心底仓配置，跟踪{n}",
    lambda n: f"核心层选择——{n}，兼具流动性与分散性",
    lambda n: f"作为核心宽基{n}，提供市场β收益",
]

_SATELLITE_PHRASES = [
    lambda n: f"卫星层配置{n}，增强组合弹性",
    lambda n: f"行业{n}作为弹性卫星，博取超额收益",
    lambda n: f"{n}卫星仓位，参与赛道轮动机会",
]

_DEFENSE_PHRASES = [
    lambda n: f"防御层{n}提供下行保护",
    lambda n: f"{n}与权益低相关，分散尾部风险",
    lambda n: f"避险资产{n}，降低组合波动",
]

def _layer_phrase(layer, asset_name):
    pool = {"core": _CORE_PHRASES, "satellite": _SATELLITE_PHRASES, "defense": _DEFENSE_PHRASES}
    phrasers = pool.get(layer, _CORE_PHRASES)
    return random.choice(phrasers)(asset_name)
```

**注意**：用 `random.seed(hash(symbol))` 保证同一标的同一方案调用结果稳定。

### 影响
- 同一页面上 8-12 条理由不会出现完全相同的句式
- 内容不变仅句式变换，不影响信息量

---

## 实施顺序

| 改进 | 文件 | 行数变更 | 优先级 | 测试方式 |
|------|------|---------|--------|---------|
| 1. 统一 regime | `portfolio_service.py` + `strategy_check_worker.py` | ~15行删 | P0 | `verify_e2e.py` 策略检查测试 |
| 2. 极端下跌排除 | `engine/risk_controls.py` | +25行 | P0 | 引擎单测 + 设计结果验证 |
| 3. 防御有效性 | `engine/risk_controls.py` | +25行 | P1 | 引擎单测 |
| 4. Freshness检查 | `engine/risk_controls.py` + `strategy_design.py` | +20行 | P1 | 设计结果验证 |
| 5. 理由多样化 | `engine/rationale.py` | +25行 | P2 | 视觉审查 |

### 注意事项
- P0/P1 改动不需要改 API 契约（输出字段不变）
- P2 改动仅影响入选理由的句式，不改变信息内容
- 实施后跑 `verify_e2e.py` 确认 31/31 PASS
