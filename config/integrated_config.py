"""
统一配置系统
使用Pydantic v2语法，确保向后兼容性
"""
from typing import Optional, Dict, Any, List
from pathlib import Path
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field
except Exception:
    from pydantic import BaseSettings, Field
    class SettingsConfigDict(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
import logging
import yaml

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('config')


class ServerSettings(BaseSettings):
    """服务器配置"""
    port: int = Field(default=8000, description="服务器端口")
    host: str = Field(default="0.0.0.0", description="服务器主机")
    max_connections: int = Field(default=10, description="最大连接数")
    
    # WebSocket配置
    ws_port: int = Field(default=8765, description="WebSocket服务端口")
    ws_heartbeat_interval: int = Field(default=30, description="心跳间隔（秒）")
    ws_timeout: int = Field(default=60, description="超时时间（秒）")
    
    # 性能配置
    max_requests_per_minute: int = Field(default=60, description="每分钟最大请求数")
    max_ip_requests_per_minute: int = Field(default=30, description="每IP每分钟最大请求数")
    max_content_length: int = Field(default=16 * 1024 * 1024, description="最大内容长度")
    max_upload_image_size: int = Field(default=10 * 1024 * 1024, description="最大上传图片大小(字节)")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_SERVER_",
        extra="allow"
    )


class ModelSettings(BaseSettings):
    """模型配置"""
    model_dir: str = Field(default="models", description="模型目录")
    cache_dir: str = Field(default="cache", description="缓存目录")
    device: str = Field(default="cuda", description="设备类型(cpu/cuda)")
    max_memory: Optional[int] = Field(default=None, description="最大内存使用(MB)")
    name: str = Field(default="qianwen-turbo", description="默认模型名称")
    text_path: Optional[str] = Field(default=None, description="文本模型路径")
    summary_model_path: Optional[str] = Field(default=None, description="摘要/工具模型路径(CPU Offload)")
    vision_path: Optional[str] = Field(default=None, description="视觉模型路径")
    image_gen_path: Optional[str] = Field(default=None, description="图像生成模型路径")
    whisper_path: Optional[str] = Field(default=None, description="Whisper模型路径")
    default_image_model: str = Field(default="chilloutmix_NiPrunedFp32Fix.safetensors", description="默认图像生成模型文件名")
    fallback_image_model: str = Field(default="nsfw_v10.safetensors", description="备用图像生成模型文件名")
    image_gen_width: int = Field(default=512, description="图像生成默认宽度")
    image_gen_height: int = Field(default=512, description="图像生成默认高度")
    image_gen_steps: int = Field(default=20, description="图像生成默认步数")
    image_output_dir: str = Field(default="output/image", description="图像输出目录")
    image_service_url: str = Field(default="ws://localhost:8001", description="图像服务WebSocket地址")
    gpu_enabled: bool = Field(default=True, description="是否启用GPU")
    memory_limit: int = Field(default=16, description="内存限制(GB)")
    load_mode: str = Field(default="local", description="模型加载模式(online/local)")
    local_model_prefix: str = Field(default="./models/", description="本地模型路径前缀")
    
    # 生成参数
    temperature: float = Field(default=1.2, description="生成温度")
    min_p: float = Field(default=0.1, description="Min-P 采样")
    repetition_penalty: float = Field(default=1.15, description="重复惩罚")
    top_p: float = Field(default=1.0, description="Top-P 采样")
    max_new_tokens: int = Field(default=1024, description="最大生成长度")

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MODEL_",
        extra="allow"
    )


class MemorySettings(BaseSettings):
    """内存管理配置"""
    # 对话历史配置
    default_history_length: int = Field(default=10, description="默认历史记录长度")
    max_history_length: int = Field(default=50, description="最大历史记录长度")
    history_dir: str = Field(default="history", description="历史记录存储目录")
    auto_save_interval: int = Field(default=300, description="自动保存间隔(秒)")
    
    # 内存管理配置
    memory_pruning_threshold: float = Field(default=0.3, description="重要性阈值")
    long_term_memory_db: str = Field(default="long_term_memory.db", description="长期记忆数据库文件")
    high_memory_threshold: int = Field(default=70, description="高内存使用率阈值")
    very_high_memory_threshold: int = Field(default=85, description="非常高内存使用率阈值")
    gc_interval: int = Field(default=300, description="垃圾回收间隔")
    slow_response_threshold: float = Field(default=5.0, description="慢响应阈值")
    critical_response_threshold: float = Field(default=10.0, description="严重慢响应阈值")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MEMORY_",
        extra="allow"
    )


