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

    # 方案状态: completed / running / failed
    status = Column(String(20), nullable=False, default="completed")
    error_message = Column(Text, nullable=True)

    # 报告质量分级: pending / full / fallback / none
    report_quality = Column(String(16), nullable=False, default="pending")
    # 报告生成完成时间戳
    report_generated_at = Column(DateTime, nullable=True)
