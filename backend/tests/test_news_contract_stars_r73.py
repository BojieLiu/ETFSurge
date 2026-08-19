# -*- coding: utf-8 -*-
"""R73: 资讯 stars 契约一致性断言（round29 §14.3）。

背景（round29 Round 13 归因修正）：`_compute_stars`（news_fetcher.py:228）是
round9 P2-1 刻意「纯新鲜度」设计（<1h→5★/…/更旧→1★），非实现 bug；
契约 `api-contracts/news/all.md:84` 旧公式 `min(level+freshness,5)` 过时且
与 all.md:3（stars=level）自相矛盾。R73 = 更新契约对齐实现 + 契约一致性断言。

断言范围：
1. 负向：契约不再出现旧混合公式（min(level+freshness,5) / Combined score = level + freshness）。
2. 正向：契约三处口径（all.md 顶部注记 / 字段表 / Stars formula 段）均为「纯新鲜度」。
3. 实现一致性：任意 level + 新鲜度 <1h → 5★ 合法（level 与 stars 解耦）。
"""
from datetime import datetime, timedelta
from pathlib import Path

from app.fetchers.news_fetcher import _compute_stars

ROOT = Path(__file__).resolve().parent.parent.parent
ALL_MD = ROOT / "api-contracts" / "news" / "all.md"
CLASS_MD = ROOT / "api-contracts" / "news" / "classification.md"


def _read(path: Path) -> str:
    assert path.exists(), f"契约文件缺失: {path}"
    return path.read_text(encoding="utf-8")


class TestR73ContractNoOldFormula:
    """负向：契约不再出现「level+freshness 混合」旧公式。"""

    def test_all_md_no_min_level_freshness(self):
        content = _read(ALL_MD)
        assert "min(level + freshness, 5)" not in content
        assert "min(level+freshness, 5)" not in content

    def test_all_md_no_combined_score(self):
        content = _read(ALL_MD)
        assert "Combined score = level + freshness" not in content
        assert "level + freshness bonus" not in content

    def test_classification_md_no_mixed_formula(self):
        content = _read(CLASS_MD)
        assert "min(level + freshness, 5)" not in content
        assert "level + freshness" not in content


class TestR73ContractFreshnessSemantics:
    """正向：契约三处口径统一为「纯新鲜度维度」."""

    def test_all_md_annotation_says_pure_freshness(self):
        content = _read(ALL_MD)
        assert "纯新鲜度" in content
        assert "与" in content and "level" in content and "解耦" in content

    def test_all_md_field_table_says_pure_freshness(self):
        content = _read(ALL_MD)
        # 字段表 stars 行
        assert "纯新鲜度维度" in content
        assert "Combined score" not in content

    def test_all_md_stars_formula_section_has_buckets(self):
        content = _read(ALL_MD)
        for token in ("<1h", "5★", "<6h", "4★", "<24h", "3★", "<72h", "2★"):
            assert token in content, f"Stars formula 段缺少 {token}"

    def test_classification_md_stars_freshness(self):
        content = _read(CLASS_MD)
        assert "新鲜度维度" in content


class TestR73ContractMatchesImplementation:
    """实现一致性：契约公式与 _compute_stars 行为一致（任意 level 可获 5★）。"""

    def test_any_level_plus_fresh_news_yields_5_star(self):
        now = datetime.now()
        fresh = (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        for level in range(1, 6):
            assert _compute_stars(level, fresh) == 5, \
                f"level={level} + <1h 新鲜度应得 5★（纯新鲜度语义，与 level 解耦）"

    def test_old_news_always_1_star_regardless_of_level(self):
        now = datetime.now()
        old = (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        for level in range(1, 6):
            assert _compute_stars(level, old) == 1, \
                f"level={level} + 更旧应得 1★（level 不提升 stars）"
