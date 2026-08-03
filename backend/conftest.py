"""Pytest fixtures for the ETF Surge backend.

#6: 不在 conftest 层全局 mock 外部数据源。改为 pool_manager 的 _test_mode
属性来抑制 teardown 时的 HTTP 泄漏（见 market_data_hub.py）。

Tests that need mock should use local pytest fixtures, avoiding session-level
side effects on test isolation.

# F23 (round6 §17.2): autouse socket 拦截 —— 防止测试真实联网导致 commit 卡死。
# 默认替换 socket 为守卫版：非白名单（localhost/127.*）connect / DNS 解析
# 抛 NetworkBlockedError（快速 FAIL 而非无限挂起）；需要真实网络的测试
# 用 `@pytest.mark.network` 显式放行。
"""
import socket as _socket
import types

import pytest

from pytest import fixture

# ── F23: socket 拦截门禁 ─────────────────────────────────────────────
_ORIGINAL_SOCKET = _socket.socket
_ORIGINAL_CREATE_CONNECTION = _socket.create_connection
_ORIGINAL_GETADDRINFO = _socket.getaddrinfo
_ORIGINAL_GETHOSTBYNAME = _socket.gethostbyname
_ORIGINAL_GETHOSTBYNAME_EX = _socket.gethostbyname_ex

_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class NetworkBlockedError(RuntimeError):
    """测试访问真实网络被门禁拦截。请 mock 外部数据源，或标记 @pytest.mark.network。"""


def _is_localhost(host) -> bool:
    if isinstance(host, str):
        host = host.lower()
        if host in _LOCALHOST_HOSTS:
            return True
        if host.startswith("127."):
            return True
    return False


def _guard_address(address) -> None:
    host = address[0] if isinstance(address, tuple) else address
    if _is_localhost(host):
        return
    raise NetworkBlockedError(
        f"测试访问真实网络被拦截: {address!r}。"
        "请 mock 外部数据源，或将测试标记为 @pytest.mark.network 显式放行。"
    )


class _GuardedSocket(_ORIGINAL_SOCKET):
    """真实 socket 的子类——仅拦截非白名单的 connect/connect_ex。

    继承而非代理：isinstance(sock, socket.socket) 与 ssl 包装均不受影响。
    """

    def connect(self, address):
        _guard_address(address)
        return super().connect(address)

    def connect_ex(self, address):
        _guard_address(address)
        return super().connect_ex(address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _is_localhost(host):
        raise NetworkBlockedError(
            f"测试访问真实网络被拦截: getaddrinfo({host!r})。"
            "请 mock 外部数据源，或将测试标记为 @pytest.mark.network 显式放行。"
        )
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


def _guarded_gethostbyname(host):
    if not _is_localhost(host):
        raise NetworkBlockedError(
            f"测试访问真实网络被拦截: gethostbyname({host!r})。"
            "请 mock 外部数据源，或将测试标记为 @pytest.mark.network 显式放行。"
        )
    return _ORIGINAL_GETHOSTBYNAME(host)


def _guarded_gethostbyname_ex(host):
    if not _is_localhost(host):
        raise NetworkBlockedError(
            f"测试访问真实网络被拦截: gethostbyname_ex({host!r})。"
            "请 mock 外部数据源，或将测试标记为 @pytest.mark.network 显式放行。"
        )
    return _ORIGINAL_GETHOSTBYNAME_EX(host)


def _guarded_create_connection(address, *args, **kwargs):
    _guard_address(address)
    return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)


@pytest.fixture(autouse=True)
def _block_real_network(request, monkeypatch):
    """autouse socket 拦截：默认禁止真实网络，@pytest.mark.network 显式放行。"""
    if request.node.get_closest_marker("network") is not None:
        yield
        return
    monkeypatch.setattr(_socket, "socket", _GuardedSocket)
    monkeypatch.setattr(_socket, "create_connection", _guarded_create_connection)
    monkeypatch.setattr(_socket, "getaddrinfo", _guarded_getaddrinfo)
    monkeypatch.setattr(_socket, "gethostbyname", _guarded_gethostbyname)
    monkeypatch.setattr(_socket, "gethostbyname_ex", _guarded_gethostbyname_ex)
    yield


def _make_etf(**kw):
    """Build a lightweight attribute-access object shaped like PortfolioETF."""
    return types.SimpleNamespace(**kw)


@pytest.fixture(autouse=True, scope="session")
def _prevent_pool_teardown_http():
    """#6: 用 market_data_hub._test_mode 抑制 teardown 时的 HTTP 泄漏。

    不再全局 mock em_global_fetcher / sentiment_fetcher，
    让需要使用真实数据的测试能接触到原始数据源。
    """
    import app.services.market_data_hub as mdh
    mdh.market_data_hub._test_mode = True
    yield
    mdh.market_data_hub._test_mode = False


@pytest.fixture
def dummy_portfolio_rows():
    """A small in-memory ETF list shaped like portfolio.models.ETF.

    Objects expose attribute access (.symbol, .target_weight, ...) matching
    the way portfolio_service reads fields.
    """
    return [
        _make_etf(symbol="159338", name="中证A500ETF", short_name="A500ETF",
                  asset_type="A", portfolio_type="on_exchange",
                  target_weight=0.4, tracked_index=None),
        _make_etf(symbol="518880", name="黄金ETF", short_name="黄金ETF",
                  asset_type="A", portfolio_type="on_exchange",
                  target_weight=0.3, tracked_index=None),
        _make_etf(symbol="022449", name="A500联接C", short_name="A500联接C",
                  asset_type="A", portfolio_type="off_exchange",
                  target_weight=0.3, tracked_index="159338"),
    ]
