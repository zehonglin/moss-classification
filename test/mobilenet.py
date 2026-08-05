import sys
import os
import shutil
import random
import glob
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import models, transforms, datasets
from PIL import Image

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QLineEdit, QSpinBox,
                             QDoubleSpinBox, QTextEdit, QProgressBar, QTabWidget, QSplitter,
                             QMessageBox, QGridLayout, QGroupBox, QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction


# ==========================================
# 后端逻辑：PyTorch 训练线程
# ==========================================

class TrainingWorker(QThread):
    """后台训练线程"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            self.log_signal.emit("=== 开始初始化模型 ===")

            # 参数提取
            img_size = self.config['img_size']
            batch_size = self.config['batch_size']
            epochs = self.config['epochs']
            train_dir = self.config['train_dir']
            val_dir = self.config['val_dir']
            lr = self.config['lr']

            # 检测设备
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            print(f"使用设备: {device}")
            self.log_signal.emit(f"使用设备: {device}")

            # 数据转换
            train_transform = transforms.Compose([
                transforms.Resize((img_size, img_size)),
                transforms.RandomHorizontalFlip(),
                transforms.RandomRotation(20),
                transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.1, hue=0.1),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
            ])



            val_transform = transforms.Compose([
                transforms.Resize((img_size, img_size)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
            ])

            # 加载数据集
            train_dataset = datasets.ImageFolder(train_dir, transform=train_transform)
            val_dataset = datasets.ImageFolder(val_dir, transform=val_transform)

            train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=4)
            val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=4)

            # 获取类别信息
            classes = train_dataset.classes
            num_classes = len(classes)
            self.log_signal.emit(f"检测到 {num_classes} 个类别: {classes}")

            if num_classes < 2:
                self.log_signal.emit("错误：训练集至少需要2个分类文件夹！")
                self.finished_signal.emit()
                return

            # 构建模型
            model = models.mobilenet_v2(pretrained=True)
            # 修改最后一层以适应类别数量
            model.classifier[1] = nn.Linear(model.classifier[1].in_features, num_classes)
            model = model.to(device)

            # 损失函数和优化器
            criterion = nn.CrossEntropyLoss()
            optimizer = optim.Adam(model.parameters(), lr=lr)
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'min', patience=5, factor=0.5)

            best_val_loss = float('inf')
            early_stopping_counter = 0
            patience = 10
            best_model_path = os.path.join(self.config['output_dir'], 'mobilenet_best.pth')

            self.log_signal.emit(f"=== 开始训练 (Epochs: {epochs}, Batch: {batch_size}, LR: {lr}) ===")

            for epoch in range(epochs):
                # 训练阶段
                model.train()
                train_loss = 0
                train_correct = 0
                train_total = 0

                for inputs, labels in train_loader:
                    inputs, labels = inputs.to(device), labels.to(device)

                    # 梯度清零
                    optimizer.zero_grad()

                    # 前向传播
                    outputs = model(inputs)
                    loss = criterion(outputs, labels)

                    # 反向传播和优化
                    loss.backward()
                    optimizer.step()

                    # 统计
                    train_loss += loss.item() * inputs.size(0)
                    _, predicted = torch.max(outputs, 1)
                    train_total += labels.size(0)
                    train_correct += (predicted == labels).sum().item()

                train_loss = train_loss / len(train_loader.dataset)
                train_acc = train_correct / train_total

                # 验证阶段
                model.eval()
                val_loss = 0
                val_correct = 0
                val_total = 0

                with torch.no_grad():
                    for inputs, labels in val_loader:
                        inputs, labels = inputs.to(device), labels.to(device)

                        outputs = model(inputs)
                        loss = criterion(outputs, labels)

                        val_loss += loss.item() * inputs.size(0)
                        _, predicted = torch.max(outputs, 1)
                        val_total += labels.size(0)
                        val_correct += (predicted == labels).sum().item()

                val_loss = val_loss / len(val_loader.dataset)
                val_acc = val_correct / val_total

                # 调整学习率
                scheduler.step(val_loss)

                # 早停和模型保存
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    torch.save({
                        'architecture': 'mobilenet_v2',
                        'model_state_dict': model.state_dict(),
                        'optimizer_state_dict': optimizer.state_dict(),
                        'classes': classes,
                        'img_size': img_size
                    }, best_model_path)
                    early_stopping_counter = 0
                else:
                    early_stopping_counter += 1
                    if early_stopping_counter >= patience:
                        self.log_signal.emit(f"Early stopping triggered after epoch {epoch + 1}")
                        break

                # 更新GUI
                msg = f"Epoch {epoch + 1}: loss={train_loss:.4f}, acc={train_acc:.4f}, val_loss={val_loss:.4f}, val_acc={val_acc:.4f}"
                self.log_signal.emit(msg)
                self.progress_signal.emit(epoch + 1)

            # 保存最终模型
            final_model_path = os.path.join(self.config['output_dir'], 'mobilenet_final.pth')
            torch.save({
                'architecture': 'mobilenet_v2',
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'classes': classes,
                'img_size': img_size
            }, final_model_path)

            self.log_signal.emit(f"=== 训练完成，模型已保存至: {final_model_path} ===")
            self.log_signal.emit(f"最佳模型保存至: {best_model_path}")

        except Exception as e:
            self.log_signal.emit(f"严重错误: {str(e)}")
            import traceback
            self.log_signal.emit(traceback.format_exc())
        finally:
            self.finished_signal.emit()


# ==========================================
# 前端界面：主窗口
# ==========================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 全流程助手: 标注 -> 训练 -> 识别")
        self.resize(1100, 800)

        # 全局状态
        self.image_list = []
        self.current_img_index = 0
        self.dataset_root = ""

        # 预测相关变量
        self.loaded_model = None
        self.model_img_size = 224
        self.class_names = []
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # 主界面布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #ccc; } QTabBar::tab { height: 40px; width: 150px; }")
        layout.addWidget(self.tabs)

        # --- 初始化三个功能页 ---
        self.tab_label = QWidget()
        self.init_labeling_ui()
        self.tabs.addTab(self.tab_label, "1. 数据标注")

        self.tab_train = QWidget()
        self.init_training_ui()
        self.tabs.addTab(self.tab_train, "2. 模型训练")

        self.tab_predict = QWidget()
        self.init_prediction_ui()
        self.tabs.addTab(self.tab_predict, "3. 模型识别")

    # =========================================================
    # Tab 1: 数据标注功能
    # =========================================================
    def init_labeling_ui(self):
        layout = QHBoxLayout(self.tab_label)

        # 左侧：图像显示
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self.img_label = QLabel("请先加载图片文件夹")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setStyleSheet("border: 2px dashed #aaa; background-color: #f8f9fa;")
        self.img_label.setMinimumSize(450, 450)
        left_layout.addWidget(self.img_label)
        self.file_info_label = QLabel("当前文件: 无")
        left_layout.addWidget(self.file_info_label)

        # 右侧：控制面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # 设置区
        gb_setup = QGroupBox("1. 路径设置")
        setup_layout = QVBoxLayout()
        btn_load_src = QPushButton("选择未分类图片源文件夹")
        btn_load_src.clicked.connect(self.load_source_images)
        setup_layout.addWidget(btn_load_src)
        self.lbl_src_count = QLabel("剩余图片: 0")
        setup_layout.addWidget(self.lbl_src_count)

        btn_set_dst = QPushButton("设置数据集保存根目录")
        btn_set_dst.clicked.connect(self.set_dataset_root)
        setup_layout.addWidget(btn_set_dst)
        self.lbl_dst_path = QLabel("目标: 未设置")
        self.lbl_dst_path.setWordWrap(True)
        setup_layout.addWidget(self.lbl_dst_path)
        gb_setup.setLayout(setup_layout)
        right_layout.addWidget(gb_setup)

        # 类别区
        gb_classes = QGroupBox("2. 类别管理 (点击添加)")
        class_layout = QVBoxLayout()
        input_layout = QHBoxLayout()
        self.txt_new_class = QLineEdit()
        self.txt_new_class.setPlaceholderText("输入类别名 (如 cat)")
        btn_add_class = QPushButton("添加")
        btn_add_class.clicked.connect(self.add_class)
        input_layout.addWidget(self.txt_new_class)
        input_layout.addWidget(btn_add_class)
        class_layout.addLayout(input_layout)

        # 滚动区域放按钮
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.btn_container = QWidget()
        self.class_btn_layout = QGridLayout(self.btn_container)
        scroll.setWidget(self.btn_container)
        class_layout.addWidget(scroll)
        gb_classes.setLayout(class_layout)
        right_layout.addWidget(gb_classes)

        # 划分设置
        gb_split = QGroupBox("3. 自动划分")
        split_layout = QHBoxLayout()
        split_layout.addWidget(QLabel("验证集比例:"))
        self.spin_val_ratio = QDoubleSpinBox()
        self.spin_val_ratio.setRange(0.0, 0.5)
        self.spin_val_ratio.setSingleStep(0.1)
        self.spin_val_ratio.setValue(0.2)
        split_layout.addWidget(self.spin_val_ratio)
        gb_split.setLayout(split_layout)
        right_layout.addWidget(gb_split)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    def load_source_images(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片源文件夹")
        if folder:
            exts = ['*.jpg', '*.jpeg', '*.png', '*.bmp']
            self.image_list = []
            for ext in exts:
                self.image_list.extend(glob.glob(os.path.join(folder, ext)))
                self.image_list.extend(glob.glob(os.path.join(folder, ext.upper())))
            self.lbl_src_count.setText(f"剩余图片: {len(self.image_list)}")
            self.current_img_index = 0
            self.show_current_image()

    def set_dataset_root(self):
        folder = QFileDialog.getExistingDirectory(self, "选择数据集根目录")
        if folder:
            self.dataset_root = folder
            self.lbl_dst_path.setText(f"目标: {folder}")
            os.makedirs(os.path.join(folder, 'train'), exist_ok=True)
            os.makedirs(os.path.join(folder, 'val'), exist_ok=True)
            self.refresh_existing_classes()
            # 同步更新Tab2的路径
            self.txt_train_path.setText(os.path.join(folder, 'train'))
            self.txt_val_path.setText(os.path.join(folder, 'val'))

    def refresh_existing_classes(self):
        train_dir = os.path.join(self.dataset_root, 'train')
        if os.path.exists(train_dir):
            classes = [d for d in os.listdir(train_dir) if os.path.isdir(os.path.join(train_dir, d))]
            for c in classes:
                self.create_class_button(c)

    def add_class(self):
        class_name = self.txt_new_class.text().strip()
        if not class_name or not self.dataset_root:
            QMessageBox.warning(self, "提示", "请输入类别名并设置路径")
            return
        for sub in ['train', 'val']:
            os.makedirs(os.path.join(self.dataset_root, sub, class_name), exist_ok=True)
        self.create_class_button(class_name)
        self.txt_new_class.clear()

    def create_class_button(self, class_name):
        for i in range(self.class_btn_layout.count()):
            w = self.class_btn_layout.itemAt(i).widget()
            if w and w.text() == class_name: return

        btn = QPushButton(class_name)
        btn.clicked.connect(lambda: self.move_image_to_class(class_name))
        btn.setStyleSheet("background-color: #e2e3e5; padding: 10px; font-weight: bold;")
        count = self.class_btn_layout.count()
        self.class_btn_layout.addWidget(btn, count // 2, count % 2)

    def show_current_image(self):
        if 0 <= self.current_img_index < len(self.image_list):
            path = self.image_list[self.current_img_index]
            self.file_info_label.setText(
                f"文件 ({self.current_img_index + 1}/{len(self.image_list)}): {os.path.basename(path)}")
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.img_label.setPixmap(pixmap.scaled(self.img_label.size(), Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.img_label.setText("所有图片处理完毕！")
            self.file_info_label.setText("完成")
            self.img_label.clear()

    def move_image_to_class(self, class_name):
        if not self.image_list or self.current_img_index >= len(self.image_list): return
        src_path = self.image_list[self.current_img_index]
        is_val = random.random() < self.spin_val_ratio.value()
        sub = 'val' if is_val else 'train'
        dst_path = os.path.join(self.dataset_root, sub, class_name, os.path.basename(src_path))
        try:
            shutil.move(src_path, dst_path)
            self.current_img_index += 1
            self.lbl_src_count.setText(f"剩余图片: {len(self.image_list) - self.current_img_index}")
            self.show_current_image()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    # =========================================================
    # Tab 2: 模型训练功能
    # =========================================================
    def init_training_ui(self):
        layout = QVBoxLayout(self.tab_train)

        gb_config = QGroupBox("训练参数")
        grid = QGridLayout()

        grid.addWidget(QLabel("训练集路径:"), 0, 0)
        self.txt_train_path = QLineEdit()
        grid.addWidget(self.txt_train_path, 0, 1)
        btn_t = QPushButton("选择");
        btn_t.clicked.connect(lambda: self.select_dir(self.txt_train_path))
        grid.addWidget(btn_t, 0, 2)

        grid.addWidget(QLabel("验证集路径:"), 1, 0)
        self.txt_val_path = QLineEdit()
        grid.addWidget(self.txt_val_path, 1, 1)
        btn_v = QPushButton("选择");
        btn_v.clicked.connect(lambda: self.select_dir(self.txt_val_path))
        grid.addWidget(btn_v, 1, 2)

        param_layout = QHBoxLayout()
        # Epochs
        param_layout.addWidget(QLabel("Epochs:"))
        self.spin_epochs = QSpinBox();
        self.spin_epochs.setValue(20);
        self.spin_epochs.setRange(1, 1000)
        param_layout.addWidget(self.spin_epochs)
        # Batch Size
        param_layout.addWidget(QLabel("Batch Size:"))
        self.spin_batch = QSpinBox();
        self.spin_batch.setValue(8);
        self.spin_batch.setRange(1, 256)
        param_layout.addWidget(self.spin_batch)
        # LR
        param_layout.addWidget(QLabel("学习率:"))
        self.spin_lr = QDoubleSpinBox();
        self.spin_lr.setValue(0.0005);
        self.spin_lr.setDecimals(5);
        self.spin_lr.setSingleStep(0.0001)
        param_layout.addWidget(self.spin_lr)
        # Img Size
        param_layout.addWidget(QLabel("图片大小:"))
        self.spin_size = QSpinBox();
        self.spin_size.setValue(224);
        self.spin_size.setRange(64, 512)
        param_layout.addWidget(self.spin_size)

        grid.addLayout(param_layout, 2, 0, 1, 3)
        gb_config.setLayout(grid)
        layout.addWidget(gb_config)

        self.btn_start = QPushButton("开始训练")
        self.btn_start.setStyleSheet("background-color: #0d6efd; color: white; padding: 10px; font-weight: bold;")
        self.btn_start.clicked.connect(self.start_training)
        layout.addWidget(self.btn_start)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas;")
        layout.addWidget(self.log_text)

    def select_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d: edit.setText(d)

    def start_training(self):
        train_dir = self.txt_train_path.text()
        val_dir = self.txt_val_path.text()
        if not os.path.exists(train_dir) or not os.path.exists(val_dir):
            QMessageBox.critical(self, "错误", "路径不存在")
            return

        config = {
            'train_dir': train_dir, 'val_dir': val_dir,
            'epochs': self.spin_epochs.value(), 'batch_size': self.spin_batch.value(),
            'lr': self.spin_lr.value(), 'img_size': self.spin_size.value(),
            'output_dir': os.path.dirname(train_dir)
        }

        self.progress_bar.setMaximum(config['epochs'])
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.worker = TrainingWorker(config)
        self.worker.log_signal.connect(self.log_text.append)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(lambda: [self.btn_start.setEnabled(True), self.btn_start.setText("开始训练")])
        self.btn_start.setEnabled(False);
        self.btn_start.setText("训练中...")
        self.worker.start()

    # =========================================================
    # Tab 3: 模型识别功能
    # =========================================================
    def init_prediction_ui(self):
        layout = QHBoxLayout(self.tab_predict)

        left_layout = QVBoxLayout()
        self.lbl_pred_img = QLabel("请加载要识别的图片")
        self.lbl_pred_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pred_img.setStyleSheet("border: 2px dashed #666; background-color: #e9ecef;")
        self.lbl_pred_img.setMinimumSize(400, 400)
        left_layout.addWidget(self.lbl_pred_img)
        layout.addLayout(left_layout, stretch=2)

        right_panel = QGroupBox("识别控制台")
        right_layout = QVBoxLayout()

        # 1. 加载模型
        right_layout.addWidget(QLabel("1. 加载模型 (.pth)"))
        btn_model = QPushButton("选择模型文件")
        btn_model.clicked.connect(self.load_model_file)
        right_layout.addWidget(btn_model)
        self.lbl_model_status = QLabel("未加载")
        self.lbl_model_status.setStyleSheet("color: red")
        right_layout.addWidget(self.lbl_model_status)
        right_layout.addSpacing(15)

        # 2. 加载类别 (在PyTorch版本中，类别信息已存在模型文件中)
        right_layout.addWidget(QLabel("2. 类别信息"))
        self.lbl_class_status = QLabel("类别: 未加载")
        self.lbl_class_status.setWordWrap(True)
        right_layout.addWidget(self.lbl_class_status)
        right_layout.addSpacing(15)

        # 3. 识别
        right_layout.addWidget(QLabel("3. 识别图片"))
        btn_pred = QPushButton("选择图片并识别")
        btn_pred.clicked.connect(self.run_prediction)
        btn_pred.setStyleSheet("background-color: #0d6efd; color: white; font-weight: bold; padding: 10px;")
        right_layout.addWidget(btn_pred)

        self.txt_pred_result = QTextEdit()
        self.txt_pred_result.setReadOnly(True)
        self.txt_pred_result.setStyleSheet("font-size: 35px; color: #000000; font-weight: bold;")
        right_layout.addWidget(self.txt_pred_result)

        right_panel.setLayout(right_layout)
        layout.addWidget(right_panel, stretch=1)

    def load_model_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择模型", "", "PyTorch Models (*.pth)")
        if path:
            try:
                self.lbl_model_status.setText("加载中...")
                QApplication.processEvents()

                # 加载模型
                checkpoint = torch.load(path, map_location=self.device)

                # 获取图像大小和类别信息
                self.model_img_size = checkpoint.get('img_size', 224)
                self.class_names = checkpoint.get('classes', [])

                # 创建模型
                self.loaded_model = models.mobilenet_v2(pretrained=False)
                num_classes = len(self.class_names) if self.class_names else 1000
                self.loaded_model.classifier[1] = nn.Linear(self.loaded_model.classifier[1].in_features, num_classes)

                # 加载权重
                self.loaded_model.load_state_dict(checkpoint['model_state_dict'])
                self.loaded_model = self.loaded_model.to(self.device)
                self.loaded_model.eval()

                self.lbl_model_status.setText(f"已加载: {os.path.basename(path)}")
                self.lbl_model_status.setStyleSheet("color: green")

                # 更新类别信息
                if self.class_names:
                    self.lbl_class_status.setText(f"已加载 {len(self.class_names)} 个类别")
                else:
                    self.lbl_class_status.setText("警告：未找到类别信息")

            except Exception as e:
                print(e)
                QMessageBox.critical(self, "错误", str(e))
                import traceback
                print(traceback.format_exc())

    def run_prediction(self):
        if not self.loaded_model:
            QMessageBox.warning(self, "提示", "请先加载模型！")
            return

        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            # 显示图片
            pix = QPixmap(path)
            self.lbl_pred_img.setPixmap(pix.scaled(self.lbl_pred_img.size(), Qt.AspectRatioMode.KeepAspectRatio))

            try:
                # 图像预处理
                transform = transforms.Compose([
                    transforms.Resize((self.model_img_size, self.model_img_size)),
                    transforms.ToTensor(),
                    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
                ])

                # 加载和转换图像
                img = Image.open(path).convert('RGB')
                img_tensor = transform(img).unsqueeze(0).to(self.device)

                # 预测
                with torch.no_grad():
                    output = self.loaded_model(img_tensor)
                    probabilities = torch.nn.functional.softmax(output, dim=1)[0]

                # 获取结果
                confidence, predicted_idx = torch.max(probabilities, 0)
                predicted_idx = predicted_idx.item()
                confidence = confidence.item()

                # 显示类别
                if self.class_names and predicted_idx < len(self.class_names):
                    name = self.class_names[predicted_idx]
                else:
                    name = f"类别 {predicted_idx}"

                # 构建结果显示
                res = f"结果: {name}\n置信度: {confidence:.2%}\n\n详细:\n"

                # 添加所有类别的概率
                probs_list = probabilities.tolist()
                for i, prob in enumerate(probs_list):
                    class_name = self.class_names[i]
                # 添加所有类别的概率
                probs_list = probabilities.tolist()
                for i, prob in enumerate(probs_list):
                    class_name = self.class_names[i] if i < len(self.class_names) else f"类别 {i}"
                    res += f"{class_name}: {prob:.2%}\n"

                self.txt_pred_result.setText(res)

            except Exception as e:
                QMessageBox.critical(self, "错误", f"预测过程中发生错误: {str(e)}")
                import traceback
                print(traceback.format_exc())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())