"""FactorICRecord model — persisted IC values for factor effectiveness tracking."""

from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, UniqueConstraint, func

from ..database import Base


class FactorICRecord(Base):
    __tablename__ = "factor_ic_records"
    __table_args__ = (
        # F25① (round23): 日频 1 行/因子——(factor_code, trade_date) 唯一，同天 upsert 不追加。
        # 旧实现每 120s 刷新存 1 行（4306 行/18 天 ≈240× 虚高 sample_count），本约束根治注水。
        UniqueConstraint("factor_code", "trade_date", name="uq_factor_ic_code_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    factor_code = Column(String(100), nullable=False, index=True)
    ic_value = Column(Float, default=0.0)
    ic_ir = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)
    computed_at = Column(DateTime, default=func.now())
    # F25①: 交易日（北京时间，日频 1 行）；F25③: signal_absent 标记不删（修复生存者偏差）
    trade_date = Column(Date, nullable=True, index=True)
    signal_absent = Column(Boolean, default=False)

