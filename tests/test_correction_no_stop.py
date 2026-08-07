"""纠错不得中断产线采集的测试。

新 UI（v2）纠错走 CorrectionPopup 气泡：点横幅 ✎ → 弹出 → 选品级 → close。
验证纠错只调 correct_prediction，绝不调 stop_system。
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
    # 模拟一条已出品的记录（result_updated → _on_result → _last_rec）
    rec = {
        "id": 7,
        "timestamp": "2026-08-06T00:00:00",
        "image_path": None,
        "thumbnail_path": None,
        "prediction": "A",
        "confidence": 0.9,
        "corrected_label": None,
        "quality_status": "ok",
    }
    controller.result_updated.emit(rec)
    return win, controller


def test_correction_does_not_stop_system(tmp_path):
    """点气泡选 B → correct_prediction 被调，stop_system 不被调。"""
    win, controller = _make_window(tmp_path)

    win._on_correction_requested()
    assert win._popup is not None
    win._popup._click("B")  # 模拟点 B 按钮

    assert controller.stop_calls == 0, "纠错不应调用 stop_system（产线不停）"
    assert controller.corrections == [(7, "B")]


def test_correction_cancel_keeps_status(tmp_path):
    """弹气泡后关闭不选 → 不纠错，状态不变。"""
    win, controller = _make_window(tmp_path)
    before = win._status

    win._on_correction_requested()
    assert win._popup is not None
    # 用户按 Esc / 点外部 → popup close，不 emit grade_selected
    win._popup.close()

    assert controller.stop_calls == 0
    assert controller.corrections == []
    assert win._status == before, "取消纠错后状态不应改变"
