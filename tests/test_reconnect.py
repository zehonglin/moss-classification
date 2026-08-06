"""物理掉线检测与自动重连测试。"""

import json

import pytest

from app.drivers.camera_selector import is_fatal_frame_error
from app.utils.config_manager import ConfigManager


def test_preview_mode_any_failure_is_fatal():
    assert is_fatal_frame_error(0x80000007, "preview") is True
    assert is_fatal_frame_error(0x8000001A, "preview") is True


def test_trigger_mode_timeout_not_fatal():
    # 触发模式下"超时无图"（如 MV_E_NODATA）是正常现象
    assert is_fatal_frame_error(0x80000007, "hardware") is False
    assert is_fatal_frame_error(0x80000007, "software_continuous") is False


def test_trigger_mode_fatal_codes():
    for code in (0x8000001A, 0x80000204, 0x80000300, 0x80000000):
        assert is_fatal_frame_error(code, "hardware") is True, hex(code)


class FakeHandle:
    """模拟 SDK 句柄：可配置 GetImageBuffer 返回码，其余调用为空操作。"""

    def __init__(self, ret=0):
        self.ret = ret
        self.calls = []

    def MV_CC_GetImageBuffer(self, st_out_frame, timeout):
        self.calls.append("get_image")
        return self.ret

    def MV_CC_SetEnumValueByString(self, *a):
        return 0

    def MV_CC_SetFloatValue(self, *a):
        return 0

    def MV_CC_SetIntValue(self, *a):
        return 0

    def MV_CC_SetCommandValue(self, *a):
        return 0


def test_hikvision_marks_disconnected_after_fatal_errors():
    from app.drivers.hikvision_driver import HikvisionCamera

    cam = HikvisionCamera()
    cam.b_is_connected = True
    cam.handle = FakeHandle(ret=0x8000001A)  # MV_E_NORESPONSE
    for _ in range(10):
        assert cam.get_frame(timeout_ms=10) is None
    assert cam.b_is_connected is False


def test_hikvision_trigger_mode_timeout_keeps_connected():
    from app.drivers.hikvision_driver import HikvisionCamera

    cam = HikvisionCamera()
    cam.b_is_connected = True
    cam.handle = FakeHandle(ret=0x80000007)  # 超时无图
    cam.set_trigger_config("hardware", source="Line0")
    for _ in range(30):
        assert cam.get_frame(timeout_ms=10) is None
    assert cam.b_is_connected is True


def _make_controller(tmp_path):
    from app.controllers.system_controller import SystemController

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


class FakeCam:
    def __init__(self):
        self.connected = False
        self.reconnect_calls = 0
        self.device_serial = "SN-X"
        self.device_model = "M"

    def is_connected(self):
        return self.connected

    def reconnect(self):
        self.reconnect_calls += 1
        self.connected = True

    def disconnect(self):
        self.connected = False

    def set_exposure(self, value):
        pass

    def set_resolution(self, w, h):
        pass

    def set_trigger_config(self, *a, **k):
        pass


def test_reconnect_timer_is_active(tmp_path):
    ctrl = _make_controller(tmp_path)
    try:
        assert ctrl.reconnect_timer.isActive()
        assert ctrl.reconnect_timer.interval() == 10000
    finally:
        ctrl.shutdown()


def test_try_reconnect_recovers_and_notifies(tmp_path):
    ctrl = _make_controller(tmp_path)
    cam = FakeCam()
    ctrl.camera = cam
    infos = []
    ctrl.camera_info.connect(infos.append)
    try:
        ctrl._try_reconnect()
        assert cam.connected
        assert cam.reconnect_calls == 1
        assert infos and "重连" in infos[0]
    finally:
        ctrl.shutdown()
