# 配置管理器模块 - 已统一至 integrated_config.py
import os
import yaml
from typing import Dict, Optional, Any
from pathlib import Path
from core.utils.logger import get_logger
from config.integrated_config import get_settings, AppSettings

logger = get_logger("CONFIG_MANAGER")


class ConfigManager:
    """
    配置管理器 (适配器模式)
    负责加载、管理和提供应用程序配置
    现在作为 integrated_config.Settings 的包装器，提供向后兼容性
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._initialized = False
    
    def initialize(self):
        """
        初始化配置管理器
        """
        if self._initialized:
            return
        
        logger.info("正在初始化配置管理器 (Unified)...")
        
        # 自动检测模型
        self._auto_detect_models()
        
        self._initialized = True
        logger.info("配置管理器初始化完成")

    def _auto_detect_models(self):
        """
        自动检测模型路径并更新 Settings
        """
        # 1. 检测 LLM 模型
        if not self._settings.model.text_path:
            llm_path = os.environ.get('XIAOYOU_TEXT_MODEL_PATH', '').strip()
            if not llm_path:
                potential_models = [
                    r"d:\AI\xiaoyou-core\models\llm\L3-8B-Stheno-v3.2-Q5_K_M.gguf",
                    r"d:\AI\xiaoyou-core\models\llm\Qwen2___5-7B-Instruct-Q4_K_M.gguf",
                    r"d:\AI\xiaoyou-core\models\qwen\Qwen2___5-7B-Instruct-f16.gguf",
                    r"d:\AI\xiaoyou-core\models\qwen\Qwen2___5-7B-Instruct"
                ]
                for p in potential_models:
                    if os.path.exists(p):
                        llm_path = p
                        logger.info(f"自动检测到 LLM 模型: {llm_path}")
                        break
            
            if llm_path:
                self._settings.model.text_path = llm_path

        # 2. 检测 Stable Diffusion 模型
        if not self._settings.model.image_gen_path:
            sd_path = os.environ.get('XIAOYOU_SD_MODEL_PATH', '').strip()
            if not sd_path:
                potential_paths = [
                    r"D:\AI\xiaoyou-core\models\sdxl\sdxl_base_1.0.safetensors"
                ]
                for p in potential_paths:
                    if os.path.exists(p):
                        sd_path = p
                        logger.info(f"自动检测到 SD 模型: {sd_path}")
                        break
            
            if sd_path:
                self._settings.model.image_gen_path = sd_path

        # 3. 检测 Vision 模型
        if not self._settings.model.vision_path:
            vision_path = ""
            base_dir = Path(__file__).resolve().parent.parent.parent
            models_dir = base_dir / "models"
            
            candidates = [
                models_dir / "vision" / "Qwen2-VL-2B",
                models_dir / "Qwen2-VL-7B-instruct" / "qwen" / "Qwen2-VL-7B-Instruct"
            ]
            
            for p in candidates:
                if p.exists():
                    vision_path = str(p)
                    logger.info(f"自动检测到 Vision 模型: {vision_path}")
                    break
            
            if vision_path:
                self._settings.model.vision_path = vision_path
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值 (支持点号分隔路径)
        """
        if not self._initialized:
            self.initialize()
        
        # 尝试从 Settings 获取
        try:
            keys = key_path.split(".")
            current = self._settings
            for key in keys:
                if hasattr(current, key):
                    current = getattr(current, key)
                elif isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    # 特殊映射处理 (向后兼容)
                    mapped_val = self._map_legacy_key(key_path)
                    if mapped_val is not None:
                        return mapped_val
                    return default
            return current
        except Exception:
            return default
    
    def _map_legacy_key(self, key_path: str) -> Any:
        """映射旧的键路径到新的 Settings 结构"""
        # 1. 语音模块旧键映射
        if key_path == "voice.tts.enabled" or key_path == "voice.stt.enabled":
            return self._settings.voice.enabled
        if key_path == "voice.tts.engine" or key_path == "voice.stt.engine":
            return self._settings.voice.default_engine
        
        # 2. 模型路径旧键映射
        if key_path == "models.llm.path":
            return self._settings.model.text_path
        if key_path == "models.stable_diffusion.path":
            return self._settings.model.image_gen_path
        if key_path == "models.vision.path":
            return self._settings.model.vision_path
            
        # 3. Config.py 风格的大写键映射 (兼容旧代码)
        # 服务器配置
        if key_path == "SERVER_PORT":
            return self._settings.server.port
        if key_path == "WS_PORT":
            return self._settings.server.ws_port
        if key_path == "WS_HEARTBEAT_INTERVAL":
            return self._settings.server.ws_heartbeat_interval
        if key_path == "WS_TIMEOUT":
            return self._settings.server.ws_timeout
        if key_path == "MAX_CONNECTIONS":
            return self._settings.server.max_connections
            
        # 日志配置
        if key_path == "LOG_LEVEL":
            return self._settings.log.level
        if key_path == "LOG_FILE":
            return self._settings.log.file
            
        # 性能配置
        if key_path == "MAX_REQUESTS_PER_MINUTE":
            return self._settings.server.max_requests_per_minute
        if key_path == "MAX_CONTENT_LENGTH":
            return self._settings.server.max_content_length
            
        # 记忆配置
        if key_path == "DEFAULT_HISTORY_LENGTH":
            return self._settings.memory.default_history_length
        if key_path == "MAX_HISTORY_LENGTH":
            return self._settings.memory.max_history_length
        if key_path == "MEMORY_PRUNING_THRESHOLD":
            return self._settings.memory.memory_pruning_threshold
        if key_path == "LONG_TERM_MEMORY_DB":
            return self._settings.memory.long_term_memory_db
            
        # 模型配置
        if key_path == "DEFAULT_MODEL":
            return self._settings.model.name
        if key_path == "MODEL_PATH":
            return self._settings.model.model_dir
        if key_path == "MODEL_LOAD_MODE":
            return self._settings.model.load_mode
            
        # 语音配置 (大写)
        if key_path == "VOICE_ENABLED":
            return self._settings.voice.enabled
        if key_path == "DEFAULT_VOICE_ENGINE":
            return self._settings.voice.default_engine
        if key_path == "DEFAULT_VOICE":
            return self._settings.voice.default_voice
        if key_path == "DEFAULT_VOICE_SPEED":
            return self._settings.voice.default_speed
            
        # 缓存配置
        if key_path == "CACHE_SIZE":
            return self._settings.cache.size
        if key_path == "CACHE_TTL":
            return self._settings.cache.ttl

        return None

    def set(self, key_path: str, value: Any):
        """
        设置配置值
        注意: 这只会修改内存中的 Settings 实例，不会持久化到文件
        """
        if not self._initialized:
            self.initialize()
            
        keys = key_path.split(".")
        current = self._settings
        
        try:
            # 简化处理：只支持一层或两层属性修改，或者直接修改字典
            # 这是一个简化的实现，对于深层嵌套可能需要更复杂的逻辑
            if len(keys) == 1:
                setattr(self._settings, keys[0], value)
            elif len(keys) == 2:
                sub_obj = getattr(self._settings, keys[0])
                setattr(sub_obj, keys[1], value)
            elif len(keys) == 3:
                sub_obj = getattr(self._settings, keys[0])
                sub_sub_obj = getattr(sub_obj, keys[1])
                setattr(sub_sub_obj, keys[2], value)
            
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
        # Settings 是单例，重新实例化可能需要 hack，这里简单重新 init
        self._initialized = False
        self.initialize()
    
    def get_all_config(self) -> Dict[str, Any]:
        """获取所有配置"""
        if not self._initialized:
            self.initialize()
        return self._settings.model_dump()
    
    def validate_config(self) -> bool:
        """验证配置"""
        return True  # Pydantic 已经在加载时验证了类型

# 全局配置管理器实例
_config_manager_instance = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager_instance
    if _config_manager_instance is None:
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


__all__ = [
    "ConfigManager",
    "get_config_manager",
    "get_config",
    "set_config"
]