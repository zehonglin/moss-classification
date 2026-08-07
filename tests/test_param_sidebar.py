"""Task 12: ParamSidebar 工程师参数栏。

QFrame#ParamSidebar 容器：触发模式 combo / 防抖 / 分辨率宽高 / **软件间隔
（仅 software_continuous 显示）** / 曝光 / 模型 combo / 置信阈值 / 质量检查入口 /
操作按钮组（连接/开始/停止/拍照）。

关键：软件间隔行仅 `software_continuous` 模式可见。offscreen 下 `isVisible`/
`isVisibleTo` 对未 show 的父不可靠，所以测纯函数 `_interval_visible_for(mode)`
而非真实可见性。
"""
from app.ui.components.param_sidebar import ParamSidebar


# ---------- _interval_visible_for：纯函数（TDD 重点） ----------

def test_interval_visible_for_preview_is_false():
    sb = ParamSidebar()
    assert sb._interval_visible_for("preview") is False


def test_interval_visible_for_hardware_is_false():
    sb = ParamSidebar()
    assert sb._interval_visible_for("hardware") is False


def test_interval_visible_for_software_single_is_false():
    sb = ParamSidebar()
    assert sb._interval_visible_for("software_single") is False


def test_interval_visible_for_software_continuous_is_true():
    sb = ParamSidebar()
    assert sb._interval_visible_for("software_continuous") is True


# ---------- 容器 / objectName 命中 qss ----------

def test_object_name_is_param_sidebar():
    sb = ParamSidebar()
    assert sb.objectName() == "ParamSidebar"


def test_minimum_width_240():
    sb = ParamSidebar()
    assert sb.minimumWidth() == 240


def test_group_titles_have_group_title_object_name():
    """相机/模型/质量检查 组标题 objectName=GroupTitle，命中 style.qss。"""
    sb = ParamSidebar()
    titles = sb.findChildren(type(sb._group_titles[0]))
    names = [t.objectName() for t in titles]
    assert names.count("GroupTitle") >= 3  # 相机 / 模型 / 质量检查


# ---------- 触发模式 combo ----------

def test_trigger_combo_has_four_options():
    """四选项：预览 / 传感器触发 / 软件单张 / 软件连续。"""
    sb = ParamSidebar()
    items = [sb._trigger.itemText(i) for i in range(sb._trigger.count())]
    assert items == ["预览", "传感器触发", "软件单张", "软件连续"]


def test_initial_trigger_is_preview():
    """构造后默认 preview（index 0）。"""
    sb = ParamSidebar()
    assert sb._trigger.currentIndex() == 0


# ---------- set_trigger_mode ----------

def test_set_trigger_mode_hardware():
    sb = ParamSidebar()
    sb.set_trigger_mode("hardware")
    assert sb._trigger.currentIndex() == 1


def test_set_trigger_mode_software_continuous():
    sb = ParamSidebar()
    sb.set_trigger_mode("software_continuous")
    assert sb._trigger.currentIndex() == 3


def test_set_trigger_mode_updates_interval_row_visibility():
    """set_trigger_mode → 软件间隔行可见性跟随 _interval_visible_for 的返回值。"""
    sb = ParamSidebar()
    # hardware → 隐藏
    sb.set_trigger_mode("hardware")
    assert sb._interval_row.isHidden() is True
    # software_continuous → 显示（offscreen 下用 isHidden 而非 isVisible）
    sb.set_trigger_mode("software_continuous")
    assert sb._interval_row.isHidden() is False


# ---------- trigger_changed 信号 ----------

def test_trigger_combo_change_emits_trigger_changed():
    sb = ParamSidebar()
    received = []
    sb.trigger_changed.connect(lambda m: received.append(m))
    sb._trigger.setCurrentIndex(3)  # 软件连续
    assert received == ["software_continuous"]


# ---------- 防抖 SpinBox → debouncer_changed ----------

