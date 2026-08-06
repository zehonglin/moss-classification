from abc import ABC, abstractmethod
from PySide6.QtGui import QImage


class BaseCamera(ABC):
    """工业相机抽象基类。

    支持四种触发模式（由 controller 按配置切换）：
    - preview: TriggerMode=Off, 连续出图（预览）
    - hardware: TriggerMode=On + 外部 Line（光电传感器上升沿）
    - software_single: TriggerMode=On + Software, 手动触发一张
    - software_continuous: TriggerMode=On + Software, 软件按节拍连续触发
    """
    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def get_frame(self, timeout_ms: int | None = None) -> QImage | None:
        """取一帧。触发模式下会阻塞到硬件/软件触发到来（受 timeout_ms 约束）。
        返回 QImage 或 None（超时/未连接/取图失败）。"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    def set_resolution(self, width: int, height: int):
        pass

    @abstractmethod
    def set_exposure(self, value):
        """设置曝光（微秒，固定值；触发抓拍不要用 auto）。"""
        pass

    @abstractmethod
    def set_trigger_config(self, mode: str, source: str | None = None,
                           activation: str | None = None,
                           debouncer_time_us: int | None = None):
        """配置触发模式。
        mode: 'preview' | 'hardware' | 'software_single' | 'software_continuous'
        source: 触发源，如 'Line0'（hardware 模式用）
        activation: 'RisingEdge' | 'FallingEdge' 等（hardware 用）
        debouncer_time_us: 触发防抖（hardware 用，过滤光电信号边沿抖动）
        """
        pass

    @abstractmethod
    def enable_software_trigger(self):
        """发一次软件触发（software_single / software_continuous 模式用）。"""
        pass
