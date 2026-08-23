# -*- coding: utf-8 -*-
"""round34 R106: fund_fetcher 收到非代码 symbol——脏映射值穿透到网络层。

根因（round34 §4.4）：etf_index_mapping.json 脏值 `518880 → "黄金9999"`（上金所
现货合约被当作 tracked_index）→ 组合定价链 pricing.py 把「黄金9999」当基金代码传给
fetch_fund_nav → URL 含原始中文 → ascii 编码异常 → WARNING 每 60-120s 周期重放。

修复：① fetch_fund_nav 入口形态守卫（非纯 6 位数字直接 None，fail-fast 不发无效
请求）；② 映射脏值修正（数据侧，见 etf_index_mapping.json）。

无网络：urlopen mock 计数断言。
"""
import json
from unittest.mock import MagicMock

import pytest

from app.fetchers.fund_fetcher import fetch_fund_nav


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


@pytest.fixture()
def urlopen_spy(monkeypatch):
    """替换 urllib.request.urlopen 并统计调用次数（fund_fetcher 模块命名空间）。"""
    import app.fetchers.fund_fetcher as ff

    calls = []

    def _fake_urlopen(req, timeout=None):
        calls.append(getattr(req, "full_url", str(req)))
        return _FakeResponse(json.dumps({
            "Data": {"LSJZList": [{"DWJZ": "1.2345", "JZZZL": "0.56"}]}
        }).encode("utf-8"))

    monkeypatch.setattr(ff.urllib.request, "urlopen", _fake_urlopen)
    return calls


class TestR106NonCodeSymbolGuard:
    @pytest.mark.parametrize("bad_symbol", ["黄金9999", None, "1234567", "51a880", "", "00"])
    def test_non_code_symbol_no_network(self, urlopen_spy, bad_symbol):
        """负向：中文/None/7 位/含字母码 → 不发任何网络请求、返回 None。"""
        result = fetch_fund_nav(bad_symbol)
        assert result is None, f"非代码 symbol 应直接 None，实际 {result}"
        assert len(urlopen_spy) == 0, (
            f"守卫必须 fail-fast（urlopen 调用数应为 0），实际 {urlopen_spy}"
        )

    def test_valid_code_still_fetches(self, urlopen_spy):
        """合法 6 位数字码仍走网络路径并正常解析（守卫不得误伤）。"""
        result = fetch_fund_nav("110011")
        assert result is not None
        assert result["nav"] == pytest.approx(1.2345)
        assert result["daily_change_pct"] == pytest.approx(0.56)
        assert len(urlopen_spy) == 1 and "fundCode=110011" in urlopen_spy[0]
