"""TopStatBar 顶部统计栏（v3）。

操作员/工程师双模式完全一致（同一组件），订阅 controller
`grade_summary_updated(dict)`。

v3 变更（对照 UI 评审 D5/D6/D8/I9）：
- **统计折叠**：A/B/C/D/纠错/质量异常 6 组明细从常驻改为单一 chip
  "今日 N 盘 · 通过率 x% ▾"，点击弹出明细层（StatsPopup）——操作员视线
  不被管理数据稀释，明细仍一键可达。`_stats` 标签组保留在弹出层内。
- **通过率口径**：(A+B+C) / (A+B+C+D)；D 不合格不计入通过；质量异常不计入分母。
  "今日 N 盘" = A+B+C+D+质量异常（全部入库记录）。
- **模式切换分段控件**：[操作员 | 工程师 ⚙]，当前段高亮；点非当前段
  emit mode_change_requested(target)。替代原"操作员 ▾"下拉式按钮。
- **运行状态**：颜色改由 QSS dynamic property（state="live|idle"）命中，
  不再内联 setStyleSheet 覆盖（样式归 QSS 的架构约定）。

布局（左→右）：
    logo "苔藓识别" | 模式分段控件 | 运行状态 | stretch
    | 统计 chip（点击弹明细）| 磁盘

样式由全局 `style.qss` 命中：
    QFrame#TopBar / QLabel#RunState[state] / QLabel#StatItem
    QPushButton#StatChip / QFrame#StatsPopup
    QFrame#ModeSeg / QPushButton#ModeSegBtn[active]
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.ui.components.design_tokens import GRADE_COLORS

# 品级 → 色点颜色（向后兼容别名；取自 design_tokens 单一来源）
_DOT = GRADE_COLORS

# 运行状态枚举 → 中文文案
_RUN = {
    "live": "运行中（实时图像）",
    "history": "运行中（历史图像）",
    "idle": "已停止",
}


def _grade_text(g: str, n: int) -> str:
    """A/B/C/D 统计行富文本：色点 + 字母 + 描述词 + 加粗数字。"""
    return f'<span style="color:{_DOT[g]}">●</span> {g} <b>{n}</b>'


class TopStatBar(QFrame):
    """顶部统计栏容器（QFrame#TopBar）。

    Signals:
        mode_change_requested(str): 点非当前模式段时发出 "engineer"/"operator"；
            由上层决定是否真的切换（工程师模式可能需要密码）。
    """

    mode_change_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("TopBar")
        self.setFixedHeight(56)
        self._mode = "operator"
        self._summary = {}

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(12)

        # 左：logo + 模式分段控件 + 运行状态
        logo = QLabel("苔藓识别")
        logo.setStyleSheet("font-weight:700;")
        h.addWidget(logo)

        seg = QFrame()
        seg.setObjectName("ModeSeg")
        seg_l = QHBoxLayout(seg)
        seg_l.setContentsMargins(3, 3, 3, 3)
        seg_l.setSpacing(2)
        self._mode_op = QPushButton("操作员")
        self._mode_eng = QPushButton("工程师 ⚙")  # ⚙=U+2699 雅黑自带；勿用 plane-1 emoji（🔒 无字形会变方框）
        for b in (self._mode_op, self._mode_eng):
            b.setObjectName("ModeSegBtn")
            seg_l.addWidget(b)
        self._mode_op.clicked.connect(lambda: self._request_mode("operator"))
        self._mode_eng.clicked.connect(lambda: self._request_mode("engineer"))
        h.addWidget(seg)
        self._apply_mode_highlight()

        self._run = QLabel(_RUN["idle"])
        self._run.setObjectName("RunState")
        self._run.setProperty("state", "idle")
        self._run.style().unpolish(self._run)
        self._run.style().polish(self._run)
        h.addWidget(self._run)

        h.addStretch()

        # 右一：统计折叠 chip（点击弹明细）
        self._chip = QPushButton("今日 0 盘 · 通过率 — ▾")
        self._chip.setObjectName("StatChip")
        self._chip.clicked.connect(self._toggle_stats_popup)
        h.addWidget(self._chip)

        # 明细弹出层（Qt.Popup：点外部自动关）
        self._popup = QFrame(self, Qt.Popup)
        self._popup.setObjectName("StatsPopup")
        pop_l = QVBoxLayout(self._popup)
        pop_l.setContentsMargins(14, 10, 14, 10)
        pop_l.setSpacing(6)
        title = QLabel("今日累计（按最终品级）")
        title.setStyleSheet("font-weight:700;font-size:12px;")
        pop_l.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        self._stats: dict[str, QLabel] = {}
        for i, g in enumerate(("A", "B", "C", "D")):
            lab = QLabel(_grade_text(g, 0))
            lab.setObjectName("StatItem")
            self._stats[g] = lab
            grid.addWidget(lab, 0, i)
        corrected = QLabel("✎纠错 <b>0</b>")
        corrected.setObjectName("StatItem")
        self._stats["corrected"] = corrected
        grid.addWidget(corrected, 1, 0, 1, 2)
        rejected = QLabel("⚠质量异常 <b>0</b>")
        rejected.setObjectName("StatItem")
        self._stats["rejected"] = rejected
        grid.addWidget(rejected, 1, 2, 1, 2)
        pop_l.addLayout(grid)
        self._popup.hide()

        # 右二：磁盘余量
        self._disk = QLabel("磁盘 — GB")
        self._disk.setStyleSheet("color:#64748b;font-size:12.5px;")
        h.addWidget(self._disk)

    # ---------- public API ----------

    def set_grade_summary(self, s: dict):
        """更新统计 chip + 明细层数字。

        与 controller `grade_summary_updated(dict)` 信号直接相连；缺 key 按 0 渲染。
        通过率 = (A+B+C)/(A+B+C+D)；分母为 0 显示 "—"。
        今日盘数 = A+B+C+D+质量异常（质量异常图像同样入库，计入盘数）。
        """
        self._summary = dict(s or {})
        n = {k: int(self._summary.get(k, 0) or 0)
             for k in ("A", "B", "C", "D", "corrected", "rejected")}
        for g in ("A", "B", "C", "D"):
            self._stats[g].setText(_grade_text(g, n[g]))
        self._stats["corrected"].setText(f'✎纠错 <b>{n["corrected"]}</b>')
        self._stats["rejected"].setText(f'⚠质量异常 <b>{n["rejected"]}</b>')

        graded = n["A"] + n["B"] + n["C"] + n["D"]
        total = graded + n["rejected"]
        if graded > 0:
            pct = f"{(n['A'] + n['B'] + n['C']) / graded * 100:.1f}%"
        else:
            pct = "—"
        self._chip.setText(f"今日 {total:,} 盘 · 通过率 {pct} ▾")

    def set_disk(self, gb_text: str):
        """更新磁盘占用文本（前缀"磁盘 "）。"""
        self._disk.setText(f"磁盘 {gb_text}")

    def set_run_state(self, state: str):
        """state ∈ {'live','history','idle'} → 文案 + QSS property（live/history 绿、idle 灰）。"""
        self._run.setText(_RUN.get(state, _RUN["idle"]))
        self._run.setProperty("state", "idle" if state == "idle" else "live")
        self._run.style().unpolish(self._run)
        self._run.style().polish(self._run)

    def set_mode(self, mode: str):
        """mode='engineer'/'operator' → 分段控件高亮对应段。"""
        self._mode = mode
        self._apply_mode_highlight()

    # ---------- internals ----------

    def _request_mode(self, target):
        """点非当前段 → 请求切换；点当前段不动作。"""
        if target != self._mode:
            self.mode_change_requested.emit(target)

    def _apply_mode_highlight(self):
        """按 _mode 设置两段按钮的 active property 并 polish。"""
        is_op = self._mode == "operator"
        self._mode_op.setProperty("active", "1" if is_op else "0")
        self._mode_eng.setProperty("active", "0" if is_op else "1")
        for b in (self._mode_op, self._mode_eng):
            b.style().unpolish(b)
            b.style().polish(b)

    def _toggle_stats_popup(self):
        """点统计 chip → 在 chip 下方弹出/收起明细层。"""
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._popup.adjustSize()
        gp = self._chip.mapToGlobal(self._chip.rect().bottomLeft())
        # 右对齐 chip 右缘，防左侧空悬
        x = gp.x() + self._chip.width() - self._popup.width()
        self._popup.move(x, gp.y() + 6)
        self._popup.show()
        self._popup.raise_()
