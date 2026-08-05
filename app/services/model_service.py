import timm
import torch
import requests
import json
from PIL import Image
import torchvision.transforms as transforms
from PySide6.QtGui import QImage
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
import io
import os
import logging
import numpy as np

logger = logging.getLogger(__name__)


class ModelService:
    """
    AI model service with optimized GPU memory management.
    
    Memory Management Strategy:
    - Explicit tensor deletion after inference
    - Periodic CUDA cache clearing (every N inferences)
    - Proper cleanup when switching models
    """
    
    # Clear CUDA cache every N inferences to prevent memory fragmentation
    CUDA_CACHE_CLEAR_INTERVAL = 50
    
    def __init__(self, model_name='efficientnet_b0', models_dir='models/'):
        # Check for CUDA availability
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")

        # Configure model download directory
        os.makedirs(models_dir, exist_ok=True)
        os.environ['TORCH_HOME'] = os.path.abspath(models_dir)
        logger.info(f"Model directory set to: {os.environ['TORCH_HOME']}")

        # Inference counter for periodic CUDA cache clearing
        self._inference_count = 0
        
        # Cache for default ImageNet labels
        self._imagenet_class_names = self._get_imagenet_labels()
        self.class_names = self._imagenet_class_names

        # Load the model
        model_name = model_name.lower() # Ensure lowercase for timm
        logger.info(f"Loading initial model '{model_name}'...")
        self.model = timm.create_model(model_name, pretrained=True, num_classes=1000)
        self.model = self.model.to(self.device)
        self.model.eval()
        logger.info("Initial model loaded successfully.")

        # Get model-specific transforms
        data_config = timm.data.resolve_data_config({}, model=self.model)
        self.transform = timm.data.create_transform(**data_config, is_training=False)
        
        # Log initial GPU memory usage if CUDA is available
        if self.device == "cuda":
            self._log_gpu_memory("After initial model load")

    def _log_gpu_memory(self, context: str = ""):
        """Log current GPU memory usage for debugging."""
        if self.device == "cuda":
            allocated = torch.cuda.memory_allocated() / (1024 ** 2)
            reserved = torch.cuda.memory_reserved() / (1024 ** 2)
            logger.debug(f"GPU Memory [{context}]: Allocated={allocated:.1f}MB, Reserved={reserved:.1f}MB")

    def _cleanup_gpu_memory(self, force: bool = False):
        """
        Clean up GPU memory.
        
        Args:
            force: If True, clear cache regardless of inference count
        """
        if self.device != "cuda":
            return
            
        self._inference_count += 1
        
        if force or self._inference_count >= self.CUDA_CACHE_CLEAR_INTERVAL:
            torch.cuda.empty_cache()
            self._inference_count = 0
            logger.debug("CUDA cache cleared")
            
    def _reset_to_imagenet_labels(self):
        """Resets the class names to the default ImageNet labels."""
        if self.class_names is not self._imagenet_class_names:
            logger.info("Setting class names to default ImageNet labels.")
            self.class_names = self._imagenet_class_names

    def get_downloaded_models(self):
        """Scans the models directory for downloaded timm models."""
        models = []
        # 1. Scan for custom models in the root models directory
        models_root = os.environ.get('TORCH_HOME', 'models')
        if os.path.exists(models_root):
            for item in os.listdir(models_root):
                if item.endswith(('.pth', '.pt')):
                    models.append(item)

        # 2. Scan for downloaded timm models in hub
        hub_dir = os.path.join(models_root, 'hub')
        if os.path.exists(hub_dir):
            for item in os.listdir(hub_dir):
                # timm models are stored as 'models--timm--model_name'
                if item.startswith('models--timm--'):
                    parts = item.split('--')
                    if len(parts) >= 3:
                        model_name_with_suffix = parts[2]
                        model_name = model_name_with_suffix.split('.')[0]
                        models.append(model_name)
        
        # Ensure the current default is in the list if not found (e.g. if running for first time)
        if 'efficientnet_b0' not in models and not models:
             models.append('efficientnet_b0')
             
        return sorted(list(set(models)))

    def load_model(self, model_name):
        """
        Loads a new model with proper memory cleanup and updates class labels.
        Supports both TIMM models and Torchvision models (from test/mobilenet.py).
        """
        logger.info(f"Attempting to switch to model '{model_name}'...")
        
        try:
            old_model = self.model
            new_model = None
            is_torchvision_model = False
            
            if model_name.endswith(('.pth', '.pt')):
                # --- Load Custom Model weights ---
                logger.info(f"Loading custom weights from {model_name}...")
                models_root = os.environ.get('TORCH_HOME', 'models')
                weights_path = os.path.join(models_root, model_name)
                checkpoint = torch.load(weights_path, map_location=self.device)

                # --- Unpack Checkpoint ---
                state_dict = None
                if isinstance(checkpoint, dict):
                    if 'model_state_dict' in checkpoint:
                        state_dict = checkpoint['model_state_dict']
                    elif 'state_dict' in checkpoint:
                        state_dict = checkpoint['state_dict']
                    else:
                        state_dict = checkpoint
                else:
                    state_dict = checkpoint
                
                if not state_dict:
                    raise ValueError("Could not find a valid state_dict in the checkpoint file.")

                # --- Detect Architecture Type (Torchvision vs TIMM) ---
                # Torchvision MobileNetV2 usually has 'features.0.0.weight'
                # TIMM MobileNetV2 usually has 'blocks.0.0.conv_dw.weight' or 'conv_stem.weight'
                first_key = next(iter(state_dict.keys()))
                logger.info(f"First key in state_dict: {first_key}")

                num_classes_in_weights = 1000
                
                # Check for output layer size
                classifier_weight_key = None
                for key in state_dict.keys():
                    if key.endswith(('classifier.weight', 'fc.weight', 'head.weight', 'classifier.1.weight')):
                        classifier_weight_key = key
                        break
                if classifier_weight_key:
                    num_classes_in_weights = state_dict[classifier_weight_key].shape[0]
                logger.info(f"Detected {num_classes_in_weights} classes from model weights.")

                if 'features.0.0.weight' in state_dict or 'classifier.1.weight' in state_dict:
                    # Likely a Torchvision model (e.g. from test/mobilenet.py)
                    try:
                        from torchvision import models as tv_models
                        logger.info("Detected Torchvision-style keys. Attempting to load using torchvision.models...")
                        
                        # Currently hardcoded for MobileNetV2 as that is what the test script uses.
                        # Can be expanded to detect ResNet etc based on keys if needed.
                        if 'mobilenet' in model_name.lower() or 'classifier.1.weight' in state_dict:
                            new_model = tv_models.mobilenet_v2(pretrained=False)
                            new_model.classifier[1] = torch.nn.Linear(new_model.classifier[1].in_features, num_classes_in_weights)
                            
                        # Try to load strict first, if fails, relax
                        try:
                            new_model.load_state_dict(state_dict, strict=True)
                        except Exception as e:
                            logger.warning(f"Strict loading failed for torchvision model: {e}. Retrying with strict=False")
                            new_model.load_state_dict(state_dict, strict=False)
                            
                        is_torchvision_model = True
                        logger.info("Successfully loaded as Torchvision MobileNetV2.")
                    except Exception as e:
                        logger.error(f"Failed to load as torchvision model: {e}. Falling back to TIMM attempt.")

                if new_model is None:
                    # Fallback to TIMM logic
                    architecture = 'efficientnet_b0'
                    known_archs = ['resnet18', 'resnet34', 'resnet50', 'mobilenetv2_100', 'mobilenet_v2', 'mobilenetv3_large_100', 'efficientnet_b0', 'efficientnet_b1', 'efficientnet_b2', 'vit_base_patch16_224']
                    for arch in known_archs:
                        if model_name.lower().startswith(arch):
                            architecture = arch.replace('mobilenetv2_100', 'mobilenet_v2') 
                            break
                    logger.info(f"Inferred TIMM architecture '{architecture}' from filename '{model_name}'")

                    new_model = timm.create_model(architecture, pretrained=False, num_classes=num_classes_in_weights)
                    new_model.load_state_dict(state_dict, strict=False)

                # --- Load Class Labels (Priority: Checkpoint > JSON > Default) ---
                labels_loaded = False
                if isinstance(checkpoint, dict) and 'classes' in checkpoint and checkpoint['classes']:
                    self.class_names = checkpoint['classes']
                    labels_loaded = True
                    logger.info(f"Successfully loaded {len(self.class_names)} embedded class labels from checkpoint.")
                
                if not labels_loaded:
                    json_path = os.path.splitext(weights_path)[0] + '.json'
                    if os.path.exists(json_path):
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                self.class_names = json.load(f)
                            labels_loaded = True
                            logger.info(f"Successfully loaded {len(self.class_names)} custom class labels from {json_path}")
                        except Exception as e:
                            logger.error(f"Failed to load or parse custom labels from {json_path}: {e}")
                    
                if not labels_loaded:
                    logger.warning(f"No embedded labels or external .json file found. Falling back to ImageNet labels.")
                    self._reset_to_imagenet_labels()

            else:
                # --- Load Standard Timm Model ---
                logger.info(f"Loading pretrained timm model: {model_name}")
                new_model = timm.create_model(model_name, pretrained=True, num_classes=1000)
                self._reset_to_imagenet_labels()

            new_model = new_model.to(self.device)
            new_model.eval()
            
            # --- Configure Transforms ---
            # If it's a torchvision model (especially from our test script), it expects simple Resize -> Tensor -> Normalize
            if is_torchvision_model:
                logger.info("Using standard Torchvision transforms (Resize without Crop) for consistency.")
                from torchvision import transforms 
                # Use the size from checkpoint if available, else default to 224
                img_size = 224
                if isinstance(checkpoint, dict) and 'img_size' in checkpoint:
                    img_size = checkpoint['img_size']
                
                self.transform = transforms.Compose([
                    transforms.Resize((img_size, img_size)), # Force resize to square, matching test script
                    transforms.ToTensor(),
                    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
                ])
            else:
                # Use TIMM's optimized transforms for TIMM models
                data_config = timm.data.resolve_data_config({}, model=new_model)
                self.transform = timm.data.create_transform(**data_config, is_training=False)
            
            if old_model is not None:
                del old_model
                self._cleanup_gpu_memory(force=True)
            
            self.model = new_model
            self._log_gpu_memory("After model switch")
            logger.info(f"Successfully switched to model '{model_name}'.")
            return True
            
        except Exception as e:
            logger.exception(f"Failed to switch model to '{model_name}':")
            return False

    def _get_imagenet_labels(self):
        """Fetches and loads the ImageNet class labels."""
        try:
            url = "https://s3.amazonaws.com/deep-learning-models/image-models/imagenet_class_index.json"
            response = requests.get(url)
            response.raise_for_status()
            class_idx = json.loads(response.text)
            return [class_idx[str(k)][1] for k in range(len(class_idx))]
        except Exception as e:
            logger.error(f"Could not load ImageNet labels: {e}. Predictions will be class indices.")
            return None

    def predict(self, q_image: QImage):
        """
        Performs inference on a QImage with proper GPU memory management.
        Returns the top predicted class name and confidence score.
        """
        if q_image.isNull():
            return "No image", 0.0

        # Efficiently convert QImage to PIL Image
        # Ensure consistent format for direct buffer access
        q_image = q_image.convertToFormat(QImage.Format.Format_RGB888)
        width = q_image.width()
        height = q_image.height()
        
        # Get a memoryview of the image data
        ptr = q_image.bits()

        # Create a NumPy array from the QImage data. This copies the data.
        arr = np.array(ptr).reshape(height, width, 3)
        pil_image = Image.fromarray(arr, 'RGB')

        # Transform the image and add a batch dimension
        img_tensor = self.transform(pil_image).unsqueeze(0).to(self.device)

        # Perform inference with explicit memory management
        try:
            with torch.no_grad():
                output = self.model(img_tensor)
                probabilities = torch.nn.functional.softmax(output[0], dim=0)
            
            # Get top prediction
            confidence, top1_idx = torch.topk(probabilities, 1)
            
            # Extract values BEFORE deleting tensors
            confidence_value = confidence.item()
            top1_idx_value = top1_idx.item()
            
            # Map to class name if available
            class_name = str(top1_idx_value)
            if self.class_names and top1_idx_value < len(self.class_names):
                class_name = self.class_names[top1_idx_value]
            
            return class_name, confidence_value
            
        finally:
            # Explicitly delete tensors to free GPU memory immediately
            # This is critical for preventing memory buildup in high-frequency inference
            del img_tensor
            if 'output' in locals():
                del output
            if 'probabilities' in locals():
                del probabilities
            if 'confidence' in locals():
                del confidence
            if 'top1_idx' in locals():
                del top1_idx
            
            # Periodic cache cleanup
            self._cleanup_gpu_memory()

    def get_gpu_memory_info(self) -> dict:
        """
        Get current GPU memory usage info.
        Useful for monitoring in UI or diagnostics.
        """
        if self.device != "cuda":
            return {"available": False}
        
        return {
            "available": True,
            "allocated_mb": torch.cuda.memory_allocated() / (1024 ** 2),
            "reserved_mb": torch.cuda.memory_reserved() / (1024 ** 2),
            "max_allocated_mb": torch.cuda.max_memory_allocated() / (1024 ** 2),
        }

