"""tests 目录共享 fixtures 注册入口（Z27 §8.1 M4）。

pytest 只从 conftest.py 自动发现 fixtures；db_fixtures.py 中的
task_db / task_mgr 通过在此处导入注册为全局可用，供所有测试文件
按名称直接使用（也兼容 `from tests.db_fixtures import task_mgr` 的显式导入）。
"""
from tests.db_fixtures import task_db, task_mgr  # noqa: F401


# ── F21 R73: 共享 mock fixtures 分层 ──────────────────────────────
# 四类高频 mock 统一到 conftest，新测试优先引用，禁止各文件重复手写。
# R75 哨兵：mock 结构必须对齐真实响应（契约对齐下沉到 fixture 层）。

import pandas as pd
import pytest


@pytest.fixture(scope="session", autouse=True)
def _disable_amount_override_network():
    """P0-23 (round16 3.25): 测试环境默认跳过 filter_etfs 实时成交额网络补查
    （避免测试触发 gtimg 网络请求）；P0-23 专项测试显式关闭该开关 + mock 验证。"""
    import os
    os.environ.setdefault("ETF_SKIP_AMOUNT_OVERRIDE", "1")
    yield


def _make_hist_df():
    """与 akshare fund_etf_hist_em 真实列对齐的固定 DataFrame。"""
    return pd.DataFrame({
        "日期": ["2026-01-02", "2026-01-03"],
        "开盘": [3.8, 3.82],
        "收盘": [3.82, 3.85],
        "最高": [3.85, 3.86],
        "最低": [3.79, 3.81],
        "成交量": [100000, 120000],
        "成交额": [380000, 462000],
        "振幅": [1.5, 1.3],
        "涨跌幅": [0.5, 0.8],
        "涨跌额": [0.02, 0.03],
        "换手率": [0.9, 1.1],
    })


@pytest.fixture(autouse=True)
def _clear_sync_memory_cache():
    """P0-4 (round9): watchlist 端级 3s 缓存引入后，测试间共享 SyncMemoryCache 会串扰
    （第一批测试缓存命中，后续测试读到旧数据）。每个测试前后清理缓存保证隔离。"""
    from app.services.cache_service import sync_memory_cache
    sync_memory_cache.clear()
    yield
    sync_memory_cache.clear()


@pytest.fixture(autouse=True)
def _reset_llm_circuit():
    """round23 F7 (LLM 模块级 TTL 熔断): 熔断状态为模块级共享状态（_circuit dict）。

    测试隔离：模拟 429/5xx 的测试会打开对应 provider 的熔断，若不复位会污染
    后序真实/模拟 LLM 测试（所有 provider 被跳过 → `No LLM providers available`）。
    每个测试结束后清空 _circuit，保证各测试独立观测熔断行为。
    """
    yield
    from app.analysis import llm
    llm.reset_circuit()


@pytest.fixture
def mock_akshare(monkeypatch):
    """R73①: akshare 常用函数统一返回固定 DataFrame（走真实解析代码路径）。"""
    import akshare as ak
    monkeypatch.setattr(ak, "fund_etf_hist_em", lambda *a, **k: _make_hist_df())
    monkeypatch.setattr(ak, "fund_open_fund_info_em", lambda *a, **k: _make_hist_df())
    monkeypatch.setattr(ak, "stock_sector_spot_em", lambda *a, **k: pd.DataFrame(),
                        raising=False)
    return ak


@pytest.fixture
def mock_run_sync(monkeypatch):
    """R73③: run_sync 直接同步执行 fn（消除各文件重复的线程池 stub）。"""
    from app.core import async_utils

    async def _direct(call, *args, timeout=None, **kwargs):
        return call(*args, **kwargs)

    monkeypatch.setattr(async_utils, "run_sync", _direct)
    return _direct


@pytest.fixture
def mock_hub(monkeypatch):
    """R73②: market_data_hub 单例方法统一 stub（patch 实例方法，from-import 同样生效）。

    R75 哨兵：get_market_sentiment 返回结构必须含 sentiment_history（对齐
    fundamentals_fetcher.fetch_market_sentiment 真实返回，F19 R68 契约）。
    """
    from app.services import market_data_hub as mdh

    hub = mdh.market_data_hub
    monkeypatch.setattr(hub, "get_market_regime", lambda market="A": "neutral")
    monkeypatch.setattr(hub, "get_market_sentiment",
                        lambda: {"sentiment_index": 50.0,
                                 "sentiment_label": "中性",
                                 "advance_ratio": 0.5,
                                 "sentiment_history": [50.0] * 20})
    monkeypatch.setattr(hub, "get_pool", lambda layer=None: {})
    monkeypatch.setattr(hub, "get_index_realtime", lambda: [])
    monkeypatch.setattr(hub, "get_sector_heat", lambda limit=None: [])
    monkeypatch.setattr(hub, "get_news", lambda: [])
    monkeypatch.setattr(hub, "get_factor_matrix", lambda: {})
    monkeypatch.setattr(hub, "get_history", lambda symbol, market="A", period="daily": None)
    return hub


@pytest.fixture
def mock_registry_health(monkeypatch):
    """R73④: SourceRegistry._health 返回可控 SourceHealth。

    默认全部可用（cooldown_until=0）；测试可改 healthy_names 控制失败源。
    """
    from app.core import source_registry

    def _make_health():
        h = source_registry.SourceHealth()
        h.failures = 0
        h.cooldown_until = 0.0
        return h

    registry = source_registry.registry
    monkeypatch.setattr(registry, "health", lambda name: _make_health())
    return registry
