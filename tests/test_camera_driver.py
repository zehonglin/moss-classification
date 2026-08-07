"""相机驱动选择与静默降级防护测试。"""

import sys

import pytest

from app.controllers.system_controller import create_camera
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


def _config_with_driver(tmp_path, driver):
    cfg = tmp_path / "config.json"
    cfg.write_text(f'{{"camera_settings": {{"driver_type": "{driver}"}}}}', encoding="utf-8")
    return ConfigManager(str(cfg))


def test_config_default_driver_is_hikvision(tmp_path):
    cm = ConfigManager(str(tmp_path / "config.json"))
    assert cm.get("camera_settings.driver_type") == "hikvision"


def test_create_camera_mock_explicit_returns_mock():
    cam = create_camera("mock")
    assert cam.__class__.__name__ == "MockCamera"


def test_create_camera_unknown_driver_raises():
    with pytest.raises(ValueError):
        create_camera("bogus")


def test_create_camera_hikvision_sdk_missing_raises_not_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "app.drivers.hikvision_driver", None)
    with pytest.raises(ImportError):
        create_camera("hikvision")


def test_mock_mode_badge_visible(tmp_path):
    """新 UI 已移除 mock_badge（ParamSidebar/TopStatBar 均无此元素），
    仅验证 MainWindow 在 mock 驱动下构造不崩。"""
    from app.ui.main_window import MainWindow

    cm = _config_with_driver(tmp_path, "mock")
    win = MainWindow(cm, FakeController())
    assert win is not None


def test_hikvision_mode_badge_hidden(tmp_path):
    """新 UI 已移除 mock_badge；验证 hikvision 配置下构造不崩。"""
    from app.ui.main_window import MainWindow

    cm = _config_with_driver(tmp_path, "hikvision")
    win = MainWindow(cm, FakeController())
    assert win is not None
