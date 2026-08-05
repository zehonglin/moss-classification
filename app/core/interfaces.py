from abc import ABC, abstractmethod
from PySide6.QtGui import QImage

class BaseCamera(ABC):
    """Abstract base class for all camera hardware."""
    @abstractmethod
    def connect(self):
        """Connect to the camera hardware."""
        pass

    @abstractmethod
    def disconnect(self):
        """Disconnect from the camera hardware."""
        pass

    @abstractmethod
    def get_frame(self) -> QImage | None:
        """
        Capture a single frame from the camera.
        Returns a QImage or None if a frame cannot be captured.
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if the camera is currently connected.
        Returns True if connected, False otherwise.
        """
        pass

    @abstractmethod
    def set_resolution(self, width: int, height: int):
        """Set the camera's capture resolution."""
        pass

    @abstractmethod
    def set_exposure(self, value):
        """Set the camera's exposure time (e.g., in microseconds)."""
        pass

class BaseConveyor(ABC):
    """Abstract base class for all conveyor belt hardware."""
    @abstractmethod
    def start(self):
        """Start the conveyor belt."""
        pass

    @abstractmethod
    def stop(self):
        """Stop the conveyor belt."""
        pass

    @abstractmethod
    def set_speed(self, speed: int):
        """Set the conveyor belt speed (e.g., in mm/s)."""
        pass
