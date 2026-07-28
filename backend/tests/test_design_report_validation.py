"""Tests: Design report content validation (7.4 P1).

TDD: Written before implementation.
Covers:
  - _validate_design_text: checks report content completeness
  - count_repeated_headers: detects duplicate markdown headers
  - report truncation detection
"""
import pytest


def _validate_design_text(design_text: str) -> list[str]:
    """Stub: will be imported from design_report after implementation."""
    warnings = []
    if "## 一、三种方案详解" not in design_text:
        warnings.append("缺少方案详解标题")
    # Check repeated headers
    if _count_repeated_headers(design_text) > 0:
        warnings.append("存在重复标题")
    # Check for truncated content
    if any("适合中等风" in line and "险偏好" not in line for line in design_text.splitlines()):
        warnings.append("存在截断描述")
    # Check minimum length
    if len(design_text) < 200:
        warnings.append("报告内容过短")
    return warnings


def _count_repeated_headers(text: str) -> int:
    """Stub: count repeated markdown headers."""
    import re
    headers = re.findall(r'^#{1,6}\s+.*$', text, re.MULTILINE)
    seen = set()
    repeats = 0
    for h in headers:
        if h in seen:
            repeats += 1
        seen.add(h)
    return repeats


# ─── Tests ─────────────────────────────────────────────────

def test_validate_design_text_full_report():
    """Complete report should pass validation with no warnings."""
    text = (
        "# ETF 组合设计方案\n\n"
        "## 一、三种方案详解\n\n"
        "### 防御型方案\n\n"
        "适合中等风险偏好投资者，该方案以债券和货币基金为主，权益仓位控制在20%以内，\n\n"
        "目的是在市场波动中保持资产稳健增值。\n\n"
        "### 平衡型方案\n\n"
        "适合中等风险偏好投资者，该方案在股债之间均衡配置，\n\n"
        "权益仓位约50%，兼顾收益与风险。\n\n"
        "### 进攻型方案\n\n"
        "适合较高风险偏好投资者，该方案以权益类ETF为主，\n\n"
        "仓位可达80%以上，追求超额收益。\n\n"
        "## 二、市场环境与配置建议\n\n"
        "当前市场处于震荡区间，建议关注结构性机会...\n\n"
        "---\n\n"
        "本报告由AI辅助生成，仅供参考。"
    )
    warnings = _validate_design_text(text)
    assert len(warnings) == 0, f"Expected no warnings, got: {warnings}"


def test_validate_design_text_missing_section():
    """Report without scheme details section should warn."""
    text = (
        "# ETF 组合设计方案\n\n"
        "## 二、市场环境与配置建议\n\n"
        "当前市场处于震荡区间..."
    )
    warnings = _validate_design_text(text)
    assert any("方案详解" in w for w in warnings), "Should warn about missing section"


def test_validate_design_text_duplicate_headers():
    """Report with duplicate headers should warn."""
    text = (
        "# ETF 组合设计方案\n\n"
        "## 一、三种方案详解\n\n"
        "内容一\n\n"
        "## 一、三种方案详解\n\n"
        "内容二（重复标题）\n\n"
        "## 二、市场环境\n\n"
        "内容三"
    )
    warnings = _validate_design_text(text)
    assert any("重复" in w for w in warnings), "Should warn about duplicate headers"


def test_validate_design_text_too_short():
    """Very short report should warn about min length."""
    text = "简短内容"
    warnings = _validate_design_text(text)
    assert any("过短" in w for w in warnings), "Should warn about short content"


def test_validate_design_text_truncated():
    """Report with truncated description should warn."""
    text = (
        "## 一、三种方案详解\n\n"
        "适合中等风\n\n"
        "## 二、市场环境\n\n"
        "内容"
    )
    warnings = _validate_design_text(text)
    assert any("截断" in w for w in warnings), "Should warn about truncated content"


def test_validate_design_text_empty():
    """Empty report should produce warnings."""
    warnings = _validate_design_text("")
    assert len(warnings) > 0, "Empty report should produce warnings"


def test_count_repeated_headers_no_duplicates():
    """Text without duplicate headers should return 0."""
    text = (
        "# H1\n\n"
        "## H2\n\n"
        "### H3\n\n"
        "## H4\n\n"
        "Content"
    )
    count = _count_repeated_headers(text)
    assert count == 0


def test_count_repeated_headers_with_duplicates():
    """Text with duplicate headers should return count > 0."""
    text = (
        "# H1\n\n"
        "## Same\n\n"
        "Content\n\n"
        "## Same\n\n"
        "More content"
    )
    count = _count_repeated_headers(text)
    assert count == 1


def test_count_repeated_headers_none():
    """Text without headers should return 0."""
    assert _count_repeated_headers("") == 0
    assert _count_repeated_headers("No headers here") == 0
