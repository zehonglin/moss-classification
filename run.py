import sys
import os

# Add the project root to the python path
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(root_dir)
os.chdir(root_dir)  # 切到项目根，使 config/models/data/logs 相对路径不依赖启动目录

# Set model cache directory to local 'models' folder
# This must be done BEFORE importing torch/timm
models_dir = os.path.join(root_dir, "models")
os.makedirs(models_dir, exist_ok=True)
os.environ['TORCH_HOME'] = models_dir
os.environ['HF_HOME'] = models_dir
print(f"Set model cache directory to: {models_dir}")

from app.main import main

if __name__ == "__main__":
    main()
