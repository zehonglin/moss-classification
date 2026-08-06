# 苔藓识别系统（Moss Recognition System）

基于深度学习的工业级苔藓品级识别桌面应用。工业相机采集托盘图像，MobileNetV2 分类苔藓覆盖度品级（A/B/C/D），支持光电传感器硬件触发、ONNX 产线部署、滚动归档、置信度拒识与纠错闭环。

## 业务

- **品级**：A / B / C / D，依据健康苔藓覆盖度（A 铺满 → D 几乎无覆盖）
- **输入**：工业相机拍摄的托盘图（~2048×2048，流水线 ~3s/托盘）
- **输出**：整图一个品级 + 置信度

## 产线工作流

```
流水线连续运转（软件不管）
   └─ 托盘到位 → 光电传感器(PNP) → 相机 Line0 上升沿触发抓拍
                                     ↓
              worker 取图 → MobileNetV2 推理 → 存原图(PNG)+缩略图+DB → 界面显示
```

## 架构

- **UI 层** `app/ui`：PySide6 主界面（实时画面、结果、历史、侧边控制）
- **控制层** `app/controllers/system_controller.py`：SystemController 状态机 + SystemWorker（后台取图/推理/存储）
- **服务层** `app/services`：ModelService（.onnx/.pth 双后端）、DatabaseService（SQLite + 滚动归档）
- **核心层** `app/core/interfaces.py`：BaseCamera 抽象（含硬件/软件触发接口）
- **驱动层** `app/drivers`：HikvisionCamera（海康，硬件/软件触发）、MockCamera（开发）、hikvision_sdk/（厂商封装）

## 相机触发（四档）

| 模式 | 相机配置 | 用途 |
|------|---------|------|
| preview | TriggerMode=Off 连续出图 | 预览/调焦 |
| hardware | TriggerMode=On + Line0 上升沿 + Debouncer | **产线**（光电触发） |
| software_single | TriggerSource=Software + 按钮 | 调试单张 |
| software_continuous | TriggerSource=Software + 按间隔 | 调试连续 |

UI 侧边栏切换；DebouncerTime 可调；曝光固定（防拖影，配补光）。

## 识别与存储

- **原图**：`data/images/moss_<时间戳>.png`（PNG 无损，训练/大图查看）
- **缩略图**：`data/images/thumb/moss_<时间戳>.png`（300px，界面展示）
- **DB**：`data/moss.db`，records 表含 thumbnail_path
- **滚动归档**：保留 `storage.retention_days`（默认 60 天）；启动只报告不删，24h 定时清理
- **置信度拒识**：低于 `confidence_threshold`（默认 0.6）标"⚠️需复检"，DB 存原始数据不被污染
- **纠错闭环**：纠错时图片归档到 `data/corrections/<正确标签>/`（ImageFolder 兼容，可直接重训）

## 模型

- 架构：MobileNetV2（torchvision），ImageNet 预训练迁移学习
- 输入：224×224
- 后端：`.pth`（torch，开发）/ `.onnx`（onnxruntime，产线）
- 类别：A/B/C/D（从 checkpoint 的 classes 字段）

## 部署到产线

产线只装 onnxruntime，不装 torch：

```bash
pip install -r requirements.txt
# 传 models/mobilenetv2_best.onnx + mobilenetv2_best.json
# config.json → model_settings.current_model_name 改为 "mobilenetv2_best.onnx"
python run.py
```

## 训练 / 评估 / 导出

```bash
# 训练（原始数据按 一级/二级/三级/四级 文件夹组织 → A/B/C/D，自动 80/20 划分）
python converter/train_moss.py --src "原始数据路径" --img-size 224

# 评估（混淆矩阵 + 各类 precision/recall/F1）
python converter/eval_moss.py

# 列误判样本（人工复核，可筛方向如 C→A）
python converter/list_errors.py --from C --to A

# 导出 ONNX（产线部署用）
python converter/export_onnx.py models/mobilenetv2_best.pth
```

## 目录结构

```
app/
├── core/           # BaseCamera 接口（含触发）
├── drivers/        # HikvisionCamera / MockCamera / hikvision_sdk/
├── controllers/    # SystemController + SystemWorker
├── services/       # ModelService / DatabaseService
├── ui/             # MainWindow / widgets
├── utils/          # ConfigManager / DiskMonitor / logger
└── main.py
config/config.json
converter/          # train_moss / eval_moss / list_errors / export_onnx
data/               # images/ + corrections/ + moss.db（gitignore，运行时生成）
models/             # *.pth / *.onnx / *.json（gitignore）
requirements.txt
run.py
```

## 配置（config.json 关键项）

- `camera_settings.trigger`：mode / source / activation / debouncer_time_us / grab_timeout_ms / software_interval_ms
- `camera_settings.exposure`：固定曝光（微秒）
- `model_settings.confidence_threshold`：拒识阈值
- `storage.retention_days`：滚动归档保留天数

## 依赖

见 `requirements.txt`：
- **产线**：PySide6 + Pillow + numpy + onnxruntime（不装 torch）
- **开发/训练/导出**：额外 torch / torchvision / timm / onnx

## 许可证

MIT
