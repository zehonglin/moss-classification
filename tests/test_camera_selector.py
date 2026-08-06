"""相机序列号选择与机型信息测试。"""

import json

import pytest

from app.drivers.camera_selector import (
    read_device_model,
    read_device_serial,
    select_device_index,
)
from app.utils.config_manager import ConfigManager


class FakeUsbInfo:
    def __init__(self, serial="", model=""):
        self.chSerialNumber = serial.encode() if serial else b""
        self.chModelName = model.encode() if model else b""


class FakeSpecial:
    def __init__(self, serial="", model=""):
        self.stUsb3VInfo = FakeUsbInfo(serial, model)


class FakeInfo:
    def __init__(self, serial="", model=""):
        self.SpecialInfo = FakeSpecial(serial, model)


class FakeDeviceList:
    def __init__(self, infos):
        self.nDeviceNum = len(infos)
        self.pDeviceInfo = infos


def test_read_serial_and_model():
    info = FakeInfo("SN123", "MV-123")
    assert read_device_serial(info) == "SN123"
    assert read_device_model(info) == "MV-123"


def test_select_first_when_serial_empty():
    lst = FakeDeviceList([FakeInfo("A"), FakeInfo("B")])
    assert select_device_index(lst, "") == 0


def test_select_by_serial():
    lst = FakeDeviceList([FakeInfo("A"), FakeInfo("B")])
    assert select_device_index(lst, "B") == 1


def test_select_missing_serial_raises():
    lst = FakeDeviceList([FakeInfo("A")])
    with pytest.raises(RuntimeError):
        select_device_index(lst, "Z")


def test_select_empty_device_list_raises():
    with pytest.raises(RuntimeError):
        select_device_index(FakeDeviceList([]), "")


def test_camera_serial_config_default_empty(tmp_path):
    cm = ConfigManager(str(tmp_path / "config.json"))
    assert cm.get("camera_settings.camera_serial") == ""


def test_hikvision_camera_accepts_serial():
    from app.drivers.hikvision_driver import HikvisionCamera

    cam = HikvisionCamera(serial_number="SN1")
    assert cam.serial_number == "SN1"


def test_connect_emits_camera_info(tmp_path):
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
    ctrl = SystemController(ConfigManager(str(cfg)))
    try:
        ctrl.camera.device_serial = "MOCK-0001"
        infos = []
        ctrl.camera_info.connect(infos.append)
        ctrl.connect_camera()
        assert infos and "MOCK-0001" in infos[0]
    finally:
        ctrl.shutdown()
