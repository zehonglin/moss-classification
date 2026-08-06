import logging
import threading
from PySide6.QtCore import QObject, Signal, QThread, QTimer
from PySide6.QtGui import QImage
from app.core.interfaces import BaseCamera
from app.services.model_service import ModelService
from app.services.database_service import DatabaseService
from app.utils.config_manager import ConfigManager
from app.utils.disk_monitor import DiskSpaceMonitor
import time
import os
import json
import shutil
import re
import numpy as np
from PIL import Image
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Simplified Statuses for State Machine
STATUS_IDLE = "IDLE"  # Disconnected
STATUS_PREVIEWING = "PREVIEWING" # Camera connected, live view
STATUS_RUNNING = "RUNNING" # Full processing loop


def export_records_csv(filepath: str, rows) -> int:
    """导出记录为 CSV（UTF-8 BOM，Excel 可直接打开）。返回导出条数。"""
    import csv

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "timestamp", "image_path", "thumbnail_path",
            "prediction", "confidence", "corrected_label", "quality_status",
        ])
        for row in rows:
            writer.writerow(list(row))
    return len(rows)


def create_camera(driver_type: str, serial_number: str = None):
    """按配置创建相机驱动实例。

    驱动类型必须显式配置：hikvision 加载失败直接抛 ImportError（启动失败，
    绝不静默回退 Mock）；只有显式 "mock" 才允许使用模拟相机。
    """
    if driver_type == "hikvision":
        from app.drivers.hikvision_driver import HikvisionCamera
        return HikvisionCamera(serial_number=serial_number)
    if driver_type == "mock":
        from app.drivers.mock_driver import MockCamera
        return MockCamera()
    raise ValueError(f"未知的相机驱动类型: {driver_type!r}（可选: hikvision / mock）")


def _qimage_to_pil(q_image):
    """QImage → PIL.Image(RGB)。直接读取像素缓冲，不依赖 Qt imageformats 插件
    （本机 PySide6 缺 JPEG 插件，QImage.save / QImageReader 对 JPEG 均不可用）。"""
    q = q_image.convertToFormat(QImage.Format.Format_RGB888)
    w, h = q.width(), q.height()
    bpl = q.bytesPerLine()
    buf = np.array(q.bits(), dtype=np.uint8, copy=True)
    # 按 bytesPerLine 切片去除行尾对齐 padding，避免宽度非 4 倍数时 reshape 错位
    arr = buf[: h * bpl].reshape(h, bpl)[:, : w * 3].reshape(h, w, 3)
    return Image.fromarray(arr, "RGB")


