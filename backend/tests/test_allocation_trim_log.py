"""F4-前置: 卫星层科技配额裁剪日志（round6 §14.6 F4 前置联动）。

背景：allocation_engine 科技配额裁剪（F0-5 步骤 C，allocation_engine.py:342-385）
无 logger——task 158「防御卫星科创 12% > tech_cap 8%」无法从日志复核。
修复：裁剪触发 / 裁剪量 / 回补结果三级日志；验收断言含日志复核项。
"""
import logging

from app.engine import allocation_engine as ae

_LOGGER = "app.engine.allocation_engine"


def _sat_candidates(tech_only: bool = False):
    cands = [
        {"symbol": "588000", "name": "科创50ETF", "layer": "satellite", "tracked_index": "科创50"},
        {"symbol": "159995", "name": "芯片ETF", "layer": "satellite", "tracked_index": "芯片"},
        {"symbol": "588200", "name": "科创芯片ETF", "layer": "satellite", "tracked_index": "科创芯片"},
        {"symbol": "159992", "name": "创新药ETF", "layer": "satellite", "tracked_index": "创新药"},
        {"symbol": "515790", "name": "光伏ETF", "layer": "satellite", "tracked_index": "光伏"},
    ]
    if tech_only:
        return cands[:3]
    return cands


def _factor_matrix(cands):
    base = {"technical": 0.5, "momentum": 0.5, "valuation": 0.5, "sentiment": 0.5}
    return {c["symbol"]: dict(base) for c in cands}


def test_tech_trim_logs_trigger_and_reclaim(caplog):
    """裁剪触发时：触发日志、裁剪量日志、回补日志均应出现。"""
    cands = _sat_candidates()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        result = ae._select_and_weight(
            candidates=cands,
            factor_matrix=_factor_matrix(cands),
            budget=0.2,
            layer="satellite",
            regime="neutral",
            strategy="defensive",
            max_count=5,
        )
    assert result, "裁剪后应仍有结果"
    text = caplog.text.lower()
    # 触发日志：科技合计超预算
    assert "tech" in text and "trim" in text
    # 裁剪量日志
    assert "drop" in text or "裁剪" in text
    # 回补日志（存在非科技候选）
    assert "reclaim" in text or "回补" in text


def test_tech_trim_logs_no_reclaim_warning(caplog):
    """被裁权重无回补对象（全科技卫星池）时：应警告转现金/预算未打满。"""
    cands = _sat_candidates(tech_only=True)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = ae._select_and_weight(
            candidates=cands,
            factor_matrix=_factor_matrix(cands),
            budget=0.2,
            layer="satellite",
            regime="neutral",
            strategy="defensive",
            max_count=5,
        )
    assert result, "裁剪后应仍有结果"
    text = caplog.text.lower()
    assert "cash" in text or "回补" in text or "未打满" in text