def test_debouncer_spinbox_emits_debouncer_changed():
    sb = ParamSidebar()
    received = []
    sb.debouncer_changed.connect(lambda v: received.append(v))
    sb._debouncer.setValue(1500)
    assert received == [1500]


# ---------- 分辨率 ----------

def test_resolution_apply_button_emits_resolution_apply():
    sb = ParamSidebar()
    sb._w.setValue(1920)
    sb._h.setValue(1080)
    received = []
    sb.resolution_apply.connect(lambda w, h: received.append((w, h)))
    sb._apply_res.click()
    assert received == [(1920, 1080)]


# ---------- 软件间隔 SpinBox → interval_changed ----------

def test_interval_spinbox_emits_interval_changed():
    sb = ParamSidebar()
    received = []
    sb.interval_changed.connect(lambda v: received.append(v))
    sb._interval.setValue(2000)
    assert received == [2000]


# ---------- 曝光 → exposure_changed ----------

def test_exposure_spinbox_emits_exposure_changed():
    sb = ParamSidebar()
    received = []
    sb.exposure_changed.connect(lambda v: received.append(v))
    sb._exposure.setValue(50000)
    assert received == [50000]


# ---------- 模型 combo → model_changed ----------

def test_model_combo_emits_model_changed():
    sb = ParamSidebar()
    sb._model.addItem("mobilenet_v2")
    sb._model.addItem("resnet50")
    received = []
    sb.model_changed.connect(lambda m: received.append(m))
    sb._model.setCurrentIndex(1)
    assert received == ["resnet50"]


# ---------- 置信阈值 → threshold_changed ----------

def test_threshold_spinbox_emits_threshold_changed():
    sb = ParamSidebar()
    received = []
    sb.threshold_changed.connect(lambda v: received.append(v))
    sb._thr.setValue(0.85)
    assert received and abs(received[-1] - 0.85) < 1e-6


# ---------- 操作按钮 objectName 命中 qss ----------

def test_action_connect_button_object_name():
    sb = ParamSidebar()
    assert sb._b_conn.objectName() == "ActionConnect"


def test_action_start_button_object_name():
    sb = ParamSidebar()
    assert sb._b_start.objectName() == "ActionStart"


def test_action_stop_button_object_name():
    sb = ParamSidebar()
    assert sb._b_stop.objectName() == "ActionStop"


def test_action_capture_button_object_name():
    sb = ParamSidebar()
    assert sb._b_cap.objectName() == "ActionCapture"


# ---------- 操作按钮信号 ----------

def test_connect_button_emits_connect_clicked():
    sb = ParamSidebar()
    fired = []
    sb.connect_clicked.connect(lambda: fired.append(1))
    sb._b_conn.click()
    assert fired == [1]


def test_start_button_emits_start_clicked():
    sb = ParamSidebar()
    fired = []
    sb.start_clicked.connect(lambda: fired.append(1))
    sb._b_start.click()
    assert fired == [1]


def test_stop_button_emits_stop_clicked():
    sb = ParamSidebar()
    fired = []
    sb.stop_clicked.connect(lambda: fired.append(1))
    sb._b_stop.click()
    assert fired == [1]


def test_capture_button_emits_capture_clicked():
    sb = ParamSidebar()
    fired = []
    sb.capture_clicked.connect(lambda: fired.append(1))
    sb._b_cap.click()
    assert fired == [1]


# ---------- 11 个信号齐全 ----------

def test_all_eleven_signals_defined():
    """确认 11 个 class-level Signal 都存在。"""
    from PySide6.QtCore import Signal

    expected = [
        "trigger_changed",
        "debouncer_changed",
        "resolution_apply",
        "exposure_changed",
        "interval_changed",
        "model_changed",
        "threshold_changed",
        "connect_clicked",
        "start_clicked",
        "stop_clicked",
        "capture_clicked",
    ]
    for name in expected:
        assert hasattr(ParamSidebar, name), f"缺信号 {name}"
