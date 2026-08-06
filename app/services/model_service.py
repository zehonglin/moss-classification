import json
import os
import logging
import threading
import numpy as np
from PIL import Image
from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)

# torch / timm / torchvision 仅 .pth 路径与导出需要；产线可只装 onnxruntime 不装 torch
try:
    import torch
    import timm
    import torchvision.transforms as _tv_transforms
    _TORCH_AVAILABLE = True
except ImportError:
    torch = None
    timm = None
    _tv_transforms = None
    _TORCH_AVAILABLE = False

# 训练时的标准化常量（onnx numpy 预处理需复现，不依赖 torch）
_NORM_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_NORM_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class ModelService:
    """
    AI 模型服务，支持两种推理后端：
    - .onnx：onnxruntime（产线推荐，不依赖 torch/timm，部署瘦身）
    - .pth/.pt 或 timm 在线模型：PyTorch + timm（开发/训练/转换用）

    线程安全：推理与模型切换通过 _model_lock 串行化。
    """

    CUDA_CACHE_CLEAR_INTERVAL = 50

    def __init__(self, model_name=None, models_dir='models/'):
        os.makedirs(models_dir, exist_ok=True)
        os.environ['TORCH_HOME'] = os.path.abspath(models_dir)
        logger.info(f"Model directory set to: {os.environ['TORCH_HOME']}")

        self._inference_count = 0
        self._model_lock = threading.RLock()

        # 一次只用一种后端
        self.session = None            # onnxruntime.InferenceSession
        self._onnx_input_name = None
        self._onnx_img_size = None
        self.model = None              # torch.nn.Module
        self.transform = None          # torch 预处理
        self.class_names = None

        self.device = self._detect_device()
        logger.info(f"Using device: {self.device} | torch available: {_TORCH_AVAILABLE}")

        if model_name:
            if not self.load_model(model_name):
                logger.warning(f"初始模型 '{model_name}' 加载失败，请在界面中选择可用模型。")

    # ---------------- 设备检测 ----------------
    @staticmethod
    def _detect_device():
        """优先 onnxruntime CUDA，回退 torch CUDA，再回退 CPU（尽量不依赖 torch）。"""
        try:
            import onnxruntime as ort
            if 'CUDAExecutionProvider' in ort.get_available_providers():
                return 'cuda'
        except ImportError:
            pass
        if _TORCH_AVAILABLE and torch.cuda.is_available():
            return 'cuda'
        return 'cpu'

    # ---------------- GPU 内存（torch 路径）----------------
    def _log_gpu_memory(self, context: str = ""):
        if self.device == "cuda" and _TORCH_AVAILABLE:
            allocated = torch.cuda.memory_allocated() / (1024 ** 2)
            reserved = torch.cuda.memory_reserved() / (1024 ** 2)
            logger.debug(f"GPU Memory [{context}]: Allocated={allocated:.1f}MB, Reserved={reserved:.1f}MB")

    def _cleanup_gpu_memory(self, force: bool = False):
        if self.device != "cuda" or not _TORCH_AVAILABLE:
            return
        self._inference_count += 1
        if force or self._inference_count >= self.CUDA_CACHE_CLEAR_INTERVAL:
            torch.cuda.empty_cache()
            self._inference_count = 0
            logger.debug("CUDA cache cleared")

    # ---------------- 可用模型枚举 ----------------
    def get_downloaded_models(self):
        models = []
        models_root = os.environ.get('TORCH_HOME', 'models')
        if os.path.exists(models_root):
            for item in os.listdir(models_root):
                if item.endswith(('.pth', '.pt', '.onnx')):
                    models.append(item)
        hub_dir = os.path.join(models_root, 'hub')
        if os.path.exists(hub_dir):
            for item in os.listdir(hub_dir):
                if item.startswith('models--timm--'):
                    parts = item.split('--')
                    if len(parts) >= 3:
                        models.append(parts[2].split('.')[0])
        return sorted(set(models))

    # ---------------- 架构解析（.pth 路径）----------------
    @staticmethod
    def _is_torchvision_state_dict(state_dict: dict) -> bool:
        return any(k.startswith('features.') for k in state_dict.keys())

    def _build_model_from_arch(self, arch: str, num_classes: int, state_dict: dict):
        arch_lower = arch.lower()
        if arch_lower == 'mobilenet_v2' or (arch_lower.startswith('mobilenet') and self._is_torchvision_state_dict(state_dict)):
            from torchvision import models as tv_models
            model = tv_models.mobilenet_v2(weights=None)
            model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, num_classes)
            return model, True
        model = timm.create_model(arch_lower, pretrained=False, num_classes=num_classes)
        return model, False

    # ---------------- 加载 ----------------
    def load_model(self, model_name):
        logger.info(f"Attempting to load model '{model_name}'...")
        if model_name.endswith('.onnx'):
            return self._load_onnx(model_name)
        return self._load_torch(model_name)

    def _load_onnx(self, model_name):
        try:
            import onnxruntime as ort
            models_root = os.environ.get('TORCH_HOME', 'models')
            onnx_path = os.path.join(models_root, model_name)
            if not os.path.exists(onnx_path):
                logger.error(f"ONNX model not found: {onnx_path}")
                return False
            providers = (['CUDAExecutionProvider', 'CPUExecutionProvider']
                         if self.device == 'cuda' else ['CPUExecutionProvider'])
            session = ort.InferenceSession(onnx_path, providers=providers)

            input_meta = session.get_inputs()[0]
            input_name = input_meta.name
            shape = input_meta.shape
            img_size = shape[-1] if isinstance(shape[-1], int) else 224

            labels = None
            json_path = os.path.splitext(onnx_path)[0] + '.json'
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                labels = meta.get('classes')
                if isinstance(meta.get('img_size'), int):
                    img_size = meta['img_size']

            with self._model_lock:
                self.session = session
                self._onnx_input_name = input_name
                self._onnx_img_size = img_size
                self.model = None
                self.transform = None
                self.class_names = labels
            logger.info(f"Loaded ONNX '{model_name}' (img_size={img_size}, providers={session.get_providers()})")
            return True
        except Exception:
            logger.exception(f"Failed to load ONNX model '{model_name}':")
            return False

    def _load_torch(self, model_name):
        if not _TORCH_AVAILABLE:
            logger.error(f"加载 '{model_name}' 需要 torch/timm，但当前环境未安装。产线请使用 .onnx 模型。")
            return False
        try:
            # 在线 timm 预训练
            if not model_name.endswith(('.pth', '.pt')):
                logger.info(f"Loading pretrained timm model: {model_name}")
                new_model = timm.create_model(model_name, pretrained=True, num_classes=1000)
                new_model = new_model.to(self.device).eval()
                data_config = timm.data.resolve_data_config({}, model=new_model)
                new_transform = timm.data.create_transform(**data_config, is_training=False)
                self._install_model(new_model, new_transform, None)
                logger.info(f"Successfully loaded pretrained timm model '{model_name}'.")
                return True

            # 本地 .pth
            models_root = os.environ.get('TORCH_HOME', 'models')
            weights_path = os.path.join(models_root, model_name)
            if not os.path.exists(weights_path):
                logger.error(f"Model file not found: {weights_path}")
                return False
            checkpoint = torch.load(weights_path, map_location=self.device, weights_only=False)
            if isinstance(checkpoint, dict):
                state_dict = checkpoint.get('model_state_dict') or checkpoint.get('state_dict') or checkpoint
            else:
                state_dict = checkpoint
            if not state_dict:
                raise ValueError("Checkpoint 中未找到有效的 state_dict。")

            num_classes = self._detect_num_classes(state_dict)
            arch = None
            if isinstance(checkpoint, dict):
                arch = checkpoint.get('architecture') or checkpoint.get('arch')
            if not arch:
                raise ValueError(
                    "无法确定模型架构：checkpoint 未声明 architecture 字段。"
                    "请用 converter/train_moss.py 重训（会自动存 architecture）。")
            logger.info(f"Using architecture '{arch}'.")

            new_model, is_torchvision = self._build_model_from_arch(arch, num_classes, state_dict)
            try:
                new_model.load_state_dict(state_dict, strict=True)
            except RuntimeError as e:
                raise RuntimeError(f"权重与架构 '{arch}' 不匹配（strict 加载失败），已拒绝以防止静默误判：{e}")
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
        with self._model_lock:
            old_model = self.model
            self.model = new_model
            self.transform = new_transform
            self.class_names = new_labels
            self.session = None  # 切到 torch 后端时清掉 onnx
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
        if is_torchvision:
            img_size = 224
            if isinstance(checkpoint, dict):
                img_size = checkpoint.get('img_size', 224)
            return _tv_transforms.Compose([
                _tv_transforms.Resize((img_size, img_size)),
                _tv_transforms.ToTensor(),
                _tv_transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ])
        data_config = timm.data.resolve_data_config({}, model=new_model)
        return timm.data.create_transform(**data_config, is_training=False)

    @staticmethod
    def _load_class_labels(checkpoint, weights_path):
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

    # ---------------- 推理 ----------------
    def predict(self, q_image: QImage):
        with self._model_lock:
            if self.session is not None:
                return self._predict_onnx(q_image)
            if self.model is not None:
                return self._predict_torch(q_image)
            return "模型未加载", 0.0

    def _predict_onnx(self, q_image: QImage):
        if q_image.isNull():
            return "No image", 0.0
        arr = self._qimage_to_nchw(q_image, self._onnx_img_size)
        logits = self.session.run(None, {self._onnx_input_name: arr})[0]
        z = logits[0]
        e = np.exp(z - z.max())
        probs = e / e.sum()
        idx = int(probs.argmax())
        conf = float(probs[idx])
        name = self.class_names[idx] if (self.class_names and idx < len(self.class_names)) else str(idx)
        return name, conf

    def _predict_torch(self, q_image: QImage):
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
            if 'output' in locals(): del output
            if 'probs' in locals(): del probs
            if 'confidence' in locals(): del confidence
            if 'top1' in locals(): del top1
            self._cleanup_gpu_memory()

    @staticmethod
    def _qimage_to_hwc_uint8(q_image: QImage):
        """QImage(RGB888) → HWC uint8 numpy。按 bytesPerLine 切片去除行尾对齐 padding，
        避免 bytesPerLine > w*3 时 reshape 错位。"""
        q = q_image.convertToFormat(QImage.Format.Format_RGB888)
        w, h = q.width(), q.height()
        bpl = q.bytesPerLine()
        buf = np.array(q.bits(), dtype=np.uint8, copy=True)
        return buf[:h * bpl].reshape(h, bpl)[:, :w * 3].reshape(h, w, 3)

    def _qimage_to_tensor(self, q_image: QImage):
        """QImage → torch tensor（.pth 路径）。"""
        arr = self._qimage_to_hwc_uint8(q_image)
        pil_image = Image.fromarray(arr, 'RGB')
        return self.transform(pil_image).unsqueeze(0).to(self.device)

    def _qimage_to_nchw(self, q_image: QImage, img_size: int):
        """QImage → NCHW float32 numpy（onnx 输入），不依赖 torch。"""
        arr = self._qimage_to_hwc_uint8(q_image)
        pil = Image.fromarray(arr, 'RGB').resize((img_size, img_size))
        arr = np.array(pil, dtype=np.float32) / 255.0
        arr = (arr - _NORM_MEAN) / _NORM_STD
        arr = arr.transpose(2, 0, 1)  # HWC → CHW
        return arr[np.newaxis, ...]

    # ---------------- 诊断 ----------------
    def get_gpu_memory_info(self) -> dict:
        if self.device != "cuda" or not _TORCH_AVAILABLE:
            return {"available": False}
        return {
            "available": True,
            "allocated_mb": torch.cuda.memory_allocated() / (1024 ** 2),
            "reserved_mb": torch.cuda.memory_reserved() / (1024 ** 2),
            "max_allocated_mb": torch.cuda.max_memory_allocated() / (1024 ** 2),
        }
