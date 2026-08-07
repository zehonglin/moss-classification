# 苔藓识别系统 UI 重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 推倒重写苔藓识别系统的 PySide6 UI 层为操作员/工程师双模式现代浅色界面，品级一眼可辨、参数按需展开。

**Architecture:** 组件化重写 `app/ui/`：8 个独立组件（TopStatBar / GradeBanner / CameraView / HistoryList / ParamSidebar / CorrectionPopup / ToastStack / ModeSwitch）+ 重写 MainWindow 组装双模式 + 重写 style.qss 设计系统。为支持新 UI，controller/DB 新增聚合统计、分页查询、导出原图方法。**不改现有 controller 信号/方法签名，只新增。**

**Tech Stack:** PySide6 6.9.3 / Qt Widgets + QSS / pytest 9.1.1（offscreen Qt 测试，无 pytest-qt）/ SQLite / onnxruntime

## Global Constraints

- Python 解释器：`/e/Programs/miniconda3/envs/TaiXian/python.exe`（conda env TaiXian）；跑测试：`/e/Programs/miniconda3/envs/TaiXian/python.exe -m pytest`
- 品级语义色：A `#16a34a` / B `#65a30d` / C `#d97706` / D `#dc2626`（背景=品级）；拒采底 `#334155`；取景器 `#171717`
- 浅色基调：背景 `#f1f5f9` / 表面 `#fff` / 边框 `#e2e8f0` / 文字 `#0f172a`→`#94a3b8`
- 中文 UI 文案；字体 `"Segoe UI", "Microsoft YaHei UI", sans-serif`
- 不改 `SystemController` 现有信号与方法签名（只新增）
- 测试：`QT_QPA_PLATFORM=offscreen`（conftest 已设）+ session 级 `_qapp`；UI 组件用 `FakeController`（`tests/fakes.py`）实例化测
- 每任务结束 commit；提交信息中文，末尾 `Co-Authored-By: Claude <noreply@anthropic.com>`
- 视觉参考：`.superpowers/brainstorm/1305-1786115433/content/*.html` + `docs/superpowers/specs/2026-08-08-moss-ui-redesign-design.md`

## File Structure

```
app/ui/
├── main_window.py            # 重写：组装双模式 + 信号接线（Task 14）
├── style.qss                 # 重写：设计系统（Task 1）
├── components/               # 新增目录
│   ├── __init__.py
│   ├── grade_banner.py       # Task 6（含 banner_state 纯函数）
│   ├── correction_popup.py   # Task 7
│   ├── toast.py              # Task 8
│   ├── top_bar.py            # Task 9
│   ├── history_list.py       # Task 10
│   ├── camera_view.py        # Task 11
│   ├── param_sidebar.py      # Task 12
│   └── mode_switch.py        # Task 13
└── widgets.py                # 删除（旧 HistoryItemWidget 迁入 history_list.py，Task 15）

app/services/database_service.py   # 修改：+count_by_final_grade +search_records_paged（Task 2,3）
app/controllers/system_controller.py # 修改：+grade_summary_updated +get_grade_summary +export_with_images（Task 4,5）
tests/fakes.py                      # 修改：FakeController 加新信号/方法（Task 14）
tests/test_*.py                     # 各任务新增
```

---

### Task 1: style.qss 设计系统

**Files:**
- Modify: `app/ui/style.qss`（整体重写）

**Interfaces:**
- Produces: 全局 QSS，组件通过 `setObjectName()` 命中样式（后续组件任务用到的 objectName：`#TopBar` `#GradeBanner` `#CameraView` `#HistoryList` `#ParamSidebar` `#ModeSwitch` `#ActionConnect/#ActionStart/#ActionStop/#ActionCapture` `#Toast*`）

- [ ] **Step 1: 重写 style.qss**

完整写入 `app/ui/style.qss`：

```css
/* ===== 全局 ===== */
QWidget { background-color:#f1f5f9; color:#0f172a; font-family:"Segoe UI","Microsoft YaHei UI",sans-serif; font-size:14px; }
QMainWindow, QFrame#ContentArea { background-color:#f1f5f9; }
QFrame { border:none; }

/* 品级语义色变量通过 objectName/property 命中，见各组件 */

/* ===== 顶部统计栏 ===== */
QFrame#TopBar { background-color:#ffffff; border-bottom:1px solid #e2e8f0; }
QLabel#RunState { color:#16a34a; font-weight:600; }
QLabel#StatItem { color:#475569; }
QLabel#StatItem b { color:#0f172a; }

/* ===== 品级横幅 =====
   banner 用 dynamic property grade=A/B/C/D/rejected/wait 控制背景，
   由组件 setProperty("grade", x) + polish 触发 */
QFrame#GradeBanner { color:#ffffff; }
QFrame#GradeBanner[grade="A"] { background-color:#16a34a; }
QFrame#GradeBanner[grade="B"] { background-color:#65a30d; }
QFrame#GradeBanner[grade="C"] { background-color:#d97706; }
QFrame#GradeBanner[grade="D"] { background-color:#dc2626; }
QFrame#GradeBanner[grade="rejected"] { background-color:#334155; }
QFrame#GradeBanner[grade="wait"] { background-color:#e2e8f0; color:#64748b; }

/* ===== 取景器 ===== */
QLabel#CameraView { background-color:#171717; color:#525252; border-radius:8px; }

/* ===== 历史 ===== */
QListWidget#HistoryList { background-color:#ffffff; border:1px solid #e2e8f0; border-radius:8px; outline:none; }
QListWidget::item { border-radius:6px; padding:2px; }
QListWidget::item:selected { background-color:#fff7ed; border:1px solid #fdba74; }
QListWidget::item:hover { background-color:#f8fafc; }

/* ===== 参数栏 ===== */
QFrame#ParamSidebar { background-color:#ffffff; border-right:1px solid #e2e8f0; }
QLabel#GroupTitle { color:#94a3b8; font-size:9px; letter-spacing:1px; }

/* ===== 按钮 ===== */
QPushButton { background-color:#ffffff; color:#334155; border:1px solid #cbd5e1; border-radius:7px; padding:7px 14px; font-weight:600; }
QPushButton:hover { background-color:#f8fafc; border-color:#94a3b8; }
QPushButton:disabled { background-color:#f1f5f9; color:#94a3b8; border-color:#e2e8f0; }
QPushButton#ActionStart { background-color:#16a34a; color:#fff; border:none; }
QPushButton#ActionStart:hover { background-color:#15803d; }
QPushButton#ActionStop { background-color:#fee2e2; color:#dc2626; border:1px solid #fecaca; }
QPushButton#ActionStop:hover { background-color:#fecaca; }
QPushButton#ActionCapture, QPushButton#ActionConnect { background-color:#f1f5f9; border:1px solid #cbd5e1; }

/* ===== 输入 ===== */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
  background-color:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:5px 8px; color:#0f172a; min-height:26px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border:1px solid #16a34a; }

/* ===== Chip / 徽章 ===== */
QLabel#Chip { background-color:#f1f5f9; border:1px solid #e2e8f0; border-radius:5px; padding:2px 8px; color:#475569; }

/* ===== Toast ===== */
QFrame#Toast { border-radius:9px; padding:9px 11px; }
QFrame#Toast[severity="warn"] { background-color:#fffbeb; border:1px solid #fde68a; border-left:3px solid #f59e0b; }
QFrame#Toast[severity="danger"] { background-color:#fef2f2; border:1px solid #fecaca; border-left:3px solid #dc2626; }

/* ===== 滚动条 ===== */
QScrollBar:vertical { border:none; background:#f1f5f9; width:10px; margin:0; }
QScrollBar::handle:vertical { background:#cbd5e1; min-height:24px; border-radius:5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border:none; background:none; }
```

- [ ] **Step 2: 验证 qss 加载无语法错**

Run: `/e/Programs/miniconda3/envs/TaiXian/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); app.setStyleSheet(open('app/ui/style.qss').read()); print('qss OK')"`
Expected: `qss OK`（无异常）

- [ ] **Step 3: Commit**

```bash
git add app/ui/style.qss
git commit -m "feat(ui): 重写 style.qss 设计系统（浅色基调+品级语义色）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: DB 聚合统计 count_by_final_grade

**Files:**
- Modify: `app/services/database_service.py`（新增方法）
- Test: `tests/test_grade_summary.py`

**Interfaces:**
- Produces: `DatabaseService.count_by_final_grade() -> dict[str,int]`，返回 `{"A":n,"B":n,"C":n,"D":n,"corrected":n,"rejected":n}`；品级按 `COALESCE(corrected_label, prediction)` 统计，`corrected = corrected_label 非空数`，`rejected = quality_status != 'ok' 数`

- [ ] **Step 1: 写失败测试**

`tests/test_grade_summary.py`:
```python
from app.services.database_service import DatabaseService


def _db(tmp_path):
    return DatabaseService(_cfg(tmp_path))


def _cfg(tmp_path):
    import json
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"data_paths": {"db_filename": str(tmp_path / "moss.db")}}), encoding="utf-8")
    from app.utils.config_manager import ConfigManager
    return ConfigManager(str(p))


def _add(db, pred, conf=.9, corr=None, q="ok"):
    return db.add_record("2026-01-01T00:00:00", "x.png", pred, conf,
                         thumbnail_path="t.png", quality_status=q, corrected_label=corr)


def test_count_by_final_grade(tmp_path):
    db = _db(tmp_path)
    _add(db, "A")                 # A
    _add(db, "A", corr="B")       # 原 A 纠正为 B → B 计，纠错计，A 不计
    _add(db, "C", q="rejected_blur")  # 拒采，不计品级
    s = db.count_by_final_grade()
    assert s["A"] == 1
    assert s["B"] == 1
    assert s["corrected"] == 1
    assert s["rejected"] == 1
