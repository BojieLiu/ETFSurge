"""FactorICRecord model — persisted IC values for factor effectiveness tracking."""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, func
from ..database import Base


class FactorICRecord(Base):
    __tablename__ = "factor_ic_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    factor_code = Column(String(100), nullable=False, index=True)
    ic_value = Column(Float, default=0.0)
    ic_ir = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)
    computed_at = Column(DateTime, default=func.now())
