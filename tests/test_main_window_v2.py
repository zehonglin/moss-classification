"""Task 14: MainWindow v2 双模式集成测试。

覆盖关键接线：
    - grade_summary_updated → top_bar 品级计数
    - result_updated → banner 状态（property grade）
    - 气泡纠错流程 → controller.correct_prediction
    - 选中历史 → camera reviewing + banner 切状态
    - 模式切换（无密码直接切）
    - 操作员底栏按钮存在
"""

import json

from PySide6.QtWidgets import QPushButton

from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


def _win(tmp_path, connected=False):
    """构造一个用 FakeController 的 MainWindow（offscreen）。"""
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps(
            {
                "camera_settings": {"driver_type": "mock"},
                "model_settings": {"confidence_threshold": 0.6},
            }
        ),
        encoding="utf-8",
    )
    ctrl = FakeController(connected)
    return MainWindow(ConfigManager(str(p)), ctrl), ctrl


def test_grade_summary_updates_top_bar(tmp_path):
    """controller.grade_summary_updated → TopStatBar 显示最新计数。"""
    win, ctrl = _win(tmp_path)
    ctrl.grade_summary_updated.emit(
        {"A": 7, "B": 0, "C": 0, "D": 0, "corrected": 0, "rejected": 0}
    )
    assert "7" in win.top_bar._stats["A"].text()


def test_result_updates_banner(tmp_path):
    """controller.result_updated → banner property grade == prediction。"""
    win, ctrl = _win(tmp_path)
    ctrl.result_updated.emit(
        {
            "id": 1,
            "timestamp": "2026-01-01T00:00:00",
            "image_path": None,
            "thumbnail_path": None,
            "prediction": "A",
            "confidence": 0.9,
            "corrected_label": None,
            "quality_status": "ok",
        }
    )
    assert win.banner.property("grade") == "A"


def test_correction_popup_flow(tmp_path):
    """横幅 ✎ → CorrectionPopup → 点 B → controller.correct_prediction(id, "B")。"""
    win, ctrl = _win(tmp_path)
    ctrl.result_updated.emit(
        {
            "id": 1,
            "timestamp": "2026-01-01T00:00:00",
            "image_path": None,
            "thumbnail_path": None,
            "prediction": "A",
            "confidence": 0.9,
            "corrected_label": None,
            "quality_status": "ok",
        }
    )
    win._on_correction_requested()
    assert win._popup is not None
    win._popup._click("B")
    assert ctrl.corrections == [(1, "B")]


def test_history_selected_switches_to_history_state(tmp_path):
    """选中历史项 → camera 进 reviewing + banner 切到该品级。"""
    win, _ = _win(tmp_path)
    rec = {
        "id": 5,
        "timestamp": "2026-01-01T00:00:00",
        "image_path": None,
        "thumbnail_path": None,
        "prediction": "C",
        "confidence": 0.8,
        "corrected_label": None,
        "quality_status": "ok",
    }
    win._on_history_selected(rec)
    assert win.camera._reviewing is True
    assert win.banner.property("grade") == "C"


def test_switch_mode_to_engineer_without_password(tmp_path):
    """无密码配置 → 直接切工程师模式（含布局重排不崩）。"""
    win, _ = _win(tmp_path)
    win._switch_mode("engineer")
    assert win._mode == "engineer"
    # 切回操作员也不崩（验证共享组件未被删除）
    win._switch_mode("operator")
    assert win._mode == "operator"
    assert win.camera is not None
    assert win.banner is not None


def test_operator_mode_has_bottom_buttons(tmp_path):
    """操作员模式 → 底栏含连接/开始/停止/拍照 4 个 _do_* 方法可调用。"""
    win, _ = _win(tmp_path)
    # 底栏按钮通过 _do_* 方法接线；验证 4 个方法都存在且可调用
    for method in ("_do_connect", "_do_start", "_do_stop", "_do_capture"):
        assert callable(getattr(win, method, None))
    # 验证底栏容器存在（body layout 最后一个 item 是底栏）
    last_item = win._body_l.itemAt(win._body_l.count() - 1)
    assert last_item is not None
    bot_widget = last_item.widget()
    assert bot_widget is not None
    # 底栏内应有 4 个 QPushButton
    btns = [b for b in bot_widget.findChildren(QPushButton)]
    assert len(btns) == 4


# ---- final review fix 覆盖 ----


def test_page_change_preserves_filter(tmp_path):
    """C1: 筛选后翻页仍带 filter 参数（不返回未过滤全量）。"""
    win, ctrl = _win(tmp_path)
    win._on_filter({"prediction": "A", "quality_status": None})
    assert ctrl.last_paged["prediction"] == "A"
    win._on_page_change(2)  # 翻页
    assert ctrl.last_paged["prediction"] == "A"  # 仍带 filter
    assert ctrl.last_paged["page"] == 2


def test_model_loaded_failure_toasts(tmp_path):
    """C2: 模型加载失败 → toast danger。"""
    win, ctrl = _win(tmp_path)
    ctrl.model_loaded.emit(False, "bad.onnx")
    assert win.toasts.count() >= 1  # 失败 toast 已显示


def test_stats_updates_disk_display(tmp_path):
    """I1: stats_updated 含 free_gb → top_bar 磁盘显示。"""
    win, ctrl = _win(tmp_path)
    ctrl.stats_updated.emit(
        {
            "free_gb": 380,
            "avg_ms": 32,
            "processing_timeout_count": 0,
            "quality_rejects": 0,
        }
    )
    assert "380" in win.top_bar._disk.text()


def test_status_running_while_reviewing_shows_history(tmp_path):
    """I3: 选中历史（reviewing）时 status RUNNING → top_bar 显示"历史图像"。"""
    from app.controllers.system_controller import STATUS_RUNNING

    win, ctrl = _win(tmp_path)
    rec = {
        "id": 5,
        "timestamp": "2026-01-01T00:00:00",
        "image_path": None,
        "thumbnail_path": None,
        "prediction": "C",
        "confidence": 0.8,
        "corrected_label": None,
        "quality_status": "ok",
    }
    win._on_history_selected(rec)  # 进 reviewing
    ctrl.status_updated.emit(STATUS_RUNNING)
    assert "历史图像" in win.top_bar._run.text()
