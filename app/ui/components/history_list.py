"""HistoryList 历史列表组件（分页 + 选中暂停 + 异步缩略图）。

订阅 controller 分页查询（`search_records_paged`）渲染；运行时新记录
`append_live` —— 选中历史时只计 pending 不插入，并在筛选栏下方显示
"⏸ 列表已暂停刷新 · N 条新记录 · 返回实时后更新" 提示；点历史项 → 显示原图
（配合 Task 11 CameraView）。

布局（上→下）：
    筛选栏：[品级 ▾] [状态 ▾] [查询] stretch [↓ 导出记录]
    暂停提示（默认隐藏，append_live 命中选中态时显示）
    QListWidget#HistoryList （由 style.qss 命中选中/hover 样式）
    分页栏：[上一页] [下一页] stretch "第 n 页 · 共 m 页 · 合计 total"

样式：
    - QListWidget#HistoryList 由全局 style.qss 命中（白底 + 圆角 + 中性 slate 选中/hover）
    - HistoryItem 品级色字 + 描述词（A 良好 / B 中等 / C 较差 / D 不合格，
      色值取自 design_tokens，与 GradeBanner 同源）
    - 低置信（< threshold 且未纠错）→ ⚠ 橙色字 + "需复检" chip（仅置信度触发，与品级无关）
    - 已纠错 → 末尾绿色"已改X"角标
    - 质量异常（quality_status != 'ok'）→ "⚠ 图像质量不合格 · {翻译后原因}" + "质量异常" chip
      （原图正常入库，不用"拒采"措辞；原因经 REJECT_REASONS 翻译，与横幅一致）

异步缩略图：
    `_ThumbLoader(QThread)` 用 `QImageReader.setScaledSize` 直接读缩放图（省内存），
    `loaded(widget, pixmap)` 信号回主线程填 QPixmap。线程 run 完自动 quit，
    `finished → deleteLater` 兜底回收（避免测试里偶发 hang）。

 Signals:
    record_selected(object|None): 选中历史项的 record dict；clear_selection 时 emit None。
    page_change_requested(int): 点上一页/下一页 → 请求目标页码（page∓1）。
    filter_requested(dict): 点查询 → {"prediction": str|None, "quality_status": str|None}。
    export_requested(): 点"↓ 导出记录"。
"""
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImageReader, QPixmap
from shiboken6 import isValid as _shiboken_is_valid
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.design_tokens import GRADE_COLORS, GRADE_NAMES, REJECT_REASONS

# 品级 → 字色（向后兼容别名；取自 design_tokens 单一来源）
_GRADE_COLOR = GRADE_COLORS

# DB 行列序（与 get_recent_records / search_records_paged 对齐）
_ROW_KEYS = [
    "id",
    "timestamp",
    "image_path",
    "thumbnail_path",
    "prediction",
    "confidence",
    "corrected_label",
    "quality_status",
]

# 状态下拉 → quality_status 过滤值（"质量异常"含 rejected_blur/overexposed/underexposed 等，
# 过滤值仍用 'rejected' 前缀语义，由 DB 层匹配非 'ok' 记录）
_QMAP = {"全部状态": None, "正常": "ok", "质量异常": "rejected"}


class _ThumbLoader(QThread):
    """异步缩略图加载线程。

    用 `QImageReader.setScaledSize` 直接读取缩放后的图（避免大图全量 decode）。
    run 结束自动 quit；外层连 `finished → deleteLater` 回收线程对象。
    无论路径是否有效都会 emit `loaded`（无效路径/读取失败 → 空 QPixmap）。
    """

    loaded = Signal(object, object)  # (widget, QPixmap)

    def __init__(self, path, size, widget):
        super().__init__()
        self.path = path
        self.size = size
        self.widget = widget

    def run(self):
        pm = QPixmap()
        if self.path:
            reader = QImageReader(self.path)
            sz = reader.size()
            if sz.isValid():
                reader.setScaledSize(sz.scaled(self.size, self.size, Qt.KeepAspectRatio))
            img = reader.read()
            if not img.isNull():
                pm = QPixmap.fromImage(img)
        self.loaded.emit(self.widget, pm)


def _apply_thumb(widget, pm):
    """`_ThumbLoader.loaded` 信号回调：填进 QLabel（空 pixmap 不动）。

    守卫：widget 的 C++ 对象已被销毁时（翻页/筛选 `_list.clear()` 删旧 item 后，
    loader 线程仍可能回调到已删 QLabel）静默返回，避免
    `RuntimeError: Internal C++ object (QLabel) already deleted`。
    """
    if not pm.isNull() and _shiboken_is_valid(widget):
        widget._thumb.setPixmap(pm)


