# 苔藓识别系统工业级加固实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 1000–1500 托盘/天、无 GPU、512GB 硬盘、单台 USB3 相机的生产约束下，把系统从"可用桌面原型"加固为可 7×24 连续运行的工业软件，并修复已确认的正确性缺陷。

**Architecture:** 保持现有 UI/Controller/Service/Driver 分层。修改集中在 ConfigManager（原子写、禁止静默降级）、SystemController/SystemWorker（状态机与异常恢复）、ModelService（加载失败防护）、HikvisionCamera（序列号选择与断线检测）、存储策略（容量自适应清理）。不改变整体架构。

**Tech Stack:** Python 3.11/3.12、PySide6、onnxruntime(CPU)、SQLite(WAL)、pytest、Pillow。

## Global Constraints

- 产线节拍：1000–1500 托盘/天（约 3s/托盘）。
- 无 PLC/传送带联动需求；保留驱动层扩展接口（不实现）。
- 部署无 GPU，CPU 推理；单台 USB3 工业相机；512GB 系统盘。
- 品级 = 整图人工目视覆盖度（A/B/C/D），整图分类方案成立。
- 原图 PNG 无损、名义保留 60 天；存储策略采用 Phase 0 决策选项 A（容量水位自适应）。
- 纠错不得中断产线采集。
- 无 MES / 托盘 ID / 批次对接需求。

## 实测数据（依据）

- 2048×2048 PNG 平均 **10.46MB**（6 张苔藓样本，LANCZOS 缩放后编码）；300px 缩略图平均 **207KB**。
- 1000/天 → 原图 10.5GB/天 → 60 天 ≈ **628GB**；1500/天 → 15.7GB/天 → 60 天 ≈ **941GB**；另加缩略图约 12–19GB。
- 结论：**60 天无损 PNG 在 512GB 硬盘上不可行**，必须先在 Phase 0 决策。

## Phase 0 — 存储策略决策（阻塞项）

### 决策选项（已定：A）

- **A（推荐，已选）容量水位自适应**：名义保留 60 天；当磁盘剩余空间低于阈值（默认 50GB）时，从最旧记录开始清理；优先保最新数据，清理量记录日志并在 UI 提示。实际可保留天数会低于 60。
- **B 缩短保留期**：30 天 @1000/天 ≈ 320GB（可行），@1500/天 ≈ 470GB（仍紧张）。
- **C 降低原图分辨率**：1600² ≈ 6.4MB、1280² ≈ 4.1MB；60 天 @1000/天 ≈ 384GB / 246GB。
- **D 无损 WebP + 调整保留期**：约省 30–40%，需加依赖，UI 需支持 WebP。
- **E 外接存储 / NAS 归档**：本地 512GB 只做热缓冲，旧数据异步归档。

**已决策：选项 A。** 其余 Phase 1 任务不受影响，可并行开始。

---

## Phase 1 — P0：正确性与安全修复（优先，可无相机开发）

### Task 1.1 ConfigManager：原子写 + 损坏配置显式报错

**Files:**
- Modify: `app/utils/config_manager.py`（`_save_now`、`load_config`）
- Test: `tests/test_config_manager.py`（新增）

**Changes:**
- `_save_now` 改为：写入同目录临时文件（如 `config.json.tmp`）→ `os.replace` 原子替换；避免断电/崩溃留下半截 JSON。
- `load_config` 遇到 JSON 解析失败：不再静默回退默认配置，抛 `ConfigError`，由 `app/main.py` 捕获后弹窗并退出（或进入受限模式 + UI 红字提示），杜绝"损坏配置 → 静默切 mock 相机 + 在线模型"的危险路径。

**Acceptance:**
- `pytest tests/test_config_manager.py` 通过：损坏 JSON 不静默；连续多次写入后文件始终可解析。

### Task 1.2 禁止相机驱动静默降级

**Files:**
- Modify: `app/controllers/system_controller.py`（`_initialize_hardware`）

