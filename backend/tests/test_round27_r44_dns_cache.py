"""R44 — _ipv4_getaddrinfo DNS 缓存验收（负向断言）。

根因（round27 §1 / §15.2 R44）：warmup 期间 _fetch_us_list 等经 urllib 反复调用
socket.getaddrinfo，每次都走真实 DNS（实测 ~226 次 / 13.7s）。修复：在
_ipv4_getaddrinfo 内记忆化 (host, port) -> 解析结果，命中缓存不再调用底层真实
解析器。

负向断言核心：同一 host 第二次解析时，底层真实 getaddrinfo（config 中捕获的
_original_getaddrinfo，即 monkey-patch 之前的 socket.getaddrinfo）只被调用一次。

注意：conftest 的 F23 socket 门禁会包裹 socket.getaddrinfo；本测试不依赖真实网络——
直接 patch config._original_getaddrinfo（=捕获的原始真实解析器），由 MagicMock 接管，
断言其调用次数。
"""
import unittest.mock as mock

import pytest

import app.config as config


@pytest.fixture(autouse=True)
def _clear_dns_cache():
    """每个用例前清空 DNS 缓存，避免跨用例污染。"""
    config._dns_cache.clear()
    yield
    config._dns_cache.clear()


def test_dns_cache_avoids_second_real_resolution():
    """同一 host 第二次解析命中缓存，底层真实 getaddrinfo 仅调用一次。"""
    fake_result = [("family", "socktype", "proto", "canon", ("1.2.3.4", 80))]

    with mock.patch.object(config, "_original_getaddrinfo", autospec=True) as real_resolve:
        real_resolve.return_value = fake_result

        # 第一次：缓存未命中 -> 调用真实解析器
        r1 = config._ipv4_getaddrinfo("stock.finance.sina.com.cn", 80)
        # 第二次：同 host -> 应命中缓存，不再调用真实解析器
        r2 = config._ipv4_getaddrinfo("stock.finance.sina.com.cn", 80)

    # 关键负向断言：底层真实 DNS 只被调用一次（第二次走缓存）
    assert real_resolve.call_count == 1, (
        f"DNS 缓存失效：底层 getaddrinfo 被调用 {real_resolve.call_count} 次，"
        "期望 1 次（第二次应命中缓存）"
    )
    # 两次返回同一缓存对象
    assert r1 is r2 is fake_result


def test_dns_cache_keyed_by_host_port_isolation():
    """不同 host / port 视为独立键，各自触发一次真实解析。"""
    fake = [("family", "socktype", "proto", "canon", ("9.9.9.9", 80))]

    with mock.patch.object(config, "_original_getaddrinfo", autospec=True) as real_resolve:
        real_resolve.return_value = fake

        config._ipv4_getaddrinfo("host-a.example.com", 80)
        config._ipv4_getaddrinfo("host-a.example.com", 80)  # 命中缓存
        config._ipv4_getaddrinfo("host-b.example.com", 80)  # 新 host -> 真实解析
        config._ipv4_getaddrinfo("host-a.example.com", 443)  # 新 port -> 真实解析

    # host-a:80 命中一次; host-b:80 一次; host-a:443 一次 = 3 次
    assert real_resolve.call_count == 3


def test_ipv4_family_forced_on_cache_miss():
    """缓存未命中时，真实解析仍强制 AF_INET（IPv4 优先策略不被破坏）。"""
    fake = [("family", "socktype", "proto", "canon", ("1.1.1.1", 80))]

    with mock.patch.object(config, "_original_getaddrinfo", autospec=True) as real_resolve:
        real_resolve.return_value = fake
        config._ipv4_getaddrinfo("push2delay.eastmoney.com", 80, family=0)

    # 入参 family 被忽略，真实解析始终收到 socket.AF_INET
    args, kwargs = real_resolve.call_args
    assert args[2] == __import__("socket").AF_INET
