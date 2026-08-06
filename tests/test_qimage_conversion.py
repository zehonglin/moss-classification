"""QImage → PIL/numpy 转换测试。

覆盖 bytesPerLine 行尾对齐（宽度非 4 倍数）场景，防止 reshape 错位或崩溃。
"""

from PySide6.QtGui import QColor, QImage

from app.controllers.system_controller import _qimage_to_pil
from app.services.model_service import ModelService


def _make_image(width=130, height=90):
    """构造带行标记的测试图：每行 (0, y) 像素灰度 = y % 256。"""
    q = QImage(width, height, QImage.Format.Format_RGB888)
    for y in range(height):
        v = y % 256
        q.setPixelColor(0, y, QColor(v, v, v))
    return q


def test_qimage_to_pil_handles_padded_bytes_per_line():
    q = _make_image()
    pil = _qimage_to_pil(q)
    assert pil.size == (130, 90)
    for y in (0, 44, 89):
        v = y % 256
        assert pil.getpixel((0, y)) == (v, v, v)


def test_qimage_to_hwc_uint8_handles_padded_bytes_per_line():
    q = _make_image()
    arr = ModelService._qimage_to_hwc_uint8(q)
    assert arr.shape == (90, 130, 3)
    for y in (0, 44, 89):
        v = y % 256
        assert tuple(arr[y, 0]) == (v, v, v)
