import sys
import os
import logging
from PySide6.QtWidgets import QApplication, QMessageBox
from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigError, ConfigManager
from app.utils.logger import setup_logger

def main():
    # Setup logger first
    setup_logger()

    app = QApplication(sys.argv)

    # Load Config（损坏配置必须显式报错退出，禁止静默回退默认值）
    try:
        config_manager = ConfigManager()
    except ConfigError as e:
        QMessageBox.critical(None, "配置错误", str(e))
        logging.error(f"Config error: {e}")
        sys.exit(1)

    # Load and apply stylesheet（统一走 style_loader：utf-8 + __RES__ 资源路径替换）
    from app.ui.style_loader import load_stylesheet

    if load_stylesheet(app):
        logging.info("Loaded stylesheet: app/ui/style.qss")
    else:
        logging.warning("Stylesheet file 'app/ui/style.qss' not found.")

    try:
        window = MainWindow(config_manager)
    except (ImportError, ValueError) as e:
        # 相机驱动初始化失败：明确报错退出，禁止静默降级
        QMessageBox.critical(None, "启动失败", f"相机驱动初始化失败: {e}\n请检查相机 SDK 与配置。")
        logging.error(f"Camera driver init failed: {e}")
        sys.exit(1)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