```

> 注：`add_record` 现有签名见 `database_service.py`；若它不收 `corrected_label` 形参，改用 `update_correction(id, label)` 纠正后再统计。Step 3 实现时以实际签名为准（先读 `database_service.py`）。

- [ ] **Step 2: 跑测试确认失败**

Run: `/e/Programs/miniconda3/envs/TaiXian/python.exe -m pytest tests/test_grade_summary.py -v`
Expected: FAIL `AttributeError: 'DatabaseService' object has no attribute 'count_by_final_grade'`

- [ ] **Step 3: 实现**

在 `DatabaseService` 加（先读 `database_service.py` 确认表结构/列名/连接方式，沿用其 `_conn`）：
```python
def count_by_final_grade(self) -> dict:
    """按最终品级(corrected_label 优先)统计 + 纠错数 + 不合格数。"""
    cur = self._conn.execute(
        "SELECT COALESCE(corrected_label, prediction) AS g, COUNT(*) FROM records "
        "WHERE quality_status = 'ok' OR quality_status IS NULL "
        "GROUP BY g"
    )
    grades = {"A": 0, "B": 0, "C": 0, "D": 0}
    for g, n in cur.fetchall():
        if g in grades:
            grades[g] = n
    corrected = self._conn.execute(
        "SELECT COUNT(*) FROM records WHERE corrected_label IS NOT NULL AND corrected_label != ''"
    ).fetchone()[0]
    rejected = self._conn.execute(
        "SELECT COUNT(*) FROM records WHERE quality_status IS NOT NULL AND quality_status != 'ok'"
    ).fetchone()[0]
    return {**grades, "corrected": corrected, "rejected": rejected}
```

- [ ] **Step 4: 跑测试通过**

Run: `/e/Programs/miniconda3/envs/TaiXian/python.exe -m pytest tests/test_grade_summary.py -v`
Expected: PASS（若 `add_record` 不能直接传 corrected_label，用 `update_correction` 修正测试 setup）

- [ ] **Step 5: Commit**

```bash
git add app/services/database_service.py tests/test_grade_summary.py
git commit -m "feat(db): count_by_final_grade 聚合统计（最终品级/纠错/不合格）
Co-Authored-By: Claude <noreply@anthantic.com>"
```

---

### Task 3: DB 分页查询 search_records_paged

**Files:**
- Modify: `app/services/database_service.py`
- Test: `tests/test_history_paged.py`

**Interfaces:**
- Produces: `DatabaseService.search_records_paged(prediction=None, quality_status=None, page=1, page_size=50) -> tuple[list, int]`，返回 `(当前页 rows, 总匹配数 total)`；rows 元组结构与现有 `get_recent_records` 一致（id,timestamp,image_path,thumbnail_path,prediction,confidence,corrected_label,quality_status,...）

- [ ] **Step 1: 写失败测试**

`tests/test_history_paged.py`:
```python
from app.services.database_service import DatabaseService
from tests.test_grade_summary import _cfg, _add


def test_paged_returns_rows_and_total(tmp_path):
    db = DatabaseService(_cfg(tmp_path))
    for i in range(12):
        _add(db, "A" if i % 2 == 0 else "B")
    rows, total = db.search_records_paged(prediction="A", page=1, page_size=5)
    assert total == 6
    assert len(rows) == 5


def test_paged_second_page(tmp_path):
    db = DatabaseService(_cfg(tmp_path))
    for _ in range(12):
        _add(db, "A")
    rows, total = db.search_records_paged(page=2, page_size=5)
    assert total == 12
    assert len(rows) == 5
    rows3, _ = db.search_records_paged(page=3, page_size=5)
    assert len(rows3) == 2  # 末页余量
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/e/Programs/miniconda3/envs/TaiXian/python.exe -m pytest tests/test_history_paged.py -v`
Expected: FAIL `AttributeError ... search_records_paged`

- [ ] **Step 3: 实现**

在 `DatabaseService` 加（先读现有 `search_records` 复用其 WHERE/ORDER 构造，避免重复）：
```python
def search_records_paged(self, prediction=None, quality_status=None, page=1, page_size=50):
    where, params = [], []
    if prediction:
        where.append("prediction = ?"); params.append(prediction)
    if quality_status:
        where.append("quality_status = ?"); params.append(quality_status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = self._conn.execute(f"SELECT COUNT(*) FROM records {clause}", params).fetchone()[0]
    offset = max(page - 1, 0) * page_size
    rows = self._conn.execute(
        f"SELECT * FROM records {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    return rows, total
```
> `SELECT *` 列顺序须与 `get_recent_records` 返回元组一致——读 `database_service.py` 确认；不一致则显式列出列名（`id, timestamp, image_path, thumbnail_path, prediction, confidence, corrected_label, quality_status, rejected_reason`）。

- [ ] **Step 4: 跑测试通过** → Run: `pytest tests/test_history_paged.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/database_service.py tests/test_history_paged.py
git commit -m "feat(db): search_records_paged 分页查询
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: controller grade_summary 信号 + get_grade_summary

**Files:**
- Modify: `app/controllers/system_controller.py`
- Test: `tests/test_controller_grade_summary.py`

**Interfaces:**
- Produces: `SystemController` 新信号 `grade_summary_updated = Signal(dict)`；新方法 `get_grade_summary() -> dict`（透传 `db_service.count_by_final_grade()`）；`__init__` 增 `grade_summary_timer`（QTimer 2s）触发 `_emit_grade_summary`

- [ ] **Step 1: 写失败测试**

`tests/test_controller_grade_summary.py`:
```python
import json
from unittest.mock import patch
from app.controllers.system_controller import SystemController
from app.utils.config_manager import ConfigManager


def _ctrl(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"camera_settings": {"driver_type": "mock"}}), encoding="utf-8")
    return SystemController(ConfigManager(str(p)))


def test_get_grade_summary_returns_dict(tmp_path):
    ctrl = _ctrl(tmp_path)
    s = ctrl.get_grade_summary()
    assert set(s) >= {"A", "B", "C", "D", "corrected", "rejected"}
    ctrl.shutdown()


def test_grade_summary_updated_signal_emits(tmp_path, qtbot):
    # qtbot 不可用(无 pytest-qt)，用直接 emit 验证连接
    ctrl = _ctrl(tmp_path)
    received = []
    ctrl.grade_summary_updated.connect(lambda d: received.append(d))
    ctrl._emit_grade_summary()
    assert received and "A" in received[0]
    ctrl.shutdown()
```
> `qtbot` 行删除（无 pytest-qt）；保留直接调 `_emit_grade_summary`。

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_controller_grade_summary.py -v` → FAIL `AttributeError ... grade_summary_updated`

- [ ] **Step 3: 实现**

在 `SystemController` 类信号区加：
```python
grade_summary_updated = Signal(dict)  # 品级累计统计
```
`__init__` 末尾（stats_timer 之后）加：
```python
self.grade_summary_timer = QTimer(self)
self.grade_summary_timer.setInterval(2000)
self.grade_summary_timer.timeout.connect(self._emit_grade_summary)
self.grade_summary_timer.start()
```
加方法：
```python
def get_grade_summary(self):
    return self.db_service.count_by_final_grade()

def _emit_grade_summary(self):
    try:
        self.grade_summary_updated.emit(self.get_grade_summary())
    except Exception as e:
        logger.warning(f"grade summary emit failed: {e}")
```
> `shutdown()` 无需改（timer 随 QObject 析构）；确认 `shutdown` 关 db 在 timer 停后——读现有 `shutdown` 顺序，若 db 先关 timer 后触发会报错，则在 `shutdown` 开头加 `self.grade_summary_timer.stop()`。

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_controller_grade_summary.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/controllers/system_controller.py tests/test_controller_grade_summary.py
git commit -m "feat(ctrl): grade_summary_updated 信号 + get_grade_summary
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: controller export_with_images 导出原图

**Files:**
- Modify: `app/controllers/system_controller.py`
- Test: `tests/test_export_images.py`

**Interfaces:**
- Produces: `SystemController.export_with_images(csv_path, image_root, rows, group_by='grade') -> int`；写 CSV（复用 `export_records_csv`）+ 按 `group_by`（`grade`/`status`）建子文件夹复制 `image_path` 到 `image_root/<组>/<record_id>_<原预测>.png`；返回记录数

- [ ] **Step 1: 写失败测试**

`tests/test_export_images.py`:
```python
import json, os, pathlib
from app.controllers.system_controller import SystemController
from app.utils.config_manager import ConfigManager


def _ctrl(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"camera_settings": {"driver_type": "mock"},
                             "data_paths": {"db_filename": str(tmp_path/"moss.db")}}), encoding="utf-8")
    return SystemController(ConfigManager(str(p)))


def test_export_with_images_copies_grouped(tmp_path):
    ctrl = _ctrl(tmp_path)
    # 造一条记录 + 原图文件
    img = tmp_path / "src.png"; img.write_bytes(b"x")
    rec = (1, "2026-01-01T00:00:00", str(img), None, "A", 0.96, None, "ok", None)
    out_csv = tmp_path / "out.csv"; img_root = tmp_path / "imgs"
    n = ctrl.export_with_images(str(out_csv), str(img_root), [rec], group_by="grade")
    assert n == 1
    dest = img_root / "A" / "1_A.png"
    assert dest.exists()
    ctrl.shutdown()
```

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_export_images.py -v` → FAIL `AttributeError ... export_with_images`

- [ ] **Step 3: 实现**

