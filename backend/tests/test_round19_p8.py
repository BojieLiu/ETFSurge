"""
round19 P8（问题 8：港股指数自动补全不全）测试（2026-08-12 实施）：
- _STATIC_EXTRA_INDICES HK 静态段扩展（恒生行业分类/综合行业 10 项/主题指数；
  负向：缺行业指数 → FAIL）
- fetch_index_history HK 分支（字母代码 → 腾讯 hk{code}；负向：字母代码走 A 股
  akshare 链返回空 → FAIL）
"""

import pytest


class TestStaticExtraIndicesHk:
    """round19 P8-①: 静态兜底段 HK 指数扩展。"""

    def test_hk_segment_has_industry_and_theme(self):
        from scripts.sync_indices_meta import _STATIC_EXTRA_INDICES

        hk = [i for i in _STATIC_EXTRA_INDICES if i.get("market") == "HK"]
        symbols = {i["symbol"] for i in hk}
        # 基础 12 条 + 新增行业/主题 18 条 = 30；同步后表行数（新浪 ~25 + 静态）≥40
        assert len(hk) >= 28, f"HK 静态段应 ≥28 条（旧 12 + 行业/主题补齐），实得 {len(hk)}"
        for required in ("HSCI", "HSF", "HSAHC", "HSII", "HSHYLDI", "HSCIF", "HSCIT"):
            assert required in symbols, f"HK 静态段缺 {required}: {sorted(symbols)}"
        # 类别区分
        cats = {i["symbol"]: i.get("category") for i in hk}
        assert cats.get("HSF") == "industry", "恒生金融分类应标 industry"
        assert cats.get("HSAHC") == "theme", "恒生医疗保健应标 theme"
        # 全部 source=static（来源诚实性）
        assert all(i.get("source") == "static" for i in hk)


class TestFetchIndexHistoryHkBranch:
    """round19 P8-③: fetch_index_history 字母代码（HK 指数）走腾讯。"""

    def test_hk_alpha_code_uses_tencent(self, monkeypatch):
        """fetch_index_history('HSCI') → 腾讯 hk{code}（负向：走 A 股 akshare 链
        失败返回空 → FAIL）。"""
        from app.fetchers import china_market as cm

        tx_rows = [{"date": f"2026-08-{i:02d}", "open": 20000 + i, "high": 20100 + i,
                    "low": 19900 + i, "close": 20050 + i, "volume": 1e8} for i in range(1, 8)]
        calls = []
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history",
                            lambda s: (calls.append(s) or tx_rows))
        rows = cm.fetch_index_history("HSCI", "daily")
        assert rows == tx_rows
        assert calls == ["HSCI"], f"应传 'HSCI'（内部拼 hkHSCI），实得 {calls}"

    def test_hk_uncovered_returns_empty(self, monkeypatch):
        """腾讯不覆盖（HSAHC）→ 返回 []（前端标注「暂无行情」，负向：走 A 股链报错 → FAIL）。"""
        from app.fetchers import china_market as cm
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda s: [])
        assert cm.fetch_index_history("HSAHC", "daily") == []

    def test_a_index_keeps_akshare_chain(self, monkeypatch):
        """数字代码（A 股指数）保持原 akshare 链（不误入 HK 分支）。"""
        from app.fetchers import china_market as cm
        import pandas as pd

        a_rows = [{"date": "2026-08-11", "open": 3900.0, "high": 3910.0, "low": 3890.0,
                   "close": 3905.0, "volume": 1e9}]
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history",
                            lambda s: pytest.fail("A 股指数不应走腾讯 HK 分支"))

        df = pd.DataFrame([{"date": "2026-08-11", "open": 3900.0, "high": 3910.0,
                            "low": 3890.0, "close": 3905.0, "volume": 1e9}])
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, **k: df)
        rows = cm.fetch_index_history("000001", "daily")
        assert rows and rows[0]["收盘"] == pytest.approx(3905.0)
