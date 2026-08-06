"""纠错不得中断产线采集的测试。"""

import app.ui.main_window as mw_mod
from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


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
