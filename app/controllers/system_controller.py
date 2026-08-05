import logging
import threading
from PySide6.QtCore import QObject, Signal, QThread, QTimer
from PySide6.QtGui import QImage
from app.core.interfaces import BaseCamera, BaseConveyor
from app.services.model_service import ModelService
from app.services.database_service import DatabaseService
from app.utils.config_manager import ConfigManager
from app.utils.disk_monitor import DiskSpaceMonitor
import time
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Simplified Statuses for State Machine
STATUS_IDLE = "IDLE"  # Disconnected
STATUS_PREVIEWING = "PREVIEWING" # Camera connected, live view
STATUS_RUNNING = "RUNNING" # Full processing loop


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

    def __init__(self, camera: BaseCamera, model_service: ModelService, db_service: DatabaseService, config: ConfigManager):
        super().__init__()
        self.camera = camera
        self.model_service = model_service
        self.db_service = db_service
        self.config = config
        
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
        
        logger.info("Processing loop started.")
        
        # Track consecutive errors for smart failure detection
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10  # Stop after 10 consecutive failures
        
        while not self._stop_event.is_set():
            try:
                loop_start_time = time.time()
                
                # Check stop event before each major operation for responsive stopping
                if self._stop_event.is_set():
                    break
                
                # 1. Capture
                capture_start_time = time.time()
                image = self.camera.get_frame()
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
                    
                    # 4. Save Image to Disk
                    save_img_start_time = time.time()
                    now = datetime.now()
                    timestamp_iso = now.isoformat()
                    timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")
                    filename = f"moss_{timestamp_str}.jpg"
                    os.makedirs(save_dir, exist_ok=True)
                    image_path = os.path.join(save_dir, filename)
                    image.save(image_path)
                    save_img_duration = (time.time() - save_img_start_time) * 1000
                    
                    if self._stop_event.is_set():
                        break
                    
                    # 5. Save to DB
                    save_db_start_time = time.time()
                    record_id = self.db_service.add_record(timestamp_iso, image_path, prediction, confidence)
                    
                    record_data = {
                        "id": record_id,
                        "timestamp": timestamp_iso,
                        "image_path": image_path,
                        "prediction": prediction,
                        "confidence": confidence,
                        "corrected_label": None
                    }
                    self.result_ready.emit(record_data)
                    save_db_duration = (time.time() - save_db_start_time) * 1000
                    
                    # Successful frame - reset error counter
                    consecutive_errors = 0

                # Frequency Control & Logging
                freq_ms = self.config.get("camera_settings.capture_frequency_ms", 1000)
                if freq_ms <= 0: freq_ms = 100
                
                total_processing_time = (time.time() - loop_start_time) * 1000
                sleep_time_ms = freq_ms - total_processing_time
                
                if image:  # Only log if we captured a frame
                    logger.info(
                        f"Loop Profile: Capture={capture_duration:.2f}ms, Predict={predict_duration:.2f}ms, "
                        f"SaveImg={save_img_duration:.2f}ms, SaveDB={save_db_duration:.2f}ms | "
                        f"Total={total_processing_time:.2f}ms, Target={freq_ms}ms, Sleep={max(0, sleep_time_ms):.2f}ms"
                    )

                # Use Event.wait() for interruptible sleep instead of QThread.msleep()
                # This allows the loop to exit immediately when stop_loop() is called
                if sleep_time_ms > 0 and not self._stop_event.is_set():
                    # wait() returns True if the event is set during the wait
                    self._stop_event.wait(timeout=sleep_time_ms / 1000.0)
            
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
        
        # Initialize ModelService with a safe default model first
        default_model = 'efficientnet_b0'
        models_dir = self.config.get("model_settings.models_directory", "models/")
        self.model_service = ModelService(model_name=default_model, models_dir=models_dir)

        # After successful initialization, load the user-configured model
        desired_model = self.config.get("model_settings.current_model_name", default_model)
        if desired_model != default_model:
            # Use the load_model method which is designed to handle custom .pth files
            logger.info(f"Default model loaded. Now switching to configured model: {desired_model}")
            self.model_service.load_model(desired_model)

        
        # Hardware
        self._initialize_hardware()
        
        # Preview Timer
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(50) # ~20 FPS
        self.preview_timer.timeout.connect(self._preview_frame)
        
        # Worker Thread
        self.worker_thread = QThread()
        self.worker = SystemWorker(self.camera, self.model_service, self.db_service, self.config)
        self.worker.moveToThread(self.worker_thread)
        
        # Connections
        self.worker.image_ready.connect(self.image_updated)
        self.worker.result_ready.connect(self.result_updated)
        self.worker.error_occurred.connect(self._handle_error)
        self.worker.disk_space_warning.connect(self.disk_space_warning)  # Forward disk warnings
        self.worker_thread.started.connect(self.worker.start_loop)
        self.worker.finished.connect(self.worker_thread.quit)

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

        from app.drivers.mock_driver import MockConveyor
        self.conveyor = MockConveyor()

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
        if not self.camera.is_connected():
            self._handle_error("Camera is not connected.")
            return
        try:
            logger.info("Starting full system processing...")
            self.preview_timer.stop() # Stop preview
            
            # Apply latest settings before starting
            self.set_camera_exposure(self.config.get("camera_settings.exposure"))

            self.conveyor.start()
            self.conveyor.set_speed(self.config.get("conveyor_settings.speed_mm_per_s"))
            
            if not self.worker_thread.isRunning():
                self.worker_thread.start()
                
            self.status_updated.emit(STATUS_RUNNING)
            logger.info("Full system processing started.")
        except Exception as e:
            self._handle_error(f"Failed to start system: {e}")

    def stop_system(self):
        """
        Stops the full system processing loop.
        Thread-safe: uses Event signaling for reliable stop.
        """
        logger.info("Stopping full system processing...")
        
        if self.worker_thread.isRunning():
            # Signal the worker to stop (thread-safe via Event)
            self.worker.stop_loop()
            
            # Wait for thread to finish with extended timeout
            # Since we use Event.wait() for sleep, the loop should exit quickly
            if not self.worker_thread.wait(5000):  # 5 second timeout
                logger.warning(
                    "Worker thread did not stop within 5 seconds. "
                    "This may indicate a blocking operation in the processing loop."
                )
                # Note: We don't forcefully terminate as that could cause corruption
                # The thread will eventually stop when the current operation completes
        
        self.conveyor.stop()
        
        # Return to previewing if camera is still connected
        if self.camera.is_connected():
            self.preview_timer.start()
            self.status_updated.emit(STATUS_PREVIEWING)
            logger.info("System stopped, returned to preview mode.")
        else:
            self.status_updated.emit(STATUS_IDLE)
            logger.info("System stopped, camera is disconnected.")

    def shutdown(self):
        """Cleanly shuts down all components."""
        logger.info("Shutdown initiated...")
        if self.worker_thread.isRunning():
            self.stop_system()
        self.disconnect_camera()
        
        # Close database connection to properly checkpoint WAL
        self.db_service.close()
        
        logger.info("Shutdown complete.")

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
            image = self.camera.get_frame()
            if image:
                self.image_updated.emit(image)
        except Exception as e:
            self._handle_error(f"Preview Error: {e}")

    def correct_prediction(self, record_id, corrected_label):
        self.db_service.update_correction(record_id, corrected_label)

    def get_recent_records(self, limit=50):
        return self.db_service.get_recent_records(limit)

    def _handle_error(self, message):
        logger.error(f"System Error: {message}")
        self.error_occurred.emit(message)
        self.shutdown() # Perform a full shutdown on error

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
