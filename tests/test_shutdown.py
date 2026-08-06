"""shutdown 竞态：worker 未停止时不得强行断开相机/关闭 DB。"""

import json

from app.controllers.system_controller import SystemController
from app.utils.config_manager import ConfigManager


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


class StuckThread:
    """模拟 worker 线程卡死在相机取帧：isRunning 恒 True，wait 恒 False。"""

    def isRunning(self):
        return True

    def wait(self, ms):
        return False


def test_shutdown_skips_camera_and_db_when_worker_stuck(tmp_path, monkeypatch):
    ctrl = _make_controller(tmp_path)
    ctrl.camera.connect()
    monkeypatch.setattr(ctrl, "worker_thread", StuckThread())
    monkeypatch.setattr(ctrl.worker, "stop_loop", lambda: None)

    closed = []
    real_close = ctrl.db_service.close

    def fake_close():
        closed.append(True)
        real_close()

    ctrl.db_service.close = fake_close

    ctrl.shutdown()

    assert closed == [], "worker 未停止时不应关闭 DB（进程退出兜底）"
    assert ctrl.camera.is_connected(), "worker 未停止时不应断开相机（避免 SDK 竞态）"


def test_shutdown_closes_db_and_camera_when_worker_idle(tmp_path):
    ctrl = _make_controller(tmp_path)
    ctrl.camera.connect()
    ctrl.shutdown()
    assert not ctrl.camera.is_connected()
    assert ctrl.db_service._connection is None