class VoiceSettings(BaseSettings):
    """语音配置"""
    enabled: bool = Field(default=True, description="是否启用语音功能")
    default_engine: str = Field(default="local", description="默认语音引擎")
    default_voice: str = Field(default="zh-CN-XiaoxiaoNeural", description="默认语音")
    default_speed: float = Field(default=1.0, description="默认语速")
    gpt_model_path: Optional[str] = Field(default="models/voice/GPT/流萤-e10.ckpt", description="GPT模型路径")
    sovits_model_path: Optional[str] = Field(default="models/voice/SoVITS/Aveline_Violet_Mix.pth", description="SoVITS模型路径")
    reference_audio: Optional[str] = Field(default=None, description="参考音频路径")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_VOICE_",
        extra="allow"
    )


class CacheSettings(BaseSettings):
    """缓存配置"""
    size: int = Field(default=1000, description="LRU缓存大小")
    ttl: int = Field(default=3600, description="缓存过期时间（秒）")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_CACHE_",
        extra="allow"
    )


class LogSettings(BaseSettings):
    """日志配置"""
    level: str = Field(default="INFO", description="日志级别")
    file: str = Field(default="logs/flask_app.log", description="日志文件名")
    error_dir: str = Field(default="logs/errors", description="错误日志目录")
    log_dir: str = Field(default="logs", description="日志目录")
    use_json_format: bool = Field(default=False, description="是否使用JSON格式")
    rotation_type: str = Field(default="size", description="日志轮转类型(size/time)")
    max_bytes: int = Field(default=10 * 1024 * 1024, description="单个日志文件最大大小")
    backup_count: int = Field(default=5, description="保留日志文件数量")
    rotation_when: str = Field(default="midnight", description="时间轮转点")
    rotation_interval: int = Field(default=1, description="时间轮转间隔")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_LOG_",
        extra="allow"
    )


class TextModelSettings(BaseSettings):
    """文本模型配置"""
    text_model_path: Optional[str] = Field(default=None, description="文本模型路径")
    quantization: Optional[Dict[str, Any]] = Field(default=None, description="量化配置")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MODEL_ADAPTER_TEXT_MODEL_",
        extra="allow"
    )


class ModelAdapterSettings(BaseSettings):
    """模型适配器配置"""
    text_model: Optional[TextModelSettings] = TextModelSettings()
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MODEL_ADAPTER_",
        extra="allow"
    )


class SystemSettings(BaseSettings):
    """系统配置"""
    use_local_models_only: bool = Field(default=False, description="是否仅使用本地模型")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_SYSTEM_",
        extra="allow"
    )


class MonitorSettings(BaseSettings):
    """监控配置"""
    cpu_threshold_high: float = Field(default=95.0, description="CPU高负载阈值")
    cpu_threshold_medium: float = Field(default=85.0, description="CPU中负载阈值")
    memory_threshold_high: float = Field(default=90.0, description="内存高负载阈值")
    memory_threshold_medium: float = Field(default=80.0, description="内存中负载阈值")
    gpu_memory_threshold_high: float = Field(default=95.0, description="GPU显存高负载阈值")
    gpu_memory_threshold_medium: float = Field(default=85.0, description="GPU显存中负载阈值")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MONITOR_",
        extra="allow"
    )


class LifeSimulationSettings(BaseSettings):
    """生活模拟配置"""
    enable_spontaneous_reaction: bool = Field(default=False, description="是否启用自发反应")
    idle_threshold: int = Field(default=1800, description="闲置阈值(秒)")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_LIFE_SIMULATION_",
        extra="allow"
    )


