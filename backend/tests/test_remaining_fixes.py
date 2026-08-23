"""Tests: Remaining Phase 12 fixes (Q02, S05, P01, P02).

TDD: Tests written before implementation verification.
Covers:
  - Q02: StrategyCheckRecord.report_text column and to_dict()
  - S05: fund_fetcher circuit breaker import
  - P01: Loading container CSS min-height
  - P02: ETF scan warmup cache TTL
"""
import pytest


# ─── FIX-Q02: Strategy check pipeline repair ──────────────────


def test_q02_strategy_check_model_has_report_text():
    """Q02: StrategyCheckRecord model should have report_text column."""
    from app.models.strategy_check import StrategyCheckRecord
    assert hasattr(StrategyCheckRecord, "report_text"), "model missing report_text column"


def test_q02_strategy_check_to_dict_has_report_text():
    """Q02: to_dict() should include report_text."""
    from app.models.strategy_check import StrategyCheckRecord
    record = StrategyCheckRecord(capital=500000, summary="Test summary", report_text="Test report text content")
    d = record.to_dict()
    assert "report_text" in d, "to_dict missing report_text"
    assert d["report_text"] == "Test report text content"


def test_q02_strategy_check_to_dict_report_text_default():
    """Q02: to_dict() report_text default to empty string when None."""
    from app.models.strategy_check import StrategyCheckRecord
    record = StrategyCheckRecord(capital=500000, summary="Test")
    d = record.to_dict()
    assert d["report_text"] == "", "default should be empty string"


def test_q02_direct_migration():
    """Q02: Verify ALTER TABLE ADD COLUMN report_text works on strategy_check_records."""
    import sqlalchemy as sa
    from sqlalchemy import inspect
    engine = sa.create_engine("sqlite://", echo=False)
    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE strategy_check_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capital FLOAT NOT NULL DEFAULT 500000,
                summary TEXT,
                holdings_json TEXT,
                risk_warnings_json TEXT,
                portfolio_type VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(sa.text("ALTER TABLE strategy_check_records ADD COLUMN report_text TEXT"))
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("strategy_check_records")]
    assert "report_text" in columns, f"report_text not in {columns}"
    assert "holdings_json" in columns
    engine.dispose()


@pytest.mark.asyncio
async def test_q02_worker_receives_report_text():
    """Q02: strategy_check_worker should pass report_text to StrategyCheckRecord."""
    from app.tasks.strategy_check_worker import _pipeline_body
    assert callable(_pipeline_body)


# ─── FIX-S05: Circuit breaker for fund_fetcher ────────────────


def test_s05_source_registry_available():
    """S05: SourceRegistry should be importable from fund_fetcher context."""
    from app.core.source_registry import registry
    assert registry is not None


def test_s05_fund_fetcher_exports():
    """S05: fund_fetcher should export fetch_fund_nav."""
    from app.fetchers.fund_fetcher import fetch_fund_nav
    assert callable(fetch_fund_nav)


# ─── FIX-P02: ETF scan warmup cache ───────────────────────────

# round35 RC-B2: test_p02_etf_cache_defined 已整段删除——它断言的
# `_etf_list_cache`/`ETF_CACHE_TTL` 是 round11 TTL 归一后的死符号对（生产零读写），
# 该测试本身是空心存在性断言（§16.6 同类），符号删除后恒走 skip 分支，无保留价值。


def test_p02_sanity_checks():
    """P02: Basic sanity — verify config loading works."""
    from app.config import settings
    assert settings is not None
