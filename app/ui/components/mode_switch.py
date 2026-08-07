"""工程师模式密码校验。

- 纯函数 ``check_password`` 判定输入是否满足配置密码
- ``maybe_prompt_password`` 在配置了密码时弹 ``QInputDialog`` 收集输入

配置项 ``ui.engineer_mode_password``：未配置 / 空串 → 放行；配置 → 需精确匹配。
"""


def check_password(input_pwd, configured) -> bool:
    """未配置密码（configured 为 None / 空串）则放行；否则需精确匹配。

    Parameters
    ----------
    input_pwd:
        用户输入的密码。
    configured:
        配置的密码；为 ``None`` 或空串视为未启用密码保护。
    """
    if not configured:
        return True
    return input_pwd == configured


def maybe_prompt_password(parent, configured) -> bool:
    """配置了密码时弹 ``QInputDialog`` 校验；未配置直接返回 ``True``。

    在 offscreen / 阻塞对话框不便测试的环境下，可直接对 ``check_password``
    进行单元测试；此函数为薄封装。
    """
    if not configured:
        return True
    from PySide6.QtWidgets import QInputDialog

    # QInputDialog.TextInput 为 0，Password 为 1
    pwd, ok = QInputDialog.getText(
        parent, "工程师模式", "请输入密码:", QInputDialog.Password
    )
    return bool(ok) and check_password(pwd, configured)
