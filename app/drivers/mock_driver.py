import logging
import gc
import numpy as np
from PySide6.QtGui import QImage
from app.core.interfaces import BaseCamera

logger = logging.getLogger(__name__)


class MockCamera(BaseCamera):
    """模拟相机（开发/调试）。实现触发接口但无真实硬件行为。"""
    GC_TRIGGER_INTERVAL = 100

    def __init__(self):
        self._is_connected = False
        self._frame_count = 0
        self._image_buffer = None
        self._width = 640
        self._height = 480
        self._trigger_mode = "preview"
        self.device_serial = None
        self.device_model = "MockCamera"
        logger.info("Initialized MockCamera.")

    def connect(self):
        logger.info("[MockCamera] Connecting...")
        self._is_connected = True
        self._frame_count = 0
        self._image_buffer = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        logger.info("[MockCamera] Connection successful.")

    def disconnect(self):
        logger.info("[MockCamera] Disconnecting...")
        self._is_connected = False
        self._image_buffer = None
        self._frame_count = 0
        gc.collect()
        logger.info("[MockCamera] Disconnected.")

    def get_frame(self, timeout_ms: int | None = None) -> QImage | None:
        if not self._is_connected:
            logger.error("[MockCamera] get_frame called but not connected.")
            return None
        # mock 不真正阻塞等触发，立即返回一帧（开发用；真实触发行为见 HikvisionCamera）
        image = QImage(
            self._image_buffer.data, self._width, self._height,
            self._width * 3, QImage.Format_RGB888
        ).copy()
        self._frame_count += 1
        if self._frame_count >= self.GC_TRIGGER_INTERVAL:
            self._frame_count = 0
            gc.collect()
        return image

    def is_connected(self) -> bool:
        return self._is_connected

    def set_exposure(self, value):
        logger.info(f"[MockCamera] exposure={value}us (固定值)")

    def set_resolution(self, width: int, height: int):
        logger.info(f"[MockCamera] resolution={width}x{height}")
        self._width = width
        self._height = height
        if self._is_connected:
            self._image_buffer = np.zeros((self._height, self._width, 3), dtype=np.uint8)

    def set_trigger_config(self, mode, source=None, activation=None, debouncer_time_us=None):
        self._trigger_mode = mode
        logger.info(f"[MockCamera] trigger mode={mode} (mock 无硬件行为)")

    def enable_software_trigger(self):
        logger.info("[MockCamera] software trigger (mock 无操作)")
