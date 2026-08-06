import os

# Qt 测试必须无窗口运行（无显示器/CI 环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
