"""ParamSidebar 工程师参数栏（仅工程师模式用）。

QFrame#ParamSidebar 容器，分组布局：
    - 相机：触发模式 / 触发防抖 / 分辨率宽高 + 应用 / 软件间隔（条件显示） / 曝光
    - 模型：当前模型 / 置信度阈值
    - 质量检查：模糊 / 过曝 / 欠曝 三个阈值字段（quality_check.* config，热生效）
    - 底部操作按钮：连接相机 / 开始运行 / 停止运行 / 拍照（软件触发）

**软件间隔行**仅当触发模式 = `software_continuous` 时显示，其余隐藏。可见性
由纯函数 `_interval_visible_for(mode) -> bool` 决定，便于在 offscreen 测试环境
下断言。

样式由全局 `style.qss` 命中：
    QFrame#ParamSidebar                  —— 白底 + 右分隔线
    QLabel#GroupTitle                    —— 灰色小号大写组标题
    QPushButton#ActionConnect/#Capture   —— 中性灰
    QPushButton#ActionStart              —— 主操作绿
    QPushButton#ActionStop               —— 警示红
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class ParamSidebar(QFrame):
    """工程师参数栏容器（QFrame#ParamSidebar）。

    Public API:
        set_trigger_mode(mode): 设置触发模式 combo + 联动软件间隔行可见性。
        _interval_visible_for(mode) -> bool: 纯函数，仅 software_continuous=True。

    Signals (12):
        trigger_changed(str):    触发模式 combo 切换。
        debouncer_changed(int):  触发防抖 us。
        resolution_apply(int,int): 分辨率应用按钮 (w, h)。
        exposure_changed(int):   固定曝光 us。
        interval_changed(int):   软件间隔 ms。
        model_changed(str):      当前模型名。
        threshold_changed(float): 置信度阈值。
        quality_threshold_changed(str, float): 质量阈值（config key 后缀, 值）。
        connect_clicked():       连接相机按钮。
        start_clicked():         开始运行按钮。
        stop_clicked():          停止运行按钮。
        capture_clicked():       拍照按钮。
    """

    # ---- 11+1 signals ----
    trigger_changed = Signal(str)
    debouncer_changed = Signal(int)
    resolution_apply = Signal(int, int)
    exposure_changed = Signal(int)
    interval_changed = Signal(int)
    model_changed = Signal(str)
    threshold_changed = Signal(float)
    # 质量检查阈值：(config key 后缀, 值) —— "blur_threshold"/"overexposure_threshold"/"underexposure_threshold"
    quality_threshold_changed = Signal(str, float)
    connect_clicked = Signal()
    start_clicked = Signal()
    stop_clicked = Signal()
    capture_clicked = Signal()

    # combo 选项：显示文本 → 内部 key
    _TRIGGER_LABELS = ["预览", "传感器触发", "软件单张", "软件连续"]
    _TRIGGER_KEYS = ["preview", "hardware", "software_single", "software_continuous"]

    def __init__(self):
        super().__init__()
        self.setObjectName("ParamSidebar")
        self.setMinimumWidth(240)

        # 记录所有组标题（供测试 / qss 校验）
        self._group_titles: list[QLabel] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(10)

        # 相机参数组（含软件间隔行）
        camera_group, camera_rows = self._build_camera_group()
        v.addWidget(camera_group)

        # 模型参数组
        model_group = self._build_model_group()
        v.addWidget(model_group)

        # 质量检查组（模糊/过曝/欠曝三个真实阈值字段，绑定 quality_check.* config）
        quality_group = self._build_quality_group()
        v.addWidget(quality_group)

        v.addStretch()

        # 底部操作按钮组
        ops_title = QLabel("操作")
        ops_title.setObjectName("GroupTitle")
        v.addWidget(ops_title)
        self._b_conn = self._action_btn("连接相机", self.connect_clicked, "ActionConnect")
        self._b_start = self._action_btn("开始运行", self.start_clicked, "ActionStart")
        self._b_stop = self._action_btn("停止运行", self.stop_clicked, "ActionStop")
        self._b_cap = self._action_btn("拍照（软件触发）", self.capture_clicked, "ActionCapture")
        for b in (self._b_conn, self._b_start, self._b_stop, self._b_cap):
            v.addWidget(b)

    # ================================================================
    # 纯函数（TDD 重点）：仅 software_continuous 返回 True
    # ================================================================
    def _interval_visible_for(self, mode: str) -> bool:
        """软件间隔行可见性判定（纯函数，不依赖 widget 状态）。

        Args:
            mode: 触发模式 key（preview/hardware/software_single/software_continuous）。
        Returns:
            仅 `software_continuous` 返回 True，其余 False。
        """
        return mode == "software_continuous"

    # ================================================================
    # public API
    # ================================================================
    def set_trigger_mode(self, mode: str):
        """设置触发模式 combo + 联动软件间隔行可见性。

        未知 mode → 回落到 preview (index 0)。
        """
        idx = self._TRIGGER_KEYS.index(mode) if mode in self._TRIGGER_KEYS else 0
        # setCurrentIndex 会触发 currentIndexChanged → _on_trigger，但若 idx 未变
        # 不会触发，所以显式调用一次 _on_trigger 保证状态一致。
        self._trigger.setCurrentIndex(idx)
        self._on_trigger(self._TRIGGER_KEYS[idx])

    def set_models(self, models: list):
        """填充模型 combo（替代直访 `_model.addItems`）。"""
        self._model.addItems(models)

    def set_current_model(self, name: str):
        """设置当前模型 combo（用于初始化 / 模型加载失败后恢复）。

        若 name 不在 combo 列表中，不做任何操作（避免选空）。
        """
        if name and self._model.findText(name) >= 0:
            self._model.setCurrentText(name)

    def get_current_model(self) -> str:
        """返回当前模型 combo 文本（供模型加载失败时恢复）。"""
        return self._model.currentText()

    def set_threshold(self, value: float):
        """设置置信度阈值（替代直访 `_thr.setValue`）。"""
        self._thr.setValue(value)

    def set_quality_thresholds(self, blur: float, over: int, under: int):
        """填充质量检查三阈值初始值（由上层从 quality_check.* config 注入）。

        setValue 会触发 valueChanged → quality_threshold_changed → config.set，
        写入同值无害（与其他参数的初始化模式一致）。
        """
        self._blur.setValue(blur)
        self._over.setValue(over)
        self._under.setValue(under)

    def set_resolution(self, width: int, height: int):
        """填充分辨率宽高初值（由上层从 camera_settings.* config 注入）。

        不触发 resolution_apply（仅"应用"按钮 emit），故启动注入不会重复下发硬件。
        """
        self._w.setValue(width)
        self._h.setValue(height)

    def set_exposure(self, value: int):
        """填充固定曝光初值。setValue 同值无害（同其他参数初始化模式）。"""
        self._exposure.setValue(value)

    def set_debouncer(self, value: int):
        """填充触发防抖初值。"""
        self._debouncer.setValue(value)

    def set_interval(self, value: int):
        """填充软件间隔初值（仅 software_continuous 时该行可见）。"""
        self._interval.setValue(value)

    def set_buttons_running(self, running: bool):
        """操作按钮禁用状态机：运行中 → 开始禁用/停止可用；已停止 → 反之。"""
        self._b_start.setEnabled(not running)
        self._b_stop.setEnabled(running)

    # ================================================================
    # internals：构建分组
    # ================================================================
    def _build_camera_group(self) -> tuple[QFrame, QFrame]:
        """构建相机参数组。返回 (group_frame, interval_row) 用于布局插入。"""
        # 触发模式 combo
        self._trigger = QComboBox()
        self._trigger.addItems(self._TRIGGER_LABELS)
        self._trigger.currentIndexChanged.connect(
            lambda i: self._on_trigger(self._TRIGGER_KEYS[i])
        )

        # 触发防抖
        self._debouncer = QSpinBox()
        self._debouncer.setRange(0, 100000)
        self._debouncer.setSingleStep(500)
        self._debouncer.setSuffix(" us")
        self._debouncer.valueChanged.connect(self.debouncer_changed)

        # 分辨率宽 / 高 + 应用按钮
        self._w = QSpinBox()
        self._w.setRange(256, 4096)
        self._w.setSingleStep(64)
        self._h = QSpinBox()
        self._h.setRange(256, 4096)
        self._h.setSingleStep(64)
        self._apply_res = QPushButton("应用")
        self._apply_res.clicked.connect(
            lambda: self.resolution_apply.emit(self._w.value(), self._h.value())
        )

        # 软件间隔行（条件显示）—— 独立 QFrame，初始 hide
        self._interval = QSpinBox()
        self._interval.setRange(100, 60000)
        self._interval.setSingleStep(100)
        self._interval.setSuffix(" ms")
        self._interval.valueChanged.connect(self.interval_changed)
        self._interval_row = QFrame()
        ir = QFormLayout(self._interval_row)
        ir.setContentsMargins(0, 0, 0, 0)
        ir.setSpacing(4)
        ir.addRow("软件间隔:", self._interval)
        self._interval_row.hide()  # 默认隐藏（初始 preview 模式）

        # 固定曝光
        self._exposure = QSpinBox()
        self._exposure.setRange(100, 1000000)
        self._exposure.setSingleStep(1000)
        self._exposure.setSuffix(" us")
        self._exposure.valueChanged.connect(self.exposure_changed)

        rows = [
            ("触发模式:", self._trigger),
            ("触发防抖:", self._debouncer),
            ("分辨率宽:", self._w),
            ("分辨率高:", self._h),
            ("", self._apply_res),
            ("曝光(固定):", self._exposure),
        ]
        group = self._make_group("相机", rows, extra=self._interval_row)
        return group, self._interval_row

    def _build_model_group(self) -> QFrame:
        self._model = QComboBox()
        self._model.currentTextChanged.connect(self.model_changed)
        self._thr = QDoubleSpinBox()
        self._thr.setRange(0.0, 1.0)
        self._thr.setSingleStep(0.05)
        self._thr.setDecimals(2)
        self._thr.valueChanged.connect(self.threshold_changed)
        rows = [("当前模型:", self._model), ("置信度阈值:", self._thr)]
        return self._make_group("模型", rows)

    def _build_quality_group(self) -> QFrame:
        """质量检查三阈值（对齐 mockup：模糊/过曝/欠曝各一行真实数值字段）。

        取值范围与 config_manager 默认值口径一致：
            模糊阈值  —— 拉普拉斯方差，0~10000，默认 50.0（一位小数）
            过曝阈值  —— 灰度均值上限，0~255，默认 235
            欠曝阈值  —— 灰度均值下限，0~255，默认 25
        SystemController 每帧实时读 config → config.set 即热生效。
        """
        self._blur = QDoubleSpinBox()
        self._blur.setRange(0.0, 10000.0)
        self._blur.setDecimals(1)
        self._blur.setSingleStep(5.0)
        self._blur.valueChanged.connect(
            lambda v: self.quality_threshold_changed.emit("blur_threshold", v)
        )

        self._over = QSpinBox()
        self._over.setRange(0, 255)
        self._over.valueChanged.connect(
            lambda v: self.quality_threshold_changed.emit("overexposure_threshold", v)
        )

        self._under = QSpinBox()
        self._under.setRange(0, 255)
        self._under.valueChanged.connect(
            lambda v: self.quality_threshold_changed.emit("underexposure_threshold", v)
        )

        rows = [
            ("模糊阈值:", self._blur),
            ("过曝阈值:", self._over),
            ("欠曝阈值:", self._under),
        ]
        return self._make_group("质量检查", rows)

    def _make_group(self, title: str, rows: list[tuple[str, object]], extra=None) -> QFrame:
        """组装一个参数组：组标题 + 表单行（+ 可选附加 widget）。

        Args:
            title: 组标题文案。
            rows: list of (label_text, widget)；label_text 为空串时不带 label。
            extra: 可选附加 widget（如软件间隔行），追加在表单之后。
        """
        group = QFrame()
        L = QVBoxLayout(group)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(4)

        t = QLabel(title)
        t.setObjectName("GroupTitle")
        self._group_titles.append(t)
        L.addWidget(t)

        form = QFormLayout()
        form.setSpacing(4)
        form.setContentsMargins(0, 0, 0, 0)
        for label, w in rows:
            if label == "":
                form.addRow(w)
            else:
                form.addRow(label, w)
        L.addLayout(form)

        if extra is not None:
            L.addWidget(extra)

        return group

    def _action_btn(self, text: str, sig, object_name: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(object_name)
        b.clicked.connect(sig)
        return b

    # ================================================================
    # internals：触发模式切换处理
    # ================================================================
    def _on_trigger(self, mode: str):
        """触发模式切换 → 软件间隔行可见性 + emit trigger_changed。

        注意：combo 的 currentIndexChanged 在 setCurrentIndex 时也会触发，
        这里始终 emit 以保证上层收到最新模式（多次 emit 同值是无害的）。
        """
        visible = self._interval_visible_for(mode)
        self._interval_row.setVisible(visible)
        self.trigger_changed.emit(mode)
