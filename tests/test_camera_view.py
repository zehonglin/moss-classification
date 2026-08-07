"""Task 11: CameraView 取景器组件。

QWidget 容器包 QLabel#CameraView（实时帧）+ 返回条 _retbar（看历史时显示）。
- set_live(qimage)：实时态刷帧；选中历史（_reviewing=True）时不刷。
- set_history(image_or_path, timestamp)：进选中态、显示原图 + 返回条。
- clear_history()：退出选中态、隐藏返回条、清画面。
- 信号：back_to_live（返回按钮 click）、request_fullscreen（_view doubleClicked）。
"""
import struct
import zlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from app.ui.components.camera_view import CameraView


# ---------- 测试用 QImage 工厂 ----------

def _make_qimage(size=4, color=0xFF0000):
    """构造一张合法 QImage（Format_RGB32，纯色）。"""
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(color)
    return img


def _png_bytes(size=4, color=(255, 0, 0)):
    """生成最小合法 PNG 字节（纯色 RGB）。"""
    width = height = size
    raw = bytearray()
    for _y in range(height):
        raw.append(0)  # filter byte
        raw.extend(color * width)

    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(bytes(raw))
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


# ---------- 初始态 ----------

def test_initial_state_not_reviewing():
    """构造后默认实时态（_reviewing=False），返回条隐藏。"""
    cv = CameraView()
    assert cv._reviewing is False
    assert cv._retbar.isHidden()


def test_view_object_name_hits_qss():
    """_view objectName=CameraView 命中 style.qss 取景器规则。"""
    cv = CameraView()
    assert cv._view.objectName() == "CameraView"


def test_initial_view_text_is_live_placeholder():
    """初始 _view 文案为"实时画面"。"""
    cv = CameraView()
    assert "实时画面" in cv._view.text()


# ---------- set_history：进选中态 + 显示返回条 ----------

def test_set_history_enters_reviewing():
    """set_history → _reviewing=True（无图也能进历史态）。"""
    cv = CameraView()
    cv.set_history(None, "2026-01-01 14:31:55")
    assert cv._reviewing is True


def test_set_history_shows_retbar():
    """set_history → 返回条不再隐藏（offscreen 下 isVisible 不可靠，用 isHidden）。"""
    cv = CameraView()
    assert cv._retbar.isHidden()
    cv.set_history(None, "2026-01-01 14:31:55")
    assert not cv._retbar.isHidden()


def test_set_history_info_contains_timestamp():
    """返回条信息含 timestamp。"""
    cv = CameraView()
    cv.set_history(None, "2026-01-01 14:31:55")
    assert "2026-01-01 14:31:55" in cv._ret_info.text()
    assert "查看历史" in cv._ret_info.text()
    assert "原图" in cv._ret_info.text()


def test_set_history_with_qimage_shows_pixmap():
    """set_history 接 QImage → 显示 scaled pixmap（非空）。"""
    cv = CameraView()
    cv.resize(200, 200)
    cv._view.resize(200, 200)
    cv.set_history(_make_qimage(8), "t")
    pm = cv._view.pixmap()
    assert pm is not None and not pm.isNull()


def test_set_history_with_path_loads_pixmap(tmp_path):
    """set_history 接 path 字符串 → QPixmap(path) 加载。"""
    img_path = tmp_path / "hist.png"
    img_path.write_bytes(_png_bytes())
    cv = CameraView()
    cv.resize(200, 200)
    cv._view.resize(200, 200)
    cv.set_history(str(img_path), "t")
    pm = cv._view.pixmap()
    assert pm is not None and not pm.isNull()


# ---------- set_live：reviewing 时不刷 ----------

