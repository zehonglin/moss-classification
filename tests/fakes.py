"""测试共享的假控制器（避免真实 SystemController 的 DB/模型/线程副作用）。"""

from PySide6.QtCore import QObject, Signal


class _FakeCam:
    def __init__(self, connected):
        self._connected = connected

    def is_connected(self):
        return self._connected


class FakeController(QObject):
    """MainWindow 单测用的最小假控制器。"""

    image_updated = Signal(object)
    result_updated = Signal(dict)
    status_updated = Signal(str)
    error_occurred = Signal(str)
    disk_space_warning = Signal(str)
    model_loaded = Signal(bool, str)
    camera_info = Signal(str)
    stats_updated = Signal(dict)

    def __init__(self, connected=False):
        super().__init__()
        self.status = "IDLE"
        self.camera = _FakeCam(connected)
        self.stop_calls = 0
        self.corrections = []

    def get_recent_records(self):
        return []

    def get_available_models(self):
        return []

    def stop_system(self):
        self.stop_calls += 1

    def correct_prediction(self, record_id, label):
        self.corrections.append((record_id, label))
