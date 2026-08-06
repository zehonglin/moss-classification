"""图像质量检查：过曝/欠曝（灰度均值）+ 模糊（Laplacian 方差）。

拒采帧仍会保存原图与缩略图并入库（quality_status 标记），但不产出品级。
"""

import numpy as np
from PIL import Image


def _to_gray(pil_image: Image.Image) -> np.ndarray:
    return np.asarray(pil_image.convert("L"), dtype=np.uint8)


def _laplacian_variance(gray: np.ndarray) -> float:
    """3×3 Laplacian 核方差（经典无参考清晰度度量）。"""
    h, w = gray.shape
    if h < 3 or w < 3:
        return 0.0
    center = gray[1:-1, 1:-1].astype(np.float32)
    lap = (
        center * -4
        + gray[1:-1, :-2].astype(np.float32)
        + gray[1:-1, 2:].astype(np.float32)
        + gray[:-2, 1:-1].astype(np.float32)
        + gray[2:, 1:-1].astype(np.float32)
    )
    return float(lap.var())


def analyze_image(
    pil_image: Image.Image,
    blur_threshold: float = 50.0,
    overexposure_threshold: float = 235.0,
    underexposure_threshold: float = 25.0,
) -> tuple:
    """返回 (status, reason)。status: ok / rejected_blur / rejected_overexposed / rejected_underexposed。"""
    gray = _to_gray(pil_image)
    mean = float(gray.mean())

    if mean >= overexposure_threshold:
        return "rejected_overexposed", f"画面过曝（灰度均值 {mean:.0f} ≥ {overexposure_threshold:.0f}）"
    if mean <= underexposure_threshold:
        return "rejected_underexposed", f"画面欠曝（灰度均值 {mean:.0f} ≤ {underexposure_threshold:.0f}）"

    lap_var = _laplacian_variance(gray)
    if lap_var < blur_threshold:
        return "rejected_blur", f"画面模糊（Laplacian 方差 {lap_var:.1f} < {blur_threshold:.1f}）"

    return "ok", None
