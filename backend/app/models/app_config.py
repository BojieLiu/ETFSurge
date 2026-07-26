"""AppConfig model — runtime key-value configuration persisted to SQLite."""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, func
from ..database import Base


class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
