"""tests 目录共享 fixtures 注册入口（Z27 §8.1 M4）。

pytest 只从 conftest.py 自动发现 fixtures；db_fixtures.py 中的
task_db / task_mgr 通过在此处导入注册为全局可用，供所有测试文件
按名称直接使用（也兼容 `from tests.db_fixtures import task_mgr` 的显式导入）。
"""
from tests.db_fixtures import task_db, task_mgr  # noqa: F401
