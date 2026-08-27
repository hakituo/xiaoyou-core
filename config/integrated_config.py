"""
统一配置系统
从领域子模块聚合所有配置，提供全局单例和向后兼容接口
"""

from typing import Dict, Any
from pathlib import Path
import os
import logging

from dotenv import load_dotenv

from config._base import BaseSettings, Field, SettingsConfigDict

# 领域子模块
from config.settings_server import (
    ServerSettings,
    CacheSettings,
    SystemSettings,
    MonitorSettings,
    UserSettings,
    SecuritySettings,
    PlatformSettings,
)
from config.settings_model import (
    CloudProviderSettings,  # noqa: F401 - re-export
    ModelSettings,
    TextModelSettings,  # noqa: F401 - re-export
    ModelAdapterSettings,
)
from config.settings_chat import (
    ChatPostProcessSettings,  # noqa: F401 - re-export
    ChatRewriteSettings,  # noqa: F401 - re-export
    ChatContextBudgetSettings,  # noqa: F401 - re-export
    ChatContextCompressSettings,  # noqa: F401 - re-export
    ChatRagSettings,  # noqa: F401 - re-export
    ChatSettings,
    VectorSearchSettings,
)
from config.settings_life import (
    DualRoleSettings,
    StudySettings,
    LifeSimulationSettings,
    EmotionSettings,
)
from config.settings_infra import (
    CPPSchedulerConnectionSettings,  # noqa: F401 - re-export
    CPPSchedulerHTTPClientSettings,  # noqa: F401 - re-export
    VTubeStudioSettings,
    SchedulerSettings,
    VoiceSettings,
    DataOpsSettings,
)
from config.settings_core import (
    MemorySettings,
    LogSettings,
    ImmuneSettings,
    AutoHealSettings,
    SelfImprovementSettings,
)
from config.settings_meme import MemeSearchSettings
from config.settings_adapters import TelegramAdapterSettings
from config.debug_config import DebugSettings

# 辅助模块
from config.cache_manager import (
    build_empty_startup_cache,
    load_startup_cache as _load_startup_cache,
    save_startup_cache as _save_startup_cache,
)
from config.model_detector import (
    apply_detected_model_paths as _apply_detected_model_paths,
    auto_detect_models as _auto_detect_models,
    build_model_cache_entry as _build_model_cache_entry,
    get_cached_model_detection as _get_cached_model_detection,
    get_normalize_local_path as _get_normalize_local_path,
)
from config.yaml_loader import (
    apply_yaml_config as _apply_yaml_config_impl,
    build_yaml_cache_entry as _build_yaml_cache_entry,
    get_cached_yaml_config as _get_cached_yaml_config,
    load_resolved_yaml_config_from_disk as _load_resolved_yaml_config_from_disk,
)

load_dotenv()

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

logger = logging.getLogger("config")


def _get_project_root_dir() -> Path:
    """获取项目根目录（委托给 core.utils.common）"""
    from core.utils.common import get_project_root
    return get_project_root()


class AppSettings(BaseSettings):
    """应用配置"""

    # 子配置
    server: ServerSettings = ServerSettings()
    model: ModelSettings = ModelSettings()
    memory: MemorySettings = MemorySettings()
    study: StudySettings = StudySettings()
    voice: VoiceSettings = VoiceSettings()
    cache: CacheSettings = CacheSettings()
    vector_search: VectorSearchSettings = VectorSearchSettings()
    log: LogSettings = LogSettings()
    model_adapter: ModelAdapterSettings = ModelAdapterSettings()
    system: SystemSettings = SystemSettings()
    monitor: MonitorSettings = MonitorSettings()
    chat: ChatSettings = ChatSettings()
    dual_role: DualRoleSettings = DualRoleSettings()
    data_ops: DataOpsSettings = DataOpsSettings()
    immune: ImmuneSettings = ImmuneSettings()
    life_simulation: LifeSimulationSettings = LifeSimulationSettings()
    emotion: EmotionSettings = EmotionSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    vtube: VTubeStudioSettings = VTubeStudioSettings()
    user: UserSettings = UserSettings()
    security: SecuritySettings = SecuritySettings()
    auto_heal: AutoHealSettings = AutoHealSettings()
    self_improvement: SelfImprovementSettings = SelfImprovementSettings()
    platform: PlatformSettings = PlatformSettings()
    debug: DebugSettings = DebugSettings()
    meme_search: MemeSearchSettings = MemeSearchSettings()
    telegram: TelegramAdapterSettings = TelegramAdapterSettings()

    # 应用基本信息
    name: str = Field(default="xiaoyou-core", description="应用名称")
    version: str = Field(default="0.1.0", description="应用版本")
    description: str = Field(
        default="AI Core System for Multi-modal Interaction", description="应用描述"
    )

    # 环境配置
    environment: str = Field(default="development", description="运行环境")
    # 注意：debug 字段已在第 128 行定义为 DebugSettings 类型，
    # 此处不再重复定义 bool 类型的 debug，避免字段名冲突导致 DebugSettings 被覆盖。

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_",
        env_nested_delimiter="__",
        extra="allow",
    )

    def validate(self) -> None:
        """
        验证配置有效性
        Raises:
            ValueError: 当配置无效时抛出
        """
        errors = []

        # 验证模型配置
        if self.model.llm.provider == "local":
            if not self.model.text_path:
                default_path = Path("models/llm/L3-8B-Stheno-v3.2-Q5_K_M.gguf")
                if not default_path.exists():
                    logger.warning(
                        f"Local LLM provider selected but text_path not set and default {default_path} not found."
                    )
            elif not Path(self.model.text_path).exists():
                logger.warning(
                    f"Configured text_path {self.model.text_path} does not exist."
                )

        # 验证目录是否存在
        for name, path_str in [
            ("Model Dir", self.model.model_dir),
            ("Cache Dir", self.model.cache_dir),
            ("History Dir", self.memory.history_dir),
            ("Log Dir", self.log.log_dir),
        ]:
            try:
                p = Path(path_str)
                if not p.exists():
                    logger.info(f"Creating missing directory: {name} at {p}")
                    p.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Failed to create {name} at {path_str}: {e}")

        # 验证 Forge 配置
        if self.model.image.provider == "forge":
            if not self.model.forge_dir:
                errors.append("Forge provider selected but forge_dir is empty.")

        if errors:
            raise ValueError("\n".join(errors))


