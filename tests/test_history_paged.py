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
