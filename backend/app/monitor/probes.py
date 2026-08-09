"""Centralized health probe registration for all data sources.

All probe functions are lazy-imported and time-bounded.
Probe names must match SourceRegistry source names for shared circuit-breaker state.
"""

from ..services.source_health import register_probe


def register_all_probes() -> None:
    """Register all 5 data-source health probes.

    Each probe is a simple pass/fail check with an appropriate timeout.
    Probes run every 120s via the health_loop in main.py.
    """

    # ── C1: Sina (10s) ──────────────────────────────────────────
    from ..fetchers.china_market import _sina_realtime

    def _probe_sina():
        result = _sina_realtime(["510050"], "A")
        return bool(result and any(r.get("price", 0) > 0 for r in result))
    register_probe("sina", _probe_sina, timeout=10)

    # ── C2: Tencent / QQ (10s) ─────────────────────────────────
    from ..fetchers.china_market import _tencent_realtime

    def _probe_tencent():
        result = _tencent_realtime(["510050"], "A")
        return bool(result and any(r.get("price", 0) > 0 for r in result))
    register_probe("tencent", _probe_tencent, timeout=10)

    # ── C3: akshare (15s) — use sector endpoint (system-actual function) ──
    def _probe_akshare():
        try:
            # Lazy import to avoid startup overhead
            # Use stock_sector_spot_em (板块热点) which is the actual function
            # used by the system via sector_fetcher, not stock_zh_a_hist
            import akshare as ak  # type: ignore[import-untyped]
            df = ak.stock_sector_spot_em()
            return df is not None and len(df) > 0
        except Exception:
            return False
    register_probe("akshare", _probe_akshare, timeout=15)

    # ── C4: levistock (10s) — sector endpoint ──────────────────
    def _probe_levistock():
        try:
            import levistock as lv  # type: ignore[import-untyped]
            data = lv.sector_em("industry")
            return data is not None and len(data) > 0
        except Exception:
            return False
    register_probe("levistock", _probe_levistock, timeout=10)

    # ── C5: 东方财富 / dongfang (8s) — HK realtime ──────────
    from ..fetchers.china_market import _em_hk_realtime

    def _probe_dongfang():
        result = _em_hk_realtime(["00700"])
        return bool(result and any(r.get("price", 0) > 0 for r in result))
    register_probe("dongfang", _probe_dongfang, timeout=8)

    # ── T1: 主线程池健康 (1s) ──────────────────────────────────
    from ..core.async_utils import get_thread_pool_stats

    def _probe_main_pool():
        stats = get_thread_pool_stats()
        shared = stats.get("shared_executor", {})
        alive = shared.get("alive_threads", 0)
        max_w = shared.get("max_workers", 32)
        # 活跃线程超过 80% 即视为不健康
        return alive <= max_w * 0.8
    register_probe("threadpool_main", _probe_main_pool, timeout=1)

    # ── T2: akshare 专用线程池健康 (1s) ───────────────────────
    from ..services.market_data_hub import market_data_hub

    def _probe_akshare_pool():
        stats = market_data_hub.get_akshare_pool_stats()
        alive = stats.get("alive_threads", 0)
        max_w = stats.get("max_workers", 4)
        return alive <= max_w * 0.8
    register_probe("threadpool_akshare", _probe_akshare_pool, timeout=1)
