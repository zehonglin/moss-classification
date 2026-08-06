import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QSplitter, QLabel,
    QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy, QFormLayout,
    QComboBox, QSpinBox, QDoubleSpinBox, QSlider, QLineEdit, QInputDialog, QListWidget,
    QListWidgetItem, QCheckBox, QAbstractSpinBox, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from app.controllers.system_controller import SystemController, STATUS_IDLE, STATUS_PREVIEWING, STATUS_RUNNING
from app.ui.widgets import HistoryItemWidget
from app.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, config_manager: ConfigManager, controller=None):
        super().__init__()
        self.setWindowTitle("苔藓识别系统 - Pro")
        self.resize(1280, 800)

        self.config = config_manager
        # controller 可注入（测试用）；生产路径由 SystemController 构造
        self.controller = controller if controller is not None else SystemController(self.config)
        self.selected_history_item = None
        self.status = STATUS_IDLE
        self.confidence_threshold = self.config.get("model_settings.confidence_threshold", 0.6)
        
        # Connect Controller Signals
        self.controller.image_updated.connect(self._update_image_display)
        self.controller.result_updated.connect(self._update_result_display)
        self.controller.status_updated.connect(self._update_status)
        self.controller.error_occurred.connect(self._handle_error)
        self.controller.disk_space_warning.connect(self._handle_disk_warning)
        self.controller.model_loaded.connect(self._on_model_loaded)
        self.controller.camera_info.connect(self._show_camera_info)
        self.controller.stats_updated.connect(self._update_stats_label)

        self._init_ui()
        self._load_history()
        self._update_status(STATUS_IDLE) # Set initial state
        logger.info("Main window initialized and UI is ready.")

    def _init_ui(self):
        # Main Layout: Sidebar (Left) + Content (Right)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Sidebar
        self.sidebar = self._create_sidebar()
        main_layout.addWidget(self.sidebar)

        # 2. Content Area
        content_area = QFrame()
        content_area.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(20)

        # 2.1 Top Bar (Status & Result)
        top_bar = self._create_top_bar()
        content_layout.addLayout(top_bar)

        # 2.2 Main Content (Image & History)
        splitter = QSplitter(Qt.Horizontal)
        
        self.image_feed_label = self._create_image_feed_area()
        history_area = self._create_history_area()  # 容器：筛选栏 + 历史列表
        self.history_list_widget.itemClicked.connect(self._on_history_item_clicked)
        
        splitter.addWidget(self.image_feed_label)
        splitter.addWidget(history_area)
        splitter.setSizes([700, 400]) 
        
        content_layout.addWidget(splitter, 1) # Set stretch factor to 1 to take remaining space
        
        main_layout.addWidget(content_area)

    def _create_spinbox_control(self, spinbox: QSpinBox) -> QWidget:
        """Creates a widget with a spinbox and custom +/- buttons."""
        container = QFrame()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        minus_button = QPushButton("-")
        minus_button.setObjectName("ValueButton")
        minus_button.clicked.connect(spinbox.stepDown)

        plus_button = QPushButton("+")
        plus_button.setObjectName("ValueButton")
        plus_button.clicked.connect(spinbox.stepUp)

        spinbox.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spinbox.setAlignment(Qt.AlignCenter)
        spinbox.lineEdit().setMinimumWidth(60)
        
        layout.addWidget(minus_button)
        layout.addWidget(spinbox, 1)
        layout.addWidget(plus_button)
        
        return container

    def _create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(260)
        sidebar.setMaximumWidth(320)
        main_sidebar_layout = QVBoxLayout(sidebar)
        main_sidebar_layout.setContentsMargins(20, 30, 20, 30)
        main_sidebar_layout.setSpacing(15)

        title = QLabel("苔藓识别系统")
        title.setObjectName("HeaderLabel")
        title.setAlignment(Qt.AlignCenter)
        main_sidebar_layout.addWidget(title)

        # 模拟相机模式标识：仅显式配置 driver_type=mock 时可见，防止操作员误用
        self.mock_badge = QLabel("模拟相机模式")
        self.mock_badge.setObjectName("MockBadge")
        self.mock_badge.setAlignment(Qt.AlignCenter)
        self.mock_badge.setStyleSheet(
            "background-color:#FFB300; color:#212121; border-radius:6px; padding:6px; font-weight:bold;"
        )
        self.mock_badge.setVisible(self.config.get("camera_settings.driver_type") == "mock")
        main_sidebar_layout.addWidget(self.mock_badge)
        
        # Wrap contents in a scroll area to handle small vertical screens
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(15)
        
        self.controls_group = QFrame()
        controls_layout = QFormLayout(self.controls_group)
        controls_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        controls_layout.setVerticalSpacing(15)

        # --- 触发模式 ---
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems(["预览模式", "传感器触发", "软件手动触发", "软件连续触发"])
        self._trigger_mode_keys = ["preview", "hardware", "software_single", "software_continuous"]
        cur_mode = self.config.get("camera_settings.trigger.mode", "preview")
        self.trigger_combo.setCurrentIndex(self._trigger_mode_keys.index(cur_mode) if cur_mode in self._trigger_mode_keys else 0)
        self.trigger_combo.currentIndexChanged.connect(self._on_trigger_mode_changed)
        controls_layout.addRow("触发模式:", self.trigger_combo)

        self.debouncer_spinbox = QSpinBox()
        self.debouncer_spinbox.setRange(0, 100000)
        self.debouncer_spinbox.setSingleStep(500)
        self.debouncer_spinbox.setValue(self.config.get("camera_settings.trigger.debouncer_time_us", 5000))
        self.debouncer_spinbox.setSuffix(" us")
        controls_layout.addRow("触发防抖:", self._create_spinbox_control(self.debouncer_spinbox))

        # --- Resolution Controls ---
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(256, 4096)
        self.width_spinbox.setSingleStep(64)
        self.width_spinbox.setValue(self.config.get("camera_settings.resolution_width", 2048))
        controls_layout.addRow("分辨率宽度:", self._create_spinbox_control(self.width_spinbox))

        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(256, 4096)
        self.height_spinbox.setSingleStep(64)
        self.height_spinbox.setValue(self.config.get("camera_settings.resolution_height", 2048))
        controls_layout.addRow("分辨率高度:", self._create_spinbox_control(self.height_spinbox))
        
        apply_res_button = QPushButton("应用分辨率")
        apply_res_button.clicked.connect(self._on_set_resolution_clicked)
        controls_layout.addRow(apply_res_button)
        # --- End Resolution Controls ---

        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(100, 60000)
        self.interval_spinbox.setValue(self.config.get("camera_settings.trigger.software_interval_ms", 1000))
        self.interval_spinbox.setSuffix(" ms")
        controls_layout.addRow("软件触发间隔:", self._create_spinbox_control(self.interval_spinbox))
        
        scroll_layout.addWidget(self.controls_group)

        scroll_layout.addWidget(QLabel("相机曝光 (us, 固定):"))

        self.exposure_spinbox = QSpinBox()
        self.exposure_spinbox.setRange(100, 1000000)
        self.exposure_spinbox.setSingleStep(1000)
        exp_config = self.config.get("camera_settings.exposure", 10000)
        self.exposure_spinbox.setValue(int(exp_config) if isinstance(exp_config, (int, float)) else 10000)
        exposure_control = self._create_spinbox_control(self.exposure_spinbox)
        scroll_layout.addWidget(exposure_control)
        self.exposure_spinbox.valueChanged.connect(self._on_exposure_changed)

        model_group = QFrame()
        model_layout = QFormLayout(model_group)
        model_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        model_layout.setVerticalSpacing(15)
        self.model_combo = QComboBox()
        self.model_combo.addItems(self.controller.get_available_models())
        self.model_combo.setCurrentText(self.config.get("model_settings.current_model_name", "efficientnet_b0"))
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        model_layout.addRow("选择模型:", self.model_combo)

        self.threshold_spinbox = QDoubleSpinBox()
        self.threshold_spinbox.setRange(0.0, 1.0)
        self.threshold_spinbox.setSingleStep(0.05)
        self.threshold_spinbox.setDecimals(2)
        self.threshold_spinbox.setValue(self.confidence_threshold)
        self.threshold_spinbox.valueChanged.connect(self._on_threshold_changed)
        model_layout.addRow("置信度阈值:", self.threshold_spinbox)
        scroll_layout.addWidget(model_group)
        
        scroll_layout.addStretch()

        # -- Action Buttons (Moved out of scroll area or kept at bottom of scroll?) --
        # Keeping them in scroll_layout ensures they are reachable on small screens via scrolling.
        self.toggle_camera_button = QPushButton("连接相机")
        self.toggle_camera_button.setObjectName("ConnectButton")
        self.toggle_camera_button.setMinimumHeight(45)

        self.start_button = QPushButton("开始运行")
        self.start_button.setObjectName("StartButton")
        self.start_button.setMinimumHeight(45)
        
        self.stop_button = QPushButton("停止运行")
        self.stop_button.setObjectName("StopButton")
        self.stop_button.setMinimumHeight(45)

        self.capture_button = QPushButton("拍照（软件触发）")
        self.capture_button.setObjectName("CaptureButton")
        self.capture_button.setMinimumHeight(45)
        self.capture_button.setEnabled(False)  # 仅 software_single 模式启用

        self.toggle_camera_button.clicked.connect(self._on_toggle_camera_connection)
        self.start_button.clicked.connect(self._on_start_clicked)
        self.stop_button.clicked.connect(self.controller.stop_system)
        self.capture_button.clicked.connect(self._on_capture_clicked)

        scroll_layout.addWidget(self.toggle_camera_button)
        scroll_layout.addWidget(self.start_button)
        scroll_layout.addWidget(self.stop_button)
        scroll_layout.addWidget(self.capture_button)
        
        scroll.setWidget(scroll_content)
        main_sidebar_layout.addWidget(scroll)

        return sidebar

    def _create_top_bar(self):
        self.result_panel = QFrame()
        self.result_panel.setObjectName("ResultPanel")
        self.result_panel.setMinimumHeight(120) # Increased min height so it occupies more space by default
        self.result_panel.setMaximumHeight(150)
        # Let it expand if needed, but min height ensures visibility
        container_layout = QHBoxLayout()
        layout = QHBoxLayout(self.result_panel)
        layout.setContentsMargins(20, 10, 20, 10)
        self.result_label = QLabel("请先连接相机")
        self.result_label.setObjectName("ResultLabel")
        self.result_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft) # Ensure text is centered vertically
        self.result_label.setWordWrap(True) # Allow text to wrap on small screens
        self.correction_button = QPushButton("纠错当前")
        self.correction_button.setFixedWidth(100)
        self.correction_button.clicked.connect(self._show_correction_dialog)
        layout.addWidget(self.result_label, 1) # Give label stretch priority
        layout.addWidget(self.correction_button)
        container_layout.addWidget(self.result_panel)
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("StatsLabel")
        self.stats_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.stats_label.setWordWrap(True)
        container_layout.addWidget(self.stats_label)
        return container_layout

    def _create_image_feed_area(self):
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("background-color: #000; border-radius: 8px; color: #555; font-weight: bold;")
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Reduced minimum size to allow window to shrink significantly
        label.setMinimumSize(100, 100) 
        return label

    def _create_history_area(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("品级:"))
        self.history_pred_combo = QComboBox()
        self.history_pred_combo.addItems(["全部品级", "A", "B", "C", "D"])
        filter_row.addWidget(self.history_pred_combo)
        filter_row.addWidget(QLabel("状态:"))
        self.history_quality_combo = QComboBox()
        self.history_quality_combo.addItems(["全部状态", "正常", "拒采"])
        filter_row.addWidget(self.history_quality_combo)
        self.filter_button = QPushButton("查询")
        self.filter_button.clicked.connect(self._on_history_filter_clicked)
        filter_row.addWidget(self.filter_button)
        self.export_button = QPushButton("导出 CSV")
        self.export_button.clicked.connect(self._on_export_clicked)
        filter_row.addWidget(self.export_button)
        layout.addLayout(filter_row)

        self.history_list_widget = QListWidget()
        self.history_list_widget.setSpacing(5)
        layout.addWidget(self.history_list_widget)
        return container

    def _on_exposure_changed(self):
        exposure_value = self.exposure_spinbox.value()
        self.config.set("camera_settings.exposure", exposure_value)
        self.controller.set_camera_exposure(exposure_value)

    def _on_set_resolution_clicked(self):
        width = self.width_spinbox.value()
        height = self.height_spinbox.value()
        logger.info(f"UI request to set resolution to {width}x{height}")
        self.controller.set_camera_resolution(width, height)

    def _on_toggle_camera_connection(self):
        if self.toggle_camera_button.text() == "连接相机":
            logger.info("UI request to connect camera...")
            self.toggle_camera_button.setText("连接中...")
            self.toggle_camera_button.setEnabled(False)
            self.controller.connect_camera()
        else:
            logger.info("UI request to disconnect camera...")
            self.controller.disconnect_camera()

    def _on_model_changed(self, text):
        if text != self.config.get("model_settings.current_model_name"):
            logger.info(f"UI initiated model switch to {text}...")
            # Disable controls during switch
            self.model_combo.setEnabled(False)
            self.toggle_camera_button.setEnabled(False)
            self.start_button.setEnabled(False)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self._perform_model_switch(text))

    def _perform_model_switch(self, model_name):
        # 后台加载（controller.reload_model 异步），完成后回调 _on_model_loaded 恢复控件
        self.controller.reload_model(model_name)

    def _on_model_loaded(self, ok, model_name):
        """模型后台加载完成，恢复控件。"""
        self.model_combo.setEnabled(True)
        self.toggle_camera_button.setEnabled(True)
        self.start_button.setEnabled(self.controller.camera.is_connected())
        if ok:
            self._update_status(self.status)
        else:
            self.result_label.setText(f"模型加载失败: {model_name}")

    def _on_threshold_changed(self, value):
        """置信度阈值变更：低于此值的结果标记为"需复检"。"""
        self.confidence_threshold = float(value)
        self.config.set("model_settings.confidence_threshold", self.confidence_threshold)
        logger.info(f"Confidence threshold set to {self.confidence_threshold}")

    def _on_trigger_mode_changed(self, index):
        """触发模式切换：记录 config + 通知 controller 配相机 + 管理拍照按钮。"""
        mode = self._trigger_mode_keys[index]
        self.config.set("camera_settings.trigger.mode", mode)
        self.config.set("camera_settings.trigger.debouncer_time_us", self.debouncer_spinbox.value())
        self.controller.set_trigger_mode(mode)
        self.capture_button.setEnabled(
            mode == "software_single" and self.controller.camera.is_connected()
        )
        logger.info(f"Trigger mode changed: {mode}")

    def _on_capture_clicked(self):
        """software_single 模式的拍照按钮。"""
        self.controller.capture_single()

    def _on_start_clicked(self):
        # 同步触发相关参数到 config（worker 启动时读取）
        self.config.set("camera_settings.trigger.software_interval_ms", self.interval_spinbox.value())
        self.config.set("camera_settings.trigger.debouncer_time_us", self.debouncer_spinbox.value())
        self.config.set("camera_settings.exposure", self.exposure_spinbox.value())
        logger.info("System start requested.")
        self.controller.start_system()

    def _update_image_display(self, q_image):
        # If an item is selected in the history, don't update the feed with live images
        if self.selected_history_item:
            return
            
        pixmap = QPixmap.fromImage(q_image)
        self.image_feed_label.setPixmap(pixmap.scaled(
            self.image_feed_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

    def _update_result_display(self, record_data: dict):
        """Receives a new record and updates the UI incrementally."""
        # 调试捕获（capture_single，id=None）：未入库，不进历史、不参与纠错
        if record_data.get("id") is None:
            pred = record_data.get("prediction", "?")
            conf = record_data.get("confidence", 0.0)
            conf_text = f" {conf:.1%}" if isinstance(conf, (int, float)) else ""
            self.result_label.setText(f"调试捕获（未入库）: {pred}{conf_text}")
            self.correction_button.setEnabled(False)
            return

        self._add_history_record(record_data)  # 列表始终更新（让操作员知道在采）
        # 选中历史项时，结果栏/画面保持在该历史项（不被新记录抢），只更新列表
        if self.selected_history_item:
            return
        quality_status = record_data.get("quality_status", "ok")
        if quality_status not in (None, "ok"):
            reason = record_data.get("rejected_reason") or quality_status
            self.result_label.setText(f"⚠️ 质量不合格（未出结果）: {reason}")
            self.result_label.setStyleSheet("color: #EF5350;")
            self.correction_button.setEnabled(False)
            return
        self._display_record_info(
            record_data['id'],
            record_data['prediction'],
            record_data['confidence']
        )

    def _add_history_record(self, record_data: dict):
        """
        Inserts a single new record at the top of the history list.
        
        Memory Management:
        - Explicitly deletes old items and their widgets when trimming
        - Limits list to 50 items to prevent unbounded growth
        """
        # Convert dict to the tuple format used elsewhere
        record_tuple = (
            record_data['id'],
            record_data['timestamp'],
            record_data['image_path'],
            record_data.get('thumbnail_path'),
            record_data['prediction'],
            record_data['confidence'],
            record_data['corrected_label'],
            record_data.get('quality_status', 'ok'),
        )
        
        # Create item without a parent
        item = QListWidgetItem()
        # Set data before inserting
        item.setData(Qt.UserRole, record_tuple)
        item_widget = HistoryItemWidget(
            record_data['image_path'],
            record_data.get('thumbnail_path'),
            record_data['timestamp'],
            record_data['prediction'],
            record_data['confidence'],
            record_data['corrected_label'] if record_data['corrected_label'] else "None",
            confidence_threshold=self.confidence_threshold,
            quality_status=record_data.get('quality_status', 'ok'),
        )
        item.setSizeHint(item_widget.sizeHint())

        # Insert at the top and then set the custom widget for that item
        self.history_list_widget.insertItem(0, item)
        self.history_list_widget.setItemWidget(item, item_widget)

        # Trim the list if it gets too long - with proper cleanup
        while self.history_list_widget.count() > 50:
            last_index = self.history_list_widget.count() - 1
            
            # Get the widget associated with the item BEFORE removing
            old_item = self.history_list_widget.item(last_index)
            old_widget = self.history_list_widget.itemWidget(old_item)
            
            # Remove the item from list (returns the item)
            removed_item = self.history_list_widget.takeItem(last_index)
            
            # Explicitly delete the widget to free memory (including QPixmap)
            if old_widget is not None:
                old_widget.deleteLater()
            
            # Delete the item itself
            del removed_item


    def _display_record_info(self, record_id, prediction, confidence, corrected_label=None):
        is_corrected = bool(corrected_label)
        needs_review = (not is_corrected) and isinstance(confidence, (int, float)) and confidence < self.confidence_threshold
        if needs_review:
            text = f"⚠️ 需复检  {prediction}  {confidence:.1%}"
            self.result_label.setStyleSheet("color: #FFA726;")  # 橙色:低置信度
        else:
            text = f"{prediction}  {confidence:.1%}"
            self.result_label.setStyleSheet("")  # 恢复 QSS 默认
        if corrected_label:
            text += f" (已纠错: {corrected_label})"
        self.result_label.setText(text)
        self.last_record_id = record_id
        self.last_prediction = prediction
        self.correction_button.setEnabled(True)

    def _update_status(self, status):
        self.status = status
        logger.info(f"UI received status update: {status}")

        # Update button states regardless of history view
        if status == STATUS_IDLE:
            self.toggle_camera_button.setText("连接相机")
            self.toggle_camera_button.setEnabled(True)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.controls_group.setEnabled(True)
            self.result_label.setText("请先连接相机")
            self.correction_button.setEnabled(False)
        elif status == STATUS_PREVIEWING:
            self.toggle_camera_button.setText("断开连接")
            self.toggle_camera_button.setEnabled(True)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.controls_group.setEnabled(True)
            self.result_label.setText("准备就绪,请开始运行")
            self.correction_button.setEnabled(False)
        elif status == STATUS_RUNNING:
            self.toggle_camera_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.controls_group.setEnabled(False)
            self.result_label.setText("运行中...")

        # Update image display only if not viewing a history item
        if self.selected_history_item:
            return

        if status == STATUS_IDLE:
            self.image_feed_label.setText("SYSTEM IDLE")
        elif status == STATUS_PREVIEWING:
            self.image_feed_label.setText("CAMERA LIVE")

    def _handle_error(self, message):
        logger.error(f"Received error in UI: {message}")
        self.result_label.setText(f"错误: {message}")
        # 可恢复错误：不清空连接状态（相机仍可能连接着），按钮状态由 controller 状态驱动。
        # 若确为未连接，controller 会单独发 status_updated(IDLE)。
        self.selected_history_item = None  # Reset history view on error

    def _handle_disk_warning(self, message):
        """通用警告显示（磁盘空间/相机无图等，经 disk_space_warning 信号转发）。"""
        logger.warning(f"Warning: {message}")
        self.result_label.setText(f"⚠️ {message}")
        self.result_label.setStyleSheet("color: #FFA726;")  # 橙色警告

    def _show_camera_info(self, message):
        """相机连接信息（序列号/型号）。"""
        logger.info(f"Camera info: {message}")
        self.result_label.setText(message)

    def _update_stats_label(self, stats: dict):
        """更新实时吞吐/耗时/超时统计。"""
        per_hour = stats.get("per_hour", 0)
        avg_ms = stats.get("avg_ms", 0)
        self.stats_label.setText(
            f"已处理 {stats.get('processed', 0)} 张 | ≈{per_hour:.0f} 张/小时 | "
            f"平均 {avg_ms:.0f}ms | 拒采 {stats.get('quality_rejects', 0)} 张 | "
            f"处理超时 {stats.get('processing_timeout_count', 0)} 次"
        )

    def _show_correction_dialog(self):
        """纠错。优先针对当前查看的历史项（selected），无选中则用最近一条（last）。

        纠错不得中断产线采集：不调用 stop_system，直接后台更新 DB 并刷新界面。
        """
        target_id, target_pred = self.last_record_id, self.last_prediction
        if self.selected_history_item:
            data = self.selected_history_item.data(Qt.UserRole)
            if data and data[0] is not None:
                target_id = data[0]      # id
                target_pred = data[4]    # prediction

        logger.info(f"Correction dialog initiated for record {target_id}.")
        corrected_label, ok = QInputDialog.getText(
            self, "纠错", f"当前识别为 '{target_pred}'.\n请输入正确类别:", QLineEdit.Normal, "")
        if ok and corrected_label:
            logger.info(f"Submitting correction for record {target_id}: '{corrected_label}'")
            self.controller.correct_prediction(target_id, corrected_label)
            self._update_history_item(target_id, corrected_label)
            self._display_record_info(target_id, target_pred, 0, corrected_label)
            self.result_label.setText(f"已提交纠错: {target_pred} → {corrected_label}")
        else:
            logger.info("Correction dialog cancelled. 采集状态不变。")

    def _update_history_item(self, record_id, corrected_label):
        """Finds a history item by ID and updates its corrected label."""
        for i in range(self.history_list_widget.count()):
            item = self.history_list_widget.item(i)
            record_data = list(item.data(Qt.UserRole)) # Get a mutable copy
            if record_data and record_data[0] == record_id:
                # Update the data stored in the item
                record_data[6] = corrected_label
                item.setData(Qt.UserRole, tuple(record_data))
                # Re-create the widget with the new data
                new_widget = HistoryItemWidget(
                    record_data[2], # image_path
                    record_data[3], # thumbnail_path
                    record_data[1], # timestamp
                    record_data[4], # prediction
                    record_data[5], # confidence
                    record_data[6],  # new corrected_label
                    confidence_threshold=self.confidence_threshold,
                    quality_status=record_data[7] if len(record_data) > 7 else "ok",
                )
                item.setSizeHint(new_widget.sizeHint())
                self.history_list_widget.setItemWidget(item, new_widget)
                break

    def _on_history_item_clicked(self, item):
        if self.selected_history_item == item:
            # Clicked the same item again: Deselect
            self.history_list_widget.setCurrentItem(None)
            self.selected_history_item = None
            logger.info("History item deselected. Resuming live/idle view.")
            # Re-apply the status to restore the correct image feed text (IDLE/LIVE)
            self._update_status(self.status)
        else:
            # A new item is selected
            self.selected_history_item = item
            record_data = item.data(Qt.UserRole)
            if record_data:
                r_id, _, img_path, thumb_path, pred, conf, corr_label, quality = record_data[:8]
                logger.info(f"History item clicked: Record ID {r_id}, Path: {img_path}")
                if quality not in (None, "ok"):
                    self.result_label.setText(f"⚠️ 质量不合格（未出结果）: {quality}")
                    self.result_label.setStyleSheet("color: #EF5350;")
                    self.correction_button.setEnabled(False)
                else:
                    self._display_record_info(r_id, pred, conf, corr_label)
                pixmap = QPixmap(img_path)
                if not pixmap.isNull():
                    self.image_feed_label.setPixmap(pixmap.scaled(
                        self.image_feed_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                else:
                    self.image_feed_label.setText(f"无法加载图片:\n{img_path}")

    def _load_history(self):
        self._populate_history(self.controller.get_recent_records())

    def _populate_history(self, records):
        self.history_list_widget.clear()
        for record in records:
            item = QListWidgetItem() # Create item without parent
            item.setData(Qt.UserRole, record)
            item_widget = HistoryItemWidget(
                record[2], # image_path
                record[3], # thumbnail_path
                record[1], # timestamp
                record[4], # prediction
                record[5], # confidence
                record[6] if record[6] else "None", # corrected_label
                confidence_threshold=self.confidence_threshold,
                quality_status=record[7] if len(record) > 7 else "ok",
            )
            item.setSizeHint(item_widget.sizeHint())
            self.history_list_widget.addItem(item)
            self.history_list_widget.setItemWidget(item, item_widget)

    def _on_history_filter_clicked(self):
        """按品级/状态查询历史（从 DB 检索，最多 200 条）。"""
        pred = self.history_pred_combo.currentText()
        quality_map = {"全部状态": None, "正常": "ok", "拒采": "rejected"}
        quality = quality_map.get(self.history_quality_combo.currentText())
        records = self.controller.get_filtered_records(
            prediction=None if pred == "全部品级" else pred,
            quality_status=quality,
            limit=200,
        )
        self._populate_history(records)

    def _on_export_clicked(self):
        """导出当前筛选结果为 CSV。"""
        pred = self.history_pred_combo.currentText()
        quality_map = {"全部状态": None, "正常": "ok", "拒采": "rejected"}
        quality = quality_map.get(self.history_quality_combo.currentText())
        records = self.controller.get_filtered_records(
            prediction=None if pred == "全部品级" else pred,
            quality_status=quality,
            limit=200,
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出记录", "moss_records.csv", "CSV 文件 (*.csv)"
        )
        if not path:
            return
        n = self.controller.export_history_csv(path, records)
        QMessageBox.information(self, "导出完成", f"已导出 {n} 条记录:\n{path}")

    def closeEvent(self, event):
        """窗口关闭时清理：停止 worker、断开相机、关闭数据库（WAL checkpoint）。"""
        logger.info("Application closing, shutting down controller...")
        try:
            self.controller.shutdown()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        event.accept()

