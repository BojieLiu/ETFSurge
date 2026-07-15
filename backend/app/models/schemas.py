from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class PortfolioETFBase(BaseModel):
    symbol: str
    name: str
    asset_type: str = "A"
    target_weight: float = Field(gt=0, le=1)
    portfolio_type: str = "on_exchange"
    short_name: Optional[str] = None
    tracked_index: Optional[str] = None
    avg_cost: Optional[float] = Field(default=None, ge=0, description="Average cost basis per share (CNY)")
    shares_held: Optional[float] = Field(default=None, ge=0, description="Number of shares currently held")
    first_buy_date: Optional[date] = Field(default=None, description="First purchase date (YYYY-MM-DD)")
    last_trade_date: Optional[date] = Field(default=None, description="Last trade date (YYYY-MM-DD)")


class PortfolioETFCreate(PortfolioETFBase):
    pass


class PortfolioETFUpdate(BaseModel):
    name: Optional[str] = None
    target_weight: Optional[float] = Field(default=None, gt=0, le=1)
    is_active: Optional[bool] = None
    portfolio_type: Optional[str] = None
    short_name: Optional[str] = None
    tracked_index: Optional[str] = None
    avg_cost: Optional[float] = Field(default=None, ge=0)
    shares_held: Optional[float] = Field(default=None, ge=0)
    first_buy_date: Optional[date] = None
    last_trade_date: Optional[date] = None


class PortfolioETFResponse(PortfolioETFBase):
    id: int
    is_active: bool
    cost_basis: Optional[float] = Field(default=None, description="Total cost basis = avg_cost * shares_held")

    class Config:
        from_attributes = True


class CalculateRequest(BaseModel):
    total_capital: float = Field(gt=0)


class StrategyCheckRequest(BaseModel):
    total_capital: float = Field(gt=0)
    design_data: Optional[dict] = None  # AI portfolio design to check instead of DB ETFs


class AllocationItem(BaseModel):
    symbol: str
    name: str
    short_name: Optional[str] = None
    asset_type: str
    portfolio_type: str
    target_weight: float
    target_amount: float
    current_price: float
    change_pct: float = 0
    shares: float = 0
    tracked_index: Optional[str] = None
    is_estimated: bool = False
    estimate_source: Optional[str] = None
    shares_outstanding: Optional[float] = None
    fund_scale: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    avg_volume_20d: Optional[float] = None
    main_net_inflow: Optional[float] = None
    main_net_inflow_pct: Optional[float] = None


class CalculateResponse(BaseModel):
    total_capital: float
    allocations: list[AllocationItem]
    total_amount: Optional[float] = None
    cash_weight: Optional[float] = None
    cash_amount: Optional[float] = None


class PNLItem(BaseModel):
    symbol: str
    name: str
    short_name: Optional[str] = None
    asset_type: str
    portfolio_type: str
    target_amount: float
    current_price: float
    change_pct: float
    daily_pnl: float
    tracked_index: Optional[str] = None
    is_estimated: bool = False
    estimate_source: Optional[str] = None
    shares_outstanding: Optional[float] = None
    fund_scale: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    main_net_inflow: Optional[float] = None
    main_net_inflow_pct: Optional[float] = None


class PNLSummary(BaseModel):
    items: list[PNLItem]
    total_pnl: float
    total_amount: float
    weighted_change_pct: float


class StrategySuggestion(BaseModel):
    action: str
    symbol: str
    name: str
    current_weight: float
    suggested_weight: float
    reason: str


class StrategyCheckResponse(BaseModel):
    summary: str
    suggestions: list[StrategySuggestion]
    raw_llm: str


# PnL History / 累计盈亏历史
class HoldingPnL(BaseModel):
    symbol: str
    name: str
    short_name: Optional[str] = None
    asset_type: str
    portfolio_type: str
    shares_held: float
    avg_cost: float
    cost_basis: float
    current_price: float
    market_value: float
    cumulative_pnl: float
    cumulative_pnl_pct: float
    first_buy_date: Optional[str] = None
    last_trade_date: Optional[str] = None


class DailyPnLSeries(BaseModel):
    date: str
    total_market_value: float
    total_cumulative_pnl: float
    total_cumulative_pnl_pct: float


class PnLHistoryResponse(BaseModel):
    summary: dict
    holdings: list[HoldingPnL]
    daily_series: list[DailyPnLSeries]


# Portfolio Export/Import / 组合导出导入
class ImportError(BaseModel):
    row: int
    symbol: str
    error: str


class ImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[ImportError]
    holdings: list[PortfolioETFResponse]
