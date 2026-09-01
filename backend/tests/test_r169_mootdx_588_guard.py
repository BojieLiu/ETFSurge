"""R169 (round51): mootdx 对科创板 ETF 588xxx 实时报价 x10 防护.

根因 (tdxpy 0.2.7 源码级): helper.get_security_type 两位前缀分类表无 '58' 段
-> NotImplementedError 被吞 -> get_security_coefficient 回退 0.01 (SH_FUND 正确
0.001) -> price_raw x 0.01 = x10. price 与 last_close 同源同错, 无法单源自检.

修复: _mootdx_realtime provider 层对 588 前缀返回空 -> fetch_a_stock_realtime /
fetch_a_stock_batch 降级链自动落 tencent/sina (正确源).

负向断言 (文档要求): 588xxx 不允许出现 mootdx 返回 (x10 污染源必须被拦截);
纯 588 批次 _mootdx_realtime 必须空; 混合批次只保留非 588.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.fetchers import china_market as cm


def test_mootdx_realtime_skips_588_prefix():
    """588 前缀在 mootdx provider 层被剔除, 不进入 client.quotes."""
    # mock 掉 client 层, 捕获实际传给 quotes 的 symbols
    fake_client = MagicMock()
    fake_client.quotes.return_value = MagicMock(empty=True)
    with patch.object(cm, "_mootdx", return_value=fake_client), \
         patch.object(cm, "_run_mootdx_with_timeout",
                      side_effect=lambda fn: fn()):
        cm._mootdx_realtime(["588000", "588130", "159338"])
        called = fake_client.quotes.call_args.kwargs["symbol"]
        assert "588000" not in called, f"588000 应被剔除: {called}"
        assert "588130" not in called, f"588130 应被剔除: {called}"
        assert "159338" in called, f"非 588 应保留: {called}"


def test_mootdx_realtime_all_588_returns_empty():
    """纯 588 批次 -> 空 -> _filtered 返回 None -> 降级链继续下一源."""
    fake_client = MagicMock()
    with patch.object(cm, "_mootdx", return_value=fake_client), \
         patch.object(cm, "_run_mootdx_with_timeout",
                      side_effect=lambda fn: fn()):
        out = cm._mootdx_realtime(["588000", "588130"])
        assert out == [], f"纯 588 批次应空列表: {out}"
        fake_client.quotes.assert_not_called(), "不应发起任何 mootdx 请求"


def test_mootdx_realtime_non_588_unaffected():
    """非 588 标的照常走 mootdx (不误伤正常路径)."""
    fake_client = MagicMock()
    row = {"code": "159338", "price": 1.221, "last_close": 1.223,
           "volume": 100, "amount": 122.1}
    df = MagicMock()
    df.empty = False
    df.iterrows.return_value = iter([(0, row)])
    fake_client.quotes.return_value = df
    with patch.object(cm, "_mootdx", return_value=fake_client), \
         patch.object(cm, "_run_mootdx_with_timeout",
                      side_effect=lambda fn: fn()):
        out = cm._mootdx_realtime(["159338"])
        assert len(out) == 1
        assert out[0]["symbol"] == "159338"
        assert abs(out[0]["price"] - 1.221) < 1e-9
