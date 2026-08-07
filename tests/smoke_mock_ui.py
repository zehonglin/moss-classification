"""Task 15: mock 冒烟脚本。

区别于 test_smoke_ui.py（用 FakeController）——这里走真实装配链：
    ConfigManager(driver_type=mock) + SystemController + MainWindow + show()

offscreen 下 show() 不真显示，但能验证：
    - SystemController 的真实信号在 mock 驱动下能正确接线到 MainWindow
    - QApplication 样式加载
    - 双模式切换在真实 controller 上下文下不抛异常
    - closeEvent 调 shutdown 不崩

用法：/e/Programs/miniconda3/envs/TaiXian/python.exe tests/smoke_mock_ui.py
退出码 0 = 通过；非 0 = 失败（含异常 traceback）。
"""
import json
import os
import sys
import tempfile
import traceback

# offscreen 模式（无显示器也能跑）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 项目根加入 sys.path（直接 run 脚本时不走 run.py）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from app.controllers.system_controller import SystemController
    from app.ui.main_window import MainWindow
    from app.utils.config_manager import ConfigManager

    app = QApplication.instance() or QApplication([])

    # 加载样式表（与 app/main.py 一致）
    qss = os.path.join(ROOT, "app", "ui", "style.qss")
    if os.path.exists(qss):
        with open(qss, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    # 写一份 mock 驱动的临时 config（不污染用户 config.json）
    cfg_dir = tempfile.mkdtemp(prefix="moss_smoke_")
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

    try:
        cfg = ConfigManager(cfg_path)
        ctrl = SystemController(cfg)
        win = MainWindow(cfg, ctrl)
        win.show()
        app.processEvents()

        # 双模式切换
        win._switch_mode("engineer")
        app.processEvents()
        win._switch_mode("operator")
        app.processEvents()

        # 分页刷新（真实 SystemController 的 DB 路径）
        win._on_page_change(1)
        app.processEvents()

        # 关闭（触发 closeEvent → ctrl.shutdown）
        win.close()
        app.processEvents()
        print("[smoke] OK: MainWindow + SystemController(mock) 启动/双模式/关闭 均无异常")
        return 0
    except Exception:
        print("[smoke] FAIL:")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
