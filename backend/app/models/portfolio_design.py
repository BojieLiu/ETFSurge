"""
组合设计方案历史记录模型
Portfolio design history model
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from ..database import Base


class PortfolioDesign(Base):
    __tablename__ = "portfolio_designs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    capital = Column(Float, nullable=False, default=500000)
    risk_profile = Column(String(20), nullable=False, default="balanced")

    # 方案 JSON 数据（完整 strategies 数组）
    strategies_json = Column(Text, nullable=False, default="[]")

    # 生成时的市场快照 JSON
    market_snapshot_json = Column(Text, nullable=True)

    # LLM 生成的完整设计报告（Markdown 文本）
    design_text = Column(Text, nullable=True)
