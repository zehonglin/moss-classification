"""MainWindow v2 — 双模式组装（操作员/工程师）+ 信号接线 + 气泡纠错 + toast。

布局（§5 设计文档）：
    顶部统计栏 TopStatBar（双模式一致，订阅 grade_summary_updated）
    操作员模式：品级横幅 + 取景器/历史列表 + 底部操作按钮栏
    工程师模式：左侧参数栏 + 主区（品级横幅 + 取景器/历史列表）

关键交互：
    - result_updated → history.append_live + banner.set_state（选中历史时不抢横幅）
    - 选中历史 → camera.set_history + banner 切"正在查看历史"+ top_bar 状态切"历史图像"
    - 点横幅 ✎ → CorrectionPopup → 点目标品级 → controller.correct_prediction + banner 立即反映
    - 模式切换：默认直接切；工程师模式可选密码（config ui.engineer_mode_password）
    - toast：disk_space_warning / error_occurred / camera_info → ToastStack.show
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.controllers.system_controller import (
    STATUS_IDLE,
    STATUS_PREVIEWING,
    STATUS_RUNNING,
    SystemController,
)
from app.ui.components.camera_view import CameraView
from app.ui.components.correction_popup import CorrectionPopup
from app.ui.components.grade_banner import GradeBanner, banner_state
from app.ui.components.history_list import HistoryList
from app.ui.components.mode_switch import maybe_prompt_password
from app.ui.components.param_sidebar import ParamSidebar
from app.ui.components.toast import ToastStack, severity_for
from app.ui.components.top_bar import TopStatBar
from app.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """苔藓识别主窗口 v2（双模式）。"""

    def __init__(self, config_manager: ConfigManager, controller=None):
        super().__init__()
        self.setWindowTitle("苔藓识别系统")
        self.resize(1600, 900)

        self.config = config_manager
        self.controller = (
            controller if controller is not None else SystemController(self.config)
        )
        self.threshold = self.config.get("model_settings.confidence_threshold", 0.6)
        self._mode = "operator"
        self._selected = None
        self._page = 1
        self._filter = None
        self._last_rec = None
        self._status = STATUS_IDLE
        self._popup = None

        # ---- 构造组件 ----
        self.top_bar = TopStatBar()
        self.top_bar.mode_change_requested.connect(self._switch_mode)

        self.banner = GradeBanner(self.threshold)
        self.banner.correction_requested.connect(self._on_correction_requested)

        self.camera = CameraView()
        self.camera.back_to_live.connect(self._exit_history)
        self.camera.request_fullscreen.connect(self._toggle_fullscreen)

        self.history = HistoryList(self.threshold)
        self.history.record_selected.connect(self._on_history_selected)
        self.history.page_change_requested.connect(self._on_page_change)
        self.history.filter_requested.connect(self._on_filter)
        self.history.export_requested.connect(self._on_export)

        self.sidebar = ParamSidebar()
        self._wire_sidebar()
        self._populate_sidebar_defaults()

        self.toasts = ToastStack()

        # ---- 组装布局 ----
        central = QWidget()
        self.setCentralWidget(central)
        self._root = QVBoxLayout(central)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self.top_bar)

        self._body = QWidget()
        self._body_l = QVBoxLayout(self._body)
        self._body_l.setContentsMargins(0, 0, 0, 0)
        self._body_l.setSpacing(0)
        self._root.addWidget(self._body, 1)

        self._apply_mode_layout()

        # ---- 接线 controller ----
        self._connect_controller()

        # 首页加载
        self._on_page_change(1)

        # toast 浮动栈挂到主窗右上角（attach_to 内部 show）
        self.toasts.attach_to(self)

        # ESC：退出历史 / 关闭气泡
        QShortcut(QKeySequence("Esc"), self, activated=self._on_esc)

        logger.info("MainWindow v2 ready.")

    # ================================================================
    # 布局：双模式组装
    # ================================================================

    def _banner_wrap(self):
        """横幅外层留白容器：圆角卡片与窗口边缘留出呼吸感（对齐 mockup .banner-wrap）。

        该容器是"中间容器"——模式切换时随 _apply_mode_layout 释放；
        banner 本体在清空前已 setParent(None) 脱钩，不受影响。
        """
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(16, 12, 16, 0)
        lay.setSpacing(0)
        lay.addWidget(self.banner)
        return wrap

    def _apply_mode_layout(self):
        """按当前 _mode 重排 body 区。共享组件不销毁，中间容器释放。

        关键：先把 4 个共享组件 reparent 到 None（脱离旧中间容器），再清空 layout。
        否则中间容器被 Python GC 回收时会连带删除仍挂在其 C++ 树下的共享组件。
        """
        # 1. 共享组件脱钩（C++ 父子关系解除，Python 实例引用保留 → 不会被删）
        for w in (self.banner, self.camera, self.history, self.sidebar):
            w.setParent(None)

        # 2. 清空 body layout + 释放中间容器
        while self._body_l.count():
            it = self._body_l.takeAt(0)
            child = it.widget()
            if child is not None:
                child.deleteLater()

        if self._mode == "operator":
            # 横幅（圆角卡片 + 外层留白）
            self._body_l.addWidget(self._banner_wrap())

            # 中间区：取景器(3) + 历史(2)。
            # 边距与横幅卡片左右对齐（16px 侧距），卡片间 16px 间隔（对齐 mockup .mid）
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(16, 12, 16, 12)
            rh.setSpacing(16)
            rh.addWidget(self.camera, 3)
            rh.addWidget(self.history, 2)
            self._body_l.addWidget(row, 1)

            # 底栏操作按钮（主次分级 + 防误触布局）：
            #   [连接相机][连接状态] …… [拍照] │ [停止运行] [开始运行]
            # 开始/停止之间用竖分隔线拉开物理距离；开始为主操作（QSS 放大实心绿）。
            bot = QWidget()
            bh = QHBoxLayout(bot)
            bh.setContentsMargins(12, 8, 12, 8)
            bh.setSpacing(8)
            self._bot_btns = {}

            b_conn = QPushButton("连接相机")
            b_conn.setObjectName("ActionConnect")
            b_conn.clicked.connect(self._do_connect)
            bh.addWidget(b_conn)
            self._bot_btns["connect"] = b_conn

            self._conn_state = QLabel("")
            self._conn_state.setStyleSheet("color:#94a3b8;font-size:11px;")
            bh.addWidget(self._conn_state)

            bh.addStretch()

            b_cap = QPushButton("拍照")
            b_cap.setObjectName("ActionCapture")
            b_cap.clicked.connect(self._do_capture)
            bh.addWidget(b_cap)
            self._bot_btns["capture"] = b_cap

            sep = QFrame()
            sep.setObjectName("BotSep")
            sep.setFrameShape(QFrame.VLine)
            bh.addWidget(sep)

            b_stop = QPushButton("■ 停止运行")
            b_stop.setObjectName("ActionStop")
            b_stop.clicked.connect(self._do_stop)
            bh.addWidget(b_stop)
            self._bot_btns["stop"] = b_stop

            b_start = QPushButton("▶ 开始运行")
            b_start.setObjectName("ActionStart")
            b_start.clicked.connect(self._do_start)
            bh.addWidget(b_start)
            self._bot_btns["start"] = b_start

            self._body_l.addWidget(bot)
            self._apply_button_state()
            self._update_conn_state()
        else:
            # 工程师模式：左侧参数栏 + 右侧主区
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(0)
            rh.addWidget(self.sidebar)

            main = QWidget()
            ml = QVBoxLayout(main)
            ml.setContentsMargins(0, 0, 0, 0)
            ml.setSpacing(0)
            ml.addWidget(self._banner_wrap())
            sub = QWidget()
            sh = QHBoxLayout(sub)
            sh.setContentsMargins(16, 12, 16, 12)  # 与横幅/操作员模式同口径对齐
            sh.setSpacing(16)
            sh.addWidget(self.camera, 3)
            sh.addWidget(self.history, 2)
            ml.addWidget(sub, 1)
            rh.addWidget(main, 1)
            self._body_l.addWidget(row, 1)

        self.banner.set_reviewing(self._selected is not None)

    # ================================================================
    # 参数栏信号接线
    # ================================================================

    def _wire_sidebar(self):
        s = self.sidebar
        s.trigger_changed.connect(self._on_trigger_changed)
        s.debouncer_changed.connect(
            lambda v: self.config.set(
                "camera_settings.trigger.debouncer_time_us", v
            )
        )
        s.resolution_apply.connect(
            lambda w, h: self.controller.set_camera_resolution(w, h)
        )
        s.exposure_changed.connect(self._on_exposure_changed)
        s.interval_changed.connect(
            lambda v: self.config.set(
                "camera_settings.trigger.software_interval_ms", v
            )
        )
        s.model_changed.connect(self._on_model_changed)
        s.threshold_changed.connect(self._on_threshold_changed)
        # 质量检查三阈值：controller 每帧实时读 quality_check.* → config.set 即热生效
        s.quality_threshold_changed.connect(
            lambda key, v: self.config.set(f"quality_check.{key}", v)
        )
        s.connect_clicked.connect(self._do_connect)
        s.start_clicked.connect(self._do_start)
        s.stop_clicked.connect(self.controller.stop_system)
        s.capture_clicked.connect(self.controller.capture_single)

    def _on_trigger_changed(self, mode):
        self.config.set("camera_settings.trigger.mode", mode)
        self.controller.set_trigger_mode(mode)

    def _on_exposure_changed(self, value):
        self.config.set("camera_settings.exposure", value)
        self.controller.set_camera_exposure(value)

    def _populate_sidebar_defaults(self):
        """从 config/controller 填充 ParamSidebar 的初始值（模型列表 / 阈值 / 触发模式）。

        ParamSidebar 构造时不接 controller，这些值由 MainWindow 注入。
        通过公共方法 set_models / set_threshold 填充，不直访私有成员。
        """
        # 模型列表
        models = self.controller.get_available_models() or []
        if models:
            self.sidebar.set_models(models)
        current_model = self.config.get("model_settings.current_model_name")
        self.sidebar.set_current_model(current_model)
        # 置信度阈值
        self.sidebar.set_threshold(self.threshold)
        # 质量检查三阈值（默认值与 config_manager 口径一致）
        self.sidebar.set_quality_thresholds(
            self.config.get("quality_check.blur_threshold", 50.0),
            int(self.config.get("quality_check.overexposure_threshold", 235)),
            int(self.config.get("quality_check.underexposure_threshold", 25)),
        )
        # 触发模式（联动软件间隔行可见性）
        cur_mode = self.config.get("camera_settings.trigger.mode", "preview")
        self.sidebar.set_trigger_mode(cur_mode)

    # ================================================================
    # controller 信号接线
    # ================================================================

    def _connect_controller(self):
        c = self.controller
        c.image_updated.connect(self.camera.set_live)
        c.result_updated.connect(self._on_result)
        c.status_updated.connect(self._on_status)
        c.error_occurred.connect(self._on_error)
        c.disk_space_warning.connect(self._on_warn)
        c.camera_info.connect(self._on_cam_info)
        c.grade_summary_updated.connect(self.top_bar.set_grade_summary)
        c.stats_updated.connect(self._on_stats)
        c.model_loaded.connect(self._on_model_loaded)

    # ================================================================
    # 信号处理
    # ================================================================

    def _on_result(self, rec):
        """新识别结果：调试捕获直接显横幅；正常结果进历史 + 刷新横幅。"""
        if rec.get("id") is None:
            self.banner.set_state(banner_state(rec, self.threshold))
            return
        self.history.append_live(rec)
        if self._selected is not None:
            return  # 选中历史时不抢横幅
        self.banner.set_state(banner_state(rec, self.threshold))
        self._last_rec = rec

    def _on_status(self, status):
        """controller 状态 → top_bar 运行状态文案 + 按钮禁用状态机。

        reviewing 时即使 status=RUNNING 也显示"历史图像"（不抢回 live）。
        """
        self._status = status
        if status == STATUS_IDLE:
            self.top_bar.set_run_state("idle")
        elif status in (STATUS_PREVIEWING, STATUS_RUNNING):
            self.top_bar.set_run_state(
                "history" if self.camera.is_reviewing() else "live"
            )
        self._apply_button_state()

    def _apply_button_state(self):
        """按钮禁用状态机（I5）：运行中 → 开始禁用/停止可用；已停止 → 反之。

        操作员底栏按钮在 `_apply_mode_layout` 重建，故用 getattr 容错；
        工程师参数栏按钮常驻，由 sidebar.set_buttons_running 同步。
        """
        running = self._status in (STATUS_PREVIEWING, STATUS_RUNNING)
        btns = getattr(self, "_bot_btns", None) or {}
        if "start" in btns:
            btns["start"].setEnabled(not running)
        if "stop" in btns:
            btns["stop"].setEnabled(running)
        if hasattr(self, "sidebar"):
            self.sidebar.set_buttons_running(running)

    def _update_conn_state(self):
        """底栏连接相机按钮旁的连接状态小字（相机已连接/未连接）。"""
        lab = getattr(self, "_conn_state", None)
        if lab is None:
            return
        try:
            connected = self.controller.camera.is_connected()
        except Exception:
            connected = False
        lab.setText("相机已连接" if connected else "相机未连接")

    def _on_warn(self, msg):
        self.toasts.show(msg, severity=severity_for(msg))

    def _on_error(self, msg):
        self.toasts.show(msg, severity="danger")

    def _on_cam_info(self, msg):
        self.toasts.show(msg, severity="warn")

    def _on_stats(self, stats):
        """吞吐统计路由：磁盘显示（I1）。"""
        free_gb = stats.get("free_gb", 0)
        self.top_bar.set_disk(f"{free_gb:.0f}GB 可用")

    def _on_model_loaded(self, ok, model_name):
        """模型后台加载完成（C2）：失败时 toast + combo 恢复到当前实际模型。"""
        if ok:
            logger.info(f"模型已加载: {model_name}")
            return
        self.toasts.show(f"模型加载失败: {model_name}", severity="danger")
        # combo 恢复到 config 里当前实际加载的模型，避免显示一个未加载的模型名
        current = self.config.get("model_settings.current_model_name") or ""
        self.sidebar.set_current_model(current)

    # ---- 历史选中 ----

    def _on_history_selected(self, rec):
        if rec is None:
            self._selected = None
            self.camera.clear_history()
            self.banner.set_reviewing(False)
            self.top_bar.set_run_state(
                "live"
                if self._status in (STATUS_PREVIEWING, STATUS_RUNNING)
                else "idle"
            )
            self._refresh_list()
            return
        self._selected = rec
        self.camera.set_history(rec.get("image_path"), rec.get("timestamp"))
        self.banner.set_state(banner_state(rec, self.threshold))
        self.banner.set_reviewing(True)
        self.top_bar.set_run_state("history")

    def _exit_history(self):
        self.history.clear_selection()  # → 触发 _on_history_selected(None)

    # ---- 分页 / 筛选 / 导出 ----

    def _on_page_change(self, page):
        self._page = max(page, 1)
        filt = self._filter or {}
        rows, total = self.controller.search_records_paged(
            prediction=filt.get("prediction"),
            quality_status=filt.get("quality_status"),
            page=self._page,
            page_size=50,
        )
        self.history.set_page(rows, total, self._page, 50)

    def _refresh_list(self):
        self._on_page_change(self._page)

    def _on_filter(self, f):
        self._filter = f
        self._page = 1
        rows, total = self.controller.search_records_paged(
            prediction=f.get("prediction"),
            quality_status=f.get("quality_status"),
            page=1,
            page_size=50,
        )
        self.history.set_page(rows, total, 1, 50)

    def _on_export(self):
        """导出当前筛选结果：CSV + 可选原图。"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "导出记录", "moss_records.csv", "CSV (*.csv)"
        )
        if not path:
            return

        filt = self._filter or {}
        rows, _ = self.controller.search_records_paged(
            prediction=filt.get("prediction"),
            quality_status=filt.get("quality_status"),
            page=1,
            page_size=10 ** 9,
        )
        with_images = (
            QMessageBox.question(
                self, "导出原图", "是否同时导出原图（按品级分文件夹）？"
            )
            == QMessageBox.StandardButton.Yes
        )
        if with_images:
            import os

            root = os.path.join(
                os.path.dirname(path),
                os.path.splitext(os.path.basename(path))[0] + "_images",
            )
            self.controller.export_with_images(path, root, rows)
        else:
            self.controller.export_history_csv(path, rows)
        QMessageBox.information(self, "完成", f"已导出 {len(rows)} 条")

    # ---- 纠错 ----

    def _on_correction_requested(self):
        """横幅 ✎ → 气泡 A/B/C/D → 点选 → correct_prediction + banner 立即反映。"""
        rec = self._selected or self._last_rec
        if not rec or not rec.get("id"):
            return
        self._popup = CorrectionPopup()
        self._popup.grade_selected.connect(
            lambda label: self._apply_correction(rec, label)
        )
        self._popup.popup_for(rec, self.banner.edit_button())

    def _apply_correction(self, rec, label):
        """提交纠错到 controller + 更新本地 record + 刷新横幅 + 刷新列表。"""
        self.controller.correct_prediction(rec["id"], label)
        rec.update(corrected_label=label)
        self.banner.set_state(banner_state(rec, self.threshold))
        self._refresh_list()

    # ---- 模型 / 阈值 ----

    def _on_model_changed(self, name):
        self.controller.reload_model(name)

    def _on_threshold_changed(self, v):
        self.threshold = float(v)
        self.config.set("model_settings.confidence_threshold", v)

    # ================================================================
    # 模式切换
    # ================================================================

    def _switch_mode(self, target):
        if target == "engineer":
            pwd = self.config.get("ui.engineer_mode_password")
            if not maybe_prompt_password(self, pwd):
                return
        self._mode = target
        self.top_bar.set_mode(target)
        self._apply_mode_layout()

    # ================================================================
    # 操作按钮（操作员底栏 / 工程师参数栏共用）
    # ================================================================

    def _do_connect(self):
        if self.controller.camera.is_connected():
            self.controller.disconnect_camera()
        else:
            self.controller.connect_camera()
        self._update_conn_state()

    def _do_start(self):
        self.controller.start_system()

    def _do_stop(self):
        self.controller.stop_system()

    def _do_capture(self):
        self.controller.capture_single()

    # ================================================================
    # 键盘 / 全屏
    # ================================================================

    def _on_esc(self):
        if self.camera.is_reviewing():
            self._exit_history()
        elif self._popup is not None:
            self._popup.close()

    def _toggle_fullscreen(self):
        """全屏查看原图 — 暂禁用（no-op）。

        旧实现把 _view 设为 Qt.Window 顶层全屏，但无恢复路径，会令 _view 永久脱离
        CameraView 布局。MVP 阶段隐藏：双击仍触发本方法但不做任何事，待正确实现
        toggle + 恢复 window flags/reparent 后再启用。
        """
        return

    # ================================================================
    # 窗口尺寸
    # ================================================================

    def resizeEvent(self, event):
        """窗口缩放 → toast 栈跟随重定位右上角。"""
        super().resizeEvent(event)
        self.toasts.reposition()

    # ================================================================
    # 清理
    # ================================================================

    def closeEvent(self, event):
        try:
            self.controller.shutdown()
        except Exception as ex:
            logger.error(f"shutdown: {ex}")
        event.accept()
