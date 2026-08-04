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
    # O8 (round7 §7 P11): 实时行情补充——路由层 build_price_map 批量注入，
    # 数据源不可用时为 None（前端显示「—」）
    price: Optional[float] = Field(default=None, description="Realtime price (injected by route)")
    change_pct: Optional[float] = Field(default=None, description="Realtime change percent (injected by route)")

    class Config:
        from_attributes = True


class CalculateRequest(BaseModel):
    total_capital: float = Field(gt=0)


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


# StrategyCheckRequest / StrategySuggestion / RiskWarning / StrategyCheckResponse 已移除
# 策略检查统一走异步路径，不再需要 sync 响应模型


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


# =============================================================================
# AI Portfolio Design Response Models / AI 组合设计响应模型
# =============================================================================

# DEPRECATED: unused schema, kept for reference
class PortfolioDesignAllocation(BaseModel):
    """单个ETF在组合中的配置详情"""
    symbol: str
    name: str
    asset_class: str
    target_weight: float
    selection_rationale: Optional[str] = None
    weight_rationale: Optional[str] = None
    tracked_index: Optional[str] = None
    key_metrics: Optional[dict] = None


# DEPRECATED: unused schema, kept for reference
class PortfolioDesignPlan(BaseModel):
    """单个风格组合方案"""
    style: str  # "进攻型" | "平衡型" | "防御型"
    style_label: str
    portfolio_name: str
    positioning: str
    expected_return: float
    max_drawdown: float
    sharpe_ratio: float
    expected_characteristics: str
    weight_logic: list[dict]
    allocations: list[PortfolioDesignAllocation]
    market_analysis: dict = {}
    allocation_rationale: dict = {}
    risk_factors: list[str] = []
    rebalance_rules: str = ""


# DEPRECATED: unused schema, kept for reference
class PortfolioComparisonItem(BaseModel):
    """对比表单项"""
    holdings_count: Optional[int] = None
    equity_pct: Optional[float] = None
    tech_pct: Optional[float] = None
    defensive_pct: Optional[float] = None
    cash_pct: Optional[float] = None
    expected_volatility: Optional[str] = None
    core_holdings: Optional[str] = None


# DEPRECATED: unused schema, kept for reference
class PortfolioDesignResponse(BaseModel):
    """AI 组合设计完整响应"""
    design_text: str
    data_snapshot_time: str
    market_environment: str
    plans: list[PortfolioDesignPlan]
    comparison_table: dict[str, PortfolioComparisonItem] = {}
    indices: list[dict] = []
    commodities: list[dict] = []


# DEPRECATED: unused schema, kept for reference
class PortfolioDesignRequest(BaseModel):
    """组合设计请求体"""
    capital: float = 500000


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


# Watchlist / 自选列表
class WatchlistBase(BaseModel):
    # Z22: symbol 必须是代码形态（字母数字点横线），拒绝中文/空格/特殊字符
    symbol: str = Field(..., pattern=r"^[0-9A-Za-z.\-]+$", min_length=1, max_length=20)
    asset_type: str = "A"
    notes: Optional[str] = None
    # R28: 前端搜索已带真实名称——入库优先用它（realtime 失败时不 422）
    name: Optional[str] = None


class WatchlistCreate(WatchlistBase):
    pass


class WatchlistUpdate(BaseModel):
    notes: Optional[str] = None
    asset_type: Optional[str] = None


class WatchlistResponse(WatchlistBase):
    id: int
    name: str
    asset_type: str
    created_at: str
    updated_at: str
    realtime: Optional[dict] = None

    class Config:
        from_attributes = True


class WatchlistListResponse(BaseModel):
    items: list[WatchlistResponse]
    total: int
    limit: int
    offset: int
