import argparse
import tensorflow as tf
import torch
import timm
import numpy as np

# This script is designed to be illustrative and may require adjustments
# for specific model variations trained with different Keras backends/versions.

def convert_mobilenet_v2_weights(keras_model, pytorch_model):
    """Handles the weight conversion logic for a MobileNetV2 model."""
    print("Applying MobileNetV2 conversion logic...")
    keras_weights = keras_model.get_weights()
    keras_weight_idx = 0

    # MobileNetV2 has a relatively consistent structure for layers
    for name, param in pytorch_model.named_parameters():
        if 'num_batches_tracked' in name:
            continue

        try:
            # Conv/BN blocks (stem, inverted residuals, conv_head, bn2)
            if ('conv_stem' in name or 'blocks' in name or 
                'conv_head' in name or 'bn2' in name):
                
                if 'weight' in name and 'bn' not in name: # Conv weights (kernel)
                    keras_w = keras_weights[keras_weight_idx]
                    if keras_w.ndim == 4: # Standard Conv: Keras (kh, kw, in_c, out_c) -> PyTorch (out_c, in_c, kh, kw)
                        keras_w = np.transpose(keras_w, (3, 2, 0, 1))
                    elif keras_w.ndim == 3: # Depthwise Conv: Keras (kh, kw, c) -> PyTorch (c, 1, kh, kw)
                        keras_w = np.transpose(keras_w, (2, 0, 1))
                        keras_w = np.expand_dims(keras_w, axis=1) # Add group dimension for depthwise
                    param.data = torch.from_numpy(keras_w)
                    keras_weight_idx += 1
                elif 'bias' in name and 'bn' not in name: # Conv bias
                    param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                    keras_weight_idx += 1
                elif 'bn' in name: # BatchNorm weights
                    if 'weight' in name: param.data = torch.from_numpy(keras_weights[keras_weight_idx]); keras_weight_idx += 1 # gamma
                    elif 'bias' in name: param.data = torch.from_numpy(keras_weights[keras_weight_idx]); keras_weight_idx += 1 # beta
                    elif 'running_mean' in name: pytorch_model.state_dict()[name].copy_(torch.from_numpy(keras_weights[keras_weight_idx])); keras_weight_idx += 1
                    elif 'running_var' in name: pytorch_model.state_dict()[name].copy_(torch.from_numpy(keras_weights[keras_weight_idx])); keras_weight_idx += 1
            # Classifier
            elif 'classifier' in name:
                if 'weight' in name: # Linear weights: Keras (in_features, out_features) -> PyTorch (out_features, in_features)
                    keras_w = np.transpose(keras_weights[keras_weight_idx], (1, 0))
                    param.data = torch.from_numpy(keras_w)
                    keras_weight_idx += 1
                elif 'bias' in name: # Linear bias
                    param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                    keras_weight_idx += 1
            else:
                print(f"Warning: Layer '{name}' was not converted for V2.")
                continue

        except IndexError:
            print(f"\nError: Ran out of Keras weights while converting '{name}'. Mismatched V2 architecture.")
            return False
        except Exception as e:
            print(f"\nError converting V2 layer '{name}': {e}")
            return False

    if keras_weight_idx != len(keras_weights):
        print(f"\nWarning: V2 conversion finished, but weight counts don't match.")
        print(f"Total Keras weights: {len(keras_weights)}, Converted: {keras_weight_idx}")
    else:
        print("\nSuccessfully converted all Keras V2 weights.")
    return True


