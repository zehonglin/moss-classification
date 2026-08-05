import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QSplitter, QLabel,
    QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy, QFormLayout,
    QComboBox, QSpinBox, QDoubleSpinBox, QSlider, QLineEdit, QInputDialog, QListWidget,
    QListWidgetItem, QCheckBox, QAbstractSpinBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from app.controllers.system_controller import SystemController, STATUS_IDLE, STATUS_PREVIEWING, STATUS_RUNNING
from app.ui.widgets import HistoryItemWidget
from app.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.setWindowTitle("苔藓识别系统 - Pro")
        self.resize(1280, 800)
        
        self.config = config_manager
        self.controller = SystemController(self.config)
        self.selected_history_item = None
        self.status = STATUS_IDLE
        self.confidence_threshold = self.config.get("model_settings.confidence_threshold", 0.6)
        
        # Connect Controller Signals
        self.controller.image_updated.connect(self._update_image_display)
        self.controller.result_updated.connect(self._update_result_display)
        self.controller.status_updated.connect(self._update_status)
        self.controller.error_occurred.connect(self._handle_error)
        self.controller.disk_space_warning.connect(self._handle_disk_warning)

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
        self.history_list_widget = self._create_history_area()
        self.history_list_widget.itemClicked.connect(self._on_history_item_clicked)
        
        splitter.addWidget(self.image_feed_label)
        splitter.addWidget(self.history_list_widget)
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

        self.speed_spinbox = QSpinBox()
        self.speed_spinbox.setRange(0, 500)
        self.speed_spinbox.setValue(self.config.get("conveyor_settings.speed_mm_per_s", 50))
        controls_layout.addRow("传送带速度 (mm/s):", self._create_spinbox_control(self.speed_spinbox))

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

        self.freq_spinbox = QSpinBox()
        self.freq_spinbox.setRange(100, 10000)
        self.freq_spinbox.setValue(self.config.get("camera_settings.capture_frequency_ms", 1000))
        controls_layout.addRow("拍照频率 (ms):", self._create_spinbox_control(self.freq_spinbox))
        
        scroll_layout.addWidget(self.controls_group)

        exposure_label_row = QFrame()
        exposure_label_layout = QHBoxLayout(exposure_label_row)
        exposure_label_layout.setContentsMargins(0, 0, 0, 0)
        exposure_label_layout.addWidget(QLabel("相机曝光 (us):"))
        exposure_label_layout.addStretch()
        self.auto_exposure_cb = QCheckBox("自动")
        exposure_label_layout.addWidget(self.auto_exposure_cb)
        scroll_layout.addWidget(exposure_label_row)

        self.exposure_spinbox = QSpinBox()
        self.exposure_spinbox.setRange(100, 1000000)
        self.exposure_spinbox.setSingleStep(1000)
        exposure_control = self._create_spinbox_control(self.exposure_spinbox)
        scroll_layout.addWidget(exposure_control)

        exp_config = self.config.get("camera_settings.exposure", "auto")
        if exp_config == "auto":
            self.auto_exposure_cb.setChecked(True)
            self.exposure_spinbox.setValue(5000)
        else:
            self.auto_exposure_cb.setChecked(False)
            self.exposure_spinbox.setValue(int(exp_config))
        
        self.auto_exposure_cb.toggled.connect(exposure_control.setDisabled)
        self.auto_exposure_cb.toggled.connect(self._on_exposure_changed)
        exposure_control.setDisabled(self.auto_exposure_cb.isChecked())
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
        
        self.toggle_camera_button.clicked.connect(self._on_toggle_camera_connection)
        self.start_button.clicked.connect(self._on_start_clicked)
        self.stop_button.clicked.connect(self.controller.stop_system)

        scroll_layout.addWidget(self.toggle_camera_button)
        scroll_layout.addWidget(self.start_button)
        scroll_layout.addWidget(self.stop_button)
        
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
        list_widget = QListWidget()
        list_widget.setSpacing(5)
        return list_widget

    def _on_exposure_changed(self):
        exposure_value = "auto" if self.auto_exposure_cb.isChecked() else self.exposure_spinbox.value()
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
        self.controller.reload_model(model_name)
        # Re-enable controls and let the state machine handle button states
        self.model_combo.setEnabled(True)
        self._update_status(self.controller.status_updated.emit(STATUS_PREVIEWING)) # Refresh UI state

    def _on_threshold_changed(self, value):
        """置信度阈值变更：低于此值的结果标记为"需复检"。"""
        self.confidence_threshold = float(value)
        self.config.set("model_settings.confidence_threshold", self.confidence_threshold)
        logger.info(f"Confidence threshold set to {self.confidence_threshold}")

    def _on_start_clicked(self):
        self.config.set("conveyor_settings.speed_mm_per_s", self.speed_spinbox.value())
        self.config.set("camera_settings.capture_frequency_ms", self.freq_spinbox.value())
        self.config.set("camera_settings.exposure", "auto" if self.auto_exposure_cb.isChecked() else self.exposure_spinbox.value())
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
        self._display_record_info(
            record_data['id'],
            record_data['prediction'],
            record_data['confidence']
        )
        self._add_history_record(record_data)

    def _add_history_record(self, record_data: dict):
        """
        Inserts a single new record at the top of the history list.
        
        Memory Management:
        - Explicitly deletes old items and their widgets when trimming
        - Limits list to 50 items to prevent unbounded growth
        """
        # If an item is selected in the history, don't add new items to the list
        if self.selected_history_item:
            return

        # Convert dict to the tuple format used elsewhere
        record_tuple = (
            record_data['id'],
            record_data['timestamp'],
            record_data['image_path'],
            record_data.get('thumbnail_path'),
            record_data['prediction'],
            record_data['confidence'],
            record_data['corrected_label']
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
            confidence_threshold=self.confidence_threshold
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
        self.selected_history_item = None # Reset history view on error
        self._update_status(STATUS_IDLE) # Reset UI to safe state on error

    def _handle_disk_warning(self, message):
        """Handle disk space warning from the controller."""
        logger.warning(f"Disk space warning: {message}")
        # Show warning in the result panel with yellow/orange styling
        self.result_label.setText(f"⚠️ 磁盘警告: {message}")
        self.result_label.setStyleSheet("color: #FFA726;")  # Orange color for warning

    def _show_correction_dialog(self):
        logger.info("Correction dialog initiated.")
        self.controller.stop_system()
        
        corrected_label, ok = QInputDialog.getText(self, "纠错", f"当前识别为 '{self.last_prediction}'.\n请输入正确类别:", QLineEdit.Normal, "")
        if ok and corrected_label:
            logger.info(f"Submitting correction for record {self.last_record_id}: new label is '{corrected_label}'")
            self.controller.correct_prediction(self.last_record_id, corrected_label)
            self._update_history_item(self.last_record_id, corrected_label)
            self._display_record_info(self.last_record_id, self.last_prediction, 0, corrected_label)
        else:
            logger.info("Correction dialog cancelled.")
            # If user cancels, we should re-enable start
            self.start_button.setEnabled(True)

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
                    confidence_threshold=self.confidence_threshold
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
                r_id, _, img_path, thumb_path, pred, conf, corr_label = record_data
                logger.info(f"History item clicked: Record ID {r_id}, Path: {img_path}")
                self._display_record_info(r_id, pred, conf, corr_label)
                pixmap = QPixmap(img_path)
                if not pixmap.isNull():
                    self.image_feed_label.setPixmap(pixmap.scaled(
                        self.image_feed_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                else:
                    self.image_feed_label.setText(f"无法加载图片:\n{img_path}")

    def _load_history(self):
        self.history_list_widget.clear()
        for record in self.controller.get_recent_records():
            item = QListWidgetItem() # Create item without parent
            item.setData(Qt.UserRole, record)
            item_widget = HistoryItemWidget(
                record[2], # image_path
                record[3], # thumbnail_path
                record[1], # timestamp
                record[4], # prediction
                record[5], # confidence
                record[6] if record[6] else "None", # corrected_label
                confidence_threshold=self.confidence_threshold
            )
            item.setSizeHint(item_widget.sizeHint())
            self.history_list_widget.addItem(item)
            self.history_list_widget.setItemWidget(item, item_widget)

    def closeEvent(self, event):
        """窗口关闭时清理：停止 worker、断开相机、关闭数据库（WAL checkpoint）。"""
        logger.info("Application closing, shutting down controller...")
        try:
            self.controller.shutdown()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        event.accept()

