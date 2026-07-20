# API 契约: FactorRegistry 修复 + 链路复用

> **实现状态: ✅ 2026-07-20 已全部完成**
> - 假数据 fallback 已删除（替换为 error marker）
> - KDJ 因子（k_value/d_value/j_value）已注册
> - 综合信号因子（signal.overall）已注册（RSI+MACD+MA bias 后处理推导）
> - industry_diversification 已基于 HHI 实现（非 scaffolding）
> - 熔断保护：>50% 符号 z-score 为 0 时抛 RuntimeError

## 1. FactorRegistry 修复

### 路由: 无（内部接口）
### 改动内容

#### 1.1 删除假数据 fallback (factor_registry.py:522-528)
换为 raise ValueError 并调用方处理。市场数据不可用时不生成合成数据。

```python
# 旧
return sym, {"close": [4.0 + i * 0.01 for i in range(60)], ...}

# 新
raise ValueError(f"fetch_history failed for {sym}: {e}")
```

**调用方处理**: `compute()` 捕获异常后对该符号设空 dict `{}`，不影响其他符号。

#### 1.2 注册 KDJ 因子
从 `indicators.py` 提取 KDJ 计算逻辑，注册为:
- `technical.kdj.k_value`: K 值
- `technical.kdj.d_value`: D 值
- `technical.kdj.j_value`: J 值

#### 1.3 注册综合信号因子
从 `signal.py` 提取 `generate_signal()` 中多指标综合信号，注册为:
- `technical.signal.overall`: 综合买卖信号 (-1 ~ +1)

#### 1.4 实现 industry_diversification
用 `ETFClassifier` 的行业分布计算 HHI（赫芬达尔指数），替代当前返回 0。

#### 1.5 熔断保护
`compute()` 结尾检查：z-score 为 0 的符号比例 > 50% 则抛异常。

### 测试
- test_factor_registry.py 现有用例全部通过
- 新增 test_fake_data_removed() 确认假数据被删除
- 新增 test_kdj_registered() 确认 KDJ 因子已注册
- 新增 test_signal_registered() 确认信号因子已注册

---

## 2. indicators.py 包装层

### 路由: 无（内部接口）
### 改动内容
`compute_all_indicators()` 从 FactorRegistry 获取已有因子分，补充独立计算的 KDJ/EMA/综合信号。

### 测试
- test_indicators_uses_factor_registry() 确认委托逻辑
- 返回格式不变（前端无感知）

---

## 3. strategy_check() 复用 FactorRegistry

### 路由: 无（strategy_check 内部）
### 改动内容
`strategy_check()` 已经通过 pool_manager.get_market_regime() 统一了 regime。还需复用 factor_matrix 替代自采 `factor_registry.compute(symbols)`。

### 测试
- verify_e2e.py 中策略检查测试继续通过
