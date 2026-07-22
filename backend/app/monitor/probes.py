"""Centralized health probe registration for all data sources.

All probe functions are lazy-imported and time-bounded.
Probe names must match SourceRegistry source names for shared circuit-breaker state.
"""

from ..services.source_health import register_probe


def register_all_probes() -> None:
    """Register all 6 data-source health probes.

    Each probe is a simple pass/fail check with an appropriate timeout.
    Probes run every 120s via the health_loop in main.py.
    """

    # ── C1: mootdx (8s) ──────────────────────────────────────────
    from ..fetchers.china_market import _mootdx_realtime

    def _probe_mootdx():
        result = _mootdx_realtime(["510050"])
        return bool(result and any(r.get("price", 0) > 0 for r in result))
    register_probe("mootdx", _probe_mootdx, timeout=8)

    # ── C2: Sina (10s) ──────────────────────────────────────────
    from ..fetchers.china_market import _sina_realtime

    def _probe_sina():
        result = _sina_realtime(["510050"], "A")
        return bool(result and any(r.get("price", 0) > 0 for r in result))
    register_probe("sina", _probe_sina, timeout=10)

    # ── C3: Tencent / QQ (10s) ─────────────────────────────────
    from ..fetchers.china_market import _tencent_realtime

    def _probe_tencent():
        result = _tencent_realtime(["510050"], "A")
        return bool(result and any(r.get("price", 0) > 0 for r in result))
    register_probe("tencent", _probe_tencent, timeout=10)

    # ── C4: akshare (15s) — use history endpoint, minimal load ──
    def _probe_akshare():
        try:
            # Lazy import to avoid startup overhead
            import akshare as ak  # type: ignore[import-untyped]
            df = ak.stock_zh_a_hist("510050", period="daily")
            return df is not None and len(df) > 0
        except Exception:
            return False
    register_probe("akshare", _probe_akshare, timeout=15)

    # ── C5: levistock (10s) — sector endpoint ──────────────────
    def _probe_levistock():
        try:
            import levistock as lv  # type: ignore[import-untyped]
            data = lv.sector_em("industry")
            return data is not None and len(data) > 0
        except Exception:
            return False
    register_probe("levistock", _probe_levistock, timeout=10)

    # ── C6: 东方财富 / dongfang (8s) — HK realtime ──────────
    from ..fetchers.china_market import _em_hk_realtime

    def _probe_dongfang():
        result = _em_hk_realtime(["00700"])
        return bool(result and any(r.get("price", 0) > 0 for r in result))
    register_probe("dongfang", _probe_dongfang, timeout=8)
