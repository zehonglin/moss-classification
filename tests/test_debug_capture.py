"""调试拍照（capture_single，id=None）不得污染历史列表与纠错。

新 UI（v2）：id=None → _on_result 走 debug 分支（banner_state.kind="debug"，
show_edit=False），不调 history.append_live。
"""

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
        "quality_status": "ok",
    }


def test_debug_capture_not_added_to_history(tmp_path):
    """id=None 的调试捕获：不进历史列表，横幅纠错按钮不可见。"""
    win, _ = _make_window(tmp_path)
    win._on_result(_debug_record())
    assert win.history._list.count() == 0
    # offscreen Qt 用 isHidden() 不用 isVisible()（isVisible 恒 False）
    assert win.banner._edit.isHidden()
    assert win.banner.property("grade") == "wait"  # debug 横幅用 wait 色


def test_normal_capture_added_to_history(tmp_path):
    """id 非 None 的正常记录：进历史列表，横幅纠错按钮可见。"""
    win, _ = _make_window(tmp_path)
    rec = _debug_record()
    rec["id"] = 1
    rec["image_path"] = str(tmp_path / "x.png")
    win._on_result(rec)
    assert win.history._list.count() == 1
    assert not win.banner._edit.isHidden()
