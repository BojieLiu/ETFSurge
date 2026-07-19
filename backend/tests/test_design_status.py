"""Tests for design status endpoint (Plan B)"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_status_completed():
    """design_text non-null → status=completed, alive=False"""
    from app.routers.portfolio import get_design_status
    
    mock_design = AsyncMock()
    mock_design.id = 1
    mock_design.created_at = datetime.utcnow() - timedelta(seconds=60)
    mock_design.design_text = "# Test Report"
    
    mock_db = AsyncMock()
    mock_db.get.return_value = mock_design
    
    result = await get_design_status(1, mock_db)
    assert result["status"] == "completed"
    assert result["alive"] is False
    assert result["design_text"] == "# Test Report"

@pytest.mark.asyncio
async def test_status_running():
    """created_at < 300s, no design_text → status=running, alive=True"""
    from app.routers.portfolio import get_design_status
    
    mock_design = AsyncMock()
    mock_design.id = 2
    mock_design.created_at = datetime.utcnow() - timedelta(seconds=30)
    mock_design.design_text = None
    
    mock_db = AsyncMock()
    mock_db.get.return_value = mock_design
    
    result = await get_design_status(2, mock_db)
    assert result["status"] == "running"
    assert result["alive"] is True

@pytest.mark.asyncio
async def test_status_failed():
    """created_at > 300s, no design_text → status=failed, alive=False"""
    from app.routers.portfolio import get_design_status
    
    mock_design = AsyncMock()
    mock_design.id = 3
    mock_design.created_at = datetime.utcnow() - timedelta(seconds=600)
    mock_design.design_text = None
    
    mock_db = AsyncMock()
    mock_db.get.return_value = mock_design
    
    result = await get_design_status(3, mock_db)
    assert result["status"] == "failed"
    assert result["alive"] is False

@pytest.mark.asyncio
async def test_status_not_found():
    """design_id not in DB → status=not_found"""
    from app.routers.portfolio import get_design_status
    
    mock_db = AsyncMock()
    mock_db.get.return_value = None
    
    result = await get_design_status(999, mock_db)
    assert result["status"] == "not_found"
    assert result["alive"] is False
