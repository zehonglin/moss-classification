import timm
import torch
import json
from PIL import Image
import torchvision.transforms as transforms
from PySide6.QtGui import QImage
import threading
import os
import logging
import numpy as np

logger = logging.getLogger(__name__)


class ModelService:
    """
    AI 模型服务：负责模型加载、推理与切换。

    设计要点：
    - 本地优先：仅加载本地权重，启动时不强制联网下载预训练模型。
    - 强校验：依据 checkpoint 中的 architecture 字段构建模型并 strict 加载，
      权重与结构不匹配时直接报错，绝不静默丢弃权重。
    - 线程安全：推理（worker 线程）与模型切换（主线程）通过 _model_lock 串行化。
    - GPU 内存：显式释放张量、周期性清理 CUDA 缓存。
    """

    # 每 N 次推理清理一次 CUDA 缓存，缓解内存碎片
    CUDA_CACHE_CLEAR_INTERVAL = 50

    def __init__(self, model_name=None, models_dir='models/'):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")

        os.makedirs(models_dir, exist_ok=True)
        os.environ['TORCH_HOME'] = os.path.abspath(models_dir)
        logger.info(f"Model directory set to: {os.environ['TORCH_HOME']}")

        self._inference_count = 0

        # 推理（worker 线程）与切换（主线程）共享同一模型对象，需串行化
        self._model_lock = threading.RLock()

        # 当前模型状态，初始为空，等待显式加载（不再无条件下载 EfficientNet）
        self.model = None
        self.class_names = None
        self.transform = None

        if model_name:
            loaded = self.load_model(model_name)
            if not loaded:
                logger.warning(
                    f"初始模型 '{model_name}' 加载失败，请在界面中选择一个可用的本地模型。"
                )

    # ------------------------------------------------------------------ #
    # GPU 内存管理
    # ------------------------------------------------------------------ #

    def _log_gpu_memory(self, context: str = ""):
        if self.device == "cuda":
            allocated = torch.cuda.memory_allocated() / (1024 ** 2)
            reserved = torch.cuda.memory_reserved() / (1024 ** 2)
            logger.debug(f"GPU Memory [{context}]: Allocated={allocated:.1f}MB, Reserved={reserved:.1f}MB")

    def _cleanup_gpu_memory(self, force: bool = False):
        if self.device != "cuda":
            return
        self._inference_count += 1
        if force or self._inference_count >= self.CUDA_CACHE_CLEAR_INTERVAL:
            torch.cuda.empty_cache()
            self._inference_count = 0
            logger.debug("CUDA cache cleared")

    # ------------------------------------------------------------------ #
    # 可用模型枚举
    # ------------------------------------------------------------------ #

    def get_downloaded_models(self):
        """扫描模型目录，返回本地可用的模型（本地权重 + 已缓存的 timm 模型，不触发联网）。"""
        models = []
        models_root = os.environ.get('TORCH_HOME', 'models')

        # 1. 本地自定义权重
        if os.path.exists(models_root):
            for item in os.listdir(models_root):
                if item.endswith(('.pth', '.pt')):
                    models.append(item)

        # 2. 已缓存到 hub 的 timm 预训练模型（仅列出已下载的）
        hub_dir = os.path.join(models_root, 'hub')
        if os.path.exists(hub_dir):
            for item in os.listdir(hub_dir):
                if item.startswith('models--timm--'):
                    parts = item.split('--')
                    if len(parts) >= 3:
                        models.append(parts[2].split('.')[0])

        return sorted(set(models))

    # ------------------------------------------------------------------ #
    # 架构解析
    # ------------------------------------------------------------------ #

    @staticmethod
    def _guess_arch_from_filename(filename: str) -> str | None:
        """checkpoint 未声明 architecture 时，按文件名前缀兜底推断。"""
        name = filename.lower()
        known = [
            'mobilenetv3_large_100', 'mobilenetv3_small_100',
            'mobilenetv2_100', 'mobilenet_v2', 'mobilenetv3', 'mobilenet',
            'efficientnet_b0', 'efficientnet_b1', 'efficientnet_b2',
            'resnet18', 'resnet34', 'resnet50',
            'vit_base_patch16_224',
        ]
        for arch in known:
            if name.startswith(arch):
                return arch
        return None

    @staticmethod
    def _is_torchvision_state_dict(state_dict: dict) -> bool:
        """torchvision 风格判断（如 MobileNetV2 的 features.0.0.weight）。"""
        return any(k.startswith('features.') for k in state_dict.keys())

    def _build_model_from_arch(self, arch: str, num_classes: int, state_dict: dict):
        """依据架构名构建空模型，自动区分 torchvision 与 timm。返回 (model, is_torchvision)。"""
        arch_lower = arch.lower()

        # torchvision：显式声明，或 state_dict 为 torchvision 风格
        if arch_lower == 'mobilenet_v2' or (
            arch_lower.startswith('mobilenet') and self._is_torchvision_state_dict(state_dict)
        ):
            from torchvision import models as tv_models
            model = tv_models.mobilenet_v2(weights=None)
            model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, num_classes)
            return model, True

        # timm
        model = timm.create_model(arch_lower, pretrained=False, num_classes=num_classes)
        return model, False

    # ------------------------------------------------------------------ #
    # 模型加载
    # ------------------------------------------------------------------ #

    def load_model(self, model_name):
        """
        加载模型。优先级：本地 .pth 权重 > 在线 timm 预训练。

        约定的 checkpoint 字段（推荐训练时保存）：
            architecture      : 架构名（'mobilenet_v2' / 'mobilenetv2_100' / 'efficientnet_b0' ...）
            classes           : 类别名列表
            img_size          : 输入尺寸
            model_state_dict  : 权重（或顶层 state_dict）

        线程安全：构建在锁外完成，仅在锁内原子替换 self.model。
        """
        logger.info(f"Attempting to load model '{model_name}'...")

        try:
            # ---- 在线 timm 预训练（仅当用户显式选择非 .pth 名时才联网）----
            if not model_name.endswith(('.pth', '.pt')):
                logger.info(f"Loading pretrained timm model: {model_name}")
                new_model = timm.create_model(model_name, pretrained=True, num_classes=1000)
                new_model = new_model.to(self.device).eval()
                data_config = timm.data.resolve_data_config({}, model=new_model)
                new_transform = timm.data.create_transform(**data_config, is_training=False)
                self._install_model(new_model, new_transform, None)
                logger.info(f"Successfully loaded pretrained timm model '{model_name}'.")
                return True

            # ---- 本地 .pth 权重 ----
            models_root = os.environ.get('TORCH_HOME', 'models')
            weights_path = os.path.join(models_root, model_name)
            if not os.path.exists(weights_path):
                logger.error(f"Model file not found: {weights_path}")
                return False

            checkpoint = torch.load(weights_path, map_location=self.device)

            # 解析 state_dict
            if isinstance(checkpoint, dict):
                state_dict = checkpoint.get('model_state_dict') or checkpoint.get('state_dict') or checkpoint
            else:
                state_dict = checkpoint
            if not state_dict:
                raise ValueError("Checkpoint 中未找到有效的 state_dict。")

            # 类别数
            num_classes = self._detect_num_classes(state_dict)
            logger.info(f"Detected {num_classes} classes from model weights.")

            # 架构：checkpoint.architecture 优先，文件名兜底
            arch = None
            if isinstance(checkpoint, dict):
                arch = checkpoint.get('architecture') or checkpoint.get('arch')
            if not arch:
                arch = self._guess_arch_from_filename(model_name)
                if not arch:
                    raise ValueError(
                        "无法确定模型架构：checkpoint 未声明 architecture，且文件名无法识别。"
                        "请在训练时保存 architecture 字段，或使用规范命名。"
                    )
                logger.warning(
                    f"Checkpoint 未声明 architecture，按文件名推断为 '{arch}'；"
                    f"建议训练时保存 architecture 字段以消除歧义。"
                )
            logger.info(f"Using architecture '{arch}'.")

            # 构建模型并 strict 加载（不匹配即报错，杜绝静默误判）
            new_model, is_torchvision = self._build_model_from_arch(arch, num_classes, state_dict)
            try:
                new_model.load_state_dict(state_dict, strict=True)
            except RuntimeError as e:
                raise RuntimeError(
                    f"权重与架构 '{arch}' 不匹配（strict 加载失败），已拒绝加载以防止静默误判：{e}"
                )
            new_model = new_model.to(self.device).eval()

            new_transform = self._build_transform(new_model, is_torchvision, checkpoint)
            new_labels = self._load_class_labels(checkpoint, weights_path)

            self._install_model(new_model, new_transform, new_labels)
            self._log_gpu_memory("After model load")
            logger.info(f"Successfully loaded model '{model_name}'.")
            return True

        except Exception:
            logger.exception(f"Failed to load model '{model_name}':")
            return False

    def _install_model(self, new_model, new_transform, new_labels):
        """在锁内原子替换当前模型，避免推理与切换并发访问。"""
        with self._model_lock:
            old_model = self.model
            self.model = new_model
            self.transform = new_transform
            self.class_names = new_labels
        if old_model is not None:
            del old_model
            self._cleanup_gpu_memory(force=True)

    @staticmethod
    def _detect_num_classes(state_dict: dict) -> int:
        for key in state_dict.keys():
            if key.endswith(('classifier.weight', 'fc.weight', 'head.weight', 'classifier.1.weight')):
                return state_dict[key].shape[0]
        return 1000

    def _build_transform(self, new_model, is_torchvision: bool, checkpoint):
        """依据架构/来源构建预处理流水线。"""
        if is_torchvision:
            img_size = 224
            if isinstance(checkpoint, dict):
                img_size = checkpoint.get('img_size', 224)
            return transforms.Compose([
                transforms.Resize((img_size, img_size)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ])
        data_config = timm.data.resolve_data_config({}, model=new_model)
        return timm.data.create_transform(**data_config, is_training=False)

    @staticmethod
    def _load_class_labels(checkpoint, weights_path):
        """类别标签：checkpoint 内嵌 > 同名 .json > None。"""
        if isinstance(checkpoint, dict) and checkpoint.get('classes'):
            labels = checkpoint['classes']
            logger.info(f"Loaded {len(labels)} embedded class labels from checkpoint.")
            return labels
        json_path = os.path.splitext(weights_path)[0] + '.json'
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    labels = json.load(f)
                logger.info(f"Loaded {len(labels)} class labels from {json_path}.")
                return labels
            except Exception as e:
                logger.error(f"Failed to parse labels from {json_path}: {e}")
        logger.warning("No class labels found; predictions will be class indices.")
        return None

    # ------------------------------------------------------------------ #
    # 推理
    # ------------------------------------------------------------------ #

    def predict(self, q_image: QImage):
        """
        对一帧 QImage 推理，返回 (类名/索引, 置信度)。
        线程安全：与 load_model 通过 _model_lock 串行化。
        """
        with self._model_lock:
            if self.model is None or self.transform is None:
                return "模型未加载", 0.0
            if q_image.isNull():
                return "No image", 0.0

            img_tensor = self._qimage_to_tensor(q_image)
            try:
                with torch.no_grad():
                    output = self.model(img_tensor)
                    probs = torch.nn.functional.softmax(output[0], dim=0)
                confidence, top1 = torch.topk(probs, 1)
                conf_val = confidence.item()
                idx = top1.item()
                name = self.class_names[idx] if (self.class_names and idx < len(self.class_names)) else str(idx)
                return name, conf_val
            finally:
                del img_tensor
                if 'output' in locals():
                    del output
                if 'probs' in locals():
                    del probs
                if 'confidence' in locals():
                    del confidence
                if 'top1' in locals():
                    del top1
                self._cleanup_gpu_memory()

    def _qimage_to_tensor(self, q_image: QImage):
        """QImage -> PIL -> tensor。"""
        q_image = q_image.convertToFormat(QImage.Format.Format_RGB888)
        w, h = q_image.width(), q_image.height()
        ptr = q_image.bits()
        arr = np.array(ptr).reshape(h, w, 3)
        pil_image = Image.fromarray(arr, 'RGB')
        return self.transform(pil_image).unsqueeze(0).to(self.device)

    # ------------------------------------------------------------------ #
    # 诊断
    # ------------------------------------------------------------------ #

    def get_gpu_memory_info(self) -> dict:
        if self.device != "cuda":
            return {"available": False}
        return {
            "available": True,
            "allocated_mb": torch.cuda.memory_allocated() / (1024 ** 2),
            "reserved_mb": torch.cuda.memory_reserved() / (1024 ** 2),
            "max_allocated_mb": torch.cuda.max_memory_allocated() / (1024 ** 2),
        }
