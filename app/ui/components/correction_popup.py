"""CorrectionPopup 气泡纠错组件。

点横幅 ✎ 弹出的气泡：4 个纯字母品级色按钮 A/B/C/D（无描述文字），
当前品级按钮加白边框 outline + "当前"角标；点选即 emit grade_selected 并 close。

设计要点：
- `setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)`——气泡无标题栏、点外部自动关。
- 按钮**只显示字母**（用户明确要求），用品级色背景 + 白字大号粗体；不内联"铺满/覆盖高"等描述。
- `_badges[g]` 是每个按钮上方的角标 QLabel，当前品级显示"当前"，其他为空。
- `popup_for(record, anchor)`：record['prediction'] 决定当前品级，气泡 move 到
  anchor 全局 bottomLeft 附近（左偏 80px 防 popup 右溢出）后 show。
- `grade_selected = Signal(str)`，`_click(grade)` emit 后 close。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

# 品级 → 色值（与 style.qss / GradeBanner 对齐）
GRADES = [("A", "#16a34a"), ("B", "#65a30d"), ("C", "#d97706"), ("D", "#dc2626")]

# 按钮基础样式（无 outline）；当前品级追加 _OUTLINE_STYLE
_BUTTON_BASE_STYLE = (
    "color:#fff;border:none;border-radius:10px;"
    "font-size:28px;font-weight:800;padding:0;"
)
_OUTLINE_STYLE = "outline:3px solid #fff;outline-offset:2px;"
_BADGE_STYLE = "color:#fff;background:#0f172a;border-radius:6px;padding:1px 6px;font-size:10px;font-weight:600;"


class CorrectionPopup(QFrame):
    """品级纠正气泡：4 按钮 A/B/C/D，当前品级标"当前"，点选即提交并关闭。

    用法：
        pop = CorrectionPopup()
        pop.grade_selected.connect(controller.apply_correction)
        pop.popup_for(record, banner_widget)  # 在 banner 下方弹出
    """

    grade_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("CorrectionPopup")
        self.setStyleSheet("background:#1e293b;border:1px solid #334155;border-radius:12px;")

        self._current = None
        self._btns: dict[str, QPushButton] = {}
        self._badges: dict[str, QLabel] = {}

        # 整体纵向布局：标题 / 按钮行 / 提示
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        title = QLabel("纠正品级 · 点选正确品级")
        title.setStyleSheet("color:#e2e8f0;font-size:12px;font-weight:600;")
        v.addWidget(title)

        # 四按钮横排（每格 = 角标 + 按钮 的纵向小布局）
        row = QHBoxLayout()
        row.setSpacing(8)
        for g, color in GRADES:
            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell.setAlignment(Qt.AlignCenter)

            badge = QLabel("")
            badge.setStyleSheet(_BADGE_STYLE)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedHeight(16)
            self._badges[g] = badge

            btn = QPushButton(g)
            btn.setFixedSize(70, 64)
            btn.setStyleSheet(f"background:{color};{_BUTTON_BASE_STYLE}")
            btn.clicked.connect(lambda _checked=False, gg=g: self._click(gg))
            self._btns[g] = btn

            cell.addWidget(badge)
            cell.addWidget(btn)
            row.addLayout(cell)
        v.addLayout(row)

        self._info = QLabel("")
        self._info.setStyleSheet("color:#94a3b8;font-size:10px;")
        self._info.setAlignment(Qt.AlignCenter)
        v.addWidget(self._info)

    def popup_for(self, record, anchor):
        """根据 record（含 prediction）标记当前品级，并在 anchor 下方弹出。

        - record["prediction"]：当前品级字母（A/B/C/D），缺失则全部不标记。
        - anchor：参照 QWidget，气泡 move 到其全局 bottomLeft 下方约 6px。
        """
        self._current = record.get("prediction") if record else None
        self._apply_current_mark()

        if self._current:
            self._info.setText(f"当前 {self._current} · 可再次改正")
        else:
            self._info.setText("请选择品级")

        # 锚定在 anchor 下方（左偏 80px 防止 popup 右侧溢出屏幕）
        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.move(gp.x() - 80, gp.y() + 6)
        self.show()

    def _apply_current_mark(self):
        """根据 _current 重置每个按钮的 outline + 角标文本。"""
        for g, btn in self._btns.items():
            base = f"background:{dict(GRADES)[g]};{_BUTTON_BASE_STYLE}"
            if g == self._current:
                btn.setStyleSheet(base + _OUTLINE_STYLE)
                self._badges[g].setText("当前")
            else:
                btn.setStyleSheet(base)
                self._badges[g].setText("")

    def _click(self, grade):
        """按钮点击内部入口：emit grade_selected 并关闭气泡。

        测试可直接调用此方法（避免真实 click 事件依赖窗口可见）。
        """
        self.grade_selected.emit(grade)
        self.close()
