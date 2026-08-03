"""F23: pytest socket 拦截门禁的行为测试。

背景（round6 诊断 §17.2）：pre-commit pytest 曾因真实网络访问挂起 ~1 小时。
修复：conftest 提供 autouse socket 拦截 fixture —— 默认禁止非白名单网络访问
（快速 FAIL 而非无限挂起），白名单 localhost/127.0.0.1 放行，
显式 `@pytest.mark.network` 的测试恢复真实网络。

本文件是"门禁自身的元测试"：断言拦截确实生效、白名单确实放行、
network 标记确实恢复。
"""
import socket

import pytest

from conftest import NetworkBlockedError

# 断言测试基线的外部地址（不会真的连上——拦截应先于连接抛出）
_EXTERNAL_HOST = "8.8.8.8"
_EXTERNAL_PORT = 53


def test_socket_connect_external_blocked():
    """socket.socket().connect() 到外部地址应抛 NetworkBlockedError（而非挂起）。"""
    s = socket.socket()
    try:
        with pytest.raises(NetworkBlockedError):
            s.connect((_EXTERNAL_HOST, _EXTERNAL_PORT))
    finally:
        s.close()


def test_socket_connect_ex_blocked():
    """connect_ex 到外部地址同样被拦截。"""
    s = socket.socket()
    try:
        with pytest.raises(NetworkBlockedError):
            s.connect_ex((_EXTERNAL_HOST, _EXTERNAL_PORT))
    finally:
        s.close()


def test_create_connection_external_blocked():
    """socket.create_connection 到外部地址被拦截（requests/urllib3 底层路径）。"""
    with pytest.raises(NetworkBlockedError):
        socket.create_connection((_EXTERNAL_HOST, _EXTERNAL_PORT), timeout=1)


def test_getaddrinfo_external_blocked():
    """外部域名 DNS 解析被拦截。"""
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 80)


def test_gethostbyname_external_blocked():
    """外部主机名解析被拦截。"""
    with pytest.raises(NetworkBlockedError):
        socket.gethostbyname("example.com")


def test_localhost_allowed():
    """白名单 localhost 不触发拦截（getaddrinfo 可正常解析）。"""
    results = socket.getaddrinfo("localhost", 80)
    assert results, "localhost 应能解析"


def test_loopback_allowed():
    """127.0.0.1 不触发拦截。"""
    results = socket.getaddrinfo("127.0.0.1", 8000)
    assert results


def test_error_message_actionable():
    """拦截错误信息应给出可操作的修复指引（mock 或 @pytest.mark.network）。"""
    try:
        socket.getaddrinfo("example.com", 80)
    except NetworkBlockedError as e:
        msg = str(e)
        assert "NetworkBlocked" in msg or "拦截" in msg
        assert "network" in msg or "mock" in msg.lower()
    else:
        pytest.fail("外部解析应被拦截")


@pytest.mark.network
def test_network_marker_allows_real_network():
    """@pytest.mark.network 标记后真实网络可用（不抛 NetworkBlockedError）。

    离线环境 DNS 失败（OSError）可接受——关键断言是"不再被门禁拦截"。
    """
    try:
        socket.getaddrinfo("example.com", 80)
    except OSError:
        pass
