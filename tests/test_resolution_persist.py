"""分辨率持久化回归：set_camera_resolution 无论相机是否连接都应写回 config。

历史 bug：config.set 在 is_connected() 守卫内部，未连接时改分辨率不落盘；
叠加 UI 输入框未初始化（停在区间下限 256），连接后点"应用"会用 256 覆盖 config 的 2048。
修复后口径对齐 set_camera_exposure——config 无条件持久化，硬件仅在连接时下发。
"""

import json


def _make_controller(tmp_path):
    from app.controllers.system_controller import SystemController
    from app.utils.config_manager import ConfigManager

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


class _RecordingCam:
    """记录 set_resolution 调用；connected 可控。"""

    def __init__(self, connected):
        self._connected = connected
        self.res_calls = []

    def is_connected(self):
        return self._connected

    def set_resolution(self, w, h):
        self.res_calls.append((w, h))

    def disconnect(self):
        self._connected = False


def test_set_resolution_persists_to_config_when_disconnected(tmp_path):
    """未连接时改分辨率：config 必须落盘，硬件不得被碰。"""
    ctrl = _make_controller(tmp_path)
    cam = _RecordingCam(connected=False)
    ctrl.camera = cam
    try:
        ctrl.set_camera_resolution(1024, 768)
        assert ctrl.config.get("camera_settings.resolution_width") == 1024
        assert ctrl.config.get("camera_settings.resolution_height") == 768
        assert cam.res_calls == []  # 未连接 → 不下发硬件
    finally:
        ctrl.shutdown()


def test_set_resolution_applies_hardware_when_connected(tmp_path):
    """已连接时改分辨率：硬件下发 + config 落盘。"""
    ctrl = _make_controller(tmp_path)
    cam = _RecordingCam(connected=True)
    ctrl.camera = cam
    try:
        ctrl.set_camera_resolution(2048, 2048)
        assert cam.res_calls == [(2048, 2048)]
        assert ctrl.config.get("camera_settings.resolution_width") == 2048
        assert ctrl.config.get("camera_settings.resolution_height") == 2048
    finally:
        ctrl.shutdown()
