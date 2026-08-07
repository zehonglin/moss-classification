"""Task 4: SystemController grade_summary 信号 + get_grade_summary 测试。

无 pytest-qt，故用直接调 _emit_grade_summary + 槽函数收集验证。
"""

import json

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


def test_get_grade_summary_returns_dict(tmp_path):
    ctrl = _ctrl(tmp_path)
    s = ctrl.get_grade_summary()
    assert set(s) >= {"A", "B", "C", "D", "corrected", "rejected"}
    ctrl.shutdown()


def test_grade_summary_updated_signal_emits(tmp_path):
    """直接调 _emit_grade_summary，验证信号连接 + 槽收到含 'A' 的 dict。"""
    ctrl = _ctrl(tmp_path)
    received = []
    ctrl.grade_summary_updated.connect(lambda d: received.append(d))
    ctrl._emit_grade_summary()
    assert received, "未收到 grade_summary_updated 信号"
    assert "A" in received[0]
    ctrl.shutdown()
