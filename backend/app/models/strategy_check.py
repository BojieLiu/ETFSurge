"""
策略检查历史记录模型
Strategy check history model
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from ..database import Base


class StrategyCheckRecord(Base):
    __tablename__ = "strategy_check_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    capital = Column(Float, nullable=False, default=500000)
    portfolio_type = Column(String(20), nullable=True, comment="on_exchange|off_exchange|null=all")

    # LLM 分析结果
    summary = Column(Text, nullable=True)
    market_regime = Column(String(20), nullable=True)

    # JSON: list[StrategySuggestion]
    suggestions_json = Column(Text, nullable=True)

    # JSON: list[holdings_analysis dicts]
    holdings_json = Column(Text, nullable=True)

    # JSON: list[risk_warnings dicts]
    risk_warnings_json = Column(Text, nullable=True)

    # Q02: Full LLM-generated report text (matching portfolio_designs.design_text)
    # Q02: Full LLM-generated report text (matching portfolio_designs.design_text)
    report_text = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "capital": self.capital,
            "summary": self.summary,
            "market_regime": self.market_regime,
            "suggestions": json.loads(str(self.suggestions_json)) if self.suggestions_json else [],
            "holdings_analysis": json.loads(str(self.holdings_json)) if self.holdings_json else [],
            "risk_warnings": json.loads(str(self.risk_warnings_json)) if self.risk_warnings_json else [],
            "report_text": self.report_text or "",
            "type": "check",
        }
