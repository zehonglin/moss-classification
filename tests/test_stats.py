"""节拍/吞吐/丢帧监控测试。"""

import json
import time

from app.controllers.system_controller import SystemWorker
from app.drivers.mock_driver import MockCamera
from app.utils.config_manager import ConfigManager


def _make_worker(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "camera_settings": {
                    "driver_type": "mock",
                    "trigger": {"mode": "hardware"},
                }
            }
        ),
        encoding="utf-8",
    )
    return SystemWorker(MockCamera(), None, None, ConfigManager(str(cfg)))


def test_performance_timeout_config_default(tmp_path):
    cm = ConfigManager(str(tmp_path / "config.json"))
    assert cm.get("performance.processing_timeout_ms") == 3000


def test_worker_get_stats_computes_rate_and_avg(tmp_path):
    worker = _make_worker(tmp_path)
    worker.stats.update(
        {
            "processed": 100,
            "total_processing_ms": 5000.0,
            "timeouts": 3,
            "processing_timeout_count": 1,
            "start_time": time.time() - 3600,
        }
    )
    s = worker.get_stats()
    assert s["per_hour"] == 100
    assert s["avg_ms"] == 50.0
    assert s["timeouts"] == 3
    assert s["processing_timeout_count"] == 1


def test_grade_summary_updates_top_bar(tmp_path):
    """新版 MainWindow 由 grade_summary_updated 驱动 top_bar（取代旧 stats_label）。

    stats_updated（吞吐/超时统计）在新 UI 中不在顶部栏显示；产量由 grade_summary
    承载。此测试验证 grade_summary_updated → top_bar 的接线。
    """
    from app.ui.main_window import MainWindow

    from tests.fakes import FakeController

    cfg = tmp_path / "config.json"
    cfg.write_text('{"camera_settings": {"driver_type": "mock"}}', encoding="utf-8")
    ctrl = FakeController()
    win = MainWindow(ConfigManager(str(cfg)), ctrl)
    ctrl.grade_summary_updated.emit(
        {"A": 12, "B": 3, "C": 0, "D": 0, "corrected": 1, "rejected": 2}
    )
    assert "12" in win.top_bar._stats["A"].text()
    assert "3" in win.top_bar._stats["B"].text()
