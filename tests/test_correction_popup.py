"""Task 7: CorrectionPopup 气泡纠错组件。

点横幅 ✎ 弹出的气泡：4 个纯字母品级色按钮 A/B/C/D（无描述文字），
当前品级按钮标"当前"角标 + 白边框 outline；点选即 emit grade_selected 并关闭。

offscreen Qt 坑：测子控件可见性用 isHidden() 而非 isVisible()（Task 6 经验）；
popup 关闭不断言 isVisible（offscreen 不可靠），改为 mock close 后断言被调用 + 信号已收到。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from app.ui.components.correction_popup import CorrectionPopup, GRADES


# ---------- 组件基础结构 ----------

def test_grades_constant_has_four_letter_grades():
    """GRADES 常量四元组（字母, 色值），顺序 A→D，色值符合规格。"""
    assert [g for g, _ in GRADES] == ["A", "B", "C", "D"]
    expected_colors = {"A": "#16a34a", "B": "#65a30d", "C": "#d97706", "D": "#dc2626"}
    for g, color in GRADES:
        assert color.lower() == expected_colors[g].lower()


def test_popup_window_flags_popup_frameless():
    """必须 Qt.Popup | Qt.FramelessWindowHint：无标题栏 + 点外部自动关。"""
    pop = CorrectionPopup()
    flags = pop.windowFlags()
    assert bool(flags & Qt.Popup)
    assert bool(flags & Qt.FramelessWindowHint)


def test_popup_object_name():
    pop = CorrectionPopup()
    assert pop.objectName() == "CorrectionPopup"


def test_grade_selected_signal_exists():
    """grade_selected = Signal(str) 必须存在且可 connect。"""
    pop = CorrectionPopup()
    assert hasattr(pop, "grade_selected")
    seen = []
    pop.grade_selected.connect(lambda g: seen.append(g))
    pop.grade_selected.emit("A")
    assert seen == ["A"]


# ---------- 四个按钮：纯字母无描述 ----------

def test_four_buttons_show_only_letters():
    """4 个按钮 text 仅字母 A/B/C/D，无"铺满/覆盖高"等描述文字。"""
    pop = CorrectionPopup()
    assert set(pop._btns.keys()) == {"A", "B", "C", "D"}
    for g, btn in pop._btns.items():
        assert btn.text() == g  # 纯字母，无附加文字


def test_button_colors_match_grades_constant():
    """按钮背景色用品级色（A#16a34a/B#65a30d/C#d97706/D#dc2626）。"""
    pop = CorrectionPopup()
    for g, color in GRADES:
        style = pop._btns[g].styleSheet().lower()
        assert color.lower() in style, f"按钮 {g} 未用色值 {color}"


def test_button_text_white_large_bold():
    """白字 + 大号 + 粗体（可读性）。"""
    pop = CorrectionPopup()
    for g, btn in pop._btns.items():
        style = btn.styleSheet().lower()
        assert "#fff" in style or "white" in style
        assert "font-weight" in style
        assert "font-size" in style


# ---------- popup_for：当前品级标记 ----------

def test_popup_for_records_current_grade():
    """popup_for 设置 _current = record['prediction']。"""
    pop = CorrectionPopup()
    pop.popup_for({"prediction": "A", "id": 1}, QLabel())
    assert pop._current == "A"


def test_popup_for_marks_current_button_with_outline():
    """当前品级按钮样式含 outline（白边框视觉标记）。"""
    pop = CorrectionPopup()
    pop.popup_for({"prediction": "A", "id": 1}, QLabel())
    cur_style = pop._btns["A"].styleSheet().lower()
    assert "outline" in cur_style


def test_popup_for_does_not_mark_other_buttons():
    """非当前品级按钮不加 outline 标记。"""
    pop = CorrectionPopup()
    pop.popup_for({"prediction": "A", "id": 1}, QLabel())
    for g in ("B", "C", "D"):
        assert "outline" not in pop._btns[g].styleSheet().lower()


