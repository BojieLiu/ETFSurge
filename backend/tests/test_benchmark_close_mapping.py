"""
O19 (docs/round7-rediagnosis.md §7 P20-②): tracking_error 指数映射补全。

_WIDE_BASIS_INDEX_CODES 只映射 6 只老宽基（510300/510500/510050/588000/159915/510880），
A50(563080)/A100(562000)/A500(560600) 等新宽基无指数映射 → benchmark_close 注入不到 →
tracking_error 因「无基准序列」no_data。

修复: 补新宽基映射 + 候选池宽基家族完整性门禁（防下次新增宽基漏配）。
"""

import asyncio
import json
from pathlib import Path

import pytest

from app.services.market_data_hub import market_data_hub


class TestBenchmarkCloseMapping:
    @pytest.mark.asyncio
    async def test_new_wide_basis_injected(self, monkeypatch):
        """560600/563080/562000 进 _enrich_symbol_extra → 注入 benchmark_close（close[-20:]）。"""
        calls = {"bench": 0}

        async def fake_get_market_history(symbol, asset_type="A", period="daily"):
            calls["bench"] += 1
            return [
                {"date": f"2026-07-{d:02d}", "close": 4000.0 + d}
                for d in range(1, 25)
            ]

        def fake_fetch_etf_shares_outstanding(symbol):
            return None  # 份额数据不参与本用例

        monkeypatch.setattr(market_data_hub, "get_market_history", fake_get_market_history)
        import app.fetchers.china_market as cm
        monkeypatch.setattr(cm, "fetch_etf_shares_outstanding", fake_fetch_etf_shares_outstanding)
        market_data_hub._FUND_SHARES_CACHE.clear()

        out = await market_data_hub._enrich_symbol_extra(
            ["560600", "563080", "562000", "563020"],
            {s: {} for s in ("560600", "563080", "562000", "563020")},
        )
        for sym in ("560600", "563080", "562000", "563020"):
            assert "benchmark_close" in out[sym], f"{sym} 未注入 benchmark_close"
            assert len(out[sym]["benchmark_close"]) == 20, f"{sym} benchmark_close 长度 {len(out[sym]['benchmark_close'])}"
        assert calls["bench"] >= 4

    def test_mapping_table_has_new_codes(self):
        """映射表直接包含新宽基符号。"""
        m = market_data_hub._WIDE_BASIS_INDEX_CODES
        assert m.get("560600") == "sh000510", "560600 中证A500 → sh000510"
        assert m.get("563080") == "sh932000", "563080 中证A50 → sh932000"
        assert m.get("562000") == "sh000903", "562000 中证A100 → sh000903"
        assert "563020" in m, "563020 红利低波应已登记"
        assert "159338" in m, "159338 深市中证A500（公共底仓锚）应已登记"

    def test_candidate_pool_wide_basis_families_covered(self):
        """候选池快照出现的宽基按指数家族归一化后必须已登记（防新增宽基漏配）。

        语义门禁: 扫 etf_list_cache.json 快照，名称/tracked_index 命中宽基关键词的
        标的按家族分组（A500/A50/A100/沪深300/上证50/上证180/深证100/中证800/
        中证500/红利低波/科创50/创业板），每个家族须有 ≥1 个映射登记。
        """
        cache_path = Path(__file__).parent.parent / "app" / "data" / "etf_list_cache.json"
        if not cache_path.exists():
            pytest.skip("etf_list_cache.json 快照不存在（本地无缓存时跳过）")
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        etfs = data.get("etfs", []) if isinstance(data, dict) else data

        # 家族 → 家族关键词（名称/tracked_index 子串）
        FAMILY_KEYWORDS = {
            "A500": ("A500", "中证A500"),
            "A50": ("A50", "中证A50"),
            "A100": ("A100", "中证A100"),
            "沪深300": ("沪深300",),
            "上证50": ("上证50",),
            "上证180": ("上证180",),
            "深证100": ("深证100",),
            "中证800": ("中证800",),
            "中证500": ("中证500",),
            "红利低波": ("红利低波",),
            "科创50": ("科创50",),
            "创业板": ("创业板",),
        }
        mapped = market_data_hub._WIDE_BASIS_INDEX_CODES
        # 家族 → 快照中出现的符号
        family_symbols: dict[str, set[str]] = {k: set() for k in FAMILY_KEYWORDS}
        for item in etfs:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol", ""))
            text = f"{item.get('name', '')}{item.get('tracked_index', '')}"
            for fam, kws in FAMILY_KEYWORDS.items():
                if any(k in text for k in kws):
                    family_symbols[fam].add(sym)
        missing = []
        for fam, syms in family_symbols.items():
            if not syms:
                continue
            if not any(s in mapped for s in syms):
                missing.append(f"{fam}({sorted(syms)[:5]})")
        assert not missing, f"候选池宽基家族未登记映射: {missing}"
