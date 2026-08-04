"""
异步策略检查 worker（v2 pipeline）
Async strategy check pipeline

v2 (design-check-pipeline-redesign):
  - 顺序 Pipeline: DATA → LLM → DB SAVE → NOTIFY
  - 去除外层 240s 超时，改为 per-stage 超时保护
  - 新增 per-stage WS 进度通知
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)



async def _generate_check_llm_report(result: dict, capital: float) -> str | None:
    """S7: 生成策略检查的 LLM 分析报告。
    
    基于持仓分析结果，调用 LLM 生成简短的市场研判和建议。
    """
    try:
        import asyncio
        from ..analysis.llm import llm_complete
        
        positions = result.get("positions", [])
        if not positions:
            return None
            
        # Build a compact summary for LLM
        total_value = sum(p.get("market_value", 0) for p in positions)
        total_change = sum(p.get("change_pct", 0) for p in positions)
        top_holdings = [p for p in positions if p.get("weight", 0) > 0.05][:5]
        
        summary = (
            f"当前持仓 {len(positions)} 只ETF，总市值 {total_value:.2f}，"
            f"平均涨跌幅 {total_change/len(positions):.2f}%。\n"
        )
        if top_holdings:
            summary += "主要持仓：\n"
            for h in top_holdings:
                if h.get("symbol"):
                    summary += f"- {h.get('name','')}({h.get('symbol')}): "
                    summary += f"权重 {h.get('weight',0)*100:.1f}%, "
                    summary += f"涨跌 {h.get('change_pct',0):.2f}%\n"
        
        prompt = (
            "请根据以下ETF组合持仓信息，给出简短的市场研判和调仓建议（200字以内）：\n\n"
            + summary
        )
        
        response = await asyncio.wait_for(llm_complete(prompt), timeout=30)
        if response and response.strip():
            return response.strip()
        return None
    except Exception as e:
        logger.warning("[strategy_check] LLM report generation failed: %s", e)
        return None


async def strategy_check_pipeline(mgr, task_id: int) -> None:
    """顺序 Pipeline：DATA → LLM → DB SAVE → NOTIFY

    R5-1-1: 与 design 任务共享 LLM 互斥信号量（同一时间仅 1 个 LLM 任务在跑），
    防止预热期并发打满 DeepSeek 配额 → 429 级联超时。
    """
    # lazy import 避免循环依赖（task_manager 不反向依赖本模块）
    from .task_manager import _design_semaphore

    async with _design_semaphore:
        return await _strategy_check_pipeline_guarded(mgr, task_id)


async def _strategy_check_pipeline_guarded(mgr, task_id: int) -> None:
    """实际管线（被 _design_semaphore 保护）。"""
    from ..services.portfolio_service import strategy_check
    from app.database import async_session

    task = await mgr.get_task(task_id)
    if not task:
        return

    try:
        # FIX-21: 外层超时保护，防止整个管线无限制挂起
        # O25 (round7 §7 P25): 120s → 150s——LLM 完整档 60s + 采集 2×25s + 余量，
        # 避免「采集慢 + LLM 完整档」被外层提前截断。
        import asyncio
        return await asyncio.wait_for(
            _pipeline_body(mgr, task_id),  # type: ignore[arg-type]
            timeout=150,
        )
    except asyncio.TimeoutError:
        logger.error("[strategy_check_pipeline] task %d timed out after 150s", task_id)
        await mgr.update_task(
            task_id,
            status="failed",
            progress=100,
            stage="分析超时",
            result={"error": "策略检查超时（150s）", "partial_data": {}},
        )
        await _notify(task_id, "failed", progress=100, stage="分析超时")
    except Exception as e:
        logger.error("[strategy_check_pipeline] task %d failed: %s", task_id, e)
        await mgr.update_task(
            task_id,
            status="failed",
            progress=100,
            result={"error": str(e)},
        )
        await _notify(task_id, "failed", progress=100, stage="分析失败")


async def _pipeline_body(mgr, task_id: int) -> dict:
    """FIX-21: Pipeline 主体逻辑，被外层 asyncio.wait_for 保护。"""
    from ..services.portfolio_service import strategy_check
    from app.database import async_session

    task = await mgr.get_task(task_id)
    if not task:
        return {}

    await mgr.update_task(task_id, status="running", progress=5, stage="初始化")
    await _notify(task_id, "running", progress=5, stage="初始化")

    params = task.get("params", {})
    capital = params.get("capital", 500000)
    portfolio_type = params.get("portfolio_type")

    # Stage 1: DATA (progress 5→40%) — 数据采集 & 策略检查
    await mgr.update_task(task_id, progress=10, stage="加载持仓数据")
    await _notify(task_id, "running", progress=10, stage="加载持仓数据")

    from app.database import async_session
    async with async_session() as db:
        result = await strategy_check(db, capital, portfolio_type=portfolio_type)

    await mgr.update_task(task_id, progress=40, stage="数据采集完成")
    await _notify(task_id, "running", progress=40, stage="数据采集完成")

    # Stage 2: LLM (progress 40→80%) — LLM 已在 strategy_check 内部完成
    await mgr.update_task(task_id, progress=60, stage="AI 分析完成")
    await _notify(task_id, "running", progress=60, stage="AI 分析完成")

    # Stage 3: DB (progress 80→95%) — 持久化到数据库
    await mgr.update_task(task_id, progress=80, stage="保存报告")
    await _notify(task_id, "running", progress=80, stage="保存报告")

    record_id = None
    try:
        from app.models.strategy_check import StrategyCheckRecord

        async with async_session() as db:
            record = StrategyCheckRecord(
                capital=capital,
                summary=result.get("summary", ""),
                market_regime=result.get("market_regime", ""),
                suggestions_json=json.dumps(
                    result.get("suggestions", []), ensure_ascii=False, default=str
                ),
                holdings_json=json.dumps(
                    result.get("holdings_analysis", []), ensure_ascii=False, default=str
                ),
                risk_warnings_json=json.dumps(
                    result.get("risk_warnings", []), ensure_ascii=False, default=str
                ),
                report_text=result.get("report_text", "") or "",
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            record_id = int(record.id)
            logger.info("[strategy_check_pipeline] record %d saved", record_id)
    except Exception as e:
        logger.warning("[strategy_check_pipeline] DB persist failed: %s", e)

    # U2 R2: report_text 为空 → 任务标记 failed（诚实收敛，前端可提示
    # "LLM 分析失败，已展示规则摘要"；旧实现 completed + 空报告误导用户）
    report_text = result.get("report_text", "") or ""
    if not report_text.strip():
        logger.warning(
            "[strategy_check_pipeline] report_text empty for task %d — marking failed",
            task_id,
        )
        await mgr.update_task(task_id, status="failed", stage="报告为空")
        await _notify(task_id, "failed", progress=95, stage="报告为空")
        return result

    # S7: 生成 LLM 市场研判注释（非阻塞，失败不影响主流程）
    try:
        llm_comment = await _generate_check_llm_comment(result)
        if llm_comment:
            result["llm_comment"] = llm_comment
    except Exception:
        pass

    # Stage 4: NOTIFY (progress 95→100%)
    await mgr.update_task(
        task_id,
        progress=100,
        status="completed",
        result=result,
        record_id=record_id,
    )
    await _notify(task_id, "completed", progress=100, stage="分析完成",
                  record_id=record_id, task_type="check")

    logger.info(
        "[strategy_check_pipeline] task %d completed (record %s)",
        task_id,
        record_id,
    )

    return result


async def _notify(task_id: int, status: str, progress: int, stage: str = "",
                  record_id: int | None = None, task_type: str = "check") -> None:
    """通过 WS 广播任务状态变更（Z27: 契约 §2.4.2 — 携带 task_type + record_id）。"""
    from ..tasks.task_manager import notify_manager

    await notify_manager.broadcast({
        "type": "task_update",
        "task_id": task_id,
        "task_type": task_type,
        "status": status,
        "progress": progress,
        "stage": stage,
        "record_id": record_id,
    })


# ── S7: LLM 市场研判注释生成 ───────────────────────────────────


async def _generate_check_llm_comment(result: dict) -> str | None:
    """S7: 基于策略检查结果，生成简短 LLM 市场研判注释。

    非阻塞函数，失败时静默返回 None。
    """
    try:
        import asyncio
        from ..analysis.llm import llm_complete

        positions = result.get("positions", [])
        if not positions:
            return None

        total_value = sum(p.get("market_value", 0) for p in positions)
        avg_change = sum(p.get("change_pct", 0) for p in positions) / max(len(positions), 1)
        top3 = sorted(positions, key=lambda x: abs(x.get("weight", 0)), reverse=True)[:3]

        lines = [f"当前持仓 {len(positions)} 只ETF，总市值 {total_value:.0f}"]
        lines.append(f"组合平均涨跌 {avg_change:+.2f}%")
        for p in top3:
            name = p.get("name", "") or p.get("symbol", "")
            w = p.get("weight", 0) * 100
            chg = p.get("change_pct", 0)
            lines.append(f"  - {name}: 权重 {w:.1f}%, 涨跌 {chg:+.2f}%")

        prompt = (
            "请根据以下ETF组合持仓信息，给出简短的市场研判和调仓建议"
            "（150字以内，中文，分1-2点）：\n\n"
            + "\n".join(lines)
        )

        response = await asyncio.wait_for(llm_complete(prompt), timeout=20)
        if response and response.strip():
            return response.strip()
        return None
    except Exception as e:
        logger.debug("[strategy_check] LLM comment generation skipped: %s", e)
        return None


# ── Backward-compatible alias ─────────────────────────────────
strategy_check_worker = strategy_check_pipeline