class SystemWorker(QObject):
    """
    Worker class for the main processing loop.
    
    Thread Safety:
    - Uses threading.Event for safe cross-thread stop signaling
    - Event.is_set() and Event.set() are atomic operations
    - No locks needed for the stop mechanism
    """
    image_ready = Signal(QImage)
    result_ready = Signal(dict) # record_data dictionary
    error_occurred = Signal(str)
    disk_space_warning = Signal(str)  # Emitted when disk space is low
    finished = Signal()

    def __init__(self, camera: BaseCamera, model_service: ModelService, db_service: DatabaseService, config: ConfigManager, camera_lock=None):
        super().__init__()
        self.camera = camera
        self.model_service = model_service
        self.db_service = db_service
        self.config = config
        
        # 串行化相机访问：预览（主线程）与推理（worker 线程）共用同一相机，
        # 必须加锁，避免 SDK 并发调用导致缓冲区错乱或崩溃
        self._camera_lock = camera_lock if camera_lock is not None else threading.Lock()

        # 节拍/吞吐统计
        self.stats = {
            "processed": 0,
            "timeouts": 0,
            "processing_timeout_count": 0,
            "quality_rejects": 0,
            "total_processing_ms": 0.0,
            "start_time": time.time(),
        }
        self._consecutive_quality_rejects = 0
        self._processing_timeout_ms = self.config.get("performance.processing_timeout_ms", 3000)
        self._last_perf_alert = 0.0

        # Thread-safe stop event (replaces _is_running boolean)
        # Event is thread-safe: set(), clear(), is_set() are atomic
        self._stop_event = threading.Event()
        
        # Lock for protecting shared state during initialization/cleanup
        self._state_lock = threading.Lock()
        
        # Disk space monitor for preventing disk exhaustion
        self._disk_monitor = DiskSpaceMonitor(
            warning_threshold_gb=self.config.get("storage.disk_watermark_gb", 50.0),
            critical_threshold_gb=self.config.get("storage.critical_free_gb", 5.0),
        )

    def start_loop(self):
        """
        Main processing loop - runs in worker thread.
        
        Error Handling Strategy:
        - Single frame failures are logged and skipped (recoverable)
        - Consecutive failures above threshold trigger a stop (may indicate hardware issue)
        - Critical errors (disk full, camera disconnect) stop immediately
        """
        with self._state_lock:
            self._stop_event.clear()  # Reset stop signal

        # 触发参数（worker 仅在 hardware / software_continuous 模式启动）
        mode = self.config.get("camera_settings.trigger.mode", "hardware")
        grab_timeout = self.config.get("camera_settings.trigger.grab_timeout_ms", 2000)
        sw_interval = self.config.get("camera_settings.trigger.software_interval_ms", 1000)
        logger.info(f"Processing loop started (trigger={mode}).")

        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10
        consecutive_none = 0
        MAX_CONSECUTIVE_NONE = 15  # 连续 None 阈值（~grab_timeout×15，默认约 30s 无图判相机异常）
        
        while not self._stop_event.is_set():
            try:
                loop_start_time = time.time()
                
                # Check stop event before each major operation for responsive stopping
                if self._stop_event.is_set():
                    break
                
                # 1. software_continuous：主动发一次软件触发（hardware 由光电触发，无需）
                if mode == "software_continuous" and not self._stop_event.is_set():
                    self.camera.enable_software_trigger()
                if self._stop_event.is_set():
                    break
                # 2. 取图（触发模式阻塞等触发图；grab_timeout 内可检查 stop）
                capture_start_time = time.time()
                with self._camera_lock:
                    image = self.camera.get_frame(timeout_ms=grab_timeout)
                capture_duration = (time.time() - capture_start_time) * 1000

                # 取图为 None（超时/无触发/相机问题）：连续 None 计数，超阈值只告警不停。
                # is_connected() 仅逻辑标志不反映物理掉线（USB 拔了仍 True），无法区分原因；
                # 由操作员看告警检查现场，托盘/相机恢复后 worker 自动继续处理。
                if not image and not self._stop_event.is_set():
                    consecutive_none += 1
                    self.stats["timeouts"] += 1
                    if consecutive_none >= MAX_CONSECUTIVE_NONE:
                        self.disk_space_warning.emit(
                            f"相机连续 {MAX_CONSECUTIVE_NONE * grab_timeout / 1000:.0f}s 无图像，请检查相机/光电/产线")
                        consecutive_none = 0  # 重置避免刷屏；继续等触发
                elif image:
                    consecutive_none = 0
                
                if image and not self._stop_event.is_set():
                    self.image_ready.emit(image)

                    # 提前转换像素（质量检查与保存复用）
                    pil_img = _qimage_to_pil(image)

                    # 2. 图像质量检查：拒采帧仍保存原图+缩略图并入库，但不出品级
                    quality_status = "ok"
                    quality_reason = None
                    if self.config.get("quality_check.enabled", True):
                        from app.services.quality_service import analyze_image
                        quality_status, quality_reason = analyze_image(
                            pil_img,
                            blur_threshold=self.config.get("quality_check.blur_threshold", 50.0),
                            overexposure_threshold=self.config.get("quality_check.overexposure_threshold", 235.0),
                            underexposure_threshold=self.config.get("quality_check.underexposure_threshold", 25.0),
                        )
                        if quality_status != "ok":
                            self._consecutive_quality_rejects += 1
                            self.stats["quality_rejects"] = self.stats.get("quality_rejects", 0) + 1
                            reject_alert = self.config.get("quality_check.consecutive_reject_alert", 5)
                            if self._consecutive_quality_rejects >= reject_alert:
                                self.disk_space_warning.emit(
                                    f"连续 {self._consecutive_quality_rejects} 帧质量不合格（{quality_reason}），"
                                    f"请检查补光/镜头/焦距"
                                )
                                self._consecutive_quality_rejects = 0
                        else:
                            self._consecutive_quality_rejects = 0

                    # 3. Predict（拒采帧跳过推理）
                    if quality_status == "ok" and not self._stop_event.is_set():
                        predict_start_time = time.time()
                        prediction, confidence = self.model_service.predict(image)
                        predict_duration = (time.time() - predict_start_time) * 1000
                    else:
                        prediction, confidence = None, None
                        predict_duration = 0.0

                    if self._stop_event.is_set():
                        break

                    # 模型未加载：立即停止，不落库、不存图（防止产出"模型未加载"假记录）
                    if prediction == "模型未加载" and not self._stop_event.is_set():
                        self.error_occurred.emit(
                            "模型未加载，采集已停止。请选择可用模型后重新启动。"
                        )
                        self._stop_event.set()
                        break
                    
                    # 3. Check disk space before saving image
                    save_dir = self.config.get("data_paths.collected_data_directory", "data/images/")
                    disk_status, free_gb, disk_message = self._disk_monitor.check_space(save_dir)
                    
                    if disk_status == "critical":
                        # Critical: stop the processing loop
                        self.disk_space_warning.emit(disk_message)
                        self.error_occurred.emit(f"磁盘空间严重不足: 仅剩 {free_gb:.2f}GB，已停止采集")
                        self._stop_event.set()
                        break
                    elif disk_status == "warning":
                        # Warning: emit signal but continue
                        self.disk_space_warning.emit(disk_message)
                    
                    # 4. Save Image to Disk (原图 + 缩略图，均用 PIL，不依赖 Qt imageformats 插件)
                    save_img_start_time = time.time()
                    now = datetime.now()
                    timestamp_iso = now.isoformat()
                    timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")
                    img_format = self.config.get("storage.image_format", "png").lower()
                    os.makedirs(save_dir, exist_ok=True)
                    # 原图（训练 / 大图查看）
                    image_path = os.path.join(save_dir, f"moss_{timestamp_str}.{img_format}")
                    if img_format == "png":
                        pil_img.save(image_path, "PNG")
                    else:
                        pil_img.save(image_path, "JPEG", quality=self.config.get("storage.image_quality", 95))
                    # 缩略图（界面展示用；用 PNG，因本机 Qt 无 JPEG 解码插件，QImageReader 读不了 JPEG）
                    thumb_dir = os.path.join(save_dir, "thumb")
                    os.makedirs(thumb_dir, exist_ok=True)
                    thumb_path = os.path.join(thumb_dir, f"moss_{timestamp_str}.png")
                    thumb_size = self.config.get("storage.thumbnail_max_size", 300)
                    thumb = pil_img.copy()
                    thumb.thumbnail((thumb_size, thumb_size))
                    thumb.save(thumb_path, "PNG")
                    save_img_duration = (time.time() - save_img_start_time) * 1000
                    
                    if self._stop_event.is_set():
                        break
                    
                    # 5. Save to DB
                    save_db_start_time = time.time()
                    record_id = self.db_service.add_record(
                        timestamp_iso, image_path, prediction, confidence,
                        thumbnail_path=thumb_path,
                        quality_status=quality_status,
                        rejected_reason=quality_reason,
                    )
                    
                    record_data = {
                        "id": record_id,
                        "timestamp": timestamp_iso,
                        "image_path": image_path,
                        "thumbnail_path": thumb_path,
                        "prediction": prediction,
                        "confidence": confidence,
                        "corrected_label": None,
                        "quality_status": quality_status,
                        "rejected_reason": quality_reason,
                    }
                    self.result_ready.emit(record_data)
                    save_db_duration = (time.time() - save_db_start_time) * 1000
                    
                    # Successful frame - reset error counter
                    consecutive_errors = 0

                    # 节拍：software_continuous 按 sw_interval；hardware 无 sleep（由光电触发决定）
                    total_processing_time = (time.time() - loop_start_time) * 1000
                    if image:
                        self.stats["processed"] += 1
                        self.stats["total_processing_ms"] += total_processing_time
                        if total_processing_time > self._processing_timeout_ms:
                            self.stats["processing_timeout_count"] += 1
                            now = time.time()
                            if now - self._last_perf_alert > 60:
                                self._last_perf_alert = now
                                self.disk_space_warning.emit(
                                    f"单帧处理耗时 {total_processing_time:.0f}ms 超过阈值 "
                                    f"{self._processing_timeout_ms}ms，请检查推理/存储性能"
                                )
                        logger.debug(
                        f"Loop Profile: Capture={capture_duration:.2f}ms, Predict={predict_duration:.2f}ms, "
                        f"SaveImg={save_img_duration:.2f}ms, SaveDB={save_db_duration:.2f}ms | "
                        f"Total={total_processing_time:.2f}ms (trigger={mode})"
                    )
                if mode == "software_continuous":
                    sleep_time_ms = sw_interval - total_processing_time
                    if sleep_time_ms > 0 and not self._stop_event.is_set():
                        self._stop_event.wait(timeout=sleep_time_ms / 1000.0)
                # hardware 模式：无 sleep，立即回到循环顶 get_frame 阻塞等下一次光电触发
            
            except (OSError, IOError) as e:
                # File system errors - potentially recoverable
                consecutive_errors += 1
                logger.warning(f"File I/O error (attempt {consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}")
                
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(f"Too many consecutive I/O errors ({consecutive_errors}). Stopping.")
                    self.error_occurred.emit(f"连续文件错误过多: {e}")
                    self._stop_event.set()
                else:
                    # Skip this frame and continue
                    continue
                    
            except (ConnectionError, TimeoutError) as e:
                # Network/connection errors - potentially recoverable
                consecutive_errors += 1
                logger.warning(f"Connection error (attempt {consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}")
                
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(f"Too many consecutive connection errors ({consecutive_errors}). Stopping.")
                    self.error_occurred.emit(f"连续连接错误过多: {e}")
                    self._stop_event.set()
                else:
                    continue
                    
            except MemoryError as e:
                # Memory errors - stop immediately
                logger.critical(f"Memory error - stopping immediately: {e}")
                self.error_occurred.emit(f"内存不足: {e}")
                self._stop_event.set()
                
            except KeyboardInterrupt:
                # User interrupt - stop gracefully
                logger.info("Keyboard interrupt received, stopping...")
                self._stop_event.set()
                
            except Exception as e:
                # Unknown errors - try to continue but track failures
                consecutive_errors += 1
                logger.exception(f"Unexpected error (attempt {consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}):")
                
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(f"Too many consecutive errors ({consecutive_errors}). Stopping.")
                    self.error_occurred.emit(f"连续错误过多，系统已停止: {e}")
                    self._stop_event.set()
                else:
                    # Log warning but continue processing
                    logger.warning(f"Skipping frame due to error, will retry next cycle")
                    continue
        
        self.finished.emit()
        logger.info("Processing loop finished.")

    def get_stats(self) -> dict:
        """返回吞吐统计（每小时托盘数、平均处理耗时、超时次数等）。"""
        elapsed_h = max((time.time() - self.stats["start_time"]) / 3600.0, 1e-6)
        return {
            "processed": self.stats["processed"],
            "timeouts": self.stats["timeouts"],
            "processing_timeout_count": self.stats["processing_timeout_count"],
            "quality_rejects": self.stats["quality_rejects"],
            "per_hour": self.stats["processed"] / elapsed_h,
            "avg_ms": self.stats["total_processing_ms"] / max(self.stats["processed"], 1),
        }

    def stop_loop(self):
        """
        Signal the processing loop to stop.
        Thread-safe: can be called from any thread.
        """
        logger.info("Stop signal sent to processing loop.")
        self._stop_event.set()

    def is_running(self) -> bool:
        """Thread-safe check if the loop is running."""
        return not self._stop_event.is_set()


