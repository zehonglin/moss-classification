"""ToastStack 通知组件测试。

conftest._qapp（session autouse，offscreen）已就绪，提供 QApplication。
"""
from PySide6.QtWidgets import QApplication

from app.ui.components.toast import ToastStack, severity_for

# 模块级兜底：conftest 的 _qapp fixture 在测试开始前已建实例；
# 这里再取一次 instance 以防 import 阶段需要。
app = QApplication.instance() or QApplication([])


def test_severity_for_keywords():
    """含 danger 关键词 → danger；否则 → warn。"""
    assert severity_for("磁盘空间严重不足") == "danger"
    assert severity_for("磁盘空间警告") == "warn"
    assert severity_for("连续 5 帧质量不合格") == "warn"
    assert severity_for("模型未加载，采集已停止") == "danger"


def test_show_adds_toast_and_times_out():
    """show 后 count 反映新增；timeout_ms=0 不自动关。"""
    ts = ToastStack()
    # timeout_ms=0 → 不启动 QTimer，仅添加
    ts.show("测试警告", severity="warn", timeout_ms=0)
    assert ts.count() == 1
    # 再加一条
    ts.show("测试错误", severity="danger", timeout_ms=0)
    assert ts.count() == 2


def test_remove_decrements_count():
    """_remove 后 count 减少（× 关闭路径）。"""
    ts = ToastStack()
    t = ts.show("可关闭", severity="warn", timeout_ms=0)
    assert ts.count() == 1
    ts._remove(t)
    assert ts.count() == 0


def test_remove_idempotent_race_click_then_timer():
    """× 点击 与 QTimer 到期 竞态：二次调用 _remove 不抛 RuntimeError。

    场景：用户在 timer 到期前点 × → 第一条路径 deleteLater（排队待删）；
    随后 timer lambda 触发 _remove → 若无守卫，removeWidget 会在已删除的
    C++ 对象包装上调用，抛 RuntimeError。本测试直接连调两次 _remove 模拟
    竞态，断言第二次静默返回、count 仍为 0、不抛异常。
    """
    ts = ToastStack()
    toast = ts.show("竞态", severity="warn", timeout_ms=60000)
    assert ts.count() == 1

    # 第一次：模拟 × 点击
    ts._remove(toast)
    assert ts.count() == 0
    # 第二次：模拟 timer 到期重复触发——必须静默返回，不抛 RuntimeError
    ts._remove(toast)
    assert ts.count() == 0
