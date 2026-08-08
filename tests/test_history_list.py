"""Task 10: HistoryList 历史列表组件。

订阅 controller 分页查询（search_records_paged）渲染；运行时新记录 append_live
（选中历史时只计 pending 不插入，显示暂停提示）；点历史项 → 显示原图。
"""
import struct
import zlib

from PySide6.QtCore import Qt

from app.ui.components.history_list import HistoryList, HistoryItem, _ThumbLoader


# ---------- 测试用 record 工厂 ----------

def _rec(i, pred="A", conf=0.9, corr=None, q="ok"):
    """构造一份 record dict（thumbnail_path=None 避免异步线程干扰测试）。"""
    return {
        "id": i,
        "timestamp": "2026-01-01T00:00:%02d" % (i % 60),
        "image_path": None,
        "thumbnail_path": None,
        "prediction": pred,
        "confidence": conf,
        "corrected_label": corr,
        "quality_status": q,
    }


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


# ---------- set_page：渲染行数 + 总数标签 ----------

def test_set_page_renders_page_size():
    hl = HistoryList()
    rows = [_rec(i) for i in range(5)]
    hl.set_page(rows, 12, 1, 5)
    assert hl._list.count() == 5


def test_set_page_total_label_contains_total():
    """总数标签含 total（"合计 12"）。"""
    hl = HistoryList()
    hl.set_page([_rec(i) for i in range(5)], 12, 1, 5)
    assert "12" in hl._total_label.text()
    assert "合计" in hl._total_label.text()


def test_set_page_total_label_shows_pages():
    """标签含 "第 n 页 · 共 m 页"。"""
    hl = HistoryList()
    hl.set_page([_rec(i) for i in range(5)], 12, 1, 5)
    text = hl._total_label.text()
    assert "第 1 页" in text
    assert "共 3 页" in text  # ceil(12/5)=3


def test_set_page_clears_previous_items():
    """再次 set_page 应清空旧行。"""
    hl = HistoryList()
    hl.set_page([_rec(i) for i in range(3)], 3, 1, 50)
    assert hl._list.count() == 3
    hl.set_page([_rec(i) for i in range(5)], 5, 1, 50)
    assert hl._list.count() == 5


def test_set_page_accepts_tuple_rows():
    """DB 返回 tuple 行也能渲染（_row_to_dict 归一）。"""
    hl = HistoryList()
    # (id, timestamp, image_path, thumbnail_path, prediction, confidence, corrected_label, quality_status)
    rows = [(1, "2026-01-01T00:00:00", None, None, "A", 0.9, None, "ok")]
    hl.set_page(rows, 1, 1, 50)
    assert hl._list.count() == 1
    item = hl._list.item(0)
    rec = item.data(Qt.UserRole)
    assert rec["prediction"] == "A"
    assert rec["confidence"] == 0.9


# ---------- append_live：选中态缓冲 ----------

def test_append_live_while_selected_buffers():
    """选中历史时 append_live 只计 pending，不插入。"""
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl._on_item_selected(_rec(1))  # 模拟选中（测试入口）
    hl.append_live(_rec(2))
    assert hl._list.count() == 1  # 未插入
    assert hl._pending == 1


def test_append_live_while_selected_shows_pause_hint():
    """选中时新记录 → 显示暂停提示。"""
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl._on_item_selected(_rec(1))
    assert hl._pause_hint.isHidden()
    hl.append_live(_rec(2))
    assert not hl._pause_hint.isHidden()
    assert "1" in hl._pause_hint.text()


def test_append_live_accumulates_pending():
    """多次 append_live 在选中态累计 pending。"""
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl._on_item_selected(_rec(1))
    hl.append_live(_rec(2))
    hl.append_live(_rec(3))
    hl.append_live(_rec(4))
    assert hl._pending == 3
    assert hl._list.count() == 1


def test_append_live_when_not_selected_inserts_at_top():
    """未选中时 append_live 在顶部插入新行。"""
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl.append_live(_rec(2))
    assert hl._list.count() == 2
    top_rec = hl._list.item(0).data(Qt.UserRole)
    assert top_rec["id"] == 2  # 新记录在顶部


# ---------- clear_selection：重置 + emit None ----------

def test_clear_selection_resets_pending():
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl._on_item_selected(_rec(1))
    hl.append_live(_rec(2))
    assert hl._pending == 1
    hl.clear_selection()
    assert hl._pending == 0


def test_clear_selection_hides_pause_hint():
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl._on_item_selected(_rec(1))
    hl.append_live(_rec(2))
    hl.clear_selection()
    assert hl._pause_hint.isHidden()


