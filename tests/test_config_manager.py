"""ConfigManager 行为测试：损坏配置显式报错 + 原子写。"""

import json

import pytest

import app.utils.config_manager as cm_mod
from app.utils.config_manager import ConfigError, ConfigManager


def test_corrupt_json_raises_config_error(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{ not valid json !!!", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigManager(str(cfg))


def test_missing_config_creates_defaults(tmp_path):
    cfg = tmp_path / "config.json"
    cm = ConfigManager(str(cfg))
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["camera_settings"]["exposure"] == 10000
    assert "model_settings" in data
    assert cm.get("camera_settings.trigger.mode") == "preview"


def test_partial_config_merges_with_defaults(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"camera_settings": {"driver_type": "hikvision"}}), encoding="utf-8"
    )
    cm = ConfigManager(str(cfg))
    assert cm.get("camera_settings.driver_type") == "hikvision"
    assert cm.get("model_settings.confidence_threshold") == 0.6  # 来自默认值


def test_rapid_writes_keep_file_parsable_and_latest(tmp_path):
    cfg = tmp_path / "config.json"
    cm = ConfigManager(str(cfg))
    for i in range(25):
        cm.set("camera_settings.exposure", i)
        cm.flush()
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["camera_settings"]["exposure"] == i
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "config.json"]
    assert leftovers == []


def test_failed_atomic_write_leaves_original_intact(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cm = ConfigManager(str(cfg))
    cm.set("camera_settings.exposure", 12345)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(cm_mod.os, "replace", boom)
    cm.flush()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    # 原子写失败时原文件必须保持旧内容，而不是半截新内容
    assert data["camera_settings"]["exposure"] == 10000
