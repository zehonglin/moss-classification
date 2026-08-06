import json
import os
import logging
import threading
import atexit

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """配置读取/解析失败。调用方应显式处理（如弹窗后退出），不得静默回退默认配置。"""


class ConfigManager:
    """
    Configuration manager with debounced file writes.
    
    Performance Optimization:
    - set() marks config as dirty but doesn't write immediately
    - Debounce timer delays writes to batch multiple changes
    - flush() available for immediate save when needed
    - Auto-save on program exit via atexit
    
    This reduces disk I/O from potentially hundreds of writes
    to just a few writes during user interaction.
    """
    
    # Debounce delay in seconds - wait this long after last change before saving
    SAVE_DEBOUNCE_SECONDS = 2.0
    
    def __init__(self, config_filename="config/config.json"):
        self.config_filename = config_filename
        self.config_data = {}
        self.default_config = {
            "camera_settings": {
                "driver_type": "hikvision",
                "camera_serial": "",
                "resolution_width": 2048,
                "resolution_height": 2048,
                "exposure": 10000,
                "trigger": {
                    "mode": "preview",
                    "source": "Line0",
                    "activation": "RisingEdge",
                    "debouncer_time_us": 5000,
                    "grab_timeout_ms": 2000,
                    "software_interval_ms": 1000
                }
            },
            "model_settings": {
                "current_model_name": "efficientnet_b0",
                "models_directory": "models/",
                "confidence_threshold": 0.6
            },
            "data_paths": {
                "collected_data_directory": "data/images/",
                "db_filename": "data/moss.db",
                "corrections_directory": "data/corrections/"
            },
            "storage": {
                "image_format": "png",
                "image_quality": 95,
                "thumbnail_max_size": 300,
                "retention_days": 60,
                "disk_watermark_gb": 50,
                "cleanup_min_age_days": 7,
                "cleanup_interval_hours": 1,
                "critical_free_gb": 5
            },
            "performance": {
                "processing_timeout_ms": 3000
            },
            "quality_check": {
                "enabled": True,
                "blur_threshold": 50.0,
                "overexposure_threshold": 235.0,
                "underexposure_threshold": 25.0,
                "consecutive_reject_alert": 5
            }
        }
        
        # Debounce mechanism
        self._dirty = False
        self._save_timer: threading.Timer | None = None
        self._lock = threading.Lock()
        
        # Register cleanup on exit
        atexit.register(self._cleanup)
        
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_filename):
            try:
                with open(self.config_filename, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
                # Merge with defaults to ensure all keys are present
                self.config_data = self._merge_configs(self.default_config, self.config_data)
                logger.info(f"Successfully loaded and merged config from {self.config_filename}")
            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON from {self.config_filename}.")
                raise ConfigError(
                    f"配置文件损坏，无法解析: {self.config_filename}。"
                    "请检查文件内容或恢复备份后再启动。"
                )
            except Exception as e:
                logger.exception(f"An unexpected error occurred loading config: {e}. Loading default config.")
                self.config_data = self.default_config
        else:
            logger.warning(f"{self.config_filename} not found. Creating with default config.")
            self.config_data = self.default_config
            self._save_now()  # Save defaults if file doesn't exist

    def _save_now(self):
        """Actually write config to disk."""
        tmp_path = self.config_filename + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.config_filename), exist_ok=True)
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=4, ensure_ascii=False)
            # 原子替换：避免断电/崩溃留下半截 JSON
            os.replace(tmp_path, self.config_filename)
            self._dirty = False
            logger.debug(f"Config saved to {self.config_filename}")
        except Exception as e:
            logger.exception(f"Error saving config to {self.config_filename}:")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _schedule_save(self):
        """Schedule a debounced save operation."""
        with self._lock:
            # Cancel any pending save
            if self._save_timer is not None:
                self._save_timer.cancel()
            
            # Schedule new save after debounce delay
            self._save_timer = threading.Timer(
                self.SAVE_DEBOUNCE_SECONDS,
                self._debounced_save
            )
            self._save_timer.daemon = True  # Don't block program exit
            self._save_timer.start()

    def _debounced_save(self):
        """Called by timer to actually save."""
        with self._lock:
            if self._dirty:
                self._save_now()
                self._save_timer = None

    def save_config(self):
        """
        Mark config as dirty and schedule a debounced save.
        For backward compatibility, this triggers a delayed save.
        Use flush() for immediate save.
        """
        self._dirty = True
        self._schedule_save()

    def flush(self):
        """
        Immediately save config to disk if there are pending changes.
        Call this before critical operations or program exit.
        """
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            
            if self._dirty:
                self._save_now()

    def _cleanup(self):
        """Called on program exit to ensure config is saved."""
        self.flush()

    def get(self, key_path, default=None):
        keys = key_path.split('.')
        value = self.config_data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path, value):
        """Set a config value. 改 config_data 持 _lock（与 _save_now 读互斥，防并发写出半截 JSON）；
        save_config 在锁外调（_schedule_save 自己持锁，避免重入死锁）。"""
        keys = key_path.split('.')
        changed = False
        with self._lock:
            current = self.config_data
            for i, key in enumerate(keys):
                if i == len(keys) - 1:
                    if current.get(key) != value:
                        current[key] = value
                        changed = True
                else:
                    if not isinstance(current, dict):
                        logger.error(f"Cannot set {key_path}: intermediate key '{key}' is not a dictionary.")
                        return
                    if key not in current:
                        current[key] = {}
                    current = current[key]
        if changed:
            self.save_config()

    def set_many(self, updates: dict):
        """
        Set multiple config values at once.
        More efficient than multiple set() calls.
        
        Args:
            updates: Dict of {key_path: value} pairs
        """
        changed = False
        with self._lock:
            for key_path, value in updates.items():
                keys = key_path.split('.')
                current = self.config_data
                for i, key in enumerate(keys):
                    if i == len(keys) - 1:
                        if current.get(key) != value:
                            current[key] = value
                            changed = True
                    else:
                        if key not in current:
                            current[key] = {}
                        current = current[key]
        if changed:
            self.save_config()

    def _merge_configs(self, default, custom):
        for key, value in default.items():
            if key not in custom:
                custom[key] = value
            elif isinstance(value, dict) and isinstance(custom[key], dict):
                custom[key] = self._merge_configs(value, custom[key])
        return custom

