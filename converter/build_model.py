"""模型构建工具：按 checkpoint 的 architecture 字段构建模型（torchvision/timm 统一）。"""

import torch


def build_model(arch, num_classes, state_dict):
    """根据 architecture 构建模型骨架（不含加载权重）。

    - mobilenet_v2 或 mobilenet* 且 state_dict 含 features.* 键 → torchvision MobileNetV2
    - 其他 → timm.create_model（efficientnet_b0 / resnet50 / convnext_tiny ...）
    """
    al = str(arch).lower()
    if al == "mobilenet_v2" or (
        al.startswith("mobilenet") and any(k.startswith("features.") for k in state_dict.keys())
    ):
        from torchvision import models as tv_models

        model = tv_models.mobilenet_v2(weights=None)
        model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, num_classes)
        return model
    import timm

    return timm.create_model(al, pretrained=False, num_classes=num_classes)