class HistoryItem(QWidget):
    """单条历史记录 widget：缩略图 + 品级色字（+描述词+置信度） + 时间 + 可选角标。

    状态色规则：
      - quality_status != 'ok'  → "⚠ 图像质量不合格 · {翻译后原因}" + "质量异常" chip
      - corrected_label 非空    → 用品级色字（不再标 ⚠ 低置信）+ 绿"已改X"角标
      - confidence < threshold 且未纠错 → ⚠ 橙色字 + "需复检" chip
      - 其他                     → 品级色字（A/B/C/D 各自色）
    """

    def __init__(self, rec, threshold=0.6, size=34):
        super().__init__()
        self._rec = rec
        # 持有活跃 loader 引用：避免 Python GC 回收正在运行的 QThread，
        # 也便于测试 wait() 等线程退出（防止 hang）。
        self._loaders = []

        h = QHBoxLayout(self)
        h.setContentsMargins(7, 5, 7, 5)
        h.setSpacing(8)

        # 缩略图（左；默认占位灰底圆角，loader 完成后填 QPixmap）
        self._thumb = QLabel()
        self._thumb.setFixedSize(size, size)
        self._thumb.setStyleSheet("background:#262626;border-radius:6px;")
        h.addWidget(self._thumb)

        # 中：品级/状态 + 时间
        info = QVBoxLayout()
        info.setSpacing(0)

        pred_label = self._build_pred_label(rec, threshold)
        info.addWidget(pred_label)

        tm = QLabel(self._format_time(rec.get("timestamp")))
        tm.setStyleSheet("color:#94a3b8;font-size:11px;")
        info.addWidget(tm)

        h.addLayout(info)
        h.addStretch()

        # 右侧角标（已纠错 / 需复检 / 质量异常）
        tag = self._build_tag(rec, threshold)
        if tag is not None:
            h.addWidget(tag)

        # 异步缩略图：thumbnail_path 优先，回退 image_path
        thumb_path = rec.get("thumbnail_path") or rec.get("image_path")
        if thumb_path:
            loader = _ThumbLoader(thumb_path, size, self)
            loader.loaded.connect(_apply_thumb)
            # run 完自动 quit；连 deleteLater 回收线程对象，避免测试偶发 hang。
            self._loaders.append(loader)
            loader.finished.connect(loader.deleteLater)
            loader.start()

    @staticmethod
    def _build_pred_label(rec, threshold):
        q = rec.get("quality_status") or "ok"
        if q != "ok":
            reason = REJECT_REASONS.get(q, q)
            lab = QLabel(f"⚠ 图像质量不合格 · {reason}")
            lab.setStyleSheet("color:#475569;font-weight:700;font-size:12.5px;")
            return lab

        grade = rec.get("prediction")
        grade_color = GRADE_COLORS.get(grade, "#94a3b8")
        conf = rec.get("confidence")
        corr = rec.get("corrected_label")
        # 低置信（未纠错）→ ⚠ 橙色；纠错过 → 用品级色字
        review = isinstance(conf, (int, float)) and conf < threshold and not corr
        prefix = "⚠ " if review else ""
        grade_txt = str(grade) if grade else "?"
        name_txt = GRADE_NAMES.get(str(grade), "")
        name_part = f' <span style="color:#64748b;font-weight:600;font-size:11.5px">{name_txt}</span>' if name_txt else ""
        conf_txt = f'  <span style="color:#64748b;font-weight:600;font-size:12px">{conf:.0%}</span>' if isinstance(conf, (int, float)) else ""
        lab = QLabel(prefix + grade_txt + name_part + conf_txt)
        lab.setStyleSheet(
            f"font-weight:800;font-size:13px;color:{'#c2410c' if review else grade_color};"
        )
        return lab

    @staticmethod
    def _build_tag(rec, threshold):
        """右侧角标：已纠错 > 需复检 > 质量异常（互斥优先级）。"""
        q = rec.get("quality_status") or "ok"
        corr = rec.get("corrected_label")
        conf = rec.get("confidence")

        if corr:
            tag = QLabel(f"已改{corr}")
            tag.setStyleSheet(
                "background:#dcfce7;color:#166534;border-radius:9px;"
                "padding:2px 7px;font-size:10px;font-weight:700;"
            )
            return tag

        if q != "ok":
            tag = QLabel("质量异常")
            tag.setStyleSheet(
                "background:#e2e8f0;color:#334155;border:1px solid #cbd5e1;"
                "border-radius:9px;padding:2px 7px;font-size:10px;font-weight:700;"
            )
            return tag

        review = isinstance(conf, (int, float)) and conf < threshold
        if review:
            tag = QLabel("⚠ 需复检")
            tag.setStyleSheet(
                "background:#fef3c7;color:#92400e;border:1px solid #fde68a;"
                "border-radius:9px;padding:2px 7px;font-size:10px;font-weight:700;"
            )
            return tag
        return None

    @staticmethod
    def _format_time(ts):
        if not ts:
            return ""
        try:
            return datetime.fromisoformat(str(ts)).strftime("%H:%M:%S")
        except Exception:
            return str(ts)


