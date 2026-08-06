"""纠错不得中断产线采集的测试。"""

from PySide6.QtCore import QObject, Signal

import app.ui.main_window as mw_mod
from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager


class FakeController(QObject):
    image_updated = Signal(object)
    result_updated = Signal(dict)
    status_updated = Signal(str)
    error_occurred = Signal(str)
    disk_space_warning = Signal(str)
    model_loaded = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.status = "RUNNING"
        self.camera = type("FakeCam", (), {"is_connected": lambda self: True})()
        self.stop_calls = 0
        self.corrections = []

    def get_recent_records(self):
        return []

    def get_available_models(self):
        return []

    def stop_system(self):
        self.stop_calls += 1

    def correct_prediction(self, record_id, label):
        self.corrections.append((record_id, label))


def _make_window(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"camera_settings": {"driver_type": "mock"}}', encoding="utf-8")
    cm = ConfigManager(str(cfg))
    controller = FakeController()
    win = MainWindow(cm, controller)
    win.last_record_id = 7
    win.last_prediction = "A"
    return win, controller


def test_correction_does_not_stop_system(tmp_path, monkeypatch):
    win, controller = _make_window(tmp_path)

    monkeypatch.setattr(
        mw_mod.QInputDialog, "getText", staticmethod(lambda *a, **k: ("B", True))
    )
    win._show_correction_dialog()

    assert controller.stop_calls == 0, "纠错不应调用 stop_system（产线不停）"
    assert controller.corrections == [(7, "B")]


def test_correction_cancel_keeps_status(tmp_path, monkeypatch):
    win, controller = _make_window(tmp_path)
    before = win.status

    monkeypatch.setattr(
        mw_mod.QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False))
    )
    win._show_correction_dialog()

    assert controller.stop_calls == 0
    assert controller.corrections == []
    assert win.status == before, "取消纠错后状态不应改变"