class ModelLoadWorker(QThread):
    """后台加载模型，避免阻塞 UI（切大模型时界面不冻结）。"""
    finished_load = Signal(bool, str, int)  # success, model_name, seq（用于丢弃过期结果）

    def __init__(self, model_service, model_name, seq):
        super().__init__()
        self.model_service = model_service
        self.model_name = model_name
        self.seq = seq

    def run(self):
        ok = self.model_service.load_model(self.model_name)
        self.finished_load.emit(ok, self.model_name, self.seq)


class SystemController(QObject):
    """Main controller for the application."""
    image_updated = Signal(QImage)
    result_updated = Signal(dict)
    status_updated = Signal(str)
    error_occurred = Signal(str)
    disk_space_warning = Signal(str)  # Forwarded from worker
    model_loaded = Signal(bool, str)  # 模型后台加载完成（成功否, 模型名）
    camera_info = Signal(str)  # 相机连接信息（序列号/型号），供 UI 显示
    stats_updated = Signal(dict)  # 吞吐/超时统计，定时推给 UI

    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config = config_manager
        
        # Services
        self.db_service = DatabaseService(self.config)
        self._disk_monitor = DiskSpaceMonitor(
            warning_threshold_gb=self.config.get("storage.disk_watermark_gb", 50.0),
            critical_threshold_gb=self.config.get("storage.critical_free_gb", 5.0),
        )
        
        # 直接加载配置指定的本地模型，不再预先下载 EfficientNet（离线环境友好）
        models_dir = self.config.get("model_settings.models_directory", "models/")
        desired_model = self.config.get("model_settings.current_model_name")
        self.model_service = ModelService(model_name=desired_model, models_dir=models_dir)

        
        # Hardware
        self._initialize_hardware()
        self._model_switch_seq = 0
        self._model_loaders = []
        
        # Preview Timer
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(50) # ~20 FPS
        self.preview_timer.timeout.connect(self._preview_frame)
        
        # Worker Thread
        self._camera_lock = threading.Lock()  # 串行化预览与推理对相机的访问
        self.worker_thread = QThread()
        self.worker = SystemWorker(self.camera, self.model_service, self.db_service, self.config, self._camera_lock)
        self.worker.moveToThread(self.worker_thread)
        
        # Connections
        self.worker.image_ready.connect(self.image_updated)
        self.worker.result_ready.connect(self.result_updated)
        self.worker.error_occurred.connect(self._handle_worker_error)  # 可恢复错误：不复位整线
        self.worker.disk_space_warning.connect(self.disk_space_warning)  # Forward disk warnings
        self.worker_thread.started.connect(self.worker.start_loop)
        self.worker.finished.connect(self.worker_thread.quit)

        # 滚动归档：启动时清理一次过期数据 + 按 storage.cleanup_interval_hours 定时清理
        self.cleanup_timer = QTimer(self)
        cleanup_interval_hours = self.config.get("storage.cleanup_interval_hours", 1)
        self.cleanup_timer.setInterval(int(cleanup_interval_hours * 60 * 60 * 1000))
        self.cleanup_timer.timeout.connect(self._scheduled_cleanup)
        self.cleanup_timer.start()
        self.cleanup_old_records(delete=False)  # 启动只报告，不自动删（防误删旧样本）

        # 相机断线自动重连（每 10s 检查一次；成功恢复触发配置与预览）
        self._reconnect_attempts = 0
        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setInterval(10 * 1000)
        self.reconnect_timer.timeout.connect(self._try_reconnect)
        self.reconnect_timer.start()

        # 吞吐统计定时推送（2s）
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(2000)
        self.stats_timer.timeout.connect(self._emit_stats)
        self.stats_timer.start()

    def _emit_stats(self):
        self.stats_updated.emit(self.worker.get_stats())

    def _initialize_hardware(self):
        driver_type = self.config.get("camera_settings.driver_type", "hikvision")
        serial_number = self.config.get("camera_settings.camera_serial", "")
        logger.info(f"Initializing camera driver: {driver_type}")
        # 失败时直接抛错（启动失败），绝不静默回退模拟相机
        self.camera = create_camera(driver_type, serial_number=serial_number)

    def _apply_trigger_config(self, mode):
        """按模式应用相机触发配置（source/activation/debouncer 从 config 读）。"""
        if not self.camera.is_connected():
            return
        self.camera.set_trigger_config(
            mode,
            source=self.config.get("camera_settings.trigger.source", "Line0"),
            activation=self.config.get("camera_settings.trigger.activation", "RisingEdge"),
            debouncer_time_us=self.config.get("camera_settings.trigger.debouncer_time_us", 5000),
        )

    def set_trigger_mode(self, mode):
        """UI 切换触发模式：记录 config + 管理 preview_timer + 配相机。"""
        self.config.set("camera_settings.trigger.mode", mode)
        if not self.camera.is_connected():
            return
        if mode == "preview":
            self.preview_timer.stop()
            self._apply_trigger_config("preview")
            self.preview_timer.start()
        elif mode == "software_single":
            self.preview_timer.stop()
            self._apply_trigger_config("software_single")
        # hardware / software_continuous：保持预览看画面，start_system 时再配触发

    def capture_single(self):
        """software_single 拍照：触发一张 + 推理 + 显示（不存库，调试用）。"""
        if not self.camera.is_connected():
            self._handle_error("相机未连接。")
            return
        try:
            grab_timeout = self.config.get("camera_settings.trigger.grab_timeout_ms", 2000)
            with self._camera_lock:
                self.camera.enable_software_trigger()
                image = self.camera.get_frame(timeout_ms=grab_timeout)
            if image:
                self.image_updated.emit(image)
                prediction, confidence = self.model_service.predict(image)
                self.result_updated.emit({
                    "id": None, "timestamp": datetime.now().isoformat(),
                    "image_path": None, "thumbnail_path": None,
                    "prediction": prediction, "confidence": confidence,
                    "corrected_label": None,
                })
                logger.info(f"Single capture: {prediction} @ {confidence:.3f}")
        except Exception as e:
            self._handle_error(f"Single capture failed: {e}")

    def connect_camera(self):
        try:
            logger.info("Connecting to camera...")
            self.camera.connect()
            
            # Apply initial exposure settings
            self.set_camera_exposure(self.config.get("camera_settings.exposure"))
            
            # Apply initial resolution settings
            width = self.config.get("camera_settings.resolution_width", 2048)
            height = self.config.get("camera_settings.resolution_height", 2048)
            self.set_camera_resolution(width, height)

            # 默认预览模式（连续出图）
            self._apply_trigger_config("preview")
            self.preview_timer.start()
            self.status_updated.emit(STATUS_PREVIEWING)
            self._reconnect_attempts = 0
            if getattr(self.camera, "device_serial", None):
                self.camera_info.emit(
                    f"相机已连接 (SN: {self.camera.device_serial}, "
                    f"Model: {self.camera.device_model or '?'})"
                )
            logger.info("Camera connected, preview started.")
        except Exception as e:
            self._handle_error(f"Failed to connect camera: {e}")

    def disconnect_camera(self):
        logger.info("Disconnecting camera...")
        self.preview_timer.stop()
        if self.camera.is_connected():
            self.camera.disconnect()
        self.status_updated.emit(STATUS_IDLE)
        logger.info("Camera disconnected.")

    def start_system(self):
        """启动采集（仅 hardware / software_continuous 模式走此入口）。"""
        if not self.model_service.is_ready():
            self._handle_error("模型未加载，无法启动采集。请先选择并加载模型。")
            return
        if not self.camera.is_connected():
            self._handle_error("相机未连接。")
            return
        mode = self.config.get("camera_settings.trigger.mode", "hardware")
        if mode not in ("hardware", "software_continuous"):
            self._handle_error(f"模式 '{mode}' 不需要启动采集（preview 看画面 / software_single 用拍照按钮）。")
            return
        try:
            logger.info(f"Starting processing (trigger={mode})...")
            self.preview_timer.stop()
            self.set_camera_exposure(self.config.get("camera_settings.exposure"))
            self._apply_trigger_config(mode)  # 配触发参数（Line0 或 Software）
            if not self.worker_thread.isRunning():
                self.worker_thread.start()
            self.status_updated.emit(STATUS_RUNNING)
            logger.info("Processing started.")
        except Exception as e:
            self._handle_error(f"Failed to start system: {e}")

    def stop_system(self):
        """停止采集，恢复预览模式。worker 未及时停止则不碰相机（避免与仍在跑的 worker 竞态改触发参数）。"""
        logger.info("Stopping processing...")
        worker_stopped = True
        if self.worker_thread.isRunning():
            self.worker.stop_loop()
            if not self.worker_thread.wait(5000):
                logger.warning("Worker 未在 5s 内停止，跳过相机配置恢复以避免竞态。建议手动断开重连。")
                worker_stopped = False
        # 仅当 worker 确实停止后才操作相机（避免与仍在跑的 worker 竞态改触发参数）
        if worker_stopped and self.camera.is_connected():
            self._apply_trigger_config("preview")
            self.preview_timer.start()
            self.status_updated.emit(STATUS_PREVIEWING)
            logger.info("Stopped, returned to preview.")
        elif not self.camera.is_connected():
            self.status_updated.emit(STATUS_IDLE)
        # worker 超时未停：保持当前状态，不碰相机，等 worker 自行结束或人工介入

    def shutdown(self):
        """Cleanly shuts down all components."""
        logger.info("Shutdown initiated...")
        if self.worker_thread.isRunning():
            self.stop_system()
            if self.worker_thread.isRunning():
                # worker 卡死（如 SDK 取帧阻塞）：强行断开相机/关 DB 会与 worker 竞态，
                # 可能触发 SDK 崩溃。跳过清理，由进程退出兜底（SDK 句柄随进程释放，
                # SQLite WAL 会自动恢复）。
                logger.error(
                    "Worker 未能在超时内停止，跳过相机断开与 DB 关闭（由进程退出兜底）。"
                )
                return
        # 等待模型加载线程结束（避免退出时 QThread 仍运行导致崩溃）
        for loader in self._model_loaders:
            if loader.isRunning():
                loader.wait(5000)
        self.disconnect_camera()
        # Close database connection to properly checkpoint WAL
        self.db_service.close()
        logger.info("Shutdown complete.")

    def cleanup_old_records(self, retention_days=None, delete=True):
        """处理超过保留期的记录 + 磁盘水位清理（决策 A）。

        delete=True:  删除记录及原图/缩略图文件（定时清理用）。
        delete=False: 仅统计并记日志，不删除（启动时用，防止误删旧样本）。
        """
        if retention_days is None:
            retention_days = self.config.get("storage.retention_days", 60)
        now = datetime.now()
        cutoff = (now - timedelta(days=retention_days)).isoformat()
        if not delete:
            n = self.db_service.count_records_before(cutoff)
            if n > 0:
                logger.info(f"Retention check: {n} 条记录超过 {retention_days}d (cutoff={cutoff})。"
                            f"不自动删除——由定时清理或手动触发处理。")
            return n, 0

        total_records = total_files = total_bytes = 0

        # 1) 超过保留期的记录无条件删除
        records, files, freed = self._delete_records_older_than(cutoff)
        total_records += records
        total_files += files
        total_bytes += freed

        # 2) 磁盘水位清理：剩余空间低于水位时，从最旧开始删（保留 min_age 内新数据）
        min_age_days = self.config.get("storage.cleanup_min_age_days", 7)
        watermark_gb = self.config.get("storage.disk_watermark_gb", 50)
        save_dir = self.config.get("data_paths.collected_data_directory", "data/images/")
        status, free_gb, _ = self._disk_monitor.check_space(save_dir)
        if status in ("warning", "critical"):
            water_cutoff = (now - timedelta(days=min_age_days)).isoformat()
            while status in ("warning", "critical"):
                records, files, freed = self._delete_records_older_than(water_cutoff)
                total_records += records
                total_files += files
                total_bytes += freed
                if records == 0:
                    break
                status, free_gb, _ = self._disk_monitor.check_space(save_dir)

        if total_records:
            self.disk_space_warning.emit(
                f"存储清理: 删除 {total_records} 条记录 / {total_files} 个文件，"
                f"释放约 {total_bytes / 1e9:.2f}GB"
            )
        logger.info(
            f"Cleanup: removed {total_records} records, {total_files} files, "
            f"{total_bytes / 1e9:.2f}GB freed "
            f"(retention={retention_days}d, watermark={watermark_gb}GB, min_age={min_age_days}d)"
        )
        return total_records, total_files

    def _delete_records_older_than(self, cutoff_timestamp, limit=500):
        """先删文件再删 DB 行（DB 删除单事务）；返回 (记录数, 文件数, 释放字节)。"""
        records = self.db_service.delete_records_before_in_batches(cutoff_timestamp, limit)
        if not records:
            return 0, 0, 0
        removed_files = 0
        freed_bytes = 0
        for _rid, image_path, thumbnail_path in records:
            for p in (image_path, thumbnail_path):
                if not p:
                    continue
                try:
                    size = os.path.getsize(p) if os.path.exists(p) else 0
                    os.remove(p)
                    removed_files += 1
                    freed_bytes += size
                except OSError as e:
                    logger.warning(f"Failed to remove file {p}: {e}")
        self.db_service.delete_records_by_ids([r[0] for r in records])
        return len(records), removed_files, freed_bytes

    def _scheduled_cleanup(self):
        """定时清理包装，吞掉异常避免影响事件循环。"""
        try:
            self.cleanup_old_records()
        except Exception as e:
            logger.error(f"Scheduled cleanup failed: {e}")

    def set_camera_exposure(self, value):
        if self.camera and self.camera.is_connected():
            try:
                self.camera.set_exposure(value)
                logger.info(f"Set camera exposure to {value}.")
            except Exception as e:
                self._handle_error(f"Failed to set exposure: {e}")

    def set_camera_resolution(self, width, height):
        if self.camera and self.camera.is_connected():
            try:
                self.camera.set_resolution(width, height)
                self.config.set("camera_settings.resolution_width", width)
                self.config.set("camera_settings.resolution_height", height)
                logger.info(f"Set camera resolution to {width}x{height} and updated config.")
            except Exception as e:
                self._handle_error(f"Failed to set resolution: {e}")

    def _preview_frame(self):
        try:
            with self._camera_lock:
                image = self.camera.get_frame(timeout_ms=100)  # 短 timeout，相机异常时 UI 最多卡 100ms
            if image:
                self.image_updated.emit(image)
        except Exception as e:
            self._handle_error(f"Preview Error: {e}")

    def _try_reconnect(self):
        """相机未连接时尝试自动重连（定时调用）。"""
        if self.camera.is_connected():
            self._reconnect_attempts = 0
            return
        if not hasattr(self.camera, "reconnect"):
            return
        try:
            logger.info(f"尝试重连相机 (第 {self._reconnect_attempts + 1} 次)...")
            self.camera.reconnect()
            self._reconnect_attempts = 0
            self.set_camera_exposure(self.config.get("camera_settings.exposure"))
            width = self.config.get("camera_settings.resolution_width", 2048)
            height = self.config.get("camera_settings.resolution_height", 2048)
            self.set_camera_resolution(width, height)
            mode = self.config.get("camera_settings.trigger.mode", "preview")
            if self.worker_thread.isRunning():
                # 采集运行中：恢复配置的触发模式，worker 继续取图
                self._apply_trigger_config(mode)
            else:
                self._apply_trigger_config("preview")
                self.preview_timer.start()
                self.status_updated.emit(STATUS_PREVIEWING)
            if getattr(self.camera, "device_serial", None):
                self.camera_info.emit(
                    f"相机已重连 (SN: {self.camera.device_serial}, "
                    f"Model: {self.camera.device_model or '?'})"
                )
            logger.info("相机重连成功。")
        except Exception as e:
            self._reconnect_attempts += 1
            logger.warning(f"相机重连失败 (attempt {self._reconnect_attempts}): {e}")
            if self._reconnect_attempts % 6 == 1:
                self.disk_space_warning.emit(
                    f"相机重连失败，请检查相机连接（已尝试 {self._reconnect_attempts} 次）"
                )

    def correct_prediction(self, record_id, corrected_label):
        self.db_service.update_correction(record_id, corrected_label)
        self._export_correction_sample(record_id, corrected_label)

    def _export_correction_sample(self, record_id, corrected_label):
        """
        把纠错样本归档到 corrections/<corrected_label>/，形成 ImageFolder 兼容结构，
        便于事后用纠错数据重训。原图与 DB 记录保持不变。
        """
        record = self.db_service.get_record(record_id)
        if not record:
            logger.warning(f"Cannot export correction: record {record_id} not found.")
            return
        record_id, timestamp, image_path, _thumbnail, original_pred, confidence, _corr, quality_status, _reason = record
        if quality_status not in (None, "ok"):
            logger.warning(f"拒采记录不参与纠错导出: record {record_id} (quality={quality_status})")
            return
        if not image_path or not os.path.exists(image_path):
            logger.warning(f"Cannot export correction: source image not found ({image_path}).")
            return

        corrections_dir = self.config.get("data_paths.corrections_directory", "data/corrections/")
        # 清理标签中的路径非法字符（操作员输入兜底）
        safe_label = re.sub(r'[<>:"/\\|?*]', '_', str(corrected_label)).strip() or "unknown"
        label_dir = os.path.join(corrections_dir, safe_label)
        os.makedirs(label_dir, exist_ok=True)

        base = f"{record_id}_{original_pred}"
        dest_img = os.path.join(label_dir, base + ".jpg")
        dest_meta = os.path.join(label_dir, base + ".json")
        try:
            shutil.copy(image_path, dest_img)
            meta = {
                "record_id": record_id,
                "timestamp": timestamp,
                "source_image": image_path,
                "original_prediction": original_pred,
                "confidence": confidence,
                "corrected_label": corrected_label,
            }
            with open(dest_meta, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            logger.info(f"Exported correction sample -> {dest_img}")
        except Exception as e:
            logger.error(f"Failed to export correction sample: {e}")

    def get_recent_records(self, limit=50):
        return self.db_service.get_recent_records(limit)

    def get_filtered_records(self, prediction=None, quality_status=None, limit=200):
        """历史检索：按品级/质量状态筛选（供 UI 查询）。"""
        return self.db_service.search_records(
            prediction=prediction or None,
            quality_status=quality_status,
            limit=limit,
        )

    def export_history_csv(self, filepath, rows):
        """导出历史记录为 CSV。"""
        n = export_records_csv(filepath, rows)
        logger.info(f"Exported {n} records to {filepath}")
        return n

    def _handle_error(self, message):
        """
        可恢复错误：仅记录并通知 UI，不触发停机。
        单次操作失败（连接相机、设置参数、单帧预览等）不应让整条产线停摆。
        """
        logger.error(f"System Error: {message}")
        self.error_occurred.emit(message)

    def _handle_worker_error(self, message):
        """
        Worker 线程报告的错误：处理循环已由 worker 自行停止。
        这里仅记录、通知 UI，并尽量恢复到预览态，便于操作员排查后重新开始，
        而非整线停机或断开相机/数据库。
        """
        logger.error(f"Worker Error: {message}")
        self.error_occurred.emit(message)
        if self.camera.is_connected():
            # 先切回 preview 触发模式，再启预览取流；否则硬件触发模式下预览会一直无图
            self._apply_trigger_config("preview")
            self.preview_timer.start()
            self.status_updated.emit(STATUS_PREVIEWING)
        else:
            self.status_updated.emit(STATUS_IDLE)

    def get_available_models(self):
        return self.model_service.get_downloaded_models()

    def reload_model(self, model_name):
        """后台加载模型（不阻塞 UI）。完成通过 model_loaded 信号通知。

        带递增 seq：只有最后一次请求的加载结果会被采纳，过期结果直接丢弃。
        """
        self._model_switch_seq += 1
        seq = self._model_switch_seq
        logger.info(f"后台加载模型 {model_name} (seq={seq})...")
        # 保留运行中线程的引用，避免 QThread 运行中被 GC 销毁导致崩溃
        self._model_loaders = [w for w in self._model_loaders if w.isRunning()]
        worker = ModelLoadWorker(self.model_service, model_name, seq)
        self._model_loaders.append(worker)
        worker.finished_load.connect(self._on_model_loaded)
        worker.start()

    def _on_model_loaded(self, ok, model_name, seq):
        if seq != self._model_switch_seq:
            logger.info(
                f"忽略过期模型加载结果: {model_name} (seq={seq}, current={self._model_switch_seq})"
            )
            return
        if ok:
            self.config.set("model_settings.current_model_name", model_name)
            logger.info(f"模型切换成功: {model_name}")
        else:
            self.error_occurred.emit(f"加载模型失败: {model_name}")
            logger.error(f"加载模型失败: {model_name}")
        self.model_loaded.emit(ok, model_name)
