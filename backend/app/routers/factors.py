"""Factor analysis and IC tracking routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from ..core.logging import get_logger
from ..factors.factor_registry import registry

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/factors", tags=["factors"])


def _get_factor_name(code: str) -> str:
    """Extract a simple name from factor code."""
    parts = code.split(".")
    if len(parts) >= 2:
        raw = parts[-1].replace("_", " ")
        return raw[:1].upper() + raw[1:]
    return code


def _get_factor_category(code: str) -> str:
    """Extract category prefix from factor code."""
    parts = code.split(".")
    return parts[0] if parts else "unknown"


@router.get("/ic")
async def get_factor_ic() -> dict[str, Any]:
    """Return current IC values for all core factors.

    Data comes from FactorRegistry._last_ic_batch, which is updated
    automatically after each compute() call when market_data is available.
    """
    ic_batch = registry._last_ic_batch

    factors = [
        {
            "code": code,
            "name": _get_factor_name(code),
            "category": _get_factor_category(code),
            "ic_value": round(val, 4),
            "sample_count": None,  # not available from current batch data
        }
        for code, val in sorted(ic_batch.items())
        if abs(val) > 0.0
    ]

    return {
        "factors": factors,
        "total": len(factors),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
