"""ONNX provider 选择（过滤不可用的 provider）。"""

from app.services.model_service import ModelService


def test_pick_providers_cpu_only():
    assert ModelService._pick_providers("cpu", ["CPUExecutionProvider"]) == [
        "CPUExecutionProvider"
    ]


def test_pick_providers_cuda_unavailable_falls_back_to_cpu():
    assert ModelService._pick_providers("cuda", ["CPUExecutionProvider"]) == [
        "CPUExecutionProvider"
    ]


def test_pick_providers_keeps_available_cuda():
    assert ModelService._pick_providers(
        "cuda", ["CUDAExecutionProvider", "CPUExecutionProvider"]
    ) == ["CUDAExecutionProvider", "CPUExecutionProvider"]
