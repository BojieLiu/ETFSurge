import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
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

# round35 A1 (docs/round35-architecture-review.md §13.9 T-A1): portfolio.db 双写者
# （async engine + hub/_common.py 裸 sqlite3 快照）此前无 WAL——读写互斥时裸连接
# 直接撞 "database is locked"。journal_mode=WAL 对既有 DB 为在线操作免迁移，且持久化
# 到 DB 文件（设一次全局生效）；busy_timeout 是 per-connection 属性，须每次 connect 设。
# R139 (round38): WAL 模式在并发写入后多次 page corruption（清空重建后 2h 再次
# malformed），改为 DELETE 模式 + synchronous=FULL 牺牲并发性能换取写入完整性。
# 若进程内频现 "database is locked" 再考虑切回 WAL + synchronous=FULL 组合。
from sqlalchemy import event


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _rec):  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=DELETE")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA synchronous=FULL")
    cur.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)
    # Phase 6.1.3: initialize ConfigManager with DB session factory
    from .core.config_manager import config_manager
    config_manager.init(async_session)


def _migrate(conn):
    from sqlalchemy import inspect, text
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("portfolio_etfs")]
    if "portfolio_type" not in columns:
        conn.execute(text("ALTER TABLE portfolio_etfs ADD COLUMN portfolio_type VARCHAR(20) NOT NULL DEFAULT 'on_exchange'"))
    if "short_name" not in columns:
        conn.execute(text("ALTER TABLE portfolio_etfs ADD COLUMN short_name VARCHAR(60)"))
    # ── portfolio_designs: report_quality + report_generated_at (design-check-pipeline-redesign) ──
    design_cols = [c["name"] for c in inspector.get_columns("portfolio_designs")]
    if "report_quality" not in design_cols:
        conn.execute(text("ALTER TABLE portfolio_designs ADD COLUMN report_quality VARCHAR(16) NOT NULL DEFAULT 'pending'"))
    if "report_generated_at" not in design_cols:
        conn.execute(text("ALTER TABLE portfolio_designs ADD COLUMN report_generated_at TIMESTAMP"))
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
    # Q02: strategy_check_records.report_text
    if "report_text" not in columns_check:
        conn.execute(text("ALTER TABLE strategy_check_records ADD COLUMN report_text TEXT"))
    # round24 R5: 结构化兜底标识（llm_layer_ok / is_fallback / report_quality）
    if "llm_layer_ok" not in columns_check:
        conn.execute(text("ALTER TABLE strategy_check_records ADD COLUMN llm_layer_ok VARCHAR(8) DEFAULT 'true'"))
    if "is_fallback" not in columns_check:
        conn.execute(text("ALTER TABLE strategy_check_records ADD COLUMN is_fallback VARCHAR(8) DEFAULT 'false'"))
    if "report_quality" not in columns_check:
        conn.execute(text("ALTER TABLE strategy_check_records ADD COLUMN report_quality VARCHAR(16) DEFAULT 'full'"))
    # round19 P7-③ (2026-08-12): watchlist 存量清洗——历史手动输入可能带 sh/sz/bj
    # 前缀（如 sz301308）导致 fetch_history 0 行；统一为不带前缀规范（幂等）。
    try:
        conn.execute(text(
            "UPDATE watchlist SET symbol = substr(symbol, 3) "
            "WHERE lower(symbol) LIKE 'sh%' AND length(symbol) > 2 "
            "OR lower(symbol) LIKE 'sz%' AND length(symbol) > 2 "
            "OR lower(symbol) LIKE 'bj%' AND length(symbol) > 2"
        ))
    except Exception:
        pass  # watchlist 表不存在（首次建库）时跳过
    # F15 (round23 §3.3): 存量孤立 avg_cost 清洗——「有成本无份额」（verify_e2e 曾实锤
    # 20 条半成本持仓）落库路径已拦截，此处清历史残留（幂等，可反复执行）。
    try:
        conn.execute(text(
            "UPDATE portfolio_etfs SET avg_cost = NULL "
            "WHERE avg_cost IS NOT NULL AND (shares_held IS NULL OR shares_held <= 0)"
        ))
    except Exception:
        pass  # portfolio_etfs 表不存在（首次建库）时跳过
    # F25① (round23 §8): factor_ic_records 日频重构——trade_date/signal_absent 列 +
    # (factor_code, trade_date) 唯一索引 + 旧注水数据清空重建。
    # 决策（2026-08-14 §8 F25 设计要点②）：旧 4306 行 × 18 天是「刷新次数冒充交易日」
    # 的注水数据，无统计含义，必须清空，否则污染 count(distinct trade_date) 与 t/IR。
    try:
        ic_cols = [c["name"] for c in inspector.get_columns("factor_ic_records")]
        if "trade_date" not in ic_cols:
            conn.execute(text("ALTER TABLE factor_ic_records ADD COLUMN trade_date DATE"))
        if "signal_absent" not in ic_cols:
            conn.execute(text("ALTER TABLE factor_ic_records ADD COLUMN signal_absent BOOLEAN DEFAULT 0"))
        # 旧格式行（trade_date 为 NULL）→ 清空重建（F25 决策②）
        legacy = conn.execute(text(
            "SELECT COUNT(*) FROM factor_ic_records WHERE trade_date IS NULL"
        )).scalar()
        if legacy:
            conn.execute(text("DELETE FROM factor_ic_records"))
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_factor_ic_code_date "
                "ON factor_ic_records (factor_code, trade_date)"
            ))
        except Exception:
            pass  # 索引已存在/不支持时幂等跳过
    except Exception:
        pass  # factor_ic_records 表不存在（首次建库）时跳过
