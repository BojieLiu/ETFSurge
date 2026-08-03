"""
R5-2-6: 东财 push2 双源路由（push2 优先 → push2delay 兜底）。

- _fetch_em_etf_list(host) 参数化：host 透传到 URL。
- fetch_all_etfs_base 的 eastmoney provider 内部 registry.route 双源路由。
mock requests，无网络。
"""
from unittest.mock import patch

from app.fetchers import etf_scanner


class _FakeResp:
    def __init__(self, diff, total=None):
        self._diff = diff
        self._total = total if total is not None else len(diff)

    def json(self):
        return {"data": {"total": self._total, "diff": self._diff}}


def _diff(n):
    return [
        {"f12": f"51{n:04d}", "f14": f"ETF{n}", "f2": 1.0, "f3": 0.1,
         "f62": 0.5, "f72": 100, "f184": 10, "f45": 1000, "f66": 10,
         "f115": 1.0, "f168": "", "f84": 5, "f85": 100}
        for n in range(1, n + 1)
    ]


def test_fetch_em_list_host_param_passed_to_url():
    """host 参数化：_fetch_em_etf_list(host) 把域名拼进 URL（push2/push2delay 两域名）。"""
    seen_hosts = []

    def _fake_get(url, timeout=5, headers=None):
        seen_hosts.append(url)
        return _FakeResp(_diff(2))

    with patch("requests.get", side_effect=_fake_get):
        etf_scanner._fetch_em_etf_list("push2.eastmoney.com")
        etf_scanner._fetch_em_etf_list("push2delay.eastmoney.com")

    assert any("push2.eastmoney.com" in u for u in seen_hosts), \
        f"应请求 push2 域名: {seen_hosts}"
    assert any("push2delay.eastmoney.com" in u for u in seen_hosts), \
        f"应支持 push2delay 域名: {seen_hosts}"


def test_fetch_em_list_pushes_user_agent_and_referer():
    """补 User-Agent + Referer（行情页），抗东财 UA 校验。"""
    seen = {}

    def _fake_get(url, timeout=5, headers=None):
        seen["headers"] = headers
        return _FakeResp(_diff(1))

    with patch("requests.get", side_effect=_fake_get):
        etf_scanner._fetch_em_etf_list("push2.eastmoney.com")
    h = seen.get("headers", {})
    assert "Mozilla" in h.get("User-Agent", ""), "应带浏览器 UA"
    assert "eastmoney" in h.get("Referer", ""), "应带东财 Referer"


def test_fetch_em_list_delay_fallback_via_dual_source():
    """双源路由：push2 返回 None → push2delay 接管（模拟 fetch_all_etfs_base 内部 eastmoney provider）。

    直接验证 _fetch_em_etf_list 两域名均可独立取数（解析层零改动），
    熔断路由切换由 registry.route 负责（SourceRegistry 单测已覆盖）。
    """
    order = []

    def _fake_get(url, timeout=5, headers=None):
        order.append("push2.eastmoney.com" if "push2.eastmoney.com" in url else "push2delay.eastmoney.com")
        # push2 首页返回空（限流窗口）→ push2delay 返回数据
        if "push2.eastmoney.com" in url:
            return _FakeResp([], total=0)
        return _FakeResp(_diff(60))

    with patch("requests.get", side_effect=_fake_get):
        r_push2 = etf_scanner._fetch_em_etf_list("push2.eastmoney.com")
        r_delay = etf_scanner._fetch_em_etf_list("push2delay.eastmoney.com")

    assert r_push2 is None, "push2 空响应 → None（触发 registry 切下一源）"
    assert r_delay and len(r_delay) == 60, "push2delay 应正常返回数据"
