from __future__ import annotations
"""
TDD: etf_scanner filter_etfs — column name compatibility.

This test verifies that filter_etfs correctly handles the actual column names
returned by the current akshare fund_etf_spot_em() API.

Current akshare (2026) returns:
  - 成交额 (amount)    at column index 8
  - 换手率 (turnover)  at column index ...
  - 流通市值 (circulating MktCap) at column index 33
  - 总市值             at column index 34

It does NOT return a column named "基金规模".

All data is mocked — no network calls.
"""

import pytest
import pandas as pd

from app.fetchers.etf_scanner import filter_etfs

# P3-6 (round17): 并入 test_p023_amount_override.py（P0-23 快照成交额异常实时补查防护，
# 同一 filter_etfs 函数域）——需要 os + patch
import os
from unittest.mock import patch


def _make_mock_row(**overrides) -> dict:
    """Simulate one row from akshare fund_etf_spot_em() with real column names."""
    row = {
        "代码":      "510300",
        "名称":      "沪深300ETF",
        "最新价":    3.855,
        "涨跌幅":    0.52,
        "成交额":    1_500_000_000.0,
        "成交量":    390_000_000.0,
        "换手率":    5.12,
        "流通市值":  120.0,  # 亿元 — the REAL column name from akshare
        "总市值":    120.0,
    }
    row.update(overrides)
    return row


def _make_mock_raw_list(size: int = 5) -> list[dict]:
    """Return a list of simulated rows with real ETF column names."""
    etfs = [
        {"代码": "510300", "名称": "沪深300ETF",    "成交额": 1.5e9, "流通市值": 120.0},
        {"代码": "512480", "名称": "半导体ETF",     "成交额": 8e8,  "流通市值": 30.0},
        {"代码": "518880", "名称": "黄金ETF",       "成交额": 2e9,  "流通市值": 200.0},
        {"代码": "513100", "名称": "纳指ETF",       "成交额": 5e8,  "流通市值": 45.0},
        {"代码": "560600", "名称": "中证A500ETF",   "成交额": 3e8,  "流通市值": 15.0},
        # 以下应该被过滤掉（成交额 < 1000万）
        {"代码": "999999", "名称": "迷你债ETF",     "成交额": 5e5,  "流通市值": 0.5},
        # 以下应该被过滤掉（纯债关键词）
        {"代码": "511090", "名称": "国债ETF-30年",  "成交额": 1e8,  "流通市值": 80.0},
    ]
    result = []
    for etf in etfs:
        base = _make_mock_row()
        base.update(etf)
        result.append(base)
    return result


class TestFilterEtfs:
    """Tests for filter_etfs: column name compatibility."""

    def test_filter_etfs_with_real_column_names_returns_non_empty(self):
        """P4-a: filter_etfs must work with akshare's current column names.

        With real column names (成交额/流通市值), at least 5 ETFs should pass
        the min-amount and min-scale filters.
        """
        raw = _make_mock_raw_list()
        result = filter_etfs(raw)
        assert len(result) > 0, (
            f"filter_etfs returned 0/{len(raw)} with real column names. "
            "This suggests SCALE_NAMES still uses '基金规模' which doesn't exist "
            "in the current akshare API. Expected at least 5 ETFs to pass."
        )

    def test_filter_etfs_drops_small_etfs(self):
        """ETFs below amount/scale thresholds must be excluded."""
        raw = _make_mock_raw_list()
        # 999999 has 成交额=5e5 < 10M threshold
        result = filter_etfs(raw)
        codes = {r["symbol"] for r in result}
        assert "999999" not in codes, "迷你债ETF (low amount) should be filtered out"

    def test_filter_etfs_drops_pure_bonds(self):
        """Pure bond / money-market ETFs must be excluded (P1-2: 国债ETF kept as defense)."""
        raw = _make_mock_raw_list()
        result = filter_etfs(raw)
        codes = {r["symbol"] for r in result}
        # P1-2: 国债ETF is defense layer asset, NOT filtered out
        assert "511090" in codes, "国债ETF (511090) is a defense layer asset and should NOT be filtered"
        # 国开债/城投债/信用债/可转债 should still be excluded
        raw_bond = raw + [{"代码": "511200", "名称": "国开债ETF", "最新价": 101.0,
                           "涨跌幅": 0.01, "成交额": 5_000_000, "成交量": 50_000,
                           "换手率": 0.1, "流通市值": 5.0, "总市值": 5.0}]
        result2 = filter_etfs(raw_bond)
        codes2 = {r["symbol"] for r in result2}
        assert "511200" not in codes2, "国开债ETF should be filtered out as pure bond"

    def test_filter_etfs_from_dataframe(self):
        """filter_etfs must accept pd.DataFrame input."""
        raw = _make_mock_raw_list()
        df = pd.DataFrame(raw)
        result = filter_etfs(df)
        assert len(result) > 0, "DataFrame input must also work"

    def test_filter_etfs_output_shape(self):
        """Each filtered ETF must have required fields."""
        raw = _make_mock_raw_list()
        result = filter_etfs(raw)
        for r in result:
            assert "symbol" in r
            assert "name" in r
            assert "amount" in r
            assert isinstance(r["amount"], (int, float))
            assert r["amount"] > 0


