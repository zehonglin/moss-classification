import os
import pathlib
import shutil
import uuid

import pytest

# Qt 测试必须无窗口运行（无显示器/CI 环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_TMP_ROOT = pathlib.Path(".pytest_tmp")
_TMP_DIRS: list[pathlib.Path] = []


@pytest.fixture
def tmp_path():
    """工作区内临时目录。

    沙箱禁止写系统 Temp，且 pytest 内置 basetemp 在本环境会创建带受限 ACL 的目录，
    因此用普通 mkdir 在项目 .pytest_tmp/ 下自建临时目录（该目录已加入 .gitignore）。
    """
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    d = _TMP_ROOT / f"t-{uuid.uuid4().hex[:12]}"
    d.mkdir()
    _TMP_DIRS.append(d)
    yield d


def pytest_sessionfinish(session, exitstatus):
    for d in _TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)
