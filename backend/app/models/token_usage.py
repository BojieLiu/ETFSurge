from sqlalchemy import Column, Integer, String, Float, Boolean, BigInteger, DateTime
from ..database import Base


class TokenUsageRecord(Base):
    __tablename__ = "token_usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    function_name = Column(String(100), nullable=False, index=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    model = Column(String(50), nullable=False)
    timestamp = Column(BigInteger, nullable=False, index=True)  # epoch milliseconds
    success = Column(Boolean, default=True)
    duration_ms = Column(Float, default=0.0)
    error_message = Column(String(2000), nullable=True)