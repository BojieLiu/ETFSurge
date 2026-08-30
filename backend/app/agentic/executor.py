"""Agentic 工具执行器（v7 P1 §4 护栏：白名单 + 循环检测）。

进程内直调 P0 MCP server 的 tools/call handler（免 stdio 子进程开销）；
MCP 协议层（stdio）保持独立可用——同一 handler，两种接入形态。

护栏（每个都有 §4.5 边界用例）：
- 白名单: execute() 收到 allowed_tools 之外的工具 -> ExecutorPermissionError
- 循环检测: 同工具+同参数(规范化 JSON)连续第 2 次 -> RuntimeError("loop detected")
  （不同参数不触发——同工具换参是合法重试）
"""
from __future__ import annotations

import importlib
import json
from typing import Any

from mcp.types import CallToolRequest

from app.core.logging import get_logger

logger = get_logger(__name__)

# P0 四个 server 模块 -> Executor 可加载的工具注册表来源
_SERVER_MODULES = (
    "app.mcp_servers.quote_server",
    "app.mcp_servers.factor_server",
    "app.mcp_servers.portfolio_server",
    "app.mcp_servers.news_server",
)


class ExecutorPermissionError(PermissionError):
    """计划外工具调用（白名单护栏）。"""


def load_server(module_name: str):
    """按模块名加载并返回其低层 Server 实例（测试 patch 点）。"""
    mod = importlib.import_module(module_name)
    return mod.server


def load_all_tools() -> dict[str, Any]:
    """聚合四个 P0 server 的 tools/call handler（进程内注册表）。

    key 用 server 模块短名（quote/factor/portfolio/news），value 是
    {"handler": call_handler, "server": server}——tool_names 由
    Executor 在 async 上下文中惰性探测（_probe_tool_names），
    避免 load 时嵌套 asyncio.run（pytest-asyncio 环境会炸）。
    """
    registry: dict[str, Any] = {}
    for mod_name in _SERVER_MODULES:
        server = load_server(mod_name)
        call_handler = server.request_handlers.get(CallToolRequest)
        if call_handler is None:
            continue
        short = mod_name.rsplit(".", 1)[-1].replace("_server", "")
        registry[short] = {"handler": call_handler, "server": server}
    return registry


async def _probe_tool_names(server: Any) -> set[str]:
    """req-form 调 server 的 list_tools handler 取工具名清单（async 惰性）。"""
    from mcp.types import ListToolsRequest

    list_handler = server.request_handlers.get(ListToolsRequest)
    if list_handler is None:
        return set()
    empty = ListToolsRequest.model_validate({"method": "tools/list", "params": {}})
    try:
        res = await list_handler(empty)
        # 1.29.x req-form 返回 ServerResult 包装（.root 才是 ListToolsResult）
        inner = getattr(res, "root", res)
        return {t.name for t in inner.tools}
    except Exception:  # noqa: BLE001 - 探测失败不致命
        return set()


class Executor:
    """白名单工具执行器：进程内调 MCP handler，输出统一信封 dict。"""

    def __init__(self, allowed_tools: set[str],
                 servers: dict[str, Any] | None = None):
        self.allowed_tools = set(allowed_tools)
        self._servers = servers  # 测试注入点；None 时懒加载真实注册表
        self._last_call: tuple[str, str] | None = None
        self._route_cache: dict[str, set[str]] | None = None  # short -> tool_names

    async def _resolve_handler(self, tool: str):
        """工具名 -> call handler。按各 server 的 tools 清单路由到正确 server。

        - 真实注册表（_servers=None）: load_all_tools() + async 惰性探测
          每个 server 的 list_tools 清单，tool 命中即路由（结果缓存）。
        - 测试注入（_servers=dict）: 每个 server 逐一试（单 server 场景够用）。
        找不到 -> None（execute 返回 no handler 错误信封）。
        """
        if self._servers is not None:
            for server in self._servers.values():
                handler = server.request_handlers.get(CallToolRequest)
                if handler:
                    return handler
            return None
        registry = load_all_tools()
        if self._route_cache is None:
            self._route_cache = {}
        # 先走缓存命中
        for short, names in (self._route_cache or {}).items():
            if tool in names:
                entry = registry.get(short)
                if entry:
                    return entry["handler"]
        # 未命中：逐 server 探测（探测失败/空集的 server 不登记，最后 fallback 试调）
        unprobed: list[tuple[str, dict]] = []
        for short, entry in registry.items():
            if short in self._route_cache:
                continue
            names = await _probe_tool_names(entry["server"])
            if names:
                self._route_cache[short] = names
                if tool in names:
                    return entry["handler"]
            else:
                unprobed.append((short, entry))
        # 兜底：tools 清单探测失败的 server，按 handler 存在即用（mock/非标 server）
        for _short, entry in unprobed:
            return entry["handler"]
        return None

    @staticmethod
    def _normalize_args(arguments: dict | None) -> str:
        return json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False)

    def _check_loop(self, tool: str, arguments_json: str) -> None:
        """循环检测：同 (tool, args) 连续出现 2 次 -> RuntimeError。

        §4.5-5 边界用例: test_guard_loop_detected_terminates。
        """
        call = (tool, arguments_json)
        if self._last_call == call:
            raise RuntimeError(
                f"loop detected: {tool} {arguments_json} called twice in a row"
            )
        self._last_call = call

    async def execute(self, tool: str, arguments: dict | None) -> dict:
        """执行一个工具调用，返回统一信封 dict。

        - 白名单外 -> ExecutorPermissionError（§4.5-1）
        - 循环 -> RuntimeError("loop detected")（§4.5-5）
        - handler 异常/未知工具 -> error 信封（degraded=true, data=None）
        """
        if tool not in self.allowed_tools:
            raise ExecutorPermissionError(
                f"tool {tool!r} not in whitelist {sorted(self.allowed_tools)}"
            )
        args_json = self._normalize_args(arguments)
        self._check_loop(tool, args_json)

        handler = await self._resolve_handler(tool)
        if handler is None:
            return {"data": None, "as_of": None, "source": None, "degraded": True,
                    "error": f"no handler registered for tool {tool!r}"}

        req = CallToolRequest.model_validate(
            {"method": "tools/call",
             "params": {"name": tool, "arguments": arguments or {}}}
        )
        try:
            result = await handler(req)
            text = result.root.content[0].text
            import json as _json
            payload = _json.loads(text)
            return payload if isinstance(payload, dict) else {"data": payload}
        except Exception as exc:  # noqa: BLE001 - 失败语义：结构化错误，不编造
            logger.warning("[agentic] tool %s failed: %s", tool, exc)
            return {"data": None, "as_of": None, "source": None, "degraded": True,
                    "error": f"{type(exc).__name__}: {exc}"}
