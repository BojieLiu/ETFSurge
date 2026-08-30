"""ETF Surge MCP 工具层（v7 P0，docs/etfsurge-agentic-upgrade-v7.md §3.5/§3.6）。

四个 stdio MCP Server，包装现有生产数据链路（降级链/因子引擎/异步任务/资讯）：
- quote_server.py:     get_realtime_quote / get_history_bars（T1 行情）
- factor_server.py:    get_factor_snapshot（T2 因子）
- portfolio_server.py: strategy_check + task_status（T3 组合，异步两阶段）
- news_server.py:      search_financial_news（T4 资讯）

约定：
- 输出统一信封 {data, as_of, source, degraded}（REVIEW-R1-9 沿用既有 envelope）。
- 工具失败不编造：数据缺失在信封中如实标注（degraded=true / data=null）。
- 每个 server 可独立 `python -m app.mcp_servers.<name>` 启动（P0 验收口径）。
"""
