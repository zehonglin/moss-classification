"""Task 6: GradeBanner 组件 + banner_state 纯函数。

横幅状态矩阵（kind ∈ normal/review/rejected/corrected/wait/debug）：
- normal   —— 正常出品级，品级色
- review   —— 低置信需复检，**品级色不变**（仅 kind 切换 + 标签提示）
- rejected —— 质量不合格拒采，grade="rejected"，灰底
- corrected—— 已人工纠错，grade/letter 用 corrected_label
- debug    —— 调试捕获（rid=None，未入库），grade="wait"
- wait     —— 仅组件初始占位态（不由 banner_state 产生）
"""
from app.ui.components.grade_banner import banner_state, GradeBanner


# ---------- banner_state 纯函数：六态 ----------

def test_normal_grade():
    s = banner_state({"prediction": "A", "confidence": 0.96, "corrected_label": None,
                      "quality_status": "ok", "id": 1}, threshold=0.6)
    assert s["grade"] == "A"
    assert s["letter"] == "A"
    assert s["kind"] == "normal"
    assert s["show_edit"] is True
    assert s["conf"] == "96%"


def test_low_confidence_review_keeps_grade_color():
    """低置信走 review 态，但 grade/letter 仍是品级色（正交原则）。"""
    s = banner_state({"prediction": "C", "confidence": 0.54, "corrected_label": None,
                      "quality_status": "ok", "id": 2}, threshold=0.6)
    assert s["kind"] == "review"
    assert s["grade"] == "C"
    assert s["letter"] == "C"


def test_rejected_grade_is_rejected():
    s = banner_state({"prediction": None, "confidence": None, "corrected_label": None,
                      "quality_status": "rejected_blur", "id": 3}, threshold=0.6)
    assert s["kind"] == "rejected"
    assert s["grade"] == "rejected"
    assert s["show_edit"] is False


def test_corrected_uses_corrected_label():
    s = banner_state({"prediction": "A", "confidence": 0.96, "corrected_label": "B",
                      "quality_status": "ok", "id": 4}, threshold=0.6)
    assert s["kind"] == "corrected"
    assert s["grade"] == "B"
    assert s["letter"] == "B"


def test_debug_when_record_not_persisted():
    """rid=None（调试捕获未入库）→ kind=debug, grade=wait。"""
    s = banner_state({"prediction": "B", "confidence": 0.88, "corrected_label": None,
                      "quality_status": "ok", "id": None}, threshold=0.6)
    assert s["kind"] == "debug"
    assert s["grade"] == "wait"
    assert s["show_edit"] is False


def test_rejected_overexposed_reason_in_conf():
    s = banner_state({"prediction": None, "confidence": None, "corrected_label": None,
                      "quality_status": "rejected_overexposed", "id": 5}, threshold=0.6)
    assert s["kind"] == "rejected"
    assert "过曝" in s["conf"]


def test_confidence_boundary_equal_threshold_is_normal():
    """confidence == threshold 不算 review（严格 < 才算低置信）。"""
    s = banner_state({"prediction": "A", "confidence": 0.6, "corrected_label": None,
                      "quality_status": "ok", "id": 6}, threshold=0.6)
    assert s["kind"] == "normal"


def test_missing_confidence_treated_as_normal():
    """confidence=None 不触发 review（无置信度信息，不抹黑）。"""
    s = banner_state({"prediction": "A", "confidence": None, "corrected_label": None,
                      "quality_status": "ok", "id": 7}, threshold=0.6)
    assert s["kind"] == "normal"


# ---------- GradeBanner 组件 ----------

def test_banner_widget_applies_grade_property():
    b = GradeBanner()
    b.set_state(banner_state({"prediction": "A", "confidence": 0.9, "corrected_label": None,
                              "quality_status": "ok", "id": 1}, 0.6))
    assert b.property("grade") == "A"
    assert b.objectName() == "GradeBanner"


def test_banner_widget_initial_state_is_wait():
    b = GradeBanner()
    assert b.property("grade") == "wait"


def test_banner_widget_rejected_property():
    b = GradeBanner()
    b.set_state(banner_state({"prediction": None, "confidence": None, "corrected_label": None,
                              "quality_status": "rejected_blur", "id": 3}, 0.6))
    assert b.property("grade") == "rejected"


def test_banner_widget_corrected_property():
    b = GradeBanner()
    b.set_state(banner_state({"prediction": "A", "confidence": 0.9, "corrected_label": "D",
                              "quality_status": "ok", "id": 4}, 0.6))
    assert b.property("grade") == "D"


def test_banner_widget_edit_button_visibility():
    """show_edit=True 时 ✎ 按钮可见，rejected/debug 时隐藏。

    用 isHidden() 而非 isVisible()：offscreen 模式下未 show() 的窗口子控件
    isVisible() 恒为 False，但 isHidden() 反映 setVisible() 的调用意图。
    """
    b = GradeBanner()
    b.set_state(banner_state({"prediction": "A", "confidence": 0.9, "corrected_label": None,
                              "quality_status": "ok", "id": 1}, 0.6))
    assert b._edit.isHidden() is False

    b.set_state(banner_state({"prediction": None, "confidence": None, "corrected_label": None,
                              "quality_status": "rejected_blur", "id": 3}, 0.6))
    assert b._edit.isHidden() is True


def test_correction_requested_signal_fires_on_edit_click():
    """点击 ✎ 纠错按钮 → correction_requested 信号发射。"""
    fired = []
    b = GradeBanner()
    b.correction_requested.connect(lambda: fired.append(True))
    b.set_state(banner_state({"prediction": "A", "confidence": 0.9, "corrected_label": None,
                              "quality_status": "ok", "id": 1}, 0.6))
    b._edit.click()
    assert fired == [True]


def test_set_reviewing_shows_history_tag():
    """set_reviewing(True) → _tag 文本变"正在查看历史记录"且不再隐藏（isHidden=False）。"""
    b = GradeBanner()
    b.set_state(banner_state({"prediction": "A", "confidence": 0.9, "corrected_label": None,
                              "quality_status": "ok", "id": 1}, 0.6))
    # normal 态 _tag 隐藏
    assert b._tag.isHidden() is True
    b.set_reviewing(True)
    assert b._tag.isHidden() is False
    assert "历史" in b._tag.text()
