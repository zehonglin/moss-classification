"""图像质量检查（过曝/欠曝/模糊）测试。"""

import numpy as np
from PIL import Image

from app.services.quality_service import analyze_image


def _pil_from_gray(gray: np.ndarray) -> Image.Image:
    return Image.fromarray(gray.astype(np.uint8), "L").convert("RGB")


def test_sharp_image_passes():
    rng = np.random.default_rng(42)
    gray = rng.integers(0, 256, size=(256, 256), dtype=np.uint8)
    status, reason = analyze_image(
        _pil_from_gray(gray),
        blur_threshold=50.0,
        overexposure_threshold=235.0,
        underexposure_threshold=25.0,
    )
    assert status == "ok"
    assert reason is None


def test_blurred_image_rejected():
    gray = np.full((256, 256), 128, dtype=np.uint8)
    status, reason = analyze_image(
        _pil_from_gray(gray),
        blur_threshold=50.0,
        overexposure_threshold=235.0,
        underexposure_threshold=25.0,
    )
    assert status == "rejected_blur"
    assert "模糊" in reason


def test_overexposed_image_rejected():
    gray = np.full((256, 256), 250, dtype=np.uint8)
    status, reason = analyze_image(
        _pil_from_gray(gray),
        blur_threshold=50.0,
        overexposure_threshold=235.0,
        underexposure_threshold=25.0,
    )
    assert status == "rejected_overexposed"
    assert "过曝" in reason


def test_underexposed_image_rejected():
    gray = np.full((256, 256), 5, dtype=np.uint8)
    status, reason = analyze_image(
        _pil_from_gray(gray),
        blur_threshold=50.0,
        overexposure_threshold=235.0,
        underexposure_threshold=25.0,
    )
    assert status == "rejected_underexposed"
    assert "欠曝" in reason


def test_quality_check_config_defaults(tmp_path):
    from app.utils.config_manager import ConfigManager

    cm = ConfigManager(str(tmp_path / "config.json"))
    assert cm.get("quality_check.enabled") is True
    assert cm.get("quality_check.blur_threshold") == 50.0
    assert cm.get("quality_check.overexposure_threshold") == 235.0
    assert cm.get("quality_check.underexposure_threshold") == 25.0
