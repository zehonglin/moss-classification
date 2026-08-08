"""Task 9: TopStatBar 顶部统计栏（v3）。

操作员/工程师双模式共用同一组件，订阅 controller.grade_summary_updated(dict)。

v3 变更：
- 统计折叠：A/B/C/D/纠错/质量异常 明细收进 chip 弹出层（_stats 标签组保留在
  StatsPopup 内）；chip 显示"今日 N 盘 · 通过率 x%"。通过率口径 (A+B+C)/(A+B+C+D)，
  今日盘数 = A+B+C+D+质量异常。
- 模式切换改分段控件（_mode_op / _mode_eng，active property 高亮）。
- 运行状态颜色由 QSS dynamic property（state="live|idle"）驱动，不再内联样式。
- 品级色点用 700 深度 ramp（#15803d/#a16207/#c2410c/#b91c1c）。
"""
from app.ui.components.top_bar import TopStatBar


# ---------- set_grade_summary：明细层数字更新 ----------

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
    """v3：质量异常（图像正常入库，不用"拒采"措辞）。"""
    bar = TopStatBar()
    bar.set_grade_summary({"A": 10, "B": 5, "C": 2, "D": 1, "corrected": 3, "rejected": 4})
    assert "4" in bar._stats["rejected"].text()
    assert "质量异常" in bar._stats["rejected"].text()


def test_grade_summary_missing_keys_default_zero():
    """缺 key 不报错，按 0 渲染（与 controller 默认行为对齐）。"""
    bar = TopStatBar()
    bar.set_grade_summary({})
    for g in ("A", "B", "C", "D", "corrected", "rejected"):
        assert "0" in bar._stats[g].text()


def test_grade_summary_has_grade_color_dot():
    """A/B/C/D 标签内嵌品级色点（v3 ramp：#15803d/#a16207/#c2410c/#b91c1c）。"""
    bar = TopStatBar()
    bar.set_grade_summary({"A": 1, "B": 1, "C": 1, "D": 1, "corrected": 0, "rejected": 0})
    assert "#15803d" in bar._stats["A"].text()
    assert "#a16207" in bar._stats["B"].text()
    assert "#c2410c" in bar._stats["C"].text()
    assert "#b91c1c" in bar._stats["D"].text()


# ---------- 统计 chip：今日 N 盘 · 通过率 ----------

def test_chip_shows_total_trays_and_pass_rate():
    """chip 文案：今日 N 盘（含质量异常）· 通过率 (A+B+C)/(A+B+C+D)。"""
    bar = TopStatBar()
    # 10+5+2+1=18 有品级；通过率 (10+5+2)/18 = 94.4%；今日盘数 18+4=22
    bar.set_grade_summary({"A": 10, "B": 5, "C": 2, "D": 1, "corrected": 3, "rejected": 4})
    txt = bar._chip.text()
    assert "今日 22 盘" in txt
    assert "94.4%" in txt


def test_chip_pass_rate_dash_when_no_grades():
    """无品级记录时通过率显示 "—"（分母为 0 不算 0%）。"""
    bar = TopStatBar()
    bar.set_grade_summary({"rejected": 3})
    assert "—" in bar._chip.text()
    assert "今日 3 盘" in bar._chip.text()


def test_chip_toggles_stats_popup():
    """点 chip → 明细层 show/hide 切换。"""
    bar = TopStatBar()
    assert bar._popup.isHidden() is True
    bar._toggle_stats_popup()
    assert bar._popup.isHidden() is False
    bar._popup.hide()


# ---------- set_run_state：三态文案 + QSS property ----------

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


def test_run_state_live_property():
    """live/history → state="live"（QSS 命中绿色）。"""
    bar = TopStatBar()
    bar.set_run_state("live")
    assert bar._run.property("state") == "live"


def test_run_state_history_property():
    bar = TopStatBar()
    bar.set_run_state("history")
    assert bar._run.property("state") == "live"


def test_run_state_idle_property():
    """idle → state="idle"（QSS 命中灰色）。"""
    bar = TopStatBar()
    bar.set_run_state("live")
    bar.set_run_state("idle")
    assert bar._run.property("state") == "idle"


# ---------- 模式分段控件 + mode_change_requested 信号 ----------

def test_set_mode_engineer():
    bar = TopStatBar()
    bar.set_mode("engineer")
    assert bar._mode == "engineer"
    assert bar._mode_eng.property("active") == "1"
    assert bar._mode_op.property("active") == "0"


def test_set_mode_operator():
    bar = TopStatBar()
    bar.set_mode("engineer")
    bar.set_mode("operator")
    assert bar._mode == "operator"
    assert bar._mode_op.property("active") == "1"


def test_initial_mode_is_operator():
    bar = TopStatBar()
    assert bar._mode == "operator"
    assert bar._mode_op.property("active") == "1"


def test_mode_change_requested_from_operator_to_engineer():
    """当前操作员模式 → 点工程师段 → 请求切换到 engineer。"""
    bar = TopStatBar()
    received = []
    bar.mode_change_requested.connect(lambda m: received.append(m))
    bar._mode_eng.click()
    assert received == ["engineer"]


def test_mode_change_requested_from_engineer_to_operator():
    """当前工程师模式 → 点操作员段 → 请求切换到 operator。"""
    bar = TopStatBar()
    bar.set_mode("engineer")
    received = []
    bar.mode_change_requested.connect(lambda m: received.append(m))
    bar._mode_op.click()
    assert received == ["operator"]


def test_click_current_mode_segment_no_signal():
    """点当前模式段不重复请求（防抖动）。"""
    bar = TopStatBar()
    received = []
    bar.mode_change_requested.connect(lambda m: received.append(m))
    bar._mode_op.click()  # 已是操作员
    assert received == []


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
    """A/B/C/D/纠错/质量异常 label objectName=StatItem，命中 style.qss。"""
    bar = TopStatBar()
    for key in ("A", "B", "C", "D", "corrected", "rejected"):
        assert bar._stats[key].objectName() == "StatItem", f"{key} 缺 StatItem objectName"
