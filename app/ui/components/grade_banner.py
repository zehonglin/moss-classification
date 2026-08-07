"""GradeBanner 组件（横幅）+ banner_state 纯函数。

横幅显示当前品级（大字母 + 置信度），背景色按 grade=A/B/C/D/rejected/wait
着色（由全局 style.qss 的 `QFrame#GradeBanner[grade="..."]` 提供）。组件本身
不内联背景色——只通过 setObjectName + setProperty("grade", x) + polish 触发样式。

banner_state 是状态矩阵的核心：把 record dict 映射成横幅状态描述。设计原则
"正交"：低置信 review 态不改品级色（仍按 prediction 着色），仅切换 kind 与标签；
只有 rejected（拒采）和 corrected（人工纠正）会改变 grade/letter。
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


# 拒采质量原因 → 中文说明
_REJECT_REASONS = {
    "rejected_blur": "图像模糊",
    "rejected_overexposed": "过曝",
    "rejected_underexposed": "欠曝",
}


def _percent(conf):
    """置信度格式化为百分比；None / 非数值返回空串。"""
    return f"{conf:.0%}" if isinstance(conf, (int, float)) else ""


def banner_state(record, threshold):
    """record dict → 横幅状态描述（纯函数，无副作用，可单测）。

    返回 dict 字段：
      grade     —— style.qss 命中用的着色键（A/B/C/D/rejected/wait）
      letter    —— 大字字母显示（品级字母 / ⚠ / 占位符）
      conf      —— 置信度或拒采原因文本
      kind      —— normal|review|rejected|corrected|debug（wait 仅组件初始态）
      show_edit —— 是否显示 ✎ 纠错按钮

    状态优先级：
      1. rid=None            → debug  （未入库的调试捕获）
      2. quality 不合格      → rejected（grade="rejected"，灰底）
      3. corrected_label 非空 → corrected（grade/letter 用 corrected_label）
      4. confidence < 阈值   → review（品级色不变，仅切 kind）
      5. 其余                → normal
    """
    quality = record.get("quality_status") or "ok"
    rid = record.get("id")

    # 1. 调试捕获（未入库）
    if rid is None:
        pred = record.get("prediction") or "?"
        return {
            "grade": "wait",
            "letter": str(pred),
            "conf": _percent(record.get("confidence")),
            "kind": "debug",
            "show_edit": False,
        }

    # 2. 拒采（质量不合格）
    if quality not in ("ok", None):
        reason = _REJECT_REASONS.get(quality, quality)
        return {
            "grade": "rejected",
            "letter": "⚠",
            "conf": reason,
            "kind": "rejected",
            "show_edit": False,
        }

    # 3. 已人工纠错
    corr = record.get("corrected_label")
    if corr:
        return {
            "grade": corr,
            "letter": str(corr),
            "conf": f"原识别 {record.get('prediction')} · {_percent(record.get('confidence'))}",
            "kind": "corrected",
            "show_edit": True,
        }

    # 4/5. 正常出品级 / 低置信复检
    pred = record.get("prediction") or "?"
    conf = record.get("confidence")
    review = isinstance(conf, (int, float)) and conf < threshold
    return {
        "grade": pred,
        "letter": str(pred),
        "conf": _percent(conf),
        "kind": "review" if review else "normal",
        "show_edit": True,
    }


class GradeBanner(QFrame):
    """品级横幅。背景色由 style.qss 的 `[grade="..."]` 选择器控制。

    用 set_state(state) 应用一个 banner_state 返回的状态字典；改 grade 后必须
    unpolish+polish 才能让 Qt 重新求值 dynamic-property 选择器（Qt 不会自动重绘）。
    """

    correction_requested = Signal()

    def __init__(self, threshold=0.6):
        super().__init__()
        self.setObjectName("GradeBanner")
        self.setMinimumHeight(90)

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(20, 10, 20, 10)

        self._label = QLabel("当前品级")
        self._label.setStyleSheet("color:rgba(255,255,255,.85);font-size:10px;")
        self._letter = QLabel("")
        self._letter.setStyleSheet("font-size:40px;font-weight:800;")
        self._conf = QLabel("")
        self._conf.setStyleSheet("font-size:16px;font-weight:700;")
        self._tag = QLabel("")
        self._tag.setStyleSheet(
            "background:rgba(255,255,255,.22);"
            "border:1px solid rgba(255,255,255,.5);"
            "border-radius:20px;padding:3px 10px;"
        )
        self._edit = QPushButton("✎ 纠错")
        self._edit.setStyleSheet(
            "background:rgba(255,255,255,.9);color:#0f172a;"
            "border:none;border-radius:7px;padding:5px 12px;font-weight:600;"
        )
        self._edit.clicked.connect(self.correction_requested)

        self._lay.addWidget(self._label)
        self._lay.addWidget(self._letter)
        self._lay.addWidget(self._conf)
        self._lay.addStretch()
        self._lay.addWidget(self._tag)
        self._lay.addWidget(self._edit)

        # 初始占位态（kind=wait，仅组件内部使用）
        self.set_state({"grade": "wait", "letter": "—", "conf": "", "kind": "wait", "show_edit": False})

    def set_state(self, state):
        """应用 banner_state 返回的状态字典，并刷新 QSS dynamic property 样式。"""
        self.setProperty("grade", state["grade"])
        self._letter.setText(str(state["letter"]))
        self._conf.setText(str(state["conf"]))

        kind = state["kind"]
        if kind == "review":
            self._label.setText("当前品级")
            self._tag.setText("⚠ 需复检")
            self._tag.show()
        elif kind == "corrected":
            self._label.setText("当前品级")
            self._tag.setText("人工纠正")
            self._tag.show()
        elif kind == "rejected":
            self._label.setText("质量不合格")
            self._tag.setText("未出品级")
            self._tag.show()
        elif kind == "wait":
            self._label.setText("等待识别")
            self._tag.hide()
        else:  # normal / debug
            self._label.setText("当前品级")
            self._tag.hide()

        self._edit.setVisible(state["show_edit"])

        # dynamic property 改变后必须手动 polish，否则 QSS 不会重新求值
        self.style().unpolish(self)
        self.style().polish(self)

    def set_reviewing(self, on):
        """标记"正在查看历史"——覆盖 _tag 文本并显示。"""
        if on:
            self._tag.setText("正在查看历史记录")
            self._tag.show()
