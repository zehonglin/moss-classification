"""v3 UI 视觉冒烟：离屏渲染 MainWindow 并抓 PNG。

区别于 smoke_mock_ui.py（真实装配链只验证不崩）——本脚本用 FakeController
喂入一批典型数据（各品级 / 低置信度需复检 / 质量异常 / 已改判），抓图验证
v3 设计的落地效果：
    - 操作员模式：品级横幅（新色板 + 品级名 + 置信度条）、正方形取景器、
      顶栏 chip（今日 N 盘 · 通过率）、历史列表（标签/措辞）、底栏按钮状态机
    - 工程师模式：左侧参数栏 + 复用主区域
    - 统计弹层（chip 点开）

用法：
    /e/Programs/miniconda3/envs/TaiXian/python.exe tests/smoke_v3_screenshot.py [输出目录]
默认输出到 %TEMP%/moss_v3_shots。退出码 0 = 通过。
"""
import json
import os
import sys
import tempfile
import traceback

# 默认 offscreen（CI 无显示可用）；MOSS_SHOT_ENGINE=windows 时用真实 Windows
# 引擎 + WA_DontShowOnScreen（不弹窗），字形/字体回退渲染与真实显示一致，
# 适合做人眼验收截图。
_ENGINE = os.environ.get("MOSS_SHOT_ENGINE", "offscreen")
if _ENGINE == "offscreen":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))  # fakes.py
os.chdir(ROOT)

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    tempfile.gettempdir(), "moss_v3_shots"
)


def _fake_frame(side=720):
    """造一张正方形"苔藓托盘"风格的假相机帧。"""
    from PySide6.QtGui import QColor, QImage, QPainter

    img = QImage(side, side, QImage.Format_RGB32)
    img.fill(QColor("#2f4a33"))  # 托盘底
    p = QPainter(img)
    # 8x8 穴盘格子，明暗交替模拟苔藓长势
    cell = side // 8
    for r in range(8):
        for c in range(8):
            shade = 90 + ((r * 7 + c * 13) % 60)
            p.fillRect(
                c * cell + 6,
                r * cell + 6,
                cell - 12,
                cell - 12,
                QColor(60, shade + 60, 70),
            )
    p.end()
    return img


def _rec(rid, pred, conf, quality="ok", corrected=None, ts="2026-08-08T10:2{}:00"):
    return {
        "id": rid,
        "timestamp": ts.format(rid % 10),
        "image_path": None,
        "thumbnail_path": None,
        "prediction": pred,
        "confidence": conf,
        "quality_status": quality,
        "corrected_label": corrected,
    }


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow
    from app.ui.style_loader import stylesheet_text
    from app.utils.config_manager import ConfigManager
    from fakes import FakeController

    app = QApplication.instance() or QApplication([])

    if _ENGINE == "offscreen":
        # offscreen 后端的字体库不枚举系统字体（CJK 全部渲染成方框）；
        # 显式从字体文件加载雅黑即可正常显示中文。仅影响本脚本，不动真实应用。
        from PySide6.QtGui import QFontDatabase

        for font_file in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
            if os.path.exists(font_file):
                QFontDatabase.addApplicationFont(font_file)
                break
        # Segoe UI Symbol：⚠ ✎ ◐ 等符号字形（真实 Windows 靠字体链接回退到它，
        # offscreen 需手动加载，模拟真实显示效果）
        sym = r"C:\Windows\Fonts\seguisym.ttf"
        if os.path.exists(sym):
            QFontDatabase.addApplicationFont(sym)

    qss_text = stylesheet_text()
    if _ENGINE == "offscreen":
        # 已加载的雅黑排在首选，规避 offscreen 下 Segoe UI 无 CJK 字形的问题
        qss_text = qss_text.replace(
            'font-family:"Segoe UI","Microsoft YaHei UI",sans-serif',
            'font-family:"Microsoft YaHei UI","Segoe UI",sans-serif',
        )
    app.setStyleSheet(qss_text)

    cfg_dir = tempfile.mkdtemp(prefix="moss_shot_")
    cfg_path = os.path.join(cfg_dir, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "camera_settings": {"driver_type": "mock"},
                "model_settings": {"confidence_threshold": 0.6},
                "ui": {"engineer_mode_password": ""},
            },
            f,
        )

    os.makedirs(OUT_DIR, exist_ok=True)

    try:
        cfg = ConfigManager(cfg_path)
        ctrl = FakeController(connected=True)
        win = MainWindow(cfg, ctrl)
        win.resize(1600, 900)
        if _ENGINE == "windows":
            # 真实 Windows 引擎但不弹窗：布局/字体回退与真实显示一致
            from PySide6.QtCore import Qt

            win.setAttribute(Qt.WA_DontShowOnScreen)
        win.show()
        app.processEvents()

        # 0) 等待态（初始 wait 横幅 —— 用户开应用第一眼看到的画面，必须验收）
        p0 = os.path.join(OUT_DIR, "v3_wait.png")
        win.grab().save(p0)

        # --- 喂数据：运行态 + 统计 + 相机帧 + 历史记录 ---
        ctrl.status_updated.emit("RUNNING")
        ctrl.grade_summary_updated.emit(
            {"A": 10, "B": 8, "C": 3, "D": 1, "corrected": 1, "rejected": 2}
        )
        ctrl.image_updated.emit(_fake_frame())
        for rec in [
            _rec(1, "A", 0.96),
            _rec(2, "B", 0.88),
            _rec(3, "B", 0.74, corrected="C"),          # 已改判
            _rec(4, "D", 0.91),
            _rec(5, "B", 0.52),                          # 低置信度 → 需复检
            _rec(6, None, None, quality="rejected_blur"),  # 质量异常（已入库）
            _rec(7, "A", 0.97),                          # 最新一条 → 抢横幅
        ]:
            ctrl.result_updated.emit(rec)
            app.processEvents()

        # 1) 操作员模式全窗
        p1 = os.path.join(OUT_DIR, "v3_operator.png")
        win.grab().save(p1)

        # 2) 统计弹层（chip 点开后单独抓弹层）
        win.top_bar._chip.click()
        app.processEvents()
        p2 = os.path.join(OUT_DIR, "v3_stats_popup.png")
        win.top_bar._popup.grab().save(p2)
        win.top_bar._popup.hide()
        app.processEvents()

        # 3) 工程师模式全窗
        win._switch_mode("engineer")
        app.processEvents()
        p3 = os.path.join(OUT_DIR, "v3_engineer.png")
        win.grab().save(p3)

        win.close()
        app.processEvents()
        print("[shot] OK:")
        for p in (p0, p1, p2, p3):
            print("  -", p, os.path.getsize(p), "bytes")
        return 0
    except Exception:
        print("[shot] FAIL:")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