def test_popup_for_shows_current_badge_text():
    """当前品级按钮有"当前"角标文本（通过 _badges[g].text() 暴露）。"""
    pop = CorrectionPopup()
    pop.popup_for({"prediction": "A", "id": 1}, QLabel())
    assert pop._badges["A"].text() == "当前"
    for g in ("B", "C", "D"):
        assert pop._badges[g].text() == ""


def test_popup_for_updates_badge_when_grade_changes():
    """连续 popup_for 切换当前品级，badge 与 outline 跟随切换。"""
    pop = CorrectionPopup()
    pop.popup_for({"prediction": "A", "id": 1}, QLabel())
    assert pop._badges["A"].text() == "当前"
    assert "outline" in pop._btns["A"].styleSheet().lower()

    pop.popup_for({"prediction": "D", "id": 2}, QLabel())
    assert pop._badges["D"].text() == "当前"
    assert pop._badges["A"].text() == ""
    assert "outline" in pop._btns["D"].styleSheet().lower()
    assert "outline" not in pop._btns["A"].styleSheet().lower()


# ---------- _click：emit + close（核心行为）----------

def test_click_emits_grade_selected():
    """_click(grade) 必须发射 grade_selected 信号。"""
    pop = CorrectionPopup()
    seen = []
    pop.grade_selected.connect(lambda g: seen.append(g))
    pop._click("B")
    assert seen == ["B"]


def test_click_emits_correct_grade_for_each_button():
    """每个按钮 _click 都发对应字母。"""
    pop = CorrectionPopup()
    seen = []
    pop.grade_selected.connect(lambda g: seen.append(g))
    for g in ["A", "B", "C", "D"]:
        pop._click(g)
    assert seen == ["A", "B", "C", "D"]


def test_selecting_grade_b_emits_and_closes():
    """完整流程：popup_for（当前 C）→ _click("B") → emit ["B"] 且关闭。

    offscreen 模式下 isVisible 不可靠，mock close 后断言被调用 + 信号收到。
    """
    pop = CorrectionPopup()
    seen = []
    pop.grade_selected.connect(lambda g: seen.append(g))
    pop.popup_for({"prediction": "C", "id": 1}, QLabel())
    assert pop._current == "C"

    closed = []
    pop.close = lambda: closed.append(True)
    pop._click("B")
    assert seen == ["B"]
    assert closed == [True]


def test_click_on_each_grade_closes_popup():
    """任意按钮 _click 后都触发 close。"""
    pop = CorrectionPopup()
    closed = []
    pop.close = lambda: closed.append(True)
    for g in ["A", "B", "C", "D"]:
        pop._click(g)
    assert len(closed) == 4


def test_button_click_triggers_internal_click():
    """真实点击按钮也走 _click 路径（信号 + close 都触发）。"""
    pop = CorrectionPopup()
    seen = []
    pop.grade_selected.connect(lambda g: seen.append(g))
    closed = []
    pop.close = lambda: closed.append(True)
    pop._btns["B"].click()
    assert seen == ["B"]
    assert closed == [True]


# ---------- popup_for 锚定位置 ----------

def test_popup_for_moves_below_anchor():
    """popup_for 把 popup move 到 anchor 全局 bottomLeft 附近（下方）。"""
    anchor = QLabel()
    pop = CorrectionPopup()
    pop.popup_for({"prediction": "A", "id": 1}, anchor)
    gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
    # x 偏左一些（避免 popup 右溢出），y 在 anchor 下方
    assert pop.pos().x() <= gp.x()
    assert pop.pos().y() >= gp.y()


def test_popup_for_shows_popup():
    """popup_for 后 popup 不处于 hidden 状态（isHidden=False）。"""
    pop = CorrectionPopup()
    pop.popup_for({"prediction": "A", "id": 1}, QLabel())
    assert pop.isHidden() is False


def test_popup_for_handles_missing_prediction():
    """prediction 缺失时 _current 为 None，所有按钮无 outline/badge。"""
    pop = CorrectionPopup()
    pop.popup_for({"id": 1}, QLabel())
    assert pop._current is None
    for g in ("A", "B", "C", "D"):
        assert "outline" not in pop._btns[g].styleSheet().lower()
        assert pop._badges[g].text() == ""