def convert_mobilenet_v3_large_weights(keras_model, pytorch_model):
    """Handles the weight conversion logic for a MobileNetV3-Large model."""
    print("Applying MobileNetV3-Large conversion logic...")
    print("NOTE: V3 conversion is complex. This is a best-effort attempt and may need manual adjustments.")
    
    keras_weights = keras_model.get_weights()
    keras_weight_idx = 0

    # MobileNetV3-Large has a specific sequence of blocks and SE modules
    for name, param in pytorch_model.named_parameters():
        if 'num_batches_tracked' in name:
            continue

        try:
            # Conv/BN layers (stem, inverted residuals, conv_head, final linear before classifier)
            # This logic covers standard conv, depthwise conv, and batch norm.
            # SE blocks are handled within the loop for `blocks`.
            if ('conv_stem' in name or 'blocks' in name or 
                'conv_head' in name or 'bn2' in name): # bn2 is the final BN before classifier for V3-Large
                
                # Squeeze-and-Excite (SE) block weights, if present in a block
                if 'se' in name:
                    if 'conv_reduce' in name and 'weight' in name: # 1x1 Conv for SE reduce
                        keras_w = keras_weights[keras_weight_idx] # (1, 1, in_c, out_c)
                        param.data = torch.from_numpy(keras_w).permute(3, 2, 0, 1)
                        keras_weight_idx += 1
                    elif 'conv_reduce' in name and 'bias' in name:
                        param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                        keras_weight_idx += 1
                    elif 'conv_expand' in name and 'weight' in name: # 1x1 Conv for SE expand
                        keras_w = keras_weights[keras_weight_idx] # (1, 1, in_c, out_c)
                        param.data = torch.from_numpy(keras_w).permute(3, 2, 0, 1)
                        keras_weight_idx += 1
                    elif 'conv_expand' in name and 'bias' in name:
                        param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                        keras_weight_idx += 1
                    continue # SE block has its own weights, skip generic conv/bn below for these params
                
                # Generic Conv/BN handling
                if 'weight' in name and 'bn' not in name: # Conv weights (kernel)
                    keras_w = keras_weights[keras_weight_idx]
                    if keras_w.ndim == 4: # Standard Conv
                        keras_w = np.transpose(keras_w, (3, 2, 0, 1))
                    elif keras_w.ndim == 3: # Depthwise Conv
                        keras_w = np.transpose(keras_w, (2, 0, 1))
                        keras_w = np.expand_dims(keras_w, axis=1)
                    param.data = torch.from_numpy(keras_w)
                    keras_weight_idx += 1
                elif 'bias' in name and 'bn' not in name: # Conv bias
                    param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                    keras_weight_idx += 1
                elif 'bn' in name: # BatchNorm weights
                    if 'weight' in name: param.data = torch.from_numpy(keras_weights[keras_weight_idx]); keras_weight_idx += 1 # gamma
                    elif 'bias' in name: param.data = torch.from_numpy(keras_weights[keras_weight_idx]); keras_weight_idx += 1 # beta
                    elif 'running_mean' in name: pytorch_model.state_dict()[name].copy_(torch.from_numpy(keras_weights[keras_weight_idx])); keras_weight_idx += 1
                    elif 'running_var' in name: pytorch_model.state_dict()[name].copy_(torch.from_numpy(keras_weights[keras_weight_idx])); keras_weight_idx += 1
            # Classifier (final linear layer)
            elif 'classifier' in name:
                if 'weight' in name: # Linear weights: Keras (in_features, out_features) -> PyTorch (out_features, in_features)
                    keras_w = np.transpose(keras_weights[keras_weight_idx], (1, 0))
                    param.data = torch.from_numpy(keras_w)
                    keras_weight_idx += 1
                elif 'bias' in name: # Linear bias
                    param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                    keras_weight_idx += 1
            else:
                print(f"Warning: Layer '{name}' was not converted for V3-Large.")
                continue

        except IndexError:
            print(f"\nError: Ran out of Keras weights while converting '{name}'. Mismatched V3-Large architecture.")
            return False
        except Exception as e:
            print(f"\nError converting V3-Large layer '{name}': {e}")
            return False

    if keras_weight_idx != len(keras_weights):
        print(f"\nWarning: V3-Large conversion finished, but weight counts don't match.")
        print(f"Total Keras weights: {len(keras_weights)}, Converted: {keras_weight_idx}")
    else:
        print("\nSuccessfully converted all Keras V3-Large weights.")
    return True

