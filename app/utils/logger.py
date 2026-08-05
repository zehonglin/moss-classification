import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger():
    """
    配置全局日志记录器
    """
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, "app.log")

    # 创建一个格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 获取根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 如果已经有处理器，则不重复添加，避免日志重复打印
    if logger.hasHandlers():
        logger.handlers.clear()

    # 创建文件处理器 (带日志轮转)
    # 每个日志文件最大10MB，保留5个备份
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 将处理器添加到根日志记录器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logging.info("Logger has been configured.")

