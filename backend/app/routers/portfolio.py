import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.schemas import (
    PortfolioETFCreate, PortfolioETFUpdate, PortfolioETFResponse,
    CalculateRequest,
)
from ..services.portfolio_service import (
    list_etfs, add_etf, update_etf, remove_etf,
    calculate_allocation, calculate_daily_pnl, calculate_cumulative_pnl,
    export_portfolio, import_portfolio, calculate_weight_drift,
    apply_strategy_suggestions, apply_portfolio_design,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


@router.get("/etfs", response_model=list[PortfolioETFResponse])
async def get_etfs(
    portfolio_type: str = Query(None, pattern="^(on_exchange|off_exchange)?$"),
    db: AsyncSession = Depends(get_db),
):
    return await list_etfs(db, portfolio_type)


@router.post("/etfs", response_model=PortfolioETFResponse, status_code=201)
async def create_etf(data: PortfolioETFCreate, db: AsyncSession = Depends(get_db)):
    return await add_etf(db, data)


@router.put("/etfs/{symbol}", response_model=PortfolioETFResponse)
async def update_etf_route(symbol: str, data: PortfolioETFUpdate, db: AsyncSession = Depends(get_db)):
    result = await update_etf(db, symbol, data)
    if not result:
        raise HTTPException(status_code=404, detail="ETF not found")
    return result


@router.delete("/etfs/{symbol}", status_code=204)
async def delete_etf(symbol: str, db: AsyncSession = Depends(get_db)):
    success = await remove_etf(db, symbol)
    if not success:
        raise HTTPException(status_code=404, detail="ETF not found")


@router.post("/calculate")
async def calculate(
    req: CalculateRequest,
    portfolio_type: str = Query(None, pattern="^(on_exchange|off_exchange)?$"),
    db: AsyncSession = Depends(get_db),
):
    return await calculate_allocation(db, req.total_capital, portfolio_type)


@router.post("/daily-pnl")
async def daily_pnl(
    req: CalculateRequest,
    portfolio_type: str = Query(None, pattern="^(on_exchange|off_exchange)?$"),
    db: AsyncSession = Depends(get_db),
):
    return await calculate_daily_pnl(db, req.total_capital, portfolio_type)


@router.post("/apply-strategy")
async def apply_strategy(suggestions: list, db: AsyncSession = Depends(get_db)):
    return await apply_strategy_suggestions(db, suggestions)

@router.post("/apply-design")
async def apply_design(design: dict, db: AsyncSession = Depends(get_db)):
    return await apply_portfolio_design(db, design)


@router.get("/pnl-history")
async def pnl_history(
    portfolio_type: str | None = None,
    period: str = "all",
    total_capital: float = Query(0.0, description="总投资额，用于在成本数据缺失时估算"),
    db: AsyncSession = Depends(get_db),
):
    """获取累计盈亏历史"""
    return await calculate_cumulative_pnl(db, portfolio_type, period, total_capital)


@router.get("/export")
async def export_portfolio_endpoint(
    portfolio_type: str | None = None,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    """导出组合持仓"""
    result = await export_portfolio(db, portfolio_type, format)
    if format == "json":
        return {"holdings": result}
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=result, media_type="text/csv")



# Proper import endpoint with file upload
from fastapi import File, UploadFile

@router.post("/import", response_model=dict)
async def import_portfolio_file(
    file: UploadFile = File(...),
    portfolio_type: str = "on_exchange",
    mode: str = "merge",
    skip_invalid: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """导入组合持仓 CSV 文件"""
    content = await file.read()
    csv_content = content.decode("utf-8")
    return await import_portfolio(db, csv_content, portfolio_type, mode, skip_invalid)


@router.get("/drift-check")
async def drift_check(
    portfolio_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """权重偏离检查"""
    return await calculate_weight_drift(db, portfolio_type)


# ── /design 和 /design-enhanced 已迁移到 /design-async ──
# 旧同步路由已移除，请使用 POST /portfolio/design-async


# ── 设计历史记录 ──────────────────────────────────────────


@router.get("/designs")
async def list_designs(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """列出历史方案记录"""
    from sqlalchemy import select, desc
    from sqlalchemy.orm import load_only
    from ..models.portfolio_design import PortfolioDesign

    # UX3: 只加载元数据字段，避免 market_snapshot_json / design_text 大字段拖慢查询
    stmt = (
        select(PortfolioDesign)
        .options(load_only(
            PortfolioDesign.id,
            PortfolioDesign.created_at,
            PortfolioDesign.capital,
            PortfolioDesign.risk_profile,
            PortfolioDesign.status,
            PortfolioDesign.error_message,
            PortfolioDesign.strategies_json,
        ))
        .order_by(desc(PortfolioDesign.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "capital": r.capital,
            "risk_profile": r.risk_profile,
            "status": r.status or "completed",
            "error_message": r.error_message,
            # Phase 2.7.8: 计算非 CASH ETF 总数
            "etf_count": sum(
                sum(1 for a in (s.get("etfs") or []) if a.get("symbol") != "CASH")
                for s in (json.loads(r.strategies_json) if r.strategies_json else [])
            ),
        }
        for r in records
    ]


@router.get("/designs/{design_id}")
async def get_design(
    design_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查看某次设计的完整详情"""
    from sqlalchemy import select
    from ..models.portfolio_design import PortfolioDesign

    stmt = select(PortfolioDesign).where(PortfolioDesign.id == design_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Design not found")

    strategies = json.loads(record.strategies_json) if record.strategies_json else []

    # Build plans from strategies (Sprint 1 P1: eliminate frontend conversion)
    plans = []
    for s in strategies:
        etfs = s.get("etfs", []) or []
        plans.append({
            "style": s.get("label", ""),
            "style_label": s.get("label", ""),
            "portfolio_name": s.get("portfolio_name", ""),
            "positioning": s.get("positioning", ""),
            "expected_return": s.get("expected_return"),
            "max_drawdown": s.get("max_drawdown"),
            "sharpe_ratio": s.get("sharpe_ratio"),
            "risk_factors": s.get("risk_factors") or [],
            "rebalance_rules": "月度检视",
            "allocations": [
                {
                    "symbol": e.get("symbol", ""),
                    "name": e.get("name", ""),
                    "layer": e.get("layer", ""),
                    "target_weight": e.get("weight", 0),
                    "selection_rationale": e.get("selection_rationale") or "",
                }
                for e in etfs
            ],
        })

    return {
        "id": record.id,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "capital": record.capital,
        "risk_profile": record.risk_profile,
        "design_text": record.design_text or "",
        "status": record.status or "completed",
        "error_message": record.error_message,
        "report_quality": record.report_quality or "none",
        "report_generated_at": record.report_generated_at.isoformat() if record.report_generated_at else None,
        "strategies": strategies,
        "plans": plans,
        "market_context": json.loads(record.market_snapshot_json) if record.market_snapshot_json else {},
    }




@router.delete("/designs/{design_id}")
async def delete_design(
    design_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除某次方案记录"""
    from sqlalchemy import select
    from ..models.portfolio_design import PortfolioDesign

    stmt = select(PortfolioDesign).where(PortfolioDesign.id == design_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Design not found")

    await db.delete(record)
    await db.commit()
    return {"detail": "deleted"}

# ── 异步任务 ──────────────────────────────────
@router.get("/tasks/{task_id}")
async def get_task_status(task_id: int):
    """查询异步任务状态。"""
    from ..tasks.task_manager import task_manager
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "progress": task["progress"],
        "error_message": task.get("error_message"),
        "created_at": task.get("created_at"),
        "completed_at": task.get("completed_at"),
        "result": task.get("result"),
    }


@router.get("/tasks")
async def list_tasks(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """列出最近的任务。"""
    from ..tasks.task_manager import task_manager
    return task_manager.list_tasks(limit=limit, offset=offset)


@router.post("/design-async")
async def portfolio_design_async(
    task: dict,
):
    """异步提交设计任务，立即返回 task_id。

    请求体: {capital: 500000, constraints: {...}, market: "A"}
    Phase 5.1: 非 A 市场返回 unsupported 友好提示。
    """
    from ..core.market_context import resolve_market_context
    from fastapi.responses import JSONResponse

    market = task.get("market", "A")
    market_ctx = resolve_market_context(market)
    if not market_ctx.supports_portfolio_design:
        return JSONResponse(
            status_code=202,
            content={
                "task_id": None,
                "status": "unsupported",
                "message": f"组合设计当前仅支持 A 股市场（沪市/深市 ETF）。{market_ctx.title}市场的组合设计功能正在规划中。",
            },
        )

    from ..tasks.task_manager import task_manager, design_worker
    capital = task.get("capital", 500000)
    constraints = task.get("constraints")
    params = {"capital": capital, "constraints": constraints, "market": market}
    t = task_manager.create_task(task_type="design", params=params)
    asyncio.create_task(design_worker(task_manager, t["task_id"]))
    return JSONResponse(
        status_code=202,
        content={"task_id": t["task_id"], "status": "pending", "created_at": t["created_at"]},
    )


# ── 异步策略检查 ─────────────────────────────────────────


@router.post("/strategy-check-async")
async def strategy_check_async(task: dict):
    """异步提交策略检查任务，立即返回 task_id。

    请求体: {capital: 500000, ...}
    """
    try:
        from fastapi.responses import JSONResponse
        from ..tasks.task_manager import task_manager
        from ..tasks.strategy_check_worker import strategy_check_worker

        total_capital = task.get("total_capital", 500000)
        portfolio_type = task.get("portfolio_type")
        t = task_manager.create_task(task_type="check", params={"capital": total_capital, "portfolio_type": portfolio_type})
        asyncio.create_task(strategy_check_worker(task_manager, t["task_id"]))
        return JSONResponse(
            status_code=202,
            content={"task_id": t["task_id"], "status": "pending", "created_at": t["created_at"]},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/strategy-check-result/{task_id}")
async def get_strategy_check_result(task_id: int):
    """查询异步策略检查任务的结果。"""
    from ..tasks.task_manager import task_manager
    from fastapi.responses import JSONResponse

    task = task_manager.get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "task not found"})
    
    if task["status"] != "completed":
        return {
            "task_id": task_id,
            "status": task["status"],
            "progress": task.get("progress", 0),
            "error_message": task.get("error_message"),
            "stage": task.get("stage", ""),
        }

    result = task.get("result", {})
    return {
        "task_id": task_id,
        "status": "completed",
        "summary": result.get("summary", ""),
        "suggestions": result.get("suggestions", []),
        "holdings_analysis": result.get("holdings_analysis", []),
        "risk_warnings": result.get("risk_warnings", []),
        "market_regime": result.get("market_regime", ""),
        "record_id": task.get("record_id"),
    }


@router.get("/strategy-checks")
async def list_strategy_checks(limit: int = 10, offset: int = 0):
    """列出历史策略检查记录。"""
    try:
        from sqlalchemy import select, desc
        from sqlalchemy.ext.asyncio import AsyncSession
        from ..database import async_session
        from ..models.strategy_check import StrategyCheckRecord

        async with async_session() as db:
            stmt = (
                select(StrategyCheckRecord)
                .order_by(desc(StrategyCheckRecord.created_at))
                .offset(offset)
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [r.to_dict() for r in rows]
    except Exception:
        logger.exception("[strategy_checks] listing failed")
        return []


@router.get("/strategy-checks/{check_id}")
async def get_strategy_check(check_id: int):
    """获取单条策略检查记录详情。"""
    from sqlalchemy import select
    from ..database import async_session
    from ..models.strategy_check import StrategyCheckRecord

    async with async_session() as db:
        stmt = select(StrategyCheckRecord).where(StrategyCheckRecord.id == check_id)
        r = (await db.execute(stmt)).scalar_one_or_none()
        if not r:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "not found"})
        return r.to_dict()


@router.get("/timeline")
async def get_timeline(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Get merged timeline of portfolio designs and strategy checks.
    Queries both tables, merges by created_at DESC, supports pagination.
    """
    from ..models.portfolio_design import PortfolioDesign
    from ..models.strategy_check import StrategyCheckRecord
    import json

    # Query designs
    design_stmt = select(PortfolioDesign).order_by(PortfolioDesign.created_at.desc())
    design_result = await db.execute(design_stmt)
    designs = design_result.scalars().all()

    # Query checks
    check_stmt = select(StrategyCheckRecord).order_by(StrategyCheckRecord.created_at.desc())
    check_result = await db.execute(check_stmt)
    checks = check_result.scalars().all()

    # Build items from designs
    design_items = []
    for d in designs:
        strategies = json.loads(d.strategies_json) if d.strategies_json else []
        design_items.append({
            "id": d.id,
            "_type": "design",
            "created_at": d.created_at.isoformat() if d.created_at else "",
            "status": d.status or "completed",
            "capital": d.capital,
            "error_message": d.error_message,
        })

    # Build items from checks
    check_items = []
    for c in checks:
        check_items.append({
            "id": c.id,
            "_type": "check",
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "status": c.status or "completed",
            "summary": c.summary or c.error_message or "\u7b56\u7565\u68c0\u67e5\u5df2\u5b8c\u6210",
            "error_message": c.error_message,
        })

    # Merge and sort by created_at DESC
    merged = sorted(design_items + check_items, key=lambda x: x["created_at"], reverse=True)
    total = len(merged)

    # Paginate
    items = merged[offset:offset + limit]

    return {"items": items, "total": total}