# 苔藓识别系统（Moss Recognition System）

基于深度学习的工业级苔藓品级识别桌面应用。工业相机采集托盘图像，MobileNetV2 分类苔藓覆盖度品级（A/B/C/D），支持光电传感器硬件触发、ONNX 产线部署、滚动归档、置信度拒识与纠错闭环。

> 项目目录名 "苔藓识别-gemini cli" 为早期使用 Gemini CLI 协作时的遗留命名；当前系统不依赖任何 Gemini/云端模型，识别完全在本地完成。

## 生产约束（2026-08 确认）

- 节拍：1000–1500 托盘/天（约 3s/托盘）
- 无 PLC/传送带联动需求（保留驱动层扩展接口，见 `app/core/interfaces.py`）
- 部署机无 GPU：推理走 onnxruntime CPU（实测约 32ms/帧，含 2048² 转换）
- 单台 USB3 工业相机；512GB 系统盘；相机按 `camera_serial` 序列号选择
- 品级 = 整图人工目视覆盖度（A/B/C/D）
- 原图 PNG 无损保存；存储策略为容量水位自适应（见"存储策略"）

## 存储策略（决策 A：容量水位自适应）

原图 PNG 无损保存，名义保留 60 天；磁盘剩余低于 50GB 时从最旧开始清理（保留最近 7 天的数据不清理），低于 5GB 时停止采集。实际可保留天数受 512GB 硬盘限制（实测 2048² PNG 平均约 10.5MB/张，1000–1500 张/天 ≈ 10–16GB/天）。

配置键（`config/config.json` → `storage`）：`retention_days` / `disk_watermark_gb` / `cleanup_min_age_days` / `cleanup_interval_hours` / `critical_free_gb`。

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
- **滚动归档**：保留 `storage.retention_days`（默认 60 天）；启动只报告不删，按 `cleanup_interval_hours`（默认 1h）定时清理
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

### ONNX CPU 推理验证（性能基线）

产线无 GPU，推理走 onnxruntime CPU。开发机实测（onnxruntime 1.28 + CPU）：

- 模型：`mobilenetv2_best.onnx`（MobileNetV2，输入 224×224，8.5MB）
- 100 帧基准：平均 **32.3ms/帧**（含 2048×2048 QImage→numpy 转换 + 缩放 + 推理），远低于 500ms/帧目标
- torch vs onnx 数值校验：最大差异 < 1e-3（`export_onnx.py` 导出时自动校验）

部署后在产线机复测：

```bash
python -c "from app.services.model_service import ModelService; import time; from PySide6.QtGui import QImage; ms=ModelService('mobilenetv2_best.onnx'); q=QImage(2048,2048,QImage.Format.Format_RGB888); [ms.predict(q) for _ in range(5)]; t=time.time(); [ms.predict(q) for _ in range(100)]; print('avg_ms:', (time.time()-t)*10)"
```

若平均耗时超过 500ms/帧：检查 onnxruntime provider、CPU 是否降频、是否有杀毒软件实时扫描干扰。

## 测试

```bash
# TaiXian conda 环境（Python 3.11，含 PySide6/onnxruntime/torch/pytest）
python -m pytest
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

## 配置（config/config.json）

主配置文件。UI 修改的参数（分辨率 / 曝光 / 触发模式 / 防抖 / 软件间隔 / 置信阈值 / 质量阈值）会去抖（约 2s）原子写回本文件；缺失的键自动合并自内置默认值（`app/utils/config_manager.py`）。下表「默认」列为内置默认（缺失键时回退值），随仓库附带的 `config.json` 可能已设为实际产线值。

### model_settings — 模型

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `current_model_name` | str | `efficientnet_b0` | 当前加载的模型文件名（`.onnx` 产线 / `.pth` 开发）；模型切换或加载失败后用于恢复 |
| `models_directory` | str | `models/` | 模型文件目录 |
| `confidence_threshold` | float | `0.6` | 置信度拒识阈值，低于此值标"⚠️需复检"（DB 存原始数据不被污染） |

### data_paths — 数据路径

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `collected_data_directory` | str | `data/images/` | 原图与缩略图保存目录 |
| `db_filename` | str | `data/moss.db` | SQLite 数据库路径 |
| `corrections_directory` | str | `data/corrections/` | 纠错样本归档目录（ImageFolder 兼容，可直接重训） |

### storage — 存储与清理

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `image_format` | str | `png` | 原图格式；`png` 无损，其它值按 JPEG（有损）保存 |
| `image_quality` | int | `95` | JPEG 保存质量（仅 `image_format`≠`png` 时生效） |
| `thumbnail_max_size` | int | `300` | 缩略图最大边像素 |
| `retention_days` | int | `60` | 名义保留天数；超期记录由定时清理删除 |
| `disk_watermark_gb` | int | `50` | 磁盘剩余低于此值触发水位清理（从最旧开始删） |
| `cleanup_min_age_days` | int | `7` | 水位清理时保留最近 N 天的数据不删 |
| `cleanup_interval_hours` | int | `1` | 定时清理周期（小时） |
| `critical_free_gb` | int | `5` | 剩余低于此值**停止采集**并红字告警 |

### performance — 性能

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `processing_timeout_ms` | int | `3000` | 单帧处理（取图+推理+存储）超时阈值，超过则报错提示检查推理/存储性能 |

### quality_check — 入图质量检查

启用后，过曝/欠曝/模糊帧仍保存原图并入库（`quality_status` 标记），但不产出品级。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `enabled` | bool | `true` | 是否启用质量检查 |
| `overexposure_threshold` | float | `235.0` | 灰度均值 ≥ 此值判过曝 |
| `underexposure_threshold` | float | `25.0` | 灰度均值 ≤ 此值判欠曝 |
| `blur_threshold` | float | `50.0` | Laplacian 方差低于此值判模糊 |
| `consecutive_reject_alert` | int | `5` | 连续拒采达此次数触发告警 |

### camera_settings — 相机

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `driver_type` | str | `hikvision` | 相机驱动：`hikvision`（海康真相机）/ `mock`（开发模拟） |
| `camera_serial` | str | `""` | 指定相机序列号；空串取枚举到的第一台 |
| `resolution_width` | int | `2048` | 采集分辨率宽；UI 可调（256–4096，步进 64），点"应用"下发并写回 |
| `resolution_height` | int | `2048` | 采集分辨率高（同上） |
| `exposure` | int | `10000` | 固定曝光（微秒）；触发抓拍禁用 auto 以保证每张曝光一致 |

`camera_settings.trigger` — 触发（四档语义见上方「相机触发（四档）」）：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `mode` | str | `hardware` | 触发模式：`preview` / `hardware` / `software_single` / `software_continuous` |
| `source` | str | `Line0` | 硬件触发源（光电传感器接线） |
| `activation` | str | `RisingEdge` | 触发沿 |
| `debouncer_time_us` | int | `5000` | 触发防抖（微秒） |
| `grab_timeout_ms` | int | `2000` | 单帧抓取超时（毫秒） |
| `software_interval_ms` | int | `1000` | `software_continuous` 模式取图间隔（毫秒） |

### ui（可选）— 界面

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `engineer_mode_password` | str | 未配置 | 工程师模式密码；未配置/空串 → 切工程师模式直接放行；配置后需精确匹配才能进入（产线防误调参数）。不在默认 config 中，按需添加 `ui` 段 |

## 依赖

见 `requirements.txt`：
- **产线**：PySide6 + Pillow + numpy + onnxruntime（不装 torch）
- **开发/训练/导出**：额外 torch / torchvision / timm / onnx

## 许可证

MIT
