from sqlalchemy import Column, Integer, String, Float, Boolean
from ..database import Base


class PortfolioETF(Base):
    __tablename__ = "portfolio_etfs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    asset_type = Column(String(20), nullable=False, default="A")
    target_weight = Column(Float, nullable=False)
    portfolio_type = Column(String(20), nullable=False, default="on_exchange")
    short_name = Column(String(60), nullable=True)
    is_active = Column(Boolean, default=True)
    tracked_index = Column(String(20), nullable=True, default=None, comment="场外基金跟踪的指数代码，用于预估收益")
