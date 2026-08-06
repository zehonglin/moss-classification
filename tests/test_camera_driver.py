"""相机驱动选择与静默降级防护测试。"""

import sys

import pytest
from PySide6.QtCore import QObject, Signal

from app.controllers.system_controller import create_camera
from app.utils.config_manager import ConfigManager


class FakeController(QObject):
    """MainWindow 单测用的最小假控制器（避免真实 SystemController 的 DB/模型副作用）。"""

    image_updated = Signal(object)
    result_updated = Signal(dict)
    status_updated = Signal(str)
    error_occurred = Signal(str)
    disk_space_warning = Signal(str)
    model_loaded = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.status = "IDLE"
        self.camera = type("FakeCam", (), {"is_connected": lambda self: False})()

    def get_recent_records(self):
        return []

    def get_available_models(self):
        return []

    def stop_system(self):
        pass


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
    from app.ui.main_window import MainWindow

    cm = _config_with_driver(tmp_path, "mock")
    win = MainWindow(cm, FakeController())
    assert not win.mock_badge.isHidden()
    assert "模拟" in win.mock_badge.text()


def test_hikvision_mode_badge_hidden(tmp_path):
    from app.ui.main_window import MainWindow

    cm = _config_with_driver(tmp_path, "hikvision")
    win = MainWindow(cm, FakeController())
    assert win.mock_badge.isHidden()