class AppSettings(BaseSettings):
    """应用配置"""
    # 子配置
    server: ServerSettings = ServerSettings()
    model: ModelSettings = ModelSettings()
    memory: MemorySettings = MemorySettings()
    voice: VoiceSettings = VoiceSettings()
    cache: CacheSettings = CacheSettings()
    log: LogSettings = LogSettings()
    model_adapter: ModelAdapterSettings = ModelAdapterSettings()
    system: SystemSettings = SystemSettings()
    monitor: MonitorSettings = MonitorSettings()
    life_simulation: LifeSimulationSettings = LifeSimulationSettings()
    
    # 应用基本信息
    name: str = Field(default="xiaoyou-core", description="应用名称")
    version: str = Field(default="0.1.0", description="应用版本")
    description: str = Field(default="AI Core System for Multi-modal Interaction", description="应用描述")
    
    # 环境配置
    environment: str = Field(default="development", description="运行环境")
    debug: bool = Field(default=False, description="调试模式")
    
    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_",
        env_nested_delimiter="__",  # 支持嵌套配置访问
        extra="allow"
    )
# 全局配置实例
_settings_instance = None


def _apply_yaml_config(settings: AppSettings, yaml_config: Dict[str, Any]):
    """
    Apply YAML configuration to settings object
    """
    try:
        # Voice Settings
        if "voice" in yaml_config:
            voice_conf = yaml_config["voice"]
            if isinstance(voice_conf, dict):
                if "enabled" in voice_conf:
                    settings.voice.enabled = voice_conf["enabled"]
                if "default_engine" in voice_conf:
                    settings.voice.default_engine = voice_conf["default_engine"]
                if "default_voice" in voice_conf:
                    settings.voice.default_voice = voice_conf["default_voice"]
                if "default_speed" in voice_conf:
                    settings.voice.default_speed = voice_conf["default_speed"]
                if "gpt_sovits" in voice_conf:
                    gpt_conf = voice_conf["gpt_sovits"]
                    if isinstance(gpt_conf, dict):
                        if "gpt_model_path" in gpt_conf:
                            settings.voice.gpt_model_path = gpt_conf["gpt_model_path"]
                        if "sovits_model_path" in gpt_conf:
                            settings.voice.sovits_model_path = gpt_conf["sovits_model_path"]
        
        # Model Generation Settings
        if "model" in yaml_config and "generation" in yaml_config["model"]:
            gen_conf = yaml_config["model"]["generation"]
            if isinstance(gen_conf, dict):
                if "temperature" in gen_conf:
                    settings.model.temperature = gen_conf["temperature"]
                if "min_p" in gen_conf:
                    settings.model.min_p = gen_conf["min_p"]
                if "repetition_penalty" in gen_conf:
                    settings.model.repetition_penalty = gen_conf["repetition_penalty"]
                if "top_p" in gen_conf:
                    settings.model.top_p = gen_conf["top_p"]
                if "max_new_tokens" in gen_conf:
                    settings.model.max_new_tokens = gen_conf["max_new_tokens"]

        # Server Settings (Partial mapping)
        if "server" in yaml_config:
            server_conf = yaml_config["server"]
            if isinstance(server_conf, dict):
                if "port" in server_conf:
                    settings.server.port = server_conf["port"]
        
        # WebSocket Settings mapping
        if "websocket" in yaml_config:
            ws_conf = yaml_config["websocket"]
            if isinstance(ws_conf, dict):
                if "port" in ws_conf:
                    settings.server.ws_port = ws_conf["port"]
                if "heartbeat_interval" in ws_conf:
                    settings.server.ws_heartbeat_interval = ws_conf["heartbeat_interval"]
                if "timeout" in ws_conf:
                    settings.server.ws_timeout = ws_conf["timeout"]
        
        logger.info("Applied app.yaml configuration overrides")
    except Exception as e:
        logger.warning(f"Error applying yaml config: {e}")


