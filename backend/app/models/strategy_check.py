"""
策略检查历史记录模型
Strategy check history model
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

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

    # round24 R5: 结构化兜底标识——兜底不再只能靠逐条 source=rule 或 summary 文本识读。
    # llm_layer_ok=False + is_fallback=True 时前端显式标注「LLM 层降级，规则引擎兜底」。
    llm_layer_ok = Column(String(8), nullable=True, default="true")
    is_fallback = Column(String(8), nullable=True, default="false")
    report_quality = Column(String(16), nullable=True, default="full")

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "capital": self.capital,
            # P2-4 (round9 §4.2-4): 详情输出 portfolio_type（worker 持久化后不再是 None）
            "portfolio_type": self.portfolio_type,
            "summary": self.summary,
            "market_regime": self.market_regime,
            "suggestions": json.loads(str(self.suggestions_json)) if self.suggestions_json else [],
            "holdings_analysis": json.loads(str(self.holdings_json)) if self.holdings_json else [],
            "risk_warnings": json.loads(str(self.risk_warnings_json)) if self.risk_warnings_json else [],
            "report_text": self.report_text or "",
            "type": "check",
            # round24 R5: 结构化兜底标识透传
            "llm_layer_ok": (self.llm_layer_ok or "true") == "true",
            "is_fallback": (self.is_fallback or "false") == "true",
            "report_quality": self.report_quality or "full",
        }
