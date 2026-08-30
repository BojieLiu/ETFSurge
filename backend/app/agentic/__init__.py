"""Agentic 层（v7 P1，docs/etfsurge-agentic-upgrade-v7.md §4）。

Plan-and-Execute 循环 + 全套护栏：
- executor.py:   工具白名单 + 循环检测 + 进程内调用 P0 MCP server handler
- agent_loop.py: 主循环（步数/时间预算、写确认、输出校验、失败语义、RunReport）
- trace_store.py: 每 run 结构化 trace（P1 内存 + JSONL 落盘；P2 升 SQLite 面板）

设计约束（§1 复用优先）：
- 超时预算单源 llm_timeouts.py（STRATEGY_CHECK_READ_S=90 / DESIGN_REPORT_READ_S=120）
- 工具执行复用 P0 mcp_servers 的 handler 注册表（不重复实现业务逻辑）
- 失败语义与 P0 信封一致：degraded=true + data=None，不编造
"""