def test_set_live_skipped_when_reviewing():
    """选中态时 set_live 直接 return（不覆盖历史原图）。

    用像素颜色验证：历史原图绿色，实时帧蓝色。set_live 不应把绿色覆盖成蓝色。
    """
    cv = CameraView()
    cv.resize(200, 200)
    cv._view.resize(200, 200)
    cv.set_history(_make_qimage(8, 0x00FF00), "t")  # 绿色历史原图
    assert not cv._view.pixmap().isNull()
    cv.set_live(_make_qimage(8, 0x0000FF))  # 蓝色实时帧 — 应被跳过
    pm_after = cv._view.pixmap()
    img = pm_after.toImage()
    pixel = img.pixelColor(1, 1)
    # 仍是绿色（历史原图），未被蓝色实时帧覆盖
    assert pixel.green() > 200
    assert pixel.blue() < 100


def test_set_live_updates_when_not_reviewing():
    """实时态 set_live → 显示新帧。"""
    cv = CameraView()
    cv.resize(200, 200)
    cv._view.resize(200, 200)
    assert cv._view.pixmap() is None or cv._view.pixmap().isNull()
    cv.set_live(_make_qimage(8))
    pm = cv._view.pixmap()
    assert pm is not None and not pm.isNull()


def test_set_live_none_clears_to_placeholder():
    """set_live(None) → 显示"实时画面"占位文案 + 清 pixmap。"""
    cv = CameraView()
    cv.resize(200, 200)
    cv._view.resize(200, 200)
    cv.set_live(_make_qimage(8))
    cv.set_live(None)
    assert "实时画面" in cv._view.text()
    assert cv._view.pixmap() is None or cv._view.pixmap().isNull()


# ---------- clear_history：退出选中态 ----------

def test_clear_history_exits_reviewing():
    cv = CameraView()
    cv.set_history(None, "t")
    assert cv._reviewing is True
    cv.clear_history()
    assert cv._reviewing is False


def test_clear_history_hides_retbar():
    cv = CameraView()
    cv.set_history(None, "t")
    assert not cv._retbar.isHidden()
    cv.clear_history()
    assert cv._retbar.isHidden()


def test_clear_history_clears_view_text():
    cv = CameraView()
    cv.set_history(None, "t")
    cv.clear_history()
    assert "实时画面" in cv._view.text()
    assert cv._view.pixmap() is None or cv._view.pixmap().isNull()


def test_clear_history_resumes_live_updates():
    """clear_history 后 set_live 恢复刷新。"""
    cv = CameraView()
    cv.resize(200, 200)
    cv._view.resize(200, 200)
    cv.set_history(None, "t")
    cv.clear_history()
    cv.set_live(_make_qimage(8))
    pm = cv._view.pixmap()
    assert pm is not None and not pm.isNull()


# ---------- 信号 ----------

def test_back_button_emits_back_to_live():
    """返回按钮 click → emit back_to_live。"""
    cv = CameraView()
    fired = []
    cv.back_to_live.connect(lambda: fired.append(1))
    cv.set_history(None, "t")
    cv._ret_back.click()
    assert fired == [1]


def test_view_double_click_emits_fullscreen():
    """_view doubleClicked → emit request_fullscreen。"""
    cv = CameraView()
    fired = []
    cv.request_fullscreen.connect(lambda: fired.append(1))
    cv._view.doubleClicked.emit()
    assert fired == [1]


# ---------- resizeEvent：返回条宽度跟随 ----------

def test_resize_event_updates_retbar_width():
    """resize → _retbar 宽度跟随 self.width()。

    Qt 文档：未显示 widget 的 resize() 不立即触发 resizeEvent —— 显式 invoke
    以测 resizeEvent 本身的布线（生产路径下 widget 会先 show 再被父布局 resize）。
    """
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent

    cv = CameraView()
    cv.resize(333, 200)  # 更新几何（self.width() → 333）
    cv.resizeEvent(QResizeEvent(QSize(333, 200), QSize(640, 480)))  # 显式触发 handler
    assert cv._retbar.width() == 333


# ---------- 组件结构 ----------

def test_camera_view_is_qwidget_container():
    """CameraView 是 QWidget 容器（包 QLabel _view，不是直接 QLabel）。"""
    from PySide6.QtWidgets import QLabel, QWidget
    cv = CameraView()
    assert isinstance(cv, QWidget)
    assert isinstance(cv._view, QLabel)
