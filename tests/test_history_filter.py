"""历史记录检索/筛选/CSV 导出测试。"""

import json

from app.services.database_service import DatabaseService
from app.utils.config_manager import ConfigManager


def _make_db(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"data_paths": {"db_filename": str(tmp_path / "moss.db")}}),
        encoding="utf-8",
    )
    return DatabaseService(ConfigManager(str(cfg)))


def _seed(db):
    db.add_record("2026-08-01T00:00:00", "/a.png", "A", 0.9)
    db.add_record("2026-08-02T00:00:00", "/b.png", "B", 0.8)
    db.add_record(
        "2026-08-03T00:00:00", "/c.png", None, None,
        quality_status="rejected_blur", rejected_reason="模糊",
    )


def test_search_by_prediction(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    rows = db.search_records(prediction="B")
    assert len(rows) == 1 and rows[0][4] == "B"
    db.close()


def test_search_rejected_only(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    rows = db.search_records(quality_status="rejected")
    assert len(rows) == 1 and rows[0][7] == "rejected_blur"
    db.close()


def test_search_time_range(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    rows = db.search_records(
        start_time="2026-08-02T00:00:00", end_time="2026-08-02T23:59:59"
    )
    assert len(rows) == 1 and rows[0][4] == "B"
    db.close()


def test_export_csv_writes_parseable(tmp_path):
    from app.controllers.system_controller import export_records_csv

    rows = [(1, "2026-08-01T00:00:00", "/a.png", None, "A", 0.9, None, "ok")]
    out = tmp_path / "out.csv"
    n = export_records_csv(str(out), rows)
    assert n == 1
    text = out.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    assert lines[0] == "id,timestamp,image_path,thumbnail_path,prediction,confidence,corrected_label,quality_status"
    assert lines[1].startswith("1,2026-08-01")


def test_history_filter_reloads_list(tmp_path):
    """新 UI（v2）：HistoryList → _on_filter → controller.search_records_paged → set_page。"""
    from app.ui.main_window import MainWindow

    from tests.fakes import FakeController

    cfg = tmp_path / "config.json"
    cfg.write_text('{"camera_settings": {"driver_type": "mock"}}', encoding="utf-8")
    ctrl = FakeController()
    ctrl.paged_rows = [{"id": 1, "timestamp": "2026-08-01T00:00:00", "image_path": "x.png",
                        "thumbnail_path": None, "prediction": "A", "confidence": 0.9,
                        "corrected_label": None, "quality_status": "ok"}]
    ctrl.paged_total = 1
    win = MainWindow(ConfigManager(str(cfg)), ctrl)

    win._on_filter({"prediction": "A", "quality_status": None})

    assert win.history._list.count() == 1
    assert ctrl.last_paged == {"prediction": "A", "quality_status": None, "page": 1}
