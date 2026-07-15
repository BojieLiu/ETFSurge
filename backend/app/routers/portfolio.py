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