**Changes:**
- 删除 `except ImportError → MockCamera` 的回退分支。
- 驱动类型严格来自 `config.camera_settings.driver_type`；`hikvision` 加载失败 → 状态置 IDLE、`error_occurred` 发 UI 红字、日志 ERROR；只有显式配置 `mock` 才允许 Mock。
- `ConfigManager` 默认 `driver_type` 由 `mock` 改为 `hikvision`（防止配置缺失/损坏时误入模拟模式）。
- 保留 `MockCamera` 作为显式开发/测试模式：UI 状态栏常驻"模拟相机"标识（醒目黄色），避免操作员误用；后续可在 Mock 中加入故障注入（模拟无图超时、断线、模糊帧），用于测重连/无图告警/质量拒采。

**Acceptance:**
- 模拟海康 SDK 导入失败时应用明确报错，绝不静默进入 Mock 采集；未配置 `driver_type=mock` 时不存在任何进入 Mock 的路径；Mock 模式下 UI 有明显标识。

### Task 1.3 模型未加载时禁止采集

**Files:**
- Modify: `app/services/model_service.py`（新增 `is_ready()`）
- Modify: `app/controllers/system_controller.py`（`start_system`、`SystemWorker.start_loop`）

**Changes:**
- `ModelService.is_ready()`：`session is not None or model is not None`。
- `start_system` 前置检查：未就绪则拒绝启动并提示"模型未加载，请先选择模型"。
- `SystemWorker.start_loop` 中若 `predict` 返回 `("模型未加载", 0.0)`，停止循环并告警，**不落库、不存图**。

**Acceptance:**
- 无模型时无法启动采集；运行中模型被卸载后 worker 停止且无假记录写入。

### Task 1.4 纠错不停线

**Files:**
- Modify: `app/ui/main_window.py`（`_show_correction_dialog`）

**Changes:**
- 删除弹窗前调用 `controller.stop_system()`。
- 纠错直接提交 `correct_prediction` + 刷新历史条目；结果栏提示"已提交纠错"，产线采集状态保持不变。

**Acceptance:**
- 运行中执行纠错，worker 不停止、状态仍为 RUNNING。

### Task 1.5 capture_single 幽灵记录

**Files:**
- Modify: `app/controllers/system_controller.py`（`capture_single`）
- Modify: `app/ui/main_window.py`（`_update_result_display` / `_add_history_record`）

**Changes:**
- `id=None` 的调试结果不再加入历史列表；结果栏单独显示"调试捕获（未入库）"，并禁用纠错按钮。

**Acceptance:**
- 软件触发拍照不出现在历史列表；对其无法发起纠错。

### Task 1.6 shutdown 竞态

**Files:**
- Modify: `app/controllers/system_controller.py`（`shutdown` / `stop_system`）

**Changes:**
- worker 超过 5s 未停止时不再强行 `disconnect_camera`；改为：再等待一轮 → 记录 ERROR → 由进程退出兜底（SDK 句柄随进程释放）；或在 worker 线程内执行 disconnect。

**Acceptance:**
- 模拟 get_frame 阻塞时关闭程序，不出现 SDK 崩溃/野指针。

### Task 1.7 状态机一致性

**Files:**
- Modify: `app/controllers/system_controller.py`（`_handle_worker_error`、`_handle_error`）
- Modify: `app/ui/main_window.py`（`_handle_error`）

**Changes:**
- worker 错误恢复时：先 `_apply_trigger_config("preview")` 再启动 preview_timer（否则硬件触发模式下预览无图）。
- UI `_handle_error` 不把状态重置为 IDLE（相机仍连接）；区分"相机未连接"与"可恢复错误"；按钮状态以 controller 状态为准。

**Acceptance:**
- 模拟 worker 错误后：预览恢复出图；UI 不出现"相机已连接但按钮显示连接相机"的矛盾状态。

### Task 1.8 测试框架搭建

**Files:**
- Create: `pytest.ini`、`tests/` 目录

**Changes:**
- 引入 pytest；为 1.1–1.7 的关键逻辑（配置读写、状态机、清理、QImage→RGB 转换、纠错流）补单测；QImage 转换测试用 Qt 无窗口模式（`QT_QPA_PLATFORM=offscreen`）。

**Acceptance:**
- `pytest` 全绿；CI（可选）可无相机、无 GPU 运行。

---

## Phase 2 — P1：工业可靠性

