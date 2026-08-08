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
        self.reconnect_fails = False
        self.device_serial = "SN-X"
        self.device_model = "M"

    def is_connected(self):
        return self.connected

    def reconnect(self):
        self.reconnect_calls += 1
        if self.reconnect_fails:
            raise RuntimeError("reconnect failed (no device)")
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


def test_try_reconnect_skipped_when_never_connected(tmp_path):
    """从未成功连接过 → _try_reconnect 不应尝试重连（避免启动后空转刷屏）。"""
    ctrl = _make_controller(tmp_path)
    cam = FakeCam()  # connected=False，但有 reconnect()
    ctrl.camera = cam
    try:
        ctrl._try_reconnect()
        assert cam.reconnect_calls == 0
    finally:
        ctrl.shutdown()


def test_try_reconnect_recovers_and_notifies(tmp_path):
    """曾成功连接后掉线 → _try_reconnect 恢复并通知。"""
    ctrl = _make_controller(tmp_path)
    cam = FakeCam()
    ctrl.camera = cam
    ctrl._was_connected = True  # 模拟"连上过再掉线"
    infos = []
    ctrl.camera_info.connect(infos.append)
    try:
        ctrl._try_reconnect()
        assert cam.connected
        assert cam.reconnect_calls == 1
        assert infos and "重连" in infos[0]
    finally:
        ctrl.shutdown()


def test_disconnect_disarms_auto_reconnect(tmp_path):
    """用户主动断开后，_try_reconnect 不应再尝试重连（避免违背用户意图自动回连）。"""
    ctrl = _make_controller(tmp_path)
    cam = FakeCam()
    ctrl.camera = cam
    ctrl._was_connected = True  # 模拟之前连上过
    try:
        ctrl.disconnect_camera()
        assert ctrl._was_connected is False
        ctrl._try_reconnect()
        assert cam.reconnect_calls == 0  # 断开后不再重连
    finally:
        ctrl.shutdown()


def test_reconnect_gives_up_after_max_attempts(tmp_path):
    """连续重连失败达上限(10)后：停止重连 + 主动断开（_was_connected 复位）。"""
    from app.controllers.system_controller import SystemController

    max_attempts = SystemController.MAX_RECONNECT_ATTEMPTS
    ctrl = _make_controller(tmp_path)
    cam = FakeCam()
    cam.reconnect_fails = True
    ctrl.camera = cam
    ctrl._was_connected = True
    warns = []
    ctrl.disk_space_warning.connect(warns.append)
    try:
        for _ in range(max_attempts):
            ctrl._try_reconnect()
        assert cam.reconnect_calls == max_attempts
        assert ctrl._was_connected is False  # 放弃 → 解除自动重连
        # 超过上限后不再尝试
        ctrl._try_reconnect()
        assert cam.reconnect_calls == max_attempts
        # 给用户一条"已停止"的通知
        assert any("已停止" in w for w in warns)
    finally:
        ctrl.shutdown()
