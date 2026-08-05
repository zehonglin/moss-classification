import sys
import os
import logging
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager
from app.utils.logger import setup_logger

def main():
    # Setup logger first
    setup_logger()

    app = QApplication(sys.argv)

    # Load Config
    config_manager = ConfigManager()

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
