"""F7 (round6 §14.2/§14.6): verify_e2e 卫星层数量门禁——辅助函数单测。

规格：design-quality 门禁增加「卫星层 ≥4 只且 ≥2 个非科技主题」断言
（当前无数量下限断言，F0-5 步骤 D 仅代码注释层面）。
"""
import importlib.util
import sys
from pathlib import Path

# verify_e2e.py 是脚本（有 main），用 importlib 加载其辅助函数
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_e2e.py"
_spec = importlib.util.spec_from_file_location("verify_e2e_mod", _SCRIPT)
_ve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ve)


def _mk_strategy(allocs: list[dict], sid: str = "p1") -> dict:
    return {"id": sid, "name": sid, "allocations": allocs, "etfs": allocs}


def _alloc(symbol: str, name: str, layer: str, tracked_index: str = "") -> dict:
    return {"symbol": symbol, "name": name, "layer": layer, "tracked_index": tracked_index}


class TestSatelliteQualityCheck:
    def test_four_sats_two_non_tech_passes(self):
        """F7: 卫星 4 只、非科技 2 只 → 门禁数据达标。"""
        s = _mk_strategy([
            _alloc("588000", "科创50ETF", "satellite", "科创50"),
            _alloc("512480", "半导体ETF", "satellite", "半导体"),
            _alloc("512010", "医药ETF", "satellite", "中证医药"),
            _alloc("159928", "消费ETF", "satellite", "中证消费"),
        ])
        n, non_tech, tech = _ve._satellite_quality_check(s)
        assert n == 4 and non_tech == 2 and tech == 2

    def test_two_sats_fails_count(self):
        """F7: 卫星仅 2 只 → 数量断言 FAIL（14.2 层配比失衡场景）。"""
        s = _mk_strategy([
            _alloc("588000", "科创50ETF", "satellite", "科创50"),
            _alloc("512480", "半导体ETF", "satellite", "半导体"),
        ])
        n, non_tech, _ = _ve._satellite_quality_check(s)
        assert n == 2 and non_tech == 0

    def test_tech_heavy_fails_non_tech_count(self):
        """F7: 卫星 4 只但全为科技系 → 非科技主题断言 FAIL（14.1 科创包场场景）。"""
        s = _mk_strategy([
            _alloc("588000", "科创50ETF", "satellite", "科创50"),
            _alloc("512480", "半导体ETF", "satellite", "半导体"),
            _alloc("588190", "科创100ETF", "satellite", "科创100"),
            _alloc("515030", "AI ETF", "satellite", "人工智能"),
        ])
        n, non_tech, tech = _ve._satellite_quality_check(s)
        assert n == 4 and non_tech == 0 and tech == 4

    def test_allocations_or_etfs_structure(self):
        """F7: 兼容 allocations 与 etfs 两种持久化结构。"""
        s = {"id": "p2", "name": "p2", "etfs": [
            _alloc("512010", "医药ETF", "satellite", "中证医药"),
            _alloc("159928", "消费ETF", "satellite", "中证消费"),
            _alloc("512800", "银行ETF", "satellite", "中证银行"),
            _alloc("516160", "新能源ETF", "satellite", "新能源"),
        ]}
        n, non_tech, tech = _ve._satellite_quality_check(s)
        assert n == 4 and non_tech == 4 and tech == 0
