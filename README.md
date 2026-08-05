# 苔藓识别系统 (Moss Recognition System)

## 项目简介

这是一个基于深度学习的工业级苔藓识别桌面应用程序。该系统旨在通过工业相机实时采集苔藓图像，利用先进的计算机视觉模型（EfficientNet）进行分类识别，并结合传送带控制实现自动化检测流程。

本项目经过重构，采用了模块化的 MVC 架构，支持硬件抽象（可切换模拟/真实硬件）、SQLite 数据存储以及现代化的 PySide6 用户界面。

## 主要功能

*   **实时识别**: 集成 PyTorch + timm，支持 EfficientNet 等主流模型，实现毫秒级推理。
*   **硬件控制**:
    *   **相机**: 支持工业相机图像采集（目前提供 Mock 模拟驱动，可扩展海康/巴斯勒 SDK）。
    *   **传送带**: 支持 PLC/传送带启停与速度控制。
*   **数据记录**: 自动将识别结果、置信度及图像路径存入 SQLite 数据库。
*   **人工纠错**: 提供界面允许操作员对识别结果进行修正，并更新数据库，为后续模型迭代积累数据。
*   **历史回溯**: 实时显示最近的检测记录与缩略图。

## 系统架构

项目采用分层架构设计：

*   **UI 层 (`app/ui`)**: 基于 PySide6 的图形界面，负责展示与交互。
*   **控制层 (`app/controllers`)**: `SystemController` 负责协调硬件、AI 服务与 UI，管理系统状态。
*   **服务层 (`app/services`)**:
    *   `ModelService`: 封装 AI 模型加载与推理逻辑。
    *   `DatabaseService`: 管理 SQLite 数据库读写。
*   **核心层 (`app/core`)**: 定义 `BaseCamera` 和 `BaseConveyor` 接口，实现硬件解耦。
*   **驱动层 (`app/drivers`)**: 具体的硬件驱动实现（如 `MockCamera`）。

## 目录结构

```
root/
├── app/
│   ├── core/           # 核心接口 (Interfaces)
│   ├── drivers/        # 硬件驱动 (Mock/Real)
│   ├── ui/             # 界面组件 (MainWindow, Widgets)
│   ├── controllers/    # 业务逻辑控制
│   ├── services/       # 后台服务 (AI, DB)
│   ├── utils/          # 工具类 (Config)
│   └── main.py         # 应用入口
├── config/
│   └── config.json     # 系统配置文件
├── data/               # 数据存储 (Images, SQLite DB)
├── models/             # 模型文件存放目录
├── run.py              # 启动脚本
└── README.md           # 项目文档
```

## 环境要求

*   **操作系统**: Windows / Linux / macOS
*   **Python 版本**: 3.9+
*   **依赖库**:
    *   PySide6
    *   torch, torchvision
    *   timm
    *   Pillow
    *   requests

## 安装与运行

1.  **克隆项目或下载源码**

2.  **安装依赖**
    ```bash
    pip install PySide6 torch torchvision timm Pillow requests
    ```

3.  **运行程序**
    在项目根目录下执行：
    ```bash
    python run.py
    ```

## 配置说明

系统配置文件位于 `config/config.json`。首次运行会自动生成默认配置。

```json
{
    "camera_settings": {
        "driver_type": "mock",         // "mock" 或 "hikvision"
        "capture_frequency_ms": 1000,  // 采集频率
        "exposure": "auto"             // 曝光设置: "auto" 或 整数(微秒)
    },
    "conveyor_settings": {
        "speed_mm_per_s": 50           // 传送带速度
    },
    "model_settings": {
        "current_model_name": "efficientnet_b0", // 使用的模型名称
        "models_directory": "models/"            // 模型下载/加载目录
    },
    "data_paths": {
        "collected_data_directory": "data/images/", // 图片保存路径
        "db_filename": "data/moss.db"               // 数据库路径
    }
}
```

## 开发指南

### 1. 相机驱动配置

本系统内置了 **Mock 模拟相机** 和 **海康威视 (Hikvision)** 工业相机驱动。

**启用海康威视相机：**

1.  确保已安装海康威视 MVS 客户端（提供必要的 DLL 运行时）。
2.  修改 `config/config.json`：
    ```json
    "camera_settings": {
        "driver_type": "hikvision",  // 设置为 "hikvision"
        "capture_frequency_ms": 1000
    }
    ```
3.  如果系统检测不到 MVS 运行时，程序会自动回退到 Mock 模式。

**添加其他相机驱动：**

1.  在 `app/drivers/` 下创建新驱动文件（如 `basler_driver.py`），实现 `BaseCamera` 接口。
2.  在 `app/controllers/system_controller.py` 中注册新驱动的加载逻辑。

### 2. AI 模型管理

本系统支持 **在线下载模型** 和 **加载本地自定义模型**。

**在线模型：**
系统基于 `timm` 库，支持下载并使用其提供的预训练模型（如 `efficientnet_b0`, `resnet50` 等）。
*   在界面下拉菜单中选择模型，系统会自动下载。
*   下载后的模型保存在 `models/hub` 目录下。

**自定义模型 (本地训练)：**
您可以加载自己训练的 `.pth` 或 `.pt` 权重文件。

1.  **文件命名**：为了让系统自动识别模型架构，请在文件名前加上架构名称前缀。
    *   `resnet50_my_model.pth` -> 识别为 **ResNet50**
    *   `mobilenetv3_large_100_custom.pt` -> 识别为 **MobileNetV3**
    *   `my_model.pth` (无前缀) -> 默认识别为 **EfficientNet-B0**
2.  **文件放置**：将文件直接放入项目根目录下的 `models/` 文件夹中。
3.  **加载**：重启程序或刷新下拉菜单，您的模型将出现在列表中，选择即可即时切换。

## 许可证

MIT License
