# -*- coding: utf-8 -*-
"""round35 B3-F7 前置快照（docs/round35-architecture-review.md §6.3）——
分类器行为冻结：合并进 engine/taxonomy.py 前后 diff 必须为空。

方法：对 28 只覆盖全部分类分支 + 历史事故案例的 ETF meta，逐只运行
五标签分类 + 概念提取/归一化，与 tests/fixtures/etf_classification_baseline.json
逐字段比对。基线由重构前的 allocation_engine 分类器生成——本测试即「先固化后动手」
的可行性探针位；taxonomy 合并若引入任何行为漂移，此处必红。
"""
import json
from pathlib import Path

import pytest

from app.engine.allocation_engine import (
    _extract_index_concept,
    _is_growth_wide_basis,
    _is_large_cap_wide_basis,
    _is_tech_theme,
    _is_wide_basis,
    _normalize_segment,
    _substitute_family,
)

BASELINE = Path(__file__).resolve().parent / "fixtures" / "etf_classification_baseline.json"


def _live(entry: dict) -> dict:
    m = entry["meta"]
    concept = _extract_index_concept(m.get("name", ""))
    return {
        "meta": m,
        "wide_basis": _is_wide_basis(m),
        "growth_style": _is_growth_wide_basis(m),
        "large_cap_family": _is_large_cap_wide_basis(m),
        "tech_theme": _is_tech_theme(m.get("name", "")),
        "substitute_family": _substitute_family(m),
        "index_concept": concept,
        "segment": _normalize_segment(concept),
    }


@pytest.mark.parametrize("entry", json.loads(BASELINE.read_text(encoding="utf-8")),
                         ids=lambda e: e["meta"]["symbol"])
def test_classification_matches_frozen_baseline(entry: dict) -> None:
    assert _live(entry) == entry


def test_baseline_covers_all_branches() -> None:
    """元断言：基线本身必须覆盖五标签的真值分支（防快照退化为恒 False 集合）。"""
    entries = json.loads(BASELINE.read_text(encoding="utf-8"))
    for key in ("wide_basis", "growth_style", "large_cap_family", "tech_theme"):
        assert any(e[key] for e in entries), f"基线缺少 {key}=True 分支"
    assert any(e["substitute_family"] for e in entries), "基线缺少 substitute_family 命中"
