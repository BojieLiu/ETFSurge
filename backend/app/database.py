import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from .config import settings

_db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
_db_dir = os.path.dirname(_db_path)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

engine = create_async_engine(settings.database_url, echo=False)
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
