"""LLM health check & global liquidity — split from analysis/llm.py (Batch 2)."""

import asyncio
import time

from app.analysis.provider import ProviderConfig, get_configured_providers, has_any_api_key
from app.core.logging import get_logger

logger = get_logger(__name__)

async def llm_health_check(timeout: float = 15.0) -> dict:
    """Probe every configured LLM provider and return a structured health report.

    Returns a dict with overall `status` ("ok" / "degraded" / "no_key"),
    `has_api_key`, `checked_at` and a `providers` list. Failures are reported
    structurally (never raised), so the endpoint always returns 200.
    """
    import httpx

    checked_at = time.time()
    if not has_any_api_key():
        return {
            "status": "no_key",
            "checked_at": checked_at,
            "has_api_key": False,
            "providers": [],
        }

    providers = get_configured_providers()
    if not providers:
        return {
            "status": "no_key",
            "checked_at": checked_at,
            "has_api_key": False,
            "providers": [],
        }

    async def _probe(provider: ProviderConfig) -> dict:
        body = {
            "model": provider.model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0.0,
            "max_tokens": 16,
        }
        _start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(
                    provider.api_url,
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                msg = (data.get("choices") or [{}])[0].get("message", {})
                # content may be empty for reasoning models with tiny max_tokens;
                # the probe only cares that the API responded with a valid message.
                has_content = "content" in msg or "reasoning_content" in msg
                if not has_content:
                    raise ValueError("provider returned no message")
                latency = (time.monotonic() - _start) * 1000
                return {
                    "id": provider.id,
                    "name": provider.name,
                    "model": provider.model,
                    "ok": True,
                    "latency_ms": round(latency, 1),
                    "status": "available",
                    "error": None,
                }
        except Exception as _exc:
            latency = (time.monotonic() - _start) * 1000
            status = "timeout" if isinstance(_exc, (httpx.TimeoutException, asyncio.TimeoutError)) else "error"
            return {
                "id": provider.id,
                "name": provider.name,
                "model": provider.model,
                "ok": False,
                "latency_ms": round(latency, 1),
                "status": status,
                "error": str(_exc),
            }

    results = await asyncio.gather(*(_probe(p) for p in providers), return_exceptions=True)
    # gather never raises (each _probe catches), but guard anyway
    providers_out = []
    for r in results:
        if isinstance(r, Exception):
            providers_out.append({
                "id": "unknown", "name": "unknown", "model": "unknown",
                "ok": False, "latency_ms": 0.0, "status": "error", "error": str(r),
            })
        elif isinstance(r, dict):
            providers_out.append(r)

    overall = "ok" if any(p["ok"] for p in providers_out) else "degraded"
    return {
        "status": overall,
        "checked_at": checked_at,
        "has_api_key": True,
        "providers": providers_out,
    }
async def _fetch_global_liquidity() -> dict | None:
    """P1-5 (R4-23): FRED 海外流动性采集——美债10Y/VIX/联邦基金利率。

    任一指标失败静默（该键不注入）；全部失败/无 API key 返回 None。
    首期仅 3 个指标（CPI/非农暂不接入，控制 prompt 长度）。
    """
    try:
        import asyncio as _asyncio

        from ...fetchers.global_markets_fetcher import (
            fetch_fed_rate,
            fetch_us_10y,
            fetch_vix,
        )
        _us10, _vix, _fed = await _asyncio.wait_for(
            _asyncio.gather(
                fetch_us_10y(), fetch_vix(), fetch_fed_rate(),
                return_exceptions=True,
            ),
            timeout=15,
        )
        gl: dict[str, float] = {}
        for _k, _v in (("us_10y", _us10), ("vix", _vix), ("fed_rate", _fed)):
            if isinstance(_v, float):
                gl[_k] = round(_v, 2)
        return gl or None
    except Exception as e:
        logger.debug("[llm] _fetch_global_liquidity failed (non-fatal): %s", e)
        return None
