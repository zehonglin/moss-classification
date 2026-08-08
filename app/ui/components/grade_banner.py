"""GradeBanner 组件（横幅）+ banner_state 纯函数。

横幅显示当前品级（大字母 + 品级描述词 + 置信度进度条 + 数值），背景色按
grade=A/B/C/D/rejected/wait 着色（由全局 style.qss 的
`QFrame#GradeBanner[grade="..."]` 提供）。组件本身不内联背景色——只通过
setObjectName + setProperty("grade", x) + polish 触发样式。

banner_state 是状态矩阵的核心：把 record dict 映射成横幅状态描述。设计原则
"正交"：低置信 review 态不改品级色（仍按 prediction 着色），仅切换 kind 与标签；
只有 rejected（质量不合格）和 corrected（人工纠正）会改变 grade/letter。

v3 业务口径（2026-08-08 确认）：
- 品级描述词：A 良好 / B 中等 / C 较差 / D 不合格（均为正常品级，非动作指令）；
- "需复检"仅由置信度低于阈值触发，与品级本身无关；
- 质量不合格图像正常入库——文案"图像质量不合格 · {原因} · 原图已入库"，
  不使用"拒采/未出品级"等丢弃语义。
"""
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.ui.components.design_tokens import GRADE_NAMES, REJECT_REASONS

# 向后兼容别名（旧代码/测试可能引用 `_REJECT_REASONS`）
_REJECT_REASONS = REJECT_REASONS

# 等待态 spinner 帧（QSS 不支持动画，用 QTimer 轮转字符实现）
_SPINNER_FRAMES = ("◐", "◓", "◑", "◒")


def _percent(conf):
    """置信度格式化为百分比；None / 非数值返回空串。"""
    return f"{conf:.0%}" if isinstance(conf, (int, float)) else ""


