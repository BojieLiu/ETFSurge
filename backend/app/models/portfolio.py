from sqlalchemy import Boolean, Column, Date, Float, Integer, String

from ..database import Base


class PortfolioETF(Base):
    __tablename__ = "portfolio_etfs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    asset_type = Column(String(20), nullable=False, default="A")
    target_weight = Column(Float, nullable=False, default=0.05)
    portfolio_type = Column(String(20), nullable=False, default="on_exchange")
    short_name = Column(String(60), nullable=True)
    is_active = Column(Boolean, default=True)
    tracked_index = Column(String(20), nullable=True, default=None, comment="场外基金跟踪的指数代码，用于预估收益")
    # Cost basis fields for cumulative P&L
    avg_cost = Column(Float, nullable=True, default=None, comment="平均持仓成本价 (CNY/份)")
    shares_held = Column(Float, nullable=True, default=None, comment="当前持有份额/股数")
    first_buy_date = Column(Date, nullable=True, default=None, comment="首次买入日期")
    last_trade_date = Column(Date, nullable=True, default=None, comment="最近交易日期")

    @property
    def cost_basis(self) -> float | None:
        """Total cost basis = avg_cost * shares_held"""
        if self.avg_cost is not None and self.shares_held is not None:
            return round(self.avg_cost * self.shares_held, 2)
        return None
