import sys
import os
import ctypes
import numpy as np
import logging
import gc
from app.core.interfaces import BaseCamera
from PySide6.QtGui import QImage
from app.drivers.camera_selector import read_device_model, read_device_serial, select_device_index
from app.drivers.camera_selector import is_fatal_frame_error

# Add MvImport to path
sdk_path = os.path.join(os.getcwd(), "app", "drivers", "hikvision_sdk")
if sdk_path not in sys.path:
    sys.path.append(sdk_path)

logger = logging.getLogger(__name__)

try:
    from MvCameraControl_class import *
except (ImportError, OSError) as e:
    # Raise ImportError so SystemController can catch it and fallback to Mock
    raise ImportError(f"Hikvision SDK failed to load from {sdk_path}: {e}")


class HikvisionCamera(BaseCamera):
    """
    Hikvision industrial camera driver with memory-optimized frame capture.
    
    Memory Management Strategy:
    - Reuses ctypes buffer for pixel conversion (convert_buf)
    - Reuses numpy array buffer for RGB data (rgb_buffer)
    - QImage.copy() is still required due to Qt's memory model, but
      we trigger periodic GC to prevent memory buildup
    - All buffers are explicitly cleared on disconnect
    """
    
    # Trigger garbage collection every N frames to prevent memory buildup
    GC_TRIGGER_INTERVAL = 100
    
    # Default frame capture timeout (ms) - shorter for high-frequency capture
    DEFAULT_TIMEOUT_MS = 500
    
    # Maximum consecutive failures before logging a warning
    MAX_CONSECUTIVE_FAILURES = 5

    # 连续致命错误达到该值判定为物理掉线（触发模式超时不计入）
    MAX_CONSECUTIVE_FATAL_FAILURES = 10
    
    def __init__(self, serial_number=None):
        self.handle = None
        self.b_is_connected = False
        self.n_payload_size = 0
        self._trigger_mode = "preview"
        self.serial_number = serial_number
        self.device_serial = None
        self.device_model = None
        
        # Pixel conversion buffer (ctypes) - reused across frames
        self.convert_buf = None
        self.convert_buf_size = 0
        
        # RGB numpy array buffer - reused across frames of same dimensions
        self._rgb_buffer = None
        self._rgb_buffer_shape = (0, 0, 3)
        
        # Frame counter for periodic GC
        self._frame_count = 0
        
        # Cache for last frame dimensions to detect resolution changes
        self._last_width = 0
        self._last_height = 0
        
        # Configurable timeout for frame capture (ms)
        self._timeout_ms = self.DEFAULT_TIMEOUT_MS
        
        # Track consecutive failures for diagnostics
        self._consecutive_failures = 0
        # 连续致命错误计数（用于判定物理掉线，与日志计数分开）
        self._fatal_failure_count = 0

    def connect(self):
        if MvCamera is None:
            raise ImportError("Hikvision SDK not found. Please ensure 'app/drivers/hikvision_sdk' exists.")

        # 1. Enum Devices
        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_USB_DEVICE | MV_GIGE_DEVICE
        
        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        if ret != 0:
            raise Exception(f"Enum devices failed! ret=0x{ret:x}")

        if deviceList.nDeviceNum == 0:
            raise Exception("No Hikvision devices found!")

        # 2. 按序列号选择设备（为空取第一台），并记录机型/序列号供 UI 显示
        index = select_device_index(deviceList, self.serial_number)
        stDeviceList = ctypes.cast(deviceList.pDeviceInfo[index], ctypes.POINTER(MV_CC_DEVICE_INFO)).contents
        self.device_serial = read_device_serial(stDeviceList) or None
        self.device_model = read_device_model(stDeviceList) or None
        logger.info(f"Selected camera: serial={self.device_serial} model={self.device_model}")

        # 3. Create Handle
        self.handle = MvCamera()
        ret = self.handle.MV_CC_CreateHandle(stDeviceList)
        if ret != 0:
            raise Exception(f"Create handle failed! ret=0x{ret:x}")

        # 4. Open Device
        ret = self.handle.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise Exception(f"Open device failed! ret=0x{ret:x}")

        # 5. Get Payload Size
        stParam = MVCC_INTVALUE()
        memset(ctypes.byref(stParam), 0, ctypes.sizeof(MVCC_INTVALUE))
        ret = self.handle.MV_CC_GetIntValue("PayloadSize", stParam)
        if ret != 0:
            raise Exception(f"Get payload size failed! ret=0x{ret:x}")
        self.n_payload_size = stParam.nCurValue
        
        # 6. Start Grabbing
        ret = self.handle.MV_CC_StartGrabbing()
        if ret != 0:
            raise Exception(f"Start grabbing failed! ret=0x{ret:x}")

        self.b_is_connected = True
        self._frame_count = 0
        self._fatal_failure_count = 0
        # 默认连续模式（预览）+ 手动曝光（触发抓拍要求固定曝光）
        self.handle.MV_CC_SetEnumValueByString("TriggerMode", "Off")
        self.handle.MV_CC_SetEnumValueByString("ExposureAuto", "Off")
        logger.info("Hikvision Camera Connected (TriggerMode=Off, ExposureAuto=Off).")

    def disconnect(self):
        if self.handle is None:
            return

        try:
            if self.b_is_connected:
                # Stop Grabbing
                self.handle.MV_CC_StopGrabbing()
            # Close Device
            self.handle.MV_CC_CloseDevice()
            # Destroy Handle
            self.handle.MV_CC_DestroyHandle()
        except Exception as e:
            logger.warning(f"Disconnect cleanup error: {e}")
        finally:
            self.b_is_connected = False
            self.handle = None
            # Explicitly release all buffers to prevent memory leaks
            self._cleanup_buffers()
        logger.info("Hikvision Camera Disconnected.")

    def reconnect(self):
        """断线重连：清理旧句柄后重新连接。"""
        if self.handle is not None:
            try:
                self.disconnect()
            except Exception as e:
                logger.warning(f"Reconnect cleanup failed: {e}")
        self.connect()

    def _cleanup_buffers(self):
        """Explicitly release all allocated buffers and trigger GC."""
        self.convert_buf = None
        self.convert_buf_size = 0
        self._rgb_buffer = None
        self._rgb_buffer_shape = (0, 0, 3)
        self._last_width = 0
        self._last_height = 0
        self._frame_count = 0
        
        # Force garbage collection to release memory
        gc.collect()
        logger.debug("Camera buffers cleaned up and GC triggered.")

    def is_connected(self) -> bool:
        """Check if the camera is currently connected."""
        return self.b_is_connected

    def set_exposure(self, value):
        """设置曝光时间（微秒，固定值）。触发抓拍禁用 auto 以保证每张曝光一致。"""
        if not self.b_is_connected:
            return
        ret = self.handle.MV_CC_SetEnumValueByString("ExposureAuto", "Off")
        if ret != 0:
            logger.error(f"Set manual exposure failed! ret=0x{ret:x}")
            return
        ret = self.handle.MV_CC_SetFloatValue("ExposureTime", float(value))
        if ret != 0:
            logger.error(f"Set exposure time failed! ret=0x{ret:x}")

    def set_trigger_config(self, mode, source=None, activation=None, debouncer_time_us=None):
        """配置触发模式：preview / hardware / software_single / software_continuous。"""
        if not self.b_is_connected:
            return
        self._trigger_mode = mode
        if mode == "preview":
            self.handle.MV_CC_SetEnumValueByString("TriggerMode", "Off")
            logger.info("Trigger: preview (TriggerMode=Off 连续出图)")
        elif mode == "hardware":
            src = source or "Line0"
            self.handle.MV_CC_SetEnumValueByString("TriggerMode", "On")
            self.handle.MV_CC_SetEnumValueByString("TriggerSource", src)
            self.handle.MV_CC_SetEnumValueByString("TriggerActivation", activation or "RisingEdge")
            self.handle.MV_CC_SetEnumValueByString("LineSelector", src)  # 选 Line 再设防抖
            if debouncer_time_us is not None:
                ret = self.handle.MV_CC_SetFloatValue("LineDebouncerTime", float(debouncer_time_us))
                if ret != 0:
                    logger.error(f"Set LineDebouncerTime failed! ret=0x{ret:x}")
            logger.info(f"Trigger: hardware ({src}, {activation or 'RisingEdge'}, debounce={debouncer_time_us}us)")
        elif mode in ("software_single", "software_continuous"):
            self.handle.MV_CC_SetEnumValueByString("TriggerMode", "On")
            self.handle.MV_CC_SetEnumValueByString("TriggerSource", "Software")
            logger.info(f"Trigger: {mode} (Software source)")
        else:
            logger.warning(f"Unknown trigger mode: {mode}")

    def enable_software_trigger(self):
        """发一次软件触发（software_single / software_continuous 模式用）。
        SDK API: MV_CC_SetCommandValue('TriggerSoftware')（MvCameraControl_class.py:1245）。"""
        if not self.b_is_connected:
            return
        ret = self.handle.MV_CC_SetCommandValue("TriggerSoftware")
        if ret != 0:
            logger.error(f"Software trigger failed! ret=0x{ret:x}")

    def set_resolution(self, width: int, height: int):
        """改分辨率。改完重新获取 PayloadSize + 重建转换缓冲区；
        启动失败不自动 disconnect（避免状态更乱），抛异常让上层决定。"""
        if not self.b_is_connected:
            logger.warning("Cannot set resolution, camera is not connected.")
            return

        logger.info(f"Attempting to set resolution to {width}x{height}...")
        self.handle.MV_CC_StopGrabbing()  # 停流（忽略返回，继续尝试改宽高）

        ret_w = self.handle.MV_CC_SetIntValue("Width", width)
        ret_h = self.handle.MV_CC_SetIntValue("Height", height)
        if ret_w != 0 or ret_h != 0:
            logger.error(f"Set resolution failed: ret_w=0x{ret_w:x} ret_h=0x{ret_h:x}")

        ret_start = self.handle.MV_CC_StartGrabbing()
        if ret_start != 0:
            # 不自动 disconnect（b_is_connected/缓冲状态会更不可预期），抛异常让上层处理
            raise RuntimeError(f"分辨率切换后重启取流失败 ret=0x{ret_start:x}（建议断开重连相机）")

        # 成功：重新获取 PayloadSize + 重建转换缓冲区（尺寸可能变了）
        stParam = MVCC_INTVALUE()
        memset(ctypes.byref(stParam), 0, ctypes.sizeof(MVCC_INTVALUE))
        if self.handle.MV_CC_GetIntValue("PayloadSize", stParam) == 0:
            self.n_payload_size = stParam.nCurValue
        self._ensure_buffers(width, height)
        logger.info(f"Successfully set resolution to {width}x{height}, PayloadSize refreshed.")


    def set_timeout(self, timeout_ms: int):
        """
        Set the frame capture timeout.
        
        Args:
            timeout_ms: Timeout in milliseconds (50-5000)
        """
        self._timeout_ms = max(50, min(5000, timeout_ms))
        logger.info(f"Camera frame timeout set to {self._timeout_ms}ms")

    def _ensure_buffers(self, width: int, height: int) -> bool:
        """
        Ensure buffers are allocated for the given frame dimensions.
        Returns True if buffers were reallocated (resolution changed).
        """
        resolution_changed = (width != self._last_width or height != self._last_height)
        
        nConvertSize = width * height * 3
        
        # Reallocate ctypes buffer if needed
        if self.convert_buf_size < nConvertSize:
            self.convert_buf = (ctypes.c_ubyte * nConvertSize)()
            self.convert_buf_size = nConvertSize
            logger.info(f"Allocated convert buffer: {nConvertSize} bytes for {width}x{height}")
        
        # Reallocate numpy buffer if needed
        target_shape = (height, width, 3)
        if self._rgb_buffer is None or self._rgb_buffer_shape != target_shape:
            self._rgb_buffer = np.empty(target_shape, dtype=np.uint8)
            self._rgb_buffer_shape = target_shape
            logger.info(f"Allocated RGB buffer: {target_shape}")
        
        if resolution_changed:
            self._last_width = width
            self._last_height = height
            
        return resolution_changed

    def get_frame(self, timeout_ms: int | None = None) -> QImage | None:
        if not self.b_is_connected:
            return None

        stFrameInfo = MV_FRAME_OUT_INFO_EX()
        memset(ctypes.byref(stFrameInfo), 0, ctypes.sizeof(stFrameInfo))
        
        stOutFrame = MV_FRAME_OUT()
        memset(ctypes.byref(stOutFrame), 0, ctypes.sizeof(stOutFrame))

        # Use configurable timeout instead of fixed 1000ms
        # 触发模式可传入更长 timeout（阻塞等触发）；连续模式用默认
        timeout = timeout_ms if timeout_ms is not None else self._timeout_ms
        ret = self.handle.MV_CC_GetImageBuffer(stOutFrame, timeout)
        
        if ret == 0:
            # Success - reset failure counter
            self._consecutive_failures = 0
            self._fatal_failure_count = 0
            
            width = stOutFrame.stFrameInfo.nWidth
            height = stOutFrame.stFrameInfo.nHeight
            pixel_type = stOutFrame.stFrameInfo.enPixelType
            
            # Ensure buffers are ready (reuses existing if dimensions match)
            self._ensure_buffers(width, height)

            stConvertParam = MV_CC_PIXEL_CONVERT_PARAM()
            memset(ctypes.byref(stConvertParam), 0, ctypes.sizeof(stConvertParam))
            
            stConvertParam.nWidth = width
            stConvertParam.nHeight = height
            stConvertParam.pSrcData = stOutFrame.pBufAddr
            stConvertParam.nSrcDataLen = stOutFrame.stFrameInfo.nFrameLen
            stConvertParam.enSrcPixelType = pixel_type
            stConvertParam.enDstPixelType = PixelType_Gvsp_RGB8_Packed
            stConvertParam.pDstBuffer = ctypes.cast(self.convert_buf, ctypes.POINTER(ctypes.c_ubyte))
            stConvertParam.nDstBufferSize = self.convert_buf_size
            
            ret_conv = self.handle.MV_CC_ConvertPixelType(stConvertParam)
            
            # Always free the SDK buffer regardless of conversion result
            self.handle.MV_CC_FreeImageBuffer(stOutFrame)

            if ret_conv != 0:
                logger.error(f"Convert pixel type failed! ret=0x{ret_conv:x}")
                return None
            
            # Copy data into our reusable numpy buffer
            # This avoids creating a new numpy array each frame
            ctypes_array = np.ctypeslib.as_array(self.convert_buf)
            np.copyto(self._rgb_buffer, ctypes_array[:height*width*3].reshape((height, width, 3)))
            
            # Create QImage from our buffer
            # Note: .copy() is required because QImage doesn't own the buffer data
            # However, we're now reusing the source buffer, reducing allocations
            image = QImage(
                self._rgb_buffer.data,
                width, height,
                width * 3,
                QImage.Format_RGB888
            ).copy()
            
            # Increment frame counter and trigger periodic GC
            self._frame_count += 1
            if self._frame_count >= self.GC_TRIGGER_INTERVAL:
                self._frame_count = 0
                gc.collect()
                logger.debug("Periodic GC triggered after 100 frames")
            
            return image

        else:
            # Frame capture failed
            if is_fatal_frame_error(ret, self._trigger_mode):
                self._fatal_failure_count += 1
                if self._fatal_failure_count >= self.MAX_CONSECUTIVE_FATAL_FAILURES:
                    self.b_is_connected = False
                    logger.error(
                        f"相机疑似掉线（连续 {self._fatal_failure_count} 次致命错误 "
                        f"ret=0x{ret:x}），标记为未连接，等待自动重连。"
                    )
                    self._fatal_failure_count = 0
            else:
                # 超时/无图：触发模式下正常，重置计数避免误判掉线
                self._fatal_failure_count = 0
            
            # Log with different severity based on failure count
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    f"Camera: {self._consecutive_failures} consecutive frame failures! "
                    f"ret=0x{ret:x}. Check camera connection or adjust timeout."
                )
                # Reset counter to avoid spamming logs
                self._consecutive_failures = 0
            else:
                logger.debug(f"Get frame failed! ret=0x{ret:x} (failure #{self._consecutive_failures})")
            
            return None