def convert_mobilenet_v3_small_weights(keras_model, pytorch_model):
    """Handles the weight conversion logic for a MobileNetV3-Small model."""
    print("Applying MobileNetV3-Small conversion logic...")
    print("NOTE: V3-Small conversion is highly specific and may need manual adjustments.")
    
    keras_weights = keras_model.get_weights()
    keras_weight_idx = 0

    # MobileNetV3-Small has a different sequence and count of blocks compared to Large
    # This mapping must be meticulously matched to both Keras and timm's implementation.
    for name, param in pytorch_model.named_parameters():
        if 'num_batches_tracked' in name:
            continue
        
        try:
            # Similar to V3-Large, handle Conv/BN/SE within blocks
            if ('conv_stem' in name or 'blocks' in name or 
                'conv_head' in name or 'bn2' in name): # bn2 is the final BN before classifier for V3-Small
                
                # SE block weights
                if 'se' in name:
                    if 'conv_reduce' in name and 'weight' in name: # 1x1 Conv for SE reduce
                        keras_w = keras_weights[keras_weight_idx]
                        param.data = torch.from_numpy(keras_w).permute(3, 2, 0, 1)
                        keras_weight_idx += 1
                    elif 'conv_reduce' in name and 'bias' in name:
                        param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                        keras_weight_idx += 1
                    elif 'conv_expand' in name and 'weight' in name: # 1x1 Conv for SE expand
                        keras_w = keras_weights[keras_weight_idx]
                        param.data = torch.from_numpy(keras_w).permute(3, 2, 0, 1)
                        keras_weight_idx += 1
                    elif 'conv_expand' in name and 'bias' in name:
                        param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                        keras_weight_idx += 1
                    continue # Skip generic conv/bn below for these params
                
                # Generic Conv/BN handling
                if 'weight' in name and 'bn' not in name: # Conv weights (kernel)
                    keras_w = keras_weights[keras_weight_idx]
                    if keras_w.ndim == 4: # Standard Conv
                        keras_w = np.transpose(keras_w, (3, 2, 0, 1))
                    elif keras_w.ndim == 3: # Depthwise Conv
                        keras_w = np.transpose(keras_w, (2, 0, 1))
                        keras_w = np.expand_dims(keras_w, axis=1)
                    param.data = torch.from_numpy(keras_w)
                    keras_weight_idx += 1
                elif 'bias' in name and 'bn' not in name: # Conv bias
                    param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                    keras_weight_idx += 1
                elif 'bn' in name: # BatchNorm weights
                    if 'weight' in name: param.data = torch.from_numpy(keras_weights[keras_weight_idx]); keras_weight_idx += 1 # gamma
                    elif 'bias' in name: param.data = torch.from_numpy(keras_weights[keras_weight_idx]); keras_weight_idx += 1 # beta
                    elif 'running_mean' in name: pytorch_model.state_dict()[name].copy_(torch.from_numpy(keras_weights[keras_weight_idx])); keras_weight_idx += 1
                    elif 'running_var' in name: pytorch_model.state_dict()[name].copy_(torch.from_numpy(keras_weights[keras_weight_idx])); keras_weight_idx += 1
            # Classifier (final linear layer)
            elif 'classifier' in name:
                if 'weight' in name: # Linear weights: Keras (in_features, out_features) -> PyTorch (out_features, in_features)
                    keras_w = np.transpose(keras_weights[keras_weight_idx], (1, 0))
                    param.data = torch.from_numpy(keras_w)
                    keras_weight_idx += 1
                elif 'bias' in name: # Linear bias
                    param.data = torch.from_numpy(keras_weights[keras_weight_idx])
                    keras_weight_idx += 1
            else:
                print(f"Warning: Layer '{name}' was not converted for V3-Small.")
                continue

        except IndexError:
            print(f"\nError: Ran out of Keras weights while converting '{name}'. Mismatched V3-Small architecture.")
            return False
        except Exception as e:
            print(f"\nError converting V3-Small layer '{name}': {e}")
            return False

    if keras_weight_idx != len(keras_weights):
        print(f"\nWarning: V3-Small conversion finished, but weight counts don't match.")
        print(f"Total Keras weights: {len(keras_weights)}, Converted: {keras_weight_idx}")
    else:
        print("\nSuccessfully converted all Keras V3-Small weights.")
    return True


