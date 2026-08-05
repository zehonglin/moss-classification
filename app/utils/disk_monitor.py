"""
Disk space monitoring utilities for industrial environments.

Provides functions to check available disk space and prevent
system failures due to disk exhaustion during continuous operation.
"""

import os
import shutil
import logging
from typing import Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class DiskSpaceMonitor:
    """
    Monitor disk space and provide warnings when space is low.
    
    For industrial 24/7 operation scenarios:
    - Checks available space before each write operation
    - Provides configurable warning and critical thresholds
    - Emits warnings via callback when thresholds are crossed
    """
    
    # Default thresholds
    DEFAULT_WARNING_THRESHOLD_GB = 10.0  # Warn when < 10GB free
    DEFAULT_CRITICAL_THRESHOLD_GB = 1.0   # Critical when < 1GB free
    
    def __init__(
        self,
        warning_threshold_gb: float = DEFAULT_WARNING_THRESHOLD_GB,
        critical_threshold_gb: float = DEFAULT_CRITICAL_THRESHOLD_GB
    ):
        """
        Initialize the disk space monitor.
        
        Args:
            warning_threshold_gb: Free space (GB) below which to issue warnings
            critical_threshold_gb: Free space (GB) below which to stop operations
        """
        self.warning_threshold_bytes = warning_threshold_gb * (1024 ** 3)
        self.critical_threshold_bytes = critical_threshold_gb * (1024 ** 3)
        
        # Track last warning state to avoid spamming logs
        self._last_warning_level = "ok"
        
    def get_disk_usage(self, path: str) -> Tuple[int, int, int]:
        """
        Get disk usage statistics for the given path.
        
        Args:
            path: Directory or file path to check
            
        Returns:
            Tuple of (total_bytes, used_bytes, free_bytes)
        """
        try:
            # Get the drive/mount point for the given path
            if os.path.exists(path):
                usage = shutil.disk_usage(path)
                return usage.total, usage.used, usage.free
            else:
                # If path doesn't exist, try parent directory
                parent = os.path.dirname(path)
                if parent and os.path.exists(parent):
                    usage = shutil.disk_usage(parent)
                    return usage.total, usage.used, usage.free
                # Fall back to current directory
                usage = shutil.disk_usage(os.getcwd())
                return usage.total, usage.used, usage.free
        except Exception as e:
            logger.error(f"Failed to get disk usage for {path}: {e}")
            return 0, 0, 0
    
    def check_space(self, path: str) -> Tuple[str, float, str]:
        """
        Check if there is enough disk space at the given path.
        
        Args:
            path: Directory path to check
            
        Returns:
            Tuple of (status, free_gb, message)
            status: "ok", "warning", or "critical"
            free_gb: Available space in GB
            message: Human-readable status message
        """
        total, used, free = self.get_disk_usage(path)
        
        if total == 0:
            return "unknown", 0.0, "Unable to determine disk space"
        
        free_gb = free / (1024 ** 3)
        used_percent = (used / total) * 100
        
        if free < self.critical_threshold_bytes:
            status = "critical"
            message = f"CRITICAL: Only {free_gb:.2f}GB free ({used_percent:.1f}% used). Stopping image capture!"
        elif free < self.warning_threshold_bytes:
            status = "warning"
            message = f"WARNING: Low disk space - {free_gb:.2f}GB free ({used_percent:.1f}% used)"
        else:
            status = "ok"
            message = f"Disk space OK: {free_gb:.2f}GB free ({used_percent:.1f}% used)"
        
        # Log state changes to avoid spam
        if status != self._last_warning_level:
            if status == "critical":
                logger.critical(message)
            elif status == "warning":
                logger.warning(message)
            elif self._last_warning_level in ("warning", "critical"):
                logger.info(message)
            self._last_warning_level = status
        
        return status, free_gb, message
    
    def has_enough_space(self, path: str, required_bytes: int = 0) -> bool:
        """
        Quick check if there is enough space for an operation.
        
        Args:
            path: Directory path to check
            required_bytes: Additional bytes needed for the operation
            
        Returns:
            True if there is enough space, False otherwise
        """
        _, _, free = self.get_disk_usage(path)
        min_required = self.critical_threshold_bytes + required_bytes
        return free >= min_required
    
    def get_status_for_ui(self, path: str) -> dict:
        """
        Get disk space status formatted for UI display.
        
        Returns:
            Dictionary with keys: status, free_gb, total_gb, used_percent, message
        """
        total, used, free = self.get_disk_usage(path)
        status, free_gb, message = self.check_space(path)
        
        return {
            "status": status,
            "free_gb": free / (1024 ** 3) if total > 0 else 0,
            "total_gb": total / (1024 ** 3) if total > 0 else 0,
            "used_percent": (used / total * 100) if total > 0 else 0,
            "message": message
        }


# Singleton instance for easy access
_default_monitor: DiskSpaceMonitor | None = None


def get_disk_monitor() -> DiskSpaceMonitor:
    """Get or create the default disk space monitor instance."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = DiskSpaceMonitor()
    return _default_monitor


def check_disk_space(path: str) -> Tuple[str, float, str]:
    """
    Convenience function to check disk space using the default monitor.
    
    Args:
        path: Directory path to check
        
    Returns:
        Tuple of (status, free_gb, message)
    """
    return get_disk_monitor().check_space(path)
