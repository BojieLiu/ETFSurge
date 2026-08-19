"""tests_ok_marker 全量测试凭据（round30 方案 B）单测。

核心：mark 写入的凭据在代码面未变时 check 通过（pre-commit 可复用跳过重复全量）；
任何代码变更/过期/损坏 → check 失败（pre-commit 恢复全量，安全网不失效）。
"""
import json
import os
import time

import pytest

from scripts.tests_ok_marker import files_hash, mark, check


@pytest.fixture
def tmp_project(tmp_path):
    """临时项目树：backend/scripts/app/tests 各一个文件。"""
    backend = tmp_path / "backend"
    (backend / "scripts").mkdir(parents=True)
    (backend / "app").mkdir()
    (backend / "tests").mkdir()
    (backend / "app" / "main.py").write_text("APP=1\n", encoding="utf-8")
    (backend / "tests" / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (backend / "scripts" / "tool.py").write_text("TOOL=1\n", encoding="utf-8")
    marker = tmp_path / "logs" / "patrol" / "tests_ok.json"
    return {
        "backend": str(backend),
        "marker": str(marker),
        "roots": [str(backend / "app"), str(backend / "tests"), str(backend / "scripts")],
    }


def test_mark_then_check_valid(tmp_project):
    """写凭据后代码面未变 → check 通过（pre-commit 可复用）。"""
    mark(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
         roots=tmp_project["roots"], extra=[])
    assert check(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
                 roots=tmp_project["roots"], extra=[]) is True


def test_check_missing_marker(tmp_project):
    """无凭据 → check 失败（需跑全量）。"""
    assert check(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
                 roots=tmp_project["roots"], extra=[]) is False


def test_check_fails_when_code_changed(tmp_project):
    """代码变更（app 下文件改动）→ 指纹变化 → check 失败（安全网恢复全量）。"""
    mark(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
         roots=tmp_project["roots"], extra=[])
    assert check(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
                 roots=tmp_project["roots"], extra=[]) is True
    # 修改 backend/app/main.py 内容
    main_py = os.path.join(tmp_project["backend"], "app", "main.py")
    with open(main_py, "a", encoding="utf-8") as f:
        f.write("# changed\n")
    assert check(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
                 roots=tmp_project["roots"], extra=[]) is False


def test_check_fails_when_new_file_added(tmp_project):
    """新增测试文件 → 指纹变化 → check 失败。"""
    mark(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
         roots=tmp_project["roots"], extra=[])
    new_test = os.path.join(tmp_project["backend"], "tests", "test_new.py")
    with open(new_test, "w", encoding="utf-8") as f:
        f.write("def test_new(): pass\n")
    assert check(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
                 roots=tmp_project["roots"], extra=[]) is False


def test_check_fails_when_expired(tmp_project):
    """凭据过期（> TTL）→ check 失败。"""
    mark(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
         roots=tmp_project["roots"], extra=[])
    assert check(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
                 roots=tmp_project["roots"], extra=[], ttl=0.001) is False


def test_check_fails_when_corrupted(tmp_project):
    """凭据损坏 → check 失败。"""
    os.makedirs(os.path.dirname(tmp_project["marker"]), exist_ok=True)
    with open(tmp_project["marker"], "w", encoding="utf-8") as f:
        f.write("not-json{{{")
    assert check(marker_path=tmp_project["marker"]) is False


def test_files_hash_changes_on_edit(tmp_project):
    """指纹对文件编辑敏感（内容/时间戳任一变化即变）。"""
    h1 = files_hash(project_root=tmp_project["backend"], roots=tmp_project["roots"], extra=[])
    time.sleep(0.02)
    main_py = os.path.join(tmp_project["backend"], "app", "main.py")
    with open(main_py, "a", encoding="utf-8") as f:
        f.write("# edit\n")
    h2 = files_hash(project_root=tmp_project["backend"], roots=tmp_project["roots"], extra=[])
    assert h1 != h2


def test_marker_content(tmp_project):
    """凭据内容含 head_sha / files_hash / ts。"""
    mark(marker_path=tmp_project["marker"], project_root=tmp_project["backend"],
         roots=tmp_project["roots"], extra=[])
    with open(tmp_project["marker"], encoding="utf-8") as f:
        data = json.load(f)
    assert "head_sha" in data and "files_hash" in data and "ts" in data
    assert data["files_hash"] == files_hash(
        project_root=tmp_project["backend"], roots=tmp_project["roots"], extra=[]
    )
