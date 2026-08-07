"""Task 5: SystemController.export_with_images 测试。

验证：CSV 写入 + 按 group_by（grade/status）分组复制原图；返回记录数；
图片缺失/复制失败不崩。
"""

import json
import os

from app.controllers.system_controller import SystemController
from app.utils.config_manager import ConfigManager


def _ctrl(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps(
            {
                "camera_settings": {"driver_type": "mock"},
                "data_paths": {"db_filename": str(tmp_path / "moss.db")},
            }
        ),
        encoding="utf-8",
    )
    return SystemController(ConfigManager(str(p)))


def test_export_with_images_copies_grouped_by_grade(tmp_path):
    """brief 主用例：grade 分组，corrected_label=None → 组=原预测。"""
    ctrl = _ctrl(tmp_path)
    img = tmp_path / "src.png"
    img.write_bytes(b"x")
    # 列序与 export_records_csv 表头一致：
    # id, timestamp, image_path, thumbnail_path, prediction, confidence,
    # corrected_label, quality_status [, rejected_reason]
    rec = (1, "2026-01-01T00:00:00", str(img), None, "A", 0.96, None, "ok", None)
    out_csv = tmp_path / "out.csv"
    img_root = tmp_path / "imgs"
    n = ctrl.export_with_images(str(out_csv), str(img_root), [rec], group_by="grade")
    assert n == 1
    dest = img_root / "A" / "1_A.png"
    assert dest.exists()
    assert dest.read_bytes() == b"x"
    # CSV 也应写入
    assert out_csv.exists()
    ctrl.shutdown()


def test_export_with_images_grade_uses_corrected_label(tmp_path):
    """grade 分组：corrected_label 非空 → 组=corrected_label（最终品级）。"""
    ctrl = _ctrl(tmp_path)
    img = tmp_path / "src.png"
    img.write_bytes(b"y")
    rec = (2, "2026-01-01T00:00:00", str(img), None, "A", 0.96, "B", "ok", None)
    img_root = tmp_path / "imgs"
    n = ctrl.export_with_images(
        str(tmp_path / "c.csv"), str(img_root), [rec], group_by="grade"
    )
    assert n == 1
    # 组按最终品级 B；文件名仍用原预测 A
    dest = img_root / "B" / "2_A.png"
    assert dest.exists()
    ctrl.shutdown()


def test_export_with_images_group_by_status(tmp_path):
    """status 分组：quality != 'ok' → 组=quality_status；ok → 'ok'。"""
    ctrl = _ctrl(tmp_path)
    img1 = tmp_path / "src1.png"
    img1.write_bytes(b"r")
    img2 = tmp_path / "src2.png"
    img2.write_bytes(b"o")
    recs = [
        (3, "2026-01-01T00:00:00", str(img1), None, "A", 0.9, None,
         "rejected_blur", "模糊"),
        (4, "2026-01-01T00:00:01", str(img2), None, "B", 0.8, None, "ok", None),
    ]
    img_root = tmp_path / "imgs"
    n = ctrl.export_with_images(
        str(tmp_path / "c.csv"), str(img_root), recs, group_by="status"
    )
    assert n == 2
    assert (img_root / "rejected_blur" / "3_A.png").exists()
    assert (img_root / "ok" / "4_B.png").exists()
    ctrl.shutdown()


def test_export_with_images_missing_image_skipped(tmp_path):
    """图片不存在：跳过不崩，CSV 仍写，返回数仍为 len(rows)。"""
    ctrl = _ctrl(tmp_path)
    rec = (5, "2026-01-01T00:00:00", "/nonexistent/path/x.png", None,
           "A", 0.9, None, "ok", None)
    img_root = tmp_path / "imgs"
    n = ctrl.export_with_images(
        str(tmp_path / "c.csv"), str(img_root), [rec], group_by="grade"
    )
    assert n == 1
    # 不应创建任何子目录（图片跳过）
    assert not (img_root / "A").exists()
    ctrl.shutdown()


def test_export_with_images_empty_image_path_skipped(tmp_path):
    """image_path 为空字符串：跳过不崩。"""
    ctrl = _ctrl(tmp_path)
    rec = (6, "2026-01-01T00:00:00", "", None, "A", 0.9, None, "ok", None)
    img_root = tmp_path / "imgs"
    n = ctrl.export_with_images(
        str(tmp_path / "c.csv"), str(img_root), [rec], group_by="grade"
    )
    assert n == 1
    ctrl.shutdown()


def test_export_with_images_safe_group_name(tmp_path):
    """组名含非法路径字符：清理后兜底（不崩）。"""
    ctrl = _ctrl(tmp_path)
    img = tmp_path / "src.png"
    img.write_bytes(b"x")
    # 操作员纠错标签含路径分隔符（兜底测试）
    rec = (7, "2026-01-01T00:00:00", str(img), None, "A", 0.9,
           "B/C", "ok", None)
    img_root = tmp_path / "imgs"
    n = ctrl.export_with_images(
        str(tmp_path / "c.csv"), str(img_root), [rec], group_by="grade"
    )
    assert n == 1
    # 非法 / 被替换成 _，组名 = B_C
    dest = img_root / "B_C" / "7_A.png"
    assert dest.exists()
    ctrl.shutdown()
