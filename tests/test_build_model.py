"""converter 模型构建（按 checkpoint architecture 参数化）测试。"""

import torch

from converter.build_model import build_model


def test_build_model_torchvision_mobilenet_v2():
    sd = {"features.0.0.weight": torch.zeros(32, 3, 3, 3)}
    model = build_model("mobilenet_v2", 4, sd)
    assert model.classifier[1].out_features == 4


def test_build_model_timm_arch():
    model = build_model("efficientnet_b0", 4, {})
    assert model.classifier.out_features == 4
