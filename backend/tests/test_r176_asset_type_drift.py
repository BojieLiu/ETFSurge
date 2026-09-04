# -*- coding: utf-8 -*-
"""R176 (round52 §7.3 方案E-1): portfolio_etfs.asset_type 写入口径漂移。

round52 §7.1: 9-1 持仓重灌（3fb66b1）的 seed CSV 第 4 列写 `asset_type='ETF'`，
而 pricing 全链路（`_split_symbols:172-174` / `allocation.py:77` 基本面分支）
只认 `asset_type == 'A'` → 带 `portfolio_type` 过滤请求（页面 tab 切场内/场外）
的 15 只场内 ETF **四个分支全空** → `price_map` 空 → 现价/涨跌幅全 0（¥0.00/+0.00%）。
无类型查询时靠场外 15 只的 tracked_index 批量捎带才「看起来正常」（掩盖缺陷）。

方案 E-1（数据侧，推荐）：写入口径统一为 `'A'`（pricing/hub 既定口径），
DB 存量 15 只订正 + 全部写入点归一 + 漂移守卫。

负向断言（能失败的）：
- normalize_asset_type('ETF') 必须为 'A'（漂移值不得穿透到 DB）；
- portfolio 包内不得再出现 `asset_type="ETF"` 字面写入（防再漂移）；
- CSV 导入 asset_type=ETF 的行，落库必须是 'A'；
- 订正脚本只动 ETF→A，不得误伤 HK/US（订正范围守卫）。

无网络：纯函数 + sqlite 临时库。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services.portfolio.pricing import _split_symbols, normalize_asset_type


class TestNormalizeAssetType:
    @pytest.mark.parametrize("raw,expected", [
        ("ETF", "A"),
        ("etf", "A"),
        (" ETF ", "A"),
        ("A", "A"),
        ("A-SHARE", "A"),
        ("a-share", "A"),
        ("", "A"),
        (None, "A"),
        ("HK", "HK"),
        ("US", "US"),
    ])
    def test_aliases(self, raw, expected):
        assert normalize_asset_type(raw) == expected

    def test_unknown_value_passes_through(self):
        """未知值原样保留（不做臆断归一），但仍 strip/upper。"""
        assert normalize_asset_type(" bond ") == "BOND"


class TestSplitSymbolsCoversNormalizedType:
    def test_a_rows_enter_a_batch(self):
        """场内 ETF（asset_type='A'）必须进入 A 股批量（否则现价恒 0）。"""
        etfs = [
            {"symbol": "159338", "asset_type": "A", "tracked_index": None},
            {"symbol": "588200", "asset_type": "A", "tracked_index": None},
        ]
        a_symbols, hk, us, tracked_a = _split_symbols(etfs)
        assert a_symbols == ["159338", "588200"], f"场内 ETF 必须入 A 股批量，实际 {a_symbols}"

    def test_off_exchange_tracked_index_joins_batch(self):
        """场外联接的 tracked_index（场内代码）一并入批量（round34-B7 既有语义不变）。"""
        etfs = [{"symbol": "022449", "asset_type": "A", "tracked_index": "159338"}]
        a_symbols, *_ = _split_symbols(etfs)
        assert "159338" in a_symbols


def test_no_etf_literal_writes_in_portfolio_package():
    """漂移守卫：portfolio 包内不得再写 `asset_type="ETF"`（9-1 重灌同型回归）。"""
    pkg = Path(__file__).resolve().parent.parent / "app" / "services" / "portfolio"
    offenders = []
    for f in pkg.glob("*.py"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):  # 注释里的历史说明不算写入
                continue
            if 'asset_type="ETF"' in line or "asset_type='ETF'" in line:
                offenders.append(f"{f.name}:{line.strip()[:60]}")
    assert offenders == [], f"portfolio 包内仍有 ETF 字面写入（口径会再漂移）: {offenders}"


class TestImportPortfolioNormalizes:
    @pytest.mark.asyncio
    async def test_csv_etf_row_stored_as_a(self):
        """CSV 导入 asset_type=ETF → 落库 'A'（seed CSV 同型不再灌错）。"""
        from app.services.portfolio.transfer import import_portfolio

        captured: list[object] = []

        class FakeDb:
            def add(self, obj):
                captured.append(obj)

            async def flush(self):
                pass

            async def commit(self):
                pass

        csv_content = (
            "symbol,name,asset_type,portfolio_type,target_weight\n"
            "510300,沪深300ETF,ETF,on_exchange,0.1\n"
        )
        from unittest.mock import AsyncMock, patch

        with patch("app.services.portfolio_service.list_etfs", new=AsyncMock(return_value=[])):
            result = await import_portfolio(FakeDb(), csv_content)
        assert result["imported"] == 1 and result["errors"] == []
        assert captured and captured[0].asset_type == "A", (
            f"导入的 asset_type 必须归一为 'A'，实际 {getattr(captured[0], 'asset_type', None)!r}"
        )


# ── 存量数据订正脚本 ────────────────────────────────────────────

def _make_db(tmp_path: Path, rows) -> str:
    path = tmp_path / "portfolio.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE portfolio_etfs (id INTEGER PRIMARY KEY, symbol TEXT, "
        "portfolio_type TEXT, asset_type TEXT)"
    )
    conn.executemany(
        "INSERT INTO portfolio_etfs (symbol, portfolio_type, asset_type) VALUES (?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return str(path)


def _load_script():
    import importlib.util
    import sys

    script = Path(__file__).resolve().parent.parent / "scripts" / "fix_asset_type_drift.py"
    mod_name = "_fix_asset_type_drift_dut"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestFixAssetTypeDriftScript:
    def _rows(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            return dict(conn.execute(
                "SELECT symbol, asset_type FROM portfolio_etfs").fetchall())
        finally:
            conn.close()

    def test_dry_run_reports_without_writing(self, tmp_path):
        db = _make_db(tmp_path, [
            ("159338", "on_exchange", "ETF"),
            ("022449", "off_exchange", "A"),
            ("00700", "on_exchange", "HK"),
        ])
        mod = _load_script()
        report = mod.normalize_db_asset_types(db, apply=False)
        assert report["matched"] == ["159338"], f"只应命中 ETF 漂移行，实际 {report['matched']}"
        assert report["updated"] == 0, "dry-run 不得写库"
        assert self._rows(db)["159338"] == "ETF", "dry-run 后 DB 应保持不变"

    def test_apply_fixes_only_etf_rows(self, tmp_path):
        """负向：订正只动 ETF→A，HK/US/A 不得被误伤。"""
        db = _make_db(tmp_path, [
            ("159338", "on_exchange", "ETF"),
            ("510300", "on_exchange", "ETF"),
            ("022449", "off_exchange", "A"),
            ("00700", "on_exchange", "HK"),
            ("AAPL", "on_exchange", "US"),
        ])
        mod = _load_script()
        report = mod.normalize_db_asset_types(db, apply=True)
        assert report["updated"] == 2, f"应订正 2 行，实际 {report['updated']}"
        rows = self._rows(db)
        assert rows["159338"] == "A" and rows["510300"] == "A"
        assert rows["022449"] == "A"
        assert rows["00700"] == "HK", "HK 持仓不得被订正"
        assert rows["AAPL"] == "US", "US 持仓不得被订正"

    def test_idempotent_second_run(self, tmp_path):
        db = _make_db(tmp_path, [("159338", "on_exchange", "ETF")])
        mod = _load_script()
        assert mod.normalize_db_asset_types(db, apply=True)["updated"] == 1
        assert mod.normalize_db_asset_types(db, apply=True)["updated"] == 0, "二次运行应幂等（0 更新）"

    def test_missing_table_is_reported_not_crashed(self, tmp_path):
        """负向：表不存在 → 结构化报错而非 traceback（脚本可安全在非项目库上跑）。"""
        db = _make_db(tmp_path, [])
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE portfolio_etfs")
        conn.commit()
        conn.close()
        mod = _load_script()
        report = mod.normalize_db_asset_types(db, apply=True)
        assert report["updated"] == 0
        assert "error" in report, "缺表必须结构化回报"
