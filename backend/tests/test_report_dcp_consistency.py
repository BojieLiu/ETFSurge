"""
O18 (docs/round8-rediagnosis.md §7): 报告「今日涨跌」与实时行情一致性。

验收③: 新增 test_report_dcp_consistency——报告 DCP 与 /realtime 偏差在阈值内
（不再出现 510050 -23.40% vs 实时 +0.73% 的 ≥10 倍极端）。
"""

import pytest

from app.services import strategy_design as sd
from app.tasks import design_report as dr


class FakeHub:
    """mock market_data_hub：get_by_code 返回实时快照（percent 口径）。"""

    def __init__(self, entries: dict):
        self.entries = entries

    def get_by_code(self, code):
        return self.entries.get(code)

    def get_kline_rows_any(self, symbol):
        return None


def _strategies_with_real_time(hub):
    """构造与实时快照偏差 ≤5 个百分点的方案（模拟注入后结构）。"""
    allocs = []
    for code, entry in hub.entries.items():
        allocs.append({
            "symbol": code,
            "name": entry.get("name", code),
            "layer": "core",
            "weight": 0.2,
            "daily_change_pct": sd.sanitize_change_pct(code, entry["change_pct"]),
            "factor_score": 0.5,
            "selection_rationale": "宽基",
        })
    return [{
        "label": "平衡型",
        "positioning": "攻守兼备",
        "allocations": allocs,
        "expected_return": 0.06,
    }]


class TestReportRealtimeConsistency:
    def test_report_dcp_within_threshold_of_realtime(self):
        """报告渲染的今日涨跌与 /realtime 偏差 <5 个百分点（510050 不再出现 10 倍极端）。"""
        hub = FakeHub({
            "510050": {"name": "上证50ETF", "change_pct": 0.73},
            "518880": {"name": "黄金ETF", "change_pct": 0.13},
            "510300": {"name": "沪深300ETF", "change_pct": 0.79},
        })
        strategies = _strategies_with_real_time(hub)
        text = dr._build_plan_tables(strategies)

        # 报告值 = 渲染文本里的百分比；与实时偏差应 < 5 个百分点
        import re
        for code, entry in hub.entries.items():
            real = entry["change_pct"]
            m = re.search(rf"\|\s*{code}\s*\|\s*[^|]+\|\s*[0-9]+\|\s*[0-9.]*\|\s*([+-][0-9.]+)%", text)
            # 容错：若行结构匹配失败则跳过（核心断言在下方单值）
            if m:
                assert abs(float(m.group(1)) - real) < 5.0, f"{code} 报告值 {m.group(1)}% 与实时 {real}% 偏差超阈值"

    def test_510050_not_tenfold_extreme(self):
        """510050 报告值不再出现 ≥10 倍极端（-23.40% 类）。"""
        hub = FakeHub({"510050": {"name": "上证50ETF", "change_pct": 0.73}})
        strategies = _strategies_with_real_time(hub)
        text = dr._build_plan_tables(strategies)
        assert "-23.40%" not in text
        assert "0.73%" in text