def get_settings() -> AppSettings:
    """
    获取全局配置实例（单例模式）
    
    Returns:
        AppSettings: 应用配置实例
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = AppSettings()
        
        # Try to load app.yaml overrides
        try:
            app_yaml_path = Path("config/yaml/app.yaml")
            if app_yaml_path.exists():
                with open(app_yaml_path, "r", encoding="utf-8") as f:
                    yaml_config = yaml.safe_load(f) or {}
                _apply_yaml_config(_settings_instance, yaml_config)
                logger.info(f"Loaded configuration from {app_yaml_path}")
        except Exception as e:
            logger.warning(f"Failed to load app.yaml: {e}")
            
        logger.info(f"初始化配置系统，环境: {_settings_instance.environment}")
    return _settings_instance


# 为了向后兼容，提供一个类似旧Config类的接口
class Config:
    """向后兼容的配置类"""
    def __init__(self):
        self._settings = get_settings()
    
    def __getattr__(self, name):
        # 旧的配置项名称映射到新的配置系统
        mapping = {
            # 服务器配置
            "SERVER_PORT": lambda: self._settings.server.port,
            "WS_PORT": lambda: self._settings.server.ws_port,
            "WS_HEARTBEAT_INTERVAL": lambda: self._settings.server.ws_heartbeat_interval,
            "WS_TIMEOUT": lambda: self._settings.server.ws_timeout,
            "MAX_CONNECTIONS": lambda: self._settings.server.max_connections,
            
            # 日志配置
            "LOG_LEVEL": lambda: self._settings.log.level,
            "LOG_FILE": lambda: self._settings.log.file,
            
            # 性能配置
            "MAX_REQUESTS_PER_MINUTE": lambda: self._settings.server.max_requests_per_minute,
            "MAX_IP_REQUESTS_PER_MINUTE": lambda: self._settings.server.max_ip_requests_per_minute,
            "MAX_CONTENT_LENGTH": lambda: self._settings.server.max_content_length,
            
            # 对话历史配置
            "DEFAULT_HISTORY_LENGTH": lambda: self._settings.memory.default_history_length,
            "MAX_HISTORY_LENGTH": lambda: self._settings.memory.max_history_length,
            
            # 内存管理配置
            "MEMORY_PRUNING_THRESHOLD": lambda: self._settings.memory.memory_pruning_threshold,
            "LONG_TERM_MEMORY_DB": lambda: self._settings.memory.long_term_memory_db,
            "HIGH_MEMORY_THRESHOLD": lambda: self._settings.memory.high_memory_threshold,
            "VERY_HIGH_MEMORY_THRESHOLD": lambda: self._settings.memory.very_high_memory_threshold,
            "GC_INTERVAL": lambda: self._settings.memory.gc_interval,
            "SLOW_RESPONSE_THRESHOLD": lambda: self._settings.memory.slow_response_threshold,
            "CRITICAL_RESPONSE_THRESHOLD": lambda: self._settings.memory.critical_response_threshold,
            
            # 模型配置
            "DEFAULT_MODEL": lambda: self._settings.model.name,
            "MODEL_PATH": lambda: self._settings.model.model_dir,
            "MODEL_LOAD_MODE": lambda: self._settings.model.load_mode,
            "LOCAL_MODEL_PREFIX": lambda: self._settings.model.local_model_prefix,
            
            # 语音配置
            "VOICE_ENABLED": lambda: self._settings.voice.enabled,
            "DEFAULT_VOICE_ENGINE": lambda: self._settings.voice.default_engine,
            "DEFAULT_VOICE": lambda: self._settings.voice.default_voice,
            "DEFAULT_VOICE_SPEED": lambda: self._settings.voice.default_speed,
            
            # 缓存配置
            "CACHE_SIZE": lambda: self._settings.cache.size,
            "CACHE_TTL": lambda: self._settings.cache.ttl,
        }
        
        if name in mapping:
            return mapping[name]()
        
        # 如果找不到映射，尝试直接从配置中获取
        return getattr(self._settings, name.lower(), None)


# 向后兼容的全局配置实例
config = Config()


if __name__ == "__main__":
    # 测试配置加载
    settings = get_settings()
    print(f"服务器端口: {settings.server.port}")
    print(f"默认历史长度: {settings.memory.default_history_length}")
    print(f"默认模型: {settings.model.name}")
    
    # 测试向后兼容
    print(f"兼容模式 - SERVER_PORT: {config.SERVER_PORT}")
    print(f"兼容模式 - DEFAULT_HISTORY_LENGTH: {config.DEFAULT_HISTORY_LENGTH}")
