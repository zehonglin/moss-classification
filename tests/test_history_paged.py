"""Task 3: DatabaseService.search_records_paged 分页查询测试。

复用 Task 2 的 _cfg / _add 辅助（命名稳定，见 tests/test_grade_summary.py）。
"""

from app.services.database_service import DatabaseService
from tests.test_grade_summary import _cfg, _add


def test_paged_returns_rows_and_total(tmp_path):
    db = DatabaseService(_cfg(tmp_path))
    for i in range(12):
        _add(db, "A" if i % 2 == 0 else "B")
    rows, total = db.search_records_paged(prediction="A", page=1, page_size=5)
    assert total == 6
    assert len(rows) == 5
    db.close()


def test_paged_second_page(tmp_path):
    db = DatabaseService(_cfg(tmp_path))
    for _ in range(12):
        _add(db, "A")
    rows, total = db.search_records_paged(page=2, page_size=5)
    assert total == 12
    assert len(rows) == 5
    rows3, _ = db.search_records_paged(page=3, page_size=5)
    assert len(rows3) == 2  # 末页余量
    db.close()


def test_paged_page_less_than_one_clamped(tmp_path):
    """page<1 视作 1（offset 经 max(page-1,0) 钳制）。"""
    db = DatabaseService(_cfg(tmp_path))
    for i in range(12):
        _add(db, "A" if i % 2 == 0 else "B")
    rows0, _ = db.search_records_paged(page=0, page_size=5)
    rows1, _ = db.search_records_paged(page=1, page_size=5)
    assert rows0 == rows1
    db.close()


def test_paged_beyond_last_page_empty(tmp_path):
    """超末页：rows 空但 total 仍是匹配数。"""
    db = DatabaseService(_cfg(tmp_path))
    for _ in range(12):
        _add(db, "A")
    rows, total = db.search_records_paged(page=5, page_size=5)
    assert rows == []
    assert total == 12
    db.close()


def test_paged_column_order_preserved(tmp_path):
    """列序与 get_recent_records 一致：prediction 位于索引 4。"""
    db = DatabaseService(_cfg(tmp_path))
    _add(db, "A")
    rows, _ = db.search_records_paged(page=1, page_size=5)
    assert len(rows) == 1
    row = rows[0]
    # (id, timestamp, image_path, thumbnail_path, prediction, ...)
    assert row[4] == "A"  # 证明列未错位
    db.close()


def test_paged_quality_status_rejected_semantics(tmp_path):
    """quality_status='rejected' 查到非 ok 记录；'ok' 查不到它。

    直接验证 search_records_paged 与 search_records 的 quality_status 语义对齐：
    "rejected" → != 'ok'，"ok" → 精确匹配 'ok'。
    """
    db = DatabaseService(_cfg(tmp_path))
    _add(db, "A", q="rejected_blur")
    rej_rows, rej_total = db.search_records_paged(quality_status="rejected")
    assert rej_total >= 1
    assert len(rej_rows) >= 1
    ok_rows, ok_total = db.search_records_paged(quality_status="ok")
    assert ok_total == 0
    assert ok_rows == []
    db.close()
