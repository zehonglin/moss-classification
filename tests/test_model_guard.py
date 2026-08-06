"""模型未加载时禁止采集的防护测试。"""

import json

from app.drivers.mock_driver import MockCamera
from app.services.model_service import ModelService
from app.utils.config_manager import ConfigManager


def test_is_ready_false_without_model():
    ms = ModelService(model_name=None)
    assert ms.is_ready() is False


def test_is_ready_true_when_backend_loaded():
    ms = ModelService(model_name=None)
    ms.session = object()
    assert ms.is_ready() is True
    ms.session = None
    ms.model = object()
    assert ms.is_ready() is True


class UnloadedModel:
    """predict 始终返回"模型未加载"的假模型。"""

    def predict(self, q_image):
        return "模型未加载", 0.0


class RecordingDB:
    """记录是否被写入；模型未加载时写库应视为测试失败。"""

    def __init__(self):
        self.calls = 0

    def add_record(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("模型未加载时不应写入数据库")


def test_worker_stops_when_model_unloaded_and_saves_nothing(tmp_path):
    from app.controllers.system_controller import SystemWorker

    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "camera_settings": {
                    "driver_type": "mock",
                    "trigger": {"mode": "hardware"},
                },
                "quality_check": {"enabled": False},
                "data_paths": {"collected_data_directory": str(tmp_path / "images")},
            }
        ),
        encoding="utf-8",
    )
    cm = ConfigManager(str(cfg))
    camera = MockCamera()
    camera.connect()
    db = RecordingDB()
    worker = SystemWorker(camera, UnloadedModel(), db, cm)
    errors = []
    worker.error_occurred.connect(errors.append)

    worker.start_loop()  # 应自行停止

    assert errors, "应发出模型未加载告警"
    assert not worker.is_running(), "worker 应已停止"
    assert db.calls == 0, "模型未加载时不应写库"
    assert not (tmp_path / "images").exists(), "模型未加载时不应保存图像"


def test_start_system_refuses_without_model(tmp_path):
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
    cm = ConfigManager(str(cfg))
    controller = SystemController(cm)
    try:
        errors = []
        controller.error_occurred.connect(errors.append)
        controller.start_system()
        assert errors, "应拒绝启动并发出错误"
        assert "模型" in errors[0]
        assert not controller.worker_thread.isRunning()
    finally:
        controller.shutdown()
