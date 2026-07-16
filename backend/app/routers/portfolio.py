import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.schemas import (
    PortfolioETFCreate, PortfolioETFUpdate, PortfolioETFResponse,
    CalculateRequest, StrategyCheckRequest, StrategyCheckResponse,
)
from ..services.portfolio_service import (
    list_etfs, add_etf, update_etf, remove_etf,
    calculate_allocation, calculate_daily_pnl, calculate_cumulative_pnl,
    export_portfolio, import_portfolio, calculate_weight_drift,
    strategy_check, apply_strategy_suggestions, apply_portfolio_design,
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


@router.post("/strategy-check", response_model=StrategyCheckResponse)
async def check_strategy(req: StrategyCheckRequest, db: AsyncSession = Depends(get_db)):
    return await strategy_check(db, req.total_capital, req.design_data)

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
    db: AsyncSession = Depends(get_db),
):
    """获取累计盈亏历史"""
    return await calculate_cumulative_pnl(db, portfolio_type, period)


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


@router.post("/import")
async def import_portfolio_endpoint(
    file: str,  # Will be multipart form data
    portfolio_type: str = "on_exchange",
    mode: str = "merge",
    skip_invalid: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """导入组合持仓"""
    # Note: This endpoint expects multipart/form-data
    # The actual file handling is done in the service
    from fastapi import File, UploadFile
    pass


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


@router.post("/design")
async def portfolio_design(
    risk_profile: str = "balanced",
    capital: float = 500000,
    mode: str = "standard",
    session_id: str | None = Query(None),
    constraints: dict | None = None,
    db: AsyncSession = Depends(get_db)
):
    """
    生成全市场ETF组合方案（核心+卫星+防御三层结构）。
    mode='standard': 全市场扫描+卫星层两轮评分+情绪+指标股 (~15s)
    mode='fast': 固定候选池快速生成 (~2s)
    """
    await asyncio.to_thread(asyncio.sleep, 0)  # yield control
    from datetime import datetime
    
    if risk_profile not in ["defensive", "balanced", "aggressive"]:
        raise HTTPException(status_code=400, detail="risk_profile must be 'defensive', 'balanced', or 'aggressive'")
    if mode not in ["standard", "fast"]:
        raise HTTPException(status_code=400, detail="mode must be 'standard' or 'fast'")
    
    if mode == "standard":
        # 全量管道: 全市场扫描 + 情绪 + 指标股
        from ..services.strategy_design import generate_full_design
        result = await generate_full_design(capital=capital, constraints=constraints)
        strategies = result["strategies"]
        market_context = result["market_context"]
    else:
        # 快速管道: 固定候选池
        from ..services.strategy_design import generate_design
        design = await generate_design(risk_profile, capital, mode, constraints, db)
        strategies = design
        market_context = {
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "indices": [],
            "fund_flow": [],
            "valuation_metrics": [],
            "market_sentiment": {"sentiment_index": 50, "sentiment_label": "\u4e2d\u6027"},
            "benchmark_stocks": []
        }
    
    # 保存到历史记录
    design_id = None
    try:
        from ..models.portfolio_design import PortfolioDesign
        design_record = PortfolioDesign(
            capital=capital,
            risk_profile=risk_profile,
            strategies_json=json.dumps(strategies, ensure_ascii=False, default=str),
            market_snapshot_json=json.dumps(market_context, ensure_ascii=False, default=str),
        )
        db.add(design_record)
        await db.commit()
        design_id = design_record.id
    except Exception as e:
        logger.warning("[portfolio] failed to save design history: %s", e)

    # 如果传入 session_id，启动后台 LLM 报告推送
    if session_id:
        try:
            from ..tasks.design_report import compose_and_push_report
            asyncio.create_task(compose_and_push_report(
                session_id=session_id,
                strategies=strategies,
                market_sentiment=market_context.get("market_sentiment", {}),
                benchmark_stocks=market_context.get("benchmark_stocks", []),
            ))
        except Exception as e:
            logger.warning("[portfolio] failed to schedule design report: %s", e)

    return {
        "strategies": strategies,
        "id": design_id,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "market_context": market_context
    }


# ── 设计历史记录 ──────────────────────────────────────────


@router.get("/designs")
async def list_designs(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """列出历史方案记录"""
    from sqlalchemy import select, desc
    from ..models.portfolio_design import PortfolioDesign

    stmt = (
        select(PortfolioDesign)
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

    return {
        "id": record.id,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "capital": record.capital,
        "risk_profile": record.risk_profile,
        "strategies": json.loads(record.strategies_json) if record.strategies_json else [],
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
    from ..tasks.design_tasks import task_manager
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "progress": task["progress"],
        "design_id": task.get("design_id"),
        "error_message": task.get("error_message"),
        "created_at": task.get("created_at"),
        "completed_at": task.get("completed_at"),
    }


@router.get("/tasks")
async def list_tasks(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """列出最近的任务。"""
    from ..tasks.design_tasks import task_manager
    return task_manager.list_tasks(limit=limit, offset=offset)


@router.post("/design-async")
async def portfolio_design_async(
    task: dict,
):
    """异步提交设计任务，立即返回 task_id。

    请求体: {capital: 500000, constraints: {...}}
    """
    from ..tasks.design_tasks import task_manager, design_worker
    capital = task.get("capital", 500000)
    constraints = task.get("constraints")
    t = task_manager.create_task(capital=capital, constraints=constraints)
    asyncio.create_task(design_worker(task_manager, t["task_id"]))
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={"task_id": t["task_id"], "status": "pending", "created_at": t["created_at"]},
    )
