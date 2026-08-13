"""round15 方案四（P0）: amount 单位统一 + 单位契约 + 跨源一致性校验。

对应 docs/archived/round15-factor-pool-selection-evaluation.md §5.4/§7：
- gtimg parts[37] 成交额单位=万元 → 统一 ×10000 为元（filter 阈值 MIN_AVG_AMOUNT 是元）
- 以 data/etf_list_cache.json（2026-08-07 快照，1624 只）为固定输入做快照回归：
  真实活跃 ETF（510300/159516/159869/512480）必须通过 filter_etfs（修复前被误杀）
- fund_scale 单位契约：510300 = 1193.85（亿口径）
- 跨源量级一致性校验：腾讯（元）vs EM（元）同标的差 >100 倍 → 告警

修复前这些测试全部 FAIL（amount 万元值 < MIN_AVG_AMOUNT=1e7 被误杀）——负向断言防回归。
"""
import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

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
