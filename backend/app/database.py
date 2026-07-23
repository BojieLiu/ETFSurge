import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from .config import settings

_db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
_db_dir = os.path.dirname(_db_path)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

# SQLite 连接超时 30s：防止并发写操作（APScheduler + 用户请求）死锁
engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"timeout": 30},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        from .models.portfolio import PortfolioETF
        from .models.search import Instrument, Sector, Index
        from .models.portfolio_design import PortfolioDesign
        from .models.strategy_check import StrategyCheckRecord
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)


def _migrate(conn):
    from sqlalchemy import inspect, text
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("portfolio_etfs")]
    if "portfolio_type" not in columns:
        conn.execute(text("ALTER TABLE portfolio_etfs ADD COLUMN portfolio_type VARCHAR(20) NOT NULL DEFAULT 'on_exchange'"))
    if "short_name" not in columns:
        conn.execute(text("ALTER TABLE portfolio_etfs ADD COLUMN short_name VARCHAR(60)"))
    # Cost basis columns (for cumulative P&L tracking)
    if "avg_cost" not in columns:
        conn.execute(text("ALTER TABLE portfolio_etfs ADD COLUMN avg_cost FLOAT"))
    if "shares_held" not in columns:
        conn.execute(text("ALTER TABLE portfolio_etfs ADD COLUMN shares_held FLOAT"))
    if "first_buy_date" not in columns:
        conn.execute(text("ALTER TABLE portfolio_etfs ADD COLUMN first_buy_date DATE"))
    if "last_trade_date" not in columns:
        conn.execute(text("ALTER TABLE portfolio_etfs ADD COLUMN last_trade_date DATE"))
    # PortfolioDesign.design_text (LLM 报告持久化)
    columns_design = [c["name"] for c in inspector.get_columns("portfolio_designs")]
    if "design_text" not in columns_design:
        conn.execute(text("ALTER TABLE portfolio_designs ADD COLUMN design_text TEXT"))
    if "status" not in columns_design:
        conn.execute(text("ALTER TABLE portfolio_designs ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'completed'"))
    if "error_message" not in columns_design:
        conn.execute(text("ALTER TABLE portfolio_designs ADD COLUMN error_message TEXT"))
    # StrategyCheckRecord.portfolio_type (added alongside on_exchange/off_exchange support)
    columns_check = [c["name"] for c in inspector.get_columns("strategy_check_records")]
    if "portfolio_type" not in columns_check:
        conn.execute(text("ALTER TABLE strategy_check_records ADD COLUMN portfolio_type VARCHAR(20)"))
