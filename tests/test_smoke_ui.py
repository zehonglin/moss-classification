"""Task 15: UI 冒烟测试。

目标：单测粒度太细容易漏掉装配问题——这里做"端到端冒烟"：
    1. 构造 MainWindow（FakeController connected=True，模拟相机已连接）
    2. 切工程师模式 → 切回操作员模式（验证布局重排不崩、共享组件未被销毁）
    3. 触发 _on_page_change(1)（验证 controller.search_records_paged 接线）
    4. 断言关键组件 banner 存在 + 模式回切成功

冒烟不等价于单测：不验证业务正确性，只验证"装配正确、不崩"。
真实相机/模型的全流程冒烟见 task-15-report.md 的现场清单。
"""

import json

from app.ui.main_window import MainWindow
from app.utils.config_manager import ConfigManager
from tests.fakes import FakeController


def test_main_window_constructs_both_modes(tmp_path):
    """构造 → 双模式切换 + 分页刷新 → banner 存在、不崩。"""
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps(
            {
                "camera_settings": {"driver_type": "mock"},
                "model_settings": {"confidence_threshold": 0.6},
                "ui": {"engineer_mode_password": ""},
            }
        ),
        encoding="utf-8",
    )
    win = MainWindow(ConfigManager(str(p)), FakeController(connected=True))

    # 双模式切换（覆盖布局重排 + 共享组件 reparent）
    win._switch_mode("engineer")
    assert win._mode == "engineer"
    win._switch_mode("operator")
    assert win._mode == "operator"

    # 切换后共享组件实例仍存活（未被中间容器 GC 连带销毁）
    assert win.banner is not None
    assert win.camera is not None
    assert win.history is not None
    assert win.sidebar is not None

    # 分页刷新（触发 controller.search_records_paged → history.set_page）
    win._on_page_change(1)
    assert win._page == 1