# 全局配置实例
_settings_instance = None


def _apply_yaml_config(settings: AppSettings, yaml_config: Dict[str, Any]):
    return _apply_yaml_config_impl(
        settings, yaml_config, _get_normalize_local_path()
    )


def reset_settings_cache():
    global _settings_instance
    _settings_instance = None


def get_settings() -> AppSettings:
    """
    获取全局配置实例（单例模式）

    Returns:
        AppSettings: 应用配置实例
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = AppSettings()
        project_root = _get_project_root_dir()
        startup_cache = _load_startup_cache(project_root)
        updated_cache: Dict[str, Any] = build_empty_startup_cache()

        app_yaml_path = project_root / "config" / "yaml" / "app.yaml"
        try:
            yaml_config = _get_cached_yaml_config(app_yaml_path, startup_cache)
            if yaml_config is None and app_yaml_path.exists():
                yaml_config, yaml_text, source_paths = _load_resolved_yaml_config_from_disk(app_yaml_path)
                updated_cache["yaml"] = _build_yaml_cache_entry(
                    app_yaml_path, yaml_config, yaml_text, source_paths
                )
                logger.info(f"Loaded configuration from {app_yaml_path}")
            elif yaml_config is not None:
                updated_cache["yaml"] = startup_cache.get("yaml")

            if isinstance(yaml_config, dict):
                _apply_yaml_config(_settings_instance, yaml_config)
        except Exception as e:
            logger.warning(f"Failed to load app.yaml: {e}")

        # 专用启动器可以在不修改全局 YAML 的前提下，以本地 LLM 模式启动。
        # 必须放在 YAML 应用之后，否则 modeling.yaml 中的 provider 会覆盖它。
        if os.getenv("XIAOYOU_START_LOCAL_LLM", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            _settings_instance.model.llm.provider = "local"
            logger.info("启动器已将默认 LLM provider 覆盖为 local")

        try:
            if os.getenv("XIAOYOU_DISABLE_LOCAL_LLM", "").lower() not in (
                "1",
                "true",
                "yes",
            ):
                detected_paths = _get_cached_model_detection(
                    _settings_instance, startup_cache, project_root
                )
                if detected_paths is None:
                    detected_paths = _auto_detect_models(_settings_instance, project_root)
                    updated_cache["model_detection"] = _build_model_cache_entry(
                        _settings_instance, detected_paths, project_root
                    )
                else:
                    _apply_detected_model_paths(_settings_instance, detected_paths)
                    updated_cache["model_detection"] = startup_cache.get(
                        "model_detection"
                    )
        except Exception as e:
            logger.warning(f"Model auto-detection failed: {e}")

        if updated_cache != startup_cache:
            _save_startup_cache(updated_cache, project_root)
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
            "SHORT_TERM_CAPACITY": lambda: self._settings.memory.short_term_capacity,
            "LONG_TERM_CAPACITY": lambda: self._settings.memory.long_term_capacity,
            # 向后兼容
            "DEFAULT_HISTORY_LENGTH": lambda: self._settings.memory.short_term_capacity,
            "MAX_HISTORY_LENGTH": lambda: self._settings.memory.long_term_capacity,
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
    print(f"短期记忆容量: {settings.memory.short_term_capacity}")
    print(f"长期记忆容量: {settings.memory.long_term_capacity}")
    print(f"默认模型: {settings.model.name}")

    # 测试向后兼容
    print(f"兼容模式 - SERVER_PORT: {config.SERVER_PORT}")
    print(f"兼容模式 - DEFAULT_HISTORY_LENGTH: {config.DEFAULT_HISTORY_LENGTH}")
