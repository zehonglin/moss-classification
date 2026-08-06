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


def _qimage_to_pil(q_image):
    """QImage → PIL.Image(RGB)。直接读取像素缓冲，不依赖 Qt imageformats 插件
    （本机 PySide6 缺 JPEG 插件，QImage.save / QImageReader 对 JPEG 均不可用）。"""
    q = q_image.convertToFormat(QImage.Format.Format_RGB888)
    ptr = q.bits()
    arr = np.array(ptr).reshape(q.height(), q.width(), 3)
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

        # Thread-safe stop event (replaces _is_running boolean)
        # Event is thread-safe: set(), clear(), is_set() are atomic
        self._stop_event = threading.Event()
        
        # Lock for protecting shared state during initialization/cleanup
        self._state_lock = threading.Lock()
        
        # Disk space monitor for preventing disk exhaustion
        self._disk_monitor = DiskSpaceMonitor(
            warning_threshold_gb=10.0,  # Warn at 10GB free
            critical_threshold_gb=1.0   # Stop at 1GB free
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
                
                if image and not self._stop_event.is_set():
                    self.image_ready.emit(image)
                    
                    # 2. Predict
                    predict_start_time = time.time()
                    prediction, confidence = self.model_service.predict(image)
                    predict_duration = (time.time() - predict_start_time) * 1000
                    
                    if self._stop_event.is_set():
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
                    pil_img = _qimage_to_pil(image)
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
                    record_id = self.db_service.add_record(timestamp_iso, image_path, prediction, confidence, thumbnail_path=thumb_path)
                    
                    record_data = {
                        "id": record_id,
                        "timestamp": timestamp_iso,
                        "image_path": image_path,
                        "thumbnail_path": thumb_path,
                        "prediction": prediction,
                        "confidence": confidence,
                        "corrected_label": None
                    }
                    self.result_ready.emit(record_data)
                    save_db_duration = (time.time() - save_db_start_time) * 1000
                    
                    # Successful frame - reset error counter
                    consecutive_errors = 0

                # 节拍：software_continuous 按 sw_interval；hardware 无 sleep（由光电触发决定）
                total_processing_time = (time.time() - loop_start_time) * 1000
                if image:
                    logger.info(
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


class SystemController(QObject):
    """Main controller for the application."""
    image_updated = Signal(QImage)
    result_updated = Signal(dict)
    status_updated = Signal(str)
    error_occurred = Signal(str)
    disk_space_warning = Signal(str)  # Forwarded from worker

    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config = config_manager
        
        # Services
        self.db_service = DatabaseService(self.config)
        
        # 直接加载配置指定的本地模型，不再预先下载 EfficientNet（离线环境友好）
        models_dir = self.config.get("model_settings.models_directory", "models/")
        desired_model = self.config.get("model_settings.current_model_name")
        self.model_service = ModelService(model_name=desired_model, models_dir=models_dir)

        
        # Hardware
        self._initialize_hardware()
        
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

        # 滚动归档：启动时清理一次过期数据 + 每 24h 定时清理
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.setInterval(24 * 60 * 60 * 1000)  # 24 小时
        self.cleanup_timer.timeout.connect(self._scheduled_cleanup)
        self.cleanup_timer.start()
        self.cleanup_old_records(delete=False)  # 启动只报告，不自动删（防误删旧样本）

    def _initialize_hardware(self):
        driver_type = self.config.get("camera_settings.driver_type", "mock")
        try:
            if driver_type == "hikvision":
                from app.drivers.hikvision_driver import HikvisionCamera
                self.camera = HikvisionCamera()
                logger.info("Using Hikvision Camera Driver")
            else:
                from app.drivers.mock_driver import MockCamera
                self.camera = MockCamera()
                logger.info("Using Mock Camera Driver")
        except ImportError as e:
            logger.warning(f"Failed to load specified driver: {e}. Falling back to Mock.")
            from app.drivers.mock_driver import MockCamera
            self.camera = MockCamera()

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
        """停止采集，恢复预览模式。"""
        logger.info("Stopping processing...")
        if self.worker_thread.isRunning():
            self.worker.stop_loop()
            if not self.worker_thread.wait(5000):
                logger.warning("Worker thread did not stop within 5 seconds.")
        if self.camera.is_connected():
            self._apply_trigger_config("preview")  # 切回连续模式
            self.preview_timer.start()
            self.status_updated.emit(STATUS_PREVIEWING)
            logger.info("Stopped, returned to preview.")
        else:
            self.status_updated.emit(STATUS_IDLE)

    def shutdown(self):
        """Cleanly shuts down all components."""
        logger.info("Shutdown initiated...")
        if self.worker_thread.isRunning():
            self.stop_system()
        self.disconnect_camera()
        
        # Close database connection to properly checkpoint WAL
        self.db_service.close()
        
        logger.info("Shutdown complete.")

    def cleanup_old_records(self, retention_days=None, delete=True):
        """处理超过保留期的记录。
        delete=True:  删除记录及原图/缩略图文件（24h 定时清理用）。
        delete=False: 仅统计并记日志，不删除（启动时用，防止误删旧样本）。"""
        if retention_days is None:
            retention_days = self.config.get("storage.retention_days", 60)
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
        if not delete:
            n = self.db_service.count_records_before(cutoff)
            if n > 0:
                logger.info(f"Retention check: {n} 条记录超过 {retention_days}d (cutoff={cutoff})。"
                            f"不自动删除——由 24h 定时清理或手动触发处理。")
            return n, 0
        deleted = self.db_service.delete_records_before(cutoff)
        n_files = 0
        for image_path, thumbnail_path in deleted:
            for p in (image_path, thumbnail_path):
                if p:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                            n_files += 1
                    except OSError as e:
                        logger.warning(f"Failed to remove file {p}: {e}")
        logger.info(f"Cleanup: removed {len(deleted)} records, {n_files} files (retention={retention_days}d, cutoff={cutoff})")
        return len(deleted), n_files

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
                image = self.camera.get_frame()
            if image:
                self.image_updated.emit(image)
        except Exception as e:
            self._handle_error(f"Preview Error: {e}")

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
        _, timestamp, image_path, original_pred, confidence, _ = record
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
            self.preview_timer.start()
            self.status_updated.emit(STATUS_PREVIEWING)
        else:
            self.status_updated.emit(STATUS_IDLE)

    def get_available_models(self):
        return self.model_service.get_downloaded_models()

    def reload_model(self, model_name):
        logger.info(f"Attempting to switch model to {model_name}...")
        if self.model_service.load_model(model_name):
            self.config.set("model_settings.current_model_name", model_name)
            logger.info(f"Successfully switched model to {model_name}")
            return True
        else:
            self.error_occurred.emit(f"Failed to load model {model_name}")
            logger.error(f"Failed to load model {model_name}")
            return False
