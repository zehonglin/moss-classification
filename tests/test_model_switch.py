"""模型切换竞态：过期加载结果必须丢弃。"""

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


def test_stale_model_load_result_is_discarded(tmp_path):
    ctrl = _make_controller(tmp_path)
    try:
        emitted = []
        ctrl.model_loaded.connect(lambda ok, name: emitted.append((ok, name)))
        ctrl._model_switch_seq = 2  # 最新请求序号

        ctrl._on_model_loaded(True, "old.onnx", 1)  # 过期结果
        assert emitted == []
        assert ctrl.config.get("model_settings.current_model_name") == "nonexistent.pth"

        ctrl._on_model_loaded(True, "new.onnx", 2)  # 当前结果
        assert emitted == [(True, "new.onnx")]
        assert ctrl.config.get("model_settings.current_model_name") == "new.onnx"
    finally:
        ctrl.shutdown()


def test_reload_model_increments_seq(tmp_path):
    ctrl = _make_controller(tmp_path)
    try:
        ctrl.reload_model("a.onnx")
        assert ctrl._model_switch_seq == 1
        ctrl.reload_model("b.onnx")
        assert ctrl._model_switch_seq == 2
    finally:
        ctrl.shutdown()
