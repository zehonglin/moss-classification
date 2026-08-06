"""导出 PyTorch 模型为 ONNX（产线部署用）。

产线推理走 onnxruntime，不再依赖 torch/timm（部署瘦身）。
导出后生成同名 .json sidecar（classes/img_size/architecture），并自带数值校验。

用法:
    python converter/export_onnx.py models/mobilenetv2_best.pth
    python converter/export_onnx.py models/xxx.pth -o models/xxx.onnx
"""
import argparse
import os
import json
import torch


KNOWN_ARCHS = [
    'mobilenetv3_large_100', 'mobilenetv3_small_100',
    'mobilenetv2_100', 'mobilenet_v2', 'mobilenetv3', 'mobilenet',
    'efficientnet_b0', 'efficientnet_b1', 'efficientnet_b2',
    'resnet18', 'resnet34', 'resnet50',
    'vit_base_patch16_224',
]


def guess_arch(filename):
    name = os.path.basename(filename).lower()
    for a in KNOWN_ARCHS:
        if name.startswith(a):
            return a
    return None


def is_torchvision_sd(sd):
    return any(k.startswith('features.') for k in sd.keys())


def detect_num_classes(sd):
    for k in sd.keys():
        if k.endswith(('classifier.weight', 'fc.weight', 'head.weight', 'classifier.1.weight')):
            return sd[k].shape[0]
    return 1000


def build_model(arch, num_classes, state_dict):
    from torchvision import models as tv_models
    import timm
    al = arch.lower()
    if al == 'mobilenet_v2' or (al.startswith('mobilenet') and is_torchvision_sd(state_dict)):
        m = tv_models.mobilenet_v2(weights=None)
        m.classifier[1] = torch.nn.Linear(m.classifier[1].in_features, num_classes)
        return m
    return timm.create_model(al, pretrained=False, num_classes=num_classes)


def export(pth_path, onnx_path=None, opset=17):
    if onnx_path is None:
        onnx_path = os.path.splitext(pth_path)[0] + '.onnx'

    checkpoint = torch.load(pth_path, map_location='cpu', weights_only=False)
    if isinstance(checkpoint, dict):
        state_dict = checkpoint.get('model_state_dict') or checkpoint.get('state_dict') or checkpoint
        arch = checkpoint.get('architecture') or checkpoint.get('arch')
        classes = checkpoint.get('classes')
        img_size = checkpoint.get('img_size', 224)
    else:
        state_dict = checkpoint
        arch, classes, img_size = None, None, 224

    if not arch:
        arch = guess_arch(pth_path)
        if not arch:
            raise ValueError("无法确定架构：checkpoint 无 architecture 字段且文件名无法识别。")
        print(f"[警告] checkpoint 未声明 architecture，按文件名推断为 '{arch}'")

    num_classes = detect_num_classes(state_dict)
    model = build_model(arch, num_classes, state_dict)
    model.load_state_dict(state_dict, strict=True)
    model.eval()

    dummy = torch.randn(1, 3, img_size, img_size)
    torch.onnx.export(
        model, dummy, onnx_path,
        input_names=['input'], output_names=['logits'],
        dynamic_axes={'input': {0: 'batch'}, 'logits': {0: 'batch'}},
        opset_version=opset,
        dynamo=False,  # 用传统 exporter（torch 2.9 默认 dynamo 需 onnxscript，传统 exporter 无需）
    )
    print(f"[OK] 导出 ONNX: {onnx_path} ({os.path.getsize(onnx_path)/1024/1024:.1f}MB)")

    json_path = os.path.splitext(onnx_path)[0] + '.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({'architecture': arch, 'classes': classes, 'img_size': img_size,
                   'num_classes': num_classes}, f, ensure_ascii=False, indent=2)
    print(f"[OK] sidecar: {json_path}")

    # 数值校验（需 onnxruntime）
    try:
        import onnxruntime as ort
        import numpy as np
        sess = ort.InferenceSession(onnx_path, providers=['CPUExecutionProvider'])
        test = np.random.randn(1, 3, img_size, img_size).astype(np.float32)
        torch_out = model(torch.from_numpy(test)).detach().numpy()
        onnx_out = sess.run(None, {'input': test})[0]
        diff = float(np.abs(torch_out - onnx_out).max())
        print(f"[校验] torch vs onnx 最大差异: {diff:.2e}  {'✓ 一致' if diff < 1e-3 else '✗ 差异过大'}")
        if diff >= 1e-3:
            raise RuntimeError("ONNX 数值校验失败")
    except ImportError:
        print("[跳过] 未装 onnxruntime，跳过数值校验（pip install onnxruntime 后可校验）")

    return onnx_path


if __name__ == '__main__':
    p = argparse.ArgumentParser(description="导出 PyTorch .pth 为 ONNX（产线部署）")
    p.add_argument('pth_path', help='输入 .pth 模型路径')
    p.add_argument('-o', '--output', default=None, help='输出 .onnx 路径（默认同名）')
    p.add_argument('--opset', type=int, default=17)
    args = p.parse_args()
    export(args.pth_path, args.output, args.opset)
