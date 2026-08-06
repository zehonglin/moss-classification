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


class InterlockController(ABC):
    """产线联动扩展接口（预留，当前不实现任何硬件逻辑）。

    若未来需要与 PLC/传送带联动（到位确认、忙信号、不合格剔除、故障停机），
    实现本接口并在 SystemController 中注入；具体硬件协议（Modbus/IO/串口等）
    由实现方负责。接口签名仅供规划，可按实际协议调整。
    """

    @abstractmethod
    def wait_tray_ready(self, timeout_ms: int) -> bool:
        """等待托盘到位确认。返回是否在超时内到位。"""
        pass

    @abstractmethod
    def set_busy(self, busy: bool):
        """向产线输出忙信号（软件处理中禁止进料）。"""
        pass

    @abstractmethod
    def reject_tray(self, reason: str):
        """输出不合格剔除信号（可选，按现场工艺决定）。"""
        pass
