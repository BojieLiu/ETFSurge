# -*- coding: utf-8 -*-
"""round31 R93: data_dir 解析在容器 4 斜杠 URL 下丢失前导斜杠 → 相对路径裂。

根因（§4.1）：`config.py:148` 正则 `^sqlite(?:\\+\\w+)?:///+(.*)` 对容器
`sqlite+aiosqlite:////app/data/portfolio.db`（4 斜杠 = 绝对路径语义）贪婪吃掉
第 4 个前导斜杠 → 捕获 `app/data/portfolio.db` → `Path().parent = "app/data"`
（相对）→ 容器 CWD=/app 下解析为 /app/app/data（镜像层，重启即丢）。
本地恰绿是因为 Windows 盘符使相对值仍为绝对（isabs True）。

修复：正则改 `^sqlite(?:\+\w+)?:///?(.*)` 保留第 4 斜杠；validator 后置断言
data_dir 为绝对路径，非绝对则 WARNING + 回退项目默认 _DATA_DIR。

无网络：纯配置解析断言。
"""
import os
import pytest


def _settings(database_url: str):
    """构造 Settings 实例（绕开模块级 settings 单例）。"""
    from app.config import Settings
    return Settings(database_url=database_url, _env_file=None)


def test_container_4slash_url_keeps_leading_slash():
    """容器 URL `sqlite+aiosqlite:////app/data/portfolio.db` → data_dir=/app/data。"""
    s = _settings("sqlite+aiosqlite:////app/data/portfolio.db")
    d = s.data_dir
    assert d, "data_dir 应为非空"
    assert os.path.isabs(str(d)), f"容器 data_dir 应为绝对路径: {d}"
    assert str(d).replace("\\", "/") == "/app/data", f"应解析到 /app/data，实际 {d}"


def test_windows_local_url_still_parses():
    """本地盘符 URL 不受影响（3 斜杠 + 盘符）。"""
    s = _settings("sqlite+aiosqlite:///E:/ETF_Surge/data/portfolio.db")
    assert os.path.isabs(str(s.data_dir))
    assert "ETF_Surge" in str(s.data_dir)


def test_relative_parse_falls_back_to_project_data_dir():
    """负向：解析出相对路径（非绝对）→ WARNING 回退项目默认 data 目录。"""
    from app.config import _DATA_DIR
    s = _settings("sqlite+aiosqlite:///relative/data/portfolio.db")
    d = str(s.data_dir)
    assert os.path.isabs(d), f"data_dir 必须为绝对路径，实际 {d}"
    # 回退到项目默认 data（与 _DATA_DIR 一致或为其父目录的子集语义）
    assert os.path.samefile(d, str(_DATA_DIR)), f"应回退到 {_DATA_DIR}，实际 {d}"


def test_explicit_data_dir_wins():
    """DATA_DIR env 显式指定时优先，不解析 database_url。"""
    from app.config import Settings
    s = Settings(
        database_url="sqlite+aiosqlite:////app/data/portfolio.db",
        data_dir="/custom/data",
        _env_file=None,
    )
    assert s.data_dir == "/custom/data"
