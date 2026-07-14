from pydantic import BaseModel, Field
from typing import Optional


class PortfolioETFBase(BaseModel):
    symbol: str
    name: str
    asset_type: str = "A"
    target_weight: float = Field(gt=0, le=1)
    portfolio_type: str = "on_exchange"
    short_name: Optional[str] = None
    tracked_index: Optional[str] = None


class PortfolioETFCreate(PortfolioETFBase):
    pass


class PortfolioETFUpdate(BaseModel):
    name: Optional[str] = None
    target_weight: Optional[float] = Field(default=None, gt=0, le=1)
    is_active: Optional[bool] = None
    portfolio_type: Optional[str] = None
    short_name: Optional[str] = None
    tracked_index: Optional[str] = None


class PortfolioETFResponse(PortfolioETFBase):
    id: int
    is_active: bool

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
    shares: float = 0


class CalculateResponse(BaseModel):
    total_capital: float
    allocations: list[AllocationItem]


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
