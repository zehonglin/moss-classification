"""苔藓品级分类训练（命令行）。

自动：一级/二级/三级/四级 → A/B/C/D 映射 + train/val 分层划分 → 迁移学习训练 → 保存 checkpoint。

用法:
    python converter/train_moss.py
    python converter/train_moss.py --img-size 224 --epochs 30 --batch-size 32
"""
import os
import sys
import random
import shutil
import argparse
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms

# 中文品级 → 英文标签
LABEL_MAP = {'一级': 'A', '二级': 'B', '三级': 'C', '四级': 'D'}


def prepare_data(src_root, dst_root, val_ratio=0.2, seed=42):
    """把 一级/二级/三级/四级 分层抽样复制到 dst_root/{train,val}/{A,B,C,D}/。不动原始数据。"""
    random.seed(seed)
    for split in ('train', 'val'):
        for lbl in LABEL_MAP.values():
            os.makedirs(os.path.join(dst_root, split, lbl), exist_ok=True)

    stats = {}
    for cn, en in LABEL_MAP.items():
        src_dir = os.path.join(src_root, cn)
        if not os.path.isdir(src_dir):
            print(f"[警告] 未找到目录 {src_dir}，跳过 {cn}")
            continue
        files = sorted(f for f in os.listdir(src_dir)
                       if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp')))
        random.shuffle(files)
        n_val = max(1, int(len(files) * val_ratio))
        for f in files[n_val:]:
            shutil.copy(os.path.join(src_dir, f), os.path.join(dst_root, 'train', en, f))
        for f in files[:n_val]:
            shutil.copy(os.path.join(src_dir, f), os.path.join(dst_root, 'val', en, f))
        stats[en] = {'train': len(files) - n_val, 'val': n_val}
    return stats


def train(arch, img_size, batch_size, epochs, lr, data_root, output_path, num_workers=2):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"架构: {arch} | 设备: {device} | img_size: {img_size}")

    train_t = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.RandomResizedCrop(img_size, scale=(0.7, 1.0)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.RandomRotation(25),
        transforms.ColorJitter(brightness=0.25, contrast=0.25, saturation=0.25, hue=0.08),
        transforms.RandomGrayscale(p=0.05),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    val_t = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    train_ds = datasets.ImageFolder(os.path.join(data_root, 'train'), transform=train_t)
    val_ds = datasets.ImageFolder(os.path.join(data_root, 'val'), transform=val_t)
    classes = train_ds.classes
    print(f"类别: {classes}")
    print(f"训练集 {len(train_ds)} 张 | 验证集 {len(val_ds)} 张")

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=num_workers)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=num_workers)

    if arch == 'mobilenet_v2':
        # torchvision MobileNetV2（与 model_service 的 torchvision 分支对齐）
        model = models.mobilenet_v2(weights='DEFAULT')
        model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(classes))
    else:
        # 任意 timm 架构：efficientnet_b0 / resnet50 / convnext_tiny / vit_base_patch16_224 ...
        import timm
        model = timm.create_model(arch, pretrained=True, num_classes=len(classes))
    model = model.to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'min', patience=5, factor=0.5)

    best_val_loss = float('inf')
    patience, no_improve = 10, 0
    for epoch in range(epochs):
        # 训练
        model.train()
        tl, tc, tt = 0.0, 0, 0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            out = model(x)
            loss = criterion(out, y)
            loss.backward()
            optimizer.step()
            tl += loss.item() * x.size(0)
            _, p = torch.max(out, 1)
            tt += y.size(0)
            tc += (p == y).sum().item()
        tl /= len(train_ds)
        ta = tc / tt

        # 验证
        model.eval()
        vl, vc, vt = 0.0, 0, 0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(device), y.to(device)
                out = model(x)
                loss = criterion(out, y)
                vl += loss.item() * x.size(0)
                _, p = torch.max(out, 1)
                vt += y.size(0)
                vc += (p == y).sum().item()
        vl /= len(val_ds)
        va = vc / vt
        scheduler.step(vl)
        print(f"Epoch {epoch+1:>2}/{epochs}: train_loss={tl:.4f} acc={ta:.4f} | val_loss={vl:.4f} acc={va:.4f}")

        if vl < best_val_loss:
            best_val_loss = vl
            no_improve = 0
            torch.save({
                'architecture': arch,
                'model_state_dict': model.state_dict(),
                'classes': classes,
                'img_size': img_size,
            }, output_path)
        else:
            no_improve += 1
            if no_improve >= patience:
                print(f"早停 @ epoch {epoch+1}（{patience} epoch 未提升）")
                break

    print(f"\n完成。最优模型 → {output_path}")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description="苔藓品级分类训练")
    p.add_argument('--src', default=r'D:\TaiXian\苔藓原始数据\11.28苔藓', help='原始数据根目录（含 一级/二级/三级/四级）')
    p.add_argument('--data-root', default='data/dataset', help='划分输出目录')
    p.add_argument('--output', default='models/mobilenetv2_best.pth')
    p.add_argument('--img-size', type=int, default=224)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--epochs', type=int, default=30)
    p.add_argument('--lr', type=float, default=2e-4)
    p.add_argument('--arch', default='mobilenet_v2',
                   help="模型架构：mobilenet_v2(torchvision) 或任意 timm 名（efficientnet_b0/resnet50/convnext_tiny/vit_base_patch16_224...）")
    p.add_argument('--val-ratio', type=float, default=0.2)
    p.add_argument('--prepare-only', action='store_true', help='只划分数据不训练')
    args = p.parse_args()

    stats = prepare_data(args.src, args.data_root, args.val_ratio)
    print("数据划分:", stats)
    if args.prepare_only:
        sys.exit(0)
    train(args.arch, args.img_size, args.batch_size, args.epochs, args.lr, args.data_root, args.output)
