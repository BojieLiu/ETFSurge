"""R6-F1 (round6 §三/§十 R6-02): mootdx 容器可用性修复。

背景：`_mootdx()` 无 server 参数时依赖 `~/.mootdx/config.json` BESTIP 缓存，
全新环境（容器/CI）无该文件 → Quotes.factory 空转 → 降级链第一环空转
（report A 309s / 策略检查持仓加载 55s / 预热 6.2s）。
修复：config 缺失时显式传入已知可用 fallback server（容器实测 0.35s 可用）。
"""
import pytest

from app.fetchers import china_market as cm


def test_fallback_servers_constant():
    """fallback 服务器常量存在且为 (host, port) 格式。"""
    assert cm._MOOTDX_FALLBACK_SERVERS
    host, port = cm._MOOTDX_FALLBACK_SERVERS[0]
    assert isinstance(host, str) and host
    assert isinstance(port, int) and port > 0


def test_has_mootdx_config_true_when_file_exists(monkeypatch, tmp_path):
    """~/.mootdx/config.json 存在时判定 True（走默认路径不回归）。"""
    cfg_dir = tmp_path / ".mootdx"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text("{}", encoding="utf-8")

    class _FakeHome:
        def __init__(self, p):
            self.p = p

        def __truediv__(self, other):
            return self.p / other

    monkeypatch.setattr(cm.Path, "home", staticmethod(lambda: _FakeHome(tmp_path)))
    assert cm._has_mootdx_config() is True


def test_has_mootdx_config_false_when_missing(monkeypatch, tmp_path):
    """无 config.json（全新环境）时判定 False → 触发 fallback。"""

    class _FakeHome:
        def __init__(self, p):
            self.p = p

        def __truediv__(self, other):
            return self.p / other

    monkeypatch.setattr(cm.Path, "home", staticmethod(lambda: _FakeHome(tmp_path)))
    assert cm._has_mootdx_config() is False


def test_mootdx_no_config_uses_fallback_server(monkeypatch):
    """config 缺失（容器/CI）→ Quotes.factory 显式收到 fallback server。"""
    from mootdx.quotes import Quotes

    calls = {}

    def fake_factory(market="std", **kwargs):
        calls["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cm, "_MOOTDX_CLIENT", None)
    monkeypatch.setattr(cm, "_has_mootdx_config", lambda: False)
    monkeypatch.setattr(Quotes, "factory", staticmethod(fake_factory))

    client = cm._mootdx()
    assert client is not None
    assert calls["kwargs"].get("server") == cm._MOOTDX_FALLBACK_SERVERS[0]
    # 恢复全局缓存，避免影响其他测试
    monkeypatch.setattr(cm, "_MOOTDX_CLIENT", None)


def test_mootdx_with_config_keeps_default_path(monkeypatch):
    """config 存在（宿主机）→ factory 不显式传 server（默认路径不回归）。"""
    from mootdx.quotes import Quotes

    calls = {}

    def fake_factory(market="std", **kwargs):
        calls["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cm, "_MOOTDX_CLIENT", None)
    monkeypatch.setattr(cm, "_has_mootdx_config", lambda: True)
    monkeypatch.setattr(Quotes, "factory", staticmethod(fake_factory))

    cm._mootdx()
    assert "server" not in calls["kwargs"]
    monkeypatch.setattr(cm, "_MOOTDX_CLIENT", None)