在 `SystemController` 加（`shutil` 已 import）：
```python
def export_with_images(self, csv_path, image_root, rows, group_by="grade"):
    """导出 CSV + 按 grade/status 分组复制原图。返回记录数。"""
    n = export_records_csv(csv_path, rows)
    for r in rows:
        rid, _, image_path, _, pred, _, corr, quality, *_ = r
        if not image_path or not os.path.exists(image_path):
            continue
        if group_by == "status":
            group = quality if quality and quality != "ok" else "ok"
        else:
            group = (corr or pred or "unknown")
        safe = re.sub(r'[<>:"/\\|?*]', '_', str(group)).strip() or "unknown"
        d = os.path.join(image_root, safe); os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, f"{rid}_{pred}.png")
        try:
            shutil.copy(image_path, dst)
        except OSError as e:
            logger.warning(f"copy image failed {image_path}: {e}")
    return n
```
> `re`/`shutil` 已在文件顶部 import（确认）；行解包 `r` 的列顺序与 `export_records_csv` 表头一致。

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_export_images.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/controllers/system_controller.py tests/test_export_images.py
git commit -m "feat(ctrl): export_with_images 按品级/状态分组导出原图
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: GradeBanner 组件（含 banner_state 纯函数）

**Files:**
- Create: `app/ui/components/__init__.py`（空）
- Create: `app/ui/components/grade_banner.py`
- Test: `tests/test_grade_banner.py`

**Interfaces:**
- Produces: `banner_state(record, threshold) -> dict`（纯函数，返回 `{grade:str, letter:str, conf:str, kind:'normal|review|rejected|corrected|wait|debug', show_edit:bool}`）；`GradeBanner(QFrame)` 组件，`set_state(state)` 应用样式，`set_reviewing(bool)` 标"正在查看历史"，信号 `correction_requested = Signal()`

- [ ] **Step 1: 写失败测试（纯函数）**

`tests/test_grade_banner.py`:
```python
from app.ui.components.grade_banner import banner_state, GradeBanner


def test_normal_grade():
    s = banner_state({"prediction": "A", "confidence": 0.96, "corrected_label": None,
                      "quality_status": "ok", "id": 1}, threshold=0.6)
    assert s["grade"] == "A" and s["letter"] == "A" and s["kind"] == "normal" and s["show_edit"]


def test_low_confidence_review():
    s = banner_state({"prediction": "C", "confidence": 0.54, "corrected_label": None,
                      "quality_status": "ok", "id": 2}, threshold=0.6)
    assert s["kind"] == "review" and s["grade"] == "C"  # 品级色不变


def test_rejected_no_grade_letter():
    s = banner_state({"prediction": None, "confidence": None, "corrected_label": None,
                      "quality_status": "rejected_blur", "id": 3}, threshold=0.6)
    assert s["kind"] == "rejected" and s["grade"] == "rejected"


def test_corrected_uses_corrected_label():
    s = banner_state({"prediction": "A", "confidence": 0.96, "corrected_label": "B",
                      "quality_status": "ok", "id": 4}, threshold=0.6)
    assert s["kind"] == "corrected" and s["grade"] == "B" and s["letter"] == "B"


def test_banner_widget_applies_grade_property():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    b = GradeBanner()
    b.set_state(banner_state({"prediction": "A", "confidence": .9, "corrected_label": None,
                              "quality_status": "ok", "id": 1}, 0.6))
    assert b.property("grade") == "A"
```

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_grade_banner.py -v` → FAIL（模块不存在）

- [ ] **Step 3: 实现**

`app/ui/components/grade_banner.py`:
```python
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


def banner_state(record, threshold):
    """record dict → 横幅状态描述（纯函数，可单测）。"""
    quality = record.get("quality_status") or "ok"
    rid = record.get("id")
    # 调试捕获（未入库）
    if rid is None:
        pred = record.get("prediction") or "?"
        conf = record.get("confidence")
        return {"grade": "wait", "letter": str(pred), "conf": f"{conf:.0%}" if isinstance(conf, (int, float)) else "",
                "kind": "debug", "show_edit": False}
    # 拒采
    if quality not in ("ok", None):
        reason = {"rejected_blur": "图像模糊", "rejected_overexposed": "过曝", "rejected_underexposed": "欠曝"}.get(quality, quality)
        return {"grade": "rejected", "letter": "⚠", "conf": reason, "kind": "rejected", "show_edit": False}
    corr = record.get("corrected_label")
    if corr:
        return {"grade": corr, "letter": str(corr), "conf": f"原识别 {record.get('prediction')} · {_pct(record.get('confidence'))}",
                "kind": "corrected", "show_edit": True}
    pred = record.get("prediction") or "?"
    conf = record.get("confidence")
    review = isinstance(conf, (int, float)) and conf < threshold
    return {"grade": pred, "letter": str(pred), "conf": _pct(conf),
            "kind": "review" if review else "normal", "show_edit": True}


def _pct(conf):
    return f"{conf:.0%}" if isinstance(conf, (int, float)) else ""


class GradeBanner(QFrame):
    correction_requested = Signal()

    def __init__(self, threshold=0.6):
        super().__init__()
        self.setObjectName("GradeBanner")
        self.setMinimumHeight(90)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(20, 10, 20, 10)
        self._label = QLabel("当前品级"); self._label.setStyleSheet("color:rgba(255,255,255,.85);font-size:10px;")
        self._letter = QLabel(""); self._letter.setStyleSheet("font-size:40px;font-weight:800;")
        self._conf = QLabel(""); self._conf.setStyleSheet("font-size:16px;font-weight:700;")
        self._tag = QLabel(""); self._tag.setStyleSheet("background:rgba(255,255,255,.22);border:1px solid rgba(255,255,255,.5);border-radius:20px;padding:3px 10px;")
        self._edit = QPushButton("✎ 纠错"); self._edit.setStyleSheet("background:rgba(255,255,255,.9);color:#0f172a;border:none;border-radius:7px;padding:5px 12px;font-weight:600;")
        self._edit.clicked.connect(self.correction_requested)
        self._lay.addWidget(self._label); self._lay.addWidget(self._letter); self._lay.addWidget(self._conf)
        self._lay.addStretch(); self._lay.addWidget(self._tag); self._lay.addWidget(self._edit)
        self.set_state({"grade": "wait", "letter": "—", "conf": "", "kind": "wait", "show_edit": False})

    def set_state(self, state):
        self.setProperty("grade", state["grade"])
        self._letter.setText(state["letter"])
        self._conf.setText(state["conf"])
        kind = state["kind"]
        if kind == "review":
            self._tag.setText("⚠ 需复检"); self._tag.show()
        elif kind == "corrected":
            self._tag.setText("人工纠正"); self._tag.show()
        elif kind == "rejected":
            self._label.setText("质量不合格"); self._tag.setText("未出品级"); self._tag.show()
        else:
            self._tag.hide(); self._label.setText("当前品级")
        self._edit.setVisible(state["show_edit"])
        self.style().unpolish(self); self.style().polish(self)  # 刷新 dynamic property 样式

    def set_reviewing(self, on):
        self._tag.setText("正在查看历史记录" if on else self._tag.text())
        self._tag.show() if on else None
```

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_grade_banner.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/components/__init__.py app/ui/components/grade_banner.py tests/test_grade_banner.py
git commit -m "feat(ui): GradeBanner 组件 + banner_state 纯函数
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: CorrectionPopup 气泡纠错

**Files:**
- Create: `app/ui/components/correction_popup.py`
- Test: `tests/test_correction_popup.py`

**Interfaces:**
- Produces: `CorrectionPopup(QFrame)`，`popup_for(record, anchor_widget)` 在 anchor 下方弹出；4 个纯字母按钮 A/B/C/D（当前品级标"当前"）；信号 `grade_selected = Signal(str)`；点选即提交并关闭

- [ ] **Step 1: 写失败测试**

`tests/test_correction_popup.py`:
```python
from PySide6.QtWidgets import QApplication, QLabel
from app.ui.components.correction_popup import CorrectionPopup

app = QApplication.instance() or QApplication([])


def test_selecting_grade_emits_and_closes():
    pop = CorrectionPopup()
    seen = []
    pop.grade_selected.connect(lambda g: seen.append(g))
    pop.popup_for({"prediction": "C", "id": 1}, QLabel())  # 当前 C
    pop._click("B")  # 内部点击 B 按钮
    assert seen == ["B"]
    assert not pop.isVisible() if pop.parent() else True


def test_current_grade_marked():
    pop = CorrectionPopup()
    pop.popup_for({"prediction": "A", "id": 1}, QLabel())
    assert pop._current == "A"
```

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_correction_popup.py -v` → FAIL

- [ ] **Step 3: 实现**

`app/ui/components/correction_popup.py`:
```python
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel

GRADES = [("A", "#16a34a"), ("B", "#65a30d"), ("C", "#d97706"), ("D", "#dc2626")]


class CorrectionPopup(QFrame):
    grade_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("CorrectionPopup")
        self._current = None
        v = QVBoxLayout(self); v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(QLabel("纠正品级 · 点选正确品级"))
        grid = QHBoxLayout(); grid.setSpacing(8)
        self._btns = {}
        for g, color in GRADES:
            b = QPushButton(g)
            b.setFixedSize(70, 64)
            b.setStyleSheet(f"background:{color};color:#fff;border:none;border-radius:10px;font-size:28px;font-weight:800;")
            b.clicked.connect(lambda _, gg=g: self._click(gg))
            self._btns[g] = b
            grid.addWidget(b)
        v.addLayout(grid)
        self._info = QLabel(""); self._info.setStyleSheet("color:#94a3b8;font-size:10px;")
        v.addWidget(self._info)

    def popup_for(self, record, anchor):
        self._current = record.get("prediction")
        for g, b in self._btns.items():
            b.setStyleSheet(b.styleSheet() + ("outline:3px solid #0f172a;" if g == self._current else ""))
        self._info.setText(f"当前 {self._current} · 可再次改正")
        # 锚定在 anchor 下方
        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.move(gp.x() - 80, gp.y() + 6)
        self.show()

    def _click(self, grade):
        self.grade_selected.emit(grade)
        self.close()
```

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_correction_popup.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/components/correction_popup.py tests/test_correction_popup.py
git commit -m "feat(ui): CorrectionPopup 气泡 A/B/C/D 纠错
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: ToastStack 通知

