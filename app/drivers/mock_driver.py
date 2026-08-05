import logging
import gc
import numpy as np
from PySide6.QtGui import QImage, Qt
from app.core.interfaces import BaseCamera, BaseConveyor

logger = logging.getLogger(__name__)


class MockCamera(BaseCamera):
    """
    A mock camera for development and testing purposes.
    Implements the same memory management strategy as HikvisionCamera.
    """
    
    # Trigger garbage collection every N frames to prevent memory buildup
    GC_TRIGGER_INTERVAL = 100
    
    def __init__(self):
        self._is_connected = False
        self._frame_count = 0
        # Reusable buffer for mock image data
        self._image_buffer = None
        self._width = 640
        self._height = 480
        logger.info("Initialized MockCamera.")

    def connect(self):
        logger.info("[MockCamera] Connecting to camera...")
        self._is_connected = True
        self._frame_count = 0
        # Pre-allocate image buffer
        self._image_buffer = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        logger.info("[MockCamera] Connection successful.")
        return True

    def disconnect(self):
        logger.info("[MockCamera] Disconnecting from camera...")
        self._is_connected = False
        self._cleanup_buffers()
        logger.info("[MockCamera] Disconnected.")

    def _cleanup_buffers(self):
        """Explicitly release all allocated buffers and trigger GC."""
        self._image_buffer = None
        self._frame_count = 0
        gc.collect()
        logger.debug("[MockCamera] Buffers cleaned up and GC triggered.")

    def get_frame(self) -> QImage | None:
        if not self._is_connected:
            logger.error("[MockCamera] Error: get_frame called but camera is not connected.")
            return None
        
        logger.debug("[MockCamera] Capturing frame...")
        
        # Create QImage from reusable buffer
        # Using numpy buffer that is pre-allocated
        image = QImage(
            self._image_buffer.data,
            self._width, self._height,
            self._width * 3,
            QImage.Format_RGB888
        ).copy()
        
        # Periodic GC like HikvisionCamera
        self._frame_count += 1
        if self._frame_count >= self.GC_TRIGGER_INTERVAL:
            self._frame_count = 0
            gc.collect()
            logger.debug("[MockCamera] Periodic GC triggered after 100 frames")
        
        logger.debug("[MockCamera] Frame captured.")
        return image

    def is_connected(self) -> bool:
        """Check if the camera is currently connected."""
        return self._is_connected

    def set_exposure(self, value):
        """Set the mock camera's exposure."""
        logger.info(f"[MockCamera] Setting exposure to {value}.")

    def set_resolution(self, width: int, height: int):
        """Set the mock camera's resolution."""
        logger.info(f"[MockCamera] Setting resolution to {width}x{height}.")
        self._width = width
        self._height = height
        # If connected, re-allocate the buffer to the new size
        if self._is_connected:
            self._image_buffer = np.zeros((self._height, self._width, 3), dtype=np.uint8)
            logger.info(f"[MockCamera] Image buffer re-allocated to {width}x{height}.")


class MockConveyor(BaseConveyor):
    """A mock conveyor for development and testing purposes."""
    def __init__(self):
        self._speed = 0
        self._is_moving = False
        logger.info("Initialized MockConveyor.")

    def start(self):
        if self._speed > 0:
            logger.info(f"[MockConveyor] Starting conveyor at speed {self._speed} mm/s.")
            self._is_moving = True
        else:
            logger.warning("[MockConveyor] Cannot start, speed is set to 0.")

    def stop(self):
        logger.info("[MockConveyor] Stopping conveyor.")
        self._is_moving = False

    def set_speed(self, speed: int):
        if speed >= 0:
            logger.info(f"[MockConveyor] Setting speed to {speed} mm/s.")
            self._speed = speed
        else:
            logger.error(f"[MockConveyor] Error: Speed cannot be negative. Value was {speed}.")
