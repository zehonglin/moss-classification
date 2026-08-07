"""测试共享的假控制器（避免真实 SystemController 的 DB/模型/线程副作用）。"""

from PySide6.QtCore import QObject, Signal


class _FakeCam:
    def __init__(self, connected):
        self._connected = connected

    def is_connected(self):
        return self._connected


class FakeController(QObject):
    """MainWindow 单测用的最小假控制器。

    覆盖新 MainWindow（v2）所有调用面：
        信号：image_updated / result_updated / status_updated / error_occurred /
              disk_space_warning / model_loaded / camera_info / stats_updated /
              grade_summary_updated
        方法：connect_camera / disconnect_camera / start_system / stop_system /
              capture_single / set_trigger_mode / set_camera_exposure /
              set_camera_resolution / reload_model / correct_prediction /
              get_recent_records / search_records_paged / export_history_csv /
              export_with_images / get_grade_summary / get_available_models /
              get_filtered_records / shutdown
    """

    image_updated = Signal(object)
    result_updated = Signal(dict)
    status_updated = Signal(str)
    error_occurred = Signal(str)
    disk_space_warning = Signal(str)
    model_loaded = Signal(bool, str)
    camera_info = Signal(str)
    stats_updated = Signal(dict)
    grade_summary_updated = Signal(dict)

    def __init__(self, connected=False):
        super().__init__()
        self.status = "IDLE"
        self.camera = _FakeCam(connected)
        self.stop_calls = 0
        self.corrections = []

    def get_recent_records(self):
        return []

    def get_available_models(self):
        return ["mbnet.onnx"]

    def stop_system(self):
        self.stop_calls += 1

    def correct_prediction(self, record_id, label):
        self.corrections.append((record_id, label))

    def get_filtered_records(self, prediction=None, quality_status=None, limit=200):
        self.last_filter = {"prediction": prediction, "quality_status": quality_status}
        return getattr(self, "filtered", [])

    def export_history_csv(self, path, rows):
        self.exported = (path, rows)
        return len(rows)

    # ---- v2 新增面（MainWindow 双模式所需） ----

    def get_grade_summary(self):
        return getattr(
            self,
            "grade_summary",
            {"A": 0, "B": 0, "C": 0, "D": 0, "corrected": 0, "rejected": 0},
        )

    def search_records_paged(
        self, prediction=None, quality_status=None, page=1, page_size=50
    ):
        self.last_paged = {
            "prediction": prediction,
            "quality_status": quality_status,
            "page": page,
        }
        return getattr(self, "paged_rows", []), getattr(self, "paged_total", 0)

    def export_with_images(self, csv_path, image_root, rows, group_by="grade"):
        self.exported_with_images = (csv_path, image_root, rows, group_by)
        return len(rows)

    def connect_camera(self):
        pass

    def disconnect_camera(self):
        pass

    def start_system(self):
        pass

    def set_trigger_mode(self, mode):
        pass

    def set_camera_exposure(self, value):
        pass

    def set_camera_resolution(self, width, height):
        pass

    def reload_model(self, model_name):
        pass

    def capture_single(self):
        pass

    def shutdown(self):
        pass