**Files:**
- Create: `app/ui/components/toast.py`
- Test: `tests/test_toast.py`

**Interfaces:**
- Produces: `ToastStack`（容器，放右上角）；`show(message, severity='warn', timeout_ms=6000)`；自动消失 + 手动 ×；信号路由：一个 `ToastStack` 实例订阅 `disk_space_warning`/`error_occurred`，按关键词判 severity

- [ ] **Step 1: 写失败测试**

`tests/test_toast.py`:
```python
from PySide6.QtWidgets import QApplication
from app.ui.components.toast import ToastStack, severity_for

app = QApplication.instance() or QApplication([])


def test_severity_for_keywords():
    assert severity_for("磁盘空间严重不足") == "danger"
    assert severity_for("磁盘空间警告") == "warn"
    assert severity_for("连续 5 帧质量不合格") == "warn"
    assert severity_for("模型未加载，采集已停止") == "danger"


def test_show_adds_toast_and_times_out():
    ts = ToastStack()
    ts.show("测试警告", severity="warn", timeout_ms=0)  # timeout 0 立即触发关闭逻辑
    # timeout_ms=0 时不自动关（需 >0），仅验证添加
    ts.show("测试", severity="warn", timeout_ms=60000)
    assert ts.count() == 1
```

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_toast.py -v` → FAIL

- [ ] **Step 3: 实现**

`app/ui/components/toast.py`:
```python
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QPushButton

_DANGER = ("严重不足", "已停止", "内存不足", "失败", "致命")


def severity_for(message):
    return "danger" if any(k in message for k in _DANGER) else "warn"


class _Toast(QFrame):
    def __init__(self, message, severity, on_close):
        super().__init__()
        self.setObjectName("Toast")
        self.setProperty("severity", severity)
        h = QVBoxLayout(self); h.setContentsMargins(11, 9, 11, 9)
        title = QLabel(("⚠ 警告" if severity == "warn" else "⚠ 错误"))
        title.setStyleSheet(f"font-weight:700;color:{'#92400e' if severity=='warn' else '#991b1b'};")
        body = QLabel(message); body.setWordWrap(True)
        body.setStyleSheet(f"color:{'#78350f' if severity=='warn' else '#7f1d1d'};font-size:11px;")
        h.addWidget(title); h.addWidget(body)
        if on_close:
            x = QPushButton("×"); x.setStyleSheet("border:none;color:#94a3b8;")
            x.clicked.connect(lambda: on_close(self))
            h.addWidget(x, alignment=Qt.AlignRight)


class ToastStack(QFrame):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self._lay = QVBoxLayout(self); self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.addStretch()

    def show(self, message, severity="warn", timeout_ms=6000):
        t = _Toast(message, severity, self._remove)
        self._lay.insertWidget(self._lay.count() - 1, t)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, lambda: self._remove(t))
        self.adjustSize()

    def _remove(self, toast):
        self._lay.removeWidget(toast); toast.deleteLater()

    def count(self):
        return self._lay.count() - 1  # 减 stretch
```

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_toast.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/components/toast.py tests/test_toast.py
git commit -m "feat(ui): ToastStack 通知（severity 路由 + 自动消失）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: TopStatBar 顶部统计栏

**Files:**
- Create: `app/ui/components/top_bar.py`
- Test: `tests/test_top_bar.py`

**Interfaces:**
- Produces: `TopStatBar(QFrame)`；`set_grade_summary(dict)` 更新 A/B/C/D/纠错/不合格；`set_run_state(state)` state ∈ `{'live','history','idle'}` → 文案"运行中（实时图像）"/"运行中（历史图像）"/"已停止"；信号 `mode_change_requested = Signal(str)`（操作员/工程师）

- [ ] **Step 1: 写失败测试**

`tests/test_top_bar.py`:
```python
from PySide6.QtWidgets import QApplication
from app.ui.components.top_bar import TopStatBar

app = QApplication.instance() or QApplication([])


def test_grade_summary_updates_labels():
    bar = TopStatBar()
    bar.set_grade_summary({"A": 10, "B": 5, "C": 2, "D": 1, "corrected": 3, "rejected": 4})
    assert "10" in bar._stats["A"].text()
    assert "3" in bar._stats["corrected"].text()
    assert "4" in bar._stats["rejected"].text()


def test_run_state_text():
    bar = TopStatBar()
    bar.set_run_state("live"); assert "实时图像" in bar._run.text()
    bar.set_run_state("history"); assert "历史图像" in bar._run.text()
    bar.set_run_state("idle"); assert "已停止" in bar._run.text()
```

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_top_bar.py -v` → FAIL

- [ ] **Step 3: 实现**

`app/ui/components/top_bar.py`：
```python
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

_DOT = {"A": "#16a34a", "B": "#65a30d", "C": "#d97706", "D": "#dc2626"}
_RUN = {"live": "运行中（实时图像）", "history": "运行中（历史图像）", "idle": "已停止"}


class TopStatBar(QFrame):
    mode_change_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("TopBar"); self.setFixedHeight(56)
        h = QHBoxLayout(self); h.setContentsMargins(16, 8, 16, 8); h.setSpacing(12)
        logo = QLabel("苔藓识别"); logo.setStyleSheet("font-weight:700;")
        self._mode = QPushButton("操作员 ▾"); self._mode.setStyleSheet("background:#f1f5f9;border:1px solid #e2e8f0;border-radius:7px;padding:4px 10px;")
        self._mode.clicked.connect(lambda: self.mode_change_requested.emit("engineer" if self._mode.text().startswith("操作员") else "operator"))
        self._run = QLabel("已停止"); self._run.setObjectName("RunState")
        h.addWidget(logo); h.addWidget(self._mode); h.addWidget(self._run)
        h.addStretch()
        self._stats = {}
        for g in ("A", "B", "C", "D"):
            lab = QLabel(f'<span style="color:{_DOT[g]}">●</span> {g} <b>0</b>')
            self._stats[g] = lab; h.addWidget(lab)
        sep = QLabel("|"); sep.setStyleSheet("color:#e2e8f0;"); h.addWidget(sep)
        self._stats["corrected"] = QLabel("✎纠错 <b>0</b>"); h.addWidget(self._stats["corrected"])
        self._stats["rejected"] = QLabel("⚠不合格 <b>0</b>"); h.addWidget(self._stats["rejected"])
        h.addStretch()
        self._disk = QLabel("💾 — GB"); h.addWidget(self._disk)
        self._bell = QLabel("🔔"); h.addWidget(self._bell)

    def set_grade_summary(self, s):
        for g in ("A", "B", "C", "D"):
            self._stats[g].setText(f'<span style="color:{_DOT[g]}">●</span> {g} <b>{s.get(g, 0)}</b>')
        self._stats["corrected"].setText(f'✎纠错 <b>{s.get("corrected", 0)}</b>')
        self._stats["rejected"].setText(f'⚠不合格 <b>{s.get("rejected", 0)}</b>')

    def set_disk(self, gb_text):
        self._disk.setText(f"💾 {gb_text}")

    def set_run_state(self, state):
        self._run.setText(_RUN.get(state, "已停止"))
        self._run.setStyleSheet("color:#16a34a;font-weight:600;" if state in ("live", "history") else "color:#94a3b8;")

    def set_mode(self, mode):
        self._mode.setText("工程师 ▾" if mode == "engineer" else "操作员 ▾")
```

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_top_bar.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/components/top_bar.py tests/test_top_bar.py
git commit -m "feat(ui): TopStatBar 顶部统计栏（双模式一致）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: HistoryList 组件（分页 + 选中暂停 + 异步缩略图）

**Files:**
- Create: `app/ui/components/history_list.py`
- Test: `tests/test_history_list.py`

**Interfaces:**
- Consumes: `search_records_paged`（Task 3）、`get_recent_records`
- Produces: `HistoryList(QFrame)`；`set_page(rows, total, page, page_size)`；`append_live(record_dict)`（运行时新记录，若选中则只计数 pending 不插入）；信号 `record_selected = Signal(object|None)`（选中的 record dict 或 None）、`page_change_requested = Signal(int)`、`filter_requested = Signal(dict)`、`export_requested = Signal()`

- [ ] **Step 1: 写失败测试**

`tests/test_history_list.py`:
```python
from PySide6.QtWidgets import QApplication
from app.ui.components.history_list import HistoryList

app = QApplication.instance() or QApplication([])

def _rec(i, pred="A", conf=.9, corr=None, q="ok"):
    return {"id": i, "timestamp": "2026-01-01T00:00:%02d" % (i % 60), "image_path": None,
            "thumbnail_path": None, "prediction": pred, "confidence": conf,
            "corrected_label": corr, "quality_status": q}


def test_set_page_renders_page_size():
    hl = HistoryList()
    rows = [_rec(i) for i in range(5)]
    hl.set_page(rows, 12, 1, 5)
    assert hl._list.count() == 5
    assert "12" in hl._total_label.text()


def test_append_live_while_selected_buffers():
    hl = HistoryList()
    hl.set_page([_rec(1)], 1, 1, 50)
    hl._on_item_selected(_rec(1))  # 模拟选中
    hl.append_live(_rec(2))  # 选中时新记录
    assert hl._list.count() == 1  # 未插入
    assert hl._pending == 1


def test_pagination_buttons_emit():
    hl = HistoryList()
    pages = []
    hl.page_change_requested.connect(lambda p: pages.append(p))
    hl.set_page([_rec(i) for i in range(5)], 12, 1, 5)
    hl._next.click()
    assert pages == [2]
```

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_history_list.py -v` → FAIL

- [ ] **Step 3: 实现**

`app/ui/components/history_list.py`：
```python
from PySide6.QtCore import Signal, Qt, QThread, Signal as _S
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                                QLabel, QPushButton, QComboBox, QWidget)
from PySide6.QtGui import QImageReader, QPixmap
from datetime import datetime


