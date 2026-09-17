# -*- coding: utf-8 -*-
"""ValuationHistory model — 估值历史攒分位用（L2 P0）.

market_snapshots 同 kind 只留 2 条，不够算历史分位。
本表按 (kind, key) 留最近 250 个交易日（约 1 年日级），
收盘后由 ValuationMixin 幂等写入（同 as_of 去重）。

kind: "index"（key=指数代码，如 000300）/ "sector"（key=行业编码，如 C39）。
指数列：pe_1/pe_2/div_1/div_2（市盈率1/2、股息率1/2 口径未定，原样存）。
板块列：pe_wavg/pe_median/pe_avg（静态 PE 加权/中位数/算术平均）。
PB/ROE 源缺失（D1 实证），v1 无对应列，不建空列。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from ..database import Base


class ValuationHistory(Base):
    __tablename__ = "valuation_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False, index=True)
    key = Column(String(40), nullable=False, index=True)
    pe_1 = Column(Float, nullable=True)
    pe_2 = Column(Float, nullable=True)
    div_1 = Column(Float, nullable=True)
    div_2 = Column(Float, nullable=True)
    pe_wavg = Column(Float, nullable=True)
    pe_median = Column(Float, nullable=True)
    pe_avg = Column(Float, nullable=True)
    as_of = Column(String(24), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