def banner_state(record, threshold):
    """record dict → 横幅状态描述（纯函数，无副作用，可单测）。

    返回 dict 字段：
      grade      —— style.qss 命中用的着色键（A/B/C/D/rejected/wait）
      letter     —— 大字字母显示（品级字母 / ⚠ / 占位符）
      gname      —— 品级描述词（良好/中等/较差/不合格；无品级时为空串）
      conf       —— 置信度或质量原因文本
      conf_value —— 置信度数值（0~1，驱动进度条；非数值为 None）
      kind       —— normal|review|rejected|corrected|debug（wait 仅组件初始态）
      show_edit  —— 是否显示 ✎ 纠错按钮

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
        conf = record.get("confidence")
        return {
            "grade": "wait",
            "letter": str(pred),
            "gname": GRADE_NAMES.get(str(pred), ""),
            "conf": _percent(conf),
            "conf_value": conf if isinstance(conf, (int, float)) else None,
            "kind": "debug",
            "show_edit": False,
        }

    # 2. 质量不合格（图像正常入库留存）
    if quality not in ("ok", None):
        reason = REJECT_REASONS.get(quality, quality)
        return {
            "grade": "rejected",
            "letter": "⚠",
            "gname": "",
            "conf": reason,
            "conf_value": None,
            "kind": "rejected",
            "show_edit": False,
        }

    # 3. 已人工纠错
    corr = record.get("corrected_label")
    if corr:
        conf = record.get("confidence")
        return {
            "grade": corr,
            "letter": str(corr),
            "gname": GRADE_NAMES.get(str(corr), ""),
            "conf": f"原识别 {record.get('prediction')} · {_percent(conf)}",
            "conf_value": conf if isinstance(conf, (int, float)) else None,
            "kind": "corrected",
            "show_edit": True,
        }

    # 4/5. 正常出品级 / 低置信复检（复检仅与置信度有关，与品级无关）
    pred = record.get("prediction") or "?"
    conf = record.get("confidence")
    review = isinstance(conf, (int, float)) and conf < threshold
    return {
        "grade": pred,
        "letter": str(pred),
        "gname": GRADE_NAMES.get(str(pred), ""),
        "conf": _percent(conf),
        "conf_value": conf if isinstance(conf, (int, float)) else None,
        "kind": "review" if review else "normal",
        "show_edit": True,
    }


class GradeBanner(QFrame):
    """品级横幅。背景色由 style.qss 的 `[grade="..."]` 选择器控制。

    布局：当前品级标签 / [大字母 | 描述词] + 置信度进度条+数值 … [徽章][✎ 纠错]
    用 set_state(state) 应用一个 banner_state 返回的状态字典；改 grade 后必须
    unpolish+polish 才能让 Qt 重新求值 dynamic-property 选择器（Qt 不会自动重绘）。
    """

    correction_requested = Signal()

    def __init__(self, threshold=0.6):
        super().__init__()
        self.setObjectName("GradeBanner")
        self.setMinimumHeight(96)

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(20, 10, 20, 10)
        self._lay.setSpacing(16)

        # 左：标签 + (大字母 | 描述词)
        left = QVBoxLayout()
        left.setSpacing(2)
        self._label = QLabel("当前品级")
        # 颜色归 QSS（BannerLabel 规则；wait 态 slate 覆盖）——勿内联白色，
        # 否则 wait 浅底上"等待识别"白字不可见（内联样式优先级高于 app QSS）
        self._label.setObjectName("BannerLabel")
        self._label.setStyleSheet("font-size:11px;font-weight:600;letter-spacing:2px;")
        left.addWidget(self._label)

        grade_row = QHBoxLayout()
        grade_row.setSpacing(14)
        self._letter = QLabel("")
        self._letter.setStyleSheet("font-size:58px;font-weight:800;")
        grade_row.addWidget(self._letter)

        self._divider = QFrame()
        self._divider.setFixedWidth(1)
        self._divider.setStyleSheet("background:rgba(255,255,255,.35);")
        grade_row.addWidget(self._divider)

        self._gname = QLabel("")
        self._gname.setStyleSheet("font-size:24px;font-weight:700;")
        grade_row.addWidget(self._gname)
        grade_row.addStretch()
        left.addLayout(grade_row)
        self._lay.addLayout(left)

        # 中：置信度进度条 + 数值
        conf_box = QVBoxLayout()
        conf_box.setSpacing(4)
        conf_row = QHBoxLayout()
        self._conf_bar = QProgressBar()
        self._conf_bar.setObjectName("BannerConfBar")
        self._conf_bar.setRange(0, 100)
        self._conf_bar.setTextVisible(False)
        self._conf_bar.setFixedWidth(170)
        conf_row.addWidget(self._conf_bar)
        self._conf = QLabel("")
        self._conf.setStyleSheet("font-size:16px;font-weight:700;")
        conf_row.addWidget(self._conf)
        conf_box.addLayout(conf_row)
        self._lay.addLayout(conf_box)

        self._lay.addStretch()

        self._tag = QLabel("")
        self._tag.setStyleSheet(
            "background:rgba(255,255,255,.22);"
            "border:1px solid rgba(255,255,255,.5);"
            "border-radius:20px;padding:3px 10px;font-size:11px;font-weight:700;"
        )
        self._edit = QPushButton("✎ 纠错")
        self._edit.setStyleSheet(
            "background:rgba(255,255,255,.95);color:#0f172a;"
            "border:none;border-radius:7px;padding:8px 16px;font-weight:600;font-size:13px;"
        )
        self._edit.clicked.connect(self.correction_requested)

        self._lay.addWidget(self._tag)
        self._lay.addWidget(self._edit)

        # 低置信 review 态脉冲边框：QSS 不支持 animation，用 QTimer 周期切
        # review_pulse property + qss[review_pulse="1"] 白边框实现闪烁
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(500)
        self._pulse_on = False
        self._pulse_timer.timeout.connect(self._tick_pulse)

        # 等待态 spinner 轮转（驱动大字母位，58px slate，等待感明确）
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(300)
        self._spin_idx = 0
        self._spin_timer.timeout.connect(self._tick_spinner)

        # 初始占位态（kind=wait，仅组件内部使用）：字母位放 spinner 首帧，
        # conf 区给一句引导文案（对齐 mockup wait 态的说明性文字）
        self.set_state({"grade": "wait", "letter": _SPINNER_FRAMES[0], "gname": "",
                        "conf": "识别结果将显示在这里", "conf_value": None,
                        "kind": "wait", "show_edit": False})

    def set_state(self, state):
        """应用 banner_state 返回的状态字典，并刷新 QSS dynamic property 样式。"""
        self.setProperty("grade", state["grade"])
        self._letter.setText(str(state["letter"]))
        self._gname.setText(str(state.get("gname", "")))
        self._conf.setText(str(state["conf"]))

        # 置信度进度条：有数值时显示并填充，否则隐藏
        conf_value = state.get("conf_value")
        if isinstance(conf_value, (int, float)) and state["kind"] in (
            "normal", "review", "corrected", "debug",
        ):
            self._conf_bar.setValue(int(round(conf_value * 100)))
            self._conf_bar.show()
        else:
            self._conf_bar.hide()

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
            self._label.setText("图像质量不合格")
            self._tag.setText("原图已入库")
            self._tag.show()
        elif kind == "wait":
            self._label.setText("等待识别")
            self._tag.hide()
        else:  # normal / debug
            self._label.setText("当前品级")
            self._tag.hide()

        # 分隔线仅在"字母+描述词"成对出现时有意义（wait/rejected 无描述词 → 隐藏，避免孤线）
        self._divider.setVisible(bool(state.get("gname")))

        self._edit.setVisible(state["show_edit"])

        # review 态：启动脉冲；其他态：停止 + 复位 review_pulse
        if kind == "review":
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
            self._pulse_on = False
            self.setProperty("review_pulse", "0")

        # wait 态：启动 spinner（驱动 _letter 轮转 ◐◓◑◒）；其他态停止
        if kind == "wait":
            self._spin_timer.start()
        else:
            self._spin_timer.stop()

        # dynamic property 改变后必须手动 polish，否则 QSS 不会重新求值
        self.style().unpolish(self)
        self.style().polish(self)
        # 子标签颜色规则依赖祖先 grade property（QFrame#GradeBanner[grade=...] QLabel）：
        # polish 自身不会级联重算后代 —— 不显式重抛光的话，wait 态的 slate 字色
        # 会残留到出品级之后（实测：操作员模式下首个结果横幅字母呈 slate 色）。
        for w in (self._label, self._letter, self._gname, self._conf):
            w.style().unpolish(w)
            w.style().polish(w)

    def set_reviewing(self, on):
        """标记"正在查看历史"——覆盖 _tag 文本并显示。"""
        if on:
            self._tag.setText("正在查看历史记录")
            self._tag.show()

    def _tick_pulse(self):
        """review 态脉冲：周期切 review_pulse property 让 qss 白边框闪烁。"""
        self._pulse_on = not self._pulse_on
        self.setProperty("review_pulse", "1" if self._pulse_on else "0")
        self.style().unpolish(self)
        self.style().polish(self)

    def _tick_spinner(self):
        """wait 态 spinner：大字母位轮转 ◐◓◑◒ 帧字符（等待感）。"""
        self._spin_idx = (self._spin_idx + 1) % len(_SPINNER_FRAMES)
        self._letter.setText(_SPINNER_FRAMES[self._spin_idx])

    # ---------- public accessors ----------

    def edit_button(self):
        """返回纠错按钮 widget（供 CorrectionPopup popup_for 锚定）。

        替代上层直访 `banner._edit` 私有成员。
        """
        return self._edit
