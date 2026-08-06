"""调试拍照（capture_single，id=None）不得污染历史列表与纠错。"""

from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


def _make_window(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"camera_settings": {"driver_type": "mock"}}', encoding="utf-8")
    cm = ConfigManager(str(cfg))
    controller = FakeController()
    win = MainWindow(cm, controller)
    return win, controller


def _debug_record():
    return {
        "id": None,
        "timestamp": "2026-08-06T00:00:00",
        "image_path": None,
        "thumbnail_path": None,
        "prediction": "A",
        "confidence": 0.9,
        "corrected_label": None,
    }


def test_debug_capture_not_added_to_history(tmp_path):
    win, _ = _make_window(tmp_path)
    win._update_result_display(_debug_record())
    assert win.history_list_widget.count() == 0
    assert not win.correction_button.isEnabled()
    assert "调试捕获" in win.result_label.text()


def test_normal_capture_added_to_history(tmp_path):
    win, _ = _make_window(tmp_path)
    rec = _debug_record()
    rec["id"] = 1
    rec["image_path"] = str(tmp_path / "x.png")
    win._update_result_display(rec)
    assert win.history_list_widget.count() == 1
    assert win.correction_button.isEnabled()
