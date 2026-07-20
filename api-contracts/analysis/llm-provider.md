# API 契约: Phase 4 链路复用

## 4.1 strategy_check 复用 pool_manager 数据

### 当前
```python
# portfolio_service.py:364-378
factor_task = factor_registry.compute(symbols)  # 自采历史数据再算因子
```

### 目标
```python
# 直接复用 pool_manager 已缓存的 factor_matrix
from ..services.pool_manager import pool_manager
factor_matrix = pool_manager.get_factor_matrix() or {}
factor_scores = {sym: factor_matrix.get(sym, {}) for sym in symbols}
```

### 变更
- 删除 `factor_task = factor_registry.compute(symbols)` 和对应的 `asyncio.gather`
- `strategy_check()` 减少约 20s（免去数据采集+因子计算）
- regime 已在上一轮统一，这次只改 factor 复用

### 测试: verify_e2e.py 策略检查测试通过

---

## 4.4 llm-report 改用编排器 market_context

### 当前
```python
# analysis.py:llm_report()
results = await asyncio.gather(
    get_all_realtime(), get_indices(), get_commodities(),
    fetch_news_headlines(), fetch_macro_news(),
)
```

### 目标
优先使用 pool_manager 缓存的上下文，缓存未就绪时才自采。

### 变更
- 新增 `_get_orchestrator_context()` 工具函数
- `llm_report()` 先尝试读 pool_manager 缓存，降级才自采
- regime / sentiment 等数据通过编排器注入 LLM prompt

### 测试: `POST /analysis/llm-report` 返回正常
