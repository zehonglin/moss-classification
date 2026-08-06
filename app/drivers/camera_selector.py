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
