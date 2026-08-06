"""相机枚举与序列号选择工具（不依赖海康 SDK 类型，便于单元测试）。"""


def _unwrap(info):
    """ctypes 指针 → contents；普通对象原样返回。"""
    if hasattr(info, "contents"):
        try:
            return info.contents
        except Exception:
            return info
    return info


def _read_string(raw) -> str:
    """c_ubyte/c_char 数组或 bytes → 去掉结尾 \x00 的字符串。"""
    if raw is None:
        return ""
    try:
        if isinstance(raw, bytes):
            return raw.split(b"\x00")[0].decode("ascii", "ignore")
        return bytes(raw).split(b"\x00")[0].decode("ascii", "ignore")
    except Exception:
        return ""


def read_device_serial(device_info) -> str:
    """从 SDK 设备信息对象读取序列号（GigE/USB3）。"""
    info = _unwrap(device_info)
    special = getattr(info, "SpecialInfo", None)
    if special is None:
        return ""
    for attr in ("stGigEInfo", "stUsb3VInfo"):
        sub = getattr(special, attr, None)
        if sub is None:
            continue
        serial = _read_string(getattr(sub, "chSerialNumber", None))
        if serial:
            return serial
    return ""


def read_device_model(device_info) -> str:
    """读取相机型号名称（GigE/USB3）。"""
    info = _unwrap(device_info)
    special = getattr(info, "SpecialInfo", None)
    if special is None:
        return ""
    for attr in ("stGigEInfo", "stUsb3VInfo"):
        sub = getattr(special, attr, None)
        if sub is None:
            continue
        model = _read_string(getattr(sub, "chModelName", None))
        if model:
            return model
    return ""


def select_device_index(device_list, serial_number: str) -> int:
    """按序列号选择设备索引；serial_number 为空取第一台。未匹配抛 RuntimeError。"""
    n = getattr(device_list, "nDeviceNum", 0)
    if n <= 0:
        raise RuntimeError("未枚举到任何相机设备")
    if not serial_number:
        return 0
    for i in range(n):
        info = device_list.pDeviceInfo[i]
        if read_device_serial(info) == serial_number:
            return i
    raise RuntimeError(f"未找到序列号为 {serial_number} 的相机（共枚举 {n} 台）")


# 可视为物理掉线的 SDK 错误码：设备无响应/句柄失效/调用顺序错/设备忙(网络断开)/USB 读错误
FATAL_FRAME_ERROR_CODES = {
    0x80000000,  # MV_E_HANDLE
    0x80000003,  # MV_E_CALLORDER
    0x80000008,  # MV_E_PRECONDITION（运行环境已变化）
    0x8000001A,  # MV_E_NORESPONSE（设备无响应）
    0x80000204,  # MV_E_BUSY（设备忙，或网络断开）
    0x80000300,  # MV_E_USB_READ（读 USB 出错）
}


def is_fatal_frame_error(ret: int, trigger_mode: str) -> bool:
    """判断取帧错误是否代表物理掉线。

    触发模式下"超时无图"是正常现象（等待光电触发），不计入掉线；
    连续出图（preview）模式下任何取帧失败都值得警惕。
    """
    if ret == 0:
        return False
    if trigger_mode in ("hardware", "software_single", "software_continuous"):
        return ret in FATAL_FRAME_ERROR_CODES
    return True