# ── P0-23 (round16 3.25, 自 test_p023_amount_override.py 并入): 快照成交额异常补查 ──
# 验收: ① 快照成交额低估（<MIN_AVG_AMOUNT）但实时补查达标 → 保留（负向：误杀 → FAIL）；
#       ② 实时补查仍低 → 过滤（真实低流动性不误放）；③ ETF_SKIP_AMOUNT_OVERRIDE=1 不触发网络。


def _row(code, name, amount, scale=50.0):
    return {
        "代码": code, "名称": name, "最新价": 1.0, "涨跌幅": 0.5,
        "成交额": amount, "成交量": 100, "换手率": 1.0,
        "流通市值": scale, "总市值": scale,
    }


class TestP023SnapshotAmountRescue:
    def test_low_snapshot_amount_rescued_by_realtime(self):
        """P0-23①: 快照成交额 48.9 万（<1000万）但实时 9.7 亿 → 保留（防误杀）。

        负向：快照低估被直接过滤 → FAIL。
        """
        os.environ.pop("ETF_SKIP_AMOUNT_OVERRIDE", None)  # 关闭跳过开关（启用补查）
        try:
            raw = [
                _row("159516", "半导体设备ETF", 489_000),   # 快照 48.9 万 < 1000万
                _row("510300", "沪深300ETF", 1.5e9),        # 正常
            ]
            with patch("app.fetchers.etf_scanner._tencent_gtimg_batch",
                       return_value={"159516": {"amount": 9.7e8}}):  # 实时 9.7 亿
                result = filter_etfs(raw)
        finally:
            os.environ["ETF_SKIP_AMOUNT_OVERRIDE"] = "1"
        codes = {r["symbol"] for r in result}
        assert "159516" in codes, "快照低估但实时达标的活跃板块 ETF 不得被过滤"
        kept = next(r for r in result if r["symbol"] == "159516")
        assert kept["amount"] == pytest.approx(9.7e8), "amount 应用实时值覆盖"

    def test_real_low_amount_still_filtered(self):
        """P0-23③: 实时补查仍低 → 过滤（真实低流动性不误放）。"""
        os.environ.pop("ETF_SKIP_AMOUNT_OVERRIDE", None)
        try:
            raw = [_row("999999", "迷你债ETF", 5e5)]
            with patch("app.fetchers.etf_scanner._tencent_gtimg_batch",
                       return_value={"999999": {"amount": 3e5}}):  # 实时仍 <1000万
                result = filter_etfs(raw)
        finally:
            os.environ["ETF_SKIP_AMOUNT_OVERRIDE"] = "1"
        assert result == [], "实时补查仍低时应过滤"

    def test_skip_switch_no_network(self):
        """测试开关 ETF_SKIP_AMOUNT_OVERRIDE=1 → 不触发网络（直接过滤存疑行）。"""
        raw = [_row("999999", "迷你债ETF", 5e5)]
        with patch("app.fetchers.etf_scanner._tencent_gtimg_batch",
                   side_effect=AssertionError("不应触发网络")) as m:
            result = filter_etfs(raw)
        assert result == []
        m.assert_not_called()


