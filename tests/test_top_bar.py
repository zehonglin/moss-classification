"""Task 9: TopStatBar 顶部统计栏。

操作员/工程师双模式共用同一组件，订阅 controller.grade_summary_updated(dict)
显示 A/B/C/D/纠错/不合格累计 + 磁盘 + 运行状态 + 模式切换按钮。
"""
from app.ui.components.top_bar import TopStatBar


# ---------- set_grade_summary：A/B/C/D/纠错/不合格 数字更新 ----------

def test_grade_summary_updates_grade_labels():
    bar = TopStatBar()
    bar.set_grade_summary({"A": 10, "B": 5, "C": 2, "D": 1, "corrected": 3, "rejected": 4})
    assert "10" in bar._stats["A"].text()
    assert "5" in bar._stats["B"].text()
    assert "2" in bar._stats["C"].text()
    assert "1" in bar._stats["D"].text()


def test_grade_summary_updates_corrected_label():
    bar = TopStatBar()
    bar.set_grade_summary({"A": 10, "B": 5, "C": 2, "D": 1, "corrected": 3, "rejected": 4})
    assert "3" in bar._stats["corrected"].text()
    assert "纠错" in bar._stats["corrected"].text()


def test_grade_summary_updates_rejected_label():
    bar = TopStatBar()
    bar.set_grade_summary({"A": 10, "B": 5, "C": 2, "D": 1, "corrected": 3, "rejected": 4})
    assert "4" in bar._stats["rejected"].text()
    assert "不合格" in bar._stats["rejected"].text()


def test_grade_summary_missing_keys_default_zero():
    """缺 key 不报错，按 0 渲染（与 controller 默认行为对齐）。"""
    bar = TopStatBar()
    bar.set_grade_summary({})
    for g in ("A", "B", "C", "D", "corrected", "rejected"):
        assert "0" in bar._stats[g].text()


def test_grade_summary_has_grade_color_dot():
    """A/B/C/D 标签内嵌品级色点（#16a34a/#65a30d/#d97706/#dc2626）。"""
    bar = TopStatBar()
    bar.set_grade_summary({"A": 1, "B": 1, "C": 1, "D": 1, "corrected": 0, "rejected": 0})
    assert "#16a34a" in bar._stats["A"].text()
    assert "#65a30d" in bar._stats["B"].text()
    assert "#d97706" in bar._stats["C"].text()
    assert "#dc2626" in bar._stats["D"].text()


# ---------- set_run_state：三态文案 + 颜色 ----------

def test_run_state_live_text():
    bar = TopStatBar()
    bar.set_run_state("live")
    assert "实时图像" in bar._run.text()


def test_run_state_history_text():
    bar = TopStatBar()
    bar.set_run_state("history")
    assert "历史图像" in bar._run.text()


def test_run_state_idle_text():
    bar = TopStatBar()
    bar.set_run_state("idle")
    assert "已停止" in bar._run.text()


def test_run_state_default_idle():
    """初始态（未调 set_run_state）应为 idle 文案。"""
    bar = TopStatBar()
    assert "已停止" in bar._run.text()


def test_run_state_live_is_green():
    """live/history 用绿色字（#16a34a）。"""
    bar = TopStatBar()
    bar.set_run_state("live")
    assert "#16a34a" in bar._run.styleSheet()


def test_run_state_history_is_green():
    bar = TopStatBar()
    bar.set_run_state("history")
    assert "#16a34a" in bar._run.styleSheet()


def test_run_state_idle_is_gray():
    """idle 用灰色字。"""
    bar = TopStatBar()
    bar.set_run_state("live")
    bar.set_run_state("idle")
    assert "#16a34a" not in bar._run.styleSheet()
    assert "#94a3b8" in bar._run.styleSheet()


# ---------- set_mode + mode_change_requested 信号 ----------

def test_set_mode_engineer():
    bar = TopStatBar()
    bar.set_mode("engineer")
    assert "工程师" in bar._mode.text()


def test_set_mode_operator():
    bar = TopStatBar()
    bar.set_mode("engineer")
    bar.set_mode("operator")
    assert "操作员" in bar._mode.text()


def test_initial_mode_is_operator():
    bar = TopStatBar()
    assert "操作员" in bar._mode.text()


def test_mode_change_requested_from_operator_to_engineer():
    """当前操作员模式 → 点击 → 请求切换到 engineer。"""
    bar = TopStatBar()
    received = []
    bar.mode_change_requested.connect(lambda m: received.append(m))
    bar._mode.click()
    assert received == ["engineer"]


def test_mode_change_requested_from_engineer_to_operator():
    """当前工程师模式 → 点击 → 请求切换到 operator。"""
    bar = TopStatBar()
    bar.set_mode("engineer")
    received = []
    bar.mode_change_requested.connect(lambda m: received.append(m))
    bar._mode.click()
    assert received == ["operator"]


# ---------- set_disk ----------

def test_set_disk_updates_text():
    bar = TopStatBar()
    bar.set_disk("12.3 GB")
    assert "12.3 GB" in bar._disk.text()


# ---------- objectName / 容器结构 ----------

def test_object_name_is_topbar():
    bar = TopStatBar()
    assert bar.objectName() == "TopBar"


def test_run_label_has_runstate_object_name():
    """运行状态 label objectName=RunState，命中 style.qss。"""
    bar = TopStatBar()
    assert bar._run.objectName() == "RunState"


def test_stat_labels_have_statitem_object_name():
    """A/B/C/D/纠错/不合格 label objectName=StatItem，命中 style.qss。"""
    bar = TopStatBar()
    for key in ("A", "B", "C", "D", "corrected", "rejected"):
        assert bar._stats[key].objectName() == "StatItem", f"{key} 缺 StatItem objectName"
