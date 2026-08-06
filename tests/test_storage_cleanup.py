"""存储参数化与容量水位清理（决策 A）测试。"""

import json
import collections
from datetime import datetime, timedelta

from app.controllers.system_controller import SystemController, SystemWorker
from app.drivers.mock_driver import MockCamera
from app.services.database_service import DatabaseService
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
                "data_paths": {
                    "db_filename": str(tmp_path / "moss.db"),
                    "collected_data_directory": str(tmp_path / "images"),
                },
            }
        ),
        encoding="utf-8",
    )
    return SystemController(ConfigManager(str(cfg)))


def test_storage_config_defaults(tmp_path):
    cm = ConfigManager(str(tmp_path / "config.json"))
    assert cm.get("storage.retention_days") == 60
    assert cm.get("storage.disk_watermark_gb") == 50
    assert cm.get("storage.cleanup_min_age_days") == 7
    assert cm.get("storage.cleanup_interval_hours") == 1
    assert cm.get("storage.critical_free_gb") == 5


def test_db_batch_delete_api(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"data_paths": {"db_filename": str(tmp_path / "moss.db")}}),
        encoding="utf-8",
    )
    db = DatabaseService(ConfigManager(str(cfg)))
    db.add_record("2026-01-01T00:00:00", "/tmp/a.png", "A", 0.9)
    db.add_record("2026-02-01T00:00:00", "/tmp/b.png", "B", 0.8)

    rows = db.delete_records_before_in_batches("2026-01-15T00:00:00", limit=10)
    assert len(rows) == 1
    assert rows[0][1] == "/tmp/a.png"
    db.delete_records_by_ids([rows[0][0]])
    assert db.get_record_count() == 1
    db.close()


def test_retention_cleanup_deletes_old_records_and_files(tmp_path):
    ctrl = _make_controller(tmp_path)
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    old_ts = (datetime.now() - timedelta(days=61)).isoformat()
    new_ts = (datetime.now() - timedelta(days=1)).isoformat()
    old_img = img_dir / "old.png"
    old_img.write_bytes(b"x")
    old_thumb = img_dir / "old_thumb.png"
    old_thumb.write_bytes(b"x")
    new_img = img_dir / "new.png"
    new_img.write_bytes(b"x")
    ctrl.db_service.add_record(old_ts, str(old_img), "A", 0.9, thumbnail_path=str(old_thumb))
    ctrl.db_service.add_record(new_ts, str(new_img), "B", 0.8)

    n_rec, n_files = ctrl.cleanup_old_records()

    assert n_rec == 1
    assert n_files == 2
    assert not old_img.exists()
    assert not old_thumb.exists()
    assert new_img.exists()
    assert ctrl.db_service.get_record_count() == 1
    ctrl.shutdown()


def test_watermark_cleanup_respects_min_age(tmp_path, monkeypatch):
    ctrl = _make_controller(tmp_path)
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    old_ts = (datetime.now() - timedelta(days=10)).isoformat()
    recent_ts = (datetime.now() - timedelta(days=1)).isoformat()
    old_img = img_dir / "old.png"
    old_img.write_bytes(b"x")
    recent_img = img_dir / "recent.png"
    recent_img.write_bytes(b"x")
    ctrl.db_service.add_record(old_ts, str(old_img), "A", 0.9)
    ctrl.db_service.add_record(recent_ts, str(recent_img), "B", 0.8)

    # 模拟磁盘不足：剩余 5GB < 水位 50GB（cleanup_min_age_days=7）
    DU = collections.namedtuple("DU", "total used free")
    monkeypatch.setattr(
        "shutil.disk_usage",
        lambda p: DU(100 * 1024**3, 95 * 1024**3, 5 * 1024**3),
    )

    n_rec, _ = ctrl.cleanup_old_records()

    assert n_rec == 1, "水位清理应删除超过 min_age 的最旧记录"
    assert not old_img.exists()
    assert recent_img.exists(), "7 天内的新记录不应被水位清理删除"
    ctrl.shutdown()


def test_worker_disk_thresholds_from_config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "camera_settings": {
                    "driver_type": "mock",
                    "trigger": {"mode": "hardware"},
                },
                "storage": {"disk_watermark_gb": 20.0, "critical_free_gb": 2.0},
            }
        ),
        encoding="utf-8",
    )
    cm = ConfigManager(str(cfg))
    worker = SystemWorker(MockCamera(), None, None, cm)
    assert worker._disk_monitor.warning_threshold_bytes == int(20 * 1024**3)
    assert worker._disk_monitor.critical_threshold_bytes == int(2 * 1024**3)
