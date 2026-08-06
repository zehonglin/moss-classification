"""拒采记录的数据库存储（quality_status/rejected_reason）测试。"""

import json

from app.services.database_service import DatabaseService
from app.utils.config_manager import ConfigManager


def test_db_has_quality_columns_and_stores_reject(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"data_paths": {"db_filename": str(tmp_path / "moss.db")}}),
        encoding="utf-8",
    )
    db = DatabaseService(ConfigManager(str(cfg)))
    cols = [c[1] for c in db._connection.execute("PRAGMA table_info(records)").fetchall()]
    assert "quality_status" in cols
    assert "rejected_reason" in cols

    rid = db.add_record(
        "2026-01-01T00:00:00",
        "/tmp/a.png",
        None,
        None,
        quality_status="rejected_blur",
        rejected_reason="画面模糊",
    )
    row = db.get_record(rid)
    assert row[7] == "rejected_blur"
    assert row[8] == "画面模糊"

    recent = db.get_recent_records(limit=1)[0]
    assert recent[7] == "rejected_blur"
    db.close()


def test_normal_record_quality_default_ok(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"data_paths": {"db_filename": str(tmp_path / "moss.db")}}),
        encoding="utf-8",
    )
    db = DatabaseService(ConfigManager(str(cfg)))
    rid = db.add_record("2026-01-02T00:00:00", "/tmp/b.png", "A", 0.9)
    row = db.get_record(rid)
    assert row[7] == "ok"
    assert row[8] is None
    db.close()
