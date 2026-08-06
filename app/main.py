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

    # Load and apply stylesheet
    qss_file = "app/ui/style.qss"
    if os.path.exists(qss_file):
        with open(qss_file, "r") as f:
            app.setStyleSheet(f.read())
        logging.info(f"Loaded stylesheet: {qss_file}")
    else:
        logging.warning(f"Stylesheet file '{qss_file}' not found.")

    window = MainWindow(config_manager)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