def test_clear_selection_emits_none():
    hl = HistoryList()
    received = []
    hl.record_selected.connect(lambda r: received.append(r))
    hl.clear_selection()
    assert received == [None]


# ---------- itemClicked：选中/取消选中 ----------

def test_item_click_emits_record():
    """点未选中项 → emit 对应 record dict。"""
    hl = HistoryList()
    received = []
    hl.record_selected.connect(lambda r: received.append(r))
    hl.set_page([_rec(1), _rec(2)], 2, 1, 50)
    hl._list.setCurrentRow(-1)  # 初始无选中
    hl._list.itemClicked.emit(hl._list.item(0))
    assert received and received[-1]["id"] == 1


def test_item_click_same_item_clears_selection():
    """点已选中项 → clear_selection + emit None。"""
    hl = HistoryList()
    received = []
    hl.record_selected.connect(lambda r: received.append(r))
    hl.set_page([_rec(1)], 1, 1, 50)
    item = hl._list.item(0)
    hl._list.itemClicked.emit(item)  # 第一次选中
    hl._list.itemClicked.emit(item)  # 再次点同一项 → 取消
    assert received[-1] is None


# ---------- 分页按钮：page_change_requested ----------

def test_next_button_emits_next_page():
    hl = HistoryList()
    pages = []
    hl.page_change_requested.connect(lambda p: pages.append(p))
    hl.set_page([_rec(i) for i in range(5)], 12, 1, 5)
    hl._next.click()
    assert pages == [2]


def test_prev_button_emits_prev_page():
    hl = HistoryList()
    pages = []
    hl.page_change_requested.connect(lambda p: pages.append(p))
    hl.set_page([_rec(i) for i in range(5)], 12, 3, 5)  # 第 3 页
    hl._prev.click()
    assert pages == [2]


# ---------- 筛选栏：filter_requested ----------

def test_filter_button_emits_filter_dict():
    """点查询 → emit {prediction, quality_status}（默认全部→None）。"""
    hl = HistoryList()
    received = []
    hl.filter_requested.connect(lambda d: received.append(d))
    hl._emit_filter()
    assert received == [{"prediction": None, "quality_status": None}]


def test_filter_with_prediction_selected():
    hl = HistoryList()
    received = []
    hl.filter_requested.connect(lambda d: received.append(d))
    hl._f_pred.setCurrentText("A")
    hl._emit_filter()
    assert received[-1]["prediction"] == "A"


def test_filter_with_rejected_status():
    hl = HistoryList()
    received = []
    hl.filter_requested.connect(lambda d: received.append(d))
    hl._f_q.setCurrentText("质量异常")
    hl._emit_filter()
    assert received[-1]["quality_status"] == "rejected"


def test_filter_with_ok_status():
    hl = HistoryList()
    received = []
    hl.filter_requested.connect(lambda d: received.append(d))
    hl._f_q.setCurrentText("正常")
    hl._emit_filter()
    assert received[-1]["quality_status"] == "ok"


# ---------- 导出按钮：export_requested ----------

def test_export_button_emits_export_requested():
    hl = HistoryList()
    received = []
    hl.export_requested.connect(lambda: received.append(True))
    hl._exp.click()
    assert received == [True]


def test_export_button_label():
    hl = HistoryList()
    assert "导出" in hl._exp.text()


# ---------- HistoryItem：状态色 ----------

def test_item_low_confidence_orange():
    """置信度 < threshold 且未纠错 → 橙色 ⚠ 文本（v3：#c2410c）。"""
    item = HistoryItem(_rec(1, conf=0.3), threshold=0.6)
    pred_label = item.layout().itemAt(1).layout().itemAt(0).widget()
    assert "#c2410c" in pred_label.styleSheet()
    assert "⚠" in pred_label.text()


def test_item_normal_confidence_grade_color():
    """置信度 ≥ threshold → 品级色字。"""
    item = HistoryItem(_rec(1, pred="A", conf=0.9), threshold=0.6)
    pred_label = item.layout().itemAt(1).layout().itemAt(0).widget()
    assert "#15803d" in pred_label.styleSheet()  # A 绿（700 深度）
    assert "⚠" not in pred_label.text()


def test_item_corrected_has_green_tag():
    """已纠错 → 绿色"已改X"角标。"""
    item = HistoryItem(_rec(1, corr="B"), threshold=0.6)
    h = item.layout()
    last = h.itemAt(h.count() - 1).widget()
    assert "已改B" in last.text()
    assert "#166534" in last.styleSheet()


