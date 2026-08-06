"""评估模型在验证集表现：总体准确率 + 混淆矩阵 + 各类 precision/recall/F1。"""
import os
import argparse
import torch
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from build_model import build_model


def main(model_path, data_root, batch_size=32, num_workers=2):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    ckpt = torch.load(model_path, map_location=device, weights_only=False)
    classes = ckpt['classes']
    img_size = ckpt.get('img_size', 224)
    n = len(classes)

    arch = ckpt.get('architecture', 'mobilenet_v2')
    print(f"架构: {arch}")
    model = build_model(arch, n, ckpt['model_state_dict'])
    model.load_state_dict(ckpt['model_state_dict'])
    model = model.to(device).eval()

    val_t = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    val_ds = datasets.ImageFolder(os.path.join(data_root, 'val'), transform=val_t)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=num_workers)
    names = val_ds.classes  # ImageFolder sorted，与 model 输出索引对齐

    matrix = [[0] * n for _ in range(n)]  # [true][pred]
    correct = total = 0
    with torch.no_grad():
        for x, y in val_loader:
            x, y = x.to(device), y.to(device)
            _, p = torch.max(model(x), 1)
            for t, pr in zip(y.cpu().numpy(), p.cpu().numpy()):
                matrix[t][pr] += 1
                correct += (t == pr)
                total += 1

    print(f"img_size={img_size} | 验证集 {total} 张")
    print(f"总体准确率: {correct/total:.4f} ({correct}/{total})\n")

    print("混淆矩阵 (行=真实, 列=预测):")
    print("真实\\预测  " + "  ".join(f"{c:>5}" for c in names))
    for i, name in enumerate(names):
        print(f"  {name:>5}   " + "  ".join(f"{matrix[i][j]:>5}" for j in range(n)))

    print(f"\n各类别 (召回率=该类被认出的比例):")
    print(f"{'类别':>5} {'样本':>5} {'召回':>7} {'精确':>7} {'F1':>7}")
    for i, name in enumerate(names):
        tp = matrix[i][i]
        row = sum(matrix[i])
        col = sum(matrix[j][i] for j in range(n))
        rec = tp / row if row else 0
        prec = tp / col if col else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
        print(f"{name:>5} {row:>5} {rec:>7.3f} {prec:>7.3f} {f1:>7.3f}")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description="苔藓模型评估（混淆矩阵）")
    p.add_argument('--model', default='models/mobilenetv2_best.pth')
    p.add_argument('--data-root', default='data/dataset')
    p.add_argument('--workers', type=int, default=2, help='DataLoader 进程数（Windows 受限环境可设 0）')
    args = p.parse_args()
    main(args.model, args.data_root, num_workers=args.workers)
