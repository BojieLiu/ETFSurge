# -*- coding: utf-8 -*-
"""round35 §12-P0-3 / §11-T-① 配套 — 关停时 K 线缓存落盘（flush_kline_cache）。

背景：main.py lifespan shutdown 段以 ``getattr(hub, "flush_kline_cache", None)``
防御性调用，但该方法此前不存在 → 永久静默 no-op（假完成形态）。
本测试钉死：① 方法真实存在且为协程函数；② 落盘产生真实非空文件；
③ 空缓存 no-op 不抛错。
"""
import asyncio
import json
import os

import app.services.hub._kline as _kline_mod
from app.config import settings


def _fresh_hub(tmp_path, monkeypatch):
    """data_dir 指向 tmp + 重置路径缓存，返回干净 KlineMixin 实例。"""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    _kline_mod.KlineMixin._KLINE_CACHE_PERSIST_PATH = None
    return _kline_mod.KlineMixin()


async def test_flush_persists_real_nonempty_file(monkeypatch, tmp_path):
    """正向：有缓存行时 flush 必须在 settings.data_dir 下生成内容正确的 JSON
    （反假完成第 2 条——「没报错」不算数，要看到真实文件与真实值）。"""
    hub = _fresh_hub(tmp_path, monkeypatch)
    hub._kline_cache_rows = {"510300": [{"date": "2026-08-21", "close": 3.9}]}
    hub._kline_cache_ts = 1750000000.0
    hub._kline_cache_symbols = ["510300"]

    await asyncio.wait_for(hub.flush_kline_cache(), timeout=15)

    path = os.path.join(str(tmp_path), "kline_cache.json")
    assert os.path.isfile(path), f"落盘文件未生成: {path}"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["rows"]["510300"][0]["close"] == 3.9  # 内容断言，非仅存在性
    assert data["ts"] == 1750000000.0


def test_shutdown_path_resolves_flush_method():
    """负向（抓假完成）：main.py 关停段的 getattr 防御必须能解析到**真实存在的
    协程方法**——若有人删掉 flush_kline_cache，本断言红，防止再次退化为静默 no-op。
    """
    from app.services.market_data_hub import market_data_hub

    fn = getattr(market_data_hub, "flush_kline_cache", None)
    assert callable(fn), "hub.flush_kline_cache 缺失——§12-P0-3 关停落盘已退化为 no-op"
    assert asyncio.iscoroutinefunction(fn)


async def test_flush_empty_cache_is_clean_noop(monkeypatch, tmp_path):
    """边界：空缓存 flush 不抛错、不产生文件（_persist 的早退语义保持）。"""
    hub = _fresh_hub(tmp_path, monkeypatch)
    hub._kline_cache_rows = {}  # 行式容器由宿主 __init__ 初始化；mixin 单测显式给空

    await asyncio.wait_for(hub.flush_kline_cache(), timeout=15)

    assert not os.path.isfile(os.path.join(str(tmp_path), "kline_cache.json"))
