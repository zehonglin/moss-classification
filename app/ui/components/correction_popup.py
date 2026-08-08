"""CorrectionPopup 气泡纠错组件（v3 浅色卡片版）。

点横幅 ✎ 弹出的气泡：4 个品级色按钮 A/B/C/D，按钮**只显示字母**（品级描述词
良好/中等/较差/不合格放在按钮下方的小字里，不占用按钮文本），当前品级按钮
加深色 outline + "当前"角标；点选即 emit grade_selected 并 close。

v3 变更（UI 评审 I6）：
- 深色 slate 弹层 → **浅色卡片**（与整体浅色体系一致），顶部带锚定箭头；
- 按钮下方补品级描述词小字（与横幅/历史项措辞一致）；
- 数字键 1–4 快捷选择（操作员手不离键盘，3 秒内完成纠错），ESC 关闭；
- 当前品级 outline 由白色改为深色（浅色卡片上白框不可见）。

设计要点：
- `setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)`——气泡无标题栏、点外部自动关。
- `popup_for(record, anchor)`：record['prediction'] 决定当前品级，气泡 move 到
  anchor 全局 bottomLeft 附近（左偏 80px 防 popup 右溢出）后 show。
- `grade_selected = Signal(str)`，`_click(grade)` emit 后 close。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from app.ui.components.design_tokens import GRADE_COLORS, GRADE_NAMES

# 品级 → 色值（取自 design_tokens 单一来源；与 style.qss / GradeBanner 对齐）
GRADES = [(g, GRADE_COLORS[g]) for g in ("A", "B", "C", "D")]

# 按钮基础样式（无 outline）；当前品级追加 _OUTLINE_STYLE（深色——浅色卡片上白框不可见）
_BUTTON_BASE_STYLE = (
    "color:#fff;border:none;border-radius:10px;"
    "font-size:28px;font-weight:800;padding:0;"
)
_OUTLINE_STYLE = "border:3px solid #0f172a;"
_BADGE_STYLE = "color:#fff;background:#0f172a;border-radius:6px;padding:1px 6px;font-size:10px;font-weight:600;"
_NAME_STYLE = "color:#64748b;font-size:10.5px;font-weight:600;"


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
        # 外层透明：卡片 _card 有背景，顶部箭头用字符三角模拟
        self.setStyleSheet("background:transparent;")

        self._current = None
        self._btns: dict[str, QPushButton] = {}
        self._badges: dict[str, QLabel] = {}
        self._names: dict[str, QLabel] = {}

        # 整体纵向布局：箭头 / 卡片
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 顶部锚定箭头（白色三角字符，右对齐于卡片纠错按钮锚点附近）
        arrow_row = QHBoxLayout()
        arrow_row.setContentsMargins(0, 0, 46, 0)
        arrow_row.addStretch()
        arrow = QLabel("▲")
        arrow.setStyleSheet("color:#ffffff;font-size:12px;")
        arrow_row.addWidget(arrow)
        outer.addLayout(arrow_row)

        # 卡片
        self._card = QFrame()
        self._card.setStyleSheet(
            "background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;"
        )
        v = QVBoxLayout(self._card)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        title = QLabel("纠正品级 · 点选或按 1–4")
        title.setStyleSheet("color:#0f172a;font-size:12.5px;font-weight:700;")
        v.addWidget(title)

        # 四按钮横排（每格 = 角标 + 按钮 + 描述词 的纵向小布局）
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
            btn.setFixedSize(70, 60)
            btn.setStyleSheet(f"background:{color};{_BUTTON_BASE_STYLE}")
            btn.clicked.connect(lambda _checked=False, gg=g: self._click(gg))
            self._btns[g] = btn

            name = QLabel(GRADE_NAMES[g])
            name.setStyleSheet(_NAME_STYLE)
            name.setAlignment(Qt.AlignCenter)
            self._names[g] = name

            cell.addWidget(badge)
            cell.addWidget(btn)
            cell.addWidget(name)
            row.addLayout(cell)
        v.addLayout(row)

        self._info = QLabel("")
        self._info.setStyleSheet("color:#64748b;font-size:10.5px;")
        self._info.setAlignment(Qt.AlignCenter)
        v.addWidget(self._info)

        outer.addWidget(self._card)

        # 数字键 1–4 快捷选择（popup 激活时生效）
        for i, (g, _color) in enumerate(GRADES, start=1):
            sc = QShortcut(QKeySequence(str(i)), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(lambda gg=g: self._click(gg))

    def popup_for(self, record, anchor):
        """根据 record（含 prediction）标记当前品级，并在 anchor 下方弹出。

        - record["prediction"]：当前品级字母（A/B/C/D），缺失则全部不标记。
        - anchor：参照 QWidget，气泡 move 到其全局 bottomLeft 下方约 6px。
        """
        self._current = record.get("prediction") if record else None
        self._apply_current_mark()

        if self._current:
            self._info.setText(f"当前 {self._current} · 可再次改正 · ESC 关闭")
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
