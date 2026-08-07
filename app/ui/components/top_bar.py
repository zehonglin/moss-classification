"""TopStatBar 顶部统计栏。

操作员/工程师双模式完全一致（同一组件），订阅 controller
`grade_summary_updated(dict)` 显示 A/B/C/D/纠错/不合格累计 + 磁盘 + 运行状态 +
模式切换按钮。

布局（左→右）：
    logo "苔藓识别" | 模式切换按钮（"操作员 ▾"/"工程师 ▾"）| 运行状态 | stretch
    | A/B/C/D 统计（品级色点●+字母+数字）| 分隔 | ✎纠错 n | ⚠不合格 n
    | stretch | 磁盘 | 🔔

样式由全局 `style.qss` 命中：
    QFrame#TopBar       —— 白底 + 下边框
    QLabel#RunState     —— 默认绿色字（idle 时由组件内联样式覆盖为灰）
    QLabel#StatItem     —— 品级统计行（b 标签加深为标题色）
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

# 品级 → 色点颜色（与 style.qss GradeBanner 同源语义色）
_DOT = {"A": "#16a34a", "B": "#65a30d", "C": "#d97706", "D": "#dc2626"}

# 运行状态枚举 → 中文文案
_RUN = {
    "live": "运行中（实时图像）",
    "history": "运行中（历史图像）",
    "idle": "已停止",
}


def _grade_text(g: str, n: int) -> str:
    """A/B/C/D 统计行富文本：色点 + 字母 + 加粗数字。"""
    return f'<span style="color:{_DOT[g]}">●</span> {g} <b>{n}</b>'


class TopStatBar(QFrame):
    """顶部统计栏容器（QFrame#TopBar）。

    Signals:
        mode_change_requested(str): 点模式按钮时发出 "engineer"/"operator"
            （切到对方模式）；由上层决定是否真的切换（工程师模式可能需要密码）。
    """

    mode_change_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("TopBar")
        self.setFixedHeight(56)

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(12)

        # 左：logo + 模式切换 + 运行状态
        logo = QLabel("苔藓识别")
        logo.setStyleSheet("font-weight:700;")
        h.addWidget(logo)

        self._mode = QPushButton("操作员 ▾")
        self._mode.setStyleSheet(
            "background:#f1f5f9;border:1px solid #e2e8f0;border-radius:7px;padding:4px 10px;"
        )
        self._mode.clicked.connect(self._on_mode_clicked)
        h.addWidget(self._mode)

        self._run = QLabel(_RUN["idle"])
        self._run.setObjectName("RunState")
        # idle 灰色字覆盖 qss 默认绿（live/history 复用 qss 绿色）
        self._run.setStyleSheet("color:#94a3b8;font-weight:600;")
        h.addWidget(self._run)

        h.addStretch()

        # 中：A/B/C/D + 分隔 + 纠错 + 不合格
        self._stats: dict[str, QLabel] = {}
        for g in ("A", "B", "C", "D"):
            lab = QLabel(_grade_text(g, 0))
            lab.setObjectName("StatItem")
            self._stats[g] = lab
            h.addWidget(lab)

        sep = QLabel("|")
        sep.setStyleSheet("color:#e2e8f0;")
        h.addWidget(sep)

        corrected = QLabel("✎纠错 <b>0</b>")
        corrected.setObjectName("StatItem")
        self._stats["corrected"] = corrected
        h.addWidget(corrected)

        rejected = QLabel("⚠不合格 <b>0</b>")
        rejected.setObjectName("StatItem")
        self._stats["rejected"] = rejected
        h.addWidget(rejected)

        h.addStretch()

        # 右：磁盘 + 通知
        self._disk = QLabel("💾 — GB")
        h.addWidget(self._disk)

        self._bell = QLabel("🔔")
        h.addWidget(self._bell)

    # ---------- public API ----------

    def set_grade_summary(self, s: dict):
        """更新 A/B/C/D/纠错/不合格 数字。

        与 controller `grade_summary_updated(dict)` 信号直接相连；缺 key 按 0 渲染。
        """
        for g in ("A", "B", "C", "D"):
            self._stats[g].setText(_grade_text(g, int(s.get(g, 0) or 0)))
        self._stats["corrected"].setText(f'✎纠错 <b>{int(s.get("corrected", 0) or 0)}</b>')
        self._stats["rejected"].setText(f'⚠不合格 <b>{int(s.get("rejected", 0) or 0)}</b>')

    def set_disk(self, gb_text: str):
        """更新磁盘占用文本（直接拼入"💾 "前缀）。"""
        self._disk.setText(f"💾 {gb_text}")

    def set_run_state(self, state: str):
        """state ∈ {'live','history','idle'} → 文案 + 颜色（live/history 绿、idle 灰）。"""
        self._run.setText(_RUN.get(state, _RUN["idle"]))
        if state in ("live", "history"):
            self._run.setStyleSheet("color:#16a34a;font-weight:600;")
        else:
            self._run.setStyleSheet("color:#94a3b8;font-weight:600;")

    def set_mode(self, mode: str):
        """mode='engineer'→"工程师 ▾"，'operator'→"操作员 ▾"。"""
        self._mode.setText("工程师 ▾" if mode == "engineer" else "操作员 ▾")

    # ---------- internals ----------

    def _on_mode_clicked(self):
        """点模式按钮 → 请求切到对方模式。"""
        current_is_operator = self._mode.text().startswith("操作员")
        self.mode_change_requested.emit("engineer" if current_is_operator else "operator")
