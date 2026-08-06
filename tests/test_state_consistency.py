"""状态机一致性：worker 错误后恢复预览触发；UI 错误不清空连接状态。"""

import json

from app.controllers.system_controller import SystemController, STATUS_PREVIEWING
from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


def _make_controller(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "camera_settings": {"driver_type": "mock"},
                "model_settings": {
                    "current_model_name": "nonexistent.pth",
                    "models_directory": str(tmp_path / "models"),
                },
                "data_paths": {"db_filename": str(tmp_path / "moss.db")},
            }
        ),
        encoding="utf-8",
    )
    return SystemController(ConfigManager(str(cfg)))


def _make_window(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"camera_settings": {"driver_type": "mock"}}', encoding="utf-8")
    cm = ConfigManager(str(cfg))
    return MainWindow(cm, FakeController())


def test_worker_error_restores_preview_trigger(tmp_path):
    ctrl = _make_controller(tmp_path)
    ctrl.camera.connect()
    calls = []
    real = ctrl.camera.set_trigger_config

    def record(mode, *args, **kwargs):
        calls.append(mode)
        real(mode, *args, **kwargs)

    ctrl.camera.set_trigger_config = record

    ctrl._handle_worker_error("boom")

    assert calls and calls[-1] == "preview", "worker 错误后应先把触发模式切回 preview"
    assert ctrl.preview_timer.isActive(), "worker 错误后应恢复预览取流"


def test_ui_error_keeps_connection_state(tmp_path):
    win = _make_window(tmp_path)
    win._update_status(STATUS_PREVIEWING)
    assert win.status == STATUS_PREVIEWING

    win._handle_error("some recoverable error")

    assert win.status == STATUS_PREVIEWING, "可恢复错误不应把状态重置为 IDLE"
    assert "错误" in win.result_label.text()