class HistoryList(QFrame):
    """历史列表容器（筛选栏 + 暂停提示 + 列表 + 分页栏）。

    外层用法：
        hl = HistoryList()
        controller.page_ready.connect(lambda rows, total, page, size: hl.set_page(...))
        controller.record_appended.connect(hl.append_live)
        hl.record_selected.connect(lambda rec: camera_view.show_history(rec))
        hl.page_change_requested.connect(controller.request_page)
        hl.filter_requested.connect(controller.apply_filter)
        hl.export_requested.connect(controller.export_with_images)
    """

    record_selected = Signal(object)
    page_change_requested = Signal(int)
    filter_requested = Signal(dict)
    export_requested = Signal()

    def __init__(self, threshold=0.6):
        super().__init__()
        self.setObjectName("HistoryFrame")
        self._threshold = threshold
        self._selected = None  # 当前选中的 QListWidgetItem；None=未选中（实时模式）
        self._pending = 0      # 选中态期间累计的新记录数
        self._page = 1

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # —— 筛选栏 ——
        fbar = QHBoxLayout()
        fbar.setContentsMargins(10, 7, 10, 7)
        fbar.setSpacing(6)

        f_title = QLabel("历史记录")
        f_title.setStyleSheet("font-weight:700;font-size:13px;margin-right:4px;")
        fbar.addWidget(f_title)

        self._f_pred = QComboBox()
        self._f_pred.addItems(["全部品级", "A", "B", "C", "D"])
        self._f_q = QComboBox()
        self._f_q.addItems(list(_QMAP.keys()))

        q_btn = QPushButton("查询")
        q_btn.setObjectName("FilterQuery")  # 样式归 style.qss（小号实心绿，勿复用放大的 ActionStart）
        q_btn.clicked.connect(self._emit_filter)

        self._exp = QPushButton("↓ 导出记录")
        self._exp.clicked.connect(self.export_requested)

        fbar.addWidget(self._f_pred)
        fbar.addWidget(self._f_q)
        fbar.addWidget(q_btn)
        fbar.addStretch()
        fbar.addWidget(self._exp)
        v.addLayout(fbar)

        # —— 暂停提示（默认隐藏） ——
        self._pause_hint = QLabel("")
        self._pause_hint.setStyleSheet(
            "background:#fffbeb;color:#92400e;padding:5px 10px;"
            "border-bottom:1px solid #fde68a;"
        )
        self._pause_hint.hide()
        v.addWidget(self._pause_hint)

        # —— 列表（与空状态页叠放：QStackedWidget 切换，不占列表 item 数） ——
        self._list = QListWidget()
        self._list.setObjectName("HistoryList")
        self._list.itemClicked.connect(self._on_item_clicked)

        self._empty = QLabel("暂无记录\n连接相机并开始运行后，识别结果会显示在这里")
        self._empty.setAlignment(Qt.AlignCenter)
        # 透明底：边框/白底由外层 QFrame#HistoryFrame 卡片统一提供（对齐 mockup）
        self._empty.setStyleSheet("color:#94a3b8;font-size:12px;line-height:1.8;")

        self._stack = QStackedWidget()
        self._stack.addWidget(self._list)    # index 0：列表页
        self._stack.addWidget(self._empty)   # index 1：空状态页
        self._stack.setCurrentWidget(self._list)
        v.addWidget(self._stack)

        # —— 分页栏 ——
        pbar = QHBoxLayout()
        pbar.setContentsMargins(10, 5, 10, 5)
        pbar.setSpacing(6)

        self._prev = QPushButton("上一页")
        self._next = QPushButton("下一页")
        self._prev.clicked.connect(lambda: self.page_change_requested.emit(self._page - 1))
        self._next.clicked.connect(lambda: self.page_change_requested.emit(self._page + 1))

        self._total_label = QLabel("")
        self._total_label.setStyleSheet("color:#64748b;font-size:11px;")

        pbar.addWidget(self._prev)
        pbar.addWidget(self._next)
        pbar.addStretch()
        pbar.addWidget(self._total_label)
        v.addLayout(pbar)

    # ---------- public API ----------

    def set_page(self, rows, total, page, page_size):
        """渲染一页数据。

        Args:
            rows: record dict 列表 或 DB tuple 行（由 _row_to_dict 归一）。
            total: 匹配筛选条件的总记录数（非整表）。
            page: 当前页码（1 起）。
            page_size: 每页大小（用于算总页数）。
        """
        self._page = page
        # 翻页/筛选语义：选中项可能不在新页 → 清选中；pending 是上一页缓冲 → 清掉。
        # 必须在 _list.clear() 之前重置，否则 _selected 会悬空指向已销毁的 item，
        # 导致 `_selected is not None` 恒真 → append_live 永远缓冲、实时流失效。
        self._selected = None
        self._pending = 0
        self._pause_hint.hide()
        # 显式回收 item widget：QListWidget.clear() 只删 QListWidgetItem，
        # item widget 不会随之销毁 → 每翻页泄漏 N 个 HistoryItem。
        for i in range(self._list.count()):
            w = self._list.itemWidget(self._list.item(i))
            if w is not None:
                w.deleteLater()
        self._list.clear()
        if not rows:
            # 空状态页：无匹配记录时给引导，而不是白屏（不占列表 item 数）
            self._stack.setCurrentWidget(self._empty)
        else:
            self._stack.setCurrentWidget(self._list)
        for r in rows:
            rec = r if isinstance(r, dict) else self._row_to_dict(r)
            self._append_item(rec, at_end=True)
        pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        self._total_label.setText(f"第 {page} 页 · 共 {pages} 页 · 合计 {total}")

    def append_live(self, rec):
        """运行时新记录追加。

        - 若选中态（_selected 非空）→ 只计 pending，显示暂停提示，不插入；
        - 否则插入到列表顶部（实时模式）。
        """
        if self._selected is not None:
            self._pending += 1
            self._pause_hint.setText(
                f"⏸ 列表已暂停刷新 · {self._pending} 条新记录 · 返回实时后更新"
            )
            self._pause_hint.show()
            return
        self._stack.setCurrentWidget(self._list)  # 新记录到达 → 离开空状态页
        self._append_item(rec, at_end=False)

    def clear_selection(self):
        """退出选中态：清选中、重置 pending、隐藏暂停提示、emit None。"""
        self._selected = None
        self._list.setCurrentItem(None)
        if self._pending:
            self._pending = 0
        self._pause_hint.hide()
        self.record_selected.emit(None)

    # ---------- internals ----------

    def _append_item(self, rec, at_end):
        it = QListWidgetItem()
        it.setData(Qt.UserRole, rec)
        w = HistoryItem(rec, self._threshold)
        it.setSizeHint(w.sizeHint())
        if at_end:
            self._list.addItem(it)
        else:
            self._list.insertItem(0, it)
        self._list.setItemWidget(it, w)

    def _on_item_clicked(self, item):
        """点列表项：未选中→选中并 emit record；点已选中项→clear_selection + emit None。"""
        if self._selected is item:
            self.clear_selection()
            return
        self._selected = item
        self.record_selected.emit(item.data(Qt.UserRole) if item else None)

    def _on_item_selected(self, rec):
        """测试用入口：直接置选中态（绕过 QListWidgetItem 构造）。

        生产代码不应调用；测试模拟"用户已选中某条历史"以验证 append_live 缓冲。
        """
        self._selected = rec  # 任意非 None 真值即可触发缓冲逻辑

    def _emit_filter(self):
        pred_txt = self._f_pred.currentText()
        pred = None if pred_txt == "全部品级" else pred_txt
        self.filter_requested.emit(
            {"prediction": pred, "quality_status": _QMAP[self._f_q.currentText()]}
        )

    @staticmethod
    def _row_to_dict(r):
        """DB tuple 行 → dict（按 _ROW_KEYS 列序；短 tuple 缺位补 None）。"""
        return {k: (r[i] if i < len(r) else None) for i, k in enumerate(_ROW_KEYS)}
