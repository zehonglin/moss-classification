"""CameraView 取景器组件（实时态 + 选中历史态 + 双击全屏 + 正方形铺满）。

v3 变更（UI 评审 D3c）：相机画面为正方形（2048×2048），取景区域按
**高=宽** 设定——`_view` 不放进 layout，而是在 resizeEvent 里手动计算
居中正方形几何（side = min(w, h)），图像缩放后正好铺满整个设定区域，
左右由深色画框（容器背景）自然延伸，不再出现非匹配比例的缩放留白。

QWidget 容器包两层：
    - `_view`（QLabel#CameraView）：实时态显示相机帧；选中历史时显示原图。
      由全局 `style.qss` 的 `QLabel#CameraView` 规则命中深色背景。
    - `_retbar`（QWidget 返回条）：仅选中历史时 show，悬浮在容器顶部。
      含 `◀ 返回实时` 按钮 + 时间信息 + "ESC 退出查看"提示。

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
    QWidget,
)

# 空状态占位文案（含操作引导；"实时画面"前缀保留以兼容既有断言/用户习惯）
_PLACEHOLDER = "实时画面\n\n连接相机 → 开始运行"


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
    """取景器容器（QWidget 包 正方形 QLabel#CameraView + 返回条）。

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
        # 容器深色画框：正方形 _view 之外的左右延伸区。
        # 注意：plain QWidget 必须开 WA_StyledBackground，QSS/内联背景才会绘制
        # （否则左右延伸区显示系统默认浅灰 —— 实测运行时就漏了这个属性）
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background:#0d0d0d;border-radius:12px;")
        self.setMinimumSize(200, 200)

        # —— 取景画面 QLabel（手动几何：居中正方形，不进 layout） ——
        self._view = _ClickableLabel(_PLACEHOLDER, self)
        self._view.setObjectName("CameraView")  # 背景/线框/圆角命中 style.qss
        self._view.setAlignment(Qt.AlignCenter)
        # 内联只放占位文案的字体属性；视觉样式（含 3px 灰色线框）归 style.qss
        self._view.setStyleSheet("font-size:13px;letter-spacing:3px;line-height:1.8;")
        self._view.doubleClicked.connect(self.request_fullscreen)

        # —— 返回条（默认隐藏） ——
        self._retbar = QWidget(self)
        self._retbar.setAttribute(Qt.WA_StyledBackground, True)  # plain QWidget 须开此属性才画背景
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

        self._ret_zoom = QLabel("ESC 退出查看")
        self._ret_zoom.setStyleSheet("color:#94a3b8;")

        rh.addWidget(self._ret_back)
        rh.addWidget(self._ret_info)
        rh.addStretch()
        rh.addWidget(self._ret_zoom)
        self._retbar.hide()

    # ---------- Qt hooks ----------

    def resizeEvent(self, e):
        """容器缩放 → _view 取居中正方形（side = min(w,h)），返回条贴容器顶。"""
        super().resizeEvent(e)
        w, h = self.width(), self.height()
        side = min(w, h)
        self._view.setGeometry((w - side) // 2, (h - side) // 2, side, side)
        self._retbar.setFixedWidth(w)
        self._retbar.move(0, 0)
        self._retbar.raise_()

    # ---------- public API ----------

    def set_live(self, qimage):
        """实时帧刷新。

        `_reviewing=True` 时直接 return（看历史时不让实时帧覆盖原图）。
        `qimage=None` → 显示空状态占位（相机未连接/初始化阶段）。

        注意：QLabel.setPixmap 会清空 text，setText 会清空 pixmap —— 两互斥。
        所以"显示占位文案"时先 clear pixmap 再 setText；"显示 pixmap"时先 setText("")
        再 setPixmap。正方形帧缩放到正方形 _view = 恰好铺满整个设定区域。
        """
        if self._reviewing:
            return
        if qimage is None:
            # 先清 pixmap（setPixmap 会清 text），再 setText 设占位
            self._view.setPixmap(QPixmap())
            self._view.setText(_PLACEHOLDER)
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
        self._view.setText(_PLACEHOLDER)

    # ---------- public accessors ----------

    def is_reviewing(self) -> bool:
        """返回是否处于选中历史态（替代上层直访 `_reviewing` 私有成员）。"""
        return self._reviewing