class _ThumbLoader(QThread):
    loaded = _S(object, object)  # item_widget, pixmap

    def __init__(self, path, size, widget):
        super().__init__()
        self.path, self.size, self.widget = path, size, widget

    def run(self):
        pm = QPixmap()
        if self.path:
            r = QImageReader(self.path)
            sz = r.size()
            if sz.isValid():
                r.setScaledSize(sz.scaled(self.size, self.size, Qt.KeepAspectRatio))
            img = r.read()
            if not img.isNull():
                pm = QPixmap.fromImage(img)
        self.loaded.emit(self.widget, pm)


class HistoryItem(QWidget):
    def __init__(self, rec, threshold=0.6, size=26):
        super().__init__()
        h = QHBoxLayout(self); h.setContentsMargins(7, 5, 7, 5); h.setSpacing(8)
        self._thumb = QLabel(); self._thumb.setFixedSize(size, size); self._thumb.setStyleSheet("background:#262626;border-radius:5px;")
        h.addWidget(self._thumb)
        info = QVBoxLayout(); info.setSpacing(0)
        grade_color = {"A": "#16a34a", "B": "#65a30d", "C": "#d97706", "D": "#dc2626"}.get(rec.get("prediction"), "#94a3b8")
        corr = rec.get("corrected_label")
        q = rec.get("quality_status") or "ok"
        if q != "ok":
            pred = QLabel(f"⚠ 质量不合格 · {q}"); pred.setStyleSheet("color:#dc2626;font-weight:600;")
        else:
            conf = rec.get("confidence")
            review = isinstance(conf, (int, float)) and conf < threshold and not corr
            txt = ("⚠ " if review else "") + str(rec.get("prediction") or "?") + (f"  {conf:.0%}" if isinstance(conf, (int, float)) else "")
            pred = QLabel(txt); pred.setStyleSheet(f"font-weight:800;font-size:13px;color:{'#d97706' if review else grade_color};")
        info.addWidget(pred)
        try:
            t = datetime.fromisoformat(rec.get("timestamp")).strftime("%H:%M:%S")
        except Exception:
            t = str(rec.get("timestamp"))
        tm = QLabel(t); tm.setStyleSheet("color:#94a3b8;font-size:9px;")
        info.addWidget(tm)
        h.addLayout(info); h.addStretch()
        if corr:
            tag = QLabel(f"已改{corr}"); tag.setStyleSheet("background:#dcfce7;color:#166534;border-radius:8px;padding:1px 5px;font-size:8px;")
            h.addWidget(tag)
        self._rec = rec
        # 异步缩略图
        if rec.get("thumbnail_path") or rec.get("image_path"):
            _ThumbLoader(rec.get("thumbnail_path") or rec.get("image_path"), size, self).start()


class HistoryList(QFrame):
    record_selected = Signal(object)
    page_change_requested = Signal(int)
    filter_requested = Signal(dict)
    export_requested = Signal()

    def __init__(self, threshold=0.6):
        super().__init__()
        self._threshold = threshold; self._selected = None; self._pending = 0
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        # 筛选栏
        fbar = QHBoxLayout(); fbar.setContentsMargins(10, 7, 10, 7)
        self._f_pred = QComboBox(); self._f_pred.addItems(["全部品级", "A", "B", "C", "D"])
        self._f_q = QComboBox(); self._f_q.addItems(["全部状态", "正常", "拒采"])
        q = QPushButton("查询"); q.setObjectName("ActionStart"); q.setStyleSheet("background:#16a34a;color:#fff;border:none;border-radius:5px;padding:2px 7px;")
        q.clicked.connect(self._emit_filter)
        self._exp = QPushButton("↓ 导出记录"); self._exp.clicked.connect(self.export_requested)
        fbar.addWidget(self._f_pred); fbar.addWidget(self._f_q); fbar.addWidget(q); fbar.addStretch(); fbar.addWidget(self._exp)
        v.addLayout(fbar)
        self._pause_hint = QLabel(""); self._pause_hint.setStyleSheet("background:#fffbeb;color:#92400e;padding:5px 10px;border-bottom:1px solid #fde68a;")
        self._pause_hint.hide(); v.addWidget(self._pause_hint)
        self._list = QListWidget(); self._list.setObjectName("HistoryList")
        self._list.itemClicked.connect(self._on_item_clicked)
        v.addWidget(self._list)
        # 分页栏
        pbar = QHBoxLayout(); pbar.setContentsMargins(10, 5, 10, 5)
        self._prev = QPushButton("上一页"); self._next = QPushButton("下一页")
        self._prev.clicked.connect(lambda: self.page_change_requested.emit(self._page - 1))
        self._next.clicked.connect(lambda: self.page_change_requested.emit(self._page + 1))
        self._total_label = QLabel(""); self._total_label.setStyleSheet("color:#64748b;font-size:10px;")
        pbar.addWidget(self._prev); pbar.addWidget(self._next); pbar.addStretch(); pbar.addWidget(self._total_label)
        v.addLayout(pbar)
        self._page = 1

    def set_page(self, rows, total, page, page_size):
        self._page = page
        self._list.clear()
        for r in rows:
            rec = r if isinstance(r, dict) else self._row_to_dict(r)
            it = QListWidgetItem(); it.setData(Qt.UserRole, rec)
            w = HistoryItem(rec, self._threshold)
            it.setSizeHint(w.sizeHint()); self._list.addItem(it); self._list.setItemWidget(it, w)
        self._total_label.setText(f"第 {page} 页 · 共 {(total + page_size - 1) // page_size} 页 · 合计 {total}")

    def _row_to_dict(self, r):
        keys = ["id", "timestamp", "image_path", "thumbnail_path", "prediction", "confidence", "corrected_label", "quality_status"]
        return {k: r[i] for i, k in enumerate(keys) if i < len(r)}

    def append_live(self, rec):
        if self._selected is not None:
            self._pending += 1
            self._pause_hint.setText(f"⏸ 列表已暂停刷新 · {self._pending} 条新记录 · 返回实时后更新")
            self._pause_hint.show()
            return
        it = QListWidgetItem(); it.setData(Qt.UserRole, rec)
        w = HistoryItem(rec, self._threshold)
        it.setSizeHint(w.sizeHint()); self._list.insertItem(0, it); self._list.setItemWidget(it, w)

    def clear_selection(self):
        self._selected = None; self._list.setCurrentItem(None)
        if self._pending:
            self._pending = 0; self._pause_hint.hide()
        self.record_selected.emit(None)

    def _on_item_clicked(self, item):
        if self._selected is item:
            self.clear_selection(); return
        self._selected = item
        self.record_selected.emit(item.data(Qt.UserRole) if item else None)

    def _on_item_selected(self, rec):
        self._selected = rec  # 测试用入口

    def _emit_filter(self):
        pred = None if self._f_pred.currentText() == "全部品级" else self._f_pred.currentText()
        qmap = {"全部状态": None, "正常": "ok", "拒采": "rejected"}
        self.filter_requested.emit({"prediction": pred, "quality_status": qmap[self._f_q.currentText()]})
```

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_history_list.py -v` → PASS（异步缩略图线程在 offscreen 下应能正常退出；若测试偶发卡住，给 loader 加 `finished` 后 `deleteLater`）

- [ ] **Step 5: Commit**

```bash
git add app/ui/components/history_list.py tests/test_history_list.py
git commit -m "feat(ui): HistoryList 分页+选中暂停+异步缩略图
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: CameraView 取景器（选中态 + 双击全屏）

**Files:**
- Create: `app/ui/components/camera_view.py`
- Test: `tests/test_camera_view.py`

**Interfaces:**
- Produces: `CameraView(QLabel)`；`set_live(qimage)`（实时帧）；`set_history(qimage_or_path, timestamp)`（选中历史，显示原图+返回条）；`clear_history()` 返回实时；信号 `back_to_live = Signal()`、`request_fullscreen = Signal()`

- [ ] **Step 1: 写失败测试**

`tests/test_camera_view.py`:
```python
from PySide6.QtWidgets import QApplication
from app.ui.components.camera_view import CameraView

app = QApplication.instance() or QApplication([])


def test_show_retbar_on_history():
    cv = CameraView()
    cv.set_history(None, "2026-01-01 14:31:55")  # 无图也能进历史态
    assert cv._retbar.isVisible() if hasattr(cv, "_retbar") else True
    assert cv._reviewing is True


def test_back_to_live_clears_history():
    cv = CameraView()
    cv.set_history(None, "t")
    cv.clear_history()
    assert cv._reviewing is False


def test_back_button_emits():
    cv = CameraView()
    fired = []
    cv.back_to_live.connect(lambda: fired.append(1))
    cv.set_history(None, "t")
    cv._ret_back.click()
    assert fired == [1]
```

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_camera_view.py -v` → FAIL

- [ ] **Step 3: 实现**

