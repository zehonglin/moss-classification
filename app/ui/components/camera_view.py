"""CameraView 取景器组件（实时态 + 选中历史态 + 双击全屏）。

QWidget 容器包两层：
    - `_view`（QLabel#CameraView）：实时态显示相机帧；选中历史时显示原图。
      由全局 `style.qss` 的 `QLabel#CameraView` 规则命中深色背景。
    - `_retbar`（QWidget 返回条）：仅选中历史时 show，悬浮在 `_view` 顶部。
      含 `◀ 返回实时` 按钮 + 时间信息 + "双击全屏"提示。

态机：
    `_reviewing` 标志单向切换两个态：
      False（默认/实时）  → set_live 刷帧；返回条 hide。
      True（选中历史）    → set_live 直接 return（不覆盖原图）；返回条 show。

信号：
    back_to_live:      返回按钮 click → 上层 clear_history + 回实时流。
    request_fullscreen: _view doubleClicked → 上层弹全屏看大图。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _ClickableLabel(QLabel):
    """QLabel 子类：补 doubleClicked 信号（QLabel 原生不带）。

    mouseDoubleClickEvent → emit doubleClicked()；上层 CameraView 桥接到
    `request_fullscreen`。
    """

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)
        self.doubleClicked.emit()


class CameraView(QWidget):
    """取景器容器（QWidget 包 QLabel#CameraView + 返回条）。

    Public API:
        set_live(qimage|None):        实时态刷帧；reviewing 时跳过。
        set_history(img_or_path, ts): 进选中态、显示原图 + 返回条。
        clear_history():              退出选中态、回实时占位。

    Signals:
        back_to_live():       返回按钮 click。
        request_fullscreen(): _view 双击。
    """

    back_to_live = Signal()
    request_fullscreen = Signal()

    def __init__(self):
        super().__init__()
        self._reviewing = False

        # —— 取景画面 QLabel ——
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._view = _ClickableLabel("实时画面")
        self._view.setObjectName("CameraView")  # 命中 style.qss
        self._view.setAlignment(Qt.AlignCenter)
        self._view.setMinimumSize(200, 200)
        self._view.setStyleSheet(
            "background:#171717;color:#525252;border-radius:8px;"
            "font-size:13px;letter-spacing:3px;"
        )
        self._view.doubleClicked.connect(self.request_fullscreen)
        v.addWidget(self._view)

        # —— 返回条（默认隐藏） ——
        self._retbar = QWidget()
        self._retbar.setStyleSheet("background:rgba(0,0,0,.6);")
        rh = QHBoxLayout(self._retbar)
        rh.setContentsMargins(12, 7, 12, 7)
        rh.setSpacing(8)

        self._ret_back = QPushButton("◀ 返回实时")
        self._ret_back.setStyleSheet(
            "background:#fff;color:#0f172a;border:none;border-radius:6px;"
            "padding:4px 10px;font-weight:600;"
        )
        self._ret_back.clicked.connect(self.back_to_live)

        self._ret_info = QLabel("")
        self._ret_info.setStyleSheet("color:#e5e7eb;")

        self._ret_zoom = QLabel("双击全屏 · 滚轮缩放")
        self._ret_zoom.setStyleSheet("color:#94a3b8;")

        rh.addWidget(self._ret_back)
        rh.addWidget(self._ret_info)
        rh.addStretch()
        rh.addWidget(self._ret_zoom)

        # 悬浮在 _view 之上（同父），resizeEvent 同步宽度
        self._retbar.setParent(self)
        self._retbar.move(0, 0)
        self._retbar.hide()

    # ---------- Qt hooks ----------

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._retbar.setFixedWidth(self.width())
        self._retbar.raise_()

    # ---------- public API ----------

    def set_live(self, qimage):
        """实时帧刷新。

        `_reviewing=True` 时直接 return（看历史时不让实时帧覆盖原图）。
        `qimage=None` → 显示"实时画面"占位（相机未连接/初始化阶段）。

        注意：QLabel.setPixmap 会清空 text，setText 会清空 pixmap —— 两互斥。
        所以"显示占位文案"时先 clear pixmap 再 setText；"显示 pixmap"时先 setText("")
        再 setPixmap。
        """
        if self._reviewing:
            return
        if qimage is None:
            # 先清 pixmap（setPixmap 会清 text），再 setText 设占位
            self._view.setPixmap(QPixmap())
            self._view.setText("实时画面")
            return
        self._view.setText("")
        self._view.setPixmap(
            QPixmap.fromImage(qimage).scaled(
                self._view.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def set_history(self, image_or_path, timestamp):
        """进入选中历史态：显示原图 + 返回条。

        Args:
            image_or_path: QImage 实例 / 图片路径 str / None（无图也进历史态）。
            timestamp: 用于返回条信息显示（"查看历史 · {ts} · 原图"）。
        """
        self._reviewing = True
        self._view.setText("历史原图")
        if image_or_path is not None:
            pm = (
                QPixmap(image_or_path)
                if isinstance(image_or_path, str)
                else QPixmap.fromImage(image_or_path)
            )
            if not pm.isNull():
                self._view.setPixmap(
                    pm.scaled(
                        self._view.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
        self._ret_info.setText(f"查看历史 · <b>{timestamp}</b> · 原图")
        self._retbar.show()
        self._retbar.raise_()

    def clear_history(self):
        """退出选中态：隐藏返回条 + 清画面 + 回实时占位。"""
        self._reviewing = False
        self._retbar.hide()
        # setPixmap 会清 text → 先 clear pixmap 再 setText 占位
        self._view.setPixmap(QPixmap())
        self._view.setText("实时画面")
