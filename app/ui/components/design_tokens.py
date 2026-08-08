"""设计 token 单一来源（v3）。

品级语义（业务口径，2026-08-08 确认）：
    A 良好 / B 中等 / C 较差 / D 不合格 —— 均为正常品级结果。
    "需复检"仅由置信度低于阈值触发，与品级无关。
    质量不合格（模糊/过曝/欠曝）图像正常入库，不用"拒采"措辞。

品级色 ramp 下沉至 700 深度（白字对比度全部 ≥ 4.8:1，达 WCAG AA 正文级；
原 600 档 A/B/C 仅 3.1–3.3:1，横幅小字不达标），并采用 绿→黄→橙→红
等距色阶，保证 A/B 在余光与色弱场景下可区分。

所有 UI 组件（grade_banner / history_list / top_bar / correction_popup）
从这里取色值与文案，杜绝各处硬编码字典漂移。
"""

# 品级 → 色值（700 深度 ramp）
GRADE_COLORS = {
    "A": "#15803d",  # green-700  白字 5.0:1
    "B": "#a16207",  # yellow-700 白字 4.9:1
    "C": "#c2410c",  # orange-700 白字 5.3:1
    "D": "#b91c1c",  # red-700    白字 7.0:1
}

# 品级 → 中文描述词（横幅 / 历史项 / 纠错气泡三处一致）
GRADE_NAMES = {
    "A": "良好",
    "B": "中等",
    "C": "较差",
    "D": "不合格",
}

# 质量不合格原因 → 中文说明（横幅与历史项共用，修复 rejected_blur 原文显示问题）
REJECT_REASONS = {
    "rejected_blur": "图像模糊",
    "rejected_overexposed": "过曝",
    "rejected_underexposed": "欠曝",
}

# 历史项选中态（中性 slate，不占用品级/警告语义色）
SELECTION_BG = "#eef2f7"
SELECTION_BORDER = "#94a3b8"
