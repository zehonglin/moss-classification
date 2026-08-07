"""ToastStack 通知组件 + severity_for 纯函数。

右上角通知栈：controller 的 disk_space_warning / error_occurred 信号由外层
路由到这里，按 message 关键词判 severity（danger/warn）后显示 toast。每个 toast
默认 6 秒后自动消失，也可点 × 手动关闭。**不抢品级横幅**——品级横幅归
GradeBanner，这里只处理瞬态告警。

样式由全局 style.qss 的 `QFrame#Toast[severity="..."]` 选择器提供；组件本身
不内联背景色，仅通过 setObjectName("Toast") + setProperty("severity", x) + polish
命中 QSS。
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

# message 含任一关键词 → danger（致命级，红）；否则 warn（警示级，黄）
_DANGER_KEYWORDS = ("严重不足", "已停止", "内存不足", "失败", "致命")


def severity_for(message):
    """按 message 关键词判 severity：含 danger 关键词返回 "danger"，否则 "warn"。

    纯函数（无 Qt 副作用），便于单测。controller 的信号文本约定：
      - disk_space_warning → "磁盘空间严重不足" / "磁盘空间警告"
      - error_occurred     → "采集失败" / "模型未加载，采集已停止" / "内存不足"
    """
    return "danger" if any(k in message for k in _DANGER_KEYWORDS) else "warn"


class _Toast(QFrame):
    """单条 toast：标题 + 正文 + × 关闭按钮。

    依赖 style.qss 的 `QFrame#Toast[severity="warn|danger"]` 着色——构造时
    setObjectName + setProperty + polish 触发样式。
    """

    def __init__(self, message, severity, on_close):
        super().__init__()
        self.setObjectName("Toast")
        self.setProperty("severity", severity)

        v = QVBoxLayout(self)
        v.setContentsMargins(11, 9, 11, 9)
        v.setSpacing(2)

        is_warn = severity == "warn"
        title = QLabel("⚠ 警告" if is_warn else "⚠ 错误")
        title.setStyleSheet(
            "font-weight:700;"
            f"color:{'#92400e' if is_warn else '#991b1b'};"
        )
        body = QLabel(message)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color:{'#78350f' if is_warn else '#7f1d1d'};"
            "font-size:11px;"
        )
        v.addWidget(title)
        v.addWidget(body)

        if on_close:
            close = QPushButton("×")
            close.setStyleSheet("border:none;color:#94a3b8;font-size:14px;padding:0 2px;")
            close.setCursor(Qt.PointingHandCursor)
            close.clicked.connect(lambda: on_close(self))
            v.addWidget(close, alignment=Qt.AlignRight)

        # setProperty 后必须 polish，QSS dynamic-property 选择器才会生效
        self.style().unpolish(self)
        self.style().polish(self)


class ToastStack(QFrame):
    """Toast 容器（右上角纵向栈）。

    用法：
        ts = ToastStack()
        ts.show("磁盘空间严重不足", severity="danger")  # severity 可省，由 message 推断
    外层（MainWindow / 信号路由器）可：
        controller.disk_space_warning.connect(lambda msg: ts.show(msg, severity_for(msg)))
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("ToastStack")
        self.setWindowFlags(Qt.FramelessWindowHint)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)
        # 末尾 stretch：新 toast 用 insertWidget(count-1) 插在 stretch 之前，
        # 保持栈顶对齐；count() 返回时减去这个 stretch。
        self._lay.addStretch()

    def show(self, message, severity="warn", timeout_ms=6000):
        """新增一条 toast。

        - severity：手动指定；调用方可配合 severity_for(message) 按关键词推断。
        - timeout_ms>0：到时自动移除；==0：不自动关（测试用）。
        返回新建的 _Toast 实例（便于测试直接调 _remove）。
        """
        toast = _Toast(message, severity, self._remove)
        # 插在 stretch 之前（栈顶对齐）
        self._lay.insertWidget(self._lay.count() - 1, toast)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, lambda: self._remove(toast))
        self.adjustSize()
        return toast

    def _remove(self, toast):
        """移除并销毁一条 toast（× 关闭 / 定时器到期 共用）。"""
        self._lay.removeWidget(toast)
        toast.deleteLater()

    def count(self):
        """当前 toast 数（减去末尾的 stretch item）。"""
        return self._lay.count() - 1
