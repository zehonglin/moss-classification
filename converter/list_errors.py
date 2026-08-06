"""列出验证集误判样本（真实 != 预测）。可筛选特定误判方向，便于人工复核。"""
import os
import argparse
import torch
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from build_model import build_model


def main(model_path, data_root, src, dst, num_workers=2):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    ckpt = torch.load(model_path, map_location=device, weights_only=False)
    classes = ckpt['classes']
    img_size = ckpt.get('img_size', 224)
    n = len(classes)

    arch = ckpt.get('architecture', 'mobilenet_v2')
    model = build_model(arch, n, ckpt['model_state_dict'])
    model.load_state_dict(ckpt['model_state_dict'])
    model = model.to(device).eval()

    tfm = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    ds = datasets.ImageFolder(os.path.join(data_root, 'val'), transform=tfm)
    loader = DataLoader(ds, batch_size=32, shuffle=False, num_workers=num_workers)
    names = ds.classes

    res = []
    with torch.no_grad():
        i = 0
        for x, y in loader:
            _, p = torch.max(model(x.to(device)), 1)
            for tt, pp in zip(y.numpy(), p.cpu().numpy()):
                res.append((ds.samples[i][0], names[tt], names[pp]))
                i += 1

    errors = [r for r in res if r[1] != r[2]]
    if src and dst:
        errors = [r for r in errors if r[1] == src and r[2] == dst]
        print(f"=== {src}→{dst} 误判 ({len(errors)} 张) ===")
    else:
        print(f"=== 全部误判 ({len(errors)}/{len(res)}) ===")

    for path, tr, pr in sorted(errors):
        print(f"{tr}→{pr}: {path}")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description="列验证集误判样本")
    p.add_argument('--model', default='models/mobilenetv2_best.pth')
    p.add_argument('--data-root', default='data/dataset')
    p.add_argument('--from', dest='src', default=None, help='筛选：真实标签（如 C）')
    p.add_argument('--to', dest='dst', default=None, help='筛选：预测标签（如 A）')
    p.add_argument('--workers', type=int, default=2, help='DataLoader 进程数（Windows 受限环境可设 0）')
    args = p.parse_args()
    main(args.model, args.data_root, args.src, args.dst, num_workers=args.workers)
