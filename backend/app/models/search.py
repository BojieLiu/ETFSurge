"""搜索/下拉用的本地标的数据表（性能优化，避免每次搜索都直连 akshare/levistock）。

- instruments: 股票/ETF/指数/期货 的基础信息，供搜索、自动补全
- sectors:    行业/概念板块，供行情分析下拉框
- indices:    全球主流指数，供 Dashboard 指数面板（替代硬编码 _GLOBAL_INDEX_DEFS）
- indices_meta: 所有指数元数据（A股/港股/行业/概念/宽基/策略等），供搜索/下拉/分析入口
"""

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text
from ..database import Base

from datetime import datetime


class Instrument(Base):
    """可搜索标的（股票/ETF/指数/期货）。"""

    __tablename__ = "instruments"

    symbol = Column(String(20), primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    market = Column(String(10), nullable=False)        # 'A','HK','US','gold','oil','silver'...
    asset_type = Column(String(10), nullable=False)    # 'stock','etf','index','futures'
    pinyin = Column(String(100), index=True)           # 拼音全拼，用于首字母搜索
    first_letter = Column(String(5), index=True)       # 拼音首字母（如 'P'，'PA'）
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Sector(Base):
    """行业/概念板块（供下拉框）。"""

    __tablename__ = "sectors"

    code = Column(String(20), primary_key=True)        # 'BK0447' / 'BK1645'
    name = Column(String(100), nullable=False, index=True)
    type = Column(String(10), nullable=False)          # 'industry' | 'concept'
    updated_at = Column(DateTime, default=datetime.utcnow)


class Index(Base):
    """全球主流指数（供 Dashboard 指数面板）。"""

    __tablename__ = "indices"

    symbol = Column(String(20), primary_key=True)
    name = Column(String(100), nullable=False)
    region = Column(String(20), nullable=False)        # 'A股','港股','美股','日经','韩国'
    asset_type = Column(String(10), default="index")
    currency = Column(String(3), default="CNY")
    source = Column(String(20))                        # 'akshare','yfinance','stooq'
    is_active = Column(Boolean, default=True)


class IndexMeta(Base):
    """指数元数据（全市场指数：A股/港股/行业/概念/宽基/策略/债券等），供搜索/下拉/分析入口。"""

    __tablename__ = "indices_meta"

    symbol = Column(String(20), primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    market = Column(String(10), nullable=False)        # 'A','HK','US','CN'...
    category = Column(String(20), nullable=False)      # 'broad','industry','concept','strategy','bond','commodity'
    index_type = Column(String(20))                    # 'price','total_return','equal_weight' 等
    source = Column(String(20))                        # 'sina','ths','csindex','yfinance'
    pinyin = Column(String(100), index=True)           # 拼音全拼，用于首字母搜索
    first_letter = Column(String(5), index=True)       # 拼音首字母（如 'P'，'PA'）
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Watchlist(Base):
    """用户自选/关注列表。"""

    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True, unique=True)
    name = Column(String(100), nullable=False)
    asset_type = Column(String(10), nullable=False, default="A")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
