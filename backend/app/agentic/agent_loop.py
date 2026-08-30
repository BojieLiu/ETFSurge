"""Plan-and-Execute 主循环（v7 P1 §4，护栏全部对齐 §4.5 边界用例）。

循环：Planner 产出的 PlanStep 列表 -> 逐步 Executor.execute -> 步输出校验 ->
RunReport（结构化部分结果 + trace_id）。

护栏（全部有 §4.5 pytest 边界用例）：
- 步数预算: max_steps=10，超限终止 + partial=True（§4.5-2）
- 时间预算: profile 对齐 llm_timeouts 单源（strategy_check=90s / design_report=120s），
  整个 run 受 asyncio.wait_for 约束，超时落 degraded + 步 error 含 timeout（§4.5-3）
- 写操作确认: PlanStep.write=True 且 confirm=False -> 拒绝执行（§4.5-6）
- 输出校验: validate_output=True 时步输出缺 source -> pydantic ValidationError（§4.5-7）
- 失败语义: data=None -> 步标 data_missing，报告 summary_note 注「数据缺失」（§4.5-8）
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.llm_timeouts import DESIGN_REPORT_READ_S, STRATEGY_CHECK_READ_S


class PlanStep(BaseModel):
    """Planner 产出的单步计划。"""
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    write: bool = False  # 写操作（调仓/下单类）需人工确认


class StepOutput(BaseModel):
    """步输出校验 schema——引用溯源强制：source 必填（§4 护栏表「输出校验」）。"""
    data: Any = None
    source: str | None = None
    as_of: str | None = None
    degraded: bool = False
    error: str | None = None

    model_config = {"extra": "allow"}


class RunStep(BaseModel):
    """run 内单步执行记录（trace 单元）。"""
    index: int
    tool: str
    arguments: dict[str, Any]
    reason: str = ""
    output: Any = None
    source: str | None = None
    degraded: bool = False
    data_missing: bool = False
    error: str | None = None
    duration_ms: float = 0.0
    skipped: bool = False


class RunReport(BaseModel):
    """一次 run 的结构化结果（§4 失败语义 + §6 trace 基础）。"""
    trace_id: str
    steps: list[RunStep] = Field(default_factory=list)
    partial: bool = False      # 步数预算截断
    degraded: bool = False     # 任一步降级/失败/超时
    summary_note: str = ""     # 数据缺失/超时等汇总说明
    elapsed_ms: float = 0.0
    stopped_reason: str = ""   # step_limit / timeout / completed


class AgentBudgetExceeded(Exception):
    """步数预算超限（预留显式类型；当前实现为截断+部分结果，不抛）。"""


class AgentLoopDetected(RuntimeError):
    """循环检测（转发 Executor 的 RuntimeError 语义）。"""


class AgentWriteNotConfirmed(PermissionError):
    """写操作未确认。"""


class AgentLoop:
    """Plan-and-Execute 循环。Planner 可为 None（直接喂手工 plan，测试态）。"""

    def __init__(
        self,
        planner: Any | None,
        executor: Any,
        allowed_tools: set[str],
        max_steps: int = 10,
        profile: str = "strategy_check",   # strategy_check | design_report
        time_budget_s: float | None = None,  # 测试注入；None 时按 profile 单源取值
    ):
        self.planner = planner
        self.executor = executor
        self.allowed_tools = set(allowed_tools)
        self.max_steps = max_steps
        if time_budget_s is not None:
            self.time_budget_s = time_budget_s
        elif profile == "design_report":
            self.time_budget_s = DESIGN_REPORT_READ_S
        else:
            self.time_budget_s = STRATEGY_CHECK_READ_S

    async def _execute_step(self, step: PlanStep) -> dict:
        """单步执行（测试 mock 点；生产直通 Executor）。"""
        return await self.executor.execute(step.tool, step.arguments)

    def _validate_output(self, out: dict) -> dict:
        """步输出 schema 校验：缺 source -> ValidationError（§4.5-7）。"""
        validated = StepOutput.model_validate(out)
        if validated.source is None:
            raise ValidationError.from_exception_data(
                title="StepOutput",
                line_errors=[{
                    "type": "missing", "loc": ("source",),
                    "input": out,
                }],
            )
        return out

    async def _run_steps(self, plan: list[PlanStep], confirm: bool,
                         validate_output: bool) -> tuple[list[RunStep], str]:
        """逐步执行；返回 (runs, stopped)。

        时间预算按「步级剩余预算」实施：单步包 asyncio.wait_for(remaining)，
        单步超时标 error="timeout..." 并继续；预算耗尽则终止后续步。
        步级实施（而非外层 wait_for 包整循环）保证超时时已完成的步不丢失——
        「终止并输出部分结果」（§4 护栏表）而非丢弃。
        """
        runs: list[RunStep] = []
        stopped = "completed"
        t0 = time.monotonic()
        for i, step in enumerate(plan[: self.max_steps]):
            remaining = self.time_budget_s - (time.monotonic() - t0)
            if remaining <= 0 and runs:
                stopped = "timeout"
                break
            rs = RunStep(index=i, tool=step.tool,
                         arguments=step.arguments, reason=step.reason)
            t_start = time.monotonic()
            if step.write and not confirm:
                rs.error = "write operation not confirmed (confirm=False)"
                rs.skipped = True
                rs.duration_ms = (time.monotonic() - t_start) * 1000
                runs.append(rs)
                continue
            try:
                out = await asyncio.wait_for(
                    self._execute_step(step), timeout=max(remaining, 0.001),
                )
                if validate_output:
                    out = self._validate_output(out)
                rs.output = out
                rs.source = out.get("source")
                rs.degraded = bool(out.get("degraded"))
                rs.data_missing = out.get("data") is None
                if rs.degraded and out.get("error"):
                    rs.error = str(out["error"])
            except asyncio.TimeoutError:
                rs.error = f"timeout after {remaining:.2f}s budget"
                rs.degraded = True
                stopped = "timeout"  # 单步超时基本耗尽预算；后续步会被 remaining<=0 拦
            except ValidationError:
                raise  # §4.5-7 期望直接冒泡
            except RuntimeError as exc:
                if "loop detected" in str(exc):
                    raise AgentLoopDetected(str(exc)) from exc
                rs.error = str(exc)
            except Exception as exc:  # noqa: BLE001
                rs.error = f"{type(exc).__name__}: {exc}"
            rs.duration_ms = (time.monotonic() - t_start) * 1000
            runs.append(rs)
        return runs, stopped

    async def run(self, plan: list[PlanStep], confirm: bool = True,
                  validate_output: bool = True) -> RunReport:
        """执行计划 -> RunReport。时间预算按步级剩余预算实施（不丢已完成步）。"""
        trace_id = uuid.uuid4().hex[:16]
        t0 = time.monotonic()
        try:
            runs, stopped = await self._run_steps(plan, confirm, validate_output)
        except AgentLoopDetected:
            raise

        partial = (stopped == "timeout") or (len(plan) > self.max_steps)
        degraded = (
            any(r.degraded or r.error for r in runs)
            or stopped == "timeout"
            or partial  # 计划未完整执行（步数截断/超时）= 部分结果 = 降级
        )
        missing = [r for r in runs if r.data_missing]
        notes: list[str] = []
        if missing:
            tools = ", ".join(r.tool for r in missing)
            notes.append(f"数据缺失: {tools}（不编造，如实标注）")
        if stopped == "timeout":
            notes.append(f"run 超时（预算 {self.time_budget_s}s），已输出部分结果")
        elif partial:
            notes.append(f"计划 {len(plan)} 步超出步数预算 {self.max_steps}，已截断输出部分结果")

        return RunReport(
            trace_id=trace_id,
            steps=runs,
            partial=partial,
            degraded=degraded,
            summary_note="; ".join(notes),
            elapsed_ms=(time.monotonic() - t0) * 1000,
            stopped_reason=stopped,
        )
