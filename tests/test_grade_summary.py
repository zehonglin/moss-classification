"""Task 2: count_by_final_grade 聚合统计测试。

辅助函数 _cfg / _add / _db 会被 Task 3 的 grade_summary 服务测试复用，
命名保持稳定。
"""

import json

from app.services.database_service import DatabaseService
from app.utils.config_manager import ConfigManager


def _cfg(tmp_path):
    """用 tmp_path 构造一份指向临时 moss.db 的 ConfigManager。"""
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps({"data_paths": {"db_filename": str(tmp_path / "moss.db")}}),
        encoding="utf-8",
    )
    return ConfigManager(str(p))


def _db(tmp_path):
    """基于 tmp_path 创建一个独立的 DatabaseService。"""
    return DatabaseService(_cfg(tmp_path))


def _add(db, pred, conf=0.9, corr=None, q="ok"):
    """插入一条记录；若给出 corr 则在插入后纠正它。

    add_record 现有签名不接受 corrected_label，故先插入再用 update_correction
    更正，以模拟真实 controller 流程。
    """
    rid = db.add_record(
        "2026-01-01T00:00:00",
        "x.png",
        pred,
        conf,
        thumbnail_path="t.png",
        quality_status=q,
    )
    if corr:
        db.update_correction(rid, corr)
    return rid


def test_count_by_final_grade(tmp_path):
    db = _db(tmp_path)
    _add(db, "A")                       # A
    _add(db, "A", corr="B")             # 原 A 纠正为 B → B 计，纠错计，A 不计
    _add(db, "C", q="rejected_blur")    # 拒采，不计品级
    s = db.count_by_final_grade()
    assert s["A"] == 1
    assert s["B"] == 1
    assert s["C"] == 0
    assert s["D"] == 0
    assert s["corrected"] == 1
    assert s["rejected"] == 1
    db.close()
