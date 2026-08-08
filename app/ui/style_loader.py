"""style.qss 加载器（单一入口）。

职责：
1. 以 utf-8 读取 app/ui/style.qss（文件含中文注释，勿用系统默认编码）；
2. 把 QSS 里的 `__RES__` 占位符替换成 resources 目录的绝对路径（正斜杠），
   使 `image: url(__RES__/xxx.svg)` 在任何启动目录下都能解析
   （Qt QSS 的 url() 相对路径按进程 CWD 解析，依赖 chdir 太脆）。

用法：
    from app.ui.style_loader import load_stylesheet
    load_stylesheet(app)            # 直接 setStyleSheet

    # 需要二次加工（如测试脚本替换首选字体）时拿文本：
    from app.ui.style_loader import stylesheet_text
    app.setStyleSheet(stylesheet_text().replace(...))
"""
import os

_DIR = os.path.dirname(os.path.abspath(__file__))


def stylesheet_text() -> str:
    """读取 style.qss 并替换资源路径占位符，返回可 setStyleSheet 的文本。"""
    with open(os.path.join(_DIR, "style.qss"), "r", encoding="utf-8") as f:
        qss = f.read()
    res_dir = os.path.join(_DIR, "resources").replace(os.sep, "/")
    return qss.replace("__RES__", res_dir)


def load_stylesheet(app) -> bool:
    """app.setStyleSheet(stylesheet_text())。返回是否成功（文件缺失返回 False）。"""
    qss_file = os.path.join(_DIR, "style.qss")
    if not os.path.exists(qss_file):
        return False
    app.setStyleSheet(stylesheet_text())
    return True