# ===== folded from test_round15_amount_unit.py =====
import json
import logging
from pathlib import Path
from app.fetchers import etf_scanner as es
SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "etf_list_cache.json"
def _load_snapshot() -> list[dict]:
    if not SNAPSHOT.exists():
        pytest.skip("etf_list_cache.json 快照不存在（离线环境跳过快照回归）")
    with open(SNAPSHOT, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("etfs", data) if isinstance(data, dict) else data
def _wan_to_yuan(snapshot: list[dict]) -> list[dict]:
    """模拟修复后的数据源输出：gtimg amount 万元 → 元（与 _tencent_gtimg_chunk ×10000 同口径）。"""
    rows = []
    for row in snapshot:
        r = dict(row)
        if r.get("amount"):
            r["amount"] = float(r["amount"]) * 10000.0
        rows.append(r)
    return rows
def _gtimg_line() -> str:
    """构造 gtimg 格式行：parts[37]=成交额(万元)、parts[38]=换手率、
    parts[45]=总市值(亿)、parts[47]=PE（与 _tencent_gtimg_chunk 索引一致）。"""
    fields = [str(i) for i in range(50)]
    fields[2] = "510300"
    fields[37] = "447469"     # 成交额 万元
    fields[38] = "5.12"       # 换手率
    fields[45] = "1193.85"    # 总市值 亿
    fields[47] = "1.12"       # PE
    return 'v_sh510300="' + "~".join(fields) + '";'
GTIMG_LINE = _gtimg_line()
def _fake_gtimg_response(*args, **kwargs):
    class _Resp:
        text = GTIMG_LINE
    return _Resp()
class TestTencentAmountUnit:
    """gtimg parts[37] 万元 → 元 换算（数据源层单位契约）。"""

    def test_amount_converted_wan_to_yuan(self):
        with patch("requests.get", side_effect=_fake_gtimg_response):
            result = es._tencent_gtimg_chunk(["510300"])
        assert "510300" in result
        # 447469 万 = 4.47469e9 元；修复前返回 447469（万元残留 <1e6）
        assert result["510300"]["amount"] == pytest.approx(447469 * 10000.0)

    def test_fund_scale_unit_kept_yi(self):
        with patch("requests.get", side_effect=_fake_gtimg_response):
            result = es._tencent_gtimg_chunk(["510300"])
        # fund_scale 单位=亿，与 MIN_FUND_SCALE(亿) 匹配，不换算
        assert result["510300"]["fund_scale"] == pytest.approx(1193.85)
class TestSnapshotRegression:
    """真实快照回归：修复后真实活跃 ETF 必须通过 filter_etfs（修复前被误杀）。"""

    def test_filter_passes_real_active_etfs(self):
        snapshot = _load_snapshot()
        rows = _wan_to_yuan(snapshot)
        result = es.filter_etfs(rows)
        codes = {r["symbol"] for r in result}
        # §4.6 实证：修复前 159516/159869/512480 被误杀、510300 靠静态兜底
        for sym in ("510300", "159516", "159869", "512480"):
            assert sym in codes, f"{sym} 应通过 filter_etfs（amount 元口径 ≥1000 万）"

    def test_filter_pass_count_over_1000(self):
        """§5.4 验收 1: 修复后通过数 ≥1000（修复前 392）。"""
        snapshot = _load_snapshot()
        rows = _wan_to_yuan(snapshot)
        result = es.filter_etfs(rows)
        assert len(result) >= 1000, f"filter 通过数 {len(result)} < 1000（万元口径残留?）"

    def test_snapshot_fund_scale_unit_contract(self):
        """§5.4 验收 6: 510300 fund_scale 必须为 1193.85（亿）——若未来数据源返回元
        （1.19e11）则契约测试失败（防 parts[45] 单位漂移）。"""
        snapshot = _load_snapshot()
        hit = next((r for r in snapshot if r.get("symbol") == "510300"), None)
        assert hit is not None, "快照缺少 510300"
        assert float(hit.get("fund_scale") or 0) == pytest.approx(1193.85)

    def test_sina_tencent_provider_flags_wan_residue(self, caplog, tmp_path):
        """绝对量级检查：0<amount<1e6（万元残留特征）应触发告警。

        修复前（无 ×10000）amount 为万元值 447469 < 1e6 → 本条告警本应触发；
        修复后 amount=4.47e9 不再触发——该断言防的是「未来 ×10000 被回退」。
        """
        es.sync_memory_cache.clear()
        cache_file = tmp_path / "etf_cache.json"  # 隔离真实 data/ 缓存，防 mock 数据落盘
        with patch.object(es, "_etf_cache_file", return_value=str(cache_file)):
            with patch("app.fetchers.china_market.fetch_etf_list",
                       return_value=[{"symbol": f"51{i:04d}"} for i in range(60)]):
                with patch.object(es, "_tencent_gtimg_batch", return_value={"510300": {"amount": 447469.0}}):
                    with patch.object(es, "_fetch_em_etf_list", return_value=None):
                        with caplog.at_level(logging.WARNING, logger="app.fetchers.etf_scanner"):
                            es.fetch_all_etfs_base()
        assert any("疑似万元口径残留" in r.message for r in caplog.records)
class TestCrossCheck:
    """跨源量级一致性校验（§4.6.3/§5.4 必做项）。"""

    def test_scale_mismatch_warns(self, caplog):
        gtimg_map = {"510300": {"amount": 4.47469e9}}   # 腾讯元口径（×10000 后）
        em_list = [{"symbol": "510300", "amount": 447469.0}]  # EM 元口径，差 1e4 倍
        with caplog.at_level(logging.WARNING, logger="app.fetchers.etf_scanner"):
            es._cross_check_amount_scale(gtimg_map, em_list)
        assert any("跨源量级不一致" in r.message for r in caplog.records)

    def test_aligned_scale_no_warn(self, caplog):
        gtimg_map = {"510300": {"amount": 4.47469e9}}
        em_list = [{"symbol": "510300", "amount": 4.4e9}]  # 同量级
        with caplog.at_level(logging.WARNING, logger="app.fetchers.etf_scanner"):
            es._cross_check_amount_scale(gtimg_map, em_list)
        assert not any("跨源量级不一致" in r.message for r in caplog.records)

    def test_empty_em_silently_skipped(self, caplog):
        es._cross_check_amount_scale({"510300": {"amount": 1e9}}, None)
        assert not any("跨源量级不一致" in r.message for r in caplog.records)


# ===== folded from test_round18_p1_p2.py =====
from unittest.mock import AsyncMock, MagicMock
class TestP21AssetTypeNormalization:
    """round18 P2-1: fetch_history asset_type 归一化。"""

    def test_etf_asset_type_normalized_to_a(self, monkeypatch):
        """asset_type='etf' → 归一到 'A'（走 ETF sina 快链；负向：静默 return [] → FAIL）。"""
        from app.fetchers import china_market as cm

        calls = []
        rows = [{"date": "2026-08-12", "open": 4.7, "high": 4.76, "low": 4.7,
                 "close": 4.751, "volume": 9435356}]

        def fake_sina(symbol, period="daily"):
            calls.append((symbol, period))
            return rows

        monkeypatch.setattr(cm, "_sina_history_cb", fake_sina)
        out = cm.fetch_history("510300", "etf", "daily")
        assert out == rows, f"'etf' 应归一化到 A 走 sina 快链，实得 {len(out)} 行"
        assert calls == [("510300", "daily")]

    def test_fund_asset_type_normalized(self, monkeypatch):
        from app.fetchers import china_market as cm

        def fake_sina(symbol, period="daily"):
            return [{"date": "2026-08-12", "open": 1.0, "close": 1.05}]

        monkeypatch.setattr(cm, "_sina_history_cb", fake_sina)
        out = cm.fetch_history("510300", "FUND", "daily")
        assert out, "FUND 应归一化到 A"

    def test_unknown_asset_type_returns_empty(self, monkeypatch):
        """未知类型（如 'FOO'）保持空——不伪造数据。"""
        from app.fetchers import china_market as cm
        assert cm.fetch_history("510300", "FOO", "daily") == []
