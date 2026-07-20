# API 契约: 4.3 新闻纳入数据管道 + PoolManager 增强

## 1. PoolManager 新增方法

### get_market_regime() -> str
返回当前市场状态，委托给 `market_trends.detect_market_regime()` 并缓存 60s。

### get_market_sentiment() -> dict
返回市场情绪，从 `sentiment_fetcher` 获取并缓存 120s。

### get_factor_matrix() -> dict[str, dict]
从候选池每只 ETF 的 `factor_scores` 字段提取，格式: `{symbol: {factor_name: score}}`

### get_news() -> list[dict]
返回已缓存的新闻。无缓存时调用 `refresh_news()` 自采。
- `refresh_news()` 采集 `news_fetcher.fetch_news_headlines()` + `fetch_macro_news()`
- cache TTL 120s

## 2. 消费端更新

### llm_report (analysis.py)
- 新闻优先读 `pool_manager.get_news()`
- 自采为降级路径

### llm_news_analysis (analysis.py)
- 同上

### strategy_design.py
- 用 `pool_manager.get_factor_matrix()` 替代 `pool_manager.factor_matrix` 仮想调用
- 用 `pool_manager.get_market_regime()` 替代直接调用

## 3. 测试
- test_pool_manager_phase3.py: 新增 test_get_news() / test_get_market_regime() / test_get_factor_matrix()
- verify_e2e.py: 验证策略检查包含 regime（已有 ✅）
