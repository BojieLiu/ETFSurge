"""数据解码工具函数。

处理 akshare 等数据源返回的 latin1 编码乱码问题。
"""

from typing import Any

import pandas as pd


def decode_df(df: pd.DataFrame) -> pd.DataFrame:
    """原地修复 akshare 返回的乱码数据。

    部分 akshare 接口返回的字符串列包含 latin1→utf-8 双倍编码的乱码，
    需要重新编码才能正确显示中文。

    修复范围:
    1. 列名: ``bytes`` 类型的列名解码为 ``str``。
    2. 列值: object 列中每个字符串尝试 ``latin1 → utf-8`` 重解码。

    Args:
        df: 待修复的 DataFrame，原地修改。

    Returns:
        修复后的 DataFrame。
    """
    if df is None or df.empty:
        return df

    # 1. 修复列名
    renamed: dict[str, str] = {}
    for col in df.columns:
        if isinstance(col, bytes):
            try:
                renamed[col] = col.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    renamed[col] = col.decode("latin1")
                except UnicodeDecodeError:
                    renamed[col] = col.decode("gbk", errors="replace")
        elif isinstance(col, str):
            try:
                cleaned = col.encode("latin1").decode("utf-8")
                if cleaned != col:
                    renamed[col] = cleaned
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    if renamed:
        df.rename(columns=renamed, inplace=True)

    # 2. 修复 string 列的值（akshare 常见乱码）
    for col in df.select_dtypes(include=["object", "str"]).columns:
        fixed: list[Any] = []
        for x in df[col]:
            if isinstance(x, str):
                try:
                    fixed.append(x.encode("latin1").decode("utf-8"))
                except (UnicodeEncodeError, UnicodeDecodeError):
                    # 单元格级保护：正确 UTF-8 的值不会触发异常，保持原值
                    fixed.append(x)
            else:
                fixed.append(x)
        df[col] = fixed

    return df
