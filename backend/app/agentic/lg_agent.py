"""LangGraph 对照实现（v7 P1.5 §7.5）——用 StateGraph 重写 P1 AgentLoop 编排层。

**定位**：对照实现，不替换 P1 自研 `app.agentic.agent_loop.AgentLoop`。
目的（v7 §7 P1.5）：回答"为什么用/不用 LangGraph？StateGraph 和 Checkpointer
分别解决什么问题？"——通过把 P1 核心循环平移到 LangGraph，暴露框架承担什么、
业务护栏仍需自写什么。

**流程**（StateGraph）：
```
START -> plan -> execute -> (条件边: remaining>0 且未超时? execute : END)
```
- State.remaining: 剩余步数（reducer 递减）
- State.steps: 已执行步记录（reducer append）
- execute 节点：复用 P1 的 Executor（白名单+循环检测）+ _validate_output（schema 校验）
  + 步级剩余时间预算（asyncio.wait_for）；单步超时/失败标 degraded 继续（不丢已完成步）

**护栏映射**（对照 P1，哪些框架承担/哪些自写）：
- 步数预算截断 + 条件边循环 → **LangGraph StateGraph 承担**（条件边）
- 步级时间预算、输出 schema 校验、数据缺失标注 → **自写**（execute 节点内）
- 工具白名单、循环检测 → **复用 P1 Executor**（工具执行层，非编排层，共享才是公平对照）

**State 的 reducer 语义**：steps 用 operator.add（append），remaining 用标量覆盖——
LangGraph 状态 reducer 是本对照要讲清的核心概念之一（为什么 steps 用 append、
remaining 用 last-write-wins）。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Annotated, Any

from typing_extensions import TypedDict

try:
    from langgraph.graph import END, StateGraph
    _LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - langgraph 未装时容错
    _LANGGRAPH_AVAILABLE = False

from pydantic import ValidationError

from app.core.llm_timeouts import DESIGN_REPORT_READ_S, STRATEGY_CHECK_READ_S
from app.agentic.agent_loop import PlanStep, RunReport, RunStep, StepOutput


def _reducer_add(a: list | None, b: list | None) -> list:
    """steps 的 reducer：append 语义（LangGraph 状态默认覆盖，需显式 reducer）。"""
    return (a or []) + (b or [])


class _State(TypedDict):
    """LangGraph 状态：共享给各节点。

    steps: 已执行步（reducer=_reducer_add，append 语义——多节点可累积）
    remaining: 剩余步数（last-write-wins，标量覆盖）
    _plan: 待执行计划（plan 节点产出，execute 节点消费）
    confirm: 写操作是否已确认
    validate_output: 是否做输出 schema 校验
    """
    steps: Annotated[list, _reducer_add]
    remaining: int
    _plan: list
    confirm: bool
    validate_output: bool


class LangGraphExecutor:
    """LangGraph 对照入口（可注入 Executor 与 profile，生产与测试同构）。"""

    def __init__(
        self,
        executor: Any,
        allowed_tools: set[str],
        max_steps: int = 10,
        profile: str = "strategy_check",
        time_budget_s: float | None = None,
    ):
        if not _LANGGRAPH_AVAILABLE:
            raise RuntimeError(
                "langgraph not installed; pip install -r requirements-agentic.txt"
            )
        self.executor = executor
        self.allowed_tools = set(allowed_tools)
        self.max_steps = max_steps
        if time_budget_s is not None:
            self.time_budget_s = time_budget_s
        elif profile == "design_report":
            self.time_budget_s = DESIGN_REPORT_READ_S
        else:
            self.time_budget_s = STRATEGY_CHECK_READ_S
        self._graph = self._build_graph()

    # ── StateGraph 节点 ─────────────────────────────────────
    def _plan_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """plan 节点：填入待执行计划 + 初始化 remaining。

        P1.5 对照：Planner 由调用方预产（plan 参数），节点只把 plan 塞进 State
        （P1 自研也是 plan 先产再逐步跑）。如需真实 LLM Planner，替换本节点即可。
        """
        plan: list[PlanStep] = state["_plan"]
        return {
            "_plan": plan,
            "remaining": len(plan),
            "task": "execute",
        }

    async def _execute_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """execute 节点：执行单步 + 护栏（复用 P1 Executor + schema 校验）。

        - 步级剩余时间预算：asyncio.wait_for(remaining)，超时标 degraded 继续
        - 循环检测/白名单：由 Executor 承担（复用，非编排层）
        - 输出 schema 校验：缺 source -> ValidationError（复用 P1 _validate_output）
        - 数据缺失：output.data is None -> data_missing=True
        返回 State 增量（reducer 聚合）。
        """
        plan: list[PlanStep] = state["_plan"]
        idx = len(state.get("steps") or [])
        limit = min(len(plan), self.max_steps)
        if idx >= limit:
            # 执行量已达 max_steps 截断上限，条件边会走 END；防御性提前返回
            return {"remaining": state.get("remaining", 0) - 1}
        step = plan[idx]
        t0 = time.monotonic()
        rs = RunStep(index=idx, tool=step.tool, arguments=step.arguments,
                     reason=step.reason)
        remaining_s = self.time_budget_s - (time.monotonic() - t0)
        # 写操作未确认 -> 拒绝（§4.5-6）
        if step.write and not state["confirm"]:
            rs.error = "write operation not confirmed (confirm=False)"
            rs.skipped = True
            rs.degraded = True
            rs.duration_ms = (time.monotonic() - t0) * 1000
        else:
            try:
                out = await asyncio.wait_for(
                    self.executor.execute(step.tool, step.arguments),
                    timeout=max(remaining_s, 0.001),
                )
                if state["validate_output"]:
                    self._validate_output(out)
                rs.output = out
                rs.source = out.get("source")
                rs.degraded = bool(out.get("degraded"))
                rs.data_missing = out.get("data") is None
                if rs.degraded and out.get("error"):
                    rs.error = str(out["error"])
            except asyncio.TimeoutError:
                rs.error = f"timeout after {remaining_s:.2f}s budget"
                rs.degraded = True
            except ValidationError:
                raise  # §4.5-7 缺 source 是契约校验错误，应冒泡（对齐 P1）
            except Exception as exc:  # noqa: BLE001 - 失败语义：结构化，不编造
                rs.error = f"{type(exc).__name__}: {exc}"
                rs.degraded = True
        rs.duration_ms = (time.monotonic() - t0) * 1000
        return {
            "steps": [rs],  # reducer append
            "remaining": state["remaining"] - 1,
        }

    def _validate_output(self, out: dict) -> dict:
        """复用 P1 的 StepOutput schema 校验（§4.5-7：缺 source -> ValidationError）。"""
        validated = StepOutput.model_validate(out)
        if validated.source is None:
            raise ValidationError.from_exception_data(
                title="StepOutput", line_errors=[{
                    "type": "missing", "loc": ("source",), "input": out,
                }],
            )
        return out

    def _route(self, state: dict[str, Any]) -> str:
        """条件边：执行完全部或被 max_steps 截断 -> END；否则继续 execute 循环。

        步数预算截断（max_steps）即由此条件边承担（框架能力）——对照 P1
        AgentLoop 的 `plan[: self.max_steps]` 截断语义。
        """
        plan_len = len(state.get("_plan") or [])
        executed = len(state.get("steps") or [])
        limit = min(plan_len, self.max_steps)
        if executed >= limit:
            return "end"
        if state.get("remaining", 0) <= 0:
            return "end"
        return "execute"

    def _build_graph(self):
        """构建 StateGraph：plan -> execute -> 条件边(execute|END)。"""
        g = StateGraph(_State)
        g.add_node("plan", self._plan_node)
        g.add_node("execute", self._execute_node)
        g.add_edge("plan", "execute")
        g.add_conditional_edges(
            "execute", self._route,
            {"execute": "execute", "end": END},
        )
        g.set_entry_point("plan")
        return g.compile()

    # ── 对外入口 ───────────────────────────────────────────
    async def run(self, plan: list[PlanStep],
                  confirm: bool = True, validate_output: bool = True) -> RunReport:
        """执行 plan -> RunReport（结构对齐 P1）。

        time_budget：LangGraph 不支持步级剩余预算的流式控制，故 execute 节点内
        用 asyncio.wait_for 包单步（与 P1 同）。整体 run 不再套外层 wait_for——
        单步超时即 degrade 继续，条件边在 remaining<=0/超时用尽时收束。
        """
        trace_id = uuid.uuid4().hex[:16]
        t0 = time.monotonic()
        start: dict[str, Any] = {
            "steps": [],
            "remaining": len(plan),
            "_plan": plan,
            "confirm": confirm,
            "validate_output": validate_output,
        }
        result = await self._graph.ainvoke(start)
        runs: list[RunStep] = result.get("steps", []) or []
        stopped = "completed"
        plan_len = len(plan)
        executed = len(runs)
        if executed > 0 and any(r.skipped for r in runs):
            stopped = "completed"
        partial = executed < plan_len or len(runs) > self.max_steps
        degraded = (
            any(r.degraded or r.error for r in runs)
            or partial
            or executed < plan_len
        )
        notes: list[str] = []
        if partial:
            notes.append(f"计划 {plan_len} 步实际执行 {executed} 步（步数/时间预算截断）")
        return RunReport(
            trace_id=trace_id, steps=runs, partial=partial, degraded=degraded,
            summary_note="; ".join(notes),
            elapsed_ms=(time.monotonic() - t0) * 1000,
            stopped_reason=stopped,
        )