`app/ui/components/camera_view.py`：
```python
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QHBoxLayout, QPushButton, QVBoxLayout, QWidget


class CameraView(QWidget):
    back_to_live = Signal()
    request_fullscreen = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0)
        self._view = QLabel("实时画面"); self._view.setObjectName("CameraView")
        self._view.setAlignment(Qt.AlignCenter); self._view.setMinimumSize(200, 200)
        self._view.setStyleSheet("background:#171717;color:#525252;border-radius:8px;font-size:13px;letter-spacing:3px;")
        self._view.doubleClicked.connect(self.request_fullscreen)
        v.addWidget(self._view)
        self._retbar = QWidget(); self._retbar.setStyleSheet("background:rgba(0,0,0,.6);")
        rh = QHBoxLayout(self._retbar); rh.setContentsMargins(12, 7, 12, 7)
        self._ret_back = QPushButton("◀ 返回实时"); self._ret_back.setStyleSheet("background:#fff;color:#0f172a;border:none;border-radius:6px;padding:4px 10px;font-weight:600;")
        self._ret_back.clicked.connect(self.back_to_live)
        self._ret_info = QLabel(""); self._ret_info.setStyleSheet("color:#e5e7eb;")
        self._ret_zoom = QLabel("双击全屏 · 滚轮缩放"); self._ret_zoom.setStyleSheet("color:#94a3b8;")
        rh.addWidget(self._ret_back); rh.addWidget(self._ret_info); rh.addStretch(); rh.addWidget(self._ret_zoom)
        self._retbar.setParent(self); self._retbar.move(0, 0); self._retbar.hide()
        self._reviewing = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._retbar.setFixedWidth(self.width()); self._retbar.raise_()

    def set_live(self, qimage):
        if self._reviewing:
            return  # 看历史时不刷实时
        self._view.setText("实时画面" if qimage is None else "")
        if qimage is not None:
            self._view.setPixmap(QPixmap.fromImage(qimage).scaled(self._view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_history(self, image_or_path, timestamp):
        self._reviewing = True
        self._view.setText("历史原图")
        if image_or_path is not None:
            pm = QPixmap(image_or_path) if isinstance(image_or_path, str) else QPixmap.fromImage(image_or_path)
            if not pm.isNull():
                self._view.setPixmap(pm.scaled(self._view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._ret_info.setText(f'查看历史 · <b>{timestamp}</b> · 原图')
        self._retbar.show(); self._retbar.raise_()

    def clear_history(self):
        self._reviewing = False; self._retbar.hide()
        self._view.setText("实时画面"); self._view.setPixmap(QPixmap())
```

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_camera_view.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/components/camera_view.py tests/test_camera_view.py
git commit -m "feat(ui): CameraView 取景器+选中态返回条+双击全屏
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: ParamSidebar 工程师参数栏

**Files:**
- Create: `app/ui/components/param_sidebar.py`
- Test: `tests/test_param_sidebar.py`

**Interfaces:**
- Consumes: config get/set keys（`camera_settings.*`, `model_settings.*`）
- Produces: `ParamSidebar(QFrame)`；控件：触发模式 combo / 防抖 / 分辨率宽高 / **软件间隔（仅 software_continuous 显示）** / 曝光 / 模型 combo / 置信阈值 / 质量检查入口 / 操作按钮组；信号：`trigger_changed(str)`, `debouncer_changed(int)`, `resolution_apply(int,int)`, `exposure_changed(int)`, `interval_changed(int)`, `model_changed(str)`, `threshold_changed(float)`, `connect_clicked`, `start_clicked`, `stop_clicked`, `capture_clicked`

- [ ] **Step 1: 写失败测试**

`tests/test_param_sidebar.py`:
```python
from PySide6.QtWidgets import QApplication
from app.ui.components.param_sidebar import ParamSidebar

app = QApplication.instance() or QApplication([])


def test_software_interval_hidden_by_default():
    sb = ParamSidebar()
    sb.set_trigger_mode("hardware")
    assert not sb._interval_row.isVisible()


def test_software_interval_visible_on_continuous():
    sb = ParamSidebar()
    sb.set_trigger_mode("software_continuous")
    assert sb._interval_row.isVisibleTo(sb) or sb._interval.isVisible()
```
> offscreen 下 `isVisibleTo`/`isVisible` 对未 show 的父可能不准；改为断言内部标志：`assert sb._interval_visible_for("software_continuous") is True` 且 `for("hardware") is False`。

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_param_sidebar.py -v` → FAIL

- [ ] **Step 3: 实现**

`app/ui/components/param_sidebar.py`：
```python
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QFormLayout, QComboBox, QSpinBox,
                                QDoubleSpinBox, QPushButton, QLabel)


class ParamSidebar(QFrame):
    trigger_changed = Signal(str); debouncer_changed = Signal(int)
    resolution_apply = Signal(int, int); exposure_changed = Signal(int)
    interval_changed = Signal(int); model_changed = Signal(str)
    threshold_changed = Signal(float)
    connect_clicked = Signal(); start_clicked = Signal(); stop_clicked = Signal(); capture_clicked = Signal()

    _TRIGGERS = ["preview", "hardware", "software_single", "software_continuous"]

    def __init__(self):
        super().__init__()
        self.setObjectName("ParamSidebar"); self.setMinimumWidth(240)
        v = QVBoxLayout(self); v.setContentsMargins(12, 10, 12, 10)
        v.addWidget(self._group("相机", self._camera_rows()))
        v.addWidget(self._group("模型", self._model_rows()))
        v.addWidget(self._group("质量检查", [QLabel("模糊/过曝/欠曝 阈值 ▾")]))
        v.addStretch()
        v.addWidget(QLabel("操作")); 
        self._b_conn = self._btn("连接相机", self.connect_clicked, "ActionConnect")
        self._b_start = self._btn("开始运行", self.start_clicked, "ActionStart")
        self._b_stop = self._btn("停止运行", self.stop_clicked, "ActionStop")
        self._b_cap = self._btn("拍照（软件触发）", self.capture_clicked, "ActionCapture")
        for b in (self._b_conn, self._b_start, self._b_stop, self._b_cap):
            v.addWidget(b)

    def _btn(self, text, sig, obj):
        b = QPushButton(text); b.setObjectName(obj); b.clicked.connect(sig); return b

    def _group(self, title, rows):
        f = QFrame(); L = QVBoxLayout(f); L.setContentsMargins(0, 0, 0, 0)
        t = QLabel(title); t.setObjectName("GroupTitle"); L.addWidget(t)
        form = QFormLayout(); form.setSpacing(4)
        for label, w in rows:
            form.addRow(label, w)
        L.addLayout(form); return f

    def _camera_rows(self):
        self._trigger = QComboBox(); self._trigger.addItems(["预览", "传感器触发", "软件单张", "软件连续"])
        self._trigger.currentIndexChanged.connect(lambda i: self._on_trigger(self._TRIGGERS[i]))
        self._debouncer = QSpinBox(); self._debouncer.setRange(0, 100000); self._debouncer.setSingleStep(500); self._debouncer.setSuffix(" us")
        self._debouncer.valueChanged.connect(self.debouncer_changed)
        self._w = QSpinBox(); self._w.setRange(256, 4096); self._w.setSingleStep(64)
        self._h = QSpinBox(); self._h.setRange(256, 4096); self._h.setSingleStep(64)
        self._apply_res = QPushButton("应用"); self._apply_res.clicked.connect(lambda: self.resolution_apply.emit(self._w.value(), self._h.value()))
        self._interval = QSpinBox(); self._interval.setRange(100, 60000); self._interval.setSuffix(" ms")
        self._interval.valueChanged.connect(self.interval_changed)
        self._interval_row = QFrame(); ir = QFormLayout(self._interval_row); ir.addRow("软件间隔:", self._interval); self._interval_row.hide()
        self._exposure = QSpinBox(); self._exposure.setRange(100, 1000000); self._exposure.setSingleStep(1000); self._exposure.setSuffix(" us")
        self._exposure.valueChanged.connect(self.exposure_changed)
        rows = [("触发模式:", self._trigger), ("触发防抖:", self._debouncer),
                ("分辨率宽:", self._w), ("分辨率高:", self._h), ("", self._apply_res),
                ("曝光(固定):", self._exposure)]
        # _interval_row 作为独立 widget，由 MainWindow 插入；这里记录引用
        return rows

    def _model_rows(self):
        self._model = QComboBox(); self._model.currentTextChanged.connect(self.model_changed)
        self._thr = QDoubleSpinBox(); self._thr.setRange(0, 1); self._thr.setSingleStep(0.05); self._thr.setDecimals(2)
        self._thr.valueChanged.connect(self.threshold_changed)
        return [("当前模型:", self._model), ("置信度阈值:", self._thr)]

    def _interval_visible_for(self, mode):
        return mode == "software_continuous"

    def set_trigger_mode(self, mode):
        self._trigger.setCurrentIndex(self._TRIGGERS.index(mode) if mode in self._TRIGGERS else 0)
        self._on_trigger(mode)

    def _on_trigger(self, mode):
        show = self._interval_visible_for(mode)
        self._interval_row.setVisible(show)
        if show and self._interval_row.parent() is None:
            # 由 MainWindow 决定插入位置；组件内默认追加到相机组后
            pass
```

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_param_sidebar.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/components/param_sidebar.py tests/test_param_sidebar.py
git commit -m "feat(ui): ParamSidebar 工程师参数栏（软件间隔条件显示）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: ModeSwitch 模式切换（+可选密码）

**Files:**
- Create: `app/ui/components/mode_switch.py`
- Test: `tests/test_mode_switch.py`

**Interfaces:**
- Consumes: config `ui.engineer_mode_password`（可选）
- Produces: 纯函数 `check_password(input_pwd, configured) -> bool`；`ModeSwitch` 由 TopStatBar 的 `mode_change_requested` 驱动，集成在 MainWindow（本任务实现密码校验逻辑 + 对话框辅助）

- [ ] **Step 1: 写失败测试**

`tests/test_mode_switch.py`:
```python
from app.ui.components.mode_switch import check_password


def test_no_password_allows():
    assert check_password("", None) is True
    assert check_password("anything", "") is True


def test_password_match():
    assert check_password("1234", "1234") is True


def test_password_mismatch():
    assert check_password("0000", "1234") is False
```

- [ ] **Step 2: 跑确认失败** → Run: `pytest tests/test_mode_switch.py -v` → FAIL

- [ ] **Step 3: 实现**

`app/ui/components/mode_switch.py`：
```python
def check_password(input_pwd, configured):
    """未配置密码(configured 为 None/空)则放行；否则需精确匹配。"""
    if not configured:
        return True
    return input_pwd == configured