def convert_h5_to_pth(h5_path, pth_path, arch_name):
    """
    Converts a Keras MobileNet .h5 model to a PyTorch-compatible .pth state dictionary.

    Args:
        h5_path (str): Path to the input Keras .h5 model file.
        pth_path (str): Path to save the output PyTorch .pth file.
        arch_name (str): The 'timm' architecture name (e.g., 'mobilenetv2_100').
    """
    print(f"--- Starting Conversion ---")
    print(f"Input H5: {h5_path}")
    print(f"Output PTH: {pth_path}")
    print(f"Target Architecture: {arch_name}")
    print("-" * 25)

    print(f"\n[1/4] Loading Keras model...")
    try:
        # It's better to load without compiling for inference-only models
        keras_model = tf.keras.models.load_model(h5_path, compile=False)
        print("Keras model loaded successfully.")
        keras_model.summary()
    except Exception as e:
        print(f"Error: Failed to load Keras model. Make sure TensorFlow is installed correctly.")
        print(f"Details: {e}")
        return

    # --- Infer number of classes ---
    try:
        num_classes = keras_model.output_shape[1]
        print(f"\n[2/4] Inferred number of classes from model output: {num_classes}")
    except Exception as e:
        print(f"Error: Could not determine number of classes from model. Exiting. Details: {e}")
        return

    # --- Create the corresponding PyTorch model ---
    print(f"\n[3/4] Creating PyTorch model architecture: '{arch_name}'...")
    try:
        pytorch_model = timm.create_model(arch_name, pretrained=False, num_classes=num_classes)
        pytorch_model.eval()
    except Exception as e:
        print(f"Error: Failed to create timm model '{arch_name}'. Is the name correct? Details: {e}")
        return
    
    # --- Convert weights based on architecture ---
    print(f"\n[4/4] Starting weight conversion...")
    success = False
    if 'mobilenetv2' in arch_name: # Handle all MobileNetV2 variants
        success = convert_mobilenet_v2_weights(keras_model, pytorch_model)
    elif 'mobilenetv3_large' in arch_name: # Check for large explicitly
        success = convert_mobilenet_v3_large_weights(keras_model, pytorch_model)
    elif 'mobilenetv3_small' in arch_name: # Check for small explicitly
        success = convert_mobilenet_v3_small_weights(keras_model, pytorch_model)
    else:
        print(f"Error: Unsupported architecture '{arch_name}'. Only 'mobilenetv2_XXX', 'mobilenetv3_large_XXX', and 'mobilenetv3_small_XXX' are explicitly supported.")
        return

    # --- Save the PyTorch state dictionary ---
    if success:
        try:
            torch.save(pytorch_model.state_dict(), pth_path)
            print(f"\n--- Conversion Complete ---")
            print(f"Successfully saved converted model to: {pth_path}")
        except Exception as e:
            print(f"\nError: Failed to save the PyTorch model. Details: {e}")
    else:
        print(f"\n--- Conversion Failed ---")
        print("Model was not saved due to errors during weight conversion.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Convert a Keras MobileNet .h5 model to a PyTorch .pth state_dict."
    )
    parser.add_argument(
        "--arch",
        type=str,
        default="mobilenetv2_100",
        help="The target 'timm' architecture name. E.g., 'mobilenetv2_100', 'mobilenetv3_large_100', 'mobilenetv3_small_100'."
    )
    parser.add_argument(
        "h5_path", 
        type=str, 
        help="Path to the input Keras .h5 model file."
    )
    parser.add_argument(
        "pth_path", 
        type=str, 
        help="Path to save the output PyTorch .pth state_dict file."
    )

    args = parser.parse_args()
    convert_h5_to_pth(args.h5_path, args.pth_path, args.arch)