def test_item_rejected_red_text():
    """quality_status != 'ok' → "⚠ 图像质量不合格 · {翻译后原因}"（正常入库语义，非拒采）。"""
    item = HistoryItem(_rec(1, q="rejected_blur"), threshold=0.6)
    pred_label = item.layout().itemAt(1).layout().itemAt(0).widget()
    assert "#475569" in pred_label.styleSheet()
    assert "图像质量不合格" in pred_label.text()
    assert "图像模糊" in pred_label.text()  # rejected_blur 已翻译，不显示原始枚举


def test_item_corrected_overrides_low_confidence_review():
    """已纠错（即使低置信）不再显示 ⚠ 低置信橙色。"""
    item = HistoryItem(_rec(1, conf=0.3, corr="B"), threshold=0.6)
    pred_label = item.layout().itemAt(1).layout().itemAt(0).widget()
    # corr 存在 → review=False → 用品级色字而非橙色
    assert "#c2410c" not in pred_label.styleSheet()


# ---------- _row_to_dict：tuple→dict 归一 ----------

def test_row_to_dict_full_tuple():
    """8 列 tuple → 完整 dict。"""
    hl = HistoryList()
    row = (1, "2026-01-01T00:00:00", "x.png", "t.png", "A", 0.9, None, "ok")
    d = hl._row_to_dict(row)
    assert d["id"] == 1
    assert d["image_path"] == "x.png"
    assert d["prediction"] == "A"
    assert d["quality_status"] == "ok"


def test_row_to_dict_short_tuple_safe():
    """短 tuple 不越界。"""
    hl = HistoryList()
    d = hl._row_to_dict((1, "2026-01-01T00:00:00"))
    assert d["id"] == 1
    assert d["prediction"] is None


# ---------- 异步缩略图：不 hang ----------

def _process_events_until(predicate, timeout_ms=3000, step_ms=50):
    """轮询 processEvents 直到 predicate() 为 True 或超时。

    替代 qtbot.waitSignal（项目未装 pytest-qt）。
    """
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    t = QElapsedTimer(); t.start()
    while not predicate():
        if t.hasExpired(timeout_ms):
            return False
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents()
    return True


def test_thumb_loader_loads_real_png(tmp_path):
    """_ThumbLoader 加载真实 PNG → loaded 信号回主线程填 QPixmap（不 hang）。"""
    from PySide6.QtWidgets import QLabel
    img_path = tmp_path / "t.png"
    img_path.write_bytes(_png_bytes())
    thumb = QLabel()
    captured = []
    loader = _ThumbLoader(str(img_path), 26, thumb)
    loader.loaded.connect(lambda w, pm: captured.append(pm))
    loader.start()
    ok = _process_events_until(lambda: len(captured) > 0 or loader.isFinished(), timeout_ms=3000)
    # 再 flush 一次让 queued connection 投递到位
    from PySide6.QtCore import QCoreApplication
    for _ in range(10):
        QCoreApplication.processEvents()
    assert ok
    assert captured, "loaded 信号未触发"
    assert not captured[0].isNull()
    loader.wait(2000)  # 确保线程彻底退出


def test_thumb_loader_missing_path_emits_empty_pixmap():
    """path 为空（None/""）→ loaded 仍 emit，pixmap 为空 isNull。"""
    from PySide6.QtWidgets import QLabel
    thumb = QLabel()
    captured = []
    loader = _ThumbLoader("", 26, thumb)
    loader.loaded.connect(lambda w, pm: captured.append(pm))
    loader.start()
    _process_events_until(lambda: loader.isFinished(), timeout_ms=3000)
    from PySide6.QtCore import QCoreApplication
    for _ in range(10):
        QCoreApplication.processEvents()
    assert captured
    assert captured[0].isNull()
    loader.wait(2000)  # 确保线程彻底退出


def test_item_with_thumbnail_starts_loader_no_hang(tmp_path):
    """HistoryItem 带 thumbnail_path 启动 _ThumbLoader，测试不卡。

    显式 wait() 所有活跃 loader 退出，防止 pytest 退出时 hang。
    """
    img_path = tmp_path / "thumb.png"
    img_path.write_bytes(_png_bytes())
    rec = _rec(1)
    rec["thumbnail_path"] = str(img_path)
    item = HistoryItem(rec, threshold=0.6)
    # wait 所有 loader 退出（带超时兜底，不卡死）
    for loader in item._loaders:
        loader.wait(3000)
    # 再 flush 一次让 queued finished/deleteLater 投递到位
    from PySide6.QtCore import QCoreApplication
    for _ in range(10):
        QCoreApplication.processEvents()
    assert item._rec["id"] == 1


# ---------- objectName / 容器结构 ----------

def test_list_has_historylist_object_name():
    """QListWidget objectName=HistoryList 命中 style.qss。"""
    hl = HistoryList()
    assert hl._list.objectName() == "HistoryList"