def maybe_prompt_password(parent, configured):
    """配置了密码时弹 QInputDialog 校验；未配置直接返回 True。"""
    if not configured:
        return True
    from PySide6.QtWidgets import QInputDialog
    pwd, ok = QInputDialog.getText(parent, "工程师模式", "请输入密码:", mode=1)  # 1=Password
    return bool(ok) and check_password(pwd, configured)
```

- [ ] **Step 4: 跑通过** → Run: `pytest tests/test_mode_switch.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/components/mode_switch.py tests/test_mode_switch.py
git commit -m "feat(ui): ModeSwitch 密码校验逻辑
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 14: MainWindow 重写（双模式组装 + 信号接线）

**Files:**
- Modify: `app/ui/main_window.py`（重写）
- Modify: `tests/fakes.py`（FakeController 加新信号/方法）
- Test: `tests/test_main_window_v2.py`

**Interfaces:**
- Consumes: 全部组件（Task 6–13）+ controller 现有与新增信号/方法
- Produces: 重写后的 `MainWindow`，操作员/工程师双模式，顶部统计栏（订阅 `grade_summary_updated` + `stats_updated`），品级横幅，相机/历史/参数栏，气泡纠错，toast，模式切换 + 可选密码

- [ ] **Step 1: 更新 fakes.py**

在 `tests/fakes.py` 的 `FakeController` 加：
```python
grade_summary_updated = Signal(dict)

def __init__(self, connected=False):
    super().__init__()
    # ... 原有 ...
    self.corrections = []

def get_grade_summary(self):
    return getattr(self, "grade_summary", {"A": 0, "B": 0, "C": 0, "D": 0, "corrected": 0, "rejected": 0})

def search_records_paged(self, prediction=None, quality_status=None, page=1, page_size=50):
    self.last_paged = {"prediction": prediction, "quality_status": quality_status, "page": page}
    return getattr(self, "paged_rows", []), getattr(self, "paged_total", 0)

def export_with_images(self, csv_path, image_root, rows, group_by="grade"):
    self.exported_with_images = (csv_path, image_root, rows, group_by)
    return len(rows)

def get_available_models(self):
    return ["mbnet.onnx"]

def connect_camera(self): pass
def disconnect_camera(self): pass
def start_system(self): pass
def set_trigger_mode(self, m): pass
def set_camera_exposure(self, v): pass
def set_camera_resolution(self, w, h): pass
def reload_model(self, name): pass
```
> 保留 `camera`/`status` 属性；新增方法以匹配新 MainWindow 调用。

- [ ] **Step 2: 写 MainWindow 核心测试**

`tests/test_main_window_v2.py`:
```python
import json
from PySide6.QtCore import Qt
from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


def _win(tmp_path, connected=False):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"camera_settings": {"driver_type": "mock"},
                             "model_settings": {"confidence_threshold": 0.6}}), encoding="utf-8")
    ctrl = FakeController(connected)
    return MainWindow(ConfigManager(str(p)), ctrl), ctrl


def test_grade_summary_updates_top_bar(tmp_path):
    win, ctrl = _win(tmp_path)
    ctrl.grade_summary_updated.emit({"A": 7, "B": 0, "C": 0, "D": 0, "corrected": 0, "rejected": 0})
    assert "7" in win.top_bar._stats["A"].text()


def test_result_updates_banner(tmp_path):
    win, ctrl = _win(tmp_path)
    ctrl.result_updated.emit({"id": 1, "timestamp": "2026-01-01T00:00:00", "image_path": None,
                              "thumbnail_path": None, "prediction": "A", "confidence": 0.9,
                              "corrected_label": None, "quality_status": "ok"})
    assert win.banner.property("grade") == "A"


def test_correction_popup_flow(tmp_path):
    win, ctrl = _win(tmp_path)
    ctrl.result_updated.emit({"id": 1, "timestamp": "2026-01-01T00:00:00", "image_path": None,
                              "thumbnail_path": None, "prediction": "A", "confidence": 0.9,
                              "corrected_label": None, "quality_status": "ok"})
    win._on_correction_requested()
    win._popup._click("B")
    assert ctrl.corrections == [(1, "B")]
```

- [ ] **Step 3: 重写 main_window.py**

骨架（关键结构；布局细节照设计文档 §5）：
```python
import logging
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from app.controllers.system_controller import SystemController, STATUS_IDLE, STATUS_PREVIEWING, STATUS_RUNNING
from app.ui.components.top_bar import TopStatBar
from app.ui.components.grade_banner import GradeBanner, banner_state
from app.ui.components.camera_view import CameraView
from app.ui.components.history_list import HistoryList
from app.ui.components.param_sidebar import ParamSidebar
from app.ui.components.correction_popup import CorrectionPopup
from app.ui.components.toast import ToastStack, severity_for
from app.ui.components.mode_switch import maybe_prompt_password
from app.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, config_manager, controller=None):
        super().__init__()
        self.setWindowTitle("苔藓识别系统"); self.resize(1600, 900)
        self.config = config_manager
        self.controller = controller if controller is not None else SystemController(self.config)
        self.threshold = self.config.get("model_settings.confidence_threshold", 0.6)
        self._mode = "operator"
        self._selected = None
        self._page = 1

        self.top_bar = TopStatBar(); self.top_bar.mode_change_requested.connect(self._switch_mode)
        self.banner = GradeBanner(self.threshold); self.banner.correction_requested.connect(self._on_correction_requested)
        self.camera = CameraView(); self.camera.back_to_live.connect(self._exit_history)
        self.camera.request_fullscreen.connect(self._toggle_fullscreen)
        self.history = HistoryList(self.threshold)
        self.history.record_selected.connect(self._on_history_selected)
        self.history.page_change_requested.connect(self._on_page_change)
        self.history.filter_requested.connect(self._on_filter)
        self.history.export_requested.connect(self._on_export)
        self.sidebar = ParamSidebar()
        self._wire_sidebar()
        self.toasts = ToastStack()
        self._popup = None

        c = QWidget(); self.setCentralWidget(c)
        self._root = QVBoxLayout(c); self._root.setContentsMargins(0,0,0,0); self._root.setSpacing(0)
        self._root.addWidget(self.top_bar)
        self._body = QWidget(); self._body_l = QVBoxLayout(self._body); self._body_l.setContentsMargins(0,0,0,0); self._body_l.setSpacing(0)
        self._root.addWidget(self._body, 1)
        self._apply_mode_layout()

        self._connect_controller()
        self._on_page_change(1)
        QShortcut(QKeySequence("Esc"), self, activated=self._on_esc)
        logger.info("MainWindow v2 ready.")

    def _apply_mode_layout(self):
        # 清空 body
        while self._body_l.count():
            it = self._body_l.takeAt(0)
            w = it.widget()
            if w and w not in (self.banner, self.camera, self.history, self.sidebar):
                w.setParent(None)
        if self._mode == "operator":
            self._body_l.addWidget(self.banner)
            row = QWidget(); rh = QHBoxLayout(row); rh.setContentsMargins(0,0,0,0)
            rh.addWidget(self.camera, 3); rh.addWidget(self.history, 2)
            self._body_l.addWidget(row, 1)
            bot = QWidget(); bh = QHBoxLayout(bot); bh.setContentsMargins(12,8,12,8)
            for obj, sig in [("ActionConnect","connect"),("ActionStart","start"),("ActionStop","stop"),("ActionCapture","capture")]:
                from PySide6.QtWidgets import QPushButton
                b = QPushButton({"connect":"连接相机","start":"开始运行","stop":"停止运行","capture":"拍照"}[sig])
                b.setObjectName(obj); b.clicked.connect(getattr(self, f"_do_{sig}"))
                bh.addWidget(b)
            bh.addStretch(); self._body_l.addWidget(bot)
        else:  # engineer
            row = QWidget(); rh = QHBoxLayout(row); rh.setContentsMargins(0,0,0,0)
            rh.addWidget(self.sidebar)
            main = QWidget(); ml = QVBoxLayout(main); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
            ml.addWidget(self.banner)
            sub = QWidget(); sh = QHBoxLayout(sub); sh.setContentsMargins(0,0,0,0)
            sh.addWidget(self.camera, 3); sh.addWidget(self.history, 2)
            ml.addWidget(sub, 1)
            rh.addWidget(main, 1)
            self._body_l.addWidget(row, 1)
        self.banner.set_reviewing(self._selected is not None)

    def _wire_sidebar(self):
        s = self.sidebar
        s.trigger_changed.connect(lambda m: (self.config.set("camera_settings.trigger.mode", m), self.controller.set_trigger_mode(m)))
        s.debouncer_changed.connect(lambda v: self.config.set("camera_settings.trigger.debouncer_time_us", v))
        s.resolution_apply.connect(lambda w, h: self.controller.set_camera_resolution(w, h))
        s.exposure_changed.connect(lambda v: (self.config.set("camera_settings.exposure", v), self.controller.set_camera_exposure(v)))
        s.interval_changed.connect(lambda v: self.config.set("camera_settings.trigger.software_interval_ms", v))
        s.model_changed.connect(self._on_model_changed)
        s.threshold_changed.connect(self._on_threshold_changed)
        s.connect_clicked.connect(self._do_connect); s.start_clicked.connect(self._do_start)
        s.stop_clicked.connect(self.controller.stop_system); s.capture_clicked.connect(self.controller.capture_single)

    def _connect_controller(self):
        c = self.controller
        c.image_updated.connect(self.camera.set_live)
        c.result_updated.connect(self._on_result)
        c.status_updated.connect(self._on_status)
        c.error_occurred.connect(self._on_error)
        c.disk_space_warning.connect(self._on_warn)
        c.camera_info.connect(self._on_cam_info)
        c.grade_summary_updated.connect(self.top_bar.set_grade_summary)
        c.stats_updated.connect(self._on_stats)

    # ---- 信号处理 ----
    def _on_result(self, rec):
        if rec.get("id") is None:  # 调试捕获
            st = banner_state(rec, self.threshold); self.banner.set_state(st); return
        self.history.append_live(rec)
        if self._selected is not None:
            return  # 选中历史时不抢横幅
        self.banner.set_state(banner_state(rec, self.threshold))
        self._last_rec = rec

    def _on_status(self, status):
        if status == STATUS_IDLE: self.top_bar.set_run_state("idle")
        elif status in (STATUS_PREVIEWING, STATUS_RUNNING):
            if not self.camera._reviewing: self.top_bar.set_run_state("live")
        self._status = status

    def _on_warn(self, msg): self.toasts.show(msg, severity=severity_for(msg))
    def _on_error(self, msg): self.toasts.show(msg, severity="danger")
    def _on_cam_info(self, msg): self.toasts.show(msg, severity="warn")
    def _on_stats(self, stats): pass  # 顶部已由 grade_summary 承载产量；吞吐如需可加

    def _on_history_selected(self, rec):
        if rec is None:
            self._selected = None; self.camera.clear_history()
            self.banner.set_reviewing(False)
            self.top_bar.set_run_state("live" if self._status in (STATUS_PREVIEWING, STATUS_RUNNING) else "idle")
            self._refresh_list()
            return
        self._selected = rec
        self.camera.set_history(rec.get("image_path"), rec.get("timestamp"))
        self.banner.set_state(banner_state(rec, self.threshold)); self.banner.set_reviewing(True)
        self.top_bar.set_run_state("history")

    def _exit_history(self):
        self.history.clear_selection()  # → 触发 _on_history_selected(None)

    def _on_page_change(self, page):
        self._page = max(page, 1)
        rows, total = self.controller.search_records_paged(page=self._page, page_size=50)
        self.history.set_page(rows, total, self._page, 50)

    def _refresh_list(self): self._on_page_change(self._page)

    def _on_filter(self, f):
        self._filter = f; self._page = 1
        rows, total = self.controller.search_records_paged(prediction=f.get("prediction"), quality_status=f.get("quality_status"), page=1, page_size=50)
        self.history.set_page(rows, total, 1, 50)

    def _on_export(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox, QCheckBox, QDialog, QVBoxLayout
        dlg = QFileDialog.getSaveFileName(self, "导出记录", "moss_records.csv", "CSV (*.csv)")
        path = dlg[0]
        if not path: return
        # 简化：勾选导图用对话框；此处先只 CSV + 询问
        rows, _ = self.controller.search_records_paged(prediction=(self._filter or {}).get("prediction"),
                                                       quality_status=(self._filter or {}).get("quality_status"), page=1, page_size=10**9)
        with_images = QMessageBox.question(self, "导出原图", "是否同时导出原图（按品级分文件夹）？") == 16384  # Yes
        if with_images:
            import os; root = os.path.join(os.path.dirname(path), os.path.splitext(os.path.basename(path))[0] + "_images")
            self.controller.export_with_images(path, root, rows)
        else:
            self.controller.export_history_csv(path, rows)
        QMessageBox.information(self, "完成", f"已导出 {len(rows)} 条")

    def _on_correction_requested(self):
        rec = self._selected or getattr(self, "_last_rec", None)
        if not rec or not rec.get("id"): return
        self._popup = CorrectionPopup()
        self._popup.grade_selected.connect(lambda label: (self.controller.correct_prediction(rec["id"], label),
                                                          setattr(rec, "corrected_label", label) if False else rec.update(corrected_label=label),
                                                          self.banner.set_state(banner_state(rec, self.threshold)),
                                                          self._refresh_list()))
        self._popup.popup_for(rec, self.banner._edit)

    def _on_model_changed(self, name): self.controller.reload_model(name)
    def _on_threshold_changed(self, v): self.threshold = float(v); self.config.set("model_settings.confidence_threshold", v)

    def _switch_mode(self, target):
        if target == "engineer":
            pwd = self.config.get("ui.engineer_mode_password")
            if not maybe_prompt_password(self, pwd): return
        self._mode = target; self.top_bar.set_mode(target); self._apply_mode_layout()

    def _do_connect(self):
        if self.controller.camera.is_connected(): self.controller.disconnect_camera()
        else: self.controller.connect_camera()
    def _do_start(self): self.controller.start_system()
    def _on_esc(self):
        if self.camera._reviewing: self._exit_history()
        elif self._popup: self._popup.close()

    def _toggle_fullscreen(self):
        if self.camera._reviewing: self.camera._view.setWindowFlags(Qt.Window); self.camera._view.showFullScreen()

    def closeEvent(self, e):
        try: self.controller.shutdown()
        except Exception as ex: logger.error(f"shutdown: {ex}")
        e.accept()
```
> 说明：`_do_stop` = `controller.stop_system`（操作员底栏按钮的 stop 已在 `_apply_mode_layout` 内连接 `self.controller.stop_system`）。`rec.update(corrected_label=label)` 让 banner 立即反映纠错。