### Task 2.1 存储模块参数化 + 容量水位清理（决策 A）

**Files:**
- Modify: `config/config.json`（`storage.*`）
- Modify: `app/controllers/system_controller.py`（`cleanup_old_records`）
- Modify: `app/services/database_service.py`

**Changes:**
- config 新增（写入 `config/config.json` 的 `storage` 段）：
  - `"retention_days": 60`（名义保留期）
  - `"disk_watermark_gb": 50`（磁盘剩余低于此值触发水位清理）
  - `"cleanup_min_age_days": 7`（水位清理的最短保留年龄，防止误删新样本）
  - `"cleanup_interval_hours": 1`（水位检查周期；60 天名义清理仍按 24h）
  - `"critical_free_gb": 5`（低于此值立即停止采集，替换现有硬编码 10/1GB 阈值）
- 清理算法（重构 `SystemController.cleanup_old_records`）：
  1. 定期任务每 `cleanup_interval_hours` 检查：磁盘剩余 < `disk_watermark_gb` 且存在年龄 > `cleanup_min_age_days` 的记录 → 从最旧开始删除，直到剩余空间 ≥ 水位或无可删记录。
  2. 超过 `retention_days` 的记录无条件删除（沿用现有 24h 任务）。
  3. 删除顺序：先删文件（原图 + 缩略图）再删 DB 行，DB 删除放在一个事务里；文件不存在则跳过，不中断；删除前统计待删文件体积用于日志。
  4. 启动时仍只报告不删除（沿用现有安全策略）。
  5. 清理完成后：日志记录条数/文件数/释放空间；发生删除时通过 `disk_space_warning` 信号给 UI 一条提示（不刷屏）。
  6. 采集前磁盘检查改用 `critical_free_gb`：低于则停止循环 + 红字告警（替换现有硬编码）。
- `app/services/database_service.py` 增加 `delete_records_before_in_batches(cutoff, limit)`（分页删除，避免一次性大事务）。

**Acceptance:**
- 单测：模拟水位触发，只删满足 `cleanup_min_age_days` 的最旧记录；文件删除失败不中断、不留孤儿 DB 行；`critical_free_gb` 触发时采集停止。
- 集成：老 config（无新键）读取时有默认值兜底，不崩溃。

### Task 2.2 相机序列号选择 + 机型信息

**Files:**
- Modify: `app/drivers/hikvision_driver.py`（`connect`）
- Modify: `config/config.json`

**Changes:**
- config 新增 `camera_serial`（默认空）。枚举设备时读取 SerialNumber 匹配；为空取第一台。连接成功后把型号/序列号回传 UI 显示，防止接错相机。

**Acceptance:**
- 两台设备模拟时，指定序列号只连目标设备；为空时行为与现状一致。

### Task 2.3 物理掉线检测与自动重连

**Files:**
- Modify: `app/drivers/hikvision_driver.py`
- Modify: `app/controllers/system_controller.py`

**Changes:**
- `get_frame` 连续失败达阈值或错误码指示掉线 → `b_is_connected=False`。
- controller 定时（10s）尝试重连（限次，如 3 次），成功恢复触发配置并通知 UI；失败持续告警。

**Acceptance:**
- 拔线/断线后 UI 状态变红；插回后自动恢复采集（或至少提示手动重连）。

### Task 2.4 CPU 推理路径验证与性能基线

**Files:**
- Modify: `converter/export_onnx.py`
- Modify: `app/services/model_service.py`

**Changes:**
- 在产线机生成 ONNX（CPU），固定 `CPUExecutionProvider`；跑 100 帧基准（目标 <500ms/帧），把机型/耗时记录到 README 部署章节。

**Acceptance:**
- 产线机上 CPU 推理端到端 <500ms；README 有实测数据。

### Task 2.5 节拍 / 吞吐 / 丢帧监控

**Files:**
- Modify: `app/controllers/system_controller.py`（`SystemWorker`）

**Changes:**
- 统计每小时托盘数、平均处理耗时、单帧超时次数；状态栏显示；连续丢帧/处理超时告警。

**Acceptance:**
- 运行界面能看到实时吞吐与异常计数。

