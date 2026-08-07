"""拒采帧端到端行为：入库（不出品级）+ 原图/缩略图保存 + UI 展示。"""

import json
import os

from app.controllers.system_controller import SystemWorker
from app.drivers.mock_driver import MockCamera
from app.services.database_service import DatabaseService
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


class RecordingModel:
    """拒采帧不应触发推理。"""

    def predict(self, q_image):
        raise AssertionError("拒采帧不应调用模型推理")


def test_worker_rejected_frame_saved_and_db_marked(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "camera_settings": {
                    "driver_type": "mock",
                    "trigger": {"mode": "hardware"},
                },
                "data_paths": {
                    "db_filename": str(tmp_path / "moss.db"),
                    "collected_data_directory": str(tmp_path / "images"),
                },
                "model_settings": {
                    "current_model_name": "nonexistent.pth",
                    "models_directory": str(tmp_path / "models"),
                },
            }
        ),
        encoding="utf-8",
    )
    cm = ConfigManager(str(cfg))
    camera = MockCamera()
    camera.connect()  # 黑色帧 → 欠曝拒采
    db = DatabaseService(cm)
    worker = SystemWorker(camera, RecordingModel(), db, cm)
    results = []
    worker.result_ready.connect(lambda r: (results.append(r), worker.stop_loop()))

    worker.start_loop()

    assert results, "拒采帧也应产出记录"
    rec = results[0]
    assert rec["prediction"] is None
    assert rec["quality_status"] == "rejected_underexposed"
    assert os.path.exists(rec["image_path"]), "拒采帧原图必须保存"
    assert os.path.exists(rec["thumbnail_path"]), "拒采帧缩略图必须保存"
    row = db.get_record(rec["id"])
    assert row[7] == "rejected_underexposed"
    assert row[4] is None
    db.close()


def test_ui_rejected_record_shows_red_and_disables_correction(tmp_path):
    """新 UI（v2）：拒采记录 → banner grade="rejected" + 纠错按钮不可见 + 进历史列表。"""
    from app.ui.main_window import MainWindow

    cfg = tmp_path / "config.json"
    cfg.write_text('{"camera_settings": {"driver_type": "mock"}}', encoding="utf-8")
    ctrl = FakeController()
    win = MainWindow(ConfigManager(str(cfg)), ctrl)

    win._on_result(
        {
            "id": 1,
            "timestamp": "2026-08-06T00:00:00",
            "image_path": str(tmp_path / "x.png"),
            "thumbnail_path": None,
            "prediction": None,
            "confidence": None,
            "corrected_label": None,
            "quality_status": "rejected_blur",
            "rejected_reason": "画面模糊",
        }
    )

    assert win.history._list.count() == 1
    # offscreen Qt 用 isHidden() 不用 isVisible()
    assert win.banner._edit.isHidden(), "拒采记录不应允许纠错"
    assert win.banner.property("grade") == "rejected"