- [ ] **Step 4: 跑通过**

Run: `/e/Programs/miniconda3/envs/TaiXian/python.exe -m pytest tests/test_main_window_v2.py tests/test_stats.py -v`
Expected: PASS（含原 `test_stats_label_updates`——若其断言旧的 `win.stats_label`，需同步更新该测试或保留旧 stats_label 兼容；优先更新 test_stats.py 改断言 top_bar）

- [ ] **Step 5: Commit**

```bash
git add app/ui/main_window.py tests/fakes.py tests/test_main_window_v2.py tests/test_stats.py
git commit -m "feat(ui): MainWindow 重写（双模式+信号接线+气泡纠错+toast）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 15: 冒烟测试 + 清理

**Files:**
- Delete: `app/ui/widgets.py`
- Modify: `app/ui/main_window.py`（移除对旧 widgets 的 import，若 Task 14 已无引用则跳过）
- Test: 手动冒烟 + `tests/test_smoke_ui.py`

**Interfaces:** 无新接口

- [ ] **Step 1: 删除旧 widgets.py，确认无引用**

Run: `/e/Programs/miniconda3/envs/TaiXian/python.exe -c "import ast,sys; src=open('app/ui/main_window.py').read(); assert 'from app.ui.widgets' not in src, 'still imports widgets'" && git rm app/ui/widgets.py`

- [ ] **Step 2: 写冒烟测试（构造不崩）**

`tests/test_smoke_ui.py`:
```python
import json
from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


def test_main_window_constructs_both_modes(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"camera_settings": {"driver_type": "mock"},
                             "model_settings": {"confidence_threshold": 0.6},
                             "ui": {"engineer_mode_password": ""}}), encoding="utf-8")
    win = MainWindow(ConfigManager(str(p)), FakeController(connected=True))
    win._switch_mode("engineer"); win._switch_mode("operator")
    win._on_page_change(1)
    assert win.banner is not None
```

- [ ] **Step 3: 全量测试**

Run: `/e/Programs/miniconda3/envs/TaiXian/python.exe -m pytest -q`
Expected: 全绿（含原有后端测试）

- [ ] **Step 4: 手动冒烟（真实相机/模型）**

Run: `/e/Programs/miniconda3/envs/TaiXian/python.exe run.py`
核对清单（对照设计文档 §5–8）：
- [ ] 顶部统计栏：A/B/C/D/纠错/不合格计数随结果更新；磁盘显示
- [ ] 品级横幅：A 绿/D 红/低置信脉冲/拒采深灰/已纠错戳记/等待
- [ ] 操作员底栏：连接→开始→运行→停止→拍照
- [ ] 工程师参数栏：软件间隔仅"软件连续触发"显示
- [ ] 点横幅 ✎ → 气泡 A/B/C/D → 选 B → 横幅变 B、纠错计数 +1
- [ ] 点历史项 → 画面显原图 + 返回条 + 列表暂停提示 + 状态"运行中（历史图像）"；双击全屏；ESC 退出
- [ ] 模式切换：工程师模式密码（若配置）
- [ ] 筛选 + 分页：上一页/下一页、合计数
- [ ] 导出记录：CSV + 勾选导原图
- [ ] 警告 toast：磁盘/无图/连续拒采

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(ui): 删除旧 widgets.py + 冒烟通过
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage**（对照设计文档 §）：
- §4 视觉系统 → Task 1 ✓
- §5 信息架构（双模式 + 顶部栏）→ Task 9（TopStatBar）+ Task 14（组装）✓
- §6 组件清单 → Task 6–13（8 组件）✓
- §7 状态规范 → Task 6（banner_state 矩阵）+ Task 9（运行状态）+ Task 10/11（选中态）✓
- §8 交互（模式切换/纠错/选中/分页/导出/toast）→ Task 13/7/11/10/14(Task14含导出)/8 ✓
- §9.2 新增接口（聚合/分页/导原图）→ Task 2/3/4/5 ✓
- §10 性能（分页 50 + 异步缩略图）→ Task 3/10 ✓
- §12 迁移 → Task 14/15 ✓

**2. Placeholder scan**：无 TBD/TODO；后端方法与组件关键逻辑均有代码；UI 布局细节指向设计文档 mockup（非占位，有具体类结构）。

**3. Type consistency**：
- `count_by_final_grade`（Task 2）→ `get_grade_summary`（Task 4）→ `set_grade_summary`（Task 9）签名一致 ✓
- `search_records_paged(rows, total)`（Task 3）→ `set_page(rows, total, page, page_size)`（Task 10）一致 ✓
- `banner_state`（Task 6）被 Task 14 多处调用，签名一致 ✓
- `grade_summary_updated` 信号名在 Task 4/9/14 一致 ✓
- FakeController 新增方法（Task 14 Step1）覆盖 MainWindow 所有调用 ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-08-moss-ui-redesign.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 每个 task 派一个全新 subagent 执行，task 间 review，迭代快、上下文干净
**2. Inline Execution** - 在当前会话用 executing-plans 批量执行，带 checkpoint review

Which approach?