### Task 2.6 图像质量检查（亮度 / 模糊）

**Files:**
- Create: `app/services/quality_service.py`
- Modify: `app/controllers/system_controller.py`
- Modify: `app/services/database_service.py`
- Modify: `app/ui/widgets.py` / `app/ui/main_window.py`

**Changes:**
- 新增 `app/services/quality_service.py`：灰度均值/方差（过曝/欠曝）+ Laplacian 方差（模糊）阈值判断；config 可开关并设阈值。
- **拒采帧仍然入库（含原图），但标记为"无效/拒采"而非品级**：
  - DB `records` 表增加 `quality_status TEXT DEFAULT 'ok'`（`rejected_blur` / `rejected_overexposed` / `rejected_underexposed`）与 `rejected_reason TEXT`，走现有 `PRAGMA table_info` 迁移模式。
  - 拒采记录：`prediction=NULL`、`confidence=NULL`、`quality_status` 置对应值；**保存原图 + 缩略图**，路径与正常帧同在 `data/images/`（沿用同一套保留期/水位清理，不单独建目录）。
  - 拒采图不进入 `data/corrections/` 训练闭环，避免脏样本污染重训数据。
- UI：历史列表红色显示"质量不合格：模糊/过曝/欠曝"；当日拒采计数显示在状态栏；拒采率异常（如连续 N 张）时提示检查补光/镜头。

**Acceptance:**
- 单测：quality_service 对模糊/过曝样本判拒、正常样本放行。
- 集成：拒采帧写入 DB（`quality_status` 标记、无品级）、**保存原图 + 缩略图**、UI 显示拒采与计数；正常帧不受影响；拒采记录不计入"需复检"的置信度拒识逻辑；拒采原图随水位/保留期清理一起老化。

### Task 2.7 模型切换竞态修复

**Files:**
- Modify: `app/services/model_service.py`
- Modify: `app/controllers/system_controller.py`（`reload_model`）

**Changes:**
- 切换带递增版本号；旧加载完成但版本过期则丢弃结果；切换期间 UI 禁用模型下拉，完成后按"最后一次请求"恢复。

**Acceptance:**
- 快速连续切换两个模型后，最终加载与 UI 选择一致。

---

## Phase 3 — P2：工程化与体验

### Task 3.1 eval / list_errors 架构参数化

**Files:**
- Modify: `converter/eval_moss.py`
- Modify: `converter/list_errors.py`

**Changes:**
- 从 checkpoint 读 `architecture`，按 `train_moss.py` 相同逻辑构建模型（torchvision/timm 分支一致）。

**Acceptance:**
- 用 timm 架构训练的 checkpoint 可正常评估，不再崩溃。

### Task 3.2 历史检索 / 筛选 / 导出（可选）

- 按时间范围、品级、拒识状态筛选；导出 CSV/Excel 报表。

### Task 3.3 文档与命名清理

- README 更新：生产约束（节拍、无 GPU、512GB）、存储策略（按 Phase 0 结果）、部署与验证步骤。
- 添加 LICENSE（MIT）。
- 清理 `converter/requirements.txt` 中的 tensorflow 残留；统一 Python 版本说明。
- 在 README 说明项目目录名 "gemini cli" 的历史遗留（或建议重命名仓库）。

### Task 3.4 打包与自启动（可选）

- PyInstaller 单 exe；NSSM 注册 Windows 服务 / 开机自启；文档化海康 SDK DLL 与 Python 位数匹配。

### Task 3.5 PLC 扩展接口文档化（不实现）

- 在 `app/core/interfaces.py` 增加注释/示例接口（如 `InterlockController`），说明未来到位确认/忙信号/剔除的接入点，不实现任何硬件逻辑。

---

## 依赖关系

- Phase 1 全部任务独立于 Phase 0，可立即开始。
- Task 2.1 依赖 Phase 0 决策（已定：A）。
- Task 2.4 需在产线机执行。
- Task 3.4 依赖 Task 2.4 通过。

## 建议执行顺序

1. Phase 1（Task 1.8 测试框架先行或与 1.1–1.7 并行）。
2. Phase 0 存储决策（已完成：选项 A）。
3. Phase 2 → Phase 3。