# ---------- set_page 翻页清选中（I1 回归） + 回收 widget（I2） ----------

def test_set_page_clears_selection_on_page_change():
    """I1: set_page 翻页清空 _selected（避免悬空指向已销毁 item）。"""
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl._on_item_selected(_rec(1))  # 进入选中态
    assert hl._selected is not None
    hl.set_page([_rec(i) for i in range(5)], 5, 2, 50)  # 翻页
    assert hl._selected is None
    assert hl._pending == 0
    assert hl._pause_hint.isHidden()


def test_set_page_clears_selection_then_append_live_inserts():
    """I1 回归：翻页清选中后 append_live 走实时插入而非永远缓冲。"""
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl._on_item_selected(_rec(1))  # 选中态
    hl.append_live(_rec(2))  # 缓冲
    assert hl._pending == 1
    hl.set_page([_rec(i) for i in range(3)], 3, 2, 50)  # 翻页清选中
    assert hl._selected is None
    before = hl._list.count()
    hl.append_live(_rec(9))  # 应直接插入而非缓冲
    assert hl._list.count() == before + 1
    assert hl._pending == 0


def test_set_page_releases_old_item_widgets():
    """I2: set_page 翻页显式 deleteLater 旧 item widget（避免内存泄漏）。"""
    from shiboken6 import isValid
    hl = HistoryList()
    hl.set_page([_rec(i) for i in range(3)], 3, 1, 50)
    old_widgets = [hl._list.itemWidget(hl._list.item(i)) for i in range(3)]
    assert all(isValid(w) for w in old_widgets)
    hl.set_page([_rec(i) for i in range(2)], 2, 2, 50)  # 翻页
    # flush DeferredDelete（deleteLater 投递的事件需 sendPostedEvents 显式处理）
    from PySide6.QtCore import QCoreApplication, QEvent
    for _ in range(10):
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    # 旧 widget 的 C++ 对象应被回收
    assert all(not isValid(w) for w in old_widgets)


# ---------- _apply_thumb widget 销毁守卫（C1 回归） ----------

def test_apply_thumb_silent_on_deleted_widget():
    """C1: widget C++ 对象已销毁时 _apply_thumb 静默返回，不抛 RuntimeError。

    复现崩溃路径：翻页/筛选 `_list.clear()` 删旧 item/widget → loader 线程仍在跑 →
    回调 `_apply_thumb(widget, pm)` 填已删 QLabel → `RuntimeError: Internal C++
    object (QLabel) already deleted`。守卫 shiboken.isValid 应阻断此路径。
    """
    from PySide6.QtCore import QCoreApplication, QEvent, Qt as _Qt
    from PySide6.QtGui import QPixmap
    from shiboken6 import isValid
    from app.ui.components.history_list import _apply_thumb

    item = HistoryItem(_rec(1), threshold=0.6)  # 无 thumbnail_path → 不启 loader
    pm = QPixmap(10, 10)
    pm.fill(_Qt.red)

    # 健康路径：widget 存活时正常填 pixmap
    _apply_thumb(item, pm)

    # 销毁 widget C++ 对象（flush DeferredDelete）
    item.deleteLater()
    for _ in range(10):
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(item), "setup 失败：widget C++ 对象未销毁"

    # 关键断言：widget 已销毁 → 静默返回，不抛 RuntimeError
    _apply_thumb(item, pm)


def test_thumb_loader_callback_survives_page_clear(tmp_path):
    """C1 集成：带缩略图的 HistoryItem 启 loader → set_page 清掉它 →
    loader 线程回调时不应崩 RuntimeError。

    用真实 loader 路径 + 翻页 clear，验证 _apply_thumb 守卫端到端有效。
    """
    from PySide6.QtCore import QCoreApplication
    img_path = tmp_path / "thumb.png"
    img_path.write_bytes(_png_bytes())
    rec = _rec(1)
    rec["thumbnail_path"] = str(img_path)

    hl = HistoryList()
    hl.set_page([rec], 1, 1, 50)  # 渲染含缩略图的 item（启动 loader）
    item_widget = hl._list.itemWidget(hl._list.item(0))
    loaders = list(item_widget._loaders)

    # 翻页：set_page 会 deleteLater 旧 item widget + _list.clear()
    hl.set_page([_rec(i) for i in range(3)], 3, 2, 50)

    # 等 loader 线程跑完 + flush queued 信号（_apply_thumb 此时被调用）
    for l in loaders:
        l.wait(3000)
    for _ in range(20):
        QCoreApplication.processEvents()
    # 走到这里没抛 RuntimeError 即通过
    assert hl._list.count() == 3
