# Keras (.h5) 转 PyTorch (.pth) 模型转换器

本工具可将 Keras 保存的 `.h5` 格式模型，转换为 PyTorch 的状态字典（state dictionary）并存为 `.pth` 格式。它内置了针对 MobileNetV2、MobileNetV3-Large 和 MobileNetV3-Small 架构的特定转换逻辑。

## 使用说明

### 第一步：安装依赖

在运行转换脚本之前，你需要先安装所需的 Python 库。请打开终端，并从项目根目录运行以下命令：

```bash
pip install -r converter/requirements.txt
```

**注意：** 此命令会安装 TensorFlow 和 PyTorch。如果你的电脑配有支持 CUDA 的 GPU，为了获得最佳性能，请参考官方文档来安装对应 CUDA 版本的 TensorFlow 和 PyTorch。

### 第二步：运行转换脚本

依赖安装完毕后，你就可以运行转换脚本了。该脚本现在接受一个可选的 `--arch` 参数，用于指定模型架构，这能让转换过程更加精确。

-   `--arch <architecture>`: (可选) 指定要使用的 `timm` 库中的模型架构名称。
    -   默认值为 `mobilenetv2_100`。
    -   如果你的模型是 **MobileNetV3-Large**，请使用 `mobilenetv3_large_100`。
    -   如果你的模型是 **MobileNetV3-Small**，请使用 `mobilenetv3_small_100`。
    -   其他结构相似的 `timm` 模型名称也可能有效，但需要用户自行确认匹配的转换逻辑。
-   `<path_to_input.h5>`: (必需) 你的输入 `.h5` 模型文件的路径。
-   `<path_for_output.pth>`: (必需) 你希望输出的 `.pth` 模型文件的路径。

通用命令格式如下：
```bash
python converter/convert.py --arch <architecture> <你的输入模型.h5> <你的输出模型.pth>
```

### 如何判断是 MobileNetV3-Large 还是 MobileNetV3-Small？

由于 MobileNetV3 有 Large 和 Small 两种版本，它们的内部层结构和模块数量有所不同，因此在转换时必须指定正确的 `--arch` 参数。

**判断方法：**

1.  **从模型来源确认（最可靠）**：模型的设计者或训练者应该最清楚具体使用的版本。
2.  **通过模型摘要分析**：运行一次转换脚本（即便它会因为架构不匹配而失败，但它会打印模型摘要）。仔细查看脚本输出的 Keras 模型摘要 (`keras_model.summary()`)：
    *   **MobileNetV3-Large** 版本通常包含大约 **15** 个瓶颈层（或称作 Inverted Residual Block）。
    *   **MobileNetV3-Small** 版本通常包含大约 **11** 个瓶颈层。
    你可以通过数一下摘要中类似 `block_x_expand` 或 `block_x_depthwise` 这种重复出现的块来估算其数量。

### 命令示例

#### 示例1：转换 MobileNetV2 模型

如果你的模型是 **MobileNetV2**，你可以省略 `--arch` 标志（因为它就是默认值），或者显式地指定它。假设你的文件名为 `mobilenet_final86.h5`。

```bash
# 显式指定 v2 架构
python converter/convert.py --arch mobilenetv2_100 models/mobilenet_final86.h5 models/mobilenetv2_converted_86.pth
```

此命令会在 `models` 文件夹下创建一个名为 `mobilenetv2_converted_86.pth` 的新文件。

#### 示例2：转换 MobileNetV3-Large 模型

如果你确认你的模型是 **MobileNetV3-Large**，则**必须**指定架构。

```bash
# 假设你有一个名为 'my_mobilenet_v3_large.h5' 的 MobileNetV3-Large 模型
python converter/convert.py --arch mobilenetv3_large_100 models/my_mobilenet_v3_large.h5 models/mobilenetv3_large_converted.pth
```

#### 示例3：转换 MobileNetV3-Small 模型

如果你确认你的模型是 **MobileNetV3-Small**，则**必须**指定架构。

```bash
# 假设你有一个名为 'my_mobilenet_v3_small.h5' 的 MobileNetV3-Small 模型
python converter/convert.py --arch mobilenetv3_small_100 models/my_mobilenet_v3_small.h5 models/mobilenetv3_small_converted.pth
```

### 第三步：使用转换后的模型

脚本运行结束后，新的 `.pth` 文件就会出现在 `models` 目录下。此时，重新启动主应用程序，转换后的模型应该就会出现在模型的下拉选择菜单中，可以直接使用。
