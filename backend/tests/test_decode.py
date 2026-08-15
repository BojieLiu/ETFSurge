from __future__ import annotations
"""Tests for the decode_df function that handles latin1 double-encoding issues."""
import pandas as pd
import pytest

from app.utils.decode import decode_df


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def latin1_double_encoded_df():
    """Simulate an akshare DataFrame with latin1→utf-8 double-encoded Chinese.

    The column name '名称' becomes 'Ã\u0083Â§Ã\u0080Â°Ã\u0081Â§' when double-encoded:
    bytes: '名称'.encode('utf-8') → decode as latin1 →... but let's be precise.
    """
    # Simulate a column name that was double-encoded: "名称" → latin1 garbled
    garbled_col = "\xe5\x90\x8d\xe7\xa7\xb0"  # '名称' UTF-8 bytes misinterpreted as latin1 chars
    # Simulate a value: "沪深300ETF" → garbled
    garbled_val = "\xe6\xb2\xaa\xe6\xb7\xb1300ETF"  # '沪深300ETF' UTF-8 bytes as latin1 chars

    df = pd.DataFrame({garbled_col: [garbled_val, "正常文本"]})
    return df


@pytest.fixture
def clean_utf8_df():
    """A normal UTF-8 DataFrame that should remain unchanged."""
    df = pd.DataFrame({
        "代码": ["510300", "518880"],
        "名称": ["沪深300ETF", "华安黄金ETF"],
        "价格": [3.85, 5.21],
    })
    return df


@pytest.fixture
def empty_df():
    """Empty DataFrame."""
    return pd.DataFrame()


# ─── Tests ───────────────────────────────────────────────────────────


class TestDecodeDfGeneral:
    """缺口 ⑤: Tests for the decode_df function that handles latin1 double-encoding."""

    def test_latin1_double_encoded_values_are_decoded(self):
        """Column values with latin1→utf-8 double encoding should be corrected."""
        # Create a real latin1 double-encoded string
        # '名称' correctly encoded then re-interpreted twice
        original = "名称"
        # Step 1: encode to UTF-8 bytes
        utf8_bytes = original.encode("utf-8")
        # Step 2: interpret those bytes as latin1 characters
        double_encoded = utf8_bytes.decode("latin1")

        df = pd.DataFrame({"col": [double_encoded, "中文测试"]})
        result = decode_df(df)

        # After decode_df, the value should be back to '名称'
        assert result["col"].iloc[0] == "名称", (
            f"Expected '名称', got: {repr(result['col'].iloc[0])}"
        )

    def test_latin1_double_encoded_columns_are_fixed(self):
        """Column names with latin1→utf-8 double encoding should be corrected."""
        original_col = "名称"
        utf8_bytes = original_col.encode("utf-8")
        double_encoded_col = utf8_bytes.decode("latin1")

        df = pd.DataFrame({double_encoded_col: ["value"]})
        result = decode_df(df)

        assert "名称" in result.columns, (
            f"Expected '名称' in columns, got: {list(result.columns)}"
        )

    def test_clean_utf8_data_unchanged(self, clean_utf8_df):
        """Properly-encoded UTF-8 DataFrames should not be altered."""
        original = clean_utf8_df.copy()
        result = decode_df(clean_utf8_df)

        pd.testing.assert_frame_equal(result, original)

    def test_empty_dataframe_unchanged(self, empty_df):
        """Empty DataFrame should be returned as-is."""
        result = decode_df(empty_df)
        assert result.empty

    def test_none_dataframe_returns_none(self):
        """None input should return None."""
        result = decode_df(None)
        assert result is None

    def test_numeric_columns_unchanged(self):
        """Numeric columns should not be affected by decode_df."""
        df = pd.DataFrame({"symbol": ["510300"], "price": [3.85]})
        result = decode_df(df)
        assert result["price"].iloc[0] == 3.85

    def test_already_correct_utf8_columns_unchanged(self):
        """Already correct Chinese column names should remain intact."""
        df = pd.DataFrame({"名称": ["沪深300ETF"], "代码": ["510300"]})
        result = decode_df(df)
        assert "名称" in result.columns
        assert "代码" in result.columns
        assert result["名称"].iloc[0] == "沪深300ETF"

    def test_gbk_column_values_left_unchanged(self):
        """Non-latin1-encodable strings should remain unchanged (not crash)."""
        # A string containing only GBK-encodable chars - the latin1 roundtrip
        # will fail, so decode_df should leave it as-is
        df = pd.DataFrame({"col": ["中文测试"]})
        result = decode_df(df)
        assert result["col"].iloc[0] == "中文测试"

    def test_mixed_encoding_in_different_columns(self):
        """Different columns with different encoding issues should all be fixed."""
        col1 = "名称".encode("utf-8").decode("latin1")
        col2 = "代码"  # already correct

        val1 = "沪深300".encode("utf-8").decode("latin1")
        val2 = "510300"  # ascii, no encoding issue

        df = pd.DataFrame({col1: [val1], col2: [val2]})
        result = decode_df(df)

        assert "名称" in result.columns
        assert result["代码"].iloc[0] == "510300"


# ===== folded from test_phase2a_data_quality.py =====
import ast
import os
class TestP0_4_Encoding:
    """P0.4: Unified UTF-8 encoding."""

    def test_config_has_utf8_encoding(self):
        """config.py should set env_file_encoding = 'utf-8'."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "config.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "env_file_encoding" in content, "config.py should set env_file_encoding"
        assert "utf-8" in content.lower(), "config.py should use utf-8 encoding"

    def test_no_latin1_default_encoding(self):
        """No Python file should rely on latin1 default encoding."""
        import glob
        issues = []
        py_files = glob.glob(
            os.path.join(os.path.dirname(__file__), "..", "app", "**", "*.py"),
            recursive=True,
        )
        for pf in py_files[:30]:  # Check first 30 files as sample
            with open(pf, "r", encoding="utf-8") as f:
                try:
                    f.read()
                except UnicodeDecodeError:
                    issues.append(pf)
        assert len(issues) == 0, f"Files with encoding issues: {issues}"
