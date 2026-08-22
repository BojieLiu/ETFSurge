"""R102 (round33 §8) — Sina K-line datalen 窗口守卫。

根因：`_sina_history_cb` 硬编码 `datalen=240` → ETF 日线仅 ~240 根（~1 年）→
IC 历史回填 distinct trade_date 卡 245 < MIN_TRADING_DAYS(250)，因子恒「积累中」。
探针实证（round33 §8.1）：新浪 `datalen` 给多少返多少，无 240 上限（500/1023/1500 全返）。

修复口径：
- 日线 datalen 240→500（~2 年，IC 回填走日频需要 ≥250 交易日样本）；
- weekly/monthly/intraday 不参与因子计算，保持 240 避免无谓大 payload；
- **scale 与 datalen 是两个不同含义的 240**：scale=240 是「日线粒度」，勿动。

验证边界（D3）：本测试 mock `_session` + `registry.route`，不触网，任意时段可跑。
"""
import pytest


class _FakeResp:
    text = "[]"


class _FakeSession:
    headers: dict = {}

    def get(self, url, timeout=None):
        self.last_url = url
        return _FakeResp()


@pytest.fixture()
def _capture_url(monkeypatch):
    """拦截 HTTP 会话与熔断路由，捕获 _sina_history_cb 实际构造的 URL。"""
    sess = _FakeSession()
    monkeypatch.setattr("app.fetchers.china_market._session", lambda: sess)
    from app.core.source_registry import registry as _reg

    def _fake_route(chain, **kwargs):
        return chain[0][1]()  # 直调首个源的 call，绕过熔断计数

    monkeypatch.setattr(_reg, "route", _fake_route)
    return sess


class TestR102SinaDatalen:
    def test_sina_daily_datalen_500(self, _capture_url):
        """日线 datalen 应为 500（R102 核心断言）。"""
        from app.fetchers.china_market import _sina_history_cb

        assert _sina_history_cb("510300", "daily") == []
        url = _capture_url.last_url
        assert "datalen=500" in url, f"日线 datalen 应扩至 500（R102），实际 URL：{url}"

    def test_sina_non_daily_datalen_stays_240(self, _capture_url):
        """weekly/monthly/intraday 不参与因子计算，保持 240（防无谓大 payload）。"""
        from app.fetchers.china_market import _sina_history_cb

        for period in ("weekly", "monthly", "15m", "30m", "1h"):
            _sina_history_cb("510300", period)
            assert "datalen=240" in _capture_url.last_url, (
                f"{period} datalen 应保持 240，实际 URL：{_capture_url.last_url}"
            )

    def test_sina_daily_scale_unchanged(self, _capture_url):
        """负向：scale=240 是日线粒度语义，与 datalen 无关——严禁被连带改动。"""
        from app.fetchers.china_market import _sina_history_cb

        _sina_history_cb("510300", "daily")
        assert "scale=240" in _capture_url.last_url, (
            f"scale（粒度）勿动，实际 URL：{_capture_url.last_url}"
        )
