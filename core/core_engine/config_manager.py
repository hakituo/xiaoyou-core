# 配置管理器模块 - 已统一至 integrated_config.py
import threading
from typing import Dict, Any, Callable
from core.utils.logger import get_logger
from config.integrated_config import get_settings
from core.utils.config_accessor import get_config as _safe_get_config

logger = get_logger("CONFIG_MANAGER")

_LEGACY_KEY_MAP: Dict[str, Callable] = {}


def _build_legacy_key_map():
    """构建旧键到新 Settings 的映射（延迟构建，避免循环导入）"""
    if _LEGACY_KEY_MAP:
        return

    def _s(attr: str):
        def getter(settings):
            return getattr(settings, attr)
        return getter

    def _sub(parent: str, child: str):
        def getter(settings):
            return _safe_get_config(f"{parent}.{child}", default=None, settings=settings)
        return getter

    _LEGACY_KEY_MAP.update({
        "voice.tts.enabled": _sub("voice", "enabled"),
        "voice.stt.enabled": _sub("voice", "enabled"),
        "voice.tts.engine": _sub("voice", "default_engine"),
        "voice.stt.engine": _sub("voice", "default_engine"),
        "models.llm.path": _sub("model", "text_path"),
        "models.stable_diffusion.path": _sub("model", "image_gen_path"),
        "models.vision.path": _sub("model", "vision_path"),
        "SERVER_PORT": _sub("server", "port"),
        "WS_PORT": _sub("server", "ws_port"),
        "WS_HEARTBEAT_INTERVAL": _sub("server", "ws_heartbeat_interval"),
        "WS_TIMEOUT": _sub("server", "ws_timeout"),
        "MAX_CONNECTIONS": _sub("server", "max_connections"),
        "LOG_LEVEL": _sub("log", "level"),
        "LOG_FILE": _sub("log", "file"),
        "MAX_REQUESTS_PER_MINUTE": _sub("server", "max_requests_per_minute"),
        "MAX_CONTENT_LENGTH": _sub("server", "max_content_length"),
        "SHORT_TERM_CAPACITY": _sub("memory", "short_term_capacity"),
        "LONG_TERM_CAPACITY": _sub("memory", "long_term_capacity"),
        # 向后兼容
        "DEFAULT_HISTORY_LENGTH": _sub("memory", "short_term_capacity"),
        "MAX_HISTORY_LENGTH": _sub("memory", "long_term_capacity"),
        "MEMORY_PRUNING_THRESHOLD": _sub("memory", "memory_pruning_threshold"),
        "LONG_TERM_MEMORY_DB": _sub("memory", "long_term_memory_db"),
        "DEFAULT_MODEL": _sub("model", "name"),
        "MODEL_PATH": _sub("model", "model_dir"),
        "MODEL_LOAD_MODE": _sub("model", "load_mode"),
        "VOICE_ENABLED": _sub("voice", "enabled"),
        "DEFAULT_VOICE_ENGINE": _sub("voice", "default_engine"),
        "DEFAULT_VOICE": _sub("voice", "default_voice"),
        "DEFAULT_VOICE_SPEED": _sub("voice", "default_speed"),
        "CACHE_SIZE": _sub("cache", "size"),
        "CACHE_TTL": _sub("cache", "ttl"),
    })


class ConfigManager:
    """
    配置管理器 (适配器模式)
    负责加载、管理和提供应用程序配置
    现在作为 integrated_config.Settings 的包装器，提供向后兼容性
    """

    _instance = None
    # P0-23: 使用 threading.Lock + double-check 保护 __new__ 单例初始化，
    # 防止多线程并发导致重复创建实例（_initialized 状态不一致、配置错乱）
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                # double-check：拿到锁后再次确认，避免重复初始化
                if cls._instance is not None:
                    return cls._instance
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if hasattr(self, "_settings"):
            return
        self._settings = get_settings()

    def initialize(self):
        """初始化配置管理器"""
        if self._initialized:
            return

        logger.info("正在初始化配置管理器 (Unified)...")
        self._initialized = True
        logger.info("配置管理器初始化完成")

    def get(self, key_path: str, default: Any = None) -> Any:
        """获取配置值 (支持点号分隔路径)"""
        if not self._initialized:
            self.initialize()

        try:
            keys = key_path.split(".")
            current = self._settings
            for key in keys:
                if hasattr(current, key):
                    current = getattr(current, key)
                elif isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    mapped_val = self._map_legacy_key(key_path)
                    if mapped_val is not None:
                        return mapped_val
                    return default
            return current
        except Exception:
            return default

    def _map_legacy_key(self, key_path: str) -> Any:
        """映射旧的键路径到新的 Settings 结构"""
        _build_legacy_key_map()
        getter = _LEGACY_KEY_MAP.get(key_path)
        if getter is None:
            return None
        try:
            return getter(self._settings)
        except Exception:
            return None

    def set(self, key_path: str, value: Any):
        """设置配置值（仅修改内存中的 Settings 实例，不会持久化到文件）"""
        if not self._initialized:
            self.initialize()

        keys = key_path.split(".")

        try:
            obj = self._settings
            for key in keys[:-1]:
                obj = getattr(obj, key)
            setattr(obj, keys[-1], value)
            logger.info(f"已更新配置 (内存): {key_path}")
        except Exception as e:
            logger.error(f"设置配置失败 {key_path}: {str(e)}")

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取配置节"""
        val = self.get(section)
        if hasattr(val, "model_dump"):
            return val.model_dump()
        return val if isinstance(val, dict) else {}

    def reload(self):
        """重新加载配置"""
        self._initialized = False
        self.initialize()

    def get_all_config(self) -> Dict[str, Any]:
        """获取所有配置"""
        if not self._initialized:
            self.initialize()
        return self._settings.model_dump()

    def validate_config(self) -> bool:
        """验证配置"""
        try:
            self._settings.validate()
            return True
        except Exception as e:
            logger.error(f"Config validation failed: {e}")
            return False


_config_manager_instance = None
# P0-23: 使用 threading.Lock + double-check 保护 get_config_manager 单例，
# 防止多线程并发导致重复 initialize（_initialized 状态不一致）
_config_manager_lock = threading.Lock()


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager_instance
    if _config_manager_instance is None:
        with _config_manager_lock:
            # double-check：拿到锁后再次确认，避免重复初始化
            if _config_manager_instance is not None:
                return _config_manager_instance
            _config_manager_instance = ConfigManager()
            _config_manager_instance.initialize()
    return _config_manager_instance


def get_config(key_path: str, default: Any = None) -> Any:
    """便捷函数：获取配置值"""
    manager = get_config_manager()
    return manager.get(key_path, default)


def set_config(key_path: str, value: Any):
    """便捷函数：设置配置值"""
    manager = get_config_manager()
    manager.set(key_path, value)


__all__ = ["ConfigManager", "get_config_manager", "get_config", "set_config"]
