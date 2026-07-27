"""
Tests for GET /portfolio/designs endpoint (P4-2).

Verifies:
  - Response is a list
  - Every item has required fields: id, created_at, capital, risk_profile, status, error_message
  - error_message is either a string or null
  - status is "completed" or "failed"
  - DB layer is mocked so no real data is needed
"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime


@pytest.fixture
def mock_db_session():
    """Create a fully mocked AsyncSession that returns test records."""
    import sqlalchemy.ext.asyncio

    # Create mock records that look like PortfolioDesign ORM instances
    class MockDesign:
        """Simulates a PortfolioDesign ORM row with attributes."""
        def __init__(self, id, created_at, capital, risk_profile, status, error_message):
            self.id = id
            self.created_at = created_at
            self.capital = capital
            self.risk_profile = risk_profile
            self.status = status
            self.error_message = error_message
            self.strategies_json = None  # Needed by list_designs for etf_count

    mock_records = [
        MockDesign(
            id=1,
            created_at=datetime(2024, 1, 15, 10, 30, 0),
            capital=500000.0,
            risk_profile="balanced",
            status="completed",
            error_message=None,
        ),
        MockDesign(
            id=2,
            created_at=datetime(2024, 1, 14, 14, 0, 0),
            capital=1000000.0,
            risk_profile="aggressive",
            status="failed",
            error_message="Insufficient candidates for aggressive profile",
        ),
        MockDesign(
            id=3,
            created_at=datetime(2024, 1, 13, 9, 15, 0),
            capital=300000.0,
            risk_profile="conservative",
            status="completed",
            error_message=None,
        ),
    ]

    # Mock the execute method — execute() returns a Result, and result.scalars().all()
    # is a synchronous call, not async.
    class MockScalars:
        def all(self):
            return mock_records

    class MockResult:
        def scalars(self):
            return MockScalars()

    mock_execute = AsyncMock()
    mock_execute.return_value = MockResult()

    # Build the mock session
    session = AsyncMock(spec=sqlalchemy.ext.asyncio.AsyncSession)
    session.execute = mock_execute

    return session, mock_records


@pytest.mark.asyncio
async def test_list_designs_returns_list(mock_db_session):
    """Response from list_designs must be a list."""
    session, _ = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    assert isinstance(result, list), f"Expected list, got {type(result)}"


@pytest.mark.asyncio
async def test_list_designs_required_fields(mock_db_session):
    """Every item in the response must contain all required fields."""
    session, _ = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    required_fields = {"id", "created_at", "capital", "risk_profile", "status", "error_message"}
    for item in result:
        missing = required_fields - set(item.keys())
        assert not missing, f"Item {item.get('id')} missing fields: {missing}"


@pytest.mark.asyncio
async def test_list_designs_error_message_type(mock_db_session):
    """error_message must be either a string or null (None)."""
    session, _ = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    for item in result:
        em = item.get("error_message")
        assert em is None or isinstance(em, str), (
            f"error_message should be str or None, got {type(em)}: {em!r}"
        )


@pytest.mark.asyncio
async def test_list_designs_status_values(mock_db_session):
    """status must be 'completed' or 'failed'."""
    session, _ = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    valid_statuses = {"completed", "failed"}
    for item in result:
        assert item.get("status") in valid_statuses, (
            f"Item {item.get('id')} has invalid status: {item.get('status')!r}"
        )


@pytest.mark.asyncio
async def test_list_designs_all_records_returned(mock_db_session):
    """All mock records should appear in the response."""
    session, mock_records = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    assert len(result) == len(mock_records), (
        f"Expected {len(mock_records)} records, got {len(result)}"
    )


@pytest.mark.asyncio
async def test_list_designs_error_message_preserved():
    """A failed design with an error_message must preserve the message string."""
    import sqlalchemy.ext.asyncio
    from unittest.mock import AsyncMock

    class MockDesign:
        def __init__(self, id, created_at, capital, risk_profile, status, error_message):
            self.id = id
            self.created_at = created_at
            self.capital = capital
            self.risk_profile = risk_profile
            self.status = status
            self.error_message = error_message
            self.strategies_json = None

    failed_record = MockDesign(
        id=99,
        created_at=datetime(2024, 2, 1, 8, 0, 0),
        capital=200000.0,
        risk_profile="aggressive",
        status="failed",
        error_message="Provider timeout; no response from LLM",
    )

    class MockScalars:
        def all(self):
            return [failed_record]

    class MockResult:
        def scalars(self):
            return MockScalars()

    mock_execute = AsyncMock()
    mock_execute.return_value = MockResult()

    session = AsyncMock(spec=sqlalchemy.ext.asyncio.AsyncSession)
    session.execute = mock_execute

    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    assert len(result) == 1
    assert result[0]["error_message"] == "Provider timeout; no response from LLM"
    assert result[0]["status"] == "failed"
