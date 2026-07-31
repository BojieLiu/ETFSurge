"""Test Z05: SSL connection pool reuse in global markets fetcher.

Covers:
1. Shared httpx.Client singleton (same instance across calls)
2. _http_get_json routes through shared client
3. Connection pool stats exposed (handshakes/reused)
4. /admin/sources/connection-pool endpoint exists and returns stats
"""
import pytest
from unittest.mock import MagicMock, patch


class _FakeResponse:
    def __init__(self, data=None):
        self._data = data or {}
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class TestSharedClient:
    """Z05: shared httpx.Client singleton."""

    def test_shared_client_singleton(self):
        """Same instance returned across calls."""
        from app.fetchers import global_markets_fetcher as gmf

        # reset singleton for deterministic test
        gmf._shared_client = None
        c1 = gmf._get_shared_client()
        c2 = gmf._get_shared_client()
        assert c1 is c2
        gmf._shared_client = None  # cleanup

    def test_http_get_json_uses_shared_client(self):
        """_http_get_json routes through the shared client."""
        from app.fetchers import global_markets_fetcher as gmf

        fake_client = MagicMock()
        fake_client.get.return_value = _FakeResponse({"ok": True})

        with patch.object(gmf, "_get_shared_client", return_value=fake_client):
            result = gmf._http_get_json("https://example.com/api")

        assert result == {"ok": True}
        fake_client.get.assert_called_once()
        # URL + UA header passed
        args, kwargs = fake_client.get.call_args
        assert kwargs.get("headers", {}).get("User-Agent")

    def test_http_get_json_failure_returns_none(self):
        """Network failure -> None (no crash)."""
        from app.fetchers import global_markets_fetcher as gmf

        fake_client = MagicMock()
        fake_client.get.side_effect = Exception("connection refused")

        with patch.object(gmf, "_get_shared_client", return_value=fake_client):
            assert gmf._http_get_json("https://example.com/api") is None

    def test_connection_pool_stats_shape(self):
        """get_connection_pool_stats returns handshakes/reused numbers."""
        from app.fetchers import global_markets_fetcher as gmf

        fake_pool = MagicMock()
        fake_pool.num_connections = 3
        fake_transport = MagicMock()
        fake_transport._pool = fake_pool
        fake_client = MagicMock()
        fake_client._transport = fake_transport

        with patch.object(gmf, "_get_shared_client", return_value=fake_client):
            stats = gmf.get_connection_pool_stats()

        assert stats["handshakes"] == 3
        assert stats["reused"] >= 0

    def test_connection_pool_stats_failure_fallback(self):
        """Pool stats failure -> zeros, no crash."""
        from app.fetchers import global_markets_fetcher as gmf

        fake_client = MagicMock()
        fake_client._transport = None  # introspection fails

        with patch.object(gmf, "_get_shared_client", return_value=fake_client):
            stats = gmf.get_connection_pool_stats()
        assert stats["handshakes"] == 0
        assert stats["reused"] == 0


class TestAdminEndpoint:
    """Z05: /admin/sources/connection-pool endpoint."""

    def test_admin_connection_pool_route_exists(self):
        """Route handler exists in admin router."""
        from app.routers.admin import get_connection_pool

        assert callable(get_connection_pool)

    @pytest.mark.asyncio
    async def test_admin_connection_pool_returns_stats(self):
        """Endpoint returns handshakes/reused keys."""
        from app.routers.admin import get_connection_pool
        from app.fetchers import global_markets_fetcher as gmf

        with patch.object(gmf, "get_connection_pool_stats",
                          return_value={"handshakes": 2, "reused": 5}):
            result = await get_connection_pool()
        assert result["handshakes"] == 2
        assert result["reused"] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])